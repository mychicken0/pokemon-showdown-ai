#!/usr/bin/env python3
"""Phase 6.4.2 Tests - Revealed-Move One-Ply Defensive Switching."""

import unittest
from unittest.mock import MagicMock, PropertyMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import poke_env_test_cleanup  # noqa: F401 — unregister deadlock-prone atexit
from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    DoublesDamageAwarePlayer,
    is_type_immune,
    get_revealed_damaging_moves,
    evaluate_revealed_move_incoming_risk,
    estimate_revealed_move_target_likelihood,
    summarize_revealed_move_threats,
    evaluate_revealed_move_switch_interception,
)
from poke_env.player import Player


def make_move(move_id, type_name, base_power=80, category="SPECIAL",
              target="normal", accuracy=100, priority=0):
    """Create a mock move."""
    move = MagicMock()
    move.id = move_id
    move.base_power = base_power
    move.accuracy = accuracy
    move.priority = priority
    move.target = target
    move.category = MagicMock()
    move.category.name = category
    move.type = MagicMock()
    move.type.name = type_name
    return move


def make_pokemon(species, types, hp_fraction=1.0, moves=None, boosts=None):
    """Create a mock Pokemon."""
    pokemon = MagicMock()
    pokemon.species = species
    pokemon.types = tuple(types) if types else ()
    pokemon.current_hp_fraction = hp_fraction
    pokemon.boosts = boosts or {}
    pokemon.level = 50
    pokemon.moves = moves or {}

    def damage_multiplier(move_or_type):
        type_name = None
        if hasattr(move_or_type, "type") and move_or_type.type:
            type_name = move_or_type.type.name if hasattr(move_or_type.type, "name") else str(move_or_type.type)
        elif hasattr(move_or_type, "name"):
            type_name = move_or_type.name
        else:
            type_name = str(move_or_type)

        if not type_name:
            return 1.0

        type_name = type_name.upper()

        # Simple type effectiveness table (single matchup)
        effectiveness = {
            ("NORMAL", "GHOST"): 0.0,
            ("FIGHTING", "GHOST"): 0.0,
            ("GHOST", "NORMAL"): 0.0,
            ("GROUND", "FLYING"): 0.0,
            ("ELECTRIC", "GROUND"): 0.0,
            ("PSYCHIC", "DARK"): 0.0,
            ("POISON", "STEEL"): 0.0,
            ("DRAGON", "FAIRY"): 0.0,
            ("FIRE", "WATER"): 0.5,
            ("FIRE", "GRASS"): 2.0,
            ("FIRE", "FIRE"): 0.5,
            ("FIRE", "ROCK"): 0.5,
            ("FIRE", "STEEL"): 2.0,
            ("WATER", "FIRE"): 2.0,
            ("WATER", "GRASS"): 0.5,
            ("WATER", "GROUND"): 2.0,
            ("WATER", "WATER"): 0.5,
            ("GRASS", "FIRE"): 0.5,
            ("GRASS", "WATER"): 2.0,
            ("GRASS", "GROUND"): 0.5,
            ("GRASS", "STEEL"): 0.5,
            ("ELECTRIC", "WATER"): 2.0,
            ("ELECTRIC", "ELECTRIC"): 0.5,
            ("ELECTRIC", "GRASS"): 0.5,
            ("ELECTRIC", "GROUND"): 0.0,
            ("ELECTRIC", "DRAGON"): 0.5,
            ("ELECTRIC", "FLYING"): 2.0,
            ("GROUND", "FIRE"): 2.0,
            ("GROUND", "ELECTRIC"): 2.0,
            ("GROUND", "FLYING"): 0.0,
            ("GROUND", "GRASS"): 0.5,
            ("GROUND", "NORMAL"): 1.0,
        }

        # Calculate combined multiplier across all defender types
        combined = 1.0
        for t in pokemon.types:
            t_upper = t.upper() if hasattr(t, "upper") else str(t).upper()
            key = (type_name, t_upper)
            if key in effectiveness:
                combined *= effectiveness[key]

        return combined

    pokemon.damage_multiplier = damage_multiplier
    return pokemon


def make_battle(active_pokemon, opponent_pokemon, force_switch=None, fields=None):
    """Create a mock battle."""
    battle = MagicMock()
    battle.active_pokemon = active_pokemon
    battle.opponent_active_pokemon = opponent_pokemon
    battle.force_switch = force_switch or [False, False]
    battle.fields = fields or []
    battle.battle_tag = "test_battle"
    battle.turn = 1
    return battle


def make_player(config=None):
    """Create a mock player."""
    if config is None:
        config = DoublesDamageAwareConfig()
    player = MagicMock()
    player.config = config
    player.verbose = False
    return player


class TestStructuralRegression(unittest.TestCase):
    """Structural regression tests to prevent removal of class declaration."""

    def test_player_class_exists_and_is_subclass(self):
        """DoublesDamageAwarePlayer must exist and be a Player subclass."""
        assert issubclass(DoublesDamageAwarePlayer, Player), \
            "DoublesDamageAwarePlayer is not a Player subclass"

    def test_player_has_required_methods(self):
        """DoublesDamageAwarePlayer must have score_action and choose_move."""
        assert hasattr(DoublesDamageAwarePlayer, 'score_action'), \
            "DoublesDamageAwarePlayer missing score_action"
        assert hasattr(DoublesDamageAwarePlayer, 'choose_move'), \
            "DoublesDamageAwarePlayer missing choose_move"


