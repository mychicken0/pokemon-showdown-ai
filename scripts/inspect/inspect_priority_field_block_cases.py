#!/usr/bin/env python3
import json
import os
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description="Diagnostic Inspector for Double Battle Priority Field Cases")
    parser.add_argument("--psychic-terrain", action="store_true", help="Filter for Psychic Terrain block/events")
    parser.add_argument("--sucker-punch", action="store_true", help="Filter for Sucker Punch priority events")
    parser.add_argument("--ability-block", action="store_true", help="Filter for Armor Tail/Queenly Majesty/Dazzling blocks")
    parser.add_argument("--selected-error", action="store_true", help="Filter for cases where priority was selected and blocked")
    parser.add_argument("--avoided", action="store_true", help="Filter for cases where a blocked priority was avoided")
    parser.add_argument("--only-legal", action="store_true", help="Filter for cases where blocked priority was only legal action")
    parser.add_argument("--grounded", action="store_true", help="Filter for cases where priority target was grounded")
    parser.add_argument("--ungrounded", action="store_true", help="Filter for cases where priority target was ungrounded")
    parser.add_argument("--our-bot", action="store_true", help="Filter for our bot's priority decisions")
    parser.add_argument("--opponent", action="store_true", help="Filter for opponent's priority actions")
    parser.add_argument("--battle", type=str, help="Filter for specific battle tag")
    parser.add_argument("--filepath", type=str, default="logs/doubles_decision_audit.jsonl", help="Path to audit JSONL file")

    args = parser.parse_args()

    if not os.path.exists(args.filepath):
        print(f"Error: Log file not found at {args.filepath}")
        sys.exit(1)

    matched_cases = []

    # If neither our-bot nor opponent is explicitly requested, default to both or our-bot
    our_bot_filter = args.our_bot
    opponent_filter = args.opponent
    if not our_bot_filter and not opponent_filter:
        our_bot_filter = True
        opponent_filter = True

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

                # Match our bot
                if our_bot_filter:
                    for idx, slot_key in enumerate(("slot_0", "slot_1")):
                        slot = turn_data.get(slot_key, {})
                        if not slot:
                            continue

                        # Check if any priority event is active in this slot
                        has_p_event = slot.get("priority_move_field_blocked") or slot.get("priority_move_block_avoided")
                        if not has_p_event:
                            continue

                        match = True

                        if args.psychic_terrain:
                            if "psychic_terrain" not in slot.get("priority_move_block_reason", "") and not slot.get("priority_move_selected_into_psychic_terrain"):
                                match = False
                        if args.sucker_punch:
                            action = slot.get("action", "") or ""
                            if "suckerpunch" not in action.lower():
                                match = False
                        if args.ability_block:
                            if not slot.get("priority_blocking_ability"):
                                match = False
                        if args.selected_error:
                            if not slot.get("priority_move_field_blocked"):
                                match = False
                        if args.avoided:
                            if not slot.get("priority_move_block_avoided"):
                                match = False
                        if args.only_legal:
                            if not slot.get("priority_move_only_legal"):
                                match = False
                        if args.grounded:
                            if not slot.get("priority_target_grounded"):
                                match = False
                        if args.ungrounded:
                            if slot.get("priority_target_grounded"):
                                match = False

                        if match:
                            attacker = our_active[idx].get("species") if (len(our_active) > idx and our_active[idx]) else "Unknown"
                            matched_cases.append({
                                "source": "our_bot",
                                "slot": slot_key,
                                "battle_tag": battle_tag,
                                "turn": turn,
                                "won": is_win,
                                "attacker": attacker,
                                "move": slot.get("action", ""),
                                "target": slot.get("priority_target_species", ""),
                                "grounded": slot.get("priority_target_grounded", False),
                                "blocked": slot.get("priority_move_field_blocked", False),
                                "avoided": slot.get("priority_move_block_avoided", False),
                                "reason": slot.get("priority_move_block_reason", ""),
                                "blocking_ability": slot.get("priority_blocking_ability", ""),
                                "blocking_source": slot.get("priority_blocking_ability_source", ""),
                                "only_legal": slot.get("priority_move_only_legal", False),
                                "selected_score": slot.get("selected_score", 0.0)
                            })

                # Match opponent
                if opponent_filter:
                    opp_actions = turn_data.get("opp_actions", {})
                    if opp_actions and opp_actions.get("opponent_used_priority"):
                        match = True
                        if args.psychic_terrain:
                            # Psychic Terrain check for opponent
                            # We can check if psychic terrain is active on turn
                            # Standard check: if reason has psychic terrain in slot_0 or slot_1
                            terrain_active = False
                            for slot_key in ("slot_0", "slot_1"):
                                slot = turn_data.get(slot_key, {})
                                if slot and ("psychic_terrain" in slot.get("priority_move_block_reason", "") or slot.get("priority_move_selected_into_psychic_terrain")):
                                    terrain_active = True
                            if not terrain_active:
                                match = False
                        
                        if args.ability_block:
                            # Check if blocking ability in slot_0 or slot_1
                            ability_active = False
                            for slot_key in ("slot_0", "slot_1"):
                                slot = turn_data.get(slot_key, {})
                                if slot and slot.get("priority_blocking_ability"):
                                    ability_active = True
                            if not ability_active:
                                match = False

                        if match:
                            matched_cases.append({
                                "source": "opponent",
                                "slot": "N/A",
                                "battle_tag": battle_tag,
                                "turn": turn,
                                "won": is_win,
                                "attacker": "Opponent Active",
                                "move": "Opponent Priority Move",
                                "target": "Our Active Slot",
                                "grounded": True,
                                "blocked": True,
                                "avoided": False,
                                "reason": "opponent_priority_use",
                                "blocking_ability": "",
                                "blocking_source": "",
                                "only_legal": False,
                                "selected_score": 0.0
                            })

    if not matched_cases:
        print("No cases matching the filters were found.")
        return

    print(f"Found {len(matched_cases)} matched priority field safety cases:\n")
    for idx, case in enumerate(matched_cases, 1):
        outcome = "WIN" if case["won"] else "LOSS"
        role = "OUR_BOT" if case["source"] == "our_bot" else "OPPONENT"
        status = "BLOCKED" if case["blocked"] else "AVOIDED"
        if case["only_legal"]:
            status += " (ONLY_LEGAL)"
        print(f"Case #{idx}: [{role}] [{status}] (Battle Outcome: {outcome})")
        print(f"  Battle Tag         : {case['battle_tag']}")
        print(f"  Turn               : {case['turn']}")
        print(f"  Attacker           : {case['attacker']}")
        print(f"  Selected Move      : {case['move']}")
        print(f"  Target Species     : {case['target']} (Grounded: {case['grounded']})")
        print(f"  Block Reason       : {case['reason']}")
        if case['blocking_ability']:
            print(f"  Blocking Ability   : {case['blocking_ability']} (Source: {case['blocking_source']})")
        print(f"  Selected Score     : {case['selected_score']:.2f}")
        print("-" * 60)

if __name__ == "__main__":
    main()
