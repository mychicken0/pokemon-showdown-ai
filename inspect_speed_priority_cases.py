#!/usr/bin/env python3
import json
import os
import sys
import argparse

def main():
    parser = argparse.ArgumentParser(description="Inspect Speed/Priority Decisions from Audit Logs")
    parser.add_argument("--filepath", default="logs/doubles_decision_audit.jsonl", help="Path to audit log file")
    parser.add_argument("--battle", help="Filter by battle tag")
    parser.add_argument("--bad-protect", action="store_true", help="Filter by refined bad protect")
    parser.add_argument("--unanswered", action="store_true", help="Filter by true unanswered speed/priority threat")
    parser.add_argument("--productive-attack", action="store_true", help="Filter by productive attack under threat")
    parser.add_argument("--false-positive", action="store_true", help="Filter by false positive threat")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.filepath):
        print(f"Error: Log file not found at {args.filepath}")
        sys.exit(1)
        
    matching_turns = []
    
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
                
            audit_turns = battle.get("audit_turns", [])
            for turn_data in audit_turns:
                for slot_idx, slot_key in enumerate(("slot_0", "slot_1")):
                    slot = turn_data.get(slot_key, {})
                    other = turn_data.get("slot_1" if slot_key == "slot_0" else "slot_0", {})
                    
                    if not slot.get("outcome_known"):
                        continue
                        
                    # Classify categories
                    is_protect = slot.get("action_types", {}).get("protect", False)
                    is_switch = slot.get("action_types", {}).get("switch", False)
                    
                    # 1. detected threat
                    is_threat = slot.get("speed_priority_threatened", False)
                    
                    # 2. true unanswered
                    is_true_unanswered = False
                    if is_threat and not is_protect and not is_switch:
                        not_unanswered = (
                            slot.get("fainted_before_moving") == False or
                            slot.get("actual_ko") == True or
                            (slot.get("action_types", {}).get("spread") and slot.get("actual_damage") is not None and slot.get("actual_damage") >= 0.20) or
                            slot.get("protect_like_available") == False or
                            slot.get("switch_available") == False or
                            slot.get("only_conditional_priority") == True or
                            slot.get("was_targeted") == False or
                            slot.get("active_moved_before_threat") == True
                        )
                        if not not_unanswered:
                            is_true_unanswered = True
                            
                    # 3. productive attack
                    is_productive_attack = False
                    if is_threat and not is_protect and not is_switch:
                        is_attack = slot.get("action") and "pass" not in slot.get("action", "")
                        if is_attack:
                            is_productive_attack = (
                                slot.get("actual_ko") == True or
                                (slot.get("action_types", {}).get("spread") and slot.get("actual_damage") is not None and slot.get("actual_damage") > 0.0) or
                                (slot.get("actual_damage") is not None and slot.get("actual_damage") >= 0.30)
                            )
                            
                    # 4. false positive
                    is_false_positive = False
                    if is_threat:
                        if slot.get("was_targeted") == False or slot.get("our_mon_fainted") == False:
                            is_false_positive = True
                            
                    # 5. bad protect refined
                    is_bad_protect = False
                    if slot.get("protected_due_to_speed_priority") and is_protect:
                        if slot.get("was_targeted") == False:
                            ally_did_good = (other.get("actual_ko") or (other.get("actual_damage") is not None and other["actual_damage"] >= 0.30))
                            if not ally_did_good:
                                is_stalling = slot.get("stalling_field_condition", False)
                                if not is_stalling:
                                    is_bad_protect = True
                                    
                    # Apply filters
                    matched = True
                    if args.bad_protect and not is_bad_protect:
                        matched = False
                    if args.unanswered and not is_true_unanswered:
                        matched = False
                    if args.productive_attack and not is_productive_attack:
                        matched = False
                    if args.false_positive and not is_false_positive:
                        matched = False
                        
                    # If any of the main filters are selected, it must match at least one of them
                    if not (args.bad_protect or args.unanswered or args.productive_attack or args.false_positive):
                        # If no filters, show only when there is speed/priority activity
                        if not (is_threat or slot.get("protected_due_to_speed_priority")):
                            matched = False
                            
                    if matched:
                        matching_turns.append((battle_tag, turn_data, slot_idx, {
                            "bad_protect": is_bad_protect,
                            "unanswered": is_true_unanswered,
                            "productive_attack": is_productive_attack,
                            "false_positive": is_false_positive
                        }))
                        
    if not matching_turns:
        print("No matching cases found in the logs.")
        return
        
    print(f"Found {len(matching_turns)} matching turns:\n")
    for b_tag, turn, slot_idx, classifications in matching_turns:
        slot_key = "slot_0" if slot_idx == 0 else "slot_1"
        slot = turn[slot_key]
        
        our_active = turn.get("our_active", [None, None])[slot_idx]
        our_species = our_active.get("species", "Unknown") if our_active else "Unknown"
        our_hp = our_active.get("hp", 1.0) if our_active else 1.0
        
        opps = [opp.get("species", "Unknown") for opp in turn.get("opp_active", []) if opp]
        
        print(f"Battle Tag            : {b_tag}")
        print(f"Turn                  : {turn.get('turn')}")
        print(f"Our Active Pokemon    : {our_species} (HP: {our_hp:.2f})")
        print(f"Opponent Active Pair  : {', '.join(opps)}")
        print(f"Selected Joint Order  : {turn.get('selected_joint_order')}")
        print(f"Selected Slot Action  : {slot.get('action')}")
        
        # Threat info
        print(f"Speed/Prio Threatened : {slot.get('speed_priority_threatened')}")
        print(f"Faster Opponents      : {slot.get('faster_opponents')}")
        print(f"Priority Opponents    : {slot.get('priority_opponents')}")
        print(f"Faint Before Moving   : {slot.get('fainted_before_moving')}")
        print(f"Was Targeted          : {slot.get('was_targeted')}")
        print(f"Active Moved Before   : {slot.get('active_moved_before_threat')}")
        
        # Classification
        class_list = []
        for name, val in classifications.items():
            if val:
                class_list.append(name.upper())
        if not class_list:
            class_list.append("GOOD / NEUTRAL")
        print(f"Analyzer Classify     : {', '.join(class_list)}")
        print("-" * 50)

if __name__ == "__main__":
    main()
