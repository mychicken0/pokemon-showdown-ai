#!/usr/bin/env python3
"""
bot_doubles_verify_full_phase2.py

Verify that full_phase2 default behavior is unchanged after Phase 3 refactoring.
Runs 300 battles vs DoublesBasicAwarePlayer with all threat flags explicitly disabled.
"""
import asyncio
import random
from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer


async def main():
    suffix = random.randint(1000, 9999)
    player_user = f"VerifyFP2_{suffix}"
    opp_user = f"VerifyOpp_{suffix}"

    config = DoublesDamageAwareConfig(
        # full_phase2 core values
        switch_baseline=8.0,
        hp_targeting_weight=80.0,
        ko_bonus=350.0,
        focus_fire_synergy_bonus=80.0,
        protect_score=180.0,
        spread_bonus=50.0,
        ally_hit_penalty=300.0,
        enable_protect=True,
        enable_fake_out=True,
        enable_spread_intelligence=True,
        enable_focus_fire_synergy=True,
        # All Phase 3 threat flags explicitly disabled
        enable_threat_scoring=False,
        enable_threat_tiebreaker=False,
        enable_boosted_threat_override=False,
        enable_fakeout_threat_targeting=False,
        enable_protect_threat_refinement=False,
    )

    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(player_user, None),
        verbose=False,
        config=config,
        max_concurrent_battles=10
    )
    opponent = DoublesBasicAwarePlayer(
        account_configuration=AccountConfiguration(opp_user, None),
        verbose=False,
        max_concurrent_battles=10
    )

    n_battles = 300
    print(f"\nRunning full_phase2 verification: {n_battles} battles vs DoublesBasicAwarePlayer...")
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
    total_boosted = sum(player.boosted_override_activations_by_battle.values())

    print("\n=== Verification Results: full_phase2 (all threat flags OFF) ===")
    print(f"Battles finished : {finished}")
    print(f"Wins             : {wins}")
    print(f"Win Rate         : {win_rate:.2f}%")
    print(f"Avg Turns        : {avg_turns:.2f}")
    print(f"Avg Protect      : {avg_protect:.2f}")
    print(f"Avg Fake Out     : {avg_fake_out:.2f}")
    print(f"Avg Spread       : {avg_spread:.2f}")
    print(f"Avg Focus-Fire   : {avg_focus_fire:.2f}")
    print(f"Tiebreaker Acts  : {total_tiebreaker} (expected: 0)")
    print(f"Boost Override   : {total_boosted} (expected: 0)")
    print("=================================================================")

    if total_tiebreaker != 0 or total_boosted != 0:
        print("WARNING: Threat activations detected when all flags should be OFF!")
    else:
        print("OK: No threat activations detected. full_phase2 behavior is clean.")

    print("\nExpected win rate range: 50-60% (consistent with prior Champion Config results)")


if __name__ == "__main__":
    asyncio.run(main())
