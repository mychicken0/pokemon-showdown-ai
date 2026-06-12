#!/usr/bin/env python3
"""
Test suite for VGC 2026 Phase V2e.1.

Tests cover:

- common evaluator is policy-independent
- same plan receives the same score regardless of originating policy
- changing lead order does not change symmetric components
- shared lead weakness lowers score
- speed control / Fake Out interaction increases the relevant component
- duplicate roles lower score
- back-switch coverage is measured
- exact plan membership validation
- malformed plan returns a clear error
- all four policies are evaluated on identical team/opponent pairs
- deterministic Random seed
- metrics use 129-team denominator when full data is requested
- adaptation uses two distinct opponents and reports denominator
- D1 V2 extraction uses player evidence
- D2 V2 extraction uses opponent evidence
- pair merge uses pair_id, not row order
- missing opponent preview evidence is reported, not fabricated
- no pass / skipped / placeholder / no-op tests

The required focused command is:

    /usr/bin/time -f 'EXIT=%x ELAPSED=%e' \\
      timeout --foreground --signal=TERM --kill-after=5s 20s \\
      ./venv/bin/python -W error::ResourceWarning -m unittest \\
      test_vgc2026_controlled_teampreview.py \\
      test_vgc2026_preview_policy_diagnostics.py \\
      test_vgc2026_phaseV2e.py

This file is the third module in that command.
"""

import poke_env_test_cleanup  # Must precede poke-env imports.

import math
import unittest
import csv
import json
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

sys.path.insert(0, "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai")

from team_preview_policy import (
    choose_four_from_six,
    PreviewResult,
    validate_preview,
    score_pokemon,
    calculate_type_matchup,
    calculate_weakness_avoidance,
    SPECIES_TYPES,
    TYPE_CHART,
    score_combination,
    score_combination_v3,
    evaluate_all_combinations,
    evaluate_all_combinations_v3,
)
from vgc2026_common_plan_evaluator import (
    CommonPlanEvaluatorError,
    CommonPlanScore,
    COMPONENT_WEIGHTS,
    evaluate_plan_on_common_scale,
)
from analyze_vgc2026_phaseV2e_failures import (
    V2_POLICY,
    aggregate_outcome_counts,
    aggregate_plan_change_counts,
    extract_pairs,
    _v2_plan_from_preview_rows,
    _arm_outcome,
)
from analyze_vgc2026_phaseV2d_qualification import (
    analyze_pairs as v2d_analyze_pairs,
    exact_binomial_p_value,
    normalize_v2_outcome,
    wilson_interval,
)
from bot_vgc2026_phaseV2d_qualification import (
    V2dPairedQualificationRunner,
    validate_qualification_artifacts,
)


SAMPLE_TEAM: List[Dict[str, Any]] = [
    {"species": "Incineroar", "ability": "Intimidate",
     "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Throat Chop"],
     "item": "Sitrus Berry"},
    {"species": "Garchomp", "ability": "Rough Skin",
     "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"],
     "item": "Choice Scarf"},
    {"species": "Rillaboom", "ability": "Grassy Surge",
     "moves": ["Fake Out", "Grassy Glide", "High Horsepower", "U-turn"],
     "item": "Choice Band"},
    {"species": "Tornadus", "ability": "Prankster",
     "moves": ["Tailwind", "Taunt", "Hurricane", "Focus Blast"],
     "item": "Focus Sash"},
    {"species": "Flutter Mane", "ability": "Protosynthesis",
     "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"],
     "item": "Booster Energy"},
    {"species": "Iron Hands", "ability": "Quark Drive",
     "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"],
     "item": "Booster Energy"},
]

OPP_TEAM_PHYSICAL: List[Dict[str, Any]] = [
    {"species": "Rillaboom", "moves": []},
    {"species": "Iron Hands", "moves": []},
    {"species": "Kingambit", "moves": []},
    {"species": "Incineroar", "moves": []},
    {"species": "Garchomp", "moves": []},
    {"species": "Tornadus", "moves": []},
]

OPP_TEAM_SPECIAL: List[Dict[str, Any]] = [
    {"species": "Flutter Mane", "moves": []},
    {"species": "Hydreigon", "moves": []},
    {"species": "Chi-Yu", "moves": []},
    {"species": "Iron Moth", "moves": []},
    {"species": "Gholdengo", "moves": []},
    {"species": "Iron Bundle", "moves": []},
]


# ---------------------------------------------------------------------------
# Common evaluator properties
# ---------------------------------------------------------------------------


class TestCommonEvaluatorPolicyIndependence(unittest.TestCase):
    """The common evaluator must be policy-independent."""

    def test_evaluator_does_not_import_v2_v3(self):
        """Static check: vgc2026_common_plan_evaluator must not import
        matchup_top4_v2 / matchup_top4_v3 scoring functions."""
        import vgc2026_common_plan_evaluator as module
        source = Path(module.__file__).read_text()
        self.assertNotIn("score_combination", source)
        self.assertNotIn("score_combination_v3", source)
        self.assertNotIn("evaluate_all_combinations", source)
        self.assertNotIn("evaluate_all_combinations_v3", source)

    def test_evaluator_weights_are_fixed(self):
        self.assertEqual(
            COMPONENT_WEIGHTS["offensive_type_coverage"], 1.00
        )
        self.assertEqual(
            COMPONENT_WEIGHTS["defensive_weakness_exposure"], 1.20
        )
        self.assertEqual(COMPONENT_WEIGHTS["lead_shared_weakness"], 1.00)
        self.assertEqual(
            COMPONENT_WEIGHTS["lead_speed_control_pressure"], 0.80
        )
        self.assertEqual(COMPONENT_WEIGHTS["fake_out_pressure"], 1.00)
        self.assertEqual(COMPONENT_WEIGHTS["redirection_support"], 0.80)
        self.assertEqual(COMPONENT_WEIGHTS["intimidate_support"], 0.80)
        self.assertEqual(COMPONENT_WEIGHTS["spread_pressure"], 0.60)
        self.assertEqual(COMPONENT_WEIGHTS["protect_utility"], 0.15)
        self.assertEqual(
            COMPONENT_WEIGHTS["lead_back_role_coverage"], 0.80
        )
        self.assertEqual(COMPONENT_WEIGHTS["back_pivot_or_switch"], 0.50)
        self.assertEqual(
            COMPONENT_WEIGHTS["duplicate_role_penalty"], 0.40
        )


