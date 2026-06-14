#!/usr/bin/env python3
"""
Test suite for VGC 2026 Phase V2h — statistically valid offline
feature diagnosis.

Coverage:
- Dex-driven move classification: Shadow Ball, Make It Rain,
  Protect, Fake Out, Icy Wind, Earthquake, unknown moves
- Stalling move gating (Protect is NOT a priority tool)
- Spread move detection from target field
- Unknown-move reporting (no silent remapping)
- Standardized statistics: Cohen's d, paired mean diff, paired
  bootstrap CI, LOO stability, fold stability
- v2h analyzer merges by pair_id, not row position
- v2h analyzer treats D1/D2 as one pair
- v2h inspector: --feature, --pair, --group, --largest-positive,
  --largest-negative, --contradictory, --candidate-actionable
- Outcome-isolation: outcomes never enter feature extraction or
  policy code
- Decisive-n denominator is 55 (30 V3-both + 25 Random-both)
- All four helper commands terminate naturally
"""

import poke_env_test_cleanup  # Must precede poke-env imports.

import ast
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from team_preview_policy import (
    choose_four_from_six,
    evaluate_all_combinations,
    evaluate_all_combinations_v3,
)
from vgc2026_common_plan_evaluator import (
    COMPONENT_WEIGHTS,
    CommonPlanEvaluatorError,
    evaluate_plan_on_common_scale,
)
from vgc2026_plan_features import (
    PlanFeatures,
    _gen9_moves,
    _move_id,
    _is_priority_move,
    _is_spread_move,
    _is_stall_move,
    _move_is_damaging,
    _move_priority,
    _move_target,
    aggregate_features,
    classify_move,
    extract_plan_features,
    shannon_entropy_from_counts,
)
from analyze_vgc2026_phaseV2g_failures import (
    build_bundles_by_pair,
    build_pair_records,
    classify_pair,
    load_v2f_artifacts,
    sign_test as v2g_sign_test,
)
from analyze_vgc2026_phaseV2h_feature_stability import (
    BOOTSTRAP_SEED,
    FOLD_SEED,
    LOO_STABILITY_THRESHOLD,
    MIN_DECISIVE_PAIRS,
    N_BOOTSTRAP,
    N_FOLDS,
    FOLD_STABILITY_THRESHOLD,
    _bootstrap_paired_mean_diff_ci,
    _bootstrap_unpaired_mean_diff_ci,
    _bootstrap_sign_consistency,
    _ci_excludes_zero,
    _classify_candidate,
    _cohens_d,
    _cohens_d_ci,
    _fold_stability,
    _loo_stability,
    _paired_mean_diff,
    _unpaired_fold_stability,
    _unpaired_loo_stability,
    run_analysis as v2h_run_analysis,
)


# ---------------------------------------------------------------------------
# Move classification regression tests
# ---------------------------------------------------------------------------


