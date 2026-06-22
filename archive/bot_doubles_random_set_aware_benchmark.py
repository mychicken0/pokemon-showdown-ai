#!/usr/bin/env python3
"""
bot_doubles_random_set_aware_benchmark.py

Phase 5.2 Benchmark: Random-Set-Aware Scoring Integration.

Runs:
  A) random_set_on vs DoublesBasicAwarePlayer  (300 battles)
  B) random_set_off vs DoublesBasicAwarePlayer (300 battles)
  C) random_set_on vs random_set_off           (300 battles)
  D) random_set_on vs RandomPlayer             (100 battles)

Saves results to logs/doubles_random_set_aware_benchmark.csv.
"""
import asyncio
import csv
import os
import random

from poke_env import AccountConfiguration
from poke_env.player import RandomPlayer
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer


LOGS_DIR = "logs"
OUTPUT_CSV = os.path.join(LOGS_DIR, "doubles_random_set_aware_benchmark.csv")
BATTLE_FORMAT = "gen9randomdoublesbattle"
MAX_CONCURRENT = 10


def make_rs_on_config() -> DoublesDamageAwareConfig:
    return DoublesDamageAwareConfig(enable_random_set_opponent_modeling=True)


def make_rs_off_config() -> DoublesDamageAwareConfig:
    return DoublesDamageAwareConfig(enable_random_set_opponent_modeling=False)


def reset_rs_metrics(player: DoublesDamageAwarePlayer):
    """Reset all Phase 5.2 metrics for a clean run."""
    player.battle_metrics = {}
    player.rs_predictions_used_by_battle = {}
    player.rs_protect_predictions_by_battle = {}
    player.rs_fakeout_predictions_by_battle = {}
    player.rs_priority_predictions_by_battle = {}
    player.rs_spread_predictions_by_battle = {}
    player.rs_setup_predictions_by_battle = {}
    player.rs_speed_control_predictions_by_battle = {}
    player.rs_candidate_predictions_by_battle = {}
    player.rs_selected_predictions_by_battle = {}
    player.rs_score_delta_by_battle = {}
    player.rs_species_found_by_battle = {}
    player.rs_species_missing_by_battle = {}
    # Also reset old meta metrics to avoid interference
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


async def run_benchmark_run(
    run_name: str,
    player: DoublesDamageAwarePlayer,
    opponent,
    n_battles: int,
) -> dict:
    print(f"\nStarting Run: {run_name} ({n_battles} battles)...")
    reset_rs_metrics(player)

    await player.battle_against(opponent, n_battles=n_battles)

    finished = player.n_finished_battles
    wins = player.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0
    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0

    # Phase 5.2 metrics
    used = player.total_rs_predictions_used
    protect = player.total_rs_protect_predictions
    fakeout = player.total_rs_fakeout_predictions
    priority = player.total_rs_priority_predictions
    spread = player.total_rs_spread_predictions
    setup = player.total_rs_setup_predictions
    speed_control = player.total_rs_speed_control_predictions
    candidates = player.total_rs_candidate_predictions
    selected = player.total_rs_selected_predictions
    delta = player.total_rs_score_delta
    avg_delta = delta / selected if selected > 0 else 0.0
    avg_used_per_battle = used / finished if finished > 0 else 0.0

    found = player.total_rs_species_found
    missing = player.total_rs_species_missing
    coverage_rate = (found / (found + missing)) * 100 if (found + missing) > 0 else 0.0

    print(f"=== Results: {run_name} ===")
    print(f"Win Rate                  : {win_rate:.2f}% ({wins}/{finished})")
    print(f"Avg Turns                 : {avg_turns:.2f}")
    print(f"Database Coverage Rate    : {coverage_rate:.2f}% (Found: {found}, Missing: {missing})")
    print(f"Candidate Predictions     : {candidates}")
    print(f"Selected Predictions      : {selected}")
    print(f"Predictions Used (total)  : {used}")
    print(f"Avg Used / Battle         : {avg_used_per_battle:.2f}")
    print(f"Avg Score Delta / Pred    : {avg_delta:.2f}")
    print(f"Protect Predictions       : {protect}")
    print(f"Fake Out Predictions      : {fakeout}")
    print(f"Priority Predictions      : {priority}")
    print(f"Spread Predictions        : {spread}")
    print(f"Setup Predictions         : {setup}")
    print(f"Speed Control Predictions : {speed_control}")

    # Warnings
    if avg_used_per_battle > 5:
        print(f"[WARNING] Predictions used ({avg_used_per_battle:.2f}/battle) > 5 threshold!")
    if selected > 0 and (used / selected) < 0.10:
        print(f"[WARNING] Selected prediction rate is very low ({used}/{selected}).")
    if avg_delta > 25:
        print(f"[WARNING] Average score delta ({avg_delta:.2f}) is high!")

    print("================================")

    return {
        "run": run_name,
        "win_rate": round(win_rate, 4),
        "wins": wins,
        "finished": finished,
        "avg_turns": round(avg_turns, 2),
        "database_coverage_rate": round(coverage_rate, 4),
        "candidate_predictions": candidates,
        "selected_predictions": selected,
        "predictions_used": used,
        "avg_used_per_battle": round(avg_used_per_battle, 4),
        "avg_score_delta": round(avg_delta, 4),
        "protect_predictions": protect,
        "fakeout_predictions": fakeout,
        "priority_predictions": priority,
        "spread_predictions": spread,
        "setup_predictions": setup,
        "speed_control_predictions": speed_control,
    }


