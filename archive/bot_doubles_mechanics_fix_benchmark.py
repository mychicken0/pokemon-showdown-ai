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
CSV_PATH = "logs/doubles_mechanics_fix_benchmark.csv"

def count_audit_violations(log_path):
    """
    Parse the audit log and return counts of:
    - zero_effectiveness_move_selected
    - all_targets_immune_spread_selected
    - self_drop_move_spam
    """
    zero_eff_cnt = 0
    all_imm_cnt = 0
    self_drop_cnt = 0

    if not os.path.exists(log_path):
        return 0, 0, 0

    with open(log_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                battle = json.loads(line)
                for turn in battle.get("audit_turns", []):
                    for slot_key in ("slot_0", "slot_1"):
                        slot = turn.get(slot_key, {})
                        if slot.get("zero_effectiveness_move_selected"):
                            zero_eff_cnt += 1
                        if slot.get("all_targets_immune_spread_selected"):
                            all_imm_cnt += 1
                        if slot.get("self_drop_move_spam"):
                            self_drop_cnt += 1
            except Exception:
                continue
    return zero_eff_cnt, all_imm_cnt, self_drop_cnt

async def run_matchup(name, config_on, opp_class, n_battles, log_path, label):
    suffix = random.randint(1000, 9999)
    bot_name = f"Mech_{label}_{suffix}"[:18]
    opp_name = f"Opp_{label}_{suffix}"[:18]

    # Initialize separate audit logger for this matchup
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
        # For head-to-head (mechanics_fix_on vs mechanics_fix_off)
        config_off = DoublesDamageAwareConfig(
            enable_type_immunity_safety=False,
            enable_self_drop_move_penalty=False,
            enable_threat_scoring=False,
            enable_threat_tiebreaker=False,
            enable_boosted_threat_override=False,
            enable_ability_awareness=False,
            enable_meta_opponent_modeling=False,
            enable_random_set_opponent_modeling=False
        )
        opponent = DoublesDamageAwarePlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            verbose=False,
            config=config_off,
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

    # Retrieve penalties applied from player metrics
    draco_applied = player.total_draco_penalties_applied
    mir_applied = player.total_make_it_rain_penalties_applied

    # Read audit logger to see how many mistakes actually happened (slipped past)
    zero_eff_err, all_imm_err, self_drop_err = count_audit_violations(log_path)

    print(f"Run {label} Finished: {wins} Wins | {losses} Losses | Win Rate: {win_rate:.2f}% | Avg Turns: {avg_turns:.2f}")
    print(f"  Draco repeat penalties applied: {draco_applied}")
    print(f"  Make It Rain penalties applied: {mir_applied}")
    print(f"  Audit logs: Zero-eff mistakes: {zero_eff_err} | All-imm spreads: {all_imm_err} | Self-drop spams: {self_drop_err}")

    return {
        "matchup": name,
        "win_rate": f"{win_rate:.2f}",
        "avg_turns": f"{avg_turns:.2f}",
        "draco_applied": draco_applied,
        "make_it_rain_applied": mir_applied,
        "zero_eff_err": zero_eff_err,
        "all_imm_err": all_imm_err,
        "self_drop_err": self_drop_err
    }

async def main():
    os.makedirs("logs", exist_ok=True)

    # Standard configuration with mechanics fixes ENABLED
    config_on = DoublesDamageAwareConfig(
        enable_type_immunity_safety=True,
        enable_self_drop_move_penalty=True,
        enable_threat_scoring=False,
        enable_threat_tiebreaker=False,
        enable_boosted_threat_override=False,
        enable_ability_awareness=False,
        enable_meta_opponent_modeling=False,
        enable_random_set_opponent_modeling=False
    )

    # Standard configuration with mechanics fixes DISABLED
    config_off = DoublesDamageAwareConfig(
        enable_type_immunity_safety=False,
        enable_self_drop_move_penalty=False,
        enable_threat_scoring=False,
        enable_threat_tiebreaker=False,
        enable_boosted_threat_override=False,
        enable_ability_awareness=False,
        enable_meta_opponent_modeling=False,
        enable_random_set_opponent_modeling=False
    )

    # Run definitions
    runs_data = []

    # Run A: mechanics_fix_on vs DoublesBasicAwarePlayer (300 battles)
    r_a = await run_matchup(
        name="mechanics_fix_on vs DoublesBasicAwarePlayer",
        config_on=config_on,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=300,
        log_path="logs/doubles_mechanics_fix_on_vs_basic.jsonl",
        label="A"
    )
    runs_data.append(r_a)

    # Run B: mechanics_fix_off vs DoublesBasicAwarePlayer (300 battles)
    r_b = await run_matchup(
        name="mechanics_fix_off vs DoublesBasicAwarePlayer",
        config_on=config_off,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=300,
        log_path="logs/doubles_mechanics_fix_off_vs_basic.jsonl",
        label="B"
    )
    runs_data.append(r_b)

    # Run C: mechanics_fix_on vs mechanics_fix_off (300 battles)
    r_c = await run_matchup(
        name="mechanics_fix_on vs mechanics_fix_off",
        config_on=config_on,
        opp_class=DoublesDamageAwarePlayer,
        n_battles=300,
        log_path="logs/doubles_mechanics_fix_on_vs_off.jsonl",
        label="C"
    )
    runs_data.append(r_c)

    # Run D: mechanics_fix_on vs DoublesSafeRandomPlayer (100 battles)
    r_d = await run_matchup(
        name="mechanics_fix_on vs DoublesSafeRandomPlayer",
        config_on=config_on,
        opp_class=DoublesSafeRandomPlayer,
        n_battles=100,
        log_path="logs/doubles_mechanics_fix_on_vs_random.jsonl",
        label="D"
    )
    runs_data.append(r_d)

    # Save to CSV
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "matchup", "win_rate", "avg_turns", "draco_applied", "make_it_rain_applied", "zero_eff_err", "all_imm_err", "self_drop_err"
        ])
        writer.writeheader()
        for row in runs_data:
            writer.writerow(row)

    print(f"\nAll benchmark matchups finished. Results written to: {CSV_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
