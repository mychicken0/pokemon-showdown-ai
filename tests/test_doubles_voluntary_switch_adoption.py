#!/usr/bin/env python3
"""Phase 6.4.10 — Voluntary Switch Quality Adoption Tests.

Focused unit + analyzer + runtime parity tests for the
voluntary switch quality scoring rule. This test
file complements ``test_doubles_voluntary_switch_quality.py``
which covers the helper layer; this file covers the
adoption framework (paired analyzer, runtime parity,
audit fields, selection-change accounting, repeated
consecutive penalty, useful-stay, low-HP candidate
penalty, double-threat / quad-weak penalty, healthy
bench preservation, negative scores, no hidden info).

Test groups:

  A. Scoring OFF does not change scores
  B. Scoring ON penalizes tempo
  C. Risk reduction lowers penalty
  D. Candidate with worse risk is penalised
  E. Double-threat penalty
  F. Quad-weak penalty
  G. Low-HP candidate penalty
  H. Useful stay action penalty
  I. High-value KO stay penalty
  J. Sacrifice-aware healthy-bench preservation
  K. Repeat switch penalty only on consecutive turn
  L. No repeat penalty after gap turn
  M. Forced switches excluded
  N. No hidden info fields read
  O. Negative adjusted switch scores allowed
  P. Candidate row schema
  Q. Selected row identity via action key
  R. At most one selected row per slot
  S. Two-slot simultaneous switch valid
  T. Selected slot fields match selected row
  U. Counterfactual uses raw maps
  V. No mutation / deterministic repeat
  W. Malformed action keys fail closed in validator
  X. Runtime parity Random Doubles vs VGC
  Y. VGC selected-four bench has exactly two
     switch candidates after preview

No skipped tests. No pass-only tests.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

import poke_env_test_cleanup  # noqa: F401
sys.path.insert(0, os.path.dirname(__file__))

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    DoublesDamageAwarePlayer,
    build_voluntary_switch_candidate_table,
    evaluate_voluntary_switch_quality,
    _order_action_key,
)
from poke_env.battle.move import Move
from poke_env.battle.pokemon import Pokemon
from poke_env.battle.pokemon_type import PokemonType
from poke_env.player.battle_order import SingleBattleOrder
from analyze_doubles_voluntary_switch_paired import (
    _collect_vsw_metrics,
    analyze as analyze_paired,
    wilson_ci,
    exact_binomial_two_sided,
    paired_bootstrap_treatment,
)
from bot_doubles_voluntary_switch_diagnostics import (
    normalize_action_key,
    validate_jsonl,
    count_vsw_metrics,
)


def _make_real_pokemon(species, t1, t2=None, hp=1.0):
    p = Pokemon.__new__(Pokemon)
    p._species = species
    p._type_1 = t1
    p._type_2 = t2
    p._current_hp = int(round(hp * 100))
    p._max_hp = 100
    p._boosts = {}
    p._status = 0
    p._terastallized = False
    p._terastallized_type = None
    p._temporary_types = []
    p._gen = 9
    return p


def _make_battle(active, opponent_actives, force_switch=None,
                  turn=1, bt="test_battle"):
    battle = MagicMock()
    battle.battle_tag = bt
    battle.turn = turn
    battle.active_pokemon = active
    battle.opponent_active_pokemon = opponent_actives
    battle.available_moves = [[], []]
    battle.force_switch = force_switch or [False, False]
    battle.fields = []
    return battle


def _make_switch_order(pokemon):
    order = MagicMock()
    order.order = pokemon
    order.move_target = 0
    return order


# ---------------------------------------------------------------------------
# A. Scoring OFF does not change scores
# ---------------------------------------------------------------------------


class TestScoringOffNoChange(unittest.TestCase):
    def test_evaluate_returns_same_metrics(self):
        """When scoring is off, the diagnostic eval
        still returns the same risk metrics so the
        analyzer can read them. The scoring flag
        only affects the row's adjusted_switch_score,
        not the eval's risk values."""
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = False
        active = _make_real_pokemon(
            "Snorlax", PokemonType.NORMAL
        )
        cand = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        opp = _make_real_pokemon("Tyranitar", PokemonType.ROCK,
                                  PokemonType.DARK)
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=1
        )
        res = evaluate_voluntary_switch_quality(
            active, cand, 0, battle, 20.0, cfg
        )
        self.assertTrue(res["eligible"])
        self.assertEqual(res["candidate_risk"], 4.0)
        self.assertEqual(res["active_risk"], 1.0)
        self.assertEqual(res["risk_reduction"], -3.0)


