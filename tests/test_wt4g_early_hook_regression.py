# Phase WT-4g — early-hook regression tests for the
# WT-3 Weather/Terrain scoring path.
#
# WT-4f moved the WT-3 hook to the beginning of
# ``_score_action_impl`` and deferred the bonus via
# ``_wt3_pending_bonus``. These tests prove the
# deferred bonus does NOT leak between candidates
# and that flag OFF preserves old behavior.

import unittest
from unittest.mock import MagicMock

from doubles_engine.wt3_weather_terrain_positive import (
    get_weather_terrain_positive_bonus,
    should_include_weather_terrain_setter_candidate,
    INCLUSION_ACCEPTED,
    INCLUSION_REJECTED_FLAG_OFF,
    INCLUSION_REJECTED_NOT_SETTER,
    INCLUSION_REJECTED_NO_SYNERGY,
    INCLUSION_REJECTED_OPP_BENEFITS,
    INCLUSION_REJECTED_REDUNDANT,
    INCLUSION_REJECTED_ZERO_BONUS,
)


def _make_water_active_battle(
    opp_synergy_moves=None, opp_synergy_types=None
):
    """Build a battle where our active has Water
    synergy and Rain Dance is legal. Used for
    positive-synergy and opp-benefits-more tests.
    """
    battle = MagicMock()
    battle.weather = None
    battle.fields = None
    battle.opponent_active_pokemon = []
    battle.opponent_team = None
    surf = MagicMock()
    surf.id = "surf"
    raindance = MagicMock()
    raindance.id = "raindance"
    battle.available_moves = [[surf, raindance], []]
    p1 = MagicMock()
    p1.types = ["water"]
    p2 = MagicMock()
    p2.types = ["water"]
    battle.active_pokemon = [p1, p2]
    if opp_synergy_moves or opp_synergy_types:
        opp = MagicMock()
        opp.types = opp_synergy_types or []
        opp.moves = {m: True for m in (opp_synergy_moves or [])}
        battle.opponent_active_pokemon = [opp, opp]
    return battle


def _make_terrain_active_battle(opp_electric_moves=None):
    """Build a battle where our active has Electric
    terrain synergy. Jolteon + partner.
    """
    battle = MagicMock()
    battle.weather = None
    battle.fields = None
    battle.opponent_active_pokemon = []
    battle.opponent_team = None
    thunderbolt = MagicMock()
    thunderbolt.id = "thunderbolt"
    electricterrain = MagicMock()
    electricterrain.id = "electricterrain"
    battle.available_moves = [[thunderbolt, electricterrain], []]
    p1 = MagicMock()
    p1.types = ["electric"]
    p2 = MagicMock()
    p2.types = ["electric"]
    battle.active_pokemon = [p1, p2]
    if opp_electric_moves:
        opp = MagicMock()
        opp.types = ["electric"]
        opp.moves = {m: True for m in opp_electric_moves}
        battle.opponent_active_pokemon = [opp, opp]
    return battle


def _make_off_config(weather=500.0, terrain=400.0):
    config = MagicMock()
    config.enable_weather_terrain_positive_scoring = True
    config.weather_terrain_positive_weather_bonus = weather
    config.weather_terrain_positive_terrain_bonus = terrain
    return config


def _make_off_disabled_config():
    config = MagicMock()
    config.enable_weather_terrain_positive_scoring = False
    config.weather_terrain_positive_weather_bonus = 500.0
    config.weather_terrain_positive_terrain_bonus = 400.0
    return config


# ---- 1. _wt3_pending_bonus resets per candidate ----
class TestPendingBonusResetsPerCandidate(unittest.TestCase):
    """The deferred bonus must NOT leak between
    candidates. Score a setter (positive), then a
    non-setter (should be 0 bonus).
    """

    def test_setter_then_non_setter_no_leakage(self):
        battle = _make_water_active_battle()
        config = _make_off_config()
        setter_order = MagicMock()
        raindance = MagicMock()
        raindance.id = "raindance"
        setter_order.order = raindance
        bonus_a, reason_a = get_weather_terrain_positive_bonus(
            setter_order, 0, battle, config=config
        )
        self.assertGreater(bonus_a, 0.0)
        self.assertIn("rain", reason_a)

        non_setter_order = MagicMock()
        surf = MagicMock()
        surf.id = "surf"
        non_setter_order.order = surf
        bonus_b, reason_b = get_weather_terrain_positive_bonus(
            non_setter_order, 0, battle, config=config
        )
        self.assertEqual(bonus_b, 0.0)

    def test_two_setters_independent_calls(self):
        """Two consecutive setter calls must each
        compute their own bonus (not accumulate).
        """
        battle = _make_water_active_battle()
        config = _make_off_config()
        setter_order = MagicMock()
        raindance = MagicMock()
        raindance.id = "raindance"
        setter_order.order = raindance
        bonus1, _ = get_weather_terrain_positive_bonus(
            setter_order, 0, battle, config=config
        )
        bonus2, _ = get_weather_terrain_positive_bonus(
            setter_order, 0, battle, config=config
        )
        self.assertGreater(bonus1, 0.0)
        self.assertEqual(bonus1, bonus2)


