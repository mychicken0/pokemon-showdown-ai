import asyncio
import random
from poke_env.player import Player
from poke_env import AccountConfiguration

class RuleBasedPlayer(Player):
    def __init__(self, *args, verbose=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.verbose = verbose

    def calculate_move_score(self, move, battle):
        """
        Calculates a score for a move using basic rules:
        - Base power is the foundation.
        - STAB (Same Type Attack Bonus) gets a bonus (+20).
        - Type effectiveness multiplier is applied.
        - Accuracy scales the score (expected value).
        - Status/0-power moves receive a low base score.
        """
        base_power = move.base_power
        opponent = battle.opponent_active_pokemon
        
        if base_power > 0:
            score = float(base_power)
            
            # STAB: Same Type Attack Bonus
            active_types = battle.active_pokemon.types if battle.active_pokemon else []
            if move.type and move.type in active_types:
                score += 20.0
                
            # Type Effectiveness
            if opponent:
                multiplier = opponent.damage_multiplier(move)
                score *= multiplier
        else:
            # Status moves or moves with 0 base power
            score = 10.0
            
        # Accuracy scaling (expected value)
        acc = move.accuracy
        if isinstance(acc, (int, float)):
            score *= acc
        else:
            score *= 1.0  # Fallback
            
        return score

    def choose_move(self, battle):
        """
        Decision-making process based on explicit scoring rules.
        """
        available_moves = battle.available_moves
        opponent = battle.opponent_active_pokemon
        active = battle.active_pokemon
        
        # Verbose Logging for Battle State
        if self.verbose:
            print(f"\n--- Battle: {battle.battle_tag} | Turn {battle.turn} ---")
            if active:
                print(f"Our Active Pokémon: {active.species} ({active.current_hp}/{active.max_hp} HP)")
            if opponent:
                print(f"Opponent Active Pokémon: {opponent.species} ({opponent.current_hp}/{opponent.max_hp} HP)")
        
        if available_moves:
            if self.verbose:
                print("Evaluating and scoring all legal moves:")
            
            # Determine if there is at least one damaging move in the pool
            has_damaging_move = any(m.base_power > 0 for m in available_moves)
            
            scored_moves = {}
            for move in available_moves:
                base_power = move.base_power
                
                if base_power > 0:
                    score = float(base_power)
                    # Prefer damaging moves over status moves
                    if has_damaging_move:
                        score += 1000.0
                    
                    # STAB Bonus: Add +20 if move.type matches active Pokémon's types
                    active_types = battle.active_pokemon.types if battle.active_pokemon else []
                    if move.type and move.type in active_types:
                        score += 20.0
                        
                    # Type Effectiveness
                    if opponent:
                        if hasattr(opponent, "damage_multiplier"):
                            multiplier = opponent.damage_multiplier(move)
                            score *= multiplier
                else:
                    score = 10.0
                
                acc = move.accuracy
                if isinstance(acc, (int, float)):
                    score *= acc
                else:
                    score *= 1.0
                
                scored_moves[move] = score
                
                if self.verbose:
                    print(
                        f"  - Move: {move.id} "
                        f"| Base Power: {move.base_power} "
                        f"| Type: {move.type} "
                        f"| Category: {move.category} "
                        f"| Accuracy: {move.accuracy} "
                        f"| Score: {score:.2f}"
                    )
                
            if scored_moves:
                best_move = max(scored_moves, key=scored_moves.get)
                if self.verbose:
                    print(f"Selected action: {best_move.id} (Score: {scored_moves[best_move]:.2f})")
                return self.create_order(best_move)

        if battle.available_switches:
            selected_switch = random.choice(battle.available_switches)
            if self.verbose:
                print(f"No available moves. Selected switch: {selected_switch.species}")
            return self.create_order(selected_switch)
            
        if self.verbose:
            print("Fallback: selecting random move/switch.")
        return self.choose_random_move(battle)

async def main():
    bot = RuleBasedPlayer(
        account_configuration=AccountConfiguration("RuleBasedBot_1", None)
    )

    print("Rule-based bot is starting and waiting for challenges...")
    await bot.accept_challenges(None, n_challenges=1)
    print("Battle finished!")

if __name__ == "__main__":
    asyncio.run(main())
