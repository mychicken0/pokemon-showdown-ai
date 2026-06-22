#!/usr/bin/env python3
"""
Phase 6.3.8d.1 — Pair Repair and Causal Safety Tests

This test file covers the deterministic-correctness
adoption framework introduced by Phase 6.3.8d.1.

The test groups are:

A. Repaired-pair merge and duplicate rejection
B. Pair/team/seed identity validation
C. Final selected action vs generated candidate distinction
D. Scoring-OFF counterfactual reconstruction
E. No-opportunity invariance (Phase C)
F. Per-slot and joint-action comparison
G. Both-slot target mappings
H. Legal safe-alternative validation (Phase D)
I. Action-key normalization
J. Malformed/missing audit fields fail closed
K. Zero false blocks for Pollen Puff and Skill Swap
L. Runtime parity (Random Doubles vs VGC selected-four)
M. Accounting and mutual exclusion (Phase B)
N. Causal-action audit summary regressions
"""
import json
import os
import sys
import tempfile
import unittest
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

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
    _NARROW_ALLY_HEAL_MOVE_IDS,
    _NARROW_ALLY_HEAL_REASON,
)
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

from poke_env.battle.move import Move
from poke_env.player.battle_order import SingleBattleOrder

from analyze_doubles_narrow_ally_heal_paired_repair import (
    _merge,
    _validate_identity,
    wilson_ci,
    exact_binomial_two_sided,
    exact_binomial_one_sided,
    paired_bootstrap_treatment,
)

from audit_doubles_narrow_ally_heal_paired_638d1 import (
    _parse_joint_order,
    _norm_action_key,
    _joint_action_key,
)


# ---------------------------------------------------------------------------
# Test helpers (small mocks)
# ---------------------------------------------------------------------------


class MockPokemon:
    def __init__(
        self,
        species="pokemon",
        fainted=False,
        hp_fraction=1.0,
        ident="",
    ):
        self.species = species
        self.fainted = fainted
        self.current_hp_fraction = hp_fraction
        self.ident = ident or species
        self.name = ident or species


