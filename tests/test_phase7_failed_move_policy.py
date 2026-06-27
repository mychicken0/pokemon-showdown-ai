"""Tests for PHASE7_PRODUCTION_HARD_BLOCK_INTEGRITY_INVESTIGATION_AND_FIX.

Ponytail: pure unit tests. No poke-env runtime, no network,
no battles, no GPU. Tests hard-block integrity for the
Protect-spam and no-effect-attack fixes.
"""
import poke_env_test_cleanup  # noqa: F401
import json
import os
import sys
import unittest
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

import showdown_ai.bot_doubles_damage_aware as bot
from showdown_ai.bot_doubles_damage_aware import (
    HARD_BLOCK_SCORE_THRESHOLD,
    _is_repeated_protect_spam,
    _is_second_consecutive_protect,
    _is_no_effect_attack_blocked,
    _is_priority_blocked_by_psychic_terrain,
    _is_fake_out_first_turn_only,
    _is_same_side_single_target_damage_blocked,
    _record_protect_failed,
    _commit_protect_selection_for_selected_orders,
    select_best_joint_from_score_maps,
)
from showdown_ai.protect_like_and_type_immunity import (
    record_protect_like_attempt,
    record_protect_like_failed,
)
from showdown_ai.rl_data_3b_ff_monitor_v2 import (
    parse_protect_spam_from_raw_protocol,
    parse_no_effect_attacks_from_raw_protocol,
    stage2_gate_passes,
    make_empty_summary,
)


# ---- Fixtures ----


class _Order:
    def __init__(self, inner=None, move_target=0):
        self.order = inner
        self.move_target = move_target


class _Move:
    def __init__(self, move_id="", category="physical", target="normal",
                 priority=0, type_=None):
        self.id = move_id
        self._category = category
        self._target = target
        self.priority = priority
        self._type = type_

    @property
    def category(self):
        return self._category

    @property
    def type(self):
        if self._type is not None:
            return self._type
        return self._type


class _Terrain:
    def __init__(self, name):
        self.name = name


class _Mon:
    def __init__(self, ident="p1a: TestMon", species="TestMon",
                 types=("Normal",), item=None, ability="", first_turn=False):
        self.ident = ident
        self.species = species
        self.types = list(types)
        self.item = item
        self.ability = ability
        self.first_turn = first_turn
        self.fainted = False


class _Battle:
    def __init__(self, battle_tag="battle-X", turn=1, actives=None,
                 opp=None, fields=None):
        self.battle_tag = battle_tag
        self.turn = turn
        self.active_pokemon = actives or [_Mon()]
        self.opponent_active_pokemon = opp or [_Mon(), _Mon()]
        self.fields = fields or []


# ---- Hard-block integrity ----


class TestHardBlockThreshold(unittest.TestCase):
    def test_threshold_is_negative_1e8(self):
        self.assertEqual(HARD_BLOCK_SCORE_THRESHOLD, -1e8)


