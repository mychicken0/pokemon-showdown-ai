"""Action-trace instrumentation for Phase 7 production-path diagnosis.

Disabled by default. When enabled via
``PHASE7_ACTION_TRACE_DIR`` env var, writes per-candidate
and per-joint trace records to the given directory.

The trace is designed to prove whether the Protect hard-block
reaches final selected orders in real production, without
changing the production scoring path.
"""

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

_HARD_BLOCK_SCORE_THRESHOLD_FALLBACK = -1e8


def _hard_block_score_threshold() -> float:
    try:
        from .bot_doubles_damage_aware import HARD_BLOCK_SCORE_THRESHOLD
        return HARD_BLOCK_SCORE_THRESHOLD
    except Exception:
        return _HARD_BLOCK_SCORE_THRESHOLD_FALLBACK

_DEFAULT_ENABLED = False
_trace_dir: Optional[str] = None
_trace_dir_explicit: bool = False
_records: List[Dict[str, Any]] = []
_flush_counter: int = 0
_lock = threading.Lock()
_candidate_count = 0
_protect_candidate_count = 0
_protect_hard_block_candidate_count = 0
_hard_blocked_joint_count = 0
_selected_hard_blocked_action_count = 0
_protect_state_update_count = 0
_protect_state_reset_count = 0
_missing_score_trace_count = 0
_emergency_fallback_count = 0


def _get_trace_dir() -> Optional[str]:
    if _trace_dir_explicit:
        return _trace_dir
    env_dir = os.environ.get("PHASE7_ACTION_TRACE_DIR")
    if env_dir:
        return env_dir
    return None


def is_action_trace_enabled() -> bool:
    """Return True if action trace is enabled via env var or
    set_trace_dir."""
    return _get_trace_dir() is not None


def set_trace_dir(trace_dir: Optional[str]) -> None:
    """Enable action trace by setting the trace directory.

    Set to a non-empty string to enable and override any
    env var. Set to ``""`` to force-disable even when the
    env var is set (used in tests). Default behavior
    (never called) honors the ``PHASE7_ACTION_TRACE_DIR``
    env var.
    """
    global _trace_dir, _trace_dir_explicit
    _trace_dir = trace_dir
    _trace_dir_explicit = True


def unset_trace_dir_explicit() -> None:
    """Clear the explicit ``set_trace_dir`` override so the
    ``PHASE7_ACTION_TRACE_DIR`` env var is consulted again.
    """
    global _trace_dir, _trace_dir_explicit
    _trace_dir = None
    _trace_dir_explicit = False


def reset_action_trace_counters() -> None:
    global _candidate_count, _protect_candidate_count
    global _protect_hard_block_candidate_count
    global _hard_blocked_joint_count
    global _selected_hard_blocked_action_count
    global _protect_state_update_count
    global _protect_state_reset_count
    global _missing_score_trace_count
    global _emergency_fallback_count
    global _records
    global _flush_counter
    _candidate_count = 0
    _protect_candidate_count = 0
    _protect_hard_block_candidate_count = 0
    _hard_blocked_joint_count = 0
    _selected_hard_blocked_action_count = 0
    _protect_state_update_count = 0
    _protect_state_reset_count = 0
    _missing_score_trace_count = 0
    _emergency_fallback_count = 0
    _records = []
    _flush_counter = 0


def _is_protect_like(mid: str) -> bool:
    if not mid:
        return False
    p = mid.lower().replace(" ", "").replace("-", "")
    return p in (
        "protect", "detect", "spikyshield", "kingsshield",
        "obstruct", "maxguard", "silktrap", "quickguard",
        "wideguard", "banefulbunker", "burningbulwark",
    )


def _pokemon_ident(battle, active_idx: int) -> str:
    try:
        ap = getattr(battle, "active_pokemon", None)
        if ap and active_idx < len(ap) and ap[active_idx]:
            m = ap[active_idx]
            return (
                getattr(m, "ident", None)
                or getattr(m, "name", None)
                or getattr(m, "species", None)
                or ""
            )
    except Exception:
        pass
    return ""


