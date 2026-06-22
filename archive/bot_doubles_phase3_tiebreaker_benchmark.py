#!/usr/bin/env python3
import asyncio
import csv
import os
import random
from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer

async def run_variant(variant_name, config, n_battles=300, max_concurrent=10):
    # Use randomized names to avoid websocket login collisions
    player_user = f"P3_{variant_name[:10]}_{random.randint(1000, 9999)}"
    opp_user = f"P3Opp_{random.randint(1000, 9999)}"

    # Initialize players
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

    print(f"\nStarting benchmark for variant: {variant_name} ({n_battles} battles)...")
    await player.battle_against(opponent, n_battles=n_battles)

    finished = player.n_finished_battles
    wins = player.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0

    turns = [battle.turn for battle in player.battles.values() if battle.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0

    avg_protect = player.total_protect_count / finished if finished > 0 else 0
    avg_fake_out = player.total_fake_out_count / finished if finished > 0 else 0
    avg_spread = player.total_spread_count / finished if finished > 0 else 0
    avg_focus_fire = player.total_focus_fire_count / finished if finished > 0 else 0
    
    # Calculate activations using the dictionary per battle tag
    total_tiebreaker_activations = sum(player.tiebreaker_activations_by_battle.values())
    total_boosted_override_activations = sum(player.boosted_override_activations_by_battle.values())
    
    avg_tiebreaker = total_tiebreaker_activations / finished if finished > 0 else 0
    avg_boosted_override = total_boosted_override_activations / finished if finished > 0 else 0

    print(f"=== Results: {variant_name} ===")
    print(f"Win Rate: {win_rate:.2f}% ({wins}/{finished})")
    print(f"Avg Turns: {avg_turns:.2f}")
    print(f"Avg Protect: {avg_protect:.2f}")
    print(f"Avg Fake Out: {avg_fake_out:.2f}")
    print(f"Avg Spread: {avg_spread:.2f}")
    print(f"Avg Focus-Fire: {avg_focus_fire:.2f}")
    print(f"Avg Tiebreaker: {avg_tiebreaker:.2f} (Total: {total_tiebreaker_activations})")
    print(f"Avg Boosted Override: {avg_boosted_override:.2f} (Total: {total_boosted_override_activations})")
    print("=================================")

    return {
        "variant": variant_name,
        "win_rate": win_rate,
        "avg_turns": avg_turns,
        "protect_usage": avg_protect,
        "fake_out_usage": avg_fake_out,
        "spread_usage": avg_spread,
        "focus_fire_turns": avg_focus_fire,
        "tiebreaker_activations": total_tiebreaker_activations,
        "boosted_override_activations": total_boosted_override_activations
    }

async def main():
    variants = {
        "full_phase2": DoublesDamageAwareConfig(
            enable_threat_scoring=False,
            enable_threat_tiebreaker=False,
            enable_boosted_threat_override=False,
            enable_fakeout_threat_targeting=False,
            enable_protect_threat_refinement=False
        ),
        "threat_tiebreaker_10": DoublesDamageAwareConfig(
            enable_threat_tiebreaker=True,
            threat_tiebreaker_weight=10.0
        ),
        "threat_tiebreaker_15": DoublesDamageAwareConfig(
            enable_threat_tiebreaker=True,
            threat_tiebreaker_weight=15.0
        ),
        "threat_tiebreaker_25": DoublesDamageAwareConfig(
            enable_threat_tiebreaker=True,
            threat_tiebreaker_weight=25.0
        ),
        "threat_tiebreaker_15_with_boost_override": DoublesDamageAwareConfig(
            enable_threat_tiebreaker=True,
            threat_tiebreaker_weight=15.0,
            enable_boosted_threat_override=True
        ),
        "fakeout_threat_only": DoublesDamageAwareConfig(
            enable_fakeout_threat_targeting=True
        ),
        "protect_threat_only": DoublesDamageAwareConfig(
            enable_protect_threat_refinement=True
        )
    }

    results = []
    for name, config in variants.items():
        res = await run_variant(name, config, n_battles=300, max_concurrent=10)
        results.append(res)

    # Ensure logs folder exists
    os.makedirs("logs", exist_ok=True)
    
    csv_file = "logs/doubles_phase3_tiebreaker.csv"
    fields = [
        "variant", "win_rate", "avg_turns", "protect_usage", "fake_out_usage",
        "spread_usage", "focus_fire_turns", "tiebreaker_activations", "boosted_override_activations"
    ]
    
    with open(csv_file, mode="w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for res in results:
            writer.writerow(res)
            
    print(f"\nAll benchmarks finished! Saved results to {csv_file}")

if __name__ == "__main__":
    asyncio.run(main())