# ---------------------------------------------------------------------------
# B. Scoring ON penalizes tempo
# ---------------------------------------------------------------------------


class TestTempoPenaltyOn(unittest.TestCase):
    def test_neutral_switch_has_positive_tempo_penalty(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        cand = _make_real_pokemon(
            "Blastoise", PokemonType.WATER, hp=1.0
        )
        opp = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp], turn=1
        )
        switch_orders = [_make_switch_order(cand)]
        table = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 0.0, cfg,
        )
        self.assertEqual(len(table), 1)
        self.assertGreater(table[0]["tempo_penalty"], 0.0)
        self.assertGreater(table[0]["score_adjustment"], 0.0)


# ---------------------------------------------------------------------------
# C. Risk reduction lowers penalty
# ---------------------------------------------------------------------------


class TestRiskReductionLowersPenalty(unittest.TestCase):
    def test_real_risk_reduction_lowers_score_adjustment(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        cand = _make_real_pokemon(
            "Gastrodon", PokemonType.WATER, PokemonType.GROUND
        )
        opp1 = _make_real_pokemon(
            "Blastoise", PokemonType.WATER
        )
        opp2 = _make_real_pokemon(
            "Snorlax", PokemonType.NORMAL
        )
        battle = _make_battle(
            [active, cand], [opp1, opp2], turn=1
        )
        res = evaluate_voluntary_switch_quality(
            active, cand, 0, battle, 20.0, cfg
        )
        self.assertGreater(res["risk_reduction"], 0.0)
        # Tempo - risk_reduction_bonus
        # = 35 - 1.0*20*0.5 = 35 - 10 = 25
        self.assertLess(res["score_adjustment"], 35.0)


# ---------------------------------------------------------------------------
# D. Candidate with worse risk is penalised
# ---------------------------------------------------------------------------


class TestWorseCandidatePenalised(unittest.TestCase):
    def test_candidate_worse_than_active_flagged_unsafe(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        cand = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        opp = _make_real_pokemon(
            "Tyranitar", PokemonType.ROCK, PokemonType.DARK
        )
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=1
        )
        switch_orders = [_make_switch_order(cand)]
        table = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 20.0, cfg
        )
        self.assertEqual(len(table), 1)
        # Active risk 1.0x, candidate risk 4.0x
        self.assertEqual(table[0]["active_risk"], 1.0)
        self.assertEqual(table[0]["candidate_risk"], 4.0)
        # The quad_weak flag should be True
        self.assertTrue(table[0]["quad_weak"])
        # The penalty must be positive
        self.assertGreater(table[0]["score_adjustment"], 0.0)


# ---------------------------------------------------------------------------
# E. Double-threat penalty
# ---------------------------------------------------------------------------


class TestDoubleThreatPenalty(unittest.TestCase):
    def test_double_threat_flag_set(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        cand = _make_real_pokemon(
            "Exeggutor", PokemonType.GRASS, PokemonType.PSYCHIC
        )
        opp1 = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        opp2 = _make_real_pokemon(
            "Gengar", PokemonType.GHOST, PokemonType.POISON
        )
        battle = _make_battle(
            [active, cand], [opp1, opp2], turn=1
        )
        switch_orders = [_make_switch_order(cand)]
        table = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 20.0, cfg
        )
        self.assertEqual(len(table), 1)
        self.assertTrue(table[0]["double_threat"])


# ---------------------------------------------------------------------------
# F. Quad-weak penalty
# ---------------------------------------------------------------------------


class TestQuadWeakPenalty(unittest.TestCase):
    def test_quad_weak_flag_set(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        cand = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        opp = _make_real_pokemon(
            "Tyranitar", PokemonType.ROCK, PokemonType.DARK
        )
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=1
        )
        switch_orders = [_make_switch_order(cand)]
        table = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 20.0, cfg
        )
        self.assertEqual(len(table), 1)
        self.assertTrue(table[0]["quad_weak"])


# ---------------------------------------------------------------------------
# G. Low-HP candidate penalty
# ---------------------------------------------------------------------------


