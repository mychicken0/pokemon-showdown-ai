#!/usr/bin/env python3
"""Inspector for Phase 6.4.2 revealed-move switch interception cases.

Filters:
  --selected
  --changed
  --correct
  --wrong
  --ko-blocked
  --high-value-blocked
  --worse-other-threat
  --electric-ground
  --our-type-immune-error
  --opponent-type-immune-error
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

                        # Apply filters
                        if args.selected and not slot.get("revealed_switch_interception_selected"):
                            continue
                        if args.changed and not slot.get("revealed_switch_selection_changed"):
                            continue
                        if args.correct and not slot.get("revealed_switch_prediction_correct"):
                            continue
                        if args.wrong and not slot.get("revealed_switch_prediction_wrong"):
                            continue
                        if args.ko_blocked and not slot.get("revealed_switch_blocked_by_ko_action"):
                            continue
                        if args.high_value_blocked and not slot.get("revealed_switch_blocked_by_high_value_action"):
                            continue
                        if args.worse_other_threat and not slot.get("revealed_switch_rejected_worse_other_threat"):
                            continue
                        if args.our_type_immune_error and not slot.get("our_type_immune_move_selected"):
                            continue
                        if args.opponent_type_immune_error and not slot.get("opponent_type_immune_move_selected"):
                            continue

                        # Electric/Ground filter
                        if args.electric_ground:
                            types = slot.get("selected_switch_types", "")
                            if "Electric" not in str(types) or "Ground" not in str(types):
                                continue

                        # Check if any filter is active
                        has_filter = any([
                            args.selected, args.changed, args.correct, args.wrong,
                            args.ko_blocked, args.high_value_blocked, args.worse_other_threat,
                            args.electric_ground, args.our_type_immune_error,
                            args.opponent_type_immune_error,
                        ])

                        # If no filter, show all cases with interception data
                        if not has_filter:
                            if not slot.get("revealed_switch_prediction_available"):
                                continue

                        result = {
                            "battle_tag": battle_tag,
                            "turn": turn_num,
                            "slot": slot_key,
                            "outcome": "win" if won else "loss",
                            "prediction_available": slot.get("revealed_switch_prediction_available", False),
                            "interception_selected": slot.get("revealed_switch_interception_selected", False),
                            "selection_changed": slot.get("revealed_switch_selection_changed", False),
                            "threatening_opponent": slot.get("revealed_switch_threatening_opponent", ""),
                            "threat_move_ids": slot.get("revealed_switch_threat_move_ids", []),
                            "threat_move_types": slot.get("revealed_switch_threat_move_types", []),
                            "active_risk": slot.get("revealed_switch_active_risk", 0.0),
                            "candidate_risk": slot.get("revealed_switch_candidate_risk", 0.0),
                            "risk_reduction": slot.get("revealed_switch_risk_reduction", 0.0),
                            "candidate_species": slot.get("revealed_switch_candidate_species", ""),
                            "candidate_types": slot.get("revealed_switch_candidate_types", ""),
                            "candidate_hp": slot.get("revealed_switch_candidate_hp", 1.0),
                            "bonus_applied": slot.get("revealed_switch_bonus_applied", 0.0),
                            "blocked_by_ko": slot.get("revealed_switch_blocked_by_ko_action", False),
                            "blocked_by_high_value": slot.get("revealed_switch_blocked_by_high_value_action", False),
                            "worse_other_threat": slot.get("revealed_switch_rejected_worse_other_threat", False),
                            "post_turn_survived": slot.get("revealed_switch_post_turn_survived", True),
                            "predicted_move_used": slot.get("revealed_switch_predicted_move_used", ""),
                            "prediction_correct": slot.get("revealed_switch_prediction_correct", False),
                            "prediction_wrong": slot.get("revealed_switch_prediction_wrong", False),
                            "our_type_immune_error": slot.get("our_type_immune_move_selected", False),
                            "opponent_type_immune_error": slot.get("opponent_type_immune_move_selected", False),
                            "action": slot.get("action", ""),
                        }
                        results.append(result)
            except Exception:
                continue

    if not results:
        print("No matching cases found.")
        return

    print(f"Found {len(results)} matching case(s):\n")
    for idx, r in enumerate(results, 1):
        tags = []
        if r["interception_selected"]:
            tags.append("SELECTED")
        if r["selection_changed"]:
            tags.append("CHANGED")
        if r["prediction_correct"]:
            tags.append("CORRECT")
        if r["prediction_wrong"]:
            tags.append("WRONG")
        if r["blocked_by_ko"]:
            tags.append("KO_BLOCKED")
        if r["blocked_by_high_value"]:
            tags.append("HIGH_VALUE_BLOCKED")
        if r["worse_other_threat"]:
            tags.append("WORSE_OTHER")
        if not r["post_turn_survived"]:
            tags.append("FAINTED")
        if r["our_type_immune_error"]:
            tags.append("OUR_IMMUNE_ERR")
        if r["opponent_type_immune_error"]:
            tags.append("OPP_IMMUNE_ERR")

        tag_str = " | ".join(tags) if tags else "PREDICTION_AVAILABLE"

        print(f"  {idx}. Battle: {r['battle_tag']} Turn: {r['turn']} Slot: {r['slot']} ({r['outcome']})")
        print(f"     Tags: {tag_str}")
        if r["threatening_opponent"]:
            print(f"     Threat: {r['threatening_opponent']} Moves: {r['threat_move_ids']} ({r['threat_move_types']})")
        if r["candidate_species"]:
            print(f"     Candidate: {r['candidate_species']} ({r['candidate_types']}) HP: {r['candidate_hp']:.2f}")
            print(f"     Risk: active={r['active_risk']:.1f} candidate={r['candidate_risk']:.1f} reduction={r['risk_reduction']:.1f}")
            print(f"     Bonus: {r['bonus_applied']:.1f}")
        if r["predicted_move_used"]:
            print(f"     Predicted move used: {r['predicted_move_used']}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Inspect revealed-move switch interception cases")
    parser.add_argument("--selected", action="store_true", help="Show cases where interception was selected")
    parser.add_argument("--changed", action="store_true", help="Show cases where selection changed")
    parser.add_argument("--correct", action="store_true", help="Show correct predictions")
    parser.add_argument("--wrong", action="store_true", help="Show wrong predictions")
    parser.add_argument("--ko-blocked", action="store_true", help="Show KO-blocked cases")
    parser.add_argument("--high-value-blocked", action="store_true", help="Show high-value-blocked cases")
    parser.add_argument("--worse-other-threat", action="store_true", help="Show worse-other-threat cases")
    parser.add_argument("--electric-ground", action="store_true", help="Show Electric/Ground cases")
    parser.add_argument("--our-type-immune-error", action="store_true", help="Show our type-immune errors")
    parser.add_argument("--opponent-type-immune-error", action="store_true", help="Show opponent type-immune errors")
    parser.add_argument("--battle", type=str, default=None, help="Filter by battle tag")
    parser.add_argument("--filepath", type=str, default="logs/doubles_decision_audit.jsonl", help="Path to audit JSONL")
    args = parser.parse_args()
    inspect(args)


if __name__ == "__main__":
    main()
