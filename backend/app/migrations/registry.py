"""Migration-type registry — maps a string key to a (source, destination) pair.

The key is what the UI shows in the dropdown and what gets persisted in
``migration_plans.migration_type`` so the audit log can answer "which
adapter pair handled this migration?". Adding a new pair (e.g.
``namecheap_to_combell``) means writing the two adapters and calling
:func:`register_migration_type` on import — no other dispatch code needs to
change.

V1 ships exactly one entry: ``godaddy_to_combell``. The UI auto-selects when
only one is registered but still shows the dropdown so the pattern is
visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MigrationType:
    """One source→destination adapter pair, exposed to the UI."""

    key: str
    label: str
    source_provider: str
    destination_provider: str
    description: str = ""
    #: TLD-specific auth-code hints, keyed by TLD (without the dot). The
    #: empty-string key is the default for any TLD not listed.
    auth_code_hints: dict[str, str] = field(default_factory=dict)


MIGRATION_TYPES: dict[str, MigrationType] = {}


def register_migration_type(migration_type: MigrationType) -> MigrationType:
    """Register a migration type. Raises on duplicate keys."""
    if migration_type.key in MIGRATION_TYPES:
        raise ValueError(f"Migration type already registered: {migration_type.key!r}")
    MIGRATION_TYPES[migration_type.key] = migration_type
    return migration_type


def get_migration_type(key: str) -> MigrationType:
    """Look up a registered migration type. Raises ``KeyError`` if unknown."""
    try:
        return MIGRATION_TYPES[key]
    except KeyError as exc:
        raise KeyError(f"Unknown migration type: {key!r}") from exc


def list_migration_types() -> list[MigrationType]:
    """Stable ordering — registration order — for UI display."""
    return list(MIGRATION_TYPES.values())


# --- V1 entries -------------------------------------------------------------

register_migration_type(
    MigrationType(
        key="godaddy_to_combell",
        label="GoDaddy → Combell",
        source_provider="godaddy",
        destination_provider="combell",
        description=(
            "Full ICANN transfer-in from GoDaddy to Combell. Operator pastes "
            "the auth code; Combell's default nameservers are assigned "
            "atomically with the transfer."
        ),
        auth_code_hints={
            "": "Copy the auth code from the GoDaddy console (Domain Settings → Transfer).",
            "be": (
                "Request the auth code at dnsbelgium.be/en/transfer-code. "
                "Format: 5 groups of 3 digits (e.g. 123-456-789-012-345). "
                "Valid for 7 days; max 4 requests per 7 days per domain."
            ),
        },
    )
)
