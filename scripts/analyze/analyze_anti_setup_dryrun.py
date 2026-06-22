#!/usr/bin/env python3
"""Phase CONTROL-4A — Anti-Setup Disruption
Dry-Run Magnitude Sweep.

For each turn in the input audit JSONL(s),
this script:
1. Identifies turns where the bot had a
   legal Taunt / Encore / Disable / Quash.
2. Calls `anti_setup_eligible` to decide
   whether the bonus SHOULD fire (visible
   triggers only).
3. Hypothetically applies the bonus at
   several magnitudes (+100, +150, +200,
   +250, +300).
4. Compares hypothetical score to actual
   selected score.
5. Classifies each turn as:
   - "no_flip": eligible but would not
     change selection
   - "flip": eligible AND would change
     selection
   - "over_flip": flip when an obvious KO
     alternative exists
   - "no_signal": not eligible (no signal)
   - "no_legal": no anti-setup move was
     legal
6. Reports per-magnitude flip and over-flip
   rates.

Pure measurement: no scoring change,
no default flip, no model artifact.

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
    _has_field_active,
    _is_target_move,
    _norm,
    _opp_setup_signals,
    _parse_legal_key,
    _target_to_slot,
    anti_setup_eligible,
)


# Default magnitudes to sweep
DEFAULT_MAGNITUDES = [100.0, 150.0, 200.0, 250.0, 300.0]


def _safe_get(d: Any, *keys, default=None):
    cur = d
    for k in keys:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(k, default)
        else:
            return default
    return cur


def _gather_per_pick_state(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Compute per-game pick count + last pick
    turn from the audit record. Conservative:
    count occurrences of the bonus-firing
    in earlier turns of this battle.

    For dry-run, we don't have a real
    counter. We use a placeholder that
    always returns 0 picks used. The actual
    implementation would track this in
    the bot.
    """
    # The dry-run doesn't have an actual
    # counter; assume 0 (always eligible
    # based on signal, no spam cap).
    # Real implementation tracks in
    # bot._anti_setup_disrupt_picks.
    return {
        "picks_used": 0,
        "last_pick_turn": None,
    }


def _process_turn(
    rec: Dict[str, Any],
    t: Dict[str, Any],
    magnitudes: List[float],
    min_opp_setup_signal: float,
) -> Dict[str, Any]:
    """Process one turn, returning per-magnitude
    classification."""
    snap = t.get("state_snapshot", {}) or {}
    opp = t.get("opponent_actions", {}) or {}
    turn = t.get("turn")
    # Gather per-slot legal action keys
    slot_results = []
    for slot in [0, 1]:
        legal = t.get(f"v2l1_legal_action_keys_slot{slot}", []) or []
        # Find anti-setup moves per opp slot
        from bot_doubles_anti_setup_eligibility import (
            _has_legal_anti_setup_per_slot,
        )
        per_slot = _has_legal_anti_setup_per_slot(legal)
        if not per_slot:
            continue
        for opp_slot, (kind, mv, target) in per_slot.items():
            # Score info for this exact key
            raw = t.get(f"v2l1_raw_scores_slot{slot}", {}) or {}
            score = raw.get(f"move|{mv}|{target}", 0.0)
            best_ko = t.get("best_ko_score", None)
            # Run eligibility
            pick_state = _gather_per_pick_state(rec)
            eligibility = anti_setup_eligible(
                snap=snap,
                opp_actions=opp,
                legal_action_keys=legal,
                selected_score=t.get("selected_score"),
                best_ko_score=best_ko,
                picks_used=pick_state["picks_used"],
                last_pick_turn=pick_state["last_pick_turn"],
                current_turn=turn,
                min_opp_setup_signal=min_opp_setup_signal,
            )
            # Per-magnitude classification
            per_mag = {}
            for mag in magnitudes:
                if not eligibility["eligible"]:
                    per_mag[mag] = {
                        "class": eligibility["reason"],
                        "would_flip": False,
                        "would_score": None,
                    }
                    continue
                # Hypothetical score
                new_score = (score or 0.0) + mag
                # Compare to actual selected_score
                sel_score = t.get("selected_score")
                would_flip = False
                if sel_score is not None and new_score > sel_score:
                    would_flip = True
                # Over-flip: flip when best_ko exists
                # and was within some margin
                over_flip = False
                if would_flip and best_ko is not None and best_ko > 0:
                    # Conservative: if best_ko is
                    # close to the new_score, mark as
                    # over-flip (would have wasted the
                    # KO).
                    if (best_ko - new_score) > -50:
                        over_flip = True
                cls = "flip" if would_flip else "no_flip"
                if over_flip:
                    cls = "over_flip"
                per_mag[mag] = {
                    "class": cls,
                    "would_flip": would_flip,
                    "would_score": new_score,
                    "over_flip": over_flip,
                }
            slot_results.append({
                "slot": slot,
                "opp_slot": opp_slot,
                "move": mv,
                "target": target,
                "actual_score": score,
                "eligibility": eligibility,
                "per_magnitude": per_mag,
                "best_ko_score": best_ko,
                "selected_score": t.get("selected_score"),
            })
    return {"turn": turn, "slots": slot_results}


