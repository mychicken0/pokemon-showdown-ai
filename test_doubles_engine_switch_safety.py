#!/usr/bin/env python3
"""Tests for doubles_engine.switch_safety
extracted module.

ponytail: focused unit tests for
``evaluate_switch_candidate_type_safety``.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _Type:
    def __init__(self, name):
        self.name = name

    def title(self):
        return self.name.title()


class _FakePokemon:
    def __init__(self, type_1=None, type_2=None, current_hp_fraction=1.0):
        self.type_1 = type_1
        self.type_2 = type_2
        self.current_hp_fraction = current_hp_fraction

    def damage_multiplier(self, opp_type):
        opp_name = getattr(opp_type, "name", str(opp_type)).lower()
        if self.type_1 is None:
            return 1.0
        my_name = self.type_1.name.lower()
        chart = {
            ("electric", "ground"): 0.0,
            ("water", "electric"): 2.0,
            ("fire", "water"): 0.5,
        }
        if (my_name, opp_name) in chart:
            return chart[(my_name, opp_name)]
        return 1.0


class TestReturnShape(unittest.TestCase):
    def test_no_candidate(self):
        from doubles_engine.switch_safety import (
            evaluate_switch_candidate_type_safety,
        )
        result = evaluate_switch_candidate_type_safety(None, [])
        self.assertEqual(result["raw_safety_score"], 0.0)
        self.assertEqual(result["worst_multiplier"], 1.0)
        self.assertEqual(result["double_threat"], False)

    def test_no_opponents(self):
        from doubles_engine.switch_safety import (
            evaluate_switch_candidate_type_safety,
        )
        cand = _FakePokemon(type_1=_Type("electric"))
        result = evaluate_switch_candidate_type_safety(cand, [])
        self.assertEqual(result["raw_safety_score"], 0.0)
        self.assertEqual(result["super_effective_threat_count"], 0)


class TestTypeEffectiveness(unittest.TestCase):
    def test_super_effective(self):
        from doubles_engine.switch_safety import (
            evaluate_switch_candidate_type_safety,
        )
        cand = _FakePokemon(type_1=_Type("water"))
        opp = _FakePokemon(type_1=_Type("electric"))
        result = evaluate_switch_candidate_type_safety(cand, [opp])
        self.assertEqual(result["super_effective_threat_count"], 1)
        self.assertEqual(result["worst_multiplier"], 2.0)

    def test_resistance(self):
        from doubles_engine.switch_safety import (
            evaluate_switch_candidate_type_safety,
        )
        cand = _FakePokemon(type_1=_Type("fire"))
        opp = _FakePokemon(type_1=_Type("water"))
        result = evaluate_switch_candidate_type_safety(cand, [opp])
        self.assertEqual(result["resistant_threat_count"], 1)

    def test_immunity(self):
        from doubles_engine.switch_safety import (
            evaluate_switch_candidate_type_safety,
        )
        cand = _FakePokemon(type_1=_Type("electric"))
        opp = _FakePokemon(type_1=_Type("ground"))
        result = evaluate_switch_candidate_type_safety(cand, [opp])
        self.assertEqual(result["immune_threat_count"], 1)

    def test_double_threat(self):
        from doubles_engine.switch_safety import (
            evaluate_switch_candidate_type_safety,
        )
        cand = _FakePokemon(type_1=_Type("water"))
        opp1 = _FakePokemon(type_1=_Type("electric"))
        opp2 = _FakePokemon(type_1=_Type("electric"))
        result = evaluate_switch_candidate_type_safety(cand, [opp1, opp2])
        self.assertTrue(result["double_threat"])
        self.assertEqual(result["super_effective_threat_count"], 2)


class TestShim(unittest.TestCase):
    def test_bot_reexports(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.switch_safety import (
            evaluate_switch_candidate_type_safety as eng,
        )
        self.assertIs(b.evaluate_switch_candidate_type_safety, eng)


if __name__ == "__main__":
    unittest.main()
