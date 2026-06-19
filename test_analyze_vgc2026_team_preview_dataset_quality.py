"""Phase RL-2 — Tests for the read-only team-preview dataset
quality analyzer.

Uses tiny temp CSV/JSONL/model fixtures. Does not depend on
real logs.
"""
import csv
import json
import os
import sys
import tempfile
import unittest


def _make_csv_row(
    pair_id, side, status="ok", our_win=False,
    our_chosen_4=None, our_lead_2=None, our_back_2=None,
    our_policy="learned_preview_v3c1",
    opponent_policy="matchup_top4_v3",
):
    """Build a minimal CSV row."""
    return {
        "pair_id": str(pair_id),
        "side": side,
        "our_policy": our_policy,
        "opponent_policy": opponent_policy,
        "battle_tag": f"battle-{pair_id:03d}-{side}",
        "started_at": "2026-06-16T12:00:00",
        "finished_at": "2026-06-16T12:00:01",
        "status": status,
        "our_win": str(our_win),
        "turns": "5",
        "error_detail": "",
        "our_chosen_4": "|".join(our_chosen_4 or []),
        "our_lead_2": "|".join(our_lead_2 or []),
        "our_back_2": "|".join(our_back_2 or []),
        "opp_chosen_4": "a|b|c|d",
        "opp_lead_2": "a|b",
        "opp_back_2": "c|d",
    }


def _write_csv(path, rows):
    """Write rows to a CSV file."""
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path, rows):
    """Write rows to a JSONL file."""
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _make_model(
    feature_names=None, weights=None, bias=0.0,
):
    """Build a minimal model JSON."""
    if feature_names is None:
        feature_names = [
            "back_coverage_count", "lead_def_mean_threat",
            "lead_off_mean_eff", "sc_fo_count",
        ]
    if weights is None:
        weights = {f: 0.1 for f in feature_names}
    return {
        "feature_names": feature_names,
        "weights": weights,
        "bias": bias,
    }


class TestRequiresAtLeastOneInput(unittest.TestCase):
    def test_no_input_fails(self):
        from analyze_vgc2026_team_preview_dataset_quality import (
            main,
        )
        with tempfile.TemporaryDirectory() as tmp:
            md = os.path.join(tmp, "r.md")
            sys.argv = ["analyzer", "--md", md]
            with self.assertRaises(SystemExit):
                main()

    def test_csv_input_works(self):
        from analyze_vgc2026_team_preview_dataset_quality import (
            main,
        )
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "test.csv")
            md = os.path.join(tmp, "r.md")
            row = _make_csv_row(0, "p1", our_chosen_4=["a", "b", "c", "d"])
            _write_csv(csv_path, [row])
            sys.argv = [
                "analyzer", "--csv", csv_path, "--md", md
            ]
            main()
            self.assertTrue(os.path.exists(md))


class TestParsesCSVRows(unittest.TestCase):
    def test_parses_csv_row_counts_and_status(self):
        from analyze_vgc2026_team_preview_dataset_quality import (
            _load_csv, _aggregate,
        )
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "test.csv")
            rows = [
                _make_csv_row(0, "p1", our_chosen_4=["a", "b", "c", "d"]),
                _make_csv_row(0, "p2", our_chosen_4=["e", "f", "g", "h"]),
                _make_csv_row(1, "p1", status="timeout",
                              our_chosen_4=["a", "b", "c", "d"]),
                _make_csv_row(1, "p2", status="timeout",
                              our_chosen_4=["e", "f", "g", "h"]),
            ]
            _write_csv(csv_path, rows)
            csv_rows, _, _ = _load_csv(csv_path)
            agg = _aggregate(
                csv_rows, [], None, csv_path, None, None
            )
            self.assertEqual(agg["data_quality"]["csv_rows"], 4)
            self.assertEqual(
                agg["data_quality"]["csv_status_counts"].get("ok"), 2
            )
            self.assertEqual(
                agg["data_quality"]["csv_status_counts"].get("timeout"), 2
            )
            self.assertEqual(agg["data_quality"]["timeout_count"], 2)


