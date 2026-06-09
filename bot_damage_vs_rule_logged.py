import asyncio
from poke_env import AccountConfiguration
from bot_rule_based import RuleBasedPlayer
from bot_damage_aware import DamageAwarePlayer
from battle_logger import BattleLogger

N_BATTLES = 100

async def main():
    # 1. Initialize BattleLogger (reset=True clears any old logs)
    logger = BattleLogger(filepath="logs/battle_results.jsonl", reset=True)

    # 6. Initialize both bots in silent mode (verbose=False)
    # Pass the logger to DamageAwarePlayer
    damage_aware_player = DamageAwarePlayer(
        account_configuration=AccountConfiguration("DamageAwareBot", None),
        verbose=False,
        logger=logger,
        max_concurrent_battles=10
    )
    rule_based_player = RuleBasedPlayer(
        account_configuration=AccountConfiguration("RuleBasedOpponent", None),
        verbose=False,
        max_concurrent_battles=10
    )

    print(f"Starting logged benchmark matchup on the local server...")
    print(f"Pitting DamageAwarePlayer against RuleBasedPlayer for {N_BATTLES} battles...")
    
    # Run the battles concurrently
    await damage_aware_player.battle_against(rule_based_player, n_battles=N_BATTLES)

    # 4 & 6. Post-process and save logs only after battles finish
    total_turns_all = 0
    for battle_tag, battle in damage_aware_player.battles.items():
        # Safe getattr calls for battle fields
        tag = getattr(battle, "battle_tag", battle_tag)
        won = getattr(battle, "won", False)
        turn = getattr(battle, "turn", 0)
        winner = getattr(battle, "winner", None)
        
        # If winner is not available, infer it from battle.won
        if winner is None:
            winner = "DamageAwareBot" if won else "RuleBasedOpponent"
            
        total_turns_all += turn
        
        # Save this battle's log record
        logger.save_battle(
            battle_tag=tag,
            winner=winner,
            won=won,
            total_turns=turn
        )

    # Print final benchmark summary
    finished = damage_aware_player.n_finished_battles
    wins = damage_aware_player.n_won_battles
    losses = rule_based_player.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0
    avg_turns = (total_turns_all / finished) if finished > 0 else 0

    print("\n================ Logged Benchmark Results ================")
    print(f"Total battles finished: {finished}")
    print(f"DamageAwarePlayer wins: {wins}")
    print(f"RuleBasedPlayer wins: {losses}")
    print(f"DamageAwarePlayer Win Rate: {win_rate:.2f}%")
    print(f"Average turns per battle: {avg_turns:.2f}")
    print("==========================================================")
    print("All battle decision records successfully written to: logs/battle_results.jsonl")

if __name__ == "__main__":
    asyncio.run(main())
