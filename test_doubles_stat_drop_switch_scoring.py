"""Phase 6.4.7 — Conservative Stat-Drop Switch Scoring Tests.

Tests for the stat-drop switch pressure evaluation and scoring adjustments.
"""
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

import poke_env_test_cleanup  # noqa: F401

sys.path.insert(0, os.path.dirname(__file__))

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    classify_stat_drop_severity,
    summarize_negative_boosts,
    evaluate_stat_drop_switch_pressure,
)


class MockMove:
    def __init__(self, move_id, move_type, base_power=80, category_name="PHYSICAL"):
        self.id = move_id.lower().replace(" ", "")
        self.base_power = base_power
        self._type = move_type
        self._category_name = category_name

    @property
    def type(self):
        m = MagicMock()
        m.name = self._type
        return m

    @property
    def category(self):
        m = MagicMock()
        m.name = self._category_name
        return m


class MockPokemon:
    def __init__(self, species, types=None, ability=None, hp_fraction=1.0,
                 boosts=None, fainted=False, moves=None):
        self.species = species
        self._types = []
        for t in (types or []):
            m = MagicMock()
            m.name = t
            self._types.append(m)
        self._ability = ability
        self._current_hp_fraction = hp_fraction
        self._boosts = boosts or {}
        self._fainted = fainted
        self._moves = moves or {}
        self.fainted = fainted

    @property
    def current_hp_fraction(self):
        return self._current_hp_fraction

    @current_hp_fraction.setter
    def current_hp_fraction(self, val):
        self._current_hp_fraction = val

    @property
    def types(self):
        return self._types

    @property
    def type_1(self):
        return self._types[0] if self._types else None

    @property
    def type_2(self):
        return self._types[1] if len(self._types) > 1 else None

    @property
    def ability(self):
        return self._ability

    @property
    def boosts(self):
        return self._boosts

    def damage_multiplier(self, move):
        return 1.0

    def __bool__(self):
        return not self._fainted


class MockOrder:
    def __init__(self, order_obj, move_target):
        self.order = order_obj
        self.move_target = move_target


class MockBattle:
    def __init__(self, active_pokemon, opponent_active_pokemon, available_switches=None):
        self.active_pokemon = active_pokemon
        self.opponent_active_pokemon = opponent_active_pokemon
        self.available_switches = available_switches or []
        self.force_switch = [False, False]
        self.fields = []


class TestConfigDefaults(unittest.TestCase):
    def test_default_scoring_disabled(self):
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_stat_drop_switch_scoring)

    def test_default_penalties(self):
        config = DoublesDamageAwareConfig()
        self.assertEqual(config.stat_drop_switch_offensive_penalty, 90.0)
        self.assertEqual(config.stat_drop_switch_defensive_penalty, 35.0)
        self.assertEqual(config.stat_drop_switch_speed_penalty, 20.0)
        self.assertEqual(config.stat_drop_switch_unproductive_bonus, 80.0)
        self.assertEqual(config.stat_drop_switch_safe_switch_bonus, 80.0)

    def test_scoring_threshold_defaults(self):
        config = DoublesDamageAwareConfig()
        self.assertEqual(config.stat_drop_switch_offensive_stage_threshold, -1)
        self.assertEqual(config.stat_drop_switch_defensive_stage_threshold, -2)
        self.assertEqual(config.stat_drop_switch_speed_stage_threshold, -2)

    def test_diagnostics_still_on(self):
        config = DoublesDamageAwareConfig()
        self.assertTrue(config.enable_stat_drop_switch_diagnostics)

    def test_ability_awareness_disabled(self):
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_ability_awareness)


