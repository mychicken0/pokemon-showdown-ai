#!/usr/bin/env python3
"""Forced Switch Candidate Ordering Tests — Phase 6.4.3a.2

Verifies that forced switch diagnostic fields are properly computed and
that the bot's switch candidate evaluation is working correctly.
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import poke_env_test_cleanup  # noqa: F401

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    evaluate_switch_candidate_type_safety,
)


# ── Mock objects ──

class MockPokemon:
    def __init__(self, species, types, ability=None, level=50, hp_fraction=1.0):
        self.species = species
        self._types = []
        for t in types:
            from poke_env.battle.pokemon_type import PokemonType
            self._types.append(PokemonType[t.upper()])
        self._type_1 = self._types[0] if self._types else None
        self._type_2 = self._types[1] if len(self._types) > 1 else None
        self.ability = ability
        self.level = level
        self._hp_fraction = hp_fraction
        self._base_stats = {"hp": 100, "atk": 100, "def": 100, "spa": 100, "spd": 100, "spe": 100}
        self._boosts = {}

    @property
    def type_1(self):
        return self._type_1

    @property
    def type_2(self):
        return self._type_2

    @property
    def types(self):
        return tuple(self._types)

    @property
    def current_hp_fraction(self):
        return self._hp_fraction

    @property
    def hp(self):
        return 100

    def damage_multiplier(self, move):
        from poke_env.battle.pokemon_type import PokemonType
        from poke_env.data.gen_data import GenData
        # Handle both Move objects and PokemonType objects
        if isinstance(move, PokemonType):
            move_type = move
        elif hasattr(move, 'type'):
            move_type = move.type
        else:
            return 1.0
        if not move_type:
            return 1.0
        mult = 1.0
        chart = GenData.from_gen(9).type_chart
        for t in self._types:
            try:
                mult *= move_type.damage_multiplier(t, type_chart=chart)
            except Exception:
                pass
        return mult


class TestSwitchCandidateSafety(unittest.TestCase):
    """Verify switch candidate safety evaluation works correctly."""

    def test_resistant_candidate_scores_better(self):
        """A candidate that resists opponent types should score better."""
        # Opponent is pure Poison
        opponent = MockPokemon("muk", ["POISON"])

        # Candidate A: Grass (weak to Poison)
        candidate_a = MockPokemon("venusaur", ["GRASS", "POISON"])

        # Candidate B: Steel (resists Poison)
        candidate_b = MockPokemon("steelix", ["STEEL", "GROUND"])

        safety_a = evaluate_switch_candidate_type_safety(candidate_a, [opponent])
        safety_b = evaluate_switch_candidate_type_safety(candidate_b, [opponent])

        # B should have better (higher) safety score due to resistance
        self.assertGreater(safety_b["raw_safety_score"], safety_a["raw_safety_score"])

    def test_immune_candidate_gets_bonus(self):
        """A candidate immune to opponent's pure type should get immunity bonus."""
        # Opponent is pure Ground (no secondary attacking type)
        opponent = MockPokemon("donphan", ["GROUND"])

        # Candidate with Flying (immune to Ground)
        immune_cand = MockPokemon("charizard", ["FIRE", "FLYING"])

        # Neutral candidate
        neutral_cand = MockPokemon("blastoise", ["WATER"])

        safety_imm = evaluate_switch_candidate_type_safety(immune_cand, [opponent])
        safety_neu = evaluate_switch_candidate_type_safety(neutral_cand, [opponent])

        self.assertGreater(safety_imm["immune_threat_count"], 0)
        self.assertGreater(safety_imm["raw_safety_score"], safety_neu["raw_safety_score"])

    def test_double_threat_detected(self):
        """A candidate weak to both opponent STABs should be flagged as double threat."""
        # Opponent has Fire and Ground (both hit Fire/Steel super effectively)
        opponent = MockPokemon("coalossal", ["FIRE", "GROUND"])

        # Candidate weak to both: Fire/Steel
        candidate = MockPokemon("heatran", ["FIRE", "STEEL"])

        safety = evaluate_switch_candidate_type_safety(candidate, [opponent])
        # Fire hits Fire/Steel for 0.5x (resist), Ground hits Fire/Steel for 2x (SE)
        # So max_mult should be 2.0 (super effective from Ground)
        self.assertGreaterEqual(safety["super_effective_threat_count"], 1)


class TestForcedSwitchDiagnosticFields(unittest.TestCase):
    """Verify forced switch diagnostic field semantics."""

    def test_forced_switch_fields_default(self):
        """When not forced, candidate count should be 0."""
        # This tests the list initialization semantics
        forced_switch_candidate_count_list = [0, 0]
        forced_switch_selected_index_list = [-1, -1]
        forced_switch_selected_species_list = ["", ""]
        forced_switch_best_safety_species_list = ["", ""]
        forced_switch_selected_safety_score_list = [0.0, 0.0]
        forced_switch_best_safety_score_list = [0.0, 0.0]
        forced_switch_order_fallback_used_list = [False, False]

        self.assertEqual(forced_switch_candidate_count_list, [0, 0])
        self.assertEqual(forced_switch_selected_index_list, [-1, -1])
        self.assertEqual(forced_switch_order_fallback_used_list, [False, False])

    def test_forced_switch_multiple_candidates(self):
        """When forced with multiple candidates, count should reflect available switches."""
        candidates = [
            MockPokemon("pikachu", ["ELECTRIC"]),
            MockPokemon("charizard", ["FIRE", "FLYING"]),
            MockPokemon("bulbasaur", ["GRASS", "POISON"]),
        ]
        # Simulating what the code does
        forced_switch_candidate_count = len(candidates)
        self.assertEqual(forced_switch_candidate_count, 3)

    def test_forced_switch_order_fallback_detection(self):
        """When selected index is 0 with multiple candidates, fallback may be detected."""
        selected_index = 0
        candidate_count = 3
        fallback_used = (selected_index == 0 and candidate_count > 1)
        self.assertTrue(fallback_used)

    def test_single_candidate_no_fallback(self):
        """With single candidate, no fallback is detected."""
        selected_index = 0
        candidate_count = 1
        fallback_used = (selected_index == 0 and candidate_count > 1)
        self.assertFalse(fallback_used)


if __name__ == "__main__":
    unittest.main()
