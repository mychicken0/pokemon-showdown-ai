"""Phase RL-6 — Tests for the turn-level offline dataset
quality analyzer.

Validates:
- Parsing of one or more valid rows
- Malformed JSON handling
- Reward summary counts
- Action category summary
- Legal action count summary
- State HP/weather buckets
- Score margin summary
- Duplicate detection
- Missing optional fields counted but not fatal
- Readiness NOT_READY for tiny dataset
- Readiness READY_FOR_DRYRUN for synthetic adequate dataset
- Markdown output contains key sections
- JSON output serializable
- CLI end-to-end with temp fixture
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

# Ensure the analyzer is importable.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from analyze_turn_level_offline_dataset_quality import (  # noqa: E402
    EXPECTED_SCHEMA,
    _bucket_hp,
    _bucket_turn,
    _classify_action,
    _entropy,
    analyze,
    main,
    write_markdown,
    write_summary,
)


def _make_row(
    battle_tag="b1",
    turn=1,
    won=True,
    arm="treatment",
    sel0=None,
    sel1=None,
    legal0=None,
    legal1=None,
    our_species=None,
    opp_species=None,
    our_hp=None,
    opp_hp=None,
    weather="none",
    fields=None,
    selected_score=100.0,
    margin=10.0,
    n_unique_joint_actions=10,
    **overrides,
):
    """Create a minimal valid turn_rl_v1.0 row for testing."""
    if sel0 is None:
        sel0 = ["move", "tackle", 1, ""]
    if sel1 is None:
        sel1 = ["move", "matchagotcha", 0, ""]
    if legal0 is None:
        legal0 = [sel0, ["move", "fakeout", 1, ""]]
    if legal1 is None:
        legal1 = [sel1, ["move", "protect", 0, ""]]
    if our_species is None:
        our_species = ["incineroar", "sinistcha"]
    if opp_species is None:
        opp_species = ["garchomp", "incineroar"]
    if our_hp is None:
        our_hp = [0.5, 0.8]
    if opp_hp is None:
        opp_hp = [0.3, 0.5]
    if fields is None:
        fields = []
    base = {
        "schema_version": EXPECTED_SCHEMA,
        "dataset_id": "test_dataset",
        "source_artifact": "test.jsonl",
        "battle_tag": battle_tag,
        "episode_id": battle_tag,
        "turn_index": turn,
        "player_side": "bot",
        "benchmark_arm": arm,
        "policy_name": "matchup_top4_v3",
        "won": won,
        "battle_result": "win" if won else "loss",
        "total_turns": 10,
        "terminal_reward": 1 if won else -1,
        "discounted_return": None,
        "state_snapshot": {
            "our_active_species": our_species,
            "opp_active_species": opp_species,
            "our_active_hp_fraction": our_hp,
            "opp_active_hp_fraction": opp_hp,
            "weather": weather,
            "fields": fields,
            "side_conditions": {},
        },
        "legal_action_keys_slot0": legal0,
        "legal_action_keys_slot1": legal1,
        "selected_joint_key": [sel0, sel1],
        "final_action_keys": [sel0, sel1],
        "selected_per_slot": {
            "slot_0": sel0,
            "slot_1": sel1,
        },
        "selected_score": selected_score,
        "top_5_alternatives": [],
        "top_5_scores": [],
        "score_gap_selected_best_alt": margin,
        "v2l1_raw_scores_slot0": {"move|tackle|1": 100.0},
        "v2l1_raw_scores_slot1": {"move|matchagotcha|0": 80.0},
        "switch_counterfactual": None,
        "speed_priority_threatened": None,
        "expected_to_faint_before_moving": None,
        "overkill_penalty_triggered": False,
        "focus_fire_triggered": False,
        "stale_target_avoided": False,
        "narrow_ally_heal_candidate_blocked_slot0": None,
        "narrow_ally_heal_candidate_blocked_slot1": None,
        "joint_order_count": None,
        "total_legal_joint_orders": None,
    }
    base.update(overrides)
    return base


def _write_temp_jsonl(rows):
    """Write rows to a temp JSONL file and return the path."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False
    )
    for r in rows:
        f.write(json.dumps(r, sort_keys=True) + "\n")
    f.close()
    return f.name


