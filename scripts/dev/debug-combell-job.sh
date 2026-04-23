#!/usr/bin/env bash
# Read-only Combell diagnostic.
#
# Dumps the raw /v2/provisioningjobs/{id} response and checks whether
# Combell lists the given domain in /v2/domains. Makes no writes.
#
# Usage (from anywhere on the VPS):
#   bash /opt/rmt/scripts/dev/debug-combell-job.sh <domain> <job_id>

set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: $(basename "$0") <domain> <provisioning-job-id>" >&2
    echo "  e.g. $(basename "$0") example.com 00000000-0000-0000-0000-000000000000" >&2
    exit 1
fi

DOMAIN="$1"
JOB_ID="$2"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

echo "=== RMT Combell diagnostic ==="
echo "repo   : $REPO_ROOT"
echo "domain : $DOMAIN"
echo "job_id : $JOB_ID"
echo

docker compose exec -T \
    -e DEBUG_DOMAIN="$DOMAIN" \
    -e DEBUG_JOB_ID="$JOB_ID" \
    backend python <<'PY'
import asyncio
import json
import os

from app.db import AsyncSessionLocal
from app.migrations.adapters import load_adapters

DOMAIN = os.environ["DEBUG_DOMAIN"]
JOB_ID = os.environ["DEBUG_JOB_ID"]


async def main() -> None:
    async with AsyncSessionLocal() as session:
        pair = await load_adapters(
            session, migration_type="godaddy_to_combell", mock=False
        )
        try:
            print("=== Raw provisioning-job response from Combell ===")
            try:
                st = await pair.destination.get_provisioning_job(JOB_ID)
                print("normalised status :", st.status)
                print("raw Combell body  :")
                print(json.dumps(st.detail, indent=2, default=str))
            except Exception as exc:  # noqa: BLE001
                print("ERROR while polling job:", repr(exc))

            print()
            print("=== Does Combell list the domain? ===")
            try:
                domains = list(await pair.destination.list_domains())
                match = [d for d in domains if d.name.lower() == DOMAIN.lower()]
                if match:
                    print(f"YES - {match[0].name} (status={match[0].status})")
                else:
                    print(
                        f"NO - {DOMAIN} not in Combell /v2/domains list "
                        f"({len(domains)} domains total)"
                    )
            except Exception as exc:  # noqa: BLE001
                print("ERROR while listing domains:", repr(exc))
        finally:
            for adapter in (pair.source, pair.destination):
                aclose = getattr(adapter, "aclose", None)
                if aclose is not None:
                    await aclose()


asyncio.run(main())
PY
