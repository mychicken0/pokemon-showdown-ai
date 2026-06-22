#!/usr/bin/env python3
"""
bot_doubles_safe_random.py

Phase 5.3: DoublesSafeRandomPlayer

A random-ish Doubles player that avoids obviously terrible choices.
Specifically designed to avoid RandomPlayer's flaw of targeting its own ally
with damaging moves (confirmed: RandomPlayer can use Shadow Ball into own ally).

Rules:
- Randomly select among legal joint orders.
- Reject any single order that uses a damaging move against own ally unless
  the ally is immune (type effectiveness == 0) or absorbs the move.
- Reject damaging self-target moves (unless the move is normally self-targeting).
- For status/support moves targeting an ally: allow.
- Allow all switch orders.
- If all joint orders are filtered out, fall back to choose_random_doubles_move.

This player is intentionally NOT strategic. It is only meant to be used as a
safer baseline than RandomPlayer for sanity-check benchmarks.

IMPORTANT: This player should NOT be used as a primary adoption benchmark.
Use DoublesBasicAwarePlayer for that.
"""
import random
from typing import Optional

from poke_env import AccountConfiguration
from poke_env.battle.abstract_battle import AbstractBattle
from poke_env.battle.double_battle import DoubleBattle
from poke_env.battle.move import Move
from poke_env.battle.pokemon import Pokemon
from poke_env.player import Player
from poke_env.player.battle_order import (
    BattleOrder,
    DefaultBattleOrder,
    DoubleBattleOrder,
    PassBattleOrder,
    SingleBattleOrder,
)


class DoublesSafeRandomPlayer(Player):
    """
    A safer random Doubles player.

    Unlike poke-env's RandomPlayer, this player filters out damaging moves
    aimed at its own ally (unless the ally is immune or benefits from the move).

    Purpose: sanity-check benchmark only — not a strategic player.
    Do not use this as the primary benchmark for adoption decisions.
    """

    def __init__(self, *args, verbose: bool = False, **kwargs):
        if "battle_format" not in kwargs:
            kwargs["battle_format"] = "gen9randomdoublesbattle"
        super().__init__(*args, **kwargs)
        self.verbose = verbose

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_type_effectiveness(self, move: Move, target: Optional[Pokemon]) -> float:
        if not target:
            return 1.0
        try:
            return target.damage_multiplier(move)
        except Exception:
            try:
                mtype = getattr(move, "type", None)
                if mtype:
                    return target.damage_multiplier(mtype)
            except Exception:
                pass
        return 1.0

    def _is_damaging(self, move: Move) -> bool:
        bp = getattr(move, "base_power", 0)
        category = getattr(move, "category", None)
        cat_name = getattr(category, "name", "STATUS")
        return bp > 0 and cat_name != "STATUS"

    def _is_self_target_move(self, move: Move) -> bool:
        """Return True for moves whose mechanic is targeting self (e.g. Belly Drum)."""
        target_str = str(getattr(move, "target", "")).lower()
        return "self" in target_str

    def _order_is_safe(self, order: SingleBattleOrder, active_idx: int, battle: DoubleBattle) -> bool:
        """
        Return True if this order is safe to execute.
        Filters out damaging moves aimed at own ally.
        """
        if isinstance(order, (PassBattleOrder, DefaultBattleOrder)):
            return True
        if isinstance(order.order, Pokemon):
            # Switch is always allowed
            return True
        if not isinstance(order.order, Move):
            return True

        move = order.order
        target_pos = order.move_target

        # Ally positions are -1 (slot 0 target) and -2 (slot 1 target)
        # target_pos == -1 means targeting slot 0 ally
        # target_pos == -2 means targeting slot 1 ally
        ally_positions = (-1, -2)
        if target_pos not in ally_positions:
            # Not targeting an ally — always safe
            return True

        # Determine the actual ally Pokémon
        if target_pos == -1:
            ally = battle.active_pokemon[0]
        else:
            ally = battle.active_pokemon[1]

        # If targeting self, check if it makes sense
        if ally and ally is battle.active_pokemon[active_idx]:
            # Self-target move mechanics: only allow if the move is meant for self
            if self._is_damaging(move) and not self._is_self_target_move(move):
                return False

        if not ally:
            return True

        if not self._is_damaging(move):
            # Status/support moves onto ally are OK
            return True

        # Damaging move into ally — check immunity
        eff = self._get_type_effectiveness(move, ally)
        if eff == 0.0:
            # Ally is immune — allowed (e.g. Fire move into Flash Fire ally)
            return True

        # Ally will take damage — reject this order
        if self.verbose:
            print(f"[SafeRandom] Filtering: slot {active_idx} using {move.id} vs own ally {ally.species} (eff={eff})")
        return False

    # ------------------------------------------------------------------
    # choose_move
    # ------------------------------------------------------------------

    def choose_move(self, battle: AbstractBattle) -> BattleOrder:
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)

        valid_orders = battle.valid_orders
        if not valid_orders or (not valid_orders[0] and not valid_orders[1]):
            return self.choose_random_doubles_move(battle)

        # Filter each slot's orders
        safe_orders_0 = [
            o for o in (valid_orders[0] or [])
            if self._order_is_safe(o, 0, battle)
        ]
        safe_orders_1 = [
            o for o in (valid_orders[1] or [])
            if self._order_is_safe(o, 1, battle)
        ]

        # Fall back to all valid orders if filtering left nothing
        if not safe_orders_0 and valid_orders[0]:
            safe_orders_0 = valid_orders[0]
        if not safe_orders_1 and valid_orders[1]:
            safe_orders_1 = valid_orders[1]

        # Build joint orders from filtered slots
        joint_orders = DoubleBattleOrder.join_orders(safe_orders_0, safe_orders_1)
        if not joint_orders:
            return self.choose_random_doubles_move(battle)

        return random.choice(joint_orders)
