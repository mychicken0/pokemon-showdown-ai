#!/usr/bin/env python3
"""
analyze_doubles_meta_aware.py

Analyzes logs/doubles_meta_aware_benchmark.csv to:
- Compare meta_on vs meta_off (Run C)
- Compare impact vs DoublesBasicAwarePlayer (Run A vs Run B)
- Print database coverage, prediction rates, and score deltas
- Output default adoption recommendations based on the +3% win rate improvement threshold.
"""
import csv
import os


def main():
    csv_file = "logs/doubles_meta_aware_benchmark.csv"

    if not os.path.exists(csv_file):
        print(f"Error: {csv_file} not found. Please run bot_doubles_meta_aware_benchmark.py first.")
        return

    runs = {}
    with open(csv_file, mode="r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            run_name = row["run"]
            runs[run_name] = {
                "win_rate": float(row["win_rate"]),
                "wins": int(row["wins"]),
                "finished": int(row["finished"]),
                "avg_turns": float(row["avg_turns"]),
                "database_coverage_rate": float(row["database_coverage_rate"]),
                "candidate_predictions": int(row["candidate_predictions"]),
                "selected_predictions": int(row["selected_predictions"]),
                "predictions_used": int(row["predictions_used"]),
                "avg_score_delta": float(row["avg_score_delta"]),
                "protect_predictions": int(row["protect_predictions"]),
                "fakeout_predictions": int(row["fakeout_predictions"]),
                "priority_predictions": int(row["priority_predictions"]),
                "spread_predictions": int(row["spread_predictions"]),
                "setup_predictions": int(row["setup_predictions"]),
                "coverage_predictions": int(row["coverage_predictions"]),
                "ability_soft_penalties": int(row["ability_soft_penalties"])
            }

    print("=" * 80)
    print("                 DOUBLES PHASE 5 META-AWARE ANALYSIS")
    print("=" * 80)

    # 1. Comparison of meta_on vs meta_off (Run C)
    print("\n--- Run C: Head-to-Head (meta_on vs meta_off) ---")
    run_c = runs.get("meta_on vs meta_off")
    if run_c:
        wr_c = run_c["win_rate"]
        print(f"  meta_on win rate vs meta_off: {wr_c:.2f}% ({run_c['wins']}/{run_c['finished']})")
        diff_c = wr_c - 50.0
        print(f"  Net win rate difference     : {diff_c:+.2f}%")
    else:
        print("  Run C results not found.")

    # 2. Impact vs DoublesBasicAwarePlayer (Run A vs Run B)
    print("\n--- Runs A & B: Performance vs DoublesBasicAwarePlayer ---")
    run_a = runs.get("meta_on vs Basic")
    run_b = runs.get("meta_off vs Basic")
    if run_a and run_b:
        wr_a = run_a["win_rate"]
        wr_b = run_b["win_rate"]
        print(f"  meta_on  vs Basic: {wr_a:.2f}% | Avg Turns: {run_a['avg_turns']:.2f}")
        print(f"  meta_off vs Basic: {wr_b:.2f}% | Avg Turns: {run_b['avg_turns']:.2f}")
        diff_ab = wr_a - wr_b
        print(f"  Improvement vs Basic: {diff_ab:+.2f}%")
    else:
        print("  Runs A & B results not found.")

    # 3. Performance vs RandomPlayer (Run D)
    print("\n--- Run D: Performance vs RandomPlayer ---")
    run_d = runs.get("meta_on vs Random")
    if run_d:
        print(f"  meta_on vs Random: {run_d['win_rate']:.2f}% ({run_d['wins']}/{run_d['finished']})")
    else:
        print("  Run D results not found.")

    # 4. Meta Modeling Metrics
    print("\n--- Meta Heuristic Statistics ---")
    meta_runs = [runs.get("meta_on vs Basic"), runs.get("meta_on vs meta_off"), runs.get("meta_on vs Random")]
    meta_runs = [r for r in meta_runs if r]
    
    if meta_runs:
        total_finished = sum(r["finished"] for r in meta_runs)
        total_used = sum(r["predictions_used"] for r in meta_runs)
        total_candidates = sum(r["candidate_predictions"] for r in meta_runs)
        total_selected = sum(r["selected_predictions"] for r in meta_runs)
        
        avg_used_per_battle = total_used / total_finished if total_finished > 0 else 0.0
        avg_selected_per_battle = total_selected / total_finished if total_finished > 0 else 0.0
        
        avg_coverage = sum(r["database_coverage_rate"] for r in meta_runs) / len(meta_runs)
        avg_score_delta = sum(r["avg_score_delta"] * r["selected_predictions"] for r in meta_runs) / total_selected if total_selected > 0 else 0.0

        print(f"  Average Database Coverage Rate   : {avg_coverage:.2f}%")
        print(f"  Candidate Predictions Generated  : {total_candidates}")
        print(f"  Selected Predictions Triggered   : {total_selected} (avg {avg_selected_per_battle:.2f}/battle)")
        print(f"  Total Predictions Logged/Used    : {total_used} (avg {avg_used_per_battle:.2f}/battle)")
        print(f"  Weighted Average Score Delta     : {avg_score_delta:.2f}")
        
        print("\n  Prediction Types Triggered (Selected Actions):")
        total_protect = sum(r["protect_predictions"] for r in meta_runs)
        total_fakeout = sum(r["fakeout_predictions"] for r in meta_runs)
        total_priority = sum(r["priority_predictions"] for r in meta_runs)
        total_spread = sum(r["spread_predictions"] for r in meta_runs)
        total_setup = sum(r["setup_predictions"] for r in meta_runs)
        total_coverage = sum(r["coverage_predictions"] for r in meta_runs)
        total_soft_abilities = sum(r["ability_soft_penalties"] for r in meta_runs)

        print(f"    - Protect Predictions          : {total_protect}")
        print(f"    - Fake Out Predictions         : {total_fakeout}")
        print(f"    - Priority Predictions         : {total_priority}")
        print(f"    - Spread Move Predictions      : {total_spread}")
        print(f"    - Setup Move Predictions       : {total_setup}")
        print(f"    - Super-Effective Coverage     : {total_coverage}")
        print(f"    - Ability Soft Penalties       : {total_soft_abilities}")
    else:
        print("  No meta statistics found.")

    # 5. Warnings and Recommendations
    print("\n--- Warnings & Validation Checks ---")
    warnings = []
    
    if meta_runs:
        if avg_used_per_battle > 5.0:
            warnings.append(f"Prediction usage is high (avg {avg_used_per_battle:.2f} per battle, threshold <= 5.0). May disrupt focus-fire.")
        if avg_score_delta > 30.0:
            warnings.append(f"Average score delta is high ({avg_score_delta:.2f}, threshold <= 30.0). Heuristics may be too aggressive.")
        if avg_coverage < 10.0:
            warnings.append(f"Database coverage is very low ({avg_coverage:.2f}%, threshold >= 10.0%). Predictor is mostly fallback.")
        if total_selected == 0:
            warnings.append("Selected-action prediction rate is zero. Heuristics are not affecting final choices.")
        
    if run_c and run_c["win_rate"] < 50.0:
        warnings.append(f"meta_on lost head-to-head vs meta_off (win rate: {run_c['win_rate']:.2f}%).")

    if warnings:
        for w in warnings:
            print(f"  [WARNING] {w}")
    else:
        print("  All validation checks passed!")

    print("\n--- Final Recommendation ---")
    recommend_default = False
    reasons = []

    # Check adoption rules
    if run_c:
        diff_head = run_c["win_rate"] - 50.0
        if diff_head >= 3.0:
            reasons.append(f"beats meta_off head-to-head by {diff_head:+.2f}% (>= +3.0%)")
            recommend_default = True
        else:
            reasons.append(f"head-to-head win rate vs meta_off is {run_c['win_rate']:.2f}% (need >= +3.0% improvement)")
    elif run_a and run_b:
        diff_basic = run_a["win_rate"] - run_b["win_rate"]
        if diff_basic >= 3.0:
            reasons.append(f"beats meta_off against Basic Player by {diff_basic:+.2f}% (>= +3.0%)")
            recommend_default = True
        else:
            reasons.append(f"improvement against Basic Player is {diff_basic:+.2f}% (need >= +3.0% improvement)")

    # Safety check vs Random
    if run_d and run_d["win_rate"] < 95.0:
        recommend_default = False
        reasons.append(f"Failed safety check vs RandomPlayer: {run_d['win_rate']:.2f}% (need >= 95.0%)")

    # If any warnings triggered, avoid enabling by default unless improvement is massive
    if warnings and recommend_default:
        recommend_default = False
        reasons.append("Heuristic triggers exceed safety thresholds or coverage is too low.")

    if recommend_default:
        print("  RECOMMENDATION: Enable Meta-Aware Opponent Modeling by default!")
        print("  Reason:")
        for r in reasons:
            print(f"    - {r}")
    else:
        print("  RECOMMENDATION: Keep Meta-Aware Opponent Modeling optional and DISABLED by default.")
        print("  Reason:")
        for r in reasons:
            print(f"    - {r}")
    print("=" * 80)


if __name__ == "__main__":
    main()
