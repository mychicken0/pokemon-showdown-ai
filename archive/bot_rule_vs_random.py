import asyncio
from poke_env.player import RandomPlayer
from poke_env import AccountConfiguration
from bot_rule_based import RuleBasedPlayer

async def main():
    # Initialize players with max_concurrent_battles=1 so that logs do not overlap.
    # We use local accounts without passwords (since --no-security is active).
    rule_based_player = RuleBasedPlayer(
        account_configuration=AccountConfiguration("RuleBot", None),
        max_concurrent_battles=1
    )
    random_player = RandomPlayer(
        account_configuration=AccountConfiguration("RandomOpponent", None),
        max_concurrent_battles=1
    )

    print("Starting 10 battles between RuleBasedPlayer (RuleBot) and RandomPlayer (RandomOpponent) on the local server...")
    
    # Run the 10 battles
    await rule_based_player.battle_against(random_player, n_battles=10)

    # Get stats
    finished = rule_based_player.n_finished_battles
    wins = rule_based_player.n_won_battles
    losses = random_player.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0

    print("\n================ Battle Summary ================")
    print(f"Total battles finished: {finished}")
    print(f"RuleBasedPlayer wins: {wins}")
    print(f"RandomPlayer wins: {losses}")
    print(f"RuleBasedPlayer Win Rate: {win_rate:.2f}%")
    print("================================================")

if __name__ == "__main__":
    asyncio.run(main())
