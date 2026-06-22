"""Phase TURN-2 — Tests for the read-only turn-level analyzer.

Uses tiny temp JSONL fixtures. Does not rely on real logs.
"""
import json
import os
import sys
import tempfile
import unittest


def _make_row(
    battle_tag="b1",
    won=True,
    arm="treatment",
    enable_mega_evolution=False,
    treatment_side="p1",
    player_side="p1",
    player_name="bot1",
    turns=None,
):
    """Build a minimal audit row."""
    if turns is None:
        turns = []
    return {
        "battle_tag": battle_tag,
        "won": won,
        "benchmark_arm": arm,
        "enable_mega_evolution": enable_mega_evolution,
        "treatment_side": treatment_side,
        "player_side": player_side,
        "player_name": player_name,
        "audit_turns": turns,
    }


def _make_turn(
    turn_n=1,
    v4a_sel=None,
    v2l_sel=None,
    scf=None,
    state=None,
    decision_time_ms=None,
    score_gap=None,
    overkill=False,
    stale_selected=False,
    stale_no_effect=False,
    support_blocked=False,
    support_wrong_side_s0=False,
    support_wrong_side_s1=False,
    narrow_heal_blocked_s0=False,
    narrow_heal_blocked_s1=False,
    joint_order_count=None,
    total_legal=None,
):
    """Build a minimal audit turn."""
    t = {
        "turn": turn_n,
        "v4a_selected_joint_key": v4a_sel or [
            ["move", "tackle", 0, ""],
            ["move", "ember", 1, ""],
        ],
        "v2l1_selected_joint_key": v2l_sel or [
            ("move", "tackle", 0),
            ("move", "ember", 1),
        ],
        "switch_counterfactual": scf or {},
        "selected_score": 100.0,
        "score_gap_selected_best_alt": score_gap,
        "overkill_penalty_triggered": overkill,
        "stale_target_selected": stale_selected,
        "stale_target_caused_no_effect": stale_no_effect,
        "support_target_candidate_blocked": support_blocked,
        "support_target_wrong_side_selected_slot0": support_wrong_side_s0,
        "support_target_wrong_side_selected_slot1": support_wrong_side_s1,
        "narrow_ally_heal_candidate_blocked_slot0": (
            narrow_heal_blocked_s0
        ),
        "narrow_ally_heal_candidate_blocked_slot1": (
            narrow_heal_blocked_s1
        ),
        "joint_order_count": joint_order_count,
        "total_legal_joint_orders": total_legal,
    }
    if state:
        t["state_snapshot"] = state
    if decision_time_ms is not None:
        t["decision_time_ms"] = decision_time_ms
    return t


def _make_state(
    our_species=("charizard", "garchomp"),
    opp_species=("garchomp", "charizard"),
    our_hp=(0.5, 0.5),
    opp_hp=(0.5, 0.5),
    weather="none",
    fields=None,
):
    return {
        "our_active_species": list(our_species),
        "opp_active_species": list(opp_species),
        "our_active_hp_fraction": list(our_hp),
        "opp_active_hp_fraction": list(opp_hp),
        "weather": weather,
        "fields": fields or [],
        "side_conditions": {},
        "opponent_side_conditions": {},
    }


class TestParsesOneRow(unittest.TestCase):
    def test_parses_one_row_one_turn(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate,
        )
        state = _make_state()
        turn = _make_turn(
            turn_n=1, state=state, decision_time_ms=100.0,
            score_gap=5.0,
        )
        row = _make_row(turns=[turn])
        records = _extract_turn_record(row, 0, "test.jsonl")
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["turn_number"], 1)
        self.assertEqual(rec["benchmark_arm"], "treatment")
        self.assertEqual(rec["decision_time_ms"], 100.0)
        self.assertEqual(rec["hp_bucket_slot0"], "50-75")
        agg = _aggregate(records)
        self.assertEqual(agg["data_quality"]["turns_total"], 1)
        self.assertEqual(agg["arm_summary"]["won"], 1)


class TestMultipleFiles(unittest.TestCase):
    def test_supports_multiple_audit_jsonl(self):
        from analyze_doubles_turn_level import (
            _load_audit, _extract_turn_record, _aggregate,
        )
        with tempfile.TemporaryDirectory() as tmp:
            f1 = os.path.join(tmp, "f1.jsonl")
            f2 = os.path.join(tmp, "f2.jsonl")
            state = _make_state()
            for f, tag in [(f1, "b1"), (f2, "b2")]:
                with open(f, "w") as fh:
                    row = _make_row(
                        battle_tag=tag,
                        turns=[_make_turn(
                            turn_n=1, state=state,
                            decision_time_ms=50.0,
                        )],
                    )
                    fh.write(json.dumps(row) + "\n")
            rows1, _ = _load_audit(f1)
            rows2, _ = _load_audit(f2)
            records = []
            for ri, row in enumerate(rows1):
                records.extend(
                    _extract_turn_record(row, ri, f1)
                )
            for ri, row in enumerate(rows2):
                records.extend(
                    _extract_turn_record(row, ri, f2)
                )
            self.assertEqual(len(records), 2)
            agg = _aggregate(records)
            self.assertEqual(agg["data_quality"]["turns_total"], 2)


