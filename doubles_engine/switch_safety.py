"""Switch candidate type safety helper.

ponytail: Phase Ponytail Refactor Step 6B.
Extracted ``evaluate_switch_candidate_type_safety``
from ``bot_doubles_damage_aware.py`` to a focused
module.

The helper in this module is the same code that
used to live at lines 1390-1547 of
``bot_doubles_damage_aware.py``. The behavior is
bit-for-bit identical.

Dependency notes:
- This module has NO bot-local dependencies
  beyond the standard poke_env API.
- No lazy imports needed.
"""


def evaluate_switch_candidate_type_safety(
    candidate, opponent_actives, config=None
) -> dict:
    """Evaluate type safety of a switch candidate against visible opponents.

    Uses only currently visible Pokemon types and HP. No species-based move
    assumptions, random-set data, possible abilities, hidden moves, hidden
    items, or unrevealed information.

    For each opponent, calculates the maximum incoming multiplier among that
    opponent visible types as a conservative STAB-type exposure signal.

    Returns a dict with raw safety score, worst multiplier, per-opponent
    worst multipliers, threat counts, double-threat boolean, opponent threat
    type names, candidate HP fraction, and immunity/resistance counts.
    """
    result = {
        "raw_safety_score": 0.0,
        "worst_multiplier": 1.0,
        "per_opponent_worst_multipliers": [],
        "super_effective_threat_count": 0,
        "quad_weak_threat_count": 0,
        "resistant_threat_count": 0,
        "immune_threat_count": 0,
        "double_threat": False,
        "opponent_threat_type_names": [],
        "candidate_hp_fraction": 1.0,
    }

    if not candidate:
        return result

    # Get candidate types
    cand_type_1 = getattr(candidate, "type_1", None)
    cand_type_2 = getattr(candidate, "type_2", None)

    # Get candidate HP fraction
    hp_frac = getattr(candidate, "current_hp_fraction", 1.0)
    if hp_frac is None:
        hp_frac = 1.0
    result["candidate_hp_fraction"] = hp_frac

    # Get config penalties/bonuses
    se_penalty = (
        getattr(config, "switch_candidate_super_effective_penalty", 80.0)
        if config
        else 80.0
    )
    quad_penalty = (
        getattr(config, "switch_candidate_quad_weak_penalty", 160.0)
        if config
        else 160.0
    )
    double_penalty = (
        getattr(config, "switch_candidate_double_threat_penalty", 100.0)
        if config
        else 100.0
    )
    res_bonus = (
        getattr(config, "switch_candidate_resistance_bonus", 20.0) if config else 20.0
    )
    imm_bonus = (
        getattr(config, "switch_candidate_immunity_bonus", 30.0) if config else 30.0
    )
    low_hp_penalty = (
        getattr(config, "switch_candidate_low_hp_penalty", 30.0) if config else 30.0
    )

    raw_score = 0.0
    worst_mult = 1.0
    se_count = 0
    quad_count = 0
    res_count = 0
    imm_count = 0
    threat_types = []
    per_opp = []

    if not opponent_actives:
        result["raw_safety_score"] = raw_score
        result["worst_multiplier"] = worst_mult
        return result

    for opp in opponent_actives:
        if not opp:
            per_opp.append(1.0)
            continue

        opp_type_1 = getattr(opp, "type_1", None)
        opp_type_2 = getattr(opp, "type_2", None)

        # Calculate max incoming multiplier from opponents  visible types
        max_mult = 0.0
        opp_best_type = None

        for opp_type in (opp_type_1, opp_type_2):
            if opp_type is None:
                continue
            try:
                if cand_type_1 is not None:
                    mult1 = candidate.damage_multiplier(opp_type)
                    if mult1 > max_mult:
                        max_mult = mult1
                        opp_best_type = opp_type
            except Exception:
                if max_mult < 1.0:
                    max_mult = 1.0

        if max_mult == 0.0 and (opp_type_1 is None and opp_type_2 is None):
            max_mult = 1.0
        elif max_mult == 0.0 and cand_type_1 is None:
            max_mult = 1.0

        per_opp.append(max_mult)

        if max_mult > worst_mult:
            worst_mult = max_mult

        # Classify using ONLY the maximum multiplier per opponent
        if max_mult >= 4.0:
            quad_count += 1
            se_count += 1
            if opp_best_type and opp_best_type.name.title() not in threat_types:
                threat_types.append(opp_best_type.name.title())
        elif max_mult >= 2.0:
            se_count += 1
            if opp_best_type and opp_best_type.name.title() not in threat_types:
                threat_types.append(opp_best_type.name.title())
        elif max_mult == 0.0:
            imm_count += 1
        elif max_mult <= 0.5:
            res_count += 1

    raw_score -= se_count * se_penalty
    raw_score -= quad_count * quad_penalty
    raw_score += res_count * res_bonus
    raw_score += imm_count * imm_bonus

    # Double threat: both opponents threaten super-effective
    is_double_threat = se_count >= 2
    if is_double_threat:
        raw_score -= double_penalty

    # Low HP penalty
    if hp_frac <= 0.35:
        raw_score -= low_hp_penalty * (1.0 - hp_frac)

    result["raw_safety_score"] = raw_score
    result["worst_multiplier"] = worst_mult
    result["per_opponent_worst_multipliers"] = per_opp
    result["super_effective_threat_count"] = se_count
    result["quad_weak_threat_count"] = quad_count
    result["resistant_threat_count"] = res_count
    result["immune_threat_count"] = imm_count
    result["double_threat"] = is_double_threat
    result["opponent_threat_type_names"] = threat_types
    result["candidate_hp_fraction"] = hp_frac

    return result
