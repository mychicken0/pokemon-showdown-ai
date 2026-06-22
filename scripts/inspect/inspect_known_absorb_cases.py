"""Inspector for known absorb hard safety cases.

Filters:
  --direct-known-absorb  : show direct known absorb events
  --repeat               : show repeat selections
  --avoided              : show avoided absorb selections
  --only-legal           : show only-legal absorb selections
  --battle <battle_tag>  : filter by battle tag
  --filepath <jsonl>     : input JSONL file
"""
import argparse
import json
import sys


def inspect_cases(args):
    filepath = args.filepath
    if not filepath:
        print("Error: --filepath is required")
        sys.exit(1)

    try:
        with open(filepath, "r") as f:
            records = [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}")
        sys.exit(1)

    cases = []
    for record in records:
        battle_tag = record.get("battle_tag", "unknown")
        if args.battle and args.battle not in battle_tag:
            continue

        for turn_data in record.get("audit_turns", []):
            turn = turn_data.get("turn", 0)
            for slot_key in ("slot_0", "slot_1"):
                slot = turn_data.get(slot_key, {})
                if not slot:
                    continue

                # Check for direct absorb fields (move actually blocked from scoring)
                absorb_selected = slot.get("direct_absorb_immune_move_selected", False)
                absorb_avoided = slot.get("direct_absorb_hard_block_avoided", False)
                absorb_only_legal = slot.get("direct_absorb_only_legal_action", False)
                absorb_reason = slot.get("direct_absorb_block_reason", "")
                absorb_target = slot.get("direct_absorb_target_species", "")
                absorb_ability = slot.get("direct_absorb_target_ability", "")

                # Apply filters
                # Only count direct_absorb_immune_move_selected as a real absorb selection
                # ability_immune_move_selected alone is NOT sufficient — it may be set
                # when the ability was detected but _ability_block_enabled returned False
                # (e.g., absorb abilities with ability_hard_safety_avoid_absorb=False)
                is_absorb = absorb_selected

                if args.direct_known_absorb and not is_absorb:
                    continue
                if args.avoided and not absorb_avoided:
                    continue
                if args.only_legal and not absorb_only_legal:
                    continue

                # Show cases where absorb was selected OR avoided
                if is_absorb or absorb_avoided:
                    case = {
                        "battle_tag": battle_tag,
                        "turn": turn,
                        "slot": slot_key,
                        "action": slot.get("action", ""),
                        "move_type": slot.get("move_type", ""),
                        "target_species": absorb_target,
                        "target_ability": absorb_ability,
                        "reason": absorb_reason,
                        "absorb_selected": absorb_selected,
                        "absorb_avoided": absorb_avoided,
                        "absorb_only_legal": absorb_only_legal,
                        "selected_score": slot.get("selected_score", 0),
                        "best_alternative": slot.get("best_safe_alternative", ""),
                        "top_5_alternatives": slot.get("top_5_alternatives", []),
                    }
                    cases.append(case)

    # Print results
    if not cases:
        print("No matching cases found.")
        return

    print(f"Found {len(cases)} case(s):")
    print("-" * 80)
    for i, case in enumerate(cases, 1):
        print(f"\n  Case {i}:")
        print(f"    Battle: {case['battle_tag']} Turn: {case['turn']} Slot: {case['slot']}")
        print(f"    Action: {case['action']}")
        print(f"    Move Type: {case['move_type']}")
        print(f"    Target: {case['target_species']} ({case['target_ability']})")
        print(f"    Reason: {case['reason']}")
        print(f"    Absorb Selected: {case['absorb_selected']}")
        print(f"    Avoided: {case['absorb_avoided']}")
        print(f"    Only Legal: {case['absorb_only_legal']}")
        print(f"    Selected Score: {case['selected_score']}")
        if case['best_alternative']:
            print(f"    Best Alternative: {case['best_alternative']}")
        if case['top_5_alternatives']:
            print(f"    Top 5 Alternatives: {case['top_5_alternatives']}")


def main():
    parser = argparse.ArgumentParser(
        description="Inspector for known absorb hard safety cases"
    )
    parser.add_argument("--direct-known-absorb", action="store_true",
                        help="Show direct known absorb events")
    parser.add_argument("--repeat", action="store_true",
                        help="Show repeat selections")
    parser.add_argument("--avoided", action="store_true",
                        help="Show avoided absorb selections")
    parser.add_argument("--only-legal", action="store_true",
                        help="Show only-legal absorb selections")
    parser.add_argument("--battle", type=str, default=None,
                        help="Filter by battle tag substring")
    parser.add_argument("--filepath", type=str, required=True,
                        help="Path to JSONL audit file")
    args = parser.parse_args()

    inspect_cases(args)


if __name__ == "__main__":
    main()
