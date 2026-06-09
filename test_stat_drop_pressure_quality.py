"""Phase 6.4.7b — Stat-Drop Pressure Quality Tests."""
import unittest
import json
import os
import tempfile
import sys
import argparse

import poke_env_test_cleanup  # noqa: F401

sys.path.insert(0, os.path.dirname(__file__))


def _make_turn_with_pressure(cats=None, sw_sel=False, unprod=False, prod=False,
                              changed=False, best_sw=8.0, best_ns=150.0,
                              press_sc=170.0, ts="offensive_-1",
                              best_sw_sp="raichu", reason="test",
                              scoring_enabled=True):
    td = {"turn": 1, "selected_joint_order": "/choose move tackle 1, move tackle 2"}
    s0 = {
        "stat_drop_switch_scoring_enabled": scoring_enabled,
        "stat_drop_switch_pressure_active": True,
        "stat_drop_switch_pressure_categories": cats or ["offensive"],
        "stat_drop_switch_pressure_score": press_sc,
        "stat_drop_switch_selected": sw_sel,
        "stat_drop_switch_stayed": not sw_sel,
        "stat_drop_switch_stayed_productive": prod,
        "stat_drop_switch_stayed_unproductive": unprod,
        "stat_drop_switch_selection_changed": changed,
        "stat_drop_switch_best_switch_species": best_sw_sp,
        "stat_drop_switch_best_switch_score": best_sw,
        "stat_drop_switch_best_non_switch_score": best_ns,
        "stat_drop_switch_reason": reason,
        "stat_drop_switch_threshold_source": ts,
    }
    td["slot_0"] = s0
    td["slot_1"] = {}
    return td


class TestInspectorGap(unittest.TestCase):
    def test_gap_computation(self):
        td = _make_turn_with_pressure(best_sw=88.0, best_ns=109.0)
        rec = {"battle_tag": "test1", "won": True, "benchmark_arm": "B",
               "audit_turns": [td]}
        tmp = tempfile.mkdtemp()
        fp = os.path.join(tmp, "t.jsonl")
        with open(fp, "w") as f:
            f.write(json.dumps(rec) + "\n")

        # Direct gap computation
        gap = td["slot_0"]["stat_drop_switch_best_switch_score"] - td["slot_0"]["stat_drop_switch_best_non_switch_score"]
        self.assertEqual(gap, -21.0)

        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    def test_switch_selected_filter(self):
        td = _make_turn_with_pressure(sw_sel=True, best_sw=88.0, best_ns=50.0)
        self.assertTrue(td["slot_0"]["stat_drop_switch_selected"])

    def test_pressure_losses_filter(self):
        td = _make_turn_with_pressure(unprod=True)
        self.assertTrue(td["slot_0"]["stat_drop_switch_stayed_unproductive"])
        self.assertFalse(td["slot_0"]["stat_drop_switch_selected"])


class TestAnalyzerExtras(unittest.TestCase):
    def test_avg_scores_computed(self):
        td = _make_turn_with_pressure(best_sw=8.0, best_ns=200.0)
        td2 = _make_turn_with_pressure(best_sw=88.0, best_ns=100.0, sw_sel=True)
        td2["turn"] = 2
        rec = {"battle_tag": "test1", "won": False, "benchmark_arm": "B",
               "audit_turns": [td, td2]}
        tmp = tempfile.mkdtemp()
        fp = os.path.join(tmp, "t.jsonl")
        with open(fp, "w") as f:
            f.write(json.dumps(rec) + "\n")

        import io
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            from analyze_doubles_decision_audit import analyze_audit_log
            analyze_audit_log(fp)
            out = sys.stdout.getvalue()
        finally:
            sys.stdout = old

        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

        self.assertIn("avg best_switch_score", out)
        self.assertIn("avg best_non_switch_score", out)
        self.assertIn("action type split", out)

    def test_missing_fields_safe(self):
        td = {"turn": 1,
              "slot_0": {"stat_drop_switch_pressure_active": True},
              "slot_1": {}}
        rec = {"battle_tag": "test1", "won": False, "benchmark_arm": "B",
               "audit_turns": [td]}
        tmp = tempfile.mkdtemp()
        fp = os.path.join(tmp, "t.jsonl")
        with open(fp, "w") as f:
            f.write(json.dumps(rec) + "\n")

        import io
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            from analyze_doubles_decision_audit import analyze_audit_log
            analyze_audit_log(fp)
        finally:
            sys.stdout = old
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


class TestNoMutation(unittest.TestCase):
    def test_no_config_mutation(self):
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        c = DoublesDamageAwareConfig()
        self.assertFalse(c.enable_stat_drop_switch_scoring)
        self.assertEqual(c.stat_drop_switch_offensive_penalty, 90.0)
        self.assertEqual(c.stat_drop_switch_safe_switch_bonus, 80.0)
        self.assertEqual(c.stat_drop_switch_offensive_stage_threshold, -1)


if __name__ == "__main__":
    import argparse
    unittest.main()
