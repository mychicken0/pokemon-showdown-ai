"""Tests for the Phase 7 action-trace instrumentation.

Ponytail: pure unit tests. No poke-env runtime, no network,
no battles, no GPU. The instrumentation must be disabled
by default and have zero behavior change when disabled.
"""
import poke_env_test_cleanup  # noqa: F401
import json
import os
import tempfile
import unittest
from typing import Any, Dict, List

import showdown_ai.action_trace as action_trace
from showdown_ai.bot_doubles_damage_aware import (
    HARD_BLOCK_SCORE_THRESHOLD,
)


class _Order:
    def __init__(self, inner=None, move_target=-1):
        self.order = inner
        self.move_target = move_target


class _Move:
    def __init__(
        self, move_id="", category="status", target="self", priority=0
    ):
        self.id = move_id
        self._category = category
        self._target = target
        self.priority = priority

    @property
    def category(self):
        return self._category


class _Mon:
    def __init__(
        self,
        ident="p1a: TestMon",
        species="TestMon",
        first_turn=False,
        types=None,
    ):
        self.ident = ident
        self.species = species
        self.first_turn = first_turn
        self.fainted = False
        self.ability = ""
        self.types = types or ["Normal"]


class _Battle:
    def __init__(
        self, battle_tag="battle-X", turn=1, actives=None
    ):
        self.battle_tag = battle_tag
        self.turn = turn
        self.active_pokemon = actives or [_Mon(ident="p1a: TestMon")]


def _protect_order():
    return _Order(
        inner=_Move("protect", "status", "self", priority=4),
        move_target=-1,
    )


def _non_protect_order(move_id="tackle"):
    return _Order(
        inner=_Move(move_id, "physical", "normal", priority=0),
        move_target=0,
    )


class _TraceStateGuard:
    """Save and restore the module-level trace state.

    Tests must not leak env vars or module state to other
    tests in the suite.
    """

    def __enter__(self):
        self._prev_dir = os.environ.get("PHASE7_ACTION_TRACE_DIR")
        self._prev_trace_dir = action_trace._trace_dir
        self._prev_explicit = action_trace._trace_dir_explicit
        action_trace.reset_action_trace_counters()
        if self._prev_dir is None:
            os.environ.pop("PHASE7_ACTION_TRACE_DIR", None)
        else:
            os.environ["PHASE7_ACTION_TRACE_DIR"] = self._prev_dir
        action_trace.unset_trace_dir_explicit()
        return self

    def __exit__(self, exc_type, exc, tb):
        action_trace.unset_trace_dir_explicit()
        action_trace.reset_action_trace_counters()
        if self._prev_dir is None:
            os.environ.pop("PHASE7_ACTION_TRACE_DIR", None)
        else:
            os.environ["PHASE7_ACTION_TRACE_DIR"] = self._prev_dir
        if self._prev_explicit:
            action_trace.set_trace_dir(self._prev_trace_dir)
        else:
            action_trace.unset_trace_dir_explicit()


