#!/usr/bin/env bash
# Read-only Combell DNS-zone diagnostic.
#
# Dumps the raw /v2/dns/{domain}/records response so we can see how
# Combell itself serialises records — useful when a POST is rejected
# and we need to mirror Combell's own format (e.g. wildcard records
# rejected with dns_invalid_record_name).
#
# Usage (from anywhere on the VPS):
#   bash /opt/rmt/scripts/dev/debug-combell-zone.sh <domain>

set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $(basename "$0") <domain>" >&2
    echo "  e.g. $(basename "$0") example.be" >&2
    exit 1
fi

DOMAIN="$1"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

echo "=== RMT Combell zone diagnostic ==="
echo "repo   : $REPO_ROOT"
echo "domain : $DOMAIN"
echo

docker compose exec -T \
    -e DEBUG_DOMAIN="$DOMAIN" \
    backend python <<'PY'
import asyncio
import json
import os

from app.db import AsyncSessionLocal
from app.migrations.adapters import load_adapters

DOMAIN = os.environ["DEBUG_DOMAIN"]


async def main() -> None:
    async with AsyncSessionLocal() as session:
        pair = await load_adapters(
            session, migration_type="godaddy_to_combell", mock=False
        )
        try:
            print(f"=== Raw GET /v2/dns/{DOMAIN}/records ===")
            try:
                # Bypass the adapter's DnsRecord normalisation so we see
                # the literal JSON Combell returns — that is the source
                # of truth for the field names and value formats.
                _, rows = await pair.destination._request_json(  # noqa: SLF001
                    "GET", f"/v2/dns/{DOMAIN}/records"
                )
                rows = rows or []
                print(f"record count: {len(rows)}")
                print(json.dumps(rows, indent=2, default=str))
            except Exception as exc:  # noqa: BLE001
                print("ERROR while listing zone:", repr(exc))
        finally:
            for adapter in (pair.source, pair.destination):
                aclose = getattr(adapter, "aclose", None)
                if aclose is not None:
                    await aclose()


asyncio.run(main())
PY
