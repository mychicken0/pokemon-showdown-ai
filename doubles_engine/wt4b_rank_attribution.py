"""Phase WT-4b — Score-rank attribution helper.

This module provides pure analysis helpers for
attributing why a Weather/Terrain setter is or is
not selected after the WT-3 bonus is applied.

It is **analysis-only** — it does not modify the
scoring path, the bot config, or production
behavior.

The attribution flow:
1. For each turn, walk the audit JSONL.
2. For each legal setter, compute the WT-3 bonus.
3. Classify the reason for no-selection (if any).
4. Compute the "would-have-been" rank after bonus.
5. Output a JSON-friendly summary.

Key functions:

* `compute_wt_bonus(order_id, active_idx, battle_state, config)`:
  returns (bonus, reason) using the WT-3 helper.
* `classify_no_selection_reason(bonus, reason, base_score, selected_score)`:
  returns a reason string for why the setter was
  not selected.
* `attribute_turn(turn, battle_tag, slot, setter_move_id, config)`:
  returns a JSON-friendly dict with all attribution
  fields for a single turn + setter.
"""

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from doubles_engine.wt3_weather_terrain_positive import (
    get_weather_terrain_positive_bonus,
    is_wt3_setter_move,
    WT3_SETTER_MOVE_IDS,
    WEATHER_SETTER_IDS,
    TERRAIN_SETTER_IDS,
    RAIN_DANCE,
    SUNNY_DAY,
    SANDSTORM,
    SNOWSCAPE,
    HAIL,
    ELECTRIC_TERRAIN,
    GRASSY_TERRAIN,
    MISTY_TERRAIN,
    PSYCHIC_TERRAIN,
)


# Reason codes for no-selection
REASON_NO_SYNERGY = "no_positive_synergy"
REASON_REDUNDANT = "redundant_setter"
REASON_OPP_BENEFITS = "opponent_benefits_more"
REASON_FLAG_OFF = "wt_flag_off"
REASON_NOT_SETTER = "not_a_wt_setter"
REASON_SCORE_BELOW_SELECTED = "score_still_below_selected"
REASON_NO_BASE_SCORE = "no_base_score"
REASON_RANK_IMPROVED = "rank_improved"
REASON_RANK_NOT_IMPROVED = "rank_not_improved"
REASON_RANK_FIRST = "rank_first"
REASON_BONUS_ZERO = "bonus_zero"


def compute_wt_bonus(
    move_id: str,
    active_idx: int,
    battle: Any,
    config: Any,
) -> Tuple[float, str]:
    """Compute the WT-3 bonus for a setter order.
    Returns (bonus, reason).
    """
    from poke_env.player.battle_order import SingleBattleOrder
    norm = _norm_move_id(move_id)
    if norm not in WT3_SETTER_MOVE_IDS:
        return 0.0, REASON_NOT_SETTER
    # Build a minimal order
    from poke_env.battle.move import Move
    from poke_env.player.battle_order import SingleBattleOrder
    try:
        move = Move(norm, gen=9)
    except Exception:
        return 0.0, REASON_NOT_SETTER
    order = SingleBattleOrder(move)
    return get_weather_terrain_positive_bonus(
        order, active_idx, battle, config=config
    )


def _norm_move_id(mid: Any) -> str:
    if mid is None:
        return ""
    s = str(mid).lower()
    return (
        s.replace(" ", "").replace("-", "")
        .replace("_", "").replace("'", "")
    )


def classify_no_selection_reason(
    bonus: float,
    reason: str,
    base_score: float,
    selected_score: float,
) -> str:
    """Classify why a setter was not selected.
    Returns a reason string.
    """
    if bonus <= 0:
        if "redundant" in reason:
            return REASON_REDUNDANT
        if "opponent_benefit" in reason:
            return REASON_OPP_BENEFITS
        if "flag" in reason or not reason:
            return REASON_FLAG_OFF
        return REASON_NO_SYNERGY
    # Bonus > 0 but still not selected
    final_score = base_score + bonus
    if final_score < selected_score:
        return REASON_SCORE_BELOW_SELECTED
    return REASON_RANK_NOT_IMPROVED


