#!/usr/bin/env python3
"""Tests for Phase V3c.2 runner asyncio fix."""
import ast
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestV3a2SingleAsyncioEntry(unittest.TestCase):
    """The V3a.2 runner has a single top-level
    asyncio.run path, not per battle."""

    def test_main_has_single_asyncio_run(self):
        from bot_vgc2026_phaseV3a2_reality import main
        # Count code-only occurrences (ignore comments).
        # ponytail: comments may legitimately mention
        # asyncio.run as a description.
        src = inspect.getsource(main)
        non_comment = "\n".join(
            line for line in src.split("\n")
            if not line.lstrip().startswith("#")
        )
        self.assertEqual(
            non_comment.count("asyncio.run("),
            1,
            "main() should have exactly one code-level "
            "asyncio.run call",
        )

    def test_main_uses_run_all_pairs(self):
        from bot_vgc2026_phaseV3a2_reality import main
        src = inspect.getsource(main)
        # Should define an async _run_all_pairs() that
        # awaits D1 and D2.
        self.assertIn("async def _run_all_pairs", src)
        # Should call asyncio.run(_run_all_pairs())
        self.assertIn("asyncio.run(_run_all_pairs())", src)

    def test_two_battles_represented_by_awaited_helper(self):
        from bot_vgc2026_phaseV3a2_reality import main
        src = inspect.getsource(main)
        # Two awaited battles inside the helper.
        self.assertIn("d1 = await run_one_battle", src)
        self.assertIn("d2 = await run_one_battle", src)

    def test_no_nested_asyncio_run(self):
        from bot_vgc2026_phaseV3a2_reality import main
        src = inspect.getsource(main)
        # Make sure asyncio.run isn't called inside
        # the async helper.
        helper_start = src.find("async def _run_all_pairs")
        helper_end = src.rfind("return results")
        helper = src[helper_start:helper_end]
        self.assertNotIn(
            "asyncio.run(",
            helper,
            "asyncio.run must not be called inside the "
            "async helper (would create a nested loop)",
        )


class TestV3a2LearnedPolicyAndPrefixFlags(unittest.TestCase):
    """CLI flags for learned-policy and account-prefix."""

    def test_learned_policy_flag_exists(self):
        from bot_vgc2026_phaseV3a2_reality import main
        sig = inspect.signature(main)
        # argparse is parsed inside main; we check the
        # source for the flag.
        src = inspect.getsource(main)
        self.assertIn("--learned-policy", src)
        self.assertIn(
            "learned_preview_v3a1", src,
            "default value should preserve V3a.1",
        )
        self.assertIn("learned_preview_v3c1", src,
                      "help text should mention V3c.1")

    def test_account_prefix_flag_exists(self):
        from bot_vgc2026_phaseV3a2_reality import main
        src = inspect.getsource(main)
        self.assertIn("--account-prefix", src)
        self.assertIn("V3a2_", src)
        self.assertIn("V3c2_", src)


class TestV3a2RunOneBattleAcceptsPolicyAndPrefix(unittest.TestCase):
    """run_one_battle accepts learned_policy and
    account_prefix as keyword arguments."""

    def test_run_one_battle_signature(self):
        from bot_vgc2026_phaseV3a2_reality import run_one_battle
        sig = inspect.signature(run_one_battle)
        self.assertIn("learned_policy", sig.parameters)
        self.assertIn("account_prefix", sig.parameters)
        # Defaults preserve V3a.2 behavior.
        self.assertEqual(
            sig.parameters["learned_policy"].default,
            "learned_preview_v3a1",
        )
        self.assertEqual(
            sig.parameters["account_prefix"].default,
            "V3a2_",
        )


