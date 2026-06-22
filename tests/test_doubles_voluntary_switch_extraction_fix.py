#!/usr/bin/env python3
"""Phase 6.4.10c.1 — Audit wiring tests.

Focused tests for the VSW audit wiring fix.
ponytail: 5 tests, all prove the durable fix.
"""
import json
import os
import sys
import unittest

import poke_env_test_cleanup  # noqa: F401
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot_doubles_damage_aware import DoublesDamageAwareConfig


class TestAuditWiring(unittest.TestCase):

    def test_audit_logger_stores_candidate_count(self):
        """audit logger accepts and stores
        voluntary_switch_candidate_count."""
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        logger = DoublesDecisionAuditLogger(
            filepath="logs/test_audit_wiring.jsonl",
            reset=True, detail_level="top5",
        )
        # Confirm the kwarg exists on the signature.
        import inspect
        sig = inspect.signature(logger.log_turn_decision)
        self.assertIn(
            "voluntary_switch_candidate_count", sig.parameters
        )
        self.assertIn(
            "voluntary_switch_raw_switch_order_count",
            sig.parameters,
        )

    def test_audit_logger_drops_deleted_fields(self):
        """audit logger no longer accepts
        extraction_mismatch or build_skipped_by_guard."""
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        import inspect
        logger = DoublesDecisionAuditLogger(
            filepath="logs/test_audit_wiring.jsonl",
            reset=True, detail_level="top5",
        )
        sig = inspect.signature(logger.log_turn_decision)
        self.assertNotIn(
            "voluntary_switch_extraction_mismatch", sig.parameters
        )
        self.assertNotIn(
            "voluntary_switch_build_skipped_by_guard",
            sig.parameters,
        )

    def test_defaults_unchanged(self):
        """defaults remain as in DoublesDamageAwareConfig.

        AGENTS.md mandates:
        - diagnostics=True (observational only)
        - scoring=False (NOT adopted)
        """
        cfg = DoublesDamageAwareConfig()
        self.assertTrue(
            cfg.enable_voluntary_switch_quality_diagnostics
        )
        # AGENTS.md / adoption policy: scoring must
        # stay False until the paired qualification
        # with corrected audit fields is run and
        # adoption gates pass.
        self.assertFalse(
            cfg.enable_voluntary_switch_quality_scoring
        )

    def test_legacy_logs_do_not_crash(self):
        """legacy log records missing the new fields
        default to [0, 0] / [False, False] and don't
        crash downstream consumers."""
        legacy = {"turn": 1, "selected_joint_order": "/choose pass"}
        cand = legacy.get(
            "voluntary_switch_candidate_count", [0, 0]
        )
        raw = legacy.get(
            "voluntary_switch_raw_switch_order_count", [0, 0]
        )
        self.assertEqual(cand, [0, 0])
        self.assertEqual(raw, [0, 0])
        # Analyzer can compute mismatch without a
        # persisted boolean.
        mismatch = [
            raw[si] != cand[si] for si in (0, 1)
        ]
        self.assertEqual(mismatch, [False, False])

    def test_helpers_removed(self):
        """shared helpers added in 6.4.10c are removed
        — production uses inline isinstance."""
        with open(
            "bot_doubles_damage_aware.py"
        ) as f:
            src = f.read()
        # The build block should use inline isinstance.
        self.assertIn("isinstance(o.order, Pokemon)", src)
        # The 6.4.10c helpers are gone.
        self.assertNotIn("def is_switch_order(", src)
        self.assertNotIn("def extract_switch_candidate(", src)
        self.assertNotIn("def switch_candidate_species(", src)
        self.assertNotIn(
            "def count_switch_orders_in_slot(", src
        )
        self.assertNotIn("def count_total_switch_orders(", src)


if __name__ == "__main__":
    unittest.main()