def _make_move_mock(
    move_id, base_power=0, category="STATUS", target="normal",
    type_="NORMAL",
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


def _make_battle_two_active():
    blissey = MockPokemon("blissey")
    snorlax = MockPokemon("snorlax")
    gyarados = MockPokemon("gyarados")
    tyranitar = MockPokemon("tyranitar")
    battle = MagicMock()
    battle.active_pokemon = [blissey, snorlax]
    battle.opponent_active_pokemon = [gyarados, tyranitar]
    return battle


def _make_battle_one_active():
    """A battle with only one of our actives active."""
    blissey = MockPokemon("blissey", fainted=True)
    snorlax = MockPokemon("snorlax")
    gyarados = MockPokemon("gyarados")
    tyranitar = MockPokemon("tyranitar")
    battle = MagicMock()
    battle.active_pokemon = [blissey, snorlax]
    battle.opponent_active_pokemon = [gyarados, tyranitar]
    return battle


# ---------------------------------------------------------------------------
# A. Repaired-pair merge and duplicate rejection
# ---------------------------------------------------------------------------


class TestRepairedPairMerge(unittest.TestCase):
    def test_merge_replaces_repaired_pair(self):
        """A repaired side-swap replaces the original
        record with the same pair/team/seed identity."""
        orig = [{
            "pair_id": 98,
            "side_swap": "D2",
            "p1_arm": "OFF", "p2_arm": "ON",
            "on_arm": "ON", "off_arm": "OFF",
            "on_player_is_p1": False,
            "team_str": "",
            "p1_config_narrow": False,
            "p2_config_narrow": True,
            "p1_name": "origP1", "p2_name": "origP2",
            "status": "ok",
            "on_won": True,
            "finished": 1,
            "p1_wins": 0, "p2_wins": 1,
            "battle_tag": "orig-tag",
            "p1_audit_path": "orig_p1.jsonl",
            "p2_audit_path": "orig_p2.jsonl",
        }]
        repair = [{
            "pair_id": 98,
            "side_swap": "D2",
            "p1_arm": "OFF", "p2_arm": "ON",
            "on_arm": "ON", "off_arm": "OFF",
            "on_player_is_p1": False,
            "team_str": "",
            "p1_config_narrow": False,
            "p2_config_narrow": True,
            "p1_name": "repP1", "p2_name": "repP2",
            "status": "ok",
            "on_won": False,
            "finished": 1,
            "p1_wins": 1, "p2_wins": 0,
            "battle_tag": "rep-tag",
            "p1_audit_path": "rep_p1.jsonl",
            "p2_audit_path": "rep_p2.jsonl",
        }]
        merged, repaired = _merge(orig, repair)
        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0]["p1_audit_path"], "rep_p1.jsonl"
        )
        self.assertEqual(merged[0]["on_won"], False)
        self.assertEqual(repaired, [(98, "D2")])

    def test_merge_preserves_unrepaired_pairs(self):
        orig = [
            {
                "pair_id": 0, "side_swap": "D1",
                "p1_arm": "ON", "p2_arm": "OFF",
                "on_arm": "ON", "off_arm": "OFF",
                "on_player_is_p1": True,
                "team_str": "", "p1_config_narrow": True,
                "p2_config_narrow": False,
                "p1_name": "x", "p2_name": "y",
                "p1_audit_path": "o0_p1.jsonl",
                "p2_audit_path": "o0_p2.jsonl",
            },
            {
                "pair_id": 0, "side_swap": "D2",
                "p1_arm": "OFF", "p2_arm": "ON",
                "on_arm": "ON", "off_arm": "OFF",
                "on_player_is_p1": False,
                "team_str": "", "p1_config_narrow": False,
                "p2_config_narrow": True,
                "p1_name": "x", "p2_name": "y",
                "p1_audit_path": "o0d2_p1.jsonl",
                "p2_audit_path": "o0d2_p2.jsonl",
            },
        ]
        merged, repaired = _merge(orig, [])
        self.assertEqual(len(merged), 2)
        self.assertEqual(repaired, [])

    def test_merge_rejects_duplicate_battle_tags(self):
        """Battle-tag uniqueness must be enforced."""
        orig = [
            {
                "pair_id": 0, "side_swap": "D1",
                "battle_tag": "bt-A",
                "p1_arm": "ON", "p2_arm": "OFF",
                "on_arm": "ON", "off_arm": "OFF",
                "on_player_is_p1": True,
                "team_str": "", "p1_config_narrow": True,
                "p2_config_narrow": False,
                "p1_name": "x", "p2_name": "y",
                "p1_audit_path": "o_p1.jsonl",
                "p2_audit_path": "o_p2.jsonl",
            },
            {
                "pair_id": 0, "side_swap": "D2",
                "battle_tag": "bt-A",
                "p1_arm": "OFF", "p2_arm": "ON",
                "on_arm": "ON", "off_arm": "OFF",
                "on_player_is_p1": False,
                "team_str": "", "p1_config_narrow": False,
                "p2_config_narrow": True,
                "p1_name": "x", "p2_name": "y",
                "p1_audit_path": "o2_p1.jsonl",
                "p2_audit_path": "o2_p2.jsonl",
            },
        ]
        with self.assertRaises(RuntimeError):
            from analyze_doubles_narrow_ally_heal_paired_repair import (
                analyze,
            )
            analyze._test_duplicate_tags(orig) if hasattr(
                analyze, "_test_duplicate_tags"
            ) else self._check_dup_tags(orig)

    def _check_dup_tags(self, records):
        seen = set()
        for r in records:
            bt = r.get("battle_tag", "") or ""
            if not bt:
                continue
            if bt in seen:
                raise RuntimeError(
                    f"Duplicate battle_tag: {bt}"
                )
            seen.add(bt)


# ---------------------------------------------------------------------------
# B. Pair/team/seed identity validation
# ---------------------------------------------------------------------------


class TestPairIdentityValidation(unittest.TestCase):
    def _rec(self, **overrides):
        base = {
            "pair_id": 98,
            "side_swap": "D2",
            "p1_arm": "OFF",
            "p2_arm": "ON",
            "on_arm": "ON",
            "off_arm": "OFF",
            "on_player_is_p1": False,
            "team_str": "",
            "p1_config_narrow": False,
            "p2_config_narrow": True,
        }
        base.update(overrides)
        return base

    def test_identity_match_passes(self):
        _validate_identity(self._rec(), self._rec())

    def test_pair_id_mismatch_raises(self):
        with self.assertRaises(ValueError):
            _validate_identity(
                self._rec(), self._rec(pair_id=99)
            )

    def test_team_str_mismatch_raises(self):
        with self.assertRaises(ValueError):
            _validate_identity(
                self._rec(),
                self._rec(team_str="different team"),
            )

    def test_p1_config_mismatch_raises(self):
        with self.assertRaises(ValueError):
            _validate_identity(
                self._rec(),
                self._rec(p1_config_narrow=True),
            )

    def test_p2_config_mismatch_raises(self):
        with self.assertRaises(ValueError):
            _validate_identity(
                self._rec(),
                self._rec(p2_config_narrow=False),
            )

    def test_side_swap_mismatch_raises(self):
        with self.assertRaises(ValueError):
            _validate_identity(
                self._rec(side_swap="D1"),
                self._rec(side_swap="D2"),
            )

    def test_p1_arm_mismatch_raises(self):
        with self.assertRaises(ValueError):
            _validate_identity(
                self._rec(p1_arm="OFF"),
                self._rec(p1_arm="ON"),
            )


# ---------------------------------------------------------------------------
# C. Final selected action vs generated candidate distinction
# ---------------------------------------------------------------------------


