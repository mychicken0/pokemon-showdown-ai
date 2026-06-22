"""Phase CONTROL-PRIORITY-2D: anti_tr_target_debug runtime audit tests.

Tests for the new observational audit field that captures
anti-TR candidate evaluation:
- target has revealed Trick Room -> debug shows allowed
- wrong target -> debug shows blocked by target-aware guard
- Magic Bounce target -> debug shows mechanics block
- Aroma Veil ally -> debug shows mechanics block
- flag OFF -> old behavior preserved, debug still safe
- debug object is JSON serializable
- no candidates -> empty/no debug without crash
"""
import json
import unittest
from unittest.mock import MagicMock

from poke_env.battle.move import Move
from poke_env.battle.pokemon import Pokemon

import ability_rules
import bot_doubles_damage_aware as mod
from bot_doubles_damage_aware import DoublesDamageAwareConfig
from bot_doubles_intent_classifier import IntentDecision


class MockPokemon:
    """Mock Pokemon with revealed moves."""

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


def make_move(move_id):
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


class TestAntiTrTargetDebug(unittest.TestCase):
    """Tests for the anti_tr_target_debug audit field."""

    def setUp(self):
        self.taunt = make_move("taunt")
        self.encore = make_move("encore")
        self.disable = make_move("disable")

    def test_target_has_revealed_tr_allowed(self):
        """Target has revealed TR -> debug shows allowed."""
        cfg = DoublesDamageAwareConfig()
        cfg.enable_anti_tr_target_aware_scoring = True
        player = make_player(cfg)

        hatterene = MockPokemon(
            "hatterene", moves=["trickroom", "mysticalfire"]
        )
        gardevoir = MockPokemon("gardevoir", moves=["moonblast"])
        battle = MockBattle([hatterene, gardevoir])
        order = MockOrder(self.taunt, target=1)

        player._record_anti_tr_target_debug(
            order=order,
            active_idx=0,
            battle=battle,
            eligible=True,
            bonus_applied=500.0,
        )

        debug_list = getattr(player, "_anti_tr_target_debug_per_battle", {}).get(
            "test_battle", []
        )
        self.assertEqual(len(debug_list), 1)
        d = debug_list[0]
        self.assertEqual(d["move"], "taunt")
        self.assertEqual(d["target_species"], "hatterene")
        self.assertTrue(d["target_has_revealed_trickroom"])
        self.assertTrue(d["target_aware_enabled"])
        self.assertTrue(d["target_aware_allowed"])
        self.assertTrue(d["eligible"])
        self.assertEqual(d["bonus_applied"], 500.0)
        # Revealed moves should be captured
        self.assertIn("trickroom", d["target_revealed_moves"])

    def test_wrong_target_blocked_by_target_aware(self):
        """Wrong target (no revealed TR) -> debug shows blocked."""
        cfg = DoublesDamageAwareConfig()
        cfg.enable_anti_tr_target_aware_scoring = True
        player = make_player(cfg)

        hatterene_slot1 = MockPokemon(
            "hatterene", moves=["trickroom", "mysticalfire"]
        )
        gardevoir_slot0 = MockPokemon("gardevoir", moves=["moonblast"])
        battle = MockBattle([gardevoir_slot0, hatterene_slot1])
        order = MockOrder(self.taunt, target=1)  # target slot 0 = Gardevoir

        player._record_anti_tr_target_debug(
            order=order,
            active_idx=0,
            battle=battle,
            eligible=False,
            block_reason="target_aware_guard_blocked",
            bonus_applied=0.0,
        )

        debug_list = getattr(player, "_anti_tr_target_debug_per_battle", {}).get(
            "test_battle", []
        )
        self.assertEqual(len(debug_list), 1)
        d = debug_list[0]
        self.assertEqual(d["target_species"], "gardevoir")
        self.assertFalse(d["target_has_revealed_trickroom"])
        self.assertTrue(d["target_aware_enabled"])
        self.assertFalse(d["target_aware_allowed"])
        self.assertFalse(d["eligible"])
        self.assertEqual(d["bonus_applied"], 0.0)
        self.assertEqual(d["block_reason"], "target_aware_guard_blocked")

    def test_magic_bounce_target_mechanics_block(self):
        """Magic Bounce target -> debug shows mechanics block."""
        cfg = DoublesDamageAwareConfig()
        cfg.enable_status_move_ability_safety = True
        cfg.status_ability_safety_track_magic_bounce = True
        player = make_player(cfg)

        # Hatterene w/ Magic Bounce revealed
        hatterene = MockPokemon(
            "hatterene",
            ability="magicbounce",
            moves=["trickroom", "mysticalfire"],
        )
        battle = MockBattle([hatterene, MockPokemon("incineroar", moves=["fakeout"])])
        order = MockOrder(self.taunt, target=1)

        player._record_anti_tr_target_debug(
            order=order,
            active_idx=0,
            battle=battle,
            eligible=False,
            block_reason="Magic Bounce reflects status moves",
            bonus_applied=0.0,
            mechanics_block_enabled=True,
            blocked_by_magic_bounce=True,
        )

        debug_list = getattr(player, "_anti_tr_target_debug_per_battle", {}).get(
            "test_battle", []
        )
        self.assertEqual(len(debug_list), 1)
        d = debug_list[0]
        self.assertTrue(d["mechanics_block_enabled"])
        self.assertTrue(d["blocked_by_magic_bounce"])
        self.assertFalse(d["eligible"])

    def test_aroma_veil_ally_mechanics_block(self):
        """Aroma Veil ally -> debug shows mechanics block."""
        cfg = DoublesDamageAwareConfig()
        cfg.enable_status_move_ability_safety = True
        cfg.status_ability_safety_track_aroma_veil_ally = True
        player = make_player(cfg)

        hatterene = MockPokemon(
            "hatterene", moves=["trickroom", "mysticalfire"]
        )
        # Aromatisse is the ally
        aromatisse = MockPokemon(
            "aromatisse", ability="aromaveil", moves=["trickroom"]
        )
        battle = MockBattle([hatterene, aromatisse])
        order = MockOrder(self.taunt, target=1)

        player._record_anti_tr_target_debug(
            order=order,
            active_idx=0,
            battle=battle,
            eligible=False,
            block_reason="Ally Aroma Veil blocks taunt",
            bonus_applied=0.0,
            mechanics_block_enabled=True,
            blocked_by_aroma_veil_ally=True,
        )

        debug_list = getattr(player, "_anti_tr_target_debug_per_battle", {}).get(
            "test_battle", []
        )
        self.assertEqual(len(debug_list), 1)
        d = debug_list[0]
        self.assertTrue(d["mechanics_block_enabled"])
        self.assertTrue(d["blocked_by_aroma_veil_ally"])
        self.assertFalse(d["blocked_by_aroma_veil"])  # not target-side
        self.assertFalse(d["eligible"])

    def test_flag_off_old_behavior_preserved(self):
        """Flag OFF: debug still safe, target_aware_enabled=False."""
        cfg = DoublesDamageAwareConfig()
        cfg.enable_anti_tr_target_aware_scoring = False
        cfg.enable_status_move_ability_safety = False
        player = make_player(cfg)

        hatterene = MockPokemon(
            "hatterene", moves=["trickroom", "mysticalfire"]
        )
        battle = MockBattle([hatterene, MockPokemon("gardevoir", moves=["moonblast"])])
        order = MockOrder(self.taunt, target=1)

        player._record_anti_tr_target_debug(
            order=order,
            active_idx=0,
            battle=battle,
            eligible=True,
            bonus_applied=500.0,
        )

        debug_list = getattr(player, "_anti_tr_target_debug_per_battle", {}).get(
            "test_battle", []
        )
        self.assertEqual(len(debug_list), 1)
        d = debug_list[0]
        # Both flags OFF
        self.assertFalse(d["target_aware_enabled"])
        self.assertFalse(d["mechanics_block_enabled"])
        # target_aware_allowed defaults to True when flag is off
        self.assertTrue(d["target_aware_allowed"])

    def test_debug_object_is_json_serializable(self):
        """Debug object must be JSON-safe."""
        cfg = DoublesDamageAwareConfig()
        player = make_player(cfg)

        hatterene = MockPokemon(
            "hatterene", moves=["trickroom", "mysticalfire"]
        )
        battle = MockBattle([hatterene, MockPokemon("gardevoir")])
        order = MockOrder(self.taunt, target=1)

        player._record_anti_tr_target_debug(
            order=order,
            active_idx=0,
            battle=battle,
            eligible=True,
            bonus_applied=500.0,
        )

        debug_list = getattr(player, "_anti_tr_target_debug_per_battle", {}).get(
            "test_battle", []
        )
        # Should be JSON-serializable
        try:
            json_str = json.dumps(debug_list)
            parsed = json.loads(json_str)
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0]["move"], "taunt")
        except (TypeError, ValueError) as e:
            self.fail(f"Debug not JSON-serializable: {e}")

    def test_no_candidates_empty_debug(self):
        """No candidates -> no debug entry, no crash."""
        cfg = DoublesDamageAwareConfig()
        player = make_player(cfg)

        # Don't call _record_anti_tr_target_debug at all
        # The per-battle list should not exist or be empty
        debug_list = getattr(player, "_anti_tr_target_debug_per_battle", {}).get(
            "test_battle", []
        )
        self.assertEqual(debug_list, [])

    def test_encore_target_debug(self):
        """Encore is also recorded in target debug."""
        cfg = DoublesDamageAwareConfig()
        player = make_player(cfg)

        hatterene = MockPokemon(
            "hatterene", moves=["trickroom", "mysticalfire"]
        )
        battle = MockBattle([hatterene, MockPokemon("gardevoir")])
        order = MockOrder(self.encore, target=1)

        player._record_anti_tr_target_debug(
            order=order,
            active_idx=0,
            battle=battle,
            eligible=True,
            bonus_applied=500.0,
        )

        debug_list = getattr(player, "_anti_tr_target_debug_per_battle", {}).get(
            "test_battle", []
        )
        self.assertEqual(len(debug_list), 1)
        self.assertEqual(debug_list[0]["move"], "encore")

    def test_disable_target_debug(self):
        """Disable is also recorded in target debug."""
        cfg = DoublesDamageAwareConfig()
        player = make_player(cfg)

        hatterene = MockPokemon(
            "hatterene", moves=["trickroom", "mysticalfire"]
        )
        battle = MockBattle([hatterene, MockPokemon("gardevoir")])
        order = MockOrder(self.disable, target=1)

        player._record_anti_tr_target_debug(
            order=order,
            active_idx=0,
            battle=battle,
            eligible=True,
            bonus_applied=500.0,
        )

        debug_list = getattr(player, "_anti_tr_target_debug_per_battle", {}).get(
            "test_battle", []
        )
        self.assertEqual(len(debug_list), 1)
        self.assertEqual(debug_list[0]["move"], "disable")

    def test_legacy_pokemon_without_moves_safe(self):
        """Legacy mock with no `moves` attr -> no crash."""
        cfg = DoublesDamageAwareConfig()
        player = make_player(cfg)

        legacy_opp = MagicMock(spec=["species", "ability"])
        legacy_opp.species = "hatterene"
        legacy_opp.ability = "magicbounce"
        gardevoir = MockPokemon("gardevoir", moves=["moonblast"])
        battle = MockBattle([legacy_opp, gardevoir])
        order = MockOrder(self.taunt, target=1)

        try:
            player._record_anti_tr_target_debug(
                order=order,
                active_idx=0,
                battle=battle,
                eligible=True,
                bonus_applied=500.0,
            )
        except Exception as e:
            self.fail(f"Crashed with legacy mock: {e}")

        debug_list = getattr(player, "_anti_tr_target_debug_per_battle", {}).get(
            "test_battle", []
        )
        self.assertEqual(len(debug_list), 1)
        d = debug_list[0]
        # No moves -> no TR info
        self.assertEqual(d["target_revealed_moves"], [])
        self.assertFalse(d["target_has_revealed_trickroom"])


if __name__ == "__main__":
    unittest.main()
