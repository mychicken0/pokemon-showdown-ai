#!/usr/bin/env python3
"""Phase V3b — opponent-adaptive preview features.

Ponytail: standalone focused module. Reuses
``evaluate_all_combinations_v3`` from
``team_preview_policy`` and the existing
``_move_data`` / ``classify_move`` from
``vgc2026_plan_features``. Reuses
``calculate_type_multiplier`` from
``doubles_mechanics`` for the actual type
effectiveness math.

Goal: every feature in V3b MUST depend on the
opponent team. If the opponent team is the same
and the plan is the same, the features MUST be
the same (deterministic). If only the opponent
team changes, the features MUST change
(opponent-sensitive).

Six feature groups, all built only from open
team-sheet data (species, ability, moves,
types) — no hidden information.
"""
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from doubles_mechanics import calculate_type_multiplier
from team_preview_policy import get_species_types
from vgc2026_plan_features import (
    _move_data,
    _is_priority_move,
    _is_stall_move,
    classify_move,
)


# ---------------------------------------------------------------------------
# Helpers (minimal, stdlib-only)
# ---------------------------------------------------------------------------


def _pokemon_types(pokemon: Dict[str, Any]) -> List[str]:
    """Return the upper-cased types for a pokemon dict.
    ponytail: relies on get_species_types from
    team_preview_policy which is open team-sheet.
    """
    return [t.upper() for t in get_species_types(
        pokemon.get("species", "")
    )]


def _best_effectiveness(
    attacker_types: List[str], defender_types: List[str]
) -> float:
    """Best type effectiveness an attacker's
    types can produce vs a defender's types.
    """
    if not attacker_types or not defender_types:
        return 0.0
    best = 0.0
    for atk in attacker_types:
        mult = calculate_type_multiplier(atk, defender_types)
        if mult > best:
            best = mult
    return best


def _max_damaging_multiplier(
    pokemon: Dict[str, Any], defender_types: List[str]
) -> float:
    """Highest damaging-move multiplier this
    pokemon can produce against the defender's
    types.
    """
    best = _best_effectiveness(_pokemon_types(pokemon), defender_types)
    for move in pokemon.get("moves", []) or []:
        md = _move_data(move)
        if md.get("category") not in ("Physical", "Special"):
            continue
        if md.get("basePower", 0) <= 0:
            continue
        move_type = md.get("type", "")
        if not move_type:
            continue
        mult = calculate_type_multiplier(
            move_type.upper(), defender_types
        )
        if mult > best:
            best = mult
    return best


def _has_speed_control(pokemon: Dict[str, Any]) -> Dict[str, bool]:
    """Returns dict of speed-control booleans from
    the pokemon's visible moves.
    ponytail: name-based, not category-based,
    because classify_move returns "status" for
    Tailwind/Trick Room.
    """
    moves_lc = {m.lower() for m in
                (pokemon.get("moves") or [])}
    has_tw = "tailwind" in moves_lc
    has_tr = "trick room" in moves_lc
    has_iw = "icy wind" in moves_lc or "electroweb" in moves_lc
    has_fo = any(classify_move(m) == "fake_out"
                 for m in moves_lc)
    has_protect = any(_is_stall_move(m)
                      for m in moves_lc)
    has_priority = any(_is_priority_move(m)
                       for m in moves_lc)
    has_helping = "helping hand" in moves_lc
    has_follow = "follow me" in moves_lc or \
        "rage powder" in moves_lc
    has_switch = "parting shot" in moves_lc or \
        "teleport" in moves_lc or \
        "chilly reception" in moves_lc
    return {
        "tailwind": has_tw,
        "trick_room": has_tr,
        "icy_wind_electroweb": has_iw,
        "fake_out": has_fo,
        "protect": has_protect,
        "priority": has_priority,
        "helping_hand": has_helping,
        "redirection": has_follow,
        "switch_utility": has_switch,
    }


def _ability_cat(pokemon: Dict[str, Any]) -> str:
    ab = (pokemon.get("ability") or "").lower()
    if "intimidate" in ab:
        return "intimidate"
    if any(k in ab for k in ("follow me", "rage powder")):
        return "redirection"
    if "drizzle" in ab or "drought" in ab:
        return "weather"
    return "other"


# ---------------------------------------------------------------------------
# Per-plan features vs opponent team
# ---------------------------------------------------------------------------


