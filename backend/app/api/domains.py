"""Read-only domain list endpoint — source registrar view.

Powers the "Domain list" screen in the wizard. Queries are intentionally
simple (no server-side search/sort) because GoDaddy's v1 API does not
support either — the frontend filters the <500 rows client-side.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.migrations.adapters import load_adapters
from app.migrations.registry import get_migration_type, list_migration_types
from app.registrars.http import RegistrarHTTPError

router = APIRouter(prefix="/domains", tags=["domains"])


class DomainSummaryOut(BaseModel):
    name: str
    status: str
    expires_at: datetime | None = None
    locked: bool | None = None
    privacy: bool | None = None


class DomainListResponse(BaseModel):
    migration_type: str
    source_provider: str
    destination_provider: str
    domains: list[DomainSummaryOut]


def _default_migration_type() -> str:
    types = list_migration_types()
    if not types:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No migration types registered.",
        )
    return types[0].key


@router.get(
    "",
    response_model=DomainListResponse,
    summary="List domains from the source registrar for a migration type",
)
async def list_domains(
    session: Annotated[AsyncSession, Depends(get_session)],
    migration_type: Annotated[str | None, Query()] = None,
    mock: Annotated[bool, Query()] = False,
) -> DomainListResponse:
    key = migration_type or _default_migration_type()
    mig_type = get_migration_type(key)
    pair = await load_adapters(session, migration_type=key, mock=mock)
    try:
        rows = await pair.source.list_domains()
    except RegistrarHTTPError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Source registrar call failed: {exc}",
        ) from exc
    finally:
        aclose = getattr(pair.source, "aclose", None)
        if aclose is not None:
            await aclose()
        aclose_dst = getattr(pair.destination, "aclose", None)
        if aclose_dst is not None:
            await aclose_dst()

    return DomainListResponse(
        migration_type=key,
        source_provider=mig_type.source_provider,
        destination_provider=mig_type.destination_provider,
        domains=[DomainSummaryOut(**asdict(row)) for row in rows],
    )