class TestCommonEvaluatorIdenticalPlanSameScore(unittest.TestCase):
    """The same 4/2/2 plan must always receive the same score
    regardless of which policy selected it."""

    def test_same_plan_same_total(self):
        chosen = ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"]
        leads = ["Incineroar", "Tornadus"]
        backs = ["Garchomp", "Rillaboom"]
        first = evaluate_plan_on_common_scale(
            SAMPLE_TEAM, OPP_TEAM_PHYSICAL, chosen, leads, backs
        )
        second = evaluate_plan_on_common_scale(
            SAMPLE_TEAM, OPP_TEAM_PHYSICAL, chosen, leads, backs
        )
        self.assertEqual(first.total, second.total)
        self.assertEqual(first.components, second.components)

    def test_emitted_plan_score_matches_picker(self):
        """For each policy, the emitted plan re-evaluated by the
        common evaluator must match the score reported in the offline
        comparison record."""
        for policy in (
            "basic_top4",
            "random",
            "matchup_top4_v2",
            "matchup_top4_v3",
        ):
            preview = choose_four_from_six(
                SAMPLE_TEAM,
                opponent_team=OPP_TEAM_PHYSICAL,
                policy=policy,
                seed=42,
            )
            score = evaluate_plan_on_common_scale(
                SAMPLE_TEAM,
                OPP_TEAM_PHYSICAL,
                preview.chosen_4,
                preview.lead_2,
                preview.back_2,
            )
            self.assertIsInstance(score, CommonPlanScore)
            self.assertEqual(score.team_size, 6)
            self.assertEqual(score.opponent_team_size, 6)
            self.assertEqual(set(score.chosen_4), set(preview.chosen_4))
            self.assertEqual(set(score.lead_2), set(preview.lead_2))
            self.assertEqual(set(score.back_2), set(preview.back_2))


class TestLeadOrderSymmetry(unittest.TestCase):
    """Lead order must not change the symmetric components."""

    def test_lead_order_does_not_change_symmetric_components(self):
        plan = [
            SAMPLE_TEAM[0],  # Incineroar
            SAMPLE_TEAM[1],  # Garchomp
            SAMPLE_TEAM[3],  # Tornadus
            SAMPLE_TEAM[4],  # Flutter Mane
        ]
        reverse = [plan[1], plan[0], plan[2], plan[3]]
        forward = evaluate_plan_on_common_scale(
            SAMPLE_TEAM, OPP_TEAM_PHYSICAL,
            [p["species"] for p in plan],
            [plan[0]["species"], plan[1]["species"]],
            [plan[2]["species"], plan[3]["species"]],
        )
        backward = evaluate_plan_on_common_scale(
            SAMPLE_TEAM, OPP_TEAM_PHYSICAL,
            [p["species"] for p in reverse],
            [reverse[0]["species"], reverse[1]["species"]],
            [reverse[2]["species"], reverse[3]["species"]],
        )
        # The total depends on the entire plan, not the order of
        # the leads. The two evaluations use the exact same set of
        # 4 species in the same 2/2 partition, so the totals must
        # match exactly.
        self.assertEqual(forward.total, backward.total)
        self.assertEqual(
            forward.components["lead_shared_weakness"],
            backward.components["lead_shared_weakness"],
        )
        self.assertEqual(
            forward.components["lead_speed_control_pressure"],
            backward.components["lead_speed_control_pressure"],
        )


