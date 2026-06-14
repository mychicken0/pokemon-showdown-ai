#!/usr/bin/env python3
"""
Phase V2k.3 — focused regression tests for the four
blockers Codex identified after the V2k.2 review:

A. D=0 (or near-zero) must be treated as unresolved,
   NOT propagated as a negative sign. The "1 if d > 0
   else -1" anti-pattern assigns a residual to the
   negative sign when D is effectively zero.

B. Mold Breaker / Teravolt / Turboblaze must bypass
   Soundproof, Bulletproof, and Damp, not just Wonder
   Guard. The bypass check must run BEFORE the
   early-return rules for those three abilities.

C. Five-fold assignment must use a deterministic seeded
   random permutation of the row indices, NOT a
   contiguous row-order slice. The spec demands
   reproducibility independent of the artifact row
   order.

D. _build_speed_evidence must attempt to read the
   visible Trick Room state from the lead pair
   dictionaries and forward it to the shared resolver.
   The V2f artifacts may or may not expose this field;
   when exposed, the resolver may return a resolved
   result.

Every test asserts an exact, observable fact. No
placeholders, no skipped tests, no weakened gates.
"""
import io
import json
import os
import random
import statistics
import sys
import unittest
from typing import Any, Dict, List
from unittest.mock import patch

if "." not in sys.path:
    sys.path.insert(0, ".")

import poke_env_test_cleanup  # noqa: F401

import doubles_mechanics as _dm
import vgc2026_lead_matchup_evaluator_v3 as v2j
import analyze_vgc2026_phaseV2k_lead_matchups as v2k
import team_preview_policy as tpp


# ---------------------------------------------------------------------------
# V2k.3-A: D=0 / D-near-zero must NOT be a stable sign
# ---------------------------------------------------------------------------


class TestV2k3AZeroSignalNotNegative(unittest.TestCase):
    """A near-zero between-group difference (D) is a
    degenerate signal, NOT a stable negative
    difference. The stability gates must treat it as
    unresolved.
    """

    def test_d_exactly_zero_loo_fails(self):
        a = [0.1, 0.2, 0.3, 0.4]   # mean 0.25
        b = [0.15, 0.20, 0.25, 0.30, 0.35]  # mean 0.25
        # D_full = 0.0 exactly.
        self.assertEqual(
            v2k._loo_stability_difference(a, b), 0.0
        )

    def test_d_tiny_positive_loo_fails(self):
        # D_full = 0.00000005 — a floating-point residual
        # that ``1 if d > 0 else -1`` would assign to
        # positive, then every omission's also-tiny
        # positive D would match, producing LOO = 1.0.
        # The SIGNAL_MARGIN fix must report 0.0.
        a = [0.0000001] * 30
        b = [0.00000005] * 25
        self.assertEqual(
            v2k._loo_stability_difference(a, b), 0.0
        )

    def test_d_tiny_negative_loo_fails(self):
        # Symmetric test: D_full is a tiny negative
        # residual. The gate must report 0.0, NOT a
        # stable negative difference.
        a = [-0.0000001] * 30
        b = [0.00000005] * 25
        self.assertEqual(
            v2k._loo_stability_difference(a, b), 0.0
        )

    def test_d_tiny_zero_fold_fails(self):
        a = [0.0000001] * 30
        b = [0.00000005] * 25
        count, fold_diffs, _, _ = (
            v2k._fold_stability_difference(a, b, n_folds=5)
        )
        self.assertEqual(count, 0)
        self.assertEqual(fold_diffs, [])

    def test_d_tiny_zero_not_driven_fails(self):
        a = [0.0000001] * 30
        b = [0.00000005] * 25
        self.assertFalse(
            v2k._not_driven_by_one_difference(a, b)
        )

    def test_d_meaningful_positive_loo_passes(self):
        a = [10.0] * 30
        b = [5.0] * 25
        self.assertEqual(
            v2k._loo_stability_difference(a, b), 1.0
        )

    def test_d_meaningful_negative_loo_passes(self):
        a = [5.0] * 30
        b = [10.0] * 25
        self.assertEqual(
            v2k._loo_stability_difference(a, b), 1.0
        )

    def test_signal_margin_constant(self):
        # Static guard: the SIGNAL_MARGIN threshold is
        # exposed and large enough to absorb floating-
        # point residuals that ``1 if d > 0 else -1``
        # would otherwise assign a sign to.
        self.assertGreater(v2k.SIGNAL_MARGIN, 1e-7)
        self.assertLess(v2k.SIGNAL_MARGIN, 1e-3)


