#!/usr/bin/env python3
"""Phase 6.4.7 — Stat-Drop Switch Scoring Benchmark.

Smoke arms:
  A) scoring_off vs Basic — 50 battles
  B) scoring_on vs Basic — 50 battles
  C) scoring_on vs off — 50 battles
  D) scoring_on vs SafeRandom — 30 battles

Artifact tag: phase647_stat_drop_switch_scoring_smoke
"""
import asyncio, csv, json, os, random, sys, time

sys.path.insert(0, os.path.dirname(__file__))
import atexit
import poke_env.concurrency
_clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if _clear_loop is not None:
    try:
        atexit.unregister(_clear_loop)
    except Exception:
        pass

from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer
from bot_doubles_safe_random import DoublesSafeRandomPlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

MAX_CONCURRENT = 15
STALL_TIMEOUT = 180
HEARTBEAT_INTERVAL = 30

class StallError(Exception): pass

async def _cleanup_player(player):
    try:
        if hasattr(player, "ps_client") and hasattr(player.ps_client, "_stop_listening"):
            await player.ps_client._stop_listening()
    except Exception:
        pass

async def _run_arm_with_watchdog(name, battle_factory, hb_factory, arm_timeout):
    bt = asyncio.create_task(battle_factory())
    wt = asyncio.create_task(hb_factory())
    exc = None
    try:
        done, _ = await asyncio.wait_for(
            asyncio.wait({bt, wt}, return_when=asyncio.FIRST_COMPLETED), timeout=arm_timeout)
        for t in (bt, wt):
            if t in done and not t.cancelled():
                e = t.exception()
                if e and not isinstance(e, asyncio.CancelledError):
                    raise e
    except asyncio.TimeoutError:
        exc = f"ARM TIMEOUT after {arm_timeout}s"
    except StallError as e:
        exc = str(e)
    except Exception as e:
        exc = f"{type(e).__name__}: {e}"
    finally:
        for t in (wt, bt):
            if t and not t.done():
                t.cancel()
        for t in (wt, bt):
            if t:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
    return ("ok" if exc is None else "error"), exc

async def run_matchup(name, config, opp_cls, opp_cfg, n, log_path, arm_to=1800, arm=""):
    if opp_cls == "basic":
        Opp = DoublesBasicAwarePlayer
    elif opp_cls == "safe_random":
        Opp = DoublesSafeRandomPlayer
    else:
        Opp = DoublesDamageAwarePlayer

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

    print(f"\n---> {name}: {n} battles")
    st = time.time(); state = {"last": st, "fin": 0}
    async def hb():
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            el = time.time()-st; f = p.n_finished_battles
            w = p.n_won_battles; l = o.n_won_battles if hasattr(o,'n_won_battles') else 0
            sl = time.time()-state["last"]
            if f > state["fin"]: state["last"] = time.time(); state["fin"] = f
            print(f"  [{name}] {el:.0f}s | {f}/{n} | {w}W {l}L | {sl:.0f}s since last")
            if sl > STALL_TIMEOUT: raise StallError(f"Stall: {name}")

    async def run(): return await p.battle_against(o, n_battles=n)
    status, exc = await _run_arm_with_watchdog(name, run, hb, arm_to)
    res = _result(name, n, p, o, status, log_path, arm)
    if exc: res["err"] = exc
    await _cleanup_player(p); await _cleanup_player(o)
    if status != "ok": print(f"  [{name}] {status.upper()}: {exc}")
    return res

