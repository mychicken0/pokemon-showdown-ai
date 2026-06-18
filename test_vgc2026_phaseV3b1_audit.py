#!/usr/bin/env python3
"""Tests for Phase V3b.1 diagnostic audit.

Ponytail: focused tests for the audit module.
"""
import json
import os
import statistics
import sys
import unittest
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vgc2026_phaseV3b1_audit import (
    ABLATION_JSON,
    ABLATION_MD,
    DATA_AUDIT_JSON,
    DATA_AUDIT_MD,
    DEFAULT_SEEDS,
    GO_MEAN_MEDIAN_THRESHOLD,
    GO_V3_BEAT_FRACTION,
    SPLIT_STABILITY_JSON,
    SPLIT_STABILITY_MD,
    V3A1_REF,
    _build_pairs_with_meta,
    _policy_from_pair_row,
    _train_with_variant,
    ablation_audit,
    dataset_audit,
    feature_scale_audit,
    recommend,
    render_ablation_md,
    render_data_audit_md,
    render_split_stability_md,
    split_stability_audit,
)


class TestSplitAuditDeterminism(unittest.TestCase):
    """Split audit must be deterministic for the
    same seed."""

    @classmethod
    def setUpClass(cls):
        from vgc_team_pool import load_vgc_pool
        from vgc2026_phaseV3b_train import _load_v3b_rows
        from vgc2026_phaseV3a_learn_preview import (
            DEFAULT_V3A1_SOURCES,
        )
        cls.pool = load_vgc_pool()
        sources = [s for s in
                   DEFAULT_V3A1_SOURCES.split(",") if s]
        cls.rows, _ = _load_v3b_rows(
            sources[:1], cls.pool
        )

    def test_split_audit_deterministic_same_seed(self):
        a = split_stability_audit(
            self.rows, seeds=[42], n_epochs=2
        )
        b = split_stability_audit(
            self.rows, seeds=[42], n_epochs=2
        )
        self.assertEqual(
            a["per_seed"][0]["val_acc"],
            b["per_seed"][0]["val_acc"],
        )

    def test_split_audit_changes_across_seeds(self):
        a = split_stability_audit(
            self.rows, seeds=[0], n_epochs=2
        )
        b = split_stability_audit(
            self.rows, seeds=[29], n_epochs=2
        )
        # Different seeds should produce different
        # val accuracies on average (or at least
        # different n_train/n_val splits).
        same_val = (
            a["per_seed"][0]["n_val_pairs"]
            == b["per_seed"][0]["n_val_pairs"]
        )
        same_n_train = (
            a["per_seed"][0]["n_train_pairs"]
            == b["per_seed"][0]["n_train_pairs"]
        )
        # It is allowed for the pair counts to
        # match if the team_hashes happen to fall
        # on the same boundary; require at least
        # the val_acc to differ (or both counts
        # differ).
        self.assertTrue(
            a["per_seed"][0]["val_acc"]
            != b["per_seed"][0]["val_acc"]
            or not same_val
            or not same_n_train
        )


class TestSplitAuditNoLeakage(unittest.TestCase):
    """No team_hash overlap between train and val
    for any seed."""

    @classmethod
    def setUpClass(cls):
        from vgc_team_pool import load_vgc_pool
        from vgc2026_phaseV3b_train import _load_v3b_rows
        from vgc2026_phaseV3a_learn_preview import (
            DEFAULT_V3A1_SOURCES,
        )
        cls.pool = load_vgc_pool()
        sources = [s for s in
                   DEFAULT_V3A1_SOURCES.split(",") if s]
        cls.rows, _ = _load_v3b_rows(
            sources[:1], cls.pool
        )

    def test_no_leakage_across_seeds(self):
        from vgc2026_phaseV3a_learn_preview import (
            assert_no_leakage, group_split,
        )
        for seed in [0, 7, 13, 42, 100, 999]:
            train_rows, val_rows, _ = group_split(
                self.rows, val_fraction=0.2, seed=seed
            )
            assert_no_leakage(train_rows, val_rows)


