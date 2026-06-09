#!/usr/bin/env python3
import asyncio
from poke_env.player import RandomPlayer
from poke_env import AccountConfiguration

async def main():
    format_id = "gen9randomdoublesbattle"
    print(f"Starting self-play battle in format '{format_id}'...")
    
    player_1 = RandomPlayer(
        account_configuration=AccountConfiguration("DoublesBot_1", None),
        battle_format=format_id,
        max_concurrent_battles=1
    )
    player_2 = RandomPlayer(
        account_configuration=AccountConfiguration("DoublesBot_2", None),
        battle_format=format_id,
        max_concurrent_battles=1
    )

    try:
        # Challenge and execute 1 battle
        await player_1.battle_against(player_2, n_battles=1)
        
        # Check if the battle completed and extract info
        if player_1.battles:
            battle_tag, battle = list(player_1.battles.items())[0]
            print("\n=== Battle Completed Successfully ===")
            print(f"Battle Tag: {battle_tag}")
            print(f"Battle Format: {battle.format}")
            print(f"Completed: {battle.finished}")
            
            # Determine the winner based on battle.won
            if battle.won is True:
                winner_name = player_1.username
            elif battle.won is False:
                winner_name = player_2.username
            else:
                winner_name = "Tie / Unknown"
                
            print(f"Winner: {winner_name}")
        else:
            print("No battle recorded in player_1.battles.")
    except Exception as e:
        print(f"Failed to run battle in '{format_id}': {e}")

if __name__ == "__main__":
    asyncio.run(main())