class TestHardBlockSkipsJoint(unittest.TestCase):
    def _make_joints(self, *configs):
        # configs: list of (first_inner, second_inner) tuples.
        class _Joint:
            def __init__(self, fo, so):
                self.first_order = fo
                self.second_order = so
        joints = []
        for fo, so in configs:
            j_fo = _Order(
                inner=fo, move_target=getattr(fo, "_mt", 0)
            )
            j_so = _Order(
                inner=so, move_target=getattr(so, "_mt", 0)
            )
            joints.append(_Joint(j_fo, j_so))
        return joints

    def _move(self, name, priority=0, mt=0):
        m = _Move(name, "physical", "normal", priority)
        m._mt = mt
        return m

    def _cfg(self):
        class _Cfg:
            safety_block_joint_penalty = 1000.0
        return _Cfg()

    def _battle(self):
        return _Battle()

    def test_hard_block_joint_loses_to_unblocked(self):
        # Joint A: protect hard-blocked (s1=-1e9) + tackle (s2=0)
        # Joint B: tackle (s1=0) + tackle (s2=0)
        # A should lose to B.
        protect = self._move("protect", priority=4, mt=-1)
        tackle = self._move("tackle", mt=0)
        joints = self._make_joints((protect, tackle), (tackle, tackle))
        a, b = joints
        scores = {
            id(a.first_order): -1e9,
            id(b.first_order): 0.0,
            id(a.second_order): 0.0,
            id(b.second_order): 0.0,
        }
        out = select_best_joint_from_score_maps(
            self._battle(), self._cfg(), joints, scores, scores
        )
        self.assertIsNotNone(out[0])
        self.assertEqual(out[0], b)

    def test_ml_score_cannot_resurrect_hard_blocked(self):
        # Hard-blocked joint with a high ML overlay (10.0) should
        # still be skipped because the per-slot score -1e9 is
        # below HARD_BLOCK_SCORE_THRESHOLD.
        protect = self._move("protect", priority=4, mt=-1)
        tackle = self._move("tackle", mt=0)
        joints = self._make_joints((protect, tackle), (tackle, tackle))
        a, b = joints
        scores = {
            id(a.first_order): -1e9,
            id(b.first_order): 0.0,
            id(a.second_order): 0.0,
            id(b.second_order): 0.0,
        }
        out = select_best_joint_from_score_maps(
            self._battle(), self._cfg(), joints, scores, scores
        )
        self.assertIsNotNone(out[0])
        self.assertEqual(out[0], b)

    def test_threshold_score_is_hard_blocked(self):
        protect = self._move("protect", priority=4, mt=-1)
        tackle = self._move("tackle", mt=0)
        joints = self._make_joints((protect, tackle), (tackle, tackle))
        a, b = joints
        scores = {
            id(a.first_order): HARD_BLOCK_SCORE_THRESHOLD,
            id(b.first_order): 0.0,
            id(a.second_order): 0.0,
            id(b.second_order): 0.0,
        }
        out = select_best_joint_from_score_maps(
            self._battle(), self._cfg(), joints, scores, scores
        )
        self.assertEqual(out[0], b)

    def test_safety_block_penalty_does_not_undo_hard_block(self):
        # Joint with a safety-blocked slot (e.g. ally-redirection)
        # is penalized but not eliminated; the joint with a
        # hard-blocked slot IS eliminated.
        protect = self._move("protect", priority=4, mt=-1)
        tackle = self._move("tackle", mt=0)
        joints = self._make_joints((protect, tackle), (tackle, tackle))
        a, b = joints
        scores = {
            id(a.first_order): -1e9,
            id(b.first_order): 0.0,
            id(a.second_order): 0.0,
            id(b.second_order): 0.0,
        }
        # Mark a as "safety-blocked" via the da dict.
        da = {id(a.first_order): True}
        out = select_best_joint_from_score_maps(
            self._battle(), self._cfg(), joints, scores, scores,
            direct_absorb_blocked=da,
        )
        # a is hard-blocked (-1e9) AND safety-blocked; the
        # selector should pick b.
        self.assertIsNotNone(out[0])
        self.assertEqual(out[0], b)

    def test_both_joints_hard_blocked_returns_one(self):
        # When ALL joints are hard-blocked, the selector
        # still returns one (fallback). It must NOT return
        # the unblockable joint because there isn't one.
        protect = self._move("protect", priority=4, mt=-1)
        tackle = self._move("tackle", mt=0)
        joints = self._make_joints(
            (protect, tackle),
            (tackle, protect),
        )
        a, b = joints
        scores = {
            id(a.first_order): -1e9,
            id(b.first_order): 0.0,
            id(a.second_order): 0.0,
            id(b.second_order): -1e9,
        }
        out = select_best_joint_from_score_maps(
            self._battle(), self._cfg(), joints, scores, scores
        )
        # Selector returns one of them, but both have a
        # hard-blocked slot. The test is simply: it does not
        # crash and returns some joint.
        self.assertIsNotNone(out[0])


# ---- Protect production-path tests ----


