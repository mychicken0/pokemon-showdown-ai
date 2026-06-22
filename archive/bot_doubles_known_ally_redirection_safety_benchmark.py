#!/usr/bin/env python3
"""Phase 6.3.6b.5 — Corrected Known Ally Redirection Smoke Qualification.

Arms (100/100/100/50):
  A) Safety OFF vs Basic
  B) Safety ON vs Basic
  C) Safety ON vs OFF
  D) Safety ON vs SafeRandom

Artifact tag: phase636b5_corrected_ally_redirection_smoke
"""
import asyncio, csv, json, os, random, sys, time
sys.path.insert(0, os.path.dirname(__file__))
import atexit
import poke_env.concurrency
_clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if _clear_loop is not None:
    try: atexit.unregister(_clear_loop)
    except Exception: pass

from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer
from bot_doubles_safe_random import DoublesSafeRandomPlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

MAX_CONCURRENT = 15; STALL_TIMEOUT = 180; HEARTBEAT_INTERVAL = 30

class StallError(Exception): pass

async def _cleanup(p):
    try:
        if hasattr(p, "ps_client") and hasattr(p.ps_client, "_stop_listening"):
            await p.ps_client._stop_listening()
    except Exception: pass

async def _run_arm(name, bf, hf, timeout):
    bt = asyncio.create_task(bf()); wt = asyncio.create_task(hf()); exc = None
    try:
        done, _ = await asyncio.wait_for(asyncio.wait({bt, wt}, return_when=asyncio.FIRST_COMPLETED), timeout=timeout)
        for t in (bt, wt):
            if t in done and not t.cancelled():
                e = t.exception()
                if e and not isinstance(e, asyncio.CancelledError): raise e
    except asyncio.TimeoutError: exc = f"TIMEOUT {timeout}s"
    except StallError as e: exc = str(e)
    except Exception as e: exc = f"{type(e).__name__}: {e}"
    finally:
        for t in (wt, bt):
            if t and not t.done(): t.cancel()
        for t in (wt, bt):
            if t:
                try: await t
                except (asyncio.CancelledError, Exception): pass
    return ("ok" if exc is None else "error"), exc

async def run_matchup(name, config, opp_cls, opp_cfg, n, log_path, arm=""):
    if opp_cls == "basic": Opp = DoublesBasicAwarePlayer
    elif opp_cls == "safe_random": Opp = DoublesSafeRandomPlayer
    else: Opp = DoublesDamageAwarePlayer
    suf = random.randint(10000, 99999)
    bn = f"SinB_{name.replace(' ','_')[:8]}_{suf}"[:18]
    on = f"Opp_{name.replace(' ','_')[:8]}_{suf}"[:18]
    al = DoublesDecisionAuditLogger(filepath=log_path, reset=True, detail_level="top5", benchmark_arm=arm,
        singleton_safety_enabled=bool(getattr(config,"ability_hard_safety_allow_singleton_deduction",False)),
        priority_safety_enabled=bool(getattr(config,"enable_priority_field_hard_safety",False)))
    p = DoublesDamageAwarePlayer(account_configuration=AccountConfiguration(bn,None), verbose=False, config=config,
        audit_logger=al, max_concurrent_battles=MAX_CONCURRENT)
    if opp_cls == "mirror":
        o = Opp(account_configuration=AccountConfiguration(on,None), verbose=False, config=opp_cfg, max_concurrent_battles=MAX_CONCURRENT)
    else:
        o = Opp(account_configuration=AccountConfiguration(on,None), verbose=False, max_concurrent_battles=MAX_CONCURRENT)
    print(f"\n---> {name}: {n}")
    st = time.time(); state = {"last": st, "fin": 0}
    async def hb():
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            el = time.time()-st; f = p.n_finished_battles
            w = p.n_won_battles; l_ = o.n_won_battles if hasattr(o,'n_won_battles') else 0
            sl = time.time()-state["last"]
            if f > state["fin"]: state["last"] = time.time(); state["fin"] = f
            print(f"  [{name}] {el:.0f}s | {f}/{n} | {w}W {l_}L | {sl:.0f}s since")
            if sl > STALL_TIMEOUT: raise StallError(f"Stall: {name}")
    async def run(): return await p.battle_against(o, n_battles=n)
    status, exc = await _run_arm(name, run, hb, 1800)
    res = _result(name, n, p, o, status, log_path, arm)
    if exc: res["err"] = exc
    await _cleanup(p); await _cleanup(o)
    if status != "ok": print(f"  [{name}] {status.upper()}: {exc}")
    return res

