"""Phase SPREAD-4 — Tests for the new spread-defense
score-gap audit fields. Mirrors the SPREAD-2 fixture
pattern from
``test_doubles_spread2_audit_wiring.py``.

New audit fields tested:
- ``wide_guard_score`` (per slot)
- ``quick_guard_score`` (per slot)
- ``crafty_shield_score`` (per slot)
- ``score_gap_wide_guard_vs_selected`` (top level)
- ``score_gap_quick_guard_vs_selected`` (top level)

No scoring change in the bot. Pure observation.
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
    selected_score=100.0,
    # SPREAD-4 fields:
    wide_guard_score=(None, None),
    quick_guard_score=(None, None),
    crafty_shield_score=(None, None),
    score_gap_wide_guard_vs_selected=(None, None),
    score_gap_quick_guard_vs_selected=(None, None),
):
    return dict(
        battle_tag="test-battle-1",
        turn=1,
        battle=battle,
        selected_joint_order=selected_joint_order,
        selected_score=selected_score,
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
        wide_guard_legal=[False, False],
        quick_guard_legal=[False, False],
        crafty_shield_legal=[False, False],
        spread_defense_selected=("", ""),
        opp_pressure_state=False,
        # SPREAD-4 fields:
        wide_guard_score=wide_guard_score,
        quick_guard_score=quick_guard_score,
        crafty_shield_score=crafty_shield_score,
        score_gap_wide_guard_vs_selected=(
            score_gap_wide_guard_vs_selected
        ),
        score_gap_quick_guard_vs_selected=(
            score_gap_quick_guard_vs_selected
        ),
    )


class TestLoggerAcceptsSPREAD4Fields(unittest.TestCase):
    """The logger must accept the SPREAD-4 fields
    without raising TypeError and persist them."""

    def test_logger_accepts_wide_guard_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            logger.log_turn_decision(
                **_build_kwargs(
                    battle,
                    wide_guard_score=(120.5, None),
                )
            )
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            self.assertEqual(t["slot_0"]["wide_guard_score"], 120.5)
            self.assertIsNone(t["slot_1"]["wide_guard_score"])

    def test_logger_accepts_quick_guard_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            logger.log_turn_decision(
                **_build_kwargs(
                    battle,
                    quick_guard_score=(None, 95.0),
                )
            )
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            self.assertIsNone(t["slot_0"]["quick_guard_score"])
            self.assertEqual(t["slot_1"]["quick_guard_score"], 95.0)

    def test_logger_accepts_crafty_shield_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            logger.log_turn_decision(
                **_build_kwargs(
                    battle,
                    crafty_shield_score=(80.0, 80.0),
                )
            )
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            self.assertEqual(t["slot_0"]["crafty_shield_score"], 80.0)
            self.assertEqual(t["slot_1"]["crafty_shield_score"], 80.0)

    def test_logger_persists_score_gap_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            logger.log_turn_decision(
                **_build_kwargs(
                    battle,
                    score_gap_wide_guard_vs_selected=(-45.5, -90.0),
                    score_gap_quick_guard_vs_selected=(-100.0, None),
                )
            )
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            self.assertIn("score_gap_wide_guard_vs_selected", t)
            self.assertEqual(
                t["score_gap_wide_guard_vs_selected"], [-45.5, -90.0]
            )
            self.assertEqual(
                t["score_gap_quick_guard_vs_selected"], [-100.0, None]
            )

    def test_logger_defaults_for_missing_score_gap(self):
        """When score-gap lists are omitted, the
        logger should NOT persist them (backward
        compat)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            kwargs = _build_kwargs(battle)
            for k in (
                "wide_guard_score",
                "quick_guard_score",
                "crafty_shield_score",
                "score_gap_wide_guard_vs_selected",
                "score_gap_quick_guard_vs_selected",
            ):
                kwargs.pop(k, None)
            logger.log_turn_decision(**kwargs)
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            self.assertNotIn("score_gap_wide_guard_vs_selected", t)
            self.assertNotIn("score_gap_quick_guard_vs_selected", t)


