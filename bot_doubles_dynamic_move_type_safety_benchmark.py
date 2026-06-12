#!/usr/bin/env python3
"""Phase 6.3.7m.3 — Dynamic Aura Wheel Local Smoke Qualification (final).

Smoke arms:
  A) Current bot vs DoublesBasicAwarePlayer — 100 battles
  B) Current bot vs DoublesSafeRandomPlayer — 50 battles

Watchdogs: heartbeat 30s, stall 180s, arm 1800s.

Usage:
  ./venv/bin/python bot_doubles_dynamic_move_type_safety_benchmark.py --artifact-tag mytag [--overwrite]
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


async def run_matchup_with_watchdog(name, config, opp_class, n_battles, log_path,
                                     arm_timeout=1800, benchmark_arm=""):
    if opp_class == "basic":
        OppClass = DoublesBasicAwarePlayer
    elif opp_class == "safe_random":
        OppClass = DoublesSafeRandomPlayer
    else:
        raise ValueError(f"Unknown opp_class: {opp_class}")
    suffix = random.randint(10000, 99999)
    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"SinB_DT_{suffix}"[:18], None),
        verbose=False, config=config,
        audit_logger=DoublesDecisionAuditLogger(
            filepath=log_path, reset=True, detail_level="top5",
            benchmark_arm=benchmark_arm),
        max_concurrent_battles=MAX_CONCURRENT,
    )
    opponent = OppClass(
        account_configuration=AccountConfiguration(f"Opp_DT_{suffix}"[:18], None),
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


# ========================== Metric counting (per-slot-turn) ==========================

def _count_dynamic_metrics(log_path):
    m = {
        "dynamic_candidate_opportunity_turns": 0,
        "full_belly_candidate_opportunities": 0,
        "hangry_candidate_opportunities": 0,
        "full_belly_aurawheel_selected": 0,
        "hangry_aurawheel_selected": 0,
        "full_belly_known_volt_absorb_opportunities": 0,
        "full_belly_known_volt_absorb_blocked": 0,
        "full_belly_known_volt_absorb_selected": 0,
        "hangry_known_volt_absorb_opportunities": 0,
        "hangry_known_volt_absorb_selected_legal": 0,
        "blocked_total": 0, "selected_total": 0, "avoided_total": 0,
        "spread_count": 0, "focus_fire_count": 0, "timeout_count": 0,
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
                        # --- generic per-slot metrics (before table gate) ---
                        if slot.get("dynamic_type_absorb_candidate_blocked"):
                            m["blocked_total"] += 1
                        if slot.get("dynamic_type_absorb_selected"):
                            m["selected_total"] += 1
                        if slot.get("dynamic_type_absorb_avoided"):
                            m["avoided_total"] += 1
                        if slot.get("dynamic_type_absorb_selected") and slot.get("dynamic_type_absorb_avoided"):
                            m["accounting_mutual_exclusion_pass"] = False
                        if slot.get("action_types", {}).get("spread"):
                            m["spread_count"] += 1
                        # --- dynamic opportunity metrics ---
                        table = slot.get("dynamic_type_absorb_candidate_target_table", [])
                        if not table:
                            continue
                        m["dynamic_candidate_opportunity_turns"] += 1

                        has_full_belly = any(r.get("form") == "morpeko" and r.get("effective_type") == "ELECTRIC" for r in table)
                        has_hangry = any(r.get("form") == "morpekohangry" and r.get("effective_type") == "DARK" for r in table)
                        if has_full_belly:
                            m["full_belly_candidate_opportunities"] += 1
                        if has_hangry:
                            m["hangry_candidate_opportunities"] += 1

                        fb_vabsorb = any(r.get("form") == "morpeko" and r.get("effective_type") == "ELECTRIC" and r.get("target_known_ability") == "voltabsorb" for r in table)
                        hg_vabsorb = any(r.get("form") == "morpekohangry" and r.get("effective_type") == "DARK" and r.get("target_known_ability") == "voltabsorb" for r in table)
                        if fb_vabsorb:
                            m["full_belly_known_volt_absorb_opportunities"] += 1
                        if hg_vabsorb:
                            m["hangry_known_volt_absorb_opportunities"] += 1

                        fb_blocked = any(r.get("form") == "morpeko" and r.get("effective_type") == "ELECTRIC" and r.get("target_known_ability") == "voltabsorb" and r.get("ability_blocked") for r in table)
                        fb_sel = any(r.get("form") == "morpeko" and r.get("effective_type") == "ELECTRIC" and r.get("target_known_ability") == "voltabsorb" and r.get("selected") for r in table)
                        hg_sel_legal = any(r.get("form") == "morpekohangry" and r.get("effective_type") == "DARK" and r.get("target_known_ability") == "voltabsorb" and r.get("selected") and not r.get("ability_blocked") for r in table)
                        if fb_blocked:
                            m["full_belly_known_volt_absorb_blocked"] += 1
                        if fb_sel:
                            m["full_belly_known_volt_absorb_selected"] += 1
                        if hg_sel_legal:
                            m["hangry_known_volt_absorb_selected_legal"] += 1

                        if any(r.get("form") == "morpeko" and r.get("effective_type") == "ELECTRIC" and r.get("selected") for r in table):
                            m["full_belly_aurawheel_selected"] += 1
                        if any(r.get("form") == "morpekohangry" and r.get("effective_type") == "DARK" and r.get("selected") for r in table):
                            m["hangry_aurawheel_selected"] += 1
            except Exception:
                continue
    m["accounting_invariant_pass"] = (m["blocked_total"] == m["selected_total"] + m["avoided_total"])
    return m


def _make_result(name, n_battles, player, opponent, status, log_path, benchmark_arm=""):
    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles if hasattr(opponent, 'n_won_battles') else 0
    ties = finished - wins - losses
    wr = (wins / finished * 100) if finished > 0 else 0.0
    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0.0
    m = _count_dynamic_metrics(log_path)
    m["timeout_count"] = getattr(player, "_timeout_count", 0)
    return {"name": name, "status": status, "planned": n_battles, "finished": finished,
            "wins": wins, "losses": losses, "ties": ties,
            "win_rate": f"{wr:.2f}", "avg_turns": f"{avg_turns:.2f}",
            "benchmark_arm": benchmark_arm, **m}


# ========================== Testable validators ==========================

def validate_jsonl(jsonl_path, expected_count, expected_arm):
    errors = []
    if not os.path.exists(jsonl_path):
        return [f"missing file: {jsonl_path}"]
    records = []
    seen_tags = set()
    with open(jsonl_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"{jsonl_path}:{line_num}: malformed JSON: {e}")
                continue
            records.append(rec)
            bt = rec.get("battle_tag", "")
            if not bt:
                errors.append(f"{jsonl_path}:{line_num}: missing battle_tag")
                continue
            if bt in seen_tags:
                errors.append(f"{jsonl_path}:{line_num}: duplicate battle_tag '{bt}'")
            seen_tags.add(bt)
            won = rec.get("won")
            if not isinstance(won, bool):
                errors.append(f"{jsonl_path}:{line_num}: won is not bool (got {type(won).__name__})")
            arm = rec.get("benchmark_arm")
            if arm is None:
                errors.append(f"{jsonl_path}:{line_num}: '{bt}' missing benchmark_arm")
            elif arm != expected_arm:
                errors.append(f"{jsonl_path}:{line_num}: '{bt}' benchmark_arm={arm} expected={expected_arm}")
    if len(records) != expected_count:
        errors.append(f"{jsonl_path}: expected {expected_count} records, got {len(records)}")
    blocked = 0; sel = 0; avd = 0
    for rec in records:
        for td in rec.get("audit_turns", []):
            for sk in ("slot_0", "slot_1"):
                slot = td.get(sk, {})
                if slot.get("dynamic_type_absorb_candidate_blocked"):
                    blocked += 1
                if slot.get("dynamic_type_absorb_selected"):
                    sel += 1
                if slot.get("dynamic_type_absorb_avoided"):
                    avd += 1
                if slot.get("dynamic_type_absorb_selected") and slot.get("dynamic_type_absorb_avoided"):
                    bt = rec.get("battle_tag", "?")
                    errors.append(f"{bt} slot={sk} has both selected and avoided true")
    if blocked != sel + avd:
        errors.append(f"accounting failed: blocked={blocked} != selected={sel} + avoided={avd}")
    return errors


def _safe_int(val, label):
    try:
        return int(val)
    except (ValueError, TypeError):
        raise ValueError(f"non-integer {label}: {val!r}")


def validate_csv(csv_path, expected_arms):
    errors = []
    if not os.path.exists(csv_path):
        return [f"missing file: {csv_path}"]
    seen_arms = set()
    try:
        with open(csv_path, "r", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return [f"{csv_path}: missing or malformed header"]
            for row in reader:
                arm = (row.get("benchmark_arm") or "").strip()
                if not arm:
                    errors.append("row with empty benchmark_arm")
                    continue
                if arm in seen_arms:
                    errors.append(f"duplicate arm '{arm}' in CSV")
                seen_arms.add(arm)
                if row.get("status") != "ok":
                    errors.append(f"arm {arm}: status={row.get('status')!r} (expected ok)")

                try:
                    planned = _safe_int(row.get("planned"), f"arm {arm} planned")
                except ValueError as e:
                    errors.append(str(e))
                    planned = None
                try:
                    finished = _safe_int(row.get("finished"), f"arm {arm} finished")
                except ValueError as e:
                    errors.append(str(e))
                    finished = None

                exp = expected_arms.get(arm)
                if exp is None:
                    errors.append(f"arm '{arm}' not in expected arms {list(expected_arms.keys())}")
                elif planned is not None and planned != exp:
                    errors.append(f"arm {arm}: planned={planned} expected={exp}")
                elif finished is not None and finished != exp:
                    errors.append(f"arm {arm}: finished={finished} expected={exp}")

                inv = row.get("accounting_invariant_pass", "")
                if inv != "True":
                    errors.append(f"arm {arm}: accounting_invariant_pass={inv!r} (expected True)")
                mex = row.get("accounting_mutual_exclusion_pass", "")
                if mex != "True":
                    errors.append(f"arm {arm}: accounting_mutual_exclusion_pass={mex!r} (expected True)")
    except Exception as e:
        errors.append(f"{csv_path}: error reading CSV: {e}")
        return errors
    for exp_arm in expected_arms:
        if exp_arm not in seen_arms:
            errors.append(f"missing expected arm '{exp_arm}' in CSV")
    return errors


# ========================== main ==========================

async def main():
    p = argparse.ArgumentParser(description="Dynamic Aura Wheel Smoke Benchmark")
    p.add_argument("--artifact-tag", type=str, required=True)
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()
    tag = args.artifact_tag
    csv_path = f"logs/dynamic_move_type_{tag}.csv"
    arm_paths = [f"logs/dynamic_move_type_{tag}_{a}.jsonl" for a in ("A","B")]

    if not args.overwrite:
        existing = [p for p in ([csv_path] + arm_paths) if os.path.exists(p)]
        if existing:
            print("Artifacts already exist:")
            for p in existing:
                print(f"  {p}")
            sys.exit(2)

    config = DoublesDamageAwareConfig()
    arms = [("A", "DynamicBot vs Basic", "basic", 100), ("B", "DynamicBot vs SafeRandom", "safe_random", 50)]
    results = []
    for arm_id, name, opp_class, n_battles in arms:
        log_path = f"logs/dynamic_move_type_{tag}_{arm_id}.jsonl"
        result = await run_matchup_with_watchdog(name, config, opp_class, n_battles, log_path, arm_timeout=1800, benchmark_arm=arm_id)
        results.append(result)
        print(f"  {arm_id}: {result.get('win_rate','N/A')}% WR, {result.get('wins',0)}W/{result.get('losses',0)}L, finished={result.get('finished',0)}")

    fieldnames = [
        "name","status","planned","finished","wins","losses","ties","win_rate","avg_turns","benchmark_arm",
        "dynamic_candidate_opportunity_turns",
        "full_belly_candidate_opportunities","hangry_candidate_opportunities",
        "full_belly_aurawheel_selected","hangry_aurawheel_selected",
        "full_belly_known_volt_absorb_opportunities","full_belly_known_volt_absorb_blocked","full_belly_known_volt_absorb_selected",
        "hangry_known_volt_absorb_opportunities","hangry_known_volt_absorb_selected_legal",
        "blocked_total","selected_total","avoided_total",
        "spread_count","focus_fire_count","timeout_count",
        "accounting_invariant_pass","accounting_mutual_exclusion_pass",
    ]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, False) for k in fieldnames})
    print(f"\nSaved: {csv_path}")

    print("\n--- JSONL Validation ---")
    jerrs = []
    for arm_id, _, _, n_battles in arms:
        e = validate_jsonl(f"logs/dynamic_move_type_{tag}_{arm_id}.jsonl", n_battles, arm_id)
        jerrs.extend(e)
        print(f"  [{arm_id}] {'PASS' if not e else 'FAIL: ' + '; '.join(e)}")
    print("\n--- CSV Validation ---")
    cerrs = validate_csv(csv_path, {a: n for a, _, _, n in arms})
    print(f"  {'PASS' if not cerrs else 'FAIL: ' + '; '.join(cerrs)}")

    all_errs = jerrs + cerrs
    if all_errs:
        print(f"\nVALIDATION FAILED ({len(all_errs)} errors)")
        sys.exit(3)
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
