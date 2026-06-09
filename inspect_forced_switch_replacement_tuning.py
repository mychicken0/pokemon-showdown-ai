#!/usr/bin/env python3
"""Phase 6.4.4a — Forced Switch Replacement Safety Tuning Inspector.

Reads existing smoke JSONL/CSV artifacts to diagnose why Phase 6.4.4 smoke
did not improve enough.

Usage:
  python inspect_forced_switch_replacement_tuning.py --csv logs/forced_switch_replacement_safety_phase644_smoke.csv --filepath logs/forced_switch_replacement_safety_phase644_smoke_B.jsonl
  python inspect_forced_switch_replacement_tuning.py --filepath logs/forced_switch_replacement_safety_phase644_smoke_B.jsonl --selection-changed
  python inspect_forced_switch_replacement_tuning.py --filepath logs/forced_switch_replacement_safety_phase644_smoke_B.jsonl --worse-than-best
"""
import argparse
import json
import sys


def load_csv(path):
    """Load CSV summary."""
    import csv
    rows = []
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_cases(filepath, args):
    """Load and filter forced switch cases from JSONL."""
    cases = []
    with open(filepath) as f:
        for line in f:
            battle = json.loads(line)
            battle_tag = battle.get("battle_tag", "unknown")
            won = battle.get("won", False)
            for turn in battle.get("audit_turns", []):
                turn_num = turn.get("turn", 0)
                for slot_key in ("slot_0", "slot_1"):
                    slot = turn.get(slot_key, {})
                    if not slot.get("forced_switch"):
                        continue
                    if not slot.get("forced_switch_safety_enabled"):
                        continue

                    # Apply filters
                    if args.selection_changed and not slot.get("forced_switch_safety_selection_changed"):
                        continue
                    if args.selected_double_threat and not slot.get("forced_switch_selected_double_threat"):
                        continue
                    if args.selected_quad_weak and not slot.get("forced_switch_selected_quad_weak"):
                        continue
                    if args.fallback_used and not slot.get("forced_switch_order_fallback_used"):
                        continue
                    if args.worse_than_best:
                        sel_sc = slot.get("forced_switch_selected_safety_score", 0)
                        best_sc = slot.get("forced_switch_best_safety_score", 0)
                        if sel_sc >= best_sc:
                            continue
                    if args.battle and args.battle not in battle_tag:
                        continue

                    # Get opponent info
                    opp_active = turn.get("opp_active", [])
                    opp_info = []
                    for opp in opp_active:
                        if opp:
                            species = opp.get("species", "?")
                            types = opp.get("types", [])
                            opp_info.append(f"{species} ({'/'.join(types)})")

                    # Get candidate safety table if available
                    cand_table = slot.get("forced_switch_candidate_safety_table")

                    cases.append({
                        "battle_tag": battle_tag,
                        "turn": turn_num,
                        "slot": slot_key,
                        "won": won,
                        "selected_species": slot.get("forced_switch_selected_species", ""),
                        "selected_score": slot.get("forced_switch_selected_safety_score", 0),
                        "best_species": slot.get("forced_switch_best_safety_species", ""),
                        "best_score": slot.get("forced_switch_best_safety_score", 0),
                        "score_gap": slot.get("forced_switch_best_safety_score", 0) - slot.get("forced_switch_selected_safety_score", 0),
                        "selected_dt": slot.get("forced_switch_selected_double_threat", False),
                        "selected_qw": slot.get("forced_switch_selected_quad_weak", False),
                        "selection_changed": slot.get("forced_switch_safety_selection_changed", False),
                        "fallback_used": slot.get("forced_switch_order_fallback_used", False),
                        "candidate_count": slot.get("forced_switch_candidate_count", 0),
                        "reason": slot.get("forced_switch_reason", ""),
                        "opp_info": opp_info,
                        "candidate_table": cand_table,
                    })
    return cases