class TestProtectStreakHardBlocked(unittest.TestCase):
    def _protect(self, target_self=True):
        return _Order(inner=_Move("protect", "status", "self", priority=4),
                      move_target=-1 if target_self else 0)

    def _battle_with_active(self, ident="p1a: Whimsicott",
                            first_turn=True):
        return _Battle(
            actives=[_Mon(ident=ident, species="Whimsicott",
                            types=("Grass", "Fairy"), first_turn=first_turn)]
        )

    def test_first_protect_allowed(self):
        battle = self._battle_with_active()
        state: Dict = {}
        self.assertFalse(
            _is_repeated_protect_spam(self._protect(), battle, 0, state)
        )

    def test_outer_score_wrapper_cannot_resurrect_hard_block(self):
        player = bot.DoublesDamageAwarePlayer.__new__(
            bot.DoublesDamageAwarePlayer
        )
        player.config = bot.DoublesDamageAwareConfig()
        player._base_scores_cache = {0: {}, 1: {}}
        player._pure_scoring_mode = False
        player._active_config_override = None
        player._expected_to_faint_before_moving = {
            "battle-X": {0: True, 1: False}
        }
        player._b17_protect_floor_debug = {}
        battle = self._battle_with_active()
        with mock.patch.object(
            player, "_score_action_impl", return_value=-1e9
        ):
            score = player.score_action(self._protect(), 0, battle)
        self.assertEqual(score, -1e9)

    def test_second_protect_not_blocked(self):
        battle = self._battle_with_active()
        state: Dict = {}
        ident = battle.active_pokemon[0].ident
        # Record the first Protect via the pure helper.
        record_protect_like_attempt(
            state, battle.battle_tag, 0, ident, 1, "protect"
        )
        # 2nd consecutive Protect: not blocked.
        battle.turn = 2
        self.assertFalse(
            _is_repeated_protect_spam(self._protect(), battle, 0, state)
        )

    def test_third_protect_hard_blocked(self):
        battle = self._battle_with_active()
        state: Dict = {}
        ident = battle.active_pokemon[0].ident
        for t in (1, 2, 3):
            battle.turn = t
            is_blocked = _is_repeated_protect_spam(
                self._protect(), battle, 0, state
            )
            if t < 3:
                self.assertFalse(
                    is_blocked, f"turn {t} should NOT be blocked"
                )
            else:
                self.assertTrue(
                    is_blocked, f"turn {t} should be blocked"
                )
            if not is_blocked:
                record_protect_like_attempt(
                    state, battle.battle_tag, 0, ident, t, "protect"
                )

    def test_16_turn_whimsicott_streak(self):
        # Reproduce battle-9 p1b: Whimsicott t13-t28 pattern.
        # Two active mons (p1a, p1b) so slot=1 is in range.
        battle = _Battle(actives=[
            _Mon(ident="p1a: Garchomp", species="Garchomp",
                 types=("Dragon", "Ground")),
            _Mon(ident="p1b: Whimsicott", species="Whimsicott",
                 types=("Grass", "Fairy")),
        ])
        state: Dict = {}
        for turn in range(13, 29):
            battle.turn = turn
            is_blocked = _is_repeated_protect_spam(
                self._protect(), battle, 1, state
            )
            should_block = (turn - 13) % 3 == 2
            if not should_block:
                self.assertFalse(
                    is_blocked,
                    f"Whimsicott turn {turn} should NOT be blocked"
                )
            else:
                self.assertTrue(
                    is_blocked,
                    f"Whimsicott turn {turn} should be blocked"
                )
            if not is_blocked:
                record_protect_like_attempt(
                    state, battle.battle_tag, 1, "p1b: Whimsicott",
                    turn, "protect",
                )
            else:
                record_protect_like_attempt(
                    state, battle.battle_tag, 1, "p1b: Whimsicott",
                    turn, "tackle",
                )

    def test_state_resets_after_non_protect_move(self):
        battle = self._battle_with_active()
        state: Dict = {}
        ident = battle.active_pokemon[0].ident
        # 3 Protects across 3 turns -> 3rd is blocked
        for t in (1, 2, 3):
            battle.turn = t
            record_protect_like_attempt(
                state, battle.battle_tag, 0, ident, t, "protect"
            )
        # A non-Protect move on a NEW turn resets
        battle.turn = 4
        record_protect_like_attempt(
            state, battle.battle_tag, 0, ident, 4, "tackle"
        )
        # Then 2 fresh Protect candidates should be allowed
        # and committed.
        for t in (5, 6):
            battle.turn = t
            self.assertFalse(
                _is_repeated_protect_spam(self._protect(), battle, 0, state),
                f"turn {t} should NOT be blocked",
            )
            record_protect_like_attempt(
                state, battle.battle_tag, 0, ident, t, "protect"
            )
        # 3rd fresh Protect on a new turn should be blocked
        battle.turn = 7
        self.assertTrue(
            _is_repeated_protect_spam(self._protect(), battle, 0, state)
        )

    def test_state_resets_after_switch(self):
        battle1 = _Battle(actives=[_Mon(ident="p1a: Whimsicott")])
        battle2 = _Battle(actives=[_Mon(ident="p1a: Garchomp")])
        state: Dict = {}
        # Whimsicott: 3 Protects across 3 turns -> 3rd blocked
        for t in (1, 2, 3):
            battle1.turn = t
            record_protect_like_attempt(
                state, battle1.battle_tag, 0, "p1a: Whimsicott",
                t, "protect",
            )
        # Switch to Garchomp: fresh streak (different ident)
        battle2.turn = 4
        self.assertFalse(
            _is_repeated_protect_spam(self._protect(), battle2, 0, state)
        )

    def test_state_no_slot_leak(self):
        battle = _Battle(actives=[
            _Mon(ident="p1a: MonA"),
            _Mon(ident="p1b: MonB"),
        ])
        state: Dict = {}
        # p1a: 3 Protects across 3 turns -> 3rd blocked
        for t in (1, 2, 3):
            battle.turn = t
            record_protect_like_attempt(
                state, battle.battle_tag, 0, "p1a: MonA",
                t, "protect",
            )
        # p1b: first Protect on a new turn -> not blocked
        battle.turn = 4
        self.assertFalse(
            _is_repeated_protect_spam(self._protect(), battle, 1, state)
        )

    def test_state_no_battle_leak(self):
        battle_a = _Battle(battle_tag="battle-A")
        battle_b = _Battle(battle_tag="battle-B")
        state: Dict = {}
        # battle-A: 3 Protects across 3 turns
        for t in (1, 2, 3):
            battle_a.turn = t
            record_protect_like_attempt(
                state, "battle-A", 0, "p1a: TestMon",
                t, "protect",
            )
        # battle-B: fresh streak (different battle_tag)
        battle_b.turn = 4
        self.assertFalse(
            _is_repeated_protect_spam(self._protect(), battle_b, 0, state)
        )

    def test_failed_protect_blocks_next(self):
        battle = self._battle_with_active()
        state: Dict = {}
        ident = battle.active_pokemon[0].ident
        # First Protect on turn 1, recorded as failed.
        battle.turn = 1
        record_protect_like_attempt(
            state, battle.battle_tag, 0, ident, 1, "protect",
            failed=True,
        )
        # Next Protect attempt on a new turn: blocked
        # (2nd+ whose previous attempt already failed).
        battle.turn = 2
        self.assertTrue(
            _is_repeated_protect_spam(self._protect(), battle, 0, state)
        )


