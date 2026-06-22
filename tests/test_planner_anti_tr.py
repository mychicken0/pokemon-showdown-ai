"""PLANNER-ANTI-TR unit tests: Anti-Trick Room response.

Tests for the new TR-specific scoring policy:
- Taunt/Encore/Disable boost when ANTI_TRICK_ROOM intent fires
- KO pressure bonus for damaging moves when ANTI_TRICK_ROOM fires
- Standard anti-spam guards
- Threshold/move checks
"""
import unittest
from unittest.mock import MagicMock

import bot_doubles_damage_aware as mod
from bot_doubles_damage_aware import DoublesDamageAwareConfig
from bot_doubles_intent_classifier import IntentDecision
from poke_env.battle.move import Move


def make_player():
    """Make a player with the anti-TR response enabled."""
    config = DoublesDamageAwareConfig()
    config.enable_anti_trick_room_response = True
    config.anti_trick_room_response_bonus = 500.0
    config.anti_trick_room_ko_bonus = 200.0

    player = mod.DoublesDamageAwarePlayer.__new__(mod.DoublesDamageAwarePlayer)
    player.config = config
    player._anti_trick_room_response_picks_per_game = {}
    player._anti_trick_room_response_last_pick_turn = {}
    player._anti_trick_room_ko_picks_per_game = {}
    player._anti_trick_room_ko_last_pick_turn = {}
    return player


def make_battle_with_intent(intent, opp_revealed_moves=None, has_tr_field=False):
    """Build a battle with a given intent decision."""
    battle = MagicMock()
    battle.battle_tag = "test"
    battle.turn = 3

    # Create decision
    decision = MagicMock()
    decision.intent = intent
    decision.confidence = 0.85
    decision.matched_moves = ("trickroom",) if intent == "ANTI_TRICK_ROOM" else ()
    decision.evidence_source = "revealed_moves"
    decision.routed_to_policy = "anti_setup"
    decision.opp_pressure = True
    setattr(battle, "_planner_intent_decision", decision)

    # Field state
    if has_tr_field:
        tr_field = MagicMock()
        tr_field.name = "TRICK_ROOM"
        battle.fields = [tr_field]
    else:
        battle.fields = []

    battle.side_conditions = {}

    # Active mons
    mon_0 = MagicMock()
    mon_0.species = "garganacl"
    mon_0.current_hp_fraction = 1.0
    mon_0.fainted = False
    mon_1 = MagicMock()
    mon_1.species = "incineroar"
    mon_1.current_hp_fraction = 1.0
    mon_1.fainted = False
    battle.active_pokemon = [mon_0, mon_1]

    # Opp mons
    if opp_revealed_moves is None:
        opp_revealed_moves = [{}, {}]
    opp_0 = MagicMock()
    opp_0.species = "Porygon2"
    opp_0.moves = opp_revealed_moves[0] if len(opp_revealed_moves) > 0 else {}
    opp_1 = MagicMock()
    opp_1.species = "Indeedee"
    opp_1.moves = opp_revealed_moves[1] if len(opp_revealed_moves) > 1 else {}
    battle.opponent_active_pokemon = [opp_0, opp_1]

    return battle


def make_taunt_order(target=1):
    order = MagicMock()
    order.order = Move("taunt", gen=9)
    order.move_target = target
    return order


def make_encore_order(target=1):
    order = MagicMock()
    order.order = Move("encore", gen=9)
    order.move_target = target
    return order


def make_disable_order(target=1):
    order = MagicMock()
    order.order = Move("disable", gen=9)
    order.move_target = target
    return order


def make_damaging_order(target=1, name="bodypress", power=80):
    order = MagicMock()
    order.order = Move(name, gen=9)
    order.move_target = target
    return order


def make_status_order(target=1, name="recover", power=0):
    order = MagicMock()
    order.order = Move(name, gen=9)
    order.move_target = target
    return order


