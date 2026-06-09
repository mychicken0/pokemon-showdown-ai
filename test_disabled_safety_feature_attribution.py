"""Phase 6.4.8 — Disabled Safety Feature Attribution Tests.

Tests for the unified inspector and analyzer attribution sections.
"""
import unittest
import json
import os
import tempfile
import sys

import poke_env_test_cleanup  # noqa: F401

sys.path.insert(0, os.path.dirname(__file__))


def _make_turn(forced=False, stale=False, statdrop=False, **kw):
    td = {"turn": 1, "selected_joint_order": "/choose move a1, move a2",
          "score_gap_selected_best_alt": 10.0}
    s0 = {}
    s1 = {}
    if forced:
        s0["forced_switch"] = True
        s0["forced_switch_safety_enabled"] = kw.get("fs_enabled", False)
        s0["forced_switch_selected_double_threat"] = kw.get("fs_dt", False)
        s0["forced_switch_selected_quad_weak"] = kw.get("fs_qw", False)
        s0["forced_switch_safety_selection_changed"] = kw.get("fs_changed", False)
        s0["forced_switch_selected_safety_score"] = kw.get("fs_sel_score", 0)
        s0["forced_switch_best_safety_score"] = kw.get("fs_best_score", 0)
        s0["forced_switch_order_fallback_used"] = kw.get("fs_fallback", False)
        s0["forced_switch_candidate_count"] = kw.get("fs_cand_count", 3)
        s0["forced_switch_selected_species"] = kw.get("fs_species", "pikachu")
        s0["forced_switch_best_safety_species"] = kw.get("fs_best_species", "gyarados")
        s0["forced_switch_reason"] = kw.get("fs_reason", "double_threat")
    if statdrop:
        s0["stat_drop_switch_scoring_enabled"] = kw.get("sd_enabled", False)
        s0["stat_drop_switch_pressure_active"] = True
        s0["stat_drop_switch_selected"] = kw.get("sd_selected", False)
        s0["stat_drop_switch_stayed_unproductive"] = kw.get("sd_unprod", False)
        s0["stat_drop_switch_selection_changed"] = kw.get("sd_changed", False)
        s0["stat_drop_switch_pressure_categories"] = kw.get("sd_cats", ["offensive"])
        s0["stat_drop_switch_best_switch_species"] = kw.get("sd_best_sw", "gyarados")
        s0["stat_drop_switch_best_switch_score"] = kw.get("sd_best_sw_sc", 30.0)
        s0["stat_drop_switch_best_non_switch_score"] = kw.get("sd_best_ns", 50.0)
        s0["stat_drop_switch_pressure_score"] = kw.get("sd_press", 130.0)
        s0["stat_drop_switch_reason"] = kw.get("sd_reason", "offensive_drop")
    if stale:
        td["stale_target_selected"] = True
        td["stale_target_caused_type_immune"] = kw.get("st_ti", False)
        td["stale_target_caused_no_effect"] = kw.get("st_ne", False)
        td["stale_target_reason"] = kw.get("st_reason", "fallback_type_immune")
        td["stale_target_first_move"] = "closecombat"
        td["stale_target_first_target"] = "abomasnow"
        td["stale_target_second_move"] = "bodypress"
        td["stale_target_second_intended_target"] = "abomasnow"
        td["stale_target_fallback_target"] = "sableye"
    td["slot_0"] = s0
    td["slot_1"] = s1
    return td


class TestInspectorParsing(unittest.TestCase):
    def setUp(self):
        from inspect_disabled_safety_feature_cases import _get_feature_cases

        self._get_feature_cases = _get_feature_cases

    def test_parses_forced_switch(self):
        td = _make_turn(forced=True, fs_dt=True)
        cases = self._get_feature_cases(td, "forced_switch")
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["feature"], "forced-switch")
        self.assertTrue(cases[0]["double_threat"])

    def test_parses_stale_target(self):
        td = _make_turn(stale=True, st_ti=True)
        cases = self._get_feature_cases(td, "stale_target")
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["feature"], "stale-target")
        self.assertTrue(cases[0]["type_immune"])

    def test_parses_stat_drop(self):
        td = _make_turn(statdrop=True, sd_unprod=True)
        cases = self._get_feature_cases(td, "stat_drop_switch")
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["feature"], "stat-drop")
        self.assertTrue(cases[0]["stayed_unproductive"])

    def test_missing_fields_safe_defaults(self):
        td = _make_turn(forced=True)
        # No fs_dt, fs_qw, etc.
        cases = self._get_feature_cases(td, "forced_switch")
        self.assertEqual(len(cases), 1)
        self.assertFalse(cases[0]["double_threat"])
        self.assertFalse(cases[0]["quad_weak"])

    def test_no_relevant_slot_returns_empty(self):
        td = {"turn": 1, "slot_0": {}, "slot_1": {}}
        cases = self._get_feature_cases(td, "forced_switch")
        self.assertEqual(len(cases), 0)

    def test_no_stale_returns_empty(self):
        td = {"turn": 1, "slot_0": {}, "slot_1": {}}
        cases = self._get_feature_cases(td, "stale_target")
        self.assertEqual(len(cases), 0)


class TestAnalyzerCounts(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_log(self, records):
        with open(self.log_path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def test_counts_forced_switch(self):
        td = _make_turn(forced=True, fs_dt=True, fs_qw=False)
        rec = {"battle_tag": "test1", "won": False, "benchmark_arm": "B",
               "audit_turns": [td]}
        self._write_log([rec])

        from analyze_doubles_decision_audit import analyze_audit_log
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            analyze_audit_log(self.log_path)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("selected double-threat", output)
        self.assertIn("selected quad-weak", output)

    def test_counts_stale_target(self):
        td = _make_turn(stale=True, st_ti=True, st_ne=False)
        rec = {"battle_tag": "test1", "won": False, "benchmark_arm": "B",
               "audit_turns": [td]}
        self._write_log([rec])

        from analyze_doubles_decision_audit import analyze_audit_log
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            analyze_audit_log(self.log_path)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("stale_target_selected", output)
        self.assertIn("type-immune fallback", output)

    def test_counts_stat_drop(self):
        td = _make_turn(statdrop=True, sd_unprod=True, sd_cats=["offensive", "defensive"])
        rec = {"battle_tag": "test1", "won": False, "benchmark_arm": "B",
               "audit_turns": [td]}
        self._write_log([rec])

        from analyze_doubles_decision_audit import analyze_audit_log
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            analyze_audit_log(self.log_path)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("switch selected", output)
        self.assertIn("stayed unproductive", output)
        self.assertIn("offensive/defensive/speed", output)

    def test_missing_fields_treated_safe(self):
        """Legacy logs missing newer fields should not crash."""
        td = {"turn": 1, "slot_0": {"forced_switch": True},
              "slot_1": {}}
        rec = {"battle_tag": "test1", "won": False, "benchmark_arm": "A",
               "audit_turns": [td]}
        self._write_log([rec])

        from analyze_doubles_decision_audit import analyze_audit_log
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            analyze_audit_log(self.log_path)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("forced switch events", output)


class TestNoMutation(unittest.TestCase):
    def test_no_config_mutation(self):
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        c = DoublesDamageAwareConfig()
        defaults = {
            "enable_forced_switch_replacement_safety": False,
            "enable_stale_target_after_ally_ko_safety": False,
            "enable_stat_drop_switch_scoring": False,
            "enable_ability_awareness": False,
        }
        for k, v in defaults.items():
            self.assertEqual(getattr(c, k), v, f"{k} should still be {v}")


if __name__ == "__main__":
    unittest.main()
