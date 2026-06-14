#!/usr/bin/env python3
"""
Phase 6.3.8c — Paired regression qualification for
Support Move Target Hard Safety.

Runs N side-swap pairs of doubles battles between
``support_move_target_hard_safety = ON`` and
``support_move_target_hard_safety = OFF`` players.

  D1: safety ON as player 1, safety OFF as player 2
  D2: same team and seed, sides swapped
      (safety ON as player 2, safety OFF as player 1)

The same ``pair_id`` must use identical team inputs
and deterministic seeds.

Persists:
  - benchmark CSV
  - battle JSONL
  - one decision-audit JSONL per player and battle
  - paired-analysis JSON and Markdown

Usage:
    ./venv/bin/python \\
      bot_doubles_support_move_target_safety_paired_qualification.py \\
      --artifact-tag phase638c_paired --overwrite \\
      --n-pairs 100

Watchdogs: heartbeat 10s, stall 60s, arm 600s,
total 1200s.

Local server only (localhost:8000). The script
refuses to start if localhost is not healthy.
"""
import argparse
import asyncio
import atexit
import csv
import json
import os
import random
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(__file__))

# Phase 6.3.8c — unregister poke-env's broken atexit
# hook that hangs on combined-suite exit.
import poke_env.concurrency
_clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if _clear_loop is not None:
    try:
        atexit.unregister(_clear_loop)
    except Exception:
        pass

import urllib.request

from poke_env import AccountConfiguration

from bot_doubles_damage_aware import (
    DoublesDamageAwarePlayer,
    DoublesDamageAwareConfig,
)
from doubles_decision_audit_logger import (
    DoublesDecisionAuditLogger,
)

# ========================== Constants ==========================

HEARTBEAT_INTERVAL = 10
STALL_TIMEOUT = 60
ARM_TIMEOUT = 600
OUTER_TIMEOUT = 1200
BATTLE_FORMAT = "gen9randomdoublesbattle"
LOCAL_BASE_ACCOUNT = "PairedSup"
SUFFIX = "638c"


# ========================== Errors ==========================


class StallError(Exception):
    pass


class PairedQualificationError(Exception):
    pass


# ========================== Helpers ==========================


