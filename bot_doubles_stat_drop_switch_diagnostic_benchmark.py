#!/usr/bin/env python3
"""Phase 6.4.3a Stat-Drop Switch Diagnostic Benchmark.

Diagnostic-only qualification run.  Does NOT change scoring or defaults.
Measures whether stat-drop switch logic is worth turning into scoring.

Arms:
  A) current bot vs DoublesBasicAwarePlayer — 300 battles
  B) current bot vs DoublesSafeRandomPlayer — 100 battles
  C) current bot mirror vs current bot mirror — 300 battles

Watchdogs:
  - heartbeat every 30s
  - stall timeout 180s
  - arm timeout 3600s
  - FIRST_COMPLETED orchestration

Artifacts:
  logs/stat_drop_switch_diagnostic_<tag>.csv
  logs/stat_drop_switch_diagnostic_<tag>_<arm>.jsonl
"""
import atexit
import asyncio
import csv
import json
import os
import random
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))

# Benchmark-process exit guard
import poke_env.concurrency  # noqa: F401
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
                                     arm_timeout=3600, benchmark_arm=""):
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


def _count_stat_drop_metrics(log_path):
    m = {
        "severe_negative_boost_active": 0,
        "switch_available": 0,
        "switched": 0,
        "stayed": 0,
        "stayed_productive": 0,
        "stayed_unproductive": 0,
        "only_legal_no_switch": 0,
        "offensive_drop": 0,
        "defensive_drop": 0,
        "speed_drop": 0,
    }
    unproductive_species = Counter()
    unproductive_actions = Counter()

    if not os.path.exists(log_path):
        return m, unproductive_species, unproductive_actions

    with open(log_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                for turn in record.get("audit_turns", []):
                    for sk in ("slot_0", "slot_1"):
                        s = turn.get(sk, {})
                        if not s:
                            continue
                        if not s.get("severe_negative_boost_active"):
                            continue
                        m["severe_negative_boost_active"] += 1
                        cats = s.get("severe_negative_boost_categories", [])
                        if "offensive" in cats:
                            m["offensive_drop"] += 1
                        if "defensive" in cats:
                            m["defensive_drop"] += 1
                        if "speed" in cats:
                            m["speed_drop"] += 1
                        if s.get("severe_negative_boost_switch_available"):
                            m["switch_available"] += 1
                        if s.get("severe_negative_boost_switched"):
                            m["switched"] += 1
                        if s.get("severe_negative_boost_stayed"):
                            m["stayed"] += 1
                        if s.get("severe_negative_boost_stayed_productive"):
                            m["stayed_productive"] += 1
                        if s.get("severe_negative_boost_stayed_unproductive"):
                            m["stayed_unproductive"] += 1
                            species = s.get("severe_negative_boost_species", "unknown")
                            unproductive_species[species] += 1
                            action = s.get("severe_negative_boost_selected_action", "unknown")
                            unproductive_actions[action] += 1
                        if s.get("severe_negative_boost_only_legal_no_switch"):
                            m["only_legal_no_switch"] += 1
            except Exception:
                continue
    return m, unproductive_species, unproductive_actions


def _make_result(name, n_battles, player, opponent, status, log_path, benchmark_arm=""):
    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles if hasattr(opponent, 'n_won_battles') else 0
    ties = finished - wins - losses
    wr = (wins / finished * 100) if finished > 0 else 0.0
    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0.0

    m, unprod_species, unprod_actions = _count_stat_drop_metrics(log_path)

    return {
        "name": name, "status": status,
        "planned": n_battles, "finished": finished,
        "wins": wins, "losses": losses, "ties": ties,
        "win_rate": f"{wr:.2f}", "avg_turns": f"{avg_turns:.2f}",
        "benchmark_arm": benchmark_arm,
        "top_unproductive_species": dict(unprod_species.most_common(10)),
        "top_unproductive_actions": dict(unprod_actions.most_common(10)),
        **m,
    }


def label_name(name):
    return name.replace(" ", "_").replace("vs", "")


def _validate_artifacts(artifact_tag, arms):
    print("\n" + "=" * 70)
    print("ARTIFACT VALIDATION")
    print("=" * 70)
    all_ok = True

    csv_path = f"logs/stat_drop_switch_diagnostic_{artifact_tag}.csv"
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
        jsonl_path = f"logs/stat_drop_switch_diagnostic_{artifact_tag}_{arm_id}.jsonl"
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
    parser = argparse.ArgumentParser(description="Phase 6.4.3a Stat-Drop Switch Diagnostic Benchmark")
    parser.add_argument("--smoke", action="store_true", help="Run smoke (10/10/10)")
    parser.add_argument("--artifact-tag", default="", help="Tag for output filenames")
    parser.add_argument("--overwrite", action="store_true", help="Allow overwriting existing artifacts")
    args = parser.parse_args()

    if args.smoke:
        n_a, n_b, n_c = 10, 10, 10
        tag = "smoke"
    else:
        n_a, n_b, n_c = 300, 100, 300
        tag = "full"

    artifact_tag = args.artifact_tag if args.artifact_tag else tag

    os.makedirs("logs", exist_ok=True)

    output_paths = [
        f"logs/stat_drop_switch_diagnostic_{artifact_tag}.csv",
        f"logs/stat_drop_switch_diagnostic_{artifact_tag}_A.jsonl",
        f"logs/stat_drop_switch_diagnostic_{artifact_tag}_B.jsonl",
        f"logs/stat_drop_switch_diagnostic_{artifact_tag}_C.jsonl",
    ]

    if not args.overwrite:
        existing = [p for p in output_paths if os.path.exists(p)]
        if existing:
            print("ERROR: artifact(s) already exist. Use --overwrite to replace.")
            for p in existing:
                print(f"  {p}")
            sys.exit(1)

    # Use current default config (diagnostic-only, no scoring changes)
    config = DoublesDamageAwareConfig()

    results = {}
    arms = [
        ("A", "Bot vs Basic", config, "basic", None, n_a),
        ("B", "Bot vs SafeRandom", config, "safe_random", None, n_b),
        ("C", "Bot vs Bot (mirror)", config, "mirror", config, n_c),
    ]

    for arm_id, arm_name, cfg, opp, opp_cfg, n in arms:
        results[arm_id] = await run_matchup_with_watchdog(
            arm_name, cfg, opp, opp_cfg, n,
            f"logs/stat_drop_switch_diagnostic_{artifact_tag}_{arm_id}.jsonl",
            benchmark_arm=arm_id,
        )

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for k in sorted(results.keys()):
        r = results[k]
        err = r.get("error_detail", "")
        err_s = f" ERR: {err}" if err else ""
        print(f"  {r['name']:30s} | {r['status']:8s} | {r['finished']}/{r['planned']} | "
              f"{r['wins']}W {r['losses']}L ({r['win_rate']}%) | "
              f"Severe: {r['severe_negative_boost_active']} | "
              f"StayedUnprod: {r['stayed_unproductive']}"
              f"{err_s}")

    # Write CSV
    csv_path = f"logs/stat_drop_switch_diagnostic_{artifact_tag}.csv"
    fieldnames = [
        "name", "status", "planned", "finished", "wins", "losses", "ties",
        "win_rate", "avg_turns", "benchmark_arm",
        "severe_negative_boost_active", "switch_available", "switched",
        "stayed", "stayed_productive", "stayed_unproductive",
        "only_legal_no_switch", "offensive_drop", "defensive_drop", "speed_drop",
    ]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for k in sorted(results.keys()):
            row = {fn: results[k].get(fn, "") for fn in fieldnames}
            w.writerow(row)
    print(f"\nCSV saved to {csv_path}")

    # Print top unproductive cases
    print("\n" + "=" * 70)
    print("TOP UNPRODUCTIVE STAYED-IN SPECIES")
    print("=" * 70)
    for k in sorted(results.keys()):
        r = results[k]
        top_sp = r.get("top_unproductive_species", {})
        top_ac = r.get("top_unproductive_actions", {})
        if top_sp:
            print(f"  [{r['name']}]")
            for sp, cnt in list(top_sp.items())[:10]:
                print(f"    {sp}: {cnt}")
        if top_ac:
            print(f"  [{r['name']}] actions:")
            for ac, cnt in list(top_ac.items())[:10]:
                print(f"    {ac}: {cnt}")

    # Validate
    _validate_artifacts(artifact_tag, arms)

    return results


if __name__ == "__main__":
    asyncio.run(main())
