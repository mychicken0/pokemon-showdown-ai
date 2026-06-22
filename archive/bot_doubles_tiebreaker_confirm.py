#!/usr/bin/env python3
"""
bot_doubles_tiebreaker_confirm.py

Robust 500-battle confirmation benchmark for gated threat tiebreaker variants.
Tests 8 variants vs DoublesBasicAwarePlayer with max_concurrent_battles=10.
Saves results to logs/doubles_tiebreaker_confirm.csv.

Variant list:
1. full_phase2                   - baseline (tiebreaker disabled)
2. threat_tiebreaker_5           - weight=5.0,  gap=80.0
3. threat_tiebreaker_10          - weight=10.0, gap=80.0
4. threat_tiebreaker_15          - weight=15.0, gap=80.0
5. threat_tiebreaker_10_gap_40   - weight=10.0, gap=40.0
6. threat_tiebreaker_10_gap_60   - weight=10.0, gap=60.0
7. threat_tiebreaker_10_repeat   - weight=10.0, gap=80.0 (noise/repeat check, same as #3)
8. threat_tiebreaker_10_gap_120  - weight=10.0, gap=120.0
"""
import asyncio
import csv
import os
import random
from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer


async def run_variant(variant_name: str, config: DoublesDamageAwareConfig,
                      n_battles: int = 500, max_concurrent: int = 10) -> dict:
    suffix = random.randint(1000, 9999)
    player_user = f"TC_{variant_name[:10]}_{suffix}"
    opp_user = f"TCOpp_{suffix}"

    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(player_user, None),
        verbose=False,
        config=config,
        max_concurrent_battles=max_concurrent
    )
    opponent = DoublesBasicAwarePlayer(
        account_configuration=AccountConfiguration(opp_user, None),
        verbose=False,
        max_concurrent_battles=max_concurrent
    )

    print(f"\nStarting variant: {variant_name} ({n_battles} battles)...")
    await player.battle_against(opponent, n_battles=n_battles)

    finished = player.n_finished_battles
    wins = player.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0
    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0

    avg_protect = player.total_protect_count / finished if finished > 0 else 0
    avg_fake_out = player.total_fake_out_count / finished if finished > 0 else 0
    avg_spread = player.total_spread_count / finished if finished > 0 else 0
    avg_focus_fire = player.total_focus_fire_count / finished if finished > 0 else 0

    total_tiebreaker = sum(player.tiebreaker_activations_by_battle.values())
    activations_per_battle = total_tiebreaker / finished if finished > 0 else 0.0

    print(f"=== Results: {variant_name} ===")
    print(f"Win Rate              : {win_rate:.2f}% ({wins}/{finished})")
    print(f"Avg Turns             : {avg_turns:.2f}")
    print(f"Avg Protect           : {avg_protect:.2f}")
    print(f"Avg Fake Out          : {avg_fake_out:.2f}")
    print(f"Avg Spread            : {avg_spread:.2f}")
    print(f"Avg Focus-Fire        : {avg_focus_fire:.2f}")
    print(f"Tiebreaker Total      : {total_tiebreaker}")
    print(f"Tiebreaker/Battle     : {activations_per_battle:.2f}")
    if activations_per_battle > 8.0:
        print(f"  WARNING: Tiebreaker activations/battle ({activations_per_battle:.2f}) > 8.0 — gate may be too loose!")
    print("=================================")

    return {
        "variant": variant_name,
        "win_rate": win_rate,
        "wins": wins,
        "finished": finished,
        "avg_turns": avg_turns,
        "protect_usage": avg_protect,
        "fake_out_usage": avg_fake_out,
        "spread_usage": avg_spread,
        "focus_fire_turns": avg_focus_fire,
        "total_tiebreaker_activations": total_tiebreaker,
        "tiebreaker_per_battle": activations_per_battle,
    }


async def main():
    variants = {
        "full_phase2": DoublesDamageAwareConfig(
            enable_threat_tiebreaker=False,
            enable_threat_scoring=False,
            enable_boosted_threat_override=False,
            enable_fakeout_threat_targeting=False,
            enable_protect_threat_refinement=False,
        ),
        "threat_tiebreaker_5": DoublesDamageAwareConfig(
            enable_threat_tiebreaker=True,
            threat_tiebreaker_weight=5.0,
            threat_tiebreaker_score_gap=80.0,
        ),
        "threat_tiebreaker_10": DoublesDamageAwareConfig(
            enable_threat_tiebreaker=True,
            threat_tiebreaker_weight=10.0,
            threat_tiebreaker_score_gap=80.0,
        ),
        "threat_tiebreaker_15": DoublesDamageAwareConfig(
            enable_threat_tiebreaker=True,
            threat_tiebreaker_weight=15.0,
            threat_tiebreaker_score_gap=80.0,
        ),
        "threat_tiebreaker_10_gap_40": DoublesDamageAwareConfig(
            enable_threat_tiebreaker=True,
            threat_tiebreaker_weight=10.0,
            threat_tiebreaker_score_gap=40.0,
        ),
        "threat_tiebreaker_10_gap_60": DoublesDamageAwareConfig(
            enable_threat_tiebreaker=True,
            threat_tiebreaker_weight=10.0,
            threat_tiebreaker_score_gap=60.0,
        ),
        # Intentional repeat of threat_tiebreaker_10 for noise/variance check
        "threat_tiebreaker_10_repeat": DoublesDamageAwareConfig(
            enable_threat_tiebreaker=True,
            threat_tiebreaker_weight=10.0,
            threat_tiebreaker_score_gap=80.0,
        ),
        "threat_tiebreaker_10_gap_120": DoublesDamageAwareConfig(
            enable_threat_tiebreaker=True,
            threat_tiebreaker_weight=10.0,
            threat_tiebreaker_score_gap=120.0,
        ),
    }

    results = []
    for name, config in variants.items():
        res = await run_variant(name, config, n_battles=500, max_concurrent=10)
        results.append(res)

    os.makedirs("logs", exist_ok=True)
    csv_file = "logs/doubles_tiebreaker_confirm.csv"
    fields = [
        "variant", "win_rate", "wins", "finished", "avg_turns",
        "protect_usage", "fake_out_usage", "spread_usage", "focus_fire_turns",
        "total_tiebreaker_activations", "tiebreaker_per_battle",
    ]
    with open(csv_file, mode="w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for res in results:
            writer.writerow(res)

    print(f"\nAll benchmarks finished! Results saved to {csv_file}")


if __name__ == "__main__":
    asyncio.run(main())
