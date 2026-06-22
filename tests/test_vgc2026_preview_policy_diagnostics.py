#!/usr/bin/env python3
"""
Test suite for VGC 2026 Preview Policy Diagnostics — Phase V2d

Tests the matchup_top4_v2 policy implementation covering:
- uniqueness and exact 4/2/2 structure
- determinism
- different opponent changes selection when matchup differs
- dual-type effectiveness
- immunity handling
- role deduplication
- lead synergy
- back coverage
- Protect/Fake Out/speed-control logic
- no hidden information
- no mutation of basic_top4
- artifact validators
- analyzer and inspector behavior
- lifecycle natural exit
"""

import poke_env_test_cleanup  # Must precede poke-env imports.

import math
import unittest
import random
import tempfile
import sys
import subprocess
import csv
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from team_preview_policy import (
    choose_four_from_six, PreviewResult, validate_preview,
    score_pokemon, calculate_type_matchup, calculate_weakness_avoidance,
    SPECIES_TYPES, TYPE_CHART,
    score_combination, evaluate_all_combinations
)
from eval_vgc2026_policies_offline import (
    analyze_results,
    eval_all_policies,
    shannon_entropy_from_counts,
)
from bot_vgc2026_phaseV2d_smoke import V2dSmokeRunner
from bot_vgc2026_phaseV2d_qualification import (
    V2dPairedQualificationRunner,
    validate_qualification_artifacts,
)
from analyze_vgc2026_phaseV2d_qualification import (
    analyze_pairs,
    exact_binomial_p_value,
    normalize_v2_outcome,
    wilson_interval,
)
from poke_env.teambuilder.constant_teambuilder import ConstantTeambuilder


# Test fixtures
SAMPLE_TEAM = [
    {"species": "Incineroar", "ability": "Intimidate", "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Throat Chop"], "item": "Sitrus Berry", "nature": "Adamant", "evs": {"hp": 252, "atk": 252, "def": 4}, "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 0}},
    {"species": "Garchomp", "ability": "Rough Skin", "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"], "item": "Choice Scarf", "nature": "Jolly", "evs": {"hp": 4, "atk": 252, "spe": 252}, "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}},
    {"species": "Rillaboom", "ability": "Grassy Surge", "moves": ["Fake Out", "Grassy Glide", "High Horsepower", "U-turn"], "item": "Choice Band", "nature": "Adamant", "evs": {"hp": 252, "atk": 252, "def": 4}, "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}},
    {"species": "Tornadus", "ability": "Prankster", "moves": ["Tailwind", "Taunt", "Hurricane", "Focus Blast"], "item": "Focus Sash", "nature": "Timid", "evs": {"hp": 4, "spa": 252, "spe": 252}, "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}},
    {"species": "Flutter Mane", "ability": "Protosynthesis", "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"], "item": "Booster Energy", "nature": "Timid", "evs": {"hp": 4, "spa": 252, "spe": 252}, "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}},
    {"species": "Iron Hands", "ability": "Quark Drive", "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"], "item": "Booster Energy", "nature": "Adamant", "evs": {"hp": 252, "atk": 252, "def": 4}, "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}},
]

OPP_TEAM_PHYSICAL = [
    {"species": "Rillaboom", "moves": []},
    {"species": "Iron Hands", "moves": []},
    {"species": "Kingambit", "moves": []},
    {"species": "Incineroar", "moves": []},
    {"species": "Garchomp", "moves": []},
    {"species": "Tornadus", "moves": []},
]

OPP_TEAM_SPECIAL = [
    {"species": "Flutter Mane", "moves": []},
    {"species": "Hydreigon", "moves": []},
    {"species": "Chi-Yu", "moves": []},
    {"species": "Iron Moth", "moves": []},
    {"species": "Gholdengo", "moves": []},
    {"species": "Iron Bundle", "moves": []},
]


class TestMatchupTop4V2Structure(unittest.TestCase):
    """Test matchup_top4_v2 produces valid structure."""

    def test_returns_four_unique_pokemon(self):
        """Test chosen_4 has exactly 4 unique species."""
        result = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM_PHYSICAL, policy="matchup_top4_v2", seed=42)
        self.assertEqual(len(result.chosen_4), 4)
        self.assertEqual(len(set(result.chosen_4)), 4)

    def test_lead_2_in_chosen(self):
        """Test lead_2 are subset of chosen_4."""
        result = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM_PHYSICAL, policy="matchup_top4_v2", seed=42)
        self.assertEqual(len(result.lead_2), 2)
        self.assertTrue(set(result.lead_2).issubset(set(result.chosen_4)))

    def test_back_2_in_chosen(self):
        """Test back_2 are subset of chosen_4."""
        result = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM_PHYSICAL, policy="matchup_top4_v2", seed=42)
        self.assertEqual(len(result.back_2), 2)
        self.assertTrue(set(result.back_2).issubset(set(result.chosen_4)))

    def test_no_overlap_lead_back(self):
        """Test lead_2 and back_2 are disjoint."""
        result = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM_PHYSICAL, policy="matchup_top4_v2", seed=42)
        self.assertEqual(set(result.lead_2).intersection(set(result.back_2)), set())

    def test_policy_name(self):
        """Test policy name is correct."""
        result = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM_PHYSICAL, policy="matchup_top4_v2", seed=42)
        self.assertEqual(result.policy, "matchup_top4_v2")

    def test_scores_present(self):
        """Test chosen Pokemon have scores."""
        result = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM_PHYSICAL, policy="matchup_top4_v2", seed=42)
        # matchup_top4_v2 only returns scores for the chosen 4
        self.assertEqual(len(result.scores), 4)
        for s in result.scores:
            self.assertIsInstance(s.total, float)


