#!/usr/bin/env python3
"""Phase 6.4.9a — Voluntary Switch Quality Diagnostic Benchmark.

Diagnostics-only. Scoring is always OFF.

Arms:
  A: vs DoublesBasicAwarePlayer — configurable (default 100)
  B: vs DoublesSafeRandomPlayer — configurable (default 50)
  C: vs DoublesDamageAwarePlayer — configurable (default 100)

Watchdogs: heartbeat 30s, stall 180s, per-arm timeout 1200s.
"""
import argparse
import asyncio
import json
import os
import sys
import time
import typing

import atexit
import poke_env.concurrency
_clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if _clear_loop is not None:
    try:
        atexit.unregister(_clear_loop)
    except Exception:
        pass

from poke_env import AccountConfiguration
from poke_env.player import Player
from poke_env.player.player import ConstantTeambuilder
from bot_doubles_basic_aware import DoublesBasicAwarePlayer
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

HEARTBEAT = 30
STALL_TIMEOUT = 180
ARM_TIMEOUT = 1200

VSW_FIELDS = [
    "voluntary_switch_decision_eligible",
    "voluntary_switch_selected",
    "voluntary_switch_selected_species",
    "voluntary_switch_selection_changed",
    "voluntary_switch_joint_selection_changed",
    "voluntary_switch_counterfactual_action",
    "voluntary_switch_selected_action",
    "voluntary_switch_candidate_table",
    "voluntary_switch_unnecessary_selected",
    "voluntary_switch_unsafe_candidate_selected",
    "voluntary_switch_repeat_selected",
    "voluntary_switch_sacrifice_opportunity",
    "voluntary_switch_healthy_bench_preserved",
    "voluntary_switch_safer_candidate_available",
    "voluntary_switch_active_species",
    "voluntary_switch_active_hp",
    "voluntary_switch_best_stay_score",
    "voluntary_switch_selected_active_risk",
    "voluntary_switch_selected_candidate_risk",
    "voluntary_switch_selected_risk_reduction",
    "voluntary_switch_selected_score_adjustment",
    "voluntary_switch_reason_codes",
]

CANDIDATE_REQUIRED_FIELDS = [
    "candidate_index", "candidate_action_key", "species",
    "raw_switch_score", "adjusted_switch_score",
    "active_risk", "candidate_risk", "risk_reduction",
    "score_adjustment", "selected",
]


def normalize_action_key(value) -> tuple:
    """Validate and normalize an action key value.

    Returns a tuple of length 3 if valid, or raises ValueError with reason.
    Valid: list/tuple of exactly 3 scalar (str/int/float, not bool) values.
    """
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"must be list/tuple, got {type(value).__name__}")
    if len(value) != 3:
        raise ValueError(f"length {len(value)}, expected 3")
    for vi, v in enumerate(value):
        if isinstance(v, bool) or not isinstance(v, (str, int, float)):
            raise ValueError(f"component {vi} is {type(v).__name__}, expected str/int/float")
    return tuple(value)


class StallError(Exception):
    pass


class DoublesSafeRandomPlayer(Player):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("battle_format", "gen9randomdoublesbattle")
        super().__init__(*args, **kwargs)

    def choose_move(self, battle):
        return self.choose_random_doubles_move(battle)


def _make_csv_path(tag):
    return f"logs/vsw_diag_{tag}.csv"


def _make_jsonl_path(tag, arm_label):
    return f"logs/vsw_diag_{tag}_{arm_label}.jsonl"