def _count(log_path):
    m = {
        "candidate_blocked": 0, "selected": 0, "selected_known_before": 0,
        "selected_revealed_after": 0, "our_error": 0, "opponent_error": 0,
        "avoided": 0, "avoidable_selected": 0, "only_legal": 0,
        "repeat_selected": 0, "safe_alt_available": 0,
        "reason_sd": 0, "reason_lr": 0,
        "spread": 0, "focus": 0, "absorb_repeat": 0, "stale_sel": 0,
        "type_immune": 0, "crashes": 0, "opportunity": 0,
    }
    if not os.path.exists(log_path): return m
    with open(log_path) as f:
        for line in f:
            if not line.strip(): continue
            try: rec = json.loads(line)
            except Exception: continue
            for td in rec.get("audit_turns", []):
                for sk in ("slot_0", "slot_1"):
                    s = td.get(sk, {})
                    if not s: continue
                    if s.get("known_ally_redirection_candidate_blocked"): m["candidate_blocked"] += 1
                    if s.get("known_ally_redirection_opportunity_observed"): m["opportunity"] += 1
                    if s.get("known_ally_redirection_selected"): m["selected"] += 1
                    if s.get("known_ally_redirection_known_before_decision"):
                        if s.get("known_ally_redirection_selected"): m["selected_known_before"] += 1
                    elif s.get("known_ally_redirection_selected"): m["selected_revealed_after"] += 1
                    if s.get("our_known_ally_redirection_error"): m["our_error"] += 1
                    if s.get("opponent_known_ally_redirection_error"): m["opponent_error"] += 1
                    if s.get("known_ally_redirection_avoided"): m["avoided"] += 1
                    if s.get("known_ally_redirection_only_legal"): m["only_legal"] += 1
                    if s.get("known_ally_redirection_repeat_selected"): m["repeat_selected"] += 1
                    if s.get("known_ally_redirection_safe_alternative_available"): m["safe_alt_available"] += 1
                    r = s.get("known_ally_redirection_reason", "")
                    if "stormdrain" in r: m["reason_sd"] += 1
                    if "lightningrod" in r: m["reason_lr"] += 1
                    if s.get("action_types", {}).get("spread"): m["spread"] += 1
                    if s.get("direct_known_absorb_repeat_selected"): m["absorb_repeat"] += 1
                    if s.get("our_type_immune_move_selected"): m["type_immune"] += 1
                if td.get("stale_target_selected"): m["stale_sel"] += 1
                if td.get("focus_fire_triggered"): m["focus"] += 1
    # compute avoidable_selected from data
    return m

def _result(name, n, p, o, status, log_path, arm=""):
    f = p.n_finished_battles; w = p.n_won_battles
    l_ = o.n_won_battles if hasattr(o,'n_won_battles') else 0
    t = f-w-l_; wr = (w/f*100) if f>0 else 0
    turns = [b.turn for b in p.battles.values() if b.finished]
    at = sum(turns)/len(turns) if turns else 0
    m = _count(log_path)
    # avoidable_selected = selected - only_legal - (selected with revealed_after and not known)
    m["avoidable_selected"] = m["selected"] - m["only_legal"]
    cr = getattr(p, "_timeout_count", 0) + getattr(o, "_timeout_count", 0) if hasattr(o, "_timeout_count") else 0
    m["crashes"] = cr
    return {"name":name,"status":status,"planned":n,"finished":f,"wins":w,"losses":l_,"ties":t,
            "win_rate":f"{wr:.2f}","avg_turns":f"{at:.2f}","benchmark_arm":arm,**m}

async def main():
    tag = "phase636b7_corrected_ally_redirect_evidence_smoke"
    csvp = f"logs/known_ally_redirection_{tag}.csv"
    if os.path.exists(csvp) and "--overwrite" not in sys.argv:
        print(f"CSV exists: {csvp}"); return
    off = DoublesDamageAwareConfig()
    on = DoublesDamageAwareConfig()
    on.enable_known_ally_redirection_hard_safety = True
    arms = [
        ("A","AllyRedirOff vs Basic","basic",None,100),
        ("B","AllyRedirOn vs Basic","basic",None,100),
        ("C","AllyRedirOn vs Off","mirror",off,100),
        ("D","AllyRedirOn vs SafeRandom","safe_random",None,50),
    ]
    results = []
    for aid, aname, ocls, ocfg, n in arms:
        lp = f"logs/known_ally_redirection_{tag}_{aid}.jsonl"
        cfg = on if "On" in aname and "Off" not in aname else off
        r = await run_matchup(aname, cfg, ocls, ocfg, n, lp, arm=aid)
        results.append(r)
        print(f"  {aid}: {r.get('win_rate','N/A')}% WR, {r.get('wins',0)}W/{r.get('losses',0)}L")
    fns = ["name","status","planned","finished","wins","losses","ties",
           "win_rate","avg_turns","benchmark_arm",
            "candidate_blocked","opportunity","selected","selected_known_before","selected_revealed_after",
           "our_error","opponent_error","avoided","avoidable_selected","only_legal",
           "repeat_selected","safe_alt_available","reason_sd","reason_lr",
           "spread","focus","absorb_repeat","stale_sel","type_immune","crashes"]
    with open(csvp,"w",newline="") as f:
        w = csv.DictWriter(f, fieldnames=fns); w.writeheader()
        for r in results: w.writerow({k:r.get(k,0) for k in fns})
    print(f"\nSaved: {csvp}")

if __name__ == "__main__":
    asyncio.run(main())
