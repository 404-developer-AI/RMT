"""Migration engine — orchestrates the lifecycle state machine.

The engine is a thin coordinator. Each public method corresponds to one
operator action (preview, confirm, poll) or to one background tick
(polling). Actual registrar I/O lives in the adapters; persistence is done
via SQLAlchemy; audit writes go through :mod:`app.audit`.

State diagram (repeated from ARCHITECTURE.md §3.2):

    DRAFT → PREVIEWED → CONFIRMED → AWAITING_TRANSFER → POPULATING_DNS → COMPLETED
                                   └→ FAILED / CANCELLED can fire at any step.

Re-running the same plan after a failure is safe: the engine checks
whether the state machine has already advanced and skips the redundant
work, preserving the "idempotent operations" principle from CLAUDE.md.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.logging import get_logger
from app.migrations.diff import ZoneDiff, compute_diff, serialize_diff
from app.migrations.preflight import run_preflight, serialize_report
from app.migrations.registry import get_migration_type
from app.migrations.snapshot import build_snapshot_payload, capture_snapshot
from app.migrations.translators import translate_registrant
from app.models import DomainSnapshot, MigrationPlan, MigrationState
from app.registrars.base import DnsRecord, RegistrarAdapter

logger = get_logger(__name__)


class MigrationEngineError(RuntimeError):
    """Raised for domain-level failures the API should surface as 4xx/5xx."""


class IllegalTransitionError(MigrationEngineError):
    """Raised when an action does not match the current plan state."""


# --- helpers ---------------------------------------------------------------


def new_correlation_id() -> str:
    """``mig_`` + 22 url-safe chars — compact, sortable within the same second."""
    return f"mig_{secrets.token_urlsafe(16)[:22]}"


def _registrant_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Pull the registrant block out of a serialized snapshot."""
    domain = snapshot.get("domain") or {}
    contacts = domain.get("contacts") or {}
    registrant = contacts.get("registrant") or {}
    if isinstance(registrant, dict):
        return registrant
    return {}


# --- public API ------------------------------------------------------------