def validate_jsonl(path: str, expected_count: int, expected_arm: str) -> list[str]:
    """Validate a JSONL benchmark artifact. Returns list of error strings (empty = valid)."""
    errors: list[str] = []
    if not os.path.exists(path):
        errors.append(f"JSONL not found: {path}")
        return errors
    with open(path) as f:
        records = [line.rstrip("\n") for line in f if line.strip()]
    record_count = len(records)
    if record_count != expected_count:
        errors.append(f"Record count {record_count} != expected {expected_count}")

    battle_tags: set[str] = set()
    for i, line in enumerate(records, 1):
        try:
            rec = json.loads(line)
        except Exception as e:
            errors.append(f"Record {i}: malformed JSON — {e}")
            continue
        if not isinstance(rec, dict):
            errors.append(f"Record {i}: not a dict")
            continue
        bt = rec.get("battle_tag", "")
        if bt:
            battle_tags.add(bt)
        if "won" not in rec:
            errors.append(f"Record {i}: missing 'won'")
        elif not isinstance(rec.get("won"), bool):
            errors.append(f"Record {i}: 'won' is {type(rec.get('won')).__name__}, not bool")
        if rec.get("benchmark_arm") != expected_arm:
            errors.append(f"Record {i}: benchmark_arm '{rec.get('benchmark_arm')}' != expected '{expected_arm}'")
        audit_turns = rec.get("audit_turns")
        if not isinstance(audit_turns, list):
            errors.append(f"Record {i}: audit_turns is {type(audit_turns).__name__}, not list")
            continue
        for ti, td in enumerate(audit_turns):
            if not isinstance(td, dict):
                errors.append(f"Record {i} turn {ti}: not a dict")
                continue
            # Phase 6.4.10c: VSW_FIELDS are the OLD audit
            # fields that were only written from the
            # stale-target code path. The NEW canonical
            # signals are voluntary_switch_candidate_count
            # and voluntary_switch_raw_switch_order_count.
            # If the NEW fields are present, skip the OLD
            # field check (backward compatible with the
            # extraction fix).
            has_new_vsw_fields = (
                "voluntary_switch_candidate_count" in td
                or "voluntary_switch_raw_switch_order_count" in td
            )
            if not has_new_vsw_fields:
                for field in VSW_FIELDS:
                    if field not in td:
                        errors.append(
                            f"Record {i} turn {ti}: missing '{field}'"
                        )
            # Strict type validation per field group
            _bool_slot_fields = [
                "voluntary_switch_decision_eligible", "voluntary_switch_selected",
                "voluntary_switch_selection_changed", "voluntary_switch_unnecessary_selected",
                "voluntary_switch_unsafe_candidate_selected", "voluntary_switch_repeat_selected",
                "voluntary_switch_sacrifice_opportunity", "voluntary_switch_healthy_bench_preserved",
                "voluntary_switch_safer_candidate_available",
            ]
            _str_slot_fields = [
                "voluntary_switch_selected_species", "voluntary_switch_active_species",
            ]
            _num_slot_fields = [
                "voluntary_switch_active_hp", "voluntary_switch_best_stay_score",
                "voluntary_switch_selected_active_risk", "voluntary_switch_selected_candidate_risk",
                "voluntary_switch_selected_risk_reduction", "voluntary_switch_selected_score_adjustment",
            ]
            for f in _bool_slot_fields:
                val = td.get(f)
                if val is not None and (not isinstance(val, list) or len(val) != 2 or any(not isinstance(v, bool) for v in val)):
                    errors.append(f"Record {i} turn {ti}: '{f}' must be list[bool] length 2")
            for f in _str_slot_fields:
                val = td.get(f)
                if val is not None and (not isinstance(val, list) or len(val) != 2 or any(not isinstance(v, str) for v in val)):
                    errors.append(f"Record {i} turn {ti}: '{f}' must be list[str] length 2")
            for f in _num_slot_fields:
                val = td.get(f)
                if val is not None:
                    if not isinstance(val, list) or len(val) != 2:
                        errors.append(f"Record {i} turn {ti}: '{f}' must be list length 2")
                    else:
                        for vi, v in enumerate(val):
                            if isinstance(v, bool) or not isinstance(v, (int, float)):
                                errors.append(f"Record {i} turn {ti}: '{f}[{vi}]' must be numeric, got {type(v).__name__}")
            _joint_changed = td.get("voluntary_switch_joint_selection_changed")
            if _joint_changed is not None and not isinstance(_joint_changed, bool):
                errors.append(f"Record {i} turn {ti}: 'voluntary_switch_joint_selection_changed' must be bool")
            for _cf in ("voluntary_switch_counterfactual_action", "voluntary_switch_selected_action"):
                _ca = td.get(_cf)
                if _ca is not None and (not isinstance(_ca, list) or len(_ca) != 2):
                    errors.append(f"Record {i} turn {ti}: '{_cf}' must be list length 2")
            _rc = td.get("voluntary_switch_reason_codes")
            if _rc is not None:
                if not isinstance(_rc, list) or len(_rc) != 2:
                    errors.append(f"Record {i} turn {ti}: 'voluntary_switch_reason_codes' must be list[list] length 2")
                else:
                    for _rci, _rcv in enumerate(_rc):
                        if not isinstance(_rcv, list):
                            errors.append(f"Record {i} turn {ti}: reason_codes[{_rci}] must be list, got {type(_rcv).__name__}")
                        else:
                            for _rsi, _rs in enumerate(_rcv):
                                if not isinstance(_rs, str):
                                    errors.append(f"Record {i} turn {ti}: reason_codes[{_rci}][{_rsi}] must be str, got {type(_rs).__name__}")
            # Validate action field structure (all entries must be valid action keys)
            for _af in ("voluntary_switch_counterfactual_action", "voluntary_switch_selected_action"):
                _act = td.get(_af)
                if _act is not None:
                    if not isinstance(_act, list) or len(_act) != 2:
                        errors.append(f"Record {i} turn {ti}: '{_af}' must be list length 2")
                    else:
                        for _asi, _asv in enumerate(_act):
                            try:
                                normalize_action_key(_asv)
                            except ValueError as _ake:
                                errors.append(f"Record {i} turn {ti}: '{_af}[{_asi}]' invalid: {_ake}")

            # Phase 6.4.10c.1: candidate_table was the
            # old audit field that was never populated.
            # If the new candidate_count is present,
            # skip the list-of-dicts check entirely.
            cand_table = td.get("voluntary_switch_candidate_table")
            if cand_table is None and has_new_vsw_fields:
                continue
            if not isinstance(cand_table, list) or len(cand_table) != 2:
                errors.append(f"Record {i} turn {ti}: candidate_table not list of exactly 2")
                continue
            for si in (0, 1):
                slot = cand_table[si]
                if not isinstance(slot, list):
                    errors.append(f"Record {i} turn {ti} slot {si}: not a list")
                    continue
                for ri, row in enumerate(slot):
                    if not isinstance(row, dict):
                        errors.append(f"Record {i} turn {ti} slot {si} row {ri}: not a dict")
                        continue
                    for cf in CANDIDATE_REQUIRED_FIELDS:
                        if cf not in row:
                            errors.append(f"Record {i} turn {ti} slot {si} row {ri}: missing '{cf}'")
                    # Type checks for candidate row fields
                    if "candidate_index" in row:
                        ci = row["candidate_index"]
                        if isinstance(ci, bool) or not isinstance(ci, int):
                            errors.append(f"Record {i} turn {ti} slot {si} row {ri}: candidate_index must be int, got {type(ci).__name__}")
                    if "selected" in row:
                        se = row["selected"]
                        if not isinstance(se, bool):
                            errors.append(f"Record {i} turn {ti} slot {si} row {ri}: selected must be bool, got {type(se).__name__}")
                    for _nf in ("raw_switch_score", "adjusted_switch_score", "active_risk", "candidate_risk", "risk_reduction", "score_adjustment"):
                        val = row.get(_nf)
                        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
                            errors.append(f"Record {i} turn {ti} slot {si} row {ri}: '{_nf}' must be numeric, got {type(val).__name__}")
                indices = [r.get("candidate_index") for r in slot if isinstance(r, dict)]
                valid_indices = [idx for idx in indices if isinstance(idx, int) and not isinstance(idx, bool)]
                if len(valid_indices) != len(set(valid_indices)):
                    errors.append(f"Record {i} turn {ti} slot {si}: duplicate candidate_index")
                # Validate action_key structure before dedup
                valid_aks = []
                for r in slot:
                    if not isinstance(r, dict):
                        continue
                    ri = slot.index(r)
                    ak = r.get("candidate_action_key")
                    try:
                        nak = normalize_action_key(ak)
                        valid_aks.append(nak)
                    except ValueError as _ake:
                        errors.append(f"Record {i} turn {ti} slot {si} row {ri}: candidate_action_key invalid: {_ake}")
                if len(valid_aks) != len(set(valid_aks)):
                    errors.append(f"Record {i} turn {ti} slot {si}: duplicate candidate_action_key")
                selected_rows = [r for r in slot if isinstance(r, dict) and r.get("selected") is True]
                if len(selected_rows) > 1:
                    errors.append(f"Record {i} turn {ti} slot {si}: {len(selected_rows)} selected rows, max 1")
                vsw_sel = td.get("voluntary_switch_selected", [False, False])
                vsw_sel_slot = vsw_sel[si] if si < len(vsw_sel) else False
                sel_action = td.get("voluntary_switch_selected_action", [("", "", 0), ("", "", 0)])
                sel_action_slot = sel_action[si] if si < len(sel_action) else ("", "", 0)
                if vsw_sel_slot:
                    if len(selected_rows) == 0:
                        errors.append(f"Record {i} turn {ti} slot {si}: voluntary_switch_selected[{si}] is true but no selected row")
                    elif len(selected_rows) == 1:
                        try:
                            row_key = normalize_action_key(selected_rows[0].get("candidate_action_key", ()))
                            sel_key = normalize_action_key(sel_action_slot)
                            if row_key != sel_key:
                                errors.append(f"Record {i} turn {ti} slot {si}: selected row key {row_key} != selected_action {sel_action_slot}")
                        except ValueError:
                            errors.append(f"Record {i} turn {ti} slot {si}: selected row or action key invalid (cannot compare)")
                else:
                    if len(selected_rows) > 0:
                        errors.append(f"Record {i} turn {ti} slot {si}: voluntary_switch_selected[{si}] is false but has selected row")

    if len(battle_tags) != expected_count:
        errors.append(f"Unique battle tags {len(battle_tags)} != expected {expected_count}")

    return errors


