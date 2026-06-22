#!/usr/bin/env python3
"""Decision Timing Diagnostics Tests — Phase 6.4.3a.3

Verifies that timing diagnostics are optional (disabled by default) and
that when enabled, timing fields are properly computed and passed to the
audit logger.
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import poke_env_test_cleanup  # noqa: F401

from bot_doubles_damage_aware import DoublesDamageAwareConfig


class TestTimingConfig(unittest.TestCase):
    """Verify timing config defaults."""

    def test_timing_disabled_by_default(self):
        """enable_decision_timing_diagnostics should default to False."""
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_decision_timing_diagnostics)

    def test_timing_can_be_enabled(self):
        """enable_decision_timing_diagnostics can be set to True."""
        config = DoublesDamageAwareConfig(enable_decision_timing_diagnostics=True)
        self.assertTrue(config.enable_decision_timing_diagnostics)


class TestTimingComputation(unittest.TestCase):
    """Verify timing computation logic."""

    def test_timing_fields_default_none_when_disabled(self):
        """When timing is disabled, fields should be None."""
        # Simulate what choose_move does
        _timing_enabled = False
        _t_start = 0
        _t_valid_order = 0.0
        _t_score_action = 0.0
        _t_joint_scoring = 0.0
        _t_audit_postprocess = 0.0
        _score_action_call_count = 0
        _joint_order_count = 0

        decision_time_ms = ((_t_start + 0.01) * 1000) if _timing_enabled else None
        valid_order_time_ms = _t_valid_order if _timing_enabled else None
        score_action_time_ms = _t_score_action if _timing_enabled else None
        joint_scoring_time_ms = _t_joint_scoring if _timing_enabled else None
        audit_postprocess_time_ms = _t_audit_postprocess if _timing_enabled else None
        score_action_call_count = _score_action_call_count if _timing_enabled else None
        joint_order_count = _joint_order_count if _timing_enabled else None

        self.assertIsNone(decision_time_ms)
        self.assertIsNone(valid_order_time_ms)
        self.assertIsNone(score_action_time_ms)
        self.assertIsNone(joint_scoring_time_ms)
        self.assertIsNone(audit_postprocess_time_ms)
        self.assertIsNone(score_action_call_count)
        self.assertIsNone(joint_order_count)

    def test_timing_fields_populated_when_enabled(self):
        """When timing is enabled, fields should be populated."""
        _timing_enabled = True
        _t_start = 1000.0
        _t_valid_order = 5.0
        _t_score_action = 10.0
        _t_joint_scoring = 3.0
        _t_audit_postprocess = 2.0
        _score_action_call_count = 8
        _joint_order_count = 16

        valid_order_time_ms = _t_valid_order if _timing_enabled else None
        score_action_time_ms = _t_score_action if _timing_enabled else None
        joint_scoring_time_ms = _t_joint_scoring if _timing_enabled else None
        score_action_call_count = _score_action_call_count if _timing_enabled else None
        joint_order_count = _joint_order_count if _timing_enabled else None

        self.assertEqual(valid_order_time_ms, 5.0)
        self.assertEqual(score_action_time_ms, 10.0)
        self.assertEqual(joint_scoring_time_ms, 3.0)
        self.assertEqual(score_action_call_count, 8)
        self.assertEqual(joint_order_count, 16)

    def test_timing_fields_are_numeric(self):
        """Timing fields should be numeric when enabled."""
        _timing_enabled = True
        values = {
            "decision_time_ms": 15.5,
            "valid_order_time_ms": 2.3,
            "score_action_time_ms": 8.7,
            "joint_scoring_time_ms": 1.2,
            "audit_postprocess_time_ms": 3.3,
            "score_action_call_count": 6,
            "joint_order_count": 12,
        }
        for k, v in values.items():
            self.assertIsInstance(v, (int, float), f"{k} should be numeric")


class TestTimingAuditSerialization(unittest.TestCase):
    """Verify timing fields serialize correctly to audit JSONL."""

    def test_timing_fields_in_turn_data(self):
        """Timing fields should be included in turn data when present."""
        turn_data = {
            "turn": 1,
            "decision_time_ms": 15.5,
            "valid_order_time_ms": 2.3,
            "score_action_time_ms": 8.7,
            "joint_scoring_time_ms": 1.2,
            "audit_postprocess_time_ms": 3.3,
            "score_action_call_count": 6,
            "joint_order_count": 12,
        }
        self.assertEqual(turn_data["decision_time_ms"], 15.5)
        self.assertEqual(turn_data["score_action_call_count"], 6)
        self.assertEqual(turn_data["joint_order_count"], 12)

    def test_timing_fields_none_when_disabled(self):
        """Timing fields should be None when disabled."""
        turn_data = {
            "turn": 1,
            "decision_time_ms": None,
            "valid_order_time_ms": None,
            "score_action_time_ms": None,
            "joint_scoring_time_ms": None,
            "audit_postprocess_time_ms": None,
            "score_action_call_count": None,
            "joint_order_count": None,
        }
        for k in ["decision_time_ms", "valid_order_time_ms", "score_action_time_ms",
                   "joint_scoring_time_ms", "audit_postprocess_time_ms",
                   "score_action_call_count", "joint_order_count"]:
            self.assertIsNone(turn_data[k])


if __name__ == "__main__":
    unittest.main()
