"""Tests for the Combell adapter in mock mode."""

from __future__ import annotations

import pytest

from app.registrars.combell import CombellAdapter


@pytest.fixture
def adapter() -> CombellAdapter:
    return CombellAdapter(
        api_key="test",
        api_secret=None,
        api_base="https://api.example",
        mock=True,
    )


async def test_mock_test_connection_returns_true(adapter: CombellAdapter) -> None:
    assert await adapter.test_connection() is True


async def test_mock_transfer_request_returns_job_ref(adapter: CombellAdapter) -> None:
    job = await adapter.request_transfer_in(
        name="example.com",
        auth_code="secret-code",
        registrant={"email": "fixture@example.com"},
        name_servers=[],
    )
    assert job.job_id
    assert job.submitted_at is not None


async def test_mock_provisioning_job_status_is_ongoing_by_default(
    adapter: CombellAdapter,
) -> None:
    status = await adapter.get_provisioning_job("fixture-job-1")
    assert status.status == "ongoing"


async def test_mock_provisioning_job_status_finished_when_name_indicates(
    adapter: CombellAdapter,
) -> None:
    status = await adapter.get_provisioning_job("fixture-job-finished-1")
    assert status.status == "finished"


async def test_mock_list_dns_records_returns_empty_zone(adapter: CombellAdapter) -> None:
    records = await adapter.list_dns_records("example.com")
    assert records == []