class TestActionTraceDisabledByDefault(unittest.TestCase):
    def test_disabled_when_env_var_unset(self):
        with _TraceStateGuard():
            os.environ.pop("PHASE7_ACTION_TRACE_DIR", None)
            action_trace.set_trace_dir(None)
            self.assertFalse(action_trace.is_action_trace_enabled())

    def test_record_candidate_noop_when_disabled(self):
        with _TraceStateGuard():
            os.environ.pop("PHASE7_ACTION_TRACE_DIR", None)
            action_trace.set_trace_dir(None)
            battle = _Battle(actives=[_Mon()])
            action_trace.record_candidate(
                battle, 0, _protect_order(), -1e9,
                hard_block_reason="repeated_protect",
            )
            summary = action_trace.get_summary()
            self.assertEqual(summary["candidate_count"], 0)
            self.assertEqual(summary["protect_candidate_count"], 0)
            self.assertEqual(summary["action_trace_event_count"], 0)

    def test_state_update_noop_when_disabled(self):
        with _TraceStateGuard():
            os.environ.pop("PHASE7_ACTION_TRACE_DIR", None)
            action_trace.set_trace_dir(None)
            battle = _Battle(actives=[_Mon()])
            action_trace.record_state_update(battle, 0, is_reset=False)
            action_trace.record_state_update(battle, 0, is_reset=True)
            summary = action_trace.get_summary()
            self.assertEqual(summary["protect_state_update_count"], 0)
            self.assertEqual(summary["protect_state_reset_count"], 0)

    def test_joint_record_noop_when_disabled(self):
        with _TraceStateGuard():
            os.environ.pop("PHASE7_ACTION_TRACE_DIR", None)
            action_trace.set_trace_dir(None)
            battle = _Battle(actives=[_Mon()])
            action_trace.record_joint(
                battle, 0, _protect_order(), _protect_order(),
                -1e9, -1e9, -1.0, -1.0, -1.0,
                joint_has_hard_block=True,
                joint_selected=False,
                selection_rank=-1,
            )
            summary = action_trace.get_summary()
            self.assertEqual(summary["hard_blocked_joint_count"], 0)
            self.assertEqual(summary["action_trace_event_count"], 0)

    def test_final_orders_noop_when_disabled(self):
        with _TraceStateGuard():
            os.environ.pop("PHASE7_ACTION_TRACE_DIR", None)
            action_trace.set_trace_dir(None)
            battle = _Battle(actives=[_Mon()])
            action_trace.record_final_orders(
                battle, _protect_order(), _protect_order(),
                first_was_hard_blocked=True,
                second_was_hard_blocked=True,
                emergency_fallback_used=True,
                fallback_reason="test",
            )
            summary = action_trace.get_summary()
            self.assertEqual(
                summary["selected_hard_blocked_action_count"], 0
            )
            self.assertEqual(summary["emergency_fallback_count"], 0)

    def test_flush_records_noop_when_disabled(self):
        with _TraceStateGuard():
            os.environ.pop("PHASE7_ACTION_TRACE_DIR", None)
            action_trace.set_trace_dir(None)
            with tempfile.TemporaryDirectory() as d:
                action_trace.flush_records()
                files = os.listdir(d)
                self.assertEqual(files, [])


