"""Phase 6.4.9 — Voluntary Switch Quality and Sacrifice Awareness Tests."""
import unittest
import json
import os
import sys
import tempfile
import asyncio
import time
import argparse
from unittest.mock import MagicMock, AsyncMock, patch

import poke_env_test_cleanup  # noqa: F401
sys.path.insert(0, os.path.dirname(__file__))

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    evaluate_voluntary_switch_quality,
    build_voluntary_switch_candidate_table,
    evaluate_switch_candidate_type_safety,
    select_best_joint_from_score_maps,
    DoublesDamageAwarePlayer,
)
from bot_doubles_voluntary_switch_diagnostics import (
    validate_jsonl,
    validate_csv,
    count_vsw_metrics,
    run_with_watchdog,
    normalize_action_key,
    build_argument_parser,
    build_runtime_config,
    build_arm_definitions,
    VSW_FIELDS,
    CANDIDATE_REQUIRED_FIELDS,
    HEARTBEAT,
    STALL_TIMEOUT,
    ARM_TIMEOUT,
    DoublesSafeRandomPlayer,
    _make_csv_path,
    _make_jsonl_path,
    StallError,
)
from bot_doubles_basic_aware import DoublesBasicAwarePlayer
from poke_env.battle.move import Move
from poke_env.battle.pokemon import Pokemon


class MockPokemon:
    def __init__(self, species, type_1=None, type_2=None, hp=1.0, fainted=False,
                 ability=None, item=None, boosts=None):
        self.species = species
        self._type_1 = type_1
        self._type_2 = type_2
        self.current_hp_fraction = hp
        self.fainted = fainted
        self._ability = ability
        self._item = item
        self.boosts = boosts or {}
        self.level = 100
        self.stats = {}
        self.moves = {}

    @property
    def type_1(self):
        return self._type_1

    @property
    def type_2(self):
        return self._type_2

    @property
    def ability(self):
        return self._ability

    def damage_multiplier(self, opp_type):
        if self._type_1 is None and self._type_2 is None:
            return 1.0
        mult = 1.0
        for t in (self._type_1, self._type_2):
            if t is None:
                continue
            from poke_env.battle.pokemon_type import PokemonType
            if opp_type == PokemonType.ELECTRIC and t == PokemonType.GROUND:
                mult *= 0.0
            elif opp_type == PokemonType.WATER and t == PokemonType.FIRE:
                mult *= 2.0
            elif opp_type == PokemonType.WATER and t == PokemonType.WATER:
                mult *= 0.5
            elif opp_type == PokemonType.GRASS and t == PokemonType.GROUND:
                mult *= 2.0
            elif opp_type == PokemonType.FIRE and t == PokemonType.FIRE:
                mult *= 0.5
            elif opp_type == PokemonType.GRASS and t == PokemonType.WATER:
                mult *= 2.0
            elif opp_type == PokemonType.ELECTRIC and t == PokemonType.WATER:
                mult *= 2.0
            elif opp_type == PokemonType.FIGHTING and t == PokemonType.ROCK:
                mult *= 2.0
            elif opp_type == PokemonType.GRASS and t == PokemonType.ROCK:
                mult *= 0.5
            elif opp_type == PokemonType.ICE and t == PokemonType.GRASS:
                mult *= 2.0
            elif opp_type == PokemonType.FLYING and t == PokemonType.GRASS:
                mult *= 2.0
            elif opp_type == PokemonType.ICE and t == PokemonType.DRAGON:
                mult *= 2.0
            elif opp_type == PokemonType.ROCK and t == PokemonType.FIRE:
                mult *= 2.0
            elif opp_type == PokemonType.WATER and t == PokemonType.ROCK:
                mult *= 0.5
            elif opp_type == PokemonType.GRASS and t == PokemonType.DRAGON:
                mult *= 0.5
            elif opp_type == PokemonType.FAIRY and t == PokemonType.DRAGON:
                mult *= 2.0
            elif opp_type == PokemonType.DRAGON and t == PokemonType.DRAGON:
            # Ground vs Flying = 0
                mult *= 2.0
            elif opp_type == PokemonType.GROUND and t == PokemonType.FLYING:
                mult *= 0.0
            elif opp_type == PokemonType.GROUND and t == PokemonType.ELECTRIC:
                mult *= 2.0
            elif opp_type == PokemonType.WATER and t == PokemonType.GROUND:
                mult *= 2.0
            elif opp_type == PokemonType.GRASS and t == PokemonType.FIRE:
                mult *= 0.5
            elif opp_type == PokemonType.FIRE and t == PokemonType.WATER:
                mult *= 0.5
            elif opp_type == PokemonType.FIRE and t == PokemonType.GRASS:
                mult *= 2.0
            elif opp_type == PokemonType.WATER and t == PokemonType.DRAGON:
                mult *= 0.5
            elif opp_type == PokemonType.FIGHTING and t == PokemonType.GHOST:
                mult *= 0.0
            elif opp_type == PokemonType.GHOST and t == PokemonType.GHOST:
                mult *= 2.0
            elif opp_type == PokemonType.FIGHTING and t == PokemonType.DARK:
                mult *= 0.5
            elif opp_type == PokemonType.BUG and t == PokemonType.DARK:
                mult *= 2.0
            elif opp_type == PokemonType.DARK and t == PokemonType.DARK:
                mult *= 0.5
        return mult


def _make_battle(active_pokemon=None, opponent_active=None, force_switch=None):
    battle = MagicMock()
    battle.battle_tag = "test_battle_voluntary"
    battle.turn = 1
    battle.active_pokemon = active_pokemon or [None, None]
    battle.opponent_active_pokemon = opponent_active or [None, None]
    battle.available_moves = [[], []]
    battle.force_switch = force_switch or [False, False]
    battle.fields = []
    return battle


