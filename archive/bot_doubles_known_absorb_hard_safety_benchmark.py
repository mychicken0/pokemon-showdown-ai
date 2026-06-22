#!/usr/bin/env python3
"""Phase 6.3.6a — Known Absorb Hard Safety Verification Smoke.

Runs current default config against Basic and SafeRandom to verify that
Phase 6.3.6 actually fixes repeated direct known absorb selections.

Artifacts:
  logs/known_absorb_hard_safety_<tag>.csv
  logs/known_absorb_hard_safety_<tag>_A.jsonl
  logs/known_absorb_hard_safety_<tag>_B.jsonl
"""
import asyncio
import atexit
import csv
import json
import os
import random
import sys
import time

# Unregister poke_env atexit deadlock
try:
    import poke_env.concurrency
    _clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
    if _clear_loop is not None:
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


def count_known_absorb_metrics(log_path):
    """Count known absorb metrics from JSONL audit log."""
    m = {
        "direct_known_absorb_move_selected": 0,
        "direct_known_absorb_repeat_selected": 0,
        "direct_known_absorb_move_avoided": 0,
        "direct_known_absorb_only_legal": 0,
        "spread_count": 0,
        "focus_fire_count": 0,
        "protect_count": 0,
        "reason_split": {},
    }
    if not os.path.exists(log_path):
        return m

    with open(log_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                battle = json.loads(line)
                for turn in battle.get("audit_turns", []):
                    if turn.get("focus_fire_triggered"):
                        m["focus_fire_count"] += 1
                    for slot_key in ("slot_0", "slot_1"):
                        slot = turn.get(slot_key, {})
                        if not slot:
                            continue
                        if slot.get("direct_absorb_immune_move_selected"):
                            m["direct_known_absorb_move_selected"] += 1
                            reason = slot.get("direct_absorb_block_reason", "unknown")
                            m["reason_split"][reason] = m["reason_split"].get(reason, 0) + 1
                            if slot.get("direct_absorb_only_legal_action"):
                                m["direct_known_absorb_only_legal"] += 1
                        if slot.get("direct_known_absorb_repeat_selected"):
                            m["direct_known_absorb_repeat_selected"] += 1
                        if slot.get("direct_absorb_hard_block_avoided"):
                            m["direct_known_absorb_move_avoided"] += 1
                        if slot.get("action_types", {}).get("spread"):
                            m["spread_count"] += 1
                        if slot.get("action_types", {}).get("protect"):
                            m["protect_count"] += 1
            except Exception:
                continue

    return m


async def run_matchup(name, config, opp_class, opp_config, n_battles, log_path, label,
                      artifact_tag, arm_timeout=1800):
    suffix = random.randint(1000, 9999)
    bot_name = f"Absorb_{label}_{suffix}"[:18]
    opp_name = f"Opp_{label}_{suffix}"[:18]

    audit_logger = DoublesDecisionAuditLogger(
        filepath=log_path,
        reset=True,
        detail_level="top5",
        benchmark_arm=label,
    )

    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        verbose=False,
        config=config,
        audit_logger=audit_logger,
        max_concurrent_battles=MAX_CONCURRENT,
    )

    if opp_class == DoublesBasicAwarePlayer:
        opponent = DoublesBasicAwarePlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            verbose=False,
            max_concurrent_battles=MAX_CONCURRENT,
        )
    elif opp_class == DoublesSafeRandomPlayer:
        opponent = DoublesSafeRandomPlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            max_concurrent_battles=MAX_CONCURRENT,
        )
    else:
        raise ValueError(f"Unknown opponent class: {opp_class}")

    start_time = time.time()
    state = {"last_battle_time": start_time, "last_finished": 0}

    async def heartbeat():
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            elapsed = time.time() - start_time
            finished = player.n_finished_battles
            since_last = time.time() - state["last_battle_time"]
            if finished > state["last_finished"]:
                state["last_battle_time"] = time.time()
                state["last_finished"] = finished
            print(f"  [{name}] {elapsed:.0f}s | {finished}/{n_battles} | {since_last:.0f}s since last")
            if since_last > STALL_TIMEOUT:
                raise StallError(f"Stall: {name}: no battle finished in {STALL_TIMEOUT}s")

    async def run_battle():
        return await player.battle_against(opponent, n_battles=n_battles)

    status, caught_exception = await _run_arm_with_watchdog(name, run_battle, heartbeat, arm_timeout)

    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles
    ties = finished - wins - losses
    win_rate = (wins / finished * 100) if finished > 0 else 0.0
    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0.0

    m = count_known_absorb_metrics(log_path)

    if status != "ok":
        print(f"  [{name}] {status.upper()}: {caught_exception}")

    await _cleanup_player(player)
    await _cleanup_player(opponent)

    return {
        "matchup": name,
        "label": label,
        "status": status,
        "planned": n_battles,
        "finished": finished,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "win_rate": f"{win_rate:.2f}",
        "avg_turns": f"{avg_turns:.2f}",
        "error_detail": caught_exception or "",
        **m,
    }