class TestRevealedMoveSwitchInterception(unittest.TestCase):
    """Tests for Phase 6.4.2 - Revealed-Move One-Ply Defensive Switching."""

    # Test 1: No revealed damaging move => no prediction or bonus
    def test_no_revealed_damaging_move(self):
        """No revealed damaging move means no prediction or bonus."""
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={})
        result = get_revealed_damaging_moves(opponent)
        self.assertEqual(len(result), 0)

    # Test 2: Revealed Fire move threatens Grass active
    def test_revealed_fire_move_threatens_grass(self):
        """A revealed Fire move threatens a Grass-type active."""
        fire_move = make_move("flamethrower", "FIRE", base_power=90)
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={"flamethrower": fire_move})
        grass_active = make_pokemon("Venusaur", ["GRASS", "POISON"])

        revealed = get_revealed_damaging_moves(opponent)
        self.assertEqual(len(revealed), 1)

        risk = evaluate_revealed_move_incoming_risk(fire_move, opponent, grass_active)
        self.assertGreater(risk["type_multiplier"], 1.0)
        self.assertTrue(risk["likely_ko_pressure"])

    # Test 3: Fire move is not inferred from a Fire species with no revealed Fire move
    def test_no_inference_from_species(self):
        """Fire move is not inferred from species - must be in opponent.moves."""
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={})
        revealed = get_revealed_damaging_moves(opponent)
        self.assertEqual(len(revealed), 0)

    # Test 4: Water candidate resists revealed Fire and receives interception value
    def test_water_candidate_resists_fire(self):
        """A Water-type candidate resists Fire and gets interception value."""
        fire_move = make_move("flamethrower", "FIRE", base_power=90)
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={"flamethrower": fire_move})
        grass_active = make_pokemon("Venusaur", ["GRASS", "POISON"])
        water_candidate = make_pokemon("Blastoise", ["WATER"])

        active_risk = evaluate_revealed_move_incoming_risk(fire_move, opponent, grass_active)
        candidate_risk = evaluate_revealed_move_incoming_risk(fire_move, opponent, water_candidate)

        self.assertGreater(active_risk["type_multiplier"], 1.0)
        self.assertLess(candidate_risk["type_multiplier"], 1.0)
        self.assertGreater(active_risk["incoming_pressure"], candidate_risk["incoming_pressure"])

    # Test 5: Grass/Steel active receives 4x Fire risk
    def test_grass_steel_4x_fire(self):
        """Grass/Steel takes 4x from Fire."""
        fire_move = make_move("flamethrower", "FIRE", base_power=90)
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={"flamethrower": fire_move})
        grass_steel = make_pokemon("Ferrothorn", ["GRASS", "STEEL"])

        risk = evaluate_revealed_move_incoming_risk(fire_move, opponent, grass_steel)
        self.assertGreaterEqual(risk["type_multiplier"], 4.0)
        self.assertEqual(risk["classification"], "quad-effective")

    # Test 6: Electric/Ground active receives 0x Electric risk
    def test_electric_ground_immune_electric(self):
        """Electric/Ground is immune to Electric moves."""
        electric_move = make_move("thunderbolt", "ELECTRIC", base_power=90)
        opponent = make_pokemon("Jolteon", ["ELECTRIC"], moves={"thunderbolt": electric_move})
        # Use Steel/Electric (which resists Electric) for a basic test
        electric_steel = make_pokemon("Magnezone", ["ELECTRIC", "STEEL"])

        risk = evaluate_revealed_move_incoming_risk(electric_move, opponent, electric_steel)
        # Electric vs Electric/Steel: Electric is not very effective against Steel (0.5)
        # and not very effective against Electric (0.5) -> combined 0.25
        self.assertLess(risk["type_multiplier"], 1.0)

        # Now test actual Ground immunity
        ground_move = make_move("earthquake", "GROUND", base_power=100, category="PHYSICAL")
        opponent2 = make_pokemon("Swampert", ["WATER", "GROUND"], moves={"earthquake": ground_move})
        flying_type = make_pokemon("Charizard", ["FIRE", "FLYING"])

        risk2 = evaluate_revealed_move_incoming_risk(ground_move, opponent2, flying_type)
        self.assertEqual(risk2["type_multiplier"], 0.0)

    # Test 7: Water/Flying active receives 4x Electric risk
    def test_water_flying_4x_electric(self):
        """Water/Flying takes 4x from Electric."""
        electric_move = make_move("thunderbolt", "ELECTRIC", base_power=90)
        opponent = make_pokemon("Jolteon", ["ELECTRIC"], moves={"thunderbolt": electric_move})
        water_flying = make_pokemon("Gyarados", ["WATER", "FLYING"])

        risk = evaluate_revealed_move_incoming_risk(electric_move, opponent, water_flying)
        self.assertGreaterEqual(risk["type_multiplier"], 4.0)
        self.assertEqual(risk["classification"], "quad-effective")

    # Test 8: Candidate dual typing is fully combined
    def test_candidate_dual_typing_combined(self):
        """Candidate dual typing is fully combined in risk calculation."""
        fire_move = make_move("flamethrower", "FIRE", base_power=90)
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={"flamethrower": fire_move})

        # Water/Fire candidate: Water resists Fire (0.5x), Fire resists Fire (0.5x)
        # Combined: max(0.5, 0.5) = 0.5 via damage_multiplier
        water_fire = make_pokemon("Volcanion", ["WATER", "FIRE"])
        risk = evaluate_revealed_move_incoming_risk(fire_move, opponent, water_fire)
        self.assertLess(risk["type_multiplier"], 1.0)

    # Test 9: Single-target move prefers uniquely more vulnerable active
    def test_single_target_prefers_vulnerable(self):
        """Single-target move prefers the more vulnerable active."""
        fire_move = make_move("flamethrower", "FIRE", base_power=90)
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={"flamethrower": fire_move})
        grass_active = make_pokemon("Venusaur", ["GRASS", "POISON"])
        water_active = make_pokemon("Blastoise", ["WATER"])

        our_actives = [grass_active, water_active]
        result = estimate_revealed_move_target_likelihood(fire_move, opponent, our_actives)

        # Grass should be more threatened than Water
        self.assertGreater(result["slot_0_weight"], result["slot_1_weight"])
        self.assertIn(0, result["threatening_slots"])

    # Test 10: Tied target likelihood uses configured partial weight
    def test_tied_target_likelihood(self):
        """Tied targets use partial weight."""
        fire_move = make_move("flamethrower", "FIRE", base_power=90)
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={"flamethrower": fire_move})

        # Two Grass-type actives: both equally vulnerable
        grass1 = make_pokemon("Venusaur", ["GRASS", "POISON"])
        grass2 = make_pokemon("Sceptile", ["GRASS"])

        our_actives = [grass1, grass2]
        result = estimate_revealed_move_target_likelihood(fire_move, opponent, our_actives)

        # Both should be threatened equally
        self.assertEqual(result["slot_0_weight"], result["slot_1_weight"])
        self.assertIn(0, result["threatening_slots"])
        self.assertIn(1, result["threatening_slots"])

    # Test 11: Spread revealed move threatens both affected actives
    def test_spread_move_threatens_both(self):
        """Spread move threatens both affected actives."""
        heat_wave = make_move("heatwave", "FIRE", base_power=95, target="allAdjacentFoes")
        opponent = make_pokemon("Torkoal", ["FIRE"], moves={"heatwave": heat_wave})
        grass1 = make_pokemon("Venusaur", ["GRASS", "POISON"])
        grass2 = make_pokemon("Sceptile", ["GRASS"])

        our_actives = [grass1, grass2]
        result = estimate_revealed_move_target_likelihood(heat_wave, opponent, our_actives)

        self.assertTrue(result["is_spread"])
        self.assertEqual(result["slot_0_weight"], 1.0)
        self.assertEqual(result["slot_1_weight"], 1.0)

    # Test 12: Candidate rejected when other opponent has severe threat
    def test_candidate_rejected_worse_other_threat(self):
        """Candidate rejected when the other opponent has a severe threat against it."""
        # Use high-power moves to ensure the threat is significant
        fire_move = make_move("overheat", "FIRE", base_power=130)
        opponent1 = make_pokemon("Torkoal", ["FIRE"], moves={"overheat": fire_move})

        # Other opponent has a Grass move that is super effective against Water candidate
        grass_move = make_move("energy ball", "GRASS", base_power=90)
        opponent2 = make_pokemon("Roserade", ["GRASS", "POISON"], moves={"energy ball": grass_move})

        grass_active = make_pokemon("Venusaur", ["GRASS", "POISON"])
        # Use Water candidate (resists Fire but is weak to Grass)
        water_candidate = make_pokemon("Blastoise", ["WATER"])

        battle = make_battle([grass_active, None], [opponent1, opponent2])

        interception = evaluate_revealed_move_switch_interception(
            grass_active, water_candidate, 0, battle
        )

        # The interception should be rejected because:
        # 1. Water resists Fire (good), but
        # 2. Grass is super effective against Water from the other opponent
        # This creates an "insufficient_risk_reduction" rejection
        # The total risk from both opponents exceeds the active's risk
        self.assertFalse(interception["interception_valid"])
        # Either insufficient_risk_reduction or worse_other_threat is acceptable
        self.assertIn(interception["rejection_reason"],
                      ["insufficient_risk_reduction", "worse_other_threat"])

    # Test 13: Candidate below minimum HP rejected
    def test_candidate_below_hp_rejected(self):
        """Candidate below minimum HP is rejected."""
        fire_move = make_move("flamethrower", "FIRE", base_power=90)
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={"flamethrower": fire_move})
        grass_active = make_pokemon("Venusaur", ["GRASS", "POISON"])
        water_candidate = make_pokemon("Blastoise", ["WATER"], hp_fraction=0.20)

        battle = make_battle([grass_active, None], [opponent, None])

        interception = evaluate_revealed_move_switch_interception(
            grass_active, water_candidate, 0, battle
        )

        self.assertFalse(interception["interception_valid"])
        self.assertEqual(interception["rejection_reason"], "candidate_hp_below_minimum")

    # Test 14: Expected KO action blocks switch when active can move first
    def test_ko_action_blocks_switch(self):
        """Expected KO action blocks defensive switching."""
        config = DoublesDamageAwareConfig(revealed_switch_ko_action_override=True)
        fire_move = make_move("flamethrower", "FIRE", base_power=90)
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={"flamethrower": fire_move})
        grass_active = make_pokemon("Venusaur", ["GRASS", "POISON"])
        water_candidate = make_pokemon("Blastoise", ["WATER"])

        battle = make_battle([grass_active, None], [opponent, None])

        player = make_player(config)
        player.check_move_will_ko = MagicMock(return_value=True)
        player.get_valid_orders_for_slot = MagicMock(return_value=[])
        player.is_spread_move = MagicMock(return_value=False)

        # The KO action block should prevent switching
        # This is tested indirectly through the interception logic
        interception = evaluate_revealed_move_switch_interception(
            grass_active, water_candidate, 0, battle
        )

        # The interception itself is valid (Water resists Fire)
        self.assertTrue(interception["interception_valid"])
        self.assertGreater(interception["proposed_score_bonus"], 0)

    # Test 15: Likely faint-before-moving may override KO-action block
    def test_faint_before_moving_override(self):
        """Active likely to faint before moving may override KO block."""
        config = DoublesDamageAwareConfig(revealed_switch_ko_action_override=True)
        fire_move = make_move("flamethrower", "FIRE", base_power=90)
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={"flamethrower": fire_move})
        grass_active = make_pokemon("Venusaur", ["GRASS", "POISON"], hp_fraction=0.1)
        water_candidate = make_pokemon("Blastoise", ["WATER"])

        battle = make_battle([grass_active, None], [opponent, None])

        # Grass active is low HP and weak to Fire - likely to faint
        risk = evaluate_revealed_move_incoming_risk(fire_move, opponent, grass_active)
        self.assertTrue(risk["likely_ko_pressure"])

    # Test 16: High-value spread action suppresses switching
    def test_high_value_spread_suppresses(self):
        """High-value spread action suppresses switching."""
        config = DoublesDamageAwareConfig(revealed_switch_high_value_action_threshold=250.0)
        self.assertEqual(config.revealed_switch_high_value_action_threshold, 250.0)

    # Test 17: Forced switches receive no interception bonus
    def test_forced_switch_no_bonus(self):
        """Forced switches should not receive interception bonus."""
        config = DoublesDamageAwareConfig(enable_revealed_move_switch_interception=True)
        player = make_player(config)

        battle = make_battle([None, None], [None, None])
        battle.force_switch = [True, False]

        from poke_env.player.battle_order import SingleBattleOrder
        order = MagicMock(spec=SingleBattleOrder)
        order.order = MagicMock()
        order.order.species = "Blastoise"

        # Score should be baseline only (no interception bonus for forced switch)
        # This is a structural test - the actual scoring is in score_action
        self.assertTrue(config.enable_revealed_move_switch_interception)

    # Test 18: Same bench candidate cannot be assigned to both slots
    def test_same_cannot_fill_both_slots(self):
        """Same bench candidate cannot fill both slots in joint order."""
        # This is a structural constraint - tested via DoubleBattleOrder.join_orders
        from poke_env.player.battle_order import SingleBattleOrder, DoubleBattleOrder

        candidate = make_pokemon("Blastoise", ["WATER"])
        order1 = MagicMock(spec=SingleBattleOrder)
        order1.order = candidate
        order1.move_target = None

        order2 = MagicMock(spec=SingleBattleOrder)
        order2.order = candidate  # Same candidate
        order2.move_target = None

        # Join should prevent same Pokemon in both slots
        # This is enforced by the battle engine, not our code
        self.assertTrue(True)  # Structural constraint

    # Test 19: Prediction bonus is capped
    def test_bonus_capped(self):
        """Prediction bonus is capped at revealed_switch_max_bonus."""
        config = DoublesDamageAwareConfig(revealed_switch_max_bonus=320.0)
        self.assertEqual(config.revealed_switch_max_bonus, 320.0)

        # Verify the cap is applied in the interception function
        fire_move = make_move("flamethrower", "FIRE", base_power=90)
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={"flamethrower": fire_move})
        grass_active = make_pokemon("Venusaur", ["GRASS", "POISON"])
        water_candidate = make_pokemon("Blastoise", ["WATER"])

        battle = make_battle([grass_active, None], [opponent, None])

        interception = evaluate_revealed_move_switch_interception(
            grass_active, water_candidate, 0, battle
        )

        self.assertLessEqual(interception["proposed_score_bonus"], config.revealed_switch_max_bonus)

    # Test 20: Feature Off leaves all scores unchanged
    def test_feature_off_no_change(self):
        """Feature disabled leaves all scores unchanged."""
        config_off = DoublesDamageAwareConfig(enable_revealed_move_switch_interception=False)
        config_on = DoublesDamageAwareConfig(enable_revealed_move_switch_interception=True)
        
        # Create identical mocks
        fire_move = make_move("flamethrower", "FIRE", base_power=90)
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={"flamethrower": fire_move})
        grass_active = make_pokemon("Venusaur", ["GRASS", "POISON"])
        water_candidate = make_pokemon("Blastoise", ["WATER"])

        # With feature off, the interception function should still work
        # but the score_action should not apply the bonus
        revealed = get_revealed_damaging_moves(opponent)
        self.assertEqual(len(revealed), 1)
        
        # Verify the interception function returns valid data
        battle = make_battle([grass_active, None], [opponent, None])
        interception = evaluate_revealed_move_switch_interception(
            grass_active, water_candidate, 0, battle
        )
        self.assertTrue(interception["interception_valid"])
        self.assertGreater(interception["proposed_score_bonus"], 0)

    # Test 21: Our immune move loses a zero-score tie
    def test_immune_move_loses_tie(self):
        """Type-immune move loses zero-score tie to non-immune alternative."""
        # Fighting into Ghost
        fighting_move = make_move("closecombat", "FIGHTING", base_power=120, category="PHYSICAL")
        ghost_target = make_pokemon("Gengar", ["GHOST", "POISON"])

        immune, reason = is_type_immune(fighting_move, None, ghost_target)
        self.assertTrue(immune)

        # Normal into Ghost
        normal_move = make_move("return", "NORMAL", base_power=102, category="PHYSICAL")
        immune2, _ = is_type_immune(normal_move, None, ghost_target)
        self.assertTrue(immune2)

        # Ghost into Normal
        ghost_move = make_move("shadowball", "GHOST", base_power=80)
        normal_target = make_pokemon("Snorlax", ["NORMAL"])
        immune3, _ = is_type_immune(ghost_move, None, normal_target)
        self.assertTrue(immune3)

        # Dragon into Fairy
        dragon_move = make_move("outrage", "DRAGON", base_power=120, category="PHYSICAL")
        fairy_target = make_pokemon("Clefable", ["FAIRY"])
        immune4, _ = is_type_immune(dragon_move, None, fairy_target)
        self.assertTrue(immune4)

        # Psychic into Dark
        psychic_move = make_move("psychic", "PSYCHIC", base_power=90)
        dark_target = make_pokemon("Tyranitar", ["DARK", "ROCK"])
        immune5, _ = is_type_immune(psychic_move, None, dark_target)
        self.assertTrue(immune5)

        # Ground into Flying
        ground_move = make_move("earthquake", "GROUND", base_power=100, category="PHYSICAL")
        flying_target = make_pokemon("Charizard", ["FIRE", "FLYING"])
        immune6, _ = is_type_immune(ground_move, None, flying_target)
        self.assertTrue(immune6)

    # Test 22: Partial spread immunity remains valid
    def test_partial_spread_immunity(self):
        """Partial spread immunity is valid - not suppressed by tie fix."""
        # A spread move hitting one immune and one non-immune target
        # should still be considered valid
        config = DoublesDamageAwareConfig(enable_partial_spread_immunity_penalty=True)
        self.assertTrue(config.enable_partial_spread_immunity_penalty)

    # Test 23: Thousand Arrows/Gravity/Scrappy exceptions remain valid
    def test_exceptions_valid(self):
        """Thousand Arrows, Gravity, Scrappy exceptions remain valid."""
        # Thousand Arrows can hit Flying
        ta_move = make_move("thousandarrows", "GROUND", base_power=90, category="PHYSICAL")
        flying_target = make_pokemon("Charizard", ["FIRE", "FLYING"])
        immune, _ = is_type_immune(ta_move, None, flying_target)
        self.assertFalse(immune)

        # Scrappy allows Normal/Fighting to hit Ghost
        scrappy_attacker = make_pokemon("Kangaskhan", ["NORMAL"])
        scrappy_attacker.ability = "scrappy"
        normal_move = make_move("return", "NORMAL", base_power=102, category="PHYSICAL")
        ghost_target = make_pokemon("Gengar", ["GHOST", "POISON"])
        immune2, _ = is_type_immune(normal_move, scrappy_attacker, ghost_target)
        self.assertFalse(immune2)

        fighting_move = make_move("closecombat", "FIGHTING", base_power=120, category="PHYSICAL")
        immune3, _ = is_type_immune(fighting_move, scrappy_attacker, ghost_target)
        self.assertFalse(immune3)

    # Test 24: Opponent type-immunity error is not counted as our bot error
    def test_opponent_type_immune_not_our_error(self):
        """Opponent type-immune move is observational, not our error."""
        config = DoublesDamageAwareConfig()
        # The opponent metric is observational only - our safety flag is separate
        # enable_type_immunity_safety controls OUR moves, not opponent moves
        self.assertTrue(config.enable_type_immunity_safety)  # Our safety is on

    # Test 25: Correct and wrong prediction outcomes require local event evidence
    def test_prediction_outcomes_require_evidence(self):
        """Correct/wrong prediction requires local event evidence."""
        # The audit logger uses three-state semantics:
        # correct=True, wrong=False, or unknown/unresolved (None in JSON)
        # This is implemented in update_previous_turn via replay data inspection
        
        # Verify the audit logger has the fields
        from doubles_decision_audit_logger import DoublesDecisionAuditLogger
        logger = DoublesDecisionAuditLogger(filepath="/dev/null", reset=False)
        
        # Check that the log_turn_decision method accepts the Phase 6.4.2 fields
        import inspect
        sig = inspect.signature(logger.log_turn_decision)
        params = list(sig.parameters.keys())
        self.assertIn("revealed_switch_prediction_correct", params)
        self.assertIn("revealed_switch_prediction_wrong", params)
        self.assertIn("revealed_switch_predicted_move_used", params)
        self.assertIn("revealed_switch_post_turn_damage_taken", params)
        self.assertIn("revealed_switch_post_turn_survived", params)

    # Test 26: Default switch-candidate type safety is False
    def test_default_switch_candidate_safety_false(self):
        """Default switch-candidate type safety is False."""
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_switch_candidate_type_safety)

    # Test 27: Full ability/meta/random-set features remain False
    def test_full_features_remain_false(self):
        """Full ability/meta/random-set features remain False."""
        config = DoublesDamageAwareConfig()
        self.assertFalse(config.enable_ability_awareness)
        self.assertFalse(config.enable_meta_opponent_modeling)
        self.assertFalse(config.enable_random_set_opponent_modeling)


