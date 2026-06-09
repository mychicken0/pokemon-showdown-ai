#!/usr/bin/env python3
import asyncio
import random
from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer

# Define the variants to test against DoublesBasicAwarePlayer
VARIANTS = {
    "full_phase2": DoublesDamageAwareConfig(enable_threat_scoring=False),
    "phase3_threat_scoring": DoublesDamageAwareConfig(enable_threat_scoring=True),
    "phase3_no_speed_threat": DoublesDamageAwareConfig(enable_threat_scoring=True, enable_speed_threat=False),
    "phase3_no_spread_threat": DoublesDamageAwareConfig(enable_threat_scoring=True, enable_spread_threat=False),
    "phase3_no_setup_threat": DoublesDamageAwareConfig(enable_threat_scoring=True, enable_setup_threat=False),
    "phase3_low_threat_weight_20": DoublesDamageAwareConfig(enable_threat_scoring=True, threat_targeting_weight=20.0),
    "phase3_high_threat_weight_80": DoublesDamageAwareConfig(enable_threat_scoring=True, threat_targeting_weight=80.0),
}

async def run_variant(name, config, n_battles=100):
    rand_suffix = random.randint(1000, 9999)
    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"P3Abl_{rand_suffix}", None),
        verbose=False,
        config=config,
        max_concurrent_battles=5
    )
    
    opponent = DoublesBasicAwarePlayer(
        account_configuration=AccountConfiguration(f"Basic_{rand_suffix}", None),
        verbose=False,
        max_concurrent_battles=5
    )
    
    print(f"\nRunning Phase 3 variant '{name}' against DoublesBasicAwarePlayer for {n_battles} battles...")
    await player.battle_against(opponent, n_battles=n_battles)
    
    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0
    
    turns = [battle.turn for battle in player.battles.values() if battle.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0
    
    avg_protect = player.total_protect_count / finished if finished > 0 else 0
    avg_fake_out = player.total_fake_out_count / finished if finished > 0 else 0
    avg_spread = player.total_spread_count / finished if finished > 0 else 0
    avg_focus_fire = player.total_focus_fire_count / finished if finished > 0 else 0
    avg_threat_contrib = player.total_threat_contribution / finished if finished > 0 else 0
    
    print(f"[{name}] Wins/Losses: {wins}/{losses} | Win Rate: {win_rate:.2f}% | Avg Turns: {avg_turns:.2f} | Protect: {avg_protect:.2f} | FakeOut: {avg_fake_out:.2f} | Spread: {avg_spread:.2f} | FocusFire: {avg_focus_fire:.2f} | ThreatContrib: {avg_threat_contrib:.2f}")
    
    return {
        "variant_name": name,
        "win_rate": win_rate,
        "wins": wins,
        "losses": losses,
        "avg_turns": avg_turns,
        "avg_protect": avg_protect,
        "avg_fake_out": avg_fake_out,
        "avg_spread": avg_spread,
        "avg_focus_fire": avg_focus_fire,
        "avg_threat_contribution": avg_threat_contrib
    }

async def main():
    print("Starting Doubles Phase 3 Ablation Testing...")
    
    results = []
    for name, config in VARIANTS.items():
        res = await run_variant(name, config, n_battles=100)
        results.append(res)
        
    print("\n=== Phase 3 Ablation Summary ===")
    print("Variant Name                 | Win Rate | Avg Turns | Protect | FakeOut | Spread | FocusFire | ThreatContrib")
    print("-" * 110)
    for res in results:
        print(f"{res['variant_name']:28s} | {res['win_rate']:7.2f}% | {res['avg_turns']:9.2f} | {res['avg_protect']:7.2f} | {res['avg_fake_out']:7.2f} | {res['avg_spread']:6.2f} | {res['avg_focus_fire']:9.2f} | {res['avg_threat_contribution']:13.2f}")
    print("=================================")

if __name__ == "__main__":
    asyncio.run(main())
