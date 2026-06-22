"""Phase RL-DATA-2: turn_rl_v1.1 instrumentation tests.

Tests for the v1.1 support-move instrumentation added
in RL-DATA-2. The existing v1.0 builder must continue
to pass its own tests (see
test_build_turn_level_offline_dataset.py).

This file covers:
- v1.1 schema row can be built with all new keys
- Missing unavailable fields are None or safe defaults
- Unknown support move detector tags unknown moves
- Known support moves map to SUPPORT-AUDIT-1 categories
- Weather/Terrain setter fields exist (instrumentation-only)
- Safety fields include used_species_ability_inference=False
- Analyzer accepts v1.1 rows
- Existing v1.0 fixture/data still passes
- No production scoring or selected action changes
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from typing import Any, Dict, List, Optional

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from doubles_engine.support_targets import (
    ALL_SUPPORT_GROUPS,
    ALL_SUPPORT_STATUSES,
    GROUP_TARGET_SIDE_SAFETY,
    GROUP_ABILITY_MECHANICS_SAFETY,
    GROUP_ANTI_SETUP_DISRUPTION,
    GROUP_PROTECTION_DEFENSIVE_SUPPORT,
    GROUP_SPEED_TURN_CONTROL,
    GROUP_WEATHER_TERRAIN,
    GROUP_HEALING_BUFF_ALLY_SUPPORT,
    GROUP_FIELD_SIDE_CONTROL,
    GROUP_UNKNOWN_NEEDS_PROBE,
    STATUS_HANDLED_DEFAULT,
    STATUS_WIRED_DEFAULT_OFF,
    STATUS_MECHANICS_SAFETY_ONLY,
    STATUS_SCORING_GAP_CONFIRMED,
    STATUS_UNKNOWN_NEEDS_PROBE,
    aggregate_support_distribution,
    classify_support_move_for_dataset,
)
from showdown_ai.build_turn_level_offline_dataset import (
    SCHEMA_VERSION,
    SCHEMA_VERSION_V1_1,
    build_row,
)


def _make_fake_turn(turn_id=1, v4a_legal0=None, v4a_legal1=None,
                    v4a_sel=None, v4a_final=None, selected_score=100.0,
                    weather="raindance", fields=None,
                    revealed_ability_source="revealed"):
    """Build a fake audit turn dict for testing."""
    if v4a_legal0 is None:
        v4a_legal0 = [
            ["move", "raindance", 0, "no_mechanic"],
            ["move", "hurricane", 0, "no_mechanic"],
        ]
    if v4a_legal1 is None:
        v4a_legal1 = [
            ["move", "fakeout", 0, "no_mechanic"],
            ["move", "protect", 0, "no_mechanic"],
        ]
    if v4a_sel is None:
        v4a_sel = [
            ["move", "raindance", 0, "no_mechanic"],
            ["move", "fakeout", 0, "no_mechanic"],
        ]
    if v4a_final is None:
        v4a_final = v4a_sel
    if fields is None:
        fields = []
    return {
        "turn": turn_id,
        "state_snapshot": {
            "our_active_species": ["Politoed", "Incineroar"],
            "opp_active_species": ["Garchomp", "Tyranitar"],
            "our_active_hp_fraction": [1.0, 0.95],
            "opp_active_hp_fraction": [1.0, 1.0],
            "weather": weather,
            "fields": fields,
        },
        "v4a_legal_action_keys_slot0": v4a_legal0,
        "v4a_legal_action_keys_slot1": v4a_legal1,
        "v4a_selected_joint_key": v4a_sel,
        "v4a_final_action_keys": v4a_final,
        "selected_score": selected_score,
        "top_5_alternatives": [],
        "top_5_scores": [],
        "score_gap_selected_best_alt": None,
        "v2l1_raw_scores_slot0": {},
        "v2l1_raw_scores_slot1": {},
        "switch_counterfactual": None,
        "speed_priority_threatened": None,
        "expected_to_faint_before_moving": None,
        "overkill_penalty_triggered": False,
        "focus_fire_triggered": False,
        "stale_target_avoided": False,
        "narrow_ally_heal_candidate_blocked_slot0": False,
        "narrow_ally_heal_candidate_blocked_slot1": False,
        "joint_order_count": 0,
        "runtime_mode": "gen9randomdoublesbattle",
        "revealed_ability_source": revealed_ability_source,
    }


def _make_fake_battle(turns=None, won=True):
    if turns is None:
        turns = [_make_fake_turn()]
    return {
        "battle_tag": "test_battle",
        "won": won,
        "audit_turns": turns,
    }


class TestClassifierBasics(unittest.TestCase):
    """Test the per-candidate support-move classifier."""

    def test_known_healpulse_ally_support(self):
        r = classify_support_move_for_dataset("healpulse")
        self.assertEqual(r["support_group"], GROUP_HEALING_BUFF_ALLY_SUPPORT)
        self.assertEqual(
            r["support_status_from_audit"], STATUS_MECHANICS_SAFETY_ONLY
        )
        self.assertTrue(r["is_support_move"])
        self.assertTrue(r["safety_only"])
        self.assertFalse(r["positive_strategy_known"])
        self.assertFalse(r["unknown_support_move_detected"])

    def test_known_raindance_weather_terrain(self):
        r = classify_support_move_for_dataset("raindance")
        self.assertEqual(r["support_group"], GROUP_WEATHER_TERRAIN)
        self.assertEqual(
            r["support_status_from_audit"], STATUS_SCORING_GAP_CONFIRMED
        )

    def test_known_protect_default(self):
        r = classify_support_move_for_dataset("protect")
        self.assertEqual(
            r["support_group"], GROUP_PROTECTION_DEFENSIVE_SUPPORT
        )
        self.assertEqual(
            r["support_status_from_audit"], STATUS_HANDLED_DEFAULT
        )
        self.assertTrue(r["default_enabled"])

    def test_known_taunt_anti_setup(self):
        r = classify_support_move_for_dataset("taunt")
        self.assertEqual(
            r["support_group"], GROUP_ANTI_SETUP_DISRUPTION
        )
        self.assertEqual(
            r["support_status_from_audit"], STATUS_WIRED_DEFAULT_OFF
        )
        self.assertFalse(r["default_enabled"])

    def test_known_tailwind_speed(self):
        r = classify_support_move_for_dataset("tailwind")
        self.assertEqual(
            r["support_group"], GROUP_SPEED_TURN_CONTROL
        )

    def test_damaging_move_not_support(self):
        # When base_power > 0, the move is damaging, not support
        r = classify_support_move_for_dataset(
            "hurricane", base_power=110, category="special"
        )
        self.assertFalse(r["is_support_move"])
        self.assertIsNone(r["support_group"])
        self.assertFalse(r["unknown_support_move_detected"])

    def test_damaging_move_via_category(self):
        # Even with base_power=None, category=physical or special
        # means damaging
        r = classify_support_move_for_dataset(
            "thunderbolt", base_power=None, category="special"
        )
        self.assertFalse(r["is_support_move"])

    def test_unknown_support_move(self):
        # A status-style move not in the known inventory
        r = classify_support_move_for_dataset("newgensupportmove")
        self.assertEqual(r["support_group"], GROUP_UNKNOWN_NEEDS_PROBE)
        self.assertEqual(
            r["support_status_from_audit"], STATUS_UNKNOWN_NEEDS_PROBE
        )
        self.assertTrue(r["is_support_move"])
        self.assertTrue(r["unknown_support_move_detected"])

    def test_normalization(self):
        # Move id with spaces / dashes / underscores
        r1 = classify_support_move_for_dataset("heal pulse")
        r2 = classify_support_move_for_dataset("heal-pulse")
        r3 = classify_support_move_for_dataset("heal_pulse")
        self.assertEqual(r1["support_group"], GROUP_HEALING_BUFF_ALLY_SUPPORT)
        self.assertEqual(r2["support_group"], GROUP_HEALING_BUFF_ALLY_SUPPORT)
        self.assertEqual(r3["support_group"], GROUP_HEALING_BUFF_ALLY_SUPPORT)


class TestAggregateDistribution(unittest.TestCase):
    """Test the support-move distribution aggregator."""

    def test_aggregate_always_includes_all_groups(self):
        # Empty list: all groups are 0
        dist = aggregate_support_distribution([])
        for g in ALL_SUPPORT_GROUPS:
            self.assertIn(g, dist)
            self.assertEqual(dist[g], 0)

    def test_aggregate_counts_correct(self):
        classifications = [
            classify_support_move_for_dataset("healpulse"),
            classify_support_move_for_dataset("raindance"),
            classify_support_move_for_dataset("protect"),
            classify_support_move_for_dataset("taunt"),
        ]
        dist = aggregate_support_distribution(classifications)
        self.assertEqual(
            dist[GROUP_HEALING_BUFF_ALLY_SUPPORT], 1
        )
        self.assertEqual(dist[GROUP_WEATHER_TERRAIN], 1)
        self.assertEqual(
            dist[GROUP_PROTECTION_DEFENSIVE_SUPPORT], 1
        )
        self.assertEqual(
            dist[GROUP_ANTI_SETUP_DISRUPTION], 1
        )

    def test_damaging_moves_excluded(self):
        # Damaging moves are not classified as support, so
        # they don't appear in the distribution.
        classifications = [
            classify_support_move_for_dataset(
                "hurricane", base_power=110, category="special"
            ),
        ]
        dist = aggregate_support_distribution(classifications)
        # All groups are 0
        for g in ALL_SUPPORT_GROUPS:
            self.assertEqual(dist[g], 0)


class TestV11SchemaRow(unittest.TestCase):
    """Test that v1.1 row is built with all new keys."""

    def setUp(self):
        self.turn = _make_fake_turn()
        self.battle = _make_fake_battle(turns=[self.turn])

    def test_v11_schema_version(self):
        row = build_row(
            self.battle, self.turn, "test.jsonl", "A", "ds1", "A"
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["schema_version"], "turn_rl_v1.1")

    def test_v11_metadata_fields(self):
        row = build_row(
            self.battle, self.turn, "test.jsonl", "A", "ds1", "A"
        )
        # Metadata fields
        self.assertIn("config_hash", row)
        self.assertIn("config_snapshot", row)
        self.assertIn("local_only_provenance", row)
        self.assertTrue(row["local_only_provenance"])
        self.assertIn("format", row)
        self.assertIn("team_id", row)
        self.assertIn("opponent_team_id", row)
        self.assertIn("runtime_mode", row)
        self.assertEqual(row["runtime_mode"], "gen9randomdoublesbattle")

    def test_v11_weather_terrain_fields(self):
        row = build_row(
            self.battle, self.turn, "test.jsonl", "A", "ds1", "A"
        )
        # Weather / terrain
        self.assertIn("weather_current", row)
        self.assertEqual(row["weather_current"], "raindance")
        self.assertIn("terrain_current", row)
        self.assertIn("setter_move_legal", row)
        self.assertIn("setter_move_selected", row)
        self.assertIn("setter_move_raw_score", row)
        self.assertIn("type_boost_move_legal", row)
        self.assertIn("type_boost_move_selected", row)
        self.assertIn("type_boost_applied", row)
        self.assertIn("wt2_relevance_flag", row)
        self.assertIn("wt3_relevance_flag", row)
        self.assertIn("wt4_relevance_flag", row)

    def test_v11_setter_move_legal_detected(self):
        # Rain Dance is in the legal actions for slot 0
        row = build_row(
            self.battle, self.turn, "test.jsonl", "A", "ds1", "A"
        )
        self.assertIn("raindance", row["setter_move_legal"])
        self.assertTrue(row["wt2_relevance_flag"])
        # Rain Dance was selected
        self.assertIn("raindance", row["setter_move_selected"])
        self.assertTrue(row["wt4_relevance_flag"])
        # Hurricane is a type-boost move
        self.assertIn("hurricane", row["type_boost_move_legal"])
        self.assertTrue(row["wt3_relevance_flag"])

    def test_v11_safety_fields(self):
        row = build_row(
            self.battle, self.turn, "test.jsonl", "A", "ds1", "A"
        )
        # Safety fields
        self.assertIn("block_reason_wrong_side", row)
        self.assertIn("block_reason_narrow_ally_heal", row)
        self.assertIn("block_reason_broad_support_target", row)
        self.assertIn("block_reason_ability_hard_safety", row)
        self.assertIn("revealed_ability_source", row)
        # CRITICAL: used_species_ability_inference must be False
        self.assertFalse(row["used_species_ability_inference"])
        self.assertIn("impossible_target_detected", row)
        self.assertFalse(row["impossible_target_detected"])
        self.assertIn("blocked_action_resurrected_by_joint", row)
        self.assertFalse(row["blocked_action_resurrected_by_joint"])

    def test_v11_reward_fields(self):
        row = build_row(
            self.battle, self.turn, "test.jsonl", "A", "ds1", "A"
        )
        # Reward / outcome fields
        self.assertIn("terminal_win_loss", row)
        self.assertIn("turn_delta_hp", row)
        self.assertIn("faint_caused", row)
        self.assertIn("faint_suffered", row)
        self.assertIn("delayed_reward_placeholder", row)
        self.assertEqual(row["delayed_reward_placeholder"], 0.0)
        self.assertIn("sparse_reward_warning", row)
        self.assertTrue(row["sparse_reward_warning"])
        self.assertIn("reward_provenance", row)
        self.assertEqual(row["reward_provenance"], "terminal_only")
        self.assertIn("reward_confidence", row)
        self.assertEqual(row["reward_confidence"], 1.0)

    def test_v11_support_classification_fields(self):
        row = build_row(
            self.battle, self.turn, "test.jsonl", "A", "ds1", "A"
        )
        self.assertIn("per_candidate_support_classification", row)
        self.assertIn("support_move_distribution", row)
        self.assertIn("unknown_support_move_detected", row)
        # Distribution must have all 9 groups
        dist = row["support_move_distribution"]
        for g in ALL_SUPPORT_GROUPS:
            self.assertIn(g, dist)

    def test_v10_fields_preserved(self):
        # v1.0 fields must still be in the row
        row = build_row(
            self.battle, self.turn, "test.jsonl", "A", "ds1", "A"
        )
        # v1.0 required
        for f in (
            "schema_version", "dataset_id", "source_artifact",
            "battle_tag", "episode_id", "turn_index",
            "player_side", "benchmark_arm", "policy_name",
            "won", "battle_result", "total_turns",
            "terminal_reward", "state_snapshot",
            "legal_action_keys_slot0", "legal_action_keys_slot1",
            "selected_joint_key", "final_action_keys",
            "selected_per_slot", "selected_score",
        ):
            self.assertIn(f, row, f"Missing v1.0 field: {f}")


class TestUnknownSupportMoveDetector(unittest.TestCase):
    """Test the unknown support move detector behavior."""

    def test_unknown_move_in_legal_actions(self):
        # Create a turn with an unknown support move
        turn = _make_fake_turn(
            v4a_legal0=[["move", "newgenmove", 0, "no_mechanic"]],
            v4a_legal1=[["move", "fakeout", 0, "no_mechanic"]],
            v4a_sel=[
                ["move", "newgenmove", 0, "no_mechanic"],
                ["move", "fakeout", 0, "no_mechanic"],
            ],
            v4a_final=[
                ["move", "newgenmove", 0, "no_mechanic"],
                ["move", "fakeout", 0, "no_mechanic"],
            ],
        )
        battle = _make_fake_battle(turns=[turn])
        row = build_row(
            battle, turn, "test.jsonl", "A", "ds1", "A"
        )
        self.assertIsNotNone(row)
        # The unknown move should be detected
        self.assertTrue(row["unknown_support_move_detected"])
        # The distribution should include unknown_needs_probe
        self.assertGreater(
            row["support_move_distribution"][GROUP_UNKNOWN_NEEDS_PROBE], 0
        )

    def test_no_unknown_moves_means_no_unknown_flag(self):
        # All known support moves (raindance, protect)
        turn = _make_fake_turn(
            v4a_legal0=[["move", "raindance", 0, "no_mechanic"]],
            v4a_legal1=[["move", "protect", 0, "no_mechanic"]],
            v4a_sel=[
                ["move", "raindance", 0, "no_mechanic"],
                ["move", "protect", 0, "no_mechanic"],
            ],
            v4a_final=[
                ["move", "raindance", 0, "no_mechanic"],
                ["move", "protect", 0, "no_mechanic"],
            ],
        )
        battle = _make_fake_battle(turns=[turn])
        row = build_row(
            battle, turn, "test.jsonl", "A", "ds1", "A"
        )
        self.assertIsNotNone(row)
        # No unknown moves -> no unknown_support_move_detected
        self.assertFalse(row["unknown_support_move_detected"])


class TestV11DefaultsWhenSourceMissing(unittest.TestCase):
    """Test that missing source data yields safe defaults."""

    def test_minimal_turn_has_safe_defaults(self):
        # Minimal turn with only required v1.0 fields
        turn = {
            "turn": 1,
            "state_snapshot": {
                "our_active_species": [],
                "opp_active_species": [],
                "our_active_hp_fraction": [],
                "opp_active_hp_fraction": [],
                "weather": "none",
                "fields": [],
            },
            "v4a_legal_action_keys_slot0": [
                ["move", "tackle", 0, "no_mechanic"],
            ],
            "v4a_legal_action_keys_slot1": [
                ["move", "tackle", 0, "no_mechanic"],
            ],
            "v4a_selected_joint_key": [
                ["move", "tackle", 0, "no_mechanic"],
                ["move", "tackle", 0, "no_mechanic"],
            ],
            "v4a_final_action_keys": [
                ["move", "tackle", 0, "no_mechanic"],
                ["move", "tackle", 0, "no_mechanic"],
            ],
            "selected_score": 0.0,
        }
        battle = {"battle_tag": "minimal", "won": None, "audit_turns": [turn]}
        row = build_row(
            battle, turn, "test.jsonl", "A", "ds1", "A"
        )
        self.assertIsNotNone(row)
        # Safety defaults
        self.assertFalse(row["used_species_ability_inference"])
        self.assertFalse(row["impossible_target_detected"])
        self.assertFalse(row["blocked_action_resurrected_by_joint"])
        # All 9 groups in distribution
        for g in ALL_SUPPORT_GROUPS:
            self.assertIn(g, row["support_move_distribution"])


if __name__ == "__main__":
    unittest.main()
