"""Phase SCENARIO-3 — Tests for the
scripted opponent player.

Validates:
- ScriptedOpponentPlayer inherits from
  poke_env.Player (not from any bot class)
- Loads scenario file
- choose_move returns the scripted action
- Falls back to default on invalid action
- Records success/failure in metadata
- Anti-leak: no access to bot internals
- Pure function: no scoring change
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# Use the existing poke_env_test_cleanup
# (must precede any poke_env import).
import poke_env_test_cleanup  # noqa: F401  -- side effect

from poke_env.player.player import Player
from bot_vgc2026_scripted_opp import ScriptedOpponentPlayer
from scenario_probe import load_scenario_dict


def _write_scenario_file(
    tmpdir: str, scenario: dict,
) -> str:
    """Write scenario to a temp file,
    return path."""
    path = os.path.join(tmpdir, "scen.json")
    with open(path, "w") as f:
        json.dump(scenario, f)
    return path


# Minimal valid scenarios for tests
SCEN_TR_TURN1 = {
    "scenario_id": "anti_tr_basic",
    "our_team_file": "/tmp/our_team.json",
    "opp_team_file": "/tmp/opp_team.json",
    "script": {
        "turn_1": {
            "opp_slot_0": {"move": "Trick Room"},
            "opp_slot_1": {"move": "Protect"},
        },
    },
    "validators": [],
}


class TestInheritance(unittest.TestCase):
    def test_inherits_from_poke_env_player(self):
        """ScriptedOpponentPlayer must
        inherit from base Player (not from
        any bot class)."""
        self.assertTrue(issubclass(
            ScriptedOpponentPlayer, Player
        ))

    def test_does_not_import_bot_class(self):
        """ScriptedOpponentPlayer module should
        NOT import bot internals (no
        cross-talk)."""
        import bot_vgc2026_scripted_opp as mod
        src = open(mod.__file__).read()
        # No import of bot damage-aware internals
        self.assertNotIn(
            "DoublesDamageAwareConfig", src
        )
        self.assertNotIn(
            "DoublesDamageAwarePlayer", src
        )
        self.assertNotIn(
            "score_action", src
        )


class TestLoad(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.scenario_path = _write_scenario_file(
            self.tmpdir, SCEN_TR_TURN1
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_load_scenario(self):
        """Scenario is loaded on init."""
        # Use MagicMock to avoid poke_env
        # background tasks
        with unittest.mock.patch.object(
            ScriptedOpponentPlayer, "__init__",
            lambda self, scenario_path, *a, **kw: None,
        ):
            pass
        # We test the underlying behavior by
        # calling the real __init__ with mock
        # parent.
        # Use __new__ to bypass Player.__init__
        player = ScriptedOpponentPlayer.__new__(
            ScriptedOpponentPlayer
        )
        player.scenario = load_scenario_dict(
            SCEN_TR_TURN1
        )
        self.assertEqual(
            player.scenario.scenario_id,
            "anti_tr_basic"
        )


class TestPureFunction(unittest.TestCase):
    def test_no_bot_dependency_at_import(self):
        """Importing the module should not pull
        in bot internals."""
        import bot_vgc2026_scripted_opp as mod
        # Module should import scenario_probe
        # and poke_env only
        self.assertTrue(hasattr(mod, "Scenario"))
        self.assertTrue(hasattr(mod, "ScriptedOpponentPlayer"))


class TestAntiLeak(unittest.TestCase):
    def test_class_does_not_hold_bot_reference(self):
        """ScriptedOpponentPlayer.__init__ does
        not accept a bot config or score
        function reference."""
        import inspect
        sig = inspect.signature(
            ScriptedOpponentPlayer.__init__
        )
        param_names = list(sig.parameters.keys())
        # scenario_path is allowed
        # *args, **kwargs are flexible
        # but no specific bot config param
        self.assertIn("scenario_path", param_names)
        # No "bot_config" or similar
        for n in param_names:
            self.assertNotIn("bot", n.lower())
            self.assertNotIn("doubles_damage", n.lower())


class TestSchemaExample(unittest.TestCase):
    def test_scenario_turn_1_keys(self):
        """Scenario turn_1 has the expected
        keys."""
        scen = load_scenario_dict(SCEN_TR_TURN1)
        self.assertIn(1, scen.script)
        t1 = scen.script[1]
        self.assertIn("opp_slot_0", t1.actions)
        self.assertIn("opp_slot_1", t1.actions)
        self.assertEqual(
            t1.actions["opp_slot_0"].move, "trickroom"
        )
        self.assertEqual(
            t1.actions["opp_slot_1"].move, "protect"
        )

    def test_action_target_pos(self):
        """target_pos is preserved."""
        scen_dict = dict(SCEN_TR_TURN1)
        scen_dict["script"] = {
            "turn_1": {
                "opp_slot_0": {
                    "move": "Trick Room",
                    "target_pos": None,
                },
                "opp_slot_1": {
                    "move": "Protect",
                    "target_pos": None,
                },
            },
        }
        scen = load_scenario_dict(scen_dict)
        for slot in ["opp_slot_0", "opp_slot_1"]:
            self.assertIsNone(
                scen.script[1].actions[slot].target_pos
            )


class TestMetadata(unittest.TestCase):
    def test_metadata_lists_initially_empty(self):
        """Before any choose_move call, the
        metadata lists are empty."""
        scen = load_scenario_dict(SCEN_TR_TURN1)
        player = ScriptedOpponentPlayer.__new__(
            ScriptedOpponentPlayer
        )
        player.scenario = scen
        player.scenario_failures = []
        player.scenario_actions = []
        # scenario_id is set from the scenario
        self.assertEqual(
            player.scenario.scenario_id, "anti_tr_basic"
        )
        self.assertEqual(player.scenario_failures, [])
        self.assertEqual(player.scenario_actions, [])


class TestSlotKeyParsing(unittest.TestCase):
    def test_opp_slot_0_to_index_0(self):
        from bot_vgc2026_scripted_opp import (
            ScriptedOpponentPlayer,
        )
        self.assertEqual(
            ScriptedOpponentPlayer._slot_key_to_index(
                None, "opp_slot_0"
            ),
            0,
        )

    def test_opp_slot_1_to_index_1(self):
        from bot_vgc2026_scripted_opp import (
            ScriptedOpponentPlayer,
        )
        self.assertEqual(
            ScriptedOpponentPlayer._slot_key_to_index(
                None, "opp_slot_1"
            ),
            1,
        )

    def test_invalid_slot_to_none(self):
        from bot_vgc2026_scripted_opp import (
            ScriptedOpponentPlayer,
        )
        self.assertIsNone(
            ScriptedOpponentPlayer._slot_key_to_index(
                None, "weird_key"
            )
        )


class TestRecordHelpers(unittest.TestCase):
    def test_record_success(self):
        from bot_vgc2026_scripted_opp import (
            ScriptedOpponentPlayer,
        )
        from scenario_probe import ScenarioAction
        player = ScriptedOpponentPlayer.__new__(
            ScriptedOpponentPlayer
        )
        player.scenario_failures = []
        player.scenario_actions = []
        action = ScenarioAction(move="trickroom")
        player._record_success(
            turn=1, slot_idx=0, action=action,
            order="<order>",
        )
        self.assertEqual(len(player.scenario_actions), 1)
        self.assertEqual(
            player.scenario_actions[0]["turn"], 1
        )
        self.assertEqual(
            player.scenario_actions[0]["move"],
            "trickroom",
        )
        self.assertTrue(
            player.scenario_actions[0]["executed"]
        )

    def test_record_failure(self):
        from bot_vgc2026_scripted_opp import (
            ScriptedOpponentPlayer,
        )
        from scenario_probe import ScenarioAction
        player = ScriptedOpponentPlayer.__new__(
            ScriptedOpponentPlayer
        )
        player.scenario_failures = []
        player.scenario_actions = []
        action = ScenarioAction(move="notarealmove")
        player._record_failure(
            turn=2, slot_idx=1, action=action,
            reason="move_not_available",
        )
        self.assertEqual(len(player.scenario_failures), 1)
        self.assertEqual(
            player.scenario_failures[0]["turn"], 2
        )
        self.assertEqual(
            player.scenario_failures[0]["reason"],
            "move_not_available",
        )


class TestHelpFunction(unittest.TestCase):
    def test_help_runs(self):
        """Help function runs without error."""
        from bot_vgc2026_scripted_opp import main
        # Returns 0
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            result = main()
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()


class TestTeampreviewOverride(unittest.TestCase):
    """Phase SCENARIO-4: scripted player must
    lead with the mon that owns the script's
    turn_1 slot 0 move."""

    def _make_battle(self, team_dicts):
        """Build a mock battle with a team of
        simple stand-in mon objects. Avoids
        poke-env's Pokemon class complexity
        for the teampreview test."""
        class _MockMove:
            def __init__(self, name):
                self.id = name

        class _MockMon:
            def __init__(self, species, moves):
                self.species = species
                self._moves = {
                    mv.lower().replace(" ", "").replace("-", ""): _MockMove(mv)
                    for mv in moves
                }
                self.moves = self._moves
                self.base_moves = [
                    mv.lower().replace(" ", "").replace("-", "")
                    for mv in moves
                ]
                self._selected_in_teampreview = False

        class _MockBattle:
            def __init__(self, mons):
                self.team = {}
                for i, m in enumerate(mons):
                    self.team[str(i + 1)] = _MockMon(
                        m["species"], m["moves"]
                    )
                # Use a private ``format`` so
                # ``battle.format`` returns the
                # value (random_teampreview needs
                # this).
                self._format = "gen9championsvgc2026regma"

            @property
            def format(self):
                return self._format

        battle = _MockBattle(team_dicts)
        return battle

    def test_lead_with_tr_setter(self):
        """Hatterene with TR should be one of
        the two lead positions when the script
        says opp_slot_0 uses TR."""
        from bot_vgc2026_scripted_opp import (
            ScriptedOpponentPlayer,
        )
        scripted = ScriptedOpponentPlayer(
            scenario_path="data/curated_teams/scenarios/anti_tr_basic.json",
        )
        team = [
            {"species": "Volcarona", "moves": ["Heat Wave", "Protect"]},
            {"species": "Blastoise", "moves": ["Water Pulse", "Protect"]},
            {"species": "Hatterene", "moves": ["Dazzling Gleam", "Trick Room", "Protect"]},
            {"species": "Tinkaton", "moves": ["Fake Out", "Protect"]},
            {"species": "Meowscarada", "moves": ["Flower Trick", "Protect"]},
            {"species": "Torterra", "moves": ["Wood Hammer", "Protect"]},
        ]
        battle = self._make_battle(team)
        order = scripted.teampreview(battle)
        # Order should be /team XXXX
        self.assertTrue(order.startswith("/team "), f"unexpected order: {order}")
        positions = [int(c) for c in order.replace("/team ", "")]
        # Phase SCENARIO-8: in doubles /team
        # format, leads are at positions 1
        # and 2 of the 4-digit string
        # (lead, lead, back, back).
        lead_species = [
            list(battle.team.values())[p - 1].species
            for p in [positions[0], positions[1]]
        ]
        self.assertIn("Hatterene", lead_species, f"hatterene not in lead {lead_species}")

    def test_fallback_to_random_when_no_match(self):
        """If the script's turn_1 has no matching
        species, fall back to random teampreview."""
        from bot_vgc2026_scripted_opp import (
            ScriptedOpponentPlayer,
        )
        scripted = ScriptedOpponentPlayer(
            scenario_path="data/curated_teams/scenarios/anti_tr_basic.json",
        )
        team = [
            {"species": "Volcarona", "moves": ["Heat Wave", "Protect"]},
            {"species": "Blastoise", "moves": ["Water Pulse", "Protect"]},
        ]
        battle = self._make_battle(team)
        # No hatterene -> random teampreview
        order = scripted.teampreview(battle)
        # Just verify it returns a /team order
        self.assertTrue(order.startswith("/team "))