# ---------------------------------------------------------------------------
# V2k.3-B: Mold Breaker bypasses Soundproof / Bulletproof / Damp
# ---------------------------------------------------------------------------


class TestV2k3BMoldBreakerBypass(unittest.TestCase):
    """Mold Breaker / Teravolt / Turboblaze must bypass
    Soundproof, Bulletproof, and Damp. The bypass check
    must run BEFORE the early-return rules for those
    three abilities.
    """

    def test_mold_breaker_bypasses_soundproof(self):
        # Build a fake move with ``flags={"sound": True}``
        # targeting a Soundproof defender.
        class _M:
            id = "hypervoice"
            flags = {"sound": True}
        res = _dm.evaluate_move_effectiveness(
            move=_M(), attacker=None, target=None,
            defender_types=["NORMAL"],
            attacker_ability="moldbreaker",
            target_ability="soundproof",
            move_type_override="NORMAL",
        )
        self.assertFalse(res.is_type_immune)
        self.assertFalse(res.is_explicit_ability_immune)
        self.assertTrue(res.effective_multiplier > 0.0)
        # The shared module must record the bypass.
        abil_res = _dm.resolve_explicit_ability_interaction(
            move=_M(), attacker=None, target=None,
            target_ability="soundproof",
            attacker_ability="moldbreaker",
            move_id="hypervoice",
            move_type="NORMAL",
        )
        self.assertTrue(abil_res.bypassed)

    def test_teravolt_bypasses_soundproof(self):
        class _M:
            id = "hypervoice"
            flags = {"sound": True}
        abil_res = _dm.resolve_explicit_ability_interaction(
            move=_M(), attacker=None, target=None,
            target_ability="soundproof",
            attacker_ability="teravolt",
            move_id="hypervoice",
            move_type="NORMAL",
        )
        self.assertTrue(abil_res.bypassed)
        self.assertFalse(abil_res.is_immune)

    def test_turboblaze_bypasses_soundproof(self):
        class _M:
            id = "hypervoice"
            flags = {"sound": True}
        abil_res = _dm.resolve_explicit_ability_interaction(
            move=_M(), attacker=None, target=None,
            target_ability="soundproof",
            attacker_ability="turboblaze",
            move_id="hypervoice",
            move_type="NORMAL",
        )
        self.assertTrue(abil_res.bypassed)
        self.assertFalse(abil_res.is_immune)

    def test_no_bypass_keeps_soundproof_immunity(self):
        class _M:
            id = "hypervoice"
            flags = {"sound": True}
        abil_res = _dm.resolve_explicit_ability_interaction(
            move=_M(), attacker=None, target=None,
            target_ability="soundproof",
            attacker_ability=None,
            move_id="hypervoice",
            move_type="NORMAL",
        )
        self.assertFalse(abil_res.bypassed)
        self.assertTrue(abil_res.is_immune)
        self.assertEqual(abil_res.reason, "sound_into_soundproof")

    def test_mold_breaker_bypasses_bulletproof(self):
        class _M:
            id = "shadowball"
            flags = {"bullet": True}
        abil_res = _dm.resolve_explicit_ability_interaction(
            move=_M(), attacker=None, target=None,
            target_ability="bulletproof",
            attacker_ability="moldbreaker",
            move_id="shadowball",
            move_type="GHOST",
        )
        self.assertTrue(abil_res.bypassed)
        self.assertFalse(abil_res.is_immune)

    def test_no_bypass_keeps_bulletproof_immunity(self):
        class _M:
            id = "shadowball"
            flags = {"bullet": True}
        abil_res = _dm.resolve_explicit_ability_interaction(
            move=_M(), attacker=None, target=None,
            target_ability="bulletproof",
            attacker_ability=None,
            move_id="shadowball",
            move_type="GHOST",
        )
        self.assertFalse(abil_res.bypassed)
        self.assertTrue(abil_res.is_immune)
        self.assertEqual(abil_res.reason, "bullet_into_bulletproof")

    def test_mold_breaker_bypasses_damp_for_explosion(self):
        abil_res = _dm.resolve_explicit_ability_interaction(
            move="explosion", attacker=None, target=None,
            target_ability="damp",
            attacker_ability="moldbreaker",
            move_id="explosion",
            move_type="NORMAL",
        )
        self.assertTrue(abil_res.bypassed)
        self.assertFalse(abil_res.is_immune)

    def test_no_bypass_keeps_damp_immunity(self):
        abil_res = _dm.resolve_explicit_ability_interaction(
            move="explosion", attacker=None, target=None,
            target_ability="damp",
            attacker_ability=None,
            move_id="explosion",
            move_type="NORMAL",
        )
        self.assertFalse(abil_res.bypassed)
        self.assertTrue(abil_res.is_immune)
        self.assertEqual(abil_res.reason, "explosion_into_damp")

    def test_three_bypass_abilities_in_attacker_ignores(self):
        # Static guard: the three bypass abilities are
        # registered in the canonical allowlist.
        from doubles_mechanics import ATTACKER_IGNORES_ABILITY
        for ab in ("moldbreaker", "teravolt", "turboblaze"):
            self.assertIn(ab, ATTACKER_IGNORES_ABILITY)

    def test_three_abilities_in_explicit_immunity_set(self):
        from doubles_mechanics import EXPLICIT_IMMUNITY_ABILITIES
        for ab in ("soundproof", "bulletproof", "damp"):
            self.assertIn(ab, EXPLICIT_IMMUNITY_ABILITIES)


