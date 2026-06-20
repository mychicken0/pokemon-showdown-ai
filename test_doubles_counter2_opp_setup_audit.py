"""Phase COUNTER-2 — Tests for the new opponent
setup / combo counterplay audit fields.

Mirrors the SPREAD-2/SPREAD-4/SPREAD-5 fixture
pattern.

New audit fields tested:

- ``opp_actions.opponent_used_tailwind``
- ``opp_actions.opponent_used_trickroom``
- ``opp_actions.opponent_used_followme``
- ``opp_actions.opponent_used_ragepowder``
- ``opp_actions.opponent_used_fakeout``
- ``opp_actions.opponent_used_encore``
- ``opp_actions.opponent_used_taunt``
- ``opp_actions.opponent_used_quash``
- ``opp_actions.opponent_used_stat_boost_setup``
- ``opp_actions.opponent_used_screen_setup``
- ``opp_actions.opponent_used_ally_activation_move``
- ``opp_actions.opponent_used_absorb_redirect_ally``

Plus ``opp_setup_summary`` block in the analyzer.

Pure observation; no scoring change.
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


def _make_battle_with_replay(player_role, replay_lines):
    """Build a MagicMock battle with ``_replay_data``
    set to a list of ``[msg, ...]`` rows.

    The logger's ``update_previous_turn`` reads
    ``battle._replay_data`` to resolve the previous
    turn's outcome. It expects rows formatted as
    ``['turn', 'N']``, ``['move', '<slot>', '<name>']``,
    ``['-ability', '<slot>', '<ability>', ...]``,
    etc. — i.e. the raw Showdown protocol lines.
    """
    battle = MagicMock()
    battle.active_pokemon = []
    battle.opponent_active_pokemon = []
    battle.available_switches = []
    battle.force_switch = [False, False]
    battle.opponent_side_conditions = {}
    battle.side_conditions = {}
    battle.weather = None
    battle.fields = set()
    battle.player_role = player_role
    battle._replay_data = list(replay_lines)
    battle.player_username = "p1"
    return battle


def _build_kwargs():
    return dict(
        battle_tag="test-battle-1",
        turn=1,  # match the |turn|1| marker in replay data
        selected_joint_order="/choose move tackle 1",
        selected_score=100.0,
        scored_joint_orders=[],
        expected_damages=(0.0, 0.0),
        expected_kos=(False, False),
        target_hps=(1.0, 1.0),
        overkill_triggered=False,
        focus_fire_triggered=False,
        ally_hit_penalty_triggered=False,
        spread_available=[False, False],
        best_spread_score=[None, None],
        best_ko_score=[None, None],
        low_hp_opponent_existed=False,
        low_hp_opponent_targeted=False,
        slot_actions=("", ""),
        slot_action_types=(
            {"damaging": True, "status": False},
            {"damaging": True, "status": False},
        ),
        target_species=("", ""),
    )


def _drive_audit(player_role, replay_lines):
    """Build logger, log turn 1, then resolve
    turn 1 outcome via update_previous_turn."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "audit.jsonl")
        logger = _make_logger(path)
        battle = _make_battle_with_replay(player_role, replay_lines)
        logger.log_turn_decision(battle=battle, **_build_kwargs())
        logger.update_previous_turn("test-battle-1", battle)
        logger.save_battle("test-battle-1", "bot", battle)
        with open(path) as f:
            return json.loads(f.readline())


