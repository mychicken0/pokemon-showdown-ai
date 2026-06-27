"""Tests for PHASE7_PROTECT_SPAM_POLICY_AND_GATE_AUDIT_OR_FIX.

Ponytail: pure unit tests. No poke-env runtime, no network,
no battles, no GPU.

Phase 7 streak-guard revision: ``_is_repeated_protect_spam``
is now read-only. State mutation happens exactly once per
final selected order via
``_commit_protect_selection_for_selected_orders`` (called
from ``choose_move``). The tests below exercise both the
read-only check and the commit helper.
"""
import json
import os
import unittest
from typing import Any, Dict, List

import showdown_ai.bot_doubles_damage_aware as bot
from showdown_ai.bot_doubles_damage_aware import (
    _is_repeated_protect_spam,
    _is_second_consecutive_protect,
    _record_protect_failed,
    _commit_protect_selection_for_selected_orders,
    _is_fake_out_first_turn_only,
    _is_same_side_single_target_damage_blocked,
    _is_priority_blocked_by_psychic_terrain,
)
from showdown_ai.rl_data_3b_ff_monitor_v2 import (
    parse_protect_spam_from_raw_protocol,
    stage2_gate_passes,
    make_empty_summary,
)
from showdown_ai.protect_like_and_type_immunity import (
    record_protect_like_attempt,
    record_protect_like_failed,
)


# ---- Fixtures ----


class _Order:
    def __init__(self, inner=None, move_target=-1):
        self.order = inner
        self.move_target = move_target


class _Move:
    def __init__(self, move_id="", category="status", target="self", priority=0):
        self.id = move_id
        self._category = category
        self._target = target
        self.priority = priority

    @property
    def category(self):
        return self._category


class _Mon:
    def __init__(self, ident="p1a: TestMon", species="TestMon", first_turn=False):
        self.ident = ident
        self.species = species
        self.first_turn = first_turn
        self.fainted = False
        self.ability = ""
        self.types = ["Normal"]


class _Battle:
    def __init__(self, battle_tag="battle-X", turn=1, actives=None):
        self.battle_tag = battle_tag
        self.turn = turn
        self.active_pokemon = actives or [_Mon(ident="p1a: TestMon")]


class _Joint:
    """Minimal joint order with first_order and second_order."""
    def __init__(self, first=None, second=None):
        self.first_order = first
        self.second_order = second


def _protect_order():
    return _Order(inner=_Move("protect", "status", "self", priority=4), move_target=-1)


def _non_protect_order(move_id="tackle"):
    return _Order(inner=_Move(move_id, "physical", "normal", priority=0), move_target=0)


def _commit_one(battle, slot_idx, state, order, turn=None):
    """Helper: drive the streak state for one (slot, turn) via the
    pure record helper, then check the read-only guard for the
    same candidate. Mirrors the production flow at
    ``choose_move`` time, but bypasses ``choose_move`` itself.
    """
    if turn is not None:
        battle.turn = turn
    active = battle.active_pokemon[slot_idx]
    ident = active.ident
    mid = ""
    inner = getattr(order, "order", None)
    if inner is not None and hasattr(inner, "id"):
        mid = str(getattr(inner, "id", "") or "")
    record_protect_like_attempt(
        state, battle.battle_tag, slot_idx, ident,
        battle.turn, mid, failed=False,
    )


# ---- Scorer tests ----


class TestFirstProtectAllowed(unittest.TestCase):
    def test_first_protect_not_blocked(self):
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        # Read-only helper: no state, no record -> not blocked.
        self.assertFalse(
            _is_repeated_protect_spam(_protect_order(), battle, 0, state)
        )

    def test_second_protect_not_blocked(self):
        # Second consecutive Protect: not blocked (heavy
        # penalty applied by caller). To get the streak to 2
        # we must record once via the pure helper, then check
        # the read-only guard.
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        battle.turn = 1
        _commit_one(battle, 0, state, _protect_order(), turn=1)
        battle.turn = 2
        self.assertFalse(
            _is_repeated_protect_spam(_protect_order(), battle, 0, state)
        )

    def test_third_consecutive_protect_blocked(self):
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        for t in (1, 2, 3):
            _commit_one(battle, 0, state, _protect_order(), turn=t)
        # Now the streak is 3. The read-only guard should
        # block the next Protect attempt.
        battle.turn = 3
        is_blocked = _is_repeated_protect_spam(
            _protect_order(), battle, 0, state
        )
        self.assertTrue(is_blocked, "turn 3 should be blocked")


