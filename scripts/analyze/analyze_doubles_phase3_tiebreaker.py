#!/usr/bin/env python3
import csv
import os

def main():
    csv_file = "logs/doubles_phase3_tiebreaker.csv"
    if not os.path.exists(csv_file):
        print(f"Error: {csv_file} not found. Please run the phase 3 tiebreaker benchmark script first.")
        return
        
    variants = []
    with open(csv_file, mode="r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["win_rate"] = float(row["win_rate"])
            row["avg_turns"] = float(row["avg_turns"])
            row["protect_usage"] = float(row["protect_usage"])
            row["fake_out_usage"] = float(row["fake_out_usage"])
            row["spread_usage"] = float(row["spread_usage"])
            row["focus_fire_turns"] = float(row["focus_fire_turns"])
            row["tiebreaker_activations"] = float(row["tiebreaker_activations"])
            row["boosted_override_activations"] = float(row["boosted_override_activations"])
            variants.append(row)
            
    if not variants:
        print("Error: No data in CSV.")
        return
        
    # Sort variants by win rate
    variants_sorted = sorted(variants, key=lambda x: x["win_rate"], reverse=True)
    best = variants_sorted[0]
    
    # Find full_phase2 baseline
    full_phase2 = next((v for v in variants if v["variant"] == "full_phase2"), None)
    
    print("====================================================================================================")
    print("                      DOUBLES PHASE 3 TIEBREAKER & THREAT ANALYSIS                                  ")
    print("====================================================================================================")
    print(f"Total variants analyzed: {len(variants)}\n")
    
    print(f"Rank | Variant Name               | Win Rate | Avg Turns | Protect | FakeOut | Spread | FocusFire | Tiebreakers | BoostOverrides")
    print("-" * 116)
    for idx, v in enumerate(variants_sorted, 1):
        print(f"{idx:4d} | {v['variant']:26s} | {v['win_rate']:7.2f}% | {v['avg_turns']:9.2f} | {v['protect_usage']:7.2f} | {v['fake_out_usage']:7.2f} | {v['spread_usage']:6.2f} | {v['focus_fire_turns']:9.2f} | {v['tiebreaker_activations']:11.1f} | {v['boosted_override_activations']:14.1f}")
    
    print("\n----------------------------------------------------------------------------------------------------")
    print(f"Best Config by Win Rate:               {best['variant']} ({best['win_rate']:.2f}% win rate)")
    print("----------------------------------------------------------------------------------------------------")
    
    if full_phase2:
        print("\nComparison against full_phase2 baseline:")
        baseline_wr = full_phase2["win_rate"]
        for v in variants_sorted:
            if v["variant"] == "full_phase2":
                continue
            diff = v["win_rate"] - baseline_wr
            print(f"  {v['variant']:26s}: {v['win_rate']:6.2f}% (change: {diff:+.2f}%)")
            
        print("\nDecision Points:")
        print("  1. Does any gated threat tiebreaker or refinement variant improve performance over full_phase2?")
        improvers = [v for v in variants_sorted if v["win_rate"] > baseline_wr]
        if improvers:
            print(f"     Yes! {len(improvers)} variant(s) beat the baseline.")
            for imp in improvers:
                diff = imp["win_rate"] - baseline_wr
                print(f"       - {imp['variant']} ({diff:+.2f}%)")
        else:
            print("     No. No variant beat the baseline.")

        print("  2. Should threat remain disabled by default?")
        # If the best variant is full_phase2 or if the difference is very small (< 0.5% improvement), we recommend keeping it disabled.
        if best["variant"] == "full_phase2" or best["win_rate"] - baseline_wr <= 0.0:
            print("     Yes. Since full_phase2 remains the best performing config, threat should remain disabled by default.")
        else:
            diff = best["win_rate"] - baseline_wr
            print(f"     Recommendation based on benchmark: Adopt '{best['variant']}' as the new default if the user wishes,")
            print(f"     since it improves win rate by {diff:+.2f}%. Otherwise, keep disabled by default as requested.")
    else:
        print("\nError: Could not find 'full_phase2' baseline in the results.")
    print("====================================================================================================")

if __name__ == "__main__":
    main()
