#!/usr/bin/env python3
import random
from typing import Dict, List, Optional, Union
from poke_env.player import Player
from poke_env import AccountConfiguration
from poke_env.battle.abstract_battle import AbstractBattle
from poke_env.battle.double_battle import DoubleBattle
from poke_env.battle.pokemon import Pokemon
from poke_env.battle.move import Move
from poke_env.player.battle_order import (
    BattleOrder,
    DoubleBattleOrder,
    SingleBattleOrder,
    PassBattleOrder,
    DefaultBattleOrder
)

class DoublesBasicAwarePlayer(Player):
    """
    A baseline Doubles player that evaluates joint DoubleBattleOrder options
    but only scores damaging moves using BP * STAB * type_effectiveness * accuracy.
    It avoids targeting allies but lacks advanced priority, KO, or spread/protect logic.
    """
    def __init__(self, *args, verbose=False, **kwargs):
        if "battle_format" not in kwargs:
            kwargs["battle_format"] = "gen9randomdoublesbattle"
        super().__init__(*args, **kwargs)
        self.verbose = verbose

    def get_accuracy(self, move: Move) -> float:
        try:
            acc = getattr(move, "accuracy", 1.0)
            if acc is True or acc is None:
                return 1.0
            if isinstance(acc, (int, float)):
                if acc == 100:
                    return 1.0
                if acc > 1.0:
                    return acc / 100.0
                return acc
            return 1.0
        except Exception:
            return 1.0

    def get_type_effectiveness(self, move: Move, opponent: Optional[Pokemon]) -> float:
        if not opponent:
            return 1.0
        try:
            return opponent.damage_multiplier(move)
        except Exception:
            try:
                move_type = getattr(move, "type", None)
                if move_type:
                    return opponent.damage_multiplier(move_type)
            except Exception:
                pass
        return 1.0

    def score_action(self, order: SingleBattleOrder, active_idx: int, battle: DoubleBattle) -> float:
        active_mon = battle.active_pokemon[active_idx]
        if not active_mon:
            return 0.0

        if isinstance(order, PassBattleOrder) or getattr(order, "order", None) == "/choose pass":
            return 0.0
        
        if isinstance(order, DefaultBattleOrder) or getattr(order, "order", None) == "/choose default":
            return 1.0

        # Switch orders
        if isinstance(order.order, Pokemon):
            # Baseline score of 20 for switching
            return 20.0

        # Move orders
        if isinstance(order.order, Move):
            move = order.order
            target_pos = order.move_target
            
            target_mon = None
            if target_pos == 1:
                target_mon = battle.opponent_active_pokemon[0]
            elif target_pos == 2:
                target_mon = battle.opponent_active_pokemon[1]
            elif target_pos == -1:
                target_mon = battle.active_pokemon[0]
            elif target_pos == -2:
                target_mon = battle.active_pokemon[1]

            base_power = getattr(move, "base_power", 0)
            category = getattr(move, "category", None)
            category_name = getattr(category, "name", "STATUS")

            # Status Moves
            if category_name == "STATUS" or base_power == 0:
                return 10.0

            # Damaging Moves
            active_types = getattr(active_mon, "types", [])
            move_type = getattr(move, "type", None)
            stab_multiplier = 1.5 if (move_type and move_type in active_types) else 1.0

            # Type effectiveness multiplier
            if target_mon:
                type_multiplier = self.get_type_effectiveness(move, target_mon)
            elif target_pos == 0:
                opps = [opp for opp in battle.opponent_active_pokemon if opp]
                if opps:
                    type_multiplier = sum(self.get_type_effectiveness(move, opp) for opp in opps) / len(opps)
                else:
                    type_multiplier = 1.0
            else:
                type_multiplier = 1.0

            if type_multiplier == 0.0:
                return 0.0

            accuracy_multiplier = self.get_accuracy(move)
            
            # Basic Score formula
            score = float(base_power) * stab_multiplier * type_multiplier * accuracy_multiplier

            # Avoid ally targeting
            if target_pos in (-1, -2):
                return 0.0

            return max(score, 0.0)

        return 0.0

    def choose_move(self, battle: AbstractBattle) -> BattleOrder:
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)

        valid_orders = battle.valid_orders
        if not valid_orders or (not valid_orders[0] and not valid_orders[1]):
            return self.choose_random_doubles_move(battle)

        joint_orders = DoubleBattleOrder.join_orders(valid_orders[0], valid_orders[1])
        if not joint_orders:
            return self.choose_random_doubles_move(battle)

        scored_joint_orders = []
        for joint_order in joint_orders:
            first = joint_order.first_order
            second = joint_order.second_order
            
            score_1 = self.score_action(first, 0, battle)
            score_2 = self.score_action(second, 1, battle)
            joint_score = score_1 + score_2

            scored_joint_orders.append((joint_order, joint_score))

        scored_joint_orders.sort(key=lambda x: x[1], reverse=True)
        return scored_joint_orders[0][0]
