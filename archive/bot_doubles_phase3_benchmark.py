#!/usr/bin/env python3
import asyncio
import random
from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer

async def run_matchup(player_name, opponent, player_config, title, n_battles=300):
    rand_suffix = random.randint(1000, 9999)
    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(f"P3_{player_name}_{rand_suffix}", None),
        verbose=False,
        config=player_config,
        max_concurrent_battles=5
    )
    
    opp_username = f"Opp_{rand_suffix}"
    print(f"\nStarting matchup: {title} ({n_battles} battles)...")
    
    if opponent == "basic":
        opp_player = DoublesBasicAwarePlayer(
            account_configuration=AccountConfiguration(opp_username, None),
            verbose=False,
            max_concurrent_battles=5
        )
    else:
        opp_player = DoublesDamageAwarePlayer(
            account_configuration=AccountConfiguration(opp_username, None),
            verbose=False,
            config=DoublesDamageAwareConfig(enable_threat_scoring=False),
            max_concurrent_battles=5
        )
        
    await player.battle_against(opp_player, n_battles=n_battles)
    
    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opp_player.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0
    
    turns = [battle.turn for battle in player.battles.values() if battle.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0
    
    avg_protect = player.total_protect_count / finished if finished > 0 else 0
    avg_fake_out = player.total_fake_out_count / finished if finished > 0 else 0
    avg_spread = player.total_spread_count / finished if finished > 0 else 0
    avg_focus_fire = player.total_focus_fire_count / finished if finished > 0 else 0
    avg_threat_contrib = player.total_threat_contribution / finished if finished > 0 else 0
    
    print(f"\n=== Results: {title} ===")
    print(f"Total battles finished: {finished}")
    print(f"Player wins (wins/losses): {wins}/{losses}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Average turns per battle: {avg_turns:.2f}")
    print(f"Average Protect usage per battle: {avg_protect:.2f}")
    print(f"Average Fake Out usage per battle: {avg_fake_out:.2f}")
    print(f"Average Spread moves used per battle: {avg_spread:.2f}")
    print(f"Average Focus-Fire turns per battle: {avg_focus_fire:.2f}")
    if player_config.enable_threat_scoring:
        print(f"Average Threat-Targeting Contribution: {avg_threat_contrib:.2f}")
    print("=========================================")

async def main():
    print("Starting Doubles Phase 3 Benchmark Suite...")
    
    phase3_config = DoublesDamageAwareConfig(enable_threat_scoring=True)
    
    # A) Phase 3 vs DoublesBasicAwarePlayer (300 battles)
    await run_matchup(
        player_name="P3Bas",
        opponent="basic",
        player_config=phase3_config,
        title="DoublesDamageAware (Phase 3) vs DoublesBasicAwarePlayer",
        n_battles=300
    )
    
    # B) Phase 3 vs full_phase2 (300 battles)
    await run_matchup(
        player_name="P3P2",
        opponent="phase2",
        player_config=phase3_config,
        title="DoublesDamageAware (Phase 3) vs DoublesDamageAware (full_phase2)",
        n_battles=300
    )

if __name__ == "__main__":
    asyncio.run(main())