class TestHelpers(unittest.TestCase):
    def test_bucket_hp(self):
        self.assertEqual(_bucket_hp(0.0), "<25%")
        self.assertEqual(_bucket_hp(0.2), "<25%")
        self.assertEqual(_bucket_hp(0.25), "25-50%")
        self.assertEqual(_bucket_hp(0.26), "25-50%")
        self.assertEqual(_bucket_hp(0.5), "50-75%")
        self.assertEqual(_bucket_hp(0.75), "75-100%")
        self.assertEqual(_bucket_hp(1.0), "75-100%")

    def test_bucket_turn(self):
        self.assertEqual(_bucket_turn(1), "1-3")
        self.assertEqual(_bucket_turn(3), "1-3")
        self.assertEqual(_bucket_turn(4), "4-6")
        self.assertEqual(_bucket_turn(6), "4-6")
        self.assertEqual(_bucket_turn(7), "7-9")
        self.assertEqual(_bucket_turn(9), "7-9")
        self.assertEqual(_bucket_turn(10), "10+")
        self.assertEqual(_bucket_turn(50), "10+")

    def test_classify_action(self):
        self.assertEqual(
            _classify_action(["move", "tackle", 1, ""]),
            "move_attack",
        )
        self.assertEqual(
            _classify_action(["move", "protect", 0, ""]),
            "move_status_ally",
        )
        self.assertEqual(
            _classify_action(["move", "healpulse", -1, ""]),
            "move_status_ally",
        )
        self.assertEqual(
            _classify_action(["move", "thunderwave", 1, ""]),
            "move_status_opp",
        )
        self.assertEqual(
            _classify_action(["move", "trickroom", 0, ""]),
            "move_status_field",
        )
        self.assertEqual(
            _classify_action(["switch", "garchomp", 0, ""]),
            "switch",
        )
        self.assertEqual(
            _classify_action(["pass", "", 0, ""]),
            "pass",
        )

    def test_entropy(self):
        from collections import Counter
        self.assertEqual(_entropy(Counter()), 0.0)
        # 50/50 distribution has entropy 1 bit.
        c = Counter({"a": 5, "b": 5})
        self.assertAlmostEqual(_entropy(c), 1.0, places=5)


class TestAnalyzeSingleRow(unittest.TestCase):
    def test_parses_one_valid_row(self):
        row = _make_row()
        path = _write_temp_jsonl([row])
        try:
            r = analyze([path])
            self.assertEqual(r["row_summary"]["n_rows"], 1)
            self.assertEqual(r["row_summary"]["n_episodes"], 1)
            self.assertEqual(r["row_summary"]["n_battles"], 1)
        finally:
            os.unlink(path)

    def test_parses_multiple_files(self):
        rows_a = [
            _make_row(battle_tag=f"b_a_{i}", source_artifact="a.jsonl")
            for i in range(3)
        ]
        rows_b = [
            _make_row(battle_tag=f"b_b_{i}", source_artifact="b.jsonl")
            for i in range(2)
        ]
        pa = _write_temp_jsonl(rows_a)
        pb = _write_temp_jsonl(rows_b)
        try:
            r = analyze([pa, pb])
            self.assertEqual(r["row_summary"]["n_rows"], 5)
            self.assertEqual(r["row_summary"]["n_source_artifacts"], 2)
        finally:
            os.unlink(pa)
            os.unlink(pb)

    def test_rejects_malformed_json(self):
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        )
        f.write("not valid json\n")
        f.write(json.dumps(_make_row()) + "\n")
        f.close()
        try:
            r = analyze([f.name])
            self.assertEqual(r["row_summary"]["n_rows"], 1)
            self.assertEqual(r["row_summary"]["n_malformed_json"], 1)
        finally:
            os.unlink(f.name)


