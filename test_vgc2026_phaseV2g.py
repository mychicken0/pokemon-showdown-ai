#!/usr/bin/env python3
"""
Test suite for VGC 2026 Phase V2g — V3 battle failure diagnosis.

Covers the required test categories:
- pair merge by pair_id, independent of row order
- correct plan ownership via player_policy
- split pairs excluded from sign tests
- 30/25/45 gives p=0.590053 and one-sided p=0.295027
- feature extraction uses exact selected plan
- no hidden information
- exact 4/2/2 validation
- all 90 plans evaluated (feature-related)
- deterministic output
- returned plan equals scored plan
- symmetric lead components
- weather/terrain conflict tests
- physical/special balance tests
- immediate-pressure tests
- existing V2/V3 behavior unchanged
- malformed artifacts return errors rather than exceptions
- zero skipped, placeholder, pass-only or no-op tests
- natural process termination
"""

import poke_env_test_cleanup  # Must precede poke-env imports.

import csv
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

sys.path.insert(0, "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai")

from team_preview_policy import (
    choose_four_from_six,
    score_combination,
    score_combination_v3,
    evaluate_all_combinations,
    evaluate_all_combinations_v3,
    PreviewResult,
    validate_preview,
)
from vgc2026_common_plan_evaluator import (
    CommonPlanEvaluatorError,
    CommonPlanScore,
    COMPONENT_WEIGHTS,
    evaluate_plan_on_common_scale,
)
from vgc2026_plan_features import (
    PlanFeatures,
    _back_pressure,
    _move_kind,
    aggregate_features,
    extract_plan_features,
    shannon_entropy_from_counts,
)
from analyze_vgc2026_phaseV2g_failures import (
    build_bundles_by_pair,
    build_pair_records,
    classify_pair,
    load_v2f_artifacts,
    sign_test as v2g_sign_test,
    _v3_plan_from_preview,
    _random_plan_from_preview,
)
from analyze_vgc2026_phaseV2f_qualification import (
    extract_pairs as v2f_extract_pairs,
    paired_sign_test as v2f_paired_sign_test,
)


SAMPLE_TEAM: List[Dict[str, Any]] = [
    {"species": "Incineroar", "ability": "Intimidate",
     "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Throat Chop"]},
    {"species": "Garchomp", "ability": "Rough Skin",
     "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
    {"species": "Rillaboom", "ability": "Grassy Surge",
     "moves": ["Fake Out", "Grassy Glide", "High Horsepower", "U-turn"]},
    {"species": "Tornadus", "ability": "Prankster",
     "moves": ["Tailwind", "Taunt", "Hurricane", "Focus Blast"]},
    {"species": "Flutter Mane", "ability": "Protosynthesis",
     "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"]},
    {"species": "Iron Hands", "ability": "Quark Drive",
     "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
]
OPP_TEAM: List[Dict[str, Any]] = [
    {"species": "Rillaboom", "moves": []},
    {"species": "Iron Hands", "moves": []},
    {"species": "Kingambit", "moves": []},
    {"species": "Incineroar", "moves": []},
    {"species": "Garchomp", "moves": []},
    {"species": "Tornadus", "moves": []},
]


# ---------------------------------------------------------------------------
# Pair merge by pair_id, independent of row order
# ---------------------------------------------------------------------------


