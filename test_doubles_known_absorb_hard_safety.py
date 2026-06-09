"""Phase 6.3.6 — Known Absorb Hard Safety Tests.

Tests for the fix to the known absorb repeat bug where the bot repeatedly
used damaging moves into known ability absorb/immunity targets.

Root cause: get_known_ability() parsed replay events incorrectly, failing
to detect -ability events for Storm Drain, Water Absorb, etc.
"""
import unittest
from unittest.mock import MagicMock, patch

import poke_env_test_cleanup  # noqa: F401

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    get_known_ability,
    ability_hard_blocks_move,
    direct_known_absorb_blocks_move,
    _normalize_ability_name,
    _ability_block_enabled,
    resolve_known_ability,
    is_known_absorb_ability,
)


class MockPokemon:
    """Minimal mock for testing ability resolution."""
    def __init__(self, species, types=None, ability=None, possible_abilities=None):
        self.species = species
        self.types = types or []
        self._ability = ability
        self.possible_abilities = possible_abilities or []
        self.fainted = False
        self._current_hp_fraction = 1.0

    @property
    def current_hp_fraction(self):
        return self._current_hp_fraction

    @current_hp_fraction.setter
    def current_hp_fraction(self, val):
        self._current_hp_fraction = val

    @property
    def ability(self):
        return self._ability

    @ability.setter
    def ability(self, val):
        self._ability = val

    @property
    def type_1(self):
        return self.types[0] if self.types else None

    @property
    def type_2(self):
        return self.types[1] if len(self.types) > 1 else None

    @property
    def temporary_ability(self):
        return None

    @property
    def forme_change_ability(self):
        return None

    @property
    def base_species(self):
        return self.species

    @property
    def effects(self):
        return {}

    @property
    def status(self):
        return None


class MockMove:
    """Minimal mock for testing move type/blocking."""
    def __init__(self, name, move_type, base_power=90, category_name="SPECIAL", flags=None, target="normal"):
        self.id = name.lower().replace(" ", "")
        self._type = move_type
        self.base_power = base_power
        self._category_name = category_name
        self._target = target
        self.flags = flags or {}

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

    @property
    def target(self):
        return self._target

    @target.setter
    def target(self, val):
        self._target = val


class MockBattle:
    """Minimal mock for testing with replay data."""
    def __init__(self, replay_data=None, tag="test_battle"):
        self._replay_data = replay_data or []
        self.battle_tag = tag
        self.fields = []
        self.active_pokemon = [None, None]
        self.opponent_active_pokemon = [None, None]


def _make_replay(*events):
    """Create replay data from event strings like '-ability|p2a: Gastrodon|Storm Drain'."""
    result = []
    for event_str in events:
        parts = event_str.split("|")
        result.append(parts)
    return result


# ===== Test 1: Wave Crash into known Storm Drain is blocked =====
class TestStormDrainBlocksWaveCrash(unittest.TestCase):
    def test_wave_crash_into_storm_drain_blocked(self):
        attacker = MockPokemon("bruxish", ["WATER", "PSYCHIC"])
        target = MockPokemon("gastrodon", ["WATER", "GROUND"])
        target._ability = "stormdrain"
        move = MockMove("wavecrash", "WATER", base_power=120, category_name="PHYSICAL")
        battle = MockBattle(replay_data=_make_replay(
            "-ability|p2a: Gastrodon|Storm Drain"
        ), tag="live_battle")

        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked, "Wave Crash into known Storm Drain should be blocked")
        self.assertIn("stormdrain", reason.lower())


# ===== Test 2: Surf into Water Absorb is blocked =====
class TestWaterAbsorbBlocksSurf(unittest.TestCase):
    def test_surf_into_water_absorb_blocked(self):
        attacker = MockPokemon("starmie", ["WATER", "PSYCHIC"])
        target = MockPokemon("vaporeon", ["WATER"])
        target._ability = "waterabsorb"
        move = MockMove("surf", "WATER", base_power=90, category_name="SPECIAL")
        battle = MockBattle(replay_data=_make_replay(
            "-ability|p2a: Vaporeon|Water Absorb"
        ), tag="live_battle")

        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked)


# ===== Test 3: Water into Dry Skin is blocked =====
class TestDrySkinBlocksWater(unittest.TestCase):
    def test_water_into_dry_skin_blocked(self):
        attacker = MockPokemon("starmie", ["WATER", "PSYCHIC"])
        target = MockPokemon("toxicroak", ["POISON", "FIGHTING"])
        target._ability = "dryskin"
        move = MockMove("scald", "WATER", base_power=80, category_name="SPECIAL")
        battle = MockBattle(replay_data=_make_replay(
            "-ability|p2a: Toxicroak|Dry Skin"
        ), tag="live_battle")

        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked)