class TestParsesJSONLRows(unittest.TestCase):
    def test_parses_jsonl_row_counts(self):
        from analyze_vgc2026_team_preview_dataset_quality import (
            _load_jsonl, _aggregate,
        )
        with tempfile.TemporaryDirectory() as tmp:
            jsonl_path = os.path.join(tmp, "test.jsonl")
            rows = [
                {
                    "pair_id": 0, "side": "p1",
                    "our_policy": "learned_preview_v3c1",
                    "opponent_policy": "matchup_top4_v3",
                    "status": "ok", "our_win": True,
                    "our_chosen_4": ["a", "b", "c", "d"],
                },
                {
                    "pair_id": 0, "side": "p2",
                    "our_policy": "matchup_top4_v3",
                    "opponent_policy": "learned_preview_v3c1",
                    "status": "ok", "our_win": False,
                    "our_chosen_4": ["e", "f", "g", "h"],
                },
            ]
            _write_jsonl(jsonl_path, rows)
            jsonl_rows, _, _ = _load_jsonl(jsonl_path)
            agg = _aggregate(
                [], jsonl_rows, None, None, jsonl_path, None
            )
            self.assertEqual(agg["data_quality"]["jsonl_rows"], 2)
            self.assertEqual(agg["pair_integrity"]["complete_pairs"], 1)
            self.assertEqual(agg["pair_integrity"]["valid_pairs"], 1)


class TestHandlesMalformedJSONL(unittest.TestCase):
    def test_handles_malformed_jsonl_line(self):
        from analyze_vgc2026_team_preview_dataset_quality import (
            _load_jsonl, _aggregate,
        )
        with tempfile.TemporaryDirectory() as tmp:
            jsonl_path = os.path.join(tmp, "test.jsonl")
            with open(jsonl_path, "w") as f:
                f.write(
                    '{"pair_id": 0, "side": "p1", "status": "ok", '
                    '"our_win": true, "our_chosen_4": ["a", "b", "c", "d"]}\n'
                )
                f.write("this is not valid json\n")
                f.write(
                    '{"pair_id": 0, "side": "p2", "status": "ok", '
                    '"our_win": false, "our_chosen_4": ["e", "f", "g", "h"]}\n'
                )
            jsonl_rows, errors, total = _load_jsonl(jsonl_path)
            self.assertEqual(len(jsonl_rows), 2)
            self.assertEqual(errors, 1)
            self.assertEqual(total, 3)
            agg = _aggregate(
                [], jsonl_rows, None, None, jsonl_path, None
            )
            self.assertEqual(agg["data_quality"]["jsonl_rows"], 2)


class TestCompletePairs(unittest.TestCase):
    def test_computes_complete_pairs(self):
        from analyze_vgc2026_team_preview_dataset_quality import (
            _aggregate,
        )
        rows = [
            {"pair_id": 0, "side": "p1", "status": "ok",
             "our_win": True,
             "our_chosen_4": ["a", "b", "c", "d"]},
            {"pair_id": 0, "side": "p2", "status": "ok",
             "our_win": False,
             "our_chosen_4": ["e", "f", "g", "h"]},
            {"pair_id": 1, "side": "p1", "status": "ok",
             "our_win": False,
             "our_chosen_4": ["i", "j", "k", "l"]},
            # pair 1 missing p2
        ]
        agg = _aggregate([], rows, None, None, None, None)
        self.assertEqual(agg["pair_integrity"]["total_rows"], 3)
        self.assertEqual(agg["pair_integrity"]["complete_pairs"], 1)
        self.assertEqual(agg["pair_integrity"]["missing_d2_count"], 1)


class TestDuplicateBattleTags(unittest.TestCase):
    def test_detects_duplicate_battle_tags(self):
        from analyze_vgc2026_team_preview_dataset_quality import (
            _aggregate,
        )
        rows = [
            {"pair_id": 0, "side": "p1", "status": "ok",
             "our_win": True, "battle_tag": "battle-001-p1",
             "our_chosen_4": ["a", "b", "c", "d"]},
            {"pair_id": 0, "side": "p2", "status": "ok",
             "our_win": False, "battle_tag": "battle-001-p1",  # dup
             "our_chosen_4": ["e", "f", "g", "h"]},
        ]
        agg = _aggregate([], rows, None, None, None, None)
        self.assertEqual(agg["pair_integrity"]["duplicate_battle_tags"], 1)