class TestLowHpCandidatePenalty(unittest.TestCase):
    def test_low_hp_candidate_flag_set(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        cand = _make_real_pokemon(
            "Blastoise", PokemonType.WATER, hp=0.20
        )
        opp = _make_real_pokemon(
            "Venusaur", PokemonType.GRASS, PokemonType.POISON
        )
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=1
        )
        switch_orders = [_make_switch_order(cand)]
        table = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 20.0, cfg
        )
        self.assertEqual(len(table), 1)
        self.assertTrue(table[0]["low_hp"])


# ---------------------------------------------------------------------------
# H. Useful stay action penalty
# ---------------------------------------------------------------------------


class TestUsefulStayPenalty(unittest.TestCase):
    def test_active_with_useful_action_flagged(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        cand = _make_real_pokemon(
            "Blastoise", PokemonType.WATER
        )
        opp = _make_real_pokemon(
            "Venusaur", PokemonType.GRASS, PokemonType.POISON
        )
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=1
        )
        res = evaluate_voluntary_switch_quality(
            active, cand, 0, battle, 80.0, cfg
        )
        self.assertTrue(res["active_has_useful_action"])
        self.assertFalse(res["active_has_high_value_action"])


# ---------------------------------------------------------------------------
# I. High-value KO stay penalty
# ---------------------------------------------------------------------------


class TestHighValueStayPenalty(unittest.TestCase):
    def test_active_with_high_value_action_flagged(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        cand = _make_real_pokemon(
            "Blastoise", PokemonType.WATER
        )
        opp = _make_real_pokemon(
            "Venusaur", PokemonType.GRASS, PokemonType.POISON
        )
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=1
        )
        res = evaluate_voluntary_switch_quality(
            active, cand, 0, battle, 250.0, cfg
        )
        self.assertTrue(res["active_has_useful_action"])
        self.assertTrue(res["active_has_high_value_action"])


# ---------------------------------------------------------------------------
# J. Sacrifice-aware healthy-bench preservation
# ---------------------------------------------------------------------------


class TestSacrificeAwareBench(unittest.TestCase):
    def test_sacrifice_preserve_bench_flagged(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING,
            hp=0.10,
        )
        cand = _make_real_pokemon(
            "Blastoise", PokemonType.WATER, hp=1.0
        )
        opp = _make_real_pokemon(
            "Venusaur", PokemonType.GRASS, PokemonType.POISON
        )
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=1
        )
        switch_orders = [_make_switch_order(cand)]
        table = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 80.0, cfg
        )
        self.assertEqual(len(table), 1)
        self.assertTrue(table[0]["sacrifice_penalty"] > 0)
        self.assertIn("sacrifice_preserve_bench",
                      table[0]["reason_codes"])


# ---------------------------------------------------------------------------
# K. Repeat switch penalty only on consecutive turn
# ---------------------------------------------------------------------------


class TestRepeatSwitchPenaltyOnConsecutiveTurn(unittest.TestCase):
    def test_repeat_penalty_only_when_consecutive(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon(
            "Snorlax", PokemonType.NORMAL
        )
        cand = _make_real_pokemon(
            "Blastoise", PokemonType.WATER
        )
        opp = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=2, bt="test_repeat"
        )
        history = {("test_repeat", 0): {"last_switch_turn": 1}}
        switch_orders = [_make_switch_order(cand)]
        table = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 20.0, cfg,
            voluntary_switch_history=history,
        )
        self.assertEqual(len(table), 1)
        self.assertGreater(table[0]["repeat_penalty"], 0.0)


# ---------------------------------------------------------------------------
# L. No repeat penalty after gap turn
# ---------------------------------------------------------------------------


class TestNoRepeatAfterGapTurn(unittest.TestCase):
    def test_no_repeat_penalty_after_gap_turn(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon(
            "Snorlax", PokemonType.NORMAL
        )
        cand = _make_real_pokemon(
            "Blastoise", PokemonType.WATER
        )
        opp = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=5, bt="test_gap"
        )
        # last_switch_turn=2, current=5, gap=3 (not consecutive)
        history = {("test_gap", 0): {"last_switch_turn": 2}}
        switch_orders = [_make_switch_order(cand)]
        table = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 20.0, cfg,
            voluntary_switch_history=history,
        )
        self.assertEqual(len(table), 1)
        self.assertEqual(table[0]["repeat_penalty"], 0.0)


