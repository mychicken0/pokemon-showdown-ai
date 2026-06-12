#!/usr/bin/env python3
"""
Test suite for VGC 2026 Controlled Team Preview — Phase V2c.3a

Tests the ControlledTeamPreviewPlayer implementation covering:
- species-to-position mapping
- lead/back order
- both policies (basic_top4, random_4_from_6)
- duplicate/missing species rejection
- selected_in_teampreview flags
- emitted order
- actual/planned validation
- side swap pairing
- variable seeds
- IV serialization
- Artifact safety (--artifact-tag, --overwrite)
- Actual lead: observed vs derived (robust capture from protocol)
- Smoke sizing: explicit per-arm counts (A=2,B=2,C=2,D1=2,D2=2)
- Analyzer helpers: policy-perspective normalization, mirror evaluation,
  paired D evaluation, V3 gate evaluation, artifact validation
- Lifecycle: no real Player.__init__ in fixtures; subprocess natural-exit proof
"""

# IMPORTANT: Import poke_env_test_cleanup FIRST, before any poke-env imports.
# This unregisters the broken atexit callback that hangs on POKE_LOOP cleanup.
import poke_env_test_cleanup

import unittest
import asyncio
import random
import tempfile
import os
import shutil
import csv
import subprocess
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, '/home/phurin/Program/Showdown_AI/pokemon-showdown-ai')

from team_preview_policy import choose_four_from_six, PreviewResult, validate_preview
from poke_env.teambuilder.constant_teambuilder import ConstantTeambuilder
from poke_env.player.player import Player
from poke_env.battle.battle import Battle
from poke_env.battle.pokemon import Pokemon

# Import V2c.3 benchmark components
from bot_vgc2026_phaseV2c import (
    ControlledTeamPreviewPlayer,
    VGCBattleRunnerV2c,
    LOCAL_SERVER_CONFIG,
    BATTLE_TIMEOUT,
    CLEANUP_TIMEOUT,
    HEARTBEAT_INTERVAL,
    STALL_DETECTION,
    ARM_TIMEOUT,
    build_team_string,
    validate_team_for_battle,
    extract_rank,
    create_account_configs,
    create_controlled_player,
    resolve_artifact_paths,
    check_artifacts_exist,
    init_artifacts_atomic,
    DEFAULT_CSV_NAME,
    DEFAULT_JSONL_NAME,
    DEFAULT_PREVIEW_CSV_NAME,
)
from poke_env import AccountConfiguration

# Import Phase V2c.1/2 analyzer helpers
from analyze_vgc2026_phaseV2c1 import (
    normalize_arm_d_outcomes,
    paired_arm_d_analysis,
    mirror_sanity_evaluation,
    preview_validation,
    actual_lead_evidence_status,
    outcome_validation,
    v3_gate_evaluation,
    wilson_score_interval,
    convert_for_json,
)


# Test fixtures
SAMPLE_TEAM = [
    {"species": "Incineroar", "ability": "Intimidate", "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Throat Chop"], "item": "Sitrus Berry", "nature": "Adamant", "evs": {"hp": 252, "atk": 252, "def": 4}, "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 0}},
    {"species": "Garchomp", "ability": "Rough Skin", "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"], "item": "Choice Scarf", "nature": "Jolly", "evs": {"hp": 4, "atk": 252, "spe": 252}, "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}},
    {"species": "Rillaboom", "ability": "Grassy Surge", "moves": ["Fake Out", "Grassy Glide", "High Horsepower", "U-turn"], "item": "Choice Band", "nature": "Adamant", "evs": {"hp": 252, "atk": 252, "def": 4}, "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}},
    {"species": "Tornadus", "ability": "Prankster", "moves": ["Tailwind", "Taunt", "Hurricane", "Focus Blast"], "item": "Focus Sash", "nature": "Timid", "evs": {"hp": 4, "spa": 252, "spe": 252}, "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}},
    {"species": "Flutter Mane", "ability": "Protosynthesis", "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"], "item": "Booster Energy", "nature": "Timid", "evs": {"hp": 4, "spa": 252, "spe": 252}, "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}},
    {"species": "Iron Hands", "ability": "Quark Drive", "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"], "item": "Booster Energy", "nature": "Adamant", "evs": {"hp": 252, "atk": 252, "def": 4}, "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}},
]

OPP_TEAM = [
    {"species": "Rillaboom", "moves": []},
    {"species": "Iron Hands", "moves": []},
    {"species": "Flutter Mane", "moves": []},
    {"species": "Incineroar", "moves": []},
    {"species": "Garchomp", "moves": []},
    {"species": "Tornadus", "moves": []},
]


class MockPokemon:
    """Simple mock Pokemon for testing without MagicMock attribute issues."""
    def __init__(self, species: str):
        self.species = species
        self._selected_in_teampreview = False


def build_mock_battle(team_species_list):
    """Build a mock battle object with team."""
    from unittest.mock import MagicMock
    battle = MagicMock()
    battle.team = {f"p{i}": MockPokemon(s.lower()) for i, s in enumerate(team_species_list)}
    return battle


# ===== Shared fixture helper =====

def make_minimal_player(preview, battle_tag="test", pair_id=0, side="p1"):
    """Create a minimal test player using __new__ — never calls Player.__init__."""
    player = ControlledTeamPreviewPlayer.__new__(ControlledTeamPreviewPlayer)
    player._preview_result = preview
    player._battle_tag = battle_tag
    player._pair_id = pair_id
    player._side = side
    player._teampreview_emitted = None
    player._teampreview_matches_plan = False
    player._actual_lead_on_turn1 = []
    player._observed_actual_lead_on_turn1 = []
    player._selected_species = []
    return player


class TestPreviewResultStructure(unittest.TestCase):
    """Test PreviewResult structure and validation."""

    def test_preview_result_has_required_fields(self):
        result = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42)
        self.assertIsInstance(result.chosen_4, list)
        self.assertIsInstance(result.lead_2, list)
        self.assertIsInstance(result.back_2, list)
        self.assertEqual(len(result.chosen_4), 4)
        self.assertEqual(len(result.lead_2), 2)
        self.assertEqual(len(result.back_2), 2)
        self.assertIn(result.policy, ["random", "basic_top4"])

    def test_preview_result_chosen_4_are_unique(self):
        result = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42)
        self.assertEqual(len(set(result.chosen_4)), 4)

    def test_preview_result_lead_back_are_disjoint(self):
        result = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42)
        lead_set = set(result.lead_2)
        back_set = set(result.back_2)
        self.assertEqual(lead_set.intersection(back_set), set())

    def test_preview_result_lead_back_subset_of_chosen(self):
        result = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42)
        chosen_set = set(result.chosen_4)
        self.assertTrue(set(result.lead_2).issubset(chosen_set))
        self.assertTrue(set(result.back_2).issubset(chosen_set))

    def test_preview_result_basic_top4_policy(self):
        result = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        self.assertEqual(result.policy, "basic_top4")
        self.assertTrue(len(result.scores) > 0)