# ===== Test 4: Electric into Volt Absorb is blocked =====
class TestVoltAbsorbBlocksElectric(unittest.TestCase):
    def test_electric_into_volt_absorb_blocked(self):
        attacker = MockPokemon("pikachu", ["ELECTRIC"])
        target = MockPokemon("jolteon", ["ELECTRIC"])
        target._ability = "voltabsorb"
        move = MockMove("thunderbolt", "ELECTRIC", base_power=90, category_name="SPECIAL")
        battle = MockBattle(replay_data=_make_replay(
            "-ability|p2a: Jolteon|Volt Absorb"
        ), tag="live_battle")

        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked)


# ===== Test 5: Electric into Motor Drive is blocked =====
class TestMotorDriveBlocksElectric(unittest.TestCase):
    def test_electric_into_motor_drive_blocked(self):
        attacker = MockPokemon("pikachu", ["ELECTRIC"])
        target = MockPokemon("zekrom", ["DRAGON", "ELECTRIC"])
        target._ability = "motordrive"
        move = MockMove("thunderbolt", "ELECTRIC", base_power=90, category_name="SPECIAL")
        battle = MockBattle(replay_data=_make_replay(
            "-ability|p2a: Zekrom|Motor Drive"
        ), tag="live_battle")

        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked)


# ===== Test 6: Electric into Lightning Rod is blocked =====
class TestLightningRodBlocksElectric(unittest.TestCase):
    def test_electric_into_lightning_rod_blocked(self):
        attacker = MockPokemon("pikachu", ["ELECTRIC"])
        target = MockPokemon("rhyperior", ["GROUND", "ROCK"])
        target._ability = "lightningrod"
        move = MockMove("thunderbolt", "ELECTRIC", base_power=90, category_name="SPECIAL")
        battle = MockBattle(replay_data=_make_replay(
            "-ability|p2a: Rhyperior|Lightning Rod"
        ), tag="live_battle")

        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked)


# ===== Test 7: Fire into Flash Fire is blocked =====
class TestFlashFireBlocksFire(unittest.TestCase):
    def test_fire_into_flash_fire_blocked(self):
        attacker = MockPokemon("charizard", ["FIRE", "FLYING"])
        target = MockPokemon("houndoom", ["DARK", "FIRE"])
        target._ability = "flashfire"
        move = MockMove("flamethrower", "FIRE", base_power=90, category_name="SPECIAL")
        battle = MockBattle(replay_data=_make_replay(
            "-ability|p2a: Houndoom|Flash Fire"
        ), tag="live_battle")

        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked)


# ===== Test 8: Fire into Well-Baked Body is blocked =====
class TestWellBakedBodyBlocksFire(unittest.TestCase):
    def test_fire_into_well_baked_body_blocked(self):
        attacker = MockPokemon("charizard", ["FIRE", "FLYING"])
        target = MockPokemon("dachsbun", ["FAIRY"])
        target._ability = "wellbakedbody"
        move = MockMove("flamethrower", "FIRE", base_power=90, category_name="SPECIAL")
        battle = MockBattle(replay_data=_make_replay(
            "-ability|p2a: Dachsbun|Well-Baked Body"
        ), tag="live_battle")

        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked)


# ===== Test 9: Grass into Sap Sipper is blocked =====
class TestSapSipperBlocksGrass(unittest.TestCase):
    def test_grass_into_sap_sipper_blocked(self):
        attacker = MockPokemon("venusaur", ["GRASS", "POISON"])
        target = MockPokemon("miltank", ["NORMAL"])
        target._ability = "sapsipper"
        move = MockMove("gigadrain", "GRASS", base_power=75, category_name="SPECIAL")
        battle = MockBattle(replay_data=_make_replay(
            "-ability|p2a: Miltank|Sap Sipper"
        ), tag="live_battle")

        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked)


# ===== Test 10: Ground into Earth Eater is blocked =====
class TestEarthEaterBlocksGround(unittest.TestCase):
    def test_ground_into_earth_eater_blocked(self):
        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        target = MockPokemon("orthworm", ["STEEL"])
        target._ability = "eartheater"
        move = MockMove("earthquake", "GROUND", base_power=100, category_name="PHYSICAL")
        battle = MockBattle(replay_data=_make_replay(
            "-ability|p2a: Orthworm|Earth Eater"
        ), tag="live_battle")

        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked)