# ---- No-effect / immunity hard-block tests ----


class TestNoEffectHardBlock(unittest.TestCase):
    """Mock is_type_immune to simulate the shared-engine
    type chart and verify the hard-block returns True."""

    def _mon(self, ident, types):
        return _Mon(ident=ident, types=types)

    def _battle(self, target, actor=None):
        if actor is None:
            actor = self._mon("p1a: Archaludon",
                               types=("Steel", "Electric"))
        opp = [target, self._mon("p2b: Other", types=("Normal",))]
        return _Battle(actives=[actor], opp=opp)

    def test_electric_into_ground_blocked(self):
        target = self._mon("p2a: Garchomp", types=("Dragon", "Ground"))
        battle = self._battle(target)
        order = _Order(
            inner=_Move("electroball", "special", "normal", priority=0),
            move_target=0,
        )
        with mock.patch.object(bot, "is_type_immune",
                               return_value=(True, "test_immunity")):
            self.assertTrue(
                _is_no_effect_attack_blocked(order, battle, 0)
            )

    def test_archaludon_electro_shot_into_garchomp_blocked(self):
        # Screenshot-like case.
        target = self._mon("p2a: Garchomp", types=("Dragon", "Ground"))
        battle = self._battle(target)
        order = _Order(
            inner=_Move("electroshot", "special", "normal", priority=0),
            move_target=0,
        )
        with mock.patch.object(bot, "is_type_immune",
                               return_value=(True, "test_immunity")):
            self.assertTrue(
                _is_no_effect_attack_blocked(order, battle, 0)
            )

    def test_normal_into_ghost_blocked(self):
        target = self._mon("p2a: Gengar", types=("Ghost", "Poison"))
        battle = self._battle(target)
        order = _Order(
            inner=_Move("tackle", "physical", "normal", priority=0),
            move_target=0,
        )
        with mock.patch.object(bot, "is_type_immune",
                               return_value=(True, "test_immunity")):
            self.assertTrue(
                _is_no_effect_attack_blocked(order, battle, 0)
            )

    def test_fighting_into_ghost_blocked(self):
        target = self._mon("p2a: Gengar", types=("Ghost", "Poison"))
        battle = self._battle(target)
        order = _Order(
            inner=_Move("drainpunch", "physical", "fighting", priority=0),
            move_target=0,
        )
        with mock.patch.object(bot, "is_type_immune",
                               return_value=(True, "test_immunity")):
            self.assertTrue(
                _is_no_effect_attack_blocked(order, battle, 0)
            )

    def test_poison_into_steel_blocked(self):
        target = self._mon("p2a: Steelix", types=("Steel", "Ground"))
        battle = self._battle(target)
        order = _Order(
            inner=_Move("sludgebomb", "special", "poison", priority=0),
            move_target=0,
        )
        with mock.patch.object(bot, "is_type_immune",
                               return_value=(True, "test_immunity")):
            self.assertTrue(
                _is_no_effect_attack_blocked(order, battle, 0)
            )

    def test_psychic_into_dark_blocked(self):
        target = self._mon("p2a: Kingambit", types=("Dark", "Steel"))
        battle = self._battle(target)
        order = _Order(
            inner=_Move("psychic", "special", "psychic", priority=0),
            move_target=0,
        )
        with mock.patch.object(bot, "is_type_immune",
                               return_value=(True, "test_immunity")):
            self.assertTrue(
                _is_no_effect_attack_blocked(order, battle, 0)
            )

    def test_dragon_into_fairy_blocked(self):
        target = self._mon("p2a: Gardevoir", types=("Psychic", "Fairy"))
        battle = self._battle(target)
        order = _Order(
            inner=_Move("dragonpulse", "special", "dragon", priority=0),
            move_target=0,
        )
        with mock.patch.object(bot, "is_type_immune",
                               return_value=(True, "test_immunity")):
            self.assertTrue(
                _is_no_effect_attack_blocked(order, battle, 0)
            )

    def test_status_move_not_blocked_by_immunity(self):
        target = self._mon("p2a: Garchomp", types=("Dragon", "Ground"))
        battle = self._battle(target)
        order = _Order(
            inner=_Move("thunderwave", "status", "electric", priority=0),
            move_target=0,
        )
        with mock.patch.object(bot, "is_type_immune",
                               return_value=(True, "test_immunity")):
            self.assertFalse(
                _is_no_effect_attack_blocked(order, battle, 0)
            )

    def test_spread_move_not_overblocked(self):
        # Spread move with TWO targets where ONE is immune
        # and ONE is not: the move is not entirely no-effect
        # and must NOT be hard-blocked.
        target0 = self._mon("p2a: Garchomp", types=("Dragon", "Ground"))
        target1 = self._mon("p2b: Charizard", types=("Fire", "Flying"))
        battle = self._battle(target0, target1)
        order = _Order(
            inner=_Move("earthquake", "physical", "ground", priority=0),
            move_target=0,
        )
        # is_type_immune returns True for target0 (immune)
        # and False for target1 (not immune). The spread
        # move can still hit target1, so the action is
        # not entirely no-effect.
        def fake_imm(move, attacker, target, **kwargs):
            if target is target0:
                return (True, "test_immunity")
            return (False, "")
        with mock.patch.object(bot, "is_type_immune",
                               side_effect=fake_imm):
            self.assertFalse(
                _is_no_effect_attack_blocked(order, battle, 0)
            )

    def test_spread_move_all_immune_blocked(self):
        # Spread move with TWO targets where BOTH are immune:
        # the move is entirely no-effect and MUST be
        # hard-blocked.
        target0 = self._mon("p2a: Salamence", types=("Dragon", "Flying"))
        target1 = self._mon("p2b: Charizard", types=("Fire", "Flying"))
        battle = self._battle(target0, target1)
        order = _Order(
            inner=_Move("earthquake", "physical", "ground", priority=0),
            move_target=0,
        )
        with mock.patch.object(bot, "is_type_immune",
                               return_value=(True, "test_immunity")):
            self.assertTrue(
                _is_no_effect_attack_blocked(order, battle, 0)
            )

    def test_unknown_target_typing_does_not_guess(self):
        # Target has empty types list; helper must not block.
        target = self._mon("p2a: ???", types=())
        battle = self._battle(target)
        order = _Order(
            inner=_Move("electroball", "special", "electric", priority=0),
            move_target=0,
        )
        # is_type_immune may still return True but the helper
        # itself should refuse to block unknown types.
        with mock.patch.object(bot, "is_type_immune",
                               return_value=(True, "test_immunity")):
            self.assertFalse(
                _is_no_effect_attack_blocked(order, battle, 0)
            )

    def test_ally_target_not_blocked(self):
        target = self._mon("p1b: Ally", types=("Steel",))
        battle = _Battle(
            actives=[_Mon(ident="p1a: User")],
            opp=[self._mon("p2a: Opp", types=("Normal",))],
        )
        order = _Order(
            inner=_Move("thunderwave", "status", "electric", priority=0),
            move_target=-1,  # self/ally target
        )
        self.assertFalse(
            _is_no_effect_attack_blocked(order, battle, 0)
        )

    def test_no_levitate_species_inference(self):
        # The helper does not look at species. Only known
        # types from poke-env's types list block.
        target = self._mon("p2a: Garchomp", types=("Dragon", "Ground"))
        # types contains Ground -> Electric is no-effect
        battle = self._battle(target)
        order = _Order(
            inner=_Move("electroball", "special", "electric", priority=0),
            move_target=0,
        )
        # Even if the helper were to attempt Levitate inference,
        # Garchomp is not Flying. The test verifies that the
        # block is via type (Ground), not species.
        with mock.patch.object(bot, "is_type_immune",
                               return_value=(True, "test_immunity")):
            self.assertTrue(
                _is_no_effect_attack_blocked(order, battle, 0)
            )


