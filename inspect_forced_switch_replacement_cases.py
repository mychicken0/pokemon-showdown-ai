#!/usr/bin/env python3
"""Phase 6.4.4: Forced Switch Replacement Safety Inspector.

Filters forced switch replacement cases from audit JSONL logs.

Usage:
  python inspect_forced_switch_replacement_cases.py <jsonl_path> [options]
  python inspect_forced_switch_replacement_cases.py logs/benchmark.jsonl --selected-double-threat
  python inspect_forced_switch_replacement_cases.py logs/benchmark.jsonl --selection-changed --battle tag123
"""
import argparse
import json
import sys


def load_battles(filepath):
    battles = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                battles.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return battles


def filter_cases(battles, args):
    cases = []
    for battle in battles:
        battle_tag = battle.get("battle_tag", "unknown")
        won = battle.get("won", False)
        for turn in battle.get("audit_turns", []):
            turn_num = turn.get("turn", 0)
            for slot_key in ("slot_0", "slot_1"):
                slot = turn.get(slot_key, {})
                if not slot:
                    continue
                if not slot.get("forced_switch"):
                    continue

                if args.battle and args.battle not in battle_tag:
                    continue
                if args.selected_double_threat and not slot.get("forced_switch_selected_double_threat"):
                    continue
                if args.selected_quad_weak and not slot.get("forced_switch_selected_quad_weak"):
                    continue
                if args.selection_changed and not slot.get("forced_switch_safety_selection_changed"):
                    continue
                if args.fallback_used and not slot.get("forced_switch_order_fallback_used"):
                    continue

                cases.append({
                    "battle_tag": battle_tag,
                    "turn": turn_num,
                    "slot": slot_key,
                    "outcome": "win" if won else "loss",
                    "selected_species": slot.get("forced_switch_selected_species", ""),
                    "best_safety_species": slot.get("forced_switch_best_safety_species", ""),
                    "selected_score": slot.get("forced_switch_selected_safety_score", 0.0),
                    "best_score": slot.get("forced_switch_best_safety_score", 0.0),
                    "candidate_count": slot.get("forced_switch_candidate_count", 0),
                    "selected_double_threat": slot.get("forced_switch_selected_double_threat", False),
                    "selected_quad_weak": slot.get("forced_switch_selected_quad_weak", False),
                    "selection_changed": slot.get("forced_switch_safety_selection_changed", False),
                    "fallback_used": slot.get("forced_switch_order_fallback_used", False),
                    "safety_enabled": slot.get("forced_switch_safety_enabled", False),
                    "selected_low_hp": slot.get("forced_switch_selected_low_hp", False),
                    "reason": slot.get("forced_switch_reason", ""),
                })
    return cases


def main():
    parser = argparse.ArgumentParser(
        description="Inspect forced switch replacement safety cases from audit JSONL"
    )
    parser.add_argument("filepath", help="Path to audit JSONL file")
    parser.add_argument("--selected-double-threat", action="store_true",
                        help="Filter: selected replacement is double-threat")
    parser.add_argument("--selected-quad-weak", action="store_true",
                        help="Filter: selected replacement has 4x weakness")
    parser.add_argument("--selection-changed", action="store_true",
                        help="Filter: safety changed the selection")
    parser.add_argument("--fallback-used", action="store_true",
                        help="Filter: list-order fallback was used")
    parser.add_argument("--battle", type=str, default=None,
                        help="Filter: battle tag substring")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max cases to show (default: 50)")
    args = parser.parse_args()

    battles = load_battles(args.filepath)
    cases = filter_cases(battles, args)

    if not cases:
        print("No matching forced switch replacement cases found.")
        return

    print(f"Found {len(cases)} case(s) (showing up to {args.limit}):")
    print("-" * 80)
    for i, c in enumerate(cases[:args.limit], 1):
        print(f"  {i}. [{c['battle_tag']}] turn {c['turn']} {c['slot']} ({c['outcome']})")
        print(f"     Selected: {c['selected_species']} (score={c['selected_score']:.1f})"
              f" | Best: {c['best_safety_species']} (score={c['best_score']:.1f})")
        print(f"     Candidates: {c['candidate_count']} | Safety ON: {c['safety_enabled']}")
        tags = []
        if c['selected_double_threat']:
            tags.append("DOUBLE_THREAT")
        if c['selected_quad_weak']:
            tags.append("QUAD_WEAK")
        if c['selected_low_hp']:
            tags.append("LOW_HP")
        if c['selection_changed']:
            tags.append("CHANGED")
        if c['fallback_used']:
            tags.append("FALLBACK")
        if tags:
            print(f"     Tags: {', '.join(tags)}")
        if c['reason']:
            print(f"     Reasons: {c['reason']}")
        gap = c['best_score'] - c['selected_score']
        if gap > 0:
            print(f"     Score gap: {gap:.1f} (selected worse than best)")


if __name__ == "__main__":
    main()
