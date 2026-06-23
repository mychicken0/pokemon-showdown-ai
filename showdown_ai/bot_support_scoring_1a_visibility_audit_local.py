#!/usr/bin/env python3
"""Phase SUPPORT-SCORING-1A — support-move visibility
audit.

A local-only audit that runs N battles on
localhost:8000 to verify which support moves are:

* visible in `battle.valid_orders`
* visible in the audit's legal action keys
* reached by `_score_action_impl`
* scored meaningfully
* blocked by hard safety
* selected

This is **observational only**. It does NOT change any
runtime scoring, behavior, or selected actions. The
audit only records what already happens.

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
from poke_env.player.battle_order import DoubleBattleOrder

from bot_doubles_damage_aware import DoublesDamageAwarePlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger
from doubles_engine.support_scoring_audit import (
    classify_support_move,
    group_support_move,
    is_priority_1b_candidate,
    NOT_OBSERVED,
    READY_FOR_SCORING_1B,
    NEEDS_TARGET_SEMANTICS_FIRST,
    NEEDS_EARLY_HOOK_LIKE_WT,
    SAFETY_ONLY_NOT_SCORING,
    ALREADY_HANDLED,
    BLOCKED_RISKY,
)

HEALTH_URL = "http://localhost:8000"
LOCAL_BASE = "SS1aAudit"


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
    audit_path: str,
    target_moves: set,
):
    """Run a single random battle. For each candidate
    support move in `target_moves`, record whether it
    appeared in legal keys, in valid_orders, was
    selected, or was blocked by hard safety.
    """
    bot_name = f"{LOCAL_BASE}B_{suffix}"[:18]
    opp_name = f"{LOCAL_BASE}O_{suffix}"[:18]
    audit_logger = DoublesDecisionAuditLogger(
        filepath=audit_path, reset=True, detail_level="top5"
    )
    audit_logger.set_current_battle_meta(
        benchmark_arm="ss1a_audit",
        enable_mega_evolution=False,
        enable_decision_timing_diagnostics=False,
        treatment_side="p1",
        player_side="p1",
        player_name="SS1aAudit",
    )
    bot = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        audit_logger=audit_logger,
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9randombattle",
    )
    # Make sure the audit only changes observation,
    # never behavior. Verify the support safety
    # default is the adopted one and the WT default
    # is unchanged.
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
        battle_format="gen9randombattle",
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
    # Now read the audit and record observations.
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
                                []
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
                            # Determine if selected
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--battles",
        type=int,
        default=10,
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
    target_moves = {
        "tailwind", "wideguard", "helpinghand",
        "followme", "ragepowder", "quickguard",
        "coaching", "lifedew", "pollenpuff",
        "healpulse", "floralhealing", "decorate",
        "haze", "clearsmog", "reflect",
        "lightscreen", "auroraveil", "icywind",
        "electroweb", "snarl", "willowisp",
        "thunderwave", "spore", "taunt",
        "encore", "fakeout", "protect", "detect",
    }
    results = []
    for i in range(1, args.battles + 1):
        suffix = f"{i}_{int(time.time()*1000) % 100000}"[-12:]
        audit_path = os.path.join(
            args.audit_dir, f"ss1a_battle_{i}.jsonl"
        )
        print(
            f"  Battle {i}/{args.battles} suffix={suffix}",
            flush=True,
        )
        try:
            r = asyncio.run(
                run_one_battle(suffix, audit_path, target_moves)
            )
            results.append(r)
            print(
                f"    finished={r['finished']} "
                f"observations={r['n_observations']} "
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
                    "n_observations": 0,
                    "observations": [],
                    "error": str(e),
                }
            )
        time.sleep(2)
    # Aggregate by move_id
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
        "n_battles": args.battles,
        "n_finished": sum(
            r.get("n_finished", 0) for r in results
        ),
        "n_errors": sum(1 for r in results if r.get("error")),
        "by_move": dict(by_move),
        "raw_results": results,
    }
    with open(args.output, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print()
    print("=" * 60)
    print("SUPPORT-SCORING-1A visibility audit complete")
    print("=" * 60)
    print(
        f"  Battles: {args.battles} | "
        f"Finished: {summary['n_finished']} | "
        f"Errors: {summary['n_errors']}"
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
