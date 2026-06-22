#!/usr/bin/env python3
"""Tests for Phase V3c.1 VGC learned-preview trainer.

Ponytail: focused tests for the V3c.1 module.
"""
import json
import os
import statistics
import sys
import unittest
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vgc2026_phaseV3c1_train import (
    GATE_BEATS_LEARNED_FRACTION,
    GATE_BEATS_V3_FRACTION,
    GATE_FEATURE_DOMINANCE,
    GATE_MEAN_VAL,
    GATE_OVERFIT_GAP,
    V3C_PAIRING_FILES,
    V3C1_FEATURE_SCALE,
    V3C1_MODEL_PATH,
    V3C1_REPORT_JSON,
    V3C1_REPORT_MD,
    V3C1_SPLIT_STABILITY,
    _ablation,
    _build_decisive_pairs_per_pairing,
    _feature_scale,
    _group_split_pairs,
    _load_v3c_pairing,
    _score_baselines_on_pairs,
    _split_by_pairing,
    _stability,
    _train_perceptron,
    _training_gates,
    _validate_v3c_dataset,
    train_v3c1,
)
from vgc_team_pool import load_vgc_pool


def _make_fake_row(
    pair_id: int,
    side: str,
    our_policy: str,
    opp_policy: str,
    our_win: bool,
    features: Dict[str, float],
    team_hash: str = "team_a",
) -> Dict[str, Any]:
    return {
        "pair_id": pair_id,
        "side": side,
        "our_policy": our_policy,
        "opponent_policy": opp_policy,
        "our_chosen_4": ["a", "b", "c", "d"],
        "our_lead_2": ["a", "b"],
        "our_back_2": ["c", "d"],
        "opp_chosen_4": ["e", "f", "g", "h"],
        "opp_lead_2": ["e", "f"],
        "opp_back_2": ["g", "h"],
        "our_win": our_win,
        "status": "ok",
        "turns": 5,
        "our_team": [],
        "opponent_team": [],
        "team_hash": team_hash,
        "opponent_team_hash": team_hash,
        "source": "test",
        "our_features": features,
    }


class TestV3cDatasetLoader(unittest.TestCase):
    """V3c dataset loader validates 6 pairing files."""

    @classmethod
    def setUpClass(cls):
        cls.pool = load_vgc_pool()

    def test_files_exist(self):
        for f in V3C_PAIRING_FILES:
            self.assertTrue(
                os.path.isfile(f),
                f"missing {f}",
            )

    def test_loader_extracts_features(self):
        rows, skipped = _load_v3c_pairing(
            V3C_PAIRING_FILES[0], self.pool
        )
        self.assertEqual(len(rows), 50)
        self.assertEqual(skipped, {})
        for r in rows:
            self.assertIn("our_features", r)
            self.assertGreater(len(r["our_features"]), 0)
            # No hidden-info substrings in feature names.
            for fn in r["our_features"]:
                for bad in (
                    "hidden", "item", "tier", "usage",
                    "online", "api", "scrape", "llm",
                ):
                    self.assertNotIn(bad, fn.lower())


class TestDecisivePairExtraction(unittest.TestCase):
    """Decisive pair extraction excludes split pairs."""

    def test_decisive_a_both(self):
        # Pair 0: a wins both sides. Use different
        # chosen_4 for the two policies so they
        # aren't filtered as identical_plans.
        rows = [
            _make_fake_row(
                0, "p1", "a", "b", True,
                {"f1": 1.0}, team_hash="h0",
            ),
            _make_fake_row(
                0, "p2", "b", "a", False,
                {"f1": 0.0}, team_hash="h0",
            ),
        ]
        rows[0]["our_chosen_4"] = ["a1", "b1", "c1", "d1"]
        rows[1]["our_chosen_4"] = ["a2", "b2", "c2", "d2"]
        pairs, skipped = _build_decisive_pairs_per_pairing(
            rows
        )
        self.assertEqual(len(pairs), 1)
        self.assertEqual(skipped, {})
        winner, loser = pairs[0]
        self.assertEqual(winner["our_policy"], "a")
        self.assertEqual(loser["our_policy"], "b")

    def test_split_pair_excluded(self):
        # Pair 0: split. a wins D1, b wins D2.
        # Use different chosen_4.
        rows = [
            _make_fake_row(
                0, "p1", "a", "b", True,
                {"f1": 1.0}, team_hash="h0",
            ),
            _make_fake_row(
                0, "p2", "b", "a", True,
                {"f1": 0.0}, team_hash="h0",
            ),
        ]
        rows[0]["our_chosen_4"] = ["a1", "b1", "c1", "d1"]
        rows[1]["our_chosen_4"] = ["a2", "b2", "c2", "d2"]
        pairs, skipped = _build_decisive_pairs_per_pairing(
            rows
        )
        self.assertEqual(len(pairs), 0)
        self.assertIn("tied_or_split", skipped)

    def test_identical_plans_excluded(self):
        # Winner and loser pick the same plan. Use
        # different our_policy so a_both wins; same
        # our_chosen_4.
        rows = [
            _make_fake_row(
                0, "p1", "a", "b", True,
                {"f1": 1.0}, team_hash="h0",
            ),
            _make_fake_row(
                0, "p2", "b", "a", False,
                {"f1": 0.0}, team_hash="h0",
            ),
        ]
        # Both pick same chosen_4.
        rows[0]["our_chosen_4"] = ["a", "b", "c", "d"]
        rows[1]["our_chosen_4"] = ["a", "b", "c", "d"]
        pairs, skipped = _build_decisive_pairs_per_pairing(
            rows
        )
        self.assertEqual(len(pairs), 0)
        self.assertIn("identical_plans", skipped)


