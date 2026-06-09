#!/usr/bin/env python3
"""Phase 6.4.5 — Stale Target / Retarget Immunity Case Inspector.

Inspect audit logs for stale target safety events.
"""
import json
import os
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Diagnostic Inspector for Stale Target / Retarget Immunity Cases"
    )
    parser.add_argument("--stale-target", action="store_true",
                        help="Filter for stale_target_selected cases")
    parser.add_argument("--type-immune", action="store_true",
                        help="Filter for stale target with fallback type immune risk")
    parser.add_argument("--no-effect", action="store_true",
                        help="Filter for stale target with no-effect risk")
    parser.add_argument("--avoided", action="store_true",
                        help="Filter for stale_target_avoided cases")
    parser.add_argument("--battle", type=str,
                        help="Filter for specific battle tag")
    parser.add_argument("--filepath", type=str,
                        default="logs/doubles_decision_audit.jsonl",
                        help="Path to audit JSONL file")

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
                battle = json.loads(line)
            except Exception:
                continue

            battle_tag = battle.get("battle_tag", "Unknown")
            if args.battle and args.battle != battle_tag:
                continue

            is_win = battle.get("won", False)

            for turn_data in battle.get("audit_turns", []):
                turn = turn_data.get("turn", 0)

                match = False

                if args.stale_target:
                    if turn_data.get("stale_target_selected", False):
                        match = True
                elif args.type_immune:
                    if (turn_data.get("stale_target_selected", False)
                            and turn_data.get("stale_target_caused_type_immune", False)):
                        match = True
                elif args.no_effect:
                    if (turn_data.get("stale_target_selected", False)
                            and turn_data.get("stale_target_caused_no_effect", False)):
                        match = True
                elif args.avoided:
                    if turn_data.get("stale_target_avoided", False):
                        match = True
                else:
                    if (turn_data.get("stale_target_selected", False)
                            or turn_data.get("stale_target_avoided", False)):
                        match = True

                if match:
                    matched_cases.append({
                        "battle_tag": battle_tag,
                        "turn": turn,
                        "won": is_win,
                        "selected_joint_order": turn_data.get("selected_joint_order", ""),
                        "selected_score": turn_data.get("selected_score", 0.0),
                        "score_gap": turn_data.get("score_gap_selected_best_alt", 0.0),
                        "top_5_alternatives": turn_data.get("top_5_alternatives", []),
                        "top_5_scores": turn_data.get("top_5_scores", []),
                        "stale_target_selected": turn_data.get("stale_target_selected", False),
                        "stale_target_avoided": turn_data.get("stale_target_avoided", False),
                        "same_target_expected_ko": turn_data.get("stale_target_same_target_expected_ko", False),
                        "caused_no_effect": turn_data.get("stale_target_caused_no_effect", False),
                        "caused_type_immune": turn_data.get("stale_target_caused_type_immune", False),
                        "first_slot": turn_data.get("stale_target_first_slot", 0),
                        "first_move": turn_data.get("stale_target_first_move", ""),
                        "first_target": turn_data.get("stale_target_first_target", ""),
                        "second_slot": turn_data.get("stale_target_second_slot", 1),
                        "second_move": turn_data.get("stale_target_second_move", ""),
                        "second_intended_target": turn_data.get("stale_target_second_intended_target", ""),
                        "fallback_target": turn_data.get("stale_target_fallback_target", ""),
                        "reason": turn_data.get("stale_target_reason", ""),
                    })

    if not matched_cases:
        print("No matching cases found.")
        return

    wins = sum(1 for c in matched_cases if c["won"])
    losses = sum(1 for c in matched_cases if not c["won"])
    print(f"Found {len(matched_cases)} matching cases ({wins}W / {losses}L)\n")

    for idx, case in enumerate(matched_cases, 1):
        print(f"Case #{idx}:")
        print(f"  Battle Tag         : {case['battle_tag']}")
        print(f"  Turn               : {case['turn']}")
        print(f"  Result             : {'WIN' if case['won'] else 'LOSS'}")
        print(f"  Selected Joint     : {case['selected_joint_order']}")
        print(f"  Selected Score     : {case['selected_score']:.2f}")
        print(f"  Score Gap          : {case['score_gap']:.2f}")
        print(f"  First Slot         : {case['first_slot']}")
        print(f"  First Move         : {case['first_move']}")
        print(f"  First Target       : {case['first_target']}")
        print(f"  Second Slot        : {case['second_slot']}")
        print(f"  Second Move        : {case['second_move']}")
        print(f"  Intended Target    : {case['second_intended_target']}")
        print(f"  Fallback Target    : {case['fallback_target']}")
        print(f"  Reason             : {case['reason']}")
        print(f"  Stale Selected     : {case['stale_target_selected']}")
        print(f"  Stale Avoided      : {case['stale_target_avoided']}")
        print(f"  Same Target KO     : {case['same_target_expected_ko']}")
        print(f"  Type Immune Risk   : {case['caused_type_immune']}")
        print(f"  No-Effect Risk     : {case['caused_no_effect']}")
        if case["top_5_alternatives"]:
            print(f"  Top Alternatives:")
            for alt, score in zip(case["top_5_alternatives"][:3], case["top_5_scores"][:3]):
                print(f"    {alt}: {score:.2f}")
        print()


if __name__ == "__main__":
    main()
