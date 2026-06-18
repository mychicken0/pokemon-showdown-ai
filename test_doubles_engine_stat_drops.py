#!/usr/bin/env python3
"""Tests for doubles_engine.stat_drops
extracted module.

ponytail: focused unit tests for the stat-drop
helpers.
"""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _FakeConfig:
    stat_drop_mild_threshold = 1
    stat_drop_moderate_threshold = 2
    stat_drop_severe_threshold = 3


class TestSummarizeNegativeBoosts(unittest.TestCase):
    def test_no_pokemon(self):
        from doubles_engine.stat_drops import summarize_negative_boosts
        result = summarize_negative_boosts(None)
        self.assertEqual(result["total_severity"], 0)
        self.assertFalse(result["is_severely_dropped"])

    def test_no_boosts(self):
        from doubles_engine.stat_drops import summarize_negative_boosts
        p = SimpleNamespace(boosts=None)
        result = summarize_negative_boosts(p)
        self.assertEqual(result["total_severity"], 0)

    def test_some_drops(self):
        from doubles_engine.stat_drops import summarize_negative_boosts
        p = SimpleNamespace(boosts={"atk": -2, "spe": -1})
        result = summarize_negative_boosts(p)
        self.assertEqual(result["attack_minus"], 2)
        self.assertEqual(result["speed_minus"], 1)
        self.assertEqual(result["total_severity"], 3)
        self.assertEqual(result["worst_stage"], 2)
        self.assertEqual(result["worst_stat"], "atk")
        self.assertTrue(result["is_severely_dropped"])

    def test_no_drops(self):
        from doubles_engine.stat_drops import summarize_negative_boosts
        p = SimpleNamespace(boosts={"atk": 1, "spe": 2})
        result = summarize_negative_boosts(p)
        self.assertEqual(result["total_severity"], 0)
        self.assertEqual(result["worst_stage"], 0)


class TestClassifyStatDropSeverity(unittest.TestCase):
    def test_none(self):
        from doubles_engine.stat_drops import classify_stat_drop_severity
        result = classify_stat_drop_severity({}, _FakeConfig(), [])
        self.assertFalse(result["recommend_switch"])

    def test_mild(self):
        from doubles_engine.stat_drops import classify_stat_drop_severity
        boosts = {"worst_stage": 1, "total_severity": 1}
        result = classify_stat_drop_severity(boosts, _FakeConfig(), [])
        self.assertFalse(result["recommend_switch"])
        self.assertGreater(result["score_penalty"], 0)

    def test_severe(self):
        from doubles_engine.stat_drops import classify_stat_drop_severity
        boosts = {"worst_stage": 3, "total_severity": 5}
        result = classify_stat_drop_severity(boosts, _FakeConfig(), [])
        self.assertTrue(result["recommend_switch"])
        self.assertTrue(result["recommend_switch"])

    def test_moderate(self):
        from doubles_engine.stat_drops import classify_stat_drop_severity
        boosts = {"worst_stage": 2, "total_severity": 2}
        result = classify_stat_drop_severity(boosts, _FakeConfig(), [])
        self.assertTrue(result["recommend_switch"])
        self.assertTrue(result["recommend_switch"])
        self.assertTrue(result["recommend_switch"])


class TestEvaluateStatDropSwitchPressure(unittest.TestCase):
    def test_no_pokemon(self):
        from doubles_engine.stat_drops import (
            evaluate_stat_drop_switch_pressure,
        )
        result = evaluate_stat_drop_switch_pressure(
            _FakeConfig(), None, None, None, None, None
        )
        self.assertEqual(result["pressure_score"], 0.0)
        self.assertFalse(result["recommend_switch"])

    def test_no_drops(self):
        from doubles_engine.stat_drops import (
            evaluate_stat_drop_switch_pressure,
        )
        p = SimpleNamespace(boosts={"atk": 1})
        result = evaluate_stat_drop_switch_pressure(
            _FakeConfig(), p, None, None, None, None
        )
        self.assertEqual(result["pressure_score"], 0.0)

    def test_severe_drops(self):
        from doubles_engine.stat_drops import (
            evaluate_stat_drop_switch_pressure,
        )
        p = SimpleNamespace(boosts={"atk": -3, "spe": -2})
        result = evaluate_stat_drop_switch_pressure(
            _FakeConfig(), p, None, None, None, None
        )
        self.assertTrue(result["recommend_switch"])
        self.assertTrue(result["recommend_switch"])
        self.assertGreater(result["pressure_score"], 0.0)


class TestShim(unittest.TestCase):
    def test_bot_reexports(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.stat_drops import (
            summarize_negative_boosts as eng_a,
            classify_stat_drop_severity as eng_b,
            evaluate_stat_drop_switch_pressure as eng_c,
        )
        self.assertIs(b.summarize_negative_boosts, eng_a)
        self.assertIs(b.classify_stat_drop_severity, eng_b)
        self.assertIs(b.evaluate_stat_drop_switch_pressure, eng_c)


if __name__ == "__main__":
    unittest.main()
