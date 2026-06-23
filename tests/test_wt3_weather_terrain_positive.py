"""Tests for Phase WT-3 Weather/Terrain positive scoring.

These tests cover:

* Helper-level logic (move classification, weather/
  terrain state detection, synergy scoring).
* Master flag behavior (OFF = no bonus, ON = bonus
  applied).
* Redundant setter prevention (no bonus if weather/
  terrain already active).
* Opponent-benefit penalty (no bonus if opponent
  benefits more).
* Conservative signal coverage (rain with own Water
  attacker, sun with own Fire attacker, etc.).
* No species-based ability inference.
* No Magic Bounce species inference.
* Target legality / hard safety preserved.

These tests do NOT spawn battles. They use unit-level
fixtures and mock the battle state.
"""

import os
import sys
import unittest
from typing import Any, Optional
from unittest.mock import MagicMock

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "showdown_ai"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analyze"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "inspect"))


# ---- Helper / state detection tests ----
class TestIsWt3SetterMove(unittest.TestCase):
    def test_weather_setters(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            is_wt3_setter_move,
        )
        self.assertTrue(is_wt3_setter_move("raindance"))
        self.assertTrue(is_wt3_setter_move("sunnyday"))
        self.assertTrue(is_wt3_setter_move("sandstorm"))
        self.assertTrue(is_wt3_setter_move("snowscape"))
        self.assertTrue(is_wt3_setter_move("hail"))

    def test_terrain_setters(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            is_wt3_setter_move,
        )
        self.assertTrue(is_wt3_setter_move("electricterrain"))
        self.assertTrue(is_wt3_setter_move("grassyterrain"))
        self.assertTrue(is_wt3_setter_move("mistyterrain"))
        self.assertTrue(is_wt3_setter_move("psychicterrain"))

    def test_non_setters(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            is_wt3_setter_move,
        )
        self.assertFalse(is_wt3_setter_move("tackle"))
        self.assertFalse(is_wt3_setter_move("protect"))
        self.assertFalse(is_wt3_setter_move("tailwind"))
        self.assertFalse(is_wt3_setter_move("trickroom"))

    def test_normalized_inputs(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            is_wt3_setter_move,
        )
        # Normalization strips spaces/dashes/underscores
        self.assertTrue(is_wt3_setter_move("Rain Dance"))
        self.assertTrue(is_wt3_setter_move("rain-dance"))
        self.assertTrue(is_wt3_setter_move("RAIN_DANCE"))


class TestGetActiveWeather(unittest.TestCase):
    def test_no_weather(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_weather,
        )
        battle = MagicMock()
        battle.weather = None
        self.assertIsNone(get_active_weather(battle))

    def test_rain_active(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_weather, RAIN_DANCE,
        )
        battle = MagicMock()
        battle.weather = MagicMock()
        battle.weather.__str__ = lambda self: "RAIN"
        self.assertEqual(get_active_weather(battle), RAIN_DANCE)

    def test_sun_active(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_weather, SUNNY_DAY,
        )
        battle = MagicMock()
        battle.weather = MagicMock()
        battle.weather.__str__ = lambda self: "SUN"
        self.assertEqual(get_active_weather(battle), SUNNY_DAY)

    def test_sandstorm_active(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_weather, SANDSTORM,
        )
        battle = MagicMock()
        battle.weather = MagicMock()
        battle.weather.__str__ = lambda self: "SANDSTORM"
        self.assertEqual(get_active_weather(battle), SANDSTORM)

    def test_snowscape_active(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_weather, SNOWSCAPE,
        )
        battle = MagicMock()
        battle.weather = MagicMock()
        battle.weather.__str__ = lambda self: "SNOWSCAPE"
        self.assertEqual(get_active_weather(battle), SNOWSCAPE)

    def test_hail_active(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_weather, HAIL,
        )
        battle = MagicMock()
        battle.weather = MagicMock()
        battle.weather.__str__ = lambda self: "HAIL"
        self.assertEqual(get_active_weather(battle), HAIL)

    def test_no_battle(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_weather,
        )
        self.assertIsNone(get_active_weather(None))

    def test_unknown_weather(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_weather,
        )
        battle = MagicMock()
        battle.weather = MagicMock()
        battle.weather.__str__ = lambda self: "FOG"  # not handled
        self.assertIsNone(get_active_weather(battle))


