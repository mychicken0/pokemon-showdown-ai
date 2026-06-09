#!/usr/bin/env python3
"""Phase 6.3.7 — Dynamic Move Type Case Inspector."""
import json, os, argparse, sys

def main():
    p = argparse.ArgumentParser(description="Dynamic Move Type Inspector")
    p.add_argument("--dynamic", action="store_true")
    p.add_argument("--battle", type=str)
    p.add_argument("--filepath", type=str, default="logs/doubles_decision_audit.jsonl")
    p.add_argument("--limit", type=int, default=20)
    args = p.parse_args()
    if not os.path.exists(args.filepath):
        print(f"Error: {args.filepath} not found"); sys.exit(1)
    matched = []
    with open(args.filepath) as f:
        for line in f:
            if not line.strip(): continue
            try: rec = json.loads(line)
            except Exception: continue
            bt = rec.get("battle_tag",""); won = rec.get("won",False)
            if args.battle and args.battle != bt: continue
            for td in rec.get("audit_turns", []):
                for sk in ("slot_0","slot_1"):
                    s = td.get(sk,{})
                    if not s: continue
                    dyn = s.get("dynamic_move_type_applied", False)
                    eff = s.get("effective_move_type","")
                    decl = s.get("declared_move_type","")
                    if args.dynamic and not dyn: continue
                    if dyn or eff:
                        matched.append({
                            "bt":bt,"turn":td.get("turn",0),"slot":sk,"won":won,
                            "declared":decl,"effective":eff,
                            "source":s.get("effective_move_type_source",""),
                            "dynamic":dyn,"form":s.get("dynamic_move_type_form",""),
                            "selected":td.get("selected_joint_order","")[:60],
                        })
    if not matched:
        print("No dynamic type cases found."); return
    w = sum(1 for c in matched if c["won"]); l = sum(1 for c in matched if not c["won"])
    print(f"Found {len(matched)} cases ({w}W/{l}L)\n")
    for i, c in enumerate(matched[:args.limit],1):
        print(f"Case #{i}: {c['bt']} t{c['turn']} {c['slot']} {'WIN' if c['won'] else 'LOSS'}")
        print(f"  Declared: {c['declared']}  Effective: {c['effective']}  Source: {c['source']}")
        print(f"  Dynamic: {c['dynamic']}  Form: {c['form']}")
        print(f"  Selected: {c['selected']}")
        print()

if __name__ == "__main__":
    main()
