import poke_env_test_cleanup  # noqa: F401 — unregister deadlock-prone atexit
import unittest
from typing import Optional, List
from bot_doubles_damage_aware import (
    DoublesDamageAwarePlayer,
    DoublesDamageAwareConfig,
    is_opponent_spread_move
)
from poke_env.player.battle_order import SingleBattleOrder
from poke_env.battle.move import Move
from poke_env.battle.pokemon import Pokemon
from poke_env.battle.pokemon_type import PokemonType
from poke_env.battle.move_category import MoveCategory

class MockMove(Move):
    def __init__(self, move_id: str, move_type: str, base_power: int = 80, category: str = "SPECIAL", target: str = "normal", priority: int = 0, accuracy: float = 1.0):
        super().__init__(move_id=move_id, gen=9)
        self._type = PokemonType[move_type.upper()] if move_type else PokemonType.NORMAL
        self._base_power = base_power
        self._category = MoveCategory[category.upper()] if category else MoveCategory.SPECIAL
        self._target = target
        self._priority = priority
        self._accuracy = accuracy

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def accuracy(self) -> float:
        return self._accuracy

class MockPokemon(Pokemon):
    def __init__(self, species: str, base_stats: dict = None, stats: dict = None, boosts: dict = None, status: str = None, item: str = None, level: int = 80):
        super().__init__(gen=9, species=species)
        self._species = species
        self._base_stats = base_stats or {"spe": 100}
        self._stats = stats or {}
        self._boosts = boosts or {}
        self._status = status
        self._item = item
        self._level = level
        self._current_hp_fraction = 1.0
        self._moves = {}

    @property
    def base_stats(self) -> dict:
        return self._base_stats

    @property
    def stats(self) -> dict:
        return self._stats

    @property
    def boosts(self) -> dict:
        return self._boosts

    @property
    def status(self) -> Optional[str]:
        return self._status

    @property
    def item(self) -> Optional[str]:
        return self._item

    @property
    def level(self) -> int:
        return self._level

    @property
    def current_hp_fraction(self) -> float:
        return self._current_hp_fraction

    @current_hp_fraction.setter
    def current_hp_fraction(self, val: float):
        self._current_hp_fraction = val

    @property
    def moves(self) -> dict:
        return self._moves

class MockBattle:
    def __init__(self, fields=None, side_conditions=None, opponent_side_conditions=None):
        self.fields = fields or {}
        self.side_conditions = side_conditions or {}
        self.opponent_side_conditions = opponent_side_conditions or {}
        self.opponent_active_pokemon = [None, None]
        self.active_pokemon = {0: None, 1: None}
        self.battle_tag = "test_battle"
        self.turn = 1
        self.available_switches = []
        self.available_moves = [[], []]
        self._replay_data = []


class TestPlayer(DoublesDamageAwarePlayer):
    def __init__(self, config=None):
        self.config = config or DoublesDamageAwareConfig()
        self.verbose = False
        self.active_turns = {}
        self.last_protect_turn = {}
        self.opponent_active_turns = {}
        self._speed_priority_threatened = {}
        self._faster_opponents = {}
        self._priority_opponents = {}
        self._speed_priority_protect_bonus_applied = {}
        self._speed_priority_attack_penalty_applied = {}
        self._speed_priority_switch_bonus_applied = {}
        self._protected_due_to_speed_priority = {}
        self._expected_to_faint_before_moving = {}
        self._order_aware_overkill_penalty_applied = {}
        self._base_scores_cache = {0: {}, 1: {}}
        self.partial_immune_spread_by_battle = {}
        self.partial_ability_immune_spread_by_battle = {}
        self.efficient_partial_spread_by_battle = {}
        self.inefficient_partial_spread_by_battle = {}
        self.immune_target_species_by_battle = {}
        self.damaged_target_species_by_battle = {}
        self.best_single_alternative_by_battle = {}
        self._current_valid_orders = [[], []]

    def check_move_will_ko(self, move, attacker, target, battle, config=None) -> bool:
        # For tests, assume move KOs if target HP is <= 0.20
        return getattr(target, "current_hp_fraction", 1.0) <= 0.20

    def get_expected_damage(self, move, active, opponent, battle=None, config=None) -> float:
        return 0.1

    def score_opponent_threat(self, opponent, battle, our_pokemon=None) -> float:
        return 0.8 if getattr(opponent, "species", "") == "dangerous" else 0.2

    def best_move_score_for_slot(self, slot_idx: int, battle) -> float:
        return 50.0