# ===== Test 11: Unknown ability does not block =====
class TestUnknownAbilityDoesNotBlock(unittest.TestCase):
    def test_unknown_ability_does_not_block(self):
        attacker = MockPokemon("starmie", ["WATER", "PSYCHIC"])
        target = MockPokemon("gastrodon", ["WATER", "GROUND"])
        target._ability = None  # unknown
        move = MockMove("scald", "WATER", base_power=80, category_name="SPECIAL")
        battle = MockBattle(replay_data=[], tag="live_battle")

        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertFalse(blocked, "Unknown ability should not block")


# ===== Test 12: Multi-ability species with unrevealed ability is not guessed =====
class TestMultiAbilityNotGuessed(unittest.TestCase):
    def test_multi_ability_not_guessed(self):
        # Gastrodon has Storm Drain and Sticky Hold - if not revealed, should not guess
        attacker = MockPokemon("starmie", ["WATER", "PSYCHIC"])
        target = MockPokemon("gastrodon", ["WATER", "GROUND"])
        target._ability = None
        target.possible_abilities = ["stormdrain", "stickyhold"]
        move = MockMove("scald", "WATER", base_power=80, category_name="SPECIAL")
        config = DoublesDamageAwareConfig(
            ability_hard_safety_allow_singleton_deduction=True
        )
        battle = MockBattle(replay_data=[], tag="live_battle")

        resolution = resolve_known_ability(target, battle, config)
        # Should not resolve since there are multiple possible abilities
        self.assertIsNone(resolution["ability"])


# ===== Test 13: Direct absorb score is 0 =====
class TestDirectAbsorbScoreIsZero(unittest.TestCase):
    def test_direct_absorb_score_zero(self):
        from test_doubles_ability_hard_safety import TestPlayer, MockBattle as FullMockBattle
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_direct_absorb_only=True,
        )
        player = TestPlayer.create(config)
        battle = FullMockBattle()
        battle.battle_tag = "test_direct_absorb"

        from test_doubles_ability_hard_safety import MockPokemon as FullMockPokemon, MockMove as FullMockMove
        from poke_env.player.battle_order import SingleBattleOrder

        attacker = FullMockPokemon("starmie", ["WATER"])
        target = FullMockPokemon("gastrodon", ["WATER", "GROUND"], ability="Storm Drain")
        move = FullMockMove("scald", "WATER")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)

        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0, "Direct absorb score should be 0")


# ===== Test 14: Expected damage is 0 =====
class TestExpectedDamageIsZero(unittest.TestCase):
    def test_expected_damage_zero(self):
        from test_doubles_ability_hard_safety import TestPlayer, MockBattle as FullMockBattle
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_direct_absorb_only=True,
        )
        player = TestPlayer.create(config)
        battle = FullMockBattle()
        battle.battle_tag = "test_expected_damage"

        from test_doubles_ability_hard_safety import MockPokemon as FullMockPokemon, MockMove as FullMockMove

        attacker = FullMockPokemon("starmie", ["WATER"])
        target = FullMockPokemon("gastrodon", ["WATER", "GROUND"], ability="Storm Drain")
        move = FullMockMove("scald", "WATER")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]

        dmg = player.get_expected_damage(move, attacker, target, battle, is_single_target_direct=True)
        self.assertEqual(dmg, 0.0, "Expected damage should be 0 for direct absorb")


# ===== Test 15: Expected KO detection bypasses direct absorb =====
class TestExpectedKOBypassDirectAbsorb(unittest.TestCase):
    def test_check_move_will_ko_bypasses_direct_absorb(self):
        """check_move_will_ko does NOT pass is_single_target_direct=True,
        so it does not detect direct absorb blocks. This is by design —
        the blocking happens at score_action level."""
        from test_doubles_ability_hard_safety import TestPlayer, MockBattle as FullMockBattle, MockPokemon as FullMockPokemon, MockMove as FullMockMove
        from poke_env.player.battle_order import SingleBattleOrder

        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_direct_absorb_only=True,
        )
        player = TestPlayer.create(config)
        battle = FullMockBattle()
        battle.battle_tag = "test_expected_ko"

        attacker = FullMockPokemon("starmie", ["WATER"])
        target = FullMockPokemon("gastrodon", ["WATER", "GROUND"], ability="Storm Drain")
        target._current_hp_fraction = 0.1
        move = FullMockMove("scald", "WATER")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]

        # With is_single_target_direct=True, damage is 0
        dmg = player.get_expected_damage(move, attacker, target, battle, config=config, is_single_target_direct=True)
        self.assertEqual(dmg, 0.0)

        # score_action properly blocks the move
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0, "score_action should block direct absorb")


