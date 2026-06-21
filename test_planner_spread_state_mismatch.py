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


def make_decision(opp_pressure=True):
    return IntentDecision(
        intent="SPREAD_DEFENSE",
        confidence=0.65,
        evidence_source="revealed_moves",
        matched_moves=("rockslide",),
        routed_to_policy="spread_defense",
        opp_pressure=opp_pressure,
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

    def test_state_mismatch_eligible_fails_guard5_legacy(self):
        """Legacy decision (no opp_pressure field) with live opp_press=False.
        
        Pre-PLANNER-SPREAD-3d behavior: eligible fails Guard 5 because
        the live state at scoring time is False (changed from True at
        detect time). This is the BUG that the new snapshot field fixes.
        """
        # Build a legacy decision (no opp_pressure) via spec'd mock
        from unittest.mock import MagicMock
        legacy_decision = MagicMock(spec=[
            "intent", "confidence", "evidence_source",
            "matched_moves", "routed_to_policy",
        ])
        legacy_decision.intent = "SPREAD_DEFENSE"
        legacy_decision.confidence = 0.65
        legacy_decision.matched_moves = ("rockslide",)
        legacy_decision.evidence_source = "revealed_moves"
        legacy_decision.routed_to_policy = "spread_defense"
        # No opp_pressure attribute (legacy)
        self.assertFalse(hasattr(legacy_decision, "opp_pressure"))
        battle = make_battle()
        setattr(battle, "_planner_intent_decision", legacy_decision)
        player = make_player(opp_press_value=False)
        order = make_wg_order()
        result = player._planner_spread_defense_eligible(order, 1, battle)
        self.assertFalse(result,
            "BUG CONFIRMED (legacy path): eligible fails Guard 5 when "
            "live opp_press is False even though intent=SPREAD_DEFENSE")

    def test_snapshot_field_passes_guard5(self):
        """PLANNER-SPREAD-3d: with opp_pressure=True on decision,
        eligible should pass Guard 5 even when live state is False.
        This is the FIX — the detector's snapshot wins.
        """
        # Detector saw opp_press=True, stored on decision
        decision = make_decision(opp_pressure=True)
        battle = make_battle()
        setattr(battle, "_planner_intent_decision", decision)
        # Live state at scoring time is False (state changed)
        player = make_player(opp_press_value=False)
        order = make_wg_order()
        result = player._planner_spread_defense_eligible(order, 1, battle)
        self.assertTrue(result,
            "FIX VERIFIED: snapshot opp_pressure=True on decision "
            "lets eligible pass Guard 5 even when live state is False")

    def test_snapshot_field_false_fails_guard5(self):
        """PLANNER-SPREAD-3d: with opp_pressure=False on decision,
        eligible should fail Guard 5. Detector saw no pressure, so
        the bonus should NOT apply.
        """
        decision = make_decision(opp_pressure=False)
        battle = make_battle()
        setattr(battle, "_planner_intent_decision", decision)
        # Even with live state True, snapshot wins
        player = make_player(opp_press_value=True)
        order = make_wg_order()
        result = player._planner_spread_defense_eligible(order, 1, battle)
        self.assertFalse(result,
            "FIX VERIFIED: snapshot opp_pressure=False on decision "
            "blocks Guard 5 even when live state is True")

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


class TestDetectorSnapshot(unittest.TestCase):
    """PLANNER-SPREAD-3d: verify the detector sets opp_pressure."""

    def test_detector_sets_opp_pressure_true(self):
        """When ctx has opp_pressure=True, the decision should have it too."""
        from bot_doubles_intent_classifier import IntentDetector
        det = IntentDetector(min_confidence=0.5)
        ctx = {
            "opp_revealed_moves": ["rockslide"],
            "fields": [],
            "side_conditions": [],
            "opp_used_tr": False,
            "opp_used_tw": False,
            "opp_used_stat_boost": False,
            "opp_pressure": True,
            "active_user_hp_fraction": 1.0,
            "expected_to_faint": False,
            "target_already_taunted": False,
        }
        decision = det.detect(ctx)
        self.assertEqual(decision.intent, "SPREAD_DEFENSE")
        self.assertTrue(decision.opp_pressure,
            "PLANNER-SPREAD-3d: detector must set opp_pressure on decision")

    def test_detector_sets_opp_pressure_false(self):
        """When ctx has opp_pressure=False, the decision should have it too."""
        from bot_doubles_intent_classifier import IntentDetector
        det = IntentDetector(min_confidence=0.5)
        ctx = {
            "opp_revealed_moves": ["rockslide"],
            "fields": [],
            "side_conditions": [],
            "opp_used_tr": False,
            "opp_used_tw": False,
            "opp_used_stat_boost": False,
            "opp_pressure": False,
            "active_user_hp_fraction": 1.0,
            "expected_to_faint": False,
            "target_already_taunted": False,
        }
        decision = det.detect(ctx)
        self.assertEqual(decision.intent, "SPREAD_DEFENSE")
        self.assertFalse(decision.opp_pressure,
            "PLANNER-SPREAD-3d: opp_pressure=False on decision")

    def test_no_intent_decision_has_opp_pressure_false(self):
        """NO_INTENT decisions should have opp_pressure=False."""
        from bot_doubles_intent_classifier import IntentDetector
        det = IntentDetector(min_confidence=0.5)
        # expected_to_faint=True forces NO_INTENT
        ctx = {
            "opp_revealed_moves": [],
            "fields": [],
            "side_conditions": [],
            "opp_used_tr": False,
            "opp_used_tw": False,
            "opp_used_stat_boost": False,
            "opp_pressure": False,
            "active_user_hp_fraction": 1.0,
            "expected_to_faint": True,
            "target_already_taunted": False,
        }
        decision = det.detect(ctx)
        self.assertEqual(decision.intent, "NO_INTENT")
        self.assertFalse(decision.opp_pressure)
