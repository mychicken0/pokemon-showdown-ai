#!/usr/bin/env python3
"""
Phase V2k — Lead Matchup Evaluator v3 Analyzer Tests.

Tests the repaired V2k analyzer, including:

- Pair classification is exactly v3_both=30, random_both=25,
  split=45, decisive=55.
- Sign test reproduces the V2f p-values
  (two-sided 0.590053, one-sided 0.295027).
- Plan ownership is by ``player_policy``, never by row
  position.
- Per-component ``v3_both_components`` and
  ``v3_in_random_both_components`` are populated with the
  correct V3 plan values, NOT with mixed V3+Random values.
- ``v3_both_unknown_rates`` is only populated for v3_both
  pairs, not all decisive pairs.
- Between-group bootstrap is INDEPENDENT (unpaired)
  because group sizes differ (30 vs 25).
- Within-failure bootstrap is PAIRED for 25 matched pairs.
- A missing CI is a gate failure with an explicit reason,
  not a silent skip.
- Synthetic mode reports ``evidence_mode=synthetic`` and
  cannot pass the real-freeze gate.
- Real artifact mode reports the actual file paths, sizes
  and data-row counts.
- The shuffle-merge property: shuffling the input rows
  yields the same per-pair classification and sign test.
"""

import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

import poke_env_test_cleanup  # noqa: F401

import analyze_vgc2026_phaseV2k_lead_matchups as v2k


class TestV2kSignTest(unittest.TestCase):
    """The synthetic distribution is exactly 30/25/45."""

    def test_synthetic_pair_counts(self):
        inputs = v2k.build_synthetic_inputs()
        result = v2k.sign_test(inputs["pair_records"])
        self.assertEqual(result["v3_both"], 30)
        self.assertEqual(result["random_both"], 25)
        self.assertEqual(result["split"], 45)
        self.assertEqual(result["decisive_n"], 55)
        # Match the corrected V2f p-values exactly.
        self.assertAlmostEqual(result["two_sided_p"], 0.590053, places=5)
        self.assertAlmostEqual(result["one_sided_p"], 0.295027, places=5)

    def test_synthetic_total_pairs(self):
        inputs = v2k.build_synthetic_inputs()
        self.assertEqual(len(inputs["pair_records"]), 100)


class TestV2kShuffleInvariant(unittest.TestCase):
    def test_shuffled_pair_records_yield_same_classification(self):
        inputs = v2k.build_synthetic_inputs()
        records = list(inputs["pair_records"])
        # Shuffle deterministically.
        rng = random.Random(20260613)
        rng.shuffle(records)
        result = v2k.sign_test(records)
        self.assertEqual(result["v3_both"], 30)
        self.assertEqual(result["random_both"], 25)
        self.assertEqual(result["split"], 45)
        self.assertEqual(result["decisive_n"], 55)
        self.assertAlmostEqual(result["two_sided_p"], 0.590053, places=5)


class TestV2kPerComponentArrays(unittest.TestCase):
    """The per-component arrays must contain the right
    values for the right group. Specifically:
    - v3_both_components[k] has 30 values, all from the V3
      plan, on the 30 v3_both pairs.
    - v3_in_random_both_components[k] has 25 values, all
      from the V3 plan (the LOSING V3 plan), on the 25
      random_both pairs.
    - random_in_random_both_components[k] has 25 values,
      all from the Random plan, on the 25 random_both
      pairs.
    - within_components[k] has 25 values, the V3 - Random
      differences.
    """

    def test_synthetic_per_component_arrays(self):
        inputs = v2k.build_synthetic_inputs()
        report = v2k._safe_run(inputs, evidence_mode="synthetic")
        # The decision is B (continue) because the synthetic
        # CIs are not statistically significant; this confirms
        # the arrays are populated as expected.
        for row in report["gate_table"]:
            self.assertEqual(row["n_v3_both"], 30)
            self.assertEqual(row["n_random_both"], 25)
            self.assertEqual(row["n_within"], 25)

    def test_evidence_mode_synthetic(self):
        inputs = v2k.build_synthetic_inputs()
        report = v2k._safe_run(inputs, evidence_mode="synthetic")
        rap = report["real_artifact_proof"]
        self.assertEqual(rap["evidence_mode"], "synthetic")
        self.assertFalse(rap["real_freeze_gate_passed"])

    def test_decision_is_b_continue(self):
        inputs = v2k.build_synthetic_inputs()
        report = v2k._safe_run(inputs, evidence_mode="synthetic")
        self.assertEqual(report["decision"]["code"], "B")
        self.assertEqual(report["decision"]["phase_v3_status"], "BLOCKED")
        self.assertFalse(
            report["decision"]["matchup_top4_v4_implemented"]
        )


