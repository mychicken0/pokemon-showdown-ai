import asyncio
from poke_env import AccountConfiguration
from bot_rule_based import RuleBasedPlayer
from bot_damage_aware import DamageAwarePlayer
from bot_switch_aware import SwitchAwarePlayer
from battle_logger import BattleLogger

N_BATTLES = 100

async def run_benchmark_a(logger):
    """Benchmark A: SwitchAwarePlayer vs DamageAwarePlayer (old)"""
    print("\n-----------------------------------------------------------")
    print("RUNNING BENCHMARK A: SwitchAwarePlayer vs DamageAwarePlayer")
    print("-----------------------------------------------------------")
    
    switch_aware = SwitchAwarePlayer(
        account_configuration=AccountConfiguration("SwitchAwareBotA", None),
        verbose=False,
        logger=logger,
        max_concurrent_battles=10
    )
    damage_aware = DamageAwarePlayer(
        account_configuration=AccountConfiguration("DamageAwareOppA", None),
        verbose=False,
        max_concurrent_battles=10
    )
    
    print(f"Pitting SwitchAwarePlayer against DamageAwarePlayer for {N_BATTLES} battles...")
    await switch_aware.battle_against(damage_aware, n_battles=N_BATTLES)
    
    # Post-process and save battle logs
    for battle_tag, battle in switch_aware.battles.items():
        tag = getattr(battle, "battle_tag", battle_tag)
        won = getattr(battle, "won", False)
        turn = getattr(battle, "turn", 0)
        winner = getattr(battle, "winner", None)
        if winner is None:
            winner = "SwitchAwareBotA" if won else "DamageAwareOppA"
        logger.save_battle(
            battle_tag=tag,
            winner=winner,
            won=won,
            total_turns=turn
        )
    
    finished = switch_aware.n_finished_battles
    wins = switch_aware.n_won_battles
    losses = damage_aware.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0
    
    print("\n================ Benchmark A Results ================")
    print(f"Total battles finished: {finished}")
    print(f"SwitchAwarePlayer wins: {wins}")
    print(f"DamageAwarePlayer wins: {losses}")
    print(f"SwitchAwarePlayer Win Rate: {win_rate:.2f}%")
    print("=====================================================")

async def run_benchmark_b(logger):
    """Benchmark B: SwitchAwarePlayer vs RuleBasedPlayer"""
    print("\n-----------------------------------------------------------")
    print("RUNNING BENCHMARK B: SwitchAwarePlayer vs RuleBasedPlayer")
    print("-----------------------------------------------------------")
    
    switch_aware = SwitchAwarePlayer(
        account_configuration=AccountConfiguration("SwitchAwareBotB", None),
        verbose=False,
        logger=logger,
        max_concurrent_battles=10
    )
    rule_based = RuleBasedPlayer(
        account_configuration=AccountConfiguration("RuleBasedOppB", None),
        verbose=False,
        max_concurrent_battles=10
    )
    
    print(f"Pitting SwitchAwarePlayer against RuleBasedPlayer for {N_BATTLES} battles...")
    await switch_aware.battle_against(rule_based, n_battles=N_BATTLES)
    
    # Post-process and save battle logs
    for battle_tag, battle in switch_aware.battles.items():
        tag = getattr(battle, "battle_tag", battle_tag)
        won = getattr(battle, "won", False)
        turn = getattr(battle, "turn", 0)
        winner = getattr(battle, "winner", None)
        if winner is None:
            winner = "SwitchAwareBotB" if won else "RuleBasedOppB"
        logger.save_battle(
            battle_tag=tag,
            winner=winner,
            won=won,
            total_turns=turn
        )
    
    finished = switch_aware.n_finished_battles
    wins = switch_aware.n_won_battles
    losses = rule_based.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0
    
    print("\n================ Benchmark B Results ================")
    print(f"Total battles finished: {finished}")
    print(f"SwitchAwarePlayer wins: {wins}")
    print(f"RuleBasedPlayer wins: {losses}")
    print(f"SwitchAwarePlayer Win Rate: {win_rate:.2f}%")
    print("=====================================================")

async def main():
    # Initialize BattleLogger (reset=True clears any old logs)
    logger = BattleLogger(filepath="logs/battle_results.jsonl", reset=True)
    
    # Execute benchmarks sequentially using the same logger
    await run_benchmark_a(logger)
    await run_benchmark_b(logger)

if __name__ == "__main__":
    asyncio.run(main())
