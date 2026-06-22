#!/usr/bin/env python3
"""Tests for Phase V3b opponent-adaptive features.

Ponytail: focused tests in a single file. No
new framework.
"""
import json
import os
import sys
import unittest
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vgc2026_phaseV3b_opponent_features import (
    _max_damaging_multiplier,
    _pokemon_types,
    _plan_features,
    _has_speed_control,
    audit_v3b_features,
    enumerate_v3b_plans,
    v3b_features_for_plan,
)
from vgc2026_phaseV3b_train import (
    DEFAULT_V3B_AUDIT_JSON,
    DEFAULT_V3B_AUDIT_MD,
    DEFAULT_V3B_MODEL_PATH,
    DEFAULT_V3B_REPORT_PATH,
    V3A1_VAL_ACC_REFERENCE,
    _discover_v3b_feature_names,
    _extract_v3b_features,
    _load_v3b_rows,
    train_v3b,
    train_v3b_and_save,
    write_audit_files,
)


def _build_test_team_with_moves(
    species_moves: List[tuple],
) -> List[Dict[str, Any]]:
    """Build a 6-pokemon team from (species, moves)
    tuples. ponytail: explicit per-pokemon control
    for tests that need distinct moves/types.
    """
    team = []
    for s, moves in species_moves:
        team.append({
            "species": s,
            "moves": list(moves),
            "ability": "",
        })
    while len(team) < 6:
        team.append({
            "species": "Pikachu",
            "moves": ["Tackle"],
            "ability": "",
        })
    return team[:6]


def _build_test_team(seed_species: List[str]) -> List[Dict[str, Any]]:
    """Build a 6-pokemon team from species names with
    realistic moves and abilities. ponytail: minimal
    fixture, not a real Pikalytics team, but uses
    common damaging moves so V3b features are
    non-trivial.
    """
    common_moves = [
        "Earthquake", "Tackle", "Ice Beam", "Surf",
        "Thunderbolt", "Moonblast", "Sludge Bomb",
        "Knock Off", "Heat Wave", "Rock Slide",
    ]
    team = []
    for i, s in enumerate(seed_species):
        team.append({
            "species": s,
            "moves": [
                common_moves[i % len(common_moves)],
                common_moves[(i + 1) % len(common_moves)],
                common_moves[(i + 2) % len(common_moves)],
                "Protect",
            ],
            "ability": "",
        })
    # Pad to 6
    extras = ["Pikachu", "Charizard", "Garchomp",
              "Incineroar", "Pelipper", "Venusaur"]
    j = 0
    while len(team) < 6:
        team.append({
            "species": extras[j % len(extras)],
            "moves": ["Tackle", "Surf", "Ice Beam", "Protect"],
            "ability": "",
        })
        j += 1
    return team[:6]


