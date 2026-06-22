#!/usr/bin/env python3
"""
bot_doubles_ability_aware_benchmark.py

Runs benchmarks for the Ability-Aware Doubles Player:
- Run A: ability_on vs DoublesBasicAwarePlayer (300 battles)
- Run B: ability_off vs DoublesBasicAwarePlayer (300 battles)
- Run C: ability_on vs ability_off (300 battles)
- Run D: ability_on vs RandomPlayer (100 battles)

Saves results to logs/doubles_ability_aware_benchmark.csv.
"""
import asyncio
import csv
import os
import random
from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer
from poke_env.player import RandomPlayer


async def run_benchmark_run(run_name: str, player: DoublesDamageAwarePlayer, opponent, n_battles: int):
    print(f"\nStarting Run: {run_name} ({n_battles} battles)...")
    
    # Reset metrics per battle tag
    player.ability_blocks_avoided_by_battle = {}
    player.ability_absorbs_avoided_by_battle = {}
    player.ability_redirects_avoided_by_battle = {}
    player.ally_safe_spreads_by_battle = {}
    player.ability_multipliers_applied_by_battle = {}

    await player.battle_against(opponent, n_battles=n_battles)

    finished = player.n_finished_battles
    wins = player.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0
    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0

    blocks = player.total_ability_blocks_avoided
    absorbs = player.total_ability_absorbs_avoided
    redirects = player.total_ability_redirects_avoided
    spreads = player.total_ally_safe_spreads
    multipliers = player.total_ability_multipliers_applied

    print(f"=== Results: {run_name} ===")
    print(f"Win Rate                 : {win_rate:.2f}% ({wins}/{finished})")
    print(f"Avg Turns                : {avg_turns:.2f}")
    print(f"Ability Blocks Avoided   : {blocks}")
    print(f"Absorbs Avoided          : {absorbs}")
    print(f"Redirections Avoided     : {redirects}")
    print(f"Ally-Safe Spreads Used   : {spreads}")
    print(f"Ability Multipliers      : {multipliers}")
    print("================================")

    return {
        "run": run_name,
        "win_rate": win_rate,
        "wins": wins,
        "finished": finished,
        "avg_turns": avg_turns,
        "blocks_avoided": blocks,
        "absorbs_avoided": absorbs,
        "redirects_avoided": redirects,
        "ally_safe_spreads_used": spreads,
        "multipliers_applied": multipliers
    }


async def main():
    suffix = random.randint(1000, 9999)
    results = []

    # Run A: ability_on vs DoublesBasicAwarePlayer (300 battles)
    config_a = DoublesDamageAwareConfig(enable_ability_awareness=True)
    player_a = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"AbOnA_{suffix}", None),
        verbose=False,
        config=config_a,
        max_concurrent_battles=10
    )
    opponent_a = DoublesBasicAwarePlayer(
        account_configuration=AccountConfiguration(f"AbBasicA_{suffix}", None),
        verbose=False,
        max_concurrent_battles=10
    )
    res_a = await run_benchmark_run("ability_on vs Basic", player_a, opponent_a, 300)
    results.append(res_a)

    # Run B: ability_off vs DoublesBasicAwarePlayer (300 battles)
    config_b = DoublesDamageAwareConfig(enable_ability_awareness=False)
    player_b = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"AbOffB_{suffix}", None),
        verbose=False,
        config=config_b,
        max_concurrent_battles=10
    )
    opponent_b = DoublesBasicAwarePlayer(
        account_configuration=AccountConfiguration(f"AbBasicB_{suffix}", None),
        verbose=False,
        max_concurrent_battles=10
    )
    res_b = await run_benchmark_run("ability_off vs Basic", player_b, opponent_b, 300)
    results.append(res_b)

    # Run C: ability_on vs ability_off (300 battles)
    config_c_p = DoublesDamageAwareConfig(enable_ability_awareness=True)
    config_c_o = DoublesDamageAwareConfig(enable_ability_awareness=False)
    player_c = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"AbOnC_{suffix}", None),
        verbose=False,
        config=config_c_p,
        max_concurrent_battles=10
    )
    opponent_c = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"AbOffC_{suffix}", None),
        verbose=False,
        config=config_c_o,
        max_concurrent_battles=10
    )
    res_c = await run_benchmark_run("ability_on vs ability_off", player_c, opponent_c, 300)
    results.append(res_c)

    # Run D: ability_on vs RandomPlayer (100 battles)
    config_d = DoublesDamageAwareConfig(enable_ability_awareness=True)
    player_d = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"AbOnD_{suffix}", None),
        verbose=False,
        config=config_d,
        max_concurrent_battles=10
    )
    opponent_d = RandomPlayer(
        account_configuration=AccountConfiguration(f"AbRandD_{suffix}", None),
        battle_format="gen9randomdoublesbattle",
        max_concurrent_battles=10
    )
    res_d = await run_benchmark_run("ability_on vs Random", player_d, opponent_d, 100)
    results.append(res_d)

    os.makedirs("logs", exist_ok=True)
    csv_file = "logs/doubles_ability_aware_benchmark.csv"
    fields = [
        "run", "win_rate", "wins", "finished", "avg_turns",
        "blocks_avoided", "absorbs_avoided", "redirects_avoided",
        "ally_safe_spreads_used", "multipliers_applied"
    ]
    with open(csv_file, mode="w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for res in results:
            writer.writerow(res)

    print(f"\nAll Phase 4 benchmarks finished! Results saved to {csv_file}")


if __name__ == "__main__":
    asyncio.run(main())