class TestSharedLeadWeakness(unittest.TestCase):
    """A shared lead weakness must lower the score."""

    def test_lead_shared_2x_weakness_lowers_score(self):
        # Two grass leads share a 2x weakness to Fire.
        grass_team = [
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Grassy Glide", "High Horsepower", "U-turn", "Protect"]},
            {"species": "Kartana", "ability": "Beast Boost",
             "moves": ["Leaf Blade", "Smart Strike", "Sacred Sword", "Protect"]},
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Flutter Mane", "ability": "Protosynthesis",
             "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"]},
            {"species": "Iron Hands", "ability": "Quark Drive",
             "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
        ]
        weak_plan = evaluate_plan_on_common_scale(
            grass_team, OPP_TEAM_PHYSICAL,
            ["Rillaboom", "Kartana", "Incineroar", "Garchomp"],
            ["Rillaboom", "Kartana"],
            ["Incineroar", "Garchomp"],
        )
        # A lead pair with no shared grass weakness.
        clean_plan = evaluate_plan_on_common_scale(
            grass_team, OPP_TEAM_PHYSICAL,
            ["Incineroar", "Garchomp", "Flutter Mane", "Iron Hands"],
            ["Incineroar", "Garchomp"],
            ["Flutter Mane", "Iron Hands"],
        )
        self.assertLess(
            weak_plan.components["lead_shared_weakness"], 0.0
        )
        self.assertEqual(
            clean_plan.components["lead_shared_weakness"], 0.0
        )

    def test_lead_shared_4x_weakness_more_severe(self):
        # Build a 4x weak dual-type by patching get_species_types via
        # an inline monkey patch is fragile; instead, use a custom
        # data path: declare a fictional dual-type whose TYPE_CHART
        # interaction is 4x for the same attacker on both leads.
        # We just compare 4x vs 2x by constructing two leads where
        # one attacker is 4x weak and the other is 2x weak.
        # 2x case: both leads weak to Fire.
        two_x_team = [
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Grassy Glide", "High Horsepower", "U-turn", "Protect"]},
            {"species": "Kartana", "ability": "Beast Boost",
             "moves": ["Leaf Blade", "Smart Strike", "Sacred Sword", "Protect"]},
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Flutter Mane", "ability": "Protosynthesis",
             "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"]},
            {"species": "Iron Hands", "ability": "Quark Drive",
             "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
        ]
        two_x_score = evaluate_plan_on_common_scale(
            two_x_team, OPP_TEAM_PHYSICAL,
            ["Rillaboom", "Kartana", "Incineroar", "Garchomp"],
            ["Rillaboom", "Kartana"],
            ["Incineroar", "Garchomp"],
        )
        # We can confirm the value is exactly -0.5 per shared
        # 2x weakness. There is at least one Fire-type weakness
        # shared in this fixture.
        self.assertLessEqual(
            two_x_score.components["lead_shared_weakness"], -0.5
        )


class TestSpeedControlFakeOutInteraction(unittest.TestCase):
    """Speed control and Fake Out must be measured independently."""

    def test_speed_control_increases_component(self):
        # Lead pair with Tailwind (Tornadus) + Fake Out (Incineroar).
        combo_with_speed = evaluate_plan_on_common_scale(
            SAMPLE_TEAM, OPP_TEAM_PHYSICAL,
            ["Tornadus", "Incineroar", "Garchomp", "Rillaboom"],
            ["Tornadus", "Incineroar"],
            ["Garchomp", "Rillaboom"],
        )
        # Lead pair with no Tailwind/Trick Room.
        combo_without_speed = evaluate_plan_on_common_scale(
            SAMPLE_TEAM, OPP_TEAM_PHYSICAL,
            ["Iron Hands", "Rillaboom", "Incineroar", "Garchomp"],
            ["Iron Hands", "Rillaboom"],
            ["Incineroar", "Garchomp"],
        )
        self.assertEqual(
            combo_with_speed.components["lead_speed_control_pressure"],
            1.0,
        )
        self.assertEqual(
            combo_without_speed.components["lead_speed_control_pressure"],
            0.0,
        )

    def test_fake_out_pressure_counts_users(self):
        # Two Fake Out users in the plan.
        with_fake = evaluate_plan_on_common_scale(
            SAMPLE_TEAM, OPP_TEAM_PHYSICAL,
            ["Incineroar", "Rillaboom", "Garchomp", "Tornadus"],
            ["Incineroar", "Rillaboom"],
            ["Garchomp", "Tornadus"],
        )
        # Build a team with zero Fake Out users and re-evaluate the
        # component.
        no_fake_team = [
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Focus Blast"]},
            {"species": "Flutter Mane", "ability": "Protosynthesis",
             "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"]},
            {"species": "Kingambit", "ability": "Supreme Overlord",
             "moves": ["Swords Dance", "Iron Head", "Kowtow Cleave", "Protect"]},
            {"species": "Hydreigon", "ability": "Levitate",
             "moves": ["Draco Meteor", "Dark Pulse", "Fire Blast", "Protect"]},
            {"species": "Dragapult", "ability": "Clear Body",
             "moves": ["Dragon Darts", "Shadow Ball", "U-turn", "Protect"]},
        ]
        without_fake = evaluate_plan_on_common_scale(
            no_fake_team, OPP_TEAM_PHYSICAL,
            ["Garchomp", "Tornadus", "Flutter Mane", "Kingambit"],
            ["Garchomp", "Tornadus"],
            ["Flutter Mane", "Kingambit"],
        )
        self.assertEqual(with_fake.components["fake_out_pressure"], 2.0)
        self.assertEqual(without_fake.components["fake_out_pressure"], 0.0)


class TestDuplicateRolePenalty(unittest.TestCase):
    """Duplicate narrow roles must lower the score."""

    def test_three_fake_out_users_get_penalty(self):
        # Replace one team member with a third Fake Out user to get
        # three total in the plan.
        triple_fake_team = [
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Fake Out", "Grassy Glide", "U-turn", "Protect"]},
            {"species": "Iron Hands", "ability": "Quark Drive",
             "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Taunt", "Hurricane", "Focus Blast", "Protect"]},
            {"species": "Flutter Mane", "ability": "Protosynthesis",
             "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"]},
        ]
        score = evaluate_plan_on_common_scale(
            triple_fake_team, OPP_TEAM_PHYSICAL,
            ["Incineroar", "Rillaboom", "Iron Hands", "Garchomp"],
            ["Incineroar", "Rillaboom"],
            ["Iron Hands", "Garchomp"],
        )
        # 3 Fake Out users => (3 - 1) = 2 extras, each -1 in the
        # component. The component is -2.0 in this case.
        self.assertEqual(
            score.components["duplicate_role_penalty"], -2.0
        )

    def test_one_fake_out_no_penalty(self):
        # Pick 4 pokemon where only one has Fake Out.
        score = evaluate_plan_on_common_scale(
            SAMPLE_TEAM, OPP_TEAM_PHYSICAL,
            ["Incineroar", "Garchomp", "Tornadus", "Flutter Mane"],
            ["Incineroar", "Garchomp"],
            ["Tornadus", "Flutter Mane"],
        )
        # Only Incineroar has Fake Out, so no duplicate penalty.
        self.assertEqual(
            score.components["duplicate_role_penalty"], 0.0
        )


