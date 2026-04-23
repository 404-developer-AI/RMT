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


def test_diff_ignores_priority_on_non_priority_types() -> None:
    """Combell returns priority=10 on every A / TXT read even though we
    never set it. A strict tuple compare then loops on phantom updates.
    The diff must treat priority as irrelevant outside MX / SRV."""
    src = [
        DnsRecord(type="A", name="@", data="1.2.3.4", ttl=3600, priority=None),
        DnsRecord(type="TXT", name="@", data="v=spf1 -all", ttl=3600, priority=None),
    ]
    dst = [
        DnsRecord(type="A", name="@", data="1.2.3.4", ttl=3600, priority=10),
        DnsRecord(type="TXT", name="@", data="v=spf1 -all", ttl=3600, priority=10),
    ]
    diff = compute_diff(
        source_records=src, destination_records=dst, supported_types=SUPPORTED
    )
    assert diff.is_empty, "priority default should not cause a mismatch"


def test_diff_still_respects_priority_for_mx_records() -> None:
    src = [DnsRecord(type="MX", name="@", data="mail.example.com", ttl=3600, priority=10)]
    dst = [DnsRecord(type="MX", name="@", data="mail.example.com", ttl=3600, priority=20)]
    diff = compute_diff(
        source_records=src, destination_records=dst, supported_types=SUPPORTED
    )
    assert len(diff.to_update) == 1


def test_diff_deletes_extra_mx_at_same_name() -> None:
    """Combell ships a backup MX (``mx.backup.mailprotect.be``) alongside the
    operator's imported MX. Keying the diff on (type, name) alone used to
    collapse both destination MX records into a single slot so the backup
    silently survived. The diff must treat (type, name) as a multiset."""
    src = [
        DnsRecord(type="MX", name="@", data="mail.example.com", ttl=3600, priority=10),
    ]
    dst = [
        DnsRecord(type="MX", name="@", data="mail.example.com", ttl=3600, priority=10),
        # Combell default — must be scheduled for deletion.
        DnsRecord(
            type="MX", name="@", data="mx.backup.mailprotect.be", ttl=3600, priority=50
        ),
    ]
    diff = compute_diff(
        source_records=src, destination_records=dst, supported_types=SUPPORTED
    )
    assert diff.to_create == []
    assert diff.to_update == []
    assert len(diff.to_delete) == 1
    assert diff.to_delete[0].data == "mx.backup.mailprotect.be"


def test_diff_multi_value_txt_records_match_by_content() -> None:
    """SPF + DKIM commonly share (TXT, @) — each must match by value, not
    collapse under a single key."""
    spf = DnsRecord(
        type="TXT", name="@", data="v=spf1 include:_spf.example -all", ttl=3600
    )
    dkim = DnsRecord(type="TXT", name="@", data="v=DKIM1; p=MIG...", ttl=3600)
    src = [spf, dkim]
    dst = [dkim, spf]  # same set, different ordering
    diff = compute_diff(
        source_records=src, destination_records=dst, supported_types=SUPPORTED
    )
    assert diff.is_empty


def test_diff_multi_value_txt_with_extra_record_schedules_delete() -> None:
    """Two TXT at the same name, destination has a third — extra -> delete."""
    spf = DnsRecord(type="TXT", name="@", data="v=spf1 -all", ttl=3600)
    dkim = DnsRecord(type="TXT", name="@", data="v=DKIM1; p=AAA", ttl=3600)
    verification = DnsRecord(
        type="TXT", name="@", data="google-site-verification=old", ttl=3600
    )
    src = [spf, dkim]
    dst = [spf, dkim, verification]
    diff = compute_diff(
        source_records=src, destination_records=dst, supported_types=SUPPORTED
    )
    assert diff.to_create == []
    assert diff.to_update == []
    assert [r.data for r in diff.to_delete] == [verification.data]


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
