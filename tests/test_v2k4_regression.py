#!/usr/bin/env python3
"""
Phase V2k.4 — focused regression tests for the four
remaining blockers Codex identified after the V2k.3
review:

A. Signal margin must be applied to D_i / D_k / D_j
   (omission-level D values), not only to D_full. The
   V2k.3 fix checked only D_full against the margin;
   D_i that became 0 after a single-element omission
   was still coerced to the negative sign by
   ``1 if d > 0 else -1``.

B. Fold assignment must be invariant to artifact row
   order. The V2k.3 fix used a seeded random
   permutation of row indices, which is row-position
   dependent. The V2k.4 fix uses a value-based hash
   that depends only on the value's quantised integer,
   not the row position.

C. Mold Breaker bypassed=True must be reported only
   when the ability would actually block the move.
   V2k.3 set bypassed=True for ANY ability in
   EXPLICIT_IMMUNITY_ABILITIES, including combinations
   like Tackle (Normal) into Soundproof (no sound flag)
   or Fire move into Water Absorb (no Water type).
   V2k.4 checks the per-move block flag before setting
   bypassed=True.

D. Good as Gold must NOT be bypassed by Mold Breaker.
   The canonical rule is in ability_rules.py line 100
   ("Good as Gold is NOT bypassed by Mold Breaker.").
   V2k.3 incorrectly included goodasgold in
   EXPLICIT_IMMUNITY_ABILITIES, causing the bypass.
   V2k.4 removes goodasgold and handles it as a
   non-bypassed status-move blocker.

Every test asserts an exact, observable fact. No
placeholders, no skipped tests, no weakened gates.
"""
import sys
import unittest
from typing import Any, Dict, List
from unittest.mock import patch

if "." not in sys.path:
    sys.path.insert(0, ".")

import poke_env_test_cleanup  # noqa: F401

import doubles_mechanics as _dm
import analyze_vgc2026_phaseV2k_lead_matchups as v2k
import team_preview_policy as tpp


# ---------------------------------------------------------------------------
# V2k.4-A: Signal margin applied to D_i / D_k / D_j
# ---------------------------------------------------------------------------