def validate_artifacts(artifact_tag, arms):
    print("\n" + "=" * 70)
    print("ARTIFACT VALIDATION")
    print("=" * 70)
    all_ok = True

    csv_path = f"logs/known_absorb_hard_safety_{artifact_tag}.csv"
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

    for arm_id, arm_name, _cfg, _opp, _opp_cfg, n in arms:
        jsonl_path = f"logs/known_absorb_hard_safety_{artifact_tag}_{arm_id}.jsonl"
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

    print(f"\n  Overall: {'PASS' if all_ok else 'FAIL'}")
    return all_ok


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Phase 6.3.6a Known Absorb Verification Smoke")
    parser.add_argument("--smoke", action="store_true", help="Run smoke (100/50)")
    parser.add_argument("--artifact-tag", default="", help="Tag for output filenames")
    parser.add_argument("--overwrite", action="store_true", help="Allow overwriting existing artifacts")
    args = parser.parse_args()

    if args.smoke:
        n_a, n_b = 100, 50
        tag = "smoke"
    else:
        n_a, n_b = 300, 100
        tag = "full"

    artifact_tag = args.artifact_tag if args.artifact_tag else f"phase636a_{tag}"

    os.makedirs("logs", exist_ok=True)

    output_paths = [
        f"logs/known_absorb_hard_safety_{artifact_tag}.csv",
        f"logs/known_absorb_hard_safety_{artifact_tag}_A.jsonl",
        f"logs/known_absorb_hard_safety_{artifact_tag}_B.jsonl",
    ]

    if not args.overwrite:
        existing = [p for p in output_paths if os.path.exists(p)]
        if existing:
            print("ERROR: artifact(s) already exist. Use --overwrite to replace.")
            for p in existing:
                print(f"  {p}")
            sys.exit(1)

    config = DoublesDamageAwareConfig()

    results = {}
    arms = [
        ("A", "Current Default vs Basic", config, DoublesBasicAwarePlayer, None, n_a),
        ("B", "Current Default vs SafeRandom", config, DoublesSafeRandomPlayer, None, n_b),
    ]

    for arm_id, arm_name, cfg, opp, opp_cfg, n in arms:
        results[arm_id] = await run_matchup(
            arm_name, cfg, opp, opp_cfg, n,
            f"logs/known_absorb_hard_safety_{artifact_tag}_{arm_id}.jsonl",
            arm_id, artifact_tag,
        )

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for k in sorted(results.keys()):
        r = results[k]
        err = r.get("error_detail", "")
        err_s = f" ERR: {err}" if err else ""
        print(f"  {r['matchup']:35s} | {r['status']:8s} | {r['finished']}/{r['planned']} | "
              f"{r['wins']}W {r['losses']}L ({r['win_rate']}%) | "
              f"DA_sel: {r['direct_known_absorb_move_selected']} | "
              f"DA_rep: {r['direct_known_absorb_repeat_selected']} | "
              f"DA_avd: {r['direct_known_absorb_move_avoided']} | "
              f"DA_ol: {r['direct_known_absorb_only_legal']}"
              f"{err_s}")

    csv_path = f"logs/known_absorb_hard_safety_{artifact_tag}.csv"
    fieldnames = [
        "matchup", "label", "status", "planned", "finished", "wins", "losses", "ties",
        "win_rate", "avg_turns", "error_detail",
        "direct_known_absorb_move_selected", "direct_known_absorb_repeat_selected",
        "direct_known_absorb_move_avoided", "direct_known_absorb_only_legal",
        "spread_count", "focus_fire_count", "protect_count",
    ]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for k in sorted(results.keys()):
            w.writerow(results[k])
    print(f"\nCSV saved to {csv_path}")

    for k in sorted(results.keys()):
        r = results[k]
        rs = r.get("reason_split", {})
        if rs:
            print(f"\n  [{r['matchup']}] Reason split:")
            for reason, cnt in sorted(rs.items(), key=lambda x: -x[1]):
                print(f"    {reason}: {cnt}")

    validate_artifacts(artifact_tag, arms)

    return results


if __name__ == "__main__":
    asyncio.run(main())
