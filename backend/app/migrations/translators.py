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
from typing import Any

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


# --- dispatch --------------------------------------------------------------


_REGISTRANT_TRANSLATORS: dict[str, Any] = {
    "godaddy_to_combell": godaddy_to_combell_registrant,
}


def translate_registrant(migration_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Run the registrar-pair-specific translator; pass through if none exists."""
    translator = _REGISTRANT_TRANSLATORS.get(migration_type)
    if translator is None:
        return raw
    return translator(raw)