class TestClassifySeverity(unittest.TestCase):
    def test_offensive_minus2_triggers(self):
        boosts = {"atk": -2, "spa": 0, "def": 0, "spd": 0, "spe": 0}
        config = DoublesDamageAwareConfig()
        move = MockMove("tackle", "NORMAL", base_power=80, category_name="PHYSICAL")
        order = MockOrder(move, 1)
        result = classify_stat_drop_severity(boosts, config, [order])
        self.assertTrue(result["severe"])
        self.assertIn("offensive", result["categories"])

    def test_speed_minus2_triggers(self):
        boosts = {"atk": 0, "spa": 0, "def": 0, "spd": 0, "spe": -2}
        config = DoublesDamageAwareConfig()
        result = classify_stat_drop_severity(boosts, config, [])
        self.assertTrue(result["severe"])
        self.assertIn("speed", result["categories"])

    def test_no_drop_no_severe(self):
        boosts = {"atk": 0, "spa": 0, "def": 0, "spd": 0, "spe": 0}
        config = DoublesDamageAwareConfig()
        result = classify_stat_drop_severity(boosts, config, [])
        self.assertFalse(result["severe"])

    def test_minus1_not_severe(self):
        boosts = {"atk": -1, "spa": 0, "def": 0, "spd": 0, "spe": 0}
        config = DoublesDamageAwareConfig()
        move = MockMove("tackle", "NORMAL", base_power=80, category_name="PHYSICAL")
        order = MockOrder(move, 1)
        result = classify_stat_drop_severity(boosts, config, [order])
        self.assertFalse(result["severe"])

    def test_defensive_minus2_triggers(self):
        boosts = {"atk": 0, "spa": 0, "def": -2, "spd": 0, "spe": 0}
        config = DoublesDamageAwareConfig()
        result = classify_stat_drop_severity(boosts, config, [])
        self.assertTrue(result["severe"])
        self.assertIn("defensive", result["categories"])


class TestSummarizeNegativeBoosts(unittest.TestCase):
    def test_offensive_negative_stages(self):
        mon = MockPokemon("testmon", ["NORMAL"],
                          boosts={"atk": -2, "spa": -1, "def": 0, "spd": 0, "spe": 0})
        result = summarize_negative_boosts(mon)
        self.assertEqual(result["offensive_negative_stages"], 3)
        self.assertEqual(result["total_negative_stages"], 3)

    def test_severe_negative_boost_minus3(self):
        mon = MockPokemon("testmon", ["NORMAL"],
                          boosts={"atk": -3, "spa": 0, "def": 0, "spd": 0, "spe": 0})
        result = summarize_negative_boosts(mon)
        self.assertTrue(result["severe_negative_boost"])


