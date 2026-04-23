"""Migration plans — one row per migration attempt."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MigrationState(str, enum.Enum):
    """Lifecycle states. Mirrors the diagram in ARCHITECTURE.md §3.2."""

    DRAFT = "DRAFT"
    PREVIEWED = "PREVIEWED"
    CONFIRMED = "CONFIRMED"
    AWAITING_TRANSFER = "AWAITING_TRANSFER"
    POPULATING_DNS = "POPULATING_DNS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MigrationPlan(Base, TimestampMixin):
    """A single domain's migration attempt across the lifecycle state machine."""

    __tablename__ = "migration_plans"

    id: Mapped[int] = mapped_column(primary_key=True)

    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    domain: Mapped[str] = mapped_column(String(253), nullable=False, index=True)
    migration_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    state: Mapped[MigrationState] = mapped_column(
        Enum(MigrationState, name="migration_state", native_enum=False, length=32),
        nullable=False,
        default=MigrationState.DRAFT,
        index=True,
    )

    diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    provisioning_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