class TestDeterminism(unittest.TestCase):
    """Test deterministic behavior."""

    def test_same_seed_same_result(self):
        """Test same seed produces identical results."""
        result1 = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM_PHYSICAL, policy="matchup_top4_v2", seed=42)
        result2 = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM_PHYSICAL, policy="matchup_top4_v2", seed=42)
        self.assertEqual(result1.chosen_4, result2.chosen_4)
        self.assertEqual(result1.lead_2, result2.lead_2)
        self.assertEqual(result1.back_2, result2.back_2)

    def test_different_seed_does_not_change_deterministic_policy(self):
        """The deterministic policy ignores seed when no random tie-break exists."""
        result1 = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM_PHYSICAL, policy="matchup_top4_v2", seed=42)
        result2 = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM_PHYSICAL, policy="matchup_top4_v2", seed=123)
        self.assertEqual(result1.chosen_4, result2.chosen_4)
        self.assertEqual(result1.lead_2, result2.lead_2)
        self.assertEqual(result1.back_2, result2.back_2)


class TestOpponentDependentSelection(unittest.TestCase):
    """Test selection changes based on opponent team."""

    def test_different_opponent_changes_selection(self):
        """A deterministic matchup contrast must change the selected plan."""
        grass_poison = [{"species": "Venusaur", "moves": []} for _ in range(6)]
        water_fairy = [{"species": "Tapu Fini", "moves": []} for _ in range(6)]
        first = choose_four_from_six(
            SAMPLE_TEAM, opponent_team=grass_poison,
            policy="matchup_top4_v2", seed=42,
        )
        second = choose_four_from_six(
            SAMPLE_TEAM, opponent_team=water_fairy,
            policy="matchup_top4_v2", seed=42,
        )
        self.assertNotEqual(
            (set(first.chosen_4), tuple(first.lead_2)),
            (set(second.chosen_4), tuple(second.lead_2)),
        )

    def test_no_opponent_fallback(self):
        """Test policy works without opponent team."""
        result = choose_four_from_six(SAMPLE_TEAM, policy="matchup_top4_v2", seed=42)
        self.assertEqual(len(result.chosen_4), 4)
        self.assertEqual(len(result.lead_2), 2)
        self.assertEqual(len(result.back_2), 2)