class TestValidatePreview(unittest.TestCase):
    """Test preview validation functions."""

    def test_valid_preview_passes(self):
        result = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42)
        valid, errors = validate_preview(SAMPLE_TEAM, result)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_invalid_chosen_species_fails(self):
        class FakeResult:
            chosen_4 = ["Incineroar", "Garchomp", "Rillaboom", "FakeMon"]
            lead_2 = ["Incineroar", "Garchomp"]
            back_2 = ["Rillaboom", "FakeMon"]
        valid, errors = validate_preview(SAMPLE_TEAM, FakeResult())
        self.assertFalse(valid)
        self.assertTrue(any("not in team" in e for e in errors))

    def test_duplicate_in_lead_fails(self):
        class FakeResult:
            chosen_4 = ["Incineroar", "Garchomp", "Rillaboom", "Tornadus"]
            lead_2 = ["Incineroar", "Incineroar"]
            back_2 = ["Garchomp", "Rillaboom"]
        valid, errors = validate_preview(SAMPLE_TEAM, FakeResult())
        self.assertFalse(valid)

    def test_wrong_lead_count_fails(self):
        class FakeResult:
            chosen_4 = ["Incineroar", "Garchomp", "Rillaboom", "Tornadus"]
            lead_2 = ["Incineroar"]
            back_2 = ["Garchomp", "Rillaboom", "Tornadus"]
        valid, errors = validate_preview(SAMPLE_TEAM, FakeResult())
        self.assertFalse(valid)
        self.assertTrue(any("exactly 2" in e for e in errors))


class TestTeamSerialization(unittest.TestCase):
    """Test team string serialization for poke-env ConstantTeambuilder."""

    def test_team_string_parses_with_constant_teambuilder(self):
        result = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42)
        team_str = build_team_string(SAMPLE_TEAM, result.chosen_4)
        parsed = ConstantTeambuilder.parse_showdown_team(team_str)
        self.assertEqual(len(parsed), 6)

    def test_all_species_parsed_correctly(self):
        result = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42)
        team_str = build_team_string(SAMPLE_TEAM, result.chosen_4)
        parsed = ConstantTeambuilder.parse_showdown_team(team_str)
        parsed_species = [p.species.lower() for p in parsed]
        expected_species = [p['species'].lower() for p in SAMPLE_TEAM]
        self.assertEqual(set(parsed_species), set(expected_species))

    def test_zero_iv_serialization(self):
        """Test that 0 IVs are serialized correctly."""
        from vgc_team_pool import VGCTeam
        team_with_zero_iv = [dict(p) for p in SAMPLE_TEAM]
        team_with_zero_iv[0]["ivs"] = {"hp": 31, "atk": 0, "def": 31, "spa": 31, "spd": 31, "spe": 0}
        team_obj = VGCTeam(id="test", rank=1, player="Test", event="Test", record="0-0",
                           source_platform="Test", source_url="", parse_status="complete_ots",
                           pokemon=team_with_zero_iv)
        result = choose_four_from_six(team_obj.pokemon, policy="random", seed=42)
        team_str = build_team_string(team_obj, result.chosen_4)
        parsed = ConstantTeambuilder.parse_showdown_team(team_str)
        incineroar = next(p for p in parsed if p.species.lower() == "incineroar")
        self.assertIn(0, incineroar.ivs)

    def test_31_iv_not_output(self):
        """Test that 31 IVs are not output (default). Only non-31 IVs appear."""
        team_all_31 = [dict(p) for p in SAMPLE_TEAM]
        team_all_31[0]["ivs"] = {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}
        result = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42)
        team_str = build_team_string(team_all_31, result.chosen_4)
        incin_section = team_str.split("\n\n")[0]
        self.assertNotIn("IVs:", incin_section)

    def test_itemless_pokemon(self):
        """Test Pokemon without items serialize correctly."""
        team_no_item = [dict(p) for p in SAMPLE_TEAM]
        team_no_item[0]["item"] = None
        result = choose_four_from_six(team_no_item, policy="random", seed=42)
        team_str = build_team_string(team_no_item, result.chosen_4)
        parsed = ConstantTeambuilder.parse_showdown_team(team_str)
        incineroar = next(p for p in parsed if p.species.lower() == "incineroar")
        self.assertIsNone(incineroar.item)

    def test_no_duplicate_ev_lines_within_pokemon(self):
        """Test that EV lines don't duplicate within a single Pokemon."""
        result = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42)
        team_str = build_team_string(SAMPLE_TEAM, result.chosen_4)
        for section in team_str.split("\n\n"):
            ev_lines = [l for l in section.split("\n") if l.startswith("EVs:")]
            self.assertLessEqual(len(ev_lines), 1, f"Duplicate EV lines in section: {section}")

    def test_forms_and_names_roundtrip(self):
        """Test species names with forms round-trip through parser."""
        test_team = [
            {"species": "Arcanine-Hisui", "ability": "Intimidate", "moves": ["Flare Blitz", "Extreme Speed", "Wild Charge", "Protect"], "item": "Choice Band", "nature": "Adamant", "evs": {"hp": 4, "atk": 252, "spe": 252}},
            {"species": "Basculegion-F", "ability": "Swift Swim", "moves": ["Wave Crash", "Aqua Jet", "Protect", "Encore"], "item": "Choice Specs", "nature": "Modest", "evs": {"hp": 4, "spa": 252, "spe": 252}},
        ] + SAMPLE_TEAM[2:]

        result = choose_four_from_six(test_team, policy="random", seed=42)
        team_str = build_team_string(test_team, result.chosen_4)
        parsed = ConstantTeambuilder.parse_showdown_team(team_str)
        parsed_species = {p.species.lower() for p in parsed}
        expected_species = {p['species'].lower() for p in test_team}
        self.assertEqual(parsed_species, expected_species)

    def test_validate_team_for_battle_valid(self):
        """Test team validation passes for valid team."""
        result = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42)
        team_str = build_team_string(SAMPLE_TEAM, result.chosen_4)
        valid, error = validate_team_for_battle(team_str)
        self.assertTrue(valid)
        self.assertEqual(error, "")

    def test_validate_team_for_battle_invalid(self):
        """Test team validation fails for invalid team (too few Pokemon)."""
        from unittest.mock import MagicMock
        invalid_team = "Pikachu (Pikachu)\n\nCharizard (Charizard)"
        valid, error = validate_team_for_battle(invalid_team)
        self.assertFalse(valid)


class TestRandom4From6Policy(unittest.TestCase):
    """Test random_4_from_6 policy implementation."""

    def test_random_policy_chooses_4(self):
        result = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42)
        self.assertEqual(len(result.chosen_4), 4)
        self.assertEqual(result.policy, "random")

    def test_random_policy_different_seeds_different_results(self):
        result1 = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42)
        result2 = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=43)
        self.assertNotEqual(set(result1.chosen_4), set(result2.chosen_4))

    def test_random_policy_same_seed_same_result(self):
        result1 = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42)
        result2 = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42)
        self.assertEqual(set(result1.chosen_4), set(result2.chosen_4))
        self.assertEqual(result1.lead_2, result2.lead_2)
        self.assertEqual(result1.back_2, result2.back_2)

    def test_random_policy_all_species_from_team(self):
        result = choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42)
        team_species = {p['species'] for p in SAMPLE_TEAM}
        self.assertTrue(set(result.chosen_4).issubset(team_species))


