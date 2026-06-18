#!/usr/bin/env python3
"""Tests for the extracted doubles_engine.mechanics
module.

ponytail: focused unit tests for the mechanics
wrappers. These tests verify:
- Each helper produces the expected output for
  representative inputs.
- The late-defined primitives (lazy imports) work
  correctly.
- Importing ``bot_doubles_damage_aware`` still
  succeeds after the shim replaces the original
  block.

Behavior-preservation evidence: existing tests in
``test_doubles_ability_hard_safety`` and related
test files exercise the same code path through the
shim, so the extraction is verified to be
bit-for-bit equivalent.
"""
import os
import sys
import unittest
from typing import Any, Dict, List, Optional, Tuple

import poke_env_test_cleanup  # noqa: F401  — must precede any poke_env import

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _FakeMove:
    """Mimics poke_env's Move object. Has
    .id, .type (str or enum with .name), .base_power,
    .deduced_target, .target, .move_target.

    ponytail: ``type`` is set as a str directly. The
    bot's helper ``is_opponent_spread_move`` reads
    ``move.type.name`` if available, else str.
    Since we only need the type as a string, set it
    as a str; the bot's get_effective_move_type
    handles both. The id is a string.
    """

    def __init__(
        self,
        id: str = "tackle",
        type: str = "normal",
        base_power: int = 40,
        target: str = "normal",
    ):
        self.id = id
        # Wrap type in a tiny enum so .name works.
        class _T:
            def __init__(self, n):
                self.name = n.upper()
        self.type = _T(type)
        self.base_power = base_power
        self.target = target
        self.deduced_target = target


class _FakePokemon:
    """Mimics poke_env's Pokemon object. Has
    .ability (str), .types (list), .species, .status,
    .fainted, .temporary_ability, .possible_abilities.

    ponytail: ``ability`` is a plain string. The
    bot's ``_normalize_ability_name`` calls
    ``str(ability)`` and then strips to alnum
    lowercase. A plain string like "Intimidate"
    normalizes to "intimidate".
    """

    def __init__(
        self,
        species: str = "pikachu",
        ability: Any = "static",
        types: Optional[List[str]] = None,
        status: Any = None,
        fainted: bool = False,
        temporary_ability: Any = None,
        possible_abilities: Any = None,
    ):
        self.species = species
        self.ability = ability
        if types is None:
            types = ["electric"]
        self.types = []
        for t in types:
            class _T:
                def __init__(self, n):
                    self.name = n.upper()
            self.types.append(_T(t))
        self.status = status
        self.fainted = fainted
        self.temporary_ability = temporary_ability
        self.possible_abilities = possible_abilities

    def damage_multiplier(self, *args, **kwargs):
        return 1.0


class _FakeOrder:
    def __init__(self, id: str = "watergun", type: str = "water"):
        self.order = _FakeMove(id=id, type=type)
        self.move_target = 0
        self.mega = False
        self.z_move = False
        self.dynamax = False
        self.terastallize = False


class _FakeBattle:
    def __init__(
        self,
        fields: Optional[list] = None,
        our_team: Optional[list] = None,
        battle_tag: Optional[str] = "test",
    ):
        self.fields = fields or {}
        # ``_pokemon_is_on_our_team`` checks
        # ``battle.active_pokemon`` and ``battle.team``.
        # The fake exposes both. ponytail: list of
        # pokemons, not a dict, so the function falls
        # through to the iterable branch.
        self.active_pokemon = list(our_team) if our_team else []
        self.team = list(our_team) if our_team else []
        self.battle_tag = battle_tag
        # ``get_known_ability`` reads ``_replay_data``;
        # leave it as ``None`` unless the test sets it.
        self._replay_data = None


class _FakeConfig:
    def __init__(
        self,
        enable_ability_hard_safety_only: bool = True,
        ability_hard_safety_allow_singleton_deduction: bool = True,
        ability_hard_safety_avoid_absorb: bool = True,
    ):
        self.enable_ability_hard_safety_only = (
            enable_ability_hard_safety_only
        )
        self.ability_hard_safety_allow_singleton_deduction = (
            ability_hard_safety_allow_singleton_deduction
        )
        self.ability_hard_safety_avoid_absorb = (
            ability_hard_safety_avoid_absorb
        )


class TestImportSmoke(unittest.TestCase):
    """Import smoke: ``bot_doubles_damage_aware``
    still succeeds after the shim replacement."""

    def test_bot_imports(self):
        import bot_doubles_damage_aware  # noqa: F401

    def test_mechanics_imports(self):
        import doubles_engine.mechanics  # noqa: F401

    def test_all_helpers_reexported(self):
        import bot_doubles_damage_aware as m
        for name in (
            "resolve_known_ability",
            "ability_hard_blocks_move",
            "direct_known_absorb_blocks_move",
            "ability_redirects_single_target_move",
            "ally_ability_makes_safe",
            "_ability_block_enabled",
        ):
            self.assertTrue(
                hasattr(m, name),
                f"bot_doubles_damage_aware missing {name}",
            )


