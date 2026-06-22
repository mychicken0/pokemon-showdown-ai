import asyncio
from poke_env.player import Player
from poke_env import AccountConfiguration

# Create a custom Player class that extends poke_env's base Player
class RandomBot(Player):
    def choose_move(self, battle):
        """
        This method is called at every turn in the battle.
        It must return a move or switch action.
        """
        # Print the current turn number and battle tag
        print(f"\n--- Battle: {battle.battle_tag} | Turn {battle.turn} ---")
        
        # Display our active Pokémon status
        active = battle.active_pokemon
        if active:
            print(f"Active Pokémon: {active.species} ({active.current_hp}/{active.max_hp} HP)")
        else:
            print("Active Pokémon: None")
            
        # Display opponent active Pokémon status
        opponent = battle.opponent_active_pokemon
        if opponent:
            print(f"Opponent Pokémon: {opponent.species} ({opponent.current_hp}/{opponent.max_hp} HP)")
        else:
            print("Opponent Pokémon: Unknown")
            
        # Log the choices available to this bot
        print("Available moves:", [move.id for move in battle.available_moves])
        print("Available switches:", [switch.species for switch in battle.available_switches])
        
        # Select and return a random legal action (move or switch)
        action = self.choose_random_move(battle)
        return action

async def main():
    # Initialize the random bot.
    # The default server configuration in poke-env is already pointing to localhost (LocalhostServerConfiguration)
    # The password is None as the local server has --no-security enabled.
    bot = RandomBot(
        account_configuration=AccountConfiguration("RandomAgent_1", None)
    )

    print("Bot is starting and waiting for a challenge...")
    # Accept a single challenge from any player
    await bot.accept_challenges(None, n_challenges=1)
    print("Battle has finished. Shutting down bot.")

if __name__ == "__main__":
    asyncio.run(main())