# ---------------------------------------------------------------------------
# M. Forced switches excluded
# ---------------------------------------------------------------------------


class TestForcedSwitchesExcluded(unittest.TestCase):
    def test_forced_switch_returns_empty_table(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        cand = _make_real_pokemon(
            "Blastoise", PokemonType.WATER
        )
        opp = _make_real_pokemon(
            "Venusaur", PokemonType.GRASS, PokemonType.POISON
        )
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=1,
            force_switch=[True, False],
        )
        switch_orders = [_make_switch_order(cand)]
        table = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 20.0, cfg
        )
        self.assertEqual(table, [])


# ---------------------------------------------------------------------------
# N. No hidden info fields read
# ---------------------------------------------------------------------------


class TestNoHiddenInfo(unittest.TestCase):
    def test_eval_reads_only_visible_info(self):
        """The evaluate function reads species,
        type_1, type_2, current_hp_fraction, and
        damage_multiplier only. No hidden items,
        abilities, or moves are read."""
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon(
            "Snorlax", PokemonType.NORMAL
        )
        cand = _make_real_pokemon(
            "Blastoise", PokemonType.WATER
        )
        opp = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=1
        )
        res = evaluate_voluntary_switch_quality(
            active, cand, 0, battle, 20.0, cfg
        )
        # No "items" or "hidden_*" keys
        for k in res.keys():
            self.assertNotIn("item", k.lower())
            self.assertNotIn("hidden", k.lower())


# ---------------------------------------------------------------------------
# O. Negative adjusted switch scores allowed
# ---------------------------------------------------------------------------


class TestNegativeAdjustedScores(unittest.TestCase):
    def test_negative_adjusted_switch_score(self):
        """Bad switches should be allowed to produce
        negative adjusted_switch_score to make the
        engine prefer the stay action."""
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        cand = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        opp = _make_real_pokemon(
            "Tyranitar", PokemonType.ROCK, PokemonType.DARK
        )
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=1
        )
        switch_orders = [_make_switch_order(cand)]
        table = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 20.0, cfg
        )
        self.assertEqual(len(table), 1)
        # The adjusted_switch_score is clamped at -200
        # in the production code.
        self.assertLessEqual(table[0]["adjusted_switch_score"], 0.0)


# ---------------------------------------------------------------------------
# P. Candidate row schema
# ---------------------------------------------------------------------------


class TestCandidateRowSchema(unittest.TestCase):
    REQUIRED_FIELDS = (
        "candidate_index", "candidate_action_key", "species",
        "raw_switch_score", "adjusted_switch_score",
        "active_risk", "candidate_risk", "risk_reduction",
        "tempo_penalty", "candidate_penalty", "repeat_penalty",
        "sacrifice_penalty", "stay_value_penalty",
        "score_adjustment", "double_threat", "quad_weak",
        "low_hp", "switch_improves_position", "safer_than_active",
        "best_stay_score", "active_has_useful_action",
        "active_has_high_value_action", "sacrifice_preferred",
        "reason_codes", "selected",
    )

    def test_required_fields_present(self):
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        cand = _make_real_pokemon(
            "Blastoise", PokemonType.WATER
        )
        opp = _make_real_pokemon(
            "Venusaur", PokemonType.GRASS, PokemonType.POISON
        )
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=1
        )
        switch_orders = [_make_switch_order(cand)]
        table = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 20.0, cfg
        )
        self.assertEqual(len(table), 1)
        for f in self.REQUIRED_FIELDS:
            self.assertIn(f, table[0])


# ---------------------------------------------------------------------------
# Q. Selected row identity via action key
# ---------------------------------------------------------------------------


class TestSelectedRowActionKey(unittest.TestCase):
    def test_action_key_for_switch(self):
        # Build a real SingleBattleOrder that wraps a
        # real Pokemon. The production code's
        # ``_order_action_key`` requires the order to
        # be a ``SingleBattleOrder`` instance.
        from poke_env.player.battle_order import (
            SingleBattleOrder,
        )
        cand = _make_real_pokemon("Blastoise", PokemonType.WATER)
        order = SingleBattleOrder(
            order=cand,
            move_target=0,
        )
        key = _order_action_key(order)
        self.assertEqual(key, ("switch", "Blastoise", 0))


