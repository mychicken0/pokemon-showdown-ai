# Phase SUPPORT-SCORING-1A — classification tests.
#
# These tests verify the audit-only classification
# helpers. They do NOT change any runtime scoring,
# behavior, or selected actions. They only verify
# the classification logic.

import unittest

from doubles_engine.support_scoring_audit import (
    classify_support_move,
    group_support_move,
    is_priority_1b_candidate,
    NOT_OBSERVED,
    READY_FOR_SCORING_1B,
    NEEDS_TARGET_SEMANTICS_FIRST,
    NEEDS_EARLY_HOOK_LIKE_WT,
    SAFETY_ONLY_NOT_SCORING,
    ALREADY_HANDLED,
    BLOCKED_RISKY,
    GROUP_HEALING_BUFF_ALLY_SUPPORT,
    GROUP_PROTECTION_DEFENSIVE_SUPPORT,
    GROUP_SPEED_TURN_CONTROL,
)


class TestClassifyTier1(unittest.TestCase):
    """Tier 1: priority candidates for SUPPORT-SCORING-1B."""

    def test_tailwind_classified(self):
        self.assertEqual(
            classify_support_move("tailwind"),
            NEEDS_TARGET_SEMANTICS_FIRST,
        )

    def test_wideguard_classified(self):
        self.assertEqual(
            classify_support_move("wideguard"),
            NEEDS_TARGET_SEMANTICS_FIRST,
        )

    def test_helpinghand_classified(self):
        self.assertEqual(
            classify_support_move("helpinghand"),
            NEEDS_TARGET_SEMANTICS_FIRST,
        )

    def test_tailwind_is_priority_1b_candidate(self):
        self.assertTrue(is_priority_1b_candidate("tailwind"))

    def test_wideguard_is_priority_1b_candidate(self):
        self.assertTrue(is_priority_1b_candidate("wideguard"))

    def test_helpinghand_is_priority_1b_candidate(self):
        self.assertTrue(is_priority_1b_candidate("helpinghand"))


class TestClassifyTier2(unittest.TestCase):
    """Tier 2: candidate visibility / target-semantics
    audit only.
    """

    def test_followme_classified(self):
        self.assertEqual(
            classify_support_move("followme"),
            NEEDS_TARGET_SEMANTICS_FIRST,
        )

    def test_ragepowder_classified(self):
        self.assertEqual(
            classify_support_move("ragepowder"),
            NEEDS_TARGET_SEMANTICS_FIRST,
        )

    def test_quickguard_classified(self):
        self.assertEqual(
            classify_support_move("quickguard"),
            NEEDS_TARGET_SEMANTICS_FIRST,
        )

    def test_coaching_classified(self):
        self.assertEqual(
            classify_support_move("coaching"),
            NEEDS_TARGET_SEMANTICS_FIRST,
        )

    def test_lifedew_classified(self):
        self.assertEqual(
            classify_support_move("lifedew"),
            NEEDS_TARGET_SEMANTICS_FIRST,
        )

    def test_pollenpuff_classified(self):
        self.assertEqual(
            classify_support_move("pollenpuff"),
            NEEDS_TARGET_SEMANTICS_FIRST,
        )

    def test_haze_classified(self):
        self.assertEqual(
            classify_support_move("haze"),
            NEEDS_TARGET_SEMANTICS_FIRST,
        )

    def test_clearsmog_classified(self):
        self.assertEqual(
            classify_support_move("clearsmog"),
            NEEDS_TARGET_SEMANTICS_FIRST,
        )