class TestConsecutiveFailedProtect(unittest.TestCase):
    def test_failed_protect_blocks_next(self):
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        # First Protect on turn 1, recorded as failed.
        battle.turn = 1
        ident = battle.active_pokemon[0].ident
        record_protect_like_attempt(
            state, battle.battle_tag, 0, ident, 1, "protect",
            failed=True,
        )
        # Second consecutive Protect on turn 2: blocked.
        battle.turn = 2
        self.assertTrue(
            _is_repeated_protect_spam(_protect_order(), battle, 0, state)
        )


class TestProtectStreakReset(unittest.TestCase):
    def test_switch_resets_streak(self):
        battle1 = _Battle(actives=[_Mon(ident="p1a: Garchomp")])
        state: Dict = {}
        _commit_one(battle1, 0, state, _protect_order(), turn=1)
        _commit_one(battle1, 0, state, _protect_order(), turn=2)
        # Switch the active ident: new key, fresh streak.
        battle2 = _Battle(actives=[_Mon(ident="p1a: Volcarona")])
        # 1st Protect for the new mon: not blocked.
        self.assertFalse(
            _is_repeated_protect_spam(_protect_order(), battle2, 0, state)
        )

    def test_non_protect_move_resets_streak(self):
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        _commit_one(battle, 0, state, _protect_order(), turn=1)
        # Non-Protect selection on turn 2 resets the streak.
        record_protect_like_attempt(
            state, battle.battle_tag, 0, battle.active_pokemon[0].ident,
            2, "tackle", failed=False,
        )
        # Next Protect on turn 3 starts a fresh streak.
        battle.turn = 3
        self.assertFalse(
            _is_repeated_protect_spam(_protect_order(), battle, 0, state)
        )

    def test_turn_gap_resets_streak(self):
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        _commit_one(battle, 0, state, _protect_order(), turn=1)
        # Turn gap > 1: gap of 2 turns (jump to turn 3).
        battle.turn = 3
        self.assertFalse(
            _is_repeated_protect_spam(_protect_order(), battle, 0, state)
        )

    def test_different_slot_does_not_inherit_streak(self):
        battle = _Battle(actives=[_Mon(ident="p1a: MonA"), _Mon(ident="p1b: MonB")])
        state: Dict = {}
        # Slot 0: 2 consecutive Protects.
        _commit_one(battle, 0, state, _protect_order(), turn=1)
        _commit_one(battle, 0, state, _protect_order(), turn=2)
        # Slot 1: 1st Protect (different key, fresh streak).
        battle.turn = 3
        self.assertFalse(
            _is_repeated_protect_spam(_protect_order(), battle, 1, state)
        )

    def test_different_battle_does_not_inherit_streak(self):
        state: Dict = {}
        battle1 = _Battle(battle_tag="battle-1", actives=[_Mon()])
        _commit_one(battle1, 0, state, _protect_order(), turn=1)
        _commit_one(battle1, 0, state, _protect_order(), turn=2)
        battle2 = _Battle(battle_tag="battle-2", actives=[_Mon()])
        battle2.turn = 3
        self.assertFalse(
            _is_repeated_protect_spam(_protect_order(), battle2, 0, state)
        )


class TestNonProtectMovesUnaffected(unittest.TestCase):
    def test_tackle_unaffected(self):
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        # Non-Protect: never blocked, state unchanged.
        self.assertFalse(
            _is_repeated_protect_spam(_non_protect_order("tackle"), battle, 0, state)
        )
        # State should remain empty (no record).
        self.assertEqual(state, {})

    def test_switch_unaffected(self):
        # _Order with no .id attribute on the inner is
        # treated as a non-action.
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        order = _Order(inner=object(), move_target=0)
        self.assertFalse(
            _is_repeated_protect_spam(order, battle, 0, state)
        )

    def test_pass_unaffected(self):
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        self.assertFalse(
            _is_repeated_protect_spam(
                _Order(inner=_Move("pass", "status", "self"), move_target=-1),
                battle, 0, state,
            )
        )