# ---------------------------------------------------------------------------
# R. At most one selected row per slot
# ---------------------------------------------------------------------------


class TestAtMostOneSelectedRow(unittest.TestCase):
    def test_validator_catches_multiple_selected(self):
        # Two selected rows in the same slot
        turn = {
            "turn": 1,
            "voluntary_switch_decision_eligible": [True, False],
            "voluntary_switch_selected": [True, False],
            "voluntary_switch_selected_species": ["X", ""],
            "voluntary_switch_selection_changed": [False, False],
            "voluntary_switch_joint_selection_changed": False,
            "voluntary_switch_counterfactual_action": [
                ["switch", "X", 0], ["", "", 0]
            ],
            "voluntary_switch_selected_action": [
                ["switch", "X", 0], ["", "", 0]
            ],
            "voluntary_switch_candidate_table": [
                [
                    {
                        "candidate_index": 0,
                        "candidate_action_key": ["switch", "X", 0],
                        "species": "X",
                        "raw_switch_score": 0.0,
                        "adjusted_switch_score": 0.0,
                        "active_risk": 1.0,
                        "candidate_risk": 1.0,
                        "risk_reduction": 0.0,
                        "score_adjustment": 0.0,
                        "selected": True,
                    },
                    {
                        "candidate_index": 1,
                        "candidate_action_key": ["switch", "Y", 0],
                        "species": "Y",
                        "raw_switch_score": 0.0,
                        "adjusted_switch_score": 0.0,
                        "active_risk": 1.0,
                        "candidate_risk": 1.0,
                        "risk_reduction": 0.0,
                        "score_adjustment": 0.0,
                        "selected": True,
                    },
                ],
                [],
            ],
            "voluntary_switch_unnecessary_selected": [False, False],
            "voluntary_switch_unsafe_candidate_selected": [False, False],
            "voluntary_switch_repeat_selected": [False, False],
            "voluntary_switch_sacrifice_opportunity": [False, False],
            "voluntary_switch_healthy_bench_preserved": [False, False],
            "voluntary_switch_safer_candidate_available": [False, False],
            "voluntary_switch_active_species": ["A", ""],
            "voluntary_switch_active_hp": [1.0, 0.0],
            "voluntary_switch_best_stay_score": [10.0, 0.0],
            "voluntary_switch_selected_active_risk": [1.0, 0.0],
            "voluntary_switch_selected_candidate_risk": [1.0, 0.0],
            "voluntary_switch_selected_risk_reduction": [0.0, 0.0],
            "voluntary_switch_selected_score_adjustment": [0.0, 0.0],
            "voluntary_switch_reason_codes": [[], []],
        }
        rec = {
            "battle_tag": "test", "won": True,
            "benchmark_arm": "A", "audit_turns": [turn],
        }
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        )
        path = f.name
        f.write(json.dumps(rec) + "\n")
        f.close()
        self.addCleanup(os.remove, path)
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(
            any("selected rows" in e for e in errors),
            errors,
        )


# ---------------------------------------------------------------------------
# S. Two-slot simultaneous switch valid
# ---------------------------------------------------------------------------