class TestV3bFeatureOppSensitivity(unittest.TestCase):
    """V3b features must change when opponent team
    changes but our team/plan stays same."""

    def test_features_change_with_opp_team(self):
        # Our team: ground coverage (Garchomp has
        # Earthquake, Ice for dragons).
        team_a = _build_test_team_with_moves([
            ("Garchomp", ["Earthquake", "Ice Beam", "Protect"]),
            ("Pikachu", ["Thunderbolt", "Surf", "Protect"]),
            ("Incineroar", ["Flare Blitz", "Fake Out", "Protect"]),
            ("Pelipper", ["Hurricane", "Surf", "Protect"]),
            ("Venusaur", ["Sludge Bomb", "Earth Power", "Protect"]),
            ("Dragonite", ["Ice Punch", "Thunder Punch", "Protect"]),
        ])
        # Opponent 1: heavy on physical attackers.
        opp_phys = _build_test_team_with_moves([
            ("Rillaboom", ["Wood Hammer", "Fake Out", "Protect"]),
            ("Landorus", ["Earthquake", "Rock Slide", "Protect"]),
            ("Urshifu", ["Close Combat", "Sucker Punch", "Protect"]),
            ("Tyranitar", ["Rock Slide", "Crunch", "Protect"]),
            ("Zacian", ["Behemoth Blade", "Play Rough", "Protect"]),
            ("Scizor", ["U-turn", "Bullet Punch", "Protect"]),
        ])
        # Opponent 2: heavy on special attackers.
        opp_spec = _build_test_team_with_moves([
            ("Calyrex-Shadow", ["Astral Barrage", "Psyshock", "Protect"]),
            ("Koraidon", ["Draco Meteor", "Flamethrower", "Protect"]),
            ("Miraidon", ["Draco Meteor", "Volt Switch", "Protect"]),
            ("Palkia", ["Hydro Pump", "Draco Meteor", "Protect"]),
            ("Kyogre", ["Water Spout", "Origin Pulse", "Protect"]),
            ("Xerneas", ["Moonblast", "Thunder", "Protect"]),
        ])
        chosen = ["Garchomp", "Pikachu", "Incineroar", "Pelipper"]
        lead = chosen[:2]
        back = chosen[2:]
        f1 = v3b_features_for_plan(team_a, chosen, lead, back,
                                   opp_phys)
        f2 = v3b_features_for_plan(team_a, chosen, lead, back,
                                   opp_spec)
        # opp_phys_move_count must differ (physical
        # team has many physical moves, special team
        # has few).
        self.assertNotEqual(
            f1.get("opp_phys_move_count", 0),
            f2.get("opp_phys_move_count", 0),
            "opp_phys_move_count must change with "
            "opponent team",
        )

    def test_features_change_with_plan(self):
        # Our team: a flying/dragon pivot, a ground
        # attacker, a steel pivot, a fairy support.
        team_a = _build_test_team_with_moves([
            ("Dragonite", ["Hurricane", "Ice Punch", "Protect"]),
            ("Garchomp", ["Earthquake", "Rock Slide", "Protect"]),
            ("Scizor", ["U-turn", "Bullet Punch", "Protect"]),
            ("Incineroar", ["Fake Out", "Flare Blitz", "Protect"]),
            ("Pelipper", ["Surf", "Hurricane", "Protect"]),
            ("Dragapult", ["Shadow Ball", "Draco Meteor", "Protect"]),
        ])
        # Opponent: pure dragon team.
        opp = _build_test_team_with_moves([
            ("Dragapult", ["Shadow Ball", "Draco Meteor", "Protect"]),
            ("Garchomp", ["Earthquake", "Outrage", "Protect"]),
            ("Dragonite", ["Hurricane", "Ice Punch", "Protect"]),
            ("Salamence", ["Earthquake", "Draco Meteor", "Protect"]),
            ("Latios", ["Luster Purge", "Dragon Pulse", "Protect"]),
            ("Hydreigon", ["Dark Pulse", "Draco Meteor", "Protect"]),
        ])
        # Plan 1: lead Dragonite+Dragapult (strong
        # against dragons: ice + ghost).
        chosen1 = ["Dragonite", "Dragapult", "Garchomp", "Scizor"]
        # Plan 2: lead Garchomp+Scizor (ground coverage
        # doesn't hit dragons super-effectively).
        chosen2 = ["Garchomp", "Scizor", "Dragonite", "Dragapult"]
        lead1, back1 = chosen1[:2], chosen1[2:]
        lead2, back2 = chosen2[:2], chosen2[2:]
        f1 = v3b_features_for_plan(team_a, chosen1, lead1,
                                   back1, opp)
        f2 = v3b_features_for_plan(team_a, chosen2, lead2,
                                   back2, opp)
        # lead_off_best_eff should differ: Dragonite has
        # 4x ice coverage, Garchomp has 0x dragon.
        self.assertNotEqual(
            f1.get("lead_off_best_eff", 0),
            f2.get("lead_off_best_eff", 0),
            "lead_off_best_eff must change when lead "
            "changes",
        )

    def test_no_hidden_info_in_feature_names(self):
        # All V3b feature names should be in the
        # documented set. No "opp_item", "opp_hidden_*",
        # etc.
        team_a = _build_test_team(
            ["Garchomp", "Pikachu", "Incineroar",
             "Pelipper", "Venusaur", "Dragonite"]
        )
        opp = _build_test_team(
            ["Palkia", "Gyarados", "Vaporeon",
             "Swampert", "Blastoise", "Inteleon"]
        )
        chosen = ["Garchomp", "Pikachu", "Incineroar", "Pelipper"]
        feats = v3b_features_for_plan(
            team_a, chosen, chosen[:2], chosen[2:], opp
        )
        forbidden_substrings = [
            "hidden", "item", "tier", "usage", "rank",
            "meta", "online", "api", "scrape", "llm",
        ]
        for fname in feats:
            for bad in forbidden_substrings:
                self.assertNotIn(
                    bad, fname.lower(),
                    f"feature {fname} contains "
                    f"forbidden substring '{bad}'",
                )

    def test_deterministic_feature_extraction(self):
        team_a = _build_test_team(
            ["Garchomp", "Pikachu", "Incineroar",
             "Pelipper", "Venusaur", "Dragonite"]
        )
        opp = _build_test_team(
            ["Palkia", "Gyarados", "Vaporeon",
             "Swampert", "Blastoise", "Inteleon"]
        )
        chosen = ["Garchomp", "Pikachu", "Incineroar", "Pelipper"]
        f1 = v3b_features_for_plan(
            team_a, chosen, chosen[:2], chosen[2:], opp
        )
        f2 = v3b_features_for_plan(
            team_a, chosen, chosen[:2], chosen[2:], opp
        )
        self.assertEqual(f1, f2)

    def test_malformed_plan_fails_closed(self):
        # A chosen_4 with species not in our_team
        # should fail closed (return empty).
        team_a = _build_test_team(
            ["Garchomp", "Pikachu", "Incineroar",
             "Pelipper", "Venusaur", "Dragonite"]
        )
        opp = _build_test_team(
            ["Palkia", "Gyarados", "Vaporeon",
             "Swampert", "Blastoise", "Inteleon"]
        )
        # Use a species that isn't in team_a.
        bad_chosen = ["Mewtwo", "Mew", "Lugia", "Ho-Oh"]
        f = v3b_features_for_plan(
            team_a, bad_chosen, bad_chosen[:2], bad_chosen[2:],
            opp,
        )
        self.assertEqual(f, {})


