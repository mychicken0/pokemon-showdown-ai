#!/usr/bin/env python3
"""SUPPORT-SCORING-1C — small paired eval / activation
tuning for Helping Hand + Tailwind opt-in scoring.

A local-only paired eval that runs OFF vs ON with
identical or comparable local conditions. The eval
addresses the 1B issue: OFF arms finished 0 due to
local login rate limit.

Key improvements over 1B activation smoke:
- Unique user prefix per run to avoid name collisions
- Longer delay between battles (5+ seconds)
- Sequential battle execution (no concurrent workers)
- Clear error classification: login_rate_limit vs
  other errors
- Retry/backoff for login rate limit errors
- Fails clearly if OFF or ON cannot start

Local server only (localhost:8000). No official
server. No commits. No default flips.
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
from typing import Any, Dict, List, Optional, Set, Tuple

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

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    DoublesDamageAwarePlayer,
)
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

HEALTH_URL = "http://localhost:8000"
LOCAL_BASE = "SS1cEv"

HELPING_HAND = "helpinghand"
TAILWIND = "tailwind"
WT_SETTER_IDS = {
    "raindance", "sunnyday", "sandstorm", "snowscape",
    "hail", "electricterrain", "grassyterrain",
    "mistyterrain", "psychicterrain",
}
TARGET_MOVES = {HELPING_HAND, TAILWIND}


def check_localhost_healthy(timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _norm(move_id):
    if move_id is None:
        return ""
    s = str(move_id)
    return (
        s.lower()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .replace("'", "")
    )


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


def _build_helping_hand_team():
    return {
        "team": [
            {
                "species": "Oranguru",
                "ability": "Inner Focus",
                "item": "Leftovers",
                "evs": {"hp": 252, "spd": 252, "def": 4},
                "nature": "Calm",
                "moves": [
                    "Helping Hand",
                    "Protect",
                    "Psychic",
                    "Trick Room",
                ],
                "types": ["normal", "psychic"],
            },
            {
                "species": "Garchomp",
                "ability": "Rough Skin",
                "item": "Choice Scarf",
                "evs": {"atk": 252, "spd": 252, "hp": 4},
                "nature": "Jolly",
                "moves": [
                    "Earthquake",
                    "Rock Slide",
                    "Scale Shot",
                    "Protect",
                ],
                "types": ["dragon", "ground"],
            },
        ]
    }


def _build_tailwind_team():
    return {
        "team": [
            {
                "species": "Whimsicott",
                "ability": "Prankster",
                "item": "Leftovers",
                "evs": {"hp": 252, "spd": 252, "def": 4},
                "nature": "Bold",
                "moves": [
                    "Tailwind",
                    "Protect",
                    "Moonblast",
                    "Encore",
                ],
                "types": ["grass", "fairy"],
            },
            {
                "species": "Garchomp",
                "ability": "Rough Skin",
                "item": "Choice Scarf",
                "evs": {"atk": 252, "spd": 252, "hp": 4},
                "nature": "Jolly",
                "moves": [
                    "Earthquake",
                    "Rock Slide",
                    "Scale Shot",
                    "Protect",
                ],
                "types": ["dragon", "ground"],
            },
        ]
    }


def _build_opp_team():
    return {
        "team": [
            {
                "species": "Tyranitar",
                "ability": "Sand Stream",
                "item": "Leftovers",
                "evs": {"hp": 252, "def": 252, "spd": 4},
                "nature": "Careful",
                "moves": [
                    "Rock Slide",
                    "Crunch",
                    "Stone Edge",
                    "Protect",
                ],
                "types": ["rock", "dark"],
            },
            {
                "species": "Gyarados",
                "ability": "Intimidate",
                "item": "Leftovers",
                "evs": {"atk": 252, "spd": 252, "hp": 4},
                "nature": "Jolly",
                "moves": [
                    "Waterfall",
                    "Ice Fang",
                    "Dragon Dance",
                    "Protect",
                ],
                "types": ["water", "flying"],
            },
        ]
    }


MODES = {
    "helpinghand": _build_helping_hand_team,
    "tailwind": _build_tailwind_team,
}


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


def classify_error(error_msg: str) -> str:
    """Classify a battle error message into categories."""
    if not error_msg:
        return "no_error"
    lower = error_msg.lower()
    if "nametaken" in lower:
        return "login_rate_limit"
    if "to be logged in" in lower or "logged in" in lower:
        return "login_rate_limit"
    if "challstr" in lower:
        return "login_rate_limit"
    if "timeout" in lower:
        return "battle_timeout"
    if "websocket" in lower or "connection" in lower:
        return "websocket_error"
    return "other"


# ---------------------------------------------------------------------------
# Battle execution
# ---------------------------------------------------------------------------


async def run_one_battle(
    suffix: str,
    our_team_showdown: str,
    opp_team_showdown: str,
    audit_path: str,
    enable_support_scoring: bool,
    helping_hand_bonus: float,
    tailwind_bonus: float,
    timeout_seconds: int,
):
    bot_name = f"{LOCAL_BASE}B_{suffix}"[:18]
    opp_name = f"{LOCAL_BASE}O_{suffix}"[:18]
    audit_logger = DoublesDecisionAuditLogger(
        filepath=audit_path, reset=True, detail_level="top5"
    )
    audit_logger.set_current_battle_meta(
        benchmark_arm=(
            f"ss1c_{'on' if enable_support_scoring else 'off'}"
        ),
        enable_mega_evolution=False,
        enable_decision_timing_diagnostics=False,
        treatment_side="p1",
        player_side="p1",
        player_name=(
            f"SS1c{'On' if enable_support_scoring else 'Off'}"
        ),
    )
    bot = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        audit_logger=audit_logger,
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9doublescustomgame",
        team=our_team_showdown,
    )
    bot.config.enable_support_positive_scoring = (
        enable_support_scoring
    )
    bot.config.helping_hand_bonus = helping_hand_bonus
    bot.config.tailwind_bonus = tailwind_bonus
    # Verify defaults are preserved.
    assert bot.config.enable_ally_heal_wrong_side_hard_safety is True
    assert (
        bot.config.enable_weather_terrain_positive_scoring is False
    )
    assert bot.config.enable_anti_trick_room_response is False
    assert bot.config.enable_support_move_target_hard_safety is False
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
            timeout=timeout_seconds,
        )
    except Exception as e:
        error = str(e)
    try:
        await bot.ps_client._stop_listening()
        await opp.ps_client._stop_listening()
    except Exception:
        pass
    # Collect observations
    observations = {
        HELPING_HAND: {"legal": 0, "selected": 0, "positive": 0},
        TAILWIND: {"legal": 0, "selected": 0, "positive": 0},
    }
    action_dist: Counter = Counter()
    bad_cases: List[Dict[str, Any]] = []
    total_turns = 0
    # Check support decisions from bot instance
    for bt, dec_list in getattr(
        bot, "_support_decisions", {}
    ).items():
        for sd in dec_list:
            if not isinstance(sd, dict):
                continue
            mid = _norm(sd.get("move_id", ""))
            if mid in TARGET_MOVES and sd.get(
                "should_score", False
            ):
                observations[mid]["positive"] += 1
    if os.path.exists(audit_path):
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
                        legal = (
                            turn.get(
                                "v4a_legal_action_keys_slot"
                                + str(slot),
                                [],
                            )
                            or []
                        )
                        for k in legal:
                            if not (
                                isinstance(k, list) and len(k) >= 2
                            ):
                                continue
                            kind = str(k[0])
                            mid = _norm(k[1])
                            target_pos = k[2] if len(k) > 2 else 0
                            if mid in TARGET_MOVES:
                                observations[mid]["legal"] += 1
                            # Classify action for distribution
                            if kind == "move":
                                if mid in TARGET_MOVES:
                                    if mid == HELPING_HAND:
                                        action_dist["helping_hand"] += 1
                                    elif mid == TAILWIND:
                                        action_dist["tailwind"] += 1
                                elif mid in WT_SETTER_IDS:
                                    action_dist["wt_setter"] += 1
                                elif mid in (
                                    "protect", "detect"
                                ):
                                    action_dist["protect"] += 1
                                elif target_pos and target_pos > 0:
                                    action_dist["attack"] += 1
                                else:
                                    action_dist["other_support"] += 1
                            elif kind == "switch":
                                action_dist["switch"] += 1
                            else:
                                action_dist["other"] += 1
                        # Check selected
                        selected_key = turn.get(
                            "v4a_selected_joint_key", []
                        ) or []
                        for sk in selected_key:
                            if not (
                                isinstance(sk, list) and len(sk) >= 2
                            ):
                                continue
                            if str(sk[0]) != "move":
                                continue
                            sk_mid = _norm(sk[1])
                            sk_target_pos = sk[2] if len(sk) > 2 else 0
                            if sk_mid in TARGET_MOVES:
                                observations[sk_mid]["selected"] += 1
                                # Check bad cases
                                if sk_mid == HELPING_HAND:
                                    if sk_target_pos and sk_target_pos > 0:
                                        bad_cases.append({
                                            "battle": battle.get(
                                                "battle_tag", "?"
                                            ),
                                            "turn": turn.get("turn"),
                                            "slot": slot,
                                            "move": sk_mid,
                                            "target_pos": sk_target_pos,
                                            "reason": (
                                                "hh_targeted_opponent"
                                            ),
                                        })
                                if sk_mid == TAILWIND:
                                    # Check if Tailwind already
                                    # active (weather or fields)
                                    weather = battle.get(
                                        "audit_turns", [{}]
                                    )[0].get(
                                        "state_snapshot", {}
                                    ).get("weather", [])
                                    fields = battle.get(
                                        "audit_turns", [{}]
                                    )[0].get(
                                        "state_snapshot", {}
                                    ).get("fields", [])
                                    if "tailwind" in (
                                        str(w).lower()
                                        for w in weather
                                    ):
                                        bad_cases.append({
                                            "battle": battle.get(
                                                "battle_tag", "?"
                                            ),
                                            "turn": turn.get("turn"),
                                            "slot": slot,
                                            "move": sk_mid,
                                            "reason": (
                                                "tw_already_active"
                                            ),
                                        })
    error_type = classify_error(error) if error else "no_error"
    return {
        "suffix": suffix,
        "elapsed_s": time.time() - start,
        "finished": bot.n_finished_battles > 0,
        "n_finished": bot.n_finished_battles,
        "n_turns": total_turns,
        "observations": observations,
        "action_distribution": dict(action_dist),
        "bad_cases": bad_cases,
        "error": error,
        "error_type": error_type,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server-url",
        default="ws://localhost:8000/showdown/websocket",
    )
    parser.add_argument(
        "--pairs",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--modes",
        default="helpinghand,tailwind",
    )
    parser.add_argument(
        "--helping-hand-bonus",
        type=float,
        default=120.0,
    )
    parser.add_argument(
        "--tailwind-bonus",
        type=float,
        default=180.0,
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=5.0,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
    )
    parser.add_argument(
        "--unique-user-prefix",
        default=None,
    )
    parser.add_argument(
        "--output",
        default="logs/support_scoring_1c_small_paired_eval.json",
    )
    parser.add_argument(
        "--audit-dir",
        default="logs/support_scoring_1c_audits",
    )
    args = parser.parse_args()
    if not check_localhost_healthy():
        print("ERROR: localhost:8000 not healthy; refusing")
        sys.exit(1)
    os.makedirs(args.audit_dir, exist_ok=True)
    user_prefix = args.unique_user_prefix or (
        f"{int(time.time()) % 1000000:06d}"
    )
    # Use a fresh base per run to avoid name collisions
    # that can trigger local rate limit.
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    for m in modes:
        if m not in MODES:
            print(f"ERROR: unknown mode {m}")
            sys.exit(1)
    opp_team = _build_opp_team()
    opp_team_showdown = json_to_showdown(opp_team)
    results = []
    error_summary: Counter = Counter()
    for mode in modes:
        our_team = MODES[mode]()
        our_team_showdown = json_to_showdown(our_team)
        for p in range(1, args.pairs + 1):
            for arm_flag in [False, True]:
                arm = "on" if arm_flag else "off"
                suffix = f"{p}_{arm}_{int(time.time()*1000) % 100000}"[-12:]
                audit_path = os.path.join(
                    args.audit_dir,
                    f"ss1c_{mode}_{p}_{arm}.jsonl",
                )
                print(
                    f"  Mode={mode} Pair={p} arm={arm.upper()} "
                    f"suffix={suffix}",
                    flush=True,
                )
                # Simple sequential pattern matching WT4g.
                # No retry — if it fails, we record and move on.
                try:
                    r = asyncio.run(
                        run_one_battle(
                            suffix, our_team_showdown,
                            opp_team_showdown, audit_path,
                            arm_flag,
                            args.helping_hand_bonus,
                            args.tailwind_bonus,
                            args.timeout_seconds,
                        )
                    )
                except Exception as e:
                    print(f"    Error: {e}", flush=True)
                    r = {
                        "suffix": suffix,
                        "finished": False,
                        "n_finished": 0,
                        "n_turns": 0,
                        "observations": {
                            HELPING_HAND: {
                                "legal": 0, "selected": 0,
                                "positive": 0,
                            },
                            TAILWIND: {
                                "legal": 0, "selected": 0,
                                "positive": 0,
                            },
                        },
                        "action_distribution": {},
                        "bad_cases": [],
                        "error": str(e),
                        "error_type": classify_error(str(e)),
                    }
                r["mode"] = mode
                r["arm"] = arm
                r["pair"] = p
                results.append(r)
                error_summary[r.get("error_type", "no_error")] += 1
                hh = r["observations"][HELPING_HAND]
                tw = r["observations"][TAILWIND]
                print(
                    f"    finished={r['finished']} "
                    f"turns={r.get('n_turns', 0)} "
                    f"hh_legal={hh['legal']} "
                    f"hh_sel={hh['selected']} "
                    f"hh_pos={hh['positive']} "
                    f"tw_legal={tw['legal']} "
                    f"tw_sel={tw['selected']} "
                    f"tw_pos={tw['positive']} "
                    f"bad={len(r.get('bad_cases', []))} "
                    f"err={r.get('error_type', 'no_error')}",
                    flush=True,
                )
                time.sleep(args.delay_seconds)
    # Aggregate
    summary = {
        "n_pairs": args.pairs,
        "n_modes": len(modes),
        "n_results": len(results),
        "error_summary": dict(error_summary),
        "by_mode_arm": {},
    }
    for mode in modes:
        for arm in ("on", "off"):
            arm_results = [
                r for r in results
                if r.get("mode") == mode and r.get("arm") == arm
            ]
            if not arm_results:
                continue
            key = f"{mode}_{arm}"
            n_finished = sum(
                1 for r in arm_results if r.get("finished")
            )
            n_errors = sum(
                1 for r in arm_results
                if r.get("error_type") not in ("no_error",)
            )
            total_hh_legal = sum(
                r["observations"][HELPING_HAND]["legal"]
                for r in arm_results
            )
            total_hh_selected = sum(
                r["observations"][HELPING_HAND]["selected"]
                for r in arm_results
            )
            total_hh_positive = sum(
                r["observations"][HELPING_HAND]["positive"]
                for r in arm_results
            )
            total_tw_legal = sum(
                r["observations"][TAILWIND]["legal"]
                for r in arm_results
            )
            total_tw_selected = sum(
                r["observations"][TAILWIND]["selected"]
                for r in arm_results
            )
            total_tw_positive = sum(
                r["observations"][TAILWIND]["positive"]
                for r in arm_results
            )
            total_bad = sum(
                len(r.get("bad_cases", []))
                for r in arm_results
            )
            avg_turns = sum(
                r.get("n_turns", 0) for r in arm_results
            ) / len(arm_results)
            # Aggregate action distribution
            action_dist: Counter = Counter()
            for r in arm_results:
                for k, v in r.get(
                    "action_distribution", {}
                ).items():
                    action_dist[k] += v
            summary["by_mode_arm"][key] = {
                "n_finished": n_finished,
                "n_errors": n_errors,
                "avg_turns": round(avg_turns, 1),
                "helpinghand_legal": total_hh_legal,
                "helpinghand_selected": total_hh_selected,
                "helpinghand_positive": total_hh_positive,
                "tailwind_legal": total_tw_legal,
                "tailwind_selected": total_tw_selected,
                "tailwind_positive": total_tw_positive,
                "bad_cases_total": total_bad,
                "action_distribution": dict(action_dist),
            }
    summary["raw_results"] = results
    with open(args.output, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print()
    print("=" * 60)
    print("SUPPORT-SCORING-1C paired eval complete")
    print("=" * 60)
    print(
        f"  Pairs: {args.pairs} | "
        f"Modes: {modes} | "
        f"Results: {len(results)}"
    )
    print(f"  Error summary: {dict(error_summary)}")
    for key, stats in summary["by_mode_arm"].items():
        print(
            f"  {key:25s} finished={stats['n_finished']} "
            f"errors={stats['n_errors']} "
            f"turns={stats['avg_turns']} "
            f"hh_legal={stats['helpinghand_legal']} "
            f"hh_sel={stats['helpinghand_selected']} "
            f"hh_pos={stats['helpinghand_positive']} "
            f"tw_legal={stats['tailwind_legal']} "
            f"tw_sel={stats['tailwind_selected']} "
            f"tw_pos={stats['tailwind_positive']} "
            f"bad={stats['bad_cases_total']}"
        )
    print(f"  Output: {args.output}")


if __name__ == "__main__":
    main()
