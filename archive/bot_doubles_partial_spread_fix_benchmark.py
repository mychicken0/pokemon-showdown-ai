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
CSV_PATH = "logs/doubles_partial_spread_fix_benchmark.csv"

def count_spread_metrics(log_path):
    """
    Parse the audit log and return counts of:
    - spread moves used
    - valid spread moves used
    - partial immune spread selected
    - efficient partial spread selected
    - inefficient partial spread selected
    """
    spread_cnt = 0
    valid_spread_cnt = 0
    partial_immune_cnt = 0
    efficient_cnt = 0
    inefficient_cnt = 0

    if not os.path.exists(log_path):
        return 0, 0, 0, 0, 0

    with open(log_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                battle = json.loads(line)
                for turn in battle.get("audit_turns", []):
                    for slot_key in ("slot_0", "slot_1"):
                        slot = turn.get(slot_key, {})
                        if slot.get("action_types", {}).get("spread"):
                            spread_cnt += 1
                            if slot.get("partial_immune_spread_selected"):
                                partial_immune_cnt += 1
                                if slot.get("efficient_partial_spread_selected"):
                                    efficient_cnt += 1
                                if slot.get("inefficient_partial_spread_selected"):
                                    inefficient_cnt += 1
                            # Define valid spread usage as:
                            # valid_spread_moves_used = selected spread moves that are not inefficient_partial_spread_selected
                            if not slot.get("inefficient_partial_spread_selected"):
                                valid_spread_cnt += 1
            except Exception:
                continue
    return spread_cnt, valid_spread_cnt, partial_immune_cnt, efficient_cnt, inefficient_cnt

async def run_matchup(name, config_on, opp_class, n_battles, log_path, label):
    suffix = random.randint(1000, 9999)
    bot_name = f"Spread_{label}_{suffix}"[:18]
    opp_name = f"Opp_{label}_{suffix}"[:18]

    # Initialize audit logger
    audit_logger = DoublesDecisionAuditLogger(
        filepath=log_path,
        reset=True,
        detail_level="top5"
    )

    # Instantiate player
    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        verbose=False,
        config=config_on,
        audit_logger=audit_logger,
        max_concurrent_battles=MAX_CONCURRENT
    )

    # Instantiate opponent
    if opp_class == DoublesDamageAwarePlayer:
        # Matchup C: on vs off
        config_off = DoublesDamageAwareConfig(
            enable_type_immunity_safety=True,
            enable_self_drop_move_penalty=True,
            enable_partial_spread_immunity_penalty=False,
            enable_threat_scoring=False,
            enable_threat_tiebreaker=False,
            enable_boosted_threat_override=False,
            enable_ability_awareness=False,
            enable_meta_opponent_modeling=False,
            enable_random_set_opponent_modeling=False
        )
        # Create opponent with audit logger so we can log their choices too
        opp_log_path = log_path.replace("_on_vs_off.jsonl", "_off_side_on_vs_off.jsonl")
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

    # Reconstruct results
    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0.0

    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0.0

    # Read audit logger to see spread metrics
    spread_cnt, valid_spread_cnt, partial_immune_cnt, efficient_cnt, inefficient_cnt = count_spread_metrics(log_path)

    print(f"Run {label} Finished: {wins} Wins | {losses} Losses | Win Rate: {win_rate:.2f}% | Avg Turns: {avg_turns:.2f}")
    print(f"  Spread Used: {spread_cnt} | Valid Spread: {valid_spread_cnt} | Partial Immune: {partial_immune_cnt}")
    print(f"  Efficient Partial: {efficient_cnt} | Inefficient Partial: {inefficient_cnt}")

    return {
        "matchup": name,
        "win_rate": f"{win_rate:.2f}",
        "avg_turns": f"{avg_turns:.2f}",
        "spread_cnt": spread_cnt,
        "valid_spread_cnt": valid_spread_cnt,
        "partial_immune_cnt": partial_immune_cnt,
        "efficient_cnt": efficient_cnt,
        "inefficient_cnt": inefficient_cnt
    }

async def main():
    os.makedirs("logs", exist_ok=True)

    # Standard configuration with mechanics fixes + partial spread fix ENABLED
    config_on = DoublesDamageAwareConfig(
        enable_type_immunity_safety=True,
        enable_self_drop_move_penalty=True,
        enable_partial_spread_immunity_penalty=True,
        enable_threat_scoring=False,
        enable_threat_tiebreaker=False,
        enable_boosted_threat_override=False,
        enable_ability_awareness=False,
        enable_meta_opponent_modeling=False,
        enable_random_set_opponent_modeling=False
    )

    # Standard configuration with mechanics fixes ENABLED, but partial spread fix DISABLED
    config_off = DoublesDamageAwareConfig(
        enable_type_immunity_safety=True,
        enable_self_drop_move_penalty=True,
        enable_partial_spread_immunity_penalty=False,
        enable_threat_scoring=False,
        enable_threat_tiebreaker=False,
        enable_boosted_threat_override=False,
        enable_ability_awareness=False,
        enable_meta_opponent_modeling=False,
        enable_random_set_opponent_modeling=False
    )

    runs_data = []

    # Run A: partial_spread_fix_on vs DoublesBasicAwarePlayer (300 battles)
    r_a = await run_matchup(
        name="partial_spread_fix_on vs DoublesBasicAwarePlayer",
        config_on=config_on,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=300,
        log_path="logs/doubles_partial_spread_fix_on_vs_basic.jsonl",
        label="A"
    )
    runs_data.append(r_a)

    # Run B: partial_spread_fix_off vs DoublesBasicAwarePlayer (300 battles)
    r_b = await run_matchup(
        name="partial_spread_fix_off vs DoublesBasicAwarePlayer",
        config_on=config_off,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=300,
        log_path="logs/doubles_partial_spread_fix_off_vs_basic.jsonl",
        label="B"
    )
    runs_data.append(r_b)

    # Run C: partial_spread_fix_on vs partial_spread_fix_off (300 battles)
    r_c = await run_matchup(
        name="partial_spread_fix_on vs partial_spread_fix_off",
        config_on=config_on,
        opp_class=DoublesDamageAwarePlayer,
        n_battles=300,
        log_path="logs/doubles_partial_spread_fix_on_vs_off.jsonl",
        label="C"
    )
    runs_data.append(r_c)

    # Run D: partial_spread_fix_on vs DoublesSafeRandomPlayer (100 battles)
    r_d = await run_matchup(
        name="partial_spread_fix_on vs DoublesSafeRandomPlayer",
        config_on=config_on,
        opp_class=DoublesSafeRandomPlayer,
        n_battles=100,
        log_path="logs/doubles_partial_spread_fix_on_vs_random.jsonl",
        label="D"
    )
    runs_data.append(r_d)

    # Save to CSV
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "matchup", "win_rate", "avg_turns", "spread_cnt", "valid_spread_cnt", "partial_immune_cnt", "efficient_cnt", "inefficient_cnt"
        ])
        writer.writeheader()
        for row in runs_data:
            writer.writerow(row)

    print(f"\nAll benchmark matchups finished. Results written to: {CSV_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
