import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from bot_doubles_decision_graph_viewer import DecisionDashboard
from doubles_decision_audit_logger import DoublesDecisionAuditLogger
from doubles_decision_graph_model import (
    DecisionStore,
    IncrementalJsonlTail,
    action_stories,
    build_turn_graph,
    calculate_graph_layout,
    describe_joint_order,
    display_name,
    inspector_sections,
    ranked_candidates,
    read_json_lines,
    turn_summary,
)


class DecisionStoreTests(unittest.TestCase):
    def test_live_decision_and_outcome_merge(self):
        store = DecisionStore()
        store.apply_record({
            "event": "decision", "battle_tag": "battle-1", "turn": 3,
            "selected_joint_order": "move 1, move 2",
            "slot_0": {"action": "Earthquake", "expected_damage": 80},
        })
        store.apply_record({
            "event": "outcome", "battle_tag": "battle-1", "turn": 3,
            "slot_0": {"outcome_known": True, "actual_damage": 73},
        })
        turn = store.get_turn("battle-1", 3)
        self.assertEqual(turn["slot_0"]["action"], "Earthquake")
        self.assertEqual(turn["slot_0"]["actual_damage"], 73)

    def test_battle_end_merge(self):
        store = DecisionStore()
        store.apply_record({"event": "battle_end", "battle_tag": "battle-1",
                            "winner": "bot", "won": True, "total_turns": 8})
        self.assertTrue(store.battles["battle-1"]["won"])

    def test_legacy_battle_record_import(self):
        store = DecisionStore()
        store.apply_record({
            "battle_tag": "battle-old", "won": False,
            "audit_turns": [{"turn": 1, "selected_joint_order": "pass"}],
        })
        self.assertEqual(store.get_turn("battle-old", 1)["selected_joint_order"], "pass")

    def test_read_json_lines_skips_malformed(self):
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
            path = handle.name
            handle.write('{"battle_tag":"ok"}\n')
            handle.write("{broken\n")
        try:
            self.assertEqual([row["battle_tag"] for row in read_json_lines(path)], ["ok"])
        finally:
            os.unlink(path)


class TailTests(unittest.TestCase):
    def test_partial_line_waits_for_completion(self):
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
            path = handle.name
            handle.write('{"event":"decision"')
        try:
            tail = IncrementalJsonlTail(path)
            self.assertEqual(tail.poll(), [])
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(',"turn":1}\n')
            self.assertEqual(tail.poll()[0]["turn"], 1)
        finally:
            os.unlink(path)

    def test_truncation_resets_reader(self):
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
            path = handle.name
            handle.write('{"turn":1}\n')
        try:
            tail = IncrementalJsonlTail(path)
            self.assertEqual(tail.poll()[0]["turn"], 1)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"turn":2}\n')
            self.assertEqual(tail.poll()[0]["turn"], 2)
        finally:
            os.unlink(path)


class GraphTests(unittest.TestCase):
    def test_graph_contains_candidates_actions_and_reasons(self):
        turn = {
            "turn": 5,
            "our_active": [{"species": "Gliscor", "hp_fraction": 0.41}],
            "opp_active": ["Cresselia"],
            "selected_joint_order": "High Horsepower into Cresselia",
            "selected_score": 0,
            "top_5_alternatives": ["Protect", "Dual Wingbeat"],
            "top_5_scores": [30, 25],
            "slot_0": {
                "action": "High Horsepower", "target_species": "Cresselia",
                "ground_into_levitate_selected": True,
                "ability_block_reason": "ground_into_levitate",
            },
            "slot_1": {"action": "Protect", "expected_ko": False},
            "flags": {"focus_fire_triggered": True},
        }
        nodes, edges = build_turn_graph("battle-1", turn)
        ids = {node.node_id for node in nodes}
        self.assertIn("turn", ids)
        self.assertIn("candidate_0", ids)
        self.assertIn("selected", ids)
        self.assertIn("slot_0", ids)
        self.assertIn("slot_0_ground_into_levitate_selected", ids)
        self.assertIn("flag_focus_fire_triggered", ids)
        self.assertTrue(edges)

    def test_missing_optional_fields_are_supported(self):
        nodes, _ = build_turn_graph("battle-empty", {"turn": 1})
        self.assertIn("selected", {node.node_id for node in nodes})

    def test_ranked_candidates_puts_selected_first(self):
        candidates = ranked_candidates({
            "selected_joint_order": "Protect, Surf",
            "selected_score": 90,
            "top_5_alternatives": ["Switch, Surf", "Protect, Protect"],
            "top_5_scores": [80, 70],
        })
        self.assertTrue(candidates[0]["selected"])
        self.assertEqual([row["score"] for row in candidates], [90, 80, 70])

    def test_protocol_actions_become_readable_decision_story(self):
        turn = {
            "our_active": [{"species": "sandyshocks"}, {"species": "ambipom"}],
            "opp_active": [{"species": "regigigas"}, {"species": "qwilfishhisui"}],
            "selected_joint_order": "/choose move earthpower 2, move fakeout 2",
            "focus_fire_triggered": True,
            "slot_0": {
                "action": "/choose move earthpower 2", "target_species": "qwilfishhisui",
                "expected_damage": 1.1, "expected_ko": True, "selected_score": 800,
            },
            "slot_1": {
                "action": "/choose move fakeout 2", "target_species": "qwilfishhisui",
                "action_types": {"fakeout": True}, "selected_score": 300,
            },
        }
        stories = action_stories(turn)
        self.assertEqual(display_name("qwilfishhisui"), "Qwilfish-Hisui")
        self.assertEqual(stories[0]["actor"], "Sandy Shocks")
        self.assertEqual(stories[0]["verb"], "Earth Power")
        self.assertEqual(stories[0]["target"], "Qwilfish-Hisui")
        self.assertIn("Expected knockout", stories[0]["reasons"])
        self.assertIn("Focus fire", stories[1]["reasons"])
        plan = describe_joint_order(turn["selected_joint_order"], turn)
        self.assertIn("Sandy Shocks: Earth Power → Qwilfish-Hisui", plan)

    def test_summary_and_inspector_hide_empty_values(self):
        turn = {
            "selected_score": 10,
            "slot_0": {"ground_into_levitate_selected": True, "actual_damage": None},
        }
        summary = turn_summary(turn)
        sections = inspector_sections(turn["slot_0"])
        self.assertEqual(summary["signal"], "Ground into Levitate")
        self.assertNotIn("actual_damage", sections["Scoring"])
        self.assertIn("ground_into_levitate_selected", sections["Safety"])

    def test_layout_has_no_same_column_overlap(self):
        nodes, _ = build_turn_graph("battle-1", {
            "turn": 4,
            "top_5_alternatives": [f"candidate {i}" for i in range(5)],
            "top_5_scores": [5, 4, 3, 2, 1],
            "slot_0": {"action": "Move A", "expected_ko": True},
            "slot_1": {"action": "Move B", "speed_priority_threatened": True},
        })
        layouts = calculate_graph_layout(nodes)
        for first in nodes:
            for second in nodes:
                if first.node_id >= second.node_id or first.column != second.column:
                    continue
                a = layouts[first.node_id]
                b = layouts[second.node_id]
                overlap = not (a.y + a.height <= b.y or b.y + b.height <= a.y)
                self.assertFalse(overlap, f"{first.node_id} overlaps {second.node_id}")


