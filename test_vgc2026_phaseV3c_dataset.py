#!/usr/bin/env python3
"""Tests for Phase V3c dataset builder."""
import json
import os
import sys
import unittest
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vgc2026_phaseV3c_dataset import (
    ALL_FOUR_POLICIES,
    LOG_DIR,
    PAIRINGS,
    _acceptance_gates,
    _build_merged,
    _label_entropy,
    _pairing_slug,
    _per_pairing_categories,
    _side_collapse,
    _split_pair_categories,
    _tag_for_pairing,
    _validate_pairing,
    _wilson_ci,
    build_per_pairing_summary,
)


def _make_row(
    pair_id: int,
    side: str,
    our_policy: str,
    our_win: bool,
    status: str = "ok",
) -> Dict[str, Any]:
    """Build a minimal row for tests."""
    return {
        "pair_id": pair_id,
        "side": side,
        "our_policy": our_policy,
        "opponent_policy": "opponent",
        "battle_tag": f"battle-gen9vgc2026regma-{pair_id:03d}-{side}",
        "status": status,
        "our_win": our_win,
        "turns": 5,
        "error_detail": "",
        "our_chosen_4": ["a", "b", "c", "d"],
        "our_lead_2": ["a", "b"],
        "our_back_2": ["c", "d"],
        "opp_chosen_4": ["e", "f", "g", "h"],
        "opp_lead_2": ["e", "f"],
        "opp_back_2": ["g", "h"],
        "our_team": [
            {"species": s} for s in ["a", "b", "c", "d", "x", "y"]
        ],
    }


class TestPairingConfigGeneration(unittest.TestCase):
    def test_pairing_slug_sorted(self):
        # a vs b == b vs a (sorted slug).
        self.assertEqual(
            _pairing_slug("v3", "basic"),
            _pairing_slug("basic", "v3"),
        )
        self.assertEqual(
            _pairing_slug("matchup_top4_v3", "learned_preview_v3a1"),
            "learned_preview_v3a1_vs_matchup_top4_v3",
        )

    def test_tag_for_pairing_stable(self):
        self.assertEqual(
            _tag_for_pairing(
                "matchup_top4_v3", "learned_preview_v3a1"
            ),
            "phaseV3c_preview_dataset25_"
            "learned_preview_v3a1_vs_matchup_top4_v3",
        )

    def test_pairings_list_complete(self):
        # All 6 required pairings present.
        expected = {
            ("matchup_top4_v3", "learned_preview_v3a1"),
            ("matchup_top4_v3", "basic_top4"),
            ("learned_preview_v3a1", "basic_top4"),
            ("matchup_top4_v3", "random"),
            ("learned_preview_v3a1", "random"),
            ("basic_top4", "random"),
        }
        actual = set(PAIRINGS)
        self.assertEqual(actual, expected)
        # All four policies present.
        all_pols = set()
        for a, b in PAIRINGS:
            all_pols.add(a)
            all_pols.add(b)
        self.assertEqual(all_pols, set(ALL_FOUR_POLICIES))


class TestSideSwapPolicyAssignment(unittest.TestCase):
    def test_side_swap_correct(self):
        # D1: a as p1, b as p2.
        # D2: b as p1, a as p2.
        # our_win=True means our (D1=a) won.
        rows = []
        for p in range(5):
            d1 = _make_row(p, "p1", "a", our_win=True)
            d2 = _make_row(p, "p2", "b", our_win=False)
            rows.append(d1)
            rows.append(d2)
        val = _validate_pairing(rows, "a", "b")
        # a won all 5 as p1, a won all 5 as p2 (because
        # D2's our_win=False means a won as p2).
        self.assertEqual(val["a_wins_as_p1"], 5)
        self.assertEqual(val["a_wins_as_p2"], 5)
        self.assertEqual(val["b_wins_as_p1"], 0)
        self.assertEqual(val["b_wins_as_p2"], 0)
        self.assertEqual(val["winner_policy_a"], 10)
        self.assertEqual(val["winner_policy_b"], 0)


class TestPerPairingCategories(unittest.TestCase):
    def test_a_both(self):
        rows = [
            _make_row(0, "p1", "a", our_win=True),
            _make_row(0, "p2", "b", our_win=False),
        ]
        cats = _per_pairing_categories(rows, "a", "b")
        self.assertEqual(cats["a_both"], 1)
        self.assertEqual(cats["b_both"], 0)
        self.assertEqual(cats["split"], 0)

    def test_b_both(self):
        rows = [
            _make_row(0, "p1", "a", our_win=False),
            _make_row(0, "p2", "b", our_win=True),
        ]
        cats = _per_pairing_categories(rows, "a", "b")
        self.assertEqual(cats["a_both"], 0)
        self.assertEqual(cats["b_both"], 1)
        self.assertEqual(cats["split"], 0)

    def test_split(self):
        rows = [
            _make_row(0, "p1", "a", our_win=True),
            _make_row(0, "p2", "b", our_win=True),
        ]
        cats = _per_pairing_categories(rows, "a", "b")
        self.assertEqual(cats["a_both"], 0)
        self.assertEqual(cats["b_both"], 0)
        self.assertEqual(cats["split"], 1)


