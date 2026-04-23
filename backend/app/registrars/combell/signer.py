"""Combell HMAC-SHA256 request signer.

Combell signs every API call with a custom HMAC-SHA256 scheme. The string
that gets signed is the concatenation of:

    apikey + method.lower()
           + percent_encoded_uppercase_path
           + unix_timestamp
           + nonce
           + content

where ``content`` is ``base64(MD5(body))`` for requests that carry a body
and the empty string otherwise. The signature is the base64-encoded
HMAC-SHA256 of that concatenation, keyed with the *base64-decoded* api
secret (Combell's control panel exposes the secret already base64-encoded;
we decode once at construction). The resulting Authorization header is:

    Authorization: hmac {apikey}:{signature}:{nonce}:{timestamp}

Two non-obvious bits of the spec:

* The path includes everything from ``/v2`` onward — including any query
  string. ``?``, ``=`` and ``&`` therefore get percent-encoded along with
  the slashes.
* Percent-encoding uses **uppercase** hex (``%2F``, not ``%2f``). Python's
  :func:`urllib.parse.quote` emits lowercase hex, so we post-process the
  escape sequences. We deliberately uppercase only the ``%xx`` triplets,
  not the surrounding unreserved characters which must stay verbatim.

The signer is deliberately stateless beyond holding the credentials so it
is cheap to construct per adapter instance and trivially safe to share
across coroutines. It performs no I/O.

IP whitelisting is enforced by Combell on top of HMAC — a perfectly-signed
request from a non-whitelisted source IP still fails. That is an
operational concern outside this module (see ARCHITECTURE.md §4).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass
from urllib.parse import quote

# Pre-compiled: Python's quote() emits lowercase hex; we uppercase the
# escape triplets only so unreserved characters stay verbatim.
_PERCENT_ESCAPE_RE = re.compile(r"%[0-9a-fA-F]{2}")


def _percent_encode_uppercase(path: str) -> str:
    """Percent-encode ``path`` with uppercase hex, encoding everything but unreserved."""
    encoded = quote(path, safe="")
    return _PERCENT_ESCAPE_RE.sub(lambda m: m.group(0).upper(), encoded)


def _content_hash(body: bytes | None) -> str:
    """Combell's ``content`` field: ``base64(MD5(body))`` or empty when no body.

    MD5 is mandated by the protocol — it is not used here as a security
    primitive (the HMAC-SHA256 around it provides the integrity guarantee),
    so ``usedforsecurity=False`` keeps Bandit and FIPS-style linters quiet.
    """
    if not body:
        return ""
    digest = hashlib.md5(body, usedforsecurity=False).digest()
    return base64.b64encode(digest).decode("ascii")


@dataclass(frozen=True)
class SignedRequest:
    """Result of signing a single outbound request.

    The component fields (``timestamp``, ``nonce``, ``content``) are exposed
    alongside the assembled header so callers and tests can inspect what was
    actually signed without re-running the signer.
    """

    authorization: str
    timestamp: str
    nonce: str
    content: str


class CombellSigner:
    """Compute the ``Authorization`` header for a Combell API request.

    Construct once per credential pair and call :meth:`sign` per outbound
    request — the timestamp and nonce are generated fresh on each call.
    """

    def __init__(self, *, api_key: str, api_secret: str) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if not api_secret:
            raise ValueError("api_secret is required")
        self._api_key = api_key
        # Combell distributes the secret as base64; the HMAC key is its
        # decoded byte string. Validate strictly so a paste error fails
        # loudly at construction instead of producing silent bad signatures.
        try:
            self._secret_bytes = base64.b64decode(api_secret, validate=True)
        except binascii.Error as exc:
            raise ValueError("api_secret is not valid base64") from exc

    def sign(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        *,
        timestamp: str | None = None,
        nonce: str | None = None,
    ) -> SignedRequest:
        """Sign one request and return its :class:`SignedRequest`.

        ``timestamp`` and ``nonce`` are dependency-injection seams for tests;
        production callers leave them ``None`` to get a fresh unix timestamp
        and a 128-bit cryptographic nonce respectively.
        """
        ts = timestamp if timestamp is not None else str(int(time.time()))
        n = nonce if nonce is not None else secrets.token_hex(16)
        content = _content_hash(body)

        encoded_path = _percent_encode_uppercase(path)
        string_to_sign = (
            self._api_key + method.lower() + encoded_path + ts + n + content
        )

        digest = hmac.new(
            self._secret_bytes,
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        signature = base64.b64encode(digest).decode("ascii")

        return SignedRequest(
            authorization=f"hmac {self._api_key}:{signature}:{n}:{ts}",
            timestamp=ts,
            nonce=n,
            content=content,
        )
