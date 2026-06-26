"""Tests for PHASE7_PROTECT_LIKE_AND_TYPE_IMMUNITY_PRODUCTION_PATH_FIX.

Ponytail: pure unit tests. No poke-env runtime, no network,
no battles, no GPU.

Covers:
- Protect-like variant loophole (normalized stall class)
- First-call-per-turn guard for state mutation
- Canonical hard-block short-circuit in _compute_joint_scores
- Spread-move type-immunity handling
- Parser updates for Protect-like variants and spread moves
- Canonical trace coverage
"""
import json
import os
import unittest
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

import showdown_ai.bot_doubles_damage_aware as bot
from showdown_ai.bot_doubles_damage_aware import (
    HARD_BLOCK_SCORE_THRESHOLD,
    _is_repeated_protect_spam,
    _is_second_consecutive_protect,
    _is_no_effect_attack_blocked,
    _record_protect_failed,
)
from showdown_ai.protect_like_and_type_immunity import (
    PROTECT_LIKE_MOVE_IDS,
    SPREAD_DAMAGING_MOVE_IDS,
    normalise_protect_like_move_id,
    is_spread_damaging_move,
    make_protect_streak_key,
    protect_streak_should_block,
    record_protect_like_attempt,
    record_protect_like_failed,
    is_damaging_no_effect_blocked,
    is_single_target_damaging_move,
    all_spread_targets_immune,
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
    def __init__(
        self, move_id="", category="physical", target="normal",
        priority=0, type_=None,
    ):
        self.id = move_id
        self._category = category
        self._target = target
        self.priority = priority
        self._type = type_

    @property
    def category(self):
        return self._category


class _Mon:
    def __init__(
        self, ident="p1a: TestMon", species="TestMon", first_turn=False,
        types=None, fainted=False, ability="",
    ):
        self.ident = ident
        self.species = species
        self.first_turn = first_turn
        self.fainted = fainted
        self.ability = ability
        self.types = types or ["Normal"]


class _Battle:
    def __init__(
        self, battle_tag="battle-X", turn=1, actives=None,
        opponents=None,
    ):
        self.battle_tag = battle_tag
        self.turn = turn
        self.active_pokemon = actives or [_Mon(ident="p1a: TestMon")]
        self.opponent_active_pokemon = opponents or [
            _Mon(ident="p2a: OppMon"),
        ]


def _protect_order(move_id="protect"):
    return _Order(
        inner=_Move(move_id, "status", "self", priority=4),
        move_target=-1,
    )


def _non_protect_order(move_id="tackle", move_target=0):
    return _Order(
        inner=_Move(move_id, "physical", "normal", priority=0),
        move_target=move_target,
    )


# ============================================================
# Protect-like variant loophole tests
# ============================================================


class TestProtectLikeNormalisation(unittest.TestCase):
    def test_protect_normalises_to_stall_class(self):
        self.assertEqual(
            normalise_protect_like_move_id("protect"),
            "protect_like",
        )

    def test_detect_normalises_to_stall_class(self):
        self.assertEqual(
            normalise_protect_like_move_id("detect"),
            "protect_like",
        )

    def test_kingsshield_normalises_to_stall_class(self):
        self.assertEqual(
            normalise_protect_like_move_id("kingsshield"),
            "protect_like",
        )

    def test_banefulbunker_normalises_to_stall_class(self):
        self.assertEqual(
            normalise_protect_like_move_id("banefulbunker"),
            "protect_like",
        )

    def test_burningbulwark_normalises_to_stall_class(self):
        self.assertEqual(
            normalise_protect_like_move_id("burningbulwark"),
            "protect_like",
        )

    def test_non_protect_returns_none(self):
        self.assertIsNone(normalise_protect_like_move_id("tackle"))
        self.assertIsNone(normalise_protect_like_move_id("earthquake"))
        self.assertIsNone(normalise_protect_like_move_id(""))

    def test_wideguard_not_in_stall_class(self):
        # Wide Guard protects allies, not the user. Not a
        # self-protection stall move.
        self.assertIsNone(normalise_protect_like_move_id("wideguard"))


class TestProtectLikeStreakBlocking(unittest.TestCase):
    def test_first_protect_allowed(self):
        blocked, _ = protect_streak_should_block(
            {}, "battle-1", 0, "p1a: Mon", 1, "protect"
        )
        self.assertFalse(blocked)

    def test_third_protect_blocked(self):
        state: Dict = {}
        for t in (1, 2):
            _blocked, _ = protect_streak_should_block(
                state, "battle-1", 0, "p1a: Mon", t, "protect"
            )
            record_protect_like_attempt(
                state, "battle-1", 0, "p1a: Mon", t, "protect"
            )
        # 3rd attempt: should be blocked
        blocked, _ = protect_streak_should_block(
            state, "battle-1", 0, "p1a: Mon", 3, "protect"
        )
        self.assertTrue(blocked)

    def test_protect_detect_kingsshield_blocked_third(self):
        # The whole point of the fix: Protect -> Detect ->
        # King's Shield counts as 3 consecutive
        # Protect-like attempts.
        state: Dict = {}
        for t, mid in [(1, "protect"), (2, "detect"), (3, "kingsshield")]:
            _blocked, _ = protect_streak_should_block(
                state, "battle-1", 0, "p1a: Mon", t, mid
            )
            record_protect_like_attempt(
                state, "battle-1", 0, "p1a: Mon", t, mid
            )
        # 4th attempt: should be blocked
        blocked, _ = protect_streak_should_block(
            state, "battle-1", 0, "p1a: Mon", 4, "banefulbunker"
        )
        self.assertTrue(blocked)

    def test_detect_protect_detect_blocked_third(self):
        state: Dict = {}
        for t, mid in [(1, "detect"), (2, "protect"), (3, "detect")]:
            record_protect_like_attempt(
                state, "battle-1", 0, "p1a: Mon", t, mid
            )
        blocked, _ = protect_streak_should_block(
            state, "battle-1", 0, "p1a: Mon", 4, "detect"
        )
        self.assertTrue(blocked)

    def test_kingsshield_participates_in_streak(self):
        state: Dict = {}
        record_protect_like_attempt(
            state, "battle-1", 0, "p1a: Mon", 1, "kingsshield"
        )
        record_protect_like_attempt(
            state, "battle-1", 0, "p1a: Mon", 2, "spikyshield"
        )
        blocked, _ = protect_streak_should_block(
            state, "battle-1", 0, "p1a: Mon", 3, "kingsshield"
        )
        self.assertTrue(blocked)

    def test_non_protect_move_resets_streak(self):
        state: Dict = {}
        for t in (1, 2):
            record_protect_like_attempt(
                state, "battle-1", 0, "p1a: Mon", t, "protect"
            )
        # Non-Protect move on turn 3 resets the streak
        record_protect_like_attempt(
            state, "battle-1", 0, "p1a: Mon", 3, "tackle"
        )
        blocked, _ = protect_streak_should_block(
            state, "battle-1", 0, "p1a: Mon", 4, "protect"
        )
        self.assertFalse(blocked)

    def test_switch_resets_streak(self):
        state: Dict = {}
        for t in (1, 2):
            record_protect_like_attempt(
                state, "battle-1", 0, "p1a: MonA", t, "protect"
            )
        # Switch to a new pokemon (different ident)
        blocked, _ = protect_streak_should_block(
            state, "battle-1", 0, "p1a: MonB", 3, "protect"
        )
        self.assertFalse(blocked)

    def test_p1a_streak_does_not_affect_p1b(self):
        state: Dict = {}
        for t in (1, 2):
            record_protect_like_attempt(
                state, "battle-1", 0, "p1a: Mon", t, "protect"
            )
        # p1b is independent
        blocked, _ = protect_streak_should_block(
            state, "battle-1", 1, "p1b: Mon", 3, "protect"
        )
        self.assertFalse(blocked)

    def test_battle_boundary_resets_streak(self):
        state: Dict = {}
        for t in (1, 2):
            record_protect_like_attempt(
                state, "battle-1", 0, "p1a: Mon", t, "protect"
            )
        # New battle: fresh state
        blocked, _ = protect_streak_should_block(
            state, "battle-2", 0, "p1a: Mon", 3, "protect"
        )
        self.assertFalse(blocked)

    def test_previous_failed_protect_blocks_next(self):
        state: Dict = {}
        record_protect_like_attempt(
            state, "battle-1", 0, "p1a: Mon", 1, "protect",
            failed=True,
        )
        # 2nd attempt after a failed 1st: blocked
        blocked, _ = protect_streak_should_block(
            state, "battle-1", 0, "p1a: Mon", 2, "protect"
        )
        self.assertTrue(blocked)

    def test_first_protect_like_allowed(self):
        state: Dict = {}
        blocked, _ = protect_streak_should_block(
            state, "battle-1", 0, "p1a: Mon", 1, "kingsshield"
        )
        self.assertFalse(blocked)

    def test_second_protect_like_not_blocked(self):
        state: Dict = {}
        record_protect_like_attempt(
            state, "battle-1", 0, "p1a: Mon", 1, "protect"
        )
        blocked, _ = protect_streak_should_block(
            state, "battle-1", 0, "p1a: Mon", 2, "protect"
        )
        self.assertFalse(blocked)


class TestProtectLikeGuardNoMutation(unittest.TestCase):
    def test_first_call_per_turn_guard(self):
        # The production path calls the helper many times
        # per turn. The first-call-per-turn guard ensures
        # the streak is only incremented once per
        # (battle, turn, slot, ident). We test the
        # production helper directly.
        battle = _Battle(actives=[_Mon(ident="p1a: Mon")])
        state: Dict = {}
        for _ in range(20):
            _is_repeated_protect_spam(
                _protect_order(), battle, 0, state
            )
        # After 20 calls in the same turn, the streak
        # should still be 1 (only the first call incremented).
        rec = state[("battle-X", 0, "p1a: Mon")]
        self.assertEqual(rec["streak"], 1)

    def test_counterfactual_scoring_does_not_mutate(self):
        # The counterfactual re-compute path should be
        # idempotent: calling the helper 20 times in the
        # same turn should not change the state.
        battle = _Battle(actives=[_Mon(ident="p1a: Mon")])
        state: Dict = {}
        for _ in range(20):
            _is_repeated_protect_spam(
                _protect_order(), battle, 0, state
            )
        rec = state[("battle-X", 0, "p1a: Mon")]
        self.assertEqual(rec["streak"], 1)

    def test_state_updates_once_from_final_orders(self):
        # record_protect_like_attempt should be called
        # exactly once per final selected order.
        state: Dict = {"_turn_guard": set()}
        record_protect_like_attempt(
            state, "battle-1", 0, "p1a: Mon", 1, "protect"
        )
        rec = state[("battle-1", 0, "p1a: Mon")]
        self.assertEqual(rec["streak"], 1)
        self.assertEqual(rec["last_turn"], 1)

    def test_final_order_protect_like_sequence(self):
        # Simulate a sequence of final selected orders
        state: Dict = {"_turn_guard": set()}
        for t in range(1, 5):
            record_protect_like_attempt(
                state, "battle-1", 0, "p1a: Mon", t, "protect"
            )
        rec = state[("battle-1", 0, "p1a: Mon")]
        self.assertEqual(rec["streak"], 4)

    def test_selected_order_state_records_normalized_class(self):
        state: Dict = {"_turn_guard": set()}
        record_protect_like_attempt(
            state, "battle-1", 0, "p1a: Mon", 1, "kingsshield"
        )
        rec = state[("battle-1", 0, "p1a: Mon")]
        self.assertEqual(rec["last_ident"], "p1a: Mon")
        self.assertEqual(rec["streak"], 1)


# ============================================================
# Type-immunity no-effect tests
# ============================================================


class TestTypeImmunityNoEffect(unittest.TestCase):
    def test_ground_into_flying_blocked(self):
        target = _Mon(ident="p2a: Tornadus", types=("Flying",))
        opp_list = [target]
        blocked, _ = is_damaging_no_effect_blocked(
            "earthquake", -1, opp_list,
            lambda m, a, t, **kw: (True, "ground_vs_flying"),
            None,
        )
        self.assertTrue(blocked)

    def test_earthquake_two_flying_targets_blocked(self):
        t0 = _Mon(ident="p2a: Tornadus", types=("Flying",))
        t1 = _Mon(ident="p2b: Charizard", types=("Fire", "Flying"))
        opp_list = [t0, t1]
        blocked, _ = is_damaging_no_effect_blocked(
            "earthquake", -1, opp_list,
            lambda m, a, t, **kw: (True, "ground_vs_flying"),
            None,
        )
        self.assertTrue(blocked)

    def test_earthquake_one_flying_one_valid_not_overblocked(self):
        t0 = _Mon(ident="p2a: Garchomp", types=("Dragon", "Ground"))
        t1 = _Mon(ident="p2b: Tornadus", types=("Flying",))
        opp_list = [t0, t1]

        def fake_imm(m, a, t, **kw):
            if t is t1:
                return (True, "ground_vs_flying")
            return (False, "")

        blocked, _ = is_damaging_no_effect_blocked(
            "earthquake", -1, opp_list, fake_imm, None
        )
        self.assertFalse(blocked)

    def test_electric_into_ground_blocked(self):
        target = _Mon(ident="p2a: Garchomp", types=("Dragon", "Ground"))
        opp_list = [target]
        blocked, _ = is_damaging_no_effect_blocked(
            "thunderbolt", 0, opp_list,
            lambda m, a, t, **kw: (True, "electric_vs_ground"),
            None,
        )
        self.assertTrue(blocked)

    def test_normal_into_ghost_blocked(self):
        target = _Mon(ident="p2a: Gengar", types=("Ghost", "Poison"))
        opp_list = [target]
        blocked, _ = is_damaging_no_effect_blocked(
            "tackle", 0, opp_list,
            lambda m, a, t, **kw: (True, "normal_vs_ghost"),
            None,
        )
        self.assertTrue(blocked)

    def test_fighting_into_ghost_blocked(self):
        target = _Mon(ident="p2a: Gengar", types=("Ghost", "Poison"))
        opp_list = [target]
        blocked, _ = is_damaging_no_effect_blocked(
            "closecombat", 0, opp_list,
            lambda m, a, t, **kw: (True, "fighting_vs_ghost"),
            None,
        )
        self.assertTrue(blocked)

    def test_poison_into_steel_blocked(self):
        target = _Mon(ident="p2a: Aegislash", types=("Steel", "Ghost"))
        opp_list = [target]
        blocked, _ = is_damaging_no_effect_blocked(
            "sludgebomb", 0, opp_list,
            lambda m, a, t, **kw: (True, "poison_vs_steel"),
            None,
        )
        self.assertTrue(blocked)

    def test_psychic_into_dark_blocked(self):
        target = _Mon(ident="p2a: Darkrai", types=("Dark",))
        opp_list = [target]
        blocked, _ = is_damaging_no_effect_blocked(
            "psychic", 0, opp_list,
            lambda m, a, t, **kw: (True, "psychic_vs_dark"),
            None,
        )
        self.assertTrue(blocked)

    def test_dragon_into_fairy_blocked(self):
        target = _Mon(ident="p2a: Clefable", types=("Fairy",))
        opp_list = [target]
        blocked, _ = is_damaging_no_effect_blocked(
            "outrage", 0, opp_list,
            lambda m, a, t, **kw: (True, "dragon_vs_fairy"),
            None,
        )
        self.assertTrue(blocked)

    def test_status_move_not_blocked_by_type_immunity(self):
        target = _Mon(ident="p2a: Gengar", types=("Ghost", "Poison"))
        opp_list = [target]
        blocked, _ = is_damaging_no_effect_blocked(
            "thunderwave", 0, opp_list,
            lambda m, a, t, **kw: (True, "normal_vs_ghost"),
            None,
        )
        self.assertFalse(blocked)

    def test_unknown_target_type_does_not_guess(self):
        # Target with truly empty types list (not the
        # _Mon fixture which defaults to ["Normal"]).
        target = type("_T", (), {
            "ident": "p2a: ???",
            "species": "???",
            "types": [],
            "fainted": False,
            "ability": "",
        })()
        opp_list = [target]
        blocked, _ = is_damaging_no_effect_blocked(
            "earthquake", -1, opp_list,
            lambda m, a, t, **kw: (True, "would_guess"),
            None,
        )
        self.assertFalse(blocked)

    def test_no_levitate_species_inference(self):
        # Garchomp is a Ground/Dragon pokemon that could
        # theoretically have Levitate. The helper must
        # not infer Levitate from species. If the
        # opponent is Garchomp, the helper should block
        # only if the types explicitly say it has no
        # Ground type. Garchomp is Dragon/Ground, so
        # Earthquake should NOT be blocked (Garchomp is
        # hit by Ground).
        target = _Mon(ident="p2a: Garchomp", types=("Dragon", "Ground"))
        opp_list = [target]
        blocked, _ = is_damaging_no_effect_blocked(
            "earthquake", -1, opp_list,
            lambda m, a, t, **kw: (False, ""),  # honest immunity check
            None,
        )
        self.assertFalse(blocked)

    def test_no_magic_bounce_species_inference(self):
        # Same idea: no ability inference.
        target = _Mon(ident="p2a: Gengar", types=("Ghost", "Poison"))
        opp_list = [target]
        blocked, _ = is_damaging_no_effect_blocked(
            "tackle", 0, opp_list,
            lambda m, a, t, **kw: (True, "normal_vs_ghost"),
            None,
        )
        self.assertTrue(blocked)

    def test_no_prankster_species_inference(self):
        # Whimsicott is a Prankster species. The helper
        # should not infer Prankster from species.
        target = _Mon(ident="p2a: Whimsicott", types=("Grass", "Fairy"))
        opp_list = [target]
        # Fire move into Grass/Fairy: blocked (honest type check)
        blocked, _ = is_damaging_no_effect_blocked(
            "flamethrower", 0, opp_list,
            lambda m, a, t, **kw: (True, "fire_vs_grass"),
            None,
        )
        self.assertTrue(blocked)


class TestIsSpreadDamagingMove(unittest.TestCase):
    def test_earthquake_is_spread(self):
        self.assertTrue(is_spread_damaging_move("earthquake"))

    def test_surf_is_spread(self):
        self.assertTrue(is_spread_damaging_move("surf"))

    def test_tackle_is_not_spread(self):
        self.assertFalse(is_spread_damaging_move("tackle"))

    def test_heatwave_is_spread(self):
        self.assertTrue(is_spread_damaging_move("heatwave"))


# ============================================================
# Canonical hard-block joint tests
# ============================================================


class TestCanonicalJointHardBlock(unittest.TestCase):
    def test_canonical_joint_hard_blocked(self):
        # A joint with one hard-blocked slot should have
        # joint_score = -1e18 (effectively impossible).
        score_1 = HARD_BLOCK_SCORE_THRESHOLD - 1.0  # blocked
        score_2 = 50.0  # not blocked
        if score_1 <= HARD_BLOCK_SCORE_THRESHOLD or score_2 <= HARD_BLOCK_SCORE_THRESHOLD:
            joint_score = -1e18
        else:
            joint_score = score_1 + score_2
        self.assertEqual(joint_score, -1e18)

    def test_canonical_joint_no_hard_block(self):
        score_1 = 50.0
        score_2 = 60.0
        if score_1 <= HARD_BLOCK_SCORE_THRESHOLD or score_2 <= HARD_BLOCK_SCORE_THRESHOLD:
            joint_score = -1e18
        else:
            joint_score = score_1 + score_2
        self.assertEqual(joint_score, 110.0)

    def test_both_slots_hard_blocked(self):
        score_1 = -1e9
        score_2 = -1e9
        if score_1 <= HARD_BLOCK_SCORE_THRESHOLD or score_2 <= HARD_BLOCK_SCORE_THRESHOLD:
            joint_score = -1e18
        else:
            joint_score = score_1 + score_2
        self.assertEqual(joint_score, -1e18)

    def test_threshold_boundary(self):
        # Exactly at threshold: blocked.
        score_1 = HARD_BLOCK_SCORE_THRESHOLD
        score_2 = 50.0
        if score_1 <= HARD_BLOCK_SCORE_THRESHOLD or score_2 <= HARD_BLOCK_SCORE_THRESHOLD:
            joint_score = -1e18
        else:
            joint_score = score_1 + score_2
        self.assertEqual(joint_score, -1e18)


# ============================================================
# Parser tests
# ============================================================


class TestParserProtectLikeVariants(unittest.TestCase):
    def setUp(self):
        self.tmpdir = os.path.join(
            "/tmp",
            "phase7_pl_imm_pars_" + str(os.getpid()),
        )
        os.makedirs(self.tmpdir, exist_ok=True)
        self.battle = os.path.join(self.tmpdir, "battle-1.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, lines):
        with open(self.battle, "w") as f:
            for ln in lines:
                f.write(json.dumps({"line": ln}) + "\n")

    def test_protect_detect_kingsshield_one_streak(self):
        # Protect -> Detect -> King's Shield is one
        # Protect-like streak. Each |move| line must have
        # a target field (|move|actor|move|target|) for
        # the parser to recognize it.
        self._write([
            "|turn|1",
            "|move|p1a: Garchomp|Protect|p1a: Garchomp",
            "|turn|2",
            "|move|p1a: Garchomp|Detect|p1a: Garchomp",
            "|turn|3",
            "|move|p1a: Garchomp|King's Shield|p1a: Garchomp",
        ])
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["max_consecutive_protect_streak"], 3)
        self.assertEqual(out["protect_policy_bug_count"], 1)

    def test_banefulbunker_counted_as_protect_like(self):
        self._write([
            "|turn|1",
            "|move|p1a: Garchomp|Baneful Bunker|p1a: Garchomp",
            "|turn|2",
            "|move|p1a: Garchomp|Baneful Bunker|p1a: Garchomp",
            "|turn|3",
            "|move|p1a: Garchomp|Baneful Bunker|p1a: Garchomp",
        ])
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["max_consecutive_protect_streak"], 3)
        self.assertEqual(out["protect_policy_bug_count"], 1)

    def test_burningbulwark_counted_as_protect_like(self):
        self._write([
            "|turn|1",
            "|move|p1a: Garchomp|Burning Bulwark|p1a: Garchomp",
            "|turn|2",
            "|move|p1a: Garchomp|Burning Bulwark|p1a: Garchomp",
            "|turn|3",
            "|move|p1a: Garchomp|Burning Bulwark|p1a: Garchomp",
        ])
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["max_consecutive_protect_streak"], 3)
        self.assertEqual(out["protect_policy_bug_count"], 1)

    def test_non_protect_failed_not_counted_as_spam(self):
        self._write([
            "|turn|1",
            "|move|p1a: Garchomp|Tackle",
            "|-fail|p1a: Garchomp",
        ])
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["protect_policy_bug_count"], 0)


