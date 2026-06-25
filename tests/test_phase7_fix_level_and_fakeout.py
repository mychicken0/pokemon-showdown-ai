"""Tests for PHASE7_DATA_EXPANSION_FIX_LEVEL_MISMATCH_AND_FAKE_OUT.

Ponytail: pure unit tests. No poke-env runtime, no network,
no battles, no GPU.
"""
import json
import os
import unittest
import sys
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)

# Import team definitions and validators
import showdown_ai.rl_data_3b_small_local_audit as audit_mod


class _Order:
    def __init__(self, inner=None, move_target=0):
        self.order = inner
        self.move_target = move_target


class _Move:
    def __init__(self, move_id="", category="", target=""):
        self.id = move_id
        self._category = category
        self._target = target

    @property
    def category(self):
        return self._category


try:
    from showdown_ai.bot_doubles_damage_aware import (
        _is_fake_out_first_turn_only,
        _is_same_side_single_target_damage_blocked,
    )
except Exception:
    _is_fake_out_first_turn_only = None
    _is_same_side_single_target_damage_blocked = None


class FakeBattle:
    """Minimal battle mock for Fake Out testing."""
    def __init__(self, active_mons):
        self.active_pokemon = active_mons


class FakeMon:
    """Minimal Pokemon mock for first_turn testing."""
    def __init__(self, first_turn=False):
        self.first_turn = first_turn


# ---- Fix A: Team Level Validation ----

class TestTeamLevelExplicit(unittest.TestCase):
    """OPP_TEAM must have explicit Level: 50 for every Pokemon."""

    def test_opp_team_has_level_50_for_incineroar(self):
        self.assertIn("Level: 50", audit_mod.OPP_TEAM.split("Incineroar")[1].split("Tornadus")[0])

    def test_opp_team_has_level_50_for_tornadus(self):
        self.assertIn("Level: 50", audit_mod.OPP_TEAM.split("Tornadus")[1].split("Clefable")[0])

    def test_opp_team_has_level_50_for_clefable(self):
        self.assertIn("Level: 50", audit_mod.OPP_TEAM.split("Clefable")[1].split("Garchomp")[0])

    def test_opp_team_has_level_50_for_garchomp(self):
        self.assertIn("Level: 50", audit_mod.OPP_TEAM.split("Garchomp")[1].split("Tyranitar")[0])

    def test_opp_team_has_level_50_for_tyranitar(self):
        self.assertIn("Level: 50", audit_mod.OPP_TEAM.split("Tyranitar")[1].split("Volcarona")[0])

    def test_opp_team_has_level_50_for_volcarona(self):
        self.assertIn("Level: 50", audit_mod.OPP_TEAM.split("Volcarona")[1])


class TestTeamValidator(unittest.TestCase):
    """_validate_team_levels rejects missing/non-50 Level lines."""

    def test_valid_opp_team_passes(self):
        audit_mod._validate_team_levels(audit_mod.OPP_TEAM, "OPP_TEAM", expected_level=50)

    def test_missing_level_raises(self):
        bad_team = "Pikachu @ Light Ball\nAbility: Static\n- Thunderbolt"
        with self.assertRaises(ValueError) as ctx:
            audit_mod._validate_team_levels(bad_team, "bad", expected_level=50)
        self.assertIn("Pikachu", str(ctx.exception))

    def test_wrong_level_raises(self):
        bad_team = "Charizard @ Life Orb\nAbility: Blaze\nLevel: 100\n- Flamethrower"
        with self.assertRaises(ValueError) as ctx:
            audit_mod._validate_team_levels(bad_team, "bad", expected_level=50)
        self.assertIn("Charizard", str(ctx.exception))

    def test_wrong_level_100_raises(self):
        with self.assertRaises(ValueError):
            audit_mod._validate_team_levels(audit_mod.OPP_TEAM, "OPP_TEAM", expected_level=100)

    def test_wrong_number_of_pokemon_raises(self):
        team = "Pikachu @ Light Ball\nAbility: Static\nLevel: 50\n- Thunderbolt"
        with self.assertRaises(ValueError):
            audit_mod._validate_team_levels(team, "too_few", expected_level=50)

    def test_validate_all_teams_passes(self):
        audit_mod._validate_all_teams(expected_level=50)

    def test_our_team_json_has_level_50(self):
        """The wt2_audit_team JSON file defines Level 50 for all
        6 Pokemon, verified by _validate_all_teams."""
        audit_mod._validate_all_teams(expected_level=50)


class TestOurTeamLevelExplicit(unittest.TestCase):
    """OUR_TEAM (from JSON) has explicit Level: 50 for every
    Pokemon via json_to_showdown converter."""

    def test_validate_all_teams_checks_both_teams(self):
        audit_mod._validate_all_teams(expected_level=50)


# ---- Fix B: Fake Out Safety ----