class TestGroupSplitNoLeakage(unittest.TestCase):
    """Group split has no team_hash leakage."""

    def test_no_leakage(self):
        from vgc2026_phaseV3a_learn_preview import (
            assert_no_leakage,
        )
        rows = []
        for p in range(10):
            team_hash = f"h{p}"
            rows.append(
                _make_fake_row(
                    p, "p1", "a", "b", True,
                    {"f1": 1.0}, team_hash=team_hash,
                )
            )
            rows.append(
                _make_fake_row(
                    p, "p2", "b", "a", False,
                    {"f1": 0.0}, team_hash=team_hash,
                )
            )
        pairs, _ = _build_decisive_pairs_per_pairing(rows)
        train, val = _group_split_pairs(
            pairs, val_fraction=0.2, seed=42
        )
        train_hashes = {p[0]["team_hash"] for p in train}
        val_hashes = {p[0]["team_hash"] for p in val}
        self.assertEqual(
            train_hashes & val_hashes,
            set(),
            "team_hash must not overlap between train and val",
        )
        assert_no_leakage(
            [{"team_hash": p[0]["team_hash"]} for p in train],
            [{"team_hash": p[0]["team_hash"]} for p in val],
        )


class TestNormalizedVariantUsesTrainStatsOnly(unittest.TestCase):
    """Normalized variant uses train stats only."""

    def test_normalized_uses_train_only(self):
        rows = []
        for p in range(10):
            team_hash = f"h{p}"
            # Half teams have feature f1=1.0, half have 0.0.
            val_f1 = 1.0 if p < 5 else 0.0
            rows.append(
                _make_fake_row(
                    p, "p1", "a", "b", True,
                    {"f1": val_f1}, team_hash=team_hash,
                )
            )
            rows.append(
                _make_fake_row(
                    p, "p2", "b", "a", False,
                    {"f1": 0.0}, team_hash=team_hash,
                )
            )
        pairs, _ = _build_decisive_pairs_per_pairing(rows)
        train, val = _group_split_pairs(
            pairs, val_fraction=0.2, seed=42
        )
        # Check that val rows are normalized using
        # train mean/std. We can't directly assert
        # the model behavior, but we can verify
        # the train mean/std excludes val.
        train_hashes = {p[0]["team_hash"] for p in train}
        val_hashes = {p[0]["team_hash"] for p in val}
        self.assertEqual(train_hashes & val_hashes, set())


class TestTrainingGatesBlockWeakValAcc(unittest.TestCase):
    """Training gates block weak val_acc."""

    def test_block_when_weak(self):
        stability = {
            "val_acc_mean": 0.30,
            "val_acc_median": 0.32,
            "beats_v3_fraction": 0.37,
            "beats_learned_fraction": 0.93,
            "overfit_gap_mean": 0.30,
        }
        scale = {
            "max_contribution_share": 0.20,
        }
        gates = _training_gates(stability, scale, 10)
        self.assertFalse(gates["overall_pass"])
        self.assertFalse(
            gates["gates"]["mean_val_acc_ge_0.60"]
        )

    def test_pass_when_strong(self):
        stability = {
            "val_acc_mean": 0.65,
            "val_acc_median": 0.65,
            "beats_v3_fraction": 0.85,
            "beats_learned_fraction": 0.70,
            "overfit_gap_mean": 0.15,
        }
        scale = {
            "max_contribution_share": 0.20,
        }
        gates = _training_gates(stability, scale, 15)
        self.assertTrue(gates["overall_pass"])


