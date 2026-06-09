import asyncio
from poke_env.player import RandomPlayer
from poke_env import AccountConfiguration

async def main():
    # Initialize two random players.
    # They connect to localhost:8000 using poke-env's default configuration.
    # We specify different usernames and omit passwords since --no-security is on.
    player_1 = RandomPlayer(
        account_configuration=AccountConfiguration("SelfplayBot_1", None),
        max_concurrent_battles=1
    )
    player_2 = RandomPlayer(
        account_configuration=AccountConfiguration("SelfplayBot_2", None),
        max_concurrent_battles=1
    )

    print("Starting self-play battle on local Pokémon Showdown server...")
    print("SelfplayBot_1 is challenging SelfplayBot_2...")
    
    # Challenge and execute 1 battle
    await player_1.battle_against(player_2, n_battles=1)

    # Output results to verify completion
    print("\n=== Battle Finished Successfully ===")
    print(f"Finished battles: {player_1.n_finished_battles}")
    print(f"SelfplayBot_1 wins: {player_1.n_won_battles}")
    print(f"SelfplayBot_2 wins: {player_2.n_won_battles}")

if __name__ == "__main__":
    asyncio.run(main())
