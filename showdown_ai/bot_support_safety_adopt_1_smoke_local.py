#!/usr/bin/env python3
"""SUPPORT-SAFETY-ADOPT-1 — small local safety smoke.

A local-only smoke that runs 5 random doubles battles
on localhost:8000 to verify the default-ON narrow
hard safety does not crash and does not cause illegal
actions.

Uses gen9doublescustomgame with a standard team file
to ensure reliable connection and avoid the
poke-env 'int' object is not iterable error that
occurs with gen9randombattle.

Local server only (localhost:8000). No official server.
No commits. No default flip beyond the narrow flag.
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
LOCAL_BASE = "SSAdopt1"


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
    audit_path: str,
):
    bot_name = f"{LOCAL_BASE}B_{suffix}"[:18]
    opp_name = f"{LOCAL_BASE}O_{suffix}"[:18]
    audit_logger = DoublesDecisionAuditLogger(
        filepath=audit_path, reset=True, detail_level="top5"
    )
    audit_logger.set_current_battle_meta(
        benchmark_arm="ssadopt1_on",
        enable_mega_evolution=False,
        enable_decision_timing_diagnostics=False,
        treatment_side="p1",
        player_side="p1",
        player_name="SSAdopt1On",
    )
    bot = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        audit_logger=audit_logger,
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9doublescustomgame",
        team=our_team_showdown,
    )
    # Default-ON narrow flag (SUPPORT-SAFETY-ADOPT-1).
    # Other defaults are preserved.
    assert bot.config.enable_anti_trick_room_response is False
    assert (
        bot.config.enable_weather_terrain_positive_scoring is False
    )
    assert bot.config.enable_support_move_target_hard_safety is False
    assert bot.config.enable_ally_heal_wrong_side_hard_safety is True
    opp = RandomPlayer(
        account_configuration=AccountConfiguration(opp_name, None),
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9doublescustomgame",
        team=opp_team_showdown,
    )
    start = time.time()
    error = None
    try:
        await asyncio.wait_for(
            bot.battle_against(opp, n_battles=1),
            timeout=300,
        )
    except Exception as e:
        error = str(e)
    try:
        await bot.ps_client._stop_listening()
        await opp.ps_client._stop_listening()
    except Exception:
        pass
    # Count narrow blocks
    n_narrow_blocks = 0
    blocked_dict = getattr(
        bot, "_support_target_wrong_side_blocked", {}
    )
    if blocked_dict:
        for bt, slot_dict in blocked_dict.items():
            for slot, was_blocked in slot_dict.items():
                if was_blocked:
                    n_narrow_blocks += 1
    return {
        "suffix": suffix,
        "elapsed_s": time.time() - start,
        "finished": bot.n_finished_battles > 0,
        "n_finished": bot.n_finished_battles,
        "n_narrow_blocks": n_narrow_blocks,
        "error": error,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--battles",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--output",
        default="logs/support_safety_adopt_1_smoke.json",
    )
    parser.add_argument(
        "--audit-dir",
        default="logs/support_safety_adopt_1_audits",
    )
    args = parser.parse_args()
    if not check_localhost_healthy():
        print("ERROR: localhost:8000 not healthy; refusing")
        sys.exit(1)
    os.makedirs(args.audit_dir, exist_ok=True)
    # Use a simple 2-mon team for reliable connection.
    our_team_path = (
        "data/curated_teams/custom/wt4e_terrain_2mon.json"
    )
    opp_team_path = (
        "data/curated_teams/custom/wt4e_terrain_2mon_opp.json"
    )
    with open(our_team_path) as f:
        our_team = json_to_showdown(json.load(f))
    with open(opp_team_path) as f:
        opp_team = json_to_showdown(json.load(f))
    results = []
    for i in range(1, args.battles + 1):
        suffix = f"{i}_{int(time.time()*1000) % 100000}"[-12:]
        audit_path = os.path.join(
            args.audit_dir, f"ssadopt1_battle_{i}.jsonl"
        )
        print(
            f"  Battle {i}/{args.battles} suffix={suffix}",
            flush=True,
        )
        try:
            r = asyncio.run(
                run_one_battle(
                    suffix, our_team, opp_team, audit_path
                )
            )
            results.append(r)
            print(
                f"    finished={r['finished']} "
                f"elapsed={r['elapsed_s']:.1f}s "
                f"narrow_blocks={r['n_narrow_blocks']} "
                f"error={r.get('error')}",
                flush=True,
            )
        except Exception as e:
            print(f"    Error: {e}", flush=True)
            results.append(
                {
                    "suffix": suffix,
                    "finished": False,
                    "n_finished": 0,
                    "n_narrow_blocks": 0,
                    "error": str(e),
                }
            )
        time.sleep(2)
    total_finished = sum(r.get("n_finished", 0) for r in results)
    total_errors = sum(1 for r in results if r.get("error"))
    total_blocks = sum(r.get("n_narrow_blocks", 0) for r in results)
    output = {
        "n_battles": args.battles,
        "n_finished": total_finished,
        "n_errors": total_errors,
        "total_narrow_blocks": total_blocks,
        "results": results,
    }
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print()
    print("=" * 60)
    print("SUPPORT-SAFETY-ADOPT-1 smoke complete")
    print("=" * 60)
    print(
        f"  Finished: {total_finished}/{args.battles} | "
        f"Errors: {total_errors} | "
        f"Narrow blocks: {total_blocks}"
    )
    print(f"  Output: {args.output}")


if __name__ == "__main__":
    main()
