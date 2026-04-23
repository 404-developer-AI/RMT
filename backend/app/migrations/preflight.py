"""Per-TLD pre-flight checks for a GoDaddy → Combell migration.

The runner takes a :class:`DomainDetail` + the zone's DNS records and
evaluates a list of rules. Each rule returns a :class:`CheckResult` with
``severity`` of ``blocking`` or ``warning``. The UI blocks the confirm
button until every *blocking* check passes; warnings are dismissable.

Two rule sets ship in V1:

* **gTLD** (any TLD that is not ``.be``) — unlocked, not transferProtected,
  privacy off, registrant email present, ICANN 60-day rule, expiry > 15
  days, and a warning for zones that may contain CAA records (GoDaddy v1
  cannot read them).
* **.be** — unlocked, not transferProtected, registrant email present.
  Privacy is a warning (DNSBelgium rejects transfers when WHOIS privacy is
  on, but a surprising number of ``.be`` domains never had privacy
  available, so we warn instead of block).

Adding a third TLD rule set (e.g. ``.nl``) is an append-only change — the
runner picks the rule set by TLD and falls back to ``gTLD`` when the TLD
is unknown.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.registrars.base import DnsRecord, DomainDetail

Severity = Literal["blocking", "warning"]


@dataclass(frozen=True)
class CheckResult:
    """One row in the pre-flight report."""

    key: str
    severity: Severity
    ok: bool
    message: str


@dataclass(frozen=True)
class PreflightReport:
    """Aggregated pre-flight result for a single domain."""

    domain: str
    tld: str
    ruleset: str
    results: list[CheckResult] = field(default_factory=list)

    @property
    def blocking_failures(self) -> list[CheckResult]:
        return [r for r in self.results if r.severity == "blocking" and not r.ok]

    @property
    def warnings(self) -> list[CheckResult]:
        return [r for r in self.results if r.severity == "warning" and not r.ok]

    @property
    def passed(self) -> bool:
        return not self.blocking_failures


def extract_tld(domain: str) -> str:
    """Trailing label, without the dot and lowercased."""
    return domain.rsplit(".", 1)[-1].lower() if "." in domain else domain.lower()


def run_preflight(
    detail: DomainDetail,
    records: Sequence[DnsRecord],
    *,
    now: datetime | None = None,
) -> PreflightReport:
    """Evaluate the correct rule set for the domain's TLD."""
    tld = extract_tld(detail.name)
    ruleset = "be" if tld == "be" else "gtld"
    checks = _run_common(detail, records, now=now or datetime.now(tz=UTC))
    if ruleset == "gtld":
        checks.extend(_run_gtld_only(detail, now=now or datetime.now(tz=UTC)))
    else:
        checks.extend(_run_be_only(detail))
    return PreflightReport(domain=detail.name, tld=tld, ruleset=ruleset, results=checks)


# --- rules ------------------------------------------------------------------


def _run_common(
    detail: DomainDetail,
    records: Sequence[DnsRecord],
    *,
    now: datetime,
) -> list[CheckResult]:
    results: list[CheckResult] = []

    results.append(
        CheckResult(
            key="domain.unlocked",
            severity="blocking",
            ok=not detail.locked,
            message=(
                "Domain is not registrar-locked."
                if not detail.locked
                else (
                    "Domain is locked at the registrar. Unlock it in the "
                    "GoDaddy console before transferring."
                )
            ),
        )
    )

    results.append(
        CheckResult(
            key="domain.not_transfer_protected",
            severity="blocking",
            ok=not detail.transfer_protected,
            message=(
                "Transfer protection is off."
                if not detail.transfer_protected
                else (
                    "GoDaddy's transfer-protection add-on is active. "
                    "Disable it before continuing."
                )
            ),
        )
    )

    registrant = detail.contacts.registrant or {}
    email = registrant.get("email") or registrant.get("Email")
    results.append(
        CheckResult(
            key="registrant.email_present",
            severity="blocking",
            ok=bool(email),
            message=(
                f"Registrant email is set ({email})."
                if email
                else (
                    "Registrant email is missing — the destination registrar "
                    "needs it for the transfer confirmation."
                )
            ),
        )
    )

    caa_present = any(r.type == "CAA" for r in records)
    results.append(
        CheckResult(
            key="dns.caa_records",
            severity="warning",
            ok=not caa_present,
            message=(
                "No CAA records detected (or GoDaddy v1 cannot read them). "
                "If you know the zone has CAA, re-create them at Combell after the transfer."
                if not caa_present
                else (
                    "CAA records detected — these may not round-trip via "
                    "GoDaddy v1 and will need manual verification."
                )
            ),
        )
    )

    # GoDaddy returns ``data: "Parked"`` on A records for domains without a
    # real DNS setup — the string is not a valid IP and would 400 at
    # Combell. The translator filters it out of the populate, but we
    # surface a warning so the operator knows to configure an apex A at
    # Combell after the transfer (otherwise the domain won't resolve).
    parking_present = any(
        r.type == "A" and (r.data or "").strip().lower() == "parked"
        for r in records
    )
    results.append(
        CheckResult(
            key="dns.godaddy_parking_placeholder",
            severity="warning",
            ok=not parking_present,
            message=(
                "No GoDaddy parking placeholder detected."
                if not parking_present
                else (
                    "GoDaddy parking placeholder (A @ 'Parked') detected. "
                    "It will be filtered out during populate — configure a "
                    "real apex A record at Combell after the transfer."
                )
            ),
        )
    )

    _ = now  # reserved for future time-based common checks
    return results


