"""Probe Combell's POST validation for wildcard A records.

Tries to create a wildcard A record on a target domain using two POST
body shapes, then deletes whatever it managed to create. The goal is
to find the exact body that Combell's ``POST /v2/dns/{domain}/records``
endpoint accepts, since the GET endpoint is known to return
``record_name: "*"`` literally — meaning the storage layer accepts it
but the POST validator may want extra fields.

Experiments tried (in order):

1. ``record_name: "*"`` with ``priority: 0`` explicitly set.
2. ``record_name: "*"`` with the relative name and ``priority`` omitted —
   i.e. a control matching what the engine currently sends.

Each successful POST is followed by a DELETE on the returned id so the
zone is left untouched. Uses the RFC-5737 documentation IP ``192.0.2.1``
as content so a leaked record cannot route real traffic.

Usage from the repo root in PowerShell::

    $env:COMBELL_API_KEY = "..."
    $env:COMBELL_API_SECRET = "..."
    backend\.venv\Scripts\python.exe `
        scripts\dev\test_combell_wildcard_post.py grenspoal.be
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.registrars.combell.adapter import CombellAdapter  # noqa: E402

TEST_CONTENT = "192.0.2.1"  # RFC 5737 TEST-NET-1


async def attempt_post(
    adapter: CombellAdapter, domain: str, body: dict[str, Any]
) -> tuple[bool, Any]:
    print(f"  body: {json.dumps(body)}")
    try:
        status, data = await adapter._request_json(  # noqa: SLF001
            "POST",
            f"/v2/dns/{domain}/records",
            body=body,
            expected_status=(200, 201, 202),
        )
        print(f"  -> HTTP {status} OK")
        print(f"     response: {json.dumps(data, default=str)}")
        return True, data
    except Exception as exc:  # noqa: BLE001
        print(f"  -> FAILED: {exc!r}")
        return False, None


async def find_and_delete_test_record(
    adapter: CombellAdapter, domain: str
) -> None:
    """Locate any record with our TEST_CONTENT and delete it.

    Combell's POST may not return the created id in its body; the
    safest cleanup is to list the zone and delete every match by
    content — the documentation IP is unique enough that a false
    positive is essentially impossible on a customer zone.
    """
    try:
        _, rows = await adapter._request_json(  # noqa: SLF001
            "GET", f"/v2/dns/{domain}/records"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  cleanup list failed: {exc!r}")
        return
    for row in rows or []:
        if row.get("content") == TEST_CONTENT:
            rec_id = row.get("id")
            if not rec_id:
                continue
            print(f"  cleanup: DELETE record id={rec_id}")
            try:
                await adapter._request_json(  # noqa: SLF001
                    "DELETE",
                    f"/v2/dns/{domain}/records/{rec_id}",
                    expected_status=(200, 202, 204),
                )
            except Exception as exc:  # noqa: BLE001
                print(f"    delete failed: {exc!r}")


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
        # Belt-and-braces: clean up first in case a prior run left junk.
        print(f"=== pre-cleanup of {TEST_CONTENT} on {domain} ===")
        await find_and_delete_test_record(adapter, domain)

        print()
        print("=== Experiment 1: record_name='*' with priority: 0 explicit ===")
        body1 = {
            "type": "A",
            "record_name": "*",
            "content": TEST_CONTENT,
            "ttl": 3600,
            "priority": 0,
        }
        ok1, _ = await attempt_post(adapter, domain, body1)
        await find_and_delete_test_record(adapter, domain)

        print()
        print("=== Experiment 2: record_name='*' without priority (control) ===")
        body2 = {
            "type": "A",
            "record_name": "*",
            "content": TEST_CONTENT,
            "ttl": 3600,
        }
        ok2, _ = await attempt_post(adapter, domain, body2)
        await find_and_delete_test_record(adapter, domain)

        print()
        print("=== Summary ===")
        print(f"  Experiment 1 (priority: 0 explicit): {'PASS' if ok1 else 'FAIL'}")
        print(f"  Experiment 2 (control, no priority): {'PASS' if ok2 else 'FAIL'}")
        if ok1 and not ok2:
            print()
            print("  Conclusion: Combell's POST requires explicit priority for A records.")
            print("  Fix: always send priority (default 0) in _record_to_combell_body.")
        elif ok1 and ok2:
            print()
            print("  Conclusion: both worked — original failure may have been transient")
            print("  or tied to another field (TTL?). Re-check the original error.")
        elif not ok1 and not ok2:
            print()
            print("  Conclusion: POST does not accept '*' regardless of priority.")
            print("  Fall back to skipping wildcards + preflight warning.")
        return 0 if (ok1 or ok2) else 1
    finally:
        await adapter.aclose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "Usage: python scripts/dev/test_combell_wildcard_post.py <domain>",
            file=sys.stderr,
        )
        sys.exit(1)
    sys.exit(asyncio.run(main(sys.argv[1])))
