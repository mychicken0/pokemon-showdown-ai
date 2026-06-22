#!/usr/bin/env python3
"""Tests for Phase V3c.2a analyzer perspective fix.

Regression targets: see V3c.2 artifact exact counts.
"""
import json
import os
import random
import sys
import unittest
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analyze_vgc2026_phaseV3a2_reality import (
    _row_perspective_result,
    analyze,
)


LEARNED = "learned_preview_v3c1"
BASELINE = "matchup_top4_v3"


def _row(
    our_policy: str,
    opp_policy: str,
    our_win: bool,
    side: str = "p1",
    status: str = "ok",
    pair_id: int = 0,
) -> Dict[str, Any]:
    return {
        "pair_id": pair_id,
        "side": side,
        "our_policy": our_policy,
        "opponent_policy": opp_policy,
        "our_win": our_win,
        "status": status,
        "turns": 5,
        "our_chosen_4": ["a", "b", "c", "d"],
        "our_lead_2": ["a", "b"],
        "our_back_2": ["c", "d"],
    }


class TestRowPerspectiveLearnedIsPlayer(unittest.TestCase):
    def test_player_learned_player_won(self):
        row = _row(LEARNED, BASELINE, our_win=True)
        lw, bw, reason = _row_perspective_result(
            row, LEARNED, BASELINE
        )
        self.assertIsNone(reason)
        self.assertIs(lw, True)
        self.assertIs(bw, False)

    def test_player_learned_player_lost(self):
        row = _row(LEARNED, BASELINE, our_win=False)
        lw, bw, reason = _row_perspective_result(
            row, LEARNED, BASELINE
        )
        self.assertIsNone(reason)
        self.assertIs(lw, False)
        self.assertIs(bw, True)


class TestRowPerspectiveLearnedIsOpponent(unittest.TestCase):
    def test_opp_learned_opp_won(self):
        # our_policy=baseline, opp_policy=learned, our_win=False
        # → baseline lost, learned won.
        row = _row(BASELINE, LEARNED, our_win=False)
        lw, bw, reason = _row_perspective_result(
            row, LEARNED, BASELINE
        )
        self.assertIsNone(reason)
        self.assertIs(lw, True)
        self.assertIs(bw, False)

    def test_opp_learned_player_won(self):
        # our_policy=baseline, opp_policy=learned, our_win=True
        # → baseline won, learned lost.
        row = _row(BASELINE, LEARNED, our_win=True)
        lw, bw, reason = _row_perspective_result(
            row, LEARNED, BASELINE
        )
        self.assertIsNone(reason)
        self.assertIs(lw, False)
        self.assertIs(bw, True)


class TestRowPerspectiveInvalid(unittest.TestCase):
    def test_both_sides_learned(self):
        row = _row(LEARNED, LEARNED, our_win=True)
        lw, bw, reason = _row_perspective_result(
            row, LEARNED, BASELINE
        )
        self.assertIsNone(lw)
        self.assertEqual(reason, "both_sides_learned")

    def test_neither_side_learned(self):
        row = _row(BASELINE, "random", our_win=True)
        lw, bw, reason = _row_perspective_result(
            row, LEARNED, BASELINE
        )
        self.assertIsNone(lw)
        self.assertEqual(reason, "neither_side_learned")

    def test_both_sides_baseline(self):
        row = _row(BASELINE, BASELINE, our_win=True)
        lw, bw, reason = _row_perspective_result(
            row, LEARNED, BASELINE
        )
        self.assertIsNone(lw)
        self.assertEqual(reason, "both_sides_baseline")

    def test_neither_side_baseline(self):
        row = _row(LEARNED, "random", our_win=True)
        lw, bw, reason = _row_perspective_result(
            row, LEARNED, BASELINE
        )
        self.assertIsNone(lw)
        self.assertEqual(reason, "neither_side_baseline")

    def test_malformed_outcome_non_boolean(self):
        row = _row(LEARNED, BASELINE, our_win="yes")
        lw, bw, reason = _row_perspective_result(
            row, LEARNED, BASELINE
        )
        self.assertIsNone(lw)
        self.assertEqual(reason, "missing_our_win")

    def test_status_not_ok(self):
        row = _row(LEARNED, BASELINE, our_win=True, status="timeout")
        lw, bw, reason = _row_perspective_result(
            row, LEARNED, BASELINE
        )
        self.assertIsNone(lw)
        self.assertEqual(reason, "status_timeout")

    def test_missing_our_policy(self):
        row = _row(BASELINE, LEARNED, our_win=True)
        row.pop("our_policy")
        lw, bw, reason = _row_perspective_result(
            row, LEARNED, BASELINE
        )
        self.assertIsNone(lw)
        self.assertEqual(reason, "missing_policy")


