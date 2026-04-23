"""FastAPI application factory + module-level `app` instance."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import api_router
from app.config import get_settings
from app.db import engine
from app.logging import configure_logging, get_logger
from app.migrations.poller import run_forever as run_poller


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logger = get_logger("app.lifespan")
    logger.info("app.startup", version=__version__)
    settings = get_settings()
    poller_task: asyncio.Task[None] | None = None
    # Skip the poller in test mode — the fixtures run without a long-lived
    # event loop and the background sweep would otherwise race with the
    # per-test engine.dispose().
    if settings.app_env != "testing":
        poller_task = asyncio.create_task(run_poller(), name="migration-poller")
    try:
        yield
    finally:
        if poller_task is not None:
            poller_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await poller_task
        await engine.dispose()
        logger.info("app.shutdown")


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    app = FastAPI(
        title="RMT — Registrar Migration Tool",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if not settings.is_production else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api")

    return app


app = create_app()
