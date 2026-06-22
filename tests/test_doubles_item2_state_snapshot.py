"""Phase ITEM-2 — Tests for the state_snapshot
enhancement that adds ability, item, and
revealed-moves fields.

Validates that the new fields are populated
correctly given a fake Battle with ability,
item, and moves on the active Pokemon.

Per AGENTS.md: only visible data is captured.
Hidden info is not exposed.
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

from doubles_decision_audit_logger import (
    DoublesDecisionAuditLogger,
)


class _FakeAbility:
    def __init__(self, name):
        self.name = name


class _FakeItem:
    def __init__(self, name):
        self.name = name


class _FakeMove:
    def __init__(self, mid):
        self.id = mid
        self.name = mid


class _FakePokemon:
    """Minimal stand-in for poke_env Pokemon that
    supports ability, item, and revealed moves."""

    def __init__(
        self, species=None, hp_fraction=None, types=None,
        ability=None, item=None, moves=None,
    ):
        self.species = species
        self._hp_fraction = hp_fraction
        self._types = types or []
        self.ability = ability
        self.item = item
        self.moves = moves or []

    @property
    def current_hp_fraction(self):
        return self._hp_fraction

    @property
    def types(self):
        return self._types


class _FakeType:
    def __init__(self, name):
        self.name = name


class _FakeBattle:
    def __init__(self, our=None, opp=None, weather=None,
                 fields=None, side_conditions=None,
                 opponent_side_conditions=None):
        self.turn = 3
        self.active_pokemon = our or [None, None]
        self.opponent_active_pokemon = opp or [None, None]
        self.weather = weather if weather is not None else {}
        self.fields = fields if fields is not None else {}
        self.side_conditions = (
            side_conditions if side_conditions is not None else {}
        )
        self.opponent_side_conditions = (
            opponent_side_conditions
            if opponent_side_conditions is not None else {}
        )


class TestStateSnapshotAbility(unittest.TestCase):
    """state_snapshot captures ability name per slot."""

    def test_ability_known(self):
        pkmn = _FakePokemon(
            species="garchomp", hp_fraction=1.0,
            ability=_FakeAbility("Rough Skin"),
        )
        battle = _FakeBattle(our=[pkmn, None])
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, battle_tag="bt"
        )
        self.assertEqual(snap["our_active_ability"][0], "roughskin")
        self.assertIsNone(snap["our_active_ability"][1])

    def test_ability_unknown_returns_none(self):
        pkmn = _FakePokemon(
            species="garchomp", hp_fraction=1.0,
            ability=None,  # not yet revealed
        )
        battle = _FakeBattle(our=[pkmn, None])
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, battle_tag="bt"
        )
        self.assertIsNone(snap["our_active_ability"][0])

    def test_ability_name_normalized(self):
        """Spaces and punctuation stripped, lowercase."""
        pkmn = _FakePokemon(
            species="garchomp", hp_fraction=1.0,
            ability=_FakeAbility("Rough Skin"),
        )
        battle = _FakeBattle(our=[pkmn, None])
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, battle_tag="bt"
        )
        ab = snap["our_active_ability"][0]
        self.assertNotIn(" ", ab)
        self.assertNotIn("_", ab)
        self.assertEqual(ab, ab.lower())


class TestStateSnapshotItem(unittest.TestCase):
    """state_snapshot captures item name per slot."""

    def test_item_known(self):
        pkmn = _FakePokemon(
            species="garchomp", hp_fraction=1.0,
            item=_FakeItem("Choice Scarf"),
        )
        battle = _FakeBattle(our=[pkmn, None])
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, battle_tag="bt"
        )
        self.assertEqual(snap["our_active_item"][0], "choicescarf")

    def test_item_no_item_returns_none(self):
        pkmn = _FakePokemon(
            species="garchomp", hp_fraction=1.0,
            item=None,  # no held item
        )
        battle = _FakeBattle(our=[pkmn, None])
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, battle_tag="bt"
        )
        self.assertIsNone(snap["our_active_item"][0])

    def test_item_noitem_keyword_returns_none(self):
        """Common 'No Item' string should be None, not 'noitem'."""
        pkmn = _FakePokemon(
            species="garchomp", hp_fraction=1.0,
            item=_FakeItem("No Item"),
        )
        battle = _FakeBattle(our=[pkmn, None])
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, battle_tag="bt"
        )
        self.assertIsNone(snap["our_active_item"][0])

    def test_item_focussash(self):
        pkmn = _FakePokemon(
            species="garchomp", hp_fraction=1.0,
            item=_FakeItem("Focus Sash"),
        )
        battle = _FakeBattle(our=[pkmn, None])
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, battle_tag="bt"
        )
        self.assertEqual(snap["our_active_item"][0], "focussash")


class TestStateSnapshotMovesRevealed(unittest.TestCase):
    """state_snapshot captures revealed move IDs per slot."""

    def test_moves_revealed(self):
        pkmn = _FakePokemon(
            species="garchomp", hp_fraction=1.0,
            moves=[_FakeMove("earthquake"), _FakeMove("outrage")],
        )
        battle = _FakeBattle(our=[pkmn, None])
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, battle_tag="bt"
        )
        self.assertEqual(
            snap["our_active_moves_revealed"][0],
            ["earthquake", "outrage"],
        )
        self.assertEqual(
            snap["our_active_moves_revealed"][1], []
        )

    def test_no_moves_returns_empty(self):
        pkmn = _FakePokemon(
            species="garchomp", hp_fraction=1.0,
            moves=[],
        )
        battle = _FakeBattle(our=[pkmn, None])
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, battle_tag="bt"
        )
        self.assertEqual(snap["our_active_moves_revealed"][0], [])

    def test_opp_slot_also_captures(self):
        opp = _FakePokemon(
            species="rotomwash", hp_fraction=1.0,
            ability=_FakeAbility("Levitate"),
            item=_FakeItem("Leftovers"),
            moves=[_FakeMove("hydropump")],
        )
        battle = _FakeBattle(opp=[opp, None])
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, battle_tag="bt"
        )
        self.assertEqual(snap["opp_active_ability"][0], "levitate")
        self.assertEqual(snap["opp_active_item"][0], "leftovers")
        self.assertEqual(
            snap["opp_active_moves_revealed"][0], ["hydropump"]
        )


class TestStateSnapshotBackCompat(unittest.TestCase):
    """Existing keys still present (no regression)."""

    def test_existing_keys_present(self):
        pkmn = _FakePokemon(
            species="garchomp", hp_fraction=1.0,
            types=[_FakeType("DRAGON"), _FakeType("GROUND")],
        )
        battle = _FakeBattle(our=[pkmn, None])
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, battle_tag="bt"
        )
        # Existing keys
        self.assertIn("our_active_species", snap)
        self.assertIn("opp_active_species", snap)
        self.assertIn("our_active_hp_fraction", snap)
        self.assertIn("opp_active_hp_fraction", snap)
        self.assertIn("our_active_types", snap)
        self.assertIn("opp_active_types", snap)
        # New keys
        self.assertIn("our_active_ability", snap)
        self.assertIn("opp_active_ability", snap)
        self.assertIn("our_active_item", snap)
        self.assertIn("opp_active_item", snap)
        self.assertIn("our_active_moves_revealed", snap)
        self.assertIn("opp_active_moves_revealed", snap)


if __name__ == "__main__":
    unittest.main()