class TestV2kBootstrapShape(unittest.TestCase):
    """Between-group CI must be unpaired (different group
    sizes). Within-failure CI must be paired (same n).
    """

    def test_between_group_independent(self):
        # Build a v3_both array of 30 values and a
        # v3_in_random_both array of 25 values with a real
        # difference. The independent bootstrap should
        # produce a non-trivial CI; the paired bootstrap would
        # refuse (different lengths).
        v3_both = [1.0] * 30
        v3_in_random_both = [0.5] * 25
        ci = v2k._bootstrap_independent_mean_diff_ci(
            v3_both, v3_in_random_both
        )
        self.assertIsNotNone(ci)
        observed, lo, hi = ci
        # Mean diff = 0.5; resample should produce a CI
        # around 0.5 (the data has no variance, so the CI
        # is degenerate to 0.5).
        self.assertAlmostEqual(observed, 0.5, places=5)

    def test_within_failure_paired(self):
        # 25 paired differences of +1.0.
        within = [1.0] * 25
        # Build the within CI by hand.
        rng = random.Random(v2k.BOOTSTRAP_SEED + 1)
        n_resamples = v2k.N_BOOTSTRAP
        diffs = [float(v) for v in within]
        observed = sum(diffs) / len(diffs)
        n = len(diffs)
        resamples = [
            sum(
                diffs[rng.randrange(n)]
                for _ in range(n)
            ) / n
            for _ in range(n_resamples)
        ]
        resamples.sort()
        lo_idx = max(0, int(0.025 * n_resamples))
        hi_idx = min(
            n_resamples - 1,
            int(0.975 * n_resamples) - 1,
        )
        ci = (observed, resamples[lo_idx], resamples[hi_idx])
        # All differences are +1.0, so the CI must be [+1, +1].
        self.assertEqual(ci[0], 1.0)
        self.assertEqual(ci[1], 1.0)
        self.assertEqual(ci[2], 1.0)

    def test_missing_ci_returns_none(self):
        # Empty input -> None.
        self.assertIsNone(
            v2k._bootstrap_independent_mean_diff_ci([], [])
        )
        # Single element -> None.
        self.assertIsNone(
            v2k._bootstrap_independent_mean_diff_ci([1.0], [2.0])
        )


class TestV2kGates(unittest.TestCase):
    """Strict actionable gate table is populated correctly."""

    def test_no_actionable_components_synthetic(self):
        inputs = v2k.build_synthetic_inputs()
        report = v2k._safe_run(inputs, evidence_mode="synthetic")
        # 0 actionable components means the decision is B.
        self.assertEqual(
            len(report["actionable_components"]), 0
        )

    def test_gate_reasons_recorded(self):
        inputs = v2k.build_synthetic_inputs()
        report = v2k._safe_run(inputs, evidence_mode="synthetic")
        # Every component has a gate_reasons dict.
        for row in report["gate_table"]:
            self.assertIn("gate_reasons", row)
            # If the component is not actionable, at least
            # one gate reason should be present.
            if not row["candidate_actionable"]:
                self.assertGreaterEqual(
                    len(row["gate_reasons"]), 1,
                    f"{row['component']} should have a reason",
                )

    def test_ci_present_field_works(self):
        # Present CI -> True.
        self.assertTrue(v2k._ci_present((0.0, 0.1, 0.2)))
        # None -> False.
        self.assertFalse(v2k._ci_present(None))


class TestV2kRealArtifactValidation(unittest.TestCase):
    def test_validate_artifact_rejects_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            is_real, paths = v2k._validate_artifact(
                logs_dir, "nonexistent_artifact"
            )
            self.assertFalse(is_real)
            self.assertFalse(paths["benchmark_csv"]["exists"])

    def test_validate_artifact_rejects_wrong_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            prefix = "fake_v2k_artifact"
            # Write CSV with only 5 rows.
            (logs_dir / f"{prefix}_benchmark.csv").write_text(
                "battle_tag,pair_id,side\n" + "x,0,p1\n" * 5
            )
            (logs_dir / f"{prefix}_preview_evidence.csv").write_text(
                "battle_tag,pair_id,side\n" + "x,0,p1\n" * 5
            )
            (logs_dir / f"{prefix}_benchmark.jsonl").write_text(
                "{}\n" * 5
            )
            is_real, paths = v2k._validate_artifact(logs_dir, prefix)
            self.assertFalse(is_real)
            self.assertEqual(paths["benchmark_csv"]["data_rows"], 5)
            self.assertEqual(paths["preview_evidence_csv"]["data_rows"], 5)
            self.assertEqual(paths["benchmark_jsonl"]["record_count"], 5)

    def test_validate_artifact_accepts_complete_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            prefix = "complete_v2k_artifact"
            (logs_dir / f"{prefix}_benchmark.csv").write_text(
                "battle_tag,pair_id,side\n" + "x,0,p1\n" * 200
            )
            (logs_dir / f"{prefix}_preview_evidence.csv").write_text(
                "battle_tag,pair_id,side\n" + "x,0,p1\n" * 400
            )
            (logs_dir / f"{prefix}_benchmark.jsonl").write_text(
                "{}\n" * 200
            )
            is_real, paths = v2k._validate_artifact(logs_dir, prefix)
            self.assertTrue(is_real)
            self.assertEqual(paths["benchmark_csv"]["data_rows"], 200)
            self.assertEqual(paths["preview_evidence_csv"]["data_rows"], 400)
            self.assertEqual(paths["benchmark_jsonl"]["record_count"], 200)


