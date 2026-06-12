#!/usr/bin/env python3
"""Inspect voluntary switch quality cases from audit logs."""
import json
import os
import sys


def inspect_voluntary_switch_cases(
    filepath="logs/doubles_decision_audit.jsonl",
    show_selected=False,
    show_unnecessary=False,
    show_unsafe_candidate=False,
    show_double_threat=False,
    show_quad_weak=False,
    show_sacrifice_preferred=False,
    show_healthy_bench=False,
    show_repeat_switch=False,
    show_selection_changed=False,
    battle_filter=None,
    arm_filter=None,
):
    if not os.path.exists(filepath):
        print(f"Error: Log file not found at {filepath}")
        return

    found = 0
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                turn = json.loads(line)
            except json.JSONDecodeError:
                continue

            event = turn.get("event", "")
            if event not in ("decision", "") and "audit_turns" not in turn:
                # Maybe a battle record
                pass

            bt = str(turn.get("battle_tag", ""))
            if battle_filter and battle_filter not in bt:
                continue
            arm = turn.get("benchmark_arm", "")
            if arm_filter and arm_filter not in arm:
                continue

            for td in turn.get("audit_turns", []):
                turn_num = td.get("turn", 0)
                vsw_sel = td.get("voluntary_switch_selected", [False, False])
                vsw_eligible = td.get("voluntary_switch_decision_eligible", [False, False])
                vsw_species = td.get("voluntary_switch_selected_species", ["", ""])
                vsw_table = td.get("voluntary_switch_candidate_table", [[], []])
                vsw_sel_changed = td.get("voluntary_switch_selection_changed", [False, False])
                vsw_joint_changed = td.get("voluntary_switch_joint_selection_changed", False)

                for si in (0, 1):
                    selected = vsw_sel[si] if si < len(vsw_sel) else False
                    if show_selected and not selected:
                        continue
                    if show_selection_changed and not (vsw_sel_changed[si] if si < len(vsw_sel_changed) else False):
                        continue

                    table = vsw_table[si] if si < len(vsw_table) else []
                    sel_row = next((r for r in table if r.get("selected")), None)

                    # Evaluate filters
                    if show_unnecessary and sel_row:
                        if not (sel_row.get("active_has_useful_action", False) and
                                not sel_row.get("switch_improves_position", False)):
                            continue
                    if show_unsafe_candidate and sel_row:
                        if not sel_row.get("double_threat", False):
                            continue
                    if show_double_threat and sel_row:
                        if not sel_row.get("double_threat", False):
                            continue
                    if show_quad_weak and sel_row:
                        if not sel_row.get("quad_weak", False):
                            continue
                    if show_sacrifice_preferred and sel_row:
                        if not sel_row.get("sacrifice_preferred", False):
                            continue
                    if show_healthy_bench:
                        if not (sel_row and sel_row.get("active_low_hp", False) and
                                not selected and sel_row.get("active_has_useful_action", False)):
                            continue
                    if show_repeat_switch:
                        rep = False
                        for r in table:
                            if r.get("repeat_penalty", 0) > 0:
                                rep = True
                                break
                        if not rep:
                            continue

                    # Print case
                    print(f"--- {bt[:30]} turn={turn_num} slot=slot_{si} ---")
                    print(f"  Eligible: {vsw_eligible[si] if si < len(vsw_eligible) else False}")
                    print(f"  Selected: {selected}")
                    if sel_row:
                        print(f"  Species: {sel_row.get('species', '')}")
                        print(f"  HP: {sel_row.get('hp', 1.0):.2f}")
                        print(f"  Raw score: {sel_row.get('raw_switch_score', 0):.1f}")
                        print(f"  Adjusted: {sel_row.get('adjusted_switch_score', 0):.1f}")
                        print(f"  Adjustment: {sel_row.get('score_adjustment', 0):.1f}")
                        print(f"  Active risk: {sel_row.get('active_risk', 0):.1f}x")
                        print(f"  Candidate risk: {sel_row.get('candidate_risk', 0):.1f}x")
                        print(f"  Risk reduction: {sel_row.get('risk_reduction', 0):.1f}")
                        print(f"  Tempo penalty: {sel_row.get('tempo_penalty', 0):.1f}")
                        print(f"  Repeat penalty: {sel_row.get('repeat_penalty', 0):.1f}")
                        print(f"  Double threat: {sel_row.get('double_threat', False)}")
                        print(f"  Quad weak: {sel_row.get('quad_weak', False)}")
                        print(f"  Low HP candidate: {sel_row.get('low_hp', False)}")
                        print(f"  Best stay: {sel_row.get('best_stay_score', 0):.1f}")
                        print(f"  Has useful action: {sel_row.get('active_has_useful_action', False)}")
                        print(f"  Sacrifice preferred: {sel_row.get('sacrifice_preferred', False)}")
                        print(f"  Reason codes: {sel_row.get('reason_codes', [])}")
                    print(f"  Selection changed: {vsw_sel_changed[si] if si < len(vsw_sel_changed) else False}")
                    if vsw_joint_changed:
                        print(f"  Joint selection changed: True")
                    print()
                    found += 1

    if found == 0:
        print("No matching voluntary switch cases found.")
    else:
        print(f"Total matching cases: {found}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Inspect voluntary switch quality cases")
    parser.add_argument("--selected", action="store_true")
    parser.add_argument("--unnecessary", action="store_true")
    parser.add_argument("--unsafe-candidate", action="store_true")
    parser.add_argument("--double-threat", action="store_true")
    parser.add_argument("--quad-weak", action="store_true")
    parser.add_argument("--sacrifice-preferred", action="store_true")
    parser.add_argument("--healthy-bench-preserved", action="store_true")
    parser.add_argument("--repeat-switch", action="store_true")
    parser.add_argument("--selection-changed", action="store_true")
    parser.add_argument("--battle", dest="battle_filter")
    parser.add_argument("--arm", dest="arm_filter")
    parser.add_argument("--filepath", default="logs/doubles_decision_audit.jsonl")
    args = parser.parse_args()

    inspect_voluntary_switch_cases(
        filepath=args.filepath,
        show_selected=args.selected,
        show_unnecessary=args.unnecessary,
        show_unsafe_candidate=args.unsafe_candidate,
        show_double_threat=args.double_threat,
        show_quad_weak=args.quad_weak,
        show_sacrifice_preferred=args.sacrifice_preferred,
        show_healthy_bench=args.healthy_bench_preserved,
        show_repeat_switch=args.repeat_switch,
        show_selection_changed=args.selection_changed,
        battle_filter=args.battle_filter,
        arm_filter=args.arm_filter,
    )
