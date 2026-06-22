#!/usr/bin/env python3
import json
import os
import sys

def inspect_battle(battle_tag, filepath="logs/doubles_decision_audit.jsonl"):
    if not os.path.exists(filepath):
        print(f"Error: Log file not found at {filepath}")
        return

    battle_record = None
    with open(filepath, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                if rec.get("battle_tag") == battle_tag:
                    battle_record = rec
                    break
            except Exception:
                continue

    if not battle_record:
        print(f"Error: Battle tag '{battle_tag}' not found in {filepath}")
        return

    print("=" * 80)
    print(f"  Decision Audit Log Viewer: {battle_tag}")
    print("=" * 80)
    print(f"  Winner      : {battle_record.get('winner')}")
    print(f"  Result      : {'WON' if battle_record.get('won') else 'LOST'}")
    print(f"  Total Turns : {battle_record.get('total_turns')}")
    print("-" * 80)

    pattern_names = {
        1: "missed_ko",
        2: "failed_to_target_low_hp",
        3: "bad_double_target",
        4: "underused_spread",
        5: "bad_protect",
        6: "missed_protect",
        7: "bad_status_move",
        8: "speed_priority_loss",
        9: "switch_mistake",
        10: "damage_estimate_error",
        11: "zero_effectiveness_move_selected",
        12: "all_targets_immune_spread_selected",
        13: "self_drop_move_spam"
    }

    for turn_data in battle_record.get("audit_turns", []):
        turn = turn_data.get("turn")
        our_active = turn_data.get("our_active", [None, None])
        opp_active = turn_data.get("opp_active", [None, None])
        slot_0 = turn_data.get("slot_0", {})
        slot_1 = turn_data.get("slot_1", {})
        opp_actions = turn_data.get("opp_actions", {})

        print(f"\n[Turn {turn}]")
        print(f"  Actives    : P1={our_active[0]} | P2={our_active[1]}")
        print(f"  Opponents  : O1={opp_active[0]} | O2={opp_active[1]}")
        print(f"  Selected   : {turn_data.get('selected_joint_order')} (Score: {turn_data.get('selected_score'):.2f})")
        print(f"  Score Gap  : {turn_data.get('score_gap_selected_best_alt'):.2f}  | Alternatives: {turn_data.get('total_legal_joint_orders')}")

        # Slot decisions
        for idx, (slot_key, name) in enumerate([("slot_0", "P1"), ("slot_1", "P2")]):
            slot = turn_data.get(slot_key, {})
            print(f"    * {name} Action: {slot.get('action')} (Score: {slot.get('selected_score', 0.0):.2f})")
            if "move" in (slot.get("action") or ""):
                print(f"      - Target: {slot.get('target_species')} (HP Before: {slot.get('target_hp_before')})")
                print(f"      - Expected: damage={slot.get('expected_damage')}, ko={slot.get('expected_ko')}")
                if slot.get("outcome_known"):
                    print(f"      - Actual: damage={slot.get('actual_damage')}, ko={slot.get('actual_ko')}, protect_used={slot.get('target_used_protect')}")
            if slot.get("outcome_known"):
                print(f"      - Status: fainted={slot.get('our_mon_fainted')}, fainted_before_moving={slot.get('fainted_before_moving')}, targeted={slot.get('was_targeted')}")

        # Alternatives
        alts = turn_data.get("top_5_alternatives", [])
        scores = turn_data.get("top_5_scores", [])
        if alts:
            print("    * Top 3 Alternatives:")
            for a_idx, (alt, score) in enumerate(zip(alts[:3], scores[:3]), 1):
                print(f"      {a_idx}. {alt} (Score: {score:.2f})")

        # Evaluate loss flags on this turn
        triggered = []
        
        # 1. missed_ko
        for slot in (slot_0, slot_1):
            if slot.get("outcome_known"):
                if slot.get("expected_ko") and not slot.get("actual_ko"):
                    triggered.append(1)
                    break
                if slot.get("opponent_survived_below_20"):
                    triggered.append(1)
                    break

        # 2. failed_to_target_low_hp
        low_hp_opponents = []
        for opp in opp_active:
            if opp and opp.get("hp") is not None and opp["hp"] <= 0.35 and opp["hp"] > 0:
                low_hp_opponents.append(opp["species"])
        if low_hp_opponents:
            targeted_any = False
            for slot in (slot_0, slot_1):
                if slot.get("target_species") in low_hp_opponents:
                    targeted_any = True
            no_ko = (slot_0.get("actual_ko") != True and slot_1.get("actual_ko") != True)
            if not targeted_any and no_ko:
                triggered.append(2)

        # 3. bad_double_target
        if turn_data.get("both_slots_targeted_same_opp"):
            if slot_0.get("expected_ko") or slot_0.get("actual_ko") or slot_1.get("expected_ko") or slot_1.get("actual_ko"):
                if slot_0.get("outcome_known") and slot_1.get("outcome_known"):
                    triggered.append(3)

        # 4. underused_spread
        opps_count = sum(1 for opp in opp_active if opp and opp.get("hp", 0) > 0)
        if opps_count == 2:
            if not slot_0.get("action_types", {}).get("spread") and not slot_1.get("action_types", {}).get("spread"):
                if slot_0.get("spread_available") or slot_1.get("spread_available"):
                    close_0 = (slot_0.get("spread_available") and
                               slot_0.get("best_spread_score") is not None and
                               slot_0.get("selected_score", 0.0) - slot_0.get("best_spread_score", 0.0) <= 30.0)
                    close_1 = (slot_1.get("spread_available") and
                               slot_1.get("best_spread_score") is not None and
                               slot_1.get("selected_score", 0.0) - slot_1.get("best_spread_score", 0.0) <= 30.0)
                    if close_0 or close_1:
                        triggered.append(4)

        # 5. bad_protect
        for idx, (slot, other) in enumerate([(slot_0, slot_1), (slot_1, slot_0)]):
            if slot.get("action_types", {}).get("protect") and slot.get("outcome_known"):
                if not slot.get("was_targeted"):
                    ally_did_good = (other.get("actual_ko") or
                                     (other.get("actual_damage") is not None and other["actual_damage"] >= 0.30))
                    if not ally_did_good:
                        triggered.append(5)
                        break

        # 6. missed_protect
        for idx, slot in enumerate((slot_0, slot_1)):
            mon = our_active[idx]
            if mon and mon.get("hp") is not None and mon["hp"] < 0.35 and mon["hp"] > 0:
                if not slot.get("action_types", {}).get("protect"):
                    if slot.get("outcome_known") and slot.get("our_mon_fainted"):
                        triggered.append(6)
                        break

        # 7. bad_status_move
        for slot in (slot_0, slot_1):
            if slot.get("action_types", {}).get("status"):
                if slot.get("best_ko_score") is not None:
                    triggered.append(7)
                    break

        # 8. speed_priority_loss
        for slot in (slot_0, slot_1):
            if slot.get("outcome_known"):
                if slot.get("fainted_before_moving"):
                    triggered.append(8)
                    break
                elif slot.get("our_mon_fainted") and (opp_actions.get("opponent_moved_before_us") or opp_actions.get("opponent_used_priority")):
                    triggered.append(8)
                    break

        # 9. switch_mistake
        for slot in (slot_0, slot_1):
            if slot.get("action_types", {}).get("switch"):
                if slot.get("best_ko_score") is not None:
                    triggered.append(9)
                    break

        # 10. damage_estimate_error
        for slot in (slot_0, slot_1):
            if slot.get("outcome_known"):
                est = slot.get("expected_damage")
                act = slot.get("actual_damage")
                if est is not None and act is not None:
                    if abs(est - act) > 0.25:
                        triggered.append(10)
                        break

        # 11. zero_effectiveness_move_selected
        for slot in (slot_0, slot_1):
            if slot.get("zero_effectiveness_move_selected"):
                triggered.append(11)
                break

        # 12. all_targets_immune_spread_selected
        for slot in (slot_0, slot_1):
            if slot.get("all_targets_immune_spread_selected"):
                triggered.append(12)
                break

        # 13. self_drop_move_spam
        for slot in (slot_0, slot_1):
            if slot.get("self_drop_move_spam"):
                triggered.append(13)
                break

        if triggered:
            print("    * Triggered Flags: " + ", ".join(pattern_names[p] for p in triggered))

    print("\n" + "=" * 80)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inspect_doubles_audit_battle.py <battle_tag>")
        sys.exit(1)
    inspect_battle(sys.argv[1])
