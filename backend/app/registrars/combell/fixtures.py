"""Local fixture responses for the Combell adapter's ``mock=True`` mode.

Again deliberately obvious values — ``fixture-job-*`` ids,
``example.com``-style domains — so a leaked fixture can never be confused
with a customer record.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.registrars.base import JobStatusValue


def fixture_domains() -> list[dict[str, Any]]:
    """Combell returns a flat list from ``GET /v2/domains``."""
    return []


def fixture_transfer_job() -> dict[str, Any]:
    """Response body Combell returns on ``POST /v2/domains/transfers``."""
    return {
        "id": "fixture-job-transfer-1",
        "status": "ongoing",
        "created_at": datetime.now(tz=UTC).isoformat(),
    }


def fixture_job_status(job_id: str) -> dict[str, Any]:
    """For a fixture job id, ``finished`` after first call; for others, ``ongoing``.

    We deliberately do not persist state here — the migration engine's tests
    drive job progression by stubbing this function rather than relying on
    fixture memory.
    """
    status: JobStatusValue = "finished" if "finished" in job_id else "ongoing"
    return {"id": job_id, "status": status}


def fixture_dns_records(name: str) -> list[dict[str, Any]]:
    """Zone reads return an empty zone until a record has been created."""
    _ = name
    return []