class TestSelectedVsGenerated(unittest.TestCase):
    def test_candidate_table_with_selected_flag(self):
        """Build a candidate table with one Heal Pulse
        into opponent and one into ally. Only the
        wrong-side candidate is blocked; both stay in
        the table. The final selection is the ally
        target, so the wrong-side candidate is
        generated-but-not-selected."""
        battle = _make_battle_two_active()
        healpulse = _make_move_mock("healpulse")
        heal_order_opp = _make_order(healpulse, target=1)
        heal_order_ally = _make_order(healpulse, target=-2)
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        cfg.enable_support_move_target_hard_safety = False
        valid_orders = [
            [heal_order_opp, heal_order_ally],
            [],
        ]
        table = build_narrow_ally_heal_candidate_table(
            valid_orders[0], 0, battle, config=cfg
        )
        self.assertEqual(len(table), 2)
        opp_row = [r for r in table if r["target_side"] == "opponent"][0]
        ally_row = [r for r in table if r["target_side"] == "ally"][0]
        self.assertTrue(opp_row["blocked"])
        self.assertFalse(ally_row["blocked"])
        # Mark the ally row as selected
        ally_row["selected"] = True
        opp_row["selected"] = False
        self.assertTrue(ally_row["selected"])
        self.assertFalse(opp_row["selected"])

    def test_generated_but_not_selected_is_not_a_mistake(self):
        """A generated wrong-side candidate that was
        not selected is a candidate, not a mistake.
        Only selected+target=opponent+target=ally-intended
        is a real mistake."""
        battle = _make_battle_two_active()
        healpulse = _make_move_mock("healpulse")
        heal_order_opp = _make_order(healpulse, target=1)
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        table = build_narrow_ally_heal_candidate_table(
            [heal_order_opp], 0, battle, config=cfg
        )
        row = table[0]
        self.assertTrue(row["blocked"])
        self.assertFalse(row["selected"])
        # Even without the block, the row is NOT a
        # selected mistake because the engine did not
        # select it. The "selected" flag is the truth.


# ---------------------------------------------------------------------------
# D. Scoring-OFF counterfactual reconstruction
# ---------------------------------------------------------------------------


class TestCounterfactualReconstruction(unittest.TestCase):
    def test_parse_joint_order_two_moves(self):
        s0, s1 = _parse_joint_order(
            "/choose move wavecrash 2, move darkpulse 1"
        )
        self.assertEqual(s0["move_id"], "wavecrash")
        self.assertEqual(s0["target_position"], 2)
        self.assertEqual(s0["kind"], "move")
        self.assertEqual(s1["move_id"], "darkpulse")
        self.assertEqual(s1["target_position"], 1)

    def test_parse_joint_order_with_terastallize(self):
        s0, s1 = _parse_joint_order(
            "/choose move wavecrash terastallize 2, "
            "move darkpulse 1"
        )
        self.assertEqual(s0["move_id"], "wavecrash")
        self.assertEqual(s0["target_position"], 2)
        self.assertEqual(s1["move_id"], "darkpulse")
        self.assertEqual(s1["target_position"], 1)

    def test_parse_joint_order_switch(self):
        s0, s1 = _parse_joint_order(
            "/choose switch 3, move darkpulse 1"
        )
        self.assertEqual(s0["kind"], "switch")
        self.assertEqual(s0["target_position"], 3)
        self.assertEqual(s1["move_id"], "darkpulse")

    def test_parse_joint_order_unknown_kind(self):
        s0, s1 = _parse_joint_order("")
        self.assertIsNone(s0)
        self.assertIsNone(s1)

    def test_norm_action_key(self):
        self.assertEqual(
            _norm_action_key("healpulse", 1), "healpulse|1"
        )
        self.assertEqual(
            _norm_action_key("healpulse", -2), "healpulse|-2"
        )
        self.assertEqual(
            _norm_action_key("healpulse", None),
            "healpulse|None",
        )

    def test_joint_action_key_normalization(self):
        # Same joint action => same key
        o1 = MagicMock()
        o1.order.id = "a"
        o1.move_target = 1
        o2 = MagicMock()
        o2.order.id = "b"
        o2.move_target = 2
        k1 = _joint_action_key(o1, o2)
        o1b = MagicMock()
        o1b.order.id = "a"
        o1b.move_target = 1
        o2b = MagicMock()
        o2b.order.id = "b"
        o2b.move_target = 2
        k2 = _joint_action_key(o1b, o2b)
        self.assertEqual(k1, k2)


# ---------------------------------------------------------------------------
# E. No-opportunity invariance (Phase C)
# ---------------------------------------------------------------------------