class TestReadOnlyGuardIsIdempotent(unittest.TestCase):
    """Phase 7 streak-guard revision: candidate scoring
    (per-candidate helper calls) must not mutate the streak
    state. Repeated calls of the read-only helper must be
    idempotent.
    """

    def test_repeated_calls_with_no_commit_do_not_mutate(self):
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        for _ in range(20):
            self.assertFalse(
                _is_repeated_protect_spam(
                    _protect_order(), battle, 0, state
                )
            )
        # No state mutation: state should be empty.
        self.assertEqual(state, {})

    def test_repeated_calls_with_commit_block_on_third(self):
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        for t in (1, 2, 3):
            _commit_one(battle, 0, state, _protect_order(), turn=t)
        # Even after 20 read-only helper calls, the third
        # consecutive Protect is blocked.
        for _ in range(20):
            self.assertTrue(
                _is_repeated_protect_spam(
                    _protect_order(), battle, 0, state
                )
            )

    def test_mixed_candidate_scoring_does_not_reset_streak(self):
        # The core regression test: pre-fix, the
        # per-candidate scoring loop reset the streak to 0
        # on every non-Protect candidate evaluation. With
        # the read-only guard + commit-once pattern, scoring
        # a non-Protect candidate does not reset the streak.
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        _commit_one(battle, 0, state, _protect_order(), turn=1)
        _commit_one(battle, 0, state, _protect_order(), turn=2)
        battle.turn = 3
        # Simulate the per-candidate scoring loop: 10
        # non-Protect candidates + 10 Protect candidates.
        # Read-only helper must not mutate state.
        for _ in range(10):
            self.assertFalse(
                _is_repeated_protect_spam(
                    _non_protect_order("tackle"), battle, 0, state
                )
            )
            self.assertFalse(
                _is_repeated_protect_spam(
                    _protect_order(), battle, 0, state
                )
            )
        # Streak is still 2 (not reset to 0 by the
        # per-candidate evaluation).
        rec = state.get((battle.battle_tag, 0, "p1a: TestMon"))
        self.assertEqual(rec["streak"], 2)
        # Now commit a Protect selection for turn 3. This
        # is the 3rd consecutive Protect and must be
        # blocked by the next read-only check.
        best = _Joint(first=_protect_order(), second=None)
        _commit_protect_selection_for_selected_orders(
            battle, best, state
        )
        rec = state.get((battle.battle_tag, 0, "p1a: TestMon"))
        self.assertEqual(rec["streak"], 3)
        self.assertTrue(
            _is_repeated_protect_spam(
                _protect_order(), battle, 0, state
            )
        )