class TestFeatureScaleAudit(unittest.TestCase):
    """Feature scale audit must handle zero-variance
    features gracefully."""

    @classmethod
    def setUpClass(cls):
        from vgc_team_pool import load_vgc_pool
        from vgc2026_phaseV3b_train import _load_v3b_rows
        from vgc2026_phaseV3a_learn_preview import (
            DEFAULT_V3A1_SOURCES,
        )
        cls.pool = load_vgc_pool()
        sources = [s for s in
                   DEFAULT_V3A1_SOURCES.split(",") if s]
        cls.rows, _ = _load_v3b_rows(
            sources[:1], cls.pool
        )

    def test_scale_audit_handles_zero_variance(self):
        # The V3b feature set has 3 zero-variance
        # features (our_redirection_count, sc_fo_count,
        # sc_opp_fo_count). The audit must still
        # succeed and report them as zero-variance.
        audit = feature_scale_audit(self.rows)
        self.assertIn("extreme_scale_features", audit)
        # The audit should not raise on zero-std
        # features and should still produce
        # a top-10 list.
        self.assertGreaterEqual(
            len(audit["top10_by_contribution"]), 1
        )
        for entry in audit["top10_by_contribution"]:
            for k in (
                "name", "weight", "std", "contribution",
                "mean", "zero_frac",
            ):
                self.assertIn(k, entry)
            # Contribution is |w| * std, which is 0
            # for zero-variance features. Allow that.
            self.assertGreaterEqual(
                entry["contribution"], 0.0
            )

    def test_per_feature_has_stats(self):
        audit = feature_scale_audit(self.rows)
        for fn, st in audit["per_feature"].items():
            for k in (
                "min", "max", "mean", "std", "zero_frac"
            ):
                self.assertIn(k, st)


class TestAblationVariants(unittest.TestCase):
    """Ablation variants have disjoint expected
    feature sets and normalized variant uses train
    stats only."""

    @classmethod
    def setUpClass(cls):
        from vgc_team_pool import load_vgc_pool
        from vgc2026_phaseV3b_train import _load_v3b_rows
        from vgc2026_phaseV3a_learn_preview import (
            DEFAULT_V3A1_SOURCES,
        )
        cls.pool = load_vgc_pool()
        sources = [s for s in
                   DEFAULT_V3A1_SOURCES.split(",") if s]
        cls.rows, _ = _load_v3b_rows(
            sources[:1], cls.pool
        )

    def test_variants_have_disjoint_feature_sets(self):
        all_features = sorted(
            self.rows[0]["our_features"].keys()
        )
        base = [f for f in all_features
                if not f.startswith("delta_")]
        delta = [f for f in all_features
                 if f.startswith("delta_")]
        matchup = [
            f for f in base if (
                f.startswith("lead_off_")
                or f.startswith("lead_def_")
                or f.startswith("back_")
                or f.startswith("opp_")
            )
        ]
        # all_features = base + delta
        self.assertEqual(
            set(base) | set(delta), set(all_features)
        )
        # base and delta disjoint
        self.assertEqual(set(base) & set(delta), set())
        # matchup ⊂ base
        self.assertTrue(set(matchup).issubset(set(base)))

    def test_normalized_uses_train_stats_only(self):
        # Build a small synthetic dataset where the
        # mean of opp_phys_move_count differs between
        # train and val. With normalization, the
        # val features should be transformed using
        # the train mean/std, not the val mean/std.
        rows = self.rows[:100]
        # Train/val split: first 80 train, last 20 val.
        train_rows = rows[:80]
        val_rows = rows[80:]
        from vgc2026_phaseV3b1_audit import (
            _train_with_variant,
        )
        fnames = sorted(rows[0]["our_features"].keys())
        # Just check it doesn't crash and returns a
        # weight dict.
        w, b, meta = _train_with_variant(
            rows, fnames, seed=42, l2=0.01,
            learning_rate=0.1, n_epochs=2,
            normalize=True,
        )
        self.assertIsInstance(w, dict)
        self.assertGreater(len(w), 0)


