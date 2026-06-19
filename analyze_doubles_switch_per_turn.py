#!/usr/bin/env python3
"""Phase SWITCH-2 — Read-Only Switch Outcome Analyzer.

Aggregates switch-related audit fields across turns and
battles to produce actionable evidence about the bot's
switch behavior. Read-only: no production change, no
scoring change, no new audit fields.

Inputs: persisted audit JSONL files (one or more).
The analyzer handles:
  - one audit file
  - multiple --audit-jsonl files
  - missing optional fields safely
  - legacy logs without switch fields

Outputs:
  - Markdown report (--md)
  - Optional JSON summary (--json)

Metrics:
  1. File/row/turn counts
  2. Arm counts by benchmark_arm
  3. Switch opportunity counts
  4. Switch-vs-stay delta distribution
  5. Chosen switch quality
  6. State slices (HP, weather, fields, species)
  7. Top suspicious turns
  8. Per-battle summary
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple


def _percentile(values: List[float], p: float) -> float:
    """Phase SWITCH-2: simple percentile (linear interp)."""
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
    """Phase SWITCH-2: bucket active HP fraction."""
    if hp_fraction is None:
        return "unknown"
    if hp_fraction < 0.25:
        return "0-25"
    if hp_fraction < 0.50:
        return "25-50"
    if hp_fraction < 0.75:
        return "50-75"
    return "75-100"


# Phase ANALYZER-1: attribution parser. Action keys come
# in pipe-delimited form like "switch|sneasler|0" or
# "move|rockslide|0". This helper extracts the
# structured pieces so the analyzer can label them
# clearly in mirror-match cases.
def _parse_action_key(
    key: Optional[Any],
) -> Dict[str, Optional[str]]:
    """Parse an action key into structured fields.

    Returns a dict with:
      - raw: the original key (or None)
      - category: "switch" / "move" / "unknown"
      - species_or_move: the species (for switch) or
        move id (for move)
      - target: the target slot (string or None)
      - switch_target: the species when category is
        "switch", else None
      - is_switch: bool
    """
    out: Dict[str, Optional[str]] = {
        "raw": str(key) if key is not None else None,
        "category": None,
        "species_or_move": None,
        "target": None,
        "switch_target": None,
        "is_switch": False,
    }
    if key is None:
        out["category"] = "unknown"
        return out
    if not isinstance(key, str):
        out["category"] = "unknown"
        return out
    parts = key.split("|")
    if len(parts) < 2:
        out["category"] = "unknown"
        return out
    kind = parts[0].strip().lower()
    if kind == "switch":
        out["category"] = "switch"
        out["is_switch"] = True
        out["species_or_move"] = parts[1].strip().lower()
        out["switch_target"] = out["species_or_move"]
        if len(parts) >= 3:
            out["target"] = parts[2].strip()
    elif kind == "move":
        out["category"] = "move"
        out["is_switch"] = False
        out["species_or_move"] = parts[1].strip().lower()
        if len(parts) >= 3:
            out["target"] = parts[2].strip()
    else:
        out["category"] = "unknown"
    return out


def _attribution_labels(
    state_snapshot: Dict[str, Any],
    slot_idx: int,
) -> Dict[str, Optional[str]]:
    """Extract clear attribution labels for our active
    and opponent active at the given slot index.

    Returns dict with:
      - our_active_slot0 / our_active_slot1
      - opp_active_slot0 / opp_active_slot1
      - our_active (the slot-specific one)
      - opp_active (the slot-specific one)
    """
    ss = state_snapshot or {}
    our_list = ss.get("our_active_species", []) or []
    opp_list = ss.get("opp_active_species", []) or []
    our0 = str(our_list[0]).lower() if len(our_list) > 0 else None
    our1 = str(our_list[1]).lower() if len(our_list) > 1 else None
    opp0 = str(opp_list[0]).lower() if len(opp_list) > 0 else None
    opp1 = str(opp_list[1]).lower() if len(opp_list) > 1 else None
    out: Dict[str, Optional[str]] = {
        "our_active_slot0": our0,
        "our_active_slot1": our1,
        "opp_active_slot0": opp0,
        "opp_active_slot1": opp1,
        "our_active": our0 if slot_idx == 0 else our1,
        "opp_active": opp0 if slot_idx == 0 else opp1,
    }
    return out


def _build_attribution(
    state_snapshot: Dict[str, Any],
    slot_idx: int,
    chosen_action_key: Optional[str],
    best_switch_action_key: Optional[str],
    best_non_switch_action_key: Optional[str],
) -> Dict[str, Any]:
    """Build a clean attribution dict for a turn slot.

    Includes:
      - our_active / opp_active (slot-specific)
      - our_active_slot0 / our_active_slot1 /
        opp_active_slot0 / opp_active_slot1
      - selected_action_key + parsed selected_*
      - best_switch_action_key + parsed best_switch_*
      - best_non_switch_action_key + parsed
        best_non_switch_*
      - mirror_match_with_opp_active: bool — True if
        our_switch_target species == opp_active
        species at the same slot
    """
    labels = _attribution_labels(state_snapshot, slot_idx)
    sel = _parse_action_key(chosen_action_key)
    bs = _parse_action_key(best_switch_action_key)
    bns = _parse_action_key(best_non_switch_action_key)
    mirror = False
    if (
        bs.get("switch_target")
        and labels.get("opp_active")
        and bs["switch_target"] == labels["opp_active"]
    ):
        mirror = True
    out = {
        **labels,
        "selected_action_key": chosen_action_key,
        "selected_category": sel.get("category"),
        "selected_species_or_move": sel.get(
            "species_or_move"
        ),
        "selected_target": sel.get("target"),
        "selected_is_switch": bool(sel.get("is_switch")),
        "best_switch_action_key": best_switch_action_key,
        "best_switch_target": bs.get("switch_target"),
        "best_switch_target_raw": (
            bs.get("species_or_move")
            if bs.get("category") == "switch" else None
        ),
        "best_switch_category": bs.get("category"),
        "best_non_switch_action_key": (
            best_non_switch_action_key
        ),
        "best_non_switch_move": bns.get("species_or_move"),
        "best_non_switch_target": bns.get("target"),
        "best_non_switch_category": bns.get("category"),
        "mirror_match_with_opp_active": mirror,
    }
    return out


def _load_audit(path: str) -> List[Dict[str, Any]]:
    """Phase SWITCH-2: load a JSONL file, skipping malformed lines."""
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


def _collect_slot_data(
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Phase SWITCH-2: aggregate per-slot switch data.

    Returns a dict with:
      - counts: arm, rows, turns
      - opportunities: switch_cf_present, slot0/slot1 present
      - deltas: list of switch_vs_non_switch_delta values
      - quality: chosen switch positive/negative counts
      - state: HP buckets, weather, fields, species
      - per_battle: list of per-battle summaries
      - top_suspicious: sorted list of suspicious turns
    """
    counts = {
        "arm": Counter(),
        "rows": 0,
        "turns": 0,
    }
    opportunities = {
        "switch_cf_present": 0,
        "slot0_present": 0,
        "slot1_present": 0,
        "slot0_positive_delta": 0,
        "slot1_positive_delta": 0,
    }
    deltas: List[float] = []
    quality = {
        "chosen_switch_positive_delta": 0,
        "chosen_switch_negative_delta": 0,
        "chosen_switch_zero_delta": 0,
        "non_switch_positive_delta": 0,
        "non_switch_negative_delta": 0,
        "non_switch_zero_delta": 0,
        "no_best_switch": 0,
        "no_best_non_switch": 0,
    }
    state = {
        "hp_buckets": Counter(),
        "weather": Counter(),
        "fields": Counter(),
        "our_species": Counter(),
        "opp_species": Counter(),
    }
    per_battle: List[Dict[str, Any]] = []
    top_suspicious: List[Dict[str, Any]] = []

    for row in rows:
        counts["rows"] += 1
        arm = row.get("benchmark_arm", "") or "unknown"
        counts["arm"][arm] += 1
        battle_tag = row.get("battle_tag", "?")
        won = row.get("won")
        turns_list = row.get("audit_turns", [])
        counts["turns"] += len(turns_list)

        battle_switch_chosen = 0
        battle_pos_delta_not_switched = 0
        battle_neg_delta_switched = 0

        for turn in turns_list:
            counts["turns"] += 1
            scf = turn.get("switch_counterfactual") or {}
            if scf:
                opportunities["switch_cf_present"] += 1
            ss = turn.get("state_snapshot") or {}
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
            our_species_list = ss.get("our_active_species", []) or []
            opp_species_list = ss.get("opp_active_species", []) or []
            our_hp_list = ss.get("our_active_hp_fraction", []) or []

            # Slot 0
            slot0 = scf.get("slot0") if isinstance(scf, dict) else None
            if slot0:
                opportunities["slot0_present"] += 1
                delta = slot0.get("switch_vs_non_switch_delta")
                if delta is not None:
                    deltas.append(float(delta))
                    if delta > 0:
                        opportunities["slot0_positive_delta"] += 1
                if slot0.get("chosen_is_switch"):
                    battle_switch_chosen += 1
                    if delta is not None:
                        if delta > 0:
                            quality["chosen_switch_positive_delta"] += 1
                        elif delta < 0:
                            quality["chosen_switch_negative_delta"] += 1
                        else:
                            quality["chosen_switch_zero_delta"] += 1
                else:
                    if delta is not None:
                        if delta > 0:
                            quality["non_switch_positive_delta"] += 1
                            battle_pos_delta_not_switched += 1
                        elif delta < 0:
                            quality["non_switch_negative_delta"] += 1
                        else:
                            quality["non_switch_zero_delta"] += 1
                # State slices
                hp0 = our_hp_list[0] if len(our_hp_list) > 0 else None
                state["hp_buckets"][_hp_bucket(hp0)] += 1
                state["weather"][weather] += 1
                state["fields"][fields_key] += 1
                if our_species_list:
                    state["our_species"][our_species_list[0]] += 1
                if opp_species_list:
                    state["opp_species"][opp_species_list[0]] += 1
                # Suspicious: switch chosen with most negative delta
                if (slot0.get("chosen_is_switch")
                        and delta is not None and delta < 0):
                    attr = _build_attribution(
                        ss, 0,
                        slot0.get("chosen_action_key"),
                        slot0.get("best_switch_action_key"),
                        slot0.get("best_non_switch_action_key"),
                    )
                    top_suspicious.append({
                        "battle_tag": battle_tag,
                        "arm": arm,
                        "turn": turn.get("turn"),
                        "slot": "slot0",
                        "chosen": slot0.get("chosen_action_key"),
                        "best_switch": slot0.get(
                            "best_switch_action_key"
                        ),
                        "best_non_switch": slot0.get(
                            "best_non_switch_action_key"
                        ),
                        "delta": delta,
                        "kind": "switch_with_negative_delta",
                        "attribution": attr,
                    })
                # Suspicious: stay chosen with positive delta
                if (not slot0.get("chosen_is_switch")
                        and delta is not None and delta > 0):
                    attr = _build_attribution(
                        ss, 0,
                        slot0.get("chosen_action_key"),
                        slot0.get("best_switch_action_key"),
                        slot0.get("best_non_switch_action_key"),
                    )
                    top_suspicious.append({
                        "battle_tag": battle_tag,
                        "arm": arm,
                        "turn": turn.get("turn"),
                        "slot": "slot0",
                        "chosen": slot0.get("chosen_action_key"),
                        "best_switch": slot0.get(
                            "best_switch_action_key"
                        ),
                        "best_non_switch": slot0.get(
                            "best_non_switch_action_key"
                        ),
                        "delta": delta,
                        "kind": "stay_with_positive_delta",
                        "attribution": attr,
                    })
            else:
                quality["no_best_switch"] += 1
                quality["no_best_non_switch"] += 1

            # Slot 1
            slot1 = scf.get("slot1") if isinstance(scf, dict) else None
            if slot1:
                opportunities["slot1_present"] += 1
                delta = slot1.get("switch_vs_non_switch_delta")
                if delta is not None:
                    deltas.append(float(delta))
                    if delta > 0:
                        opportunities["slot1_positive_delta"] += 1
                if slot1.get("chosen_is_switch"):
                    battle_switch_chosen += 1
                    if delta is not None:
                        if delta > 0:
                            quality["chosen_switch_positive_delta"] += 1
                        elif delta < 0:
                            quality["chosen_switch_negative_delta"] += 1
                        else:
                            quality["chosen_switch_zero_delta"] += 1
                else:
                    if delta is not None:
                        if delta > 0:
                            quality["non_switch_positive_delta"] += 1
                            battle_pos_delta_not_switched += 1
                        elif delta < 0:
                            quality["non_switch_negative_delta"] += 1
                        else:
                            quality["non_switch_zero_delta"] += 1
                # State slices
                hp1 = our_hp_list[1] if len(our_hp_list) > 1 else None
                state["hp_buckets"][_hp_bucket(hp1)] += 1
                state["weather"][weather] += 1
                state["fields"][fields_key] += 1
                if len(our_species_list) > 1:
                    state["our_species"][our_species_list[1]] += 1
                if len(opp_species_list) > 1:
                    state["opp_species"][opp_species_list[1]] += 1
                if (slot1.get("chosen_is_switch")
                        and delta is not None and delta < 0):
                    attr = _build_attribution(
                        ss, 1,
                        slot1.get("chosen_action_key"),
                        slot1.get("best_switch_action_key"),
                        slot1.get("best_non_switch_action_key"),
                    )
                    top_suspicious.append({
                        "battle_tag": battle_tag,
                        "arm": arm,
                        "turn": turn.get("turn"),
                        "slot": "slot1",
                        "chosen": slot1.get("chosen_action_key"),
                        "best_switch": slot1.get(
                            "best_switch_action_key"
                        ),
                        "best_non_switch": slot1.get(
                            "best_non_switch_action_key"
                        ),
                        "delta": delta,
                        "kind": "switch_with_negative_delta",
                        "attribution": attr,
                    })
                if (not slot1.get("chosen_is_switch")
                        and delta is not None and delta > 0):
                    attr = _build_attribution(
                        ss, 1,
                        slot1.get("chosen_action_key"),
                        slot1.get("best_switch_action_key"),
                        slot1.get("best_non_switch_action_key"),
                    )
                    top_suspicious.append({
                        "battle_tag": battle_tag,
                        "arm": arm,
                        "turn": turn.get("turn"),
                        "slot": "slot1",
                        "chosen": slot1.get("chosen_action_key"),
                        "best_switch": slot1.get(
                            "best_switch_action_key"
                        ),
                        "best_non_switch": slot1.get(
                            "best_non_switch_action_key"
                        ),
                        "delta": delta,
                        "kind": "stay_with_positive_delta",
                        "attribution": attr,
                    })
            else:
                quality["no_best_switch"] += 1
                quality["no_best_non_switch"] += 1

        per_battle.append({
            "battle_tag": battle_tag,
            "arm": arm,
            "won": won,
            "turns": len(turns_list),
            "switch_chosen_count": battle_switch_chosen,
            "positive_delta_not_switched_count": (
                battle_pos_delta_not_switched
            ),
            "negative_delta_switched_count": (
                battle_neg_delta_switched
            ),
        })

    return {
        "counts": {
            "rows": counts["rows"],
            "turns": counts["turns"],
            "arm": dict(counts["arm"]),
        },
        "opportunities": opportunities,
        "deltas": deltas,
        "quality": quality,
        "state": {
            "hp_buckets": dict(state["hp_buckets"]),
            "weather": dict(state["weather"]),
            "fields": dict(state["fields"]),
            "our_species": dict(state["our_species"]),
            "opp_species": dict(state["opp_species"]),
        },
        "per_battle": per_battle,
        "top_suspicious": top_suspicious,
    }


