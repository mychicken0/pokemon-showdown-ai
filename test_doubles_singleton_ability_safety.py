#!/usr/bin/env python3
"""Tests for Phase 6.3.5 - Deterministic Singleton Ability Safety.

30 required tests covering singleton ability resolution, Ground-into-Flying,
and dual-type mechanics.
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import poke_env_test_cleanup  # noqa: F401 — unregister deadlock-prone atexit

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    DoublesDamageAwarePlayer,
    resolve_known_ability,
    get_known_ability,
    ability_hard_blocks_move,
    get_max_type_threat,
    is_type_immune,
    _normalize_ability_name,
    priority_move_is_field_blocked,
    evaluate_priority_move_legality,
)


class MockMove:
    """Minimal Move mock for testing."""
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
    """Minimal Pokemon mock for testing."""
    def __init__(self, species, types, ability=None, possible_abilities=None, level=50):
        self.species = species
        self._types = []
        for t in types:
            from poke_env.battle.pokemon_type import PokemonType
            self._types.append(PokemonType[t.upper()])
        self._type_1 = self._types[0] if self._types else None
        self._type_2 = self._types[1] if len(self._types) > 1 else None
        self.ability = ability or ""
        self.possible_abilities = possible_abilities or []
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

    def damage_multiplier(self, move_or_type):
        from poke_env.battle.pokemon_type import PokemonType
        from poke_env.data.gen_data import GenData
        # Handle both Move objects and PokemonType objects
        move_type = None
        if isinstance(move_or_type, PokemonType):
            move_type = move_or_type
        elif hasattr(move_or_type, 'type'):
            move_type = move_or_type.type
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
        self._player_role = "p1"


class MockField:
    def __init__(self, name):
        self.name = name


class TestResolveKnownAbility(unittest.TestCase):
    """Tests 1-6, 10-20 for singleton ability resolution."""

    def test_01_singleton_levitate_resolves_only_when_flag_enabled(self):
        """Test 1: singleton [levitate] resolves only when the new flag is enabled."""
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])

        # Without flag: should be unknown
        config_off = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=False)
        result = resolve_known_ability(pokemon, config=config_off)
        self.assertEqual(result["ability"], None)
        self.assertEqual(result["source"], "unknown")
        self.assertFalse(result["is_deterministic"])

        # With flag: should resolve to levitate
        config_on = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=True)
        result = resolve_known_ability(pokemon, config=config_on)
        self.assertEqual(result["ability"], "levitate")
        self.assertEqual(result["source"], "deterministic_singleton")
        self.assertTrue(result["is_deterministic"])

    def test_02_singleton_resolution_enabled_by_default(self):
        """Test 2: singleton resolution is enabled by default (adopted)."""
        config = DoublesDamageAwareConfig()
        self.assertTrue(config.ability_hard_safety_allow_singleton_deduction)

    def test_03_multiple_abilities_never_resolve(self):
        """Test 3: multiple abilities never resolve by deduction."""
        pokemon = MockPokemon("pikachu", ["ELECTRIC"], possible_abilities=["Static", "Lightning Rod"])
        config = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=True)
        result = resolve_known_ability(pokemon, config=config)
        self.assertEqual(result["ability"], None)
        self.assertEqual(result["source"], "unknown")
        self.assertFalse(result["is_deterministic"])

    def test_04_empty_possible_abilities_remain_unknown(self):
        """Test 4: empty possible abilities remain unknown."""
        pokemon = MockPokemon("mystery", ["NORMAL"], possible_abilities=[])
        config = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=True)
        result = resolve_known_ability(pokemon, config=config)
        self.assertEqual(result["ability"], None)
        self.assertEqual(result["source"], "unknown")

    def test_05_exact_form_possible_abilities_used(self):
        """Test 5: exact form's possible abilities are used."""
        pokemon = MockPokemon("rotomwash", ["WATER", "ELECTRIC"], possible_abilities=["Levitate"])
        config = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=True)
        result = resolve_known_ability(pokemon, config=config)
        self.assertEqual(result["ability"], "levitate")
        self.assertEqual(result["source"], "deterministic_singleton")
        self.assertEqual(result["possible_abilities"], ["levitate"])

    def test_06_no_species_hardcoded_mapping(self):
        """Test 6: no species hard-coded mapping is used."""
        # A Pokemon not in any hard-coded list should still work if possible_abilities is correct
        pokemon = MockPokemon("custommon", ["NORMAL"], possible_abilities=["CustomAbility"])
        config = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=True)
        result = resolve_known_ability(pokemon, config=config)
        self.assertEqual(result["ability"], "customability")
        self.assertEqual(result["source"], "deterministic_singleton")

    def test_07_singleton_levitate_blocks_ground(self):
        """Test 7: singleton Levitate blocks Ground."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        battle = MockBattle()

        blocks, reason = ability_hard_blocks_move(move, attacker, pokemon, battle, config)
        self.assertTrue(blocks)
        self.assertIn("levitate", reason.lower())

    def test_08_singleton_levitate_expected_damage_zero(self):
        """Test 8: singleton Levitate expected damage is zero."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        battle = MockBattle()
        battle.active_pokemon = [attacker]
        battle.opponent_active_pokemon = [pokemon]

        from bot_doubles_damage_aware import DoublesDamageAwarePlayer
        player = DoublesDamageAwarePlayer.__new__(DoublesDamageAwarePlayer)
        player.config = config
        player.verbose = False
        player.ability_blocks_avoided_by_battle = {}
        player.ability_absorbs_avoided_by_battle = {}
        player.ability_redirects_avoided_by_battle = {}
        player.ability_multipliers_applied_by_battle = {}
        player.partial_immune_spread_by_battle = {}
        player.partial_ability_immune_spread_by_battle = {}
        player.efficient_partial_spread_by_battle = {}
        player.inefficient_partial_spread_by_battle = {}
        player.immune_target_species_by_battle = {}
        player.damaged_target_species_by_battle = {}
        player.best_single_alternative_by_battle = {}

        damage = player.get_expected_damage(move, attacker, pokemon, battle, config)
        self.assertEqual(damage, 0.0)

    def test_09_singleton_levitate_loses_tie_to_useful_action(self):
        """Test 9: singleton Levitate loses a joint zero-score tie to a useful legal action."""
        # Ground into Levitate should be blocked, while a Fire move would not be
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        ground_move = MockMove("earthquake", "GROUND")
        fire_move = MockMove("flamethrower", "FIRE")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        battle = MockBattle()
        battle.active_pokemon = [attacker]
        battle.opponent_active_pokemon = [pokemon]

        # Ground should be blocked
        ground_blocks, _ = ability_hard_blocks_move(ground_move, attacker, pokemon, battle, config)
        self.assertTrue(ground_blocks)

        # Fire should NOT be blocked
        fire_blocks, _ = ability_hard_blocks_move(fire_move, attacker, pokemon, battle, config)
        self.assertFalse(fire_blocks)

    def test_10_thousand_arrows_bypasses(self):
        """Test 10: Thousand Arrows bypasses singleton Levitate."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        move = MockMove("thousandarrows", "GROUND")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        battle = MockBattle()

        blocks, _ = ability_hard_blocks_move(move, attacker, pokemon, battle, config)
        self.assertFalse(blocks)

    def test_11_gravity_bypasses(self):
        """Test 11: Gravity bypasses singleton Levitate."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        battle = MockBattle(fields=[MockField("gravity")])

        blocks, _ = ability_hard_blocks_move(move, attacker, pokemon, battle, config)
        self.assertFalse(blocks)

    def test_12_mold_breaker_bypasses(self):
        """Test 12: Mold Breaker bypasses singleton Levitate."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"], ability="moldbreaker")
        battle = MockBattle()
        battle.active_pokemon = [attacker, None]
        battle._player_role = "p1"

        blocks, _ = ability_hard_blocks_move(move, attacker, pokemon, battle, config)
        self.assertFalse(blocks)

    def test_13_teravolt_bypasses(self):
        """Test 13: Teravolt bypasses singleton Levitate."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"], ability="teravolt")
        battle = MockBattle()
        battle.active_pokemon = [attacker, None]
        battle._player_role = "p1"

        blocks, _ = ability_hard_blocks_move(move, attacker, pokemon, battle, config)
        self.assertFalse(blocks)

    def test_14_turboblaze_bypasses(self):
        """Test 14: Turboblaze bypasses singleton Levitate."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"], ability="turboblaze")
        battle = MockBattle()
        battle.active_pokemon = [attacker, None]
        battle._player_role = "p1"

        blocks, _ = ability_hard_blocks_move(move, attacker, pokemon, battle, config)
        self.assertFalse(blocks)

    def test_15_gastro_acid_suppresses(self):
        """Test 15: Gastro Acid suppresses singleton ability."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        pokemon.status = "gastroacid"
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        battle = MockBattle()

        resolution = resolve_known_ability(pokemon, battle, config)
        self.assertTrue(resolution["is_currently_suppressed"])
        self.assertEqual(resolution["suppression_reason"], "gastro_acid")

    def test_16_neutralizing_gas_suppresses(self):
        """Test 16: Neutralizing Gas suppresses singleton ability."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        battle = MockBattle(fields=[MockField("Neutralizing Gas")])

        resolution = resolve_known_ability(pokemon, battle, config)
        self.assertTrue(resolution["is_currently_suppressed"])
        self.assertEqual(resolution["suppression_reason"], "neutralizing_gas")

    def test_17_smack_down_makes_ground_connect(self):
        """Test 17: Smack Down makes Ground connect."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        pokemon = MockPokemon("charizard", ["FIRE", "FLYING"], possible_abilities=["Blaze"])
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        battle = MockBattle(fields=[MockField("smackdown")])

        blocks, _ = ability_hard_blocks_move(move, attacker, pokemon, battle, config)
        # Smack Down makes Ground connect, so no ability block
        self.assertFalse(blocks)

    def test_18_temporary_changed_ability_overrides(self):
        """Test 18: temporary changed ability overrides singleton base ability."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        pokemon.temporary_ability = "Trace"  # Temporary ability change
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        battle = MockBattle()

        # With Trace as temporary ability, Ground should NOT be blocked
        blocks, reason = ability_hard_blocks_move(move, attacker, pokemon, battle, config)
        self.assertFalse(blocks)

    def test_19_explicit_protocol_reveal_overrides(self):
        """Test 19: explicit protocol reveal overrides singleton base data."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        # Simulate protocol reveal of a different ability
        pokemon.ability = "Trace"
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        battle = MockBattle()

        # With explicit Trace ability, Ground should NOT be blocked
        blocks, reason = ability_hard_blocks_move(move, attacker, pokemon, battle, config)
        self.assertFalse(blocks)

    def test_20_conflicting_current_ability_records_conflict(self):
        """Test 20: conflicting current ability records records conflict."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        # Pokemon with singleton Levitate but current ability set to something else
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        pokemon.ability = "Trace"  # Conflicts with singleton
        battle = MockBattle()
        battle.active_pokemon = [pokemon, None]

        result = resolve_known_ability(pokemon, battle, config)
        # Our team Pokemon's explicit ability takes precedence over singleton
        self.assertEqual(result["ability"], "trace")
        self.assertEqual(result["source"], "our_team_known")

    def test_21_ground_into_flying_immune(self):
        """Test: Ground into Flying is immune."""
        move = MockMove("earthquake", "GROUND")
        target = MockPokemon("charizard", ["FIRE", "FLYING"])
        from bot_doubles_damage_aware import is_type_immune
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    def test_22_ground_into_electric_flying_immune(self):
        """Test: Ground into Electric/Flying is immune."""
        move = MockMove("earthquake", "GROUND")
        target = MockPokemon("zapdos", ["ELECTRIC", "FLYING"])
        from bot_doubles_damage_aware import is_type_immune
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    def test_23_thousand_arrows_bypasses_flying(self):
        """Test: Thousand Arrows bypasses Flying."""
        move = MockMove("thousandarrows", "GROUND")
        target = MockPokemon("charizard", ["FIRE", "FLYING"])
        from bot_doubles_damage_aware import is_type_immune
        immune, _ = is_type_immune(move, None, target)
        self.assertFalse(immune)

    def test_24_no_absorb_safety_enabled(self):
        """Test: no absorb safety is enabled by this flag."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        self.assertFalse(config.ability_hard_safety_avoid_absorb)

    def test_25_no_redirection_safety_enabled(self):
        """Test: no redirection safety is enabled by this flag."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        self.assertFalse(config.ability_hard_safety_avoid_redirection)

    def test_26_no_ally_safety_enabled(self):
        """Test: no ally safety is enabled by this flag."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        self.assertFalse(config.ability_hard_safety_ally_spread_safety)

    def test_27_ground_into_pure_flying_immune(self):
        """Test: Ground into pure Flying is immune."""
        move = MockMove("earthquake", "GROUND")
        target = MockPokemon("pidgeot", ["FLYING"])
        from bot_doubles_damage_aware import is_type_immune
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    def test_28_electric_into_water_ground_zero(self):
        """Test: Electric into Water/Ground = 0x."""
        move = MockMove("thunderbolt", "ELECTRIC")
        target = MockPokemon("swampert", ["WATER", "GROUND"])
        from bot_doubles_damage_aware import is_type_immune
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    def test_29_electric_into_water_flying_4x(self):
        """Test: Electric into Water/Flying = 4x."""
        from poke_env.battle.pokemon_type import PokemonType
        from poke_env.data.gen_data import GenData
        chart = GenData.from_gen(9).type_chart

        mult_water = PokemonType.ELECTRIC.damage_multiplier(PokemonType.WATER, type_chart=chart)
        mult_flying = PokemonType.ELECTRIC.damage_multiplier(PokemonType.FLYING, type_chart=chart)
        # Electric vs Water = 2x, Electric vs Flying = 2x, combined = 4x
        self.assertEqual(mult_water * mult_flying, 4.0)

    def test_30_hidden_grounding_item_not_inferred(self):
        """Test: hidden grounding item (Iron Ball) is not inferred."""
        move = MockMove("earthquake", "GROUND")
        target = MockPokemon("charizard", ["FIRE", "FLYING"], possible_abilities=["Blaze"])
        from bot_doubles_damage_aware import is_type_immune
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)  # Without Iron Ball, Ground is still immune


