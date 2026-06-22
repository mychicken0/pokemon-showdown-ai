#!/usr/bin/env python3
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
CSV_PATH = "logs/doubles_direct_absorb_safety_corrected_benchmark.csv"

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
        "productive_partial_absorb_spread": 0
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

async def run_matchup(name, config, opp_class, opp_config, n_battles, log_path, label):
    suffix = random.randint(1000, 9999)
    bot_name = f"Safety_{label}_{suffix}"[:18]
    opp_name = f"Opp_{label}_{suffix}"[:18]

    audit_logger = DoublesDecisionAuditLogger(
        filepath=log_path,
        reset=True,
        detail_level="top5"
    )

    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        verbose=False,
        config=config,
        audit_logger=audit_logger,
        max_concurrent_battles=MAX_CONCURRENT
    )

    if opp_class == DoublesDamageAwarePlayer:
        opponent = DoublesDamageAwarePlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            verbose=False,
            config=opp_config,
            max_concurrent_battles=MAX_CONCURRENT
        )
    elif opp_class == DoublesBasicAwarePlayer:
        opponent = DoublesBasicAwarePlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            verbose=False,
            max_concurrent_battles=MAX_CONCURRENT
        )
    elif opp_class == DoublesSafeRandomPlayer:
        opponent = DoublesSafeRandomPlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            max_concurrent_battles=MAX_CONCURRENT
        )
    else:
        raise ValueError(f"Unknown opponent class: {opp_class}")

    print(f"\n---> Starting Run {label}: {name} ({n_battles} battles)...")
    await player.battle_against(opponent, n_battles=n_battles)

    planned = n_battles
    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles
    unfinished = planned - finished
    win_rate = (wins / finished) * 100 if finished > 0 else 0.0

    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0.0

    # Count crashes/exceptions/timeouts from finished battles
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

    print(f"Run {label} Finished: {wins} Wins | {losses} Losses | Win Rate: {win_rate:.2f}% | Avg Turns: {avg_turns:.2f}")
    print(f"  Planned: {planned} | Finished: {finished} | Unfinished: {unfinished} | Timeouts: {timeouts} | Crashes: {crashes} | Exceptions: {exceptions}")
    print(f"  Protect: {m['protect_cnt']} | Spread: {m['spread_cnt']} | Focus-fire: {m['focus_fire_cnt']}")
    print(f"  Direct Block Avoided: {m['direct_absorb_hard_block_avoided']} | Direct Immune Selected: {m['direct_absorb_immune_move_selected']} (only legal={m['direct_absorb_only_legal_action']})")
    print(f"  Redirected Absorb Selected: {m['redirected_absorb_selected']} | Productive Spread: {m['productive_partial_absorb_spread']}")

    return {
        "matchup": name,
        "planned_battles": planned,
        "finished_battles": finished,
        "unfinished_battles": unfinished,
        "wins": wins,
        "losses": losses,
        "ties_or_unknown": ties_or_unknown,
        "timeouts": timeouts,
        "crashes": crashes,
        "exceptions": exceptions,
        "win_rate": f"{win_rate:.2f}",
        "avg_turns": f"{avg_turns:.2f}",
        **m
    }

async def main():
    os.makedirs("logs", exist_ok=True)

    # Setup configurations: control is Ground-only defaults, experimental adds direct absorb safety
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
        ability_hard_safety_direct_absorb_only=False, # control off
        enable_ability_awareness=False,
        enable_meta_opponent_modeling=False,
        enable_random_set_opponent_modeling=False
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
        ability_hard_safety_direct_absorb_only=True, # experimental on
        enable_ability_awareness=False,
        enable_meta_opponent_modeling=False,
        enable_random_set_opponent_modeling=False
    )

    runs_data = []

    # Run 1: Control Off vs Basic: 500 battles
    r1 = await run_matchup(
        name="Control Off vs Basic",
        config=config_control,
        opp_class=DoublesBasicAwarePlayer,
        opp_config=None,
        n_battles=500,
        log_path="logs/doubles_direct_absorb_safety_corrected_run1.jsonl",
        label="1"
    )
    runs_data.append(r1)

    # Run 2: Direct Absorb On vs Basic: 500 battles
    r2 = await run_matchup(
        name="Direct Absorb On vs Basic",
        config=config_experimental,
        opp_class=DoublesBasicAwarePlayer,
        opp_config=None,
        n_battles=500,
        log_path="logs/doubles_direct_absorb_safety_corrected_run2.jsonl",
        label="2"
    )
    runs_data.append(r2)

    # Run 3: Direct Absorb On vs Control Off: 500 battles
    r3 = await run_matchup(
        name="Direct Absorb On vs Control Off",
        config=config_experimental,
        opp_class=DoublesDamageAwarePlayer,
        opp_config=config_control,
        n_battles=500,
        log_path="logs/doubles_direct_absorb_safety_corrected_run3.jsonl",
        label="3"
    )
    runs_data.append(r3)

    # Run 4: Direct Absorb On vs SafeRandom: 100 battles
    r4 = await run_matchup(
        name="Direct Absorb On vs SafeRandom",
        config=config_experimental,
        opp_class=DoublesSafeRandomPlayer,
        opp_config=None,
        n_battles=100,
        log_path="logs/doubles_direct_absorb_safety_corrected_run4.jsonl",
        label="4"
    )
    runs_data.append(r4)

    # Save summary results to CSV with stability fields
    fieldnames = [
        "matchup", "planned_battles", "finished_battles", "unfinished_battles",
        "wins", "losses", "ties_or_unknown", "timeouts", "crashes", "exceptions",
        "win_rate", "avg_turns", "protect_cnt", "spread_cnt", "focus_fire_cnt",
        "zero_eff_cnt", "all_imm_cnt", "ground_into_levitate", "direct_absorb_hard_block_avoided",
        "direct_absorb_immune_move_selected", "direct_absorb_only_legal_action",
        "redirected_absorb_selected", "productive_partial_absorb_spread"
    ]

    # Validate stability fields
    for row in runs_data:
        assert row["finished_battles"] == row["planned_battles"], (
            f"finished_battles ({row['finished_battles']}) != planned_battles ({row['planned_battles']}) in {row['matchup']}"
        )
        assert row["wins"] + row["losses"] + row["ties_or_unknown"] == row["finished_battles"], (
            f"wins+losses+ties ({row['wins']}+{row['losses']}+{row['ties_or_unknown']}) != finished ({row['finished_battles']}) in {row['matchup']}"
        )
        assert row["unfinished_battles"] == 0, f"unfinished_battles != 0 in {row['matchup']}"
        assert row["timeouts"] == 0, f"timeouts != 0 in {row['matchup']}"
        assert row["crashes"] == 0, f"crashes != 0 in {row['matchup']}"
        assert row["exceptions"] == 0, f"exceptions != 0 in {row['matchup']}"

    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in runs_data:
            writer.writerow(row)

    print(f"\nAll Phase 6.3.3a corrected benchmark matchups finished. Results written to: {CSV_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
