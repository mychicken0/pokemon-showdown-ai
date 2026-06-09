#!/usr/bin/env python3
"""Phase 6.4.1a Benchmark: Switch Safety Correctness and Qualification.

Runs four matchups:
  1. Off vs DoublesBasicAwarePlayer: 500 battles
  2. On vs DoublesBasicAwarePlayer: 500 battles
  3. On vs Off: 500 battles
  4. On vs DoublesSafeRandomPlayer: 100 battles

Saves CSV and JSONL audit logs with phase641a artifact filenames.
"""
import asyncio
import csv
import json
import os
import random
import sys
from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer
from bot_doubles_safe_random import DoublesSafeRandomPlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

MAX_CONCURRENT = 15
CSV_PATH = "logs/doubles_switch_candidate_safety_phase641a_benchmark.csv"


def count_audit_metrics(log_path):
    """Count all required metrics from a JSONL audit log."""
    metrics = {
        "protect_cnt": 0,
        "spread_cnt": 0,
        "focus_fire_cnt": 0,
        "ground_into_levitate": 0,
        "direct_absorb_immune_move_selected": 0,
        "direct_absorb_hard_block_avoided": 0,
        "direct_absorb_only_legal_action": 0,
        "redirected_absorb_selected": 0,
        "productive_partial_absorb_spread": 0,
        "zero_eff_cnt": 0,
        "all_imm_cnt": 0,
        # Phase 6.4 metrics (corrected names)
        "forced_switch_cnt": 0,
        "final_unsafe_selected": 0,
        "legal_safer_joint_available": 0,
        "unsafe_switch_avoided": 0,
        "joint_selection_changed": 0,
        "selected_double_threat": 0,
        "eligible_neg_boost_decisions": 0,
        "offensive_drop_count": 0,
        "defensive_drop_count": 0,
        "speed_drop_count": 0,
        "severe_neg_boost_switch": 0,
        "severe_neg_boost_non_switch": 0,
        "voluntary_switch_cnt": 0,
    }

    if not os.path.exists(log_path):
        return metrics

    with open(log_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                battle = json.loads(line)
                for turn in battle.get("audit_turns", []):
                    if turn.get("focus_fire_triggered"):
                        metrics["focus_fire_cnt"] += 1

                    for slot_key in ("slot_0", "slot_1"):
                        slot = turn.get(slot_key, {})
                        if not slot:
                            continue

                        action_types = slot.get("action_types", {})

                        if action_types.get("protect"):
                            metrics["protect_cnt"] += 1
                        if action_types.get("spread"):
                            metrics["spread_cnt"] += 1
                        if slot.get("zero_effectiveness_move_selected"):
                            metrics["zero_eff_cnt"] += 1
                        if slot.get("all_targets_immune_spread_selected"):
                            metrics["all_imm_cnt"] += 1
                        if slot.get("ground_into_levitate_selected"):
                            metrics["ground_into_levitate"] += 1
                        if slot.get("direct_absorb_immune_move_selected"):
                            metrics["direct_absorb_immune_move_selected"] += 1
                        if slot.get("direct_absorb_hard_block_avoided"):
                            metrics["direct_absorb_hard_block_avoided"] += 1
                        if slot.get("direct_absorb_only_legal_action"):
                            metrics["direct_absorb_only_legal_action"] += 1

                        is_absorb_selected = bool(slot.get("absorb_immune_move_selected"))
                        is_redirected = bool(slot.get("absorb_via_redirection"))
                        is_prod_spread = bool(slot.get("productive_partial_absorb_spread"))

                        if is_absorb_selected and is_redirected:
                            metrics["redirected_absorb_selected"] += 1
                        if is_absorb_selected and is_prod_spread:
                            metrics["productive_partial_absorb_spread"] += 1

                        # Phase 6.4 metrics (corrected names)
                        is_forced = bool(slot.get("forced_switch"))
                        is_switch = bool(action_types.get("switch"))
                        if is_forced:
                            metrics["forced_switch_cnt"] += 1
                        if is_switch and not is_forced:
                            metrics["voluntary_switch_cnt"] += 1
                        if slot.get("final_unsafe_switch_selected"):
                            metrics["final_unsafe_selected"] += 1
                        if slot.get("legal_safer_joint_switch_available"):
                            metrics["legal_safer_joint_available"] += 1
                        if slot.get("unsafe_switch_avoided_by_type_safety"):
                            metrics["unsafe_switch_avoided"] += 1
                        if slot.get("joint_switch_selection_changed_by_type_safety"):
                            metrics["joint_selection_changed"] += 1
                        if slot.get("final_double_threat_switch_selected"):
                            metrics["selected_double_threat"] += 1
                        if slot.get("negative_boost_decision_eligible"):
                            metrics["eligible_neg_boost_decisions"] += 1
                        if slot.get("negative_boost_relevant_offensive_drop"):
                            metrics["offensive_drop_count"] += 1
                        if slot.get("negative_boost_defensive_drop"):
                            metrics["defensive_drop_count"] += 1
                        if slot.get("negative_boost_speed_drop"):
                            metrics["speed_drop_count"] += 1
                        if slot.get("neg_boost_severe_negative_boost"):
                            if is_switch:
                                metrics["severe_neg_boost_switch"] += 1
                            else:
                                metrics["severe_neg_boost_non_switch"] += 1
            except Exception:
                continue

    return metrics


async def run_matchup(name, config, opp_class, opp_config, n_battles, log_path, label):
    """Run a single matchup and return result dict."""
    suffix = random.randint(10000, 99999)
    bot_name = f"Phase641a_{label}_{suffix}"[:18]
    opp_name = f"Opp_{label}_{suffix}"[:18]

    audit_logger = DoublesDecisionAuditLogger(
        filepath=log_path,
        reset=True,
        detail_level="top5",
    )

    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        verbose=False,
        config=config,
        audit_logger=audit_logger,
        max_concurrent_battles=MAX_CONCURRENT,
    )

    if opp_class == DoublesDamageAwarePlayer:
        opponent = DoublesDamageAwarePlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            verbose=False,
            config=opp_config,
            max_concurrent_battles=MAX_CONCURRENT,
        )
    elif opp_class == DoublesBasicAwarePlayer:
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

    print(f"\n---> {name} ({n_battles} battles)...")
    await player.battle_against(opponent, n_battles=n_battles)

    planned = n_battles
    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles
    unfinished = planned - finished
    win_rate = (wins / finished) * 100 if finished > 0 else 0.0

    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0.0

    crashes = exceptions = timeouts = 0
    for b in player.battles.values():
        if b.finished:
            if getattr(b, "crashed", False):
                crashes += 1
            if getattr(b, "exception", False):
                exceptions += 1
            if getattr(b, "timed_out", False):
                timeouts += 1

    ties_or_unknown = finished - wins - losses

    m = count_audit_metrics(log_path)

    print(f"  Finished: {finished}/{planned} | Wins: {wins} | Losses: {losses} | Ties: {ties_or_unknown}")
    print(f"  Win Rate: {win_rate:.2f}% | Avg Turns: {avg_turns:.2f}")
    print(f"  Crashes: {crashes} | Exceptions: {exceptions} | Timeouts: {timeouts}")
    print(f"  Protect: {m['protect_cnt']} | Spread: {m['spread_cnt']} | Focus-fire: {m['focus_fire_cnt']}")
    print(f"  Forced Switch: {m['forced_switch_cnt']} | Voluntary Switch: {m['voluntary_switch_cnt']}")
    print(f"  Final Unsafe Selected: {m['final_unsafe_selected']}")
    print(f"  Legal Safer Joint Available: {m['legal_safer_joint_available']}")
    print(f"  Unsafe Avoided: {m['unsafe_switch_avoided']}")
    print(f"  Joint Selection Changed: {m['joint_selection_changed']}")
    print(f"  Selected Double-Threat: {m['selected_double_threat']}")
    print(f"  Eligible Neg-Boost Decisions: {m['eligible_neg_boost_decisions']}")
    print(f"    Offensive Drops: {m['offensive_drop_count']} | Defensive: {m['defensive_drop_count']} | Speed: {m['speed_drop_count']}")
    print(f"  Severe Neg-Boost Switch: {m['severe_neg_boost_switch']} | Non-Switch: {m['severe_neg_boost_non_switch']}")

    return {
        "matchup": name,
        "planned_battles": planned,
        "finished_battles": finished,
        "unfinished_battles": unfinished,
        "wins": wins,
        "losses": losses,
        "ties_or_unknown": ties_or_unknown,
        "win_rate": f"{win_rate:.2f}",
        "avg_turns": f"{avg_turns:.2f}",
        "crashes": crashes,
        "exceptions": exceptions,
        "timeouts": timeouts,
        **m,
    }


