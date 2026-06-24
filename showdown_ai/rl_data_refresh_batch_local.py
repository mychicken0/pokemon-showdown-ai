#!/usr/bin/env python3
"""RL-DATA-REFRESH-PREP-LONGRUN — batch data collector.

Runs N battles in a single Python process using poke_env's
async loop. Designed for reliability.
"""

import argparse
import asyncio
import atexit
import json
import os
import sys
import time
import urllib.request
from collections import Counter
from typing import Any, Dict, List

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPT_DIR)

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
from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    DoublesDamageAwarePlayer,
)
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

LOCAL_BASE = "RLBat"
HEALTH_URL = "http://localhost:8000"
HEARTBEAT_INTERVAL = 60

def _norm(mid: Any) -> str:
    if mid is None:
        return ""
    s = str(mid).lower()
    return s.replace(" ", "").replace("-", "").replace("_", "").replace("'", "")

HELPING_HAND = "helpinghand"
TAILWIND = "tailwind"
SUPPORT_SCORED_IDS = frozenset({HELPING_HAND, TAILWIND})
WT_SETTER_IDS = frozenset({
    "raindance", "sunnyday", "sandstorm", "hail", "snowscape",
    "electricterrain", "grassyterrain", "mistyterrain", "psychicterrain",
})

def build_config(mode: str) -> DoublesDamageAwareConfig:
    config = DoublesDamageAwareConfig()
    config.enable_support_positive_scoring = False
    config.enable_weather_terrain_positive_scoring = False
    config.enable_ally_heal_wrong_side_hard_safety = True
    config.enable_anti_trick_room_response = False
    config.enable_support_move_target_hard_safety = False
    if mode == "enhanced_wt_support":
        config.enable_weather_terrain_positive_scoring = True
        config.enable_support_positive_scoring = True
        config.helping_hand_bonus = 120.0
        config.tailwind_bonus = 180.0
    return config


