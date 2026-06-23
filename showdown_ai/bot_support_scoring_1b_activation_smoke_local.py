#!/usr/bin/env python3
"""SUPPORT-SCORING-1B — local activation smoke.

A local-only smoke that runs battles on
localhost:8000 to verify that Helping Hand and
Tailwind positive scoring works end-to-end with
forced support-move visibility.

Uses small custom teams (one setter + one partner
with damaging move) so that the support moves
actually appear in `battle.valid_orders`.

This is **observational only**. It does NOT change
any runtime scoring, behavior, or selected actions.
The support scoring flag is ON for the test arms,
OFF for the baseline arm.

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
LOCAL_BASE = "SS1bAct"

HELPING_HAND = "helpinghand"
TAILWIND = "tailwind"
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


def _make_damaging_move(move_id, base_power=80):
    m = type("M", (), {})()
    m.id = move_id
    m.base_power = base_power
    return m


def _build_helping_hand_team():
    """Oranguru (Helping Hand) + Garchomp (dmg)."""
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
    """Whimsicott (Tailwind) + Garchomp (dmg)."""
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


async def run_one_battle(
    suffix: str,
    our_team_showdown: str,
    opp_team_showdown: str,
    audit_path: str,
    enable_support_scoring: bool,
):
    bot_name = f"{LOCAL_BASE}B_{suffix}"[:18]
    opp_name = f"{LOCAL_BASE}O_{suffix}"[:18]
    audit_logger = DoublesDecisionAuditLogger(
        filepath=audit_path, reset=True, detail_level="top5"
    )
    audit_logger.set_current_battle_meta(
        benchmark_arm=(
            f"ss1b_{'on' if enable_support_scoring else 'off'}"
        ),
        enable_mega_evolution=False,
        enable_decision_timing_diagnostics=False,
        treatment_side="p1",
        player_side="p1",
        player_name=(
            f"SS1b{'On' if enable_support_scoring else 'Off'}"
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
    bot.config.helping_hand_bonus = 120.0
    bot.config.tailwind_bonus = 180.0
    # Verify the audit is observational only. No
    # default flips, no WT, no broad support, no
    # Anti-TR. The adopted narrow ally heal safety
    # remains ON.
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
            timeout=300,
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
    # Check support decisions from the bot instance
    # (they are stored on self._support_decisions, not
    # in the audit JSONL).
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
                for turn in battle.get("audit_turns", []):
                    for slot in (0, 1):
                        legal = (
                            turn.get(
                                "v4a_legal_action_keys_slot" + str(slot),
                                [],
                            )
                            or []
                        )
                        for k in legal:
                            if not (
                                isinstance(k, list) and len(k) >= 2
                            ):
                                continue
                            if str(k[0]) != "move":
                                continue
                            mid = _norm(k[1])
                            if mid not in TARGET_MOVES:
                                continue
                            observations[mid]["legal"] += 1
                            selected_key = turn.get(
                                "v4a_selected_joint_key", []
                            ) or []
                            for sk in selected_key:
                                if (
                                    isinstance(sk, list)
                                    and len(sk) >= 2
                                    and str(sk[0]) == "move"
                                    and _norm(sk[1]) == mid
                                ):
                                    observations[mid]["selected"] += 1
                                    break
    return {
        "suffix": suffix,
        "elapsed_s": time.time() - start,
        "finished": bot.n_finished_battles > 0,
        "n_finished": bot.n_finished_battles,
        "observations": observations,
        "error": error,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--battles-per-mode",
        type=int,
        default=3,
    )
    parser.add_argument(
        "--mode",
        default="all",
        choices=["helpinghand", "tailwind", "all"],
    )
    parser.add_argument(
        "--output",
        default="logs/support_scoring_1b_activation.json",
    )
    parser.add_argument(
        "--audit-dir",
        default="logs/support_scoring_1b_audits",
    )
    args = parser.parse_args()
    if not check_localhost_healthy():
        print("ERROR: localhost:8000 not healthy; refusing")
        sys.exit(1)
    os.makedirs(args.audit_dir, exist_ok=True)
    teams = {
        "helpinghand": _build_helping_hand_team(),
        "tailwind": _build_tailwind_team(),
    }
    opp_team = _build_opp_team()
    opp_team_showdown = json_to_showdown(opp_team)
    modes = (
        ["helpinghand", "tailwind"]
        if args.mode == "all"
        else [args.mode]
    )
    results = []
    for mode in modes:
        our_team = teams[mode]
        our_team_showdown = json_to_showdown(our_team)
        for i in range(1, args.battles_per_mode + 1):
            for arm_flag in [False, True]:
                suffix = (
                    f"{mode}_{i}_{'on' if arm_flag else 'off'}_"
                    f"{int(time.time()*1000) % 100000}"
                )[-12:]
                audit_path = os.path.join(
                    args.audit_dir, f"ss1b_{mode}_{i}_{'on' if arm_flag else 'off'}.jsonl"
                )
                print(
                    f"  Mode={mode} Battle {i}/{args.battles_per_mode} "
                    f"arm={'ON' if arm_flag else 'OFF'}",
                    flush=True,
                )
                try:
                    r = asyncio.run(
                        run_one_battle(
                            suffix, our_team_showdown,
                            opp_team_showdown, audit_path,
                            arm_flag,
                        )
                    )
                    r["mode"] = mode
                    r["arm"] = "on" if arm_flag else "off"
                    results.append(r)
                    obs = r["observations"]
                    print(
                        f"    finished={r['finished']} "
                        f"hh_legal={obs[HELPING_HAND]['legal']} "
                        f"hh_sel={obs[HELPING_HAND]['selected']} "
                        f"hh_pos={obs[HELPING_HAND]['positive']} "
                        f"tw_legal={obs[TAILWIND]['legal']} "
                        f"tw_sel={obs[TAILWIND]['selected']} "
                        f"tw_pos={obs[TAILWIND]['positive']} "
                        f"error={r.get('error')}",
                        flush=True,
                    )
                except Exception as e:
                    print(f"    Error: {e}", flush=True)
                    results.append(
                        {
                            "mode": mode,
                            "arm": "on" if arm_flag else "off",
                            "finished": False,
                            "observations": {
                                HELPING_HAND: {
                                    "legal": 0, "selected": 0, "positive": 0
                                },
                                TAILWIND: {
                                    "legal": 0, "selected": 0, "positive": 0
                                },
                            },
                            "error": str(e),
                        }
                    )
                time.sleep(2)
    # Aggregate
    summary = {
        "n_modes": len(modes),
        "n_battles": len(results),
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
            summary["by_mode_arm"][key] = {
                "n_finished": sum(
                    1 for r in arm_results if r.get("finished")
                ),
                "n_errors": sum(
                    1 for r in arm_results if r.get("error")
                ),
                "helpinghand_legal": sum(
                    r["observations"][HELPING_HAND]["legal"]
                    for r in arm_results
                ),
                "helpinghand_selected": sum(
                    r["observations"][HELPING_HAND]["selected"]
                    for r in arm_results
                ),
                "helpinghand_positive": sum(
                    r["observations"][HELPING_HAND]["positive"]
                    for r in arm_results
                ),
                "tailwind_legal": sum(
                    r["observations"][TAILWIND]["legal"]
                    for r in arm_results
                ),
                "tailwind_selected": sum(
                    r["observations"][TAILWIND]["selected"]
                    for r in arm_results
                ),
                "tailwind_positive": sum(
                    r["observations"][TAILWIND]["positive"]
                    for r in arm_results
                ),
            }
    with open(args.output, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print()
    print("=" * 60)
    print("SUPPORT-SCORING-1B activation smoke complete")
    print("=" * 60)
    for key, stats in summary["by_mode_arm"].items():
        print(
            f"  {key:25s} finished={stats['n_finished']} "
            f"hh_legal={stats['helpinghand_legal']} "
            f"hh_sel={stats['helpinghand_selected']} "
            f"hh_pos={stats['helpinghand_positive']} "
            f"tw_legal={stats['tailwind_legal']} "
            f"tw_sel={stats['tailwind_selected']} "
            f"tw_pos={stats['tailwind_positive']}"
        )
    print(f"  Output: {args.output}")


if __name__ == "__main__":
    main()