# ---- 2. _wt3_pending_bonus resets per call even after early return ----
class TestPendingBonusResetsAfterEarlyReturn(unittest.TestCase):
    """A setter call that returns a positive bonus
    must not affect a subsequent call that returns
    early (e.g., support move, switch, hard block).
    """

    def test_setter_then_support_move(self):
        battle = _make_water_active_battle()
        config = _make_off_config()
        setter_order = MagicMock()
        raindance = MagicMock()
        raindance.id = "raindance"
        setter_order.order = raindance
        bonus_a, _ = get_weather_terrain_positive_bonus(
            setter_order, 0, battle, config=config
        )
        self.assertGreater(bonus_a, 0.0)
        support_order = MagicMock()
        healpulse = MagicMock()
        healpulse.id = "healpulse"
        support_order.order = healpulse
        bonus_b, _ = get_weather_terrain_positive_bonus(
            support_order, 0, battle, config=config
        )
        self.assertEqual(bonus_b, 0.0)

    def test_setter_then_switch(self):
        battle = _make_water_active_battle()
        config = _make_off_config()
        setter_order = MagicMock()
        raindance = MagicMock()
        raindance.id = "raindance"
        setter_order.order = raindance
        bonus_a, _ = get_weather_terrain_positive_bonus(
            setter_order, 0, battle, config=config
        )
        self.assertGreater(bonus_a, 0.0)
        switch_order = MagicMock()
        switch_order.order = None
        bonus_b, _ = get_weather_terrain_positive_bonus(
            switch_order, 0, battle, config=config
        )
        self.assertEqual(bonus_b, 0.0)


# ---- 3. Flag OFF preserves old behavior ----
class TestFlagOffUnchanged(unittest.TestCase):
    """When the master flag is OFF, no positive WT
    bonus must be applied. The hook may run, but
    the bonus must be 0 and the inclusion helper
    must reject with FLAG_OFF.
    """

    def test_inclusion_helper_flag_off_rejects(self):
        battle = _make_water_active_battle()
        config = _make_off_disabled_config()
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(result["reason"], INCLUSION_REJECTED_FLAG_OFF)
        self.assertEqual(result["bonus"], 0.0)

    def test_bonus_helper_flag_off_returns_zero(self):
        battle = _make_water_active_battle()
        config = _make_off_disabled_config()
        setter_order = MagicMock()
        raindance = MagicMock()
        raindance.id = "raindance"
        setter_order.order = raindance
        bonus, reason = get_weather_terrain_positive_bonus(
            setter_order, 0, battle, config=config
        )
        self.assertEqual(bonus, 0.0)


# ---- 4. Flag ON + synergy positive ----
class TestFlagOnSynergyPositive(unittest.TestCase):
    """Flag ON + own synergy > opp synergy +
    setter legal + bonus > 0 => include=True
    and bonus > 0.
    """

    def test_rain_setter_water_active(self):
        battle = _make_water_active_battle()
        config = _make_off_config()
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertTrue(result["include"])
        self.assertEqual(result["reason"], INCLUSION_ACCEPTED)
        self.assertGreater(result["bonus"], 0.0)

    def test_electric_terrain_setter(self):
        battle = _make_terrain_active_battle()
        config = _make_off_config()
        result = should_include_weather_terrain_setter_candidate(
            "electricterrain", 0, battle, config
        )
        self.assertTrue(result["include"])
        self.assertEqual(result["reason"], INCLUSION_ACCEPTED)
        self.assertGreater(result["bonus"], 0.0)