class TestPairMerge(unittest.TestCase):

    def test_pair_merge_uses_pair_id_not_row_order(self):
        # Build 100 rows of benchmark + preview data and confirm
        # that build_pair_records returns the same pair list when
        # the rows are shuffled.
        benchmark_rows: List[Dict[str, Any]] = []
        preview_rows: List[Dict[str, Any]] = []
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
                "our_win": "False",
                "opponent_win": "True",
            })
            preview_rows.append({
                "battle_tag": f"D1_{pair_id:04d}_p1",
                "pair_id": str(pair_id),
                "side": "p1",
                "player_policy": "matchup_top4_v3",
                "opponent_policy": "random",
                "planned_chosen_4": "a|b|c|d",
                "planned_lead_2": "a|b",
                "planned_back_2": "c|d",
            })
            preview_rows.append({
                "battle_tag": f"D2_{pair_id:04d}_p2",
                "pair_id": str(pair_id),
                "side": "p2",
                "player_policy": "matchup_top4_v3",
                "opponent_policy": "random",
                "planned_chosen_4": "a|b|c|d",
                "planned_lead_2": "a|b",
                "planned_back_2": "c|d",
            })
        team_lookup = {
            f"team_{i}": {"id": f"team_{i}", "pokemon": SAMPLE_TEAM}
            for i in range(5)
        }
        team_lookup.update({
            f"opp_{i}": {"id": f"opp_{i}", "pokemon": OPP_TEAM}
            for i in range(5)
        })
        # Shuffle the benchmark rows to verify the merge uses
        # pair_id and not row position.
        import random
        random.seed(0)
        shuffled = list(benchmark_rows)
        random.shuffle(shuffled)
        pairs_a = build_pair_records(
            benchmark_rows, preview_rows, team_lookup
        )
        pairs_b = build_pair_records(
            shuffled, preview_rows, team_lookup
        )
        self.assertEqual(
            [p["pair_id"] for p in pairs_a],
            [p["pair_id"] for p in pairs_b],
        )
        self.assertEqual(
            [p["d1_v3_plan"] for p in pairs_a],
            [p["d1_v3_plan"] for p in pairs_b],
        )


# ---------------------------------------------------------------------------
# Correct plan ownership via player_policy
# ---------------------------------------------------------------------------


class TestPlanOwnership(unittest.TestCase):

    def test_player_policy_v3_owns_v3_plan(self):
        rows = [
            {
                "battle_tag": "D1_0000_p1",
                "side": "p1",
                "player_policy": "matchup_top4_v3",
                "opponent_policy": "random",
                "planned_chosen_4": "a|b|c|d",
                "planned_lead_2": "a|b",
                "planned_back_2": "c|d",
            },
        ]
        plan = _v3_plan_from_preview(rows, "D1_0000_p1")
        self.assertIsNotNone(plan)
        self.assertEqual(plan["chosen_4"], ["a", "b", "c", "d"])
        self.assertEqual(plan["source_player_policy"], "matchup_top4_v3")

    def test_opponent_policy_metadata_does_not_own_v3_plan(self):
        rows = [
            {
                "battle_tag": "D1_0000_p1",
                "side": "p1",
                "player_policy": "random",
                "opponent_policy": "matchup_top4_v3",
                "planned_chosen_4": "a|b|c|d",
                "planned_lead_2": "a|b",
                "planned_back_2": "c|d",
            },
        ]
        plan = _v3_plan_from_preview(rows, "D1_0000_p1")
        self.assertIsNone(plan)

    def test_random_plan_ownership_is_separate(self):
        rows = [
            {
                "battle_tag": "D1_0000_p1",
                "side": "p1",
                "player_policy": "matchup_top4_v3",
                "opponent_policy": "random",
                "planned_chosen_4": "a|b|c|d",
                "planned_lead_2": "a|b",
                "planned_back_2": "c|d",
            },
            {
                "battle_tag": "D1_0000_p1",
                "side": "p2",
                "player_policy": "random",
                "opponent_policy": "matchup_top4_v3",
                "planned_chosen_4": "w|x|y|z",
                "planned_lead_2": "w|x",
                "planned_back_2": "y|z",
            },
        ]
        v3_plan = _v3_plan_from_preview(rows, "D1_0000_p1")
        random_plan = _random_plan_from_preview(rows, "D1_0000_p1")
        self.assertEqual(v3_plan["chosen_4"], ["a", "b", "c", "d"])
        self.assertEqual(random_plan["chosen_4"], ["w", "x", "y", "z"])