def _count(log_path):
    m = {"pressure": 0, "switch_sel": 0, "stayed_prod": 0, "stayed_unprod": 0,
         "sel_changed": 0, "offensive": 0, "defensive": 0, "speed": 0,
         "threshold_off_m1": 0, "threshold_def_m2": 0, "threshold_spd_m2": 0,
         "threshold_mixed": 0,
         "sev_stay_unprod": 0, "absorb_repeat": 0, "stale_sel": 0,
         "forced_dt": 0, "spread": 0, "focus": 0}
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
                    if s.get("stat_drop_switch_pressure_active"): m["pressure"] += 1
                    if s.get("stat_drop_switch_selected"): m["switch_sel"] += 1
                    if s.get("stat_drop_switch_stayed_productive"): m["stayed_prod"] += 1
                    if s.get("stat_drop_switch_stayed_unproductive"): m["stayed_unprod"] += 1
                    if s.get("stat_drop_switch_selection_changed"): m["sel_changed"] += 1
                    cats = s.get("stat_drop_switch_pressure_categories", [])
                    if "offensive" in cats: m["offensive"] += 1
                    if "defensive" in cats: m["defensive"] += 1
                    if "speed" in cats: m["speed"] += 1
                    if s.get("severe_neg_boost_stayed_unproductive"): m["sev_stay_unprod"] += 1
                    ts = s.get("stat_drop_switch_threshold_source", "")
                    if ts == "offensive_-1": m["threshold_off_m1"] += 1
                    elif ts == "defensive_-2": m["threshold_def_m2"] += 1
                    elif ts == "speed_-2": m["threshold_spd_m2"] += 1
                    elif ts == "mixed": m["threshold_mixed"] += 1
                    if s.get("direct_known_absorb_repeat_selected"): m["absorb_repeat"] += 1
                    if s.get("forced_switch_selected_double_threat"): m["forced_dt"] += 1
                    if s.get("action_types", {}).get("spread"): m["spread"] += 1
                if td.get("stale_target_selected"): m["stale_sel"] += 1
                if td.get("focus_fire_triggered"): m["focus"] += 1
    return m

def _result(name, n, p, o, status, log_path, arm=""):
    f = p.n_finished_battles; w = p.n_won_battles
    l = o.n_won_battles if hasattr(o,'n_won_battles') else 0
    t = f-w-l; wr = (w/f*100) if f>0 else 0
    turns = [b.turn for b in p.battles.values() if b.finished]
    at = sum(turns)/len(turns) if turns else 0
    m = _count(log_path)
    return {"name":name,"status":status,"planned":n,"finished":f,"wins":w,"losses":l,"ties":t,
            "win_rate":f"{wr:.2f}","avg_turns":f"{at:.2f}","benchmark_arm":arm,**m}

async def main():
    tag = "phase647d_corrected_counterfactual_recheck"
    csvp = f"logs/stat_drop_switch_scoring_{tag}.csv"
    if os.path.exists(csvp) and "--overwrite" not in sys.argv:
        print(f"CSV exists: {csvp}"); return

    off = DoublesDamageAwareConfig()
    on = DoublesDamageAwareConfig()
    on.enable_stat_drop_switch_scoring = True

    arms = [
        ("A","ScoringOff vs Basic","basic",None,100),
        ("B","ScoringOn vs Basic","basic",None,100),
        ("C","ScoringOn vs Off","mirror",off,100),
        ("D","ScoringOn vs SafeRandom","safe_random",None,50),
    ]
    results = []
    for aid, aname, ocls, ocfg, n in arms:
        lp = f"logs/stat_drop_switch_scoring_{tag}_{aid}.jsonl"
        cfg = on if "On" in aname and "Off" not in aname else (off if "Off" in aname else on)
        r = await run_matchup(aname, cfg, ocls, ocfg, n, lp, arm=aid)
        results.append(r)
        print(f"  {aid}: {r.get('win_rate','N/A')}% WR, {r.get('wins',0)}W/{r.get('losses',0)}L")

    fns = ["name","status","planned","finished","wins","losses","ties",
           "win_rate","avg_turns","benchmark_arm","pressure","switch_sel",
           "stayed_prod","stayed_unprod","sel_changed","offensive","defensive",
           "speed","threshold_off_m1","threshold_def_m2","threshold_spd_m2","threshold_mixed",
           "sev_stay_unprod","absorb_repeat","stale_sel","forced_dt",
           "spread","focus"]
    with open(csvp,"w",newline="") as f:
        w = csv.DictWriter(f, fieldnames=fns); w.writeheader()
        for r in results: w.writerow({k:r.get(k,0) for k in fns})
    print(f"\nSaved: {csvp}")

if __name__ == "__main__":
    asyncio.run(main())
