"""Audit service — persistent append-only log of migration actions.

:func:`record` is the single entry point. Every state transition and every
outbound registrar API call funnels through it. Secret redaction is applied
to ``before`` / ``after`` / ``target`` *before* the row is built, so the
cipher-text of an API key never ends up in Postgres even if a caller
accidentally passes it in.

The redaction rules mirror :mod:`app.logging` so that operators see the
same treatment in JSON log output and audit rows.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import SENSITIVE_KEY_FRAGMENTS, get_logger
from app.models import AuditEvent

logger = get_logger(__name__)

REDACTED = "***REDACTED***"
# Fields we always strip out of registrant contact blocks before persisting.
_PII_KEYS = {"email", "phone", "fax", "nameFirst", "nameLast", "name_first", "name_last"}


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS)


def _redact(value: Any, *, strip_pii: bool = True) -> Any:
    """Deep-copy-ish scrub of a JSON-serialisable tree.

    * Keys that look like a secret name → value replaced with a marker.
    * PII keys in nested dicts → replaced with a marker (so the diff engine
      can still see "a registrant was recorded" but not its contents).
    """
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if _is_sensitive_key(k) or (strip_pii and k in _PII_KEYS):
                out[k] = REDACTED
            else:
                out[k] = _redact(v, strip_pii=strip_pii)
        return out
    if isinstance(value, list):
        return [_redact(item, strip_pii=strip_pii) for item in value]
    if isinstance(value, tuple):
        return [_redact(item, strip_pii=strip_pii) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


async def record(
    session: AsyncSession,
    *,
    correlation_id: str,
    actor: str,
    action: str,
    target: Mapping[str, Any],
    result: str,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    duration_ms: int | None = None,
    registrar: str | None = None,
) -> AuditEvent:
    """Persist an audit event. Commits the session.

    The caller is expected to pass small, registrar-agnostic dicts — we scrub
    them one more time here as a safety net, then persist.
    """
    row = AuditEvent(
        correlation_id=correlation_id,
        actor=actor,
        action=action,
        target=_redact(dict(target), strip_pii=False),
        before=_redact(dict(before), strip_pii=True) if before is not None else None,
        after=_redact(dict(after), strip_pii=True) if after is not None else None,
        result=result,
        duration_ms=duration_ms,
        registrar=registrar,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info(
        "audit.event",
        correlation_id=correlation_id,
        action=action,
        result=result,
        registrar=registrar,
    )
    return row


async def list_events(
    session: AsyncSession,
    *,
    domain: str | None = None,
    correlation_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    action_prefix: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[AuditEvent]:
    """Return a filtered slice of the audit log, newest first."""
    stmt = select(AuditEvent).order_by(AuditEvent.ts.desc())
    if correlation_id is not None:
        stmt = stmt.where(AuditEvent.correlation_id == correlation_id)
    if since is not None:
        stmt = stmt.where(AuditEvent.ts >= since)
    if until is not None:
        stmt = stmt.where(AuditEvent.ts <= until)
    if action_prefix is not None:
        stmt = stmt.where(AuditEvent.action.startswith(action_prefix))
    if domain is not None:
        # Domain lives inside the JSONB target.domain field.
        stmt = stmt.where(AuditEvent.target["domain"].astext == domain)
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())