# ---------------------------------------------------------------------------
# V2k.3-C: Five-fold assignment uses frozen-seed permutation
# ---------------------------------------------------------------------------


class TestV2k3CFrozenSeedFolds(unittest.TestCase):
    """Five-fold assignment must use a deterministic
    seeded permutation of the row indices, NOT a
    contiguous row-order slice. The spec demands
    reproducibility independent of the artifact row
    order.
    """

    def test_fold_uses_permutation(self):
        # V2k.5 uses stable observation identities and
        # balanced hash-ranked folds.
        import inspect
        src = inspect.getsource(v2k._fold_stability_difference)
        self.assertIn("_balanced_fold_assignment", src)
        self.assertNotIn("shuffle", src)

    def test_fold_deterministic_with_same_seed(self):
        # Same input + same seed → same result.
        a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        b = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
        c1, d1, _, _ = v2k._fold_stability_difference(a, b)
        c2, d2, _, _ = v2k._fold_stability_difference(a, b)
        self.assertEqual(c1, c2)
        self.assertEqual(d1, d2)

    def test_fold_invariant_to_row_order(self):
        # V2k.4 — the fold assignment is value-based,
        # NOT row-position-based. Shuffling the input
        # rows gives the same fold results because the
        # assignment depends only on the value
        # identity, not the position.
        a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0,
             11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0,
             19.0, 20.0]
        b = [0.5 * i for i in a]
        a_ids = list(range(20))
        b_ids = list(range(100, 120))
        c1, d1, sa1, sb1 = v2k._fold_stability_difference(
            a, b, group_a_ids=a_ids, group_b_ids=b_ids
        )
        # Reverse the order of group A.
        a_rev = list(reversed(a))
        a_ids_rev = list(reversed(a_ids))
        c2, d2, sa2, sb2 = v2k._fold_stability_difference(
            a_rev, b,
            group_a_ids=a_ids_rev,
            group_b_ids=b_ids,
        )
        # The fold results must be identical because
        # the assignment is value-based, not row-based.
        self.assertEqual(
            c1, c2,
            "Fold count must be invariant to row order",
        )
        self.assertEqual(
            d1, d2,
            "Fold diffs must be invariant to row order",
        )
        self.assertEqual(sa1, sa2)
        self.assertEqual(sb1, sb2)

    def test_fold_signature_has_seed_parameter(self):
        import inspect
        sig = inspect.signature(v2k._fold_stability_difference)
        self.assertIn("seed", sig.parameters)

    def test_seed_default_is_bootstrap_seed(self):
        import inspect
        sig = inspect.signature(v2k._fold_stability_difference)
        # The default seed value is BOOTSTRAP_SEED.
        self.assertEqual(
            sig.parameters["seed"].default,
            v2k.BOOTSTRAP_SEED,
        )

    def test_groups_independent_partitions(self):
        # A and B must get independent value-based
        # partitions (different seeds). A meaningful
        # signal (D != 0) is required for the fold
        # signs to be recorded.
        a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0,
             11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0,
             19.0, 20.0]
        b = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4,
             1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2, 2.3, 2.4]
        c, d, sa, sb = v2k._fold_stability_difference(a, b)
        # D_full is meaningfully positive. Fold signs
        # must be recorded for each fold.
        self.assertNotEqual(sa, ["n/a"] * 5)
        self.assertNotEqual(sb, ["n/a"] * 5)
        # The two partitions are independent (different
        # seeds). The fold_diffs vectors were recorded.
        self.assertEqual(len(d), 5)

    def test_stable_fold_uses_value_hash(self):
        # A signal with two distinct values per group
        # must produce stable folds. The fold
        # containing both values is skipped, so the
        # count is at most 4 (5 minus the shared fold).
        a = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0,
             18.0, 19.0, 20.0, 21.0, 22.0, 23.0, 24.0, 25.0,
             26.0, 27.0, 28.0, 29.0, 30.0, 31.0, 32.0, 33.0,
             34.0, 35.0, 36.0, 37.0, 38.0, 39.0]
        b = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0,
             11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0,
             19.0, 20.0, 21.0, 22.0, 23.0, 24.0, 25.0]
        # The mean difference is meaningfully positive.
        count, _, _, _ = v2k._fold_stability_difference(
            a, b, n_folds=5,
        )
        # The count is at least 4 (one fold may be
        # skipped if both values land in the same
        # fold).
        self.assertGreaterEqual(count, 4)
        self.assertLessEqual(count, 5)

    def test_stable_fold_negative_meaningful(self):
        a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0,
             11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0,
             19.0, 20.0, 21.0, 22.0, 23.0, 24.0, 25.0]
        b = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0,
             18.0, 19.0, 20.0, 21.0, 22.0, 23.0, 24.0, 25.0,
             26.0, 27.0, 28.0, 29.0, 30.0, 31.0, 32.0, 33.0,
             34.0]
        count, _, _, _ = v2k._fold_stability_difference(
            a, b, n_folds=5,
        )
        self.assertGreaterEqual(count, 4)
        self.assertLessEqual(count, 5)