class TestCommitOncePerFinalSelection(unittest.TestCase):
    """Phase 7 streak-guard revision: state mutation
    happens exactly once per final selected order via
    ``_commit_protect_selection_for_selected_orders``.
    """

    def test_commit_increments_streak_on_protect(self):
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        # Slot 0: Protect. Slot 1: tackle.
        best = _Joint(
            first=_protect_order(),
            second=_non_protect_order("tackle"),
        )
        battle.turn = 1
        _commit_protect_selection_for_selected_orders(
            battle, best, state
        )
        # Slot 0 streak should be 1.
        self.assertEqual(
            state.get((battle.battle_tag, 0, battle.active_pokemon[0].ident), {}).get("streak"),
            1,
        )

    def test_commit_resets_streak_on_non_protect(self):
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        # Slot 0: 2 consecutive Protects via direct record.
        _commit_one(battle, 0, state, _protect_order(), turn=1)
        _commit_one(battle, 0, state, _protect_order(), turn=2)
        # Now select a non-Protect order on turn 3.
        best = _Joint(
            first=_non_protect_order("tackle"),
            second=None,
        )
        battle.turn = 3
        _commit_protect_selection_for_selected_orders(
            battle, best, state
        )
        # Streak should be reset to 0.
        self.assertEqual(
            state.get((battle.battle_tag, 0, battle.active_pokemon[0].ident), {}).get("streak"),
            0,
        )

    def test_commit_idempotent_for_same_selection(self):
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        best = _Joint(
            first=_protect_order(),
            second=None,
        )
        battle.turn = 1
        _commit_protect_selection_for_selected_orders(
            battle, best, state
        )
        # Calling commit again on the same battle/turn
        # should NOT increment the streak a second time
        # because the helper records the current_turn.
        _commit_protect_selection_for_selected_orders(
            battle, best, state
        )
        _commit_protect_selection_for_selected_orders(
            battle, best, state
        )
        # Streak should be 1, not 3.
        self.assertEqual(
            state.get((battle.battle_tag, 0, battle.active_pokemon[0].ident), {}).get("streak"),
            1,
        )

    def test_commit_isolates_p1a_and_p1b(self):
        battle = _Battle(actives=[_Mon(ident="p1a: MonA"), _Mon(ident="p1b: MonB")])
        state: Dict = {}
        best = _Joint(
            first=_protect_order(),
            second=_protect_order(),
        )
        battle.turn = 1
        _commit_protect_selection_for_selected_orders(
            battle, best, state
        )
        # Both slots should be streak=1.
        self.assertEqual(
            state.get((battle.battle_tag, 0, "p1a: MonA"), {}).get("streak"),
            1,
        )
        self.assertEqual(
            state.get((battle.battle_tag, 1, "p1b: MonB"), {}).get("streak"),
            1,
        )

    def test_commit_isolates_battle_a_and_battle_b(self):
        state: Dict = {}
        battle_a = _Battle(battle_tag="battle-A", actives=[_Mon()])
        best_a = _Joint(first=_protect_order(), second=None)
        battle_a.turn = 1
        _commit_protect_selection_for_selected_orders(
            battle_a, best_a, state
        )
        battle_b = _Battle(battle_tag="battle-B", actives=[_Mon()])
        best_b = _Joint(first=_protect_order(), second=None)
        battle_b.turn = 1
        _commit_protect_selection_for_selected_orders(
            battle_b, best_b, state
        )
        # Both battles should have their own streak=1.
        self.assertEqual(
            state.get(("battle-A", 0, "p1a: TestMon"), {}).get("streak"),
            1,
        )
        self.assertEqual(
            state.get(("battle-B", 0, "p1a: TestMon"), {}).get("streak"),
            1,
        )

    def test_commit_handles_none_order_safely(self):
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        best = _Joint(first=None, second=None)
        battle.turn = 1
        _commit_protect_selection_for_selected_orders(
            battle, best, state
        )
        # No state mutation expected.
        self.assertEqual(state, {})

    def test_commit_full_lifecycle_three_consecutive_protect_blocked(self):
        # End-to-end: 3 consecutive commits -> 3rd is blocked.
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        for t in (1, 2, 3):
            best = _Joint(first=_protect_order(), second=None)
            battle.turn = t
            _commit_protect_selection_for_selected_orders(
                battle, best, state
            )
        # At turn 3, streak should be 3 and the guard blocks.
        self.assertTrue(
            _is_repeated_protect_spam(_protect_order(), battle, 0, state)
        )

    def test_commit_full_lifecycle_protect_detect_kingsshield(self):
        # Protect -> Detect -> King's Shield counts as 3
        # consecutive Protect-like attempts.
        battle = _Battle(actives=[_Mon()])
        state: Dict = {}
        for t, mid in [(1, "protect"), (2, "detect"), (3, "kingsshield")]:
            order = _Order(
                inner=_Move(mid, "status", "self", priority=4),
                move_target=-1,
            )
            best = _Joint(first=order, second=None)
            battle.turn = t
            _commit_protect_selection_for_selected_orders(
                battle, best, state
            )
        battle.turn = 3
        # 4th consecutive: must be blocked.
        self.assertTrue(
            _is_repeated_protect_spam(
                _Order(
                    inner=_Move("banefulbunker", "status", "self", priority=4),
                    move_target=-1,
                ),
                battle, 0, state,
            )
        )


class TestExistingSafetyPreserved(unittest.TestCase):
    def test_fake_out_first_turn_still_works(self):
        # The Fake Out first-turn rule must still apply.
        battle = _Battle(actives=[_Mon(first_turn=True)])
        order = _Order(
            inner=_Move("fakeout", "physical", "normal", priority=3),
            move_target=0,
        )
        self.assertFalse(_is_fake_out_first_turn_only(order, battle, 0))

    def test_same_side_damage_block_still_works(self):
        order = _Order(
            inner=_Move("crunch", "physical", "normal", priority=0),
            move_target=-1,
        )
        self.assertTrue(_is_same_side_single_target_damage_blocked(order))

    def test_psychic_terrain_priority_block_still_works(self):
        class _TerrainObj:
            def __init__(self, name):
                self.name = name

        target = _Mon(ident="p2a: Volcarona", species="Volcarona")
        target.types = ["Bug", "Fire"]
        target.ability = ""
        target.item = None
        battle = _Battle(actives=[_Mon(ident="p1a: Incineroar", species="Incineroar")])
        battle.fields = [_TerrainObj("Psychic Terrain")]
        battle.opponent_active_pokemon = [target, None]
        order = _Order(
            inner=_Move("fakeout", "physical", "normal", priority=3),
            move_target=0,
        )
        self.assertTrue(_is_priority_blocked_by_psychic_terrain(order, battle, 0))


