#!/usr/bin/env python3
import asyncio
import csv
import json
import math
import os
import random
import sys
from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

MAX_CONCURRENT = 15
CSV_PATH = "logs/doubles_direct_absorb_confirmation_benchmark.csv"


def count_audit_direct_absorb_metrics(log_path):
    metrics = {
        "protect_cnt": 0,
        "spread_cnt": 0,
        "focus_fire_cnt": 0,
        "zero_eff_cnt": 0,
        "all_imm_cnt": 0,
        "ground_into_levitate": 0,
        "direct_absorb_hard_block_avoided": 0,
        "direct_absorb_immune_move_selected": 0,
        "direct_absorb_only_legal_action": 0,
        "redirected_absorb_selected": 0,
        "productive_partial_absorb_spread": 0,
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

                        is_protect = bool(slot.get("action_types", {}).get("protect"))
                        is_spread = bool(slot.get("action_types", {}).get("spread"))
                        is_zero_eff = bool(slot.get("zero_effectiveness_move_selected"))
                        is_all_imm = bool(slot.get("all_targets_immune_spread_selected"))
                        is_ground_lev = bool(slot.get("ground_into_levitate_selected"))

                        is_da_avoided = bool(slot.get("direct_absorb_hard_block_avoided"))
                        is_da_selected = bool(slot.get("direct_absorb_immune_move_selected"))
                        is_da_only_legal = bool(slot.get("direct_absorb_only_legal_action"))

                        is_absorb_selected = bool(slot.get("absorb_immune_move_selected"))
                        is_redirected = bool(slot.get("absorb_via_redirection"))
                        is_prod_spread = bool(slot.get("productive_partial_absorb_spread"))

                        if is_protect:
                            metrics["protect_cnt"] += 1
                        if is_spread:
                            metrics["spread_cnt"] += 1
                        if is_zero_eff:
                            metrics["zero_eff_cnt"] += 1
                        if is_all_imm:
                            metrics["all_imm_cnt"] += 1
                        if is_ground_lev:
                            metrics["ground_into_levitate"] += 1

                        if is_da_avoided:
                            metrics["direct_absorb_hard_block_avoided"] += 1
                        if is_da_selected:
                            metrics["direct_absorb_immune_move_selected"] += 1
                            if is_da_only_legal:
                                metrics["direct_absorb_only_legal_action"] += 1
                        if is_absorb_selected and is_redirected:
                            metrics["redirected_absorb_selected"] += 1
                        if is_absorb_selected and is_prod_spread:
                            metrics["productive_partial_absorb_spread"] += 1
            except Exception:
                continue

    return metrics


async def run_block(run_number, variant, execution_order, config, n_battles, log_path):
    suffix = random.randint(1000, 9999)
    label = f"R{run_number}_{variant[:4]}_{suffix}"
    bot_name = f"Conf_{label}"[:18]
    opp_name = f"Opp_{label}"[:18]

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

    opponent = DoublesBasicAwarePlayer(
        account_configuration=AccountConfiguration(opp_name, None),
        verbose=False,
        max_concurrent_battles=MAX_CONCURRENT,
    )

    print(f"\n---> Run {run_number}: {variant} vs Basic (order {execution_order}) ({n_battles} battles)...")
    await player.battle_against(opponent, n_battles=n_battles)

    planned = n_battles
    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles
    unfinished = planned - finished
    win_rate = (wins / finished) * 100 if finished > 0 else 0.0

    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0.0

    crashes = 0
    exceptions = 0
    timeouts = 0
    for b in player.battles.values():
        if b.finished:
            if getattr(b, "crashed", False):
                crashes += 1
            if getattr(b, "exception", False):
                exceptions += 1
            if getattr(b, "timed_out", False):
                timeouts += 1

    ties_or_unknown = finished - wins - losses

    m = count_audit_direct_absorb_metrics(log_path)

    print(f"  Run {run_number} Finished: {wins}W {losses}L | Win Rate: {win_rate:.2f}% | Avg Turns: {avg_turns:.2f}")
    print(f"    Planned: {planned} | Finished: {finished} | Unfinished: {unfinished} | T/O: {timeouts} | Crashes: {crashes} | Exceptions: {exceptions}")
    print(f"    Protect: {m['protect_cnt']} | Spread: {m['spread_cnt']} | Focus-fire: {m['focus_fire_cnt']}")
    print(f"    Block Avoided: {m['direct_absorb_hard_block_avoided']} | Immune Selected: {m['direct_absorb_immune_move_selected']} (only legal={m['direct_absorb_only_legal_action']})")
    print(f"    Redirected: {m['redirected_absorb_selected']} | Prod Spread: {m['productive_partial_absorb_spread']}")

    return {
        "run": run_number,
        "variant": variant,
        "execution_order": execution_order,
        "planned_battles": planned,
        "finished_battles": finished,
        "unfinished_battles": unfinished,
        "wins": wins,
        "losses": losses,
        "ties_or_unknown": ties_or_unknown,
        "win_rate": f"{win_rate:.2f}",
        "avg_turns": f"{avg_turns:.2f}",
        "timeouts": timeouts,
        "crashes": crashes,
        "exceptions": exceptions,
        **m,
    }


def aggregate_blocks(blocks):
    total_wins = sum(b["wins"] for b in blocks)
    total_losses = sum(b["losses"] for b in blocks)
    total_finished = sum(b["finished_battles"] for b in blocks)
    total_planned = sum(b["planned_battles"] for b in blocks)
    total_ties = sum(b["ties_or_unknown"] for b in blocks)
    total_unfinished = sum(b["unfinished_battles"] for b in blocks)
    total_timeouts = sum(b["timeouts"] for b in blocks)
    total_crashes = sum(b["crashes"] for b in blocks)
    total_exceptions = sum(b["exceptions"] for b in blocks)

    win_rates = [float(b["win_rate"]) for b in blocks]
    avg_turns = [float(b["avg_turns"]) for b in blocks]

    agg_win_rate = (total_wins / total_finished) * 100 if total_finished > 0 else 0.0
    mean_block_wr = sum(win_rates) / len(win_rates) if win_rates else 0.0
    min_block_wr = min(win_rates) if win_rates else 0.0
    max_block_wr = max(win_rates) if win_rates else 0.0
    std_block_wr = 0.0
    if len(win_rates) > 1:
        variance = sum((wr - mean_block_wr) ** 2 for wr in win_rates) / len(win_rates)
        std_block_wr = math.sqrt(variance)

    agg_avg_turns = sum(avg_turns) / len(avg_turns) if avg_turns else 0.0

    agg_protect = sum(b["protect_cnt"] for b in blocks)
    agg_spread = sum(b["spread_cnt"] for b in blocks)
    agg_focus = sum(b["focus_fire_cnt"] for b in blocks)
    agg_zero = sum(b["zero_eff_cnt"] for b in blocks)
    agg_all_imm = sum(b["all_imm_cnt"] for b in blocks)
    agg_ground = sum(b["ground_into_levitate"] for b in blocks)
    agg_block_avoided = sum(b["direct_absorb_hard_block_avoided"] for b in blocks)
    agg_immune_sel = sum(b["direct_absorb_immune_move_selected"] for b in blocks)
    agg_only_legal = sum(b["direct_absorb_only_legal_action"] for b in blocks)
    agg_redirect = sum(b["redirected_absorb_selected"] for b in blocks)
    agg_prod_spread = sum(b["productive_partial_absorb_spread"] for b in blocks)

    return {
        "total_planned": total_planned,
        "total_finished": total_finished,
        "total_wins": total_wins,
        "total_losses": total_losses,
        "total_ties_or_unknown": total_ties,
        "agg_win_rate": agg_win_rate,
        "mean_block_wr": mean_block_wr,
        "min_block_wr": min_block_wr,
        "max_block_wr": max_block_wr,
        "std_block_wr": std_block_wr,
        "agg_avg_turns": agg_avg_turns,
        "total_unfinished": total_unfinished,
        "total_timeouts": total_timeouts,
        "total_crashes": total_crashes,
        "total_exceptions": total_exceptions,
        "agg_protect": agg_protect,
        "agg_spread": agg_spread,
        "agg_focus": agg_focus,
        "agg_zero": agg_zero,
        "agg_all_imm": agg_all_imm,
        "agg_ground": agg_ground,
        "agg_block_avoided": agg_block_avoided,
        "agg_immune_sel": agg_immune_sel,
        "agg_only_legal": agg_only_legal,
        "agg_redirect": agg_redirect,
        "agg_prod_spread": agg_prod_spread,
    }


async def main():
    os.makedirs("logs", exist_ok=True)

    config_control = DoublesDamageAwareConfig(
        enable_type_immunity_safety=True,
        enable_self_drop_move_penalty=True,
        enable_partial_spread_immunity_penalty=True,
        enable_speed_priority_awareness=True,
        enable_order_aware_overkill=False,
        enable_ability_hard_safety_only=True,
        ability_hard_safety_avoid_absorb=False,
        ability_hard_safety_avoid_redirection=False,
        ability_hard_safety_ally_spread_safety=False,
        ability_hard_safety_direct_absorb_only=False,
        enable_ability_awareness=False,
        enable_meta_opponent_modeling=False,
        enable_random_set_opponent_modeling=False,
    )

    config_experimental = DoublesDamageAwareConfig(
        enable_type_immunity_safety=True,
        enable_self_drop_move_penalty=True,
        enable_partial_spread_immunity_penalty=True,
        enable_speed_priority_awareness=True,
        enable_order_aware_overkill=False,
        enable_ability_hard_safety_only=True,
        ability_hard_safety_avoid_absorb=False,
        ability_hard_safety_avoid_redirection=False,
        ability_hard_safety_ally_spread_safety=False,
        ability_hard_safety_direct_absorb_only=True,
        enable_ability_awareness=False,
        enable_meta_opponent_modeling=False,
        enable_random_set_opponent_modeling=False,
    )

    # Six blocks in the specified execution order
    block_defs = [
        (1, "Control Off", config_control),
        (2, "Direct On", config_experimental),
        (3, "Direct On", config_experimental),
        (4, "Control Off", config_control),
        (5, "Control Off", config_control),
        (6, "Direct On", config_experimental),
    ]

    runs_data = []
    for run_num, variant, config in block_defs:
        log_path = f"logs/doubles_direct_absorb_confirmation_run{run_num}.jsonl"
        result = await run_block(
            run_number=run_num,
            variant=variant,
            execution_order=run_num,
            config=config,
            n_battles=500,
            log_path=log_path,
        )
        runs_data.append(result)

    # Stability validation
    print("\n=== Stability Validation ===")
    all_stable = True
    for row in runs_data:
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
        print(f"  Run {row['run']} ({row['variant']}): {status}")

    if not all_stable:
        print("\nSTABILITY FAILURE — aborting without adoption recommendation.")
        return

    print("All stability checks PASS.")

    # Split into Control Off and Direct On
    control_blocks = [r for r in runs_data if r["variant"] == "Control Off"]
    direct_blocks = [r for r in runs_data if r["variant"] == "Direct On"]

    control_agg = aggregate_blocks(control_blocks)
    direct_agg = aggregate_blocks(direct_blocks)

    aggregate_delta = direct_agg["agg_win_rate"] - control_agg["agg_win_rate"]

    # Paired chronological comparisons
    run_data_map = {r["run"]: r for r in runs_data}
    pair_2v1 = float(run_data_map[2]["win_rate"]) - float(run_data_map[1]["win_rate"])
    pair_3v4 = float(run_data_map[3]["win_rate"]) - float(run_data_map[4]["win_rate"])
    pair_6v5 = float(run_data_map[6]["win_rate"]) - float(run_data_map[5]["win_rate"])

    # Print aggregate report
    print(f"\n{'='*80}")
    print(f"  CONTROL OFF AGGREGATE ({control_agg['total_planned']} battles)")
    print(f"{'='*80}")
    print(f"  Wins: {control_agg['total_wins']} | Losses: {control_agg['total_losses']} | Ties/Unknown: {control_agg['total_ties_or_unknown']}")
    print(f"  Aggregate Win Rate: {control_agg['agg_win_rate']:.2f}%")
    print(f"  Mean Block Win Rate: {control_agg['mean_block_wr']:.2f}%")
    print(f"  Min Block Win Rate:  {control_agg['min_block_wr']:.2f}%")
    print(f"  Max Block Win Rate:  {control_agg['max_block_wr']:.2f}%")
    print(f"  Std Dev (population): {control_agg['std_block_wr']:.2f} pp")
    print(f"  Avg Turns: {control_agg['agg_avg_turns']:.2f}")
    print(f"  Protect: {control_agg['agg_protect']} | Spread: {control_agg['agg_spread']} | Focus-fire: {control_agg['agg_focus']}")
    print(f"  Block Avoided: {control_agg['agg_block_avoided']} | Immune Selected: {control_agg['agg_immune_sel']} (only legal={control_agg['agg_only_legal']})")
    print(f"  Redirected: {control_agg['agg_redirect']} | Prod Spread: {control_agg['agg_prod_spread']}")
    print(f"  Ground-Levitate: {control_agg['agg_ground']} | Zero-Eff: {control_agg['agg_zero']} | All-Imm: {control_agg['agg_all_imm']}")

    print(f"\n{'='*80}")
    print(f"  DIRECT ON AGGREGATE ({direct_agg['total_planned']} battles)")
    print(f"{'='*80}")
    print(f"  Wins: {direct_agg['total_wins']} | Losses: {direct_agg['total_losses']} | Ties/Unknown: {direct_agg['total_ties_or_unknown']}")
    print(f"  Aggregate Win Rate: {direct_agg['agg_win_rate']:.2f}%")
    print(f"  Mean Block Win Rate: {direct_agg['mean_block_wr']:.2f}%")
    print(f"  Min Block Win Rate:  {direct_agg['min_block_wr']:.2f}%")
    print(f"  Max Block Win Rate:  {direct_agg['max_block_wr']:.2f}%")
    print(f"  Std Dev (population): {direct_agg['std_block_wr']:.2f} pp")
    print(f"  Avg Turns: {direct_agg['agg_avg_turns']:.2f}")
    print(f"  Protect: {direct_agg['agg_protect']} | Spread: {direct_agg['agg_spread']} | Focus-fire: {direct_agg['agg_focus']}")
    print(f"  Block Avoided: {direct_agg['agg_block_avoided']} | Immune Selected: {direct_agg['agg_immune_sel']} (only legal={direct_agg['agg_only_legal']})")
    print(f"  Redirected: {direct_agg['agg_redirect']} | Prod Spread: {direct_agg['agg_prod_spread']}")
    print(f"  Ground-Levitate: {direct_agg['agg_ground']} | Zero-Eff: {direct_agg['agg_zero']} | All-Imm: {direct_agg['agg_all_imm']}")

    print(f"\n{'='*80}")
    print(f"  DELTA REPORT")
    print(f"{'='*80}")
    print(f"  Aggregate Delta: {aggregate_delta:+.2f} pp")
    print(f"    (Direct On {direct_agg['agg_win_rate']:.2f}% - Control Off {control_agg['agg_win_rate']:.2f}%)")
    print(f"  Paired Chronological Comparisons:")
    print(f"    Run 2 On - Run 1 Off: {pair_2v1:+.2f} pp")
    print(f"    Run 3 On - Run 4 Off: {pair_3v4:+.2f} pp")
    print(f"    Run 6 On - Run 5 Off: {pair_6v5:+.2f} pp")

    # Classification
    print(f"\n{'='*80}")
    print(f"  CLASSIFICATION")
    print(f"{'='*80}")
    if aggregate_delta < -2.00:
        classification = "Reproducible Regression"
        print(f"  {classification}: aggregate_delta={aggregate_delta:+.2f} pp < -2.00 pp")
        print(f"  Adoption rejected. Flag remains False.")
        print(f"  Recommend no further direct-absorb scoring work in Phase 6.")
        print(f"  Preserve implementation as disabled diagnostic code.")
    elif aggregate_delta > 2.00:
        classification = "Positive Confirmation"
        print(f"  {classification}: aggregate_delta={aggregate_delta:+.2f} pp > +2.00 pp")
        print(f"  Feature classified as performance-positive.")
        print(f"  Flag remains False pending Codex review.")
    else:
        classification = "Performance-Neutral Confirmation"
        print(f"  {classification}: -2.00 <= aggregate_delta={aggregate_delta:+.2f} pp <= +2.00")
        print(f"  Original regression classified as likely variance.")
        print(f"  Flag remains False pending Codex review.")
        # Check On blocks for non-only-legal direct absorb selections
        all_clean = all(r["direct_absorb_immune_move_selected"] == 0 for r in direct_blocks)
        if all_clean:
            print(f"  All On blocks avoided non-only-legal direct absorb selections.")
        else:
            print(f"  WARNING: Some On blocks had direct absorb-immune selections.")

    # Write CSV
    fieldnames = [
        "run", "variant", "execution_order",
        "planned_battles", "finished_battles", "unfinished_battles",
        "wins", "losses", "ties_or_unknown",
        "win_rate", "avg_turns",
        "timeouts", "crashes", "exceptions",
        "protect_cnt", "spread_cnt", "focus_fire_cnt",
        "ground_into_levitate",
        "direct_absorb_hard_block_avoided",
        "direct_absorb_immune_move_selected",
        "direct_absorb_only_legal_action",
        "redirected_absorb_selected",
        "productive_partial_absorb_spread",
        "zero_eff_cnt", "all_imm_cnt",
    ]

    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in runs_data:
            writer.writerow(row)

        # Aggregate rows
        agg_control_row = {
            "run": "CTRL_AGG",
            "variant": "Control Off",
            "execution_order": "",
            "planned_battles": control_agg["total_planned"],
            "finished_battles": control_agg["total_finished"],
            "unfinished_battles": control_agg["total_unfinished"],
            "wins": control_agg["total_wins"],
            "losses": control_agg["total_losses"],
            "ties_or_unknown": control_agg["total_ties_or_unknown"],
            "win_rate": f"{control_agg['agg_win_rate']:.2f}",
            "avg_turns": f"{control_agg['agg_avg_turns']:.2f}",
            "timeouts": control_agg["total_timeouts"],
            "crashes": control_agg["total_crashes"],
            "exceptions": control_agg["total_exceptions"],
            "protect_cnt": control_agg["agg_protect"],
            "spread_cnt": control_agg["agg_spread"],
            "focus_fire_cnt": control_agg["agg_focus"],
            "ground_into_levitate": control_agg["agg_ground"],
            "direct_absorb_hard_block_avoided": control_agg["agg_block_avoided"],
            "direct_absorb_immune_move_selected": control_agg["agg_immune_sel"],
            "direct_absorb_only_legal_action": control_agg["agg_only_legal"],
            "redirected_absorb_selected": control_agg["agg_redirect"],
            "productive_partial_absorb_spread": control_agg["agg_prod_spread"],
            "zero_eff_cnt": control_agg["agg_zero"],
            "all_imm_cnt": control_agg["agg_all_imm"],
        }
        writer.writerow(agg_control_row)

        agg_direct_row = {
            "run": "ON_AGG",
            "variant": "Direct On",
            "execution_order": "",
            "planned_battles": direct_agg["total_planned"],
            "finished_battles": direct_agg["total_finished"],
            "unfinished_battles": direct_agg["total_unfinished"],
            "wins": direct_agg["total_wins"],
            "losses": direct_agg["total_losses"],
            "ties_or_unknown": direct_agg["total_ties_or_unknown"],
            "win_rate": f"{direct_agg['agg_win_rate']:.2f}",
            "avg_turns": f"{direct_agg['agg_avg_turns']:.2f}",
            "timeouts": direct_agg["total_timeouts"],
            "crashes": direct_agg["total_crashes"],
            "exceptions": direct_agg["total_exceptions"],
            "protect_cnt": direct_agg["agg_protect"],
            "spread_cnt": direct_agg["agg_spread"],
            "focus_fire_cnt": direct_agg["agg_focus"],
            "ground_into_levitate": direct_agg["agg_ground"],
            "direct_absorb_hard_block_avoided": direct_agg["agg_block_avoided"],
            "direct_absorb_immune_move_selected": direct_agg["agg_immune_sel"],
            "direct_absorb_only_legal_action": direct_agg["agg_only_legal"],
            "redirected_absorb_selected": direct_agg["agg_redirect"],
            "productive_partial_absorb_spread": direct_agg["agg_prod_spread"],
            "zero_eff_cnt": direct_agg["agg_zero"],
            "all_imm_cnt": direct_agg["agg_all_imm"],
        }
        writer.writerow(agg_direct_row)

    print(f"\nResults written to: {CSV_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
