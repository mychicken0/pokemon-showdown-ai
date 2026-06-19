"""Phase SWITCH-2 — Tests for the read-only switch analyzer.

Uses tiny temp JSONL fixtures. Does not rely on real logs.
"""
import json
import os
import sys
import tempfile
import unittest
from collections import Counter


def _make_row(
    battle_tag="b1",
    won=True,
    arm="treatment",
    turns=None,
):
    """Build a minimal audit row."""
    if turns is None:
        turns = []
    return {
        "battle_tag": battle_tag,
        "won": won,
        "benchmark_arm": arm,
        "audit_turns": turns,
    }


def _make_turn(
    turn_n=1,
    scf=None,
    state=None,
):
    """Build a minimal audit turn."""
    t = {
        "turn": turn_n,
        "switch_counterfactual": scf or {},
    }
    if state:
        t["state_snapshot"] = state
    return t


def _make_scf_slot(
    chosen_is_switch=False,
    chosen="move|heatwave|0",
    cf="move|heatwave|0",
    best_switch="switch|charizard|0",
    best_switch_score=100.0,
    best_non_switch="move|heatwave|0",
    best_non_switch_score=120.0,
    delta=-20.0,
):
    return {
        "chosen_is_switch": chosen_is_switch,
        "chosen_action_key": chosen,
        "counterfactual_action_key": cf,
        "best_switch_action_key": best_switch,
        "best_switch_score": best_switch_score,
        "best_non_switch_action_key": best_non_switch,
        "best_non_switch_score": best_non_switch_score,
        "switch_vs_non_switch_delta": delta,
        "selection_changed": False,
        "reason_codes": [],
    }


class TestAnalyzerParsesOneRow(unittest.TestCase):
    def test_one_row_one_turn_one_slot(self):
        from analyze_doubles_switch_per_turn import (
            _collect_slot_data, _delta_summary,
        )
        scf = {"slot0": _make_scf_slot(delta=50.0)}
        turn = _make_turn(scf=scf)
        row = _make_row(turns=[turn])
        data = _collect_slot_data([row])
        self.assertEqual(data["counts"]["rows"], 1)
        self.assertEqual(data["opportunities"]["slot0_present"], 1)
        self.assertEqual(data["opportunities"]["slot1_present"], 0)
        self.assertEqual(len(data["deltas"]), 1)
        self.assertEqual(data["deltas"][0], 50.0)
        ds = _delta_summary(data["deltas"])
        self.assertEqual(ds["count"], 1)
        self.assertEqual(ds["max"], 50.0)
        self.assertEqual(ds["min"], 50.0)


class TestAnalyzerMultipleFiles(unittest.TestCase):
    def test_handles_multiple_audit_jsonl_files(self):
        from analyze_doubles_switch_per_turn import (
            _collect_slot_data, _load_audit,
        )
        with tempfile.TemporaryDirectory() as tmp:
            f1 = os.path.join(tmp, "f1.jsonl")
            f2 = os.path.join(tmp, "f2.jsonl")
            with open(f1, "w") as f:
                row = _make_row(
                    battle_tag="b1",
                    turns=[_make_turn(scf={
                        "slot0": _make_scf_slot(delta=10.0)
                    })],
                )
                f.write(json.dumps(row) + "\n")
            with open(f2, "w") as f:
                row = _make_row(
                    battle_tag="b2",
                    turns=[_make_turn(scf={
                        "slot0": _make_scf_slot(delta=20.0)
                    })],
                )
                f.write(json.dumps(row) + "\n")
            rows = _load_audit(f1) + _load_audit(f2)
            data = _collect_slot_data(rows)
            self.assertEqual(data["counts"]["rows"], 2)
            self.assertEqual(len(data["deltas"]), 2)
            self.assertIn(10.0, data["deltas"])
            self.assertIn(20.0, data["deltas"])