class TestMissingAuditTurns(unittest.TestCase):
    def test_missing_audit_turns_does_not_crash(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate,
        )
        row = _make_row(turns=[])
        records = _extract_turn_record(row, 0, "test.jsonl")
        self.assertEqual(records, [])
        agg = _aggregate(records)
        self.assertEqual(agg["data_quality"]["turns_total"], 0)


class TestMissingOptionalFields(unittest.TestCase):
    def test_missing_optional_fields_does_not_crash(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate,
        )
        # Turn with no state_snapshot, no v4a, no v2l, no timing.
        turn = {"turn": 1}
        row = _make_row(turns=[turn])
        records = _extract_turn_record(row, 0, "test.jsonl")
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertIsNone(rec["decision_time_ms"])
        # state_snapshot is {} when missing (not None).
        self.assertEqual(rec["state_snapshot"], {})
        agg = _aggregate(records)
        self.assertEqual(agg["data_quality"]["turns_total"], 1)
        self.assertEqual(
            agg["data_quality"]["turns_missing_state_snapshot"],
            1,
        )


class TestArmSummary(unittest.TestCase):
    def test_arm_summary_counts_treatment_baseline(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate,
        )
        rows = [
            _make_row(arm="treatment", turns=[
                _make_turn(turn_n=1)
            ]),
            _make_row(arm="treatment", turns=[
                _make_turn(turn_n=1)
            ]),
            _make_row(arm="baseline", turns=[
                _make_turn(turn_n=1)
            ]),
        ]
        records = []
        for ri, row in enumerate(rows):
            records.extend(
                _extract_turn_record(row, ri, "test.jsonl")
            )
        agg = _aggregate(records)
        self.assertEqual(agg["arm_summary"]["by_arm"]["treatment"], 2)
        self.assertEqual(agg["arm_summary"]["by_arm"]["baseline"], 1)


class TestActionCategoryCounts(unittest.TestCase):
    def test_action_category_counts_move_switch_protect(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate,
        )
        # Move + move
        t1 = _make_turn(v4a_sel=[
            ["move", "tackle", 0, ""],
            ["move", "ember", 1, ""],
        ])
        # Switch + move
        t2 = _make_turn(turn_n=2, v4a_sel=[
            ["switch", "charizard", 0, ""],
            ["move", "ember", 1, ""],
        ])
        # Switch + switch
        t3 = _make_turn(turn_n=3, v4a_sel=[
            ["switch", "charizard", 0, ""],
            ["switch", "garchomp", 1, ""],
        ])
        # Pass as string (bot's selected_joint_order format)
        t4 = _make_turn(turn_n=4, v4a_sel=[
            "/choose pass",
            "/choose pass",
        ])
        row = _make_row(turns=[t1, t2, t3, t4])
        records = _extract_turn_record(row, 0, "test.jsonl")
        agg = _aggregate(records)
        self.assertEqual(
            agg["action_selection"]["slot0_category"]["move"], 1
        )
        self.assertEqual(
            agg["action_selection"]["slot0_category"]["switch"], 2
        )
        self.assertEqual(
            agg["action_selection"]["slot0_category"]["pass"], 1
        )
        self.assertEqual(
            agg["action_selection"]["slot0_category"].get("unknown", 0), 0
        )
        self.assertEqual(
            agg["action_selection"]["slot1_category"]["pass"], 1
        )


class TestV4aMechanicCounts(unittest.TestCase):
    def test_v4a_mechanic_counts_include_mega_plain(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate,
        )
        t1 = _make_turn(v4a_sel=[
            ["move", "tackle", 0, ""],
            ["move", "ember", 1, "mega"],
        ])
        t2 = _make_turn(turn_n=2, v4a_sel=[
            ["move", "tackle", 0, ""],
            ["move", "ember", 1, ""],
        ])
        row = _make_row(turns=[t1, t2])
        records = _extract_turn_record(row, 0, "test.jsonl")
        agg = _aggregate(records)
        self.assertEqual(
            agg["action_selection"]["slot1_mechanic"]["mega"], 1
        )
        self.assertEqual(
            agg["action_selection"]["slot1_mechanic"]["plain"], 1
        )


class TestTimingSummary(unittest.TestCase):
    def test_timing_summary_computes_min_median_max_mean(self):
        from analyze_doubles_turn_level import (
            _timing_summary,
        )
        vs = [10.0, 20.0, 30.0, 40.0, 50.0]
        ts = _timing_summary(vs)
        self.assertEqual(ts["count"], 5)
        self.assertEqual(ts["min"], 10.0)
        self.assertEqual(ts["max"], 50.0)
        self.assertEqual(ts["mean"], 30.0)
        self.assertEqual(ts["median"], 30.0)

    def test_timing_summary_empty(self):
        from analyze_doubles_turn_level import (
            _timing_summary,
        )
        ts = _timing_summary([])
        self.assertEqual(ts["count"], 0)


