"""Phase BI-2D: switch counterfactual persistence tests.

Validates that the per-slot ``switch_counterfactual``
sub-dict is captured in the persisted audit JSONL
and live JSONL, and that it contains only the
expected primitives (no raw candidate tables, no
order objects, no hidden info).
"""
import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _cleanup(paths):
    for p in paths:
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


def _make_logger(detail_level="top5"):
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
        detail_level=detail_level,
        live_event_filepath=live_path,
    )
    return logger, main_path, live_path


def _minimal_kwargs():
    return dict(
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


def _log_one(logger, switch_counterfactual):
    class FB:
        player_username = "test"
        turn = 1
        active_pokemon = [None, None]
        opponent_active_pokemon = [None, None]

    logger.completed_turns["tag"] = []
    logger.log_turn_decision(
        battle_tag="tag",
        turn=1,
        battle=FB(),
        selected_joint_order="pass",
        selected_score=0.0,
        switch_counterfactual=switch_counterfactual,
        **_minimal_kwargs(),
    )


class TestSwitchCounterfactualHelper(unittest.TestCase):
    """Direct tests of the per-slot assembly helper."""

    def test_helper_builds_with_switch_chosen(self):
        from doubles_engine.audit_metadata import (
            assemble_switch_counterfactual_slot,
        )
        scf = assemble_switch_counterfactual_slot(
            slot_idx=0,
            voluntary_switch_candidate_table=[
                {
                    "candidate_action_key": ("switch", "rotom-wash", 0),
                    "adjusted_switch_score": 95.3,
                    "reason_codes": ["risk_reduction"],
                },
                {
                    "candidate_action_key": ("switch", "incineroar", 0),
                    "adjusted_switch_score": 60.0,
                    "reason_codes": [],
                },
            ],
            selected_action_key=("switch", "rotom-wash", 0),
            counterfactual_action_key=("move", "voltswitch", 0),
            best_stay_score=70.0,
            best_stay_action_key=("move", "voltswitch", 0),
            selection_changed=True,
            reason_codes=["risk_reduction"],
        )
        self.assertTrue(scf["chosen_is_switch"])
        self.assertEqual(
            scf["chosen_action_key"], "switch|rotom-wash|0"
        )
        self.assertEqual(
            scf["counterfactual_action_key"], "move|voltswitch|0"
        )
        self.assertEqual(
            scf["best_switch_action_key"], "switch|rotom-wash|0"
        )
        self.assertEqual(scf["best_switch_score"], 95.3)
        self.assertEqual(
            scf["best_non_switch_action_key"], "move|voltswitch|0"
        )
        self.assertEqual(scf["best_non_switch_score"], 70.0)
        self.assertAlmostEqual(
            scf["switch_vs_non_switch_delta"], 25.3, places=2
        )
        self.assertTrue(scf["selection_changed"])
        self.assertEqual(scf["reason_codes"], ["risk_reduction"])

    def test_helper_builds_with_stay_chosen(self):
        from doubles_engine.audit_metadata import (
            assemble_switch_counterfactual_slot,
        )
        scf = assemble_switch_counterfactual_slot(
            slot_idx=1,
            voluntary_switch_candidate_table=[
                {
                    "candidate_action_key": ("switch", "garchomp", 0),
                    "adjusted_switch_score": 75.0,
                    "reason_codes": [],
                },
            ],
            selected_action_key=("move", "earthquake", 1),
            counterfactual_action_key=("move", "earthquake", 1),
            best_stay_score=110.0,
            best_stay_action_key=("move", "earthquake", 1),
            selection_changed=False,
            reason_codes=[],
        )
        self.assertFalse(scf["chosen_is_switch"])
        self.assertEqual(
            scf["chosen_action_key"], "move|earthquake|1"
        )
        self.assertEqual(scf["best_switch_score"], 75.0)
        self.assertEqual(scf["best_non_switch_score"], 110.0)
        self.assertEqual(
            scf["switch_vs_non_switch_delta"], -35.0
        )

    def test_helper_no_switch_candidate_uses_safe_defaults(self):
        from doubles_engine.audit_metadata import (
            assemble_switch_counterfactual_slot,
        )
        scf = assemble_switch_counterfactual_slot(
            slot_idx=0,
            voluntary_switch_candidate_table=[],
            selected_action_key=("move", "tackle", 0),
            counterfactual_action_key=("move", "tackle", 0),
            best_stay_score=42.0,
            best_stay_action_key=("move", "tackle", 0),
            selection_changed=False,
            reason_codes=[],
        )
        self.assertFalse(scf["chosen_is_switch"])
        self.assertEqual(scf["best_switch_action_key"], "")
        self.assertIsNone(scf["best_switch_score"])
        self.assertEqual(
            scf["best_non_switch_action_key"], "move|tackle|0"
        )
        self.assertEqual(scf["best_non_switch_score"], 42.0)
        self.assertIsNone(scf["switch_vs_non_switch_delta"])

    def test_helper_no_non_switch_action(self):
        from doubles_engine.audit_metadata import (
            assemble_switch_counterfactual_slot,
        )
        scf = assemble_switch_counterfactual_slot(
            slot_idx=0,
            voluntary_switch_candidate_table=[
                {
                    "candidate_action_key": ("switch", "pikachu", 0),
                    "adjusted_switch_score": 50.0,
                    "reason_codes": [],
                },
            ],
            selected_action_key=("switch", "pikachu", 0),
            counterfactual_action_key=("switch", "pikachu", 0),
            best_stay_score=None,
            best_stay_action_key=None,
            selection_changed=False,
            reason_codes=[],
        )
        self.assertTrue(scf["chosen_is_switch"])
        self.assertEqual(
            scf["best_switch_action_key"], "switch|pikachu|0"
        )
        self.assertEqual(scf["best_switch_score"], 50.0)
        self.assertEqual(scf["best_non_switch_action_key"], "")
        self.assertIsNone(scf["best_non_switch_score"])
        self.assertIsNone(scf["switch_vs_non_switch_delta"])

    def test_helper_delta_convention(self):
        """Delta = best_switch_score - best_non_switch_score.

        Positive: switch was preferred.
        Negative: stay was preferred.
        Zero: tie.
        """
        from doubles_engine.audit_metadata import (
            assemble_switch_counterfactual_slot,
        )
        # Tied
        scf = assemble_switch_counterfactual_slot(
            slot_idx=0,
            voluntary_switch_candidate_table=[
                {
                    "candidate_action_key": ("switch", "pikachu", 0),
                    "adjusted_switch_score": 50.0,
                    "reason_codes": [],
                },
            ],
            selected_action_key=("move", "tackle", 0),
            counterfactual_action_key=("move", "tackle", 0),
            best_stay_score=50.0,
            best_stay_action_key=("move", "tackle", 0),
            selection_changed=False,
            reason_codes=[],
        )
        self.assertEqual(scf["switch_vs_non_switch_delta"], 0.0)

    def test_helper_reason_codes_coerced_to_strings(self):
        from doubles_engine.audit_metadata import (
            assemble_switch_counterfactual_slot,
        )
        scf = assemble_switch_counterfactual_slot(
            slot_idx=0,
            voluntary_switch_candidate_table=[],
            selected_action_key=("move", "tackle", 0),
            counterfactual_action_key=("move", "tackle", 0),
            best_stay_score=10.0,
            best_stay_action_key=("move", "tackle", 0),
            selection_changed=False,
            reason_codes=[1, 2.5, None, "valid"],
        )
        # Non-string values are coerced via str(); None
        # is skipped because it is falsy. Valid string
        # survives.
        coerced = scf["reason_codes"]
        self.assertIn("valid", coerced)
        # None should be skipped (it is falsy).
        self.assertNotIn(None, coerced)


class TestSwitchCounterfactualPersisted(unittest.TestCase):
    """End-to-end persistence tests."""

    def _scf_payload(self):
        return {
            "slot0": {
                "chosen_is_switch": True,
                "chosen_action_key": "switch|rotom-wash|0",
                "counterfactual_action_key": "move|voltswitch|0",
                "best_switch_action_key": "switch|rotom-wash|0",
                "best_switch_score": 95.3,
                "best_non_switch_action_key": "move|voltswitch|0",
                "best_non_switch_score": 70.0,
                "switch_vs_non_switch_delta": 25.3,
                "selection_changed": True,
                "reason_codes": ["risk_reduction"],
            },
            "slot1": {
                "chosen_is_switch": False,
                "chosen_action_key": "move|earthquake|1",
                "counterfactual_action_key": "move|earthquake|1",
                "best_switch_action_key": "switch|garchomp|0",
                "best_switch_score": 75.0,
                "best_non_switch_action_key": "move|earthquake|1",
                "best_non_switch_score": 110.0,
                "switch_vs_non_switch_delta": -35.0,
                "selection_changed": False,
                "reason_codes": [],
            },
            "joint_selection_changed": True,
        }

    def test_persisted_main_jsonl_has_switch_counterfactual(self):
        logger, main_path, live_path = _make_logger()
        try:
            scf = self._scf_payload()
            _log_one(logger, scf)

            class FB:
                player_username = "test"
                turn = 1
                active_pokemon = [None, None]
                opponent_active_pokemon = [None, None]

            logger.save_battle("tag", "test", FB())

            with open(main_path) as f:
                record = json.loads(f.readline())
            audit_turns = record["audit_turns"]
            self.assertGreaterEqual(len(audit_turns), 1)
            turn = audit_turns[0]
            self.assertIn("switch_counterfactual", turn)
            persisted = turn["switch_counterfactual"]
            self.assertIn("slot0", persisted)
            self.assertIn("slot1", persisted)
            self.assertTrue(persisted["joint_selection_changed"])
            self.assertEqual(
                persisted["slot0"]["best_switch_score"], 95.3
            )
            self.assertEqual(
                persisted["slot1"]["best_non_switch_score"], 110.0
            )
        finally:
            _cleanup([main_path, live_path])

    def test_live_event_has_switch_counterfactual(self):
        logger, main_path, live_path = _make_logger()
        try:
            scf = self._scf_payload()
            _log_one(logger, scf)

            with open(live_path) as f:
                lines = [l for l in f if l.strip()]
            self.assertGreater(len(lines), 0)
            event = json.loads(lines[0])
            self.assertIn("switch_counterfactual", event)
            sc = event["switch_counterfactual"]
            self.assertIn("slot0", sc)
            self.assertIn("slot1", sc)
            self.assertTrue(sc["joint_selection_changed"])
            self.assertTrue(sc["slot0"]["chosen_is_switch"])
            self.assertFalse(sc["slot1"]["chosen_is_switch"])
        finally:
            _cleanup([main_path, live_path])

    def test_missing_kwarg_serializes_as_none(self):
        """When the bot does NOT pass switch_counterfactual,
        the persisted JSONL keeps the field as None and the
        live event projects an empty dict.
        """
        logger, main_path, live_path = _make_logger()
        try:
            _log_one(logger, None)

            class FB:
                player_username = "test"
                turn = 1
                active_pokemon = [None, None]
                opponent_active_pokemon = [None, None]

            logger.save_battle("tag", "test", FB())

            with open(main_path) as f:
                record = json.loads(f.readline())
            self.assertIsNone(
                record["audit_turns"][0]["switch_counterfactual"]
            )

            with open(live_path) as f:
                lines = [l for l in f if l.strip()]
            event = json.loads(lines[0])
            self.assertEqual(event["switch_counterfactual"], {})
        finally:
            _cleanup([main_path, live_path])

    def test_persisted_json_round_trip_succeeds(self):
        """The whole switch_counterfactual sub-dict
        must round-trip through json.dumps / loads.
        """
        logger, main_path, live_path = _make_logger()
        try:
            scf = self._scf_payload()
            _log_one(logger, scf)

            class FB:
                player_username = "test"
                turn = 1
                active_pokemon = [None, None]
                opponent_active_pokemon = [None, None]

            logger.save_battle("tag", "test", FB())

            with open(main_path) as f:
                record = json.loads(f.readline())
            persisted = record["audit_turns"][0][
                "switch_counterfactual"
            ]
            encoded = json.dumps(persisted)
            decoded = json.loads(encoded)
            self.assertEqual(
                decoded["slot0"]["chosen_action_key"],
                "switch|rotom-wash|0",
            )
            self.assertEqual(
                decoded["slot1"]["best_non_switch_score"], 110.0
            )
        finally:
            _cleanup([main_path, live_path])


class TestSwitchCounterfactualHiddenInfo(unittest.TestCase):
    """The snapshot must not include hidden info.

    The switch_counterfactual sub-dict only carries
    visible/observable data plus the bot's own
    selection. We forbid raw order objects, full
    candidate tables, ability, item, moves.
    """

    def test_no_raw_order_objects_in_payload(self):
        from doubles_engine.audit_metadata import (
            assemble_switch_counterfactual_slot,
        )

        class FakeOrder:
            ability = "levitate"
            item = "leftovers"
            moves = ["calmmind", "recover"]

            def __repr__(self):
                return "<FakeOrder>"

        scf = assemble_switch_counterfactual_slot(
            slot_idx=0,
            voluntary_switch_candidate_table=[
                {
                    "candidate_action_key": ("switch", "pikachu", 0),
                    "adjusted_switch_score": 50.0,
                    "reason_codes": ["risk_reduction"],
                },
            ],
            selected_action_key=("switch", "pikachu", 0),
            counterfactual_action_key=FakeOrder(),  # not a tuple
            best_stay_score=10.0,
            best_stay_action_key=("move", "tackle", 0),
            selection_changed=False,
            reason_codes=["risk_reduction"],
        )
        flat = json.dumps(scf)
        self.assertNotIn("levitate", flat)
        self.assertNotIn("leftovers", flat)
        self.assertNotIn("calmmind", flat)
        self.assertNotIn("recover", flat)
        self.assertNotIn("FakeOrder", flat)
        self.assertNotIn("<", flat)

    def test_persisted_payload_no_hidden_info(self):
        logger, main_path, live_path = _make_logger()
        try:
            scf = {
                "slot0": {
                    "chosen_is_switch": True,
                    "chosen_action_key": "switch|pikachu|0",
                    "counterfactual_action_key": "move|tackle|0",
                    "best_switch_action_key": "switch|pikachu|0",
                    "best_switch_score": 50.0,
                    "best_non_switch_action_key": "move|tackle|0",
                    "best_non_switch_score": 10.0,
                    "switch_vs_non_switch_delta": 40.0,
                    "selection_changed": True,
                    "reason_codes": ["risk_reduction"],
                },
                "slot1": {
                    "chosen_is_switch": False,
                    "chosen_action_key": "",
                    "counterfactual_action_key": "",
                    "best_switch_action_key": "",
                    "best_switch_score": None,
                    "best_non_switch_action_key": "",
                    "best_non_switch_score": None,
                    "switch_vs_non_switch_delta": None,
                    "selection_changed": False,
                    "reason_codes": [],
                },
                "joint_selection_changed": False,
            }
            _log_one(logger, scf)

            class FB:
                player_username = "test"
                turn = 1
                active_pokemon = [None, None]
                opponent_active_pokemon = [None, None]

            logger.save_battle("tag", "test", FB())

            with open(main_path) as f:
                record = json.loads(f.readline())
            persisted = record["audit_turns"][0][
                "switch_counterfactual"
            ]
            flat = json.dumps(persisted)
            # No hidden-info keywords leak through.
            for forbidden in (
                "ability", "item", "moves", "evs", "nature",
                "possible_abilities", "possible_items",
                "possible_moves", "base_stats",
            ):
                self.assertNotIn(forbidden, flat)
        finally:
            _cleanup([main_path, live_path])


class TestNoProductionCleanupImport(unittest.TestCase):
    def test_logger_does_not_import_cleanup(self):
        import doubles_decision_audit_logger as m
        with open(m.__file__) as f:
            content = f.read()
        self.assertNotIn("import poke_env_test_cleanup", content)
        self.assertNotIn("from poke_env_test_cleanup", content)

    def test_audit_metadata_does_not_import_cleanup(self):
        import doubles_engine.audit_metadata as m
        with open(m.__file__) as f:
            content = f.read()
        self.assertNotIn("import poke_env_test_cleanup", content)
        self.assertNotIn("from poke_env_test_cleanup", content)


if __name__ == "__main__":
    unittest.main()