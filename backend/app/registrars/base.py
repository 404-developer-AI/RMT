"""Abstract registrar adapter interface + transport-agnostic DTOs.

Mirrors the contract in ARCHITECTURE.md §3.1. Concrete adapters subclass
:class:`RegistrarAdapter` and implement only the methods relevant to their
:class:`RegistrarRole`. Source-only adapters (GoDaddy in V1) leave the
destination methods raising :class:`NotImplementedError`; destination
adapters (Combell in V1) do the inverse. The migration engine inspects
:attr:`RegistrarAdapter.capabilities` and the role flag to dispatch correctly.

Two orthogonal modes shape every call:

* ``dry_run=True`` — reads still hit the live API; writes are no-ops that
  return believable shapes so the UI can preview a migration without
  touching the destination registrar.
* ``mock=True`` — *no* network at all. Reads and writes both return local
  fixture responses. Necessary for CI and for dev machines without
  credentials, since Combell has no sandbox environment.

The flags are independent: ``mock`` implies no network regardless of
``dry_run``; ``dry_run`` alone still talks to the registrar for reads.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


class RegistrarRole(str, enum.Enum):
    SOURCE = "source"
    DESTINATION = "destination"


# --- DTOs -------------------------------------------------------------------
#
# Plain dataclasses, deliberately registrar-agnostic. Adapters translate from
# their own JSON shapes into these on the way out, and from these back into
# the registrar's expected request bodies on the way in.


@dataclass(frozen=True)
class DomainSummary:
    """One row in a domain-list response."""

    name: str
    status: str
    expires_at: datetime | None = None
    locked: bool | None = None
    privacy: bool | None = None


@dataclass(frozen=True)
class Contacts:
    """The four ICANN contact roles. Each block is registrar-shaped JSON."""

    registrant: dict[str, Any]
    admin: dict[str, Any] | None = None
    tech: dict[str, Any] | None = None
    billing: dict[str, Any] | None = None


@dataclass(frozen=True)
class DnsRecord:
    """A single DNS record, normalised across registrars.

    ``data`` holds the type-specific payload exactly as the registrar
    accepts it (e.g. ``"1.2.3.4"`` for an A record, structured priority +
    target for MX). The diff engine compares records on the (type, name,
    data, ttl) tuple.
    """

    type: Literal["A", "AAAA", "CAA", "CNAME", "MX", "TXT", "SRV", "ALIAS", "TLSA", "NS"]
    name: str
    data: str
    ttl: int
    priority: int | None = None


@dataclass(frozen=True)
class DomainDetail:
    """Full per-domain state captured at snapshot time."""

    name: str
    status: str
    nameservers: tuple[str, ...]
    contacts: Contacts
    locked: bool
    transfer_protected: bool
    privacy: bool
    expires_at: datetime | None
    transfer_away_eligible_at: datetime | None
    auth_code: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProvisioningJobRef:
    """Returned by mutating Combell calls — the engine polls until done."""

    job_id: str
    submitted_at: datetime


JobStatusValue = Literal["ongoing", "finished", "failed", "cancelled"]


@dataclass(frozen=True)
class JobStatus:
    """One poll of a provisioning job."""

    job_id: str
    status: JobStatusValue
    polled_at: datetime
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterCapabilities:
    """Per-adapter feature matrix. Surfaced in the UI to hide unsupported actions."""

    can_read_caa: bool = False
    can_read_dnssec: bool = False
    can_export_auth_code: bool = False
    supported_record_types: tuple[str, ...] = ()


# --- Interface --------------------------------------------------------------


class RegistrarAdapter(ABC):
    """Common interface every registrar adapter implements.

    Subclasses declare their :attr:`role` and :attr:`provider` (registry key
    used in ``registrar_credentials.provider`` and in the migration-type
    registry). Construction never performs I/O — adapters are cheap to
    instantiate per request, and :meth:`test_connection` is the only call
    expected to round-trip immediately.
    """

    #: Registry key matching ``registrar_credentials.provider``.
    provider: str
    #: Whether this adapter acts as the source or destination in a migration.
    role: RegistrarRole
    #: Static capability matrix. Concrete adapters override.
    capabilities: AdapterCapabilities = AdapterCapabilities()

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str | None = None,
        api_base: str,
        dry_run: bool = False,
        mock: bool = False,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_base = api_base
        self.dry_run = dry_run
        self.mock = mock

    # --- lifecycle / connectivity ------------------------------------------

    @abstractmethod
    async def test_connection(self) -> bool:
        """Issue a cheap read to verify credentials. Returns True on success.

        Used by the settings page's "Test connection" button. Implementations
        must not raise on an authentication failure — instead return False
        and let the caller render a friendly error.
        """

    # --- source capabilities (GoDaddy in V1) -------------------------------

    async def list_domains(self) -> Sequence[DomainSummary]:
        raise NotImplementedError(f"{type(self).__name__} does not implement list_domains")

    async def get_domain(self, name: str) -> DomainDetail:
        raise NotImplementedError(f"{type(self).__name__} does not implement get_domain")

    async def list_dns_records(self, name: str) -> Sequence[DnsRecord]:
        raise NotImplementedError(f"{type(self).__name__} does not implement list_dns_records")

    async def get_nameservers(self, name: str) -> Sequence[str]:
        raise NotImplementedError(f"{type(self).__name__} does not implement get_nameservers")

    async def get_contacts(self, name: str) -> Contacts:
        raise NotImplementedError(f"{type(self).__name__} does not implement get_contacts")

    async def get_auth_code(self, name: str) -> str | None:
        """Optional. Returns ``None`` when the registrar does not expose one.

        V1 always asks the operator to paste manually; this hook is reserved
        for the V2 "suggestion" UX and for adapters that do expose the code
        (GoDaddy gTLDs).
        """
        return None

    # --- destination capabilities (Combell in V1) --------------------------

    async def request_transfer_in(
        self,
        *,
        name: str,
        auth_code: str,
        registrant: dict[str, Any],
        name_servers: Sequence[str] | None = None,
    ) -> ProvisioningJobRef:
        raise NotImplementedError(
            f"{type(self).__name__} does not implement request_transfer_in"
        )

    async def get_provisioning_job(self, job_id: str) -> JobStatus:
        raise NotImplementedError(
            f"{type(self).__name__} does not implement get_provisioning_job"
        )

    async def create_dns_record(self, name: str, record: DnsRecord) -> None:
        raise NotImplementedError(f"{type(self).__name__} does not implement create_dns_record")

    async def update_dns_record(self, name: str, record: DnsRecord) -> None:
        raise NotImplementedError(f"{type(self).__name__} does not implement update_dns_record")

    async def delete_dns_record(self, name: str, record: DnsRecord) -> None:
        raise NotImplementedError(f"{type(self).__name__} does not implement delete_dns_record")

    async def set_nameservers(self, name: str, nameservers: Sequence[str]) -> None:
        raise NotImplementedError(f"{type(self).__name__} does not implement set_nameservers")