async def create_plan(
    session: AsyncSession,
    *,
    domain: str,
    migration_type: str,
    actor: str = "operator",
) -> MigrationPlan:
    """Insert a DRAFT plan. Does no registrar I/O."""
    get_migration_type(migration_type)  # raises on unknown key
    row = MigrationPlan(
        correlation_id=new_correlation_id(),
        domain=domain,
        migration_type=migration_type,
        state=MigrationState.DRAFT,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    await audit.record(
        session,
        correlation_id=row.correlation_id,
        actor=actor,
        action="migration.created",
        target={"domain": domain, "migration_type": migration_type},
        result="success",
    )
    return row


async def preview_plan(
    session: AsyncSession,
    plan: MigrationPlan,
    *,
    source: RegistrarAdapter,
    destination: RegistrarAdapter,
    actor: str = "operator",
) -> tuple[MigrationPlan, DomainSnapshot, dict[str, Any], ZoneDiff]:
    """Snapshot + pre-flight + zone diff. Transitions DRAFT → PREVIEWED.

    Safe to call repeatedly: every preview writes a fresh snapshot row. The
    engine returns the latest snapshot + rendered report so the API can
    hand the frontend everything the wizard needs in one shot.
    """
    if plan.state not in (MigrationState.DRAFT, MigrationState.PREVIEWED):
        raise IllegalTransitionError(
            f"Cannot preview a plan in state {plan.state.value}."
        )

    started = time.perf_counter()
    detail = await source.get_domain(plan.domain)
    records = list(await source.list_dns_records(plan.domain))

    snapshot_row = await capture_snapshot(
        session,
        migration_plan_id=plan.id,
        correlation_id=plan.correlation_id,
        domain=plan.domain,
        source_provider=source.provider,
        detail=detail,
        records=records,
    )

    report = run_preflight(detail, records)
    report_dict = serialize_report(report)

    # Compute a preview diff against what's currently at Combell. For a
    # pre-transfer zone that usually returns an empty list, so the diff
    # will list every source record as "to_create".
    destination_records: list[DnsRecord] = []
    try:
        destination_records = list(await destination.list_dns_records(plan.domain))
    except Exception:
        # If Combell does not own the domain yet, listing will 404/etc —
        # treat as an empty zone for preview purposes.
        destination_records = []

    diff = compute_diff(
        source_records=records,
        destination_records=destination_records,
        supported_types=destination.capabilities.supported_record_types,
    )

    plan.state = MigrationState.PREVIEWED
    plan.diff = {
        "preflight": report_dict,
        "zone_diff": serialize_diff(diff),
        "snapshot_id": snapshot_row.id,
    }
    await session.commit()
    await session.refresh(plan)

    duration_ms = int((time.perf_counter() - started) * 1000)
    await audit.record(
        session,
        correlation_id=plan.correlation_id,
        actor=actor,
        action="migration.previewed",
        target={"domain": plan.domain, "snapshot_id": snapshot_row.id},
        after={"state": plan.state.value, "preflight": report_dict, "diff_summary": diff.summary()},
        result="success",
        duration_ms=duration_ms,
        registrar=source.provider,
    )
    return plan, snapshot_row, report_dict, diff


async def confirm_and_submit(
    session: AsyncSession,
    plan: MigrationPlan,
    *,
    source: RegistrarAdapter,
    destination: RegistrarAdapter,
    auth_code: str,
    typed_domain: str,
    actor: str = "operator",
) -> MigrationPlan:
    """Submit the transfer request to Combell.

    Requires the plan to be PREVIEWED with a passing pre-flight report. The
    ``typed_domain`` guard matches the one the UI shows — an extra
    belt-and-braces in case a caller bypasses the frontend.
    """
    if plan.state != MigrationState.PREVIEWED:
        raise IllegalTransitionError(
            f"Cannot confirm a plan in state {plan.state.value}; expected PREVIEWED."
        )
    if typed_domain.strip().lower() != plan.domain.lower():
        raise MigrationEngineError(
            "Typed domain does not match the plan's domain — confirmation rejected."
        )
    auth_code = auth_code.strip()
    if not auth_code:
        raise MigrationEngineError("Auth code is required.")

    preflight = (plan.diff or {}).get("preflight") or {}
    if not preflight.get("passed", False):
        raise MigrationEngineError(
            "Pre-flight checks have not passed — resolve blocking issues before confirming."
        )

    snapshot = await _load_latest_snapshot(session, plan)
    if snapshot is None:
        raise MigrationEngineError("No snapshot exists for this plan — preview it first.")
    raw_registrant = _registrant_from_snapshot(snapshot.snapshot)
    # Translate between registrar shapes (GoDaddy nameFirst / addressMailing.*
    # vs Combell first_name / postal_code / country_code). The dispatcher
    # returns the raw dict unchanged when no translator is registered for
    # this migration type, so future pairs can opt in without engine edits.
    registrant = translate_registrant(plan.migration_type, raw_registrant)

    started = time.perf_counter()
    _ = source  # not used during confirm, but kept in the signature for symmetry
    job = await destination.request_transfer_in(
        name=plan.domain,
        auth_code=auth_code,
        registrant=registrant,
        name_servers=[],
    )
    duration_ms = int((time.perf_counter() - started) * 1000)

    plan.state = MigrationState.AWAITING_TRANSFER
    plan.provisioning_job_id = job.job_id
    plan.confirmed_at = datetime.now(tz=UTC)
    await session.commit()
    await session.refresh(plan)

    # Intentionally redacted — audit.record strips the auth_code as soon as
    # it sees a "secret"-looking key. The target still lets operators see
    # WHICH domain was confirmed at what time.
    await audit.record(
        session,
        correlation_id=plan.correlation_id,
        actor=actor,
        action="migration.confirmed",
        target={"domain": plan.domain, "provisioning_job_id": job.job_id},
        after={
            "state": plan.state.value,
            "auth_code_token": "***REDACTED***",
            "confirmed_at": plan.confirmed_at.isoformat(),
        },
        result="success",
        duration_ms=duration_ms,
        registrar=destination.provider,
    )
    return plan


async def poll_transfer(
    session: AsyncSession,
    plan: MigrationPlan,
    *,
    destination: RegistrarAdapter,
    actor: str = "poller",
) -> MigrationPlan:
    """Single poll tick. Idempotent. Advances state when the job finishes."""
    if plan.state != MigrationState.AWAITING_TRANSFER:
        return plan
    if not plan.provisioning_job_id:
        raise MigrationEngineError("Plan is awaiting transfer but has no provisioning_job_id.")

    started = time.perf_counter()
    status = await destination.get_provisioning_job(plan.provisioning_job_id)
    duration_ms = int((time.perf_counter() - started) * 1000)

    plan.last_polled_at = status.polled_at
    await session.commit()

    await audit.record(
        session,
        correlation_id=plan.correlation_id,
        actor=actor,
        action="migration.poll",
        target={"domain": plan.domain, "provisioning_job_id": status.job_id},
        after={"status": status.status},
        result="success",
        duration_ms=duration_ms,
        registrar=destination.provider,
    )

    if status.status == "finished":
        plan.state = MigrationState.POPULATING_DNS
        await session.commit()
        await audit.record(
            session,
            correlation_id=plan.correlation_id,
            actor=actor,
            action="migration.state_changed",
            target={"domain": plan.domain},
            after={"state": plan.state.value},
            result="success",
        )
    elif status.status in ("failed", "cancelled"):
        plan.state = MigrationState.FAILED
        plan.error_message = f"Provisioning job ended with status: {status.status}"
        await session.commit()
        await audit.record(
            session,
            correlation_id=plan.correlation_id,
            actor=actor,
            action="migration.failed",
            target={"domain": plan.domain, "provisioning_job_id": status.job_id},
            after={"state": plan.state.value, "reason": plan.error_message},
            result="failure",
        )
    await session.refresh(plan)
    return plan


async def populate_and_verify(
    session: AsyncSession,
    plan: MigrationPlan,
    *,
    destination: RegistrarAdapter,
    actor: str = "engine",
) -> MigrationPlan:
    """Bulk-create DNS records at Combell, then verify the zone."""
    if plan.state != MigrationState.POPULATING_DNS:
        raise IllegalTransitionError(
            f"Cannot populate a plan in state {plan.state.value}; expected POPULATING_DNS."
        )
    snapshot = await _load_latest_snapshot(session, plan)
    if snapshot is None:
        raise MigrationEngineError("No snapshot found — cannot populate.")

    source_records = _records_from_snapshot(snapshot.snapshot)
    destination_records_before: list[DnsRecord] = []
    try:
        destination_records_before = list(await destination.list_dns_records(plan.domain))
    except Exception:
        destination_records_before = []

    diff = compute_diff(
        source_records=source_records,
        destination_records=destination_records_before,
        supported_types=destination.capabilities.supported_record_types,
    )

    started = time.perf_counter()
    # Delete first so a to_update that coincides with a to_delete on the
    # same (type, name) cannot collide. NS / SOA are already filtered out
    # of diff.to_delete by compute_diff, so Combell's nameservers stay put.
    for record in diff.to_delete:
        await destination.delete_dns_record(plan.domain, record)
    for record in diff.to_create:
        await destination.create_dns_record(plan.domain, record)
    for record in diff.to_update:
        await destination.update_dns_record(plan.domain, record)
    duration_ms = int((time.perf_counter() - started) * 1000)

    # Verify — read the zone back and diff against the snapshot.
    destination_records_after = list(await destination.list_dns_records(plan.domain))
    verify_diff = compute_diff(
        source_records=source_records,
        destination_records=destination_records_after,
        supported_types=destination.capabilities.supported_record_types,
    )
    verify_ok = not (
        verify_diff.to_create or verify_diff.to_update or verify_diff.to_delete
    )

    if verify_ok:
        plan.state = MigrationState.COMPLETED
        plan.completed_at = datetime.now(tz=UTC)
        plan.error_message = None
    else:
        plan.state = MigrationState.FAILED
        plan.error_message = (
            f"Verification failed — {len(verify_diff.to_create)} create, "
            f"{len(verify_diff.to_update)} update, "
            f"{len(verify_diff.to_delete)} delete operations still outstanding."
        )

    existing_diff = plan.diff or {}
    plan.diff = {
        **existing_diff,
        "populated": serialize_diff(diff),
        "verify": serialize_diff(verify_diff),
    }
    await session.commit()
    await session.refresh(plan)

    await audit.record(
        session,
        correlation_id=plan.correlation_id,
        actor=actor,
        action="migration.populated",
        target={"domain": plan.domain},
        after={
            "state": plan.state.value,
            "diff_summary": diff.summary(),
            "verify_ok": verify_ok,
        },
        result="success" if verify_ok else "failure",
        duration_ms=duration_ms,
        registrar=destination.provider,
    )
    return plan


async def recover_from_destination(
    session: AsyncSession,
    plan: MigrationPlan,
    *,
    destination: RegistrarAdapter,
    actor: str = "operator",
) -> MigrationPlan:
    """Re-sync a plan's zone from the snapshot using the current Combell state.

    Purpose: rescue a migration that hit a client-side failure *after* the
    server-side transfer already succeeded (the ``steaan.be`` failure
    mode), and to offer a "replay from snapshot" action for plans that
    already look ``COMPLETED`` but whose zone has drifted.

    Steps:

    1. Verify Combell actually owns the domain — otherwise there is
       nothing to re-sync and an error message guides the operator back
       to the confirm step.
    2. Force the plan into ``POPULATING_DNS`` and commit so the audit log
       records the state transition.
    3. Run :func:`populate_and_verify`, which now performs a zone-replace
       (deletes destination records not in the snapshot, except NS/SOA).

    Refuses on ``DRAFT`` (no snapshot yet) and ``CANCELLED`` (operator
    explicitly gave up). Works on every other state including ``COMPLETED``
    as a safety re-sync, per the agreed design.
    """
    if plan.state in (MigrationState.DRAFT, MigrationState.CANCELLED):
        raise IllegalTransitionError(
            f"Cannot recover a plan in state {plan.state.value}. "
            "DRAFT has no snapshot yet; CANCELLED was explicitly abandoned."
        )
    snapshot = await _load_latest_snapshot(session, plan)
    if snapshot is None:
        raise MigrationEngineError(
            "No snapshot exists for this plan — run the preview step first."
        )

    # Does the destination really own the domain now? If not, the
    # populate step would drop records into a zone that is not ours.
    started = time.perf_counter()
    owned = await _destination_owns_domain(destination, plan.domain)
    ownership_ms = int((time.perf_counter() - started) * 1000)

    await audit.record(
        session,
        correlation_id=plan.correlation_id,
        actor=actor,
        action="migration.recover.ownership_check",
        target={"domain": plan.domain},
        after={"owned": owned},
        result="success" if owned else "failure",
        duration_ms=ownership_ms,
        registrar=destination.provider,
    )

    if not owned:
        raise MigrationEngineError(
            f"{destination.provider} does not list {plan.domain!r} as owned. "
            "Wait for the transfer to finish before attempting recovery."
        )

    previous_state = plan.state.value
    plan.state = MigrationState.POPULATING_DNS
    plan.error_message = None
    # If we landed here from PREVIEWED (the steaan.be case), confirmed_at
    # was never set — mark it now so the audit log has a coherent timeline.
    if plan.confirmed_at is None:
        plan.confirmed_at = datetime.now(tz=UTC)
    if not plan.provisioning_job_id:
        plan.provisioning_job_id = "recovered-from-destination"
    await session.commit()
    await session.refresh(plan)

    await audit.record(
        session,
        correlation_id=plan.correlation_id,
        actor=actor,
        action="migration.recover.started",
        target={"domain": plan.domain},
        before={"state": previous_state},
        after={"state": plan.state.value},
        result="success",
        registrar=destination.provider,
    )

    return await populate_and_verify(
        session, plan, destination=destination, actor=actor
    )


async def _destination_owns_domain(
    destination: RegistrarAdapter, domain: str
) -> bool:
    """Best-effort check: does the destination list ``domain`` in its inventory?

    Uses :meth:`list_domains` because Combell returns 404 (not a caught
    subclass) on ``list_dns_records`` for unowned domains, which is a
    heavier failure mode than we need for a yes/no question.
    """
    try:
        rows = list(await destination.list_domains())
    except Exception:
        return False
    needle = domain.lower()
    return any(row.name.lower() == needle for row in rows)


async def cancel_plan(
    session: AsyncSession,
    plan: MigrationPlan,
    *,
    actor: str = "operator",
    reason: str | None = None,
) -> MigrationPlan:
    """Cancel a plan that has not yet been confirmed."""
    if plan.state in (
        MigrationState.COMPLETED,
        MigrationState.FAILED,
        MigrationState.CANCELLED,
    ):
        return plan
    if plan.state in (
        MigrationState.AWAITING_TRANSFER,
        MigrationState.POPULATING_DNS,
    ):
        raise IllegalTransitionError(
            "The transfer is already in flight — cannot cancel locally. "
            "Contact Combell to abort the provisioning job."
        )
    plan.state = MigrationState.CANCELLED
    plan.error_message = reason
    await session.commit()
    await session.refresh(plan)
    await audit.record(
        session,
        correlation_id=plan.correlation_id,
        actor=actor,
        action="migration.cancelled",
        target={"domain": plan.domain},
        after={"state": plan.state.value, "reason": reason},
        result="success",
    )
    return plan


# --- internal helpers ------------------------------------------------------


async def _load_latest_snapshot(
    session: AsyncSession, plan: MigrationPlan
) -> DomainSnapshot | None:
    from sqlalchemy import select

    stmt = (
        select(DomainSnapshot)
        .where(DomainSnapshot.migration_plan_id == plan.id)
        .order_by(DomainSnapshot.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def _records_from_snapshot(snapshot: dict[str, Any]) -> list[DnsRecord]:
    """Rehydrate :class:`DnsRecord` objects from the persisted snapshot."""
    records_raw = snapshot.get("records") or []
    records: list[DnsRecord] = []
    for row in records_raw:
        try:
            records.append(
                DnsRecord(
                    type=row["type"],
                    name=row.get("name", "@"),
                    data=str(row.get("data", "")),
                    ttl=int(row.get("ttl", 3600)),
                    priority=row.get("priority"),
                )
            )
        except KeyError:
            continue
    return records


async def poll_until_settled(
    session: AsyncSession,
    plan: MigrationPlan,
    *,
    destination: RegistrarAdapter,
    max_iterations: int = 60,
    base_backoff_s: float = 2.0,
    max_backoff_s: float = 60.0,
) -> MigrationPlan:
    """Synchronous poll loop. Intended for short-TLD flows (``.be``) and tests.

    Long-running gTLD transfers should be driven by the background poller
    (see :func:`app.migrations.poller.run_forever`) — this helper blocks
    the current task and is therefore unsuitable for a multi-day wait.
    """
    for attempt in range(max_iterations):
        plan = await poll_transfer(session, plan, destination=destination)
        if plan.state != MigrationState.AWAITING_TRANSFER:
            return plan
        wait_for = min(base_backoff_s * (2 ** attempt), max_backoff_s)
        await asyncio.sleep(wait_for)
    return plan


def serialize_plan(plan: MigrationPlan) -> dict[str, Any]:
    """Shape returned by the /api/migrations endpoints."""
    return {
        "id": plan.id,
        "correlation_id": plan.correlation_id,
        "domain": plan.domain,
        "migration_type": plan.migration_type,
        "state": plan.state.value,
        "provisioning_job_id": plan.provisioning_job_id,
        "last_polled_at": plan.last_polled_at.isoformat() if plan.last_polled_at else None,
        "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
        "completed_at": plan.completed_at.isoformat() if plan.completed_at else None,
        "error_message": plan.error_message,
        "diff": plan.diff,
        "created_at": plan.created_at.isoformat(),
        "updated_at": plan.updated_at.isoformat(),
    }


def serialize_snapshot(snapshot: DomainSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "migration_plan_id": snapshot.migration_plan_id,
        "correlation_id": snapshot.correlation_id,
        "domain": snapshot.domain,
        "source_provider": snapshot.source_provider,
        "snapshot": snapshot.snapshot,
        "created_at": snapshot.created_at.isoformat(),
    }


__all__ = [
    "IllegalTransitionError",
    "MigrationEngineError",
    "cancel_plan",
    "confirm_and_submit",
    "create_plan",
    "new_correlation_id",
    "poll_transfer",
    "poll_until_settled",
    "populate_and_verify",
    "preview_plan",
    "recover_from_destination",
    "serialize_plan",
    "serialize_snapshot",
]

# Silence "unused import" while still making the helpers available via the
# package surface.
_ = build_snapshot_payload, asdict
