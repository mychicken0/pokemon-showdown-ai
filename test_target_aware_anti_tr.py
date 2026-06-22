"""Phase CONTROL-PRIORITY-2C: Target-aware anti-TR scoring tests."""
import unittest
from unittest.mock import MagicMock

from poke_env.battle.move import Move

import ability_rules
import bot_doubles_damage_aware as mod
from bot_doubles_damage_aware import DoublesDamageAwareConfig
from bot_doubles_intent_classifier import IntentDecision


class MockPokemon:
    def __init__(self, species, ability=None, moves=None, fainted=False):
        self.species = species
        self.ability = ability
        self.moves = moves or []
        self.fainted = fainted


class MockOrder:
    def __init__(self, move, target):
        self.order = move
        self.move_target = target


class MockBattle:
    def __init__(self, opp_active_pokemon, our_active_pokemon=None, hp_frac=1.0, turn=2):
        self.opponent_active_pokemon = opp_active_pokemon
        self.active_pokemon = our_active_pokemon or []
        self.battle_tag = "test_battle"
        self.turn = turn
        self._planner_intent_decision = IntentDecision(
            intent="ANTI_TRICK_ROOM",
            confidence=1.0,
            evidence_source="revealed_moves",
            matched_moves=("trickroom",),
            routed_to_policy="anti_setup",
            opp_pressure=False,
        )


def make_move(move_id, category="STATUS"):
    return Move(move_id, gen=9)


def make_player(config=None):
    cfg = config or DoublesDamageAwareConfig()
    cfg.enable_anti_trick_room_response = True
    cfg.anti_trick_room_response_bonus = 500.0
    cfg.anti_trick_room_ko_bonus = 200.0
    player = mod.DoublesDamageAwarePlayer.__new__(mod.DoublesDamageAwarePlayer)
    player.config = cfg
    player._anti_trick_room_response_picks_per_game = {}
    player._anti_trick_room_response_last_pick_turn = {}
    player._anti_trick_room_ko_picks_per_game = {}
    player._anti_trick_room_ko_last_pick_turn = {}
    return player


def call_eligible(player, order, active_idx, battle):
    return mod.DoublesDamageAwarePlayer._anti_trick_room_response_eligible(
        player, order, active_idx, battle
    )


class TestOppHasTrickRoom(unittest.TestCase):
    def test_opp_with_tr_returns_true(self):
        opp = MockPokemon("hatterene", moves=["trickroom", "mysticalfire"])
        self.assertTrue(ability_rules.opp_has_trick_room(opp))

    def test_opp_without_tr_returns_false(self):
        opp = MockPokemon("incineroar", moves=["fakeout", "flareblitz"])
        self.assertFalse(ability_rules.opp_has_trick_room(opp))

    def test_opp_with_dash_in_id(self):
        opp = MockPokemon("hatterene", moves=["trick-room"])
        self.assertTrue(ability_rules.opp_has_trick_room(opp))

    def test_opp_with_underscore_in_id(self):
        opp = MockPokemon("hatterene", moves=["trick_room"])
        self.assertTrue(ability_rules.opp_has_trick_room(opp))

    def test_opp_no_moves_returns_false(self):
        opp = MockPokemon("hatterene", moves=[])
        self.assertFalse(ability_rules.opp_has_trick_room(opp))

    def test_opp_none_returns_false(self):
        self.assertFalse(ability_rules.opp_has_trick_room(None))