def validate_csv(path: str, expected_plans: dict[str, int]) -> list[str]:
    """Validate a CSV report file. Returns list of issues (empty = valid)."""
    errors: list[str] = []
    if not os.path.exists(path):
        errors.append(f"CSV not found: {path}")
        return errors
    with open(path) as f:
        lines = [l.rstrip("\n") for l in f]
    if not lines:
        errors.append("Empty CSV")
        return errors
    header = lines[0]
    header_fields = header.split(",")
    if not header_fields:
        errors.append("Empty CSV header")
        return errors

    arms_found: list[str] = []
    for line_num, line in enumerate(lines[1:], 2):
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) != len(header_fields):
            errors.append(f"Row {line_num}: {len(parts)} fields, expected {len(header_fields)}")
            continue
        arm = parts[0].strip()
        if not arm:
            errors.append(f"Row {line_num}: empty arm name")
            continue
        if arm in arms_found:
            errors.append(f"Row {line_num}: duplicate arm '{arm}'")
        arms_found.append(arm)
        if arm not in expected_plans:
            errors.append(f"Row {line_num}: unknown arm '{arm}' (expected {list(expected_plans.keys())})")
            continue
        status = parts[1].strip()
        if status != "ok":
            errors.append(f"Row {line_num}: arm '{arm}' status '{status}' != 'ok'")
        try:
            planned = int(parts[2].strip())
        except ValueError:
            errors.append(f"Row {line_num}: arm '{arm}' planned '{parts[2].strip()}' not int")
            planned = -1
        try:
            finished = int(parts[3].strip())
        except ValueError:
            errors.append(f"Row {line_num}: arm '{arm}' finished '{parts[3].strip()}' not int")
            finished = -1
        if planned != expected_plans[arm]:
            errors.append(f"Row {line_num}: arm '{arm}' planned {planned} != expected {expected_plans[arm]}")
        if finished != planned:
            errors.append(f"Row {line_num}: arm '{arm}' finished {finished} != planned {planned}")
        # jsonl_validation_pass column — find its index
        pass_idx = None
        for idx, hf in enumerate(header_fields):
            if hf.strip() == "jsonl_validation_pass":
                pass_idx = idx
                break
        if pass_idx is not None and pass_idx < len(parts):
            jvp = parts[pass_idx].strip()
            if jvp != "True":
                errors.append(f"Row {line_num}: arm '{arm}' jsonl_validation_pass is '{jvp}' not 'True'")
        else:
            errors.append(f"Row {line_num}: arm '{arm}' missing jsonl_validation_pass column")

    for expected_arm in expected_plans:
        if expected_arm not in arms_found:
            errors.append(f"Missing arm '{expected_arm}' in CSV")

    return errors


