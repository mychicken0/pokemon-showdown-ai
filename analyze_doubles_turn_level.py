#!/usr/bin/env python3
"""Phase TURN-2 — Read-Only Turn-Level Analyzer.

Aggregates turn-level audit fields across battles to
produce actionable evidence about the bot's decision
patterns. Read-only: no production change, no scoring
change, no new audit fields.

Inputs: persisted audit JSONL files (one or more).
The analyzer handles:
  - one audit file
  - multiple --audit-jsonl files
  - missing optional fields safely
  - legacy logs without BI fields

Outputs:
  - Markdown report (--md, required)
  - Optional JSON summary (--json)
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple


def _percentile(values: List[float], p: float) -> float:
    """Phase TURN-2: simple percentile (linear interp)."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _hp_bucket(hp_fraction: Optional[float]) -> str:
    """Phase TURN-2: bucket active HP fraction."""
    if hp_fraction is None:
        return "unknown"
    if hp_fraction < 0.25:
        return "0-25"
    if hp_fraction < 0.50:
        return "25-50"
    if hp_fraction < 0.75:
        return "50-75"
    return "75-100"


def _action_category(action_key: Any) -> str:
    """Phase TURN-2: categorize an action key.

    Handles list format (V4a key), string format
    (e.g. ``/choose pass``), and the "unknown" first
    element that appears when the V4a builder could not
    classify a pass action.
    """
    if not action_key:
        return "unknown"
    if isinstance(action_key, str):
        kl = action_key.lower()
        if "switch" in kl:
            return "switch"
        if "pass" in kl:
            return "pass"
        if "move" in kl or "choose" in kl:
            return "move"
        return "unknown"
    if isinstance(action_key, list):
        if len(action_key) >= 1:
            a = action_key[0]
            # The V4a key for a pass action is
            # ['unknown', '/choose pass', target, ''].
            # Detect pass by the second element.
            if (
                a == "unknown"
                and len(action_key) >= 2
                and isinstance(action_key[1], str)
                and "pass" in action_key[1].lower()
            ):
                return "pass"
        else:
            return "unknown"
    else:
        return "unknown"
    if a == "move":
        return "move"
    if a == "switch":
        return "switch"
    if a == "pass":
        return "pass"
    return "unknown"


# Phase BEHAVIOR-2: tiny stable allowlists for the
# analyzer. These are duplicated from the bot/doubles
# engine to keep the analyzer independent (no bot import
# needed). If a move is missing from this list, it is
# reported as "other_speed_control" or "other_support".
PROTECT_LIKE_MOVES = frozenset({
    "protect", "detect", "spikyshield", "kingsshield",
    "obstruct", "maxguard", "silktrap", "burningbulwark",
})

# Phase SPREAD-2: spread-defense move allowlist
# (counter-spread moves). Distinct from
# PROTECT_LIKE_MOVES because Wide Guard / Quick
# Guard / Crafty Shield were not in the 8-move
# allowlist. Pure observation allowlist; no scoring
# change in the analyzer.
SPREAD_DEFENSE_MOVES = frozenset({
    "wideguard", "quickguard", "craftyshield",
})

# Phase SPREAD-2: opp-side spread-move allowlist
# (duplicated from the audit logger). Used by the
# analyzer to compute ``opp_used_spread_turn_count``
# from prior artifacts that have
# ``selected_action_move_id`` per slot but no
# dedicated opp_actions spread counter (older
# artifacts).
OPP_SPREAD_LIKE_MOVES = frozenset({
    "hypervoice", "rockslide", "heatwave", "blizzard",
    "clangsour", "clangingscales", "dazzlinggleam",
    "muddywater", "snarl", "expandforce", "makeitrain",
    "glare", "icywind", "acidspray", "strugglebug",
    "waterspout", "eruption", "dragondarts", "earthquake",
    "surf", "discharge", "mindblown", "teeterdance",
})

OPP_PROTECT_LIKE_MOVES = frozenset({
    "protect", "detect", "spikyshield", "kingsshield",
    "banefulbunker", "silktrap", "burningbulwark",
    "maxguard", "obstruct",
})

SPEED_CONTROL_MOVES = frozenset({
    "tailwind", "trickroom", "icywind", "electroweb",
    "thunderwave", "thundercage", "scaryface",
    "stringshot", "cottonspore", "stunspore", "poisonpowder",
    "glare", "nuzzle", "stickyweb", "rockslide", "bulldoze",
    "lowsweep", "mudslap", "snarl",
})

# Category: slow the opponent.
SPEED_CONTROL_DROP_CATEGORY = frozenset({
    "icywind", "electroweb", "scaryface", "stringshot",
    "cottonspore", "stunspore", "poisonpowder", "glare",
    "nuzzle", "stickyweb", "rockslide", "bulldoze",
    "lowsweep", "mudslap", "snarl",
})

# Category: paralyze (speed-control via status).
SPEED_CONTROL_STATUS_CATEGORY = frozenset({
    "thunderwave", "glare", "stunspore", "nuzzle",
})

# Category: set field condition (tailwind/trickroom).
SPEED_CONTROL_FIELD_CATEGORY = frozenset({
    "tailwind", "trickroom", "thundercage",
})

SUPPORT_MOVE_ALLOWLIST = frozenset({
    # Ally beneficial
    "healpulse", "floralhealing", "decorate",
    "helpinghand", "aromatherapy", "life dew",
    "junglehealing", "healorder", "milkdrink",
    "recover", "softboiled", "roost", "morningsun",
    "moonlight", "synthesis", "wish", "healbell",
    "safeguard", "lightscreen", "reflect", "auroraveil",
    "tailwind", "trickroom", "magiccoat", "haze",
    # Redirection
    "followme", "ragepowder",
    # Disruption
    "thunderwave", "taunt", "encore", "disable",
    "torment", "fakeout", "fakeout", "icywind",
    "electroweb", "scaryface",
    # Either
    "pollenpuff", "skillswap",
})

# Support target category (duplicated from
# doubles_engine/support_targets).
SUPPORT_ALLY_BENEFICIAL = frozenset({
    "healpulse", "floralhealing", "decorate",
    "helpinghand", "aromatherapy", "life dew",
    "junglehealing", "healorder", "milkdrink",
    "recover", "softboiled", "roost", "morningsun",
    "moonlight", "synthesis", "wish", "healbell",
})
SUPPORT_FIELD = frozenset({
    "safeguard", "lightscreen", "reflect", "auroraveil",
    "tailwind", "trickroom", "magiccoat", "haze",
})
SUPPORT_OPPONENT_DISRUPTIVE = frozenset({
    "thunderwave", "taunt", "encore", "disable",
    "torment", "fakeout", "icywind", "electroweb",
    "scaryface",
})
SUPPORT_REDIRECTION = frozenset({
    "followme", "ragepowder",
})
SUPPORT_EITHER = frozenset({
    "pollenpuff", "skillswap",
})


def _move_id_from_action(action_key: Any) -> Optional[str]:
    """Phase BEHAVIOR-2: extract move id from V4a action key.

    The V4a key for a move action is
    ['move', '<command>', '<target>', '<mechanic>'].
    For example, ['move', '/choose move tackle 1', 'opp1', 'plain'].
    Returns the move id (e.g. 'tackle') or None.
    """
    if not isinstance(action_key, list) or len(action_key) < 2:
        return None
    if action_key[0] != "move":
        return None
    cmd = action_key[1]
    if not isinstance(cmd, str):
        return None
    # Format: '/choose move <id> <target>'
    parts = cmd.split()
    if len(parts) < 3:
        return None
    if parts[0] != "/choose" or parts[1] != "move":
        return None
    mid = parts[2].lower()
    # Strip any non-alphanumeric chars (e.g. punctuation).
    return "".join(c for c in mid if c.isalnum() or c == "_")


def _is_protect_move(move_id: Optional[str]) -> bool:
    """Phase BEHAVIOR-2: check if move is protect-like."""
    if move_id is None:
        return False
    return move_id in PROTECT_LIKE_MOVES


def _slot_from_top_level_list(
    value: Optional[List[Any]],
    slot_idx: int,
) -> Optional[Any]:
    """Phase BEHAVIOR-3: extract slot value from a
    top-level list field.

    The new logger persists fields like
    speed_priority_threatened as [slot0, slot1]. This
    helper extracts the value for a given slot.
    Returns None if the field is missing or the list is
    too short.
    """
    if not isinstance(value, list):
        return None
    if slot_idx >= len(value):
        return None
    return value[slot_idx]


def _categorize_speed_control(
    move_id: Optional[str],
) -> Optional[str]:
    """Phase BEHAVIOR-2: categorize a speed-control move.

    Returns one of: 'tailwind', 'trickroom', 'icywind',
    'electroweb', 'thunderwave', 'scaryface', 'other_drop',
    'other_status', 'other_field', None.
    """
    if move_id is None:
        return None
    if move_id in {"tailwind", "trickroom"}:
        return move_id
    if move_id in {"icywind", "electroweb"}:
        return move_id
    if move_id == "thunderwave":
        return "thunderwave"
    if move_id == "scaryface":
        return "scaryface"
    if move_id in SPEED_CONTROL_MOVES:
        if move_id in SPEED_CONTROL_FIELD_CATEGORY:
            return "other_field"
        if move_id in SPEED_CONTROL_DROP_CATEGORY:
            return "other_drop"
        if move_id in SPEED_CONTROL_STATUS_CATEGORY:
            return "other_status"
    return None


def _categorize_support_move(
    move_id: Optional[str],
) -> Optional[str]:
    """Phase BEHAVIOR-2: categorize a support move.

    Returns one of: 'heal_ally', 'buff_ally', 'field',
    'redirect', 'disrupt_opp', 'either', 'protect', None.
    """
    if move_id is None:
        return None
    if move_id in SUPPORT_ALLY_BENEFICIAL:
        return "heal_ally" if "heal" in move_id or "recover" in move_id or "roost" in move_id or "wish" in move_id or "milk" in move_id or "morningsun" in move_id or "moonlight" in move_id or "synthesis" in move_id or "softboiled" in move_id or "floralhealing" in move_id or "junglehealing" in move_id or "aromatherapy" in move_id or "healbell" in move_id or "healorder" in move_id or "life" in move_id else "buff_ally"
    if move_id in SUPPORT_FIELD:
        return "field"
    if move_id in SUPPORT_REDIRECTION:
        return "redirect"
    if move_id in SUPPORT_OPPONENT_DISRUPTIVE:
        return "disrupt_opp"
    if move_id in SUPPORT_EITHER:
        return "either"
    return None


