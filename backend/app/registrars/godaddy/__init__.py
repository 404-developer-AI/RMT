"""GoDaddy source adapter — read-only for V1.

Implements the six source-side methods plus the pre-flight helpers against
GoDaddy's public v1 API (``https://api.godaddy.com/v1/...``). GoDaddy's v1
API is the only one generally available to non-reseller accounts; v2 adds
CAA/DNSSEC introspection but requires a reseller tier we do not have.

V1 consequences:
* No CAA / DNSSEC read support — both flagged as "unknown" and the
  pre-flight runner emits a warning for zones that *should* contain CAA.
* Auth codes are exposed via ``GET /v1/domains/{domain}`` as the
  ``authCode`` field — surfaced here for completeness, but the operator
  pastes manually in V1 per the resolved roadmap decision.

Authentication is a single static header: ``Authorization: sso-key
{api_key}:{api_secret}``.
"""

from app.registrars.godaddy.adapter import GoDaddyAdapter

__all__ = ["GoDaddyAdapter"]