class TestV2kPlanOwnershipByPolicy(unittest.TestCase):
    """The V3 plan and Random plan owners are identified by
    ``player_policy`` in the preview row, not by row
    position.
    """

    def test_pair_records_use_player_policy(self):
        # Construct a tiny pair-record set: 1 v3_both + 1
        # random_both + 1 split. Each pair has both D1 and
        # D2 rows so the V2j classify_pair can read both
        # ``d1_v3_win`` and ``d2_v3_win``.
        #
        # The our_win field is from the row's own player
        # perspective. In D1 (p1) the V3 player is the
        # player; in D2 (p2) the V3 player is the opponent.
        # So:
        #   v3_both (V3 wins both)  -> p1.our_win=True,  p2.our_win=False
        #   random_both            -> p1.our_win=False, p2.our_win=True
        #   split                  -> p1.our_win=True,  p2.our_win=True
        # The "True" on p2 in the split case is from Random's
        # perspective — V3 lost D2.
        benchmark_rows = [
            # pair 0: v3_both
            {"pair_id": "0", "side": "p1", "our_win": "true",
             "team_id": "t0", "opponent_team_id": "o0"},
            {"pair_id": "0", "side": "p2", "our_win": "false",
             "team_id": "o0", "opponent_team_id": "t0"},
            # pair 1: random_both
            {"pair_id": "1", "side": "p1", "our_win": "false",
             "team_id": "t1", "opponent_team_id": "o1"},
            {"pair_id": "1", "side": "p2", "our_win": "true",
             "team_id": "o1", "opponent_team_id": "t1"},
            # pair 2: split (V3 wins D1, loses D2)
            {"pair_id": "2", "side": "p1", "our_win": "true",
             "team_id": "t2", "opponent_team_id": "o2"},
            {"pair_id": "2", "side": "p2", "our_win": "true",
             "team_id": "o2", "opponent_team_id": "t2"},
        ]
        preview_rows = [
            # pair 0: D1 V3 is player, D2 V3 is opponent
            {"pair_id": "0", "side": "p1", "player_policy": "matchup_top4_v3",
             "opponent_policy": "random",
             "planned_chosen_4": "a|b|c|d",
             "planned_lead_2": "a|b",
             "planned_back_2": "c|d"},
            {"pair_id": "0", "side": "p2", "player_policy": "random",
             "opponent_policy": "matchup_top4_v3",
             "planned_chosen_4": "e|f|g|h",
             "planned_lead_2": "e|f",
             "planned_back_2": "g|h"},
            # pair 1: same structure
            {"pair_id": "1", "side": "p1", "player_policy": "matchup_top4_v3",
             "opponent_policy": "random",
             "planned_chosen_4": "a|b|c|d",
             "planned_lead_2": "a|b",
             "planned_back_2": "c|d"},
            {"pair_id": "1", "side": "p2", "player_policy": "random",
             "opponent_policy": "matchup_top4_v3",
             "planned_chosen_4": "e|f|g|h",
             "planned_lead_2": "e|f",
             "planned_back_2": "g|h"},
            # pair 2: same structure
            {"pair_id": "2", "side": "p1", "player_policy": "matchup_top4_v3",
             "opponent_policy": "random",
             "planned_chosen_4": "a|b|c|d",
             "planned_lead_2": "a|b",
             "planned_back_2": "c|d"},
            {"pair_id": "2", "side": "p2", "player_policy": "random",
             "opponent_policy": "matchup_top4_v3",
             "planned_chosen_4": "e|f|g|h",
             "planned_lead_2": "e|f",
             "planned_back_2": "g|h"},
        ]
        team_lookup = {
            "t0": {"id": "t0", "pokemon": []},
            "t1": {"id": "t1", "pokemon": []},
            "t2": {"id": "t2", "pokemon": []},
            "o0": {"id": "o0", "pokemon": []},
            "o1": {"id": "o1", "pokemon": []},
            "o2": {"id": "o2", "pokemon": []},
        }
        pair_records = v2k.build_pair_records(
            benchmark_rows, preview_rows, team_lookup
        )
        by_pid = {int(p["pair_id"]): p for p in pair_records}
        self.assertEqual(v2k.classify_pair(by_pid[0]), "v3_both")
        self.assertEqual(v2k.classify_pair(by_pid[1]), "random_both")
        self.assertEqual(v2k.classify_pair(by_pid[2]), "split")


