#!/usr/bin/env python3
"""
Test suite for VGC 2026 Phase V2f paired qualification.

Tests cover:
- exactly 100 D1 and 100 D2 specs
- identical team IDs per pair
- policy-stable preview seeds
- different pair IDs receive different seeds
- D1/D2 policy assignment
- V3 outcome normalization for both arms
- pair merge by pair_id with shuffled row order
- V3-both, Random-both and split classification
- incomplete/duplicate pair rejection
- wrong policy rejection
- team identity mismatch rejection
- preview ownership uses player_policy only
- opponent_policy metadata cannot own a plan
- missing observed lead rejection
- preview mismatch rejection
- malformed JSON rejection
- duplicate tag rejection
- CSV/JSONL disagreement rejection
- Wilson interval and exact binomial known values
- two-sided and one-sided paired p-values
- side-collapse gate
- no placeholder, skipped or pass-only tests
- natural process termination
"""

import poke_env_test_cleanup  # Must precede poke-env imports.

import csv
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot_vgc2026_phaseV2f_qualification import (
    V2fPairedQualificationRunner,
    validate_v2f_qualification_artifacts,
)
from analyze_vgc2026_phaseV2f_qualification import (
    aggregate as v2f_aggregate,
    evaluate_gates,
    exact_binomial_p_value,
    extract_pairs,
    paired_sign_test,
    plan_consistency_stats,
    preview_evidence_stats,
    _v3_perspective,
    _v3_plan_from_preview_rows,
    wilson_interval,
)


# ---------------------------------------------------------------------------
# Runner specification tests
# ---------------------------------------------------------------------------


class TestRunnerSpecifications(unittest.TestCase):

    def _specs(self, pairs: int = 100) -> Dict[str, List[Dict[str, Any]]]:
        runner = V2fPairedQualificationRunner.__new__(
            V2fPairedQualificationRunner
        )
        runner.pairs = pairs

        class _StubPool:
            def __init__(self, length: int) -> None:
                self._length = length

            def __iter__(self) -> Any:
                return iter(range(self._length))

            def __len__(self) -> int:
                return self._length

        runner.my_pool = _StubPool(pairs)
        runner.opponent_pool = _StubPool(pairs)
        return runner.generate_arm_specifications()

    def test_exactly_100_d1_and_100_d2_specs(self):
        specs = self._specs(pairs=100)
        self.assertEqual(len(specs["D1"]), 100)
        self.assertEqual(len(specs["D2"]), 100)

    def test_d1_d2_have_same_pair_ids(self):
        specs = self._specs(pairs=100)
        d1_ids = sorted(spec["pair_id"] for spec in specs["D1"])
        d2_ids = sorted(spec["pair_id"] for spec in specs["D2"])
        self.assertEqual(d1_ids, d2_ids)
        self.assertEqual(d1_ids, list(range(100)))

    def test_identical_team_ids_per_pair(self):
        specs = self._specs(pairs=100)
        for d1, d2 in zip(specs["D1"], specs["D2"]):
            self.assertEqual(d1["pair_id"], d2["pair_id"])
            self.assertEqual(d1["our_team_idx"], d2["our_team_idx"])
            self.assertEqual(d1["opp_team_idx"], d2["opp_team_idx"])

    def test_d1_policy_assignment(self):
        specs = self._specs(pairs=10)
        for spec in specs["D1"]:
            self.assertEqual(spec["player_policy"], "matchup_top4_v3")
            self.assertEqual(spec["opponent_policy"], "random")
            self.assertEqual(spec["side"], "p1")

    def test_d2_policy_assignment(self):
        specs = self._specs(pairs=10)
        for spec in specs["D2"]:
            self.assertEqual(spec["player_policy"], "random")
            self.assertEqual(spec["opponent_policy"], "matchup_top4_v3")
            self.assertEqual(spec["side"], "p2")