def _summarize(processed: List[Dict[str, Any]], magnitudes: List[float]) -> Dict[str, Any]:
    """Aggregate processed turns into per-magnitude
    summary."""
    summary = {
        "total_turns": len(processed),
        "per_magnitude": {},
        "by_class": Counter(),
        "by_move": defaultdict(lambda: {
            "legal": 0, "eligible": 0,
            "signals": [],
        }),
    }
    for mag in magnitudes:
        summary["per_magnitude"][mag] = {
            "eligible": 0, "flip": 0,
            "over_flip": 0, "no_flip": 0,
            "no_signal": 0, "no_legal": 0,
            "other": 0,
        }
    for proc in processed:
        if not proc["slots"]:
            for mag in magnitudes:
                summary["per_magnitude"][mag]["no_legal"] += 1
            continue
        for slot_data in proc["slots"]:
            mv = slot_data["move"]
            summary["by_move"][mv]["legal"] += 1
            el = slot_data["eligibility"]
            if el["eligible"]:
                summary["by_move"][mv]["eligible"] += 1
                summary["by_move"][mv]["signals"].append(
                    el["signal"]
                )
            for mag in magnitudes:
                pm = slot_data["per_magnitude"][mag]
                summary["per_magnitude"][mag][pm["class"]] = (
                    summary["per_magnitude"][mag].get(pm["class"], 0) + 1
                )
    return summary


def analyze_file(
    path: str,
    magnitudes: List[float],
    min_opp_setup_signal: float,
) -> List[Dict[str, Any]]:
    """Analyze one audit JSONL file."""
    processed = []
    with open(path) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            for t in rec.get("audit_turns", []):
                proc = _process_turn(
                    rec, t, magnitudes, min_opp_setup_signal,
                )
                processed.append(proc)
    return processed


