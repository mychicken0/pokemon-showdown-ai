#!/usr/bin/env python3
"""
analyze_doubles_tiebreaker_confirm.py

Analyzes logs/doubles_tiebreaker_confirm.csv and produces:
- Ranked table with win rates and activation stats
- Efficiency scores (win_rate - avg_turns * 0.005)
- Noise check between threat_tiebreaker_10 and threat_tiebreaker_10_repeat
- Conservative recommendation based on the +3% win rate adoption rule
"""
import csv
import os


def main():
    csv_file = "logs/doubles_tiebreaker_confirm.csv"
    if not os.path.exists(csv_file):
        print(f"Error: {csv_file} not found. Please run bot_doubles_tiebreaker_confirm.py first.")
        return

    variants = []
    with open(csv_file, mode="r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["win_rate"] = float(row["win_rate"])
            row["wins"] = int(row["wins"])
            row["finished"] = int(row["finished"])
            row["avg_turns"] = float(row["avg_turns"])
            row["protect_usage"] = float(row["protect_usage"])
            row["fake_out_usage"] = float(row["fake_out_usage"])
            row["spread_usage"] = float(row["spread_usage"])
            row["focus_fire_turns"] = float(row["focus_fire_turns"])
            row["total_tiebreaker_activations"] = float(row["total_tiebreaker_activations"])
            row["tiebreaker_per_battle"] = float(row["tiebreaker_per_battle"])
            row["efficiency_score"] = row["win_rate"] - (row["avg_turns"] * 0.005)
            variants.append(row)

    if not variants:
        print("Error: No data found in CSV.")
        return

    full_phase2 = next((v for v in variants if v["variant"] == "full_phase2"), None)
    if not full_phase2:
        print("Error: full_phase2 baseline not found in results.")
        return

    baseline_wr = full_phase2["win_rate"]
    baseline_turns = full_phase2["avg_turns"]

    # Sort by win rate, then by lower avg_turns as tiebreaker
    variants_sorted = sorted(variants, key=lambda x: (-x["win_rate"], x["avg_turns"]))

    # --- Header ---
    print("=" * 120)
    print("               DOUBLES PHASE 3 TIEBREAKER CONFIRMATION ANALYSIS")
    print("=" * 120)
    print(f"{'Rank':<5} {'Variant':<34} {'WinRate':>8} {'AvgTurns':>9} {'Eff':>7} {'Protect':>8} {'FakeOut':>8} {'TBperBat':>9} {'WR vs FP2':>10}")
    print("-" * 120)

    for idx, v in enumerate(variants_sorted, 1):
        diff = v["win_rate"] - baseline_wr
        diff_str = f"{diff:+.2f}%"
        tb_warn = "(*)" if v["tiebreaker_per_battle"] > 8.0 else "   "
        print(f"{idx:<5} {v['variant']:<34} {v['win_rate']:>7.2f}% {v['avg_turns']:>9.2f} "
              f"{v['efficiency_score']:>7.2f} {v['protect_usage']:>8.2f} {v['fake_out_usage']:>8.2f} "
              f"{v['tiebreaker_per_battle']:>7.2f}{tb_warn} {diff_str:>10}")

    print("-" * 120)
    print("(*) = Tiebreaker activations/battle > 8.0 — gate may be too loose")

    # --- Noise / Variance Check ---
    print("\n--- Noise / Repeat Check (threat_tiebreaker_10 vs threat_tiebreaker_10_repeat) ---")
    v10 = next((v for v in variants if v["variant"] == "threat_tiebreaker_10"), None)
    v10r = next((v for v in variants if v["variant"] == "threat_tiebreaker_10_repeat"), None)
    if v10 and v10r:
        wr_diff = abs(v10["win_rate"] - v10r["win_rate"])
        tb_diff = abs(v10["tiebreaker_per_battle"] - v10r["tiebreaker_per_battle"])
        print(f"  threat_tiebreaker_10        : {v10['win_rate']:.2f}% | TB/battle: {v10['tiebreaker_per_battle']:.2f}")
        print(f"  threat_tiebreaker_10_repeat : {v10r['win_rate']:.2f}% | TB/battle: {v10r['tiebreaker_per_battle']:.2f}")
        print(f"  Win rate difference         : {wr_diff:.2f}%")
        print(f"  TB activation difference    : {tb_diff:.2f}")
        if wr_diff > 3.0:
            print("  NOTE: High variance detected! Results for this config may be unreliable over 500 battles.")
        elif wr_diff > 1.5:
            print("  NOTE: Moderate variance. Results are somewhat noisy but within acceptable range.")
        else:
            print("  OK: Low variance. Results appear stable.")
    else:
        print("  (Could not find both repeat variants for comparison)")

    # --- Activation Rate Analysis ---
    print("\n--- Tiebreaker Activation Rate Analysis ---")
    tiebreaker_variants = [v for v in variants if v["variant"] != "full_phase2"]
    for v in sorted(tiebreaker_variants, key=lambda x: x["tiebreaker_per_battle"]):
        warn = " <-- WARNING: too loose!" if v["tiebreaker_per_battle"] > 8.0 else ""
        print(f"  {v['variant']:<34} : {v['tiebreaker_per_battle']:.2f} activations/battle{warn}")

    # --- Best variant selection ---
    print("\n--- Best Configurations ---")
    best_by_wr = variants_sorted[0]
    best_by_eff = sorted(variants, key=lambda x: -x["efficiency_score"])[0]
    print(f"  Best by Win Rate  : {best_by_wr['variant']} ({best_by_wr['win_rate']:.2f}%)")
    print(f"  Best by Efficiency: {best_by_eff['variant']} (eff={best_by_eff['efficiency_score']:.2f})")

    # --- Per-variant win rate interpretation vs full_phase2 ---
    print("\n--- Win Rate Comparison vs full_phase2 ---")
    for v in variants_sorted:
        if v["variant"] == "full_phase2":
            continue
        diff = v["win_rate"] - baseline_wr
        if diff >= 5.0:
            strength = "STRONG improvement"
        elif diff >= 3.0:
            strength = "Meaningful improvement"
        elif diff > 0:
            strength = "Weak / may be noise"
        else:
            strength = "No improvement / regression"
        print(f"  {v['variant']:<34} : {diff:+.2f}% — {strength}")

    # --- Conservative recommendation ---
    print("\n--- Conservative Selection Rule ---")
    print("(If two configs are within 1.0% win rate, prefer: lower weight > lower gap > fewer activations > fewer turns)")

    # Find the single best tiebreaker candidate
    candidates = [v for v in variants if v["variant"] != "full_phase2"
                  and v["variant"] != "threat_tiebreaker_10_repeat"]
    best_candidates = sorted(candidates, key=lambda x: (-x["win_rate"], x["avg_turns"]))

    if not best_candidates:
        print("  No non-baseline candidates found.")
        return

    best = best_candidates[0]
    # Collect all candidates within 1% of best
    close_group = [v for v in best_candidates if best["win_rate"] - v["win_rate"] <= 1.0]

    if len(close_group) > 1:
        # Apply conservative tiebreaker rules
        # Parse weight and gap from variant name if possible, else use defaults
        def get_weight(v):
            name = v["variant"]
            for part in name.split("_"):
                try:
                    val = float(part)
                    if 1.0 <= val <= 50.0:
                        return val
                except ValueError:
                    pass
            return 99.0

        def get_gap(v):
            name = v["variant"]
            if "gap_" in name:
                try:
                    return float(name.split("gap_")[-1])
                except ValueError:
                    pass
            return 80.0  # default gap

        close_group_sorted = sorted(
            close_group,
            key=lambda v: (get_weight(v), get_gap(v), v["tiebreaker_per_battle"], v["avg_turns"])
        )
        best = close_group_sorted[0]
        print(f"  Conservative best from group within 1%: {best['variant']}")
    else:
        print(f"  Clear best candidate: {best['variant']}")

    # --- Final adoption recommendation ---
    print("\n--- Final Adoption Recommendation ---")
    win_diff = best["win_rate"] - baseline_wr
    turns_diff = best["avg_turns"] - baseline_turns
    tb_per_battle = best["tiebreaker_per_battle"]
    meets_wr_threshold = win_diff >= 3.0
    meets_turns_threshold = turns_diff <= 0.5
    tb_not_extreme = tb_per_battle <= 12.0  # allow up to 12 as not extreme

    print(f"  Candidate      : {best['variant']}")
    print(f"  Win rate diff  : {win_diff:+.2f}% (need >= +3.0% to adopt)")
    print(f"  Turns diff     : {turns_diff:+.2f} (need <= +0.5 to adopt)")
    print(f"  TB/battle      : {tb_per_battle:.2f} (need <= 12.0 to be acceptable)")

    if meets_wr_threshold and meets_turns_threshold and tb_not_extreme:
        print(f"\n  RECOMMENDATION: Adopt '{best['variant']}' as the new experimental default.")
        print(f"  It beats full_phase2 by {win_diff:+.2f}% over 500 battles with acceptable turn cost.")
        print(f"  To enable it, set: enable_threat_tiebreaker=True, threat_tiebreaker_weight={best['variant']}")
    else:
        print(f"\n  RECOMMENDATION: Keep 'full_phase2' as the stable default.")
        reasons = []
        if not meets_wr_threshold:
            reasons.append(f"win rate improvement ({win_diff:+.2f}%) is below the +3.0% threshold")
        if not meets_turns_threshold:
            reasons.append(f"average turns increased by {turns_diff:+.2f} (above 0.5 limit)")
        if not tb_not_extreme:
            reasons.append(f"tiebreaker activations/battle ({tb_per_battle:.2f}) are too high")
        for r in reasons:
            print(f"    Reason: {r}")
        if best["win_rate"] > baseline_wr:
            print(f"\n  MARK as experimental_best: '{best['variant']}' ({best['win_rate']:.2f}% win rate)")
            print(f"  Enable with: enable_threat_tiebreaker=True")

    print("=" * 120)


if __name__ == "__main__":
    main()
