"""Phase PLANNER-2 — Tests for the intent
classifier and audit field integration.

Validates:
- Move ID normalization
- Intent classification for setup, anti-setup,
  protect, redirect, spread defense, combo,
  damaging, status
- Order classification
- Per-slot and per-move ID handling
- KO_NOW detection
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from bot_doubles_intent_classifier import (
    INTENT_FAMILIES,
    classify_move_intent,
    classify_order_intent,
    get_all_intent_ids,
    _norm,
)


class TestNormalize(unittest.TestCase):
    def test_lowercase(self):
        self.assertEqual(_norm("TAUNT"), "taunt")

    def test_no_spaces(self):
        self.assertEqual(_norm("Swords Dance"), "swordsdance")

    def test_no_dashes(self):
        self.assertEqual(_norm("Trick-Room"), "trickroom")

    def test_no_underscores(self):
        self.assertEqual(_norm("Wide_Guard"), "wideguard")

    def test_no_apostrophes(self):
        self.assertEqual(_norm("King's Shield"), "kingsshield")


class TestClassifyMoveIntent(unittest.TestCase):
    def test_setup_moves(self):
        for mv in ["swordsdance", "nastyplot", "calmmind",
                    "dragondance", "bulkup", "quiverdance",
                    "shellsmash", "workup", "agility"]:
            self.assertEqual(
                classify_move_intent(mv), "SETUP",
                f"{mv} should be SETUP",
            )

    def test_speed_setup(self):
        for mv in ["tailwind", "trickroom"]:
            self.assertEqual(
                classify_move_intent(mv), "SETUP",
                f"{mv} should be SETUP",
            )

    def test_anti_setup_moves(self):
        for mv in ["taunt", "encore", "disable", "quash", "torment"]:
            self.assertEqual(
                classify_move_intent(mv), "ANTI_SETUP",
                f"{mv} should be ANTI_SETUP",
            )

    def test_protect_moves(self):
        for mv in ["protect", "detect", "spikyshield",
                    "kingsshield", "banefulbunker", "silktrap",
                    "burningbulwark"]:
            self.assertEqual(
                classify_move_intent(mv), "PROTECT",
                f"{mv} should be PROTECT",
            )

    def test_redirect_moves(self):
        for mv in ["followme", "ragepowder", "spotlight"]:
            self.assertEqual(
                classify_move_intent(mv), "REDIRECT",
                f"{mv} should be REDIRECT",
            )

    def test_spread_defense_moves(self):
        for mv in ["wideguard", "quickguard", "craftyshield"]:
            self.assertEqual(
                classify_move_intent(mv), "SPREAD_DEFENSE",
                f"{mv} should be SPREAD_DEFENSE",
            )

    def test_combo_moves(self):
        for mv in ["helpinghand", "coaching", "decorate",
                    "haze", "clearsmog", "beatup", "lifedew",
                    "healpulse", "pollenpuff", "allyswitch"]:
            self.assertEqual(
                classify_move_intent(mv), "COMBO",
                f"{mv} should be COMBO",
            )

    def test_damaging_move_with_base_power(self):
        self.assertEqual(
            classify_move_intent(
                "earthquake", base_power=100
            ),
            "DAMAGE",
        )

    def test_ko_now_with_high_damage_pct(self):
        self.assertEqual(
            classify_move_intent(
                "earthquake", base_power=100, damage_pct=0.6
            ),
            "KO_NOW",
        )

    def test_status_move_with_zero_base_power(self):
        self.assertEqual(
            classify_move_intent(
                "spore", base_power=0
            ),
            "STATUS",
        )

    def test_unknown_move_no_base_power(self):
        self.assertEqual(
            classify_move_intent("notarealmove"),
            "UNKNOWN",
        )

    def test_empty_move_id(self):
        self.assertEqual(
            classify_move_intent(""),
            "UNKNOWN",
        )

    def test_none_move_id(self):
        self.assertEqual(
            classify_move_intent(None),
            "UNKNOWN",
        )

    def test_move_name_normalized(self):
        # Mixed case + spaces
        self.assertEqual(
            classify_move_intent("Swords Dance"),
            "SETUP",
        )
        self.assertEqual(
            classify_move_intent("TAUNT"),
            "ANTI_SETUP",
        )
        self.assertEqual(
            classify_move_intent("wide-guard"),
            "SPREAD_DEFENSE",
        )


class TestClassifyOrderIntent(unittest.TestCase):
    def test_none_order(self):
        self.assertEqual(classify_order_intent(None), "UNKNOWN")

    def test_pass_order(self):
        class _Order:
            order = None
        self.assertEqual(classify_order_intent(_Order()), "PASS")

    def test_switch_order(self):
        class _Order:
            class _Pokemon:
                species = "garchomp"
            order = _Pokemon
        self.assertEqual(
            classify_order_intent(_Order()), "SWITCH"
        )

    def test_move_order_setup(self):
        class _Move:
            id = "tailwind"
            base_power = 0
        class _Order:
            order = _Move()
        self.assertEqual(
            classify_order_intent(_Order()), "SETUP"
        )

    def test_move_order_damaging(self):
        class _Move:
            id = "earthquake"
            base_power = 100
        class _Order:
            order = _Move()
        self.assertEqual(
            classify_order_intent(_Order()), "DAMAGE"
        )

    def test_move_order_anti_setup(self):
        class _Move:
            id = "taunt"
            base_power = 0
        class _Order:
            order = _Move()
        self.assertEqual(
            classify_order_intent(_Order()), "ANTI_SETUP"
        )


class TestIntentFamiliesConfig(unittest.TestCase):
    def test_all_families_present(self):
        expected = {
            "SETUP", "ANTI_SETUP", "PROTECT",
            "REDIRECT", "SPREAD_DEFENSE", "COMBO",
        }
        self.assertEqual(
            set(INTENT_FAMILIES.keys()), expected
        )

    def test_get_all_intent_ids(self):
        ids = get_all_intent_ids()
        self.assertIn("DAMAGE", ids)
        self.assertIn("KO_NOW", ids)
        self.assertIn("STATUS", ids)
        self.assertIn("SETUP", ids)
        self.assertIn("ANTI_SETUP", ids)
        self.assertIn("PROTECT", ids)
        self.assertIn("REDIRECT", ids)
        self.assertIn("SPREAD_DEFENSE", ids)
        self.assertIn("COMBO", ids)
        self.assertIn("SWITCH", ids)
        self.assertIn("PASS", ids)


class TestAntiSetupOverlap(unittest.TestCase):
    """Ensure anti-setup moves are not
    mis-classified as setup or vice-versa."""

    def test_taunt_not_setup(self):
        self.assertNotEqual(
            classify_move_intent("taunt"), "SETUP"
        )
        self.assertEqual(
            classify_move_intent("taunt"), "ANTI_SETUP"
        )

    def test_swordsdance_not_anti_setup(self):
        self.assertNotEqual(
            classify_move_intent("swordsdance"),
            "ANTI_SETUP",
        )
        self.assertEqual(
            classify_move_intent("swordsdance"), "SETUP"
        )

    def test_tailwind_is_setup(self):
        # TW is the "speed setup" branch, so
        # it goes to SETUP
        self.assertEqual(
            classify_move_intent("tailwind"), "SETUP"
        )

    def test_trickroom_is_setup(self):
        self.assertEqual(
            classify_move_intent("trickroom"), "SETUP"
        )


class TestProtectOverlap(unittest.TestCase):
    """Ensure protect moves are not
    mis-classified as combo or status."""

    def test_protect_not_status(self):
        self.assertNotEqual(
            classify_move_intent(
                "protect", base_power=0
            ),
            "STATUS",
        )
        self.assertEqual(
            classify_move_intent("protect"), "PROTECT"
        )

    def test_detect_not_combo(self):
        self.assertNotEqual(
            classify_move_intent("detect"), "COMBO"
        )


if __name__ == "__main__":
    unittest.main()