def _v4a_mechanic(action_key: Any) -> str:
    """Phase TURN-2: extract V4a mechanic label."""
    if not isinstance(action_key, list) or len(action_key) < 4:
        return "unknown"
    return action_key[3] or "plain"


# Phase ANALYZER-2: parse a V4a action key into
# structured pieces for attribution. The V4a key
# is a 4-element list [kind, id, target, mechanic].
def _parse_v4a_action(
    action_key: Any,
) -> Dict[str, Optional[str]]:
    """Parse a V4a action key into structured fields.

    Returns a dict with:
      - raw: original key
      - kind: "move" / "switch" / "pass" / "unknown"
      - id: the move id (e.g. "tackle") or
        switch species
      - target: target slot as string, or None
      - mechanic: mechanic tag, or None
    """
    if not isinstance(action_key, list):
        return {
            "raw": str(action_key) if action_key else None,
            "kind": "unknown",
            "id": None,
            "target": None,
            "mechanic": None,
        }
    if len(action_key) < 2:
        return {
            "raw": str(action_key),
            "kind": "unknown",
            "id": None,
            "target": None,
            "mechanic": None,
        }
    a0 = action_key[0]
    a1 = action_key[1]
    a2 = action_key[2] if len(action_key) > 2 else None
    a3 = action_key[3] if len(action_key) > 3 else None
    kind = "unknown"
    if a0 == "move":
        kind = "move"
    elif a0 == "switch":
        kind = "switch"
    elif a0 == "pass":
        kind = "pass"
    elif (
        a0 == "unknown"
        and isinstance(a1, str)
        and "pass" in a1.lower()
    ):
        kind = "pass"
    return {
        "raw": str(action_key),
        "kind": kind,
        "id": str(a1).lower() if a1 is not None else None,
        "target": str(a2) if a2 is not None else None,
        "mechanic": str(a3) if a3 is not None else None,
    }


def _slot_labels(
    state_snapshot: Dict[str, Any],
) -> Dict[str, Optional[str]]:
    """Extract per-slot our/opp active species
    attribution labels from a state_snapshot.

    Returns dict with:
      - our_active_slot0 / our_active_slot1
      - opp_active_slot0 / opp_active_slot1
    """
    ss = state_snapshot or {}
    our = ss.get("our_active_species", []) or []
    opp = ss.get("opp_active_species", []) or []
    our0 = str(our[0]).lower() if len(our) > 0 else None
    our1 = str(our[1]).lower() if len(our) > 1 else None
    opp0 = str(opp[0]).lower() if len(opp) > 0 else None
    opp1 = str(opp[1]).lower() if len(opp) > 1 else None
    return {
        "our_active_slot0": our0,
        "our_active_slot1": our1,
        "opp_active_slot0": opp0,
        "opp_active_slot1": opp1,
    }


def _load_audit(path: str) -> Tuple[List[Dict[str, Any]], int]:
    """Phase TURN-2: load a JSONL file, skipping malformed lines."""
    rows: List[Dict[str, Any]] = []
    skipped = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                skipped += 1
                continue
    return rows, skipped


def _extract_turn_record(
    row: Dict[str, Any],
    row_index: int,
    source_file: str,
) -> List[Dict[str, Any]]:
    """Phase TURN-2: extract normalized turn records from
    a single audit row. Returns one record per turn.
    """
    battle_tag = row.get("battle_tag", "?")
    arm = row.get("benchmark_arm", "") or "unknown"
    enable_mega = bool(row.get("enable_mega_evolution", False))
    treatment_side = row.get("treatment_side", "") or ""
    player_side = row.get("player_side", "") or ""
    player_name = row.get("player_name", "") or ""
    won = row.get("won")
    turns = row.get("audit_turns", []) or []
    records: List[Dict[str, Any]] = []
    for ti, turn in enumerate(turns):
        if not isinstance(turn, dict):
            continue
        ss = turn.get("state_snapshot") or {}
        our_species = ss.get("our_active_species", []) or []
        opp_species = ss.get("opp_active_species", []) or []
        our_hp = ss.get("our_active_hp_fraction", []) or []
        opp_hp = ss.get("opp_active_hp_fraction", []) or []
        weather_raw = ss.get("weather", "none")
        if isinstance(weather_raw, list):
            weather = (
                ",".join(sorted(weather_raw))
                if weather_raw else "none"
            )
        else:
            weather = str(weather_raw) if weather_raw else "none"
        fields_list = ss.get("fields", []) or []
        if not isinstance(fields_list, list):
            fields_list = [str(fields_list)]
        fields_key = ",".join(sorted(fields_list)) if fields_list else "none"

        v4a_sel = turn.get("v4a_selected_joint_key")
        v4a_final = turn.get("v4a_final_action_keys")
        v2l_sel = turn.get("v2l1_selected_joint_key")
        v2l_final = turn.get("v2l1_final_action_keys")
        scf = turn.get("switch_counterfactual") or {}

        # Action categories for the selected joint.
        slot0_cat = "unknown"
        slot1_cat = "unknown"
        if isinstance(v4a_sel, list) and len(v4a_sel) >= 1:
            slot0_cat = _action_category(v4a_sel[0])
        if isinstance(v4a_sel, list) and len(v4a_sel) >= 2:
            slot1_cat = _action_category(v4a_sel[1])
        # V4a mechanic labels.
        slot0_mech = _v4a_mechanic(
            v4a_sel[0] if isinstance(v4a_sel, list) and len(v4a_sel) >= 1 else None
        )
        slot1_mech = _v4a_mechanic(
            v4a_sel[1] if isinstance(v4a_sel, list) and len(v4a_sel) >= 2 else None
        )

        rec = {
            "source_file": source_file,
            "row_index": row_index,
            "battle_tag": battle_tag,
            "benchmark_arm": arm,
            "enable_mega_evolution": enable_mega,
            "treatment_side": treatment_side,
            "player_side": player_side,
            "player_name": player_name,
            "won": won,
            "turn_index": ti,
            "turn_number": turn.get("turn"),
            "selected_joint_order": turn.get("selected_joint_order"),
            "selected_score": turn.get("selected_score"),
            "v4a_selected_joint_key": v4a_sel,
            "v4a_final_action_keys": v4a_final,
            "v2l1_selected_joint_key": v2l_sel,
            "v2l1_final_action_keys": v2l_final,
            "slot0_category": slot0_cat,
            "slot1_category": slot1_cat,
            "slot0_mechanic": slot0_mech,
            "slot1_mechanic": slot1_mech,
            "state_snapshot": ss,
            "our_active_species": our_species,
            "opp_active_species": opp_species,
            "our_active_hp_fraction": our_hp,
            "opp_active_hp_fraction": opp_hp,
            "hp_bucket_slot0": _hp_bucket(
                our_hp[0] if len(our_hp) > 0 else None
            ),
            "hp_bucket_slot1": _hp_bucket(
                our_hp[1] if len(our_hp) > 1 else None
            ),
            "weather": weather,
            "fields": fields_key,
            "switch_counterfactual": scf,
            # Timing
            "decision_time_ms": turn.get("decision_time_ms"),
            "valid_order_time_ms": turn.get("valid_order_time_ms"),
            "score_action_time_ms": turn.get("score_action_time_ms"),
            "joint_scoring_time_ms": turn.get("joint_scoring_time_ms"),
            "audit_postprocess_time_ms": turn.get(
                "audit_postprocess_time_ms"
            ),
            "joint_order_count": turn.get("joint_order_count"),
            "total_legal_joint_orders": turn.get(
                "total_legal_joint_orders"
            ),
            "score_action_call_count": turn.get(
                "score_action_call_count"
            ),
            "score_gap_selected_best_alt": turn.get(
                "score_gap_selected_best_alt"
            ),
            # Safety / correction flags
            "overkill_penalty_triggered": turn.get(
                "overkill_penalty_triggered"
            ),
            "order_aware_overkill_penalty_applied": turn.get(
                "order_aware_overkill_penalty_applied"
            ),
            "focus_fire_triggered": turn.get("focus_fire_triggered"),
            "ally_hit_penalty_triggered": turn.get(
                "ally_hit_penalty_triggered"
            ),
            "stale_target_selected": turn.get("stale_target_selected"),
            "stale_target_avoided": turn.get("stale_target_avoided"),
            "stale_target_caused_no_effect": turn.get(
                "stale_target_caused_no_effect"
            ),
            "stale_target_caused_type_immune": turn.get(
                "stale_target_caused_type_immune"
            ),
            "low_hp_opponent_existed": turn.get(
                "low_hp_opponent_existed"
            ),
            "low_hp_opponent_targeted": turn.get(
                "low_hp_opponent_targeted"
            ),
            "support_target_candidate_blocked": turn.get(
                "support_target_candidate_blocked"
            ),
            "support_target_wrong_side_selected_slot0": turn.get(
                "support_target_wrong_side_selected_slot0"
            ),
            "support_target_wrong_side_selected_slot1": turn.get(
                "support_target_wrong_side_selected_slot1"
            ),
            "narrow_ally_heal_candidate_blocked_slot0": turn.get(
                "narrow_ally_heal_candidate_blocked_slot0"
            ),
            "narrow_ally_heal_candidate_blocked_slot1": turn.get(
                "narrow_ally_heal_candidate_blocked_slot1"
            ),
            # Phase BEHAVIOR-2: protect / speed-control /
            # speed-priority / support-targeting.
            "protect_selected_slot0": _is_protect_move(
                _move_id_from_action(
                    v4a_sel[0]
                    if isinstance(v4a_sel, list)
                    and len(v4a_sel) >= 1
                    else None
                )
            ),
            "protect_selected_slot1": _is_protect_move(
                _move_id_from_action(
                    v4a_sel[1]
                    if isinstance(v4a_sel, list)
                    and len(v4a_sel) >= 2
                    else None
                )
            ),
            "speed_control_selected_slot0": _categorize_speed_control(
                _move_id_from_action(
                    v4a_sel[0]
                    if isinstance(v4a_sel, list)
                    and len(v4a_sel) >= 1
                    else None
                )
            ),
            "speed_control_selected_slot1": _categorize_speed_control(
                _move_id_from_action(
                    v4a_sel[1]
                    if isinstance(v4a_sel, list)
                    and len(v4a_sel) >= 2
                    else None
                )
            ),
            "support_selected_slot0": _categorize_support_move(
                _move_id_from_action(
                    v4a_sel[0]
                    if isinstance(v4a_sel, list)
                    and len(v4a_sel) >= 1
                    else None
                )
            ),
            "support_selected_slot1": _categorize_support_move(
                _move_id_from_action(
                    v4a_sel[1]
                    if isinstance(v4a_sel, list)
                    and len(v4a_sel) >= 2
                    else None
                )
            ),
            # Speed-priority threat (from persisted fields).
            # Phase BEHAVIOR-3: read from new top-level
            # fields with array shape.
            "speed_priority_field_present": (
                "speed_priority_threatened" in turn
            ),
            "speed_priority_threat_slot0": (
                _slot_from_top_level_list(
                    turn.get("speed_priority_threatened"), 0
                )
            ),
            "speed_priority_threat_slot1": (
                _slot_from_top_level_list(
                    turn.get("speed_priority_threatened"), 1
                )
            ),
            # Phase BEHAVIOR-9: score-diff debug fields.
            "speed_priority_score_diff_slot0": turn.get(
                "speed_priority_score_diff_slot0"
            ),
            "speed_priority_score_diff_slot1": turn.get(
                "speed_priority_score_diff_slot1"
            ),
            "speed_priority_protect_score_slot0": turn.get(
                "speed_priority_protect_score_slot0"
            ),
            "speed_priority_protect_score_slot1": turn.get(
                "speed_priority_protect_score_slot1"
            ),
            "speed_priority_best_attack_score_slot0": turn.get(
                "speed_priority_best_attack_score_slot0"
            ),
            "speed_priority_best_attack_score_slot1": turn.get(
                "speed_priority_best_attack_score_slot1"
            ),
            "protected_due_to_speed_priority": (
                turn.get("protected_due_to_speed_priority")
            ),
            "speed_priority_protect_bonus_applied": (
                turn.get("speed_priority_protect_bonus_applied")
            ),
            "speed_priority_attack_penalty_applied": (
                turn.get("speed_priority_attack_penalty_applied")
            ),
            "speed_priority_switch_bonus_applied": (
                turn.get("speed_priority_switch_bonus_applied")
            ),
            "expected_to_faint_before_moving": (
                turn.get("expected_to_faint_before_moving")
            ),
            "faster_opponents": turn.get("faster_opponents"),
            "priority_opponents": turn.get("priority_opponents"),
            "target_used_protect": turn.get("target_used_protect"),
            # Phase SPREAD-2: project the per-slot
            # spread-defense fields from slot_0 /
            # slot_1 into the flat record shape so
            # the analyzer aggregation can read them.
            "wide_guard_legal_slot0": bool(
                (turn.get("slot_0") or {}).get("wide_guard_legal")
            ),
            "wide_guard_legal_slot1": bool(
                (turn.get("slot_1") or {}).get("wide_guard_legal")
            ),
            "quick_guard_legal_slot0": bool(
                (turn.get("slot_0") or {}).get("quick_guard_legal")
            ),
            "quick_guard_legal_slot1": bool(
                (turn.get("slot_1") or {}).get("quick_guard_legal")
            ),
            "crafty_shield_legal_slot0": bool(
                (turn.get("slot_0") or {}).get("crafty_shield_legal")
            ),
            "crafty_shield_legal_slot1": bool(
                (turn.get("slot_1") or {}).get("crafty_shield_legal")
            ),
            "spread_defense_selected_slot0": str(
                (turn.get("slot_0") or {}).get(
                    "spread_defense_selected"
                )
                or ""
            ),
            "spread_defense_selected_slot1": str(
                (turn.get("slot_1") or {}).get(
                    "spread_defense_selected"
                )
                or ""
            ),
            "opp_pressure_state": bool(
                turn.get("opp_pressure_state")
            ),
            "opp_actions": dict(turn.get("opp_actions") or {}),
            # Phase SPREAD-4: score-gap lists at the
            # top level of each turn. Used by the
            # dry-run simulator to compute decision-
            # flip counts at hypothetical bonus
            # magnitudes.
            "score_gap_wide_guard_vs_selected": list(
                turn.get("score_gap_wide_guard_vs_selected") or []
            ),
            "score_gap_quick_guard_vs_selected": list(
                turn.get("score_gap_quick_guard_vs_selected") or []
            ),
            # Per-slot raw score mirror (projected
            # from slot_0 / slot_1).
            "wide_guard_score_slot0": (
                (turn.get("slot_0") or {}).get("wide_guard_score")
            ),
            "wide_guard_score_slot1": (
                (turn.get("slot_1") or {}).get("wide_guard_score")
            ),
            "quick_guard_score_slot0": (
                (turn.get("slot_0") or {}).get("quick_guard_score")
            ),
            "quick_guard_score_slot1": (
                (turn.get("slot_1") or {}).get("quick_guard_score")
            ),
            "crafty_shield_score_slot0": (
                (turn.get("slot_0") or {}).get("crafty_shield_score")
            ),
            "crafty_shield_score_slot1": (
                (turn.get("slot_1") or {}).get("crafty_shield_score")
            ),
            # Phase BEHAVIOR-2: store move_id for
            # by-move aggregation.
            "move_id_slot0": _move_id_from_action(
                v4a_sel[0]
                if isinstance(v4a_sel, list)
                and len(v4a_sel) >= 1
                else None
            ),
            "move_id_slot1": _move_id_from_action(
                v4a_sel[1]
                if isinstance(v4a_sel, list)
                and len(v4a_sel) >= 2
                else None
            ),
        }
        records.append(rec)
    return records


