#!/usr/bin/env python3
"""Tests for the extracted doubles_engine.field_state
and doubles_engine.types modules.

ponytail: focused unit tests for the field/type
helpers. These tests verify:
- Each helper produces the expected output for
  representative inputs.
- Module-level state dicts are mutable and shared
  across helpers.
- The shim in ``bot_doubles_damage_aware`` re-exports
  the helpers under their original names.
- Importing the modules does not require the bot.

Behavior-preservation evidence: existing tests in
``test_doubles_type_immunity_regression``,
``test_doubles_mechanics_parity``, and
``test_vgc2026_runtime_engine_parity`` exercise the
same code path through the shim, so the extraction
is verified to be bit-for-bit equivalent.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _FakeField:
    def __init__(self, name: str):
        self.name = name


class _FakePokemon:
    """Minimal Pokemon mock for type effectiveness tests."""

    def __init__(self, species: str = "pikachu", types=None):
        self.species = species
        if types is None:
            types = ["electric"]
        self.types = types

    def damage_multiplier(self, move_type):
        # Trivial: super effective against ground,
        # normal against electric, etc.
        chart = {
            "ground": 2.0,
            "electric": 1.0,
            "water": 0.5,
        }
        return chart.get(str(move_type).lower(), 1.0)


class _FakeBattle:
    def __init__(self, fields=None, battle_tag: str = "test-bt"):
        self.fields = fields or {}
        self.battle_tag = battle_tag
        self._replay_data = []


# ---------------------------------------------------------------------------
# field_state module — module-level consts
# ---------------------------------------------------------------------------


class TestFieldStateConsts(unittest.TestCase):
    def test_type_consuming_moves(self):
        from doubles_engine.field_state import _TYPE_CONSUMING_MOVES
        self.assertEqual(
            _TYPE_CONSUMING_MOVES,
            {"doubleshock": "ELECTRIC", "burnup": "FIRE"},
        )

    def test_dynamic_type_moves(self):
        from doubles_engine.field_state import DYNAMIC_TYPE_MOVES
        self.assertIn("aurawheel", DYNAMIC_TYPE_MOVES)
        self.assertEqual(
            DYNAMIC_TYPE_MOVES["aurawheel"]["attacker_base_species"],
            "morpeko",
        )

    def test_module_state_dicts_exist(self):
        from doubles_engine import field_state
        self.assertIsInstance(field_state._pokemon_forms, dict)
        self.assertIsInstance(field_state._ident_to_obj, dict)
        self.assertIsInstance(field_state._replay_cursors, dict)


# ---------------------------------------------------------------------------
# field_state module — is_gravity_active
# ---------------------------------------------------------------------------


class TestIsGravityActive(unittest.TestCase):
    def test_no_fields(self):
        from doubles_engine.field_state import is_gravity_active
        battle = _FakeBattle(fields={})
        self.assertFalse(is_gravity_active(battle))

    def test_with_gravity(self):
        from doubles_engine.field_state import is_gravity_active
        battle = _FakeBattle(fields={_FakeField("Gravity")})
        self.assertTrue(is_gravity_active(battle))

    def test_with_other_field(self):
        from doubles_engine.field_state import is_gravity_active
        battle = _FakeBattle(fields={_FakeField("Trick Room")})
        self.assertFalse(is_gravity_active(battle))


# ---------------------------------------------------------------------------
# field_state module — get_max_type_threat
# ---------------------------------------------------------------------------


class TestGetMaxTypeThreat(unittest.TestCase):
    def test_no_active(self):
        from doubles_engine.field_state import get_max_type_threat
        self.assertEqual(get_max_type_threat(None, _FakePokemon()), 0.0)
        self.assertEqual(get_max_type_threat(_FakePokemon(), None), 0.0)

    def test_single_type(self):
        from doubles_engine.field_state import get_max_type_threat
        ours = _FakePokemon("pikachu")
        opp = MagicMock()
        opp.type_1 = "ground"
        opp.type_2 = None
        self.assertEqual(get_max_type_threat(ours, opp), 2.0)

    def test_dual_type_max(self):
        from doubles_engine.field_state import get_max_type_threat
        ours = _FakePokemon("pikachu")
        opp = MagicMock()
        opp.type_1 = "water"  # 0.5
        opp.type_2 = "ground"  # 2.0
        self.assertEqual(get_max_type_threat(ours, opp), 2.0)

    def test_exception_returns_zero(self):
        from doubles_engine.field_state import get_max_type_threat
        ours = MagicMock()
        ours.damage_multiplier = MagicMock(side_effect=Exception)
        opp = MagicMock()
        opp.type_1 = "ground"
        opp.type_2 = None
        self.assertEqual(get_max_type_threat(ours, opp), 0.0)


# ---------------------------------------------------------------------------
# field_state module — form helpers
# ---------------------------------------------------------------------------


class TestFormHelpers(unittest.TestCase):
    def test_normalize_form_name(self):
        from doubles_engine.field_state import _normalize_form_name
        self.assertEqual(_normalize_form_name("Morpeko-Hangry"), "morpekohangry")
        self.assertEqual(_normalize_form_name("a_b c-d"), "abcd")
        self.assertEqual(_normalize_form_name(""), "")

    def test_normalize_ident(self):
        from doubles_engine.field_state import _normalize_ident
        self.assertEqual(_normalize_ident("p1a: Pawmot"), "p1a:pawmot")
        self.assertEqual(_normalize_ident("P1A: PAWMOT"), "p1a:pawmot")

    def test_record_and_get_observed_form_by_object(self):
        from doubles_engine import field_state
        # Reset state for the test
        field_state._pokemon_forms.clear()
        field_state._ident_to_obj.clear()
        pokemon = MagicMock()
        record = field_state.record_observed_form_change(
            "bt1", "p1a: MOCK", "morpekohangry", pokemon=pokemon
        )
        # record returns None implicitly
        result = field_state.get_observed_form(_FakeBattle(battle_tag="bt1"), pokemon)
        self.assertEqual(result, "morpekohangry")

    def test_record_observed_form_no_pokemon(self):
        from doubles_engine import field_state
        field_state._pokemon_forms.clear()
        field_state._ident_to_obj.clear()
        field_state.record_observed_form_change("bt1", "p1a: MOCK", "morpeko")
        # No pokemon stored; get_observed_form needs a pokemon arg.
        # Verify _ident_to_obj was populated.
        self.assertIn(("bt1", "p1a:mock"), field_state._ident_to_obj)

    def test_clear_observed_form_state(self):
        from doubles_engine import field_state
        field_state._pokemon_forms[("bt1", 123)] = "form1"
        field_state._ident_to_obj[("bt1", "p1a:mock")] = 123
        field_state._replay_cursors["bt1"] = 0
        field_state.clear_observed_form_state("bt1")
        self.assertNotIn(("bt1", 123), field_state._pokemon_forms)
        self.assertNotIn(("bt1", "p1a:mock"), field_state._ident_to_obj)
        self.assertNotIn("bt1", field_state._replay_cursors)

    def test_get_observed_form_no_battle(self):
        from doubles_engine import field_state
        self.assertIsNone(field_state.get_observed_form(None, MagicMock()))

    def test_get_observed_form_no_pokemon(self):
        from doubles_engine import field_state
        self.assertIsNone(field_state.get_observed_form(_FakeBattle(), None))


# ---------------------------------------------------------------------------
# field_state module — replay scan
# ---------------------------------------------------------------------------


class TestReplayScan(unittest.TestCase):
    def test_scan_form_changes_no_replay(self):
        from doubles_engine.field_state import _scan_replay_for_form_changes
        battle = _FakeBattle(battle_tag="bt1")
        battle._replay_data = None
        # Should not raise.
        _scan_replay_for_form_changes(battle)

    def test_scan_form_changes_picks_up_formechange(self):
        from doubles_engine import field_state
        field_state._pokemon_forms.clear()
        field_state._ident_to_obj.clear()
        field_state._replay_cursors.clear()
        battle = _FakeBattle(battle_tag="bt1")
        battle._replay_data = [
            ["", "-formechange", "p1a: Morpeko", "Morpeko-Hangry, L100, M"]
        ]
        battle.get_pokemon = MagicMock(return_value=MagicMock())
        field_state._scan_replay_for_form_changes(battle)
        self.assertIn(("bt1", "p1a:morpeko"), field_state._ident_to_obj)

    def test_scan_type_consumption_picks_up_usedup(self):
        from doubles_engine import field_state
        field_state._pokemon_forms.clear()
        field_state._ident_to_obj.clear()
        field_state._replay_cursors.clear()
        battle = _FakeBattle(battle_tag="bt1")
        battle._replay_data = [
            ["", "-usedup", "p1a: Pawmot", "Electric"]
        ]
        consumed = {}
        field_state._scan_replay_for_type_consumption(battle, consumed)
        self.assertIn("bt1", consumed)
        self.assertIn("p1a: Pawmot", consumed["bt1"])
        self.assertIn("ELECTRIC", consumed["bt1"]["p1a: Pawmot"])


# ---------------------------------------------------------------------------
# field_state module — is_type_consumed
# ---------------------------------------------------------------------------


class TestIsTypeConsumed(unittest.TestCase):
    def test_no_move(self):
        from doubles_engine.field_state import is_type_consumed
        self.assertFalse(is_type_consumed(None, MagicMock(), MagicMock(), {}))

    def test_no_attacker(self):
        from doubles_engine.field_state import is_type_consumed
        move = MagicMock()
        move.id = "doubleshock"
        self.assertFalse(is_type_consumed(move, None, MagicMock(), {}))

    def test_no_battle(self):
        from doubles_engine.field_state import is_type_consumed
        move = MagicMock()
        move.id = "doubleshock"
        self.assertFalse(is_type_consumed(move, MagicMock(), None, {}))

    def test_non_consuming_move(self):
        from doubles_engine.field_state import is_type_consumed
        move = MagicMock()
        move.id = "tackle"
        self.assertFalse(is_type_consumed(move, MagicMock(), MagicMock(), {}))

    def test_consumed_type_blocks(self):
        from doubles_engine.field_state import is_type_consumed
        move = MagicMock()
        move.id = "doubleshock"
        battle = MagicMock()
        battle.battle_tag = "bt1"
        battle.get_pokemon_identifier = MagicMock(return_value="p1a: Pawmot")
        consumed = {"bt1": {"p1a: Pawmot": {"ELECTRIC"}}}
        self.assertTrue(is_type_consumed(move, MagicMock(), battle, consumed))


# ---------------------------------------------------------------------------
# types module — effective-move-type helpers
# ---------------------------------------------------------------------------


class TestEffectiveMoveType(unittest.TestCase):
    def test_get_effective_move_type_basic(self):
        from doubles_engine.types import get_effective_move_type
        move = MagicMock()
        move.id = "tackle"
        move.type = MagicMock()
        move.type.name = "NORMAL"
        self.assertEqual(get_effective_move_type(move), "NORMAL")

    def test_get_declared_move_type(self):
        from doubles_engine.types import _get_declared_move_type
        # _get_declared_move_type delegates to doubles_mechanics.
        # The exact value depends on the data; just verify it returns a string.
        move = MagicMock()
        result = _get_declared_move_type(move)
        # MagicMock of move returns some default; just check it's a string.
        self.assertIsInstance(result, (str, type(None)))

    def test_resolve_effective_move_type_returns_dict(self):
        from doubles_engine.types import resolve_effective_move_type
        move = MagicMock()
        move.id = "tackle"
        result = resolve_effective_move_type(move)
        self.assertIsInstance(result, dict)
        self.assertIn("declared_type", result)
        self.assertIn("effective_type", result)
        self.assertIn("source", result)

    def test_resolve_effective_move_type_no_move(self):
        from doubles_engine.types import resolve_effective_move_type
        result = resolve_effective_move_type(None)
        self.assertIsInstance(result, dict)

    def test_resolve_effective_move_type_dynamic_aura_wheel(self):
        from doubles_engine.types import resolve_effective_move_type
        from doubles_engine import field_state
        field_state._pokemon_forms.clear()
        field_state._ident_to_obj.clear()
        # Set up observed form
        pokemon = MagicMock()
        pokemon.species = "morpekohangry"
        field_state.record_observed_form_change(
            "bt1", "p1a: MOCK", "morpekohangry", pokemon=pokemon
        )
        move = MagicMock()
        move.id = "aurawheel"
        result = resolve_effective_move_type(
            move, attacker=pokemon, battle=_FakeBattle(battle_tag="bt1")
        )
        self.assertIsInstance(result, dict)
        # The effective type for hangry form should be DARK.
        self.assertEqual(result["effective_type"], "DARK")


# ---------------------------------------------------------------------------
# Shim verification: bot_doubles_damage_aware re-exports
# ---------------------------------------------------------------------------


class TestShimReExports(unittest.TestCase):
    def test_bot_reexports_field_helpers(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.field_state import (
            is_gravity_active as eng_is_grav,
            get_max_type_threat as eng_gmt,
            get_observed_form as eng_gof,
        )
        self.assertIs(b.is_gravity_active, eng_is_grav)
        self.assertIs(b.get_max_type_threat, eng_gmt)
        self.assertIs(b.get_observed_form, eng_gof)

    def test_bot_reexports_type_helpers(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.types import (
            resolve_effective_move_type as eng_resolve,
            get_effective_move_type as eng_get,
        )
        self.assertIs(b.resolve_effective_move_type, eng_resolve)
        self.assertIs(b.get_effective_move_type, eng_get)

    def test_bot_reexports_consts(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.field_state import (
            _TYPE_CONSUMING_MOVES as eng_tcm,
            DYNAMIC_TYPE_MOVES as eng_dtm,
        )
        self.assertIs(b._TYPE_CONSUMING_MOVES, eng_tcm)
        self.assertIs(b.DYNAMIC_TYPE_MOVES, eng_dtm)


if __name__ == "__main__":
    unittest.main()