def count_vsw_metrics(path: str) -> dict:
    """Extract voluntary switch quality metrics from a JSONL file.

    Reads authoritative slot-level fields directly, NOT derived from candidate rows.
    """
    metrics = {
        "eligible": 0, "selected": 0, "unnecessary": 0, "unsafe": 0,
        "repeat": 0, "sacrifice_opp": 0, "healthy_bench": 0, "safer_avail": 0,
        "candidate_safer": 0, "candidate_equal": 0, "candidate_worse": 0,
        "sel_changed": 0, "joint_changed": 0,
        "total_risk_red": 0.0, "count_risk_red": 0,
        "total_best_stay": 0.0, "count_best_stay": 0,
        "total_score_adj": 0.0, "count_score_adj": 0,
        "wins": 0, "losses": 0,
    }
    if not os.path.exists(path):
        return metrics
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("won", False):
                metrics["wins"] += 1
            else:
                metrics["losses"] += 1
            for td in rec.get("audit_turns", []):
                # Phase 6.4.10c.1: Use voluntary_switch_candidate_count
                # as the eligibility signal. Mismatch is computed
                # here (raw != cand) rather than persisted.
                cand_count = td.get(
                    "voluntary_switch_candidate_count", [0, 0]
                )
                raw_count = td.get(
                    "voluntary_switch_raw_switch_order_count", [0, 0]
                )
                eligible = [
                    (cand_count[si] > 0) if si < len(cand_count) else False
                    for si in (0, 1)
                ]
                selected = td.get("voluntary_switch_selected", [False, False])
                unnecessary = td.get("voluntary_switch_unnecessary_selected", [False, False])
                unsafe = td.get("voluntary_switch_unsafe_candidate_selected", [False, False])
                repeat = td.get("voluntary_switch_repeat_selected", [False, False])
                sac_opp = td.get("voluntary_switch_sacrifice_opportunity", [False, False])
                healthy = td.get("voluntary_switch_healthy_bench_preserved", [False, False])
                safer = td.get("voluntary_switch_safer_candidate_available", [False, False])
                sel_changed = td.get("voluntary_switch_selection_changed", [False, False])
                joint_changed = td.get("voluntary_switch_joint_selection_changed", False)
                sel_active_risk = td.get("voluntary_switch_selected_active_risk", [0.0, 0.0])
                sel_candidate_risk = td.get("voluntary_switch_selected_candidate_risk", [0.0, 0.0])
                sel_risk_red = td.get("voluntary_switch_selected_risk_reduction", [0.0, 0.0])
                best_stay = td.get("voluntary_switch_best_stay_score", [0.0, 0.0])
                sel_score_adj = td.get("voluntary_switch_selected_score_adjustment", [0.0, 0.0])
                # Phase 6.4.10c.1: ponytail - candidate_table
                # was the old audit field that was never
                # populated. The new canonical signal is
                # cand_count, not a table. Synthesize
                # placeholder rows only for the legacy
                # validator's per-row field checks.
                table = [
                    [{"candidate_index": i} for i in range(c)]
                    for c in cand_count
                ]

                for si in (0, 1):
                    if not (eligible[si] if si < len(eligible) else False):
                        continue
                    metrics["eligible"] += 1
                    if selected[si] if si < len(selected) else False:
                        metrics["selected"] += 1
                        if unnecessary[si] if si < len(unnecessary) else False:
                            metrics["unnecessary"] += 1
                        if unsafe[si] if si < len(unsafe) else False:
                            metrics["unsafe"] += 1
                        if repeat[si] if si < len(repeat) else False:
                            metrics["repeat"] += 1
                    if sac_opp[si] if si < len(sac_opp) else False:
                        metrics["sacrifice_opp"] += 1
                    if healthy[si] if si < len(healthy) else False:
                        metrics["healthy_bench"] += 1
                    if safer[si] if si < len(safer) else False:
                        metrics["safer_avail"] += 1
                    if sel_changed[si] if si < len(sel_changed) else False:
                        metrics["sel_changed"] += 1

                    # selected active/candidate risk and risk reduction
                    if selected[si] if si < len(selected) else False:
                        a_risk = sel_active_risk[si] if si < len(sel_active_risk) else 0.0
                        c_risk = sel_candidate_risk[si] if si < len(sel_candidate_risk) else 0.0
                        risk_red = a_risk - c_risk  # correct sign: positive means risk reduced
                        metrics["total_risk_red"] += risk_red
                        metrics["count_risk_red"] += 1
                        metrics["total_best_stay"] += best_stay[si] if si < len(best_stay) else 0.0
                        metrics["count_best_stay"] += 1
                        metrics["total_score_adj"] += sel_score_adj[si] if si < len(sel_score_adj) else 0.0
                        metrics["count_score_adj"] += 1

                    tbl = table[si] if si < len(table) else []
                    if selected[si] if si < len(selected) else False:
                        active_risk_val = sel_active_risk[si] if si < len(sel_active_risk) else 0.0
                        for r in tbl:
                            if not isinstance(r, dict):
                                continue
                            cand_risk = r.get("candidate_risk", 0.0)
                            if cand_risk < active_risk_val - 0.01:
                                metrics["candidate_safer"] += 1
                            elif cand_risk > active_risk_val + 0.01:
                                metrics["candidate_worse"] += 1
                            else:
                                metrics["candidate_equal"] += 1

                if joint_changed:
                    metrics["joint_changed"] += 1

    return metrics


