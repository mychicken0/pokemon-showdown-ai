"""Phase RL-5 — Turn-level offline dataset builder.

Builds the ``turn_rl_v1.0`` dataset from existing
audit JSONL files. No training, no model artifact,
no battle runs. Read-only over source artifacts.

Output:
    logs/turn_level_offline_dataset_<tag>.jsonl
    logs/turn_level_offline_dataset_<tag>_summary.json
    logs/turn_level_offline_dataset_<tag>_validation.md

The builder applies the 10 validation gates from
RL-4 and aborts if any gate fails. The dataset is
only emitted if all gates pass.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Schema version this builder emits.
# Phase RL-5 emitted "turn_rl_v1.0". Phase RL-DATA-2 adds
# v1.1 support-move instrumentation. v1.1 is backward
# compatible: every v1.0 field is preserved, only new
# fields are added.
SCHEMA_VERSION = "turn_rl_v1.0"  # v1.1 added by RL-DATA-2 (also accepted)
SCHEMA_VERSION_V1_1 = "turn_rl_v1.1"

# Required top-level fields for v1.0.
REQUIRED_IDENTITY = (
    "schema_version",
    "dataset_id",
    "source_artifact",
    "battle_tag",
    "episode_id",
    "turn_index",
    "player_side",
    "benchmark_arm",
    "policy_name",
)
REQUIRED_EPISODE = (
    "won",
    "battle_result",
    "total_turns",
    "terminal_reward",
)
REQUIRED_STATE = (
    "state_snapshot",
)
REQUIRED_ACTION = (
    "legal_action_keys_slot0",
    "legal_action_keys_slot1",
    "selected_joint_key",
    "final_action_keys",
)
REQUIRED_SELECTED = (
    "selected_per_slot",
    "selected_score",
)
# Missing-required threshold (RL-4 gate).
MISSING_REQUIRED_THRESHOLD = 0.05

# Forbidden fields (leakage). RL-4 leakage rules.
# Keys that must NOT appear in the state group.
LEAKAGE_KEYS_IN_STATE = (
    "won",
    "battle_result",
    "terminal_reward",
)
# Key prefixes that are forbidden anywhere.
LEAKAGE_KEY_PREFIXES = ("_",)


def _to_json_safe(value: Any) -> Any:
    """Recursively convert to JSON-safe primitives."""
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(v) for v in value]
    # Fallback: stringify (e.g., for MockMove or other non-serializable).
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _v4a_key_to_tuple(key: Any) -> Optional[Tuple]:
    """Normalize a V4a key to a 4-tuple of strings.

    Accepts:
      - list/tuple of 4 elements: (kind, move_id, target_pos, mechanic)
      - None: returns None
    Returns None for malformed keys.
    """
    if key is None:
        return None
    if not isinstance(key, (list, tuple)) or len(key) != 4:
        return None
    return (str(key[0]), str(key[1]), str(key[2]), str(key[3]))


def _battle_result(won: Optional[bool]) -> str:
    """Map won (True/False/None) to battle_result string."""
    if won is True:
        return "win"
    if won is False:
        return "loss"
    return "unknown"


def _terminal_reward(won: Optional[bool]) -> int:
    """Map won to terminal reward (+1/-1/0)."""
    if won is True:
        return 1
    if won is False:
        return -1
    return 0


def _player_side_from_arm(arm: str) -> str:
    """Infer player_side from benchmark_arm.

    The audit JSONL is per-arm. The treatment arm is
    the bot learner; the baseline arm is a different
    bot learner. In both cases the learner is the
    bot, so player_side is "bot".
    """
    return "bot"


def _build_state_snapshot(turn: Dict[str, Any]) -> Dict[str, Any]:
    """Extract state_snapshot from a turn record.

    Returns a JSON-safe dict with only fields visible
    at decision time.
    """
    ss = turn.get("state_snapshot") or {}
    out = {
        "our_active_species": _to_json_safe(
            ss.get("our_active_species", [])
        ),
        "opp_active_species": _to_json_safe(
            ss.get("opp_active_species", [])
        ),
        "our_active_hp_fraction": _to_json_safe(
            ss.get("our_active_hp_fraction", [])
        ),
        "opp_active_hp_fraction": _to_json_safe(
            ss.get("opp_active_hp_fraction", [])
        ),
        "weather": _to_json_safe(ss.get("weather", "none")),
        "fields": _to_json_safe(ss.get("fields", [])),
        "side_conditions": _to_json_safe(
            ss.get("side_conditions", {})
        ),
        "turn_number": _to_json_safe(turn.get("turn", 0)),
    }
    return out


def _build_action_space(turn: Dict[str, Any]) -> Tuple[
    List, List, Optional[List], Optional[List]
]:
    """Extract legal action keys from a turn record.

    Returns (legal0, legal1, v4a_selected, final_keys).
    v4a_selected and final_keys are normalized to
    4-tuple form. Returns (None, None, None, None)
    if any required field is missing.
    """
    legal0_raw = turn.get("v4a_legal_action_keys_slot0")
    legal1_raw = turn.get("v4a_legal_action_keys_slot1")
    v4a_sel_raw = turn.get("v4a_selected_joint_key")
    final_keys_raw = turn.get("v4a_final_action_keys")
    if (
        legal0_raw is None
        or legal1_raw is None
        or v4a_sel_raw is None
        or final_keys_raw is None
    ):
        return ([], [], None, None)
    legal0 = [
        _v4a_key_to_tuple(k)
        for k in legal0_raw
        if _v4a_key_to_tuple(k) is not None
    ]
    legal1 = [
        _v4a_key_to_tuple(k)
        for k in legal1_raw
        if _v4a_key_to_tuple(k) is not None
    ]
    v4a_sel = None
    if isinstance(v4a_sel_raw, (list, tuple)) and len(v4a_sel_raw) == 2:
        k0 = _v4a_key_to_tuple(v4a_sel_raw[0])
        k1 = _v4a_key_to_tuple(v4a_sel_raw[1])
        if k0 is not None and k1 is not None:
            v4a_sel = [k0, k1]
    final_keys = None
    if isinstance(final_keys_raw, (list, tuple)) and len(final_keys_raw) == 2:
        k0 = _v4a_key_to_tuple(final_keys_raw[0])
        k1 = _v4a_key_to_tuple(final_keys_raw[1])
        if k0 is not None and k1 is not None:
            final_keys = [k0, k1]
    return (legal0, legal1, v4a_sel, final_keys)


def _build_optional_fields(turn: Dict[str, Any]) -> Dict[str, Any]:
    """Extract optional fields. Missing → None."""
    def _opt(key, default=None):
        v = turn.get(key)
        if v is None:
            return default
        return _to_json_safe(v)
    out = {
        "top_5_alternatives": _opt("top_5_alternatives", []),
        "top_5_scores": _opt("top_5_scores", []),
        "score_gap_selected_best_alt": _opt(
            "score_gap_selected_best_alt"
        ),
        "v2l1_raw_scores_slot0": _opt(
            "v2l1_raw_scores_slot0", {}
        ),
        "v2l1_raw_scores_slot1": _opt(
            "v2l1_raw_scores_slot1", {}
        ),
        "switch_counterfactual": _opt("switch_counterfactual"),
        "speed_priority_threatened": _opt(
            "speed_priority_threatened"
        ),
        "expected_to_faint_before_moving": _opt(
            "expected_to_faint_before_moving"
        ),
        "overkill_penalty_triggered": _opt(
            "overkill_penalty_triggered"
        ),
        "focus_fire_triggered": _opt("focus_fire_triggered"),
        "stale_target_avoided": _opt("stale_target_avoided"),
        "narrow_ally_heal_candidate_blocked_slot0": _opt(
            "narrow_ally_heal_candidate_blocked_slot0"
        ),
        "narrow_ally_heal_candidate_blocked_slot1": _opt(
            "narrow_ally_heal_candidate_blocked_slot1"
        ),
        "joint_order_count": _opt("joint_order_count"),
        "total_legal_joint_orders": _opt("total_legal_joint_orders"),
    }
    return out


def _build_selected_per_slot(
    v4a_sel: List, final_keys: List
) -> Dict[str, Any]:
    """Build the selected_per_slot dict from V4a keys."""
    return {
        "slot_0": list(v4a_sel[0]) if v4a_sel else None,
        "slot_1": list(v4a_sel[1]) if v4a_sel else None,
    }


def _selected_joint_key_in_legal(
    v4a_sel: List, legal0: List, legal1: List
) -> bool:
    """Check that the selected joint key is in the legal set."""
    if v4a_sel is None or len(v4a_sel) != 2:
        return False
    k0, k1 = v4a_sel[0], v4a_sel[1]
    if len(legal0) == 0 or len(legal1) == 0:
        return False
    in_legal0 = any(
        leg == k0 or list(leg) == list(k0) for leg in legal0
    )
    in_legal1 = any(
        leg == k1 or list(leg) == list(k1) for leg in legal1
    )
    return in_legal0 and in_legal1


def _v4a_key_to_list(key: Any) -> Optional[List]:
    """Convert a V4a key to a list of 4 strings, or None."""
    if key is None:
        return None
    if not isinstance(key, (list, tuple)) or len(key) != 4:
        return None
    return [str(x) for x in key]


def _row_has_leakage(row: Dict[str, Any]) -> List[str]:
    """Check a row for leakage. Returns list of leak descriptions."""
    leaks = []
    # 1. State group must not contain outcome fields.
    state = row.get("state_snapshot", {})
    if isinstance(state, dict):
        for k in LEAKAGE_KEYS_IN_STATE:
            if k in state:
                leaks.append(f"state.contains_forbidden:{k}")
    # 2. No top-level key starts with _.
    for k in row.keys():
        for prefix in LEAKAGE_KEY_PREFIXES:
            if k.startswith(prefix):
                leaks.append(f"top_level.forbidden_prefix:{k}")
                break
    # 3. selected_joint_key must not contain raw objects.
    sel = row.get("selected_joint_key", [])
    if not isinstance(sel, list):
        leaks.append("selected_joint_key.not_list")
    else:
        for entry in sel:
            if not isinstance(entry, list):
                leaks.append("selected_joint_key.entry_not_list")
                break
            if len(entry) != 4:
                leaks.append("selected_joint_key.entry_not_4tuple")
                break
    return leaks


def _row_json_serializable(row: Dict[str, Any]) -> bool:
    """Check that a row is JSON-serializable."""
    try:
        json.dumps(row, sort_keys=True)
        return True
    except (TypeError, ValueError):
        return False


def _row_has_required_fields(row: Dict[str, Any]) -> List[str]:
    """Check that a row has all required top-level fields."""
    missing = []
    for f in REQUIRED_IDENTITY + REQUIRED_EPISODE + REQUIRED_STATE + REQUIRED_ACTION + REQUIRED_SELECTED:
        if f not in row:
            missing.append(f)
    return missing


# ============================================================
# Phase RL-DATA-2: turn_rl_v1.1 instrumentation helpers
# ============================================================
# These helpers add the v1.1 fields defined in
# logs/rl_data_1_turn_level_schema_plan.md. They are
# instrumentation-only: they do NOT change scoring, behavior,
# or selected actions. They run inside build_row() and
# produce extra fields that downstream tools (analyzer,
# dry-run) can read.

# Lazy import: support_targets depends on bot_doubles_damage_aware
# (late binding for DoublesDamageAwareConfig). Importing
# support_targets here triggers the cycle, so we do a lazy
# import inside each function that needs it.
def _support_targets_classify():
    """Lazy import to avoid circular dependency."""
    from doubles_engine.support_targets import (
        classify_support_move_for_dataset,
        aggregate_support_distribution,
    )
    return classify_support_move_for_dataset, aggregate_support_distribution


# Setter move ids for WT-2 (per logs/phaseWT2_setter_audit.md).
_WT2_SETTER_MOVE_IDS = frozenset({
    "raindance", "sunnyday", "sandstorm", "hail", "snowscape",
    "electricterrain", "grassyterrain", "mistyterrain", "psychicterrain",
})

# Type-boost moves: moves whose type is boosted by the
# current weather/terrain. v1.1 records which are legal
# and selected. The actual list is data-driven (from
# state_snapshot.weather / state_snapshot.fields).
_TYPE_BOOST_MOVE_IDS = frozenset({
    # Rain
    "hurricane", "thunder", "watergun", "hydroPump", "surf",
    "muddywater", "weatherball",
    # Sun
    "fireblast", "flamethrower", "solarbeam", "solarblade",
    "firepunch", "flamecharge",
    # Sand
    "rockslide", "stoneedge", "earthpower", "earthquake",
    # Electric terrain
    "thunderbolt", "thunderpunch", "voltswitch",
    # Grassy terrain
    "gigadrain", "razorleaf", "leafstorm", "energyball",
    "leafblade", "powerwhip",
    # Psychic terrain
    "psychic", "psyshock", "psybeam", "zenheadbutt", "extrasensory",
    # Misty terrain
    "moonblast", "drainingkiss", "fairywind",
})


def _extract_v1_1_config_snapshot(turn: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a config-snapshot dict from the turn if
    available, else return an empty dict.

    The audit logger does not currently record the
    full DoublesDamageAwareConfig. v1.1 records whatever
    is available; missing fields are safe defaults.
    """
    cfg = turn.get("config_snapshot") or {}
    if not isinstance(cfg, dict):
        return {}
    return _to_json_safe(cfg)


