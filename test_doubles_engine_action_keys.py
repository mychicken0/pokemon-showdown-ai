#!/usr/bin/env python3
"""Tests for the extracted doubles_engine.action_keys
module.

ponytail: focused unit tests for the action-keys
helpers. These helpers must preserve the V2l.1
3-tuple key semantics and the V4a 4-tuple
mechanic-aware key semantics.

Behavior-preservation evidence: the V2l.1 tests
in test_doubles_ability_hard_safety and related
test files exercise the same code path through
the shim in bot_doubles_damage_aware, so the
extraction is verified to be bit-for-bit
equivalent.
"""
import os
import sys
import unittest
from typing import List

import poke_env_test_cleanup  # noqa: F401  — must precede any poke_env import

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from poke_env.battle.double_battle import SingleBattleOrder  # noqa: E402

from doubles_engine.action_keys import (  # noqa: E402
    V2L1_KEY_LEN,
    V4A_KEY_LEN,
    _final_action_keys_from_joint,
    _final_action_keys_with_mechanic_from_joint,
    _legal_action_keys_for_slot,
    _legal_action_keys_with_mechanic_for_slot,
    _order_action_key,
    _order_action_key_with_mechanic,
    _order_mechanic_label,
    _raw_score_map_for_slot,
    _raw_score_map_with_mechanic_for_slot,
    _safety_block_map_for_slot,
    _selected_joint_key,
    _selected_joint_key_with_mechanic,
    classify_only_legal,
)


class _FakeMove:
    """Mimics poke_env's Move order inner (has .id)."""

    def __init__(self, id: str):
        self.id = id


class _FakePokemon:
    """Mimics poke_env's Pokemon order inner (has .species)."""

    def __init__(self, species: str):
        self.species = species


def _make_order(
    id: str = None,
    species: str = None,
    move_target: int = 0,
    mega: bool = False,
    z_move: bool = False,
    dynamax: bool = False,
    terastallize: bool = False,
):
    """Build a real poke_env SingleBattleOrder with
    test-friendly fields. ponytail: __new__ to
    bypass real battle state. Mirrors the way
    poke_env_test_cleanup-style test fixtures
    avoid real battle contexts.
    """
    order = SingleBattleOrder.__new__(SingleBattleOrder)
    if id is not None:
        order.order = _FakeMove(id)
    elif species is not None:
        order.order = _FakePokemon(species)
    else:
        order.order = None
    order.move_target = move_target
    order.mega = mega
    order.z_move = z_move
    order.dynamax = dynamax
    order.terastallize = terastallize
    return order


class _FakeJointOrder:
    def __init__(self, first, second):
        self.first_order = first
        self.second_order = second


class TestV2L1KeyShape(unittest.TestCase):
    """V2l.1 keys are 3-tuples (action_type, action_id, target)."""

    def test_none_order(self):
        self.assertEqual(_order_action_key(None), ("none", "", 0))

    def test_move_key_shape(self):
        order = _make_order(id="tackle", move_target=1)
        key = _order_action_key(order)
        self.assertEqual(len(key), V2L1_KEY_LEN)
        self.assertEqual(key, ("move", "tackle", 1))

    def test_switch_key_shape(self):
        order = _make_order(species="pikachu", move_target=0)
        key = _order_action_key(order)
        self.assertEqual(len(key), V2L1_KEY_LEN)
        self.assertEqual(key, ("switch", "pikachu", 0))

    def test_unknown_type_uses_fallback(self):
        # Non-SingleBattleOrder, non-None -> "unknown" branch.
        key = _order_action_key("not an order")
        self.assertEqual(len(key), V2L1_KEY_LEN)
        self.assertEqual(key[0], "unknown")


class TestV4AKeyShape(unittest.TestCase):
    """V4a keys are 4-tuples with mechanic label."""

    def test_none_order(self):
        self.assertEqual(
            _order_action_key_with_mechanic(None),
            ("none", "", 0, ""),
        )

    def test_move_key_shape(self):
        order = _make_order(id="tackle", move_target=2)
        key = _order_action_key_with_mechanic(order)
        self.assertEqual(len(key), V4A_KEY_LEN)
        self.assertEqual(key, ("move", "tackle", 2, ""))

    def test_mega_mechanic(self):
        order = _make_order(id="tackle", move_target=0, mega=True)
        key = _order_action_key_with_mechanic(order)
        self.assertEqual(key, ("move", "tackle", 0, "mega"))

    def test_zmove_mechanic(self):
        order = _make_order(
            id="tackle", move_target=0, z_move=True
        )
        self.assertEqual(
            _order_action_key_with_mechanic(order),
            ("move", "tackle", 0, "zmove"),
        )

    def test_dynamax_mechanic(self):
        order = _make_order(
            id="tackle", move_target=0, dynamax=True
        )
        self.assertEqual(
            _order_action_key_with_mechanic(order),
            ("move", "tackle", 0, "dynamax"),
        )

    def test_tera_mechanic(self):
        order = _make_order(
            id="tackle", move_target=0, terastallize=True
        )
        self.assertEqual(
            _order_action_key_with_mechanic(order),
            ("move", "tackle", 0, "terastallize"),
        )

    def test_switch_key_shape(self):
        order = _make_order(species="pikachu", move_target=0)
        key = _order_action_key_with_mechanic(order)
        self.assertEqual(len(key), V4A_KEY_LEN)
        self.assertEqual(key, ("switch", "pikachu", 0, ""))