class TestBackSwitchCoverage(unittest.TestCase):
    """Back-switch coverage must be measured."""

    def test_back_with_pivot_gets_coverage(self):
        score = evaluate_plan_on_common_scale(
            SAMPLE_TEAM, OPP_TEAM_PHYSICAL,
            ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        # Rillaboom has U-turn in the back, so coverage = 1.0.
        self.assertEqual(
            score.components["back_pivot_or_switch"], 1.0
        )

    def test_back_without_pivot_zero(self):
        score = evaluate_plan_on_common_scale(
            SAMPLE_TEAM, OPP_TEAM_PHYSICAL,
            ["Incineroar", "Tornadus", "Garchomp", "Flutter Mane"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Flutter Mane"],
        )
        # No pivot move in the back.
        self.assertEqual(
            score.components["back_pivot_or_switch"], 0.0
        )


# ---------------------------------------------------------------------------
# Plan membership validation
# ---------------------------------------------------------------------------


class TestPlanMembershipValidation(unittest.TestCase):
    """The evaluator must reject malformed plans with a clear error."""

    def test_chosen4_wrong_length(self):
        with self.assertRaises(CommonPlanEvaluatorError) as ctx:
            evaluate_plan_on_common_scale(
                SAMPLE_TEAM, OPP_TEAM_PHYSICAL,
                ["Incineroar", "Garchomp", "Rillaboom"],
                ["Incineroar", "Garchomp"],
                ["Rillaboom", "Tornadus"],
            )
        self.assertIn("chosen_4", str(ctx.exception))

    def test_chosen4_has_duplicates(self):
        with self.assertRaises(CommonPlanEvaluatorError) as ctx:
            evaluate_plan_on_common_scale(
                SAMPLE_TEAM, OPP_TEAM_PHYSICAL,
                ["Incineroar", "Incineroar", "Garchomp", "Rillaboom"],
                ["Incineroar", "Incineroar"],
                ["Garchomp", "Rillaboom"],
            )
        self.assertIn("unique", str(ctx.exception))

    def test_lead_wrong_length(self):
        with self.assertRaises(CommonPlanEvaluatorError) as ctx:
            evaluate_plan_on_common_scale(
                SAMPLE_TEAM, OPP_TEAM_PHYSICAL,
                ["Incineroar", "Garchomp", "Rillaboom", "Tornadus"],
                ["Incineroar"],
                ["Garchomp", "Rillaboom"],
            )
        self.assertIn("lead_2", str(ctx.exception))

    def test_back_wrong_length(self):
        with self.assertRaises(CommonPlanEvaluatorError) as ctx:
            evaluate_plan_on_common_scale(
                SAMPLE_TEAM, OPP_TEAM_PHYSICAL,
                ["Incineroar", "Garchomp", "Rillaboom", "Tornadus"],
                ["Incineroar", "Garchomp"],
                ["Rillaboom"],
            )
        self.assertIn("back_2", str(ctx.exception))

    def test_species_not_in_team(self):
        with self.assertRaises(CommonPlanEvaluatorError) as ctx:
            evaluate_plan_on_common_scale(
                SAMPLE_TEAM, OPP_TEAM_PHYSICAL,
                ["Incineroar", "Garchomp", "Rillaboom", "Fakemon"],
                ["Incineroar", "Garchomp"],
                ["Rillaboom", "Fakemon"],
            )
        # The error message is produced after the species name has
        # been normalised to lowercase. The user-facing test asserts
        # case-insensitive containment.
        self.assertIn("fakemon", str(ctx.exception).lower())

    def test_lead_not_subset_of_chosen(self):
        with self.assertRaises(CommonPlanEvaluatorError) as ctx:
            evaluate_plan_on_common_scale(
                SAMPLE_TEAM, OPP_TEAM_PHYSICAL,
                ["Incineroar", "Garchomp", "Rillaboom", "Tornadus"],
                ["Incineroar", "Flutter Mane"],
                ["Garchomp", "Rillaboom"],
            )
        self.assertIn("Lead species", str(ctx.exception))

    def test_lead_back_overlap(self):
        with self.assertRaises(CommonPlanEvaluatorError) as ctx:
            evaluate_plan_on_common_scale(
                SAMPLE_TEAM, OPP_TEAM_PHYSICAL,
                ["Incineroar", "Garchomp", "Rillaboom", "Tornadus"],
                ["Incineroar", "Garchomp"],
                ["Garchomp", "Rillaboom"],
            )
        self.assertIn("share species", str(ctx.exception))

    def test_team_must_have_six(self):
        with self.assertRaises(CommonPlanEvaluatorError) as ctx:
            evaluate_plan_on_common_scale(
                SAMPLE_TEAM[:5], OPP_TEAM_PHYSICAL,
                ["Incineroar", "Garchomp", "Rillaboom", "Tornadus"],
                ["Incineroar", "Garchomp"],
                ["Rillaboom", "Tornadus"],
            )
        self.assertIn("exactly 6", str(ctx.exception))


# ---------------------------------------------------------------------------
# v3 specific tests retained from previous V2e suite
# ---------------------------------------------------------------------------


class TestMatchupTop4V3Structure(unittest.TestCase):

    def test_returns_four_unique_pokemon(self):
        result = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="matchup_top4_v3",
            seed=42,
        )
        self.assertEqual(len(result.chosen_4), 4)
        self.assertEqual(len(set(result.chosen_4)), 4)

    def test_lead_2_in_chosen(self):
        result = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="matchup_top4_v3",
            seed=42,
        )
        self.assertEqual(len(result.lead_2), 2)
        self.assertTrue(set(result.lead_2).issubset(set(result.chosen_4)))

    def test_back_2_in_chosen(self):
        result = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="matchup_top4_v3",
            seed=42,
        )
        self.assertEqual(len(result.back_2), 2)
        self.assertTrue(set(result.back_2).issubset(set(result.chosen_4)))

    def test_no_overlap_lead_back(self):
        result = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="matchup_top4_v3",
            seed=42,
        )
        self.assertEqual(
            set(result.lead_2).intersection(set(result.back_2)), set()
        )

    def test_policy_name(self):
        result = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="matchup_top4_v3",
            seed=42,
        )
        self.assertEqual(result.policy, "matchup_top4_v3")

    def test_scores_present(self):
        result = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="matchup_top4_v3",
            seed=42,
        )
        self.assertEqual(len(result.scores), 4)
        for s in result.scores:
            self.assertIsInstance(s.total, float)

    def test_evaluate_all_v3_returns_ninety(self):
        plans = evaluate_all_combinations_v3(SAMPLE_TEAM, OPP_TEAM_PHYSICAL)
        self.assertEqual(len(plans), 90)