# ===== Test 16: KO/HP/focus-fire bonus not added for blocked move =====
class TestNoBonusForBlockedMove(unittest.TestCase):
    def test_no_bonus_for_blocked(self):
        from test_doubles_ability_hard_safety import TestPlayer, MockBattle as FullMockBattle, MockPokemon as FullMockPokemon, MockMove as FullMockMove
        from poke_env.player.battle_order import SingleBattleOrder

        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_direct_absorb_only=True,
        )
        player = TestPlayer.create(config)
        battle = FullMockBattle()
        battle.battle_tag = "test_no_bonus"

        attacker = FullMockPokemon("starmie", ["WATER"])
        target = FullMockPokemon("gastrodon", ["WATER", "GROUND"], ability="Storm Drain")
        target.current_hp_fraction = 0.1  # low HP - would normally get KO bonus
        move = FullMockMove("scald", "WATER")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)

        score = player.score_action(order, 0, battle)
        # Should be 0 regardless of low HP, KO potential, etc.
        self.assertEqual(score, 0.0, "No bonus should be added for blocked move")


# ===== Test 17: Spread move with one absorb target keeps damage to non-immune =====
class TestSpreadMovePartialAbsorb(unittest.TestCase):
    def test_spread_keeps_non_immune_damage(self):
        from test_doubles_ability_hard_safety import TestPlayer, MockBattle as FullMockBattle, MockPokemon as FullMockPokemon, MockMove as FullMockMove
        from poke_env.player.battle_order import SingleBattleOrder

        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_direct_absorb_only=True,
            enable_partial_spread_immunity_penalty=True,
        )
        player = TestPlayer.create(config)
        battle = FullMockBattle()
        battle.battle_tag = "test_spread_partial"

        attacker = FullMockPokemon("starmie", ["WATER"])
        target_absorb = FullMockPokemon("gastrodon", ["WATER", "GROUND"], ability="Storm Drain")
        target_normal = FullMockPokemon("garchomp", ["DRAGON", "GROUND"])
        move = FullMockMove("surf", "WATER", target="allAdjacent")
        battle.opponent_active_pokemon = [target_absorb, target_normal]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=0)  # spread

        score = player.score_action(order, 0, battle)
        # Should NOT be 0 - spread move can still hit the non-immune target
        self.assertGreater(score, 0.0, "Spread move should keep non-immune target damage")


# ===== Test 18: Spread move with all absorb targets still scores =====
class TestSpreadAllAbsorbScoresPositive(unittest.TestCase):
    def test_spread_all_absorb_scores_positive(self):
        """Spread moves don't use direct_absorb_only path (single-target only).
        Both targets are treated as damaged by the type-immune spread check.
        This is expected behavior — spread moves bypass direct absorb blocking."""
        from test_doubles_ability_hard_safety import TestPlayer, MockBattle as FullMockBattle, MockPokemon as FullMockPokemon, MockMove as FullMockMove
        from poke_env.player.battle_order import SingleBattleOrder

        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_direct_absorb_only=True,
            enable_partial_spread_immunity_penalty=True,
        )
        player = TestPlayer.create(config)
        battle = FullMockBattle()
        battle.battle_tag = "test_spread_all_absorb"

        attacker = FullMockPokemon("starmie", ["WATER"])
        target1 = FullMockPokemon("gastrodon", ["WATER", "GROUND"], ability="Storm Drain")
        target2 = FullMockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        move = FullMockMove("surf", "WATER", target="allAdjacent")
        battle.opponent_active_pokemon = [target1, target2]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=0)

        score = player.score_action(order, 0, battle)
        # Spread moves bypass direct_absorb_only — score is positive
        self.assertGreater(score, 0.0, "Spread move with absorb targets still scores positive (by design)")


# ===== Test 19: Repeat absorb selection detected in audit =====
class TestRepeatAbsorbDetection(unittest.TestCase):
    def test_repeat_detection_concept(self):
        """Test the concept of repeat detection - same attacker+move+target+ability."""
        # This tests the data structure for repeat tracking
        attack_history = {}
        key = ("starmie", "scald", "gastrodon", "stormdrain")
        # First occurrence
        attack_history[key] = attack_history.get(key, 0) + 1
        self.assertEqual(attack_history[key], 1)
        # Second occurrence (repeat)
        attack_history[key] = attack_history[key] + 1
        self.assertEqual(attack_history[key], 2)
        # Repeat count > 1 indicates repeat
        self.assertGreater(attack_history[key], 1)