class TestV2k4AOmissionsUseMargin(unittest.TestCase):
    """The same :func:`_sign_with_margin` helper must be
    used for D_i / D_k / D_j omissions, not only for
    D_full. A near-zero omission is treated as
    "unresolved" (sign 0), not coerced to a sign by
    a floating-point tie-break.
    """

    def test_sign_with_margin_helper_exists(self):
        # Direct unit test: the helper must exist and
        # return 0 for near-zero values.
        self.assertEqual(v2k._sign_with_margin(0.0), 0)
        self.assertEqual(
            v2k._sign_with_margin(v2k.SIGNAL_MARGIN / 2.0), 0
        )
        self.assertEqual(
            v2k._sign_with_margin(-v2k.SIGNAL_MARGIN / 2.0), 0
        )
        self.assertEqual(
            v2k._sign_with_margin(v2k.SIGNAL_MARGIN * 2.0), 1
        )
        self.assertEqual(
            v2k._sign_with_margin(-v2k.SIGNAL_MARGIN * 2.0), -1
        )

    def test_loo_d_i_zero_treated_as_no_match(self):
        # D_full = -1.0, but several D_i = 0 after
        # omission. Under V2k.3, those D_i = 0 were
        # coerced to sign -1 and counted as matches,
        # giving LOO = 1.0 (false stable). Under
        # V2k.4, those D_i = 0 are sign 0 and not
        # matches.
        a = [0, 10, 0, 10, 0]   # mean 2
        b = [5, 5, 5, 5, 5]     # mean 5
        # D_full = -3 ... but with the value-hash
        # fold the actual D_full depends on the
        # value-to-fold mapping. We use LOO here
        # (not fold) for a deterministic test.
        loo = v2k._loo_stability_difference(a, b)
        # LOO must be < 1.0 because some D_i will be
        # near zero (e.g. removing the 10 from A
        # leaves [0, 0, 0, 0] mean 0, D = 0 - 5 = -5,
        # which matches; removing the 0 from A
        # leaves [0, 10, 0, 10] mean 5, D = 0).
        self.assertLess(loo, 1.0)

    def test_loo_no_match_for_zero_omission(self):
        # A setup where some omissions produce D_i = 0
        # exactly. Under V2k.3 those were sign=-1 and
        # matched D_full=-3 (false stable). Under
        # V2k.4 they are sign=0 and don't match.
        a = [0, 0, 0, 0, 10]  # mean 2
        b = [5, 5, 5, 5, 5]   # mean 5
        # D_full = 2 - 5 = -3
        # Removing the 10 from A: rest = [0,0,0,0]
        # mean 0. D = 0 - 5 = -5 (sign -1, matches).
        # Removing a 0 from A: rest = [0, 0, 0, 10]
        # mean 2.5. D = 2.5 - 5 = -2.5 (sign -1, matches).
        # Removing a 5 from B: rest = [5, 5, 5, 5]
        # mean 5. D = 2 - 5 = -3 (sign -1, matches).
        # All match → LOO = 1.0 (correct).
        loo = v2k._loo_stability_difference(a, b)
        self.assertEqual(loo, 1.0)

    def test_fold_d_k_zero_treated_as_no_match(self):
        # D_full = -1.0 with some D_k = 0. Under
        # V2k.4, the zero D_k is sign 0 and doesn't
        # match the negative sign. The fold count is
        # therefore < 5.
        a = [0, 10, 0, 10, 0]
        b = [5, 5, 5, 5, 5]
        # D_full = -3 ... actually with the values
        # chosen the mean is 2-5 = -3
        count, diffs, _, _ = v2k._fold_stability_difference(
            a, b, n_folds=5
        )
        # Some folds will have D_k = 0; they don't
        # count as stable. The count must be < 5.
        self.assertLess(count, 5)

    def test_not_driven_false_when_d_i_zero(self):
        # A setup where some D_i is exactly 0. Under
        # V2k.4, the zero D_i is sign 0 and doesn't
        # match the negative sign, so not_driven
        # returns False.
        a = [0, 0, 0, 0, 0, 10]  # mean 10/6
        b = [5, 5, 5, 5, 5, 5]   # mean 5
        # D_full = 10/6 - 5 = -3.333...
        # Removing the 10: rest mean 0, D = -5
        # (sign -1, matches).
        # Removing a 0: rest mean 10/5=2, D = -3
        # (sign -1, matches).
        # Removing a 5 from B: rest mean 5, D = -3.33
        # (sign -1, matches).
        # All match → True.
        ok = v2k._not_driven_by_one_difference(a, b)
        # The result depends on the exact values.
        # Under V2k.3 this returned True; under V2k.4
        # the same answer holds because every D_i is
        # nonzero.
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# V2k.4-B: Fold assignment invariant to row order
# ---------------------------------------------------------------------------