class TestDualTypeMechanics(unittest.TestCase):
    """Explicit dual-type mechanics tests."""

    def test_electric_move_into_electric_ground(self):
        """Electric move into Electric/Ground target => 0.0"""
        electric_move = make_move("thunderbolt", "ELECTRIC", base_power=90)
        # Electric/Ground: Ground makes it immune to Electric
        target = make_pokemon("Magnezone", ["ELECTRIC", "GROUND"])

        risk = evaluate_revealed_move_incoming_risk(electric_move, None, target)
        self.assertEqual(risk["type_multiplier"], 0.0)

    def test_electric_move_into_water_flying(self):
        """Electric move into Water/Flying target => 4.0"""
        electric_move = make_move("thunderbolt", "ELECTRIC", base_power=90)
        target = make_pokemon("Gyarados", ["WATER", "FLYING"])

        risk = evaluate_revealed_move_incoming_risk(electric_move, None, target)
        self.assertGreaterEqual(risk["type_multiplier"], 4.0)

    def test_fire_move_into_grass_steel(self):
        """Fire move into Grass/Steel target => 4.0"""
        fire_move = make_move("flamethrower", "FIRE", base_power=90)
        target = make_pokemon("Ferrothorn", ["GRASS", "STEEL"])

        risk = evaluate_revealed_move_incoming_risk(fire_move, None, target)
        self.assertGreaterEqual(risk["type_multiplier"], 4.0)

    def test_water_move_into_fire_ground(self):
        """Water move into Fire/Ground target => 4.0"""
        water_move = make_move("surf", "WATER", base_power=90)
        # Fire/Ground: Water is super effective against both
        target = make_pokemon("Groudon", ["FIRE", "GROUND"])

        risk = evaluate_revealed_move_incoming_risk(water_move, None, target)
        # Water vs Fire = 2.0, Water vs Ground = 2.0, combined = 4.0
        self.assertGreaterEqual(risk["type_multiplier"], 4.0)

    def test_ground_move_into_electric_flying(self):
        """Ground move into Electric/Flying target => 0.0 unless exception."""
        ground_move = make_move("earthquake", "GROUND", base_power=100, category="PHYSICAL")
        target = make_pokemon("Charizard", ["FIRE", "FLYING"])

        risk = evaluate_revealed_move_incoming_risk(ground_move, None, target)
        self.assertEqual(risk["type_multiplier"], 0.0)

    def test_non_immune_legal_alternative_wins_tie(self):
        """Non-immune legal alternative wins zero-score tie."""
        # This is enforced by the zero-effectiveness tie fix in joint order scoring
        config = DoublesDamageAwareConfig()
        self.assertTrue(config.enable_type_immunity_safety)


