"""Revealed-move switch interception helpers.

ponytail: Phase Ponytail Refactor Step 6C.
Extracted the revealed-move helpers from
``bot_doubles_damage_aware.py`` to a focused
module.

The helpers in this module are the same code that
used to live at lines 1971-2355 of
``bot_doubles_damage_aware.py``. The behavior is
bit-for-bit identical.

Helpers extracted (5):
- get_revealed_damaging_moves
- evaluate_revealed_move_incoming_risk
- estimate_revealed_move_target_likelihood
- summarize_revealed_move_threats
- evaluate_revealed_move_switch_interception

Dependency notes:
- This module has NO bot-local dependencies
  beyond the standard poke_env API
  (``damage_multiplier``, ``moves``,
  ``current_hp_fraction``, etc.).
- No lazy imports needed.
"""


def get_revealed_damaging_moves(opponent) -> list:
    """Get revealed damaging moves from an opponent.

    Uses only opponent.moves.values() -- never infers from species.
    """
    result = []
    if not opponent:
        return result
    moves = getattr(opponent, "moves", None)
    if not moves:
        return result
    for move in moves.values():
        try:
            if move is None:
                continue
            base_power = getattr(move, "base_power", 0)
            if not base_power or base_power <= 0:
                continue
            cat = getattr(move, "category", None)
            cat_name = getattr(cat, "name", "STATUS") if cat else "STATUS"
            if cat_name == "STATUS":
                continue
            result.append(move)
        except Exception:
            continue
    return result


def evaluate_revealed_move_incoming_risk(move, opponent, defender, battle=None) -> dict:
    """Evaluate incoming risk of a revealed move against a defender.

    Uses only the move's observed type, base_power, and the defender's
    visible type(s). Does NOT infer hidden moves, abilities, items, or
    species sets.
    """
    result = {
        "damage_fraction": 0.0,
        "is_threatening": False,
        "super_effective": False,
        "reason": "",
    }
    if not move or not defender:
        return result
    base_power = getattr(move, "base_power", 0)
    if not base_power or base_power <= 0:
        return result
    try:
        move_type = getattr(move, "type", None)
        if move_type is None:
            return result
        type_name = getattr(move_type, "name", str(move_type)).lower()
        mult = 1.0
        try:
            mult = defender.damage_multiplier(type_name)
        except Exception:
            mult = 1.0
        if mult <= 0.0:
            result["damage_fraction"] = 0.0
            result["is_threatening"] = False
            result["reason"] = "type_immunity"
            return result
        result["super_effective"] = mult >= 2.0
        # Heuristic: rough damage fraction based on base_power and type mult.
        # Calibrated to be conservative: only flag "threatening" if SE and
        # high base power, OR if STAB + super effective.
        if mult >= 2.0 and base_power >= 60:
            result["damage_fraction"] = min(1.0, 0.6 * mult)
            result["is_threatening"] = True
            result["reason"] = "se_high_power"
        elif mult >= 4.0:
            result["damage_fraction"] = min(1.0, 0.8 * mult)
            result["is_threatening"] = True
            result["reason"] = "quad_weak"
        else:
            result["damage_fraction"] = min(0.4, 0.15 * mult * (base_power / 100.0))
            result["is_threatening"] = result["damage_fraction"] >= 0.3
        return result
    except Exception:
        return result


def estimate_revealed_move_target_likelihood(
    move, attacker, ally, opponent_actives, battle=None
) -> dict:
    """Estimate likelihood that a revealed move targets each opponent slot.

    Uses only observed move data. Heuristic based on move.target and
    whether the move can hit each slot.
    """
    result = {
        "opp_slot_0_likelihood": 0.5,
        "opp_slot_1_likelihood": 0.5,
        "reason": "",
    }
    if not move or not opponent_actives:
        return result
    target = getattr(move, "target", None)
    target_str = str(target).lower() if target else ""
    if "all" in target_str or "foe" in target_str or "adjacent" in target_str:
        # Spread move: both slots equally likely
        result["opp_slot_0_likelihood"] = 0.5
        result["opp_slot_1_likelihood"] = 0.5
        result["reason"] = "spread"
    else:
        # Single-target: 50/50 by default (we don't have positioning data)
        result["opp_slot_0_likelihood"] = 0.5
        result["opp_slot_1_likelihood"] = 0.5
        result["reason"] = "single_target_default"
    return result


def summarize_revealed_move_threats(opponent, defender) -> dict:
    """Summarize revealed-move threats from an opponent against a defender.

    Returns dict with:
      - threatening_moves: list of (move, damage_fraction) tuples
      - max_damage_fraction: float
      - se_count: int
      - has_quad_weak: bool
      - reason: str
    """
    result = {
        "threatening_moves": [],
        "max_damage_fraction": 0.0,
        "se_count": 0,
        "has_quad_weak": False,
        "reason": "",
    }
    moves = get_revealed_damaging_moves(opponent)
    if not moves or not defender:
        return result
    for move in moves:
        risk = evaluate_revealed_move_incoming_risk(move, opponent, defender)
        if risk["is_threatening"]:
            result["threatening_moves"].append(
                (move, risk["damage_fraction"])
            )
            if risk["damage_fraction"] > result["max_damage_fraction"]:
                result["max_damage_fraction"] = risk["damage_fraction"]
            if risk["super_effective"]:
                result["se_count"] += 1
            if risk["reason"] == "quad_weak":
                result["has_quad_weak"] = True
    return result


def evaluate_revealed_move_switch_interception(
    candidate, opponent, ally=None, battle=None, config=None
) -> dict:
    """Evaluate whether switching to ``candidate`` would intercept a revealed move.

    Used to avoid pivoting into a confirmed move. Uses only observed
    revealed moves, never hidden or random-set data.

    Returns dict with:
      - intercept_score: float (lower = more danger)
      - max_damage_fraction: float
      - threatening_moves: list
      - should_avoid: bool
      - reason: str
    """
    result = {
        "intercept_score": 0.0,
        "max_damage_fraction": 0.0,
        "threatening_moves": [],
        "should_avoid": False,
        "reason": "",
    }
    if not candidate or not opponent:
        return result
    summary = summarize_revealed_move_threats(opponent, candidate)
    result["max_damage_fraction"] = summary["max_damage_fraction"]
    result["threatening_moves"] = summary["threatening_moves"]
    if summary["max_damage_fraction"] >= 0.5:
        result["should_avoid"] = True
        result["reason"] = "high_incoming_damage"
    elif summary["se_count"] >= 2:
        result["should_avoid"] = True
        result["reason"] = "multiple_se_threats"
    elif summary["has_quad_weak"]:
        result["should_avoid"] = True
        result["reason"] = "quad_weak_to_opponent"
    # Compute intercept score (negative = bad switch)
    result["intercept_score"] = -summary["max_damage_fraction"] * 100.0
    return result