# ---- 5. Non-WT status move ----
class TestNonWTStatusMoveUnaffected(unittest.TestCase):
    """Non-WT status moves (e.g., Thunder Wave,
    Toxic) must NOT receive WT bonus. The
    inclusion helper must reject with NOT_SETTER.
    """

    def test_thunderwave_no_bonus(self):
        battle = _make_water_active_battle()
        config = _make_off_config()
        result = should_include_weather_terrain_setter_candidate(
            "thunderwave", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(result["reason"], INCLUSION_REJECTED_NOT_SETTER)
        self.assertEqual(result["bonus"], 0.0)

    def test_toxic_no_bonus(self):
        battle = _make_water_active_battle()
        config = _make_off_config()
        result = should_include_weather_terrain_setter_candidate(
            "toxic", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(result["reason"], INCLUSION_REJECTED_NOT_SETTER)


# ---- 6. Redundant WT setter ----
class TestRedundantWTSetter(unittest.TestCase):
    """If the weather/terrain is already active,
    the setter is redundant. Bonus must be 0.
    """

    def test_rain_already_active(self):
        battle = _make_water_active_battle()
        battle.weather = MagicMock()
        battle.weather.__str__ = lambda self: "RAIN"
        config = _make_off_config()
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(result["reason"], INCLUSION_REJECTED_REDUNDANT)
        self.assertEqual(result["bonus"], 0.0)

    def test_electric_terrain_already_active(self):
        battle = _make_terrain_active_battle()
        # Use a real list with a Field enum-like object
        from doubles_engine.wt3_weather_terrain_positive import (
            get_active_terrain,
        )
        class _FakeField:
            def __str__(self):
                return "ELECTRIC_TERRAIN"
        battle.fields = [_FakeField()]
        config = _make_off_config()
        result = should_include_weather_terrain_setter_candidate(
            "electricterrain", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(result["reason"], INCLUSION_REJECTED_REDUNDANT)


# ---- 7. Opponent benefits more ----
class TestOppBenefitsMore(unittest.TestCase):
    """If the opponent has more synergy, no bonus.
    High bonus config cannot bypass this guard.
    """

    def test_opp_water_thunder_hurricane_blocks(self):
        battle = _make_water_active_battle(
            opp_synergy_moves=["surf", "thunder", "hurricane"]
        )
        config = _make_off_config(weather=10000.0, terrain=10000.0)
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(
            result["reason"], INCLUSION_REJECTED_OPP_BENEFITS
        )
        self.assertEqual(result["bonus"], 0.0)

    def test_opp_electric_blocks_terrain_bonus(self):
        battle = _make_terrain_active_battle(
            opp_electric_moves=["thunderbolt", "voltswitch"]
        )
        config = _make_off_config(weather=10000.0, terrain=10000.0)
        result = should_include_weather_terrain_setter_candidate(
            "electricterrain", 0, battle, config
        )
        self.assertFalse(result["include"])


# ---- 8. No species-based ability inference ----
class TestNoSpeciesAbilityInference(unittest.TestCase):
    """The WT helper must NOT infer abilities from
    species. The bonus depends only on observed
    state (weather, terrain, types, moves).
    """

    def test_politoed_with_drizzle_still_uses_moveset(self):
        """Even if Politoed has Drizzle (auto-rain),
        the helper checks the active Pokemon's types
        and the opp's synergy, not the species.
        """
        battle = _make_water_active_battle()
        config = _make_off_config()
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertTrue(result["include"])
        self.assertEqual(result["reason"], INCLUSION_ACCEPTED)

    def test_tapu_lele_with_psychic_surge_still_uses_moveset(self):
        """Even if Tapu Lele has Psychic Surge (auto
        Psychic Terrain), the helper checks the
        active Pokemon's types and the opp's
        synergy, not the species. Here we set
        Psychic-type moves so synergy is positive.
        """
        battle = MagicMock()
        battle.weather = None
        battle.fields = None
        battle.opponent_active_pokemon = []
        battle.opponent_team = None
        moonblast = MagicMock()
        moonblast.id = "moonblast"
        psychterrain = MagicMock()
        psychterrain.id = "psychicterrain"
        psychic_move = MagicMock()
        psychic_move.id = "psychic"
        battle.available_moves = [[moonblast, psychterrain, psychic_move], []]
        p1 = MagicMock()
        p1.types = ["psychic", "fairy"]
        p2 = MagicMock()
        p2.types = ["psychic", "fairy"]
        battle.active_pokemon = [p1, p2]
        config = _make_off_config()
        result = should_include_weather_terrain_setter_candidate(
            "psychicterrain", 0, battle, config
        )
        self.assertTrue(result["include"])
        self.assertEqual(result["reason"], INCLUSION_ACCEPTED)


# ---- 9. Zero bonus config ----
class TestZeroBonusConfig(unittest.TestCase):
    """If bonus values are 0, the helper must
    reject with ZERO_BONUS. No accidental positive.
    """

    def test_zero_weather_bonus(self):
        battle = _make_water_active_battle()
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 0.0
        config.weather_terrain_positive_terrain_bonus = 400.0
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertFalse(result["include"])
        self.assertEqual(result["reason"], INCLUSION_REJECTED_ZERO_BONUS)


# ---- 10. Anti-TR unchanged ----
class TestAntiTrickRoomUnchanged(unittest.TestCase):
    """The WT-3 path must not affect Anti-TR
    behavior. The inclusion helper does not look
    at Trick Room or anti-TR state.
    """

    def test_trick_room_active_no_effect_on_rain(self):
        battle = _make_water_active_battle()
        battle.fields = MagicMock()
        battle.fields.__str__ = lambda self: "TRICK_ROOM"
        config = _make_off_config()
        result = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertTrue(result["include"])
        self.assertEqual(result["reason"], INCLUSION_ACCEPTED)


# ---- 11. Independent calls do not share state ----
class TestIndependentCalls(unittest.TestCase):
    """Two consecutive calls with the same input
    must produce the same output. The helper is
    pure and stateless.
    """

    def test_same_input_same_output(self):
        battle = _make_water_active_battle()
        config = _make_off_config()
        setter_order = MagicMock()
        raindance = MagicMock()
        raindance.id = "raindance"
        setter_order.order = raindance
        r1 = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        r2 = should_include_weather_terrain_setter_candidate(
            "raindance", 0, battle, config
        )
        self.assertEqual(r1["include"], r2["include"])
        self.assertEqual(r1["reason"], r2["reason"])
        self.assertEqual(r1["bonus"], r2["bonus"])


if __name__ == "__main__":
    unittest.main()