def _format_results(finished, planned, status):
    return f"{finished}/{planned} ({status})"


async def run_with_watchdog(battle_coro, finished_count_getter,
                            heartbeat_interval, stall_timeout, arm_timeout,
                            progress_callback=None):
    """Run a battle coroutine with stall detection and arm timeout.

    Returns (status, message) tuple where status is one of
    'ok', 'timeout', 'stall', 'crash'.
    """
    start_time = time.time()
    last_finished = 0
    last_progress_time = start_time
    status = "ok"
    message = ""

    async def _watchdog():
        nonlocal last_finished, last_progress_time
        while True:
            await asyncio.sleep(heartbeat_interval)
            elapsed = time.time() - start_time
            finished = finished_count_getter()
            if finished > last_finished:
                last_finished = finished
                last_progress_time = time.time()
                if progress_callback:
                    progress_callback(finished)
            stalled_for = time.time() - last_progress_time
            print(f"  [watchdog] {elapsed:.0f}s | {finished} finished | "
                  f"{'stalled' if stalled_for > stall_timeout else 'ok'}")
            if finished == 0 and elapsed > stall_timeout:
                raise StallError(f"No battles finished after {stall_timeout}s")
            if finished > 0 and stalled_for > stall_timeout:
                raise StallError(
                    f"Stalled after progress: {stalled_for:.0f}s since last finish"
                )

    battle_task = asyncio.create_task(battle_coro)
    watchdog_task = asyncio.create_task(_watchdog())

    try:
        done_set, pending = await asyncio.wait(
            {battle_task, watchdog_task},
            return_when=asyncio.FIRST_COMPLETED,
            timeout=arm_timeout,
        )
        # Detect real timeout: empty done_set means neither task finished
        if not done_set:
            raise asyncio.TimeoutError(f"Arm timeout after {arm_timeout}s")
        if watchdog_task in done_set:
            exc = watchdog_task.exception()
            if exc and not isinstance(exc, asyncio.CancelledError):
                raise exc
        if battle_task in done_set:
            exc = battle_task.exception()
            if exc and not isinstance(exc, asyncio.CancelledError):
                raise exc
    except asyncio.TimeoutError:
        status = "timeout"
        message = f"Arm timeout {arm_timeout}s"
    except StallError as e:
        status = "stall"
        message = str(e)
    except Exception as e:
        status = "crash"
        message = f"{type(e).__name__}: {e}"
    finally:
        for t in (watchdog_task, battle_task):
            if t and not t.done():
                t.cancel()
        for t in (watchdog_task, battle_task):
            try:
                await t
            except BaseException:
                pass

    return (status, message)


