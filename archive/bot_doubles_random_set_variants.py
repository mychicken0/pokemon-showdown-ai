#!/usr/bin/env python3
"""
bot_doubles_random_set_variants.py

Phase 5.3: Conservative Random-Set Variant Benchmark.

Tests 7 variants of random-set-aware scoring to find one that is conservative
enough to be safe while still adding value.

Variants:
  1. random_set_off          - Baseline full_phase2 (control)
  2. random_set_current      - Phase 5.2 behavior (all rules, defaults)
  3. no_protect_overcommit   - Disable Rule 1 (protect overcommit penalty)
  4. defensive_only          - Only Fake Out + Priority + Spread Protect bonuses; NO targeting bonuses
  5. low_delta               - All rules but halved deltas and ±20 clamp
  6. high_confidence_only    - Stricter per-rule thresholds
  7. close_score_only        - Close-score gating for all targeting bonuses

Each variant is tested against:
  A) DoublesBasicAwarePlayer  (300 battles)
  B) random_set_off           (300 battles)
  C) DoublesSafeRandomPlayer  (100 battles) — sanity check only, NOT for adoption

IMPORTANT:
  - SafeRandom win rate is printed as a sanity check only.
  - It is NOT used in the adoption rule.
  - An adoption rule pass requires:
      (a) head-to-head vs random_set_off > 50%
      (b) delta vs Basic >= +3% compared to random_set_off vs Basic
      (c) avg predictions/battle <= 5

Saves results to logs/doubles_random_set_variants.csv.
"""
import asyncio
import csv
import os
import random

from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer
from bot_doubles_safe_random import DoublesSafeRandomPlayer


LOGS_DIR = "logs"
OUTPUT_CSV = os.path.join(LOGS_DIR, "doubles_random_set_variants.csv")
BATTLE_FORMAT = "gen9randomdoublesbattle"
MAX_CONCURRENT = 10

PREDICTIONS_WARNING_THRESHOLD = 5.0
SELECTED_RATE_WARNING_THRESHOLD = 10.0


# ==========================================================================
# Variant config factories
# ==========================================================================

def make_off_config() -> DoublesDamageAwareConfig:
    """Variant 1: Baseline full_phase2 (no random-set modeling)."""
    return DoublesDamageAwareConfig(enable_random_set_opponent_modeling=False)


def make_current_config() -> DoublesDamageAwareConfig:
    """Variant 2: Phase 5.2 behavior — all rules, default thresholds."""
    return DoublesDamageAwareConfig(enable_random_set_opponent_modeling=True)


def make_no_overcommit_config() -> DoublesDamageAwareConfig:
    """Variant 3: Disable Protect overcommit penalty (Rule 1) only."""
    return DoublesDamageAwareConfig(
        enable_random_set_opponent_modeling=True,
        rs_enable_protect_overcommit_penalty=False,
    )


def make_defensive_only_config() -> DoublesDamageAwareConfig:
    """
    Variant 4: Defensive Protect bonuses only.
    - Allow: Fake Out bonus, Priority bonus (HP < 20%), Spread bonus (HP < 25%)
    - Disable: Protect overcommit penalty, Setup targeting, Speed control bonus
    - Disable: priority KO targeting bonus
    - Tighter spread threshold: 0.25
    """
    return DoublesDamageAwareConfig(
        enable_random_set_opponent_modeling=True,
        rs_enable_protect_overcommit_penalty=False,
        rs_enable_fakeout_bonus=True,
        rs_enable_priority_bonus=True,
        rs_enable_spread_bonus=True,
        rs_enable_setup_targeting=False,
        rs_enable_speed_control_bonus=False,
        rs_spread_hp_threshold=0.25,
    )


def make_low_delta_config() -> DoublesDamageAwareConfig:
    """
    Variant 5: All rules enabled but all deltas halved.
    Clamp reduced to ±20.
    """
    return DoublesDamageAwareConfig(
        enable_random_set_opponent_modeling=True,
        rs_protect_overcommit_delta=5.0,      # was 12
        rs_fakeout_protect_delta=10.0,         # was 18
        rs_priority_protect_delta=10.0,        # was 20 (Protect) / 12 (KO targeting)
        rs_spread_protect_delta=6.0,           # was 12
        rs_setup_targeting_delta=4.0,          # was 8
        rs_speed_control_protect_delta=4.0,    # was 8
        random_set_max_protect_bonus_per_active=15.0,
        random_set_max_score_delta_per_turn=20.0,
    )