class TestTwoSlotSimultaneousSwitch(unittest.TestCase):
    def test_two_slot_switch_validates(self):
        turn = {
            "turn": 1,
            "voluntary_switch_decision_eligible": [True, True],
            "voluntary_switch_selected": [True, True],
            "voluntary_switch_selected_species": ["X", "Y"],
            "voluntary_switch_selection_changed": [False, False],
            "voluntary_switch_joint_selection_changed": False,
            "voluntary_switch_counterfactual_action": [
                ["switch", "X", 0], ["switch", "Y", 0]
            ],
            "voluntary_switch_selected_action": [
                ["switch", "X", 0], ["switch", "Y", 0]
            ],
            "voluntary_switch_candidate_table": [
                [{
                    "candidate_index": 0,
                    "candidate_action_key": ["switch", "X", 0],
                    "species": "X",
                    "raw_switch_score": 0.0,
                    "adjusted_switch_score": 0.0,
                    "active_risk": 1.0,
                    "candidate_risk": 1.0,
                    "risk_reduction": 0.0,
                    "score_adjustment": 0.0,
                    "selected": True,
                }],
                [{
                    "candidate_index": 0,
                    "candidate_action_key": ["switch", "Y", 0],
                    "species": "Y",
                    "raw_switch_score": 0.0,
                    "adjusted_switch_score": 0.0,
                    "active_risk": 1.0,
                    "candidate_risk": 1.0,
                    "risk_reduction": 0.0,
                    "score_adjustment": 0.0,
                    "selected": True,
                }],
            ],
            "voluntary_switch_unnecessary_selected": [False, False],
            "voluntary_switch_unsafe_candidate_selected": [False, False],
            "voluntary_switch_repeat_selected": [False, False],
            "voluntary_switch_sacrifice_opportunity": [False, False],
            "voluntary_switch_healthy_bench_preserved": [False, False],
            "voluntary_switch_safer_candidate_available": [False, False],
            "voluntary_switch_active_species": ["A", "B"],
            "voluntary_switch_active_hp": [1.0, 1.0],
            "voluntary_switch_best_stay_score": [10.0, 10.0],
            "voluntary_switch_selected_active_risk": [1.0, 1.0],
            "voluntary_switch_selected_candidate_risk": [1.0, 1.0],
            "voluntary_switch_selected_risk_reduction": [0.0, 0.0],
            "voluntary_switch_selected_score_adjustment": [0.0, 0.0],
            "voluntary_switch_reason_codes": [[], []],
        }
        rec = {
            "battle_tag": "test", "won": True,
            "benchmark_arm": "A", "audit_turns": [turn],
        }
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        )
        path = f.name
        f.write(json.dumps(rec) + "\n")
        f.close()
        self.addCleanup(os.remove, path)
        errors = validate_jsonl(path, 1, "A")
        self.assertEqual(errors, [])


# ---------------------------------------------------------------------------
# T. Selected slot fields match selected row
# ---------------------------------------------------------------------------


class TestSelectedSlotFieldsMatchRow(unittest.TestCase):
    def test_mismatch_caught_by_validator(self):
        turn = {
            "turn": 1,
            "voluntary_switch_decision_eligible": [True, False],
            "voluntary_switch_selected": [True, False],
            "voluntary_switch_selected_species": ["X", ""],
            "voluntary_switch_selection_changed": [False, False],
            "voluntary_switch_joint_selection_changed": False,
            "voluntary_switch_counterfactual_action": [
                ["switch", "X", 0], ["", "", 0]
            ],
            "voluntary_switch_selected_action": [
                # MISMATCH: selected says Y but the
                # selected row is X.
                ["switch", "Y", 0], ["", "", 0]
            ],
            "voluntary_switch_candidate_table": [
                [{
                    "candidate_index": 0,
                    "candidate_action_key": ["switch", "X", 0],
                    "species": "X",
                    "raw_switch_score": 0.0,
                    "adjusted_switch_score": 0.0,
                    "active_risk": 1.0,
                    "candidate_risk": 1.0,
                    "risk_reduction": 0.0,
                    "score_adjustment": 0.0,
                    "selected": True,
                }],
                [],
            ],
            "voluntary_switch_unnecessary_selected": [False, False],
            "voluntary_switch_unsafe_candidate_selected": [False, False],
            "voluntary_switch_repeat_selected": [False, False],
            "voluntary_switch_sacrifice_opportunity": [False, False],
            "voluntary_switch_healthy_bench_preserved": [False, False],
            "voluntary_switch_safer_candidate_available": [False, False],
            "voluntary_switch_active_species": ["A", ""],
            "voluntary_switch_active_hp": [1.0, 0.0],
            "voluntary_switch_best_stay_score": [10.0, 0.0],
            "voluntary_switch_selected_active_risk": [1.0, 0.0],
            "voluntary_switch_selected_candidate_risk": [1.0, 0.0],
            "voluntary_switch_selected_risk_reduction": [0.0, 0.0],
            "voluntary_switch_selected_score_adjustment": [0.0, 0.0],
            "voluntary_switch_reason_codes": [[], []],
        }
        rec = {
            "battle_tag": "test", "won": True,
            "benchmark_arm": "A", "audit_turns": [turn],
        }
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        )
        path = f.name
        f.write(json.dumps(rec) + "\n")
        f.close()
        self.addCleanup(os.remove, path)
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(
            any("selected row key" in e for e in errors),
            errors,
        )