class TestHPBuckets(unittest.TestCase):
    def test_hp_buckets_from_state_snapshot(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate, _hp_bucket,
        )
        # Sanity: bucket boundaries.
        self.assertEqual(_hp_bucket(None), "unknown")
        self.assertEqual(_hp_bucket(0.1), "0-25")
        self.assertEqual(_hp_bucket(0.5), "50-75")
        self.assertEqual(_hp_bucket(0.9), "75-100")
        # Aggregation.
        state = _make_state(our_hp=(0.1, 0.9))
        turn = _make_turn(state=state)
        row = _make_row(turns=[turn])
        records = _extract_turn_record(row, 0, "test.jsonl")
        agg = _aggregate(records)
        self.assertEqual(
            agg["state_slices"]["hp_bucket_slot0"]["0-25"], 1
        )
        self.assertEqual(
            agg["state_slices"]["hp_bucket_slot1"]["75-100"], 1
        )


class TestSafetyFlags(unittest.TestCase):
    def test_safety_correction_flags_aggregate(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate,
        )
        turns = [
            _make_turn(turn_n=1, overkill=True),
            _make_turn(
                turn_n=2, stale_selected=True,
                stale_no_effect=True,
            ),
            _make_turn(
                turn_n=3, support_blocked=True,
                support_wrong_side_s0=True,
            ),
            _make_turn(
                turn_n=4, narrow_heal_blocked_s1=True,
            ),
        ]
        row = _make_row(turns=turns)
        records = _extract_turn_record(row, 0, "test.jsonl")
        agg = _aggregate(records)
        self.assertEqual(agg["safety"]["overkill_penalty_triggered"], 1)
        self.assertEqual(agg["safety"]["stale_target_selected"], 1)
        self.assertEqual(agg["safety"]["stale_target_caused_no_effect"], 1)
        self.assertEqual(
            agg["safety"]["support_target_candidate_blocked"], 1
        )
        self.assertEqual(
            agg["safety"]["support_target_wrong_side_selected"], 1
        )
        self.assertEqual(
            agg["safety"]["narrow_ally_heal_candidate_blocked"], 1
        )


class TestTopSlowTurnsSorted(unittest.TestCase):
    def test_top_slow_turns_sorted_descending(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record,
        )
        turns = [
            _make_turn(turn_n=1, decision_time_ms=100.0),
            _make_turn(turn_n=2, decision_time_ms=500.0),
            _make_turn(turn_n=3, decision_time_ms=200.0),
        ]
        row = _make_row(turns=turns)
        records = _extract_turn_record(row, 0, "test.jsonl")
        sorted_slow = sorted(
            records,
            key=lambda r: r.get("decision_time_ms") or 0.0,
            reverse=True,
        )
        self.assertEqual(
            sorted_slow[0]["decision_time_ms"], 500.0
        )
        self.assertEqual(
            sorted_slow[1]["decision_time_ms"], 200.0
        )
        self.assertEqual(
            sorted_slow[2]["decision_time_ms"], 100.0
        )


class TestTopSuspiciousRespectsTopN(unittest.TestCase):
    def test_top_suspicious_turns_respects_top_n(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate,
        )
        # Create 5 suspicious turns (all with low margin).
        turns = [
            _make_turn(turn_n=i, score_gap=1.0)
            for i in range(1, 6)
        ]
        row = _make_row(turns=turns)
        records = _extract_turn_record(row, 0, "test.jsonl")
        agg = _aggregate(records)
        self.assertEqual(len(agg["suspicious"]), 5)
        # top_n=3 should give 3.
        sorted_susp = sorted(
            agg["suspicious"],
            key=lambda s: len(s.get("reasons", [])),
            reverse=True,
        )[:3]
        self.assertEqual(len(sorted_susp), 3)


class TestWritesMarkdown(unittest.TestCase):
    def test_writes_markdown_report(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate, _write_markdown,
        )
        with tempfile.TemporaryDirectory() as tmp:
            md = os.path.join(tmp, "report.md")
            state = _make_state()
            turn = _make_turn(state=state, decision_time_ms=100.0)
            row = _make_row(turns=[turn])
            records = _extract_turn_record(row, 0, "test.jsonl")
            agg = _aggregate(records)
            _write_markdown(
                ["test.jsonl"],
                records,
                agg,
                10,
                md,
            )
            with open(md) as f:
                content = f.read()
            self.assertIn("# Phase TURN-2", content)
            self.assertIn("## TL;DR", content)
            self.assertIn("## Inputs", content)
            self.assertIn("## Data Quality", content)
            self.assertIn("## Arm Summary", content)
            self.assertIn("## Action Selection", content)
            self.assertIn("## Margin / Alternatives", content)
            self.assertIn("## Timing", content)
            self.assertIn("## Safety and Corrections", content)
            self.assertIn("## State Slices", content)
            self.assertIn("## Top Suspicious Turns", content)
            self.assertIn("## Per-Battle Summary", content)
            self.assertIn("## Limitations", content)
            self.assertIn("## Recommendations", content)


class TestWritesJSON(unittest.TestCase):
    def test_writes_json_summary(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate, _write_json,
        )
        with tempfile.TemporaryDirectory() as tmp:
            json_path = os.path.join(tmp, "summary.json")
            state = _make_state()
            turn = _make_turn(state=state, decision_time_ms=100.0)
            row = _make_row(turns=[turn])
            records = _extract_turn_record(row, 0, "test.jsonl")
            agg = _aggregate(records)
            _write_json(records, agg, 10, json_path)
            with open(json_path) as f:
                summary = json.load(f)
            self.assertIn("inputs", summary)
            self.assertIn("data_quality", summary)
            self.assertIn("arm_summary", summary)
            self.assertIn("action_selection", summary)
            self.assertIn("margin_summary", summary)
            self.assertIn("timing_summary", summary)
            self.assertIn("safety_summary", summary)
            self.assertIn("state_slices", summary)
            self.assertIn("top_suspicious_turns", summary)
            self.assertIn("top_slow_turns", summary)
            self.assertIn("per_battle", summary)