def _delta_summary(deltas: List[float]) -> Dict[str, float]:
    """Phase SWITCH-2: compute delta distribution summary."""
    if not deltas:
        return {
            "count": 0,
            "min": 0.0,
            "p25": 0.0,
            "median": 0.0,
            "p75": 0.0,
            "max": 0.0,
            "mean": 0.0,
        }
    return {
        "count": len(deltas),
        "min": min(deltas),
        "p25": _percentile(deltas, 0.25),
        "median": _percentile(deltas, 0.50),
        "p75": _percentile(deltas, 0.75),
        "max": max(deltas),
        "mean": sum(deltas) / len(deltas),
    }


def _write_markdown(
    input_paths: List[str],
    data: Dict[str, Any],
    delta_summary: Dict[str, float],
    top_n: int,
    md_path: str,
) -> None:
    """Phase SWITCH-2: write the markdown report."""
    counts = data["counts"]
    opps = data["opportunities"]
    quality = data["quality"]
    state = data["state"]
    per_battle = data["per_battle"]
    top_suspicious = data["top_suspicious"]

    lines: List[str] = []
    lines.append("# Phase SWITCH-2 — Switch Outcome Analysis")
    lines.append("")
    lines.append("## TL;DR")
    lines.append("")
    lines.append(
        f"- Rows: {counts['rows']}, audit turns: {counts['turns']}"
    )
    lines.append(
        f"- Arm counts: {counts['arm']}"
    )
    lines.append(
        f"- Switch counterfactual present in "
        f"{opps['switch_cf_present']} turns"
    )
    lines.append(
        f"- Slot0 present: {opps['slot0_present']}, "
        f"Slot1 present: {opps['slot1_present']}"
    )
    lines.append(
        f"- Deltas collected: {delta_summary['count']}"
    )
    lines.append(
        f"- Median delta: {delta_summary['median']:.2f}, "
        f"mean: {delta_summary['mean']:.2f}"
    )
    lines.append(
        f"- Chosen switch positive delta: "
        f"{quality['chosen_switch_positive_delta']}, "
        f"negative: {quality['chosen_switch_negative_delta']}"
    )
    lines.append(
        f"- Stay with positive delta: "
        f"{quality['non_switch_positive_delta']}, "
        f"negative: {quality['non_switch_negative_delta']}"
    )
    lines.append("")
    lines.append("## Inputs")
    lines.append("")
    for p in input_paths:
        lines.append(f"- `{p}`")
    lines.append("")
    lines.append("## Data quality")
    lines.append("")
    total_slots = (
        opps["slot0_present"] + opps["slot1_present"]
    )
    lines.append(
        f"- Rows with audit_turns: {counts['rows']}"
    )
    lines.append(
        f"- Total audit turns: {counts['turns']}"
    )
    lines.append(
        f"- Turns with switch_counterfactual: "
        f"{opps['switch_cf_present']}"
    )
    lines.append(
        f"- Total slot records (slot0 + slot1): {total_slots}"
    )
    if total_slots == 0:
        lines.append(
            "- WARNING: zero switch counterfactual records found. "
            "The bot may not have any switch opportunities in the "
            "provided audit data."
        )
    lines.append("")
    lines.append("## Aggregate counts")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    lines.append(f"| rows | {counts['rows']} |")
    lines.append(f"| audit turns | {counts['turns']} |")
    lines.append(f"| switch_cf_present | {opps['switch_cf_present']} |")
    lines.append(f"| slot0_present | {opps['slot0_present']} |")
    lines.append(f"| slot1_present | {opps['slot1_present']} |")
    lines.append(
        f"| slot0_positive_delta | "
        f"{opps['slot0_positive_delta']} |"
    )
    lines.append(
        f"| slot1_positive_delta | "
        f"{opps['slot1_positive_delta']} |"
    )
    lines.append("")
    lines.append("## Delta distribution")
    lines.append("")
    if delta_summary["count"] == 0:
        lines.append("No deltas collected.")
    else:
        lines.append("| stat | value |")
        lines.append("|---|---|")
        for k in [
            "count", "min", "p25", "median", "p75", "max", "mean",
        ]:
            lines.append(
                f"| {k} | {delta_summary[k]:.2f} |"
            )
    lines.append("")
    lines.append("## Chosen switch quality")
    lines.append("")
    lines.append("| metric | count |")
    lines.append("|---|---|")
    for k, v in quality.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("## State slices")
    lines.append("")
    lines.append("### HP buckets")
    lines.append("")
    lines.append("| bucket | count |")
    lines.append("|---|---|")
    for k, v in sorted(state["hp_buckets"].items()):
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("### Weather")
    lines.append("")
    lines.append("| weather | count |")
    lines.append("|---|---|")
    for k, v in sorted(state["weather"].items()):
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("### Fields")
    lines.append("")
    lines.append("| fields | count |")
    lines.append("|---|---|")
    for k, v in sorted(state["fields"].items()):
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
    lines.append("## Top suspicious turns")
    lines.append("")
    # Sort by absolute delta descending, take top_n
    sorted_susp = sorted(
        top_suspicious,
        key=lambda x: abs(x.get("delta", 0)),
        reverse=True,
    )[:top_n]
    if not sorted_susp:
        lines.append("No suspicious turns found.")
    else:
        # Phase ANALYZER-1: attribution columns. The
        # `our_active` / `opp_active` / `best_switch_target`
        # columns are now first-class; readers can see at
        # a glance whether the switch target is from our
        # bench or matches an opponent active.
        lines.append(
            "| battle | arm | turn | slot | kind | "
            "our_active | opp_active | chosen | "
            "best_switch_target | best_non_switch | "
            "delta | mirror |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for s in sorted_susp:
            attr = s.get("attribution", {}) or {}
            our_a = attr.get("our_active") or "-"
            opp_a = attr.get("opp_active") or "-"
            bs_t = (
                attr.get("best_switch_target") or "-"
            )
            bns = s.get("best_non_switch") or "-"
            mirror = (
                "Y" if attr.get(
                    "mirror_match_with_opp_active"
                ) else ""
            )
            lines.append(
                f"| {s.get('battle_tag', '?')} | "
                f"{s.get('arm', '?')} | "
                f"{s.get('turn', '?')} | "
                f"{s.get('slot', '?')} | "
                f"{s.get('kind', '?')} | "
                f"`{our_a}` | `{opp_a}` | "
                f"`{s.get('chosen', '?')}` | "
                f"`{bs_t}` | `{bns}` | "
                f"{s.get('delta', 0):.2f} | "
                f"{mirror} |"
            )
    lines.append("")
    lines.append("## Per-battle summary")
    lines.append("")
    if not per_battle:
        lines.append("No battles.")
    else:
        # Show first 20 battles
        lines.append("| battle | arm | won | turns | switches | pos_not_switched | neg_switched |")
        lines.append("|---|---|---|---|---|---|---|")
        for b in per_battle[:20]:
            lines.append(
                f"| `{b.get('battle_tag', '?')}` | "
                f"{b.get('arm', '?')} | "
                f"{b.get('won')} | "
                f"{b.get('turns', 0)} | "
                f"{b.get('switch_chosen_count', 0)} | "
                f"{b.get('positive_delta_not_switched_count', 0)} | "
                f"{b.get('negative_delta_switched_count', 0)} |"
            )
        if len(per_battle) > 20:
            lines.append(
                f"\n(showing first 20 of {len(per_battle)} battles)"
            )
    lines.append("")
    lines.append("## Recommendations")
    lines.append("")
    # Compute recommendations
    if delta_summary["count"] == 0:
        lines.append(
            "- No switch deltas available. The bot has no "
            "switch opportunities in the provided audit data. "
            "Consider whether the bot is over-attacking or "
            "whether the switch counterfactual is being "
            "populated correctly."
        )
    else:
        pos_count = quality["non_switch_positive_delta"]
        neg_count = quality["chosen_switch_negative_delta"]
        if pos_count > 0 and neg_count > 0:
            lines.append(
                f"- {pos_count} stay cases with positive delta "
                f"(bot could have switched and improved score)."
            )
            lines.append(
                f"- {neg_count} switch cases with negative delta "
                f"(bot switched and lost score)."
            )
            lines.append(
                "- These suggest the switch scoring may need "
                "tuning. Consider whether `enable_voluntary_switch_quality_scoring` "
                "is True and whether the scoring helpers are "
                "producing expected behavior."
            )
        elif pos_count == 0 and neg_count == 0:
            lines.append(
                "- All switch decisions appear consistent with "
                "the counterfactual. No immediate action needed."
            )
    lines.append("")
    lines.append("## Analyzer limitations")
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
        "- The `switch_counterfactual` sub-dict is per-slot, not "
        "per-turn. Both slots are aggregated."
    )
    lines.append(
        "- The `voluntary_switch` sub-dict (BI-1) is NOT used "
        "by this analyzer. It focuses on `switch_counterfactual`."
    )
    lines.append("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))


def _write_json(
    data: Dict[str, Any],
    delta_summary: Dict[str, float],
    top_n: int,
    json_path: str,
) -> None:
    """Phase SWITCH-2: write the JSON summary."""
    sorted_susp = sorted(
        data["top_suspicious"],
        key=lambda x: abs(x.get("delta", 0)),
        reverse=True,
    )[:top_n]
    out = {
        "counts": data["counts"],
        "opportunities": data["opportunities"],
        "delta_summary": delta_summary,
        "quality_summary": data["quality"],
        "state_summary": data["state"],
        "top_suspicious_turns": sorted_susp,
        "per_battle": data["per_battle"],
    }
    with open(json_path, "w") as f:
        json.dump(out, f, indent=2, default=str)


def main():
    parser = argparse.ArgumentParser(
        description="Phase SWITCH-2 — Read-only switch "
                    "outcome analyzer"
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
        "--min-delta", type=float, default=0.0,
        help="Minimum absolute delta to include. Default 0.0."
    )
    parser.add_argument(
        "--top-n", type=int, default=20,
        help="Top N suspicious turns to include. Default 20."
    )
    parser.add_argument(
        "--include-baseline", action="store_true",
        default=False,
        help="Include baseline arm rows. Default false "
             "(filter to treatment only)."
    )
    args = parser.parse_args()

    # Load all audit files.
    all_rows: List[Dict[str, Any]] = []
    for path in args.audit_jsonl:
        rows = _load_audit(path)
        all_rows.extend(rows)

    # Filter by arm if needed.
    if not args.include_baseline:
        all_rows = [
            r for r in all_rows
            if r.get("benchmark_arm") in ("treatment", "")
            or not r.get("benchmark_arm")
        ]

    if not all_rows:
        print("No rows found after filtering.", file=sys.stderr)
        sys.exit(1)

    data = _collect_slot_data(all_rows)
    delta_summary = _delta_summary(data["deltas"])

    _write_markdown(
        args.audit_jsonl,
        data,
        delta_summary,
        args.top_n,
        args.md,
    )
    print(f"Wrote markdown report: {args.md}")

    if args.json:
        _write_json(
            data,
            delta_summary,
            args.top_n,
            args.json,
        )
        print(f"Wrote JSON summary: {args.json}")


if __name__ == "__main__":
    main()