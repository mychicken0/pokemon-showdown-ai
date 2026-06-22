#!/usr/bin/env python3
import json
import os
import sys

def inspect_partial_spread_cases(filepath="logs/doubles_decision_audit.jsonl"):
    if not os.path.exists(filepath):
        print(f"Error: Log file not found at {filepath}")
        sys.exit(1)

    total_partial_immune = 0
    total_efficient = 0
    total_inefficient = 0
    examples = []

    with open(filepath, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                battle = json.loads(line)
            except Exception as e:
                continue

            battle_tag = battle.get("battle_tag", "Unknown")
            won = battle.get("won", False)
            audit_turns = battle.get("audit_turns", [])

            for turn_data in audit_turns:
                turn = turn_data.get("turn", 0)
                our_active = turn_data.get("our_active", [None, None])
                opp_active = turn_data.get("opp_active", [None, None])
                
                for idx, slot in enumerate((turn_data.get("slot_0", {}), turn_data.get("slot_1", {}))):
                    if slot.get("partial_immune_spread_selected"):
                        total_partial_immune += 1
                        is_eff = slot.get("efficient_partial_spread_selected", False)
                        is_ineff = slot.get("inefficient_partial_spread_selected", False)
                        if is_eff:
                            total_efficient += 1
                        if is_ineff:
                            total_inefficient += 1

                        examples.append({
                            "battle_tag": battle_tag,
                            "won": won,
                            "turn": turn,
                            "slot": idx,
                            "our_mon": our_active[idx].get("species") if our_active[idx] else "Unknown",
                            "opponents": [opp.get("species") for opp in opp_active if opp],
                            "move": slot.get("action"),
                            "best_single_alternative": slot.get("best_single_target_alternative"),
                            "immune_targets": slot.get("immune_target_species", []),
                            "damaged_targets": slot.get("damaged_target_species", []),
                            "is_efficient": is_eff,
                            "is_inefficient": is_ineff
                        })

    print("==================================================")
    print("  PARTIAL SPREAD IMMUNITY AUDIT INSPECTION REPORT  ")
    print("==================================================")
    print(f"Total Partial-Immune Spread Moves Selected: {total_partial_immune}")
    print(f"  - Efficient Partial Spread:              {total_efficient}")
    print(f"  - Inefficient Partial Spread:            {total_inefficient}")
    print("==================================================")
    
    if examples:
        print("\nTop Examples of Partial Spread Immunity Selections:")
        # Print a mix of efficient and inefficient examples
        printed_count = 0
        for ex in examples[:15]:
            print(f"\nBattle: {ex['battle_tag']} (Won: {ex['won']}) | Turn: {ex['turn']} | Slot: {ex['slot']}")
            print(f"  Our Pokemon: {ex['our_mon']}")
            print(f"  Opponent Active: {', '.join(ex['opponents'])}")
            print(f"  Selected Spread Move: {ex['move']}")
            print(f"  Immune Opponents: {', '.join(ex['immune_targets'])}")
            print(f"  Damaged Opponents: {', '.join(ex['damaged_targets'])}")
            print(f"  Best Single Alternative: {ex['best_single_alternative']}")
            print(f"  Status: {'EFFICIENT' if ex['is_efficient'] else 'INEFFICIENT' if ex['is_inefficient'] else 'UNKNOWN'}")
            printed_count += 1
    else:
        print("\nNo partial spread immunity cases found in the audit logs.")

if __name__ == "__main__":
    filepath = "logs/doubles_decision_audit.jsonl"
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    inspect_partial_spread_cases(filepath)
