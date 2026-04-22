"""Health endpoint tests."""

from __future__ import annotations

from httpx import AsyncClient


async def test_healthz_returns_ok(client: AsyncClient) -> None:
    resp = await client.get("/api/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


async def test_readyz_reports_database_status(client: AsyncClient) -> None:
    """readyz always returns a structured response; status depends on DB reachability."""
    resp = await client.get("/api/readyz")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert "status" in body
    assert "checks" in body
    assert "database" in body["checks"]