def make_high_confidence_config() -> DoublesDamageAwareConfig:
    """
    Variant 6: Stricter per-rule thresholds — only fire predictions on high-confidence species.
    """
    return DoublesDamageAwareConfig(
        enable_random_set_opponent_modeling=True,
        rs_protect_threshold=0.90,
        rs_fakeout_threshold=0.50,
        rs_priority_threshold=0.75,
        rs_spread_threshold=0.75,
        rs_setup_threshold=0.75,
        rs_speed_control_threshold=0.75,
    )


def make_close_score_config() -> DoublesDamageAwareConfig:
    """
    Variant 7: Close-score gating — only apply targeting bonuses when scores are within 30 pts.
    Also disable Protect overcommit penalty and Setup targeting (both were primary offenders).
    """
    return DoublesDamageAwareConfig(
        enable_random_set_opponent_modeling=True,
        rs_enable_protect_overcommit_penalty=False,
        rs_enable_setup_targeting=False,
        rs_close_score_gate_enabled=True,
        rs_close_score_gate_gap=30.0,
    )


VARIANTS = [
    ("random_set_off",          make_off_config()),
    ("random_set_current",      make_current_config()),
    ("no_protect_overcommit",   make_no_overcommit_config()),
    ("defensive_only",          make_defensive_only_config()),
    ("low_delta",               make_low_delta_config()),
    ("high_confidence_only",    make_high_confidence_config()),
    ("close_score_only",        make_close_score_config()),
]


# ==========================================================================
# Metric reset helpers
# ==========================================================================

def reset_rs_metrics(player: DoublesDamageAwarePlayer):
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


# ==========================================================================
# Single run helper
# ==========================================================================

async def run_one(
    run_name: str,
    player: DoublesDamageAwarePlayer,
    opponent,
    n_battles: int,
    is_sanity_check: bool = False,
) -> dict:
    print(f"\n  Running: {run_name} ({'SANITY CHECK ONLY — not used for adoption' if is_sanity_check else str(n_battles) + ' battles'})...")
    reset_rs_metrics(player)

    await player.battle_against(opponent, n_battles=n_battles)

    finished = player.n_finished_battles
    wins = player.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0
    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0

    used = player.total_rs_predictions_used
    candidates = player.total_rs_candidate_predictions
    selected = player.total_rs_selected_predictions
    delta = player.total_rs_score_delta
    avg_used_per_battle = used / finished if finished > 0 else 0.0
    selected_per_battle = selected / finished if finished > 0 else 0.0
    avg_delta = delta / selected if selected > 0 else 0.0
    selected_rate = (used / candidates * 100) if candidates > 0 else 0.0

    protect = player.total_rs_protect_predictions
    fakeout = player.total_rs_fakeout_predictions
    priority = player.total_rs_priority_predictions
    spread = player.total_rs_spread_predictions
    setup = player.total_rs_setup_predictions
    speed_ctrl = player.total_rs_speed_control_predictions

    found = player.total_rs_species_found
    missing = player.total_rs_species_missing
    coverage = (found / (found + missing) * 100) if (found + missing) > 0 else 0.0

    sanity_label = " [SANITY CHECK ONLY]" if is_sanity_check else ""
    print(f"    Win Rate    : {win_rate:.2f}% ({wins}/{finished}){sanity_label}")
    print(f"    Avg Turns   : {avg_turns:.2f}")
    print(f"    DB Coverage : {coverage:.2f}%")
    print(f"    Preds/Battle: {avg_used_per_battle:.2f}  Selected/Battle: {selected_per_battle:.2f}  Selected Rate: {selected_rate:.1f}%")
    print(f"    Avg Delta   : {avg_delta:.2f}")
    print(f"    Protect:{protect}  FakeOut:{fakeout}  Priority:{priority}  Spread:{spread}  Setup:{setup}  SpeedCtrl:{speed_ctrl}")

    if avg_used_per_battle > PREDICTIONS_WARNING_THRESHOLD:
        print(f"    [WARNING] avg_used_per_battle={avg_used_per_battle:.2f} > {PREDICTIONS_WARNING_THRESHOLD}")
    if candidates > 0 and selected_rate < SELECTED_RATE_WARNING_THRESHOLD:
        print(f"    [WARNING] selected_rate={selected_rate:.1f}% below {SELECTED_RATE_WARNING_THRESHOLD}%")

    return {
        "run": run_name,
        "win_rate": round(win_rate, 4),
        "wins": wins,
        "finished": finished,
        "avg_turns": round(avg_turns, 2),
        "db_coverage_rate": round(coverage, 4),
        "candidates": candidates,
        "selected": selected,
        "predictions_used": used,
        "avg_used_per_battle": round(avg_used_per_battle, 4),
        "selected_per_battle": round(selected_per_battle, 4),
        "selected_rate_pct": round(selected_rate, 4),
        "avg_score_delta": round(avg_delta, 4),
        "protect_preds": protect,
        "fakeout_preds": fakeout,
        "priority_preds": priority,
        "spread_preds": spread,
        "setup_preds": setup,
        "speed_ctrl_preds": speed_ctrl,
        "is_sanity_check": is_sanity_check,
    }