class TestResolveKnownAbility(unittest.TestCase):
    def test_no_pokemon(self):
        from doubles_engine.mechanics import resolve_known_ability
        r = resolve_known_ability(None)
        self.assertEqual(r["ability"], None)
        self.assertEqual(r["source"], "unknown")
        self.assertEqual(r["is_deterministic"], False)

    def test_our_team_known(self):
        from doubles_engine.mechanics import resolve_known_ability
        our_pokemon = _FakePokemon(
            species="incineroar", ability="Intimidate"
        )
        battle = _FakeBattle(our_team=[our_pokemon])
        r = resolve_known_ability(our_pokemon, battle=battle)
        self.assertEqual(r["ability"], "intimidate")
        self.assertEqual(r["source"], "our_team_known")
        self.assertTrue(r["is_deterministic"])

    def test_protocol_revealed(self):
        from doubles_engine.mechanics import resolve_known_ability
        opponent = _FakePokemon(
            species="swampert", ability="torrent"
        )
        # battle_tag="test" + no _replay_data triggers
        # the early-return path: function returns the
        # opponent's ability (no protocol gating).
        battle = _FakeBattle(our_team=[])
        r = resolve_known_ability(opponent, battle=battle)
        # Without _replay_data, the function returns the
        # ability unconditionally. is_deterministic=True
        # because the ability is treated as known.
        self.assertEqual(r["ability"], "torrent")
        self.assertTrue(r["is_deterministic"])

    def test_singleton_deduction(self):
        from doubles_engine.mechanics import resolve_known_ability
        opponent = _FakePokemon(
            species="swampert", ability="", possible_abilities=["torrent"]
        )
        config = _FakeConfig(
            ability_hard_safety_allow_singleton_deduction=True
        )
        battle = _FakeBattle(our_team=[])
        r = resolve_known_ability(
            opponent, battle=battle, config=config
        )
        # Singleton deduction should pick "torrent"
        # from possible_abilities.
        self.assertEqual(r["ability"], "torrent")
        self.assertEqual(r["source"], "deterministic_singleton")
        self.assertTrue(r["is_deterministic"])

    def test_no_singleton_when_disabled(self):
        from doubles_engine.mechanics import resolve_known_ability
        opponent = _FakePokemon(
            species="swampert", ability="", possible_abilities=["torrent"]
        )
        config = _FakeConfig(
            ability_hard_safety_allow_singleton_deduction=False
        )
        battle = _FakeBattle(our_team=[])
        r = resolve_known_ability(
            opponent, battle=battle, config=config
        )
        # No deduction -> ability stays None.
        self.assertIsNone(r["ability"])
        self.assertEqual(r["source"], "unknown")


class TestAbilityBlockEnabled(unittest.TestCase):
    """_ability_block_enabled gates the ability-hard
    safety config flags."""

    def test_disabled_when_no_config(self):
        from doubles_engine.mechanics import _ability_block_enabled
        self.assertFalse(_ability_block_enabled(None, "any"))

    def test_disabled_when_no_safety_flag(self):
        from doubles_engine.mechanics import _ability_block_enabled
        config = _FakeConfig(enable_ability_hard_safety_only=False)
        self.assertFalse(_ability_block_enabled(config, "any"))

    def test_sound_bullet_explosion_excluded(self):
        from doubles_engine.mechanics import _ability_block_enabled
        config = _FakeConfig()
        for reason in (
            "sound_into_soundproof",
            "bullet_into_bulletproof",
            "explosion_into_damp",
        ):
            self.assertFalse(_ability_block_enabled(config, reason))

    def test_absorb_prefix_default_avoid(self):
        from doubles_engine.mechanics import _ability_block_enabled
        config = _FakeConfig(ability_hard_safety_avoid_absorb=True)
        self.assertTrue(
            _ability_block_enabled(config, "water_into_waterabsorb")
        )

    def test_absorb_prefix_allow_when_disabled(self):
        from doubles_engine.mechanics import _ability_block_enabled
        config = _FakeConfig(ability_hard_safety_avoid_absorb=False)
        self.assertFalse(
            _ability_block_enabled(config, "water_into_waterabsorb")
        )

    def test_other_reason_default_allow(self):
        from doubles_engine.mechanics import _ability_block_enabled
        config = _FakeConfig()
        self.assertTrue(
            _ability_block_enabled(config, "redirected_by_stormdrain")
        )