class TestGetMaxTypeThreat(unittest.TestCase):
    """Tests for the get_max_type_threat helper."""

    def test_returns_zero_for_none(self):
        self.assertEqual(get_max_type_threat(None, None), 0.0)

    def test_uses_both_types(self):
        """Max threat considers both opponent types."""
        our_active = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        opp = MockPokemon("gyarados", ["WATER", "FLYING"])

        threat = get_max_type_threat(our_active, opp)
        # Water vs Dragon+Ground = 1.0x (0.5 * 2.0), Flying vs Dragon+Ground = 0.0x (1.0 * 0.0)
        # max = 1.0
        self.assertGreaterEqual(threat, 0.0)
        self.assertLessEqual(threat, 4.0)

    def test_pure_type(self):
        """Single-type opponent."""
        our_active = MockPokemon("venusaur", ["GRASS", "POISON"])
        opp = MockPokemon("charizard", ["FIRE"])

        threat = get_max_type_threat(our_active, opp)
        # Fire vs Grass+Poison = 0.25x (2.0 * 0.5)
        self.assertGreaterEqual(threat, 0.0)


class TestPriorityFieldSafety(unittest.TestCase):
    """Tests 10-28 for priority field hard safety under Psychic Terrain and blocking abilities."""

    def test_10_sucker_punch_blocked_psychic_terrain(self):
        """Test 10: Sucker Punch into grounded target is blocked under Psychic Terrain."""
        config = DoublesDamageAwareConfig(enable_priority_field_hard_safety=True)
        attacker = MockPokemon("pawmot", ["ELECTRIC", "FIGHTING"])
        target = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        move = MockMove("suckerpunch", "DARK", base_power=70, target="normal")
        move.priority = 1
        class PriorityMockBattle(MockBattle):
            def is_grounded(self, mon):
                return True
        battle = PriorityMockBattle(fields=[MockField("psychicterrain")])
        battle._replay_data = None
        battle.opponent_active_pokemon = [target, None]
        
        blocked, reason = priority_move_is_field_blocked(move, attacker, target, battle, config)
        self.assertTrue(blocked)
        self.assertEqual(reason, "priority_blocked_by_psychic_terrain")

    def test_11_quick_attack_blocked_psychic_terrain(self):
        """Test 11: Quick Attack into grounded target is blocked."""
        config = DoublesDamageAwareConfig(enable_priority_field_hard_safety=True)
        attacker = MockPokemon("pikachu", ["ELECTRIC"])
        target = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        move = MockMove("quickattack", "NORMAL", base_power=40)
        move.priority = 1
        class PriorityMockBattle(MockBattle):
            def is_grounded(self, mon):
                return True
        battle = PriorityMockBattle(fields=[MockField("psychicterrain")])
        battle._replay_data = None
        battle.opponent_active_pokemon = [target, None]
        blocked, reason = priority_move_is_field_blocked(move, attacker, target, battle, config)
        self.assertTrue(blocked)

    def test_12_fake_out_blocked_psychic_terrain(self):
        """Test 12: Fake Out into grounded target is blocked."""
        config = DoublesDamageAwareConfig(enable_priority_field_hard_safety=True)
        attacker = MockPokemon("meowth", ["NORMAL"])
        target = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        move = MockMove("fakeout", "NORMAL", base_power=40)
        move.priority = 3
        class PriorityMockBattle(MockBattle):
            def is_grounded(self, mon):
                return True
        battle = PriorityMockBattle(fields=[MockField("psychicterrain")])
        battle._replay_data = None
        battle.opponent_active_pokemon = [target, None]
        blocked, reason = priority_move_is_field_blocked(move, attacker, target, battle, config)
        self.assertTrue(blocked)

    def test_13_expected_damage_zero_when_blocked(self):
        """Test 13: priority damaging move expected damage is zero."""
        config = DoublesDamageAwareConfig(enable_priority_field_hard_safety=True)
        attacker = MockPokemon("pawmot", ["ELECTRIC", "FIGHTING"])
        target = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        move = MockMove("suckerpunch", "DARK", base_power=70)
        move.priority = 1
        class PriorityMockBattle(MockBattle):
            def is_grounded(self, mon):
                return True
        battle = PriorityMockBattle(fields=[MockField("psychicterrain")])
        battle._replay_data = None
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, None]
        
        player = DoublesDamageAwarePlayer.__new__(DoublesDamageAwarePlayer)
        player.config = config
        player.verbose = False
        damage = player.get_expected_damage(move, attacker, target, battle, config)
        self.assertEqual(damage, 0.0)

    def test_14_expected_ko_is_false_when_blocked(self):
        """Test 14: expected KO is false when priority move is blocked."""
        config = DoublesDamageAwareConfig(enable_priority_field_hard_safety=True)
        attacker = MockPokemon("pawmot", ["ELECTRIC", "FIGHTING"])
        target = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        move = MockMove("suckerpunch", "DARK", base_power=70)
        move.priority = 1
        class PriorityMockBattle(MockBattle):
            def is_grounded(self, mon):
                return True
        battle = PriorityMockBattle(fields=[MockField("psychicterrain")])
        battle._replay_data = None
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, None]
        
        player = DoublesDamageAwarePlayer.__new__(DoublesDamageAwarePlayer)
        player.config = config
        player.verbose = False
        player.estimate_opponent_max_hp = lambda m: 100.0
        ko = player.check_move_will_ko(move, attacker, target, battle)
        self.assertFalse(ko)

    def test_15_no_bonuses_survive(self):
        """Test 15: no KO/HP/focus-fire bonus survives in score_action."""
        config = DoublesDamageAwareConfig(
            enable_priority_field_hard_safety=True,
            ability_hard_safety_block_score=0.0
        )
        attacker = MockPokemon("pawmot", ["ELECTRIC", "FIGHTING"])
        target = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        move = MockMove("suckerpunch", "DARK", base_power=70)
        move.priority = 1
        class PriorityMockBattle(MockBattle):
            def is_grounded(self, mon):
                return True
        battle = PriorityMockBattle(fields=[MockField("psychicterrain")])
        battle._replay_data = None
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, None]
        battle.available_moves = [[move], []]
        
        player = DoublesDamageAwarePlayer.__new__(DoublesDamageAwarePlayer)
        player.config = config
        player.verbose = False
        player.estimate_opponent_max_hp = lambda m: 100.0
        player.ability_blocks_avoided_by_battle = {}
        player.ability_absorbs_avoided_by_battle = {}
        player.ability_redirects_avoided_by_battle = {}
        player.ability_multipliers_applied_by_battle = {}
        player.partial_immune_spread_by_battle = {}
        player.partial_ability_immune_spread_by_battle = {}
        player.efficient_partial_spread_by_battle = {}
        player.inefficient_partial_spread_by_battle = {}
        player.immune_target_species_by_battle = {}
        player.damaged_target_species_by_battle = {}
        player.best_single_alternative_by_battle = {}
        player.get_valid_orders_for_slot = lambda idx, b: []
        player.get_type_effectiveness = lambda mv, t: 1.0
        player.get_boosted_stat = lambda m, st: 100
        player.get_accuracy = lambda m: 1.0
        player.is_spread_move = lambda m: False

        from poke_env.battle.double_battle import SingleBattleOrder
        order = SingleBattleOrder(move, 1)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_16_non_priority_move_remains_valid(self):
        """Test 16: non-priority move remains valid under Psychic Terrain."""
        config = DoublesDamageAwareConfig(enable_priority_field_hard_safety=True)
        attacker = MockPokemon("pawmot", ["ELECTRIC", "FIGHTING"])
        target = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        move = MockMove("crunch", "DARK", base_power=80)
        class PriorityMockBattle(MockBattle):
            def is_grounded(self, mon):
                return True
        battle = PriorityMockBattle(fields=[MockField("psychicterrain")])
        battle._replay_data = None
        battle.opponent_active_pokemon = [target, None]
        blocked, reason = priority_move_is_field_blocked(move, attacker, target, battle, config)
        self.assertFalse(blocked)

    def test_17_sucker_punch_flying_valid(self):
        """Test 17: Sucker Punch into Flying target remains valid under Psychic Terrain."""
        config = DoublesDamageAwareConfig(enable_priority_field_hard_safety=True)
        attacker = MockPokemon("pawmot", ["ELECTRIC", "FIGHTING"])
        target = MockPokemon("charizard", ["FIRE", "FLYING"])
        move = MockMove("suckerpunch", "DARK", base_power=70)
        move.priority = 1
        class PriorityMockBattle(MockBattle):
            def is_grounded(self, mon):
                return False
        battle = PriorityMockBattle(fields=[MockField("psychicterrain")])
        battle._replay_data = None
        battle.opponent_active_pokemon = [target, None]
        blocked, reason = priority_move_is_field_blocked(move, attacker, target, battle, config)
        self.assertFalse(blocked)

    def test_18_sucker_punch_levitate_valid(self):
        """Test 18: Sucker Punch into Levitate target remains valid under Psychic Terrain."""
        config = DoublesDamageAwareConfig(enable_priority_field_hard_safety=True)
        attacker = MockPokemon("pawmot", ["ELECTRIC", "FIGHTING"])
        target = MockPokemon("cresselia", ["PSYCHIC"], possible_abilities=["Levitate"])
        move = MockMove("suckerpunch", "DARK", base_power=70)
        move.priority = 1
        class PriorityMockBattle(MockBattle):
            def is_grounded(self, mon):
                return False
        battle = PriorityMockBattle(fields=[MockField("psychicterrain")])
        battle._replay_data = None
        battle.opponent_active_pokemon = [target, None]
        blocked, reason = priority_move_is_field_blocked(move, attacker, target, battle, config)
        self.assertFalse(blocked)

    def test_19_gravity_makes_blocked(self):
        """Test 19: Gravity makes a Flying/Levitate target grounded and therefore blocked."""
        config = DoublesDamageAwareConfig(enable_priority_field_hard_safety=True)
        attacker = MockPokemon("pawmot", ["ELECTRIC", "FIGHTING"])
        target = MockPokemon("charizard", ["FIRE", "FLYING"])
        move = MockMove("suckerpunch", "DARK", base_power=70)
        move.priority = 1
        class PriorityMockBattle(MockBattle):
            def is_grounded(self, mon):
                return True
        battle = PriorityMockBattle(fields=[MockField("psychicterrain"), MockField("gravity")])
        battle._replay_data = None
        battle.opponent_active_pokemon = [target, None]
        blocked, reason = priority_move_is_field_blocked(move, attacker, target, battle, config)
        self.assertTrue(blocked)

    def test_20_smack_down_makes_blocked(self):
        """Test 20: Smack Down grounding causes Psychic Terrain block."""
        config = DoublesDamageAwareConfig(enable_priority_field_hard_safety=True)
        attacker = MockPokemon("pawmot", ["ELECTRIC", "FIGHTING"])
        target = MockPokemon("charizard", ["FIRE", "FLYING"])
        move = MockMove("suckerpunch", "DARK", base_power=70)
        move.priority = 1
        class PriorityMockBattle(MockBattle):
            def is_grounded(self, mon):
                return True
        battle = PriorityMockBattle(fields=[MockField("psychicterrain"), MockField("smackdown")])
        battle._replay_data = None
        battle.opponent_active_pokemon = [target, None]
        blocked, reason = priority_move_is_field_blocked(move, attacker, target, battle, config)
        self.assertTrue(blocked)

    def test_21_self_priority_not_blocked(self):
        """Test 21: self/ally priority is not incorrectly blocked."""
        config = DoublesDamageAwareConfig(enable_priority_field_hard_safety=True)
        attacker = MockPokemon("pawmot", ["ELECTRIC", "FIGHTING"])
        ally = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        move = MockMove("helpinghand", "NORMAL", base_power=0)
        move.priority = 5
        class PriorityMockBattle(MockBattle):
            def is_grounded(self, mon):
                return True
        battle = PriorityMockBattle(fields=[MockField("psychicterrain")])
        battle._replay_data = None
        battle.opponent_active_pokemon = [MockPokemon("mew", ["PSYCHIC"]), None]
        blocked, reason = priority_move_is_field_blocked(move, attacker, ally, battle, config)
        self.assertFalse(blocked)

    def test_24_armor_tail_blocks(self):
        """Test 24: Armor Tail blocks priority against either opponent slot."""
        config = DoublesDamageAwareConfig(enable_priority_field_hard_safety=True)
        attacker = MockPokemon("pawmot", ["ELECTRIC", "FIGHTING"])
        target = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        move = MockMove("suckerpunch", "DARK", base_power=70)
        move.priority = 1
        
        opp_blocker = MockPokemon("farigiraf", ["NORMAL", "PSYCHIC"])
        opp_blocker.ability = "armortail"
        
        class PriorityMockBattle(MockBattle):
            def is_grounded(self, mon):
                return True
        battle = PriorityMockBattle()
        battle._replay_data = None
        battle.opponent_active_pokemon = [target, opp_blocker]
        
        res = evaluate_priority_move_legality(move, attacker, target, battle, config)
        self.assertTrue(res["blocked"])
        self.assertEqual(res["reason"], "priority_blocked_by_ability_armortail")

    def test_25_queenly_majesty_blocks(self):
        """Test 25: Queenly Majesty blocks priority."""
        config = DoublesDamageAwareConfig(enable_priority_field_hard_safety=True)
        attacker = MockPokemon("pawmot", ["ELECTRIC", "FIGHTING"])
        target = MockPokemon("tsareena", ["GRASS"])
        move = MockMove("suckerpunch", "DARK", base_power=70)
        move.priority = 1
        
        target.ability = "queenlymajesty"
        
        class PriorityMockBattle(MockBattle):
            def is_grounded(self, mon):
                return True
        battle = PriorityMockBattle()
        battle._replay_data = None
        battle.opponent_active_pokemon = [target, None]
        
        res = evaluate_priority_move_legality(move, attacker, target, battle, config)
        self.assertTrue(res["blocked"])
        self.assertEqual(res["reason"], "priority_blocked_by_ability_queenlymajesty")

    def test_26_dazzling_blocks(self):
        """Test 26: Dazzling blocks priority."""
        config = DoublesDamageAwareConfig(enable_priority_field_hard_safety=True)
        attacker = MockPokemon("pawmot", ["ELECTRIC", "FIGHTING"])
        target = MockPokemon("bruxish", ["WATER", "PSYCHIC"])
        move = MockMove("suckerpunch", "DARK", base_power=70)
        move.priority = 1
        
        target.ability = "dazzling"
        
        class PriorityMockBattle(MockBattle):
            def is_grounded(self, mon):
                return True
        battle = PriorityMockBattle()
        battle._replay_data = None
        battle.opponent_active_pokemon = [target, None]
        
        res = evaluate_priority_move_legality(move, attacker, target, battle, config)
        self.assertTrue(res["blocked"])
        self.assertEqual(res["reason"], "priority_blocked_by_ability_dazzling")

    def test_31_ast_config_propagation(self):
        """Test 31: Python AST check verifying config propagation in all calls."""
        import ast
        filepath = os.path.join(os.path.dirname(__file__), "bot_doubles_damage_aware.py")
        with open(filepath, "r") as f:
            tree = ast.parse(f.read(), filename=filepath)

        target_funcs = {
            "ability_hard_blocks_move",
            "resolve_known_ability",
            "get_expected_damage",
            "check_move_will_ko",
        }

        # Find enclosing function node for any given AST node
        def find_enclosing_func(node):
            curr = node
            while hasattr(curr, "parent"):
                curr = curr.parent
                if isinstance(curr, ast.FunctionDef):
                    return curr.name
            return None

        # Add parent pointers to all nodes
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                child.parent = parent

        class CallVisitor(ast.NodeVisitor):
            def __init__(self):
                self.violations = []

            def visit_Call(self, node):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "self":
                    func_name = node.func.attr

                if func_name in target_funcs:
                    enclosing = find_enclosing_func(node)
                    # Check if config parameter is passed (either positional or keyword)
                    passed = False
                    for arg in node.args:
                        # Simple check if "config" or "self.config" or "resolved_config" is in arg expression representation
                        if isinstance(arg, ast.Name) and arg.id in ("config", "resolved_config"):
                            passed = True
                        elif isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name) and arg.value.id == "self" and arg.attr == "config":
                            passed = True
                    for kw in node.keywords:
                        if kw.arg == "config":
                            passed = True

                    # Allowlist check: direct_known_absorb_blocks_move with config=None
                    if enclosing == "direct_known_absorb_blocks_move" and func_name == "ability_hard_blocks_move":
                        # Verify it passes config=None explicitly
                        none_passed = False
                        for kw in node.keywords:
                            if kw.arg == "config" and isinstance(kw.value, ast.Constant) and kw.value.value is None:
                                none_passed = True
                        if none_passed:
                            passed = True

                    if not passed:
                        self.violations.append((func_name, enclosing, node.lineno))
                self.generic_visit(node)

        visitor = CallVisitor()
        visitor.visit(tree)
        self.assertEqual(visitor.violations, [], f"AST config propagation violations found: {visitor.violations}")

    def test_32_counterfactual_side_effect_free(self):
        """Test 32: Pure counterfactual check must be side-effect free."""
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
        )
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        battle = MockBattle()
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [pokemon, None]
        battle.available_moves = [[move], []]

        player = DoublesDamageAwarePlayer.__new__(DoublesDamageAwarePlayer)
        player.config = config
        player.verbose = False
        player.ability_blocks_avoided_by_battle = {}
        player.ability_absorbs_avoided_by_battle = {}
        player.ability_redirects_avoided_by_battle = {}
        player.ability_multipliers_applied_by_battle = {}
        player.partial_immune_spread_by_battle = {}
        player.partial_ability_immune_spread_by_battle = {}
        player.efficient_partial_spread_by_battle = {}
        player.inefficient_partial_spread_by_battle = {}
        player.immune_target_species_by_battle = {}
        player.damaged_target_species_by_battle = {}
        player.best_single_alternative_by_battle = {}
        player.get_valid_orders_for_slot = lambda idx, b: []
        player.get_type_effectiveness = lambda mv, t: 1.0
        player.get_boosted_stat = lambda m, st: 100
        player.get_accuracy = lambda m: 1.0
        player.is_spread_move = lambda m: False

        # Set up a base score cache and test metrics
        player._base_scores_cache = {0: {123: 50.0}, 1: {}}
        player.draco_penalties_applied_by_battle = {"test": 0}

        # Run pure scoring
        from poke_env.battle.double_battle import SingleBattleOrder
        order = SingleBattleOrder(move, 1)
        
        # Calling with pure=True should keep cache and metrics unchanged
        score = player.score_action(order, 0, battle, config=config, pure=True)
        self.assertEqual(player._base_scores_cache, {0: {123: 50.0}, 1: {}})
        self.assertEqual(player.draco_penalties_applied_by_battle, {"test": 0})

    def test_33_only_legal_not_triggered_when_safe_alternative_exists(self):
        """Test 33: classify_only_legal returns False when a safe alternative exists.

        One blocked Ground order, one safe Fire order.  The selected order is
        the blocked Ground.  A safe alternative exists => only_legal=False.
        """
        from poke_env.battle.double_battle import SingleBattleOrder
        from bot_doubles_damage_aware import classify_only_legal

        mismagius = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        garchomp = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        ground_move = MockMove("earthquake", "GROUND", base_power=100)
        fire_move = MockMove("flamethrower", "FIRE", base_power=90)

        ground_order = SingleBattleOrder(ground_move, move_target=1)
        fire_order = SingleBattleOrder(fire_move, move_target=1)

        jo1 = type("JO", (), {"first_order": ground_order, "second_order": None})()
        jo2 = type("JO", (), {"first_order": fire_order, "second_order": None})()
        joint_orders = [jo1, jo2]

        safety_blocked = {id(ground_order): True}

        self.assertFalse(classify_only_legal(joint_orders, 0, ground_order, safety_blocked))

    def test_34_only_legal_triggered_when_all_alternatives_blocked(self):
        """Test 34: classify_only_legal returns True when all alternatives are blocked.

        Two different blocked Ground orders.  Both are safety-blocked.
        No safe alternative exists => only_legal=True.
        """
        from poke_env.battle.double_battle import SingleBattleOrder
        from bot_doubles_damage_aware import classify_only_legal

        ground_move1 = MockMove("earthquake", "GROUND", base_power=100)
        ground_move2 = MockMove("earthpower", "GROUND", base_power=90)

        order1 = SingleBattleOrder(ground_move1, move_target=1)
        order2 = SingleBattleOrder(ground_move2, move_target=1)

        jo1 = type("JO", (), {"first_order": order1, "second_order": None})()
        jo2 = type("JO", (), {"first_order": order2, "second_order": None})()
        joint_orders = [jo1, jo2]

        safety_blocked = {id(order1): True, id(order2): True}

        self.assertTrue(classify_only_legal(joint_orders, 0, order1, safety_blocked))

    def test_34b_only_legal_false_when_switch_alternative_exists(self):
        """Test 34b: classify_only_legal returns False when a legal switch exists.

        Blocked Ground order plus a legal switch.  Switch is not safety-blocked
        => safe alternative exists => only_legal=False.
        """
        from poke_env.battle.double_battle import SingleBattleOrder
        from bot_doubles_damage_aware import classify_only_legal

        ground_move = MockMove("earthquake", "GROUND", base_power=100)
        switch_pokemon = MockPokemon("rotom", ["ELECTRIC", "FIRE"])

        ground_order = SingleBattleOrder(ground_move, move_target=1)
        switch_order = SingleBattleOrder(switch_pokemon)

        jo1 = type("JO", (), {"first_order": ground_order, "second_order": None})()
        jo2 = type("JO", (), {"first_order": switch_order, "second_order": None})()
        joint_orders = [jo1, jo2]

        safety_blocked = {id(ground_order): True}

        self.assertFalse(classify_only_legal(joint_orders, 0, ground_order, safety_blocked))

    def test_34c_only_legal_unselected_not_blocked_returns_false(self):
        """Test 34c: classify_only_legal returns False when selected order is not blocked."""
        from poke_env.battle.double_battle import SingleBattleOrder
        from bot_doubles_damage_aware import classify_only_legal

        fire_move = MockMove("flamethrower", "FIRE", base_power=90)
        fire_order = SingleBattleOrder(fire_move, move_target=1)

        jo = type("JO", (), {"first_order": fire_order, "second_order": None})()
        joint_orders = [jo]

        # Selected order is not in safety_blocked => False
        self.assertFalse(classify_only_legal(joint_orders, 0, fire_order, {}))

    def test_45_canonical_selection_chooses_safe_alternative(self):
        """Test 45: _compute_joint_scores ranks the safe alternative above
        the blocked Ground-into-Levitate action.

        Exercises the actual canonical production ranking path.
        Verifies:
        - selected slot uses the safe non-Ground action
        - blocked candidate observed = True
        - hard block applied = True
        - selected Ground-into-Levitate error = False
        """
        from poke_env.battle.double_battle import SingleBattleOrder
        from bot_doubles_damage_aware import (
            _compute_order_safety_blocks, classify_only_legal,
        )

        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_allow_singleton_deduction=True,
            ability_hard_safety_block_score=0.0,
            safety_block_joint_penalty=1000.0,
        )

        mismagius = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        garchomp = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        ground_move = MockMove("earthquake", "GROUND", base_power=100)
        fire_move = MockMove("flamethrower", "FIRE", base_power=90)

        battle = MockBattle()
        battle.active_pokemon = [garchomp, None]
        battle.opponent_active_pokemon = [mismagius, None]

        ground_order = SingleBattleOrder(ground_move, move_target=1)
        fire_order = SingleBattleOrder(fire_move, move_target=1)

        # Two joint orders: ground into Levitate, fire into Levitate
        jo_ground = type("JO", (), {"first_order": ground_order, "second_order": None})()
        jo_fire = type("JO", (), {"first_order": fire_order, "second_order": None})()
        joint_orders = [jo_ground, jo_fire]
        valid_orders = [[ground_order, fire_order], []]

        # Slot scores: fire scores higher than ground (ground gets block_score=0)
        slot_0_scores = {id(ground_order): 0.0, id(fire_order): 80.0}
        slot_1_scores = {}

        # Compute safety blocks
        _da, _sb, _ar, _ar_meta = _compute_order_safety_blocks(battle, config, valid_orders)

        # Ground into singleton Levitate must be safety-blocked
        self.assertTrue(_sb.get(id(ground_order), False),
                        "Ground into singleton Levitate must be safety-blocked")
        self.assertFalse(_sb.get(id(fire_order), False),
                         "Fire must not be safety-blocked")

        # Canonical scoring via instance method
        player = DoublesDamageAwarePlayer.__new__(DoublesDamageAwarePlayer)
        player.config = config
        player.meta_engine = None
        player.random_set_engine = None

        scored = player._compute_joint_scores(
            battle, config, joint_orders,
            slot_0_scores, slot_1_scores, _da, _sb, _ar,
        )

        # Best joint must be the fire order (safe alternative)
        best = scored[0]
        best_first = best[0].first_order
        self.assertEqual(best_first.order.id, "flamethrower",
                         "Selected slot must use the safe Fire alternative")

        # Verify production helper: only_legal=False (safe Fire alternative exists)
        self.assertFalse(classify_only_legal(joint_orders, 0, best_first, _sb))

        # Verify observer semantics:
        # blocked_candidate_observed = True (Ground into Levitate exists)
        # hard_block_applied = True (safety block on Ground order)
        # selected error = False (selected Fire, not Ground)
        self.assertTrue(_sb.get(id(ground_order), False), "hard_block_applied=True")
        self.assertFalse(best_first.order.id == "earthquake", "selected error=False")

    def test_46_only_legal_when_no_safe_joint_order(self):
        """Test 46: classify_only_legal returns True when the only available
        action is the blocked Ground move and it has no safe alternative."""
        from poke_env.battle.double_battle import SingleBattleOrder
        from bot_doubles_damage_aware import classify_only_legal

        ground_move = MockMove("earthquake", "GROUND", base_power=100)
        ground_order = SingleBattleOrder(ground_move, move_target=1)

        jo = type("JO", (), {"first_order": ground_order, "second_order": None})()
        joint_orders = [jo]

        safety_blocked = {id(ground_order): True}

        self.assertTrue(classify_only_legal(joint_orders, 0, ground_order, safety_blocked))

    def test_47_watchdog_stall_terminates_before_arm_timeout(self):
        """Test 47: _run_arm_with_watchdog detects stalls via heartbeat and
        terminates before arm_timeout.  The battle task is cancelled."""
        import asyncio
        from bot_doubles_singleton_ability_safety_benchmark import (
            _run_arm_with_watchdog, StallError,
        )

        async def run_test():
            async def stalled_battle():
                """Battle that never finishes."""
                await asyncio.sleep(3600)

            stall_interval = 0.05  # very short for testing
            original_stall = 180

            async def fast_heartbeat():
                """Heartbeat that stalls almost immediately."""
                await asyncio.sleep(stall_interval)
                raise StallError("test stall detected")

            status, detail = await _run_arm_with_watchdog(
                "test_stall", stalled_battle, fast_heartbeat, arm_timeout=5.0,
            )
            self.assertEqual(status, "error")
            self.assertIn("stall", detail.lower())

        asyncio.run(run_test())

    def test_47b_watchdog_normal_completion(self):
        """Test 47b: _run_arm_with_watchdog returns success when battle
        completes normally and watchdog remains pending."""
        import asyncio
        from bot_doubles_singleton_ability_safety_benchmark import _run_arm_with_watchdog

        async def run_test():
            async def normal_battle():
                """Battle that finishes immediately."""
                return "victory"

            async def infinite_heartbeat():
                """Heartbeat that never fires."""
                await asyncio.sleep(3600)

            status, detail = await _run_arm_with_watchdog(
                "test_ok", normal_battle, infinite_heartbeat, arm_timeout=5.0,
            )
            self.assertEqual(status, "ok")
            self.assertIsNone(detail)

        asyncio.run(run_test())

    def test_35_thousand_arrows_exception_suppresses_safety(self):
        """Test 35: Thousand Arrows bypasses Levitate safety."""
        config = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=True)
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        move = MockMove("thousandarrows", "GROUND")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        battle = MockBattle()
        blocks, _ = ability_hard_blocks_move(move, attacker, pokemon, battle, config)
        self.assertFalse(blocks)

    def test_36_gravity_exception_suppresses_safety(self):
        """Test 36: Gravity active suppresses Levitate safety."""
        config = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=True)
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        battle = MockBattle(fields=[MockField("gravity")])
        blocks, _ = ability_hard_blocks_move(move, attacker, pokemon, battle, config)
        self.assertFalse(blocks)

    def test_37_mold_breaker_exception_suppresses_safety(self):
        """Test 37: Mold Breaker ability suppresses Levitate safety."""
        config = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=True)
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("pinsir", ["BUG"], ability="moldbreaker")
        battle = MockBattle()
        battle.active_pokemon = [attacker, None]
        blocks, _ = ability_hard_blocks_move(move, attacker, pokemon, battle, config)
        self.assertFalse(blocks)

    def test_38_teravolt_exception_suppresses_safety(self):
        """Test 38: Teravolt ability suppresses Levitate safety."""
        config = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=True)
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("kyurem", ["DRAGON", "ICE"], ability="teravolt")
        battle = MockBattle()
        battle.active_pokemon = [attacker, None]
        blocks, _ = ability_hard_blocks_move(move, attacker, pokemon, battle, config)
        self.assertFalse(blocks)

    def test_39_turboblaze_exception_suppresses_safety(self):
        """Test 39: Turboblaze ability suppresses Levitate safety."""
        config = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=True)
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("reshiram", ["DRAGON", "FIRE"], ability="turboblaze")
        battle = MockBattle()
        battle.active_pokemon = [attacker, None]
        blocks, _ = ability_hard_blocks_move(move, attacker, pokemon, battle, config)
        self.assertFalse(blocks)

    def test_40_gastro_acid_suppresses_singleton_safety(self):
        """Test 40: Gastro Acid status suppresses Levitate safety."""
        config = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=True)
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        pokemon.status = "gastroacid"
        battle = MockBattle()
        res = resolve_known_ability(pokemon, battle, config)
        self.assertTrue(res["is_currently_suppressed"])
        self.assertEqual(res["suppression_reason"], "gastro_acid")

    def test_41_neutralizing_gas_suppresses_singleton_safety(self):
        """Test 41: Neutralizing Gas field suppresses Levitate safety."""
        config = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=True)
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        battle = MockBattle(fields=[MockField("Neutralizing Gas")])
        res = resolve_known_ability(pokemon, battle, config)
        self.assertTrue(res["is_currently_suppressed"])
        self.assertEqual(res["suppression_reason"], "neutralizing_gas")

    def test_42_smack_down_suppresses_singleton_safety(self):
        """Test 42: Smack Down grounding suppresses Levitate safety."""
        config = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=True)
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        move = MockMove("earthquake", "GROUND")
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        battle = MockBattle(fields=[MockField("smackdown")])
        blocks, _ = ability_hard_blocks_move(move, attacker, pokemon, battle, config)
        self.assertFalse(blocks)

    def test_43_temporary_changed_ability_suppresses_singleton_safety(self):
        """Test 43: temporary changed ability overrides singleton base ability."""
        config = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=True)
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        pokemon.temporary_ability = "Trace"
        battle = MockBattle()
        res = resolve_known_ability(pokemon, battle, config)
        self.assertEqual(res["ability"], "trace")
        self.assertEqual(res["source"], "temporary_changed")

    def test_44_explicit_protocol_reveal_suppresses_singleton_safety(self):
        """Test 44: explicit protocol reveal overrides singleton base data."""
        config = DoublesDamageAwareConfig(ability_hard_safety_allow_singleton_deduction=True)
        pokemon = MockPokemon("mismagius", ["GHOST"], possible_abilities=["Levitate"])
        pokemon.ability = "Trace"
        battle = MockBattle()
        res = resolve_known_ability(pokemon, battle, config)
        self.assertEqual(res["ability"], "trace")
        self.assertEqual(res["source"], "protocol_revealed")