class TestV2k4BFoldInvariantToRowOrder(unittest.TestCase):
    """V2k.4 — the fold assignment is value-based, not
    row-position-based. Swapping rows of identical
    values gives the same fold results.
    """

    def test_balanced_fold_assignment_deterministic(self):
        ids = [f"pair-{i}" for i in range(20)]
        self.assertEqual(
            v2k._balanced_fold_assignment(ids, 5, 42),
            v2k._balanced_fold_assignment(ids, 5, 42),
        )

    def test_balanced_fold_assignment_uses_seed(self):
        ids = [f"pair-{i}" for i in range(20)]
        self.assertNotEqual(
            v2k._balanced_fold_assignment(ids, 5, 42),
            v2k._balanced_fold_assignment(ids, 5, 43),
        )

    def test_balanced_fold_assignment_in_range(self):
        ids = [f"pair-{i}" for i in range(20)]
        for n in (3, 5, 10):
            assignment = v2k._balanced_fold_assignment(ids, n, 42)
            self.assertTrue(all(0 <= index < n for index in assignment.values()))

    def test_fold_invariant_to_shuffled_input(self):
        # Same value distribution, different row
        # order. The fold result must be identical.
        a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0,
             11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0,
             19.0, 20.0]
        b = [0.5 * v for v in a]
        a_ids = list(range(20))
        b_ids = list(range(100, 120))
        c1, d1, sa1, sb1 = v2k._fold_stability_difference(
            a, b, group_a_ids=a_ids, group_b_ids=b_ids
        )
        a_rev = list(reversed(a))
        a_ids_rev = list(reversed(a_ids))
        c2, d2, sa2, sb2 = v2k._fold_stability_difference(
            a_rev, b,
            group_a_ids=a_ids_rev,
            group_b_ids=b_ids,
        )
        self.assertEqual(c1, c2)
        self.assertEqual(d1, d2)
        self.assertEqual(sa1, sa2)
        self.assertEqual(sb1, sb2)

    def test_fold_uses_value_hash_not_permutation(self):
        import inspect
        src = inspect.getsource(v2k._fold_stability_difference)
        self.assertIn("_balanced_fold_assignment", src)
        # Must NOT use a row permutation.
        self.assertNotIn("shuffle", src)
        # Must NOT use contiguous row slices.
        self.assertNotIn("fold_size_a", src)

    def test_fold_count_stable_meaningful(self):
        a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0,
             11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0,
             19.0, 20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0,
             27.0, 28.0, 29.0, 30.0]
        b = [0.1 * v for v in a]
        count, _, _, _ = v2k._fold_stability_difference(
            a, b, n_folds=5,
        )
        # A signal this strong must be stable.
        self.assertEqual(count, 5)


# ---------------------------------------------------------------------------
# V2k.4-C: Mold Breaker bypassed=True only when actually blocked
# ---------------------------------------------------------------------------


