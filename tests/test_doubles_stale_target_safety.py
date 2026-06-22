"""Phase 6.4.5 — Stale Target / Retarget Immunity Safety Tests.

Tests for stale target detection after ally KO: when both our slots target
the same opponent and the first (faster) action is expected to KO, the
second action may resolve into a no-effect or type-immune fallback target.
"""
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

import poke_env_test_cleanup  # noqa: F401

sys.path.insert(0, os.path.dirname(__file__))

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    is_type_immune,
    detect_stale_target_after_ally_ko_risk,
)


class MockMove:
    def __init__(self, move_id, move_type, base_power=80, category_name="PHYSICAL"):
        self.id = move_id.lower().replace(" ", "")
        self.base_power = base_power
        self._type = move_type
        self._category_name = category_name

    @property
    def type(self):
        m = MagicMock()
        m.name = self._type
        return m

    @property
    def category(self):
        m = MagicMock()
        m.name = self._category_name
        return m


class MockPokemon:
    def __init__(self, species, types, ability=None, hp_fraction=1.0):
        self.species = species
        self.types = []
        for t in types:
            m = MagicMock()
            m.name = t
            self.types.append(m)
        self._ability = ability
        self.fainted = False
        self._current_hp_fraction = hp_fraction

    @property
    def current_hp_fraction(self):
        return self._current_hp_fraction

    @current_hp_fraction.setter
    def current_hp_fraction(self, val):
        self._current_hp_fraction = val

    @property
    def type_1(self):
        return self.types[0] if self.types else None

    @property
    def type_2(self):
        return self.types[1] if len(self.types) > 1 else None

    @property
    def ability(self):
        return self._ability

    @property
    def damage_multiplier(self):
        return 1.0


class MockOrder:
    def __init__(self, order_obj, move_target):
        self.order = order_obj
        self.move_target = move_target


class MockBattle:
    def __init__(self, active_pokemon, opponent_active_pokemon, fields=None):
        self.active_pokemon = active_pokemon
        self.opponent_active_pokemon = opponent_active_pokemon
        self.fields = fields or []


