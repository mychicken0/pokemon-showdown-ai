"""Voluntary switch quality helper.

ponytail: Phase Ponytail Refactor Step 6E.
Extracted ``evaluate_voluntary_switch_quality``
from ``bot_doubles_damage_aware.py`` to a focused
module.

The helper in this module is the same code that
used to live at lines 1410-1656 of
``bot_doubles_damage_aware.py``. The behavior is
bit-for-bit identical.

Dependency notes:
- This module has NO bot-local dependencies
  beyond the standard poke_env API.
- No lazy imports needed.
"""


def evaluate_voluntary_switch_quality(
    active,
    candidate,
    slot_idx,
    battle,
    best_stay_score,
    config,
    player=None,
) -> dict:
    """Evaluate voluntary (non-forced) switch quality for a candidate.

    Computes risk metrics for the active mon vs the candidate against
    visible opponent types.  Returns a dict that the caller can use to
    adjust switch scores.

    Uses only visible information (type_1, type_2, current_hp_fraction).
    Does NOT modify any state -- the caller is responsible for applying
    score_adjustment.
    """
    result = {
        "eligible": True,
        "active_risk": 0.0,
        "candidate_risk": 0.0,
        "risk_reduction": 0.0,
        "best_stay_score": best_stay_score,
        "tempo_penalty": 0.0,
        "candidate_penalty": 0.0,
        "repeat_switch_penalty": 0.0,
        "sacrifice_preserve_bench_value": 0.0,
        "score_adjustment": 0.0,
        "candidate_double_threat": False,
        "candidate_quad_weak": False,
        "candidate_low_hp": False,
        "active_low_hp": False,
        "active_has_useful_action": False,
        "active_has_high_value_action": False,
        "switch_improves_position": False,
        "sacrifice_preferred": False,
        "reason_codes": [],
    }

    if active is None or candidate is None:
        result["eligible"] = False
        result["reason_codes"].append("missing_pokemon")
        return result

    if slot_idx < len(battle.force_switch) and battle.force_switch[slot_idx]:
        result["eligible"] = False
        result["reason_codes"].append("forced_switch")
        return result

    tempo_penalty = (
        getattr(config, "voluntary_switch_tempo_penalty", 35.0) if config else 35.0
    )
    unsafe_penalty = (
        getattr(config, "voluntary_switch_unsafe_candidate_penalty", 120.0)
        if config
        else 120.0
    )
    quad_penalty = (
        getattr(config, "voluntary_switch_quad_weak_penalty", 180.0)
        if config
        else 180.0
    )
    double_penalty = (
        getattr(config, "voluntary_switch_double_threat_penalty", 160.0)
        if config
        else 160.0
    )
    low_hp_cand_penalty = (
        getattr(config, "voluntary_switch_low_hp_candidate_penalty", 35.0)
        if config
        else 35.0
    )
    repeat_penalty = (
        getattr(config, "voluntary_switch_repeat_penalty", 80.0) if config else 80.0
    )
    min_risk_reduction = (
        getattr(config, "voluntary_switch_min_risk_reduction", 1.0) if config else 1.0
    )
    sacrifice_hp_threshold = (
        getattr(config, "voluntary_switch_sacrifice_hp_threshold", 0.15)
        if config
        else 0.15
    )
    useful_action_threshold = (
        getattr(config, "voluntary_switch_useful_action_threshold", 40.0)
        if config
        else 40.0
    )
    high_value_threshold = (
        getattr(config, "voluntary_switch_high_value_action_threshold", 120.0)
        if config
        else 120.0
    )
    preserve_bench_bonus = (
        getattr(config, "voluntary_switch_sacrifice_preserve_bench_bonus", 70.0)
        if config
        else 70.0
    )

    opponent_actives = getattr(battle, "opponent_active_pokemon", [])
    opponent_actives = [
        opp for opp in opponent_actives if opp and not getattr(opp, "fainted", False)
    ]

    active_type_1 = getattr(active, "type_1", None)
    active_type_2 = getattr(active, "type_2", None)
    cand_type_1 = getattr(candidate, "type_1", None)
    cand_type_2 = getattr(candidate, "type_2", None)

    active_hp = getattr(active, "current_hp_fraction", 1.0) or 1.0
    candidate_hp = getattr(candidate, "current_hp_fraction", 1.0) or 1.0

    # --- Active risk: worst-case max incoming multiplier ---
    active_risk = 0.0
    for opp in opponent_actives:
        opp_type_1 = getattr(opp, "type_1", None)
        opp_type_2 = getattr(opp, "type_2", None)
        max_mult = 0.0
        for opp_type in (opp_type_1, opp_type_2):
            if opp_type is None:
                continue
            try:
                if active_type_1 is not None:
                    mult = active.damage_multiplier(opp_type)
                    if mult > max_mult:
                        max_mult = mult
            except Exception:
                if max_mult < 1.0:
                    max_mult = 1.0
        if max_mult == 0.0 and opp_type_1 is None and opp_type_2 is None:
            max_mult = 1.0
        elif max_mult == 0.0 and active_type_1 is None:
            max_mult = 1.0
        if max_mult > active_risk:
            active_risk = max_mult
    result["active_risk"] = active_risk

    # --- Candidate risk + threat classification ---
    candidate_risk = 0.0
    se_count = 0
    quad_count = 0
    for opp in opponent_actives:
        opp_type_1 = getattr(opp, "type_1", None)
        opp_type_2 = getattr(opp, "type_2", None)
        max_mult = 0.0
        for opp_type in (opp_type_1, opp_type_2):
            if opp_type is None:
                continue
            try:
                if cand_type_1 is not None:
                    mult = candidate.damage_multiplier(opp_type)
                    if mult > max_mult:
                        max_mult = mult
            except Exception:
                if max_mult < 1.0:
                    max_mult = 1.0
        if max_mult == 0.0 and opp_type_1 is None and opp_type_2 is None:
            max_mult = 1.0
        elif max_mult == 0.0 and cand_type_1 is None:
            max_mult = 1.0
        if max_mult > candidate_risk:
            candidate_risk = max_mult
        if max_mult >= 4.0:
            quad_count += 1
            se_count += 1
        elif max_mult >= 2.0:
            se_count += 1
    result["candidate_risk"] = candidate_risk

    is_double_threat = se_count >= 2
    result["candidate_double_threat"] = is_double_threat
    result["candidate_quad_weak"] = quad_count > 0

    # --- Risk reduction ---
    risk_reduction = active_risk - candidate_risk
    result["risk_reduction"] = risk_reduction

    # --- HP state ---
    active_low_hp = active_hp <= sacrifice_hp_threshold
    result["active_low_hp"] = active_low_hp
    candidate_low_hp = candidate_hp <= 0.35
    result["candidate_low_hp"] = candidate_low_hp

    # --- Action availability (inferred from best_stay_score) ---
    active_has_useful_action = best_stay_score > useful_action_threshold
    active_has_high_value_action = best_stay_score > high_value_threshold
    result["active_has_useful_action"] = active_has_useful_action
    result["active_has_high_value_action"] = active_has_high_value_action

    # --- Position assessment ---
    switch_improves_position = risk_reduction > min_risk_reduction
    result["switch_improves_position"] = switch_improves_position

    # --- Tempo penalty (always applied for voluntary switches) ---
    result["tempo_penalty"] = tempo_penalty

    # --- Candidate penalty ---
    cand_penalty = 0.0
    cand_penalty += se_count * unsafe_penalty
    cand_penalty += quad_count * quad_penalty
    if is_double_threat:
        cand_penalty += double_penalty
    if candidate_low_hp:
        cand_penalty += low_hp_cand_penalty * (1.0 - candidate_hp)
        result["reason_codes"].append("candidate_low_hp")
    if quad_count > 0:
        result["reason_codes"].append("candidate_quad_weak")
    if is_double_threat:
        result["reason_codes"].append("candidate_double_threat")
    if se_count > 0:
        result["reason_codes"].append("candidate_unsafe")
    result["candidate_penalty"] = cand_penalty

    # --- Repeat switch penalty (computed by caller, passed via player) ---
    repeat_switch_penalty = 0.0
    result["repeat_switch_penalty"] = repeat_switch_penalty

    # --- Sacrifice preserve bench value ---
    sacrifice_value = 0.0
    if active_low_hp and not candidate_low_hp:
        sacrifice_value = preserve_bench_bonus
        result["reason_codes"].append("sacrifice_preserve_bench")
    result["sacrifice_preserve_bench_value"] = sacrifice_value

    # --- Sacrifice preferred ---
    sacrifice_preferred = (
        active_low_hp and not active_has_useful_action and not switch_improves_position
    )
    result["sacrifice_preferred"] = sacrifice_preferred
    if sacrifice_preferred:
        result["reason_codes"].append("sacrifice_preferred")

    # --- Risk reduction bonus ---
    risk_reduction_bonus = 0.0
    if risk_reduction > 0:
        risk_reduction_bonus = risk_reduction * 30.0
        result["reason_codes"].append("risk_reduction_bonus")

    # --- Score adjustment (positive = penalty against the switch) ---
    score_adjustment = (
        tempo_penalty - risk_reduction_bonus + cand_penalty + repeat_switch_penalty
    )
    result["score_adjustment"] = score_adjustment

    return result
