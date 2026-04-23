"""Registrar adapters — common interface in :mod:`app.registrars.base`.

Concrete adapters (GoDaddy, Combell) live in sibling subpackages. Importing
them here is what causes the :func:`register_adapter` decorators to run,
which is how they show up in :func:`registered_providers`.
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

# Import concrete adapters so their @register_adapter decorators execute.
from app.registrars.combell.adapter import CombellAdapter  # noqa: F401
from app.registrars.godaddy.adapter import GoDaddyAdapter  # noqa: F401
from app.registrars.registry import (
    get_adapter_class,
    register_adapter,
    registered_providers,
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
    "get_adapter_class",
    "register_adapter",
    "registered_providers",
]
