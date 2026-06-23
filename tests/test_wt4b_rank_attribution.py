"""Tests for Phase WT-4b forced-synergy fixtures and
rank attribution helpers.

These tests prove the scoring can activate in
controlled situations:

* Case A — Rain activation (own Water + opp no rain)
* Case B — Sun activation (own Fire + opp no sun)
* Case C — Electric/Grassy/Psychic Terrain activation
* Case D — Redundant setter (no bonus)
* Case E — Opponent benefits more (no bonus)
* Case F — Misty Terrain (no Fairy/Psychic-only bonus)

Also tests:
* Rank attribution computes correctly
* Config bonus values are passed correctly
* Master flag default remains OFF
"""

import os
import sys
import unittest
from typing import Any
from unittest.mock import MagicMock

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "showdown_ai"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analyze"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "inspect"))


# ---- Helper builders ----
def _make_battle_with_water_user(opp_synergy_moves=None):
    """Build a battle where our active slot 0 has
    revealed Water-type moves.
    """
    battle = MagicMock()
    battle.weather = None
    battle.fields = None
    battle.opponent_active_pokemon = []
    battle.opponent_team = None
    surf = MagicMock()
    surf.id = "surf"
    hydro = MagicMock()
    hydro.id = "hydropump"
    battle.available_moves = [[surf, hydro], []]
    battle.active_pokemon = [MagicMock(), MagicMock()]
    battle.active_pokemon[0].types = ["water"]
    battle.active_pokemon[1].types = ["water"]
    if opp_synergy_moves:
        opp = MagicMock()
        opp.types = []
        opp.moves = {m: True for m in opp_synergy_moves}
        battle.opponent_active_pokemon = [opp, opp]
    return battle


def _make_battle_with_fire_user(opp_synergy_moves=None):
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
    if opp_synergy_moves:
        opp = MagicMock()
        opp.types = []
        opp.moves = {m: True for m in opp_synergy_moves}
        battle.opponent_active_pokemon = [opp, opp]
    return battle


def _make_battle_with_electric_user(opp_synergy_moves=None):
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
    if opp_synergy_moves:
        opp = MagicMock()
        opp.types = []
        opp.moves = {m: True for m in opp_synergy_moves}
        battle.opponent_active_pokemon = [opp, opp]
    return battle


def _make_battle_with_grass_user(opp_synergy_moves=None):
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
    if opp_synergy_moves:
        opp = MagicMock()
        opp.types = []
        opp.moves = {m: True for m in opp_synergy_moves}
        battle.opponent_active_pokemon = [opp, opp]
    return battle


def _make_battle_with_psychic_user(opp_synergy_moves=None):
    battle = MagicMock()
    battle.weather = None
    battle.fields = None
    battle.opponent_active_pokemon = []
    battle.opponent_team = None
    psychic = MagicMock()
    psychic.id = "psychic"
    battle.available_moves = [[psychic], []]
    battle.active_pokemon = [MagicMock(), MagicMock()]
    battle.active_pokemon[0].types = ["psychic"]
    battle.active_pokemon[1].types = ["psychic"]
    if opp_synergy_moves:
        opp = MagicMock()
        opp.types = []
        opp.moves = {m: True for m in opp_synergy_moves}
        battle.opponent_active_pokemon = [opp, opp]
    return battle


def _make_battle_with_rain_active():
    battle = _make_battle_with_water_user()
    battle.weather = MagicMock()
    battle.weather.__str__ = lambda self: "RAIN"
    return battle


def _make_battle_with_electric_terrain_active():
    battle = _make_battle_with_electric_user()
    f = MagicMock()
    f.__str__ = lambda self: "ELECTRIC_TERRAIN"
    battle.fields = [f]
    return battle


def _make_config(
    weather_bonus=500.0,
    terrain_bonus=400.0,
    flag=True,
):
    config = MagicMock()
    config.enable_weather_terrain_positive_scoring = flag
    config.weather_terrain_positive_weather_bonus = (
        weather_bonus
    )
    config.weather_terrain_positive_terrain_bonus = (
        terrain_bonus
    )
    return config


# ---- Case A: Rain activation ----
class TestCaseARainActivation(unittest.TestCase):
    def test_rain_with_own_water_no_opp_rain_bonus(self):
        """Case A: own Water user, opp has no rain
        synergy. WT helper should return weather_bonus.
        """
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = _make_config(weather_bonus=500.0)
        battle = _make_battle_with_water_user()
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "raindance"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 500.0)
        self.assertIn("rain", reason.lower())

    def test_rain_bonus_with_configurable_value(self):
        """WT-4b: bonus is configurable.
        """
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = _make_config(weather_bonus=1000.0)
        battle = _make_battle_with_water_user()
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "raindance"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 1000.0)

    def test_rain_with_own_thunder_hurricane(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = _make_config(weather_bonus=500.0)
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
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "raindance"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 500.0)


