"""PLANNER-ANTI-TR investigation fixture test.

Documents the eligible check behavior at the exact battle state from
trial 2 t4 and t5 of the v4 smoke. This is a regression guard.

The investigation showed:
- At t4 (Hatterene 1.0 HP), Taunt+SaltCure scored 607.1 (rank 2)
- At t5 (Hatterene 0.59 HP), Taunt+SaltCure scored below top 5
  because the bot preferred KO pressure on the low-HP TR setter

The +500 bonus is tuned correctly: Taunt is competitive when KO
isn't feasible, but the bot still makes smart KO plays.
"""
import unittest

from poke_env.battle.move import Move

import bot_doubles_damage_aware as mod
from bot_doubles_damage_aware import DoublesDamageAwareConfig
from bot_doubles_intent_classifier import IntentDecision


class MockPokemon:
    def __init__(self, hp):
        self.current_hp_fraction = hp


class MockOrder:
    def __init__(self, move, target):
        self.order = move
        self.move_target = target


class MockBattle:
    def __init__(self, hp_frac, turn=5):
        self.active_pokemon = [None, None]
        if hp_frac is not None:
            self.active_pokemon[0] = MockPokemon(hp_frac)
        self.battle_tag = "test_battle"
        self.turn = turn
        self._planner_intent_decision = IntentDecision(
            intent="ANTI_TRICK_ROOM",
            confidence=1.0,
            evidence_source="revealed_moves",
            matched_moves=("trickroom",),
            routed_to_policy="anti_setup",
            opp_pressure=False,
        )


class TestAntiTrickRoomEligibleInvestigation(unittest.TestCase):
    """Regression guard for the trial 2 t4/t5 investigation."""

    def setUp(self):
        config = DoublesDamageAwareConfig()
        config.enable_anti_trick_room_response = True
        config.anti_trick_room_response_bonus = 500.0
        config.anti_trick_room_ko_bonus = 200.0

        self.player = mod.DoublesDamageAwarePlayer.__new__(
            mod.DoublesDamageAwarePlayer
        )
        self.player.config = config
        self.player._anti_trick_room_response_picks_per_game = {}
        self.player._anti_trick_room_response_last_pick_turn = {}
        self.player._anti_trick_room_ko_picks_per_game = {}
        self.player._anti_trick_room_ko_last_pick_turn = {}

        self.taunt = Move("taunt", gen=9)
        self.encore = Move("encore", gen=9)
        self.disable = Move("disable", gen=9)
        self.flareblitz = Move("flareblitz", gen=9)

    def test_taunt_eligible_at_hp_0_67(self):
        """At t5, Incineroar HP=0.67, Taunt should be eligible."""
        battle = MockBattle(hp_frac=0.67, turn=5)
        order = MockOrder(self.taunt, target=1)
        result = mod.DoublesDamageAwarePlayer._anti_trick_room_response_eligible(
            self.player, order, 0, battle
        )
        self.assertTrue(result)

    def test_taunt_eligible_at_hp_1_0(self):
        """At t4, Incineroar HP=1.0, Taunt should be eligible."""
        battle = MockBattle(hp_frac=1.0, turn=4)
        order = MockOrder(self.taunt, target=1)
        result = mod.DoublesDamageAwarePlayer._anti_trick_room_response_eligible(
            self.player, order, 0, battle
        )
        self.assertTrue(result)

    def test_taunt_ineligible_at_hp_below_threshold(self):
        """At HP < 0.25, Taunt should NOT be eligible (survival guard)."""
        battle = MockBattle(hp_frac=0.20, turn=4)
        order = MockOrder(self.taunt, target=1)
        result = mod.DoublesDamageAwarePlayer._anti_trick_room_response_eligible(
            self.player, order, 0, battle
        )
        self.assertFalse(result)

    def test_taunt_ineligible_with_wrong_target(self):
        """Target 0 (EMPTY) is not eligible."""
        battle = MockBattle(hp_frac=1.0, turn=4)
        order = MockOrder(self.taunt, target=0)
        result = mod.DoublesDamageAwarePlayer._anti_trick_room_response_eligible(
            self.player, order, 0, battle
        )
        self.assertFalse(result)

    def test_flareblitz_not_response_eligible(self):
        """Flare Blitz is not a Taunt/Encore/Disable."""
        battle = MockBattle(hp_frac=1.0, turn=4)
        order = MockOrder(self.flareblitz, target=1)
        result = mod.DoublesDamageAwarePlayer._anti_trick_room_response_eligible(
            self.player, order, 0, battle
        )
        self.assertFalse(result)

    def test_flareblitz_ko_pressure_eligible(self):
        """Flare Blitz with ANTI_TR + target 1 should get KO bonus."""
        battle = MockBattle(hp_frac=1.0, turn=4)
        order = MockOrder(self.flareblitz, target=1)
        result = mod.DoublesDamageAwarePlayer._anti_trick_room_ko_pressure_eligible(
            self.player, order, 0, battle
        )
        self.assertTrue(result)

    def test_encore_eligible(self):
        """Encore is a valid response move."""
        battle = MockBattle(hp_frac=1.0, turn=4)
        order = MockOrder(self.encore, target=1)
        result = mod.DoublesDamageAwarePlayer._anti_trick_room_response_eligible(
            self.player, order, 0, battle
        )
        self.assertTrue(result)

    def test_disable_eligible(self):
        """Disable is a valid response move."""
        battle = MockBattle(hp_frac=1.0, turn=4)
        order = MockOrder(self.disable, target=1)
        result = mod.DoublesDamageAwarePlayer._anti_trick_room_response_eligible(
            self.player, order, 0, battle
        )
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
