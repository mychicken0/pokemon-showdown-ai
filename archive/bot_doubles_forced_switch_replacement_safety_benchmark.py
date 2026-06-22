#!/usr/bin/env python3
"""Phase 6.4.4 — Forced Switch Replacement Safety Benchmark.

Smoke arms (10/10/10/10):
  A) forced_switch_safety_off vs Basic — 30 battles
  B) forced_switch_safety_on vs Basic — 30 battles
  C) forced_switch_safety_on vs forced_switch_safety_off — 30 battles
  D) forced_switch_safety_on vs SafeRandom — 20 battles

Uses watchdogs:
  - heartbeat 30s
  - stall timeout 180s
  - arm timeout 1200s

Save:
  - logs/forced_switch_replacement_safety_<tag>.csv
  - logs/forced_switch_replacement_safety_<tag>_<arm>.jsonl
"""
import asyncio
import csv
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

# Unregister deadlock-prone atexit callback (benchmark-process exit guard)
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
                                     arm_timeout=1200, benchmark_arm=""):
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
    """Count forced switch and general metrics from JSONL."""
    m = {
        "forced_switch_count": 0,
        "forced_switch_safety_on_count": 0,
        "forced_switch_selected_double_threat": 0,
        "forced_switch_selected_quad_weak": 0,
        "forced_switch_safety_selection_changed": 0,
        "forced_switch_fallback_used": 0,
        "forced_switch_score_gap_sum": 0.0,
        "forced_switch_score_gap_count": 0,
        "spread_count": 0,
        "focus_fire_count": 0,
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
                    for sk in ("slot_0", "slot_1"):
                        slot = turn.get(sk, {})
                        if not slot:
                            continue
                        if slot.get("forced_switch"):
                            m["forced_switch_count"] += 1
                            if slot.get("forced_switch_safety_enabled"):
                                m["forced_switch_safety_on_count"] += 1
                            if slot.get("forced_switch_selected_double_threat"):
                                m["forced_switch_selected_double_threat"] += 1
                            if slot.get("forced_switch_selected_quad_weak"):
                                m["forced_switch_selected_quad_weak"] += 1
                            if slot.get("forced_switch_safety_selection_changed"):
                                m["forced_switch_safety_selection_changed"] += 1
                            if slot.get("forced_switch_order_fallback_used"):
                                m["forced_switch_fallback_used"] += 1
                            sel_sc = slot.get("forced_switch_selected_safety_score", 0.0)
                            best_sc = slot.get("forced_switch_best_safety_score", 0.0)
                            gap = best_sc - sel_sc
                            if gap != 0:
                                m["forced_switch_score_gap_sum"] += gap
                                m["forced_switch_score_gap_count"] += 1
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


def _validate_artifacts(artifact_tag, arms):
    print("\n" + "=" * 70)
    print("ARTIFACT VALIDATION")
    print("=" * 70)
    all_ok = True

    csv_path = f"logs/forced_switch_replacement_safety_{artifact_tag}.csv"
    if not os.path.exists(csv_path):
        print(f"  FAIL: CSV not found: {csv_path}")
        all_ok = False
    else:
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        print(f"  CSV: {csv_path} — {len(rows)} rows")
        if len(rows) != len(arms):
            print(f"  FAIL: expected {len(arms)} rows, got {len(rows)}")
            all_ok = False

    for arm_id, arm_name, _, _, _, n in arms:
        jsonl_path = f"logs/forced_switch_replacement_safety_{artifact_tag}_{arm_id}.jsonl"
        if not os.path.exists(jsonl_path):
            print(f"  FAIL: JSONL not found: {jsonl_path}")
            all_ok = False
            continue
        with open(jsonl_path, "r") as f:
            lines = [l.strip() for l in f if l.strip()]
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"  FAIL: malformed JSON in {jsonl_path}")
                all_ok = False
                continue
        tags = set(r.get("battle_tag") for r in records)
        outcomes = sum(1 for r in records if r.get("won") is not None)
        arm_meta = sum(1 for r in records if r.get("benchmark_arm") == arm_id)
        print(f"  {arm_id} ({arm_name}): {len(records)} records, "
              f"{len(tags)} unique tags, {outcomes} outcomes, {arm_meta} arm metadata")
        if len(records) != n:
            print(f"    FAIL: expected {n} records")
            all_ok = False
        if len(tags) != n:
            print(f"    FAIL: expected {n} unique tags")
            all_ok = False
        if outcomes != n:
            print(f"    FAIL: expected {n} outcomes")
            all_ok = False
        if arm_meta != n:
            print(f"    FAIL: expected {n} arm metadata matches")
            all_ok = False

    print(f"\n  Overall: {'PASS' if all_ok else 'FAIL'}")
    return all_ok


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Phase 6.4.4 Forced Switch Replacement Safety Benchmark")
    parser.add_argument("--smoke", action="store_true", help="Run smoke (30/30/30/20)")
    parser.add_argument("--artifact-tag", default="", help="Tag for output filenames")
    parser.add_argument("--overwrite", action="store_true", help="Allow overwriting existing artifacts")
    args = parser.parse_args()

    if args.smoke:
        n_a, n_b, n_c, n_d = 30, 30, 30, 20
        tag = "smoke"
    else:
        n_a, n_b, n_c, n_d = 300, 300, 300, 100
        tag = "full"

    artifact_tag = args.artifact_tag if args.artifact_tag else tag

    os.makedirs("logs", exist_ok=True)

    output_paths = [
        f"logs/forced_switch_replacement_safety_{artifact_tag}.csv",
        f"logs/forced_switch_replacement_safety_{artifact_tag}_A.jsonl",
        f"logs/forced_switch_replacement_safety_{artifact_tag}_B.jsonl",
        f"logs/forced_switch_replacement_safety_{artifact_tag}_C.jsonl",
        f"logs/forced_switch_replacement_safety_{artifact_tag}_D.jsonl",
    ]

    if not args.overwrite:
        existing = [p for p in output_paths if os.path.exists(p)]
        if existing:
            print("ERROR: artifact(s) already exist. Use --overwrite to replace.")
            for p in existing:
                print(f"  {p}")
            sys.exit(1)

    config_off = DoublesDamageAwareConfig(enable_forced_switch_replacement_safety=False)
    config_on = DoublesDamageAwareConfig(enable_forced_switch_replacement_safety=True)

    results = {}
    arms = [
        ("A", "Safety OFF vs Basic", config_off, "basic", None, n_a),
        ("B", "Safety ON vs Basic", config_on, "basic", None, n_b),
        ("C", "Safety ON vs OFF", config_on, "mirror", config_off, n_c),
        ("D", "Safety ON vs SafeRandom", config_on, "safe_random", None, n_d),
    ]

    for arm_id, arm_name, cfg, opp, opp_cfg, n in arms:
        results[arm_id] = await run_matchup_with_watchdog(
            arm_name, cfg, opp, opp_cfg, n,
            f"logs/forced_switch_replacement_safety_{artifact_tag}_{arm_id}.jsonl",
            benchmark_arm=arm_id,
        )

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for k in sorted(results.keys()):
        r = results[k]
        err = r.get("error_detail", "")
        err_s = f" ERR: {err}" if err else ""
        print(f"  {r['name']:30s} | {r['status']:8s} | {r['finished']}/{r['planned']} | "
              f"{r['wins']}W {r['losses']}L ({r['win_rate']}%) | "
              f"FS: {r['forced_switch_count']} | "
              f"DT: {r['forced_switch_selected_double_threat']} | "
              f"QW: {r['forced_switch_selected_quad_weak']} | "
              f"Chg: {r['forced_switch_safety_selection_changed']}"
              f"{err_s}")

    # CSV
    csv_path = f"logs/forced_switch_replacement_safety_{artifact_tag}.csv"
    fieldnames = [
        "name", "status", "planned", "finished", "wins", "losses", "ties",
        "win_rate", "avg_turns", "benchmark_arm",
        "forced_switch_count", "forced_switch_safety_on_count",
        "forced_switch_selected_double_threat", "forced_switch_selected_quad_weak",
        "forced_switch_safety_selection_changed", "forced_switch_fallback_used",
        "forced_switch_score_gap_sum", "forced_switch_score_gap_count",
        "spread_count", "focus_fire_count",
    ]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for k in sorted(results.keys()):
            row = {fn: results[k].get(fn, "") for fn in fieldnames}
            w.writerow(row)
    print(f"\nCSV saved to {csv_path}")

    # Validate
    _validate_artifacts(artifact_tag, arms)

    return results


if __name__ == "__main__":
    asyncio.run(main())
