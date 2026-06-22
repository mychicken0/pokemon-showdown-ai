#!/usr/bin/env python3
"""Inspector for Phase 6.4.3 stat-drop switch diagnostic cases.

Filters:
  --severe-negative-boost
  --stayed-unproductive
  --stayed-productive
  --switched
  --switch-available
  --category offensive|defensive|speed
  --battle <battle_tag>
  --filepath <jsonl>
"""
import argparse
import json
import os
import sys


def inspect(args):
    if not os.path.exists(args.filepath):
        print(f"Error: File not found: {args.filepath}")
        sys.exit(1)

    results = []

    with open(args.filepath, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                battle = json.loads(line)
                battle_tag = battle.get("battle_tag", "")
                won = battle.get("won", False)

                if args.battle and args.battle not in battle_tag:
                    continue

                for turn in battle.get("audit_turns", []):
                    turn_num = turn.get("turn", 0)

                    for slot_idx, slot_key in enumerate(("slot_0", "slot_1")):
                        slot = turn.get(slot_key, {})
                        if not slot:
                            continue

                        is_severe = bool(slot.get("severe_negative_boost_active"))
                        if not is_severe:
                            if args.severe_negative_boost:
                                continue
                            else:
                                continue

                        # Apply filters
                        if args.severe_negative_boost and not is_severe:
                            continue
                        if args.stayed_unproductive and not bool(slot.get("severe_negative_boost_stayed_unproductive")):
                            continue
                        if args.stayed_productive and not bool(slot.get("severe_negative_boost_stayed_productive")):
                            continue
                        if args.switched and not bool(slot.get("severe_negative_boost_switched")):
                            continue
                        if args.switch_available and not bool(slot.get("severe_negative_boost_switch_available")):
                            continue
                        if args.category:
                            cats = slot.get("severe_negative_boost_categories", [])
                            if args.category not in cats:
                                continue

                        results.append({
                            "battle_tag": battle_tag,
                            "turn": turn_num,
                            "slot": slot_idx,
                            "won": won,
                            "species": slot.get("severe_negative_boost_species", ""),
                            "categories": slot.get("severe_negative_boost_categories", []),
                            "selected_action": slot.get("severe_negative_boost_selected_action", ""),
                            "best_switch": slot.get("severe_negative_boost_best_switch_candidate", ""),
                            "switch_available": bool(slot.get("severe_negative_boost_switch_available")),
                            "switched": bool(slot.get("severe_negative_boost_switched")),
                            "stayed": bool(slot.get("severe_negative_boost_stayed")),
                            "productive": bool(slot.get("severe_negative_boost_stayed_productive")),
                            "unproductive": bool(slot.get("severe_negative_boost_stayed_unproductive")),
                            "only_legal": bool(slot.get("severe_negative_boost_only_legal_no_switch")),
                        })
            except Exception:
                continue

    if not results:
        print("No matching cases found.")
        return

    print(f"Found {len(results)} matching case(s):")
    print("-" * 70)
    for i, r in enumerate(results, 1):
        outcome = "WON" if r["won"] else "LOST"
        print(f"  {i}. [{r['battle_tag']}] turn {r['turn']} slot {r['slot']} ({outcome})")
        print(f"     Species: {r['species']} Categories: {','.join(r['categories'])}")
        print(f"     Selected: {r['selected_action']}")
        print(f"     Best switch: {r['best_switch'] or 'none'}")
        print(f"     Switch available: {r['switch_available']} Switched: {r['switched']}")
        if r["stayed"]:
            prod = "productive" if r["productive"] else "unproductive"
            print(f"     Stayed: {prod}")
        if r["only_legal"]:
            print(f"     Only legal (no switch available)")


def main():
    parser = argparse.ArgumentParser(description="Inspect stat-drop switch diagnostic cases")
    parser.add_argument("--severe-negative-boost", action="store_true",
                        help="Show only severe negative boost cases")
    parser.add_argument("--stayed-unproductive", action="store_true",
                        help="Show only unproductive stayed-in cases")
    parser.add_argument("--stayed-productive", action="store_true",
                        help="Show only productive stayed-in cases")
    parser.add_argument("--switched", action="store_true",
                        help="Show only cases where the bot switched out")
    parser.add_argument("--switch-available", action="store_true",
                        help="Show only cases where a switch was available")
    parser.add_argument("--category", type=str, default=None,
                        choices=["offensive", "defensive", "speed"],
                        help="Filter by drop category (offensive, defensive, speed)")
    parser.add_argument("--battle", type=str, default=None,
                        help="Filter by battle tag substring")
    parser.add_argument("--filepath", type=str,
                        default="logs/doubles_decision_audit.jsonl",
                        help="Path to audit JSONL file")
    args = parser.parse_args()

    # If no filter specified, show all severe cases
    if not any([args.severe_negative_boost, args.stayed_unproductive,
                args.stayed_productive, args.switched, args.switch_available]):
        args.severe_negative_boost = True

    inspect(args)


if __name__ == "__main__":
    main()
