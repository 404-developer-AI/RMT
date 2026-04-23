"""GoDaddy read-only adapter implementation.

The adapter uses GoDaddy's v1 public API. All endpoints used here are
generally available to non-reseller accounts:

* ``GET /v1/domains``                    — list owned domains
* ``GET /v1/domains/{domain}``           — domain detail (locks, contacts, authCode, …)
* ``GET /v1/domains/{domain}/records``   — DNS records

Authentication is a single static header:

    Authorization: sso-key {api_key}:{api_secret}

Two orthogonal modes are respected:

* ``dry_run=True``: reads still hit the live API; writes no-op. GoDaddy is
  source-only in V1 so this degenerates to "reads as usual" — kept for
  uniformity with the interface.
* ``mock=True``: no network at all. Returns local fixtures from
  :mod:`app.registrars.godaddy.fixtures` so CI and dev machines without
  credentials can exercise the full migration flow.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.registrars.base import (
    AdapterCapabilities,
    Contacts,
    DnsRecord,
    DomainDetail,
    DomainSummary,
    RegistrarAdapter,
    RegistrarRole,
)
from app.registrars.godaddy import fixtures
from app.registrars.http import RateLimitedClient, RegistrarHTTPError
from app.registrars.registry import register_adapter


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@register_adapter
class GoDaddyAdapter(RegistrarAdapter):
    """GoDaddy source adapter. Read-only methods only."""

    provider = "godaddy"
    role = RegistrarRole.SOURCE
    capabilities = AdapterCapabilities(
        can_read_caa=False,
        can_read_dnssec=False,
        can_export_auth_code=True,
        supported_record_types=("A", "AAAA", "CNAME", "MX", "TXT", "SRV", "NS"),
    )

    _REQUESTS_PER_MINUTE = 60  # GoDaddy's documented soft cap per endpoint

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

    # --- lifecycle --------------------------------------------------------

    def _get_client(self) -> RateLimitedClient:
        if self._client is None:
            if self.api_secret is None:
                raise RegistrarHTTPError(
                    "GoDaddy requires an api_secret — paired with api_key in the sso-key header."
                )
            headers = {
                "Authorization": f"sso-key {self.api_key}:{self.api_secret}",
            }
            self._client = RateLimitedClient(
                base_url=self.api_base,
                headers=headers,
                requests_per_minute=self._REQUESTS_PER_MINUTE,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def test_connection(self) -> bool:
        """Cheap read: list up to one domain.

        Returns ``True`` on 2xx, ``False`` on 401/403. Any other outcome
        propagates as an exception so the caller can surface a useful
        error in the settings page.
        """
        if self.mock:
            return True
        client = self._get_client()
        response = await client.request("GET", "/v1/domains", params={"limit": 1})
        if response.status_code in (401, 403):
            return False
        if response.status_code >= 400:
            raise RegistrarHTTPError(
                f"GoDaddy returned {response.status_code} on test_connection",
                status_code=response.status_code,
                body=response.text,
            )
        return True

    # --- reads ------------------------------------------------------------

    async def list_domains(self) -> Sequence[DomainSummary]:
        if self.mock:
            rows = fixtures.fixture_domains()
        else:
            client = self._get_client()
            _, data = await client.request_json("GET", "/v1/domains", params={"limit": 500})
            rows = data or []
        return [self._to_summary(row) for row in rows]

    async def get_domain(self, name: str) -> DomainDetail:
        if self.mock:
            row = fixtures.fixture_domain_detail(name)
        else:
            client = self._get_client()
            _, row = await client.request_json("GET", f"/v1/domains/{name}")
        return self._to_detail(row)

    async def list_dns_records(self, name: str) -> Sequence[DnsRecord]:
        if self.mock:
            rows = fixtures.fixture_dns_records(name)
        else:
            client = self._get_client()
            _, rows = await client.request_json("GET", f"/v1/domains/{name}/records")
            rows = rows or []
        return [self._to_record(row) for row in rows]

    async def get_nameservers(self, name: str) -> Sequence[str]:
        detail = await self.get_domain(name)
        return tuple(detail.nameservers)

    async def get_contacts(self, name: str) -> Contacts:
        detail = await self.get_domain(name)
        return detail.contacts

    async def get_auth_code(self, name: str) -> str | None:
        """Read the ``authCode`` field from ``GET /v1/domains/{domain}``.

        V1 always asks the operator to paste manually; this method exists
        so the V2 "suggestion" UX has a working hook without extra plumbing.
        """
        if self.mock:
            detail = fixtures.fixture_domain_detail(name)
            return detail.get("authCode")
        client = self._get_client()
        _, row = await client.request_json("GET", f"/v1/domains/{name}")
        value = (row or {}).get("authCode")
        return value if isinstance(value, str) and value else None

    # --- translators ------------------------------------------------------

    @staticmethod
    def _to_summary(row: dict[str, Any]) -> DomainSummary:
        return DomainSummary(
            name=row["domain"],
            status=str(row.get("status", "UNKNOWN")),
            expires_at=_parse_iso(row.get("expires")),
            locked=row.get("locked"),
            privacy=row.get("privacy"),
        )

    @staticmethod
    def _to_detail(row: dict[str, Any]) -> DomainDetail:
        # GoDaddy v1 puts the four contact roles at the top level of the
        # /v1/domains/{domain} response — ``contactRegistrant``,
        # ``contactAdmin``, ``contactTech``, ``contactBilling``. A nested
        # ``contacts`` wrapper is accepted too as a defensive fallback so
        # fixtures that follow the older shape still parse correctly.
        nested = row.get("contacts")
        source: dict[str, Any] = nested if isinstance(nested, dict) else row
        contacts = Contacts(
            registrant=source.get("contactRegistrant") or {},
            admin=source.get("contactAdmin"),
            tech=source.get("contactTech"),
            billing=source.get("contactBilling"),
        )
        return DomainDetail(
            name=row["domain"],
            status=str(row.get("status", "UNKNOWN")),
            nameservers=tuple(row.get("nameServers") or ()),
            contacts=contacts,
            locked=bool(row.get("locked", False)),
            transfer_protected=bool(
                row.get("transferProtected", row.get("locked", False))
            ),
            privacy=bool(row.get("privacy", False)),
            expires_at=_parse_iso(row.get("expires")),
            transfer_away_eligible_at=_parse_iso(row.get("transferAwayEligibleAt")),
            auth_code=row.get("authCode") or None,
            extra={k: v for k, v in row.items() if k not in _KNOWN_DETAIL_KEYS},
        )

    @staticmethod
    def _to_record(row: dict[str, Any]) -> DnsRecord:
        return DnsRecord(
            type=row["type"],
            name=row.get("name", "@"),
            data=str(row.get("data", "")),
            ttl=int(row.get("ttl", 3600)),
            priority=row.get("priority"),
        )


_KNOWN_DETAIL_KEYS = {
    "domain",
    "status",
    "nameServers",
    "contacts",
    "locked",
    "transferProtected",
    "privacy",
    "expires",
    "transferAwayEligibleAt",
    "authCode",
}