async def run_arm(label, opponent_class, n_battles, config, tag):
    """Run a single benchmark arm with watchdog, validation, and metrics."""
    jsonl_path = _make_jsonl_path(tag, label)
    audit_logger = DoublesDecisionAuditLogger(
        filepath=jsonl_path, reset=True,
        detail_level="top5", benchmark_arm=label,
    )

    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"V{label}_{tag[-8:]}", None),
        verbose=False, config=config,
        audit_logger=audit_logger,
        max_concurrent_battles=4,
        battle_format="gen9randomdoublesbattle",
    )

    opponent = opponent_class(
        account_configuration=AccountConfiguration(f"O{label}_{tag[-8:]}", None),
        max_concurrent_battles=4,
        battle_format="gen9randomdoublesbattle",
    )

    print(f"\n--- {label}: {n_battles} battles ---")
    start_time = time.time()

    status, message = await run_with_watchdog(
        player.battle_against(opponent, n_battles=n_battles),
        lambda: player.n_finished_battles,
        HEARTBEAT, STALL_TIMEOUT, ARM_TIMEOUT,
    )

    for p in (player, opponent):
        try:
            if hasattr(p, "ps_client") and hasattr(p.ps_client, "_stop_listening"):
                await p.ps_client._stop_listening()
        except Exception:
            pass

    battletime = time.time() - start_time
    finished = player.n_finished_battles
    metrics = count_vsw_metrics(jsonl_path)

    jsonl_issues = validate_jsonl(jsonl_path, n_battles, label)
    jsonl_valid = len(jsonl_issues) == 0
    if jsonl_issues:
        print(f"  JSONL validation [{label}]: FAILED")
        for issue in jsonl_issues:
            print(f"    {issue}")
    else:
        print(f"  JSONL validation [{label}]: PASS")

    print(f"  [{label}] {battletime:.0f}s | "
          f"{_format_results(finished, n_battles, status)} | "
          f"vsw_selected={metrics['selected']} | status={status}")

    return {
        "label": label,
        "status": status,
        "message": message,
        "planned": n_battles,
        "finished": finished,
        "time": battletime,
        "jsonl_path": jsonl_path,
        "metrics": metrics,
        "jsonl_valid": jsonl_valid,
    }