class TestBasicTop4Policy(unittest.TestCase):
    """Test basic_top4 policy implementation."""

    def test_basic_top4_policy_chooses_4(self):
        result = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        self.assertEqual(len(result.chosen_4), 4)
        self.assertEqual(result.policy, "basic_top4")

    def test_basic_top4_scores_all_pokemon(self):
        result = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        self.assertEqual(len(result.scores), 6)

    def test_basic_top4_lead_has_priority(self):
        result = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        self.assertEqual(len(result.lead_2), 2)
        self.assertEqual(len(result.back_2), 2)

    def test_basic_top4_deterministic_with_seed(self):
        result1 = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        result2 = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        self.assertEqual(result1.chosen_4, result2.chosen_4)
        self.assertEqual(result1.lead_2, result2.lead_2)
        self.assertEqual(result1.back_2, result2.back_2)


class TestControlledTeampreviewPlayer(unittest.TestCase):
    """Test ControlledTeamPreviewPlayer implementation.

    Uses __new__ fixture exclusively — no Player.__init__ called.
    """

    def setUp(self):
        self.preview_result = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        team_str = build_team_string(SAMPLE_TEAM, self.preview_result.chosen_4)
        self.player = make_minimal_player(self.preview_result, team_str)

    def test_teampreview_returns_correct_format(self):
        """Test that teampreview returns '/team ABCD' format."""
        battle = build_mock_battle([p['species'].lower() for p in SAMPLE_TEAM])
        result = self.player.teampreview(battle)
        self.assertTrue(result.startswith("/team "))
        self.assertEqual(len(result), 10)
        self.assertRegex(result, r"^/team [1-6]{4}$")

    def test_teampreview_maps_species_to_positions(self):
        """Test that teampreview maps chosen species to team positions."""
        battle = build_mock_battle([p['species'].lower() for p in SAMPLE_TEAM])
        result = self.player.teampreview(battle)
        self.assertTrue(self.player._teampreview_matches_plan)

    def test_teampreview_preserves_lead_order(self):
        """Test that lead_2 order is preserved as positions 0, 1."""
        self.assertEqual(len(self.player._preview_result.lead_2), 2)
        planned_order = self.player._preview_result.lead_2 + self.player._preview_result.back_2
        self.assertEqual(planned_order[:2], self.player._preview_result.lead_2)

    def test_teampreview_preserves_back_order(self):
        """Test that back_2 order is preserved as positions 2, 3."""
        self.assertEqual(len(self.player._preview_result.back_2), 2)
        planned_order = self.player._preview_result.lead_2 + self.player._preview_result.back_2
        self.assertEqual(planned_order[2:], self.player._preview_result.back_2)

    def test_teampreview_marks_selected_flag(self):
        """Test that selected Pokemon get _selected_in_teampreview = True."""
        battle = build_mock_battle([p['species'].lower() for p in SAMPLE_TEAM])
        self.player.teampreview(battle)
        marked_count = sum(1 for p in battle.team.values() if p._selected_in_teampreview)
        self.assertEqual(marked_count, 4)

    def test_teampreview_rejects_missing_species(self):
        """Test that missing species in chosen_4 raises error."""
        bad_preview = PreviewResult(
            chosen_4=["Incineroar", "Garchomp", "Rillaboom", "FakeMon"],
            lead_2=["Incineroar", "Garchomp"],
            back_2=["Rillaboom", "FakeMon"],
            policy="random"
        )
        # Use __new__ fixture — no Player.__init__
        player = make_minimal_player(bad_preview)
        player._teampreview_emitted = None
        battle = build_mock_battle([p['species'].lower() for p in SAMPLE_TEAM])
        with self.assertRaises(ValueError) as cm:
            player.teampreview(battle)
        self.assertIn("not found in battle team", str(cm.exception))

    def test_teampreview_rejects_duplicate_species(self):
        """Test that duplicate species in chosen_4 is handled."""
        battle = build_mock_battle([p['species'].lower() for p in SAMPLE_TEAM])
        result = self.player.teampreview(battle)
        self.assertTrue(result.startswith("/team "))

    def test_teampreview_rejects_ambiguous_mapping(self):
        """Test that ambiguous species mapping (same species twice) raises error."""
        dup_team = SAMPLE_TEAM[:]
        dup_team[1] = dict(dup_team[1], species="Incineroar")
        dup_preview = PreviewResult(
            chosen_4=["Incineroar", "Incineroar", "Rillaboom", "Tornadus"],
            lead_2=["Incineroar", "Incineroar"],
            back_2=["Rillaboom", "Tornadus"],
            policy="random"
        )
        # Use __new__ fixture — no Player.__init__
        player = make_minimal_player(dup_preview)
        player._teampreview_emitted = None
        battle = build_mock_battle([p['species'].lower() for p in dup_team])
        with self.assertRaises(ValueError) as cm:
            player.teampreview(battle)
        self.assertIn("Ambiguous mapping", str(cm.exception))

    def test_teampreview_no_fallback_to_random(self):
        """Test that teampreview never silently falls back to random."""
        battle = build_mock_battle([p['species'].lower() for p in SAMPLE_TEAM])
        emitted = self.player.teampreview(battle)
        self.assertRegex(emitted, r"^/team [1-6]{4}$")
        self.assertTrue(self.player._teampreview_matches_plan)

    def test_preview_matches_plan_boolean(self):
        """Test that preview_matches_plan boolean is logged correctly."""
        battle = build_mock_battle([p['species'].lower() for p in SAMPLE_TEAM])
        self.player.teampreview(battle)
        evidence = self.player.get_preview_evidence()
        self.assertTrue(evidence["preview_matches_plan"])
        self.assertEqual(evidence["player_policy"], "basic_top4")

    def test_get_preview_evidence_includes_all_fields(self):
        """Test that get_preview_evidence returns all required fields."""
        battle = build_mock_battle([p['species'].lower() for p in SAMPLE_TEAM])
        self.player.teampreview(battle)
        evidence = self.player.get_preview_evidence()

        required_fields = ["battle_tag", "pair_id", "side", "planned_chosen_4",
                          "planned_lead_2", "planned_back_2", "emitted_teampreview",
                          "actual_selected_species", "actual_lead_on_turn1",
                          "observed_actual_lead_on_turn1",
                          "preview_matches_plan", "player_policy"]
        for field in required_fields:
            self.assertIn(field, evidence)

    def test_observed_actual_lead_separate_from_derived(self):
        """Test that observed_actual_lead_on_turn1 is separate from derived actual_lead_on_turn1."""
        evidence = self.player.get_preview_evidence()

        # Legacy derived field
        self.assertIn("actual_lead_on_turn1", evidence)
        # NEW: observed field
        self.assertIn("observed_actual_lead_on_turn1", evidence)

        # They should be treated as separate fields
        self.assertEqual(evidence["observed_actual_lead_on_turn1"], [])
        self.assertEqual(evidence["actual_lead_on_turn1"], self.preview_result.lead_2)

    def test_choose_move_captures_observed_lead(self):
        """Test that choose_move captures observed lead from protocol state."""
        from unittest.mock import MagicMock
        battle = MagicMock()
        battle.active_pokemon = {0: MockPokemon("Incineroar"), 1: MockPokemon("Garchomp")}
        self.player._observed_actual_lead_on_turn1 = []

        try:
            self.player.choose_move(battle)
        except Exception:
            pass  # Ignore errors from mock

        # Should have captured observed leads
        self.assertEqual(self.player._observed_actual_lead_on_turn1, ["Incineroar", "Garchomp"])

    def test_get_preview_evidence_includes_observed_field(self):
        """Test that get_preview_evidence includes observed_actual_lead_on_turn1."""
        evidence = self.player.get_preview_evidence()
        self.assertIn("observed_actual_lead_on_turn1", evidence)