class TestPreviewSeeds(unittest.TestCase):

    def _runner(self) -> V2fPairedQualificationRunner:
        return V2fPairedQualificationRunner.__new__(
            V2fPairedQualificationRunner
        )

    def test_policy_stable_seeds(self):
        runner = self._runner()
        runner.seed = 42
        seeds_a = runner.get_preview_seeds(0, 0, "matchup_top4_v3", "random")
        seeds_b = runner.get_preview_seeds(0, 0, "matchup_top4_v3", "random")
        self.assertEqual(seeds_a, seeds_b)

    def test_different_pair_ids_get_different_seeds(self):
        runner = self._runner()
        runner.seed = 42
        seeds_a = runner.get_preview_seeds(0, 0, "matchup_top4_v3", "random")
        seeds_b = runner.get_preview_seeds(1, 0, "matchup_top4_v3", "random")
        self.assertNotEqual(seeds_a, seeds_b)

    def test_v3_offsets_differ_from_v2(self):
        runner = self._runner()
        runner.seed = 42
        seeds_v3 = runner.get_preview_seeds(0, 0, "matchup_top4_v3", "random")
        # V2 runner offsets are +101 / +202, V3 uses +401 / +202.
        v3_player = seeds_v3[0]
        v3_opponent = seeds_v3[1]
        self.assertEqual(v3_player - v3_opponent, 401 - 202)


# ---------------------------------------------------------------------------
# Outcome normalization
# ---------------------------------------------------------------------------


class TestV3OutcomeNormalization(unittest.TestCase):

    def test_d1_v3_win_uses_our_win(self):
        d1_row = {
            "battle_tag": "D1_0000_p1",
            "our_win": "True",
            "opponent_win": "False",
        }
        outcome = _v3_perspective(d1_row)
        self.assertEqual(outcome["outcome"], "win")

    def test_d1_v3_loss_uses_our_win(self):
        d1_row = {
            "battle_tag": "D1_0000_p1",
            "our_win": "False",
            "opponent_win": "True",
        }
        outcome = _v3_perspective(d1_row)
        self.assertEqual(outcome["outcome"], "loss")

    def test_d2_v3_win_uses_opponent_win(self):
        d2_row = {
            "battle_tag": "D2_0000_p2",
            "our_win": "False",
            "opponent_win": "True",
        }
        outcome = _v3_perspective(d2_row)
        self.assertEqual(outcome["outcome"], "win")

    def test_d2_v3_loss_uses_opponent_win(self):
        d2_row = {
            "battle_tag": "D2_0000_p2",
            "our_win": "True",
            "opponent_win": "False",
        }
        outcome = _v3_perspective(d2_row)
        self.assertEqual(outcome["outcome"], "loss")

    def test_unexpected_arm_is_invalid(self):
        outcome = _v3_perspective({
            "battle_tag": "X1_0000_p1",
            "our_win": "True",
            "opponent_win": "False",
        })
        self.assertEqual(outcome["outcome"], "invalid")


# ---------------------------------------------------------------------------
# Pair merge by pair_id
# ---------------------------------------------------------------------------


class TestPairMergeByID(unittest.TestCase):

    def _build_rows(self) -> List[Dict[str, Any]]:
        rows = []
        for pair_id in range(5):
            rows.append({
                "pair_id": str(pair_id),
                "battle_tag": f"D1_{pair_id:04d}_p1",
                "team_id": f"team_{pair_id}",
                "opponent_team_id": f"opp_{pair_id}",
                "our_win": "True",
                "opponent_win": "False",
            })
            rows.append({
                "pair_id": str(pair_id),
                "battle_tag": f"D2_{pair_id:04d}_p2",
                "team_id": f"team_{pair_id}",
                "opponent_team_id": f"opp_{pair_id}",
                "our_win": "False",
                "opponent_win": "True",
            })
        return rows

    def test_pair_merge_uses_pair_id_not_row_order(self):
        rows = self._build_rows()
        import random
        random.seed(0)
        random.shuffle(rows)
        pairs = extract_pairs(rows, [])
        self.assertEqual(len(pairs), 5)
        for pair in pairs:
            self.assertEqual(pair["status"], "ok")
            self.assertEqual(pair["d1_v3"]["outcome"], "win")
            self.assertEqual(pair["d2_v3"]["outcome"], "win")
            self.assertTrue(pair["team_identity_match"])

    def test_shuffled_rows_preserve_merge(self):
        rows = self._build_rows()
        first = extract_pairs(rows, [])
        import random
        random.seed(1)
        random.shuffle(rows)
        second = extract_pairs(rows, [])
        first_ids = [p["pair_id"] for p in first]
        second_ids = [p["pair_id"] for p in second]
        self.assertEqual(first_ids, second_ids)


# ---------------------------------------------------------------------------
# Outcome classification
# ---------------------------------------------------------------------------