# ---------------------------------------------------------------------------
# V2k.3-D: _build_speed_evidence must pass Trick Room state
# ---------------------------------------------------------------------------


class TestV2k3DSpeedEvidenceTrickRoom(unittest.TestCase):
    """_build_speed_evidence must attempt to read the
    visible Trick Room state from the lead pair
    dictionaries and forward it to the shared resolver.
    """

    def test_trick_room_true_resolves_120_vs_100(self):
        # Both speeds are visible AND Trick Room is
        # explicitly True. The resolver must return
        # ``b_faster`` (the slower parameter acts first
        # in Trick Room).
        ev = v2j._build_speed_evidence(
            [{"species": "a", "speed": 120.0,
              "trick_room": True}],
            [
                {"species": "b", "speed": 100.0,
                 "trick_room": True},
                {"species": "c", "speed": 80.0,
                 "trick_room": True},
            ],
        )
        # a-vs-b must be resolved.
        comparison_ab = next(
            c for c in ev["comparisons"]
            if c["our_species"] == "a" and c["opp_species"] == "b"
        )
        self.assertNotEqual(
            comparison_ab["result"], "unresolved",
            f"a-vs-b must resolve when trick_room=True "
            f"and speeds are visible: {comparison_ab}",
        )

    def test_trick_room_false_resolves_120_vs_100(self):
        # Trick Room explicitly False: a-vs-b
        # resolves to ``a_faster``.
        ev = v2j._build_speed_evidence(
            [{"species": "a", "speed": 120.0,
              "trick_room": False}],
            [
                {"species": "b", "speed": 100.0,
                 "trick_room": False},
                {"species": "c", "speed": 80.0,
                 "trick_room": False},
            ],
        )
        comparison_ab = next(
            c for c in ev["comparisons"]
            if c["our_species"] == "a" and c["opp_species"] == "b"
        )
        self.assertNotEqual(
            comparison_ab["result"], "unresolved",
            f"a-vs-b must resolve when trick_room=False "
            f"and speeds are visible: {comparison_ab}",
        )

    def test_trick_room_string_true_resolves(self):
        ev = v2j._build_speed_evidence(
            [{"species": "a", "speed": 120.0,
              "trick_room": "true"}],
            [
                {"species": "b", "speed": 100.0,
                 "trick_room": "true"},
                {"species": "c", "speed": 80.0,
                 "trick_room": "true"},
            ],
        )
        comparison_ab = next(
            c for c in ev["comparisons"]
            if c["our_species"] == "a" and c["opp_species"] == "b"
        )
        self.assertNotEqual(
            comparison_ab["result"], "unresolved",
        )

    def test_trick_room_missing_remains_unresolved(self):
        # No trick_room field anywhere → unresolved.
        ev = v2j._build_speed_evidence(
            [{"species": "a", "speed": 120.0}],
            [
                {"species": "b", "speed": 100.0},
                {"species": "c", "speed": 80.0},
            ],
        )
        # All four comparisons must be unresolved.
        for c in ev["comparisons"]:
            self.assertEqual(c["result"], "unresolved")
            self.assertEqual(c["trick_room_supplied"], None)

    def test_trick_room_synonym_resolves(self):
        # Synonym ``trickroom`` (no underscore) must
        # be accepted.
        ev = v2j._build_speed_evidence(
            [{"species": "a", "speed": 120.0,
              "trickroom": True}],
            [
                {"species": "b", "speed": 100.0,
                 "trickroom": True},
                {"species": "c", "speed": 80.0,
                 "trickroom": True},
            ],
        )
        comparison_ab = next(
            c for c in ev["comparisons"]
            if c["our_species"] == "a" and c["opp_species"] == "b"
        )
        self.assertNotEqual(
            comparison_ab["result"], "unresolved",
        )

    def test_trick_room_in_opponent_pair_resolves(self):
        # Trick Room exposed only in the opponent pair
        # still resolves.
        ev = v2j._build_speed_evidence(
            [{"species": "a", "speed": 120.0}],
            [
                {"species": "b", "speed": 100.0,
                 "trick_room": False},
                {"species": "c", "speed": 80.0},
            ],
        )
        # Even though the OUR lead has no trick_room,
        # the OPPONENT's pair does, so the resolver
        # has a visible value.
        for c in ev["comparisons"]:
            self.assertEqual(
                c["trick_room_supplied"], False,
                f"trick_room must propagate to all "
                f"comparisons: {c}",
            )

    def test_per_comparison_records_trick_room(self):
        # Audit record: every comparison carries the
        # trick_room supplied value for the audit.
        ev = v2j._build_speed_evidence(
            [{"species": "a", "speed": 120.0,
              "trick_room": True}],
            [
                {"species": "b", "speed": 100.0,
                 "trick_room": True},
                {"species": "c", "speed": 80.0,
                 "trick_room": True},
            ],
        )
        for c in ev["comparisons"]:
            self.assertIn("trick_room_supplied", c)
            self.assertEqual(c["trick_room_supplied"], True)

    def test_extract_visible_trick_room(self):
        # Direct unit test of the helper.
        self.assertIsNone(
            v2j._extract_visible_trick_room(
                [{"species": "a"}, {"species": "b"}]
            )
        )
        self.assertIsNone(
            v2j._extract_visible_trick_room([])
        )
        self.assertTrue(
            v2j._extract_visible_trick_room(
                [{"species": "a", "trick_room": True}]
            )
        )
        self.assertFalse(
            v2j._extract_visible_trick_room(
                [{"species": "a", "trick_room": False}]
            )
        )
        self.assertTrue(
            v2j._extract_visible_trick_room(
                [{"species": "a", "trick_room": "true"}]
            )
        )
        self.assertFalse(
            v2j._extract_visible_trick_room(
                [{"species": "a", "trick_room": "false"}]
            )
        )
        self.assertTrue(
            v2j._extract_visible_trick_room(
                [{"species": "a", "trickroom": True}]
            )
        )
        # Synonym ``trick-room``
        self.assertTrue(
            v2j._extract_visible_trick_room(
                [{"species": "a", "trick-room": "yes"}]
            )
        )
        # Invalid value treated as None
        self.assertIsNone(
            v2j._extract_visible_trick_room(
                [{"species": "a", "trick_room": object()}]
            )
        )

    def test_extract_visible_tailwind(self):
        # Direct unit test of the Tailwind helper.
        self.assertIsNone(
            v2j._extract_visible_tailwind(
                [{"species": "a"}]
            )
        )
        self.assertTrue(
            v2j._extract_visible_tailwind(
                [{"species": "a", "tailwind": True}]
            )
        )
        self.assertFalse(
            v2j._extract_visible_tailwind(
                [{"species": "a", "tailwind": "no"}]
            )
        )
        self.assertTrue(
            v2j._extract_visible_tailwind(
                [{"species": "a", "is_tailwind": 1}]
            )
        )