def _collect_observations(audit_path: str):
    hh_legal = hh_selected = hh_positive = 0
    tw_legal = tw_selected = tw_positive = 0
    wt_legal = wt_selected = 0
    total_turns = 0
    action_dist: Counter = Counter()
    bad_cases = 0
    if not os.path.exists(audit_path):
        return {"hh_legal": 0, "hh_selected": 0, "hh_positive": 0,
                "tw_legal": 0, "tw_selected": 0, "tw_positive": 0,
                "wt_legal": 0, "wt_selected": 0,
                "total_turns": 0, "action_dist": {}, "bad_cases": 0}
    with open(audit_path) as f:
        for line in f:
            try:
                battle = json.loads(line)
            except json.JSONDecodeError:
                continue
            turns = battle.get("audit_turns", [])
            total_turns = len(turns)
            for turn in turns:
                for slot in (0, 1):
                    legal = turn.get(f"v4a_legal_action_keys_slot{slot}", []) or []
                    for k in legal:
                        if not (isinstance(k, list) and len(k) >= 2):
                            continue
                        mid = _norm(k[1])
                        target_pos = k[2] if len(k) > 2 else 0
                        if mid == HELPING_HAND:
                            hh_legal += 1
                        elif mid == TAILWIND:
                            tw_legal += 1
                        if mid in WT_SETTER_IDS:
                            wt_legal += 1
                        if target_pos and target_pos > 0:
                            action_dist["attack"] += 1
                        elif mid in ("protect", "detect"):
                            action_dist["protect"] += 1
                        elif mid in SUPPORT_SCORED_IDS:
                            action_dist["support_scored"] += 1
                        elif mid in WT_SETTER_IDS:
                            action_dist["wt_setter"] += 1
                        else:
                            action_dist["other_support"] += 1
                selected = turn.get("v4a_selected_joint_key", []) or []
                for sk in selected:
                    if not (isinstance(sk, list) and len(sk) >= 2):
                        continue
                    if str(sk[0]) != "move":
                        continue
                    sk_mid = _norm(sk[1])
                    sk_target_pos = sk[2] if len(sk) > 2 else 0
                    if sk_mid == HELPING_HAND:
                        hh_selected += 1
                        if sk_target_pos > 0:
                            bad_cases += 1
                    elif sk_mid == TAILWIND:
                        tw_selected += 1
                    if sk_mid in WT_SETTER_IDS:
                        wt_selected += 1
    return {"hh_legal": hh_legal, "hh_selected": hh_selected, "hh_positive": 0,
            "tw_legal": tw_legal, "tw_selected": tw_selected, "tw_positive": 0,
            "wt_legal": wt_legal, "wt_selected": wt_selected,
            "total_turns": total_turns, "action_dist": dict(action_dist), "bad_cases": bad_cases}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="enhanced_wt_support",
                        choices=["default", "enhanced_wt_support"])
    parser.add_argument("--battles", type=int, default=50)
    parser.add_argument("--target-rows", type=int, default=10000)
    parser.add_argument("--no-server-check", action="store_true")
    parser.add_argument("--output", default="logs/rl_data_refresh_batch.jsonl")
    parser.add_argument("--summary", default="logs/rl_data_refresh_batch_summary.json")
    args = parser.parse_args()

    if not args.no_server_check:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=5) as r:
                if r.status != 200:
                    print("ERROR: server unhealthy")
                    sys.exit(1)
        except Exception:
            print("ERROR: cannot reach localhost:8000")
            sys.exit(1)

    os.makedirs("logs", exist_ok=True)
    config = build_config(args.mode)
    policy_mode = "default" if args.mode == "default" else "enhanced_wt_support"
    print(f"RL-DATA-REFRESH-PREP ({policy_mode}) battles={args.battles} target_rows={args.target_rows}")

    all_results = []
    total_turns_all = 0
    last_heartbeat = time.time()

    # Use a single account per session - poke_env changes suffix
    bot = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration("RLRefreshBot", None),
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9randomdoublesbattle",
    )
    bot.config = config
    opp = RandomPlayer(
        account_configuration=AccountConfiguration("RLRefreshOpp", None),
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9randomdoublesbattle",
    )

    for b in range(1, args.battles + 1):
        suffix = f"{int(time.time()*1000) % 100000:05d}_{b}"
        audit_path = args.output.replace(".jsonl", f"_{suffix}.jsonl")
        per_logger = DoublesDecisionAuditLogger(
            filepath=audit_path, reset=True, detail_level="top5"
        )
        per_logger.set_current_battle_meta(
            benchmark_arm=f"rl_refresh_{policy_mode}",
            enable_mega_evolution=False,
            enable_decision_timing_diagnostics=False,
            treatment_side="p1",
            player_side="p1",
            player_name=f"RL{policy_mode.capitalize()}",
        )
        bot.audit_logger = per_logger

        start = time.time()
        error = None
        try:
            await asyncio.wait_for(
                bot.battle_against(opp, n_battles=1),
                timeout=300,
            )
        except Exception as e:
            error = str(e)

        obs = _collect_observations(audit_path)
        total_turns_all += obs["total_turns"]

        # Also collect support positive decisions
        hh_positive = 0
        tw_positive = 0
        for bt, dec_list in getattr(bot, "_support_decisions", {}).items():
            for sd in dec_list:
                mid = _norm(sd.get("move_id", ""))
                if mid == HELPING_HAND and sd.get("should_score", False):
                    hh_positive += 1
                if mid == TAILWIND and sd.get("should_score", False):
                    tw_positive += 1

        result = {
            "battle": b,
            "finished": bot.n_finished_battles > 0,
            "n_finished": bot.n_finished_battles,
            "turns": obs["total_turns"],
            "elapsed": round(time.time() - start, 1),
            "hh_legal": obs["hh_legal"],
            "hh_selected": obs["hh_selected"],
            "hh_positive": hh_positive,
            "tw_legal": obs["tw_legal"],
            "tw_selected": obs["tw_selected"],
            "tw_positive": tw_positive,
            "wt_legal": obs["wt_legal"],
            "wt_selected": obs["wt_selected"],
            "bad_cases": obs["bad_cases"],
            "error": str(error) if error else None,
            "error_type": "no_error" if not error else "error",
        }
        all_results.append(result)
        print(f"  Battle {b}/{args.battles}: fin={result['finished']} "
              f"turns={result['turns']} hh_s={result['hh_selected']} "
              f"tw_s={result['tw_selected']} wt_s={result['wt_selected']}")

        if time.time() - last_heartbeat > HEARTBEAT_INTERVAL:
            nf = sum(1 for r in all_results if r["finished"])
            print(f"  [HEARTBEAT] battles={b} finished={nf} turns={total_turns_all}")
            last_heartbeat = time.time()

        if total_turns_all >= args.target_rows:
            print(f"  Target rows {args.target_rows} reached at battle {b}")
            break

    # Aggregate summary
    n_finished = sum(1 for r in all_results if r["finished"])
    total_hh_legal = sum(r["hh_legal"] for r in all_results)
    total_hh_selected = sum(r["hh_selected"] for r in all_results)
    total_hh_positive = sum(r["hh_positive"] for r in all_results)
    total_tw_legal = sum(r["tw_legal"] for r in all_results)
    total_tw_selected = sum(r["tw_selected"] for r in all_results)
    total_tw_positive = sum(r["tw_positive"] for r in all_results)
    total_wt_legal = sum(r["wt_legal"] for r in all_results)
    total_wt_selected = sum(r["wt_selected"] for r in all_results)
    total_bad = sum(r["bad_cases"] for r in all_results)

    summary = {
        "mode": policy_mode,
        "battles_attempted": len(all_results),
        "battles_finished": n_finished,
        "total_turns": total_turns_all,
        "helpinghand_legal": total_hh_legal,
        "helpinghand_selected": total_hh_selected,
        "helpinghand_positive": total_hh_positive,
        "tailwind_legal": total_tw_legal,
        "tailwind_selected": total_tw_selected,
        "tailwind_positive": total_tw_positive,
        "wt_legal": total_wt_legal,
        "wt_selected": total_wt_selected,
        "bad_cases_total": total_bad,
        "raw_results": all_results,
        "config": {
            "enable_support_positive_scoring": config.enable_support_positive_scoring,
            "enable_weather_terrain_positive_scoring": config.enable_weather_terrain_positive_scoring,
            "enable_ally_heal_wrong_side_hard_safety": config.enable_ally_heal_wrong_side_hard_safety,
            "enable_anti_trick_room_response": config.enable_anti_trick_room_response,
            "enable_support_move_target_hard_safety": config.enable_support_move_target_hard_safety,
        },
    }
    with open(args.summary, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n{'='*50}")
    print(f"RL-DATA-REFRESH-PREP complete ({policy_mode})")
    print(f"{'='*50}")
    print(f"  Battles: {len(all_results)} finished={n_finished}")
    print(f"  Total turns: {total_turns_all}")
    print(f"  HH legal={total_hh_legal} sel={total_hh_selected} pos={total_hh_positive}")
    print(f"  TW legal={total_tw_legal} sel={total_tw_selected} pos={total_tw_positive}")
    print(f"  WT legal={total_wt_legal} sel={total_wt_selected}")
    print(f"  Bad cases: {total_bad}")


if __name__ == "__main__":
    asyncio.run(main())