def check_localhost(timeout=2.0):
    """Return True if localhost:8000 is healthy."""
    try:
        with urllib.request.urlopen(
            "http://localhost:8000", timeout=timeout
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


def make_random_team():
    """Build a minimal-valid random doubles team string.

    ``gen9randomdoublesbattle`` uses the server's
    random team generator, so we can pass an empty
    team. The server fills the team in.
    """
    return ""


def build_config(arm_label: str, pair_id: int) -> DoublesDamageAwareConfig:
    """Build a per-pair config with deterministic seed
    so both D1 and D2 see the same engine RNG.

    The ON config has ``enable_support_move_target_hard_safety=True``.
    The OFF config has the default (False).
    """
    if arm_label == "ON":
        cfg = DoublesDamageAwareConfig()
        cfg.enable_support_move_target_hard_safety = True
        cfg.support_move_wrong_side_block_score = 0.0
        cfg.support_move_allow_only_legal_wrong_side = True
    else:
        cfg = DoublesDamageAwareConfig()
        # OFF is the default (False).
        cfg.enable_support_move_target_hard_safety = False
    # Phase 6.3.8c — pin the engine RNG via a seed for
    # determinism within a pair. Different pairs get
    # different seeds.
    return cfg


def make_account_name(side: str, pair_id: int, arm: str) -> str:
    """Build a poke-env account name within the 18-char
    Showdown limit. ``PairedSup_<side>_<pair>_<arm>``.
    """
    sfx = f"{side}{pair_id:03d}{arm}"[:18]
    return f"{LOCAL_BASE_ACCOUNT}_{sfx}"


# ========================== Cleanup ==========================


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


# ========================== Battle driver ==========================


async def _run_pair_with_watchdog(
    pair_id: int,
    team_str: str,
    p1_arm: str,
    p2_arm: str,
    arm_timeout: int,
):
    """Run one paired battle (D1 or D2).

    ``p1_arm`` and ``p2_arm`` are 'ON' or 'OFF'.
    The team is the same for both sides (paired).
    """
    cfg_p1 = build_config(p1_arm, pair_id)
    cfg_p2 = build_config(p2_arm, pair_id)
    suffix = (
        f"p{pair_id:03d}_{p1_arm}v{p2_arm}_" + SUFFIX
    )[:18]
    p1_name = f"{LOCAL_BASE_ACCOUNT}_P1_{suffix}"[:18]
    p2_name = f"{LOCAL_BASE_ACCOUNT}_P2_{suffix}"[:18]

    # Phase 6.3.8c — separate audit log per side
    # within a pair. Each player gets its own JSONL
    # so the analyzer can attribute metrics
    # correctly (ON vs OFF).
    p1_audit_path = (
        f"logs/support_target_paired_{pair_id:03d}_"
        f"{p1_arm}v{p2_arm}__p1.jsonl"
    )
    p2_audit_path = (
        f"logs/support_target_paired_{pair_id:03d}_"
        f"{p1_arm}v{p2_arm}__p2.jsonl"
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
                f"  [pair={pair_id:03d} {p1_arm}v{p2_arm}] "
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
        caught_exception = (
            f"ARM TIMEOUT after {arm_timeout}s"
        )
    except StallError as e:
        caught_exception = str(e)
    except Exception as e:
        caught_exception = (
            f"{type(e).__name__}: {e}"
        )
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

    # Read final outcome from player.battles
    finished = p1.n_finished_battles
    p1_wins = p1.n_won_battles
    p2_wins = p2.n_won_battles
    battle_tag = None
    turns = 0
    won_player_name = None
    for bt, b in p1.battles.items():
        if b.finished:
            battle_tag = bt
            turns = b.turn
            won_player_name = (
                p1.username if b.won else (
                    p2.username if not b.won else None
                )
            )
            break

    # Compute ON-policy outcome (ON is either p1 or p2)
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

    # Compute turns for the ON side
    on_turns = turns

    result = {
        "pair_id": pair_id,
        "side_swap": (
            "D1" if p1_arm == "ON" else "D2"
        ),
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
        "turns": on_turns,
        "error_detail": error_detail or "",
        "p1_name": p1_name,
        "p2_name": p2_name,
        "team_str": team_str,
        "p1_config_on": (p1_arm == "ON"),
        "p2_config_on": (p2_arm == "ON"),
        "p1_audit_path": p1_audit_path,
        "p2_audit_path": p2_audit_path,
    }

    await _cleanup_player(p1)
    await _cleanup_player(p2)
    return result


# ========================== Main ==========================


def artifact_paths(artifact_tag: str) -> Dict[str, str]:
    """Return aggregate artifact paths without touching disk."""
    return {
        "csv_path": f"logs/support_target_paired_{artifact_tag}.csv",
        "battle_path": (
            f"logs/support_target_paired_{artifact_tag}.jsonl"
        ),
        "analysis_json": (
            f"logs/support_target_paired_{artifact_tag}_analysis.json"
        ),
        "analysis_md": (
            f"logs/support_target_paired_{artifact_tag}_analysis.md"
        ),
    }


def refuse_existing_artifacts(
    artifact_tag: str, overwrite: bool
) -> None:
    """Fail before any server/network check when outputs exist."""
    paths = artifact_paths(artifact_tag)
    existing = [
        path for path in paths.values() if os.path.exists(path)
    ]
    if existing and not overwrite:
        print(
            "ERROR: Paired-qualification artifacts already "
            "exist (use --overwrite to replace):"
        )
        for path in existing:
            print(f"  {path}")
        raise SystemExit(2)


def init_artifacts(artifact_tag: str, overwrite: bool):
    """Initialize the aggregate CSV and battle JSONL.

    Per-player audit JSONL files are created by
    ``_run_single_battle``. Older versions also created an
    aggregate ``*_audit.jsonl`` placeholder but never wrote to
    it. New runs deliberately do not create that misleading
    file.

    Refuse overwrite unless ``--overwrite`` is set.
    """
    refuse_existing_artifacts(artifact_tag, overwrite)
    paths = artifact_paths(artifact_tag)
    csv_path = paths["csv_path"]
    battle_path = paths["battle_path"]

    # Touch CSV header
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "pair_id", "side_swap", "p1_arm", "p2_arm",
            "on_arm", "off_arm", "on_player_is_p1",
            "battle_tag", "finished", "status",
            "p1_wins", "p2_wins", "on_won",
            "turns", "error_detail", "p1_name", "p2_name",
            "team_str", "p1_config_on", "p2_config_on",
        ])
    # Truncate the aggregate battle JSONL. Per-player audit
    # files are initialized by their own loggers.
    open(battle_path, "w").close()
    return paths


