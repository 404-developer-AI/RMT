"""Tests for the GoDaddy adapter in mock mode.

Mock mode is the only path we can exercise without a live account — the
fixtures file drives the full shape the engine depends on.
"""

from __future__ import annotations

import pytest

from app.registrars.godaddy import GoDaddyAdapter


@pytest.fixture
def adapter() -> GoDaddyAdapter:
    return GoDaddyAdapter(
        api_key="test", api_secret="test", api_base="https://api.example", mock=True
    )


async def test_mock_test_connection_returns_true(adapter: GoDaddyAdapter) -> None:
    assert await adapter.test_connection() is True


async def test_mock_list_domains_returns_fixture_rows(adapter: GoDaddyAdapter) -> None:
    rows = await adapter.list_domains()
    names = {r.name for r in rows}
    assert {"example.com", "fixture.be", "locked-example.com"}.issubset(names)


async def test_mock_get_domain_normalises_fields(adapter: GoDaddyAdapter) -> None:
    detail = await adapter.get_domain("example.com")
    assert detail.locked is False
    assert detail.privacy is False
    assert detail.contacts.registrant["email"] == "fixture@example.com"


async def test_mock_list_dns_records_returns_stable_rows(adapter: GoDaddyAdapter) -> None:
    records = await adapter.list_dns_records("example.com")
    types = {r.type for r in records}
    assert "A" in types
    assert "MX" in types


async def test_mock_get_auth_code_returns_fixture_for_com(adapter: GoDaddyAdapter) -> None:
    code = await adapter.get_auth_code("example.com")
    assert code == "fixture-auth-code-example-com"


async def test_mock_get_auth_code_returns_none_for_be(adapter: GoDaddyAdapter) -> None:
    code = await adapter.get_auth_code("fixture.be")
    assert code is None