def _pokemon_types(battle, active_idx: int) -> str:
    try:
        ap = getattr(battle, "active_pokemon", None)
        if ap and active_idx < len(ap) and ap[active_idx]:
            m = ap[active_idx]
            t = getattr(m, "types", None)
            if t:
                return ",".join(t)
    except Exception:
        pass
    return ""


def _battle_id(battle) -> str:
    return getattr(battle, "battle_tag", "?")


def _turn(battle) -> int:
    return getattr(battle, "turn", 0)


def record_candidate(
    battle,
    active_idx: int,
    order,
    score: float,
    hard_block_reason: str = "",
    committed_protect_streak=None,
    protect_last_failed=None,
) -> None:
    """Record a candidate scoring event.

    Called by the scorer. Does NOT mutate the order or
    score. Safe to leave enabled in production because it
    only reads attributes and increments counters.
    """
    if not is_action_trace_enabled():
        return
    inner = getattr(order, "order", None)
    mid = (
        str(getattr(inner, "id", ""))
        if inner is not None
        else ""
    )
    is_protect = _is_protect_like(mid)
    target = getattr(order, "move_target", 0)
    threshold = _hard_block_score_threshold()
    record = {
        "kind": "candidate",
        "battle_tag": _battle_id(battle),
        "turn": _turn(battle),
        "side": "p1" if active_idx in (0, 1) else "?",
        "active_idx": active_idx,
        "pokemon_ident": _pokemon_ident(battle, active_idx),
        "pokemon_types": _pokemon_types(battle, active_idx),
        "candidate_move_id": mid,
        "protect_like_class": "protect_like" if is_protect else "",
        "candidate_target": target,
        "is_protect_candidate": is_protect,
        "committed_protect_streak": committed_protect_streak,
        "protect_last_failed": protect_last_failed,
        "raw_score_before_policy": score,
        "score_after_score_action_impl": score,
        "is_hard_blocked": score <= threshold,
        "hard_block_reason": hard_block_reason,
    }
    with _lock:
        _records.append(record)
        global _candidate_count
        global _protect_candidate_count
        global _protect_hard_block_candidate_count
        _candidate_count += 1
        threshold = _hard_block_score_threshold()
        if is_protect:
            _protect_candidate_count += 1
            if score <= threshold:
                _protect_hard_block_candidate_count += 1


def record_state_update(
    battle,
    active_idx: int,
    is_reset: bool = False,
    selected_move_id: str = "",
    committed_streak_before=None,
    committed_streak_after=None,
    source: str = "",
) -> None:
    """Record a Protect streak state update or reset."""
    if not is_action_trace_enabled():
        return
    with _lock:
        global _protect_state_update_count, _protect_state_reset_count
        if is_reset:
            _protect_state_reset_count += 1
        else:
            _protect_state_update_count += 1
        _records.append({
            "kind": "protect_state_commit",
            "battle_tag": _battle_id(battle),
            "turn": _turn(battle),
            "active_idx": active_idx,
            "pokemon_ident": _pokemon_ident(battle, active_idx),
            "selected_move_id": selected_move_id,
            "committed_streak_before": committed_streak_before,
            "committed_streak_after": committed_streak_after,
            "is_reset": is_reset,
            "source": source,
        })


