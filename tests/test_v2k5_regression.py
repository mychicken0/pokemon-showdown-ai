#!/usr/bin/env python3
"""Regression coverage for the Phase V2k.5 corrections."""

import inspect
import json
import os
import unittest

import poke_env_test_cleanup  # noqa: F401

import analyze_vgc2026_phaseV2k_lead_matchups as analyzer
import doubles_mechanics as mechanics


class TestRealMoveMetadata(unittest.TestCase):
    def test_thunder_wave_good_as_gold_blocks(self):
        result = mechanics.resolve_explicit_ability_interaction(
            "thunderwave", None, None, "goodasgold",
            move_type="ELECTRIC",
        )
        self.assertTrue(result.is_immune)
        self.assertFalse(result.bypassed)
        self.assertEqual(result.reason, "goodasgold_status_block")

    def test_thunder_wave_good_as_gold_mold_breaker_bypasses(self):
        result = mechanics.resolve_explicit_ability_interaction(
            "thunderwave", None, None, "goodasgold",
            attacker_ability="moldbreaker",
            move_type="ELECTRIC",
        )
        self.assertFalse(result.is_immune)
        self.assertTrue(result.bypassed)

    def test_thunder_wave_magic_bounce_uses_reflectable_flag(self):
        result = mechanics.resolve_explicit_ability_interaction(
            "thunderwave", None, None, "magicbounce",
            move_type="ELECTRIC",
        )
        self.assertTrue(result.is_immune)
        self.assertEqual(result.reason, "magicbounce_status_block")

    def test_spore_overcoat_uses_powder_flag(self):
        result = mechanics.resolve_explicit_ability_interaction(
            "spore", None, None, "overcoat",
            move_type="GRASS",
        )
        self.assertTrue(result.is_immune)
        self.assertEqual(result.reason, "overcoat_powder_block")

    def test_non_powder_grass_move_not_blocked_by_overcoat(self):
        result = mechanics.resolve_explicit_ability_interaction(
            "energyball", None, None, "overcoat",
            move_type="GRASS",
        )
        self.assertFalse(result.is_immune)
        self.assertFalse(result.bypassed)


class TestWonderGuard(unittest.TestCase):
    def test_direct_resolver_does_not_raise(self):
        result = mechanics.resolve_explicit_ability_interaction(
            "waterpulse", None, None, "wonderguard",
            move_type="WATER",
            defender_types=["BUG", "GHOST"],
        )
        self.assertTrue(result.is_immune)
        self.assertEqual(
            result.reason, "non_super_effective_into_wonderguard"
        )

    def test_neutral_damaging_move_is_blocked(self):
        result = mechanics.evaluate_move_effectiveness(
            "waterpulse", None, None, ["BUG", "GHOST"],
            target_ability="wonderguard",
        )
        self.assertTrue(result.is_explicit_ability_immune)
        self.assertEqual(result.effective_multiplier, 0.0)

    def test_super_effective_damaging_move_is_allowed(self):
        result = mechanics.evaluate_move_effectiveness(
            "firepunch", None, None, ["BUG", "GHOST"],
            target_ability="wonderguard",
        )
        self.assertFalse(result.is_explicit_ability_immune)
        self.assertEqual(result.effective_multiplier, 2.0)

    def test_status_move_is_not_blocked_by_wonder_guard(self):
        result = mechanics.evaluate_move_effectiveness(
            "thunderwave", None, None, ["BUG", "GHOST"],
            target_ability="wonderguard",
        )
        self.assertFalse(result.is_explicit_ability_immune)

    def test_mold_breaker_bypasses_neutral_move_block(self):
        result = mechanics.evaluate_move_effectiveness(
            "waterpulse", None, None, ["BUG", "GHOST"],
            target_ability="wonderguard",
            attacker_ability="moldbreaker",
        )
        self.assertFalse(result.is_explicit_ability_immune)
        self.assertEqual(result.effective_multiplier, 1.0)
        self.assertIn("bypassed_by_wonderguard", result.explicit_ability_reason)


class TestStablePairIdFolds(unittest.TestCase):
    def test_constant_groups_produce_all_five_folds(self):
        count, diffs, _, _ = analyzer._fold_stability_difference(
            [10.0] * 30,
            [1.0] * 25,
            group_a_ids=list(range(30)),
            group_b_ids=list(range(100, 125)),
        )
        self.assertEqual(count, 5)
        self.assertEqual(len(diffs), 5)
        self.assertEqual(diffs, [9.0] * 5)

    def test_row_reorder_with_ids_is_invariant(self):
        values = [float(index) for index in range(1, 21)]
        ids = [f"pair-{index}" for index in range(20)]
        b_values = [value / 2.0 for value in values]
        b_ids = [f"other-{index}" for index in range(20)]
        first = analyzer._fold_stability_difference(
            values, b_values,
            group_a_ids=ids,
            group_b_ids=b_ids,
        )
        second = analyzer._fold_stability_difference(
            list(reversed(values)), b_values,
            group_a_ids=list(reversed(ids)),
            group_b_ids=b_ids,
        )
        self.assertEqual(first, second)

    def test_duplicate_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            analyzer._fold_stability_difference(
                [10.0] * 5,
                [1.0] * 5,
                group_a_ids=["same"] * 5,
                group_b_ids=list(range(5)),
            )

    def test_fallback_for_equal_values_is_balanced(self):
        count, diffs, _, _ = analyzer._fold_stability_difference(
            [10.0] * 30,
            [1.0] * 25,
        )
        self.assertEqual(count, 5)
        self.assertEqual(len(diffs), 5)

    def test_production_safe_run_collects_pair_ids(self):
        source = inspect.getsource(analyzer._safe_run)
        self.assertIn("v3_both_pair_ids.append(pair_id)", source)
        self.assertIn("random_both_pair_ids.append(pair_id)", source)


class TestV2k5Artifact(unittest.TestCase):
    def test_generated_artifact_structure(self):
        report = analyzer.run_analysis(
            analyzer.build_synthetic_inputs(),
            evidence_mode="synthetic",
            real_artifact_paths={},
        )
        proof = report["real_artifact_proof"]
        self.assertEqual(proof["evidence_mode"], "synthetic")
        self.assertFalse(proof["real_freeze_gate_passed"])
        self.assertTrue(proof["real_freeze_gate_reasons"])
        for row in report["gate_table"]:
            if abs(row["between_mean"]) <= analyzer.SIGNAL_MARGIN:
                self.assertEqual(row["fold_diffs"], [])
            else:
                self.assertEqual(len(row["fold_diffs"]), 5)


if __name__ == "__main__":
    unittest.main()
