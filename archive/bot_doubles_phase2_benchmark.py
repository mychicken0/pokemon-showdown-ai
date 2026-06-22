#!/usr/bin/env python3
import asyncio
from poke_env import AccountConfiguration
from poke_env.player import RandomPlayer
from bot_doubles_damage_aware import DoublesDamageAwarePlayer
from bot_doubles_basic_aware import DoublesBasicAwarePlayer

N_BATTLES = 100

async def run_matchup(player_name, opponent, title):
    # Initialize Phase 2 player (verbose=False, max_concurrent_battles=5)
    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(player_name, None),
        verbose=False,
        max_concurrent_battles=5
    )
    
    print(f"\nStarting matchup: {title}...")
    await player.battle_against(opponent, n_battles=N_BATTLES)
    
    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0
    
    turns = [battle.turn for battle in player.battles.values() if battle.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0
    
    # Retrieve metrics from the player
    avg_protect = player.total_protect_count / finished if finished > 0 else 0
    avg_fake_out = player.total_fake_out_count / finished if finished > 0 else 0
    avg_spread = player.total_spread_count / finished if finished > 0 else 0
    
    print(f"\n=== Results: {title} ===")
    print(f"Total battles finished: {finished}")
    print(f"{player_name} wins: {wins}")
    print(f"{opponent.__class__.__name__} wins: {losses}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Average turns per battle: {avg_turns:.2f}")
    print(f"Average Protect usage per battle: {avg_protect:.2f}")
    print(f"Average Fake Out usage per battle: {avg_fake_out:.2f}")
    print(f"Average Spread moves used per battle: {avg_spread:.2f}")
    print("=========================================")

async def main():
    print("Starting Doubles Phase 2 Benchmark Suite...")
    
    # Matchup A: Phase 2 bot vs RandomPlayer
    random_opp = RandomPlayer(
        account_configuration=AccountConfiguration("DoublesRandOpp", None),
        battle_format="gen9randomdoublesbattle",
        max_concurrent_battles=5
    )
    await run_matchup("Phase2BotA", random_opp, "DoublesDamageAware (Phase 2) vs RandomPlayer")
    
    # Matchup B: Phase 2 bot vs DoublesBasicAwarePlayer
    basic_opp = DoublesBasicAwarePlayer(
        account_configuration=AccountConfiguration("DoublesBasicOpp", None),
        verbose=False,
        max_concurrent_battles=5
    )
    await run_matchup("Phase2BotB", basic_opp, "DoublesDamageAware (Phase 2) vs DoublesBasicAwarePlayer")

if __name__ == "__main__":
    asyncio.run(main())