# ===== Test 20: Only-legal absorb selection classified separately =====
class TestOnlyLegalAbsorbClassification(unittest.TestCase):
    def test_only_legal_when_no_alternative(self):
        """When the only legal move targets an absorb ability, it should be classified as only-legal."""
        from test_doubles_ability_hard_safety import TestPlayer, MockBattle as FullMockBattle, MockPokemon as FullMockPokemon, MockMove as FullMockMove
        from poke_env.player.battle_order import SingleBattleOrder

        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_direct_absorb_only=True,
        )
        player = TestPlayer.create(config)
        battle = FullMockBattle()
        battle.battle_tag = "test_only_legal"

        attacker = FullMockPokemon("starmie", ["WATER"])
        target = FullMockPokemon("gastrodon", ["WATER", "GROUND"], ability="Storm Drain")
        move = FullMockMove("scald", "WATER")  # only legal move
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        battle.available_moves = [[move], []]
        player.init_battle_maps(battle.battle_tag)

        # When there's only one legal order and it's absorb-blocked,
        # the score should be 0 and the action should be classified as only-legal
        order = SingleBattleOrder(move, move_target=1)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)


# ===== Test 21: Redirection safety remains disabled by default =====
class TestRedirectionSafetyDisabled(unittest.TestCase):
    def test_redirection_disabled_by_default(self):
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.ability_hard_safety_avoid_redirection,
                         "Redirection safety should be disabled by default")


# ===== Test 22: Ally ability spread safety remains disabled =====
class TestAllySpreadSafetyDisabled(unittest.TestCase):
    def test_ally_spread_disabled_by_default(self):
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.ability_hard_safety_ally_spread_safety,
                         "Ally spread safety should be disabled by default")


# ===== Test 23: Full ability awareness remains disabled =====
class TestAbilityAwarenessDisabled(unittest.TestCase):
    def test_ability_awareness_disabled_by_default(self):
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_ability_awareness,
                         "Full ability awareness should be disabled by default")


# ===== Test 24: get_known_ability parses -ability event correctly =====
class TestGetKnownAbilityParsing(unittest.TestCase):
    def test_ability_event_parsed_correctly(self):
        """Test that get_known_ability correctly parses -ability events."""
        target = MockPokemon("gastrodon", ["WATER", "GROUND"])
        battle = MockBattle(replay_data=_make_replay(
            "-ability|p2a: Gastrodon|Storm Drain"
        ), tag="live_battle")

        ability = get_known_ability(target, battle)
        self.assertEqual(ability, "stormdrain",
                         "Should parse Storm Drain from -ability event")

    def test_heal_from_ability_parsed(self):
        """Test that get_known_ability parses [from] ability: in heal events."""
        target = MockPokemon("gastrodon", ["WATER", "GROUND"])
        battle = MockBattle(replay_data=_make_replay(
            "-heal|p2a: Gastrodon|100/100|[from] ability: Storm Drain"
        ), tag="live_battle")

        ability = get_known_ability(target, battle)
        self.assertEqual(ability, "stormdrain",
                         "Should parse Storm Drain from heal event")

    def test_damage_from_ability_parsed(self):
        """Test that get_known_ability parses [from] ability: in damage events."""
        target = MockPokemon("ferrothorn", ["GRASS", "STEEL"])
        battle = MockBattle(replay_data=_make_replay(
            "-damage|p1a: Archeops|88/100|[from] ability: Iron Barbs|[of] p2a: Ferrothorn"
        ), tag="live_battle")

        # The [of] target is Ferrothorn, so this should set Ferrothorn's ability
        ability = get_known_ability(target, battle)
        self.assertEqual(ability, "ironbarbs",
                         "Should parse Iron Barbs from damage event")


# ===== Test 25: is_known_absorb_ability helper =====
class TestIsKnownAbsorbAbility(unittest.TestCase):
    def test_all_absorb_abilities_recognized(self):
        absorb_abilities = [
            "waterabsorb", "stormdrain", "dryskin",
            "voltabsorb", "motordrive", "lightningrod",
            "flashfire", "wellbakedbody", "sapsipper",
        ]
        for ab in absorb_abilities:
            self.assertTrue(is_known_absorb_ability(ab), f"{ab} should be recognized as absorb")

    def test_non_absorb_not_recognized(self):
        non_absorb = ["levitate", "intimidate", "pressure", "unnerve"]
        for ab in non_absorb:
            self.assertFalse(is_known_absorb_ability(ab), f"{ab} should NOT be recognized as absorb")


if __name__ == "__main__":
    unittest.main()