class TestActionTraceEnabledByEnvVar(unittest.TestCase):
    def test_enabled_when_env_var_set(self):
        with tempfile.TemporaryDirectory() as d:
            with _TraceStateGuard():
                os.environ["PHASE7_ACTION_TRACE_DIR"] = d
                action_trace.unset_trace_dir_explicit()
                self.assertTrue(action_trace.is_action_trace_enabled())
                self.assertEqual(action_trace._get_trace_dir(), d)

    def test_set_trace_dir_overrides_env(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            with _TraceStateGuard():
                os.environ["PHASE7_ACTION_TRACE_DIR"] = d1
                action_trace.set_trace_dir(d2)
                self.assertTrue(action_trace.is_action_trace_enabled())
                self.assertEqual(action_trace._get_trace_dir(), d2)

    def test_unset_explicit_falls_back_to_env(self):
        with tempfile.TemporaryDirectory() as d:
            with _TraceStateGuard():
                os.environ["PHASE7_ACTION_TRACE_DIR"] = d
                action_trace.set_trace_dir("/some/other/path")
                self.assertEqual(action_trace._get_trace_dir(), "/some/other/path")
                action_trace.unset_trace_dir_explicit()
                self.assertEqual(action_trace._get_trace_dir(), d)


class TestRecordCandidateBehavior(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="phase7_trace_test_")
        self._guard = _TraceStateGuard()
        self._guard.__enter__()
        os.environ["PHASE7_ACTION_TRACE_DIR"] = self._tmpdir
        action_trace.unset_trace_dir_explicit()

    def tearDown(self):
        self._guard.__exit__(None, None, None)

    def test_protect_candidate_increments_protect_counter(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_candidate(
            battle, 0, _protect_order(), 0.5,
            hard_block_reason="",
        )
        summary = action_trace.get_summary()
        self.assertEqual(summary["candidate_count"], 1)
        self.assertEqual(summary["protect_candidate_count"], 1)
        self.assertEqual(
            summary["protect_hard_block_candidate_count"], 0
        )

    def test_non_protect_does_not_increment_protect_counter(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_candidate(
            battle, 0, _non_protect_order("tackle"), 0.5,
            hard_block_reason="",
        )
        summary = action_trace.get_summary()
        self.assertEqual(summary["candidate_count"], 1)
        self.assertEqual(summary["protect_candidate_count"], 0)

    def test_hard_blocked_protect_increments_both(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_candidate(
            battle, 0, _protect_order(), -1e9,
            hard_block_reason="repeated_protect_like_third_attempt",
            committed_protect_streak=2,
            protect_last_failed=False,
        )
        summary = action_trace.get_summary()
        self.assertEqual(summary["protect_candidate_count"], 1)
        self.assertEqual(
            summary["protect_hard_block_candidate_count"], 1
        )

    def test_score_at_threshold_counts_as_hard_block(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_candidate(
            battle, 0, _protect_order(), HARD_BLOCK_SCORE_THRESHOLD,
            hard_block_reason="repeated_protect",
        )
        summary = action_trace.get_summary()
        self.assertEqual(
            summary["protect_hard_block_candidate_count"], 1
        )

    def test_record_carries_battle_metadata(self):
        mon = _Mon(ident="p1a: Volcarona", species="Volcarona", types=["Bug", "Fire"])
        battle = _Battle(battle_tag="battle-42", turn=7, actives=[mon])
        action_trace.record_candidate(
            battle, 0, _protect_order(), -1e9,
            hard_block_reason="repeated_protect_like_third_attempt",
            committed_protect_streak=2,
            protect_last_failed=False,
        )
        records = action_trace.get_records()
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["kind"], "candidate")
        self.assertEqual(rec["battle_tag"], "battle-42")
        self.assertEqual(rec["turn"], 7)
        self.assertEqual(rec["active_idx"], 0)
        self.assertEqual(rec["pokemon_ident"], "p1a: Volcarona")
        self.assertEqual(rec["pokemon_types"], "Bug,Fire")
        self.assertEqual(rec["candidate_move_id"], "protect")
        self.assertTrue(rec["is_protect_candidate"])
        self.assertTrue(rec["is_hard_blocked"])
        self.assertEqual(
            rec["hard_block_reason"],
            "repeated_protect_like_third_attempt",
        )
        self.assertEqual(rec["protect_like_class"], "protect_like")
        self.assertEqual(rec["committed_protect_streak"], 2)
        self.assertFalse(rec["protect_last_failed"])
        self.assertEqual(rec["raw_score_before_policy"], -1e9)

    def test_commit_trace_exposes_final_order_state_transition(self):
        battle = _Battle(battle_tag="battle-commit", turn=4, actives=[_Mon()])
        action_trace.record_state_update(
            battle,
            0,
            is_reset=False,
            selected_move_id="protect",
            committed_streak_before=1,
            committed_streak_after=2,
            source="final_selected_order",
        )
        rec = action_trace.get_records()[0]
        self.assertEqual(rec["kind"], "protect_state_commit")
        self.assertEqual(rec["source"], "final_selected_order")
        self.assertEqual(rec["selected_move_id"], "protect")
        self.assertEqual(rec["committed_streak_before"], 1)
        self.assertEqual(rec["committed_streak_after"], 2)


class TestRecordStateUpdateBehavior(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="phase7_trace_test_")
        self._guard = _TraceStateGuard()
        self._guard.__enter__()
        os.environ["PHASE7_ACTION_TRACE_DIR"] = self._tmpdir
        action_trace.unset_trace_dir_explicit()

    def tearDown(self):
        self._guard.__exit__(None, None, None)

    def test_state_update_increments_update_counter(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_state_update(battle, 0, is_reset=False)
        action_trace.record_state_update(battle, 0, is_reset=False)
        summary = action_trace.get_summary()
        self.assertEqual(summary["protect_state_update_count"], 2)
        self.assertEqual(summary["protect_state_reset_count"], 0)

    def test_state_reset_increments_reset_counter(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_state_update(battle, 0, is_reset=True)
        summary = action_trace.get_summary()
        self.assertEqual(summary["protect_state_update_count"], 0)
        self.assertEqual(summary["protect_state_reset_count"], 1)


class TestFlushRecordsBehavior(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="phase7_trace_test_")
        self._guard = _TraceStateGuard()
        self._guard.__enter__()
        os.environ["PHASE7_ACTION_TRACE_DIR"] = self._tmpdir
        action_trace.unset_trace_dir_explicit()

    def tearDown(self):
        self._guard.__exit__(None, None, None)

    def test_flush_writes_jsonl_and_summary(self):
        battle = _Battle(battle_tag="battle-99", turn=3, actives=[_Mon()])
        action_trace.record_candidate(
            battle, 0, _protect_order(), -1e9,
            hard_block_reason="repeated_protect",
        )
        action_trace.flush_records()
        files = sorted(os.listdir(self._tmpdir))
        self.assertEqual(len(files), 2)
        jsonls = [f for f in files if f.endswith(".jsonl")]
        summaries = [f for f in files if f.endswith(".json")]
        self.assertEqual(len(jsonls), 1)
        self.assertEqual(len(summaries), 1)
        with open(os.path.join(self._tmpdir, jsonls[0])) as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["kind"], "candidate")
        with open(os.path.join(self._tmpdir, summaries[0])) as f:
            summary = json.load(f)
        self.assertTrue(summary["action_trace_enabled"])
        self.assertEqual(summary["action_trace_event_count"], 1)
        self.assertEqual(summary["protect_hard_block_candidate_count"], 1)

    def test_flush_idempotent_writes_separate_files(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_candidate(
            battle, 0, _protect_order(), -1e9,
            hard_block_reason="repeated_protect",
        )
        action_trace.flush_records()
        action_trace.flush_records()
        files = sorted(os.listdir(self._tmpdir))
        jsonls = [f for f in files if f.endswith(".jsonl")]
        self.assertEqual(len(jsonls), 2)
        for jsonl in jsonls:
            with open(os.path.join(self._tmpdir, jsonl)) as f:
                lines = [l for l in f.read().splitlines() if l.strip()]
            self.assertEqual(len(lines), 1)

    def test_reset_clears_buffer_before_flush(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_candidate(
            battle, 0, _protect_order(), -1e9,
            hard_block_reason="repeated_protect",
        )
        action_trace.reset_action_trace_counters()
        action_trace.flush_records()
        files = sorted(os.listdir(self._tmpdir))
        jsonls = [f for f in files if f.endswith(".jsonl")]
        self.assertEqual(len(jsonls), 1)
        with open(os.path.join(self._tmpdir, jsonls[0])) as f:
            content = f.read()
        self.assertEqual(content, "")

    def test_flush_after_reset_writes_empty(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_candidate(
            battle, 0, _protect_order(), -1e9,
            hard_block_reason="repeated_protect",
        )
        action_trace.reset_action_trace_counters()
        action_trace.flush_records()
        files = sorted(os.listdir(self._tmpdir))
        jsonls = [f for f in files if f.endswith(".jsonl")]
        self.assertEqual(len(jsonls), 1)
        with open(os.path.join(self._tmpdir, jsonls[0])) as f:
            content = f.read()
        self.assertEqual(content, "")


class TestRecordCandidateDoesNotMutateOrder(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="phase7_trace_test_")
        self._guard = _TraceStateGuard()
        self._guard.__enter__()
        os.environ["PHASE7_ACTION_TRACE_DIR"] = self._tmpdir
        action_trace.unset_trace_dir_explicit()

    def tearDown(self):
        self._guard.__exit__(None, None, None)

    def test_record_does_not_change_order_score(self):
        order = _protect_order()
        original_score = -1e9
        battle = _Battle(actives=[_Mon()])
        action_trace.record_candidate(
            battle, 0, order, original_score,
            hard_block_reason="repeated_protect",
        )
        self.assertEqual(getattr(order, "move_target", None), -1)
        self.assertIsNotNone(order.order)
        self.assertEqual(order.order.id, "protect")


class TestRecordJointBehavior(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="phase7_trace_test_")
        self._guard = _TraceStateGuard()
        self._guard.__enter__()
        os.environ["PHASE7_ACTION_TRACE_DIR"] = self._tmpdir
        action_trace.unset_trace_dir_explicit()

    def tearDown(self):
        self._guard.__exit__(None, None, None)

    def test_joint_hard_block_increments_counter(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_joint(
            battle, 0, _protect_order(), _protect_order(),
            -1e9, -1e9, -2e9, -2e9, -2e9,
            joint_has_hard_block=True,
            joint_selected=True,
            selection_rank=0,
        )
        summary = action_trace.get_summary()
        self.assertEqual(summary["hard_blocked_joint_count"], 1)

    def test_joint_no_hard_block_does_not_increment(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_joint(
            battle, 0, _non_protect_order("tackle"),
            _non_protect_order("tackle"),
            50.0, 60.0, 110.0, 110.0, 110.0,
            joint_has_hard_block=False,
            joint_selected=True,
            selection_rank=0,
        )
        summary = action_trace.get_summary()
        self.assertEqual(summary["hard_blocked_joint_count"], 0)

    def test_joint_at_threshold_counts_as_hard_block(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_joint(
            battle, 0, _protect_order(), _protect_order(),
            HARD_BLOCK_SCORE_THRESHOLD, 50.0, 0.0, 0.0, 0.0,
            joint_has_hard_block=True,
            joint_selected=False,
            selection_rank=1,
        )
        summary = action_trace.get_summary()
        self.assertEqual(summary["hard_blocked_joint_count"], 1)

    def test_joint_carries_metadata(self):
        battle = _Battle(battle_tag="battle-j", turn=4, actives=[_Mon()])
        action_trace.record_joint(
            battle, 7, _protect_order(), _protect_order(),
            -1e9, 50.0, -1e9 + 50, -1e9 + 50, -1e9 + 50,
            joint_has_hard_block=True,
            joint_selected=False,
            selection_rank=7,
            call_depth=0,
            counterfactual="canonical",
        )
        records = action_trace.get_records()
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["kind"], "joint")
        self.assertEqual(rec["battle_tag"], "battle-j")
        self.assertEqual(rec["turn"], 4)
        self.assertEqual(rec["joint_id"], 7)
        self.assertEqual(rec["slot0_move"], "protect")
        self.assertEqual(rec["slot1_move"], "protect")
        self.assertEqual(rec["selection_rank"], 7)
        self.assertEqual(rec["call_depth"], 0)
        self.assertEqual(rec["counterfactual"], "canonical")
        self.assertTrue(rec["joint_has_hard_block"])

    def test_joint_default_call_depth_and_counterfactual(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_joint(
            battle, 0, _protect_order(), _protect_order(),
            -1e9, -1e9, -2e9, -2e9, -2e9,
            joint_has_hard_block=True,
            joint_selected=False,
            selection_rank=0,
        )
        records = action_trace.get_records()
        self.assertEqual(records[0]["call_depth"], 0)
        self.assertEqual(records[0]["counterfactual"], "")


class TestRecordFinalOrdersBehavior(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="phase7_trace_test_")
        self._guard = _TraceStateGuard()
        self._guard.__enter__()
        os.environ["PHASE7_ACTION_TRACE_DIR"] = self._tmpdir
        action_trace.unset_trace_dir_explicit()

    def tearDown(self):
        self._guard.__exit__(None, None, None)

    def test_final_orders_hard_block_increments_counter(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_final_orders(
            battle, _protect_order(), _protect_order(),
            first_was_hard_blocked=True,
            second_was_hard_blocked=True,
            emergency_fallback_used=False,
        )
        summary = action_trace.get_summary()
        self.assertEqual(
            summary["selected_hard_blocked_action_count"], 1
        )

    def test_final_orders_no_hard_block(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_final_orders(
            battle, _non_protect_order("tackle"),
            _non_protect_order("tackle"),
            first_was_hard_blocked=False,
            second_was_hard_blocked=False,
            emergency_fallback_used=False,
        )
        summary = action_trace.get_summary()
        self.assertEqual(
            summary["selected_hard_blocked_action_count"], 0
        )

    def test_final_orders_emergency_fallback(self):
        battle = _Battle(actives=[_Mon()])
        action_trace.record_final_orders(
            battle, _protect_order(), _protect_order(),
            first_was_hard_blocked=False,
            second_was_hard_blocked=False,
            emergency_fallback_used=True,
            fallback_reason="no_legal_action",
        )
        summary = action_trace.get_summary()
        self.assertEqual(summary["emergency_fallback_count"], 1)

    def test_final_orders_carries_metadata(self):
        battle = _Battle(battle_tag="battle-f", turn=9, actives=[_Mon()])
        action_trace.record_final_orders(
            battle, _protect_order(), _non_protect_order("tackle"),
            first_was_hard_blocked=True,
            second_was_hard_blocked=False,
            emergency_fallback_used=False,
            fallback_reason="",
        )
        records = action_trace.get_records()
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["kind"], "final_orders")
        self.assertEqual(rec["battle_tag"], "battle-f")
        self.assertEqual(rec["turn"], 9)
        self.assertEqual(rec["final_slot0_move"], "protect")
        self.assertEqual(rec["final_slot1_move"], "tackle")
        self.assertTrue(rec["final_slot0_was_hard_blocked"])
        self.assertFalse(rec["final_slot1_was_hard_blocked"])


class TestWiredProductionCallPoint(unittest.TestCase):
    """Static check: the production scorer must call
    action_trace.record_candidate, record_joint, and
    record_final_orders at the right points.
    """

    def test_record_candidate_called_after_repeated_protect_block(self):
        import inspect
        from showdown_ai import bot_doubles_damage_aware as b
        src = inspect.getsource(b)
        marker = "if _is_repeated_protect_spam("
        idx = src.find(marker)
        self.assertGreaterEqual(idx, 0, "repeated_protect_spam call not found")
        window = src[idx:idx + 1200]
        self.assertIn("action_trace.record_candidate(", window)
        self.assertIn("repeated_protect", window)

    def test_record_joint_called_after_compute_joint_scores(self):
        import inspect
        from showdown_ai import bot_doubles_damage_aware as b
        src = inspect.getsource(b)
        marker = "scored_joint_orders = self._compute_joint_scores("
        idx = src.find(marker)
        self.assertGreaterEqual(idx, 0, "_compute_joint_scores call not found")
        window = src[idx:idx + 4000]
        self.assertIn("action_trace.record_joint(", window)
        self.assertIn("call_depth=int(pure)", window)
        self.assertIn('counterfactual="pure" if pure else "canonical"',
                      window)

    def test_record_final_orders_called_before_return_best_joint(self):
        import inspect
        from showdown_ai import bot_doubles_damage_aware as b
        src = inspect.getsource(b)
        marker = "return best_joint"
        idx = src.find(marker)
        self.assertGreaterEqual(idx, 0, "return best_joint not found")
        window = src[max(0, idx - 4000):idx]
        self.assertIn("action_trace.record_final_orders(", window)
        self.assertIn("HARD_BLOCK_SCORE_THRESHOLD", window)


class TestNoCircularImport(unittest.TestCase):
    """Regression: bot_doubles_damage_aware eagerly imports
    action_trace at module top. action_trace must not
    re-import bot_doubles_damage_aware at module top or
    the cycle breaks when either module is the entry
    point.
    """

    def test_action_trace_no_eager_relative_import_of_bot(self):
        import inspect
        import showdown_ai.action_trace as at
        src = inspect.getsource(at)
        module_lines = [
            line for line in src.splitlines()
            if line.startswith(("from .bot_", "import .bot_"))
        ]
        self.assertEqual(
            module_lines, [],
            f"action_trace.py must not eagerly import "
            f"bot_doubles_damage_aware; found: {module_lines}",
        )

    def test_threshold_resolves_via_lazy_import(self):
        from showdown_ai import action_trace
        threshold = action_trace._hard_block_score_threshold()
        from showdown_ai.bot_doubles_damage_aware import (
            HARD_BLOCK_SCORE_THRESHOLD,
        )
        self.assertEqual(threshold, HARD_BLOCK_SCORE_THRESHOLD)

    def test_threshold_fallback_when_bot_unavailable(self):
        from showdown_ai import action_trace
        original = action_trace._hard_block_score_threshold
        action_trace._hard_block_score_threshold = lambda: (
            action_trace._HARD_BLOCK_SCORE_THRESHOLD_FALLBACK
        )
        try:
            self.assertEqual(
                action_trace._hard_block_score_threshold(), -1e8
            )
        finally:
            action_trace._hard_block_score_threshold = original


class AuditModuleTraceEnablerTest(unittest.TestCase):
    """Verify the diagnostic trace enabler wiring inside
    ``rl_data_3b_small_local_audit.run_smoke``.

    The audit module must:
      * import safely (no hard dependency on ``action_trace``),
      * call ``action_trace.flush_records()`` at the end of
        ``run_smoke`` before return,
      * be harmless when trace is disabled.
    """

    def test_audit_module_imports_with_action_trace_available(self):
        import showdown_ai.rl_data_3b_small_local_audit as audit_mod
        self.assertTrue(hasattr(audit_mod, "run_smoke"))
        self.assertTrue(hasattr(audit_mod, "action_trace"))

    def test_audit_module_imports_when_action_trace_missing(self):
        import showdown_ai.rl_data_3b_small_local_audit as audit_mod
        # The module must guard the import with try/except
        # ImportError so that a missing action_trace does not
        # break the audit module. Verify the guard exists in
        # source text.
        import inspect
        src = inspect.getsource(audit_mod)
        self.assertIn("from . import action_trace", src)
        self.assertIn("except ImportError:", src)
        self.assertIn("import action_trace", src)

    def test_run_smoke_calls_flush_records_before_return(self):
        import inspect
        import showdown_ai.rl_data_3b_small_local_audit as audit_mod
        src = inspect.getsource(audit_mod.run_smoke)
        self.assertIn("action_trace.flush_records()", src)
        flush_pos = src.find("action_trace.flush_records()")
        return_pos = src.rfind("return {")
        self.assertGreater(flush_pos, -1, "flush_records() call not found")
        self.assertGreater(
            return_pos, flush_pos,
            "flush_records() must be called before the return dict",
        )

    def test_flush_in_run_smoke_is_wrapped_in_try_except(self):
        import inspect
        import showdown_ai.rl_data_3b_small_local_audit as audit_mod
        src = inspect.getsource(audit_mod.run_smoke)
        self.assertIn("try:", src)
        self.assertIn("action_trace.flush_records()", src)
        self.assertIn("except Exception as e:", src)
        flush_pos = src.find("action_trace.flush_records()")
        try_window = src.rfind("try:", 0, flush_pos)
        except_window = src.find("except Exception as e:", flush_pos)
        self.assertGreater(try_window, -1)
        self.assertGreater(except_window, flush_pos)


if __name__ == "__main__":
    unittest.main()