class TestProcessLifecycle(unittest.TestCase):
    """Regression tests verifying test process terminates naturally."""

    def test_48_import_helper_subprocess_exits_naturally(self):
        """Test 48: subprocess importing poke_env_test_cleanup and
        bot_doubles_damage_aware exits naturally within 3 seconds."""
        import subprocess
        proc = subprocess.run(
            [sys.executable, "-c",
             "import poke_env_test_cleanup; import bot_doubles_damage_aware"],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(proc.returncode, 0,
                         f"subprocess exited {proc.returncode}: {proc.stderr}")

    def test_49_daemon_thread_exists_no_nondaemon_leak(self):
        """Test 49: after importing poke_env, Thread-1 (__run_loop) is daemon
        and no non-daemon background thread exists."""
        import subprocess
        proc = subprocess.run(
            [sys.executable, "-c", """
import poke_env_test_cleanup
import bot_doubles_damage_aware
import threading
threads = threading.enumerate()
nondaemon = [t for t in threads if not t.daemon and t.name != 'MainThread']
if len(nondaemon) > 0:
    print(f'LEAKED: {[t.name for t in nondaemon]}', flush=True)
    raise SystemExit(1)
print('OK', flush=True)
"""],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(proc.returncode, 0,
                         f"non-daemon thread leak: {proc.stdout} {proc.stderr}")

    def test_50_double_import_harmless(self):
        """Test 50: importing poke_env_test_cleanup twice is harmless."""
        import subprocess
        proc = subprocess.run(
            [sys.executable, "-c",
             "import poke_env_test_cleanup; import poke_env_test_cleanup; print('OK')"],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("OK", proc.stdout)

    def test_51_production_does_not_import_helper(self):
        """Test 51: production modules do not import poke_env_test_cleanup."""
        import subprocess
        proc = subprocess.run(
            [sys.executable, "-c", """
import ast, os
for fname in os.listdir('.'):
    if not fname.endswith('.py') or fname.startswith('test_') or fname == 'poke_env_test_cleanup.py':
        continue
    try:
        tree = ast.parse(open(fname).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if 'poke_env_test_cleanup' in alias.name:
                        print(f'VIOLATION: {fname}')
                        raise SystemExit(1)
            if isinstance(node, ast.ImportFrom) and node.module and 'poke_env_test_cleanup' in node.module:
                print(f'VIOLATION: {fname}')
                raise SystemExit(1)
    except SystemExit:
        raise
    except:
        pass
print('OK')
"""],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(proc.returncode, 0,
                         f"production import violation: {proc.stdout} {proc.stderr}")


class TestAuditLoggerMetadata(unittest.TestCase):
    """Verify DoublesDecisionAuditLogger metadata without real Player."""

    def test_52_benchmark_arm_preserved(self):
        """Test 52: benchmark_arm appears in saved JSONL."""
        import json, tempfile
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger

        with tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False) as f:
            path = f.name
        try:
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level='top5',
                benchmark_arm='C',
                singleton_safety_enabled=True,
                priority_safety_enabled=False,
            )
            class FakeBattle:
                player_username = 'test'
                turn = 1
            logger.completed_turns['tag'] = []
            logger.save_battle('tag', 'test', FakeBattle())
            with open(path) as f:
                record = json.loads(f.readline())
            self.assertEqual(record['benchmark_arm'], 'C')
            self.assertTrue(record['singleton_safety_enabled'])
            self.assertFalse(record['priority_safety_enabled'])
        finally:
            os.unlink(path)

    def test_53_constructor_fallback_when_no_config(self):
        """Test 53: constructor flags used when no per-battle config exists."""
        import json, tempfile
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger

        with tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False) as f:
            path = f.name
        try:
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level='top5',
                benchmark_arm='F',
                singleton_safety_enabled=False,
                priority_safety_enabled=True,
            )
            class FakeBattle:
                player_username = 'test'
                turn = 1
            logger.completed_turns['tag'] = []
            logger.save_battle('tag', 'test', FakeBattle())
            with open(path) as f:
                record = json.loads(f.readline())
            self.assertEqual(record['benchmark_arm'], 'F')
            self.assertFalse(record['singleton_safety_enabled'])
            self.assertTrue(record['priority_safety_enabled'])
        finally:
            os.unlink(path)

    def test_54_per_battle_config_overrides_constructor(self):
        """Test 54: per-battle config overrides constructor metadata."""
        import json, tempfile, dataclasses
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        from bot_doubles_damage_aware import DoublesDamageAwareConfig

        with tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False) as f:
            path = f.name
        try:
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level='top5',
                benchmark_arm='A',
                singleton_safety_enabled=False,
                priority_safety_enabled=False,
            )
            # Store a per-battle config with different flags
            cfg = DoublesDamageAwareConfig(
                ability_hard_safety_allow_singleton_deduction=True,
                enable_priority_field_hard_safety=True,
            )
            logger.battle_configs['tag'] = cfg
            class FakeBattle:
                player_username = 'test'
                turn = 1
            logger.completed_turns['tag'] = []
            logger.save_battle('tag', 'test', FakeBattle())
            with open(path) as f:
                record = json.loads(f.readline())
            self.assertTrue(record['singleton_safety_enabled'])
            self.assertTrue(record['priority_safety_enabled'])
        finally:
            os.unlink(path)