class TestJSONSerializable(unittest.TestCase):
    def test_json_is_serializable(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate, _write_json,
        )
        with tempfile.TemporaryDirectory() as tmp:
            json_path = os.path.join(tmp, "s.json")
            state = _make_state()
            turn = _make_turn(state=state, decision_time_ms=100.0)
            row = _make_row(turns=[turn])
            records = _extract_turn_record(row, 0, "test.jsonl")
            agg = _aggregate(records)
            _write_json(records, agg, 10, json_path)
            # Reload and verify all values are JSON-safe.
            with open(json_path) as f:
                obj = json.load(f)
            def _check(o):
                if isinstance(o, dict):
                    for k, v in o.items():
                        self.assertIsInstance(k, str)
                        _check(v)
                elif isinstance(o, list):
                    for v in o:
                        _check(v)
                else:
                    self.assertIn(
                        type(o).__name__,
                        ("str", "int", "float", "bool", "NoneType"),
                    )
            _check(obj)


class TestCLIEndToEnd(unittest.TestCase):
    def test_cli_runs_end_to_end(self):
        from analyze_doubles_turn_level import main
        with tempfile.TemporaryDirectory() as tmp:
            f1 = os.path.join(tmp, "f1.jsonl")
            md = os.path.join(tmp, "report.md")
            json_path = os.path.join(tmp, "summary.json")
            state = _make_state()
            with open(f1, "w") as f:
                row = _make_row(turns=[_make_turn(state=state)])
                f.write(json.dumps(row) + "\n")
            sys.argv = [
                "analyzer",
                "--audit-jsonl", f1,
                "--md", md,
                "--json", json_path,
            ]
            main()
            self.assertTrue(os.path.exists(md))
            self.assertTrue(os.path.exists(json_path))


def _make_turn_with_v4a(v4a_sel):
    """Build a turn with custom v4a_sel."""
    return _make_turn(v4a_sel=v4a_sel)


# Phase BEHAVIOR-2: module-level imports for new tests.
from analyze_doubles_turn_level import (
    _extract_turn_record, _aggregate,
)


class TestProtectSelected(unittest.TestCase):
    def test_detects_protect_selected_from_v4a_final(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate,
        )
        v4a_sel = [
            ["move", "/choose move protect", "self", "plain"],
            ["move", "/choose move tackle 1", "opp1", "plain"],
        ]
        turn = _make_turn_with_v4a(v4a_sel)
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        self.assertEqual(len(recs), 1)
        self.assertTrue(recs[0]["protect_selected_slot0"])
        self.assertFalse(recs[0]["protect_selected_slot1"])


class TestSpeedControlSelected(unittest.TestCase):
    def test_detects_tailwind_selected(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate,
        )
        v4a_sel = [
            ["move", "/choose move tailwind", "self", "plain"],
            ["move", "/choose move tackle 1", "opp1", "plain"],
        ]
        turn = _make_turn_with_v4a(v4a_sel)
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        self.assertEqual(recs[0]["speed_control_selected_slot0"],
                         "tailwind")

    def test_detects_trickroom_selected(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record,
        )
        v4a_sel = [
            ["move", "/choose move trickroom", "self", "plain"],
            ["move", "/choose move tackle 1", "opp1", "plain"],
        ]
        turn = _make_turn_with_v4a(v4a_sel)
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        self.assertEqual(recs[0]["speed_control_selected_slot0"],
                         "trickroom")

    def test_detects_icywind_electroweb_thunderwave(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record,
        )
        for mv, expected in [
            ("icywind", "icywind"),
            ("electroweb", "electroweb"),
            ("thunderwave", "thunderwave"),
        ]:
            v4a_sel = [
                ["move", f"/choose move {mv}", "opp1", "plain"],
                ["move", "/choose move tackle 1", "opp1", "plain"],
            ]
            turn = _make_turn_with_v4a(v4a_sel)
            recs = _extract_turn_record(
                {"battle_tag": "b1", "audit_turns": [turn]},
                0, "f1.jsonl",
            )
            self.assertEqual(
                recs[0]["speed_control_selected_slot0"],
                expected,
                f"failed for {mv}",
            )

    def test_counts_speed_control_by_move_id(self):
        from analyze_doubles_turn_level import _aggregate
        v4a_sel = [
            ["move", "/choose move tailwind", "self", "plain"],
            ["move", "/choose move tailwind", "self", "plain"],
        ]
        turn = _make_turn_with_v4a(v4a_sel)
        recs = [
            _extract_turn_record(
                {"battle_tag": "b1", "audit_turns": [turn]},
                0, "f1.jsonl",
            )[0]
            for _ in range(3)
        ]
        agg = _aggregate(recs)
        self.assertEqual(
            agg["speed_control_summary"]["by_move"]["tailwind"],
            6,  # 2 slots * 3 turns
        )