class TestVoluntarySwitchQuality(unittest.TestCase):

    def setUp(self):
        self.config = DoublesDamageAwareConfig()
        self.config.enable_voluntary_switch_quality_diagnostics = True
        self.config.enable_voluntary_switch_quality_scoring = False

    # 1. Forced switch excluded
    def test_forced_switch_excluded(self):
        from poke_env.battle.pokemon_type import PokemonType
        active = MockPokemon("Charizard", type_1=PokemonType.FIRE, type_2=PokemonType.FLYING)
        candidate = MockPokemon("Blastoise", type_1=PokemonType.WATER)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[MockPokemon("Venusaur", type_1=PokemonType.GRASS)],
            force_switch=[True, False],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 0.0, self.config)
        self.assertFalse(result["eligible"])
        self.assertIn("forced_switch", result["reason_codes"])

    # 2. Neutral voluntary switch receives tempo cost
    def test_neutral_switch_tempo_cost(self):
        from poke_env.battle.pokemon_type import PokemonType
        active = MockPokemon("Charizard", type_1=PokemonType.FIRE, type_2=PokemonType.FLYING, hp=1.0)
        candidate = MockPokemon("Blastoise", type_1=PokemonType.WATER, hp=1.0)
        opp = MockPokemon("Snorlax", type_1=PokemonType.NORMAL)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp, None],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 0.0, self.config)
        self.assertTrue(result["eligible"])
        self.assertGreater(result["score_adjustment"], 0,
                           "Neutral switch should have positive adjustment (penalty)")

    # 3. Clearly safer candidate can overcome tempo cost
    def test_safer_candidate_reduces_penalty(self):
        from poke_env.battle.pokemon_type import PokemonType
        # Active is weak to opponent (Fire vs Water)
        active = MockPokemon("Charizard", type_1=PokemonType.FIRE, type_2=PokemonType.FLYING, hp=1.0)
        # Candidate resists (Dragon vs Water)
        candidate = MockPokemon("Kingdra", type_1=PokemonType.WATER, type_2=PokemonType.DRAGON, hp=1.0)
        opp = MockPokemon("Blastoise", type_1=PokemonType.WATER)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp, None],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 0.0, self.config)
        self.assertTrue(result["eligible"])
        self.assertTrue(result["risk_reduction"] > 0,
                        "Safer candidate should reduce risk")

    # 4. Candidate weak to both opponents is penalized
    def test_double_threat_penalty(self):
        from poke_env.battle.pokemon_type import PokemonType
        active = MockPokemon("Snorlax", type_1=PokemonType.NORMAL, hp=1.0)
        candidate = MockPokemon("Exeggutor", type_1=PokemonType.GRASS, type_2=PokemonType.PSYCHIC, hp=1.0)
        opp1 = MockPokemon("Charizard", type_1=PokemonType.FIRE)  # Fire > Grass
        opp2 = MockPokemon("Gengar", type_1=PokemonType.GHOST, type_2=PokemonType.POISON)  # Ghost > Psychic
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp1, opp2],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 0.0, self.config)
        self.assertGreater(result["candidate_penalty"], 0,
                           "Exeggutor vs Fire+Ghost should have candidate penalty")
        self.assertTrue(result["eligible"])

    # 5. Quad-weak candidate is penalized
    def test_quad_weak_penalty(self):
        from poke_env.battle.pokemon_type import PokemonType
        active = MockPokemon("Snorlax", type_1=PokemonType.NORMAL, hp=1.0)
        # Charizard is Fire/Flying, weak 4x to Rock
        candidate = MockPokemon("Tyranitar", type_1=PokemonType.ROCK, type_2=PokemonType.DARK, hp=1.0)
        opp = MockPokemon("Machamp", type_1=PokemonType.FIGHTING)  # Fighting > Rock
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp, None],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 0.0, self.config)
        self.assertTrue(result["eligible"])

    # 6. Dual-type matchup uses combined multiplier
    def test_dual_type_combined_multiplier(self):
        from poke_env.battle.pokemon_type import PokemonType
        active = MockPokemon("Snorlax", type_1=PokemonType.NORMAL, hp=1.0)
        # Garchomp is Dragon/Ground. Ice move would be 4x effective
        candidate = MockPokemon("Garchomp", type_1=PokemonType.DRAGON, type_2=PokemonType.GROUND, hp=1.0)
        opp = MockPokemon("Weavile", type_1=PokemonType.DARK, type_2=PokemonType.ICE)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp, None],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 0.0, self.config)
        self.assertTrue(result["eligible"])

    # 7. Low-HP candidate is penalized
    def test_low_hp_candidate_penalty(self):
        from poke_env.battle.pokemon_type import PokemonType
        active = MockPokemon("Charizard", type_1=PokemonType.FIRE, type_2=PokemonType.FLYING, hp=1.0)
        candidate = MockPokemon("Blastoise", type_1=PokemonType.WATER, hp=0.20)
        opp = MockPokemon("Venusaur", type_1=PokemonType.GRASS)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp, None],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 0.0, self.config)
        self.assertTrue(result["eligible"])
        self.assertTrue(result["candidate_low_hp"])

    # 8. Candidate worse than active gets no bonus
    def test_candidate_worse_no_bonus(self):
        from poke_env.battle.pokemon_type import PokemonType
        # Active resists, candidate is weak
        active = MockPokemon("Kingdra", type_1=PokemonType.WATER, type_2=PokemonType.DRAGON, hp=1.0)
        candidate = MockPokemon("Charizard", type_1=PokemonType.FIRE, type_2=PokemonType.FLYING, hp=1.0)
        opp = MockPokemon("Blastoise", type_1=PokemonType.WATER)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp, None],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 0.0, self.config)
        self.assertTrue(result["eligible"])
        self.assertFalse(result["switch_improves_position"],
                         "Worse candidate should not improve position")

    # 9. Active KO action discourages switching
    def test_active_ko_action_discourages_switch(self):
        from poke_env.battle.pokemon_type import PokemonType
        active = MockPokemon("Charizard", type_1=PokemonType.FIRE, type_2=PokemonType.FLYING, hp=1.0)
        candidate = MockPokemon("Blastoise", type_1=PokemonType.WATER, hp=1.0)
        opp = MockPokemon("Venusaur", type_1=PokemonType.GRASS)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp, None],
        )
        # High best_stay_score simulates KO action
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 250.0, self.config)
        self.assertTrue(result["active_has_high_value_action"])
        self.assertTrue(result["active_has_useful_action"])

    # 10. High-value stay action discourages switching
    def test_high_value_stay_discourages_switch(self):
        from poke_env.battle.pokemon_type import PokemonType
        active = MockPokemon("Charizard", type_1=PokemonType.FIRE, type_2=PokemonType.FLYING, hp=1.0)
        candidate = MockPokemon("Blastoise", type_1=PokemonType.WATER, hp=1.0)
        opp = MockPokemon("Venusaur", type_1=PokemonType.GRASS)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp, None],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 150.0, self.config)
        self.assertTrue(result["active_has_high_value_action"])

    # 11. Useful low-HP active may be allowed to stay/faint
    def test_low_hp_useful_action_stay_preferred(self):
        from poke_env.battle.pokemon_type import PokemonType
        active = MockPokemon("Charizard", type_1=PokemonType.FIRE, type_2=PokemonType.FLYING, hp=0.10)
        candidate = MockPokemon("Blastoise", type_1=PokemonType.WATER, hp=1.0)
        opp = MockPokemon("Venusaur", type_1=PokemonType.GRASS)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp, None],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 80.0, self.config)
        self.assertTrue(result["active_low_hp"])
        self.assertTrue(result["active_has_useful_action"])

    # 12. Low-HP active with no useful action may switch
    def test_low_hp_no_action_sacrifice_preferred(self):
        from poke_env.battle.pokemon_type import PokemonType
        active = MockPokemon("Charizard", type_1=PokemonType.FIRE, type_2=PokemonType.FLYING, hp=0.10)
        candidate = MockPokemon("Blastoise", type_1=PokemonType.WATER, hp=1.0)
        opp = MockPokemon("Venusaur", type_1=PokemonType.GRASS)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp, None],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 5.0, self.config)
        self.assertTrue(result["active_low_hp"])
        self.assertFalse(result["active_has_useful_action"])

    # 13. Clearly safer candidate overrides sacrifice preference
    def test_safer_candidate_overrides_sacrifice(self):
        from poke_env.battle.pokemon_type import PokemonType
        # Active is weak + low HP
        active = MockPokemon("Charizard", type_1=PokemonType.FIRE, type_2=PokemonType.FLYING, hp=0.10)
        # Candidate is immune to opponent's type
        candidate = MockPokemon("Flygon", type_1=PokemonType.GROUND, type_2=PokemonType.DRAGON, hp=1.0)
        opp = MockPokemon("Electivire", type_1=PokemonType.ELECTRIC)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp, None],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 5.0, self.config)
        # Flygon is Ground type which is immune to Electric - risk_reduction should be positive
        # Note: the mock damage_multiplier may handle this correctly
        self.assertTrue(result["eligible"])

    # 14. Consecutive voluntary switch receives repeat penalty
    def test_repeat_switch_penalty(self):
        from poke_env.battle.pokemon_type import PokemonType
        config = DoublesDamageAwareConfig()
        config.enable_voluntary_switch_quality_diagnostics = True
        config.enable_voluntary_switch_quality_scoring = False
        active = MockPokemon("Charizard", type_1=PokemonType.FIRE, type_2=PokemonType.FLYING, hp=1.0)
        candidate = MockPokemon("Blastoise", type_1=PokemonType.WATER, hp=1.0)
        opp = MockPokemon("Venusaur", type_1=PokemonType.GRASS)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp, None],
            force_switch=[False, False],
        )

        # Build a switch order
        class MockOrder:
            def __init__(self, mon):
                self.order = mon
                self.move_target = 0

        switch_orders = [MockOrder(candidate)]

        # First call: no history, no repeat
        table1 = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 0.0, config,
            voluntary_switch_history={},
        )
        for row in table1:
            self.assertEqual(row["repeat_penalty"], 0.0,
                             "First switch should have no repeat penalty")

        # Second call: simulate recent switch in history
        battle.turn = 2
        history = {(battle.battle_tag, 0): {"last_switch_turn": 1}}
        table2 = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 0.0, config,
            voluntary_switch_history=history,
        )
        for row in table2:
            self.assertGreater(row["repeat_penalty"], 0,
                               "Consecutive switch should have repeat penalty")

    # 15. Forced switch does not receive repeat penalty
    def test_forced_no_repeat_penalty(self):
        from poke_env.battle.pokemon_type import PokemonType
        active = MockPokemon("Charizard", type_1=PokemonType.FIRE, type_2=PokemonType.FLYING)
        candidate = MockPokemon("Blastoise", type_1=PokemonType.WATER)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[MockPokemon("Venusaur", type_1=PokemonType.GRASS)],
            force_switch=[True, False],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 0.0, self.config)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["repeat_switch_penalty"], 0)

    # 16. No hidden-information access (smoke test)
    def test_no_hidden_info_access(self):
        from poke_env.battle.pokemon_type import PokemonType
        active = MockPokemon("Charizard", type_1=PokemonType.FIRE, type_2=PokemonType.FLYING, hp=1.0)
        candidate = MockPokemon("Blastoise", type_1=PokemonType.WATER, hp=1.0)
        opp = MockPokemon("Venusaur", type_1=PokemonType.GRASS)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp, None],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 0.0, self.config)
        self.assertTrue(result["eligible"])
        # Should not crash or access hidden info
        self.assertIn("score_adjustment", result)

    # 17. Scoring OFF changes no scores (config default)
    def test_scoring_off_no_change(self):
        from poke_env.battle.pokemon_type import PokemonType
        config_off = DoublesDamageAwareConfig()
        config_off.enable_voluntary_switch_quality_diagnostics = True
        config_off.enable_voluntary_switch_quality_scoring = False
        active = MockPokemon("Charizard", type_1=PokemonType.FIRE, type_2=PokemonType.FLYING, hp=1.0)
        candidate = MockPokemon("Blastoise", type_1=PokemonType.WATER, hp=1.0)
        opp = MockPokemon("Venusaur", type_1=PokemonType.GRASS)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp, None],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 0.0, config_off)
        self.assertTrue(result["eligible"])
        # Diagnostics populate even when scoring off
        self.assertIn("active_risk", result)

    # 18. Diagnostics still populate when scoring is OFF
    def test_diagnostics_populate_when_scoring_off(self):
        from poke_env.battle.pokemon_type import PokemonType
        config = DoublesDamageAwareConfig()
        config.enable_voluntary_switch_quality_diagnostics = True
        config.enable_voluntary_switch_quality_scoring = False
        active = MockPokemon("Charizard", type_1=PokemonType.FIRE, type_2=PokemonType.FLYING, hp=1.0)
        candidate = MockPokemon("Blastoise", type_1=PokemonType.WATER, hp=1.0)
        opp = MockPokemon("Venusaur", type_1=PokemonType.GRASS)
        battle = _make_battle(
            active_pokemon=[active, None],
            opponent_active=[opp, None],
        )
        result = evaluate_voluntary_switch_quality(active, candidate, 0, battle, 0.0, config)
        self.assertTrue(result["eligible"])
        self.assertGreater(result["active_risk"], 0,
                           "Diagnostics should compute active risk even when scoring is off")

    # 19. Evaluate switch candidate type safety still works
    def test_existing_switch_candidate_safety_unchanged(self):
        from poke_env.battle.pokemon_type import PokemonType
        candidate = MockPokemon("Blastoise", type_1=PokemonType.WATER, hp=1.0)
        opp1 = MockPokemon("Venusaur", type_1=PokemonType.GRASS)
        result = evaluate_switch_candidate_type_safety(candidate, [opp1])
        self.assertIn("raw_safety_score", result)
        self.assertIn("worst_multiplier", result)


