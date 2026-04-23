"""Source-registrar state captured at migration start — never overwritten."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DomainSnapshot(Base):
    """Full source-registrar state for a single migration attempt.

    This row is the operator's authoritative backup. It is written once at
    migration start and is never updated. Re-runs of the same plan write a
    new snapshot row rather than mutating an existing one.
    """

    __tablename__ = "domain_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)

    migration_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("migration_plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(253), nullable=False, index=True)
    source_provider: Mapped[str] = mapped_column(String(64), nullable=False)

    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