class TestSpeedPriorityMissing(unittest.TestCase):
    def test_handles_missing_speed_priority_fields(self):
        from analyze_doubles_turn_level import _aggregate
        v4a_sel = [
            ["move", "/choose move tackle 1", "opp1", "plain"],
            ["move", "/choose move tackle 1", "opp1", "plain"],
        ]
        turn = _make_turn_with_v4a(v4a_sel)
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        agg = _aggregate(recs)
        # No speed_priority fields were set, so
        # fields_available should be False and
        # fields_missing_count should be 1.
        self.assertFalse(
            agg["speed_priority_summary"]["fields_available"]
        )
        self.assertEqual(
            agg["speed_priority_summary"]["fields_missing_count"],
            1,
        )

    def test_counts_speed_priority_threat_when_present(self):
        from analyze_doubles_turn_level import _aggregate
        v4a_sel = [
            ["move", "/choose move tackle 1", "opp1", "plain"],
            ["move", "/choose move tackle 1", "opp1", "plain"],
        ]
        turn = _make_turn_with_v4a(v4a_sel)
        # Phase BEHAVIOR-3: use new top-level list shape.
        turn["speed_priority_threatened"] = [True, False]
        turn["protected_due_to_speed_priority"] = [True, False]
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
        # Phase BEHAVIOR-4: check per-slot and per-turn
        # counts separately.
        self.assertEqual(
            agg["speed_priority_summary"][
                "protected_due_to_speed_priority_slot0_true_count"
            ], 1
        )
        self.assertEqual(
            agg["speed_priority_summary"][
                "protected_due_to_speed_priority_slot1_true_count"
            ], 0
        )
        self.assertEqual(
            agg["speed_priority_summary"][
                "protected_due_to_speed_priority_turn_any_count"
            ], 1
        )


class TestSupportTargeting(unittest.TestCase):
    def test_detects_support_selected_move(self):
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate,
        )
        v4a_sel = [
            ["move", "/choose move healpulse 1", "ally", "plain"],
            ["move", "/choose move tackle 1", "opp1", "plain"],
        ]
        turn = _make_turn_with_v4a(v4a_sel)
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        agg = _aggregate(recs)
        self.assertEqual(
            agg["support_targeting_summary"][
                "slot0_support_selected"
            ], 1
        )
        self.assertIn(
            "heal_ally",
            agg["support_targeting_summary"]["by_category"],
        )

    def test_detects_support_wrong_side_block(self):
        from analyze_doubles_turn_level import _aggregate
        v4a_sel = [
            ["move", "/choose move tackle 1", "opp1", "plain"],
            ["move", "/choose move tackle 1", "opp1", "plain"],
        ]
        turn = _make_turn_with_v4a(v4a_sel)
        turn["support_target_wrong_side_selected_slot0"] = True
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        agg = _aggregate(recs)
        self.assertEqual(
            agg["support_targeting_summary"]["wrong_side_selected"],
            1
        )

    def test_detects_narrow_ally_heal_wrong_side_block(self):
        from analyze_doubles_turn_level import _aggregate
        v4a_sel = [
            ["move", "/choose move tackle 1", "opp1", "plain"],
            ["move", "/choose move tackle 1", "opp1", "plain"],
        ]
        turn = _make_turn_with_v4a(v4a_sel)
        turn["narrow_ally_heal_candidate_blocked_slot0"] = True
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        agg = _aggregate(recs)
        self.assertEqual(
            agg["support_targeting_summary"][
                "narrow_ally_heal_blocked"
            ], 1
        )


class TestOutputNewKeys(unittest.TestCase):
    def test_json_contains_new_top_level_keys(self):
        from analyze_doubles_turn_level import _aggregate
        v4a_sel = [
            ["move", "/choose move tackle 1", "opp1", "plain"],
            ["move", "/choose move tackle 1", "opp1", "plain"],
        ]
        turn = _make_turn_with_v4a(v4a_sel)
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        agg = _aggregate(recs)
        self.assertIn("protect_summary", agg)
        self.assertIn("speed_control_summary", agg)
        self.assertIn("speed_priority_summary", agg)
        self.assertIn("support_targeting_summary", agg)

    def test_markdown_contains_new_sections(self):
        from analyze_doubles_turn_level import (
            main, _write_markdown,
        )
        with tempfile.TemporaryDirectory() as tmp:
            f1 = os.path.join(tmp, "f1.jsonl")
            md = os.path.join(tmp, "report.md")
            json_path = os.path.join(tmp, "summary.json")
            v4a_sel = [
                ["move", "/choose move protect", "self", "plain"],
                ["move", "/choose move tailwind", "self", "plain"],
            ]
            turn = _make_turn(v4a_sel=v4a_sel)
            state = _make_state()
            turn["state_snapshot"] = state
            with open(f1, "w") as f:
                row = _make_row(turns=[turn])
                f.write(json.dumps(row) + "\n")
            sys.argv = [
                "analyzer",
                "--audit-jsonl", f1,
                "--md", md,
                "--json", json_path,
            ]
            main()
            with open(md) as f:
                content = f.read()
            self.assertIn("## Protect Summary", content)
            self.assertIn("## Speed-Control Summary", content)
            self.assertIn(
                "## Speed-Priority Threat Summary", content
            )
            self.assertIn("## Support-Targeting Summary", content)

    def test_old_minimal_fixture_still_passes(self):
        # Old minimal fixture should still parse.
        from analyze_doubles_turn_level import main
        with tempfile.TemporaryDirectory() as tmp:
            f1 = os.path.join(tmp, "f1.jsonl")
            md = os.path.join(tmp, "report.md")
            json_path = os.path.join(tmp, "summary.json")
            with open(f1, "w") as f:
                row = _make_row(turns=[_make_turn()])
                f.write(json.dumps(row) + "\n")
            sys.argv = [
                "analyzer",
                "--audit-jsonl", f1,
                "--md", md,
                "--json", json_path,
            ]
            main()
            with open(json_path) as f:
                d = json.load(f)
            self.assertIn("protect_summary", d)
            self.assertIn("speed_control_summary", d)
            self.assertIn("speed_priority_summary", d)
            self.assertIn("support_targeting_summary", d)