def save_csv(results: list, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not results:
        return
    # Exclude non-serializable fields
    save_rows = [{k: v for k, v in r.items() if k != "is_sanity_check"} for r in results]
    fieldnames = list(save_rows[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(save_rows)
    print(f"\nResults saved to: {path}")


# ==========================================================================
# Main benchmark
# ==========================================================================

async def main():
    suffix = random.randint(1000, 9999)
    all_results = []

    # Reference: random_set_off vs Basic to compute deltas
    off_vs_basic_rate = None

    for v_idx, (variant_name, variant_cfg) in enumerate(VARIANTS):
        print(f"\n{'='*70}")
        print(f"  Variant {v_idx + 1}: {variant_name}")
        print(f"{'='*70}")

        # --- Run A: variant vs DoublesBasicAwarePlayer ---
        player_a = DoublesDamageAwarePlayer(
            account_configuration=AccountConfiguration(f"V{v_idx}a_{suffix}", None),
            battle_format=BATTLE_FORMAT,
            verbose=False,
            config=variant_cfg,
            max_concurrent_battles=MAX_CONCURRENT,
        )
        opponent_a = DoublesBasicAwarePlayer(
            account_configuration=AccountConfiguration(f"BasicA{v_idx}_{suffix}", None),
            battle_format=BATTLE_FORMAT,
            verbose=False,
            max_concurrent_battles=MAX_CONCURRENT,
        )
        row_a = await run_one(f"{variant_name} vs Basic", player_a, opponent_a, 300)
        all_results.append(row_a)

        if variant_name == "random_set_off":
            off_vs_basic_rate = row_a["win_rate"]

        # --- Run B: variant vs random_set_off ---
        if variant_name != "random_set_off":
            off_cfg_b = make_off_config()
            player_b_on = DoublesDamageAwarePlayer(
                account_configuration=AccountConfiguration(f"V{v_idx}b_{suffix}", None),
                battle_format=BATTLE_FORMAT,
                verbose=False,
                config=variant_cfg,
                max_concurrent_battles=MAX_CONCURRENT,
            )
            player_b_off = DoublesDamageAwarePlayer(
                account_configuration=AccountConfiguration(f"V{v_idx}bOff_{suffix}", None),
                battle_format=BATTLE_FORMAT,
                verbose=False,
                config=off_cfg_b,
                max_concurrent_battles=MAX_CONCURRENT,
            )
            row_b = await run_one(f"{variant_name} vs random_set_off", player_b_on, player_b_off, 300)
            all_results.append(row_b)
        else:
            # Baseline doesn't need to fight itself
            row_b = {"run": "random_set_off vs random_set_off", "win_rate": 50.0, "wins": 150, "finished": 300,
                     "avg_turns": 0, "db_coverage_rate": 0, "candidates": 0, "selected": 0, "predictions_used": 0,
                     "avg_used_per_battle": 0, "selected_per_battle": 0, "selected_rate_pct": 0, "avg_score_delta": 0,
                     "protect_preds": 0, "fakeout_preds": 0, "priority_preds": 0, "spread_preds": 0,
                     "setup_preds": 0, "speed_ctrl_preds": 0, "is_sanity_check": False}

        # --- Run C: variant vs DoublesSafeRandomPlayer (sanity check only) ---
        player_c = DoublesDamageAwarePlayer(
            account_configuration=AccountConfiguration(f"V{v_idx}c_{suffix}", None),
            battle_format=BATTLE_FORMAT,
            verbose=False,
            config=variant_cfg,
            max_concurrent_battles=MAX_CONCURRENT,
        )
        safe_random = DoublesSafeRandomPlayer(
            account_configuration=AccountConfiguration(f"SafeRandC{v_idx}_{suffix}", None),
            battle_format=BATTLE_FORMAT,
            verbose=False,
            max_concurrent_battles=MAX_CONCURRENT,
        )
        row_c = await run_one(f"{variant_name} vs SafeRandom", player_c, safe_random, 100, is_sanity_check=True)
        all_results.append(row_c)

    save_csv(all_results, OUTPUT_CSV)

    # ==========================================================================
    # Final summary
    # ==========================================================================
    print("\n" + "=" * 70)
    print("  Phase 5.3 Variant Benchmark — Final Summary")
    print("=" * 70)
    print()
    print(f"  {'Variant':<28} {'vs Basic':>9}  {'vs Off':>7}  {'vs SafeRand':>12}  {'Pred/Bat':>8}  {'ΔDelta':>7}")
    print("  " + "-" * 72)

    for v_idx, (variant_name, _) in enumerate(VARIANTS):
        wr_basic = next((r["win_rate"] for r in all_results if r["run"] == f"{variant_name} vs Basic"), 0)
        wr_off   = next((r["win_rate"] for r in all_results if r["run"] == f"{variant_name} vs random_set_off"), 50.0 if variant_name == "random_set_off" else 0)
        wr_safe  = next((r["win_rate"] for r in all_results if r["run"] == f"{variant_name} vs SafeRandom"), 0)
        pred_bat = next((r["avg_used_per_battle"] for r in all_results if r["run"] == f"{variant_name} vs Basic"), 0)
        delta_vs_basic = wr_basic - (off_vs_basic_rate or 0)

        safe_label = f"{wr_safe:.1f}% [sanity]"
        print(f"  {variant_name:<28} {wr_basic:>8.2f}%  {wr_off:>6.2f}%  {safe_label:>15}  {pred_bat:>7.2f}  {delta_vs_basic:>+6.2f}%")

    print()
    print("  Adoption Rule: variant must beat random_set_off > 50.0% AND delta vs Basic >= +3.0%")
    print("  AND avg_used_per_battle <= 5.0")
    print()

    passed_variants = []
    for v_idx, (variant_name, _) in enumerate(VARIANTS):
        if variant_name == "random_set_off":
            continue
        wr_basic = next((r["win_rate"] for r in all_results if r["run"] == f"{variant_name} vs Basic"), 0)
        wr_off   = next((r["win_rate"] for r in all_results if r["run"] == f"{variant_name} vs random_set_off"), 0)
        pred_bat = next((r["avg_used_per_battle"] for r in all_results if r["run"] == f"{variant_name} vs Basic"), 99)
        delta_vs_basic = wr_basic - (off_vs_basic_rate or 0)

        passes = wr_off > 50.0 and delta_vs_basic >= 3.0 and pred_bat <= 5.0
        icon = "✅" if passes else "❌"
        print(f"  {icon} {variant_name:<28}  vs_off={wr_off:.2f}%  delta={delta_vs_basic:+.2f}%  pred/bat={pred_bat:.2f}")
        if passes:
            passed_variants.append((variant_name, wr_off, delta_vs_basic, pred_bat))

    print()
    if passed_variants:
        # Rank by delta vs basic, then vs_off
        passed_variants.sort(key=lambda x: (x[2], x[1]), reverse=True)
        best = passed_variants[0]
        print(f"  ✅ WINNER: {best[0]} — Consider enabling this variant by default.")
        print(f"     vs_off={best[1]:.2f}%  delta={best[2]:+.2f}%  pred/bat={best[3]:.2f}")
    else:
        print("  ❌ No variant passed the adoption rule.")
        # Find the safest (closest to passing)
        candidates_list = []
        for v_idx, (variant_name, _) in enumerate(VARIANTS):
            if variant_name == "random_set_off":
                continue
            wr_basic = next((r["win_rate"] for r in all_results if r["run"] == f"{variant_name} vs Basic"), 0)
            wr_off   = next((r["win_rate"] for r in all_results if r["run"] == f"{variant_name} vs random_set_off"), 0)
            pred_bat = next((r["avg_used_per_battle"] for r in all_results if r["run"] == f"{variant_name} vs Basic"), 99)
            delta_vs_basic = wr_basic - (off_vs_basic_rate or 0)
            score = (wr_off - 50.0) + delta_vs_basic - max(0, pred_bat - 5.0)
            candidates_list.append((variant_name, score, wr_off, delta_vs_basic, pred_bat))
        candidates_list.sort(key=lambda x: x[1], reverse=True)
        if candidates_list:
            best_exp = candidates_list[0]
            print(f"  Closest variant: {best_exp[0]} (score={best_exp[1]:.2f})")
            print(f"  → Recommended as experimental only: DoublesDamageAwareConfig(enable_random_set_opponent_modeling=True, ...)")
        print("  → Keep enable_random_set_opponent_modeling=False (default)")

    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
