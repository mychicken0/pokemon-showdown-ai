"""Phase CONTROL-1 — Tests for the read-only control
move evidence analyzer.

Validates:
- Family move mapping is correct
- _move_to_family handles spaces, dashes, underscores
- _parse_action_key returns (kind, value, target)
- _parse_selected_joint returns list of parsed keys
- _safe_turn_bucket classifies correctly
- _has_field_active detects weather/terrain/conditions
- analyze_audit_file aggregates correctly
- build_report produces valid markdown + JSON
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

from analyze_control_move_evidence import (
    CONTROL_FAMILIES,
    _move_to_family,
    _parse_action_key,
    _parse_selected_joint,
    _safe_turn_bucket,
    _has_field_active,
    _has_opp_context,
    analyze_audit_file,
    build_report,
    merge_stats,
)


class TestMoveToFamily(unittest.TestCase):
    def test_protect_is_defensive_stall(self):
        self.assertEqual(_move_to_family("protect"), "defensive_stall")

    def test_tailwind_is_speed_control(self):
        self.assertEqual(_move_to_family("tailwind"), "speed_control")

    def test_trickroom_is_speed_control(self):
        self.assertEqual(_move_to_family("trickroom"), "speed_control")

    def test_taunt_is_anti_setup(self):
        self.assertEqual(_move_to_family("taunt"), "anti_setup_disrupt")

    def test_encore_is_anti_setup(self):
        self.assertEqual(_move_to_family("encore"), "anti_setup_disrupt")

    def test_followme_is_redirection(self):
        self.assertEqual(_move_to_family("followme"), "redirection")

    def test_wideguard_is_spread_defense(self):
        self.assertEqual(_move_to_family("wideguard"), "spread_defense")

    def test_earthquake_is_not_control(self):
        self.assertIsNone(_move_to_family("earthquake"))

    def test_icywind_is_speed_control(self):
        self.assertEqual(_move_to_family("icywind"), "speed_control")

    def test_helpinghand_is_combo_support(self):
        self.assertEqual(_move_to_family("helpinghand"), "combo_support")

    def test_space_normalized(self):
        # "Follow Me" → "followme"
        self.assertEqual(_move_to_family("Follow Me"), "redirection")

    def test_dash_normalized(self):
        # "Trick-Room" → "trickroom"
        self.assertEqual(_move_to_family("Trick-Room"), "speed_control")

    def test_underscore_normalized(self):
        # "Helping_Hand" → "helpinghand"
        self.assertEqual(_move_to_family("Helping_Hand"), "combo_support")

    def test_rain_dance_is_field_control(self):
        self.assertEqual(_move_to_family("raindance"), "field_control")

    def test_light_screen_is_field_control(self):
        self.assertEqual(_move_to_family("lightscreen"), "field_control")


class TestParseActionKey(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(
            _parse_action_key("move|earthpower|1"),
            ("move", "earthpower", "1"),
        )

    def test_switch(self):
        self.assertEqual(
            _parse_action_key("switch|garchomp|0"),
            ("switch", "garchomp", "0"),
        )

    def test_invalid(self):
        self.assertIsNone(_parse_action_key("nope"))
        self.assertIsNone(_parse_action_key("a|b"))

    def test_none(self):
        self.assertIsNone(_parse_action_key(None))


class TestParseSelectedJoint(unittest.TestCase):
    def test_single(self):
        self.assertEqual(
            _parse_selected_joint("move|earthpower|1"),
            [("move", "earthpower", "1")],
        )

    def test_pair(self):
        self.assertEqual(
            _parse_selected_joint("move|earthpower|1;move|heatwave|0"),
            [("move", "earthpower", "1"), ("move", "heatwave", "0")],
        )

    def test_empty(self):
        self.assertEqual(_parse_selected_joint(""), [])
        self.assertEqual(_parse_selected_joint(None), [])


class TestSafeTurnBucket(unittest.TestCase):
    def test_early(self):
        self.assertEqual(_safe_turn_bucket(1), "early")
        self.assertEqual(_safe_turn_bucket(3), "early")

    def test_mid(self):
        self.assertEqual(_safe_turn_bucket(4), "mid")
        self.assertEqual(_safe_turn_bucket(7), "mid")

    def test_late(self):
        self.assertEqual(_safe_turn_bucket(8), "late")
        self.assertEqual(_safe_turn_bucket(20), "late")

    def test_unknown(self):
        self.assertEqual(_safe_turn_bucket(None), "unknown")


class TestHasFieldActive(unittest.TestCase):
    def test_weather(self):
        snap = {"weather": ["raindance"], "fields": []}
        self.assertTrue(_has_field_active(snap, "raindance"))

    def test_terrain(self):
        snap = {"weather": [], "fields": ["electricterrain"]}
        self.assertTrue(_has_field_active(snap, "electricterrain"))

    def test_missing(self):
        snap = {"weather": [], "fields": []}
        self.assertFalse(_has_field_active(snap, "raindance"))

    def test_none_snap(self):
        self.assertFalse(_has_field_active(None, "raindance"))


class TestHasOppContext(unittest.TestCase):
    def test_protect_detected(self):
        opp = {"opponent_used_protect": True}
        self.assertIn("opp_used_protect", _has_opp_context(opp))

    def test_empty(self):
        self.assertEqual(_has_opp_context({}), [])

    def test_multiple(self):
        opp = {
            "opponent_used_protect": True,
            "opponent_used_tailwind": True,
        }
        signals = _has_opp_context(opp)
        self.assertIn("opp_used_protect", signals)
        self.assertIn("opp_used_tailwind", signals)


class TestControlFamiliesConfig(unittest.TestCase):
    def test_all_families_present(self):
        required = {
            "defensive_stall", "speed_control",
            "anti_setup_disrupt", "field_control",
            "redirection", "spread_defense", "combo_support",
        }
        self.assertEqual(set(CONTROL_FAMILIES.keys()), required)

    def test_protect_in_defensive_stall(self):
        self.assertIn("protect", CONTROL_FAMILIES["defensive_stall"])

    def test_encore_in_anti_setup(self):
        self.assertIn("encore", CONTROL_FAMILIES["anti_setup_disrupt"])

    def test_helpinghand_in_combo_support(self):
        self.assertIn("helpinghand", CONTROL_FAMILIES["combo_support"])


class TestAnalyzeAuditFile(unittest.TestCase):
    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write("")
            path = f.name
        try:
            stats = analyze_audit_file(path)
            self.assertEqual(stats["total_turns"], 0)
            self.assertEqual(
                stats["by_family"]["anti_setup_disrupt"]["legal_count"], 0
            )
        finally:
            os.unlink(path)

    def test_one_turn_with_protect(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            rec = {
                "battle_tag": "test-battle",
                "audit_turns": [{
                    "turn": 3,
                    "state_snapshot": {"weather": [], "fields": []},
                    "opponent_actions": {},
                    "v2l1_legal_action_keys_slot0": [
                        ["move", "earthpower", "1"],
                        ["move", "protect", "0"],
                    ],
                    "v2l1_raw_scores_slot0": {
                        "move|earthpower|1": 200.0,
                        "move|protect|0": 50.0,
                    },
                    "v2l1_legal_action_keys_slot1": [],
                    "v2l1_raw_scores_slot1": {},
                    "v2l1_selected_joint_key": "move|earthpower|1;pass",
                    "selected_score": 200.0,
                }],
            }
            f.write(json.dumps(rec) + "\n")
            path = f.name
        try:
            stats = analyze_audit_file(path)
            self.assertEqual(stats["total_turns"], 1)
            self.assertEqual(
                stats["by_family"]["defensive_stall"]["legal_count"], 1
            )
            self.assertEqual(
                stats["by_family"]["defensive_stall"]["selected_count"], 0
            )
            self.assertEqual(stats["by_move"]["protect"]["legal_count"], 1)
            self.assertEqual(len(stats["control_legal_not_selected"]), 1)
        finally:
            os.unlink(path)

    def test_one_turn_with_tailwind_selected(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            rec = {
                "battle_tag": "test-battle",
                "audit_turns": [{
                    "turn": 1,
                    "state_snapshot": {"weather": [], "fields": []},
                    "opponent_actions": {},
                    "v2l1_legal_action_keys_slot0": [
                        ["move", "tailwind", "0"],
                    ],
                    "v2l1_raw_scores_slot0": {
                        "move|tailwind|0": 150.0,
                    },
                    "v2l1_legal_action_keys_slot1": [],
                    "v2l1_raw_scores_slot1": {},
                    "v2l1_selected_joint_key": "move|tailwind|0;pass",
                    "selected_score": 150.0,
                }],
            }
            f.write(json.dumps(rec) + "\n")
            path = f.name
        try:
            stats = analyze_audit_file(path)
            self.assertEqual(
                stats["by_family"]["speed_control"]["legal_count"], 1
            )
            self.assertEqual(
                stats["by_family"]["speed_control"]["selected_count"], 1
            )
            self.assertEqual(stats["by_move"]["tailwind"]["selected_count"], 1)
        finally:
            os.unlink(path)

    def test_malformed_json_skipped(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write("not json\n")
            rec = {
                "battle_tag": "test-battle",
                "audit_turns": [],
            }
            f.write(json.dumps(rec) + "\n")
            path = f.name
        try:
            stats = analyze_audit_file(path)
            self.assertEqual(stats["total_turns"], 0)
        finally:
            os.unlink(path)


class TestBuildReport(unittest.TestCase):
    def test_report_includes_decision(self):
        stats = {
            "total_turns": 100,
            "by_family": {fam: {
                "legal_count": 0, "selected_count": 0,
                "scores_when_legal": [],
                "scores_when_selected": [],
                "scores_when_not_selected": [],
                "scores_at_rank1": [],
                "ranks_when_legal": [],
            } for fam in CONTROL_FAMILIES},
            "by_move": {},
            "control_legal_not_selected": [],
            "control_legal_and_selected": [],
            "field_already_active": {},
            "opp_context_total": {},
            "turn_buckets": {"early": 50, "mid": 30, "late": 20},
            "immediate_ko_alternative": 10,
            "safety_block_on_control": 0,
        }
        md, summary = build_report(
            stats, ["fake.jsonl"], "test label"
        )
        self.assertIn("Phase CONTROL-1", md)
        self.assertIn("test label", md)
        self.assertIn("Final decision:", md)
        self.assertIn("defensive_stall", md)
        self.assertIn("anti_setup_disrupt", md)
        self.assertEqual(summary["target"], "test label")
        self.assertEqual(summary["decision"], "INSUFFICIENT_DATA")


class TestMergeStats(unittest.TestCase):
    def test_merge_increments(self):
        a = {
            "total_turns": 10,
            "by_family": {fam: {
                "legal_count": 1, "selected_count": 0,
                "scores_when_legal": [10.0],
                "scores_when_selected": [],
                "scores_when_not_selected": [10.0],
                "scores_at_rank1": [10.0],
                "ranks_when_legal": [1],
            } for fam in CONTROL_FAMILIES},
            "by_move": {},
            "control_legal_not_selected": [],
            "control_legal_and_selected": [],
            "field_already_active": {"tailwind": 2},
            "opp_context_total": {},
            "turn_buckets": {"early": 5},
            "immediate_ko_alternative": 1,
            "safety_block_on_control": 0,
        }
        b = {
            "total_turns": 5,
            "by_family": {fam: {
                "legal_count": 0, "selected_count": 0,
                "scores_when_legal": [],
                "scores_when_selected": [],
                "scores_when_not_selected": [],
                "scores_at_rank1": [],
                "ranks_when_legal": [],
            } for fam in CONTROL_FAMILIES},
            "by_move": {},
            "control_legal_not_selected": [],
            "control_legal_and_selected": [],
            "field_already_active": {"tailwind": 3, "trickroom": 1},
            "opp_context_total": {},
            "turn_buckets": {"mid": 5},
            "immediate_ko_alternative": 0,
            "safety_block_on_control": 0,
        }
        merge_stats(a, b)
        self.assertEqual(a["total_turns"], 15)
        self.assertEqual(a["field_already_active"]["tailwind"], 5)
        self.assertEqual(a["field_already_active"]["trickroom"], 1)
        self.assertEqual(a["turn_buckets"]["early"], 5)
        self.assertEqual(a["turn_buckets"]["mid"], 5)


if __name__ == "__main__":
    unittest.main()