class TestOutcomeClassification(unittest.TestCase):

    def _pair(self, d1: str, d2: str) -> Dict[str, Any]:
        return {
            "pair_id": 0,
            "status": "ok",
            "d1_v3": {"outcome": d1},
            "d2_v3": {"outcome": d2},
        }

    def test_v3_both(self):
        v3_both, random_both, split, invalid, _, _ = paired_sign_test(
            [self._pair("win", "win")]
        )
        self.assertEqual(v3_both, 1)
        self.assertEqual(random_both, 0)
        self.assertEqual(split, 0)

    def test_random_both(self):
        v3_both, random_both, split, invalid, _, _ = paired_sign_test(
            [self._pair("loss", "loss")]
        )
        self.assertEqual(v3_both, 0)
        self.assertEqual(random_both, 1)
        self.assertEqual(split, 0)

    def test_split(self):
        v3_both, random_both, split, invalid, two_sided, one_sided = paired_sign_test(
            [self._pair("win", "loss")]
        )
        self.assertEqual(v3_both, 0)
        self.assertEqual(random_both, 0)
        self.assertEqual(split, 1)
        self.assertEqual(two_sided, 1.0)
        self.assertEqual(one_sided, 1.0)

    def test_real_artifact_counts_exclude_split_pairs_from_sign_test(self):
        pairs = (
            [self._pair("win", "win") for _ in range(30)]
            + [self._pair("loss", "loss") for _ in range(25)]
            + [self._pair("win", "loss") for _ in range(45)]
        )
        v3_both, random_both, split, invalid, two_sided, one_sided = (
            paired_sign_test(pairs)
        )
        self.assertEqual((v3_both, random_both, split, invalid), (30, 25, 45, 0))
        self.assertAlmostEqual(two_sided, 0.5900533317766357)
        self.assertAlmostEqual(one_sided, 0.29502666588831783)


# ---------------------------------------------------------------------------
# Plan ownership
# ---------------------------------------------------------------------------


class TestPlanOwnership(unittest.TestCase):

    def test_player_policy_v3_owns_plan(self):
        plan = _v3_plan_from_preview_rows([
            {
                "battle_tag": "D1_0000_p1",
                "player_policy": "matchup_top4_v3",
                "opponent_policy": "random",
                "planned_chosen_4": "a|b|c|d",
                "planned_lead_2": "a|b",
                "planned_back_2": "c|d",
            },
        ])
        self.assertIsNotNone(plan)
        self.assertEqual(plan["chosen_4"], ["a", "b", "c", "d"])
        self.assertEqual(plan["source_player_policy"], "matchup_top4_v3")

    def test_opponent_policy_metadata_does_not_own_row_plan(self):
        # opponent_policy = "matchup_top4_v3" is metadata, not
        # ownership. The plan must be ignored because player_policy
        # is "random".
        plan = _v3_plan_from_preview_rows([
            {
                "battle_tag": "D1_0000_p1",
                "player_policy": "random",
                "opponent_policy": "matchup_top4_v3",
                "planned_chosen_4": "a|b|c|d",
                "planned_lead_2": "a|b",
                "planned_back_2": "c|d",
            },
        ])
        self.assertIsNone(plan)


# ---------------------------------------------------------------------------
# Plan consistency
# ---------------------------------------------------------------------------


class TestPlanConsistency(unittest.TestCase):

    def test_plan_consistency_reports_match(self):
        pairs = [
            {
                "pair_id": 0,
                "status": "ok",
                "d1_v3_plan_available": True,
                "d2_v3_plan_available": True,
                "v3_plans_match": True,
            },
        ]
        stats = plan_consistency_stats(pairs)
        self.assertEqual(stats["v3_plan_matches"], 1)
        self.assertEqual(stats["v3_plan_mismatches"], 0)

    def test_plan_consistency_reports_mismatch(self):
        pairs = [
            {
                "pair_id": 0,
                "status": "ok",
                "d1_v3_plan_available": True,
                "d2_v3_plan_available": True,
                "v3_plans_match": False,
                "d1_v3_plan": {"chosen_4": ["a"]},
                "d2_v3_plan": {"chosen_4": ["b"]},
            },
        ]
        stats = plan_consistency_stats(pairs)
        self.assertEqual(stats["v3_plan_mismatches"], 1)
        self.assertEqual(stats["v3_plan_mismatch_pairs"][0]["pair_id"], 0)


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


