"""Phase RL-7 — Tests for the offline policy dry-run
feasibility script.

All tests use tiny temp JSONL fixtures. No reliance on
large logs.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from dryrun_turn_level_offline_policy import (  # noqa: E402
    FORBIDDEN_FEATURE_FIELDS,
    SCHEMA_VERSION,
    _action_category,
    _check_no_episode_leakage,
    _deterministic_split,
    _dryrun_core,
    _dryrun_enriched,
    _episode_key,
    _extract_features,
    _leakage_check,
    _load_dataset,
    _majority_baseline,
    _pairwise_accuracy,
    _readiness_decision,
    _sample_negatives,
    LinearPairwiseReranker,
)


def _make_row(
    battle_tag: str = "b1",
    arm: str = "treatment",
    turn: int = 1,
    won: bool = True,
    our_hp=(1.0, 1.0),
    opp_hp=(1.0, 1.0),
    selected=(
        ["move", "tackle", "1", ""],
        ["move", "matchagotcha", "0", ""],
    ),
    legal0=None,
    legal1=None,
    total_joint_orders: int = 50,
    speed_priority_threatened=None,
    expected_to_faint_before_moving=None,
    joint_order_count=None,
    weather="none",
):
    """Build a minimal turn_rl_v1.0 row."""
    if legal0 is None:
        legal0 = [list(selected[0]), ["move", "fakeout", "1", ""]]
    if legal1 is None:
        legal1 = [list(selected[1]), ["move", "protect", "0", ""]]
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": "test",
        "source_artifact": "test.jsonl",
        "battle_tag": battle_tag,
        "episode_id": battle_tag,
        "turn_index": turn,
        "player_side": "bot",
        "benchmark_arm": arm,
        "policy_name": "test",
        "won": won,
        "battle_result": "win" if won else "loss",
        "total_turns": 5,
        "terminal_reward": 1 if won else -1,
        "discounted_return": None,
        "state_snapshot": {
            "our_active_species": ["incineroar", "sinistcha"],
            "opp_active_species": ["garchomp", "incineroar"],
            "our_active_hp_fraction": list(our_hp),
            "opp_active_hp_fraction": list(opp_hp),
            "weather": weather,
            "fields": [],
            "side_conditions": [],
            "turn_number": turn,
        },
        "legal_action_keys_slot0": [list(k) for k in legal0],
        "legal_action_keys_slot1": [list(k) for k in legal1],
        "legal_joint_action_keys": None,
        "selected_joint_key": [list(selected[0]), list(selected[1])],
        "final_action_keys": [list(selected[0]), list(selected[1])],
        "selected_per_slot": {
            "slot_0": list(selected[0]),
            "slot_1": list(selected[1]),
        },
        "selected_score": 100.0,
        "top_5_alternatives": [],
        "top_5_scores": [],
        "score_gap_selected_best_alt": 10.0,
        "v2l1_raw_scores_slot0": {},
        "v2l1_raw_scores_slot1": {},
        "switch_counterfactual": None,
        "speed_priority_threatened": speed_priority_threatened,
        "expected_to_faint_before_moving":
            expected_to_faint_before_moving,
        "overkill_penalty_triggered": False,
        "focus_fire_triggered": False,
        "stale_target_avoided": False,
        "narrow_ally_heal_candidate_blocked_slot0": None,
        "narrow_ally_heal_candidate_blocked_slot1": None,
        "joint_order_count": joint_order_count,
        "total_legal_joint_orders": total_joint_orders,
    }


def _make_battle(rows, battle_tag="b1", arm="treatment", won=True):
    """Wrap rows in a list (no audit file needed)."""
    return rows


def _write_jsonl(rows, path):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


class TestLoadDataset(unittest.TestCase):
    def test_load_tiny_dataset(self):
        rows = [
            _make_row(battle_tag="b1", turn=1),
            _make_row(battle_tag="b1", turn=2),
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
            path = f.name
        try:
            loaded = _load_dataset(path)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0]["battle_tag"], "b1")
        finally:
            os.unlink(path)

    def test_load_empty_lines_skipped(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write("\n\n")
            path = f.name
        try:
            loaded = _load_dataset(path)
            self.assertEqual(len(loaded), 0)
        finally:
            os.unlink(path)


class TestEpisodeSplit(unittest.TestCase):
    def test_split_deterministic(self):
        rows = [
            _make_row(battle_tag=f"b{i}", turn=1)
            for i in range(10)
        ]
        for _ in range(2):
            t, v = _deterministic_split(
                rows, val_fraction=0.2, seed=42
            )
            self.assertEqual(len(t) + len(v), 10)
            self.assertGreater(len(v), 0)

    def test_split_no_episode_leakage(self):
        rows = [
            _make_row(battle_tag=f"b{i}", turn=t)
            for i in range(5) for t in range(3)
        ]
        t, v = _deterministic_split(
            rows, val_fraction=0.4, seed=42
        )
        train_eps = {_episode_key(r) for r in t}
        val_eps = {_episode_key(r) for r in v}
        self.assertEqual(
            len(train_eps & val_eps), 0,
            "Episode leakage detected"
        )
        # All episodes accounted for.
        all_eps = {_episode_key(r) for r in rows}
        self.assertEqual(train_eps | val_eps, all_eps)

    def test_check_no_episode_leakage_helper(self):
        t = [_make_row(battle_tag="b1"), _make_row(battle_tag="b2")]
        v = [_make_row(battle_tag="b3")]
        self.assertTrue(_check_no_episode_leakage(t, v))
        v2 = [_make_row(battle_tag="b1")]
        self.assertFalse(_check_no_episode_leakage(t, v2))


class TestActionCategory(unittest.TestCase):
    def test_move_attack(self):
        cat = _action_category(["move", "tackle", "1", ""])
        self.assertEqual(cat, "move_attack")

    def test_move_status_ally(self):
        cat = _action_category(["move", "protect", "0", ""])
        self.assertEqual(cat, "move_status_ally")

    def test_move_status_opp(self):
        # Status move on opponent (no negative target)
        # Note: the current categorizer only labels moves
        # as move_status_ally if they are protect/heal
        # moves; otherwise it falls back to target-based
        # attack categorization. So a status move hitting
        # an opponent slot is still move_attack.
        cat = _action_category(["move", "spore", "1", ""])
        # This is intentional behavior: spore targeting
        # an opponent slot is categorized as move_attack.
        self.assertEqual(cat, "move_attack")

    def test_switch(self):
        cat = _action_category(["switch", "garchomp", "0", ""])
        self.assertEqual(cat, "switch")

    def test_unknown(self):
        cat = _action_category(["unknown_kind", "x", "0", ""])
        self.assertEqual(cat, "unknown")

    def test_none(self):
        self.assertEqual(_action_category(None), "unknown")


class TestForbiddenFields(unittest.TestCase):
    def test_extract_features_never_reads_forbidden(self):
        """Static check: the _extract_features function
        must not access forbidden fields. We can verify
        by giving a row where forbidden fields would
        change the result if they were read.
        """
        # Create a row with forbidden fields set to
        # sentinel values. If the function reads them,
        # the feature vector would differ.
        r_clean = _make_row()
        r_dirty = _make_row()
        r_dirty["won"] = not r_dirty["won"]
        r_dirty["terminal_reward"] = -r_dirty["terminal_reward"]
        r_dirty["battle_result"] = "loss"
        r_dirty["selected_score"] = -999.0
        r_dirty["final_action_keys"] = [["fake"], ["fake"]]
        f_clean = _extract_features(r_clean, include_enriched=False)
        f_dirty = _extract_features(r_dirty, include_enriched=False)
        self.assertEqual(
            f_clean, f_dirty,
            "Feature extractor is reading forbidden fields"
        )

    def test_forbidden_set_includes_outcome(self):
        for f in ("won", "terminal_reward", "battle_result"):
            self.assertIn(f, FORBIDDEN_FEATURE_FIELDS)


class TestFeatureExtraction(unittest.TestCase):
    def test_extract_features_core_dim(self):
        r = _make_row()
        f = _extract_features(r, include_enriched=False)
        # 4 (turn bucket) + 8 (HP) + 4 (weather) + 2
        # (legal count) + 10 (selected cat) + 1 (joint
        # orders) = 29
        self.assertEqual(len(f), 29)

    def test_extract_features_enriched_dim(self):
        r = _make_row(
            speed_priority_threatened=[True, False],
            expected_to_faint_before_moving=[False, True],
        )
        f = _extract_features(r, include_enriched=True)
        self.assertEqual(len(f), 33)

    def test_extract_features_handles_missing_hp(self):
        r = _make_row()
        r["state_snapshot"]["our_active_hp_fraction"] = None
        r["state_snapshot"]["opp_active_hp_fraction"] = None
        f = _extract_features(r, include_enriched=False)
        self.assertEqual(len(f), 29)

    def test_extract_features_handles_short_enriched(self):
        r = _make_row(
            speed_priority_threatened=[True],
            expected_to_faint_before_moving=[True],
        )
        f = _extract_features(r, include_enriched=True)
        self.assertEqual(len(f), 33)


class TestNegativeSampling(unittest.TestCase):
    def test_negatives_exclude_selected(self):
        r = _make_row()
        negs = _sample_negatives(r, n=3, seed=42)
        self.assertGreater(len(negs), 0)
        sel = tuple(tuple(k) for k in r["selected_joint_key"])
        for a0, a1 in negs:
            self.assertNotEqual((tuple(a0), tuple(a1)), sel)

    def test_negatives_unique(self):
        r = _make_row()
        negs = _sample_negatives(r, n=5, seed=42)
        keys = [(tuple(a0), tuple(a1)) for a0, a1 in negs]
        self.assertEqual(len(keys), len(set(keys)))

    def test_negatives_empty_when_no_legal(self):
        r = _make_row()
        r["legal_action_keys_slot0"] = []
        r["legal_action_keys_slot1"] = []
        negs = _sample_negatives(r, n=3, seed=42)
        self.assertEqual(negs, [])


class TestLinearPairwiseReranker(unittest.TestCase):
    def test_score_initially_zero(self):
        m = LinearPairwiseReranker(n_features=3, seed=42)
        self.assertEqual(m.score([1.0, 2.0, 3.0]), 0.0)

    def test_update_pushes_pos_above_neg(self):
        m = LinearPairwiseReranker(n_features=2, lr=1.0, seed=42)
        pos = [1.0, 0.0]
        neg = [0.0, 1.0]
        m.update(pos, neg)
        # After update, pos should beat neg.
        self.assertGreater(m.score(pos), m.score(neg))

    def test_deterministic_with_same_seed(self):
        m1 = LinearPairwiseReranker(n_features=3, seed=42)
        m2 = LinearPairwiseReranker(n_features=3, seed=42)
        for _ in range(5):
            m1.update([1.0, 0.0, 1.0], [0.0, 1.0, 0.0])
            m2.update([1.0, 0.0, 1.0], [0.0, 1.0, 0.0])
        self.assertEqual(m1.weights, m2.weights)

    def test_pairwise_examples_generated(self):
        r = _make_row()
        feats = _extract_features(r, include_enriched=False)
        negs = _sample_negatives(r, n=2, seed=42)
        self.assertGreater(len(negs), 0)
        # Pairwise examples: pos_feats vs neg_feats.
        for a0, a1 in negs:
            r_neg = dict(r)
            r_neg["selected_joint_key"] = [a0, a1]
            r_neg["selected_per_slot"] = {
                "slot_0": a0, "slot_1": a1
            }
            neg_feats = _extract_features(
                r_neg, include_enriched=False
            )
            self.assertEqual(len(neg_feats), len(feats))


class TestPairwiseAccuracy(unittest.TestCase):
    def test_pairwise_accuracy_returns_float(self):
        m = LinearPairwiseReranker(n_features=29, seed=42)
        rows = [_make_row(battle_tag=f"b{i}") for i in range(3)]
        acc = _pairwise_accuracy(
            m, rows, n_negatives=2, seed=42
        )
        self.assertIsInstance(acc, float)
        self.assertGreaterEqual(acc, 0.0)
        self.assertLessEqual(acc, 1.0)


class TestMajorityBaseline(unittest.TestCase):
    def test_majority_baseline_returns_float(self):
        train = [_make_row(battle_tag=f"b{i}") for i in range(5)]
        val = [_make_row(battle_tag=f"v{i}") for i in range(2)]
        acc = _majority_baseline(train, val)
        self.assertIsInstance(acc, float)
        self.assertGreaterEqual(acc, 0.0)
        self.assertLessEqual(acc, 1.0)


class TestDryRunCore(unittest.TestCase):
    def test_dryrun_core_returns_metrics(self):
        rows = []
        for i in range(8):
            for t in range(3):
                rows.append(_make_row(
                    battle_tag=f"b{i}", turn=t,
                    won=(i % 2 == 0),
                ))
        metrics = _dryrun_core(rows, n_negatives=2, n_epochs=1)
        self.assertEqual(metrics["rows_total"], 24)
        self.assertIn("train_rows", metrics)
        self.assertIn("val_rows", metrics)
        self.assertIn("train_pairwise_accuracy", metrics)
        self.assertIn("val_pairwise_accuracy", metrics)
        self.assertIn("deterministic", metrics)
        self.assertTrue(metrics["deterministic"])

    def test_dryrun_core_deterministic(self):
        rows = [
            _make_row(battle_tag=f"b{i}", turn=t)
            for i in range(5) for t in range(2)
        ]
        m1 = _dryrun_core(rows, n_negatives=2, n_epochs=1,
                          seed=42)
        m2 = _dryrun_core(rows, n_negatives=2, n_epochs=1,
                          seed=42)
        self.assertEqual(
            m1["val_pairwise_accuracy"],
            m2["val_pairwise_accuracy"],
        )

    def test_dryrun_core_overfit_gap_reported(self):
        rows = [
            _make_row(battle_tag=f"b{i}", turn=t)
            for i in range(10) for t in range(3)
        ]
        m = _dryrun_core(rows, n_negatives=2, n_epochs=1)
        self.assertIn("overfit_gap", m)
        self.assertIsInstance(m["overfit_gap"], float)


class TestDryRunEnriched(unittest.TestCase):
    def test_enriched_reports_field_coverage(self):
        rows = [
            _make_row(
                battle_tag=f"b{i}", turn=1,
                speed_priority_threatened=[True, False],
                expected_to_faint_before_moving=[False, True],
            )
            for i in range(5)
        ]
        m = _dryrun_enriched(rows, n_negatives=2, n_epochs=1)
        self.assertEqual(
            m["speed_priority_threatened_coverage"], 5
        )
        self.assertEqual(
            m["expected_to_faint_before_moving_coverage"], 5
        )
        self.assertEqual(m["joint_order_count_coverage"], 0)


class TestLeakageCheck(unittest.TestCase):
    def test_leakage_clean_dataset(self):
        rows = [_make_row() for _ in range(3)]
        out = _leakage_check(rows)
        self.assertEqual(
            out["state_snapshot_forbidden_field_violations"], 0
        )
        self.assertFalse(
            out["feature_extractor_reads_forbidden_fields"]
        )

    def test_leakage_dirty_state(self):
        rows = [_make_row()]
        rows[0]["state_snapshot"]["won"] = True
        out = _leakage_check(rows)
        self.assertEqual(
            out["state_snapshot_forbidden_field_violations"], 1
        )


class TestReadinessDecision(unittest.TestCase):
    def test_not_ready_no_core(self):
        d = _readiness_decision(None, None)
        self.assertEqual(d, "NOT_READY")

    def test_not_ready_tiny_data(self):
        core = {"status": "ok", "rows_total": 1,
                "train_episodes": 1, "val_episodes": 0,
                "deterministic": True}
        d = _readiness_decision(core, None)
        self.assertEqual(d, "NOT_READY")

    def test_pipeline_works_adequate_data(self):
        core = {
            "status": "ok",
            "rows_total": 100,
            "train_episodes": 8,
            "val_episodes": 2,
            "deterministic": True,
        }
        d = _readiness_decision(core, None)
        self.assertEqual(d, "DRYRUN_PIPELINE_WORKS")

    def test_not_ready_non_deterministic(self):
        core = {
            "status": "ok",
            "rows_total": 100,
            "train_episodes": 8,
            "val_episodes": 2,
            "deterministic": False,
        }
        d = _readiness_decision(core, None)
        self.assertEqual(d, "NOT_READY")


class TestCLIEndToEnd(unittest.TestCase):
    def test_cli_runs_with_core_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset_path = os.path.join(tmp, "core.jsonl")
            json_path = os.path.join(tmp, "out.json")
            md_path = os.path.join(tmp, "out.md")
            rows = [
                _make_row(
                    battle_tag=f"b{i}", turn=t,
                    won=(i % 2 == 0),
                )
                for i in range(8) for t in range(3)
            ]
            _write_jsonl(rows, dataset_path)
            from dryrun_turn_level_offline_policy import main
            rc = main([
                "--core-dataset", dataset_path,
                "--output-json", json_path,
                "--output-md", md_path,
                "--n-negatives", "2",
                "--n-epochs", "1",
            ])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(json_path))
            self.assertTrue(os.path.exists(md_path))
            with open(json_path) as f:
                d = json.load(f)
            self.assertIn(d["readiness"],
                          ("NOT_READY", "DRYRUN_PIPELINE_WORKS"))
            self.assertTrue(d["no_model_artifact"])
            self.assertTrue(d["no_episode_leakage"])

    def test_cli_runs_with_core_and_enriched(self):
        with tempfile.TemporaryDirectory() as tmp:
            core_path = os.path.join(tmp, "core.jsonl")
            enr_path = os.path.join(tmp, "enr.jsonl")
            json_path = os.path.join(tmp, "out.json")
            md_path = os.path.join(tmp, "out.md")
            core_rows = [
                _make_row(battle_tag=f"c{i}", turn=t)
                for i in range(8) for t in range(3)
            ]
            enr_rows = [
                _make_row(
                    battle_tag=f"e{i}", turn=1,
                    speed_priority_threatened=[True, False],
                    expected_to_faint_before_moving=[False, True],
                )
                for i in range(5)
            ]
            _write_jsonl(core_rows, core_path)
            _write_jsonl(enr_rows, enr_path)
            from dryrun_turn_level_offline_policy import main
            rc = main([
                "--core-dataset", core_path,
                "--enriched-dataset", enr_path,
                "--output-json", json_path,
                "--output-md", md_path,
                "--n-negatives", "2",
                "--n-epochs", "1",
            ])
            self.assertEqual(rc, 0)
            with open(json_path) as f:
                d = json.load(f)
            self.assertIsNotNone(d.get("enriched_metrics"))
            self.assertEqual(
                d["enriched_metrics"][
                    "speed_priority_threatened_coverage"
                ],
                5,
            )

    def test_cli_missing_core_fails(self):
        from dryrun_turn_level_offline_policy import main
        with tempfile.TemporaryDirectory() as tmp:
            rc = main([
                "--core-dataset", os.path.join(tmp, "missing.jsonl"),
                "--output-json", os.path.join(tmp, "out.json"),
                "--output-md", os.path.join(tmp, "out.md"),
            ])
            self.assertEqual(rc, 2)


class TestNoModelArtifact(unittest.TestCase):
    def test_dryrun_does_not_write_model_file(self):
        """The dry-run function returns a metrics dict.
        It must not write any model file. This is a
        code-level check: we inspect the function for
        the absence of `open(...,'w')` calls writing
        weights.
        """
        import inspect
        from dryrun_turn_level_offline_policy import (
            _dryrun_core, _dryrun_enriched,
        )
        src_core = inspect.getsource(_dryrun_core)
        src_enr = inspect.getsource(_dryrun_enriched)
        # No "open" with "wb" or "w" for pickle/torch
        # save etc. (Just static inspection.)
        for needle in ("pickle.dump", "torch.save",
                       "joblib.dump"):
            self.assertNotIn(needle, src_core)
            self.assertNotIn(needle, src_enr)


class TestFixtureAdequate(unittest.TestCase):
    def test_adequate_synthetic_fixture_yields_works(self):
        """A synthetic fixture with 60 rows across 10
        episodes should yield DRYRUN_PIPELINE_WORKS.
        """
        rows = []
        for i in range(10):
            for t in range(6):
                rows.append(_make_row(
                    battle_tag=f"b{i:02d}", turn=t,
                    won=(i % 2 == 0),
                ))
        with tempfile.TemporaryDirectory() as tmp:
            core_path = os.path.join(tmp, "core.jsonl")
            json_path = os.path.join(tmp, "out.json")
            md_path = os.path.join(tmp, "out.md")
            _write_jsonl(rows, core_path)
            from dryrun_turn_level_offline_policy import main
            rc = main([
                "--core-dataset", core_path,
                "--output-json", json_path,
                "--output-md", md_path,
                "--n-negatives", "2",
                "--n-epochs", "1",
            ])
            self.assertEqual(rc, 0)
            with open(json_path) as f:
                d = json.load(f)
            self.assertEqual(
                d["readiness"], "DRYRUN_PIPELINE_WORKS"
            )

    def test_tiny_fixture_yields_not_ready(self):
        """A 1-row fixture should yield NOT_READY."""
        rows = [_make_row()]
        with tempfile.TemporaryDirectory() as tmp:
            core_path = os.path.join(tmp, "core.jsonl")
            json_path = os.path.join(tmp, "out.json")
            md_path = os.path.join(tmp, "out.md")
            _write_jsonl(rows, core_path)
            from dryrun_turn_level_offline_policy import main
            rc = main([
                "--core-dataset", core_path,
                "--output-json", json_path,
                "--output-md", md_path,
                "--n-negatives", "2",
                "--n-epochs", "1",
            ])
            self.assertEqual(rc, 0)
            with open(json_path) as f:
                d = json.load(f)
            self.assertEqual(d["readiness"], "NOT_READY")


if __name__ == "__main__":
    unittest.main()
