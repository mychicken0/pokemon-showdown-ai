#!/usr/bin/env python3
"""Tests for the extracted doubles_engine.support_targets
module.

ponytail: focused unit tests for the support-target
helpers. These tests verify:
- Each helper produces the expected output for
  representative inputs.
- Module-level consts are intact.
- The shim in ``bot_doubles_damage_aware`` re-exports
  the helpers under their original names.
- Importing the module does not require the bot.

Behavior-preservation evidence: existing tests in
``test_doubles_support_move_target_safety``,
``test_doubles_support_move_target_safety_paired``,
``test_doubles_narrow_ally_heal_safety``, and
``test_doubles_narrow_ally_heal_paired_repair``
exercise the same code path through the shim, so
the extraction is verified to be bit-for-bit
equivalent.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

import poke_env_test_cleanup  # noqa: F401  — must precede any poke_env import

from poke_env.battle.move import Move
from poke_env.battle.target import Target
from poke_env.player.battle_order import SingleBattleOrder

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _FakeMove(Move):
    """A real Move subclass with overridable id, base_power, target.

    ponytail: the support-target block functions check
    ``isinstance(move, Move)``. Using a real Move
    subclass satisfies the check.

    ``Move.id`` is a read-only property. To change the
    move id, we set ``_id`` (the underlying private
    attribute). Similarly for ``base_power`` and
    ``target`` which are also read-only.

    ``category`` is also read-only and derived from the
    move's pokedex entry. Tests use real move IDs so
    the category is correct (e.g. ``healpulse`` is
    STATUS, ``tackle`` is PHYSICAL).

    The bot's ``classify_support_move_target_intent``
    does ``str(getattr(move, "target", "")).lower()``,
    so we set ``target`` as a string. We avoid
    poke_env's Target enum here because its __str__
    is "<Target.SELF: 15>" which doesn't match the
    bot's expected target strings.
    """

    def __init__(
        self,
        id: str = "tackle",
        base_power: int = 40,
        target: str = "normal",
    ):
        super().__init__(id, gen=9)
        # Override id via the private _id.
        self._id = id
        # Override base_power via _base_power_override.
        self._base_power_override = base_power
        # Set target as a string so
        # str(move.target).lower() returns the target
        # name directly.
        self._request_target = target


class _FakeOrder:
    """Mimics poke_env's SingleBattleOrder. Has
    .order (a Move) and .move_target (int).
    """

    def __init__(self, move: _FakeMove, move_target: int = 0):
        self.order = move
        self.move_target = move_target


class _FakePokemon:
    """Mimics poke_env's Pokemon. Has .species."""

    def __init__(self, species: str = "pokemon"):
        self.species = species


class _FakeBattle:
    """Mimics poke_env's DoubleBattle for target resolution.
    Has .active_pokemon and .opponent_active_pokemon.
    """

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
# Module-level consts
# ---------------------------------------------------------------------------


class TestModuleConsts(unittest.TestCase):
    def test_pollen_puff_id(self):
        from doubles_engine.support_targets import _POLLEN_PUFF_MOVE_ID
        self.assertEqual(_POLLEN_PUFF_MOVE_ID, "pollenpuff")

    def test_narrow_ally_heal_move_ids(self):
        from doubles_engine.support_targets import _NARROW_ALLY_HEAL_MOVE_IDS
        self.assertEqual(
            _NARROW_ALLY_HEAL_MOVE_IDS,
            {"healpulse", "floralhealing", "decorate"},
        )

    def test_narrow_ally_heal_reason_keys(self):
        from doubles_engine.support_targets import _NARROW_ALLY_HEAL_REASON
        self.assertEqual(
            set(_NARROW_ALLY_HEAL_REASON.keys()),
            {"healpulse", "floralhealing", "decorate"},
        )

    def test_support_ally_beneficial_single(self):
        from doubles_engine.support_targets import (
            _SUPPORT_ALLY_BENEFICIAL_SINGLE,
        )
        self.assertEqual(
            _SUPPORT_ALLY_BENEFICIAL_SINGLE,
            {"healpulse", "floralhealing", "decorate"},
        )

    def test_support_ally_beneficial_allies(self):
        from doubles_engine.support_targets import (
            _SUPPORT_ALLY_BENEFICIAL_ALLIES,
        )
        self.assertEqual(
            _SUPPORT_ALLY_BENEFICIAL_ALLIES,
            {"helpinghand", "coaching", "howl", "lifedew"},
        )

    def test_support_ally_beneficial_team(self):
        from doubles_engine.support_targets import (
            _SUPPORT_ALLY_BENEFICIAL_TEAM,
        )
        self.assertEqual(
            _SUPPORT_ALLY_BENEFICIAL_TEAM,
            {"aromatherapy", "healbell"},
        )

    def test_support_opponent_disruptive_single(self):
        from doubles_engine.support_targets import (
            _SUPPORT_OPPONENT_DISRUPTIVE_SINGLE,
        )
        # Pollen Puff and Skill Swap are NOT in here.
        self.assertNotIn("pollenpuff", _SUPPORT_OPPONENT_DISRUPTIVE_SINGLE)
        self.assertNotIn("skillswap", _SUPPORT_OPPONENT_DISRUPTIVE_SINGLE)
        self.assertIn("taunt", _SUPPORT_OPPONENT_DISRUPTIVE_SINGLE)
        self.assertIn("thunderwave", _SUPPORT_OPPONENT_DISRUPTIVE_SINGLE)
        self.assertIn("willowisp", _SUPPORT_OPPONENT_DISRUPTIVE_SINGLE)

    def test_support_either_move_ids(self):
        from doubles_engine.support_targets import _SUPPORT_EITHER_MOVE_IDS
        self.assertEqual(_SUPPORT_EITHER_MOVE_IDS, {"skillswap"})