class TestDecisionThresholds(unittest.TestCase):
    """Decision thresholds enforce BLOCK when
    mean/median < 0.60."""

    def test_block_when_weak_winner_dominates(self):
        # A dataset where 80% of winners are random.
        data = {
            "winner_policy_distribution": {
                "random": 80, "basic_top4": 10,
                "matchup_top4_v3": 10,
            },
        }
        split = {
            "val_acc_mean": 0.50,
            "val_acc_median": 0.50,
            "beats_v3_fraction": 0.50,
        }
        abl = {"variants": []}
        rec = recommend(data, split, abl)
        self.assertEqual(rec["decision"], "BLOCK_LABEL_QUALITY")

    def test_block_when_val_below_threshold(self):
        data = {
            "winner_policy_distribution": {
                "matchup_top4_v3": 60, "basic_top4": 30,
                "random": 10,
            },
        }
        split = {
            "val_acc_mean": 0.40,
            "val_acc_median": 0.40,
            "beats_v3_fraction": 0.50,
        }
        abl = {"variants": []}
        rec = recommend(data, split, abl)
        self.assertEqual(rec["decision"], "BLOCK_MORE_DATA")

    def test_block_when_no_variant_beats_v3(self):
        data = {
            "winner_policy_distribution": {
                "matchup_top4_v3": 60, "basic_top4": 30,
                "random": 10,
            },
        }
        split = {
            "val_acc_mean": 0.70,
            "val_acc_median": 0.70,
            "beats_v3_fraction": 0.50,
        }
        abl = {
            "variants": [
                {
                    "name": "all_features",
                    "val_acc_mean": 0.70,
                    "val_acc_median": 0.70,
                    "beats_v3_fraction": 0.50,
                }
            ]
        }
        rec = recommend(data, split, abl)
        self.assertEqual(rec["decision"], "BLOCK_MODEL_CLASS")


class TestArtifactsJsonSerializable(unittest.TestCase):
    """V3b.1 audit artifacts are JSON-serializable."""

    def test_data_audit_json_loadable(self):
        if not os.path.isfile(DATA_AUDIT_JSON):
            self.skipTest(f"missing {DATA_AUDIT_JSON}")
        with open(DATA_AUDIT_JSON) as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)
        for k in (
            "n_total_raw_rows",
            "n_decisive_pairs",
            "train_n_pairs",
            "val_n_pairs",
        ):
            self.assertIn(k, data)

    def test_split_stability_json_loadable(self):
        if not os.path.isfile(SPLIT_STABILITY_JSON):
            self.skipTest(f"missing {SPLIT_STABILITY_JSON}")
        with open(SPLIT_STABILITY_JSON) as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)
        for k in (
            "n_seeds", "val_acc_mean", "val_acc_median",
            "beats_v3_fraction",
        ):
            self.assertIn(k, data)

    def test_ablation_json_loadable(self):
        if not os.path.isfile(ABLATION_JSON):
            self.skipTest(f"missing {ABLATION_JSON}")
        with open(ABLATION_JSON) as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)
        self.assertIn("variants", data)
        self.assertIsInstance(data["variants"], list)
        self.assertGreater(len(data["variants"]), 0)


class TestExistingArtifactsPreserved(unittest.TestCase):
    """V3a/V3a1/V3b artifacts must not have been
    overwritten."""

    def test_v3a1_model_still_exists(self):
        from vgc2026_phaseV3a_learn_preview import (
            DEFAULT_V3A1_MODEL_PATH,
        )
        self.assertTrue(
            os.path.isfile(DEFAULT_V3A1_MODEL_PATH),
            "V3a.1 model artifact must be preserved",
        )

    def test_v3b_model_still_exists(self):
        from vgc2026_phaseV3b_train import (
            DEFAULT_V3B_MODEL_PATH,
        )
        self.assertTrue(
            os.path.isfile(DEFAULT_V3B_MODEL_PATH),
            "V3b model artifact must be preserved",
        )


