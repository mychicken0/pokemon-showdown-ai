#!/usr/bin/env python3
import csv
import os

def main():
    csv_file = "logs/doubles_champion_config_test.csv"
    if not os.path.exists(csv_file):
        print(f"Error: {csv_file} not found. Please run the champion config test script first.")
        return
        
    variants = []
    with open(csv_file, mode="r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["win_rate"] = float(row["win_rate"])
            row["avg_turns"] = float(row["avg_turns"])
            row["avg_protect"] = float(row["avg_protect"])
            row["avg_fake_out"] = float(row["avg_fake_out"])
            row["avg_spread"] = float(row["avg_spread"])
            row["avg_focus_fire"] = float(row["avg_focus_fire"])
            row["wins"] = int(row["wins"])
            row["losses"] = int(row["losses"])
            variants.append(row)
            
    if not variants:
        print("Error: No data in CSV.")
        return
        
    # Sort variants by win rate
    variants_sorted = sorted(variants, key=lambda x: x["win_rate"], reverse=True)
    
    best = variants_sorted[0]
    
    # best config with average turns under 8.5
    under_8_5 = [v for v in variants if v["avg_turns"] < 8.5]
    best_under_8_5 = sorted(under_8_5, key=lambda x: x["win_rate"], reverse=True)[0] if under_8_5 else None
    
    # best config with spread usage under 1.5
    under_1_5_spread = [v for v in variants if v["avg_spread"] < 1.5]
    best_under_1_5_spread = sorted(under_1_5_spread, key=lambda x: x["win_rate"], reverse=True)[0] if under_1_5_spread else None
    
    # Find full_phase2 baseline
    full_phase2 = next((v for v in variants if v["variant_name"] == "full_phase2"), None)
    
    print("====================================================")
    print("           DOUBLES CHAMPION CONFIG ANALYSIS         ")
    print("====================================================")
    print(f"Total variants analyzed: {len(variants)}\n")
    
    print(f"Rank | Variant Name               | Win Rate | Wins/Losses | Avg Turns | Protect | FakeOut | Spread | FocusFire")
    print("-" * 105)
    for idx, v in enumerate(variants_sorted, 1):
        wins_losses = f"{v['wins']}/{v['losses']}"
        print(f"{idx:4d} | {v['variant_name']:26s} | {v['win_rate']:7.2f}% | {wins_losses:11s} | {v['avg_turns']:9.2f} | {v['avg_protect']:7.2f} | {v['avg_fake_out']:7.2f} | {v['avg_spread']:6.2f} | {v['avg_focus_fire']:9.2f}")
    
    print("\n----------------------------------------------------")
    print(f"Best Config by Win Rate:               {best['variant_name']} ({best['win_rate']:.2f}% win rate)")
    
    if best_under_8_5:
        print(f"Best Config with Avg Turns < 8.5:      {best_under_8_5['variant_name']} ({best_under_8_5['win_rate']:.2f}% win rate, {best_under_8_5['avg_turns']:.2f} turns)")
    else:
        print("Best Config with Avg Turns < 8.5:      None found")
        
    if best_under_1_5_spread:
        print(f"Best Config with Spread Usage < 1.5:   {best_under_1_5_spread['variant_name']} ({best_under_1_5_spread['win_rate']:.2f}% win rate, {best_under_1_5_spread['avg_spread']:.2f} spread)")
    else:
        print("Best Config with Spread Usage < 1.5:   None found")
    print("----------------------------------------------------")
    
    if full_phase2:
        print("\nComparison against full_phase2 baseline:")
        baseline_wr = full_phase2["win_rate"]
        for v in variants_sorted:
            if v["variant_name"] == "full_phase2":
                continue
            diff = v["win_rate"] - baseline_wr
            print(f"  {v['variant_name']:26s}: {v['win_rate']:6.2f}% (change: {diff:+.2f}%)")
            
        print("\nRecommendation:")
        if best["variant_name"] == "full_phase2":
            print("  Retain 'full_phase2' as the default config. It achieved the highest win rate.")
        else:
            diff = best["win_rate"] - baseline_wr
            print(f"  Adopt '{best['variant_name']}' as the new default config.")
            print(f"  It improves the win rate by {diff:+.2f}% over 'full_phase2' in robust 300-battle tests.")
    else:
        print("\nError: Could not find 'full_phase2' baseline in the results.")
    print("====================================================")

if __name__ == "__main__":
    main()
