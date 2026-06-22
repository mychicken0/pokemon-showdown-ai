"""Custom opp player that uses Trick Room aggressively.

This is a TEST OPPONENT, not the main bot. It always tries to set up
Trick Room turn 1 if available, then uses max damage moves. Used only
for testing anti-TR features.
"""
from poke_env.battle.abstract_battle import AbstractBattle
from poke_env.player.battle_order import (
    BattleOrder, DoubleBattleOrder, SingleBattleOrder,
    PassBattleOrder, DefaultBattleOrder,
)
from poke_env.battle.move import Move
from poke_env.battle.pokemon import Pokemon
from poke_env.battle.double_battle import DoubleBattle
from bot_doubles_basic_aware import DoublesBasicAwarePlayer


class DoublesTRUserPlayer(DoublesBasicAwarePlayer):
    """Custom opp that prioritizes Trick Room.
    
    Strategy:
    - Turn 1 (if not on Trick Room): use TR if available
    - Otherwise: use strongest damaging move (basic AI behavior)
    """
    
    SETUP_MOVES = {
        "trickroom", "tailwind", "trick_room",
    }
    
    def choose_move(self, battle: AbstractBattle) -> BattleOrder:
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)
        
        # If TR is not yet set, try to set it up
        tr_active = False
        for f in getattr(battle, "fields", []):
            f_str = str(f).lower() if not hasattr(f, "name") else f.name.lower()
            if "trick" in f_str and "room" in f_str:
                tr_active = True
                break
        
        if not tr_active:
            # Try to find TR in either slot
            tr_orders = []
            other_orders = []
            for slot_idx in (0, 1):
                valid_orders = battle.valid_orders[slot_idx] if slot_idx < len(battle.valid_orders) else []
                for order in valid_orders:
                    if hasattr(order, "order") and isinstance(order.order, Move):
                        move_id = str(getattr(order.order, "id", "")).lower().replace(" ", "").replace("-", "").replace("_", "")
                        if move_id in ("trickroom", "trick_room"):
                            tr_orders.append((slot_idx, order))
                        else:
                            other_orders.append((slot_idx, order))
            
            if tr_orders and other_orders:
                # Pick the first TR order
                slot_idx, tr_order = tr_orders[0]
                # Use the other mon's best move
                other_slot = 1 - slot_idx
                other_valid = battle.valid_orders[other_slot] if other_slot < len(battle.valid_orders) else []
                if other_valid:
                    best_other = self._best_order(other_valid, other_slot, battle)
                    return DoubleBattleOrder(tr_order, best_other)
                else:
                    return tr_order
        
        # Fall back to basic AI behavior
        return super().choose_move(battle)
    
    def _best_order(self, valid_orders, slot_idx, battle):
        """Pick the best scoring order from a list."""
        scored = [(o, self.score_action(o, slot_idx, battle)) for o in valid_orders]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0] if scored else self.choose_random_doubles_move(battle)
