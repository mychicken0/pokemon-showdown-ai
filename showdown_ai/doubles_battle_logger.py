import json
import os

class DoublesBattleLogger:
    """
    A simple logging utility for Doubles battles to record decisions,
    turn-by-turn states, action scores, and final outcomes.
    """
    def __init__(self, filepath="logs/doubles_battle_results.jsonl", reset=True):
        self.filepath = filepath
        self.turns_log = {} # maps battle_tag -> list of turn dicts
        
        # Ensure log folder exists
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        
        # Reset check: Clear file if reset=True
        if reset and os.path.exists(self.filepath):
            try:
                os.remove(self.filepath)
            except Exception:
                pass

    def log_turn(self, battle_tag, turn, our_actives, opp_actives, selected_order_message,
                 first_order, second_order, first_score, second_score):
        """
        Record decision data for a single doubles turn.
        """
        if battle_tag not in self.turns_log:
            self.turns_log[battle_tag] = []
            
        turn_data = {
            "turn": int(turn),
            "our_active_1": str(our_actives[0].species) if our_actives[0] else None,
            "our_active_2": str(our_actives[1].species) if our_actives[1] else None,
            "opp_active_1": str(opp_actives[0].species) if opp_actives[0] else None,
            "opp_active_2": str(opp_actives[1].species) if opp_actives[1] else None,
            "selected_order_message": str(selected_order_message) if selected_order_message else None,
            "first_order": str(first_order) if first_order else None,
            "second_order": str(second_order) if second_order else None,
            "first_score": float(first_score),
            "second_score": float(second_score),
            "joint_score": float(first_score + second_score)
        }
        
        self.turns_log[battle_tag].append(turn_data)

    def save_battle(self, battle_tag, winner, total_turns):
        """
        Combine turn history with final outcome and write to the JSONL log file.
        """
        turns = self.turns_log.get(battle_tag, [])
        battle_record = {
            "battle_tag": str(battle_tag),
            "winner": str(winner),
            "total_turns": int(total_turns),
            "turns": turns
        }
        with open(self.filepath, "a") as f:
            f.write(json.dumps(battle_record) + "\n")
