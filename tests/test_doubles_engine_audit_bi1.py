#!/usr/bin/env python3
"""Tests for Phase BI-1 audit-completeness instrumentation.

ponytail: focused tests for the V4a and
voluntary-switch telemetry that BI-1 adds to the
audit logger and the live JSONL event.

These tests verify:
- V4a fields are accepted by log_turn_decision(...)
  and written to turn_data.
- voluntary_switch fields (decision_eligible,
  selected, selected_species) are accepted and
  written to turn_data.
- The _build_live_decision_event output contains
  a ``v4a`` sub-dict with selected_joint_key and
  final_action_keys.
- The live event contains a ``voluntary_switch``
  sub-dict with eligibility, selection, candidate
  count, and selected_species.
- Missing fields serialize as the logger's
  conventional defaults ([], {}, False, "").

No behavior change. No scoring change. No
``SingleBattleOrder(mega=True)`` is ever created.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _make_logger(detail_level="top5", live_event_filepath=None):
    """Construct a fresh audit logger with
    isolated temp files."""
    with tempfile.NamedTemporaryFile(
        suffix=".jsonl", delete=False
    ) as f:
        path = f.name
    if live_event_filepath is None:
        with tempfile.NamedTemporaryFile(
            suffix=".live.jsonl", delete=False
        ) as f:
            live_path = f.name
    else:
        live_path = live_event_filepath
    from doubles_decision_audit_logger import (
        DoublesDecisionAuditLogger,
    )
    logger = DoublesDecisionAuditLogger(
        filepath=path,
        reset=True,
        detail_level=detail_level,
        live_event_filepath=live_path,
    )
    return logger, path, live_path


def _cleanup(paths):
    for p in paths:
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


# Minimal valid kwargs for log_turn_decision (Phase BI-1
# only asserts on V4a and voluntary_switch kwargs, so the
# other args use safe defaults).
_MINIMAL_KWARGS = dict(
    scored_joint_orders=[],
    expected_damages=[None, None],
    expected_kos=[None, None],
    target_hps=[1.0, 1.0],
    overkill_triggered=[False, False],
    focus_fire_triggered=[False, False],
    ally_hit_penalty_triggered=[False, False],
    spread_available=[False, False],
    best_spread_score=[0.0, 0.0],
    best_ko_score=[0.0, 0.0],
    low_hp_opponent_existed=False,
    low_hp_opponent_targeted=False,
    slot_actions=[None, None],
    slot_action_types=[None, None],
    target_species=[None, None],
    v2l1_legal_action_keys_slot0=[],
    v2l1_legal_action_keys_slot1=[],
    v2l1_raw_scores_slot0={},
    v2l1_raw_scores_slot1={},
    v2l1_safety_blocks_slot0={},
    v2l1_safety_blocks_slot1={},
    v2l1_selected_joint_key=None,
    v2l1_final_action_keys=[],
)


def _call(logger, battle_tag="tag", turn=1, **overrides):
    """Call log_turn_decision with minimal kwargs +
    caller overrides. Returns the pending turn_data
    dict (the one that holds V2l.1 / V4a / voluntary
    switch kwargs). The audit logger stores this
    in ``pending_turns`` and promotes it to
    ``completed_turns`` only on the next call.
    """
    battle_turn = turn  # capture in local for class-body closure

    class FakeBattle:
        player_username = "test"
        turn = battle_turn
        active_pokemon = [None, None]
        opponent_active_pokemon = [None, None]

    kwargs = dict(_MINIMAL_KWARGS)
    kwargs.update(overrides)
    logger.completed_turns[battle_tag] = []
    logger.log_turn_decision(
        battle_tag=battle_tag,
        turn=turn,
        battle=FakeBattle(),
        selected_joint_order="pass",
        selected_score=0.0,
        **kwargs,
    )
    return logger.pending_turns.get(battle_tag)


class TestV4aFieldsAccepted(unittest.TestCase):
    def test_log_turn_decision_accepts_v4a_kwargs(self):
        logger, main, live = _make_logger()
        try:
            td = _call(
                logger,
                v4a_legal_action_keys_slot0=[],
                v4a_legal_action_keys_slot1=[],
                v4a_raw_scores_slot0={},
                v4a_raw_scores_slot1={},
                v4a_selected_joint_key=None,
                v4a_final_action_keys=[],
            )
            # turn_data should now carry the v4a keys.
            self.assertIn("v4a_legal_action_keys_slot0", td)
            self.assertIn("v4a_legal_action_keys_slot1", td)
            self.assertIn("v4a_raw_scores_slot0", td)
            self.assertIn("v4a_raw_scores_slot1", td)
            self.assertIn("v4a_selected_joint_key", td)
            self.assertIn("v4a_final_action_keys", td)
        finally:
            _cleanup([main, live])


class TestV4aFieldsInLiveEvent(unittest.TestCase):
    def test_live_event_has_v4a_subdict(self):
        logger, main, live = _make_logger()
        try:
            _call(
                logger,
                v4a_selected_joint_key=("none", "", 0, ""),
                v4a_final_action_keys=[("none", "", 0, "")],
            )
            with open(live) as f:
                lines = [l for l in f if l.strip()]
            self.assertGreater(len(lines), 0)
            event = json.loads(lines[-1])
            self.assertIn("v4a", event)
            # JSON serialization converts tuples to
            # lists, so the live event value is a list.
            self.assertEqual(
                event["v4a"]["v4a_selected_joint_key"],
                ["none", "", 0, ""],
            )
            self.assertEqual(
                event["v4a"]["v4a_final_action_keys"],
                [["none", "", 0, ""]],
            )
        finally:
            _cleanup([main, live])

    def test_v4a_mechanic_unchanged_for_plain_move(self):
        """Plain (non-Mega) move V4a key mechanic must
        remain empty string. No Mega behavior is
        implied. This is a regression guard.
        """
        from doubles_engine.action_keys import (
            _order_action_key_with_mechanic,
        )
        from poke_env.player.battle_order import (
            SingleBattleOrder,
        )
        from poke_env.battle.move import Move

        # Construct a plain move (no mega attribute).
        move = MagicMock(spec=Move)
        move.id = "tackle"
        order = MagicMock(spec=SingleBattleOrder)
        order.order = move
        order.move_target = 0
        # Ensure mega/z_move/dynamax/terastallize
        # are all False (plain move).
        type(order).mega = property(lambda self: False)
        type(order).z_move = property(lambda self: False)
        type(order).dynamax = property(lambda self: False)
        type(order).terastallize = property(lambda self: False)

        key = _order_action_key_with_mechanic(order)
        # 4-tuple: (action_type, action_id, target, mechanic)
        self.assertEqual(len(key), 4)
        self.assertEqual(key[3], "")  # mechanic is empty


class TestVoluntarySwitchFields(unittest.TestCase):
    def test_voluntary_switch_kwargs_accepted(self):
        """voluntary_switch_decision_eligible, _selected,
        _selected_species are now explicit kwargs.
        """
        logger, main, live = _make_logger()
        try:
            td = _call(
                logger,
                voluntary_switch_decision_eligible=[True, False],
                voluntary_switch_selected=[True, False],
                voluntary_switch_selected_species=["pikachu", ""],
            )
            self.assertEqual(
                td.get("voluntary_switch_decision_eligible"),
                [True, False],
            )
            self.assertEqual(
                td.get("voluntary_switch_selected"),
                [True, False],
            )
            self.assertEqual(
                td.get("voluntary_switch_selected_species"),
                ["pikachu", ""],
            )
        finally:
            _cleanup([main, live])

    def test_voluntary_switch_live_event_subdict(self):
        logger, main, live = _make_logger()
        try:
            _call(
                logger,
                voluntary_switch_decision_eligible=[True, False],
                voluntary_switch_selected=[False, True],
                voluntary_switch_selected_species=["pikachu", "charizard"],
                voluntary_switch_candidate_count=[2, 1],
            )
            with open(live) as f:
                lines = [l for l in f if l.strip()]
            event = json.loads(lines[-1])
            self.assertIn("voluntary_switch", event)
            vsw = event["voluntary_switch"]
            self.assertEqual(
                vsw["voluntary_switch_decision_eligible"],
                [True, False],
            )
            self.assertEqual(
                vsw["voluntary_switch_selected"],
                [False, True],
            )
            self.assertEqual(
                vsw["voluntary_switch_candidate_count"],
                [2, 1],
            )
            self.assertEqual(
                vsw["voluntary_switch_selected_species"],
                ["pikachu", "charizard"],
            )
        finally:
            _cleanup([main, live])

    def test_missing_voluntary_switch_defaults(self):
        """When voluntary_switch_* are not passed,
        the logger should fall back to safe defaults
        ([], [], False, ""). This is the same
        convention used for the existing raw/cand
        counts.
        """
        logger, main, live = _make_logger()
        try:
            td = _call(logger)
            # Defaults are the safe empty form.
            self.assertEqual(
                td.get("voluntary_switch_decision_eligible"),
                [False, False],
            )
            self.assertEqual(
                td.get("voluntary_switch_selected"),
                [False, False],
            )
            self.assertEqual(
                td.get("voluntary_switch_selected_species"),
                ["", ""],
            )
        finally:
            _cleanup([main, live])


class TestNoProductionCleanupImport(unittest.TestCase):
    """Regression guard: BI-1 must not add a
    production import of poke_env_test_cleanup.
    """

    def test_bot_does_not_import_cleanup(self):
        import bot_doubles_damage_aware as b
        with open(b.__file__) as f:
            content = f.read()
        self.assertNotIn(
            "import poke_env_test_cleanup", content
        )
        self.assertNotIn(
            "from poke_env_test_cleanup", content
        )

    def test_audit_logger_does_not_import_cleanup(self):
        import doubles_decision_audit_logger as m
        with open(m.__file__) as f:
            content = f.read()
        self.assertNotIn(
            "import poke_env_test_cleanup", content
        )
        self.assertNotIn(
            "from poke_env_test_cleanup", content
        )


# ---------------------------------------------------------------------------
# Persisted JSONL validation (BI-2A)
# ---------------------------------------------------------------------------
# These tests confirm that the BI-1 audit fields actually reach
# the persisted JSONL (audit_turns and the live event file), not
# only the in-memory turn_data. This is the end-to-end validation
# that the phase plan requires.


class TestPersistedJSONL(unittest.TestCase):
    """Drive the audit logger through a full save_battle
    and assert the BI-1 fields appear in the persisted
    JSONL.
    """

    def _save_and_read(self, **vsw_overrides):
        """Helper: build a fresh logger with both the
        main JSONL and the live-event JSONL, log one
        fake turn with BI-1 kwargs, call save_battle,
        and return (main_record, live_events).
        """
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False
        ) as f:
            main_path = f.name
        with tempfile.NamedTemporaryFile(
            suffix=".live.jsonl", delete=False
        ) as f:
            live_path = f.name
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        logger = DoublesDecisionAuditLogger(
            filepath=main_path,
            reset=True,
            detail_level="top5",
            live_event_filepath=live_path,
        )
        try:
            class FB:
                player_username = "test"
                turn = 1
                active_pokemon = [None, None]
                opponent_active_pokemon = [None, None]

            # Vol switch decisions for BI-1.
            _call(
                logger,
                v4a_legal_action_keys_slot0=[("move", "tackle", 0, "")],
                v4a_legal_action_keys_slot1=[("switch", "pikachu", -1, "")],
                v4a_selected_joint_key=(
                    ("move", "tackle", 0, ""),
                    ("switch", "pikachu", -1, ""),
                ),
                v4a_final_action_keys=[
                    ("move", "tackle", 0, ""),
                    ("switch", "pikachu", -1, ""),
                ],
                voluntary_switch_decision_eligible=[True, False],
                voluntary_switch_selected=[True, False],
                voluntary_switch_selected_species=["pikachu", ""],
                voluntary_switch_candidate_count=[2, 1],
            )
            # save_battle writes the main JSONL.
            logger.save_battle("tag", "test", FB())

            with open(main_path) as f:
                main_record = json.loads(f.readline())
            with open(live_path) as f:
                live_lines = [l for l in f if l.strip()]
            live_events = [json.loads(l) for l in live_lines]

            return main_record, live_events
        finally:
            _cleanup([main_path, live_path])

    def test_persisted_main_jsonl_has_v4a_keys(self):
        main_record, _ = self._save_and_read()
        # The audit_turns list is in the main JSONL.
        audit_turns = main_record["audit_turns"]
        self.assertGreaterEqual(len(audit_turns), 1)
        turn = audit_turns[0]
        # V4a fields written to turn_data appear in the
        # persisted JSONL.
        self.assertIn("v4a_selected_joint_key", turn)
        self.assertIn("v4a_final_action_keys", turn)
        # JSON serialization converts tuples to lists.
        # v4a_selected_joint_key is a 2-tuple of 4-tuples.
        self.assertEqual(
            turn["v4a_selected_joint_key"],
            [["move", "tackle", 0, ""],
             ["switch", "pikachu", -1, ""]],
        )
        # v4a_final_action_keys is a list of 4-tuples.
        self.assertEqual(
            turn["v4a_final_action_keys"],
            [["move", "tackle", 0, ""],
             ["switch", "pikachu", -1, ""]],
        )

    def test_persisted_main_jsonl_has_voluntary_switch_keys(self):
        main_record, _ = self._save_and_read()
        audit_turns = main_record["audit_turns"]
        turn = audit_turns[0]
        # Voluntary switch kwargs are written to turn_data.
        self.assertIn("voluntary_switch_decision_eligible", turn)
        self.assertIn("voluntary_switch_selected", turn)
        self.assertIn("voluntary_switch_selected_species", turn)
        self.assertEqual(
            turn["voluntary_switch_decision_eligible"],
            [True, False],
        )
        self.assertEqual(
            turn["voluntary_switch_selected"],
            [True, False],
        )
        self.assertEqual(
            turn["voluntary_switch_selected_species"],
            ["pikachu", ""],
        )

    def test_live_event_has_v4a_and_voluntary_switch_subdicts(self):
        _, live_events = self._save_and_read()
        decision_events = [
            e for e in live_events if e.get("event") == "decision"
        ]
        self.assertGreaterEqual(len(decision_events), 1)
        ev = decision_events[0]
        # V4a sub-dict with selected_joint_key and
        # final_action_keys.
        self.assertIn("v4a", ev)
        self.assertIn("v4a_selected_joint_key", ev["v4a"])
        self.assertIn("v4a_final_action_keys", ev["v4a"])
        # Voluntary switch sub-dict.
        self.assertIn("voluntary_switch", ev)
        self.assertIn(
            "voluntary_switch_decision_eligible",
            ev["voluntary_switch"],
        )
        self.assertIn(
            "voluntary_switch_selected",
            ev["voluntary_switch"],
        )
        self.assertIn(
            "voluntary_switch_candidate_count",
            ev["voluntary_switch"],
        )
        self.assertIn(
            "voluntary_switch_selected_species",
            ev["voluntary_switch"],
        )

    def test_missing_v4a_serializes_with_safe_defaults(self):
        """When the bot does not pass v4a_* kwargs, the
        persisted JSONL should still serialize (with
        None or empty-list defaults, not raise).
        """
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False
        ) as f:
            main_path = f.name
        with tempfile.NamedTemporaryFile(
            suffix=".live.jsonl", delete=False
        ) as f:
            live_path = f.name
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        logger = DoublesDecisionAuditLogger(
            filepath=main_path,
            reset=True,
            detail_level="top5",
            live_event_filepath=live_path,
        )
        try:
            class FB:
                player_username = "test"
                turn = 1
                active_pokemon = [None, None]
                opponent_active_pokemon = [None, None]

            _call(logger)  # no v4a_* or voluntary_switch_* kwargs
            logger.save_battle("tag", "test", FB())

            with open(main_path) as f:
                main_record = json.loads(f.readline())
            audit_turns = main_record["audit_turns"]
            turn = audit_turns[0]
            # v4a_selected_joint_key default is None.
            self.assertIsNone(turn["v4a_selected_joint_key"])
            # v4a_final_action_keys default is None (logger
            # sig default), but the live event writer
            # coerces to [] for the live JSONL. The
            # main JSONL keeps None.
            self.assertIsNone(turn["v4a_final_action_keys"])
            # voluntary_switch defaults.
            self.assertEqual(
                turn["voluntary_switch_decision_eligible"],
                [False, False],
            )
            self.assertEqual(
                turn["voluntary_switch_selected"],
                [False, False],
            )
            self.assertEqual(
                turn["voluntary_switch_selected_species"],
                ["", ""],
            )
        finally:
            _cleanup([main_path, live_path])


if __name__ == "__main__":
    unittest.main()
