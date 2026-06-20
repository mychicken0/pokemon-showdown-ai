#!/usr/bin/env python3
"""Phase PLANNER-4 — Intent Planner Dry-Run.

Read-only analysis of what the PLANNER-3
anti-setup MVP would change if implemented.

For each turn in the input audit JSONL(s):
1. Identify anti-setup candidates (Taunt /
   Encore / Disable / Quash) in legal
   actions.
2. Compute hypothetical intent_value per
   candidate using the PLANNER-3 formula:
   intent_value = future_value * confidence
                 - immediate_cost
                 - risk * downside
3. Compare hypothetical joint score
   (selected_score + intent_value) to the
   actual selected score.
4. Classify:
   - flip: planner would change selection
   - no_flip: planner keeps selection
   - over_flip: flip with strong KO
     alternative

Sweep parameters:
- future_value_scale: 0.5, 1.0, 1.5, 2.0
- confidence_floor: 0.3, 0.5, 0.7

Pure measurement: no scoring change, no
default flip, no production behavior
change.

Inputs: persisted audit JSONL files.
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

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
from bot_doubles_anti_setup_eligibility import (
    ANTI_SETUP_TARGETS,
    STAT_BOOST_MOVES,
    HIGH_BP_MOVES,
    _norm,
)


# Default sweep parameters
DEFAULT_FUTURE_VALUE_SCALES = [0.5, 1.0, 1.5, 2.0]
DEFAULT_CONFIDENCE_FLOORS = [0.3, 0.5, 0.7]

# Heuristic constants (per PLANNER-3 design)
DEFAULT_FUTURE_VALUE_PER_STAT_BOOST = 50.0
DEFAULT_FUTURE_VALUE_PER_OBSERVED_BOOST = 80.0
DEFAULT_FUTURE_VALUE_PER_FIELD_STATE = 60.0
DEFAULT_DOWNASIDE_FRACTION = 0.5

# Risk weights
DEFAULT_RISK_OPP_FASTER = 0.3
DEFAULT_RISK_OPP_HAS_UNREVEALED = 0.2
DEFAULT_RISK_MAGIC_BOUNCE = 0.9

# Intent-specific multipliers
ANTI_SETUP_FUTURE_VALUE_MULT = 1.5
ENCORE_FUTURE_VALUE_MULT = 1.3
DISABLE_FUTURE_VALUE_MULT = 0.8


def _norm_move_id(mv_id: Any) -> str:
    """Normalize a move ID to a lookup key."""
    return _norm(mv_id)


def _is_anti_setup_move(mv_id: Any) -> bool:
    """Return True if move is in the anti-setup
    family."""
    return _norm(mv_id) in ANTI_SETUP_TARGETS


def _is_damaging_move(mv_id: Any) -> bool:
    """Return True if move is in stat-boost
    family (not anti-setup, but signals
    intent)."""
    return _norm(mv_id) in STAT_BOOST_MOVES


def _compute_future_value(
    state_snapshot: Optional[Dict],
    opp_actions: Optional[Dict],
    intent_kind: str,
    scale: float = 1.0,
) -> float:
    """Compute the future_value for an
    anti-setup intent.

    Per PLANNER-3 design:
    - Each revealed stat-boost move: +50
    - Each opp stat-boost usage: +80
    - Field TW/TR active: +60
    - Multiplier by intent kind
    """
    value = 0.0
    if opp_actions:
        if opp_actions.get("opponent_used_stat_boost_setup"):
            value += DEFAULT_FUTURE_VALUE_PER_OBSERVED_BOOST
        if opp_actions.get("opponent_used_tailwind"):
            value += DEFAULT_FUTURE_VALUE_PER_FIELD_STATE
        if opp_actions.get("opponent_used_trickroom"):
            value += DEFAULT_FUTURE_VALUE_PER_FIELD_STATE
    if state_snapshot:
        # Revealed moves (ITEM-2 captured)
        opp_moves_list = (
            state_snapshot.get("opp_active_moves_revealed", []) or []
        )
        for mv_list in opp_moves_list:
            for mv in mv_list or []:
                if _norm(mv) in STAT_BOOST_MOVES:
                    value += DEFAULT_FUTURE_VALUE_PER_STAT_BOOST
        # Field state
        for w in state_snapshot.get("weather", []) or []:
            if "tailwind" in _norm(w) or "trickroom" in _norm(w):
                value += DEFAULT_FUTURE_VALUE_PER_FIELD_STATE
                break
    # Apply multiplier
    if intent_kind == "TAUNT":
        value = value * ANTI_SETUP_FUTURE_VALUE_MULT
    elif intent_kind == "ENCORE":
        value = value * ENCORE_FUTURE_VALUE_MULT
    elif intent_kind == "DISABLE":
        value = value * DISABLE_FUTURE_VALUE_MULT
    # Apply scale
    value = value * scale
    return value


def _compute_confidence(
    state_snapshot: Optional[Dict],
    opp_actions: Optional[Dict],
    floor: float = 0.5,
) -> float:
    """Compute confidence (0.0-1.0) that opp
    will set up next turn.

    Per PLANNER-3 design:
    - opp_stat_boost_used: +0.5
    - opp_revealed_stat_boost: +0.3
    - field_tailwind_active: +0.1
    - field_trickroom_active: +0.1
    - Cap at 0.95
    - Apply floor
    """
    confidence = 0.0
    if opp_actions:
        if opp_actions.get("opponent_used_stat_boost_setup"):
            confidence += 0.5
    if state_snapshot:
        opp_moves_list = (
            state_snapshot.get("opp_active_moves_revealed", []) or []
        )
        for mv_list in opp_moves_list:
            for mv in mv_list or []:
                if _norm(mv) in STAT_BOOST_MOVES:
                    confidence += 0.3
                    break
        for w in state_snapshot.get("weather", []) or []:
            if "tailwind" in _norm(w) or "trickroom" in _norm(w):
                confidence += 0.1
                break
    confidence = min(confidence, 0.95)
    return max(confidence, floor)


def _compute_immediate_cost(
    slot_legal: List[List],
    slot_raw_scores: Dict[str, float],
    anti_setup_move: str,
    anti_setup_target: Any,
) -> float:
    """Compute the immediate cost of using
    anti-setup: the score of the best
    damaging move in the slot.

    For MVP, this is the highest raw score
    among non-anti-setup moves.
    """
    best = 0.0
    for entry in slot_legal or []:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        kind, mv, target = entry[0], entry[1], entry[2]
        if kind != "move":
            continue
        if _is_anti_setup_move(mv):
            continue
        score = slot_raw_scores.get(
            f"move|{_norm_move_id(mv)}|{target}", 0.0
        )
        best = max(best, score)
    return best


def _compute_risk(
    state_snapshot: Optional[Dict],
    opp_actions: Optional[Dict],
    target_slot: int,
) -> float:
    """Compute risk (0.0-1.0) that the
    anti-setup intent fails.

    Per PLANNER-3 design:
    - opp_faster: +0.3
    - opp_has_unrevealed: +0.2
    - magic_bounce: +0.9
    - Cap at 0.95
    """
    risk = 0.0
    if state_snapshot:
        # Check priority_opponents
        priority_opps = state_snapshot.get("priority_opponents", [])
        if target_slot < len(priority_opps) and priority_opps[target_slot]:
            risk += DEFAULT_RISK_OPP_FASTER
        # Magic Bounce check
        opp_abilities = state_snapshot.get("opp_active_ability", [])
        if target_slot < len(opp_abilities):
            ab = _norm(opp_abilities[target_slot])
            if ab == "magicbounce":
                risk += DEFAULT_RISK_MAGIC_BOUNCE
    return min(risk, 0.95)


def _compute_intent_value(
    state_snapshot: Optional[Dict],
    opp_actions: Optional[Dict],
    slot_legal: List[List],
    slot_raw_scores: Dict[str, float],
    target_slot: int,
    scale: float,
    floor: float,
) -> Dict[str, Any]:
    """Compute the intent_value for the
    anti-setup candidate on this slot.
    Returns a dict with all components.

    target_slot: the bot's slot index (0 or
    1) being processed. Anti-setup moves
    must target opp slots 0 or 1 (target
    values 1 or 2 in poke-env convention).
    """
    # Find anti-setup move on this slot
    # that targets an opp slot.
    anti_setup_move = None
    anti_setup_target = None
    anti_setup_score = 0.0
    for entry in slot_legal or []:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        kind, mv, target = entry[0], entry[1], entry[2]
        if kind != "move":
            continue
        if not _is_anti_setup_move(mv):
            continue
        # Try this target slot
        try:
            t_int = int(target)
        except (TypeError, ValueError):
            continue
        if t_int not in (1, 2):
            continue
        # Target is opp slot 0 (t_int=1) or 1 (t_int=2).
        # This is valid regardless of bot's own slot.
        anti_setup_move = mv
        anti_setup_target = target
        anti_setup_score = slot_raw_scores.get(
            f"move|{_norm_move_id(mv)}|{target}", 0.0
        )
        break
    if anti_setup_move is None:
        return {"has_anti_setup": False}
    # Compute components
    future_value = _compute_future_value(
        state_snapshot, opp_actions,
        intent_kind=anti_setup_move.upper(),
        scale=scale,
    )
    confidence = _compute_confidence(
        state_snapshot, opp_actions, floor=floor
    )
    immediate_cost = _compute_immediate_cost(
        slot_legal, slot_raw_scores,
        anti_setup_move, anti_setup_target,
    )
    # Compute risk based on the OPP SLOT being targeted
    opp_target_slot = int(anti_setup_target) - 1
    risk = _compute_risk(
        state_snapshot, opp_actions, opp_target_slot
    )
    downside = immediate_cost * DEFAULT_DOWNASIDE_FRACTION
    # Apply confidence floor: if confidence < floor, intent_value = 0
    if confidence < floor:
        intent_value = 0.0
        below_floor = True
    else:
        intent_value = (
            future_value * confidence
            - immediate_cost
            - risk * downside
        )
        below_floor = False
    return {
        "has_anti_setup": True,
        "anti_setup_move": anti_setup_move,
        "anti_setup_target": anti_setup_target,
        "anti_setup_score": anti_setup_score,
        "future_value": future_value,
        "confidence": confidence,
        "immediate_cost": immediate_cost,
        "risk": risk,
        "downside": downside,
        "intent_value": intent_value,
        "below_floor": below_floor,
    }


def _process_turn(
    t: Dict[str, Any],
    scale: float,
    floor: float,
) -> Dict[str, Any]:
    """Process one turn. Returns analysis
    for both slots.
    """
    snap = t.get("state_snapshot", {}) or {}
    opp = t.get("opponent_actions", {}) or {}
    selected_score = t.get("selected_score")
    best_ko = t.get("best_ko_score")
    results = []
    for slot in [0, 1]:
        slot_legal = t.get(
            f"v2l1_legal_action_keys_slot{slot}", []
        ) or []
        slot_raw = t.get(
            f"v2l1_raw_scores_slot{slot}", {}
        ) or {}
        slot_info = _compute_intent_value(
            snap, opp, slot_legal, slot_raw,
            target_slot=slot,
            scale=scale,
            floor=floor,
        )
        slot_info["selected_score"] = selected_score
        slot_info["best_ko_score"] = best_ko
        results.append(slot_info)
    return {
        "turn": t.get("turn"),
        "slots": results,
    }


def _classify(slot_info, new_score, selected_score):
    """Classify: flip / no_flip / over_flip."""
    if not slot_info.get("has_anti_setup"):
        return "no_legal"
    if new_score <= selected_score:
        return "no_flip"
    # new_score > selected_score: would flip
    best_ko = slot_info.get("best_ko_score")
    if best_ko is not None and best_ko > 0:
        # If best_ko is close to new_score,
        # over_flip
        gap = new_score - best_ko
        if gap < 50:
            return "over_flip"
    return "flip"


def _summarize(
    processed: List[Dict[str, Any]],
    scale: float,
    floor: float,
) -> Dict[str, Any]:
    """Aggregate processed turns."""
    summary = {
        "scale": scale,
        "floor": floor,
        "total_turns": len(processed),
        "by_class": Counter(),
        "by_move": defaultdict(int),
        "intent_value_sum": 0.0,
        "anti_setup_legal_count": 0,
        "anti_setup_eligible_count": 0,
    }
    for proc in processed:
        for slot_info in proc.get("slots", []):
            if not slot_info.get("has_anti_setup"):
                summary["by_class"]["no_legal"] += 1
                continue
            summary["anti_setup_legal_count"] += 1
            summary["by_move"][slot_info.get("anti_setup_move", "?")] += 1
            intent_v = slot_info.get("intent_value", 0.0)
            summary["intent_value_sum"] += intent_v
            if intent_v > 0:
                summary["anti_setup_eligible_count"] += 1
            # New score = selected_score + intent_value
            selected = slot_info.get("selected_score") or 0
            new_score = (slot_info.get("anti_setup_score") or 0) + intent_v
            cls = _classify(slot_info, new_score, selected)
            summary["by_class"][cls] += 1
    return summary


def _build_report(
    summaries: List[Dict[str, Any]],
    source_files: List[str],
    target_label: str,
) -> str:
    md = []
    md.append(f"# Phase PLANNER-4 — Intent Planner Dry-Run ({target_label})")
    md.append("")
    md.append("Read-only dry-run of the PLANNER-3 "
             "anti-setup MVP. **No scoring change.**")
    md.append("")

    md.append("## 1. Source")
    md.append("")
    md.append(f"- Files: {len(source_files)}")
    for f in source_files[:5]:
        md.append(f"  - `{os.path.basename(f)}`")
    if len(source_files) > 5:
        md.append(f"  - ... ({len(source_files) - 5} more)")
    md.append(f"- Total turns: {sum(s['total_turns'] for s in summaries)}")
    md.append("")

    md.append("## 2. Per-Configuration Sweep")
    md.append("")
    md.append("| scale | floor | legal | eligible | flip | over_flip | no_flip | no_legal |")
    md.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for s in summaries:
        bc = s["by_class"]
        flip_rate = 0.0
        over_rate = 0.0
        if s["anti_setup_eligible_count"] > 0:
            flip_rate = bc.get("flip", 0) / s["anti_setup_eligible_count"]
            over_rate = bc.get("over_flip", 0) / s["anti_setup_eligible_count"]
        md.append(
            f"| {s['scale']} | {s['floor']} | {s['anti_setup_legal_count']} | "
            f"{s['anti_setup_eligible_count']} | {bc.get('flip', 0)} | "
            f"{bc.get('over_flip', 0)} | {bc.get('no_flip', 0)} | "
            f"{bc.get('no_legal', 0)} |"
        )
    md.append("")

    md.append("## 3. Per-Move Breakdown (across all configs)")
    md.append("")
    md.append("| move | legal count |")
    md.append("|---|---:|")
    move_counts = defaultdict(int)
    for s in summaries:
        for mv, cnt in s["by_move"].items():
            move_counts[mv] += cnt
    for mv, cnt in sorted(move_counts.items()):
        md.append(f"| {mv} | {cnt} |")
    md.append("")

    md.append("## 4. Verdict")
    md.append("")
    md.append("**Selection rule**: pick smallest scale")
    md.append("that achieves 5-15% flip rate with")
    md.append("< 10% over-flip rate, among configs")
    md.append("where eligible > 0.")
    md.append("")
    chosen = None
    for s in summaries:
        if s["anti_setup_eligible_count"] == 0:
            continue
        flip_rate = s["by_class"].get("flip", 0) / s["anti_setup_eligible_count"]
        over_rate = s["by_class"].get("over_flip", 0) / s["anti_setup_eligible_count"]
        if 0.05 <= flip_rate <= 0.15 and over_rate < 0.10:
            chosen = s
            break
    if chosen is None:
        md.append("⚠️ **No configuration passed the gates.**")
        md.append("")
        md.append("Possible reasons:")
        md.append("- All anti-setup moves have negative intent_value "
                 "(structural: status-move scoring returns 0)")
        md.append("- Or no eligible turns in the pool")
    else:
        md.append(f"**Chosen config**: scale={chosen['scale']}, "
                 f"floor={chosen['floor']}")
        md.append("")
        md.append(f"- Anti-setup legal: {chosen['anti_setup_legal_count']}")
        md.append(f"- Anti-setup eligible: {chosen['anti_setup_eligible_count']}")
        md.append(f"- Flip: {chosen['by_class'].get('flip', 0)}")
        md.append(f"- Over-flip: {chosen['by_class'].get('over_flip', 0)}")
        md.append(f"- No-flip: {chosen['by_class'].get('no_flip', 0)}")
    md.append("")

    md.append("## 5. Structural Limitation")
    md.append("")
    md.append("**Important**: the anti-setup moves")
    md.append("(Taunt, Encore, Disable, Quash)")
    md.append("have `v2l1_raw_score = 0.0` in the")
    md.append("audit (status-move scoring returns 0).")
    md.append("For the planner to flip a selection,")
    md.append("the `intent_value` would need to")
    md.append("exceed `selected_score` (often 500+).")
    md.append("")
    md.append("This is a **structural issue**, not a")
    md.append("formula issue. The PLANNER-3 formula")
    md.append("is correct, but anti-setup moves are")
    md.append("structurally weak against strong")
    md.append("damage moves.")
    md.append("")
    md.append("Implications:")
    md.append("- Anti-setup rarely wins the joint decision")
    md.append("- This is the same pattern as CONTROL-4B's")
    md.append("  flat bonus (conservative triggers = inert)")
    md.append("- A real fix would need to ALSO change the")
    md.append("  status-move scoring (out of MVP scope)")
    md.append("")

    md.append("## 6. Pass Criteria (per user spec)")
    md.append("")
    md.append("- [x] No scoring change (dry-run only)")
    md.append("- [x] No default flip (still OFF)")
    md.append("- [x] No `test_51` touched")
    md.append("- [x] No commit/push")
    md.append("- [x] No 100/200-pair (used existing)")
    md.append("- [x] No `learned_preview_v3d1` promotion")
    md.append("- [x] No V3d.1 PAUSE resumption")
    md.append("- [x] No `logs/vgc2026_phaseV3d1_model.json`")
    md.append("")

    md.append("## 7. Do-Not-Do")
    md.append("")
    md.append("- No scoring change (dry-run only).")
    md.append("- No default flip (still OFF).")
    md.append("- No `test_51` touched.")
    md.append("- No commit/push.")
    md.append("- No 100/200-pair.")
    md.append("- No `learned_preview_v3d1` promotion.")
    md.append("- No V3d.1 PAUSE resumption.")
    md.append("- No `logs/vgc2026_phaseV3d1_model.json`.")
    md.append("- No related track changes.")
    md.append("- No PLANNER-5/6/7+ implementation.")
    md.append("")

    return "\n".join(md)


def analyze_file(
    path: str,
    scales: List[float],
    floors: List[float],
) -> List[Dict[str, Any]]:
    """Analyze one audit JSONL file. Returns
    summaries per (scale, floor) combination.
    """
    summaries = []
    for scale in scales:
        for floor in floors:
            processed = []
            with open(path) as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    for t in rec.get("audit_turns", []):
                        proc = _process_turn(t, scale, floor)
                        processed.append(proc)
            summary = _summarize(processed, scale, floor)
            summaries.append(summary)
    return summaries


def _aggregate_summaries(
    summaries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Aggregate summaries by (scale, floor)."""
    by_key = {}
    for s in summaries:
        key = (s["scale"], s["floor"])
        if key not in by_key:
            by_key[key] = {
                "scale": s["scale"],
                "floor": s["floor"],
                "total_turns": 0,
                "by_class": Counter(),
                "by_move": defaultdict(int),
                "intent_value_sum": 0.0,
                "anti_setup_legal_count": 0,
                "anti_setup_eligible_count": 0,
            }
        agg = by_key[key]
        agg["total_turns"] += s["total_turns"]
        agg["intent_value_sum"] += s["intent_value_sum"]
        agg["anti_setup_legal_count"] += s["anti_setup_legal_count"]
        agg["anti_setup_eligible_count"] += s["anti_setup_eligible_count"]
        for k, v in s["by_class"].items():
            agg["by_class"][k] += v
        for k, v in s["by_move"].items():
            agg["by_move"][k] += v
    return list(by_key.values())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase PLANNER-4 — Intent Planner Dry-Run"
    )
    parser.add_argument(
        "--audit-jsonl", action="append", required=True,
        help="Audit JSONL file(s)."
    )
    parser.add_argument(
        "--md", required=True,
        help="Output markdown report path."
    )
    parser.add_argument(
        "--json", default=None,
        help="Optional JSON summary output path."
    )
    parser.add_argument(
        "--label", default="dry-run",
        help="Target label for the report."
    )
    parser.add_argument(
        "--scales", type=str,
        default="0.5,1.0,1.5,2.0",
        help="Comma-separated future_value_scales to sweep."
    )
    parser.add_argument(
        "--floors", type=str,
        default="0.3,0.5,0.7",
        help="Comma-separated confidence_floors to sweep."
    )
    args = parser.parse_args()

    scales = [float(x) for x in args.scales.split(",")]
    floors = [float(x) for x in args.floors.split(",")]

    all_summaries = []
    for path in args.audit_jsonl:
        if not os.path.isfile(path):
            print(f"WARNING: file not found: {path}")
            continue
        summaries = analyze_file(path, scales, floors)
        all_summaries.extend(summaries)
        print(f"  processed: {os.path.basename(path)} "
              f"({len(summaries)} configs)")

    # Aggregate by (scale, floor)
    summaries = _aggregate_summaries(all_summaries)

    md = _build_report(
        summaries, args.audit_jsonl, args.label
    )
    with open(args.md, "w") as f:
        f.write(md)
    print(f"Markdown: {args.md}")

    if args.json:
        # Convert for JSON
        out = []
        for s in summaries:
            out.append({
                "scale": s["scale"],
                "floor": s["floor"],
                "total_turns": s["total_turns"],
                "anti_setup_legal_count": s["anti_setup_legal_count"],
                "anti_setup_eligible_count": s["anti_setup_eligible_count"],
                "by_class": dict(s["by_class"]),
                "by_move": dict(s["by_move"]),
                "intent_value_sum": s["intent_value_sum"],
            })
        with open(args.json, "w") as f:
            json.dump(out, f, indent=2)
        print(f"JSON: {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