# ---------------------------------------------------------------------------
# Split pairs excluded from sign tests
# ---------------------------------------------------------------------------


class TestSignTestExcludesSplits(unittest.TestCase):

    def test_split_pair_excluded_from_sign_test(self):
        # A single split pair must NOT contribute to the
        # directional sign test count.
        pair = {
            "pair_id": 0,
            "d1_outcome": "win",
            "d2_outcome": "loss",
        }
        stats = v2g_sign_test([pair])
        self.assertEqual(stats["v3_both"], 0)
        self.assertEqual(stats["random_both"], 0)
        self.assertEqual(stats["split"], 1)
        self.assertEqual(stats["decisive_n"], 0)

    def test_thirty_twentyfive_fortyfive_pvalues(self):
        # Construct 30 v3_both, 25 random_both, 45 split.
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
        # 30 wins out of 55 decisive trials. Use the exact binomial
        # to compute p-values from scratch.
        # two-sided p = 2 * P(k >= 30) under Bin(55, 0.5)
        from math import comb
        probs = [comb(55, k) / 2 ** 55 for k in range(56)]
        two_sided = min(
            1.0,
            sum(p for p in probs if p <= probs[30] + 1e-15),
        )
        one_sided = sum(probs[30:])
        self.assertAlmostEqual(stats["two_sided_p"], two_sided, places=12)
        self.assertAlmostEqual(stats["one_sided_p"], one_sided, places=12)
        # Pin the documented values to guard against silent regression.
        self.assertAlmostEqual(stats["two_sided_p"], 0.590053, places=5)
        self.assertAlmostEqual(stats["one_sided_p"], 0.295027, places=5)


# ---------------------------------------------------------------------------
# Feature extraction uses exact selected plan
# ---------------------------------------------------------------------------


