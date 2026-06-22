"""Phase CONTROL-PRIORITY-2A: Status-move ability safety tests.

Tests for the new opt-in status-move ability safety:
- Magic Bounce (target) - reflected status moves
- Good as Gold (target) - immune to status moves
- Aroma Veil (target) - blocks Taunt/Encore/Disable
- Aroma Veil (target's ally) - blocks via ally protection
- Mold Breaker / Teravolt / Turboblaze (attacker) - bypass

All tests are fixture tests (no battle run), per evidence
ladder level 1.
"""
import unittest
from unittest.mock import MagicMock

from poke_env.battle.move import Move

import ability_rules
from bot_doubles_damage_aware import DoublesDamageAwareConfig


class MockPokemon:
    def __init__(self, species, ability=None, fainted=False):
        self.species = species
        self.ability = ability
        self.fainted = fainted


class MockMove:
    def __init__(self, move_id, category="STATUS", flags=None):
        self.id = move_id
        self.category = category
        self.flags = flags or set()


class MockBattle:
    def __init__(self, opp_active_pokemon):
        self.opponent_active_pokemon = opp_active_pokemon


def make_move(move_id, category="STATUS"):
    """Create a real Move instance for testing."""
    return Move(move_id, gen=9)


class TestShouldAvoidStatusIntoAbility(unittest.TestCase):
    """Tests for the extended should_avoid_status_into_ability helper."""

    def test_magic_bounce_blocks_taunt(self):
        target = MockPokemon("hatterene", ability="magicbounce")
        move = make_move("taunt")
        avoid, reason = ability_rules.should_avoid_status_into_ability(
            target, move
        )
        self.assertTrue(avoid)
        self.assertIn("Magic Bounce", reason)

    def test_good_as_gold_blocks_taunt(self):
        target = MockPokemon("gholdengo", ability="goodasgold")
        move = make_move("taunt")
        avoid, reason = ability_rules.should_avoid_status_into_ability(
            target, move
        )
        self.assertTrue(avoid)
        self.assertIn("Good as Gold", reason)

    def test_aroma_veil_blocks_taunt(self):
        target = MockPokemon("aromatisse", ability="aromaveil")
        move = make_move("taunt")
        avoid, reason = ability_rules.should_avoid_status_into_ability(
            target, move
        )
        self.assertTrue(avoid)
        self.assertIn("Aroma Veil", reason)

    def test_aroma_veil_blocks_encore(self):
        target = MockPokemon("aromatisse", ability="aromaveil")
        move = make_move("encore")
        avoid, reason = ability_rules.should_avoid_status_into_ability(
            target, move
        )
        self.assertTrue(avoid)
        self.assertIn("Aroma Veil", reason)

    def test_aroma_veil_blocks_disable(self):
        target = MockPokemon("aromatisse", ability="aromaveil")
        move = make_move("disable")
        avoid, reason = ability_rules.should_avoid_status_into_ability(
            target, move
        )
        self.assertTrue(avoid)
        self.assertIn("Aroma Veil", reason)

    def test_aroma_veil_does_NOT_block_thunderwave(self):
        """Aroma Veil only blocks Taunt/Encore/Disable (specific moves).
        Thunder Wave is a different status move."""
        target = MockPokemon("aromatisse", ability="aromaveil")
        move = make_move("thunderwave")
        avoid, reason = ability_rules.should_avoid_status_into_ability(
            target, move
        )
        self.assertFalse(avoid)

    def test_taunt_allowed_when_ability_not_revealed(self):
        target = MockPokemon("hatterene", ability=None)
        move = make_move("taunt")
        avoid, _ = ability_rules.should_avoid_status_into_ability(
            target, move
        )
        self.assertFalse(avoid)

    def test_damaging_move_NOT_blocked_vs_magic_bounce(self):
        """Flare Blitz is not a status move, so Magic Bounce doesn't apply."""
        target = MockPokemon("hatterene", ability="magicbounce")
        move = make_move("flareblitz", category="PHYSICAL")
        avoid, _ = ability_rules.should_avoid_status_into_ability(
            target, move
        )
        self.assertFalse(avoid)

    def test_damaging_move_NOT_blocked_vs_aroma_veil(self):
        target = MockPokemon("aromatisse", ability="aromaveil")
        move = make_move("flareblitz", category="PHYSICAL")
        avoid, _ = ability_rules.should_avoid_status_into_ability(
            target, move
        )
        self.assertFalse(avoid)

    def test_mold_breaker_attacker_bypasses_magic_bounce(self):
        """Attacker with Mold Breaker disables target's Magic Bounce."""
        target = MockPokemon("hatterene", ability="magicbounce")
        attacker = MockPokemon("haxorus", ability="moldbreaker")
        move = make_move("taunt")
        avoid, reason = ability_rules.should_avoid_status_into_ability(
            target, move, attacker=attacker
        )
        self.assertFalse(avoid)
        self.assertIn("bypassed", reason)

    def test_teravolt_attacker_bypasses_good_as_gold(self):
        target = MockPokemon("gholdengo", ability="goodasgold")
        attacker = MockPokemon("zekrom", ability="teravolt")
        move = make_move("taunt")
        avoid, reason = ability_rules.should_avoid_status_into_ability(
            target, move, attacker=attacker
        )
        self.assertFalse(avoid)
        self.assertIn("bypassed", reason)

    def test_turboblaze_attacker_bypasses_aroma_veil(self):
        target = MockPokemon("aromatisse", ability="aromaveil")
        attacker = MockPokemon("reshiram", ability="turboblaze")
        move = make_move("taunt")
        avoid, reason = ability_rules.should_avoid_status_into_ability(
            target, move, attacker=attacker
        )
        self.assertFalse(avoid)
        self.assertIn("bypassed", reason)

    def test_no_attacker_means_no_bypass_check(self):
        """When attacker is not provided, bypass check is skipped.
        This is the original behavior (backward compatible)."""
        target = MockPokemon("hatterene", ability="magicbounce")
        move = make_move("taunt")
        avoid, _ = ability_rules.should_avoid_status_into_ability(
            target, move
        )
        self.assertTrue(avoid)