class TestStatisticsHelpers(unittest.TestCase):

    def test_exact_binomial_known_values(self):
        self.assertEqual(exact_binomial_p_value(0, 0), 1.0)
        self.assertAlmostEqual(
            exact_binomial_p_value(10, 10), 0.001953125
        )
        self.assertAlmostEqual(
            exact_binomial_p_value(10, 10, alternative="greater"),
            0.0009765625,
        )

    def test_wilson_interval_contains_half_for_even_record(self):
        low, high = wilson_interval(50, 100)
        self.assertLess(low, 0.5)
        self.assertGreater(high, 0.5)

    def test_paired_two_sided_and_one_sided(self):
        # Build 8 decisive pairs all V3 winning, 2 not decisive
        # (incomplete). The decisive count is 8, all V3 wins. The
        # one-sided p-value is sum(P(k >= 8) | k ~ Bin(8, 0.5))
        # and the two-sided p-value uses probabilities <= observed.
        pairs = []
        for _ in range(8):
            pairs.append({
                "pair_id": 0,
                "status": "ok",
                "d1_v3": {"outcome": "win"},
                "d2_v3": {"outcome": "win"},
            })
        for _ in range(2):
            pairs.append({
                "pair_id": 0,
                "status": "incomplete",
                "d1_v3": {"outcome": "invalid"},
                "d2_v3": None,
            })
        _, _, _, _, two_sided, one_sided = paired_sign_test(pairs)
        # 8 wins out of 8 decisive trials, so the one-sided p-value
        # equals 0.5**8 = 0.00390625.
        self.assertAlmostEqual(one_sided, 0.5 ** 8)
        # The two-sided p-value is 2 * 0.5**8 = 0.0078125 because
        # only 8/8 has equal-or-lower probability than the observed
        # 8/8.
        self.assertAlmostEqual(two_sided, 2 * 0.5 ** 8)


# ---------------------------------------------------------------------------
# Side-collapse gate
# ---------------------------------------------------------------------------


class TestSideCollapseGate(unittest.TestCase):

    def _aggregate(self, d1_wins, d1_losses, d2_wins, d2_losses):
        # Synthesize a minimal aggregate for the gate check.
        return {
            "total_pairs": 100,
            "completed_pairs": 100,
            "d1": {
                "battles": d1_wins + d1_losses,
                "v3_wins": d1_wins,
                "v3_losses": d1_losses,
                "v3_ties": 0,
                "v3_win_rate": (
                    d1_wins / (d1_wins + d1_losses)
                    if (d1_wins + d1_losses) else 0.0
                ),
            },
            "d2": {
                "battles": d2_wins + d2_losses,
                "v3_wins": d2_wins,
                "v3_losses": d2_losses,
                "v3_ties": 0,
                "v3_win_rate": (
                    d2_wins / (d2_wins + d2_losses)
                    if (d2_wins + d2_losses) else 0.0
                ),
            },
            "combined": {
                "battles": d1_wins + d1_losses + d2_wins + d2_losses,
                "v3_wins": d1_wins + d2_wins,
                "v3_losses": d1_losses + d2_losses,
                "v3_ties": 0,
                "v3_win_rate": (
                    (d1_wins + d2_wins)
                    / (d1_wins + d1_losses + d2_wins + d2_losses)
                ),
                "wilson_95_ci": [0.0, 1.0],
                "two_sided_binomial_p_value": 1.0,
            },
            "paired": {
                "v3_both": 0,
                "random_both": 0,
                "split": 0,
                "invalid": 0,
                "two_sided_p_value": 1.0,
                "one_sided_greater_p_value": 1.0,
            },
        }

    def test_side_collapse_passes_when_both_above_40_percent(self):
        agg = self._aggregate(45, 55, 45, 55)
        preview_stats = {
            "preview_rows": 400,
            "preview_matches": 400,
            "observed_leads_populated": 400,
            "v3_player_policy_rows": 200,
        }
        plan_stats = {
            "pairs_with_both_v3_plans": 100,
            "v3_plan_matches": 100,
            "v3_plan_mismatches": 0,
        }
        gates = evaluate_gates(
            agg, preview_stats, plan_stats, tests_passed=True
        )
        self.assertTrue(gates["no_suspicious_side_collapse"])

    def test_side_collapse_fails_when_d1_below_40_percent(self):
        agg = self._aggregate(30, 70, 60, 40)
        preview_stats = {
            "preview_rows": 400,
            "preview_matches": 400,
            "observed_leads_populated": 400,
            "v3_player_policy_rows": 200,
        }
        plan_stats = {
            "pairs_with_both_v3_plans": 100,
            "v3_plan_matches": 100,
            "v3_plan_mismatches": 0,
        }
        gates = evaluate_gates(
            agg, preview_stats, plan_stats, tests_passed=True
        )
        self.assertFalse(gates["no_suspicious_side_collapse"])


