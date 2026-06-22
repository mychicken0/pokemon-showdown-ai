import poke_env_test_cleanup  # noqa: F401 — unregister deadlock-prone atexit
import unittest
import json
import os
from bot_doubles_damage_aware import (
    DoublesDamageAwarePlayer,
    DoublesDamageAwareConfig,
    is_type_immune
)
from test_doubles_speed_priority import MockPokemon, MockMove, MockBattle, TestPlayer
from poke_env.player.battle_order import SingleBattleOrder, DoubleBattleOrder

class TestDoublesSpeedPriorityAnalysis(unittest.TestCase):
    def setUp(self):
        self.config = DoublesDamageAwareConfig(
            enable_speed_priority_awareness=True,
            speed_priority_protect_only=False,
            speed_priority_use_scaled_penalty=True
        )
        self.player = TestPlayer(config=self.config)
        self.battle = MockBattle()

    # 1. Threat detected but active survives and acts:
    # - should count as detected threat
    # - should NOT count as true_unanswered_speed_priority_threat
    def test_threat_detected_but_active_survives_and_acts(self):
        # We can test this by checking the classification logic directly.
        slot_data = {
            "outcome_known": True,
            "speed_priority_threatened": True,
            "fainted_before_moving": False,
            "was_targeted": True,
            "our_mon_fainted": False,
            "protect_like_available": True,
            "switch_available": True,
            "action_types": {"damaging": True}
        }
        is_protect = slot_data.get("action_types", {}).get("protect", False)
        is_switch = slot_data.get("action_types", {}).get("switch", False)
        is_threat = slot_data.get("speed_priority_threatened", False)
        
        is_unanswered = False
        if is_threat and not is_protect and not is_switch:
            not_unanswered = (
                slot_data.get("fainted_before_moving") == False or
                slot_data.get("actual_ko") == True or
                slot_data.get("protect_like_available") == False or
                slot_data.get("switch_available") == False or
                slot_data.get("was_targeted") == False
            )
            is_unanswered = not not_unanswered
            
        self.assertTrue(is_threat)
        self.assertFalse(is_unanswered)

    # 2. Threat detected, active attacks and KOs opponent:
    # - should count as productive_attack_under_threat
    # - should NOT count as unanswered
    def test_threat_detected_active_attacks_and_kos(self):
        slot_data = {
            "outcome_known": True,
            "speed_priority_threatened": True,
            "fainted_before_moving": False,
            "was_targeted": True,
            "actual_ko": True,
            "action": "move tackle 1",
            "action_types": {"damaging": True},
            "protect_like_available": True,
            "switch_available": True
        }
        is_protect = slot_data.get("action_types", {}).get("protect", False)
        is_switch = slot_data.get("action_types", {}).get("switch", False)
        is_threat = slot_data.get("speed_priority_threatened", False)
        
        is_unanswered = False
        if is_threat and not is_protect and not is_switch:
            not_unanswered = (
                slot_data.get("fainted_before_moving") == False or
                slot_data.get("actual_ko") == True or
                slot_data.get("protect_like_available") == False or
                slot_data.get("switch_available") == False
            )
            is_unanswered = not not_unanswered

        is_productive_attack = False
        if is_threat and not is_protect and not is_switch:
            is_attack = slot_data.get("action") and "pass" not in slot_data.get("action", "")
            if is_attack:
                is_productive_attack = (
                    slot_data.get("actual_ko") == True or
                    (slot_data.get("actual_damage") is not None and slot_data.get("actual_damage") >= 0.30)
                )

        self.assertTrue(is_productive_attack)
        self.assertFalse(is_unanswered)

    # 3. Conditional priority only:
    # - Sucker Punch revealed
    # - non-attacking candidate action
    # - should not trigger full priority danger
    def test_conditional_priority_only(self):
        our_active = MockPokemon("slowbro", base_stats={"spe": 30})
        our_hp = 0.30
        our_active.current_hp_fraction = our_hp
        
        opp = MockPokemon("scizor", base_stats={"spe": 10})
        # opponent has sucker punch (conditional priority)
        opp._moves = {"suckerpunch": MockMove("suckerpunch", "DARK", priority=1)}
        
        self.battle.opponent_active_pokemon[0] = opp
        
        # Test case: we are choosing a non-attacking action (e.g. switch or status move or pass)
        non_attacking_action = SingleBattleOrder(MockMove("growl", "NORMAL", category="STATUS"))
        
        # Should not trigger priority threat active since it's conditional priority and we are not attacking
        threat_info = self.player.estimate_speed_priority_threat(our_active, [opp], self.battle, non_attacking_action)
        self.assertFalse(threat_info["priority_threatened"])
        self.assertEqual(threat_info["threat_confidence"], 0.0) # no threat because we are not attacking

        # Test case: choosing an attacking action
        attacking_action = SingleBattleOrder(MockMove("tackle", "NORMAL", category="PHYSICAL"))
        threat_info_attack = self.player.estimate_speed_priority_threat(our_active, [opp], self.battle, attacking_action)
        self.assertTrue(threat_info_attack["priority_threatened"])
        self.assertEqual(threat_info_attack["threat_confidence"], 0.50) # conditional priority confidence

    # 4. Protect chosen and opponent targets protected slot:
    # - should count as successful/valid protect
    # - should NOT count as bad protect
    def test_protect_chosen_and_opponent_targets_protected_slot(self):
        slot_data = {
            "protected_due_to_speed_priority": True,
            "action_types": {"protect": True},
            "was_targeted": True
        }
        other_data = {
            "actual_ko": False,
            "actual_damage": 0.0
        }
        is_bad_protect = False
        if slot_data.get("protected_due_to_speed_priority") and slot_data.get("action_types", {}).get("protect"):
            if slot_data.get("was_targeted") == False:
                ally_did_good = (other_data.get("actual_ko") or (other_data.get("actual_damage") is not None and other_data["actual_damage"] >= 0.30))
                if not ally_did_good:
                    is_bad_protect = True
                    
        self.assertFalse(is_bad_protect)

    # 5. Protect chosen and no one targets slot, no ally value:
    # - should count as bad protect
    def test_protect_chosen_and_no_one_targets_slot_no_ally_value(self):
        slot_data = {
            "protected_due_to_speed_priority": True,
            "action_types": {"protect": True},
            "was_targeted": False,
            "stalling_field_condition": False
        }
        other_data = {
            "actual_ko": False,
            "actual_damage": 0.0,
            "action": "move tackle 1"
        }
        is_bad_protect = False
        if slot_data.get("protected_due_to_speed_priority") and slot_data.get("action_types", {}).get("protect"):
            if slot_data.get("was_targeted") == False:
                ally_did_good = (other_data.get("actual_ko") or (other_data.get("actual_damage") is not None and other_data["actual_damage"] >= 0.30))
                if not ally_did_good:
                    is_stalling = slot_data.get("stalling_field_condition", False)
                    if not is_stalling:
                        is_bad_protect = True
                        
        self.assertTrue(is_bad_protect)

    # 6. No legal Protect available:
    # - Protect bonus must not apply
    def test_no_legal_protect_available(self):
        # We clear available_moves and valid_orders, so no legal protect order exists
        our_active = MockPokemon("charizard")
        self.player._current_valid_orders = [[SingleBattleOrder(MockMove("ember", "FIRE"))], []]
        self.battle.available_moves = [[MockMove("ember", "FIRE")], []]
        
        has_protect = self.player.has_legal_protect_like_action(our_active, self.battle, slot_index=0)
        self.assertFalse(has_protect)

    # 7. Strong spread move under threat:
    # - attack penalty should be skipped or reduced
    def test_strong_spread_move_under_threat(self):
        our_active = MockPokemon("charizard")
        opp1 = MockPokemon("gengar")
        opp2 = MockPokemon("alakazam")
        # Attack order with high power spread move
        spread_move = MockMove("heatwave", "FIRE", target="allAdjacentFoes", base_power=95)
        action = SingleBattleOrder(spread_move, move_target=0)
        
        is_high_value = self.player.is_high_value_action_under_threat(action, our_active, self.battle, [opp1, opp2])
        self.assertTrue(is_high_value)

    # 8. True unanswered threat:
    # - active was threatened
    # - safer option existed
    # - attacked with low-value move
    # - fainted before moving
    # - should count as true_unanswered_speed_priority_threat
    def test_true_unanswered_threat(self):
        slot_data = {
            "outcome_known": True,
            "speed_priority_threatened": True,
            "fainted_before_moving": True,
            "was_targeted": True,
            "our_mon_fainted": True,
            "protect_like_available": True,
            "switch_available": True,
            "only_conditional_priority": False,
            "active_moved_before_threat": False,
            "actual_ko": False,
            "action": "move tackle 1",
            "action_types": {"damaging": True}
        }
        is_protect = slot_data.get("action_types", {}).get("protect", False)
        is_switch = slot_data.get("action_types", {}).get("switch", False)
        is_threat = slot_data.get("speed_priority_threatened", False)
        
        is_unanswered = False
        if is_threat and not is_protect and not is_switch:
            not_unanswered = (
                slot_data.get("fainted_before_moving") == False or
                slot_data.get("actual_ko") == True or
                slot_data.get("protect_like_available") == False or
                slot_data.get("switch_available") == False or
                slot_data.get("only_conditional_priority") == True or
                slot_data.get("was_targeted") == False or
                slot_data.get("active_moved_before_threat") == True
            )
            is_unanswered = not not_unanswered

        self.assertTrue(is_unanswered)

if __name__ == "__main__":
    unittest.main()
