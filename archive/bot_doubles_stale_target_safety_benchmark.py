#!/usr/bin/env python3
"""Phase 6.4.5 — Stale Target / Retarget Immunity Safety Benchmark.

Smoke arms (50/50/50/30):
  A) stale safety off vs Basic — 50 battles
  B) stale safety on vs Basic — 50 battles
  C) stale safety on vs off — 50 battles
  D) stale safety on vs SafeRandom — 30 battles

Uses watchdogs:
  - heartbeat 30s
  - stall timeout 180s
  - arm timeout 1800s

Artifact tag: phase645_stale_target_smoke
"""
import asyncio
import csv
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

import atexit
import poke_env.concurrency
_clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if _clear_loop is not None:
    try:
        atexit.unregister(_clear_loop)
    except Exception:
        pass

from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer
from bot_doubles_safe_random import DoublesSafeRandomPlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

MAX_CONCURRENT = 15
STALL_TIMEOUT = 180
HEARTBEAT_INTERVAL = 30


class StallError(Exception):
    pass


async def _cleanup_player(player):
    try:
        if hasattr(player, "ps_client") and hasattr(player.ps_client, "_stop_listening"):
            await player.ps_client._stop_listening()
    except Exception:
        pass


async def _run_arm_with_watchdog(name, battle_coro_factory, heartbeat_coro_factory, arm_timeout):
    battle_task = asyncio.create_task(battle_coro_factory())
    watchdog_task = asyncio.create_task(heartbeat_coro_factory())
    caught_exception = None

    try:
        done, pending = await asyncio.wait_for(
            asyncio.wait({battle_task, watchdog_task}, return_when=asyncio.FIRST_COMPLETED),
            timeout=arm_timeout,
        )
        if watchdog_task in done:
            w_exc = watchdog_task.exception()
            if w_exc and not isinstance(w_exc, asyncio.CancelledError):
                raise w_exc
        if battle_task in done:
            b_exc = battle_task.exception()
            if b_exc and not isinstance(b_exc, asyncio.CancelledError):
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

    status = "ok" if caught_exception is None else "error"
    return status, caught_exception


async def run_matchup_with_watchdog(name, config, opp_class, opp_config, n_battles, log_path,
                                     arm_timeout=1800, benchmark_arm=""):
    if opp_class == "basic":
        OppClass = DoublesBasicAwarePlayer
    elif opp_class == "safe_random":
        OppClass = DoublesSafeRandomPlayer
    elif opp_class == "mirror":
        OppClass = DoublesDamageAwarePlayer
    else:
        raise ValueError(f"Unknown opp_class: {opp_class}")

    suffix = random.randint(10000, 99999)
    bot_name = f"SinB_{label_name(name)[:8]}_{suffix}"[:18]
    opp_name = f"Opp_{label_name(name)[:8]}_{suffix}"[:18]

    audit_logger = DoublesDecisionAuditLogger(
        filepath=log_path, reset=True, detail_level="top5",
        benchmark_arm=benchmark_arm,
        singleton_safety_enabled=bool(
            getattr(config, "ability_hard_safety_allow_singleton_deduction", False)
        ),
        priority_safety_enabled=bool(
            getattr(config, "enable_priority_field_hard_safety", False)
        ),
    )

    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        verbose=False, config=config,
        audit_logger=audit_logger,
        max_concurrent_battles=MAX_CONCURRENT,
    )

    if opp_class == "mirror":
        opponent = OppClass(
            account_configuration=AccountConfiguration(opp_name, None),
            verbose=False, config=opp_config,
            max_concurrent_battles=MAX_CONCURRENT,
        )
    else:
        opponent = OppClass(
            account_configuration=AccountConfiguration(opp_name, None),
            verbose=False, max_concurrent_battles=MAX_CONCURRENT,
        )

    print(f"\n---> {name}: {n_battles} battles")
    start_time = time.time()
    state = {"last_battle_time": start_time, "last_finished": 0}

    async def heartbeat():
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            elapsed = time.time() - start_time
            finished = player.n_finished_battles
            wins = player.n_won_battles
            losses = opponent.n_won_battles if hasattr(opponent, 'n_won_battles') else 0
            since_last = time.time() - state["last_battle_time"]
            if finished > state["last_finished"]:
                state["last_battle_time"] = time.time()
                state["last_finished"] = finished
            print(f"  [{name}] {elapsed:.0f}s | {finished}/{n_battles} | "
                  f"{wins}W {losses}L | {since_last:.0f}s since last")
            if since_last > STALL_TIMEOUT:
                raise StallError(f"Stall: {name}: no battle finished in {STALL_TIMEOUT}s")

    async def run_battle():
        return await player.battle_against(opponent, n_battles=n_battles)

    status, caught_exception = await _run_arm_with_watchdog(name, run_battle, heartbeat, arm_timeout)

    result = _make_result(name, n_battles, player, opponent, status, log_path, benchmark_arm=benchmark_arm)
    if caught_exception:
        result["error_detail"] = caught_exception

    await _cleanup_player(player)
    await _cleanup_player(opponent)

    if status != "ok":
        print(f"  [{name}] {status.upper()}: {caught_exception}")

    return result


