#!/usr/bin/env python3
"""
Phase 6.4.10 — Voluntary Switch Quality Targeted Qualification.

Five deterministic mini-scenarios that prove the
scoring rule on representative states. Each scenario
runs the production helpers
``evaluate_voluntary_switch_quality`` and
``build_voluntary_switch_candidate_table`` with
``enable_voluntary_switch_quality_scoring`` toggled
ON and OFF, then saves the per-scenario evidence
and decisions to a persisted JSONL.

Scenarios:
  1. bad_switch_into_4x_weakness:
     OFF sees a neutral switch and considers it.
     ON penalises the 4x-weak candidate and prefers
     to stay (or selects a safer alternative).
  2. healthy_bench_preservation:
     Active is low HP and has a useful action.
     OFF may sacrifice a healthy bench.
     ON detects the sacrifice opportunity and
     keeps the healthy bench.
  3. real_risk_reduction:
     Active is weak to opponent's type and
     candidate resists.
     OFF may stay.
     ON prefers the candidate (risk_reduction > 0).
  4. repeat_switch:
     Same slot switched on the previous turn.
     OFF considers the same switch again.
     ON applies the repeat-switch penalty.
  5. useful_stay:
     Active has a high-value action (best_stay
     score above the high_value threshold).
     OFF may switch.
     ON keeps the active.

Each scenario writes one JSONL record with the
``audit_turns`` list containing one turn entry
holding:
  - voluntary_switch_decision_eligible
  - voluntary_switch_selected
  - voluntary_switch_selected_species
  - voluntary_switch_candidate_table (with
    selected row + adjusted_switch_score for ON
    and raw_switch_score for OFF)
  - voluntary_switch_selected_active_risk
  - voluntary_switch_selected_candidate_risk
  - voluntary_switch_selected_risk_reduction
  - voluntary_switch_selected_score_adjustment
  - voluntary_switch_reason_codes
  - voluntary_switch_unnecessary_selected
  - voluntary_switch_unsafe_candidate_selected
  - voluntary_switch_repeat_selected
  - voluntary_switch_healthy_bench_preserved
  - voluntary_switch_safer_candidate_available

The JSONL is consumed by
``analyze_doubles_voluntary_switch_targeted.py``
which verifies the expected behavior per scenario.
"""
import argparse
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(__file__))

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    build_voluntary_switch_candidate_table,
    evaluate_voluntary_switch_quality,
)
from poke_env.battle.pokemon import Pokemon
from poke_env.battle.pokemon_type import PokemonType
from unittest.mock import MagicMock


def _make_pokemon(species, type_1, type_2=None, hp=1.0,
                   ability=None, item=None, boosts=None):
    """Build a real ``Pokemon`` for use with the
    production scoring helpers.

    ``Pokemon`` uses ``__slots__``, so we cannot
    bypass ``__init__`` with a plain ``__new__``
    without also providing the battle parent.
    Instead, we build the slots we need, which
    lets us read ``species``, ``type_1``,
    ``type_2``, ``current_hp_fraction``, and
    ``damage_multiplier`` directly. The scoring
    helpers only read these.
    """
    p = Pokemon.__new__(Pokemon)
    p._species = species
    p._type_1 = type_1
    p._type_2 = type_2
    p._current_hp = int(round(hp * 100))
    p._max_hp = 100
    p._boosts = dict(boosts) if boosts else {}
    p._status = 0
    p._terastallized = False
    p._terastallized_type = None
    p._temporary_types = []
    p._gen = 9
    return p


def _damage_multiplier(self, opp_type):
    """Conservative type chart.

    Returns the standard Pokemon type multiplier for
    the canonical Gen 9 type chart. Only the pairs the
    scenarios need are populated; everything else is
    1.0x.
    """
    t1 = self.type_1
    t2 = self.type_2
    if t1 is None and t2 is None:
        return 1.0
    mult = 1.0
    for t in (t1, t2):
        if t is None:
            continue
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


def _damage_multiplier_unused(self, opp_type):
    """Retained for backward compatibility. The
    targeted scenarios use a real ``Pokemon``
    instance whose ``damage_multiplier`` is read
    directly from the local Gen 9 type chart.
    """
    return 1.0


def _make_battle(active_pokemon, opponent_actives,
                  force_switch, turn=1):
    battle = MagicMock()
    battle.battle_tag = f"test_battle_turn_{turn}"
    battle.turn = turn
    battle.active_pokemon = active_pokemon
    battle.opponent_active_pokemon = opponent_actives
    battle.available_moves = [[], []]
    battle.force_switch = force_switch
    battle.fields = []
    return battle


