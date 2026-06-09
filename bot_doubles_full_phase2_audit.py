#!/usr/bin/env python3
import asyncio
import os
import random
from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

N_BATTLES = 300
MAX_CONCURRENT = 10
AUDIT_LOG_PATH = "logs/doubles_decision_audit.jsonl"

async def main():
    # Set up random usernames to avoid collisions
    suffix = random.randint(1000, 9999)
    bot_name = f"AuditBot_{suffix}"
    opp_name = f"BasicBot_{suffix}"

    # Initialize the audit logger
    audit_logger = DoublesDecisionAuditLogger(
        filepath=AUDIT_LOG_PATH,
        reset=True,
        detail_level="top5"
    )

    # Configure player with stable full_phase2 defaults
    config = DoublesDamageAwareConfig(
        enable_threat_scoring=False,
        enable_threat_tiebreaker=False,
        enable_boosted_threat_override=False,
        enable_ability_awareness=False,
        enable_meta_opponent_modeling=False,
        enable_random_set_opponent_modeling=False
    )

    damage_aware_player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        verbose=False,
        config=config,
        audit_logger=audit_logger,
        max_concurrent_battles=MAX_CONCURRENT
    )

    basic_aware_player = DoublesBasicAwarePlayer(
        account_configuration=AccountConfiguration(opp_name, None),
        verbose=False,
        max_concurrent_battles=MAX_CONCURRENT
    )

    print(f"Starting Doubles Phase 6 Audit Benchmark...")
    print(f"Pitting DoublesDamageAwarePlayer (full_phase2) against DoublesBasicAwarePlayer for {N_BATTLES} battles...")
    
    # Run the battles
    await damage_aware_player.battle_against(basic_aware_player, n_battles=N_BATTLES)

    # Print results
    finished = damage_aware_player.n_finished_battles
    wins = damage_aware_player.n_won_battles
    losses = basic_aware_player.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0

    # Calculate average turns
    turns = [battle.turn for battle in damage_aware_player.battles.values() if battle.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0

    # Count audit records written
    records_count = 0
    if os.path.exists(AUDIT_LOG_PATH):
        with open(AUDIT_LOG_PATH, "r") as f:
            for line in f:
                if line.strip():
                    records_count += 1

    print("\n================ Audit Benchmark Results ================")
    print(f"Total battles finished: {finished}")
    print(f"Wins: {wins} | Losses: {losses}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Average turns per battle: {avg_turns:.2f}")
    print(f"Audit log path: {AUDIT_LOG_PATH}")
    print(f"Number of battle audit records written: {records_count}")
    print("=========================================================")

if __name__ == "__main__":
    asyncio.run(main())
