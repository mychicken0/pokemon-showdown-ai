#!/usr/bin/env python3
"""Phase 6.4.10b — Voluntary Switch Surface Probe Analyzer.

Reads the JSONL produced by
``bot_doubles_voluntary_switch_surface_probe.py``
and prints a per-format summary plus a verdict:

  - If any format has > 0 voluntary switch
    opportunities (i.e. ``n_voluntary_switches > 0``
    in a turn with the active alive and
    ``force_switch[slot] == False``), the runtime
    surface is proven. The analyzer recommends
    targeted bad-switch/good-switch qualification
    in that format.
  - If no format has any voluntary switch
    opportunities, the analyzer prints the exact
    reason and recommends moving to Protect/stall-loop
    safety next.

The analyzer is read-only and does not modify any
artifacts.
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def analyze(artifact_tag: str) -> Dict[str, Any]:
    jsonl_path = (
        f"logs/voluntary_switch_surface_{artifact_tag}.jsonl"
    )
    records = _read_jsonl(jsonl_path)
    if not records:
        print(f"ERROR: no records in {jsonl_path}")
        sys.exit(2)
    # Group by side (player).
    by_side: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_side[r.get("side", "")].append(r)
    # Per-format: side -> first 3 chars of side.
    by_format: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for side, recs in by_side.items():
        # side is like "VSWsurf_A1". Format label is
        # the 9th char: "A", "B", or "C".
        if len(side) >= 9:
            label = side[8]
        else:
            label = "?"
        by_format[label].extend(recs)
    report: Dict[str, Any] = {
        "artifact_tag": artifact_tag,
        "n_records": len(records),
        "formats": [],
    }
    for label in sorted(by_format.keys()):
        recs = by_format[label]
        n_slot_turns = len(recs)
        n_alive = sum(
            1 for r in recs
            if not r.get("active_fainted", False)
        )
        n_forced = sum(
            1 for r in recs
            if r.get("force_switch", False)
        )
        n_voluntary = sum(
            1 for r in recs
            if (
                not r.get("active_fainted", False)
                and not r.get("force_switch", False)
                and r.get("n_voluntary_switches", 0) > 0
            )
        )
        first_voluntary = None
        for r in recs:
            if (
                not r.get("active_fainted", False)
                and not r.get("force_switch", False)
                and r.get("n_voluntary_switches", 0) > 0
            ):
                first_voluntary = {
                    "battle_tag": r.get("battle_tag"),
                    "turn": r.get("turn"),
                    "slot": r.get("slot"),
                    "side": r.get("side"),
                    "active_species": r.get("active_species"),
                    "n_voluntary_switches": r.get(
                        "n_voluntary_switches"
                    ),
                    "switch_candidate_species": list(
                        r.get("switch_candidate_species", [])
                    ),
                }
                break
        report["formats"].append({
            "format_label": label,
            "n_records": n_slot_turns,
            "n_alive": n_alive,
            "n_forced": n_forced,
            "n_voluntary_opportunities": n_voluntary,
            "first_voluntary": first_voluntary,
        })
    return report


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Phase 6.4.10b voluntary switch surface probe analyzer"
        )
    )
    parser.add_argument(
        "--artifact-tag", type=str, required=True,
        help="Artifact tag to analyze",
    )
    parser.add_argument(
        "--md", type=str, default=None,
        help="Optional markdown output path.",
    )
    args = parser.parse_args()
    report = analyze(args.artifact_tag)
    print(
        f"Surface probe analysis: {report['n_records']} records "
        f"across {len(report['formats'])} formats"
    )
    for fmt in report["formats"]:
        print(
            f"  Format {fmt['format_label']}: "
            f"n_voluntary={fmt['n_voluntary_opportunities']} "
            f"n_forced={fmt['n_forced']} "
            f"n_alive={fmt['n_alive']}"
        )
        if fmt.get("first_voluntary"):
            print(
                f"    first_voluntary: "
                f"{fmt['first_voluntary']}"
            )
    has_voluntary = any(
        f["n_voluntary_opportunities"] > 0
        for f in report["formats"]
    )
    if has_voluntary:
        print(
            "\nVERDICT: voluntary switch surface IS proven in "
            "at least one format."
        )
        print(
            "  Next: run a targeted bad-switch/good-switch "
            "qualification in the format with the most "
            "opportunities."
        )
    else:
        print(
            "\nVERDICT: NO voluntary switch surface found in any "
            "tested format. The current poke-env engine with the "
            "available formats does NOT exercise voluntary "
            "switch orders in live play."
        )
        print(
            "  Next: move to Protect/stall-loop safety."
        )
    if args.md:
        with open(args.md, "w") as f:
            f.write(_format_md(report))


def _format_md(report: Dict[str, Any]) -> str:
    lines = [
        f"# Phase 6.4.10b Surface Probe Analyzer — "
        f"{report['artifact_tag']}",
        "",
        f"- n_records: {report['n_records']}",
        f"- n_formats: {len(report['formats'])}",
        "",
    ]
    for fmt in report["formats"]:
        lines.append(f"## Format {fmt['format_label']}")
        lines.append("")
        lines.append(f"- n_records: {fmt['n_records']}")
        lines.append(f"- n_alive: {fmt['n_alive']}")
        lines.append(f"- n_forced: {fmt['n_forced']}")
        lines.append(
            f"- n_voluntary_opportunities: "
            f"{fmt['n_voluntary_opportunities']}"
        )
        if fmt.get("first_voluntary"):
            lines.append(
                f"- first_voluntary: {fmt['first_voluntary']}"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
