"""Tests for the migration-type registry."""

from __future__ import annotations

import pytest

from app.migrations import (
    MIGRATION_TYPES,
    MigrationType,
    get_migration_type,
    list_migration_types,
    register_migration_type,
)


def test_v1_ships_godaddy_to_combell() -> None:
    entry = get_migration_type("godaddy_to_combell")
    assert entry.source_provider == "godaddy"
    assert entry.destination_provider == "combell"
    assert entry.label == "GoDaddy → Combell"


def test_per_tld_auth_code_hint() -> None:
    entry = get_migration_type("godaddy_to_combell")
    assert "dnsbelgium.be" in entry.auth_code_hints["be"]
    assert "GoDaddy console" in entry.auth_code_hints[""]


def test_unknown_key_raises() -> None:
    with pytest.raises(KeyError, match="Unknown migration type"):
        get_migration_type("does_not_exist")


def test_duplicate_registration_rejected() -> None:
    with pytest.raises(ValueError, match="already registered"):
        register_migration_type(
            MigrationType(
                key="godaddy_to_combell",
                label="dup",
                source_provider="x",
                destination_provider="y",
            )
        )


def test_list_returns_at_least_one_entry() -> None:
    entries = list_migration_types()
    assert any(e.key == "godaddy_to_combell" for e in entries)
    assert MIGRATION_TYPES is not None