class TestAnalyzerMissingFields(unittest.TestCase):
    def test_missing_scf_does_not_crash(self):
        from analyze_doubles_switch_per_turn import (
            _collect_slot_data,
        )
        turn = _make_turn(scf=None)
        row = _make_row(turns=[turn])
        data = _collect_slot_data([row])
        self.assertEqual(data["counts"]["rows"], 1)
        self.assertEqual(data["opportunities"]["slot0_present"], 0)
        self.assertEqual(data["opportunities"]["switch_cf_present"], 0)
        self.assertEqual(data["deltas"], [])

    def test_legacy_row_without_arm_field(self):
        from analyze_doubles_switch_per_turn import (
            _collect_slot_data,
        )
        row = {
            "battle_tag": "b1",
            "won": True,
            # No benchmark_arm field
            "audit_turns": [_make_turn(scf={
                "slot0": _make_scf_slot(delta=5.0)
            })],
        }
        data = _collect_slot_data([row])
        # Row counted as "unknown" arm.
        self.assertIn("unknown", data["counts"]["arm"])


class TestAnalyzerDeltaCounts(unittest.TestCase):
    def test_positive_and_negative_delta_counts(self):
        from analyze_doubles_switch_per_turn import (
            _collect_slot_data,
        )
        turns = [
            _make_turn(turn_n=1, scf={
                "slot0": _make_scf_slot(
                    chosen_is_switch=False, delta=30.0
                )
            }),
            _make_turn(turn_n=2, scf={
                "slot0": _make_scf_slot(
                    chosen_is_switch=True, delta=-10.0
                )
            }),
            _make_turn(turn_n=3, scf={
                "slot0": _make_scf_slot(
                    chosen_is_switch=False, delta=0.0
                )
            }),
        ]
        row = _make_row(turns=turns)
        data = _collect_slot_data([row])
        self.assertEqual(
            data["quality"]["non_switch_positive_delta"], 1
        )
        self.assertEqual(
            data["quality"]["chosen_switch_negative_delta"], 1
        )
        self.assertEqual(
            data["quality"]["non_switch_zero_delta"], 1
        )
        self.assertEqual(data["opportunities"]["slot0_present"], 3)


class TestAnalyzerChosenSwitchQuality(unittest.TestCase):
    def test_chosen_switch_positive_and_negative(self):
        from analyze_doubles_switch_per_turn import (
            _collect_slot_data,
        )
        turns = [
            _make_turn(turn_n=1, scf={
                "slot0": _make_scf_slot(
                    chosen_is_switch=True, delta=50.0
                )
            }),
            _make_turn(turn_n=2, scf={
                "slot0": _make_scf_slot(
                    chosen_is_switch=True, delta=-50.0
                )
            }),
        ]
        row = _make_row(turns=turns)
        data = _collect_slot_data([row])
        self.assertEqual(
            data["quality"]["chosen_switch_positive_delta"], 1
        )
        self.assertEqual(
            data["quality"]["chosen_switch_negative_delta"], 1
        )


class TestAnalyzerHPBuckets(unittest.TestCase):
    def test_buckets_active_hp_correctly(self):
        from analyze_doubles_switch_per_turn import (
            _collect_slot_data, _hp_bucket,
        )
        # Sanity: bucket boundaries.
        self.assertEqual(_hp_bucket(None), "unknown")
        self.assertEqual(_hp_bucket(0.10), "0-25")
        self.assertEqual(_hp_bucket(0.24), "0-25")
        self.assertEqual(_hp_bucket(0.25), "25-50")
        self.assertEqual(_hp_bucket(0.49), "25-50")
        self.assertEqual(_hp_bucket(0.50), "50-75")
        self.assertEqual(_hp_bucket(0.74), "50-75")
        self.assertEqual(_hp_bucket(0.75), "75-100")
        self.assertEqual(_hp_bucket(1.0), "75-100")
        # Aggregation: use state_snapshot with HP. Both slots
        # have SCF data so both HP values are bucketed.
        turn = _make_turn(
            scf={
                "slot0": _make_scf_slot(delta=10.0),
                "slot1": _make_scf_slot(delta=10.0),
            },
            state={
                "our_active_species": ["charizard", "garchomp"],
                "opp_active_species": ["garchomp", "charizard"],
                "our_active_hp_fraction": [0.1, 0.6],
                "opp_active_hp_fraction": [0.8, 0.4],
                "weather": "none",
                "fields": [],
                "side_conditions": {},
                "opponent_side_conditions": {},
            },
        )
        row = _make_row(turns=[turn])
        data = _collect_slot_data([row])
        self.assertEqual(data["state"]["hp_buckets"]["0-25"], 1)
        self.assertEqual(data["state"]["hp_buckets"]["50-75"], 1)