class TestAllyHasAromaVeil(unittest.TestCase):
    """Tests for the new ally_has_aroma_veil helper."""

    def test_ally_has_aroma_veil_returns_true(self):
        target = MockPokemon("hatterene", ability="magicbounce")
        ally = MockPokemon("aromatisse", ability="aromaveil")
        battle = MockBattle([target, ally])
        self.assertTrue(ability_rules.ally_has_aroma_veil(target, battle))

    def test_ally_no_aroma_veil_returns_false(self):
        target = MockPokemon("hatterene", ability="magicbounce")
        ally = MockPokemon("incineroar", ability="intimidate")
        battle = MockBattle([target, ally])
        self.assertFalse(ability_rules.ally_has_aroma_veil(target, battle))

    def test_ally_fainted_returns_false(self):
        target = MockPokemon("hatterene", ability="magicbounce")
        ally = MockPokemon("aromatisse", ability="aromaveil", fainted=True)
        battle = MockBattle([target, ally])
        self.assertFalse(ability_rules.ally_has_aroma_veil(target, battle))

    def test_no_ally_returns_false(self):
        target = MockPokemon("hatterene", ability="magicbounce")
        battle = MockBattle([target, None])
        self.assertFalse(ability_rules.ally_has_aroma_veil(target, battle))

    def test_target_itself_has_aroma_veil_returns_false(self):
        """ally_has_aroma_veil should only check PARTNER, not target itself."""
        target = MockPokemon("aromatisse", ability="aromaveil")
        ally = MockPokemon("hatterene", ability=None)
        battle = MockBattle([target, ally])
        self.assertFalse(ability_rules.ally_has_aroma_veil(target, battle))


class TestConfigFlags(unittest.TestCase):
    """Tests for the new config flags."""

    def test_default_off(self):
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_status_move_ability_safety)

    def test_sub_flags_default_true(self):
        config = DoublesDamageAwareConfig()
        self.assertTrue(config.status_ability_safety_track_magic_bounce)
        self.assertTrue(config.status_ability_safety_track_good_as_gold)
        self.assertTrue(config.status_ability_safety_track_aroma_veil)
        self.assertTrue(config.status_ability_safety_track_aroma_veil_ally)

    def test_flags_can_be_modified(self):
        config = DoublesDamageAwareConfig()
        config.enable_status_move_ability_safety = True
        config.status_ability_safety_track_magic_bounce = False
        config.status_ability_safety_track_good_as_gold = True
        self.assertTrue(config.enable_status_move_ability_safety)
        self.assertFalse(config.status_ability_safety_track_magic_bounce)
        self.assertTrue(config.status_ability_safety_track_good_as_gold)


if __name__ == "__main__":
    unittest.main()