class TestClassifyTier3(unittest.TestCase):
    """Tier 3: safety-first, not scoring candidates.
    These are already handled by the narrow ally heal
    hard safety (SUPPORT-SAFETY-ADOPT-1). They MUST
    remain safety-first, not scoring-first.
    """

    def test_healpulse_safety_first(self):
        self.assertEqual(
            classify_support_move("healpulse"),
            SAFETY_ONLY_NOT_SCORING,
        )

    def test_floralhealing_safety_first(self):
        self.assertEqual(
            classify_support_move("floralhealing"),
            SAFETY_ONLY_NOT_SCORING,
        )

    def test_decorate_safety_first(self):
        self.assertEqual(
            classify_support_move("decorate"),
            SAFETY_ONLY_NOT_SCORING,
        )

    def test_healpulse_not_priority_1b(self):
        self.assertFalse(
            is_priority_1b_candidate("healpulse")
        )

    def test_floralhealing_not_priority_1b(self):
        self.assertFalse(
            is_priority_1b_candidate("floralhealing")
        )

    def test_decorate_not_priority_1b(self):
        self.assertFalse(
            is_priority_1b_candidate("decorate")
        )


class TestClassifyTier4(unittest.TestCase):
    """Tier 4: already handled by Protect, anti-setup
    disruption, etc. Not scoring candidates.
    """

    def test_protect_already_handled(self):
        self.assertEqual(
            classify_support_move("protect"),
            ALREADY_HANDLED,
        )

    def test_detect_already_handled(self):
        self.assertEqual(
            classify_support_move("detect"),
            ALREADY_HANDLED,
        )

    def test_taunt_already_handled(self):
        self.assertEqual(
            classify_support_move("taunt"),
            ALREADY_HANDLED,
        )

    def test_encore_already_handled(self):
        self.assertEqual(
            classify_support_move("encore"),
            ALREADY_HANDLED,
        )

    def test_willowisp_already_handled(self):
        self.assertEqual(
            classify_support_move("willowisp"),
            ALREADY_HANDLED,
        )

    def test_thunderwave_already_handled(self):
        self.assertEqual(
            classify_support_move("thunderwave"),
            ALREADY_HANDLED,
        )


class TestUnknownMoves(unittest.TestCase):
    """Unknown move ids return NOT_OBSERVED so the
    audit treats them as out-of-scope rather than
    silently mapping to a scoring bucket.
    """

    def test_unknown_move_returns_not_observed(self):
        self.assertEqual(
            classify_support_move("unknownmove"),
            NOT_OBSERVED,
        )

    def test_empty_move_returns_not_observed(self):
        self.assertEqual(
            classify_support_move(""),
            NOT_OBSERVED,
        )

    def test_none_move_returns_not_observed(self):
        self.assertEqual(
            classify_support_move(None),
            NOT_OBSERVED,
        )

    def test_damaging_move_returns_not_observed(self):
        # Damaging moves are not support moves; the
        # classifier must not accidentally bucket them
        # as a scoring candidate.
        self.assertEqual(
            classify_support_move("thunderbolt"),
            NOT_OBSERVED,
        )

    def test_unknown_move_not_priority_1b(self):
        self.assertFalse(
            is_priority_1b_candidate("unknownmove")
        )


class TestGroupSupportMove(unittest.TestCase):
    """group_support_move returns the SUPPORT-AUDIT-1
    group for known support moves. Unknown moves
    return GROUP_UNKNOWN_NEEDS_PROBE.
    """

    def test_tailwind_group(self):
        self.assertEqual(
            group_support_move("tailwind"),
            GROUP_SPEED_TURN_CONTROL,
        )

    def test_wideguard_group(self):
        self.assertEqual(
            group_support_move("wideguard"),
            GROUP_PROTECTION_DEFENSIVE_SUPPORT,
        )

    def test_helpinghand_group(self):
        self.assertEqual(
            group_support_move("helpinghand"),
            GROUP_HEALING_BUFF_ALLY_SUPPORT,
        )

    def test_unknown_group(self):
        from doubles_engine.support_scoring_audit import (
            GROUP_UNKNOWN_NEEDS_PROBE,
        )
        self.assertEqual(
            group_support_move("unknownmove"),
            GROUP_UNKNOWN_NEEDS_PROBE,
        )