class TestCOUNTER2FieldsPersist(unittest.TestCase):
    """The logger must set the new opp_actions
    fields correctly when the corresponding move /
    ability appears in the replay data.
    """

    def test_tailwind_detection(self):
        record = _drive_audit(
            player_role="p1",
            replay_lines=[
                ["turn", "1"],
                ["move", "p2a: Whimsicott", "Tailwind"],
            ],
        )
        opp = record["audit_turns"][0]["opp_actions"]
        self.assertTrue(opp["opponent_used_tailwind"])
        self.assertFalse(opp["opponent_used_trickroom"])
        self.assertFalse(opp["opponent_used_followme"])

    def test_trickroom_detection(self):
        record = _drive_audit(
            player_role="p1",
            replay_lines=[
                ["turn", "1"],
                ["move", "p2a: Porygon2", "Trick Room"],
            ],
        )
        opp = record["audit_turns"][0]["opp_actions"]
        self.assertTrue(opp["opponent_used_trickroom"])
        self.assertFalse(opp["opponent_used_tailwind"])

    def test_fakeout_detection(self):
        """Fake Out is priority AND fakeout-specific."""
        record = _drive_audit(
            player_role="p1",
            replay_lines=[
                ["turn", "1"],
                ["move", "p2a: Incineroar", "Fake Out", "p1a"],
            ],
        )
        opp = record["audit_turns"][0]["opp_actions"]
        self.assertTrue(opp["opponent_used_fakeout"])
        self.assertTrue(opp["opponent_used_priority"])

    def test_followme_ragepowder_detection(self):
        record = _drive_audit(
            player_role="p1",
            replay_lines=[
                ["turn", "1"],
                ["move", "p2a: Amoonguss", "Follow Me"],
                ["move", "p2b: Togekiss", "Rage Powder"],
            ],
        )
        opp = record["audit_turns"][0]["opp_actions"]
        self.assertTrue(opp["opponent_used_followme"])
        self.assertTrue(opp["opponent_used_ragepowder"])

    def test_encore_taunt_quash_detection(self):
        record = _drive_audit(
            player_role="p1",
            replay_lines=[
                ["turn", "1"],
                ["move", "p2a: Tornadus", "Encore", "p1a"],
                ["move", "p2b: Crobat", "Taunt", "p1a"],
                ["move", "p2a: Murkrow", "Quash", "p1a"],
            ],
        )
        opp = record["audit_turns"][0]["opp_actions"]
        self.assertTrue(opp["opponent_used_encore"])
        self.assertTrue(opp["opponent_used_taunt"])
        self.assertTrue(opp["opponent_used_quash"])

    def test_swordsdance_detection(self):
        """Swords Dance should set stat_boost_setup."""
        record = _drive_audit(
            player_role="p1",
            replay_lines=[
                ["turn", "1"],
                ["move", "p2a: Garchomp", "Swords Dance"],
            ],
        )
        opp = record["audit_turns"][0]["opp_actions"]
        self.assertTrue(opp["opponent_used_stat_boost_setup"])

    def test_nastyplot_calmmind_detection(self):
        record = _drive_audit(
            player_role="p1",
            replay_lines=[
                ["turn", "1"],
                ["move", "p2a: Indeedee", "Calm Mind"],
                ["move", "p2b: Hatterene", "Nasty Plot"],
            ],
        )
        opp = record["audit_turns"][0]["opp_actions"]
        self.assertTrue(opp["opponent_used_stat_boost_setup"])

    def test_reflect_screen_detection(self):
        record = _drive_audit(
            player_role="p1",
            replay_lines=[
                ["turn", "1"],
                ["move", "p2a: Grimmsnarl", "Reflect"],
            ],
        )
        opp = record["audit_turns"][0]["opp_actions"]
        self.assertTrue(opp["opponent_used_screen_setup"])

    def test_lightscreen_auroraveil_detection(self):
        record = _drive_audit(
            player_role="p1",
            replay_lines=[
                ["turn", "1"],
                ["move", "p2a: Grimmsnarl", "Light Screen"],
                ["move", "p2b: Alcremie", "Aurora Veil"],
            ],
        )
        opp = record["audit_turns"][0]["opp_actions"]
        self.assertTrue(opp["opponent_used_screen_setup"])

    def test_beatup_detection(self):
        record = _drive_audit(
            player_role="p1",
            replay_lines=[
                ["turn", "1"],
                ["move", "p2a: Houndour", "Beat Up", "p1a"],
            ],
        )
        opp = record["audit_turns"][0]["opp_actions"]
        self.assertTrue(opp["opponent_used_ally_activation_move"])

    def test_lightning_rod_ability_activation(self):
        """-ability events for Lightning Rod / Storm
        Drain / Water Absorb / Flash Fire / Sap
        Sipper should set
        ``opponent_used_absorb_redirect_ally``."""
        record = _drive_audit(
            player_role="p1",
            replay_lines=[
                ["turn", "1"],
                [
                    "-ability",
                    "p2a: Togedemaru",
                    "Lightning Rod",
                    "boost",
                ],
            ],
        )
        opp = record["audit_turns"][0]["opp_actions"]
        self.assertTrue(opp["opponent_used_absorb_redirect_ally"])

    def test_stormdrain_ability_activation(self):
        record = _drive_audit(
            player_role="p1",
            replay_lines=[
                ["turn", "1"],
                ["-ability", "p2a: Gastrodon", "Storm Drain", "boost"],
            ],
        )
        opp = record["audit_turns"][0]["opp_actions"]
        self.assertTrue(opp["opponent_used_absorb_redirect_ally"])

    def test_default_values(self):
        """When no opp setup events occur, all
        new fields should be False."""
        record = _drive_audit(
            player_role="p1",
            replay_lines=[
                ["turn", "1"],
                ["move", "p2a: Charizard", "Heat Wave"],
            ],
        )
        opp = record["audit_turns"][0]["opp_actions"]
        for fld in (
            "opponent_used_tailwind",
            "opponent_used_trickroom",
            "opponent_used_followme",
            "opponent_used_ragepowder",
            "opponent_used_fakeout",
            "opponent_used_encore",
            "opponent_used_taunt",
            "opponent_used_quash",
            "opponent_used_stat_boost_setup",
            "opponent_used_screen_setup",
            "opponent_used_ally_activation_move",
            "opponent_used_absorb_redirect_ally",
        ):
            self.assertIn(fld, opp)
            self.assertFalse(opp[fld])


