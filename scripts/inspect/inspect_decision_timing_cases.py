#!/usr/bin/env python3
"""Phase 6.4.6 — Decision Timing Case Inspector.

Inspect decision timing diagnostics from audit logs.
"""
import json
import os
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Inspector for Decision Timing Diagnostics"
    )
    parser.add_argument("--slowest", action="store_true",
                        help="Sort by decision_time_ms descending (default)")
    parser.add_argument("--min-ms", type=float, default=None,
                        help="Filter by minimum decision_time_ms")
    parser.add_argument("--battle", type=str,
                        help="Filter for specific battle tag")
    parser.add_argument("--filepath", type=str,
                        default="logs/doubles_decision_audit.jsonl",
                        help="Path to audit JSONL file")
    parser.add_argument("--limit", type=int, default=50,
                        help="Maximum cases to show (default: 50)")

    args = parser.parse_args()

    if not os.path.exists(args.filepath):
        print(f"Error: Log file not found at {args.filepath}")
        sys.exit(1)

    matched_cases = []

    with open(args.filepath, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue

            battle_tag = record.get("battle_tag", "Unknown")
            if args.battle and args.battle != battle_tag:
                continue

            for turn_data in record.get("audit_turns", []):
                dt = turn_data.get("decision_time_ms")
                if dt is None:
                    continue

                if args.min_ms is not None and float(dt) < args.min_ms:
                    continue

                flags = []
                if turn_data.get("stale_target_selected"):
                    flags.append("stale-target")
                for sk in ("slot_0", "slot_1"):
                    slot = turn_data.get(sk, {})
                    if slot.get("forced_switch"):
                        flags.append("forced-switch")
                        break
                for sk in ("slot_0", "slot_1"):
                    slot = turn_data.get(sk, {})
                    if slot.get("severe_neg_boost_active"):
                        flags.append("severe-neg-boost")
                        break
                for sk in ("slot_0", "slot_1"):
                    slot = turn_data.get(sk, {})
                    if slot.get("direct_absorb_immune_move_selected"):
                        flags.append("direct-absorb")
                        break
                for sk in ("slot_0", "slot_1"):
                    slot = turn_data.get(sk, {})
                    if slot.get("direct_known_absorb_repeat_selected"):
                        flags.append("known-absorb-repeat")
                        break

                matched_cases.append({
                    "battle_tag": battle_tag,
                    "turn": turn_data.get("turn", 0),
                    "decision_time_ms": float(dt),
                    "valid_order_time_ms": turn_data.get("valid_order_time_ms"),
                    "score_action_time_ms": turn_data.get("score_action_time_ms"),
                    "joint_scoring_time_ms": turn_data.get("joint_scoring_time_ms"),
                    "audit_postprocess_time_ms": turn_data.get("audit_postprocess_time_ms"),
                    "score_action_call_count": turn_data.get("score_action_call_count"),
                    "joint_order_count": turn_data.get("joint_order_count"),
                    "selected_joint_order": turn_data.get("selected_joint_order", ""),
                    "flags": flags,
                    "stale_target": turn_data.get("stale_target_selected", False),
                })

    if args.slowest:
        matched_cases.sort(key=lambda x: x["decision_time_ms"], reverse=True)

    if not matched_cases:
        print("No timing data found — enable_decision_timing_diagnostics may be off.")
        return

    total = len(matched_cases)
    dts = sorted([c["decision_time_ms"] for c in matched_cases])
    avg = sum(dts) / total
    p50 = dts[total // 2]
    p95_idx = int(total * 0.95)
    p95 = dts[p95_idx] if p95_idx < total else dts[-1]
    mx = dts[-1]

    print(f"Total turns with timing: {total}")
    print(f"  avg={avg:.2f}ms  p50={p50:.2f}ms  p95={p95:.2f}ms  max={mx:.2f}ms")
    print()

    for idx, case in enumerate(matched_cases[:args.limit], 1):
        flags = case["flags"]
        flag_str = " | ".join(flags) if flags else "none"
        print(f"Case #{idx}:")
        print(f"  Battle Tag           : {case['battle_tag']}")
        print(f"  Turn                 : {case['turn']}")
        print(f"  decision_time_ms     : {case['decision_time_ms']:.2f}")
        print(f"  valid_order_time_ms  : {_fmt(case['valid_order_time_ms'])}")
        print(f"  score_action_time_ms : {_fmt(case['score_action_time_ms'])}")
        print(f"  joint_scoring_time_ms: {_fmt(case['joint_scoring_time_ms'])}")
        print(f"  audit_postprocess_ms : {_fmt(case['audit_postprocess_time_ms'])}")
        print(f"  score_action_calls   : {case['score_action_call_count']}")
        print(f"  joint_order_count    : {case['joint_order_count']}")
        print(f"  selected             : {case['selected_joint_order'][:80]}")
        print(f"  flags                : [{flag_str}]")
        print()


def _fmt(val):
    return f"{val:.2f}" if val is not None else "N/A"


if __name__ == "__main__":
    main()
