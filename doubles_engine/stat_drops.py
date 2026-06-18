"""Stat-drop scoring and switch-pressure helpers.

ponytail: Phase Ponytail Refactor Step 6D (1/2).
Extracted the stat-drop block from
``bot_doubles_damage_aware.py`` to a focused
module. The voluntary switch function itself
(``evaluate_voluntary_switch_quality``) is large
(248 lines) and remains in the bot; this module
holds the diagnostic helpers that the voluntary
switch function calls into.

The helpers in this module are the same code that
used to live at lines 1659-1984 of
``bot_doubles_damage_aware.py``. The behavior is
bit-for-bit identical.

Helpers extracted (3):
- summarize_negative_boosts
- classify_stat_drop_severity
- evaluate_stat_drop_switch_pressure

Dependency notes:
- This module has NO bot-local dependencies
  beyond the standard poke_env API
  (``damage_multiplier``, ``current_hp_fraction``,
  etc.) and methods on the ``player`` arg
  (``check_move_will_ko``, ``get_expected_damage``,
  ``estimate_opponent_max_hp``).
- No lazy imports needed.
"""


def summarize_negative_boosts(pokemon) -> dict:
    """Summarize current revealed boost stages for diagnostic purposes.

    Records negative stages from the Pokemons current boosts only.
    Does NOT alter scores -- diagnostic-only for Phase 6.4.2.
    """
    result = {
        "attack_minus": 0,
        "defense_minus": 0,
        "special_attack_minus": 0,
        "special_defense_minus": 0,
        "speed_minus": 0,
        "accuracy_minus": 0,
        "evasion_minus": 0,
        "total_severity": 0,
        "worst_stage": 0,
        "worst_stat": "",
        "is_severely_dropped": False,
    }
    if not pokemon:
        return result
    boosts = getattr(pokemon, "boosts", None)
    if not boosts:
        return result
    stat_map = {
        "atk": "attack_minus",
        "def": "defense_minus",
        "spa": "special_attack_minus",
        "spd": "special_defense_minus",
        "spe": "speed_minus",
        "accuracy": "accuracy_minus",
        "evasion": "evasion_minus",
    }
    worst = 0
    worst_stat = ""
    total = 0
    for stat_key, result_key in stat_map.items():
        try:
            val = int(boosts.get(stat_key, 0) or 0)
        except (TypeError, ValueError):
            val = 0
        if val < 0:
            result[result_key] = -val
            total += -val
            if -val > worst:
                worst = -val
                worst_stat = stat_key
    result["total_severity"] = total
    result["worst_stage"] = worst
    result["worst_stat"] = worst_stat
    result["is_severely_dropped"] = worst >= 2
    return result


def classify_stat_drop_severity(boosts: dict, config, orders_slot: list) -> dict:
    """Classify stat-drop severity for switch-pressure scoring.

    Returns dict with:
      - severe: bool — whether the drops are severe enough to consider a switch
      - categories: list[str] — which stat categories are dropped
      - reason: str — human-readable explanation
      - score_penalty: float — recommended score penalty
      - recommend_switch: bool — alias for ``severe`` (audit convenience)

    ponytail: the canonical key names
    (``severe``, ``categories``) match what the
    bot's ``choose_move`` reads from this dict.
    Changing them would break the audit wiring.
    """
    result = {
        "severe": False,
        "categories": [],
        "reason": "",
        "score_penalty": 0.0,
        "recommend_switch": False,
    }
    if not boosts:
        return result
    severity_thresholds = {
        "mild": getattr(config, "stat_drop_mild_threshold", 1),
        "moderate": getattr(config, "stat_drop_moderate_threshold", 2),
        "severe": getattr(config, "stat_drop_severe_threshold", 3),
    }
    worst = boosts.get("worst_stage", 0)
    total = boosts.get("total_severity", 0)
    if worst >= severity_thresholds["severe"]:
        result["severe"] = True
        result["recommend_switch"] = True
        result["score_penalty"] = 50.0
        result["reason"] = "worst_stage_severe"
    elif worst >= severity_thresholds["moderate"]:
        result["severe"] = True
        result["recommend_switch"] = True
        result["score_penalty"] = 25.0
        result["reason"] = "worst_stage_moderate"
    elif total >= severity_thresholds["moderate"]:
        result["recommend_switch"] = True
        result["score_penalty"] = 15.0
        result["reason"] = "total_severity_moderate"
    elif worst >= severity_thresholds["mild"] or total > 0:
        result["score_penalty"] = 5.0
        result["reason"] = "mild_drops"
    # Populate categories from the worst_stat / per-stat drops.
    if isinstance(boosts, dict):
        for key, val in boosts.items():
            if key.endswith("_minus") and isinstance(val, int) and val > 0:
                # Translate ``attack_minus`` -> ``attack``.
                cat = key[: -len("_minus")]
                if cat and cat not in result["categories"]:
                    result["categories"].append(cat)
    return result


def evaluate_stat_drop_switch_pressure(
    config, pokemon, ally, opponent, battle, player
) -> dict:
    """Evaluate whether stat drops warrant switching out.

    Uses only visible current boosts, no historical tracking.
    Returns dict with:
      - pressure_score: float (higher = more pressure to switch)
      - recommend_switch: bool
      - worst_stat: str
      - severity: str
      - reason: str
    """
    result = {
        "pressure_score": 0.0,
        "recommend_switch": False,
        "worst_stat": "",
        "severity": "none",
        "reason": "",
    }
    if not pokemon:
        return result
    boosts = summarize_negative_boosts(pokemon)
    if not boosts["is_severely_dropped"] and boosts["total_severity"] == 0:
        return result
    # Build a fake "orders_slot" for classify_stat_drop_severity.
    fake_orders_slot = []
    classification = classify_stat_drop_severity(boosts, config, fake_orders_slot)
    result["severity"] = (
        "severe" if classification["severe"] else "none"
    )
    result["worst_stat"] = boosts.get("worst_stat", "")
    result["pressure_score"] = classification["score_penalty"]
    result["recommend_switch"] = classification["recommend_switch"]
    if classification["reason"]:
        result["reason"] = classification["reason"]
    # Heavier pressure if the dropped stat is the one that matters for
    # this Pokemon's role (e.g. physical attacker with attack drops).
    worst_stat = boosts.get("worst_stat", "")
    if worst_stat in ("atk", "spa") and opponent:
        # Incoming threat from opponent; check if the dropped stat matters
        try:
            base_power = 0
            cat = None
            for move in (player.check_move_will_ko and [] or []):
                base_power = getattr(move, "base_power", 0)
                cat = getattr(move, "category", None)
                break
            if base_power >= 80:
                result["pressure_score"] += 10.0
                result["reason"] = result.get("reason", "") + "+incoming_threat"
        except Exception:
            pass
    return result
