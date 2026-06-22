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

MAX_CONCURRENT = 10
CSV_PATH = "logs/doubles_speed_priority_benchmark.csv"

def count_speed_priority_metrics(log_path):
    protect_cnt = 0
    switch_cnt = 0
    unanswered_cnt = 0
    bad_protect_cnt = 0
    successful_protect_cnt = 0
    overkill_cnt = 0

    if not os.path.exists(log_path):
        return 0, 0, 0, 0, 0, 0

    with open(log_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                battle = json.loads(line)
                for turn in battle.get("audit_turns", []):
                    if turn.get("order_aware_overkill_penalty_applied"):
                        overkill_cnt += 1
                        
                    for slot_key in ("slot_0", "slot_1"):
                        slot = turn.get(slot_key, {})
                        action_types = slot.get("action_types", {})
                        
                        if action_types.get("protect"):
                            protect_cnt += 1
                        if action_types.get("switch"):
                            switch_cnt += 1
                            
                        if slot.get("outcome_known") and slot.get("speed_priority_threatened"):
                            if slot.get("expected_to_faint_before_moving") and slot.get("fainted_before_moving"):
                                unanswered_cnt += 1
                        
                        if slot.get("outcome_known") and slot.get("speed_priority_threatened"):
                            if slot.get("protected_due_to_speed_priority") and not slot.get("our_mon_fainted"):
                                successful_protect_cnt += 1
                                
                        if slot.get("outcome_known") and slot.get("protected_due_to_speed_priority"):
                            if slot.get("was_targeted") == False:
                                bad_protect_cnt += 1
            except Exception:
                continue
    return protect_cnt, switch_cnt, unanswered_cnt, bad_protect_cnt, successful_protect_cnt, overkill_cnt

async def run_matchup(name, config_on, opp_class, n_battles, log_path, label):
    suffix = random.randint(1000, 9999)
    bot_name = f"SP_{label}_{suffix}"[:18]
    opp_name = f"Opp_{label}_{suffix}"[:18]

    audit_logger = DoublesDecisionAuditLogger(
        filepath=log_path,
        reset=True,
        detail_level="top5"
    )

    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        verbose=False,
        config=config_on,
        audit_logger=audit_logger,
        max_concurrent_battles=MAX_CONCURRENT
    )

    if opp_class == DoublesDamageAwarePlayer:
        config_off = DoublesDamageAwareConfig(
            enable_type_immunity_safety=True,
            enable_self_drop_move_penalty=True,
            enable_partial_spread_immunity_penalty=True,
            enable_speed_priority_awareness=False,
            enable_order_aware_overkill=False
        )
        opp_log_path = log_path.replace("_best_vs_off.jsonl", "_off_side_best_vs_off.jsonl")
        opp_audit_logger = DoublesDecisionAuditLogger(
            filepath=opp_log_path,
            reset=True,
            detail_level="top5"
        )
        opponent = DoublesDamageAwarePlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            verbose=False,
            config=config_off,
            audit_logger=opp_audit_logger,
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

    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0.0

    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0.0

    protect_cnt, switch_cnt, unanswered_cnt, bad_protect_cnt, successful_protect_cnt, overkill_cnt = count_speed_priority_metrics(log_path)

    print(f"Run {label} Finished: {wins} Wins | {losses} Losses | Win Rate: {win_rate:.2f}% | Avg Turns: {avg_turns:.2f}")
    print(f"  Protect Used: {protect_cnt} | Switch Used: {switch_cnt} | Unanswered Threat: {unanswered_cnt}")
    print(f"  Bad Protect: {bad_protect_cnt} | Successful Protect: {successful_protect_cnt} | Overkill penalty: {overkill_cnt}")

    return {
        "matchup": name,
        "win_rate": f"{win_rate:.2f}",
        "avg_turns": f"{avg_turns:.2f}",
        "protect_cnt": protect_cnt,
        "switch_cnt": switch_cnt,
        "unanswered_cnt": unanswered_cnt,
        "bad_protect_cnt": bad_protect_cnt,
        "successful_protect_cnt": successful_protect_cnt,
        "overkill_cnt": overkill_cnt
    }