def _get_setter_legal_in_turn(turn: Dict[str, Any]) -> List[Tuple[int, str]]:
    """Return list of (slot_idx, setter_move_id) for
    all legal setters in this turn.
    """
    out: List[Tuple[int, str]] = []
    for slot_key, slot_idx in (
        ("v4a_legal_action_keys_slot0", 0),
        ("v4a_legal_action_keys_slot1", 1),
    ):
        for k in turn.get(slot_key, []):
            if (
                isinstance(k, (list, tuple))
                and len(k) >= 2
                and str(k[0]) == "move"
            ):
                mid = _norm_move_id(k[1])
                if mid in WT3_SETTER_MOVE_IDS:
                    out.append((slot_idx, mid))
    return out


def _get_selected_setter(turn: Dict[str, Any]) -> Optional[Tuple[int, str]]:
    """Return (slot_idx, setter_move_id) if a setter
    was selected, else None.
    """
    for slot_idx, k in enumerate(
        turn.get("v4a_selected_joint_key", [])
    ):
        if (
            isinstance(k, (list, tuple))
            and len(k) >= 2
            and str(k[0]) == "move"
        ):
            mid = _norm_move_id(k[1])
            if mid in WT3_SETTER_MOVE_IDS:
                return (slot_idx, mid)
    return None


def _build_battle_mock_from_turn(turn: Dict[str, Any]) -> Any:
    """Build a minimal MagicMock battle for the WT
    helper from an audit turn.
    """
    from unittest.mock import MagicMock
    battle = MagicMock()
    battle.weather = None
    # Try to read weather from state_snapshot
    state = turn.get("state_snapshot", {}) or {}
    weather_str = state.get("weather", "")
    if weather_str and weather_str != "none":
        if isinstance(weather_str, list) and weather_str:
            battle.weather = MagicMock()
            battle.weather.__str__ = (
                lambda self: weather_str[0].upper()
            )
    battle.fields = None
    # Get opp types and moves from opp_actions
    opp_actions = turn.get("opp_actions", {}) or {}
    opp_mons = opp_actions.get("opp_active_mons", []) or []
    battle.opponent_active_pokemon = []
    for mon_data in opp_mons:
        if not isinstance(mon_data, dict):
            continue
        opp = MagicMock()
        opp.types = [
            str(t).lower()
            for t in (mon_data.get("types") or [])
        ]
        opp.moves = {
            str(m).lower(): True
            for m in (mon_data.get("moves") or [])
        }
        battle.opponent_active_pokemon.append(opp)
    battle.opponent_team = None
    # Our active types (our_active is a list of slot
    # dicts, not a single dict)
    our_active_list = turn.get("our_active", []) or []
    our_types: List[str] = []
    if isinstance(our_active_list, list):
        for slot_data in our_active_list:
            if isinstance(slot_data, dict):
                slot_types = slot_data.get("types") or []
                for t in slot_types:
                    our_types.append(str(t).lower())
    battle.active_pokemon = [MagicMock(), MagicMock()]
    battle.active_pokemon[0].types = our_types
    battle.active_pokemon[1].types = our_types
    battle.available_moves = [[], []]
    return battle