class TestSlotVsTurnCounts(unittest.TestCase):
    def test_slot_true_count_vs_turn_any_count_differ(self):
        """Phase BEHAVIOR-4: slot_true_count and turn_any_count
        are different metrics and must not be conflated.
        """
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate,
        )
        v4a_sel = [
            ["move", "/choose move tackle 1", "opp1", "plain"],
            ["move", "/choose move tackle 1", "opp1", "plain"],
        ]
        turns = [
            {
                "turn": 1,
                "v4a_selected_joint_key": v4a_sel,
                "speed_priority_threatened": [True, False],
                "protected_due_to_speed_priority": [True, False],
            },
            {
                "turn": 2,
                "v4a_selected_joint_key": v4a_sel,
                "speed_priority_threatened": [False, True],
                "protected_due_to_speed_priority": [False, True],
            },
            {
                "turn": 3,
                "v4a_selected_joint_key": v4a_sel,
                "speed_priority_threatened": [True, True],
                "protected_due_to_speed_priority": [True, True],
            },
        ]
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": turns},
            0, "f1.jsonl",
        )
        agg = _aggregate(recs)
        sp = agg["speed_priority_summary"]
        self.assertEqual(sp["slot0_threatened"], 2)
        self.assertEqual(sp["slot1_threatened"], 2)
        self.assertEqual(sp["any_slot_threatened"], 3)
        self.assertEqual(
            sp["protected_due_to_speed_priority_slot0_true_count"], 2
        )
        self.assertEqual(
            sp["protected_due_to_speed_priority_slot1_true_count"], 2
        )
        self.assertEqual(
            sp["protected_due_to_speed_priority_turn_any_count"], 3
        )

    def test_two_slots_true_counts_as_2_slot_1_turn_any(self):
        """Phase BEHAVIOR-4: a single turn with both slots
        true counts as 2 slot_true but 1 turn_any.
        """
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
            "speed_priority_threatened": [True, True],
            "expected_to_faint_before_moving": [True, True],
        }
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        agg = _aggregate(recs)
        sp = agg["speed_priority_summary"]
        self.assertEqual(sp["slot0_threatened"], 1)
        self.assertEqual(sp["slot1_threatened"], 1)
        self.assertEqual(sp["any_slot_threatened"], 1)
        self.assertEqual(
            sp["expected_to_faint_before_moving_slot0_true_count"],
            1,
        )
        self.assertEqual(
            sp["expected_to_faint_before_moving_slot1_true_count"],
            1,
        )
        self.assertEqual(
            sp["expected_to_faint_before_moving_turn_any_count"],
            1,
        )

    def test_all_fields_report_both_slot_and_turn_counts(self):
        """Phase BEHAVIOR-4: all 5 boolean fields report
        both slot_true_count and turn_any_count.
        """
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
            "protected_due_to_speed_priority": [True, True],
            "speed_priority_protect_bonus_applied": [True, False],
            "speed_priority_attack_penalty_applied": [False, True],
            "speed_priority_switch_bonus_applied": [True, True],
            "expected_to_faint_before_moving": [True, True],
        }
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        agg = _aggregate(recs)
        sp = agg["speed_priority_summary"]
        for fld in [
            "protected_due_to_speed_priority",
            "speed_priority_protect_bonus_applied",
            "speed_priority_attack_penalty_applied",
            "speed_priority_switch_bonus_applied",
            "expected_to_faint_before_moving",
        ]:
            self.assertIn(f"{fld}_slot0_true_count", sp)
            self.assertIn(f"{fld}_slot1_true_count", sp)
            self.assertIn(f"{fld}_turn_any_count", sp)