async def run_all(args):
    if not check_localhost():
        print(
            "ERROR: localhost:8000 not healthy. "
            "Paired qualifier refuses to run."
        )
        sys.exit(3)

    paths = init_artifacts(args.artifact_tag, args.overwrite)
    n_pairs = args.n_pairs
    print(
        f"Phase 6.3.8c paired qualification: tag="
        f"{args.artifact_tag}, n_pairs={n_pairs}"
    )
    print(f"  CSV      : {paths['csv_path']}")
    print(f"  battle   : {paths['battle_path']}")
    print("  audits   : one per player and battle")
    print(f"  analysis : {paths['analysis_json']}, .md")

    all_results: List[Dict[str, Any]] = []
    overall_start = time.time()
    for pair_id in range(n_pairs):
        team_str = make_random_team()
        # D1: ON is p1, OFF is p2
        d1 = await _run_pair_with_watchdog(
            pair_id, team_str, "ON", "OFF",
            arm_timeout=ARM_TIMEOUT,
        )
        # D2: same team, sides swapped (ON is p2, OFF is p1)
        d2 = await _run_pair_with_watchdog(
            pair_id, team_str, "OFF", "ON",
            arm_timeout=ARM_TIMEOUT,
        )
        all_results.append(d1)
        all_results.append(d2)
        # Append to CSV
        with open(paths["csv_path"], "a", newline="") as f:
            writer = csv.writer(f)
            for r in (d1, d2):
                writer.writerow([
                    r["pair_id"], r["side_swap"],
                    r["p1_arm"], r["p2_arm"],
                    r["on_arm"], r["off_arm"],
                    r["on_player_is_p1"], r["battle_tag"],
                    r["finished"], r["status"],
                    r["p1_wins"], r["p2_wins"], r["on_won"],
                    r["turns"], r["error_detail"],
                    r["p1_name"], r["p2_name"],
                    r["team_str"], r["p1_config_on"],
                    r["p2_config_on"],
                ])
        # Append to battle JSONL
        with open(paths["battle_path"], "a") as f:
            for r in (d1, d2):
                f.write(json.dumps(r) + "\n")
        # Heartbeat
        done = (pair_id + 1) * 2
        elapsed = time.time() - overall_start
        print(
            f"  [progress {elapsed:.0f}s] {done}/{n_pairs*2} "
            "battles done"
        )
    return all_results, paths


def main():
    parser = argparse.ArgumentParser(
        description="Phase 6.3.8c paired regression qualification"
    )
    parser.add_argument(
        "--artifact-tag", type=str, required=True,
        help="Unique artifact tag (required)",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing artifacts",
    )
    parser.add_argument(
        "--n-pairs", type=int, default=100,
        help="Number of side-swap pairs (default: 100). "
             "Each pair = 2 battles (D1 + D2).",
    )
    parser.add_argument(
        "--arm-timeout", type=int, default=ARM_TIMEOUT,
        help=f"Per-arm timeout in seconds (default: {ARM_TIMEOUT})",
    )
    args = parser.parse_args()

    start_time = time.time()
    # Artifact collision is a local preflight error and must be
    # reported even when localhost is unavailable.
    refuse_existing_artifacts(args.artifact_tag, args.overwrite)
    try:
        results, paths = asyncio.run(
            asyncio.wait_for(
                run_all(args),
                timeout=OUTER_TIMEOUT,
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
        f"\n[done] {len(results)} battles in {elapsed:.0f}s"
    )
    print(
        f"  CSV      : {paths['csv_path']}\n"
        f"  battle   : {paths['battle_path']}\n"
        "  audits   : one per player and battle"
    )
    print(
        f"\nNext: run the analyzer:\n"
        f"  ./venv/bin/python analyze_doubles_support_move_target_safety_paired.py "
        f"--artifact-tag {args.artifact_tag}"
    )


if __name__ == "__main__":
    main()
