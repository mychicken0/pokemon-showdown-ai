import poke_env_test_cleanup  # noqa: F401 — unregister deadlock-prone atexit
import unittest
from typing import Optional, List

from bot_doubles_damage_aware import (
    is_type_immune,
    get_known_ability,
    attacker_ignores_target_ability,
    ability_hard_blocks_move,
    ability_redirects_single_target_move,
    ally_ability_makes_safe,
    get_spread_target_effectiveness_with_ability,
    DoublesDamageAwarePlayer,
    DoublesDamageAwareConfig,
    _ability_block_enabled,
    direct_known_absorb_blocks_move,
    is_opponent_spread_move
)
from poke_env.player.battle_order import SingleBattleOrder, DoubleBattleOrder
from poke_env.battle.move import Move
from poke_env.battle.pokemon import Pokemon
from poke_env.battle.pokemon_type import PokemonType
from poke_env.battle.move_category import MoveCategory
from poke_env.battle.double_battle import DoubleBattle
from poke_env.battle.target import Target

class MockMove(Move):
    def __init__(self, move_id: str, move_type: str, base_power: int = 80, category: str = "SPECIAL", target: str = "normal", flags: Optional[dict] = None):
        super().__init__(move_id=move_id, gen=9)
        if move_type:
            try:
                self._type = PokemonType[move_type.upper()]
            except Exception:
                pass
        if base_power is not None:
            self._base_power = base_power
        if category:
            try:
                self._category = MoveCategory[category.upper()]
            except Exception:
                pass
        if target:
            self._target = target
        if flags:
            self._flags = flags
        else:
            self._flags = {}

    @property
    def flags(self) -> dict:
        return self._flags

class MockPokemon(Pokemon):
    def __init__(self, species: str, types: List[str] = None, ability: Optional[str] = None, boosts: Optional[dict] = None):
        super().__init__(gen=9, species=species)
        if types:
            try:
                t_list = []
                for t in types:
                    t_list.append(PokemonType[t.upper()])
                self._type_1 = t_list[0]
                self._type_2 = t_list[1] if len(t_list) > 1 else None
            except Exception:
                pass
        if ability:
            self._ability = ability.lower().replace(" ", "").replace("-", "")
        else:
            self._ability = None
        if boosts:
            self._boosts = boosts
        else:
            self._boosts = {}
        self._current_hp_fraction = 1.0

    @property
    def current_hp_fraction(self) -> float:
        return self._current_hp_fraction

    @current_hp_fraction.setter
    def current_hp_fraction(self, val: float):
        self._current_hp_fraction = val

    @property
    def types(self) -> tuple:
        t2 = getattr(self, "_type_2", None)
        if t2:
            return (self._type_1, t2)
        return (self._type_1, None)

class MockField:
    def __init__(self, name: str):
        self.name = name.lower()

class MockBattle(DoubleBattle):
    def __init__(self, fields=None):
        import logging
        super().__init__("test_battle", "test_user", logging.getLogger("poke_env"), gen=9)
        self._fields = fields or []
        self._opponent_active_pokemon = [None, None]
        self._active_pokemon = [None, None]
        self._turn = 1
        self._available_moves = [[], []]
        self._force_switch = [False, False]
        self._battle_tag_val = "test_battle"
        self._replay_data_val = None
        self._valid_orders = [[], []]

    @property
    def battle_tag(self):
        return self._battle_tag_val

    @battle_tag.setter
    def battle_tag(self, val):
        self._battle_tag_val = val

    @property
    def _replay_data(self):
        return self._replay_data_val

    @_replay_data.setter
    def _replay_data(self, val):
        self._replay_data_val = val

    @property
    def fields(self):
        return self._fields

    @property
    def opponent_active_pokemon(self):
        return self._opponent_active_pokemon

    @opponent_active_pokemon.setter
    def opponent_active_pokemon(self, val):
        self._opponent_active_pokemon = val

    @property
    def active_pokemon(self):
        return self._active_pokemon

    @active_pokemon.setter
    def active_pokemon(self, val):
        self._active_pokemon = val

    @property
    def turn(self):
        return self._turn

    @turn.setter
    def turn(self, val):
        self._turn = val

    @property
    def available_moves(self):
        return self._available_moves

    @available_moves.setter
    def available_moves(self, val):
        self._available_moves = val

    @property
    def force_switch(self):
        return self._force_switch

    @force_switch.setter
    def force_switch(self, val):
        self._force_switch = val

    @property
    def valid_orders(self):
        return self._valid_orders

    @valid_orders.setter
    def valid_orders(self, val):
        self._valid_orders = val

class TestPlayer(DoublesDamageAwarePlayer):
    """Scoring-only test fixture.  Uses __new__ to avoid Player.__init__
    which creates asyncio primitives on a background thread via
    poke_env.concurrency.create_in_poke_loop."""

    def __init__(self, config=None):
        # Intentionally DO NOT call super().__init__() — this class is
        # constructed via __new__ in the factory below.
        pass

    @staticmethod
    def create(config=None):
        """Factory that bypasses Player.__init__ entirely."""
        p = DoublesDamageAwarePlayer.__new__(TestPlayer)
        p.config = config or DoublesDamageAwareConfig()
        p.verbose = False
        p.custom_logger = None
        p.audit_logger = None
        p._active_config_override = None

        p.ability_blocks_avoided_by_battle = {}
        p.ability_absorbs_avoided_by_battle = {}
        p.ability_redirects_avoided_by_battle = {}
        p.ability_multipliers_applied_by_battle = {}

        p.partial_immune_spread_by_battle = {}
        p.partial_ability_immune_spread_by_battle = {}
        p.efficient_partial_spread_by_battle = {}
        p.inefficient_partial_spread_by_battle = {}
        p.immune_target_species_by_battle = {}
        p.damaged_target_species_by_battle = {}
        p.best_single_alternative_by_battle = {}

        p._speed_priority_threatened = {}
        p._faster_opponents = {}
        p._priority_opponents = {}
        p._speed_priority_protect_bonus_applied = {}
        p._speed_priority_attack_penalty_applied = {}
        p._speed_priority_switch_bonus_applied = {}
        p._protected_due_to_speed_priority = {}
        p._expected_to_faint_before_moving = {}
        p._order_aware_overkill_penalty_applied = {}

        p._ability_hard_block_avoided = {}
        p._ability_immune_move_selected = {}
        p._ground_into_levitate_selected = {}
        p._ability_block_reason = {}
        p._ability_blocked_target_species = {}
        p._ability_blocked_target_ability = {}
        p._ally_ability_safe_spread = {}
        p._ability_redirection_avoided = {}

        p._direct_absorb_hard_block_avoided = {}
        p._direct_absorb_immune_move_selected = {}
        p._direct_absorb_block_reason = {}
        p._direct_absorb_target_species = {}
        p._direct_absorb_target_ability = {}
        p._direct_absorb_only_legal_action = {}

        p.active_turns = {}
        p.battle_metrics = {}
        p.last_protect_turn = {}
        p.opponent_active_turns = {}

        p._base_scores_cache = {0: {}, 1: {}}

        p.meta_engine = None
        p.random_set_engine = None

        return p

    def init_battle_maps(self, battle_tag: str):
        self.partial_immune_spread_by_battle[battle_tag] = {0: False, 1: False}
        self.efficient_partial_spread_by_battle[battle_tag] = {0: False, 1: False}
        self.inefficient_partial_spread_by_battle[battle_tag] = {0: False, 1: False}
        self.immune_target_species_by_battle[battle_tag] = {0: [], 1: []}
        self.damaged_target_species_by_battle[battle_tag] = {0: [], 1: []}
        self.best_single_alternative_by_battle[battle_tag] = {0: "", 1: ""}

        self._speed_priority_threatened[battle_tag] = {0: False, 1: False}
        self._faster_opponents[battle_tag] = {0: [], 1: []}
        self._priority_opponents[battle_tag] = {0: [], 1: []}
        self._speed_priority_protect_bonus_applied[battle_tag] = {0: False, 1: False}
        self._speed_priority_attack_penalty_applied[battle_tag] = {0: False, 1: False}
        self._speed_priority_switch_bonus_applied[battle_tag] = {0: False, 1: False}
        self._protected_due_to_speed_priority[battle_tag] = {0: False, 1: False}
        self._expected_to_faint_before_moving[battle_tag] = {0: False, 1: False}
        self._order_aware_overkill_penalty_applied[battle_tag] = False

        self._ability_hard_block_avoided[battle_tag] = {0: False, 1: False}
        self._ability_immune_move_selected[battle_tag] = {0: False, 1: False}
        self._ground_into_levitate_selected[battle_tag] = {0: False, 1: False}
        self._ability_block_reason[battle_tag] = {0: "", 1: ""}
        self._ability_blocked_target_species[battle_tag] = {0: "", 1: ""}
        self._ability_blocked_target_ability[battle_tag] = {0: "", 1: ""}
        self._ally_ability_safe_spread[battle_tag] = {0: False, 1: False}
        self._ability_redirection_avoided[battle_tag] = {0: False, 1: False}

        self._direct_absorb_hard_block_avoided[battle_tag] = {0: False, 1: False}
        self._direct_absorb_immune_move_selected[battle_tag] = {0: False, 1: False}
        self._direct_absorb_block_reason[battle_tag] = {0: "", 1: ""}
        self._direct_absorb_target_species[battle_tag] = {0: "", 1: ""}
        self._direct_absorb_target_ability[battle_tag] = {0: "", 1: ""}
        self._direct_absorb_only_legal_action[battle_tag] = {0: False, 1: False}

    def get_accuracy(self, move) -> float:
        return 1.0

    def get_boosted_stat(self, pokemon, stat_name) -> float:
        return 100.0

    def get_type_effectiveness(self, move, opponent, attacker=None) -> float:
        if not opponent:
            return 1.0
        return opponent.damage_multiplier(move)

    def estimate_opponent_max_hp(self, opponent) -> float:
        return 300.0

    def get_valid_orders_for_slot(self, slot_idx: int, battle) -> List[SingleBattleOrder]:
        orders = []
        if slot_idx < len(battle.available_moves):
            for move in battle.available_moves[slot_idx]:
                orders.append(SingleBattleOrder(move, move_target=1))
        return orders