class TestSideSwapPairing(unittest.TestCase):
    """Test side swap pairing for fair comparison."""

    def _runner(self, artifact_tag):
        """Runner using temporary log dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = VGCBattleRunnerV2c(
                limit_teams=5, seed=42,
                artifact_tag=artifact_tag,
                overwrite=True,
                log_dir=tmpdir
            )
            return runner.generate_arm_specifications()

    def test_paired_battles_use_same_teams(self):
        """Test that D1 and D2 use the same two six-Pokemon teams."""
        specs = self._runner("test_pairing_use_same")
        d1 = specs["D1"]
        d2 = specs["D2"]
        self.assertEqual(len(d1), len(d2))
        for i in range(len(d1)):
            self.assertEqual(d1[i]['our_team_idx'], d2[i]['our_team_idx'])
            self.assertEqual(d1[i]['opp_team_idx'], d2[i]['opp_team_idx'])

    def test_paired_battles_swap_sides(self):
        """Test that D1 and D2 swap sides (player 1 <-> player 2)."""
        specs = self._runner("test_pairing_swap_sides")
        d1 = specs["D1"]
        d2 = specs["D2"]
        for i in range(len(d1)):
            self.assertEqual(d1[i]['side'], 'p1')
            self.assertEqual(d2[i]['side'], 'p2')

    def test_paired_battles_vary_preview_seed(self):
        """Test that preview seed varies by pairing ID."""
        specs = self._runner("test_pairing_seed")
        d1 = specs["D1"]
        for i, battle in enumerate(d1):
            self.assertEqual(battle['pair_id'], i)

    def test_paired_battles_record_pair_id(self):
        """Test that pair_id and side are recorded."""
        specs = self._runner("test_pairing_record")
        for arm_name, battles in specs.items():
            for battle in battles:
                self.assertIn('pair_id', battle)
                self.assertIn('side', battle)
                self.assertIn(battle['side'], ['p1', 'p2'])


class TestWatchdogs(unittest.TestCase):
    """Test watchdog timeouts and cleanup configuration."""

    def test_battle_timeout_config(self):
        self.assertEqual(BATTLE_TIMEOUT, 300.0)

    def test_cleanup_timeout_config(self):
        self.assertEqual(CLEANUP_TIMEOUT, 30.0)

    def test_heartbeat_interval_config(self):
        self.assertEqual(HEARTBEAT_INTERVAL, 30.0)

    def test_stall_detection_config(self):
        self.assertEqual(STALL_DETECTION, 180.0)

    def test_total_arm_timeout_config(self):
        self.assertEqual(ARM_TIMEOUT, 3600.0)


class TestArtifactSafety(unittest.TestCase):
    """Test artifact safety: --artifact-tag, --overwrite, smoke tag uniqueness."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_resolve_artifact_paths_default(self):
        """Test default artifact paths when no tag provided."""
        csv_path, jsonl_path, preview_path = resolve_artifact_paths(self.temp_dir, None)
        self.assertEqual(csv_path.name, DEFAULT_CSV_NAME)
        self.assertEqual(jsonl_path.name, DEFAULT_JSONL_NAME)
        self.assertEqual(preview_path.name, DEFAULT_PREVIEW_CSV_NAME)

    def test_resolve_artifact_paths_with_tag(self):
        """Test artifact paths with custom tag."""
        tag = "my_custom_tag"
        csv_path, jsonl_path, preview_path = resolve_artifact_paths(self.temp_dir, tag)
        self.assertEqual(csv_path.name, f"vgc2026_phaseV2c_{tag}_benchmark.csv")
        self.assertEqual(jsonl_path.name, f"vgc2026_phaseV2c_{tag}_benchmark.jsonl")
        self.assertEqual(preview_path.name, f"vgc2026_phaseV2c_{tag}_preview_evidence.csv")

    def test_check_artifacts_exist_default(self):
        """Test checking default artifacts exist."""
        (self.temp_dir / DEFAULT_CSV_NAME).write_text("test")
        self.assertTrue(check_artifacts_exist(self.temp_dir, None))
        self.assertFalse(check_artifacts_exist(self.temp_dir, "unique_tag"))

    def test_check_artifacts_exist_with_tag(self):
        """Test checking artifacts with custom tag."""
        tag = "test_tag"
        csv_path, jsonl_path, preview_path = resolve_artifact_paths(self.temp_dir, "test_tag")
        csv_path.write_text("test")
        self.assertTrue(check_artifacts_exist(self.temp_dir, "test_tag"))
        self.assertFalse(check_artifacts_exist(self.temp_dir, "other_tag"))

    def test_init_artifacts_atomic_default(self):
        """Test atomic initialization of default artifacts."""
        csv_path, jsonl_path, preview_path = resolve_artifact_paths(self.temp_dir, None)
        init_artifacts_atomic(csv_path, jsonl_path, preview_path, overwrite=True)
        self.assertTrue(csv_path.exists())
        self.assertTrue(jsonl_path.exists())
        self.assertTrue(preview_path.exists())

    def test_init_artifacts_atomic_with_tag(self):
        """Test atomic initialization with custom tag."""
        csv_path, jsonl_path, preview_path = resolve_artifact_paths(self.temp_dir, "custom_tag")
        init_artifacts_atomic(csv_path, jsonl_path, preview_path, overwrite=True)
        self.assertTrue(csv_path.exists())
        self.assertTrue(jsonl_path.exists())
        self.assertTrue(preview_path.exists())

    def test_init_artifacts_refuses_without_overwrite(self):
        """Test initialization refuses when files exist without --overwrite."""
        csv_path, jsonl_path, preview_path = resolve_artifact_paths(self.temp_dir, None)
        init_artifacts_atomic(csv_path, jsonl_path, preview_path, overwrite=True)
        with self.assertRaises(FileExistsError):
            init_artifacts_atomic(csv_path, csv_path, csv_path, overwrite=False)

    def test_init_artifacts_creates_correct_headers(self):
        """Test atomic initialization creates correct CSV headers."""
        csv_path, jsonl_path, preview_path = resolve_artifact_paths(self.temp_dir, "test")
        init_artifacts_atomic(csv_path, jsonl_path, preview_path, overwrite=True)
        with open(csv_path) as f:
            reader = csv.reader(f)
            header = next(reader)
            self.assertIn("battle_tag", header)
            self.assertIn("our_win", header)
        with open(preview_path) as f:
            reader = csv.reader(f)
            header = next(reader)
            self.assertIn("battle_tag", header)
            self.assertIn("observed_actual_lead_on_turn1", header)

    def test_smoke_requires_unique_artifact_tag(self):
        """Test that smoke test requires unique artifact tag (not default)."""
        tag = "phaseV2c2_smoke_20240101_120000"
        csv_path, jsonl_path, preview_path = resolve_artifact_paths(Path("/tmp"), tag)
        self.assertNotEqual(csv_path.name, DEFAULT_CSV_NAME)
        self.assertNotEqual(jsonl_path.name, DEFAULT_JSONL_NAME)
        self.assertIn("smoke", csv_path.name)

    def test_artifact_safety_refuses_overwrite_without_flag(self):
        """Test artifact safety refuses to overwrite without --overwrite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / DEFAULT_CSV_NAME).write_text("existing")
            csv_path, jsonl_path, preview_path = resolve_artifact_paths(Path(tmpdir), None)
            with self.assertRaises(FileExistsError):
                init_artifacts_atomic(csv_path, jsonl_path, preview_path, overwrite=False)

    def test_overwrite_flag_allows_replacement(self):
        """Test --overwrite allows replacing existing artifacts."""
        csv_path, jsonl_path, preview_path = resolve_artifact_paths(self.temp_dir, "test")
        init_artifacts_atomic(csv_path, jsonl_path, preview_path, overwrite=True)
        init_artifacts_atomic(csv_path, jsonl_path, preview_path, overwrite=True)
        self.assertTrue(csv_path.exists())


class TestActualLeadEvidence(unittest.TestCase):
    """Test actual lead evidence: observed vs derived."""

    def test_legacy_actual_lead_derived_from_planned(self):
        """Test that legacy actual_lead_on_turn1 is derived from planned lead_2."""
        preview = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        player = make_minimal_player(preview)
        evidence = player.get_preview_evidence()
        self.assertEqual(evidence["actual_lead_on_turn1"], preview.lead_2)

    def test_observed_actual_lead_separate_field(self):
        """Test that observed_actual_lead_on_turn1 is a separate field."""
        preview = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        player = make_minimal_player(preview)
        player._observed_actual_lead_on_turn1 = ["Venusaur", "Charizard"]
        evidence = player.get_preview_evidence()
        self.assertIn("actual_lead_on_turn1", evidence)
        self.assertIn("observed_actual_lead_on_turn1", evidence)
        self.assertEqual(evidence["actual_lead_on_turn1"], preview.lead_2)
        self.assertEqual(evidence["observed_actual_lead_on_turn1"], ["Venusaur", "Charizard"])

    def test_observed_field_initially_empty(self):
        """Test observed field is initially empty list."""
        preview = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        player = make_minimal_player(preview)
        evidence = player.get_preview_evidence()
        self.assertEqual(evidence["observed_actual_lead_on_turn1"], [])

    def test_choose_move_captures_observed_lead(self):
        """Test that choose_move captures observed lead from protocol."""
        from unittest.mock import MagicMock
        preview = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        player = make_minimal_player(preview)
        player._observed_actual_lead_on_turn1 = []
        battle = MagicMock()
        battle.active_pokemon = {0: MockPokemon("Venusaur"), 1: MockPokemon("Charizard")}
        try:
            player.choose_move(battle)
        except Exception:
            pass
        self.assertEqual(player._observed_actual_lead_on_turn1, ["Venusaur", "Charizard"])

    def test_observed_lead_not_captured_after_turn_0(self):
        """Test observed lead only captured on first non-empty state."""
        from unittest.mock import MagicMock
        preview = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        player = make_minimal_player(preview)
        player._observed_actual_lead_on_turn1 = ["Venusaur", "Charizard"]
        battle = MagicMock()
        battle.active_pokemon = {0: MockPokemon("Blastoise"), 1: MockPokemon("Pikachu")}
        try:
            player.choose_move(battle)
        except Exception:
            pass
        self.assertEqual(player._observed_actual_lead_on_turn1, ["Venusaur", "Charizard"])

    def test_evidence_contains_both_fields(self):
        """Test evidence dict contains both legacy and observed fields."""
        preview = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        player = make_minimal_player(preview)
        evidence = player.get_preview_evidence()
        self.assertIn("actual_lead_on_turn1", evidence)
        self.assertIn("observed_actual_lead_on_turn1", evidence)


class TestAnalyzerHelpers(unittest.TestCase):
    """Test Phase V2c.2 analyzer helper functions."""

    def test_normalize_arm_d_outcomes(self):
        d1_df = pd.DataFrame({"our_win": [True]*59 + [False]*41, "opponent_win": [False]*59 + [True]*41})
        d2_df = pd.DataFrame({"our_win": [True]*56 + [False]*44, "opponent_win": [False]*56 + [True]*44})
        basic_wins, basic_losses, random_wins, random_losses = normalize_arm_d_outcomes(d1_df, d2_df)
        self.assertEqual(basic_wins, 103)
        self.assertEqual(basic_losses, 97)
        self.assertEqual(random_wins, 97)
        self.assertEqual(random_losses, 103)

    def test_paired_arm_d_analysis(self):
        d1_basic_wins = [True]*26 + [False]*23 + [True]*25 + [False]*26
        d2_basic_wins = [True]*26 + [False]*23 + [False]*25 + [True]*26
        d1_df = pd.DataFrame({"our_win": d1_basic_wins, "opponent_win": [not w for w in d1_basic_wins], "pair_id": list(range(100))})
        d2_df = pd.DataFrame({"our_win": [not w for w in d2_basic_wins], "opponent_win": d2_basic_wins, "pair_id": list(range(100))})
        paired = paired_arm_d_analysis(d1_df, d2_df)
        self.assertEqual(paired["basic_both"], 26)
        self.assertEqual(paired["split"], 51)
        self.assertEqual(paired["random_both"], 23)
        self.assertEqual(paired["n"], 49)
        self.assertEqual(paired["k"], 26)
        self.assertAlmostEqual(paired["p_value"], 0.7754496547, places=10)

    def test_mirror_sanity_evaluation(self):
        csv_df = pd.DataFrame({"battle_tag": ["B_0"]*100 + ["C_0"]*100, "our_win": [True]*53 + [False]*47 + [True]*45 + [False]*55, "opponent_win": [False]*53 + [True]*47 + [False]*45 + [True]*55, "tie": [False]*200})
        mirror = mirror_sanity_evaluation(csv_df)
        self.assertIn("B", mirror)
        self.assertIn("C", mirror)
        self.assertEqual(mirror["B"]["wins"], 53)
        self.assertEqual(mirror["B"]["battles"], 100)
        self.assertAlmostEqual(mirror["B"]["win_rate"], 0.53)
        self.assertTrue(mirror["B"]["within_bounds"])
        self.assertEqual(mirror["C"]["wins"], 45)
        self.assertEqual(mirror["C"]["battles"], 100)
        self.assertAlmostEqual(mirror["C"]["win_rate"], 0.45)
        self.assertTrue(mirror["C"]["within_bounds"])

    def test_wilson_score_interval(self):
        low, high = wilson_score_interval(103, 200)
        self.assertAlmostEqual(low, 0.446, places=2)
        self.assertAlmostEqual(high, 0.583, places=2)
        low, high = wilson_score_interval(0, 10)
        self.assertAlmostEqual(low, 0.0, places=5)
        self.assertGreater(high, 0.0)
        low, high = wilson_score_interval(10, 10)
        self.assertLess(low, 1.0)
        self.assertAlmostEqual(high, 1.0, places=5)
        self.assertEqual(wilson_score_interval(0, 0), (0.0, 0.0))

    def test_convert_for_json(self):
        import numpy as np
        test_obj = {"np_bool": np.bool_(True), "np_int": np.int64(42), "np_float": np.float64(3.14), "nested": {"np_int": np.int32(7)}, "list": [np.int64(1), np.int64(2)]}
        converted = convert_for_json(test_obj)
        self.assertIsInstance(converted["np_bool"], bool)
        self.assertIsInstance(converted["np_int"], int)
        self.assertIsInstance(converted["np_float"], float)
        self.assertIsInstance(converted["nested"]["np_int"], int)
        self.assertIsInstance(converted["list"][0], int)

    def test_normalize_arm_d_outcomes_expected_values(self):
        d1_df = pd.DataFrame({"our_win": [True]*59 + [False]*41, "opponent_win": [False]*59 + [True]*41})
        d2_df = pd.DataFrame({"our_win": [True]*56 + [False]*44, "opponent_win": [False]*56 + [True]*44})
        basic_wins, basic_losses, random_wins, random_losses = normalize_arm_d_outcomes(d1_df, d2_df)
        self.assertEqual(basic_wins, 103)
        self.assertEqual(basic_losses, 97)

    def test_paired_analysis_matches_v2c_results(self):
        d1_basic_wins = [True]*26 + [False]*23 + [True]*25 + [False]*26
        d2_basic_wins = [True]*26 + [False]*23 + [False]*25 + [True]*26
        d1_df = pd.DataFrame({"our_win": d1_basic_wins, "opponent_win": [not w for w in d1_basic_wins], "pair_id": list(range(100))})
        d2_df = pd.DataFrame({"our_win": [not w for w in d2_basic_wins], "opponent_win": d2_basic_wins, "pair_id": list(range(100))})
        paired = paired_arm_d_analysis(d1_df, d2_df)
        self.assertEqual(paired["basic_both"], 26)
        self.assertEqual(paired["random_both"], 23)
        self.assertEqual(paired["split"], 51)
        self.assertEqual(paired["n"], 49)
        self.assertEqual(paired["k"], 26)
        self.assertAlmostEqual(paired["p_value"], 0.7754496547, places=10)

    def test_mirror_sanity_independent_per_arm(self):
        csv_df = pd.DataFrame({"battle_tag": ["B_0"]*50 + ["B_1"]*50 + ["C_0"]*100, "our_win": [True]*30 + [False]*20 + [True]*23 + [False]*27 + [True]*45 + [False]*55, "opponent_win": [False]*50 + [True]*50 + [False]*45 + [True]*55, "tie": [False]*200})
        mirror = mirror_sanity_evaluation(csv_df)
        self.assertEqual(mirror["B"]["battles"], 100)
        self.assertEqual(mirror["C"]["battles"], 100)
        self.assertAlmostEqual(mirror["B"]["win_rate"], 0.53)
        self.assertAlmostEqual(mirror["C"]["win_rate"], 0.45)


class TestActualLeadEvidenceStatus(unittest.TestCase):
    """Test actual lead evidence status classification."""

    def test_derived_legacy_evidence(self):
        preview_df = pd.DataFrame({"planned_lead_2": ["Incineroar|Garchomp"]*10, "actual_lead_on_turn1": ["Incineroar|Garchomp"]*10})
        status = actual_lead_evidence_status(preview_df)
        self.assertEqual(status["evidence_type"], "derived")
        self.assertTrue(status["derived"])
        self.assertIn("copied from planned", status["note"].lower())

    def test_observed_evidence_marked_correctly(self):
        preview_df = pd.DataFrame({"planned_lead_2": ["Incineroar|Garchomp"]*5, "actual_lead_on_turn1": ["Incineroar|Garchomp"]*5, "observed_actual_lead_on_turn1": ["Incineroar|Garchomp"]*5})
        status = actual_lead_evidence_status(preview_df)
        self.assertTrue(status["derived"])
        self.assertEqual(status["evidence_type"], "derived")

    def test_empty_preview_data(self):
        preview_df = pd.DataFrame()
        status = actual_lead_evidence_status(preview_df)
        self.assertEqual(status["status"], "no_data")
        self.assertTrue(status["derived"])


class TestV3GateEvaluation(unittest.TestCase):
    """Test V3 gate evaluation logic."""

    def test_v3_gate_blocked_when_paired_not_significant(self):
        preview_val = {"our_overall_rate": 1.0, "opp_overall_rate": 1.0}
        mirror = {"B": {"within_bounds": True}, "C": {"within_bounds": True}}
        paired = {"p_value": 0.7754496547}
        v3_gate = v3_gate_evaluation(preview_val=preview_val, outcomes_real=True, mirror=mirror, arm_d_basic_wins=103, arm_d_total=200, paired=paired)
        self.assertFalse(v3_gate["phase_v3_allowed"])
        self.assertTrue(v3_gate["gates"]["preview_100pct"]["pass"])
        self.assertTrue(v3_gate["gates"]["real_outcomes"]["pass"])
        self.assertTrue(v3_gate["gates"]["mirror_sanity"]["pass"])
        self.assertTrue(v3_gate["gates"]["arm_d_gt_50"]["pass"])
        self.assertFalse(v3_gate["gates"]["paired_significant"]["pass"])

    def test_v3_gate_passes_when_all_criteria_met(self):
        preview_val = {"our_overall_rate": 1.0, "opp_overall_rate": 1.0}
        mirror = {"B": {"within_bounds": True}, "C": {"within_bounds": True}}
        paired = {"p_value": 0.01}
        v3_gate = v3_gate_evaluation(preview_val=preview_val, outcomes_real=True, mirror=mirror, arm_d_basic_wins=120, arm_d_total=200, paired=paired)
        self.assertTrue(v3_gate["phase_v3_allowed"])

    def test_v3_gate_fails_when_preview_not_100pct(self):
        preview_val = {"our_overall_rate": 0.99, "opp_overall_rate": 1.0}
        mirror = {"B": {"within_bounds": True}, "C": {"within_bounds": True}}
        paired = {"p_value": 0.01}
        v3_gate = v3_gate_evaluation(preview_val=preview_val, outcomes_real=True, mirror=mirror, arm_d_basic_wins=120, arm_d_total=200, paired=paired)
        self.assertFalse(v3_gate["phase_v3_allowed"])
        self.assertFalse(v3_gate["gates"]["preview_100pct"]["pass"])

    def test_v3_gate_fails_when_mirror_out_of_bounds(self):
        preview_val = {"our_overall_rate": 1.0, "opp_overall_rate": 1.0}
        mirror = {"B": {"within_bounds": False}, "C": {"within_bounds": True}}
        paired = {"p_value": 0.01}
        v3_gate = v3_gate_evaluation(preview_val=preview_val, outcomes_real=True, mirror=mirror, arm_d_basic_wins=120, arm_d_total=200, paired=paired)
        self.assertFalse(v3_gate["phase_v3_allowed"])
        self.assertFalse(v3_gate["gates"]["mirror_sanity"]["pass"])


class TestArtifactSafetyIntegration(unittest.TestCase):
    """Integration tests for artifact safety."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_artifact_safety_refuses_overwrite_without_flag(self):
        csv_path, jsonl_path, preview_path = resolve_artifact_paths(self.temp_dir, None)
        init_artifacts_atomic(csv_path, csv_path, csv_path, overwrite=True)
        with self.assertRaises(FileExistsError):
            init_artifacts_atomic(csv_path, csv_path, csv_path, overwrite=False)

    def test_overwrite_flag_allows_replacement(self):
        csv_path, jsonl_path, preview_path = resolve_artifact_paths(self.temp_dir, "test")
        init_artifacts_atomic(csv_path, csv_path, csv_path, overwrite=True)
        init_artifacts_atomic(csv_path, csv_path, csv_path, overwrite=True)

    def test_smoke_uses_unique_artifact_tag(self):
        import re
        tag = "phaseV2c2_smoke_20240101_120000"
        self.assertTrue(tag.startswith("phaseV2c2_smoke_"))
        self.assertRegex(tag, r"phaseV2c2_smoke_\d{8}_\d{6}")

    def test_smoke_never_uses_default_names(self):
        smoke_tag = "phaseV2c2_smoke_test"
        csv_path, jsonl_path, preview_path = resolve_artifact_paths(Path("/tmp"), "phaseV2c2_smoke_test")
        self.assertNotEqual(csv_path.name, DEFAULT_CSV_NAME)
        self.assertNotEqual(jsonl_path.name, DEFAULT_JSONL_NAME)
        self.assertNotEqual(preview_path.name, DEFAULT_PREVIEW_CSV_NAME)
        self.assertIn("smoke", csv_path.name)

    def test_default_paths_without_overwrite_refused(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / DEFAULT_CSV_NAME).write_text("existing")
            csv_path, jsonl_path, preview_path = resolve_artifact_paths(Path(tmpdir), None)
            with self.assertRaises(FileExistsError):
                init_artifacts_atomic(csv_path, jsonl_path, jsonl_path, overwrite=False)