class TestWinnerDistribution(unittest.TestCase):
    def test_winner_counts_balanced(self):
        # 4 rows each, 2 pairings, balanced.
        rows = []
        for p in range(4):
            d1 = _make_row(p, "p1", "v3", our_win=True)
            d2 = _make_row(p, "p2", "learned", our_win=True)
            rows.append(d1)
            rows.append(d2)
        val = _validate_pairing(rows, "v3", "learned")
        self.assertEqual(val["winner_policy_a"], 4)
        self.assertEqual(val["winner_policy_b"], 4)


class TestLabelEntropy(unittest.TestCase):
    def test_entropy_max_uniform(self):
        # 4 winners, one of each policy, on decisive pairs.
        rows = []
        for p in range(4):
            d1 = _make_row(p, "p1", "v3", our_win=True)
            d2 = _make_row(p, "p2", "learned", our_win=False)
            rows.append(d1)
            rows.append(d2)
        # Make decisive: v3 won both as p1, learned won both as p2.
        ent = _label_entropy(rows)
        # Only v3 wins, so entropy=0.
        self.assertEqual(ent["entropy"], 0.0)

    def test_entropy_uniform_4_policies(self):
        # 4 decisive pairs, each with a different policy winning.
        # Pair 0: v3 both sides (a_both).
        # Pair 1: basic both sides (b_both, basic is our in D1).
        # Pair 2: random both sides (b_both, random is our in D1).
        # Pair 3: learned both sides (b_both, learned is our in D1).
        rows = []
        # Pair 0: v3 both. a=v3, b=learned. v3 wins D1 (a), v3 wins D2
        # (so our_win=False in D2).
        rows.append(_make_row(0, "p1", "v3", our_win=True))
        rows.append(_make_row(0, "p2", "learned", our_win=False))
        # Pair 1: a=basic, b=v3. basic wins both.
        rows.append(_make_row(1, "p1", "basic", our_win=True))
        rows.append(_make_row(1, "p2", "v3", our_win=False))
        # Pair 2: a=random, b=v3. random wins both.
        rows.append(_make_row(2, "p1", "random", our_win=True))
        rows.append(_make_row(2, "p2", "v3", our_win=False))
        # Pair 3: a=learned, b=v3. learned wins both.
        rows.append(_make_row(3, "p1", "learned", our_win=True))
        rows.append(_make_row(3, "p2", "v3", our_win=False))
        ent = _label_entropy(rows)
        # 4 winners, 1 each of v3, basic, random, learned
        # (basic/random/learned appear once because D1
        # had them as a, and they won both sides). Entropy
        # = -4 * 0.25 * log2(0.25) = log2(4) = 2.0.
        self.assertAlmostEqual(ent["entropy"], 2.0, places=2)


class TestAcceptanceGates(unittest.TestCase):
    def _mk_pp(self, n_decisive, side_collapse):
        return {
            "policy_a": "a",
            "policy_b": "b",
            "categories": {"n_decisive": n_decisive},
            "side_collapse": side_collapse,
            "winner_policy_a": 5,
            "winner_policy_b": 5,
        }

    def test_hard_gates_pass_overall_pass(self):
        per_pairing = [self._mk_pp(15, 0.10) for _ in range(6)]
        merged = {
            "n_battles_total": 300,
            "n_complete_pairs": 150,
            "n_bad_status_total": 0,
            "n_team_serialization_total": 0,
            "n_duplicate_tags_total": 0,
            "winner_policy_counts_decisive": {
                "matchup_top4_v3": 30,
                "learned_preview_v3a1": 30,
                "basic_top4": 30,
                "random": 30,
            },
            "label_entropy": 1.0,
        }
        g = _acceptance_gates(per_pairing, merged)
        self.assertTrue(g["overall_pass"])

    def test_block_on_bad_status(self):
        per_pairing = [self._mk_pp(15, 0.10) for _ in range(6)]
        merged = {
            "n_battles_total": 300,
            "n_complete_pairs": 150,
            "n_bad_status_total": 1,
            "n_team_serialization_total": 0,
            "n_duplicate_tags_total": 0,
            "winner_policy_counts_decisive": {
                "matchup_top4_v3": 30,
                "learned_preview_v3a1": 30,
                "basic_top4": 30,
                "random": 30,
            },
            "label_entropy": 1.0,
        }
        g = _acceptance_gates(per_pairing, merged)
        self.assertFalse(g["gates"]["zero_bad_status"])
        self.assertFalse(g["overall_pass"])