class TestIsTypeImmune(unittest.TestCase):
    """Test basic type immunity checks used by stale target detection."""

    def test_fighting_into_sableye_dark_ghost(self):
        """Fighting moves are immune against Dark/Ghost Sableye."""
        move = MockMove("closecombat", "FIGHTING")
        target = MockPokemon("sableye", ["DARK", "GHOST"])
        immune, reason = is_type_immune(move, None, target)
        self.assertTrue(immune, f"Fighting should be immune vs Dark/Ghost, got reason={reason}")

    def test_body_press_is_fighting(self):
        """Body Press is a Fighting-type move for immunity checks."""
        move = MockMove("bodypress", "FIGHTING")
        target = MockPokemon("sableye", ["DARK", "GHOST"])
        immune, reason = is_type_immune(move, None, target)
        self.assertTrue(immune, f"Body Press (Fighting) should be immune vs Dark/Ghost")

    def test_fighting_not_immune_into_normal(self):
        """Fighting moves are not immune against Normal types."""
        move = MockMove("closecombat", "FIGHTING")
        target = MockPokemon("snorlax", ["NORMAL"])
        immune, _ = is_type_immune(move, None, target)
        self.assertFalse(immune)

    def test_normal_into_ghost(self):
        """Normal moves are immune against Ghost types."""
        move = MockMove("tacklenormal", "NORMAL")
        target = MockPokemon("gengar", ["GHOST", "POISON"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)

    def test_ground_into_flying(self):
        """Ground moves are immune against Flying types."""
        move = MockMove("earthquake", "GROUND")
        target = MockPokemon("tornadus", ["FLYING"])
        immune, _ = is_type_immune(move, None, target)
        self.assertTrue(immune)


class TestDetectStaleTargetRisk(unittest.TestCase):
    """Test the detect_stale_target_after_ally_ko_risk helper."""

    def _make_mock_battle(self, opp1, opp2):
        return MockBattle(
            active_pokemon=[
                MockPokemon("mienshao", ["FIGHTING"]),
                MockPokemon("bastiodon", ["ROCK", "STEEL"]),
            ],
            opponent_active_pokemon=[opp1, opp2],
        )

    def _make_damaging_order(self, move_id, move_type, target_pos):
        move = MockMove(move_id, move_type, base_power=120)
        return MockOrder(move, target_pos)

    def test_same_target_ko_detected(self):
        """Same-target joint order where first action expected KOs target is detected."""
        abomasnow = MockPokemon("abomasnow", ["GRASS", "ICE"], hp_fraction=0.3)
        sableye = MockPokemon("sableye", ["DARK", "GHOST"])
        battle = self._make_mock_battle(abomasnow, sableye)

        first = self._make_damaging_order("closecombat", "FIGHTING", 1)
        second = self._make_damaging_order("bodypress", "FIGHTING", 1)

        result = detect_stale_target_after_ally_ko_risk(
            first, second, True, abomasnow, abomasnow,
            battle.opponent_active_pokemon, battle=battle,
        )

        self.assertTrue(result["risk"], f"Expected risk=True, got {result}")
        self.assertEqual(result["first_target_species"], "abomasnow")
        self.assertEqual(result["second_target_species"], "abomasnow")

    def test_same_target_no_ko_not_detected(self):
        """Same-target joint order where first action does NOT KO is not detected."""
        abomasnow = MockPokemon("abomasnow", ["GRASS", "ICE"], hp_fraction=1.0)
        sableye = MockPokemon("sableye", ["DARK", "GHOST"])
        battle = self._make_mock_battle(abomasnow, sableye)

        first = self._make_damaging_order("closecombat", "FIGHTING", 1)
        second = self._make_damaging_order("bodypress", "FIGHTING", 1)

        result = detect_stale_target_after_ally_ko_risk(
            first, second, False, abomasnow, abomasnow,
            battle.opponent_active_pokemon, battle=battle,
        )

        self.assertFalse(result["risk"], f"Should not detect risk without expected KO, got {result}")

    def test_different_targets_not_detected(self):
        """Different targets are not detected as stale target risk."""
        abomasnow = MockPokemon("abomasnow", ["GRASS", "ICE"], hp_fraction=0.3)
        sableye = MockPokemon("sableye", ["DARK", "GHOST"])
        battle = self._make_mock_battle(abomasnow, sableye)

        first = self._make_damaging_order("closecombat", "FIGHTING", 1)
        second = self._make_damaging_order("stoneedge", "ROCK", 2)

        result = detect_stale_target_after_ally_ko_risk(
            first, second, True, abomasnow, sableye,
            battle.opponent_active_pokemon, battle=battle,
        )

        self.assertFalse(result["risk"], f"Different targets should not trigger risk, got {result}")

    def test_fallback_type_immune_detected(self):
        """If fallback opponent is Ghost and second move is Fighting, type-immune risk detected."""
        abomasnow = MockPokemon("abomasnow", ["GRASS", "ICE"], hp_fraction=0.3)
        sableye = MockPokemon("sableye", ["DARK", "GHOST"])
        battle = self._make_mock_battle(abomasnow, sableye)

        first = self._make_damaging_order("closecombat", "FIGHTING", 1)
        second = self._make_damaging_order("bodypress", "FIGHTING", 1)

        result = detect_stale_target_after_ally_ko_risk(
            first, second, True, abomasnow, abomasnow,
            battle.opponent_active_pokemon, battle=battle,
        )

        self.assertTrue(result["risk"])
        self.assertTrue(result["fallback_target_type_immune"],
                        f"Fallback Sableye (Dark/Ghost) should be immune to Fighting")
        self.assertEqual(result["fallback_target_species"], "sableye")
        self.assertIn("type_immune", result.get("reason", ""))

    def test_no_fallback_target_no_effect(self):
        """If no fallback target exists, no-effect risk is detected."""
        abomasnow = MockPokemon("abomasnow", ["GRASS", "ICE"], hp_fraction=0.3)
        battle = MockBattle(
            active_pokemon=[
                MockPokemon("mienshao", ["FIGHTING"]),
                MockPokemon("bastiodon", ["ROCK", "STEEL"]),
            ],
            opponent_active_pokemon=[abomasnow, None],
        )

        first = self._make_damaging_order("closecombat", "FIGHTING", 1)
        second = self._make_damaging_order("bodypress", "FIGHTING", 1)

        result = detect_stale_target_after_ally_ko_risk(
            first, second, True, abomasnow, abomasnow,
            battle.opponent_active_pokemon, battle=battle,
        )

        self.assertTrue(result["risk"])
        self.assertTrue(result["fallback_target_no_effect"],
                        "No fallback target should mean no-effect")
        self.assertEqual(result.get("reason", ""), "no_fallback_target_after_ally_ko")

    def test_non_damaging_second_move_not_detected(self):
        """Status/support second move is not penalized (base_power <= 0)."""
        abomasnow = MockPokemon("abomasnow", ["GRASS", "ICE"], hp_fraction=0.3)
        sableye = MockPokemon("sableye", ["DARK", "GHOST"])
        battle = self._make_mock_battle(abomasnow, sableye)

        first = self._make_damaging_order("closecombat", "FIGHTING", 1)
        status_move = MockMove("spore", "GRASS", base_power=0, category_name="STATUS")
        second = MockOrder(status_move, 1)

        result = detect_stale_target_after_ally_ko_risk(
            first, second, True, abomasnow, abomasnow,
            battle.opponent_active_pokemon, battle=battle,
        )

        self.assertFalse(result["risk"], f"Status move should not trigger risk, got {result}")

    def test_not_both_damaging_not_detected(self):
        """Non-damaging first move should not trigger risk."""
        abomasnow = MockPokemon("abomasnow", ["GRASS", "ICE"], hp_fraction=0.3)
        sableye = MockPokemon("sableye", ["DARK", "GHOST"])
        battle = self._make_mock_battle(abomasnow, sableye)

        status_move = MockMove("spore", "GRASS", base_power=0, category_name="STATUS")
        first = MockOrder(status_move, 1)
        second = self._make_damaging_order("bodypress", "FIGHTING", 1)

        result = detect_stale_target_after_ally_ko_risk(
            first, second, True, abomasnow, abomasnow,
            battle.opponent_active_pokemon, battle=battle,
        )

        self.assertFalse(result["risk"], f"Non-damaging first move should not trigger risk")

    def test_fallback_not_immune_not_type_immune(self):
        """If fallback is not immune to second move, no type-immune flag."""
        abomasnow = MockPokemon("abomasnow", ["GRASS", "ICE"], hp_fraction=0.3)
        landorus = MockPokemon("landorus", ["GROUND", "FLYING"])
        battle = self._make_mock_battle(abomasnow, landorus)

        first = self._make_damaging_order("closecombat", "FIGHTING", 1)
        second = self._make_damaging_order("stoneedge", "ROCK", 1)

        result = detect_stale_target_after_ally_ko_risk(
            first, second, True, abomasnow, abomasnow,
            battle.opponent_active_pokemon, battle=battle,
        )

        self.assertTrue(result["risk"], "Risk should be detected")
        self.assertFalse(result["fallback_target_type_immune"],
                         "Rock into Landorus (Ground/Flying) is not type-immune")
        self.assertFalse(result["fallback_target_no_effect"],
                         "Fallback target exists so no-effect should be false")

    def test_result_fields_populated(self):
        """Result dict contains all required fields."""
        abomasnow = MockPokemon("abomasnow", ["GRASS", "ICE"], hp_fraction=0.3)
        sableye = MockPokemon("sableye", ["DARK", "GHOST"])
        battle = self._make_mock_battle(abomasnow, sableye)

        first = self._make_damaging_order("closecombat", "FIGHTING", 1)
        second = self._make_damaging_order("bodypress", "FIGHTING", 1)

        result = detect_stale_target_after_ally_ko_risk(
            first, second, True, abomasnow, abomasnow,
            battle.opponent_active_pokemon, battle=battle,
        )

        expected_fields = [
            "risk", "reason", "fallback_target_species",
            "fallback_target_type_immune", "fallback_target_no_effect",
            "first_move_id", "second_move_id",
            "first_target_species", "second_target_species",
        ]
        for field in expected_fields:
            self.assertIn(field, result, f"Missing field {field}")

        self.assertTrue(result["risk"])
        self.assertNotEqual(result["first_move_id"], "")
        self.assertNotEqual(result["second_move_id"], "")

    def test_no_targets_none(self):
        """None targets should return safe."""
        battle = self._make_mock_battle(
            MockPokemon("abomasnow", ["GRASS", "ICE"]),
            MockPokemon("sableye", ["DARK", "GHOST"]),
        )

        first = self._make_damaging_order("closecombat", "FIGHTING", 1)
        second = self._make_damaging_order("bodypress", "FIGHTING", 1)

        result = detect_stale_target_after_ally_ko_risk(
            first, second, True, None, None,
            battle.opponent_active_pokemon, battle=battle,
        )

        self.assertFalse(result["risk"], "None targets should not trigger risk")


class TestConfigDefaults(unittest.TestCase):
    """Test that config defaults are correct."""

    def test_default_enable_stale_target_false(self):
        """enable_stale_target_after_ally_ko_safety defaults to False."""
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_stale_target_after_ally_ko_safety)

    def test_default_penalty_values(self):
        """Default penalty values are as specified."""
        config = DoublesDamageAwareConfig()
        self.assertEqual(config.stale_target_after_ally_ko_penalty, 120.0)
        self.assertEqual(config.stale_target_type_immune_penalty, 250.0)

    def test_default_ability_awareness_false(self):
        """Full ability awareness remains disabled."""
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_ability_awareness)


class TestNoHiddenInfo(unittest.TestCase):
    """Verify no hidden info is used in stale target detection."""

    def test_no_ability_prediction_in_detect(self):
        """detect_stale_target_after_ally_ko_risk does not reference possible_abilities."""
        import inspect
        source = inspect.getsource(detect_stale_target_after_ally_ko_risk)
        self.assertNotIn("possible_abilities", source,
                         "Stale target detection should not use possible_abilities (hidden info)")

    def test_no_species_inference_in_detect(self):
        """detect_stale_target_after_ally_ko_risk does not use species data to infer moves."""
        import inspect
        source = inspect.getsource(detect_stale_target_after_ally_ko_risk)
        self.assertNotIn("meta_engine", source,
                         "Stale target detection should not use meta engine")
        self.assertNotIn("random_set_engine", source,
                         "Stale target detection should not use random set engine")


if __name__ == "__main__":
    unittest.main()
