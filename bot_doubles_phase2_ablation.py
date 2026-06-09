#!/usr/bin/env python3
import asyncio
import os
import csv
from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer

# Define the variants to test
VARIANTS = {
    "full_phase2": DoublesDamageAwareConfig(),
    "no_focus_fire_bonus": DoublesDamageAwareConfig(focus_fire_synergy_bonus=0.0),
    "no_hp_targeting_bonus": DoublesDamageAwareConfig(hp_targeting_weight=0.0),
    "old_hp_targeting_weight_30": DoublesDamageAwareConfig(hp_targeting_weight=30.0),
    "old_ko_bonus_250": DoublesDamageAwareConfig(ko_bonus=250.0),
    "no_protect_logic": DoublesDamageAwareConfig(enable_protect=False),
    "no_spread_intelligence": DoublesDamageAwareConfig(enable_spread_intelligence=False),
    "no_fake_out_logic": DoublesDamageAwareConfig(enable_fake_out=False)
}

async def run_variant(name, config, n_battles=100):
    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"Abl_{name[:10]}", None),
        verbose=False,
        config=config,
        max_concurrent_battles=5
    )
    
    opponent = DoublesBasicAwarePlayer(
        account_configuration=AccountConfiguration(f"Abl_Basic_{name[:6]}", None),
        verbose=False,
        max_concurrent_battles=5
    )
    
    print(f"\nRunning variant '{name}' against DoublesBasicAwarePlayer for {n_battles} battles...")
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
    
    print(f"[{name}] Win Rate: {win_rate:.2f}% | Avg Turns: {avg_turns:.2f} | Protect: {avg_protect:.2f} | FakeOut: {avg_fake_out:.2f} | Spread: {avg_spread:.2f} | FocusFire: {avg_focus_fire:.2f}")
    
    return {
        "variant_name": name,
        "win_rate": win_rate,
        "wins": wins,
        "losses": losses,
        "avg_turns": avg_turns,
        "avg_protect": avg_protect,
        "avg_fake_out": avg_fake_out,
        "avg_spread": avg_spread,
        "avg_focus_fire": avg_focus_fire
    }

async def main():
    print("Starting Doubles Phase 2 Ablation Testing...")
    
    results = []
    for name, config in VARIANTS.items():
        res = await run_variant(name, config, n_battles=100)
        results.append(res)
        
    os.makedirs("logs", exist_ok=True)
    csv_file = "logs/doubles_phase2_ablation.csv"
    
    with open(csv_file, mode="w", newline="") as f:
        fieldnames = ["variant_name", "win_rate", "wins", "losses", "avg_turns", "avg_protect", "avg_fake_out", "avg_spread", "avg_focus_fire"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for res in results:
            writer.writerow(res)
            
    print(f"\nAblation results saved to: {csv_file}")

if __name__ == "__main__":
    asyncio.run(main())