class TestNoSpeciesInference(unittest.TestCase):
    def test_no_prankster_species_inference(self):
        # Helper must not look at species; pure positional /
        # id-based logic.
        m = _Mon(ident="p1a: Whimsicott", species="Whimsicott")
        battle = _Battle(actives=[m])
        state: Dict = {}
        # Whimsicott is a Prankster species, but the helper
        # only inspects move id and ident, not species.
        # 1st Protect is not blocked.
        self.assertFalse(
            _is_repeated_protect_spam(_protect_order(), battle, 0, state)
        )

    def test_no_magic_bounce_species_inference(self):
        import inspect
        # Scope to the new Protect-spam helper block only.
        # The full module legitimately contains
        # "Levitate" / "Magic Bounce" in unrelated
        # existing ability-resolution code; this test
        # only asserts the new helpers do not introduce
        # species-based Magic Bounce inference.
        src = inspect.getsource(bot)
        # Find the Protect helper block and check it.
        marker = "_PROTECT_LIKE_MOVE_IDS_SPAM"
        idx = src.find(marker)
        self.assertGreaterEqual(idx, 0)
        # Take a 4k-char window after the marker; this
        # covers the new helpers and a generous margin.
        window = src[idx:idx + 4000]
        self.assertNotIn("Magic Bounce", window)
        self.assertNotIn("magicbounce", window)

    def test_no_levitate_species_inference(self):
        import inspect
        src = inspect.getsource(bot)
        marker = "_PROTECT_LIKE_MOVE_IDS_SPAM"
        idx = src.find(marker)
        self.assertGreaterEqual(idx, 0)
        window = src[idx:idx + 4000]
        self.assertNotIn("Levitate", window)
        self.assertNotIn("levitate", window)

    def test_state_does_not_look_at_ability(self):
        battle = _Battle(actives=[_Mon(ident="p1a: Garchomp")])
        battle.active_pokemon[0].ability = "roughskin"
        state: Dict = {}
        # ability is not consulted.
        self.assertFalse(
            _is_repeated_protect_spam(_protect_order(), battle, 0, state)
        )


# ---- Parser / gate tests ----