class TestDoublesSpeedPriority(unittest.TestCase):
    def setUp(self):
        self.player = TestPlayer()
        self.battle = MockBattle()

    def test_effective_speed_no_boosts(self):
        mon = MockPokemon("pikachu", base_stats={"spe": 90}, level=80)
        # Formula: (2 * 90 + 52) * 80 / 100 + 5 = 232 * 0.8 + 5 = 185.6 + 5 = 190.6
        speed = self.player.get_effective_speed(mon, self.battle)
        self.assertAlmostEqual(speed, 190.6, places=1)

    def test_effective_speed_with_boost(self):
        mon = MockPokemon("pikachu", base_stats={"spe": 90}, boosts={"spe": 1}, level=80)
        # speed = 190.6 * 1.5 = 285.9
        speed = self.player.get_effective_speed(mon, self.battle)
        self.assertAlmostEqual(speed, 285.9, places=1)

    def test_trick_room_speed_reversal(self):
        # Trick Room inactive
        self.assertFalse(self.player.is_trick_room_active(self.battle))
        
        # Trick Room active via string field
        self.battle.fields = {"TRICK_ROOM": 1}
        self.assertTrue(self.player.is_trick_room_active(self.battle))

    def test_priority_moves_outrun(self):
        normal_move = MockMove("tackle", "NORMAL", priority=0)
        prio_move = MockMove("extremespeed", "NORMAL", priority=2)
        self.assertEqual(self.player.get_move_priority(normal_move), 0)
        self.assertEqual(self.player.get_move_priority(prio_move), 2)

    def test_revealed_priority_threat_detection(self):
        opp = MockPokemon("scizor")
        opp._moves = {"bulletpunch": MockMove("bulletpunch", "STEEL", priority=1)}
        self.battle.opponent_active_pokemon[0] = opp
        
        prio_info = self.player.opponent_has_revealed_priority_move(opp, self.battle)
        self.assertTrue(prio_info["has_priority"])
        self.assertTrue(prio_info["has_guaranteed_priority"])

        # Test First Impression first turn check
        opp_fi = MockPokemon("axew")
        opp_fi._moves = {"firstimpression": MockMove("firstimpression", "BUG", priority=1)}
        
        # Turn 1: has priority
        self.battle.opponent_active_pokemon[0] = opp_fi
        prio_info_fi_1 = self.player.opponent_has_revealed_priority_move(opp_fi, self.battle)
        self.assertTrue(prio_info_fi_1["has_priority"])
        
        # Turn 2: active turns > 1, priority should be filtered out
        opp_fi_id = self.player.get_pokemon_identifier(opp_fi)
        self.player.opponent_active_turns["test_battle"] = {(0, opp_fi_id): (2, 2)}
        prio_info_fi_2 = self.player.opponent_has_revealed_priority_move(opp_fi, self.battle)
        self.assertFalse(prio_info_fi_2["has_priority"])

    def test_no_unrevealed_priority_prediction(self):
        opp = MockPokemon("dragonite")
        # No moves revealed
        opp._moves = {}
        prio_info = self.player.opponent_has_revealed_priority_move(opp, self.battle)
        self.assertFalse(prio_info["has_priority"])

    def test_slower_active_at_low_hp_threatened(self):
        self.player.config.enable_speed_priority_awareness = True
        our_active = MockPokemon("slowbro", base_stats={"spe": 30}, level=80)
        our_active.current_hp_fraction = 0.30
        
        opp = MockPokemon("aerodactyl", base_stats={"spe": 130}, level=80)
        self.battle.opponent_active_pokemon[0] = opp
        
        threat_info = self.player.estimate_speed_priority_threat(our_active, [opp], self.battle)
        self.assertTrue(threat_info["is_threatened"])
        self.assertTrue(threat_info["speed_threatened"])
        self.assertTrue(threat_info["faint_before_moving"])

    def test_slower_active_at_high_hp_not_threatened(self):
        self.player.config.enable_speed_priority_awareness = True
        our_active = MockPokemon("slowbro", base_stats={"spe": 30}, level=80)
        our_active.current_hp_fraction = 1.0 # High HP
        
        opp = MockPokemon("aerodactyl", base_stats={"spe": 130}, level=80)
        self.battle.opponent_active_pokemon[0] = opp
        
        threat_info = self.player.estimate_speed_priority_threat(our_active, [opp], self.battle)
        self.assertFalse(threat_info["is_threatened"])

    def test_protect_bonus_gated_by_availability(self):
        self.player.config.enable_speed_priority_awareness = True
        self.player.config.speed_priority_use_scaled_penalty = False
        # Phase BEHAVIOR-16: disable the Protect floor for
        # this test. The test is about the BEHAVIOR-11
        # bonus path (which IS gated by Protect
        # availability), not the floor (which applies
        # to any Protect-like action regardless of legal
        # orders).
        self.player.config.speed_priority_expected_faint_protect_score_floor = 0.0
        # Phase BEHAVIOR-11: disable the expected-faint
        # Protect bonus for this test. The test is
        # about the is_threatened bonus path, not the
        # expected-faint bonus.
        self.player.config.speed_priority_protect_bonus_under_expected_faint = 0.0
        our_active = MockPokemon("slowbro", base_stats={"spe": 30}, level=80)
        our_active.current_hp_fraction = 0.25
        
        opp = MockPokemon("aerodactyl", base_stats={"spe": 130}, level=80)
        self.battle.opponent_active_pokemon[0] = opp
        self.battle.active_pokemon[0] = our_active
        
        # Test case: Protect is NOT in legal moves
        self.player._current_valid_orders[0] = []
        score = self.player.score_action(SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0), 0, self.battle)
        # Since Protect is not in legal orders, the bonus should not apply to Protect order
        self.assertEqual(score, 0.0)

        # Test case: Protect is available
        self.player._current_valid_orders[0] = [SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0)]
        self.player.last_protect_turn["test_battle"] = {}
        score_with_protect = self.player.score_action(SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0), 0, self.battle)
        # Protect score = base_protect (180) + speed_priority_protect_bonus (60) = 240
        self.assertEqual(score_with_protect, 240.0)

    def test_attack_penalty_applied(self):
        self.player.config.enable_speed_priority_awareness = True
        self.player.config.speed_priority_protect_only = False
        
        our_active = MockPokemon("slowbro", base_stats={"spe": 30}, level=80)
        our_active.current_hp_fraction = 0.25
        
        opp = MockPokemon("aerodactyl", base_stats={"spe": 130}, level=80)
        self.battle.opponent_active_pokemon[0] = opp
        self.battle.active_pokemon[0] = our_active
        
        # Make Protect and Switch available so bypass is False
        self.player._current_valid_orders[0] = [
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
            SingleBattleOrder(MockMove("watergun", "WATER", base_power=40), move_target=1)
        ]
        self.battle.available_switches = [MockPokemon("scizor")]
        
        # Base raw damage score is low for watergun
        # We expect a penalty of 45.0
        score = self.player.score_action(SingleBattleOrder(MockMove("watergun", "WATER", base_power=40), move_target=1), 0, self.battle)
        # Penalty applied: score should drop to 0.0 or very low
        self.assertTrue(score < 100.0)


    def test_attack_penalty_skipped_on_ko_and_spread(self):
        self.player.config.enable_speed_priority_awareness = True
        self.player.config.speed_priority_protect_only = False
        
        our_active = MockPokemon("slowbro", base_stats={"spe": 30}, level=80)
        our_active.current_hp_fraction = 0.25
        
        opp = MockPokemon("aerodactyl", base_stats={"spe": 130}, level=80)
        opp.current_hp_fraction = 0.10 # Target is in KO range
        self.battle.opponent_active_pokemon[0] = opp
        self.battle.active_pokemon[0] = our_active
        
        self.player._current_valid_orders[0] = [
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
            SingleBattleOrder(MockMove("surf", "WATER"), move_target=1)
        ]
        self.battle.available_switches = [MockPokemon("scizor")]
        
        # KO move bypasses penalty
        score = self.player.score_action(SingleBattleOrder(MockMove("surf", "WATER"), move_target=1), 0, self.battle)
        # Score should include KO bonus (+350) and no penalty applied
        self.assertTrue(score > 350.0)

    def test_order_aware_overkill_detected(self):
        self.player.config.enable_order_aware_overkill = True
        
        faster_mon = MockPokemon("aerodactyl", base_stats={"spe": 130}, level=80)
        slower_mon = MockPokemon("slowbro", base_stats={"spe": 30}, level=80)
        
        self.battle.active_pokemon[0] = faster_mon
        self.battle.active_pokemon[1] = slower_mon
        
        target = MockPokemon("gengar")
        target.current_hp_fraction = 0.15 # Low HP, faster expected to KO
        self.battle.opponent_active_pokemon[0] = target
        
        order_0 = SingleBattleOrder(MockMove("surf", "WATER"), move_target=1)
        order_1 = SingleBattleOrder(MockMove("psychic", "PSYCHIC"), move_target=1)
        
        overkill = self.player.selected_target_will_be_koed_before_second_action(order_0, order_1, self.battle)
        self.assertTrue(overkill)

    def test_order_aware_overkill_skipped(self):
        self.player.config.enable_order_aware_overkill = True
        
        faster_mon = MockPokemon("aerodactyl", base_stats={"spe": 130}, level=80)
        slower_mon = MockPokemon("slowbro", base_stats={"spe": 30}, level=80)
        
        self.battle.active_pokemon[0] = faster_mon
        self.battle.active_pokemon[1] = slower_mon
        
        target = MockPokemon("gengar")
        target.current_hp_fraction = 1.0 # High HP, faster cannot KO
        self.battle.opponent_active_pokemon[0] = target
        
        order_0 = SingleBattleOrder(MockMove("surf", "WATER"), move_target=1)
        order_1 = SingleBattleOrder(MockMove("psychic", "PSYCHIC"), move_target=1)
        
        overkill = self.player.selected_target_will_be_koed_before_second_action(order_0, order_1, self.battle)
        self.assertFalse(overkill)

if __name__ == "__main__":
    unittest.main()
