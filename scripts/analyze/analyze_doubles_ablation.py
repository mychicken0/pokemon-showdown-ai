#!/usr/bin/env python3
import csv
import os

def main():
    csv_file = "logs/doubles_phase2_ablation.csv"
    if not os.path.exists(csv_file):
        print(f"Error: {csv_file} not found. Please run the ablation script first.")
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
            variants.append(row)
            
    if not variants:
        print("Error: No data in CSV.")
        return
        
    # Sort variants by win rate
    variants_sorted = sorted(variants, key=lambda x: x["win_rate"], reverse=True)
    
    best = variants_sorted[0]
    worst = variants_sorted[-1]
    
    # Find full_phase2 baseline
    full_phase2 = next((v for v in variants if v["variant_name"] == "full_phase2"), None)
    
    print("====================================================")
    print("           DOUBLES ABLATION ANALYSIS RESULTS        ")
    print("====================================================")
    print(f"Total variants analyzed: {len(variants)}\n")
    
    print(f"Rank | Variant Name               | Win Rate | Avg Turns | Protect | FakeOut | Spread | FocusFire")
    print("-" * 95)
    for idx, v in enumerate(variants_sorted, 1):
        print(f"{idx:4d} | {v['variant_name']:26s} | {v['win_rate']:7.2f}% | {v['avg_turns']:9.2f} | {v['avg_protect']:7.2f} | {v['avg_fake_out']:7.2f} | {v['avg_spread']:6.2f} | {v['avg_focus_fire']:9.2f}")
    
    print("\n----------------------------------------------------")
    print(f"Best Variant:  {best['variant_name']} ({best['win_rate']:.2f}% win rate)")
    print(f"Worst Variant: {worst['variant_name']} ({worst['win_rate']:.2f}% win rate)")
    print("----------------------------------------------------")
    
    if full_phase2:
        print("\nImpact on Win Rate (relative to full_phase2 baseline):")
        baseline_wr = full_phase2["win_rate"]
        print(f"  full_phase2 (Baseline): {baseline_wr:.2f}%")
        
        impacts = []
        for v in variants:
            if v["variant_name"] == "full_phase2":
                continue
            diff = v["win_rate"] - baseline_wr
            impacts.append((v["variant_name"], diff))
            print(f"  {v['variant_name']:26s}: {v['win_rate']:6.2f}% (change: {diff:+.2f}%)")
            
        # Feature value: feature is valuable if disabling it hurts performance (change is negative)
        # So most valuable is the one with the most negative change
        valuable_sorted = sorted(impacts, key=lambda x: x[1])
        
        print("\nFeature Valuation:")
        print("  (Ranked by how much performance drops when the feature is disabled/reverted)")
        for rank, (name, diff) in enumerate(valuable_sorted, 1):
            if diff < 0:
                print(f"   {rank}. {name:26s} | High Value  | Loss of {abs(diff):.2f}% when disabled")
            elif diff > 0:
                print(f"   {rank}. {name:26s} | Neg Value?  | Gain of {diff:.2f}% when disabled (potential noise/interference)")
            else:
                print(f"   {rank}. {name:26s} | Neutral     | No change in win rate")
                
        # Best features
        most_valuable = [x[0] for x in valuable_sorted if x[1] < 0]
        if most_valuable:
            print(f"\nMost valuable features: {', '.join(most_valuable)}")
        else:
            print("\nNo features showed a negative impact when disabled (could be due to variance/small sample size).")
            
        # Is full config better?
        if best["variant_name"] == "full_phase2":
            print("\nConclusion: The full Phase 2 config is the optimal configuration.")
        else:
            better_variants = [v["variant_name"] for v in variants_sorted if v["win_rate"] > baseline_wr]
            print(f"\nConclusion: The full config is NOT the absolute best. Variant(s) {', '.join(better_variants)} scored higher.")
            print("Note: Small sample sizes (100 battles) are subject to matchmaking variance.")
    else:
        print("\nError: Could not find 'full_phase2' baseline in the results.")
    print("====================================================")

if __name__ == "__main__":
    main()