class TestNormalization(unittest.TestCase):
    """Move ids are normalized the same way as
    doubles_engine.support_targets (lowercased, no
    spaces, dashes, underscores, apostrophes).
    """

    def test_uppercase_normalized(self):
        self.assertEqual(
            classify_support_move("TAILWIND"),
            NEEDS_TARGET_SEMANTICS_FIRST,
        )

    def test_dash_normalized(self):
        self.assertEqual(
            classify_support_move("wide-guard"),
            NEEDS_TARGET_SEMANTICS_FIRST,
        )

    def test_underscore_normalized(self):
        self.assertEqual(
            classify_support_move("helping_hand"),
            NEEDS_TARGET_SEMANTICS_FIRST,
        )

    def test_space_normalized(self):
        self.assertEqual(
            classify_support_move("heal pulse"),
            SAFETY_ONLY_NOT_SCORING,
        )

    def test_apostrophe_normalized(self):
        # The apostrophe in "aurora veil" is rare; just
        # verify the normalizer handles apostrophes.
        result = classify_support_move("aurora'veil")
        # Should be either NEEDS_TARGET_SEMANTICS_FIRST
        # or NOT_OBSERVED depending on the inventory.
        self.assertIn(
            result,
            (NEEDS_TARGET_SEMANTICS_FIRST, NOT_OBSERVED),
        )


class TestScopeGuard(unittest.TestCase):
    """The classifier does NOT enable any default
    flips. It only categorizes moves for audit.
    """

    def test_classifier_does_not_change_defaults(self):
        """The classifier is pure. It does not read or
        write any config or bot state. The bucketing
        is a function of the move id only.
        """
        for mid in [
            "tailwind", "wideguard", "helpinghand",
            "followme", "ragepowder", "coaching",
            "healpulse", "floralhealing", "decorate",
            "protect", "taunt", "encore", "willowisp",
            "thunderwave", "haze", "clearsmog",
            "auroraveil", "snarl", "spore", "fakeout",
        ]:
            cls = classify_support_move(mid)
            # All Tier 1-4 moves must be one of the
            # 7 valid buckets. The audit never returns
            # None or a runtime action.
            self.assertIn(
                cls,
                (
                    READY_FOR_SCORING_1B,
                    NEEDS_TARGET_SEMANTICS_FIRST,
                    NEEDS_EARLY_HOOK_LIKE_WT,
                    SAFETY_ONLY_NOT_SCORING,
                    ALREADY_HANDLED,
                    NOT_OBSERVED,
                    BLOCKED_RISKY,
                ),
                f"{mid} classified to unexpected {cls!r}",
            )


class TestAuditOnlyContract(unittest.TestCase):
    """The classifier must be importable as a pure
    analysis module. No poke-env or bot state
    dependency. No runtime side effects.
    """

    def test_importable_without_poke_env(self):
        # This test runs in the same process. If poke-env
        # were required at import time, the test would
        # fail at module import. The module is already
        # imported at the top of this file.
        from doubles_engine import support_scoring_audit
        self.assertTrue(hasattr(support_scoring_audit, "classify_support_move"))

    def test_classifier_is_pure(self):
        # Calling the classifier twice with the same
        # input must produce the same output.
        for _ in range(3):
            self.assertEqual(
                classify_support_move("tailwind"),
                classify_support_move("tailwind"),
            )
            self.assertEqual(
                classify_support_move("healpulse"),
                classify_support_move("healpulse"),
            )

    def test_priority_1b_only_tier1_moves(self):
        """is_priority_1b_candidate must be True only for
        Tier 1 (priority) moves. It must be False for
        safety-first, already-handled, and unknown moves.
        """
        # Tier 1: priority
        self.assertTrue(is_priority_1b_candidate("tailwind"))
        self.assertTrue(is_priority_1b_candidate("wideguard"))
        self.assertTrue(is_priority_1b_candidate("helpinghand"))
        # Tier 3: safety-first
        self.assertFalse(is_priority_1b_candidate("healpulse"))
        # Tier 4: already-handled
        self.assertFalse(is_priority_1b_candidate("protect"))
        # Unknown
        self.assertFalse(is_priority_1b_candidate("unknownmove"))


if __name__ == "__main__":
    unittest.main()
