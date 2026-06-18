"""Forced switch replacement safety helpers.

ponytail: Phase Ponytail Refactor Step 6A.
Extracted
``evaluate_forced_switch_replacement_safety``
from ``bot_doubles_damage_aware.py`` to a focused
module.

The helper in this module is the same code that
used to live at lines 1550-1719 of
``bot_doubles_damage_aware.py``. The behavior is
bit-for-bit identical.

Dependency notes:
- This module has NO bot-local dependencies
  beyond the standard poke_env API
  (``damage_multiplier``, ``type_1``, ``type_2``,
  ``current_hp_fraction``, ``fainted``).
- No lazy imports needed.
"""


def evaluate_forced_switch_replacement_safety(
    candidate, opponent_actives, battle=None, config=None
) -> dict:
    """Evaluate forced switch replacement safety for a single candidate.

    Used ONLY for required replacement switches (after faint), NOT voluntary pivots.
    Uses only visible opponent types, HP, and already-revealed moves.
    Does NOT infer hidden moves, abilities, items, or species sets.

    Returns dict with:
      - score: float (higher is safer)
      - max_threat_multiplier: float
      - opponent_threat_count: int (opponents with SE threat)
      - quad_weak_count: int
      - resistance_count: int
      - immunity_count: int
      - low_hp_penalty_applied: bool
      - reasons: list[str]
    """
    result = {
        "score": 0.0,
        "max_threat_multiplier": 1.0,
        "opponent_threat_count": 0,
        "quad_weak_count": 0,
        "resistance_count": 0,
        "immunity_count": 0,
        "low_hp_penalty_applied": False,
        "reasons": [],
    }

    if not candidate:
        return result

    # Config penalties/bonuses
    se_penalty = (
        getattr(config, "forced_switch_super_effective_penalty", 90.0)
        if config
        else 90.0
    )
    quad_penalty = (
        getattr(config, "forced_switch_quad_weak_penalty", 180.0) if config else 180.0
    )
    double_penalty = (
        getattr(config, "forced_switch_double_threat_penalty", 120.0)
        if config
        else 120.0
    )
    res_bonus = (
        getattr(config, "forced_switch_resistance_bonus", 25.0) if config else 25.0
    )
    imm_bonus = (
        getattr(config, "forced_switch_immunity_bonus", 35.0) if config else 35.0
    )
    low_hp_penalty = (
        getattr(config, "forced_switch_low_hp_penalty", 30.0) if config else 30.0
    )
    fainted_penalty = (
        getattr(config, "forced_switch_fainted_or_unavailable_penalty", 9999.0)
        if config
        else 9999.0
    )

    # Check fainted/unavailable
    if getattr(candidate, "fainted", False):
        result["score"] = -fainted_penalty
        result["reasons"].append("fainted")
        return result

    hp_frac = getattr(candidate, "current_hp_fraction", 1.0)
    if hp_frac is None:
        hp_frac = 1.0

    # Get candidate types
    cand_type_1 = getattr(candidate, "type_1", None)
    cand_type_2 = getattr(candidate, "type_2", None)

    raw_score = 0.0
    worst_mult = 1.0
    se_count = 0
    quad_count = 0
    res_count = 0
    imm_count = 0
    threat_types = []

    if not opponent_actives:
        result["score"] = raw_score
        result["max_threat_multiplier"] = worst_mult
        return result

    for opp in opponent_actives:
        if not opp or getattr(opp, "fainted", False):
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
                    mult = candidate.damage_multiplier(opp_type)
                    if mult > max_mult:
                        max_mult = mult
                        opp_best_type = opp_type
            except Exception:
                if max_mult < 1.0:
                    max_mult = 1.0

        if max_mult == 0.0 and (opp_type_1 is None and opp_type_2 is None):
            max_mult = 1.0
        elif max_mult == 0.0 and cand_type_1 is None:
            max_mult = 1.0

        if max_mult > worst_mult:
            worst_mult = max_mult

        # Classify
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

    # Apply penalties and bonuses
    raw_score -= se_count * se_penalty
    raw_score -= quad_count * quad_penalty
    raw_score += res_count * res_bonus
    raw_score += imm_count * imm_bonus

    # Double threat: both opponents threaten super-effective
    is_double_threat = se_count >= 2
    if is_double_threat:
        raw_score -= double_penalty
        result["reasons"].append("double_threat")

    if quad_count > 0:
        result["reasons"].append("quad_weak")

    # Low HP penalty
    if hp_frac <= 0.35:
        raw_score -= low_hp_penalty * (1.0 - hp_frac)
        result["low_hp_penalty_applied"] = True
        result["reasons"].append("low_hp")

    if se_count > 0:
        result["reasons"].append("super_effective_threat")

    result["score"] = raw_score
    result["max_threat_multiplier"] = worst_mult
    result["opponent_threat_count"] = se_count
    result["quad_weak_count"] = quad_count
    result["resistance_count"] = res_count
    result["immunity_count"] = imm_count

    return result