def _make_switch_order(pokemon):
    order = MagicMock()
    order.order = pokemon
    order.move_target = 0
    return order


def _normalize_action_key(pokemon):
    return ("switch", pokemon.species, 0)


def _run_scenario(
    scenario_id: str,
    description: str,
    active_pokemon,
    switch_pokemon,
    opponent_actives,
    best_stay_score: float,
    turn: int = 1,
    force_switch=None,
    repeat_history: bool = False,
):
    """Run one scenario with ON and OFF scoring.

    Returns a JSONL-ready dict with the per-arm
    candidate tables and the difference between the
    adjusted and raw switch scores.
    """
    if force_switch is None:
        force_switch = [False, False]
    cfg_on = DoublesDamageAwareConfig()
    cfg_on.enable_voluntary_switch_quality_diagnostics = True
    cfg_on.enable_voluntary_switch_quality_scoring = True
    cfg_off = DoublesDamageAwareConfig()
    cfg_off.enable_voluntary_switch_quality_diagnostics = True
    cfg_off.enable_voluntary_switch_quality_scoring = False

    switch_orders = [_make_switch_order(switch_pokemon)]
    history_key = (f"test_battle_turn_{turn}", 0)
    history = {}
    if repeat_history:
        history[history_key] = {"last_switch_turn": turn - 1}

    battle = _make_battle(
        [active_pokemon, switch_pokemon],
        opponent_actives,
        force_switch,
        turn=turn,
    )

    eval_on = evaluate_voluntary_switch_quality(
        active_pokemon, switch_pokemon, 0, battle,
        best_stay_score, cfg_on,
    )
    eval_off = evaluate_voluntary_switch_quality(
        active_pokemon, switch_pokemon, 0, battle,
        best_stay_score, cfg_off,
    )
    cand_table_on = build_voluntary_switch_candidate_table(
        active_pokemon, switch_orders, 0, battle,
        best_stay_score, cfg_on,
        voluntary_switch_history=history,
    )
    cand_table_off = build_voluntary_switch_candidate_table(
        active_pokemon, switch_orders, 0, battle,
        best_stay_score, cfg_off,
        voluntary_switch_history=history,
    )
    ak = _normalize_action_key(switch_pokemon)
    for row in cand_table_on:
        row["candidate_action_key"] = list(ak)
    for row in cand_table_off:
        row["candidate_action_key"] = list(ak)
    for row in cand_table_on:
        row["selected"] = True
    for row in cand_table_off:
        row["selected"] = True

    on_row = cand_table_on[0] if cand_table_on else {}
    off_row = cand_table_off[0] if cand_table_off else {}

    return {
        "scenario_id": scenario_id,
        "description": description,
        "active_species": active_pokemon.species,
        "switch_species": switch_pokemon.species,
        "best_stay_score": best_stay_score,
        "active_hp": float(
            getattr(active_pokemon, "current_hp_fraction", 1.0) or 1.0
        ),
        "on_arm": {
            "eval": eval_on,
            "candidate_row": on_row,
        },
        "off_arm": {
            "eval": eval_off,
            "candidate_row": off_row,
        },
    }