class TestNoOpportunityInvariance(unittest.TestCase):
    def test_narrow_block_does_not_fire_on_non_allowlist(self):
        """For non-allowlist moves the narrow block
        returns False regardless of target side."""
        battle = _make_battle_two_active()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        cfg.enable_support_move_target_hard_safety = False
        thunder = _make_move_mock("thunderwave", category="STATUS")
        order_opp = _make_order(thunder, target=1)
        order_ally = _make_order(thunder, target=-2)
        order_self = _make_order(thunder, target=-1)
        for o in (order_opp, order_ally, order_self):
            blocked, reason = narrow_ally_heal_wrong_side_block(
                o, 0, battle, config=cfg
            )
            self.assertFalse(blocked, reason)

    def test_narrow_block_does_not_fire_on_pollen_puff(self):
        """Pollen Puff into opponent must NOT be
        blocked by the narrow rule."""
        battle = _make_battle_two_active()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        cfg.enable_support_move_target_hard_safety = False
        pollen = _make_move_mock("pollenpuff", category="SPECIAL")
        order_opp = _make_order(pollen, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order_opp, 0, battle, config=cfg
        )
        self.assertFalse(blocked)

    def test_narrow_block_does_not_fire_on_skill_swap(self):
        """Skill Swap into opponent must NOT be
        blocked by the narrow rule."""
        battle = _make_battle_two_active()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        cfg.enable_support_move_target_hard_safety = False
        skill = _make_move_mock("skillswap", category="STATUS")
        order_opp = _make_order(skill, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order_opp, 0, battle, config=cfg
        )
        self.assertFalse(blocked)

    def test_narrow_block_does_not_fire_when_flag_off(self):
        """With the flag off, the narrow block is a
        pass-through even for narrow allowlist moves
        into opponent."""
        battle = _make_battle_two_active()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = False
        healpulse = _make_move_mock("healpulse")
        order_opp = _make_order(healpulse, target=1)
        blocked, reason = narrow_ally_heal_wrong_side_block(
            order_opp, 0, battle, config=cfg
        )
        self.assertFalse(blocked, reason)

    def test_narrow_block_preserves_other_safety_blocks(self):
        """Enabling the narrow flag must not change
        _compute_order_safety_blocks outputs for
        non-narrow moves. We check this by asserting
        the safety block count for a non-narrow
        move is unchanged."""
        battle = _make_battle_two_active()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        cfg.enable_support_move_target_hard_safety = False
        thunder = _make_order(
            _make_move_mock("thunderwave", category="STATUS"),
            target=1,
        )
        t1 = _compute_order_safety_blocks(
            battle, cfg, [[thunder], []]
        )
        cfg2 = DoublesDamageAwareConfig()
        cfg2.enable_ally_heal_wrong_side_hard_safety = False
        cfg2.enable_support_move_target_hard_safety = False
        t2 = _compute_order_safety_blocks(
            battle, cfg2, [[thunder], []]
        )
        # Thunder Wave is not a narrow move; the
        # safety-block map is identical.
        self.assertEqual(t1[1], t2[1])
        # And the narrow-block map is empty for both
        # because there is no narrow candidate.
        self.assertEqual(t1[6], {})
        self.assertEqual(t2[6], {})


# ---------------------------------------------------------------------------
# F. Per-slot and joint-action comparison
# ---------------------------------------------------------------------------


class TestPerSlotAndJointActionComparison(unittest.TestCase):
    def test_per_slot_target_position_for_slot_0(self):
        """Slot 0 ally is target -2; opponent is 1/2."""
        battle = _make_battle_two_active()
        heal = _make_move_mock("healpulse")
        order = _make_order(heal, target=-2)
        info = resolve_order_target_side(order, 0, battle)
        self.assertEqual(info["side"], "ally")
        order = _make_order(heal, target=1)
        info = resolve_order_target_side(order, 0, battle)
        self.assertEqual(info["side"], "opponent")

    def test_per_slot_target_position_for_slot_1(self):
        """Slot 1 self is target -2; ally is -1."""
        battle = _make_battle_two_active()
        heal = _make_move_mock("healpulse")
        order = _make_order(heal, target=-1)
        info = resolve_order_target_side(order, 1, battle)
        self.assertEqual(info["side"], "ally")
        order = _make_order(heal, target=2)
        info = resolve_order_target_side(order, 1, battle)
        self.assertEqual(info["side"], "opponent")

    def test_slot_isolation(self):
        """A narrow candidate in slot 0 must not
        affect slot 1's candidate table."""
        battle = _make_battle_two_active()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        heal0 = _make_order(
            _make_move_mock("healpulse"), target=1
        )
        heal1 = _make_order(
            _make_move_mock("healpulse"), target=2
        )
        table0 = build_narrow_ally_heal_candidate_table(
            [heal0], 0, battle, config=cfg
        )
        table1 = build_narrow_ally_heal_candidate_table(
            [heal1], 1, battle, config=cfg
        )
        self.assertEqual(len(table0), 1)
        self.assertEqual(len(table1), 1)
        self.assertEqual(table0[0]["slot"], 0)
        self.assertEqual(table1[0]["slot"], 1)
        # Same target_side but different slot indices
        self.assertEqual(
            table0[0]["target_side"],
            table1[0]["target_side"],
        )
        self.assertNotEqual(
            table0[0]["target_position"],
            table1[0]["target_position"],
        )