class TestMechanicLabel(unittest.TestCase):
    def test_none(self):
        self.assertEqual(_order_mechanic_label(None), "")

    def test_priority(self):
        # Priority order: mega > z_move > dynamax > tera
        self.assertEqual(
            _order_mechanic_label(_make_order(mega=True)),
            "mega",
        )
        self.assertEqual(
            _order_mechanic_label(_make_order(z_move=True)),
            "zmove",
        )
        self.assertEqual(
            _order_mechanic_label(_make_order(dynamax=True)),
            "dynamax",
        )
        self.assertEqual(
            _order_mechanic_label(_make_order(terastallize=True)),
            "terastallize",
        )
        self.assertEqual(_order_mechanic_label(_make_order()), "")


class TestLegalActionKeysForSlot(unittest.TestCase):
    """The valid_orders is a list-of-lists indexed by slot_idx."""

    def test_empty_valid_orders(self):
        self.assertEqual(_legal_action_keys_for_slot([], 0), [])
        self.assertEqual(_legal_action_keys_for_slot(None, 0), [])

    def test_slot_idx_out_of_range(self):
        orders = [[_make_order(id="tackle")]]
        self.assertEqual(_legal_action_keys_for_slot(orders, 1), [])

    def test_basic_iteration(self):
        orders = [
            [_make_order(id="tackle", move_target=1)],
            [_make_order(id="sludgebomb", move_target=0)],
        ]
        keys_0 = _legal_action_keys_for_slot(orders, 0)
        keys_1 = _legal_action_keys_for_slot(orders, 1)
        self.assertEqual(keys_0, [("move", "tackle", 1)])
        self.assertEqual(keys_1, [("move", "sludgebomb", 0)])

    def test_with_none_order_uses_none_key(self):
        # None orders: _order_action_key(None) returns
        # ("none", "", 0), so the entry is appended.
        # ponytail: matches the original code's
        # try/except behavior.
        orders = [
            [None, _make_order(id="tackle", move_target=1)],
        ]
        keys = _legal_action_keys_for_slot(orders, 0)
        self.assertEqual(
            keys, [("none", "", 0), ("move", "tackle", 1)]
        )

    def test_v4a_mechanic_keys(self):
        orders = [
            [_make_order(id="tackle", move_target=0, mega=True)],
        ]
        keys = _legal_action_keys_with_mechanic_for_slot(
            orders, 0
        )
        self.assertEqual(keys, [("move", "tackle", 0, "mega")])


class TestRawScoreMapForSlot(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_raw_score_map_for_slot({}, [], 0), {})

    def test_basic(self):
        o1 = _make_order(id="tackle", move_target=0)
        o2 = _make_order(id="sludge", move_target=0)
        slot_scores = {id(o1): 100.5, id(o2): 50.0}
        orders = [[o1, o2]]
        result = _raw_score_map_for_slot(
            slot_scores, orders, 0
        )
        self.assertEqual(
            result,
            {
                ("move", "tackle", 0): 100.5,
                ("move", "sludge", 0): 50.0,
            },
        )

    def test_missing_score_defaults_to_zero(self):
        o1 = _make_order(id="tackle", move_target=0)
        slot_scores = {}  # o1 not in map
        orders = [[o1]]
        result = _raw_score_map_for_slot(
            slot_scores, orders, 0
        )
        self.assertEqual(result, {("move", "tackle", 0): 0.0})

    def test_v4a_mechanic_version(self):
        o1 = _make_order(id="tackle", move_target=0, mega=True)
        slot_scores = {id(o1): 42.0}
        orders = [[o1]]
        result = _raw_score_map_with_mechanic_for_slot(
            slot_scores, orders, 0
        )
        self.assertEqual(
            result, {("move", "tackle", 0, "mega"): 42.0}
        )


