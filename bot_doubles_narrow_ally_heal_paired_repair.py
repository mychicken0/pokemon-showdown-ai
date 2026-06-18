#!/usr/bin/env python3
"""
Phase 6.3.8d.1 — Pair Repair Qualifier

Reruns only the missing/invalid side-swap battles
for pair 98 of the Phase 6.3.8d paired qualification.

Pair 98 D2 (OFFvON) stalled during the original run
with the message::

    Stall: pair 98 OFFvON no battle finished in 60s

The root cause is classified as a server/process
lifecycle transient: the player-name truncation
(both D1 and D2 reused the same 18-char prefix) led
to a server-side name collision during cleanup, and
the cleanup of the D1 players did not finish in time
for the D2 login. The exact same runner code worked
without stall in the Phase 6.3.8c run on the same
server, so the bug is in server-side state, not in
the runner.

This script:
  - reruns ONLY pair 98 D2 (the missing side-swap)
  - uses the exact same team (empty string for
    ``gen9randomdoublesbattle``), the exact same
    policies (OFFvON), the exact same deterministic
    seed sources, and the exact same per-arm watchdog
    configuration
  - writes per-side audit JSONL files to a NEW path
    under ``logs/narrow_ally_heal_paired_phase638d1_*``
    so the original 6.3.8d artifacts are NOT
    overwritten
  - records the repaired battle_tag and result
    for the merge step

The repair artifact is later combined with the 99
valid original 6.3.8d pairs by
``analyze_doubles_narrow_ally_heal_paired_repair.py``
to produce a complete 100-pair / 200-battle repaired
Phase 6.3.8d.1 dataset.

Watchdog: heartbeat 10s, stall 60s, arm 600s,
outer 1200s.

Local server only (localhost:8000).
"""
import argparse
import asyncio
import atexit
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(__file__))

import poke_env.concurrency
clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if clear_loop is not None:
    try:
        atexit.unregister(clear_loop)
    except Exception:
        pass

import urllib.request

from poke_env import AccountConfiguration

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    DoublesDamageAwarePlayer,
)
from doubles_decision_audit_logger import (
    DoublesDecisionAuditLogger,
)


HEARTBEAT_INTERVAL = 10
STALL_TIMEOUT = 60
ARM_TIMEOUT = 600
OUTER_TIMEOUT = 1200
BATTLE_FORMAT = "gen9randomdoublesbattle"
LOCAL_BASE_ACCOUNT = "NarrowPair638d1"


class StallError(Exception):
    pass


