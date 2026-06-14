#!/usr/bin/env python3
"""Phase V2l.1 local canonical-decision smoke.

This is deliberately a decision-path smoke, not a completed battle
benchmark. It runs only when the local Showdown server is healthy,
executes the real ``ControlledTeamPreviewPlayer.choose_move`` path on
a concrete doubles state, persists the audit JSONL, and validates it
with the runtime-parity inspector.
"""

import json
import os
import sys
import tempfile
import urllib.request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _local_server_healthy(timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(
            "http://localhost:8000", timeout=timeout
        ) as response:
            return response.status == 200
    except Exception:
        return False


def _run_decision_smoke() -> tuple[bool, str]:
    import poke_env_test_cleanup  # noqa: F401
    from inspect_vgc2026_runtime_parity import (
        _parity_mismatch_reasons,
    )
    from test_vgc2026_runtime_engine_parity import (
        _run_canonical_decision,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "v2l1_smoke.jsonl")
        result = _run_canonical_decision(
            "vgc_selected_four",
            path,
            "v2l1-local-decision-smoke",
        )
        turn = result["turn"]
        reasons = _parity_mismatch_reasons(turn)
        if reasons:
            return False, f"parity mismatches: {reasons}"
        if result["player"]._v2l1_invocation_status != "completed":
            return False, "canonical invocation did not complete"
        if not result["selected_message"].startswith("/choose "):
            return False, "canonical engine returned no choice"
        with open(path) as stream:
            records = [
                json.loads(line)
                for line in stream
                if line.strip()
            ]
        if len(records) != 1:
            return False, f"expected one audit record, got {len(records)}"
        return True, (
            f"choice={result['selected_message']} "
            f"invocation={turn['shared_engine_invocation_id']}"
        )


def main() -> int:
    if not _local_server_healthy():
        print(
            "SKIPPED: localhost:8000 is not healthy; "
            "no remote server was contacted."
        )
        return 0
    ok, message = _run_decision_smoke()
    if not ok:
        print(f"SMOKE FAILED: {message}")
        return 1
    print(f"SMOKE OK: {message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