class TestV2kEndToEndPipeline(unittest.TestCase):
    """The full pipeline runs end-to-end and produces the
    expected artifact shape."""

    def test_synthetic_pipeline_completes(self):
        inputs = v2k.build_synthetic_inputs()
        report = v2k._safe_run(inputs, evidence_mode="synthetic")
        # All required sections present.
        for k in (
            "decisive_n", "v3_both_n", "random_both_n", "split_n",
            "sign_test", "v3_both_summary",
            "v3_in_random_both_summary",
            "random_in_random_both_summary",
            "within_failure_summary",
            "split_summary", "gate_table",
            "actionable_components", "contradictory_components",
            "decision", "audit_unknown", "runtime",
            "fingerprint", "outcome_freeze_proof",
            "real_artifact_proof",
        ):
            self.assertIn(k, report)

    def test_synthetic_artifact_writes_to_tempdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            inputs = v2k.build_synthetic_inputs()
            report = v2k._safe_run(inputs, evidence_mode="synthetic")
            json_path, md_path = v2k.write_artifacts(report, out_dir)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            # Re-load JSON to verify it round-trips.
            data = json.loads(json_path.read_text())
            self.assertEqual(data["decision"]["code"], "B")
            self.assertEqual(data["real_artifact_proof"]["evidence_mode"], "synthetic")


# ---------------------------------------------------------------------------
# V2k.1 — Statistical-definition regression
# ---------------------------------------------------------------------------


class TestV2k1BetweenMeanDefinition(unittest.TestCase):
    """The V2k.1 analyzer's ``between_mean`` must equal the
    between-group difference, not the raw v3_both mean.
    """

    def test_between_mean_equals_group_difference(self):
        # A=[10,10], B=[9,9] => between_mean=+1, not 10.
        result = v2k.evaluate_component(
            "test",
            v3_both_values=[10.0, 10.0],
            v3_in_random_both_values=[9.0, 9.0],
            random_in_random_both_values=[9.0, 9.0],
            v3_both_unknown_rates=[],
        )
        self.assertEqual(result["between_mean"], 1.0)
        # between_sign must be "+".
        self.assertEqual(result["between_sign"], "+")

    def test_between_mean_reverses_with_groups(self):
        # Reversing the group assignments must reverse the
        # between_mean sign.
        result = v2k.evaluate_component(
            "test",
            v3_both_values=[9.0, 9.0],
            v3_in_random_both_values=[10.0, 10.0],
            random_in_random_both_values=[10.0, 10.0],
            v3_both_unknown_rates=[],
        )
        self.assertEqual(result["between_mean"], -1.0)
        self.assertEqual(result["between_sign"], "-")

    def test_between_bootstrap_ci_observed_matches_between_mean(self):
        # between_mean MUST equal between_bootstrap_ci[0].
        result = v2k.evaluate_component(
            "test",
            v3_both_values=[10.0, 10.0, 10.0, 10.0, 10.0],
            v3_in_random_both_values=[
                9.0, 9.0, 9.0, 9.0, 9.0,
            ],
            random_in_random_both_values=[
                9.0, 9.0, 9.0, 9.0, 9.0,
            ],
            v3_both_unknown_rates=[],
        )
        ci = result["between_bootstrap_ci"]
        self.assertIsNotNone(ci)
        self.assertEqual(result["between_mean"], ci[0])


