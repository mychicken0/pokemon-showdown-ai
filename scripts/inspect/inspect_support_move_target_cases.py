#!/usr/bin/env python3
"""Inspect support move target cases from audit logs."""
import json
import os
import sys


def inspect_support_move_target_cases(
    filepath="logs/doubles_decision_audit.jsonl",
    show_selected=False,
    show_avoided=False,
    show_only_legal=False,
    show_heal_pulse=False,
    show_ally_benefit_into_opponent=False,
    show_opponent_disruption_into_ally=False,
    move_filter=None,
    battle_filter=None,
):
    if not os.path.exists(filepath):
        print(f"Error: Log file not found at {filepath}")
        return

    found = 0
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                turn = json.loads(line)
            except json.JSONDecodeError:
                continue

            event = turn.get("event", "")
            if event != "decision":
                continue

            bt = str(turn.get("battle_tag", ""))
            if battle_filter and battle_filter not in bt:
                continue

            for slot_key in ("slot_0", "slot_1"):
                slot = turn.get(slot_key, {})
                if not slot:
                    continue

                cand_blocked = slot.get("support_target_candidate_blocked", False)
                selected = slot.get("support_target_selected", False)
                avoided = slot.get("support_target_avoided", False)
                only_legal = slot.get("support_target_only_legal", False)
                move_id = slot.get("support_target_move_id", "")
                intended = slot.get("support_target_intended_side", "")
                actual = slot.get("support_target_actual_side", "")
                reason = slot.get("support_target_reason", "")
                source = slot.get("support_target_classification_source", "")
                t_pos = slot.get("support_target_target_position", None)
                t_species = slot.get("support_target_target_species", "")
                t_identity = slot.get("support_target_target_identity", "")
                blocked_score = slot.get("support_target_blocked_candidate_score", None)
                safe_kind = slot.get("support_target_safe_alternative_kind", "")
                safe_move = slot.get("support_target_safe_alternative_move_id", "")
                safe_tpos = slot.get("support_target_safe_alternative_target_position", None)

                # Actual selected action
                action = slot.get("action", "")
                action_move = slot.get("move_type", "")

                outcome = turn.get("outcome", "")

                # Apply filters
                if show_selected and not selected:
                    continue
                if show_avoided and not avoided:
                    continue
                if show_only_legal and not only_legal:
                    continue
                if show_heal_pulse and "healpulse" not in (move_id, action_move):
                    continue
                if show_ally_benefit_into_opponent and not (
                    intended == "ally" and actual == "opponent"
                ):
                    continue
                if show_opponent_disruption_into_ally and not (
                    intended == "opponent" and actual in ("ally", "self")
                ):
                    continue
                if move_filter and move_filter not in move_id:
                    continue

                if not any([show_selected, show_avoided, show_only_legal,
                            show_heal_pulse, show_ally_benefit_into_opponent,
                            show_opponent_disruption_into_ally, move_filter]):
                    if not cand_blocked and not selected and not avoided:
                        continue

                print(f"--- Battle: {bt} | Turn: {turn.get('turn')} | Slot: {slot_key} ---")
                print(f"  Attacker: {turn.get('our_active', ['?','?'])[0 if slot_key == 'slot_0' else 1]}")
                print(f"  Move: {action_move}")
                print(f"  Intended Side: {intended}")
                print(f"  Actual Side: {actual}")
                print(f"  Target Species: {t_species}")
                print(f"  Target Identity: {t_identity}")
                print(f"  Reason: {reason}")
                print(f"  Source: {source}")
                print(f"  Target Position: {t_pos}")
                print(f"  Candidate Blocked: {cand_blocked}")
                print(f"  Selected: {selected}")
                print(f"  Avoided: {avoided}")
                print(f"  Only Legal: {only_legal}")
                if blocked_score is not None:
                    print(f"  Blocked Candidate Score: {blocked_score}")
                if safe_kind:
                    print(f"  Safe Alternative Kind: {safe_kind}")
                if safe_move:
                    print(f"  Safe Alternative Move ID: {safe_move}")
                if safe_tpos is not None:
                    print(f"  Safe Alternative Target Position: {safe_tpos}")
                print(f"  Outcome: {outcome}")
                print()
                found += 1

    if found == 0:
        print("No matching support move target cases found.")
    else:
        print(f"Total matching cases: {found}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Inspect support move target cases")
    parser.add_argument("--selected", action="store_true", help="Show wrong-side selected actions")
    parser.add_argument("--avoided", action="store_true", help="Show wrong-side avoided actions")
    parser.add_argument("--only-legal", action="store_true", help="Show only-legal classifications")
    parser.add_argument("--heal-pulse", action="store_true", help="Show Heal Pulse cases")
    parser.add_argument("--ally-benefit-into-opponent", action="store_true",
                        help="Show ally-benefit moves targeting opponents")
    parser.add_argument("--opponent-disruption-into-ally", action="store_true",
                        help="Show opponent-disruption moves targeting allies")
    parser.add_argument("--move", dest="move_filter", help="Filter by move ID")
    parser.add_argument("--battle", dest="battle_filter", help="Filter by battle tag")
    parser.add_argument("--filepath", default="logs/doubles_decision_audit.jsonl",
                        help="Path to audit log file")
    args = parser.parse_args()

    inspect_support_move_target_cases(
        filepath=args.filepath,
        show_selected=args.selected,
        show_avoided=args.avoided,
        show_only_legal=args.only_legal,
        show_heal_pulse=args.heal_pulse,
        show_ally_benefit_into_opponent=args.ally_benefit_into_opponent,
        show_opponent_disruption_into_ally=args.opponent_disruption_into_ally,
        move_filter=args.move_filter,
        battle_filter=args.battle_filter,
    )
