"""Phase SPREAD-2 — Tests for the new spread-defense
audit fields. Pure unit tests using a mock battle
object; no live poke-env, no Showdown.

Mirrors the COMBO-3 fixture pattern from
``test_doubles_combo3_ally_activation_audit.py``.

New audit fields tested:

Per-slot (slot_0 / slot_1 sub-dicts):
- ``wide_guard_legal``
- ``quick_guard_legal``
- ``crafty_shield_legal``
- ``spread_defense_selected``

Top-level:
- ``opp_pressure_state``

``opp_actions``:
- ``opponent_used_spread``
- ``opponent_used_protect``
- ``opponent_used_wide_guard``
- ``opponent_used_quick_guard``

No scoring change. Pure observation.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from doubles_decision_audit_logger import (
    DoublesDecisionAuditLogger,
)


def _make_logger(path):
    return DoublesDecisionAuditLogger(
        filepath=path, reset=True, detail_level="top5"
    )


def _make_battle_mock():
    battle = MagicMock()
    battle.active_pokemon = []
    battle.opponent_active_pokemon = []
    battle.available_switches = []
    battle.force_switch = [False, False]
    battle.opponent_side_conditions = {}
    battle.side_conditions = {}
    battle.weather = None
    battle.fields = set()
    return battle


def _build_kwargs(
    battle,
    selected_joint_order="/choose move surf 1",
    slot_actions=("", ""),
    slot_action_types=(
        {"damaging": True, "status": False},
        {"damaging": True, "status": False},
    ),
    target_species=("", ""),
    expected_damages=(0.0, 0.0),
    expected_kos=(False, False),
    target_hps=(1.0, 1.0),
    # New SPREAD-2 fields:
    wide_guard_legal=(False, False),
    quick_guard_legal=(False, False),
    crafty_shield_legal=(False, False),
    spread_defense_selected=("", ""),
    opp_pressure_state=False,
):
    """Build kwargs for log_turn_decision."""
    return dict(
        battle_tag="test-battle-1",
        turn=1,
        battle=battle,
        selected_joint_order=selected_joint_order,
        selected_score=100.0,
        scored_joint_orders=[],
        expected_damages=expected_damages,
        expected_kos=expected_kos,
        target_hps=target_hps,
        overkill_triggered=False,
        focus_fire_triggered=False,
        ally_hit_penalty_triggered=False,
        spread_available=[False, False],
        best_spread_score=[None, None],
        best_ko_score=[None, None],
        low_hp_opponent_existed=False,
        low_hp_opponent_targeted=False,
        slot_actions=slot_actions,
        slot_action_types=slot_action_types,
        target_species=target_species,
        # New SPREAD-2 fields:
        wide_guard_legal=wide_guard_legal,
        quick_guard_legal=quick_guard_legal,
        crafty_shield_legal=crafty_shield_legal,
        spread_defense_selected=spread_defense_selected,
        opp_pressure_state=opp_pressure_state,
    )


class TestLoggerAcceptsNewFields(unittest.TestCase):
    """The logger must accept the new SPREAD-2
    fields without raising TypeError. Values must
    be persisted in the saved battle record.
    """

    def test_logger_accepts_wide_guard_legal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            logger.log_turn_decision(
                **_build_kwargs(
                    battle,
                    wide_guard_legal=(True, False),
                )
            )
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            self.assertIn("wide_guard_legal", t["slot_0"])
            self.assertEqual(t["slot_0"]["wide_guard_legal"], True)
            self.assertEqual(t["slot_1"]["wide_guard_legal"], False)

    def test_logger_accepts_quick_guard_legal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            logger.log_turn_decision(
                **_build_kwargs(
                    battle,
                    quick_guard_legal=(False, True),
                )
            )
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            self.assertEqual(t["slot_0"]["quick_guard_legal"], False)
            self.assertEqual(t["slot_1"]["quick_guard_legal"], True)

    def test_logger_accepts_crafty_shield_legal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            logger.log_turn_decision(
                **_build_kwargs(
                    battle,
                    crafty_shield_legal=(True, True),
                )
            )
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            self.assertEqual(t["slot_0"]["crafty_shield_legal"], True)
            self.assertEqual(t["slot_1"]["crafty_shield_legal"], True)

    def test_logger_accepts_spread_defense_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            logger.log_turn_decision(
                **_build_kwargs(
                    battle,
                    spread_defense_selected=("wideguard", ""),
                )
            )
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            self.assertEqual(
                t["slot_0"]["spread_defense_selected"], "wideguard"
            )
            self.assertEqual(
                t["slot_1"]["spread_defense_selected"], ""
            )

    def test_logger_accepts_opp_pressure_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            logger.log_turn_decision(
                **_build_kwargs(battle, opp_pressure_state=True)
            )
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            self.assertIn("opp_pressure_state", t)
            self.assertEqual(t["opp_pressure_state"], True)

    def test_logger_default_opp_pressure_state_false(self):
        """When opp_pressure_state is omitted, the
        top-level field should be missing (default
        False from logger initializer). This proves
        backward compat — old artifacts without
        the field still load cleanly."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            # omit opp_pressure_state
            kwargs = _build_kwargs(battle)
            kwargs.pop("opp_pressure_state", None)
            logger.log_turn_decision(**kwargs)
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            # When omitted, the field is NOT persisted.
            self.assertNotIn("opp_pressure_state", t)

    def test_logger_default_spread_defense_fields_false(self):
        """When the new per-slot fields are omitted,
        each slot dict should still get the field
        defaulting to False/empty-string."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            kwargs = _build_kwargs(battle)
            for k in (
                "wide_guard_legal",
                "quick_guard_legal",
                "crafty_shield_legal",
                "spread_defense_selected",
            ):
                kwargs.pop(k, None)
            logger.log_turn_decision(**kwargs)
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            for sk in ("slot_0", "slot_1"):
                self.assertIn("wide_guard_legal", t[sk])
                self.assertIn("quick_guard_legal", t[sk])
                self.assertIn("crafty_shield_legal", t[sk])
                self.assertIn("spread_defense_selected", t[sk])
                self.assertEqual(t[sk]["wide_guard_legal"], False)
                self.assertEqual(t[sk]["quick_guard_legal"], False)
                self.assertEqual(t[sk]["crafty_shield_legal"], False)
                self.assertEqual(t[sk]["spread_defense_selected"], "")


class TestBotSpreadDefenseHelpers(unittest.TestCase):
    """Phase SPREAD-2: bot-local helpers
    ``is_spread_defense_move`` and
    ``_normalize_move_id_for_spread_defense`` must
    classify Wide Guard / Quick Guard / Crafty
    Shield correctly. Pure observation; no scoring
    change."""

    def test_normalize_move_id(self):
        from bot_doubles_damage_aware import (
            _normalize_move_id_for_spread_defense,
        )
        self.assertEqual(
            _normalize_move_id_for_spread_defense("Wide Guard"),
            "wideguard",
        )
        self.assertEqual(
            _normalize_move_id_for_spread_defense("quick_guard"),
            "quickguard",
        )
        self.assertEqual(
            _normalize_move_id_for_spread_defense("Crafty-Shield"),
            "craftyshield",
        )
        self.assertEqual(
            _normalize_move_id_for_spread_defense(""), ""
        )
        self.assertEqual(
            _normalize_move_id_for_spread_defense(None), ""
        )

    def test_is_spread_defense_move_true(self):
        from bot_doubles_damage_aware import is_spread_defense_move
        self.assertTrue(is_spread_defense_move("wideguard"))
        self.assertTrue(is_spread_defense_move("Wide Guard"))
        self.assertTrue(is_spread_defense_move("Quick_Guard"))
        self.assertTrue(is_spread_defense_move("crafty-shield"))

    def test_is_spread_defense_move_false(self):
        from bot_doubles_damage_aware import is_spread_defense_move
        self.assertFalse(is_spread_defense_move("protect"))
        self.assertFalse(is_spread_defense_move("rockslide"))
        self.assertFalse(is_spread_defense_move("fakeout"))
        self.assertFalse(is_spread_defense_move(""))
        self.assertFalse(is_spread_defense_move(None))


class TestAnalyzerSpreadDefenseSummary(unittest.TestCase):
    """Phase SPREAD-2: the analyzer's
    ``spread_defense_summary`` aggregates the new
    fields. The summary must surface legal and
    selected counts for Wide Guard / Quick Guard /
    Crafty Shield plus opp-pressure + opp-used
    counters.
    """

    def _run_analyzer_on_records(self, records):
        from analyze_doubles_turn_level import (
            _aggregate,
        )
        return _aggregate(records)

    def _make_record(self, **overrides):
        """Build a minimal audit record that the
        analyzer can ingest. Defaults are all
        False / 0 / empty."""
        rec = {
            "state_snapshot": {
                "turn": 1,
                "our_active_species": ["a", "b"],
                "opp_active_species": ["c", "d"],
                "our_active_hp_fraction": [1.0, 1.0],
                "opp_active_hp_fraction": [1.0, 1.0],
                "weather": None,
                "fields": [],
            },
            "benchmark_arm": "treatment",
            "player_side": "p1",
            "won": None,
            "slot_0": {},
            "slot_1": {},
            "opp_actions": {},
            # New SPREAD-2 fields (defaults):
            "wide_guard_legal_slot0": False,
            "wide_guard_legal_slot1": False,
            "quick_guard_legal_slot0": False,
            "quick_guard_legal_slot1": False,
            "crafty_shield_legal_slot0": False,
            "crafty_shield_legal_slot1": False,
            "spread_defense_selected_slot0": "",
            "spread_defense_selected_slot1": "",
            "opp_pressure_state": False,
            "opp_actions": {
                "opponent_used_spread": False,
                "opponent_used_protect": False,
                "opponent_used_wide_guard": False,
                "opponent_used_quick_guard": False,
            },
        }
        rec.update(overrides)
        return rec

    def test_summary_counts_legal_wide_guard(self):
        rec = self._make_record(wide_guard_legal_slot0=True)
        agg = self._run_analyzer_on_records([rec])
        s = agg["spread_defense_summary"]
        self.assertEqual(s["slot0_wide_guard_legal"], 1)
        self.assertEqual(s["any_slot_wide_guard_legal"], 1)
        self.assertEqual(s["slot0_wide_guard_selected"], 0)

    def test_summary_counts_selected_wide_guard(self):
        rec = self._make_record(
            wide_guard_legal_slot0=True,
            spread_defense_selected_slot0="wideguard",
        )
        agg = self._run_analyzer_on_records([rec])
        s = agg["spread_defense_summary"]
        self.assertEqual(s["slot0_wide_guard_selected"], 1)
        self.assertEqual(s["any_slot_wide_guard_selected"], 1)
        self.assertEqual(
            s["selected_by_move"]["wideguard"], 1
        )

    def test_summary_legal_not_selected(self):
        rec = self._make_record(
            wide_guard_legal_slot0=True,
            crafty_shield_legal_slot1=True,
        )
        agg = self._run_analyzer_on_records([rec])
        s = agg["spread_defense_summary"]
        self.assertEqual(s["spread_defense_legal_not_selected"], 1)

    def test_summary_opp_pressure_state(self):
        rec = self._make_record(opp_pressure_state=True)
        agg = self._run_analyzer_on_records([rec])
        s = agg["spread_defense_summary"]
        self.assertEqual(s["opp_pressure_state_turn_count"], 1)

    def test_summary_opp_used_spread(self):
        rec = self._make_record(
            opp_actions={
                "opponent_used_spread": True,
                "opponent_used_protect": False,
                "opponent_used_wide_guard": False,
                "opponent_used_quick_guard": False,
            }
        )
        agg = self._run_analyzer_on_records([rec])
        s = agg["spread_defense_summary"]
        self.assertEqual(s["opp_used_spread_turn_count"], 1)
        self.assertEqual(s["opp_used_protect_turn_count"], 0)

    def test_summary_opp_used_wide_guard(self):
        rec = self._make_record(
            opp_actions={
                "opponent_used_spread": False,
                "opponent_used_protect": False,
                "opponent_used_wide_guard": True,
                "opponent_used_quick_guard": False,
            }
        )
        agg = self._run_analyzer_on_records([rec])
        s = agg["spread_defense_summary"]
        self.assertEqual(s["opp_used_wide_guard_turn_count"], 1)

    def test_summary_legal_not_selected_false_when_selected(self):
        """When ANY spread-defense move is selected,
        ``legal_not_selected`` must NOT increment
        even if multiple are legal."""
        rec = self._make_record(
            wide_guard_legal_slot0=True,
            quick_guard_legal_slot0=True,
            crafty_shield_legal_slot1=True,
            spread_defense_selected_slot1="craftyshield",
        )
        agg = self._run_analyzer_on_records([rec])
        s = agg["spread_defense_summary"]
        self.assertEqual(s["spread_defense_legal_not_selected"], 0)
        self.assertEqual(s["slot1_crafty_shield_selected"], 1)


if __name__ == "__main__":
    unittest.main()
