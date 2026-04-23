"""Sanity tests for the abstract RegistrarAdapter contract."""

from __future__ import annotations

import pytest

from app.registrars import (
    AdapterCapabilities,
    DnsRecord,
    RegistrarAdapter,
    RegistrarRole,
)


class _StubSourceAdapter(RegistrarAdapter):
    """Implements only the read-side methods — destination methods stay abstract-by-default."""

    provider = "stub-source"
    role = RegistrarRole.SOURCE
    capabilities = AdapterCapabilities(can_export_auth_code=True)

    async def test_connection(self) -> bool:
        return True


def _adapter() -> _StubSourceAdapter:
    return _StubSourceAdapter(
        api_key="fixture-key",
        api_secret="fixture-secret",
        api_base="https://example.invalid",
    )


def test_dry_run_and_mock_default_false() -> None:
    a = _adapter()
    assert a.dry_run is False
    assert a.mock is False


async def test_unimplemented_destination_method_raises() -> None:
    a = _adapter()
    with pytest.raises(NotImplementedError, match="request_transfer_in"):
        await a.request_transfer_in(
            name="example.com",
            auth_code="000-000-000-000-000",
            registrant={},
        )


async def test_optional_get_auth_code_returns_none_by_default() -> None:
    a = _adapter()
    assert await a.get_auth_code("example.com") is None


def test_dns_record_dataclass_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    record = DnsRecord(type="A", name="@", data="1.2.3.4", ttl=3600)
    with pytest.raises(FrozenInstanceError):
        record.ttl = 60  # type: ignore[misc]
