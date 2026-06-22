#!/usr/bin/env python3
import asyncio
from poke_env import AccountConfiguration
from poke_env.player import RandomPlayer
from bot_doubles_damage_aware import DoublesDamageAwarePlayer
from doubles_battle_logger import DoublesBattleLogger

# Benchmark settings: 50 battles first as requested
N_BATTLES = 50

async def main():
    # Setup doubles battle logger (resets existing logs)
    logger = DoublesBattleLogger(filepath="logs/doubles_battle_results.jsonl", reset=True)
    
    # Initialize both players
    damage_aware_player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration("DoublesDamageBot", None),
        verbose=False,
        logger=logger,
        max_concurrent_battles=5
    )
    random_player = RandomPlayer(
        account_configuration=AccountConfiguration("DoublesRandomBot", None),
        battle_format="gen9randomdoublesbattle",
        max_concurrent_battles=5
    )

    print(f"Starting Doubles benchmark matchup on the local server...")
    print(f"Pitting DoublesDamageAwarePlayer against RandomPlayer for {N_BATTLES} battles...")
    
    # Run the battles
    await damage_aware_player.battle_against(random_player, n_battles=N_BATTLES)

    # Print results
    finished = damage_aware_player.n_finished_battles
    wins = damage_aware_player.n_won_battles
    losses = random_player.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0

    # Calculate average turns
    turns = [battle.turn for battle in damage_aware_player.battles.values() if battle.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0

    print("\n================ Doubles Benchmark Results ================")
    print(f"Total battles finished: {finished}")
    print(f"DoublesDamageAwarePlayer wins: {wins}")
    print(f"RandomPlayer wins: {losses}")
    print(f"DoublesDamageAwarePlayer Win Rate: {win_rate:.2f}%")
    print(f"Average turns per battle: {avg_turns:.2f}")
    print("===========================================================")

if __name__ == "__main__":
    asyncio.run(main())