class TestGetActiveTerrain(unittest.TestCase):
    def test_no_terrain(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_terrain,
        )
        battle = MagicMock()
        battle.fields = None
        self.assertIsNone(get_active_terrain(battle))

    def test_empty_fields(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_terrain,
        )
        battle = MagicMock()
        battle.fields = []
        self.assertIsNone(get_active_terrain(battle))

    def test_electric_terrain(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_terrain, ELECTRIC_TERRAIN,
        )
        battle = MagicMock()
        f = MagicMock()
        f.__str__ = lambda self: "ELECTRIC_TERRAIN"
        battle.fields = [f]
        self.assertEqual(
            get_active_terrain(battle), ELECTRIC_TERRAIN
        )

    def test_grassy_terrain(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_terrain, GRASSY_TERRAIN,
        )
        battle = MagicMock()
        f = MagicMock()
        f.__str__ = lambda self: "GRASSY_TERRAIN"
        battle.fields = [f]
        self.assertEqual(
            get_active_terrain(battle), GRASSY_TERRAIN
        )

    def test_misty_terrain(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_terrain, MISTY_TERRAIN,
        )
        battle = MagicMock()
        f = MagicMock()
        f.__str__ = lambda self: "MISTY_TERRAIN"
        battle.fields = [f]
        self.assertEqual(
            get_active_terrain(battle), MISTY_TERRAIN
        )

    def test_psychic_terrain(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_terrain, PSYCHIC_TERRAIN,
        )
        battle = MagicMock()
        f = MagicMock()
        f.__str__ = lambda self: "PSYCHIC_TERRAIN"
        battle.fields = [f]
        self.assertEqual(
            get_active_terrain(battle), PSYCHIC_TERRAIN
        )

    def test_no_battle(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_terrain,
        )
        self.assertIsNone(get_active_terrain(None))


# ---- Flag behavior tests ----
class TestFlagOffNoBonus(unittest.TestCase):
    def test_flag_off_no_bonus_rain(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        # Even with strong own synergy, flag OFF = 0
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = False
        # Build a minimal battle with a Water-type
        # move available
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        # Build a Rain Dance order
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "raindance"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 0.0)
        self.assertEqual(reason, "")