def main():
    parser = argparse.ArgumentParser(
        description="Phase 6.4.4a Forced Switch Replacement Safety Tuning Inspector"
    )
    parser.add_argument("--filepath", required=True, help="Path to JSONL audit file")
    parser.add_argument("--csv", help="Path to CSV summary file")
    parser.add_argument("--selection-changed", action="store_true")
    parser.add_argument("--selected-double-threat", action="store_true")
    parser.add_argument("--selected-quad-weak", action="store_true")
    parser.add_argument("--fallback-used", action="store_true")
    parser.add_argument("--worse-than-best", action="store_true")
    parser.add_argument("--battle", help="Filter by battle tag substring")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    # Show CSV summary if provided
    if args.csv:
        try:
            rows = load_csv(args.csv)
            print("=" * 80)
            print("CSV SUMMARY")
            print("=" * 80)
            for row in rows:
                print(f"  {row.get('name', '?'):30s} | FS={row.get('forced_switch_count', 0):>4s} | "
                      f"DT={row.get('forced_switch_selected_double_threat', 0):>3s} | "
                      f"QW={row.get('forced_switch_selected_quad_weak', 0):>3s} | "
                      f"Chg={row.get('forced_switch_safety_selection_changed', 0):>4s} | "
                      f"Gap={float(row.get('forced_switch_score_gap_sum', 0)) / max(int(row.get('forced_switch_score_gap_count', 1)), 1):.1f}")
            print()
        except Exception as e:
            print(f"Warning: Could not load CSV: {e}")

    # Load and display cases
    cases = load_cases(args.filepath, args)
    if not cases:
        print("No matching cases found.")
        return

    print("=" * 80)
    print(f"FORCED SWITCH CASES ({len(cases)} found, showing {min(len(cases), args.limit)})")
    print("=" * 80)

    # Aggregate stats
    total = len(cases)
    dt_count = sum(1 for c in cases if c["selected_dt"])
    qw_count = sum(1 for c in cases if c["selected_qw"])
    changed_count = sum(1 for c in cases if c["selection_changed"])
    worse_count = sum(1 for c in cases if c["score_gap"] > 0)
    gaps = [c["score_gap"] for c in cases if c["score_gap"] > 0]

    print(f"\nAggregate ({total} cases):")
    print(f"  Selected double-threat: {dt_count} ({100*dt_count/max(total,1):.1f}%)")
    print(f"  Selected quad-weak:     {qw_count} ({100*qw_count/max(total,1):.1f}%)")
    print(f"  Selection changed:      {changed_count} ({100*changed_count/max(total,1):.1f}%)")
    print(f"  Worse than best:        {worse_count} ({100*worse_count/max(total,1):.1f}%)")
    if gaps:
        print(f"  Avg gap (worse cases):  {sum(gaps)/len(gaps):.1f}")
        print(f"  Max gap:                {max(gaps):.1f}")

    # Top reasons
    all_reasons = []
    for c in cases:
        if c["reason"]:
            all_reasons.extend(c["reason"].split(","))
    if all_reasons:
        from collections import Counter
        reason_counts = Counter(all_reasons)
        print(f"\nTop reasons:")
        for reason, count in reason_counts.most_common(10):
            print(f"  {reason}: {count}")

    # Per-case details
    print(f"\n{'='*80}")
    print("PER-CASE DETAILS")
    print(f"{'='*80}")
    for i, c in enumerate(cases[:args.limit], 1):
        outcome = "WIN" if c["won"] else "LOSS"
        print(f"\n  {i}. [{c['battle_tag']}] Turn {c['turn']} {c['slot']} ({outcome})")
        print(f"     Opponents: {', '.join(c['opp_info']) if c['opp_info'] else '?'}")
        print(f"     Selected:  {c['selected_species']:20s} score={c['selected_score']:>8.1f}  DT={c['selected_dt']} QW={c['selected_qw']}")
        print(f"     Best:      {c['best_species']:20s} score={c['best_score']:>8.1f}")
        print(f"     Gap={c['score_gap']:.1f} Changed={c['selection_changed']} Fallback={c['fallback_used']} Cand={c['candidate_count']}")
        if c["reason"]:
            print(f"     Reasons: {c['reason']}")

        # Show candidate safety table if available
        if c["candidate_table"]:
            print(f"     Candidate safety table:")
            for entry in c["candidate_table"]:
                sp = entry.get("species", "?")
                sc = entry.get("score", 0)
                mult = entry.get("max_threat_multiplier", 1.0)
                reasons = entry.get("reasons", [])
                marker = " <-- selected" if sp == c["selected_species"] else ""
                marker += " <-- best" if sp == c["best_species"] else ""
                print(f"       {sp:20s} score={sc:>8.1f} mult={mult:.1f} reasons={','.join(reasons) if reasons else 'none'}{marker}")


if __name__ == "__main__":
    main()
