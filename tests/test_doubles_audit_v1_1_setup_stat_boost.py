"""Phase RL-DATA-3c — Tests for setup_stat_boost inventory group.

Validates that the SUPPORT-AUDIT-1 inventory extension
(setup / stat-boost moves) classifies the new moves
correctly and does not regress existing behavior.

Coverage:
- ``quiverdance`` is classified as
  ``setup_stat_boost``, not ``unknown_needs_probe``.
- ``swordsdance`` / ``nastyplot`` / ``dragondance`` /
  ``calmmind`` / ``bulkup`` classify as
  ``setup_stat_boost``.
- Known setup moves are not treated as damaging
  (they have ``base_power=0`` and are status).
- True unknown support move still becomes
  ``unknown_needs_probe``.
- The static fallback table in
  ``doubles_engine.move_metadata`` has the new
  setup moves.
- The new group is included in
  ``ALL_SUPPORT_GROUPS``.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from doubles_engine.move_metadata import (  # noqa: E402
    _FALLBACK_MOVE_METADATA,
)
from doubles_engine.support_targets import (  # noqa: E402
    ALL_SUPPORT_GROUPS,
    GROUP_SETUP_STAT_BOOST,
    STATUS_NO_POSITIVE_STRATEGY,
    classify_support_move_for_dataset,
)


# ============================================================
# Setup / stat-boost inventory
# ============================================================
class TestSetupStatBoostInventory(unittest.TestCase):
    """Verify setup / stat-boost moves are in the
    inventory and classify correctly.
    """

    def test_setup_stat_boost_group_in_all_groups(self):
        self.assertIn(GROUP_SETUP_STAT_BOOST, ALL_SUPPORT_GROUPS)
        # 10 groups total now (was 9).
        self.assertEqual(len(ALL_SUPPORT_GROUPS), 10)

    def test_quiverdance_is_setup_stat_boost(self):
        r = classify_support_move_for_dataset("quiverdance")
        self.assertEqual(r["support_group"], GROUP_SETUP_STAT_BOOST)
        self.assertEqual(
            r["support_status_from_audit"],
            STATUS_NO_POSITIVE_STRATEGY,
        )
        self.assertTrue(r["is_support_move"])
        self.assertFalse(r["unknown_support_move_detected"])
        # Safety / positive strategy semantics.
        self.assertTrue(r["safety_only"])
        self.assertFalse(r["positive_strategy_known"])
        self.assertIsNone(r["opt_in_flag_required"])
        self.assertTrue(r["default_enabled"])

    def test_swordsdance_is_setup_stat_boost(self):
        r = classify_support_move_for_dataset("swordsdance")
        self.assertEqual(r["support_group"], GROUP_SETUP_STAT_BOOST)
        self.assertTrue(r["is_support_move"])
        self.assertFalse(r["unknown_support_move_detected"])

    def test_nastyplot_is_setup_stat_boost(self):
        r = classify_support_move_for_dataset("nastyplot")
        self.assertEqual(r["support_group"], GROUP_SETUP_STAT_BOOST)
        self.assertTrue(r["is_support_move"])
        self.assertFalse(r["unknown_support_move_detected"])

    def test_dragondance_is_setup_stat_boost(self):
        r = classify_support_move_for_dataset("dragondance")
        self.assertEqual(r["support_group"], GROUP_SETUP_STAT_BOOST)
        self.assertTrue(r["is_support_move"])
        self.assertFalse(r["unknown_support_move_detected"])

    def test_calmmind_is_setup_stat_boost(self):
        r = classify_support_move_for_dataset("calmmind")
        self.assertEqual(r["support_group"], GROUP_SETUP_STAT_BOOST)
        self.assertTrue(r["is_support_move"])
        self.assertFalse(r["unknown_support_move_detected"])

    def test_bulkup_is_setup_stat_boost(self):
        r = classify_support_move_for_dataset("bulkup")
        self.assertEqual(r["support_group"], GROUP_SETUP_STAT_BOOST)
        self.assertTrue(r["is_support_move"])
        self.assertFalse(r["unknown_support_move_detected"])

    def test_other_setup_moves_in_inventory(self):
        for mid in (
            "irondefense", "amnesia", "agility", "shellsmash",
            "bellydrum", "growth", "workup", "curse",
            "cosmicpower", "coil", "honeclaws", "autotomize",
            "rockpolish", "shiftgear", "tailglow", "geomancy",
            "victorydance", "clangeroussoul", "tidyup",
            "substitute",
        ):
            r = classify_support_move_for_dataset(mid)
            self.assertEqual(
                r["support_group"],
                GROUP_SETUP_STAT_BOOST,
                f"{mid} should be setup_stat_boost, got {r['support_group']}",
            )
            self.assertTrue(
                r["is_support_move"],
                f"{mid} should be a support move",
            )
            self.assertFalse(
                r["unknown_support_move_detected"],
                f"{mid} should not be unknown",
            )

    def test_normalization(self):
        # Spaces, dashes, underscores
        for variant in (
            "Quiver Dance", "quiver-dance", "quiver_dance",
        ):
            r = classify_support_move_for_dataset(variant)
            self.assertEqual(r["support_group"], GROUP_SETUP_STAT_BOOST)


class TestSetupStatBoostFallbackMetadata(unittest.TestCase):
    """Verify the static fallback table in
    ``doubles_engine.move_metadata`` has the new
    setup moves with correct base_power / category.
    """

    def test_quiverdance_in_fallback(self):
        self.assertIn("quiverdance", _FALLBACK_MOVE_METADATA)
        bp, cat = _FALLBACK_MOVE_METADATA["quiverdance"]
        self.assertEqual(bp, 0)
        self.assertEqual(cat, "status")

    def test_all_setup_moves_in_fallback(self):
        for mid in (
            "quiverdance", "swordsdance", "nastyplot",
            "dragondance", "calmmind", "bulkup",
            "irondefense", "amnesia", "agility",
            "shellsmash", "bellydrum", "growth",
            "workup", "curse", "cosmicpower", "coil",
            "honeclaws", "autotomize", "rockpolish",
            "shiftgear", "tailglow", "geomancy",
            "victorydance", "clangeroussoul", "tidyup",
            "substitute",
        ):
            self.assertIn(
                mid, _FALLBACK_MOVE_METADATA,
                f"missing {mid} in fallback",
            )
            bp, cat = _FALLBACK_MOVE_METADATA[mid]
            self.assertEqual(bp, 0, f"{mid} should have base_power=0")
            self.assertEqual(
                cat, "status",
                f"{mid} should be status",
            )


class TestSetupStatBoostWithMetadata(unittest.TestCase):
    """Verify the classifier uses metadata correctly
    for setup moves.
    """

    def test_quiverdance_with_metadata_is_setup(self):
        r = classify_support_move_for_dataset(
            "quiverdance", base_power=0, category="status"
        )
        self.assertEqual(r["support_group"], GROUP_SETUP_STAT_BOOST)
        self.assertTrue(r["is_support_move"])
        self.assertFalse(r["unknown_support_move_detected"])

    def test_quiverdance_with_damaging_metadata_is_damage_like(self):
        # The classifier checks base_power > 0 BEFORE
        # checking the inventory. So a setup move
        # with base_power > 0 is treated as damage-like
        # (the conservative behavior). This is correct:
        # the classifier should not trust the inventory
        # over the actual metadata.
        r = classify_support_move_for_dataset(
            "quiverdance", base_power=80, category="special"
        )
        self.assertIsNone(r["support_group"])
        self.assertFalse(r["is_support_move"])
        self.assertFalse(r["unknown_support_move_detected"])

    def test_true_unknown_support_move_still_unknown(self):
        # A non-damaging move not in the inventory
        # is still unknown.
        r = classify_support_move_for_dataset(
            "newgensupportmove", base_power=0, category="status"
        )
        self.assertEqual(r["support_group"], "unknown_needs_probe")
        self.assertTrue(r["is_support_move"])
        self.assertTrue(r["unknown_support_move_detected"])

    def test_known_damaging_move_still_damage_like(self):
        r = classify_support_move_for_dataset(
            "fakeout", base_power=40, category="physical"
        )
        self.assertFalse(r["is_support_move"])
        self.assertFalse(r["unknown_support_move_detected"])


class TestSetupStatBoostNoRegression(unittest.TestCase):
    """Verify the inventory extension does not
    regress existing behavior.
    """

    def test_protect_still_protection(self):
        r = classify_support_move_for_dataset("protect")
        self.assertEqual(
            r["support_group"],
            "protection_defensive_support",
        )

    def test_raindance_still_weather_terrain(self):
        r = classify_support_move_for_dataset("raindance")
        self.assertEqual(r["support_group"], "weather_terrain")

    def test_taunt_still_anti_setup(self):
        r = classify_support_move_for_dataset("taunt")
        self.assertEqual(
            r["support_group"],
            "anti_setup_disruption",
        )

    def test_healpulse_still_healing(self):
        r = classify_support_move_for_dataset("healpulse")
        self.assertEqual(
            r["support_group"],
            "healing_buff_ally_support",
        )
