#!/usr/bin/env python3
"""Phase SUPPORT-SCORING-1A — forced visibility audit.

A local-only audit that uses small custom teams with
forced support-move visibility. This proves which
support moves reach the scoring pipeline.

The custom teams are minimal: each team has 2-3
Pokemon, each with 1-2 support moves plus a Protect or
damaging move for switching fallback.

Teams created for this audit (local-only fixtures):
* `wt4e_tailwind_setter.json` — Whimsicott with
  Tailwind + Protect
* `wt4e_wideguard_setter.json` — Farigiraf with
  Wide Guard + Helping Hand + Protect
* `wt4e_helpinghand_setter.json` — Oranguru with
  Helping Hand + Protect
* `wt4e_followme_setter.json` — Togekiss with
  Follow Me + Protect (Follow Me is dual-purpose
  with Aero Blast, but we keep it minimal)

The audit only records what already happens. It does
NOT change any runtime scoring, behavior, or
selected actions. The support safety default is
verified to remain ON.

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
from collections import Counter, defaultdict

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
from doubles_engine.support_scoring_audit import (
    classify_support_move,
    group_support_move,
    is_priority_1b_candidate,
    NOT_OBSERVED,
)

HEALTH_URL = "http://localhost:8000"
LOCAL_BASE = "SS1aForced"


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


async def run_one_battle(
    suffix: str,
    our_team_showdown: str,
    opp_team_showdown: str,
    audit_path: str,
    target_moves: set,
):
    bot_name = f"{LOCAL_BASE}B_{suffix}"[:18]
    opp_name = f"{LOCAL_BASE}O_{suffix}"[:18]
    audit_logger = DoublesDecisionAuditLogger(
        filepath=audit_path, reset=True, detail_level="top5"
    )
    audit_logger.set_current_battle_meta(
        benchmark_arm="ss1a_forced",
        enable_mega_evolution=False,
        enable_decision_timing_diagnostics=False,
        treatment_side="p1",
        player_side="p1",
        player_name="SS1aForced",
    )
    bot = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        audit_logger=audit_logger,
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9doublescustomgame",
        team=our_team_showdown,
    )
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
    observations = []
    if os.path.exists(audit_path):
        with open(audit_path) as f:
            for line in f:
                try:
                    battle = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for turn in battle.get("audit_turns", []):
                    turn_num = turn.get("turn", 0)
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
                            if mid not in target_moves:
                                continue
                            selected_key = turn.get(
                                "v4a_selected_joint_key", []
                            ) or []
                            is_selected = False
                            for sk in selected_key:
                                if (
                                    isinstance(sk, list)
                                    and len(sk) >= 2
                                    and str(sk[0]) == "move"
                                    and _norm(sk[1]) == mid
                                ):
                                    is_selected = True
                                    break
                            target_pos = k[2] if len(k) > 2 else 0
                            obs = {
                                "battle_tag": battle.get(
                                    "battle_tag", "?"
                                ),
                                "turn": turn_num,
                                "slot": slot,
                                "move_id": mid,
                                "in_legal_keys": True,
                                "selected": is_selected,
                                "target_position": target_pos,
                                "classification": (
                                    classify_support_move(mid)
                                ),
                                "group": group_support_move(mid),
                                "is_priority_1b": (
                                    is_priority_1b_candidate(mid)
                                ),
                            }
                            observations.append(obs)
    return {
        "suffix": suffix,
        "elapsed_s": time.time() - start,
        "finished": bot.n_finished_battles > 0,
        "n_finished": bot.n_finished_battles,
        "n_observations": len(observations),
        "observations": observations,
        "error": error,
    }


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--battles",
        type=int,
        default=3,
    )
    parser.add_argument(
        "--output",
        default="logs/support_scoring_1a_visibility.json",
    )
    parser.add_argument(
        "--audit-dir",
        default="logs/support_scoring_1a_audits",
    )
    args = parser.parse_args()
    if not check_localhost_healthy():
        print("ERROR: localhost:8000 not healthy; refusing")
        sys.exit(1)
    os.makedirs(args.audit_dir, exist_ok=True)
    # Local-only custom teams with the target support
    # moves. Each team has 2 Pokemon: one with the
    # target support move + Protect, and one with a
    # simple damaging move + Protect. The opp is a
    # simple RandomPlayer team with 2 Pokemon.
    teams = {
        "tailwind": {
            "our": {
                "team": [
                    {
                        "species": "Whimsicott",
                        "ability": "Prankster",
                        "item": "Leftovers",
                        "evs": {"hp": 252, "spd": 252, "def": 4},
                        "nature": "Bold",
                        "moves": ["Tailwind", "Protect", "Moonblast", "Encore"],
                        "types": ["grass", "fairy"],
                    },
                    {
                        "species": "Garchomp",
                        "ability": "Rough Skin",
                        "item": "Choice Scarf",
                        "evs": {"atk": 252, "spd": 252, "hp": 4},
                        "nature": "Jolly",
                        "moves": ["Earthquake", "Rock Slide", "Scale Shot", "Protect"],
                        "types": ["dragon", "ground"],
                    },
                ]
            },
            "opp": {
                "team": [
                    {
                        "species": "Tyranitar",
                        "ability": "Sand Stream",
                        "item": "Leftovers",
                        "evs": {"hp": 252, "def": 252, "spd": 4},
                        "nature": "Careful",
                        "moves": ["Rock Slide", "Crunch", "Stone Edge", "Protect"],
                        "types": ["rock", "dark"],
                    },
                    {
                        "species": "Gyarados",
                        "ability": "Intimidate",
                        "item": "Leftovers",
                        "evs": {"atk": 252, "spd": 252, "hp": 4},
                        "nature": "Jolly",
                        "moves": ["Waterfall", "Ice Fang", "Dragon Dance", "Protect"],
                        "types": ["water", "flying"],
                    },
                ]
            },
            "moves": {"tailwind"},
        },
        "wideguard": {
            "our": {
                "team": [
                    {
                        "species": "Farigiraf",
                        "ability": "Armor Tail",
                        "item": "Leftovers",
                        "evs": {"hp": 252, "spd": 252, "def": 4},
                        "nature": "Bold",
                        "moves": ["Wide Guard", "Helping Hand", "Protect", "Psychic"],
                        "types": ["normal", "psychic"],
                    },
                    {
                        "species": "Garchomp",
                        "ability": "Rough Skin",
                        "item": "Choice Scarf",
                        "evs": {"atk": 252, "spd": 252, "hp": 4},
                        "nature": "Jolly",
                        "moves": ["Earthquake", "Rock Slide", "Scale Shot", "Protect"],
                        "types": ["dragon", "ground"],
                    },
                ]
            },
            "opp": {
                "team": [
                    {
                        "species": "Tyranitar",
                        "ability": "Sand Stream",
                        "item": "Leftovers",
                        "evs": {"hp": 252, "def": 252, "spd": 4},
                        "nature": "Careful",
                        "moves": ["Rock Slide", "Crunch", "Stone Edge", "Protect"],
                        "types": ["rock", "dark"],
                    },
                    {
                        "species": "Gyarados",
                        "ability": "Intimidate",
                        "item": "Leftovers",
                        "evs": {"atk": 252, "spd": 252, "hp": 4},
                        "nature": "Jolly",
                        "moves": ["Waterfall", "Ice Fang", "Dragon Dance", "Protect"],
                        "types": ["water", "flying"],
                    },
                ]
            },
            "moves": {"wideguard", "helpinghand"},
        },
        "helpinghand": {
            "our": {
                "team": [
                    {
                        "species": "Oranguru",
                        "ability": "Inner Focus",
                        "item": "Leftovers",
                        "evs": {"hp": 252, "spd": 252, "def": 4},
                        "nature": "Calm",
                        "moves": ["Helping Hand", "Protect", "Psychic", "Trick Room"],
                        "types": ["normal", "psychic"],
                    },
                    {
                        "species": "Garchomp",
                        "ability": "Rough Skin",
                        "item": "Choice Scarf",
                        "evs": {"atk": 252, "spd": 252, "hp": 4},
                        "nature": "Jolly",
                        "moves": ["Earthquake", "Rock Slide", "Scale Shot", "Protect"],
                        "types": ["dragon", "ground"],
                    },
                ]
            },
            "opp": {
                "team": [
                    {
                        "species": "Tyranitar",
                        "ability": "Sand Stream",
                        "item": "Leftovers",
                        "evs": {"hp": 252, "def": 252, "spd": 4},
                        "nature": "Careful",
                        "moves": ["Rock Slide", "Crunch", "Stone Edge", "Protect"],
                        "types": ["rock", "dark"],
                    },
                    {
                        "species": "Gyarados",
                        "ability": "Intimidate",
                        "item": "Leftovers",
                        "evs": {"atk": 252, "spd": 252, "hp": 4},
                        "nature": "Jolly",
                        "moves": ["Waterfall", "Ice Fang", "Dragon Dance", "Protect"],
                        "types": ["water", "flying"],
                    },
                ]
            },
            "moves": {"helpinghand"},
        },
        "followme": {
            "our": {
                "team": [
                    {
                        "species": "Togekiss",
                        "ability": "Serene Grace",
                        "item": "Leftovers",
                        "evs": {"hp": 252, "spd": 252, "def": 4},
                        "nature": "Calm",
                        "moves": ["Follow Me", "Protect", "Air Slash", "Thunder Wave"],
                        "types": ["fairy", "flying"],
                    },
                    {
                        "species": "Garchomp",
                        "ability": "Rough Skin",
                        "item": "Choice Scarf",
                        "evs": {"atk": 252, "spd": 252, "hp": 4},
                        "nature": "Jolly",
                        "moves": ["Earthquake", "Rock Slide", "Scale Shot", "Protect"],
                        "types": ["dragon", "ground"],
                    },
                ]
            },
            "opp": {
                "team": [
                    {
                        "species": "Tyranitar",
                        "ability": "Sand Stream",
                        "item": "Leftovers",
                        "evs": {"hp": 252, "def": 252, "spd": 4},
                        "nature": "Careful",
                        "moves": ["Rock Slide", "Crunch", "Stone Edge", "Protect"],
                        "types": ["rock", "dark"],
                    },
                    {
                        "species": "Gyarados",
                        "ability": "Intimidate",
                        "item": "Leftovers",
                        "evs": {"atk": 252, "spd": 252, "hp": 4},
                        "nature": "Jolly",
                        "moves": ["Waterfall", "Ice Fang", "Dragon Dance", "Protect"],
                        "types": ["water", "flying"],
                    },
                ]
            },
            "moves": {"followme"},
        },
    }
    results = []
    for team_name, cfg in teams.items():
        our_team = json_to_showdown(cfg["our"])
        opp_team = json_to_showdown(cfg["opp"])
        target_moves = cfg["moves"]
        for i in range(1, args.battles + 1):
            suffix = (
                f"{team_name}_{i}_{int(time.time()*1000) % 100000}"
            )[-12:]
            audit_path = os.path.join(
                args.audit_dir, f"ss1a_{team_name}_{i}.jsonl"
            )
            print(
                f"  Team={team_name} Battle {i}/{args.battles}",
                flush=True,
            )
            try:
                r = asyncio.run(
                    run_one_battle(
                        suffix, our_team, opp_team,
                        audit_path, target_moves,
                    )
                )
                results.append(
                    {"team": team_name, **r}
                )
                print(
                    f"    finished={r['finished']} "
                    f"obs={r['n_observations']} "
                    f"error={r.get('error')}",
                    flush=True,
                )
            except Exception as e:
                print(f"    Error: {e}", flush=True)
                results.append(
                    {
                        "team": team_name,
                        "suffix": suffix,
                        "finished": False,
                        "n_observations": 0,
                        "observations": [],
                        "error": str(e),
                    }
                )
            time.sleep(2)
    by_move = defaultdict(lambda: {
        "in_legal_keys": 0,
        "selected": 0,
        "turns_seen": 0,
        "classification": None,
    })
    for r in results:
        for obs in r.get("observations", []):
            mid = obs["move_id"]
            by_move[mid]["in_legal_keys"] += 1
            if obs["selected"]:
                by_move[mid]["selected"] += 1
            by_move[mid]["turns_seen"] += 1
            by_move[mid]["classification"] = obs[
                "classification"
            ]
    summary = {
        "n_battles": len(results),
        "n_finished": sum(
            r.get("n_finished", 0) for r in results
        ),
        "n_errors": sum(1 for r in results if r.get("error")),
        "by_team": {
            tn: {
                "n_finished": sum(
                    r.get("n_finished", 0)
                    for r in results if r.get("team") == tn
                ),
                "n_observations": sum(
                    r.get("n_observations", 0)
                    for r in results if r.get("team") == tn
                ),
            }
            for tn in teams
        },
        "by_move": dict(by_move),
        "raw_results": results,
    }
    with open(args.output, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print()
    print("=" * 60)
    print("SUPPORT-SCORING-1A forced visibility audit complete")
    print("=" * 60)
    print(
        f"  Battles: {len(results)} | "
        f"Finished: {summary['n_finished']} | "
        f"Errors: {summary['n_errors']}"
    )
    for tn, st in summary["by_team"].items():
        print(
            f"  Team {tn}: finished={st['n_finished']} "
            f"obs={st['n_observations']}"
        )
    print("  Move observations (in_legal_keys / selected):")
    for mid, stats in sorted(by_move.items()):
        print(
            f"    {mid:20s} "
            f"legal={stats['in_legal_keys']:3d} "
            f"sel={stats['selected']:3d} "
            f"class={stats['classification']}"
        )
    print(f"  Output: {args.output}")


if __name__ == "__main__":
    main()