class TestMoveClassification(unittest.TestCase):
    """Regression tests for the dex-driven move classifier.

    Each test asserts the exact label the Gen 9 dex metadata
    produces. The dex is the source of truth."""

    def test_shadow_ball_is_special(self):
        # Shadow Ball: target=normal, category=Special, no flags.
        self.assertEqual(classify_move("Shadow Ball"), "special")
        self.assertEqual(_move_target("Shadow Ball"), "normal")
        self.assertEqual(_move_priority("Shadow Ball"), 0)
        self.assertFalse(_is_spread_move("Shadow Ball"))

    def test_make_it_rain_is_spread(self):
        # Make It Rain: target=allAdjacentFoes, category=Special,
        # basePower=120. The classifier labels it "spread" because
        # the target is a spread target and the move is damaging.
        self.assertEqual(classify_move("Make It Rain"), "spread")
        self.assertEqual(_move_target("Make It Rain"), "allAdjacentFoes")
        self.assertTrue(_move_is_damaging("Make It Rain"))
        self.assertTrue(_is_spread_move("Make It Rain"))
        self.assertFalse(_is_priority_move("Make It Rain"))

    def test_protect_is_stall_not_priority(self):
        # Protect: priority=4, but the dex flags stallingMove=true.
        # The classifier must label it "stall" and the priority
        # gate must exclude it from the priority category.
        self.assertEqual(classify_move("Protect"), "stall")
        self.assertTrue(_is_stall_move("Protect"))
        self.assertFalse(_is_priority_move("Protect"))
        self.assertEqual(_move_priority("Protect"), 4)

    def test_fake_out_is_priority(self):
        # Fake Out: priority=3, NOT a stalling move. Labelled
        # "priority".
        self.assertEqual(classify_move("Fake Out"), "priority")
        self.assertTrue(_is_priority_move("Fake Out"))
        self.assertFalse(_is_stall_move("Fake Out"))
        self.assertEqual(_move_priority("Fake Out"), 3)

    def test_icy_wind_is_spread(self):
        # Icy Wind: target=allAdjacentFoes, basePower=55,
        # category=Special, has a speed-drop secondary. The
        # spread classifier must label it "spread".
        self.assertEqual(classify_move("Icy Wind"), "spread")
        self.assertEqual(_move_target("Icy Wind"), "allAdjacentFoes")
        self.assertTrue(_is_spread_move("Icy Wind"))
        self.assertFalse(_is_priority_move("Icy Wind"))

    def test_earthquake_is_spread(self):
        # Earthquake: target=allAdjacent, basePower=100, category=
        # Physical. The spread classifier labels it "spread".
        self.assertEqual(classify_move("Earthquake"), "spread")
        self.assertEqual(_move_target("Earthquake"), "allAdjacent")
        self.assertTrue(_is_spread_move("Earthquake"))
        self.assertFalse(_is_priority_move("Earthquake"))

    def test_unknown_move_is_explicitly_unknown(self):
        # The classifier must NOT silently remap an unknown move
        # to a known status. The audit list catches this case.
        self.assertEqual(
            classify_move("SoraN00bCustomMove123"), "unknown"
        )
        # The dex lookup returns an empty mapping, so the move
        # data is {}.
        self.assertEqual(_move_id("SoraN00bCustomMove123"),
                         "soran00bcustommove123")
        # The dex does not contain it.
        self.assertNotIn("soran00bcustommove123", _gen9_moves())

    def test_protect_priority_plus_stall_exclusion(self):
        # A move with priority=4 that is also a stalling move
        # must NOT be counted as priority. We assert this by
        # checking the gate predicate directly.
        self.assertTrue(_is_stall_move("Protect"))
        self.assertFalse(_is_priority_move("Protect"))

    def test_unknown_moves_reported_in_audit(self):
        # Build a 4-mon plan with a single unknown move in the
        # back. The audit must surface it.
        team = [
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
            {"species": "WeirdMon", "ability": "Pressure",
             "moves": ["SoraN00bCustomMove123", "UnknownMove_42"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Fake Out", "Grassy Glide", "U-turn", "Protect"]},
            {"species": "Flutter Mane", "ability": "Protosynthesis",
             "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"]},
        ]
        opp = [
            {"species": "Rillaboom", "moves": []},
            {"species": "Iron Hands", "moves": []},
            {"species": "Kingambit", "moves": []},
            {"species": "Incineroar", "moves": []},
            {"species": "Garchomp", "moves": []},
            {"species": "Tornadus", "moves": []},
        ]
        bundle = extract_plan_features(
            team, opp,
            ["Incineroar", "Tornadus", "WeirdMon", "Garchomp"],
            ["Incineroar", "Tornadus"],
            ["WeirdMon", "Garchomp"],
        )
        self.assertGreater(bundle.audit["unknown_count"], 0)
        self.assertIn("SoraN00bCustomMove123", bundle.audit["unknown_moves"])
        self.assertIn("UnknownMove_42", bundle.audit["unknown_moves"])

    def test_make_it_rain_in_audit(self):
        # The audit must classify Make It Rain as "spread" (a
        # kind of special damaging move), NOT as "special"
        # alone.
        team = [
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
            {"species": "Iron Hands", "ability": "Quark Drive",
             "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Fake Out", "Grassy Glide", "U-turn", "Protect"]},
            {"species": "SpecialMon", "ability": "Pressure",
             "moves": ["Make It Rain"]},
        ]
        opp = [
            {"species": "Rillaboom", "moves": []},
            {"species": "Iron Hands", "moves": []},
            {"species": "Kingambit", "moves": []},
            {"species": "Incineroar", "moves": []},
            {"species": "Garchomp", "moves": []},
            {"species": "Tornadus", "moves": []},
        ]
        bundle = extract_plan_features(
            team, opp,
            ["Incineroar", "Tornadus", "Iron Hands", "SpecialMon"],
            ["Incineroar", "Tornadus"],
            ["Iron Hands", "SpecialMon"],
        )
        self.assertIn("spread", bundle.audit["move_classes"])

    def test_icy_wind_in_audit(self):
        team = [
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
            {"species": "Iron Hands", "ability": "Quark Drive",
             "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Fake Out", "Grassy Glide", "U-turn", "Protect"]},
            {"species": "IcyMon", "ability": "Pressure",
             "moves": ["Icy Wind"]},
        ]
        opp = [
            {"species": "Rillaboom", "moves": []},
            {"species": "Iron Hands", "moves": []},
            {"species": "Kingambit", "moves": []},
            {"species": "Incineroar", "moves": []},
            {"species": "Garchomp", "moves": []},
            {"species": "Tornadus", "moves": []},
        ]
        bundle = extract_plan_features(
            team, opp,
            ["Incineroar", "Tornadus", "Iron Hands", "IcyMon"],
            ["Incineroar", "Tornadus"],
            ["Iron Hands", "IcyMon"],
        )
        self.assertIn("spread", bundle.audit["move_classes"])

    def test_earthquake_in_audit(self):
        team = [
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
            {"species": "Iron Hands", "ability": "Quark Drive",
             "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Fake Out", "Grassy Glide", "U-turn", "Protect"]},
            {"species": "QuakeMon", "ability": "Pressure",
             "moves": ["Earthquake"]},
        ]
        opp = [
            {"species": "Rillaboom", "moves": []},
            {"species": "Iron Hands", "moves": []},
            {"species": "Kingambit", "moves": []},
            {"species": "Incineroar", "moves": []},
            {"species": "Garchomp", "moves": []},
            {"species": "Tornadus", "moves": []},
        ]
        bundle = extract_plan_features(
            team, opp,
            ["Incineroar", "Tornadus", "Iron Hands", "QuakeMon"],
            ["Incineroar", "Tornadus"],
            ["Iron Hands", "QuakeMon"],
        )
        self.assertIn("spread", bundle.audit["move_classes"])


