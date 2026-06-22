#!/usr/bin/env python3
"""Phase 6.4.6 — Decision Timing Benchmark.

Smoke arms (50/30):
  A) current default vs Basic — 50 battles  (timing ON)
  B) current default vs SafeRandom — 30 battles  (timing ON)

Artifact tag: phase646_decision_timing_smoke
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


def _count_timing_metrics(log_path):
    m = {
        "turns_with_timing": 0,
        "decision_vals": [],
        "score_action_vals": [],
        "joint_scoring_vals": [],
        "audit_post_vals": [],
        "valid_order_vals": [],
        "sac_vals": [],
        "jo_vals": [],
        "slowest_turn": None,
        "slowest_decision_ms": 0.0,
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
                battle_tag = record.get("battle_tag", "")
                for turn_data in record.get("audit_turns", []):
                    dt = turn_data.get("decision_time_ms")
                    if dt is None:
                        continue
                    dt_f = float(dt)
                    m["turns_with_timing"] += 1
                    m["decision_vals"].append(dt_f)

                    sa = turn_data.get("score_action_time_ms")
                    if sa is not None:
                        m["score_action_vals"].append(float(sa))
                    js = turn_data.get("joint_scoring_time_ms")
                    if js is not None:
                        m["joint_scoring_vals"].append(float(js))
                    ap = turn_data.get("audit_postprocess_time_ms")
                    if ap is not None:
                        m["audit_post_vals"].append(float(ap))
                    vo = turn_data.get("valid_order_time_ms")
                    if vo is not None:
                        m["valid_order_vals"].append(float(vo))
                    sac = turn_data.get("score_action_call_count")
                    if sac is not None:
                        m["sac_vals"].append(int(sac))
                    jo = turn_data.get("joint_order_count")
                    if jo is not None:
                        m["jo_vals"].append(int(jo))

                    if dt_f > m["slowest_decision_ms"]:
                        m["slowest_decision_ms"] = dt_f
                        m["slowest_turn"] = {
                            "battle_tag": battle_tag,
                            "turn": turn_data.get("turn", 0),
                            "decision_time_ms": dt_f,
                            "selected_joint_order": turn_data.get("selected_joint_order", "")[:80],
                        }
            except Exception:
                continue
    return m


def _compute_stats(vals):
    if not vals:
        return {}
    sv = sorted(vals)
    n = len(sv)
    return {
        "avg": sum(sv) / n,
        "p50": sv[n // 2],
        "p95": sv[int(n * 0.95)] if int(n * 0.95) < n else sv[-1],
        "max": sv[-1],
    }


def _make_result(name, n_battles, player, opponent, status, log_path, benchmark_arm=""):
    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles if hasattr(opponent, 'n_won_battles') else 0
    ties = finished - wins - losses
    wr = (wins / finished * 100) if finished > 0 else 0.0
    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0.0

    m = _count_timing_metrics(log_path)
    timeouts = getattr(player, "_timeout_count", 0)
    m["timeout_count"] = timeouts

    dt_stats = _compute_stats(m["decision_vals"])
    sa_stats = _compute_stats(m["score_action_vals"])
    js_stats = _compute_stats(m["joint_scoring_vals"])
    ap_stats = _compute_stats(m["audit_post_vals"])
    vo_stats = _compute_stats(m["valid_order_vals"])

    sac_avg = sum(m["sac_vals"]) / len(m["sac_vals"]) if m["sac_vals"] else 0.0
    jo_avg = sum(m["jo_vals"]) / len(m["jo_vals"]) if m["jo_vals"] else 0.0

    return {
        "name": name, "status": status,
        "planned": n_battles, "finished": finished,
        "wins": wins, "losses": losses, "ties": ties,
        "win_rate": f"{wr:.2f}", "avg_turns": f"{avg_turns:.2f}",
        "benchmark_arm": benchmark_arm,
        "turns_with_timing": m["turns_with_timing"],
        "decision_avg_ms": f"{dt_stats.get('avg', 0):.2f}" if dt_stats else "N/A",
        "decision_p50_ms": f"{dt_stats.get('p50', 0):.2f}" if dt_stats else "N/A",
        "decision_p95_ms": f"{dt_stats.get('p95', 0):.2f}" if dt_stats else "N/A",
        "decision_max_ms": f"{dt_stats.get('max', 0):.2f}" if dt_stats else "N/A",
        "valid_order_avg_ms": f"{vo_stats.get('avg', 0):.2f}" if vo_stats else "N/A",
        "valid_order_p95_ms": f"{vo_stats.get('p95', 0):.2f}" if vo_stats else "N/A",
        "score_action_avg_ms": f"{sa_stats.get('avg', 0):.2f}" if sa_stats else "N/A",
        "score_action_p95_ms": f"{sa_stats.get('p95', 0):.2f}" if sa_stats else "N/A",
        "joint_scoring_avg_ms": f"{js_stats.get('avg', 0):.2f}" if js_stats else "N/A",
        "joint_scoring_p95_ms": f"{js_stats.get('p95', 0):.2f}" if js_stats else "N/A",
        "audit_post_avg_ms": f"{ap_stats.get('avg', 0):.2f}" if ap_stats else "N/A",
        "audit_post_p95_ms": f"{ap_stats.get('p95', 0):.2f}" if ap_stats else "N/A",
        "sac_avg": f"{sac_avg:.1f}",
        "jo_avg": f"{jo_avg:.1f}",
        "slowest_decision_ms": f"{m['slowest_decision_ms']:.2f}" if m["slowest_turn"] else "N/A",
        "slowest_battle_turn": f"{m['slowest_turn']['battle_tag'][:20]}:t{m['slowest_turn']['turn']}" if m["slowest_turn"] else "N/A",
        "timeout_count": timeouts,
    }


def label_name(name):
    return name.replace(" ", "_").replace("vs", "")


async def main():
    artifact_tag = "phase646_decision_timing_smoke"
    csv_path = f"logs/decision_timing_{artifact_tag}.csv"

    if os.path.exists(csv_path) and "--overwrite" not in sys.argv:
        print(f"CSV already exists: {csv_path}")
        print("Use --overwrite to overwrite.")
        return

    config = DoublesDamageAwareConfig()
    # Enable timing diagnostics but keep ALL scoring defaults unchanged
    config.enable_decision_timing_diagnostics = True

    arms = [
        ("A", "Default+Timing vs Basic", "basic", 50),
        ("B", "Default+Timing vs SafeRandom", "safe_random", 30),
    ]

    results = []
    for arm_id, arm_name, opp_class, n_battles in arms:
        log_path = f"logs/decision_timing_{artifact_tag}_{arm_id}.jsonl"
        result = await run_matchup_with_watchdog(
            arm_name, config, opp_class, None, n_battles, log_path,
            arm_timeout=1800, benchmark_arm=arm_id,
        )
        results.append(result)
        print(f"  {arm_id}: {result.get('win_rate', 'N/A')}% WR, "
              f"{result.get('wins', 0)}W/{result.get('losses', 0)}L, "
              f"finished={result.get('finished', 0)}")

    fieldnames = [
        "name", "status", "planned", "finished", "wins", "losses", "ties",
        "win_rate", "avg_turns", "benchmark_arm",
        "turns_with_timing",
        "decision_avg_ms", "decision_p50_ms", "decision_p95_ms", "decision_max_ms",
        "valid_order_avg_ms", "valid_order_p95_ms",
        "score_action_avg_ms", "score_action_p95_ms",
        "joint_scoring_avg_ms", "joint_scoring_p95_ms",
        "audit_post_avg_ms", "audit_post_p95_ms",
        "sac_avg", "jo_avg",
        "slowest_decision_ms", "slowest_battle_turn",
        "timeout_count",
    ]

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            row = {k: r.get(k, "N/A") for k in fieldnames}
            writer.writerow(row)

    print(f"\nSaved: {csv_path}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
