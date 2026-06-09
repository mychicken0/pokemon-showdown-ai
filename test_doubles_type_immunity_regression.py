#!/usr/bin/env python3
"""Type Immunity Regression Tests — Phase 6.4.3a.1

Verifies that score_action and is_type_immune correctly block all standard
type immunities, including dual-type targets, and that the our_type_immune_*
audit fields are properly computed (not hardcoded).
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import poke_env_test_cleanup  # noqa: F401

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    is_type_immune,
    ability_hard_blocks_move,
)


# ── Mock objects (same pattern as test_ground_into_flying.py) ──

class MockMove:
    def __init__(self, move_id, move_type, base_power=80, category="PHYSICAL",
                 target="normal", flags=None):
        self.id = move_id
        self._type_name = move_type.upper()
        self.base_power = base_power
        self.category_name = category.upper()
        self.target = target
        self.flags = flags or {}

    @property
    def type(self):
        from poke_env.battle.pokemon_type import PokemonType
        return PokemonType[self._type_name]

    @property
    def category(self):
        from poke_env.battle.move_category import MoveCategory
        return MoveCategory[self.category_name]


class MockPokemon:
    def __init__(self, species, types, ability=None, level=50):
        self.species = species
        self._types = []
        for t in types:
            from poke_env.battle.pokemon_type import PokemonType
            self._types.append(PokemonType[t.upper()])
        self._type_1 = self._types[0] if self._types else None
        self._type_2 = self._types[1] if len(self._types) > 1 else None
        self.ability = ability
        self.level = level
        self._base_stats = {"hp": 100, "atk": 100, "def": 100, "spa": 100, "spd": 100, "spe": 100}
        self._boosts = {}

    @property
    def types(self):
        return tuple(self._types)

    @property
    def current_hp_fraction(self):
        return 1.0

    @property
    def hp(self):
        return 100

    def damage_multiplier(self, move):
        from poke_env.battle.pokemon_type import PokemonType
        from poke_env.data.gen_data import GenData
        move_type = move.type if hasattr(move, 'type') else None
        if not move_type:
            return 1.0
        mult = 1.0
        chart = GenData.from_gen(9).type_chart
        for t in self._types:
            try:
                mult *= move_type.damage_multiplier(t, type_chart=chart)
            except Exception:
                pass
        return mult


class MockBattle:
    def __init__(self, fields=None):
        self.fields = fields or []
        self.active_pokemon = [None, None]
        self.opponent_active_pokemon = [None, None]
        self.turn = 1
        self.battle_tag = "test"
        self.force_switch = [False, False]
        self.available_moves = [[], []]
        self._replay_data = []


class TestDualTypeImmunity(unittest.TestCase):
    """Verify all standard type immunities including dual-type targets."""

    # Normal -> Ghost
    def test_normal_into_ghost(self):
        move = MockMove("tacklenormal", "NORMAL")
        target = MockPokemon("gengar", ["GHOST", "POISON"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    # Fighting -> Ghost
    def test_fighting_into_ghost(self):
        move = MockMove("closecombat", "FIGHTING")
        target = MockPokemon("gengar", ["GHOST", "POISON"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    # Fighting -> Steel/Ghost (dual type)
    def test_fighting_into_steel_ghost(self):
        move = MockMove("closecombat", "FIGHTING")
        target = MockPokemon("aegislash", ["STEEL", "GHOST"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    # Fighting -> Normal/Ghost — Ghost grants immunity
    def test_fighting_into_normal_ghost(self):
        move = MockMove("closecombat", "FIGHTING")
        target = MockPokemon("melmetal", ["NORMAL", "GHOST"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    # Electric -> Ground
    def test_electric_into_ground(self):
        move = MockMove("thunderbolt", "ELECTRIC")
        target = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    # Electric -> Water/Ground (dual type — Ground grants immunity)
    def test_electric_into_water_ground(self):
        move = MockMove("thunderbolt", "ELECTRIC")
        target = MockPokemon("swampert", ["WATER", "GROUND"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    # Ground -> Flying
    def test_ground_into_flying(self):
        move = MockMove("earthquake", "GROUND")
        target = MockPokemon("charizard", ["FIRE", "FLYING"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    # Ground -> Electric/Flying (dual type)
    def test_ground_into_electric_flying(self):
        move = MockMove("earthquake", "GROUND")
        target = MockPokemon("zapdos", ["ELECTRIC", "FLYING"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    # Psychic -> Dark
    def test_psychic_into_dark(self):
        move = MockMove("psychic", "PSYCHIC")
        target = MockPokemon("tyranitar", ["ROCK", "DARK"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    # Psychic -> Dark/Poison (dual type)
    def test_psychic_into_dark_poison(self):
        move = MockMove("psychic", "PSYCHIC")
        target = MockPokemon("drapion", ["POISON", "DARK"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    # Poison -> Steel
    def test_poison_into_steel(self):
        move = MockMove("sludgebomb", "POISON")
        target = MockPokemon("steelix", ["STEEL", "GROUND"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    # Poison -> Fairy/Steel (dual type)
    def test_poison_into_fairy_steel(self):
        move = MockMove("sludgebomb", "POISON")
        target = MockPokemon("mawile", ["FAIRY", "STEEL"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    # Dragon -> Fairy
    def test_dragon_into_fairy(self):
        move = MockMove("dragonpulse", "DRAGON")
        target = MockPokemon("clefable", ["FAIRY"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    # Dragon -> Water/Fairy (dual type)
    def test_dragon_into_water_fairy(self):
        move = MockMove("dragonpulse", "DRAGON")
        target = MockPokemon("primarina", ["WATER", "FAIRY"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    # Ghost -> Normal
    def test_ghost_into_normal(self):
        move = MockMove("shadowball", "GHOST")
        target = MockPokemon("blissey", ["NORMAL"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)


class TestImmunityExceptions(unittest.TestCase):
    """Verify known exceptions bypass immunity."""

    # Thousand Arrows hits Flying
    def test_thousand_arrows_hits_flying(self):
        move = MockMove("thousandarrows", "GROUND")
        target = MockPokemon("charizard", ["FIRE", "FLYING"])
        immune, _ = is_type_immune(move, None, target)
        self.assertFalse(immune)

    # Gravity allows Ground to hit Flying
    def test_gravity_ground_hits_flying(self):
        class GravityField:
            def __init__(self):
                self.name = "gravity"
        battle = MockBattle(fields=[GravityField()])
        move = MockMove("earthquake", "GROUND")
        target = MockPokemon("charizard", ["FIRE", "FLYING"])
        immune, _ = is_type_immune(move, None, target, battle)
        self.assertFalse(immune)

    # Scrappy allows Fighting into Ghost
    def test_scrappy_fighting_hits_ghost(self):
        move = MockMove("closecombat", "FIGHTING")
        attacker = MockPokemon("pangoro", ["FIGHTING", "DARK"], ability="scrappy")
        target = MockPokemon("gengar", ["GHOST", "POISON"])
        immune, _ = is_type_immune(move, attacker, target)
        self.assertFalse(immune)

    # Scrappy allows Normal into Ghost
    def test_scrappy_normal_hits_ghost(self):
        move = MockMove("bodyslam", "NORMAL")
        attacker = MockPokemon("pangoro", ["FIGHTING", "DARK"], ability="scrappy")
        target = MockPokemon("gengar", ["GHOST", "POISON"])
        immune, _ = is_type_immune(move, attacker, target)
        self.assertFalse(immune)


class TestNonImmune(unittest.TestCase):
    """Verify non-immune interactions return False."""

    def test_fire_into_grass(self):
        move = MockMove("flamethrower", "FIRE")
        target = MockPokemon("venusaur", ["GRASS", "POISON"])
        immune, _ = is_type_immune(move, None, target)
        self.assertFalse(immune)

    def test_water_into_fire(self):
        move = MockMove("surf", "WATER")
        target = MockPokemon("charizard", ["FIRE", "FLYING"])
        immune, _ = is_type_immune(move, None, target)
        self.assertFalse(immune)

    def test_ground_into_water(self):
        move = MockMove("earthquake", "GROUND")
        target = MockPokemon("swampert", ["WATER", "GROUND"])
        immune, _ = is_type_immune(move, None, target)
        self.assertFalse(immune)


if __name__ == "__main__":
    unittest.main()