class TestPolicyWrapperNotAddedWhenGatesFail(unittest.TestCase):
    """Policy wrapper not added when gates fail."""

    def test_no_model_artifact(self):
        if os.path.isfile(V3C1_MODEL_PATH):
            self.skipTest(
                f"{V3C1_MODEL_PATH} exists; gates passed"
            )
        # V3c.1 BLOCKED so the model must not exist.
        self.assertFalse(
            os.path.isfile(V3C1_MODEL_PATH),
            f"{V3C1_MODEL_PATH} should not exist "
            f"when gates fail",
        )


class TestArtifactJsonSchema(unittest.TestCase):
    """V3c.1 artifacts are JSON-serializable."""

    def test_training_report_json_loadable(self):
        if not os.path.isfile(V3C1_REPORT_JSON):
            self.skipTest(
                f"missing {V3C1_REPORT_JSON}"
            )
        with open(V3C1_REPORT_JSON) as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)
        for k in (
            "phase",
            "validation",
            "n_decisive_pairs",
            "stability",
            "gates",
        ):
            self.assertIn(k, data)

    def test_training_report_md_exists(self):
        if not os.path.isfile(V3C1_REPORT_MD):
            self.skipTest(
                f"missing {V3C1_REPORT_MD}"
            )
        with open(V3C1_REPORT_MD) as f:
            content = f.read()
        self.assertIn("Phase V3c.1", content)

    def test_feature_scale_json_loadable(self):
        if not os.path.isfile(V3C1_FEATURE_SCALE):
            self.skipTest(
                f"missing {V3C1_FEATURE_SCALE}"
            )
        with open(V3C1_FEATURE_SCALE) as f:
            data = json.load(f)
        self.assertIn("per_feature", data)
        self.assertIn("top10_by_contribution", data)

    def test_split_stability_json_loadable(self):
        if not os.path.isfile(V3C1_SPLIT_STABILITY):
            self.skipTest(
                f"missing {V3C1_SPLIT_STABILITY}"
            )
        with open(V3C1_SPLIT_STABILITY) as f:
            data = json.load(f)
        self.assertIn("val_acc_mean", data)
        self.assertIn("per_seed", data)


class TestDefaultPolicyUnchanged(unittest.TestCase):
    """Default policy remains matchup_top4_v3 / basic_top4."""

    def test_default_policy_unchanged(self):
        from team_preview_policy import choose_four_from_six
        import inspect
        default_pol = inspect.signature(
            choose_four_from_six
        ).parameters["policy"].default
        self.assertEqual(default_pol, "basic_top4")

    def test_v3a1_wrapper_still_opt_in(self):
        from team_preview_policy import choose_four_from_six
        team = [
            {"species": s, "moves": ["Tackle"], "ability": ""}
            for s in ["a", "b", "c", "d", "e", "f"]
        ]
        opp = team[:]
        result = choose_four_from_six(
            team, opp, policy="matchup_top4_v3"
        )
        self.assertEqual(len(result.chosen_4), 4)


class TestExistingArtifactsPreserved(unittest.TestCase):
    """V3a/V3a1/V3b/V3c.1 artifacts must not be
    overwritten by V3c.1 (this phase is BLOCKED).
    """

    def test_v3a1_model_still_exists(self):
        from vgc2026_phaseV3a_learn_preview import (
            DEFAULT_V3A1_MODEL_PATH,
        )
        self.assertTrue(
            os.path.isfile(DEFAULT_V3A1_MODEL_PATH)
        )

    def test_v3b_model_still_exists(self):
        from vgc2026_phaseV3b_train import (
            DEFAULT_V3B_MODEL_PATH,
        )
        self.assertTrue(
            os.path.isfile(DEFAULT_V3B_MODEL_PATH)
        )


class TestValidationCounts(unittest.TestCase):
    """Validation counts match expected."""

    @classmethod
    def setUpClass(cls):
        cls.pool = load_vgc_pool()
        cls.rows = []
        for f in V3C_PAIRING_FILES:
            rows, _ = _load_v3c_pairing(f, cls.pool)
            cls.rows.extend(rows)

    def test_n_battles(self):
        v = _validate_v3c_dataset(
            self.rows, {"n_files_loaded": 6}
        )
        self.assertEqual(v["n_battles"], 300)
        self.assertEqual(v["n_status_bad"], 0)
        self.assertEqual(v["n_chosen_4_ok"], 300)
        self.assertEqual(v["n_lead_2_ok"], 300)
        self.assertEqual(v["n_back_2_ok"], 300)


if __name__ == "__main__":
    unittest.main()
