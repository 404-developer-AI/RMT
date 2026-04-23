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