class TestDualTypeEffectiveness(unittest.TestCase):
    """Test dual-type effectiveness calculations."""

    def test_super_effective_both_types(self):
        """Test 2x * 2x = 4x effectiveness."""
        # Fire/Flying vs Grass/Bug: Fire(2x Grass) * Flying(2x Bug) = 4x
        our = ["fire", "flying"]
        their = ["grass", "bug"]
        result = calculate_type_matchup(our, their)
        # calculate_type_matchup returns combined_multiplier / 4
        # 4x -> 1.0
        self.assertGreaterEqual(result, 0.9)  # 4x -> 1.0

    def test_immune(self):
        """Test 0x effectiveness (immunity)."""
        # Normal vs Ghost
        our = ["normal"]
        their = ["ghost"]
        result = calculate_type_matchup(our, their)
        self.assertEqual(result, 0.0)

    def test_not_very_effective(self):
        """Test 0.5x effectiveness."""
        # Fire vs Water
        our = ["fire"]
        their = ["water"]
        result = calculate_type_matchup(our, their)
        self.assertLess(result, 0.5)


class TestImmunityHandling(unittest.TestCase):
    """Test immunity handling in weakness avoidance."""

    def test_4x_weakness_penalty(self):
        """Test 4x weakness gives 0 avoidance."""
        # Grass/Steel vs Fire: both Grass and Steel are 2x weak to Fire -> 4x
        our = ["grass", "steel"]
        their = ["fire"]
        result = calculate_weakness_avoidance(our, their)
        self.assertEqual(result, 0.0)  # 4x weakness

    def test_2x_weakness_half(self):
        """Test 2x weakness gives 0.5 avoidance."""
        # Fire vs Ground
        our = ["fire"]
        their = ["ground"]
        result = calculate_weakness_avoidance(our, their)
        self.assertEqual(result, 0.5)

    def test_neutral_resistance(self):
        """Test neutral gives 1.0 avoidance."""
        our = ["fire"]
        their = ["poison"]
        result = calculate_weakness_avoidance(our, their)
        self.assertEqual(result, 1.0)


class TestRoleDeduplication(unittest.TestCase):
    """Test role deduplication in joint scoring."""

    def test_penalizes_duplicate_roles(self):
        """Test that combinations with duplicate roles are penalized."""
        # Create team with multiple Fake Out users
        multi_fake_out_team = [
            {"species": "Incineroar", "ability": "Intimidate", "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Throat Chop"]},
            {"species": "Rillaboom", "ability": "Grassy Surge", "moves": ["Fake Out", "Grassy Glide", "High Horsepower", "U-turn"]},
            {"species": "Garchomp", "ability": "Rough Skin", "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster", "moves": ["Tailwind", "Taunt", "Hurricane", "Focus Blast"]},
            {"species": "Flutter Mane", "ability": "Protosynthesis", "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"]},
            {"species": "Iron Hands", "ability": "Quark Drive", "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
        ]

        # Evaluate all combinations
        results = evaluate_all_combinations(multi_fake_out_team)

        # Check that combinations with 3+ Fake Out have lower scores
        # (at least the top ones should not all have 3 Fake Out)
        best = results[0]
        combo = best[0]
        fake_out_count = sum(1 for p in combo if "Fake Out" in p.get("moves", []))
        self.assertLessEqual(fake_out_count, 2)
        self.assertLessEqual(best[2]["role_duplicate_penalty"], 0.0)


class TestLeadSynergy(unittest.TestCase):
    """Test lead pair synergy scoring."""

    def test_fake_out_plus_spread_bonus(self):
        """Test Fake Out + Spread gives synergy bonus."""
        combo = [
            {"species": "Incineroar", "ability": "Intimidate", "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Throat Chop"]},
            {"species": "Garchomp", "ability": "Rough Skin", "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge", "moves": ["Fake Out", "Grassy Glide", "High Horsepower", "U-turn"]},
            {"species": "Tornadus", "ability": "Prankster", "moves": ["Tailwind", "Taunt", "Hurricane", "Focus Blast"]},
        ]
        score, details = score_combination(combo, None)
        self.assertGreater(details["lead_synergy"], 0)