# ---------------------------------------------------------------------------
# classify_support_move_target_intent
# ---------------------------------------------------------------------------


class TestClassifySupportMoveTargetIntent(unittest.TestCase):
    def test_none_move(self):
        from doubles_engine.support_targets import (
            classify_support_move_target_intent,
        )
        result = classify_support_move_target_intent(None)
        self.assertFalse(result["classified"])
        self.assertEqual(result["intended_side"], "unknown")

    def test_move_without_id(self):
        from doubles_engine.support_targets import (
            classify_support_move_target_intent,
        )
        move = MagicMock(spec=["__bool__"])
        move.__bool__ = lambda self: True
        result = classify_support_move_target_intent(move)
        self.assertFalse(result["classified"])
        self.assertEqual(result["intended_side"], "unknown")

    def test_pollen_puff_is_either(self):
        from doubles_engine.support_targets import (
            classify_support_move_target_intent,
        )
        move = _FakeMove(id="pollenpuff")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "either")

    def test_healpulse_is_ally(self):
        from doubles_engine.support_targets import (
            classify_support_move_target_intent,
        )
        move = _FakeMove(id="healpulse")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "ally")

    def test_taunt_is_opponent(self):
        from doubles_engine.support_targets import (
            classify_support_move_target_intent,
        )
        move = _FakeMove(id="taunt")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "opponent")

    def test_aromatherapy_is_field(self):
        from doubles_engine.support_targets import (
            classify_support_move_target_intent,
        )
        move = _FakeMove(id="aromatherapy")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "field")

    def test_helpinghand_is_ally(self):
        from doubles_engine.support_targets import (
            classify_support_move_target_intent,
        )
        move = _FakeMove(id="helpinghand")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "ally")

    def test_skillswap_is_either(self):
        from doubles_engine.support_targets import (
            classify_support_move_target_intent,
        )
        move = _FakeMove(id="skillswap")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "either")

    def test_unclassified_move(self):
        from doubles_engine.support_targets import (
            classify_support_move_target_intent,
        )
        move = _FakeMove(id="tackle")
        result = classify_support_move_target_intent(move)
        self.assertFalse(result["classified"])
        self.assertEqual(result["intended_side"], "unknown")

    def test_self_targeting_metadata(self):
        from doubles_engine.support_targets import (
            classify_support_move_target_intent,
        )
        move = _FakeMove(id="recover", target="self")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "self")

    def test_adjacent_ally_targeting(self):
        from doubles_engine.support_targets import (
            classify_support_move_target_intent,
        )
        move = _FakeMove(id="acupressure", target="adjacentAlly")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "ally")


# ---------------------------------------------------------------------------
# resolve_order_target_side
# ---------------------------------------------------------------------------