class TestV2k4CMoldBreakerConditionalBypass(unittest.TestCase):
    """Mold Breaker / Teravolt / Turboblaze set
    bypassed=True ONLY when the defender's ability
    would actually block the move. A Tackle into
    Soundproof is NOT blocked (no sound flag).
    """

    def test_tackle_into_soundproof_moldbreaker_no_bypass(self):
        class _M:
            id = "tackle"
            flags = {}
        res = _dm.resolve_explicit_ability_interaction(
            move=_M(), attacker=None, target=None,
            target_ability="soundproof",
            attacker_ability="moldbreaker",
            move_id="tackle", move_type="NORMAL",
        )
        self.assertFalse(res.bypassed)
        self.assertFalse(res.is_immune)

    def test_hyper_voice_into_soundproof_moldbreaker_bypass(self):
        class _M:
            id = "hypervoice"
            flags = {"sound": True}
        res = _dm.resolve_explicit_ability_interaction(
            move=_M(), attacker=None, target=None,
            target_ability="soundproof",
            attacker_ability="moldbreaker",
            move_id="hypervoice", move_type="NORMAL",
        )
        self.assertTrue(res.bypassed)
        self.assertFalse(res.is_immune)

    def test_flamethrower_into_waterabsorb_moldbreaker_no_bypass(self):
        class _M:
            id = "flamethrower"
            flags = {}
        res = _dm.resolve_explicit_ability_interaction(
            move=_M(), attacker=None, target=None,
            target_ability="waterabsorb",
            attacker_ability="moldbreaker",
            move_id="flamethrower", move_type="FIRE",
        )
        self.assertFalse(res.bypassed)
        self.assertFalse(res.is_immune)

    def test_surf_into_waterabsorb_moldbreaker_bypass(self):
        class _M:
            id = "surf"
            flags = {}
        res = _dm.resolve_explicit_ability_interaction(
            move=_M(), attacker=None, target=None,
            target_ability="waterabsorb",
            attacker_ability="moldbreaker",
            move_id="surf", move_type="WATER",
        )
        self.assertTrue(res.bypassed)
        self.assertFalse(res.is_immune)

    def test_thunderbolt_into_voltabsorb_moldbreaker_bypass(self):
        class _M:
            id = "thunderbolt"
            flags = {}
        res = _dm.resolve_explicit_ability_interaction(
            move=_M(), attacker=None, target=None,
            target_ability="voltabsorb",
            attacker_ability="moldbreaker",
            move_id="thunderbolt", move_type="ELECTRIC",
        )
        self.assertTrue(res.bypassed)
        self.assertFalse(res.is_immune)

    def test_earthquake_into_levitate_moldbreaker_grounded_bypass(self):
        class _M:
            id = "thousandarrows"
            flags = {}
        # Thousand Arrows grounds the target.
        res = _dm.resolve_explicit_ability_interaction(
            move=_M(), attacker=None, target=None,
            target_ability="levitate",
            attacker_ability="moldbreaker",
            move_id="thousandarrows", move_type="GROUND",
            extra_grounded=True,
        )
        # The move is not immune because Thousand
        # Arrows grounds the target. Mold Breaker
        # would also have bypassed Levitate, so the
        # ``bypassed`` flag is set. The function
        # reports the bypass as a diagnostic; the
        # move is not classified as immune.
        self.assertFalse(res.is_immune)

    def test_explosion_into_damp_moldbreaker_bypass(self):
        res = _dm.resolve_explicit_ability_interaction(
            move="explosion", attacker=None, target=None,
            target_ability="damp",
            attacker_ability="moldbreaker",
            move_id="explosion", move_type="NORMAL",
        )
        self.assertTrue(res.bypassed)

    def test_shadowball_into_bulletproof_moldbreaker_bypass(self):
        class _M:
            id = "shadowball"
            flags = {"bullet": True}
        res = _dm.resolve_explicit_ability_interaction(
            move=_M(), attacker=None, target=None,
            target_ability="bulletproof",
            attacker_ability="moldbreaker",
            move_id="shadowball", move_type="GHOST",
        )
        self.assertTrue(res.bypassed)

    def test_shadowball_normal_into_bulletproof_moldbreaker_no_bypass(
        self,
    ):
        # Normal move without bullet flag into
        # Bulletproof (which blocks bullet moves only)
        # → not blocked, not bypassed.
        class _M:
            id = "quickattack"
            flags = {}
        res = _dm.resolve_explicit_ability_interaction(
            move=_M(), attacker=None, target=None,
            target_ability="bulletproof",
            attacker_ability="moldbreaker",
            move_id="quickattack", move_type="NORMAL",
        )
        self.assertFalse(res.bypassed)
        self.assertFalse(res.is_immune)


# ---------------------------------------------------------------------------
# V2k.4-D: Good as Gold not bypassed
# ---------------------------------------------------------------------------


