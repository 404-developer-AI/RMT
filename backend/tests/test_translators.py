"""Tests for the per-migration-type DTO translators."""

from __future__ import annotations

from app.migrations.translators import (
    _normalize_phone,
    godaddy_to_combell_record,
    godaddy_to_combell_registrant,
    translate_records,
    translate_registrant,
)
from app.registrars.base import DnsRecord


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


# --- record translator ----------------------------------------------------


def test_cname_at_is_resolved_to_domain() -> None:
    """GoDaddy stores CNAME target of `@` meaning the apex; Combell refuses."""
    rec = DnsRecord(type="CNAME", name="www", data="@", ttl=3600)
    out = godaddy_to_combell_record(rec, domain="example.com")
    assert out.data == "example.com"


def test_mx_at_is_resolved_to_domain() -> None:
    rec = DnsRecord(type="MX", name="@", data="@", ttl=3600, priority=10)
    out = godaddy_to_combell_record(rec, domain="example.com")
    assert out.data == "example.com"
    assert out.priority == 10


def test_cname_with_concrete_hostname_is_untouched() -> None:
    rec = DnsRecord(type="CNAME", name="blog", data="hosting.example.net", ttl=3600)
    assert godaddy_to_combell_record(rec, domain="example.com") is rec


def test_a_record_with_at_is_left_alone() -> None:
    # @ in the NAME side is the apex; @ in the DATA side of an A record
    # would be nonsensical and should not be touched (it would 400, which
    # is exactly the signal the operator needs).
    rec = DnsRecord(type="A", name="@", data="1.2.3.4", ttl=3600)
    out = godaddy_to_combell_record(rec, domain="example.com")
    assert out is rec


def test_translate_records_routes_to_godaddy_to_combell() -> None:
    src = [DnsRecord(type="CNAME", name="www", data="@", ttl=3600)]
    out = translate_records("godaddy_to_combell", src, domain="example.com")
    assert out[0].data == "example.com"


def test_translate_records_passes_through_unknown_pair() -> None:
    src = [DnsRecord(type="CNAME", name="www", data="@", ttl=3600)]
    out = translate_records("totally_unknown", src, domain="example.com")
    assert out is src


# --- GoDaddy-internal record filter ---------------------------------------


def test_domainconnect_cname_is_filtered_out() -> None:
    """GoDaddy's Domain Connect discovery CNAME must not land at Combell."""
    src = [
        DnsRecord(
            type="CNAME",
            name="_domainconnect",
            data="_domainconnect.gd.domaincontrol.com",
            ttl=3600,
        ),
        DnsRecord(type="A", name="@", data="1.2.3.4", ttl=3600),
    ]
    out = translate_records("godaddy_to_combell", src, domain="example.com")
    assert [r.name for r in out] == ["@"]


def test_any_cname_into_domaincontrol_is_filtered() -> None:
    """Any *.domaincontrol.com target is GoDaddy-owned infrastructure."""
    src = [
        DnsRecord(
            type="CNAME", name="autodiscover", data="autodiscover.domaincontrol.com", ttl=3600
        ),
        DnsRecord(type="CNAME", name="blog", data="blog.example.net", ttl=3600),
    ]
    out = translate_records("godaddy_to_combell", src, domain="example.com")
    assert [r.name for r in out] == ["blog"]


def test_cname_ending_in_lookalike_domain_is_kept() -> None:
    """Only the real ``domaincontrol.com`` suffix gets filtered — not a
    user-owned domain that happens to end with the same letters."""
    src = [
        DnsRecord(
            type="CNAME", name="www", data="fakedomaincontrol.com", ttl=3600
        ),
    ]
    out = translate_records("godaddy_to_combell", src, domain="example.com")
    assert len(out) == 1


def test_filter_ignores_trailing_dot_and_casing() -> None:
    src = [
        DnsRecord(
            type="CNAME",
            name="_domainconnect",
            data="_domainconnect.GD.Domaincontrol.COM.",
            ttl=3600,
        ),
    ]
    out = translate_records("godaddy_to_combell", src, domain="example.com")
    assert out == []


def test_non_cname_pointing_at_domaincontrol_is_untouched() -> None:
    """TXT / A records are not filtered — only CNAMEs are GoDaddy-internal."""
    src = [
        DnsRecord(
            type="TXT", name="@", data="some-random-domaincontrol.com value", ttl=3600
        ),
    ]
    out = translate_records("godaddy_to_combell", src, domain="example.com")
    assert len(out) == 1


def test_parked_a_record_is_filtered_out() -> None:
    """GoDaddy returns ``data: "Parked"`` for domains without real DNS —
    a panel artefact that would 400 at Combell (not a valid IP)."""
    src = [
        DnsRecord(type="A", name="@", data="Parked", ttl=600),
        DnsRecord(type="A", name="www", data="1.2.3.4", ttl=3600),
    ]
    out = translate_records("godaddy_to_combell", src, domain="example.com")
    assert [r.data for r in out] == ["1.2.3.4"]


def test_parked_filter_is_case_insensitive_and_trims_whitespace() -> None:
    src = [
        DnsRecord(type="A", name="@", data="parked", ttl=600),
        DnsRecord(type="A", name="a", data="PARKED", ttl=600),
        DnsRecord(type="A", name="b", data="  Parked  ", ttl=600),
    ]
    out = translate_records("godaddy_to_combell", src, domain="example.com")
    assert out == []


def test_parked_filter_only_matches_exact_value() -> None:
    """Substring match would be too greedy. Only exact 'Parked' counts."""
    src = [DnsRecord(type="A", name="@", data="1.2.3.Parked", ttl=3600)]
    out = translate_records("godaddy_to_combell", src, domain="example.com")
    assert len(out) == 1


def test_parked_filter_does_not_touch_non_a_records() -> None:
    """TXT with literal 'Parked' is user-authored; keep it."""
    src = [DnsRecord(type="TXT", name="@", data="Parked", ttl=3600)]
    out = translate_records("godaddy_to_combell", src, domain="example.com")
    assert len(out) == 1