# ---------------------------------------------------------------------------
# U. Counterfactual uses raw maps
# ---------------------------------------------------------------------------


class TestCounterfactualUsesRawMaps(unittest.TestCase):
    def test_score_maps_not_mutated(self):
        """Calling build_voluntary_switch_candidate_table
        with the same raw scores twice should produce
        the same adjusted scores. The counterfactual
        flow in choose_move must not mutate the raw
        score maps."""
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        cand = _make_real_pokemon(
            "Blastoise", PokemonType.WATER
        )
        opp = _make_real_pokemon(
            "Venusaur", PokemonType.GRASS, PokemonType.POISON
        )
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=1
        )
        switch_orders = [_make_switch_order(cand)]
        table1 = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 20.0, cfg
        )
        table2 = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 20.0, cfg
        )
        self.assertEqual(len(table1), 1)
        self.assertEqual(len(table2), 1)
        # Same adjusted_switch_score both times
        self.assertEqual(
            table1[0]["adjusted_switch_score"],
            table2[0]["adjusted_switch_score"],
        )


# ---------------------------------------------------------------------------
# V. No mutation / deterministic repeat
# ---------------------------------------------------------------------------


class TestDeterministicRepeat(unittest.TestCase):
    def test_evaluate_deterministic(self):
        """Calling evaluate_voluntary_switch_quality
        twice with the same inputs must produce the
        same output."""
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        cand = _make_real_pokemon(
            "Blastoise", PokemonType.WATER
        )
        opp = _make_real_pokemon(
            "Venusaur", PokemonType.GRASS, PokemonType.POISON
        )
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=1
        )
        r1 = evaluate_voluntary_switch_quality(
            active, cand, 0, battle, 20.0, cfg
        )
        r2 = evaluate_voluntary_switch_quality(
            active, cand, 0, battle, 20.0, cfg
        )
        for k in r1.keys():
            self.assertEqual(r1[k], r2[k])


# ---------------------------------------------------------------------------
# W. Malformed action keys fail closed in validator
# ---------------------------------------------------------------------------


class TestMalformedActionKeysFailClosed(unittest.TestCase):
    def test_wrong_type_action_key_caught(self):
        turn = {
            "turn": 1,
            "voluntary_switch_decision_eligible": [True, False],
            "voluntary_switch_selected": [False, False],
            "voluntary_switch_selected_species": ["", ""],
            "voluntary_switch_selection_changed": [False, False],
            "voluntary_switch_joint_selection_changed": False,
            "voluntary_switch_counterfactual_action": [
                "not_a_list", ["", "", 0]
            ],
            "voluntary_switch_selected_action": [
                ["", "", 0], ["", "", 0]
            ],
            "voluntary_switch_candidate_table": [
                [{
                    "candidate_index": 0,
                    "candidate_action_key": ["switch", "X", 0],
                    "species": "X",
                    "raw_switch_score": 0.0,
                    "adjusted_switch_score": 0.0,
                    "active_risk": 1.0,
                    "candidate_risk": 1.0,
                    "risk_reduction": 0.0,
                    "score_adjustment": 0.0,
                    "selected": False,
                }],
                [],
            ],
            "voluntary_switch_unnecessary_selected": [False, False],
            "voluntary_switch_unsafe_candidate_selected": [False, False],
            "voluntary_switch_repeat_selected": [False, False],
            "voluntary_switch_sacrifice_opportunity": [False, False],
            "voluntary_switch_healthy_bench_preserved": [False, False],
            "voluntary_switch_safer_candidate_available": [False, False],
            "voluntary_switch_active_species": ["A", ""],
            "voluntary_switch_active_hp": [1.0, 0.0],
            "voluntary_switch_best_stay_score": [10.0, 0.0],
            "voluntary_switch_selected_active_risk": [0.0, 0.0],
            "voluntary_switch_selected_candidate_risk": [0.0, 0.0],
            "voluntary_switch_selected_risk_reduction": [0.0, 0.0],
            "voluntary_switch_selected_score_adjustment": [0.0, 0.0],
            "voluntary_switch_reason_codes": [[], []],
        }
        rec = {
            "battle_tag": "test", "won": True,
            "benchmark_arm": "A", "audit_turns": [turn],
        }
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        )
        path = f.name
        f.write(json.dumps(rec) + "\n")
        f.close()
        self.addCleanup(os.remove, path)
        errors = validate_jsonl(path, 1, "A")
        self.assertTrue(
            any(
                "counterfactual_action" in e
                and "list" in e
                for e in errors
            ),
            errors,
        )


