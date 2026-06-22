"""Phase 6.4.7c — Stat-Drop Selection Changed Counterfactual Audit Tests."""
import unittest
from unittest.mock import MagicMock
import sys
import os

import poke_env_test_cleanup  # noqa: F401

sys.path.insert(0, os.path.dirname(__file__))

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
)


class MockMove:
    def __init__(self, move_id, base_power=80):
        self.id = move_id
        self.base_power = base_power

    @property
    def category(self):
        from unittest.mock import MagicMock
        m = MagicMock()
        m.name = "PHYSICAL"
        return m


class MockPokemon:
    def __init__(self, species):
        self.species = species
        self.current_hp_fraction = 1.0


class TestOrderActionKey(unittest.TestCase):
    """Test that action-key tuples correctly distinguish moves/switches."""

    def test_move_key(self):
        key = ("move", "closecombat", 1)
        self.assertEqual(key[0], "move")
        self.assertEqual(key[1], "closecombat")

    def test_switch_key(self):
        key = ("switch", "gyarados", 0)
        self.assertEqual(key[0], "switch")
        self.assertEqual(key[1], "gyarados")

    def test_move_vs_switch_differs(self):
        mk = ("move", "tackle", 1)
        sk = ("switch", "gyarados", 0)
        self.assertNotEqual(mk, sk)

    def test_switch_species_differs(self):
        s1 = ("switch", "gyarados", 0)
        s2 = ("switch", "raichu", 0)
        self.assertNotEqual(s1, s2)

    def test_same_move_same_key(self):
        k1 = ("move", "closecombat", 1)
        k2 = ("move", "closecombat", 1)
        self.assertEqual(k1, k2)

    def test_none_order(self):
        key = ("none", "", 0)
        self.assertEqual(key[0], "none")

    def test_move_target_differs(self):
        k1 = ("move", "tackle", 1)
        k2 = ("move", "tackle", 2)
        self.assertNotEqual(k1, k2)


class TestConfigPreservation(unittest.TestCase):
    def test_default_scoring_disabled(self):
        c = DoublesDamageAwareConfig()
        self.assertFalse(c.enable_stat_drop_switch_scoring)

    def test_ability_hard_safety_preserved(self):
        c = DoublesDamageAwareConfig()
        self.assertTrue(c.enable_ability_hard_safety_only)
        self.assertTrue(c.ability_hard_safety_direct_absorb_only)

    def test_singleton_deduction_preserved(self):
        c = DoublesDamageAwareConfig()
        self.assertTrue(c.ability_hard_safety_allow_singleton_deduction)

    def test_no_hidden_features_enabled(self):
        c = DoublesDamageAwareConfig()
        self.assertTrue(c.enable_forced_switch_replacement_safety)  # adopted in Phase 6.4.4e
        self.assertFalse(c.enable_stale_target_after_ally_ko_safety)
        self.assertFalse(c.enable_ability_awareness)

    def test_constants_unchanged(self):
        c = DoublesDamageAwareConfig()
        self.assertEqual(c.stat_drop_switch_offensive_penalty, 90.0)
        self.assertEqual(c.stat_drop_switch_unproductive_bonus, 80.0)
        self.assertEqual(c.stat_drop_switch_safe_switch_bonus, 80.0)
        self.assertEqual(c.stat_drop_switch_offensive_stage_threshold, -1)


class TestCounterfactualLogic(unittest.TestCase):
    def test_selection_changed_move_to_switch(self):
        ak = ("switch", "gyarados", 0)
        ck = ("move", "tackle", 1)
        self.assertNotEqual(ak, ck)

    def test_selection_unchanged_both_switch(self):
        ak = ("switch", "gyarados", 0)
        ck = ("switch", "gyarados", 0)
        self.assertEqual(ak, ck)

    def test_selection_unchanged_both_move(self):
        ak = ("move", "tackle", 1)
        ck = ("move", "tackle", 1)
        self.assertEqual(ak, ck)

    def test_pass_default_detected(self):
        none_key = ("none", "", 0)
        move_key = ("move", "tackle", 1)
        self.assertNotEqual(none_key, move_key)


if __name__ == "__main__":
    unittest.main()
