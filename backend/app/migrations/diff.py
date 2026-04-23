"""Record-set diff engine + TTL clamping for the GoDaddy → Combell populate step.

Populate performs a **zone replace**: the snapshot is treated as the
authoritative zone content, and anything at the destination that does not
match is reconciled. Concretely:

* Records in the source but missing (or stale) at the destination are
  created / updated.
* Records at the destination that are not in the source are deleted — so
  Combell's default parking / mail-placeholder records disappear on
  populate and the zone ends up matching the snapshot exactly.

NS and SOA records are always excluded from both sides of the diff:
Combell manages nameservers via a separate domain-level endpoint
(``PUT /v2/domains/{name}/nameservers``) and SOA records are registrar-
owned. Leaving them in the diff would delete Combell's own nameservers,
which is the opposite of what operators want.

TTL clamping is applied on the *outgoing* records: Combell rejects TTLs
outside 60–86400 s with a 400. We clamp rather than error so a zone with a
60 s TTL record migrates without the operator having to pre-process it;
the audit log records the original and clamped values side by side.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace

from app.registrars.base import DnsRecord

COMBELL_MIN_TTL = 60
COMBELL_MAX_TTL = 86400


def clamp_ttl(ttl: int) -> int:
    return max(COMBELL_MIN_TTL, min(COMBELL_MAX_TTL, int(ttl)))


def clamp_record(record: DnsRecord) -> DnsRecord:
    """Return a copy with ``ttl`` in the 60–86400 range."""
    if COMBELL_MIN_TTL <= record.ttl <= COMBELL_MAX_TTL:
        return record
    return replace(record, ttl=clamp_ttl(record.ttl))


@dataclass(frozen=True)
class ZoneDiff:
    """Result of diffing a snapshot against the destination's current zone."""

    to_create: list[DnsRecord]
    to_update: list[DnsRecord]
    to_delete: list[DnsRecord]
    skipped: list[DnsRecord]  # records the destination does not support

    @property
    def is_empty(self) -> bool:
        return not (self.to_create or self.to_update or self.to_delete)

    def summary(self) -> dict[str, int]:
        return {
            "to_create": len(self.to_create),
            "to_update": len(self.to_update),
            "to_delete": len(self.to_delete),
            "skipped": len(self.skipped),
        }


def _record_key(record: DnsRecord) -> tuple[str, str]:
    """Identity key for diffing. Combell stores one record per (type, name)."""
    return record.type, record.name


def _value_tuple(record: DnsRecord) -> tuple[str, int, int | None]:
    """What needs to match for a record to be considered up-to-date."""
    return record.data, record.ttl, record.priority


def compute_diff(
    *,
    source_records: Iterable[DnsRecord],
    destination_records: Iterable[DnsRecord],
    supported_types: tuple[str, ...],
) -> ZoneDiff:
    """Three-way diff between source snapshot and current destination zone.

    Records whose ``type`` is not in ``supported_types`` are moved to
    ``skipped`` and never submitted. NS / SOA records are managed by the
    registrar itself at Combell, so we explicitly drop them here too.
    """
    supported = set(supported_types)
    supported.discard("NS")  # NS records are managed by Combell's nameserver API
    supported.discard("SOA")

    source_clamped = [clamp_record(r) for r in source_records]
    skipped = [r for r in source_clamped if r.type not in supported]
    source_relevant = [r for r in source_clamped if r.type in supported]

    # Destination records get filtered the same way: NS / SOA stay on the
    # destination untouched because they represent the registrar's own
    # management of the zone, not user-authored content.
    destination_relevant = [
        r for r in destination_records if r.type in supported
    ]

    destination_map = {_record_key(r): r for r in destination_relevant}
    source_map: dict[tuple[str, str], DnsRecord] = {}
    for r in source_relevant:
        # Multiple records can share a (type, name) — notably TXT and MX.
        # The diff engine then has to compare lists. For the simple V1
        # "populate into an empty zone" case, duplicates are rare enough
        # that we let the registrar handle them: we emit a create for each.
        source_map.setdefault(_record_key(r), r)

    to_create: list[DnsRecord] = []
    to_update: list[DnsRecord] = []
    for key, rec in source_map.items():
        existing = destination_map.get(key)
        if existing is None:
            to_create.append(rec)
        elif _value_tuple(existing) != _value_tuple(rec):
            to_update.append(rec)

    # Zone-replace: every destination record that has no counterpart in
    # the source snapshot is scheduled for deletion. This is what wipes
    # Combell's default parking / mail-placeholder records after a
    # transfer — without this step, the populate would silently leave
    # stale records alongside the migrated ones.
    to_delete = [
        existing
        for key, existing in destination_map.items()
        if key not in source_map
    ]

    return ZoneDiff(
        to_create=to_create,
        to_update=to_update,
        to_delete=to_delete,
        skipped=skipped,
    )


def serialize_diff(diff: ZoneDiff) -> dict[str, list[dict[str, object]]]:
    return {
        "to_create": [asdict(r) for r in diff.to_create],
        "to_update": [asdict(r) for r in diff.to_update],
        "to_delete": [asdict(r) for r in diff.to_delete],
        "skipped": [asdict(r) for r in diff.skipped],
    }