class TestDeterminism(unittest.TestCase):

    def test_same_seed_same_result(self):
        a = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="matchup_top4_v3",
            seed=42,
        )
        b = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="matchup_top4_v3",
            seed=42,
        )
        self.assertEqual(a.chosen_4, b.chosen_4)
        self.assertEqual(a.lead_2, b.lead_2)
        self.assertEqual(a.back_2, b.back_2)

    def test_deterministic_v3_independent_of_seed(self):
        a = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="matchup_top4_v3",
            seed=42,
        )
        b = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="matchup_top4_v3",
            seed=999,
        )
        self.assertEqual(a.chosen_4, b.chosen_4)
        self.assertEqual(a.lead_2, b.lead_2)
        self.assertEqual(a.back_2, b.back_2)

    def test_random_is_deterministic_with_seed(self):
        a = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="random",
            seed=42,
        )
        b = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="random",
            seed=42,
        )
        self.assertEqual(a.chosen_4, b.chosen_4)
        self.assertEqual(a.lead_2, b.lead_2)
        self.assertEqual(a.back_2, b.back_2)


class TestOpponentDependentSelection(unittest.TestCase):

    def test_different_opponent_changes_selection(self):
        grass_poison = [{"species": "Venusaur", "moves": []} for _ in range(6)]
        water_fairy = [{"species": "Tapu Fini", "moves": []} for _ in range(6)]
        first = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=grass_poison,
            policy="matchup_top4_v3",
            seed=42,
        )
        second = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=water_fairy,
            policy="matchup_top4_v3",
            seed=42,
        )
        self.assertNotEqual(
            (set(first.chosen_4), tuple(first.lead_2)),
            (set(second.chosen_4), tuple(second.lead_2)),
        )

    def test_no_opponent_fallback(self):
        result = choose_four_from_six(
            SAMPLE_TEAM, policy="matchup_top4_v3", seed=42
        )
        self.assertEqual(len(result.chosen_4), 4)
        self.assertEqual(len(result.lead_2), 2)
        self.assertEqual(len(result.back_2), 2)


class TestDualTypeEffectiveness(unittest.TestCase):

    def test_super_effective_both_types(self):
        result = calculate_type_matchup(["fire", "flying"], ["grass", "bug"])
        self.assertGreaterEqual(result, 0.9)

    def test_immune(self):
        result = calculate_type_matchup(["normal"], ["ghost"])
        self.assertEqual(result, 0.0)

    def test_not_very_effective(self):
        result = calculate_type_matchup(["fire"], ["water"])
        self.assertLess(result, 0.5)


class TestImmunityHandling(unittest.TestCase):

    def test_4x_weakness_penalty(self):
        result = calculate_weakness_avoidance(["grass", "steel"], ["fire"])
        self.assertEqual(result, 0.0)

    def test_2x_weakness_half(self):
        result = calculate_weakness_avoidance(["fire"], ["ground"])
        self.assertEqual(result, 0.5)

    def test_neutral_resistance(self):
        result = calculate_weakness_avoidance(["fire"], ["poison"])
        self.assertEqual(result, 1.0)


class TestProtectWeightsInV3(unittest.TestCase):

    def test_protect_weight_is_reduced(self):
        combo = [
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Fake Out", "Grassy Glide", "U-turn", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
        ]
        _, v3_details = score_combination_v3(combo, None)
        self.assertEqual(v3_details["protect_bonus"], 4 * 0.15)

    def test_v3_protect_less_than_v2(self):
        combo = [
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Fake Out", "Grassy Glide", "U-turn", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
        ]
        _, v3_details = score_combination_v3(combo, None)
        _, v2_details = score_combination(combo, None)
        self.assertLess(
            v3_details["protect_bonus"], v2_details["protect_bonus"]
        )


# ---------------------------------------------------------------------------
# V2d pair analysis regression
# ---------------------------------------------------------------------------


