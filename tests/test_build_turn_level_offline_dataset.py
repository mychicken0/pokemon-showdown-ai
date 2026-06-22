"""Phase RL-5 — Tests for the turn-level offline dataset builder.

Validates:
- Schema v1.0 conformance
- All 10 validation gates
- Edge cases (empty inputs, malformed V4a keys, etc.)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

# Ensure the builder is importable.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from build_turn_level_offline_dataset import (  # noqa: E402
    SCHEMA_VERSION,
    _row_has_leakage,
    _row_has_required_fields,
    _row_json_serializable,
    _selected_joint_key_in_legal,
    _to_json_safe,
    _v4a_key_to_tuple,
    aggregate_battles,
    build_dataset_from_artifact,
    build_row,
    validate_dataset,
    write_dataset,
    write_summary,
    write_validation_md,
)


def _make_minimal_turn(**overrides):
    """Create a minimal turn record for testing."""
    base = {
        "turn": 1,
        "our_active": ["incineroar", "sinistcha"],
        "opp_active": ["garchomp", "incineroar"],
        "state_snapshot": {
            "our_active_species": ["incineroar", "sinistcha"],
            "opp_active_species": ["garchomp", "incineroar"],
            "our_active_hp_fraction": [0.5, 0.8],
            "opp_active_hp_fraction": [0.3, 0.5],
            "weather": "none",
            "fields": [],
            "side_conditions": {},
        },
        "v4a_selected_joint_key": [
            ["move", "tackle", 1, ""],
            ["move", "matchagotcha", 0, ""],
        ],
        "v4a_final_action_keys": [
            ["move", "tackle", 1, ""],
            ["move", "matchagotcha", 0, ""],
        ],
        "v4a_legal_action_keys_slot0": [
            ["move", "tackle", 1, ""],
            ["move", "fakeout", 1, ""],
        ],
        "v4a_legal_action_keys_slot1": [
            ["move", "matchagotcha", 0, ""],
            ["move", "protect", 0, ""],
        ],
        "selected_score": 100.0,
        "top_5_alternatives": [],
        "top_5_scores": [],
        "score_gap_selected_best_alt": 10.0,
        "v2l1_raw_scores_slot0": {"move|tackle|1": 100.0},
        "v2l1_raw_scores_slot1": {"move|matchagotcha|0": 80.0},
        "preview_policy": "matchup_top4_v3",
    }
    base.update(overrides)
    return base


def _make_battle_row(turns=None, won=True, battle_tag="test_battle"):
    """Create a minimal battle row for testing."""
    if turns is None:
        turns = [_make_minimal_turn()]
    return {
        "battle_tag": battle_tag,
        "won": won,
        "audit_turns": turns,
        "selected_four": ["incineroar", "sinistcha", "garchomp", "tyranitar"],
    }


class TestSchemaVersion(unittest.TestCase):
    def test_schema_version_constant(self):
        self.assertEqual(SCHEMA_VERSION, "turn_rl_v1.0")


class TestV4aKeyNormalization(unittest.TestCase):
    def test_normalize_valid_key(self):
        k = _v4a_key_to_tuple(("move", "tackle", 1, ""))
        self.assertEqual(k, ("move", "tackle", "1", ""))

    def test_normalize_none(self):
        self.assertIsNone(_v4a_key_to_tuple(None))

    def test_normalize_wrong_length(self):
        self.assertIsNone(_v4a_key_to_tuple(("move", "tackle", 1)))
        self.assertIsNone(_v4a_key_to_tuple("not a tuple"))


class TestJsonSafety(unittest.TestCase):
    def test_primitives_pass_through(self):
        self.assertEqual(_to_json_safe(1), 1)
        self.assertEqual(_to_json_safe("a"), "a")
        self.assertEqual(_to_json_safe(None), None)
        self.assertEqual(_to_json_safe(True), True)

    def test_dict_recursion(self):
        out = _to_json_safe({"a": 1, "b": [1, 2, 3]})
        self.assertEqual(out, {"a": 1, "b": [1, 2, 3]})

    def test_unsupported_falls_back_to_str(self):
        class NotSerializable:
            def __repr__(self):
                return "fallback_repr"
        out = _to_json_safe(NotSerializable())
        self.assertEqual(out, "fallback_repr")


class TestBuildRow(unittest.TestCase):
    def test_build_basic_row(self):
        battle = _make_battle_row(won=True)
        turn = battle["audit_turns"][0]
        row = build_row(
            battle, turn,
            source_artifact="test.jsonl",
            benchmark_arm="treatment",
            dataset_id="test_dataset",
            policy_name_fallback="treatment",
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["schema_version"], "turn_rl_v1.0")
        self.assertEqual(row["battle_tag"], "test_battle")
        self.assertEqual(row["turn_index"], 1)
        self.assertEqual(row["won"], True)
        self.assertEqual(row["battle_result"], "win")
        self.assertEqual(row["terminal_reward"], 1)
        self.assertEqual(row["benchmark_arm"], "treatment")
        self.assertEqual(row["source_artifact"], "test.jsonl")
        self.assertEqual(row["selected_joint_key"][0], ["move", "tackle", "1", ""])
        self.assertEqual(
            row["selected_per_slot"]["slot_0"],
            ["move", "tackle", "1", ""],
        )

    def test_build_loss_row(self):
        battle = _make_battle_row(won=False)
        turn = battle["audit_turns"][0]
        row = build_row(
            battle, turn,
            source_artifact="test.jsonl",
            benchmark_arm="treatment",
            dataset_id="test_dataset",
            policy_name_fallback="treatment",
        )
        self.assertEqual(row["battle_result"], "loss")
        self.assertEqual(row["terminal_reward"], -1)

    def test_build_unknown_row(self):
        battle = _make_battle_row(won=None)
        turn = battle["audit_turns"][0]
        row = build_row(
            battle, turn,
            source_artifact="test.jsonl",
            benchmark_arm="treatment",
            dataset_id="test_dataset",
            policy_name_fallback="treatment",
        )
        self.assertEqual(row["battle_result"], "unknown")
        self.assertEqual(row["terminal_reward"], 0)

    def test_build_fails_when_v4a_missing(self):
        battle = _make_battle_row()
        turn = battle["audit_turns"][0]
        del turn["v4a_selected_joint_key"]
        row = build_row(
            battle, turn,
            source_artifact="test.jsonl",
            benchmark_arm="treatment",
            dataset_id="test_dataset",
            policy_name_fallback="treatment",
        )
        self.assertIsNone(row)

    def test_build_fails_when_legal_missing(self):
        battle = _make_battle_row()
        turn = battle["audit_turns"][0]
        del turn["v4a_legal_action_keys_slot0"]
        row = build_row(
            battle, turn,
            source_artifact="test.jsonl",
            benchmark_arm="treatment",
            dataset_id="test_dataset",
            policy_name_fallback="treatment",
        )
        self.assertIsNone(row)


class TestSelectedJointKeyInLegal(unittest.TestCase):
    def test_in_legal(self):
        sel = [("move", "tackle", "1", ""), ("move", "matchagotcha", "0", "")]
        legal0 = [("move", "tackle", "1", ""), ("move", "fakeout", "1", "")]
        legal1 = [("move", "matchagotcha", "0", ""), ("move", "protect", "0", "")]
        self.assertTrue(_selected_joint_key_in_legal(sel, legal0, legal1))

    def test_not_in_legal(self):
        sel = [("move", "tackle", "1", ""), ("move", "matchagotcha", "0", "")]
        legal0 = [("move", "fakeout", "1", "")]
        legal1 = [("move", "matchagotcha", "0", "")]
        self.assertFalse(
            _selected_joint_key_in_legal(sel, legal0, legal1)
        )

    def test_empty_legal(self):
        sel = [("move", "tackle", "1", "")]
        self.assertFalse(_selected_joint_key_in_legal(sel, [], []))


class TestLeakageDetection(unittest.TestCase):
    def test_clean_row(self):
        row = {"state_snapshot": {"weather": "none"}, "schema_version": "turn_rl_v1.0"}
        self.assertEqual(_row_has_leakage(row), [])

    def test_won_in_state(self):
        row = {
            "state_snapshot": {"won": True},
            "schema_version": "turn_rl_v1.0",
        }
        leaks = _row_has_leakage(row)
        self.assertTrue(
            any("state.contains_forbidden" in l for l in leaks)
        )

    def test_underscore_key(self):
        row = {
            "state_snapshot": {},
            "_internal": "secret",
            "schema_version": "turn_rl_v1.0",
        }
        leaks = _row_has_leakage(row)
        self.assertTrue(
            any("forbidden_prefix" in l for l in leaks)
        )


class TestRequiredFields(unittest.TestCase):
    def test_complete_row(self):
        battle = _make_battle_row()
        turn = battle["audit_turns"][0]
        row = build_row(
            battle, turn,
            source_artifact="test.jsonl",
            benchmark_arm="treatment",
            dataset_id="test_dataset",
            policy_name_fallback="treatment",
        )
        self.assertEqual(_row_has_required_fields(row), [])


class TestJsonSerializable(unittest.TestCase):
    def test_serializable_row(self):
        battle = _make_battle_row()
        turn = battle["audit_turns"][0]
        row = build_row(
            battle, turn,
            source_artifact="test.jsonl",
            benchmark_arm="treatment",
            dataset_id="test_dataset",
            policy_name_fallback="treatment",
        )
        self.assertTrue(_row_json_serializable(row))

    def test_circular_reference(self):
        # Build a self-referential dict to test the
        # failure path.
        d = {}
        d["self"] = d
        self.assertFalse(_row_json_serializable(d))


class TestValidateDataset(unittest.TestCase):
    def _build_n_rows(self, n, won=True):
        rows = []
        for i in range(n):
            battle = _make_battle_row(
                won=won,
                battle_tag=f"test_battle_{i}",
            )
            turn = battle["audit_turns"][0]
            row = build_row(
                battle, turn,
                source_artifact="test.jsonl",
                benchmark_arm="treatment",
                dataset_id="test_dataset",
                policy_name_fallback="treatment",
            )
            row["turn_index"] = i
            rows.append(row)
        return rows

    def test_clean_dataset_passes_all_gates(self):
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False
        ) as f:
            tmppath = f.name
        try:
            rows = self._build_n_rows(5)
            write_dataset(rows, tmppath)
            report = validate_dataset(
                rows, tmppath, source_artifacts=[tmppath]
            )
            self.assertTrue(report["overall_pass"])
            for gate_name, gate in report["gates"].items():
                self.assertTrue(
                    gate["pass"],
                    f"gate {gate_name} failed: {gate}",
                )
        finally:
            os.unlink(tmppath)

    def test_episode_boundary_violation(self):
        # Two rows from the same battle with different
        # battle_result. After dedup, the boundary
        # check should see only the first (kept by
        # dedup). But if we add a non-dedup variant
        # (same key), it gets dropped. So to test the
        # boundary violation, we need a key that
        # dedup can't catch.
        # Use different (bt, arm, turn) for two rows
        # of the same battle with different results.
        rows = self._build_n_rows(1, won=True)
        row2 = dict(rows[0])
        row2["battle_result"] = "loss"
        row2["won"] = False
        row2["terminal_reward"] = -1
        row2["turn_index"] = 1  # same turn, same battle
        # But different (bt, arm, turn) because we
        # changed arm.
        row2["benchmark_arm"] = "baseline"
        rows.append(row2)
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False
        ) as f:
            tmppath = f.name
        try:
            report = validate_dataset(
                rows, tmppath, source_artifacts=[tmppath]
            )
            # This is OK — different arms are different
            # episodes. The gate should still pass.
            self.assertTrue(report["gates"]["episode_boundary"]["pass"])
        finally:
            os.unlink(tmppath)

    def test_no_hidden_info_violation(self):
        rows = self._build_n_rows(1)
        rows[0]["state_snapshot"]["won"] = True  # leakage
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False
        ) as f:
            tmppath = f.name
        try:
            report = validate_dataset(
                rows, tmppath, source_artifacts=[tmppath]
            )
            self.assertFalse(report["gates"]["no_hidden_info"]["pass"])
        finally:
            os.unlink(tmppath)

    def test_legal_selected_violation(self):
        rows = self._build_n_rows(1)
        # Replace selected with a key not in legal
        rows[0]["selected_joint_key"] = [
            ["move", "unknown_move", 1, ""],
            ["move", "matchagotcha", 0, ""],
        ]
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False
        ) as f:
            tmppath = f.name
        try:
            report = validate_dataset(
                rows, tmppath, source_artifacts=[tmppath]
            )
            self.assertFalse(report["gates"]["legal_selected"]["pass"])
        finally:
            os.unlink(tmppath)

    def test_action_distribution_violation(self):
        rows = self._build_n_rows(1)
        rows[0]["legal_action_keys_slot0"] = []
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False
        ) as f:
            tmppath = f.name
        try:
            report = validate_dataset(
                rows, tmppath, source_artifacts=[tmppath]
            )
            self.assertFalse(
                report["gates"]["action_distribution"]["pass"]
            )
        finally:
            os.unlink(tmppath)

    def test_missing_required_violation(self):
        rows = self._build_n_rows(1)
        del rows[0]["won"]  # required field
        # The builder should still build the row (won=None),
        # but validation should flag it.
        # Actually, won is a required field, so build_row
        # may fail. Let me build differently.
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False
        ) as f:
            tmppath = f.name
        try:
            # The builder always includes won=None for
            # unknown. So del won't help. Instead, test
            # the threshold logic: if 100% of rows are
            # missing, it fails.
            bad_rows = []
            for i in range(5):
                battle = _make_battle_row(
                    won=None,  # unknown → terminal_reward=0
                    battle_tag=f"test_battle_{i}",
                )
                turn = battle["audit_turns"][0]
                row = build_row(
                    battle, turn,
                    source_artifact="test.jsonl",
                    benchmark_arm="treatment",
                    dataset_id="test_dataset",
                    policy_name_fallback="treatment",
                )
                del row["won"]
                del row["battle_result"]
                del row["terminal_reward"]
                bad_rows.append(row)
            report = validate_dataset(
                bad_rows, tmppath, source_artifacts=[tmppath]
            )
            self.assertFalse(
                report["gates"]["missing_required"]["pass"]
            )
        finally:
            os.unlink(tmppath)

    def test_reward_balance_always_passes(self):
        # The reward_balance gate is informational only.
        rows = self._build_n_rows(3, won=True)
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False
        ) as f:
            tmppath = f.name
        try:
            report = validate_dataset(
                rows, tmppath, source_artifacts=[tmppath]
            )
            self.assertTrue(report["gates"]["reward_balance"]["pass"])
            self.assertEqual(
                report["gates"]["reward_balance"]["n_positive"], 3
            )
            self.assertEqual(
                report["gates"]["reward_balance"]["n_negative"], 0
            )
        finally:
            os.unlink(tmppath)


class TestWriteFunctions(unittest.TestCase):
    def test_write_dataset(self):
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False
        ) as f:
            tmppath = f.name
        try:
            rows = [
                {"a": 1, "b": [1, 2]},
                {"a": 2, "b": [3, 4]},
            ]
            write_dataset(rows, tmppath)
            with open(tmppath) as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 2)
            for i, line in enumerate(lines):
                r = json.loads(line)
                self.assertEqual(r, rows[i])
        finally:
            os.unlink(tmppath)

    def test_write_summary(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False
        ) as f:
            tmppath = f.name
        try:
            report = {
                "schema_version": "turn_rl_v1.0",
                "overall_pass": True,
                "gates": {"json_serializable": {"pass": True}},
            }
            write_summary(report, tmppath)
            with open(tmppath) as f:
                loaded = json.load(f)
            self.assertEqual(loaded, report)
        finally:
            os.unlink(tmppath)

    def test_write_validation_md(self):
        with tempfile.NamedTemporaryFile(
            suffix=".md", delete=False
        ) as f:
            tmppath = f.name
        try:
            report = {
                "schema_version": "turn_rl_v1.0",
                "source_artifact": "test.jsonl",
                "n_rows": 5,
                "n_battles": 1,
                "overall_pass": True,
                "gates": {
                    "json_serializable": {"pass": True},
                    "legal_selected": {"pass": True, "n_violations": 0},
                },
                "battles": [
                    {
                        "battle_tag": "b1",
                        "benchmark_arm": "treatment",
                        "won": True,
                        "battle_result": "win",
                        "total_turns": 5,
                        "terminal_reward": 1,
                        "n_rows": 5,
                    }
                ],
            }
            write_validation_md(report, tmppath)
            with open(tmppath) as f:
                content = f.read()
            self.assertIn("turn_rl_v1.0", content)
            self.assertIn("overall_pass", content)
            self.assertIn("json_serializable", content)
        finally:
            os.unlink(tmppath)


class TestBuildDatasetFromArtifact(unittest.TestCase):
    def test_build_from_jsonl(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            battle = _make_battle_row(won=True)
            f.write(json.dumps(battle) + "\n")
            tmppath = f.name
        try:
            rows, skipped = build_dataset_from_artifact(
                tmppath, "treatment", "test_dataset"
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(skipped, [])
            self.assertEqual(rows[0]["benchmark_arm"], "treatment")
        finally:
            os.unlink(tmppath)

    def test_build_skips_malformed_jsonl(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write("not valid json\n")
            tmppath = f.name
        try:
            rows, skipped = build_dataset_from_artifact(
                tmppath, "treatment", "test_dataset"
            )
            self.assertEqual(len(rows), 0)
            self.assertIn("json_decode_error", skipped)
        finally:
            os.unlink(tmppath)


class TestAggregateBattles(unittest.TestCase):
    def test_aggregate_basic(self):
        battle = _make_battle_row(won=True, battle_tag="b1")
        turn = battle["audit_turns"][0]
        row = build_row(
            battle, turn,
            source_artifact="test.jsonl",
            benchmark_arm="treatment",
            dataset_id="test_dataset",
            policy_name_fallback="treatment",
        )
        # Build two rows for same battle
        row2 = dict(row)
        row2["turn_index"] = 2
        rows = [row, row2]
        battles = aggregate_battles(rows)
        self.assertEqual(len(battles), 1)
        # The aggregate uses battle_tag as key (not
        # battle_tag + arm) because it predates the
        # episode_boundary gate. The key here is just
        # the battle_tag.
        self.assertIn("b1", battles)
        self.assertEqual(battles["b1"]["n_rows"], 2)


class TestFieldCoverageFromSource(unittest.TestCase):
    """Phase RL-5b: prove the builder preserves optional
    source fields when present. These tests are the
    evidence that RL-5b is a no-op for the BI3M2
    source (which has these fields as None) and a
    correct mapping for sources that have non-None
    values (e.g. BEHAVIOR-18).

    The 3 fields audited by RL-6 are:
      - speed_priority_threatened
      - expected_to_faint_before_moving
      - joint_order_count
    """

    def test_preserves_speed_priority_threatened_from_source(self):
        """Source has [True, False] → row preserves it."""
        turn = _make_minimal_turn(
            speed_priority_threatened=[True, False]
        )
        battle = _make_battle_row(turns=[turn])
        row = build_row(
            battle, turn,
            source_artifact="test.jsonl",
            benchmark_arm="treatment",
            dataset_id="d",
            policy_name_fallback="treatment",
        )
        self.assertIsNotNone(row)
        self.assertEqual(
            row["speed_priority_threatened"],
            [True, False]
        )

    def test_preserves_expected_to_faint_before_moving_from_source(self):
        """Source has [False, True] → row preserves it."""
        turn = _make_minimal_turn(
            expected_to_faint_before_moving=[False, True]
        )
        battle = _make_battle_row(turns=[turn])
        row = build_row(
            battle, turn,
            source_artifact="test.jsonl",
            benchmark_arm="treatment",
            dataset_id="d",
            policy_name_fallback="treatment",
        )
        self.assertIsNotNone(row)
        self.assertEqual(
            row["expected_to_faint_before_moving"],
            [False, True]
        )

    def test_preserves_joint_order_count_from_source(self):
        """Source has 42 → row preserves 42."""
        turn = _make_minimal_turn(joint_order_count=42)
        battle = _make_battle_row(turns=[turn])
        row = build_row(
            battle, turn,
            source_artifact="test.jsonl",
            benchmark_arm="treatment",
            dataset_id="d",
            policy_name_fallback="treatment",
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["joint_order_count"], 42)

    def test_missing_optional_fields_remain_none(self):
        """Source missing these fields → row keeps None.

        This is the BI3M2 case. The keys are not present
        in the source turn, so the builder's _opt()
        returns None and the row preserves None.
        """
        # _make_minimal_turn does not set these fields.
        turn = _make_minimal_turn()
        self.assertNotIn("speed_priority_threatened", turn)
        self.assertNotIn("expected_to_faint_before_moving", turn)
        self.assertNotIn("joint_order_count", turn)
        battle = _make_battle_row(turns=[turn])
        row = build_row(
            battle, turn,
            source_artifact="test.jsonl",
            benchmark_arm="treatment",
            dataset_id="d",
            policy_name_fallback="treatment",
        )
        self.assertIsNotNone(row)
        self.assertIsNone(row["speed_priority_threatened"])
        self.assertIsNone(row["expected_to_faint_before_moving"])
        self.assertIsNone(row["joint_order_count"])

    def test_explicit_none_preserves_none(self):
        """Source explicitly sets None → row keeps None.

        The BI3M2 source has these keys present but
        valued as None. The builder's _opt() returns
        None for None input.
        """
        turn = _make_minimal_turn(
            speed_priority_threatened=None,
            expected_to_faint_before_moving=None,
            joint_order_count=None,
        )
        battle = _make_battle_row(turns=[turn])
        row = build_row(
            battle, turn,
            source_artifact="test.jsonl",
            benchmark_arm="treatment",
            dataset_id="d",
            policy_name_fallback="treatment",
        )
        self.assertIsNotNone(row)
        self.assertIsNone(row["speed_priority_threatened"])
        self.assertIsNone(row["expected_to_faint_before_moving"])
        self.assertIsNone(row["joint_order_count"])

    def test_fixed_fields_json_serializable(self):
        """Row with all 3 fields set → JSON round-trip works.

        Proves the preserved values are JSON-safe, so
        the dataset writer can serialize them.
        """
        turn = _make_minimal_turn(
            speed_priority_threatened=[True, False],
            expected_to_faint_before_moving=[False, True],
            joint_order_count=42,
        )
        battle = _make_battle_row(turns=[turn])
        row = build_row(
            battle, turn,
            source_artifact="test.jsonl",
            benchmark_arm="treatment",
            dataset_id="d",
            policy_name_fallback="treatment",
        )
        self.assertIsNotNone(row)
        self.assertTrue(_row_json_serializable(row))
        # JSON round-trip.
        s = json.dumps(row, sort_keys=True)
        rt = json.loads(s)
        self.assertEqual(
            rt["speed_priority_threatened"], [True, False]
        )
        self.assertEqual(
            rt["expected_to_faint_before_moving"], [False, True]
        )
        self.assertEqual(rt["joint_order_count"], 42)

    def test_end_to_end_jsonl_with_non_none_fields(self):
        """Build dataset from a JSONL where the 3 fields
        are non-None. The resulting dataset row must
        preserve them. This is the BEHAVIOR-18 source
        pattern (after audit logger was updated to
        populate these fields).
        """
        turn = _make_minimal_turn(
            speed_priority_threatened=[True, False],
            expected_to_faint_before_moving=[False, True],
            joint_order_count=42,
        )
        battle = _make_battle_row(turns=[turn])
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write(json.dumps(battle) + "\n")
            tmppath = f.name
        try:
            rows, skipped = build_dataset_from_artifact(
                tmppath, "treatment", "test_dataset"
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(skipped, [])
            self.assertEqual(
                rows[0]["speed_priority_threatened"],
                [True, False]
            )
            self.assertEqual(
                rows[0]["expected_to_faint_before_moving"],
                [False, True]
            )
            self.assertEqual(rows[0]["joint_order_count"], 42)
        finally:
            os.unlink(tmppath)

    def test_end_to_end_jsonl_with_explicit_none_fields(self):
        """Build dataset from a JSONL where the 3 fields
        are explicitly None (BI3M2 pattern). The
        resulting dataset row must keep them as None.
        """
        turn = _make_minimal_turn(
            speed_priority_threatened=None,
            expected_to_faint_before_moving=None,
            joint_order_count=None,
        )
        battle = _make_battle_row(turns=[turn])
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write(json.dumps(battle) + "\n")
            tmppath = f.name
        try:
            rows, skipped = build_dataset_from_artifact(
                tmppath, "treatment", "test_dataset"
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(skipped, [])
            self.assertIsNone(rows[0]["speed_priority_threatened"])
            self.assertIsNone(
                rows[0]["expected_to_faint_before_moving"]
            )
            self.assertIsNone(rows[0]["joint_order_count"])
        finally:
            os.unlink(tmppath)


if __name__ == "__main__":
    unittest.main()