class TestAnalyzerCOUNTER2Summary(unittest.TestCase):
    """Phase COUNTER-2: the analyzer's
    ``opp_setup_summary`` correctly aggregates
    per-turn opp actions into per-move and
    per-category counts.
    """

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
            # SPREAD-2 fields (carried through):
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
        # COUNTER-2 fields go INSIDE ``opp_actions``
        # because the analyzer reads them from there
        # (matches the JSONL layout produced by
        # the audit logger).
        if overrides:
            rec["opp_actions"] = dict(overrides)
        return rec

    def test_tailwind_tr_turn_count(self):
        rec = self._make_record(opponent_used_tailwind=True)
        from analyze_doubles_turn_level import _aggregate
        agg = _aggregate([rec])
        s = agg["opp_setup_summary"]
        self.assertEqual(s["opp_used_tailwind_turn_count"], 1)
        self.assertEqual(s["speed_setup_total"], 1)
        # Other categories zero.
        self.assertEqual(s["redirection_setup_total"], 0)
        self.assertEqual(s["tempo_disruption_total"], 0)

    def test_trickroom_and_tailwind(self):
        rec = self._make_record(
            opponent_used_tailwind=True,
            opponent_used_trickroom=True,
        )
        from analyze_doubles_turn_level import _aggregate
        agg = _aggregate([rec])
        s = agg["opp_setup_summary"]
        self.assertEqual(s["opp_used_tailwind_turn_count"], 1)
        self.assertEqual(s["opp_used_trickroom_turn_count"], 1)
        # Both speed_setup: total = 2.
        self.assertEqual(s["speed_setup_total"], 2)

    def test_fakeout_tempo_disruption(self):
        rec = self._make_record(opponent_used_fakeout=True)
        from analyze_doubles_turn_level import _aggregate
        agg = _aggregate([rec])
        s = agg["opp_setup_summary"]
        self.assertEqual(s["opp_used_fakeout_turn_count"], 1)
        self.assertEqual(s["tempo_disruption_total"], 1)

    def test_followme_redirection(self):
        rec = self._make_record(opponent_used_followme=True)
        from analyze_doubles_turn_level import _aggregate
        agg = _aggregate([rec])
        s = agg["opp_setup_summary"]
        self.assertEqual(s["opp_used_followme_turn_count"], 1)
        self.assertEqual(s["redirection_setup_total"], 1)

    def test_swordsdance_stat_boost(self):
        rec = self._make_record(opponent_used_stat_boost_setup=True)
        from analyze_doubles_turn_level import _aggregate
        agg = _aggregate([rec])
        s = agg["opp_setup_summary"]
        self.assertEqual(s["opp_used_stat_boost_setup_turn_count"], 1)
        self.assertEqual(s["stat_boost_setup_total"], 1)

    def test_lightningrod_partner_absorb_redirect(self):
        rec = self._make_record(
            opponent_used_absorb_redirect_ally=True
        )
        from analyze_doubles_turn_level import _aggregate
        agg = _aggregate([rec])
        s = agg["opp_setup_summary"]
        self.assertEqual(
            s["opp_used_absorb_redirect_ally_turn_count"], 1
        )
        self.assertEqual(s["partner_absorb_redirect_total"], 1)

    def test_multiple_categories_one_turn(self):
        """A turn can fire multiple categories
        (e.g. opp uses Tailwind + Encore in same
        turn). Verify all counters increment
        independently."""
        rec = self._make_record(
            opponent_used_tailwind=True,
            opponent_used_encore=True,
            opponent_used_followme=True,
            opponent_used_stat_boost_setup=True,
        )
        from analyze_doubles_turn_level import _aggregate
        agg = _aggregate([rec])
        s = agg["opp_setup_summary"]
        self.assertEqual(s["speed_setup_total"], 1)
        self.assertEqual(s["tempo_disruption_total"], 1)
        self.assertEqual(s["redirection_setup_total"], 1)
        self.assertEqual(s["stat_boost_setup_total"], 1)
        self.assertEqual(
            s["opp_used_tailwind_turn_count"]
            + s["opp_used_encore_turn_count"]
            + s["opp_used_followme_turn_count"]
            + s["opp_used_stat_boost_setup_turn_count"],
            4,
        )

    def test_no_setup_events(self):
        rec = self._make_record()
        from analyze_doubles_turn_level import _aggregate
        agg = _aggregate([rec])
        s = agg["opp_setup_summary"]
        # All counters should be 0.
        for k, v in s.items():
            self.assertEqual(v, 0, f"{k} expected 0, got {v}")


if __name__ == "__main__":
    unittest.main()
