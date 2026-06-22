#!/usr/bin/env python3
"""Tests for doubles_engine.forced_switch
extracted module.

ponytail: focused unit tests for
``evaluate_forced_switch_replacement_safety``.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _Type:
    def __init__(self, name):
        self.name = name

    def title(self):
        return self.name.title()


class _FakePokemon:
    def __init__(self, type_1=None, type_2=None, fainted=False,
                 current_hp_fraction=1.0):
        self.type_1 = type_1
        self.type_2 = type_2
        self.fainted = fainted
        self.current_hp_fraction = current_hp_fraction

    def damage_multiplier(self, opp_type):
        # Simple chart: ground vs electric=0, water=2x; etc.
        opp_name = getattr(opp_type, "name", str(opp_type)).lower()
        if self.type_1 is None:
            return 1.0
        my_name = self.type_1.name.lower()
        chart = {
            ("electric", "ground"): 0.0,
            ("fire", "water"): 0.5,
            ("water", "electric"): 2.0,
            ("grass", "fire"): 0.5,
        }
        if (my_name, opp_name) in chart:
            return chart[(my_name, opp_name)]
        return 1.0


# ---------------------------------------------------------------------------
# Basic return shape
# ---------------------------------------------------------------------------


class TestReturnShape(unittest.TestCase):
    def test_no_candidate(self):
        from doubles_engine.forced_switch import (
            evaluate_forced_switch_replacement_safety,
        )
        result = evaluate_forced_switch_replacement_safety(None, [])
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["max_threat_multiplier"], 1.0)
        self.assertEqual(result["opponent_threat_count"], 0)

    def test_no_opponents(self):
        from doubles_engine.forced_switch import (
            evaluate_forced_switch_replacement_safety,
        )
        cand = _FakePokemon(type_1=_Type("electric"))
        result = evaluate_forced_switch_replacement_safety(cand, [])
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["opponent_threat_count"], 0)


# ---------------------------------------------------------------------------
# Fainted candidate
# ---------------------------------------------------------------------------


class TestFaintedCandidate(unittest.TestCase):
    def test_fainted_penalty(self):
        from doubles_engine.forced_switch import (
            evaluate_forced_switch_replacement_safety,
        )
        cand = _FakePokemon(fainted=True)
        result = evaluate_forced_switch_replacement_safety(cand, [])
        self.assertLess(result["score"], 0)
        self.assertIn("fainted", result["reasons"])


# ---------------------------------------------------------------------------
# Type effectiveness
# ---------------------------------------------------------------------------


class TestTypeEffectiveness(unittest.TestCase):
    def test_immunity(self):
        from doubles_engine.forced_switch import (
            evaluate_forced_switch_replacement_safety,
        )
        cand = _FakePokemon(type_1=_Type("electric"))
        opp = _FakePokemon(type_1=_Type("ground"))
        result = evaluate_forced_switch_replacement_safety(cand, [opp])
        self.assertEqual(result["immunity_count"], 1)

    def test_super_effective(self):
        from doubles_engine.forced_switch import (
            evaluate_forced_switch_replacement_safety,
        )
        cand = _FakePokemon(type_1=_Type("water"))
        opp = _FakePokemon(type_1=_Type("electric"))
        result = evaluate_forced_switch_replacement_safety(cand, [opp])
        self.assertEqual(result["opponent_threat_count"], 1)
        self.assertEqual(result["max_threat_multiplier"], 2.0)

    def test_resistance(self):
        from doubles_engine.forced_switch import (
            evaluate_forced_switch_replacement_safety,
        )
        cand = _FakePokemon(type_1=_Type("fire"))
        opp = _FakePokemon(type_1=_Type("water"))
        result = evaluate_forced_switch_replacement_safety(cand, [opp])
        self.assertEqual(result["resistance_count"], 1)


# ---------------------------------------------------------------------------
# Low HP penalty
# ---------------------------------------------------------------------------


class TestLowHpPenalty(unittest.TestCase):
    def test_low_hp(self):
        from doubles_engine.forced_switch import (
            evaluate_forced_switch_replacement_safety,
        )
        cand = _FakePokemon(type_1=_Type("normal"),
                            current_hp_fraction=0.2)
        # Need at least one opponent for low_hp to apply
        # (function returns early if no opponents).
        opp = _FakePokemon(type_1=_Type("water"))
        result = evaluate_forced_switch_replacement_safety(cand, [opp])
        self.assertTrue(result["low_hp_penalty_applied"])
        self.assertIn("low_hp", result["reasons"])


# ---------------------------------------------------------------------------
# Fainted opponent
# ---------------------------------------------------------------------------


class TestFaintedOpponent(unittest.TestCase):
    def test_fainted_opp_skipped(self):
        from doubles_engine.forced_switch import (
            evaluate_forced_switch_replacement_safety,
        )
        cand = _FakePokemon(type_1=_Type("water"))
        opp1 = _FakePokemon(type_1=_Type("electric"), fainted=True)
        opp2 = _FakePokemon(type_1=_Type("grass"))
        result = evaluate_forced_switch_replacement_safety(cand, [opp1, opp2])
        # Only opp2 should be evaluated.
        self.assertEqual(result["opponent_threat_count"], 0)


# ---------------------------------------------------------------------------
# Shim
# ---------------------------------------------------------------------------


class TestShim(unittest.TestCase):
    def test_bot_reexports(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.forced_switch import (
            evaluate_forced_switch_replacement_safety as eng,
        )
        self.assertIs(b.evaluate_forced_switch_replacement_safety, eng)


if __name__ == "__main__":
    unittest.main()