def _count_audit_metrics(log_path):
    m = {
        "stale_target_selected": 0,
        "stale_target_avoided": 0,
        "stale_target_same_target_expected_ko": 0,
        "stale_target_caused_type_immune": 0,
        "stale_target_caused_no_effect": 0,
        "type_immune_move_selected": 0,
        "direct_known_absorb_repeat_selected": 0,
        "spread_count": 0,
        "focus_fire_count": 0,
        "timeout_count": 0,
    }
    if not os.path.exists(log_path):
        return m
    with open(log_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                for turn in record.get("audit_turns", []):
                    if turn.get("stale_target_selected"):
                        m["stale_target_selected"] += 1
                    if turn.get("stale_target_avoided"):
                        m["stale_target_avoided"] += 1
                    if turn.get("stale_target_same_target_expected_ko"):
                        m["stale_target_same_target_expected_ko"] += 1
                    if turn.get("stale_target_caused_type_immune"):
                        m["stale_target_caused_type_immune"] += 1
                    if turn.get("stale_target_caused_no_effect"):
                        m["stale_target_caused_no_effect"] += 1
                    for sk in ("slot_0", "slot_1"):
                        slot = turn.get(sk, {})
                        if not slot:
                            continue
                        if slot.get("our_type_immune_move_selected"):
                            m["type_immune_move_selected"] += 1
                        if slot.get("direct_known_absorb_repeat_selected"):
                            m["direct_known_absorb_repeat_selected"] += 1
                        act_types = slot.get("action_types", {})
                        if act_types.get("spread"):
                            m["spread_count"] += 1
                    if turn.get("focus_fire_triggered"):
                        m["focus_fire_count"] += 1
            except Exception:
                continue
    return m


def _make_result(name, n_battles, player, opponent, status, log_path, benchmark_arm=""):
    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles if hasattr(opponent, 'n_won_battles') else 0
    ties = finished - wins - losses
    wr = (wins / finished * 100) if finished > 0 else 0.0
    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0.0

    m = _count_audit_metrics(log_path)
    timeouts = getattr(player, "_timeout_count", 0)
    m["timeout_count"] = timeouts

    return {
        "name": name, "status": status,
        "planned": n_battles, "finished": finished,
        "wins": wins, "losses": losses, "ties": ties,
        "win_rate": f"{wr:.2f}", "avg_turns": f"{avg_turns:.2f}",
        "benchmark_arm": benchmark_arm,
        **m,
    }


def label_name(name):
    return name.replace(" ", "_").replace("vs", "")


async def main():
    artifact_tag = "phase645_stale_target_smoke"
    csv_path = f"logs/stale_target_safety_{artifact_tag}.csv"

    arms = [
        ("A", "StaleOff vs Basic", 50),
        ("B", "StaleOn vs Basic", 50),
        ("C", "StaleOn vs StaleOff", 50),
        ("D", "StaleOn vs SafeRandom", 30),
    ]

    existing_csv = os.path.exists(csv_path)
    if existing_csv and "--overwrite" not in sys.argv:
        print(f"CSV already exists: {csv_path}")
        print("Use --overwrite to overwrite.")
        return

    config_off = DoublesDamageAwareConfig()
    config_on = DoublesDamageAwareConfig()
    config_on.enable_stale_target_after_ally_ko_safety = True

    results = []

    for arm_id, arm_name, n_battles in arms:
        log_path = f"logs/stale_target_safety_{artifact_tag}_{arm_id}.jsonl"

        if "Off vs Basic" in arm_name:
            result = await run_matchup_with_watchdog(
                arm_name, config_off, "basic", None, n_battles, log_path,
                arm_timeout=1800, benchmark_arm=arm_id,
            )
        elif "StaleOn vs Basic" in arm_name:
            result = await run_matchup_with_watchdog(
                arm_name, config_on, "basic", None, n_battles, log_path,
                arm_timeout=1800, benchmark_arm=arm_id,
            )
        elif "StaleOn vs StaleOff" in arm_name:
            result = await run_matchup_with_watchdog(
                arm_name, config_on, "mirror", config_off, n_battles, log_path,
                arm_timeout=1800, benchmark_arm=arm_id,
            )
        elif "StaleOn vs SafeRandom" in arm_name:
            result = await run_matchup_with_watchdog(
                arm_name, config_on, "safe_random", None, n_battles, log_path,
                arm_timeout=1800, benchmark_arm=arm_id,
            )
        else:
            continue

        results.append(result)
        print(f"  {arm_id}: {result.get('win_rate', 'N/A')}% WR, "
              f"{result.get('wins', 0)}W/{result.get('losses', 0)}L, "
              f"finished={result.get('finished', 0)}")

    fieldnames = [
        "name", "status", "planned", "finished", "wins", "losses", "ties",
        "win_rate", "avg_turns", "benchmark_arm",
        "stale_target_selected", "stale_target_avoided",
        "stale_target_same_target_expected_ko",
        "stale_target_caused_type_immune", "stale_target_caused_no_effect",
        "type_immune_move_selected", "direct_known_absorb_repeat_selected",
        "spread_count", "focus_fire_count", "timeout_count",
    ]

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            row = {k: r.get(k, 0) for k in fieldnames}
            writer.writerow(row)

    print(f"\nSaved: {csv_path}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