class TestSuspiciousAttributionHelpers(unittest.TestCase):
    """Phase ANALYZER-2: pure helper tests for the
    V4a action parser and slot label extractor.
    """

    def setUp(self):
        from analyze_doubles_turn_level import (
            _parse_v4a_action,
            _slot_labels,
        )
        self.parse = _parse_v4a_action
        self.labels = _slot_labels

    def test_parse_v4a_move(self):
        p = self.parse(["move", "tackle", 1, ""])
        self.assertEqual(p["kind"], "move")
        self.assertEqual(p["id"], "tackle")
        self.assertEqual(p["target"], "1")

    def test_parse_v4a_switch(self):
        p = self.parse(["switch", "sneasler", 0, ""])
        self.assertEqual(p["kind"], "switch")
        self.assertEqual(p["id"], "sneasler")
        self.assertEqual(p["target"], "0")

    def test_parse_v4a_pass(self):
        p = self.parse(["unknown", "/choose pass", 0, ""])
        self.assertEqual(p["kind"], "pass")
        self.assertEqual(p["target"], "0")

    def test_parse_v4a_none(self):
        p = self.parse(None)
        self.assertEqual(p["kind"], "unknown")

    def test_parse_v4a_short(self):
        p = self.parse(["move"])
        self.assertEqual(p["kind"], "unknown")

    def test_slot_labels_basic(self):
        ss = {
            "our_active_species": ["tyranitar", "incineroar"],
            "opp_active_species": ["sneasler", "garchomp"],
        }
        l = self.labels(ss)
        self.assertEqual(l["our_active_slot0"], "tyranitar")
        self.assertEqual(l["our_active_slot1"], "incineroar")
        self.assertEqual(l["opp_active_slot0"], "sneasler")
        self.assertEqual(l["opp_active_slot1"], "garchomp")

    def test_slot_labels_missing(self):
        l = self.labels({})
        self.assertIsNone(l["our_active_slot0"])
        self.assertIsNone(l["opp_active_slot0"])


class TestSuspiciousAttributionRecord(unittest.TestCase):
    """Phase ANALYZER-2: the suspicious record
    produced by _aggregate includes per-slot
    attribution fields.
    """

    def setUp(self):
        from analyze_doubles_turn_level import (
            _aggregate,
            _extract_turn_record,
        )
        self.aggregate = _aggregate
        self.extract = _extract_turn_record

    def _make_suspicious_record(self):
        """Build a record that triggers the suspicious
        path (stale target selected)."""
        row = {
            "battle_tag": "b1",
            "won": False,
            "benchmark_arm": "treatment",
            "enable_mega_evolution": True,
            "audit_turns": [
                {
                    "turn": 4,
                    "state_snapshot": {
                        "our_active_species": [
                            "tyranitar", "incineroar"
                        ],
                        "opp_active_species": [
                            "sneasler", "garchomp"
                        ],
                        "our_active_hp_fraction": [1.0, 0.5],
                        "opp_active_hp_fraction": [0.8, 0.6],
                    },
                    "v4a_selected_joint_key": [
                        ["move", "rockslide", 0, ""],
                        ["move", "fakeout", 1, ""],
                    ],
                    "stale_target_selected": True,
                    "stale_target_avoided": False,
                    "stale_target_caused_no_effect": False,
                    "stale_target_caused_type_immune": False,
                    "selected_joint_order": None,
                    "selected_score": 100.0,
                    "score_gap_selected_best_alt": 10.0,
                    "v2l1_selected_joint_key": None,
                    "v2l1_final_action_keys": None,
                    "v4a_final_action_keys": None,
                    "overkill_penalty_triggered": False,
                    "order_aware_overkill_penalty_applied": False,
                    "focus_fire_triggered": False,
                    "support_target_candidate_blocked": None,
                    "support_target_wrong_side_selected_slot0": False,
                    "support_target_wrong_side_selected_slot1": False,
                }
            ],
        }
        records = self.extract(row, 0, "test.jsonl")
        return self.aggregate(records)

    def test_turn_record_includes_our_and_opp_active_species(self):
        agg = self._make_suspicious_record()
        susp = agg["suspicious"]
        self.assertGreater(len(susp), 0)
        s = susp[0]
        self.assertEqual(s["our_active_slot0"], "tyranitar")
        self.assertEqual(s["our_active_slot1"], "incineroar")
        self.assertEqual(s["opp_active_slot0"], "sneasler")
        self.assertEqual(s["opp_active_slot1"], "garchomp")

    def test_selected_action_key_parsed_into_category_target_mechanic(self):
        agg = self._make_suspicious_record()
        s = agg["suspicious"][0]
        # Slot 0: move rockslide target 0.
        self.assertEqual(s["selected_slot0_kind"], "move")
        self.assertEqual(s["selected_slot0_id"], "rockslide")
        self.assertEqual(s["selected_slot0_target"], "0")
        self.assertEqual(s["selected_slot0_mechanic"], "")
        # Slot 1: move fakeout target 1.
        self.assertEqual(s["selected_slot1_kind"], "move")
        self.assertEqual(s["selected_slot1_id"], "fakeout")
        self.assertEqual(s["selected_slot1_target"], "1")
        self.assertEqual(s["selected_slot1_mechanic"], "")

    def test_mirror_match_turn_attribution_not_ambiguous(self):
        """Mirror-match case: our bench sneasler (chosen
        via switch) vs opp active sneasler. The record
        must distinguish them.
        """
        row = {
            "battle_tag": "b1",
            "won": False,
            "benchmark_arm": "treatment",
            "enable_mega_evolution": True,
            "audit_turns": [
                {
                    "turn": 5,
                    "state_snapshot": {
                        "our_active_species": [
                            "tyranitar", "incineroar"
                        ],
                        "opp_active_species": [
                            "sneasler", "garchomp"
                        ],
                        "our_active_hp_fraction": [1.0, 0.5],
                        "opp_active_hp_fraction": [0.8, 0.6],
                    },
                    "v4a_selected_joint_key": [
                        ["switch", "sneasler", 0, ""],
                        ["move", "protect", 0, ""],
                    ],
                    "stale_target_selected": True,
                    "stale_target_avoided": False,
                    "stale_target_caused_no_effect": False,
                    "stale_target_caused_type_immune": False,
                    "selected_joint_order": None,
                    "selected_score": 100.0,
                    "score_gap_selected_best_alt": 10.0,
                    "v2l1_selected_joint_key": None,
                    "v2l1_final_action_keys": None,
                    "v4a_final_action_keys": None,
                    "overkill_penalty_triggered": False,
                    "order_aware_overkill_penalty_applied": False,
                    "focus_fire_triggered": False,
                    "support_target_candidate_blocked": None,
                    "support_target_wrong_side_selected_slot0": False,
                    "support_target_wrong_side_selected_slot1": False,
                }
            ],
        }
        records = self.extract(row, 0, "test.jsonl")
        agg = self.aggregate(records)
        s = agg["suspicious"][0]
        # Slot 0: switch to sneasler (our bench).
        self.assertEqual(s["selected_slot0_kind"], "switch")
        self.assertEqual(s["selected_slot0_id"], "sneasler")
        # opp_active_slot0 is the opponent's sneasler,
        # not ours.
        self.assertEqual(s["opp_active_slot0"], "sneasler")
        # our_active_slot0 is tyranitar (not sneasler).
        self.assertEqual(s["our_active_slot0"], "tyranitar")
        # The reader can now see "switch to sneasler" was
        # a switch to bench sneasler, while opp active
        # is also sneasler — they are different Pokemon.

    def test_top_suspicious_json_preserves_old_keys(self):
        agg = self._make_suspicious_record()
        s = agg["suspicious"][0]
        # Old keys preserved.
        for k in (
            "battle_tag", "arm", "turn", "reasons",
            "selected", "margin",
        ):
            self.assertIn(k, s)
        # New attribution keys added.
        for k in (
            "our_active_slot0", "our_active_slot1",
            "opp_active_slot0", "opp_active_slot1",
            "selected_slot0_kind", "selected_slot1_kind",
            "selected_slot0_id", "selected_slot1_id",
            "selected_slot0_target", "selected_slot1_target",
            "selected_slot0_mechanic", "selected_slot1_mechanic",
        ):
            self.assertIn(k, s)


