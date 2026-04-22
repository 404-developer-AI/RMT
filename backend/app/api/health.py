"""Liveness and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db import get_session
from app.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> dict[str, str]:
    """Always-on liveness check. Returns 200 if the process is alive."""
    return {"status": "ok", "version": __version__}


@router.get("/readyz", summary="Readiness probe")
async def readyz(
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Readiness check — verifies the database is reachable."""
    checks: dict[str, str] = {}
    try:
        result = await session.execute(text("SELECT 1"))
        result.scalar_one()
        checks["database"] = "ok"
    except Exception as exc:
        logger.warning("readyz.database_unreachable", error=str(exc))
        checks["database"] = "error"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not-ready", "checks": checks, "version": __version__}

    return {"status": "ready", "checks": checks, "version": __version__}