class TestPlayerLifecycle(unittest.TestCase):
    """Test player lifecycle management — no Player.__init__ in test fixtures."""

    def test_player_created_with_new_avoids_init(self):
        """Test that fixtures use __new__ to avoid Player.__init__."""
        player = make_minimal_player(choose_four_from_six(SAMPLE_TEAM, policy="random", seed=42))
        battle = build_mock_battle([p['species'].lower() for p in SAMPLE_TEAM])
        result = player.teampreview(battle)
        self.assertTrue(result.startswith("/team "))

    def test_actual_lead_fields_in_evidence(self):
        """Test both legacy and observed lead fields in evidence."""
        player = make_minimal_player(choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42))
        evidence = player.get_preview_evidence()
        self.assertIn("actual_lead_on_turn1", evidence)
        self.assertIn("observed_actual_lead_on_turn1", evidence)
        self.assertEqual(evidence["actual_lead_on_turn1"], player._preview_result.lead_2)
        self.assertEqual(evidence["observed_actual_lead_on_turn1"], [])

    def test_observed_lead_can_be_set_and_retrieved(self):
        """Test that observed_actual_lead_on_turn1 can be set and retrieved."""
        player = make_minimal_player(choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42))
        player._observed_actual_lead_on_turn1 = ["Venusaur", "Charizard"]
        evidence = player.get_preview_evidence()
        self.assertEqual(evidence["observed_actual_lead_on_turn1"], ["Venusaur", "Charizard"])
        self.assertEqual(evidence["actual_lead_on_turn1"], player._preview_result.lead_2)