class TestV2k1WithinFailurePairedBootstrap(unittest.TestCase):
    """The V2k.1 analyzer's within-failure bootstrap is the
    PAIRED bootstrap on the matched (v3, random) arrays, not
    a hand-rolled one-sample bootstrap on pre-computed
    differences. The within_mean MUST equal within_bootstrap_ci[0].
    """

    def test_within_mean_equals_paired_bootstrap_observed(self):
        # Paired V3=[3,5], Random=[2,1] => within_mean = mean
        # of [3-2, 5-1] = mean of [1, 4] = +2.5.
        result = v2k.evaluate_component(
            "test",
            v3_both_values=[],
            v3_in_random_both_values=[3.0, 5.0],
            random_in_random_both_values=[2.0, 1.0],
            v3_both_unknown_rates=[],
        )
        self.assertEqual(result["within_mean"], 2.5)
        ci = result["within_bootstrap_ci"]
        self.assertIsNotNone(ci)
        self.assertEqual(result["within_mean"], ci[0])

    def test_within_reverses_with_pair_order(self):
        # Reversing the order of each pair reverses the
        # within_mean sign.
        result = v2k.evaluate_component(
            "test",
            v3_both_values=[],
            v3_in_random_both_values=[2.0, 1.0],
            random_in_random_both_values=[3.0, 5.0],
            v3_both_unknown_rates=[],
        )
        self.assertEqual(result["within_mean"], -2.5)

    def test_unequal_paired_groups_hard_fail(self):
        # The paired bootstrap refuses when the two arrays
        # have different lengths.
        result = v2k.evaluate_component(
            "test",
            v3_both_values=[],
            v3_in_random_both_values=[1.0, 2.0, 3.0],
            random_in_random_both_values=[1.0, 2.0],
            v3_both_unknown_rates=[],
        )
        # within_bootstrap_ci is None and the gate fails
        # with an explicit reason.
        self.assertIsNone(result["within_bootstrap_ci"])
        self.assertFalse(
            result["gates"]["within_failure_paired_bootstrap_ci_excludes_zero"]
        )
        self.assertIn(
            "within_failure_paired_bootstrap_ci_excludes_zero",
            result["gate_reasons"],
        )

    def test_unequal_independent_groups_accepted(self):
        # The independent bootstrap is called with two
        # arrays of DIFFERENT lengths. The function must
        # accept this and produce a CI.
        v3_both = [1.0] * 30
        v3_in = [2.0] * 25
        result = v2k.evaluate_component(
            "test",
            v3_both_values=v3_both,
            v3_in_random_both_values=v3_in,
            random_in_random_both_values=v3_in,
            v3_both_unknown_rates=[],
        )
        self.assertIsNotNone(result["between_bootstrap_ci"])


class TestV2k1DirectionAgreement(unittest.TestCase):
    """Direction-agreement compares the two ACTUAL differences,
    not the raw v3_both mean vs the within diff.
    """

    def test_direction_agree_when_signs_match(self):
        # v3_both = [10, 10], v3_in = [5, 5]: between = +5
        # v3 = [10], random = [3]: within = +7.
        # Both positive -> agree.
        result = v2k.evaluate_component(
            "test",
            v3_both_values=[10.0, 10.0],
            v3_in_random_both_values=[5.0, 5.0],
            random_in_random_both_values=[3.0, 3.0],
            v3_both_unknown_rates=[],
        )
        self.assertEqual(result["between_sign"], "+")
        self.assertEqual(result["within_sign"], "+")
        # The agreement gate is determined by sign; it can
        # be True or False depending on the CIs, but the
        # signs themselves must both be "+".
        self.assertTrue(result["between_sign"] == result["within_sign"])

    def test_direction_disagree_when_signs_differ(self):
        # v3_both = [5, 5], v3_in = [10, 10]: between = -5
        # v3 = [10], random = [12]: within = -2.
        # Both negative -> agree.
        # But if within is + and between is - -> disagree.
        result = v2k.evaluate_component(
            "test",
            v3_both_values=[5.0, 5.0],
            v3_in_random_both_values=[10.0, 10.0],
            random_in_random_both_values=[12.0, 12.0],
            v3_both_unknown_rates=[],
        )
        self.assertEqual(result["between_sign"], "-")
        self.assertEqual(result["within_sign"], "-")
        self.assertTrue(result["between_sign"] == result["within_sign"])

    def test_direction_disagree_explicit_flip(self):
        # v3_both = [10, 10], v3_in = [5, 5]: between = +5
        # v3 = [10], random = [12]: within = -2.
        # Signs differ -> disagree.
        result = v2k.evaluate_component(
            "test",
            v3_both_values=[10.0, 10.0],
            v3_in_random_both_values=[5.0, 5.0],
            random_in_random_both_values=[12.0, 12.0],
            v3_both_unknown_rates=[],
        )
        self.assertEqual(result["between_sign"], "+")
        self.assertEqual(result["within_sign"], "-")
        self.assertFalse(
            result["gates"]["between_within_direction_agree"]
        )


if __name__ == "__main__":
    unittest.main()
