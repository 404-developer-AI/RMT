"""Snapshot service — capture the full source-registrar state once per migration.

A snapshot is the operator's authoritative backup. It is written once at
migration start via :func:`capture_snapshot` and is never updated. If the
migration is re-run (e.g. after fixing a pre-flight failure), the engine
writes a *new* snapshot row rather than mutating the old one.

The JSON shape stored in ``domain_snapshots.snapshot`` is the registrar's
normalised DTO tree — the dataclass-serialised form of
:class:`DomainDetail` + a list of :class:`DnsRecord`. Storing the
normalised form (rather than the raw registrar JSON) keeps replay trivial:
the engine reads a snapshot and can drive the Combell side without a
second call to GoDaddy.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DomainSnapshot
from app.registrars.base import DnsRecord, DomainDetail


def _serialize_domain_detail(detail: DomainDetail) -> dict[str, Any]:
    """Convert :class:`DomainDetail` into a JSON-safe dict.

    ``asdict`` handles nested dataclasses; we only need to patch datetimes
    to ISO strings.
    """
    raw = asdict(detail)
    for key in ("expires_at", "transfer_away_eligible_at"):
        value = raw.get(key)
        if isinstance(value, datetime):
            raw[key] = value.isoformat()
    # asdict turns a frozen tuple into a list — keep that, JSON-safe.
    return raw


def build_snapshot_payload(
    detail: DomainDetail,
    records: list[DnsRecord],
) -> dict[str, Any]:
    """JSON-safe snapshot body stored on the row + returned to the UI."""
    return {
        "domain": _serialize_domain_detail(detail),
        "records": [asdict(r) for r in records],
    }


async def capture_snapshot(
    session: AsyncSession,
    *,
    migration_plan_id: int | None,
    correlation_id: str,
    domain: str,
    source_provider: str,
    detail: DomainDetail,
    records: list[DnsRecord],
) -> DomainSnapshot:
    """Persist a new snapshot row and return it. Commits the session."""
    payload = build_snapshot_payload(detail, records)
    row = DomainSnapshot(
        migration_plan_id=migration_plan_id,
        correlation_id=correlation_id,
        domain=domain,
        source_provider=source_provider,
        snapshot=payload,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row