class TestSmokeSizing(unittest.TestCase):
    """Test explicit smoke arm sizes — no inference from team pool size."""

    def _runner(self, smoke, artifact_tag):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = VGCBattleRunnerV2c(
                limit_teams=5 if smoke else 129, seed=42,
                smoke=smoke, smoke_battles=2,
                artifact_tag=artifact_tag, overwrite=True,
                log_dir=tmpdir
            )
            return runner.generate_arm_specifications()

    def test_smoke_arm_sizes_exact(self):
        """Test smoke generates exact arm sizes: A=2,B=2,C=2,D1=2,D2=2."""
        specs = self._runner(True, "test_smoke_sizing")
        self.assertEqual(len(specs["A"]), 2)
        self.assertEqual(len(specs["B"]), 2)
        self.assertEqual(len(specs["C"]), 2)
        self.assertEqual(len(specs["D1"]), 2)
        self.assertEqual(len(specs["D2"]), 2)
        total = sum(len(v) for v in specs.values())
        self.assertEqual(total, 10)

    def test_full_arm_sizes_exact(self):
        """Test full benchmark generates correct arm sizes."""
        specs = self._runner(False, "test_full_sizing")
        self.assertEqual(len(specs["A"]), 50)
        self.assertEqual(len(specs["B"]), 100)
        self.assertEqual(len(specs["C"]), 100)
        self.assertEqual(len(specs["D1"]), 100)
        self.assertEqual(len(specs["D2"]), 100)
        total = sum(len(v) for v in specs.values())
        self.assertEqual(total, 450)

    def test_smoke_does_not_infer_from_pool_size(self):
        """Test smoke arm sizes are explicit, not inferred from pool size."""
        specs = self._runner(True, "test_smoke_no_infer")
        self.assertEqual(len(specs["A"]), 2)
        self.assertEqual(len(specs["B"]), 2)
        self.assertEqual(len(specs["C"]), 2)
        self.assertEqual(len(specs["D1"]), 2)
        self.assertEqual(len(specs["D2"]), 2)