class TestEvaluatePressure(unittest.TestCase):
    def _config_on(self):
        c = DoublesDamageAwareConfig()
        c.enable_stat_drop_switch_scoring = True
        return c

    def _make_battle(self):
        return MockBattle(
            active_pokemon=[
                MockPokemon("mienshao", ["FIGHTING"], boosts={"atk": -2}),
                MockPokemon("bastiodon", ["ROCK", "STEEL"]),
            ],
            opponent_active_pokemon=[
                MockPokemon("abomasnow", ["GRASS", "ICE"], hp_fraction=0.8),
                MockPokemon("sableye", ["DARK", "GHOST"]),
            ],
        )

    def test_offensive_drop_pressure_when_disabled(self):
        config = DoublesDamageAwareConfig()
        config.enable_stat_drop_switch_scoring = False
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": -2})
        move = MockMove("tackle", "NORMAL", base_power=80, category_name="PHYSICAL")
        move_order = MockOrder(move, 1)
        result = evaluate_stat_drop_switch_pressure(mon, [move_order], None, config)
        self.assertFalse(result["should_consider_switch"])
        self.assertIn("scoring_disabled", result["reasons"])

    def test_no_drop_no_pressure(self):
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": 0})
        result = evaluate_stat_drop_switch_pressure(mon, [], None, config)
        self.assertFalse(result["should_consider_switch"])

    def test_offensive_drop_pressure_no_switches(self):
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": -2},
                          hp_fraction=0.8)
        move = MockMove("tackle", "NORMAL", base_power=80, category_name="PHYSICAL")
        move_order = MockOrder(move, 1)
        result = evaluate_stat_drop_switch_pressure(mon, [move_order], None, config)
        self.assertTrue(result["offensive_drop"])
        self.assertIn("no_legal_switch", result["reasons"])

    def test_offensive_drop_with_switch_pressure(self):
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": -2},
                          hp_fraction=0.8)
        switch_mon = MockPokemon("switchin", ["WATER"])
        switch_order = MockOrder(switch_mon, 0)
        move = MockMove("tackle", "NORMAL", base_power=80, category_name="PHYSICAL")
        move_order = MockOrder(move, 1)
        result = evaluate_stat_drop_switch_pressure(mon, [switch_order, move_order], None, config)
        self.assertTrue(result["should_consider_switch"])
        self.assertIn("offensive_drop_penalty", result["reasons"])
        self.assertGreater(result["stay_penalty"], 0)

    def test_defensive_only_weaker(self):
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": 0, "def": -2},
                          hp_fraction=0.8)
        switch_mon = MockPokemon("switchin", ["WATER"])
        switch_order = MockOrder(switch_mon, 0)
        move = MockMove("tackle", "NORMAL", base_power=80, category_name="PHYSICAL")
        move_order = MockOrder(move, 1)
        result = evaluate_stat_drop_switch_pressure(mon, [switch_order, move_order], None, config)
        self.assertTrue(result["should_consider_switch"])
        self.assertTrue(result["defensive_drop"])
        self.assertIn("defensive_drop_penalty", result["reasons"])

    def test_speed_only_weaker(self):
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": 0, "spe": -2},
                          hp_fraction=0.8)
        switch_mon = MockPokemon("switchin", ["WATER"])
        switch_order = MockOrder(switch_mon, 0)
        result = evaluate_stat_drop_switch_pressure(mon, [switch_order], None, config)
        self.assertTrue(result["should_consider_switch"])
        self.assertTrue(result["speed_drop"])
        self.assertIn("speed_drop_penalty", result["reasons"])

    def test_low_hp_blocks_pressure(self):
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": -2},
                          hp_fraction=0.15)
        switch_mon = MockPokemon("switchin", ["WATER"])
        switch_order = MockOrder(switch_mon, 0)
        move = MockMove("tackle", "NORMAL", base_power=80, category_name="PHYSICAL")
        move_order = MockOrder(move, 1)
        result = evaluate_stat_drop_switch_pressure(mon, [switch_order, move_order], None, config)
        self.assertFalse(result["should_consider_switch"])
        self.assertIn("active_hp_below_low_hp_block", result["reasons"])

    def test_protect_suppresses_pressure(self):
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": -2},
                          hp_fraction=0.5)
        switch_mon = MockPokemon("switchin", ["WATER"])
        switch_order = MockOrder(switch_mon, 0)
        protect_move = MockMove("protect", "NORMAL", base_power=0, category_name="STATUS")
        protect_order = MockOrder(protect_move, 0)
        move = MockMove("tackle", "NORMAL", base_power=80, category_name="PHYSICAL")
        move_order = MockOrder(move, 1)
        result = evaluate_stat_drop_switch_pressure(
            mon, [switch_order, protect_order, move_order], None, config)
        self.assertFalse(result["should_consider_switch"])
        self.assertIn("protect_available", result["reasons"])

    def test_return_fields_complete(self):
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": -2, "spe": -2},
                          hp_fraction=0.8)
        switch_mon = MockPokemon("switchin", ["WATER"])
        switch_order = MockOrder(switch_mon, 0)
        move = MockMove("tackle", "NORMAL", base_power=80, category_name="PHYSICAL")
        move_order = MockOrder(move, 1)
        result = evaluate_stat_drop_switch_pressure(mon, [switch_order, move_order], None, config)
        fields = [
            "should_consider_switch", "categories", "offensive_drop",
            "defensive_drop", "speed_drop", "productive_action_available",
            "best_non_switch_score", "switch_available", "active_hp_fraction",
            "reasons", "stay_penalty",
        ]
        for f in fields:
            self.assertIn(f, result, f"Missing field: {f}")

    def test_no_hidden_info(self):
        import inspect
        source = inspect.getsource(evaluate_stat_drop_switch_pressure)
        self.assertNotIn("possible_abilities", source)
        self.assertNotIn("meta_engine", source)
        self.assertNotIn("random_set_engine", source)