# ---------------------------------------------------------------------------
# Artifact validation
# ---------------------------------------------------------------------------


class TestArtifactValidation(unittest.TestCase):

    def _write_artifacts(
        self,
        root: Path,
        *,
        battle_tags: Sequence[str],
        outcomes: Optional[Sequence[str]] = None,
        player_policies: Optional[Sequence[str]] = None,
        opponent_policies: Optional[Sequence[str]] = None,
        observed_leads: Optional[Sequence[str]] = None,
        team_ids: Optional[Sequence[str]] = None,
        opponent_team_ids: Optional[Sequence[str]] = None,
        pair_ids: Optional[Sequence[int]] = None,
        v3_plans: Optional[Sequence[Dict[str, str]]] = None,
        malformed_json: bool = False,
    ) -> Dict[str, Path]:
        csv_path = root / "benchmark.csv"
        jsonl_path = root / "benchmark.jsonl"
        preview_path = root / "preview.csv"
        outcomes = outcomes or ["win"] * len(battle_tags)
        # Default to V3-as-player for D1, random-as-player for D2.
        # (Override via player_policies/opponent_policies to simulate
        # wrong policies.)
        if player_policies is None:
            player_policies = [
                "matchup_top4_v3"
                if tag.startswith("D1_") else "random"
                for tag in battle_tags
            ]
        if opponent_policies is None:
            opponent_policies = [
                "random"
                if tag.startswith("D1_") else "matchup_top4_v3"
                for tag in battle_tags
            ]
        observed_leads = observed_leads or ["a|b"] * (len(battle_tags) * 2)
        team_ids = team_ids or [f"team_{i}" for i in range(len(battle_tags))]
        opponent_team_ids = opponent_team_ids or [
            f"opp_{i}" for i in range(len(battle_tags))
        ]
        pair_ids = pair_ids or list(range(len(battle_tags)))
        v3_plans = v3_plans or [
            {
                "chosen": "a|b|c|d",
                "lead": "a|b",
                "back": "c|d",
            }
        ]
        with csv_path.open("w", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "battle_tag", "pair_id", "team_id",
                    "opponent_team_id", "player_policy", "opponent_policy",
                    "our_win", "opponent_win", "tie", "battle_result",
                ],
            )
            writer.writeheader()
            for i, tag in enumerate(battle_tags):
                writer.writerow({
                    "battle_tag": tag,
                    "pair_id": (
                        str(pair_ids[i]) if i < len(pair_ids) else "0"
                    ),
                    "team_id": (
                        team_ids[i] if i < len(team_ids) else "team"
                    ),
                    "opponent_team_id": (
                        opponent_team_ids[i]
                        if i < len(opponent_team_ids) else "opp"
                    ),
                    "player_policy": player_policies[i],
                    "opponent_policy": opponent_policies[i],
                    "our_win": "True" if outcomes[i] == "win" else "False",
                    "opponent_win": (
                        "False" if outcomes[i] == "win" else "True"
                    ),
                    "tie": "False",
                    "battle_result": outcomes[i],
                })
        with jsonl_path.open("w") as handle:
            for i, tag in enumerate(battle_tags):
                if malformed_json and i == 0:
                    handle.write("{bad json")
                else:
                    handle.write(json.dumps({
                        "battle_tag": tag,
                        "pair_id": pair_ids[i] if i < len(pair_ids) else 0,
                        "team_id": team_ids[i] if i < len(team_ids) else "team",
                        "opponent_team_id": (
                            opponent_team_ids[i]
                            if i < len(opponent_team_ids) else "opp"
                        ),
                        "player_policy": player_policies[i],
                        "opponent_policy": opponent_policies[i],
                        "battle_result": outcomes[i],
                        "our_win": outcomes[i] == "win",
                        "opponent_win": outcomes[i] != "win",
                        "tie": False,
                    }) + "\n")
        with preview_path.open("w", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "battle_tag", "pair_id", "side",
                    "player_policy", "opponent_policy",
                    "planned_chosen_4", "planned_lead_2",
                    "planned_back_2", "emitted_teampreview",
                    "actual_selected_species", "actual_lead_on_turn1",
                    "observed_actual_lead_on_turn1",
                    "preview_matches_plan",
                ],
            )
            writer.writeheader()
            for i, tag in enumerate(battle_tags):
                # The benchmark CSV stores player_policy and
                # opponent_policy for the p1 (player) perspective. We
                # use those as the V3 plan owners for the preview
                # rows on side p1. The p2 row is the mirrored
                # perspective.
                p1_player = player_policies[i]
                p1_opponent = opponent_policies[i]
                p2_player = opponent_policies[i]  # mirrored
                p2_opponent = player_policies[i]
                # The V3 plan for this battle is determined by which
                # side has player_policy=matchup_top4_v3.
                v3_plan = v3_plans[i] if i < len(v3_plans) else v3_plans[0]
                # p1 row
                writer.writerow({
                    "battle_tag": tag,
                    "pair_id": (
                        str(pair_ids[i]) if i < len(pair_ids) else "0"
                    ),
                    "side": "p1",
                    "player_policy": p1_player,
                    "opponent_policy": p1_opponent,
                    "planned_chosen_4": v3_plan["chosen"],
                    "planned_lead_2": v3_plan["lead"],
                    "planned_back_2": v3_plan["back"],
                    "emitted_teampreview": "/team 1234",
                    "actual_selected_species": v3_plan["chosen"],
                    "actual_lead_on_turn1": v3_plan["lead"],
                    "observed_actual_lead_on_turn1": (
                        observed_leads[i * 2]
                        if i * 2 < len(observed_leads) else "a|b"
                    ),
                    "preview_matches_plan": "True",
                })
                # p2 row
                writer.writerow({
                    "battle_tag": tag,
                    "pair_id": (
                        str(pair_ids[i]) if i < len(pair_ids) else "0"
                    ),
                    "side": "p2",
                    "player_policy": p2_player,
                    "opponent_policy": p2_opponent,
                    "planned_chosen_4": v3_plan["chosen"],
                    "planned_lead_2": v3_plan["lead"],
                    "planned_back_2": v3_plan["back"],
                    "emitted_teampreview": "/team 1234",
                    "actual_selected_species": v3_plan["chosen"],
                    "actual_lead_on_turn1": v3_plan["lead"],
                    "observed_actual_lead_on_turn1": (
                        observed_leads[i * 2 + 1]
                        if i * 2 + 1 < len(observed_leads) else "a|b"
                    ),
                    "preview_matches_plan": "True",
                })
        return {
            "csv": csv_path,
            "jsonl": jsonl_path,
            "preview": preview_path,
        }

    def test_well_formed_artifacts_pass(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            battle_tags = [f"D1_{i:04d}_p1" for i in range(2)]
            battle_tags += [f"D2_{i:04d}_p2" for i in range(2)]
            paths = self._write_artifacts(
                root,
                battle_tags=battle_tags,
                team_ids=(
                    ["team_0", "team_1", "team_0", "team_1"]
                ),
                opponent_team_ids=(
                    ["opp_0", "opp_1", "opp_0", "opp_1"]
                ),
                pair_ids=[0, 1, 0, 1],
            )
            errors = validate_v2f_qualification_artifacts(
                paths["csv"], paths["jsonl"], paths["preview"],
                expected_pairs=2,
            )
        self.assertEqual(errors, [], msg=str(errors))

    def test_wrong_csv_row_count_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            battle_tags = [f"D1_{i:04d}_p1" for i in range(2)]
            battle_tags += [f"D2_{i:04d}_p2" for i in range(2)]
            paths = self._write_artifacts(
                root,
                battle_tags=battle_tags,
                pair_ids=[0, 0, 0, 0],
            )
            errors = validate_v2f_qualification_artifacts(
                paths["csv"], paths["jsonl"], paths["preview"],
                expected_pairs=10,  # wrong expected
            )
        self.assertTrue(
            any("CSV rows=" in error for error in errors)
        )

    def test_duplicate_tags_fail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            battle_tags = [f"D1_0000_p1", f"D1_0000_p1"]
            battle_tags += [f"D2_{i:04d}_p2" for i in range(2)]
            paths = self._write_artifacts(
                root, battle_tags=battle_tags, pair_ids=[0, 0, 0, 0]
            )
            errors = validate_v2f_qualification_artifacts(
                paths["csv"], paths["jsonl"], paths["preview"],
                expected_pairs=2,
            )
        self.assertIn("duplicate battle tags", errors)

    def test_malformed_json_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            battle_tags = [f"D1_{i:04d}_p1" for i in range(2)]
            battle_tags += [f"D2_{i:04d}_p2" for i in range(2)]
            paths = self._write_artifacts(
                root,
                battle_tags=battle_tags,
                pair_ids=[0, 0, 0, 0],
                malformed_json=True,
            )
            errors = validate_v2f_qualification_artifacts(
                paths["csv"], paths["jsonl"], paths["preview"],
                expected_pairs=2,
            )
        self.assertTrue(
            any("malformed JSONL" in error for error in errors)
        )

    def test_timeout_outcome_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            battle_tags = [f"D1_{i:04d}_p1" for i in range(2)]
            battle_tags += [f"D2_{i:04d}_p2" for i in range(2)]
            paths = self._write_artifacts(
                root,
                battle_tags=battle_tags,
                outcomes=["timeout", "win", "win", "win"],
                pair_ids=[0, 0, 0, 0],
            )
            errors = validate_v2f_qualification_artifacts(
                paths["csv"], paths["jsonl"], paths["preview"],
                expected_pairs=2,
            )
        self.assertTrue(
            any("disallowed outcome 'timeout'" in error for error in errors)
        )

    def test_wrong_policy_assignment_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            battle_tags = [f"D1_{i:04d}_p1" for i in range(2)]
            battle_tags += [f"D2_{i:04d}_p2" for i in range(2)]
            paths = self._write_artifacts(
                root,
                battle_tags=battle_tags,
                player_policies=[
                    "matchup_top4_v3", "matchup_top4_v3",
                    "matchup_top4_v3", "matchup_top4_v3",
                ],
                opponent_policies=[
                    "random", "random", "random", "random",
                ],
                pair_ids=[0, 0, 0, 0],
            )
            errors = validate_v2f_qualification_artifacts(
                paths["csv"], paths["jsonl"], paths["preview"],
                expected_pairs=2,
            )
        self.assertTrue(
            any("wrong policies" in error for error in errors)
        )

    def test_team_identity_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            battle_tags = [f"D1_{i:04d}_p1" for i in range(2)]
            battle_tags += [f"D2_{i:04d}_p2" for i in range(2)]
            paths = self._write_artifacts(
                root,
                battle_tags=battle_tags,
                team_ids=["team_0", "team_0", "team_1", "team_1"],
                opponent_team_ids=["opp_0"] * 4,
                pair_ids=[0, 0, 0, 0],
            )
            errors = validate_v2f_qualification_artifacts(
                paths["csv"], paths["jsonl"], paths["preview"],
                expected_pairs=2,
            )
        self.assertTrue(
            any("team_id mismatch" in error for error in errors)
        )

    def test_missing_observed_lead_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            battle_tags = [f"D1_{i:04d}_p1" for i in range(2)]
            battle_tags += [f"D2_{i:04d}_p2" for i in range(2)]
            paths = self._write_artifacts(
                root,
                battle_tags=battle_tags,
                observed_leads=["a|b", "", "c|d", "e|f"],
                pair_ids=[0, 0, 0, 0],
            )
            errors = validate_v2f_qualification_artifacts(
                paths["csv"], paths["jsonl"], paths["preview"],
                expected_pairs=2,
            )
        self.assertTrue(
            any("missing observed lead" in error for error in errors)
        )

    def test_preview_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            battle_tags = [f"D1_{i:04d}_p1" for i in range(2)]
            battle_tags += [f"D2_{i:04d}_p2" for i in range(2)]
            paths = self._write_artifacts(root, battle_tags=battle_tags)
            # Overwrite the preview CSV to break preview_matches_plan.
            with paths["preview"].open("w", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "battle_tag", "pair_id", "player_policy",
                        "opponent_policy", "planned_chosen_4",
                        "planned_lead_2", "planned_back_2",
                        "emitted_teampreview", "actual_selected_species",
                        "actual_lead_on_turn1",
                        "observed_actual_lead_on_turn1",
                        "preview_matches_plan",
                    ],
                )
                writer.writeheader()
                for tag in [f"D1_{i:04d}_p1" for i in range(2)] + [
                    f"D2_{i:04d}_p2" for i in range(2)
                ]:
                    writer.writerow({
                        "battle_tag": f"{tag}_p1",
                        "pair_id": 0,
                        "player_policy": "matchup_top4_v3",
                        "opponent_policy": "random",
                        "planned_chosen_4": "a|b|c|d",
                        "planned_lead_2": "a|b",
                        "planned_back_2": "c|d",
                        "emitted_teampreview": "/team 1234",
                        "actual_selected_species": "a|b|c|d",
                        "actual_lead_on_turn1": "a|b",
                        "observed_actual_lead_on_turn1": "a|b",
                        "preview_matches_plan": "False",
                    })
            errors = validate_v2f_qualification_artifacts(
                paths["csv"], paths["jsonl"], paths["preview"],
                expected_pairs=2,
            )
        self.assertTrue(
            any("preview mismatch" in error for error in errors)
        )

    def test_v3_plan_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            battle_tags = [f"D1_{i:04d}_p1" for i in range(2)]
            battle_tags += [f"D2_{i:04d}_p2" for i in range(2)]
            v3_plans = [
                # Pair 0: D1 V3 picks a..d, D2 V3 picks w..z.
                # Pair 1: D1 V3 picks a..d, D2 V3 picks m..p.
                # Each preview row uses its own v3_plans[i] for the
                # V3 plan; the D1 and D2 sides for the same pair
                # must pick the same plan when inputs match.
                {"chosen": "a|b|c|d", "lead": "a|b", "back": "c|d"},
                {"chosen": "a|b|c|d", "lead": "a|b", "back": "c|d"},
                {"chosen": "w|x|y|z", "lead": "w|x", "back": "y|z"},
                {"chosen": "m|n|o|p", "lead": "m|n", "back": "o|p"},
            ]
            paths = self._write_artifacts(
                root,
                battle_tags=battle_tags,
                v3_plans=v3_plans,
                team_ids=["team_0", "team_1", "team_0", "team_1"],
                opponent_team_ids=["opp_0", "opp_1", "opp_0", "opp_1"],
                pair_ids=[0, 1, 0, 1],
            )
            errors = validate_v2f_qualification_artifacts(
                paths["csv"], paths["jsonl"], paths["preview"],
                expected_pairs=2,
            )
        self.assertTrue(
            any("V3 plan mismatch" in error for error in errors),
            msg=str(errors),
        )

    def test_csv_jsonl_disagreement_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            battle_tags = [f"D1_{i:04d}_p1" for i in range(2)]
            battle_tags += [f"D2_{i:04d}_p2" for i in range(2)]
            paths = self._write_artifacts(
                root,
                battle_tags=battle_tags,
                pair_ids=[0, 0, 0, 0],
            )
            # Write an extra JSONL record not present in the CSV.
            with paths["jsonl"].open("a") as handle:
                handle.write(
                    json.dumps({
                        "battle_tag": "D3_9999_p1",
                        "battle_result": "win",
                    }) + "\n"
                )
            errors = validate_v2f_qualification_artifacts(
                paths["csv"], paths["jsonl"], paths["preview"],
                expected_pairs=2,
            )
        self.assertTrue(
            any("CSV/JSONL disagreement" in error for error in errors)
        )

    def test_incomplete_pair_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            # Only one D1 row, no D2 row. This makes the pair
            # incomplete and must be flagged.
            battle_tags = [f"D1_0000_p1"]
            paths = self._write_artifacts(
                root, battle_tags=battle_tags, pair_ids=[0]
            )
            errors = validate_v2f_qualification_artifacts(
                paths["csv"], paths["jsonl"], paths["preview"],
                expected_pairs=1,
            )
        self.assertTrue(
            any("incomplete" in error for error in errors),
            msg=str(errors),
        )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle(unittest.TestCase):

    def test_natural_termination(self):
        result = subprocess.run(
            [
                sys.executable, "-c",
                "import poke_env_test_cleanup; "
                "import vgc2026_common_plan_evaluator; "
                "import team_preview_policy; "
                "import bot_vgc2026_phaseV2f_qualification; "
                "import analyze_vgc2026_phaseV2f_qualification; "
                "print('ok')",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
