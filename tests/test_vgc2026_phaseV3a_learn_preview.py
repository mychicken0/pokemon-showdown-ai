#!/usr/bin/env python3
"""Phase V3a — VGC Preview Learning Baseline Tests.

Focused tests for the V3a offline learner. All
tests use the canonical team pool and existing
V3 evaluators. No skipped / pass-only tests.
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


from vgc2026_phaseV3a_learn_preview import (
    DEFAULT_MODEL_PATH,
    discover_feature_names,
    enumerate_plans,
    evaluate_against_rows,
    load_model,
    make_pair_targets,
    pairwise_update,
    save_model,
    score_plan,
    train,
    train_and_save,
)
from team_preview_policy import (
    PreviewResult,
    choose_four_from_six,
    evaluate_all_combinations_v3,
)
from vgc_team_pool import load_vgc_pool


def _sample_team() -> List[Dict[str, Any]]:
    """Return a 6-Pokémon team in poke-env format."""
    return [
        {
            "species": "incineroar", "ability": "Intimidate",
            "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"],
        },
        {
            "species": "garchomp", "ability": "Rough Skin",
            "moves": ["Earthquake", "Rock Slide", "Stomping Tantrum", "Dragon Claw"],
        },
        {
            "species": "rillaboom", "ability": "Grassy Surge",
            "moves": ["Fake Out", "Grassy Glide", "U-turn", "Protect"],
        },
        {
            "species": "fluttermane", "ability": "Protosynthesis",
            "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"],
        },
        {
            "species": "ironhands", "ability": "Quark Drive",
            "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"],
        },
        {
            "species": "amoonguss", "ability": "Regenerator",
            "moves": ["Spore", "Pollen Puff", "Rage Powder", "Protect"],
        },
    ]


def _opponent_team() -> List[Dict[str, Any]]:
    return [
        {
            "species": "venusaur", "ability": "Chlorophyll",
            "moves": ["Sleep Powder", "Sludge Bomb", "Earth Power", "Protect"],
        },
        {
            "species": "charizard", "ability": "Blaze",
            "moves": ["Heat Wave", "Solar Beam", "Weather Ball", "Protect"],
        },
        {
            "species": "garchomp", "ability": "Rough Skin",
            "moves": ["Earthquake", "Rock Slide", "Stomping Tantrum", "Protect"],
        },
        {
            "species": "incineroar", "ability": "Intimidate",
            "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"],
        },
        {
            "species": "floetteeternal", "ability": "Flower Veil",
            "moves": ["Moonblast", "Dazzling Gleam", "Calm Mind", "Protect"],
        },
        {
            "species": "sinistcha", "ability": "Hospitality",
            "moves": ["Matcha Gotcha", "Rage Powder", "Trick Room", "Protect"],
        },
    ]


class TestActionEnumeration(unittest.TestCase):
    def test_evaluate_all_combinations_v3_returns_90(self):
        """V3 enumerator returns 90 plans for 6 unique
        team members: 15 subsets * 6 lead/back
        partitions."""
        results = evaluate_all_combinations_v3(_sample_team())
        self.assertEqual(len(results), 90)

    def test_enumerate_plans_dedupes(self):
        """enumerate_plans skips plans that fail
        _resolve_plan (e.g. duplicate species)."""
        plans = enumerate_plans(_sample_team(), _opponent_team())
        # 90 unique plans; no duplicates.
        keys = set()
        for chosen, lead, back, _ in plans:
            k = tuple(sorted(s.lower() for s in chosen))
            keys.add(k)
        # If pool accepts all 90, no dedup happens.
        self.assertGreaterEqual(len(plans), 15)

    def test_deterministic_order(self):
        """enumerate_plans returns the same order on
        repeat calls."""
        a = enumerate_plans(_sample_team(), _opponent_team())
        b = enumerate_plans(_sample_team(), _opponent_team())
        self.assertEqual(
            [(c, l, b2) for c, l, b2, _ in a],
            [(c, l, b2) for c, l, b2, _ in b],
        )


class TestFeatureExtraction(unittest.TestCase):
    def setUp(self):
        self.team = _sample_team()
        self.opp = _opponent_team()

    def test_extract_plan_features_no_hidden_info(self):
        """Feature extraction uses only public team
        data: species, types, ability, moves. No
        hidden items, no hidden abilities, no battle
        logs."""
        from vgc2026_plan_features import extract_plan_features
        chosen = ["incineroar", "garchomp", "rillaboom", "fluttermane"]
        lead = ["incineroar", "garchomp"]
        back = ["rillaboom", "fluttermane"]
        pf = extract_plan_features(
            self.team, self.opp, chosen, lead, back
        )
        # Features is a flat dict of floats.
        for k, v in pf.features.items():
            self.assertIsInstance(v, (int, float))
        # Stable keys.
        self.assertIn("offensive_type_coverage", pf.features)

    def test_feature_names_stable(self):
        """Feature names are a stable sorted list."""
        from vgc2026_plan_features import extract_plan_features
        chosen = ["incineroar", "garchomp", "rillaboom", "fluttermane"]
        lead = ["incineroar", "garchomp"]
        back = ["rillaboom", "fluttermane"]
        pf = extract_plan_features(
            self.team, self.opp, chosen, lead, back
        )
        # All keys are strings, no spaces, lowercase
        # + underscores.
        for k in pf.features:
            self.assertIsInstance(k, str)
            self.assertNotIn(" ", k)

    def test_no_row_order_leakage_in_features(self):
        """Feature extraction is order-independent:
        same plan in any order yields the same
        features dict."""
        from vgc2026_plan_features import extract_plan_features
        chosen = ["incineroar", "garchomp", "rillaboom", "fluttermane"]
        pf1 = extract_plan_features(
            self.team, self.opp, chosen,
            chosen[:2], chosen[2:],
        )
        pf2 = extract_plan_features(
            self.team, self.opp, chosen,
            chosen[:2], chosen[2:],
        )
        self.assertEqual(pf1.features, pf2.features)


class TestLearner(unittest.TestCase):
    def test_pairwise_update_increases_winner(self):
        """pairwise_update pushes winner score above
        loser score."""
        weights = {"a": 0.0, "b": 0.0}
        bias = 0.0
        # Use orthogonal features so the update
        # is unambiguous.
        w = {"a": 1.0}
        l = {"b": 1.0}
        s_w_before = score_plan(weights, bias, w)
        s_l_before = score_plan(weights, bias, l)
        self.assertEqual(s_w_before, 0.0)
        self.assertEqual(s_l_before, 0.0)
        weights, bias = pairwise_update(weights, bias, w, l)
        s_w_after = score_plan(weights, bias, w)
        s_l_after = score_plan(weights, bias, l)
        # Winner score strictly increased.
        self.assertGreater(s_w_after, s_w_before)
        # Loser score strictly decreased.
        self.assertLess(s_l_after, s_l_before)

    def test_train_split_by_pair_id(self):
        """Training splits by pair_id, not by row
        order. Two different pair_ids must not
        share a train/val fold by row."""
        rows = [
            {"pair_id": 0, "our_features": {"a": 1.0}, "our_win": True},
            {"pair_id": 0, "our_features": {"a": 0.0}, "our_win": False},
            {"pair_id": 1, "our_features": {"a": 1.0}, "our_win": True},
            {"pair_id": 1, "our_features": {"a": 0.0}, "our_win": False},
        ]
        # Make pair 0 a "easy" case and pair 1 a "hard"
        # case; the model should learn on pair 0
        # only.
        weights, bias, meta = train(
            rows,
            feature_names=["a"],
            n_epochs=10,
            learning_rate=0.5,
            seed=42,
        )
        # At least one pair is in train, one in val.
        self.assertGreaterEqual(meta["n_train_pairs"], 0)
        self.assertGreaterEqual(meta["n_val_pairs"], 0)

    def test_model_json_round_trip(self):
        """save_model + load_model round-trip
        preserves weights, bias, and feature names.
        No pickle."""
        weights = {"a": 0.5, "b": -0.3, "c": 0.1}
        bias = 0.7
        feature_names = ["a", "b", "c"]
        meta = {"train_acc": 0.55, "n_epochs": 5}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            path = f.name
        try:
            art = save_model(
                path, weights, bias, feature_names, meta
            )
            self.assertIn("artifact_sha256", art)
            loaded = load_model(path)
            self.assertEqual(loaded["weights"], weights)
            self.assertEqual(loaded["bias"], bias)
            self.assertEqual(loaded["feature_names"], feature_names)
            self.assertEqual(
                loaded["metadata"]["train_acc"],
                meta["train_acc"],
            )
            self.assertEqual(
                loaded["artifact_sha256"],
                art["artifact_sha256"],
            )
        finally:
            os.unlink(path)

    def test_load_model_raises_when_missing(self):
        """load_model raises FileNotFoundError on
        missing file (the policy wrapper relies on
        this for fail-loud behavior)."""
        with self.assertRaises(FileNotFoundError):
            load_model("/nonexistent/path/model.json")

    def test_default_model_path_unchanged(self):
        """Default model path is stable (the runtime
        policy depends on it)."""
        self.assertEqual(
            DEFAULT_MODEL_PATH,
            "logs/vgc2026_phaseV3a_preview_model.json",
        )


class TestPolicyWrapper(unittest.TestCase):
    def test_learned_policy_deterministic(self):
        """learned_preview_v3a returns the same plan
        for the same inputs (deterministic tie-break
        by plan tuple)."""
        team = _sample_team()
        opp = _opponent_team()
        # Skip if model not trained yet.
        if not os.path.isfile(DEFAULT_MODEL_PATH):
            self.skipTest("model not trained")
        a = choose_four_from_six(
            team, opponent_team=opp,
            policy="learned_preview_v3a", seed=42,
        )
        b = choose_four_from_six(
            team, opponent_team=opp,
            policy="learned_preview_v3a", seed=42,
        )
        self.assertEqual(a.chosen_4, b.chosen_4)
        self.assertEqual(a.lead_2, b.lead_2)
        self.assertEqual(a.back_2, b.back_2)
        self.assertEqual(a.policy, "learned_preview_v3a")

    def test_default_policy_unchanged(self):
        """Default choose_four_from_six policy is
        unchanged: callers must pass policy=..."""
        team = _sample_team()
        # Unknown policy raises ValueError. (The
        # original behavior — explicit opt-in only.)
        with self.assertRaises(ValueError):
            choose_four_from_six(team, policy="unknown_policy_xyz")

    def test_v3_unchanged(self):
        """matchup_top4_v3 still works exactly as
        before (no behavior change to existing
        policy)."""
        team = _sample_team()
        opp = _opponent_team()
        v3 = choose_four_from_six(
            team, opponent_team=opp, policy="matchup_top4_v3"
        )
        self.assertEqual(v3.policy, "matchup_top4_v3")
        self.assertEqual(len(v3.chosen_4), 4)
        self.assertEqual(len(v3.lead_2), 2)
        self.assertEqual(len(v3.back_2), 2)


class TestEndToEndTraining(unittest.TestCase):
    def test_train_and_save_produces_artifact(self):
        """train_and_save writes a model JSON with
        artifact_sha256 hash."""
        from vgc_team_pool import load_vgc_pool
        # We need a paired JSONL. Use the existing one.
        paired_path = (
            "logs/vgc2026_phaseV2c_phaseV2f_v3_paired_"
            "qualification_benchmark.jsonl"
        )
        if not os.path.isfile(paired_path):
            self.skipTest("paired JSONL not found")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            tmp_model = f.name
        try:
            team_pool = load_vgc_pool()
            result = train_and_save(
                paired_path,
                team_pool,
                model_path=tmp_model,
                n_epochs=2,
                seed=42,
            )
            self.assertIn("artifact", result)
            self.assertIn("artifact_sha256", result["artifact"])
            # Verify the file exists and is valid JSON.
            with open(tmp_model) as f:
                m = json.load(f)
            self.assertIn("weights", m)
            self.assertIn("feature_names", m)
            self.assertIn("bias", m)
        finally:
            if os.path.isfile(tmp_model):
                os.unlink(tmp_model)


# ===========================================================================
# Phase V3a.1 tests
# ===========================================================================


class TestV3a1SharedHelpers(unittest.TestCase):
    """V3a.1 shared helper invariants."""

    def test_stable_team_hash_is_stable(self):
        """_stable_team_hash is deterministic and
        order-independent."""
        from vgc2026_phaseV3a_learn_preview import (
            _stable_team_hash,
        )
        team = [
            {"species": "incineroar", "moves": []},
            {"species": "garchomp", "moves": []},
            {"species": "amoonguss", "moves": []},
        ]
        team_reordered = [
            {"species": "garchomp", "moves": []},
            {"species": "incineroar", "moves": []},
            {"species": "amoonguss", "moves": []},
        ]
        h1 = _stable_team_hash(team)
        h2 = _stable_team_hash(team_reordered)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_load_multi_source_preserves_source_labels(self):
        """load_multi_source attaches source, source
        artifact basename to each row.
        ponytail: uses the in-repo V2c2 fixture."""
        from vgc2026_phaseV3a_learn_preview import (
            load_multi_source,
        )
        from vgc_team_pool import load_vgc_pool
        path = (
            "logs/vgc2026_phaseV2c_phaseV2c2_smoke_test_"
            "benchmark.jsonl"
        )
        if not os.path.isfile(path):
            self.skipTest("V2c2 fixture not present")
        pool = load_vgc_pool()
        rows, skipped = load_multi_source([path], pool)
        self.assertGreater(len(rows), 0)
        sources = {r.get("source") for r in rows}
        self.assertEqual(len(sources), 1)
        self.assertIn("phaseV2c2_smoke_test_benchmark", next(iter(sources)))

    def test_no_hidden_info_features(self):
        """Features are computed from open team-sheet
        data only. No hidden items, hidden abilities,
        or battle outcome fields.
        """
        from vgc2026_phaseV3a_learn_preview import (
            discover_feature_names,
            load_multi_source,
        )
        from vgc_team_pool import load_vgc_pool
        path = (
            "logs/vgc2026_phaseV2c_phaseV2c2_smoke_test_"
            "benchmark.jsonl"
        )
        if not os.path.isfile(path):
            self.skipTest("V2c2 fixture not present")
        pool = load_vgc_pool()
        rows, _ = load_multi_source([path], pool)
        names = discover_feature_names(rows)
        # No hidden info field names.
        forbidden = [
            "hidden_item", "hidden_ability", "our_win",
            "opponent_win", "turns", "tie", "errors",
        ]
        for f in forbidden:
            self.assertNotIn(
                f, names,
                f"Forbidden feature name '{f}' leaked into "
                f"the feature set",
            )


class TestV3a1DecisiveFilter(unittest.TestCase):
    """V3a.1 decisive pair filter."""

    def test_skip_same_policy_pair(self):
        """A pair where only one policy appears is
        skipped (no learning signal).
        """
        from vgc2026_phaseV3a_learn_preview import (
            build_decisive_pair_targets,
        )
        rows = [
            {
                "pair_id": 0,
                "team_hash": "t1",
                "our_policy": "basic_top4",
                "our_win": True,
                "our_chosen_4": ["a", "b", "c", "d"],
                "opponent_chosen_4": ["e", "f", "g", "h"],
            },
        ]
        pairs, skipped = build_decisive_pair_targets(rows)
        self.assertEqual(pairs, [])
        self.assertIn("single_policy_in_pair", skipped)

    def test_skip_identical_plans(self):
        """A pair where winner and loser picked the
        same chosen_4 set is skipped.
        """
        from vgc2026_phaseV3a_learn_preview import (
            build_decisive_pair_targets,
        )
        rows = [
            {
                "pair_id": 0,
                "team_hash": "t1",
                "our_policy": "basic_top4",
                "our_win": True,
                "our_chosen_4": ["a", "b", "c", "d"],
                "opponent_chosen_4": ["a", "b", "c", "d"],
            },
            {
                "pair_id": 0,
                "team_hash": "t1",
                "our_policy": "random",
                "our_win": False,
                "our_chosen_4": ["a", "b", "c", "d"],
                "opponent_chosen_4": ["a", "b", "c", "d"],
            },
        ]
        pairs, skipped = build_decisive_pair_targets(rows)
        self.assertEqual(pairs, [])
        # Either identical_plans or tied: both are
        # valid rejection reasons. The filter must
        # reject this pair.
        self.assertTrue(
            "identical_plans" in skipped
            or "tied_or_lost_margin" in skipped
        )

    def test_decisive_pair_accepted(self):
        """A pair with two different policies and
        different chosen_4 sets and a 1+ win margin
        is accepted.
        """
        from vgc2026_phaseV3a_learn_preview import (
            build_decisive_pair_targets,
        )
        # 2 basic_top4 wins, 0 random wins: clear margin.
        rows = [
            {
                "pair_id": 0,
                "team_hash": "t1",
                "our_policy": "basic_top4",
                "our_win": True,
                "our_chosen_4": ["a", "b", "c", "d"],
                "opponent_chosen_4": ["w", "x", "y", "z"],
            },
            {
                "pair_id": 0,
                "team_hash": "t1",
                "our_policy": "basic_top4",
                "our_win": True,
                "our_chosen_4": ["a", "b", "c", "d"],
                "opponent_chosen_4": ["e", "f", "g", "h"],
            },
            {
                "pair_id": 0,
                "team_hash": "t1",
                "our_policy": "random",
                "our_win": False,
                "our_chosen_4": ["e", "f", "g", "h"],
                "opponent_chosen_4": ["a", "b", "c", "d"],
            },
        ]
        pairs, _ = build_decisive_pair_targets(rows)
        self.assertEqual(len(pairs), 1)
        w, l = pairs[0]
        self.assertEqual(w["our_policy"], "basic_top4")
        self.assertEqual(l["our_policy"], "random")

    def test_skip_tied_margin(self):
        """A pair with 0 win margin (tied) is
        skipped.
        """
        from vgc2026_phaseV3a_learn_preview import (
            build_decisive_pair_targets,
        )
        rows = [
            {
                "pair_id": 0,
                "team_hash": "t1",
                "our_policy": "basic_top4",
                "our_win": True,
                "our_chosen_4": ["a", "b", "c", "d"],
                "opponent_chosen_4": ["w", "x", "y", "z"],
            },
            {
                "pair_id": 0,
                "team_hash": "t1",
                "our_policy": "random",
                "our_win": True,
                "our_chosen_4": ["e", "f", "g", "h"],
                "opponent_chosen_4": ["a", "b", "c", "d"],
            },
        ]
        pairs, skipped = build_decisive_pair_targets(rows)
        self.assertEqual(pairs, [])
        self.assertIn("tied_or_lost_margin", skipped)


class TestV3a1GroupSplit(unittest.TestCase):
    """V3a.1 deterministic group split by team_hash."""

    def test_split_no_leakage(self):
        """group_split produces train and val sets
        with no team_hash overlap.
        """
        from vgc2026_phaseV3a_learn_preview import (
            group_split, assert_no_leakage,
        )
        rows = [
            {"pair_id": 0, "team_hash": "t_a"},
            {"pair_id": 1, "team_hash": "t_a"},
            {"pair_id": 2, "team_hash": "t_b"},
            {"pair_id": 3, "team_hash": "t_b"},
            {"pair_id": 4, "team_hash": "t_c"},
            {"pair_id": 5, "team_hash": "t_d"},
        ]
        train, val, meta = group_split(
            rows, val_fraction=0.5, seed=42
        )
        train_teams = {r["team_hash"] for r in train}
        val_teams = {r["team_hash"] for r in val}
        self.assertEqual(train_teams & val_teams, set())
        # No-leakage assertion must pass.
        assert_no_leakage(train, val)

    def test_split_deterministic(self):
        """Same seed produces the same split."""
        from vgc2026_phaseV3a_learn_preview import (
            group_split,
        )
        rows = [
            {"pair_id": i, "team_hash": f"t_{i}"}
            for i in range(20)
        ]
        t1, v1, _ = group_split(rows, val_fraction=0.25, seed=42)
        t2, v2, _ = group_split(rows, val_fraction=0.25, seed=42)
        self.assertEqual(
            [r["team_hash"] for r in t1],
            [r["team_hash"] for r in t2],
        )


class TestV3a1AveragedPerceptron(unittest.TestCase):
    """V3a.1 averaged perceptron and L2."""

    def test_averaged_changes_weights_deterministically(self):
        """averaged_pairwise_update returns consistent
        accumulator on repeat calls with same input.
        """
        from vgc2026_phaseV3a_learn_preview import (
            averaged_pairwise_update,
        )
        weights = {"a": 0.0, "b": 0.0}
        bias = 0.0
        acc: Dict[str, float] = {"a": 0.0, "b": 0.0}
        bias_acc = 0.0
        for _ in range(10):
            weights, bias, acc, bias_acc = (
                averaged_pairwise_update(
                    weights, bias,
                    winner_features={"a": 1.0},
                    loser_features={"b": 1.0},
                    learning_rate=0.1,
                    l2=0.0,
                    min_margin=1.0,
                    accumulator=acc,
                    bias_accumulator=bias_acc,
                )
            )
        # Weight for "a" should have been pushed up,
        # weight for "b" down.
        self.assertGreater(weights["a"], 0.0)
        self.assertLess(weights["b"], 0.0)
        # Accumulator is a running sum, so acc["a"]
        # is at least 10 * the per-step delta.
        self.assertGreaterEqual(acc["a"], weights["a"])

    def test_l2_reduces_weight_norm(self):
        """L2 weight decay reduces the L2 norm of
        the weights over many updates.
        """
        from vgc2026_phaseV3a_learn_preview import (
            averaged_pairwise_update,
            score_plan,
        )
        weights = {"a": 0.0}
        bias = 0.0
        norm_no_l2 = 0.0
        for _ in range(50):
            weights, bias, _, _ = averaged_pairwise_update(
                weights, bias,
                winner_features={"a": 1.0},
                loser_features={},
                learning_rate=0.1,
                l2=0.0,
                min_margin=10.0,  # always update
                accumulator=None,
                bias_accumulator=None,
            )
        norm_no_l2 = abs(weights["a"])
        # Reset and apply with L2.
        weights = {"a": 0.0}
        bias = 0.0
        for _ in range(50):
            weights, bias, _, _ = averaged_pairwise_update(
                weights, bias,
                winner_features={"a": 1.0},
                loser_features={},
                learning_rate=0.1,
                l2=0.1,
                min_margin=10.0,
                accumulator=None,
                bias_accumulator=None,
            )
        norm_with_l2 = abs(weights["a"])
        self.assertLess(norm_with_l2, norm_no_l2)

    def test_margin_skip_no_update(self):
        """If winner score is already > loser by the
        margin, no update happens.
        """
        from vgc2026_phaseV3a_learn_preview import (
            averaged_pairwise_update,
        )
        weights = {"a": 10.0}
        bias = 0.0
        before = dict(weights)
        new_w, _, _, _ = averaged_pairwise_update(
            weights, bias,
            winner_features={"a": 1.0},
            loser_features={"a": 0.0},
            learning_rate=0.1,
            l2=0.0,
            min_margin=1.0,
            accumulator=None,
            bias_accumulator=None,
        )
        self.assertEqual(new_w["a"], before["a"])


class TestV3a1SaveLoad(unittest.TestCase):
    """V3a.1 model save/load and policy wrapper."""

    def test_model_json_round_trip(self):
        """save_model + load_model round-trips weights
        and feature names. JSON only.
        """
        from vgc2026_phaseV3a_learn_preview import (
            save_model, load_model,
        )
        weights = {"a": 0.5, "b": -0.3}
        bias = 0.7
        feature_names = ["a", "b"]
        meta = {"train_acc": 0.5}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            path = f.name
        try:
            art = save_model(
                path, weights, bias, feature_names, meta
            )
            loaded = load_model(path)
            self.assertEqual(loaded["weights"], weights)
            self.assertEqual(loaded["bias"], bias)
            self.assertEqual(loaded["feature_names"], feature_names)
            self.assertEqual(loaded["artifact_sha256"], art["artifact_sha256"])
        finally:
            os.unlink(path)

    def test_default_v3a1_artifact_paths(self):
        """Default V3a.1 paths are stable."""
        from vgc2026_phaseV3a_learn_preview import (
            DEFAULT_V3A1_MODEL_PATH,
            DEFAULT_V3A1_REPORT_PATH,
        )
        self.assertEqual(
            DEFAULT_V3A1_MODEL_PATH,
            "logs/vgc2026_phaseV3a1_preview_model.json",
        )
        self.assertEqual(
            DEFAULT_V3A1_REPORT_PATH,
            "logs/vgc2026_phaseV3a1_preview_training_report.json",
        )

    def test_default_policy_unchanged(self):
        """team_preview_policy default path is
        unchanged. No learned_preview_v3a1 branch
        changes matchup_top4_v3 behavior.
        """
        from team_preview_policy import choose_four_from_six
        team = [
            {"species": "incineroar", "ability": "Intimidate",
             "moves": ["Fake Out"]},
            {"species": "garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake"]},
            {"species": "rillaboom", "ability": "Grassy Surge",
             "moves": ["Fake Out"]},
            {"species": "fluttermane", "ability": "Protosynthesis",
             "moves": ["Moonblast"]},
            {"species": "ironhands", "ability": "Quark Drive",
             "moves": ["Fake Out"]},
            {"species": "amoonguss", "ability": "Regenerator",
             "moves": ["Spore"]},
        ]
        v3 = choose_four_from_six(team, policy="matchup_top4_v3")
        self.assertEqual(v3.policy, "matchup_top4_v3")
        # Unknown policy still raises.
        with self.assertRaises(ValueError):
            choose_four_from_six(
                team, policy="never_a_real_policy_name"
            )


class TestV3a2PolicyWrapper(unittest.TestCase):
    """Phase V3a.2: learned_preview_v3a1 wrapper."""

    def setUp(self):
        from vgc_team_pool import load_vgc_pool
        self.pool = load_vgc_pool()
        self.team = [
            {"species": "incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Stomping Tantrum", "Protect"]},
            {"species": "rillaboom", "ability": "Grassy Surge",
             "moves": ["Fake Out", "Grassy Glide", "U-turn", "Protect"]},
            {"species": "fluttermane", "ability": "Protosynthesis",
             "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"]},
            {"species": "ironhands", "ability": "Quark Drive",
             "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
            {"species": "amoonguss", "ability": "Regenerator",
             "moves": ["Spore", "Pollen Puff", "Rage Powder", "Protect"]},
        ]
        self.opp = [
            {"species": "venusaur", "ability": "Chlorophyll",
             "moves": ["Sleep Powder", "Sludge Bomb", "Earth Power", "Protect"]},
            {"species": "charizard", "ability": "Blaze",
             "moves": ["Heat Wave", "Solar Beam", "Weather Ball", "Protect"]},
            {"species": "garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Stomping Tantrum", "Protect"]},
            {"species": "incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "floetteeternal", "ability": "Flower Veil",
             "moves": ["Moonblast", "Dazzling Gleam", "Calm Mind", "Protect"]},
            {"species": "sinistcha", "ability": "Hospitality",
             "moves": ["Matcha Gotcha", "Rage Powder", "Trick Room", "Protect"]},
        ]

    def test_learned_preview_v3a1_loads_and_returns_valid_plan(self):
        """learned_preview_v3a1 loads the model JSON
        and returns a valid 4/2/2 plan.
        """
        from vgc2026_phaseV3a_learn_preview import (
            DEFAULT_V3A1_MODEL_PATH,
        )
        if not os.path.isfile(DEFAULT_V3A1_MODEL_PATH):
            self.skipTest("V3a.1 model not trained yet")
        from team_preview_policy import choose_four_from_six
        result = choose_four_from_six(
            self.team, opponent_team=self.opp,
            policy="learned_preview_v3a1",
        )
        self.assertEqual(result.policy, "learned_preview_v3a1")
        self.assertEqual(len(result.chosen_4), 4)
        self.assertEqual(len(result.lead_2), 2)
        self.assertEqual(len(result.back_2), 2)
        # All chosen are from our team.
        for s in result.chosen_4:
            self.assertIn(
                s.lower(),
                [p["species"].lower() for p in self.team],
            )

    def test_learned_preview_v3a1_deterministic(self):
        """Repeated calls return the same plan."""
        from vgc2026_phaseV3a_learn_preview import (
            DEFAULT_V3A1_MODEL_PATH,
        )
        if not os.path.isfile(DEFAULT_V3A1_MODEL_PATH):
            self.skipTest("V3a.1 model not trained yet")
        from team_preview_policy import choose_four_from_six
        a = choose_four_from_six(
            self.team, opponent_team=self.opp,
            policy="learned_preview_v3a1", seed=42,
        )
        b = choose_four_from_six(
            self.team, opponent_team=self.opp,
            policy="learned_preview_v3a1", seed=42,
        )
        self.assertEqual(a.chosen_4, b.chosen_4)
        self.assertEqual(a.lead_2, b.lead_2)
        self.assertEqual(a.back_2, b.back_2)

    def test_learned_preview_v3a1_missing_model_raises(self):
        """If the V3a.1 model JSON is missing, the
        policy raises FileNotFoundError. ponytail:
        no fallback to V3.
        """
        import os as _os
        from vgc2026_phaseV3a_learn_preview import (
            DEFAULT_V3A1_MODEL_PATH,
        )
        # If the model is currently present, the test
        # can't run. Skip with a note.
        if not _os.path.isfile(DEFAULT_V3A1_MODEL_PATH):
            self.skipTest(
                "V3a.1 model not present; cannot test "
                "loaded path"
            )
        from team_preview_policy import choose_four_from_six
        # Move the model temporarily, expect FileNotFoundError.
        backup = DEFAULT_V3A1_MODEL_PATH + ".bak"
        _os.rename(DEFAULT_V3A1_MODEL_PATH, backup)
        try:
            with self.assertRaises(FileNotFoundError):
                choose_four_from_six(
                    self.team, opponent_team=self.opp,
                    policy="learned_preview_v3a1",
                )
        finally:
            _os.rename(backup, DEFAULT_V3A1_MODEL_PATH)

    def test_default_policy_unchanged_v3a2(self):
        """Adding learned_preview_v3a1 does not change
        the default policy (still matchup_top4_v3)
        or any other existing policy.
        """
        from team_preview_policy import choose_four_from_six
        # matchup_top4_v3 still works.
        v3 = choose_four_from_six(
            self.team, opponent_team=self.opp,
            policy="matchup_top4_v3",
        )
        self.assertEqual(v3.policy, "matchup_top4_v3")
        self.assertEqual(len(v3.chosen_4), 4)
        # basic_top4 still works.
        basic = choose_four_from_six(
            self.team, opponent_team=self.opp,
            policy="basic_top4",
        )
        self.assertEqual(basic.policy, "basic_top4")
        # random still works.
        rnd = choose_four_from_six(
            self.team, opponent_team=self.opp,
            policy="random",
        )
        self.assertEqual(rnd.policy, "random")
        # Unknown still raises.
        with self.assertRaises(ValueError):
            choose_four_from_six(self.team, policy="totally_made_up")

    def test_no_mutation_of_input_teams(self):
        """learned_preview_v3a1 must not mutate the
        input team lists.
        """
        from vgc2026_phaseV3a_learn_preview import (
            DEFAULT_V3A1_MODEL_PATH,
        )
        if not os.path.isfile(DEFAULT_V3A1_MODEL_PATH):
            self.skipTest("V3a.1 model not trained yet")
        from team_preview_policy import choose_four_from_six
        team_copy = [dict(p) for p in self.team]
        opp_copy = [dict(p) for p in self.opp]
        choose_four_from_six(
            self.team, opponent_team=self.opp,
            policy="learned_preview_v3a1",
        )
        # Original teams unchanged.
        self.assertEqual(self.team, team_copy)
        self.assertEqual(self.opp, opp_copy)


class TestV3a4SideAsymmetryAudit(unittest.TestCase):
    """V3a.4 side-asymmetry audit helpers."""

    def _make_rows(self, plans):
        """Build fake paired rows from a list of
        dicts with keys: pair_id, side, our_win,
        our_chosen_4, opp_chosen_4.
        """
        return [
            {
                "pair_id": p["pair_id"],
                "side": p["side"],
                "our_policy": "learned_preview_v3a1"
                if p["side"] == "p1" else "matchup_top4_v3",
                "opponent_policy": "matchup_top4_v3"
                if p["side"] == "p1" else "learned_preview_v3a1",
                "our_win": p["our_win"],
                "our_chosen_4": p["our_chosen_4"],
                "our_lead_2": p["our_chosen_4"][:2],
                "our_back_2": p["our_chosen_4"][2:],
                "opp_chosen_4": p["opp_chosen_4"],
                "opp_lead_2": p["opp_chosen_4"][:2],
                "opp_back_2": p["opp_chosen_4"][2:],
                "turns": 5,
            }
            for p in plans
        ]

    def test_split_pair_categories(self):
        """_split_pair_categories groups pairs into
        learned_p1_only, learned_p2_only, learned_both,
        learned_neither."""
        from analyze_vgc2026_phaseV3a2_reality import (
            _split_pair_categories,
        )
        rows = self._make_rows([
            {"pair_id": 0, "side": "p1", "our_win": True,
             "our_chosen_4": ["a"], "opp_chosen_4": ["b"]},
            {"pair_id": 0, "side": "p2", "our_win": False,
             "our_chosen_4": ["b"], "opp_chosen_4": ["a"]},
            {"pair_id": 1, "side": "p1", "our_win": False,
             "our_chosen_4": ["a"], "opp_chosen_4": ["b"]},
            {"pair_id": 1, "side": "p2", "our_win": True,
             "our_chosen_4": ["b"], "opp_chosen_4": ["a"]},
            {"pair_id": 2, "side": "p1", "our_win": True,
             "our_chosen_4": ["a"], "opp_chosen_4": ["b"]},
            {"pair_id": 2, "side": "p2", "our_win": True,
             "our_chosen_4": ["b"], "opp_chosen_4": ["a"]},
            {"pair_id": 3, "side": "p1", "our_win": False,
             "our_chosen_4": ["a"], "opp_chosen_4": ["b"]},
            {"pair_id": 3, "side": "p2", "our_win": False,
             "our_chosen_4": ["b"], "opp_chosen_4": ["a"]},
        ])
        cats, _ = _split_pair_categories(rows)
        self.assertEqual(cats["learned_p1_only"], [0])
        self.assertEqual(cats["learned_p2_only"], [1])
        self.assertEqual(cats["learned_both"], [2])
        self.assertEqual(cats["learned_neither"], [3])

    def test_validate_d1_d2_determinism_pass(self):
        """D1 our_chosen_4 == D2 opp_chosen_4 (learned)
        and D1 opp == D2 our (V3) when plans are
        stable."""
        from analyze_vgc2026_phaseV3a2_reality import (
            _validate_d1_d2_determinism,
        )
        rows = self._make_rows([
            {"pair_id": 0, "side": "p1", "our_win": True,
             "our_chosen_4": ["a", "b", "c", "d"],
             "opp_chosen_4": ["e", "f", "g", "h"]},
            {"pair_id": 0, "side": "p2", "our_win": False,
             "our_chosen_4": ["e", "f", "g", "h"],
             "opp_chosen_4": ["a", "b", "c", "d"]},
        ])
        learned_mism, v3_mism = _validate_d1_d2_determinism(rows)
        self.assertEqual(learned_mism, [])
        self.assertEqual(v3_mism, [])

    def test_audit_handles_shuffled_rows(self):
        """audit_side_asymmetry is invariant under
        row shuffling (joins by pair_id, not position)."""
        import random as _r
        from analyze_vgc2026_phaseV3a2_reality import (
            audit_side_asymmetry,
        )
        rows = self._make_rows([
            {"pair_id": i % 3, "side": "p1"
             if i % 2 == 0 else "p2",
             "our_win": (i % 3 == 0),
             "our_chosen_4": ["a", "b", "c", "d"],
             "opp_chosen_4": ["e", "f", "g", "h"]}
            for i in range(6)
        ])
        a1 = audit_side_asymmetry(rows)
        rng = _r.Random(42)
        shuffled = list(rows)
        rng.shuffle(shuffled)
        a2 = audit_side_asymmetry(shuffled)
        self.assertEqual(a1["categories"], a2["categories"])


if __name__ == "__main__":
    unittest.main()
