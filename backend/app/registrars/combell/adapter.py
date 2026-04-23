"""Combell destination adapter.

The adapter talks to the Combell v2 API. Every request is signed by
:class:`app.registrars.combell.signer.CombellSigner` — Combell's HMAC
scheme is non-standard and documented in the signer module.

Endpoints used (all prefixed with ``/v2`` — required by the signer):

* ``GET  /v2/domains``                              — list owned domains
* ``POST /v2/domains/transfers``                    — request transfer-in
* ``GET  /v2/provisioningjobs/{job_id}``            — poll a job
* ``GET  /v2/dns/{domain}/records``                 — list DNS records
* ``POST /v2/dns/{domain}/records``                 — create a DNS record
* ``PUT  /v2/dns/{domain}/records/{record_id}``     — update a record
* ``DELETE /v2/dns/{domain}/records/{record_id}``   — delete a record
* ``PUT  /v2/domains/{domain}/nameservers``         — replace NS list

Two orthogonal modes:
* ``dry_run=True``: reads hit the live API; writes log the intended call
  and return a believable shape so the engine can proceed with a preview.
* ``mock=True``: no network at all. Fixtures live in
  :mod:`app.registrars.combell.fixtures`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from app.logging import get_logger
from app.registrars.base import (
    AdapterCapabilities,
    DnsRecord,
    DomainSummary,
    JobStatus,
    ProvisioningJobRef,
    RegistrarAdapter,
    RegistrarRole,
)
from app.registrars.combell import fixtures
from app.registrars.combell.signer import CombellSigner
from app.registrars.http import RateLimitedClient, RegistrarHTTPError
from app.registrars.registry import register_adapter

logger = get_logger(__name__)


@register_adapter
class CombellAdapter(RegistrarAdapter):
    """Combell destination adapter."""

    provider = "combell"
    role = RegistrarRole.DESTINATION
    capabilities = AdapterCapabilities(
        can_read_caa=True,
        can_read_dnssec=False,
        can_export_auth_code=False,
        supported_record_types=(
            "A", "AAAA", "CAA", "CNAME", "MX", "TXT", "SRV", "ALIAS", "TLSA",
        ),
    )

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str | None = None,
        api_base: str,
        dry_run: bool = False,
        mock: bool = False,
    ) -> None:
        super().__init__(
            api_key=api_key,
            api_secret=api_secret,
            api_base=api_base,
            dry_run=dry_run,
            mock=mock,
        )
        self._client: RateLimitedClient | None = None
        self._signer: CombellSigner | None = None
        if not mock:
            if api_secret is None:
                raise RegistrarHTTPError("Combell requires an api_secret (base64).")
            self._signer = CombellSigner(api_key=api_key, api_secret=api_secret)

    # --- lifecycle --------------------------------------------------------

    def _get_client(self) -> RateLimitedClient:
        if self._client is None:
            self._client = RateLimitedClient(base_url=self.api_base)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def test_connection(self) -> bool:
        """401 from Combell has three common causes — IP not whitelisted,
        wrong api_key, or a bad signature. The generic ``return False`` loses
        that detail, so we raise with Combell's own response body (truncated).
        The credentials endpoint's generic ``except Exception`` then surfaces
        the string in the UI, giving the operator an actionable next step.
        """
        if self.mock:
            return True
        client = self._get_client()
        # Combell signs the path INCLUDING the query string. We therefore
        # compose the full "/v2/domains?take=1" once and use that verbatim
        # for both the signature and the outgoing request — passing params=
        # separately to httpx would re-append a query string that the
        # signature did not cover.
        path_with_query = _compose_path("/v2/domains", {"take": 1})
        headers = self._sign("GET", path_with_query)
        response = await client.request("GET", path_with_query, headers=headers)
        if response.status_code == 200:
            return True
        if response.status_code in (401, 403):
            body = (response.text or "").strip()
            hint = _combell_auth_hint(body)
            detail = f"HTTP {response.status_code}"
            if body:
                detail += f" — {body[:200]}"
            detail += f" ({hint})"
            logger.warning(
                "combell.test_connection.rejected",
                status=response.status_code,
                body_snippet=body[:200],
            )
            raise RegistrarHTTPError(detail, status_code=response.status_code, body=body)
        raise RegistrarHTTPError(
            f"Combell returned HTTP {response.status_code} on test_connection",
            status_code=response.status_code,
            body=response.text,
        )

    # --- signing ----------------------------------------------------------

    def _sign(self, method: str, path: str, body: bytes | None = None) -> dict[str, str]:
        if self._signer is None:
            raise RegistrarHTTPError(
                "Combell signer is not initialised — adapter was constructed in mock mode."
            )
        signed = self._signer.sign(method, path, body)
        headers = {"Authorization": signed.authorization}
        if body is not None:
            headers["Content-Type"] = "application/json"
        return headers

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any | None = None,
        expected_status: tuple[int, ...] = (200, 201, 202, 204),
    ) -> tuple[int, Any]:
        client = self._get_client()
        body_bytes = (
            json.dumps(body, separators=(",", ":")).encode("utf-8")
            if body is not None
            else None
        )
        # Combell signs path + query string together. Compose the full path
        # here and pass it as a single string to both the signer and httpx
        # so the two can never drift apart.
        full_path = _compose_path(path, params)
        headers = self._sign(method, full_path, body_bytes)
        return await client.request_json(
            method,
            full_path,
            headers=headers,
            content=body_bytes,
            expected_status=expected_status,
        )

    # --- reads ------------------------------------------------------------

    async def list_domains(self) -> Sequence[DomainSummary]:
        if self.mock:
            return [
                DomainSummary(name=d["name"], status=d.get("status", "ACTIVE"))
                for d in fixtures.fixture_domains()
            ]
        _, data = await self._request_json("GET", "/v2/domains", params={"take": 500})
        rows = data or []
        return [
            DomainSummary(
                name=row.get("domain_name") or row.get("name"),
                status=str(row.get("status", "ACTIVE")),
            )
            for row in rows
            if (row.get("domain_name") or row.get("name"))
        ]

    async def list_dns_records(self, name: str) -> Sequence[DnsRecord]:
        if self.mock:
            rows = fixtures.fixture_dns_records(name)
        else:
            _, rows = await self._request_json("GET", f"/v2/dns/{name}/records")
            rows = rows or []
        return [
            DnsRecord(
                type=row["type"],
                name=row.get("record_name") or row.get("name", "@"),
                data=str(row.get("content") or row.get("data", "")),
                ttl=int(row.get("ttl", 3600)),
                priority=row.get("priority"),
                id=row.get("id"),
            )
            for row in rows
        ]

    # --- transfers + provisioning ----------------------------------------

    async def request_transfer_in(
        self,
        *,
        name: str,
        auth_code: str,
        registrant: dict[str, Any],
        name_servers: Sequence[str] | None = None,
    ) -> ProvisioningJobRef:
        """Submit an ICANN transfer-in for ``name``.

        When ``name_servers`` is falsy Combell assigns its defaults atomically
        with the transfer — the V1 policy documented in ARCHITECTURE.md §7.
        """
        # Combell's /v2/domains/transfers body (TransferDomain schema,
        # verified against swagger-v2.json):
        #   domain_name, auth_code, name_servers[], registrant
        # Note: the auth_code field is named "auth_code" — NOT transfer_code.
        # Combell rejects an unknown-name field silently and reports
        # "authorization_code_empty", which is the error path the engine hit
        # during the first live attempt.
        body = {
            "domain_name": name,
            "auth_code": auth_code,
            "registrant": registrant,
            "name_servers": list(name_servers) if name_servers else [],
        }
        if self.dry_run:
            logger.info(
                "combell.transfer_in.dry_run",
                domain=name,
                nameservers=body["name_servers"],
            )
            return ProvisioningJobRef(
                job_id=f"dry-run-{name}",
                submitted_at=datetime.now(tz=UTC),
            )
        if self.mock:
            payload = fixtures.fixture_transfer_job()
            return ProvisioningJobRef(
                job_id=str(payload["id"]),
                submitted_at=datetime.now(tz=UTC),
            )
        # Combell returns 202 Accepted with an empty body for async
        # operations; the provisioning-job id lives in the Location header
        # (RFC 7231) pointing at /v2/provisioningjobs/{id}. We go through
        # the raw client here instead of _request_json so we can inspect
        # those headers — parsing the body would just produce ``None``.
        client = self._get_client()
        body_bytes = json.dumps(body, separators=(",", ":")).encode("utf-8")
        path = "/v2/domains/transfers"
        headers = self._sign("POST", path, body_bytes)
        response = await client.request(
            "POST", path, headers=headers, content=body_bytes,
        )
        if response.status_code not in (200, 201, 202):
            raise RegistrarHTTPError(
                f"Combell rejected the transfer request with HTTP "
                f"{response.status_code}: {(response.text or '').strip()[:300]}",
                status_code=response.status_code,
                body=response.text,
            )
        job_id = _extract_job_id(
            location=response.headers.get("Location"),
            body_text=response.text,
        )
        return ProvisioningJobRef(job_id=job_id, submitted_at=datetime.now(tz=UTC))

    async def get_provisioning_job(self, job_id: str) -> JobStatus:
        polled_at = datetime.now(tz=UTC)
        if self.mock:
            row = fixtures.fixture_job_status(job_id)
            return JobStatus(job_id=job_id, status=row["status"], polled_at=polled_at, detail=row)
        if job_id.startswith("dry-run-"):
            return JobStatus(
                job_id=job_id,
                status="finished",
                polled_at=polled_at,
                detail={"dry_run": True},
            )
        _, data = await self._request_json("GET", f"/v2/provisioningjobs/{job_id}")
        raw = (data or {}).get("status", "ongoing")
        return JobStatus(
            job_id=job_id,
            status=_normalise_job_status(str(raw)),
            polled_at=polled_at,
            detail=data or {},
        )

    # --- dns writes -------------------------------------------------------

    async def create_dns_record(self, name: str, record: DnsRecord) -> None:
        body = _record_to_combell_body(record)
        if self.dry_run:
            logger.info("combell.dns.create.dry_run", domain=name, record=asdict(record))
            return
        if self.mock:
            logger.info("combell.dns.create.mock", domain=name, record=asdict(record))
            return
        await self._request_json(
            "POST",
            f"/v2/dns/{name}/records",
            body=body,
            expected_status=(200, 201, 202),
        )

    async def update_dns_record(self, name: str, record: DnsRecord) -> None:
        """Edit an existing record. Uses ``PUT /v2/dns/{name}/records/{id}``.

        If the caller-supplied record does not carry an ``id`` (the engine
        pulls source-side snapshots here after a diff), we look it up in
        the current destination zone by matching ``(type, record_name)``.
        """
        if self.dry_run:
            logger.info("combell.dns.update.dry_run", domain=name, record=asdict(record))
            return
        if self.mock:
            logger.info("combell.dns.update.mock", domain=name, record=asdict(record))
            return
        record_id = record.id or await self._find_record_id(name, record)
        if record_id is None:
            raise RegistrarHTTPError(
                f"Could not find a Combell record id for {record.type} {record.name!r} "
                f"on {name}; cannot update without it."
            )
        body = _record_to_combell_body(record)
        await self._request_json(
            "PUT",
            f"/v2/dns/{name}/records/{record_id}",
            body=body,
            expected_status=(200, 202, 204),
        )

    async def delete_dns_record(self, name: str, record: DnsRecord) -> None:
        """Delete a record by its Combell id.

        Combell's DELETE lives at ``/v2/dns/{domain}/records/{record_id}``.
        The list endpoint only accepts GET/POST, so a filter-based delete
        (``?type=A&record_name=foo``) returns 405. If the passed record
        has no id, resolve one via :meth:`_find_record_id` before firing.
        """
        if self.dry_run:
            logger.info("combell.dns.delete.dry_run", domain=name, record=asdict(record))
            return
        if self.mock:
            logger.info("combell.dns.delete.mock", domain=name, record=asdict(record))
            return
        record_id = record.id or await self._find_record_id(name, record)
        if record_id is None:
            # Nothing at the destination matched — treat as already deleted.
            logger.info(
                "combell.dns.delete.not_found",
                domain=name,
                type=record.type,
                name_=record.name,
            )
            return
        await self._request_json(
            "DELETE",
            f"/v2/dns/{name}/records/{record_id}",
            expected_status=(200, 202, 204),
        )

    async def _find_record_id(self, domain: str, record: DnsRecord) -> str | None:
        """Resolve the destination id of a record by its ``(type, name, content)``.

        Falls back to ``(type, name)`` if nothing matches on content — Combell
        can have at most one record per (type, name) for A/AAAA/CNAME, so
        that pass is still unique for the common case. For TXT / MX this
        may return an arbitrary match, which is acceptable: the engine's
        "replace this record" intent is already satisfied.
        """
        current = await self.list_dns_records(domain)
        for existing in current:
            if (
                existing.type == record.type
                and existing.name == record.name
                and existing.data == record.data
            ):
                return existing.id
        for existing in current:
            if existing.type == record.type and existing.name == record.name:
                return existing.id
        return None

    async def set_nameservers(self, name: str, nameservers: Sequence[str]) -> None:
        body = {"name_servers": list(nameservers)}
        if self.dry_run:
            logger.info("combell.ns.set.dry_run", domain=name, nameservers=list(nameservers))
            return
        if self.mock:
            logger.info("combell.ns.set.mock", domain=name, nameservers=list(nameservers))
            return
        await self._request_json(
            "PUT",
            f"/v2/domains/{name}/nameservers",
            body=body,
            expected_status=(200, 202, 204),
        )


# --- helpers ---------------------------------------------------------------


def _compose_path(path: str, params: dict[str, Any] | None) -> str:
    """Assemble ``path?query`` once, with a deterministic byte sequence.

    Combell's signature covers the full request line after the host, so
    the string we sign MUST equal what we send. We build the query here
    with :func:`urllib.parse.urlencode` and then hand the composed path
    to httpx as-is (no separate ``params=`` argument) — that guarantees
    the bytes in the signed string and on the wire are identical.

    Key order is preserved (``params`` is expected to be a dict, which is
    insertion-ordered in Python 3.7+). Callers that care about a stable
    canonical ordering pass an already-ordered dict.
    """
    if not params:
        return path
    encoded = urlencode(
        [(k, v) for k, v in params.items() if v is not None],
        doseq=True,
    )
    if not encoded:
        return path
    return f"{path}?{encoded}"


def _record_to_combell_body(record: DnsRecord) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": record.type,
        "record_name": record.name,
        "content": record.data,
        "ttl": record.ttl,
    }
    if record.priority is not None:
        body["priority"] = record.priority
    return body


def _extract_job_id(*, location: str | None, body_text: str | None) -> str:
    """Pull a provisioning-job id out of a Combell 202 response.

    Primary source is the ``Location`` header, which for 202-Accepted
    endpoints points at ``/v2/provisioningjobs/{id}`` — that's the
    documented RFC 7231 pattern and it matches Combell's behaviour in
    practice. The body fallback exists for robustness: some older
    deployments return a small JSON document instead, and a mis-configured
    reverse proxy might strip the header entirely.
    """
    if location:
        candidate = location.strip().rstrip("/").rsplit("/", 1)[-1]
        if candidate:
            return candidate
    if body_text:
        try:
            payload = json.loads(body_text)
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            for key in ("id", "provisioning_job_id", "job_id"):
                if isinstance(payload.get(key), str | int):
                    return str(payload[key])
            nested = payload.get("provisioning_job")
            if isinstance(nested, dict) and isinstance(nested.get("id"), str | int):
                return str(nested["id"])
    raise RegistrarHTTPError(
        "Combell response did not contain a provisioning-job id "
        f"(Location header: {location!r}, body: {(body_text or '').strip()[:200]!r})"
    )


def _combell_auth_hint(body: str) -> str:
    """Map Combell's 401/403 body text to a human-readable next action.

    Combell's error strings are not perfectly stable, so we match on
    substrings that have been observed in production responses. When
    nothing matches we return the generic hint which points the operator
    at the whitelist + key pair checklist.
    """
    lowered = body.lower()
    ip_keywords = ("whitelist", "not allowed", "denied")
    if "ip" in lowered and any(k in lowered for k in ip_keywords):
        return "source IP is not whitelisted at Combell — add it under API configuration"
    if "signature" in lowered or "hmac" in lowered:
        return "signature rejected — check that api_secret is pasted exactly as Combell provided it"
    if "unauthorized" in lowered or "invalid key" in lowered or "not found" in lowered:
        return "api_key is unknown to Combell — verify it in the control panel"
    return (
        "check: (1) this host's public IP is whitelisted at Combell, "
        "(2) api_key matches the one in the Combell control panel, "
        "(3) api_secret was pasted exactly (it is already base64)"
    )


def _normalise_job_status(raw: str) -> str:
    lowered = raw.lower()
    if lowered in ("finished", "failed", "cancelled", "canceled", "ongoing"):
        return "cancelled" if lowered == "canceled" else lowered
    if lowered in ("in_progress", "pending", "queued"):
        return "ongoing"
    if lowered in ("error",):
        return "failed"
    return "ongoing"