class TestBotSpreadDefenseScoreHelpers(unittest.TestCase):
    """Phase SPREAD-4: the bot-local helpers
    should classify Wide Guard / Quick Guard /
    Crafty Shield correctly. The score-extraction
    code lives in choose_move. The helper we
    test here is the same one used in SPREAD-2."""

    def test_normalize_wg_qg_cs(self):
        from bot_doubles_damage_aware import (
            _normalize_move_id_for_spread_defense,
        )
        for s in (
            "Wide Guard", "wide_guard", "WIDE-GUARD",
            "Quick Guard", "quickguard",
            "Crafty Shield", "craftyshield",
        ):
            n = _normalize_move_id_for_spread_defense(s)
            self.assertIn(
                n,
                {"wideguard", "quickguard", "craftyshield"},
            )


class TestAnalyzerSPREAD4Summary(unittest.TestCase):
    """Phase SPREAD-4: the analyzer's
    ``spread_defense_summary.score_gap_wg_*``
    fields correctly summarize the score-gap
    distribution."""

    def _make_record(self, **overrides):
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
            "wide_guard_legal_slot0": False,
            "wide_guard_legal_slot1": False,
            "quick_guard_legal_slot0": False,
            "quick_guard_legal_slot1": False,
            "crafty_shield_legal_slot0": False,
            "crafty_shield_legal_slot1": False,
            "spread_defense_selected_slot0": "",
            "spread_defense_selected_slot1": "",
            "opp_pressure_state": False,
            "score_gap_wide_guard_vs_selected": [],
            "score_gap_quick_guard_vs_selected": [],
        }
        rec.update(overrides)
        return rec

    def test_summary_collects_score_gaps(self):
        rec = self._make_record(
            wide_guard_legal_slot0=True,
            score_gap_wide_guard_vs_selected=[-50.0, -100.0],
        )
        from analyze_doubles_turn_level import _aggregate
        agg = _aggregate([rec])
        s = agg["spread_defense_summary"]
        self.assertEqual(
            s["score_gap_wg_legal_not_selected_count"], 2
        )
        self.assertEqual(
            s["score_gap_wg_legal_not_selected_min"], -100.0
        )
        self.assertEqual(
            s["score_gap_wg_legal_not_selected_max"], -50.0
        )
        self.assertEqual(
            s["score_gap_wg_legal_not_selected_mean"], -75.0
        )

    def test_summary_skips_when_wg_not_legal(self):
        """When WG is not legal, score-gap should
        NOT be collected even if the gap list is
        non-empty."""
        rec = self._make_record(
            wide_guard_legal_slot0=False,
            score_gap_wide_guard_vs_selected=[-100.0],
        )
        from analyze_doubles_turn_level import _aggregate
        agg = _aggregate([rec])
        s = agg["spread_defense_summary"]
        self.assertEqual(
            s["score_gap_wg_legal_not_selected_count"], 0
        )

    def test_summary_skips_when_wg_selected(self):
        """When WG is legal AND selected, the gap
        should NOT enter the counterfactual list
        (it's a successful selection, not a missed
        one)."""
        rec = self._make_record(
            wide_guard_legal_slot0=True,
            spread_defense_selected_slot0="wideguard",
            score_gap_wide_guard_vs_selected=[100.0],
        )
        from analyze_doubles_turn_level import _aggregate
        agg = _aggregate([rec])
        s = agg["spread_defense_summary"]
        self.assertEqual(
            s["score_gap_wg_legal_not_selected_count"], 0
        )

    def test_summary_separates_pressure_subgroup(self):
        """Gaps in opp_pressure=True turns are
        tracked separately."""
        rec_p = self._make_record(
            wide_guard_legal_slot0=True,
            opp_pressure_state=True,
            score_gap_wide_guard_vs_selected=[-40.0],
        )
        rec_no = self._make_record(
            wide_guard_legal_slot0=True,
            opp_pressure_state=False,
            score_gap_wide_guard_vs_selected=[-200.0],
        )
        from analyze_doubles_turn_level import _aggregate
        agg = _aggregate([rec_p, rec_no])
        s = agg["spread_defense_summary"]
        self.assertEqual(
            s["score_gap_wg_legal_not_selected_count"], 2
        )
        self.assertEqual(
            s["score_gap_wg_legal_not_selected_with_pressure_count"],
            1,
        )
        self.assertEqual(
            s["score_gap_wg_legal_not_selected_with_pressure"][0],
            -40.0,
        )


if __name__ == "__main__":
    unittest.main()