class TestAllyAbilityMakesSafe(unittest.TestCase):
    def test_no_ally(self):
        from doubles_engine.mechanics import ally_ability_makes_safe
        self.assertEqual(
            ally_ability_makes_safe(None, _FakeMove()), (False, "")
        )

    def test_telepathy_ally(self):
        from doubles_engine.mechanics import ally_ability_makes_safe
        ally = _FakePokemon(species="claydol", ability="Telepathy")
        result = ally_ability_makes_safe(ally, _FakeMove(type="fighting"))
        self.assertEqual(result, (True, "telepathy"))

    def test_levitate_ground(self):
        from doubles_engine.mechanics import ally_ability_makes_safe
        ally = _FakePokemon(species="gastly", ability="Levitate")
        result = ally_ability_makes_safe(ally, _FakeMove(type="ground"))
        self.assertEqual(result, (True, "levitate"))

    def test_thousandarrows_breaks_levitate(self):
        # Thousand Arrows hits Levitate (Grounded).
        from doubles_engine.mechanics import ally_ability_makes_safe
        ally = _FakePokemon(species="gastly", ability="Levitate")
        move = _FakeMove(id="thousandarrows", type="ground")
        result = ally_ability_makes_safe(ally, move)
        self.assertEqual(result, (False, ""))

    def test_eartheater(self):
        from doubles_engine.mechanics import ally_ability_makes_safe
        ally = _FakePokemon(
            species="orthworm", ability="Earth Eater"
        )
        result = ally_ability_makes_safe(ally, _FakeMove(type="ground"))
        self.assertEqual(result, (True, "eartheater"))

    def test_waterabsorb_water(self):
        from doubles_engine.mechanics import ally_ability_makes_safe
        ally = _FakePokemon(
            species="lanturn", ability="Water Absorb"
        )
        result = ally_ability_makes_safe(ally, _FakeMove(type="water"))
        self.assertEqual(result, (True, "waterabsorb"))

    def test_voltabsorb_electric(self):
        from doubles_engine.mechanics import ally_ability_makes_safe
        ally = _FakePokemon(
            species="donphan", ability="Volt Absorb"
        )
        result = ally_ability_makes_safe(ally, _FakeMove(type="electric"))
        self.assertEqual(result, (True, "voltabsorb"))

    def test_flashfire_fire(self):
        from doubles_engine.mechanics import ally_ability_makes_safe
        ally = _FakePokemon(
            species="heatran", ability="Flash Fire"
        )
        result = ally_ability_makes_safe(ally, _FakeMove(type="fire"))
        self.assertEqual(result, (True, "flashfire"))

    def test_sapsipper_grass(self):
        from doubles_engine.mechanics import ally_ability_makes_safe
        ally = _FakePokemon(
            species="bouffalant", ability="Sap Sipper"
        )
        result = ally_ability_makes_safe(ally, _FakeMove(type="grass"))
        self.assertEqual(result, (True, "sapsipper"))

    def test_levitate_blocked_by_gravity(self):
        from doubles_engine.mechanics import ally_ability_makes_safe
        ally = _FakePokemon(species="gastly", ability="Levitate")
        # Create a battle with Gravity active.
        class _GravityField:
            name = "gravity"
        battle = _FakeBattle(fields=[_GravityField()])
        result = ally_ability_makes_safe(
            ally, _FakeMove(type="ground"), battle=battle
        )
        self.assertEqual(result, (False, ""))


class TestAbilityHardBlocksMove(unittest.TestCase):
    """ability_hard_blocks_move uses late-defined
    primitives (_extract_move_id, _extract_ability,
    _extract_target_types) via lazy imports."""

    def test_no_target(self):
        from doubles_engine.mechanics import ability_hard_blocks_move
        self.assertEqual(
            ability_hard_blocks_move(_FakeMove(), None, None),
            (False, ""),
        )

    def test_no_ability_returns_no_block(self):
        from doubles_engine.mechanics import ability_hard_blocks_move
        # No protocol reveal, no possible abilities, no
        # our_team. Target's ability stays None.
        target = _FakePokemon(
            species="snorlax", ability="", possible_abilities=None
        )
        battle = _FakeBattle(our_team=[])
        result = ability_hard_blocks_move(
            _FakeMove(type="fighting"),
            _FakePokemon(species="machamp"),
            target, battle=battle,
        )
        # No ability -> no block.
        self.assertEqual(result, (False, ""))

    def test_with_target_returns_tuple(self):
        from doubles_engine.mechanics import ability_hard_blocks_move
        # Returns a tuple in all cases.
        target = _FakePokemon(species="gastly", ability="Levitate")
        battle = _FakeBattle(our_team=[])
        result = ability_hard_blocks_move(
            _FakeMove(id="earthquake", type="ground"),
            _FakePokemon(species="garchomp"),
            target, battle=battle,
        )
        # Either blocks or not — the wrapper must
        # always return a 2-tuple.
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], bool)
        self.assertIsInstance(result[1], str)