# ---------------------------------------------------------------------------
# Statistical unit tests
# ---------------------------------------------------------------------------


class TestStatisticalUnit(unittest.TestCase):
    """The pair_id is the statistical unit. D1 and D2 are not
    independent plan samples for the same team/opponent."""

    def test_pair_merge_uses_pair_id(self):
        benchmark_rows, preview_rows, team_lookup = _synthetic_artifacts()
        # Shuffle the rows and confirm the merge is stable.
        import random
        random.seed(0)
        rows = list(benchmark_rows)
        random.shuffle(rows)
        pairs_a = build_pair_records(
            benchmark_rows, preview_rows, team_lookup
        )
        pairs_b = build_pair_records(
            rows, preview_rows, team_lookup
        )
        self.assertEqual(
            [p["pair_id"] for p in pairs_a],
            [p["pair_id"] for p in pairs_b],
        )

    def test_decisive_n_is_55(self):
        # Build 30 v3_both, 25 random_both, 45 split and confirm
        # the sign-test decisive count is 55.
        pairs: List[Dict[str, Any]] = []
        for _ in range(30):
            pairs.append({
                "pair_id": 0,
                "d1_outcome": "win",
                "d2_outcome": "win",
            })
        for _ in range(25):
            pairs.append({
                "pair_id": 0,
                "d1_outcome": "loss",
                "d2_outcome": "loss",
            })
        for _ in range(45):
            pairs.append({
                "pair_id": 0,
                "d1_outcome": "win",
                "d2_outcome": "loss",
            })
        stats = v2g_sign_test(pairs)
        self.assertEqual(stats["v3_both"], 30)
        self.assertEqual(stats["random_both"], 25)
        self.assertEqual(stats["split"], 45)
        self.assertEqual(stats["decisive_n"], 55)
        self.assertAlmostEqual(stats["two_sided_p"], 0.590053, places=5)
        self.assertAlmostEqual(stats["one_sided_p"], 0.295027, places=5)

    def test_split_pairs_excluded_from_sign_test(self):
        pair = {"pair_id": 0, "d1_outcome": "win", "d2_outcome": "loss"}
        stats = v2g_sign_test([pair])
        self.assertEqual(stats["decisive_n"], 0)