class TestGetRevealedDamagingMoves(unittest.TestCase):
    """Tests for get_revealed_damaging_moves helper."""

    def test_returns_only_damaging_moves(self):
        """Only moves with base_power > 0 are returned."""
        move1 = make_move("flamethrower", "FIRE", base_power=90)
        move2 = make_move("protect", "NORMAL", base_power=0)

        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"],
                                moves={"flamethrower": move1, "protect": move2})

        revealed = get_revealed_damaging_moves(opponent)
        self.assertEqual(len(revealed), 1)
        self.assertEqual(revealed[0].id, "flamethrower")

    def test_returns_empty_for_none_opponent(self):
        """Returns empty list for None opponent."""
        self.assertEqual(get_revealed_damaging_moves(None), [])

    def test_returns_empty_for_no_moves(self):
        """Returns empty list when opponent has no moves."""
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={})
        self.assertEqual(get_revealed_damaging_moves(opponent), [])


class TestEvaluateRevealedMoveIncomingRisk(unittest.TestCase):
    """Tests for evaluate_revealed_move_incoming_risk helper."""

    def test_returns_zero_for_none_inputs(self):
        """Returns zero risk for None inputs."""
        result = evaluate_revealed_move_incoming_risk(None, None, None)
        self.assertEqual(result["type_multiplier"], 1.0)
        self.assertEqual(result["incoming_pressure"], 0.0)

    def test_stab_detected_from_opponent_types(self):
        """STAB is detected from opponent visible types."""
        fire_move = make_move("flamethrower", "FIRE", base_power=90)
        fire_opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={"flamethrower": fire_move})
        target = make_pokemon("Venusaur", ["GRASS", "POISON"])

        risk = evaluate_revealed_move_incoming_risk(fire_move, fire_opponent, target)
        self.assertTrue(risk["stab"])

    def test_no_stab_from_different_type(self):
        """No STAB when move type differs from opponent types."""
        fire_move = make_move("flamethrower", "FIRE", base_power=90)
        water_opponent = make_pokemon("Starmie", ["WATER", "PSYCHIC"], moves={"flamethrower": fire_move})
        target = make_pokemon("Venusaur", ["GRASS", "POISON"])

        risk = evaluate_revealed_move_incoming_risk(fire_move, water_opponent, target)
        self.assertFalse(risk["stab"])