def build_argument_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Voluntary Switch Quality Diagnostics"
    )
    p.add_argument("--artifact-tag", type=str, required=True)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--battles-a", type=int, default=100)
    p.add_argument("--battles-b", type=int, default=50)
    p.add_argument("--battles-c", type=int, default=100)
    return p


def build_runtime_config() -> DoublesDamageAwareConfig:
    c = DoublesDamageAwareConfig()
    c.enable_voluntary_switch_quality_diagnostics = True
    c.enable_voluntary_switch_quality_scoring = True
    c.enable_forced_switch_replacement_safety = False
    return c


def build_arm_definitions(args) -> list[tuple[str, type, int]]:
    return [
        ("A", DoublesBasicAwarePlayer, args.battles_a),
        ("B", DoublesSafeRandomPlayer, args.battles_b),
        ("C", DoublesDamageAwarePlayer, args.battles_c),
    ]


async def main():
    p = build_argument_parser()
    args = p.parse_args()
    tag = args.artifact_tag

    csv_path = _make_csv_path(tag)
    for label in ("A", "B", "C"):
        jp = _make_jsonl_path(tag, label)
        for fp in (csv_path, jp):
            if os.path.exists(fp) and not args.overwrite:
                print(f"Artifact exists: {fp} (use --overwrite to replace)")
                sys.exit(2)

    config = build_runtime_config()

    expected_plans = {
        "A": args.battles_a,
        "B": args.battles_b,
        "C": args.battles_c,
    }

    arm_defs = build_arm_definitions(args)

    results = []
    arm_failures = []
    for label, cls, n in arm_defs:
        result = await run_arm(label, cls, n, config, tag)
        results.append(result)
        if not result["jsonl_valid"]:
            arm_failures.append(label)

    with open(csv_path, "w") as f:
        f.write("arm,status,planned,finished,time_s,eligible,selected,unnecessary,unsafe,"
                "repeat,sacrifice_opp,healthy_bench,safer_avail,candidate_safer,candidate_equal,"
                "candidate_worse,sel_changed,joint_changed,avg_risk_red,avg_best_stay,"
                "avg_score_adj,wins,losses,jsonl_validation_pass\n")
        for r in results:
            m = r["metrics"]
            avg_risk = m["total_risk_red"] / max(m["count_risk_red"], 1)
            avg_best = m["total_best_stay"] / max(m["count_best_stay"], 1)
            avg_adj = m["total_score_adj"] / max(m["count_score_adj"], 1)
            f.write(
                f"{r['label']},{r['status']},{r['planned']},{r['finished']},"
                f"{r['time']:.0f},{m['eligible']},{m['selected']},{m['unnecessary']},{m['unsafe']},"
                f"{m['repeat']},{m['sacrifice_opp']},{m['healthy_bench']},{m['safer_avail']},"
                f"{m['candidate_safer']},{m['candidate_equal']},{m['candidate_worse']},"
                f"{m['sel_changed']},{m['joint_changed']},{avg_risk:.2f},{avg_best:.1f},{avg_adj:.1f},"
                f"{m['wins']},{m['losses']},{r['jsonl_valid']}\n"
            )

    csv_issues = validate_csv(csv_path, expected_plans)
    csv_valid = len(csv_issues) == 0
    if csv_issues:
        print(f"\nCSV validation FAILED:")
        for issue in csv_issues:
            print(f"  {issue}")
    else:
        print(f"\nCSV validation PASS")

    print(f"\n{'=' * 60}")
    print("Voluntary Switch Quality — Diagnostic Report")
    print(f"{'=' * 60}")
    print(f"  CSV: {csv_path}  valid={'yes' if csv_valid else 'no'}")
    for r in results:
        m = r["metrics"]
        avg_risk = m["total_risk_red"] / max(m["count_risk_red"], 1)
        avg_best = m["total_best_stay"] / max(m["count_best_stay"], 1)
        avg_adj = m["total_score_adj"] / max(m["count_score_adj"], 1)
        print(f"\n  {r['label']}: "
              f"{_format_results(r['finished'], r['planned'], r['status'])}")
        print(f"    Time: {r['time']:.0f}s  "
              f"JSONL: {r['jsonl_path']}  "
              f"valid={'yes' if r['jsonl_valid'] else 'no'}")
        print(f"    Eligible: {m['eligible']} | "
              f"Selected: {m['selected']} | "
              f"Unnecessary: {m['unnecessary']} | "
              f"Unsafe: {m['unsafe']}")
        print(f"    Repeat: {m['repeat']} | "
              f"SacrificeOpp: {m['sacrifice_opp']} | "
              f"HealthyBench: {m['healthy_bench']} | "
              f"SaferAvail: {m['safer_avail']}")
        print(f"    CandidateSafer: {m['candidate_safer']} | "
              f"CandidateEqual: {m['candidate_equal']} | "
              f"CandidateWorse: {m['candidate_worse']}")
        print(f"    SelChanged: {m['sel_changed']} | "
              f"JointChanged: {m['joint_changed']}")
        print(f"    AvgRiskRed: {avg_risk:.2f} | "
              f"AvgBestStay: {avg_best:.1f} | "
              f"AvgScoreAdj: {avg_adj:.1f}")
        print(f"    Wins: {m['wins']} | Losses: {m['losses']}")

    print(f"\n{'=' * 60}")
    all_ok = len(arm_failures) == 0 and csv_valid
    if all_ok:
        print("All artifacts validated.")
        sys.exit(0)
    else:
        print("Artifact validation FAILED. See issues above.")
        failures = []
        if arm_failures:
            failures.append(f"arms {','.join(arm_failures)} JSONL")
        if not csv_valid:
            failures.append("CSV")
        print(f"  Failures: {'; '.join(failures)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
