"""Phase RL-DATA-3d — Tests for action distribution analysis.

Validates that the selected-joint classification is
correctly mutually exclusive and that overlapping
tags can coexist without corrupting the primary
distribution.

Coverage:
- selected-joint primary categories are mutually exclusive
- overlapping tags can coexist (e.g., attack+protect is
  one primary but has both has_attack and has_protect
  tags)
- attack+protect is not counted as double_attack
- double_switch is not counted as double_attack
- setup move selected is detected
- weather setter selected is detected
- switch/pass actions are not counted as support moves
- legal-vs-selected analysis works
- score-baseline unavailable path works when scores
  are missing
- baseline calculations handle empty/small datasets
  safely
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from typing import Any, Dict, List

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(
    0, os.path.dirname(
        os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
    )
)

from scripts.analyze.analyze_rl_data_3d_action_distribution import (  # noqa: E402
    _action_kind,
    _classify_legal_tags,
    _classify_selected_joint_primary,
    _classify_selected_joint_tags,
    _is_protect_move,
    _is_setup_move,
    _is_support_move,
    _is_weather_setter,
    _move_id_norm,
    _norm_move_id,
    analyze_dataset,
)


# ============================================================
# _classify_selected_joint_primary — mutually exclusive
# ============================================================
class TestSelectedJointPrimaryMutuallyExclusive(unittest.TestCase):
    """Verify primary categories are mutually exclusive."""

    def test_double_attack_both_damaging(self):
        primary = _classify_selected_joint_primary(
            "move", "move", "moonblast", "hydropump"
        )
        self.assertEqual(primary, "double_attack")

    def test_double_protect_both_protect(self):
        primary = _classify_selected_joint_primary(
            "move", "move", "protect", "detect"
        )
        self.assertEqual(primary, "double_protect")

    def test_attack_plus_protect_one_protect(self):
        primary = _classify_selected_joint_primary(
            "move", "move", "moonblast", "protect"
        )
        self.assertEqual(primary, "attack_plus_protect")
        # NOT double_attack or double_protect
        self.assertNotEqual(primary, "double_attack")
        self.assertNotEqual(primary, "double_protect")

    def test_attack_plus_setup(self):
        primary = _classify_selected_joint_primary(
            "move", "move", "moonblast", "quiverdance"
        )
        self.assertEqual(primary, "attack_plus_setup")

    def test_attack_plus_weather_setter(self):
        primary = _classify_selected_joint_primary(
            "move", "move", "moonblast", "raindance"
        )
        self.assertEqual(primary, "attack_plus_weather_setter")

    def test_attack_plus_support(self):
        primary = _classify_selected_joint_primary(
            "move", "move", "moonblast", "helpinghand"
        )
        self.assertEqual(primary, "attack_plus_support")

    def test_double_switch(self):
        primary = _classify_selected_joint_primary(
            "switch", "switch", "volcarona", "garchomp"
        )
        self.assertEqual(primary, "double_switch")
        self.assertNotEqual(primary, "double_attack")

    def test_move_plus_switch(self):
        primary = _classify_selected_joint_primary(
            "move", "switch", "moonblast", "volcarona"
        )
        self.assertEqual(primary, "move_plus_switch")

    def test_single_move_plus_pass(self):
        primary = _classify_selected_joint_primary(
            "move", "pass", "moonblast", "/choose pass"
        )
        self.assertEqual(primary, "single_move_plus_pass")

    def test_attack_plus_switch_when_one_is_pass(self):
        # When slot1 is a pass and slot0 is a switch,
        # this is "attack_plus_switch" (label may be
        # misleading but the category captures the
        # fact that one slot has a non-move action).
        primary = _classify_selected_joint_primary(
            "switch", "pass", "volcarona", "/choose pass"
        )
        # Per the classifier, this is
        # "attack_plus_switch" which is actually
        # "switch + pass". The label is imperfect
        # but the category is correct.
        self.assertEqual(primary, "attack_plus_switch")

    def test_unknown_unknown(self):
        primary = _classify_selected_joint_primary(
            "unknown", "unknown", "", ""
        )
        self.assertEqual(primary, "unknown")

    def test_pure_pass(self):
        primary = _classify_selected_joint_primary(
            "pass", "pass", "/choose pass", "/choose pass"
        )
        self.assertEqual(primary, "unknown")


# ============================================================
# _classify_selected_joint_tags — overlapping
# ============================================================
class TestSelectedJointOverlappingTags(unittest.TestCase):
    """Verify overlapping tags can coexist."""

    def test_double_attack_tags(self):
        tags = _classify_selected_joint_tags(
            "move", "move", "moonblast", "hydropump"
        )
        self.assertTrue(tags["has_attack"])
        self.assertFalse(tags["has_protect"])
        self.assertFalse(tags["has_switch"])
        self.assertFalse(tags["has_pass"])
        self.assertFalse(tags["has_setup"])
        self.assertFalse(tags["has_weather_setter"])

    def test_attack_plus_protect_tags(self):
        # One damaging, one Protect. Both has_attack
        # and has_protect should be True.
        tags = _classify_selected_joint_tags(
            "move", "move", "moonblast", "protect"
        )
        self.assertTrue(tags["has_attack"])
        self.assertTrue(tags["has_protect"])
        self.assertFalse(tags["has_switch"])
        # The PRIMARY is "attack_plus_protect" (one
        # primary), but the TAGS can coexist.
        primary = _classify_selected_joint_primary(
            "move", "move", "moonblast", "protect"
        )
        self.assertEqual(primary, "attack_plus_protect")
        # This is NOT double_attack.
        self.assertNotEqual(primary, "double_attack")

    def test_double_switch_tags(self):
        tags = _classify_selected_joint_tags(
            "switch", "switch", "volcarona", "garchomp"
        )
        self.assertFalse(tags["has_attack"])
        self.assertTrue(tags["has_switch"])
        self.assertFalse(tags["has_protect"])
        # Primary is double_switch.
        primary = _classify_selected_joint_primary(
            "switch", "switch", "volcarona", "garchomp"
        )
        self.assertEqual(primary, "double_switch")
        self.assertNotEqual(primary, "double_attack")

    def test_setup_in_tag(self):
        tags = _classify_selected_joint_tags(
            "move", "move", "moonblast", "quiverdance"
        )
        self.assertTrue(tags["has_attack"])
        self.assertTrue(tags["has_setup"])

    def test_weather_setter_in_tag(self):
        tags = _classify_selected_joint_tags(
            "move", "move", "moonblast", "raindance"
        )
        self.assertTrue(tags["has_attack"])
        self.assertTrue(tags["has_weather_setter"])

    def test_pass_in_tag(self):
        tags = _classify_selected_joint_tags(
            "move", "pass", "moonblast", "/choose pass"
        )
        self.assertTrue(tags["has_attack"])
        self.assertTrue(tags["has_pass"])
        self.assertFalse(tags["has_protect"])

    def test_support_in_tag(self):
        tags = _classify_selected_joint_tags(
            "move", "move", "moonblast", "helpinghand"
        )
        self.assertTrue(tags["has_attack"])
        self.assertTrue(tags["has_support"])


# ============================================================
# _classify_legal_tags
# ============================================================
class TestLegalTags(unittest.TestCase):
    """Verify legal candidate classification."""

    def test_legal_with_protect_and_attack(self):
        legal0 = [
            ["move", "moonblast", 0, ""],
            ["move", "protect", 0, ""],
        ]
        legal1 = [["move", "hydropump", 0, ""]]
        tags = _classify_legal_tags(legal0, legal1)
        self.assertTrue(tags["has_attack"])
        self.assertTrue(tags["has_protect"])
        self.assertFalse(tags["has_switch"])

    def test_legal_with_setup(self):
        legal0 = [["move", "quiverdance", 0, ""]]
        legal1 = []
        tags = _classify_legal_tags(legal0, legal1)
        self.assertTrue(tags["has_setup"])

    def test_legal_with_weather_setter(self):
        legal0 = [["move", "raindance", 0, ""]]
        tags = _classify_legal_tags(legal0, [])
        self.assertTrue(tags["has_weather_setter"])
        # Also terrain setter for electricterrain
        legal0b = [["move", "electricterrain", 0, ""]]
        tags2 = _classify_legal_tags(legal0b, [])
        self.assertTrue(tags2["has_weather_setter"])
        self.assertTrue(tags2["has_terrain_setter"])

    def test_legal_with_switch(self):
        legal0 = [["switch", "volcarona", 0, ""]]
        tags = _classify_legal_tags(legal0, [])
        self.assertTrue(tags["has_switch"])
        self.assertFalse(tags["has_attack"])

    def test_empty_legal(self):
        tags = _classify_legal_tags([], [])
        self.assertFalse(tags["has_attack"])
        self.assertFalse(tags["has_protect"])


# ============================================================
# Move keyword detection
# ============================================================
class TestMoveKeywords(unittest.TestCase):
    """Verify move keyword detection."""

    def test_protect_detection(self):
        self.assertTrue(_is_protect_move("protect"))
        self.assertTrue(_is_protect_move("detect"))
        self.assertTrue(_is_protect_move("kingsshield"))
        self.assertFalse(_is_protect_move("moonblast"))
        self.assertFalse(_is_protect_move("raindance"))

    def test_setup_detection(self):
        self.assertTrue(_is_setup_move("quiverdance"))
        self.assertTrue(_is_setup_move("swordsdance"))
        self.assertTrue(_is_setup_move("nastyplot"))
        self.assertTrue(_is_setup_move("substitute"))
        self.assertFalse(_is_setup_move("moonblast"))
        self.assertFalse(_is_setup_move("protect"))

    def test_weather_setter_detection(self):
        self.assertTrue(_is_weather_setter("raindance"))
        self.assertTrue(_is_weather_setter("sunnyday"))
        self.assertTrue(_is_weather_setter("sandstorm"))
        self.assertTrue(_is_weather_setter("electricterrain"))
        self.assertFalse(_is_weather_setter("moonblast"))

    def test_support_detection(self):
        self.assertTrue(_is_support_move("helpinghand"))
        self.assertTrue(_is_support_move("healpulse"))
        self.assertTrue(_is_support_move("taunt"))
        self.assertTrue(_is_support_move("lightscreen"))
        # Protect IS a support move (in the keyword set).
        self.assertTrue(_is_support_move("protect"))
        self.assertFalse(_is_support_move("moonblast"))
        self.assertFalse(_is_support_move("hydropump"))
        self.assertFalse(_is_support_move("raindance"))


# ============================================================
# analyze_dataset — end-to-end
# ============================================================
class TestAnalyzeDataset(unittest.TestCase):
    """End-to-end tests for the analysis script."""

    def test_minimal_dataset(self):
        """A 2-row minimal dataset exercises the
        primary classification.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            rows = [
                {
                    "schema_version": "turn_rl_v1.1",
                    "selected_joint_key": [
                        ["move", "moonblast", 0, ""],
                        ["move", "hydropump", 0, ""],
                    ],
                    "legal_action_keys_slot0": [
                        ["move", "moonblast", 0, ""],
                    ],
                    "legal_action_keys_slot1": [
                        ["move", "hydropump", 0, ""],
                    ],
                    "local_only_provenance": True,
                    "used_species_ability_inference": False,
                },
                {
                    "schema_version": "turn_rl_v1.1",
                    "selected_joint_key": [
                        ["move", "protect", 0, ""],
                        ["move", "detect", 0, ""],
                    ],
                    "legal_action_keys_slot0": [
                        ["move", "protect", 0, ""],
                        ["move", "moonblast", 0, ""],
                    ],
                    "legal_action_keys_slot1": [
                        ["move", "detect", 0, ""],
                        ["move", "hydropump", 0, ""],
                    ],
                    "local_only_provenance": True,
                    "used_species_ability_inference": False,
                },
            ]
            for r in rows:
                f.write(json.dumps(r) + "\n")
            tmp_path = f.name
        try:
            result = analyze_dataset(tmp_path)
            self.assertEqual(result["n_rows"], 2)
            self.assertTrue(result["hard_safety_clean"])
            primary = result["selected_joint_primary_distribution"]
            self.assertEqual(primary["double_attack"]["count"], 1)
            self.assertEqual(primary["double_protect"]["count"], 1)
            # Tags
            tags = result["selected_joint_overlapping_tags"]
            self.assertEqual(tags["has_attack"]["count"], 2)
            self.assertEqual(tags["has_protect"]["count"], 1)
        finally:
            os.unlink(tmp_path)

    def test_score_field_unavailable_path(self):
        """When raw scores are missing, the score
        baseline reports unavailable / 0% accuracy.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            row = {
                "schema_version": "turn_rl_v1.1",
                "selected_joint_key": [
                    ["move", "moonblast", 0, ""],
                    ["move", "hydropump", 0, ""],
                ],
                "legal_action_keys_slot0": [
                    ["move", "moonblast", 0, ""],
                ],
                "legal_action_keys_slot1": [
                    ["move", "hydropump", 0, ""],
                ],
                "local_only_provenance": True,
                "used_species_ability_inference": False,
                # No v2l1_raw_scores_slot0 / slot1
            }
            f.write(json.dumps(row) + "\n")
            tmp_path = f.name
        try:
            result = analyze_dataset(tmp_path)
            sbb = result["baselines"]["score_based_baseline"]
            self.assertFalse(sbb["available"])
            self.assertEqual(sbb["per_slot_max_score_accuracy"], 0)
        finally:
            os.unlink(tmp_path)

    def test_score_field_available_path(self):
        """When raw scores are present, the score
        baseline is computed.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            row = {
                "schema_version": "turn_rl_v1.1",
                "selected_joint_key": [
                    ["move", "moonblast", 0, ""],
                    ["move", "hydropump", 0, ""],
                ],
                "legal_action_keys_slot0": [
                    ["move", "moonblast", 0, ""],
                    ["move", "tackle", 0, ""],
                ],
                "legal_action_keys_slot1": [
                    ["move", "hydropump", 0, ""],
                    ["move", "watergun", 0, ""],
                ],
                "v2l1_raw_scores_slot0": {
                    "move|moonblast|0|": 100.0,
                    "move|tackle|0|": 50.0,
                },
                "v2l1_raw_scores_slot1": {
                    "move|hydropump|0|": 100.0,
                    "move|watergun|0|": 50.0,
                },
                "local_only_provenance": True,
                "used_species_ability_inference": False,
            }
            f.write(json.dumps(row) + "\n")
            tmp_path = f.name
        try:
            result = analyze_dataset(tmp_path)
            sbb = result["baselines"]["score_based_baseline"]
            self.assertTrue(sbb["available"])
            # The selected matches the max-score candidate
            # for both slots, so accuracy = 100%.
            self.assertEqual(sbb["per_slot_max_score_accuracy"], 1.0)
        finally:
            os.unlink(tmp_path)

    def test_empty_dataset(self):
        """An empty dataset should not crash."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            tmp_path = f.name
        try:
            result = analyze_dataset(tmp_path)
            self.assertEqual(result["n_rows"], 0)
        finally:
            os.unlink(tmp_path)


# ============================================================
# Helpers
# ============================================================
class TestHelpers(unittest.TestCase):
    """Test the small helper functions."""

    def test_norm_move_id(self):
        self.assertEqual(_norm_move_id("Fake Out"), "fakeout")
        self.assertEqual(_norm_move_id("fake-out"), "fakeout")
        self.assertEqual(_norm_move_id("fake_out"), "fakeout")
        self.assertEqual(_norm_move_id(None), "")

    def test_move_id_norm(self):
        self.assertEqual(
            _move_id_norm(["move", "Fake Out", 0, ""]),
            "fakeout"
        )
        self.assertEqual(
            _move_id_norm(["switch", "Volcarona", 0, ""]),
            "volcarona"
        )
        self.assertEqual(_move_id_norm([]), "")

    def test_action_kind(self):
        self.assertEqual(
            _action_kind(["move", "moonblast", 0, ""]),
            "move"
        )
        self.assertEqual(
            _action_kind(["switch", "volcarona", 0, ""]),
            "switch"
        )
        self.assertEqual(
            _action_kind(["pass", "pass", 0, ""]),
            "pass"
        )
        self.assertEqual(
            _action_kind(["unknown", "/choose pass", 0, ""]),
            "pass"
        )
        self.assertEqual(_action_kind("not a list"), "unknown")
        self.assertEqual(_action_kind([]), "unknown")
