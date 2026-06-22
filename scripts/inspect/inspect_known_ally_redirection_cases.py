#!/usr/bin/env python3
"""Phase 6.3.6b — Known Ally Redirection Case Inspector."""
import json, os, argparse, sys

def main():
    p = argparse.ArgumentParser(description="Known Ally Redirection Inspector")
    p.add_argument("--selected", action="store_true")
    p.add_argument("--avoidable", action="store_true")
    p.add_argument("--only-legal", action="store_true")
    p.add_argument("--avoided", action="store_true")
    p.add_argument("--repeat", action="store_true")
    p.add_argument("--storm-drain", action="store_true")
    p.add_argument("--lightning-rod", action="store_true")
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
                turn = td.get("turn",0)
                for sk in ("slot_0","slot_1"):
                    s = td.get(sk,{})
                    if not s: continue
                    sel = s.get("known_ally_redirection_selected",False)
                    reason = s.get("known_ally_redirection_reason","")
                    match = False
                    if args.selected and sel: match = True
                    elif args.avoidable and sel and s.get("known_ally_redirection_safe_alternative_available",False): match = True
                    elif args.only_legal and sel and s.get("known_ally_redirection_only_legal",False): match = True
                    elif args.avoided and s.get("known_ally_redirection_avoided",False): match = True
                    elif args.repeat and s.get("known_ally_redirection_repeat_selected",False): match = True
                    elif args.storm_drain and "stormdrain" in reason: match = True
                    elif args.lightning_rod and "lightningrod" in reason: match = True
                    elif not any([args.selected,args.avoidable,args.only_legal,args.avoided,args.repeat,args.storm_drain,args.lightning_rod]):
                        if sel or s.get("known_ally_redirection_avoided",False): match = True
                    if match:
                        matched.append({
                            "bt":bt,"turn":turn,"slot":sk,"won":won,
                            "sel":sel,"avoided":s.get("known_ally_redirection_avoided",False),
                            "only_legal":s.get("known_ally_redirection_only_legal",False),
                            "repeat":s.get("known_ally_redirection_repeat_selected",False),
                            "reason":reason,
                            "ally":s.get("known_ally_redirection_ally_species",""),
                            "ally_ability":s.get("known_ally_redirection_ally_ability",""),
                            "move":s.get("known_ally_redirection_move_id",""),
                            "known_before":s.get("known_ally_redirection_known_before_decision",False),
                            "safe_alt":s.get("known_ally_redirection_safe_alternative_available",False),
                            "order":td.get("selected_joint_order","")[:60],
                            "score":td.get("selected_score",0),
                            "opportunity":s.get("known_ally_redirection_opportunity_observed",False),
                            "blocked_move":s.get("known_ally_redirection_blocked_candidate_move_id",""),
                            "blocked_attacker":s.get("known_ally_redirection_blocked_candidate_attacker_species",""),
                            "blocked_target":s.get("known_ally_redirection_blocked_candidate_target_species",""),
                            "blocked_ally":s.get("known_ally_redirection_blocked_candidate_ally_species",""),
                            "blocked_ally_ab":s.get("known_ally_redirection_blocked_candidate_ally_ability",""),
                            "blocked_reason":s.get("known_ally_redirection_blocked_candidate_reason",""),
                            "blocked_known_before":s.get("known_ally_redirection_blocked_candidate_known_before",False),
                            "blocked_score":s.get("known_ally_redirection_blocked_candidate_score",0.0),
                            "best_safe_alt":s.get("known_ally_redirection_best_safe_alternative",""),
                            "best_safe_alt_score":s.get("known_ally_redirection_best_safe_alternative_score",0.0),
                        })
    if not matched:
        print("No matching cases."); return
    w = sum(1 for c in matched if c["won"]); l = sum(1 for c in matched if not c["won"])
    print(f"Found {len(matched)} cases ({w}W/{l}L)\n")
    for i, c in enumerate(matched[:args.limit],1):
        print(f"Case #{i}:")
        print(f"  Battle: {c['bt']}  Turn: {c['turn']}  {c['slot']}  {'WIN' if c['won'] else 'LOSS'}")
        print(f"  Selected: {c['order']}")
        print(f"  Redir Selected: {c['sel']}  Avoided: {c['avoided']}  Only-Legal: {c['only_legal']}  Repeat: {c['repeat']}")
        print(f"  Move: {c['move']}  Ally: {c['ally']} ({c['ally_ability']})")
        print(f"  Known Before: {c['known_before']}  Reason: {c['reason']}")
        print(f"  Safe Alt Available: {c['safe_alt']}  Score: {c['score']:.1f}")
        if c.get("opportunity") or c.get("blocked_move"):
            print(f"  Blocked Candidate: {c['blocked_move']} {c['blocked_attacker']}->{c['blocked_target']}")
            print(f"    Ally: {c['blocked_ally']} ({c['blocked_ally_ab']}) KnownBefore: {c['blocked_known_before']}")
            print(f"    Reason: {c['blocked_reason']}  Score: {c['blocked_score']:.1f}")
            print(f"    Best Safe Alt: {c['best_safe_alt']} ({c['best_safe_alt_score']:.1f})")
        print()

if __name__ == "__main__":
    main()
