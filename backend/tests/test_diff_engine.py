"""Tests for the record-set diff engine + TTL clamping."""

from __future__ import annotations

from app.migrations.diff import (
    COMBELL_MAX_TTL,
    COMBELL_MIN_TTL,
    clamp_record,
    compute_diff,
)
from app.registrars.base import DnsRecord

SUPPORTED = ("A", "AAAA", "CNAME", "MX", "TXT", "SRV", "ALIAS", "TLSA")


def _a(name: str, data: str, ttl: int = 3600) -> DnsRecord:
    return DnsRecord(type="A", name=name, data=data, ttl=ttl)


def test_clamp_ttl_respects_combell_bounds() -> None:
    assert clamp_record(_a("@", "1.2.3.4", ttl=10)).ttl == COMBELL_MIN_TTL
    assert clamp_record(_a("@", "1.2.3.4", ttl=100000)).ttl == COMBELL_MAX_TTL
    assert clamp_record(_a("@", "1.2.3.4", ttl=300)).ttl == 300


def test_diff_empty_destination_emits_create_for_every_source_record() -> None:
    src = [_a("@", "1.2.3.4"), _a("www", "1.2.3.4")]
    diff = compute_diff(source_records=src, destination_records=[], supported_types=SUPPORTED)
    assert len(diff.to_create) == 2
    assert diff.to_update == []
    assert diff.to_delete == []


def test_diff_matching_record_is_a_noop() -> None:
    rec = _a("@", "1.2.3.4")
    diff = compute_diff(
        source_records=[rec], destination_records=[rec], supported_types=SUPPORTED
    )
    assert diff.is_empty


def test_diff_changed_value_emits_update() -> None:
    src = [_a("@", "1.2.3.4")]
    dst = [_a("@", "5.6.7.8")]
    diff = compute_diff(
        source_records=src, destination_records=dst, supported_types=SUPPORTED
    )
    assert diff.to_create == []
    assert len(diff.to_update) == 1


def test_diff_skips_unsupported_types() -> None:
    src = [DnsRecord(type="NS", name="@", data="ns1.example.com", ttl=3600)]
    diff = compute_diff(
        source_records=src, destination_records=[], supported_types=SUPPORTED
    )
    # NS is always managed by the registrar — never emitted.
    assert diff.to_create == []


def test_diff_clamps_source_ttls_before_comparing() -> None:
    src = [_a("@", "1.2.3.4", ttl=30)]
    # Destination has the clamped value, so the diff should be empty.
    dst = [_a("@", "1.2.3.4", ttl=COMBELL_MIN_TTL)]
    diff = compute_diff(
        source_records=src, destination_records=dst, supported_types=SUPPORTED
    )
    assert diff.is_empty


# --- zone-replace (delete) behaviour --------------------------------------


def test_diff_schedules_delete_for_destination_only_records() -> None:
    """Combell's default parking A record should be scheduled for deletion."""
    src = [_a("@", "1.2.3.4")]
    dst = [
        _a("@", "1.2.3.4"),
        # Extra default Combell record not present in snapshot
        DnsRecord(type="A", name="parking", data="81.89.121.1", ttl=3600),
    ]
    diff = compute_diff(
        source_records=src, destination_records=dst, supported_types=SUPPORTED
    )
    assert diff.to_create == []
    assert diff.to_update == []
    assert len(diff.to_delete) == 1
    assert diff.to_delete[0].name == "parking"


def test_diff_never_deletes_ns_records_at_destination() -> None:
    """NS records are owned by the registrar — must survive zone-replace."""
    src = [_a("@", "1.2.3.4")]
    dst = [
        DnsRecord(type="NS", name="@", data="ns1.combell.be", ttl=3600),
        DnsRecord(type="NS", name="@", data="ns2.combell.be", ttl=3600),
    ]
    diff = compute_diff(
        source_records=src, destination_records=dst, supported_types=SUPPORTED
    )
    assert diff.to_delete == []


def test_diff_never_deletes_soa_records_at_destination() -> None:
    src = [_a("@", "1.2.3.4")]
    dst = [
        DnsRecord(type="SOA", name="@", data="ns1.combell.be. hostmaster...", ttl=3600),
    ]
    diff = compute_diff(
        source_records=src, destination_records=dst, supported_types=SUPPORTED
    )
    assert diff.to_delete == []


def test_diff_zone_replace_full_example() -> None:
    """Snapshot has its own records; Combell zone has parking + defaults."""
    src = [
        _a("@", "1.2.3.4"),
        DnsRecord(type="MX", name="@", data="mail.example.com", ttl=3600, priority=10),
    ]
    dst = [
        # Matches source — no-op.
        _a("@", "1.2.3.4"),
        # Combell parking record — should be deleted.
        DnsRecord(type="A", name="www", data="81.89.121.1", ttl=3600),
        # Combell default MX — should be replaced by the snapshot's MX.
        DnsRecord(type="MX", name="@", data="mailcluster.combell.be", ttl=3600, priority=10),
        # NS records — must survive.
        DnsRecord(type="NS", name="@", data="ns1.combell.be", ttl=3600),
    ]
    diff = compute_diff(
        source_records=src, destination_records=dst, supported_types=SUPPORTED
    )
    assert len(diff.to_update) == 1 and diff.to_update[0].type == "MX"
    assert len(diff.to_delete) == 1 and diff.to_delete[0].name == "www"
    assert diff.to_create == []
    # NS not touched.
    assert all(r.type != "NS" for r in diff.to_delete)