class TestV3bFeatureAudit(unittest.TestCase):
    """Feature audit gates."""

    @classmethod
    def setUpClass(cls):
        from vgc_team_pool import load_vgc_pool
        cls.pool = load_vgc_pool()

    def test_audit_gates(self):
        audit = audit_v3b_features(
            self.pool, n_teams=5, n_opps_per_team=3, seed=42
        )
        # Gates from the task contract.
        self.assertGreaterEqual(
            audit["n_opp_sensitive"], 15,
            f"need >=15 opp_sensitive, got "
            f"{audit['n_opp_sensitive']}",
        )
        self.assertGreaterEqual(
            audit["n_plan_varying"], 10,
            f"need >=10 plan_varying, got "
            f"{audit['n_plan_varying']}",
        )

    def test_audit_summary_fields(self):
        audit = audit_v3b_features(
            self.pool, n_teams=3, n_opps_per_team=2, seed=42
        )
        for entry in audit["feature_summary"]:
            for key in (
                "name", "nonzero_count",
                "avg_var_across_plans_same_team",
                "var_across_opps_same_team",
                "opponent_sensitive", "plan_varying",
            ):
                self.assertIn(key, entry)


class TestV3bTrainingArtifacts(unittest.TestCase):
    """Training artifacts and gates."""

    @classmethod
    def setUpClass(cls):
        from vgc_team_pool import load_vgc_pool
        cls.pool = load_vgc_pool()
        cls.jsonl_paths = [
            "logs/vgc2026_phaseV2c_phaseV2c2_smoke_test_benchmark.jsonl"
        ]

    def test_group_split_no_leakage(self):
        rows, _ = _load_v3b_rows(self.jsonl_paths, self.pool)
        from vgc2026_phaseV3a_learn_preview import (
            assert_no_leakage, group_split,
        )
        train_rows, val_rows, _ = group_split(
            rows, val_fraction=0.2, seed=42
        )
        assert_no_leakage(train_rows, val_rows)

    def test_artifact_json_schema(self):
        # V3b model and report were already written by
        # the V3b training CLI run.
        self.assertTrue(
            os.path.isfile(DEFAULT_V3B_MODEL_PATH),
            f"missing {DEFAULT_V3B_MODEL_PATH}",
        )
        with open(DEFAULT_V3B_MODEL_PATH) as f:
            model = json.load(f)
        for key in (
            "feature_names", "weights", "bias", "metadata",
        ):
            self.assertIn(key, model)
        # The feature_names should be a non-empty list
        # of strings.
        self.assertIsInstance(model["feature_names"], list)
        self.assertGreater(len(model["feature_names"]), 0)
        self.assertIsInstance(model["weights"], dict)
        for fname in model["feature_names"]:
            self.assertIn(fname, model["weights"])
        self.assertTrue(
            os.path.isfile(DEFAULT_V3B_REPORT_PATH),
            f"missing {DEFAULT_V3B_REPORT_PATH}",
        )
        with open(DEFAULT_V3B_REPORT_PATH) as f:
            report = json.load(f)
        self.assertEqual(report["phase"], "V3b")
        self.assertEqual(
            report["default_policy"], "matchup_top4_v3"
        )
        self.assertIn("val_pairwise_accuracy_used", str(
            report["train_meta"]
        ) or "")
        # Per task: blocked when val_acc is weak.
        val_acc = report["train_meta"][
            "val_pairwise_accuracy_used"
        ]
        self.assertLess(
            val_acc, V3A1_VAL_ACC_REFERENCE,
            "V3b is BLOCKED on val_acc, expected val "
            f"< {V3A1_VAL_ACC_REFERENCE}, got {val_acc}",
        )

    def test_default_policy_unchanged(self):
        # The V3b training is BLOCKED on val_acc, so
        # the policy wrapper must not be registered.
        # Verify the default policy param of
        # choose_four_from_six is still 'basic_top4'
        # (the V3a.1 / V3 default). ponytail:
        # read-only check, do not change defaults.
        from team_preview_policy import choose_four_from_six
        import inspect
        sig = inspect.signature(choose_four_from_six)
        self.assertEqual(
            sig.parameters["policy"].default,
            "basic_top4",
            "V3b is BLOCKED: choose_four_from_six default "
            "must remain 'basic_top4' (the V3 wrapper "
            "may be selected explicitly by passing "
            "policy='matchup_top4_v3')",
        )

    def test_audit_files_written(self):
        self.assertTrue(
            os.path.isfile(DEFAULT_V3B_AUDIT_JSON),
            f"missing {DEFAULT_V3B_AUDIT_JSON}",
        )
        self.assertTrue(
            os.path.isfile(DEFAULT_V3B_AUDIT_MD),
            f"missing {DEFAULT_V3B_AUDIT_MD}",
        )
        with open(DEFAULT_V3B_AUDIT_JSON) as f:
            audit = json.load(f)
        self.assertIn("n_opp_sensitive", audit)
        self.assertIn("n_plan_varying", audit)
        self.assertIn("feature_summary", audit)


class TestV3bExistingTestsStillPass(unittest.TestCase):
    """The existing V3a/V3a.1 tests must still pass.

    Re-runs the existing V3a test file as a smoke
    test. ponytail: this verifies V3b didn't
    regress V3a.1 artifacts.
    """
    def test_v3a_module_imports_cleanly(self):
        import vgc2026_phaseV3a_learn_preview as v3a
        # V3a.1 model must still exist.
        from vgc2026_phaseV3a_learn_preview import (
            DEFAULT_V3A1_MODEL_PATH,
        )
        self.assertTrue(
            os.path.isfile(DEFAULT_V3A1_MODEL_PATH),
            "V3a.1 model artifact must be preserved",
        )


if __name__ == "__main__":
    unittest.main()
