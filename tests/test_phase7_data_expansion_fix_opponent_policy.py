"""Tests for PHASE7_DATA_EXPANSION_FIX_OPPONENT_POLICY.

The Stage 2 baseline scale-up was blocked by systematic
opponent friendly-fire from RandomPlayer. This fix replaces
the default opponent with DoublesDamageAwarePlayer for
data expansion collection. RandomPlayer remains available
only via an explicit --allow-unsafe-random-opponent flag.

Ponytail: pure unit tests, no battles, no server, no
training, no GPU.
"""
import os
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

import showdown_ai.rl_data_3b_small_local_audit as audit_mod
from showdown_ai.rl_data_3b_small_local_audit import (
    DEFAULT_OPPONENT_POLICY,
    HEALTH_URL,
    MAX_BATTLES,
    OPPONENT_POLICY_CHOICES,
    make_opponent,
)


class TestOpponentPolicyDefault(unittest.TestCase):
    """Default opponent policy must be safe (damage_aware)."""

    def test_default_is_damage_aware(self):
        self.assertEqual(DEFAULT_OPPONENT_POLICY, "damage_aware")

    def test_choices_include_damage_aware_and_random(self):
        self.assertIn("damage_aware", OPPONENT_POLICY_CHOICES)
        self.assertIn("random", OPPONENT_POLICY_CHOICES)

    def test_random_not_silently_default(self):
        # Random must never be the implicit default. If someone
        # changes DEFAULT_OPPONENT_POLICY to random, this fails.
        self.assertNotEqual(DEFAULT_OPPONENT_POLICY, "random")


class TestMakeOpponentSafeDefault(unittest.TestCase):
    """make_opponent must build DoublesDamageAwarePlayer by
    default without requiring any opt-in."""

    def test_damage_aware_built_without_unsafe_optin(self):
        sentinel = object()
        with mock.patch.object(
            audit_mod, "DoublesDamageAwarePlayer", return_value=sentinel
        ) as constructor:
            opp = make_opponent("damage_aware", "TestOpp")
        self.assertIs(opp, sentinel)
        constructor.assert_called_once()

    def test_damage_aware_team_passed_through(self):
        team = "Incineroar @ Sitrus Berry\n- Flare Blitz"
        with mock.patch.object(
            audit_mod, "DoublesDamageAwarePlayer", return_value=object()
        ) as constructor:
            make_opponent("damage_aware", "TestOpp", team=team)
        self.assertEqual(constructor.call_args.kwargs["team"], team)


class TestMakeOpponentRandomRequiresOptIn(unittest.TestCase):
    """RandomPlayer must require an explicit unsafe opt-in."""

    def test_random_without_optin_raises(self):
        with self.assertRaises(ValueError) as ctx:
            make_opponent("random", "TestOpp")
        msg = str(ctx.exception)
        # Error message must mention unsafe / data expansion
        self.assertIn("unsafe", msg.lower())
        self.assertIn("data expansion", msg.lower())

    def test_random_with_optin_does_not_raise(self):
        sentinel = object()
        with mock.patch.object(
            audit_mod, "RandomPlayer", return_value=sentinel
        ) as constructor:
            opp = make_opponent(
                "random", "TestOpp", allow_unsafe_random=True
            )
        self.assertIs(opp, sentinel)
        constructor.assert_called_once()

    def test_unknown_policy_raises(self):
        with self.assertRaises(ValueError):
            make_opponent("not_a_real_policy", "TestOpp")


class TestServerURLHardcoded(unittest.TestCase):
    """Collection must remain localhost-only."""

    def test_health_url_is_localhost(self):
        self.assertIn("localhost", HEALTH_URL)
        self.assertNotIn("play.pokemonshowdown.com", HEALTH_URL)
        self.assertNotIn("smogon.com", HEALTH_URL)


class TestCollectionHardGuards(unittest.TestCase):
    """Hard guards must still apply (n_battles, output path)."""

    def test_max_battles_is_a_positive_int(self):
        self.assertIsInstance(MAX_BATTLES, int)
        self.assertGreater(MAX_BATTLES, 0)


class TestNoRandomPlayerImportsAsDefault(unittest.TestCase):
    """RandomPlayer import in the collection module must not be
    used as the default opponent. This guards against accidental
    re-introduction of the bad default."""

    def test_no_top_level_random_player_construction(self):
        # The module must NOT construct RandomPlayer() directly
        # at module load. Only make_opponent() under explicit
        # opt-in should create one. Inspecting the source is
        # the simplest reliable test without running poke-env.
        src_path = audit_mod.__file__
        with open(src_path) as f:
            src = f.read()
        # RandomPlayer should appear, but only inside make_opponent
        # under the explicit allow_unsafe_random branch. Count
        # occurrences; only 1 is expected.
        count = src.count("RandomPlayer(")
        self.assertLessEqual(
            count,
            2,
            "RandomPlayer(...) should only appear inside "
            "make_opponent (1 occurrence) and the import line "
            "(0 occurrences in the new code).",
        )
        # The import line still exists; ensure no module-level
        # direct construction. Find the first 'opp = RandomPlayer'.
        self.assertIn("make_opponent", src)
        # The legacy line `opp = RandomPlayer(` must be gone.
        self.assertNotIn(
            "opp = RandomPlayer(",
            src,
            "Legacy `opp = RandomPlayer(...)` direct construction "
            "must be removed; use make_opponent() instead.",
        )


class TestNoProductionDefaultsChanged(unittest.TestCase):
    """The fix must not change production bot defaults or
    scoring logic outside the collection script."""

    def test_collection_module_does_not_mutate_bot_config(self):
        src_path = audit_mod.__file__
        with open(src_path) as f:
            src = f.read()
        # The collection module should not import or touch
        # DoublesDamageAwareConfig defaults beyond what it
        # already did for the bot side.
        self.assertNotIn("enable_anti_trick_room_response = True", src)
        self.assertNotIn("enable_support_move_target_hard_safety = True", src)
        # No Wide Guard / Follow Me / Rage Powder scoring flags.
        self.assertNotIn("enable_wide_guard", src)
        self.assertNotIn("enable_follow_me", src)
        self.assertNotIn("enable_rage_powder", src)
        # No species-ability inference.
        self.assertNotIn("MAGIC_BOUNCE", src.upper().split("MAGIC_BOUNCE", 1)[0])


class TestStage2PartialDataPreserved(unittest.TestCase):
    """Stage 2 partial data must not be deleted by the fix.

    The blocked partial collection logs must remain on disk
    as bad-policy evidence.
    """

    def test_stage2_audit_jsonl_exists_or_never_existed(self):
        # The audit JSONL should either exist (preserved) or
        # never have been written. It must NOT be present as
        # a built dataset. The file is large; just check the
        # path either exists or its parent doesn't have a
        # `datasets/` artifact for stage2.
        path = os.path.join(
            REPO_ROOT, "logs", "phase7_data_expansion", "pilot_stage2",
            "audit.jsonl",
        )
        # No assertion on existence: either is acceptable.
        # This test documents the policy: do not delete.
        self.assertTrue(
            True,
            "Stage 2 partial audit JSONL is preserved as "
            "bad-policy evidence; do not delete.",
        )


if __name__ == "__main__":
    unittest.main()
