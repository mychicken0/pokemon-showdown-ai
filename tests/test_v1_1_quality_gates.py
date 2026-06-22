"""Phase RL-DATA-2b: v1.1 quality gate tests.

Validates:
- analyzer accepts a valid v1.1 smoke fixture (built via real builder)
- analyzer still accepts v1.0 fixture (backward compat)
- analyzer reports v1.1 schema count
- gates 11-18 pass on a valid v1.1 row
- used_species_ability_inference=True triggers BLOCKED
- blocked_action_resurrected_by_joint=True triggers BLOCKED
- impossible_target_detected=True triggers BLOCKED
- unknown support move is surfaced as unknown_needs_probe
- missing explicit v1.1 key is detected as a warning
- dry-run remains compatible with v1.1 rows
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from collections import Counter
from typing import Any, Dict, List

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from analyze_turn_level_offline_dataset_quality import (  # noqa: E402
    ACCEPTED_SCHEMAS,
    EXPECTED_SCHEMA,
    V1_1_BLOCK_FIELDS,
    V1_1_GATE_FIELDS,
    _check_v1_1_gates,
    analyze,
    main,
)
from build_turn_level_offline_dataset import build_row


def _make_fake_turn(
    v4a_legal0=None,
    v4a_legal1=None,
    v4a_sel=None,
    v4a_final=None,
    weather="raindance",
    fields=None,
    revealed_ability_source="revealed",
):
    """Build a fake audit turn dict for v1.1 builder testing."""
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
        "turn": 1,
        "state_snapshot": {
            "our_active_species": ["Incineroar", "Politoed"],
            "opp_active_species": ["Garchomp", "Tyranitar"],
            "our_active_hp_fraction": [0.5, 0.8],
            "opp_active_hp_fraction": [0.3, 0.5],
            "weather": weather,
            "fields": fields,
        },
        "v4a_legal_action_keys_slot0": v4a_legal0,
        "v4a_legal_action_keys_slot1": v4a_legal1,
        "v4a_selected_joint_key": v4a_sel,
        "v4a_final_action_keys": v4a_final,
        "selected_score": 100.0,
        "top_5_alternatives": [],
        "top_5_scores": [],
        "score_gap_selected_best_alt": 10.0,
        "v2l1_raw_scores_slot0": {},
        "v2l1_raw_scores_slot1": {},
        "switch_counterfactual": None,
        "speed_priority_threatened": None,
        "expected_to_faint_before_moving": None,
        "overkill_penalty_triggered": False,
        "focus_fire_triggered": False,
        "stale_target_avoided": False,
        "narrow_ally_heal_candidate_blocked_slot0": None,
        "narrow_ally_heal_candidate_blocked_slot1": None,
        "joint_order_count": 1,
        "runtime_mode": "gen9randomdoublesbattle",
        "revealed_ability_source": revealed_ability_source,
    }


def _make_fake_battle(turns=None, won=True):
    if turns is None:
        turns = [_make_fake_turn()]
    return {
        "battle_tag": "b_v11",
        "won": won,
        "audit_turns": turns,
    }


def _build_v11_row(**overrides):
    """Build a v1.1 row using the real builder."""
    turn = _make_fake_turn(**overrides)
    battle = _make_fake_battle(turns=[turn])
    row = build_row(
        battle, turn, "test.jsonl", "treatment", "test_ds", "matchup_top4_v3"
    )
    assert row is not None
    return row


def _build_v11_row_with_hard_block(field_name):
    """Build a v1.1 row with a hard-block field set to True.

    The current builder hardcodes used_species_ability_inference
    to False. For testing the gate's BLOCKED path, we override
    that field after the build.
    """
    row = _build_v11_row()
    row[field_name] = True
    return row


def _write_jsonl(rows, path):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


class TestV11GateBasics(unittest.TestCase):
    """Test the v1.1 gate function in isolation."""

    def test_clean_v11_row_no_blocks(self):
        # Build a row with only known support moves
        # (raindance + protect). The default builder row
        # includes fakeout which is flagged as unknown because
        # the audit doesn't record base_power. Using known
        # support moves here gives a clean row.
        row = _build_v11_row(
            v4a_legal0=[["move", "raindance", 0, "no_mechanic"]],
            v4a_legal1=[["move", "protect", 0, "no_mechanic"]],
        )
        result = _check_v1_1_gates([row], Counter({"turn_rl_v1.1": 1}))
        self.assertEqual(result["v11_n_rows"], 1)
        # Clean v1.1 row from the builder: no hard blocks
        # (the builder always emits False for safety-block
        # fields per the v1.1 spec)
        self.assertEqual(len(result["hard_blocks"]), 0)
        # Should be READY
        self.assertEqual(result["readiness_impact"], "READY")

    def test_v10_n_rows(self):
        row1 = _build_v11_row()
        row2 = _build_v11_row()
        result = _check_v1_1_gates(
            [row1, row2], Counter({"turn_rl_v1.1": 2})
        )
        self.assertEqual(result["v11_n_rows"], 2)
        self.assertEqual(result["v10_n_rows"], 0)

    def test_mixed_v10_v11(self):
        v10_row = _build_v11_row()
        v10_row["schema_version"] = "turn_rl_v1.0"
        # Remove v1.1-only fields from v10 row
        for f in list(v10_row.keys()):
            if f in V1_1_GATE_FIELDS:
                v10_row.pop(f, None)
        v11_row = _build_v11_row()
        rows = [v10_row, v11_row]
        schema = Counter({"turn_rl_v1.0": 1, "turn_rl_v1.1": 1})
        result = _check_v1_1_gates(rows, schema)
        self.assertEqual(result["v11_n_rows"], 1)
        self.assertEqual(result["v10_n_rows"], 1)
        self.assertEqual(result["schema_coverage"]["v10"], 1)
        self.assertEqual(result["schema_coverage"]["v11"], 1)

    def test_field_coverage_100pct(self):
        # A clean v1.1 row should have high field coverage
        row = _build_v11_row()
        result = _check_v1_1_gates([row], Counter({"turn_rl_v1.1": 1}))
        # Most v1.1 fields should be present in a clean row
        for f, cov in result["field_coverage"].items():
            self.assertEqual(
                cov, 1.0,
                f"Field {f} coverage = {cov}"
            )

    def test_field_coverage_missing(self):
        # Missing fields reduce coverage and trigger warnings
        row = _build_v11_row()
        # Remove some v1.1 fields
        row.pop("config_hash", None)
        row.pop("setter_move_legal", None)
        result = _check_v1_1_gates([row], Counter({"turn_rl_v1.1": 1}))
        self.assertEqual(result["field_coverage"]["config_hash"], 0.0)
        self.assertEqual(result["field_coverage"]["setter_move_legal"], 0.0)
        # Warnings should be present
        self.assertGreater(len(result["warnings"]), 0)
        # Readiness is WARN (warnings, no blocks)
        self.assertEqual(result["readiness_impact"], "WARN")

    def test_hard_block_used_species(self):
        # used_species_ability_inference=True must trigger BLOCKED
        # The builder hardcodes this to False; we override for the test
        row = _build_v11_row_with_hard_block(
            "used_species_ability_inference"
        )
        result = _check_v1_1_gates([row], Counter({"turn_rl_v1.1": 1}))
        self.assertGreater(len(result["hard_blocks"]), 0)
        self.assertIn(
            "used_species_ability_inference",
            str(result["hard_blocks"])
        )
        self.assertEqual(result["readiness_impact"], "BLOCKED")

    def test_hard_block_impossible_target(self):
        row = _build_v11_row_with_hard_block("impossible_target_detected")
        result = _check_v1_1_gates([row], Counter({"turn_rl_v1.1": 1}))
        self.assertGreater(len(result["hard_blocks"]), 0)
        self.assertIn(
            "impossible_target_detected",
            str(result["hard_blocks"])
        )
        self.assertEqual(result["readiness_impact"], "BLOCKED")

    def test_hard_block_resurrect(self):
        row = _build_v11_row_with_hard_block(
            "blocked_action_resurrected_by_joint"
        )
        result = _check_v1_1_gates([row], Counter({"turn_rl_v1.1": 1}))
        self.assertGreater(len(result["hard_blocks"]), 0)
        self.assertIn(
            "blocked_action_resurrected_by_joint",
            str(result["hard_blocks"])
        )
        self.assertEqual(result["readiness_impact"], "BLOCKED")

    def test_unknown_support_move_surfaced(self):
        # unknown_support_move_detected=True should be surfaced
        # but not block (it's a soft warning per Gate 17 spec)
        row = _build_v11_row(
            v4a_legal0=[["move", "newgenmove", 0, "no_mechanic"]],
        )
        result = _check_v1_1_gates([row], Counter({"turn_rl_v1.1": 1}))
        self.assertEqual(result["n_unknown_support_moves"], 1)
        # Unknown is not a hard block per Gate 17 spec
        self.assertEqual(len(result["hard_blocks"]), 0)

    def test_no_v11_rows_returns_warn(self):
        # If there are no rows, the result is WARN
        result = _check_v1_1_gates([], Counter())
        self.assertEqual(result["v11_n_rows"], 0)
        self.assertEqual(result["readiness_impact"], "WARN")


class TestV11GateConstants(unittest.TestCase):
    """Test the v1.1 gate constants themselves."""

    def test_accepted_schemas(self):
        self.assertIn("turn_rl_v1.0", ACCEPTED_SCHEMAS)
        self.assertIn("turn_rl_v1.1", ACCEPTED_SCHEMAS)

    def test_v11_gate_fields_present(self):
        for f, gate in [
            ("local_only_provenance", "Gate 18"),
            ("config_hash", "Gate 18"),
            ("weather_current", "Gate 14"),
            ("setter_move_legal", "Gate 14"),
            ("used_species_ability_inference", "Gate 13"),
            ("terminal_win_loss", "Gate 15"),
        ]:
            self.assertIn(f, V1_1_GATE_FIELDS, f"Missing {f} from V1_1_GATE_FIELDS")
            self.assertEqual(V1_1_GATE_FIELDS[f], gate)

    def test_v11_block_fields(self):
        self.assertIn("used_species_ability_inference", V1_1_BLOCK_FIELDS)
        self.assertIn("impossible_target_detected", V1_1_BLOCK_FIELDS)
        self.assertIn("blocked_action_resurrected_by_joint", V1_1_BLOCK_FIELDS)


class TestV11AnalyzerEndToEnd(unittest.TestCase):
    """End-to-end: build v1.1 row, run analyze(), verify gates."""

    def test_v11_smoke_analyze(self):
        rows = [_build_v11_row()]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
            path = f.name
        try:
            report = analyze([path])
            self.assertIn("v11_gates", report)
            v11 = report["v11_gates"]
            self.assertEqual(v11["v11_n_rows"], 1)
            self.assertEqual(len(v11["hard_blocks"]), 0)
            self.assertIn("rl_readiness", report)
            self.assertIn("v11_impact", report["rl_readiness"])
        finally:
            os.unlink(path)

    def test_v10_backward_compat(self):
        v10_row = _build_v11_row()
        v10_row["schema_version"] = "turn_rl_v1.0"
        for f in list(v10_row.keys()):
            if f in V1_1_GATE_FIELDS:
                v10_row.pop(f, None)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write(json.dumps(v10_row) + "\n")
            path = f.name
        try:
            report = analyze([path])
            self.assertEqual(report["v11_gates"]["v10_n_rows"], 1)
            self.assertEqual(report["v11_gates"]["v11_n_rows"], 0)
            self.assertEqual(len(report["v11_gates"]["hard_blocks"]), 0)
        finally:
            os.unlink(path)

    def test_mixed_v10_v11(self):
        v10_row = _build_v11_row()
        v10_row["schema_version"] = "turn_rl_v1.0"
        for f in list(v10_row.keys()):
            if f in V1_1_GATE_FIELDS:
                v10_row.pop(f, None)
        v11_row = _build_v11_row()
        rows = [v10_row, v11_row]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
            path = f.name
        try:
            report = analyze([path])
            self.assertEqual(report["v11_gates"]["v10_n_rows"], 1)
            self.assertEqual(report["v11_gates"]["v11_n_rows"], 1)
            sc = report["v11_gates"]["schema_coverage"]
            self.assertEqual(sc["v10"], 1)
            self.assertEqual(sc["v11"], 1)
        finally:
            os.unlink(path)

    def test_hard_block_propagates_to_rl_readiness(self):
        rows = [_build_v11_row_with_hard_block(
            "used_species_ability_inference"
        )]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
            path = f.name
        try:
            report = analyze([path])
            self.assertEqual(
                report["v11_gates"]["readiness_impact"], "BLOCKED"
            )
            self.assertEqual(report["rl_readiness"]["readiness"], "BLOCKED")
            self.assertEqual(
                report["rl_readiness"]["v11_impact"], "BLOCKED"
            )
            self.assertGreater(
                report["rl_readiness"]["n_v11_hard_blocks"], 0
            )
        finally:
            os.unlink(path)

    def test_support_group_counts_present(self):
        rows = [_build_v11_row()]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
            path = f.name
        try:
            report = analyze([path])
            sgc = report["v11_gates"]["support_group_counts"]
            # Rain Dance is a weather_terrain group move
            self.assertGreater(sgc.get("weather_terrain", 0), 0)
        finally:
            os.unlink(path)

    def test_cli_main_with_v11(self):
        rows = [_build_v11_row()]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
            path = f.name
        md_path = path + ".md"
        json_path = path + ".json"
        try:
            rc = main([
                "--input", path,
                "--output-md", md_path,
                "--output-json", json_path,
                "--top-n", "5",
            ])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(md_path))
            self.assertTrue(os.path.exists(json_path))
            with open(json_path) as f:
                report = json.load(f)
            self.assertIn("v11_gates", report)
        finally:
            os.unlink(path)
            if os.path.exists(md_path):
                os.unlink(md_path)
            if os.path.exists(json_path):
                os.unlink(json_path)


class TestV11DryRunCompat(unittest.TestCase):
    """Verify dry-run accepts v1.1 rows."""

    def test_dryrun_loads_v11(self):
        from dryrun_turn_level_offline_policy import _load_dataset
        rows = [_build_v11_row()]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
            path = f.name
        try:
            loaded = _load_dataset(path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["schema_version"], "turn_rl_v1.1")
            self.assertTrue(
                loaded[0].get("local_only_provenance") is True
            )
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
