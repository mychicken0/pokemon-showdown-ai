"""PLANNER-IMPL-2 — Tests for the per-turn IntentDetector.

Test-first: these tests are written BEFORE
the implementation. The detector is a pure
function; tests use a simple context dict
(no poke-env dependency).

Coverage (13 fixture tests):

ANTI_TRICK_ROOM (3):
  - test_atr_revealed_in_moves
  - test_atr_active_in_fields
  - test_atr_no_signal_returns_no_intent

ANTI_TAILWIND (3):
  - test_atw_revealed_in_moves
  - test_atw_active_in_side_conditions
  - test_atw_no_signal_returns_no_intent

ANTI_STAT_BOOST (3):
  - test_asb_revealed_in_moves
  - test_asb_counter_incremented
  - test_asb_no_signal_returns_no_intent

SPREAD_DEFENSE (2):
  - test_sd_revealed_spread_move
  - test_sd_no_signal_returns_no_intent

Cross-cutting (4):
  - test_no_intent_default_when_empty_context
  - test_confidence_threshold_below_min_returns_no_intent
  - test_fainting_user_returns_no_intent
  - test_target_already_taunted_returns_no_intent
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from bot_doubles_intent_classifier import (
    IntentDetector,
    IntentDecision,
    NO_INTENT,
    ANTI_TRICK_ROOM,
    ANTI_TAILWIND,
    ANTI_STAT_BOOST,
    SPREAD_DEFENSE,
    EVIDENCE_REVEALED_MOVES,
    EVIDENCE_FIELD_STATE,
    EVIDENCE_SIDE_CONDITION,
    EVIDENCE_OPP_COUNTER,
    EVIDENCE_OPP_PRESSURE,
    ROUTE_NONE,
    ROUTE_ANTI_SETUP,
    ROUTE_SPREAD_DEFENSE,
)


def make_ctx(**overrides):
    """Build a default empty context; override keys as needed."""
    ctx = {
        "opp_revealed_moves": [],  # list of move-id strings
        "fields": [],              # list of field-enum names (e.g., "trick_room")
        "side_conditions": [],     # list of side-condition names (e.g., "tailwind")
        "opp_used_tr": False,
        "opp_used_tw": False,
        "opp_used_stat_boost": False,
        "opp_pressure": False,
        "active_user_hp_fraction": 1.0,
        "expected_to_faint": False,
        "target_already_taunted": False,
    }
    ctx.update(overrides)
    return ctx


class TestAntiTrickRoom(unittest.TestCase):
    def test_atr_revealed_in_moves(self):
        det = IntentDetector()
        ctx = make_ctx(opp_revealed_moves=["trickroom"])
        d = det.detect(ctx)
        self.assertEqual(d.intent, ANTI_TRICK_ROOM)
        self.assertEqual(d.evidence_source, EVIDENCE_REVEALED_MOVES)
        self.assertEqual(d.routed_to_policy, ROUTE_ANTI_SETUP)
        self.assertGreaterEqual(d.confidence, 0.5)
        self.assertIn("trickroom", d.matched_moves)

    def test_atr_active_in_fields(self):
        det = IntentDetector()
        ctx = make_ctx(fields=["trick_room"])
        d = det.detect(ctx)
        self.assertEqual(d.intent, ANTI_TRICK_ROOM)
        self.assertEqual(d.evidence_source, EVIDENCE_FIELD_STATE)
        self.assertGreaterEqual(d.confidence, 0.9)

    def test_atr_no_signal_returns_no_intent(self):
        det = IntentDetector()
        ctx = make_ctx()
        d = det.detect(ctx)
        self.assertEqual(d.intent, NO_INTENT)
        self.assertEqual(d.confidence, 0.0)
        self.assertEqual(d.routed_to_policy, ROUTE_NONE)


class TestAntiTailwind(unittest.TestCase):
    def test_atw_revealed_in_moves(self):
        det = IntentDetector()
        ctx = make_ctx(opp_revealed_moves=["tailwind"])
        d = det.detect(ctx)
        self.assertEqual(d.intent, ANTI_TAILWIND)
        self.assertEqual(d.evidence_source, EVIDENCE_REVEALED_MOVES)
        self.assertEqual(d.routed_to_policy, ROUTE_ANTI_SETUP)
        self.assertGreaterEqual(d.confidence, 0.5)
        self.assertIn("tailwind", d.matched_moves)

    def test_atw_active_in_side_conditions(self):
        det = IntentDetector()
        ctx = make_ctx(side_conditions=["tailwind"])
        d = det.detect(ctx)
        self.assertEqual(d.intent, ANTI_TAILWIND)
        self.assertEqual(d.evidence_source, EVIDENCE_SIDE_CONDITION)
        self.assertGreaterEqual(d.confidence, 0.9)

    def test_atw_no_signal_returns_no_intent(self):
        det = IntentDetector()
        ctx = make_ctx()
        d = det.detect(ctx)
        self.assertEqual(d.intent, NO_INTENT)
        self.assertEqual(d.confidence, 0.0)


class TestAntiStatBoost(unittest.TestCase):
    def test_asb_revealed_in_moves(self):
        det = IntentDetector()
        ctx = make_ctx(opp_revealed_moves=["swordsdance"])
        d = det.detect(ctx)
        self.assertEqual(d.intent, ANTI_STAT_BOOST)
        self.assertEqual(d.evidence_source, EVIDENCE_REVEALED_MOVES)
        self.assertEqual(d.routed_to_policy, ROUTE_ANTI_SETUP)
        self.assertGreaterEqual(d.confidence, 0.5)
        self.assertIn("swordsdance", d.matched_moves)

    def test_asb_counter_incremented(self):
        det = IntentDetector()
        ctx = make_ctx(opp_used_stat_boost=True)
        d = det.detect(ctx)
        self.assertEqual(d.intent, ANTI_STAT_BOOST)
        self.assertEqual(d.evidence_source, EVIDENCE_OPP_COUNTER)
        self.assertGreaterEqual(d.confidence, 0.8)

    def test_asb_no_signal_returns_no_intent(self):
        det = IntentDetector()
        ctx = make_ctx()
        d = det.detect(ctx)
        self.assertEqual(d.intent, NO_INTENT)
        self.assertEqual(d.confidence, 0.0)


class TestSpreadDefense(unittest.TestCase):
    def test_sd_revealed_spread_move(self):
        det = IntentDetector()
        ctx = make_ctx(opp_revealed_moves=["heatwave"])
        d = det.detect(ctx)
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertEqual(d.evidence_source, EVIDENCE_REVEALED_MOVES)
        self.assertEqual(d.routed_to_policy, ROUTE_SPREAD_DEFENSE)
        self.assertGreaterEqual(d.confidence, 0.5)
        self.assertIn("heatwave", d.matched_moves)

    def test_sd_no_signal_returns_no_intent(self):
        det = IntentDetector()
        ctx = make_ctx()
        d = det.detect(ctx)
        self.assertEqual(d.intent, NO_INTENT)
        self.assertEqual(d.confidence, 0.0)


class TestCrossCutting(unittest.TestCase):
    def test_no_intent_default_when_empty_context(self):
        det = IntentDetector()
        d = det.detect({})
        self.assertEqual(d.intent, NO_INTENT)
        self.assertEqual(d.confidence, 0.0)
        self.assertEqual(d.evidence_source, "")
        self.assertEqual(d.routed_to_policy, ROUTE_NONE)

    def test_confidence_threshold_below_min_returns_no_intent(self):
        # Confidence is fixed by evidence type; this test checks
        # the detector's min_confidence knob (default 0.5).
        det = IntentDetector(min_confidence=0.95)
        ctx = make_ctx(opp_revealed_moves=["trickroom"])
        d = det.detect(ctx)
        # 0.7 < 0.95, so the detector suppresses it
        self.assertEqual(d.intent, NO_INTENT)

    def test_fainting_user_returns_no_intent(self):
        det = IntentDetector()
        ctx = make_ctx(
            opp_revealed_moves=["trickroom"],
            expected_to_faint=True,
        )
        d = det.detect(ctx)
        self.assertEqual(d.intent, NO_INTENT)

    def test_target_already_taunted_returns_no_intent(self):
        det = IntentDetector()
        ctx = make_ctx(
            opp_revealed_moves=["trickroom"],
            target_already_taunted=True,
        )
        d = det.detect(ctx)
        self.assertEqual(d.intent, NO_INTENT)


if __name__ == "__main__":
    unittest.main()
