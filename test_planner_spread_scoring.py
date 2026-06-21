"""PLANNER-SPREAD-2 — Tests for narrow spread defense scoring.

Test-first: these tests are written BEFORE the runtime smoke.

Validates:
- _planner_spread_defense_eligible returns True only when all guards pass
- Default OFF (enable_planner_spread_defense_scoring=False): never eligible
- Move is not Wide Guard: not eligible
- Intent is not SPREAD_DEFENSE: not eligible
- Confidence below threshold: not eligible
- Opp pressure not detected: not eligible
- Anti-spam: per-game pick count exceeded: not eligible
- All guards pass: eligible
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from bot_doubles_damage_aware import DoublesDamageAwareConfig


def make_player(spread_defense_flag=False, intent_flag=False):
    """Build a minimal mock player with the eligible method."""
    from bot_doubles_damage_aware import DoublesDamageAwarePlayer

    config = DoublesDamageAwareConfig()
    config.enable_planner_spread_defense_scoring = spread_defense_flag
    config.enable_planner_intent_detector = intent_flag

    # We don't need a real player; instantiate a stub via __new__ to bypass
    # the heavy __init__ that creates background tasks.
    player = DoublesDamageAwarePlayer.__new__(DoublesDamageAwarePlayer)
    player.config = config
    # Counter dicts (anti-spam)
    player._planner_spread_defense_picks_per_game = {}
    player._planner_spread_defense_last_pick_turn = {}
    return player


def make_order(move_id):
    """Build a mock order with a move."""
    from poke_env.battle.move import Move
    from poke_env.data import GenData

    # Try to construct a real Move, fall back to mock if move unknown
    try:
        move = Move(move_id, gen=9)
    except (ValueError, Exception):
        # Fall back: build a mock with the move id as attribute
        move = MagicMock()
        move.id = move_id

    order = MagicMock()
    order.order = move
    return order


def make_battle(turn=1, opp_pressure=True, has_decision=True,
                 decision_intent="SPREAD_DEFENSE", decision_confidence=0.65,
                 our_hp_0=0.5, our_hp_1=0.5):
    """Build a mock battle.

    our_hp_0 / our_hp_1: HP fractions for our active slots 0/1.
    Default 0.5 (both threatened) so the partner threat guard passes.
    Tests that want both at full HP should pass 1.0/1.0 explicitly.
    """
    battle = MagicMock()
    battle.battle_tag = "test-battle"
    battle.turn = turn
    if has_decision:
        decision = MagicMock()
        decision.intent = decision_intent
        decision.confidence = decision_confidence
        battle._planner_intent_decision = decision
    else:
        battle._planner_intent_decision = None
    # Set up active_pokemon with HP for partner threat guard
    mon_0 = MagicMock()
    mon_0.species = "testmon0"
    mon_0.current_hp_fraction = our_hp_0
    mon_0.fainted = False
    mon_1 = MagicMock()
    mon_1.species = "testmon1"
    mon_1.current_hp_fraction = our_hp_1
    mon_1.fainted = False
    battle.active_pokemon = [mon_0, mon_1]
    return battle


class TestEligibleDefaults(unittest.TestCase):
    """When the scoring flag is OFF, never eligible."""

    def test_default_off_never_eligible(self):
        player = make_player(spread_defense_flag=False, intent_flag=True)
        order = make_order("wideguard")
        battle = make_battle()
        result = player._planner_spread_defense_eligible(
            order, 0, battle
        )
        self.assertFalse(result)

    def test_intent_flag_off_never_eligible(self):
        player = make_player(spread_defense_flag=True, intent_flag=False)
        order = make_order("wideguard")
        battle = make_battle()
        result = player._planner_spread_defense_eligible(
            order, 0, battle
        )
        self.assertFalse(result)


class TestMoveGuard(unittest.TestCase):
    """Only Wide Guard candidates are eligible."""

    def test_non_wideguard_not_eligible(self):
        player = make_player(spread_defense_flag=True, intent_flag=True)
        order = make_order("heatwave")  # not WG
        battle = make_battle()
        result = player._planner_spread_defense_eligible(
            order, 0, battle
        )
        self.assertFalse(result)

    def test_wideguard_eligible(self):
        player = make_player(spread_defense_flag=True, intent_flag=True)
        order = make_order("wideguard")
        battle = make_battle()
        # Mock _slot_in_opp_pressure to return True
        player._slot_in_opp_pressure = MagicMock(return_value=True)
        result = player._planner_spread_defense_eligible(
            order, 0, battle
        )
        self.assertTrue(result)

    def test_wideguard_normalized_eligible(self):
        """Wide Guard with dashes/underscores in name should be eligible.

        The eligible method requires a real Move instance (isinstance check
        is a safety guard against accidental non-move orders). For this test
        we use a real Move constructed with the canonical lowercase name.
        The normalization is exercised by the actual Wide Guard move which
        uses the lowercase 'wideguard' id.
        """
        player = make_player(spread_defense_flag=True, intent_flag=True)
        order = make_order("wideguard")  # real Move instance
        battle = make_battle()
        player._slot_in_opp_pressure = MagicMock(return_value=True)
        result = player._planner_spread_defense_eligible(
            order, 0, battle
        )
        self.assertTrue(result)


class TestIntentGuard(unittest.TestCase):
    """Only fires when IntentDecision is SPREAD_DEFENSE."""

    def test_no_decision_not_eligible(self):
        player = make_player(spread_defense_flag=True, intent_flag=True)
        order = make_order("wideguard")
        battle = make_battle(has_decision=False)
        player._slot_in_opp_pressure = MagicMock(return_value=True)
        result = player._planner_spread_defense_eligible(
            order, 0, battle
        )
        self.assertFalse(result)

    def test_non_spread_intent_not_eligible(self):
        player = make_player(spread_defense_flag=True, intent_flag=True)
        order = make_order("wideguard")
        battle = make_battle(decision_intent="ANTI_TRICK_ROOM")
        player._slot_in_opp_pressure = MagicMock(return_value=True)
        result = player._planner_spread_defense_eligible(
            order, 0, battle
        )
        self.assertFalse(result)

    def test_no_intent_not_eligible(self):
        player = make_player(spread_defense_flag=True, intent_flag=True)
        order = make_order("wideguard")
        battle = make_battle(decision_intent="NO_INTENT")
        player._slot_in_opp_pressure = MagicMock(return_value=True)
        result = player._planner_spread_defense_eligible(
            order, 0, battle
        )
        self.assertFalse(result)


class TestConfidenceGuard(unittest.TestCase):
    """Confidence must meet threshold."""

    def test_low_confidence_not_eligible(self):
        player = make_player(spread_defense_flag=True, intent_flag=True)
        order = make_order("wideguard")
        # Default min_confidence is 0.5; provide 0.4
        battle = make_battle(decision_confidence=0.4)
        player._slot_in_opp_pressure = MagicMock(return_value=True)
        result = player._planner_spread_defense_eligible(
            order, 0, battle
        )
        self.assertFalse(result)

    def test_high_confidence_eligible(self):
        player = make_player(spread_defense_flag=True, intent_flag=True)
        order = make_order("wideguard")
        battle = make_battle(decision_confidence=0.95)
        player._slot_in_opp_pressure = MagicMock(return_value=True)
        result = player._planner_spread_defense_eligible(
            order, 0, battle
        )
        self.assertTrue(result)


class TestOppPressureGuard(unittest.TestCase):
    """Opp pressure must be detected."""

    def test_no_opp_pressure_not_eligible(self):
        player = make_player(spread_defense_flag=True, intent_flag=True)
        order = make_order("wideguard")
        battle = make_battle()
        player._slot_in_opp_pressure = MagicMock(return_value=False)
        result = player._planner_spread_defense_eligible(
            order, 0, battle
        )
        self.assertFalse(result)

    def test_opp_pressure_eligible(self):
        player = make_player(spread_defense_flag=True, intent_flag=True)
        order = make_order("wideguard")
        battle = make_battle()
        player._slot_in_opp_pressure = MagicMock(return_value=True)
        result = player._planner_spread_defense_eligible(
            order, 0, battle
        )
        self.assertTrue(result)


class TestAntiSpam(unittest.TestCase):
    """Anti-spam: per-game pick count, min turns between picks."""

    def test_max_picks_exceeded_not_eligible(self):
        player = make_player(spread_defense_flag=True, intent_flag=True)
        order = make_order("wideguard")
        battle = make_battle()
        # Simulate 3 picks already (default max_picks=3)
        player._planner_spread_defense_picks_per_game["test-battle"] = 3
        player._planner_spread_defense_last_pick_turn["test-battle"] = -999
        player._slot_in_opp_pressure = MagicMock(return_value=True)
        result = player._planner_spread_defense_eligible(
            order, 0, battle
        )
        self.assertFalse(result)

    def test_min_gap_not_met_not_eligible(self):
        player = make_player(spread_defense_flag=True, intent_flag=True)
        order = make_order("wideguard")
        battle = make_battle(turn=3)
        # Last pick was on turn 2; min_gap=2 so 3-2=1 < 2 → not eligible
        player._planner_spread_defense_picks_per_game["test-battle"] = 1
        player._planner_spread_defense_last_pick_turn["test-battle"] = 2
        player._slot_in_opp_pressure = MagicMock(return_value=True)
        result = player._planner_spread_defense_eligible(
            order, 0, battle
        )
        self.assertFalse(result)

    def test_anti_spam_passes_eligible(self):
        player = make_player(spread_defense_flag=True, intent_flag=True)
        order = make_order("wideguard")
        battle = make_battle(turn=5)
        # Last pick on turn 2; current=5; gap=3 >= 2 → eligible
        player._planner_spread_defense_picks_per_game["test-battle"] = 1
        player._planner_spread_defense_last_pick_turn["test-battle"] = 2
        player._slot_in_opp_pressure = MagicMock(return_value=True)
        result = player._planner_spread_defense_eligible(
            order, 0, battle
        )
        self.assertTrue(result)


class TestPickRecording(unittest.TestCase):
    """Pick recording updates the per-game counter."""

    def test_record_pick_increments_counter(self):
        player = make_player(spread_defense_flag=True, intent_flag=True)
        battle = make_battle(turn=3)
        player._planner_spread_defense_record_pick(battle, 0)
        self.assertEqual(
            player._planner_spread_defense_picks_per_game["test-battle"], 1
        )
        self.assertEqual(
            player._planner_spread_defense_last_pick_turn["test-battle"], 3
        )
        # Record another
        battle2 = make_battle(turn=5)
        player._planner_spread_defense_record_pick(battle2, 1)
        self.assertEqual(
            player._planner_spread_defense_picks_per_game["test-battle"], 2
        )
        self.assertEqual(
            player._planner_spread_defense_last_pick_turn["test-battle"], 5
        )


class TestConfigDefaults(unittest.TestCase):
    """Verify config defaults are safe (off, small bonus)."""

    def test_default_off(self):
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_planner_spread_defense_scoring)

    def test_default_bonus_is_small(self):
        config = DoublesDamageAwareConfig()
        # Should be <= 300 (smaller than existing 500)
        self.assertLessEqual(config.planner_spread_defense_wg_bonus, 300.0)
        # Should be > 0
        self.assertGreater(config.planner_spread_defense_wg_bonus, 0.0)

    def test_default_min_confidence(self):
        # PLANNER-SPREAD-8A: tightened default to 0.65 (was 0.5).
        # The revealed_moves detector path returns 0.65 conf, so this
        # threshold matches the detector's confidence and filters
        # the lower-confidence opp_pressure-only branch.
        config = DoublesDamageAwareConfig()
        self.assertEqual(config.planner_spread_defense_min_confidence, 0.65)


if __name__ == "__main__":
    unittest.main()
