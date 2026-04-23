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

from collections import defaultdict
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
    """Group key for diffing. A single (type, name) can hold MULTIPLE records
    — MX with different priorities, TXT with SPF + DKIM, NS with several
    nameservers. The diff groups by this key and then matches records
    within each group by value, so duplicates never collapse into one slot.
    """
    return record.type, record.name


#: Record types where the ``priority`` field is semantically meaningful.
#: Everything else either ignores priority (A / AAAA / CNAME / TXT / CAA /
#: ALIAS / TLSA) or stores it in a type-specific sub-field we do not model
#: yet (SRV uses ``service`` / ``weight`` / ``target`` alongside the
#: priority). Combell's DnsRecord schema defaults ``priority`` to ``10``
#: on every read — including A/TXT — so comparing source (``None``) to
#: destination (``10``) produced a phantom "update needed" verdict for
#: every non-MX record after a round-trip.
_PRIORITY_TYPES = frozenset({"MX", "SRV"})


def _value_tuple(record: DnsRecord) -> tuple[str, int, int | None]:
    """What needs to match for a record to be considered up-to-date."""
    priority = record.priority if record.type in _PRIORITY_TYPES else None
    return record.data, record.ttl, priority


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

    A single ``(type, name)`` can legitimately hold multiple records. The
    diff groups both sides by that key and then matches records within a
    group by value (``data`` + ``ttl`` + priority-if-applicable):

    * One-to-one at a key with differing value -> in-place ``update`` so
      we keep Combell's record id and issue a single PUT.
    * Several records on either side -> every unmatched source record
      becomes a ``create`` and every unmatched destination record a
      ``delete``. This is what catches Combell's default
      ``mx.backup.mailprotect.be`` secondary MX that sits next to the
      operator's own MX and otherwise never shows up in the diff.
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

    source_by_key: dict[tuple[str, str], list[DnsRecord]] = defaultdict(list)
    for r in source_relevant:
        source_by_key[_record_key(r)].append(r)

    dest_by_key: dict[tuple[str, str], list[DnsRecord]] = defaultdict(list)
    for r in destination_relevant:
        dest_by_key[_record_key(r)].append(r)

    to_create: list[DnsRecord] = []
    to_update: list[DnsRecord] = []
    to_delete: list[DnsRecord] = []

    for key in set(source_by_key) | set(dest_by_key):
        s_list = source_by_key.get(key, [])
        d_list = dest_by_key.get(key, [])

        if len(s_list) == 1 and len(d_list) == 1:
            # Exactly one record on each side — preserve the id-preserving
            # in-place update path. Combell's PUT is cheaper than DELETE +
            # POST and avoids a brief NXDOMAIN window for the record.
            s, d = s_list[0], d_list[0]
            if _value_tuple(s) != _value_tuple(d):
                to_update.append(replace(s, id=d.id))
            continue

        # Multi-value or one-sided: walk the source list, consume matching
        # destination records by value, and treat the rest as create /
        # delete. Update-in-place would need a heuristic to pair "old"
        # with "new" and that is not worth the ambiguity here.
        d_remaining = list(d_list)
        for s in s_list:
            value = _value_tuple(s)
            match_index = next(
                (i for i, d in enumerate(d_remaining) if _value_tuple(d) == value),
                None,
            )
            if match_index is None:
                to_create.append(s)
            else:
                d_remaining.pop(match_index)
        to_delete.extend(d_remaining)

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
