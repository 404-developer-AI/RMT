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
    IllegalTransitionError,
    MigrationEngineError,
    confirm_and_submit,
    create_plan,
    poll_transfer,
    populate_and_verify,
    preview_plan,
    recover_from_destination,
)
from app.models import AuditEvent, DomainSnapshot, MigrationPlan, MigrationState
from app.registrars.base import (
    Contacts,
    DnsRecord,
    DomainDetail,
    DomainSummary,
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
        self.zone: list[DnsRecord] = []
        self.owned: set[str] = set()
        self._job_status = "ongoing"

    @property  # type: ignore[override]
    def capabilities(self):
        from app.registrars.base import AdapterCapabilities

        return AdapterCapabilities(
            supported_record_types=("A", "AAAA", "CNAME", "MX", "TXT"),
        )

    async def test_connection(self) -> bool:
        return True

    async def list_domains(self):
        return [DomainSummary(name=d, status="ACTIVE") for d in sorted(self.owned)]

    async def list_dns_records(self, name: str):
        return list(self.zone)

    async def request_transfer_in(
        self, *, name, auth_code, registrant, name_servers=None
    ) -> ProvisioningJobRef:
        # Deliberately not added to ``owned`` — real Combell only lists the
        # domain after the transfer is registry-side complete, not at
        # submission time. Tests that need post-transfer state add it
        # explicitly.
        return ProvisioningJobRef(job_id="stub-job-1", submitted_at=datetime.now(tz=UTC))

    async def get_provisioning_job(self, job_id: str) -> JobStatus:
        return JobStatus(
            job_id=job_id,
            status=self._job_status,  # type: ignore[arg-type]
            polled_at=datetime.now(tz=UTC),
            detail={"id": job_id, "status": self._job_status},
        )

    async def create_dns_record(self, name, record) -> None:
        self.zone.append(record)

    async def update_dns_record(self, name, record) -> None:
        # Simple replace on (type, name) identity.
        self.zone = [
            r for r in self.zone if (r.type, r.name) != (record.type, record.name)
        ]
        self.zone.append(record)

    async def delete_dns_record(self, name, record) -> None:
        self.zone = [
            r for r in self.zone if (r.type, r.name) != (record.type, record.name)
        ]


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
        assert destination.zone, "populate step should have created the A record"


async def test_poll_advances_when_destination_owns_despite_ongoing_job(
    clean_migration_state: None,
) -> None:
    """Reproduces the servicelimburgbv.be incident.

    Combell leaves /v2/provisioningjobs on ``ongoing`` until the NS cutover
    propagates, but /v2/domains already lists the domain as soon as the
    registry-side transfer completes. The poller must treat inventory
    presence as the authoritative done-signal and advance regardless.
    """
    source = StubSource()
    destination = StubDestination()

    async with AsyncSessionLocal() as session:
        plan = await create_plan(
            session, domain="example.com", migration_type="godaddy_to_combell"
        )
        plan, *_ = await preview_plan(
            session, plan, source=source, destination=destination
        )
        plan = await confirm_and_submit(
            session,
            plan,
            source=source,
            destination=destination,
            auth_code="test-auth-code",
            typed_domain="example.com",
        )
        assert plan.state == MigrationState.AWAITING_TRANSFER
        assert destination._job_status == "ongoing"

        # Job stuck on ongoing AND domain not yet in Combell's inventory.
        plan = await poll_transfer(session, plan, destination=destination)
        assert plan.state == MigrationState.AWAITING_TRANSFER

        # Combell now lists the domain, job stays "ongoing" (real bug).
        destination.owned.add("example.com")
        plan = await poll_transfer(session, plan, destination=destination)
        assert plan.state == MigrationState.POPULATING_DNS

        # Audit row captures the raw Combell body and the ownership flag
        # so this class of stall is diagnosable from the UI next time.
        from sqlalchemy import select

        events = (
            await session.execute(
                select(AuditEvent)
                .where(AuditEvent.action == "migration.poll")
                .order_by(AuditEvent.ts.desc())
            )
        ).scalars().all()
        assert events, "expected a migration.poll audit row"
        latest = events[0].after or {}
        assert latest.get("destination_owned") is True
        assert latest.get("raw", {}).get("status") == "ongoing"


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


# --- recover_from_destination ---------------------------------------------


async def test_recover_from_previewed_wipes_defaults_and_populates(
    clean_migration_state: None,
) -> None:
    """Reproduces the steaan.be scenario.

    Transfer succeeded on Combell's side but the engine never advanced
    past PREVIEWED. Clicking Resume should:
      * verify Combell now owns the domain,
      * delete the default Combell records not in the snapshot,
      * create the snapshot's records,
      * move the plan to COMPLETED with confirmed_at populated.
    """
    source = StubSource()
    destination = StubDestination()
    # Simulate post-transfer state: Combell owns the domain, its zone has
    # only a default parking record.
    destination.owned.add("example.com")
    destination.zone = [
        DnsRecord(type="A", name="parking", data="81.89.121.1", ttl=3600),
    ]

    async with AsyncSessionLocal() as session:
        plan = await create_plan(
            session, domain="example.com", migration_type="godaddy_to_combell"
        )
        plan, *_ = await preview_plan(
            session, plan, source=source, destination=destination
        )
        assert plan.state == MigrationState.PREVIEWED
        assert plan.confirmed_at is None

        plan = await recover_from_destination(
            session, plan, destination=destination
        )

    assert plan.state == MigrationState.COMPLETED
    assert plan.confirmed_at is not None
    # Parking record is gone, snapshot's A record is in place.
    types_names = {(r.type, r.name) for r in destination.zone}
    assert ("A", "@") in types_names
    assert ("A", "parking") not in types_names


async def test_recover_refuses_when_destination_does_not_own_domain(
    clean_migration_state: None,
) -> None:
    source = StubSource()
    destination = StubDestination()  # destination.owned stays empty

    async with AsyncSessionLocal() as session:
        plan = await create_plan(
            session, domain="example.com", migration_type="godaddy_to_combell"
        )
        plan, *_ = await preview_plan(
            session, plan, source=source, destination=destination
        )
        with pytest.raises(MigrationEngineError, match="does not list"):
            await recover_from_destination(
                session, plan, destination=destination
            )


async def test_recover_refused_on_draft_state(
    clean_migration_state: None,
) -> None:
    destination = StubDestination()
    destination.owned.add("example.com")
    async with AsyncSessionLocal() as session:
        plan = await create_plan(
            session, domain="example.com", migration_type="godaddy_to_combell"
        )
        # DRAFT has no snapshot yet — recovery is meaningless.
        with pytest.raises(IllegalTransitionError):
            await recover_from_destination(
                session, plan, destination=destination
            )


async def test_recover_is_safe_to_run_on_already_completed_plan(
    clean_migration_state: None,
) -> None:
    """Replay on a COMPLETED plan should converge the zone and stay COMPLETED."""
    source = StubSource()
    destination = StubDestination()
    destination.owned.add("example.com")

    async with AsyncSessionLocal() as session:
        plan = await create_plan(
            session, domain="example.com", migration_type="godaddy_to_combell"
        )
        plan, *_ = await preview_plan(
            session, plan, source=source, destination=destination
        )
        plan = await recover_from_destination(
            session, plan, destination=destination
        )
        assert plan.state == MigrationState.COMPLETED

        # Someone adds a stray record at Combell; another Resume click
        # should clean it up without fussing about the plan's state.
        destination.zone.append(
            DnsRecord(type="A", name="stray", data="2.2.2.2", ttl=3600)
        )
        plan = await recover_from_destination(
            session, plan, destination=destination
        )
        assert plan.state == MigrationState.COMPLETED
        assert all(r.name != "stray" for r in destination.zone)