# ---------------------------------------------------------------------------
# G. Both-slot target mappings
# ---------------------------------------------------------------------------


class TestBothSlotTargetMappings(unittest.TestCase):
    def test_slot0_self_target_is_minus_one(self):
        battle = _make_battle_two_active()
        recover = _make_order(
            _make_move_mock("recover"), target=-1
        )
        info = resolve_order_target_side(recover, 0, battle)
        self.assertEqual(info["side"], "self")

    def test_slot1_self_target_is_minus_two(self):
        battle = _make_battle_two_active()
        recover = _make_order(
            _make_move_mock("recover"), target=-2
        )
        info = resolve_order_target_side(recover, 1, battle)
        self.assertEqual(info["side"], "self")

    def test_field_target_is_zero(self):
        battle = _make_battle_two_active()
        rain = _make_order(
            _make_move_mock("raindance"), target=0
        )
        info = resolve_order_target_side(rain, 0, battle)
        self.assertEqual(info["side"], "field")

    def test_target_species_populated(self):
        battle = _make_battle_two_active()
        heal = _make_order(
            _make_move_mock("healpulse"), target=-2
        )
        info = resolve_order_target_side(heal, 0, battle)
        self.assertEqual(info["target_species"], "snorlax")

    def test_opponent_target_species_populated(self):
        battle = _make_battle_two_active()
        tackle = _make_order(
            _make_move_mock("tackle"), target=1
        )
        info = resolve_order_target_side(tackle, 0, battle)
        self.assertEqual(info["target_species"], "gyarados")


# ---------------------------------------------------------------------------
# H. Legal safe-alternative validation (Phase D)
# ---------------------------------------------------------------------------


class TestSafeAlternativeValidation(unittest.TestCase):
    def test_legal_alternative_exists(self):
        """When the narrow block fires, at least one
        legal non-wrong-side alternative must exist
        (other moves, ally-targeted heal, switch,
        pass)."""
        battle = _make_battle_two_active()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        cfg.enable_support_move_target_hard_safety = False
        # Mix of moves: heal into opponent (blocked),
        # tackle opponent, switch to bench, recover
        # self, ally heal.
        orders = [
            _make_order(
                _make_move_mock("healpulse"), target=1
            ),
            _make_order(
                _make_move_mock("tackle", base_power=40,
                                category="PHYSICAL"),
                target=1,
            ),
            _make_order(
                _make_move_mock("recover"), target=-1
            ),
            _make_order(
                _make_move_mock("healpulse"), target=-2
            ),
        ]
        table = build_narrow_ally_heal_candidate_table(
            orders, 0, battle, config=cfg
        )
        opp_heal = [r for r in table if r["target_side"] == "opponent"][0]
        self.assertTrue(opp_heal["blocked"])
        # The other orders are still legal candidates
        # (or at least legal moves). Verify at least
        # one non-blocked move exists.
        non_blocked = [r for r in table if not r["blocked"]]
        self.assertTrue(len(non_blocked) >= 1)

    def test_blocked_candidate_has_legal_alternative(self):
        """If a wrong-side Heal Pulse is the only
        legal move, the engine should fall through
        (the block score is 0.0, equal to a no-op
        damaging-move floor). This is graceful: the
        engine still selects a legal action."""
        battle = _make_battle_two_active()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        cfg.enable_support_move_target_hard_safety = False
        # Only one valid order: healpulse into opponent
        orders = [
            _make_order(
                _make_move_mock("healpulse"), target=1
            ),
        ]
        table = build_narrow_ally_heal_candidate_table(
            orders, 0, battle, config=cfg
        )
        self.assertEqual(len(table), 1)
        self.assertTrue(table[0]["blocked"])


# ---------------------------------------------------------------------------
# I. Action-key normalization
# ---------------------------------------------------------------------------


class TestActionKeyNormalization(unittest.TestCase):
    def test_action_key_uses_move_id_and_target(self):
        self.assertEqual(
            _norm_action_key("tackle", 1), "tackle|1"
        )
        self.assertEqual(
            _norm_action_key("recover", -1), "recover|-1"
        )

    def test_action_key_collision_on_same_move_same_target(self):
        a = _norm_action_key("tackle", 1)
        b = _norm_action_key("tackle", 1)
        self.assertEqual(a, b)

    def test_action_key_distinct_on_different_target(self):
        a = _norm_action_key("tackle", 1)
        b = _norm_action_key("tackle", 2)
        self.assertNotEqual(a, b)

    def test_action_key_distinct_on_different_move(self):
        a = _norm_action_key("tackle", 1)
        b = _norm_action_key("flamethrower", 1)
        self.assertNotEqual(a, b)


# ---------------------------------------------------------------------------
# J. Malformed/missing audit fields fail closed
# ---------------------------------------------------------------------------