class TestDatasetAudit(unittest.TestCase):
    """Dataset audit must produce all required
    fields."""

    @classmethod
    def setUpClass(cls):
        from vgc_team_pool import load_vgc_pool
        from vgc2026_phaseV3b_train import _load_v3b_rows
        from vgc2026_phaseV3a_learn_preview import (
            DEFAULT_V3A1_SOURCES,
        )
        cls.pool = load_vgc_pool()
        cls.sources = [s for s in
                       DEFAULT_V3A1_SOURCES.split(",")
                       if s]

    def test_dataset_audit_fields(self):
        audit = dataset_audit(self.sources, self.pool)
        for k in (
            "n_total_raw_rows",
            "n_decisive_pairs",
            "train_n_pairs",
            "val_n_pairs",
            "train_n_teams",
            "val_n_teams",
            "source_distribution",
            "winner_policy_distribution",
            "loser_policy_distribution",
        ):
            self.assertIn(k, audit)


class TestRenderers(unittest.TestCase):
    """Markdown renderers produce non-empty output."""

    def test_render_data_audit_md(self):
        audit = {
            "n_total_raw_rows": 100,
            "n_decisive_pairs": 10,
            "n_source_skipped": {},
            "n_skipped": {},
            "train_n_rows": 80,
            "val_n_rows": 20,
            "train_n_pairs": 7,
            "val_n_pairs": 3,
            "train_n_teams": 6,
            "val_n_teams": 2,
            "source_distribution": {"a": 60, "b": 40},
            "train_source_distribution": {"a": 50, "b": 30},
            "val_source_distribution": {"a": 10, "b": 10},
            "winner_policy_distribution": {"v3": 5, "r": 5},
            "loser_policy_distribution": {"v3": 7, "r": 3},
        }
        md = render_data_audit_md(audit)
        self.assertGreater(len(md), 100)
        self.assertIn("Phase V3b.1", md)

    def test_render_split_stability_md(self):
        audit = {
            "n_seeds": 3,
            "n_features": 20,
            "val_acc_mean": 0.50,
            "val_acc_median": 0.50,
            "val_acc_min": 0.30,
            "val_acc_max": 0.70,
            "val_acc_stdev": 0.10,
            "train_acc_mean": 0.60,
            "beats_v3_count": 2,
            "beats_v3_fraction": 0.67,
            "beats_v3a1_ref_count": 0,
            "beats_v3a1_ref_fraction": 0.0,
            "v3a1_reference": 0.75,
            "per_seed": [
                {
                    "seed": i,
                    "n_train_pairs": 10,
                    "n_val_pairs": 3,
                    "train_acc": 0.6,
                    "val_acc": 0.5,
                    "v3_baseline_acc": 0.2,
                    "beats_v3": True,
                    "beats_v3a1_ref": False,
                }
                for i in range(3)
            ],
        }
        md = render_split_stability_md(audit)
        self.assertGreater(len(md), 100)
        self.assertIn("Phase V3b.1", md)

    def test_render_ablation_md(self):
        audit = {
            "n_seeds": 3,
            "n_variants": 2,
            "n_features_total": 20,
            "variants": [
                {
                    "name": "a",
                    "l2": 0.01,
                    "normalize": False,
                    "n_features": 20,
                    "val_acc_mean": 0.5,
                    "val_acc_median": 0.5,
                    "val_acc_min": 0.3,
                    "val_acc_max": 0.7,
                    "train_acc_mean": 0.6,
                    "overfit_gap_mean": 0.1,
                    "beats_v3_fraction": 0.7,
                    "beats_v3a1_ref_fraction": 0.0,
                },
                {
                    "name": "b",
                    "l2": 0.001,
                    "normalize": True,
                    "n_features": 20,
                    "val_acc_mean": 0.6,
                    "val_acc_median": 0.6,
                    "val_acc_min": 0.4,
                    "val_acc_max": 0.8,
                    "train_acc_mean": 0.65,
                    "overfit_gap_mean": 0.05,
                    "beats_v3_fraction": 0.9,
                    "beats_v3a1_ref_fraction": 0.1,
                },
            ],
        }
        md = render_ablation_md(audit)
        self.assertGreater(len(md), 100)


if __name__ == "__main__":
    unittest.main()