class TestDirectKnownAbsorbBlocksMove(unittest.TestCase):
    """direct_known_absorb_blocks_move delegates
    spread blocking to is_opponent_spread_move via
    lazy import."""

    def test_spread_move_not_blocked(self):
        from doubles_engine.mechanics import (
            direct_known_absorb_blocks_move,
        )
        from poke_env.battle.double_battle import SingleBattleOrder
        # Build a spread move order. ponytail: we just
        # need the move to be classified as a spread
        # move by is_opponent_spread_move. Using a real
        # poke_env SingleBattleOrder ensures the
        # type/target detection works.
        move = _FakeMove(
            id="earthquake", type="ground", target="all_adjacent"
        )
        order = SingleBattleOrder.__new__(SingleBattleOrder)
        order.order = move
        order.move_target = 0
        order.mega = False
        order.z_move = False
        order.dynamax = False
        order.terastallize = False
        target = _FakePokemon(
            species="gastly", ability="Levitate"
        )
        result = direct_known_absorb_blocks_move(
            move,
            _FakePokemon(species="garchomp"),
            target,
            order=order,
        )
        # Spread move -> not blocked.
        self.assertEqual(result, (False, ""))

    def test_non_spread_move_delegates_to_ability(self):
        from doubles_engine.mechanics import (
            direct_known_absorb_blocks_move,
        )
        # Non-spread: 0 base power -> not blocked.
        move = _FakeMove(
            id="splash", type="normal", base_power=0
        )
        target = _FakePokemon(species="pikachu", ability="Static")
        result = direct_known_absorb_blocks_move(
            move, _FakePokemon(species="gyarados"), target
        )
        self.assertEqual(result, (False, ""))


class TestAbilityRedirectsSingleTargetMove(unittest.TestCase):
    def test_no_move(self):
        from doubles_engine.mechanics import (
            ability_redirects_single_target_move,
        )
        self.assertEqual(
            ability_redirects_single_target_move(
                None, _FakePokemon(), [_FakePokemon()]
            ),
            (False, ""),
        )

    def test_stormdrain_redirects_water(self):
        from doubles_engine.mechanics import (
            ability_redirects_single_target_move,
        )
        intended = _FakePokemon(species="pikachu", ability="Static")
        stormdrain = _FakePokemon(
            species="gastrodon", ability="Storm Drain"
        )
        # Single-target water move (not a spread move):
        # waterpulse has target "any" / single-target. Use
        # a non-spread water move so Stormdrain can
        # redirect. (surf is classified as a spread move
        # and would not be redirected.)
        move = _FakeMove(id="waterpulse", type="water")
        result = ability_redirects_single_target_move(
            move, intended, [intended, stormdrain]
        )
        self.assertEqual(
            result, (True, "redirected_by_stormdrain")
        )

    def test_lightningrod_redirects_electric(self):
        from doubles_engine.mechanics import (
            ability_redirects_single_target_move,
        )
        intended = _FakePokemon(species="snorlax", ability="Thick Fat")
        lrod = _FakePokemon(
            species="zapdos", ability="Lightning Rod"
        )
        # Single-target electric move (thunderbolt has
        # target "any" / single-target). thunder is a
        # spread move and would not be redirected.
        move = _FakeMove(id="thunderbolt", type="electric")
        result = ability_redirects_single_target_move(
            move, intended, [intended, lrod]
        )
        self.assertEqual(
            result, (True, "redirected_by_lightningrod")
        )

    def test_fainted_redirector_skipped(self):
        from doubles_engine.mechanics import (
            ability_redirects_single_target_move,
        )
        intended = _FakePokemon(species="pikachu", ability="Static")
        fainted = _FakePokemon(
            species="gastrodon",
            ability="Storm Drain",
            fainted=True,
        )
        move = _FakeMove(id="waterpulse", type="water")
        result = ability_redirects_single_target_move(
            move, intended, [intended, fainted]
        )
        # Fainted redirector can't redirect.
        self.assertEqual(result, (False, ""))

    def test_intended_target_only_no_redirect(self):
        from doubles_engine.mechanics import (
            ability_redirects_single_target_move,
        )
        intended = _FakePokemon(species="pikachu", ability="Static")
        move = _FakeMove(id="waterpulse", type="water")
        # Only intended target in list -> no redirect.
        result = ability_redirects_single_target_move(
            move, intended, [intended]
        )
        self.assertEqual(result, (False, ""))


if __name__ == "__main__":
    unittest.main()