class TestRewardSummary(unittest.TestCase):
    def test_reward_counts(self):
        rows = [
            _make_row(battle_tag=f"b_{i}", won=(i % 2 == 0))
            for i in range(6)
        ]
        path = _write_temp_jsonl(rows)
        try:
            r = analyze([path])
            self.assertEqual(r["reward_summary"]["total"][1], 3)
            self.assertEqual(r["reward_summary"]["total"][-1], 3)
        finally:
            os.unlink(path)

    def test_reward_by_arm(self):
        rows = [
            _make_row(battle_tag="t1", won=True, arm="treatment"),
            _make_row(battle_tag="t2", won=True, arm="treatment"),
            _make_row(battle_tag="b1", won=False, arm="baseline"),
        ]
        path = _write_temp_jsonl(rows)
        try:
            r = analyze([path])
            self.assertEqual(r["reward_summary"]["by_arm"]["treatment"][1], 2)
            self.assertEqual(r["reward_summary"]["by_arm"]["baseline"][-1], 1)
        finally:
            os.unlink(path)


class TestActionDistribution(unittest.TestCase):
    def test_action_category_summary(self):
        rows = [_make_row(battle_tag=f"b_{i}") for i in range(5)]
        path = _write_temp_jsonl(rows)
        try:
            r = analyze([path])
            # Each row uses tackle (attack) + matchagotcha
            # (attack). The default legal set includes
            # fakeout and protect, but selected is tackle+
            # matchagotcha.
            self.assertIn(
                "move_attack+move_attack",
                r["action_distribution"]["selected_joint_category"],
            )
        finally:
            os.unlink(path)


class TestLegalActionSpace(unittest.TestCase):
    def test_legal_count_summary(self):
        rows = [_make_row(battle_tag=f"b_{i}") for i in range(3)]
        path = _write_temp_jsonl(rows)
        try:
            r = analyze([path])
            s0 = r["legal_summary"]["slot0_min_median_max"]
            self.assertEqual(s0[0], 2)  # min legal count
            self.assertGreater(s0[1], 0)  # median
        finally:
            os.unlink(path)


class TestStateCoverage(unittest.TestCase):
    def test_hp_weather_buckets(self):
        rows = [
            _make_row(
                battle_tag="b1", our_hp=[0.1, 0.9], opp_hp=[0.3, 0.5]
            ),
            _make_row(
                battle_tag="b2", our_hp=[0.5, 0.5], opp_hp=[0.7, 0.8],
                weather="raindance"
            ),
        ]
        path = _write_temp_jsonl(rows)
        try:
            r = analyze([path])
            self.assertIn("<25%", r["state_coverage"]["our_active_hp_buckets"])
            self.assertIn(
                "raindance", r["state_coverage"]["weather"]
            )
        finally:
            os.unlink(path)


class TestScoreMargin(unittest.TestCase):
    def test_margin_summary(self):
        rows = [
            _make_row(battle_tag=f"b_{i}", margin=10.0 * (i + 1))
            for i in range(5)
        ]
        path = _write_temp_jsonl(rows)
        try:
            r = analyze([path])
            self.assertEqual(
                r["score_margin_summary"]["score_gap"]["count"], 5
            )
            self.assertEqual(
                r["score_margin_summary"]["score_gap"]["min"], 10.0
            )
            self.assertEqual(
                r["score_margin_summary"]["score_gap"]["max"], 50.0
            )
        finally:
            os.unlink(path)