class TestMarkdownAttributionColumns(unittest.TestCase):
    """Phase ANALYZER-2: the markdown table for
    Top Suspicious Turns includes attribution columns.
    """

    def setUp(self):
        from analyze_doubles_turn_level import (
            _aggregate,
            _extract_turn_record,
            _write_markdown,
        )
        self.aggregate = _aggregate
        self.extract = _extract_turn_record
        self.write_md = _write_markdown

    def test_top_suspicious_markdown_has_attribution_columns(self):
        row = {
            "battle_tag": "b1",
            "won": False,
            "benchmark_arm": "treatment",
            "enable_mega_evolution": True,
            "audit_turns": [
                {
                    "turn": 4,
                    "state_snapshot": {
                        "our_active_species": [
                            "tyranitar", "incineroar"
                        ],
                        "opp_active_species": [
                            "sneasler", "garchomp"
                        ],
                        "our_active_hp_fraction": [1.0, 0.5],
                        "opp_active_hp_fraction": [0.8, 0.6],
                    },
                    "v4a_selected_joint_key": [
                        ["move", "rockslide", 0, ""],
                        ["move", "fakeout", 1, ""],
                    ],
                    "stale_target_selected": True,
                    "stale_target_avoided": False,
                    "stale_target_caused_no_effect": False,
                    "stale_target_caused_type_immune": False,
                    "selected_joint_order": None,
                    "selected_score": 100.0,
                    "score_gap_selected_best_alt": 10.0,
                    "v2l1_selected_joint_key": None,
                    "v2l1_final_action_keys": None,
                    "v4a_final_action_keys": None,
                    "overkill_penalty_triggered": False,
                    "order_aware_overkill_penalty_applied": False,
                    "focus_fire_triggered": False,
                    "support_target_candidate_blocked": None,
                    "support_target_wrong_side_selected_slot0": False,
                    "support_target_wrong_side_selected_slot1": False,
                }
            ],
        }
        records = self.extract(row, 0, "test.jsonl")
        agg = self.aggregate(records)
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            md = os.path.join(tmp, "out.md")
            self.write_md(
                ["test.jsonl"], records, agg, 5, md
            )
            with open(md) as f:
                content = f.read()
        # Required attribution columns.
        for col in (
            "our_s0", "opp_s0",
            "sel0_kind", "sel0_id", "sel0_tgt",
            "our_s1", "opp_s1",
            "sel1_kind", "sel1_id", "sel1_tgt",
        ):
            self.assertIn(col, content)
        # Old reasons column preserved.
        self.assertIn("reasons", content)
        # Old margin column preserved.
        self.assertIn("margin", content)


if __name__ == "__main__":
    unittest.main()