#!/usr/bin/env python3
"""Phase WT-4g — small OFF vs ON paired evaluation.

A local-only paired evaluation that runs the
WT-4e 2-Pokemon forced active-setter teams in
OFF vs ON configuration.

For each pair:
* One battle with flag OFF
* One battle with flag ON
* Same custom teams, same opp, same bonus values

Metrics collected:
* battles completed
* crashes/errors
* wins/losses
* average turns
* setter active turns
* WT hook calls on setters
* positive WT bonus count
* selected setters
* bad/redundant setters
* action distribution (attack/protect/switch/support/setter)

Local server only (localhost:8000). No official
server. No commits. No default flip.
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
from poke_env.player.battle_order import DoubleBattleOrder

from bot_doubles_damage_aware import DoublesDamageAwarePlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

HEALTH_URL = "http://localhost:8000"
DEFAULT_PAIRS = 5
MAX_PAIRS = 10
HEARTBEAT_INTERVAL = 30
STALL_TIMEOUT = 180
ARM_TIMEOUT = 300

LOCAL_BASE = "WT4gEval"

WT3_SETTER_IDS = {
    "raindance", "sunnyday", "sandstorm", "snowscape", "hail",
    "electricterrain", "grassyterrain", "mistyterrain",
    "psychicterrain",
}

MODE_TEAMS = {
    "rain": {
        "our": "data/curated_teams/custom/wt4e_rain_2mon.json",
        "opp": "data/curated_teams/custom/wt4e_rain_2mon_opp.json",
        "setter_move": "raindance",
    },
    "sun": {
        "our": "data/curated_teams/custom/wt4e_sun_2mon.json",
        "opp": "data/curated_teams/custom/wt4e_sun_2mon_opp.json",
        "setter_move": "sunnyday",
    },
    "terrain": {
        "our": "data/curated_teams/custom/wt4e_terrain_2mon.json",
        "opp": "data/curated_teams/custom/wt4e_terrain_2mon_opp.json",
        "setter_move": "electricterrain",
    },
}


def check_localhost_healthy(timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def json_to_showdown(team_dict: Dict[str, Any]) -> str:
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


def _norm_move_id(mid: Any) -> str:
    if mid is None:
        return ""
    s = str(mid).lower()
    return (
        s.replace(" ", "").replace("-", "")
        .replace("_", "").replace("'", "")
    )


def _classify_action(
    action: str, setter_move_norm: str
) -> str:
    if not action:
        return "pass"
    a = action.lower()
    if "move " + setter_move_norm in a.replace("-", "").replace(" ", ""):
        return "setter"
    if a.startswith("/choose move"):
        if "protect" in a:
            return "protect"
        if "switch" in a:
            return "switch"
        return "attack"
    if a.startswith("/choose switch"):
        return "switch"
    if "pass" in a:
        return "pass"
    return "support"


def _extract_setter_metrics(
    audit_path: str, setter_move_norm: str
) -> Dict[str, Any]:
    """Walk the audit JSONL and compute activation
    metrics.
    """
    stats: Dict[str, Any] = {
        "n_turns": 0,
        "n_setter_active_turns": 0,
        "n_setter_selected": 0,
        "n_setter_calls": 0,
        "n_setter_positive": 0,
        "n_bad_setter": 0,
        "n_redundant_setter": 0,
        "action_distribution": Counter(),
        "selected_examples": [],
        "setter_active_examples": [],
        "wins": 0,
        "losses": 0,
    }
    if not os.path.exists(audit_path):
        return stats
    with open(audit_path) as f:
        for line in f:
            try:
                battle = json.loads(line)
            except json.JSONDecodeError:
                continue
            for turn in battle.get("audit_turns", []):
                stats["n_turns"] += 1
                action_str = turn.get("action", "")
                action_kind = _classify_action(
                    action_str, setter_move_norm
                )
                stats["action_distribution"][action_kind] += 1
                for k in turn.get(
                    "v4a_selected_joint_key", []
                ):
                    if (
                        isinstance(k, (list, tuple))
                        and len(k) >= 2
                        and str(k[0]) == "move"
                        and _norm_move_id(k[1]) in WT3_SETTER_IDS
                    ):
                        stats["n_setter_selected"] += 1
                        if len(
                            stats["selected_examples"]
                        ) < 5:
                            stats["selected_examples"].append(
                                {
                                    "battle": battle.get(
                                        "battle_tag", "?"
                                    ),
                                    "turn": turn.get("turn"),
                                    "setter": _norm_move_id(
                                        k[1]
                                    ),
                                    "score": turn.get(
                                        "selected_score"
                                    ),
                                }
                            )
            for hook_d in battle.get("wt3_hooks", []):
                if isinstance(hook_d, dict):
                    stats["n_setter_calls"] += 1
                    if hook_d.get("bonus", 0) > 0:
                        stats["n_setter_positive"] += 1
    return stats


async def run_pair(
    pair_idx: int,
    mode: str,
    setter_move_norm: str,
    our_team_showdown: str,
    opp_team_showdown: str,
    enable_wt: bool,
    weather_bonus: float,
    terrain_bonus: float,
    audit_dir: str,
) -> Dict[str, Any]:
    arm = "on" if enable_wt else "off"
    suffix = f"{pair_idx}_{mode}_{arm}_{int(time.time() * 1000) % 100000}"[-12:]
    bot_name = f"{LOCAL_BASE}B_{suffix}"[:18]
    opp_name = f"{LOCAL_BASE}O_{suffix}"[:18]
    audit_path = os.path.join(
        audit_dir, f"wt4g_{mode}_{arm}_{pair_idx}.jsonl"
    )
    audit_logger = DoublesDecisionAuditLogger(
        filepath=audit_path, reset=True, detail_level="top5"
    )
    audit_logger.set_current_battle_meta(
        benchmark_arm=f"wt4g_{mode}_{arm}",
        enable_mega_evolution=False,
        enable_decision_timing_diagnostics=False,
        treatment_side="p1",
        player_side="p1",
        player_name=f"WT4gEval{mode}{arm}",
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
            timeout=ARM_TIMEOUT,
        )
    except asyncio.TimeoutError:
        pass
    except Exception as e:
        return {
            "pair_idx": pair_idx,
            "mode": mode,
            "arm": arm,
            "enable_wt": enable_wt,
            "error": str(e),
            "elapsed_s": time.time() - start,
            "finished": False,
        }
    try:
        await bot.ps_client._stop_listening()
        await opp.ps_client._stop_listening()
    except Exception:
        pass
    finished = bot.n_finished_battles > 0
    stats = _extract_setter_metrics(audit_path, setter_move_norm)
    n_wt3_calls = sum(
        len(dl)
        for dl in getattr(bot, "_wt3_decisions", {}).values()
    )
    n_wt3_setters = sum(
        1
        for bt, dl in getattr(bot, "_wt3_decisions", {}).items()
        for d in dl
        if isinstance(d, dict)
        and d.get("move_id", "") in WT3_SETTER_IDS
    )
    n_wt3_positive = sum(
        1
        for bt, dl in getattr(bot, "_wt3_decisions", {}).items()
        for d in dl
        if isinstance(d, dict)
        and d.get("move_id", "") in WT3_SETTER_IDS
        and d.get("bonus", 0) > 0
    )
    n_wt4c = len(getattr(bot, "_wt4c_inclusions", []))
    return {
        "pair_idx": pair_idx,
        "mode": mode,
        "arm": arm,
        "enable_wt": enable_wt,
        "elapsed_s": time.time() - start,
        "finished": finished,
        "n_finished_battles": bot.n_finished_battles,
        "n_turns": stats["n_turns"],
        "n_setter_active_turns": stats["n_setter_active_turns"],
        "n_setter_selected": stats["n_setter_selected"],
        "n_wt3_calls": n_wt3_calls,
        "n_wt3_setters": n_wt3_setters,
        "n_wt3_positive": n_wt3_positive,
        "n_wt4c": n_wt4c,
        "action_distribution": dict(stats["action_distribution"]),
        "selected_examples": stats["selected_examples"],
        "audit_path": audit_path,
    }


async def run_eval(
    pairs: int,
    modes: List[str],
    weather_bonus: float,
    terrain_bonus: float,
    audit_dir: str,
) -> List[Dict[str, Any]]:
    # Load teams
    teams = {}
    for mode, paths in MODE_TEAMS.items():
        with open(paths["our"]) as f:
            teams.setdefault(mode, {})["our"] = json_to_showdown(
                json.load(f)
            )
        with open(paths["opp"]) as f:
            teams[mode]["opp"] = json_to_showdown(json.load(f))
    results = []
    pair_idx = 0
    for mode in modes:
        for p in range(1, pairs + 1):
            pair_idx += 1
            for arm_flag in [False, True]:
                print(
                    f"  Pair {pair_idx} mode={mode} arm="
                    f"{'ON' if arm_flag else 'OFF'} p={p}",
                    flush=True,
                )
                try:
                    r = await run_pair(
                        pair_idx,
                        mode,
                        MODE_TEAMS[mode]["setter_move"],
                        teams[mode]["our"],
                        teams[mode]["opp"],
                        arm_flag,
                        weather_bonus,
                        terrain_bonus,
                        audit_dir,
                    )
                except Exception as e:
                    r = {
                        "pair_idx": pair_idx,
                        "mode": mode,
                        "arm": "on" if arm_flag else "off",
                        "enable_wt": arm_flag,
                        "error": str(e),
                        "finished": False,
                        "n_turns": 0,
                        "n_setter_selected": 0,
                        "n_wt3_calls": 0,
                        "n_wt3_setters": 0,
                        "n_wt3_positive": 0,
                        "n_wt4c": 0,
                        "action_distribution": {},
                    }
                results.append(r)
                print(
                    f"    finished={r.get('finished')} "
                    f"turns={r.get('n_turns', 0)} "
                    f"setter_sel={r.get('n_setter_selected', 0)} "
                    f"wt3_pos={r.get('n_wt3_positive', 0)}",
                    flush=True,
                )
                # Small delay to avoid rate limiting
                await asyncio.sleep(2)
    return results


def aggregate(
    results: List[Dict[str, Any]], arm_flag: bool
) -> Dict[str, Any]:
    arm_results = [r for r in results if r.get("enable_wt") == arm_flag]
    if not arm_results:
        return {}
    total_turns = sum(r.get("n_turns", 0) for r in arm_results)
    total_setter_selected = sum(
        r.get("n_setter_selected", 0) for r in arm_results
    )
    total_wt3_calls = sum(
        r.get("n_wt3_calls", 0) for r in arm_results
    )
    total_wt3_setters = sum(
        r.get("n_wt3_setters", 0) for r in arm_results
    )
    total_wt3_positive = sum(
        r.get("n_wt3_positive", 0) for r in arm_results
    )
    total_finished = sum(
        1 for r in arm_results if r.get("finished")
    )
    total_errors = sum(
        1 for r in arm_results if "error" in r
    )
    action_dist = Counter()
    for r in arm_results:
        for k, v in r.get("action_distribution", {}).items():
            action_dist[k] += v
    return {
        "arm": "ON" if arm_flag else "OFF",
        "n_pairs": len(arm_results),
        "n_finished": total_finished,
        "n_errors": total_errors,
        "total_turns": total_turns,
        "avg_turns": (
            total_turns / len(arm_results) if arm_results else 0
        ),
        "total_setter_selected": total_setter_selected,
        "total_wt3_calls": total_wt3_calls,
        "total_wt3_setters": total_wt3_setters,
        "total_wt3_positive": total_wt3_positive,
        "action_distribution": dict(action_dist),
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--pairs",
        type=int,
        default=DEFAULT_PAIRS,
    )
    parser.add_argument(
        "--modes",
        default="rain,sun,terrain",
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
        default="logs/wt4g_paired_audits",
    )
    args = parser.parse_args()
    if args.pairs < 1:
        print("ERROR: --pairs must be >= 1")
        sys.exit(1)
    if args.pairs > MAX_PAIRS:
        print(f"ERROR: --pairs must be <= {MAX_PAIRS}")
        sys.exit(1)
    if not check_localhost_healthy():
        print("ERROR: localhost:8000 not healthy; refusing")
        sys.exit(1)
    os.makedirs(args.audit_dir, exist_ok=True)
    modes = args.modes.split(",")
    for m in modes:
        if m not in MODE_TEAMS:
            print(f"ERROR: unknown mode {m}")
            sys.exit(1)
    print("=" * 60)
    print("WT-4g small OFF vs ON paired evaluation")
    print(
        f"  pairs/mode: {args.pairs} | modes: {modes}"
    )
    print("=" * 60)
    results = []
    try:
        results = asyncio.run(
            run_eval(
                args.pairs,
                modes,
                args.weather_bonus,
                args.terrain_bonus,
                args.audit_dir,
            )
        )
    except KeyboardInterrupt:
        print("KeyboardInterrupt - writing partial results")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"ERROR during eval: {e}")
        print("Writing partial results...")
    off_agg = aggregate(results, False)
    on_agg = aggregate(results, True)
    output = {
        "n_results": len(results),
        "off_aggregate": off_agg,
        "on_aggregate": on_agg,
        "raw_results": results,
    }
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print()
    print("=" * 60)
    print("WT-4g small paired eval complete")
    print("=" * 60)
    print(f"  Output: {args.output}")
    print(
        f"  OFF: {off_agg.get('n_finished', 0)}/"
        f"{off_agg.get('n_pairs', 0)} finished | "
        f"setter_sel="
        f"{off_agg.get('total_setter_selected', 0)} | "
        f"wt3_pos="
        f"{off_agg.get('total_wt3_positive', 0)}"
    )
    print(
        f"  ON: {on_agg.get('n_finished', 0)}/"
        f"{on_agg.get('n_pairs', 0)} finished | "
        f"setter_sel="
        f"{on_agg.get('total_setter_selected', 0)} | "
        f"wt3_pos="
        f"{on_agg.get('total_wt3_positive', 0)}"
    )
    off_agg = aggregate(results, False)
    on_agg = aggregate(results, True)
    output = {
        "n_results": len(results),
        "off_aggregate": off_agg,
        "on_aggregate": on_agg,
        "raw_results": results,
    }
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print()
    print("=" * 60)
    print("WT-4g small paired eval complete")
    print("=" * 60)
    print(f"  Output: {args.output}")
    print(
        f"  OFF: {off_agg.get('n_finished', 0)}/"
        f"{off_agg.get('n_pairs', 0)} finished | "
        f"setter_sel="
        f"{off_agg.get('total_setter_selected', 0)} | "
        f"wt3_pos="
        f"{off_agg.get('total_wt3_positive', 0)}"
    )
    print(
        f"  ON: {on_agg.get('n_finished', 0)}/"
        f"{on_agg.get('n_pairs', 0)} finished | "
        f"setter_sel="
        f"{on_agg.get('total_setter_selected', 0)} | "
        f"wt3_pos="
        f"{on_agg.get('total_wt3_positive', 0)}"
    )


if __name__ == "__main__":
    main()