# ---- Case B: Sun activation ----
class TestCaseBSunActivation(unittest.TestCase):
    def test_sun_with_own_fire_no_opp_sun(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = _make_config(weather_bonus=500.0)
        battle = _make_battle_with_fire_user()
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "sunnyday"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 500.0)
        self.assertIn("sun", reason.lower())

    def test_sun_with_own_solarbeam(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = _make_config(weather_bonus=500.0)
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        solarbeam = MagicMock()
        solarbeam.id = "solarbeam"
        battle.available_moves = [[solarbeam], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["fire"]
        battle.active_pokemon[1].types = ["fire"]
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "sunnyday"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 500.0)


# ---- Case C: Terrain activation ----
class TestCaseCTerrainActivation(unittest.TestCase):
    def test_electric_terrain_with_own_electric(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = _make_config(terrain_bonus=400.0)
        battle = _make_battle_with_electric_user()
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "electricterrain"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 400.0)
        self.assertIn("terrain", reason.lower())

    def test_grassy_terrain_with_own_grass(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = _make_config(terrain_bonus=400.0)
        battle = _make_battle_with_grass_user()
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "grassyterrain"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 400.0)
        self.assertIn("terrain", reason.lower())

    def test_psychic_terrain_with_own_psychic(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = _make_config(terrain_bonus=400.0)
        battle = _make_battle_with_psychic_user()
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "psychicterrain"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 400.0)
        self.assertIn("terrain", reason.lower())


# ---- Case D: Redundant setter ----
class TestCaseDRedundantSetter(unittest.TestCase):
    def test_rain_already_active_no_bonus(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = _make_config(weather_bonus=500.0)
        battle = _make_battle_with_rain_active()
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "raindance"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 0.0)
        self.assertIn("redundant", reason.lower())

    def test_electric_terrain_already_active_no_bonus(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = _make_config(terrain_bonus=400.0)
        battle = _make_battle_with_electric_terrain_active()
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "electricterrain"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 0.0)
        self.assertIn("redundant", reason.lower())


# ---- Case E: Opponent benefits more ----
class TestCaseEOpponentBenefitsMore(unittest.TestCase):
    def test_rain_opp_has_more_water_synergy(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = _make_config(weather_bonus=500.0)
        # Our side: 1 water move; opp side: 3 water moves
        battle = _make_battle_with_water_user(
            opp_synergy_moves=["surf", "hydropump", "thunder"]
        )
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "raindance"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 0.0)
        self.assertIn("opponent", reason.lower())


# ---- Case F: Misty Terrain ----
class TestCaseFMistyTerrain(unittest.TestCase):
    def test_misty_no_bonus_for_fairy_psychic_opp(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = _make_config(terrain_bonus=400.0)
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["fairy"]
        battle.active_pokemon[1].types = ["fairy"]
        opp = MagicMock()
        opp.types = ["fairy", "psychic"]
        opp.moves = {}
        battle.opponent_active_pokemon = [opp, opp]
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "mistyterrain"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        # Pre-WT-4a bug: Fairy/Psychic opp would give
        # bonus. Post-WT-4a: no bonus.
        self.assertEqual(bonus, 0.0)

    def test_misty_bonus_for_dragon_status_threat(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = _make_config(terrain_bonus=400.0)
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        battle.available_moves = [[], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["fairy"]
        battle.active_pokemon[1].types = ["fairy"]
        # Opp has Dragon Claw (Dragon-type threat)
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
        self.assertEqual(bonus, 400.0)


# ---- WT-4b attribution helper tests ----
class TestWT4bAttributionHelpers(unittest.TestCase):
    def test_compute_wt_bonus_for_rain(self):
        from doubles_engine.wt4b_rank_attribution import (
            compute_wt_bonus,
        )
        config = _make_config(weather_bonus=500.0)
        battle = _make_battle_with_water_user()
        bonus, reason = compute_wt_bonus(
            "raindance", 0, battle, config
        )
        self.assertEqual(bonus, 500.0)

    def test_compute_wt_bonus_for_non_setter(self):
        from doubles_engine.wt4b_rank_attribution import (
            compute_wt_bonus,
        )
        config = _make_config(weather_bonus=500.0)
        battle = _make_battle_with_water_user()
        bonus, reason = compute_wt_bonus(
            "tackle", 0, battle, config
        )
        self.assertEqual(bonus, 0.0)
        self.assertIn("not", reason.lower())

    def test_compute_wt_bonus_for_redundant(self):
        from doubles_engine.wt4b_rank_attribution import (
            compute_wt_bonus,
        )
        config = _make_config(weather_bonus=500.0)
        battle = _make_battle_with_rain_active()
        bonus, reason = compute_wt_bonus(
            "raindance", 0, battle, config
        )
        self.assertEqual(bonus, 0.0)
        self.assertIn("redundant", reason.lower())

    def test_classify_no_selection_bonus_zero_no_synergy(self):
        from doubles_engine.wt4b_rank_attribution import (
            classify_no_selection_reason,
        )
        reason = classify_no_selection_reason(
            0.0, "no_synergy", 0.0, 100.0
        )
        self.assertEqual(reason, "no_positive_synergy")

    def test_classify_no_selection_bonus_zero_redundant(self):
        from doubles_engine.wt4b_rank_attribution import (
            classify_no_selection_reason,
        )
        reason = classify_no_selection_reason(
            0.0, "redundant_weather_penalty", 0.0, 100.0
        )
        self.assertEqual(reason, "redundant_setter")

    def test_classify_no_selection_bonus_zero_opp(self):
        from doubles_engine.wt4b_rank_attribution import (
            classify_no_selection_reason,
        )
        reason = classify_no_selection_reason(
            0.0, "opponent_benefit_penalty", 0.0, 100.0
        )
        self.assertEqual(reason, "opponent_benefits_more")

    def test_classify_no_selection_bonus_positive_below(self):
        from doubles_engine.wt4b_rank_attribution import (
            classify_no_selection_reason,
        )
        reason = classify_no_selection_reason(
            500.0, "rain_water_synergy", 0.0, 1000.0
        )
        self.assertEqual(
            reason, "score_still_below_selected"
        )

    def test_classify_no_selection_bonus_positive_above(self):
        from doubles_engine.wt4b_rank_attribution import (
            classify_no_selection_reason,
        )
        # Bonus = 500, base = 0, final = 500
        # selected = 100, final > selected but not selected
        # This means rank improved but final selection
        # didn't pick it (joint scoring issue)
        reason = classify_no_selection_reason(
            500.0, "rain_water_synergy", 0.0, 100.0
        )
        self.assertEqual(reason, "rank_not_improved")


# ---- Master flag and config tests ----
class TestWT4bConfigAndFlag(unittest.TestCase):
    def test_master_flag_default_off(self):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig()
        self.assertFalse(
            cfg.enable_weather_terrain_positive_scoring
        )

    def test_tuned_bonus_defaults(self):
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

    def test_flag_off_with_high_bonus_no_effect(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = _make_config(weather_bonus=1000.0, flag=False)
        battle = _make_battle_with_water_user()
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "raindance"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(bonus, 0.0)
        self.assertEqual(reason, "")


# ---- No species / no Magic Bounce / no Anti-TR ----
class TestWT4bSafetyGuarantees(unittest.TestCase):
    def test_no_species_ability_inference_in_rain(self):
        from doubles_engine.wt3_weather_terrain_positive import (
            _score_rain_synergy,
        )
        battle = MagicMock()
        battle.available_moves = [[], []]
        # Kingdra-type: no revealed moves
        active = MagicMock()
        active.types = ["water", "dragon"]
        battle.active_pokemon = [active, active]
        # Even with Swift Swim, no revealed moves = 0
        self.assertEqual(_score_rain_synergy(battle, 0), 0.0)

    def test_magical_bounce_species_not_inferred(self):
        """WT-4b: the helper does not track any species-
        based ability. Hatterene has Magic Bounce but
        it should not be inferred.
        """
        from doubles_engine.wt3_weather_terrain_positive import (
            get_weather_terrain_positive_bonus,
        )
        config = _make_config(weather_bonus=500.0)
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        # Hatterene revealed moves: no Water synergy
        psyshock = MagicMock()
        psyshock.id = "psyshock"
        battle.available_moves = [[psyshock], []]
        battle.active_pokemon = [MagicMock(), MagicMock()]
        battle.active_pokemon[0].types = ["psychic"]
        battle.active_pokemon[1].types = ["psychic"]
        order = MagicMock()
        order.order = MagicMock()
        order.order.id = "raindance"
        bonus, reason = get_weather_terrain_positive_bonus(
            order, 0, battle, config=config
        )
        # No water synergy = no bonus
        self.assertEqual(bonus, 0.0)

    def test_anti_tr_setting_does_not_change_wt(self):
        """WT-4b: the anti-Trick-Room config is
        independent of WT scoring. Verify both
        settings can be changed independently.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig()
        # Both default to OFF
        self.assertFalse(cfg.enable_anti_trick_room_response)
        self.assertFalse(
            cfg.enable_weather_terrain_positive_scoring
        )
        # Change one, not the other
        cfg.enable_anti_trick_room_response = True
        self.assertTrue(cfg.enable_anti_trick_room_response)
        self.assertFalse(
            cfg.enable_weather_terrain_positive_scoring
        )


if __name__ == "__main__":
    unittest.main()
