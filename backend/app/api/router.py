"""Top-level API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import credentials, health, metadata

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(metadata.router)
api_router.include_router(credentials.router)
