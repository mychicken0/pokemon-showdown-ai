"""Phase RL-DATA-3f — Tests for BC dry-run analysis.

Validates the BC dry-run analysis script's:

* Feature extraction excludes leakage fields.
* Label extraction works for setup / weather / support
  / protect / attack / switch / pass.
* Majority baseline works.
* Legal heuristic baseline works.
* Score baseline unavailable path works.
* BC fallback path works.
* Metrics handle missing minority classes.
* Confusion matrix handles zero counts safely.
* No model artifact is written.
* Empty dataset handled gracefully.

Coverage:
- ``extract_features`` excludes all LEAKAGE_FIELDS
- ``extract_labels`` returns the correct primary /
  slot0 / slot1 labels
- ``majority_baseline`` predicts the most common
  label and reports accuracy
- ``legal_heuristic_baseline`` works
- ``score_baseline`` handles missing scores
- ``_NaiveBayesClassifier`` trains and predicts
- ``_per_class_metrics`` handles zero counts
- ``_confusion_matrix`` handles zero counts
- ``bc_model_dryrun`` works on a small synthetic
  dataset
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from typing import Any, Dict, List

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(
    0, os.path.join(
        os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ),
        "scripts",
        "analyze",
    )
)

from analyze_rl_data_3f_bc_dryrun import (  # noqa: E402
    LEAKAGE_FIELDS,
    _NaiveBayesClassifier,
    _accuracy,
    _classify_action_kind_label,
    _confusion_matrix,
    _legal_counts,
    _legal_signature,
    _per_class_metrics,
    _safe_div,
    _to_bool_features,
    analyze_dataset,
    bc_model_dryrun,
    extract_features,
    extract_labels,
    legal_heuristic_baseline,
    majority_baseline,
    score_baseline,
)


# ============================================================
# extract_features — leakage exclusion
# ============================================================
class TestExtractFeaturesLeakage(unittest.TestCase):
    """Verify feature extraction excludes leakage fields."""

    def test_leakage_fields_excluded(self):
        # Build a row with a leakage field
        row = {
            "legal_action_keys_slot0": [
                ["move", "moonblast", 0, ""]
            ],
            "legal_action_keys_slot1": [
                ["move", "hydropump", 0, ""]
            ],
            "selected_joint_key": [
                ["move", "moonblast", 0, ""],
                ["move", "hydropump", 0, ""],
            ],
            "selected_score": 100.0,
            "terminal_win_loss": 1,
            "won": True,
            "faint_caused": 0,
            "turn_delta_hp": {"side_a": -50, "side_b": -100},
            "used_species_ability_inference": False,
            "dataset_source": "rl_data_3c_default",
            "state_snapshot": {
                "weather": "raindance",
                "fields": [],
            },
        }
        feats, leakage = extract_features(
            row, include_exploration_features=False
        )
        # Leakage fields should be reported
        self.assertIn("selected_joint_key", leakage)
        self.assertIn("selected_score", leakage)
        self.assertIn("terminal_win_loss", leakage)
        self.assertIn("won", leakage)
        # But they should NOT appear in the features
        self.assertNotIn("selected_joint_key", feats)
        self.assertNotIn("selected_score", feats)
        self.assertNotIn("terminal_win_loss", feats)
        self.assertNotIn("won", feats)
        self.assertNotIn("turn_delta_hp", feats)
        self.assertNotIn("faint_caused", feats)
        # Legal features should be present
        self.assertIn("has_legal_attack_slot0", feats)
        self.assertIn("has_legal_attack_slot1", feats)

    def test_exploration_features_excluded_by_default(self):
        row = {
            "legal_action_keys_slot0": [["move", "moonblast", 0, ""]],
            "legal_action_keys_slot1": [],
            "dataset_source": "rl_data_3e_exploration",
            "exploration_enabled": True,
            "exploration_candidate_group": "setup_stat_boost",
        }
        feats, leakage = extract_features(
            row, include_exploration_features=False
        )
        # Exploration features should be in leakage
        # (not used as features by default).
        self.assertIn("dataset_source", leakage)
        self.assertIn("exploration_enabled", leakage)
        # But they should NOT appear in the features
        self.assertNotIn("dataset_source", feats)
        self.assertNotIn("exploration_enabled", feats)

    def test_exploration_features_when_enabled(self):
        row = {
            "legal_action_keys_slot0": [["move", "moonblast", 0, ""]],
            "legal_action_keys_slot1": [],
            "dataset_source": "rl_data_3e_exploration",
            "exploration_triggered": True,
            "exploration_candidate_group": "setup_stat_boost",
        }
        feats, leakage = extract_features(
            row, include_exploration_features=True
        )
        # When enabled, exploration features should be
        # present in the features.
        self.assertIn("exploration_triggered", feats)
        self.assertIn("dataset_source_3e", feats)
        self.assertIn("dataset_source_3c", feats)


# ============================================================
# extract_labels
# ============================================================
class TestExtractLabels(unittest.TestCase):
    """Verify label extraction for all action kinds."""

    def test_double_attack(self):
        row = {
            "selected_joint_key": [
                ["move", "moonblast", 0, ""],
                ["move", "hydropump", 0, ""],
            ],
        }
        labels = extract_labels(row)
        self.assertEqual(labels["primary"], "double_attack")
        self.assertEqual(labels["slot0"], "attack")
        self.assertEqual(labels["slot1"], "attack")

    def test_attack_plus_protect(self):
        row = {
            "selected_joint_key": [
                ["move", "moonblast", 0, ""],
                ["move", "protect", 1, ""],
            ],
        }
        labels = extract_labels(row)
        self.assertEqual(labels["primary"], "attack_plus_protect")
        self.assertEqual(labels["slot0"], "attack")
        self.assertEqual(labels["slot1"], "protect")

    def test_attack_plus_setup(self):
        row = {
            "selected_joint_key": [
                ["move", "moonblast", 0, ""],
                ["move", "quiverdance", 1, ""],
            ],
        }
        labels = extract_labels(row)
        self.assertEqual(labels["primary"], "attack_plus_setup")
        self.assertEqual(labels["slot1"], "setup")

    def test_attack_plus_weather_setter(self):
        row = {
            "selected_joint_key": [
                ["move", "moonblast", 0, ""],
                ["move", "raindance", 1, ""],
            ],
        }
        labels = extract_labels(row)
        self.assertEqual(labels["primary"], "attack_plus_weather_setter")
        self.assertEqual(labels["slot1"], "weather_setter")

    def test_double_switch(self):
        row = {
            "selected_joint_key": [
                ["switch", "volcarona", 0, ""],
                ["switch", "garchomp", 0, ""],
            ],
        }
        labels = extract_labels(row)
        self.assertEqual(labels["primary"], "double_switch")
        self.assertEqual(labels["slot0"], "switch")
        self.assertEqual(labels["slot1"], "switch")

    def test_single_move_plus_pass(self):
        row = {
            "selected_joint_key": [
                ["move", "moonblast", 0, ""],
                ["pass", "pass", 0, ""],
            ],
        }
        labels = extract_labels(row)
        self.assertEqual(labels["primary"], "single_move_plus_pass")
        self.assertEqual(labels["slot0"], "attack")
        self.assertEqual(labels["slot1"], "pass")


# ============================================================
# _classify_action_kind_label
# ============================================================
class TestClassifyActionKindLabel(unittest.TestCase):
    """Verify single-move label classification."""

    def test_damaging(self):
        self.assertEqual(
            _classify_action_kind_label("moonblast", "move"),
            "attack"
        )
        self.assertEqual(
            _classify_action_kind_label("fakeout", "move"),
            "attack"
        )

    def test_setup(self):
        self.assertEqual(
            _classify_action_kind_label("quiverdance", "move"),
            "setup"
        )
        self.assertEqual(
            _classify_action_kind_label("swordsdance", "move"),
            "setup"
        )

    def test_weather_setter(self):
        self.assertEqual(
            _classify_action_kind_label("raindance", "move"),
            "weather_setter"
        )

    def test_terrain_setter(self):
        # Note: the 3d script's _is_weather_setter
        # includes terrain setters (electricterrain,
        # grassyterrain, etc.) so the weather check
        # fires first. The 3f script uses the 3d
        # helper, so terrain setters are classified as
        # "weather_setter" by the existing 3d logic.
        # This test documents the current behavior.
        self.assertEqual(
            _classify_action_kind_label("electricterrain", "move"),
            "weather_setter"
        )

    def test_protect(self):
        self.assertEqual(
            _classify_action_kind_label("protect", "move"),
            "protect"
        )

    def test_support_other(self):
        self.assertEqual(
            _classify_action_kind_label("helpinghand", "move"),
            "support_other"
        )
        self.assertEqual(
            _classify_action_kind_label("taunt", "move"),
            "support_other"
        )

    def test_switch(self):
        self.assertEqual(
            _classify_action_kind_label("volcarona", "switch"),
            "switch"
        )

    def test_pass(self):
        self.assertEqual(
            _classify_action_kind_label("/choose pass", "pass"),
            "pass"
        )


# ============================================================
# _legal_signature / _legal_counts
# ============================================================
class TestLegalSignatureAndCounts(unittest.TestCase):
    """Verify legal-action signature and counts."""

    def test_empty_legal(self):
        sig = _legal_signature([])
        self.assertFalse(sig["has_legal_attack"])
        self.assertFalse(sig["has_legal_protect"])
        self.assertFalse(sig["has_legal_switch"])
        counts = _legal_counts([])
        self.assertEqual(counts["attack"], 0)
        self.assertEqual(counts["n_legal_total"], 0)

    def test_mixed_legal(self):
        legal = [
            ["move", "moonblast", 0, ""],
            ["move", "protect", 0, ""],
            ["move", "quiverdance", 0, ""],
            ["switch", "volcarona", 0, ""],
        ]
        sig = _legal_signature(legal)
        self.assertTrue(sig["has_legal_attack"])
        self.assertTrue(sig["has_legal_protect"])
        self.assertTrue(sig["has_legal_setup"])
        self.assertTrue(sig["has_legal_switch"])
        counts = _legal_counts(legal)
        self.assertEqual(counts["attack"], 1)
        self.assertEqual(counts["protect"], 1)
        self.assertEqual(counts["setup"], 1)
        self.assertEqual(counts["switch"], 1)
        self.assertEqual(counts["n_legal_total"], 4)


# ============================================================
# Baselines
# ============================================================
class TestMajorityBaseline(unittest.TestCase):
    def test_majority_predicts_most_common(self):
        rows = [
            {"selected_joint_key": [["move", "a", 0, ""], ["move", "b", 0, ""]]},
            {"selected_joint_key": [["move", "a", 0, ""], ["move", "c", 0, ""]]},
            {"selected_joint_key": [["move", "a", 0, ""], ["move", "d", 0, ""]]},
            {"selected_joint_key": [["move", "x", 0, ""], ["move", "y", 0, ""]]},
        ]
        result = majority_baseline(rows, "primary")
        # Primary labels: "double_attack" for rows 1-3,
        # "double_attack" for row 4 (both are attacks).
        # Majority is "double_attack" with count 4.
        self.assertEqual(result["predicted"], "double_attack")
        self.assertEqual(result["count"], 4)
        self.assertEqual(result["accuracy"], 1.0)

    def test_empty_dataset(self):
        result = majority_baseline([], "primary")
        self.assertEqual(result["accuracy"], 0.0)
        self.assertEqual(result["predicted"], "none")


class TestLegalHeuristicBaseline(unittest.TestCase):
    def test_legal_heuristic_slot0(self):
        rows = [
            {
                "selected_joint_key": [
                    ["move", "moonblast", 0, ""],
                    ["move", "hydropump", 0, ""],
                ],
                "legal_action_keys_slot0": [
                    ["move", "moonblast", 0, ""],
                    ["move", "protect", 0, ""],
                ],
                "legal_action_keys_slot1": [
                    ["move", "hydropump", 0, ""],
                ],
            },
        ]
        result = legal_heuristic_baseline(rows, "slot0")
        # Heuristic: attack is legal -> predict "attack"
        self.assertEqual(result["accuracy"], 1.0)
        self.assertEqual(result["y_pred"], ["attack"])

    def test_legal_heuristic_primary(self):
        rows = [
            {
                "selected_joint_key": [
                    ["move", "moonblast", 0, ""],
                    ["move", "hydropump", 0, ""],
                ],
                "legal_action_keys_slot0": [
                    ["move", "moonblast", 0, ""],
                ],
                "legal_action_keys_slot1": [
                    ["move", "hydropump", 0, ""],
                ],
            },
        ]
        result = legal_heuristic_baseline(rows, "primary")
        # Both slots have attack -> predict "double_attack"
        self.assertEqual(result["y_pred"], ["double_attack"])


class TestScoreBaseline(unittest.TestCase):
    def test_score_baseline_slot0(self):
        rows = [
            {
                "selected_joint_key": [["move", "moonblast", 0, ""], []],
                "v2l1_raw_scores_slot0": {
                    "move|moonblast|0|": 100.0,
                    "move|tackle|0|": 50.0,
                },
                "v2l1_raw_scores_slot1": {},
                "legal_action_keys_slot0": [
                    ["move", "moonblast", 0, ""],
                    ["move", "tackle", 0, ""],
                ],
                "legal_action_keys_slot1": [],
            },
        ]
        result = score_baseline(rows, "slot0")
        # Max score is moonblast -> predict "attack"
        self.assertEqual(result["y_pred"], ["attack"])

    def test_score_baseline_unavailable(self):
        rows = [
            {
                "selected_joint_key": [["move", "moonblast", 0, ""], []],
                "v2l1_raw_scores_slot0": {},
                "v2l1_raw_scores_slot1": {},
                "legal_action_keys_slot0": [["move", "moonblast", 0, ""]],
                "legal_action_keys_slot1": [],
            },
        ]
        result = score_baseline(rows, "slot0")
        self.assertFalse(result["available"])


# ============================================================
# _NaiveBayesClassifier
# ============================================================
class TestNaiveBayesClassifier(unittest.TestCase):
    def test_train_and_predict(self):
        X = [
            {"f1": True, "f2": False},
            {"f1": True, "f2": False},
            {"f1": False, "f2": True},
            {"f1": False, "f2": True},
        ]
        y = ["a", "a", "b", "b"]
        clf = _NaiveBayesClassifier(alpha=1.0)
        clf.fit(X, y, ["f1", "f2"])
        preds = clf.predict([
            {"f1": True, "f2": False},
            {"f1": False, "f2": True},
        ])
        self.assertEqual(preds[0], "a")
        self.assertEqual(preds[1], "b")

    def test_alpha_smoothing(self):
        X = [
            {"f1": True, "f2": True},
        ]
        y = ["a"]
        clf = _NaiveBayesClassifier(alpha=2.0)
        clf.fit(X, y, ["f1", "f2"])
        # Predict with f1=False, f2=False
        preds = clf.predict([{"f1": False, "f2": False}])
        # Should not crash
        self.assertEqual(len(preds), 1)


# ============================================================
# Metrics
# ============================================================
class TestPerClassMetrics(unittest.TestCase):
    def test_basic_metrics(self):
        m = _per_class_metrics(
            ["a", "a", "b", "b"],
            ["a", "b", "b", "a"],
            ["a", "b"],
        )
        # Class a: tp=1, fp=1, fn=1
        # Class b: tp=1, fp=1, fn=1
        self.assertEqual(m["a"]["tp"], 1)
        self.assertEqual(m["a"]["fp"], 1)
        self.assertEqual(m["a"]["fn"], 1)
        self.assertEqual(m["a"]["precision"], 0.5)
        self.assertEqual(m["a"]["recall"], 0.5)
        self.assertEqual(m["a"]["f1"], 0.5)

    def test_zero_support_class(self):
        # Class "c" has no support
        m = _per_class_metrics(
            ["a", "a"],
            ["a", "a"],
            ["a", "b", "c"],
        )
        self.assertEqual(m["c"]["support"], 0)
        self.assertEqual(m["c"]["precision"], 0.0)
        self.assertEqual(m["c"]["recall"], 0.0)
        self.assertEqual(m["c"]["f1"], 0.0)


class TestConfusionMatrix(unittest.TestCase):
    def test_basic(self):
        cm = _confusion_matrix(
            ["a", "a", "b"],
            ["a", "b", "b"],
            ["a", "b"],
        )
        self.assertEqual(cm["a"]["a"], 1)
        self.assertEqual(cm["a"]["b"], 1)
        self.assertEqual(cm["b"]["b"], 1)
        self.assertEqual(cm["b"]["a"], 0)


class TestSafeDiv(unittest.TestCase):
    def test_zero_denominator(self):
        self.assertEqual(_safe_div(5, 0), 0.0)
        self.assertEqual(_safe_div(0, 0), 0.0)
        self.assertEqual(_safe_div(10, 2), 5.0)


# ============================================================
# bc_model_dryrun
# ============================================================
class TestBcModelDryrun(unittest.TestCase):
    def _make_rows(self, n: int, attack_rate: float = 0.8) -> List[Dict]:
        """Build a small synthetic dataset for BC testing."""
        rows = []
        for i in range(n):
            if i < int(n * attack_rate):
                sel0 = ["move", "moonblast", 0, ""]
                sel1 = ["move", "hydropump", 0, ""]
            else:
                # Protect instead of attack
                sel0 = ["move", "moonblast", 0, ""]
                sel1 = ["move", "protect", 0, ""]
            rows.append({
                "selected_joint_key": [sel0, sel1],
                "legal_action_keys_slot0": [
                    sel0,
                    ["move", "protect", 0, ""],
                ],
                "legal_action_keys_slot1": [
                    sel1,
                ],
            })
        return rows

    def test_bc_runs_and_returns_metrics(self):
        # Build a synthetic dataset where the label
        # depends on a feature (weather_current). This
        # gives the Naive Bayes classifier something
        # learnable.
        rows = []
        for i in range(200):
            # Alternate between two states with
            # distinct labels.
            if i % 2 == 0:
                sel0 = ["move", "raindance", 0, ""]
                sel1 = ["move", "moonblast", 0, ""]
                weather = "raindance"
            else:
                sel0 = ["move", "moonblast", 0, ""]
                sel1 = ["move", "moonblast", 0, ""]
                weather = "sunnyday"
            rows.append({
                "selected_joint_key": [sel0, sel1],
                "legal_action_keys_slot0": [
                    sel0,
                    ["move", "moonblast", 0, ""],
                ],
                "legal_action_keys_slot1": [
                    sel1,
                ],
                "state_snapshot": {
                    "weather": weather,
                    "fields": [],
                },
            })
        split = 160
        train = rows[:split]
        test = rows[split:]
        result = bc_model_dryrun(
            train, test, "slot0", seed=42
        )
        self.assertEqual(result["label_key"], "slot0")
        self.assertEqual(result["model_type"], "naive_bayes_no_dependency")
        self.assertFalse(result["model_artifact_saved"])
        self.assertFalse(result["scikit_learn_used"])
        # The model should learn the weather -> label
        # relationship. Accuracy should be > 0.5.
        self.assertGreater(result["accuracy"], 0.5)
        # Per-class metrics present
        self.assertIn("weather_setter", result["per_class_metrics"])
        self.assertIn("attack", result["per_class_metrics"])

    def test_bc_empty_handled(self):
        result = bc_model_dryrun([], [], "primary", seed=42)
        self.assertEqual(result["accuracy"], 0.0)
        self.assertEqual(result["n_train"], 0)
        self.assertEqual(result["n_test"], 0)


# ============================================================
# analyze_dataset (end-to-end)
# ============================================================
class TestAnalyzeDataset(unittest.TestCase):
    def test_synthetic_dataset_analysis(self):
        """Run the full analysis on a tiny synthetic
        dataset.
        """
        # Build 50 rows with a mix of attack and
        # attack+protect selections.
        rows = []
        for i in range(50):
            if i % 3 == 0:
                sel0 = ["move", "moonblast", 0, ""]
                sel1 = ["move", "protect", 1, ""]
            else:
                sel0 = ["move", "moonblast", 0, ""]
                sel1 = ["move", "hydropump", 0, ""]
            rows.append({
                "schema_version": "turn_rl_v1.1",
                "local_only_provenance": True,
                "used_species_ability_inference": False,
                "selected_joint_key": [sel0, sel1],
                "legal_action_keys_slot0": [
                    sel0,
                    ["move", "protect", 0, ""],
                ],
                "legal_action_keys_slot1": [
                    sel1,
                ],
                "v2l1_raw_scores_slot0": {
                    "move|moonblast|0|": 100.0,
                    "move|protect|0|": 50.0,
                },
                "v2l1_raw_scores_slot1": {
                    "move|hydropump|0|": 100.0,
                    "move|protect|1|": 50.0,
                },
                "state_snapshot": {
                    "weather": "raindance",
                    "fields": [],
                },
            })
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
            tmp_path = f.name
        try:
            result = analyze_dataset(
                tmp_path, "synthetic",
                include_exploration_features=False,
                seed=42,
            )
            self.assertEqual(result["n_rows"], 50)
            # Leakage is expected (the dataset has these
            # fields, but the feature extractor does not
            # use them).
            self.assertTrue(result["leakage_check"]["leakage_detected"])
            # All three label keys are present.
            for label_key in ("primary", "slot0", "slot1"):
                self.assertIn(label_key, result["bc_results"])
        finally:
            os.unlink(tmp_path)

    def test_empty_dataset(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            tmp_path = f.name
        try:
            result = analyze_dataset(
                tmp_path, "empty",
                include_exploration_features=False,
                seed=42,
            )
            self.assertEqual(result["n_rows"], 0)
            # No crash
            for label_key in ("primary", "slot0", "slot1"):
                self.assertIn(label_key, result["bc_results"])
        finally:
            os.unlink(tmp_path)


# ============================================================
# _to_bool_features
# ============================================================
class TestToBoolFeatures(unittest.TestCase):
    def test_conversion(self):
        feats = [{"a": 1, "b": "yes", "c": False}, {"a": 0, "b": "no"}]
        keys = ["a", "b", "c"]
        out = _to_bool_features(feats, keys)
        self.assertEqual(out[0], {"a": True, "b": True, "c": False})
        self.assertEqual(out[1], {"a": False, "b": True, "c": False})


# ============================================================
# LEAKAGE_FIELDS
# ============================================================
class TestLeakageFields(unittest.TestCase):
    def test_leakage_fields_set(self):
        # Spot-check that key leakage fields are in the
        # LEAKAGE_FIELDS set.
        for f in (
            "selected_joint_key", "selected_score",
            "terminal_win_loss", "won", "turn_delta_hp",
            "faint_caused", "faint_suffered",
            "used_species_ability_inference",
            "local_only_provenance", "dataset_source",
        ):
            self.assertIn(f, LEAKAGE_FIELDS)
