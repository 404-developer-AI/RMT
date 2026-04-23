"""Tests for the per-TLD pre-flight runner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.migrations.preflight import run_preflight
from app.registrars.base import Contacts, DnsRecord, DomainDetail

NOW = datetime(2026, 4, 23, tzinfo=UTC)


def _detail(
    name: str,
    *,
    locked: bool = False,
    transfer_protected: bool = False,
    privacy: bool = False,
    transfer_away_eligible_at: datetime | None = NOW - timedelta(days=10),
    expires_at: datetime | None = NOW + timedelta(days=180),
    registrant_email: str | None = "op@example.com",
) -> DomainDetail:
    registrant = {"email": registrant_email} if registrant_email else {}
    return DomainDetail(
        name=name,
        status="ACTIVE",
        nameservers=("ns1.godaddy.com",),
        contacts=Contacts(registrant=registrant),
        locked=locked,
        transfer_protected=transfer_protected,
        privacy=privacy,
        expires_at=expires_at,
        transfer_away_eligible_at=transfer_away_eligible_at,
    )


def test_happy_path_gtld_passes() -> None:
    report = run_preflight(_detail("example.com"), [], now=NOW)
    assert report.ruleset == "gtld"
    assert report.passed
    assert report.blocking_failures == []


def test_locked_domain_blocks_gtld_transfer() -> None:
    report = run_preflight(_detail("example.com", locked=True), [], now=NOW)
    assert not report.passed
    assert any(r.key == "domain.unlocked" for r in report.blocking_failures)


def test_icann_sixty_day_window_blocks() -> None:
    report = run_preflight(
        _detail(
            "example.com",
            transfer_away_eligible_at=NOW + timedelta(days=5),
        ),
        [],
        now=NOW,
    )
    assert not report.passed
    assert any(r.key == "icann.sixty_day_rule" for r in report.blocking_failures)


def test_expiry_too_close_blocks() -> None:
    report = run_preflight(
        _detail("example.com", expires_at=NOW + timedelta(days=10)),
        [],
        now=NOW,
    )
    assert not report.passed
    assert any(r.key == "domain.expiry_gt_15d" for r in report.blocking_failures)


def test_caa_records_raise_warning_only() -> None:
    records = [DnsRecord(type="CAA", name="@", data="0 issue letsencrypt.org", ttl=3600)]
    report = run_preflight(_detail("example.com"), records, now=NOW)
    assert report.passed  # CAA is a warning, not a blocker
    assert any(r.key == "dns.caa_records" and not r.ok for r in report.results)


def test_godaddy_parking_placeholder_raises_warning_only() -> None:
    """A 'Parked' A-record is a GoDaddy artefact — warn, do not block."""
    records = [DnsRecord(type="A", name="@", data="Parked", ttl=600)]
    report = run_preflight(_detail("example.com"), records, now=NOW)
    assert report.passed
    warning = next(
        r for r in report.results if r.key == "dns.godaddy_parking_placeholder"
    )
    assert warning.severity == "warning"
    assert not warning.ok
    assert "Parked" in warning.message


def test_godaddy_parking_check_passes_when_absent() -> None:
    records = [DnsRecord(type="A", name="@", data="1.2.3.4", ttl=3600)]
    report = run_preflight(_detail("example.com"), records, now=NOW)
    check = next(
        r for r in report.results if r.key == "dns.godaddy_parking_placeholder"
    )
    assert check.ok


def test_godaddy_parking_check_is_case_insensitive() -> None:
    records = [DnsRecord(type="A", name="@", data="parked", ttl=600)]
    report = run_preflight(_detail("example.com"), records, now=NOW)
    check = next(
        r for r in report.results if r.key == "dns.godaddy_parking_placeholder"
    )
    assert not check.ok


def test_be_ruleset_treats_privacy_as_warning_only() -> None:
    report = run_preflight(
        _detail("fixture.be", privacy=True, transfer_away_eligible_at=None),
        [],
        now=NOW,
    )
    # .be has no ICANN 60-day rule and no expiry-window rule.
    assert report.ruleset == "be"
    assert report.passed
    assert any(
        r.key == "domain.privacy_off" and r.severity == "warning" and not r.ok
        for r in report.results
    )
