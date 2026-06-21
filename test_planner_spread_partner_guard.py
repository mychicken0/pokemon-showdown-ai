"""PLANNER-SPREAD-8B unit tests: partner threat relevance guard.

This guard ensures WG is only boosted when the team is in actual
spread-move danger (i.e., at least one ally is threatened by a hit).
Pure HP-based guards would be too aggressive; this guard uses
"threat relevance" — is there a team value from preventing spread damage?
"""
import unittest
from unittest.mock import MagicMock

import bot_doubles_damage_aware as mod
from bot_doubles_damage_aware import DoublesDamageAwareConfig
from bot_doubles_intent_classifier import IntentDecision
from poke_env.battle.move import Move


def make_player_with_guard(threat_threshold=0.7):
    """Make a player with the partner guard enabled."""
    config = DoublesDamageAwareConfig()
    config.enable_planner_intent_detector = True
    config.enable_planner_spread_defense_scoring = True
    config.planner_spread_defense_partner_threat_threshold = threat_threshold
    
    player = mod.DoublesDamageAwarePlayer.__new__(mod.DoublesDamageAwarePlayer)
    player.config = config
    player._planner_spread_defense_picks_per_game = {}
    player._planner_spread_defense_last_pick_turn = {}
    player._planner_spread_defense_bonus_applied_per_game = {}
    # Mock opp_pressure to always be True (so we test only the partner guard)
    player._slot_in_opp_pressure = lambda *args: True
    return player


def make_battle(slot_0_species, slot_0_hp, slot_1_species, slot_1_hp):
    """Build a mock battle with given slot 0/1 species and HP fractions."""
    battle = MagicMock()
    battle.battle_tag = "test-battle"
    battle.turn = 3
    battle.active_pokemon = [None, None]
    if slot_0_species:
        mon_0 = MagicMock()
        mon_0.species = slot_0_species
        mon_0.current_hp_fraction = slot_0_hp
        mon_0.fainted = slot_0_hp == 0
        battle.active_pokemon[0] = mon_0
    if slot_1_species:
        mon_1 = MagicMock()
        mon_1.species = slot_1_species
        mon_1.current_hp_fraction = slot_1_hp
        mon_1.fainted = slot_1_hp == 0
        battle.active_pokemon[1] = mon_1
    return battle


def make_wg_order():
    order = MagicMock()
    order.order = Move("wideguard", gen=9)
    return order


def make_spread_decision():
    return IntentDecision(
        intent="SPREAD_DEFENSE",
        confidence=0.65,
        evidence_source="revealed_moves",
        matched_moves=("rockslide",),
        routed_to_policy="spread_defense",
        opp_pressure=True,
    )