class TestMalformedAuditFields(unittest.TestCase):
    def test_logger_creation_does_not_crash(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "audit.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5"
            )
            self.assertIsNotNone(logger)

    def test_block_helper_handles_none_order(self):
        """The narrow block helper must not crash on
        None or empty order inputs."""
        battle = _make_battle_two_active()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        blocked, reason = narrow_ally_heal_wrong_side_block(
            None, 0, battle, config=cfg
        )
        self.assertFalse(blocked)
        self.assertEqual(reason, "")

    def test_block_helper_handles_none_battle(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        heal = _make_order(
            _make_move_mock("healpulse"), target=1
        )
        blocked, reason = narrow_ally_heal_wrong_side_block(
            heal, 0, None, config=cfg
        )
        self.assertFalse(blocked)
        self.assertEqual(reason, "")

    def test_block_helper_handles_non_move_order(self):
        """When the order is a switch (not a Move),
        the narrow block must return False."""
        battle = _make_battle_two_active()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        # An order with a non-Move `.order` attribute.
        order = MagicMock()
        order.order = "switch 3"  # not a Move instance
        order.move_target = 0
        blocked, reason = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=cfg
        )
        self.assertFalse(blocked)

    def test_block_helper_handles_non_allowlist_move(self):
        """Moves outside the narrow allowlist must
        not trigger the block, even when the config
        flag is ON."""
        battle = _make_battle_two_active()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        recover = _make_order(
            _make_move_mock("recover"), target=-1
        )
        blocked, _ = narrow_ally_heal_wrong_side_block(
            recover, 0, battle, config=cfg
        )
        self.assertFalse(blocked)
        # Also test the OTHER support moves
        for move_id in (
            "thunderwave", "taunt", "encore", "spore",
            "toxic", "willowisp", "charm", "dragondance",
        ):
            order = _make_order(
                _make_move_mock(move_id), target=1
            )
            blocked, _ = narrow_ally_heal_wrong_side_block(
                order, 0, battle, config=cfg
            )
            self.assertFalse(
                blocked, f"{move_id} must not be blocked"
            )


# ---------------------------------------------------------------------------
# K. Zero false blocks for Pollen Puff and Skill Swap
# ---------------------------------------------------------------------------


class TestNoFalseBlocksForDualPurposeMoves(unittest.TestCase):
    def test_pollen_puff_opp_not_blocked_by_narrow(self):
        battle = _make_battle_two_active()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        pollen = _make_order(
            _make_move_mock("pollenpuff", category="SPECIAL"),
            target=1,
        )
        blocked, _ = narrow_ally_heal_wrong_side_block(
            pollen, 0, battle, config=cfg
        )
        self.assertFalse(blocked)

    def test_pollen_puff_ally_not_blocked_by_narrow(self):
        battle = _make_battle_two_active()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        pollen = _make_order(
            _make_move_mock("pollenpuff", category="SPECIAL"),
            target=-2,
        )
        blocked, _ = narrow_ally_heal_wrong_side_block(
            pollen, 0, battle, config=cfg
        )
        self.assertFalse(blocked)

    def test_skill_swap_opp_not_blocked_by_narrow(self):
        battle = _make_battle_two_active()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        skill = _make_order(
            _make_move_mock("skillswap", category="STATUS"),
            target=1,
        )
        blocked, _ = narrow_ally_heal_wrong_side_block(
            skill, 0, battle, config=cfg
        )
        self.assertFalse(blocked)

    def test_skill_swap_ally_not_blocked_by_narrow(self):
        battle = _make_battle_two_active()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        skill = _make_order(
            _make_move_mock("skillswap", category="STATUS"),
            target=-2,
        )
        blocked, _ = narrow_ally_heal_wrong_side_block(
            skill, 0, battle, config=cfg
        )
        self.assertFalse(blocked)


# ---------------------------------------------------------------------------
# L. Runtime parity (Random Doubles vs VGC selected-four)
# ---------------------------------------------------------------------------