def record_joint(
    battle,
    joint_id: int,
    first_order,
    second_order,
    score_1: float,
    score_2: float,
    joint_score: float,
    joint_score_before_penalty: float,
    joint_score_after_penalty: float,
    joint_has_hard_block: bool,
    joint_selected: bool,
    selection_rank: int,
    call_depth: int = 0,
    counterfactual: str = "",
) -> None:
    if not is_action_trace_enabled():
        return
    record = {
        "kind": "joint",
        "battle_tag": _battle_id(battle),
        "turn": _turn(battle),
        "joint_id": joint_id,
        "slot0_move": _inner_id(first_order),
        "slot1_move": _inner_id(second_order),
        "slot0_score": score_1,
        "slot1_score": score_2,
        "joint_score_before_penalty": joint_score_before_penalty,
        "joint_score_after_penalty": joint_score_after_penalty,
        "joint_has_hard_block": joint_has_hard_block,
        "joint_selected": joint_selected,
        "selection_rank": selection_rank,
        "call_depth": call_depth,
        "counterfactual": counterfactual,
    }
    with _lock:
        _records.append(record)
        global _hard_blocked_joint_count
        if joint_has_hard_block:
            _hard_blocked_joint_count += 1


def _inner_id(order):
    inner = getattr(order, "order", None)
    if inner is None:
        return ""
    return str(getattr(inner, "id", ""))


def record_final_orders(
    battle,
    first_order,
    second_order,
    first_was_hard_blocked: bool,
    second_was_hard_blocked: bool,
    emergency_fallback_used: bool,
    fallback_reason: str = "",
) -> None:
    if not is_action_trace_enabled():
        return
    record = {
        "kind": "final_orders",
        "battle_tag": _battle_id(battle),
        "turn": _turn(battle),
        "final_slot0_move": _inner_id(first_order),
        "final_slot1_move": _inner_id(second_order),
        "final_slot0_was_hard_blocked": first_was_hard_blocked,
        "final_slot1_was_hard_blocked": second_was_hard_blocked,
        "emergency_fallback_used": emergency_fallback_used,
        "fallback_reason": fallback_reason,
    }
    with _lock:
        _records.append(record)
        global _selected_hard_blocked_action_count
        global _emergency_fallback_count
        if first_was_hard_blocked or second_was_hard_blocked:
            _selected_hard_blocked_action_count += 1
        if emergency_fallback_used:
            _emergency_fallback_count += 1


def record_missing_score_trace(battle, label: str) -> None:
    if not is_action_trace_enabled():
        return
    with _lock:
        global _missing_score_trace_count
        _missing_score_trace_count += 1
        _records.append({
            "kind": "missing_score_trace",
            "battle_tag": _battle_id(battle),
            "turn": _turn(battle),
            "label": label,
        })


def get_summary() -> Dict[str, Any]:
    """Return a summary of all trace counters."""
    with _lock:
        return {
            "action_trace_enabled": is_action_trace_enabled(),
            "action_trace_event_count": len(_records),
            "protect_candidate_count": _protect_candidate_count,
            "protect_hard_block_candidate_count": _protect_hard_block_candidate_count,
            "hard_blocked_joint_count": _hard_blocked_joint_count,
            "selected_hard_blocked_action_count": _selected_hard_blocked_action_count,
            "protect_state_update_count": _protect_state_update_count,
            "protect_state_reset_count": _protect_state_reset_count,
            "missing_score_trace_count": _missing_score_trace_count,
            "candidate_count": _candidate_count,
            "emergency_fallback_count": _emergency_fallback_count,
        }


def get_records() -> List[Dict[str, Any]]:
    with _lock:
        return list(_records)


def flush_records() -> None:
    """Write all buffered records to the trace directory.

    Each call creates a timestamped JSONL file. Safe to
    call multiple times.
    """
    if not is_action_trace_enabled():
        return
    trace_dir = _get_trace_dir()
    if not trace_dir:
        return
    os.makedirs(trace_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    with _lock:
        global _flush_counter
        _flush_counter += 1
        seq = _flush_counter
    out_path = os.path.join(
        trace_dir, f"action_trace_{timestamp}_{seq:04d}.jsonl"
    )
    with _lock:
        records = list(_records)
    with open(out_path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    summary = get_summary()
    summary_path = os.path.join(
        trace_dir, f"action_trace_summary_{timestamp}_{seq:04d}.json"
    )
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
