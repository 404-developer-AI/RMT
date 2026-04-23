"""Append-only audit log — one row per state transition or registrar call."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditEvent(Base):
    """Structured audit row matching ARCHITECTURE.md §3.4.

    Every migration state transition and every outbound registrar API call
    emits one of these. Secret redaction happens before the row is built —
    callers must not pass plaintext credentials in ``before`` / ``after``.
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)

    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    target: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    result: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    registrar: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