def _lead_offense_vs_opp(
    leads: List[Dict[str, Any]],
    opp_team: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Group 1: lead offensive matchup."""
    # Count opp species threatened super-effectively
    # (>1x) by our lead damaging moves.
    opp_threatened = 0
    opp_immune_to_us = 0
    effectiveness_values: List[float] = []
    for opp in opp_team:
        opp_types = _pokemon_types(opp)
        if not opp_types:
            continue
        per_pokemon_max = 0.0
        per_pokemon_immune = True
        for lead in leads:
            eff = _max_damaging_multiplier(lead, opp_types)
            if eff > per_pokemon_max:
                per_pokemon_max = eff
            if eff > 1.0:
                per_pokemon_immune = False
        effectiveness_values.append(per_pokemon_max)
        if per_pokemon_max > 1.0:
            opp_threatened += 1
        if per_pokemon_immune:
            opp_immune_to_us += 1
    if not effectiveness_values:
        return {
            "lead_off_best_eff": 0.0,
            "lead_off_mean_eff": 0.0,
            "lead_off_worst_eff": 0.0,
            "lead_off_threatened_count": 0.0,
            "lead_off_immune_count": 0.0,
        }
    return {
        "lead_off_best_eff": max(effectiveness_values),
        "lead_off_mean_eff": sum(effectiveness_values) / len(
            effectiveness_values
        ),
        "lead_off_worst_eff": min(effectiveness_values),
        "lead_off_threatened_count": float(opp_threatened),
        "lead_off_immune_count": float(opp_immune_to_us),
    }


def _lead_defense_vs_opp(
    leads: List[Dict[str, Any]],
    opp_team: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Group 2: lead defensive matchup. How hard
    does the opponent hit our lead pair?
    """
    threat_values: List[float] = []
    lead_4x = 0
    for our_lead in leads:
        our_types = _pokemon_types(our_lead)
        if not our_types:
            continue
        per_lead_max = 0.0
        for opp in opp_team:
            opp_types = _pokemon_types(opp)
            if not opp_types:
                continue
            eff = _best_effectiveness(opp_types, our_types)
            if eff > per_lead_max:
                per_lead_max = eff
        threat_values.append(per_lead_max)
        if per_lead_max >= 4.0:
            lead_4x += 1
    if not threat_values:
        return {
            "lead_def_mean_threat": 0.0,
            "lead_def_worst_threat": 0.0,
            "lead_def_4x_count": 0.0,
        }
    return {
        "lead_def_mean_threat": sum(threat_values) / len(
            threat_values
        ),
        "lead_def_worst_threat": max(threat_values),
        "lead_def_4x_count": float(lead_4x),
    }


def _speed_control_matchup(
    leads: List[Dict[str, Any]],
    backs: List[Dict[str, Any]],
    opp_team: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Group 3: speed/control matchup."""
    our_team = leads + backs
    our_sc = {
        k: any(_has_speed_control(p)[k] for p in our_team)
        for k in (
            "tailwind", "trick_room", "icy_wind_electroweb",
            "fake_out", "protect", "priority",
        )
    }
    opp_sc = {
        k: any(_has_speed_control(p)[k] for p in opp_team)
        for k in our_sc
    }
    return {
        "sc_tw_advantage": float(
            int(our_sc["tailwind"]) - int(opp_sc["tailwind"])
        ),
        "sc_tr_advantage": float(
            int(our_sc["trick_room"]) - int(opp_sc["trick_room"])
        ),
        "sc_iw_advantage": float(
            int(our_sc["icy_wind_electroweb"])
            - int(opp_sc["icy_wind_electroweb"])
        ),
        "sc_fo_count": float(sum(1 for p in our_team
                                 if _has_speed_control(p)["fake_out"])),
        "sc_opp_fo_count": float(sum(1 for p in opp_team
                                     if _has_speed_control(p)["fake_out"])),
    }


def _back_coverage_vs_opp(
    leads: List[Dict[str, Any]],
    backs: List[Dict[str, Any]],
    opp_team: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Group 4: back coverage. Best back damage
    multiplier vs each opp species. Also
    coverage gap: opp species that neither lead
    nor back threatens super-effectively.
    """
    threatened_by_lead = set()
    threatened_by_back = set()
    all_opp_4x_by_us = 0
    for i, opp in enumerate(opp_team):
        opp_types = _pokemon_types(opp)
        if not opp_types:
            continue
        lead_max = 0.0
        for lead in leads:
            eff = _max_damaging_multiplier(lead, opp_types)
            if eff > lead_max:
                lead_max = eff
        back_max = 0.0
        for back in backs:
            eff = _max_damaging_multiplier(back, opp_types)
            if eff > back_max:
                back_max = eff
        if lead_max > 1.0:
            threatened_by_lead.add(i)
        if back_max > 1.0:
            threatened_by_back.add(i)
        if max(lead_max, back_max) > 1.0:
            all_opp_4x_by_us += 1
    # Species covered only by back, not by lead.
    back_only = threatened_by_back - threatened_by_lead
    return {
        "back_coverage_count": float(len(threatened_by_back)),
        "back_only_count": float(len(back_only)),
        "opp_threatened_total": float(
            len(threatened_by_lead | threatened_by_back)
        ),
    }


def _role_denial_vs_opp(
    leads: List[Dict[str, Any]],
    backs: List[Dict[str, Any]],
    opp_team: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Group 5: role denial / support."""
    # Intimidate on leads/backs.
    our_intim = sum(
        1 for p in leads + backs
        if _ability_cat(p) == "intimidate"
    )
    # Opponent physical move count.
    opp_phys = 0
    opp_spread = 0
    opp_single_target = 0
    for opp in opp_team:
        for mv in opp.get("moves", []) or []:
            cat = classify_move(mv)
            if cat == "spread":
                opp_spread += 1
            elif cat in ("priority", "fake_out"):
                opp_single_target += 1
            else:
                md = _move_data(mv)
                if md.get("category") in ("Physical", "Special"):
                    opp_phys += 1
    # Redirection on leads/backs.
    our_redir = sum(
        1 for p in leads + backs
        if _ability_cat(p) == "redirection"
    )
    return {
        "our_intimidate_count": float(our_intim),
        "our_redirection_count": float(our_redir),
        "opp_phys_move_count": float(opp_phys),
        "opp_spread_move_count": float(opp_spread),
    }


def _plan_features(
    chosen: List[Dict[str, Any]],
    lead_2: List[str],
    back_2: List[str],
    opp_team: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Compute all V3b features for one plan.
    chosen is the 4 selected pokemon. lead_2 and
    back_2 are species names.
    """
    by_species = {p["species"].lower(): p for p in chosen}
    leads = []
    for s in lead_2:
        m = by_species.get(s.lower())
        if m is not None:
            leads.append(m)
    backs = []
    for s in back_2:
        m = by_species.get(s.lower())
        if m is not None:
            backs.append(m)
    feats: Dict[str, float] = {}
    feats.update(_lead_offense_vs_opp(leads, opp_team))
    feats.update(_lead_defense_vs_opp(leads, opp_team))
    feats.update(_speed_control_matchup(leads, backs, opp_team))
    feats.update(_back_coverage_vs_opp(leads, backs, opp_team))
    feats.update(_role_denial_vs_opp(leads, backs, opp_team))
    return feats


# ---------------------------------------------------------------------------
# Public enumeration
# ---------------------------------------------------------------------------


def enumerate_v3b_plans(
    our_team: List[Dict[str, Any]],
    opp_team: Optional[List[Dict[str, Any]]] = None,
):
    """Enumerate all 90 plans with V3b features
    plus opponent-specific deltas (group 6).
    ponytail: delegates to existing
    evaluate_all_combinations_v3.
    """
    from team_preview_policy import evaluate_all_combinations_v3
    results = evaluate_all_combinations_v3(our_team, opp_team)
    # First pass: collect base features.
    plans = []
    for ordered_plan, _score, _details in results:
        species = [p.get("species", "") for p in ordered_plan]
        lead_2 = species[:2]
        back_2 = species[2:]
        feats = _plan_features(
            ordered_plan, lead_2, back_2, opp_team or []
        )
        plans.append((species, lead_2, back_2, feats))
    # Second pass: opponent-specific deltas.
    # ponytail: for each feature, mean across all 90
    # plans, then delta = plan_feat - mean. Gives
    # the learner "why this plan is better for this
    # opponent".
    if plans and opp_team:
        all_feat_names = sorted(plans[0][3].keys())
        means = {
            fn: sum(p[3].get(fn, 0.0) for p in plans) / len(plans)
            for fn in all_feat_names
        }
        for i, (sp, l2, b2, fdict) in enumerate(plans):
            for fn in all_feat_names:
                fdict[f"delta_{fn}"] = (
                    fdict.get(fn, 0.0) - means[fn]
                )
    return plans


# ---------------------------------------------------------------------------
# Feature audit
# ---------------------------------------------------------------------------


def audit_v3b_features(
    team_pool,
    n_teams: int = 10,
    n_opps_per_team: int = 3,
    seed: int = 42,
):
    """Compute feature audit metrics across a
    sample of teams and opponent matchups. Returns
    a dict with per-feature stats and gate results.

    Audit criteria:
    - nonzero_count: how many plans have a
      non-default-zero value for this feature
    - var_across_plans_same_team: variance of the
      feature across the 90 plans for the same team
      (with one fixed opponent)
    - var_across_opps_same_team: variance of the
      feature's mean across different opponents for
      the same team
    - opponent_sensitive: feature value changes
      when opponent team changes (with plan fixed)
    """
    import random as _r
    import statistics as _st
    rng = _r.Random(seed)
    team_count = min(n_teams, len(team_pool))
    opps = [team_pool.get_team(i) for i in range(min(
        n_opps_per_team + 1, len(team_pool)
    ))]
    sample_team_indices = list(range(team_count))
    rng.shuffle(sample_team_indices)
    sample_team_indices = sample_team_indices[:n_teams]
    feature_names: List[str] = []
    # per_feature_stats[name] = dict with keys
    # nonzero_count, var_across_plans, var_across_opps,
    # opponent_sensitive_count
    per_feature_stats: Dict[str, Dict[str, Any]] = {}
    n_total_plan = 0
    n_plan_opp = 0
    n_opp_sensitive_tests = 0
    for ti in sample_team_indices:
        team = team_pool.get_team(ti).pokemon
        for opp in opps[:n_opps_per_team]:
            opp_team = opp.pokemon
            plans = enumerate_v3b_plans(team, opp_team)
            if not plans:
                continue
            n_plan_opp += 1
            if not feature_names:
                feature_names = sorted(plans[0][3].keys())
                for fn in feature_names:
                    per_feature_stats[fn] = {
                        "nonzero_count": 0,
                        "var_across_plans_sum": 0.0,
                        "var_across_plans_n": 0,
                        "opp_values": [],
                        "opp_sensitive_count": 0,
                    }
            # Per-plan values for var_across_plans.
            plan_vals: Dict[str, List[float]] = {fn: []
                for fn in feature_names}
            for _c, _l, _b, fdict in plans:
                n_total_plan += 1
                for fn in feature_names:
                    v = fdict.get(fn, 0.0)
                    plan_vals[fn].append(v)
                    if v != 0.0:
                        per_feature_stats[fn]["nonzero_count"] += 1
            for fn in feature_names:
                vals = plan_vals[fn]
                if len(vals) >= 2 and max(vals) != min(vals):
                    var = _st.variance(vals)
                    per_feature_stats[fn]["var_across_plans_sum"] += var
                    per_feature_stats[fn]["var_across_plans_n"] += 1
            # Save the first plan's values for opp-sensitivity.
            first_plan = plans[0][3]
            for fn in feature_names:
                per_feature_stats[fn]["opp_values"].append(
                    first_plan.get(fn, 0.0)
                )
    # Now compute var_across_opps_same_team for each
    # feature: the variance of the first-plan values
    # across different opponents (which we just
    # collected). This shows opponent-sensitivity
    # of a representative plan.
    for fn in feature_names:
        opp_vals = per_feature_stats[fn]["opp_values"]
        if len(opp_vals) >= 2:
            var = _st.variance(opp_vals) if max(opp_vals) != min(
                opp_vals
            ) else 0.0
            per_feature_stats[fn][
                "var_across_opps_same_team"
            ] = var
            # Opponent-sensitive flag: var > 0.
            per_feature_stats[fn][
                "opp_sensitive_count"
            ] = int(var > 0)
        else:
            per_feature_stats[fn][
                "var_across_opps_same_team"
            ] = 0.0
            per_feature_stats[fn][
                "opp_sensitive_count"
            ] = 0
    # Build per-feature summary.
    summary = []
    n_opp_sensitive = 0
    n_plan_varying = 0
    for fn in feature_names:
        st = per_feature_stats[fn]
        n = st["var_across_plans_n"]
        avg_var = st["var_across_plans_sum"] / n if n else 0.0
        plan_varying = avg_var > 0
        opp_sensitive = st["opp_sensitive_count"] > 0
        if plan_varying:
            n_plan_varying += 1
        if opp_sensitive:
            n_opp_sensitive += 1
        summary.append({
            "name": fn,
            "nonzero_count": st["nonzero_count"],
            "avg_var_across_plans_same_team": avg_var,
            "var_across_opps_same_team": st[
                "var_across_opps_same_team"
            ],
            "opponent_sensitive": opp_sensitive,
            "plan_varying": plan_varying,
        })
    return {
        "n_features": len(feature_names),
        "n_opp_sensitive": n_opp_sensitive,
        "n_plan_varying": n_plan_varying,
        "n_plan_opp_pairs_audited": n_plan_opp,
        "n_total_plan_records": n_total_plan,
        "feature_summary": summary,
    }


def v3b_features_for_plan(
    our_team: List[Dict[str, Any]],
    chosen_4: List[str],
    lead_2: List[str],
    back_2: List[str],
    opp_team: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, float]:
    """Public helper: compute V3b features for one
    specific (chosen, lead, back) given an
    opponent team. ponytail: 1-line wrapper.
    """
    by_species = {p["species"].lower(): p for p in our_team}
    chosen_pkmn = []
    for s in chosen_4:
        m = by_species.get(s.lower())
        if m is not None:
            chosen_pkmn.append(m)
    if len(chosen_pkmn) != 4:
        # If we can't resolve the chosen 4, fail closed:
        # return empty so callers can detect.
        return {}
    return _plan_features(chosen_pkmn, lead_2, back_2, opp_team or [])