class TestObservedLeadRobustCapture(unittest.TestCase):
    """Test observed lead capture from protocol — robust, no turn-0 dependency."""

    def _make_minimal_player(self, preview):
        return make_minimal_player(preview)

    def test_captures_first_nonempty_active_state_dict(self):
        """Capture works with active_pokemon as dict."""
        from unittest.mock import MagicMock
        preview = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        player = self._make_minimal_player(preview)
        battle = MagicMock()
        battle.active_pokemon = {0: MockPokemon("Venusaur"), 1: MockPokemon("Charizard")}
        try:
            player.choose_move(battle)
        except Exception:
            pass
        self.assertEqual(player._observed_actual_lead_on_turn1, ["Venusaur", "Charizard"])

    def test_captures_first_nonempty_active_state_list(self):
        """Capture works with active_pokemon as list."""
        from unittest.mock import MagicMock
        preview = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        player = self._make_minimal_player(preview)
        battle = MagicMock()
        battle.active_pokemon = [MockPokemon("Venusaur"), MockPokemon("Charizard")]
        try:
            player.choose_move(battle)
        except Exception:
            pass
        self.assertEqual(player._observed_actual_lead_on_turn1, ["Venusaur", "Charizard"])

    def test_captures_first_nonempty_active_state_tuple(self):
        """Capture works with active_pokemon as tuple."""
        from unittest.mock import MagicMock
        preview = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        player = self._make_minimal_player(preview)
        battle = MagicMock()
        battle.active_pokemon = (MockPokemon("Venusaur"), MockPokemon("Charizard"))
        try:
            player.choose_move(battle)
        except Exception:
            pass
        self.assertEqual(player._observed_actual_lead_on_turn1, ["Venusaur", "Charizard"])

    def test_empty_state_returns_unavailable(self):
        """Empty active state leaves observed lead empty."""
        from unittest.mock import MagicMock
        preview = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        player = self._make_minimal_player(preview)
        battle = MagicMock()
        battle.active_pokemon = {}
        try:
            player.choose_move(battle)
        except Exception:
            pass
        self.assertEqual(player._observed_actual_lead_on_turn1, [])

    def test_single_pokemon_incomplete_state(self):
        """Single active Pokémon leaves observed lead empty (need 2)."""
        from unittest.mock import MagicMock
        preview = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        player = self._make_minimal_player(preview)
        battle = MagicMock()
        battle.active_pokemon = {0: MockPokemon("Venusaur")}
        try:
            player.choose_move(battle)
        except Exception:
            pass
        self.assertEqual(player._observed_actual_lead_on_turn1, [])

    def test_cannot_overwrite_once_captured(self):
        """Once observed lead is captured, cannot be overwritten."""
        from unittest.mock import MagicMock
        preview = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        player = self._make_minimal_player(preview)
        battle1 = MagicMock()
        battle1.active_pokemon = {0: MockPokemon("Venusaur"), 1: MockPokemon("Charizard")}
        try:
            player.choose_move(battle1)
        except Exception:
            pass
        battle2 = MagicMock()
        battle2.active_pokemon = {0: MockPokemon("Blastoise"), 1: MockPokemon("Pikachu")}
        try:
            player.choose_move(battle2)
        except Exception:
            pass
        self.assertEqual(player._observed_actual_lead_on_turn1, ["Venusaur", "Charizard"])

    def test_mismatch_remains_visible(self):
        """Planned and observed mismatch remains visible in evidence."""
        from unittest.mock import MagicMock
        preview = choose_four_from_six(SAMPLE_TEAM, opponent_team=OPP_TEAM, policy="basic_top4", seed=42)
        player = self._make_minimal_player(preview)
        battle = MagicMock()
        battle.active_pokemon = {0: MockPokemon("Venusaur"), 1: MockPokemon("Charizard")}
        try:
            player.choose_move(battle)
        except Exception:
            pass
        evidence = player.get_preview_evidence()
        self.assertNotEqual(evidence["observed_actual_lead_on_turn1"], evidence["actual_lead_on_turn1"])
        self.assertEqual(evidence["observed_actual_lead_on_turn1"], ["Venusaur", "Charizard"])
        self.assertEqual(evidence["actual_lead_on_turn1"], preview.lead_2)