class TestNoOverwriteGuard(unittest.TestCase):
    """No overwrite guard for existing artifacts."""

    def test_init_artifacts_raises_on_existing(self):
        from bot_vgc2026_phaseV3a2_reality import init_artifacts
        # Create a fake tag that already has files.
        fake_tag = "phaseV3c_no_overwrite_test"
        jsonl = os.path.join(
            LOG_DIR, f"vgc2026_{fake_tag}.jsonl"
        )
        csv = os.path.join(
            LOG_DIR, f"vgc2026_{fake_tag}.csv"
        )
        # Clean up first.
        for p in (jsonl, csv):
            if os.path.isfile(p):
                os.remove(p)
        init_artifacts(fake_tag, overwrite=False)
        self.assertTrue(os.path.isfile(jsonl))
        # Re-init without overwrite should raise.
        with self.assertRaises(FileExistsError):
            init_artifacts(fake_tag, overwrite=False)
        # Re-init with overwrite should succeed.
        init_artifacts(fake_tag, overwrite=True)
        # Cleanup.
        for p in (jsonl, csv):
            if os.path.isfile(p):
                os.remove(p)


class TestLearnedPreviewV3a1Preflight(unittest.TestCase):
    """V3a.1 model artifact must exist for
    learned_preview_v3a1 to work."""

    def test_v3a1_model_artifact_exists(self):
        from vgc2026_phaseV3a_learn_preview import (
            DEFAULT_V3A1_MODEL_PATH,
        )
        self.assertTrue(
            os.path.isfile(DEFAULT_V3A1_MODEL_PATH),
            f"missing {DEFAULT_V3A1_MODEL_PATH}",
        )

    def test_preflight_fails_cleanly(self):
        from vgc2026_phaseV3c_dataset import (
            _verify_policies_available,
        )
        err = _verify_policies_available()
        # The V3a.1 model exists, so this should be None.
        self.assertIsNone(err)


class TestDefaultPolicyUnchanged(unittest.TestCase):
    """Default policy remains basic_top4."""

    def test_default_policy(self):
        from team_preview_policy import choose_four_from_six
        import inspect
        default_pol = inspect.signature(
            choose_four_from_six
        ).parameters["policy"].default
        self.assertEqual(default_pol, "basic_top4")

    def test_v3a1_wrapper_opt_in(self):
        from team_preview_policy import choose_four_from_six
        # The V3a.1 wrapper exists but is opt-in.
        # Choosing matchup_top4_v3 explicitly should work.
        team = [
            {"species": s, "moves": ["Tackle"], "ability": ""}
            for s in ["a", "b", "c", "d", "e", "f"]
        ]
        opp = team[:]
        result = choose_four_from_six(
            team, opp, policy="matchup_top4_v3"
        )
        self.assertEqual(len(result.chosen_4), 4)


class TestWilsonCI(unittest.TestCase):
    def test_wilson_basic(self):
        lower, upper = _wilson_ci(50, 100)
        self.assertGreater(lower, 0.0)
        self.assertLess(upper, 1.0)
        self.assertLess(lower, 0.5)
        self.assertGreater(upper, 0.5)

    def test_wilson_zero(self):
        lower, upper = _wilson_ci(0, 0)
        self.assertEqual((lower, upper), (0.0, 0.0))


class TestArtifactsJsonSerializable(unittest.TestCase):
    """V3c dataset artifacts are JSON-serializable."""

    def test_summary_json_loadable(self):
        path = os.path.join(
            LOG_DIR,
            "vgc2026_phaseV3c_preview_dataset25_summary.json",
        )
        if not os.path.isfile(path):
            self.skipTest(f"missing {path}")
        with open(path) as f:
            data = json.load(f)
        self.assertIn("per_pairing", data)
        self.assertIn("merged", data)
        self.assertIn("gates", data)

    def test_summary_md_exists(self):
        path = os.path.join(
            LOG_DIR,
            "vgc2026_phaseV3c_preview_dataset25_summary.md",
        )
        if not os.path.isfile(path):
            self.skipTest(f"missing {path}")
        with open(path) as f:
            content = f.read()
        self.assertIn("Phase V3c", content)


if __name__ == "__main__":
    unittest.main()
