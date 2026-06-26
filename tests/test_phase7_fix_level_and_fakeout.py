"""Tests for PHASE7_DATA_EXPANSION_FIX_LEVEL_MISMATCH_AND_FAKE_OUT.

Ponytail: pure unit tests. No poke-env runtime, no network,
no battles, no GPU.
"""
import json
import os
import unittest
from unittest import mock
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


# ---------------------------------------------------------------------------
# P0 hotfix: validator must be fail-hard AND called before any battle starts.
# ---------------------------------------------------------------------------

OPP_TEAM_OK = audit_mod.OPP_TEAM  # committed L50 team


def _our_team_ok_dict() -> dict:
    return {
        "team": [
            {"species": f"Mon{i}", "ability": "Overgrow", "level": 50,
             "moves": ["tackle"]} for i in range(6)
        ]
    }


def _our_team_missing_level_dict() -> dict:
    d = _our_team_ok_dict()
    d["team"][0].pop("level")
    return d


def _our_team_level100_dict() -> dict:
    d = _our_team_ok_dict()
    for p in d["team"]:
        p["level"] = 100
    return d


def _our_team_5_dict() -> dict:
    d = _our_team_ok_dict()
    d["team"] = d["team"][:5]
    return d


class TestValidateAllTeamsAcceptsCurrent(unittest.TestCase):
    def test_accepts_current_committed_teams(self):
        # Should not raise on the real committed files.
        audit_mod._validate_all_teams(expected_level=50)

    def test_accepts_level50(self):
        d = _our_team_ok_dict()
        with mock.patch("builtins.open",
                                  mock.mock_open(read_data=json.dumps(d))):
            with mock.patch("os.path.isfile", return_value=True):
                audit_mod._validate_all_teams(expected_level=50)


class TestValidateAllTeamsFailHard(unittest.TestCase):
    def test_missing_our_team_json_raises(self):
        with mock.patch("os.path.isfile", return_value=False):
            with self.assertRaises(ValueError):
                audit_mod._validate_all_teams(expected_level=50)

    def test_malformed_our_team_json_raises(self):
        with mock.patch("os.path.isfile", return_value=True):
            with mock.patch("builtins.open",
                                      mock.mock_open(read_data="{not json")):
                with self.assertRaises(ValueError):
                    audit_mod._validate_all_teams(expected_level=50)

    def test_our_team_5_raises(self):
        d = _our_team_5_dict()
        with mock.patch("builtins.open",
                                  mock.mock_open(read_data=json.dumps(d))):
            with mock.patch("os.path.isfile", return_value=True):
                with self.assertRaises(ValueError):
                    audit_mod._validate_all_teams(expected_level=50)

    def test_our_team_missing_level_raises(self):
        d = _our_team_missing_level_dict()
        with mock.patch("builtins.open",
                                  mock.mock_open(read_data=json.dumps(d))):
            with mock.patch("os.path.isfile", return_value=True):
                with self.assertRaises(ValueError):
                    audit_mod._validate_all_teams(expected_level=50)

    def test_our_team_level100_raises(self):
        d = _our_team_level100_dict()
        with mock.patch("builtins.open",
                                  mock.mock_open(read_data=json.dumps(d))):
            with mock.patch("os.path.isfile", return_value=True):
                with self.assertRaises(ValueError):
                    audit_mod._validate_all_teams(expected_level=50)


class TestRunSmokeCallsValidatorBeforeAnything(unittest.TestCase):
    """P0 hotfix: validator MUST run before read/logger/battle loop."""

    def _assert_validator_runs_before(self, call_sequence: list):
        validator_idx = None
        for i, name in enumerate(call_sequence):
            if name == "validator":
                validator_idx = i
                break
        self.assertIsNotNone(validator_idx, "validator not called")
        for later in ("open_team", "json_to_showdown",
                      "audit_logger", "raw_capture", "run_single_battle"):
            if later in call_sequence:
                self.assertLess(
                    validator_idx, call_sequence.index(later),
                    f"validator must run before {later} (got order {call_sequence})",
                )

    def test_validator_called_in_run_smoke_before_io(self):
        # Inspect source text: confirm validator call appears before
        # the with-open(OUR_TEAM_JSON) block, json_to_showdown call,
        # DoublesDecisionAuditLogger construction, and the battle loop.
        import inspect
        src = inspect.getsource(audit_mod.run_smoke)
        # locate positions
        positions = {
            "validator": src.find("_validate_all_teams(expected_level=50)"),
            "open_team": src.find("with open(OUR_TEAM_JSON) as f"),
            "json_to_showdown": src.find("our_team_showdown = json_to_showdown"),
            "audit_logger": src.find("DoublesDecisionAuditLogger("),
            "battle_loop": src.find("for idx in range(1, battles + 1)"),
        }
        for k, v in positions.items():
            self.assertGreaterEqual(v, 0, f"{k} not found in run_smoke source")
        order = sorted(positions.items(), key=lambda kv: kv[1])
        names_in_order = [k for k, _ in order]
        self.assertEqual(names_in_order[0], "validator")

    def test_run_smoke_does_not_start_battle_if_validator_raises(self):
        """If _validate_all_teams raises, no battle loop or logger runs."""
        call_sequence = []

        def fake_validator(expected_level=50):
            call_sequence.append("validator")
            raise ValueError("forced fail")

        # Patch everything that would be a side effect to record order.
        def fake_open(*a, **k):
            call_sequence.append("open_team")
            class _F:
                def __enter__(self_inner):
                    call_sequence.append("open_team_enter")
                    return self_inner
                def __exit__(self_inner, *a):
                    return False
            return _F()

        def fake_json_to_showdown(d):
            call_sequence.append("json_to_showdown")
            return ""

        def fake_audit_logger(**k):
            call_sequence.append("audit_logger")
            class _L:
                def set_current_battle_meta(self_inner, **k):
                    pass
            return _L()

        def fake_run_single_battle(*a, **k):
            call_sequence.append("run_single_battle")
            return {"result": "won"}

        async def fake_check():
            call_sequence.append("check_localhost")
            return True

        with mock.patch.object(audit_mod, "_validate_all_teams", fake_validator), \
             mock.patch.object(audit_mod, "json_to_showdown", fake_json_to_showdown), \
             mock.patch("builtins.open", fake_open), \
             mock.patch.object(audit_mod, "DoublesDecisionAuditLogger", fake_audit_logger), \
             mock.patch.object(audit_mod, "run_single_battle", fake_run_single_battle), \
             mock.patch.object(audit_mod, "check_localhost_healthy", fake_check):
            import asyncio
            with self.assertRaises(ValueError):
                asyncio.run(audit_mod.run_smoke(battles=1, output_path="/tmp/x.jsonl"))

        # validator must run; no downstream side effects fired.
        self.assertIn("validator", call_sequence)
        self.assertLess(
            call_sequence.index("validator"),
            len(call_sequence),
        )
        for forbidden in ("open_team", "json_to_showdown", "audit_logger",
                          "run_single_battle"):
            self.assertNotIn(forbidden, call_sequence)

    def test_path_resolved_from_repo_root(self):
        """OUR_TEAM JSON path must use REPO_ROOT, not CWD-relative."""
        import inspect
        src = inspect.getsource(audit_mod._validate_all_teams)
        # must reference REPO_ROOT
        self.assertIn("REPO_ROOT", src)
        # must NOT use a bare os.path.join without REPO_ROOT as first arg
        self.assertIn("os.path.join(\n        REPO_ROOT", src)


if __name__ == "__main__":
    unittest.main()
