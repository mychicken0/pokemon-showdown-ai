"""Phase PROTECT-1 — Protect usage evidence audit.

Read-only diagnostic over audit JSONL files. No
production code, no scoring change, no battle runs.
Answers the 7 data questions from the PROTECT-1
spec.

Inputs: one or more audit JSONL paths.
Output: logs/phasePROTECT1_protect_usage_evidence_audit.<md|json>

Ponytail: 1 file, stdlib only, deterministic, no
external dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple


# Phase BEHAVIOR-2 / TURN-2 / SWITCH-2: tiny stable
# allowlists. Mirrored from analyze_doubles_turn_level
# to keep this script independent.
PROTECT_LIKE = {
    "protect", "detect", "kingsshield", "spikyshield",
    "banefulbunker", "silktrap", "maxguard", "obstruct",
}


def _is_protect_key(key: Optional[Any]) -> bool:
    if not isinstance(key, list) or len(key) < 2:
        return False
    return str(key[1]).lower() in PROTECT_LIKE


def _is_move_key(key: Optional[Any]) -> bool:
    if not isinstance(key, list) or len(key) < 1:
        return False
    return key[0] == "move"


def _is_switch_key(key: Optional[Any]) -> bool:
    if not isinstance(key, list) or len(key) < 1:
        return False
    return key[0] == "switch"


def _hp_bucket(hp: Optional[float]) -> str:
    if hp is None:
        return "unknown"
    if hp < 0.25:
        return "<25%"
    if hp < 0.5:
        return "25-50%"
    if hp < 0.75:
        return "50-75%"
    if hp <= 1.01:
        return "75-100%"
    return "unknown"


def _load(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _per_slot_protect_legal(
    turn: Dict[str, Any], slot_idx: int
) -> bool:
    legal = turn.get(
        f"v4a_legal_action_keys_slot{slot_idx}", []
    ) or []
    return any(_is_protect_key(k) for k in legal)


def _per_slot_move_attack(
    turn: Dict[str, Any], slot_idx: int
) -> bool:
    sel = turn.get("v4a_selected_joint_key") or []
    if len(sel) <= slot_idx:
        return False
    k = sel[slot_idx]
    return _is_move_key(k) and not _is_protect_key(k)


def _per_slot_switch(
    turn: Dict[str, Any], slot_idx: int
) -> bool:
    sel = turn.get("v4a_selected_joint_key") or []
    if len(sel) <= slot_idx:
        return False
    return _is_switch_key(sel[slot_idx])


def _per_slot_protect_selected(
    turn: Dict[str, Any], slot_idx: int
) -> bool:
    sel = turn.get("v4a_selected_joint_key") or []
    if len(sel) <= slot_idx:
        return False
    return _is_protect_key(sel[slot_idx])


def _expected_faint_slot(
    turn: Dict[str, Any], slot_idx: int
) -> Optional[bool]:
    """Read expected_to_faint_before_moving for a slot.
    Returns None if the field is missing."""
    ef = turn.get("expected_to_faint_before_moving")
    if not isinstance(ef, list) or len(ef) <= slot_idx:
        return None
    v = ef[slot_idx]
    if v is None:
        return None
    return bool(v)


def _speed_priority_threat_slot(
    turn: Dict[str, Any], slot_idx: int
) -> Optional[bool]:
    sp = turn.get("speed_priority_threatened")
    if not isinstance(sp, list) or len(sp) <= slot_idx:
        return None
    v = sp[slot_idx]
    if v is None:
        return None
    return bool(v)


def _switch_cf_delta_slot(
    turn: Dict[str, Any], slot_idx: int
) -> Optional[float]:
    scf = turn.get("switch_counterfactual") or {}
    slot = scf.get(f"slot{slot_idx}")
    if not isinstance(slot, dict):
        return None
    d = slot.get("switch_vs_non_switch_delta")
    if d is None:
        return None
    return float(d)


def _score_diff_slot(
    turn: Dict[str, Any], slot_idx: int
) -> Optional[float]:
    """Read score gap from selected vs best alt.
    For PROTECT-1, we use the speed_priority_score_diff
    if available (Protect - best non-protect), else
    fall back to score_gap_selected_best_alt."""
    sp_diff = turn.get(
        f"speed_priority_score_diff_slot{slot_idx}"
    )
    if sp_diff is not None:
        return float(sp_diff)
    return None


def _protect_floor_debug_slot(
    turn: Dict[str, Any], slot_idx: int
) -> Dict[str, Any]:
    """Read speed_priority_protect_floor_debug for a
    slot.

    The BEHAVIOR-17/18 audit logger persists this as
    a per-slot dict under the
    `speed_priority_protect_floor_debug` key:

        speed_priority_protect_floor_debug:
          slot0:
            expected_faint: bool
            protect_like_keys: [..]
            protect_score_before_floor: float
            protect_score_after_floor: float
            floor_applied: bool
            floor_value: float
            action_count: int
            selected_action_key: str

    Returns {} if the field is missing or the slot
    is absent.
    """
    debug = turn.get("speed_priority_protect_floor_debug")
    if not isinstance(debug, dict):
        return {}
    slot = debug.get(f"slot{slot_idx}")
    if not isinstance(slot, dict):
        return {}
    return slot


def _protect_score_slot(
    turn: Dict[str, Any], slot_idx: int
) -> Optional[float]:
    """Read the protect score from the BEHAVIOR-17/18
    `speed_priority_protect_score_slot{slot_idx}`
    field. This is the score Protect received
    AFTER the floor was applied.
    """
    v = turn.get(
        f"speed_priority_protect_score_slot{slot_idx}"
    )
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _best_attack_score_slot(
    turn: Dict[str, Any], slot_idx: int
) -> Optional[float]:
    """Read the best non-protect attack score.
    """
    v = turn.get(
        f"speed_priority_best_attack_score_slot{slot_idx}"
    )
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def collect_audit(
    paths: List[str],
) -> Dict[str, Any]:
    """Walk all turns; compute Protect selection,
    availability, attack-through, and switch
    comparison stats.
    """
    out: Dict[str, Any] = {
        "input_paths": paths,
        "rows": 0,
        "turns": 0,
        "v4a_coverage": 0,
        "speed_priority_coverage": 0,
        "expected_faint_coverage": 0,
        "switch_cf_coverage": 0,
        # Selection counts
        "protect_selected_by_slot": {"slot0": 0, "slot1": 0},
        "protect_selected_total": 0,
        "move_attack_selected_by_slot": {
            "slot0": 0, "slot1": 0
        },
        "switch_selected_by_slot": {"slot0": 0, "slot1": 0},
        # Availability counts
        "protect_legal_by_slot": {"slot0": 0, "slot1": 0},
        "protect_legal_but_not_selected_by_slot": {
            "slot0": 0, "slot1": 0
        },
        # HP buckets for Protect selected
        "protect_selected_hp_bucket": {
            "<25%": 0, "25-50%": 0, "50-75%": 0,
            "75-100%": 0, "unknown": 0,
        },
        "move_attack_selected_hp_bucket": {
            "<25%": 0, "25-50%": 0, "50-75%": 0,
            "75-100%": 0, "unknown": 0,
        },
        # expected_faint + Protect available
        "exp_faint_true_protect_legal_attack_chosen": 0,
        "exp_faint_true_protect_legal_protect_chosen": 0,
        "exp_faint_true_protect_legal_switch_chosen": 0,
        "exp_faint_true_protect_not_legal_attack_chosen": 0,
        "exp_faint_false_protect_legal_attack_chosen": 0,
        "exp_faint_false_protect_legal_protect_chosen": 0,
        # expected_faint missing (predates BEHAVIOR-18)
        "exp_faint_missing": 0,
        # Speed-priority threat + Protect chosen
        "sp_threat_true_protect_chosen": 0,
        "sp_threat_false_protect_chosen": 0,
        # Switch counterfactual positive in expected_faint
        "exp_faint_true_scf_positive_protect_chosen": 0,
        "exp_faint_true_scf_positive_attack_chosen": 0,
        "exp_faint_true_scf_negative_attack_chosen": 0,
        # Wins/losses
        "won_protect_chosen": 0,
        "lost_protect_chosen": 0,
        "won_attack_through": 0,
        "lost_attack_through": 0,
        "won_attack_normal": 0,
        "lost_attack_normal": 0,
        # Top attack-through cases
        "top_attack_through": [],
        # Protect-floor debug (correct path: nested per-slot)
        "protect_floor_debug_field_present": 0,
        "protect_floor_present_per_slot": {
            "slot0": 0, "slot1": 0
        },
        "protect_floor_applied_per_slot": {
            "slot0": 0, "slot1": 0
        },
        "protect_floor_value_seen": [],
        # Floor applied + ef=True
        "floor_applied_ef_true_per_slot": {
            "slot0": 0, "slot1": 0
        },
        # Floor applied + Protect chosen
        "floor_applied_protect_chosen_per_slot": {
            "slot0": 0, "slot1": 0
        },
        # Floor applied + attack chosen (floor not enough)
        "floor_applied_attack_chosen_per_slot": {
            "slot0": 0, "slot1": 0
        },
        # protected_due_to_speed_priority per-turn
        "protected_due_to_sp_per_turn": 0,
        "speed_priority_protect_bonus_applied": 0,
        "speed_priority_attack_penalty_applied": 0,
        "speed_priority_switch_bonus_applied": 0,
        # Score diff (Protect - best attack)
        "score_diff_present_per_slot": {
            "slot0": 0, "slot1": 0
        },
        # HP field check
        "state_snapshot_present": 0,
    }
    rows: List[Dict[str, Any]] = []
    for path in paths:
        for r in _load(path):
            rows.append(r)
    out["rows"] = len(rows)
    for r in rows:
        battle_tag = r.get("battle_tag", "?")
        won = r.get("won")
        for t in r.get("audit_turns", []):
            if not isinstance(t, dict):
                continue
            out["turns"] += 1
            if (
                t.get("v4a_legal_action_keys_slot0")
                or t.get("v4a_legal_action_keys_slot1")
            ):
                out["v4a_coverage"] += 1
            if t.get("speed_priority_threatened") is not None:
                out["speed_priority_coverage"] += 1
            if t.get("expected_to_faint_before_moving") is not None:
                out["expected_faint_coverage"] += 1
            if t.get("switch_counterfactual"):
                out["switch_cf_coverage"] += 1
            if t.get("state_snapshot"):
                out["state_snapshot_present"] += 1
            # Phase PROTECT-2: per-turn BEHAVIOR-17/18
            # bonus/penalty flags. These are stored as
            # 2-element lists (per-slot), not as a
            # single boolean.
            psp = t.get("protected_due_to_speed_priority")
            if isinstance(psp, list):
                if any(x is True for x in psp):
                    out["protected_due_to_sp_per_turn"] += 1
            spba = t.get("speed_priority_protect_bonus_applied")
            if isinstance(spba, list):
                if any(x is True for x in spba):
                    out[
                        "speed_priority_protect_bonus_applied"
                    ] += 1
            spa = t.get("speed_priority_attack_penalty_applied")
            if isinstance(spa, list):
                if any(x is True for x in spa):
                    out[
                        "speed_priority_attack_penalty_applied"
                    ] += 1
            ssb = t.get("speed_priority_switch_bonus_applied")
            if isinstance(ssb, list):
                if any(x is True for x in ssb):
                    out[
                        "speed_priority_switch_bonus_applied"
                    ] += 1
            # Per-slot fields: floor debug + score diff.
            for slot_idx in (0, 1):
                slot_key = f"slot{slot_idx}"
                fdebug = _protect_floor_debug_slot(t, slot_idx)
                if fdebug:
                    out[
                        "protect_floor_present_per_slot"
                    ][slot_key] += 1
                    if fdebug.get("floor_applied"):
                        out[
                            "protect_floor_applied_per_slot"
                        ][slot_key] += 1
                    fv = fdebug.get("floor_value")
                    if fv is not None:
                        out["protect_floor_value_seen"].append(
                            float(fv)
                        )
                sd = _score_diff_slot(t, slot_idx)
                if sd is not None:
                    out[
                        "score_diff_present_per_slot"
                    ][slot_key] += 1
            debug_root = t.get(
                "speed_priority_protect_floor_debug"
            )
            if isinstance(debug_root, dict) and debug_root:
                out["protect_floor_debug_field_present"] += 1
            for slot_idx in (0, 1):
                slot_key = f"slot{slot_idx}"
                legal = _per_slot_protect_legal(t, slot_idx)
                sel_protect = _per_slot_protect_selected(
                    t, slot_idx
                )
                sel_attack = _per_slot_move_attack(
                    t, slot_idx
                )
                sel_switch = _per_slot_switch(t, slot_idx)
                ef = _expected_faint_slot(t, slot_idx)
                sp = _speed_priority_threat_slot(t, slot_idx)
                scf_d = _switch_cf_delta_slot(t, slot_idx)
                ss = t.get("state_snapshot") or {}
                our_hp_list = ss.get(
                    "our_active_hp_fraction", []
                ) or []
                our_hp = (
                    our_hp_list[slot_idx]
                    if len(our_hp_list) > slot_idx
                    else None
                )
                bucket = _hp_bucket(our_hp)
                if legal:
                    out["protect_legal_by_slot"][slot_key] += 1
                    if not sel_protect:
                        out[
                            "protect_legal_but_not_selected_by_slot"
                        ][slot_key] += 1
                if sel_protect:
                    out["protect_selected_by_slot"][
                        slot_key
                    ] += 1
                    out["protect_selected_total"] += 1
                    out["protect_selected_hp_bucket"][bucket] += 1
                    if sp is True:
                        out["sp_threat_true_protect_chosen"] += 1
                    elif sp is False:
                        out["sp_threat_false_protect_chosen"] += 1
                    if won is True:
                        out["won_protect_chosen"] += 1
                    elif won is False:
                        out["lost_protect_chosen"] += 1
                if sel_attack:
                    out["move_attack_selected_by_slot"][
                        slot_key
                    ] += 1
                    out["move_attack_selected_hp_bucket"][
                        bucket
                    ] += 1
                    if won is True:
                        out["won_attack_normal"] += 1
                    elif won is False:
                        out["lost_attack_normal"] += 1
                if sel_switch:
                    out["switch_selected_by_slot"][slot_key] += 1
                # attack-through: ef True + Protect legal +
                # attack selected.
                if (
                    ef is True
                    and legal
                    and sel_attack
                ):
                    out[
                        "exp_faint_true_protect_legal_attack_chosen"
                    ] += 1
                    if won is True:
                        out["won_attack_through"] += 1
                    elif won is False:
                        out["lost_attack_through"] += 1
                    # Track top attack-through
                    sd = _score_diff_slot(t, slot_idx)
                    out["top_attack_through"].append({
                        "battle_tag": battle_tag,
                        "won": won,
                        "turn": t.get("turn"),
                        "slot": slot_key,
                        "our_hp": our_hp,
                        "speed_priority_threat": sp,
                        "switch_cf_delta": scf_d,
                        "score_diff": sd,
                    })
                if (
                    ef is True
                    and legal
                    and sel_protect
                ):
                    out[
                        "exp_faint_true_protect_legal_protect_chosen"
                    ] += 1
                if (
                    ef is True
                    and legal
                    and sel_switch
                ):
                    out[
                        "exp_faint_true_protect_legal_switch_chosen"
                    ] += 1
                if (
                    ef is True
                    and not legal
                    and sel_attack
                ):
                    out[
                        "exp_faint_true_protect_not_legal_attack_chosen"
                    ] += 1
                if (
                    ef is False
                    and legal
                    and sel_attack
                ):
                    out[
                        "exp_faint_false_protect_legal_attack_chosen"
                    ] += 1
                if (
                    ef is False
                    and legal
                    and sel_protect
                ):
                    out[
                        "exp_faint_false_protect_legal_protect_chosen"
                    ] += 1
                if (
                    ef is None
                ):
                    out["exp_faint_missing"] += 1
                # Switch comparison
                if (
                    ef is True
                    and scf_d is not None
                    and scf_d > 0
                    and sel_attack
                ):
                    out[
                        "exp_faint_true_scf_positive_attack_chosen"
                    ] += 1
                if (
                    ef is True
                    and scf_d is not None
                    and scf_d < 0
                    and sel_attack
                ):
                    out[
                        "exp_faint_true_scf_negative_attack_chosen"
                    ] += 1
                if (
                    ef is True
                    and scf_d is not None
                    and scf_d > 0
                    and sel_protect
                ):
                    out[
                        "exp_faint_true_scf_positive_protect_chosen"
                    ] += 1
                # Phase PROTECT-2: per-slot floor effect.
                fdebug = _protect_floor_debug_slot(
                    t, slot_idx
                )
                if fdebug and fdebug.get("floor_applied"):
                    if ef is True:
                        out[
                            "floor_applied_ef_true_per_slot"
                        ][slot_key] += 1
                    if sel_protect:
                        out[
                            "floor_applied_protect_chosen_per_slot"
                        ][slot_key] += 1
                    if sel_attack:
                        out[
                            "floor_applied_attack_chosen_per_slot"
                        ][slot_key] += 1
    # Trim top attack-through to top 10 by score_diff
    # (lowest = bot picked the smaller gap, i.e. closer
    # to Protect being right).
    out["top_attack_through"] = sorted(
        out["top_attack_through"],
        key=lambda x: (
            x.get("score_diff") is None,
            x.get("score_diff") or 0
        ),
    )[:10]
    return out


def _write_markdown(data: Dict[str, Any], path: str) -> None:
    lines: List[str] = []
    lines.append("# Phase PROTECT-1 — Protect Usage Evidence Audit")
    lines.append("")
    lines.append("## 1. Coverage")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---:|")
    lines.append(f"| rows | {data['rows']} |")
    lines.append(f"| turns | {data['turns']} |")
    lines.append(f"| v4a coverage | {data['v4a_coverage']} |")
    lines.append(
        f"| speed_priority_coverage | "
        f"{data['speed_priority_coverage']} |"
    )
    lines.append(
        f"| expected_faint_coverage | "
        f"{data['expected_faint_coverage']} |"
    )
    lines.append(
        f"| switch_cf_coverage | {data['switch_cf_coverage']} |"
    )
    lines.append(
        f"| state_snapshot_present | "
        f"{data['state_snapshot_present']} |"
    )
    lines.append(
        f"| protect_floor_debug_field_present | "
        f"{data['protect_floor_debug_field_present']} |"
    )
    for s in ("slot0", "slot1"):
        lines.append(
            f"| protect_floor_present_{s} | "
            f"{data['protect_floor_present_per_slot'][s]} |"
        )
        lines.append(
            f"| protect_floor_applied_{s} | "
            f"{data['protect_floor_applied_per_slot'][s]} |"
        )
        lines.append(
            f"| floor_applied_ef_true_{s} | "
            f"{data['floor_applied_ef_true_per_slot'][s]} |"
        )
        lines.append(
            f"| floor_applied_protect_chosen_{s} | "
            f"{data['floor_applied_protect_chosen_per_slot'][s]} |"
        )
        lines.append(
            f"| floor_applied_attack_chosen_{s} | "
            f"{data['floor_applied_attack_chosen_per_slot'][s]} |"
        )
    lines.append(
        f"| protected_due_to_speed_priority | "
        f"{data['protected_due_to_sp_per_turn']} |"
    )
    lines.append(
        f"| speed_priority_protect_bonus_applied | "
        f"{data['speed_priority_protect_bonus_applied']} |"
    )
    lines.append(
        f"| speed_priority_attack_penalty_applied | "
        f"{data['speed_priority_attack_penalty_applied']} |"
    )
    lines.append(
        f"| speed_priority_switch_bonus_applied | "
        f"{data['speed_priority_switch_bonus_applied']} |"
    )
    fv_list = data.get("protect_floor_value_seen", [])
    if fv_list:
        uniq = sorted(set(fv_list))
        lines.append(
            f"| protect_floor_value_seen (unique) | "
            f"{uniq} |"
        )
    lines.append("")
    lines.append("## 2. Protect Selection")
    lines.append("")
    lines.append("| metric | slot0 | slot1 | total |")
    lines.append("|---|---:|---:|---:|")
    p0 = data["protect_selected_by_slot"]["slot0"]
    p1 = data["protect_selected_by_slot"]["slot1"]
    a0 = data["move_attack_selected_by_slot"]["slot0"]
    a1 = data["move_attack_selected_by_slot"]["slot1"]
    s0 = data["switch_selected_by_slot"]["slot0"]
    s1 = data["switch_selected_by_slot"]["slot1"]
    lines.append(
        f"| Protect selected | {p0} | {p1} | {p0 + p1} |"
    )
    lines.append(
        f"| Move-attack selected | {a0} | {a1} | {a0 + a1} |"
    )
    lines.append(
        f"| Switch selected | {s0} | {s1} | {s0 + s1} |"
    )
    l0 = data["protect_legal_by_slot"]["slot0"]
    l1 = data["protect_legal_by_slot"]["slot1"]
    lines.append(
        f"| Protect legal | {l0} | {l1} | {l0 + l1} |"
    )
    lines.append(
        f"| Protect legal but NOT selected | "
        f"{data['protect_legal_but_not_selected_by_slot']['slot0']} | "
        f"{data['protect_legal_but_not_selected_by_slot']['slot1']} | "
        f"{data['protect_legal_but_not_selected_by_slot']['slot0'] + data['protect_legal_but_not_selected_by_slot']['slot1']} |"
    )
    lines.append("")
    if data["turns"] > 0:
        lines.append(
            f"Protect selected turn ratio: "
            f"{data['protect_selected_total'] / data['turns']:.3f} "
            f"({data['protect_selected_total']} of {data['turns']})"
        )
    lines.append("")
    lines.append("## 3. Protect by HP bucket")
    lines.append("")
    lines.append("| bucket | Protect selected | attack selected |")
    lines.append("|---|---:|---:|")
    for b in (
        "<25%", "25-50%", "50-75%", "75-100%", "unknown"
    ):
        lines.append(
            f"| {b} | "
            f"{data['protect_selected_hp_bucket'][b]} | "
            f"{data['move_attack_selected_hp_bucket'][b]} |"
        )
    lines.append("")
    lines.append("## 4. expected_faint + Protect availability")
    lines.append("")
    lines.append("| case | count |")
    lines.append("|---|---:|")
    lines.append(
        f"| ef=True + Protect legal + attack chosen (attack-through) | "
        f"{data['exp_faint_true_protect_legal_attack_chosen']} |"
    )
    lines.append(
        f"| ef=True + Protect legal + Protect chosen | "
        f"{data['exp_faint_true_protect_legal_protect_chosen']} |"
    )
    lines.append(
        f"| ef=True + Protect legal + switch chosen | "
        f"{data['exp_faint_true_protect_legal_switch_chosen']} |"
    )
    lines.append(
        f"| ef=True + Protect NOT legal + attack chosen | "
        f"{data['exp_faint_true_protect_not_legal_attack_chosen']} |"
    )
    lines.append(
        f"| ef=False + Protect legal + attack chosen | "
        f"{data['exp_faint_false_protect_legal_attack_chosen']} |"
    )
    lines.append(
        f"| ef=False + Protect legal + Protect chosen | "
        f"{data['exp_faint_false_protect_legal_protect_chosen']} |"
    )
    lines.append(
        f"| ef missing (predates BEHAVIOR-18) | "
        f"{data['exp_faint_missing']} |"
    )
    lines.append("")
    lines.append("## 5. Switch-vs-Protect comparison")
    lines.append("")
    lines.append("| case | count |")
    lines.append("|---|---:|")
    lines.append(
        f"| ef=True + scf_delta>0 + attack chosen "
        f"(bot attacked when switch looked better) | "
        f"{data['exp_faint_true_scf_positive_attack_chosen']} |"
    )
    lines.append(
        f"| ef=True + scf_delta<0 + attack chosen "
        f"(switch would have been worse, attack is fine) | "
        f"{data['exp_faint_true_scf_negative_attack_chosen']} |"
    )
    lines.append(
        f"| ef=True + scf_delta>0 + Protect chosen "
        f"(Protect over switch) | "
        f"{data['exp_faint_true_scf_positive_protect_chosen']} |"
    )
    lines.append("")
    lines.append("## 6. Outcome sanity")
    lines.append("")
    lines.append("| case | won | lost |")
    lines.append("|---|---:|---:|")
    lines.append(
        f"| Protect chosen | {data['won_protect_chosen']} | "
        f"{data['lost_protect_chosen']} |"
    )
    lines.append(
        f"| Attack-through (ef+Protect legal+attack) | "
        f"{data['won_attack_through']} | "
        f"{data['lost_attack_through']} |"
    )
    lines.append(
        f"| Attack normal | {data['won_attack_normal']} | "
        f"{data['lost_attack_normal']} |"
    )
    lines.append("")
    lines.append("## 7. Speed-priority context")
    lines.append("")
    lines.append("| case | count |")
    lines.append("|---|---:|")
    lines.append(
        f"| sp_threat=True + Protect chosen | "
        f"{data['sp_threat_true_protect_chosen']} |"
    )
    lines.append(
        f"| sp_threat=False + Protect chosen | "
        f"{data['sp_threat_false_protect_chosen']} |"
    )
    lines.append("")
    lines.append("## 8. Top attack-through cases (smallest score_diff first)")
    lines.append("")
    lines.append("| battle | turn | slot | our_hp | sp_threat | scf_delta | score_diff | won |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for t in data["top_attack_through"]:
        lines.append(
            f"| `{t['battle_tag']}` | {t['turn']} | {t['slot']} | "
            f"{t.get('our_hp')} | {t.get('speed_priority_threat')} | "
            f"{t.get('switch_cf_delta')} | {t.get('score_diff')} | "
            f"{t.get('won')} |"
        )
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="PROTECT-1 read-only Protect usage audit"
    )
    parser.add_argument(
        "--input", action="append", required=True,
        help="Audit JSONL path. Pass multiple times.",
    )
    parser.add_argument(
        "--output-md", required=True,
    )
    parser.add_argument(
        "--output-json", required=True,
    )
    args = parser.parse_args(argv)
    if not all(os.path.exists(p) for p in args.input):
        for p in args.input:
            if not os.path.exists(p):
                print(f"ERROR: missing {p}", file=sys.stderr)
        return 2
    data = collect_audit(args.input)
    with open(args.output_json, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    _write_markdown(data, args.output_md)
    print(f"Wrote {args.output_json}", file=sys.stderr)
    print(f"Wrote {args.output_md}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