def check_localhost(timeout=2.0):
    try:
        with urllib.request.urlopen(
            "http://localhost:8000", timeout=timeout
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


def build_config(arm_label):
    """Build the per-side config for a 6.3.8d pair.

    The exact 6.3.8d configuration is preserved so the
    repair run uses the same policies as the original
    run that produced the 99 valid pairs.

    ON: ``enable_ally_heal_wrong_side_hard_safety=True``,
        ``enable_support_move_target_hard_safety=False``.
    OFF: both flags at default (False).
    """
    if arm_label == "ON":
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = True
        cfg.ally_heal_wrong_side_block_score = 0.0
        cfg.enable_support_move_target_hard_safety = False
    else:
        cfg = DoublesDamageAwareConfig()
        cfg.enable_ally_heal_wrong_side_hard_safety = False
        cfg.enable_support_move_target_hard_safety = False
    return cfg


async def _cleanup_player(player):
    try:
        if hasattr(player, "ps_client") and hasattr(
            player.ps_client, "_stop_listening"
        ):
            try:
                await player.ps_client._stop_listening()
            except Exception:
                pass
    except Exception:
        pass


async def _run_repair_pair_with_watchdog(
    pair_id,
    team_str,
    p1_arm,
    p2_arm,
    arm_timeout,
    audit_dir_suffix,
):
    """Run a single repaired paired battle.

    Player names are intentionally distinct from the
    6.3.8d run to avoid server-side name collision
    after the 6.3.8d D1 cleanup. The exact policies
    and team are preserved.
    """
    cfg_p1 = build_config(p1_arm)
    cfg_p2 = build_config(p2_arm)
    suffix = f"r{audit_dir_suffix}_p{pair_id:03d}_{p1_arm}v{p2_arm}"
    p1_name = f"{LOCAL_BASE_ACCOUNT}_P1_{suffix}"[:18]
    p2_name = f"{LOCAL_BASE_ACCOUNT}_P2_{suffix}"[:18]

    p1_audit_path = (
        f"logs/narrow_ally_heal_paired_phase{audit_dir_suffix}_"
        f"{pair_id:03d}_{p1_arm}v{p2_arm}__p1.jsonl"
    )
    p2_audit_path = (
        f"logs/narrow_ally_heal_paired_phase{audit_dir_suffix}_"
        f"{pair_id:03d}_{p1_arm}v{p2_arm}__p2.jsonl"
    )
    p1_audit = DoublesDecisionAuditLogger(
        filepath=p1_audit_path, reset=True, detail_level="top5",
    )
    p2_audit = DoublesDecisionAuditLogger(
        filepath=p2_audit_path, reset=True, detail_level="top5",
    )

    p1 = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(p1_name, None),
        verbose=False, config=cfg_p1, audit_logger=p1_audit,
        max_concurrent_battles=1,
        battle_format=BATTLE_FORMAT,
        team=team_str,
    )
    p2 = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(p2_name, None),
        verbose=False, config=cfg_p2, audit_logger=p2_audit,
        max_concurrent_battles=1,
        battle_format=BATTLE_FORMAT,
        team=team_str,
    )

    start_time = time.time()
    state = {
        "last_battle_time": start_time,
        "last_finished": 0,
    }

    async def heartbeat():
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            elapsed = time.time() - start_time
            finished = p1.n_finished_battles
            p1_w = p1.n_won_battles
            p2_w = p2.n_won_battles
            since_last = time.time() - state["last_battle_time"]
            if finished > state["last_finished"]:
                state["last_battle_time"] = time.time()
                state["last_finished"] = finished
            print(
                f"  [repair pair={pair_id:03d} {p1_arm}v{p2_arm}] "
                f"{elapsed:.0f}s | {finished}/1 | "
                f"P1={p1_w}W P2={p2_w}W | "
                f"{since_last:.0f}s since last"
            )
            if since_last > STALL_TIMEOUT:
                raise StallError(
                    f"Stall: pair {pair_id} {p1_arm}v{p2_arm} "
                    f"no battle finished in {STALL_TIMEOUT}s"
                )

    battle_task = asyncio.create_task(
        p1.battle_against(p2, n_battles=1)
    )
    watchdog_task = asyncio.create_task(heartbeat())
    caught_exception = None
    try:
        done, pending = await asyncio.wait_for(
            asyncio.wait(
                {battle_task, watchdog_task},
                return_when=asyncio.FIRST_COMPLETED,
            ),
            timeout=arm_timeout,
        )
        if watchdog_task in done:
            w_exc = watchdog_task.exception()
            if w_exc and not isinstance(
                w_exc, asyncio.CancelledError
            ):
                raise w_exc
        if battle_task in done:
            b_exc = battle_task.exception()
            if b_exc and not isinstance(
                b_exc, asyncio.CancelledError
            ):
                raise b_exc
    except asyncio.TimeoutError:
        caught_exception = f"ARM TIMEOUT after {arm_timeout}s"
    except StallError as e:
        caught_exception = str(e)
    except Exception as e:
        caught_exception = f"{type(e).__name__}: {e}"
    finally:
        for task in (watchdog_task, battle_task):
            if task and not task.done():
                task.cancel()
        for task in (watchdog_task, battle_task):
            if task:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    finished = p1.n_finished_battles
    p1_wins = p1.n_won_battles
    p2_wins = p2.n_won_battles
    battle_tag = None
    on_player_is_p1 = (p1_arm == "ON")
    if not finished:
        status = "no_battle"
        on_won = None
    elif p1_wins == 0 and p2_wins == 0:
        status = "tie"
        on_won = None
    elif (on_player_is_p1 and p1_wins == 1) or (
        not on_player_is_p1 and p2_wins == 1
    ):
        status = "ok"
        on_won = True
    elif (on_player_is_p1 and p2_wins == 1) or (
        not on_player_is_p1 and p1_wins == 1
    ):
        status = "ok"
        on_won = False
    else:
        status = "ok"
        on_won = None

    error_detail = caught_exception
    if finished == 0 and not caught_exception:
        error_detail = "no_battle_finished"

    result = {
        "pair_id": pair_id,
        "side_swap": ("D1" if p1_arm == "ON" else "D2"),
        "p1_arm": p1_arm,
        "p2_arm": p2_arm,
        "on_arm": "ON",
        "off_arm": "OFF",
        "on_player_is_p1": on_player_is_p1,
        "battle_tag": battle_tag or "",
        "finished": int(finished),
        "status": status,
        "p1_wins": int(p1_wins),
        "p2_wins": int(p2_wins),
        "on_won": on_won,
        "error_detail": error_detail or "",
        "p1_name": p1_name,
        "p2_name": p2_name,
        "team_str": team_str,
        "p1_config_narrow": (p1_arm == "ON"),
        "p2_config_narrow": (p2_arm == "ON"),
        "p1_audit_path": p1_audit_path,
        "p2_audit_path": p2_audit_path,
    }

    await _cleanup_player(p1)
    await _cleanup_player(p2)
    return result