class TestSafetyBlockMapForSlot(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(
            _safety_block_map_for_slot({}, [], 0), {}
        )

    def test_basic(self):
        o1 = _make_order(id="tackle", move_target=0)
        safety_blocked = {id(o1): True}
        orders = [[o1]]
        result = _safety_block_map_for_slot(
            safety_blocked, orders, 0
        )
        self.assertEqual(
            result, {("move", "tackle", 0): True}
        )

    def test_default_false(self):
        o1 = _make_order(id="tackle", move_target=0)
        safety_blocked = {}  # o1 not blocked
        orders = [[o1]]
        result = _safety_block_map_for_slot(
            safety_blocked, orders, 0
        )
        self.assertEqual(
            result, {("move", "tackle", 0): False}
        )


class TestFinalAndSelectedJointKeys(unittest.TestCase):
    def test_none_joint(self):
        # ponytail: Step 2b fix. Original returns
        # [("none", "", 0), ("none", "", 0)] for None
        # joint, not (None, None). Step 1 changed this
        # to a tuple of Nones; Step 2b restored the
        # original list with "none" keys.
        self.assertEqual(
            _final_action_keys_from_joint(None),
            [("none", "", 0), ("none", "", 0)],
        )
        self.assertEqual(
            _final_action_keys_with_mechanic_from_joint(None),
            [("none", "", 0, ""), ("none", "", 0, "")],
        )

    def test_basic(self):
        o1 = _make_order(id="tackle", move_target=0)
        o2 = _make_order(id="sludge", move_target=1)
        jo = _FakeJointOrder(o1, o2)
        # Original returns a LIST (not a tuple).
        self.assertEqual(
            _final_action_keys_from_joint(jo),
            [("move", "tackle", 0), ("move", "sludge", 1)],
        )
        # V4a version: 4-tuple keys, list.
        self.assertEqual(
            _final_action_keys_with_mechanic_from_joint(jo),
            [
                ("move", "tackle", 0, ""),
                ("move", "sludge", 1, ""),
            ],
        )

    def test_selected_joint_key(self):
        o1 = _make_order(id="tackle", move_target=0)
        o2 = _make_order(id="sludge", move_target=1)
        jo = _FakeJointOrder(o1, o2)
        # _selected_joint_key returns a TUPLE.
        self.assertEqual(
            _selected_joint_key(jo),
            (("move", "tackle", 0), ("move", "sludge", 1)),
        )
        # _selected_joint_key_with_mechanic returns a TUPLE too.
        self.assertEqual(
            _selected_joint_key_with_mechanic(jo),
            (
                ("move", "tackle", 0, ""),
                ("move", "sludge", 1, ""),
            ),
        )


class TestClassifyOnlyLegal(unittest.TestCase):
    """classify_only_legal: True when the selected blocked
    action has no non-safety-blocked alternative."""

    def test_not_blocked_returns_false(self):
        sel = _make_order(id="tackle", move_target=0)
        alt = _make_order(id="sludge", move_target=1)
        jo = _FakeJointOrder(sel, alt)
        safety_blocked = {id(alt): True}
        # sel is not in safety_blocked -> only_legal=False
        self.assertFalse(
            classify_only_legal([jo], 0, sel, safety_blocked)
        )

    def test_blocked_with_all_alts_blocked_returns_true(self):
        sel = _make_order(id="tackle", move_target=0)
        alt = _make_order(id="sludge", move_target=1)
        jo = _FakeJointOrder(sel, alt)
        safety_blocked = {id(sel): True, id(alt): True}
        # alt is blocked too -> only_legal=True
        self.assertTrue(
            classify_only_legal([jo], 0, sel, safety_blocked)
        )

    def test_blocked_with_safe_alt_in_other_joint_returns_false(self):
        # The function checks ALL joint_orders for safe
        # alts. To trigger the "has safe alt" path, we
        # need a second joint_order whose same-slot
        # order is a different (and unblocked) action.
        sel = _make_order(id="tackle", move_target=0)
        sel_joint = _FakeJointOrder(sel, None)
        alt = _make_order(id="sludge", move_target=0)
        alt_joint = _FakeJointOrder(alt, None)
        safety_blocked = {id(sel): True}  # alt NOT blocked
        # alt is a safe alternative in alt_joint -> only_legal=False
        self.assertFalse(
            classify_only_legal(
                [sel_joint, alt_joint], 0, sel, safety_blocked
            )
        )

    def test_no_alternatives(self):
        sel = _make_order(id="tackle", move_target=0)
        jo = _FakeJointOrder(sel, None)
        safety_blocked = {id(sel): True}
        # No alternative -> only_legal=True
        self.assertTrue(
            classify_only_legal([jo], 0, sel, safety_blocked)
        )

    def test_no_safety_blocked_arg(self):
        sel = _make_order(id="tackle", move_target=0)
        jo = _FakeJointOrder(sel, _make_order(id="x"))
        # safety_blocked=None -> no orders blocked
        self.assertFalse(
            classify_only_legal([jo], 0, sel, None)
        )


if __name__ == "__main__":
    unittest.main()