class TestV3c2ArtifactRegressionCounts(unittest.TestCase):
    """V3c.2 artifact exact-count regression test."""

    @classmethod
    def setUpClass(cls):
        cls.jsonl = (
            "logs/vgc2026_phaseV3c2_learned_v3c1_vs_v3_reality20"
            ".jsonl"
        )
        if not os.path.isfile(cls.jsonl):
            raise unittest.SkipTest(
                f"missing V3c.2 artifact {cls.jsonl}"
            )

    def test_perspective_counts(self):
        report = analyze(
            "phaseV3c2_learned_v3c1_vs_v3_reality20",
            learned_policy=LEARNED,
            baseline_policy=BASELINE,
        )
        self.assertEqual(report["n_pairs_valid"], 20)
        self.assertEqual(report["n_valid_battles"], 40)
        self.assertEqual(report["n_perspective_invalid"], 0)
        self.assertEqual(report["learned_wins"], 23)
        self.assertEqual(report["baseline_wins"], 17)
        self.assertEqual(report["learned_as_p1_n"], 20)
        self.assertEqual(report["learned_as_p2_n"], 20)
        self.assertEqual(report["learned_wins_as_p1"], 12)
        self.assertEqual(report["learned_wins_as_p2"], 11)
        self.assertEqual(report["on_both"], 7)
        self.assertEqual(report["v3_both"], 4)
        self.assertEqual(report["split"], 9)
        self.assertAlmostEqual(
            report["treatment_effect_mean"], 0.15, places=4
        )
        self.assertAlmostEqual(
            report["side_collapse"], 0.05, places=4
        )

    def test_shuffled_row_order_produces_identical_paired_counts(self):
        # Load rows, shuffle them, feed to analyze.
        rows = []
        with open(self.jsonl) as f:
            for line in f:
                rows.append(json.loads(line))
        # Reorder rows randomly.
        rng = random.Random(42)
        rng.shuffle(rows)
        # Write to a temporary jsonl.
        tmp_tag = "phaseV3c2a_test_shuffled"
        tmp_path = f"logs/vgc2026_{tmp_tag}.jsonl"
        with open(tmp_path, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        try:
            report = analyze(
                tmp_tag,
                learned_policy=LEARNED,
                baseline_policy=BASELINE,
            )
            self.assertEqual(report["n_pairs_valid"], 20)
            self.assertEqual(report["learned_wins"], 23)
            self.assertEqual(report["on_both"], 7)
            self.assertEqual(report["v3_both"], 4)
            self.assertEqual(report["split"], 9)
        finally:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)


class TestSideDiagnosticVsTreatmentEffect(unittest.TestCase):
    """Side diagnostic is a separate field from
    treatment effect. The analyzer must report
    both."""

    def test_side_diagnostic_in_report(self):
        report = analyze(
            "phaseV3c2_learned_v3c1_vs_v3_reality20",
            learned_policy=LEARNED,
            baseline_policy=BASELINE,
        )
        # Side diagnostic fields.
        self.assertIn("learned_as_p1_n", report)
        self.assertIn("learned_as_p2_n", report)
        self.assertIn("learned_as_p1_win_rate", report)
        self.assertIn("learned_as_p2_win_rate", report)
        self.assertIn("side_collapse", report)
        # Treatment effect fields.
        self.assertIn("treatment_effect_mean", report)
        self.assertIn("on_both", report)
        self.assertIn("v3_both", report)
        self.assertIn("split", report)
        # Side diagnostic and treatment effect are
        # separate measurements: side collapse is
        # |p1_rate - p2_rate|, treatment is
        # (on_both - v3_both) / n.
        self.assertNotEqual(
            report["side_collapse"],
            report["treatment_effect_mean"],
        )


class TestAnalyzerLearnedAndBaselineArgs(unittest.TestCase):
    """Analyzer must accept learned-policy and
    baseline-policy args."""

    def test_default_args(self):
        # The default args must still work for V3a.2
        # (no perspective validation against specific
        # policies because V3a.2 used random_vs_basic
        # labels; the analyzer simply doesn't compute
        # win rate for them).
        # The default is learned_preview_v3a1 and
        # matchup_top4_v3. Calling with default args
        # on V3c.2 artifact will produce 100% invalid
        # rows because the actual policies are V3c.1
        # vs V3.
        report = analyze(
            "phaseV3c2_learned_v3c1_vs_v3_reality20",
        )
        self.assertEqual(report["n_perspective_invalid"], 40)

    def test_explicit_args(self):
        report = analyze(
            "phaseV3c2_learned_v3c1_vs_v3_reality20",
            learned_policy=LEARNED,
            baseline_policy=BASELINE,
        )
        self.assertEqual(report["n_perspective_invalid"], 0)
        self.assertEqual(report["learned_wins"], 23)


class TestArtifactJsonSerializable(unittest.TestCase):
    """V3c.2a analyzer's report is JSON-serializable."""

    def test_report_json_loadable(self):
        report = analyze(
            "phaseV3c2_learned_v3c1_vs_v3_reality20",
            learned_policy=LEARNED,
            baseline_policy=BASELINE,
        )
        # Must be JSON-serializable.
        s = json.dumps(report, default=str)
        loaded = json.loads(s)
        self.assertEqual(
            loaded["learned_wins"], report["learned_wins"]
        )


if __name__ == "__main__":
    unittest.main()
