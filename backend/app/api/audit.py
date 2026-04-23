"""Audit-log viewer API.

Supports filtering by domain, date range, action prefix, and correlation
id, plus a JSON export. CSV export lives here too because it is a trivial
serialisation of the same query result.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit as audit_service
from app.db import get_session
from app.models import AuditEvent

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEventOut(BaseModel):
    id: int
    ts: datetime
    correlation_id: str
    actor: str
    action: str
    target: dict[str, Any]
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    result: str
    duration_ms: int | None
    registrar: str | None


def _to_out(row: AuditEvent) -> AuditEventOut:
    return AuditEventOut(
        id=row.id,
        ts=row.ts,
        correlation_id=row.correlation_id,
        actor=row.actor,
        action=row.action,
        target=row.target,
        before=row.before,
        after=row.after,
        result=row.result,
        duration_ms=row.duration_ms,
        registrar=row.registrar,
    )


@router.get(
    "",
    response_model=list[AuditEventOut],
    summary="List audit events with optional filters",
)
async def list_audit_events(
    session: Annotated[AsyncSession, Depends(get_session)],
    domain: Annotated[str | None, Query()] = None,
    correlation_id: Annotated[str | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    action_prefix: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditEventOut]:
    rows = await audit_service.list_events(
        session,
        domain=domain,
        correlation_id=correlation_id,
        since=since,
        until=until,
        action_prefix=action_prefix,
        limit=limit,
        offset=offset,
    )
    return [_to_out(r) for r in rows]


@router.get(
    "/export.csv",
    summary="Export audit events as CSV (applies the same filters as the list endpoint)",
    response_class=Response,
)
async def export_csv(
    session: Annotated[AsyncSession, Depends(get_session)],
    domain: Annotated[str | None, Query()] = None,
    correlation_id: Annotated[str | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    action_prefix: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=10000)] = 1000,
) -> Response:
    rows = await audit_service.list_events(
        session,
        domain=domain,
        correlation_id=correlation_id,
        since=since,
        until=until,
        action_prefix=action_prefix,
        limit=limit,
        offset=0,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "ts",
            "correlation_id",
            "actor",
            "action",
            "result",
            "duration_ms",
            "registrar",
            "target",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.id,
                r.ts.isoformat(),
                r.correlation_id,
                r.actor,
                r.action,
                r.result,
                r.duration_ms if r.duration_ms is not None else "",
                r.registrar or "",
                r.target,
            ]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="rmt-audit.csv"',
        },
    )
