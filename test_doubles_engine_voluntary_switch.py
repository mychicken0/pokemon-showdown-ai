#!/usr/bin/env python3
"""Tests for doubles_engine.voluntary_switch
extracted module.

ponytail: focused unit tests for
``evaluate_voluntary_switch_quality``.
"""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _Type:
    def __init__(self, name):
        self.name = name


class _FakePokemon:
    def __init__(self, type_1=None, type_2=None, current_hp_fraction=1.0):
        self.type_1 = type_1
        self.type_2 = type_2
        self.current_hp_fraction = current_hp_fraction

    def damage_multiplier(self, opp_type):
        opp_name = (
            getattr(opp_type, "name", str(opp_type)).lower()
            if opp_type
            else ""
        )
        if self.type_1 is None:
            return 1.0
        my_name = self.type_1.name.lower()
        chart = {
            ("electric", "ground"): 0.0,
            ("water", "electric"): 2.0,
            ("fire", "water"): 0.5,
            ("fire", "ground"): 2.0,
        }
        if (my_name, opp_name) in chart:
            return chart[(my_name, opp_name)]
        return 1.0


class _FakeBattle:
    def __init__(self, force_switch=None):
        self.force_switch = force_switch or [False, False]
        self.opponent_active_pokemon = [
            _FakePokemon(type_1=_Type("electric")),
            _FakePokemon(type_1=_Type("ground")),
        ]


class _FakeConfig:
    voluntary_switch_tempo_penalty = 35.0
    voluntary_switch_unsafe_candidate_penalty = 120.0
    voluntary_switch_quad_weak_penalty = 180.0
    voluntary_switch_double_threat_penalty = 160.0
    voluntary_switch_low_hp_candidate_penalty = 35.0
    voluntary_switch_repeat_penalty = 80.0
    voluntary_switch_min_risk_reduction = 1.0
    voluntary_switch_sacrifice_hp_threshold = 0.15
    voluntary_switch_useful_action_threshold = 40.0
    voluntary_switch_high_value_action_threshold = 120.0
    voluntary_switch_sacrifice_preserve_bench_bonus = 70.0


class TestReturnShape(unittest.TestCase):
    def test_missing_pokemon(self):
        from doubles_engine.voluntary_switch import (
            evaluate_voluntary_switch_quality,
        )
        result = evaluate_voluntary_switch_quality(
            None, None, 0, _FakeBattle(), 0.0, _FakeConfig()
        )
        self.assertFalse(result["eligible"])
        self.assertIn("missing_pokemon", result["reason_codes"])

    def test_forced_switch(self):
        from doubles_engine.voluntary_switch import (
            evaluate_voluntary_switch_quality,
        )
        battle = _FakeBattle(force_switch=[True, False])
        active = _FakePokemon(type_1=_Type("water"))
        candidate = _FakePokemon(type_1=_Type("electric"))
        result = evaluate_voluntary_switch_quality(
            active, candidate, 0, battle, 0.0, _FakeConfig()
        )
        self.assertFalse(result["eligible"])
        self.assertIn("forced_switch", result["reason_codes"])


class TestRiskComputation(unittest.TestCase):
    def test_basic_switch(self):
        from doubles_engine.voluntary_switch import (
            evaluate_voluntary_switch_quality,
        )
        active = _FakePokemon(type_1=_Type("water"))  # 2x to electric
        candidate = _FakePokemon(type_1=_Type("fire"))  # 2x to ground
        result = evaluate_voluntary_switch_quality(
            active, candidate, 0, _FakeBattle(), 0.0, _FakeConfig()
        )
        # Both have risk 2.0 -> risk_reduction = 0 -> no improvement
        self.assertTrue(result["eligible"])
        self.assertEqual(result["active_risk"], 2.0)
        self.assertEqual(result["candidate_risk"], 2.0)
        self.assertEqual(result["risk_reduction"], 0.0)
        self.assertFalse(result["switch_improves_position"])

    def test_risk_reduction(self):
        from doubles_engine.voluntary_switch import (
            evaluate_voluntary_switch_quality,
        )
        # Active is weak (water vs electric/ground = 2x); candidate is immune
        # to both (use a custom type setup)
        active = _FakePokemon(type_1=_Type("water"))
        # Candidate is electric type which is 0x to ground but 1x to electric
        candidate = _FakePokemon(type_1=_Type("electric"))
        result = evaluate_voluntary_switch_quality(
            active, candidate, 0, _FakeBattle(), 0.0, _FakeConfig()
        )
        # Active: max(2.0 to electric, 0.0 to ground since water has 1x to
        # ground) = 2.0. Wait, our chart doesn't have water/ground so it's 1x.
        # Active risk: max(2.0, 1.0) = 2.0
        # Candidate (electric): max(1.0 to electric, 0.0 to ground) = 1.0
        # Risk reduction = 1.0
        self.assertEqual(result["active_risk"], 2.0)
        self.assertEqual(result["candidate_risk"], 1.0)


class TestSacrifice(unittest.TestCase):
    def test_sacrifice_preserve_bench(self):
        from doubles_engine.voluntary_switch import (
            evaluate_voluntary_switch_quality,
        )
        active = _FakePokemon(type_1=_Type("water"),
                              current_hp_fraction=0.1)
        candidate = _FakePokemon(type_1=_Type("water"),
                                 current_hp_fraction=1.0)
        result = evaluate_voluntary_switch_quality(
            active, candidate, 0, _FakeBattle(), 0.0, _FakeConfig()
        )
        self.assertEqual(
            result["sacrifice_preserve_bench_value"],
            70.0,
        )
        self.assertIn("sacrifice_preserve_bench", result["reason_codes"])


class TestShim(unittest.TestCase):
    def test_bot_reexports(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.voluntary_switch import (
            evaluate_voluntary_switch_quality as eng,
        )
        self.assertIs(b.evaluate_voluntary_switch_quality, eng)


if __name__ == "__main__":
    unittest.main()