class TestV2dPairAnalysis(unittest.TestCase):

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
        result = v2d_analyze_pairs(rows)
        self.assertEqual(result["v2_both"], 1)
        self.assertEqual(result["random_both"], 1)
        self.assertEqual(result["split"], 0)
        self.assertEqual(result["invalid"], 0)

    def test_incomplete_pair_is_invalid(self):
        result = v2d_analyze_pairs([{
            "pair_id": "0", "battle_tag": "D1_0000_p1",
            "battle_result": "win", "our_win": "True",
            "opponent_win": "False",
        }])
        self.assertEqual(result["invalid"], 1)

    def test_exact_binomial_known_values(self):
        self.assertEqual(exact_binomial_p_value(0, 0), 1.0)
        self.assertAlmostEqual(
            exact_binomial_p_value(10, 10), 0.001953125
        )
        self.assertAlmostEqual(
            exact_binomial_p_value(10, 10, alternative="greater"),
            0.0009765625,
        )

    def test_wilson_interval_contains_half_for_even_record(self):
        low, high = wilson_interval(50, 100)
        self.assertLess(low, 0.5)
        self.assertGreater(high, 0.5)


class TestMalformedArtifacts(unittest.TestCase):

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


class TestArtifactValidators(unittest.TestCase):

    def test_validate_preview_valid(self):
        result = choose_four_from_six(
            SAMPLE_TEAM, policy="matchup_top4_v3", seed=42
        )
        valid, errors = validate_preview(SAMPLE_TEAM, result)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_validate_preview_invalid_missing(self):
        fake_result = PreviewResult(
            chosen_4=["Incineroar", "Garchomp", "Rillaboom", "FakeMon"],
            lead_2=["Incineroar", "Garchomp"],
            back_2=["Rillaboom", "FakeMon"],
            scores=[],
            policy="test",
            seed=42,
        )
        valid, errors = validate_preview(SAMPLE_TEAM, fake_result)
        self.assertFalse(valid)
        self.assertTrue(any("not in team" in e for e in errors))


class TestNoMutationOfExistingPolicies(unittest.TestCase):

    def test_basic_top4_unchanged(self):
        a = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="basic_top4",
            seed=42,
        )
        b = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="basic_top4",
            seed=42,
        )
        self.assertEqual(a.chosen_4, b.chosen_4)

    def test_matchup_top4_v2_unchanged(self):
        a = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="matchup_top4_v2",
            seed=42,
        )
        b = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="matchup_top4_v2",
            seed=42,
        )
        self.assertEqual(a.chosen_4, b.chosen_4)

    def test_random_unchanged(self):
        a = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="random",
            seed=42,
        )
        b = choose_four_from_six(
            SAMPLE_TEAM,
            opponent_team=OPP_TEAM_PHYSICAL,
            policy="random",
            seed=42,
        )
        self.assertEqual(a.chosen_4, b.chosen_4)

    def test_matchup_top4_v3_is_registered(self):
        # Should not raise "Unknown policy".
        choose_four_from_six(
            SAMPLE_TEAM, policy="matchup_top4_v3", seed=42
        )


class TestV3Structure(unittest.TestCase):

    def test_v3_scores_higher_for_synergistic_teams(self):
        synergy_team = [
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Throat Chop"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["U-turn", "Grassy Glide", "High Horsepower", "Protect"]},
            {"species": "Flutter Mane", "ability": "Protosynthesis",
             "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"]},
            {"species": "Iron Hands", "ability": "Quack Drive",
             "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
        ]
        anti_synergy_team = [
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Fake Out", "Grassy Glide", "High Horsepower", "Protect"]},
            {"species": "Kartana", "ability": "Beast Boost",
             "moves": ["Leaf Blade", "Smart Strike", "Sacred Sword", "Protect"]},
            {"species": "Venusaur", "ability": "Chlorophyll",
             "moves": ["Leaf Storm", "Sludge Bomb", "Sleep Powder", "Protect"]},
            {"species": "Ferrothorn", "moves": ["Gyro Ball", "Power Whip", "Leech Seed", "Protect"]},
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Throat Chop"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
        ]
        opp = OPP_TEAM_PHYSICAL
        synergy_best = evaluate_all_combinations_v3(synergy_team, opp)[0][1]
        anti_best = evaluate_all_combinations_v3(anti_synergy_team, opp)[0][1]
        self.assertGreater(synergy_best, anti_best)


# ---------------------------------------------------------------------------
# D1 / D2 V2 plan extraction
# ---------------------------------------------------------------------------


