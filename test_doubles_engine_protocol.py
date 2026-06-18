#!/usr/bin/env python3
"""Tests for the extracted doubles_engine.protocol
and doubles_engine.type_absorb modules.

ponytail: focused unit tests for the protocol and
type-absorb helpers. These tests verify:
- Each helper produces the expected output for
  representative inputs.
- The shim in ``bot_doubles_damage_aware`` re-exports
  the helpers under their original names.
- The ``_ALLOWED_DYNAMIC_ABSORB_REASONS`` allowlist
  is preserved.

Behavior-preservation evidence: existing tests in
``test_doubles_ability_hard_safety`` and
``test_vgc2026_runtime_engine_parity`` exercise the
same code path through the shim.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _FakePokemon:
    def __init__(self, species: str = "pokemon"):
        self.species = species
        self.ident = f"p1a: {species}"


class _FakeBattle:
    def __init__(self, replay_data=None, battle_tag: str = "test-bt"):
        self._replay_data = replay_data or []
        self.battle_tag = battle_tag
        self.turn = 0


# ---------------------------------------------------------------------------
# protocol — _normalize_protocol_token
# ---------------------------------------------------------------------------


class TestNormalizeProtocolToken(unittest.TestCase):
    def test_basic(self):
        from doubles_engine.protocol import _normalize_protocol_token
        self.assertEqual(
            _normalize_protocol_token("Storm Drain"),
            "stormdrain",
        )
        self.assertEqual(
            _normalize_protocol_token("STORM-DRAIN"),
            "stormdrain",
        )
        self.assertEqual(
            _normalize_protocol_token("p1a: Pikachu"),
            "p1a:pikachu",
        )

    def test_none(self):
        from doubles_engine.protocol import _normalize_protocol_token
        self.assertEqual(_normalize_protocol_token(None), "")

    def test_empty(self):
        from doubles_engine.protocol import _normalize_protocol_token
        self.assertEqual(_normalize_protocol_token(""), "")


# ---------------------------------------------------------------------------
# protocol — _get_pokemon_by_ident
# ---------------------------------------------------------------------------


class TestGetPokemonByIdent(unittest.TestCase):
    def test_no_battle(self):
        from doubles_engine.protocol import _get_pokemon_by_ident
        self.assertIsNone(_get_pokemon_by_ident(None, "p1a: X"))

    def test_no_ident(self):
        from doubles_engine.protocol import _get_pokemon_by_ident
        self.assertIsNone(_get_pokemon_by_ident(_FakeBattle(), ""))

    def test_success(self):
        from doubles_engine.protocol import _get_pokemon_by_ident
        pokemon = _FakePokemon("Pikachu")
        battle = MagicMock()
        battle.get_pokemon = MagicMock(return_value=pokemon)
        result = _get_pokemon_by_ident(battle, "p1a: Pikachu")
        self.assertIs(result, pokemon)

    def test_exception(self):
        from doubles_engine.protocol import _get_pokemon_by_ident
        battle = MagicMock()
        battle.get_pokemon = MagicMock(side_effect=Exception("boom"))
        self.assertIsNone(_get_pokemon_by_ident(battle, "p1a: X"))


# ---------------------------------------------------------------------------
# protocol — _get_battle_pokemon_identity
# ---------------------------------------------------------------------------


class TestGetBattlePokemonIdentity(unittest.TestCase):
    def test_no_battle(self):
        from doubles_engine.protocol import _get_battle_pokemon_identity
        self.assertEqual(_get_battle_pokemon_identity(None, _FakePokemon()), "")

    def test_no_pokemon(self):
        from doubles_engine.protocol import _get_battle_pokemon_identity
        self.assertEqual(_get_battle_pokemon_identity(_FakeBattle(), None), "")

    def test_team_match(self):
        from doubles_engine.protocol import _get_battle_pokemon_identity
        pokemon = _FakePokemon("Pikachu")
        battle = MagicMock()
        battle.team = {"p1a: Pikachu": pokemon}
        battle.opponent_team = {}
        battle._team = {}
        battle._opponent_team = {}
        self.assertEqual(
            _get_battle_pokemon_identity(battle, pokemon),
            "p1a: Pikachu",
        )

    def test_opponent_team_match(self):
        from doubles_engine.protocol import _get_battle_pokemon_identity
        pokemon = _FakePokemon("Gyarados")
        battle = MagicMock()
        battle.team = {}
        battle.opponent_team = {"p2a: Gyarados": pokemon}
        battle._team = {}
        battle._opponent_team = {}
        self.assertEqual(
            _get_battle_pokemon_identity(battle, pokemon),
            "p2a: Gyarados",
        )

    def test_no_match(self):
        from doubles_engine.protocol import _get_battle_pokemon_identity
        pokemon = _FakePokemon("Pikachu")
        battle = MagicMock()
        battle.team = {}
        battle.opponent_team = {}
        battle._team = {}
        battle._opponent_team = {}
        self.assertEqual(_get_battle_pokemon_identity(battle, pokemon), "")


# ---------------------------------------------------------------------------
# protocol — find_protocol_ability_reveal_turn
# ---------------------------------------------------------------------------


class TestFindProtocolAbilityRevealTurn(unittest.TestCase):
    def test_no_battle(self):
        from doubles_engine.protocol import (
            find_protocol_ability_reveal_turn,
        )
        self.assertIsNone(
            find_protocol_ability_reveal_turn(None, _FakePokemon(), "Storm Drain")
        )

    def test_no_target(self):
        from doubles_engine.protocol import (
            find_protocol_ability_reveal_turn,
        )
        self.assertIsNone(
            find_protocol_ability_reveal_turn(_FakeBattle(), None, "Storm Drain")
        )

    def test_no_ability(self):
        from doubles_engine.protocol import (
            find_protocol_ability_reveal_turn,
        )
        self.assertIsNone(
            find_protocol_ability_reveal_turn(_FakeBattle(), _FakePokemon(), "")
        )

    def test_no_replay(self):
        from doubles_engine.protocol import (
            find_protocol_ability_reveal_turn,
        )
        battle = _FakeBattle(replay_data=[])
        self.assertIsNone(
            find_protocol_ability_reveal_turn(battle, _FakePokemon(), "Storm Drain")
        )

    def test_reveal_at_turn_3(self):
        from doubles_engine.protocol import (
            find_protocol_ability_reveal_turn,
        )
        pokemon = _FakePokemon("Pikachu")
        battle = MagicMock()
        battle._replay_data = [
            ["", "turn", 1],
            ["", "turn", 2],
            ["", "turn", 3],
            ["", "-ability", "p1a: Pikachu", "Storm Drain"],
        ]
        battle.turn = 5
        battle.get_pokemon = MagicMock(return_value=pokemon)
        result = find_protocol_ability_reveal_turn(
            battle, pokemon, "Storm Drain"
        )
        self.assertEqual(result, 3)

    def test_no_reveal_for_wrong_pokemon(self):
        from doubles_engine.protocol import (
            find_protocol_ability_reveal_turn,
        )
        pokemon = _FakePokemon("Pikachu")
        other = _FakePokemon("Gyarados")
        battle = MagicMock()
        battle._replay_data = [
            ["", "turn", 1],
            ["", "-ability", "p2a: Gyarados", "Storm Drain"],
        ]
        battle.turn = 5
        battle.get_pokemon = MagicMock(side_effect=lambda ident: other if "Gyarados" in ident else pokemon)
        result = find_protocol_ability_reveal_turn(
            battle, pokemon, "Storm Drain"
        )
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# type_absorb — _ALLOWED_DYNAMIC_ABSORB_REASONS
# ---------------------------------------------------------------------------


class TestAllowedDynamicAbsorbReasons(unittest.TestCase):
    def test_contains_expected(self):
        from doubles_engine.type_absorb import (
            _ALLOWED_DYNAMIC_ABSORB_REASONS,
        )
        expected = {
            "water_into_waterabsorb",
            "water_into_stormdrain",
            "water_into_dryskin",
            "electric_into_voltabsorb",
            "electric_into_motordrive",
            "electric_into_lightningrod",
            "fire_into_flashfire",
            "fire_into_wellbakedbody",
            "grass_into_sapsipper",
        }
        self.assertEqual(_ALLOWED_DYNAMIC_ABSORB_REASONS, expected)

    def test_is_frozenset(self):
        from doubles_engine.type_absorb import (
            _ALLOWED_DYNAMIC_ABSORB_REASONS,
        )
        self.assertIsInstance(_ALLOWED_DYNAMIC_ABSORB_REASONS, frozenset)


# ---------------------------------------------------------------------------
# type_absorb — classify_dynamic_type_absorb_candidates (smoke)
# ---------------------------------------------------------------------------


class TestClassifyDynamicTypeAbsorbCandidates(unittest.TestCase):
    def test_no_attacker(self):
        from doubles_engine.type_absorb import (
            classify_dynamic_type_absorb_candidates,
        )
        result = classify_dynamic_type_absorb_candidates(
            [], None, None, [], MagicMock(), MagicMock(), {}
        )
        self.assertFalse(result["candidate_blocked"])
        self.assertFalse(result["selected"])
        self.assertFalse(result["avoided"])

    def test_no_valid_orders(self):
        from doubles_engine.type_absorb import (
            classify_dynamic_type_absorb_candidates,
        )
        result = classify_dynamic_type_absorb_candidates(
            [], None, _FakePokemon("Pikachu"), [], MagicMock(), MagicMock(), {}
        )
        self.assertFalse(result["candidate_blocked"])


# ---------------------------------------------------------------------------
# Shim verification
# ---------------------------------------------------------------------------


class TestShimReExports(unittest.TestCase):
    def test_bot_reexports_protocol(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.protocol import (
            find_protocol_ability_reveal_turn as eng_fprt,
            _normalize_protocol_token as eng_npt,
        )
        self.assertIs(b.find_protocol_ability_reveal_turn, eng_fprt)
        self.assertIs(b._normalize_protocol_token, eng_npt)

    def test_bot_reexports_type_absorb(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.type_absorb import (
            classify_dynamic_type_absorb_candidates as eng_cdtac,
            _ALLOWED_DYNAMIC_ABSORB_REASONS as eng_adar,
        )
        self.assertIs(b.classify_dynamic_type_absorb_candidates, eng_cdtac)
        self.assertIs(b._ALLOWED_DYNAMIC_ABSORB_REASONS, eng_adar)


if __name__ == "__main__":
    unittest.main()
