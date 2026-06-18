#!/usr/bin/env python3
"""Tests for doubles_engine.revealed_switch
extracted module.

ponytail: focused unit tests for the
revealed-move switch interception helpers.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _Type:
    def __init__(self, name):
        self.name = name


class _FakeMove:
    def __init__(self, id="tackle", base_power=40, type_name="normal",
                 category="PHYSICAL"):
        self.id = id
        self.base_power = base_power

        class _T:
            def __init__(self, n):
                self.name = n.upper()
        self.type = _T(type_name)
        cat_obj = type("Cat", (), {"name": category})()
        self.category = cat_obj


class _FakePokemon:
    def __init__(self, type_1=None, type_2=None, moves=None):
        self.type_1 = type_1
        self.type_2 = type_2
        if moves is None:
            moves = {}
        self.moves = moves

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
        }
        if (my_name, opp_name) in chart:
            return chart[(my_name, opp_name)]
        return 1.0


class TestGetRevealedDamagingMoves(unittest.TestCase):
    def test_no_opponent(self):
        from doubles_engine.revealed_switch import get_revealed_damaging_moves
        self.assertEqual(get_revealed_damaging_moves(None), [])

    def test_no_moves(self):
        from doubles_engine.revealed_switch import get_revealed_damaging_moves
        opp = _FakePokemon(moves={})
        self.assertEqual(get_revealed_damaging_moves(opp), [])

    def test_filters_status(self):
        from doubles_engine.revealed_switch import get_revealed_damaging_moves
        opp = _FakePokemon(moves={
            "tackle": _FakeMove(base_power=40, category="PHYSICAL"),
            "growl": _FakeMove(base_power=0, category="STATUS"),
        })
        result = get_revealed_damaging_moves(opp)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "tackle")


class TestEvaluateRevealedMoveIncomingRisk(unittest.TestCase):
    def test_no_move(self):
        from doubles_engine.revealed_switch import (
            evaluate_revealed_move_incoming_risk,
        )
        result = evaluate_revealed_move_incoming_risk(
            None, None, _FakePokemon()
        )
        self.assertEqual(result["damage_fraction"], 0.0)

    def test_status_move(self):
        from doubles_engine.revealed_switch import (
            evaluate_revealed_move_incoming_risk,
        )
        move = _FakeMove(base_power=0, category="STATUS")
        result = evaluate_revealed_move_incoming_risk(
            move, None, _FakePokemon(type_1=_Type("electric"))
        )
        self.assertEqual(result["damage_fraction"], 0.0)

    def test_immunity(self):
        from doubles_engine.revealed_switch import (
            evaluate_revealed_move_incoming_risk,
        )
        move = _FakeMove(id="earthquake", base_power=100,
                         type_name="ground", category="PHYSICAL")
        defender = _FakePokemon(type_1=_Type("electric"))
        result = evaluate_revealed_move_incoming_risk(
            move, None, defender
        )
        self.assertEqual(result["damage_fraction"], 0.0)
        self.assertEqual(result["reason"], "type_immunity")

    def test_super_effective(self):
        from doubles_engine.revealed_switch import (
            evaluate_revealed_move_incoming_risk,
        )
        move = _FakeMove(id="thunderbolt", base_power=90,
                         type_name="electric", category="SPECIAL")
        defender = _FakePokemon(type_1=_Type("water"))
        result = evaluate_revealed_move_incoming_risk(
            move, None, defender
        )
        self.assertTrue(result["super_effective"])


class TestSummarizeRevealedMoveThreats(unittest.TestCase):
    def test_no_moves(self):
        from doubles_engine.revealed_switch import (
            summarize_revealed_move_threats,
        )
        result = summarize_revealed_move_threats(None, _FakePokemon())
        self.assertEqual(result["se_count"], 0)
        self.assertEqual(result["threatening_moves"], [])

    def test_with_se_move(self):
        from doubles_engine.revealed_switch import (
            summarize_revealed_move_threats,
        )
        opp = _FakePokemon(moves={
            "thunderbolt": _FakeMove(
                id="thunderbolt", base_power=90,
                type_name="electric", category="SPECIAL"
            )
        })
        defender = _FakePokemon(type_1=_Type("water"))
        result = summarize_revealed_move_threats(opp, defender)
        self.assertGreater(len(result["threatening_moves"]), 0)
        self.assertGreaterEqual(result["se_count"], 1)


class TestEvaluateRevealedMoveSwitchInterception(unittest.TestCase):
    def test_no_threats(self):
        from doubles_engine.revealed_switch import (
            evaluate_revealed_move_switch_interception,
        )
        opp = _FakePokemon(moves={})
        result = evaluate_revealed_move_switch_interception(
            _FakePokemon(), opp
        )
        self.assertFalse(result["should_avoid"])

    def test_with_threat(self):
        from doubles_engine.revealed_switch import (
            evaluate_revealed_move_switch_interception,
        )
        opp = _FakePokemon(moves={
            "thunderbolt": _FakeMove(
                id="thunderbolt", base_power=90,
                type_name="electric", category="SPECIAL"
            )
        })
        candidate = _FakePokemon(type_1=_Type("water"))
        result = evaluate_revealed_move_switch_interception(
            candidate, opp
        )
        # SE threat should be flagged.
        self.assertGreater(result["max_damage_fraction"], 0.0)


class TestShim(unittest.TestCase):
    def test_bot_reexports(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.revealed_switch import (
            get_revealed_damaging_moves as eng_a,
            evaluate_revealed_move_incoming_risk as eng_b,
            evaluate_revealed_move_switch_interception as eng_c,
        )
        self.assertIs(b.get_revealed_damaging_moves, eng_a)
        self.assertIs(b.evaluate_revealed_move_incoming_risk, eng_b)
        self.assertIs(b.evaluate_revealed_move_switch_interception, eng_c)


if __name__ == "__main__":
    unittest.main()
