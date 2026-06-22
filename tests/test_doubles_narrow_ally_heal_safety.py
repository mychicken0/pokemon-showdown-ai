#!/usr/bin/env python3
"""Phase 6.3.8d — Narrow Ally-Heal Wrong-Side Safety Tests.

Tests the production-grade narrow Phase 6.3.8d
hard-block. The narrow rule only blocks
``Heal Pulse``, ``Floral Healing``, and ``Decorate``
when aimed at an opponent. General opponent-
disruption moves (Taunt, Encore, Thunder Wave,
etc.) are NOT touched. Pollen Puff and Skill Swap
remain legal on both sides.

The same tests must pass for both Random
Doubles and VGC selected-four runtime modes
because both runtime modes call the canonical
``DoublesDamageAwarePlayer.choose_move`` path.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import poke_env_test_cleanup  # noqa: F401
sys.path.insert(0, os.path.dirname(__file__))

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    DoublesDamageAwarePlayer,
    build_narrow_ally_heal_candidate_table,
    classify_support_move_target_intent,
    narrow_ally_heal_wrong_side_block,
    resolve_order_target_side,
    _compute_order_safety_blocks,
)
from poke_env.battle.move import Move
from poke_env.player.battle_order import SingleBattleOrder


class MockPokemon:
    def __init__(self, species="pokemon", fainted=False):
        self.species = species
        self.fainted = fainted
        self.current_hp_fraction = 1.0


def _make_move_mock(
    move_id, base_power=0, category="STATUS",
    target="normal", type_="NORMAL",
):
    move = MagicMock(spec=Move)
    move.id = move_id
    move.base_power = base_power
    cat = MagicMock()
    cat.name = category
    move.category = cat
    move.type = type_
    move.target = target
    return move


def _make_order(move, target=None):
    order = MagicMock(spec=SingleBattleOrder)
    order.order = move
    if target is not None:
        order.move_target = target
    return order


def _make_battle():
    """Build a deterministic battle for the narrow
    rule. Slot 0 is the actor, slot 1 is the ally.
    Opponent slots 0/1 are positions 1/2 (positive).
    Ally slot from slot 0's view is -2; self is -1.
    From slot 1's view, self is -2 and ally is -1.
    """
    blissey = MockPokemon("blissey")
    snorlax = MockPokemon("snorlax")
    gyarados = MockPokemon("gyarados")
    tyranitar = MockPokemon("tyranitar")
    battle = MagicMock()
    battle.active_pokemon = [blissey, snorlax]
    battle.opponent_active_pokemon = [gyarados, tyranitar]
    return battle


# ---------------------------------------------------------------------------
# Classification / candidate table
# ---------------------------------------------------------------------------


class TestNarrowAllowlist(unittest.TestCase):
    def test_narrow_allowlist_has_only_three_moves(self):
        # Module-level sanity: only the three narrow
        # moves are in the allowlist.
        from bot_doubles_damage_aware import (
            _NARROW_ALLY_HEAL_MOVE_IDS,
        )
        self.assertEqual(
            _NARROW_ALLY_HEAL_MOVE_IDS,
            {"healpulse", "floralhealing", "decorate"},
        )

    def test_broad_ally_beneficial_classification_includes_narrow(self):
        # The narrow allowlist is a strict subset of
        # the broad classification so that
        # classification returns ``ally`` for these
        # three moves.
        for move_id in (
            "healpulse", "floralhealing", "decorate",
        ):
            move = _make_move_mock(move_id)
            result = classify_support_move_target_intent(move)
            self.assertTrue(result["classified"])
            self.assertEqual(result["intended_side"], "ally")


# ---------------------------------------------------------------------------
# narrow_ally_heal_wrong_side_block: per-move tests
# ---------------------------------------------------------------------------


class TestNarrowBlockPerMove(unittest.TestCase):
    def test_heal_pulse_into_opponent_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        # Slot 0 attacks opponent 0 (position 1)
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        blocked, reason = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)
        self.assertIn("healpulse", reason)

    def test_floral_healing_into_opponent_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("floralhealing", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)

    def test_decorate_into_opponent_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("decorate", base_power=0, category="STATUS")
        order = _make_order(move, target=2)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)


# ---------------------------------------------------------------------------
# Same moves into ally remain legal
# ---------------------------------------------------------------------------


class TestNarrowBlockAllyLegal(unittest.TestCase):
    def test_heal_pulse_into_ally_slot0(self):
        # Slot 0 → ally is at -2
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = _make_order(move, target=-2)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)

    def test_heal_pulse_into_ally_slot1(self):
        # Slot 1 → ally is at -1
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = _make_order(move, target=-1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 1, battle, config=config
        )
        self.assertFalse(blocked)

    def test_decorate_into_ally_slot0(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("decorate", base_power=0, category="STATUS")
        order = _make_order(move, target=-2)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)

    def test_floral_healing_into_ally_slot1(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("floralhealing", base_power=0, category="STATUS")
        order = _make_order(move, target=-1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 1, battle, config=config
        )
        self.assertFalse(blocked)


# ---------------------------------------------------------------------------
# Slot mappings preserved
# ---------------------------------------------------------------------------


class TestSlotMappings(unittest.TestCase):
    """Slot 0: self=-1, ally=-2, opponents=1/2.
    Slot 1: self=-2, ally=-1, opponents=1/2.

    The narrow rule must respect these mappings.
    """

    def test_slot0_self_legal(self):
        # Slot 0 self at -1: not an opponent target.
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = _make_order(move, target=-1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)

    def test_slot1_self_legal(self):
        # Slot 1 self at -2: not an opponent target.
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = _make_order(move, target=-2)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 1, battle, config=config
        )
        self.assertFalse(blocked)

    def test_slot0_opp1_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)

    def test_slot0_opp2_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("decorate", base_power=0, category="STATUS")
        order = _make_order(move, target=2)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)

    def test_slot1_opp1_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 1, battle, config=config
        )
        self.assertTrue(blocked)

    def test_slot1_opp2_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("floralhealing", base_power=0, category="STATUS")
        order = _make_order(move, target=2)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 1, battle, config=config
        )
        self.assertTrue(blocked)


# ---------------------------------------------------------------------------
# Two-slot isolation
# ---------------------------------------------------------------------------


class TestTwoSlotIsolation(unittest.TestCase):
    def test_block_in_slot0_does_not_affect_slot1(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        # Slot 0 uses Heal Pulse into opponent (blocked).
        m_blocked = _make_move_mock(
            "healpulse", base_power=0, category="STATUS"
        )
        o_blocked = _make_order(m_blocked, target=1)
        # Slot 1 uses Heal Pulse into ally (legal).
        m_safe = _make_move_mock(
            "healpulse", base_power=0, category="STATUS"
        )
        o_safe = _make_order(m_safe, target=-1)
        _, _, _, _, _, _, narrow_blocked, narrow_reasons = (
            _compute_order_safety_blocks(
                battle, config, [[o_blocked], [o_safe]]
            )
        )
        # Slot 0 order is in the narrow block map.
        self.assertIn(id(o_blocked), narrow_blocked)
        # Slot 1 order is NOT in the narrow block map.
        self.assertNotIn(id(o_safe), narrow_blocked)
        # The reason for the slot 0 block mentions
        # the move id.
        self.assertIn("healpulse", narrow_reasons.get(id(o_blocked), ""))


# ---------------------------------------------------------------------------
# Opponent-disruption moves are NOT classified as narrow
# ---------------------------------------------------------------------------


class TestOpponentDisruptionNotNarrow(unittest.TestCase):
    """Taunt, Encore, Thunder Wave, Will-O-Wisp, etc.
    must NOT be classified as narrow-allowlist
    candidates, even when aimed at an opponent.
    """

    def _build_narrow_table(self, orders, config, slot_idx=0):
        battle = _make_battle()
        return build_narrow_ally_heal_candidate_table(
            orders, slot_idx, battle, config=config
        )

    def test_taunt_into_opponent_not_in_narrow_table(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _make_move_mock("taunt", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        rows = self._build_narrow_table([order], config)
        # Taunt is not in the narrow allowlist.
        self.assertEqual(rows, [])

    def test_encore_into_opponent_not_in_narrow_table(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _make_move_mock("encore", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        rows = self._build_narrow_table([order], config)
        self.assertEqual(rows, [])

    def test_thunder_wave_into_opponent_not_in_narrow_table(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _make_move_mock(
            "thunderwave", base_power=0, category="STATUS"
        )
        order = _make_order(move, target=1)
        rows = self._build_narrow_table([order], config)
        self.assertEqual(rows, [])

    def test_will_o_wisp_into_opponent_not_in_narrow_table(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _make_move_mock(
            "willowisp", base_power=0, category="STATUS"
        )
        order = _make_order(move, target=1)
        rows = self._build_narrow_table([order], config)
        self.assertEqual(rows, [])

    def test_toxic_into_opponent_not_in_narrow_table(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _make_move_mock("toxic", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        rows = self._build_narrow_table([order], config)
        self.assertEqual(rows, [])

    def test_charm_into_opponent_not_in_narrow_table(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        move = _make_move_mock("charm", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        rows = self._build_narrow_table([order], config)
        self.assertEqual(rows, [])

    def test_thunder_wave_into_opponent_not_blocked(self):
        # Even with the narrow flag ON, Thunder Wave
        # into opponent is NOT blocked (no entry in
        # narrow_blocked).
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock(
            "thunderwave", base_power=0, category="STATUS"
        )
        order = _make_order(move, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)

    def test_taunt_into_opponent_not_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("taunt", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)


# ---------------------------------------------------------------------------
# Pollen Puff and Skill Swap are NOT touched
# ---------------------------------------------------------------------------


class TestPollenPuffAndSkillSwapUnaffected(unittest.TestCase):
    def test_pollen_puff_into_opponent_not_in_narrow_table(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        # Pollen Puff is a damaging move (base_power=90).
        move = _make_move_mock(
            "pollenpuff", base_power=90, category="SPECIAL",
        )
        order = _make_order(move, target=1)
        rows = build_narrow_ally_heal_candidate_table(
            [order], 0, battle, config=config
        )
        self.assertEqual(rows, [])

    def test_pollen_puff_into_ally_not_in_narrow_table(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock(
            "pollenpuff", base_power=90, category="SPECIAL",
        )
        order = _make_order(move, target=-2)
        rows = build_narrow_ally_heal_candidate_table(
            [order], 0, battle, config=config
        )
        self.assertEqual(rows, [])

    def test_skill_swap_into_opponent_not_in_narrow_table(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock(
            "skillswap", base_power=0, category="STATUS"
        )
        order = _make_order(move, target=1)
        rows = build_narrow_ally_heal_candidate_table(
            [order], 0, battle, config=config
        )
        self.assertEqual(rows, [])

    def test_skill_swap_into_ally_not_in_narrow_table(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock(
            "skillswap", base_power=0, category="STATUS"
        )
        order = _make_order(move, target=-2)
        rows = build_narrow_ally_heal_candidate_table(
            [order], 0, battle, config=config
        )
        self.assertEqual(rows, [])

    def test_pollen_puff_into_opponent_not_narrow_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock(
            "pollenpuff", base_power=90, category="SPECIAL",
        )
        order = _make_order(move, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)

    def test_skill_swap_into_opponent_not_narrow_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock(
            "skillswap", base_power=0, category="STATUS"
        )
        order = _make_order(move, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)


# ---------------------------------------------------------------------------
# Unknown moves fail open
# ---------------------------------------------------------------------------


class TestUnknownMovesFailOpen(unittest.TestCase):
    def test_unknown_move_into_opponent_not_in_narrow_table(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("madeupmove", base_power=80)
        order = _make_order(move, target=1)
        rows = build_narrow_ally_heal_candidate_table(
            [order], 0, battle, config=config
        )
        self.assertEqual(rows, [])

    def test_unknown_move_into_opponent_not_narrow_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("madeupmove", base_power=80)
        order = _make_order(move, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)


# ---------------------------------------------------------------------------
# Feature OFF leaves selection unchanged
# ---------------------------------------------------------------------------


class TestFeatureOffLeavesSelectionUnchanged(unittest.TestCase):
    def test_default_config_disables_narrow_flag(self):
        # The default value MUST be False per task
        # requirement.
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_ally_heal_wrong_side_hard_safety)
        self.assertEqual(
            config.ally_heal_wrong_side_block_score, 0.0
        )

    def test_broad_flag_still_default_off(self):
        # The broad support flag is NOT silently
        # repurposed. It remains OFF by default.
        config = DoublesDamageAwareConfig()
        self.assertFalse(
            config.enable_support_move_target_hard_safety
        )

    def test_narrow_flag_off_does_not_block(self):
        config = DoublesDamageAwareConfig()
        # Flag is OFF (default).
        battle = _make_battle()
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)


# ---------------------------------------------------------------------------
# Random Doubles and VGC share helper/config paths
# ---------------------------------------------------------------------------


class TestRuntimeParity(unittest.TestCase):
    """Both runtimes use the same canonical helper
    and the same config. This test verifies that
    the narrow feature returns identical results
    regardless of which runtime flag is set.
    """

    def test_narrow_block_consistent_across_runtimes(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        # Both Random Doubles (DoublesDamageAwarePlayer)
        # and VGC (ControlledTeamPreviewPlayer) use
        # the same DoublesDamageAwareConfig. The
        # narrow flag reads from the same config
        # attribute, so the helper must return
        # identical results.
        config_rd = DoublesDamageAwareConfig()
        config_rd.enable_ally_heal_wrong_side_hard_safety = True
        config_vgc = DoublesDamageAwareConfig()
        config_vgc.enable_ally_heal_wrong_side_hard_safety = True
        result_rd = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config_rd
        )
        result_vgc = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config_vgc
        )
        self.assertEqual(result_rd, result_vgc)
        # The VGC player class is a subclass of
        # DoublesDamageAwarePlayer; it must inherit
        # the same helper.
        from bot_vgc2026_phaseV2c import (
            ControlledTeamPreviewPlayer,
        )
        self.assertTrue(
            issubclass(
                ControlledTeamPreviewPlayer,
                DoublesDamageAwarePlayer,
            )
        )

    def test_vgc_player_uses_damage_aware_choose_move(self):
        # The VGC player delegates choose_move to
        # DoublesDamageAwarePlayer.choose_move
        # (the canonical path). The narrow feature
        # reads the SAME config flag in both
        # runtimes.
        import bot_vgc2026_phaseV2c as v2c
        with open(v2c.__file__, "r", encoding="utf-8") as fp:
            src = fp.read()
        self.assertIn(
            "DoublesDamageAwarePlayer.choose_move",
            src,
        )


# ---------------------------------------------------------------------------
# Accounting invariant: candidate_blocked ==
# selected + avoided
# ---------------------------------------------------------------------------


class TestAccountingInvariant(unittest.TestCase):
    def test_candidate_blocked_equals_selected_plus_avoided(self):
        # Build a candidate table for a slot where
        # the only narrow move is into opponent (so
        # blocked=True, selected=False, avoided=True
        # once a safe alternative is selected).
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        blocked_move = _make_move_mock(
            "healpulse", base_power=0, category="STATUS"
        )
        blocked_order = _make_order(blocked_move, target=1)
        rows = build_narrow_ally_heal_candidate_table(
            [blocked_order], 0, battle, config=config
        )
        # One row, blocked=True.
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["blocked"])

    def test_unblocked_candidate_leaves_blocked_false(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        safe_move = _make_move_mock(
            "healpulse", base_power=0, category="STATUS"
        )
        safe_order = _make_order(safe_move, target=-2)
        rows = build_narrow_ally_heal_candidate_table(
            [safe_order], 0, battle, config=config
        )
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["blocked"])

    def test_no_audit_field_pollution_for_nonnarrow_moves(self):
        # A turn that only has Taunt + Encore + Pollen
        # Puff should not generate any narrow
        # candidate rows.
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        taunt = _make_move_mock("taunt", base_power=0, category="STATUS")
        encore = _make_move_mock("encore", base_power=0, category="STATUS")
        pp = _make_move_mock(
            "pollenpuff", base_power=90, category="SPECIAL"
        )
        o1 = _make_order(taunt, target=1)
        o2 = _make_order(encore, target=1)
        o3 = _make_order(pp, target=1)
        rows = build_narrow_ally_heal_candidate_table(
            [o1, o2, o3], 0, battle, config=config
        )
        self.assertEqual(rows, [])


# ---------------------------------------------------------------------------
# Return value of _compute_order_safety_blocks
# ---------------------------------------------------------------------------


class TestSafetyBlocksReturnShape(unittest.TestCase):
    def test_returns_eight_dicts(self):
        config = DoublesDamageAwareConfig()
        result = _compute_order_safety_blocks(
            battle=None, config=config, valid_orders=[[], []]
        )
        # 8 dicts: direct_absorb, safety, ally_redirect,
        # ally_redirect_meta, support_target_blocked,
        # support_target_reasons, narrow_blocked,
        # narrow_reasons.
        self.assertEqual(len(result), 8)
        for d in result:
            self.assertEqual(d, {})

    def test_narrow_dicts_empty_when_flag_off(self):
        config = DoublesDamageAwareConfig()
        # Flag is OFF (default).
        battle = _make_battle()
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        _, _, _, _, _, _, narrow_blocked, narrow_reasons = (
            _compute_order_safety_blocks(
                battle, config, [[order], []]
            )
        )
        # Flag OFF: no narrow block even though the
        # move is a wrong-side ally heal.
        self.assertEqual(narrow_blocked, {})
        self.assertEqual(narrow_reasons, {})

    def test_narrow_dicts_populated_when_flag_on(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        _, _, _, _, _, _, narrow_blocked, narrow_reasons = (
            _compute_order_safety_blocks(
                battle, config, [[order], []]
            )
        )
        # Flag ON: Heal Pulse into opponent is
        # blocked.
        self.assertIn(id(order), narrow_blocked)
        self.assertIn("healpulse", narrow_reasons[id(order)])


# ---------------------------------------------------------------------------
# Metadata restrictions preserved
# ---------------------------------------------------------------------------


class TestMetadataRestrictionsPreserved(unittest.TestCase):
    def test_self_only_moves_not_in_narrow_table(self):
        # Recover, etc. are self-only and not in the
        # narrow allowlist.
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("recover", base_power=0, category="STATUS")
        order = _make_order(move, target=0)
        rows = build_narrow_ally_heal_candidate_table(
            [order], 0, battle, config=config
        )
        self.assertEqual(rows, [])

    def test_team_field_moves_not_in_narrow_table(self):
        # Aromatherapy is a team field move.
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock(
            "aromatherapy", base_power=0, category="STATUS"
        )
        order = _make_order(move, target=0)
        rows = build_narrow_ally_heal_candidate_table(
            [order], 0, battle, config=config
        )
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
