"""Phase CONTROL-4A — Tests for the
anti-setup disruption eligibility helper
and dry-run analyzer.

Validates:
- ANTI_SETUP_TARGETS contains exactly
  taunt/encore/disable/quash
- _norm normalizes names correctly
- _is_target_move correctly identifies
  the 4 target moves
- _has_field_active detects weather/terrain
- _target_to_slot maps VGC targets
- _opp_setup_signals computes visible
  signals only
- anti_setup_eligible applies all 5 guards
  correctly
- analyze_anti_setup_dryrun produces
  valid output
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from bot_doubles_anti_setup_eligibility import (
    ANTI_SETUP_TARGETS,
    STAT_BOOST_MOVES,
    HIGH_BP_MOVES,
    _norm,
    _is_target_move,
    _has_field_active,
    _target_to_slot,
    _opp_setup_signals,
    _bot_survives,
    _parse_legal_key,
    _has_legal_anti_setup,
    anti_setup_eligible,
)
from analyze_anti_setup_dryrun import (
    analyze_file,
    _process_turn,
    _summarize,
    _build_report,
    DEFAULT_MAGNITUDES,
)


class TestTargetMoves(unittest.TestCase):
    def test_targets_are_4_moves(self):
        self.assertEqual(
            ANTI_SETUP_TARGETS,
            frozenset({"taunt", "encore", "disable", "quash"}),
        )

    def test_targets_no_outsiders(self):
        # Wide guard, quick guard, etc. are NOT targets
        self.assertNotIn("wideguard", ANTI_SETUP_TARGETS)
        self.assertNotIn("quickguard", ANTI_SETUP_TARGETS)
        self.assertNotIn("haze", ANTI_SETUP_TARGETS)
        self.assertNotIn("torment", ANTI_SETUP_TARGETS)


class TestNormalize(unittest.TestCase):
    def test_lowercase(self):
        self.assertEqual(_norm("TAUNT"), "taunt")

    def test_no_spaces(self):
        self.assertEqual(_norm("Swords Dance"), "swordsdance")

    def test_no_dashes(self):
        self.assertEqual(_norm("Nasty-Plot"), "nastyplot")

    def test_no_underscores(self):
        self.assertEqual(_norm("Calm_Mind"), "calmmind")

    def test_no_apostrophes(self):
        self.assertEqual(_norm("King's Shield"), "kingsshield")


class TestIsTargetMove(unittest.TestCase):
    def test_taunt(self):
        self.assertTrue(_is_target_move("taunt"))

    def test_encore(self):
        self.assertTrue(_is_target_move("encore"))

    def test_disable(self):
        self.assertTrue(_is_target_move("disable"))

    def test_quash(self):
        self.assertTrue(_is_target_move("quash"))

    def test_protect_not_target(self):
        self.assertFalse(_is_target_move("protect"))

    def test_earthquake_not_target(self):
        self.assertFalse(_is_target_move("earthquake"))


class TestTargetToSlot(unittest.TestCase):
    def test_slot_0(self):
        self.assertEqual(_target_to_slot(1), 0)

    def test_slot_1(self):
        self.assertEqual(_target_to_slot(2), 1)

    def test_self(self):
        self.assertIsNone(_target_to_slot(-1))

    def test_ally(self):
        self.assertIsNone(_target_to_slot(-2))

    def test_invalid(self):
        self.assertIsNone(_target_to_slot("foo"))
        self.assertIsNone(_target_to_slot(None))


class TestHasFieldActive(unittest.TestCase):
    def test_weather(self):
        snap = {"weather": ["raindance"], "fields": []}
        self.assertTrue(_has_field_active(snap, "raindance"))

    def test_field(self):
        snap = {"weather": [], "fields": ["trickroom"]}
        self.assertTrue(_has_field_active(snap, "trickroom"))

    def test_missing(self):
        snap = {"weather": [], "fields": []}
        self.assertFalse(_has_field_active(snap, "tailwind"))

    def test_none_snap(self):
        self.assertFalse(_has_field_active(None, "tailwind"))


class TestParseLegalKey(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(
            _parse_legal_key("move|taunt|1"),
            ("move", "taunt", "1"),
        )

    def test_invalid(self):
        self.assertIsNone(_parse_legal_key("nope"))
        self.assertIsNone(_parse_legal_key(None))


class TestHasLegalAntiSetup(unittest.TestCase):
    def test_taunt_legal(self):
        legal = [["move", "earthquake", "1"],
                 ["move", "taunt", "1"]]
        result = _has_legal_anti_setup(legal)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "taunt")

    def test_no_anti_setup(self):
        legal = [["move", "earthquake", "1"]]
        self.assertIsNone(_has_legal_anti_setup(legal))

    def test_prefer_slot_0(self):
        legal = [
            ["move", "encore", "2"],
            ["move", "taunt", "1"],
        ]
        result = _has_legal_anti_setup(legal)
        # Both are anti-setup; should prefer
        # slot 0 (target=1)
        self.assertEqual(result[1], "taunt")


class TestOppSetupSignals(unittest.TestCase):
    def test_no_signals(self):
        signals = _opp_setup_signals(None, None, 0)
        self.assertEqual(signals, 0.0)

    def test_stat_boost_used(self):
        opp = {"opponent_used_stat_boost_setup": True}
        signals = _opp_setup_signals(None, opp, 0)
        self.assertEqual(signals, 1.0)

    def test_tailwind_used(self):
        opp = {"opponent_used_tailwind": True}
        signals = _opp_setup_signals(None, opp, 0)
        self.assertEqual(signals, 0.5)

    def test_field_tailwind(self):
        snap = {"weather": [], "fields": [],
                "side_conditions": ["tailwind"]}
        signals = _opp_setup_signals(snap, None, 0)
        self.assertEqual(signals, 0.5)

    def test_revealed_setup_move(self):
        # Without scoring_move: stat-boost is +1,
        # high-BP is +0 (move-aware)
        snap = {"opp_active_moves_revealed": [
            ["swordsdance", "earthquake"], []
        ]}
        signals = _opp_setup_signals(snap, None, 0)
        self.assertEqual(signals, 1.0)

    def test_revealed_high_bp_for_disable(self):
        # With scoring_move='disable': both
        # stat-boost and high-BP contribute
        snap = {"opp_active_moves_revealed": [
            ["swordsdance", "earthquake"], []
        ]}
        signals = _opp_setup_signals(
            snap, None, 0, scoring_move="disable"
        )
        self.assertEqual(signals, 2.0)

    def test_combined(self):
        opp = {"opponent_used_stat_boost_setup": True,
               "opponent_used_tailwind": True}
        snap = {"weather": [], "fields": [],
                "opp_active_moves_revealed": []}
        signals = _opp_setup_signals(snap, opp, 0)
        self.assertEqual(signals, 1.5)

    def test_ignores_our_setup(self):
        # Revealed-moves for OUR side, not opp
        snap = {"our_active_moves_revealed": [
            ["swordsdance"], []
        ]}
        signals = _opp_setup_signals(snap, None, 0)
        self.assertEqual(signals, 0.0)


class TestBotSurvives(unittest.TestCase):
    def test_high_hp(self):
        snap = {"our_active_hp_fraction": [0.8, 1.0]}
        self.assertTrue(_bot_survives(snap, 0))

    def test_low_hp(self):
        snap = {"our_active_hp_fraction": [0.1, 1.0]}
        self.assertFalse(_bot_survives(snap, 0))

    def test_no_snap_assumes_alive(self):
        self.assertTrue(_bot_survives(None, 0))


class TestAntiSetupEligible(unittest.TestCase):
    def test_no_legal(self):
        res = anti_setup_eligible(
            snap=None, opp_actions=None,
            legal_action_keys=[["move", "earthquake", "1"]],
            selected_score=100.0,
        )
        self.assertFalse(res["eligible"])
        self.assertEqual(res["reason"], "no_legal")

    def test_target_invalid(self):
        # target=-1 is self, not valid. The
        # _has_legal_anti_setup filter strips
        # non-opp targets, so result is
        # "no_legal" (no opp-targeted anti-setup
        # move).
        res = anti_setup_eligible(
            snap=None, opp_actions=None,
            legal_action_keys=[["move", "taunt", "-1"]],
            selected_score=100.0,
        )
        self.assertFalse(res["eligible"])
        self.assertEqual(res["reason"], "no_legal")

    def test_no_survival(self):
        snap = {"our_active_hp_fraction": [0.1, 1.0]}
        opp = {"opponent_used_stat_boost_setup": True}
        res = anti_setup_eligible(
            snap=snap, opp_actions=opp,
            legal_action_keys=[["move", "taunt", "1"]],
            selected_score=100.0,
        )
        self.assertFalse(res["eligible"])
        self.assertEqual(res["reason"], "no_survival")

    def test_no_signal(self):
        opp = {}  # no signals
        res = anti_setup_eligible(
            snap=None, opp_actions=opp,
            legal_action_keys=[["move", "taunt", "1"]],
            selected_score=100.0,
        )
        self.assertFalse(res["eligible"])
        self.assertEqual(res["reason"], "no_signal")

    def test_signal_present(self):
        opp = {"opponent_used_stat_boost_setup": True}
        res = anti_setup_eligible(
            snap=None, opp_actions=opp,
            legal_action_keys=[["move", "taunt", "1"]],
            selected_score=100.0,
        )
        self.assertTrue(res["eligible"])
        self.assertEqual(res["reason"], "ok")
        self.assertEqual(res["signal"], 1.0)
        self.assertEqual(res["target_slot"], 0)
        self.assertEqual(res["move"], "taunt")

    def test_spam_cap(self):
        opp = {"opponent_used_stat_boost_setup": True}
        res = anti_setup_eligible(
            snap=None, opp_actions=opp,
            legal_action_keys=[["move", "taunt", "1"]],
            selected_score=100.0,
            picks_used=2,  # already at cap
            max_picks_per_game=2,
        )
        self.assertFalse(res["eligible"])
        self.assertEqual(res["reason"], "spam_cap")

    def test_spam_gap(self):
        opp = {"opponent_used_stat_boost_setup": True}
        res = anti_setup_eligible(
            snap=None, opp_actions=opp,
            legal_action_keys=[["move", "taunt", "1"]],
            selected_score=100.0,
            picks_used=1,
            last_pick_turn=2,
            current_turn=3,
            min_turn_between=3,
        )
        self.assertFalse(res["eligible"])
        self.assertEqual(res["reason"], "spam_gap")

    def test_threshold_2_no_fire(self):
        # Only 1 signal, threshold 2
        opp = {"opponent_used_stat_boost_setup": True}
        res = anti_setup_eligible(
            snap=None, opp_actions=opp,
            legal_action_keys=[["move", "taunt", "1"]],
            selected_score=100.0,
            min_opp_setup_signal=2.0,
        )
        self.assertFalse(res["eligible"])
        self.assertEqual(res["reason"], "no_signal")

    def test_threshold_2_fires(self):
        # 2.0 signals, threshold 2.0
        # stat-boost (1.0) + tailwind used (0.5)
        # + tailwind field (0.5) = 2.0
        opp = {"opponent_used_stat_boost_setup": True,
               "opponent_used_tailwind": True}
        snap = {"weather": [], "fields": [],
                "side_conditions": ["tailwind"],
                "opp_active_moves_revealed": []}
        # Use the eligibility path directly
        from bot_doubles_anti_setup_eligibility import (
            _opp_setup_signals, anti_setup_eligible,
        )
        sig = _opp_setup_signals(snap, opp, 0)
        # Should be 2.0 (1.0 + 0.5 + 0.5)
        self.assertEqual(sig, 2.0)
        res = anti_setup_eligible(
            snap=snap, opp_actions=opp,
            legal_action_keys=[["move", "taunt", "1"]],
            selected_score=100.0,
            min_opp_setup_signal=2.0,
        )
        self.assertTrue(res["eligible"])


class TestAnalyzeFile(unittest.TestCase):
    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write("")
            path = f.name
        try:
            result = analyze_file(path, [200.0], 1.0)
            self.assertEqual(len(result), 0)
        finally:
            os.unlink(path)

    def test_turn_with_taunt_legal(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            rec = {
                "battle_tag": "test",
                "audit_turns": [{
                    "turn": 3,
                    "state_snapshot": {"weather": [], "fields": []},
                    "opponent_actions": {
                        "opponent_used_stat_boost_setup": True,
                    },
                    "v2l1_legal_action_keys_slot0": [
                        ["move", "earthquake", "1"],
                        ["move", "taunt", "1"],
                    ],
                    "v2l1_raw_scores_slot0": {
                        "move|earthquake|1": 200.0,
                        "move|taunt|1": 0.0,
                    },
                    "v2l1_legal_action_keys_slot1": [],
                    "v2l1_raw_scores_slot1": {},
                    "selected_score": 200.0,
                    "best_ko_score": 200.0,
                }],
            }
            f.write(json.dumps(rec) + "\n")
            path = f.name
        try:
            result = analyze_file(path, [200.0], 1.0)
            self.assertEqual(len(result), 1)
            slot = result[0]["slots"][0]
            self.assertEqual(slot["move"], "taunt")
            # At +200, taunt = 0 + 200 = 200, equal
            # to selected (200), so no flip
            per_mag = slot["per_magnitude"][200.0]
            self.assertFalse(per_mag["would_flip"])
        finally:
            os.unlink(path)

    def test_turn_with_taunt_would_flip(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            rec = {
                "battle_tag": "test",
                "audit_turns": [{
                    "turn": 3,
                    "state_snapshot": {"weather": [], "fields": []},
                    "opponent_actions": {
                        "opponent_used_stat_boost_setup": True,
                    },
                    "v2l1_legal_action_keys_slot0": [
                        ["move", "earthquake", "1"],
                        ["move", "taunt", "1"],
                    ],
                    "v2l1_raw_scores_slot0": {
                        "move|earthquake|1": 100.0,
                        "move|taunt|1": 0.0,
                    },
                    "selected_score": 100.0,
                    "best_ko_score": 100.0,
                }],
            }
            f.write(json.dumps(rec) + "\n")
            path = f.name
        try:
            result = analyze_file(path, [200.0], 1.0)
            slot = result[0]["slots"][0]
            per_mag = slot["per_magnitude"][200.0]
            # Taunt score: 0 + 200 = 200, > selected 100
            self.assertTrue(per_mag["would_flip"])
            # best_ko = 100, but new_score = 200
            # (best_ko - new_score = -100, < -50)
            # so NOT over_flip (over_flip would mean
            # best_ko is close to new_score)
            # Actually check: (best_ko - new_score) > -50
            # means best_ko is within 50 of new_score
            # Here best_ko=100, new_score=200, diff=-100
            # -100 > -50 is False, so NOT over_flip
            self.assertFalse(per_mag["over_flip"])
        finally:
            os.unlink(path)


class TestBuildReport(unittest.TestCase):
    def test_report_includes_decision(self):
        summary = {
            "total_turns": 100,
            "per_magnitude": {
                200.0: {
                    "eligible": 5, "flip": 2, "over_flip": 0,
                    "no_flip": 3, "no_signal": 50,
                    "no_legal": 45,
                },
            },
            "by_class": {},
            "by_move": {"taunt": {
                "legal": 10, "eligible": 5, "signals": [1.0],
            }},
        }
        md = _build_report(
            summary, [200.0], ["fake.jsonl"], "test"
        )
        self.assertIn("Phase CONTROL-4A", md)
        self.assertIn("Chosen magnitude: +200", md)
        self.assertIn("test", md)
        self.assertIn("Flip rate", md)


if __name__ == "__main__":
    unittest.main()
