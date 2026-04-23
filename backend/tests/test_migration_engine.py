"""End-to-end tests for the migration engine using mock adapters.

Drives the state machine from DRAFT → PREVIEWED → CONFIRMED → COMPLETED
against the GoDaddy + Combell mock fixtures. Real registrar I/O is
exercised by the adapter tests; here we focus on orchestration + audit
coverage.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.db import AsyncSessionLocal
from app.migrations.engine import (
    confirm_and_submit,
    create_plan,
    poll_transfer,
    populate_and_verify,
    preview_plan,
)
from app.models import AuditEvent, DomainSnapshot, MigrationPlan, MigrationState
from app.registrars.base import (
    Contacts,
    DnsRecord,
    DomainDetail,
    JobStatus,
    ProvisioningJobRef,
    RegistrarAdapter,
    RegistrarRole,
)


class StubSource(RegistrarAdapter):
    provider = "stub-source"
    role = RegistrarRole.SOURCE

    def __init__(self) -> None:
        super().__init__(api_key="", api_base="", mock=True)

    async def test_connection(self) -> bool:
        return True

    async def get_domain(self, name: str) -> DomainDetail:
        return DomainDetail(
            name=name,
            status="ACTIVE",
            nameservers=("ns1.stub.test",),
            contacts=Contacts(registrant={"email": "op@example.com"}),
            locked=False,
            transfer_protected=False,
            privacy=False,
            expires_at=datetime.now(tz=UTC) + timedelta(days=200),
            transfer_away_eligible_at=datetime.now(tz=UTC) - timedelta(days=10),
        )

    async def list_dns_records(self, name: str):
        return [DnsRecord(type="A", name="@", data="1.2.3.4", ttl=3600)]


class StubDestination(RegistrarAdapter):
    provider = "stub-dest"
    role = RegistrarRole.DESTINATION

    def __init__(self) -> None:
        super().__init__(api_key="", api_base="", mock=True)
        self.created: list[DnsRecord] = []
        self._job_status = "ongoing"

    @property  # type: ignore[override]
    def capabilities(self):
        from app.registrars.base import AdapterCapabilities

        return AdapterCapabilities(
            supported_record_types=("A", "AAAA", "CNAME", "MX", "TXT"),
        )

    async def test_connection(self) -> bool:
        return True

    async def list_dns_records(self, name: str):
        return list(self.created)

    async def request_transfer_in(
        self, *, name, auth_code, registrant, name_servers=None
    ) -> ProvisioningJobRef:
        return ProvisioningJobRef(job_id="stub-job-1", submitted_at=datetime.now(tz=UTC))

    async def get_provisioning_job(self, job_id: str) -> JobStatus:
        return JobStatus(
            job_id=job_id,
            status=self._job_status,  # type: ignore[arg-type]
            polled_at=datetime.now(tz=UTC),
        )

    async def create_dns_record(self, name, record) -> None:
        self.created.append(record)


@pytest.fixture
async def clean_migration_state():
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AuditEvent))
        await session.execute(delete(DomainSnapshot))
        await session.execute(delete(MigrationPlan))
        await session.commit()
    yield
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AuditEvent))
        await session.execute(delete(DomainSnapshot))
        await session.execute(delete(MigrationPlan))
        await session.commit()


async def test_full_lifecycle_happy_path(clean_migration_state: None) -> None:
    source = StubSource()
    destination = StubDestination()

    async with AsyncSessionLocal() as session:
        plan = await create_plan(
            session, domain="example.com", migration_type="godaddy_to_combell"
        )
        assert plan.state == MigrationState.DRAFT

        plan, snapshot, report, diff = await preview_plan(
            session, plan, source=source, destination=destination
        )
        assert plan.state == MigrationState.PREVIEWED
        assert snapshot.migration_plan_id == plan.id
        assert report["passed"]
        assert diff.summary()["to_create"] == 1

        plan = await confirm_and_submit(
            session,
            plan,
            source=source,
            destination=destination,
            auth_code="test-auth-code",
            typed_domain="example.com",
        )
        assert plan.state == MigrationState.AWAITING_TRANSFER
        assert plan.provisioning_job_id == "stub-job-1"

        # Job still ongoing — poll is a no-op advance-wise.
        plan = await poll_transfer(session, plan, destination=destination)
        assert plan.state == MigrationState.AWAITING_TRANSFER

        # Flip the stub to finished and re-poll.
        destination._job_status = "finished"
        plan = await poll_transfer(session, plan, destination=destination)
        assert plan.state == MigrationState.POPULATING_DNS

        plan = await populate_and_verify(session, plan, destination=destination)
        assert plan.state == MigrationState.COMPLETED
        assert destination.created, "populate step should have created the A record"


async def test_confirm_rejects_wrong_typed_domain(clean_migration_state: None) -> None:
    source = StubSource()
    destination = StubDestination()
    async with AsyncSessionLocal() as session:
        plan = await create_plan(
            session, domain="example.com", migration_type="godaddy_to_combell"
        )
        plan, *_ = await preview_plan(
            session, plan, source=source, destination=destination
        )
        with pytest.raises(Exception) as excinfo:
            await confirm_and_submit(
                session,
                plan,
                source=source,
                destination=destination,
                auth_code="code",
                typed_domain="other.com",
            )
        assert "Typed domain does not match" in str(excinfo.value)