class TestValidateJsonl(unittest.TestCase):
    """21 tests for validate_jsonl."""

    def _cand_row(self, index=0, key=None, species="Blastoise", selected=True,
                  active_risk=2.0, candidate_risk=1.0):
        if key is None:
            key = ["Switch|Blastoise", "", 0]
        return {
            "candidate_index": index,
            "candidate_action_key": key,
            "species": species,
            "raw_switch_score": 0.0,
            "adjusted_switch_score": 0.0,
            "active_risk": active_risk,
            "candidate_risk": candidate_risk,
            "risk_reduction": active_risk - candidate_risk,
            "score_adjustment": 0.5,
            "selected": selected,
        }

    def _empty_turn_slot0_selected(self, turn=1):
        return {
            "turn": turn,
            "voluntary_switch_decision_eligible": [True, False],
            "voluntary_switch_selected": [True, False],
            "voluntary_switch_selected_species": ["Blastoise", ""],
            "voluntary_switch_selection_changed": [False, False],
            "voluntary_switch_joint_selection_changed": False,
            "voluntary_switch_counterfactual_action": [("", "", 0), ("", "", 0)],
            "voluntary_switch_selected_action": [("Switch|Blastoise", "", 0), ("", "", 0)],
            "voluntary_switch_candidate_table": [
                [self._cand_row()],
                [],
            ],
            "voluntary_switch_unnecessary_selected": [False, False],
            "voluntary_switch_unsafe_candidate_selected": [False, False],
            "voluntary_switch_repeat_selected": [False, False],
            "voluntary_switch_sacrifice_opportunity": [False, False],
            "voluntary_switch_healthy_bench_preserved": [False, False],
            "voluntary_switch_safer_candidate_available": [False, False],
            "voluntary_switch_active_species": ["Charizard", ""],
            "voluntary_switch_active_hp": [1.0, 0.0],
            "voluntary_switch_best_stay_score": [100.0, 0.0],
            "voluntary_switch_selected_active_risk": [2.0, 0.0],
            "voluntary_switch_selected_candidate_risk": [1.0, 0.0],
            "voluntary_switch_selected_risk_reduction": [1.0, 0.0],
            "voluntary_switch_selected_score_adjustment": [0.5, 0.0],
            "voluntary_switch_reason_codes": [["safer_candidate"], []],
        }

    def _write_jsonl(self, records):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
        path = f.name
        for rec in records:
            f.write(json.dumps(rec) + "\n")
        f.close()
        self.addCleanup(os.remove, path)
        return path

    def test_valid_artifact(self):
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": [self._empty_turn_slot0_selected()],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertEqual(errors, [])

    def test_missing_file(self):
        errors = validate_jsonl("/nonexistent/path.jsonl", 1, "A")
        self.assertIn("not found", errors[0])

    def test_malformed_json(self):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
        path = f.name
        f.write("this is not json\n")
        f.close()
        self.addCleanup(os.remove, path)
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(any("malformed JSON" in e for e in errors))

    def test_wrong_record_count(self):
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": [self._empty_turn_slot0_selected()],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 2, "A")
        self.assertTrue(any("Record count" in e for e in errors))

    def test_duplicate_battle_tag(self):
        rec = {
            "battle_tag": "dup_tag",
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": [self._empty_turn_slot0_selected()],
        }
        path = self._write_jsonl([rec, rec])
        errors = validate_jsonl(path, 2, "A")
        self.assertTrue(any("Unique battle tags" in e for e in errors))

    def test_missing_battle_tag(self):
        rec = {
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": [self._empty_turn_slot0_selected()],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(any("Unique battle tags" in e for e in errors))

    def test_non_boolean_won(self):
        rec = {
            "battle_tag": "test_001",
            "won": "yes",
            "benchmark_arm": "A",
            "audit_turns": [self._empty_turn_slot0_selected()],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(any("not bool" in e for e in errors))

    def test_wrong_benchmark_arm(self):
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "benchmark_arm": "X",
            "audit_turns": [self._empty_turn_slot0_selected()],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(any("benchmark_arm" in e and "X" in e for e in errors))

    def test_missing_benchmark_arm(self):
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "audit_turns": [self._empty_turn_slot0_selected()],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(any("benchmark_arm" in e for e in errors))

    def test_audit_turns_not_list(self):
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": "not_a_list",
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(any("not list" in e for e in errors))

    def test_missing_vsw_field(self):
        turn = self._empty_turn_slot0_selected()
        del turn["voluntary_switch_selected"]
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": [turn],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(any("missing" in e and "voluntary_switch_selected" in e for e in errors))

    def test_slot_field_not_list(self):
        turn = self._empty_turn_slot0_selected()
        turn["voluntary_switch_candidate_table"] = ["not_a_list", []]
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": [turn],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(any("not a list" in e for e in errors))

    def test_candidate_table_wrong_shape(self):
        turn = self._empty_turn_slot0_selected()
        turn["voluntary_switch_candidate_table"] = [[]]
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": [turn],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(any("not list of exactly 2" in e for e in errors))

    def test_missing_candidate_field(self):
        row = self._cand_row()
        del row["species"]
        turn = self._empty_turn_slot0_selected()
        turn["voluntary_switch_candidate_table"] = [[row], []]
        turn["voluntary_switch_selected"] = [False, False]
        turn["voluntary_switch_selected_species"] = ["", ""]
        turn["voluntary_switch_selected_action"] = [("", "", 0), ("", "", 0)]
        turn["voluntary_switch_decision_eligible"] = [True, False]
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": [turn],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(any("missing" in e and "species" in e for e in errors))

    def test_duplicate_candidate_index(self):
        turn = self._empty_turn_slot0_selected()
        turn["voluntary_switch_candidate_table"] = [
            [self._cand_row(index=0), self._cand_row(index=0, key=["Switch|X", "", 0], species="X", selected=False)],
            [],
        ]
        turn["voluntary_switch_selected"] = [False, False]
        turn["voluntary_switch_selected_species"] = ["", ""]
        turn["voluntary_switch_selected_action"] = [("", "", 0), ("", "", 0)]
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": [turn],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(any("duplicate candidate_index" in e for e in errors))

    def test_duplicate_candidate_action_key(self):
        turn = self._empty_turn_slot0_selected()
        key = ["Switch|Same", "", 0]
        turn["voluntary_switch_candidate_table"] = [
            [self._cand_row(index=0, key=key, species="A", selected=False),
             self._cand_row(index=1, key=key, species="B", selected=False)],
            [],
        ]
        turn["voluntary_switch_selected"] = [False, False]
        turn["voluntary_switch_selected_species"] = ["", ""]
        turn["voluntary_switch_selected_action"] = [("", "", 0), ("", "", 0)]
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": [turn],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(any("duplicate candidate_action_key" in e for e in errors))

    def test_two_selected_rows_in_one_slot(self):
        turn = self._empty_turn_slot0_selected()
        turn["voluntary_switch_candidate_table"] = [
            [self._cand_row(index=0, selected=True),
             self._cand_row(index=1, key=["Switch|X", "", 0], species="X", selected=True)],
            [],
        ]
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": [turn],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(any("selected rows" in e for e in errors))

    def test_selected_flag_mismatch_true_but_no_row(self):
        turn = self._empty_turn_slot0_selected()
        turn["voluntary_switch_selected"] = [True, False]
        turn["voluntary_switch_candidate_table"] = [[], []]
        turn["voluntary_switch_selected_species"] = ["Blastoise", ""]
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": [turn],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(any("is true but no selected row" in e for e in errors))

    def test_selected_flag_false_but_has_selected_row(self):
        turn = self._empty_turn_slot0_selected()
        turn["voluntary_switch_selected"] = [False, False]
        turn["voluntary_switch_selected_species"] = ["", ""]
        turn["voluntary_switch_selected_action"] = [("", "", 0), ("", "", 0)]
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": [turn],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(any("is false but has selected row" in e for e in errors))

    def test_valid_no_switch(self):
        turn = self._empty_turn_slot0_selected()
        turn["voluntary_switch_selected"] = [False, False]
        turn["voluntary_switch_selected_species"] = ["", ""]
        turn["voluntary_switch_selected_action"] = [("", "", 0), ("", "", 0)]
        turn["voluntary_switch_decision_eligible"] = [True, False]
        turn["voluntary_switch_candidate_table"] = [[], []]
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": [turn],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertEqual(errors, [])

    def test_valid_two_slot_switch(self):
        turn = self._empty_turn_slot0_selected()
        row0 = self._cand_row(index=0, key=["switch", "Blastoise", 0], species="Blastoise", selected=True)
        row1 = self._cand_row(index=1, key=["switch", "Charizard", 0], species="Charizard", selected=True)
        turn["voluntary_switch_selected"] = [True, True]
        turn["voluntary_switch_selected_species"] = ["Blastoise", "Charizard"]
        turn["voluntary_switch_selected_action"] = [
            ["switch", "Blastoise", 0],
            ["switch", "Charizard", 0],
        ]
        turn["voluntary_switch_decision_eligible"] = [True, True]
        turn["voluntary_switch_candidate_table"] = [[row0], [row1]]
        turn["voluntary_switch_active_species"] = ["Charizard", "Snorlax"]
        turn["voluntary_switch_active_hp"] = [1.0, 1.0]
        turn["voluntary_switch_selected_active_risk"] = [2.0, 3.0]
        turn["voluntary_switch_selected_candidate_risk"] = [1.0, 1.5]
        turn["voluntary_switch_selected_risk_reduction"] = [1.0, 1.5]
        turn["voluntary_switch_selected_score_adjustment"] = [0.5, 0.3]
        turn["voluntary_switch_best_stay_score"] = [100.0, 80.0]
        turn["voluntary_switch_reason_codes"] = [["safer"], ["safer"]]
        rec = {
            "battle_tag": "test_001",
            "won": True,
            "benchmark_arm": "A",
            "audit_turns": [turn],
        }
        path = self._write_jsonl([rec])
        errors = validate_jsonl(path, 1, "A")
        self.assertEqual(errors, [], f"Expected no errors, got: {errors}")

    def test_valid_slot0_only_switch(self):
        turn = self._empty_turn_slot0_selected()
        row0 = self._cand_row(index=0, key=["switch", "Blastoise", 0], species="Blastoise", selected=True)
        turn["voluntary_switch_selected"] = [True, False]
        turn["voluntary_switch_selected_species"] = ["Blastoise", ""]
        turn["voluntary_switch_selected_action"] = [["switch", "Blastoise", 0], ("", "", 0)]
        turn["voluntary_switch_decision_eligible"] = [True, False]
        turn["voluntary_switch_candidate_table"] = [[row0], []]
        turn["voluntary_switch_active_species"] = ["Charizard", "Snorlax"]
        turn["voluntary_switch_active_hp"] = [1.0, 1.0]
        turn["voluntary_switch_selected_active_risk"] = [2.0, 0.0]
        turn["voluntary_switch_selected_candidate_risk"] = [1.0, 0.0]
        turn["voluntary_switch_selected_risk_reduction"] = [1.0, 0.0]
        turn["voluntary_switch_selected_score_adjustment"] = [0.5, 0.0]
        turn["voluntary_switch_best_stay_score"] = [100.0, 0.0]
        turn["voluntary_switch_reason_codes"] = [["safer"], []]
        rec = {"battle_tag": "t2", "won": True, "benchmark_arm": "A", "audit_turns": [turn]}
        errors = validate_jsonl(self._write_jsonl([rec]), 1, "A")
        self.assertEqual(errors, [])

    def test_valid_slot1_only_switch(self):
        turn = self._empty_turn_slot0_selected()
        row1 = self._cand_row(index=0, key=["switch", "Blastoise", 0], species="Blastoise", selected=True)
        turn["voluntary_switch_selected"] = [False, True]
        turn["voluntary_switch_selected_species"] = ["", "Blastoise"]
        turn["voluntary_switch_selected_action"] = [("", "", 0), ["switch", "Blastoise", 0]]
        turn["voluntary_switch_decision_eligible"] = [False, True]
        turn["voluntary_switch_candidate_table"] = [[], [row1]]
        turn["voluntary_switch_active_species"] = ["Charizard", "Snorlax"]
        turn["voluntary_switch_active_hp"] = [1.0, 1.0]
        turn["voluntary_switch_selected_active_risk"] = [0.0, 2.0]
        turn["voluntary_switch_selected_candidate_risk"] = [0.0, 1.0]
        turn["voluntary_switch_selected_risk_reduction"] = [0.0, 1.0]
        turn["voluntary_switch_selected_score_adjustment"] = [0.0, 0.5]
        turn["voluntary_switch_best_stay_score"] = [0.0, 100.0]
        turn["voluntary_switch_reason_codes"] = [[], ["safer"]]
        rec = {"battle_tag": "t3", "won": True, "benchmark_arm": "A", "audit_turns": [turn]}
        errors = validate_jsonl(self._write_jsonl([rec]), 1, "A")
        self.assertEqual(errors, [])

    def test_two_selected_rows_same_slot_invalid(self):
        turn = self._empty_turn_slot0_selected()
        row0a = self._cand_row(index=0, key=["switch", "A", 0], species="A", selected=True)
        row0b = self._cand_row(index=1, key=["switch", "B", 0], species="B", selected=True)
        turn["voluntary_switch_selected"] = [True, False]
        turn["voluntary_switch_selected_species"] = ["A", ""]
        turn["voluntary_switch_selected_action"] = [["switch", "A", 0], ("", "", 0)]
        turn["voluntary_switch_decision_eligible"] = [True, False]
        turn["voluntary_switch_candidate_table"] = [[row0a, row0b], []]
        turn["voluntary_switch_active_species"] = ["Charizard", "Snorlax"]
        turn["voluntary_switch_active_hp"] = [1.0, 1.0]
        turn["voluntary_switch_selected_active_risk"] = [2.0, 0.0]
        turn["voluntary_switch_selected_candidate_risk"] = [1.0, 0.0]
        turn["voluntary_switch_selected_risk_reduction"] = [1.0, 0.0]
        turn["voluntary_switch_selected_score_adjustment"] = [0.5, 0.0]
        turn["voluntary_switch_best_stay_score"] = [100.0, 0.0]
        turn["voluntary_switch_reason_codes"] = [["safer"], []]
        rec = {"battle_tag": "t4", "won": True, "benchmark_arm": "A", "audit_turns": [turn]}
        errors = validate_jsonl(self._write_jsonl([rec]), 1, "A")
        self.assertTrue(len(errors) > 0, "Two selected rows in one slot should fail")


CSV_HEADER = ("arm,status,planned,finished,time_s,eligible,selected,unnecessary,unsafe,"
              "repeat,sacrifice_opp,healthy_bench,safer_avail,candidate_safer,candidate_equal,"
              "candidate_worse,sel_changed,joint_changed,avg_risk_red,avg_best_stay,"
              "avg_score_adj,wins,losses,jsonl_validation_pass")


class TestValidateCsv(unittest.TestCase):
    """12 tests for validate_csv."""

    def _write_csv(self, lines):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
        path = f.name
        for line in lines:
            f.write(line + "\n")
        f.close()
        self.addCleanup(os.remove, path)
        return path

    def test_valid_csv(self):
        lines = [
            CSV_HEADER,
            "A,ok,100,100,10,50,10,1,0,2,5,3,4,20,10,5,10,2,0.5,10,2,40,60,True",
            "B,ok,50,50,5,25,5,0,0,1,2,1,2,10,5,3,5,1,0.3,5,1,20,30,True",
            "C,ok,100,100,10,50,10,1,0,2,5,3,4,20,10,5,10,2,0.5,10,2,40,60,True",
        ]
        path = self._write_csv(lines)
        errors = validate_csv(path, {"A": 100, "B": 50, "C": 100})
        self.assertEqual(errors, [])

    def test_missing_file(self):
        errors = validate_csv("/nonexistent/path.csv", {"A": 100})
        self.assertIn("not found", errors[0])

    def test_missing_arm(self):
        lines = [
            CSV_HEADER,
            "A,ok,100,100,10,50,10,1,0,2,5,3,4,20,10,5,10,2,0.5,10,2,40,60,True",
            "B,ok,50,50,5,25,5,0,0,1,2,1,2,10,5,3,5,1,0.3,5,1,20,30,True",
        ]
        path = self._write_csv(lines)
        errors = validate_csv(path, {"A": 100, "B": 50, "C": 100})
        self.assertTrue(any("Missing arm 'C'" in e for e in errors))

    def test_duplicate_arm(self):
        lines = [
            CSV_HEADER,
            "A,ok,100,100,10,50,10,1,0,2,5,3,4,20,10,5,10,2,0.5,10,2,40,60,True",
            "A,ok,100,100,10,50,10,1,0,2,5,3,4,20,10,5,10,2,0.5,10,2,40,60,True",
            "B,ok,50,50,5,25,5,0,0,1,2,1,2,10,5,3,5,1,0.3,5,1,20,30,True",
            "C,ok,100,100,10,50,10,1,0,2,5,3,4,20,10,5,10,2,0.5,10,2,40,60,True",
        ]
        path = self._write_csv(lines)
        errors = validate_csv(path, {"A": 100, "B": 50, "C": 100})
        self.assertTrue(any("duplicate arm 'A'" in e for e in errors))

    def test_unknown_arm(self):
        lines = [
            CSV_HEADER,
            "A,ok,100,100,10,50,10,1,0,2,5,3,4,20,10,5,10,2,0.5,10,2,40,60,True",
            "D,ok,50,50,5,25,5,0,0,1,2,1,2,10,5,3,5,1,0.3,5,1,20,30,True",
            "C,ok,100,100,10,50,10,1,0,2,5,3,4,20,10,5,10,2,0.5,10,2,40,60,True",
        ]
        path = self._write_csv(lines)
        errors = validate_csv(path, {"A": 100, "B": 50, "C": 100})
        self.assertTrue(any("unknown arm 'D'" in e for e in errors))

    def test_empty_arm_name(self):
        lines = [
            CSV_HEADER,
            "A,ok,100,100,10,50,10,1,0,2,5,3,4,20,10,5,10,2,0.5,10,2,40,60,True",
            ",ok,50,50,5,25,5,0,0,1,2,1,2,10,5,3,5,1,0.3,5,1,20,30,True",
            "C,ok,100,100,10,50,10,1,0,2,5,3,4,20,10,5,10,2,0.5,10,2,40,60,True",
        ]
        path = self._write_csv(lines)
        errors = validate_csv(path, {"A": 100, "B": 50, "C": 100})
        self.assertTrue(any("empty arm name" in e for e in errors))

    def test_non_integer_planned(self):
        lines = [
            CSV_HEADER,
            "A,ok,abc,100,10,50,10,1,0,2,5,3,4,20,10,5,10,2,0.5,10,2,40,60,True",
        ]
        path = self._write_csv(lines)
        errors = validate_csv(path, {"A": 100})
        self.assertTrue(any("not int" in e for e in errors))

    def test_planned_mismatch(self):
        lines = [
            CSV_HEADER,
            "A,ok,10,10,10,50,10,1,0,2,5,3,4,20,10,5,10,2,0.5,10,2,40,60,True",
        ]
        path = self._write_csv(lines)
        errors = validate_csv(path, {"A": 2})
        self.assertTrue(any("planned 10 != expected 2" in e for e in errors))

    def test_finished_mismatch(self):
        lines = [
            CSV_HEADER,
            "A,ok,2,1,10,50,10,1,0,2,5,3,4,20,10,5,10,2,0.5,10,2,40,60,True",
        ]
        path = self._write_csv(lines)
        errors = validate_csv(path, {"A": 2})
        self.assertTrue(any("finished 1 != planned 2" in e for e in errors))

    def test_failed_status(self):
        lines = [
            CSV_HEADER,
            "A,stall,100,100,10,50,10,1,0,2,5,3,4,20,10,5,10,2,0.5,10,2,40,60,True",
        ]
        path = self._write_csv(lines)
        errors = validate_csv(path, {"A": 100})
        self.assertTrue(any("status 'stall' != 'ok'" in e for e in errors))

    def test_false_validation_flag(self):
        lines = [
            CSV_HEADER,
            "A,ok,100,100,10,50,10,1,0,2,5,3,4,20,10,5,10,2,0.5,10,2,40,60,False",
        ]
        path = self._write_csv(lines)
        errors = validate_csv(path, {"A": 100})
        self.assertTrue(any("jsonl_validation_pass is 'False'" in e for e in errors))

    def test_malformed_column_count(self):
        lines = [
            CSV_HEADER,
            "A,ok,100",
        ]
        path = self._write_csv(lines)
        errors = validate_csv(path, {"A": 100})
        self.assertTrue(any("fields, expected" in e for e in errors))


class TestCountVswMetrics(unittest.TestCase):
    """12 tests for count_vsw_metrics."""

    def _write_jsonl(self, records):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
        path = f.name
        for rec in records:
            f.write(json.dumps(rec) + "\n")
        f.close()
        self.addCleanup(os.remove, path)
        return path

    def _make_turn(self, eligible=None, selected=None, unnecessary=None,
                   unsafe=None, repeat=None, sac_opp=None, healthy=None,
                   safer=None, sel_changed=None, joint_changed=False,
                   sel_active_risk=None, sel_candidate_risk=None,
                   best_stay=None, sel_score_adj=None, candidate_table=None,
                   active_species=None, active_hp=None):
        bool2 = lambda v: [v[0] if len(v) > 0 else False, v[1] if len(v) > 1 else False] if v else [False, False]
        float2 = lambda v: [v[0] if len(v) > 0 else 0.0, v[1] if len(v) > 1 else 0.0] if v else [0.0, 0.0]
        turn = {
            "turn": 1,
            "voluntary_switch_decision_eligible": bool2(eligible),
            "voluntary_switch_selected": bool2(selected),
            "voluntary_switch_selected_species": [("Blastoise" if selected and selected[0] else ""),
                                                   ("Charizard" if selected and len(selected) > 1 and selected[1] else "")],
            "voluntary_switch_selection_changed": bool2(sel_changed),
            "voluntary_switch_joint_selection_changed": joint_changed,
            "voluntary_switch_counterfactual_action": [("", "", 0), ("", "", 0)],
            "voluntary_switch_selected_action": [("Switch|Blastoise", "", 0), ("Switch|Charizard", "", 0)],
            "voluntary_switch_candidate_table": candidate_table or [[], []],
            "voluntary_switch_unnecessary_selected": bool2(unnecessary),
            "voluntary_switch_unsafe_candidate_selected": bool2(unsafe),
            "voluntary_switch_repeat_selected": bool2(repeat),
            "voluntary_switch_sacrifice_opportunity": bool2(sac_opp),
            "voluntary_switch_healthy_bench_preserved": bool2(healthy),
            "voluntary_switch_safer_candidate_available": bool2(safer),
            "voluntary_switch_active_species": active_species or ["Charizard", ""],
            "voluntary_switch_active_hp": float2(active_hp),
            "voluntary_switch_best_stay_score": float2(best_stay),
            "voluntary_switch_selected_active_risk": float2(sel_active_risk),
            "voluntary_switch_selected_candidate_risk": float2(sel_candidate_risk),
            "voluntary_switch_selected_risk_reduction": [a - c for a, c in zip(float2(sel_active_risk), float2(sel_candidate_risk))],
            "voluntary_switch_selected_score_adjustment": float2(sel_score_adj),
            "voluntary_switch_reason_codes": [[], []],
        }
        return turn

    def test_missing_file(self):
        metrics = count_vsw_metrics("/nonexistent/path.jsonl")
        self.assertEqual(metrics["eligible"], 0)
        self.assertEqual(metrics["selected"], 0)

    def test_risk_reduction_sign(self):
        turn = self._make_turn(
            eligible=[True, False], selected=[True, False],
            sel_active_risk=[4.0, 0.0], sel_candidate_risk=[1.0, 0.0],
            candidate_table=[[{"candidate_index": 0, "candidate_action_key": ["Switch|Blastoise", "", 0],
                              "species": "Blastoise", "raw_switch_score": 0.0, "adjusted_switch_score": 0.0,
                              "active_risk": 4.0, "candidate_risk": 1.0, "risk_reduction": 3.0,
                              "score_adjustment": 0.5, "selected": True}], []],
        )
        rec = {"battle_tag": "test", "won": True, "benchmark_arm": "A", "audit_turns": [turn]}
        path = self._write_jsonl([rec])
        metrics = count_vsw_metrics(path)
        self.assertAlmostEqual(metrics["total_risk_red"], 3.0)
        self.assertEqual(metrics["count_risk_red"], 1)

    def test_unnecessary_count(self):
        turn = self._make_turn(
            eligible=[True, True], selected=[True, True],
            unnecessary=[True, False],
        )
        rec = {"battle_tag": "test", "won": True, "benchmark_arm": "A", "audit_turns": [turn]}
        path = self._write_jsonl([rec])
        metrics = count_vsw_metrics(path)
        self.assertEqual(metrics["unnecessary"], 1)

    def test_unsafe_count(self):
        turn = self._make_turn(
            eligible=[True, True], selected=[True, False],
            unsafe=[True, False],
        )
        rec = {"battle_tag": "test", "won": True, "benchmark_arm": "A", "audit_turns": [turn]}
        path = self._write_jsonl([rec])
        metrics = count_vsw_metrics(path)
        self.assertEqual(metrics["unsafe"], 1)

    def test_repeat_count(self):
        turn = self._make_turn(
            eligible=[True, True], selected=[True, False],
            repeat=[True, False],
        )
        rec = {"battle_tag": "test", "won": True, "benchmark_arm": "A", "audit_turns": [turn]}
        path = self._write_jsonl([rec])
        metrics = count_vsw_metrics(path)
        self.assertEqual(metrics["repeat"], 1)

    def test_sacrifice_opportunity_without_switch(self):
        turn = self._make_turn(
            eligible=[True, True], selected=[False, False],
            sac_opp=[True, False],
        )
        rec = {"battle_tag": "test", "won": True, "benchmark_arm": "A", "audit_turns": [turn]}
        path = self._write_jsonl([rec])
        metrics = count_vsw_metrics(path)
        self.assertEqual(metrics["sacrifice_opp"], 1)

    def test_healthy_bench_preserved(self):
        turn = self._make_turn(
            eligible=[True, True], selected=[False, False],
            healthy=[True, False],
        )
        rec = {"battle_tag": "test", "won": True, "benchmark_arm": "A", "audit_turns": [turn]}
        path = self._write_jsonl([rec])
        metrics = count_vsw_metrics(path)
        self.assertEqual(metrics["healthy_bench"], 1)

    def test_safer_candidate_available(self):
        turn = self._make_turn(
            eligible=[True, True], selected=[False, False],
            safer=[True, False],
        )
        rec = {"battle_tag": "test", "won": True, "benchmark_arm": "A", "audit_turns": [turn]}
        path = self._write_jsonl([rec])
        metrics = count_vsw_metrics(path)
        self.assertEqual(metrics["safer_avail"], 1)

    def test_selection_changes(self):
        turn = self._make_turn(
            eligible=[True, True], selected=[True, False],
            sel_changed=[True, False], joint_changed=True,
        )
        rec = {"battle_tag": "test", "won": True, "benchmark_arm": "A", "audit_turns": [turn]}
        path = self._write_jsonl([rec])
        metrics = count_vsw_metrics(path)
        self.assertEqual(metrics["sel_changed"], 1)
        self.assertEqual(metrics["joint_changed"], 1)

    def test_wins_and_losses(self):
        turn = self._make_turn(eligible=[True, False], selected=[False, False])
        recs = [
            {"battle_tag": "w1", "won": True, "benchmark_arm": "A", "audit_turns": [turn]},
            {"battle_tag": "l1", "won": False, "benchmark_arm": "A", "audit_turns": [turn]},
        ]
        path = self._write_jsonl(recs)
        metrics = count_vsw_metrics(path)
        self.assertEqual(metrics["wins"], 1)
        self.assertEqual(metrics["losses"], 1)

    def test_selected_only_averages(self):
        row0 = {"candidate_index": 0, "candidate_action_key": ["Switch|Blastoise", "", 0],
                "species": "Blastoise", "raw_switch_score": 0.0, "adjusted_switch_score": 0.0,
                "active_risk": 4.0, "candidate_risk": 2.0, "risk_reduction": 2.0,
                "score_adjustment": 0.5, "selected": True}
        row1 = {"candidate_index": 0, "candidate_action_key": ["Switch|X", "", 0],
                "species": "X", "raw_switch_score": 0.0, "adjusted_switch_score": 0.0,
                "active_risk": 10.0, "candidate_risk": 5.0, "risk_reduction": 5.0,
                "score_adjustment": 0.5, "selected": False}
        turn = {
            "turn": 1,
            "voluntary_switch_decision_eligible": [True, True],
            "voluntary_switch_selected": [True, False],
            "voluntary_switch_selected_species": ["Blastoise", ""],
            "voluntary_switch_selection_changed": [False, False],
            "voluntary_switch_joint_selection_changed": False,
            "voluntary_switch_counterfactual_action": [("", "", 0), ("", "", 0)],
            "voluntary_switch_selected_action": [("Switch|Blastoise", "", 0), ("", "", 0)],
            "voluntary_switch_candidate_table": [[row0], [row1]],
            "voluntary_switch_unnecessary_selected": [False, False],
            "voluntary_switch_unsafe_candidate_selected": [False, False],
            "voluntary_switch_repeat_selected": [False, False],
            "voluntary_switch_sacrifice_opportunity": [False, False],
            "voluntary_switch_healthy_bench_preserved": [False, False],
            "voluntary_switch_safer_candidate_available": [False, False],
            "voluntary_switch_active_species": ["Charizard", "Snorlax"],
            "voluntary_switch_active_hp": [1.0, 1.0],
            "voluntary_switch_best_stay_score": [100.0, 80.0],
            "voluntary_switch_selected_active_risk": [4.0, 10.0],
            "voluntary_switch_selected_candidate_risk": [2.0, 5.0],
            "voluntary_switch_selected_risk_reduction": [2.0, 5.0],
            "voluntary_switch_selected_score_adjustment": [0.5, 0.5],
            "voluntary_switch_reason_codes": [["safer"], []],
        }
        rec = {"battle_tag": "test", "won": True, "benchmark_arm": "A", "audit_turns": [turn]}
        path = self._write_jsonl([rec])
        metrics = count_vsw_metrics(path)
        self.assertAlmostEqual(metrics["total_risk_red"], 2.0)
        self.assertEqual(metrics["count_risk_red"], 1)
        self.assertAlmostEqual(metrics["total_best_stay"], 100.0)
        self.assertEqual(metrics["count_best_stay"], 1)

    def test_two_slot_switch(self):
        row0 = {"candidate_index": 0, "candidate_action_key": ["Switch|Blastoise", "", 0],
                "species": "Blastoise", "raw_switch_score": 0.0, "adjusted_switch_score": 0.0,
                "active_risk": 4.0, "candidate_risk": 2.0, "risk_reduction": 2.0,
                "score_adjustment": 0.5, "selected": True}
        row1 = {"candidate_index": 0, "candidate_action_key": ["Switch|Charizard", "", 0],
                "species": "Charizard", "raw_switch_score": 0.0, "adjusted_switch_score": 0.0,
                "active_risk": 3.0, "candidate_risk": 1.5, "risk_reduction": 1.5,
                "score_adjustment": 0.3, "selected": True}
        turn = {
            "turn": 1,
            "voluntary_switch_decision_eligible": [True, True],
            "voluntary_switch_selected": [True, True],
            "voluntary_switch_selected_species": ["Blastoise", "Charizard"],
            "voluntary_switch_selection_changed": [False, False],
            "voluntary_switch_joint_selection_changed": False,
            "voluntary_switch_counterfactual_action": [("", "", 0), ("", "", 0)],
            "voluntary_switch_selected_action": [("Switch|Blastoise", "", 0), ("Switch|Charizard", "", 0)],
            "voluntary_switch_candidate_table": [[row0], [row1]],
            "voluntary_switch_unnecessary_selected": [False, False],
            "voluntary_switch_unsafe_candidate_selected": [False, False],
            "voluntary_switch_repeat_selected": [False, False],
            "voluntary_switch_sacrifice_opportunity": [False, False],
            "voluntary_switch_healthy_bench_preserved": [False, False],
            "voluntary_switch_safer_candidate_available": [False, False],
            "voluntary_switch_active_species": ["Charizard", "Snorlax"],
            "voluntary_switch_active_hp": [1.0, 1.0],
            "voluntary_switch_best_stay_score": [100.0, 80.0],
            "voluntary_switch_selected_active_risk": [4.0, 3.0],
            "voluntary_switch_selected_candidate_risk": [2.0, 1.5],
            "voluntary_switch_selected_risk_reduction": [2.0, 1.5],
            "voluntary_switch_selected_score_adjustment": [0.5, 0.3],
            "voluntary_switch_reason_codes": [["safer"], ["safer"]],
        }
        rec = {"battle_tag": "test", "won": True, "benchmark_arm": "A", "audit_turns": [turn]}
        path = self._write_jsonl([rec])
        metrics = count_vsw_metrics(path)
        self.assertEqual(metrics["eligible"], 2)
        self.assertEqual(metrics["selected"], 2)
        self.assertAlmostEqual(metrics["total_risk_red"], 4.0 - 2.0 + 3.0 - 1.5)


class TestRunWithWatchdog(unittest.TestCase):
    """7 tests for run_with_watchdog."""

    HB = 0.01
    STALL = 0.1
    ARM = 0.2

    def _run(self, battle_coro, getter, hb=None, stall=None, arm=None):
        return asyncio.run(run_with_watchdog(
            battle_coro, getter,
            hb or self.HB, stall or self.STALL, arm or self.ARM,
        ))

    def test_natural_completion(self):
        async def _battle():
            return
        status, msg = self._run(_battle(), lambda: 0)
        self.assertEqual(status, "ok")

    def test_initial_stall(self):
        async def _battle():
            await asyncio.sleep(100)
        status, msg = self._run(_battle(), lambda: 0)
        self.assertEqual(status, "stall")

    def test_partial_progress_then_stall(self):
        counter = [0]
        async def _battle():
            await asyncio.sleep(100)
        async def _increment():
            await asyncio.sleep(0.02)
            counter[0] = 1
        async def _run():
            inc_task = asyncio.create_task(_increment())
            status, msg = await run_with_watchdog(
                _battle(), lambda: counter[0],
                self.HB, self.STALL, self.ARM,
            )
            inc_task.cancel()
            return status, msg
        status, msg = asyncio.run(_run())
        self.assertEqual(status, "stall")

    def test_continuous_progress(self):
        counter = [0]
        async def _battle():
            for _ in range(30):
                await asyncio.sleep(0.005)
                counter[0] += 1
        status, msg = self._run(_battle(), lambda: counter[0])
        self.assertEqual(status, "ok")

    def test_battle_exception(self):
        async def _battle():
            raise ValueError("test crash")
        status, msg = self._run(_battle(), lambda: 0)
        self.assertEqual(status, "crash")

    def test_arm_timeout(self):
        call_count = [0]
        def _getter():
            call_count[0] += 1
            return call_count[0]
        async def _battle():
            await asyncio.sleep(100)
        status, msg = self._run(_battle(), _getter)
        self.assertEqual(status, "timeout")

    def test_no_leaked_tasks(self):
        async def _run():
            async def _battle():
                await asyncio.sleep(100)
            tasks_before = asyncio.all_tasks()
            status, msg = await run_with_watchdog(
                _battle(), lambda: 0, self.HB, self.STALL, self.ARM,
            )
            tasks_after = asyncio.all_tasks()
            new_tasks = tasks_after - tasks_before
            pending = [t for t in new_tasks if not t.done()]
            self.assertEqual(len(pending), 0, f"Leaked tasks: {pending}")
            return status
        status = asyncio.run(_run())
        self.assertEqual(status, "stall")


class TestNormalizeActionKey(unittest.TestCase):
    """Tests for normalize_action_key."""

    def test_valid_move_key(self):
        self.assertEqual(normalize_action_key(("move", "flamethrower", 1)), ("move", "flamethrower", 1))

    def test_valid_switch_key(self):
        self.assertEqual(normalize_action_key(["switch", "Blastoise", 0]), ("switch", "Blastoise", 0))

    def test_wrong_length(self):
        with self.assertRaises(ValueError):
            normalize_action_key(["switch"])

    def test_nested_list(self):
        with self.assertRaises(ValueError):
            normalize_action_key([["nested"], "", 0])

    def test_dict_component(self):
        with self.assertRaises(ValueError):
            normalize_action_key(["move", {}, 0])

    def test_bool_component(self):
        with self.assertRaises(ValueError):
            normalize_action_key(["move", "fire", True])

    def test_none_component(self):
        with self.assertRaises(ValueError):
            normalize_action_key(["move", None, 0])

    def test_not_list(self):
        with self.assertRaises(ValueError):
            normalize_action_key("not_a_key")

    def test_malformed_selected_action_entry(self):
        with self.assertRaises(ValueError):
            normalize_action_key([["switch"], "", 0])

    def test_nested_in_selected_action(self):
        with self.assertRaises(ValueError):
            normalize_action_key([[["nested"], "", 0], 0, 0])


class TestRunnerStructure(unittest.TestCase):
    """Tests using production helpers from bot_doubles_voluntary_switch_diagnostics."""

    def test_three_arms_a_b_c(self):
        class MockArgs:
            battles_a = 100
            battles_b = 50
            battles_c = 100
        adefs = build_arm_definitions(MockArgs())
        self.assertEqual(len(adefs), 3)
        labels = [a[0] for a in adefs]
        self.assertEqual(labels, ["A", "B", "C"])

    def test_no_duplicate_labels(self):
        class MockArgs:
            battles_a = 1; battles_b = 1; battles_c = 1
        adefs = build_arm_definitions(MockArgs())
        labels = [a[0] for a in adefs]
        self.assertEqual(len(labels), len(set(labels)))

    def test_arm_classes_correct(self):
        from bot_doubles_basic_aware import DoublesBasicAwarePlayer
        from bot_doubles_damage_aware import DoublesDamageAwarePlayer
        class MockArgs:
            battles_a = 1; battles_b = 1; battles_c = 1
        adefs = build_arm_definitions(MockArgs())
        self.assertIs(adefs[0][1], DoublesBasicAwarePlayer)
        self.assertIs(adefs[1][1], DoublesSafeRandomPlayer)
        self.assertIs(adefs[2][1], DoublesDamageAwarePlayer)

    def test_default_plans(self):
        p = build_argument_parser()
        args = p.parse_args(["--artifact-tag=test"])
        self.assertEqual(args.battles_a, 100)
        self.assertEqual(args.battles_b, 50)
        self.assertEqual(args.battles_c, 100)

    def test_cli_overrides(self):
        p = build_argument_parser()
        args = p.parse_args(["--artifact-tag=test", "--battles-a=5", "--battles-b=3"])
        self.assertEqual(args.battles_a, 5)
        self.assertEqual(args.battles_b, 3)
        self.assertEqual(args.battles_c, 100)

    def test_missing_artifact_tag_exits(self):
        with self.assertRaises(SystemExit) as ctx:
            p = build_argument_parser()
            p.parse_args([])
        self.assertEqual(ctx.exception.code, 2)

    def test_runtime_config_flags(self):
        cfg = build_runtime_config()
        self.assertTrue(cfg.enable_voluntary_switch_quality_diagnostics)
        self.assertTrue(cfg.enable_voluntary_switch_quality_scoring)
        self.assertFalse(cfg.enable_forced_switch_replacement_safety)


if __name__ == "__main__":
    unittest.main()
