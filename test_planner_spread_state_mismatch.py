"""PLANNER-SPREAD-3c fixture: state mismatch between detector and eligible.

Demonstrates that when choose_move is called multiple times per turn,
the eligible check can fail Guard 5 even when the detector returned
SPREAD_DEFENSE (because opp_pressure state can change between calls).
"""
import unittest
from unittest.mock import MagicMock

import bot_doubles_damage_aware as mod
from bot_doubles_damage_aware import DoublesDamageAwareConfig
from bot_doubles_intent_classifier import IntentDecision
from poke_env.battle.move import Move


def make_player(opp_press_value=False):
    """Make a player with controlled opp_pressure state."""
    config = DoublesDamageAwareConfig()
    config.enable_planner_intent_detector = True
    config.enable_planner_spread_defense_scoring = True

    player = mod.DoublesDamageAwarePlayer.__new__(mod.DoublesDamageAwarePlayer)
    player.config = config
    player._planner_spread_defense_picks_per_game = {}
    player._planner_spread_defense_last_pick_turn = {}
    player._slot_in_opp_pressure = lambda *args: opp_press_value
    return player


def make_battle():
    battle = MagicMock()
    battle.battle_tag = "test"
    battle.turn = 3
    return battle


def make_decision():
    return IntentDecision(
        intent="SPREAD_DEFENSE",
        confidence=0.65,
        evidence_source="revealed_moves",
        matched_moves=("rockslide",),
        routed_to_policy="spread_defense",
    )


def make_wg_order():
    order = MagicMock()
    order.order = Move("wideguard", gen=9)
    return order


class TestStateMismatch(unittest.TestCase):
    """Test that state mismatch between detector and eligible is detected."""

    def test_state_match_eligible_passes(self):
        """Detector and eligible both see opp_press=True → eligible should pass."""
        player = make_player(opp_press_value=True)
        battle = make_battle()
        decision = make_decision()
        setattr(battle, "_planner_intent_decision", decision)
        order = make_wg_order()
        result = player._planner_spread_defense_eligible(order, 1, battle)
        self.assertTrue(result, "eligible should pass when both see opp_press=True")

    def test_state_mismatch_eligible_fails_guard5(self):
        """Detector saw opp_press=True but eligible sees opp_press=False.
        
        This is the BUG that causes the bonus to not apply in the smoke run.
        The detector's decision said SPREAD_DEFENSE (with full evidence),
        but the eligible's Guard 5 re-evaluates the LIVE state, which has
        changed between the detector call and the eligible call.
        """
        decision = make_decision()
        battle = make_battle()
        setattr(battle, "_planner_intent_decision", decision)
        player = make_player(opp_press_value=False)
        order = make_wg_order()
        result = player._planner_spread_defense_eligible(order, 1, battle)
        self.assertFalse(result,
            "BUG CONFIRMED: eligible fails Guard 5 even though "
            "decision.intent=SPREAD_DEFENSE because live opp_press state changed")

    def test_intent_no_intent_fails(self):
        """When intent is NO_INTENT, eligible should return False."""
        player = make_player(opp_press_value=True)
        battle = make_battle()
        decision = IntentDecision(
            intent="NO_INTENT",
            confidence=0.0,
            evidence_source="",
            matched_moves=(),
            routed_to_policy="",
        )
        setattr(battle, "_planner_intent_decision", decision)
        order = make_wg_order()
        result = player._planner_spread_defense_eligible(order, 1, battle)
        self.assertFalse(result, "eligible should fail for NO_INTENT")


if __name__ == "__main__":
    unittest.main()