class TestAntiTrickRoomResponse(unittest.TestCase):
    """Test the anti-TR response eligibility."""

    def test_master_switch_off(self):
        """If master switch is OFF, no bonus applies."""
        player = make_player()
        player.config.enable_anti_trick_room_response = False
        battle = make_battle_with_intent("ANTI_TRICK_ROOM")
        order = make_taunt_order()
        result = player._anti_trick_room_response_eligible(order, 0, battle)
        self.assertFalse(result,
            "Master switch OFF: should not be eligible")

    def test_taunt_eligible_when_tr_detected(self):
        """Taunt is eligible when ANTI_TRICK_ROOM intent fires."""
        player = make_player()
        battle = make_battle_with_intent("ANTI_TRICK_ROOM")
        order = make_taunt_order()
        result = player._anti_trick_room_response_eligible(order, 0, battle)
        self.assertTrue(result,
            "Taunt + ANTI_TRICK_ROOM intent: should be eligible")

    def test_encore_eligible_when_tr_detected(self):
        player = make_player()
        battle = make_battle_with_intent("ANTI_TRICK_ROOM")
        order = make_encore_order()
        result = player._anti_trick_room_response_eligible(order, 0, battle)
        self.assertTrue(result, "Encore: should be eligible")

    def test_disable_eligible_when_tr_detected(self):
        player = make_player()
        battle = make_battle_with_intent("ANTI_TRICK_ROOM")
        order = make_disable_order()
        result = player._anti_trick_room_response_eligible(order, 0, battle)
        self.assertTrue(result, "Disable: should be eligible")

    def test_quash_NOT_eligible(self):
        """Quash is not in the anti-TR set (only Taunt/Encore/Disable)."""
        player = make_player()
        battle = make_battle_with_intent("ANTI_TRICK_ROOM")
        order = MagicMock()
        order.order = Move("quash", gen=9)
        order.move_target = 1
        result = player._anti_trick_room_response_eligible(order, 0, battle)
        self.assertFalse(result, "Quash: should NOT be eligible (anti-TR scope)")

    def test_protect_NOT_eligible(self):
        player = make_player()
        battle = make_battle_with_intent("ANTI_TRICK_ROOM")
        order = MagicMock()
        order.order = Move("protect", gen=9)
        order.move_target = -1  # self
        result = player._anti_trick_room_response_eligible(order, 0, battle)
        self.assertFalse(result, "Protect: should NOT be eligible")

    def test_NOT_eligible_when_intent_is_ANTI_TAILWIND(self):
        """If intent is ANTI_TAILWIND, anti-TR doesn't apply."""
        player = make_player()
        battle = make_battle_with_intent("ANTI_TAILWIND")
        order = make_taunt_order()
        result = player._anti_trick_room_response_eligible(order, 0, battle)
        self.assertFalse(result, "ANTI_TAILWIND intent: should not be eligible for anti-TR")

    def test_NOT_eligible_when_intent_is_NO_INTENT(self):
        player = make_player()
        battle = make_battle_with_intent("NO_INTENT")
        order = make_taunt_order()
        result = player._anti_trick_room_response_eligible(order, 0, battle)
        self.assertFalse(result, "NO_INTENT: should not be eligible")

    def test_NOT_eligible_when_intent_is_SPREAD_DEFENSE(self):
        player = make_player()
        battle = make_battle_with_intent("SPREAD_DEFENSE")
        order = make_taunt_order()
        result = player._anti_trick_room_response_eligible(order, 0, battle)
        self.assertFalse(result, "SPREAD_DEFENSE: should not be eligible for anti-TR")

    def test_low_hp_user_not_eligible(self):
        """If user HP < 25%, not eligible (would faint before moving)."""
        player = make_player()
        battle = make_battle_with_intent("ANTI_TRICK_ROOM")
        battle.active_pokemon[0].current_hp_fraction = 0.20
        order = make_taunt_order()
        result = player._anti_trick_room_response_eligible(order, 0, battle)
        self.assertFalse(result, "Low HP user: should not be eligible")

    def test_wrong_target_not_eligible(self):
        """If target is not opp slot, not eligible."""
        player = make_player()
        battle = make_battle_with_intent("ANTI_TRICK_ROOM")
        order = make_taunt_order(target=-1)  # self
        result = player._anti_trick_room_response_eligible(order, 0, battle)
        self.assertFalse(result, "Target=self: should not be eligible")

    def test_anti_spam_max_picks(self):
        """Max picks per game enforced."""
        player = make_player()
        battle = make_battle_with_intent("ANTI_TRICK_ROOM")
        battle.battle_tag = "test-game"
        player._anti_trick_room_response_picks_per_game = {"test-game": 5}
        order = make_taunt_order()
        result = player._anti_trick_room_response_eligible(order, 0, battle)
        self.assertFalse(result, "Max picks reached: should not be eligible")


class TestAntiTrickRoomKOPressure(unittest.TestCase):
    """Test the KO pressure bonus for damaging moves."""

    def test_master_switch_off(self):
        player = make_player()
        player.config.enable_anti_trick_room_response = False
        battle = make_battle_with_intent("ANTI_TRICK_ROOM")
        order = make_damaging_order()
        result = player._anti_trick_room_ko_pressure_eligible(order, 0, battle)
        self.assertFalse(result, "Master switch OFF: should not be eligible")

    def test_damaging_move_eligible_when_tr_detected(self):
        player = make_player()
        battle = make_battle_with_intent("ANTI_TRICK_ROOM")
        order = make_damaging_order()
        result = player._anti_trick_room_ko_pressure_eligible(order, 0, battle)
        self.assertTrue(result, "Damaging move + ANTI_TRICK_ROOM: should be eligible")

    def test_status_move_NOT_eligible(self):
        player = make_player()
        battle = make_battle_with_intent("ANTI_TRICK_ROOM")
        order = make_status_order(name="recover", power=0)
        result = player._anti_trick_room_ko_pressure_eligible(order, 0, battle)
        self.assertFalse(result, "Status move: should not be eligible for KO pressure")

    def test_NOT_eligible_without_tr_intent(self):
        player = make_player()
        battle = make_battle_with_intent("ANTI_TAILWIND")
        order = make_damaging_order()
        result = player._anti_trick_room_ko_pressure_eligible(order, 0, battle)
        self.assertFalse(result, "No TR intent: should not be eligible")


if __name__ == "__main__":
    unittest.main()