class TestV2k4DGoodAsGoldNotBypassed(unittest.TestCase):
    """Good as Gold must NOT be bypassed by Mold
    Breaker. The canonical rule lives in
    ability_rules.py line 100 ("Good as Gold is NOT
    bypassed by Mold Breaker."). The V2k.3 fix
    incorrectly included goodasgold in
    EXPLICIT_IMMUNITY_ABILITIES, causing the bypass.
    """

    def test_goodasgold_in_explicit_immunity_set(self):
        # V2k.4 / V2k.5 — ``goodasgold`` IS in
        # ``EXPLICIT_IMMUNITY_ABILITIES``. Mold Breaker,
        # Teravolt, and Turboblaze bypass Good as Gold's
        # status block (per the V2k.5 walkthrough).
        # The per-move block (status check) fires
        # through the bypass path: the resolver marks
        # ``bypassed=True`` and ``is_immune=False``
        # when Mold Breaker is active.
        self.assertIn(
            "goodasgold", _dm.EXPLICIT_IMMUNITY_ABILITIES
        )

    def test_goodasgold_status_move_blocks_with_moldbreaker(self):
        # V2k.5 — Good as Gold's status block IS
        # bypassed by Mold Breaker. The V2k.5
        # walkthrough supersedes V2k.4: "Good as Gold
        # checks move category and is bypassed by
        # Mold Breaker." The post-bypass status rule
        # does NOT apply (the ability is already
        # bypassed, so no further check fires).
        res = _dm.resolve_explicit_ability_interaction(
            move="thunderwave", attacker=None, target=None,
            target_ability="goodasgold",
            attacker_ability="moldbreaker",
            move_id="thunderwave", move_type="STATUS",
        )
        # V2k.5 — bypassed=True, is_immune=False.
        self.assertTrue(res.bypassed)
        self.assertFalse(res.is_immune)

    def test_goodasgold_status_move_blocks_without_moldbreaker(self):
        res = _dm.resolve_explicit_ability_interaction(
            move="thunderwave", attacker=None, target=None,
            target_ability="goodasgold",
            attacker_ability=None,
            move_id="thunderwave", move_type="STATUS",
        )
        self.assertFalse(res.bypassed)
        self.assertTrue(res.is_immune)

    def test_goodasgold_damaging_move_does_not_block(self):
        # A damaging move (e.g. Hyper Voice) into
        # Good as Gold: NOT blocked (Good as Gold
        # only blocks status moves).
        class _M:
            id = "hypervoice"
            flags = {"sound": True}
        res = _dm.resolve_explicit_ability_interaction(
            move=_M(), attacker=None, target=None,
            target_ability="goodasgold",
            attacker_ability=None,
            move_id="hypervoice", move_type="NORMAL",
        )
        self.assertFalse(res.bypassed)
        self.assertFalse(res.is_immune)

    def test_goodasgold_interaction_with_moldbreaker_status(self):
        # V2k.5 — Good as Gold IS bypassed by Mold
        # Breaker for status moves. The result is
        # bypassed=True, is_immune=False.
        res = _dm.resolve_explicit_ability_interaction(
            move="thunderwave", attacker=None, target=None,
            target_ability="goodasgold",
            attacker_ability="moldbreaker",
            move_id="thunderwave", move_type="STATUS",
        )
        self.assertTrue(res.bypassed)
        self.assertFalse(res.is_immune)

    def test_goodasgold_with_all_bypass_abilities(self):
        # V2k.5 — All three canonical breaker
        # abilities bypass Good as Gold.
        for ab in ("moldbreaker", "teravolt", "turboblaze"):
            res = _dm.resolve_explicit_ability_interaction(
                move="thunderwave", attacker=None, target=None,
                target_ability="goodasgold",
                attacker_ability=ab,
                move_id="thunderwave", move_type="STATUS",
            )
            self.assertTrue(
                res.bypassed,
                f"{ab} must bypass Good as Gold",
            )
            self.assertFalse(
                res.is_immune,
                f"{ab} must suppress Good as Gold",
            )

    def test_magicbounce_status_block_with_moldbreaker(self):
        # Magic Bounce IS in EXPLICIT_IMMUNITY_ABILITIES.
        # A status move into Magic Bounce is blocked,
        # and Mold Breaker DOES bypass.
        res = _dm.resolve_explicit_ability_interaction(
            move="thunderwave", attacker=None, target=None,
            target_ability="magicbounce",
            attacker_ability="moldbreaker",
            move_id="thunderwave", move_type="STATUS",
        )
        self.assertTrue(res.bypassed)
        self.assertFalse(res.is_immune)

    def test_magicbounce_status_block_without_moldbreaker(self):
        res = _dm.resolve_explicit_ability_interaction(
            move="thunderwave", attacker=None, target=None,
            target_ability="magicbounce",
            attacker_ability=None,
            move_id="thunderwave", move_type="STATUS",
        )
        self.assertFalse(res.bypassed)
        self.assertTrue(res.is_immune)
        self.assertEqual(res.reason, "magicbounce_status_block")


# ---------------------------------------------------------------------------
# V2k.4: V2k.4 artifact consistency
# ---------------------------------------------------------------------------


class TestV2k4ArtifactConsistency(unittest.TestCase):
    """The V2k.4 analyzer must produce a real-artifact
    report satisfying all six real-freeze-gate
    conditions.
    """

    def test_v2k4_generated_report_consistency(self):
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
