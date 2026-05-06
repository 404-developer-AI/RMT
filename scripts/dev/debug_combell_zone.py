"""Read-only Combell DNS-zone diagnostic — runs locally without Docker.

Reads COMBELL_API_KEY and COMBELL_API_SECRET from the environment, lists
``GET /v2/dns/{domain}/records`` and prints the raw JSON. Useful when we
need to mirror Combell's own field/value formatting (e.g. wildcard
record_name handling).

Usage from the repo root in PowerShell::

    $env:COMBELL_API_KEY = "..."
    $env:COMBELL_API_SECRET = "..."
    backend\.venv\Scripts\python.exe scripts\dev\debug_combell_zone.py grenspoal.be

Note: Combell whitelists by IP. If your dev machine's IP is not in the
whitelist, expect a 401. In that case run the bash variant on the VPS:
``scripts/dev/debug-combell-zone.sh``.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Make ``backend/app`` importable when this script is run from the repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.registrars.combell.adapter import CombellAdapter  # noqa: E402


async def main(domain: str) -> int:
    api_key = os.environ.get("COMBELL_API_KEY")
    api_secret = os.environ.get("COMBELL_API_SECRET")
    if not api_key or not api_secret:
        print("ERROR: set COMBELL_API_KEY and COMBELL_API_SECRET first.", file=sys.stderr)
        return 2

    adapter = CombellAdapter(
        api_key=api_key,
        api_secret=api_secret,
        api_base="https://api.combell.com",
    )
    try:
        print(f"=== Raw GET /v2/dns/{domain}/records ===")
        try:
            _, rows = await adapter._request_json(  # noqa: SLF001
                "GET", f"/v2/dns/{domain}/records"
            )
            rows = rows or []
            print(f"record count: {len(rows)}")
            print(json.dumps(rows, indent=2, default=str))
        except Exception as exc:  # noqa: BLE001
            print("ERROR while listing zone:", repr(exc))
            return 1
    finally:
        await adapter.aclose()
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/dev/debug_combell_zone.py <domain>", file=sys.stderr)
        sys.exit(1)
    sys.exit(asyncio.run(main(sys.argv[1])))
