#!/usr/bin/env python3
"""Phase 6.4.7 — Stat-Drop Switch Scoring Case Inspector."""
import json, os, argparse, sys


def main():
    parser = argparse.ArgumentParser(description="Inspector for Stat-Drop Switch Scoring")
    parser.add_argument("--pressure-active", action="store_true")
    parser.add_argument("--switch-selected", action="store_true")
    parser.add_argument("--stayed-unproductive", action="store_true")
    parser.add_argument("--selection-changed", action="store_true")
    parser.add_argument("--category", type=str, choices=["offensive", "defensive", "speed"])
    parser.add_argument("--battle", type=str)
    parser.add_argument("--filepath", type=str, default="logs/doubles_decision_audit.jsonl")
    args = parser.parse_args()

    if not os.path.exists(args.filepath):
        print(f"Error: {args.filepath} not found")
        sys.exit(1)

    matched = []
    with open(args.filepath) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            bt = record.get("battle_tag", "Unknown")
            if args.battle and args.battle != bt:
                continue
            won = record.get("won", False)
            for td in record.get("audit_turns", []):
                for sk in ("slot_0", "slot_1"):
                    slot = td.get(sk, {})
                    if not slot:
                        continue
                    match = False
                    if args.pressure_active and slot.get("stat_drop_switch_pressure_active"):
                        match = True
                    elif args.switch_selected and slot.get("stat_drop_switch_selected"):
                        match = True
                    elif args.stayed_unproductive and slot.get("stat_drop_switch_stayed_unproductive"):
                        match = True
                    elif args.selection_changed and slot.get("stat_drop_switch_selection_changed"):
                        match = True
                    elif args.category:
                        cats = slot.get("stat_drop_switch_pressure_categories", [])
                        if args.category in cats:
                            match = True
                    else:
                        if slot.get("stat_drop_switch_pressure_active"):
                            match = True
                    if match:
                        matched.append({
                            "battle_tag": bt, "turn": td.get("turn", 0), "won": won,
                            "categories": slot.get("stat_drop_switch_pressure_categories", []),
                            "switch_selected": slot.get("stat_drop_switch_selected", False),
                            "stayed_unproductive": slot.get("stat_drop_switch_stayed_unproductive", False),
                            "best_switch": slot.get("stat_drop_switch_best_switch_species", ""),
                            "best_switch_score": slot.get("stat_drop_switch_best_switch_score", 0),
                            "best_non_switch": slot.get("stat_drop_switch_best_non_switch_score", 0),
                            "reason": slot.get("stat_drop_switch_reason", ""),
                            "selected": td.get("selected_joint_order", "")[:60],
                        })

    if not matched:
        print("No matching cases.")
        return

    wins = sum(1 for c in matched if c["won"])
    losses = sum(1 for c in matched if not c["won"])
    print(f"Found {len(matched)} cases ({wins}W/{losses}L)\n")

    for i, c in enumerate(matched, 1):
        print(f"Case #{i}:")
        print(f"  Battle: {c['battle_tag']}  Turn: {c['turn']}  Outcome: {'WIN' if c['won'] else 'LOSS'}")
        print(f"  Categories: {c['categories']}")
        print(f"  Selected: {c['selected']}")
        print(f"  Switch Selected: {c['switch_selected']}  Stayed Unproductive: {c['stayed_unproductive']}")
        print(f"  Best Switch: {c['best_switch']} ({c['best_switch_score']:.1f})")
        print(f"  Best Non-Switch: {c['best_non_switch']:.1f}")
        print(f"  Reason: {c['reason']}")
        print()


if __name__ == "__main__":
    main()
