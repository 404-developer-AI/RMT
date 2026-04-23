"""Rate-limit aware HTTP client shared by concrete adapters.

Two registrars, two rate-limit dialects, one client:

* **Combell** returns ``X-RateLimit-Remaining`` / ``X-RateLimit-Reset`` on
  every response and ``429 Too Many Requests`` with ``Retry-After`` when
  the window is exhausted. We honour ``Retry-After`` as a hard sleep and
  preemptively pause when ``Remaining`` hits zero to avoid a round-trip
  rejection.
* **GoDaddy** does not document its per-endpoint limits but caps roughly at
  60 requests per minute per endpoint. We throttle per-endpoint on the
  client side and also react to ``Retry-After`` on 429 as a belt-and-braces.

The client is intentionally stateless beyond the ``httpx.AsyncClient`` it
wraps and a small in-memory bucket dict, so it is trivially safe to share
across coroutines within one adapter instance.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from app.logging import get_logger

logger = get_logger(__name__)


class RegistrarHTTPError(RuntimeError):
    """Base class for registrar-HTTP failures surfaced to the engine."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass
class _Bucket:
    """Per-endpoint token bucket used for pre-emptive throttling.

    ``tokens`` is a float so we can refill fractionally and issue partial
    requests smoothly. Access from multiple coroutines is serialised through
    :attr:`lock`.
    """

    capacity: float
    tokens: float
    fill_per_sec: float
    updated_at: float
    lock: asyncio.Lock


class RateLimitedClient:
    """Wraps ``httpx.AsyncClient`` with 429 handling + per-endpoint throttle.

    Parameters
    ----------
    base_url:
        Base URL of the registrar — full paths are given to ``request``.
    headers:
        Static headers (auth is signed per-call by the adapter, so auth lives
        in the per-request headers, not here).
    requests_per_minute:
        Client-side cap. ``None`` disables proactive throttling; the server's
        429 / ``Retry-After`` response remains the authoritative signal.
    timeout:
        httpx timeout in seconds applied to every request.
    max_retries:
        How many times to retry on 429 / 503 before giving up.
    """

    def __init__(
        self,
        *,
        base_url: str,
        headers: Mapping[str, str] | None = None,
        requests_per_minute: int | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Accept": "application/json", **(dict(headers) if headers else {})},
            timeout=timeout,
        )
        self._rpm = requests_per_minute
        self._max_retries = max_retries
        self._buckets: dict[str, _Bucket] = {}
        self._buckets_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> RateLimitedClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # --- throttle bookkeeping ---------------------------------------------

    async def _throttle(self, bucket_key: str) -> None:
        """Wait until a token is available for ``bucket_key``.

        Runs before every request. When ``requests_per_minute`` is ``None``
        this is a zero-cost no-op.
        """
        if self._rpm is None:
            return
        async with self._buckets_lock:
            bucket = self._buckets.get(bucket_key)
            if bucket is None:
                bucket = _Bucket(
                    capacity=float(self._rpm),
                    tokens=float(self._rpm),
                    fill_per_sec=self._rpm / 60.0,
                    updated_at=time.monotonic(),
                    lock=asyncio.Lock(),
                )
                self._buckets[bucket_key] = bucket
        async with bucket.lock:
            now = time.monotonic()
            elapsed = now - bucket.updated_at
            bucket.tokens = min(bucket.capacity, bucket.tokens + elapsed * bucket.fill_per_sec)
            bucket.updated_at = now
            if bucket.tokens < 1.0:
                wait_for = (1.0 - bucket.tokens) / bucket.fill_per_sec
                await asyncio.sleep(wait_for)
                bucket.tokens = 0.0
                bucket.updated_at = time.monotonic()
            else:
                bucket.tokens -= 1.0

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float:
        """Interpret ``Retry-After`` as a float seconds value.

        Combell and GoDaddy both send integer seconds; we still accept an
        HTTP-date for completeness. Missing / unparsable falls back to 1 s
        so we always back off at least a little.
        """
        header = response.headers.get("Retry-After")
        if not header:
            return 1.0
        try:
            return max(0.5, float(header))
        except ValueError:
            try:
                from email.utils import parsedate_to_datetime

                target = parsedate_to_datetime(header)
            except (TypeError, ValueError):
                return 1.0
            return max(0.5, target.timestamp() - time.time())

    # --- request ----------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        bucket_key: str | None = None,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        """Send a request and return the raw ``httpx.Response``.

        Retries on 429 and 503 up to ``max_retries`` times, honouring
        ``Retry-After``. Non-retryable errors (4xx other than 429, 5xx other
        than 503) are returned as-is — the adapter decides whether to treat
        them as errors.
        """
        key = bucket_key or path
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            await self._throttle(key)
            try:
                response = await self._client.request(
                    method,
                    path,
                    headers=dict(headers) if headers else None,
                    params=dict(params) if params else None,
                    json=json,
                    content=content,
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt >= self._max_retries:
                    raise RegistrarHTTPError(
                        f"HTTP request failed after {attempt + 1} attempts: {exc}",
                    ) from exc
                await asyncio.sleep(min(2.0 ** attempt, 30.0))
                continue

            if response.status_code in (429, 503) and attempt < self._max_retries:
                wait_for = self._retry_after_seconds(response)
                logger.info(
                    "registrar.http.retry",
                    method=method,
                    path=path,
                    status=response.status_code,
                    attempt=attempt,
                    wait_s=round(wait_for, 2),
                )
                await asyncio.sleep(wait_for)
                continue

            # Honour X-RateLimit-Remaining: when Combell says we have zero
            # tokens left, pause until the reset so the next call does not
            # have to retry.
            remaining = response.headers.get("X-RateLimit-Remaining")
            reset = response.headers.get("X-RateLimit-Reset")
            if remaining == "0" and reset:
                try:
                    reset_s = max(0.0, float(reset) - time.time())
                    if reset_s > 0:
                        logger.debug(
                            "registrar.http.preempt_pause",
                            reset_s=round(reset_s, 2),
                        )
                        await asyncio.sleep(min(reset_s, 10.0))
                except ValueError:
                    pass

            return response

        raise RegistrarHTTPError(
            f"HTTP request failed after retries: {last_exc}",
        ) from last_exc

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        bucket_key: str | None = None,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        content: bytes | None = None,
        expected_status: tuple[int, ...] = (200, 201, 202, 204),
    ) -> tuple[int, Any]:
        """Convenience wrapper that parses JSON and raises on unexpected status.

        Returns ``(status_code, parsed_json_or_none)``. ``204 No Content``
        returns an empty dict so call sites don't have to special-case it.
        """
        response = await self.request(
            method,
            path,
            bucket_key=bucket_key,
            headers=headers,
            params=params,
            json=json,
            content=content,
        )
        if response.status_code not in expected_status:
            raise RegistrarHTTPError(
                f"Unexpected status {response.status_code} for {method} {path}",
                status_code=response.status_code,
                body=response.text,
            )
        if response.status_code == 204 or not response.content:
            return response.status_code, None
        try:
            return response.status_code, response.json()
        except ValueError as exc:
            raise RegistrarHTTPError(
                f"Registrar returned non-JSON body: {response.text[:200]!r}",
                status_code=response.status_code,
                body=response.text,
            ) from exc