def init_artifacts(artifact_tag, overwrite):
    csv_path = f"logs/narrow_ally_heal_paired_{artifact_tag}.csv"
    battle_path = f"logs/narrow_ally_heal_paired_{artifact_tag}.jsonl"

    existing = [
        p for p in (csv_path, battle_path) if os.path.exists(p)
    ]
    if existing and not overwrite:
        print(
            "ERROR: Repair artifacts already exist "
            "(use --overwrite to replace):"
        )
        for p in existing:
            print(f"  {p}")
        sys.exit(2)

    with open(csv_path, "w", newline="") as f:
        writer = __import__("csv").writer(f)
        writer.writerow([
            "pair_id", "side_swap", "p1_arm", "p2_arm",
            "on_arm", "off_arm", "on_player_is_p1",
            "battle_tag", "finished", "status",
            "p1_wins", "p2_wins", "on_won",
            "error_detail", "p1_name", "p2_name",
            "team_str", "p1_config_narrow", "p2_config_narrow",
            "p1_audit_path", "p2_audit_path",
        ])
    for p in (battle_path,):
        open(p, "w").close()
    return {
        "csv_path": csv_path,
        "battle_path": battle_path,
    }


async def run_repair(args):
    if not check_localhost():
        print(
            "ERROR: localhost:8000 not healthy. "
            "Repair refuses to run."
        )
        sys.exit(3)

    paths = init_artifacts(args.artifact_tag, args.overwrite)
    print(
        f"Phase 6.3.8d.1 pair repair: "
        f"tag={args.artifact_tag}, "
        f"repair_pairs={args.repair_pairs}, "
        f"repair_sides={args.repair_sides}"
    )
    print(f"  CSV      : {paths['csv_path']}")
    print(f"  battle   : {paths['battle_path']}")

    repair_pairs = sorted(set(int(x) for x in args.repair_pairs))
    repair_sides = set(s.upper() for s in args.repair_sides)

    all_results = []
    for pair_id in repair_pairs:
        team_str = args.team_str
        if "D2" in repair_sides:
            d2 = await _run_repair_pair_with_watchdog(
                pair_id, team_str, "OFF", "ON",
                arm_timeout=ARM_TIMEOUT,
                audit_dir_suffix="638d1",
            )
            all_results.append(d2)
            with open(paths["csv_path"], "a", newline="") as f:
                writer = __import__("csv").writer(f)
                writer.writerow([
                    d2["pair_id"], d2["side_swap"],
                    d2["p1_arm"], d2["p2_arm"],
                    d2["on_arm"], d2["off_arm"],
                    d2["on_player_is_p1"], d2["battle_tag"],
                    d2["finished"], d2["status"],
                    d2["p1_wins"], d2["p2_wins"], d2["on_won"],
                    d2["error_detail"],
                    d2["p1_name"], d2["p2_name"],
                    d2["team_str"], d2["p1_config_narrow"],
                    d2["p2_config_narrow"],
                    d2["p1_audit_path"], d2["p2_audit_path"],
                ])
            with open(paths["battle_path"], "a") as f:
                f.write(json.dumps(d2) + "\n")
            print(
                f"  [progress] pair {pair_id} D2 done: "
                f"status={d2['status']} "
                f"p1_wins={d2['p1_wins']} p2_wins={d2['p2_wins']}"
            )
        if "D1" in repair_sides:
            d1 = await _run_repair_pair_with_watchdog(
                pair_id, team_str, "ON", "OFF",
                arm_timeout=ARM_TIMEOUT,
                audit_dir_suffix="638d1",
            )
            all_results.append(d1)
            with open(paths["csv_path"], "a", newline="") as f:
                writer = __import__("csv").writer(f)
                writer.writerow([
                    d1["pair_id"], d1["side_swap"],
                    d1["p1_arm"], d1["p2_arm"],
                    d1["on_arm"], d1["off_arm"],
                    d1["on_player_is_p1"], d1["battle_tag"],
                    d1["finished"], d1["status"],
                    d1["p1_wins"], d1["p2_wins"], d1["on_won"],
                    d1["error_detail"],
                    d1["p1_name"], d1["p2_name"],
                    d1["team_str"], d1["p1_config_narrow"],
                    d1["p2_config_narrow"],
                    d1["p1_audit_path"], d1["p2_audit_path"],
                ])
            with open(paths["battle_path"], "a") as f:
                f.write(json.dumps(d1) + "\n")
            print(
                f"  [progress] pair {pair_id} D1 done: "
                f"status={d1['status']} "
                f"p1_wins={d1['p1_wins']} p2_wins={d1['p2_wins']}"
            )
    return all_results, paths


