"""Local fixture responses for the GoDaddy adapter's ``mock=True`` mode.

Everything here is deliberately obvious — ``example.com``, ``fixture.be``,
ASCII phone numbers — so a leaked fixture can never be mistaken for a
customer record. CI and dev machines without credentials hit these so the
full migration flow can be exercised end to end without live calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


def _now() -> datetime:
    return datetime.now(tz=UTC)


def fixture_domains() -> list[dict[str, Any]]:
    """Two domains: a gTLD eligible to transfer, a .be, plus one locked."""
    now = _now()
    return [
        {
            "domain": "example.com",
            "status": "ACTIVE",
            "locked": False,
            "privacy": False,
            "expires": (now + timedelta(days=200)).isoformat(),
            "transferAwayEligibleAt": (now - timedelta(days=10)).isoformat(),
            "nameServers": ["ns1.godaddy.com", "ns2.godaddy.com"],
            "authCode": "fixture-auth-code-example-com",
        },
        {
            "domain": "fixture.be",
            "status": "ACTIVE",
            "locked": False,
            "privacy": False,
            "expires": (now + timedelta(days=150)).isoformat(),
            "transferAwayEligibleAt": None,
            "nameServers": ["ns1.godaddy.com", "ns2.godaddy.com"],
            "authCode": None,
        },
        {
            "domain": "locked-example.com",
            "status": "ACTIVE",
            "locked": True,
            "privacy": True,
            "expires": (now + timedelta(days=30)).isoformat(),
            "transferAwayEligibleAt": (now + timedelta(days=40)).isoformat(),
            "nameServers": ["ns1.godaddy.com", "ns2.godaddy.com"],
            "authCode": None,
        },
    ]


def fixture_domain_detail(name: str) -> dict[str, Any]:
    for row in fixture_domains():
        if row["domain"] == name:
            # GoDaddy v1 shape: contact roles at top level, not nested.
            return {
                **row,
                **_fixture_contacts(),
                "transferProtected": row["locked"],
            }
    raise KeyError(f"No fixture for domain {name!r}")


def _fixture_contacts() -> dict[str, Any]:
    common = {
        "nameFirst": "Fixture",
        "nameLast": "Operator",
        "email": "fixture@example.com",
        "phone": "+32.12345678",
        "addressMailing": {
            "address1": "1 Fixture Street",
            "city": "Brussels",
            "postalCode": "1000",
            "country": "BE",
        },
    }
    return {
        "contactRegistrant": common,
        "contactAdmin": common,
        "contactTech": common,
        "contactBilling": common,
    }


def fixture_dns_records(name: str) -> list[dict[str, Any]]:
    if name == "example.com":
        return [
            {"type": "A", "name": "@", "data": "192.0.2.10", "ttl": 3600},
            {"type": "A", "name": "www", "data": "192.0.2.10", "ttl": 3600},
            {"type": "MX", "name": "@", "data": "mail.example.com", "ttl": 3600, "priority": 10},
            {"type": "TXT", "name": "@", "data": "v=spf1 -all", "ttl": 3600},
            {"type": "CNAME", "name": "blog", "data": "example.com", "ttl": 3600},
        ]
    if name == "fixture.be":
        return [
            {"type": "A", "name": "@", "data": "198.51.100.5", "ttl": 3600},
            {"type": "AAAA", "name": "@", "data": "2001:db8::5", "ttl": 3600},
        ]
    return []
