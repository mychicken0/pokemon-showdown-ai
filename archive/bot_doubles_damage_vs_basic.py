#!/usr/bin/env python3
import asyncio
from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer
from bot_doubles_basic_aware import DoublesBasicAwarePlayer

N_BATTLES = 100

async def main():
    # Initialize both players (silent mode, concurrent limit = 5)
    damage_aware_player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration("DoublesDamageBot", None),
        verbose=False,
        max_concurrent_battles=5
    )
    basic_aware_player = DoublesBasicAwarePlayer(
        account_configuration=AccountConfiguration("DoublesBasicBot", None),
        verbose=False,
        max_concurrent_battles=5
    )

    print(f"Starting Doubles benchmark matchup on the local server...")
    print(f"Pitting DoublesDamageAwarePlayer (Phase 1) against DoublesBasicAwarePlayer for {N_BATTLES} battles...")
    
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

    print("\n================ Benchmark Results ================")
    print(f"Total battles finished: {finished}")
    print(f"DoublesDamageAwarePlayer wins: {wins}")
    print(f"DoublesBasicAwarePlayer wins: {losses}")
    print(f"DoublesDamageAwarePlayer Win Rate: {win_rate:.2f}%")
    print(f"Average turns per battle: {avg_turns:.2f}")
    print("===================================================")

if __name__ == "__main__":
    asyncio.run(main())