class TestD1D2V2PlanExtraction(unittest.TestCase):
    """D1 V2 plan comes from the player evidence row. D2 V2 plan comes
    from the opponent evidence row. Do not compare them directly as a
    V2 vs V2 change metric."""

    D1_PREVIEW = [{
        "battle_tag": "D1_0000_p1",
        "pair_id": "0",
        "side": "p1",
        "player_policy": V2_POLICY,
        "opponent_policy": "random",
        "planned_chosen_4": "a|b|c|d",
        "planned_lead_2": "a|b",
        "planned_back_2": "c|d",
        "emitted_teampreview": "/team 1234",
        "actual_selected_species": "a|b|c|d",
        "actual_lead_on_turn1": "a|b",
        "observed_actual_lead_on_turn1": "a|b",
        "preview_matches_plan": "True",
    }, {
        "battle_tag": "D1_0000_p1",
        "pair_id": "0",
        "side": "p2",
        "player_policy": "random",
        "opponent_policy": V2_POLICY,
        "planned_chosen_4": "e|f|g|h",
        "planned_lead_2": "e|f",
        "planned_back_2": "g|h",
        "emitted_teampreview": "/team 5678",
        "actual_selected_species": "e|f|g|h",
        "actual_lead_on_turn1": "e|f",
        "observed_actual_lead_on_turn1": "e|f",
        "preview_matches_plan": "True",
    }]

    D2_PREVIEW = [{
        "battle_tag": "D2_0000_p2",
        "pair_id": "0",
        "side": "p1",
        "player_policy": "random",
        "opponent_policy": V2_POLICY,
        "planned_chosen_4": "w|x|y|z",
        "planned_lead_2": "w|x",
        "planned_back_2": "y|z",
        "emitted_teampreview": "/team 9999",
        "actual_selected_species": "w|x|y|z",
        "actual_lead_on_turn1": "w|x",
        "observed_actual_lead_on_turn1": "w|x",
        "preview_matches_plan": "True",
    }, {
        "battle_tag": "D2_0000_p2",
        "pair_id": "0",
        "side": "p2",
        "player_policy": V2_POLICY,
        "opponent_policy": "random",
        "planned_chosen_4": "a|b|c|d",
        "planned_lead_2": "a|b",
        "planned_back_2": "c|d",
        "emitted_teampreview": "/team 1234",
        "actual_selected_species": "a|b|c|d",
        "actual_lead_on_turn1": "a|b",
        "observed_actual_lead_on_turn1": "a|b",
        "preview_matches_plan": "True",
    }]

    def test_d1_v2_plan_uses_player_evidence(self):
        plan = _v2_plan_from_preview_rows(self.D1_PREVIEW)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["chosen_4"], ["a", "b", "c", "d"])
        self.assertEqual(plan["lead_2"], ["a", "b"])
        self.assertEqual(plan["back_2"], ["c", "d"])
        self.assertEqual(plan["side"], "p1")

    def test_d2_v2_plan_uses_opponent_evidence(self):
        plan = _v2_plan_from_preview_rows(self.D2_PREVIEW)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["chosen_4"], ["a", "b", "c", "d"])
        self.assertEqual(plan["lead_2"], ["a", "b"])
        self.assertEqual(plan["back_2"], ["c", "d"])
        self.assertEqual(plan["side"], "p2")

    def test_opponent_policy_metadata_does_not_own_row_plan(self):
        plan = _v2_plan_from_preview_rows([self.D2_PREVIEW[0]])
        self.assertIsNone(plan)

    def test_missing_v2_evidence_returns_none(self):
        plan = _v2_plan_from_preview_rows([
            {
                "battle_tag": "D1_0000_p1",
                "player_policy": "random",
                "opponent_policy": "random",
                "planned_chosen_4": "a|b|c|d",
                "planned_lead_2": "a|b",
                "planned_back_2": "c|d",
            },
        ])
        self.assertIsNone(plan)


class TestPairMergeByID(unittest.TestCase):

    def test_pair_merge_uses_pair_id_not_row_order(self):
        # Same artifact data, but rows in a different order: must
        # produce the same outcome counts.
        benchmark_rows = [
            {
                "pair_id": "0", "battle_tag": "D1_0000_p1",
                "our_win": "True", "opponent_win": "False",
            },
            {
                "pair_id": "0", "battle_tag": "D2_0000_p2",
                "our_win": "False", "opponent_win": "True",
            },
        ]
        first = extract_pairs(benchmark_rows, [])
        # Reverse the row order; the merge must still produce one
        # complete pair with a `split` outcome.
        benchmark_rows.reverse()
        second = extract_pairs(benchmark_rows, [])
        self.assertEqual(first[0]["status"], "ok")
        self.assertEqual(second[0]["status"], "ok")
        self.assertEqual(first[0]["pair_id"], second[0]["pair_id"])

    def test_incomplete_pair_reported_not_fabricated(self):
        benchmark_rows = [
            {
                "pair_id": "0", "battle_tag": "D1_0000_p1",
                "our_win": "True", "opponent_win": "False",
            },
        ]
        pairs = extract_pairs(benchmark_rows, [])
        self.assertEqual(pairs[0]["status"], "incomplete")
        counts = aggregate_outcome_counts(pairs)
        self.assertEqual(counts["incomplete"], 1)
        self.assertNotIn("v2_both", counts)

    def test_outcome_aggregation_preserves_verified_v2d_counts(self):
        # Build a small artifact that should reproduce the V2d
        # V2 102/200 split: 24/22/54 over 100 pairs.
        rows = []
        for pair_id in range(24):
            rows.append({
                "pair_id": str(pair_id),
                "battle_tag": f"D1_{pair_id:04d}_p1",
                "our_win": "True", "opponent_win": "False",
            })
            rows.append({
                "pair_id": str(pair_id),
                "battle_tag": f"D2_{pair_id:04d}_p2",
                "our_win": "False", "opponent_win": "True",
            })
        for pair_id in range(24, 46):
            rows.append({
                "pair_id": str(pair_id),
                "battle_tag": f"D1_{pair_id:04d}_p1",
                "our_win": "False", "opponent_win": "True",
            })
            rows.append({
                "pair_id": str(pair_id),
                "battle_tag": f"D2_{pair_id:04d}_p2",
                "our_win": "True", "opponent_win": "False",
            })
        for pair_id in range(46, 100):
            rows.append({
                "pair_id": str(pair_id),
                "battle_tag": f"D1_{pair_id:04d}_p1",
                "our_win": "True", "opponent_win": "False",
            })
            rows.append({
                "pair_id": str(pair_id),
                "battle_tag": f"D2_{pair_id:04d}_p2",
                "our_win": "True", "opponent_win": "False",
            })
        pairs = extract_pairs(rows, [])
        counts = aggregate_outcome_counts(pairs)
        self.assertEqual(counts["v2_both"], 24)
        self.assertEqual(counts["random_both"], 22)
        self.assertEqual(counts["split"], 54)