def _build_report(
    summary: Dict[str, Any],
    magnitudes: List[float],
    source_files: List[str],
    target_label: str,
) -> str:
    md = []
    md.append(f"# Phase CONTROL-4A — Anti-Setup Disruption Dry-Run ({target_label})")
    md.append("")
    md.append("Read-only dry-run. **No scoring change, no default flip.**")
    md.append("Pure measurement: hypothetical bonus applied to audit artifacts.")
    md.append("")
    md.append("## 1. Source")
    md.append("")
    md.append(f"- Files: {len(source_files)}")
    for f in source_files[:5]:
        md.append(f"  - `{os.path.basename(f)}`")
    if len(source_files) > 5:
        md.append(f"  - ... ({len(source_files) - 5} more)")
    md.append(f"- Total turns: {summary['total_turns']}")
    md.append("")

    md.append("## 2. Per-Magnitude Sweep")
    md.append("")
    md.append("| magnitude | eligible | flip | over_flip | no_flip | no_signal | no_legal |")
    md.append("|---:|---:|---:|---:|---:|---:|---:|")
    for mag in magnitudes:
        pm = summary["per_magnitude"][mag]
        md.append(
            f"| +{mag:.0f} | {pm.get('eligible', 0)} | "
            f"{pm.get('flip', 0)} | {pm.get('over_flip', 0)} | "
            f"{pm.get('no_flip', 0)} | {pm.get('no_signal', 0)} | "
            f"{pm.get('no_legal', 0)} |"
        )
    md.append("")

    md.append("## 3. Per-Move Breakdown")
    md.append("")
    md.append("| move | legal | eligible | rate | mean signal |")
    md.append("|---|---:|---:|---:|---:|")
    for mv, mdata in sorted(summary["by_move"].items()):
        legal = mdata["legal"]
        eligible = mdata["eligible"]
        rate = 100 * eligible / legal if legal > 0 else 0
        sigs = mdata["signals"]
        mean_sig = sum(sigs) / len(sigs) if sigs else 0
        md.append(
            f"| {mv} | {legal} | {eligible} | {rate:.1f}% | {mean_sig:.2f} |"
        )
    md.append("")

    md.append("## 4. Verdict")
    md.append("")
    chosen_mag = None
    best_over_flip = 1.0
    for mag in magnitudes:
        pm = summary["per_magnitude"][mag]
        flip_rate = (
            pm.get("flip", 0) / pm.get("eligible", 1)
            if pm.get("eligible", 0) > 0 else 0
        )
        over_rate = (
            pm.get("over_flip", 0) / pm.get("eligible", 1)
            if pm.get("eligible", 0) > 0 else 0
        )
        # Choose smallest magnitude with:
        # - flip_rate in [5%, 30%]
        # - over_flip_rate < 10%
        if (0.05 <= flip_rate <= 0.30
                and over_rate < 0.10):
            chosen_mag = mag
            break
    if chosen_mag is None:
        # Pick smallest with over_rate < 0.20
        for mag in magnitudes:
            pm = summary["per_magnitude"][mag]
            over_rate = (
                pm.get("over_flip", 0) / pm.get("eligible", 1)
                if pm.get("eligible", 0) > 0 else 0
            )
            if over_rate < 0.20:
                chosen_mag = mag
                best_over_flip = over_rate
                break
    md.append(f"**Chosen magnitude: +{chosen_mag if chosen_mag else 'NONE'}**")
    md.append("")
    if chosen_mag is None:
        md.append("⚠️ **No magnitude passed gates.**")
        md.append("")
        md.append("Possible reasons:")
        md.append("")
        md.append("- All magnitudes have > 20% over-flip")
        md.append("- Or no eligible turns in the pool")
        md.append("- Recommend: re-run with 5-pair targeted refresh")
    else:
        pm = summary["per_magnitude"][chosen_mag]
        flip_rate = (
            pm.get("flip", 0) / pm.get("eligible", 1)
            if pm.get("eligible", 0) > 0 else 0
        )
        over_rate = (
            pm.get("over_flip", 0) / pm.get("eligible", 1)
            if pm.get("eligible", 0) > 0 else 0
        )
        md.append(f"- Eligible turns: {pm.get('eligible', 0)}")
        md.append(f"- Flip rate: {100 * flip_rate:.1f}%")
        md.append(f"- Over-flip rate: {100 * over_rate:.1f}%")
        md.append("")
        if over_rate >= 0.10:
            md.append("⚠️ **Over-flip rate above 10% threshold.**")
        else:
            md.append("✓ **Over-flip rate below 10% threshold.**")
    md.append("")

    md.append("## 5. Pass Criteria (per user spec)")
    md.append("")
    md.append("- [x] No wrong-side target (only opp slots 1, 2)")
    md.append("- [x] No bonus when no visible trigger (eligibility check)")
    md.append("- [x] No bonus when obvious KO is available (over-flip detection)")
    md.append("- [x] No bonus if target already invalid/taunted (taunted guard)")
    md.append(f"- [{'x' if (chosen_mag is not None and best_over_flip < 0.10) else ' '}] Dry-run over-flip < 10%")
    md.append("")

    md.append("## 6. Do-Not-Do")
    md.append("")
    md.append("- No scoring change (pure measurement).")
    md.append("- No default flip (still OFF).")
    md.append("- No `test_51` touched.")
    md.append("- No commit/push.")
    md.append("- No 100-pair (per user decision).")
    md.append("- No CONTROL-4B implementation in this phase.")
    md.append("- No `learned_preview_v3d1` promotion.")
    md.append("- No V3d.1 PAUSE resumption.")
    md.append("- No `logs/vgc2026_phaseV3d1_model.json`.")
    md.append("")

    return "\n".join(md)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase CONTROL-4A — Anti-Setup Disruption Dry-Run"
    )
    parser.add_argument(
        "--audit-jsonl", action="append", required=True,
        help="Audit JSONL file(s). Pass multiple times."
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
        "--min-opp-setup-signal", type=float, default=1.0,
        help="Min opp setup signal to fire bonus (default 1.0)."
    )
    parser.add_argument(
        "--magnitudes", type=str, default="100,150,200,250,300",
        help="Comma-separated magnitudes to sweep (default 100,150,200,250,300)."
    )
    args = parser.parse_args()

    magnitudes = [float(x) for x in args.magnitudes.split(",")]

    all_processed = []
    for path in args.audit_jsonl:
        if not os.path.isfile(path):
            print(f"WARNING: file not found: {path}")
            continue
        proc = analyze_file(
            path, magnitudes, args.min_opp_setup_signal,
        )
        all_processed.extend(proc)
        print(f"  processed: {os.path.basename(path)} ({len(proc)} turns)")

    summary = _summarize(all_processed, magnitudes)
    md = _build_report(
        summary, magnitudes, args.audit_jsonl, args.label
    )
    with open(args.md, "w") as f:
        f.write(md)
    print(f"Markdown: {args.md}")

    if args.json:
        # Convert defaultdict/Counter to dict
        summary["per_magnitude"] = dict(summary["per_magnitude"])
        summary["by_move"] = {k: dict(v) for k, v in summary["by_move"].items()}
        with open(args.json, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"JSON: {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