def attribute_turn_setter(
    turn: Dict[str, Any],
    battle_tag: str,
    slot_idx: int,
    setter_move_id: str,
    config: Any,
    selected_score: float,
    selected_move_id: str,
) -> Dict[str, Any]:
    """Compute attribution for a single turn + setter.
    Returns a JSON-friendly dict.
    """
    battle = _build_battle_mock_from_turn(turn)
    bonus, reason = compute_wt_bonus(
        setter_move_id, slot_idx, battle, config
    )
    # Estimate base score for the setter
    # (from the audit's setter_move_raw_score)
    raw_setter = turn.get("setter_move_raw_score", {}) or {}
    norm = _norm_move_id(setter_move_id)
    base_score = float(raw_setter.get(norm, 0) or 0)
    final_score = base_score + bonus
    # Determine if this setter was selected
    sel_setter = _get_selected_setter(turn)
    was_selected = (
        sel_setter is not None
        and sel_setter[1] == setter_move_id
        and sel_setter[0] == slot_idx
    )
    # Classify reason
    if was_selected:
        no_sel_reason = REASON_RANK_FIRST
    else:
        no_sel_reason = classify_no_selection_reason(
            bonus, reason, base_score, selected_score
        )
    return {
        "battle_tag": battle_tag,
        "turn": turn.get("turn"),
        "slot": slot_idx,
        "setter_move": setter_move_id,
        "selected_move": selected_move_id,
        "selected_score": selected_score,
        "wt_bonus": bonus,
        "wt_reason": reason,
        "base_score": base_score,
        "final_score_after_wt": final_score,
        "was_selected": was_selected,
        "no_selection_reason": no_sel_reason,
        "score_gap_to_selected": selected_score - final_score,
    }


def attribute_audit_file(
    audit_path: str,
    config: Any,
) -> Dict[str, Any]:
    """Walk an audit JSONL and produce attribution
    summary for all legal setters.
    """
    summary: Dict[str, Any] = {
        "n_turns": 0,
        "n_legal_setters": 0,
        "n_synergy_positive_setters": 0,
        "n_selected_setters": 0,
        "n_redundant_setters": 0,
        "n_opp_benefits_setters": 0,
        "n_no_synergy_setters": 0,
        "n_score_below_setters": 0,
        "n_flag_off_setters": 0,
        "setter_details": [],
        "reason_counts": {},
    }
    if not os.path.exists(audit_path):
        return summary
    with open(audit_path) as f:
        for line in f:
            try:
                battle = json.loads(line)
            except json.JSONDecodeError:
                continue
            bt = battle.get("battle_tag", "?")
            for turn in battle.get("audit_turns", []):
                summary["n_turns"] += 1
                legal_setters = _get_setter_legal_in_turn(turn)
                if not legal_setters:
                    continue
                selected_score = (
                    float(turn.get("selected_score", 0) or 0)
                )
                sel_key = turn.get(
                    "v4a_selected_joint_key", []
                )
                # Build a string representation of the
                # selected joint
                sel_strs = []
                for k in sel_key:
                    if isinstance(k, (list, tuple)) and len(k) >= 2:
                        sel_strs.append(
                            f"{k[0]}:{_norm_move_id(k[1])}"
                        )
                selected_move_id = (
                    ", ".join(sel_strs) if sel_strs else ""
                )
                for slot_idx, setter_id in legal_setters:
                    summary["n_legal_setters"] += 1
                    attr = attribute_turn_setter(
                        turn,
                        bt,
                        slot_idx,
                        setter_id,
                        config,
                        selected_score,
                        selected_move_id,
                    )
                    summary["setter_details"].append(attr)
                    if attr["was_selected"]:
                        summary["n_selected_setters"] += 1
                    if attr["wt_bonus"] > 0:
                        summary["n_synergy_positive_setters"] += 1
                    reason = attr["no_selection_reason"]
                    summary["reason_counts"][reason] = (
                        summary["reason_counts"].get(reason, 0)
                        + 1
                    )
                    if reason == REASON_REDUNDANT:
                        summary["n_redundant_setters"] += 1
                    elif reason == REASON_OPP_BENEFITS:
                        summary["n_opp_benefits_setters"] += 1
                    elif reason == REASON_NO_SYNERGY:
                        summary["n_no_synergy_setters"] += 1
                    elif reason == REASON_SCORE_BELOW_SELECTED:
                        summary["n_score_below_setters"] += 1
                    elif reason == REASON_FLAG_OFF:
                        summary["n_flag_off_setters"] += 1
    # Limit details to first 20 for readability
    summary["setter_details_limited"] = (
        summary["setter_details"][:20]
    )
    summary["n_setter_details_total"] = len(
        summary["setter_details"]
    )
    del summary["setter_details"]
    return summary