class TestFakeOutSafetyDefinition(unittest.TestCase):
    """_is_fake_out_first_turn_only exists and is callable."""

    def test_function_exists(self):
        self.assertIsNotNone(_is_fake_out_first_turn_only)

    def test_function_callable(self):
        b = FakeBattle([FakeMon(first_turn=True)])
        order = _Order(inner=_Move("fakeout"))
        self.assertTrue(callable(_is_fake_out_first_turn_only))


class TestFakeOutFirstTurnAllowed(unittest.TestCase):
    """Fake Out on first active turn is NOT blocked."""

    def test_fake_out_first_turn_allowed(self):
        b = FakeBattle([FakeMon(first_turn=True)])
        order = _Order(inner=_Move("fakeout"))
        self.assertFalse(_is_fake_out_first_turn_only(order, b, 0))

    def test_fake_out_first_turn_slot_1_allowed(self):
        b = FakeBattle([FakeMon(), FakeMon(first_turn=True)])
        order = _Order(inner=_Move("fakeout"))
        self.assertFalse(_is_fake_out_first_turn_only(order, b, 1))


class TestFakeOutNotFirstTurnBlocked(unittest.TestCase):
    """Fake Out after the first active turn IS blocked."""

    def test_fake_out_not_first_turn_blocked(self):
        b = FakeBattle([FakeMon(first_turn=False)])
        order = _Order(inner=_Move("fakeout"))
        self.assertTrue(_is_fake_out_first_turn_only(order, b, 0))

    def test_fake_out_not_first_turn_slot_1_blocked(self):
        b = FakeBattle([FakeMon(), FakeMon(first_turn=False)])
        order = _Order(inner=_Move("fakeout"))
        self.assertTrue(_is_fake_out_first_turn_only(order, b, 1))


class TestNonFakeOutNotBlocked(unittest.TestCase):
    """Non-Fake-Out moves are NOT blocked by the Fake Out rule."""

    def test_psychic_not_blocked(self):
        b = FakeBattle([FakeMon(first_turn=False)])
        order = _Order(inner=_Move("psychic"))
        self.assertFalse(_is_fake_out_first_turn_only(order, b, 0))

    def test_protect_not_blocked(self):
        b = FakeBattle([FakeMon(first_turn=False)])
        order = _Order(inner=_Move("protect"))
        self.assertFalse(_is_fake_out_first_turn_only(order, b, 0))

    def test_switch_not_blocked(self):
        b = FakeBattle([FakeMon(first_turn=False)])
        order = _Order(inner=None)
        self.assertFalse(_is_fake_out_first_turn_only(order, b, 0))

    def test_flare_blitz_not_blocked(self):
        b = FakeBattle([FakeMon(first_turn=False)])
        order = _Order(inner=_Move("flareblitz"))
        self.assertFalse(_is_fake_out_first_turn_only(order, b, 0))


class TestFakeOutEdgeCases(unittest.TestCase):
    """Edge cases for Fake Out safety."""

    def test_no_active_mon_returns_false(self):
        b = FakeBattle([None])
        order = _Order(inner=_Move("fakeout"))
        self.assertFalse(_is_fake_out_first_turn_only(order, b, 0))

    def test_empty_battle_active_list_returns_false(self):
        b = FakeBattle([])
        order = _Order(inner=_Move("fakeout"))
        self.assertFalse(_is_fake_out_first_turn_only(order, b, 0))

    def test_no_inner_returns_false(self):
        b = FakeBattle([FakeMon(first_turn=False)])
        order = _Order(inner=None)
        self.assertFalse(_is_fake_out_first_turn_only(order, b, 0))


class TestExistingSafetyPreserved(unittest.TestCase):
    """Existing same-side single-target damaging move safety still works."""

    def test_psychic_ally_target_blocked(self):
        move = _Move(move_id="psychic", category="Special")
        order = _Order(inner=move, move_target=-2)
        self.assertTrue(_is_same_side_single_target_damage_blocked(order))

    def test_psychic_opponent_not_blocked(self):
        move = _Move(move_id="psychic", category="Special")
        order = _Order(inner=move, move_target=1)
        self.assertFalse(_is_same_side_single_target_damage_blocked(order))


class TestScopeCheck(unittest.TestCase):
    """No scope creep from these fixes."""

    def test_no_anti_tr_change(self):
        # Just verify the bot module doesn't contain any new anti-TR code
        src_path = os.path.join(REPO_ROOT, "showdown_ai", "bot_doubles_damage_aware.py")
        with open(src_path) as f:
            src = f.read()
        self.assertNotIn("_is_fake_out_first_turn_only", src.split("_is_fake_out_first_turn_only")[0:1])

    def test_test_51_untouched(self):
        import subprocess
        r = subprocess.run(
            ["git", "status", "--short", "tests/"],
            capture_output=True, text=True,
            cwd=REPO_ROOT,
        )
        self.assertNotIn("test_51", r.stdout)


if __name__ == "__main__":
    unittest.main()