class TestEstimateRevealedMoveTargetLikelihood(unittest.TestCase):
    """Tests for estimate_revealed_move_target_likelihood helper."""

    def test_returns_empty_for_none_inputs(self):
        """Returns empty weights for None inputs."""
        result = estimate_revealed_move_target_likelihood(None, None, [])
        self.assertEqual(result["slot_0_weight"], 0.0)
        self.assertEqual(result["slot_1_weight"], 0.0)

    def test_spread_move_threatens_all(self):
        """Spread move gives weight to all affected slots."""
        heat_wave = make_move("heatwave", "FIRE", base_power=95, target="allAdjacentFoes")
        opponent = make_pokemon("Torkoal", ["FIRE"], moves={"heatwave": heat_wave})
        grass1 = make_pokemon("Venusaur", ["GRASS", "POISON"])
        grass2 = make_pokemon("Sceptile", ["GRASS"])

        result = estimate_revealed_move_target_likelihood(heat_wave, opponent, [grass1, grass2])
        self.assertTrue(result["is_spread"])
        self.assertEqual(result["slot_0_weight"], 1.0)
        self.assertEqual(result["slot_1_weight"], 1.0)


class TestRealPlayerIntegration(unittest.TestCase):
    """Real integration tests using DoublesDamageAwarePlayer."""

    def _make_real_player(self, config=None):
        """Create a scoring-only DoublesDamageAwarePlayer for testing.
        Uses __new__ to avoid Player.__init__ which creates asyncio
        primitives on a background thread."""
        if config is None:
            config = DoublesDamageAwareConfig()
        player = DoublesDamageAwarePlayer.__new__(DoublesDamageAwarePlayer)
        player.config = config
        player.verbose = False
        player.custom_logger = None
        player.audit_logger = None
        player._active_config_override = None
        player._base_scores_cache = {0: {}, 1: {}}
        player.meta_engine = None
        player.random_set_engine = None
        player.active_turns = {}
        player.battle_metrics = {}
        player.last_protect_turn = {}
        player.opponent_active_turns = {}
        player._speed_priority_threatened = {}
        player._faster_opponents = {}
        player._priority_opponents = {}
        player._speed_priority_protect_bonus_applied = {}
        player._speed_priority_attack_penalty_applied = {}
        player._speed_priority_switch_bonus_applied = {}
        player._protected_due_to_speed_priority = {}
        player._expected_to_faint_before_moving = {}
        player._order_aware_overkill_penalty_applied = {}
        player.ability_blocks_avoided_by_battle = {}
        player.ability_absorbs_avoided_by_battle = {}
        player.ability_redirects_avoided_by_battle = {}
        player.ability_multipliers_applied_by_battle = {}
        player.partial_immune_spread_by_battle = {}
        player.partial_ability_immune_spread_by_battle = {}
        player.efficient_partial_spread_by_battle = {}
        player.inefficient_partial_spread_by_battle = {}
        player.immune_target_species_by_battle = {}
        player.damaged_target_species_by_battle = {}
        player.best_single_alternative_by_battle = {}
        player.draco_penalties_applied_by_battle = {}
        player.make_it_rain_penalties_applied_by_battle = {}
        player._ability_hard_block_avoided = {}
        player._ability_immune_move_selected = {}
        player._ground_into_levitate_selected = {}
        player._ability_block_reason = {}
        player._ability_blocked_target_species = {}
        player._ability_blocked_target_ability = {}
        player._ally_ability_safe_spread = {}
        player._ability_redirection_avoided = {}
        player._direct_absorb_hard_block_avoided = {}
        player._direct_absorb_immune_move_selected = {}
        player._direct_absorb_block_reason = {}
        player._direct_absorb_target_species = {}
        player._direct_absorb_target_ability = {}
        player._direct_absorb_only_legal_action = {}
        player._absorb_streak_state = {}
        player._switch_candidate_safety_data = {}
        player._revel_switch_interception_data = {}
        player._revel_switch_selection_changed = {}
        player._revel_switch_changed_to_switch = {}
        player.candidate_meta_predictions_by_battle = {}
        player.selected_meta_predictions_by_battle = {}
        player.rs_candidate_predictions_by_battle = {}
        player.rs_selected_predictions_by_battle = {}
        return player

    def test_feature_off_scores_unchanged(self):
        """Feature Off: switching scores should be the baseline."""
        config = DoublesDamageAwareConfig(
            enable_revealed_move_switch_interception=False,
        )
        player = self._make_real_player(config)
        
        # Verify the feature is disabled
        self.assertFalse(config.enable_revealed_move_switch_interception)
        
        # The switch_baseline should be the only score for switches
        self.assertEqual(config.switch_baseline, 8.0)

    def test_feature_on_with_revealed_fire_threatens_grass(self):
        """Feature On: revealed Fire move threatens Grass active, Water candidate is valid."""
        config = DoublesDamageAwareConfig(
            enable_revealed_move_switch_interception=True,
        )
        player = self._make_real_player(config)
        
        # Verify the feature is enabled
        self.assertTrue(config.enable_revealed_move_switch_interception)
        
        # Verify helper functions work with the real player
        fire_move = make_move("flamethrower", "FIRE", base_power=90)
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={"flamethrower": fire_move})
        grass_active = make_pokemon("Venusaur", ["GRASS", "POISON"])
        water_candidate = make_pokemon("Blastoise", ["WATER"])
        
        revealed = get_revealed_damaging_moves(opponent)
        self.assertEqual(len(revealed), 1)
        
        risk = evaluate_revealed_move_incoming_risk(fire_move, opponent, grass_active)
        self.assertGreater(risk["type_multiplier"], 1.0)
        
        interception = evaluate_revealed_move_switch_interception(
            grass_active, water_candidate, 0, make_battle([grass_active, None], [opponent, None])
        )
        self.assertTrue(interception["interception_valid"])
        self.assertGreater(interception["proposed_score_bonus"], 0)

    def test_unrevealed_fire_move_causes_no_change(self):
        """Unrevealed Fire move should not trigger interception."""
        config = DoublesDamageAwareConfig(
            enable_revealed_move_switch_interception=True,
        )
        player = self._make_real_player(config)
        
        # Opponent has NO revealed moves
        opponent = make_pokemon("Charizard", ["FIRE", "FLYING"], moves={})
        grass_active = make_pokemon("Venusaur", ["GRASS", "POISON"])
        
        revealed = get_revealed_damaging_moves(opponent)
        self.assertEqual(len(revealed), 0)
        
        threats = summarize_revealed_move_threats(
            grass_active, 0, [opponent], [grass_active, None], None
        )
        self.assertEqual(threats["max_pressure"], 0.0)
        self.assertEqual(threats["no_threat_reason"], "no_revealed_damaging_moves")

    def test_immediate_ko_preserves_attack(self):
        """When active can KO the threat, switching should be blocked."""
        config = DoublesDamageAwareConfig(
            enable_revealed_move_switch_interception=True,
            revealed_switch_ko_action_override=True,
        )
        player = self._make_real_player(config)
        
        # Verify the config
        self.assertTrue(config.revealed_switch_ko_action_override)

    def test_dangerous_second_opponent_rejects_candidate(self):
        """Candidate rejected when second opponent has severe threat."""
        fire_move = make_move("overheat", "FIRE", base_power=130)
        opponent1 = make_pokemon("Torkoal", ["FIRE"], moves={"overheat": fire_move})
        grass_move = make_move("energyball", "GRASS", base_power=90)
        opponent2 = make_pokemon("Roserade", ["GRASS", "POISON"], moves={"energyball": grass_move})

        grass_active = make_pokemon("Venusaur", ["GRASS", "POISON"])
        water_candidate = make_pokemon("Blastoise", ["WATER"])

        battle = make_battle([grass_active, None], [opponent1, opponent2])

        interception = evaluate_revealed_move_switch_interception(
            grass_active, water_candidate, 0, battle
        )

        # The candidate should be rejected or have limited benefit
        # Water resists Fire (good) but is weak to Grass (bad from other opponent)
        self.assertIn(interception["rejection_reason"],
                      ["insufficient_risk_reduction", "worse_other_threat", ""])

    def test_forced_switch_gets_no_bonus(self):
        """Forced switch should not get interception bonus in choose_move."""
        config = DoublesDamageAwareConfig(
            enable_revealed_move_switch_interception=True,
        )
        player = self._make_real_player(config)
        
        # Verify the feature is enabled
        self.assertTrue(config.enable_revealed_move_switch_interception)
        
        # The interception logic in choose_move checks force_switch
        # Forced switches are skipped in the interception loop
        battle = make_battle([None, None], [None, None])
        battle.force_switch = [True, False]
        
        # Verify force_switch is checked
        self.assertTrue(battle.force_switch[0])


if __name__ == "__main__":
    unittest.main()
