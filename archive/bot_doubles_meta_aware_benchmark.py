#!/usr/bin/env python3
"""
bot_doubles_meta_aware_benchmark.py

Runs benchmarks for the Meta-Aware Doubles Player:
- Run A: meta_on vs DoublesBasicAwarePlayer (300 battles)
- Run B: meta_off vs DoublesBasicAwarePlayer (300 battles)
- Run C: meta_on vs meta_off (300 battles)
- Run D: meta_on vs RandomPlayer (100 battles)

Saves results to logs/doubles_meta_aware_benchmark.csv.
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
    player.meta_predictions_used_by_battle = {}
    player.meta_protect_predictions_by_battle = {}
    player.meta_fakeout_predictions_by_battle = {}
    player.meta_priority_predictions_by_battle = {}
    player.meta_spread_predictions_by_battle = {}
    player.meta_setup_predictions_by_battle = {}
    player.meta_coverage_predictions_by_battle = {}
    player.meta_ability_soft_penalties_by_battle = {}
    player.meta_species_found_by_battle = {}
    player.meta_species_missing_by_battle = {}
    player.candidate_meta_predictions_by_battle = {}
    player.selected_meta_predictions_by_battle = {}
    player.total_meta_score_delta_by_battle = {}

    await player.battle_against(opponent, n_battles=n_battles)

    finished = player.n_finished_battles
    wins = player.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0
    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0

    # Retrieve metrics
    used = player.total_meta_predictions_used
    protect = player.total_meta_protect_predictions
    fakeout = player.total_meta_fakeout_predictions
    priority = player.total_meta_priority_predictions
    spread = player.total_meta_spread_predictions
    setup = player.total_meta_setup_predictions
    coverage = player.total_meta_coverage_predictions
    soft_abilities = player.total_meta_ability_soft_penalties

    candidates = player.total_candidate_meta_predictions
    selected = player.total_selected_meta_predictions
    delta = player.total_meta_score_delta
    avg_delta = delta / selected if selected > 0 else 0.0

    found = player.total_meta_species_found
    missing = player.total_meta_species_missing
    coverage_rate = (found / (found + missing)) * 100 if (found + missing) > 0 else 0.0

    print(f"=== Results: {run_name} ===")
    print(f"Win Rate                 : {win_rate:.2f}% ({wins}/{finished})")
    print(f"Avg Turns                : {avg_turns:.2f}")
    print(f"Database Coverage Rate   : {coverage_rate:.2f}% (Found: {found}, Missing: {missing})")
    print(f"Candidate Predictions    : {candidates}")
    print(f"Selected Predictions     : {selected}")
    print(f"Predictions Used (Count) : {used}")
    print(f"Avg Score Delta per Pred : {avg_delta:.2f}")
    print(f"Protect Predictions      : {protect}")
    print(f"Fake Out Predictions     : {fakeout}")
    print(f"Priority Predictions     : {priority}")
    print(f"Spread Predictions       : {spread}")
    print(f"Setup Predictions        : {setup}")
    print(f"Coverage Predictions     : {coverage}")
    print(f"Ability Soft Penalties   : {soft_abilities}")
    print("================================")

    return {
        "run": run_name,
        "win_rate": win_rate,
        "wins": wins,
        "finished": finished,
        "avg_turns": avg_turns,
        "database_coverage_rate": coverage_rate,
        "candidate_predictions": candidates,
        "selected_predictions": selected,
        "predictions_used": used,
        "avg_score_delta": avg_delta,
        "protect_predictions": protect,
        "fakeout_predictions": fakeout,
        "priority_predictions": priority,
        "spread_predictions": spread,
        "setup_predictions": setup,
        "coverage_predictions": coverage,
        "ability_soft_penalties": soft_abilities
    }


async def main():
    suffix = random.randint(1000, 9999)
    results = []

    # Run A: meta_on vs DoublesBasicAwarePlayer (300 battles)
    config_a = DoublesDamageAwareConfig(enable_meta_opponent_modeling=True)
    player_a = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"MetaOnA_{suffix}", None),
        verbose=False,
        config=config_a,
        max_concurrent_battles=10
    )
    opponent_a = DoublesBasicAwarePlayer(
        account_configuration=AccountConfiguration(f"MetaBasicA_{suffix}", None),
        verbose=False,
        max_concurrent_battles=10
    )
    res_a = await run_benchmark_run("meta_on vs Basic", player_a, opponent_a, 300)
    results.append(res_a)

    # Run B: meta_off vs DoublesBasicAwarePlayer (300 battles)
    config_b = DoublesDamageAwareConfig(enable_meta_opponent_modeling=False)
    player_b = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"MetaOffB_{suffix}", None),
        verbose=False,
        config=config_b,
        max_concurrent_battles=10
    )
    opponent_b = DoublesBasicAwarePlayer(
        account_configuration=AccountConfiguration(f"MetaBasicB_{suffix}", None),
        verbose=False,
        max_concurrent_battles=10
    )
    res_b = await run_benchmark_run("meta_off vs Basic", player_b, opponent_b, 300)
    results.append(res_b)

    # Run C: meta_on vs meta_off (300 battles)
    config_c_p = DoublesDamageAwareConfig(enable_meta_opponent_modeling=True)
    config_c_o = DoublesDamageAwareConfig(enable_meta_opponent_modeling=False)
    player_c = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"MetaOnC_{suffix}", None),
        verbose=False,
        config=config_c_p,
        max_concurrent_battles=10
    )
    opponent_c = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"MetaOffC_{suffix}", None),
        verbose=False,
        config=config_c_o,
        max_concurrent_battles=10
    )
    res_c = await run_benchmark_run("meta_on vs meta_off", player_c, opponent_c, 300)
    results.append(res_c)

    # Run D: meta_on vs RandomPlayer (100 battles)
    config_d = DoublesDamageAwareConfig(enable_meta_opponent_modeling=True)
    player_d = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"MetaOnD_{suffix}", None),
        verbose=False,
        config=config_d,
        max_concurrent_battles=10
    )
    opponent_d = RandomPlayer(
        account_configuration=AccountConfiguration(f"MetaRandD_{suffix}", None),
        battle_format="gen9randomdoublesbattle",
        max_concurrent_battles=10
    )
    res_d = await run_benchmark_run("meta_on vs Random", player_d, opponent_d, 100)
    results.append(res_d)

    os.makedirs("logs", exist_ok=True)
    csv_file = "logs/doubles_meta_aware_benchmark.csv"
    fields = [
        "run", "win_rate", "wins", "finished", "avg_turns", "database_coverage_rate",
        "candidate_predictions", "selected_predictions", "predictions_used", "avg_score_delta",
        "protect_predictions", "fakeout_predictions", "priority_predictions", "spread_predictions",
        "setup_predictions", "coverage_predictions", "ability_soft_penalties"
    ]
    with open(csv_file, mode="w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for res in results:
            writer.writerow(res)

    print(f"\nAll Phase 5 benchmarks finished! Results saved to {csv_file}")


if __name__ == "__main__":
    asyncio.run(main())
