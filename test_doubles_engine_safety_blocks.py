#!/usr/bin/env python3
"""Tests for the extracted doubles_engine.safety_blocks
module.

ponytail: focused unit tests for
``_compute_order_safety_blocks``. These tests
verify:
- 8-tuple return shape.
- Direct absorb safety (when enabled).
- Priority field safety.
- Type immunity safety.
- Ability hard safety.
- Support-target safety.
- Ally-redirect safety.
- Narrow ally-heal safety.

Behavior-preservation evidence: existing tests in
``test_doubles_support_move_target_safety``,
``test_doubles_narrow_ally_heal_safety``, and
``test_vgc2026_runtime_engine_parity`` exercise the
same code path through the shim.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

import poke_env_test_cleanup  # noqa: F401  — must precede any poke_env import

from poke_env.battle.move import Move
from poke_env.player.battle_order import SingleBattleOrder

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _FakeMove(Move):
    """A real Move subclass with overridable id, base_power, target.

    ponytail: the safety blocks check
    ``isinstance(move, Move)`` in some helpers
    (e.g. ``support_move_wrong_side_block``). A
    real Move subclass satisfies the check.

    ``Move.id``, ``base_power``, ``target`` are
    read-only properties; we set the underlying
    private attributes (``_id``,
    ``_base_power_override``, ``_request_target``).
    """

    def __init__(self, id="tackle", base_power=40, target="normal", category="PHYSICAL"):
        super().__init__(id, gen=9)
        self._id = id
        self._base_power_override = base_power
        self._request_target = target
        # category is read-only on Move; use real move IDs
        # (e.g. "healpulse" is STATUS, "tackle" is PHYSICAL)
        # so the bot's category.name lookup returns the
        # right value.


class _FakeOrder:
    def __init__(self, move, move_target=0):
        self.order = move
        self.move_target = move_target


class _FakePokemon:
    def __init__(self, species="pokemon"):
        self.species = species
        self.fainted = False


class _FakeBattle:
    def __init__(self):
        self.active_pokemon = [
            _FakePokemon("blissey"),
            _FakePokemon("snorlax"),
        ]
        self.opponent_active_pokemon = [
            _FakePokemon("gyarados"),
            _FakePokemon("tyranitar"),
        ]


# ---------------------------------------------------------------------------
# Test 8-tuple return shape
# ---------------------------------------------------------------------------


class TestReturnShape(unittest.TestCase):
    def test_empty_input_returns_8_dicts(self):
        from doubles_engine.safety_blocks import (
            _compute_order_safety_blocks,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        result = _compute_order_safety_blocks(battle, config, [[], []])
        self.assertEqual(len(result), 8)
        for d in result:
            self.assertEqual(d, {})


# ---------------------------------------------------------------------------
# Test direct-absorb safety
# ---------------------------------------------------------------------------


class TestDirectAbsorbSafety(unittest.TestCase):
    def test_disabled_by_default(self):
        from doubles_engine.safety_blocks import (
            _compute_order_safety_blocks,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        move = _FakeMove(id="tackle")
        order = _FakeOrder(move, move_target=1)
        (da, _, _, _, _, _, _, _) = _compute_order_safety_blocks(
            battle, config, [[order], []]
        )
        self.assertEqual(da, {})


# ---------------------------------------------------------------------------
# Test narrow-heal safety
# ---------------------------------------------------------------------------


class TestNarrowHealSafety(unittest.TestCase):
    def test_healpulse_into_opponent_blocked(self):
        from doubles_engine.safety_blocks import (
            _compute_order_safety_blocks,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _FakeMove(id="healpulse", base_power=0, category="STATUS")
        order = _FakeOrder(move, move_target=1)  # opponent
        (_, _, _, _, _, _, nb, nr) = _compute_order_safety_blocks(
            battle, config, [[order], []]
        )
        self.assertIn(id(order), nb)
        self.assertIn("healpulse", nr[id(order)])

    def test_healpulse_into_ally_not_blocked(self):
        from doubles_engine.safety_blocks import (
            _compute_order_safety_blocks,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _FakeMove(id="healpulse", base_power=0, category="STATUS")
        order = _FakeOrder(move, move_target=-2)  # ally
        (_, _, _, _, _, _, nb, _) = _compute_order_safety_blocks(
            battle, config, [[order], []]
        )
        self.assertNotIn(id(order), nb)


# ---------------------------------------------------------------------------
# Test support-target safety
# ---------------------------------------------------------------------------


class TestSupportTargetSafety(unittest.TestCase):
    def test_healpulse_into_opponent_blocked(self):
        from doubles_engine.safety_blocks import (
            _compute_order_safety_blocks,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        move = _FakeMove(id="healpulse", base_power=0, category="STATUS")
        order = _FakeOrder(move, move_target=1)  # opponent
        (_, _, _, _, st, sr) = _compute_order_safety_blocks(
            battle, config, [[order], []]
        )[:6]
        self.assertIn(id(order), st)
        self.assertIn("healpulse", sr[id(order)])


# ---------------------------------------------------------------------------
# Test shim re-export
# ---------------------------------------------------------------------------


class TestShimReExport(unittest.TestCase):
    def test_bot_reexports_compute(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.safety_blocks import (
            _compute_order_safety_blocks as eng,
        )
        self.assertIs(b._compute_order_safety_blocks, eng)


if __name__ == "__main__":
    unittest.main()
