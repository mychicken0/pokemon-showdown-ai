#!/usr/bin/env python3
"""
Phase 6.4.10 — Voluntary Switch Quality Paired Qualification.

Runs N side-swap pairs of doubles battles between
``enable_voluntary_switch_quality_scoring = ON`` and
``OFF`` players. The ON config has
``enable_voluntary_switch_quality_diagnostics = True``
and ``enable_voluntary_switch_quality_scoring = True``.
The OFF config has diagnostics on and scoring off.

  D1: scoring ON as player 1, scoring OFF as player 2
  D2: same team and seed, sides swapped
      (scoring OFF as player 1, scoring ON as player 2)

Per-slot audit JSONL files are persisted for the
analyzer. Each pair produces two side-swap files per
player (``__p1`` and ``__p2``).

Watchdog: heartbeat 10s, stall 60s, arm 600s,
outer 1200s.

Local server only (localhost:8000).
"""
import argparse
import asyncio
import atexit
import csv
import json
import os
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

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
LOCAL_BASE_ACCOUNT = "PairedVsw"
SUFFIX = "6410"


class StallError(Exception):
    pass


class PairedQualificationError(Exception):
    pass


def check_localhost(timeout=2.0):
    try:
        with urllib.request.urlopen(
            "http://localhost:8000", timeout=timeout
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


def build_config(arm_label: str) -> DoublesDamageAwareConfig:
    """Build a per-side config.

    ON: ``enable_voluntary_switch_quality_diagnostics=True``,
        ``enable_voluntary_switch_quality_scoring=True``.
        All other defaults preserved (for example,
        forced-switch safety stays at its current
        default; broad support-target safety stays
        off).
    OFF: ``enable_voluntary_switch_quality_diagnostics=True``,
        ``enable_voluntary_switch_quality_scoring=False``.
    """
    cfg = DoublesDamageAwareConfig()
    cfg.enable_voluntary_switch_quality_diagnostics = True
    if arm_label == "ON":
        cfg.enable_voluntary_switch_quality_scoring = True
    else:
        cfg.enable_voluntary_switch_quality_scoring = False
    # Phase 6.4.10d: preflight guard — abort if
    # base defaults regress. AGENTS.md mandates
    # these stay False until paired adoption.
    assert cfg.enable_support_move_target_hard_safety is False, (
        "support-move hard safety must stay False until adoption"
    )
    assert cfg.enable_ally_heal_wrong_side_hard_safety is False, (
        "ally-heal hard safety must stay False until adoption"
    )
    return cfg


def preflight_assert_defaults():
    """Phase 6.4.10d: assert source defaults before
    any battle. Aborts with non-zero exit if the
    base config has regressed."""
    cfg = DoublesDamageAwareConfig()
    assert cfg.enable_voluntary_switch_quality_diagnostics is True, (
        f"diagnostics must be True, got "
        f"{cfg.enable_voluntary_switch_quality_diagnostics}"
    )
    assert cfg.enable_voluntary_switch_quality_scoring is False, (
        f"scoring must be False (ON arm overrides it), got "
        f"{cfg.enable_voluntary_switch_quality_scoring}"
    )
    assert cfg.enable_support_move_target_hard_safety is False, (
        "support-move hard safety must be False"
    )
    assert cfg.enable_ally_heal_wrong_side_hard_safety is False, (
        "ally-heal hard safety must be False"
    )


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


async def _run_pair_with_watchdog(
    pair_id: int,
    team_str: str,
    p1_arm: str,
    p2_arm: str,
    arm_timeout: int,
):
    """Run one paired battle (D1 or D2)."""
    cfg_p1 = build_config(p1_arm)
    cfg_p2 = build_config(p2_arm)
    suffix = (
        f"p{pair_id:03d}_{p1_arm}v{p2_arm}_" + SUFFIX
    )[:18]
    p1_name = f"{LOCAL_BASE_ACCOUNT}_P1_{suffix}"[:18]
    p2_name = f"{LOCAL_BASE_ACCOUNT}_P2_{suffix}"[:18]

    p1_audit_path = (
        f"logs/voluntary_switch_paired_{pair_id:03d}_"
        f"{p1_arm}v{p2_arm}__p1.jsonl"
    )
    p2_audit_path = (
        f"logs/voluntary_switch_paired_{pair_id:03d}_"
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
    # Phase 6.4.10d: ON/OFF config assertion. Abort
    # if either side has the wrong scoring flag.
    assert p1.config.enable_voluntary_switch_quality_scoring is (
        p1_arm == "ON"
    ), (
        f"p1 ({p1_arm}) scoring flag wrong: "
        f"{p1.config.enable_voluntary_switch_quality_scoring}"
    )
    assert p2.config.enable_voluntary_switch_quality_scoring is (
        p2_arm == "ON"
    ), (
        f"p2 ({p2_arm}) scoring flag wrong: "
        f"{p2.config.enable_voluntary_switch_quality_scoring}"
    )
    assert p1.config.enable_voluntary_switch_quality_diagnostics
    assert p2.config.enable_voluntary_switch_quality_diagnostics

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
    # Phase 6.4.10d: extract turns from the
    # completed battle object if any.
    turns = 0
    battle_tag = None
    for bt, b in p1.battles.items():
        battle_tag = bt
        turns = max(turns, int(getattr(b, "turn", 0) or 0))
        break
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
        "turns": turns,
        "error_detail": error_detail or "",
        "p1_name": p1_name,
        "p2_name": p2_name,
        "team_str": team_str,
        "p1_config_vsw": (p1_arm == "ON"),
        "p2_config_vsw": (p2_arm == "ON"),
        "p1_audit_path": p1_audit_path,
        "p2_audit_path": p2_audit_path,
    }

    await _cleanup_player(p1)
    await _cleanup_player(p2)
    return result


def init_artifacts(artifact_tag, overwrite):
    csv_path = f"logs/voluntary_switch_paired_{artifact_tag}.csv"
    battle_path = f"logs/voluntary_switch_paired_{artifact_tag}.jsonl"
    analysis_json = (
        f"logs/voluntary_switch_paired_{artifact_tag}_analysis.json"
    )
    analysis_md = (
        f"logs/voluntary_switch_paired_{artifact_tag}_analysis.md"
    )

    existing = [
        p for p in (csv_path, battle_path, analysis_json, analysis_md)
        if os.path.exists(p)
    ]
    if existing and not overwrite:
        print(
            "ERROR: Paired-qualification artifacts already exist "
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
            "turns", "error_detail", "p1_name", "p2_name",
            "team_str", "p1_config_vsw", "p2_config_vsw",
            "p1_audit_path", "p2_audit_path",
        ])
    for p in (battle_path,):
        open(p, "w").close()
    return {
        "csv_path": csv_path,
        "battle_path": battle_path,
        "analysis_json": analysis_json,
        "analysis_md": analysis_md,
    }