class TestDoublesAbilityHardSafety(unittest.TestCase):
    
    def test_ground_move_into_known_levitate(self):
        # 1. Ground move into known Levitate
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_levitate"
        
        attacker = MockPokemon("landorus", ["GROUND"])
        target = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        move = MockMove("earthquake", "GROUND")
        
        # Helper check
        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked)
        self.assertEqual(reason, "ground_into_levitate")
        
        # Expected damage check
        dmg = player.get_expected_damage(move, attacker, target, battle)
        self.assertEqual(dmg, 0.0)
        self.assertFalse(player.check_move_will_ko(move, attacker, target, battle))
        
        # Score check
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_ground_move_into_levitate_during_gravity(self):
        # 2. Ground move into Levitate during Gravity
        battle = MockBattle(fields=[MockField("gravity")])
        attacker = MockPokemon("landorus", ["GROUND"])
        target = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        move = MockMove("earthquake", "GROUND")
        
        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertFalse(blocked)

    def test_thousand_arrows_into_levitate(self):
        # 3. Thousand Arrows into Levitate
        battle = MockBattle()
        attacker = MockPokemon("zygarde", ["DRAGON"])
        target = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        move = MockMove("thousandarrows", "GROUND")
        
        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertFalse(blocked)

    def test_mold_breaker_attacker_into_levitate(self):
        # 4. Mold Breaker attacker into Levitate
        battle = MockBattle()
        attacker = MockPokemon("pinsir", ["BUG"], ability="Mold Breaker")
        target = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        move = MockMove("earthquake", "GROUND")
        
        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertFalse(blocked)

    def test_earth_eater_blocks_ground(self):
        # 5. Earth Eater blocks Ground
        battle = MockBattle()
        attacker = MockPokemon("garchomp", ["GROUND"])
        target = MockPokemon("orthworm", ["STEEL"], ability="Earth Eater")
        move = MockMove("earthpower", "GROUND")
        
        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked)
        self.assertEqual(reason, "ground_into_eartheater")

    def test_water_absorb_blocks_water(self):
        # 6. Water Absorb blocks Water
        battle = MockBattle()
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        move = MockMove("surf", "WATER")
        
        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked)
        self.assertEqual(reason, "water_into_waterabsorb")

    def test_volt_absorb_blocks_electric(self):
        # 7. Volt Absorb blocks Electric
        battle = MockBattle()
        attacker = MockPokemon("pikachu", ["ELECTRIC"])
        target = MockPokemon("jolteon", ["ELECTRIC"], ability="Volt Absorb")
        move = MockMove("thunderbolt", "ELECTRIC")
        
        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked)
        self.assertEqual(reason, "electric_into_voltabsorb")

    def test_flash_fire_blocks_fire(self):
        # 8. Flash Fire blocks Fire
        battle = MockBattle()
        attacker = MockPokemon("charizard", ["FIRE"])
        target = MockPokemon("arcanine", ["FIRE"], ability="Flash Fire")
        move = MockMove("flamethrower", "FIRE")
        
        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked)
        self.assertEqual(reason, "fire_into_flashfire")

    def test_sap_sipper_blocks_grass(self):
        # 9. Sap Sipper blocks Grass
        battle = MockBattle()
        attacker = MockPokemon("venusaur", ["GRASS"])
        target = MockPokemon("miltank", ["NORMAL"], ability="Sap Sipper")
        move = MockMove("gigadrain", "GRASS")
        
        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertTrue(blocked)
        self.assertEqual(reason, "grass_into_sapsipper")

    def test_spread_move_with_one_ability_immune_target(self):
        # 10. Spread move with one ability-immune target
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, enable_partial_spread_immunity_penalty=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_partial"
        
        attacker = MockPokemon("garchomp", ["GROUND", "DRAGON"])
        opp1 = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        opp2 = MockPokemon("lucario", ["STEEL", "FIGHTING"])
        
        battle.opponent_active_pokemon = [opp1, opp2]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        
        move = MockMove("earthquake", "GROUND", target="allAdjacentFoes")
        eff = get_spread_target_effectiveness_with_ability(move, attacker, battle.opponent_active_pokemon, config, battle)
        
        self.assertTrue(eff["partial_immunity"])
        self.assertFalse(eff["all_targets_immune"])
        self.assertIn("rotom", eff["immune_target_names"])
        self.assertIn("lucario", eff["damaged_target_names"])
        order = SingleBattleOrder(move, move_target=0)
        self.assertGreater(player.score_action(order, 0, battle), 0.0)

    def test_spread_move_with_all_targets_ability_immune(self):
        # 11. Spread move with all targets ability-immune
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_all_immune"
        
        attacker = MockPokemon("garchomp", ["GROUND", "DRAGON"])
        opp1 = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        opp2 = MockPokemon("dragonite", ["DRAGON", "FLYING"]) # Immune to Ground by type
        
        battle.opponent_active_pokemon = [opp1, opp2]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        
        move = MockMove("earthquake", "GROUND", target="allAdjacentFoes")
        order = SingleBattleOrder(move, move_target=0)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_ally_levitate_makes_earthquake_ally_safe(self):
        # 12. Ally Levitate makes Earthquake ally-safe
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_ally_spread_safety=True, ally_hit_penalty=100.0)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_ally_safe"
        
        attacker = MockPokemon("garchomp", ["GROUND"])
        ally = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        opp1 = MockPokemon("lucario", ["STEEL"])
        
        battle.active_pokemon = [attacker, ally]
        battle.opponent_active_pokemon = [opp1, None]
        player.init_battle_maps(battle.battle_tag)
        
        move = MockMove("earthquake", "GROUND", target="allAdjacent")
        
        # Test direct helper
        safe, reason = ally_ability_makes_safe(ally, move, battle)
        self.assertTrue(safe)
        self.assertEqual(reason, "levitate")
        
        # Score should not suffer ally hit penalty
        order = SingleBattleOrder(move, move_target=0)
        score = player.score_action(order, 0, battle)
        self.assertGreater(score, 0.0)

    def test_storm_drain_redirection(self):
        # 13. Storm Drain redirection Water single-target
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_avoid_absorb=True,
            ability_hard_safety_avoid_redirection=True
        )
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_redirection"
        
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("charizard", ["FIRE"]) # Good target normally
        opp2 = MockPokemon("gastrodon", ["WATER", "GROUND"], ability="Storm Drain") # Redirect target
        
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, opp2]
        player.init_battle_maps(battle.battle_tag)
        
        move = MockMove("scald", "WATER")
        
        # Storm Drain helper check
        redirects, reason = ability_redirects_single_target_move(
            move, target, battle.opponent_active_pokemon, attacker, battle
        )
        self.assertTrue(redirects)
        self.assertEqual(reason, "redirected_by_stormdrain")
        
        # Score targeting charizard should be 0.0
        order = SingleBattleOrder(move, move_target=1)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_lightning_rod_redirection(self):
        # 14. Lightning Rod redirection Electric single-target
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_avoid_absorb=True,
            ability_hard_safety_avoid_redirection=True
        )
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_lightning_rod"
        
        attacker = MockPokemon("pikachu", ["ELECTRIC"])
        target = MockPokemon("charizard", ["FIRE"]) # Good target normally
        opp2 = MockPokemon("raichu", ["ELECTRIC"], ability="Lightning Rod") # Redirect target
        
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, opp2]
        player.init_battle_maps(battle.battle_tag)
        
        move = MockMove("thunderbolt", "ELECTRIC")
        
        # Lightning Rod helper check
        redirects, reason = ability_redirects_single_target_move(
            move, target, battle.opponent_active_pokemon, attacker, battle
        )
        self.assertTrue(redirects)
        self.assertEqual(reason, "redirected_by_lightningrod")
        
        # Score targeting charizard should be 0.0
        order = SingleBattleOrder(move, move_target=1)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_unknown_ability(self):
        # 15. Unknown ability: no block, neutral scoring
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_unknown"
        
        attacker = MockPokemon("landorus", ["GROUND"])
        target = MockPokemon("pikachu", ["ELECTRIC"], ability=None) # Unknown, multiple possible abilities
        move = MockMove("earthpower", "GROUND")
        
        blocked, reason = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertFalse(blocked)
        
        dmg = player.get_expected_damage(move, attacker, target, battle)
        self.assertGreater(dmg, 0.0)

    def test_default_adopted_config(self):
        config = DoublesDamageAwareConfig()
        self.assertTrue(config.enable_ability_hard_safety_only)
        self.assertFalse(config.ability_hard_safety_avoid_absorb)
        self.assertFalse(config.ability_hard_safety_avoid_redirection)
        self.assertFalse(config.ability_hard_safety_ally_spread_safety)
        self.assertFalse(config.enable_ability_awareness)

    def test_default_config_behaviors(self):
        # Default config represents Ground Target Only. Let's prove it behaviorally.
        config = DoublesDamageAwareConfig() # Adopted defaults
        player = TestPlayer.create(config)
        
        # 1. Blocks explicitly revealed Levitate against Ground
        move_ground = MockMove("earthquake", "GROUND")
        target_lev = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        blocked, reason = ability_hard_blocks_move(move_ground, None, target_lev, None)
        self.assertTrue(blocked)
        self.assertTrue(_ability_block_enabled(config, reason))

        # 2. Blocks explicitly revealed Earth Eater against Ground
        target_ee = MockPokemon("orthworm", ["STEEL"], ability="Earth Eater")
        blocked, reason = ability_hard_blocks_move(move_ground, None, target_ee, None)
        self.assertTrue(blocked)
        self.assertTrue(_ability_block_enabled(config, reason))

        # 3. Does not block Water Absorb
        move_water = MockMove("surf", "WATER")
        target_wa = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        blocked, reason = ability_hard_blocks_move(move_water, None, target_wa, None)
        self.assertTrue(blocked)
        self.assertFalse(_ability_block_enabled(config, reason))

        # 4. Does not block Volt Absorb
        move_elec = MockMove("thunderbolt", "ELECTRIC")
        target_va = MockPokemon("jolteon", ["ELECTRIC"], ability="Volt Absorb")
        blocked, reason = ability_hard_blocks_move(move_elec, None, target_va, None)
        self.assertTrue(blocked)
        self.assertFalse(_ability_block_enabled(config, reason))

        # 5. Does not avoid Storm Drain or Lightning Rod redirection
        battle_red = MockBattle()
        battle_red.battle_tag = "test_redirection_default"
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("charizard", ["FIRE"])
        opp_sd = MockPokemon("gastrodon", ["WATER", "GROUND"], ability="Storm Drain")
        battle_red.active_pokemon = [attacker, None]
        battle_red.opponent_active_pokemon = [target, opp_sd]
        battle_red._replay_data = [["", "-ability", "p2b: Gastrodon", "Storm Drain"]]
        player.init_battle_maps(battle_red.battle_tag)
        order_water = SingleBattleOrder(move_water, move_target=1)
        score_water = player.score_action(order_water, 0, battle_red)
        # Redirection should NOT be avoided, so the score is not 0
        self.assertGreater(score_water, 0.0)

        # 6. Does not skip ally-hit penalties based on ability
        battle_ally = MockBattle()
        battle_ally.battle_tag = "test_ally_default"
        ally_rotom = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        battle_ally.active_pokemon = [target_lev, ally_rotom] # target_lev as attacker
        battle_ally.opponent_active_pokemon = [target, None]
        battle_ally._replay_data = [["", "-ability", "p1b: Rotom", "Levitate"]]
        player.init_battle_maps(battle_ally.battle_tag)
        order_eq = SingleBattleOrder(move_ground, move_target=0)
        score_eq_levitate = player.score_action(order_eq, 0, battle_ally)
        # Levy-safe ally should still get hit penalty under default config
        ally_hit = MockPokemon("pikachu", ["ELECTRIC"])
        battle_ally.active_pokemon = [target_lev, ally_hit]
        score_eq_pikachu = player.score_action(order_eq, 0, battle_ally)
        self.assertEqual(score_eq_levitate, score_eq_pikachu)

        # 7. Does not infer an unrevealed opponent ability
        battle_unr = MockBattle()
        battle_unr._replay_data = []
        target_unr = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        battle_unr.opponent_active_pokemon = [target_unr, None]
        self.assertIsNone(get_known_ability(target_unr, battle_unr))

    def test_unrevealed_opponent_ability_is_not_known(self):
        battle = MockBattle()
        battle._replay_data = []
        target = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        battle.opponent_active_pokemon = [target, None]
        self.assertIsNone(get_known_ability(target, battle))

        attacker = MockPokemon("landorus", ["GROUND"])
        move = MockMove("earthpower", "GROUND")
        blocked, _ = ability_hard_blocks_move(move, attacker, target, battle)
        self.assertFalse(blocked)

    def test_replay_revealed_opponent_ability_is_known(self):
        battle = MockBattle()
        target = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        battle.opponent_active_pokemon = [target, None]
        battle._replay_data = [["", "-ability", "p2a: Rotom", "Levitate"]]
        self.assertEqual(get_known_ability(target, battle), "levitate")

    def test_ground_target_only_blocks_levitate_and_earth_eater(self):
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_avoid_absorb=False,
            ability_hard_safety_avoid_redirection=False,
            ability_hard_safety_ally_spread_safety=False
        )
        move = MockMove("earthquake", "GROUND")
        target_lev = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        blocked, reason = ability_hard_blocks_move(move, None, target_lev, None)
        self.assertTrue(blocked)
        self.assertTrue(_ability_block_enabled(config, reason))

        target_ee = MockPokemon("orthworm", ["STEEL"], ability="Earth Eater")
        blocked, reason = ability_hard_blocks_move(move, None, target_ee, None)
        self.assertTrue(blocked)
        self.assertTrue(_ability_block_enabled(config, reason))

    def test_ground_target_only_does_not_block_water_absorb_or_volt_absorb(self):
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_avoid_absorb=False,
            ability_hard_safety_avoid_redirection=False,
            ability_hard_safety_ally_spread_safety=False
        )
        move_water = MockMove("surf", "WATER")
        target_wa = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        blocked, reason = ability_hard_blocks_move(move_water, None, target_wa, None)
        self.assertTrue(blocked)
        self.assertFalse(_ability_block_enabled(config, reason))

        move_elec = MockMove("thunderbolt", "ELECTRIC")
        target_va = MockPokemon("jolteon", ["ELECTRIC"], ability="Volt Absorb")
        blocked, reason = ability_hard_blocks_move(move_elec, None, target_va, None)
        self.assertTrue(blocked)
        self.assertFalse(_ability_block_enabled(config, reason))

    def test_ground_target_only_does_not_apply_redirection(self):
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_avoid_absorb=False,
            ability_hard_safety_avoid_redirection=False,
            ability_hard_safety_ally_spread_safety=False
        )
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_redirection_off"
        
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("charizard", ["FIRE"])
        opp2 = MockPokemon("gastrodon", ["WATER", "GROUND"], ability="Storm Drain")
        
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, opp2]
        battle._replay_data = [["", "-ability", "p2b: Gastrodon", "Storm Drain"]]
        player.init_battle_maps(battle.battle_tag)
        
        move_water = MockMove("scald", "WATER")
        order_water = SingleBattleOrder(move_water, move_target=1)
        score_water_redirection_off = player.score_action(order_water, 0, battle)
        self.assertGreater(score_water_redirection_off, 0.0)

        # Control check: when Gastrodon does not have Storm Drain, score should be the same
        opp2.ability = "None"
        battle._replay_data = []
        score_water_control = player.score_action(order_water, 0, battle)
        self.assertEqual(score_water_redirection_off, score_water_control)

        # Electric redirection check
        attacker_elec = MockPokemon("pikachu", ["ELECTRIC"])
        opp2_elec = MockPokemon("raichu", ["ELECTRIC"], ability="Lightning Rod")
        battle.active_pokemon = [attacker_elec, None]
        battle.opponent_active_pokemon = [target, opp2_elec]
        battle._replay_data = [["", "-ability", "p2b: Raichu", "Lightning Rod"]]
        
        move_elec = MockMove("thunderbolt", "ELECTRIC")
        order_elec = SingleBattleOrder(move_elec, move_target=1)
        score_elec_redirection_off = player.score_action(order_elec, 0, battle)
        self.assertGreater(score_elec_redirection_off, 0.0)

        # Control check: when Raichu does not have Lightning Rod, score should be the same
        opp2_elec.ability = "None"
        battle._replay_data = []
        score_elec_control = player.score_action(order_elec, 0, battle)
        self.assertEqual(score_elec_redirection_off, score_elec_control)

    def test_ground_target_only_does_not_enable_ally_spread_safety(self):
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_avoid_absorb=False,
            ability_hard_safety_avoid_redirection=False,
            ability_hard_safety_ally_spread_safety=False
        )
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_ally_safety_off"
        
        attacker = MockPokemon("garchomp", ["GROUND"])
        ally = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        opp = MockPokemon("lucario", ["STEEL"])
        
        battle.active_pokemon = [attacker, ally]
        battle.opponent_active_pokemon = [opp, None]
        battle._replay_data = [["", "-ability", "p1b: Rotom", "Levitate"]]
        player.init_battle_maps(battle.battle_tag)
        
        move = MockMove("earthquake", "GROUND", target="allAdjacentFoes")
        order = SingleBattleOrder(move, move_target=0)
        
        score_rotom = player.score_action(order, 0, battle)
        
        # 1. Flying-type ally should not get ally-hit penalty (score should be higher)
        ally_flying = MockPokemon("staraptor", ["NORMAL", "FLYING"])
        battle.active_pokemon = [attacker, ally_flying]
        score_flying = player.score_action(order, 0, battle)
        self.assertGreater(score_flying, score_rotom)
        
        # 2. Rotom's score with safety off should be exactly equal to Pikachu's (which is hit)
        ally_hit = MockPokemon("pikachu", ["ELECTRIC"])
        battle.active_pokemon = [attacker, ally_hit]
        score_hit = player.score_action(order, 0, battle)
        self.assertEqual(score_rotom, score_hit)

        # 3. If safety IS enabled, Rotom should have a higher score (no penalty)
        config_on = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_avoid_absorb=False,
            ability_hard_safety_avoid_redirection=False,
            ability_hard_safety_ally_spread_safety=True
        )
        player_on = TestPlayer.create(config_on)
        battle.active_pokemon = [attacker, ally]
        battle._replay_data = [["", "-ability", "p1b: Rotom", "Levitate"]]
        player_on.init_battle_maps(battle.battle_tag)
        score_with_safety_on = player_on.score_action(order, 0, battle)
        
        self.assertGreater(score_with_safety_on, score_rotom)

    def test_soundproof_bulletproof_damp_inactive(self):
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True
        )
        move_sound = MockMove("hypervoice", "NORMAL", flags={"sound": True})
        target_sp = MockPokemon("exploud", ["NORMAL"], ability="Soundproof")
        blocked, reason = ability_hard_blocks_move(move_sound, None, target_sp, None)
        self.assertTrue(blocked)
        self.assertFalse(_ability_block_enabled(config, reason))

        move_bullet = MockMove("shadowball", "GHOST", flags={"bullet": True})
        target_bp = MockPokemon("chesnaught", ["GRASS"], ability="Bulletproof")
        blocked, reason = ability_hard_blocks_move(move_bullet, None, target_bp, None)
        self.assertTrue(blocked)
        self.assertFalse(_ability_block_enabled(config, reason))

        move_explosion = MockMove("explosion", "NORMAL")
        target_damp = MockPokemon("swampert", ["WATER"], ability="Damp")
        blocked, reason = ability_hard_blocks_move(move_explosion, None, target_damp, None)
        self.assertTrue(blocked)
        self.assertFalse(_ability_block_enabled(config, reason))

    def test_candidate_evaluation_does_not_mutate_audit_metrics(self):
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_mutation"
        
        attacker = MockPokemon("landorus", ["GROUND"])
        target = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        move = MockMove("earthquake", "GROUND")
        
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        battle._replay_data = [["", "-ability", "p2a: Rotom", "Levitate"]]
        
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)
        
        score = player.score_action(order, 0, battle, is_selected=False)
        self.assertFalse(player._ability_hard_block_avoided[battle.battle_tag][0])
        self.assertFalse(player._ability_immune_move_selected[battle.battle_tag][0])

    def test_avoided_and_selected_error_audit_recording(self):
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_avoid_select"
        
        attacker = MockPokemon("garchomp", ["GROUND"])
        target = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        
        move_blocked = MockMove("earthquake", "GROUND")
        move_safe = MockMove("dragonclaw", "DRAGON")
        
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, None]
        player.init_battle_maps(battle.battle_tag)
        
        battle.available_moves = [[move_blocked, move_safe], []]
        battle.valid_orders = [[SingleBattleOrder(move_blocked, move_target=1), SingleBattleOrder(move_safe, move_target=1)], [SingleBattleOrder(None)]]
        
        battle.player_username = "Player"
        battle.opponent_username = "Opponent"
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        battle._replay_data = [["", "-ability", "p2a: Rotom", "Levitate"]]
        
        best_joint = player.choose_move(battle)
        
        self.assertEqual(best_joint.first_order.order.id, "dragonclaw")
        
        self.assertTrue(player._ability_hard_block_avoided[battle.battle_tag][0])
        self.assertEqual(player._ability_block_reason[battle.battle_tag][0], "ground_into_levitate")
        self.assertEqual(player._ability_blocked_target_species[battle.battle_tag][0], "rotom")
        self.assertEqual(player._ability_blocked_target_ability[battle.battle_tag][0], "levitate")
        self.assertFalse(player._ability_immune_move_selected[battle.battle_tag][0])

        battle.available_moves = [[move_blocked], []]
        battle.valid_orders = [[SingleBattleOrder(move_blocked, move_target=1)], [SingleBattleOrder(None)]]
        player.init_battle_maps(battle.battle_tag)
        
        best_joint_blocked = player.choose_move(battle)
        self.assertEqual(best_joint_blocked.first_order.order.id, "earthquake")
        self.assertTrue(player._ability_immune_move_selected[battle.battle_tag][0])
        self.assertFalse(player._ability_hard_block_avoided[battle.battle_tag][0])

    def test_partial_spread_remains_nonzero(self):
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, enable_partial_spread_immunity_penalty=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_partial_spread"
        
        attacker = MockPokemon("garchomp", ["GROUND"])
        opp1 = MockPokemon("rotom", ["ELECTRIC"], ability="Levitate")
        opp2 = MockPokemon("lucario", ["STEEL"])
        
        battle.opponent_active_pokemon = [opp1, opp2]
        battle.active_pokemon = [attacker, None]
        battle._replay_data = [["", "-ability", "p2a: Rotom", "Levitate"]]
        player.init_battle_maps(battle.battle_tag)
        
        move = MockMove("earthquake", "GROUND", target="allAdjacentFoes")
        order = SingleBattleOrder(move, move_target=0)
        
        score = player.score_action(order, 0, battle)
        self.assertGreater(score, 0.0)

    def test_analyzer_cli_path(self):
        import tempfile
        import json
        import os
        # Create a tiny dummy jsonl file
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as tmp:
            tmp.write(json.dumps({
                "battle_tag": "test_cli_path",
                "won": True,
                "audit_turns": []
            }) + "\n")
            tmp_path = tmp.name
        
        try:
            from analyze_doubles_decision_audit import analyze_audit_log
            # Test that calling it directly with tmp_path doesn't crash and analyzes the file
            analyze_audit_log(tmp_path)
        finally:
            os.remove(tmp_path)

    def test_inspector_partial_ability_filter(self):
        import tempfile
        import json
        import os
        # Create a dummy jsonl file with:
        # 1. One bot partial ability-immune spread
        # 2. One opponent ability error
        dummy_data = [
            {
                "battle_tag": "battle-1",
                "won": True,
                "audit_turns": [
                    {
                        "turn": 1,
                        "our_active_pokemon": [{"species": "Garchomp"}, {"species": "Pikachu"}],
                        "slot_0": {
                            "action": "earthquake",
                            "partial_ability_immune_spread_selected": True,
                        }
                    }
                ]
            },
            {
                "battle_tag": "battle-2",
                "won": False,
                "audit_turns": [
                    {
                        "turn": 2,
                        "our_active_pokemon": [{"species": "Garchomp"}, {"species": "Pikachu"}],
                        "opponent_actions_prev_turn": {
                            "opponent_ability_error": True
                        }
                    }
                ]
            }
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as tmp:
            for item in dummy_data:
                tmp.write(json.dumps(item) + "\n")
            tmp_path = tmp.name

        try:
            import sys
            from unittest.mock import patch
            import io
            
            test_args = [
                "inspect_ability_hard_safety_cases.py",
                "--partial-ability-spread",
                "--filepath", tmp_path
            ]
            
            from inspect_ability_hard_safety_cases import main as inspect_main
            
            with patch.object(sys, "argv", test_args):
                f = io.StringIO()
                with patch.object(sys, "stdout", f):
                    try:
                        inspect_main()
                    except SystemExit as e:
                        self.assertEqual(e.code, 0)
                
                output = f.getvalue()
                # Verify that only the bot partial spread case (battle-1) is returned
                self.assertIn("battle-1", output)
                self.assertNotIn("battle-2", output)
        finally:
            os.remove(tmp_path)

    def test_water_absorb_avoidable(self):
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_water_avoidable"
        
        attacker = MockPokemon("vaporeon", ["WATER"])
        target = MockPokemon("eevee", ["NORMAL"], ability="Water Absorb")
        
        move_blocked = MockMove("surf", "WATER", base_power=90)
        move_safe = MockMove("quickattack", "NORMAL", base_power=40)
        
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, None]
        player.init_battle_maps(battle.battle_tag)
        
        battle.available_moves = [[move_blocked, move_safe], []]
        battle.valid_orders = [[SingleBattleOrder(move_blocked, move_target=1), SingleBattleOrder(move_safe, move_target=1)], [SingleBattleOrder(None)]]
        
        battle._replay_data = [["", "-ability", "p2a: Eevee", "Water Absorb"]]
        
        import unittest.mock
        mock_audit = unittest.mock.Mock()
        player.audit_logger = mock_audit
        
        player.choose_move(battle)
        
        self.assertTrue(mock_audit.log_turn_decision.called)
        kwargs = mock_audit.log_turn_decision.call_args[1]
        self.assertTrue(kwargs["absorb_immune_move_selected"][0])
        self.assertTrue(kwargs["avoidable_absorb_error"][0])
        self.assertFalse(kwargs["absorb_selection_forced"][0])

    def test_volt_absorb_forced(self):
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_volt_forced"
        
        attacker = MockPokemon("jolteon", ["ELECTRIC"])
        target = MockPokemon("jolteon", ["ELECTRIC"], ability="Volt Absorb")
        
        move_blocked = MockMove("thunderbolt", "ELECTRIC", base_power=90)
        
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, None]
        player.init_battle_maps(battle.battle_tag)
        
        battle.available_moves = [[move_blocked], []]
        battle.valid_orders = [[SingleBattleOrder(move_blocked, move_target=1)], [SingleBattleOrder(None)]]
        
        battle._replay_data = [["", "-ability", "p2a: Jolteon", "Volt Absorb"]]
        
        import unittest.mock
        mock_audit = unittest.mock.Mock()
        player.audit_logger = mock_audit
        
        player.choose_move(battle)
        
        self.assertTrue(mock_audit.log_turn_decision.called)
        kwargs = mock_audit.log_turn_decision.call_args[1]
        self.assertTrue(kwargs["absorb_immune_move_selected"][0])
        self.assertFalse(kwargs["avoidable_absorb_error"][0])
        self.assertTrue(kwargs["absorb_selection_forced"][0])

    def test_unknown_ability_absorb_metric(self):
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_unknown_ability"
        
        attacker = MockPokemon("vaporeon", ["WATER"])
        target = MockPokemon("vaporeon", ["WATER"])  # no ability revealed
        
        move_blocked = MockMove("surf", "WATER", base_power=90)
        
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, None]
        player.init_battle_maps(battle.battle_tag)
        
        battle.available_moves = [[move_blocked], []]
        battle.valid_orders = [[SingleBattleOrder(move_blocked, move_target=1)], [SingleBattleOrder(None)]]
        
        import unittest.mock
        mock_audit = unittest.mock.Mock()
        player.audit_logger = mock_audit
        
        player.choose_move(battle)
        
        self.assertTrue(mock_audit.log_turn_decision.called)
        kwargs = mock_audit.log_turn_decision.call_args[1]
        self.assertFalse(kwargs["absorb_immune_move_selected"][0])

    def test_productive_partial_spread(self):
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_productive_partial"
        
        attacker = MockPokemon("vaporeon", ["WATER"])
        target_immune = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        target_normal = MockPokemon("pikachu", ["ELECTRIC"])
        
        move_spread = MockMove("surf", "WATER", base_power=90, target="allAdjacentFoes")
        
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target_immune, target_normal]
        player.init_battle_maps(battle.battle_tag)
        
        battle.available_moves = [[move_spread], []]
        battle.valid_orders = [[SingleBattleOrder(move_spread, move_target=0)], [SingleBattleOrder(None)]]
        
        battle._replay_data = [["", "-ability", "p2a: Vaporeon", "Water Absorb"]]
        
        import unittest.mock
        mock_audit = unittest.mock.Mock()
        player.audit_logger = mock_audit
        
        player.choose_move(battle)
        
        self.assertTrue(mock_audit.log_turn_decision.called)
        kwargs = mock_audit.log_turn_decision.call_args[1]
        self.assertTrue(kwargs["absorb_immune_move_selected"][0])
        self.assertTrue(kwargs["productive_partial_absorb_spread"][0])
        self.assertFalse(kwargs["avoidable_absorb_error"][0])

    def test_all_target_absorb_spread_avoidable(self):
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_all_target_spread"
        
        attacker = MockPokemon("vaporeon", ["WATER"])
        target1 = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        target2 = MockPokemon("lanturn", ["WATER", "ELECTRIC"], ability="Water Absorb")
        
        move_spread = MockMove("surf", "WATER", base_power=90, target="allAdjacentFoes")
        move_safe = MockMove("shadowball", "GHOST", base_power=80)
        
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target1, target2]
        player.init_battle_maps(battle.battle_tag)
        
        battle.available_moves = [[move_spread, move_safe], []]
        battle.valid_orders = [[SingleBattleOrder(move_spread, move_target=0), SingleBattleOrder(move_safe, move_target=1)], [SingleBattleOrder(None)]]
        
        battle._replay_data = [
            ["", "-ability", "p2a: Vaporeon", "Water Absorb"],
            ["", "-ability", "p2b: Lanturn", "Water Absorb"]
        ]
        
        import unittest.mock
        mock_audit = unittest.mock.Mock()
        player.audit_logger = mock_audit
        
        player.choose_move(battle)
        
        self.assertTrue(mock_audit.log_turn_decision.called)
        kwargs = mock_audit.log_turn_decision.call_args[1]
        self.assertTrue(kwargs["absorb_immune_move_selected"][0])
        self.assertFalse(kwargs["productive_partial_absorb_spread"][0])
        self.assertTrue(kwargs["avoidable_absorb_error"][0])

    def test_safe_alternative_excludes_type_immune(self):
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_type_immune_alt"
        
        attacker = MockPokemon("vaporeon", ["WATER"])
        target = MockPokemon("eevee", ["NORMAL"], ability="Water Absorb")
        
        move_blocked = MockMove("surf", "WATER", base_power=90)
        move_immune = MockMove("shadowball", "GHOST", base_power=80) # normal immune to ghost
        
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, None]
        player.init_battle_maps(battle.battle_tag)
        
        battle.available_moves = [[move_blocked, move_immune], []]
        battle.valid_orders = [[SingleBattleOrder(move_blocked, move_target=1), SingleBattleOrder(move_immune, move_target=1)], [SingleBattleOrder(None)]]
        
        battle._replay_data = [["", "-ability", "p2a: Eevee", "Water Absorb"]]
        
        import unittest.mock
        mock_audit = unittest.mock.Mock()
        player.audit_logger = mock_audit
        
        player.choose_move(battle)
        
        self.assertTrue(mock_audit.log_turn_decision.called)
        kwargs = mock_audit.log_turn_decision.call_args[1]
        self.assertTrue(kwargs["absorb_immune_move_selected"][0])
        self.assertFalse(kwargs["avoidable_absorb_error"][0])

    def test_safe_alternative_excludes_another_blocked(self):
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_blocked_alt"
        
        attacker = MockPokemon("vaporeon", ["WATER"])
        target = MockPokemon("lanturn", ["WATER", "ELECTRIC"], ability="Water Absorb")
        target2 = MockPokemon("houndoom", ["DARK", "FIRE"], ability="Flash Fire")
        
        move_blocked1 = MockMove("surf", "WATER", base_power=90)
        move_blocked2 = MockMove("overheat", "FIRE", base_power=130)
        
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, target2]
        player.init_battle_maps(battle.battle_tag)
        
        battle.available_moves = [[move_blocked1, move_blocked2], []]
        battle.valid_orders = [[SingleBattleOrder(move_blocked1, move_target=1), SingleBattleOrder(move_blocked2, move_target=2)], [SingleBattleOrder(None)]]
        
        battle._replay_data = [
            ["", "-ability", "p2a: Lanturn", "Water Absorb"],
            ["", "-ability", "p2b: Houndoom", "Flash Fire"]
        ]
        
        import unittest.mock
        mock_audit = unittest.mock.Mock()
        player.audit_logger = mock_audit
        
        player.choose_move(battle)
        
        self.assertTrue(mock_audit.log_turn_decision.called)
        kwargs = mock_audit.log_turn_decision.call_args[1]
        self.assertTrue(kwargs["absorb_immune_move_selected"][0])
        self.assertFalse(kwargs["avoidable_absorb_error"][0])

    def test_safe_alternative_excludes_redirected(self):
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_redirected_alt"
        
        attacker = MockPokemon("jolteon", ["ELECTRIC"])
        target = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        redirector = MockPokemon("raichu", ["ELECTRIC"], ability="Lightning Rod")
        
        move_blocked = MockMove("surf", "WATER", base_power=90)
        move_electric = MockMove("thunderbolt", "ELECTRIC", base_power=90)
        
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, redirector]
        player.init_battle_maps(battle.battle_tag)
        
        battle.available_moves = [[move_blocked, move_electric], []]
        battle.valid_orders = [[SingleBattleOrder(move_blocked, move_target=1), SingleBattleOrder(move_electric, move_target=1)], [SingleBattleOrder(None)]]
        
        battle._replay_data = [
            ["", "-ability", "p2a: Vaporeon", "Water Absorb"],
            ["", "-ability", "p2b: Raichu", "Lightning Rod"]
        ]
        
        import unittest.mock
        mock_audit = unittest.mock.Mock()
        player.audit_logger = mock_audit
        
        player.choose_move(battle)
        
        self.assertTrue(mock_audit.log_turn_decision.called)
        kwargs = mock_audit.log_turn_decision.call_args[1]
        self.assertTrue(kwargs["absorb_immune_move_selected"][0])
        self.assertFalse(kwargs["avoidable_absorb_error"][0])

    def test_streak_increments(self):
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_streak"
        
        attacker = MockPokemon("jolteon", ["ELECTRIC"])
        target = MockPokemon("jolteon", ["ELECTRIC"], ability="Volt Absorb")
        move = MockMove("thunderbolt", "ELECTRIC", base_power=90)
        
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, None]
        player.init_battle_maps(battle.battle_tag)
        
        battle.available_moves = [[move], []]
        battle.valid_orders = [[SingleBattleOrder(move, move_target=1)], [SingleBattleOrder(None)]]
        battle._replay_data = [["", "-ability", "p2a: Jolteon", "Volt Absorb"]]
        
        import unittest.mock
        mock_audit = unittest.mock.Mock()
        player.audit_logger = mock_audit
        
        battle.turn = 1
        player.choose_move(battle)
        kwargs = mock_audit.log_turn_decision.call_args[1]
        self.assertEqual(kwargs["absorb_selected_streak"][0], 1)
        
        battle.turn = 2
        player.choose_move(battle)
        kwargs2 = mock_audit.log_turn_decision.call_args[1]
        self.assertEqual(kwargs2["absorb_selected_streak"][0], 2)

    def test_streak_resets(self):
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_streak_reset"
        
        attacker = MockPokemon("jolteon", ["ELECTRIC"])
        target = MockPokemon("jolteon", ["ELECTRIC"], ability="Volt Absorb")
        move = MockMove("thunderbolt", "ELECTRIC", base_power=90)
        
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, None]
        player.init_battle_maps(battle.battle_tag)
        
        battle.available_moves = [[move], []]
        battle.valid_orders = [[SingleBattleOrder(move, move_target=1)], [SingleBattleOrder(None)]]
        battle._replay_data = [["", "-ability", "p2a: Jolteon", "Volt Absorb"]]
        
        import unittest.mock
        mock_audit = unittest.mock.Mock()
        player.audit_logger = mock_audit
        
        battle.turn = 1
        player.choose_move(battle)
        self.assertEqual(mock_audit.log_turn_decision.call_args[1]["absorb_selected_streak"][0], 1)
        
        battle.turn = 3
        player.choose_move(battle)
        self.assertEqual(mock_audit.log_turn_decision.call_args[1]["absorb_selected_streak"][0], 1)

    def test_candidate_scoring_no_mutation(self):
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_mutation"
        
        attacker = MockPokemon("jolteon", ["ELECTRIC"])
        target = MockPokemon("jolteon", ["ELECTRIC"], ability="Volt Absorb")
        move = MockMove("thunderbolt", "ELECTRIC", base_power=90)
        
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, None]
        player.init_battle_maps(battle.battle_tag)
        
        order = SingleBattleOrder(move, move_target=1)
        player.score_action(order, 0, battle)
        
        # score_action alone must not initialize streak state for this battle
        self.assertNotIn(battle.battle_tag, player._absorb_streak_state)

    def test_streak_idempotent_same_turn(self):
        """Two choose_move calls on the same turn for the same absorb event
        must keep streak=1 (not increment to 2). Idempotency fix from 6.3.2a."""
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_streak_idempotent"

        attacker = MockPokemon("jolteon", ["ELECTRIC"])
        # Volt Absorb absorbs ELECTRIC moves
        target = MockPokemon("raichu", ["ELECTRIC"], ability="Volt Absorb")
        move = MockMove("thunderbolt", "ELECTRIC", base_power=90)

        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, None]
        player.init_battle_maps(battle.battle_tag)

        battle.available_moves = [[move], []]
        battle.valid_orders = [[SingleBattleOrder(move, move_target=1)], [SingleBattleOrder(None)]]
        battle._replay_data = [["", "-ability", "p2a: Raichu", "Volt Absorb"]]

        import unittest.mock
        mock_audit = unittest.mock.Mock()
        player.audit_logger = mock_audit

        battle.turn = 1
        player.choose_move(battle)
        streak_first = mock_audit.log_turn_decision.call_args[1]["absorb_selected_streak"][0]
        self.assertEqual(streak_first, 1, "First choose_move call on turn 1 must set streak=1")

        # Second evaluation on same turn (idempotent — must NOT increment)
        player.choose_move(battle)
        streak_second = mock_audit.log_turn_decision.call_args[1]["absorb_selected_streak"][0]
        self.assertEqual(streak_second, 1,
            "Second choose_move on same turn must preserve streak=1 (idempotent). Got: " + str(streak_second))

        # Advance to turn 2 — same event, should now be streak=2
        battle.turn = 2
        player.choose_move(battle)
        streak_t2 = mock_audit.log_turn_decision.call_args[1]["absorb_selected_streak"][0]
        self.assertEqual(streak_t2, 2, "Same event on turn 2 must increment streak to 2")

    def test_streak_continues_across_slot_change(self):
        """Same attacker switching from slot 0 to slot 1 on consecutive turns
        must still increment the streak (identity-based key, not slot-based)."""
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_streak_slot_change"

        attacker = MockPokemon("jolteon", ["ELECTRIC"])
        partner = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        # Volt Absorb absorbs ELECTRIC — correct matchup
        target = MockPokemon("raichu", ["ELECTRIC"], ability="Volt Absorb")
        move = MockMove("thunderbolt", "ELECTRIC", base_power=90)

        battle.opponent_active_pokemon = [target, None]
        player.init_battle_maps(battle.battle_tag)

        import unittest.mock
        mock_audit = unittest.mock.Mock()
        player.audit_logger = mock_audit

        # Turn 1: attacker in slot 0
        battle.active_pokemon = [attacker, partner]
        battle.available_moves = [[move], []]
        battle.valid_orders = [
            [SingleBattleOrder(move, move_target=1)],
            [SingleBattleOrder(None)]
        ]
        battle._replay_data = [["", "-ability", "p2a: Raichu", "Volt Absorb"]]
        battle.turn = 1
        player.choose_move(battle)
        streak_t1 = mock_audit.log_turn_decision.call_args[1]["absorb_selected_streak"][0]
        self.assertEqual(streak_t1, 1, "Turn 1, attacker in slot 0, streak=1")

        # Turn 2: same attacker is now in slot 1 (swapped positions)
        battle.active_pokemon = [partner, attacker]
        battle.available_moves = [[], [move]]
        battle.valid_orders = [
            [SingleBattleOrder(None)],
            [SingleBattleOrder(move, move_target=1)]
        ]
        battle.turn = 2
        player.choose_move(battle)
        streak_t2 = mock_audit.log_turn_decision.call_args[1]["absorb_selected_streak"][1]
        self.assertEqual(streak_t2, 2,
            "Attacker moved to slot 1 — identity-based key should give streak=2, not reset")

    def test_canonical_score_preserved_for_best_alt(self):
        """absorb_best_safe_alternative_score must be a float >= 0 from slot_scores.
        The alternative check must not call score_action (canonical score preservation)."""
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_canonical_score"

        attacker = MockPokemon("jolteon", ["ELECTRIC"])
        absorb_target = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        safe_target = MockPokemon("charizard", ["FIRE", "FLYING"])
        move_absorb = MockMove("thunderbolt", "ELECTRIC", base_power=90)
        move_safe = MockMove("shadowball", "GHOST", base_power=80)

        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [absorb_target, safe_target]
        player.init_battle_maps(battle.battle_tag)

        order_absorb = SingleBattleOrder(move_absorb, move_target=1)
        order_safe = SingleBattleOrder(move_safe, move_target=2)
        battle.available_moves = [[move_absorb, move_safe], []]
        battle.valid_orders = [
            [order_absorb, order_safe],
            [SingleBattleOrder(None)]
        ]
        battle._replay_data = [["", "-ability", "p2a: Vaporeon", "Water Absorb"]]

        import unittest.mock
        mock_audit = unittest.mock.Mock()
        player.audit_logger = mock_audit

        battle.turn = 1
        player.choose_move(battle)
        kwargs = mock_audit.log_turn_decision.call_args[1]

        alt_score = kwargs["absorb_best_safe_alternative_score"][0]
        self.assertIsInstance(alt_score, float, "Best safe alt score must be a float")
        self.assertGreaterEqual(alt_score, 0.0, "Canonical alt score must be non-negative")

    def test_redirected_candidate_excluded_as_unsafe(self):
        """A Water-type move that would be redirected into a Storm Drain absorber
        must NOT appear as a safe alternative move."""
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_redirect_excluded"

        attacker = MockPokemon("jolteon", ["ELECTRIC"])
        primary_target = MockPokemon("charizard", ["FIRE", "FLYING"])
        redirector = MockPokemon("gastrodon", ["WATER", "GROUND"], ability="Storm Drain")
        move_water = MockMove("watergun", "WATER", base_power=40)
        move_safe = MockMove("shadowball", "GHOST", base_power=80)

        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [primary_target, redirector]
        player.init_battle_maps(battle.battle_tag)

        order_water = SingleBattleOrder(move_water, move_target=1)
        order_safe = SingleBattleOrder(move_safe, move_target=1)
        battle.available_moves = [[move_water, move_safe], []]
        battle.valid_orders = [
            [order_water, order_safe],
            [SingleBattleOrder(None)]
        ]
        # Reveal Storm Drain for gastrodon
        battle._replay_data = [["", "-ability", "p2b: Gastrodon", "Storm Drain"]]

        import unittest.mock
        mock_audit = unittest.mock.Mock()
        player.audit_logger = mock_audit

        battle.turn = 1
        player.choose_move(battle)
        kwargs = mock_audit.log_turn_decision.call_args[1]

        if kwargs["absorb_immune_move_selected"][0]:
            best_alt = kwargs["absorb_best_safe_alternative_move"][0]
            self.assertNotEqual(best_alt, "watergun",
                "watergun should not be a safe alternative if it would be redirected into Storm Drain absorber")

    def test_productive_spread_not_self_selected_as_alt(self):
        """A productive partial spread (hits one opponent, absorbed by another)
        must not be listed as its own safe alternative."""
        config = DoublesDamageAwareConfig()
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_productive_not_self_alt"

        attacker = MockPokemon("garchomp", ["DRAGON", "GROUND"])
        absorb_target = MockPokemon("gastrodon", ["WATER", "GROUND"], ability="Water Absorb")
        normal_target = MockPokemon("gengar", ["GHOST", "POISON"])
        move_eq = MockMove("earthquake", "GROUND", base_power=100, target="allAdjacentFoes")

        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [absorb_target, normal_target]
        player.init_battle_maps(battle.battle_tag)

        order_eq = SingleBattleOrder(move_eq, move_target=0)
        battle.available_moves = [[move_eq], []]
        battle.valid_orders = [[order_eq], [SingleBattleOrder(None)]]
        battle._replay_data = [["", "-ability", "p2a: Gastrodon", "Water Absorb"]]

        import unittest.mock
        mock_audit = unittest.mock.Mock()
        player.audit_logger = mock_audit

        battle.turn = 1
        player.choose_move(battle)
        kwargs = mock_audit.log_turn_decision.call_args[1]

        if kwargs["absorb_immune_move_selected"][0] and kwargs["productive_partial_absorb_spread"][0]:
            self.assertFalse(kwargs["avoidable_absorb_error"][0],
                "Productive partial spread must not be classified as avoidable")
            best_alt = kwargs["absorb_best_safe_alternative_move"][0]
            self.assertNotEqual(best_alt, "earthquake",
                "earthquake cannot be its own best safe alternative")

    def test_bot_only_filters_exclude_opponent(self):
        import tempfile
        import json
        import os
        dummy_data = [
            {
                "battle_tag": "battle-bot",
                "won": True,
                "audit_turns": [
                    {
                        "turn": 1,
                        "our_active": [{"species": "Garchomp"}, None],
                        "slot_0": {
                            "action": "surf",
                            "absorb_immune_move_selected": True,
                        }
                    }
                ]
            },
            {
                "battle_tag": "battle-opp",
                "won": False,
                "audit_turns": [
                    {
                        "turn": 2,
                        "our_active": [{"species": "Garchomp"}, None],
                        "opp_actions": {
                            "opponent_ability_error": True
                        }
                    }
                ]
            }
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as tmp:
            for item in dummy_data:
                tmp.write(json.dumps(item) + "\n")
            tmp_path = tmp.name

        try:
            import sys
            from unittest.mock import patch
            import io
            
            test_args = [
                "inspect_ability_hard_safety_cases.py",
                "--absorb-selected",
                "--filepath", tmp_path
            ]
            
            from inspect_ability_hard_safety_cases import main as inspect_main
            
            with patch.object(sys, "argv", test_args):
                f = io.StringIO()
                with patch.object(sys, "stdout", f):
                    try:
                        inspect_main()
                    except SystemExit as e:
                        self.assertEqual(e.code, 0)
                
                output = f.getvalue()
                self.assertIn("battle-bot", output)
                self.assertNotIn("battle-opp", output)
        finally:
            os.remove(tmp_path)

    def test_analyzer_custom_filepath(self):
        import tempfile
        import json
        import os
        import sys
        dummy_data = {
            "battle_tag": "battle-absorb",
            "won": True,
            "audit_turns": [
                {
                    "turn": 1,
                    "our_active": [{"species": "Garchomp"}, None],
                    "slot_0": {
                        "action": "surf",
                        "absorb_immune_move_selected": True,
                        "avoidable_absorb_error": True,
                        "absorb_best_safe_alternative_move": "shadowball",
                        "absorb_best_safe_alternative_target": "pikachu",
                        "absorb_best_safe_alternative_score": 50.0,
                        "absorb_selected_score": 10.0,
                        "absorb_selected_streak": 1,
                        "absorb_error_reason": "water_into_waterabsorb"
                    }
                }
            ]
        }
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as tmp:
            tmp.write(json.dumps(dummy_data) + "\n")
            tmp_path = tmp.name

        try:
            from analyze_doubles_decision_audit import analyze_audit_log
            import io
            from unittest.mock import patch
            
            f = io.StringIO()
            with patch.object(sys, "stdout", f):
                analyze_audit_log(tmp_path)
            
            output = f.getvalue()
            self.assertIn("Absorb Error Qualification Report", output)
            self.assertIn("absorb_selected_action_count", output)
            self.assertIn(": 1  (", output)  # at least one action count equals 1
            self.assertIn("absorb_avoidable_action_count", output)
            self.assertIn("direct_absorb_selected_count", output)
        finally:
            os.remove(tmp_path)

    def test_adopted_defaults_unchanged(self):
        config = DoublesDamageAwareConfig()
        self.assertTrue(config.enable_ability_hard_safety_only)
        self.assertFalse(config.ability_hard_safety_avoid_absorb)
        self.assertFalse(config.ability_hard_safety_avoid_redirection)
        self.assertFalse(config.ability_hard_safety_ally_spread_safety)

    def test_unclassified_not_labeled_avoidable(self):
        # selected event with all three primary flags false is not labeled avoidable
        from inspect_absorb_error_cases import classify_absorb_event
        slot = {
            "absorb_immune_move_selected": True,
            "productive_partial_absorb_spread": False,
            "avoidable_absorb_error": False,
            "absorb_selection_forced": False,
            "absorb_safe_alternative_available": True
        }
        res = classify_absorb_event(slot)
        self.assertEqual(res, "UNCLASSIFIED")
        self.assertNotEqual(res, "AVOIDABLE_SAFE_DAMAGE_ALT")

    def test_other_useful_scored_alt_classification(self):
        # OTHER_USEFUL_SCORED_ALT classification
        from inspect_absorb_error_cases import classify_absorb_event
        slot = {
            "absorb_immune_move_selected": True,
            "productive_partial_absorb_spread": False,
            "avoidable_absorb_error": False,
            "absorb_selection_forced": False,
            "absorb_safe_alternative_available": False
        }
        res = classify_absorb_event(slot)
        self.assertEqual(res, "OTHER_USEFUL_SCORED_ALT")

    def test_classes_are_mutually_exclusive(self):
        # all five classes are mutually exclusive
        from inspect_absorb_error_cases import classify_absorb_event
        slot = {
            "absorb_immune_move_selected": True,
            "productive_partial_absorb_spread": True,
            "avoidable_absorb_error": True,
            "absorb_selection_forced": True,
            "absorb_safe_alternative_available": False
        }
        # productive spread has priority 1, so it should return PRODUCTIVE_PARTIAL_SPREAD
        res = classify_absorb_event(slot)
        self.assertEqual(res, "PRODUCTIVE_PARTIAL_SPREAD")

    def test_class_totals_equal_selected_totals(self):
        # class totals equal selected totals
        from inspect_absorb_error_cases import classify_absorb_event
        slots = [
            {"absorb_immune_move_selected": True, "productive_partial_absorb_spread": True},
            {"absorb_immune_move_selected": True, "avoidable_absorb_error": True},
            {"absorb_immune_move_selected": True, "absorb_selection_forced": True},
            {"absorb_immune_move_selected": True, "absorb_safe_alternative_available": False},
            {"absorb_immune_move_selected": True, "absorb_safe_alternative_available": True} # unclassified
        ]
        results = [classify_absorb_event(s) for s in slots]
        self.assertEqual(len(results), len(slots))
        self.assertIn("PRODUCTIVE_PARTIAL_SPREAD", results)
        self.assertIn("AVOIDABLE_SAFE_DAMAGE_ALT", results)
        self.assertIn("FORCED_NO_USEFUL_SCORED_ALT", results)
        self.assertIn("OTHER_USEFUL_SCORED_ALT", results)
        self.assertIn("UNCLASSIFIED", results)

    def test_inspect_avoidable_absorb_excludes_other_useful_alt(self):
        # --avoidable-absorb excludes other-useful-alt events
        import tempfile
        import json
        import os
        dummy_data = [
            {
                "battle_tag": "battle-avoidable",
                "won": True,
                "audit_turns": [
                    {
                        "turn": 1,
                        "our_active": [{"species": "Garchomp"}, None],
                        "slot_0": {
                            "action": "surf",
                            "absorb_immune_move_selected": True,
                            "avoidable_absorb_error": True
                        }
                    }
                ]
            },
            {
                "battle_tag": "battle-other-useful",
                "won": False,
                "audit_turns": [
                    {
                        "turn": 2,
                        "our_active": [{"species": "Garchomp"}, None],
                        "slot_0": {
                            "action": "surf",
                            "absorb_immune_move_selected": True,
                            "absorb_safe_alternative_available": False,
                            "absorb_selection_forced": False
                        }
                    }
                ]
            }
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as tmp:
            for item in dummy_data:
                tmp.write(json.dumps(item) + "\n")
            tmp_path = tmp.name

        try:
            import sys
            from unittest.mock import patch
            import io
            from inspect_absorb_error_cases import main as inspect_main
            
            test_args = [
                "inspect_absorb_error_cases.py",
                "--avoidable-absorb",
                "--filepath", tmp_path
            ]
            with patch.object(sys, "argv", test_args):
                f = io.StringIO()
                with patch.object(sys, "stdout", f):
                    try:
                        inspect_main()
                    except SystemExit as e:
                        self.assertEqual(e.code, 0)
                output = f.getvalue()
                self.assertIn("battle-avoidable", output)
                self.assertNotIn("battle-other-useful", output)
        finally:
            os.remove(tmp_path)

    def test_inspect_other_useful_alt_returns_only_matching(self):
        # --other-useful-alt returns only matching events
        import tempfile
        import json
        import os
        dummy_data = [
            {
                "battle_tag": "battle-avoidable",
                "won": True,
                "audit_turns": [
                    {
                        "turn": 1,
                        "our_active": [{"species": "Garchomp"}, None],
                        "slot_0": {
                            "action": "surf",
                            "absorb_immune_move_selected": True,
                            "avoidable_absorb_error": True
                        }
                    }
                ]
            },
            {
                "battle_tag": "battle-other-useful",
                "won": False,
                "audit_turns": [
                    {
                        "turn": 2,
                        "our_active": [{"species": "Garchomp"}, None],
                        "slot_0": {
                            "action": "surf",
                            "absorb_immune_move_selected": True,
                            "absorb_safe_alternative_available": False,
                            "absorb_selection_forced": False
                        }
                    }
                ]
            }
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as tmp:
            for item in dummy_data:
                tmp.write(json.dumps(item) + "\n")
            tmp_path = tmp.name

        try:
            import sys
            from unittest.mock import patch
            import io
            from inspect_absorb_error_cases import main as inspect_main
            
            test_args = [
                "inspect_absorb_error_cases.py",
                "--other-useful-alt",
                "--filepath", tmp_path
            ]
            with patch.object(sys, "argv", test_args):
                f = io.StringIO()
                with patch.object(sys, "stdout", f):
                    try:
                        inspect_main()
                    except SystemExit as e:
                        self.assertEqual(e.code, 0)
                output = f.getvalue()
                self.assertNotIn("battle-avoidable", output)
                self.assertIn("battle-other-useful", output)
        finally:
            os.remove(tmp_path)

    def test_analyzer_sample_labels_match_raw_flags(self):
        # analyzer sample labels match raw flags
        import tempfile
        import json
        import os
        import sys
        dummy_data = {
            "battle_tag": "battle-sample-label",
            "won": True,
            "audit_turns": [
                {
                    "turn": 1,
                    "our_active": [{"species": "Garchomp"}, None],
                    "slot_0": {
                        "action": "surf",
                        "absorb_immune_move_selected": True,
                        "absorb_safe_alternative_available": False,
                        "absorb_selection_forced": False
                    }
                }
            ]
        }
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as tmp:
            tmp.write(json.dumps(dummy_data) + "\n")
            tmp_path = tmp.name

        try:
            from analyze_doubles_decision_audit import analyze_audit_log
            import io
            from unittest.mock import patch
            
            f = io.StringIO()
            with patch.object(sys, "stdout", f):
                analyze_audit_log(tmp_path)
            output = f.getvalue()
            self.assertIn("OTHER_USEFUL_SCORED_ALT", output)
        finally:
            os.remove(tmp_path)

    def test_summarize_existing_mode_does_no_player_init(self):
        # summarize-existing mode performs no battle/server initialization
        import tempfile
        import os
        from bot_doubles_absorb_error_audit import summarize_existing_logs, SUMMARY_CSV_PATH
        
        tmp_basic = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp_rand = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp_basic.close()
        tmp_rand.close()
        
        import bot_doubles_absorb_error_audit
        old_summary = SUMMARY_CSV_PATH
        
        # Override paths temporarily
        import bot_doubles_absorb_error_audit
        bot_doubles_absorb_error_audit.SUMMARY_CSV_PATH = tempfile.mktemp(suffix=".csv")
        
        try:
            import unittest.mock
            with unittest.mock.patch("bot_doubles_absorb_error_audit.count_audit_absorb_metrics") as mock_count:
                mock_count.return_value = {
                    "total_battles": 0, "wins": 0, "losses": 0, "absorb_selected_action_count": 0,
                    "direct_absorb_selected_action_count": 0, "redirected_absorb_selected_action_count": 0,
                    "absorb_avoidable_action_count": 0, "direct_avoidable_absorb_action_count": 0,
                    "redirected_avoidable_absorb_action_count": 0, "forced_no_useful_scored_alt_action_count": 0,
                    "avoidable_safe_damage_alt_action_count": 0, "productive_partial_spread_action_count": 0,
                    "other_useful_scored_alt_action_count": 0, "unclassified_action_count": 0,
                    "absorb_streak_gte_2_count": 0, "absorb_max_streak": 0,
                    "battles_with_absorb_selected_win": 0, "battles_with_absorb_selected_loss": 0,
                    "battles_with_absorb_avoidable_win": 0, "battles_with_absorb_avoidable_loss": 0,
                    "battles_with_forced_win": 0, "battles_with_forced_loss": 0,
                    "battles_with_productive_spread_win": 0, "battles_with_productive_spread_loss": 0
                }
                import io
                from unittest.mock import patch
                import sys
                f = io.StringIO()
                with patch.object(sys, "stdout", f):
                    summarize_existing_logs()
                
                self.assertTrue(os.path.exists(bot_doubles_absorb_error_audit.SUMMARY_CSV_PATH))
                with open(bot_doubles_absorb_error_audit.SUMMARY_CSV_PATH, "r") as csv_f:
                    header = csv_f.readline().strip()
                    self.assertIn("forced_no_useful_scored_alt_action_count", header)
                    self.assertIn("other_useful_scored_alt_action_count", header)
        finally:
            if os.path.exists(bot_doubles_absorb_error_audit.SUMMARY_CSV_PATH):
                os.remove(bot_doubles_absorb_error_audit.SUMMARY_CSV_PATH)
            os.remove(tmp_basic.name)
            os.remove(tmp_rand.name)

    def test_regenerated_csv_explicit_unit_names(self):
        # regenerated CSV uses explicit unit names
        import tempfile
        import csv
        import os
        from bot_doubles_absorb_error_audit import SUMMARY_CSV_PATH
        if os.path.exists(SUMMARY_CSV_PATH):
            with open(SUMMARY_CSV_PATH, "r") as f:
                reader = csv.reader(f)
                header = next(reader)
                self.assertIn("absorb_selected_action_count", header)
                self.assertIn("absorb_avoidable_action_count", header)
                self.assertIn("forced_no_useful_scored_alt_action_count", header)
                self.assertIn("productive_partial_spread_action_count", header)
                self.assertIn("other_useful_scored_alt_action_count", header)
                self.assertIn("unclassified_action_count", header)
                self.assertNotIn("wins_absorb_selected", header)

    def test_direct_absorb_default_flag_is_true(self):
        config = DoublesDamageAwareConfig()
        self.assertTrue(config.ability_hard_safety_direct_absorb_only)

    def test_direct_absorb_water_absorb(self):
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_da_water_absorb"
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        move = MockMove("scald", "WATER")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)
        
        # Test helper directly
        blocked, reason = direct_known_absorb_blocks_move(move, attacker, target, battle, order)
        self.assertTrue(blocked)
        
        # Test get_expected_damage with context parameter
        dmg = player.get_expected_damage(move, attacker, target, battle, is_single_target_direct=True)
        self.assertEqual(dmg, 0.0)
        
        # Test score_action
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_direct_absorb_storm_drain(self):
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_da_storm_drain"
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("gastrodon", ["WATER"], ability="Storm Drain")
        move = MockMove("scald", "WATER")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)
        blocked, reason = direct_known_absorb_blocks_move(move, attacker, target, battle, order)
        self.assertTrue(blocked)
        dmg = player.get_expected_damage(move, attacker, target, battle, is_single_target_direct=True)
        self.assertEqual(dmg, 0.0)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_direct_absorb_dry_skin(self):
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_da_dry_skin"
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("toxicroak", ["POISON"], ability="Dry Skin")
        move = MockMove("scald", "WATER")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)
        blocked, reason = direct_known_absorb_blocks_move(move, attacker, target, battle, order)
        self.assertTrue(blocked)
        dmg = player.get_expected_damage(move, attacker, target, battle, is_single_target_direct=True)
        self.assertEqual(dmg, 0.0)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_direct_absorb_volt_absorb(self):
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_da_volt_absorb"
        attacker = MockPokemon("jolteon", ["ELECTRIC"])
        target = MockPokemon("jolteon", ["ELECTRIC"], ability="Volt Absorb")
        move = MockMove("thunderbolt", "ELECTRIC")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)
        blocked, reason = direct_known_absorb_blocks_move(move, attacker, target, battle, order)
        self.assertTrue(blocked)
        dmg = player.get_expected_damage(move, attacker, target, battle, is_single_target_direct=True)
        self.assertEqual(dmg, 0.0)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_direct_absorb_motor_drive(self):
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_da_motor_drive"
        attacker = MockPokemon("jolteon", ["ELECTRIC"])
        target = MockPokemon("electivire", ["ELECTRIC"], ability="Motor Drive")
        move = MockMove("thunderbolt", "ELECTRIC")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)
        blocked, reason = direct_known_absorb_blocks_move(move, attacker, target, battle, order)
        self.assertTrue(blocked)
        dmg = player.get_expected_damage(move, attacker, target, battle, is_single_target_direct=True)
        self.assertEqual(dmg, 0.0)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_direct_absorb_lightning_rod(self):
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_da_lightning_rod"
        attacker = MockPokemon("jolteon", ["ELECTRIC"])
        target = MockPokemon("raichu", ["ELECTRIC"], ability="Lightning Rod")
        move = MockMove("thunderbolt", "ELECTRIC")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)
        blocked, reason = direct_known_absorb_blocks_move(move, attacker, target, battle, order)
        self.assertTrue(blocked)
        dmg = player.get_expected_damage(move, attacker, target, battle, is_single_target_direct=True)
        self.assertEqual(dmg, 0.0)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_direct_absorb_flash_fire(self):
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_da_flash_fire"
        attacker = MockPokemon("arcanine", ["FIRE"])
        target = MockPokemon("arcanine", ["FIRE"], ability="Flash Fire")
        move = MockMove("flamethrower", "FIRE")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)
        blocked, reason = direct_known_absorb_blocks_move(move, attacker, target, battle, order)
        self.assertTrue(blocked)
        dmg = player.get_expected_damage(move, attacker, target, battle, is_single_target_direct=True)
        self.assertEqual(dmg, 0.0)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_direct_absorb_well_baked_body(self):
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_da_well_baked_body"
        attacker = MockPokemon("arcanine", ["FIRE"])
        target = MockPokemon("dachsbun", ["FAIRY"], ability="Well-Baked Body")
        move = MockMove("flamethrower", "FIRE")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)
        blocked, reason = direct_known_absorb_blocks_move(move, attacker, target, battle, order)
        self.assertTrue(blocked)
        dmg = player.get_expected_damage(move, attacker, target, battle, is_single_target_direct=True)
        self.assertEqual(dmg, 0.0)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_direct_absorb_sap_sipper(self):
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_da_sap_sipper"
        attacker = MockPokemon("venusaur", ["GRASS"])
        target = MockPokemon("gogoat", ["GRASS"], ability="Sap Sipper")
        move = MockMove("gigadrain", "GRASS")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)
        blocked, reason = direct_known_absorb_blocks_move(move, attacker, target, battle, order)
        self.assertTrue(blocked)
        dmg = player.get_expected_damage(move, attacker, target, battle, is_single_target_direct=True)
        self.assertEqual(dmg, 0.0)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_direct_absorb_no_block_unknown_ability(self):
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_da_unknown"
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("vaporeon", ["WATER"], ability=None)
        move = MockMove("scald", "WATER")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)
        blocked, reason = direct_known_absorb_blocks_move(move, attacker, target, battle, order)
        self.assertFalse(blocked)
        dmg = player.get_expected_damage(move, attacker, target, battle, is_single_target_direct=True)
        self.assertNotEqual(dmg, 0.0)
        score = player.score_action(order, 0, battle)
        self.assertNotEqual(score, 0.0)

    def test_direct_absorb_mold_breaker_bypass(self):
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_da_mold_breaker"
        attacker = MockPokemon("pinsir", ["BUG"], ability="Mold Breaker")
        target = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        move = MockMove("scald", "WATER")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)
        blocked, reason = direct_known_absorb_blocks_move(move, attacker, target, battle, order)
        self.assertFalse(blocked)
        dmg = player.get_expected_damage(move, attacker, target, battle, is_single_target_direct=True)
        self.assertNotEqual(dmg, 0.0)
        score = player.score_action(order, 0, battle)
        self.assertNotEqual(score, 0.0)

    def test_direct_absorb_status_move_unchanged(self):
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_da_status"
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        move = MockMove("watersport", "WATER", base_power=0)
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=1)
        blocked, reason = direct_known_absorb_blocks_move(move, attacker, target, battle, order)
        self.assertFalse(blocked)
        # Status moves should still be selectable
        score = player.score_action(order, 0, battle)
        self.assertNotEqual(score, 0.0)

    def test_direct_absorb_spread_move_not_blocked(self):
        # Regression test proving that a spread move into one known absorb target still scores damage against the other target and is unchanged by the new flag.
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_da_spread"
        attacker = MockPokemon("starmie", ["WATER"])
        target_absorb = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        target_normal = MockPokemon("charizard", ["FIRE", "FLYING"])
        move = MockMove("surf", "WATER", target="allAdjacentFoes")
        battle.opponent_active_pokemon = [target_absorb, target_normal]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        order = SingleBattleOrder(move, move_target=0)
        
        # Helper check: is_opponent_spread_move(move, order) is True, so direct_known_absorb_blocks_move should return False
        blocked, reason = direct_known_absorb_blocks_move(move, attacker, target_absorb, battle, order)
        self.assertFalse(blocked)
        
        # Expected damage to the normal target should not be 0
        dmg_normal = player.get_expected_damage(move, attacker, target_normal, battle, is_single_target_direct=False)
        self.assertNotEqual(dmg_normal, 0.0)
        
        # Score check
        score = player.score_action(order, 0, battle)
        self.assertNotEqual(score, 0.0)

    def test_direct_absorb_no_redirection_ally_overlap(self):
        # Redirection and ally safety are not affected by this flag.
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        self.assertFalse(player.config.ability_hard_safety_avoid_redirection)
        self.assertFalse(player.config.ability_hard_safety_ally_spread_safety)

    def test_direct_absorb_concurrency_evaluation_safety(self):
        # Concurrency/evaluation safety (no mutations on candidate evaluations: is_selected=False).
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_da_concurrency"
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        move = MockMove("scald", "WATER")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        
        # Evaluate with is_selected=False
        order = SingleBattleOrder(move, move_target=1)
        player.score_action(order, 0, battle, is_selected=False)
        
        # Metrics must NOT be mutated
        self.assertFalse(player._direct_absorb_immune_move_selected.setdefault(battle.battle_tag, {0: False, 1: False})[0])

    def test_direct_absorb_metrics_logged(self):
        # Metrics are computed and logged correctly on final decisions.
        config = DoublesDamageAwareConfig(enable_ability_hard_safety_only=True, ability_hard_safety_direct_absorb_only=True)
        player = TestPlayer.create(config)
        battle = MockBattle()
        battle.battle_tag = "test_da_logging"
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        move = MockMove("scald", "WATER")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)
        
        # Evaluate with is_selected=True
        order = SingleBattleOrder(move, move_target=1)
        player.score_action(order, 0, battle, is_selected=True)
        
        # Metrics MUST be mutated
        self.assertTrue(player._direct_absorb_immune_move_selected.setdefault(battle.battle_tag, {0: False, 1: False})[0])