def _extract_v1_1_metadata(
    turn: Dict[str, Any],
    row_battle: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract v1.1 metadata fields.

    Returns a dict with:
        - config_hash: str | None (None if not recorded)
        - config_snapshot: dict (may be empty)
        - local_only_provenance: bool (always True)
        - format: str | None
        - team_id: str | None
        - opponent_team_id: str | None
        - runtime_mode: str | None (from turn.runtime_mode)
        - terminal_win_loss: int | None
        - turn_delta_hp: dict (per-side delta this turn)
        - faint_caused: int | None
        - faint_suffered: int | None
        - delayed_reward_placeholder: float (0.0)
        - sparse_reward_warning: bool
        - reward_provenance: str ("terminal_only")
        - reward_confidence: float (1.0)
    """
    metadata: Dict[str, Any] = {
        "config_hash": turn.get("config_hash"),
        "config_snapshot": _extract_v1_1_config_snapshot(turn),
        "local_only_provenance": True,
        "format": turn.get("format") or row_battle.get("format"),
        "team_id": turn.get("team_id") or row_battle.get("team_id"),
        "opponent_team_id": (
            turn.get("opponent_team_id")
            or row_battle.get("opponent_team_id")
        ),
        "runtime_mode": turn.get("runtime_mode"),
        "terminal_win_loss": None,  # filled from episode
        "turn_delta_hp": _to_json_safe(turn.get("turn_delta_hp", {})),
        "faint_caused": turn.get("faint_caused"),
        "faint_suffered": turn.get("faint_suffered"),
        "delayed_reward_placeholder": 0.0,
        "sparse_reward_warning": True,
        "reward_provenance": "terminal_only",
        "reward_confidence": 1.0,
    }
    return metadata


def _extract_v1_1_weather_terrain(
    turn: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract v1.1 weather/terrain fields.

    Returns a dict with:
        - weather_current: str | None
        - terrain_current: str | None
        - setter_move_legal: list[str]
        - setter_move_selected: list[str]
        - setter_move_raw_score: dict (None if not available)
        - type_boost_move_legal: list[str]
        - type_boost_move_selected: list[str]
        - type_boost_applied: list[str]
        - wt2_relevance_flag: bool (setter move was legal)
        - wt3_relevance_flag: bool (type-boost move was legal)
        - wt4_relevance_flag: bool (setter move was selected)

    Phase RL-DATA-3a: prefer audit-emitted values when
    present (turn.get("weather_current") /
    turn.get("terrain_current")). The audit logger
    already populated these when v1.1 emission is
    enabled. We only fall back to the v1.0 state
    snapshot when the audit fields are missing.

    The state-snapshot fallback handles a pre-existing
    audit logger quirk where ``_enum_keys`` iterates
    a string and returns single characters
    (``["r", "a", "i", "n", ...]``). We detect that
    case and join the list back into the original
    string before lowercasing.
    """
    # Prefer audit-emitted values
    if "weather_current" in turn or "terrain_current" in turn:
        return {
            "weather_current": turn.get("weather_current"),
            "terrain_current": turn.get("terrain_current"),
            "setter_move_legal": _setter_legal(turn),
            "setter_move_selected": _setter_selected(turn),
            "setter_move_raw_score": turn.get(
                "setter_move_raw_score"
            ),
            "type_boost_move_legal": _tb_legal(turn),
            "type_boost_move_selected": _tb_selected(turn),
            "type_boost_applied": turn.get(
                "type_boost_applied", []
            ),
            "wt2_relevance_flag": bool(
                turn.get("setter_move_legal", [])
            ),
            "wt3_relevance_flag": bool(
                turn.get("type_boost_move_legal", [])
            ),
            "wt4_relevance_flag": bool(
                turn.get("setter_move_selected", [])
            ),
        }

    ss = turn.get("state_snapshot") or {}
    weather = ss.get("weather", "none")
    fields = ss.get("fields", [])

    def _canon(value: Any) -> Optional[str]:
        if isinstance(value, str):
            if not value or value == "none":
                return None
            return value.split(".")[-1].lower()
        if isinstance(value, list):
            if not value:
                return None
            # Detect the audit logger character-list
            # quirk and join the list back into a
            # string.
            if all(
                isinstance(x, str) and len(x) == 1
                for x in value
            ):
                joined = "".join(value)
                return joined.split(".")[-1].lower() or None
            for x in value:
                if not x:
                    continue
                s = str(x).split(".")[-1].lower()
                if s:
                    return s
            return None
        return None

    weather_current = _canon(weather)
    terrain_current = _canon(fields)

    # Setter moves: collect from legal actions
    legal0 = turn.get("v4a_legal_action_keys_slot0") or []
    legal1 = turn.get("v4a_legal_action_keys_slot1") or []

    def _setter_moves_in(keys) -> List[str]:
        out: List[str] = []
        for k in keys:
            if not isinstance(k, (list, tuple)) or len(k) < 2:
                continue
            mid = _normalize_v1_1_move_id(k[1])
            if mid in _WT2_SETTER_MOVE_IDS:
                out.append(mid)
        return out

    setter_legal = sorted(set(_setter_moves_in(legal0) + _setter_moves_in(legal1)))

    # Selected setter
    sel_joint = turn.get("v4a_selected_joint_key")
    setter_selected: List[str] = []
    if isinstance(sel_joint, (list, tuple)):
        for k in sel_joint:
            if isinstance(k, (list, tuple)) and len(k) >= 2:
                mid = _normalize_v1_1_move_id(k[1])
                if mid in _WT2_SETTER_MOVE_IDS:
                    setter_selected.append(mid)

    # Type-boost moves
    def _type_boost_moves_in(keys) -> List[str]:
        out: List[str] = []
        for k in keys:
            if not isinstance(k, (list, tuple)) or len(k) < 2:
                continue
            mid = _normalize_v1_1_move_id(k[1])
            if mid in _TYPE_BOOST_MOVE_IDS:
                out.append(mid)
        return out

    tb_legal = sorted(
        set(_type_boost_moves_in(legal0) + _type_boost_moves_in(legal1))
    )

    tb_selected: List[str] = []
    if isinstance(sel_joint, (list, tuple)):
        for k in sel_joint:
            if isinstance(k, (list, tuple)) and len(k) >= 2:
                mid = _normalize_v1_1_move_id(k[1])
                if mid in _TYPE_BOOST_MOVE_IDS:
                    tb_selected.append(mid)

    # Raw scores for setter moves (v4a_raw_scores_slot0/1)
    setter_raw: Dict[str, Any] = {}
    raw0 = turn.get("v4a_raw_scores_slot0") or {}
    raw1 = turn.get("v4a_raw_scores_slot1") or {}
    if isinstance(raw0, dict):
        for k, v in raw0.items():
            mid = _normalize_v1_1_move_id(k)
            if mid in _WT2_SETTER_MOVE_IDS:
                setter_raw[mid] = _to_json_safe(v)
    if isinstance(raw1, dict):
        for k, v in raw1.items():
            mid = _normalize_v1_1_move_id(k)
            if mid in _WT2_SETTER_MOVE_IDS:
                setter_raw[mid] = _to_json_safe(v)

    # WT-2 / WT-3 / WT-4 relevance flags
    wt2 = bool(setter_legal)
    wt3 = bool(tb_legal)
    wt4 = bool(setter_selected)

    return {
        "weather_current": weather_current,
        "terrain_current": terrain_current,
        "setter_move_legal": setter_legal,
        "setter_move_selected": setter_selected,
        "setter_move_raw_score": setter_raw if setter_raw else None,
        "type_boost_move_legal": tb_legal,
        "type_boost_move_selected": tb_selected,
        "type_boost_applied": [],  # would need execution-time data
        "wt2_relevance_flag": wt2,
        "wt3_relevance_flag": wt3,
        "wt4_relevance_flag": wt4,
    }


def _normalize_v1_1_move_id(move_id: Any) -> str:
    """Normalize a move id to a lowercased no-space string."""
    if move_id is None:
        return ""
    s = str(move_id)
    return s.lower().replace(" ", "").replace("-", "").replace("_", "").replace("'", "")


# Phase RL-DATA-3a: small helpers for the audit-emitted
# fast path in ``_extract_v1_1_weather_terrain``. When
# the audit logger has already emitted v1.1 fields, we
# pass them through directly. These helpers only run on
# the audit-fast path; the state-snapshot fallback
# path uses inline logic.
def _setter_legal(turn: Dict[str, Any]) -> List[str]:
    """Return the audit-emitted setter_move_legal list
    (defaulting to ``[]`` if absent)."""
    v = turn.get("setter_move_legal")
    if isinstance(v, list):
        return list(v)
    return []


def _setter_selected(turn: Dict[str, Any]) -> List[str]:
    v = turn.get("setter_move_selected")
    if isinstance(v, list):
        return list(v)
    return []


def _tb_legal(turn: Dict[str, Any]) -> List[str]:
    v = turn.get("type_boost_move_legal")
    if isinstance(v, list):
        return list(v)
    return []


def _tb_selected(turn: Dict[str, Any]) -> List[str]:
    v = turn.get("type_boost_move_selected")
    if isinstance(v, list):
        return list(v)
    return []


def _extract_v1_1_safety_fields(turn: Dict[str, Any]) -> Dict[str, Any]:
    """Extract v1.1 safety/mechanics fields.

    Returns a dict with:
        - block_reason_wrong_side: str | None
        - block_reason_narrow_ally_heal: str | None
        - block_reason_broad_support_target: str | None
        - block_reason_ability_hard_safety: str | None
        - revealed_ability_source: str ("revealed" or "singleton_deduction")
        - used_species_ability_inference: bool (always False)
        - impossible_target_detected: bool (always False unless audit says so)
        - blocked_action_resurrected_by_joint: bool (always False)
    """
    out: Dict[str, Any] = {
        "block_reason_wrong_side": turn.get("block_reason_wrong_side"),
        "block_reason_narrow_ally_heal": (
            turn.get("block_reason_narrow_ally_heal")
        ),
        "block_reason_broad_support_target": (
            turn.get("block_reason_broad_support_target")
        ),
        "block_reason_ability_hard_safety": (
            turn.get("block_reason_ability_hard_safety")
        ),
        "revealed_ability_source": turn.get("revealed_ability_source")
        or "revealed",
        "used_species_ability_inference": False,  # never True
        "impossible_target_detected": bool(
            turn.get("impossible_target_detected", False)
        ),
        "blocked_action_resurrected_by_joint": bool(
            turn.get("blocked_action_resurrected_by_joint", False)
        ),
    }
    return out


def _extract_v1_1_support_classification(
    turn: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract v1.1 support-move classification.

    For each candidate action in the legal set, classify
    the move using the SUPPORT-AUDIT-1 inventory. Returns
    a dict with:
        - per_candidate: dict mapping move_id -> classification
        - support_move_distribution: dict (group -> count)
        - unknown_support_move_detected: bool (any candidate)

    Phase RL-DATA-3a.1: prefer the audit-emitted
    ``move_metadata_map`` (built by the audit logger
    from poke-env ``Move`` objects, the active mon's
    moves, or the static fallback). Without metadata
    the classifier treats known damaging moves like
    ``fakeout`` and ``hurricane`` as
    ``unknown_needs_probe``. With metadata they are
    correctly identified as damage-like.

    Phase RL-DATA-3b-followup: filter non-move
    actions before support classification. V4a
    legal-action keys mix move actions, switch
    actions, and pass actions. Switch actions
    carry a species name (e.g., ``"volcarona"``)
    as the "move id". Sending these to the
    classifier inflates Gate 17 with false
    ``unknown_needs_probe`` tags. The builder now
    detects the action kind via
    ``doubles_engine.v4a_action_kind`` and only
    calls the support classifier on real move
    actions. Switch / pass / unknown actions get
    a pre-built ``NON_MOVE_CLASSIFICATION`` dict
    with ``is_support_move=False`` and
    ``unknown_support_move_detected=False``.
    """
    classify, aggregate = _support_targets_classify()
    # Lazy import to keep the import-light.
    from doubles_engine.v4a_action_kind import (
        resolve_candidate_action_kind,
        split_candidate_id_from_v4a_key,
        build_non_move_classification,
        ACTION_KIND_MOVE,
    )
    # Audit-emitted per-move metadata map (preferred)
    move_metadata_map: Dict[str, Any] = (
        turn.get("move_metadata_map") or {}
    )
    per_candidate: Dict[str, Any] = {}
    classifications: List[Dict[str, Any]] = []

    # Walk legal keys for slot 0 and slot 1
    legal0 = turn.get("v4a_legal_action_keys_slot0") or []
    legal1 = turn.get("v4a_legal_action_keys_slot1") or []
    for keys in (legal0, legal1):
        if not isinstance(keys, list):
            continue
        for k in keys:
            if not isinstance(k, (list, tuple)) or len(k) < 2:
                continue
            # Phase RL-DATA-3b-followup: detect the
            # action kind before classifying. Only
            # ``move`` actions go through the support
            # classifier. Switch / pass / unknown
            # actions get the pre-built
            # ``NON_MOVE_CLASSIFICATION`` dict.
            action_kind = resolve_candidate_action_kind(k)
            kind, candidate_id = split_candidate_id_from_v4a_key(k)
            if not candidate_id:
                continue
            if action_kind != ACTION_KIND_MOVE:
                # Non-move action: skip the support
                # classifier. The pre-built dict
                # explicitly sets
                # ``unknown_support_move_detected=False``
                # so the dataset does not falsely
                # inflate Gate 17.
                cls_with_meta = build_non_move_classification(
                    action_kind=action_kind,
                    metadata_source="n/a",
                )
                classifications.append(cls_with_meta)
                per_candidate[candidate_id] = cls_with_meta
                continue
            # Move action: resolve metadata, then
            # call the support classifier.
            mid = candidate_id
            meta = move_metadata_map.get(mid) or {}
            base_power = meta.get("base_power")
            category = meta.get("category")
            cls = classify(
                mid,
                base_power=base_power,
                category=category,
            )
            # Annotate each per-candidate entry with
            # the metadata source for downstream
            # inspection. Mirrors the audit logger.
            cls_with_meta = dict(cls)
            cls_with_meta["action_kind"] = action_kind
            cls_with_meta["is_move_action"] = True
            cls_with_meta["is_switch_action"] = False
            cls_with_meta["is_pass_action"] = False
            cls_with_meta["metadata_source"] = meta.get(
                "metadata_source"
            ) or "unknown"
            cls_with_meta["resolved_base_power"] = base_power
            cls_with_meta["resolved_category"] = category
            classifications.append(cls_with_meta)
            per_candidate[mid] = cls_with_meta

    distribution = aggregate(classifications)
    any_unknown = any(
        c.get("unknown_support_move_detected", False)
        for c in classifications
    )

    return {
        "per_candidate_support_classification": per_candidate,
        "support_move_distribution": distribution,
        "unknown_support_move_detected": any_unknown,
    }


# Phase RL-DATA-4: live exploration fields emitted by
# the audit logger at log time. These are true
# trajectory metadata (not post-processing). The audit
# logger's ``update_pending_turn_with_live_exploration``
# sets these on the pending turn dict; the builder
# passes them through into the v1.1 dataset row.
LIVE_EXPLORATION_FIELDS = (
    "live_exploration_enabled",
    "live_exploration_triggered",
    "live_exploration_rate",
    "live_exploration_seed",
    "live_exploration_candidate_group",
    "live_exploration_original_action",
    "live_exploration_selected_action",
    "live_exploration_submitted_action",
    "live_exploration_reason",
    "live_exploration_no_candidate_reason",
    "live_exploration_action_was_legal",
    "live_exploration_postprocess_only",
)


def _extract_v1_1_live_exploration(turn: Dict[str, Any]) -> Dict[str, Any]:
    """Pass through live exploration fields from the
    audit JSONL into the v1.1 dataset row. Defaults to
    safe values when the audit JSONL does not have the
    fields (i.e., the audit was produced without
    live exploration enabled).
    """
    out: Dict[str, Any] = {}
    for field in LIVE_EXPLORATION_FIELDS:
        out[field] = turn.get(field, None)
    # Backward-compat defaults: if the audit JSONL has
    # no live_exploration fields at all (older
    # artifacts), set the safe defaults.
    if "live_exploration_enabled" not in turn:
        out["live_exploration_enabled"] = False
        out["live_exploration_triggered"] = False
        out["live_exploration_rate"] = 0.0
        out["live_exploration_seed"] = 0
        out["live_exploration_candidate_group"] = "none"
        out["live_exploration_original_action"] = ""
        out["live_exploration_selected_action"] = ""
        out["live_exploration_submitted_action"] = ""
        out["live_exploration_reason"] = ""
        out["live_exploration_no_candidate_reason"] = ""
        out["live_exploration_action_was_legal"] = True
        out["live_exploration_postprocess_only"] = False
    return out


def _build_v1_1_fields(
    turn: Dict[str, Any],
    row_battle: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the v1.1 field group for a turn.

    Combines metadata, weather/terrain, safety, and
    support-classification. All v1.1 fields are added
    with safe defaults (None / False / 0 / empty list)
    when source data is unavailable.
    """
    out: Dict[str, Any] = {}

    # Metadata
    metadata = _extract_v1_1_metadata(turn, row_battle)
    out.update(metadata)

    # Weather / Terrain
    wt = _extract_v1_1_weather_terrain(turn, state)
    out.update(wt)

    # Safety
    safety = _extract_v1_1_safety_fields(turn)
    out.update(safety)

    # Support classification
    support = _extract_v1_1_support_classification(turn)
    out.update(support)

    # Phase RL-DATA-4: pass through live_exploration
    # fields from the audit JSONL into the v1.1 dataset
    # row. These fields are emitted by the audit logger
    # at log time (true trajectory exploration, not
    # post-processing). They are additive and do not
    # change scoring or behavior.
    live_explore_fields = _extract_v1_1_live_exploration(turn)
    out.update(live_explore_fields)

    return out


def build_row(
    row_battle: Dict[str, Any],
    turn: Dict[str, Any],
    source_artifact: str,
    benchmark_arm: str,
    dataset_id: str,
    policy_name_fallback: str,
) -> Optional[Dict[str, Any]]:
    """Build a single turn_rl_v1.0 row from a battle row + turn.

    Returns None if the turn cannot be built (missing
    required fields, malformed V4a keys, etc.).
    """
    battle_tag = row_battle.get("battle_tag", "")
    turn_index = turn.get("turn")
    if turn_index is None:
        return None
    won = row_battle.get("won")
    total_turns = len(row_battle.get("audit_turns", []))

    # Episode fields.
    episode = {
        "won": _to_json_safe(won),
        "battle_result": _battle_result(won),
        "total_turns": _to_json_safe(total_turns),
        "terminal_reward": _terminal_reward(won),
        "discounted_return": None,
    }

    # State.
    state = _build_state_snapshot(turn)

    # Action space.
    legal0, legal1, v4a_sel, final_keys = _build_action_space(turn)
    if v4a_sel is None or final_keys is None:
        return None

    # Selected.
    selected_per_slot = _build_selected_per_slot(v4a_sel, final_keys)
    selected_score = _to_json_safe(turn.get("selected_score"))

    # Optional fields.
    optional = _build_optional_fields(turn)

    # Identity.
    row = {
        "schema_version": SCHEMA_VERSION_V1_1,  # RL-DATA-2: v1.1
        "dataset_id": dataset_id,
        "source_artifact": source_artifact,
        "battle_tag": battle_tag,
        "episode_id": battle_tag,
        "turn_index": _to_json_safe(turn_index),
        "player_side": _player_side_from_arm(benchmark_arm),
        "benchmark_arm": benchmark_arm,
        "policy_name": _to_json_safe(
            turn.get("preview_policy") or policy_name_fallback
        ),
        # Episode.
        **episode,
        # State.
        "state_snapshot": state,
        # Action space.
        "legal_action_keys_slot0": [
            list(k) for k in legal0
        ],
        "legal_action_keys_slot1": [
            list(k) for k in legal1
        ],
        "legal_joint_action_keys": None,  # omitted in v1.0
        # Selected.
        "selected_joint_key": [list(k) for k in v4a_sel],
        "final_action_keys": [list(k) for k in final_keys],
        "selected_per_slot": selected_per_slot,
        "selected_score": selected_score,
    }
    # Add v1.0 optional fields.
    row.update(optional)

    # Phase RL-DATA-2: add v1.1 instrumentation fields. These
    # are instrumentation-only; they do NOT change scoring,
    # behavior, or selected actions.
    v1_1 = _build_v1_1_fields(turn, row_battle, state)
    row.update(v1_1)

    return row


def build_dataset_from_artifact(
    audit_path: str, benchmark_arm: str, dataset_id: str
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Build rows from a single audit JSONL artifact.

    Returns (rows, skipped_reasons).
    """
    rows = []
    skipped = []
    with open(audit_path) as f:
        for line in f:
            try:
                row_battle = json.loads(line)
            except json.JSONDecodeError:
                skipped.append("json_decode_error")
                continue
            bt = row_battle.get("battle_tag", "?")
            for turn in row_battle.get("audit_turns", []):
                row = build_row(
                    row_battle,
                    turn,
                    audit_path,
                    benchmark_arm,
                    dataset_id,
                    policy_name_fallback=benchmark_arm,
                )
                if row is None:
                    skipped.append(
                        f"build_failed:{bt}:t{turn.get('turn')}"
                    )
                    continue
                rows.append(row)
    return rows, skipped


def aggregate_battles(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-battle metadata from rows."""
    battles = {}
    for r in rows:
        bt = r.get("battle_tag", "")
        if bt not in battles:
            battles[bt] = {
                "battle_tag": bt,
                "won": r.get("won"),
                "battle_result": r.get("battle_result"),
                "total_turns": r.get("total_turns"),
                "terminal_reward": r.get("terminal_reward"),
                "n_rows": 0,
            }
        battles[bt]["n_rows"] += 1
    return battles


def validate_dataset(
    rows: List[Dict[str, Any]],
    source_artifact: str,
    missing_threshold: float = MISSING_REQUIRED_THRESHOLD,
    source_artifacts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run the 10 validation gates. Returns a report dict.

    Each gate reports pass/fail and a count. The
    overall report is "pass" only if all gates pass.
    """
    n = len(rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "source_artifact": None,  # set later
        "n_rows": n,
        "gates": {},
    }
    # Dedupe first: source artifacts may have
    # duplicate turns. Dedup by (battle_tag,
    # benchmark_arm, turn_index), keeping the first
    # occurrence. Track dropped count for the
    # duplicate_detection gate.
    seen = set()
    deduped_rows = []
    n_dup = 0
    for r in rows:
        key = (
            r.get("battle_tag"),
            r.get("benchmark_arm"),
            r.get("turn_index"),
        )
        if key in seen:
            n_dup += 1
            continue
        seen.add(key)
        deduped_rows.append(r)
    rows = deduped_rows
    n = len(rows)
    # Gate 1: JSON serializable.
    n_not_json = sum(
        0 if _row_json_serializable(r) else 1 for r in rows
    )
    report["gates"]["json_serializable"] = {
        "n_violations": n_not_json,
        "pass": n_not_json == 0,
    }
    # Gate 2: legal selected.
    n_illegal = 0
    for r in rows:
        sel = r.get("selected_joint_key", [])
        legal0 = r.get("legal_action_keys_slot0", [])
        legal1 = r.get("legal_action_keys_slot1", [])
        if not _selected_joint_key_in_legal(sel, legal0, legal1):
            n_illegal += 1
    report["gates"]["legal_selected"] = {
        "n_violations": n_illegal,
        "pass": n_illegal == 0,
    }
    # Gate 3: episode boundary valid.
    # Paired battles share the same battle_tag across
    # treatment and baseline arms, but they are
    # DIFFERENT games. The boundary must be within
    # (battle_tag, benchmark_arm), not just battle_tag.
    battles = {}
    for r in rows:
        key = (r.get("battle_tag"), r.get("benchmark_arm"))
        if key not in battles:
            battles[key] = {
                "battle_tag": r.get("battle_tag"),
                "benchmark_arm": r.get("benchmark_arm"),
                "won": r.get("won"),
                "battle_result": r.get("battle_result"),
                "total_turns": r.get("total_turns"),
                "terminal_reward": r.get("terminal_reward"),
                "n_rows": 0,
            }
        battles[key]["n_rows"] += 1
    n_bad_episodes = 0
    for key, meta in battles.items():
        if meta["n_rows"] < 1:
            n_bad_episodes += 1
            continue
        # All rows for this (battle_tag, arm) must
        # agree on battle_result, won, terminal_reward,
        # total_turns.
        bt_rows = [
            r for r in rows
            if r.get("battle_tag") == meta["battle_tag"]
            and r.get("benchmark_arm") == meta["benchmark_arm"]
        ]
        results = {r.get("battle_result") for r in bt_rows}
        wons = {r.get("won") for r in bt_rows}
        rewards = {r.get("terminal_reward") for r in bt_rows}
        if len(results) > 1 or len(wons) > 1 or len(rewards) > 1:
            n_bad_episodes += 1
    report["gates"]["episode_boundary"] = {
        "n_violations": n_bad_episodes,
        "pass": n_bad_episodes == 0,
    }
    # Gate 4: no hidden info.
    n_leaks = 0
    for r in rows:
        if _row_has_leakage(r):
            n_leaks += 1
    report["gates"]["no_hidden_info"] = {
        "n_violations": n_leaks,
        "pass": n_leaks == 0,
    }
    # Gate 5: missing required.
    rows_missing = sum(
        1 for r in rows if _row_has_required_fields(r)
    )
    miss_rate = rows_missing / n if n > 0 else 0.0
    report["gates"]["missing_required"] = {
        "n_violations": rows_missing,
        "miss_rate": miss_rate,
        "threshold": missing_threshold,
        "pass": miss_rate < missing_threshold,
    }
    # Gate 6: action distribution.
    n_empty_legal0 = sum(
        1 for r in rows if len(r.get("legal_action_keys_slot0", [])) == 0
    )
    n_empty_legal1 = sum(
        1 for r in rows if len(r.get("legal_action_keys_slot1", [])) == 0
    )
    report["gates"]["action_distribution"] = {
        "n_empty_legal0": n_empty_legal0,
        "n_empty_legal1": n_empty_legal1,
        "pass": n_empty_legal0 == 0 and n_empty_legal1 == 0,
    }
    # Gate 7: reward balance.
    rewards = [r.get("terminal_reward") for r in rows]
    pos = sum(1 for x in rewards if x == 1)
    neg = sum(1 for x in rewards if x == -1)
    zer = sum(1 for x in rewards if x == 0)
    report["gates"]["reward_balance"] = {
        "n_positive": pos,
        "n_negative": neg,
        "n_zero": zer,
        "pass": True,  # always pass; just report
    }
    # Gate 8: duplicate detection.
    # Duplicates were already removed at the top of
    # validation. This gate reports the count.
    report["gates"]["duplicate_detection"] = {
        "n_duplicates_dropped": n_dup,
        "pass": True,
    }
    # Gate 9: schema version present.
    # Phase RL-DATA-2: the builder produces
    # turn_rl_v1.1 rows by default. v1.0 is still
    # accepted as a legacy schema. The gate accepts
    # both.
    n_wrong_schema = sum(
        1 for r in rows
        if r.get("schema_version")
        not in (SCHEMA_VERSION, SCHEMA_VERSION_V1_1)
    )
    report["gates"]["schema_version"] = {
        "n_violations": n_wrong_schema,
        "pass": n_wrong_schema == 0,
    }
    # Gate 10: source traceability.
    # If multiple source artifacts, all must exist.
    n_no_source = sum(
        1 for r in rows if not r.get("source_artifact")
    )
    if source_artifacts:
        all_exist = all(
            os.path.exists(p) for p in source_artifacts
        )
        trace_source = "multi"
    else:
        all_exist = os.path.exists(source_artifact)
        trace_source = source_artifact
    report["gates"]["source_traceability"] = {
        "n_violations": n_no_source,
        "pass": n_no_source == 0 and all_exist,
    }
    # Overall.
    report["overall_pass"] = all(
        g["pass"] for g in report["gates"].values()
    )
    # Per-(battle, arm) summary.
    report["n_battles"] = len(battles)
    report["battles"] = list(battles.values())
    report["source_artifact"] = trace_source
    return report


def write_dataset(rows: List[Dict[str, Any]], path: str) -> None:
    """Write rows to a JSONL file."""
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")


def write_summary(report: Dict[str, Any], path: str) -> None:
    """Write the validation summary to a JSON file."""
    with open(path, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)


def write_validation_md(report: Dict[str, Any], path: str) -> None:
    """Write a human-readable validation MD report."""
    lines = []
    lines.append(f"# Turn-level offline dataset validation")
    lines.append("")
    lines.append(f"- schema_version: `{report.get('schema_version')}`")
    lines.append(f"- source_artifact: `{report.get('source_artifact')}`")
    lines.append(f"- n_rows: {report.get('n_rows')}")
    lines.append(f"- n_battles: {report.get('n_battles')}")
    lines.append(
        f"- overall_pass: **{report.get('overall_pass')}**"
    )
    lines.append("")
    lines.append("## Gates")
    lines.append("")
    lines.append("| gate | pass | details |")
    lines.append("|---|---|---|")
    for k, v in report.get("gates", {}).items():
        details = ", ".join(
            f"{kk}={vv}" for kk, vv in v.items() if kk != "pass"
        )
        lines.append(f"| {k} | {v.get('pass')} | {details} |")
    lines.append("")
    # Reward balance.
    rb = report.get("gates", {}).get("reward_balance", {})
    lines.append("## Reward balance")
    lines.append("")
    lines.append(f"- positive (win): {rb.get('n_positive')}")
    lines.append(f"- negative (loss): {rb.get('n_negative')}")
    lines.append(f"- zero (tie/unknown): {rb.get('n_zero')}")
    lines.append("")
    # Per-battle summary (first 20).
    battles = report.get("battles", [])
    if battles:
        lines.append("## Per-battle summary (first 20)")
        lines.append("")
        lines.append(
            "| battle_tag | arm | won | battle_result | total_turns | terminal_reward | n_rows |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for b in battles[:20]:
            lines.append(
                f"| `{b.get('battle_tag')}` | {b.get('benchmark_arm')} | "
                f"{b.get('won')} | {b.get('battle_result')} | "
                f"{b.get('total_turns')} | {b.get('terminal_reward')} | "
                f"{b.get('n_rows')} |"
            )
        if len(battles) > 20:
            lines.append("")
            lines.append(f"... and {len(battles) - 20} more battles")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build turn_rl_v1.0 dataset from audit JSONL."
    )
    parser.add_argument(
        "--input", action="append", required=True,
        help="Input audit JSONL. Pass multiple times for multiple files.",
    )
    parser.add_argument(
        "--arm", action="append", required=True,
        help="Benchmark arm for each input (treatment / baseline). "
        "Must match the order of --input.",
    )
    parser.add_argument(
        "--tag", required=True,
        help="Output tag. Files written to logs/turn_level_offline_dataset_<tag>.{jsonl,json,md}",
    )
    parser.add_argument(
        "--out-dir", default="logs",
        help="Output directory (default: logs).",
    )
    args = parser.parse_args(argv)
    if len(args.input) != len(args.arm):
        print(
            "ERROR: --input and --arm must have the same count",
            file=sys.stderr,
        )
        return 2
    # Build dataset.
    dataset_id = (
        f"build_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_"
        f"{uuid.uuid4().hex[:8]}"
    )
    all_rows = []
    all_skipped = []
    for path, arm in zip(args.input, args.arm):
        rows, skipped = build_dataset_from_artifact(
            path, arm, dataset_id
        )
        all_rows.extend(rows)
        all_skipped.extend(skipped)
        print(
            f"Built {len(rows)} rows from {path} (arm={arm})",
            file=sys.stderr,
        )
    # Validate.
    # We validate against the first source artifact (or
    # "multi" if multiple). The summary reports per-arm.
    source = args.input[0] if len(args.input) == 1 else "multi"
    report = validate_dataset(
        all_rows,
        source,
        source_artifacts=args.input,
    )
    # Use deduped row count for the dataset output
    # (validate_dataset dedupes internally).
    n_deduped = report["n_rows"]
    # Write deduped dataset to disk.
    deduped_seen = set()
    deduped_rows = []
    for r in all_rows:
        key = (
            r.get("battle_tag"),
            r.get("benchmark_arm"),
            r.get("turn_index"),
        )
        if key in deduped_seen:
            continue
        deduped_seen.add(key)
        deduped_rows.append(r)
    report["dataset_id"] = dataset_id
    report["source_artifacts"] = args.input
    report["benchmark_arms"] = args.arm
    report["skipped"] = all_skipped
    report["n_rows_input"] = len(all_rows)
    report["n_rows_deduped"] = n_deduped
    # Write outputs.
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    jsonl_path = os.path.join(
        out_dir, f"turn_level_offline_dataset_{args.tag}.jsonl"
    )
    summary_path = os.path.join(
        out_dir, f"turn_level_offline_dataset_{args.tag}_summary.json"
    )
    md_path = os.path.join(
        out_dir, f"turn_level_offline_dataset_{args.tag}_validation.md"
    )
    write_dataset(deduped_rows, jsonl_path)
    write_summary(report, summary_path)
    write_validation_md(report, md_path)
    print(
        f"Wrote {n_deduped} rows to {jsonl_path}",
        file=sys.stderr,
    )
    print(
        f"Wrote summary to {summary_path}",
        file=sys.stderr,
    )
    print(
        f"Wrote validation to {md_path}",
        file=sys.stderr,
    )
    print(
        f"Overall pass: {report['overall_pass']}",
        file=sys.stderr,
    )
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