class LiveLoggerTests(unittest.TestCase):
    def test_logger_writes_compact_event(self):
        with tempfile.TemporaryDirectory() as directory:
            main_path = os.path.join(directory, "main.jsonl")
            live_path = os.path.join(directory, "live.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=main_path, live_event_filepath=live_path,
            )
            event = logger._build_live_decision_event("battle-1", {
                "turn": 2, "selected_joint_order": "Protect",
                "slot_0": {"action": "Protect", "unused_field": 123},
                "slot_1": {},
            })
            logger._append_live_event(event)
            row = list(read_json_lines(live_path))[0]
            self.assertEqual(row["schema_version"], 1)
            self.assertEqual(row["slot_0"]["action"], "Protect")
            self.assertNotIn("unused_field", row["slot_0"])

    def test_disabled_live_logger_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = DoublesDecisionAuditLogger(
                filepath=os.path.join(directory, "main.jsonl"),
                live_event_filepath=None,
            )
            logger._append_live_event({"event": "decision"})
            self.assertFalse(os.path.exists(os.path.join(directory, "live.jsonl")))

    def test_live_write_failure_never_raises_again(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = DoublesDecisionAuditLogger(
                filepath=os.path.join(directory, "main.jsonl"),
                live_event_filepath=os.path.join(directory, "live.jsonl"),
            )
            with patch("builtins.open", side_effect=OSError("disk unavailable")):
                logger._append_live_event({"event": "decision"})
            self.assertTrue(logger._live_stream_failed)
            logger._append_live_event({"event": "decision"})


class QtDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dashboard_loads_replay_offscreen(self):
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
            path = handle.name
            handle.write(json.dumps({
                "battle_tag": "battle-modern",
                "won": True,
                "audit_turns": [{
                    "turn": 1,
                    "selected_joint_order": "Protect, Thunderbolt",
                    "selected_score": 50,
                    "top_5_alternatives": ["Switch, Thunderbolt"],
                    "top_5_scores": [44],
                    "total_legal_joint_orders": 6,
                    "slot_0": {"action": "Protect"},
                    "slot_1": {"action": "Thunderbolt", "expected_damage": 60},
                }],
            }) + "\n")
        try:
            window = DecisionDashboard(replay=path)
            self.app.processEvents()
            self.assertEqual(window.battle_box.currentText(), "battle-modern")
            self.assertEqual(window.candidate_list.count(), 2)
            self.assertGreater(len(window.graph.scene().items()), 0)
            self.assertEqual(window.score_card.value.text(), "50.00")
            window.close()
        finally:
            os.unlink(path)

    def test_live_follow_advances_within_same_battle(self):
        window = DecisionDashboard()
        window.store.apply_record({
            "event": "decision", "battle_tag": "battle-live", "turn": 1,
            "slot_0": {}, "slot_1": {},
        })
        window._refresh_battles(True)
        self.assertEqual(window.turn_spin.value(), 1)
        window.store.apply_record({
            "event": "decision", "battle_tag": "battle-live", "turn": 2,
            "slot_0": {}, "slot_1": {},
        })
        window._refresh_battles(True)
        self.assertEqual(window.turn_spin.value(), 2)
        window.close()


if __name__ == "__main__":
    unittest.main()