class TestTargetAwareAntiTREligible(unittest.TestCase):
    def setUp(self):
        self.taunt = make_move("taunt")
        self.encore = make_move("encore")
        self.disable = make_move("disable")

    def test_flag_off_preserves_old_behavior(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_anti_tr_target_aware_scoring = False
        player = make_player(cfg)
        hatterene = MockPokemon("hatterene", moves=["mysticalfire"])
        gardevoir = MockPokemon("gardevoir", moves=["moonblast"])
        battle = MockBattle([hatterene, gardevoir])
        order = MockOrder(self.taunt, target=1)
        result = call_eligible(player, order, 0, battle)
        self.assertTrue(result)  # Flag OFF: existing behavior

    def test_flag_on_target_revealed_tr_allows_bonus(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_anti_tr_target_aware_scoring = True
        player = make_player(cfg)
        hatterene = MockPokemon("hatterene", moves=["trickroom", "mysticalfire"])
        gardevoir = MockPokemon("gardevoir", moves=["moonblast"])
        battle = MockBattle([hatterene, gardevoir])
        order = MockOrder(self.taunt, target=1)
        result = call_eligible(player, order, 0, battle)
        self.assertTrue(result)  # Target has TR, allow bonus

    def test_flag_on_wrong_target_blocks_bonus(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_anti_tr_target_aware_scoring = True
        player = make_player(cfg)
        hatterene_slot1 = MockPokemon("hatterene", moves=["trickroom", "mysticalfire"])
        gardevoir_slot0 = MockPokemon("gardevoir", moves=["moonblast"])
        battle = MockBattle([gardevoir_slot0, hatterene_slot1])
        order = MockOrder(self.taunt, target=1)
        result = call_eligible(player, order, 0, battle)
        self.assertFalse(result)

    def test_flag_on_species_known_but_tr_not_revealed_blocks(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_anti_tr_target_aware_scoring = True
        player = make_player(cfg)
        hatterene_no_reveal = MockPokemon("hatterene", moves=["mysticalfire", "psyshock", "protect"])
        gardevoir = MockPokemon("gardevoir", moves=["moonblast"])
        battle = MockBattle([hatterene_no_reveal, gardevoir])
        order = MockOrder(self.taunt, target=1)
        result = call_eligible(player, order, 0, battle)
        self.assertFalse(result)

    def test_encore_uses_same_target_aware_guard(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_anti_tr_target_aware_scoring = True
        player = make_player(cfg)
        hatterene = MockPokemon("hatterene", moves=["trickroom"])
        gardevoir = MockPokemon("gardevoir", moves=["moonblast"])
        battle = MockBattle([hatterene, gardevoir])
        order = MockOrder(self.encore, target=2)
        result = call_eligible(player, order, 0, battle)
        self.assertFalse(result)

    def test_disable_uses_same_target_aware_guard(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_anti_tr_target_aware_scoring = True
        player = make_player(cfg)
        hatterene = MockPokemon("hatterene", moves=["trickroom"])
        gardevoir = MockPokemon("gardevoir", moves=["moonblast"])
        battle = MockBattle([hatterene, gardevoir])
        order = MockOrder(self.disable, target=2)
        result = call_eligible(player, order, 0, battle)
        self.assertFalse(result)

    def test_legacy_mock_without_moves_is_safe(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_anti_tr_target_aware_scoring = True
        player = make_player(cfg)
        legacy_opp = MagicMock(spec=["species", "ability"])
        legacy_opp.species = "hatterene"
        legacy_opp.ability = "magicbounce"
        gardevoir = MockPokemon("gardevoir", moves=["moonblast"])
        battle = MockBattle([legacy_opp, gardevoir])
        order = MockOrder(self.taunt, target=1)
        try:
            result = call_eligible(player, order, 0, battle)
            self.assertFalse(result)  # No moves = no TR info = block (conservative)
        except Exception as e:
            self.fail(f"Crashed with: {e}")


class TestConfigFlags(unittest.TestCase):
    def test_default_off(self):
        cfg = DoublesDamageAwareConfig()
        self.assertFalse(cfg.enable_anti_tr_target_aware_scoring)

    def test_flag_can_be_modified(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_anti_tr_target_aware_scoring = True
        self.assertTrue(cfg.enable_anti_tr_target_aware_scoring)


if __name__ == "__main__":
    unittest.main()