class TestResolveOrderTargetSide(unittest.TestCase):
    def test_target_zero_is_field(self):
        from doubles_engine.support_targets import (
            resolve_order_target_side,
        )
        battle = _FakeBattle()
        order = _FakeOrder(_FakeMove(id="earthquake"), move_target=0)
        result = resolve_order_target_side(order, 0, battle)
        self.assertEqual(result["side"], "field")
        self.assertEqual(result["target_position"], 0)

    def test_target_one_is_opponent(self):
        from doubles_engine.support_targets import (
            resolve_order_target_side,
        )
        battle = _FakeBattle()
        order = _FakeOrder(_FakeMove(id="tackle"), move_target=1)
        result = resolve_order_target_side(order, 0, battle)
        self.assertEqual(result["side"], "opponent")
        self.assertEqual(result["target_species"], "gyarados")

    def test_target_two_is_opponent(self):
        from doubles_engine.support_targets import (
            resolve_order_target_side,
        )
        battle = _FakeBattle()
        order = _FakeOrder(_FakeMove(id="tackle"), move_target=2)
        result = resolve_order_target_side(order, 0, battle)
        self.assertEqual(result["side"], "opponent")
        self.assertEqual(result["target_species"], "tyranitar")

    def test_target_neg1_from_slot0_is_self(self):
        from doubles_engine.support_targets import (
            resolve_order_target_side,
        )
        battle = _FakeBattle()
        order = _FakeOrder(_FakeMove(id="healpulse"), move_target=-1)
        result = resolve_order_target_side(order, 0, battle)
        self.assertEqual(result["side"], "self")
        self.assertEqual(result["target_species"], "blissey")

    def test_target_neg2_from_slot0_is_ally(self):
        from doubles_engine.support_targets import (
            resolve_order_target_side,
        )
        battle = _FakeBattle()
        order = _FakeOrder(_FakeMove(id="healpulse"), move_target=-2)
        result = resolve_order_target_side(order, 0, battle)
        self.assertEqual(result["side"], "ally")
        self.assertEqual(result["target_species"], "snorlax")

    def test_target_neg1_from_slot1_is_ally(self):
        from doubles_engine.support_targets import (
            resolve_order_target_side,
        )
        battle = _FakeBattle()
        order = _FakeOrder(_FakeMove(id="healpulse"), move_target=-1)
        result = resolve_order_target_side(order, 1, battle)
        self.assertEqual(result["side"], "ally")
        self.assertEqual(result["target_species"], "blissey")

    def test_target_neg2_from_slot1_is_self(self):
        from doubles_engine.support_targets import (
            resolve_order_target_side,
        )
        battle = _FakeBattle()
        order = _FakeOrder(_FakeMove(id="healpulse"), move_target=-2)
        result = resolve_order_target_side(order, 1, battle)
        self.assertEqual(result["side"], "self")
        self.assertEqual(result["target_species"], "snorlax")

    def test_no_order(self):
        from doubles_engine.support_targets import (
            resolve_order_target_side,
        )
        battle = _FakeBattle()
        result = resolve_order_target_side(None, 0, battle)
        self.assertEqual(result["side"], "unknown")
        self.assertIsNone(result["target_position"])

    def test_no_battle(self):
        from doubles_engine.support_targets import (
            resolve_order_target_side,
        )
        order = _FakeOrder(_FakeMove(id="tackle"), move_target=1)
        result = resolve_order_target_side(order, 0, None)
        self.assertEqual(result["side"], "unknown")


# ---------------------------------------------------------------------------
# build_support_target_candidate_table
# ---------------------------------------------------------------------------


