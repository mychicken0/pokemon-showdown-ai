#!/usr/bin/env python3
"""
Phase V2l — VGC Runtime Parity Inspector

Reads persisted audit JSONL files produced by
``DoublesDecisionAuditLogger`` and prints the
runtime-parity evidence for each decision.

Supports:
  --battle           filter to a specific battle tag
  --runtime-mode     filter by runtime_mode (random_doubles / vgc_selected_four)
  --shared-engine    filter to records with shared_engine_used=True
  --mismatch-only    print only records with parity mismatches
  --preview-policy   filter by preview policy (e.g. basic_top4)

Each record printed contains:
  - battle tag and turn
  - runtime mode
  - player / choose_move owner
  - selected four (vgc_selected_four only)
  - final action keys (per-slot)
  - joint order
  - any parity mismatch reason

Usage:
    ./venv/bin/python inspect_vgc2026_runtime_parity.py \\
        logs/doubles_decision_audit.jsonl \\
        --mismatch-only
"""
import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.append(rec)
    return out


def _iter_turn_records(
    records: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Each top-level record has a ``audit_turns`` list.
    Flatten to one entry per turn.
    """
    flat = []
    for rec in records:
        for turn in rec.get("audit_turns", []) or []:
            enriched = dict(turn)
            enriched["battle_tag"] = rec.get(
                "battle_tag", turn.get("battle_tag", "")
            )
            enriched["winner"] = rec.get("winner", "")
            flat.append(enriched)
    return flat


def _matches(
    turn: Dict[str, Any],
    battle: Optional[str],
    runtime_mode: Optional[str],
    shared_engine: Optional[bool],
    preview_policy: Optional[str],
) -> bool:
    if battle and turn.get("battle_tag") != battle:
        return False
    if runtime_mode and turn.get("runtime_mode") != runtime_mode:
        return False
    if shared_engine is not None:
        if bool(turn.get("shared_engine_used", False)) != shared_engine:
            return False
    if preview_policy and turn.get("preview_policy") != preview_policy:
        return False
    return True


def _parity_mismatch_reasons(turn: Dict[str, Any]) -> List[str]:
    """Detect parity-mismatch reasons for a single
    turn record. Returns an empty list if all
    parity assertions pass.
    """
    reasons = []
    if turn.get("shared_engine_used") is not True:
        reasons.append(
            "shared_engine_used != True "
            f"(got {turn.get('shared_engine_used')!r})"
        )
    if not turn.get("shared_engine_invocation_id"):
        reasons.append("shared_engine_invocation_id missing")
    if turn.get("shared_engine_invocation_status") != "completed":
        reasons.append(
            "shared_engine_invocation_status != 'completed' "
            f"(got {turn.get('shared_engine_invocation_status')!r})"
        )
    if not turn.get("shared_engine_owner"):
        reasons.append("shared_engine_owner missing")
    if not turn.get("concrete_player_class"):
        reasons.append("concrete_player_class missing")
    if turn.get("runtime_mode") not in (
        "random_doubles", "vgc_selected_four",
    ):
        reasons.append(
            f"runtime_mode unexpected: {turn.get('runtime_mode')!r}"
        )
    if turn.get("runtime_mode") == "vgc_selected_four":
        if not turn.get("selected_four"):
            reasons.append(
                "vgc_selected_four without selected_four"
            )
    if not turn.get("v2l1_selected_joint_key"):
        reasons.append("v2l1_selected_joint_key missing")
    final_keys = turn.get("v2l1_final_action_keys")
    if not isinstance(final_keys, list) or not final_keys:
        reasons.append("v2l1_final_action_keys missing")
    return reasons


def _format_turn(
    turn: Dict[str, Any], verbose: bool = False
) -> str:
    out = []
    out.append(
        f"battle={turn.get('battle_tag', '?')} "
        f"turn={turn.get('turn', '?')}"
    )
    out.append(
        f"  runtime_mode      : {turn.get('runtime_mode', '?')}"
    )
    out.append(
        f"  player class      : "
        f"{turn.get('concrete_player_class', '?')}"
    )
    out.append(
        f"  choose_move owner : "
        f"{turn.get('shared_engine_owner', '?')}"
    )
    out.append(
        f"  shared_engine_used: {turn.get('shared_engine_used', '?')}"
    )
    if turn.get("runtime_mode") == "vgc_selected_four":
        out.append(
            f"  selected_four     : "
            f"{turn.get('selected_four', '?')}"
        )
        out.append(
            f"  lead_2            : {turn.get('lead_2', '?')}"
        )
        out.append(
            f"  back_2            : {turn.get('back_2', '?')}"
        )
        out.append(
            f"  preview_policy    : {turn.get('preview_policy', '?')}"
        )
    if verbose:
        slot_0 = turn.get("slot_0", {}) or {}
        slot_1 = turn.get("slot_1", {}) or {}
        out.append(
            f"  slot_0 action     : {slot_0.get('action', '?')}"
        )
        out.append(
            f"  slot_1 action     : {slot_1.get('action', '?')}"
        )
        out.append(
            f"  joint_order       : "
            f"{turn.get('selected_joint_order', '?')}"
        )
    reasons = _parity_mismatch_reasons(turn)
    if reasons:
        out.append(f"  PARITY MISMATCH:")
        for r in reasons:
            out.append(f"    - {r}")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="V2l runtime parity inspector"
    )
    parser.add_argument(
        "jsonl",
        nargs="?",
        default="logs/doubles_decision_audit.jsonl",
        help="Path to audit JSONL",
    )
    parser.add_argument(
        "--battle", default=None,
        help="Filter to a specific battle tag",
    )
    parser.add_argument(
        "--runtime-mode", default=None,
        choices=["random_doubles", "vgc_selected_four"],
        help="Filter by runtime mode",
    )
    parser.add_argument(
        "--shared-engine",
        type=lambda v: v.lower() in ("1", "true", "yes"),
        default=None,
        help="Filter by shared_engine_used",
    )
    parser.add_argument(
        "--mismatch-only", action="store_true",
        help="Print only records with parity mismatches",
    )
    parser.add_argument(
        "--preview-policy", default=None,
        help="Filter by preview policy",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print per-slot actions and joint order",
    )
    args = parser.parse_args()

    records = _load_jsonl(args.jsonl)
    if not records:
        print(f"No records found at {args.jsonl}", file=sys.stderr)
        return 1
    flat = _iter_turn_records(records)
    matched = [
        t for t in flat
        if _matches(
            t, args.battle, args.runtime_mode,
            args.shared_engine, args.preview_policy,
        )
    ]
    if args.mismatch_only:
        matched = [
            t for t in matched
            if _parity_mismatch_reasons(t)
        ]
    if not matched:
        print(
            "No records matched the filter / no mismatches",
            file=sys.stderr,
        )
        return 0
    for turn in matched:
        print(_format_turn(turn, verbose=args.verbose))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