class TestPartnerThreatRelevance(unittest.TestCase):
    """Test the partner threat relevance guard."""

    def test_both_full_hp_suppress(self):
        """Both mons at full HP: no threat, suppress WG."""
        player = make_player_with_guard()
        battle = make_battle("garganacl", 1.0, "incineroar", 1.0)
        decision = make_spread_decision()
        result = player._planner_spread_defense_partner_threat_relevant(
            decision, 0, battle
        )
        self.assertFalse(result,
            "Both at full HP: no threat, should suppress WG")

    def test_wg_user_low_partner_full_allow(self):
        """WG user threatened (low HP), partner full: allow self-preservation."""
        player = make_player_with_guard()
        battle = make_battle("garganacl", 0.30, "incineroar", 1.0)
        decision = make_spread_decision()
        result = player._planner_spread_defense_partner_threat_relevant(
            decision, 0, battle
        )
        self.assertTrue(result,
            "WG user threatened: should allow WG (self-preservation)")

    def test_wg_user_full_partner_low_allow(self):
        """WG user full, partner threatened: allow (partner capitalization)."""
        player = make_player_with_guard()
        battle = make_battle("garganacl", 1.0, "incineroar", 0.25)
        decision = make_spread_decision()
        result = player._planner_spread_defense_partner_threat_relevant(
            decision, 0, battle
        )
        self.assertTrue(result,
            "Partner threatened: should allow WG (capitalize)")

    def test_both_low_allow(self):
        """Both mons at low HP: definitely allow."""
        player = make_player_with_guard()
        battle = make_battle("garganacl", 0.25, "incineroar", 0.20)
        decision = make_spread_decision()
        result = player._planner_spread_defense_partner_threat_relevant(
            decision, 0, battle
        )
        self.assertTrue(result,
            "Both threatened: should allow WG")

    def test_partner_fainted_wg_user_full_suppress(self):
        """Partner fainted, WG user full: no team benefit, suppress."""
        player = make_player_with_guard()
        battle = make_battle("garganacl", 1.0, None, 0)
        decision = make_spread_decision()
        result = player._planner_spread_defense_partner_threat_relevant(
            decision, 0, battle
        )
        self.assertFalse(result,
            "Partner fainted, WG user full: no benefit, should suppress")

    def test_partner_fainted_wg_user_low_allow(self):
        """Partner fainted, WG user threatened: allow self-preservation."""
        player = make_player_with_guard()
        battle = make_battle("garganacl", 0.30, None, 0)
        decision = make_spread_decision()
        result = player._planner_spread_defense_partner_threat_relevant(
            decision, 0, battle
        )
        self.assertTrue(result,
            "Partner fainted, WG user threatened: should allow self-preservation")

    def test_both_just_below_threshold_allow(self):
        """Both mons at 0.69 (just below 0.7 threshold): should allow."""
        player = make_player_with_guard()
        battle = make_battle("garganacl", 0.69, "incineroar", 0.69)
        decision = make_spread_decision()
        result = player._planner_spread_defense_partner_threat_relevant(
            decision, 0, battle
        )
        self.assertTrue(result,
            "Both just below threshold: should allow (just barely)")

    def test_both_just_above_threshold_suppress(self):
        """Both mons at 0.71 (just above 0.7 threshold): should suppress."""
        player = make_player_with_guard()
        battle = make_battle("garganacl", 0.71, "incineroar", 0.71)
        decision = make_spread_decision()
        result = player._planner_spread_defense_partner_threat_relevant(
            decision, 0, battle
        )
        self.assertFalse(result,
            "Both just above threshold: should suppress (no threat)")

    def test_mispredict_case_from_audit_p90(self):
        """Real case from audit: WG user full, partner low.
        This is the partner-gap case #7. With the guard, this should be ALLOWED
        (partner threatened) even though the user is full HP.
        """
        player = make_player_with_guard()
        # p90 t4: volcarona (partner) at 0.48, garganacl (WG user) at 1.0
        battle = make_battle("garganacl", 1.0, "volcarona", 0.48)
        decision = make_spread_decision()
        result = player._planner_spread_defense_partner_threat_relevant(
            decision, 0, battle
        )
        self.assertTrue(result,
            "Audit case #7 (volcarona 0.48): should allow (partner threatened)")

    def test_no_benefit_case_from_audit_p69(self):
        """Real case from audit: both full HP, opp didn't use spread.
        With the guard, this should be SUPPRESSED (no team value).
        """
        player = make_player_with_guard()
        # p69 t6: both volcarona and garganacl at 1.0
        battle = make_battle("garganacl", 1.0, "volcarona", 1.0)
        decision = make_spread_decision()
        result = player._planner_spread_defense_partner_threat_relevant(
            decision, 0, battle
        )
        self.assertFalse(result,
            "Audit case #4 (both full HP): should suppress (no threat)")

    def test_slot1_is_wg_user(self):
        """The guard should work regardless of which slot uses WG."""
        player = make_player_with_guard()
        # WG is in slot 1 (incineroar), partner is slot 0 (garganacl)
        battle = make_battle("garganacl", 0.20, "incineroar", 0.85)
        decision = make_spread_decision()
        result = player._planner_spread_defense_partner_threat_relevant(
            decision, 1, battle
        )
        self.assertTrue(result,
            "WG in slot 1, partner (slot 0) threatened: should allow")

    def test_threshold_configurable(self):
        """Threshold is configurable via config."""
        # With threshold 0.5, even 0.55 should suppress
        player = make_player_with_guard(threat_threshold=0.5)
        battle = make_battle("garganacl", 0.55, "incineroar", 0.55)
        decision = make_spread_decision()
        result = player._planner_spread_defense_partner_threat_relevant(
            decision, 0, battle
        )
        self.assertFalse(result,
            "With threshold 0.5, HP 0.55 should suppress")


if __name__ == "__main__":
    unittest.main()