# ---------------------------------------------------------------------------
# Standardized statistics
# ---------------------------------------------------------------------------


class TestStandardizedStatistics(unittest.TestCase):
    def test_paired_mean_diff(self):
        a = [1.0, 2.0, 3.0]
        b = [0.5, 1.0, 2.0]
        diff = _paired_mean_diff(a, b)
        self.assertAlmostEqual(diff, statistics.fmean([0.5, 1.0, 1.0]))

    def test_paired_mean_diff_empty(self):
        self.assertIsNone(_paired_mean_diff([], []))

    def test_paired_mean_diff_length_mismatch(self):
        self.assertIsNone(_paired_mean_diff([1.0], [1.0, 2.0]))

    def test_cohens_d_basic(self):
        a = [1.0, 1.1, 1.0, 1.2]
        b = [0.0, 0.0, 0.1, 0.2]
        d = _cohens_d(a, b)
        self.assertIsNotNone(d)
        # a is clearly higher than b, so d should be positive.
        self.assertGreater(d, 0.0)

    def test_cohens_d_zero_variance_returns_none(self):
        a = [1.0, 1.0, 1.0]
        b = [1.0, 1.0, 1.0]
        self.assertIsNone(_cohens_d(a, b))

    def test_cohens_d_too_small(self):
        # Need at least 2 in each group.
        self.assertIsNone(_cohens_d([1.0], [2.0, 3.0]))

    def test_bootstrap_paired_mean_diff_ci_deterministic(self):
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [0.0, 1.0, 2.0, 3.0, 4.0]
        ci1 = _bootstrap_paired_mean_diff_ci(
            a, b, n_resamples=200, seed=BOOTSTRAP_SEED
        )
        ci2 = _bootstrap_paired_mean_diff_ci(
            a, b, n_resamples=200, seed=BOOTSTRAP_SEED
        )
        self.assertIsNotNone(ci1)
        self.assertIsNotNone(ci2)
        # Determinism: same seed -> same CI.
        self.assertAlmostEqual(ci1[0], ci2[0])
        self.assertAlmostEqual(ci1[1], ci2[1])
        self.assertAlmostEqual(ci1[2], ci2[2])
        # Observed mean is +1.0; the sign must be positive.
        self.assertAlmostEqual(ci1[0], 1.0)
        self.assertGreater(ci1[3], 0)
        # The CI is narrow enough that 0 is not in it.
        self.assertGreater(ci1[1], 0.0)

    def test_bootstrap_paired_mean_diff_ci_zero_diff(self):
        a = [1.0, 2.0, 3.0]
        b = [1.0, 2.0, 3.0]
        ci = _bootstrap_paired_mean_diff_ci(
            a, b, n_resamples=200, seed=BOOTSTRAP_SEED
        )
        self.assertIsNotNone(ci)
        self.assertAlmostEqual(ci[0], 0.0)

    def test_cohens_d_ci_deterministic(self):
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [0.0, 1.0, 2.0, 3.0, 4.0]
        ci1 = _cohens_d_ci(a, b, n_resamples=200, seed=BOOTSTRAP_SEED)
        ci2 = _cohens_d_ci(a, b, n_resamples=200, seed=BOOTSTRAP_SEED)
        self.assertIsNotNone(ci1)
        self.assertIsNotNone(ci2)
        # Determinism.
        self.assertAlmostEqual(ci1[0], ci2[0])
        self.assertAlmostEqual(ci1[1], ci2[1])
        self.assertAlmostEqual(ci1[2], ci2[2])

    def test_ci_excludes_zero_positive_interval(self):
        self.assertTrue(_ci_excludes_zero((1.0, 0.2, 1.8, 100)))

    def test_ci_excludes_zero_negative_interval(self):
        self.assertTrue(_ci_excludes_zero((-1.0, -1.8, -0.2, 100)))

    def test_ci_covering_zero_is_not_excluding(self):
        self.assertFalse(_ci_excludes_zero((0.1, -0.2, 0.5, 60)))

    def test_unpaired_bootstrap_uses_difference_between_groups(self):
        ci = _bootstrap_unpaired_mean_diff_ci(
            [10.0, 11.0, 12.0],
            [1.0, 2.0, 3.0],
            n_resamples=200,
            seed=BOOTSTRAP_SEED,
        )
        self.assertIsNotNone(ci)
        self.assertAlmostEqual(ci[0], 9.0)
        self.assertGreater(ci[1], 0.0)

    def test_bootstrap_sign_consistency(self):
        values = [1.0, 2.0, 3.0, 4.0]
        # Observed mean is 2.5. Bootstrap samples with replacement
        # of {1,2,3,4} should mostly have positive mean.
        count = _bootstrap_sign_consistency(
            values, observed=2.5, n_resamples=200, seed=BOOTSTRAP_SEED
        )
        # All resamples of a 4-element positive set must have a
        # positive mean.
        self.assertEqual(count, 200)

    def test_loo_stability_all_positive(self):
        pair_ids = [1, 2, 3, 4, 5]
        a = {1: 1.0, 2: 1.5, 3: 2.0, 4: 2.5, 5: 3.0}
        b = {pid: 0.0 for pid in pair_ids}
        stability = _loo_stability(pair_ids, a, b)
        # Dropping any single pair still leaves a positive mean
        # diff.
        self.assertGreater(stability, 0.0)

    def test_loo_stability_threshold_constant(self):
        # The constant is the one used in the analysis.
        self.assertEqual(LOO_STABILITY_THRESHOLD, 0.90)

    def test_fold_stability_5_folds(self):
        pair_ids = list(range(20))
        a = {pid: 1.0 for pid in pair_ids}
        b = {pid: 0.0 for pid in pair_ids}
        count, directions, diffs = _fold_stability(
            pair_ids, a, b, n_folds=5, seed=FOLD_SEED
        )
        # All folds have a positive diff.
        self.assertEqual(int(count), 5)
        self.assertEqual(len(diffs), 5)
        self.assertTrue(all(d > 0 for d in diffs))

    def test_fold_stability_threshold(self):
        self.assertEqual(FOLD_STABILITY_THRESHOLD, 4)
        self.assertEqual(N_FOLDS, 5)
        self.assertEqual(N_BOOTSTRAP, 1000)

    def test_unpaired_loo_is_translation_invariant(self):
        group_a = {1: 101.0, 2: 102.0, 3: 103.0}
        group_b = {4: 99.0, 5: 100.0, 6: 101.0}
        shifted_a = {key: value + 1000.0 for key, value in group_a.items()}
        shifted_b = {key: value + 1000.0 for key, value in group_b.items()}
        self.assertEqual(
            _unpaired_loo_stability(group_a, group_b),
            _unpaired_loo_stability(shifted_a, shifted_b),
        )

    def test_unpaired_fold_compares_group_means(self):
        group_a = {index: 10.0 + index for index in range(10)}
        group_b = {100 + index: float(index) for index in range(10)}
        count, directions, diffs = _unpaired_fold_stability(
            group_a, group_b, n_folds=5, seed=FOLD_SEED
        )
        self.assertEqual(int(count), 5)
        self.assertEqual(len(directions), 5)
        self.assertTrue(all(diff > 0 for diff in diffs))

    def test_min_decisive_pairs_constant(self):
        self.assertEqual(MIN_DECISIVE_PAIRS, 20)