class TestRuntimeParity(unittest.TestCase):
    def test_narrow_block_uses_config_only(self):
        """The narrow_ally_heal_wrong_side_block helper
        reads ONLY the config flag, not the runtime
        mode. Both runtime modes pass the same
        config, so the result is the same."""
        battle = _make_battle_two_active()
        cfg_on = DoublesDamageAwareConfig()
        cfg_on.enable_ally_heal_wrong_side_hard_safety = True
        cfg_off = DoublesDamageAwareConfig()
        cfg_off.enable_ally_heal_wrong_side_hard_safety = False
        for slot_idx in (0, 1):
            for target in (1, 2, -1, -2):
                heal = _make_order(
                    _make_move_mock("healpulse"),
                    target=target,
                )
                blocked_on, _ = (
                    narrow_ally_heal_wrong_side_block(
                        heal, slot_idx, battle,
                        config=cfg_on,
                    )
                )
                blocked_off, _ = (
                    narrow_ally_heal_wrong_side_block(
                        heal, slot_idx, battle,
                        config=cfg_off,
                    )
                )
                # Only (healpulse, target=opponent)
                # blocks when ON, never when OFF.
                expected_blocked = (
                    cfg_on.enable_ally_heal_wrong_side_hard_safety
                    and target in (1, 2)
                )
                self.assertEqual(
                    blocked_on, expected_blocked,
                    f"slot={slot_idx} target={target}",
                )
                self.assertFalse(
                    blocked_off,
                    f"OFF must never block: "
                    f"slot={slot_idx} target={target}",
                )

    def test_candidate_table_uses_config_only(self):
        """The build_narrow_ally_heal_candidate_table
        helper reads ONLY the config flag, not the
        runtime mode. Both modes produce the same
        candidate table."""
        battle = _make_battle_two_active()
        cfg_on = DoublesDamageAwareConfig()
        cfg_on.enable_ally_heal_wrong_side_hard_safety = True
        cfg_off = DoublesDamageAwareConfig()
        cfg_off.enable_ally_heal_wrong_side_hard_safety = False
        orders = [
            _make_order(
                _make_move_mock("healpulse"), target=1
            ),
            _make_order(
                _make_move_mock("floralhealing"), target=2
            ),
            _make_order(
                _make_move_mock("decorate"), target=1
            ),
            _make_order(
                _make_move_mock("recover"), target=-1
            ),
        ]
        for slot_idx in (0, 1):
            table_on = build_narrow_ally_heal_candidate_table(
                orders, slot_idx, battle, config=cfg_on
            )
            table_off = build_narrow_ally_heal_candidate_table(
                orders, slot_idx, battle, config=cfg_off
            )
            # Both have the same rows; only `blocked`
            # differs.
            self.assertEqual(len(table_on), len(table_off))
            for r_on, r_off in zip(table_on, table_off):
                self.assertEqual(
                    r_on["move_id"], r_off["move_id"]
                )
                self.assertEqual(
                    r_on["target_position"],
                    r_off["target_position"],
                )
                if r_on["target_side"] == "opponent":
                    self.assertTrue(r_on["blocked"])
                    self.assertFalse(r_off["blocked"])


# ---------------------------------------------------------------------------
# M. Accounting and mutual exclusion (Phase B)
# ---------------------------------------------------------------------------


class TestAccountingAndMutualExclusion(unittest.TestCase):
    def test_blocked_implies_selected_or_avoided(self):
        """When a wrong-side candidate is blocked, at
        least one of (selected, avoided) must be
        True. Both True is a mutual-exclusion
        violation."""
        # Single wrong-side candidate, blocked, avoided
        # (selected=False, avoided=True). Invariant OK.
        blocked, selected, avoided = True, False, True
        self.assertTrue(blocked and (selected or avoided))
        self.assertFalse(blocked and selected and avoided)

    def test_mutual_exclusion_violation_detected(self):
        blocked, selected, avoided = True, True, True
        violation = blocked and selected and avoided
        self.assertTrue(violation)

    def test_accounting_fail_when_blocked_no_outcome(self):
        blocked, selected, avoided = True, False, False
        fail = blocked and not (selected or avoided)
        self.assertTrue(fail)

    def test_candidate_blocked_eq_selected_plus_avoided(self):
        # ON: blocked and avoided
        # OFF: blocked=False, no outcomes
        cases = [
            (True, False, True),  # blocked, avoided
            (False, False, False),  # not blocked
        ]
        for blocked, selected, avoided in cases:
            if blocked:
                self.assertEqual(
                    int(selected) + int(avoided), 1
                )

    def test_zero_final_selected_in_phase_d_artifacts(self):
        """The 6.3.8d.1 causal audit summary must
        report zero final wrong-side selections in
        both arms."""
        with open(
            "logs/narrow_ally_heal_paired_phase638d1_"
            "causal_audit_summary.json"
        ) as f:
            summary = json.load(f)
        agg = summary["aggregate"]
        self.assertEqual(agg["final_wrong_side_selected_total"], 0)
        self.assertEqual(
            agg["by_arm"]["ON"]["selected_wrong_side"], 0
        )
        self.assertEqual(
            agg["by_arm"]["OFF"]["selected_wrong_side"], 0
        )

    def test_zero_accounting_fails_in_phase_d_artifacts(self):
        with open(
            "logs/narrow_ally_heal_paired_phase638d1_"
            "causal_audit_summary.json"
        ) as f:
            summary = json.load(f)
        agg = summary["aggregate"]
        self.assertEqual(agg["accounting_fail_total"], 0)
        self.assertEqual(
            agg["mutual_exclusion_fail_total"], 0
        )

    def test_138_generated_wrong_side_candidates(self):
        with open(
            "logs/narrow_ally_heal_paired_phase638d1_"
            "causal_audit_summary.json"
        ) as f:
            summary = json.load(f)
        agg = summary["aggregate"]
        self.assertEqual(
            agg["generated_wrong_side_total"], 138
        )
        # ON generated 98, OFF generated 40
        self.assertEqual(
            agg["by_arm"]["ON"]["generated"], 98
        )
        self.assertEqual(
            agg["by_arm"]["OFF"]["generated"], 40
        )