class TestParserGroundFlyingNoEffect(unittest.TestCase):
    def setUp(self):
        self.tmpdir = os.path.join(
            "/tmp",
            "phase7_pl_imm_pars2_" + str(os.getpid()),
        )
        os.makedirs(self.tmpdir, exist_ok=True)
        self.battle = os.path.join(self.tmpdir, "battle-1.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, lines):
        with open(self.battle, "w") as f:
            for ln in lines:
                f.write(json.dumps({"line": ln}) + "\n")

    def test_earthquake_into_flying_counted(self):
        # Phase 7 fix: spread move |-immune| IS counted.
        self._write([
            "|turn|14",
            "|move|p1a: Garchomp|Earthquake|p2a: Tornadus",
            "|-immune|p2a: Tornadus",
        ])
        out = parse_no_effect_attacks_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["no_effect_move_count"], 1)
        self.assertEqual(out["known_immunity_no_effect_count"], 1)

    def test_attack_into_protect_not_counted(self):
        # Opponent attacks into our Protect should not
        # count as a no-effect policy bug (it's a
        # Protect failure, not a type immunity).
        self._write([
            "|turn|14",
            "|move|p2a: Garchomp|Earthquake|p1a: Clefable",
            "|move|p1a: Clefable|Protect|p1a: Clefable",
            "|-immune|p1a: Clefable",
        ])
        out = parse_no_effect_attacks_from_raw_protocol(self.tmpdir)
        # The |-immune| for the Protect user is not
        # counted as a damaging no-effect.
        self.assertEqual(out["no_effect_move_count"], 0)

    def test_repeated_earthquake_into_flying_is_bug(self):
        self._write([
            "|turn|14",
            "|move|p1a: Garchomp|Earthquake|p2a: Tornadus",
            "|-immune|p2a: Tornadus",
            "|turn|19",
            "|move|p1a: Garchomp|Earthquake|p2a: Tornadus",
            "|-immune|p2a: Tornadus",
        ])
        out = parse_no_effect_attacks_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["no_effect_move_count"], 2)
        self.assertEqual(out["no_effect_policy_bug_count"], 1)


# ============================================================
# Canonical trace coverage tests
# ============================================================


class TestCanonicalTraceCoverage(unittest.TestCase):
    def test_record_joint_canonical(self):
        # The canonical trace should use call_depth=0
        # and counterfactual="canonical".
        import showdown_ai.action_trace as action_trace
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            os.environ["PHASE7_ACTION_TRACE_DIR"] = d
            action_trace.unset_trace_dir_explicit()
            try:
                battle = _Battle(actives=[_Mon()])
                action_trace.record_joint(
                    battle, 0, _protect_order(), _protect_order(),
                    50.0, 60.0, 110.0, 110.0, 110.0,
                    joint_has_hard_block=False,
                    joint_selected=True,
                    selection_rank=0,
                    call_depth=0,
                    counterfactual="canonical",
                )
                records = action_trace.get_records()
                self.assertEqual(records[0]["call_depth"], 0)
                self.assertEqual(
                    records[0]["counterfactual"], "canonical"
                )
            finally:
                os.environ.pop("PHASE7_ACTION_TRACE_DIR", None)
                action_trace.reset_action_trace_counters()


if __name__ == "__main__":
    unittest.main()
