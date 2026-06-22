import poke_env_test_cleanup  # noqa: F401 — unregister deadlock-prone atexit
import unittest
from typing import Optional, List

from bot_doubles_damage_aware import (
    is_type_immune,
    get_self_stat_drop_penalty,
    DoublesDamageAwarePlayer,
    DoublesDamageAwareConfig,
    is_opponent_spread_move,
    get_spread_target_effectiveness
)
from poke_env.player.battle_order import SingleBattleOrder
from poke_env.battle.move import Move
from poke_env.battle.pokemon import Pokemon
from poke_env.battle.pokemon_type import PokemonType
from poke_env.battle.move_category import MoveCategory

# Subclassing poke-env classes to allow customizing for test environment
class MockMove(Move):
    def __init__(self, move_id: str, move_type: str, base_power: int = 80, category: str = "SPECIAL", target: str = "normal"):
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

class MockBattle:
    def __init__(self, fields=None):
        self.fields = fields or []
        self.opponent_active_pokemon = []
        self.active_pokemon = []
        self.battle_tag = "test_battle"
        self.turn = 1
        self.available_moves = [[], []]
        self.force_switch = [False, False]

    @property
    def valid_orders(self):
        from poke_env.player.battle_order import SingleBattleOrder
        orders = [[], []]
        for slot in (0, 1):
            if slot < len(self.available_moves):
                for move in self.available_moves[slot]:
                    target = 1
                    target_str = getattr(move, "target", "")
                    if target_str in ("allAdjacent", "allAdjacentFoes", "all"):
                        target = 0
                    orders[slot].append(SingleBattleOrder(move, move_target=target))
        return orders

class TestPlayer(DoublesDamageAwarePlayer):
    def __init__(self, config=None):
        self.config = config or DoublesDamageAwareConfig()
        self.verbose = False
        self.ability_blocks_avoided_by_battle = {}
        self.ability_absorbs_avoided_by_battle = {}
        self.ability_redirects_avoided_by_battle = {}
        self.ability_multipliers_applied_by_battle = {}
        
        # Phase 6.1.2 tracking dictionaries
        self.partial_immune_spread_by_battle = {}
        self.partial_ability_immune_spread_by_battle = {}
        self.efficient_partial_spread_by_battle = {}
        self.inefficient_partial_spread_by_battle = {}
        self.immune_target_species_by_battle = {}
        self.damaged_target_species_by_battle = {}
        self.best_single_alternative_by_battle = {}

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


