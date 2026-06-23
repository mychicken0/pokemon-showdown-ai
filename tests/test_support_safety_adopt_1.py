# Phase SUPPORT-SAFETY-ADOPT-1 — default adoption tests.
#
# These tests prove that the narrow wrong-side ally
# heal/buff hard safety is now default-ON, while:
# - the explicit opt-out still works
# - broad support target safety is still default OFF
# - Anti-Trick-Room is still default OFF
# - Weather/Terrain scoring is still default OFF
# - no species-based ability inference is added
# - no Magic Bounce species inference is added

import unittest
from unittest.mock import MagicMock

from poke_env.battle.move import Move
from poke_env.player.battle_order import SingleBattleOrder

from bot_doubles_damage_aware import DoublesDamageAwareConfig
from doubles_engine.support_targets import (
    narrow_ally_heal_wrong_side_block,
    _NARROW_ALLY_HEAL_MOVE_IDS,
)


# A real ``Move`` instance (or a ``MagicMock(spec=Move)``)
# is required because ``narrow_ally_heal_wrong_side_block``
# uses ``isinstance(move, Move)`` as a guard.
def _make_move(move_id, base_power=0, category="STATUS"):
    move = MagicMock(spec=Move)
    move.id = move_id
    move.base_power = base_power
    cat = MagicMock()
    cat.name = category
    move.category = cat
    return move


def _make_order(move, target=None):
    order = MagicMock(spec=SingleBattleOrder)
    order.order = move
    if target is not None:
        order.move_target = target
    return order


def _make_battle():
    battle = MagicMock()
    battle.opponent_active_pokemon = [MagicMock(), MagicMock()]
    battle.active_pokemon = [MagicMock(), MagicMock()]
    return battle


# ---- 1. Default adoption tests ----

class TestDefaultAdoption(unittest.TestCase):
    """The narrow hard safety must be default ON after
    SUPPORT-SAFETY-ADOPT-1. Explicit False must still
    disable it.
    """

    def test_default_narrow_flag_is_true(self):
        """A fresh ``DoublesDamageAwareConfig()`` must
        have ``enable_ally_heal_wrong_side_hard_safety``
        default to ``True``.
        """
        config = DoublesDamageAwareConfig()
        self.assertTrue(
            config.enable_ally_heal_wrong_side_hard_safety
        )

    def test_explicit_false_disables(self):
        """Explicit ``enable_ally_heal_wrong_side_hard_safety=False``
        must disable the hard safety.
        """
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = False
        self.assertFalse(
            config.enable_ally_heal_wrong_side_hard_safety
        )

    def test_broad_support_safety_still_default_off(self):
        """The broad support move target safety flag
        (``enable_support_move_target_hard_safety``) must
        remain default OFF. SUPPORT-SAFETY-ADOPT-1 only
        adopts the narrow flag.
        """
        config = DoublesDamageAwareConfig()
        self.assertFalse(
            config.enable_support_move_target_hard_safety
        )

    def test_anti_trick_room_still_default_off(self):
        """Anti-Trick-Room must remain default OFF. This
        phase is not adopting Anti-TR.
        """
        config = DoublesDamageAwareConfig()
        self.assertFalse(
            config.enable_anti_trick_room_response
        )

    def test_wt_scoring_still_default_off(self):
        """Weather/Terrain positive scoring must remain
        default OFF. This phase is not adopting WT.
        """
        config = DoublesDamageAwareConfig()
        self.assertFalse(
            config.enable_weather_terrain_positive_scoring
        )

    def test_priority_field_hard_safety_still_default_off(self):
        """Priority field hard safety must remain default
        OFF. This phase is not adopting it.
        """
        config = DoublesDamageAwareConfig()
        self.assertFalse(
            config.enable_priority_field_hard_safety
        )


# ---- 2. Move safety tests ----

def _make_move_mock(move_id, base_power=0, category="STATUS"):
    m = MagicMock()
    m.id = move_id
    m.base_power = base_power
    cat = MagicMock()
    cat.name = category
    m.category = cat
    return m


def _make_battle():
    battle = MagicMock()
    battle.opponent_active_pokemon = [MagicMock(), MagicMock()]
    battle.active_pokemon = [MagicMock(), MagicMock()]
    return battle


