#!/usr/bin/env python3
"""WT-4g small paired eval — simplified version
that runs OFF vs ON for one mode at a time.
"""

import argparse
import asyncio
import atexit
import json
import os
import sys
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPT_DIR)

# Unregister poke-env's broken atexit hook.
import poke_env.concurrency
_clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if _clear_loop is not None:
    try:
        atexit.unregister(_clear_loop)
    except Exception:
        pass

import poke_env_test_cleanup  # noqa: F401

from poke_env import AccountConfiguration
from poke_env.player.baselines import RandomPlayer

from bot_doubles_damage_aware import DoublesDamageAwarePlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

HEALTH_URL = "http://localhost:8000"
LOCAL_BASE = "WT4gSmpl"


def check_localhost_healthy(timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def json_to_showdown(team_dict):
    lines = []
    for p in team_dict.get("team", []):
        species = p["species"]
        if p.get("item"):
            lines.append(f"{species} @ {p['item']}")
        else:
            lines.append(species)
        lines.append(f"Ability: {p['ability']}")
        evs = p.get("evs", {})
        if evs:
            ev_parts = [f"{v} {k.upper()}" for k, v in evs.items() if v > 0]
            if ev_parts:
                lines.append("EVs: " + " / ".join(ev_parts))
        if p.get("nature"):
            lines.append(f"{p['nature']} Nature")
        for move in p.get("moves", []):
            lines.append(f"- {move}")
        lines.append("")
    return "\n".join(lines)


async def run_one_battle(
    suffix: str,
    our_team_showdown: str,
    opp_team_showdown: str,
    enable_wt: bool,
    weather_bonus: float,
    terrain_bonus: float,
    audit_path: str,
):
    bot_name = f"{LOCAL_BASE}B_{suffix}"[:18]
    opp_name = f"{LOCAL_BASE}O_{suffix}"[:18]
    audit_logger = DoublesDecisionAuditLogger(
        filepath=audit_path, reset=True, detail_level="top5"
    )
    audit_logger.set_current_battle_meta(
        benchmark_arm=f"wt4g_smpl_{'on' if enable_wt else 'off'}",
        enable_mega_evolution=False,
        enable_decision_timing_diagnostics=False,
        treatment_side="p1",
        player_side="p1",
        player_name=f"WT4gSmpl{('On' if enable_wt else 'Off')}",
    )
    bot = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        audit_logger=audit_logger,
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9doublescustomgame",
        team=our_team_showdown,
    )
    bot.config.enable_weather_terrain_positive_scoring = enable_wt
    bot.config.weather_terrain_positive_weather_bonus = (
        weather_bonus
    )
    bot.config.weather_terrain_positive_terrain_bonus = (
        terrain_bonus
    )
    opp = RandomPlayer(
        account_configuration=AccountConfiguration(opp_name, None),
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9doublescustomgame",
        team=opp_team_showdown,
    )
    start = time.time()
    try:
        await asyncio.wait_for(
            bot.battle_against(opp, n_battles=1),
            timeout=300,
        )
    except Exception as e:
        print(f"  Error: {e}")
    try:
        await bot.ps_client._stop_listening()
        await opp.ps_client._stop_listening()
    except Exception:
        pass
    return {
        "suffix": suffix,
        "elapsed_s": time.time() - start,
        "finished": bot.n_finished_battles > 0,
        "n_finished": bot.n_finished_battles,
        "n_wt3_calls": sum(
            len(dl)
            for dl in getattr(bot, "_wt3_decisions", {}).values()
        ),
        "n_wt3_setters": sum(
            1
            for bt, dl in getattr(bot, "_wt3_decisions", {}).items()
            for d in dl
            if isinstance(d, dict)
            and d.get("move_id", "") in (
                "raindance", "sunnyday", "sandstorm",
                "snowscape", "hail", "electricterrain",
                "grassyterrain", "mistyterrain",
                "psychicterrain",
            )
        ),
        "n_wt3_positive": sum(
            1
            for bt, dl in getattr(bot, "_wt3_decisions", {}).items()
            for d in dl
            if isinstance(d, dict)
            and d.get("move_id", "") in (
                "raindance", "sunnyday", "sandstorm",
                "snowscape", "hail", "electricterrain",
                "grassyterrain", "mistyterrain",
                "psychicterrain",
            )
            and d.get("bonus", 0) > 0
        ),
        "audit_path": audit_path,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--our-team",
        default="data/curated_teams/custom/wt4e_terrain_2mon.json",
    )
    parser.add_argument(
        "--opp-team",
        default="data/curated_teams/custom/wt4e_terrain_2mon_opp.json",
    )
    parser.add_argument(
        "--pairs",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--weather-bonus",
        type=float,
        default=500.0,
    )
    parser.add_argument(
        "--terrain-bonus",
        type=float,
        default=400.0,
    )
    parser.add_argument(
        "--output",
        default="logs/wt4g_small_paired_eval.json",
    )
    parser.add_argument(
        "--audit-dir",
        default="logs/wt4g_simple_audits",
    )
    args = parser.parse_args()
    if not check_localhost_healthy():
        print("ERROR: localhost:8000 not healthy")
        sys.exit(1)
    os.makedirs(args.audit_dir, exist_ok=True)
    with open(args.our_team) as f:
        our_team = json_to_showdown(json.load(f))
    with open(args.opp_team) as f:
        opp_team = json_to_showdown(json.load(f))
    all_results = []
    for p in range(1, args.pairs + 1):
        for arm_flag in [False, True]:
            arm = "on" if arm_flag else "off"
            suffix = f"{p}_{arm}_{int(time.time()*1000) % 100000}"[-12:]
            audit_path = os.path.join(
                args.audit_dir, f"wt4g_smpl_{arm}_{p}.jsonl"
            )
            print(
                f"  Pair {p} arm={arm.upper()} suffix={suffix}",
                flush=True,
            )
            try:
                r = asyncio.run(
                    run_one_battle(
                        suffix,
                        our_team,
                        opp_team,
                        arm_flag,
                        args.weather_bonus,
                        args.terrain_bonus,
                        audit_path,
                    )
                )
                r["pair"] = p
                r["arm"] = arm
                r["enable_wt"] = arm_flag
                all_results.append(r)
                print(
                    f"    finished={r['finished']} "
                    f"wt3_calls={r['n_wt3_calls']} "
                    f"wt3_setters={r['n_wt3_setters']} "
                    f"wt3_positive={r['n_wt3_positive']}",
                    flush=True,
                )
            except Exception as e:
                print(f"    Error: {e}", flush=True)
                all_results.append(
                    {
                        "pair": p,
                        "arm": arm,
                        "enable_wt": arm_flag,
                        "error": str(e),
                        "finished": False,
                        "n_wt3_calls": 0,
                        "n_wt3_setters": 0,
                        "n_wt3_positive": 0,
                    }
                )
            # Rate limit
            time.sleep(2)
    off_results = [r for r in all_results if not r.get("enable_wt")]
    on_results = [r for r in all_results if r.get("enable_wt")]
    off_calls = sum(r.get("n_wt3_calls", 0) for r in off_results)
    off_setters = sum(r.get("n_wt3_setters", 0) for r in off_results)
    off_positive = sum(r.get("n_wt3_positive", 0) for r in off_results)
    on_calls = sum(r.get("n_wt3_calls", 0) for r in on_results)
    on_setters = sum(r.get("n_wt3_setters", 0) for r in on_results)
    on_positive = sum(r.get("n_wt3_positive", 0) for r in on_results)
    output = {
        "n_pairs": args.pairs,
        "off_aggregate": {
            "n_finished": sum(1 for r in off_results if r.get("finished")),
            "n_errors": sum(1 for r in off_results if "error" in r),
            "total_wt3_calls": off_calls,
            "total_wt3_setters": off_setters,
            "total_wt3_positive": off_positive,
        },
        "on_aggregate": {
            "n_finished": sum(1 for r in on_results if r.get("finished")),
            "n_errors": sum(1 for r in on_results if "error" in r),
            "total_wt3_calls": on_calls,
            "total_wt3_setters": on_setters,
            "total_wt3_positive": on_positive,
        },
        "raw_results": all_results,
    }
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print()
    print("=" * 60)
    print("WT-4g simple paired eval complete")
    print("=" * 60)
    print(
        f"  OFF: {output['off_aggregate']['n_finished']}/"
        f"{len(off_results)} finished | "
        f"wt3_calls={off_calls} | "
        f"wt3_setters={off_setters} | "
        f"wt3_positive={off_positive}"
    )
    print(
        f"  ON: {output['on_aggregate']['n_finished']}/"
        f"{len(on_results)} finished | "
        f"wt3_calls={on_calls} | "
        f"wt3_setters={on_setters} | "
        f"wt3_positive={on_positive}"
    )
    print(f"  Output: {args.output}")


if __name__ == "__main__":
    main()