class TestFlagOnWithSynergy(unittest.TestCase):
    def _make_battle_with_water_user(self):
        """Build a battle where our active slot 0 has
        revealed Water-type moves.
        """
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        # Our active at slot 0 has Surf and Hydro Pump
        surf = MagicMock()
        surf.id = "surf"
        hydro = MagicMock()
        hydro.id = "hydropump"
        battle.available_moves = [[surf, hydro], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["water"]
        battle.active_pokemon[1].types = ["water"]
        return battle

    def _make_rain_dance_order(self):
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "raindance"
        return order

    def test_rain_with_water_user_gets_bonus(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = self._make_battle_with_water_user()
        order = self._make_rain_dance_order()
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 150.0)
        self.assertIn("rain", reason.lower())

    def test_rain_with_thunder_user_gets_bonus(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        thunder = MagicMock()
        thunder.id = "thunder"
        battle.available_moves = [[thunder], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["water"]
        battle.active_pokemon[1].types = ["water"]
        order = self._make_rain_dance_order()
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 150.0)


class TestSunBonus(unittest.TestCase):
    def _make_battle_with_fire_user(self):
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        flareblitz = MagicMock()
        flareblitz.id = "flareblitz"
        fireblast = MagicMock()
        fireblast.id = "fireblast"
        battle.available_moves = [[flareblitz, fireblast], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["fire"]
        battle.active_pokemon[1].types = ["fire"]
        return battle

    def _make_sunny_day_order(self):
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "sunnyday"
        return order

    def test_sun_with_fire_user_gets_bonus(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = self._make_battle_with_fire_user()
        order = self._make_sunny_day_order()
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 150.0)
        self.assertIn("sun", reason.lower())


class TestSandBonus(unittest.TestCase):
    def _make_battle_with_rock_ground_steel(self):
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["rock"]
        battle.active_pokemon[1].types = ["ground"]
        return battle

    def _make_sandstorm_order(self):
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "sandstorm"
        return order

    def test_sand_with_rock_ground_user_gets_bonus(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = self._make_battle_with_rock_ground_steel()
        order = self._make_sandstorm_order()
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 150.0)
        self.assertIn("sand", reason.lower())


class TestSnowBonus(unittest.TestCase):
    def _make_battle_with_ice_user(self):
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["ice"]
        battle.active_pokemon[1].types = ["ice"]
        return battle

    def _make_snowscape_order(self):
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "snowscape"
        return order

    def test_snow_with_ice_user_gets_bonus(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = self._make_battle_with_ice_user()
        order = self._make_snowscape_order()
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 150.0)
        self.assertIn("snow", reason.lower())


class TestElectricTerrainBonus(unittest.TestCase):
    def _make_battle_with_electric_user(self):
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        thunderbolt = MagicMock()
        thunderbolt.id = "thunderbolt"
        battle.available_moves = [[thunderbolt], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["electric"]
        battle.active_pokemon[1].types = ["electric"]
        return battle

    def _make_electric_terrain_order(self):
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "electricterrain"
        return order

    def test_electric_terrain_with_electric_user_gets_bonus(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = self._make_battle_with_electric_user()
        order = self._make_electric_terrain_order()
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 120.0)
        self.assertIn("terrain", reason.lower())


class TestGrassyTerrainBonus(unittest.TestCase):
    def _make_battle_with_grass_user(self):
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        energyball = MagicMock()
        energyball.id = "energyball"
        battle.available_moves = [[energyball], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["grass"]
        battle.active_pokemon[1].types = ["grass"]
        return battle

    def _make_grassy_terrain_order(self):
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "grassyterrain"
        return order

    def test_grassy_terrain_with_grass_user_gets_bonus(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = self._make_battle_with_grass_user()
        order = self._make_grassy_terrain_order()
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 120.0)
        self.assertIn("terrain", reason.lower())


# ---- Redundant setter prevention tests ----
class TestRedundantSetterPrevention(unittest.TestCase):
    def _build_battle_with_weather(self, weather_str):
        battle = MagicMock()
        battle.weather = MagicMock()
        battle.weather.__str__ = lambda self: weather_str
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        surf = MagicMock()
        surf.id = "surf"
        battle.available_moves = [[surf], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["water"]
        battle.active_pokemon[1].types = ["water"]
        return battle

    def test_rain_already_active_no_bonus(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = self._build_battle_with_weather("RAIN")
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "raindance"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 0.0)
        self.assertIn("redundant", reason.lower())

    def test_sun_already_active_no_bonus(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = MagicMock()
        battle.weather = MagicMock()
        battle.weather.__str__ = lambda self: "SUN"
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        flareblitz = MagicMock()
        flareblitz.id = "flareblitz"
        battle.available_moves = [[flareblitz], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["fire"]
        battle.active_pokemon[1].types = ["fire"]
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "sunnyday"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 0.0)
        self.assertIn("redundant", reason.lower())

    def test_electric_terrain_already_active_no_bonus(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = MagicMock()
        battle.weather = None
        f = MagicMock()
        f.__str__ = lambda self: "ELECTRIC_TERRAIN"
        battle.fields = [f]
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        thunderbolt = MagicMock()
        thunderbolt.id = "thunderbolt"
        battle.available_moves = [[thunderbolt], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["electric"]
        battle.active_pokemon[1].types = ["electric"]
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "electricterrain"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 0.0)
        self.assertIn("redundant", reason.lower())


# ---- Opponent-benefit penalty tests ----
class TestOpponentBenefitPenalty(unittest.TestCase):
    def test_opponent_has_more_water_synergy_no_bonus(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        # Our side: 1 water move
        surf = MagicMock()
        surf.id = "surf"
        battle.available_moves = [[surf], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["water"]
        battle.active_pokemon[1].types = ["water"]
        # Opp side: 3 water moves (more synergy)
        opp_surf = MagicMock()
        opp_surf.id = "surf"
        opp_hydro = MagicMock()
        opp_hydro.id = "hydropump"
        opp_thunder = MagicMock()
        opp_thunder.id = "thunder"
        opp1 = MagicMock()
        opp1.moves = {"surf": True, "hydropump": True}
        opp2 = MagicMock()
        opp2.moves = {"thunder": True}
        battle.opponent_active_pokemon = [opp1, opp2]
        battle.opponent_team = None
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "raindance"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 0.0)
        self.assertIn("opponent", reason.lower())


# ---- Safety tests ----
class TestSafetyNoSpeciesInference(unittest.TestCase):
    def test_no_ability_inference_in_rain_synergy(self):
        """The synergy scoring must NOT infer abilities
        like Swift Swim, Chlorophyll, etc. from species.
        It should only count revealed moves.
        """
        from doubles_engine.wt3_weather_terrain_positive import (
            _score_rain_synergy,
            _score_sun_synergy,
            _score_electric_terrain_synergy,
        )
        # Build a battle with NO revealed moves
        battle = MagicMock()
        battle.available_moves = [[], []]
        # Even if active is "Kingdra" (which has Swift
        # Swim), the synergy score is 0 because no
        # revealed moves.
        active = MagicMock()
        active.types = ["water", "dragon"]
        battle.active_pokemon = [active, active]
        self.assertEqual(_score_rain_synergy(battle, 0), 0.0)
        self.assertEqual(_score_sun_synergy(battle, 0), 0.0)
        self.assertEqual(
            _score_electric_terrain_synergy(battle, 0), 0.0
        )


class TestNonSetterMoveNoBonus(unittest.TestCase):
    def test_tackle_gets_no_bonus(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["water"]
        battle.active_pokemon[1].types = ["water"]
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "tackle"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 0.0)
        self.assertEqual(reason, "")


class TestSwitchOrderNoBonus(unittest.TestCase):
    def test_switch_order_gets_no_bonus(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["water"]
        battle.active_pokemon[1].types = ["water"]
        # Switch order: order.order is a Pokemon, not a Move
        order = MagicMock()
        order.order = MagicMock()  # Pokemon, no .id
        order.order.name = "Incineroar"
        # Make hasattr(order.order, "id") return False
        del order.order.id
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 0.0)
        self.assertEqual(reason, "")


# ---- Config integration tests ----
class TestConfigIntegration(unittest.TestCase):
    def test_default_flag_is_false(self):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig()
        self.assertFalse(cfg.enable_weather_terrain_positive_scoring)

    def test_default_bonuses(self):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig()
        # WT-4a tuned defaults
        self.assertEqual(
            cfg.weather_terrain_positive_weather_bonus, 500.0
        )
        self.assertEqual(
            cfg.weather_terrain_positive_terrain_bonus, 400.0
        )
        self.assertEqual(
            cfg.weather_terrain_positive_max_picks_per_game, 3
        )
        self.assertEqual(
            cfg.weather_terrain_positive_min_turn_between_picks, 2
        )
        self.assertTrue(
            cfg.weather_terrain_positive_require_survival
        )


# ---- Phase WT-4a: Misty Terrain audit/fix tests ----
class TestMistyTerrainSignal(unittest.TestCase):
    """WT-4a fix: Misty Terrain should only get a
    bonus when:
    * opponent has revealed Dragon-type active, OR
    * opponent has revealed status-inflicting moves
    (status prevention is useful).

    Pre-WT-4a, Misty got a bonus for opponent
    Fairy/Psychic type, which is wrong because Misty
    doesn't block Fairy or Psychic damage.
    """

    def test_misty_no_bonus_for_fairy_opp(self):
        """Pre-WT-4a bug: opponent Fairy type should
        NOT trigger Misty bonus.
        """
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["fairy"]
        battle.active_pokemon[1].types = ["fairy"]
        # Opp is Fairy
        opp = MagicMock()
        opp.types = ["fairy"]
        opp.moves = {}
        battle.opponent_active_pokemon = [opp, opp]
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "mistyterrain"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        # No Dragon type, no status moves from opp,
        # no own synergy -> no bonus
        self.assertEqual(bonus, 0.0)

    def test_misty_no_bonus_for_psychic_opp(self):
        """Pre-WT-4a bug: opponent Psychic type should
        NOT trigger Misty bonus.
        """
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["psychic"]
        battle.active_pokemon[1].types = ["psychic"]
        # Opp is Psychic
        opp = MagicMock()
        opp.types = ["psychic"]
        opp.moves = {}
        battle.opponent_active_pokemon = [opp, opp]
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "mistyterrain"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 0.0)

    def test_misty_bonus_for_dragon_opp(self):
        """WT-4a: opp has revealed Dragon-type moves
        -> Misty bonus.
        """
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["fairy"]
        battle.active_pokemon[1].types = ["fairy"]
        # Opp has Dragon Claw revealed
        opp = MagicMock()
        opp.types = ["dragon"]
        opp.moves = {"dragonclaw": True}
        battle.opponent_active_pokemon = [opp, opp]
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "mistyterrain"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 120.0)
        self.assertIn("terrain", reason.lower())

    def test_misty_bonus_for_status_threat(self):
        """WT-4a: opp has revealed status moves ->
        Misty bonus for status prevention.
        """
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 150.0
        config.weather_terrain_positive_terrain_bonus = 120.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["normal"]
        battle.active_pokemon[1].types = ["normal"]
        # Opp has Thunder Wave revealed
        opp = MagicMock()
        opp.types = ["electric"]
        opp.moves = {"thunderwave": True}
        battle.opponent_active_pokemon = [opp, opp]
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "mistyterrain"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 120.0)


# ---- Phase WT-4a: bad setter detection tests ----
class TestIsBadSetterSelection(unittest.TestCase):
    def test_clean_setter_rain_with_water_user(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            is_bad_setter_selection,
        )
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        surf = MagicMock()
        surf.id = "surf"
        battle.available_moves = [[surf], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["water"]
        battle.active_pokemon[1].types = ["water"]
        reasons = is_bad_setter_selection(
            "raindance", 0, battle
        )
        # Rain Dance with own Water user and no opp
        # synergy should be clean.
        self.assertNotIn("no_own_synergy", reasons)
        self.assertNotIn("redundant_setter", reasons)

    def test_redundant_setter_detected(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            is_bad_setter_selection,
        )
        battle = MagicMock()
        battle.weather = MagicMock()
        battle.weather.__str__ = lambda self: "RAIN"
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["water"]
        battle.active_pokemon[1].types = ["water"]
        reasons = is_bad_setter_selection(
            "raindance", 0, battle
        )
        self.assertIn("redundant_setter", reasons)

    def test_no_own_synergy_detected(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            is_bad_setter_selection,
        )
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["normal"]
        battle.active_pokemon[1].types = ["normal"]
        reasons = is_bad_setter_selection(
            "raindance", 0, battle
        )
        self.assertIn("no_own_synergy", reasons)

    def test_opponent_benefits_detected(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            is_bad_setter_selection,
        )
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["normal"]
        battle.active_pokemon[1].types = ["normal"]
        # Opp has 3 Water moves
        opp1 = MagicMock()
        opp1.types = ["water"]
        opp1.moves = {"surf": True, "hydropump": True}
        opp2 = MagicMock()
        opp2.types = ["water"]
        opp2.moves = {"thunder": True}
        battle.opponent_active_pokemon = [opp1, opp2]
        reasons = is_bad_setter_selection(
            "raindance", 0, battle
        )
        self.assertIn("opponent_benefits_more", reasons)

    def test_non_setter_returns_empty(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            is_bad_setter_selection,
        )
        battle = MagicMock()
        reasons = is_bad_setter_selection(
            "tackle", 0, battle
        )
        self.assertEqual(reasons, [])

    def test_none_battle_returns_empty(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            is_bad_setter_selection,
        )
        reasons = is_bad_setter_selection(
            "raindance", 0, None
        )
        self.assertEqual(reasons, [])


# ---- Phase WT-4a: configurable bonus tests ----
class TestConfigurableBonus(unittest.TestCase):
    def test_candidate_bonus_values_configurable(self):
        """WT-4a: the bonus values must be configurable.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig()
        cfg.weather_terrain_positive_weather_bonus = 500.0
        cfg.weather_terrain_positive_terrain_bonus = 400.0
        self.assertEqual(
            cfg.weather_terrain_positive_weather_bonus, 500.0
        )
        self.assertEqual(
            cfg.weather_terrain_positive_terrain_bonus, 400.0
        )

    def test_master_flag_still_default_off(self):
        """WT-4a: master flag must remain OFF by default.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig()
        self.assertFalse(
            cfg.enable_weather_terrain_positive_scoring
        )

    def test_flag_off_with_high_bonus_no_effect(self):
        """WT-4a: even with a high bonus, flag OFF = 0.
        """
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = False
        config.weather_terrain_positive_weather_bonus = 1000.0
        config.weather_terrain_positive_terrain_bonus = 800.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        surf = MagicMock()
        surf.id = "surf"
        battle.available_moves = [[surf], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["water"]
        battle.active_pokemon[1].types = ["water"]
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "raindance"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 0.0)
        self.assertEqual(reason, "")


# ---- Phase WT-4c: candidate inclusion helper tests ----
class TestShouldIncludeWTSetterCandidate(unittest.TestCase):
    """WT-4c: tests for the narrow opt-in candidate
    inclusion helper.
    """

    def test_flag_off_no_inclusion(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            should_include_weather_terrain_setter_candidate,
            INCLUSION_REJECTED_FLAG_OFF,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = False
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        surf = MagicMock()
        surf.id = "surf"
        battle.available_moves = [[surf], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["water"]
        battle.active_pokemon[1].types = ["water"]
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(result["reason"], INCLUSION_REJECTED_FLAG_OFF)

    def test_flag_on_positive_rain_included(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            should_include_weather_terrain_setter_candidate,
            INCLUSION_ACCEPTED,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 500.0
        config.weather_terrain_positive_terrain_bonus = 400.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        surf = MagicMock()
        surf.id = "surf"
        battle.available_moves = [[surf], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["water"]
        battle.active_pokemon[1].types = ["water"]
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertTrue(result["include"])
        self.assertEqual(result["reason"], INCLUSION_ACCEPTED)
        self.assertEqual(result["bonus"], 500.0)
        self.assertEqual(result["target"], "raindance")

    def test_flag_on_positive_sun_included(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            should_include_weather_terrain_setter_candidate,
            INCLUSION_ACCEPTED,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 500.0
        config.weather_terrain_positive_terrain_bonus = 400.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        flareblitz = MagicMock()
        flareblitz.id = "flareblitz"
        battle.available_moves = [[flareblitz], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["fire"]
        battle.active_pokemon[1].types = ["fire"]
        result = should_include_weather_terrain_setter_candidate(
            "sunnyday", 0, battle, config
        )
        self.assertTrue(result["include"])
        self.assertEqual(result["reason"], INCLUSION_ACCEPTED)

    def test_flag_on_positive_terrain_included(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            should_include_weather_terrain_setter_candidate,
            INCLUSION_ACCEPTED,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 500.0
        config.weather_terrain_positive_terrain_bonus = 400.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        thunderbolt = MagicMock()
        thunderbolt.id = "thunderbolt"
        battle.available_moves = [[thunderbolt], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["electric"]
        battle.active_pokemon[1].types = ["electric"]
        result = should_include_weather_terrain_setter_candidate(
            "electricterrain", 0, battle, config
        )
        self.assertTrue(result["include"])
        self.assertEqual(result["reason"], INCLUSION_ACCEPTED)
        self.assertEqual(result["bonus"], 400.0)

    def test_redundant_setter_not_included(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            should_include_weather_terrain_setter_candidate,
            INCLUSION_REJECTED_REDUNDANT,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 500.0
        config.weather_terrain_positive_terrain_bonus = 400.0
        battle = MagicMock()
        battle.weather = MagicMock()
        battle.weather.__str__ = lambda self: "RAIN"
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        surf = MagicMock()
        surf.id = "surf"
        battle.available_moves = [[surf], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["water"]
        battle.active_pokemon[1].types = ["water"]
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(
            result["reason"], INCLUSION_REJECTED_REDUNDANT
        )

    def test_opp_benefits_more_not_included(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            should_include_weather_terrain_setter_candidate,
            INCLUSION_REJECTED_OPP_BENEFITS,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 500.0
        config.weather_terrain_positive_terrain_bonus = 400.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        # Our side: 1 Water move (own synergy > 0)
        surf = MagicMock()
        surf.id = "surf"
        battle.available_moves = [[surf], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["water"]
        battle.active_pokemon[1].types = ["water"]
        # Opp has 3 Water moves (more synergy)
        opp1 = MagicMock()
        opp1.types = []
        opp1.moves = {"surf": True, "hydropump": True}
        opp2 = MagicMock()
        opp2.types = []
        opp2.moves = {"thunder": True}
        battle.opponent_active_pokemon = [opp1, opp2]
        battle.opponent_team = None
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(
            result["reason"], INCLUSION_REJECTED_OPP_BENEFITS
        )

    def test_no_own_synergy_not_included(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            should_include_weather_terrain_setter_candidate,
            INCLUSION_REJECTED_NO_SYNERGY,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 500.0
        config.weather_terrain_positive_terrain_bonus = 400.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["normal"]
        battle.active_pokemon[1].types = ["normal"]
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(
            result["reason"], INCLUSION_REJECTED_NO_SYNERGY
        )

    def test_non_setter_move_not_included(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            should_include_weather_terrain_setter_candidate,
            INCLUSION_REJECTED_NOT_SETTER,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 500.0
        config.weather_terrain_positive_terrain_bonus = 400.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        result = should_include_weather_terrain_setter_candidate(
            "tackle", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(
            result["reason"], INCLUSION_REJECTED_NOT_SETTER
        )

    def test_none_config_not_included(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            should_include_weather_terrain_setter_candidate,
            INCLUSION_REJECTED_FLAG_OFF,
        )
        battle = MagicMock()
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, None
        )
        self.assertFalse(result["include"])
        self.assertEqual(result["reason"], INCLUSION_REJECTED_FLAG_OFF)

    def test_zero_bonus_not_included(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            should_include_weather_terrain_setter_candidate,
            INCLUSION_REJECTED_ZERO_BONUS,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 0.0
        config.weather_terrain_positive_terrain_bonus = 0.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        surf = MagicMock()
        surf.id = "surf"
        battle.available_moves = [[surf], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["water"]
        battle.active_pokemon[1].types = ["water"]
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(
            result["reason"], INCLUSION_REJECTED_ZERO_BONUS
        )


# ---- Phase WT-4e: status-move penalty exception tests ----
class TestStatusMovePenaltyException(unittest.TestCase):
    """WT-4d added a status-move penalty exception in
    the bot's `_score_action_impl`. If the active
    Pokemon has a damaging move, status moves normally
    get score=0. The exception allows WT-3 setters
    with positive synergy to bypass this penalty.

    These tests verify the inclusion helper correctly
    identifies when the exception should apply. The
    actual integration into the bot is tested via
    the smoke harness.
    """

    def _make_water_battle(self, opp_synergy_moves=None):
        """Build a battle where our active has Water
        synergy and Rain Dance is legal.
        """
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        surf = MagicMock()
        surf.id = "surf"
        battle.available_moves = [[surf], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["water"]
        battle.active_pokemon[1].types = ["water"]
        if opp_synergy_moves:
            opp = MagicMock()
            opp.types = []
            opp.moves = {m: True for m in opp_synergy_moves}
            battle.opponent_active_pokemon = [opp, opp]
        return battle

    def test_flag_off_status_move_penalty_not_bypassed(self):
        """Flag OFF: no inclusion, no bypass of
        status move penalty.
        """
        from doubles_engine.wt3_weather_terrain_positive import (
            should_include_weather_terrain_setter_candidate,
            INCLUSION_REJECTED_FLAG_OFF,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = False
        config.weather_terrain_positive_weather_bonus = 1000.0
        config.weather_terrain_positive_terrain_bonus = 800.0
        battle = self._make_water_battle()
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(result["reason"], INCLUSION_REJECTED_FLAG_OFF)

    def test_flag_on_positive_synergy_passes_inclusion(self):
        """Flag ON + positive synergy: inclusion
        passes, which means the status move penalty
        exception will apply in the bot.
        """
        from doubles_engine.wt3_weather_terrain_positive import (
            should_include_weather_terrain_setter_candidate,
            INCLUSION_ACCEPTED,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 500.0
        config.weather_terrain_positive_terrain_bonus = 400.0
        battle = self._make_water_battle()
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertTrue(result["include"])
        self.assertEqual(result["reason"], INCLUSION_ACCEPTED)
        self.assertEqual(result["bonus"], 500.0)

    def test_non_wt_status_move_not_affected(self):
        """Non-WT status move (e.g., Thunder Wave):
        the inclusion helper rejects it, so the
        status move penalty exception does NOT
        apply. Normal status move penalty still
        applies.
        """
        from doubles_engine.wt3_weather_terrain_positive import (
            should_include_weather_terrain_setter_candidate,
            INCLUSION_REJECTED_NOT_SETTER,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 500.0
        config.weather_terrain_positive_terrain_bonus = 400.0
        battle = self._make_water_battle()
        result = should_include_weather_terrain_setter_candidate(
            "thunderwave", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(
            result["reason"], INCLUSION_REJECTED_NOT_SETTER
        )

    def test_high_bonus_cannot_bypass_no_synergy(self):
        """Even with a very high bonus, no-synergy
        setters are NOT included.
        """
        from doubles_engine.wt3_weather_terrain_positive import (
            should_include_weather_terrain_setter_candidate,
            INCLUSION_REJECTED_NO_SYNERGY,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 10000.0
        config.weather_terrain_positive_terrain_bonus = 10000.0
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["normal"]
        battle.active_pokemon[1].types = ["normal"]
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(
            result["reason"], INCLUSION_REJECTED_NO_SYNERGY
        )

    def test_redundant_setter_passes_exception_check(self):
        """Redundant setter: inclusion helper rejects
        with redundant reason. The status move
        penalty exception does not apply because
        the helper says include=False.
        """
        from doubles_engine.wt3_weather_terrain_positive import (
            should_include_weather_terrain_setter_candidate,
            INCLUSION_REJECTED_REDUNDANT,
        )
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 500.0
        config.weather_terrain_positive_terrain_bonus = 400.0
        battle = self._make_water_battle()
        battle.weather = MagicMock()
        battle.weather.__str__ = lambda self: "RAIN"
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(
            result["reason"], INCLUSION_REJECTED_REDUNDANT
        )


if __name__ == "__main__":
    unittest.main()