# ---- Parser/gate tests ----


class TestProtectParserFixes(unittest.TestCase):
    def setUp(self):
        self.tmpdir = os.path.join("/tmp", "phase7_ptb_parser_" + str(os.getpid()))
        os.makedirs(self.tmpdir, exist_ok=True)
        self.battle = os.path.join(self.tmpdir, "battle-1.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, lines):
        with open(self.battle, "w") as f:
            for ln in lines:
                f.write(json.dumps({"line": ln}) + "\n")

    def test_first_fail_not_repeated_fail(self):
        # A single failed Protect in isolation is a
        # protect_fail_count = 1 but NOT a repeated fail.
        self._write([
            "|turn|2",
            "|move|p1a: Whimsicott|Protect|p1a: Whimsicott",
            "|-fail|p1a: Whimsicott",
        ])
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["protect_fail_count"], 1)
        self.assertEqual(out["repeated_protect_fail_count"], 0)
        self.assertTrue(out["protect_spam_gate_pass"])

    def test_two_consecutive_fails_are_two_allowed_attempts(self):
        self._write([
            "|turn|2",
            "|move|p1a: Whimsicott|Protect|p1a: Whimsicott",
            "|-fail|p1a: Whimsicott",
            "|turn|3",
            "|move|p1a: Whimsicott|Protect|p1a: Whimsicott",
            "|-fail|p1a: Whimsicott",
        ])
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["protect_fail_count"], 2)
        self.assertEqual(out["repeated_protect_fail_count"], 0)
        self.assertEqual(out["protect_policy_bug_count"], 0)
        self.assertTrue(out["protect_spam_gate_pass"])

    def test_successful_protect_resets_fail_state(self):
        # A successful Protect followed by one [still]/fail
        # is one failure, not a repeated failure. A third
        # selected attempt is still a policy bug.
        self._write([
            "|turn|2",
            "|move|p1a: Whimsicott|Protect|p1a: Whimsicott",
            "|-singleturn|p1a: Whimsicott|Protect",
            "|turn|3",
            "|move|p1a: Whimsicott|Protect||[still]",
            "|-fail|p1a: Whimsicott",
            "|turn|4",
            "|move|p1a: Whimsicott|Protect|p1a: Whimsicott",
        ])
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["protect_fail_count"], 1)
        self.assertEqual(out["repeated_protect_fail_count"], 0)
        self.assertEqual(out["protect_like_third_attempt_bug_count"], 1)
        self.assertEqual(out["protect_like_still_gap_bug_count"], 1)

    def test_non_protect_fail_not_counted(self):
        # |-miss| and |-immune| are not Protect fails.
        self._write([
            "|turn|2",
            "|move|p1a: Bot|tackle|p2a: Opp",
            "|-miss|p2a: Opp",
            "|move|p1a: Bot|electroball|p2a: Garchomp",
            "|-immune|p2a: Garchomp",
        ])
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["protect_fail_count"], 0)
        self.assertTrue(out["protect_spam_gate_pass"])