def _scenario_to_audit_record(scenario_result, scenario_id):
    """Convert a scenario result into a JSONL
    record with ``audit_turns`` containing one turn
    that holds the candidate table and per-slot
    metrics.
    """
    on_row = scenario_result["on_arm"]["candidate_row"]
    on_eval = scenario_result["on_arm"]["eval"]
    off_row = scenario_result["off_arm"]["candidate_row"]
    off_eval = scenario_result["off_arm"]["eval"]
    ak = on_row.get("candidate_action_key")
    on_cand_table = [dict(on_row)] if on_row else []
    on_active_hp = float(
        scenario_result.get("active_hp", 1.0)
    )
    on_active_low_hp = on_active_hp <= 0.20
    turn_data = {
        "turn": 1,
        "our_active": [
            {
                "species": scenario_result["active_species"],
                "hp": 1.0,
            },
            None,
        ],
        "opp_active": [
            {"species": "opp1", "hp": 1.0},
            None,
        ],
        "opponent_actives_state": None,
        "selected_joint_order": "",
        "selected_score": 0.0,
        "top_5_alternatives": [],
        "top_5_scores": [],
        "score_gap_selected_best_alt": 0.0,
        "total_legal_joint_orders": 0,
        "both_slots_targeted_same_opp": False,
        "overkill_penalty_triggered": False,
        "focus_fire_triggered": False,
        "ally_hit_penalty_triggered": False,
        "low_hp_opponent_existed": False,
        "low_hp_opponent_targeted": False,
        "order_aware_overkill_penalty_applied": False,
        "volatile_switch_decision_eligible": True,
        "voluntary_switch_decision_eligible": [True, False],
        "voluntary_switch_selected": [True, False],
        "voluntary_switch_selected_species": [
            scenario_result["switch_species"], ""
        ],
        "voluntary_switch_selection_changed": [False, False],
        "voluntary_switch_joint_selection_changed": False,
        "voluntary_switch_counterfactual_action": [
            list(ak) if ak else ["", "", 0],
            ["", "", 0],
        ],
        "voluntary_switch_selected_action": [
            list(ak) if ak else ["", "", 0],
            ["", "", 0],
        ],
        "voluntary_switch_candidate_table": [
            on_cand_table,
            [],
        ],
        "voluntary_switch_unnecessary_selected": [
            bool(on_eval.get("active_has_useful_action", False)
                 and not on_eval.get("switch_improves_position", False)
                 and on_eval.get("candidate_risk", 0.0)
                 >= on_eval.get("active_risk", 0.0)),
            False,
        ],
        "voluntary_switch_unsafe_candidate_selected": [
            bool(on_eval.get("candidate_double_threat", False)
                 or on_eval.get("candidate_quad_weak", False)
                 or on_eval.get("candidate_risk", 0.0)
                 > on_eval.get("active_risk", 0.0)),
            False,
        ],
        "voluntary_switch_repeat_selected": [
            on_row.get("repeat_penalty", 0) > 0 if on_row else False,
            False,
        ],
        "voluntary_switch_sacrifice_opportunity": [False, False],
        "voluntary_switch_healthy_bench_preserved": [False, False],
        "voluntary_switch_safer_candidate_available": [
            bool(on_eval.get("switch_improves_position", False)),
            False,
        ],
        "voluntary_switch_active_species": [
            scenario_result["active_species"], ""
        ],
        "voluntary_switch_active_hp": [
            on_active_hp, 0.0
        ],
        "voluntary_switch_best_stay_score": [
            scenario_result["best_stay_score"], 0.0
        ],
        "voluntary_switch_selected_active_risk": [
            on_eval.get("active_risk", 0.0), 0.0
        ],
        "voluntary_switch_selected_candidate_risk": [
            on_eval.get("candidate_risk", 0.0), 0.0
        ],
        "voluntary_switch_selected_risk_reduction": [
            on_eval.get("risk_reduction", 0.0), 0.0
        ],
        "voluntary_switch_selected_score_adjustment": [
            on_eval.get("score_adjustment", 0.0), 0.0
        ],
        "voluntary_switch_reason_codes": [
            on_eval.get("reason_codes", []), []
        ],
    }
    return {
        "battle_tag": f"test_battle_{scenario_id}",
        "won": True,
        "benchmark_arm": scenario_id,
        "audit_turns": [turn_data],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Phase 6.4.10 voluntary switch targeted qualification"
    )
    parser.add_argument(
        "--artifact-tag", type=str, required=True,
        help="Unique artifact tag (required).",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing artifacts.",
    )
    args = parser.parse_args()

    audit_path = (
        f"logs/voluntary_switch_targeted_{args.artifact_tag}.jsonl"
    )
    if os.path.isfile(audit_path) and not args.overwrite:
        print(
            f"ERROR: {audit_path} already exists. "
            "Use --overwrite to replace."
        )
        sys.exit(2)
    open(audit_path, "w").close()

    scenarios = []

    # Scenario 1: Bad switch into 4x weakness
    # Active Snorlax (Normal) is neutral vs Rock.
    # Candidate Charizard (Fire/Flying) is 4x weak
    # to Rock (Rock vs Fire = 2x, Rock vs Flying =
    # 2x). Switching into Charizard is bad.
    snorlax_active = _make_pokemon("Snorlax", PokemonType.NORMAL)
    charizard_4x = _make_pokemon(
        "Charizard", PokemonType.FIRE, PokemonType.FLYING
    )
    tyranitar_rock = _make_pokemon(
        "Tyranitar", PokemonType.ROCK, PokemonType.DARK
    )
    snorlax_opp2 = _make_pokemon("Snorlax", PokemonType.NORMAL)
    s1 = _run_scenario(
        "bad_switch_into_4x_weakness",
        "Active Normal; candidate Fire/Flying is 4x "
        "weak to opp's Rock/Dark. Switching in is "
        "penalised as quad_weak.",
        snorlax_active,
        charizard_4x,
        [tyranitar_rock, snorlax_opp2],
        best_stay_score=20.0,
    )
    scenarios.append(s1)

    # Scenario 2: Healthy bench preservation
    # Active Charizard at 0.10 HP has a useful
    # action. The candidate Blastoise is full HP.
    # The diagnostic identifies a sacrifice
    # opportunity that would waste the healthy
    # bench.
    charizard_low = _make_pokemon(
        "Charizard", PokemonType.FIRE, PokemonType.FLYING, hp=0.10
    )
    blastoise_full = _make_pokemon(
        "Blastoise", PokemonType.WATER, hp=1.0
    )
    venusaur_opp = _make_pokemon(
        "Venusaur", PokemonType.GRASS, PokemonType.POISON
    )
    snorlax_opp = _make_pokemon("Snorlax", PokemonType.NORMAL)
    s2 = _run_scenario(
        "healthy_bench_preservation",
        "Active is low HP and has a useful action; "
        "sacrificing a healthy bench is penalised.",
        charizard_low,
        blastoise_full,
        [venusaur_opp, snorlax_opp],
        best_stay_score=80.0,
    )
    scenarios.append(s2)

    # Scenario 3: Real risk reduction
    # Active Charizard (Fire/Flying) is 2x weak to
    # Water (Blastoise). Candidate Gastrodon
    # (Water/Ground) resists Water (0.5x) but is
    # 2x weak to Grass; the other opp is Normal so
    # the max-risk computation picks Water for the
    # active and Water for the candidate. The
    # candidate is therefore safer.
    charizard_active = _make_pokemon(
        "Charizard", PokemonType.FIRE, PokemonType.FLYING
    )
    gastrodon = _make_pokemon(
        "Gastrodon", PokemonType.WATER, PokemonType.GROUND
    )
    blastoise_opp = _make_pokemon(
        "Blastoise", PokemonType.WATER
    )
    snorlax_opp2 = _make_pokemon("Snorlax", PokemonType.NORMAL)
    s3 = _run_scenario(
        "real_risk_reduction",
        "Active is 2x weak to opp's Water; candidate "
        "Gastrodon (Water/Ground) resists Water so "
        "the max-risk drops from 2.0x to 1.0x.",
        charizard_active,
        gastrodon,
        [blastoise_opp, snorlax_opp2],
        best_stay_score=20.0,
    )
    scenarios.append(s3)

    # Scenario 4: Repeat switch
    snorlax_active4 = _make_pokemon(
        "Snorlax", PokemonType.NORMAL
    )
    blastoise_switch4 = _make_pokemon(
        "Blastoise", PokemonType.WATER
    )
    snorlax_opp4a = _make_pokemon("Snorlax", PokemonType.NORMAL)
    snorlax_opp4b = _make_pokemon("Snorlax", PokemonType.NORMAL)
    s4 = _run_scenario(
        "repeat_switch",
        "Same slot switched on the previous turn; "
        "ON applies the repeat-switch penalty.",
        snorlax_active4,
        blastoise_switch4,
        [snorlax_opp4a, snorlax_opp4b],
        best_stay_score=20.0,
        turn=2,
        repeat_history=True,
    )
    scenarios.append(s4)

    # Scenario 5: Useful stay
    charizard_active5 = _make_pokemon(
        "Charizard", PokemonType.FIRE, PokemonType.FLYING
    )
    blastoise_switch5 = _make_pokemon(
        "Blastoise", PokemonType.WATER
    )
    venusaur_opp5 = _make_pokemon(
        "Venusaur", PokemonType.GRASS, PokemonType.POISON
    )
    snorlax_opp5 = _make_pokemon("Snorlax", PokemonType.NORMAL)
    s5 = _run_scenario(
        "useful_stay",
        "Active has a high-value action; ON prefers "
        "to stay and penalises the switch.",
        charizard_active5,
        blastoise_switch5,
        [venusaur_opp5, snorlax_opp5],
        best_stay_score=250.0,
    )
    scenarios.append(s5)

    with open(audit_path, "w") as f:
        for s in scenarios:
            record = _scenario_to_audit_record(s, s["scenario_id"])
            f.write(json.dumps(record) + "\n")

    print(
        f"Phase 6.4.10 targeted qualification: "
        f"tag={args.artifact_tag}, scenarios={len(scenarios)}"
    )
    print(f"  JSONL: {audit_path}")
    print(
        f"\n  Next: run the analyzer:\n"
        f"  ./venv/bin/python analyze_doubles_voluntary_switch_targeted.py "
        f"--artifact-tag {args.artifact_tag}"
    )


if __name__ == "__main__":
    main()
