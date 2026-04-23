"""Registrar adapters — common interface in :mod:`app.registrars.base`.

Concrete adapters (GoDaddy, Combell, …) live in sibling modules. Version 1
ships only the abstract interface plus the migration registry; concrete
adapters land in their own follow-up PRs.
"""

from app.registrars.base import (
    AdapterCapabilities,
    Contacts,
    DnsRecord,
    DomainDetail,
    DomainSummary,
    JobStatus,
    ProvisioningJobRef,
    RegistrarAdapter,
    RegistrarRole,
)

__all__ = [
    "AdapterCapabilities",
    "Contacts",
    "DnsRecord",
    "DomainDetail",
    "DomainSummary",
    "JobStatus",
    "ProvisioningJobRef",
    "RegistrarAdapter",
    "RegistrarRole",
]
