import asyncio
from poke_env import AccountConfiguration
from bot_rule_based import RuleBasedPlayer
from bot_damage_aware import DamageAwarePlayer
from bot_switch_aware import SwitchAwarePlayer
from battle_logger import BattleLogger

N_BATTLES = 300

async def run_extended_benchmark(opp_class, opp_name_prefix, opp_display_name, logger, benchmark_label):
    print("\n" + "=" * 65)
    print(f"RUNNING EXTENDED BENCHMARK: SwitchAwarePlayer vs {opp_display_name}")
    print(f"Total Battles: {N_BATTLES} | Max Concurrency: 10")
    print("=" * 65)
    
    # Unique usernames for every player in the benchmark run
    switch_aware = SwitchAwarePlayer(
        account_configuration=AccountConfiguration(f"SwAwareBot{opp_name_prefix}", None),
        verbose=False,
        logger=logger,
        max_concurrent_battles=10
    )
    opponent_bot = opp_class(
        account_configuration=AccountConfiguration(f"{opp_name_prefix}Opp", None),
        verbose=False,
        max_concurrent_battles=10
    )
    
    print(f"Pitting SwitchAwarePlayer against {opp_display_name}...")
    await switch_aware.battle_against(opponent_bot, n_battles=N_BATTLES)
    
    total_turns_all = 0
    
    # Splits based on ANY switch (both forced and strategic)
    any_switched_wins = 0
    any_switched_total = 0
    any_never_switched_wins = 0
    any_never_switched_total = 0
    
    # Splits based on STRATEGIC switch only (excluding forced fainted switches)
    strat_switched_wins = 0
    strat_switched_total = 0
    strat_never_switched_wins = 0
    strat_never_switched_total = 0
    
    total_switches_count = 0
    total_strat_switches_count = 0
    
    # Post-process and save battle logs
    for battle_tag, battle in switch_aware.battles.items():
        tag = getattr(battle, "battle_tag", battle_tag)
        won = getattr(battle, "won", False)
        turn = getattr(battle, "turn", 0)
        winner = getattr(battle, "winner", None)
        if winner is None:
            winner = f"SwAwareBot{opp_name_prefix}" if won else f"{opp_name_prefix}Opp"
            
        total_turns_all += turn
        
        # Save logs to file
        logger.save_battle(
            battle_tag=tag,
            winner=winner,
            won=won,
            total_turns=turn
        )
        
        # Analyze switches from turns_log
        turns = logger.turns_log.get(tag, [])
        
        battle_any_switches = 0
        battle_strat_switches = 0
        
        for t_rec in turns:
            if t_rec.get("selected_action_type") == "switch":
                battle_any_switches += 1
                if not t_rec.get("is_forced_switch", False):
                    battle_strat_switches += 1
                    
        total_switches_count += battle_any_switches
        total_strat_switches_count += battle_strat_switches
        
        # Any switch split
        if battle_any_switches > 0:
            any_switched_total += 1
            if won:
                any_switched_wins += 1
        else:
            any_never_switched_total += 1
            if won:
                any_never_switched_wins += 1
                
        # Strategic switch split
        if battle_strat_switches > 0:
            strat_switched_total += 1
            if won:
                strat_switched_wins += 1
        else:
            strat_never_switched_total += 1
            if won:
                strat_never_switched_wins += 1

    finished = switch_aware.n_finished_battles
    wins = switch_aware.n_won_battles
    losses = opponent_bot.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0
    avg_turns = (total_turns_all / finished) if finished > 0 else 0
    
    # Calculate win rates for splits
    any_switched_wr = (any_switched_wins / any_switched_total) * 100 if any_switched_total > 0 else 0.0
    any_never_switched_wr = (any_never_switched_wins / any_never_switched_total) * 100 if any_never_switched_total > 0 else 0.0
    
    strat_switched_wr = (strat_switched_wins / strat_switched_total) * 100 if strat_switched_total > 0 else 0.0
    strat_never_switched_wr = (strat_never_switched_wins / strat_never_switched_total) * 100 if strat_never_switched_total > 0 else 0.0
    
    print(f"\n================ Extended Benchmark Results: {benchmark_label} ================")
    print(f"Total battles finished: {finished}")
    print(f"SwitchAwarePlayer wins: {wins}")
    print(f"{opp_display_name} wins: {losses}")
    print(f"SwitchAwarePlayer Win Rate: {win_rate:.2f}%")
    print(f"Average turns per battle: {avg_turns:.2f}")
    
    print("\nSwitching Statistics:")
    print(f"  - Total switches executed (including forced): {total_switches_count}")
    print(f"  - Average switches per battle (incl. forced): {total_switches_count / finished:.2f}" if finished > 0 else "0.00")
    print(f"  - Total strategic switches executed: {total_strat_switches_count}")
    print(f"  - Average strategic switches per battle: {total_strat_switches_count / finished:.2f}" if finished > 0 else "0.00")
    
    print("\nWin Rate Splits (Including Forced Switches):")
    print(f"  - Battles with at least 1 switch: {any_switched_total} | Win Rate: {any_switched_wr:.2f}% ({any_switched_wins}/{any_switched_total})")
    print(f"  - Battles with 0 switches:       {any_never_switched_total} | Win Rate: {any_never_switched_wr:.2f}% ({any_never_switched_wins}/{any_never_switched_total})")
    
    print("\nWin Rate Splits (Strategic Switches Only):")
    print(f"  - Battles with at least 1 strategic switch: {strat_switched_total} | Win Rate: {strat_switched_wr:.2f}% ({strat_switched_wins}/{strat_switched_total})")
    print(f"  - Battles with 0 strategic switches:       {strat_never_switched_total} | Win Rate: {strat_never_switched_wr:.2f}% ({strat_never_switched_wins}/{strat_never_switched_total})")
    print("=================================================================\n")

async def main():
    logger = BattleLogger(filepath="logs/battle_results.jsonl", reset=True)
    
    # 1. SwitchAwarePlayer vs DamageAwarePlayer (300 battles)
    await run_extended_benchmark(
        opp_class=DamageAwarePlayer,
        opp_name_prefix="ExDmg4",
        opp_display_name="DamageAwarePlayer",
        logger=logger,
        benchmark_label="SwitchAware vs DamageAware"
    )
    
    # 2. SwitchAwarePlayer vs RuleBasedPlayer (300 battles)
    await run_extended_benchmark(
        opp_class=RuleBasedPlayer,
        opp_name_prefix="ExRl4",
        opp_display_name="RuleBasedPlayer",
        logger=logger,
        benchmark_label="SwitchAware vs RuleBased"
    )

if __name__ == "__main__":
    asyncio.run(main())