class TestScoringThresholds(unittest.TestCase):
    """Tests for scoring-specific thresholds (-1 offensive, -2 defensive/speed)."""

    def _config_on(self):
        c = DoublesDamageAwareConfig()
        c.enable_stat_drop_switch_scoring = True
        return c

    def test_offensive_minus1_pressure(self):
        """Offensive -1 now creates pressure when damaging move exists."""
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": -1},
                          hp_fraction=0.8)
        switch_mon = MockPokemon("switchin", ["WATER"])
        switch_order = MockOrder(switch_mon, 0)
        move = MockMove("tackle", "NORMAL", base_power=80, category_name="PHYSICAL")
        move_order = MockOrder(move, 1)
        result = evaluate_stat_drop_switch_pressure(mon, [switch_order, move_order], None, config)
        self.assertTrue(result["should_consider_switch"], f"Reasons: {result['reasons']}")
        self.assertTrue(result["offensive_drop"])

    def test_offensive_minus1_no_damaging_move(self):
        """Offensive -1 without matching damaging move = no pressure."""
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": -1},
                          hp_fraction=0.8)
        switch_mon = MockPokemon("switchin", ["WATER"])
        switch_order = MockOrder(switch_mon, 0)
        # No damaging move — only switch order
        result = evaluate_stat_drop_switch_pressure(mon, [switch_order], None, config)
        self.assertFalse(result["should_consider_switch"])

    def test_defensive_minus1_no_pressure(self):
        """Defensive -1 does NOT create pressure."""
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": 0, "def": -1},
                          hp_fraction=0.8)
        switch_mon = MockPokemon("switchin", ["WATER"])
        switch_order = MockOrder(switch_mon, 0)
        result = evaluate_stat_drop_switch_pressure(mon, [switch_order], None, config)
        self.assertFalse(result["should_consider_switch"])

    def test_defensive_minus2_pressure(self):
        """Defensive -2 creates pressure."""
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": 0, "def": -2},
                          hp_fraction=0.8)
        switch_mon = MockPokemon("switchin", ["WATER"])
        switch_order = MockOrder(switch_mon, 0)
        result = evaluate_stat_drop_switch_pressure(mon, [switch_order], None, config)
        self.assertTrue(result["should_consider_switch"])
        self.assertTrue(result["defensive_drop"])

    def test_speed_minus1_no_pressure(self):
        """Speed -1 does NOT create pressure."""
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": 0, "spe": -1},
                          hp_fraction=0.8)
        switch_mon = MockPokemon("switchin", ["WATER"])
        switch_order = MockOrder(switch_mon, 0)
        result = evaluate_stat_drop_switch_pressure(mon, [switch_order], None, config)
        self.assertFalse(result["should_consider_switch"])

    def test_speed_minus2_pressure(self):
        """Speed -2 creates pressure."""
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": 0, "spe": -2},
                          hp_fraction=0.8)
        switch_mon = MockPokemon("switchin", ["WATER"])
        switch_order = MockOrder(switch_mon, 0)
        result = evaluate_stat_drop_switch_pressure(mon, [switch_order], None, config)
        self.assertTrue(result["should_consider_switch"])
        self.assertTrue(result["speed_drop"])

    def test_threshold_source_offensive(self):
        """Threshold source reports offensive_-1."""
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": -1},
                          hp_fraction=0.8)
        switch_mon = MockPokemon("switchin", ["WATER"])
        switch_order = MockOrder(switch_mon, 0)
        move = MockMove("tackle", "NORMAL", base_power=80, category_name="PHYSICAL")
        move_order = MockOrder(move, 1)
        result = evaluate_stat_drop_switch_pressure(mon, [switch_order, move_order], None, config)
        self.assertIn("offensive_-1", result["threshold_source"])

    def test_threshold_source_mixed(self):
        """Mixed offensive + defensive = 'mixed'."""
        config = self._config_on()
        mon = MockPokemon("testmon", ["NORMAL"], boosts={"atk": -1, "def": -2},
                          hp_fraction=0.8)
        switch_mon = MockPokemon("switchin", ["WATER"])
        switch_order = MockOrder(switch_mon, 0)
        move = MockMove("tackle", "NORMAL", base_power=80, category_name="PHYSICAL")
        move_order = MockOrder(move, 1)
        result = evaluate_stat_drop_switch_pressure(mon, [switch_order, move_order], None, config)
        self.assertEqual("mixed", result["threshold_source"])
        self.assertIn("offensive", result["categories"])
        self.assertIn("defensive", result["categories"])


if __name__ == "__main__":
    unittest.main()