async def main():
    os.makedirs("logs", exist_ok=True)

    config_off = DoublesDamageAwareConfig(
        enable_switch_candidate_type_safety=False,
    )

    config_on = DoublesDamageAwareConfig(
        enable_switch_candidate_type_safety=True,
    )

    # Run 1: Off vs Basic: 500
    row1 = await run_matchup(
        name="Off vs Basic",
        config=config_off,
        opp_class=DoublesBasicAwarePlayer,
        opp_config=None,
        n_battles=500,
        log_path="logs/doubles_switch_candidate_safety_phase641a_vs_basic_off.jsonl",
        label="Off",
    )

    # Run 2: On vs Basic: 500
    row2 = await run_matchup(
        name="On vs Basic",
        config=config_on,
        opp_class=DoublesBasicAwarePlayer,
        opp_config=None,
        n_battles=500,
        log_path="logs/doubles_switch_candidate_safety_phase641a_vs_basic_on.jsonl",
        label="On",
    )

    # Run 3: On vs Off: 500
    row3 = await run_matchup(
        name="On vs Off",
        config=config_on,
        opp_class=DoublesDamageAwarePlayer,
        opp_config=config_off,
        n_battles=500,
        log_path="logs/doubles_switch_candidate_safety_phase641a_on_vs_off.jsonl",
        label="OnVsOff",
    )

    # Run 4: On vs SafeRandom: 100
    row4 = await run_matchup(
        name="On vs SafeRandom",
        config=config_on,
        opp_class=DoublesSafeRandomPlayer,
        opp_config=None,
        n_battles=100,
        log_path="logs/doubles_switch_candidate_safety_phase641a_vs_saferandom.jsonl",
        label="OnSR",
    )

    # --- Stability Validation ---
    print("\n=== Stability Validation ===")
    all_stable = True
    for row in [row1, row2, row3, row4]:
        ok = True
        if row["finished_battles"] != row["planned_battles"]:
            ok = False
        if row["wins"] + row["losses"] + row["ties_or_unknown"] != row["finished_battles"]:
            ok = False
        if row["unfinished_battles"] != 0:
            ok = False
        if row["timeouts"] != 0:
            ok = False
        if row["crashes"] != 0:
            ok = False
        if row["exceptions"] != 0:
            ok = False
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_stable = False
        print(f"  {row['matchup']}: {status}")

    if not all_stable:
        print("\nSTABILITY FAILURE — review before adoption.")
        return

    print("All stability checks PASS.")

    # --- Write CSV ---
    fieldnames = [
        "matchup", "planned_battles", "finished_battles", "unfinished_battles",
        "wins", "losses", "ties_or_unknown", "win_rate", "avg_turns",
        "crashes", "exceptions", "timeouts",
        "protect_cnt", "spread_cnt", "focus_fire_cnt",
        "ground_into_levitate",
        "direct_absorb_immune_move_selected",
        "direct_absorb_hard_block_avoided",
        "direct_absorb_only_legal_action",
        "redirected_absorb_selected",
        "productive_partial_absorb_spread",
        "zero_eff_cnt", "all_imm_cnt",
        "forced_switch_cnt", "voluntary_switch_cnt",
        "final_unsafe_selected", "legal_safer_joint_available",
        "unsafe_switch_avoided", "joint_selection_changed",
        "selected_double_threat",
        "eligible_neg_boost_decisions",
        "offensive_drop_count", "defensive_drop_count", "speed_drop_count",
        "severe_neg_boost_switch", "severe_neg_boost_non_switch",
    ]

    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in [row1, row2, row3, row4]:
            writer.writerow(row)

    print(f"\nCSV written to {CSV_PATH}")

    # --- Print Summary ---
    print("\n=== Summary ===")
    off_basic_wr = float(row1["win_rate"])
    on_basic_wr = float(row2["win_rate"])
    on_off_wr = float(row3["win_rate"])
    on_sr_wr = float(row4["win_rate"])

    print(f"  Off vs Basic:    {row1['wins']}W {row1['losses']}L  ({off_basic_wr:.2f}%)")
    print(f"  On vs Basic:     {row2['wins']}W {row2['losses']}L  ({on_basic_wr:.2f}%)")
    print(f"  On vs Off:       {row3['wins']}W {row3['losses']}L  ({on_off_wr:.2f}%)")
    print(f"  On vs SafeRandom: {row4['wins']}W {row4['losses']}L  ({on_sr_wr:.2f}%)")

    delta_basic = on_basic_wr - off_basic_wr
    print(f"\n  On vs Basic delta: {delta_basic:+.2f} pp")
    print(f"  On vs Off: {on_off_wr:.2f}%")
    print(f"  On vs SafeRandom: {on_sr_wr:.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
