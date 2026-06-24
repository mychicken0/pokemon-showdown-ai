#!/usr/bin/env python3
"""RL-DATA-REFRESH-PREP-LONGRUN — single-battle data collector.

Each invocation runs one battle and exits cleanly.
Designed to be called from a shell wrapper for stability.
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

LOCAL_BASE = "RLRef"
HEALTH_URL = "http://localhost:8000"


def _norm(mid: Any) -> str:
    if mid is None:
        return ""
    s = str(mid).lower()
    return s.replace(" ", "").replace("-", "").replace("_", "").replace("'", "")


def classify_error(error_msg: str) -> str:
    if not error_msg:
        return "no_error"
    lower = error_msg.lower()
    if "nametaken" in lower or "logged in" in lower or "challstr" in lower:
        return "login_rate_limit"
    if "timeout" in lower:
        return "battle_timeout"
    if "websocket" in lower or "connection" in lower:
        return "websocket_error"
    return "other"


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


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-url", default="ws://localhost:8000/showdown/websocket")
    parser.add_argument("--mode", default="enhanced_wt_support",
                        choices=["default", "enhanced_wt_support"])
    parser.add_argument("--max-battles", type=int, default=1)
    parser.add_argument("--no-server-check", action="store_true")
    parser.add_argument("--output", default="logs/rl_data_refresh_battle.jsonl")
    parser.add_argument("--summary", default="logs/rl_data_refresh_battle_summary.json")
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

    suffix = f"{int(time.time()*1000) % 100000:05d}"
    bot_name = f"{LOCAL_BASE}B{suffix}"[:18]
    opp_name = f"{LOCAL_BASE}O{suffix}"[:18]

    audit_logger = DoublesDecisionAuditLogger(
        filepath=args.output, reset=True, detail_level="top5"
    )
    audit_logger.set_current_battle_meta(
        benchmark_arm=f"rl_refresh_{policy_mode}",
        enable_mega_evolution=False,
        enable_decision_timing_diagnostics=False,
        treatment_side="p1",
        player_side="p1",
        player_name=f"RL{policy_mode.capitalize()}",
    )

    bot = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        audit_logger=audit_logger,
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9randomdoublesbattle",
    )
    bot.config = config

    opp = RandomPlayer(
        account_configuration=AccountConfiguration(opp_name, None),
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9randomdoublesbattle",
    )

    error = None
    start = time.time()
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

    elapsed = time.time() - start
    n_finished = bot.n_finished_battles
    finished = n_finished > 0

    # Collect observations from support decisions
    hh_positive = 0
    tw_positive = 0
    for bt, dec_list in getattr(bot, "_support_decisions", {}).items():
        for sd in dec_list:
            mid = _norm(sd.get("move_id", ""))
            if mid == HELPING_HAND and sd.get("should_score", False):
                hh_positive += 1
            if mid == TAILWIND and sd.get("should_score", False):
                tw_positive += 1

    # Collect observations from audit JSONL
    hh_legal = 0
    hh_selected = 0
    tw_legal = 0
    tw_selected = 0
    wt_legal = 0
    wt_selected = 0
    total_turns = 0
    action_dist: Counter = Counter()
    bad_cases = 0

    if os.path.exists(args.output):
        with open(args.output) as f:
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
                            if mid in SUPPORT_SCORED_IDS:
                                if mid == HELPING_HAND:
                                    hh_legal += 1
                                elif mid == TAILWIND:
                                    tw_legal += 1
                            if mid in WT_SETTER_IDS:
                                wt_legal += 1
                            if target_pos and target_pos > 0:
                                action_dist["attack"] += 1
                            elif mid == "protect" or mid == "detect":
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
                            if sk_mid in SUPPORT_SCORED_IDS:
                                if sk_mid == HELPING_HAND:
                                    hh_selected += 1
                                    if sk_target_pos > 0:
                                        bad_cases += 1
                                elif sk_mid == TAILWIND:
                                    tw_selected += 1
                            if sk_mid in WT_SETTER_IDS:
                                wt_selected += 1

    summary = {
        "mode": policy_mode,
        "elapsed_s": round(elapsed, 1),
        "finished": finished,
        "n_finished": n_finished,
        "total_turns": total_turns,
        "helpinghand_legal": hh_legal,
        "helpinghand_selected": hh_selected,
        "helpinghand_positive": hh_positive,
        "tailwind_legal": tw_legal,
        "tailwind_selected": tw_selected,
        "tailwind_positive": tw_positive,
        "wt_legal": wt_legal,
        "wt_selected": wt_selected,
        "bad_cases": bad_cases,
        "action_distribution": dict(action_dist),
        "error": str(error) if error else None,
        "error_type": classify_error(error) if error else "no_error",
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

    print(f"fin={finished} turns={total_turns} "
          f"hh_l={hh_legal} hh_s={hh_selected} hh_p={hh_positive} "
          f"tw_l={tw_legal} tw_s={tw_selected} tw_p={tw_positive} "
          f"wt_l={wt_legal} wt_s={wt_selected} "
          f"bad={bad_cases} err={summary['error_type']}")
    print(f"Summary: {args.summary}")

    if not finished:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
