#!/usr/bin/env python3
"""Phase 6.4.7b — Stat-Drop Pressure Quality Inspector.

Detailed inspection of pressure-active cases showing scores, gaps, and actions.
"""
import json, os, argparse, sys


def main():
    parser = argparse.ArgumentParser(description="Stat-Drop Pressure Quality Inspector")
    parser.add_argument("--filepath", type=str, required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--pressure-active", action="store_true")
    parser.add_argument("--switch-selected", action="store_true")
    parser.add_argument("--stayed-unproductive", action="store_true")
    parser.add_argument("--selection-changed", action="store_true")
    parser.add_argument("--offensive", action="store_true")
    parser.add_argument("--losses-only", action="store_true")
    parser.add_argument("--wins-only", action="store_true")
    parser.add_argument("--battle", type=str)
    parser.add_argument("--turn", type=int, default=None)
    args = parser.parse_args()

    if not os.path.exists(args.filepath):
        print(f"Error: {args.filepath} not found")
        sys.exit(1)

    matched = []
    with open(args.filepath) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            bt = rec.get("battle_tag", "Unknown")
            if args.battle and args.battle != bt:
                continue
            won = rec.get("won", False)
            for td in rec.get("audit_turns", []):
                turn = td.get("turn", 0)
                if args.turn is not None and turn != args.turn:
                    continue
                for sk in ("slot_0", "slot_1"):
                    s = td.get(sk, {})
                    if not s:
                        continue
                    if not s.get("stat_drop_switch_pressure_active"):
                        continue
                    match = False
                    if args.pressure_active:
                        match = True
                    elif args.switch_selected and s.get("stat_drop_switch_selected"):
                        match = True
                    elif args.stayed_unproductive and s.get("stat_drop_switch_stayed_unproductive"):
                        match = True
                    elif args.selection_changed and s.get("stat_drop_switch_selection_changed"):
                        match = True
                    elif args.offensive and "offensive" in s.get("stat_drop_switch_pressure_categories", []):
                        match = True
                    else:
                        match = True

                    if not match:
                        continue
                    if args.losses_only and won:
                        continue
                    if args.wins_only and not won:
                        continue

                    best_sw = s.get("stat_drop_switch_best_switch_score", 0)
                    best_ns = s.get("stat_drop_switch_best_non_switch_score", 0)
                    gap = best_sw - best_ns

                    sw_sel = s.get("stat_drop_switch_selected", False)
                    unprod = s.get("stat_drop_switch_stayed_unproductive", False)
                    stayed_prod = s.get("stat_drop_switch_stayed_productive", False)
                    changed = s.get("stat_drop_switch_selection_changed", False)

                    # Determine action type from selected order
                    sel = td.get("selected_joint_order", "")
                    act_type = "unknown"
                    if "switch" in sel.lower():
                        parts = sel.replace("/choose ", "").split(", ")
                        for p in parts:
                            if sk == "slot_0" and p.strip().startswith("switch") and parts[0].strip() == p.strip():
                                act_type = "switch"
                                break
                            if sk == "slot_1" and p.strip().startswith("switch"):
                                # check if it's the second part
                                if len(parts) > 1 and parts[1].strip().startswith("switch"):
                                    act_type = "switch"
                                    break
                    if act_type == "unknown":
                        if "move" in sel.lower():
                            act_type = "damaging"
                        elif "protect" in sel.lower() or "detect" in sel.lower():
                            act_type = "protect"
                        elif "pass" in sel.lower():
                            act_type = "pass"

                    matched.append({
                        "battle_tag": bt, "turn": turn, "slot": sk,
                        "won": won, "action": sel[:70],
                        "action_type": act_type,
                        "switch_selected": sw_sel,
                        "stayed_unproductive": unprod,
                        "stayed_productive": stayed_prod,
                        "selection_changed": changed,
                        "categories": s.get("stat_drop_switch_pressure_categories", []),
                        "threshold_source": s.get("stat_drop_switch_threshold_source", ""),
                        "best_switch_species": s.get("stat_drop_switch_best_switch_species", ""),
                        "best_switch_score": best_sw,
                        "best_non_switch_score": best_ns,
                        "gap": gap,
                        "pressure_score": s.get("stat_drop_switch_pressure_score", 0),
                        "reason": s.get("stat_drop_switch_reason", ""),
                        "scoring_enabled": s.get("stat_drop_switch_scoring_enabled", False),
                    })

    if not matched:
        print("No matching pressure cases.")
        return

    wins = sum(1 for c in matched if c["won"])
    losses = sum(1 for c in matched if not c["won"])
    sw_count = sum(1 for c in matched if c["switch_selected"])
    unprod_count = sum(1 for c in matched if c["stayed_unproductive"])
    changed_count = sum(1 for c in matched if c["selection_changed"])

    avg_sw = sum(c["best_switch_score"] for c in matched) / len(matched)
    avg_ns = sum(c["best_non_switch_score"] for c in matched) / len(matched)
    avg_gap = sum(c["gap"] for c in matched) / len(matched)

    print(f"Found {len(matched)} pressure cases ({wins}W/{losses}L)")
    print(f"  switch_selected: {sw_count}/{len(matched)}")
    print(f"  stayed_unproductive: {unprod_count}/{len(matched)}")
    print(f"  selection_changed: {changed_count}/{len(matched)}")
    print(f"  avg best_switch_score: {avg_sw:.1f}")
    print(f"  avg best_non_switch_score: {avg_ns:.1f}")
    print(f"  avg gap (sw - ns): {avg_gap:.1f}")
    print()

    # Action type split
    from collections import Counter
    act_counts = Counter(c["action_type"] for c in matched)
    print(f"  Action type split: {dict(act_counts)}")

    # Negative gap vs positive gap
    neg_gap = [c for c in matched if c["gap"] < 0]
    pos_gap = [c for c in matched if c["gap"] > 0]
    print(f"  Negative gap (switch < non-switch): {len(neg_gap)}")
    print(f"  Positive gap (switch > non-switch): {len(pos_gap)}")
    print()

    for i, c in enumerate(matched[:args.limit], 1):
        print(f"Case #{i}:")
        print(f"  Battle       : {c['battle_tag']}")
        print(f"  Turn         : {c['turn']}  Slot: {c['slot']}")
        print(f"  Outcome      : {'WIN' if c['won'] else 'LOSS'}")
        print(f"  Selected     : {c['action']}")
        print(f"  Action Type  : {c['action_type']}")
        print(f"  Switch Sel?  : {c['switch_selected']}  Unprod? : {c['stayed_unproductive']}")
        print(f"  Changed?     : {c['selection_changed']}")
        print(f"  Categories   : {c['categories']}  Source: {c['threshold_source']}")
        print(f"  Best Switch  : {c['best_switch_species']} ({c['best_switch_score']:.1f})")
        print(f"  Best Non-Sw  : {c['best_non_switch_score']:.1f}")
        print(f"  Gap (Sw-NS)  : {c['gap']:.1f}")
        print(f"  Pressure     : {c['pressure_score']:.1f}")
        print(f"  Scoring On?  : {c['scoring_enabled']}")
        print(f"  Reason       : {c['reason'][:100]}")
        print()


if __name__ == "__main__":
    main()