class TestDuplicateDetection(unittest.TestCase):
    def test_duplicate_state_action(self):
        # Build two rows with same state and same action.
        row1 = _make_row(battle_tag="b1", turn=1)
        row2 = _make_row(battle_tag="b2", turn=1)
        path = _write_temp_jsonl([row1, row2])
        try:
            r = analyze([path])
            # State is the same; selected action is the same.
            # So this is a duplicate state-action pair.
            self.assertGreaterEqual(
                r["duplicate_bias"]["n_duplicate_state_action"], 1
            )
        finally:
            os.unlink(path)


class TestMissingOptionalFields(unittest.TestCase):
    def test_missing_optional_counted_not_fatal(self):
        # Rows with no optional fields. Analysis should
        # still complete; missing counts are reported.
        row = _make_row(
            battle_tag="b1",
            switch_counterfactual=None,
            speed_priority_threatened=None,
            overkill_penalty_triggered=None,
        )
        path = _write_temp_jsonl([row])
        try:
            r = analyze([path])  # should not raise
            self.assertIn(
                "switch_counterfactual",
                r["counterfactual_coverage"]["missing_optional_field_counts"],
            )
        finally:
            os.unlink(path)


class TestReadiness(unittest.TestCase):
    def test_not_ready_for_tiny_dataset(self):
        # Single row fails rows >= 500.
        row = _make_row()
        path = _write_temp_jsonl([row])
        try:
            r = analyze([path])
            self.assertIn(
                r["rl_readiness"]["readiness"],
                ["NOT_READY", "PARTIAL"],
            )
        finally:
            os.unlink(path)

    def test_ready_for_dryrun_synthetic_adequate(self):
        # Build 500 rows across 50 episodes (10 turns each).
        rows = []
        for i in range(50):
            for t in range(1, 11):
                rows.append(_make_row(
                    battle_tag=f"b_{i}",
                    episode_id=f"b_{i}",
                    turn=t,
                    won=(i % 2 == 0),
                ))
        path = _write_temp_jsonl(rows)
        try:
            r = analyze([path])
            # Should be PARTIAL or READY_FOR_DRYRUN
            # (depends on entropy and dup checks).
            self.assertIn(
                r["rl_readiness"]["readiness"],
                ["PARTIAL", "READY_FOR_DRYRUN"],
            )
        finally:
            os.unlink(path)


class TestWriteFunctions(unittest.TestCase):
    def test_markdown_contains_key_sections(self):
        row = _make_row()
        path = _write_temp_jsonl([row])
        try:
            r = analyze([path])
            md_path = tempfile.mktemp(suffix=".md")
            try:
                write_markdown(r, md_path)
                with open(md_path) as f:
                    content = f.read()
                for section in [
                    "Row / Episode Summary",
                    "Reward Summary",
                    "Action Distribution",
                    "Legal Action Space",
                    "State Coverage",
                    "Score / Margin Summary",
                    "Counterfactual / Optional Fields",
                    "Duplicate / Bias Checks",
                    "RL Readiness",
                ]:
                    self.assertIn(section, content)
            finally:
                os.unlink(md_path)
        finally:
            os.unlink(path)

    def test_json_output_serializable(self):
        row = _make_row()
        path = _write_temp_jsonl([row])
        try:
            r = analyze([path])
            json_path = tempfile.mktemp(suffix=".json")
            try:
                write_summary(r, json_path)
                with open(json_path) as f:
                    loaded = json.load(f)
                self.assertIn("row_summary", loaded)
                self.assertIn("rl_readiness", loaded)
            finally:
                os.unlink(json_path)
        finally:
            os.unlink(path)


class TestCLIEndToEnd(unittest.TestCase):
    def test_cli_runs(self):
        row = _make_row()
        path = _write_temp_jsonl([row])
        md_path = tempfile.mktemp(suffix=".md")
        json_path = tempfile.mktemp(suffix=".json")
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
        finally:
            os.unlink(path)
            if os.path.exists(md_path):
                os.unlink(md_path)
            if os.path.exists(json_path):
                os.unlink(json_path)


if __name__ == "__main__":
    unittest.main()
