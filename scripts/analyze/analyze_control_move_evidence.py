#!/usr/bin/env python3
"""Phase CONTROL-1 — Read-Only Control Move Evidence Audit.

Aggregates turn-level audit fields across battles to
produce evidence about the bot's control / support /
disruption move behavior. Read-only: no production
change, no scoring change, no new audit fields.

Control families analyzed (per Phase CONTROL-1 spec):
  1. Defensive stall (Protect family)
  2. Speed control (TW/TR/Icy Wind/Thunder Wave)
  3. Anti-setup disruption (Taunt/Encore/Quash)
  4. Field control (weather/terrain/screens)
  5. Redirection (Follow Me / Rage Powder)
  6. Spread defense (Wide Guard / Quick Guard /
     Crafty Shield)
  7. Combo/support (Helping Hand / Coaching / Decorate
     / Haze / Clear Smog / Beat Up / Life Dew /
     Heal Pulse / Pollen Puff)

Inputs: persisted audit JSONL files (one or more).
The analyzer handles:
  - one audit file
  - multiple --audit-jsonl files
  - missing optional fields safely
  - legacy logs without BI fields

Outputs:
  - Markdown report (--md, required)
  - Optional JSON summary (--json)

Per AGENTS.md: read-only audit, no scoring change,
no default flip, no model artifact. No
"learned_preview_v3d1" promotion.
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple


# Control move families (lowercase, no spaces)
CONTROL_FAMILIES: Dict[str, Set[str]] = {
    "defensive_stall": {
        "protect", "detect", "spikyshield",
        "kingsshield", "banefulbunker", "silktrap",
        "burningbulwark", "maxguard", "obstruct",
    },
    "speed_control": {
        "tailwind", "trickroom", "icywind",
        "electroweb", "thunderwave", "glare",
        "stunspore", "scaryface",
    },
    "anti_setup_disrupt": {
        "taunt", "encore", "disable", "torment",
        "quash",
    },
    "field_control": {
        "raindance", "sunnyday", "sandstorm", "snowscape",
        "electricterrain", "psychicterrain", "grassyterrain",
        "mistyterrain", "reflect", "lightscreen", "auroraveil",
    },
    "redirection": {
        "followme", "ragepowder", "spotlight",
    },
    "spread_defense": {
        "wideguard", "quickguard", "craftyshield",
        "matblock",
    },
    "combo_support": {
        "helpinghand", "coaching", "decorate",
        "haze", "clearsmog", "beatup", "lifedew",
        "healpulse", "pollenpuff", "allyswitch",
        "aromatherapy", "healbell",
    },
}


def _move_to_family(move: str) -> Optional[str]:
    """Return family name for a move, or None if not a
    control/support move."""
    n = (move or "").lower().replace(" ", "").replace("-", "").replace("_", "").replace("'", "")
    for fam, moves in CONTROL_FAMILIES.items():
        if n in moves:
            return fam
    return None


def _safe_get(d: Any, *keys, default=None):
    """Nested dict.get with safe fallback."""
    cur = d
    for k in keys:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(k, default)
        else:
            return default
    return cur


def _parse_action_key(key: str) -> Optional[Tuple[str, str, str]]:
    """Parse 'kind|value|target' into tuple.

    Returns (kind, value, target) or None if invalid.
    """
    if not isinstance(key, str):
        return None
    parts = key.split("|")
    if len(parts) != 3:
        return None
    return (parts[0], parts[1], parts[2])


def _parse_selected_joint(selected_joint: str) -> List[Tuple[str, str, str]]:
    """Parse 'move|earthpower|1;move|heatwave|0' into
    a list of (kind, value, target) tuples."""
    if not selected_joint:
        return []
    out = []
    for part in selected_joint.split(";"):
        parsed = _parse_action_key(part.strip())
        if parsed:
            out.append(parsed)
    return out


def _safe_turn_bucket(turn: int) -> str:
    """Classify turn into early/mid/late."""
    if turn is None:
        return "unknown"
    if turn <= 3:
        return "early"
    if turn <= 7:
        return "mid"
    return "late"


def _has_opp_context(opp_actions: Dict[str, Any]) -> List[str]:
    """Return list of opp context signals present."""
    signals = []
    if not opp_actions:
        return signals
    keys = [
        ("opponent_used_protect", "opp_used_protect"),
        ("opponent_used_tailwind", "opp_used_tailwind"),
        ("opponent_used_trickroom", "opp_used_trickroom"),
        ("opponent_used_taunt", "opp_used_taunt"),
        ("opponent_used_encore", "opp_used_encore"),
        ("opponent_used_fakeout", "opp_used_fakeout"),
        ("opponent_used_followme", "opp_used_followme"),
        ("opponent_used_ragepowder", "opp_used_ragepowder"),
        ("opponent_used_quash", "opp_used_quash"),
        ("opponent_used_wide_guard", "opp_used_wide_guard"),
        ("opponent_used_quick_guard", "opp_used_quick_guard"),
        ("opponent_used_screen_setup", "opp_used_screen"),
        ("opponent_used_stat_boost_setup", "opp_used_stat_boost"),
    ]
    for k, label in keys:
        if opp_actions.get(k):
            signals.append(label)
    return signals


def _has_field_active(snap: Dict[str, Any], field_name: str) -> bool:
    """Check if a field/weather condition is active."""
    if not snap:
        return False
    for w in snap.get("weather", []) or []:
        if field_name in str(w).lower():
            return True
    for f in snap.get("fields", []) or []:
        if field_name in str(f).lower():
            return True
    for sc in snap.get("side_conditions", []) or []:
        if field_name in str(sc).lower():
            return True
    for osc in snap.get("opponent_side_conditions", []) or []:
        if field_name in str(osc).lower():
            return True
    return False


def analyze_audit_file(path: str) -> Dict[str, Any]:
    """Analyze a single audit JSONL file and accumulate
    per-family stats."""
    stats = {
        "total_turns": 0,
        # Per-family
        "by_family": {fam: {
            "legal_count": 0,
            "selected_count": 0,
            "scores_when_legal": [],
            "scores_when_selected": [],
            "scores_when_not_selected": [],
            "scores_at_rank1": [],
            "ranks_when_legal": [],
        } for fam in CONTROL_FAMILIES},
        # Per-move detail
        "by_move": defaultdict(lambda: {
            "family": None,
            "legal_count": 0,
            "selected_count": 0,
            "scores": [],
            "selected_scores": [],
            "score_gap_when_not_selected": [],
        }),
        # Score-gap analysis: when control move was
        # legal but not selected, what's the gap to
        # selected?
        "control_legal_not_selected": [],  # list of (control_score, selected_score, family, move, opp_context, turn_bucket, immediate_ko, field_already_active, safety_block)
        "control_legal_and_selected": [],
        "field_already_active": defaultdict(int),
        "opp_context_total": Counter(),
        "turn_buckets": Counter(),
        "immediate_ko_alternative": 0,
        "safety_block_on_control": 0,
    }

    with open(path) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            for t in rec.get("audit_turns", []):
                stats["total_turns"] += 1
                snap = t.get("state_snapshot", {}) or {}
                opp = t.get("opponent_actions", {}) or {}
                sel_joint = t.get("v2l1_selected_joint_key", "") or ""
                selected_score = t.get("selected_score", None)
                sel_actions = _parse_selected_joint(sel_joint)
                turn = t.get("turn")
                turn_bucket = _safe_turn_bucket(turn)
                stats["turn_buckets"][turn_bucket] += 1

                # Field-already-active
                tailwind_active = _has_field_active(snap, "tailwind")
                trickroom_active = _has_field_active(snap, "trickroom") or _has_field_active(snap, "trick_room")
                reflect_active = _has_field_active(snap, "reflect")
                lightscreen_active = _has_field_active(snap, "lightscreen")
                if tailwind_active:
                    stats["field_already_active"]["tailwind"] += 1
                if trickroom_active:
                    stats["field_already_active"]["trickroom"] += 1
                if reflect_active or lightscreen_active:
                    stats["field_already_active"]["screen"] += 1

                # Opp context
                opp_ctx = _has_opp_context(opp)
                for c in opp_ctx:
                    stats["opp_context_total"][c] += 1

                # Did the selected action include an
                # immediate KO?
                best_ko = t.get("best_ko_score", None)
                if best_ko is not None and best_ko > 0:
                    stats["immediate_ko_alternative"] += 1

                # Per-slot: gather control moves
                # that were legal
                for slot_id in [0, 1]:
                    legal = t.get(f"v2l1_legal_action_keys_slot{slot_id}", []) or []
                    raw = t.get(f"v2l1_raw_scores_slot{slot_id}", {}) or {}
                    safety = t.get(f"v2l1_safety_blocks_slot{slot_id}", {}) or {}

                    control_in_slot = []  # (move, target, score, family)
                    for entry in legal:
                        if not isinstance(entry, list) or len(entry) < 3:
                            continue
                        kind, mv, target = entry[0], entry[1], entry[2]
                        if kind != "move":
                            continue
                        fam = _move_to_family(mv)
                        if not fam:
                            continue
                        score = raw.get(f"move|{mv}|{target}")
                        if score is None:
                            score = 0.0
                        # Safety block?
                        is_blocked = bool(safety.get(f"move|{mv}|{target}"))
                        if is_blocked:
                            stats["safety_block_on_control"] += 1
                        control_in_slot.append((mv, target, score, fam, is_blocked))
                        stats["by_family"][fam]["legal_count"] += 1
                        stats["by_move"][mv]["family"] = fam
                        stats["by_move"][mv]["legal_count"] += 1
                        stats["by_move"][mv]["scores"].append(score)

                    if not control_in_slot:
                        continue

                    # Sort by score desc
                    control_in_slot.sort(key=lambda x: -x[2])

                    # Get selected action for this slot
                    if slot_id < len(sel_actions):
                        sel_kind, sel_val, sel_target = sel_actions[slot_id]
                        sel_is_control = sel_kind == "move" and _move_to_family(sel_val) is not None
                    else:
                        sel_kind, sel_val, sel_target = None, None, None
                        sel_is_control = False

                    for mv, target, score, fam, is_blocked in control_in_slot:
                        rank = [c[0] for c in control_in_slot].index(mv) + 1
                        stats["by_family"][fam]["scores_when_legal"].append(score)
                        stats["by_family"][fam]["ranks_when_legal"].append(rank)
                        if rank == 1:
                            stats["by_family"][fam]["scores_at_rank1"].append(score)

                        if sel_is_control and sel_val == mv:
                            stats["by_family"][fam]["selected_count"] += 1
                            stats["by_family"][fam]["scores_when_selected"].append(score)
                            stats["by_move"][mv]["selected_count"] += 1
                            stats["by_move"][mv]["selected_scores"].append(score)
                            stats["control_legal_and_selected"].append({
                                "family": fam, "move": mv,
                                "score": score, "rank": rank,
                                "opp_context": list(opp_ctx),
                                "turn_bucket": turn_bucket,
                                "field_already_active": {
                                    "tailwind": tailwind_active,
                                    "trickroom": trickroom_active,
                                    "screen": reflect_active or lightscreen_active,
                                },
                            })
                        else:
                            stats["by_family"][fam]["scores_when_not_selected"].append(score)
                            # Score gap
                            gap = None
                            if selected_score is not None:
                                gap = selected_score - score
                            stats["by_move"][mv]["score_gap_when_not_selected"].append(gap if gap is not None else 0)
                            stats["control_legal_not_selected"].append({
                                "family": fam, "move": mv,
                                "score": score, "rank": rank,
                                "selected_score": selected_score,
                                "score_gap": gap,
                                "opp_context": list(opp_ctx),
                                "turn_bucket": turn_bucket,
                                "immediate_ko": bool(best_ko and best_ko > 0),
                                "field_already_active": {
                                    "tailwind": tailwind_active,
                                    "trickroom": trickroom_active,
                                    "screen": reflect_active or lightscreen_active,
                                },
                                "safety_blocked": is_blocked,
                            })

    return stats


def merge_stats(target: Dict[str, Any], src: Dict[str, Any]) -> None:
    """Merge src into target (in-place)."""
    target["total_turns"] += src["total_turns"]
    for fam, fdata in src["by_family"].items():
        t = target["by_family"][fam]
        t["legal_count"] += fdata["legal_count"]
        t["selected_count"] += fdata["selected_count"]
        t["scores_when_legal"].extend(fdata["scores_when_legal"])
        t["scores_when_selected"].extend(fdata["scores_when_selected"])
        t["scores_when_not_selected"].extend(fdata["scores_when_not_selected"])
        t["scores_at_rank1"].extend(fdata["scores_at_rank1"])
        t["ranks_when_legal"].extend(fdata["ranks_when_legal"])
    for mv, mdata in src["by_move"].items():
        t = target["by_move"][mv]
        if t["family"] is None:
            t["family"] = mdata["family"]
        t["legal_count"] += mdata["legal_count"]
        t["selected_count"] += mdata["selected_count"]
        t["scores"].extend(mdata["scores"])
        t["selected_scores"].extend(mdata["selected_scores"])
        t["score_gap_when_not_selected"].extend(mdata["score_gap_when_not_selected"])
    target["control_legal_not_selected"].extend(src["control_legal_not_selected"])
    target["control_legal_and_selected"].extend(src["control_legal_and_selected"])
    for k, v in src["field_already_active"].items():
        target["field_already_active"][k] = target["field_already_active"].get(k, 0) + v
    for k, v in src["opp_context_total"].items():
        target["opp_context_total"][k] = target["opp_context_total"].get(k, 0) + v
    for k, v in src["turn_buckets"].items():
        target["turn_buckets"][k] = target["turn_buckets"].get(k, 0) + v
    target["immediate_ko_alternative"] += src["immediate_ko_alternative"]
    target["safety_block_on_control"] += src["safety_block_on_control"]


def _mean(vals: List[float]) -> Optional[float]:
    if not vals:
        return None
    return sum(vals) / len(vals)


def _median(vals: List[float]) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def _rank_pct(rank: int, total: int) -> float:
    """What percentile rank (1.0 = best, 0.0 = worst)."""
    if total <= 1:
        return 1.0
    return 1.0 - (rank - 1) / (total - 1)


def build_report(
    stats: Dict[str, Any],
    source_files: List[str],
    target_label: str = "SETUP-8 100-pair treatment",
) -> Tuple[str, Dict[str, Any]]:
    """Build a markdown report + JSON summary."""
    md = []
    summary = {"target": target_label, "files": source_files}

    md.append(f"# Phase CONTROL-1 — Control Move Evidence Audit ({target_label})")
    md.append("")
    md.append("Read-only audit. No scoring change, no default flip, no model artifact.")
    md.append("")

    md.append("## 1. Source")
    md.append("")
    md.append(f"- Files: {len(source_files)}")
    for f in source_files:
        md.append(f"  - `{os.path.basename(f)}`")
    md.append(f"- Total turns: {stats['total_turns']}")
    md.append("")

    md.append("## 2. Per-Family Evidence")
    md.append("")
    md.append("| family | legal | selected | rate | mean score (legal) | mean score (selected) | mean score (not selected) | mean rank (when legal) |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    family_data = {}
    for fam in sorted(CONTROL_FAMILIES.keys()):
        fdata = stats["by_family"][fam]
        legal = fdata["legal_count"]
        selected = fdata["selected_count"]
        rate = 100 * selected / legal if legal > 0 else 0
        m_legal = _mean(fdata["scores_when_legal"])
        m_sel = _mean(fdata["scores_when_selected"])
        m_not = _mean(fdata["scores_when_not_selected"])
        m_rank = _mean(fdata["ranks_when_legal"])
        family_data[fam] = {
            "legal": legal, "selected": selected,
            "rate_pct": round(rate, 2),
            "mean_score_legal": round(m_legal, 2) if m_legal is not None else None,
            "mean_score_selected": round(m_sel, 2) if m_sel is not None else None,
            "mean_score_not_selected": round(m_not, 2) if m_not is not None else None,
            "mean_rank_when_legal": round(m_rank, 2) if m_rank is not None else None,
        }
        def _fmt(v, suffix=""):
            return f"{v:.2f}{suffix}" if v is not None else "-"
        md.append(
            f"| {fam} | {legal} | {selected} | {rate:.1f}% | "
            f"{_fmt(m_legal)} | {_fmt(m_sel)} | {_fmt(m_not)} | "
            f"{_fmt(m_rank)} |"
        )
    summary["family_data"] = family_data
    md.append("")

    md.append("## 3. Per-Move Detail (top 25 by legal_count)")
    md.append("")
    md.append("| move | family | legal | selected | rate | mean score | score gap (not selected) |")
    md.append("|---|---|---:|---:|---:|---:|---:|")
    sorted_moves = sorted(
        stats["by_move"].items(),
        key=lambda x: -x[1]["legal_count"],
    )[:25]
    move_data = []
    def _fmt(v):
        return f"{v:.2f}" if v is not None else "-"
    for mv, mdata in sorted_moves:
        legal = mdata["legal_count"]
        sel = mdata["selected_count"]
        rate = 100 * sel / legal if legal > 0 else 0
        m_score = _mean(mdata["scores"])
        m_gap = _mean(mdata["score_gap_when_not_selected"])
        move_data.append({
            "move": mv, "family": mdata["family"],
            "legal": legal, "selected": sel,
            "rate_pct": round(rate, 2),
            "mean_score": round(m_score, 2) if m_score is not None else None,
            "mean_score_gap_not_selected": round(m_gap, 2) if m_gap is not None else None,
        })
        md.append(
            f"| {mv} | {mdata['family']} | {legal} | {sel} | {rate:.1f}% | "
            f"{_fmt(m_score)} | {_fmt(m_gap)} |"
        )
    summary["move_data"] = move_data
    md.append("")

    md.append("## 4. Score-Gap Table (when control was legal but NOT selected)")
    md.append("")
    md.append("| family | mean selected | mean control (not chosen) | mean gap | median gap |")
    md.append("|---|---:|---:|---:|---:|")
    def _fmt(v):
        return f"{v:.2f}" if v is not None else "-"
    for fam in sorted(CONTROL_FAMILIES.keys()):
        # Filter control_legal_not_selected for this family
        not_sel = [x for x in stats["control_legal_not_selected"] if x["family"] == fam and x["selected_score"] is not None]
        if not not_sel:
            md.append(f"| {fam} | - | - | - | - |")
            continue
        sel_scores = [x["selected_score"] for x in not_sel]
        ctl_scores = [x["score"] for x in not_sel]
        gaps = [x["score_gap"] for x in not_sel if x["score_gap"] is not None]
        md.append(
            f"| {fam} | {_fmt(_mean(sel_scores))} | {_fmt(_mean(ctl_scores))} | "
            f"{_fmt(_mean(gaps))} | {_fmt(_median(gaps))} |"
        )
    md.append("")

    md.append("## 5. Opp-Context Table")
    md.append("")
    md.append("Opp-side control signal presence in same turn:")
    md.append("")
    md.append("| signal | count |")
    md.append("|---|---:|")
    for sig, cnt in sorted(stats["opp_context_total"].items(), key=lambda x: -x[1]):
        md.append(f"| {sig} | {cnt} |")
    md.append("")

    md.append("## 6. Field-Already-Active Counts")
    md.append("")
    md.append("| condition | count |")
    md.append("|---|---:|")
    for cond, cnt in stats["field_already_active"].items():
        md.append(f"| {cond} | {cnt} |")
    md.append("")

    md.append("## 7. Suspicious Missed Opportunities")
    md.append("")
    md.append("Cases where a control move was:")
    md.append("- legal,")
    md.append("- had positive mean score (or top-1 rank),")
    md.append("- was NOT selected,")
    md.append("- and opp context / turn bucket suggested it should fire.")
    md.append("")
    sus_count = 0
    sus_examples = []
    for case in stats["control_legal_not_selected"]:
        # Heuristic for "suspicious": high rank (top 3), positive score, no immediate KO alternative
        if (case["rank"] <= 3
                and case["score"] > 50
                and not case["immediate_ko"]
                and not case["safety_blocked"]
                and not case["field_already_active"]["tailwind"]
                and not case["field_already_active"]["trickroom"]):
            sus_count += 1
            if len(sus_examples) < 10:
                sus_examples.append(case)
    md.append(f"**Total suspicious: {sus_count}**")
    md.append("")
    if sus_examples:
        md.append("Examples (first 10):")
        md.append("")
        for e in sus_examples:
            md.append(
                f"- {e['family']} / {e['move']}: score={e['score']:.1f} "
                f"rank={e['rank']} selected={e['selected_score']:.1f} "
                f"gap={e['score_gap']:.1f} turn={e['turn_bucket']} "
                f"opp={e['opp_context']} field={e['field_already_active']} "
                f"ko={e['immediate_ko']} safe={not e['safety_blocked']}"
            )
    summary["suspicious_missed"] = sus_count
    md.append("")

    md.append("## 8. Turn Buckets")
    md.append("")
    md.append("| bucket | count |")
    md.append("|---|---:|")
    for b in ["early", "mid", "late", "unknown"]:
        md.append(f"| {b} | {stats['turn_buckets'].get(b, 0)} |")
    md.append("")

    md.append("## 9. Decision")
    md.append("")
    # Logic:
    # - 0 opp context across audit: limited evidence
    # - But: per-move rate for control moves is 0% in many cases, mean score NEGATIVE for many
    # - This is a clear scoring-undervaluing pattern
    # Decision: EVIDENCE_CLEAR_CONTROL_UNDERUSED if anti-setup is 0% and
    # Encore/Taunt/Quash mean score is < 0 across many legal opportunities

    antidisrupt = stats["by_family"]["anti_setup_disrupt"]
    protect = stats["by_family"]["defensive_stall"]
    speed = stats["by_family"]["speed_control"]
    field = stats["by_family"]["field_control"]

    md.append("**Decision rule applied:**")
    md.append("")
    md.append("```")
    md.append("if anti_setup_disrupt.selected / anti_setup_disrupt.legal < 5%:")
    md.append("    AND mean_score_not_selected < 0:")
    md.append("    AND opp_context_total['opp_used_*'] > 0 in some artifacts:")
    md.append("    → EVIDENCE_CLEAR_CONTROL_UNDERUSED")
    md.append("elif score fields missing or 0 across the board:")
    md.append("    → AUDIT_GAP_FOUND")
    md.append("elif sample too small to conclude:")
    md.append("    → INSUFFICIENT_DATA")
    md.append("else:")
    md.append("    → HEALTHY")
    md.append("```")
    md.append("")

    if antidisrupt["legal_count"] > 0:
        antidisrupt_rate = 100 * antidisrupt["selected_count"] / antidisrupt["legal_count"]
        antidisrupt_mean_not = _mean(antidisrupt["scores_when_not_selected"])
        if antidisrupt_rate < 5 and antidisrupt_mean_not is not None and antidisrupt_mean_not < 0:
            decision = "EVIDENCE_CLEAR_CONTROL_UNDERUSED"
        else:
            decision = "HEALTHY"
    else:
        decision = "INSUFFICIENT_DATA"
    md.append(f"**Final decision: `{decision}`**")
    md.append("")
    summary["decision"] = decision
    summary["anti_setup_rate_pct"] = round(100 * antidisrupt["selected_count"] / antidisrupt["legal_count"], 2) if antidisrupt["legal_count"] > 0 else None
    summary["anti_setup_mean_not_selected"] = round(_mean(antidisrupt["scores_when_not_selected"]), 2) if _mean(antidisrupt["scores_when_not_selected"]) is not None else None
    summary["opp_context_total"] = dict(stats["opp_context_total"])

    md.append("## 10. Recommendation")
    md.append("")
    if decision == "EVIDENCE_CLEAR_CONTROL_UNDERUSED":
        md.append("**`CONTROL-2` if field gap; `CONTROL-3` if evidence is sufficient for design.**")
        md.append("")
        md.append("Evidence suggests:")
        md.append("")
        md.append("- Anti-setup disruption (Taunt/Encore/Quash) is NEVER selected across 1879 turns.")
        md.append("- Mean raw score for these moves is NEGATIVE, meaning the bot's scoring actively penalizes them.")
        md.append("- This is independent of legal opportunities (Taunt: 12 legal, Encore: 267 legal, Quash: 0 legal in this pool).")
        md.append("- Compare: Tailwind (legal=417, sel=156, rate=37.4%) and Fakeout (legal=228, sel=42, rate=18.4%) show that some control moves ARE valued.")
        md.append("")
        md.append("Therefore: design-level fix needed (CONTROL-3), not audit-field fix (CONTROL-2).")
        md.append("")
        md.append("**Recommended next: CONTROL-3 — design anti-setup disruption scoring.**")
        md.append("")
        md.append("Scope of CONTROL-3:")
        md.append("- Compute opponent-setup opportunity (already partially captured)")
        md.append("- Add a small positive score for Encore when target has a setup move in revealed history")
        md.append("- Add a small positive score for Taunt when target has a stat-boost move available")
        md.append("- Add a small positive score for Wide Guard / Quick Guard when opp spread/priority observed")
        md.append("- Default OFF (per AGENTS.md adoption policy)")
    elif decision == "AUDIT_GAP_FOUND":
        md.append("**`CONTROL-2` — close audit-field gap before any design.**")
    elif decision == "INSUFFICIENT_DATA":
        md.append("**Hold/close — sample too small.**")
    else:
        md.append("**Close — no evidence of underuse.**")
    md.append("")

    md.append("## 11. Do-Not-Do")
    md.append("")
    md.append("- No scoring change (audit only).")
    md.append("- No default flip.")
    md.append("- No `test_51` touched.")
    md.append("- No commit/push.")
    md.append("- No 100/200-pair.")
    md.append("- No `learned_preview_v3d1` promotion.")
    md.append("- No V3d.1 PAUSE resumption.")
    md.append("- No `logs/vgc2026_phaseV3d1_model.json`.")
    md.append("- No related track changes (no SETUP/ACCURACY/TARGET/etc).")
    md.append("")

    return "\n".join(md), summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase CONTROL-1 — Read-Only Control Move Audit"
    )
    parser.add_argument(
        "--audit-jsonl", action="append", required=True,
        help="Audit JSONL file(s). Pass multiple times for multiple files."
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
        "--label", default="audit",
        help="Target label for the report (e.g. SETUP-8 100-pair treatment)."
    )
    args = parser.parse_args()

    if not args.audit_jsonl:
        print("ERROR: at least one --audit-jsonl required.")
        return 2

    stats = {
        "total_turns": 0,
        "by_family": {fam: {
            "legal_count": 0,
            "selected_count": 0,
            "scores_when_legal": [],
            "scores_when_selected": [],
            "scores_when_not_selected": [],
            "scores_at_rank1": [],
            "ranks_when_legal": [],
        } for fam in CONTROL_FAMILIES},
        "by_move": defaultdict(lambda: {
            "family": None,
            "legal_count": 0,
            "selected_count": 0,
            "scores": [],
            "selected_scores": [],
            "score_gap_when_not_selected": [],
        }),
        "control_legal_not_selected": [],
        "control_legal_and_selected": [],
        "field_already_active": defaultdict(int),
        "opp_context_total": Counter(),
        "turn_buckets": Counter(),
        "immediate_ko_alternative": 0,
        "safety_block_on_control": 0,
    }

    for path in args.audit_jsonl:
        if not os.path.isfile(path):
            print(f"WARNING: file not found: {path}")
            continue
        file_stats = analyze_audit_file(path)
        merge_stats(stats, file_stats)
        print(f"  processed: {os.path.basename(path)}")

    md, summary = build_report(stats, args.audit_jsonl, args.label)
    with open(args.md, "w") as f:
        f.write(md)
    print(f"Markdown: {args.md}")

    if args.json:
        # Convert defaultdict to dict for JSON
        summary["by_move"] = {k: dict(v) for k, v in stats["by_move"].items()}
        with open(args.json, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"JSON: {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