class TestWinCounts(unittest.TestCase):
    def test_computes_learned_baseline_wins(self):
        from analyze_vgc2026_team_preview_dataset_quality import (
            _aggregate,
        )
        rows = [
            {"pair_id": 0, "side": "p1",
             "our_policy": "learned_preview_v3c1",
             "opponent_policy": "matchup_top4_v3",
             "status": "ok", "our_win": True,
             "our_chosen_4": ["a", "b", "c", "d"]},
            {"pair_id": 0, "side": "p2",
             "our_policy": "matchup_top4_v3",
             "opponent_policy": "learned_preview_v3c1",
             "status": "ok", "our_win": False,
             "our_chosen_4": ["e", "f", "g", "h"]},
            {"pair_id": 1, "side": "p1",
             "our_policy": "learned_preview_v3c1",
             "opponent_policy": "matchup_top4_v3",
             "status": "ok", "our_win": False,
             "our_chosen_4": ["a", "b", "c", "d"]},
            {"pair_id": 1, "side": "p2",
             "our_policy": "matchup_top4_v3",
             "opponent_policy": "learned_preview_v3c1",
             "status": "ok", "our_win": True,
             "our_chosen_4": ["e", "f", "g", "h"]},
        ]
        agg = _aggregate([], rows, None, None, None, None)
        # Pair 0: learned wins (p1 wins). Pair 1: baseline wins (p2 wins).
        self.assertEqual(agg["outcome_quality"]["learned_both"], 1)
        self.assertEqual(agg["outcome_quality"]["baseline_both"], 1)
        self.assertEqual(agg["outcome_quality"]["split"], 0)
        self.assertEqual(agg["outcome_quality"]["learned_wins"], 1)
        self.assertEqual(agg["outcome_quality"]["baseline_wins"], 1)


class TestUniqueSelected4(unittest.TestCase):
    def test_computes_unique_selected_4(self):
        from analyze_vgc2026_team_preview_dataset_quality import (
            _aggregate,
        )
        rows = [
            {"pair_id": 0, "side": "p1", "status": "ok",
             "our_win": True,
             "our_chosen_4": ["a", "b", "c", "d"]},
            {"pair_id": 0, "side": "p2", "status": "ok",
             "our_win": False,
             "our_chosen_4": ["e", "f", "g", "h"]},
            {"pair_id": 1, "side": "p1", "status": "ok",
             "our_win": True,
             "our_chosen_4": ["a", "b", "c", "d"]},  # dup
            {"pair_id": 1, "side": "p2", "status": "ok",
             "our_win": False,
             "our_chosen_4": ["e", "f", "g", "h"]},  # dup
        ]
        agg = _aggregate([], rows, None, None, None, None)
        self.assertEqual(agg["preview_plan_quality"]["unique_selected_4"], 2)
        self.assertEqual(agg["leakage_risk"]["duplicate_selected_4_rows"], 2)


class TestPlanEntropy(unittest.TestCase):
    def test_computes_plan_entropy(self):
        from analyze_vgc2026_team_preview_dataset_quality import (
            _aggregate,
        )
        rows = [
            {"pair_id": i, "side": "p1", "status": "ok",
             "our_win": True,
             "our_chosen_4": ["a", "b", "c", "d"]}
            for i in range(10)
        ]
        agg = _aggregate([], rows, None, None, None, None)
        # All same plan = 0 entropy.
        self.assertEqual(agg["preview_plan_quality"]["selected_4_entropy"], 0.0)


