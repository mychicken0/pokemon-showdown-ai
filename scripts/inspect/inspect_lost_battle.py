import json
import sys
import os

def list_lost_battles(filepath="logs/battle_results.jsonl"):
    """Lists all battle tags for matches where our bot lost."""
    if not os.path.exists(filepath):
        print(f"Log file not found at: {filepath}")
        return
    
    print("Lost Battle IDs found in logs:")
    count = 0
    with open(filepath, "r") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            if not data.get("won", False):
                print(f"  - {data.get('battle_tag')}")
                count += 1
    if count == 0:
        print("No lost battles found in logs.")

def is_forced_switch(turn_record):
    """
    Returns True when:
    - available_moves is empty
    - selected_action_type == "switch" (or selected_action starts with "switch")
    - active HP is 0 or active_hp_fraction <= 0
    """
    if turn_record.get("is_forced_switch") is True:
        return True
        
    available_moves = turn_record.get("available_moves", {})
    selected_action_type = turn_record.get("selected_action_type")
    selected_action = turn_record.get("selected_action", "")
    
    if selected_action_type is None:
        selected_action_type = "switch" if str(selected_action).startswith("switch") else "move"
        
    active_hp = turn_record.get("active_hp", 100)
    active_hp_frac = turn_record.get("active_hp_fraction")
    if active_hp_frac is None:
        active_max = turn_record.get("active_max_hp", 100) or 100
        active_hp_frac = active_hp / active_max if active_max > 0 else 1.0
        
    is_avail_empty = not available_moves or len(available_moves) == 0
    is_fainted = (active_hp <= 0 or active_hp_frac <= 0.0)
    is_switch = (selected_action_type == "switch" or str(selected_action).startswith("switch"))
    
    return is_avail_empty and is_switch and is_fainted

def inspect_battle(battle_tag, filepath="logs/battle_results.jsonl"):
    """Prints a detailed, highlighted timeline of the specified battle."""
    if not os.path.exists(filepath):
        print(f"Log file not found at: {filepath}")
        return
        
    battle_record = None
    with open(filepath, "r") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            if data.get("battle_tag") == battle_tag:
                battle_record = data
                break
                
    if not battle_record:
        print(f"Battle ID '{battle_tag}' not found in logs.")
        return
        
    print(f"\n================ Inspecting Battle: {battle_tag} ================")
    print(f"Winner: {battle_record.get('winner')}")
    print(f"Won: {battle_record.get('won')}")
    print(f"Total Turns: {battle_record.get('total_turns')}")
    print("=================================================================\n")
    
    turns = battle_record.get("turns", [])
    total_turns = len(turns)
    
    status_setup_moves = {
        "swordsdance", "nastyplot", "calmmind", "dragondance", "quiverdance",
        "recover", "roost", "slackoff", "synthesis", "thunderwave", "willowisp",
        "toxic", "stealthrock"
    }

    for idx, t in enumerate(turns):
        turn_num = t.get("turn")
        active = t.get("active_pokemon")
        active_hp = t.get("active_hp")
        active_max = t.get("active_max_hp", 100) or 100
        active_hp_pct = (active_hp / active_max) * 100
        
        opp = t.get("opponent_pokemon")
        opp_hp = t.get("opponent_hp")
        opp_max = t.get("opponent_max_hp", 100) or 100
        opp_hp_pct = (opp_hp / opp_max) * 100
        
        selected = t.get("selected_action")
        score = t.get("selected_score")
        moves = t.get("available_moves", {})
        
        action_type = t.get("selected_action_type")
        stay_sc = t.get("stay_score")
        switch_sc = t.get("switch_score")
        triggers = t.get("switch_trigger_reasons")
        
        # Highlight final 5 turns
        is_final_turns = (total_turns - idx) <= 5
        highlight_prefix = ">>> " if is_final_turns else "    "
        
        print(f"{highlight_prefix}Turn {turn_num}: {active} ({active_hp}/{active_max} HP) vs {opp} ({opp_hp}/{opp_max} HP)")
        
        # Format available moves
        moves_str = ", ".join([f"{m}: {sc:.1f}" for m, sc in moves.items()])
        print(f"{highlight_prefix}  Available: {moves_str}")
        print(f"{highlight_prefix}  Selected:  {selected} (Score: {score:.2f})")
        
        if action_type:
            action_info = f"Action Type: {action_type}"
            if stay_sc is not None:
                action_info += f" | Stay Score: {stay_sc:.2f}"
            if switch_sc is not None:
                action_info += f" | Switch Score: {switch_sc:.2f}"
            print(f"{highlight_prefix}  {action_info}")
        if triggers:
            print(f"{highlight_prefix}  Switch Triggers: {', '.join(triggers)}")
            
        # Check suspicious decisions and info messages
        warnings = []
        infos = []
        
        forced = is_forced_switch(t)
        
        if forced:
            infos.append("[INFO] [forced_switch_no_warning] Forced switch due to fainted Pokemon.")
        else:
            # 1. active HP < 25% and no switch
            if active_hp_pct < 25.0 and not selected.startswith("switch"):
                # Do not warn if:
                # - selected_action_type == "move"
                # - selected_score >= 180
                # - opponent HP is low enough that attacking may be correct (< 30.0%)
                is_attack_move = (action_type == "move" or not selected.startswith("switch"))
                if is_attack_move and score >= 180.0 and opp_hp_pct < 30.0:
                    infos.append("[INFO] [possible_correct_low_hp_attack] Low HP but selected high-score attack; may be correct.")
                else:
                    warnings.append("[WARNING] [possible_bad_no_switch] active HP < 25% and no switch")
                    
            # 2. selected score < 50
            if not selected.startswith("switch") and not selected.startswith("fallback") and score < 50.0:
                warnings.append(f"[WARNING] selected score < 50 (Score: {score:.2f})")
                
            # 3. status move at low HP
            if selected in status_setup_moves and active_hp_pct < 30.0:
                warnings.append(f"[WARNING] status move at low HP ({active_hp_pct:.1f}%)")
                
            # 4. opponent HP < 20% and no KO-like move selected
            if 0.0 < opp_hp_pct < 20.0 and (selected in status_setup_moves or selected.startswith("switch")):
                # Do not warn "opponent HP < 20% but no KO-like move selected" if:
                # - available_moves is empty
                # - active HP is 0
                # - selected_action_type == "switch"
                is_forced_ko_situation = (not moves and active_hp <= 0 and (action_type == "switch" or selected.startswith("switch")))
                if not is_forced_ko_situation:
                    warnings.append(f"[WARNING] [possible_failed_ko] opponent HP < 20% and no KO-like move selected (Selected: {selected})")
            
        for info in infos:
            print(f"{highlight_prefix}  {info}")
        for w in warnings:
            print(f"{highlight_prefix}  {w}")
        print()
        
if __name__ == "__main__":
    if len(sys.argv) < 2:
        list_lost_battles()
        print("\nTo inspect a battle, run: python3 inspect_lost_battle.py <battle_tag>")
    else:
        inspect_battle(sys.argv[1])
