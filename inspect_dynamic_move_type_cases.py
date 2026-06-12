#!/usr/bin/env python3
"""Phase 6.3.7l.1 — Dynamic Move Type Case Inspector with absorb filters and attacker metadata."""
import json, os, argparse, sys

def main():
    p = argparse.ArgumentParser(description="Dynamic Move Type Inspector")
    p.add_argument("--dynamic", action="store_true")
    p.add_argument("--candidate-blocked", action="store_true")
    p.add_argument("--selected", action="store_true")
    p.add_argument("--avoided", action="store_true")
    p.add_argument("--reason", type=str)
    p.add_argument("--form", type=str)
    p.add_argument("--battle", type=str)
    p.add_argument("--filepath", type=str, default="logs/doubles_decision_audit.jsonl")
    p.add_argument("--limit", type=int, default=20)
    args = p.parse_args()
    if not os.path.exists(args.filepath):
        print(f"Error: {args.filepath} not found"); sys.exit(1)
    has_absorb_filter = args.candidate_blocked or args.selected or args.avoided
    matched = []
    with open(args.filepath) as f:
        for line in f:
            if not line.strip(): continue
            try: rec = json.loads(line)
            except Exception: continue
            bt = rec.get("battle_tag",""); won = rec.get("won",False)
            if args.battle and args.battle != bt: continue
            for td in rec.get("audit_turns", []):
                our_active = td.get("our_active", [{}, {}])
                for sk_idx, sk in enumerate(("slot_0","slot_1")):
                    s = td.get(sk,{})
                    if not s: continue
                    dyn = s.get("dynamic_move_type_applied", False)
                    eff = s.get("effective_move_type","")
                    decl = s.get("declared_move_type","")

                    if args.dynamic and not dyn: continue
                    if args.candidate_blocked and not s.get("dynamic_type_absorb_candidate_blocked", False): continue
                    if args.selected and not s.get("dynamic_type_absorb_selected", False): continue
                    if args.avoided and not s.get("dynamic_type_absorb_avoided", False): continue
                    if args.reason and s.get("dynamic_type_absorb_reason","") != args.reason: continue
                    if args.form and s.get("dynamic_move_type_form","") != args.form: continue

                    if has_absorb_filter:
                        show = (s.get("dynamic_type_absorb_candidate_blocked", False)
                                or s.get("dynamic_type_absorb_selected", False)
                                or s.get("dynamic_type_absorb_avoided", False))
                    else:
                        show = dyn or s.get("dynamic_type_absorb_candidate_blocked", False)

                    if not show: continue

                    attacker = ""
                    try:
                        a_entry = our_active[sk_idx] if sk_idx < len(our_active) else None
                        attacker = a_entry.get("species", "") if isinstance(a_entry, dict) else ""
                    except Exception:
                        pass

                    matched.append({
                        "bt":bt,"turn":td.get("turn",0),"slot":sk,"won":won,
                        "attacker": attacker,
                        "declared":decl,"effective":eff,
                        "source":s.get("effective_move_type_source",""),
                        "dynamic":dyn,"form":s.get("dynamic_move_type_form",""),
                        "selected":td.get("selected_joint_order","")[:80],
                        "candidate_blocked": s.get("dynamic_type_absorb_candidate_blocked", False),
                        "absorb_selected": s.get("dynamic_type_absorb_selected", False),
                        "absorb_avoided": s.get("dynamic_type_absorb_avoided", False),
                        "reason": s.get("dynamic_type_absorb_reason", ""),
                        "target_species": s.get("dynamic_type_absorb_target_species", ""),
                        "target_ability": s.get("dynamic_type_absorb_target_ability", ""),
                        "blocked_move": s.get("dynamic_type_absorb_blocked_move_id", ""),
                        "blocked_score": s.get("dynamic_type_absorb_blocked_candidate_score", 0.0),
                    })
    if not matched:
        print("No dynamic type cases found."); return
    w = sum(1 for c in matched if c["won"]); l = sum(1 for c in matched if not c["won"])
    print(f"Found {len(matched)} cases ({w}W/{l}L)\n")
    for i, c in enumerate(matched[:args.limit],1):
        status = "SELECTED" if c["absorb_selected"] else "AVOIDED" if c["absorb_avoided"] else "UNSET"
        print(f"Case #{i}: {c['bt']} t{c['turn']} {c['slot']} {'WIN' if c['won'] else 'LOSS'} {status}")
        print(f"  Attacker: {c['attacker']}")
        print(f"  Declared: {c['declared']}  Effective: {c['effective']}  Source: {c['source']}")
        print(f"  Dynamic: {c['dynamic']}  Form: {c['form']}")
        if c["candidate_blocked"]:
            print(f"  Absorb: candidate_blocked reason={c['reason']} target={c['target_species']} ability={c['target_ability']}")
            print(f"  Blocked move: {c['blocked_move']}  score={c['blocked_score']}")
        print(f"  Selected: {c['selected']}")
        print()

if __name__ == "__main__":
    main()