def _run_gtld_only(detail: DomainDetail, *, now: datetime) -> list[CheckResult]:
    results: list[CheckResult] = []

    icann_ok = (
        detail.transfer_away_eligible_at is not None
        and detail.transfer_away_eligible_at <= now
    )
    if detail.transfer_away_eligible_at is None:
        msg = (
            "GoDaddy did not report a transferAwayEligibleAt timestamp — "
            "likely still inside the ICANN 60-day window."
        )
    elif icann_ok:
        msg = f"ICANN 60-day rule cleared on {detail.transfer_away_eligible_at.date().isoformat()}."
    else:
        msg = (
            f"ICANN 60-day rule is not yet satisfied — earliest transfer date "
            f"is {detail.transfer_away_eligible_at.date().isoformat()}."
        )
    results.append(
        CheckResult(
            key="icann.sixty_day_rule",
            severity="blocking",
            ok=icann_ok,
            message=msg,
        )
    )

    expiry_ok = detail.expires_at is None or detail.expires_at - now >= timedelta(days=15)
    if detail.expires_at is None:
        expiry_msg = (
            "GoDaddy did not report an expiry — proceeding assuming > 15 days remaining."
        )
    elif expiry_ok:
        expiry_msg = (
            f"Domain expires on {detail.expires_at.date().isoformat()} (>15 days out)."
        )
    else:
        expiry_msg = (
            f"Domain expires on {detail.expires_at.date().isoformat()} — "
            "too close for a safe transfer (<15 days)."
        )
    results.append(
        CheckResult(
            key="domain.expiry_gt_15d",
            severity="blocking",
            ok=expiry_ok,
            message=expiry_msg,
        )
    )

    results.append(
        CheckResult(
            key="domain.privacy_off",
            severity="blocking",
            ok=not detail.privacy,
            message=(
                "Registrant-privacy shield is off."
                if not detail.privacy
                else (
                    "Registrant privacy is on. Disable it so the correct "
                    "WHOIS data is sent with the transfer."
                )
            ),
        )
    )

    return results


def _run_be_only(detail: DomainDetail) -> list[CheckResult]:
    results: list[CheckResult] = []
    results.append(
        CheckResult(
            key="domain.privacy_off",
            severity="warning",
            ok=not detail.privacy,
            message=(
                "Registrant-privacy shield is off."
                if not detail.privacy
                else (
                    "Privacy is on. DNSBelgium may reject the transfer — "
                    "disable before requesting the auth code."
                )
            ),
        )
    )
    return results


def serialize_report(report: PreflightReport) -> dict[str, object]:
    """JSON-friendly shape for the API."""
    return {
        "domain": report.domain,
        "tld": report.tld,
        "ruleset": report.ruleset,
        "passed": report.passed,
        "results": [
            {
                "key": r.key,
                "severity": r.severity,
                "ok": r.ok,
                "message": r.message,
            }
            for r in report.results
        ],
    }


def aggregate_results(results: Iterable[CheckResult]) -> dict[str, int]:
    """Count passed / failed per severity for summary badges."""
    counts = {"blocking_failed": 0, "warnings": 0}
    for r in results:
        if not r.ok and r.severity == "blocking":
            counts["blocking_failed"] += 1
        elif not r.ok and r.severity == "warning":
            counts["warnings"] += 1
    return counts