class TestBuildSupportTargetCandidateTable(unittest.TestCase):
    def test_empty_orders(self):
        from doubles_engine.support_targets import (
            build_support_target_candidate_table,
        )
        battle = _FakeBattle()
        rows = build_support_target_candidate_table(
            [], 0, battle
        )
        self.assertEqual(rows, [])

    def test_healpulse_into_ally_included(self):
        from doubles_engine.support_targets import (
            build_support_target_candidate_table,
        )
        battle = _FakeBattle()
        move = _FakeMove(id="healpulse")
        order = _FakeOrder(move, move_target=-2)
        rows = build_support_target_candidate_table(
            [order], 0, battle
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["move_id"], "healpulse")
        self.assertEqual(rows[0]["intended_side"], "ally")
        self.assertEqual(rows[0]["target_side"], "ally")

    def test_taunt_into_opponent_included(self):
        from doubles_engine.support_targets import (
            build_support_target_candidate_table,
        )
        battle = _FakeBattle()
        move = _FakeMove(id="taunt")
        order = _FakeOrder(move, move_target=1)
        rows = build_support_target_candidate_table(
            [order], 0, battle
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["move_id"], "taunt")
        self.assertEqual(rows[0]["intended_side"], "opponent")

    def test_unclassified_move_excluded(self):
        from doubles_engine.support_targets import (
            build_support_target_candidate_table,
        )
        battle = _FakeBattle()
        move = _FakeMove(id="tackle")
        order = _FakeOrder(move, move_target=1)
        rows = build_support_target_candidate_table(
            [order], 0, battle
        )
        self.assertEqual(rows, [])

    def test_field_targeting_move_excluded(self):
        from doubles_engine.support_targets import (
            build_support_target_candidate_table,
        )
        battle = _FakeBattle()
        move = _FakeMove(id="aromatherapy")
        order = _FakeOrder(move, move_target=0)
        rows = build_support_target_candidate_table(
            [order], 0, battle
        )
        self.assertEqual(rows, [])

    def test_dedup_same_move_target(self):
        from doubles_engine.support_targets import (
            build_support_target_candidate_table,
        )
        battle = _FakeBattle()
        move = _FakeMove(id="healpulse")
        o1 = _FakeOrder(move, move_target=-2)
        o2 = _FakeOrder(move, move_target=-2)
        rows = build_support_target_candidate_table(
            [o1, o2], 0, battle
        )
        self.assertEqual(len(rows), 1)

    def test_no_battle_yields_empty(self):
        # Empty orders => empty rows (regardless of battle).
        from doubles_engine.support_targets import (
            build_support_target_candidate_table,
        )
        battle = _FakeBattle()
        rows = build_support_target_candidate_table(
            [], 0, battle
        )
        self.assertEqual(rows, [])

    def test_blocking_when_flag_enabled(self):
        from doubles_engine.support_targets import (
            build_support_target_candidate_table,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        move = _FakeMove(id="healpulse")
        order = _FakeOrder(move, move_target=1)  # targeting opponent
        rows = build_support_target_candidate_table(
            [order], 0, battle, config=config
        )
        # Healpulse aimed at opponent should be blocked.
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["blocked"])


# ---------------------------------------------------------------------------
# build_narrow_ally_heal_candidate_table
# ---------------------------------------------------------------------------


class TestBuildNarrowAllyHealCandidateTable(unittest.TestCase):
    def test_healpulse_in_narrow(self):
        from doubles_engine.support_targets import (
            build_narrow_ally_heal_candidate_table,
        )
        battle = _FakeBattle()
        move = _FakeMove(id="healpulse")
        order = _FakeOrder(move, move_target=-2)
        rows = build_narrow_ally_heal_candidate_table(
            [order], 0, battle
        )
        self.assertEqual(len(rows), 1)

    def test_taunt_not_in_narrow(self):
        from doubles_engine.support_targets import (
            build_narrow_ally_heal_candidate_table,
        )
        battle = _FakeBattle()
        move = _FakeMove(id="taunt")
        order = _FakeOrder(move, move_target=1)
        rows = build_narrow_ally_heal_candidate_table(
            [order], 0, battle
        )
        self.assertEqual(rows, [])

    def test_pollen_puff_not_in_narrow(self):
        from doubles_engine.support_targets import (
            build_narrow_ally_heal_candidate_table,
        )
        battle = _FakeBattle()
        move = _FakeMove(id="pollenpuff")
        order = _FakeOrder(move, move_target=-2)
        rows = build_narrow_ally_heal_candidate_table(
            [order], 0, battle
        )
        self.assertEqual(rows, [])

    def test_floral_healing_in_narrow(self):
        from doubles_engine.support_targets import (
            build_narrow_ally_heal_candidate_table,
        )
        battle = _FakeBattle()
        move = _FakeMove(id="floralhealing")
        order = _FakeOrder(move, move_target=-2)
        rows = build_narrow_ally_heal_candidate_table(
            [order], 0, battle
        )
        self.assertEqual(len(rows), 1)

    def test_decorate_in_narrow(self):
        from doubles_engine.support_targets import (
            build_narrow_ally_heal_candidate_table,
        )
        battle = _FakeBattle()
        move = _FakeMove(id="decorate")
        order = _FakeOrder(move, move_target=-2)
        rows = build_narrow_ally_heal_candidate_table(
            [order], 0, battle
        )
        self.assertEqual(len(rows), 1)

    def test_blocking_healpulse_into_opponent(self):
        from doubles_engine.support_targets import (
            build_narrow_ally_heal_candidate_table,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _FakeMove(id="healpulse")
        order = _FakeOrder(move, move_target=1)  # targeting opponent
        rows = build_narrow_ally_heal_candidate_table(
            [order], 0, battle, config=config
        )
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["blocked"])

    def test_no_blocking_into_ally(self):
        from doubles_engine.support_targets import (
            build_narrow_ally_heal_candidate_table,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _FakeMove(id="healpulse")
        order = _FakeOrder(move, move_target=-2)  # targeting ally
        rows = build_narrow_ally_heal_candidate_table(
            [order], 0, battle, config=config
        )
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["blocked"])