async def main():
    os.makedirs("logs", exist_ok=True)

    # 1. Config A: speed_priority_off
    config_a = DoublesDamageAwareConfig(
        enable_type_immunity_safety=True,
        enable_self_drop_move_penalty=True,
        enable_partial_spread_immunity_penalty=True,
        enable_speed_priority_awareness=False,
        enable_order_aware_overkill=False
    )

    # 2. Config B: protect_only
    config_b = DoublesDamageAwareConfig(
        enable_type_immunity_safety=True,
        enable_self_drop_move_penalty=True,
        enable_partial_spread_immunity_penalty=True,
        enable_speed_priority_awareness=True,
        speed_priority_protect_only=True,
        enable_order_aware_overkill=False
    )

    # 3. Config C: protect_attack_penalty
    config_c = DoublesDamageAwareConfig(
        enable_type_immunity_safety=True,
        enable_self_drop_move_penalty=True,
        enable_partial_spread_immunity_penalty=True,
        enable_speed_priority_awareness=True,
        speed_priority_protect_only=False,
        enable_order_aware_overkill=False
    )

    # 4. Config D: full_conservative
    config_d = DoublesDamageAwareConfig(
        enable_type_immunity_safety=True,
        enable_self_drop_move_penalty=True,
        enable_partial_spread_immunity_penalty=True,
        enable_speed_priority_awareness=True,
        speed_priority_protect_only=False,
        enable_order_aware_overkill=True
    )

    runs_data = []

    # Run A: speed_priority_off vs Basic
    res_a = await run_matchup(
        name="speed_priority_off vs DoublesBasicAwarePlayer",
        config_on=config_a,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=300,
        log_path="logs/doubles_speed_priority_off_vs_basic.jsonl",
        label="A"
    )
    runs_data.append(res_a)

    # Run B: protect_only vs Basic
    res_b = await run_matchup(
        name="protect_only vs DoublesBasicAwarePlayer",
        config_on=config_b,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=300,
        log_path="logs/doubles_protect_only_vs_basic.jsonl",
        label="B"
    )
    runs_data.append(res_b)

    # Run C: protect_attack_penalty vs Basic
    res_c = await run_matchup(
        name="protect_attack_penalty vs DoublesBasicAwarePlayer",
        config_on=config_c,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=300,
        log_path="logs/doubles_protect_attack_penalty_vs_basic.jsonl",
        label="C"
    )
    runs_data.append(res_c)

    # Run D: full_conservative vs Basic
    res_d = await run_matchup(
        name="full_conservative vs DoublesBasicAwarePlayer",
        config_on=config_d,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=300,
        log_path="logs/doubles_full_conservative_vs_basic.jsonl",
        label="D"
    )
    runs_data.append(res_d)

    # Stepwise Adoption / Programmatic Best Variant Selection
    wr_a = float(res_a["win_rate"])
    wr_b = float(res_b["win_rate"])
    wr_c = float(res_c["win_rate"])
    wr_d = float(res_d["win_rate"])

    # Default to protect_only
    best_config = config_b
    best_label = "protect_only"
    best_name = "speed_priority_protect_only"

    # Only adopt attack penalty / switch bonus if win rate improves by >= 2.0% or unanswered threats drop significantly
    # Also check if unanswered threats dropped in C vs B
    unanswered_b = res_b["unanswered_cnt"]
    unanswered_c = res_c["unanswered_cnt"]
    unanswered_d = res_d["unanswered_cnt"]

    if wr_c >= wr_b + 2.0 or (unanswered_c < unanswered_b * 0.70 and wr_c >= wr_b - 0.5):
        best_config = config_c
        best_label = "protect_attack_penalty"
        best_name = "speed_priority_protect_attack_penalty"
        # Compare full_conservative
        if wr_d >= wr_c + 2.0 or (unanswered_d < unanswered_c * 0.70 and wr_d >= wr_c - 0.5):
            best_config = config_d
            best_label = "full_conservative"
            best_name = "speed_priority_full_conservative"
    elif wr_d >= wr_b + 2.0 or (unanswered_d < unanswered_b * 0.70 and wr_d >= wr_b - 0.5):
        best_config = config_d
        best_label = "full_conservative"
        best_name = "speed_priority_full_conservative"

    print(f"\n====== Programmatic Best Variant Selection ======")
    print(f"  Win rates: A(Off)={wr_a}%, B(Protect Only)={wr_b}%, C(Attack Penalty)={wr_c}%, D(Full Conservative)={wr_d}%")
    print(f"  Unanswered threats: B={unanswered_b}, C={unanswered_c}, D={unanswered_d}")
    print(f"  Adopted Best Variant: {best_name}")
    print(f"==================================================")

    # Run E: best_variant vs speed_priority_off
    res_e = await run_matchup(
        name=f"best_variant ({best_label}) vs speed_priority_off",
        config_on=best_config,
        opp_class=DoublesDamageAwarePlayer,
        n_battles=300,
        log_path="logs/doubles_best_vs_off.jsonl",
        label="E"
    )
    runs_data.append(res_e)

    # Run F: best_variant vs DoublesSafeRandomPlayer
    res_f = await run_matchup(
        name=f"best_variant ({best_label}) vs DoublesSafeRandomPlayer",
        config_on=best_config,
        opp_class=DoublesSafeRandomPlayer,
        n_battles=100,
        log_path="logs/doubles_best_vs_safe_random.jsonl",
        label="F"
    )
    runs_data.append(res_f)

    # Save to CSV
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "matchup", "win_rate", "avg_turns", "protect_cnt", "switch_cnt", "unanswered_cnt", "bad_protect_cnt", "successful_protect_cnt", "overkill_cnt"
        ])
        writer.writeheader()
        for row in runs_data:
            writer.writerow(row)

    print(f"\nAll benchmark matchups finished. Results written to: {CSV_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