def save_csv(results: list, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not results:
        return
    fieldnames = list(results[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nResults saved to: {path}")


async def main():
    suffix = random.randint(1000, 9999)
    results = []

    # ----------------------------------------------------------------
    # Run A: random_set_on vs DoublesBasicAwarePlayer (300 battles)
    # ----------------------------------------------------------------
    config_a = make_rs_on_config()
    player_a = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"RSOnA_{suffix}", None),
        battle_format=BATTLE_FORMAT,
        verbose=False,
        config=config_a,
        max_concurrent_battles=MAX_CONCURRENT,
    )
    opponent_a = DoublesBasicAwarePlayer(
        account_configuration=AccountConfiguration(f"RSBasicA_{suffix}", None),
        battle_format=BATTLE_FORMAT,
        verbose=False,
        max_concurrent_battles=MAX_CONCURRENT,
    )
    row_a = await run_benchmark_run("random_set_on vs Basic", player_a, opponent_a, 300)
    results.append(row_a)

    # ----------------------------------------------------------------
    # Run B: random_set_off vs DoublesBasicAwarePlayer (300 battles)
    # ----------------------------------------------------------------
    config_b = make_rs_off_config()
    player_b = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"RSOffB_{suffix}", None),
        battle_format=BATTLE_FORMAT,
        verbose=False,
        config=config_b,
        max_concurrent_battles=MAX_CONCURRENT,
    )
    opponent_b = DoublesBasicAwarePlayer(
        account_configuration=AccountConfiguration(f"RSBasicB_{suffix}", None),
        battle_format=BATTLE_FORMAT,
        verbose=False,
        max_concurrent_battles=MAX_CONCURRENT,
    )
    row_b = await run_benchmark_run("random_set_off vs Basic", player_b, opponent_b, 300)
    results.append(row_b)

    # ----------------------------------------------------------------
    # Run C: random_set_on vs random_set_off (300 battles)
    # ----------------------------------------------------------------
    config_c_on = make_rs_on_config()
    config_c_off = make_rs_off_config()
    player_c_on = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"RSOnC_{suffix}", None),
        battle_format=BATTLE_FORMAT,
        verbose=False,
        config=config_c_on,
        max_concurrent_battles=MAX_CONCURRENT,
    )
    player_c_off = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"RSOffC_{suffix}", None),
        battle_format=BATTLE_FORMAT,
        verbose=False,
        config=config_c_off,
        max_concurrent_battles=MAX_CONCURRENT,
    )
    row_c = await run_benchmark_run("random_set_on vs random_set_off", player_c_on, player_c_off, 300)
    results.append(row_c)

    # ----------------------------------------------------------------
    # Run D: random_set_on vs RandomPlayer (100 battles)
    # ----------------------------------------------------------------
    config_d = make_rs_on_config()
    player_d = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"RSOnD_{suffix}", None),
        battle_format=BATTLE_FORMAT,
        verbose=False,
        config=config_d,
        max_concurrent_battles=MAX_CONCURRENT,
    )
    random_opponent = RandomPlayer(
        account_configuration=AccountConfiguration(f"RSRandD_{suffix}", None),
        battle_format=BATTLE_FORMAT,
        max_concurrent_battles=MAX_CONCURRENT,
    )
    row_d = await run_benchmark_run("random_set_on vs RandomPlayer", player_d, random_opponent, 100)
    results.append(row_d)

    save_csv(results, OUTPUT_CSV)

    # ----------------------------------------------------------------
    # Final summary
    # ----------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  Phase 5.2 Benchmark Summary")
    print("=" * 70)
    for r in results:
        print(f"  {r['run']:<42s}: {r['win_rate']:.2f}% ({r['wins']}/{r['finished']})")
    print("=" * 70)

    # Adoption check
    rate_on_vs_basic = next((r["win_rate"] for r in results if "random_set_on vs Basic" in r["run"]), 0)
    rate_off_vs_basic = next((r["win_rate"] for r in results if "random_set_off vs Basic" in r["run"]), 0)
    rate_on_vs_off = next((r["win_rate"] for r in results if "random_set_on vs random_set_off" in r["run"]), 0)
    rate_on_vs_random = next((r["win_rate"] for r in results if "RandomPlayer" in r["run"]), 0)
    avg_used = next((r["avg_used_per_battle"] for r in results if "random_set_on vs random_set_off" in r["run"]), 0)

    delta_vs_off = rate_on_vs_basic - rate_off_vs_basic
    print()
    print("  Adoption Rule Check:")
    print(f"    random_set_on vs random_set_off    : {rate_on_vs_off:.2f}% (need > 50%)")
    print(f"    delta vs Basic (on-off)            : {delta_vs_off:+.2f}% (need >= +3.00%)")
    print(f"    Safety vs RandomPlayer             : {rate_on_vs_random:.2f}% (need >= 95%)")
    print(f"    Avg predictions/battle             : {avg_used:.2f} (warn if > 5)")

    passes = (
        rate_on_vs_off > 50.0 and
        delta_vs_off >= 3.0 and
        rate_on_vs_random >= 95.0 and
        avg_used <= 5.0
    )
    if passes:
        print()
        print("  ✅ ADOPTION RULE PASSED: Consider enabling random_set_opponent_modeling by default.")
    else:
        print()
        print("  ❌ ADOPTION RULE FAILED: Keep enable_random_set_opponent_modeling=False by default.")

    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