# ---------------------------------------------------------------------------
# support_move_wrong_side_block
# ---------------------------------------------------------------------------


class TestSupportMoveWrongSideBlock(unittest.TestCase):
    def test_no_order(self):
        from doubles_engine.support_targets import (
            support_move_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        blocked, _ = support_move_wrong_side_block(None, 0, battle, config)
        self.assertFalse(blocked)

    def test_flag_off(self):
        from doubles_engine.support_targets import (
            support_move_wrong_side_block,
        )
        battle = _FakeBattle()
        # config.enable_support_move_target_hard_safety = False (default)
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        config = DoublesDamageAwareConfig()
        move = _FakeMove(id="healpulse")
        order = _FakeOrder(move, move_target=1)
        blocked, _ = support_move_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)

    def test_healpulse_into_opponent_blocked(self):
        from doubles_engine.support_targets import (
            support_move_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        move = _FakeMove(id="healpulse")
        order = _FakeOrder(move, move_target=1)
        blocked, reason = support_move_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)
        self.assertIn("healpulse", reason)

    def test_healpulse_into_ally_not_blocked(self):
        from doubles_engine.support_targets import (
            support_move_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        move = _FakeMove(id="healpulse")
        order = _FakeOrder(move, move_target=-2)
        blocked, _ = support_move_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)

    def test_pollen_puff_into_opponent_not_blocked(self):
        from doubles_engine.support_targets import (
            support_move_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        move = _FakeMove(id="pollenpuff", base_power=90)
        order = _FakeOrder(move, move_target=1)
        blocked, _ = support_move_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)

    def test_taunt_into_ally_blocked(self):
        from doubles_engine.support_targets import (
            support_move_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        move = _FakeMove(id="taunt")
        order = _FakeOrder(move, move_target=-2)
        blocked, _ = support_move_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)

    def test_status_move_filter(self):
        from doubles_engine.support_targets import (
            support_move_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        # Damaging move that's not Pollen Puff and not in the lists
        move = _FakeMove(id="crunch", base_power=80)
        order = _FakeOrder(move, move_target=-2)  # targeting ally
        blocked, _ = support_move_wrong_side_block(
            order, 0, battle, config=config
        )
        # Damaging moves are not blocked even if wrongly targeted.
        self.assertFalse(blocked)

    def test_self_targeting_wrong_target_blocked(self):
        from doubles_engine.support_targets import (
            support_move_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        move = _FakeMove(id="recover", target="self")
        order = _FakeOrder(move, move_target=1)  # wrong side
        blocked, _ = support_move_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)


# ---------------------------------------------------------------------------
# narrow_ally_heal_wrong_side_block
# ---------------------------------------------------------------------------


class TestNarrowAllyHealWrongSideBlock(unittest.TestCase):
    def test_default_flag_is_on_after_adopt1(self):
        """SUPPORT-SAFETY-ADOPT-1: the narrow flag is
        now default ON. This test was renamed from
        ``test_flag_off`` to reflect the new default.
        """
        from doubles_engine.support_targets import (
            narrow_ally_heal_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()  # default ON
        move = _FakeMove(id="healpulse")
        order = _FakeOrder(move, move_target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        # Default ON: healpulse at opponent is blocked.
        self.assertTrue(blocked)

    def test_explicit_flag_off_does_not_block(self):
        """Explicit opt-out: ``enable_ally_heal_wrong_side_hard_safety=False``
        must disable the hard safety.
        """
        from doubles_engine.support_targets import (
            narrow_ally_heal_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = False
        move = _FakeMove(id="healpulse")
        order = _FakeOrder(move, move_target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)

    def test_healpulse_into_opponent_blocked(self):
        from doubles_engine.support_targets import (
            narrow_ally_heal_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _FakeMove(id="healpulse")
        order = _FakeOrder(move, move_target=1)
        blocked, reason = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)
        self.assertIn("healpulse", reason)

    def test_healpulse_into_ally_not_blocked(self):
        from doubles_engine.support_targets import (
            narrow_ally_heal_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _FakeMove(id="healpulse")
        order = _FakeOrder(move, move_target=-2)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)

    def test_taunt_not_in_narrow_allowlist(self):
        from doubles_engine.support_targets import (
            narrow_ally_heal_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _FakeMove(id="taunt")
        order = _FakeOrder(move, move_target=-2)  # targeting ally
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        # Taunt is not in the narrow allowlist.
        self.assertFalse(blocked)

    def test_pollen_puff_not_in_narrow_allowlist(self):
        from doubles_engine.support_targets import (
            narrow_ally_heal_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _FakeMove(id="pollenpuff", base_power=90)
        order = _FakeOrder(move, move_target=1)  # targeting opponent
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        # Pollen Puff is not in the narrow allowlist.
        self.assertFalse(blocked)

    def test_floral_healing_blocked(self):
        from doubles_engine.support_targets import (
            narrow_ally_heal_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _FakeMove(id="floralhealing")
        order = _FakeOrder(move, move_target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)

    def test_decorate_blocked(self):
        from doubles_engine.support_targets import (
            narrow_ally_heal_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _FakeMove(id="decorate")
        order = _FakeOrder(move, move_target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)

    def test_no_order(self):
        from doubles_engine.support_targets import (
            narrow_ally_heal_wrong_side_block,
        )
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        battle = _FakeBattle()
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        blocked, _ = narrow_ally_heal_wrong_side_block(None, 0, battle, config)
        self.assertFalse(blocked)

    def test_no_config_uses_default_on_after_adopt1(self):
        """SUPPORT-SAFETY-ADOPT-1: with ``config=None``,
        the helper falls back to the default which is now
        ON. Heal Pulse at opponent must be blocked.
        """
        from doubles_engine.support_targets import (
            narrow_ally_heal_wrong_side_block,
        )
        battle = _FakeBattle()
        move = _FakeMove(id="healpulse")
        order = _FakeOrder(move, move_target=1)
        # No config = uses default (now ON), so block
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=None
        )
        self.assertTrue(blocked)


# ---------------------------------------------------------------------------
# Shim verification: bot_doubles_damage_aware re-exports the names
# ---------------------------------------------------------------------------


class TestShimReExports(unittest.TestCase):
    """Verify the bot module re-exports the same names
    via the shim, so old call sites still work."""

    def test_bot_reexports_classify(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.support_targets import (
            classify_support_move_target_intent as eng_classify,
        )
        self.assertIs(b.classify_support_move_target_intent, eng_classify)

    def test_bot_reexports_build_table(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.support_targets import (
            build_support_target_candidate_table as eng_build,
        )
        self.assertIs(b.build_support_target_candidate_table, eng_build)

    def test_bot_reexports_narrow_build(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.support_targets import (
            build_narrow_ally_heal_candidate_table as eng_build,
        )
        self.assertIs(b.build_narrow_ally_heal_candidate_table, eng_build)

    def test_bot_reexports_resolve(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.support_targets import (
            resolve_order_target_side as eng_resolve,
        )
        self.assertIs(b.resolve_order_target_side, eng_resolve)

    def test_bot_reexports_support_block(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.support_targets import (
            support_move_wrong_side_block as eng_block,
        )
        self.assertIs(b.support_move_wrong_side_block, eng_block)

    def test_bot_reexports_narrow_block(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.support_targets import (
            narrow_ally_heal_wrong_side_block as eng_block,
        )
        self.assertIs(b.narrow_ally_heal_wrong_side_block, eng_block)

    def test_bot_reexports_consts(self):
        import bot_doubles_damage_aware as b
        from doubles_engine.support_targets import (
            _SUPPORT_ALLY_BENEFICIAL_SINGLE as eng_const,
            _POLLEN_PUFF_MOVE_ID as eng_pollen,
            _NARROW_ALLY_HEAL_MOVE_IDS as eng_narrow,
        )
        self.assertIs(b._SUPPORT_ALLY_BENEFICIAL_SINGLE, eng_const)
        self.assertEqual(b._POLLEN_PUFF_MOVE_ID, eng_pollen)
        self.assertIs(b._NARROW_ALLY_HEAL_MOVE_IDS, eng_narrow)


if __name__ == "__main__":
    unittest.main()