class TestDoublesMechanicsScoring(unittest.TestCase):
    
    def test_normal_vs_ghost_immune(self):
        move = MockMove("slash", "NORMAL")
        target = MockPokemon("gengar", ["GHOST"])
        immune, reason = is_type_immune(move, None, target)
        self.assertTrue(immune)
        self.assertIn("NORMAL vs GHOST", reason or "")

    def test_fighting_vs_ghost_immune(self):
        move = MockMove("closecombat", "FIGHTING")
        target = MockPokemon("gengar", ["GHOST"])
        immune, reason = is_type_immune(move, None, target)
        self.assertTrue(immune)
        self.assertIn("FIGHTING vs GHOST", reason or "")

    def test_ghost_vs_normal_immune(self):
        move = MockMove("shadowball", "GHOST")
        target = MockPokemon("rattata", ["NORMAL"])
        immune, reason = is_type_immune(move, None, target)
        self.assertTrue(immune)
        self.assertIn("GHOST vs NORMAL", reason or "")

    def test_dragon_vs_fairy_immune(self):
        move = MockMove("dracometeor", "DRAGON")
        target = MockPokemon("clefable", ["FAIRY"])
        immune, reason = is_type_immune(move, None, target)
        self.assertTrue(immune)
        self.assertIn("DRAGON vs FAIRY", reason or "")

    def test_ground_vs_flying_immune(self):
        move = MockMove("earthquake", "GROUND")
        target = MockPokemon("pidgeot", ["FLYING"])
        immune, reason = is_type_immune(move, None, target)
        self.assertTrue(immune)
        self.assertIn("GROUND vs FLYING", reason or "")

    def test_scrappy_normal_fighting_vs_ghost_not_immune(self):
        move = MockMove("slash", "NORMAL")
        attacker = MockPokemon("kangaskhan", ["NORMAL"], ability="scrappy")
        target = MockPokemon("gengar", ["GHOST"])
        immune, reason = is_type_immune(move, attacker, target)
        self.assertFalse(immune)

        move_fighting = MockMove("brickbreak", "FIGHTING")
        immune, reason = is_type_immune(move_fighting, attacker, target)
        self.assertFalse(immune)

    def test_thousand_arrows_vs_flying_not_immune(self):
        move = MockMove("thousandarrows", "GROUND")
        target = MockPokemon("pidgeot", ["FLYING"])
        immune, reason = is_type_immune(move, None, target)
        self.assertFalse(immune)

    def test_gravity_ground_vs_flying_not_immune(self):
        move = MockMove("earthquake", "GROUND")
        target = MockPokemon("pidgeot", ["FLYING"])
        battle = MockBattle(fields=[MockField("gravity")])
        immune, reason = is_type_immune(move, None, target, battle)
        self.assertFalse(immune)

    def test_spread_all_immune(self):
        player = TestPlayer()
        # Normal spread move Hyper Voice
        move = MockMove("hypervoice", "NORMAL", target="allAdjacentFoes")
        attacker = MockPokemon("exploud", ["NORMAL"])
        target = MockPokemon("gengar", ["GHOST"])
        
        battle = MockBattle()
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, None]
        
        order = SingleBattleOrder(move, move_target=0)
        score = player.score_action_raw_damage(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_spread_partially_immune(self):
        player = TestPlayer()
        move = MockMove("hypervoice", "NORMAL", target="allAdjacentFoes")
        attacker = MockPokemon("exploud", ["NORMAL"])
        target_immune = MockPokemon("gengar", ["GHOST"])
        target_vulnerable = MockPokemon("abomasnow", ["GRASS", "ICE"])
        
        battle = MockBattle()
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target_immune, target_vulnerable]
        
        order = SingleBattleOrder(move, move_target=0)
        score_both = player.score_action_raw_damage(order, 0, battle)
        
        # Hyper Voice vs Abomasnow alone
        battle_alone = MockBattle()
        battle_alone.active_pokemon = [attacker, None]
        battle_alone.opponent_active_pokemon = [target_vulnerable, None]
        score_alone = player.score_action_raw_damage(order, 0, battle_alone)
        
        # When both are active, spread multiplier 0.75 applies to the vulnerable target, and immune target contributes 0.0
        self.assertGreater(score_both, 0.0)
        self.assertAlmostEqual(score_both, score_alone * 0.75)

    def test_draco_meteor_repeat_penalty(self):
        attacker = MockPokemon("dragonite", ["DRAGON"], boosts={"spa": -2})
        move = MockMove("dracometeor", "DRAGON")
        
        # Case A: expected_ko = False -> penalty applied
        mult, reason = get_self_stat_drop_penalty(attacker, move, expected_ko=False, has_reasonable_alternative=True)
        self.assertEqual(mult, 0.35)
        self.assertIn("dracometeor", reason)

        # Case B: expected_ko = True -> penalty skipped
        mult, reason = get_self_stat_drop_penalty(attacker, move, expected_ko=True, has_reasonable_alternative=True)
        self.assertEqual(mult, 1.0)

        # Case C: no alternative -> penalty skipped
        mult, reason = get_self_stat_drop_penalty(attacker, move, expected_ko=False, has_reasonable_alternative=False)
        self.assertEqual(mult, 1.0)

    def test_make_it_rain_repeat_penalty(self):
        attacker = MockPokemon("gholdengo", ["STEEL", "GHOST"], boosts={"spa": -2})
        move = MockMove("makeitrain", "STEEL")
        
        # Make It Rain has a lighter multiplier 0.65
        mult, reason = get_self_stat_drop_penalty(attacker, move, expected_ko=False, has_reasonable_alternative=True)
        self.assertEqual(mult, 0.65)
        self.assertIn("makeitrain", reason)

    def test_clanging_scales_vs_florges_all_immune(self):
        player = TestPlayer()
        # Clanging Scales is a Dragon-type spread move
        move = MockMove("clangingscales", "DRAGON", target="allAdjacentFoes")
        attacker = MockPokemon("kommoo", ["DRAGON", "FIGHTING"])
        target = MockPokemon("florges", ["FAIRY"])
        
        battle = MockBattle()
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target, None]
        
        order = SingleBattleOrder(move, move_target=0)
        # Verify spread detection
        self.assertTrue(is_opponent_spread_move(move, order))
        
        # Verify target effectiveness
        eff = get_spread_target_effectiveness(move, attacker, battle.opponent_active_pokemon, battle)
        self.assertTrue(eff["all_targets_immune"])
        self.assertEqual(eff["immune_targets"], 1)
        self.assertEqual(eff["damaged_targets"], 0)
        
        # Verify score is 0
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_clanging_scales_vs_florges_and_non_fairy_partial_immune(self):
        player = TestPlayer()
        move = MockMove("clangingscales", "DRAGON", target="allAdjacentFoes")
        attacker = MockPokemon("kommoo", ["DRAGON", "FIGHTING"])
        target_immune = MockPokemon("florges", ["FAIRY"])
        target_vulnerable = MockPokemon("charizard", ["FIRE", "FLYING"])
        
        battle = MockBattle()
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target_immune, target_vulnerable]
        
        order = SingleBattleOrder(move, move_target=0)
        # Verify target effectiveness
        eff = get_spread_target_effectiveness(move, attacker, battle.opponent_active_pokemon, battle)
        self.assertTrue(eff["partial_immunity"])
        self.assertEqual(eff["immune_targets"], 1)
        self.assertEqual(eff["damaged_targets"], 1)
        
        # Base raw score for single vulnerable target (Kommo-o Clanging Scales vs Charizard)
        # base score = 110 BP * 1.5 STAB * 1.0 effectiveness * 1.0 accuracy = 165
        # but with len(opps) == 2, spread intelligence applies * 0.75 multiplier = 123.75
        # under partial spread immunity penalty: 
        # score *= 0.70 (123.75 * 0.7 = 86.625)
        # score -= 35.0 (86.625 - 35 = 51.625)
        # plus 50.0 spread_bonus = 101.625
        score = player.score_action(order, 0, battle)
        self.assertAlmostEqual(score, 101.625)

    def test_clanging_scales_vs_florges_and_low_hp_non_fairy_ko_exception(self):
        player = TestPlayer()
        move = MockMove("clangingscales", "DRAGON", target="allAdjacentFoes", base_power=110)
        attacker = MockPokemon("kommoo", ["DRAGON", "FIGHTING"])
        target_immune = MockPokemon("florges", ["FAIRY"])
        target_vulnerable = MockPokemon("charizard", ["FIRE", "FLYING"])
        target_vulnerable.current_hp_fraction = 0.05 # very low HP
        
        battle = MockBattle()
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target_immune, target_vulnerable]
        
        order = SingleBattleOrder(move, move_target=0)
        # We need to make sure the single alternative moves are evaluated
        battle.available_moves = [[move], []]
        
        # When KO exception applies: only 0.90 scale penalty and no flat penalty
        # base score with spread = 123.75
        # score *= 0.90 = 111.375
        # plus 150.0 target_pos=0 KO bonus = 261.375
        # plus 50.0 spread_bonus = 311.375
        score = player.score_action(order, 0, battle)
        self.assertAlmostEqual(score, 311.375)

    def test_single_target_alternative_preference(self):
        player = TestPlayer()
        # Clanging Scales vs Florges + Charizard (partial immunity)
        move_spread = MockMove("clangingscales", "DRAGON", target="allAdjacentFoes")
        attacker = MockPokemon("kommoo", ["DRAGON", "FIGHTING"])
        target_immune = MockPokemon("florges", ["FAIRY"])
        target_vulnerable = MockPokemon("charizard", ["FIRE", "FLYING"])
        
        # Let's add Flamethrower (single-target damaging move)
        move_single = MockMove("flamethrower", "FIRE", base_power=90)
        
        battle = MockBattle()
        battle.active_pokemon = [attacker, None]
        battle.opponent_active_pokemon = [target_immune, target_vulnerable]
        
        # Both moves are available to slot 0
        battle.available_moves = [[move_spread, move_single], []]
        
        class MockPlayerWithFixedScores(TestPlayer):
            def score_action_raw_damage(self, ord_val, active_idx, bat_val):
                if ord_val.order.id == "clangingscales":
                    # Return 150.0 to simulate 200.0 * 0.75 spread multiplier
                    return 150.0
                elif ord_val.order.id == "flamethrower":
                    return 60.0
                return 0.0
                
        player_mock = MockPlayerWithFixedScores()
        order_spread = SingleBattleOrder(move_spread, move_target=0)
        # Spread score is 70.0, best single target Flamethrower is 60.0.
        # Gap: 70.0 - 60.0 = 10.0 (which is <= 30.0).
        # So preference gate applies and caps spread score at 60.0 - 1.0 = 59.0!
        # Plus 50.0 spread bonus = 109.0
        score = player_mock.score_action(order_spread, 0, battle)
        self.assertEqual(score, 109.0)

    def test_custom_spread_move_detector(self):
        # Test 1: allAdjacentFoes string target
        move_1 = MockMove("clangingscales", "DRAGON", target="allAdjacentFoes")
        self.assertTrue(is_opponent_spread_move(move_1))
        
        # Test 2: order move_target = 0
        move_2 = MockMove("earthquake", "GROUND", target="allAdjacent")
        order_2 = SingleBattleOrder(move_2, move_target=0)
        self.assertTrue(is_opponent_spread_move(move_2, order_2))
        
        # Test 3: fallback known list
        move_3 = MockMove("heatwave", "FIRE", target=None)
        self.assertTrue(is_opponent_spread_move(move_3))
        
        # Test 4: single target move
        move_4 = MockMove("flamethrower", "FIRE", target="normal")
        self.assertFalse(is_opponent_spread_move(move_4))


if __name__ == "__main__":
    unittest.main()