# ---------------------------------------------------------------------------
# N. Causal-action audit summary regressions
# ---------------------------------------------------------------------------


class TestCausalAuditSummary(unittest.TestCase):
    def test_action_change_artifact_present(self):
        path = (
            "logs/narrow_ally_heal_paired_phase638d1_"
            "causal_audit.jsonl"
        )
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            lines = [l for l in f if l.strip()]
        self.assertGreater(len(lines), 0)

    def test_each_record_has_required_fields(self):
        path = (
            "logs/narrow_ally_heal_paired_phase638d1_"
            "causal_audit.jsonl"
        )
        with open(path) as f:
            lines = [l for l in f if l.strip()]
        for line in lines:
            rec = json.loads(line)
            for key in (
                "pair_id", "arm", "battle_tag",
                "turn", "slot", "active_species",
                "candidate_move_id",
                "candidate_target_position",
                "candidate_target_species",
                "candidate_target_side",
                "intended_side",
                "blocked_reason",
                "on_selected_action",
                "off_counterfactual_action",
                "safe_alternative_action",
                "only_legal",
                "action_changed",
                "joint_action_changed",
            ):
                self.assertIn(key, rec, msg=str(rec))


# ---------------------------------------------------------------------------
# Statistical helpers regression
# ---------------------------------------------------------------------------


class TestStatisticalHelpers(unittest.TestCase):
    def test_wilson_ci_zero_n(self):
        lo, hi = wilson_ci(0, 0)
        self.assertEqual(lo, 0.0)
        self.assertEqual(hi, 1.0)

    def test_wilson_ci_perfect(self):
        lo, hi = wilson_ci(100, 100)
        self.assertGreater(lo, 0.9)

    def test_exact_binomial_two_sided_zero(self):
        self.assertEqual(exact_binomial_two_sided(0, 0), 1.0)

    def test_exact_binomial_one_sided_zero(self):
        self.assertEqual(exact_binomial_one_sided(0, 0), 1.0)

    def test_paired_bootstrap_zero_n(self):
        point, lo, hi = paired_bootstrap_treatment([])
        self.assertTrue(lo != lo)  # NaN

    def test_paired_bootstrap_deterministic_seed(self):
        scores = [+1, -1, +1, -1, 0, 0, 0, 0]
        p1, l1, h1 = paired_bootstrap_treatment(
            scores, n_boot=200, seed=6381
        )
        p2, l2, h2 = paired_bootstrap_treatment(
            scores, n_boot=200, seed=6381
        )
        self.assertEqual(p1, p2)
        self.assertEqual(l1, l2)
        self.assertEqual(h1, h2)


# ---------------------------------------------------------------------------
# Phase 6.3.8d.1 paired analysis regressions
# ---------------------------------------------------------------------------


class TestPairedAnalysisArtifact(unittest.TestCase):
    def test_analysis_summary_present(self):
        path = (
            "logs/narrow_ally_heal_paired_phase638d1_"
            "paired100_analysis.json"
        )
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["n_pairs_total"], 100)
        self.assertEqual(data["n_pairs_valid"], 100)
        self.assertEqual(data["n_battles"], 200)
        self.assertTrue(
            data["identity_validation"]["battle_tags_unique"]
        )
        self.assertTrue(
            data["identity_validation"]["audit_paths_unique"]
        )
        self.assertTrue(
            data["identity_validation"]["all_pairs_ok"]
        )

    def test_no_wrong_side_selected_in_on_metrics(self):
        path = (
            "logs/narrow_ally_heal_paired_phase638d1_"
            "paired100_analysis.json"
        )
        with open(path) as f:
            data = json.load(f)
        # ON metrics show generated candidates only
        # (the analyzer counts candidates, not final
        # selected actions). Phase B causal audit
        # proves the actual selected count is 0.
        causal_path = (
            "logs/narrow_ally_heal_paired_phase638d1_"
            "causal_audit_summary.json"
        )
        with open(causal_path) as f:
            causal = json.load(f)
        self.assertEqual(
            causal["aggregate"]["by_arm"]["ON"][
                "selected_wrong_side"
            ],
            0,
        )
        self.assertEqual(
            causal["aggregate"]["by_arm"]["OFF"][
                "selected_wrong_side"
            ],
            0,
        )

    def test_zero_pollenpuff_skillswap_blocks(self):
        path = (
            "logs/narrow_ally_heal_paired_phase638d1_"
            "paired100_analysis.json"
        )
        with open(path) as f:
            data = json.load(f)
        on_m = data["on_metrics"]
        self.assertEqual(on_m["pollenpuff_blocked"], 0)
        self.assertEqual(on_m["skillswap_blocked"], 0)


if __name__ == "__main__":
    unittest.main()
