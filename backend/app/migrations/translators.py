"""Per-migration-type translators between registrar-specific DTO shapes.

The migration engine keeps its orchestration generic, but every pair of
(source, destination) adapters speaks slightly different JSON for the
same concept — a registrant contact block, say, where GoDaddy returns
``nameFirst`` + ``addressMailing.postalCode`` while Combell expects
``first_name`` + ``postal_code``. The translation belongs here, close to
the migration-type registry, so the engine stays agnostic.

V1 ships one translator: ``godaddy_to_combell_registrant``. The
:func:`translate_registrant` dispatcher routes on the migration-type key
so new pairs slot in without a branch in the engine.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from app.registrars.base import DnsRecord

# Cosmetic separators operators tend to sprinkle into phone numbers.
# We strip these but leave ``+`` and ``.`` alone because those are
# meaningful in Combell's ``+CC.N`` syntax.
_PHONE_SEPARATORS_RE = re.compile(r"[\s()\-/]")


def _normalize_phone(raw: str | None) -> str:
    """Trim cosmetic separators and map ``00CC`` to ``+CC``.

    Combell accepts ``+CC.N`` — a literal dot between country code and
    subscriber number. GoDaddy's own API already stores phone numbers in
    that dotted form, so the common case is a straight pass-through. The
    only transformations we make here are the ones that are safe without
    a country-code table:

    * strip whitespace / parens / hyphens / slashes,
    * turn a leading ``00`` into ``+`` (operator shorthand),
    * keep any existing dot.

    We deliberately do NOT try to guess where the country code ends in an
    unpunctuated number: country codes are 1–3 digits and a wrong guess
    produces a subtly incorrect value Combell will reject without telling
    the operator why. If the source lacks a dot, the string is returned
    verbatim (separators stripped) and the operator fixes it upstream —
    Combell's 400 response then surfaces via the adapter's error path.
    """
    if not raw:
        return ""
    stripped = _PHONE_SEPARATORS_RE.sub("", raw)
    if not stripped:
        return ""
    if stripped.startswith("00"):
        stripped = "+" + stripped[2:]
    return stripped


def _join_address(address_mailing: dict[str, Any]) -> str:
    """Collapse GoDaddy's multi-line address into a single Combell ``address``."""
    parts = [
        address_mailing.get("address1"),
        address_mailing.get("address2"),
    ]
    return " ".join(p for p in parts if p).strip()


def godaddy_to_combell_registrant(raw: dict[str, Any]) -> dict[str, Any]:
    """Translate a GoDaddy ``contactRegistrant`` block into Combell's
    ``RegistrantInput`` schema.

    Fields map one-to-one where names allow; the address block flattens
    from ``addressMailing.*`` to the top level, and the country code is
    upper-cased to match Combell's ``'BE', 'NL', ...`` syntax. Missing
    optional fields are omitted so Combell does not receive empty-string
    values it would have to interpret.
    """
    addr = raw.get("addressMailing") or {}
    out: dict[str, Any] = {
        "first_name": raw.get("nameFirst") or "",
        "last_name": raw.get("nameLast") or "",
        "email": raw.get("email") or "",
        "phone": _normalize_phone(raw.get("phone")),
        "address": _join_address(addr),
        "postal_code": addr.get("postalCode") or "",
        "city": addr.get("city") or "",
        "country_code": (addr.get("country") or "").upper(),
        # GoDaddy does not expose a registrant language — default to English
        # which is Combell's universally accepted value. The operator can
        # change it in Combell's panel after the transfer lands.
        "language_code": "en",
    }
    org = raw.get("organization")
    if org:
        out["company_name"] = org
    fax = _normalize_phone(raw.get("fax"))
    if fax:
        out["fax"] = fax
    return out


# Record types whose ``data`` field is a hostname / FQDN. GoDaddy lets
# operators use ``@`` there as shorthand for the apex; Combell rejects
# that form with ``dns_invalid_content`` and expects the literal domain.
_HOSTNAME_CONTENT_TYPES = frozenset({"CNAME", "ALIAS", "MX"})


# GoDaddy auto-provisions a few records that only make sense inside its own
# control plane and have no meaning at another registrar:
#
# * **CNAMEs** pointing at ``*.domaincontrol.com`` — the Domain Connect
#   discovery record (``_domainconnect``), ``autodiscover``, and similar
#   GoDaddy-internal hostnames.
# * **A records** with ``data == "Parked"`` — a GoDaddy panel artefact for
#   domains without a real DNS setup. The string is not a valid IP and
#   Combell rejects it with ``dns_invalid_content`` (400) at populate
#   time, so filtering it before the diff avoids breaking the whole
#   populate step over a placeholder.
#
# A warning-level pre-flight check flags the parking placeholder so the
# operator knows they need to configure an apex A at Combell after the
# transfer lands — see :mod:`app.migrations.preflight`.
_GODADDY_INTERNAL_HOSTNAME_SUFFIXES = ("domaincontrol.com",)
_GODADDY_PARKED_SENTINEL = "parked"


def _is_godaddy_internal_record(record: DnsRecord) -> bool:
    """Return True for records that only belong in a GoDaddy-hosted zone."""
    data = (record.data or "").strip().lower()
    if not data:
        return False
    if record.type == "CNAME":
        target = data.rstrip(".")
        return any(
            target == suffix or target.endswith("." + suffix)
            for suffix in _GODADDY_INTERNAL_HOSTNAME_SUFFIXES
        )
    return record.type == "A" and data == _GODADDY_PARKED_SENTINEL


def godaddy_to_combell_record(record: DnsRecord, *, domain: str) -> DnsRecord:
    """Translate one GoDaddy-shaped DNS record into Combell's expectations.

    The only substitution we need for V1 is resolving the apex shorthand:
    GoDaddy accepts ``@`` in the ``data`` field of CNAME / ALIAS / MX
    records to mean "the domain itself", Combell does not. The name-side
    (``record_name``) ``@`` is fine on both sides because both registrars
    treat it as "the apex".

    Leaves the record unchanged when the ``data`` is empty or when the
    record type does not use a hostname in its content (A, AAAA, TXT, …).
    """
    if record.type not in _HOSTNAME_CONTENT_TYPES:
        return record
    data = (record.data or "").strip()
    if data == "@":
        return replace(record, data=domain)
    # GoDaddy sometimes stores a CNAME target without the trailing dot
    # (e.g. "parking.godaddy.com"); Combell accepts both, so leave it.
    return record


def godaddy_to_combell_records(
    records: list[DnsRecord], *, domain: str
) -> list[DnsRecord]:
    return [
        godaddy_to_combell_record(r, domain=domain)
        for r in records
        if not _is_godaddy_internal_record(r)
    ]


# --- dispatch --------------------------------------------------------------


_REGISTRANT_TRANSLATORS: dict[str, Any] = {
    "godaddy_to_combell": godaddy_to_combell_registrant,
}

_RECORD_TRANSLATORS: dict[str, Any] = {
    "godaddy_to_combell": godaddy_to_combell_records,
}


def translate_registrant(migration_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Run the registrar-pair-specific translator; pass through if none exists."""
    translator = _REGISTRANT_TRANSLATORS.get(migration_type)
    if translator is None:
        return raw
    return translator(raw)


def translate_records(
    migration_type: str, records: list[DnsRecord], *, domain: str
) -> list[DnsRecord]:
    """Run the pair-specific record translator; pass through if none exists."""
    translator = _RECORD_TRANSLATORS.get(migration_type)
    if translator is None:
        return records
    return translator(records, domain=domain)
