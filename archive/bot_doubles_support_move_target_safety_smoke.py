#!/usr/bin/env python3
"""Phase 6.3.8 — Support Move Target Hard Safety Smoke Benchmark.

4-arm smoke benchmark:
  A) safety OFF vs DoublesBasicAwarePlayer: 10 battles
  B) safety ON vs DoublesBasicAwarePlayer: 10 battles
  C) safety ON vs safety OFF: 10 battles
  D) safety ON vs DoublesSafeRandomPlayer: 10 battles

Watchdogs: heartbeat 30s, stall 180s, arm 300s.

Usage:
  ./venv/bin/python bot_doubles_support_move_target_safety_smoke.py --artifact-tag mytag [--overwrite]
"""
import argparse
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
ARM_TIMEOUT = 300


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
    return "ok" if caught_exception is None else "error", caught_exception


async def run_matchup_with_watchdog(name, config, opp_class_key, n_battles, log_path,
                                     arm_timeout=ARM_TIMEOUT, benchmark_arm="",
                                     opp_config=None):
    if opp_class_key == "basic":
        OppClass = DoublesBasicAwarePlayer
    elif opp_class_key == "safe_random":
        OppClass = DoublesSafeRandomPlayer
    elif opp_class_key == "damage_aware":
        OppClass = DoublesDamageAwarePlayer
    else:
        raise ValueError(f"Unknown opp_class_key: {opp_class_key}")

    suffix = random.randint(10000, 99999)
    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"Sup_{benchmark_arm}_{suffix}"[:18], None),
        verbose=False, config=config,
        audit_logger=DoublesDecisionAuditLogger(
            filepath=log_path, reset=True, detail_level="top5",
            benchmark_arm=benchmark_arm),
        max_concurrent_battles=MAX_CONCURRENT,
    )

    if opp_class_key == "damage_aware":
        opponent = OppClass(
            account_configuration=AccountConfiguration(f"OppC_{benchmark_arm}_{suffix}"[:18], None),
            verbose=False,
            config=opp_config or DoublesDamageAwareConfig(),
            max_concurrent_battles=MAX_CONCURRENT,
        )
    else:
        opponent = OppClass(
            account_configuration=AccountConfiguration(f"Opp_{benchmark_arm}_{suffix}"[:18], None),
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

    status, caught_exception = await _run_arm_with_watchdog(
        name, lambda: player.battle_against(opponent, n_battles=n_battles), heartbeat, arm_timeout)

    result = _make_result(name, n_battles, player, opponent, status, log_path, benchmark_arm=benchmark_arm)
    if caught_exception:
        result["error_detail"] = caught_exception
    await _cleanup_player(player)
    await _cleanup_player(opponent)
    if status != "ok":
        print(f"  [{name}] {status.upper()}: {caught_exception}")
    return result


# ========================== Metric counting ==========================


def _count_support_metrics(log_path):
    m = {
        "support_candidate_turns": 0,
        "wrong_side_candidates": 0,
        "wrong_side_blocked": 0,
        "wrong_side_selected": 0,
        "wrong_side_avoided": 0,
        "wrong_side_only_legal": 0,
        "heal_pulse_into_opponent": 0,
        "heal_pulse_into_ally": 0,
        "pollen_puff_ally": 0,
        "pollen_puff_opponent": 0,
        "spread_count": 0,
        "focus_fire_count": 0,
        "timeout_count": 0,
        "slot_candidate_blocked": 0,
        "slot_selected": 0,
        "slot_avoided": 0,
        "slot_only_legal": 0,
        "accounting_invariant_pass": True,
        "accounting_mutual_exclusion_pass": True,
    }
    if not os.path.exists(log_path):
        return m
    with open(log_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                for turn in rec.get("audit_turns", []):
                    if turn.get("focus_fire_triggered"):
                        m["focus_fire_count"] += 1

                    for sk in ("slot_0", "slot_1"):
                        slot = turn.get(sk, {})
                        if not slot:
                            continue
                        if slot.get("action_types", {}).get("spread"):
                            m["spread_count"] += 1
                        if slot.get("support_target_candidate_blocked"):
                            m["slot_candidate_blocked"] += 1
                        if slot.get("support_target_selected"):
                            m["slot_selected"] += 1
                        if slot.get("support_target_avoided"):
                            m["slot_avoided"] += 1
                        if slot.get("support_target_only_legal"):
                            m["slot_only_legal"] += 1
                        if slot.get("support_target_selected") and slot.get("support_target_avoided"):
                            m["accounting_mutual_exclusion_pass"] = False

                    candidates = turn.get("support_target_candidates", [])
                    if candidates:
                        m["support_candidate_turns"] += 1
                        slot_opp_selected = {0: False, 1: False}
                        for cand in candidates:
                            intended = cand.get("intended_side", "")
                            move_id = cand.get("move_id", "")
                            selected = cand.get("selected", False)
                            blocked = cand.get("blocked", False)
                            actual = cand.get("target_side", "")
                            # A "wrong-side" selection is
                            # when the move was classified
                            # as ally/opponent/self but the
                            # actual target_side does not
                            # match the intended side. We
                            # count only ACTUAL wrong-side,
                            # not just intended=opponent.
                            is_wrong_side = (
                                selected
                                and blocked
                                and (
                                    (
                                        intended == "opponent"
                                        and actual in ("ally", "self")
                                    )
                                    or (
                                        intended == "ally"
                                        and actual
                                        in ("opponent", "self")
                                    )
                                    or (
                                        intended == "self"
                                        and actual != "self"
                                    )
                                )
                            )
                            if intended in ("opponent",):
                                m["wrong_side_candidates"] += 1
                                if blocked:
                                    m["wrong_side_blocked"] += 1
                                if is_wrong_side:
                                    m["wrong_side_selected"] += 1
                            if move_id == "healpulse" and intended == "opponent" and is_wrong_side:
                                m["heal_pulse_into_opponent"] += 1
                            if move_id == "healpulse" and intended == "ally" and selected:
                                m["heal_pulse_into_ally"] += 1
                            if move_id == "pollenpuff" and intended == "ally" and selected:
                                m["pollen_puff_ally"] += 1
                            if move_id == "pollenpuff" and intended == "opponent" and selected:
                                m["pollen_puff_opponent"] += 1
            except Exception:
                continue
    m["wrong_side_avoided"] = m["wrong_side_blocked"] - m["wrong_side_selected"]
    m["accounting_invariant_pass"] = (m["slot_candidate_blocked"] == m["slot_selected"] + m["slot_avoided"])
    return m


def _make_result(name, n_battles, player, opponent, status, log_path, benchmark_arm=""):
    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles if hasattr(opponent, 'n_won_battles') else 0
    ties = finished - wins - losses
    wr = (wins / finished * 100) if finished > 0 else 0.0
    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0.0
    m = _count_support_metrics(log_path)
    m["timeout_count"] = getattr(player, "_timeout_count", 0)
    return {"name": name, "status": status, "planned": n_battles, "finished": finished,
            "wins": wins, "losses": losses, "ties": ties,
            "win_rate": f"{wr:.2f}", "avg_turns": f"{avg_turns:.2f}",
            "benchmark_arm": benchmark_arm, **m}


# ========================== main ==========================


async def main():
    p = argparse.ArgumentParser(description="Support Move Target Hard Safety Smoke Benchmark")
    p.add_argument("--artifact-tag", type=str, required=True)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument(
        "--n-battles", type=int, default=10,
        help="Battles per arm (default: 10).",
    )
    args = p.parse_args()
    tag = args.artifact_tag
    csv_path = f"logs/support_target_smoke_{tag}.csv"
    arm_paths = [f"logs/support_target_smoke_{tag}_{a}.jsonl" for a in ("A", "B", "C", "D")]

    if not args.overwrite:
        existing = [p for p in ([csv_path] + arm_paths) if os.path.exists(p)]
        if existing:
            print("Artifacts already exist:")
            for p in existing:
                print(f"  {p}")
            sys.exit(2)

    config_off = DoublesDamageAwareConfig()
    config_on = DoublesDamageAwareConfig()
    config_on.enable_support_move_target_hard_safety = True
    config_on.support_move_wrong_side_block_score = 0.0
    config_on.support_move_allow_only_legal_wrong_side = True

    n_battles = args.n_battles
    arms = [
        ("A", "safety OFF vs Basic", "basic", n_battles, config_off, None),
        ("B", "safety ON vs Basic", "basic", n_battles, config_on, None),
        ("C", "safety ON vs safety OFF", "damage_aware", n_battles, config_on, config_off),
        ("D", "safety ON vs SafeRandom", "safe_random", n_battles, config_on, None),
    ]
    results = []
    for arm_id, name, opp_key, n_battles, config, opp_config in arms:
        log_path = f"logs/support_target_smoke_{tag}_{arm_id}.jsonl"
        result = await run_matchup_with_watchdog(
            name, config, opp_key, n_battles, log_path,
            arm_timeout=ARM_TIMEOUT, benchmark_arm=arm_id,
            opp_config=opp_config,
        )
        results.append(result)
        print(f"  {arm_id}: {result.get('win_rate','N/A')}% WR, "
              f"{result.get('wins',0)}W/{result.get('losses',0)}L, "
              f"finished={result.get('finished',0)}")

    fieldnames = [
        "name", "status", "planned", "finished", "wins", "losses", "ties",
        "win_rate", "avg_turns", "benchmark_arm",
        "support_candidate_turns",
        "wrong_side_candidates", "wrong_side_blocked", "wrong_side_selected",
        "wrong_side_avoided", "wrong_side_only_legal",
        "heal_pulse_into_opponent", "heal_pulse_into_ally",
        "pollen_puff_ally", "pollen_puff_opponent",
        "slot_candidate_blocked", "slot_selected", "slot_avoided", "slot_only_legal",
        "spread_count", "focus_fire_count", "timeout_count",
        "accounting_invariant_pass", "accounting_mutual_exclusion_pass",
    ]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, False) for k in fieldnames})
    print(f"\nSaved: {csv_path}")

    all_ok = all(r.get("status") == "ok" for r in results)
    if all_ok:
        print("\n--- Overall Summary ---")
        for r in results:
            print(f"  {r['benchmark_arm']}: {r.get('win_rate')}% WR, "
                  f"{r.get('finished')}/{r.get('planned')} battles, "
                  f"wrong_side_blocked={r.get('wrong_side_blocked', 0)}, "
                  f"wrong_side_selected={r.get('wrong_side_selected', 0)}, "
                  f"wrong_side_avoided={r.get('wrong_side_avoided', 0)}, "
                  f"heal_opp={r.get('heal_pulse_into_opponent', 0)}, "
                  f"heal_ally={r.get('heal_pulse_into_ally', 0)}, "
                  f"pollen_ally={r.get('pollen_puff_ally', 0)}, "
                  f"pollen_opp={r.get('pollen_puff_opponent', 0)}, "
                  f"only_legal={r.get('slot_only_legal', 0)}, "
                  f"spread={r.get('spread_count', 0)}, "
                  f"focus={r.get('focus_fire_count', 0)}, "
                  f"timeout={r.get('timeout_count', 0)}")
        print("\nAll arms completed successfully.")
        sys.exit(0)
    else:
        failed = [r.get("name") for r in results if r.get("status") != "ok"]
        print(f"\nFAILED arms: {failed}")
        sys.exit(3)


if __name__ == "__main__":
    asyncio.run(main())
