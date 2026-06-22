"""Phase BEHAVIOR-3 — Tests for speed-priority audit logger.

Verifies that speed-priority threat fields are persisted
at the top level of the main JSONL, so the turn-level
analyzer can read them.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _make_mock_battle():
    """Create a minimal mock battle for testing."""
    from unittest.mock import MagicMock
    battle = MagicMock()
    battle.player_username = "p1"
    battle.player_role = "p1"
    battle.turn = 1
    return battle


class TestLoggerAcceptsSpeedPriorityKwargs(unittest.TestCase):
    def test_logger_accepts_speed_priority_kwargs(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5",
            )
            # Just check the function signature accepts
            # the kwargs.
            import inspect
            sig = inspect.signature(logger.log_turn_decision)
            params = sig.parameters
            self.assertIn("speed_priority_threatened", params)
            self.assertIn("faster_opponents", params)
            self.assertIn("priority_opponents", params)
            self.assertIn(
                "expected_to_faint_before_moving", params
            )
            self.assertIn(
                "protected_due_to_speed_priority", params
            )
            self.assertIn(
                "speed_priority_protect_bonus_applied", params
            )
            self.assertIn(
                "speed_priority_attack_penalty_applied", params
            )
            self.assertIn(
                "speed_priority_switch_bonus_applied", params
            )


class TestMissingKwargsSerializeSafe(unittest.TestCase):
    def test_missing_kwargs_serialize_with_safe_defaults(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5",
            )
            # Call without speed-priority kwargs.
            battle = _make_mock_battle()
            logger.log_turn_decision(
                battle_tag="b1",
                turn=1,
                battle=battle,
                selected_joint_order="/choose move tackle 1",
                selected_score=100.0,
                scored_joint_orders=[],
                expected_damages=[50.0, 0.0],
                expected_kos=[False, False],
                target_hps=[100.0, 100.0],
                overkill_triggered=False,
                focus_fire_triggered=False,
                ally_hit_penalty_triggered=False,
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=[None, None],
                slot_action_types=[{}, {}],
                target_species=[None, None],
            )
            # Flush battle.
            logger.save_battle("b1", "p1", battle)
            # Read the persisted JSONL.
            with open(path) as f:
                row = json.loads(f.readline())
            turn = row["audit_turns"][0]
            # Speed-priority fields should NOT be present
            # (missing kwargs).
            self.assertNotIn(
                "speed_priority_threatened", turn
            )
            self.assertNotIn("faster_opponents", turn)


class TestPersistedMainJsonl(unittest.TestCase):
    def test_persisted_main_jsonl_has_speed_priority_fields(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5",
            )
            battle = _make_mock_battle()
            logger.log_turn_decision(
                battle_tag="b1",
                turn=1,
                battle=battle,
                selected_joint_order="/choose move tackle 1",
                selected_score=100.0,
                scored_joint_orders=[],
                expected_damages=[50.0, 0.0],
                expected_kos=[False, False],
                target_hps=[100.0, 100.0],
                overkill_triggered=False,
                focus_fire_triggered=False,
                ally_hit_penalty_triggered=False,
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=[None, None],
                slot_action_types=[{}, {}],
                target_species=[None, None],
                speed_priority_threatened=[True, False],
                faster_opponents=[
                    ["charizard"], ["blastoise"]
                ],
                priority_opponents=[[], ["garchomp"]],
                expected_to_faint_before_moving=[True, False],
                protected_due_to_speed_priority=[True, False],
                speed_priority_protect_bonus_applied=[True, False],
                speed_priority_attack_penalty_applied=[False, True],
                speed_priority_switch_bonus_applied=[False, False],
            )
            logger.save_battle("b1", "p1", battle)
            with open(path) as f:
                row = json.loads(f.readline())
            turn = row["audit_turns"][0]
            # All speed-priority fields should be at
            # top level.
            self.assertEqual(
                turn["speed_priority_threatened"], [True, False]
            )
            self.assertEqual(
                turn["faster_opponents"], [["charizard"], ["blastoise"]]
            )
            self.assertEqual(
                turn["priority_opponents"], [[], ["garchomp"]]
            )
            self.assertEqual(
                turn["expected_to_faint_before_moving"],
                [True, False],
            )
            self.assertEqual(
                turn["protected_due_to_speed_priority"],
                [True, False],
            )
            self.assertEqual(
                turn["speed_priority_protect_bonus_applied"],
                [True, False],
            )
            self.assertEqual(
                turn["speed_priority_attack_penalty_applied"],
                [False, True],
            )
            self.assertEqual(
                turn["speed_priority_switch_bonus_applied"],
                [False, False],
            )


class TestSpeciesListsJsonSafe(unittest.TestCase):
    def test_species_lists_are_json_safe_strings(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5",
            )
            battle = _make_mock_battle()
            logger.log_turn_decision(
                battle_tag="b1",
                turn=1,
                battle=battle,
                selected_joint_order="/choose move tackle 1",
                selected_score=100.0,
                scored_joint_orders=[],
                expected_damages=[50.0, 0.0],
                expected_kos=[False, False],
                target_hps=[100.0, 100.0],
                overkill_triggered=False,
                focus_fire_triggered=False,
                ally_hit_penalty_triggered=False,
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=[None, None],
                slot_action_types=[{}, {}],
                target_species=[None, None],
                faster_opponents=[
                    ["charizard", "garchomp"], ["blastoise"]
                ],
            )
            logger.save_battle("b1", "p1", battle)
            with open(path) as f:
                row = json.loads(f.readline())
            turn = row["audit_turns"][0]
            # Species should be strings, not Pokemon objects.
            sp = turn["faster_opponents"]
            self.assertIsInstance(sp, list)
            for slot in sp:
                for s in slot:
                    self.assertIsInstance(s, str)


class TestNoRawPokemonObjects(unittest.TestCase):
    def test_no_raw_pokemon_objects_serialized(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5",
            )
            battle = _make_mock_battle()
            logger.log_turn_decision(
                battle_tag="b1",
                turn=1,
                battle=battle,
                selected_joint_order="/choose move tackle 1",
                selected_score=100.0,
                scored_joint_orders=[],
                expected_damages=[50.0, 0.0],
                expected_kos=[False, False],
                target_hps=[100.0, 100.0],
                overkill_triggered=False,
                focus_fire_triggered=False,
                ally_hit_penalty_triggered=False,
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=[None, None],
                slot_action_types=[{}, {}],
                target_species=[None, None],
                faster_opponents=[["charizard"], []],
            )
            logger.save_battle("b1", "p1", battle)
            with open(path) as f:
                row = json.loads(f.readline())
            # The entire row should be JSON-serializable.
            json.dumps(row)


class TestAnalyzerReadsNewFields(unittest.TestCase):
    def test_analyzer_reads_new_fields_and_fields_available_true(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate,
        )
        v4a_sel = [
            ["move", "/choose move tackle 1", "opp1", "plain"],
            ["move", "/choose move tackle 1", "opp1", "plain"],
        ]
        turn = {
            "turn": 1,
            "v4a_selected_joint_key": v4a_sel,
            "speed_priority_threatened": [True, False],
            "faster_opponents": [["charizard"], []],
            "priority_opponents": [[], ["garchomp"]],
        }
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        agg = _aggregate(recs)
        self.assertTrue(
            agg["speed_priority_summary"]["fields_available"]
        )
        self.assertEqual(
            agg["speed_priority_summary"]["slot0_threatened"], 1
        )
        self.assertEqual(
            agg["speed_priority_summary"]["slot1_threatened"], 0
        )

    def test_analyzer_remains_backward_compatible(self):
        # Old rows without the new fields should still
        # parse. fields_available should be false.
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate,
        )
        v4a_sel = [
            ["move", "/choose move tackle 1", "opp1", "plain"],
            ["move", "/choose move tackle 1", "opp1", "plain"],
        ]
        turn = {
            "turn": 1,
            "v4a_selected_joint_key": v4a_sel,
        }
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        agg = _aggregate(recs)
        self.assertFalse(
            agg["speed_priority_summary"]["fields_available"]
        )
        self.assertEqual(
            agg["speed_priority_summary"]["fields_missing_count"],
            1,
        )


if __name__ == "__main__":
    unittest.main()

class TestScoreDiffFields(unittest.TestCase):
    def test_logger_accepts_score_diff_kwargs(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5",
            )
            import inspect
            sig = inspect.signature(logger.log_turn_decision)
            params = sig.parameters
            for p in [
                "speed_priority_protect_score_slot0",
                "speed_priority_protect_score_slot1",
                "speed_priority_best_attack_score_slot0",
                "speed_priority_best_attack_score_slot1",
                "speed_priority_score_diff_slot0",
                "speed_priority_score_diff_slot1",
            ]:
                self.assertIn(p, params)

    def test_missing_score_diff_kwargs_serialize_as_none(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5",
            )
            battle = _make_mock_battle()
            logger.log_turn_decision(
                battle_tag="b1",
                turn=1,
                battle=battle,
                selected_joint_order="/choose move tackle 1",
                selected_score=100.0,
                scored_joint_orders=[],
                expected_damages=[50.0, 0.0],
                expected_kos=[False, False],
                target_hps=[100.0, 100.0],
                overkill_triggered=False,
                focus_fire_triggered=False,
                ally_hit_penalty_triggered=False,
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=[None, None],
                slot_action_types=[{}, {}],
                target_species=[None, None],
            )
            logger.save_battle("b1", "p1", battle)
            with open(path) as f:
                row = json.loads(f.readline())
            turn = row["audit_turns"][0]
            self.assertNotIn(
                "speed_priority_score_diff_slot0", turn
            )

    def test_persisted_main_jsonl_includes_score_diff_fields(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5",
            )
            battle = _make_mock_battle()
            logger.log_turn_decision(
                battle_tag="b1",
                turn=1,
                battle=battle,
                selected_joint_order="/choose move tackle 1",
                selected_score=100.0,
                scored_joint_orders=[],
                expected_damages=[50.0, 0.0],
                expected_kos=[False, False],
                target_hps=[100.0, 100.0],
                overkill_triggered=False,
                focus_fire_triggered=False,
                ally_hit_penalty_triggered=False,
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=[None, None],
                slot_action_types=[{}, {}],
                target_species=[None, None],
                v2l1_raw_scores_slot0={
                    "move|tackle|1": 100.0,
                    "move|protect|0": 240.0,
                },
                v2l1_raw_scores_slot1={
                    "move|ember|0": 80.0,
                },
            )
            logger.save_battle("b1", "p1", battle)
            with open(path) as f:
                row = json.loads(f.readline())
            turn = row["audit_turns"][0]
            self.assertEqual(
                turn.get("speed_priority_protect_score_slot0"), 240.0
            )
            self.assertEqual(
                turn.get("speed_priority_best_attack_score_slot0"),
                100.0,
            )
            self.assertEqual(
                turn.get("speed_priority_score_diff_slot0"), 140.0
            )
            self.assertNotIn(
                "speed_priority_score_diff_slot1", turn
            )

    def test_no_raw_order_objects_with_score_diff(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5",
            )
            battle = _make_mock_battle()
            logger.log_turn_decision(
                battle_tag="b1",
                turn=1,
                battle=battle,
                selected_joint_order="/choose move tackle 1",
                selected_score=100.0,
                scored_joint_orders=[],
                expected_damages=[50.0, 0.0],
                expected_kos=[False, False],
                target_hps=[100.0, 100.0],
                overkill_triggered=False,
                focus_fire_triggered=False,
                ally_hit_penalty_triggered=False,
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=[None, None],
                slot_action_types=[{}, {}],
                target_species=[None, None],
                v2l1_raw_scores_slot0={
                    "move|protect|0": 240.0,
                },
            )
            logger.save_battle("b1", "p1", battle)
            with open(path) as f:
                row = json.loads(f.readline())
            json.dumps(row)


class TestAnalyzerScoreDiffFields(unittest.TestCase):
    def test_analyzer_reads_score_diff_fields(self):
        from analyze_doubles_turn_level import _extract_turn_record, _aggregate
        v4a_sel = [
            ["move", "/choose move tackle 1", "opp1", "plain"],
            ["move", "/choose move tackle 1", "opp1", "plain"],
        ]
        turn = {
            "turn": 1,
            "v4a_selected_joint_key": v4a_sel,
            "speed_priority_threatened": [True, False],
            "expected_to_faint_before_moving": [True, False],
            "speed_priority_score_diff_slot0": -50.0,
            "speed_priority_protect_score_slot0": 100.0,
            "speed_priority_best_attack_score_slot0": 150.0,
        }
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        agg = _aggregate(recs)
        sp = agg["speed_priority_summary"]
        self.assertEqual(sp["score_debug_available_count"], 1)
        self.assertEqual(sp["score_diff_count"], 1)
        self.assertEqual(
            sp["expected_faint_with_negative_diff_count"], 1
        )

    def test_analyzer_handles_missing_score_diff_fields(self):
        from analyze_doubles_turn_level import _extract_turn_record, _aggregate
        v4a_sel = [
            ["move", "/choose move tackle 1", "opp1", "plain"],
            ["move", "/choose move tackle 1", "opp1", "plain"],
        ]
        turn = {
            "turn": 1,
            "v4a_selected_joint_key": v4a_sel,
        }
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        agg = _aggregate(recs)
        sp = agg["speed_priority_summary"]
        self.assertEqual(sp["score_debug_available_count"], 0)
        self.assertEqual(sp["score_diff_count"], 0)

    def test_analyzer_negative_diff_under_expected_faint(self):
        from analyze_doubles_turn_level import _extract_turn_record, _aggregate
        v4a_sel = [
            ["move", "/choose move tackle 1", "opp1", "plain"],
            ["move", "/choose move tackle 1", "opp1", "plain"],
        ]
        turn = {
            "turn": 1,
            "v4a_selected_joint_key": v4a_sel,
            "speed_priority_threatened": [True, False],
            "expected_to_faint_before_moving": [True, False],
            "speed_priority_score_diff_slot0": -50.0,
        }
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        agg = _aggregate(recs)
        sp = agg["speed_priority_summary"]
        self.assertEqual(
            sp["expected_faint_with_negative_diff_count"], 1
        )
        self.assertEqual(
            sp["expected_faint_with_positive_diff_count"], 0
        )