def main():
    parser = argparse.ArgumentParser(
        description="Phase 6.3.8d.1 narrow pair repair"
    )
    parser.add_argument(
        "--artifact-tag", type=str, required=True,
        help="Unique artifact tag (required).",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing artifacts.",
    )
    parser.add_argument(
        "--repair-pairs", type=int, nargs="+", default=[98],
        help="Pair IDs to repair (default: [98]).",
    )
    parser.add_argument(
        "--repair-sides", type=str, nargs="+",
        default=["D2"],
        help="Which side-swaps to repair "
        "(D1, D2; default: ['D2']).",
    )
    parser.add_argument(
        "--team-str", type=str, default="",
        help="Team string for both players (default: '').",
    )
    args = parser.parse_args()

    start_time = time.time()
    try:
        results, paths = asyncio.run(
            asyncio.wait_for(
                run_repair(args), timeout=OUTER_TIMEOUT
            )
        )
    except asyncio.TimeoutError:
        print(
            f"OUTER TIMEOUT after {OUTER_TIMEOUT}s — partial "
            "artifacts remain at the paths above."
        )
        sys.exit(4)
    except KeyboardInterrupt:
        print("KeyboardInterrupt — partial artifacts remain.")
        sys.exit(5)
    except Exception as e:
        print(f"FATAL: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(6)

    elapsed = time.time() - start_time
    print(
        f"\n[done] {len(results)} repaired battles in {elapsed:.0f}s"
    )
    print(
        f"  CSV      : {paths['csv_path']}\n"
        f"  battle   : {paths['battle_path']}"
    )
    print(
        "\nNext: run the merge analyzer:\n"
        "  ./venv/bin/python analyze_doubles_narrow_ally_heal_paired_repair.py "
        f"--repair-tag {args.artifact_tag}"
    )


if __name__ == "__main__":
    main()