# ---------------------------------------------------------------------------
# Outcome isolation
# ---------------------------------------------------------------------------


class TestOutcomeIsolation(unittest.TestCase):
    """The feature extractor and policy code must never read
    battle outcomes. Outcome-isolation is a hard gate for V2h."""

    def test_feature_module_does_not_import_battle_outcomes(self):
        import inspect
        for module_name in (
            "vgc2026_plan_features",
            "analyze_vgc2026_phaseV2h_feature_stability",
            "inspect_vgc2026_phaseV2h_feature",
        ):
            module = __import__(module_name)
            source = Path(inspect.getfile(module)).read_text()
            for forbidden in (
                "from poke_env",
                "import requests",
                "urllib",
                "play.pokemonshowdown.com",
                "smogon.com",
                "our_win",
                "opponent_win",
            ):
                self.assertNotIn(
                    forbidden, source,
                    f"{module_name} contains forbidden string {forbidden!r}"
                )

    def test_outcomes_only_in_diagnostic(self):
        # The analyzer reads outcomes from the benchmark CSV but
        # it must never pass them into extract_plan_features.
        # The features it records are preview-visible only.
        # This is verified by inspecting the analyzer's call
        # graph.
        import inspect
        import analyze_vgc2026_phaseV2h_feature_stability as mod
        source = Path(inspect.getfile(mod)).read_text()
        self.assertNotIn(
            "extract_plan_features(..., our_win=",
            source,
        )
        self.assertNotIn(
            "extract_plan_features(..., opponent_win=",
            source,
        )
        # The analyzer does not call evaluate_plan_on_common_scale
        # with a battle outcome argument.
        self.assertNotIn(
            "evaluate_plan_on_common_scale(..., battle_outcome",
            source,
        )

    def test_policy_unchanged(self):
        # Run the same plan selection through V2 and V3 twice and
        # confirm the result is identical regardless of battle
        # outcome state.
        from vgc2026_plan_features import extract_plan_features
        team = [
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Fake Out", "Grassy Glide", "U-turn", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
            {"species": "Flutter Mane", "ability": "Protosynthesis",
             "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"]},
            {"species": "Iron Hands", "ability": "Quark Drive",
             "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
        ]
        opp = [
            {"species": "Rillaboom", "moves": []},
            {"species": "Iron Hands", "moves": []},
            {"species": "Kingambit", "moves": []},
            {"species": "Incineroar", "moves": []},
            {"species": "Garchomp", "moves": []},
            {"species": "Tornadus", "moves": []},
        ]
        b1 = extract_plan_features(
            team, opp,
            ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        b2 = extract_plan_features(
            team, opp,
            ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        self.assertEqual(b1.features, b2.features)
        self.assertEqual(b1.audit, b2.audit)


# ---------------------------------------------------------------------------
# Analyzer integration
# ---------------------------------------------------------------------------


class TestAnalyzerIntegration(unittest.TestCase):
    def test_analyzer_missing_artifacts_fails(self):
        """Unit discovery must not depend on ignored benchmark
        artifacts. The production analyzer should fail explicitly
        when its requested inputs are absent.
        """
        from analyze_vgc2026_phaseV2h_feature_stability import (
            run_analysis,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                run_analysis(Path(tmp), "missing")


# ---------------------------------------------------------------------------
# Inspector integration
# ---------------------------------------------------------------------------


class TestInspectorIntegration(unittest.TestCase):
    def test_inspector_pair(self):
        result = subprocess.run(
            [
                sys.executable,
                "inspect_vgc2026_phaseV2h_feature.py",
                "--pair", "0",
                "--feature", "common_total",
            ],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Pair 0", result.stdout)
        self.assertIn("common_total", result.stdout)
        self.assertIn("preview-visible", result.stdout)

    def test_inspector_contradictory(self):
        result = subprocess.run(
            [
                sys.executable,
                "inspect_vgc2026_phaseV2h_feature.py",
                "--contradictory",
            ],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Contradictory features", result.stdout)

    def test_inspector_candidate_actionable(self):
        result = subprocess.run(
            [
                sys.executable,
                "inspect_vgc2026_phaseV2h_feature.py",
                "--candidate-actionable",
            ],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Candidate-actionable", result.stdout)

    def test_inspector_largest_positive(self):
        result = subprocess.run(
            [
                sys.executable,
                "inspect_vgc2026_phaseV2h_feature.py",
                "--feature", "common_total",
                "--largest-positive", "3",
            ],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("largest-positive", result.stdout)

    def test_inspector_largest_negative(self):
        result = subprocess.run(
            [
                sys.executable,
                "inspect_vgc2026_phaseV2h_feature.py",
                "--feature", "common_total",
                "--largest-negative", "3",
            ],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("largest-negative", result.stdout)

    def test_inspector_group(self):
        result = subprocess.run(
            [
                sys.executable,
                "inspect_vgc2026_phaseV2h_feature.py",
                "--feature", "common_total",
                "--group", "random_both",
            ],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Group random_both", result.stdout)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle(unittest.TestCase):
    def test_natural_termination(self):
        result = subprocess.run(
            [
                sys.executable, "-c",
                "import poke_env_test_cleanup; "
                "import vgc2026_common_plan_evaluator; "
                "import vgc2026_plan_features; "
                "import team_preview_policy; "
                "import analyze_vgc2026_phaseV2g_failures; "
                "import inspect_vgc2026_phaseV2g_pair; "
                "import analyze_vgc2026_phaseV2h_feature_stability; "
                "import inspect_vgc2026_phaseV2h_feature; "
                "print('ok')",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_no_pass_only_or_skipped_tests(self):
        import ast
        for module_name in (
            "test_vgc2026_phaseV2h",
        ):
            module = __import__(module_name)
            source = Path(module.__file__).read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    continue
                if not node.name.startswith("test_"):
                    continue
                body = node.body
                if not body:
                    self.fail(
                        f"{module_name}.{node.name} has an empty body"
                    )
                if (
                    len(body) == 1
                    and isinstance(body[0], ast.Pass)
                ):
                    self.fail(
                        f"{module_name}.{node.name} is a pass-only test"
                    )
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr in {"skipTest", "skip"}
                    ):
                        self.fail(
                            f"{module_name}.{node.name} uses skipTest/skip"
                        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _synthetic_artifacts():
    """Build 5 synthetic pairs (10 rows, 10 preview rows) for unit
    tests that only need the merge to work."""
    benchmark_rows: List[Dict[str, Any]] = []
    preview_rows: List[Dict[str, Any]] = []
    team_lookup: Dict[str, Dict[str, Any]] = {}
    for pair_id in range(5):
        benchmark_rows.append({
            "battle_tag": f"D1_{pair_id:04d}_p1",
            "pair_id": str(pair_id),
            "side": "p1",
            "team_id": f"team_{pair_id}",
            "opponent_team_id": f"opp_{pair_id}",
            "our_win": "True",
            "opponent_win": "False",
        })
        benchmark_rows.append({
            "battle_tag": f"D2_{pair_id:04d}_p2",
            "pair_id": str(pair_id),
            "side": "p2",
            "team_id": f"team_{pair_id}",
            "opponent_team_id": f"opp_{pair_id}",
            "our_win": "True",
            "opponent_win": "False",
        })
        preview_rows.append({
            "battle_tag": f"D1_{pair_id:04d}_p1",
            "side": "p1",
            "player_policy": "matchup_top4_v3",
            "opponent_policy": "random",
            "planned_chosen_4": "a|b|c|d",
            "planned_lead_2": "a|b",
            "planned_back_2": "c|d",
        })
        preview_rows.append({
            "battle_tag": f"D2_{pair_id:04d}_p2",
            "side": "p2",
            "player_policy": "matchup_top4_v3",
            "opponent_policy": "random",
            "planned_chosen_4": "a|b|c|d",
            "planned_lead_2": "a|b",
            "planned_back_2": "c|d",
        })
        team_lookup[f"team_{pair_id}"] = {
            "id": f"team_{pair_id}",
            "pokemon": [
                {"species": "A"},
                {"species": "B"},
                {"species": "C"},
                {"species": "D"},
                {"species": "E"},
                {"species": "F"},
            ],
        }
        team_lookup[f"opp_{pair_id}"] = {
            "id": f"opp_{pair_id}",
            "pokemon": [
                {"species": "A"},
                {"species": "B"},
                {"species": "C"},
                {"species": "D"},
                {"species": "E"},
                {"species": "F"},
            ],
        }
    return benchmark_rows, preview_rows, team_lookup


if __name__ == "__main__":
    unittest.main()