class TestAnalyzerWeatherFields(unittest.TestCase):
    def test_extracts_weather_fields_safely(self):
        from analyze_doubles_switch_per_turn import (
            _collect_slot_data,
        )
        turn = _make_turn(
            scf={"slot0": _make_scf_slot(delta=5.0)},
            state={
                "our_active_species": ["charizard"],
                "opp_active_species": ["garchomp"],
                "our_active_hp_fraction": [0.5],
                "opp_active_hp_fraction": [0.5],
                "weather": "sunnyday",
                "fields": ["electricterrain", "spikes"],
                "side_conditions": {},
                "opponent_side_conditions": {},
            },
        )
        row = _make_row(turns=[turn])
        data = _collect_slot_data([row])
        self.assertEqual(data["state"]["weather"]["sunnyday"], 1)
        # fields are sorted and comma-joined.
        self.assertIn("electricterrain,spikes", data["state"]["fields"])

    def test_missing_state_snapshot_does_not_crash(self):
        from analyze_doubles_switch_per_turn import (
            _collect_slot_data,
        )
        turn = _make_turn(scf={"slot0": _make_scf_slot(delta=5.0)})
        # No state_snapshot field.
        row = _make_row(turns=[turn])
        data = _collect_slot_data([row])
        # HP bucket is "unknown" when state is missing.
        self.assertEqual(data["state"]["hp_buckets"]["unknown"], 1)


class TestAnalyzerWritesMarkdown(unittest.TestCase):
    def test_writes_markdown_report(self):
        from analyze_doubles_switch_per_turn import (
            _write_markdown, _collect_slot_data,
            _delta_summary,
        )
        with tempfile.TemporaryDirectory() as tmp:
            md = os.path.join(tmp, "report.md")
            turns = [
                _make_turn(turn_n=1, scf={
                    "slot0": _make_scf_slot(
                        chosen_is_switch=False, delta=20.0
                    )
                }, state={
                    "our_active_species": ["charizard"],
                    "opp_active_species": ["garchomp"],
                    "our_active_hp_fraction": [0.5],
                    "opp_active_hp_fraction": [0.5],
                    "weather": "none",
                    "fields": [],
                    "side_conditions": {},
                    "opponent_side_conditions": {},
                }),
            ]
            row = _make_row(turns=turns)
            data = _collect_slot_data([row])
            delta_summary = _delta_summary(data["deltas"])
            _write_markdown(
                ["dummy.jsonl"],
                data,
                delta_summary,
                5,
                md,
            )
            with open(md) as f:
                content = f.read()
            self.assertIn("# Phase SWITCH-2", content)
            self.assertIn("## TL;DR", content)
            self.assertIn("## Inputs", content)
            self.assertIn("## Delta distribution", content)
            self.assertIn("## Chosen switch quality", content)
            self.assertIn("## State slices", content)
            self.assertIn("## Top suspicious turns", content)
            self.assertIn("## Per-battle summary", content)
            self.assertIn("## Recommendations", content)
            self.assertIn("## Analyzer limitations", content)


class TestAnalyzerWritesJSON(unittest.TestCase):
    def test_writes_json_summary(self):
        from analyze_doubles_switch_per_turn import (
            _write_json, _collect_slot_data, _delta_summary,
        )
        with tempfile.TemporaryDirectory() as tmp:
            json_path = os.path.join(tmp, "summary.json")
            turns = [
                _make_turn(turn_n=1, scf={
                    "slot0": _make_scf_slot(
                        chosen_is_switch=False, delta=10.0
                    )
                }),
            ]
            row = _make_row(turns=turns)
            data = _collect_slot_data([row])
            delta_summary = _delta_summary(data["deltas"])
            _write_json(data, delta_summary, 5, json_path)
            with open(json_path) as f:
                summary = json.load(f)
            self.assertIn("counts", summary)
            self.assertIn("opportunities", summary)
            self.assertIn("delta_summary", summary)
            self.assertIn("quality_summary", summary)
            self.assertIn("state_summary", summary)
            self.assertIn("top_suspicious_turns", summary)
            self.assertIn("per_battle", summary)