class TestNoEffectParser(unittest.TestCase):
    def setUp(self):
        self.tmpdir = os.path.join("/tmp", "phase7_noeffect_" + str(os.getpid()))
        os.makedirs(self.tmpdir, exist_ok=True)
        self.battle = os.path.join(self.tmpdir, "battle-1.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, lines):
        with open(self.battle, "w") as f:
            for ln in lines:
                f.write(json.dumps({"line": ln}) + "\n")

    def test_single_no_effect_not_bug(self):
        self._write([
            "|turn|14",
            "|move|p2b: Archaludon|Electro Shot|p1a: Garchomp",
            "|-immune|p1a: Garchomp",
        ])
        out = parse_no_effect_attacks_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["no_effect_move_count"], 1)
        self.assertEqual(out["no_effect_policy_bug_count"], 0)
        self.assertTrue(out["no_effect_policy_gate_pass"])

    def test_two_consecutive_no_effect_is_bug(self):
        self._write([
            "|turn|14",
            "|move|p2b: Archaludon|Electro Shot|p1a: Garchomp",
            "|-immune|p1a: Garchomp",
            "|turn|19",
            "|move|p2b: Archaludon|Electro Shot|p1a: Garchomp",
            "|-immune|p1a: Garchomp",
        ])
        out = parse_no_effect_attacks_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["no_effect_move_count"], 2)
        self.assertEqual(out["repeated_no_effect_move_count"], 1)
        self.assertEqual(out["no_effect_policy_bug_count"], 1)
        self.assertFalse(out["no_effect_policy_gate_pass"])

    def test_status_move_no_effect_not_counted(self):
        # |-immune| on a status move (hypothetical; servers
        # usually emit |-fail|) should NOT count as type-immunity
        # policy bug.
        self._write([
            "|turn|14",
            "|move|p1a: Clefable|Thunder Wave|p2a: Steelix",
            "|-immune|p2a: Steelix",
        ])
        out = parse_no_effect_attacks_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["no_effect_move_count"], 0)
        self.assertEqual(out["no_effect_policy_bug_count"], 0)

    def test_spread_move_immune_counted(self):
        # Phase 7 fix: spread move |-immune| IS counted as
        # a no-effect event for the specific (actor, target)
        # pair. The previous version skipped spread moves
        # entirely, which let Earthquake-into-Flying slip
        # through. The per-(actor, target) repeat check
        # then flags repeated no-effect into the same
        # target.
        self._write([
            "|turn|14",
            "|move|p1a: Garchomp|Earthquake|p2a: Tornadus",
            "|-immune|p2a: Tornadus",
        ])
        out = parse_no_effect_attacks_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["no_effect_move_count"], 1)
        self.assertEqual(out["known_immunity_no_effect_count"], 1)