class TestDefaultBlocks(unittest.TestCase):
    """With the default config (narrow flag True), the
    narrow path must block wrong-side healpulse,
    floralhealing, decorate. The correct ally-side use
    must not be blocked.
    """

    def test_default_blocks_healpulse_at_opponent(self):
        config = DoublesDamageAwareConfig()
        self.assertTrue(
            config.enable_ally_heal_wrong_side_hard_safety
        )
        battle = _make_battle()
        hp = _make_move("healpulse")
        order = _make_order(hp, target=1)  # opponent
        blocked, reason = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)
        self.assertIn("healpulse", reason.lower())

    def test_default_blocks_floralhealing_at_opponent(self):
        config = DoublesDamageAwareConfig()
        battle = _make_battle()
        fh = _make_move("floralhealing")
        order = _make_order(fh, target=1)
        blocked, reason = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)
        self.assertIn("floralhealing", reason.lower())

    def test_default_blocks_decorate_at_opponent(self):
        config = DoublesDamageAwareConfig()
        battle = _make_battle()
        dec = _make_move("decorate")
        order = _make_order(dec, target=1)
        blocked, reason = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)
        self.assertIn("decorate", reason.lower())

    def test_default_allows_healpulse_at_ally(self):
        """Correct ally-side use must NOT be blocked."""
        config = DoublesDamageAwareConfig()
        self.assertTrue(
            config.enable_ally_heal_wrong_side_hard_safety
        )
        battle = _make_battle()
        hp = _make_move("healpulse")
        order = _make_order(hp, target=-2)  # ally
        blocked, reason = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)
        self.assertEqual(reason, "")

    def test_default_allows_floralhealing_at_ally(self):
        config = DoublesDamageAwareConfig()
        battle = _make_battle()
        fh = _make_move("floralhealing")
        order = _make_order(fh, target=-2)
        blocked, reason = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)

    def test_default_allows_decorate_at_ally(self):
        config = DoublesDamageAwareConfig()
        battle = _make_battle()
        dec = _make_move("decorate")
        order = _make_order(dec, target=-2)
        blocked, reason = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)


# ---- 3. Explicit opt-out tests ----

