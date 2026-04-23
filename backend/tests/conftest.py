"""Pytest fixtures for the backend test suite.

**Isolation guarantee.** The suite truncates tables (e.g. the
``clean_credentials`` / ``clean_migration_state`` fixtures), so it MUST
NOT run against the dev database — otherwise a local ``pytest`` would wipe
the operator's configured registrar credentials. This file enforces that
by rewriting ``DATABASE_URL`` to a ``*_test`` variant before anything else
imports :mod:`app.db`.

Precedence:
1. ``TEST_DATABASE_URL`` if explicitly set (used by CI — the GitHub Actions
   workflow points this at its Postgres service container).
2. Otherwise, the dev ``DATABASE_URL`` with the database name suffixed
   ``_test``. The companion `scripts/dev/create-db.sql` creates that
   database idempotently.

If neither can be derived, the tests refuse to start rather than risking
the dev DB.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from urllib.parse import urlparse, urlunparse

# Set a deterministic APP_SECRET before anything imports app.main / get_settings
# / get_cipher. CI and dev machines with a blank .env would otherwise fail at
# cipher construction. The value is test-only and never leaves this process.
os.environ.setdefault("APP_SECRET", "rmt-test-secret-must-be-at-least-sixteen-chars")
# Keep the background migration poller out of the test event loop.
os.environ.setdefault("APP_ENV", "testing")


def _read_dev_url_from_env_file() -> str | None:
    """Fallback when ``DATABASE_URL`` is not exported in the shell.

    pydantic-settings reads ``.env`` at import time for the app proper,
    but we need the URL *before* the app imports so we can rewrite it.
    A tiny line-based parser is enough for the conftest use-case — we
    only look at ``DATABASE_URL=...`` and ignore everything else.
    """
    from pathlib import Path

    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return None
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != "DATABASE_URL":
            continue
        return value.strip().strip('"').strip("'") or None
    return None


def _rewrite_db_url_for_tests() -> None:
    """Point the test process at a dedicated ``*_test`` database.

    This runs at module import, before ``app.db`` is ever touched, so the
    engine is built against the test DB from the start.
    """
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        os.environ["DATABASE_URL"] = explicit
        return
    dev_url = os.environ.get("DATABASE_URL") or _read_dev_url_from_env_file()
    if not dev_url:
        # No DATABASE_URL set at all — nothing to derive from. Let app.config
        # use its own default, which in pydantic-settings lands in the
        # ``rmt_dev`` placeholder. That URL's guard below will refuse to let
        # tests run, which is the right failure mode.
        return
    parsed = urlparse(dev_url)
    if not parsed.path or parsed.path in ("/", ""):
        return
    dbname = parsed.path.lstrip("/")
    if dbname.endswith("_test"):
        os.environ["DATABASE_URL"] = dev_url
        return
    new_path = f"/{dbname}_test"
    os.environ["DATABASE_URL"] = urlunparse(parsed._replace(path=new_path))


_rewrite_db_url_for_tests()

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import AsyncSessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import RegistrarCredential  # noqa: E402


def _assert_isolated_db() -> None:
    """Last-line safety net: abort if the test DB URL does not look isolated.

    Catches the case where ``TEST_DATABASE_URL`` was set to the same value
    as ``DATABASE_URL`` by a copy-paste error, or where the derived name
    did not actually end up with a ``_test`` suffix.
    """
    url = get_settings().database_url
    parsed = urlparse(url)
    dbname = parsed.path.lstrip("/")
    if not dbname.endswith("_test"):
        raise RuntimeError(
            "Refusing to run the test suite against a non-test database "
            f"({dbname!r}). Set TEST_DATABASE_URL to a dedicated *_test "
            "database, or create rmt_dev_test via scripts/dev/create-db.sql "
            "and rerun."
        )


_assert_isolated_db()


def _bootstrap_schema() -> None:
    """Run ``alembic upgrade head`` against the test DB before any test runs.

    The companion ``scripts/dev/create-db.sql`` only creates the empty
    ``rmt_dev_test`` database; the schema still has to be applied. Doing
    that here keeps the test setup to a single step for the operator:
    once ``rmt_dev_test`` exists, ``pytest`` just works and picks up any
    newly-added migrations automatically.

    We suppress alembic's usual ``fileConfig`` by injecting a minimal in-
    memory ``Config`` instance that only sets ``script_location``. The
    database URL comes from :mod:`app.config`, which is already pointing
    at the test DB by this point.
    """
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config()
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")


_bootstrap_schema()


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