class TestV3a2MakePlayerNamePrefix(unittest.TestCase):
    """make_player_name accepts a prefix argument."""

    def test_default_prefix(self):
        from bot_vgc2026_phaseV3a2_reality import (
            make_player_name,
        )
        # Default behavior: V3a2_ prefix.
        name = make_player_name(0, "p1", learned=True)
        self.assertTrue(name.startswith("V3a2_p00"))
        self.assertTrue(name.endswith("L"))

    def test_custom_prefix(self):
        from bot_vgc2026_phaseV3a2_reality import (
            make_player_name,
        )
        name = make_player_name(
            0, "p1", learned=True, prefix="V3c2_"
        )
        self.assertTrue(name.startswith("V3c2_p00"))

    def test_suffix_V_for_v3(self):
        from bot_vgc2026_phaseV3a2_reality import (
            make_player_name,
        )
        name = make_player_name(
            5, "p2", learned=False, prefix="V3c2_"
        )
        self.assertTrue(name.startswith("V3c2_p05"))
        self.assertTrue(name.endswith("V"))


class TestInitArtifactsDoesNotTruncate(unittest.TestCase):
    """init_artifacts does not overwrite unless
    overwrite=True. Uses a dedicated test tag so the
    real V3c.2 artifact is not disturbed.
    """

    def test_no_overwrite_raises(self):
        from bot_vgc2026_phaseV3a2_reality import init_artifacts
        test_tag = "phaseV3c2_test_init_no_overwrite"
        jsonl = os.path.join(
            "logs", f"vgc2026_{test_tag}.jsonl"
        )
        csv = os.path.join(
            "logs", f"vgc2026_{test_tag}.csv"
        )
        # Clean up first.
        for p in (jsonl, csv):
            if os.path.isfile(p):
                os.remove(p)
        init_artifacts(test_tag, overwrite=False)
        self.assertTrue(os.path.isfile(jsonl))
        with self.assertRaises(FileExistsError):
            init_artifacts(test_tag, overwrite=False)
        # Cleanup.
        for p in (jsonl, csv):
            if os.path.isfile(p):
                os.remove(p)

    def test_overwrite_succeeds(self):
        from bot_vgc2026_phaseV3a2_reality import init_artifacts
        test_tag = "phaseV3c2_test_init_overwrite"
        jsonl = os.path.join(
            "logs", f"vgc2026_{test_tag}.jsonl"
        )
        csv = os.path.join(
            "logs", f"vgc2026_{test_tag}.csv"
        )
        # Clean up first.
        for p in (jsonl, csv):
            if os.path.isfile(p):
                os.remove(p)
        csv_p, jsonl_p, meta = init_artifacts(
            test_tag, overwrite=True
        )
        self.assertTrue(os.path.isfile(str(csv_p)))
        self.assertTrue(os.path.isfile(str(jsonl_p)))
        # Cleanup.
        for p in (str(csv_p), str(jsonl_p)):
            if os.path.isfile(p):
                os.remove(p)


class TestArtifactStructure(unittest.TestCase):
    """V3c.2 artifact structure has 40 rows in
    jsonl + csv (excluding header)."""

    def test_artifact_row_counts(self):
        jsonl = (
            "logs/vgc2026_phaseV3c2_learned_v3c1_vs_v3_reality20"
            ".jsonl"
        )
        csv_path = (
            "logs/vgc2026_phaseV3c2_learned_v3c1_vs_v3_reality20"
            ".csv"
        )
        if not os.path.isfile(jsonl):
            self.skipTest(f"missing {jsonl}")
        import json
        with open(jsonl) as f:
            n_jsonl = sum(1 for _ in f)
        # 1 timeout so jsonl has 40 rows but only 39 ok.
        self.assertEqual(n_jsonl, 40)
        import csv as _csv
        with open(csv_path) as f:
            r = list(_csv.reader(f))
        # 1 header + 40 data rows.
        self.assertEqual(len(r), 41)


class TestDefaultPolicyUnchanged(unittest.TestCase):
    """Default policy remains matchup_top4_v3 /
    basic_top4."""

    def test_default_policy(self):
        from team_preview_policy import choose_four_from_six
        sig = inspect.signature(choose_four_from_six)
        self.assertEqual(
            sig.parameters["policy"].default, "basic_top4"
        )


if __name__ == "__main__":
    unittest.main()
