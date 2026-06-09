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
    parser = argparse.ArgumentParser(description="Diagnostic Inspector for Double Battle Absorb Error Cases")
    parser.main_group = parser.add_mutually_exclusive_group()
    parser.main_group.add_argument("--absorb-selected", action="store_true", help="Filter for absorb-immune moves selected")
    parser.main_group.add_argument("--avoidable-absorb", action="store_true", help="Filter for avoidable absorb errors")
    parser.main_group.add_argument("--forced-absorb", action="store_true", help="Filter for forced absorb selections")
    parser.main_group.add_argument("--productive-partial-absorb", action="store_true", help="Filter for productive partial absorb spreads")
    parser.main_group.add_argument("--other-useful-alt", action="store_true", help="Filter for other useful scored alternatives")
    parser.main_group.add_argument("--direct-block-avoided", action="store_true", help="Filter for direct absorb blocks avoided")
    parser.main_group.add_argument("--direct-immune-selected", action="store_true", help="Filter for direct absorb immune moves selected")
    parser.main_group.add_argument("--direct-only-legal", action="store_true", help="Filter for direct absorb immune moves selected that were only legal actions")
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

                for idx, slot_key in enumerate(("slot_0", "slot_1")):
                    slot = turn_data.get(slot_key, {})
                    if not slot:
                        continue

                    match = False
                    
                    if args.absorb_selected:
                        if slot.get("absorb_immune_move_selected"):
                            match = True
                    elif args.avoidable_absorb:
                        if slot.get("avoidable_absorb_error"):
                            match = True
                    elif args.forced_absorb:
                        if slot.get("absorb_selection_forced"):
                            match = True
                    elif args.productive_partial_absorb:
                        if slot.get("productive_partial_absorb_spread"):
                            match = True
                    elif args.other_useful_alt:
                        if classify_absorb_event(slot) == "OTHER_USEFUL_SCORED_ALT":
                            match = True
                    elif args.direct_block_avoided:
                        if slot.get("direct_absorb_hard_block_avoided"):
                            match = True
                    elif args.direct_immune_selected:
                        if slot.get("direct_absorb_immune_move_selected"):
                            match = True
                    elif args.direct_only_legal:
                        if slot.get("direct_absorb_immune_move_selected") and slot.get("direct_absorb_only_legal_action"):
                            match = True
                    else:
                        # Default matching matches any absorb event
                        if slot.get("absorb_immune_move_selected") or slot.get("direct_absorb_immune_move_selected"):
                            match = True

                    if match and args.absorb_streak_min is not None:
                        streak = slot.get("absorb_selected_streak", 0)
                        if streak < args.absorb_streak_min:
                            match = False

                    if match:
                        attacker = our_active[idx].get("species") if (len(our_active) > idx and our_active[idx]) else "Unknown"
                        
                        matched_cases.append({
                            "battle_tag": battle_tag,
                            "turn": turn,
                            "won": is_win,
                            "attacker": attacker,
                            "selected_move_id": slot.get("absorb_selected_move_id") or slot.get("action", ""),
                            "target": slot.get("ability_blocked_target_species") or slot.get("target_species", ""),
                            "target_ability": slot.get("ability_blocked_target_ability", ""),
                            "block_reason": slot.get("absorb_error_reason") or slot.get("ability_block_reason", ""),
                            "classification": classify_absorb_event(slot),
                            "streak": slot.get("absorb_selected_streak", 0),
                            "via_redirection": bool(slot.get("absorb_via_redirection", False)),
                            "intended_target_species": slot.get("absorb_intended_target_species", ""),
                            "intended_target_ability": slot.get("absorb_intended_target_ability", ""),
                            "effective_target_species": slot.get("absorb_effective_target_species", ""),
                            "effective_target_ability": slot.get("absorb_effective_target_ability", ""),
                            "selected_canonical_score": float(slot.get("absorb_selected_score") or 0.0),
                            "best_alt_move": slot.get("absorb_best_safe_alternative_move") or "",
                            "best_alt_target": slot.get("absorb_best_safe_alternative_target") or "",
                            "best_alt_canonical_score": float(slot.get("absorb_best_safe_alternative_score") or 0.0),
                            
                            # Raw booleans
                            "forced": bool(slot.get("absorb_selection_forced", False)),
                            "safe_damaging_alt_available": bool(slot.get("absorb_safe_alternative_available", False)),
                            "productive_spread": bool(slot.get("productive_partial_absorb_spread", False)),
                            "avoidable": bool(slot.get("avoidable_absorb_error", False)),
                            
                            # Phase 6.3.3 direct absorb fields
                            "direct_avoided": bool(slot.get("direct_absorb_hard_block_avoided", False)),
                            "direct_selected": bool(slot.get("direct_absorb_immune_move_selected", False)),
                            "direct_only_legal": bool(slot.get("direct_absorb_only_legal_action", False)),
                            "direct_target_species": slot.get("direct_absorb_target_species", ""),
                            "direct_target_ability": slot.get("direct_absorb_target_ability", "")
                        })

    if not matched_cases:
        print("No cases matching the filters were found.")
        return

    print(f"Found {len(matched_cases)} matched absorb error cases:\n")
    for idx, case in enumerate(matched_cases, 1):
        outcome = "WIN" if case["won"] else "LOSS"
        direction = "REDIRECTED" if case["via_redirection"] else "DIRECT"
        print(f"Case #{idx}: [{case['classification']}] [{direction}] (Battle Outcome: {outcome})")
        print(f"  Battle Tag         : {case['battle_tag']}")
        print(f"  Turn               : {case['turn']}")
        print(f"  Attacker           : {case['attacker']}")
        print(f"  Selected Move ID   : {case['selected_move_id']}")
        print(f"  Intended Target    : {case['intended_target_species']} (Known Ability: {case['intended_target_ability'] or 'unknown'})")
        print(f"  Effective Target   : {case['effective_target_species']} (Known Ability: {case['effective_target_ability'] or 'unknown'}) {'<-- REDIRECTOR' if case['via_redirection'] else ''}")
        print(f"  Raw Booleans       : forced={case['forced']}, safe_damaging_alt={case['safe_damaging_alt_available']}, productive_spread={case['productive_spread']}, avoidable={case['avoidable']}")
        print(f"  Block Reason       : {case['block_reason']}")
        print(f"  Direct Block       : avoided={case['direct_avoided']}, selected={case['direct_selected']} (only legal={case['direct_only_legal']})")
        if case['direct_selected']:
            print(f"  Direct Target      : {case['direct_target_species']} (Known Ability: {case['direct_target_ability'] or 'unknown'})")
        print(f"  Streak Count       : {case['streak']}")
        print(f"  Selected Score     : {case['selected_canonical_score']:.2f} (canonical)")
        if case["best_alt_move"]:
            print(f"  Best Safe Alt      : {case['best_alt_move']} -> {case['best_alt_target']} (Canonical Score: {case['best_alt_canonical_score']:.2f})")
        else:
            print(f"  Best Safe Alt      : None")
        print("-" * 60)

if __name__ == "__main__":
    main()
