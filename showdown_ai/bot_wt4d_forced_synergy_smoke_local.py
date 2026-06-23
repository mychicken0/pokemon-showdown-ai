#!/usr/bin/env python3
"""Phase WT-4d — Forced Weather/Terrain Synergy
Activation Smoke.

A targeted local-only smoke that uses custom teams
to create favorable matchups where the opt-in
WT-3 / WT-4c scoring path should naturally
activate.

Three modes:
* rain: bot has Politoed (Rain Dance + Hydro Pump)
  vs opp with no Water/Thunder/Hurricane moves
* sun: bot has Arcanine (Flare Blitz) vs opp with
  no Fire/Solar Beam moves
* terrain: bot has Jolteon (Electric Terrain +
  Thunderbolt) vs opp with no Electric moves

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
from typing import Any, Dict, List, Optional, Tuple

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
DEFAULT_BATTLES_PER_MODE = 3
MAX_BATTLES = 20
HEARTBEAT_INTERVAL = 30
STALL_TIMEOUT = 180
ARM_TIMEOUT = 300

# Our team: WT-2 audit team (has Politoed/Rillaboom setters)
OUR_TEAM_JSON = "data/curated_teams/custom/wt2_audit_team_v1.json"

# Opp teams per mode (all have NO opposing synergy)
OPP_TEAM_FILES = {
    "rain": "data/curated_teams/custom/wt4d_rain_favorable_opp.json",
    "sun": "data/curated_teams/custom/wt4d_sun_favorable_opp.json",
    "terrain": "data/curated_teams/custom/wt4d_terrain_favorable_opp.json",
}

LOCAL_BASE = "WT4dSmoke"


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


WT3_SETTER_IDS = {
    "raindance", "sunnyday", "sandstorm", "snowscape", "hail",
    "electricterrain", "grassyterrain", "mistyterrain",
    "psychicterrain",
}


async def run_single_battle(
    idx: int,
    total: int,
    audit_logger: DoublesDecisionAuditLogger,
    our_team_showdown: str,
    opp_team_showdown: str,
    enable_wt3: bool,
    weather_bonus: float,
    terrain_bonus: float,
) -> Dict[str, Any]:
    suffix = str(idx) + str(int(time.time() * 1000) % 100000)[-5:]
    bot_name = f"{LOCAL_BASE}Bot_{suffix}"[:18]
    opp_name = f"{LOCAL_BASE}Opp_{suffix}"[:18]

    bot = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        audit_logger=audit_logger,
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9doublescustomgame",
        team=our_team_showdown,
    )
    bot.config.enable_weather_terrain_positive_scoring = (
        enable_wt3
    )
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

    async def heartbeat():
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            elapsed = time.time() - start
            print(
                f"  [{idx}/{total}] {elapsed:.0f}s | "
                f"finished={bot.n_finished_battles}",
                flush=True,
            )

    battle_task = asyncio.create_task(
        bot.battle_against(opp, n_battles=1)
    )
    hb_task = asyncio.create_task(heartbeat())
    try:
        await asyncio.wait_for(
            asyncio.wait(
                {battle_task}, return_when=asyncio.FIRST_COMPLETED
            ),
            timeout=ARM_TIMEOUT,
        )
    except asyncio.TimeoutError:
        print(
            f"  [{idx}] TIMEOUT",
            flush=True,
        )
    finally:
        hb_task.cancel()
        try:
            await bot.ps_client._stop_listening()
            await opp.ps_client._stop_listening()
        except Exception:
            pass

    return {
        "battle_idx": idx,
        "elapsed_s": time.time() - start,
        "bot_finished": bot.n_finished_battles,
        "wt3_decisions": getattr(bot, "_wt3_decisions", {}),
        "wt4c_inclusions": getattr(
            bot, "_wt4c_inclusions", []
        ),
    }


def _analyze_audit(audit_path: str) -> Dict[str, Any]:
    """Walk the audit JSONL and compute activation
    metrics.
    """
    stats: Dict[str, Any] = {
        "n_turns": 0,
        "n_legal_setters": 0,
        "n_setter_selected": 0,
        "n_wt3_setter_decisions": 0,
        "n_wt3_positive_bonus": 0,
        "n_wt4c_inclusions": 0,
        "selected_examples": [],
        "positive_bonus_examples": [],
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
                # Check if a setter was selected
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
                                    "selected_score": (
                                        turn.get(
                                            "selected_score"
                                        )
                                    ),
                                }
                            )
                # Count legal setters
                for sk in (
                    "v4a_legal_action_keys_slot0",
                    "v4a_legal_action_keys_slot1",
                ):
                    for k in turn.get(sk, []):
                        if (
                            isinstance(k, (list, tuple))
                            and len(k) >= 2
                            and str(k[0]) == "move"
                            and _norm_move_id(k[1])
                            in WT3_SETTER_IDS
                        ):
                            stats["n_legal_setters"] += 1
                            break
                    else:
                        continue
                    break
    return stats


async def run_mode(
    mode: str,
    total_modes: int,
    battles: int,
    our_team_showdown: str,
    opp_team_showdown: str,
    enable_wt3: bool,
    weather_bonus: float,
    terrain_bonus: float,
    audit_dir: str,
) -> Dict[str, Any]:
    audit_path = os.path.join(
        audit_dir, f"wt4d_{mode}_audit.jsonl"
    )
    audit_logger = DoublesDecisionAuditLogger(
        filepath=audit_path, reset=True, detail_level="top5"
    )
    audit_logger.set_current_battle_meta(
        benchmark_arm=f"wt4d_{mode}",
        enable_mega_evolution=False,
        enable_decision_timing_diagnostics=False,
        treatment_side="p1",
        player_side="p1",
        player_name=f"WT4dSmoke{mode}",
    )
    print(
        f"=== Mode {mode} ({total_modes}/{len(OPP_TEAM_FILES)}): "
        f"enable_wt3={enable_wt3} w={weather_bonus:.0f} "
        f"t={terrain_bonus:.0f} battles={battles} ===",
        flush=True,
    )
    results = []
    for idx in range(1, battles + 1):
        try:
            r = await run_single_battle(
                idx, battles, audit_logger, our_team_showdown,
                opp_team_showdown, enable_wt3, weather_bonus,
                terrain_bonus,
            )
            results.append(r)
        except Exception as e:
            print(f"  Battle {idx} failed: {e}", flush=True)
            results.append(
                {"battle_idx": idx, "error": str(e)}
            )
    stats = _analyze_audit(audit_path)
    # Add WT-3 decisions and WT-4c inclusions
    n_setter_decisions = 0
    n_positive = 0
    n_inclusions = 0
    inclusions = []
    for r in results:
        for bt, dl in r.get("wt3_decisions", {}).items():
            for d in dl:
                if (
                    isinstance(d, dict)
                    and d.get("move_id", "")
                    in WT3_SETTER_IDS
                ):
                    n_setter_decisions += 1
                    if d.get("bonus", 0) > 0:
                        n_positive += 1
                        if len(
                            stats["positive_bonus_examples"]
                        ) < 5:
                            stats[
                                "positive_bonus_examples"
                            ].append(
                                {
                                    "battle": bt,
                                    "turn": d.get("turn"),
                                    "setter": d.get("move_id"),
                                    "bonus": d.get("bonus"),
                                    "reason": d.get("reason"),
                                }
                            )
        inclusions.extend(r.get("wt4c_inclusions", []))
        n_inclusions += len(r.get("wt4c_inclusions", []))
    stats["n_wt3_setter_decisions"] = n_setter_decisions
    stats["n_wt3_positive_bonus"] = n_positive
    stats["n_wt4c_inclusions"] = n_inclusions
    stats["wt4c_inclusion_examples"] = inclusions[:5]
    n_finished = sum(
        1
        for r in results
        if "error" not in r
        and r.get("bot_finished", 0) > 0
    )
    print(
        f"  finished: {n_finished}/{battles} | "
        f"legal_setters: {stats['n_legal_setters']} | "
        f"wt3_setter_decisions: {n_setter_decisions} | "
        f"wt3_positive: {n_positive} | "
        f"wt4c_inclusions: {n_inclusions} | "
        f"setter_selected: {stats['n_setter_selected']}",
        flush=True,
    )
    return {
        "mode": mode,
        "n_finished": n_finished,
        "audit_path": audit_path,
        "stats": stats,
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        default="all",
        choices=["rain", "sun", "terrain", "all"],
    )
    parser.add_argument(
        "--battles-per-mode",
        type=int,
        default=DEFAULT_BATTLES_PER_MODE,
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
        default="logs/wt4d_forced_synergy_activation.json",
    )
    parser.add_argument(
        "--audit-dir",
        default="logs/wt4d_forced_synergy_audits",
    )
    args = parser.parse_args()

    if args.battles_per_mode < 1:
        print("ERROR: --battles-per-mode must be >= 1")
        sys.exit(1)
    if args.battles_per_mode > MAX_BATTLES:
        print(
            f"ERROR: --battles-per-mode must be <= {MAX_BATTLES}"
        )
        sys.exit(1)

    if not check_localhost_healthy():
        print(
            "ERROR: localhost:8000 not healthy; refusing to run."
        )
        sys.exit(1)

    os.makedirs(args.audit_dir, exist_ok=True)
    with open(OUR_TEAM_JSON) as f:
        our_team_data = json.load(f)
    our_team_showdown = json_to_showdown(our_team_data)

    # Load opp teams
    opp_teams = {}
    for mode, path in OPP_TEAM_FILES.items():
        with open(path) as f:
            opp_teams[mode] = json_to_showdown(json.load(f))

    modes = (
        ["rain", "sun", "terrain"]
        if args.mode == "all"
        else [args.mode]
    )

    print("=" * 60)
    print("WT-4d forced synergy activation smoke")
    print(
        f"  modes: {modes} | "
        f"battles/mode: {args.battles_per_mode}"
    )
    print("=" * 60)

    all_results = []
    for mode in modes:
        r = asyncio.run(
            run_mode(
                mode, len(modes), args.battles_per_mode,
                our_team_showdown, opp_teams[mode],
                True, args.weather_bonus, args.terrain_bonus,
                args.audit_dir,
            )
        )
        all_results.append(r)

    # Write output
    output = {
        "modes": all_results,
        "summary": {
            "n_modes": len(all_results),
            "modes_with_activation": sum(
                1
                for r in all_results
                if r["stats"]["n_wt3_positive_bonus"] > 0
            ),
            "modes_with_selection": sum(
                1
                for r in all_results
                if r["stats"]["n_setter_selected"] > 0
            ),
            "modes_with_inclusion": sum(
                1
                for r in all_results
                if r["stats"]["n_wt4c_inclusions"] > 0
            ),
        },
    }
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print()
    print("=" * 60)
    print("WT-4d forced synergy smoke complete")
    print("=" * 60)
    print(f"  Output: {args.output}")
    print(
        f"  Modes with WT-3 positive bonus: "
        f"{output['summary']['modes_with_activation']}/"
        f"{output['summary']['n_modes']}"
    )
    print(
        f"  Modes with WT-4c inclusions: "
        f"{output['summary']['modes_with_inclusion']}/"
        f"{output['summary']['n_modes']}"
    )
    print(
        f"  Modes with setter selection: "
        f"{output['summary']['modes_with_selection']}/"
        f"{output['summary']['n_modes']}"
    )


if __name__ == "__main__":
    main()
