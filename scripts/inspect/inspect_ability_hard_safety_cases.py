#!/usr/bin/env python3
import json
import os
import argparse
import sys

def classify_absorb_event(slot):
    if not slot.get("absorb_immune_move_selected"):
        return "UNCLASSIFIED"
    if slot.get("productive_partial_absorb_spread"):
        return "PRODUCTIVE_PARTIAL_SPREAD"
    if slot.get("avoidable_absorb_error"):
        return "AVOIDABLE_SAFE_DAMAGE_ALT"
    if slot.get("absorb_selection_forced"):
        return "FORCED_NO_USEFUL_SCORED_ALT"
    if not slot.get("absorb_safe_alternative_available") and not slot.get("absorb_selection_forced"):
        return "OTHER_USEFUL_SCORED_ALT"
    return "UNCLASSIFIED"

def main():
    parser = argparse.ArgumentParser(description="Diagnostic Inspector for Double Battle Ability Hard Safety Cases")
    parser.main_group = parser.add_mutually_exclusive_group()
    parser.main_group.add_argument("--ground-into-levitate", action="store_true", help="Filter for Ground moves into Levitate targets")
    parser.main_group.add_argument("--ability-immune", action="store_true", help="Filter for moves targeting known ability immunities")
    parser.main_group.add_argument("--blocks-avoided", action="store_true", help="Filter for turns where an ability block was avoided")
    parser.main_group.add_argument("--ally-safe-spread", action="store_true", help="Filter for spread moves with ally safe ability")
    parser.main_group.add_argument("--redirection", action="store_true", help="Filter for redirections avoided/triggered")
    parser.main_group.add_argument("--partial-ability-spread", action="store_true", help="Filter for partial ability-immune spread selections")
    parser.main_group.add_argument("--absorb-selected", action="store_true", help="Filter for absorb-immune moves selected")
    parser.main_group.add_argument("--avoidable-absorb", action="store_true", help="Filter for avoidable absorb errors")
    parser.main_group.add_argument("--forced-absorb", action="store_true", help="Filter for forced absorb selections")
    parser.main_group.add_argument("--productive-partial-absorb", action="store_true", help="Filter for productive partial absorb spreads")
    parser.main_group.add_argument("--other-useful-alt", action="store_true", help="Filter for other useful scored alternatives")
    parser.add_argument("--absorb-streak-min", type=int, default=None, help="Filter for consecutive absorb streak minimum count")
    parser.add_argument("--battle", type=str, help="Filter for specific battle tag")
    parser.add_argument("--filepath", type=str, default="logs/doubles_decision_audit.jsonl", help="Path to audit JSONL file")

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
                our_active = turn_data.get("our_active", [None, None])
                selected_joint_order = turn_data.get("selected_joint_order", "")
                top_5_alts = turn_data.get("top_5_alternatives", [])
                top_5_scores = turn_data.get("top_5_scores", [])
                opp_actions = turn_data.get("opp_actions", {})

                for idx, slot_key in enumerate(("slot_0", "slot_1")):
                    slot = turn_data.get(slot_key, {})
                    if not slot:
                        continue

                    match = False
                    reason = ""
                    
                    if args.ground_into_levitate:
                        if slot.get("ground_into_levitate_selected"):
                            match = True
                            reason = "ground_into_levitate"
                    elif args.ability_immune:
                        if slot.get("ability_immune_move_selected"):
                            match = True
                            reason = "ability_immune_move_selected"
                    elif args.blocks_avoided:
                        if slot.get("ability_hard_block_avoided"):
                            match = True
                            reason = "ability_hard_block_avoided"
                    elif args.ally_safe_spread:
                        if slot.get("ally_ability_safe_spread"):
                            match = True
                            reason = "ally_ability_safe_spread"
                    elif args.redirection:
                        if slot.get("ability_redirection_avoided"):
                            match = True
                            reason = "ability_redirection_avoided"
                    elif args.partial_ability_spread:
                        if slot.get("partial_ability_immune_spread_selected"):
                            match = True
                            reason = "partial_ability_immune_spread_selected"
                    elif args.absorb_selected:
                        if slot.get("absorb_immune_move_selected"):
                            match = True
                            reason = "absorb_immune_move_selected"
                    elif args.avoidable_absorb:
                        if slot.get("avoidable_absorb_error"):
                            match = True
                            reason = "avoidable_absorb_error"
                    elif args.forced_absorb:
                        if slot.get("absorb_selection_forced"):
                            match = True
                            reason = "absorb_selection_forced"
                    elif args.productive_partial_absorb:
                        if slot.get("productive_partial_absorb_spread"):
                            match = True
                            reason = "productive_partial_absorb_spread"
                    elif args.other_useful_alt:
                        if classify_absorb_event(slot) == "OTHER_USEFUL_SCORED_ALT":
                            match = True
                            reason = "other_useful_scored_alt"
                    else:
                        # Default matching matches any ability metric
                        if (slot.get("ability_hard_block_avoided") or 
                            slot.get("ability_immune_move_selected") or
                            slot.get("ground_into_levitate_selected") or
                            slot.get("ally_ability_safe_spread") or
                            slot.get("ability_redirection_avoided") or
                            slot.get("partial_ability_immune_spread_selected") or
                            slot.get("absorb_immune_move_selected") or
                            slot.get("avoidable_absorb_error") or
                            slot.get("absorb_selection_forced") or
                            slot.get("productive_partial_absorb_spread")):
                            match = True
                            reason = "any_ability_flag"

                    if match and args.absorb_streak_min is not None:
                        streak = slot.get("absorb_selected_streak", 0)
                        if streak < args.absorb_streak_min:
                            match = False

                    if match:
                        attacker = our_active[idx].get("species") if (len(our_active) > idx and our_active[idx]) else "Unknown"
                        
                        classification = classify_absorb_event(slot)
                        
                        matched_cases.append({
                            "type": "our_bot_ability_error" if (slot.get("ability_immune_move_selected") or slot.get("absorb_immune_move_selected") or slot.get("avoidable_absorb_error")) else "our_bot_info",
                            "battle_tag": battle_tag,
                            "turn": turn,
                            "won": is_win,
                            "attacker": attacker,
                            "selected_move": slot.get("action", ""),
                            "move_type": slot.get("move_type", ""),
                            "target": slot.get("ability_blocked_target_species") or slot.get("target_species", ""),
                            "target_ability": slot.get("ability_blocked_target_ability", ""),
                            "block_reason": slot.get("absorb_error_reason") or slot.get("ability_block_reason", ""),
                            "selected_joint_order": selected_joint_order,
                            "top_5": list(zip(top_5_alts, top_5_scores)),
                            "streak": slot.get("absorb_selected_streak", 0),
                            "best_alt_move": slot.get("absorb_best_safe_alternative_move") or "",
                            "best_alt_target": slot.get("absorb_best_safe_alternative_target") or "",
                            "best_alt_score": slot.get("absorb_best_safe_alternative_score") or 0.0,
                            
                            # Phase 6.3.2b exhaustive fields
                            "classification": classification,
                            "forced": bool(slot.get("absorb_selection_forced", False)),
                            "safe_damaging_alt_available": bool(slot.get("absorb_safe_alternative_available", False)),
                            "productive_spread": bool(slot.get("productive_partial_absorb_spread", False)),
                            "avoidable": bool(slot.get("avoidable_absorb_error", False)),
                            "via_redirection": bool(slot.get("absorb_via_redirection", False)),
                            "intended_target_species": slot.get("absorb_intended_target_species", ""),
                            "intended_target_ability": slot.get("absorb_intended_target_ability", ""),
                            "effective_target_species": slot.get("absorb_effective_target_species", ""),
                            "effective_target_ability": slot.get("absorb_effective_target_ability", ""),
                            "selected_move_id": slot.get("absorb_selected_move_id") or slot.get("action", ""),
                            "selected_canonical_score": float(slot.get("absorb_selected_score") or 0.0)
                        })

                # Opponent errors check
                opp_match = False
                opp_reason = ""
                if (args.absorb_selected or args.avoidable_absorb or args.forced_absorb 
                    or args.productive_partial_absorb or args.other_useful_alt or args.absorb_streak_min is not None):
                    # Never mix opponent errors into bot-only filters
                    pass
                elif args.ground_into_levitate:
                    if opp_actions.get("opponent_ground_into_levitate"):
                        opp_match = True
                        opp_reason = "ground_into_levitate"
                elif args.ability_immune:
                    if opp_actions.get("opponent_ability_error"):
                        opp_match = True
                        opp_reason = "opponent_ability_error"
                elif (not args.blocks_avoided and 
                      not args.ally_safe_spread and 
                      not args.redirection and 
                      not args.partial_ability_spread):
                    if opp_actions.get("opponent_ability_error"):
                        opp_match = True
                        opp_reason = "opponent_ability_error"

                if opp_match:
                    matched_cases.append({
                        "type": "opponent_ability_error",
                        "battle_tag": battle_tag,
                        "turn": turn,
                        "won": is_win,
                        "attacker": "Opponent",
                        "selected_move": "Opponent Move",
                        "move_type": "",
                        "target": "Our Active",
                        "target_ability": "",
                        "block_reason": opp_reason,
                        "selected_joint_order": selected_joint_order,
                        "top_5": []
                    })

    if not matched_cases:
        print("No cases matching the filters were found.")
        return

    print(f"Found {len(matched_cases)} matched cases:\n")
    for idx, case in enumerate(matched_cases, 1):
        outcome = "WIN" if case.get("won") else "LOSS"
        print(f"Case #{idx}: [{case['type'].upper()}] (Battle Outcome: {outcome})")
        print(f"  Battle Tag      : {case['battle_tag']}")
        print(f"  Turn            : {case['turn']}")
        print(f"  Attacker        : {case['attacker']}")
        print(f"  Selected Move   : {case['selected_move']}")
        print(f"  Move Type       : {case['move_type']}")
        
        # If it has absorb classification details, print them
        if case.get("classification") and case["classification"] != "UNCLASSIFIED":
            print(f"  Classification  : {case['classification']}")
            direction = "REDIRECTED" if case["via_redirection"] else "DIRECT"
            print(f"  Redirection Type: {direction}")
            print(f"  Intended Target : {case['intended_target_species']} (Known Ability: {case['intended_target_ability'] or 'unknown'})")
            print(f"  Effective Target: {case['effective_target_species']} (Known Ability: {case['effective_target_ability'] or 'unknown'})")
            print(f"  Raw Booleans    : forced={case['forced']}, safe_damaging_alt={case['safe_damaging_alt_available']}, productive_spread={case['productive_spread']}, avoidable={case['avoidable']}")
            print(f"  Selected Score  : {case['selected_canonical_score']:.2f} (canonical)")
        else:
            print(f"  Target          : {case['target']}")
            print(f"  Target Ability  : {case['target_ability']}")
            
        print(f"  Block Reason    : {case['block_reason']}")
        if case.get("streak", 0) > 0:
            print(f"  Streak Count    : {case['streak']}")
        if case.get("best_alt_move"):
            print(f"  Best Alt Move   : {case['best_alt_move']} -> {case['best_alt_target']} (Score: {case['best_alt_score']:.2f})")
        print(f"  Joint Order     : {case['selected_joint_order']}")
        if case["top_5"]:
            print("  Top Alternatives:")
            for alt, sc in case["top_5"]:
                print(f"    - {alt:<40} (Score: {sc:.2f})")
        print("-" * 60)

if __name__ == "__main__":
    main()