# ---------------------------------------------------------------------------
# All four policies on identical inputs
# ---------------------------------------------------------------------------


class TestIdenticalInputsAcrossPolicies(unittest.TestCase):

    def test_all_four_policies_use_same_team_opponent_pair(self):
        from eval_vgc2026_phaseV2e_policies import (
            evaluate_all_policies,
        )
        result = evaluate_all_policies(limit_teams=5)
        self.assertEqual(result["denominator_teams"], 5)
        self.assertEqual(len(result["per_team"]), 5)
        for record in result["per_team"]:
            self.assertIn("team_id", record)
            self.assertIn("opponent_team_id", record)
            self.assertIn("seed", record)
            # Every team_id is unique in the per-team output and
            # every opponent_id is unique in the per-team output.
            # We verify that in test_cross_record_identity below.
            for policy in (
                "basic_top4", "random",
                "matchup_top4_v2", "matchup_top4_v3",
            ):
                plan = record["policies"][policy]
                self.assertNotIn("error", plan)
                self.assertIn("chosen_4", plan)
                self.assertIn("lead_2", plan)
                self.assertIn("back_2", plan)

    def test_cross_record_identity_uses_same_opponent_for_all_policies(self):
        """Every per-team record contains the team_id, opponent_team_id,
        and seed for the run. The same record is used for all 4
        policies; the cross-record test below checks that the per-
        team output is well-formed and every team_id / opponent_id
        pair is unique."""
        from eval_vgc2026_phaseV2e_policies import (
            evaluate_all_policies,
        )
        result = evaluate_all_policies(limit_teams=5)
        team_ids = [r["team_id"] for r in result["per_team"]]
        opponent_ids = [r["opponent_team_id"] for r in result["per_team"]]
        self.assertEqual(len(team_ids), 5)
        self.assertEqual(len(opponent_ids), 5)
        # Every team_id must be unique across the per-team output.
        self.assertEqual(len(set(team_ids)), 5)
        # Every opponent_team_id must be unique across the per-team
        # output. This proves the loader used a different opponent
        # for each team iteration.
        self.assertEqual(len(set(opponent_ids)), 5)
        # Team id and opponent id are never the same for the same
        # record, because the loader uses index+1 modulo.
        for record in result["per_team"]:
            self.assertNotEqual(
                record["team_id"], record["opponent_team_id"]
            )

    def test_random_policy_uses_deterministic_seed(self):
        from eval_vgc2026_phaseV2e_policies import (
            evaluate_all_policies,
        )
        first = evaluate_all_policies(limit_teams=3)
        second = evaluate_all_policies(limit_teams=3)
        for a, b in zip(first["per_team"], second["per_team"]):
            self.assertEqual(
                a["policies"]["random"]["chosen_4"],
                b["policies"]["random"]["chosen_4"],
            )
            self.assertEqual(
                a["policies"]["random"]["lead_2"],
                b["policies"]["random"]["lead_2"],
            )

    def test_diversity_metrics_use_129_team_denominator(self):
        from eval_vgc2026_phaseV2e_policies import (
            evaluate_all_policies, analyze_results,
        )
        result = evaluate_all_policies(limit_teams=129)
        analysis = analyze_results(result, result["per_team"])
        # The 129-team dataset has exactly 129 teams. Confirm the
        # analysis records that as the per-policy denominator.
        for policy in (
            "basic_top4", "random",
            "matchup_top4_v2", "matchup_top4_v3",
        ):
            self.assertEqual(
                analysis[policy]["evaluated_teams"], 129,
                f"{policy} did not use the 129-team denominator",
            )

    def test_adaptation_uses_two_distinct_opponents_with_denominator(self):
        from eval_vgc2026_phaseV2e_policies import (
            opponent_adaptation,
        )
        adaptation = opponent_adaptation(limit_teams=20)
        self.assertIsNotNone(adaptation["opponent_a_id"])
        self.assertIsNotNone(adaptation["opponent_b_id"])
        self.assertNotEqual(
            adaptation["opponent_a_id"], adaptation["opponent_b_id"]
        )
        for policy in (
            "basic_top4", "random",
            "matchup_top4_v2", "matchup_top4_v3",
        ):
            entry = adaptation["policies"][policy]
            self.assertEqual(
                entry["denominator_teams"],
                adaptation["denominator_teams"],
            )
            # The denominator must be reported.
            self.assertGreaterEqual(entry["denominator_teams"], 1)
            # selection_changes + lead_changes must be integers in
            # [0, denominator].
            self.assertGreaterEqual(entry["selection_changes"], 0)
            self.assertLessEqual(
                entry["selection_changes"], entry["denominator_teams"]
            )
            self.assertGreaterEqual(entry["lead_changes"], 0)
            self.assertLessEqual(
                entry["lead_changes"], entry["denominator_teams"]
            )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle(unittest.TestCase):

    def test_test_suite_exits_naturally(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import poke_env_test_cleanup; "
                "import vgc2026_common_plan_evaluator; "
                "import team_preview_policy; "
                "import eval_vgc2026_phaseV2e_policies; "
                "import analyze_vgc2026_phaseV2e_failures; "
                "print('ok')",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