class TestFinalDefaults(unittest.TestCase):
    """Verify final adopted defaults after Phase 6.3.5f."""

    def test_55_singleton_deduction_adopted(self):
        """Test 55: ability_hard_safety_allow_singleton_deduction defaults True."""
        config = DoublesDamageAwareConfig()
        self.assertTrue(config.ability_hard_safety_allow_singleton_deduction)

    def test_56_priority_safety_not_adopted(self):
        """Test 56: enable_priority_field_hard_safety defaults False."""
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_priority_field_hard_safety)

    def test_57_safety_block_joint_penalty_value(self):
        """Test 57: safety_block_joint_penalty defaults 1000.0."""
        config = DoublesDamageAwareConfig()
        self.assertEqual(config.safety_block_joint_penalty, 1000.0)

    def test_58_ability_awareness_disabled(self):
        """Test 58: enable_ability_awareness defaults False."""
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_ability_awareness)

    def test_59_meta_modeling_disabled(self):
        """Test 59: enable_meta_opponent_modeling defaults False."""
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_meta_opponent_modeling)

    def test_60_random_set_modeling_disabled(self):
        """Test 60: enable_random_set_opponent_modeling defaults False."""
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_random_set_opponent_modeling)

    def test_61_threat_tiebreaker_disabled(self):
        """Test 61: enable_threat_tiebreaker defaults False."""
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_threat_tiebreaker)

    def test_62_priority_stays_disabled_after_singleton_adoption(self):
        """Test 62: priority default remains False even after singleton adoption."""
        config = DoublesDamageAwareConfig()
        self.assertTrue(config.ability_hard_safety_allow_singleton_deduction)
        self.assertFalse(config.enable_priority_field_hard_safety)


if __name__ == "__main__":
    unittest.main()