class TestModelParsing(unittest.TestCase):
    def test_parses_model_feature_count_and_weights(self):
        from analyze_vgc2026_team_preview_dataset_quality import (
            _aggregate,
        )
        model = _make_model(
            feature_names=["a", "b", "c"],
            weights={"a": 0.5, "b": -0.3, "c": 0.0},
        )
        agg = _aggregate([], [], model, None, None, None)
        self.assertEqual(agg["feature_model_quality"]["feature_count"], 3)
        self.assertEqual(agg["feature_model_quality"]["nonzero_weight_count"], 2)


class TestTopWeights(unittest.TestCase):
    def test_identifies_top_positive_negative_weights(self):
        from analyze_vgc2026_team_preview_dataset_quality import (
            _aggregate,
        )
        model = _make_model(
            feature_names=["a", "b", "c", "d"],
            weights={"a": 0.5, "b": -0.3, "c": 0.2, "d": -0.8},
        )
        agg = _aggregate([], [], model, None, None, None)
        top_pos = agg["feature_model_quality"]["top_positive_weights"]
        self.assertEqual(top_pos[0]["feature"], "a")
        top_neg = agg["feature_model_quality"]["top_negative_weights"]
        self.assertEqual(top_neg[0]["feature"], "d")


class TestHiddenInfoFeatureFlag(unittest.TestCase):
    def test_flags_suspicious_hidden_info_features(self):
        from analyze_vgc2026_team_preview_dataset_quality import (
            _aggregate,
        )
        model = _make_model(
            feature_names=["back_coverage_count", "hidden_opp_item",
                          "outcome_score", "lead_def_mean_threat"],
            weights={"back_coverage_count": 0.1,
                     "hidden_opp_item": 0.2,
                     "outcome_score": 0.3,
                     "lead_def_mean_threat": 0.4},
        )
        agg = _aggregate([], [], model, None, None, None)
        suspicious = agg["feature_model_quality"]["suspicious_feature_names"]
        self.assertIn("hidden_opp_item", suspicious)
        self.assertIn("outcome_score", suspicious)


class TestWritesMarkdown(unittest.TestCase):
    def test_writes_markdown_report(self):
        from analyze_vgc2026_team_preview_dataset_quality import (
            main,
        )
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "test.csv")
            model_path = os.path.join(tmp, "model.json")
            md = os.path.join(tmp, "r.md")
            row = _make_csv_row(0, "p1", our_chosen_4=["a", "b", "c", "d"])
            _write_csv(csv_path, [row])
            with open(model_path, "w") as f:
                json.dump(_make_model(), f)
            sys.argv = [
                "analyzer",
                "--csv", csv_path,
                "--model", model_path,
                "--md", md,
            ]
            main()
            with open(md) as f:
                content = f.read()
            self.assertIn("# Phase RL-2", content)
            self.assertIn("## TL;DR", content)
            self.assertIn("## Inputs", content)
            self.assertIn("## Data Quality", content)
            self.assertIn("## Pair Integrity", content)
            self.assertIn("## Preview Plan Quality", content)
            self.assertIn("## Outcome / Label Quality", content)
            self.assertIn("## Leakage and Duplicate Risk", content)
            self.assertIn("## Feature / Model Quality", content)
            self.assertIn("## RL Readiness", content)
            self.assertIn("## Recommendations", content)
            self.assertIn("## Limitations", content)


class TestWritesJSON(unittest.TestCase):
    def test_writes_json_summary(self):
        from analyze_vgc2026_team_preview_dataset_quality import (
            main,
        )
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "test.csv")
            md = os.path.join(tmp, "r.md")
            json_path = os.path.join(tmp, "s.json")
            row = _make_csv_row(0, "p1", our_chosen_4=["a", "b", "c", "d"])
            _write_csv(csv_path, [row])
            sys.argv = [
                "analyzer", "--csv", csv_path,
                "--md", md, "--json", json_path,
            ]
            main()
            with open(json_path) as f:
                summary = json.load(f)
            for key in [
                "data_quality", "pair_integrity",
                "preview_plan_quality", "outcome_quality",
                "leakage_risk", "feature_model_quality",
                "rl_readiness", "recommendations",
            ]:
                self.assertIn(key, summary)


if __name__ == "__main__":
    unittest.main()