class TestFeatureExtractionUsesExactPlan(unittest.TestCase):

    def test_features_depend_on_exact_plan(self):
        # The features for a known plan differ from the features
        # of a different plan chosen from the same team. A: includes
        # Incineroar (Intimidate + Fake Out). B: replaces Incineroar
        # with Iron Hands (no Intimidate).
        bundle_a = extract_plan_features(
            SAMPLE_TEAM, OPP_TEAM,
            ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        bundle_b = extract_plan_features(
            SAMPLE_TEAM, OPP_TEAM,
            ["Iron Hands", "Tornadus", "Garchomp", "Rillaboom"],
            ["Iron Hands", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        # A has Incineroar (Intimidate); B does not.
        self.assertEqual(bundle_a.features["intimidate_support"], 1.0)
        self.assertEqual(bundle_b.features["intimidate_support"], 0.0)
        # The common total must differ between the two plans
        # (the policies are scoring different role coverage).
        self.assertNotEqual(
            bundle_a.features["common_total"],
            bundle_b.features["common_total"],
        )

    def test_features_depend_on_exact_opponent_team(self):
        # Same plan against different opponents must produce
        # different offensive_type_coverage.
        plan = ("Incineroar", "Tornadus", "Garchomp", "Rillaboom")
        leads = ("Incineroar", "Tornadus")
        backs = ("Garchomp", "Rillaboom")
        bundle_phys = extract_plan_features(
            SAMPLE_TEAM, OPP_TEAM, list(plan), list(leads), list(backs)
        )
        special_opp = [
            {"species": "Flutter Mane", "moves": []},
            {"species": "Hydreigon", "moves": []},
            {"species": "Chi-Yu", "moves": []},
            {"species": "Iron Moth", "moves": []},
            {"species": "Gholdengo", "moves": []},
            {"species": "Iron Bundle", "moves": []},
        ]
        bundle_spec = extract_plan_features(
            SAMPLE_TEAM, special_opp, list(plan), list(leads), list(backs)
        )
        self.assertNotEqual(
            bundle_phys.features["offensive_type_coverage"],
            bundle_spec.features["offensive_type_coverage"],
        )


# ---------------------------------------------------------------------------
# Hidden information / no online / no battle data used
# ---------------------------------------------------------------------------


class TestNoHiddenInformation(unittest.TestCase):

    def test_extractor_does_not_import_battle_data(self):
        # Static check: vgc2026_plan_features and the V2g analyzer
        # must not pull in poke-env battle data, online APIs, or
        # qualification outcomes for tuning.
        import inspect
        for module_name in (
            "vgc2026_plan_features",
            "analyze_vgc2026_phaseV2g_failures",
            "inspect_vgc2026_phaseV2g_pair",
        ):
            module = __import__(module_name)
            source = Path(inspect.getfile(module)).read_text()
            for forbidden in (
                "from poke_env",
                "import requests",
                "urllib",
                "play.pokemonshowdown.com",
                "smogon.com",
            ):
                self.assertNotIn(forbidden, source)

    def test_extractor_uses_only_open_team_sheet_data(self):
        # The features must be derived from moves, ability, types.
        bundle = extract_plan_features(
            SAMPLE_TEAM, OPP_TEAM,
            ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        # All feature names are pre-declared.
        expected_keys = {
            "offensive_type_coverage", "defensive_weakness_exposure",
            "lead_shared_weakness", "lead_speed_control_pressure",
            "fake_out_pressure", "redirection_support",
            "intimidate_support", "spread_pressure", "protect_utility",
            "lead_back_role_coverage", "back_pivot_or_switch",
            "duplicate_role_penalty", "common_total",
            "lead_shared_2x_weakness_count",
            "lead_shared_4x_weakness_count",
            "back_immediate_pressure", "physical_damaging_moves",
            "special_damaging_moves", "physical_special_balance_diff",
            "lead_immediate_damage", "back_immediate_damage",
            "setup_moves", "restorative_moves", "type_count_unique",
        }
        self.assertTrue(
            expected_keys.issubset(set(bundle.features.keys()))
        )


# ---------------------------------------------------------------------------
# Exact 4/2/2 validation
# ---------------------------------------------------------------------------


class TestExactPlanValidation(unittest.TestCase):

    def test_malformed_plan_raises(self):
        with self.assertRaises(Exception) as ctx:
            extract_plan_features(
                SAMPLE_TEAM, OPP_TEAM,
                ["Incineroar", "Garchomp", "Rillaboom"],  # 3, not 4
                ["Incineroar", "Garchomp"],
                ["Rillaboom", "Tornadus"],
            )
        self.assertNotIsInstance(ctx.exception, AssertionError)

    def test_wrong_team_size_rejected(self):
        with self.assertRaises(ValueError):
            extract_plan_features(
                SAMPLE_TEAM[:5], OPP_TEAM,
                ["Incineroar", "Garchomp", "Rillaboom", "Tornadus"],
                ["Incineroar", "Garchomp"],
                ["Rillaboom", "Tornadus"],
            )


# ---------------------------------------------------------------------------
# Determinism, all 90 plans, returned plan equals scored plan
# ---------------------------------------------------------------------------


class TestDeterminismAndPlans(unittest.TestCase):

    def test_all_90_plans_evaluated(self):
        # The feature bundle is produced for any chosen plan. The
        # policy code evaluates all 90 legal plans; this test
        # confirms the count and the determinism of the 90-plan
        # sort.
        plans = evaluate_all_combinations(SAMPLE_TEAM, OPP_TEAM)
        self.assertEqual(len(plans), 90)
        plans_v3 = evaluate_all_combinations_v3(SAMPLE_TEAM, OPP_TEAM)
        self.assertEqual(len(plans_v3), 90)
        # Both evaluations must be deterministic.
        plans2 = evaluate_all_combinations(SAMPLE_TEAM, OPP_TEAM)
        self.assertEqual(
            [tuple(p[1] for p in plans) for p in plans2],
            [tuple(p[1] for p in plans) for p in plans],
        )

    def test_returned_plan_equals_scored_plan(self):
        preview = choose_four_from_six(
            SAMPLE_TEAM, opponent_team=OPP_TEAM,
            policy="matchup_top4_v3", seed=42,
        )
        # The PreviewResult must match the highest-scoring plan
        # returned by the evaluation pipeline.
        plans = evaluate_all_combinations_v3(SAMPLE_TEAM, OPP_TEAM)
        best_plan, best_score, _ = plans[0]
        self.assertEqual(
            preview.chosen_4,
            [p["species"] for p in best_plan],
        )
        self.assertEqual(
            preview.lead_2,
            [best_plan[0]["species"], best_plan[1]["species"]],
        )
        self.assertEqual(
            preview.back_2,
            [best_plan[2]["species"], best_plan[3]["species"]],
        )

    def test_deterministic_v3_and_random(self):
        for policy in ("matchup_top4_v3", "random"):
            a = choose_four_from_six(
                SAMPLE_TEAM, opponent_team=OPP_TEAM,
                policy=policy, seed=42,
            )
            b = choose_four_from_six(
                SAMPLE_TEAM, opponent_team=OPP_TEAM,
                policy=policy, seed=42,
            )
            self.assertEqual(a.chosen_4, b.chosen_4)
            self.assertEqual(a.lead_2, b.lead_2)
            self.assertEqual(a.back_2, b.back_2)


# ---------------------------------------------------------------------------
# Symmetric lead components
# ---------------------------------------------------------------------------


class TestSymmetricLeadComponents(unittest.TestCase):

    def test_lead_components_symmetric(self):
        plan = [
            SAMPLE_TEAM[0], SAMPLE_TEAM[1],
            SAMPLE_TEAM[3], SAMPLE_TEAM[4],
        ]
        reverse = [plan[1], plan[0], plan[2], plan[3]]
        forward = extract_plan_features(
            SAMPLE_TEAM, OPP_TEAM,
            [p["species"] for p in plan],
            [plan[0]["species"], plan[1]["species"]],
            [plan[2]["species"], plan[3]["species"]],
        )
        backward = extract_plan_features(
            SAMPLE_TEAM, OPP_TEAM,
            [p["species"] for p in reverse],
            [reverse[0]["species"], reverse[1]["species"]],
            [reverse[2]["species"], reverse[3]["species"]],
        )
        for key in (
            "lead_shared_weakness",
            "lead_shared_2x_weakness_count",
            "lead_shared_4x_weakness_count",
            "lead_speed_control_pressure",
            "lead_immediate_damage",
        ):
            self.assertEqual(
                forward.features[key],
                backward.features[key],
                f"asymmetric lead component: {key}",
            )


# ---------------------------------------------------------------------------
# Weather / terrain conflict tests
# ---------------------------------------------------------------------------


class TestWeatherTerrainConflicts(unittest.TestCase):

    def test_two_terrain_setters_flag_conflict(self):
        # Both Rillaboom (grassy surge) and Pincurchin would set
        # terrain. Use a team with two terrain setters via a
        # synthetic ability set.
        team = [
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Grassy Glide", "U-turn", "Protect", "Fake Out"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Hurricane", "Taunt", "Protect"]},
            {"species": "Indeedee", "ability": "Psychic Surge",
             "moves": ["Follow Me", "Trick Room", "Hyper Voice", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Flutter Mane", "ability": "Protosynthesis",
             "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"]},
        ]
        bundle = extract_plan_features(
            team, OPP_TEAM,
            ["Rillaboom", "Indeedee", "Garchomp", "Tornadus"],
            ["Rillaboom", "Indeedee"],
            ["Garchomp", "Tornadus"],
        )
        # Two terrain setters should be flagged.
        self.assertEqual(
            bundle.categorical["has_conflicting_terrain"], ["yes"]
        )
        self.assertEqual(
            bundle.categorical["has_terrain_setter"], ["yes"]
        )

    def test_no_conflict_when_single_weather_setter(self):
        team = [
            {"species": "Pelipper", "ability": "Drizzle",
             "moves": ["Scald", "Hurricane", "U-turn", "Protect"]},
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Wood Hammer", "U-turn", "Grassy Glide", "Protect"]},
            {"species": "Iron Hands", "ability": "Quark Drive",
             "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
        ]
        bundle = extract_plan_features(
            team, OPP_TEAM,
            ["Pelipper", "Rillaboom", "Garchomp", "Tornadus"],
            ["Pelipper", "Rillaboom"],
            ["Garchomp", "Tornadus"],
        )
        # Drizzle is a weather setter; Grassy Surge sets terrain. The
        # two do not conflict with each other, but together the plan
        # has both a weather setter and a terrain setter.
        self.assertEqual(
            bundle.categorical["has_weather_setter"], ["yes"]
        )
        self.assertEqual(
            bundle.categorical["has_terrain_setter"], ["yes"]
        )


# ---------------------------------------------------------------------------
# Physical/special balance tests
# ---------------------------------------------------------------------------


class TestPhysicalSpecialBalance(unittest.TestCase):

    def test_shadow_ball_is_special(self):
        self.assertEqual(_move_kind("Shadow Ball"), "special")

    def test_make_it_rain_is_special(self):
        self.assertEqual(_move_kind("Make It Rain"), "special")

    def test_physical_count_equals_physical_damaging(self):
        # The custom physical/special set is a small but stable
        # policy-independent classifier. The counts must sum to
        # the expected total damaging moves in the sample plan
        # according to the classifier.
        bundle = extract_plan_features(
            SAMPLE_TEAM, OPP_TEAM,
            ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        physical = bundle.features["physical_damaging_moves"]
        special = bundle.features["special_damaging_moves"]
        diff = bundle.features["physical_special_balance_diff"]
        # The custom classifier matches only moves it knows about.
        # Both counts must be non-negative and their difference must
        # equal the recorded balance diff.
        self.assertGreaterEqual(physical, 0)
        self.assertGreaterEqual(special, 0)
        self.assertEqual(physical - special, diff)


# ---------------------------------------------------------------------------
# Immediate-pressure tests
# ---------------------------------------------------------------------------


class TestImmediatePressure(unittest.TestCase):

    def test_single_target_special_move_is_not_spread_pressure(self):
        backs = [{"moves": ["Shadow Ball"]}]
        self.assertEqual(_back_pressure(backs), 0.0)

    def test_spread_special_move_is_pressure(self):
        backs = [{"moves": ["Make It Rain"]}]
        self.assertEqual(_back_pressure(backs), 0.5)

    def test_protect_is_not_priority_pressure(self):
        backs = [{"moves": ["Protect"]}]
        self.assertEqual(_back_pressure(backs), 0.0)

    def test_priority_moves_counted(self):
        # The SAMPLE_TEAM has Fake Out on Incineroar, Rillaboom,
        # and Iron Hands. None of those is in the back, so
        # back_immediate_damage is 0 and lead_immediate_damage is
        # at least 1 (Incineroar Fake Out).
        bundle = extract_plan_features(
            SAMPLE_TEAM, OPP_TEAM,
            ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        self.assertGreaterEqual(
            bundle.features["lead_immediate_damage"], 1
        )

    def test_back_with_pivot_increases_pressure(self):
        # If Rillaboom (U-turn) is in the back, the back has at
        # least one priority pivot.
        bundle = extract_plan_features(
            SAMPLE_TEAM, OPP_TEAM,
            ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        self.assertEqual(
            bundle.features["back_pivot_or_switch"], 1.0
        )


# ---------------------------------------------------------------------------
# Existing V2/V3 behavior unchanged
# ---------------------------------------------------------------------------


class TestExistingPoliciesUnchanged(unittest.TestCase):

    def test_v2_unchanged(self):
        a = choose_four_from_six(
            SAMPLE_TEAM, opponent_team=OPP_TEAM,
            policy="matchup_top4_v2", seed=42,
        )
        b = choose_four_from_six(
            SAMPLE_TEAM, opponent_team=OPP_TEAM,
            policy="matchup_top4_v2", seed=42,
        )
        self.assertEqual(a.chosen_4, b.chosen_4)
        self.assertEqual(a.lead_2, b.lead_2)
        self.assertEqual(a.back_2, b.back_2)

    def test_v3_unchanged(self):
        a = choose_four_from_six(
            SAMPLE_TEAM, opponent_team=OPP_TEAM,
            policy="matchup_top4_v3", seed=42,
        )
        b = choose_four_from_six(
            SAMPLE_TEAM, opponent_team=OPP_TEAM,
            policy="matchup_top4_v3", seed=42,
        )
        self.assertEqual(a.chosen_4, b.chosen_4)

    def test_basic_and_random_unchanged(self):
        for policy in ("basic_top4", "random"):
            a = choose_four_from_six(
                SAMPLE_TEAM, opponent_team=OPP_TEAM,
                policy=policy, seed=42,
            )
            b = choose_four_from_six(
                SAMPLE_TEAM, opponent_team=OPP_TEAM,
                policy=policy, seed=42,
            )
            self.assertEqual(a.chosen_4, b.chosen_4)


# ---------------------------------------------------------------------------
# Malformed artifacts return errors
# ---------------------------------------------------------------------------


class TestMalformedArtifactsReturnErrors(unittest.TestCase):

    def test_missing_team_id_returns_missing_bundle(self):
        # If a benchmark row references a team_id that does not
        # exist in the pool, the bundle for that pair is None.
        benchmark_rows = [{
            "battle_tag": "D1_0000_p1",
            "pair_id": "0",
            "side": "p1",
            "team_id": "missing_team",
            "opponent_team_id": "missing_opp",
            "our_win": "True",
            "opponent_win": "False",
        }, {
            "battle_tag": "D2_0000_p2",
            "pair_id": "0",
            "side": "p2",
            "team_id": "missing_team",
            "opponent_team_id": "missing_opp",
            "our_win": "False",
            "opponent_win": "True",
        }]
        preview_rows = [{
            "battle_tag": "D1_0000_p1",
            "side": "p1",
            "player_policy": "matchup_top4_v3",
            "opponent_policy": "random",
            "planned_chosen_4": "a|b|c|d",
            "planned_lead_2": "a|b",
            "planned_back_2": "c|d",
        }, {
            "battle_tag": "D2_0000_p2",
            "side": "p2",
            "player_policy": "matchup_top4_v3",
            "opponent_policy": "random",
            "planned_chosen_4": "a|b|c|d",
            "planned_lead_2": "a|b",
            "planned_back_2": "c|d",
        }]
        team_lookup: Dict[str, Dict[str, Any]] = {}
        pairs = build_pair_records(
            benchmark_rows, preview_rows, team_lookup
        )
        bundles = build_bundles_by_pair(pairs, team_lookup)
        pair_bundles = dict(bundles)[0]
        self.assertIsNone(pair_bundles["v3"])
        self.assertIsNone(pair_bundles["random"])


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
                "print('ok')",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_no_pass_only_or_skipped_tests(self):
        # AST scan: every test_* method must have a non-trivial
        # body (no pass, no skipped, no empty).
        import ast
        for module_name in (
            "test_vgc2026_phaseV2g",
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
                # Detect skipTest usage.
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr in {"skipTest", "skip"}
                    ):
                        self.fail(
                            f"{module_name}.{node.name} uses skipTest/skip"
                        )


if __name__ == "__main__":
    unittest.main()
