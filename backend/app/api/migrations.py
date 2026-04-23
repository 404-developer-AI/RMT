"""Migration-wizard endpoints.

Shape exposed to the UI:

* ``POST   /api/migrations``                — create a DRAFT plan
* ``GET    /api/migrations``                — list recent plans
* ``GET    /api/migrations/{id}``           — plan detail
* ``POST   /api/migrations/{id}/preview``   — snapshot + pre-flight + diff
* ``POST   /api/migrations/{id}/confirm``   — submit the transfer
* ``POST   /api/migrations/{id}/poll``      — manual poll tick
* ``POST   /api/migrations/{id}/cancel``    — cancel a pre-confirm plan
* ``GET    /api/migrations/{id}/snapshot``  — download the latest snapshot JSON

Every route delegates to :mod:`app.migrations.engine` for business logic —
this module is strictly concerned with request/response translation and
HTTP-status mapping.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.migrations import adapters as adapter_loader
from app.migrations.engine import (
    IllegalTransitionError,
    MigrationEngineError,
    cancel_plan,
    confirm_and_submit,
    create_plan,
    poll_transfer,
    populate_and_verify,
    preview_plan,
    serialize_plan,
    serialize_snapshot,
)
from app.models import DomainSnapshot, MigrationPlan, MigrationState
from app.registrars.http import RegistrarHTTPError

router = APIRouter(prefix="/migrations", tags=["migrations"])


# --- schemas ----------------------------------------------------------------


class CreatePlanBody(BaseModel):
    domain: str = Field(min_length=1, max_length=253)
    migration_type: str = Field(min_length=1, max_length=64)


class ConfirmBody(BaseModel):
    auth_code: str = Field(min_length=1)
    typed_domain: str = Field(min_length=1)


class CancelBody(BaseModel):
    reason: str | None = None


class PlanOut(BaseModel):
    model_config = {"extra": "allow"}


# --- helpers ---------------------------------------------------------------


async def _load_plan(session: AsyncSession, plan_id: int) -> MigrationPlan:
    plan = await session.get(MigrationPlan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Migration not found.")
    return plan


async def _load_pair(session: AsyncSession, plan: MigrationPlan, *, mock: bool):
    try:
        return await adapter_loader.load_adapters(
            session, migration_type=plan.migration_type, mock=mock
        )
    except HTTPException:
        raise


async def _close_pair(pair: adapter_loader.AdapterPair) -> None:
    for adapter in (pair.source, pair.destination):
        aclose = getattr(adapter, "aclose", None)
        if aclose is not None:
            await aclose()


def _wrap_engine(exc: Exception) -> HTTPException:
    if isinstance(exc, IllegalTransitionError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, MigrationEngineError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, RegistrarHTTPError):
        return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


# --- endpoints -------------------------------------------------------------


@router.post(
    "",
    response_model=dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="Create a DRAFT migration plan",
)
async def create(
    body: CreatePlanBody,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    try:
        plan = await create_plan(
            session,
            domain=body.domain,
            migration_type=body.migration_type,
        )
    except KeyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return serialize_plan(plan)


@router.get(
    "",
    response_model=list[dict[str, Any]],
    summary="List migration plans (newest first)",
)
async def list_plans(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    state: Annotated[str | None, Query()] = None,
) -> list[dict[str, Any]]:
    stmt = select(MigrationPlan).order_by(desc(MigrationPlan.created_at)).limit(limit)
    if state is not None:
        try:
            state_enum = MigrationState(state)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown state {state!r}",
            ) from exc
        stmt = stmt.where(MigrationPlan.state == state_enum)
    result = await session.execute(stmt)
    return [serialize_plan(p) for p in result.scalars().all()]


@router.get(
    "/{plan_id}",
    response_model=dict[str, Any],
    summary="Get one migration plan",
)
async def get_one(
    plan_id: Annotated[int, Path(ge=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    plan = await _load_plan(session, plan_id)
    return serialize_plan(plan)


@router.post(
    "/{plan_id}/preview",
    response_model=dict[str, Any],
    summary="Snapshot + pre-flight + zone diff",
)
async def preview(
    plan_id: Annotated[int, Path(ge=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mock: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    plan = await _load_plan(session, plan_id)
    pair = await _load_pair(session, plan, mock=mock)
    try:
        plan, snapshot, _, diff = await preview_plan(
            session,
            plan,
            source=pair.source,
            destination=pair.destination,
        )
    except (IllegalTransitionError, MigrationEngineError, RegistrarHTTPError) as exc:
        raise _wrap_engine(exc) from exc
    finally:
        await _close_pair(pair)
    return {
        "plan": serialize_plan(plan),
        "snapshot": serialize_snapshot(snapshot),
        "diff_summary": diff.summary(),
    }


@router.post(
    "/{plan_id}/confirm",
    response_model=dict[str, Any],
    summary="Confirm and submit the transfer",
)
async def confirm(
    plan_id: Annotated[int, Path(ge=1)],
    body: ConfirmBody,
    session: Annotated[AsyncSession, Depends(get_session)],
    mock: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    plan = await _load_plan(session, plan_id)
    pair = await _load_pair(session, plan, mock=mock)
    try:
        plan = await confirm_and_submit(
            session,
            plan,
            source=pair.source,
            destination=pair.destination,
            auth_code=body.auth_code,
            typed_domain=body.typed_domain,
        )
    except (IllegalTransitionError, MigrationEngineError, RegistrarHTTPError) as exc:
        raise _wrap_engine(exc) from exc
    finally:
        await _close_pair(pair)
    return serialize_plan(plan)


@router.post(
    "/{plan_id}/poll",
    response_model=dict[str, Any],
    summary="Manually tick the poller for this plan",
)
async def poll_once(
    plan_id: Annotated[int, Path(ge=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mock: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    plan = await _load_plan(session, plan_id)
    pair = await _load_pair(session, plan, mock=mock)
    try:
        if plan.state == MigrationState.AWAITING_TRANSFER:
            plan = await poll_transfer(session, plan, destination=pair.destination)
        if plan.state == MigrationState.POPULATING_DNS:
            plan = await populate_and_verify(
                session, plan, destination=pair.destination
            )
    except (IllegalTransitionError, MigrationEngineError, RegistrarHTTPError) as exc:
        raise _wrap_engine(exc) from exc
    finally:
        await _close_pair(pair)
    return serialize_plan(plan)


@router.post(
    "/{plan_id}/cancel",
    response_model=dict[str, Any],
    summary="Cancel a migration plan that hasn't been confirmed yet",
)
async def cancel(
    plan_id: Annotated[int, Path(ge=1)],
    body: CancelBody,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    plan = await _load_plan(session, plan_id)
    try:
        plan = await cancel_plan(session, plan, reason=body.reason)
    except (IllegalTransitionError, MigrationEngineError) as exc:
        raise _wrap_engine(exc) from exc
    return serialize_plan(plan)


@router.get(
    "/{plan_id}/snapshot",
    response_model=dict[str, Any],
    summary="Latest snapshot captured for this plan",
)
async def latest_snapshot(
    plan_id: Annotated[int, Path(ge=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    plan = await _load_plan(session, plan_id)
    stmt = (
        select(DomainSnapshot)
        .where(DomainSnapshot.migration_plan_id == plan.id)
        .order_by(desc(DomainSnapshot.created_at))
        .limit(1)
    )
    result = await session.execute(stmt)
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="No snapshot captured yet — preview the plan first.",
        )
    return serialize_snapshot(snapshot)
