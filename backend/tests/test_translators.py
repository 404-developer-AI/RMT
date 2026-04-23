"""Tests for the per-migration-type DTO translators."""

from __future__ import annotations

from app.migrations.translators import (
    _normalize_phone,
    godaddy_to_combell_registrant,
    translate_registrant,
)


def test_godaddy_to_combell_registrant_happy_path() -> None:
    raw = {
        "nameFirst": "Ada",
        "nameLast": "Lovelace",
        "email": "ada@example.com",
        "phone": "+32.123456789",
        "organization": "Analytical Engines NV",
        "addressMailing": {
            "address1": "1 Fixture Street",
            "address2": "Box 3",
            "city": "Brussels",
            "postalCode": "1000",
            "country": "be",
        },
    }
    out = godaddy_to_combell_registrant(raw)
    assert out["first_name"] == "Ada"
    assert out["last_name"] == "Lovelace"
    assert out["email"] == "ada@example.com"
    assert out["phone"] == "+32.123456789"
    assert out["address"] == "1 Fixture Street Box 3"
    assert out["postal_code"] == "1000"
    assert out["city"] == "Brussels"
    assert out["country_code"] == "BE"
    assert out["language_code"] == "en"
    assert out["company_name"] == "Analytical Engines NV"


def test_godaddy_to_combell_registrant_omits_optional_empties() -> None:
    raw = {
        "nameFirst": "Grace",
        "nameLast": "Hopper",
        "email": "grace@example.com",
        "addressMailing": {
            "address1": "1 Test Rd",
            "city": "Arlington",
            "postalCode": "22201",
            "country": "US",
        },
    }
    out = godaddy_to_combell_registrant(raw)
    assert "company_name" not in out
    assert "fax" not in out
    assert out["phone"] == ""  # explicitly preserved — required field in schema


def test_phone_normalizer_passes_dotted_form_through() -> None:
    assert _normalize_phone("+32.123456789") == "+32.123456789"


def test_phone_normalizer_strips_cosmetic_separators() -> None:
    # Dot preserved; spaces / parens / hyphens gone.
    assert _normalize_phone("+32.(0) 123 45-67-89") == "+32.0123456789"


def test_phone_normalizer_converts_double_zero_prefix() -> None:
    assert _normalize_phone("0032.123456789") == "+32.123456789"


def test_phone_normalizer_does_not_invent_a_dot() -> None:
    # Intentionally preserves the dot-less form so the operator can see
    # Combell reject it upstream rather than the translator guessing wrong.
    assert _normalize_phone("+32123456789") == "+32123456789"


def test_phone_normalizer_empty_returns_empty() -> None:
    assert _normalize_phone(None) == ""
    assert _normalize_phone("") == ""


def test_dispatch_passes_through_unknown_migration_type() -> None:
    raw = {"email": "foo@example.com"}
    out = translate_registrant("totally_unknown_pair", raw)
    assert out is raw


def test_dispatch_routes_to_godaddy_to_combell() -> None:
    raw = {
        "nameFirst": "Ada",
        "nameLast": "Lovelace",
        "email": "ada@example.com",
        "addressMailing": {
            "address1": "1 Fixture",
            "city": "Brussels",
            "postalCode": "1000",
            "country": "BE",
        },
    }
    out = translate_registrant("godaddy_to_combell", raw)
    assert out["first_name"] == "Ada"
    assert out["country_code"] == "BE"
