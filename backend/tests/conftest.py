"""Pytest fixtures for the backend test suite."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

# Set a deterministic APP_SECRET before anything imports app.main / get_settings
# / get_cipher. CI and dev machines with a blank .env would otherwise fail at
# cipher construction. The value is test-only and never leaves this process.
os.environ.setdefault("APP_SECRET", "rmt-test-secret-must-be-at-least-sixteen-chars")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db import AsyncSessionLocal, engine
from app.main import app
from app.models import RegistrarCredential


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests() -> AsyncIterator[None]:
    """Drop pooled asyncpg connections after every test.

    pytest-asyncio gives each test its own event loop; asyncpg connections
    bound to a prior loop raise ``Event loop is closed`` when the next test
    tries to reuse them. Disposing forces a clean reconnect per test.
    """
    yield
    await engine.dispose()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def clean_credentials() -> AsyncIterator[None]:
    """Truncate registrar_credentials before and after a test that writes to it."""
    async with AsyncSessionLocal() as session:
        await session.execute(delete(RegistrarCredential))
        await session.commit()
    yield
    async with AsyncSessionLocal() as session:
        await session.execute(delete(RegistrarCredential))
        await session.commit()