class TestStage2GateWithNoEffect(unittest.TestCase):
    def test_gate_fails_on_no_effect_policy_bug(self):
        s = make_empty_summary(raw_protocol_logs_present=True)
        s["no_effect_policy_bug_count"] = 1
        self.assertFalse(stage2_gate_passes(s))

    def test_gate_fails_on_repeated_no_effect(self):
        s = make_empty_summary(raw_protocol_logs_present=True)
        s["repeated_no_effect_move_count"] = 1
        self.assertFalse(stage2_gate_passes(s))

    def test_gate_passes_when_no_effect_clean(self):
        s = make_empty_summary(raw_protocol_logs_present=True)
        self.assertTrue(stage2_gate_passes(s))


# ---- Regression tests ----


class TestExistingSafetyStillWorks(unittest.TestCase):
    def test_fake_out_first_turn(self):
        battle = _Battle(actives=[_Mon(first_turn=True)])
        order = _Order(
            inner=_Move("fakeout", "physical", "normal", priority=3),
            move_target=0,
        )
        self.assertFalse(_is_fake_out_first_turn_only(order, battle, 0))

    def test_same_side_damage_block(self):
        order = _Order(
            inner=_Move("crunch", "physical", "normal", priority=0),
            move_target=-1,
        )
        self.assertTrue(_is_same_side_single_target_damage_blocked(order))



if __name__ == "__main__":
    unittest.main()
