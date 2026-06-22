#!/usr/bin/env python3
"""Phase 6.3.5b Benchmark: Deterministic Singleton Ability & Priority Terrain safety.

7 independent arms design:
  - Run A (Control vs Basic): 300 (or 10 for smoke)
  - Run B (Singleton-only vs Basic): 300 (or 10 for smoke)
  - Run C (Singleton-only vs Control): 300 (or 10 for smoke)
  - Run D (Singleton-only vs SafeRandom): 300 (or 10 for smoke)
  - Run E (Priority-only vs Basic): 300 (or 10 for smoke)
  - Run F (Priority-only vs Control): 300 (or 10 for smoke)
  - Run G (Priority-only vs SafeRandom): 300 (or 10 for smoke)

With watchdogs:
  - progress heartbeat every HEARTBEAT_INTERVAL seconds
  - stall watchdog: raise StallError after STALL_TIMEOUT without progress
  - total arm timeout via asyncio.wait_for
  - FIRST_COMPLETED so normal battle_task finish is detected
"""
import atexit
import asyncio
import csv
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

# Benchmark-process exit guard: unregister the poke_env atexit callback
# that deadlocks during interpreter shutdown.  The POKE_LOOP daemon thread
# is discarded by the interpreter without a join.  This is NOT imported
# from poke_env_test_cleanup.py — it is self-contained in the benchmark.
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
STALL_TIMEOUT = 180  # seconds without a completed battle
HEARTBEAT_INTERVAL = 30  # seconds


class StallError(Exception):
    """Raised when no battle completes within STALL_TIMEOUT seconds."""
    pass


async def _cleanup_player(player):
    """Best-effort cleanup of a poke-env Player.  Does NOT clear battles
    because _make_result needs battle data after the arm completes."""
    try:
        if hasattr(player, "ps_client") and hasattr(player.ps_client, "_stop_listening"):
            await player.ps_client._stop_listening()
    except Exception:
        pass


async def _run_arm_with_watchdog(
    name, battle_coro_factory, heartbeat_coro_factory, arm_timeout
):
    """Testable async orchestration for a single benchmark arm.

    battle_coro_factory: async callable () -> result (the battle task)
    heartbeat_coro_factory: async callable () -> None (raises StallError)
    arm_timeout: seconds before outer timeout

    Returns (status, exception_info).
    Uses FIRST_COMPLETED so normal battle_task finish is detected.
    """
    battle_task = asyncio.create_task(battle_coro_factory())
    watchdog_task = asyncio.create_task(heartbeat_coro_factory())
    caught_exception = None

    try:
        done, pending = await asyncio.wait_for(
            asyncio.wait(
                {battle_task, watchdog_task},
                return_when=asyncio.FIRST_COMPLETED,
            ),
            timeout=arm_timeout,
        )

        # If watchdog completed first with an exception, propagate it
        if watchdog_task in done:
            w_exc = watchdog_task.exception()
            if w_exc and not isinstance(w_exc, asyncio.CancelledError):
                raise w_exc

        # If battle completed with an exception, propagate it
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
    """Run a single matchup with heartbeat, stall watchdog, and arm timeout."""
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

            print(f"  [{name}] {elapsed:.0f}s elapsed | {finished}/{n_battles} done | "
                  f"{wins}W {losses}L | {since_last:.0f}s since last")

            if since_last > STALL_TIMEOUT:
                raise StallError(f"Stall: {name}: no battle finished in {STALL_TIMEOUT}s")

    async def run_battle():
        return await player.battle_against(opponent, n_battles=n_battles)

    status, caught_exception = await _run_arm_with_watchdog(
        name, run_battle, heartbeat, arm_timeout,
    )

    # Build result BEFORE cleanup (needs player.battles for avg_turns)
    result = _make_result(name, n_battles, player, opponent, status, log_path,
                          benchmark_arm=benchmark_arm)
    if caught_exception:
        result["error_detail"] = caught_exception

    # Cleanup after result is captured
    await _cleanup_player(player)
    await _cleanup_player(opponent)

    if status != "ok":
        print(f"  [{name}] {status.upper()}: {caught_exception}")

    return result


def _make_result(name, n_battles, player, opponent, status, log_path, benchmark_arm=""):
    """Build result dict. Must be called BEFORE _cleanup_player clears battles."""
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
        "crashes": 0, "exceptions": 0, "timeouts": 0,
        "benchmark_arm": benchmark_arm,
        **m,
    }