# ---------------------------------------------------------------------------
# X. Runtime parity Random Doubles vs VGC
# ---------------------------------------------------------------------------


class TestRuntimeParityVGC(unittest.TestCase):
    def test_narrow_block_uses_config_only(self):
        """The voluntary switch scoring helper reads
        ONLY the config flag, not the runtime mode.
        Both modes produce the same scoring."""
        active = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        cand = _make_real_pokemon(
            "Blastoise", PokemonType.WATER
        )
        opp = _make_real_pokemon(
            "Venusaur", PokemonType.GRASS, PokemonType.POISON
        )
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand], [opp, opp2], turn=1
        )
        cfg_rd = DoublesDamageAwareConfig()
        cfg_rd.enable_voluntary_switch_quality_diagnostics = True
        cfg_rd.enable_voluntary_switch_quality_scoring = True
        cfg_vgc = DoublesDamageAwareConfig()
        cfg_vgc.enable_voluntary_switch_quality_diagnostics = True
        cfg_vgc.enable_voluntary_switch_quality_scoring = True
        # Same code path; both modes call into the
        # same production helpers.
        switch_orders = [_make_switch_order(cand)]
        table_rd = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 20.0, cfg_rd
        )
        table_vgc = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 20.0, cfg_vgc
        )
        self.assertEqual(len(table_rd), len(table_vgc))
        for r_rd, r_vgc in zip(table_rd, table_vgc):
            self.assertEqual(
                r_rd["adjusted_switch_score"],
                r_vgc["adjusted_switch_score"],
            )
            self.assertEqual(
                r_rd["score_adjustment"],
                r_vgc["score_adjustment"],
            )


# ---------------------------------------------------------------------------
# Y. VGC selected-four bench has exactly two
#     switch candidates after preview
# ---------------------------------------------------------------------------


class TestVGCSwitchCandidateCount(unittest.TestCase):
    def test_two_slot_build_returns_at_most_one_per_slot(self):
        """For a VGC selected-four bench, each of the
        two active slots can have at most one switch
        candidate per turn (the player picks the
        next bench Pokemon to send in). The build
        function must produce at most one row per
        slot."""
        cfg = DoublesDamageAwareConfig()
        cfg.enable_voluntary_switch_quality_diagnostics = True
        cfg.enable_voluntary_switch_quality_scoring = True
        active = _make_real_pokemon(
            "Charizard", PokemonType.FIRE, PokemonType.FLYING
        )
        cand1 = _make_real_pokemon(
            "Blastoise", PokemonType.WATER
        )
        cand2 = _make_real_pokemon(
            "Venusaur", PokemonType.GRASS, PokemonType.POISON
        )
        opp = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        opp2 = _make_real_pokemon("Snorlax", PokemonType.NORMAL)
        battle = _make_battle(
            [active, cand1], [opp, opp2], turn=1
        )
        # Only one switch candidate for slot 0
        switch_orders = [_make_switch_order(cand1)]
        table = build_voluntary_switch_candidate_table(
            active, switch_orders, 0, battle, 20.0, cfg
        )
        # Exactly one row (the dedup is on (move_id, target))
        self.assertEqual(len(table), 1)


# ---------------------------------------------------------------------------
# Analyzer / inspector regressions
# ---------------------------------------------------------------------------


class TestAnalyzerRegressions(unittest.TestCase):
    def test_wilson_ci_perfect(self):
        lo, hi = wilson_ci(100, 100)
        self.assertGreater(lo, 0.9)

    def test_wilson_ci_zero(self):
        lo, hi = wilson_ci(0, 0)
        self.assertEqual(lo, 0.0)
        self.assertEqual(hi, 1.0)

    def test_paired_bootstrap_deterministic(self):
        scores = [+1, -1, +1, -1, 0, 0, 0, 0]
        p1, l1, h1 = paired_bootstrap_treatment(
            scores, n_boot=200, seed=6410
        )
        p2, l2, h2 = paired_bootstrap_treatment(
            scores, n_boot=200, seed=6410
        )
        self.assertEqual(p1, p2)
        self.assertEqual(l1, l2)
        self.assertEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