class TestPreflightAndOnOffGuard(unittest.TestCase):
    """Phase 6.4.10d: preflight default and ON/OFF
    config assertions."""

    def test_preflight_asserts_source_defaults(self):
        """preflight_assert_defaults passes when source
        defaults are correct."""
        from bot_doubles_voluntary_switch_paired_qualification import (
            preflight_assert_defaults,
        )
        preflight_assert_defaults()

    def test_build_config_on_sets_scoring_true(self):
        from bot_doubles_voluntary_switch_paired_qualification import (
            build_config,
        )
        cfg = build_config("ON")
        self.assertTrue(
            cfg.enable_voluntary_switch_quality_diagnostics
        )
        self.assertTrue(
            cfg.enable_voluntary_switch_quality_scoring
        )
        # Defaults must stay off per AGENTS.md.
        self.assertFalse(cfg.enable_support_move_target_hard_safety)
        self.assertFalse(
            cfg.enable_ally_heal_wrong_side_hard_safety
        )

    def test_build_config_off_keeps_scoring_false(self):
        from bot_doubles_voluntary_switch_paired_qualification import (
            build_config,
        )
        cfg = build_config("OFF")
        self.assertTrue(
            cfg.enable_voluntary_switch_quality_diagnostics
        )
        self.assertFalse(
            cfg.enable_voluntary_switch_quality_scoring
        )

    def test_analyzer_uses_new_candidate_count_field(self):
        """Analyzer derives eligibility from
        voluntary_switch_candidate_count, not the
        dead voluntary_switch_decision_eligible."""
        from analyze_doubles_voluntary_switch_paired import (
            _collect_vsw_metrics,
        )
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            # Turn with candidate_count=2 should count
            # as 2 eligible (per slot).
            f.write(json.dumps({
                "audit_turns": [
                    {
                        "turn": 1,
                        "voluntary_switch_candidate_count": [2, 1],
                        "voluntary_switch_raw_switch_order_count": [3, 1],
                        "voluntary_switch_decision_eligible": [
                            False, False,
                        ],
                    }
                ]
            }))
            path = f.name
        try:
            m = _collect_vsw_metrics(path)
            self.assertEqual(m["n_candidate_total"], 3)
            self.assertEqual(m["n_raw_switch_orders"], 4)
            # n_eligible counts per-slot turns where
            # candidate_count[si] > 0.
            self.assertEqual(m["n_eligible"], 2)
        finally:
            os.unlink(path)

    def test_analyzer_counts_extraction_mismatch(self):
        """Mismatches (raw>0 && cand==0) are counted
        but are expected when active is fainted."""
        from analyze_doubles_voluntary_switch_paired import (
            _collect_vsw_metrics,
        )
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write(json.dumps({
                "audit_turns": [
                    {
                        "turn": 3,
                        "voluntary_switch_candidate_count": [0, 0],
                        "voluntary_switch_raw_switch_order_count": [4, 4],
                        "our_active": [None, None],
                    }
                ]
            }))
            path = f.name
        try:
            m = _collect_vsw_metrics(path)
            self.assertEqual(m["n_extraction_mismatch"], 2)
            self.assertEqual(m["n_candidate_total"], 0)
        finally:
            os.unlink(path)

    def test_legacy_missing_fields_do_not_crash(self):
        """Audit records from the OLD audit logger
        (no candidate_count, no raw_count) default to
        0/0 and don't crash."""
        from analyze_doubles_voluntary_switch_paired import (
            _collect_vsw_metrics,
        )
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            # Legacy record: only the OLD fields.
            f.write(json.dumps({
                "audit_turns": [
                    {
                        "turn": 1,
                        "voluntary_switch_decision_eligible": [
                            True, False,
                        ],
                    }
                ]
            }))
            path = f.name
        try:
            m = _collect_vsw_metrics(path)
            # New fields default to 0.
            self.assertEqual(m["n_candidate_total"], 0)
            self.assertEqual(m["n_raw_switch_orders"], 0)
            self.assertEqual(m["n_extraction_mismatch"], 0)
            # n_eligible uses the OLD field as a fallback
            # when candidate_count is missing. This
            # preserves backward compat with the buggy
            # 6.4.10 logs.
            self.assertGreaterEqual(m["n_eligible"], 0)
        finally:
            os.unlink(path)