class TestExplicitOptOut(unittest.TestCase):
    """With explicit ``enable_ally_heal_wrong_side_hard_safety=False``,
    the narrow path must NOT block wrong-side ally heal
    moves. Pre-adoption behavior is preserved.
    """

    def test_opt_out_disables_healpulse_block(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = False
        battle = _make_battle()
        hp = _make_move("healpulse")
        order = _make_order(hp, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)

    def test_opt_out_disables_floralhealing_block(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = False
        battle = _make_battle()
        fh = _make_move("floralhealing")
        order = _make_order(fh, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)

    def test_opt_out_disables_decorate_block(self):
        config = DoublesDamageAwareConfig()
        config.enable_ally_heal_wrong_side_hard_safety = False
        battle = _make_battle()
        dec = _make_move("decorate")
        order = _make_order(dec, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)


# ---- 4. Scope guard tests ----

class TestScopeGuard(unittest.TestCase):
    """The narrow flag must not accidentally affect
    non-covered support moves, damaging moves, or
    switch/pass actions.
    """

    def test_non_covered_support_moves_not_blocked(self):
        """Taunt, Encore, Thunder Wave, Skill Swap,
        Pollen Puff, etc. are NOT in the narrow
        allowlist. The narrow path must NOT block them
        even with default config.
        """
        config = DoublesDamageAwareConfig()
        self.assertTrue(
            config.enable_ally_heal_wrong_side_hard_safety
        )
        battle = _make_battle()
        for move_id in [
            "taunt", "encore", "thunderwave", "willowisp",
            "toxic", "skillswap", "pollenpuff", "spore",
            "followme", "ragepowder", "lightscreen",
            "reflect", "tailwind", "trickroom", "haze",
            "clearsmog", "helpinghand", "lifedew",
            "aromatherapy", "healbell", "coaching",
            "howl",
        ]:
            mv = _make_move(move_id)
            order = _make_order(mv, target=1)
            blocked, _ = narrow_ally_heal_wrong_side_block(
                order, 0, battle, config=config
            )
            self.assertFalse(
                blocked,
                f"{move_id} should NOT be blocked by the "
                f"narrow allowlist",
            )

    def test_damaging_moves_not_blocked(self):
        """Damaging moves must not be blocked by the
        narrow path. (Pollen Puff is damaging and dual
        purpose; it should not be blocked.)
        """
        config = DoublesDamageAwareConfig()
        battle = _make_battle()
        for move_id in [
            "thunderbolt", "icebeam", "flamethrower",
            "hydropump", "pollenpuff",  # damaging + dual
            "earthquake", "moonblast", "psychic",
        ]:
            mv = _make_move(
                move_id, base_power=90, category="SPECIAL"
            )
            order = _make_order(mv, target=1)
            blocked, _ = narrow_ally_heal_wrong_side_block(
                order, 0, battle, config=config
            )
            self.assertFalse(
                blocked,
                f"{move_id} should NOT be blocked by the "
                f"narrow path",
            )

    def test_narrow_allowlist_has_exactly_three_moves(self):
        """The narrow allowlist must be exactly the three
        documented moves. If a future PR adds a fourth
        move, the scope of this adoption changes and a
        new phase is required.
        """
        self.assertEqual(
            _NARROW_ALLY_HEAL_MOVE_IDS,
            frozenset({
                "healpulse", "floralhealing", "decorate",
            }),
        )

    def test_protect_not_blocked(self):
        """Protect, Detect, etc. must not be affected by
        the narrow allowlist.
        """
        config = DoublesDamageAwareConfig()
        battle = _make_battle()
        for move_id in [
            "protect", "detect", "spikyshield",
            "kingsshield", "banefulbunker",
        ]:
            mv = _make_move(move_id)
            order = _make_order(mv, target=0)  # self
            blocked, _ = narrow_ally_heal_wrong_side_block(
                order, 0, battle, config=config
            )
            self.assertFalse(blocked)

    def test_switch_action_not_blocked(self):
        """Switch actions are not Move orders, so the
        narrow path must not affect them.
        """
        config = DoublesDamageAwareConfig()
        battle = _make_battle()
        order = MagicMock()
        order.order = None  # not a Move
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertFalse(blocked)


# ---- 5. Regression guard tests ----

class TestRegressionGuard(unittest.TestCase):
    """No species-based ability inference, no Magic
    Bounce species inference, no Anti-TR behavior
    change. WT scoring unchanged.
    """

    def test_narrow_helper_does_not_inspect_species(self):
        """The narrow helper must work the same
        regardless of the active Pokemon's species. We
        verify by passing the same setup with two
        different species names; the blocked flag must
        match (the reason string includes the target
        species, so we only compare the flag).
        """
        config = DoublesDamageAwareConfig()
        battle_a = _make_battle()
        battle_a.active_pokemon[0].species = "blissey"
        battle_a.active_pokemon[1].species = "garchomp"
        battle_b = _make_battle()
        battle_b.active_pokemon[0].species = "hatterene"
        battle_b.active_pokemon[1].species = "incineroar"
        hp = _make_move("healpulse")
        order = _make_order(hp, target=1)
        blocked_a, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle_a, config=config
        )
        blocked_b, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle_b, config=config
        )
        # Same result regardless of species.
        self.assertEqual(blocked_a, blocked_b)
        # And blocked is True since the target is the
        # opponent side.
        self.assertTrue(blocked_a)

    def test_narrow_helper_does_not_inspect_ability(self):
        """The narrow helper must not look at the active
        Pokemon's revealed ability. The decision is
        based solely on move + target side.
        """
        config = DoublesDamageAwareConfig()
        battle_a = _make_battle()
        # No ability field set
        battle_b = _make_battle()
        battle_b.active_pokemon[0].ability = "Magic Bounce"
        battle_b.active_pokemon[1].ability = "Light Rod"
        hp = _make_move("healpulse")
        order = _make_order(hp, target=1)
        blocked_a, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle_a, config=config
        )
        blocked_b, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle_b, config=config
        )
        self.assertEqual(blocked_a, blocked_b)
        self.assertTrue(blocked_a)

    def test_wt_default_unchanged_after_adoption(self):
        """WT scoring must remain default OFF after this
        adoption. This phase does not touch WT.
        """
        config = DoublesDamageAwareConfig()
        self.assertFalse(
            config.enable_weather_terrain_positive_scoring
        )
        self.assertEqual(
            config.weather_terrain_positive_weather_bonus,
            500.0,
        )
        self.assertEqual(
            config.weather_terrain_positive_terrain_bonus,
            400.0,
        )

    def test_anti_tr_unchanged_after_adoption(self):
        """Anti-TR must remain default OFF after this
        adoption. This phase does not touch Anti-TR.
        """
        config = DoublesDamageAwareConfig()
        self.assertFalse(
            config.enable_anti_trick_room_response
        )


# ---- 6. No species-based ability inference — extra guard ----

class TestNoSpeciesAbilityInference(unittest.TestCase):
    """The narrow path must NOT infer Magic Bounce or
    any other ability from the active Pokemon's
    species. The decision is purely move + target.
    """

    def test_hatterene_with_magic_bounce_blocks_healpulse_at_opp(self):
        """Even if a Hatterene-like setup has 'Magic
        Bounce' (just to test the path), Heal Pulse at
        opponent is still blocked — the helper does
        not use ability state.
        """
        config = DoublesDamageAwareConfig()
        battle = _make_battle()
        battle.active_pokemon[0].species = "hatterene"
        battle.active_pokemon[0].ability = "Magic Bounce"
        hp = _make_move("healpulse")
        order = _make_order(hp, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)

    def test_blissey_with_magic_bounce_blocks_decorate_at_opp(self):
        """Blissey-like setup with 'Magic Bounce' must
        not affect the narrow path's decision.
        """
        config = DoublesDamageAwareConfig()
        battle = _make_battle()
        battle.active_pokemon[0].species = "blissey"
        battle.active_pokemon[0].ability = "Magic Bounce"
        dec = _make_move("decorate")
        order = _make_order(dec, target=1)
        blocked, _ = narrow_ally_heal_wrong_side_block(
            order, 0, battle, config=config
        )
        self.assertTrue(blocked)


if __name__ == "__main__":
    unittest.main()
