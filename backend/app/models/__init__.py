"""SQLAlchemy ORM models.

Import every model module here so Alembic's autogenerate sees them.
"""

from app.models.audit import AuditEvent
from app.models.base import Base, TimestampMixin
from app.models.credentials import RegistrarCredential
from app.models.migration import MigrationPlan, MigrationState
from app.models.snapshot import DomainSnapshot

__all__ = [
    "AuditEvent",
    "Base",
    "DomainSnapshot",
    "MigrationPlan",
    "MigrationState",
    "RegistrarCredential",
    "TimestampMixin",
]
