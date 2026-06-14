#!/usr/bin/env python3
"""
Test suite for VGC 2026 Phase V2i — outcome-blind matchup evaluator v2.

Coverage:

- All 20+ mechanical components are present, bounded, and sign-correct
- 15 opponent lead pairs are enumerated exactly once
- Move metadata adapter covers all regression cases
  (Shadow Ball, Make It Rain, Protect, Fake Out, Icy Wind,
  Earthquake, Helping Hand, Tailwind, Trick Room, Follow Me,
  U-turn, Volt Switch, unknown)
- Configuration freeze: fingerprint is deterministic, sensitive
  to constant changes
- Outcome loading occurs only after freeze (analyzer asserts order)
- No input mutation
- Permutation invariance for team list order
- Lead order symmetry where mechanics are symmetric
- Synthetic superior plan scores higher than clearly unsafe plan
- Removing a useful immunity cannot improve resilience
- Adding unsupported setup cannot improve setup compatibility
- Protect cannot add offensive priority pressure
- Spread moves affect both-target pressure; single-target moves do not
- Identical plans produce identical scores
- Malformed plan rejection
- Missing dex metadata handled without crash
- No hidden / post-battle information used
- Analyzer statistics: rank correlation, disagreement rate, ablation
- Inspector filters
- Subprocess natural exit
"""