def _aggregate(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Phase TURN-2: aggregate across all turn records."""
    data_quality = {
        "rows_total": 0,
        "rows_with_audit_turns": 0,
        "rows_missing_audit_turns": 0,
        "turns_total": len(records),
        "turns_missing_state_snapshot": 0,
        "skipped_lines": 0,
    }
    arm_summary = {
        "by_arm": Counter(),
        "by_player_side": Counter(),
        "won": 0,
        "lost": 0,
    }
    action_selection = {
        "slot0_category": Counter(),
        "slot1_category": Counter(),
        "slot0_mechanic": Counter(),
        "slot1_mechanic": Counter(),
    }
    margin_values: List[float] = []
    low_margin_turns: List[Dict[str, Any]] = []
    # Phase BEHAVIOR-9: collect score_diff values for
    # distribution analysis.
    score_diff_values: List[float] = []
    timing = {
        "decision_time_ms": [],
        "valid_order_time_ms": [],
        "score_action_time_ms": [],
        "joint_scoring_time_ms": [],
        "audit_postprocess_time_ms": [],
    }
    safety = {
        "overkill_penalty_triggered": 0,
        "order_aware_overkill_penalty_applied": 0,
        "focus_fire_triggered": 0,
        "ally_hit_penalty_triggered": 0,
        "stale_target_selected": 0,
        "stale_target_avoided": 0,
        "stale_target_caused_no_effect": 0,
        "stale_target_caused_type_immune": 0,
        "low_hp_opponent_existed": 0,
        "low_hp_opponent_targeted": 0,
        "support_target_candidate_blocked": 0,
        "support_target_wrong_side_selected": 0,
        "narrow_ally_heal_candidate_blocked": 0,
    }
    # Phase SPREAD-2: spread-defense summary.
    # Mirrors ``protect_summary`` for Wide Guard /
    # Quick Guard / Crafty Shield. Pure observation;
    # no scoring change in the analyzer.
    spread_defense_summary = {
        "slot0_wide_guard_legal": 0,
        "slot1_wide_guard_legal": 0,
        "any_slot_wide_guard_legal": 0,
        "slot0_quick_guard_legal": 0,
        "slot1_quick_guard_legal": 0,
        "any_slot_quick_guard_legal": 0,
        "slot0_crafty_shield_legal": 0,
        "slot1_crafty_shield_legal": 0,
        "any_slot_crafty_shield_legal": 0,
        "slot0_wide_guard_selected": 0,
        "slot1_wide_guard_selected": 0,
        "any_slot_wide_guard_selected": 0,
        "slot0_quick_guard_selected": 0,
        "slot1_quick_guard_selected": 0,
        "any_slot_quick_guard_selected": 0,
        "slot0_crafty_shield_selected": 0,
        "slot1_crafty_shield_selected": 0,
        "any_slot_crafty_shield_selected": 0,
        "selected_by_move": Counter(),
        "spread_defense_legal_not_selected": 0,
        "opp_pressure_state_turn_count": 0,
        "opp_used_spread_turn_count": 0,
        "opp_used_protect_turn_count": 0,
        "opp_used_wide_guard_turn_count": 0,
        "opp_used_quick_guard_turn_count": 0,
        # Phase SPREAD-4: score-gap statistics so
        # the dry-run simulator can pick a bonus
        # magnitude. Negative gap = selected move
        # scored higher; positive gap = spread-
        # defense move would have flipped the
        # decision.
        "score_gap_wg_legal_not_selected": [],  # list of gaps
        "score_gap_wg_legal_not_selected_with_pressure": [],
        "score_gap_wg_legal_not_selected_min": 0.0,
        "score_gap_wg_legal_not_selected_p25": 0.0,
        "score_gap_wg_legal_not_selected_median": 0.0,
        "score_gap_wg_legal_not_selected_p75": 0.0,
        "score_gap_wg_legal_not_selected_max": 0.0,
        "score_gap_wg_legal_not_selected_mean": 0.0,
    }
    # Phase BEHAVIOR-2: protect / speed-control /
    # speed-priority / support-targeting summaries.
    protect_summary = {
        "slot0_protect_selected": 0,
        "slot1_protect_selected": 0,
        "any_slot_protect_selected": 0,
        "by_move": Counter(),
        "missing_protect_like_available": 0,
        "unavailable": False,
    }
    speed_control_summary = {
        "slot0_speed_control_selected": 0,
        "slot1_speed_control_selected": 0,
        "any_slot_speed_control_selected": 0,
        "by_move": Counter(),
        "by_category": Counter(),
        "by_slot": Counter(),
    }
    speed_priority_summary = {
        "slot0_threatened": 0,
        "slot1_threatened": 0,
        "any_slot_threatened": 0,
        "protected_due_to_speed_priority_slot0_true_count": 0,
        "protected_due_to_speed_priority_slot1_true_count": 0,
        "protected_due_to_speed_priority_turn_any_count": 0,
        "speed_priority_protect_bonus_applied_slot0_true_count": 0,
        "speed_priority_protect_bonus_applied_slot1_true_count": 0,
        "speed_priority_protect_bonus_applied_turn_any_count": 0,
        "speed_priority_attack_penalty_applied_slot0_true_count": 0,
        "speed_priority_attack_penalty_applied_slot1_true_count": 0,
        "speed_priority_attack_penalty_applied_turn_any_count": 0,
        "speed_priority_switch_bonus_applied_slot0_true_count": 0,
        "speed_priority_switch_bonus_applied_slot1_true_count": 0,
        "speed_priority_switch_bonus_applied_turn_any_count": 0,
        "expected_to_faint_before_moving_slot0_true_count": 0,
        "expected_to_faint_before_moving_slot1_true_count": 0,
        "expected_to_faint_before_moving_turn_any_count": 0,
        # Phase BEHAVIOR-9: score-diff debug fields.
        "score_debug_available_count": 0,
        "score_diff_min": 0.0,
        "score_diff_p25": 0.0,
        "score_diff_median": 0.0,
        "score_diff_p75": 0.0,
        "score_diff_max": 0.0,
        "score_diff_mean": 0.0,
        "score_diff_count": 0,
        "expected_faint_with_negative_diff_count": 0,
        "expected_faint_with_positive_diff_count": 0,
        "protect_bonus_with_negative_diff_count": 0,
        "fields_available": False,
        "fields_missing_count": 0,
    }
    support_targeting_summary = {
        "slot0_support_selected": 0,
        "slot1_support_selected": 0,
        "any_slot_support_selected": 0,
        "by_category": Counter(),
        "by_move": Counter(),
        "wrong_side_selected": 0,
        "narrow_ally_heal_blocked": 0,
        "wrong_side_field_available": False,
    }
    state_slices = {
        "hp_bucket_slot0": Counter(),
        "hp_bucket_slot1": Counter(),
        "weather": Counter(),
        "fields": Counter(),
        "our_species": Counter(),
        "opp_species": Counter(),
    }
    suspicious: List[Dict[str, Any]] = []
    per_battle: Dict[str, Dict[str, Any]] = {}

    for rec in records:
        if not rec.get("state_snapshot"):
            data_quality["turns_missing_state_snapshot"] += 1
        data_quality["rows_total"] += 0  # rows_total is rows, not turns
        arm_summary["by_arm"][rec.get("benchmark_arm", "?")] += 1
        arm_summary["by_player_side"][rec.get("player_side", "?")] += 1
        if rec.get("won") is True:
            arm_summary["won"] += 1
        elif rec.get("won") is False:
            arm_summary["lost"] += 1
        # Action selection
        action_selection["slot0_category"][
            rec.get("slot0_category", "unknown")
        ] += 1
        action_selection["slot1_category"][
            rec.get("slot1_category", "unknown")
        ] += 1
        action_selection["slot0_mechanic"][
            rec.get("slot0_mechanic", "unknown")
        ] += 1
        action_selection["slot1_mechanic"][
            rec.get("slot1_mechanic", "unknown")
        ] += 1
        # Margin
        margin = rec.get("score_gap_selected_best_alt")
        if margin is not None:
            try:
                margin_values.append(float(margin))
                if float(margin) < 10.0:
                    low_margin_turns.append({
                        "battle_tag": rec.get("battle_tag"),
                        "turn": rec.get("turn_number"),
                        "margin": float(margin),
                        "selected": rec.get("v4a_selected_joint_key"),
                    })
            except (TypeError, ValueError):
                pass
        # Timing
        for k in timing.keys():
            v = rec.get(k)
            if v is not None:
                try:
                    timing[k].append(float(v))
                except (TypeError, ValueError):
                    pass
        # Safety
        for k in [
            "overkill_penalty_triggered",
            "order_aware_overkill_penalty_applied",
            "focus_fire_triggered",
            "ally_hit_penalty_triggered",
            "stale_target_selected",
            "stale_target_avoided",
            "stale_target_caused_no_effect",
            "stale_target_caused_type_immune",
            "low_hp_opponent_existed",
            "low_hp_opponent_targeted",
            "support_target_candidate_blocked",
        ]:
            if rec.get(k):
                safety[k] += 1
        # Per-slot safety checks (support wrong-side, narrow ally heal).
        if (rec.get("support_target_wrong_side_selected_slot0")
                or rec.get("support_target_wrong_side_selected_slot1")):
            safety["support_target_wrong_side_selected"] += 1
        if (rec.get("narrow_ally_heal_candidate_blocked_slot0")
                or rec.get("narrow_ally_heal_candidate_blocked_slot1")):
            safety["narrow_ally_heal_candidate_blocked"] += 1
                # Phase BEHAVIOR-2: protect summary.
        p0 = rec.get("protect_selected_slot0")
        p1 = rec.get("protect_selected_slot1")
        if p0:
            protect_summary["slot0_protect_selected"] += 1
        if p1:
            protect_summary["slot1_protect_selected"] += 1
        if p0 or p1:
            protect_summary["any_slot_protect_selected"] += 1
        # Phase SPREAD-2: spread-defense legal/selected
        # summary (Wide Guard / Quick Guard / Crafty
        # Shield). Pure observation; no scoring change.
        wg_l_0 = bool(rec.get("wide_guard_legal_slot0"))
        wg_l_1 = bool(rec.get("wide_guard_legal_slot1"))
        qg_l_0 = bool(rec.get("quick_guard_legal_slot0"))
        qg_l_1 = bool(rec.get("quick_guard_legal_slot1"))
        cs_l_0 = bool(rec.get("crafty_shield_legal_slot0"))
        cs_l_1 = bool(rec.get("crafty_shield_legal_slot1"))
        wg_s_0 = (rec.get("spread_defense_selected_slot0") or "") == "wideguard"
        qg_s_0 = (rec.get("spread_defense_selected_slot0") or "") == "quickguard"
        cs_s_0 = (rec.get("spread_defense_selected_slot0") or "") == "craftyshield"
        wg_s_1 = (rec.get("spread_defense_selected_slot1") or "") == "wideguard"
        qg_s_1 = (rec.get("spread_defense_selected_slot1") or "") == "quickguard"
        cs_s_1 = (rec.get("spread_defense_selected_slot1") or "") == "craftyshield"
        if wg_l_0:
            spread_defense_summary["slot0_wide_guard_legal"] += 1
        if wg_l_1:
            spread_defense_summary["slot1_wide_guard_legal"] += 1
        if wg_l_0 or wg_l_1:
            spread_defense_summary["any_slot_wide_guard_legal"] += 1
        if qg_l_0:
            spread_defense_summary["slot0_quick_guard_legal"] += 1
        if qg_l_1:
            spread_defense_summary["slot1_quick_guard_legal"] += 1
        if qg_l_0 or qg_l_1:
            spread_defense_summary["any_slot_quick_guard_legal"] += 1
        if cs_l_0:
            spread_defense_summary["slot0_crafty_shield_legal"] += 1
        if cs_l_1:
            spread_defense_summary["slot1_crafty_shield_legal"] += 1
        if cs_l_0 or cs_l_1:
            spread_defense_summary["any_slot_crafty_shield_legal"] += 1
        if wg_s_0:
            spread_defense_summary["slot0_wide_guard_selected"] += 1
        if wg_s_1:
            spread_defense_summary["slot1_wide_guard_selected"] += 1
        if wg_s_0 or wg_s_1:
            spread_defense_summary["any_slot_wide_guard_selected"] += 1
            spread_defense_summary["selected_by_move"]["wideguard"] += 1
        if qg_s_0:
            spread_defense_summary["slot0_quick_guard_selected"] += 1
        if qg_s_1:
            spread_defense_summary["slot1_quick_guard_selected"] += 1
        if qg_s_0 or qg_s_1:
            spread_defense_summary["any_slot_quick_guard_selected"] += 1
            spread_defense_summary["selected_by_move"]["quickguard"] += 1
        if cs_s_0:
            spread_defense_summary["slot0_crafty_shield_selected"] += 1
        if cs_s_1:
            spread_defense_summary["slot1_crafty_shield_selected"] += 1
        if cs_s_0 or cs_s_1:
            spread_defense_summary["any_slot_crafty_shield_selected"] += 1
            spread_defense_summary["selected_by_move"]["craftyshield"] += 1
        # Counterfactual: any spread-defense legal
        # this turn but no spread-defense move
        # selected.
        any_legal = (
            wg_l_0 or wg_l_1 or qg_l_0 or qg_l_1
            or cs_l_0 or cs_l_1
        )
        any_selected = (
            wg_s_0 or wg_s_1 or qg_s_0 or qg_s_1
            or cs_s_0 or cs_s_1
        )
        if any_legal and not any_selected:
            spread_defense_summary[
                "spread_defense_legal_not_selected"
            ] += 1
        if bool(rec.get("opp_pressure_state")):
            spread_defense_summary[
                "opp_pressure_state_turn_count"
            ] += 1
        opp_a = rec.get("opp_actions", {}) or {}
        if opp_a.get("opponent_used_spread"):
            spread_defense_summary["opp_used_spread_turn_count"] += 1
        if opp_a.get("opponent_used_protect"):
            spread_defense_summary["opp_used_protect_turn_count"] += 1
        if opp_a.get("opponent_used_wide_guard"):
            spread_defense_summary["opp_used_wide_guard_turn_count"] += 1
        if opp_a.get("opponent_used_quick_guard"):
            spread_defense_summary["opp_used_quick_guard_turn_count"] += 1

        # Phase SPREAD-4: collect score-gap values
        # for turns where WG is legal but NOT
        # selected. The dry-run simulator uses
        # these to find the minimum bonus that
        # would flip each turn's decision.
        gap_wg = rec.get("score_gap_wide_guard_vs_selected") or []
        opp_p_for_gap = bool(rec.get("opp_pressure_state"))
        if wg_l_0 or wg_l_1:
            for g in gap_wg:
                if g is None:
                    continue
                if not any_selected:
                    spread_defense_summary[
                        "score_gap_wg_legal_not_selected"
                    ].append(g)
                    if opp_p_for_gap:
                        spread_defense_summary[
                            "score_gap_wg_legal_not_selected_with_pressure"
                        ].append(g)


        # Phase BEHAVIOR-2: speed-control summary.
        sc0 = rec.get("speed_control_selected_slot0")
        sc1 = rec.get("speed_control_selected_slot1")
        if sc0:
            speed_control_summary[
                "slot0_speed_control_selected"
            ] += 1
            speed_control_summary["by_category"][sc0] += 1
            speed_control_summary["by_move"][
                rec.get("move_id_slot0") or "unknown"
            ] += 1
            speed_control_summary["by_slot"]["slot0"] += 1
        if sc1:
            speed_control_summary[
                "slot1_speed_control_selected"
            ] += 1
            speed_control_summary["by_category"][sc1] += 1
            speed_control_summary["by_move"][
                rec.get("move_id_slot1") or "unknown"
            ] += 1
            speed_control_summary["by_slot"]["slot1"] += 1
        if sc0 or sc1:
            speed_control_summary[
                "any_slot_speed_control_selected"
            ] += 1
        # Phase BEHAVIOR-2: speed-priority summary.
        sp0 = rec.get("speed_priority_threat_slot0")
        sp1 = rec.get("speed_priority_threat_slot1")
        if rec.get("speed_priority_field_present"):
            speed_priority_summary["fields_available"] = True
            if sp0:
                speed_priority_summary[
                    "slot0_threatened"
                ] += 1
            if sp1:
                speed_priority_summary[
                    "slot1_threatened"
                ] += 1
            if sp0 or sp1:
                speed_priority_summary[
                    "any_slot_threatened"
                ] += 1
            # Phase BEHAVIOR-4: report both slot_true_count
            # and turn_any_count. The list shape is
            # [slot0_bool, slot1_bool].
            for fld in [
                "protected_due_to_speed_priority",
                "speed_priority_protect_bonus_applied",
                "speed_priority_attack_penalty_applied",
                "speed_priority_switch_bonus_applied",
                "expected_to_faint_before_moving",
            ]:
                v = rec.get(fld)
                if isinstance(v, list) and len(v) >= 2:
                    if v[0]:
                        speed_priority_summary[
                            f"{fld}_slot0_true_count"
                        ] += 1
                    if v[1]:
                        speed_priority_summary[
                            f"{fld}_slot1_true_count"
                        ] += 1
                    if v[0] or v[1]:
                        speed_priority_summary[
                            f"{fld}_turn_any_count"
                        ] += 1
        else:
            speed_priority_summary["fields_missing_count"] += 1
        # Phase BEHAVIOR-9: score-diff debug.
        d0 = rec.get("speed_priority_score_diff_slot0")
        d1 = rec.get("speed_priority_score_diff_slot1")
        for d in (d0, d1):
            if isinstance(d, (int, float)):
                speed_priority_summary["score_diff_count"] += 1
                score_diff_values.append(d)
        if d0 is not None or d1 is not None:
            speed_priority_summary[
                "score_debug_available_count"
            ] += 1
            # Check expected_faint + score_diff combo.
            f0 = rec.get("expected_to_faint_before_moving")
            if isinstance(f0, list):
                if (f0[0] if len(f0) > 0 else False) and (
                    d0 is not None and d0 < 0
                ):
                    speed_priority_summary[
                        "expected_faint_with_negative_diff_count"
                    ] += 1
                if (f0[0] if len(f0) > 0 else False) and (
                    d0 is not None and d0 > 0
                ):
                    speed_priority_summary[
                        "expected_faint_with_positive_diff_count"
                    ] += 1
                if (f0[1] if len(f0) > 1 else False) and (
                    d1 is not None and d1 < 0
                ):
                    speed_priority_summary[
                        "expected_faint_with_negative_diff_count"
                    ] += 1
                if (f0[1] if len(f0) > 1 else False) and (
                    d1 is not None and d1 > 0
                ):
                    speed_priority_summary[
                        "expected_faint_with_positive_diff_count"
                    ] += 1
            # protect_bonus + negative diff.
            pb0 = rec.get("speed_priority_protect_bonus_applied")
            if isinstance(pb0, list):
                if (pb0[0] if len(pb0) > 0 else False) and (
                    d0 is not None and d0 < 0
                ):
                    speed_priority_summary[
                        "protect_bonus_with_negative_diff_count"
                    ] += 1
                if (pb0[1] if len(pb0) > 1 else False) and (
                    d1 is not None and d1 < 0
                ):
                    speed_priority_summary[
                        "protect_bonus_with_negative_diff_count"
                    ] += 1
        # Phase BEHAVIOR-2: support-targeting summary.
        sup0 = rec.get("support_selected_slot0")
        sup1 = rec.get("support_selected_slot1")
        if sup0:
            support_targeting_summary[
                "slot0_support_selected"
            ] += 1
            support_targeting_summary["by_category"][sup0] += 1
            support_targeting_summary["by_move"][
                rec.get("move_id_slot0") or "unknown"
            ] += 1
        if sup1:
            support_targeting_summary[
                "slot1_support_selected"
            ] += 1
            support_targeting_summary["by_category"][sup1] += 1
            support_targeting_summary["by_move"][
                rec.get("move_id_slot1") or "unknown"
            ] += 1
        if sup0 or sup1:
            support_targeting_summary[
                "any_slot_support_selected"
            ] += 1
        # Wrong-side support block (if fields present).
        if (rec.get("support_target_wrong_side_selected_slot0") is not None
                or rec.get(
                    "support_target_wrong_side_selected_slot1"
                ) is not None):
            support_targeting_summary["wrong_side_field_available"] = True
            if (rec.get("support_target_wrong_side_selected_slot0")
                    or rec.get("support_target_wrong_side_selected_slot1")):
                support_targeting_summary["wrong_side_selected"] += 1
        if (rec.get("narrow_ally_heal_candidate_blocked_slot0")
                or rec.get("narrow_ally_heal_candidate_blocked_slot1")):
            support_targeting_summary["narrow_ally_heal_blocked"] += 1
        # State slices
        state_slices["hp_bucket_slot0"][
            rec.get("hp_bucket_slot0", "unknown")
        ] += 1
        state_slices["hp_bucket_slot1"][
            rec.get("hp_bucket_slot1", "unknown")
        ] += 1
        state_slices["weather"][rec.get("weather", "none")] += 1
        state_slices["fields"][rec.get("fields", "none")] += 1
        species0 = rec.get("our_active_species", [])
        if species0:
            state_slices["our_species"][species0[0]] += 1
        species1 = rec.get("our_active_species", [])
        if len(species1) > 1:
            state_slices["our_species"][species1[1]] += 1
        opp0 = rec.get("opp_active_species", [])
        if opp0:
            state_slices["opp_species"][opp0[0]] += 1
        opp1 = rec.get("opp_active_species", [])
        if len(opp1) > 1:
            state_slices["opp_species"][opp1[1]] += 1
        # Per-battle
        bt = rec.get("battle_tag", "?")
        if bt not in per_battle:
            per_battle[bt] = {
                "battle_tag": bt,
                "arm": rec.get("benchmark_arm"),
                "won": rec.get("won"),
                "turns": 0,
                "suspicious": 0,
            }
        per_battle[bt]["turns"] += 1
        # Suspicious: high decision time OR low margin OR safety block
        is_suspicious = False
        susp_reasons = []
        dt = rec.get("decision_time_ms")
        if dt is not None and dt > 500.0:
            is_suspicious = True
            susp_reasons.append(f"high_decision_time:{dt:.1f}ms")
        if margin is not None and margin < 5.0:
            is_suspicious = True
            susp_reasons.append(f"low_margin:{float(margin):.1f}")
        if rec.get("stale_target_selected"):
            is_suspicious = True
            susp_reasons.append("stale_target_selected")
        if rec.get("stale_target_caused_no_effect"):
            is_suspicious = True
            susp_reasons.append("stale_caused_no_effect")
        if rec.get("stale_target_caused_type_immune"):
            is_suspicious = True
            susp_reasons.append("stale_caused_type_immune")
        if rec.get("overkill_penalty_triggered"):
            is_suspicious = True
            susp_reasons.append("overkill_triggered")
        if rec.get("order_aware_overkill_penalty_applied"):
            is_suspicious = True
            susp_reasons.append("overkill_applied")
        if rec.get("support_target_candidate_blocked"):
            is_suspicious = True
            susp_reasons.append("support_target_blocked")
        if (rec.get("support_target_wrong_side_selected_slot0")
                or rec.get("support_target_wrong_side_selected_slot1")):
            is_suspicious = True
            susp_reasons.append("support_wrong_side")
        if is_suspicious:
            # Phase ANALYZER-2: per-slot attribution so
            # readers can identify our vs opp species
            # without consulting the raw state_snapshot.
            v4a_sel_rec = rec.get("v4a_selected_joint_key")
            slot0_act = (
                v4a_sel_rec[0] if isinstance(v4a_sel_rec, list)
                and len(v4a_sel_rec) >= 1 else None
            )
            slot1_act = (
                v4a_sel_rec[1] if isinstance(v4a_sel_rec, list)
                and len(v4a_sel_rec) >= 2 else None
            )
            slot0_parsed = _parse_v4a_action(slot0_act)
            slot1_parsed = _parse_v4a_action(slot1_act)
            labels = _slot_labels(rec.get("state_snapshot", {}))
            suspicious.append({
                "battle_tag": rec.get("battle_tag"),
                "arm": rec.get("benchmark_arm"),
                "turn": rec.get("turn_number"),
                "reasons": susp_reasons,
                "selected": rec.get("v4a_selected_joint_key"),
                "selected_slot0_action": slot0_act,
                "selected_slot1_action": slot1_act,
                "selected_slot0_kind": slot0_parsed["kind"],
                "selected_slot1_kind": slot1_parsed["kind"],
                "selected_slot0_id": slot0_parsed["id"],
                "selected_slot1_id": slot1_parsed["id"],
                "selected_slot0_target": slot0_parsed[
                    "target"
                ],
                "selected_slot1_target": slot1_parsed[
                    "target"
                ],
                "selected_slot0_mechanic": slot0_parsed[
                    "mechanic"
                ],
                "selected_slot1_mechanic": slot1_parsed[
                    "mechanic"
                ],
                "selected_slot0_category": rec.get(
                    "slot0_category"
                ),
                "selected_slot1_category": rec.get(
                    "slot1_category"
                ),
                "our_active_slot0": labels[
                    "our_active_slot0"
                ],
                "our_active_slot1": labels[
                    "our_active_slot1"
                ],
                "opp_active_slot0": labels[
                    "opp_active_slot0"
                ],
                "opp_active_slot1": labels[
                    "opp_active_slot1"
                ],
                "margin": margin,
                "decision_time_ms": dt,
            })
            per_battle[bt]["suspicious"] += 1

    # Convert Counters to dicts for JSON serialization.
    arm_summary["by_arm"] = dict(arm_summary["by_arm"])
    arm_summary["by_player_side"] = dict(arm_summary["by_player_side"])
    action_selection["slot0_category"] = dict(
        action_selection["slot0_category"]
    )
    action_selection["slot1_category"] = dict(
        action_selection["slot1_category"]
    )
    action_selection["slot0_mechanic"] = dict(
        action_selection["slot0_mechanic"]
    )
    action_selection["slot1_mechanic"] = dict(
        action_selection["slot1_mechanic"]
    )
    state_slices["hp_bucket_slot0"] = dict(state_slices["hp_bucket_slot0"])
    state_slices["hp_bucket_slot1"] = dict(state_slices["hp_bucket_slot1"])
    state_slices["weather"] = dict(state_slices["weather"])
    state_slices["fields"] = dict(state_slices["fields"])
    state_slices["our_species"] = dict(state_slices["our_species"])
    state_slices["opp_species"] = dict(state_slices["opp_species"])
    # Phase BEHAVIOR-2: convert new summary Counters.
    protect_summary["by_move"] = dict(protect_summary["by_move"])
    speed_control_summary["by_move"] = dict(
        speed_control_summary["by_move"]
    )
    speed_control_summary["by_category"] = dict(
        speed_control_summary["by_category"]
    )
    speed_control_summary["by_slot"] = dict(
        speed_control_summary["by_slot"]
    )
    support_targeting_summary["by_category"] = dict(
        support_targeting_summary["by_category"]
    )
    support_targeting_summary["by_move"] = dict(
        support_targeting_summary["by_move"]
    )

    return {
        "data_quality": data_quality,
        "arm_summary": arm_summary,
        "action_selection": action_selection,
        "margin_values": margin_values,
        "low_margin_turns": low_margin_turns,
        "timing": timing,
        "safety": safety,
        "state_slices": state_slices,
        "suspicious": suspicious,
        "per_battle": list(per_battle.values()),
        # Phase BEHAVIOR-2: new summaries.
        "protect_summary": protect_summary,
        "speed_control_summary": speed_control_summary,
        "speed_priority_summary": _finalize_speed_priority_summary(
            speed_priority_summary, score_diff_values
        ),
        "support_targeting_summary": support_targeting_summary,
        # Phase SPREAD-2: spread-defense summary.
        # Convert Counter to dict for JSON
        # serialization.
        "spread_defense_summary": _finalize_spread_defense_summary(
            spread_defense_summary
        ),
    }


def _finalize_spread_defense_summary(
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    """Phase SPREAD-2: convert Counters to dicts
    so the summary is JSON-serializable. Pure
    observation; no scoring change.
    """
    out = dict(summary)
    out["selected_by_move"] = dict(summary.get("selected_by_move", Counter()))
    gaps = list(summary.get(
        "score_gap_wg_legal_not_selected", []
    ))
    gaps_p = list(summary.get(
        "score_gap_wg_legal_not_selected_with_pressure", []
    ))
    out["score_gap_wg_legal_not_selected"] = gaps
    out["score_gap_wg_legal_not_selected_with_pressure"] = gaps_p
    out["score_gap_wg_legal_not_selected_count"] = len(gaps)
    out["score_gap_wg_legal_not_selected_with_pressure_count"] = (
        len(gaps_p)
    )
    if gaps:
        s = sorted(gaps)
        out["score_gap_wg_legal_not_selected_min"] = s[0]
        out["score_gap_wg_legal_not_selected_max"] = s[-1]
        out["score_gap_wg_legal_not_selected_mean"] = (
            sum(gaps) / len(gaps)
        )
        out["score_gap_wg_legal_not_selected_p25"] = (
            _percentile(gaps, 0.25)
        )
        out["score_gap_wg_legal_not_selected_median"] = (
            _percentile(gaps, 0.50)
        )
        out["score_gap_wg_legal_not_selected_p75"] = (
            _percentile(gaps, 0.75)
        )
    else:
        out["score_gap_wg_legal_not_selected_min"] = 0.0
        out["score_gap_wg_legal_not_selected_max"] = 0.0
        out["score_gap_wg_legal_not_selected_mean"] = 0.0
        out["score_gap_wg_legal_not_selected_p25"] = 0.0
        out["score_gap_wg_legal_not_selected_median"] = 0.0
        out["score_gap_wg_legal_not_selected_p75"] = 0.0
    return out


def _finalize_speed_priority_summary(
    summary: Dict[str, Any],
    score_diff_values: List[float],
) -> Dict[str, Any]:
    """Phase BEHAVIOR-9: compute score_diff distribution
    and add to the summary.
    """
    if score_diff_values:
        summary["score_diff_min"] = min(score_diff_values)
        summary["score_diff_max"] = max(score_diff_values)
        summary["score_diff_mean"] = (
            sum(score_diff_values) / len(score_diff_values)
        )
        sorted_v = sorted(score_diff_values)
        n = len(sorted_v)
        summary["score_diff_p25"] = sorted_v[max(0, int(n * 0.25) - 1)]
        summary["score_diff_median"] = sorted_v[max(0, int(n * 0.5) - 1)]
        summary["score_diff_p75"] = sorted_v[max(0, int(n * 0.75) - 1)]
    return summary


def _timing_summary(values: List[float]) -> Dict[str, float]:
    """Phase TURN-2: compute timing distribution summary."""
    if not values:
        return {
            "count": 0, "min": 0.0, "p25": 0.0,
            "median": 0.0, "p75": 0.0, "max": 0.0, "mean": 0.0,
        }
    return {
        "count": len(values),
        "min": min(values),
        "p25": _percentile(values, 0.25),
        "median": _percentile(values, 0.50),
        "p75": _percentile(values, 0.75),
        "max": max(values),
        "mean": sum(values) / len(values),
    }


def _write_markdown(
    input_paths: List[str],
    records: List[Dict[str, Any]],
    agg: Dict[str, Any],
    top_n: int,
    md_path: str,
) -> None:
    """Phase TURN-2: write the markdown report."""
    dq = agg["data_quality"]
    arm = agg["arm_summary"]
    acts = agg["action_selection"]
    safety = agg["safety"]
    state = agg["state_slices"]
    per_battle = agg["per_battle"]
    suspicious = agg["suspicious"]
    margin_values = agg["margin_values"]
    low_margin = agg["low_margin_turns"]
    timing = agg["timing"]

    lines: List[str] = []
    lines.append("# Phase TURN-2 — Turn-Level Analysis")
    lines.append("")
    lines.append("## TL;DR")
    lines.append("")
    lines.append(f"- Turn records: {len(records)}")
    lines.append(f"- Per-battle: {len(per_battle)}")
    lines.append(f"- Arms: {arm['by_arm']}")
    lines.append(
        f"- Margin values: {len(margin_values)}"
    )
    lines.append(
        f"- Low-margin turns: {len(low_margin)}"
    )
    lines.append(
        f"- Suspicious turns: {len(suspicious)}"
    )
    lines.append(
        f"- Decision time median: "
        f"{_timing_summary(timing['decision_time_ms'])['median']:.2f}ms"
    )
    lines.append("")
    lines.append("## Inputs")
    lines.append("")
    for p in input_paths:
        lines.append(f"- `{p}`")
    lines.append("")
    lines.append("## Data Quality")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    lines.append(
        f"| turn records | {dq['turns_total']} |"
    )
    lines.append(
        f"| rows missing audit_turns | "
        f"{dq['rows_missing_audit_turns']} |"
    )
    lines.append(
        f"| skipped lines | {dq['skipped_lines']} |"
    )
    lines.append("")
    lines.append("## Arm Summary")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    lines.append(
        f"| by_arm | {arm['by_arm']} |"
    )
    lines.append(
        f"| by_player_side | {arm['by_player_side']} |"
    )
    lines.append(f"| won | {arm['won']} |")
    lines.append(f"| lost | {arm['lost']} |")
    lines.append("")
    lines.append("## Action Selection")
    lines.append("")
    lines.append("### Slot 0 category")
    lines.append("")
    lines.append("| category | count |")
    lines.append("|---|---|")
    for k, v in sorted(
        acts["slot0_category"].items(),
        key=lambda x: -x[1],
    ):
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("### Slot 1 category")
    lines.append("")
    lines.append("| category | count |")
    lines.append("|---|---|")
    for k, v in sorted(
        acts["slot1_category"].items(),
        key=lambda x: -x[1],
    ):
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("### Slot 0 mechanic (V4a)")
    lines.append("")
    lines.append("| mechanic | count |")
    lines.append("|---|---|")
    for k, v in sorted(
        acts["slot0_mechanic"].items(),
        key=lambda x: -x[1],
    ):
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("### Slot 1 mechanic (V4a)")
    lines.append("")
    lines.append("| mechanic | count |")
    lines.append("|---|---|")
    for k, v in sorted(
        acts["slot1_mechanic"].items(),
        key=lambda x: -x[1],
    ):
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("## Margin / Alternatives")
    lines.append("")
    if not margin_values:
        lines.append("No margin values available.")
    else:
        ts = _timing_summary(margin_values)
        lines.append("| stat | value |")
        lines.append("|---|---|")
        for k in ["count", "min", "p25", "median", "p75", "max", "mean"]:
            lines.append(f"| {k} | {ts[k]:.2f} |")
        lines.append("")
        lines.append(
            f"Low-margin turns (margin < 10.0): {len(low_margin)}"
        )
        lines.append("")
        sorted_low = sorted(
            low_margin,
            key=lambda x: x.get("margin", 0),
        )[:top_n]
        if sorted_low:
            lines.append("| battle | turn | margin | selected |")
            lines.append("|---|---|---|---|")
            for s in sorted_low:
                sel = s.get("selected", "?")
                if isinstance(sel, list):
                    sel = str(sel)
                lines.append(
                    f"| `{s.get('battle_tag', '?')}` | "
                    f"{s.get('turn', '?')} | "
                    f"{s.get('margin', 0):.2f} | "
                    f"`{sel}` |"
                )
    lines.append("")
    lines.append("## Timing")
    lines.append("")
    for k, vs in timing.items():
        ts = _timing_summary(vs)
        lines.append(f"### {k}")
        lines.append("")
        if ts["count"] == 0:
            lines.append("No data.")
        else:
            lines.append("| stat | value (ms) |")
            lines.append("|---|---|")
            for stat in ["count", "min", "p25", "median", "p75", "max", "mean"]:
                lines.append(f"| {stat} | {ts[stat]:.2f} |")
        lines.append("")
    # Top slow turns.
    slow_turns = sorted(
        records,
        key=lambda r: r.get("decision_time_ms") or 0.0,
        reverse=True,
    )[:top_n]
    slow_with_time = [
        r for r in slow_turns if r.get("decision_time_ms") is not None
    ]
    if slow_with_time:
        lines.append("### Top slow turns")
        lines.append("")
        lines.append("| battle | arm | turn | time (ms) |")
        lines.append("|---|---|---|---|")
        for r in slow_with_time:
            lines.append(
                f"| `{r.get('battle_tag', '?')}` | "
                f"{r.get('benchmark_arm', '?')} | "
                f"{r.get('turn_number', '?')} | "
                f"{r.get('decision_time_ms', 0):.1f} |"
            )
        lines.append("")
    lines.append("## Safety and Corrections")
    lines.append("")
    lines.append("| metric | count |")
    lines.append("|---|---|")
    for k, v in safety.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")
    # Phase BEHAVIOR-2: new sections.
    lines.append("## Protect Summary")
    lines.append("")
    p = agg["protect_summary"]
    lines.append("| metric | count |")
    lines.append("|---|---|")
    lines.append(f"| slot0_protect_selected | {p['slot0_protect_selected']} |")
    lines.append(f"| slot1_protect_selected | {p['slot1_protect_selected']} |")
    lines.append(f"| any_slot_protect_selected | {p['any_slot_protect_selected']} |")
    if p["by_move"]:
        lines.append("")
        lines.append("### By move")
        lines.append("")
        lines.append("| move | count |")
        lines.append("|---|---:|")
        for mid, n in sorted(
            p["by_move"].items(), key=lambda x: -x[1]
        ):
            lines.append(f"| {mid} | {n} |")
    lines.append("")
    # Phase SPREAD-2: spread-defense summary
    # (Wide Guard / Quick Guard / Crafty Shield).
    lines.append("## Spread-Defense Summary")
    lines.append("")
    s = agg.get("spread_defense_summary", {})
    lines.append("| metric | count |")
    lines.append("|---|---|")
    for k in (
        "slot0_wide_guard_legal",
        "slot1_wide_guard_legal",
        "any_slot_wide_guard_legal",
        "slot0_quick_guard_legal",
        "slot1_quick_guard_legal",
        "any_slot_quick_guard_legal",
        "slot0_crafty_shield_legal",
        "slot1_crafty_shield_legal",
        "any_slot_crafty_shield_legal",
        "slot0_wide_guard_selected",
        "slot1_wide_guard_selected",
        "any_slot_wide_guard_selected",
        "slot0_quick_guard_selected",
        "slot1_quick_guard_selected",
        "any_slot_quick_guard_selected",
        "slot0_crafty_shield_selected",
        "slot1_crafty_shield_selected",
        "any_slot_crafty_shield_selected",
        "spread_defense_legal_not_selected",
        "opp_pressure_state_turn_count",
        "opp_used_spread_turn_count",
        "opp_used_protect_turn_count",
        "opp_used_wide_guard_turn_count",
        "opp_used_quick_guard_turn_count",
    ):
        lines.append(f"| {k} | {s.get(k, 0)} |")
    by_move = s.get("selected_by_move") or {}
    if by_move:
        lines.append("")
        lines.append("### Selected by move")
        lines.append("")
        lines.append("| move | count |")
        lines.append("|---|---:|")
        for mid, n in sorted(by_move.items(), key=lambda x: -x[1]):
            lines.append(f"| {mid} | {n} |")
    lines.append("")
    # Phase SPREAD-4: score-gap distribution
    # for Wide Guard legal-but-not-selected
    # turns. The dry-run simulator uses these
    # percentiles to pick a hypothetical
    # bonus magnitude.
    sg = s.get("score_gap_wg_legal_not_selected_count", 0)
    lines.append("### Wide Guard score-gap (selected - WG)")
    lines.append("")
    if sg == 0:
        lines.append("No Wide Guard legal-but-not-selected turns observed.")
    else:
        lines.append(f"count: {sg}")
        lines.append(
            f"count (with opp_pressure=True): "
            f"{s.get('score_gap_wg_legal_not_selected_with_pressure_count', 0)}"
        )
        lines.append("")
        lines.append("| stat | value |")
        lines.append("|---|---:|")
        lines.append(
            f"| min | {s.get('score_gap_wg_legal_not_selected_min', 0):.2f} |"
        )
        lines.append(
            f"| p25 | {s.get('score_gap_wg_legal_not_selected_p25', 0):.2f} |"
        )
        lines.append(
            f"| median | {s.get('score_gap_wg_legal_not_selected_median', 0):.2f} |"
        )
        lines.append(
            f"| mean | {s.get('score_gap_wg_legal_not_selected_mean', 0):.2f} |"
        )
        lines.append(
            f"| p75 | {s.get('score_gap_wg_legal_not_selected_p75', 0):.2f} |"
        )
        lines.append(
            f"| max | {s.get('score_gap_wg_legal_not_selected_max', 0):.2f} |"
        )
    lines.append("")
    lines.append("## Speed-Control Summary")
    lines.append("")
    s = agg["speed_control_summary"]
    lines.append("| metric | count |")
    lines.append("|---|---|")
    lines.append(f"| slot0_speed_control_selected | {s['slot0_speed_control_selected']} |")
    lines.append(f"| slot1_speed_control_selected | {s['slot1_speed_control_selected']} |")
    lines.append(f"| any_slot_speed_control_selected | {s['any_slot_speed_control_selected']} |")
    if s["by_category"]:
        lines.append("")
        lines.append("### By category")
        lines.append("")
        lines.append("| category | count |")
        lines.append("|---|---:|")
        for cat, n in sorted(
            s["by_category"].items(), key=lambda x: -x[1]
        ):
            lines.append(f"| {cat} | {n} |")
    if s["by_move"]:
        lines.append("")
        lines.append("### By move")
        lines.append("")
        lines.append("| move | count |")
        lines.append("|---|---:|")
        for mid, n in sorted(
            s["by_move"].items(), key=lambda x: -x[1]
        ):
            lines.append(f"| {mid} | {n} |")
    lines.append("")
    lines.append("## Speed-Priority Threat Summary")
    lines.append("")
    sp = agg["speed_priority_summary"]
    if not sp["fields_available"]:
        lines.append(
            f"- fields_missing_count: {sp['fields_missing_count']} "
            f"(unavailable)"
        )
    else:
        lines.append("### Threat detection")
        lines.append("")
        lines.append("| metric | count |")
        lines.append("|---|---|")
        lines.append(f"| slot0_threatened | {sp['slot0_threatened']} |")
        lines.append(f"| slot1_threatened | {sp['slot1_threatened']} |")
        lines.append(f"| any_slot_threatened | {sp['any_slot_threatened']} |")
        lines.append("")
        lines.append("### Bonus / penalty application (per-slot and per-turn counts)")
        lines.append("")
        lines.append("| field | slot0_true | slot1_true | turn_any |")
        lines.append("|---|---:|---:|---:|")
        for fld in [
            "protected_due_to_speed_priority",
            "speed_priority_protect_bonus_applied",
            "speed_priority_attack_penalty_applied",
            "speed_priority_switch_bonus_applied",
            "expected_to_faint_before_moving",
        ]:
            s0 = sp[f"{fld}_slot0_true_count"]
            s1 = sp[f"{fld}_slot1_true_count"]
            ta = sp[f"{fld}_turn_any_count"]
            lines.append(f"| {fld} | {s0} | {s1} | {ta} |")
        # Phase BEHAVIOR-9: score-diff debug.
        if sp.get("score_diff_count", 0) > 0:
            lines.append("")
            lines.append("### Score-diff debug (Protect - best non-protect move)")
            lines.append("")
            lines.append("| metric | value |")
            lines.append("|---|---:|")
            lines.append(f"| score_debug_available_count | {sp['score_debug_available_count']} |")
            lines.append(f"| score_diff_count | {sp['score_diff_count']} |")
            lines.append(f"| score_diff_min | {sp['score_diff_min']:.2f} |")
            lines.append(f"| score_diff_p25 | {sp['score_diff_p25']:.2f} |")
            lines.append(f"| score_diff_median | {sp['score_diff_median']:.2f} |")
            lines.append(f"| score_diff_p75 | {sp['score_diff_p75']:.2f} |")
            lines.append(f"| score_diff_max | {sp['score_diff_max']:.2f} |")
            lines.append(f"| score_diff_mean | {sp['score_diff_mean']:.2f} |")
            lines.append(f"| expected_faint + negative_diff | {sp['expected_faint_with_negative_diff_count']} |")
            lines.append(f"| expected_faint + positive_diff | {sp['expected_faint_with_positive_diff_count']} |")
            lines.append(f"| protect_bonus + negative_diff | {sp['protect_bonus_with_negative_diff_count']} |")
    lines.append("")
    lines.append("## Support-Targeting Summary")
    lines.append("")
    st = agg["support_targeting_summary"]
    lines.append("| metric | count |")
    lines.append("|---|---|")
    lines.append(f"| slot0_support_selected | {st['slot0_support_selected']} |")
    lines.append(f"| slot1_support_selected | {st['slot1_support_selected']} |")
    lines.append(f"| any_slot_support_selected | {st['any_slot_support_selected']} |")
    lines.append(f"| wrong_side_selected | {st['wrong_side_selected']} |")
    lines.append(f"| narrow_ally_heal_blocked | {st['narrow_ally_heal_blocked']} |")
    lines.append(f"| wrong_side_field_available | {st['wrong_side_field_available']} |")
    if st["by_category"]:
        lines.append("")
        lines.append("### By category")
        lines.append("")
        lines.append("| category | count |")
        lines.append("|---|---:|")
        for cat, n in sorted(
            st["by_category"].items(), key=lambda x: -x[1]
        ):
            lines.append(f"| {cat} | {n} |")
    if st["by_move"]:
        lines.append("")
        lines.append("### By move")
        lines.append("")
        lines.append("| move | count |")
        lines.append("|---|---:|")
        for mid, n in sorted(
            st["by_move"].items(), key=lambda x: -x[1]
        ):
            lines.append(f"| {mid} | {n} |")
    lines.append("")
    lines.append("## State Slices")
    lines.append("")
    lines.append("### HP buckets (slot 0)")
    lines.append("")
    lines.append("| bucket | count |")
    lines.append("|---|---|")
    for k, v in sorted(state["hp_bucket_slot0"].items()):
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("### HP buckets (slot 1)")
    lines.append("")
    lines.append("| bucket | count |")
    lines.append("|---|---|")
    for k, v in sorted(state["hp_bucket_slot1"].items()):
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("### Weather")
    lines.append("")
    lines.append("| weather | count |")
    lines.append("|---|---|")
    for k, v in sorted(state["weather"].items()):
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("### Fields (top 10)")
    lines.append("")
    lines.append("| fields | count |")
    lines.append("|---|---|")
    sorted_fields = sorted(
        state["fields"].items(),
        key=lambda x: -x[1],
    )[:10]
    for k, v in sorted_fields:
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("### Our species (top 10)")
    lines.append("")
    lines.append("| species | count |")
    lines.append("|---|---|")
    sorted_ours = sorted(
        state["our_species"].items(),
        key=lambda x: -x[1],
    )[:10]
    for k, v in sorted_ours:
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("### Opp species (top 10)")
    lines.append("")
    lines.append("| species | count |")
    lines.append("|---|---|")
    sorted_opps = sorted(
        state["opp_species"].items(),
        key=lambda x: -x[1],
    )[:10]
    for k, v in sorted_opps:
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("## Top Suspicious Turns")
    lines.append("")
    sorted_susp = sorted(
        suspicious,
        key=lambda s: len(s.get("reasons", [])),
        reverse=True,
    )[:top_n]
    if not sorted_susp:
        lines.append("No suspicious turns found.")
    else:
        # Phase ANALYZER-2: attribution columns. Readers
        # can now see our_active / opp_active / per-slot
        # selected action breakdown at a glance, so
        # mirror-match species (e.g. our bench Sneasler
        # vs opp active Sneasler) are no longer confused.
        lines.append(
            "| battle | arm | turn | our_s0 | opp_s0 | "
            "sel0_kind | sel0_id | sel0_tgt | "
            "our_s1 | opp_s1 | "
            "sel1_kind | sel1_id | sel1_tgt | "
            "reasons | margin |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for s in sorted_susp:
            lines.append(
                f"| `{s.get('battle_tag', '?')}` | "
                f"{s.get('arm', '?')} | "
                f"{s.get('turn', '?')} | "
                f"`{s.get('our_active_slot0', '-')}` | "
                f"`{s.get('opp_active_slot0', '-')}` | "
                f"{s.get('selected_slot0_kind', '-')} | "
                f"`{s.get('selected_slot0_id', '-')}` | "
                f"`{s.get('selected_slot0_target', '-')}` | "
                f"`{s.get('our_active_slot1', '-')}` | "
                f"`{s.get('opp_active_slot1', '-')}` | "
                f"{s.get('selected_slot1_kind', '-')} | "
                f"`{s.get('selected_slot1_id', '-')}` | "
                f"`{s.get('selected_slot1_target', '-')}` | "
                f"{','.join(s.get('reasons', []))} | "
                f"{s.get('margin', '')} |"
            )
    lines.append("")
    lines.append("## Per-Battle Summary")
    lines.append("")
    if not per_battle:
        lines.append("No battles.")
    else:
        lines.append("| battle | arm | won | turns | suspicious |")
        lines.append("|---|---|---|---|---|")
        for b in per_battle[:30]:
            lines.append(
                f"| `{b.get('battle_tag', '?')}` | "
                f"{b.get('arm', '?')} | "
                f"{b.get('won')} | "
                f"{b.get('turns', 0)} | "
                f"{b.get('suspicious', 0)} |"
            )
        if len(per_battle) > 30:
            lines.append(
                f"\n(showing first 30 of {len(per_battle)} battles)"
            )
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "- This analyzer is read-only. It does not change "
        "production code, scoring, or audit fields."
    )
    lines.append(
        "- It only sees what the audit JSONL records. Missing "
        "fields are handled safely but produce no data."
    )
    lines.append(
        "- Ability block avoidance rate is not computed at the "
        "turn level (fields may be in logger signature but not "
        "persisted)."
    )
    lines.append(
        "- Suspicious turns are heuristic, not ground truth. "
        "Manual review is needed for actionable insights."
    )
    lines.append("")
    lines.append("## Recommendations")
    lines.append("")
    if suspicious:
        lines.append(
            f"- {len(suspicious)} suspicious turns found. "
            "Review the top suspicious turns table for patterns."
        )
    if low_margin:
        lines.append(
            f"- {len(low_margin)} low-margin turns found. "
            "These are decisions where the bot's choice was "
            "close to an alternative."
        )
    if safety.get("overkill_penalty_triggered", 0) > 0:
        lines.append(
            f"- {safety['overkill_penalty_triggered']} overkill "
            "penalty triggers. Consider whether the penalty is "
            "too aggressive or too lenient."
        )
    if not suspicious and not low_margin:
        lines.append(
            "- No suspicious patterns found. Decision behavior "
            "appears healthy. No immediate action needed."
        )
    lines.append("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))


def _write_json(
    records: List[Dict[str, Any]],
    agg: Dict[str, Any],
    top_n: int,
    json_path: str,
) -> None:
    """Phase TURN-2: write the JSON summary."""
    timing_summary = {
        k: _timing_summary(v) for k, v in agg["timing"].items()
    }
    margin_ts = _timing_summary(agg["margin_values"])
    sorted_susp = sorted(
        agg["suspicious"],
        key=lambda s: len(s.get("reasons", [])),
        reverse=True,
    )[:top_n]
    slow_turns = sorted(
        records,
        key=lambda r: r.get("decision_time_ms") or 0.0,
        reverse=True,
    )[:top_n]
    out = {
        "inputs": {
            "turn_records": len(records),
            "per_battle": len(agg["per_battle"]),
        },
        "data_quality": agg["data_quality"],
        "arm_summary": agg["arm_summary"],
        "action_selection": agg["action_selection"],
        "margin_summary": {
            "distribution": margin_ts,
            "low_margin_count": len(agg["low_margin_turns"]),
            "low_margin_turns": agg["low_margin_turns"][:top_n],
        },
        "timing_summary": timing_summary,
        "safety_summary": agg["safety"],
        "state_slices": agg["state_slices"],
        "top_suspicious_turns": sorted_susp,
        "top_slow_turns": [
            {
                "battle_tag": r.get("battle_tag"),
                "arm": r.get("benchmark_arm"),
                "turn": r.get("turn_number"),
                "decision_time_ms": r.get("decision_time_ms"),
            }
            for r in slow_turns
        ],
        "per_battle": agg["per_battle"],
        # Phase BEHAVIOR-2: new summaries.
        "protect_summary": agg["protect_summary"],
        "speed_control_summary": agg["speed_control_summary"],
        "speed_priority_summary": agg["speed_priority_summary"],
        "support_targeting_summary": agg["support_targeting_summary"],
    }
    with open(json_path, "w") as f:
        json.dump(out, f, indent=2, default=str)


def main():
    parser = argparse.ArgumentParser(
        description="Phase TURN-2 — Read-only turn-level "
                    "analyzer"
    )
    parser.add_argument(
        "--audit-jsonl", action="append", required=True,
        help="Path to audit JSONL. Can be passed multiple "
             "times. (required)"
    )
    parser.add_argument(
        "--md", required=True,
        help="Output markdown report path. (required)"
    )
    parser.add_argument(
        "--json", default=None,
        help="Output JSON summary path. (optional)"
    )
    parser.add_argument(
        "--top-n", type=int, default=30,
        help="Top N suspicious turns to include. Default 30."
    )
    args = parser.parse_args()

    all_records: List[Dict[str, Any]] = []
    total_skipped = 0
    total_rows = 0
    rows_missing_audit_turns = 0
    turns_missing_state = 0
    for path in args.audit_jsonl:
        rows, skipped = _load_audit(path)
        total_skipped += skipped
        for ri, row in enumerate(rows):
            total_rows += 1
            turns_list = row.get("audit_turns", []) or []
            if not turns_list:
                rows_missing_audit_turns += 1
            recs = _extract_turn_record(row, ri, path)
            for r in recs:
                if not r.get("state_snapshot"):
                    turns_missing_state += 1
            all_records.extend(recs)

    if not all_records:
        print("No turn records found.", file=sys.stderr)
        sys.exit(1)

    # Update data quality.
    agg = _aggregate(all_records)
    agg["data_quality"]["rows_total"] = total_rows
    agg["data_quality"]["skipped_lines"] = total_skipped
    agg["data_quality"]["rows_missing_audit_turns"] = (
        rows_missing_audit_turns
    )
    agg["data_quality"]["turns_missing_state_snapshot"] = (
        turns_missing_state
    )

    _write_markdown(
        args.audit_jsonl,
        all_records,
        agg,
        args.top_n,
        args.md,
    )
    print(f"Wrote markdown report: {args.md}")

    if args.json:
        _write_json(all_records, agg, args.top_n, args.json)
        print(f"Wrote JSON summary: {args.json}")


if __name__ == "__main__":
    main()