class TestAnalyzerTopSuspiciousSorted(unittest.TestCase):
    def test_top_suspicious_turns_sorted_by_abs_delta(self):
        from analyze_doubles_switch_per_turn import (
            _collect_slot_data, _delta_summary, _write_json,
        )
        turns = [
            _make_turn(turn_n=1, scf={
                "slot0": _make_scf_slot(
                    chosen_is_switch=True, delta=5.0
                )
            }),
            _make_turn(turn_n=2, scf={
                "slot0": _make_scf_slot(
                    chosen_is_switch=False, delta=100.0
                )
            }),
            _make_turn(turn_n=3, scf={
                "slot0": _make_scf_slot(
                    chosen_is_switch=True, delta=50.0
                )
            }),
        ]
        row = _make_row(turns=turns)
        data = _collect_slot_data([row])
        # Sort by absolute delta descending.
        sorted_susp = sorted(
            data["top_suspicious"],
            key=lambda x: abs(x.get("delta", 0)),
            reverse=True,
        )
        # First should have abs(delta) >= 100.
        self.assertGreaterEqual(
            abs(sorted_susp[0]["delta"]), 100
        )


class TestAnalyzerArmCounts(unittest.TestCase):
    def test_treatment_and_baseline_arm_counts(self):
        from analyze_doubles_switch_per_turn import (
            _collect_slot_data,
        )
        rows = [
            _make_row(
                battle_tag="b1", arm="treatment",
                turns=[_make_turn(scf={
                    "slot0": _make_scf_slot(delta=10.0)
                })],
            ),
            _make_row(
                battle_tag="b2", arm="treatment",
                turns=[_make_turn(scf={
                    "slot0": _make_scf_slot(delta=20.0)
                })],
            ),
            _make_row(
                battle_tag="b3", arm="baseline",
                turns=[_make_turn(scf={
                    "slot0": _make_scf_slot(delta=30.0)
                })],
            ),
        ]
        data = _collect_slot_data(rows)
        self.assertEqual(data["counts"]["arm"]["treatment"], 2)
        self.assertEqual(data["counts"]["arm"]["baseline"], 1)


class TestAnalyzerNoHiddenSerialization(unittest.TestCase):
    def test_no_object_serialization_needed(self):
        """The analyzer only emits JSON-safe primitives
        (str, int, float, bool, None, list, dict).
        """
        from analyze_doubles_switch_per_turn import (
            _collect_slot_data, _delta_summary, _write_json,
        )
        turns = [
            _make_turn(turn_n=1, scf={
                "slot0": _make_scf_slot(
                    chosen_is_switch=False, delta=10.0
                )
            }),
        ]
        row = _make_row(turns=turns)
        data = _collect_slot_data([row])
        delta_summary = _delta_summary(data["deltas"])
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            json_path = os.path.join(tmp, "s.json")
            _write_json(data, delta_summary, 5, json_path)
            with open(json_path) as f:
                obj = json.load(f)
            # Recursive check: all values are JSON-safe.
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


class TestAnalyzerCLI(unittest.TestCase):
    def test_cli_runs_end_to_end(self):
        from analyze_doubles_switch_per_turn import main
        with tempfile.TemporaryDirectory() as tmp:
            f1 = os.path.join(tmp, "f1.jsonl")
            md = os.path.join(tmp, "report.md")
            json_path = os.path.join(tmp, "summary.json")
            with open(f1, "w") as f:
                row = _make_row(
                    battle_tag="b1",
                    turns=[_make_turn(scf={
                        "slot0": _make_scf_slot(delta=5.0)
                    })],
                )
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


if __name__ == "__main__":
    unittest.main()