class TestBackCoverage(unittest.TestCase):
    """Test back slot coverage scoring."""

    def test_diverse_back_roles_bonus(self):
        """Test diverse back roles get bonus."""
        combo = [
            {"species": "Incineroar", "ability": "Intimidate", "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Throat Chop"]},
            {"species": "Rillaboom", "ability": "Grassy Surge", "moves": ["Fake Out", "Grassy Glide", "High Horsepower", "U-turn"]},
            {"species": "Garchomp", "ability": "Rough Skin", "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster", "moves": ["Tailwind", "Taunt", "Hurricane", "Focus Blast"]},
        ]
        score, details = score_combination(combo, None)
        self.assertGreater(details["back_coverage"], 0)


class TestWeaknessSpreading(unittest.TestCase):
    """Test weakness spreading penalty."""

    def test_penalizes_common_weaknesses(self):
        """Test 3+ Pokemon with same weakness penalized."""
        # Team with 3 Fire-weak (Steel, Grass, Bug, Ice)
        combo = [
            {"species": "Rillaboom", "ability": "Grassy Surge", "moves": ["Grassy Glide", "High Horsepower", "U-turn", "Protect"]},
            {"species": "Kartana", "ability": "Beast Boost", "moves": ["Leaf Blade", "Smart Strike", "Sacred Sword", "Protect"]},
            {"species": "Venusaur", "ability": "Chlorophyll", "moves": ["Leaf Storm", "Sludge Bomb", "Sleep Powder", "Protect"]},
            {"species": "Incineroar", "ability": "Intimidate", "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Throat Chop"]},
        ]
        score, details = score_combination(combo, None)
        self.assertLess(details["weakness_penalty"], 0)


