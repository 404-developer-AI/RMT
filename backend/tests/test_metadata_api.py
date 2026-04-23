"""Tests for /api/providers and /api/migration-types."""

from __future__ import annotations

from httpx import AsyncClient


async def test_list_providers_includes_v1_pair(client: AsyncClient) -> None:
    resp = await client.get("/api/providers")
    assert resp.status_code == 200
    body = resp.json()
    keys = {p["key"] for p in body}
    assert {"godaddy", "combell"}.issubset(keys)
    # Both V1 adapters ship together — the UI can assume they are present.
    by_key = {p["key"]: p for p in body}
    assert by_key["godaddy"]["adapter_installed"] is True
    assert by_key["combell"]["adapter_installed"] is True


async def test_list_migration_types_returns_godaddy_to_combell(
    client: AsyncClient,
) -> None:
    resp = await client.get("/api/migration-types")
    assert resp.status_code == 200
    body = resp.json()
    entry = next(t for t in body if t["key"] == "godaddy_to_combell")
    assert entry["source_provider"] == "godaddy"
    assert entry["destination_provider"] == "combell"
    assert "be" in entry["auth_code_hints"]
    assert "dnsbelgium.be" in entry["auth_code_hints"]["be"]