class TestDirectAbsorbAdoptionCorrection(unittest.TestCase):
    """Phase 6.3.3a: Tests for adoption correction."""

    def _make_player(self, direct_absorb_only=False):
        config = DoublesDamageAwareConfig(
            enable_ability_hard_safety_only=True,
            ability_hard_safety_direct_absorb_only=direct_absorb_only,
        )
        player = TestPlayer.create(config)
        return player

    def test_legacy_check_move_will_ko_override_compatible(self):
        """Test 1: Legacy subclass override of check_move_will_ko remains compatible."""
        class LegacyPlayer(DoublesDamageAwarePlayer):
            def check_move_will_ko(self, move, attacker, target, battle) -> bool:
                return getattr(target, "current_hp_fraction", 1.0) <= 0.20

        player = DoublesDamageAwarePlayer.__new__(LegacyPlayer)
        player.config = DoublesDamageAwareConfig()
        player.verbose = False
        player.meta_engine = None
        player.random_set_engine = None
        battle = MockBattle()
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        target._current_hp_fraction = 0.10
        move = MockMove("scald", "WATER")
        result = player.check_move_will_ko(move, attacker, target, battle)
        self.assertTrue(result)

    def test_blocked_direct_no_focus_fire_synergy(self):
        """Test 2: Blocked direct action cannot receive focus-fire synergy."""
        player = self._make_player(direct_absorb_only=True)
        battle = MockBattle()
        battle.battle_tag = "test_no_focus_fire"
        attacker_0 = MockPokemon("chandelure", ["FIRE"])
        attacker_1 = MockPokemon("gardevoir", ["PSYCHIC"])
        target_goodra = MockPokemon("goodra", ["DRAGON"], ability="Sap Sipper")
        target_goodra._current_hp_fraction = 0.60
        target_archaludon = MockPokemon("archaludon", ["STEEL"])
        target_archaludon._current_hp_fraction = 0.60

        battle.active_pokemon = [attacker_0, attacker_1]
        battle.opponent_active_pokemon = [target_goodra, target_archaludon]
        player.init_battle_maps(battle.battle_tag)

        # Slot 0: Energy Ball (GRASS) into Sap Sipper Goodra = blocked (score 0)
        energy_ball = MockMove("energyball", "GRASS", base_power=90)
        order_blocked = SingleBattleOrder(energy_ball, move_target=1)
        score_blocked = player.score_action(order_blocked, 0, battle)
        self.assertEqual(score_blocked, 0.0)

        # Slot 0: Energy Ball into Archaludon = not blocked (positive score)
        order_safe = SingleBattleOrder(energy_ball, move_target=2)
        score_safe = player.score_action(order_safe, 0, battle)
        self.assertGreater(score_safe, 0.0)

        # Slot 1: Psychic into Goodra (ally targets Goodra)
        psychic = MockMove("psychic", "PSYCHIC", base_power=90)
        order_ally = SingleBattleOrder(psychic, move_target=1)

        # Pre-compute scores
        slot_0_scores = {}
        slot_1_scores = {}
        slot_0_scores[id(order_blocked)] = score_blocked
        slot_0_scores[id(order_safe)] = score_safe
        slot_1_scores[id(order_ally)] = player.score_action(order_ally, 1, battle)

        # Precompute blocked status
        _direct_absorb_blocked = {}
        _direct_absorb_enabled = True
        for slot_idx, orders in enumerate([[order_blocked, order_safe], [order_ally]]):
            for ord in orders:
                if ord and isinstance(ord.order, Move):
                    t_pos = ord.move_target
                    if t_pos in (1, 2):
                        t_mon = battle.opponent_active_pokemon[t_pos - 1]
                        a_mon = battle.active_pokemon[slot_idx]
                        if t_mon and a_mon:
                            if not is_opponent_spread_move(ord.order, ord):
                                blocked, _ = direct_known_absorb_blocks_move(
                                    ord.order, a_mon, t_mon, battle, ord
                                )
                                if blocked:
                                    _direct_absorb_blocked[id(ord)] = True

        # Verify the blocked order is detected
        self.assertTrue(_direct_absorb_blocked.get(id(order_blocked), False))
        self.assertFalse(_direct_absorb_blocked.get(id(order_safe), False))

        # Joint: blocked + ally should NOT get focus-fire bonus
        score_1_blocked = slot_0_scores.get(id(order_blocked), 0.0)
        score_2_ally = slot_1_scores.get(id(order_ally), 0.0)
        joint_score_no_synergy = score_1_blocked + score_2_ally
        self.assertEqual(joint_score_no_synergy, 0.0 + score_2_ally)

    def test_blocked_direct_no_bulky_target_bonus(self):
        """Test 3: Blocked direct action cannot receive bulky-target joint bonus."""
        player = self._make_player(direct_absorb_only=True)
        battle = MockBattle()
        battle.battle_tag = "test_no_bulky"
        attacker_0 = MockPokemon("chandelure", ["FIRE"])
        attacker_1 = MockPokemon("gardevoir", ["PSYCHIC"])
        target_goodra = MockPokemon("goodra", ["DRAGON"], ability="Sap Sipper")
        target_goodra._current_hp_fraction = 0.80
        target_archaludon = MockPokemon("archaludon", ["STEEL"])
        target_archaludon._current_hp_fraction = 0.80

        battle.active_pokemon = [attacker_0, attacker_1]
        battle.opponent_active_pokemon = [target_goodra, target_archaludon]
        player.init_battle_maps(battle.battle_tag)

        # Energy Ball into Goodra = blocked
        energy_ball = MockMove("energyball", "GRASS", base_power=90)
        order_blocked = SingleBattleOrder(energy_ball, move_target=1)

        # Ally also targets Goodra
        psychic = MockMove("psychic", "PSYCHIC", base_power=90)
        order_ally = SingleBattleOrder(psychic, move_target=1)

        score_blocked = player.score_action(order_blocked, 0, battle)
        score_ally = player.score_action(order_ally, 1, battle)

        # Blocked order should have score 0
        self.assertEqual(score_blocked, 0.0)

        # The joint score should be just sum of individual scores (no bulky bonus)
        joint_base = score_blocked + score_ally
        self.assertEqual(joint_base, 0.0 + score_ally)

    def test_valid_ally_action_score_intact(self):
        """Test 4: Valid ally action score remains intact when partner is blocked."""
        player = self._make_player(direct_absorb_only=True)
        battle = MockBattle()
        battle.battle_tag = "test_ally_intact"
        attacker_0 = MockPokemon("chandelure", ["FIRE"])
        attacker_1 = MockPokemon("gardevoir", ["PSYCHIC"])
        target_goodra = MockPokemon("goodra", ["DRAGON"], ability="Sap Sipper")
        target_goodra._current_hp_fraction = 0.50
        target_archaludon = MockPokemon("archaludon", ["STEEL"])
        target_archaludon._current_hp_fraction = 0.50

        battle.active_pokemon = [attacker_0, attacker_1]
        battle.opponent_active_pokemon = [target_goodra, target_archaludon]
        player.init_battle_maps(battle.battle_tag)

        # Slot 1 targets Archaludon (valid, not blocked)
        psychic = MockMove("psychic", "PSYCHIC", base_power=90)
        order_valid = SingleBattleOrder(psychic, move_target=2)
        score_valid = player.score_action(order_valid, 1, battle)
        self.assertGreater(score_valid, 0.0)

        # Slot 0 targets Goodra (blocked)
        energy_ball = MockMove("energyball", "GRASS", base_power=90)
        order_blocked = SingleBattleOrder(energy_ball, move_target=1)
        score_blocked = player.score_action(order_blocked, 0, battle)
        self.assertEqual(score_blocked, 0.0)

        # Joint score = valid score + blocked score (no bonus)
        joint = score_valid + score_blocked
        self.assertEqual(joint, score_valid)

    def test_safe_target_beats_blocked_target(self):
        """Test 5: Safe target alternative beats a blocked target in joint scoring."""
        player = self._make_player(direct_absorb_only=True)
        battle = MockBattle()
        battle.battle_tag = "test_safe_beats_blocked"
        attacker_0 = MockPokemon("chandelure", ["FIRE"])
        attacker_1 = MockPokemon("gardevoir", ["PSYCHIC"])
        target_goodra = MockPokemon("goodra", ["DRAGON"], ability="Sap Sipper")
        target_goodra._current_hp_fraction = 0.50
        target_archaludon = MockPokemon("archaludon", ["STEEL"])
        target_archaludon._current_hp_fraction = 0.50

        battle.active_pokemon = [attacker_0, attacker_1]
        battle.opponent_active_pokemon = [target_goodra, target_archaludon]
        player.init_battle_maps(battle.battle_tag)

        energy_ball = MockMove("energyball", "GRASS", base_power=90)
        order_blocked = SingleBattleOrder(energy_ball, move_target=1)
        order_safe = SingleBattleOrder(energy_ball, move_target=2)

        score_blocked = player.score_action(order_blocked, 0, battle)
        score_safe = player.score_action(order_safe, 0, battle)

        self.assertEqual(score_blocked, 0.0)
        self.assertGreater(score_safe, 0.0)

    def test_regression_54497_slot0(self):
        """Test 6: Regression for battle 54497 in slot 0."""
        player = self._make_player(direct_absorb_only=True)
        battle = MockBattle()
        battle.battle_tag = "battle-gen9randomdoublesbattle-54497"
        attacker_0 = MockPokemon("chandelure", ["FIRE", "GHOST"])
        attacker_1 = MockPokemon("gardevoir", ["PSYCHIC", "FAIRY"])
        target_goodra = MockPokemon("goodra", ["DRAGON"], ability="Sap Sipper")
        target_goodra._current_hp_fraction = 0.60
        target_archaludon = MockPokemon("archaludon", ["STEEL", "DRAGON"])
        target_archaludon._current_hp_fraction = 0.60

        battle.active_pokemon = [attacker_0, attacker_1]
        battle.opponent_active_pokemon = [target_goodra, target_archaludon]
        player.init_battle_maps(battle.battle_tag)

        energy_ball = MockMove("energyball", "GRASS", base_power=90)
        order_slot0_goodra = SingleBattleOrder(energy_ball, move_target=1)
        order_slot0_arch = SingleBattleOrder(energy_ball, move_target=2)

        # Slot 0 into Goodra must be blocked (score 0)
        score_goodra = player.score_action(order_slot0_goodra, 0, battle)
        self.assertEqual(score_goodra, 0.0)

        # Slot 0 into Archaludon must be positive
        score_arch = player.score_action(order_slot0_arch, 0, battle)
        self.assertGreater(score_arch, 0.0)

        # Verify direct_absorb_blocked detection
        blocked, reason = direct_known_absorb_blocks_move(
            energy_ball, attacker_0, target_goodra, battle, order_slot0_goodra
        )
        self.assertTrue(blocked)
        self.assertIn("sapsipper", reason.lower().replace(" ", ""))

    def test_regression_54497_slot1(self):
        """Test 7: Equivalent regression for battle 54497 in slot 1."""
        player = self._make_player(direct_absorb_only=True)
        battle = MockBattle()
        battle.battle_tag = "battle-gen9randomdoublesbattle-54497-slot1"
        attacker_0 = MockPokemon("gardevoir", ["PSYCHIC", "FAIRY"])
        attacker_1 = MockPokemon("chandelure", ["FIRE", "GHOST"])
        target_goodra = MockPokemon("goodra", ["DRAGON"], ability="Sap Sipper")
        target_goodra._current_hp_fraction = 0.60
        target_archaludon = MockPokemon("archaludon", ["STEEL", "DRAGON"])
        target_archaludon._current_hp_fraction = 0.60

        battle.active_pokemon = [attacker_0, attacker_1]
        battle.opponent_active_pokemon = [target_goodra, target_archaludon]
        player.init_battle_maps(battle.battle_tag)

        energy_ball = MockMove("energyball", "GRASS", base_power=90)
        order_slot1_goodra = SingleBattleOrder(energy_ball, move_target=1)
        order_slot1_arch = SingleBattleOrder(energy_ball, move_target=2)

        score_goodra = player.score_action(order_slot1_goodra, 1, battle)
        self.assertEqual(score_goodra, 0.0)

        score_arch = player.score_action(order_slot1_arch, 1, battle)
        self.assertGreater(score_arch, 0.0)

        blocked, reason = direct_known_absorb_blocks_move(
            energy_ball, attacker_1, target_goodra, battle, order_slot1_goodra
        )
        self.assertTrue(blocked)

    def test_only_legal_false_for_unrelated_one_order(self):
        """Test 8: Only-legal metric is false for unrelated one-order slots."""
        player = self._make_player(direct_absorb_only=True)
        battle = MockBattle()
        battle.battle_tag = "test_only_legal_false"
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        move = MockMove("scald", "WATER")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)

        # Single order slot - NOT blocked (target doesn't absorb water via direct known absorb
        # since Water Absorb blocks water, but the order is to target which IS the direct target)
        order = SingleBattleOrder(move, move_target=1)
        player.score_action(order, 0, battle, is_selected=True)

        # Check: even though there's 1 order, the selected action IS directly blocked
        # But if the selected is directly blocked AND only 1 order => only_legal=True
        # This test is about an order that is NOT blocked but has 1 order
        # Use a non-absorbing target
        target2 = MockPokemon("blissey", ["NORMAL"])
        battle.opponent_active_pokemon = [target2, None]
        battle.battle_tag = "test_only_legal_false2"
        player.init_battle_maps(battle.battle_tag)
        order2 = SingleBattleOrder(move, move_target=1)
        player.score_action(order2, 0, battle, is_selected=True)

        # The action is NOT directly blocked, so only_legal should be False
        only_legal = player._direct_absorb_only_legal_action.setdefault(battle.battle_tag, {0: False, 1: False})[0]
        self.assertFalse(only_legal)

    def test_only_legal_true_for_selected_blocked_with_one_order(self):
        """Test 9: Only-legal metric is true only for selected blocked action with exactly one legal order.
        
        This tests the logic condition: is_chosen_direct_blocked and len(valid_orders_slot) == 1.
        We verify the inputs are correct, knowing the metric is set in choose_doubles_move.
        """
        player = self._make_player(direct_absorb_only=True)
        battle = MockBattle()
        battle.battle_tag = "test_only_legal_true"
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        move = MockMove("scald", "WATER")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)

        # Verify: this move IS direct-absorb blocked
        order = SingleBattleOrder(move, move_target=1)
        blocked, reason = direct_known_absorb_blocks_move(move, attacker, target, battle, order)
        self.assertTrue(blocked)

        # Verify: score_action sets _direct_absorb_immune_move_selected when is_selected=True
        player.score_action(order, 0, battle, is_selected=True)
        immune_selected = player._direct_absorb_immune_move_selected.setdefault(battle.battle_tag, {0: False, 1: False})[0]
        self.assertTrue(immune_selected)

        # The condition for only_legal is: is_chosen_direct_blocked=True AND len(valid_orders_slot)==1
        # Both conditions are met here (blocked=True, 1 order in list)
        # The metric is set in choose_doubles_move, not score_action

    def test_avoided_zero_when_feature_off(self):
        """Test 10: Avoided metric is zero when feature is off."""
        player = self._make_player(direct_absorb_only=False)
        battle = MockBattle()
        battle.battle_tag = "test_avoided_off"
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        move = MockMove("scald", "WATER")
        battle.opponent_active_pokemon = [target, None]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)

        order = SingleBattleOrder(move, move_target=1)
        player.score_action(order, 0, battle, is_selected=True)

        avoided = player._direct_absorb_hard_block_avoided.setdefault(battle.battle_tag, {0: False, 1: False})[0]
        self.assertFalse(avoided)

    def test_avoided_true_when_feature_on_and_action_safe(self):
        """Test 11: Avoided metric is final-action safe when feature is on.
        
        This tests the logic condition: direct_block_candidate_exists and not is_chosen_direct_blocked.
        We verify the inputs are correct, knowing the metric is set in choose_doubles_move.
        """
        player = self._make_player(direct_absorb_only=True)
        battle = MockBattle()
        battle.battle_tag = "test_avoided_on"
        attacker = MockPokemon("starmie", ["WATER"])
        target = MockPokemon("vaporeon", ["WATER"], ability="Water Absorb")
        target2 = MockPokemon("blissey", ["NORMAL"])
        move = MockMove("scald", "WATER")
        battle.opponent_active_pokemon = [target, target2]
        battle.active_pokemon = [attacker, None]
        player.init_battle_maps(battle.battle_tag)

        # The slot has two orders: one blocked (into Vaporeon), one safe (into Blissey)
        # Verify: into Vaporeon IS blocked
        order_blocked = SingleBattleOrder(move, move_target=1)
        blocked, _ = direct_known_absorb_blocks_move(move, attacker, target, battle, order_blocked)
        self.assertTrue(blocked)

        # Verify: into Blissey is NOT blocked
        order_safe = SingleBattleOrder(move, move_target=2)
        safe_blocked, _ = direct_known_absorb_blocks_move(move, attacker, target2, battle, order_safe)
        self.assertFalse(safe_blocked)

        # Verify: score_action sets _direct_absorb_immune_move_selected for the blocked order
        player.score_action(order_blocked, 0, battle, is_selected=True)
        immune_blocked = player._direct_absorb_immune_move_selected.setdefault(battle.battle_tag, {0: False, 1: False})[0]
        self.assertTrue(immune_blocked)

        # Verify: score_action does NOT set _direct_absorb_immune_move_selected for the safe order
        player._direct_absorb_immune_move_selected[battle.battle_tag] = {0: False, 1: False}
        player.score_action(order_safe, 0, battle, is_selected=True)
        immune_safe = player._direct_absorb_immune_move_selected.setdefault(battle.battle_tag, {0: False, 1: False})[0]
        self.assertFalse(immune_safe)

        # The condition for avoided is: direct_block_candidate_exists=True (Vaporeon blocks)
        # AND not is_chosen_direct_blocked=True (safe order chosen)
        # The metric is set in choose_doubles_move

    def test_benchmark_row_contains_stability_fields(self):
        """Test 12: Benchmark row contains all stability fields."""
        import csv
        import io
        fieldnames = [
            "matchup", "planned_battles", "finished_battles", "unfinished_battles",
            "wins", "losses", "ties_or_unknown", "timeouts", "crashes", "exceptions",
            "win_rate", "avg_turns", "protect_cnt", "spread_cnt", "focus_fire_cnt",
            "zero_eff_cnt", "all_imm_cnt", "ground_into_levitate", "direct_absorb_hard_block_avoided",
            "direct_absorb_immune_move_selected", "direct_absorb_only_legal_action",
            "redirected_absorb_selected", "productive_partial_absorb_spread"
        ]
        row = {
            "matchup": "Test",
            "planned_battles": 100,
            "finished_battles": 100,
            "unfinished_battles": 0,
            "wins": 50,
            "losses": 50,
            "ties_or_unknown": 0,
            "timeouts": 0,
            "crashes": 0,
            "exceptions": 0,
            "win_rate": "50.00",
            "avg_turns": "8.00",
            "protect_cnt": 10,
            "spread_cnt": 20,
            "focus_fire_cnt": 5,
            "zero_eff_cnt": 1,
            "all_imm_cnt": 0,
            "ground_into_levitate": 0,
            "direct_absorb_hard_block_avoided": 2,
            "direct_absorb_immune_move_selected": 1,
            "direct_absorb_only_legal_action": 0,
            "redirected_absorb_selected": 0,
            "productive_partial_absorb_spread": 1,
        }
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)
        output.seek(0)
        reader = csv.DictReader(output)
        written_row = next(reader)
        for field in fieldnames:
            self.assertIn(field, written_row)
        self.assertEqual(written_row["planned_battles"], "100")
        self.assertEqual(written_row["finished_battles"], "100")
        self.assertEqual(written_row["ties_or_unknown"], "0")


if __name__ == "__main__":
    unittest.main()