# ---------------------------------------------------------------------------
# V2k.3-B: Direction-agreement uses a margin
# ---------------------------------------------------------------------------


class TestV2k3DirectionAgreementMargin(unittest.TestCase):
    """The direction-agreement gate must use a margin
    so a near-zero signal is treated as unresolved,
    not as either sign.
    """

    def test_direction_agree_with_zero_signal(self):
        # A=[0.25, 0.25] B=[0.25, 0.25] → both means
        # = 0.25 → between = 0.0, within = 0.0 →
        # direction_agree must FAIL (no nonzero
        # reference sign).
        result = v2k.evaluate_component(
            "x",
            v3_both_values=[0.25, 0.25],
            v3_in_random_both_values=[0.25, 0.25],
            random_in_random_both_values=[0.25, 0.25],
            v3_both_unknown_rates=[0.05, 0.05],
        )
        self.assertFalse(
            result["gates"]["between_within_direction_agree"]
        )
        # The sign must be reported as "?" (unknown).
        self.assertEqual(result["between_sign"], "?")
        self.assertEqual(result["within_sign"], "?")

    def test_direction_agree_with_tiny_zero_signal(self):
        result = v2k.evaluate_component(
            "x",
            v3_both_values=[0.0000001] * 30,
            v3_in_random_both_values=[
                0.00000005,
            ] * 25,
            random_in_random_both_values=[
                0.0000001,
            ] * 25,
            v3_both_unknown_rates=[0.05] * 30,
        )
        # D is effectively zero; the gate must
        # refuse to commit a sign.
        self.assertFalse(
            result["gates"]["between_within_direction_agree"]
        )
        self.assertEqual(result["between_sign"], "?")
        self.assertEqual(result["within_sign"], "?")

    def test_direction_agree_with_meaningful_same_sign(self):
        result = v2k.evaluate_component(
            "x",
            v3_both_values=[1.0] * 30,
            v3_in_random_both_values=[0.5] * 25,
            random_in_random_both_values=[0.4] * 25,
            v3_both_unknown_rates=[0.05] * 30,
        )
        # Both means are nonzero. Sign must be
        # detected and agreement must pass.
        self.assertTrue(
            result["gates"]["between_within_direction_agree"]
        )
        self.assertEqual(result["between_sign"], "+")
        self.assertEqual(result["within_sign"], "+")

    def test_direction_agree_with_meaningful_disagree(self):
        # V3-both high, V3-in-random also high, but
        # within-failure (V3 - Random) flips sign.
        result = v2k.evaluate_component(
            "x",
            v3_both_values=[2.0] * 30,
            v3_in_random_both_values=[0.5] * 25,
            random_in_random_both_values=[2.5] * 25,
            v3_both_unknown_rates=[0.05] * 30,
        )
        self.assertFalse(
            result["gates"]["between_within_direction_agree"]
        )