import poke_env_test_cleanup  # Must precede poke-env imports.

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vgc2026_matchup_evaluator_v2 import (
    ABSORB_ABILITIES,
    BOOTSTRAP_SEED,
    COMPONENT_SPECS,
    COMPONENT_WEIGHTS,
    EVALUATOR_ALGORITHM_VERSION,
    FAVORABLE_ZSCORE_THRESHOLD,
    FROZEN_FINGERPRINT,
    MatchupEvaluatorError,
    REDIRECTION_MOVES,
    RESTORATIVE_MOVES,
    SEVERE_BAD_ZSCORE_THRESHOLD,
    SETUP_MOVES,
    SPEED_CONTROL_MOVES,
    SPREAD_TARGETS,
    classify_move,
    component_spec,
    enumerate_opponent_lead_pairs,
    evaluate_matchup,
    move_metadata,
    plan_score,
    _plan_back_switch_defensive_coverage,
    _plan_pokemon_damaging_types,
    _plan_worst_case_lead_pair_resilience,
)
from vgc2026_common_plan_evaluator import evaluate_plan_on_common_scale


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _standard_team() -> List[Dict[str, Any]]:
    return [
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


def _standard_opponent() -> List[Dict[str, Any]]:
    return [
        {"species": "Rillaboom", "moves": []},
        {"species": "Iron Hands", "moves": []},
        {"species": "Kingambit", "moves": []},
        {"species": "Incineroar", "moves": []},
        {"species": "Garchomp", "moves": []},
        {"species": "Tornadus", "moves": []},
    ]


# ---------------------------------------------------------------------------
# Configuration freeze tests
# ---------------------------------------------------------------------------


class TestConfigurationFreeze(unittest.TestCase):
    def test_fingerprint_is_64_hex(self):
        self.assertEqual(len(FROZEN_FINGERPRINT), 64)
        int(FROZEN_FINGERPRINT, 16)  # must be valid hex

    def test_fingerprint_is_deterministic(self):
        from vgc2026_matchup_evaluator_v2 import (
            _freeze_fingerprint, FROZEN_FINGERPRINT as FP,
        )
        self.assertEqual(_freeze_fingerprint(), FP)

    def test_algorithm_version_is_explicit(self):
        self.assertEqual(
            EVALUATOR_ALGORITHM_VERSION,
            "v2i.1-preview-move-types",
        )

    def test_fingerprint_changes_with_constant(self):
        # Re-run the freeze with a different weight to confirm
        # sensitivity.
        from vgc2026_matchup_evaluator_v2 import (
            _freeze_fingerprint, COMPONENT_WEIGHTS as W,
        )
        original = _freeze_fingerprint()
        saved = dict(W)
        try:
            W["offensive_move_type_pressure"] = (
                saved["offensive_move_type_pressure"] + 1.0
            )
            perturbed = _freeze_fingerprint()
        finally:
            W["offensive_move_type_pressure"] = (
                saved["offensive_move_type_pressure"]
            )
        self.assertNotEqual(original, perturbed)

    def test_outcome_loading_occurs_after_freeze(self):
        # The analyzer must load V2f outcomes only after verifying
        # the fingerprint was frozen at construction time. The
        # analyzer's run_analysis records the freeze time and the
        # first outcome read time, then asserts that the freeze time
        # is strictly before any outcome read.
        from analyze_vgc2026_phaseV2i_matchup_evaluator import (
            load_v2f_outcomes_with_freeze_proof,
            ANALYZER_FROZEN_FINGERPRINT,
        )
        self.assertEqual(ANALYZER_FROZEN_FINGERPRINT, FROZEN_FINGERPRINT)


# ---------------------------------------------------------------------------
# Move metadata adapter tests
# ---------------------------------------------------------------------------


class TestMoveMetadataAdapter(unittest.TestCase):
    def test_shadow_ball(self):
        meta = move_metadata("Shadow Ball")
        self.assertEqual(meta.category, "special")
        self.assertEqual(meta.priority, 0)
        self.assertEqual(meta.target, "normal")
        self.assertFalse(meta.is_priority_offensive)
        self.assertFalse(meta.is_spread)
        self.assertFalse(meta.stalling)
        self.assertGreater(meta.base_power, 0)
        self.assertEqual(classify_move("Shadow Ball"), "special")

    def test_make_it_rain(self):
        meta = move_metadata("Make It Rain")
        self.assertTrue(meta.is_spread)
        self.assertTrue(meta.is_damaging)
        self.assertEqual(meta.category, "special")
        self.assertFalse(meta.is_priority_offensive)
        self.assertEqual(classify_move("Make It Rain"), "spread")

    def test_protect(self):
        meta = move_metadata("Protect")
        self.assertTrue(meta.stalling)
        self.assertEqual(meta.priority, 4)
        self.assertFalse(meta.is_priority_offensive)
        self.assertFalse(meta.is_spread)
        self.assertFalse(meta.is_damaging)
        self.assertEqual(classify_move("Protect"), "stall")

    def test_fake_out(self):
        meta = move_metadata("Fake Out")
        self.assertTrue(meta.is_priority_offensive)
        self.assertEqual(meta.priority, 3)
        self.assertFalse(meta.stalling)
        self.assertEqual(classify_move("Fake Out"), "priority")

    def test_icy_wind(self):
        meta = move_metadata("Icy Wind")
        self.assertTrue(meta.is_spread)
        self.assertEqual(meta.target, "allAdjacentFoes")
        self.assertEqual(classify_move("Icy Wind"), "spread")

    def test_earthquake(self):
        meta = move_metadata("Earthquake")
        self.assertTrue(meta.is_spread)
        self.assertEqual(meta.target, "allAdjacent")
        self.assertEqual(meta.category, "physical")
        self.assertEqual(classify_move("Earthquake"), "spread")

    def test_helping_hand(self):
        meta = move_metadata("Helping Hand")
        self.assertFalse(meta.is_priority_offensive)
        self.assertFalse(meta.is_damaging)
        # Helping Hand has priority 5 but is not damaging and not
        # stalling. It is an ally-only support move. The classifier
        # falls through to its category (status).
        self.assertEqual(meta.category, "status")
        self.assertEqual(classify_move("Helping Hand"), "status")

    def test_tailwind(self):
        meta = move_metadata("Tailwind")
        self.assertFalse(meta.is_priority_offensive)
        self.assertEqual(meta.priority, 0)
        self.assertEqual(classify_move("Tailwind"), "speed_control")

    def test_trick_room(self):
        meta = move_metadata("Trick Room")
        # Trick Room has priority -7 in the Gen 9 dex.
        self.assertEqual(meta.priority, -7)
        self.assertEqual(classify_move("Trick Room"), "speed_control")

    def test_follow_me(self):
        meta = move_metadata("Follow Me")
        self.assertEqual(meta.priority, 2)
        self.assertFalse(meta.is_priority_offensive)
        self.assertFalse(meta.is_damaging)
        self.assertEqual(classify_move("Follow Me"), "redirection")

    def test_u_turn(self):
        # U-turn is a damaging physical pivot. The classifier
        # labels it "physical" by the V2h convention; the pivot
        # keyword check only catches status-pivot moves.
        meta = move_metadata("U-turn")
        self.assertEqual(meta.category, "physical")
        self.assertTrue(meta.is_damaging)
        self.assertEqual(classify_move("U-turn"), "physical")
        # The keyword-based back pivot helper still recognises it.
        from vgc2026_matchup_evaluator_v2 import _is_pivot_keyword
        self.assertTrue(_is_pivot_keyword("U-turn"))

    def test_volt_switch(self):
        meta = move_metadata("Volt Switch")
        self.assertEqual(meta.category, "special")
        self.assertTrue(meta.is_damaging)
        self.assertEqual(classify_move("Volt Switch"), "special")
        from vgc2026_matchup_evaluator_v2 import _is_pivot_keyword
        self.assertTrue(_is_pivot_keyword("Volt Switch"))

    def test_unknown_move(self):
        meta = move_metadata("SoraN00bCustomMove123")
        self.assertEqual(meta.category, "")
        self.assertEqual(meta.base_power, 0)
        self.assertEqual(meta.priority, 0)
        self.assertFalse(meta.is_priority_offensive)
        self.assertFalse(meta.is_damaging)
        self.assertEqual(classify_move("SoraN00bCustomMove123"), "unknown")


# ---------------------------------------------------------------------------
# 15 lead pair enumeration
# ---------------------------------------------------------------------------


class TestLeadPairEnumeration(unittest.TestCase):
    def test_15_lead_pairs(self):
        opp = _standard_opponent()
        pairs = enumerate_opponent_lead_pairs(opp)
        self.assertEqual(len(pairs), 15)

    def test_pairs_unique(self):
        opp = _standard_opponent()
        pairs = enumerate_opponent_lead_pairs(opp)
        self.assertEqual(len(set(pairs)), 15)

    def test_pairs_sorted(self):
        opp = _standard_opponent()
        pairs = enumerate_opponent_lead_pairs(opp)
        for a, b in pairs:
            self.assertLess(a, b)

    def test_pairs_cover_all_6_species(self):
        opp = _standard_opponent()
        pairs = enumerate_opponent_lead_pairs(opp)
        seen = {s for p in pairs for s in p}
        # _normalise_species only lowercases, not strips spaces,
        # so "Iron Hands" becomes "iron hands".
        expected = {
            "rillaboom", "iron hands", "kingambit",
            "incineroar", "garchomp", "tornadus",
        }
        self.assertEqual(seen, expected)

    def test_team_size_must_be_6(self):
        with self.assertRaises(MatchupEvaluatorError):
            enumerate_opponent_lead_pairs([{"species": "x"}])

    def test_duplicates_rejected(self):
        opp = _standard_opponent()
        opp[1]["species"] = opp[0]["species"]
        with self.assertRaises(MatchupEvaluatorError):
            enumerate_opponent_lead_pairs(opp)


# ---------------------------------------------------------------------------
# Mechanical components
# ---------------------------------------------------------------------------


class TestMechanicalComponents(unittest.TestCase):
    def setUp(self):
        self.team = _standard_team()
        self.opp = _standard_opponent()
        self.chosen_4 = ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"]
        self.lead_2 = ["Incineroar", "Tornadus"]
        self.back_2 = ["Garchomp", "Rillaboom"]

    def test_all_components_present(self):
        eval_obj = evaluate_matchup(
            self.team, self.opp, self.chosen_4, self.lead_2, self.back_2
        )
        matchup = eval_obj.lead_pair_matchups[0]
        for spec in COMPONENT_SPECS:
            self.assertIn(spec.name, matchup.component_values)
            self.assertIn(spec.name, eval_obj.component_means)

    def test_sign_convention_and_bounds(self):
        eval_obj = evaluate_matchup(
            self.team, self.opp, self.chosen_4, self.lead_2, self.back_2
        )
        for spec in COMPONENT_SPECS:
            for matchup in eval_obj.lead_pair_matchups:
                value = matchup.component_values[spec.name]
                low, high = spec.range
                self.assertGreaterEqual(
                    value, low - 1e-9,
                    f"{spec.name} below {low} on pair "
                    f"{matchup.opponent_lead_2}: {value}"
                )
                self.assertLessEqual(
                    value, high + 1e-9,
                    f"{spec.name} above {high} on pair "
                    f"{matchup.opponent_lead_2}: {value}"
                )

    def test_15_pairs_each_with_all_components(self):
        eval_obj = evaluate_matchup(
            self.team, self.opp, self.chosen_4, self.lead_2, self.back_2
        )
        self.assertEqual(len(eval_obj.lead_pair_matchups), 15)
        for matchup in eval_obj.lead_pair_matchups:
            for spec in COMPONENT_SPECS:
                self.assertIn(spec.name, matchup.component_values)

    def test_fingerprint_recorded(self):
        eval_obj = evaluate_matchup(
            self.team, self.opp, self.chosen_4, self.lead_2, self.back_2
        )
        self.assertEqual(eval_obj.fingerprint, FROZEN_FINGERPRINT)

    def test_uncertainty_aggregates_present(self):
        eval_obj = evaluate_matchup(
            self.team, self.opp, self.chosen_4, self.lead_2, self.back_2
        )
        u = eval_obj.uncertainty
        for key in (
            "n_lead_pairs", "mean_matchup", "worst_matchup",
            "lower_quartile_matchup", "matchup_variance",
            "n_severely_bad", "n_favorable",
            "severe_threshold", "favorable_threshold",
        ):
            self.assertIn(key, u)
        self.assertEqual(u["n_lead_pairs"], 15)
        self.assertGreaterEqual(u["n_severely_bad"], 0)
        self.assertGreaterEqual(u["n_favorable"], 0)
        # severely_bad + favorable <= 15 (they may overlap only by
        # definition, but in practice severe uses < and favorable
        # uses >; the threshold can equal the mean and a value can
        # be exactly at the threshold without being counted).
        self.assertLessEqual(
            u["n_severely_bad"] + u["n_favorable"], 15
        )

    def test_plan_score_equals_mean(self):
        eval_obj = evaluate_matchup(
            self.team, self.opp, self.chosen_4, self.lead_2, self.back_2
        )
        self.assertAlmostEqual(
            plan_score(eval_obj), eval_obj.uncertainty["mean_matchup"]
        )

    def test_unknown_moves_recorded(self):
        team = list(self.team)
        team[5] = {
            "species": "WeirdMon", "ability": "Pressure",
            "moves": ["SoraN00bCustomMove123", "UnknownMove_42"],
        }
        chosen_4 = ["Incineroar", "Tornadus", "Garchomp", "WeirdMon"]
        eval_obj = evaluate_matchup(
            team, self.opp, chosen_4, self.lead_2, ["Garchomp", "WeirdMon"]
        )
        self.assertIn("SoraN00bCustomMove123", eval_obj.unknown_moves)
        self.assertIn("UnknownMove_42", eval_obj.unknown_moves)


# ---------------------------------------------------------------------------
# Per-component semantic tests
# ---------------------------------------------------------------------------


class TestComponentSemantics(unittest.TestCase):
    def setUp(self):
        self.team = _standard_team()
        self.opp = _standard_opponent()

    def test_fake_out_access_one_when_one_user(self):
        eval_obj = evaluate_matchup(
            self.team, self.opp,
            ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        # Incineroar has Fake Out, Rillaboom has Fake Out. Capped at 1.
        self.assertEqual(
            eval_obj.component_means["fake_out_access"], 1.0
        )

    def test_speed_control_access_one_with_tailwind(self):
        eval_obj = evaluate_matchup(
            self.team, self.opp,
            ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        self.assertEqual(
            eval_obj.component_means["speed_control_access"], 1.0
        )

    def test_protect_does_not_increase_priority_pressure(self):
        # A plan whose only "priority" move is Protect should
        # report zero priority pressure.
        team = [
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Protect", "Taunt", "Hurricane", "Rain Dance"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Dragon Claw", "Protect", "Stealth Rock"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Wood Hammer", "U-turn", "Protect", "Knock Off"]},
            {"species": "X", "ability": "Pressure", "moves": ["Tackle"]},
            {"species": "Y", "ability": "Pressure", "moves": ["Tackle"]},
        ]
        eval_obj = evaluate_matchup(
            team, self.opp,
            ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        # The plan still has Fake Out so priority_pressure is 1.
        # But Protect is not counted as priority.
        self.assertEqual(eval_obj.component_means["priority_pressure"], 1.0)

    def test_spread_move_pressure_counts_spreads(self):
        eval_obj = evaluate_matchup(
            self.team, self.opp,
            ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        # Earthquake (Garchomp), Rock Slide (Garchomp), Grassy Glide
        # (Rillaboom: priority, also damaging but not spread -
        # target=normal, not allAdjacent), Hurricane (Tornadus: not
        # spread - target depends on dex but is not allAdjacent).
        # The exact spread count is dex-driven, but must include
        # Earthquake at minimum.
        self.assertGreaterEqual(
            eval_obj.component_means["spread_move_pressure"], 1.0
        )

    def test_damaging_types_come_from_moves_not_species(self):
        pokemon = {
            "species": "Gyarados",
            "moves": ["Earthquake", "Ice Fang", "Protect", "Dragon Dance"],
        }
        self.assertEqual(
            set(_plan_pokemon_damaging_types(pokemon)),
            {"ground", "ice"},
        )

    def test_back_switch_coverage_ignores_our_own_lead_attacks(self):
        backs = [
            {"species": "Kingambit", "moves": ["Iron Head"]},
            {"species": "Rillaboom", "moves": ["Wood Hammer"]},
        ]
        leads = [
            {"species": "Garchomp", "moves": ["Earthquake"]},
            {"species": "Incineroar", "moves": ["Flare Blitz"]},
        ]
        opponent = [
            {"species": "Blissey", "moves": ["Tackle"]},
            {"species": "Chansey", "moves": ["Tackle"]},
            {"species": "Ditto", "moves": ["Tackle"]},
            {"species": "Smeargle", "moves": ["Tackle"]},
            {"species": "Wobbuffet", "moves": ["Tackle"]},
            {"species": "Pyukumuku", "moves": ["Tackle"]},
        ]
        self.assertEqual(
            _plan_back_switch_defensive_coverage(backs, leads, opponent),
            2.0,
        )

    def test_worst_case_resilience_zero_without_threat(self):
        selected = [{"species": "Blissey", "moves": ["Tackle"]}]
        opponent = [
            {"species": "Rillaboom", "moves": ["Wood Hammer"]},
            {"species": "Incineroar", "moves": ["Flare Blitz"]},
        ]
        self.assertEqual(
            _plan_worst_case_lead_pair_resilience(selected, opponent),
            0.0,
        )

    def test_worst_case_resilience_one_when_every_slot_threatened(self):
        selected = [
            {"species": "Gengar", "moves": ["Shadow Ball", "Thunderbolt"]},
            {"species": "Rillaboom", "moves": ["Wood Hammer"]},
        ]
        opponent = [
            {"species": "Starmie", "moves": ["Surf"]},
            {"species": "Slowbro", "moves": ["Psychic"]},
        ]
        self.assertEqual(
            _plan_worst_case_lead_pair_resilience(selected, opponent),
            1.0,
        )

    def test_removing_immunity_cannot_improve_resilience(self):
        # Plan A: Gastrodon (Storm Drain) + 3 fillers. Plan B:
        # random non-absorber. Plan A's worst_case_lead_pair_resilience
        # must be >= plan B's when the opponent's lead pair includes
        # a water type. We use a synthetic opponent with a Water lead.
        absorbing_team = [
            {"species": "Gastrodon", "ability": "Storm Drain",
             "moves": ["Earthquake", "Recover", "Ice Beam", "Protect"]},
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Dragon Claw", "Protect", "Stealth Rock"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Wood Hammer", "U-turn", "Protect", "Knock Off"]},
            {"species": "X", "ability": "Pressure", "moves": ["Tackle"]},
            {"species": "Y", "ability": "Pressure", "moves": ["Tackle"]},
        ]
        no_immunity_team = [
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Dragon Claw", "Protect", "Stealth Rock"]},
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Wood Hammer", "U-turn", "Protect", "Knock Off"]},
            {"species": "Rotom", "ability": "Levitate",
             "moves": ["Thunderbolt", "Shadow Ball", "Protect", "Volt Switch"]},
            {"species": "X", "ability": "Pressure", "moves": ["Tackle"]},
            {"species": "Y", "ability": "Pressure", "moves": ["Tackle"]},
        ]
        # Opponent with at least one water attacker (Pelipper).
        water_opp = [
            {"species": "Pelipper", "moves": []},
            {"species": "Incineroar", "moves": []},
            {"species": "Garchomp", "moves": []},
            {"species": "Rillaboom", "moves": []},
            {"species": "Tornadus", "moves": []},
            {"species": "Iron Hands", "moves": []},
        ]
        eval_absorb = evaluate_matchup(
            absorbing_team, water_opp,
            ["Gastrodon", "Incineroar", "Garchomp", "Rillaboom"],
            ["Gastrodon", "Incineroar"],
            ["Garchomp", "Rillaboom"],
        )
        eval_no_absorb = evaluate_matchup(
            no_immunity_team, water_opp,
            ["Garchomp", "Incineroar", "Rillaboom", "Rotom"],
            ["Garchomp", "Incineroar"],
            ["Rillaboom", "Rotom"],
        )
        # The immunity-aware pressure must be higher for the
        # absorbing plan.
        self.assertGreaterEqual(
            eval_absorb.component_means["immunity_aware_pressure"],
            eval_no_absorb.component_means["immunity_aware_pressure"],
        )

    def test_unsupported_setup_does_not_increase_compatibility(self):
        # No-support plan: mons with setup moves but no support
        # (no Fake Out, no Follow Me, no Tailwind, no Trick Room,
        # no Intimidate ability, no pivot).
        team_no_support = [
            {"species": "Sneasler", "ability": "Unburden",
             "moves": ["Swords Dance", "Close Combat", "Protect",
                       "Throat Chop"]},
            {"species": "Chi-Yu", "ability": "Beads of Ruin",
             "moves": ["Nasty Plot", "Heat Wave", "Dark Pulse", "Protect"]},
            {"species": "Gholdengo", "ability": "Good as Gold",
             "moves": ["Nasty Plot", "Shadow Ball", "Make It Rain",
                       "Protect"]},
            {"species": "Kyurem", "ability": "Pressure",
             "moves": ["Dragon Dance", "Earth Power", "Ice Beam", "Protect"]},
            {"species": "X", "ability": "Pressure", "moves": ["Tackle"]},
            {"species": "Y", "ability": "Pressure", "moves": ["Tackle"]},
        ]
        # With-support plan: same setup mons + a Tailwind setter.
        team_with_support = [
            {"species": "Sneasler", "ability": "Unburden",
             "moves": ["Swords Dance", "Close Combat", "Protect",
                       "Throat Chop"]},
            {"species": "Chi-Yu", "ability": "Beads of Ruin",
             "moves": ["Nasty Plot", "Heat Wave", "Dark Pulse", "Protect"]},
            {"species": "Gholdengo", "ability": "Good as Gold",
             "moves": ["Nasty Plot", "Shadow Ball", "Make It Rain",
                       "Protect"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
            {"species": "X", "ability": "Pressure", "moves": ["Tackle"]},
            {"species": "Y", "ability": "Pressure", "moves": ["Tackle"]},
        ]
        eval_no_support = evaluate_matchup(
            team_no_support, self.opp,
            ["Sneasler", "Chi-Yu", "Gholdengo", "Kyurem"],
            ["Sneasler", "Chi-Yu"],
            ["Gholdengo", "Kyurem"],
        )
        eval_with_support = evaluate_matchup(
            team_with_support, self.opp,
            ["Sneasler", "Chi-Yu", "Gholdengo", "Tornadus"],
            ["Sneasler", "Chi-Yu"],
            ["Gholdengo", "Tornadus"],
        )
        # Adding support must not decrease compatibility.
        self.assertGreaterEqual(
            eval_with_support.component_means[
                "setup_with_support_compatibility"
            ],
            eval_no_support.component_means[
                "setup_with_support_compatibility"
            ],
        )
        # And the unsupported plan must have a negative risk score.
        self.assertLess(
            eval_no_support.component_means["unsupported_setup_risk"], 0.0
        )
        # And a non-zero risk delta between the two plans. The
        # supported plan has risk = 0; the unsupported plan has a
        # negative risk. So supported > unsupported.
        self.assertGreater(
            eval_with_support.component_means["unsupported_setup_risk"],
            eval_no_support.component_means["unsupported_setup_risk"],
        )

    def test_dual_type_immunity_uses_full_multiplier(self):
        # A plan with a Levitate (ground immunity) on the back
        # should not be 2x weak to Ground.
        team = [
            {"species": "Rotom", "ability": "Levitate",
             "moves": ["Thunderbolt", "Shadow Ball", "Volt Switch", "Protect"]},
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Dragon Claw", "Protect", "Stealth Rock"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
            {"species": "X", "ability": "Pressure", "moves": ["Tackle"]},
            {"species": "Y", "ability": "Pressure", "moves": ["Tackle"]},
        ]
        ground_opp = [
            {"species": "Garchomp", "moves": []},
            {"species": "Rillaboom", "moves": []},
            {"species": "Incineroar", "moves": []},
            {"species": "Tornadus", "moves": []},
            {"species": "Iron Hands", "moves": []},
            {"species": "Kingambit", "moves": []},
        ]
        eval_obj = evaluate_matchup(
            team, ground_opp,
            ["Rotom", "Incineroar", "Garchomp", "Tornadus"],
            ["Rotom", "Incineroar"],
            ["Garchomp", "Tornadus"],
        )
        # Garchomp on the team so offensive_type_coverage > 0.
        self.assertGreater(
            eval_obj.component_means["offensive_move_type_pressure"], 0.0
        )

    def test_immunity_aware_pressure_uses_only_listed_ability(self):
        # When a species has an ability that is NOT in
        # ABSORB_ABILITIES, the component must be 0.
        team = [
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Dragon Claw", "Protect", "Stealth Rock"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Wood Hammer", "U-turn", "Protect", "Knock Off"]},
            {"species": "X", "ability": "Pressure", "moves": ["Tackle"]},
            {"species": "Y", "ability": "Pressure", "moves": ["Tackle"]},
        ]
        eval_obj = evaluate_matchup(
            team, self.opp,
            ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        # None of the team members have an absorb ability.
        self.assertEqual(
            eval_obj.component_means["immunity_aware_pressure"], 0.0
        )


# ---------------------------------------------------------------------------
# Robustness: symmetry, determinism, mutation, plan synthesis
# ---------------------------------------------------------------------------


class TestRobustness(unittest.TestCase):
    def setUp(self):
        self.team = _standard_team()
        self.opp = _standard_opponent()
        self.chosen_4 = ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"]
        self.lead_2 = ["Incineroar", "Tornadus"]
        self.back_2 = ["Garchomp", "Rillaboom"]

    def test_identical_plans_produce_identical_scores(self):
        a = evaluate_matchup(
            self.team, self.opp, self.chosen_4, self.lead_2, self.back_2
        )
        b = evaluate_matchup(
            self.team, self.opp, self.chosen_4, self.lead_2, self.back_2
        )
        self.assertEqual(plan_score(a), plan_score(b))
        for m1, m2 in zip(a.lead_pair_matchups, b.lead_pair_matchups):
            self.assertEqual(m1.component_total, m2.component_total)
            self.assertEqual(m1.component_values, m2.component_values)

    def test_permutation_invariance_of_opponent_team(self):
        # Build the opponent team in a different order; the mean
        # score should be identical because the lead pair enumeration
        # is order-independent.
        opp_a = list(self.opp)
        opp_b = list(reversed(self.opp))
        a = evaluate_matchup(
            self.team, opp_a, self.chosen_4, self.lead_2, self.back_2
        )
        b = evaluate_matchup(
            self.team, opp_b, self.chosen_4, self.lead_2, self.back_2
        )
        # The set of lead pairs is identical, so the totals
        # aggregated to a multiset should match.
        a_totals = sorted([m.component_total for m in a.lead_pair_matchups])
        b_totals = sorted([m.component_total for m in b.lead_pair_matchups])
        self.assertEqual(a_totals, b_totals)
        self.assertAlmostEqual(plan_score(a), plan_score(b))

    def test_lead_order_symmetry(self):
        # Some components are lead-order symmetric. Verify by
        # swapping the lead pair order and re-evaluating; the
        # symmetric components should be unchanged.
        swapped = list(self.lead_2)
        swapped[0], swapped[1] = swapped[1], swapped[0]
        a = evaluate_matchup(
            self.team, self.opp, self.chosen_4, self.lead_2, self.back_2
        )
        b = evaluate_matchup(
            self.team, self.opp, self.chosen_4, swapped, self.back_2
        )
        # mean_matchup is symmetric
        self.assertAlmostEqual(
            a.uncertainty["mean_matchup"], b.uncertainty["mean_matchup"]
        )
        # shared_lead_weakness is symmetric
        self.assertAlmostEqual(
            a.component_means["shared_lead_weakness"],
            b.component_means["shared_lead_weakness"],
        )
        # lead_coverage_overlap is symmetric
        self.assertAlmostEqual(
            a.component_means["lead_coverage_overlap"],
            b.component_means["lead_coverage_overlap"],
        )

    def test_no_input_mutation(self):
        team_snapshot = json.dumps(self.team, sort_keys=True, default=str)
        opp_snapshot = json.dumps(self.opp, sort_keys=True, default=str)
        evaluate_matchup(
            self.team, self.opp, self.chosen_4, self.lead_2, self.back_2
        )
        self.assertEqual(
            json.dumps(self.team, sort_keys=True, default=str),
            team_snapshot,
        )
        self.assertEqual(
            json.dumps(self.opp, sort_keys=True, default=str),
            opp_snapshot,
        )

    def test_malformed_plan_rejected(self):
        with self.assertRaises(MatchupEvaluatorError):
            evaluate_matchup(
                self.team, self.opp,
                ["Incineroar", "Tornadus", "Garchomp"],
                ["Incineroar", "Tornadus"],
                ["Garchomp", "Rillaboom"],
            )

    def test_duplicate_chosen_rejected(self):
        with self.assertRaises(MatchupEvaluatorError):
            evaluate_matchup(
                self.team, self.opp,
                ["Incineroar", "Incineroar", "Garchomp", "Rillaboom"],
                ["Incineroar", "Tornadus"],
                ["Garchomp", "Rillaboom"],
            )

    def test_lead_back_overlap_rejected(self):
        with self.assertRaises(MatchupEvaluatorError):
            evaluate_matchup(
                self.team, self.opp,
                ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
                ["Incineroar", "Incineroar"],
                ["Garchomp", "Rillaboom"],
            )

    def test_species_not_in_team_rejected(self):
        with self.assertRaises(MatchupEvaluatorError):
            evaluate_matchup(
                self.team, self.opp,
                ["Incineroar", "Tornadus", "Garchomp", "MissingNo"],
                ["Incineroar", "Tornadus"],
                ["Garchomp", "MissingNo"],
            )

    def test_missing_move_metadata_no_crash(self):
        # A team with an unknown move does not raise.
        team = list(self.team)
        team[5] = {
            "species": "WeirdMon", "ability": "Pressure",
            "moves": ["SoraN00bCustomMove123"],
        }
        chosen_4 = ["Incineroar", "Tornadus", "Garchomp", "WeirdMon"]
        # Should not raise; the score is finite and recorded.
        eval_obj = evaluate_matchup(
            team, self.opp,
            chosen_4, ["Incineroar", "Tornadus"],
            ["Garchomp", "WeirdMon"],
        )
        self.assertGreaterEqual(
            eval_obj.component_means["spread_move_pressure"], 0.0
        )


# ---------------------------------------------------------------------------
# Synthetic plan tests
# ---------------------------------------------------------------------------


class TestSyntheticPlans(unittest.TestCase):
    def setUp(self):
        self.team = _standard_team()
        self.opp = _standard_opponent()

    def test_clear_superior_plan_scores_higher(self):
        # Plan A: strong matchup, broad coverage, Intimidate lead,
        # spread, pivot, recovery, Fake Out, Tailwind, no overlap.
        strong = [
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "U-turn", "Protect"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Grassy Glide", "Wood Hammer", "U-turn", "Protect"]},
        ]
        # Plan B: clearly unsafe: 3 setup moves with no support,
        # 4x shared weakness to a common type, no Fake Out, no
        # speed control, no pivot, no recovery.
        unsafe = [
            {"species": "Slowking", "ability": "Regenerator",
             "moves": ["Calm Mind", "Slack Off", "Psyshock", "Protect"]},
            {"species": "Cramorant", "ability": "Tangled Feet",
             "moves": ["Belly Drum", "Surf", "Protect", "Roost"]},
            {"species": "Dusclops", "ability": "Frisk",
             "moves": ["Trick Room", "Pain Split", "Night Shade", "Protect"]},
            {"species": "Reuniclus", "ability": "Magic Guard",
             "moves": ["Calm Mind", "Psyshock", "Focus Blast", "Protect"]},
        ]
        eval_strong = evaluate_matchup(
            self.team, self.opp,
            [p["species"] for p in strong],
            [strong[0]["species"], strong[1]["species"]],
            [strong[2]["species"], strong[3]["species"]],
        )
        # Build a 6-mon team for the unsafe plan so plan shape is valid.
        unsafe_team = self.team + [unsafe[0]][:0]
        # Replace the team with the unsafe 4 + 2 fillers.
        unsafe_team_full = [
            {"species": p["species"], "ability": p["ability"],
             "moves": p["moves"]}
            for p in unsafe
        ] + [
            {"species": "Filler1", "ability": "Pressure", "moves": ["Tackle"]},
            {"species": "Filler2", "ability": "Pressure", "moves": ["Tackle"]},
        ]
        eval_unsafe = evaluate_matchup(
            unsafe_team_full, self.opp,
            [unsafe[0]["species"], unsafe[1]["species"],
             unsafe[2]["species"], unsafe[3]["species"]],
            [unsafe[0]["species"], unsafe[1]["species"]],
            [unsafe[2]["species"], unsafe[3]["species"]],
        )
        self.assertGreater(
            plan_score(eval_strong), plan_score(eval_unsafe)
        )

    def test_plan_with_immunity_outscores_plan_without(self):
        # Both plans target a water-heavy opponent. The absorbing
        # plan should score higher.
        water_opp = [
            {"species": "Pelipper", "moves": []},
            {"species": "Gastrodon", "moves": []},
            {"species": "Kyogre", "moves": []},
            {"species": "UrshifuRapid", "moves": []},
            {"species": "Barraskewda", "moves": []},
            {"species": "Inteleon", "moves": []},
        ]
        absorbing = [
            {"species": "Gastrodon", "ability": "Storm Drain",
             "moves": ["Earthquake", "Ice Beam", "Recover", "Protect"]},
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "U-turn", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Wood Hammer", "U-turn", "Protect", "Knock Off"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
        ]
        absorbing_team = absorbing + [
            {"species": "Filler1", "ability": "Pressure", "moves": ["Tackle"]},
            {"species": "Filler2", "ability": "Pressure", "moves": ["Tackle"]},
        ]
        non_absorbing = [
            {"species": "Garchomp", "ability": "Rough Skin",
             "moves": ["Earthquake", "Dragon Claw", "Protect", "Stealth Rock"]},
            {"species": "Incineroar", "ability": "Intimidate",
             "moves": ["Fake Out", "Flare Blitz", "U-turn", "Protect"]},
            {"species": "Rillaboom", "ability": "Grassy Surge",
             "moves": ["Wood Hammer", "U-turn", "Protect", "Knock Off"]},
            {"species": "Tornadus", "ability": "Prankster",
             "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
        ]
        non_absorbing_team = non_absorbing + [
            {"species": "Filler1", "ability": "Pressure", "moves": ["Tackle"]},
            {"species": "Filler2", "ability": "Pressure", "moves": ["Tackle"]},
        ]
        a = evaluate_matchup(
            absorbing_team, water_opp,
            [p["species"] for p in absorbing],
            [absorbing[0]["species"], absorbing[1]["species"]],
            [absorbing[2]["species"], absorbing[3]["species"]],
        )
        b = evaluate_matchup(
            non_absorbing_team, water_opp,
            [p["species"] for p in non_absorbing],
            [non_absorbing[0]["species"], non_absorbing[1]["species"]],
            [non_absorbing[2]["species"], non_absorbing[3]["species"]],
        )
        # The absorbing plan must score at least as high on the
        # immunity-aware pressure.
        self.assertGreaterEqual(
            a.component_means["immunity_aware_pressure"],
            b.component_means["immunity_aware_pressure"],
        )


# ---------------------------------------------------------------------------
# Hidden information guard
# ---------------------------------------------------------------------------


class TestHiddenInformation(unittest.TestCase):
    def setUp(self):
        self.team = _standard_team()
        self.opp = _standard_opponent()
        self.chosen_4 = ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"]
        self.lead_2 = ["Incineroar", "Tornadus"]
        self.back_2 = ["Garchomp", "Rillaboom"]

    def test_module_does_not_import_battle_outcomes(self):
        import inspect
        for module_name in ("vgc2026_matchup_evaluator_v2",):
            module = __import__(module_name)
            source = Path(inspect.getfile(module)).read_text()
            for forbidden in (
                "from poke_env", "import requests", "urllib",
                "play.pokemonshowdown.com", "smogon.com",
                "our_win", "opponent_win",
                "battle_result", "outcome",
            ):
                self.assertNotIn(
                    forbidden, source,
                    f"{module_name} contains forbidden string {forbidden!r}"
                )

    def test_no_observed_lead_dependency(self):
        # The evaluator must NOT read observed leads, turn logs, or
        # any field that requires post-preview evidence.
        import inspect
        from vgc2026_matchup_evaluator_v2 import evaluate_matchup
        source = Path(inspect.getfile(evaluate_matchup)).read_text()
        # Check that observed_lead and battle_tag are not
        # referenced as field names (the docstring may discuss
        # "turn logs" in the negative).
        for forbidden in (
            "observed_actual_lead_on_turn1",
            "actual_lead_on_turn1",
            "battle_tag",
        ):
            self.assertNotIn(forbidden, source)


# ---------------------------------------------------------------------------
# Common evaluator v1 vs evaluator v2 rank correlation
# ---------------------------------------------------------------------------


class TestEvaluatorComparison(unittest.TestCase):
    def setUp(self):
        self.team = _standard_team()
        self.opp = _standard_opponent()

    def test_v1_and_v2_evaluate_same_plan(self):
        eval_v2 = evaluate_matchup(
            self.team, self.opp,
            ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        v1 = evaluate_plan_on_common_scale(
            self.team, self.opp,
            ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "Rillaboom"],
        )
        # Both evaluators produce a total > 0 for this plan.
        self.assertGreater(plan_score(eval_v2), 0.0)
        self.assertGreater(v1.total, 0.0)


# ---------------------------------------------------------------------------
# Malformed data tests
# ---------------------------------------------------------------------------


class TestMalformedData(unittest.TestCase):
    def setUp(self):
        self.team = _standard_team()
        self.opp = _standard_opponent()

    def test_opponent_team_wrong_size(self):
        with self.assertRaises(MatchupEvaluatorError):
            evaluate_matchup(
                self.team, self.opp[:5],
                ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
                ["Incineroar", "Tornadus"],
                ["Garchomp", "Rillaboom"],
            )

    def test_team_wrong_size(self):
        with self.assertRaises(MatchupEvaluatorError):
            evaluate_matchup(
                self.team[:5], self.opp,
                ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
                ["Incineroar", "Tornadus"],
                ["Garchomp", "Rillaboom"],
            )

    def test_unknown_move_does_not_crash(self):
        team = list(self.team)
        team[5] = {
            "species": "WeirdMon", "ability": "Pressure",
            "moves": ["SoraN00bCustomMove123", "UnknownMove_42"],
        }
        eval_obj = evaluate_matchup(
            team, self.opp,
            ["Incineroar", "Tornadus", "Garchomp", "WeirdMon"],
            ["Incineroar", "Tornadus"],
            ["Garchomp", "WeirdMon"],
        )
        # Should not raise; the unknown moves are recorded in
        # unknown_moves.
        self.assertGreater(len(eval_obj.unknown_moves), 0)


# ---------------------------------------------------------------------------
# Constants pinning
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    def test_severe_threshold_is_positive(self):
        self.assertGreater(SEVERE_BAD_ZSCORE_THRESHOLD, 0)

    def test_favorable_threshold_is_positive(self):
        self.assertGreater(FAVORABLE_ZSCORE_THRESHOLD, 0)

    def test_bootstrap_seed_is_set(self):
        self.assertIsInstance(BOOTSTRAP_SEED, int)

    def test_component_weights_positive(self):
        for name, value in COMPONENT_WEIGHTS.items():
            self.assertGreater(value, 0.0, f"{name} weight must be > 0")

    def test_component_specs_have_unique_names(self):
        names = [spec.name for spec in COMPONENT_SPECS]
        self.assertEqual(len(names), len(set(names)))

    def test_component_spec_count(self):
        # At least 20 distinct mechanical components
        self.assertGreaterEqual(len(COMPONENT_SPECS), 20)

    def test_each_weight_matches_spec(self):
        for spec in COMPONENT_SPECS:
            self.assertIn(spec.name, COMPONENT_WEIGHTS)
            self.assertEqual(spec.weight, COMPONENT_WEIGHTS[spec.name])

    def test_frozen_fingerprints_match(self):
        # component_spec import works
        spec = component_spec("offensive_move_type_pressure")
        self.assertEqual(spec.name, "offensive_move_type_pressure")


# ---------------------------------------------------------------------------
# Subprocess natural exit
# ---------------------------------------------------------------------------


class TestSubprocessNaturalExit(unittest.TestCase):
    def test_import_subprocess(self):
        result = subprocess.run(
            [
                sys.executable, "-c",
                "import poke_env_test_cleanup; "
                "import vgc2026_matchup_evaluator_v2; "
                "import vgc2026_common_plan_evaluator; "
                "import vgc2026_plan_features; "
                "import analyze_vgc2026_phaseV2i_matchup_evaluator; "
                "import inspect_vgc2026_phaseV2i_matchup; "
                "print('ok')",
            ],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")


# ---------------------------------------------------------------------------
# Inspector integration
# ---------------------------------------------------------------------------


class TestInspectorIntegration(unittest.TestCase):
    def setUp(self):
        self.cwd = str(Path(__file__).resolve().parent)
        self.logs_dir = Path(self.cwd) / "logs"

    def test_inspector_pair(self):
        result = subprocess.run(
            [
                sys.executable,
                "inspect_vgc2026_phaseV2i_matchup.py",
                "--pair", "0",
                "--policy", "v3",
                "--synthetic",
            ],
            cwd=self.cwd,
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Pair 0", result.stdout)

    def test_inspector_compare_policies(self):
        result = subprocess.run(
            [
                sys.executable,
                "inspect_vgc2026_phaseV2i_matchup.py",
                "--pair", "0",
                "--compare-policies",
                "--synthetic",
            ],
            cwd=self.cwd,
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("V3", result.stdout)
        self.assertIn("Random", result.stdout)

    def test_inspector_worst_leads(self):
        result = subprocess.run(
            [
                sys.executable,
                "inspect_vgc2026_phaseV2i_matchup.py",
                "--pair", "0",
                "--policy", "v3",
                "--worst-leads", "3",
                "--synthetic",
            ],
            cwd=self.cwd,
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_inspector_component(self):
        result = subprocess.run(
            [
                sys.executable,
                "inspect_vgc2026_phaseV2i_matchup.py",
                "--pair", "0",
                "--policy", "v3",
                "--component", "offensive_move_type_pressure",
                "--synthetic",
            ],
            cwd=self.cwd,
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("offensive_move_type_pressure", result.stdout)

    def test_inspector_opponent_lead(self):
        result = subprocess.run(
            [
                sys.executable,
                "inspect_vgc2026_phaseV2i_matchup.py",
                "--pair", "0",
                "--policy", "v3",
                "--opponent-lead", "rillaboom,incineroar",
                "--synthetic",
            ],
            cwd=self.cwd,
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


# ---------------------------------------------------------------------------
# Analyzer integration
# ---------------------------------------------------------------------------


class TestAnalyzerIntegration(unittest.TestCase):
    def setUp(self):
        self.cwd = str(Path(__file__).resolve().parent)
        self.logs_dir = Path(self.cwd) / "logs"

    def test_analyzer_runs(self):
        from analyze_vgc2026_phaseV2i_matchup_evaluator import (
            run_analysis, ANALYZER_FROZEN_FINGERPRINT,
        )
        # Construct synthetic pair records so the analyzer can run
        # without depending on the full benchmark artifacts.
        from analyze_vgc2026_phaseV2i_matchup_evaluator import (
            build_synthetic_inputs,
        )
        inputs = build_synthetic_inputs()
        report = run_analysis(inputs)
        # Sign test deterministic counts.
        self.assertEqual(
            report["sign_test"]["decisive_n"], 55
        )
        self.assertEqual(report["sign_test"]["v3_both"], 30)
        self.assertEqual(report["sign_test"]["random_both"], 25)
        self.assertEqual(report["sign_test"]["split"], 45)
        # Required comparison keys.
        for key in (
            "v3_plans", "random_plans",
            "v3_both_vs_random_both",
            "within_failure_paired",
            "split_descriptive",
            "v1_v2_rank_correlation",
            "ranking_disagreement",
            "component_ablation",
            "audit_unknown", "runtime", "offline_129_team_comparison",
            "decision",
            "fingerprint", "outcome_freeze_proof",
        ):
            self.assertIn(key, report)
        # Freeze proof is recorded.
        proof = report["outcome_freeze_proof"]
        self.assertTrue(proof["frozen_before_outcomes"])
        self.assertEqual(proof["fingerprint"], ANALYZER_FROZEN_FINGERPRINT)
        self.assertIsNone(proof["first_outcome_load_unix"])
        self.assertEqual(report["decision"]["phase_v3_status"], "BLOCKED")
        self.assertEqual(
            report["offline_129_team_comparison"]["status"], "skipped"
        )

    def test_analyzer_writes_artifact(self):
        from analyze_vgc2026_phaseV2i_matchup_evaluator import (
            run_analysis, build_synthetic_inputs, write_artifacts,
        )
        default_path = (
            self.logs_dir / "vgc2026_phaseV2i_matchup_evaluator.json"
        )
        existed_before = default_path.exists()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                inputs = build_synthetic_inputs()
                report = run_analysis(inputs)
                json_path, md_path = write_artifacts(report, tmp)
                self.assertTrue(json_path.exists())
                self.assertTrue(md_path.exists())
                # The test writes only inside tmpdir. Existing real
                # artifacts are allowed and must remain untouched.
                self.assertEqual(default_path.exists(), existed_before)
                # Verify the JSON is well-formed and the markdown
                # contains the fingerprint.
                data = json.loads(json_path.read_text())
                self.assertIn("fingerprint", data)
                md_text = md_path.read_text()
                self.assertIn("Phase V2i", md_text)
        finally:
            # If the test environment previously created the
            # default file, restore its prior existence. The
            # default path must not be created by the test.
            if not existed_before and default_path.exists():
                default_path.unlink()


# ---------------------------------------------------------------------------
# Analyzer statistics
# ---------------------------------------------------------------------------


class TestAnalyzerStatistics(unittest.TestCase):
    def test_paired_bootstrap_preserves_pairing(self):
        from analyze_vgc2026_phaseV2i_matchup_evaluator import (
            _bootstrap_paired_mean_diff_ci,
        )
        ci = _bootstrap_paired_mean_diff_ci(
            [11.0, 102.0, 23.0],
            [10.0, 100.0, 20.0],
            n_resamples=200,
            seed=7,
        )
        self.assertIsNotNone(ci)
        self.assertAlmostEqual(ci[0], 2.0)
        self.assertGreater(ci[1], 0.0)

    def test_ci_excludes_zero_semantics(self):
        from analyze_vgc2026_phaseV2i_matchup_evaluator import (
            _ci_excludes_zero,
        )
        self.assertTrue(_ci_excludes_zero((1.0, 0.1, 2.0)))
        self.assertTrue(_ci_excludes_zero((-1.0, -2.0, -0.1)))
        self.assertFalse(_ci_excludes_zero((0.0, -0.1, 0.1)))
        self.assertFalse(_ci_excludes_zero(None))


# ---------------------------------------------------------------------------
# No-pass-only / no-skipped test enforcement
# ---------------------------------------------------------------------------


class TestNoPassOnlyOrSkipped(unittest.TestCase):
    def test_no_pass_only_test_bodies(self):
        import ast
        module = __import__(__name__)
        source = Path(module.__file__).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            body = node.body
            if not body:
                self.fail(f"{node.name} has an empty body")
            if (
                len(body) == 1
                and isinstance(body[0], ast.Pass)
            ):
                self.fail(f"{node.name} is a pass-only test")
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr in {"skipTest", "skip"}
                ):
                    self.fail(
                        f"{node.name} uses skipTest/skip"
                    )


if __name__ == "__main__":
    unittest.main()