class TestSpeedControl(unittest.TestCase):
    """Test speed control scoring."""

    def test_rewards_tailwind_trick_room(self):
        """Test Tailwind/Trick Room presence rewarded."""
        has_tw = [
            {"species": "Tornadus", "ability": "Prankster", "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
            {"species": "Incineroar", "ability": "Intimidate", "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin", "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge", "moves": ["Fake Out", "Grassy Glide", "High Horsepower", "Protect"]},
        ]
        score, details = score_combination(has_tw, None)
        self.assertGreater(details["speed_control_bonus"], 0)


class TestProtectFakeOut(unittest.TestCase):
    """Test Protect and Fake Out availability scoring."""

    def test_rewards_multiple_protect(self):
        """Test multiple Protect users rewarded."""
        score, details = score_combination([
            {"species": "Incineroar", "ability": "Intimidate", "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge", "moves": ["Fake Out", "Grassy Glide", "High Horsepower", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin", "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster", "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
        ], None)
        self.assertEqual(details["protect_bonus"], 4 * 0.3)


class TestNoHiddenInformation(unittest.TestCase):
    """Test policy uses only open information."""

    def test_no_battle_outcomes_used(self):
        """Test score_pokemon doesn't use battle outcomes."""
        # Just verify the function signature doesn't include battle result
        import inspect
        sig = inspect.signature(score_pokemon)
        params = list(sig.parameters.keys())
        self.assertNotIn("battle_result", params)
        self.assertIn("pokemon", params)
        self.assertIn("opponent_team", params)  # Opponent team IS visible in preview


class TestNoBasicTop4Mutation(unittest.TestCase):
    """Test matchup_top4_v2 doesn't mutate basic_top4 logic."""

    def test_basic_top4_unchanged(self):
        """Test basic_top4 still works identically."""
        result1 = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM_PHYSICAL, policy="basic_top4", seed=42)
        result2 = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM_PHYSICAL, policy="basic_top4", seed=42)
        self.assertEqual(result1.chosen_4, result2.chosen_4)

    def test_new_policy_is_separate(self):
        """Test matchup_top4_v2 is a separate policy."""
        try:
            choose_four_from_six(SAMPLE_TEAM, policy="matchup_top4_v2", seed=42)
        except ValueError as e:
            if "Unknown policy" in str(e):
                self.fail("matchup_top4_v2 not registered")


class TestArtifactValidators(unittest.TestCase):
    """Test artifact validation functions."""

    def test_validate_preview_valid(self):
        """Test valid preview passes."""
        result = choose_four_from_six(SAMPLE_TEAM, policy="matchup_top4_v2", seed=42)
        valid, errors = validate_preview(SAMPLE_TEAM, result)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_validate_preview_invalid_missing(self):
        """Test invalid preview with missing species fails."""
        from team_preview_policy import PreviewResult
        fake_result = PreviewResult(
            chosen_4=["Incineroar", "Garchomp", "Rillaboom", "FakeMon"],
            lead_2=["Incineroar", "Garchomp"],
            back_2=["Rillaboom", "FakeMon"],
            scores=[],
            policy="test",
            seed=42
        )

        valid, errors = validate_preview(SAMPLE_TEAM, fake_result)
        self.assertFalse(valid)
        self.assertTrue(any("not in team" in e for e in errors))


class TestAnalyzerAndInspector(unittest.TestCase):
    """Test analyzer and inspector behavior."""

    def test_analyzer_runs_without_error(self):
        """Test analyzer script runs."""
        import subprocess
        result = subprocess.run([
            sys.executable, "analyze_vgc2026_preview_policy_failures.py",
            "--artifact-tag", "phaseV2c2_smoke_test"
        ], capture_output=True, text=True, timeout=30, cwd=str(Path(__file__).resolve().parent))
        self.assertEqual(result.returncode, 0, f"Analyzer failed: {result.stderr}")

    def test_inspector_lists_pairs(self):
        """Test inspector lists pairs."""
        import subprocess
        result = subprocess.run([
            sys.executable, "inspect_vgc2026_preview_pair.py",
            "--artifact-tag", "phaseV2c2_smoke_test",
            "--list-arm", "D"
        ], capture_output=True, text=True, timeout=30, cwd=str(Path(__file__).resolve().parent))
        self.assertEqual(result.returncode, 0, f"Inspector failed: {result.stderr}")
        self.assertIn("Pair   0:", result.stdout)


class TestLifecycle(unittest.TestCase):
    """Test lifecycle natural exit."""

    def test_test_suite_exits_naturally(self):
        """A child import process exits without the poke-env atexit hang."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import poke_env_test_cleanup; "
                "import team_preview_policy; "
                "import eval_vgc2026_policies_offline; "
                "print('ok')",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")


class TestJointPlanOptimization(unittest.TestCase):
    """Regression tests for exact lead/back plan scoring."""

    def test_evaluates_all_ninety_plans(self):
        plans = evaluate_all_combinations(SAMPLE_TEAM, OPP_TEAM_PHYSICAL)
        self.assertEqual(len(plans), 90)

    def test_each_plan_has_two_leads_and_two_backs(self):
        for plan, _, details in evaluate_all_combinations(
            SAMPLE_TEAM, OPP_TEAM_PHYSICAL
        ):
            self.assertEqual(
                [pokemon["species"] for pokemon in plan[:2]],
                details["lead_species"],
            )
            self.assertEqual(
                [pokemon["species"] for pokemon in plan[2:]],
                details["back_species"],
            )

    def test_selected_lead_matches_scored_best_plan(self):
        best_plan, _, _ = evaluate_all_combinations(
            SAMPLE_TEAM, OPP_TEAM_PHYSICAL
        )[0]
        result = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="matchup_top4_v2",
            seed=42,
        )
        self.assertEqual(result.lead_2, [p["species"] for p in best_plan[:2]])
        self.assertEqual(result.back_2, [p["species"] for p in best_plan[2:]])

    def test_lead_synergy_is_order_symmetric(self):
        plan = [
            SAMPLE_TEAM[0],
            SAMPLE_TEAM[1],
            SAMPLE_TEAM[3],
            SAMPLE_TEAM[4],
        ]
        reverse = [plan[1], plan[0], plan[2], plan[3]]
        _, first = score_combination(plan, OPP_TEAM_PHYSICAL)
        _, second = score_combination(reverse, OPP_TEAM_PHYSICAL)
        self.assertEqual(first["lead_synergy"], second["lead_synergy"])

    def test_duplicate_role_penalty_is_negative(self):
        plan = [SAMPLE_TEAM[0], SAMPLE_TEAM[2], SAMPLE_TEAM[5], SAMPLE_TEAM[1]]
        _, details = score_combination(plan, OPP_TEAM_PHYSICAL)
        self.assertLess(details["role_duplicate_penalty"], 0.0)


class TestOfflineMetrics(unittest.TestCase):
    """Regression tests for normalized diversity and runtime metrics."""

    def test_entropy_equal_distribution(self):
        self.assertAlmostEqual(shannon_entropy_from_counts([1, 1, 1, 1]), 2.0)

    def test_entropy_empty_distribution(self):
        self.assertEqual(shannon_entropy_from_counts([]), 0.0)

    def test_offline_analysis_has_required_metrics(self):
        analysis = analyze_results(eval_all_policies(limit_teams=5))
        required = {
            "species_slot_entropy_bits",
            "combination_entropy_bits",
            "lead_pair_entropy_bits",
            "average_matchup_score",
            "minimum_matchup_score",
            "average_score_margin_vs_basic",
            "runtime_avg_ms",
            "runtime_p95_ms",
            "runtime_max_ms",
        }
        self.assertTrue(required.issubset(analysis["matchup_top4_v2"]))

    def test_species_entropy_is_bounded(self):
        analysis = analyze_results(eval_all_policies(limit_teams=5))
        metric = analysis["matchup_top4_v2"]["species_slot_entropy_bits"]
        species_count = analysis["matchup_top4_v2"]["unique_selected_species"]
        self.assertLessEqual(metric, math.log2(max(species_count, 1)))

    def test_runtime_metrics_are_ordered(self):
        analysis = analyze_results(eval_all_policies(limit_teams=5))
        metric = analysis["matchup_top4_v2"]
        self.assertGreaterEqual(metric["runtime_avg_ms"], 0.0)
        self.assertGreaterEqual(metric["runtime_p95_ms"], metric["runtime_avg_ms"])
        self.assertGreaterEqual(metric["runtime_max_ms"], metric["runtime_p95_ms"])

    def test_matchup_policy_records_opponent_adaptation(self):
        analysis = analyze_results(eval_all_policies(limit_teams=10))
        self.assertGreater(
            analysis["matchup_top4_v2"]["opponent_adaptive_changes"], 0
        )


class TestV2dSmokeSpecifications(unittest.TestCase):
    """The structural smoke must exercise the new policy in every V2 arm."""

    def test_exact_arm_counts_and_policies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = V2dSmokeRunner(
                limit_teams=5,
                log_dir=temp_dir,
                artifact_tag="spec_test",
                overwrite=True,
                smoke=True,
                smoke_battles=2,
            )
            specs = runner.generate_arm_specifications()
        self.assertEqual({arm: len(rows) for arm, rows in specs.items()}, {
            "A": 2, "B": 2, "C": 2, "D1": 2, "D2": 2,
        })
        self.assertEqual(specs["A"][0]["player_policy"], "matchup_top4_v2")
        self.assertEqual(specs["B"][0]["player_policy"], "matchup_top4_v2")
        self.assertEqual(specs["C"][0]["opponent_policy"], "matchup_top4_v2")
        self.assertEqual(specs["D1"][0]["player_policy"], "matchup_top4_v2")
        self.assertEqual(specs["D2"][0]["opponent_policy"], "matchup_top4_v2")


class TestV2dPairedQualification(unittest.TestCase):
    """Regression tests for the strict D1/D2 qualification."""

    def make_runner(self, temp_dir, pairs=3):
        return V2dPairedQualificationRunner(
            pairs=pairs,
            limit_teams=5,
            log_dir=temp_dir,
            artifact_tag="qualification_test",
            overwrite=True,
        )

    def test_exact_pair_count_and_policy_swap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = self.make_runner(temp_dir)
            specs = runner.generate_arm_specifications()
        self.assertEqual(set(specs), {"D1", "D2"})
        self.assertEqual(len(specs["D1"]), 3)
        self.assertEqual(len(specs["D2"]), 3)
        for first, second in zip(specs["D1"], specs["D2"]):
            self.assertEqual(first["pair_id"], second["pair_id"])
            self.assertEqual(first["our_team_idx"], second["our_team_idx"])
            self.assertEqual(first["opp_team_idx"], second["opp_team_idx"])
            self.assertEqual(
                (first["player_policy"], first["opponent_policy"]),
                ("matchup_top4_v2", "random"),
            )
            self.assertEqual(
                (second["player_policy"], second["opponent_policy"]),
                ("random", "matchup_top4_v2"),
            )

    def test_random_seed_is_stable_across_policy_swap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = self.make_runner(temp_dir)
            d1 = runner.get_preview_seeds(
                7, 0, "matchup_top4_v2", "random"
            )
            d2 = runner.get_preview_seeds(
                7, 0, "random", "matchup_top4_v2"
            )
        self.assertEqual(d1[0], d2[1])
        self.assertEqual(d1[1], d2[0])

    def test_seed_changes_between_pairs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = self.make_runner(temp_dir)
            first = runner.get_preview_seeds(
                1, 0, "matchup_top4_v2", "random"
            )
            second = runner.get_preview_seeds(
                2, 0, "matchup_top4_v2", "random"
            )
        self.assertNotEqual(first, second)

    def test_outcome_normalization_uses_policy_perspective(self):
        d1 = {
            "battle_tag": "D1_0000_p1",
            "battle_result": "win",
            "our_win": "True",
            "opponent_win": "False",
        }
        d2 = {
            "battle_tag": "D2_0000_p2",
            "battle_result": "loss",
            "our_win": "False",
            "opponent_win": "True",
        }
        self.assertEqual(normalize_v2_outcome(d1), "win")
        self.assertEqual(normalize_v2_outcome(d2), "win")

    def test_pair_analysis_merges_by_pair_id_not_row_order(self):
        rows = [
            {
                "pair_id": "1", "battle_tag": "D2_0001_p2",
                "battle_result": "win", "our_win": "True",
                "opponent_win": "False",
            },
            {
                "pair_id": "0", "battle_tag": "D1_0000_p1",
                "battle_result": "win", "our_win": "True",
                "opponent_win": "False",
            },
            {
                "pair_id": "1", "battle_tag": "D1_0001_p1",
                "battle_result": "loss", "our_win": "False",
                "opponent_win": "True",
            },
            {
                "pair_id": "0", "battle_tag": "D2_0000_p2",
                "battle_result": "loss", "our_win": "False",
                "opponent_win": "True",
            },
        ]
        result = analyze_pairs(rows)
        self.assertEqual(result["v2_both"], 1)
        self.assertEqual(result["random_both"], 1)
        self.assertEqual(result["split"], 0)
        self.assertEqual(result["invalid"], 0)

    def test_incomplete_pair_is_invalid(self):
        result = analyze_pairs([{
            "pair_id": "0", "battle_tag": "D1_0000_p1",
            "battle_result": "win", "our_win": "True",
            "opponent_win": "False",
        }])
        self.assertEqual(result["invalid"], 1)

    def test_exact_binomial_known_values(self):
        self.assertEqual(exact_binomial_p_value(0, 0), 1.0)
        self.assertAlmostEqual(exact_binomial_p_value(10, 10), 0.001953125)
        self.assertAlmostEqual(
            exact_binomial_p_value(10, 10, alternative="greater"),
            0.0009765625,
        )

    def test_wilson_interval_contains_half_for_even_record(self):
        low, high = wilson_interval(50, 100)
        self.assertLess(low, 0.5)
        self.assertGreater(high, 0.5)

    def test_artifact_validator_rejects_incomplete_pair(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "benchmark.csv"
            jsonl_path = root / "benchmark.jsonl"
            preview_path = root / "preview.csv"
            with csv_path.open("w", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "battle_tag", "pair_id", "player_policy",
                        "opponent_policy",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "battle_tag": "D1_0000_p1",
                    "pair_id": 0,
                    "player_policy": "matchup_top4_v2",
                    "opponent_policy": "random",
                })
            with jsonl_path.open("w") as handle:
                handle.write(json.dumps({
                    "battle_tag": "D1_0000_p1",
                    "battle_result": "win",
                }) + "\n")
            with preview_path.open("w", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "preview_matches_plan",
                        "observed_actual_lead_on_turn1",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "preview_matches_plan": "True",
                    "observed_actual_lead_on_turn1": "a|b",
                })
            errors = validate_qualification_artifacts(
                csv_path, jsonl_path, preview_path, expected_pairs=1
            )
        self.assertTrue(any("expected=2" in error for error in errors))
        self.assertIn("incomplete D1/D2 pair", errors)


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
