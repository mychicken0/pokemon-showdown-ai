import asyncio
from poke_env import AccountConfiguration
from bot_rule_based import RuleBasedPlayer
from bot_damage_aware import DamageAwarePlayer

# Benchmark settings: changed to 100 battles for more reliable testing
N_BATTLES = 100

async def main():
    # Setup players in silent mode (verbose=False) running concurrently (max_concurrent_battles=10)
    damage_aware_player = DamageAwarePlayer(
        account_configuration=AccountConfiguration("DamageAwareBot", None),
        verbose=False,
        max_concurrent_battles=10
    )
    rule_based_player = RuleBasedPlayer(
        account_configuration=AccountConfiguration("RuleBasedOpponent", None),
        verbose=False,
        max_concurrent_battles=10
    )

    print(f"Starting benchmark matchup on the local server...")
    print(f"Pitting DamageAwarePlayer against RuleBasedPlayer for {N_BATTLES} battles...")
    
    # Run the battles
    await damage_aware_player.battle_against(rule_based_player, n_battles=N_BATTLES)

    # Print results
    finished = damage_aware_player.n_finished_battles
    wins = damage_aware_player.n_won_battles
    losses = rule_based_player.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0

    print("\n================ Benchmark Results ================")
    print(f"Total battles finished: {finished}")
    print(f"DamageAwarePlayer wins: {wins}")
    print(f"RuleBasedPlayer wins: {losses}")
    print(f"DamageAwarePlayer Win Rate: {win_rate:.2f}%")
    print("===================================================")

if __name__ == "__main__":
    asyncio.run(main())