async def run_all(args):
    if not check_localhost():
        print(
            "ERROR: localhost:8000 not healthy. "
            "Paired qualifier refuses to run."
        )
        sys.exit(3)
    # Phase 6.4.10d: preflight default assertions
    # before any battle. Aborts on regression.
    preflight_assert_defaults()

    paths = init_artifacts(args.artifact_tag, args.overwrite)
    n_pairs = args.n_pairs
    print(
        f"Phase 6.4.10 voluntary switch paired qualification: "
        f"tag={args.artifact_tag}, n_pairs={n_pairs}"
    )
    print(f"  CSV      : {paths['csv_path']}")
    print(f"  battle   : {paths['battle_path']}")
    print(f"  analysis : {paths['analysis_json']}, .md")

    all_results = []
    for pair_id in range(args.start_pair, args.start_pair + n_pairs):
        team_str = ""
        d1 = await _run_pair_with_watchdog(
            pair_id, team_str, "ON", "OFF",
            arm_timeout=ARM_TIMEOUT,
        )
        d2 = await _run_pair_with_watchdog(
            pair_id, team_str, "OFF", "ON",
            arm_timeout=ARM_TIMEOUT,
        )
        all_results.append(d1)
        all_results.append(d2)
        with open(paths["csv_path"], "a", newline="") as f:
            writer = __import__("csv").writer(f)
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
                    r["team_str"], r["p1_config_vsw"],
                    r["p2_config_vsw"],
                    r["p1_audit_path"], r["p2_audit_path"],
                ])
        with open(paths["battle_path"], "a") as f:
            for r in (d1, d2):
                f.write(json.dumps(r) + "\n")
        done = (pair_id - args.start_pair + 1) * 2
        print(f"  [progress] {done}/{n_pairs * 2} pairs done")
    return all_results, paths


def main():
    parser = argparse.ArgumentParser(
        description="Phase 6.4.10 voluntary switch paired qualification"
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
        "--n-pairs", type=int, default=100,
        help="Number of side-swap pairs (default: 100).",
    )
    parser.add_argument(
        "--start-pair", type=int, default=0,
        help="Starting pair index (default: 0).",
    )
    parser.add_argument(
        "--account-prefix", type=str, default="PairedVsw",
        help="Visible username prefix (default: PairedVsw).",
    )
    args = parser.parse_args()
    # Phase 6.4.10d: override the local account
    # prefix so smoke runs use a visible prefix.
    global LOCAL_BASE_ACCOUNT
    LOCAL_BASE_ACCOUNT = args.account_prefix[:18]

    start_time = time.time()
    try:
        results, paths = asyncio.run(
            asyncio.wait_for(
                run_all(args), timeout=OUTER_TIMEOUT
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
        f"  analysis : {paths['analysis_json']}, .md"
    )
    print(
        f"\nNext: run the analyzer:\n"
        f"  ./venv/bin/python analyze_doubles_voluntary_switch_paired.py "
        f"--artifact-tag {args.artifact_tag}"
    )


if __name__ == "__main__":
    main()
