"""Phase SCENARIO-2 — Tests for the scenario
loader and validator.

Validates:
- Valid scenario loads
- Missing required field fails
- Invalid JSON fails
- Invalid turn key fails
- Invalid slot key fails
- Invalid action type fails
- Move ID normalization
- Switch action validates species
- Validators parse
- Schema is JSON-safe
- All 4 validator types work
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

from scenario_probe import (
    Scenario,
    ScenarioAction,
    ScenarioTurn,
    ScenarioValidator,
    ScenarioValidationError,
    _normalize_move_id,
    _normalize_species,
    load_scenario_dict,
    load_scenario_file,
    run_validators,
    validate_scripted_action_with_crosscheck,
    run_validators_with_canonical,
)


VALID_SCENARIO = {
    "scenario_id": "anti_tr_room_basic",
    "description": "Opp scripts Trick Room",
    "version": 1,
    "our_team_file": "/tmp/our_team.json",
    "opp_team_file": "/tmp/opp_team.json",
    "seed": 42,
    "audit_path_suffix": "anti_tr_room",
    "script": {
        "turn_1": {
            "opp_slot_0": {"move": "Trick Room", "target_pos": None},
            "opp_slot_1": {"move": "Protect", "target_pos": None},
        },
        "turn_2": {
            "opp_slot_0": {"move": "calm mind"},
        },
    },
    "validators": [
        {
            "name": "tr_used",
            "type": "expected_opp_action_used",
            "expected": True,
            "field": "trickroom",
        },
        {
            "name": "bot_legal",
            "type": "expected_bot_legal_response",
            "expected": "Taunt",
        },
    ],
}


class TestNormalize(unittest.TestCase):
    def test_move_normalize_lowercase(self):
        self.assertEqual(_normalize_move_id("TAUNT"), "taunt")

    def test_move_normalize_spaces(self):
        self.assertEqual(_normalize_move_id("Swords Dance"), "swordsdance")

    def test_move_normalize_dashes(self):
        self.assertEqual(_normalize_move_id("Trick-Room"), "trickroom")

    def test_move_normalize_underscores(self):
        self.assertEqual(_normalize_move_id("Wide_Guard"), "wideguard")

    def test_move_normalize_apostrophes(self):
        self.assertEqual(
            _normalize_move_id("King's Shield"), "kingsshield"
        )

    def test_species_normalize(self):
        self.assertEqual(
            _normalize_species("Garchomp"), "garchomp"
        )


class TestLoadValidScenario(unittest.TestCase):
    def test_minimal_scenario(self):
        minimal = {
            "scenario_id": "test",
            "our_team_file": "/tmp/our.json",
            "opp_team_file": "/tmp/opp.json",
            "script": {},
        }
        scen = load_scenario_dict(minimal)
        self.assertEqual(scen.scenario_id, "test")
        self.assertEqual(scen.version, 1)
        self.assertEqual(scen.seed, None)
        self.assertEqual(scen.audit_path_suffix, None)
        self.assertEqual(len(scen.script), 0)
        self.assertEqual(len(scen.validators), 0)

    def test_full_scenario(self):
        scen = load_scenario_dict(VALID_SCENARIO)
        self.assertEqual(scen.scenario_id, "anti_tr_room_basic")
        self.assertEqual(scen.version, 1)
        self.assertEqual(scen.seed, 42)
        self.assertEqual(scen.audit_path_suffix, "anti_tr_room")
        self.assertEqual(len(scen.script), 2)
        self.assertEqual(len(scen.validators), 2)

    def test_action_normalizes_move(self):
        scen = load_scenario_dict(VALID_SCENARIO)
        t1 = scen.script[1]
        self.assertEqual(
            t1.actions["opp_slot_0"].move, "trickroom"
        )
        self.assertEqual(
            t1.actions["opp_slot_1"].move, "protect"
        )
        self.assertEqual(
            t1.actions["opp_slot_0"].target_pos, None
        )

    def test_load_from_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(VALID_SCENARIO, f)
            path = f.name
        try:
            scen = load_scenario_file(path)
            self.assertEqual(
                scen.scenario_id, "anti_tr_room_basic"
            )
        finally:
            os.unlink(path)

    def test_load_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            load_scenario_file("/nonexistent/path.json")

    def test_load_file_invalid_json(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write("{invalid json")
            path = f.name
        try:
            with self.assertRaises(ScenarioValidationError):
                load_scenario_file(path)
        finally:
            os.unlink(path)


class TestRequiredFields(unittest.TestCase):
    def _drop(self, key):
        data = {k: v for k, v in VALID_SCENARIO.items()
                if k != key}
        return data

    def test_missing_scenario_id(self):
        with self.assertRaises(ScenarioValidationError) as cm:
            load_scenario_dict(self._drop("scenario_id"))
        self.assertIn("scenario_id", str(cm.exception))

    def test_missing_our_team_file(self):
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(self._drop("our_team_file"))

    def test_missing_opp_team_file(self):
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(self._drop("opp_team_file"))

    def test_missing_script(self):
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(self._drop("script"))


class TestTypeValidation(unittest.TestCase):
    def test_scenario_id_not_string(self):
        data = dict(VALID_SCENARIO, scenario_id=123)
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)

    def test_scenario_id_empty(self):
        data = dict(VALID_SCENARIO, scenario_id="   ")
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)

    def test_our_team_equals_opp_team(self):
        data = dict(
            VALID_SCENARIO,
            our_team_file="/tmp/same.json",
            opp_team_file="/tmp/same.json",
        )
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)

    def test_version_not_int(self):
        data = dict(VALID_SCENARIO, version="1")
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)

    def test_seed_not_int(self):
        data = dict(VALID_SCENARIO, seed="42")
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)


class TestTurnValidation(unittest.TestCase):
    def test_invalid_turn_key(self):
        data = dict(VALID_SCENARIO)
        data["script"] = {
            "round_1": {
                "opp_slot_0": {"move": "trickroom"}
            }
        }
        with self.assertRaises(ScenarioValidationError) as cm:
            load_scenario_dict(data)
        self.assertIn("turn_", str(cm.exception))

    def test_turn_zero(self):
        data = dict(VALID_SCENARIO)
        data["script"] = {
            "turn_0": {
                "opp_slot_0": {"move": "trickroom"}
            }
        }
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)

    def test_turn_not_dict(self):
        data = dict(VALID_SCENARIO)
        data["script"] = {
            "turn_1": "not a dict"
        }
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)

    def test_invalid_slot_key(self):
        data = dict(VALID_SCENARIO)
        data["script"] = {
            "turn_1": {
                "opp_slot_2": {"move": "trickroom"}
            }
        }
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)

    def test_our_slot_key_rejected(self):
        # The script is for the OPP, so our_slot
        # keys should be rejected
        data = dict(VALID_SCENARIO)
        data["script"] = {
            "turn_1": {
                "our_slot_0": {"move": "trickroom"}
            }
        }
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)

    def test_no_duplicate_turns_via_two_scripts(self):
        # Two separate scenarios with the same
        # turn_N are independent (each scenario
        # has its own script). This is tested
        # implicitly; dict literals can't have
        # duplicate keys.
        a = dict(VALID_SCENARIO, script={
            "turn_1": {"opp_slot_0": {"move": "trickroom"}},
        })
        b = dict(VALID_SCENARIO, script={
            "turn_1": {"opp_slot_0": {"move": "protect"}},
        })
        sa = load_scenario_dict(a)
        sb = load_scenario_dict(b)
        # Both are valid; their scripts differ
        self.assertNotEqual(
            sa.script[1].actions["opp_slot_0"].move,
            sb.script[1].actions["opp_slot_0"].move,
        )


class TestActionValidation(unittest.TestCase):
    def test_action_not_dict(self):
        data = dict(VALID_SCENARIO)
        data["script"] = {
            "turn_1": {"opp_slot_0": "not a dict"}
        }
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)

    def test_invalid_action_key(self):
        data = dict(VALID_SCENARIO)
        data["script"] = {
            "turn_1": {
                "opp_slot_0": {
                    "move": "trickroom",
                    "weird_key": "value",
                }
            }
        }
        with self.assertRaises(ScenarioValidationError) as cm:
            load_scenario_dict(data)
        self.assertIn("weird_key", str(cm.exception))

    def test_both_move_and_switch(self):
        data = dict(VALID_SCENARIO)
        data["script"] = {
            "turn_1": {
                "opp_slot_0": {
                    "move": "trickroom",
                    "switch": "garchomp",
                }
            }
        }
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)

    def test_empty_move(self):
        data = dict(VALID_SCENARIO)
        data["script"] = {
            "turn_1": {
                "opp_slot_0": {"move": "  "}
            }
        }
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)

    def test_invalid_target_pos(self):
        data = dict(VALID_SCENARIO)
        data["script"] = {
            "turn_1": {
                "opp_slot_0": {
                    "move": "trickroom",
                    "target_pos": 5,
                }
            }
        }
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)

    def test_noop_action(self):
        # Action with no move and no switch is OK
        # (slot does nothing)
        data = dict(VALID_SCENARIO)
        data["script"] = {
            "turn_1": {
                "opp_slot_0": {},
                "opp_slot_1": {"move": "trickroom"},
            }
        }
        scen = load_scenario_dict(data)
        self.assertTrue(
            scen.script[1].actions["opp_slot_0"].is_noop()
        )

    def test_switch_action(self):
        data = dict(VALID_SCENARIO)
        data["script"] = {
            "turn_1": {
                "opp_slot_0": {"switch": "Garchomp"}
            }
        }
        scen = load_scenario_dict(data)
        self.assertEqual(
            scen.script[1].actions["opp_slot_0"].switch,
            "garchomp",
        )


class TestValidators(unittest.TestCase):
    def test_validators_parse(self):
        scen = load_scenario_dict(VALID_SCENARIO)
        self.assertEqual(len(scen.validators), 2)
        self.assertEqual(scen.validators[0].name, "tr_used")
        self.assertEqual(
            scen.validators[0].type,
            "expected_opp_action_used",
        )
        self.assertEqual(
            scen.validators[0].field, "trickroom"
        )
        self.assertEqual(
            scen.validators[1].type,
            "expected_bot_legal_response",
        )

    def test_validator_invalid_type(self):
        data = dict(VALID_SCENARIO)
        data["validators"] = [
            {
                "name": "bad",
                "type": "not_a_real_type",
                "expected": True,
            }
        ]
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)

    def test_validator_missing_name(self):
        data = dict(VALID_SCENARIO)
        data["validators"] = [
            {
                "type": "no_script_failures",
            }
        ]
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)

    def test_validator_missing_field(self):
        data = dict(VALID_SCENARIO)
        data["validators"] = [
            {
                "name": "x",
                "type": "expected_opp_action_used",
                "expected": True,
                # missing 'field'
            }
        ]
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)

    def test_validator_empty_list(self):
        data = dict(VALID_SCENARIO, validators=[])
        scen = load_scenario_dict(data)
        self.assertEqual(len(scen.validators), 0)

    def test_validator_describe(self):
        scen = load_scenario_dict(VALID_SCENARIO)
        v = scen.validators[0]
        s = v.describe()
        self.assertIn("trickroom", s)


class TestRunValidators(unittest.TestCase):
    def test_no_audit_data_with_no_script_failures(self):
        data = dict(
            VALID_SCENARIO,
            validators=[
                {"name": "x", "type": "no_script_failures"}
            ],
        )
        scen = load_scenario_dict(data)
        results = run_validators(scen, [])
        self.assertEqual(len(results), 1)
        _, passed, _ = results[0]
        self.assertTrue(passed)

    def test_opp_action_used_validator(self):
        # Build audit data with the trigger
        audit = [{
            "audit_turns": [
                {
                    "turn": 1,
                    "opponent_actions": {
                        "opponent_used_trickroom": True
                    },
                    "state_snapshot": {},
                }
            ]
        }]
        data = dict(
            VALID_SCENARIO,
            validators=[
                {
                    "name": "x",
                    "type": "expected_opp_action_used",
                    "expected": True,
                    "field": "trickroom",
                }
            ],
        )
        scen = load_scenario_dict(data)
        results = run_validators(scen, audit)
        _, passed, msg = results[0]
        self.assertTrue(passed)
        self.assertIn("ok", msg)

    def test_opp_action_not_used_fails(self):
        audit = [{
            "audit_turns": [
                {
                    "turn": 1,
                    "opponent_actions": {
                        "opponent_used_trickroom": False
                    },
                    "state_snapshot": {},
                }
            ]
        }]
        data = dict(
            VALID_SCENARIO,
            validators=[
                {
                    "name": "x",
                    "type": "expected_opp_action_used",
                    "expected": True,
                    "field": "trickroom",
                }
            ],
        )
        scen = load_scenario_dict(data)
        results = run_validators(scen, audit)
        _, passed, msg = results[0]
        self.assertFalse(passed)
        self.assertIn("never True", msg)

    def test_bot_legal_response_validator(self):
        audit = [{
            "audit_turns": [
                {
                    "turn": 1,
                    "v2l1_legal_action_keys_slot0": [
                        ["move", "Taunt", 1],
                        ["move", "earthquake", 1],
                    ],
                    "v2l1_legal_action_keys_slot1": [],
                    "state_snapshot": {},
                }
            ]
        }]
        data = dict(
            VALID_SCENARIO,
            validators=[
                {
                    "name": "x",
                    "type": "expected_bot_legal_response",
                    "expected": "Taunt",
                }
            ],
        )
        scen = load_scenario_dict(data)
        results = run_validators(scen, audit)
        _, passed, msg = results[0]
        self.assertTrue(passed)
        self.assertIn("legal", msg)

    def test_audit_signal_validator(self):
        audit = [{
            "audit_turns": [
                {
                    "turn": 1,
                    "state_snapshot": {
                        "weather": ["raindance"]
                    },
                    "opponent_actions": {},
                }
            ]
        }]
        data = dict(
            VALID_SCENARIO,
            validators=[
                {
                    "name": "x",
                    "type": "expected_audit_signal",
                    "expected": ["raindance"],
                    "field": "weather",
                }
            ],
        )
        scen = load_scenario_dict(data)
        results = run_validators(scen, audit)
        _, passed, msg = results[0]
        self.assertTrue(passed)


class TestExpectedScriptedAction(unittest.TestCase):
    """Phase SCENARIO-11b: tests for the
    Option C canonical signal validator.
    The canonical signal is the baseline
    audit's ``scripted_actions``; the
    treatment audit's ``opponent_actions``
    is a diagnostic cross-check.
    """

    def _baseline_with_move(self, move: str) -> list:
        return [{
            "battle_tag": "test-1",
            "scenario_id": "test",
            "scripted_actions": [
                {
                    "turn": 1,
                    "slot_idx": 0,
                    "move": move,
                    "executed": True,
                },
            ],
        }]

    def _baseline_empty(self) -> list:
        return [{
            "battle_tag": "test-1",
            "scenario_id": "test",
            "scripted_actions": [],
        }]

    def _treatment_with_opp_used(self, field, val):
        return [{
            "battle_tag": "test-1",
            "audit_turns": [
                {
                    "turn": 1,
                    "opponent_actions": {
                        f"opponent_used_{field}": val,
                    },
                },
            ],
        }]

    def _treatment_with_no_opp_actions(self) -> list:
        return [{
            "battle_tag": "test-1",
            "audit_turns": [
                {"turn": 1, "opponent_actions": None},
            ],
        }]

    def test_pass_when_baseline_has_move(self):
        """Canonical: baseline scripted_actions
        has the move with executed=True. Pass."""
        result = validate_scripted_action_with_crosscheck(
            move="trickroom",
            baseline_records=self._baseline_with_move("trickroom"),
            treatment_records=None,
        )
        self.assertTrue(result["canonical_signal_fired"])
        self.assertIsNone(result["bot_opp_action_crosscheck"])
        self.assertFalse(result["bot_opp_action_gap"])
        self.assertTrue(result["passed"])

    def test_fail_when_baseline_missing_move(self):
        """No canonical match: fail."""
        result = validate_scripted_action_with_crosscheck(
            move="tailwind",
            baseline_records=self._baseline_with_move("trickroom"),
            treatment_records=None,
        )
        self.assertFalse(result["canonical_signal_fired"])
        self.assertFalse(result["passed"])

    def test_fail_when_baseline_empty(self):
        """Empty baseline: fail."""
        result = validate_scripted_action_with_crosscheck(
            move="trickroom",
            baseline_records=self._baseline_empty(),
            treatment_records=None,
        )
        self.assertFalse(result["canonical_signal_fired"])
        self.assertFalse(result["passed"])

    def test_gap_true_when_treatment_missing_opp_action(self):
        """Canonical fires but treatment
        has no opp_actions: gap=True,
        but still passes via canonical."""
        result = validate_scripted_action_with_crosscheck(
            move="trickroom",
            baseline_records=self._baseline_with_move("trickroom"),
            treatment_records=self._treatment_with_no_opp_actions(),
        )
        self.assertTrue(result["canonical_signal_fired"])
        self.assertIsNone(result["bot_opp_action_crosscheck"])
        self.assertTrue(result["bot_opp_action_gap"])
        self.assertTrue(result["passed"])

    def test_gap_true_when_treatment_field_explicit_false(self):
        """Canonical fires but treatment
        says opp_used=False: gap=True,
        still passes via canonical."""
        result = validate_scripted_action_with_crosscheck(
            move="trickroom",
            baseline_records=self._baseline_with_move("trickroom"),
            treatment_records=self._treatment_with_opp_used(
                "trickroom", False
            ),
        )
        self.assertTrue(result["canonical_signal_fired"])
        self.assertFalse(result["bot_opp_action_crosscheck"])
        self.assertTrue(result["bot_opp_action_gap"])
        self.assertTrue(result["passed"])

    def test_gap_false_when_both_agree(self):
        """Canonical fires AND treatment
        says opp_used=True: gap=False."""
        result = validate_scripted_action_with_crosscheck(
            move="trickroom",
            baseline_records=self._baseline_with_move("trickroom"),
            treatment_records=self._treatment_with_opp_used(
                "trickroom", True
            ),
        )
        self.assertTrue(result["canonical_signal_fired"])
        self.assertTrue(result["bot_opp_action_crosscheck"])
        self.assertFalse(result["bot_opp_action_gap"])
        self.assertTrue(result["passed"])

    def test_no_crash_when_treatment_field_missing(self):
        """Treatment has opp_actions but
        the field is missing: crosscheck=None,
        gap=True."""
        result = validate_scripted_action_with_crosscheck(
            move="trickroom",
            baseline_records=self._baseline_with_move("trickroom"),
            treatment_records=self._treatment_with_opp_used(
                "some_other_field", True
            ),
        )
        self.assertTrue(result["canonical_signal_fired"])
        self.assertIsNone(result["bot_opp_action_crosscheck"])
        self.assertTrue(result["bot_opp_action_gap"])
        self.assertTrue(result["passed"])

    def test_no_crash_when_treatment_records_empty(self):
        """Treatment records empty: crosscheck=None,
        gap=False (no treatment provided)."""
        result = validate_scripted_action_with_crosscheck(
            move="trickroom",
            baseline_records=self._baseline_with_move("trickroom"),
            treatment_records=[],
        )
        self.assertTrue(result["canonical_signal_fired"])
        self.assertIsNone(result["bot_opp_action_crosscheck"])
        self.assertFalse(result["bot_opp_action_gap"])
        self.assertTrue(result["passed"])

    def test_supports_trickroom(self):
        result = validate_scripted_action_with_crosscheck(
            move="trickroom",
            baseline_records=self._baseline_with_move("Trick Room"),
        )
        self.assertTrue(result["canonical_signal_fired"])

    def test_supports_tailwind(self):
        result = validate_scripted_action_with_crosscheck(
            move="tailwind",
            baseline_records=self._baseline_with_move("tailwind"),
        )
        self.assertTrue(result["canonical_signal_fired"])

    def test_supports_swordsdance(self):
        result = validate_scripted_action_with_crosscheck(
            move="swordsdance",
            baseline_records=self._baseline_with_move(
                "Swords Dance"
            ),
        )
        self.assertTrue(result["canonical_signal_fired"])

    def test_supports_heatwave(self):
        result = validate_scripted_action_with_crosscheck(
            move="heatwave",
            baseline_records=self._baseline_with_move("Heat Wave"),
        )
        self.assertTrue(result["canonical_signal_fired"])

    def test_failed_action_does_not_count(self):
        """An action with executed=False
        should NOT count as canonical fired."""
        baseline = [{
            "scripted_actions": [
                {
                    "turn": 1,
                    "slot_idx": 0,
                    "move": "trickroom",
                    "executed": False,
                },
            ],
        }]
        result = validate_scripted_action_with_crosscheck(
            move="trickroom",
            baseline_records=baseline,
            treatment_records=None,
        )
        self.assertFalse(result["canonical_signal_fired"])
        self.assertFalse(result["passed"])

    def test_run_validators_with_canonical(self):
        """Test the higher-level
        run_validators_with_canonical
        function with a scripted scenario."""
        data = dict(
            VALID_SCENARIO,
            validators=[
                {
                    "name": "tr_actually_used",
                    "type": "expected_scripted_action",
                    "expected": True,
                    "field": "trickroom",
                },
                {
                    "name": "no_failures",
                    "type": "no_script_failures",
                },
            ],
        )
        scen = load_scenario_dict(data)
        baseline = self._baseline_with_move("trickroom")
        treatment = self._treatment_with_no_opp_actions()
        results = run_validators_with_canonical(
            scen, baseline, treatment
        )
        self.assertEqual(len(results), 2)
        # scripted_action validator
        r0 = results[0]
        self.assertEqual(r0["validator"].type,
                         "expected_scripted_action")
        self.assertTrue(r0["passed"])
        self.assertTrue(r0["canonical_signal_fired"])
        self.assertTrue(r0["bot_opp_action_gap"])
        # no_script_failures
        r1 = results[1]
        self.assertEqual(r1["validator"].type,
                         "no_script_failures")
        self.assertTrue(r1["passed"])

    def test_scenario_loader_accepts_new_type(self):
        """The scenario loader should accept
        ``expected_scripted_action`` as a
        valid validator type."""
        data = dict(
            VALID_SCENARIO,
            validators=[
                {
                    "name": "x",
                    "type": "expected_scripted_action",
                    "expected": True,
                    "field": "trickroom",
                },
            ],
        )
        # Should not raise
        scen = load_scenario_dict(data)
        self.assertEqual(len(scen.validators), 1)
        v = scen.validators[0]
        self.assertEqual(v.type, "expected_scripted_action")
        self.assertEqual(v.field, "trickroom")
        self.assertTrue(v.expected)

    def test_scenario_loader_rejects_invalid_type(self):
        """The scenario loader should reject
        unknown validator types."""
        from scenario_probe import ScenarioValidationError
        data = dict(
            VALID_SCENARIO,
            validators=[
                {
                    "name": "x",
                    "type": "expected_unknown_type",
                    "expected": True,
                    "field": "x",
                },
            ],
        )
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data)


class TestSchemaJsonSafe(unittest.TestCase):
    def test_scenario_is_json_safe(self):
        scen = load_scenario_dict(VALID_SCENARIO)
        # Should be JSON-serializable (no
        # dataclass instances in fields that
        # break JSON).
        try:
            json.dumps({
                "scenario_id": scen.scenario_id,
                "version": scen.version,
                "script": {
                    turn: {
                        slot: {
                            "move": a.move,
                            "target_pos": a.target_pos,
                            "switch": a.switch,
                        }
                        for slot, a in t.actions.items()
                    }
                    for turn, t in scen.script.items()
                },
            })
        except (TypeError, ValueError) as e:
            self.fail(f"Scenario is not JSON-safe: {e}")

    def test_validators_list_is_json_safe(self):
        scen = load_scenario_dict(VALID_SCENARIO)
        try:
            json.dumps([
                {
                    "name": v.name,
                    "type": v.type,
                    "expected": v.expected,
                    "field": v.field,
                    "threshold": v.threshold,
                }
                for v in scen.validators
            ])
        except (TypeError, ValueError) as e:
            self.fail(f"Validators are not JSON-safe: {e}")


class TestPureFunction(unittest.TestCase):
    def test_load_is_pure(self):
        # load_scenario_dict should not have
        # side effects (no global state
        # modification).
        a = load_scenario_dict(VALID_SCENARIO)
        b = load_scenario_dict(VALID_SCENARIO)
        # Equal content
        self.assertEqual(a.scenario_id, b.scenario_id)
        self.assertEqual(a.version, b.version)
        # But separate instances
        self.assertIsNot(a.script, b.script)


if __name__ == "__main__":
    unittest.main()


class TestLeadField(unittest.TestCase):
    """Phase SCENARIO-4: scenario file may
    include a 'lead' dict mapping slot
    keys to species names."""

    def test_lead_field_parsed(self):
        from scenario_probe import load_scenario_dict
        data = {
            "scenario_id": "test",
            "our_team_file": "data/curated_teams/control4a/team_020.json",
            "our_team_file": "data/curated_teams/control4a/team_027.json",
            "opp_team_file": "data/curated_teams/control4a/team_020.json",
            "our_team_file": "data/curated_teams/control4a/team_027.json",
            "lead": {
                "opp_slot_0": "Hatterene",
                "opp_slot_1": "Tinkaton"
            },
            "script": {},
        }
        sc = load_scenario_dict(data, source_path="<test>")
        self.assertEqual(sc.lead, {
            "opp_slot_0": "Hatterene",
            "opp_slot_1": "Tinkaton"
        })

    def test_lead_optional(self):
        from scenario_probe import load_scenario_dict
        data = {
            "scenario_id": "test",
            "our_team_file": "data/curated_teams/control4a/team_020.json",
            "our_team_file": "data/curated_teams/control4a/team_027.json",
            "opp_team_file": "data/curated_teams/control4a/team_020.json",
            "our_team_file": "data/curated_teams/control4a/team_027.json",
            "script": {},
        }
        sc = load_scenario_dict(data, source_path="<test>")
        self.assertIsNone(sc.lead)

    def test_lead_invalid_slot_raises(self):
        from scenario_probe import (
            load_scenario_dict, ScenarioValidationError,
        )
        data = {
            "scenario_id": "test",
            "our_team_file": "data/curated_teams/control4a/team_020.json",
            "our_team_file": "data/curated_teams/control4a/team_027.json",
            "opp_team_file": "data/curated_teams/control4a/team_020.json",
            "our_team_file": "data/curated_teams/control4a/team_027.json",
            "lead": {
                "opp_slot_99": "Hatterene",
            },
            "script": {},
        }
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data, source_path="<test>")


class TestLeadField(unittest.TestCase):
    """Phase SCENARIO-4: scenario file may
    include a 'lead' dict mapping slot
    keys to species names."""

    def test_lead_field_parsed(self):
        from scenario_probe import load_scenario_dict
        data = {
            "scenario_id": "test",
            "our_team_file": "data/curated_teams/control4a/team_027.json",
            "opp_team_file": "data/curated_teams/control4a/team_020.json",
            "lead": {
                "opp_slot_0": "Hatterene",
                "opp_slot_1": "Tinkaton"
            },
            "script": {},
        }
        sc = load_scenario_dict(data, source_path="<test>")
        self.assertEqual(sc.lead, {
            "opp_slot_0": "Hatterene",
            "opp_slot_1": "Tinkaton"
        })

    def test_lead_optional(self):
        from scenario_probe import load_scenario_dict
        data = {
            "scenario_id": "test",
            "our_team_file": "data/curated_teams/control4a/team_027.json",
            "opp_team_file": "data/curated_teams/control4a/team_020.json",
            "script": {},
        }
        sc = load_scenario_dict(data, source_path="<test>")
        self.assertIsNone(sc.lead)

    def test_lead_invalid_slot_raises(self):
        from scenario_probe import (
            load_scenario_dict, ScenarioValidationError,
        )
        data = {
            "scenario_id": "test",
            "our_team_file": "data/curated_teams/control4a/team_027.json",
            "opp_team_file": "data/curated_teams/control4a/team_020.json",
            "lead": {
                "opp_slot_99": "Hatterene",
            },
            "script": {},
        }
        with self.assertRaises(ScenarioValidationError):
            load_scenario_dict(data, source_path="<test>")
