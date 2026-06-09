import json
import os

def analyze(filepath="logs/battle_results.jsonl"):
    """
    Parses logs/battle_results.jsonl and calculates performance metrics 
    and checks for possible losing patterns.
    """
    if not os.path.exists(filepath):
        print(f"Log file not found at: {filepath}")
        return

    total_battles = 0
    wins = 0
    losses = 0
    total_turns = 0
    shortest_battle = float('inf')
    longest_battle = 0
    lost_battle_ids = []
    
    # 5. Losing patterns counters using "possible" naming convention
    low_hp_loss_count = 0
    possible_bad_status_move_count = 0
    possible_low_score_endgame_move_count = 0
    possible_failed_ko_count = 0

    with open(filepath, "r") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            total_battles += 1
            turns = data.get("turns", [])
            won = data.get("won", False)
            battle_tag = data.get("battle_tag", "Unknown")
            battle_length = data.get("total_turns", len(turns))
            
            total_turns += battle_length
            if battle_length < shortest_battle:
                shortest_battle = battle_length
            if battle_length > longest_battle:
                longest_battle = battle_length
                
            if won:
                wins += 1
            else:
                losses += 1
                lost_battle_ids.append(battle_tag)
                
                # Analyze patterns on lost battles
                if turns:
                    final_turn = turns[-1]
                    active_hp = final_turn.get("active_hp", 0)
                    active_max_hp = final_turn.get("active_max_hp", 100) or 100
                    
                    # Pattern 1: Lost with active HP low (HP fraction < 25%)
                    if (active_hp / active_max_hp) < 0.25:
                        low_hp_loss_count += 1
                        
                    # Extract the final 3 turns of the battle for endgame pattern analysis
                    final_turns = turns[-3:]
                    
                    # Pattern 2: possible_bad_status_move (selected setup/status move in final 3 turns)
                    status_setup_moves = {
                        "swordsdance", "nastyplot", "calmmind", "dragondance", "quiverdance",
                        "recover", "roost", "slackoff", "synthesis", "thunderwave", "willowisp",
                        "toxic", "stealthrock"
                    }
                    selected_status_in_endgame = False
                    for t in final_turns:
                        action = t.get("selected_action", "")
                        if action in status_setup_moves:
                            selected_status_in_endgame = True
                            break
                    if selected_status_in_endgame:
                        possible_bad_status_move_count += 1
                        
                    # Pattern 3: possible_low_score_endgame_move (selected move score < 50.0 in final 3 turns)
                    selected_low_score_move = False
                    for t in final_turns:
                        action = t.get("selected_action", "")
                        score = t.get("selected_score", 0.0)
                        # Check moves only (exclude switches or fallbacks)
                        if not action.startswith("switch") and not action.startswith("fallback") and score < 50.0:
                            selected_low_score_move = True
                            break
                    if selected_low_score_move:
                        possible_low_score_endgame_move_count += 1
                        
                    # Pattern 4: possible_failed_ko (failed to KO when opponent was low in final 3 turns)
                    failed_ko = False
                    for t in final_turns:
                        opp_hp = t.get("opponent_hp", 0)
                        opp_max = t.get("opponent_max_hp", 100) or 100
                        opp_hp_fraction = opp_hp / opp_max
                        
                        # Opponent HP was low (< 20%) but they survived because we switched or used status/setup
                        if 0.0 < opp_hp_fraction < 0.20:
                            action = t.get("selected_action", "")
                            if action in status_setup_moves or action.startswith("switch"):
                                failed_ko = True
                                break
                    if failed_ko:
                        possible_failed_ko_count += 1

    win_rate = (wins / total_battles) * 100 if total_battles > 0 else 0
    avg_length = (total_turns / total_battles) if total_battles > 0 else 0
    
    # 7. Print statistics calculated purely from JSONL logs
    print("\n================ Battle Log Analysis ================")
    print(f"Total battles analyzed: {total_battles}")
    print(f"Wins: {wins} | Losses: {losses}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Average Battle Length: {avg_length:.2f} turns")
    print(f"Shortest Battle: {shortest_battle if shortest_battle != float('inf') else 0} turns")
    print(f"Longest Battle: {longest_battle} turns")
    
    # 3. Print 10 lost battle IDs
    print("\nLost Battle IDs (first 10):")
    for b_id in lost_battle_ids[:10]:
        print(f"  - {b_id}")
        
    # 5. Print possible losing patterns with correct names
    print("\nPossible Common Losing Patterns:")
    print(f"  - possible_low_hp_loss (active HP low in final turn): {low_hp_loss_count} battles")
    print(f"  - possible_bad_status_move (status move selected in final 3 turns): {possible_bad_status_move_count} battles")
    print(f"  - possible_low_score_endgame_move (selected move score < 50.0 at the end): {possible_low_score_endgame_move_count} battles")
    print(f"  - possible_failed_ko (failed to KO low-HP opponent in final 3 turns): {possible_failed_ko_count} battles")
    print("=====================================================")

if __name__ == "__main__":
    analyze()