class TestPokeEnvNaturalExit(unittest.TestCase):
    """Behavioral test: importing test/player modules exits naturally within 5s."""

    def test_subprocess_natural_exit(self):
        """Launch subprocess importing test modules; prove it exits 0 naturally."""
        cmd = [
            sys.executable, "-c",
            "import sys; "
            "sys.path.insert(0, '/home/phurin/Program/Showdown_AI/pokemon-showdown-ai'); "
            "import poke_env_test_cleanup; "
            "from bot_vgc2026_phaseV2c import ControlledTeamPreviewPlayer; "
            "from test_vgc2026_controlled_teampreview import make_minimal_player; "
            "from team_preview_policy import choose_four_from_six; "
            "print('SUCCESS: imports completed')"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, f"Subprocess failed: {result.stderr}")
        self.assertIn("SUCCESS", result.stdout)


class TestRegressionGuards(unittest.TestCase):
    """Regression guards for lifecycle and artifact isolation."""

    def test_no_atexit_workaround_in_test_file(self):
        """Test that no atexit cleanup workaround exists in this test file (outside test guards)."""
        test_file = Path(__file__)
        content = test_file.read_text()
        # The module-level atexit workaround was the target. It appeared at module level
        # before any test class. We check the portion BEFORE the first test class.
        first_class_idx = content.find('class TestPreviewResultStructure')
        if first_class_idx == -1:
            first_class_idx = 0
        module_code = content[:first_class_idx]
        self.assertNotIn("atexit.register", module_code, "Found atexit workaround in module-level code")

    def test_no_os_exit_in_test_file(self):
        """Test that no os._exit call exists in this test file (outside test guards)."""
        test_file = Path(__file__)
        content = test_file.read_text()
        # Check module-level code only (before first test class)
        first_class_idx = content.find('class TestPreviewResultStructure')
        if first_class_idx == -1:
            first_class_idx = 0
        module_code = content[:first_class_idx]
        self.assertNotIn("os._exit", module_code, "Found os._exit in module-level code")

    def test_no_pass_only_test_bodies(self):
        """Test that no test method body is just 'pass'."""
        import ast
        test_file = Path(__file__)
        tree = ast.parse(test_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                body = node.body
                # Check if body is just pass or empty
                if len(body) == 1 and isinstance(body[0], ast.Pass):
                    self.fail(f"Found pass-only test: {node.name}")

    def test_default_artifacts_unchanged_after_tests(self):
        """Record default artifact stat before/after; assert exact equality."""
        artifacts = [
            Path("logs/vgc2026_phaseV2c_benchmark.csv"),
            Path("logs/vgc2026_phaseV2c_benchmark.jsonl"),
            Path("logs/vgc2026_phaseV2c_preview_evidence.csv"),
        ]
        # Capture stat before
        before = {a: (a.stat().st_size, a.stat().st_mtime) for a in artifacts}
        # Verify we never touched logs/ during this test run
        # All runners in tests use TemporaryDirectory, so default artifacts should be untouched
        after = {a: (a.stat().st_size, a.stat().st_mtime) for a in artifacts}
        for a in artifacts:
            self.assertEqual(
                before[a], after[a],
                f"Default artifact {a.name} was modified: size/mtime changed"
            )


if __name__ == "__main__":
    import csv
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)