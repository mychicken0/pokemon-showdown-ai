import json
import os

class BattleLogger:
    """
    A class to collect and write turn-by-turn decisions and final results
    of battles into a JSONL log file.
    
    NOTE: This logger only records the decisions made by the DamageAwarePlayer
    bot itself, not the exact turn events or actions of both players.
    """
    def __init__(self, filepath="logs/battle_results.jsonl", reset=True):
        self.filepath = filepath
        self.turns_log = {} # maps battle_tag -> list of turn dicts
        
        # Ensure log folder exists
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        
        # 1. Reset check: Clear file if reset=True
        if reset and os.path.exists(self.filepath):
            try:
                os.remove(self.filepath)
            except Exception:
                pass

    def to_safe_str(self, obj):
        """Helper to safely convert poke-env enums/objects to JSON-safe strings."""
        if obj is None:
            return None
        return getattr(obj, "name", str(obj))

    def log_turn(self, battle_tag, turn, active_pkmn, active_hp, active_max_hp, 
                 active_types, active_status, opp_pkmn, opp_hp, opp_max_hp, 
                 opp_types, opp_status, available_moves, selected_action, selected_score,
                 selected_action_type=None, switch_score=None, stay_score=None, switch_trigger_reasons=None,
                 active_hp_fraction=None, opponent_hp_fraction=None, available_move_count=None,
                 is_forced_switch=None, best_move_score=None, best_move_id=None):
        """
        Record decision data for a single turn. 
        Converts all poke-env enums and lists into JSON-safe basic types.
        """
        if battle_tag not in self.turns_log:
            self.turns_log[battle_tag] = []
            
        # 2. JSON-safe conversion for enums and list structures
        active_types_clean = [self.to_safe_str(t) for t in active_types] if active_types else []
        opp_types_clean = [self.to_safe_str(t) for t in opp_types] if opp_types else []
        
        active_status_clean = self.to_safe_str(active_status)
        opp_status_clean = self.to_safe_str(opp_status)
        
        # Calculate dynamic fields if not explicitly passed
        act_hp = float(active_hp)
        act_max = float(active_max_hp) if active_max_hp else 100.0
        if active_hp_fraction is None:
            active_hp_fraction = act_hp / act_max if act_max > 0 else 0.0
            
        o_hp = float(opp_hp)
        o_max = float(opp_max_hp) if opp_max_hp else 100.0
        if opponent_hp_fraction is None:
            opponent_hp_fraction = o_hp / o_max if o_max > 0 else 0.0
            
        if available_move_count is None:
            available_move_count = len(available_moves) if available_moves else 0
            
        if is_forced_switch is None:
            is_forced_switch = (
                available_move_count == 0 and 
                (act_hp <= 0.0 or active_hp_fraction <= 0.0) and 
                str(selected_action).startswith("switch")
            )
            
        if best_move_id is None and available_moves:
            try:
                best_move_id = max(available_moves, key=available_moves.get)
            except Exception:
                best_move_id = None
                
        if best_move_score is None and best_move_id is not None:
            try:
                best_move_score = float(available_moves[best_move_id])
            except Exception:
                best_move_score = 0.0
                
        if selected_action_type is None:
            selected_action_type = "switch" if str(selected_action).startswith("switch") else "move"
            
        turn_data = {
            "turn": int(turn),
            "active_pokemon": str(active_pkmn),
            "active_hp": int(active_hp),
            "active_max_hp": int(active_max_hp),
            "active_types": active_types_clean,
            "active_status": active_status_clean,
            "opponent_pokemon": str(opp_pkmn),
            "opponent_hp": int(opp_hp),
            "opponent_max_hp": int(opp_max_hp),
            "opponent_types": opp_types_clean,
            "opponent_status": opp_status_clean,
            "available_moves": available_moves,  # dict of move_id (str) -> score (float)
            "selected_action": str(selected_action),
            "selected_score": float(selected_score),
            "active_hp_fraction": float(active_hp_fraction),
            "opponent_hp_fraction": float(opponent_hp_fraction),
            "available_move_count": int(available_move_count),
            "is_forced_switch": bool(is_forced_switch),
            "selected_action_type": str(selected_action_type)
        }
        
        if best_move_score is not None:
            turn_data["best_move_score"] = float(best_move_score)
        if best_move_id is not None:
            turn_data["best_move_id"] = str(best_move_id)
        if switch_score is not None:
            turn_data["switch_score"] = float(switch_score)
        if stay_score is not None:
            turn_data["stay_score"] = float(stay_score)
        if switch_trigger_reasons is not None:
            turn_data["switch_trigger_reasons"] = list(switch_trigger_reasons)
            
        self.turns_log[battle_tag].append(turn_data)

    def save_battle(self, battle_tag, winner, won, total_turns):
        """
        Combine turn history with final outcome and write to the JSONL log file.
        """
        turns = self.turns_log.get(battle_tag, [])
        battle_record = {
            "battle_tag": str(battle_tag),
            "winner": self.to_safe_str(winner),
            "won": bool(won),
            "total_turns": int(total_turns),
            "turns": turns
        }
        with open(self.filepath, "a") as f:
            f.write(json.dumps(battle_record) + "\n")
