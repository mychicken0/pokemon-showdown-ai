import asyncio
import csv
import os
import itertools
from poke_env import AccountConfiguration
from bot_damage_aware import DamageAwarePlayer
from bot_switch_aware import SwitchAwarePlayer, SwitchAwareConfig

N_BATTLES = 100
CSV_FILEPATH = "logs/switch_param_sweep.csv"

# Parameter ranges to sweep
SWITCH_MARGINS = [10, 20, 30, 40]
HIGH_SCORE_ATTACK_OVERRIDES = [180, 220, 260]
THREATENED_BEST_MOVE_LIMITS = [80, 120, 160]
SWITCH_PENALTIES = [0, 10, 20, 30]

async def run_single_config(margin, override, limit, penalty, run_index):
    # Unique player names to avoid session clashes
    bot_name = f"SweepBot_{run_index}"
    opp_name = f"SweepOpp_{run_index}"
    
    config = SwitchAwareConfig(
        switch_margin=float(margin),
        high_score_attack_override=float(override),
        threatened_best_move_limit=float(limit),
        switch_penalty=float(penalty)
    )
    
    switch_aware = SwitchAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        config=config,
        verbose=False,
        max_concurrent_battles=10
    )
    damage_aware = DamageAwarePlayer(
        account_configuration=AccountConfiguration(opp_name, None),
        verbose=False,
        max_concurrent_battles=10
    )
    
    # Run the benchmark
    await switch_aware.battle_against(damage_aware, n_battles=N_BATTLES)
    
    finished = switch_aware.n_finished_battles
    wins = switch_aware.n_won_battles
    losses = damage_aware.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0.0
    
    total_turns = sum(battle.turn for battle in switch_aware.battles.values())
    avg_turns = total_turns / finished if finished > 0 else 0.0
    
    strategic_switches = getattr(switch_aware, "strategic_switches", {})
    total_strat_switches = sum(strategic_switches.values())
    avg_strat_switches = total_strat_switches / finished if finished > 0 else 0.0
    
    return wins, losses, win_rate, avg_turns, avg_strat_switches

async def main():
    os.makedirs(os.path.dirname(CSV_FILEPATH), exist_ok=True)
    
    # Check if we should write header (if file doesn't exist or is empty)
    write_header = not os.path.exists(CSV_FILEPATH) or os.path.getsize(CSV_FILEPATH) == 0
    
    # Generate all combinations
    combinations = list(itertools.product(
        SWITCH_MARGINS,
        HIGH_SCORE_ATTACK_OVERRIDES,
        THREATENED_BEST_MOVE_LIMITS,
        SWITCH_PENALTIES
    ))
    
    print(f"Starting parameter sweep: {len(combinations)} configurations total.")
    print(f"Results will be written to: {CSV_FILEPATH}\n")
    
    # Open CSV in append mode to allow resuming/incremental saving
    with open(CSV_FILEPATH, "a", newline="") as csvfile:
        writer = csv.writer(csvfile)
        if write_header:
            writer.writerow([
                "switch_margin",
                "high_score_attack_override",
                "threatened_best_move_limit",
                "switch_penalty",
                "wins",
                "losses",
                "win_rate",
                "average_turns",
                "average_strategic_switches"
            ])
            csvfile.flush()
            
        for idx, (margin, override, limit, penalty) in enumerate(combinations):
            print(f"[{idx+1}/{len(combinations)}] Testing Config: margin={margin}, override={override}, limit={limit}, penalty={penalty}")
            
            wins, losses, win_rate, avg_turns, avg_strat_switches = await run_single_config(
                margin, override, limit, penalty, idx
            )
            
            print(f"  Result: wins={wins}, losses={losses}, win_rate={win_rate:.2f}%, avg_turns={avg_turns:.2f}, avg_switches={avg_strat_switches:.2f}")
            
            # Write to CSV immediately
            writer.writerow([
                margin,
                override,
                limit,
                penalty,
                wins,
                losses,
                win_rate,
                avg_turns,
                avg_strat_switches
            ])
            csvfile.flush()

if __name__ == "__main__":
    asyncio.run(main())
