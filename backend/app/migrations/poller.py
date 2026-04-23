"""Background poller — polls every AWAITING_TRANSFER plan until it settles.

The poller is a single asyncio task started from the FastAPI lifespan and
cancelled on shutdown. It fetches all plans in the ``AWAITING_TRANSFER``
state, polls each one's provisioning job, and triggers the populate step
as soon as the job finishes. Cadence is deliberately conservative: one
sweep every ``POLL_INTERVAL_SECONDS`` (60 s default) so a multi-day
transfer does not hammer Combell.

The implementation is intentionally simple for V1 (no priority queue, no
worker pool). An in-process loop is enough for a single-operator tool with
O(1)–O(10) concurrent migrations.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.logging import get_logger
from app.migrations.adapters import load_adapters
from app.migrations.engine import poll_transfer, populate_and_verify
from app.models import MigrationPlan, MigrationState

logger = get_logger(__name__)

POLL_INTERVAL_SECONDS = 60.0


async def _sweep() -> None:
    """One full sweep over every in-flight plan."""
    async with AsyncSessionLocal() as session:
        stmt = select(MigrationPlan).where(
            MigrationPlan.state.in_(
                [MigrationState.AWAITING_TRANSFER, MigrationState.POPULATING_DNS]
            )
        )
        result = await session.execute(stmt)
        plans = list(result.scalars().all())

        for plan in plans:
            try:
                pair = await load_adapters(
                    session,
                    migration_type=plan.migration_type,
                )
            except Exception as exc:
                logger.warning(
                    "poller.adapter_load_failed",
                    plan_id=plan.id,
                    error=str(exc),
                )
                continue

            try:
                if plan.state == MigrationState.AWAITING_TRANSFER:
                    plan = await poll_transfer(session, plan, destination=pair.destination)
                if plan.state == MigrationState.POPULATING_DNS:
                    await populate_and_verify(session, plan, destination=pair.destination)
            except Exception as exc:
                logger.warning(
                    "poller.tick_failed",
                    plan_id=plan.id,
                    state=plan.state.value,
                    error=str(exc),
                )


async def run_forever() -> None:
    """Loop forever. Stop by cancelling the task."""
    logger.info("poller.started", interval_s=POLL_INTERVAL_SECONDS)
    while True:
        try:
            await _sweep()
        except Exception as exc:
            logger.error("poller.sweep_failed", error=str(exc))
        try:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("poller.stopped")
            raise