def _count_audit_metrics(log_path):
    """Count Phase 6.3.5b and general metrics from JSONL using observer fields.

    Error field definitions:
      observed_selected_errors =
          singleton_ground_into_levitate_selected_observed
      only_legal_errors =
          observed_selected_errors AND singleton_only_legal_action
      avoidable_selected_errors =
          observed_selected_errors AND NOT singleton_only_legal_action
    """
    m = {
        "protect_cnt": 0, "spread_cnt": 0, "focus_fire_cnt": 0,
        "singleton_resolved": 0, "singleton_levitate_opportunities": 0,
        "singleton_hard_blocks": 0, "ground_into_singleton_levitate_selected": 0,
        "singleton_only_legal": 0, "singleton_ignored": 0,
        "ground_into_flying_selected": 0, "ground_into_flying_avoided": 0,
        "dual_type_immunity_selected": 0,
        "priority_field_blocked": 0,
        "priority_selected_into_psychic_terrain": 0,
        "sucker_punch_selected_into_psychic_terrain": 0,
        "priority_block_avoided": 0,
        "priority_only_legal": 0,
        # Phase 6.3.5b observer-derived metrics
        "observed_selected_errors": 0,
        "avoidable_selected_errors": 0,
        "only_legal_errors": 0,
        "joint_selections_changed": 0,
        "slot_selections_changed": 0,
        "blocked_candidates": 0,
        "hard_blocks_applied": 0,
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
                    if turn.get("focus_fire_triggered"):
                        m["focus_fire_cnt"] += 1
                    any_slot_changed = False
                    for sk in ("slot_0", "slot_1"):
                        s = turn.get(sk, {})
                        if not s:
                            continue
                        at = s.get("action_types", {})
                        if at and at.get("protect"):
                            m["protect_cnt"] += 1
                        if at and at.get("spread"):
                            m["spread_cnt"] += 1
                        if s.get("singleton_resolution_source") == "deterministic_singleton":
                            m["singleton_resolved"] += 1
                        if s.get("singleton_levitate_opportunity_observed"):
                            m["singleton_levitate_opportunities"] += 1
                        is_observed_err = bool(
                            s.get("singleton_ground_into_levitate_selected_observed")
                        )
                        if is_observed_err:
                            m["ground_into_singleton_levitate_selected"] += 1
                            m["observed_selected_errors"] += 1
                        is_only_legal = bool(s.get("singleton_only_legal_action"))
                        if is_only_legal:
                            m["singleton_only_legal"] += 1
                        if is_observed_err and is_only_legal:
                            m["only_legal_errors"] += 1
                        if is_observed_err and not is_only_legal:
                            m["avoidable_selected_errors"] += 1
                        if s.get("singleton_hard_block_applied"):
                            m["singleton_hard_blocks"] += 1
                            m["hard_blocks_applied"] += 1
                        if s.get("singleton_blocked_candidate_observed"):
                            m["blocked_candidates"] += 1
                        if s.get("singleton_ability_suppressed"):
                            m["singleton_ignored"] += 1
                        if s.get("singleton_selection_changed_by_safety"):
                            m["slot_selections_changed"] += 1
                            any_slot_changed = True
                        if s.get("ground_into_flying_selected"):
                            m["ground_into_flying_selected"] += 1
                        if s.get("ground_into_flying_avoided"):
                            m["ground_into_flying_avoided"] += 1
                        if s.get("dual_type_immunity_selected"):
                            m["dual_type_immunity_selected"] += 1
                        if s.get("priority_move_field_blocked"):
                            m["priority_field_blocked"] += 1
                        if s.get("priority_move_selected_into_psychic_terrain"):
                            m["priority_selected_into_psychic_terrain"] += 1
                        if s.get("sucker_punch_selected_into_psychic_terrain"):
                            m["sucker_punch_selected_into_psychic_terrain"] += 1
                        if s.get("priority_move_block_avoided"):
                            m["priority_block_avoided"] += 1
                        if s.get("priority_move_only_legal"):
                            m["priority_only_legal"] += 1
                    if any_slot_changed:
                        m["joint_selections_changed"] += 1
            except Exception:
                continue
    return m


def label_name(name):
    return name.replace(" ", "_").replace("vs", "")


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true",
                        help="Run smoke test (10/10/10/10/10/10/10)")
    parser.add_argument("--artifact-tag", default="",
                        help="Tag for output filenames (e.g. phase635d_corrected_smoke)")
    parser.add_argument("--overwrite", action="store_true",
                        help="Allow overwriting existing artifacts")
    args = parser.parse_args()

    if args.smoke:
        n_battles = 10
        tag = "smoke"
    else:
        n_battles = 300
        tag = "full"

    artifact_tag = args.artifact_tag if args.artifact_tag else tag

    os.makedirs("logs", exist_ok=True)
    singleton_csv_path = f"logs/singleton_safety_{artifact_tag}.csv"
    priority_csv_path = f"logs/priority_safety_{artifact_tag}.csv"

    # Collect all output paths and fail if any exist (unless --overwrite)
    output_paths = [singleton_csv_path, priority_csv_path]
    for arm_id in ("A", "B", "C", "D", "E", "F", "G"):
        output_paths.append(f"logs/singleton_{artifact_tag}_{arm_id}.jsonl")

    if not args.overwrite:
        existing = [p for p in output_paths if os.path.exists(p)]
        if existing:
            print("ERROR: artifact(s) already exist. Use --overwrite to replace.")
            for p in existing:
                print(f"  {p}")
            sys.exit(1)

    config_control = DoublesDamageAwareConfig(
        enable_ability_hard_safety_only=True,
        ability_hard_safety_allow_singleton_deduction=False,
        enable_priority_field_hard_safety=False,
    )
    config_singleton = DoublesDamageAwareConfig(
        enable_ability_hard_safety_only=True,
        ability_hard_safety_allow_singleton_deduction=True,
        enable_priority_field_hard_safety=False,
    )
    config_priority = DoublesDamageAwareConfig(
        enable_ability_hard_safety_only=True,
        ability_hard_safety_allow_singleton_deduction=False,
        enable_priority_field_hard_safety=True,
    )

    results = {}
    arms = [
        ("A", "Control vs Basic",         config_control,  "basic",      None,           n_battles),
        ("B", "Singleton-only vs Basic",   config_singleton, "basic",     None,           n_battles),
        ("C", "Singleton-only vs Control", config_singleton, "mirror",    config_control, n_battles),
        ("D", "Singleton-only vs SafeRandom", config_singleton, "safe_random", None,     n_battles),
        ("E", "Priority-only vs Basic",    config_priority, "basic",      None,           n_battles),
        ("F", "Priority-only vs Control",  config_priority, "mirror",     config_control, n_battles),
        ("G", "Priority-only vs SafeRandom", config_priority, "safe_random", None,       n_battles),
    ]

    for arm_id, arm_name, cfg, opp, opp_cfg, n in arms:
        results[arm_id] = await run_matchup_with_watchdog(
            arm_name, cfg, opp, opp_cfg, n,
            f"logs/singleton_{artifact_tag}_{arm_id}.jsonl",
            benchmark_arm=arm_id,
        )

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for k in sorted(results.keys()):
        r = results[k]
        err_detail = r.get("error_detail", "")
        err_suffix = f" ERR: {err_detail}" if err_detail else ""
        print(f"  {r['name']:30s} | {r['status']:8s} | {r['finished']}/{r['planned']} | "
              f"{r['wins']}W {r['losses']}L ({r['win_rate']}%) | "
              f"ObsErr: {r['observed_selected_errors']} | "
              f"HardBlk: {r['hard_blocks_applied']}"
              f"{err_suffix}")

    fieldnames = [
        "name", "status", "planned", "finished", "wins", "losses", "ties",
        "win_rate", "avg_turns", "crashes", "exceptions", "timeouts",
        "benchmark_arm",
        "protect_cnt", "spread_cnt", "focus_fire_cnt",
        "singleton_resolved", "singleton_levitate_opportunities",
        "singleton_hard_blocks", "ground_into_singleton_levitate_selected",
        "singleton_only_legal", "singleton_ignored",
        "ground_into_flying_selected", "ground_into_flying_avoided",
        "dual_type_immunity_selected",
        "priority_field_blocked", "priority_selected_into_psychic_terrain",
        "sucker_punch_selected_into_psychic_terrain", "priority_block_avoided",
        "priority_only_legal",
        "observed_selected_errors", "avoidable_selected_errors",
        "only_legal_errors", "joint_selections_changed",
        "slot_selections_changed", "blocked_candidates", "hard_blocks_applied",
    ]

    with open(singleton_csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for k in ["A", "B", "C", "D"]:
            row = {fn: results[k].get(fn, "") for fn in fieldnames}
            w.writerow(row)
    print(f"\nSingleton CSV saved to {singleton_csv_path}")

    with open(priority_csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for k in ["A", "E", "F", "G"]:
            row = {fn: results[k].get(fn, "") for fn in fieldnames}
            w.writerow(row)
    print(f"Priority CSV saved to {priority_csv_path}")

    return results


if __name__ == "__main__":
    asyncio.run(main())