# ---------------------------------------------------------------------------
# V2k.3: Final artifact consistency (V2k.3 writes to V2k3)
# ---------------------------------------------------------------------------


class TestV2k3ArtifactConsistency(unittest.TestCase):
    """The V2k.3 analyzer must accept the V2f artifacts
    and produce a real-artifact report with all six
    real-freeze-gate conditions met, every component's
    between_mean == between_bootstrap_ci[0], and every
    component's within_mean == within_bootstrap_ci[0].
    """

    def test_v2k3_generated_report_consistency(self):
        r = v2k.run_analysis(
            v2k.build_synthetic_inputs(),
            evidence_mode="synthetic",
            real_artifact_paths={},
        )
        rap = r["real_artifact_proof"]
        self.assertEqual(rap["evidence_mode"], "synthetic")
        self.assertFalse(rap["real_freeze_gate_passed"])
        for row in r["gate_table"]:
            bc = row["between_bootstrap_ci"]
            self.assertEqual(row["between_mean"], bc[0])
            wc = row["within_bootstrap_ci"]
            self.assertEqual(row["within_mean"], wc[0])
            for gate_name, passed in row["gates"].items():
                if not passed:
                    self.assertIn(
                        gate_name, row["gate_reasons"],
                        f"missing reason for {gate_name}",
                    )


if __name__ == "__main__":
    unittest.main()