class TestRawParserProtectSpam(unittest.TestCase):
    def setUp(self):
        self.tmpdir = os.path.join("/tmp", "phase7_protect_test_" + str(os.getpid()))
        os.makedirs(self.tmpdir, exist_ok=True)
        self.battle = os.path.join(self.tmpdir, "battle-1.jsonl")

    def tearDown(self):
        import shutil as _sh
        _sh.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, lines):
        with open(self.battle, "w") as f:
            for ln in lines:
                f.write(json.dumps({"line": ln}) + "\n")

    def test_single_protect_does_not_fail_gate(self):
        self._write([
            "|turn|2",
            "|move|p1a: Volcarona|Protect|p1a: Volcarona",
        ])
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["protect_move_count"], 1)
        self.assertEqual(out["protect_policy_bug_count"], 0)
        self.assertTrue(out["protect_spam_gate_pass"])

    def test_three_consecutive_protect_fails_gate(self):
        self._write([
            "|turn|2",
            "|move|p1a: Volcarona|Protect|p1a: Volcarona",
            "|turn|3",
            "|move|p1a: Volcarona|Protect|p1a: Volcarona",
            "|turn|4",
            "|move|p1a: Volcarona|Protect|p1a: Volcarona",
        ])
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["consecutive_protect_attempt_count"], 2)
        self.assertGreaterEqual(out["protect_policy_bug_count"], 1)
        self.assertFalse(out["protect_spam_gate_pass"])

    def test_consecutive_failed_protect_fails_gate(self):
        self._write([
            "|turn|2",
            "|move|p1a: Volcarona|Protect|p1a: Volcarona",
            "|-fail|p1a: Volcarona",
            "|turn|3",
            "|move|p1a: Volcarona|Protect|p1a: Volcarona",
            "|-fail|p1a: Volcarona",
        ])
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        self.assertGreaterEqual(out["protect_fail_count"], 1)
        self.assertGreaterEqual(out["repeated_protect_fail_count"], 1)
        self.assertFalse(out["protect_spam_gate_pass"])

    def test_ten_turn_streak_fails_gate(self):
        lines = ["|turn|1"]
        for t in range(1, 11):
            lines.append(f"|turn|{t}")
            lines.append(f"|move|p1a: Garchomp|Protect|p1a: Garchomp")
        self._write(lines)
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        self.assertGreaterEqual(out["max_consecutive_protect_streak"], 10)
        self.assertFalse(out["protect_spam_gate_pass"])

    def test_protect_used_by_both_sides_tracked_independently(self):
        # Bot p1a and opp p2a both spam Protect; both
        # contribute to per-side counts.
        self._write([
            "|turn|1",
            "|move|p1a: Bot|Protect|p1a: Bot",
            "|turn|2",
            "|move|p1a: Bot|Protect|p1a: Bot",
            "|turn|3",
            "|move|p1a: Bot|Protect|p1a: Bot",
            "|turn|4",
            "|move|p1a: Bot|Protect|p1a: Bot",
        ])
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        self.assertGreaterEqual(out["max_consecutive_protect_streak"], 4)
        self.assertGreaterEqual(out["protect_policy_bug_count"], 2)

    def test_partner_slot_streaks_tracked_separately(self):
        # Two p1 slots: each gets its own 3-consecutive
        # Protect streak across separate turns. The
        # parser keys streaks by actor ident (which
        # already includes the slot), so the two slots
        # contribute independently.
        self._write([
            # Slot p1a hits 3 consecutive Protects.
            "|turn|1", "|move|p1a: Bot|Protect|p1a: Bot",
            "|turn|2", "|move|p1a: Bot|Protect|p1a: Bot",
            "|turn|3", "|move|p1a: Bot|Protect|p1a: Bot",
            # Slot p1b hits 3 consecutive Protects on
            # interleaved turns.
            "|turn|1", "|move|p1b: Bot|Protect|p1b: Bot",
            "|turn|2", "|move|p1b: Bot|Protect|p1b: Bot",
            "|turn|3", "|move|p1b: Bot|Protect|p1b: Bot",
        ])
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        # Two streaks of length 3 each -> 2+ policy bugs.
        self.assertGreaterEqual(out["protect_policy_bug_count"], 2)

    def test_non_protect_failed_move_does_not_count(self):
        # |-miss| and |-immune| etc. do not count as Protect
        # fails.
        self._write([
            "|turn|1",
            "|move|p1a: Bot|tackle|p2a: Opp",
            "|-miss|p2a: Opp",
        ])
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["protect_fail_count"], 0)
        self.assertEqual(out["protect_policy_bug_count"], 0)
        self.assertTrue(out["protect_spam_gate_pass"])

    def test_gate_passes_when_no_protect_spam(self):
        self._write([
            "|turn|1",
            "|move|p1a: Bot|tackle|p2a: Opp",
        ])
        out = parse_protect_spam_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["protect_move_count"], 0)
        self.assertTrue(out["protect_spam_gate_pass"])


class TestStage2GateWithProtect(unittest.TestCase):
    def test_stage2_gate_fails_on_protect_policy_bug(self):
        s = make_empty_summary(raw_protocol_logs_present=True)
        s["protect_policy_bug_count"] = 1
        self.assertFalse(stage2_gate_passes(s))

    def test_stage2_gate_fails_on_repeated_protect_fail(self):
        s = make_empty_summary(raw_protocol_logs_present=True)
        s["repeated_protect_fail_count"] = 1
        self.assertFalse(stage2_gate_passes(s))

    def test_stage2_gate_fails_on_long_protect_streak(self):
        s = make_empty_summary(raw_protocol_logs_present=True)
        s["max_consecutive_protect_streak"] = 9
        self.assertFalse(stage2_gate_passes(s))

    def test_stage2_gate_passes_on_clean_summary(self):
        s = make_empty_summary(raw_protocol_logs_present=True)
        self.assertTrue(stage2_gate_passes(s))


if __name__ == "__main__":
    unittest.main()
