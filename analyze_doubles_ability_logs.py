#!/usr/bin/env python3
"""
analyze_doubles_ability_logs.py

Analyzes logs/doubles_ability_aware_benchmark.csv and logs/ability_benchmark.log to:
- Compare ability_on vs ability_off (Run C)
- Compare impact vs DoublesBasicAwarePlayer (Run A vs Run B)
- Print common ability events
- Output default adoption recommendations based on the +3% win rate improvement threshold.
"""
import csv
import os
import re
from collections import Counter


def main():
    csv_file = "logs/doubles_ability_aware_benchmark.csv"
    log_file = "logs/ability_benchmark.log"

    if not os.path.exists(csv_file):
        print(f"Error: {csv_file} not found. Please run bot_doubles_ability_aware_benchmark.py first.")
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
                "blocks_avoided": int(row["blocks_avoided"]),
                "absorbs_avoided": int(row["absorbs_avoided"]),
                "redirects_avoided": int(row["redirects_avoided"]),
                "ally_safe_spreads_used": int(row["ally_safe_spreads_used"]),
                "multipliers_applied": int(row["multipliers_applied"])
            }

    print("=" * 80)
    print("                 DOUBLES PHASE 4 ABILITY AWARENESS ANALYSIS")
    print("=" * 80)

    # 1. Comparison of ability_on vs ability_off (Run C)
    print("\n--- Run C: Head-to-Head (ability_on vs ability_off) ---")
    run_c = runs.get("ability_on vs ability_off")
    if run_c:
        wr_c = run_c["win_rate"]
        print(f"  ability_on win rate vs ability_off: {wr_c:.2f}% ({run_c['wins']}/{run_c['finished']})")
        diff_c = wr_c - 50.0
        print(f"  Net win rate difference           : {diff_c:+.2f}%")
    else:
        print("  Run C results not found.")

    # 2. Impact vs DoublesBasicAwarePlayer (Run A vs Run B)
    print("\n--- Runs A & B: Performance vs DoublesBasicAwarePlayer ---")
    run_a = runs.get("ability_on vs Basic")
    run_b = runs.get("ability_off vs Basic")
    if run_a and run_b:
        wr_a = run_a["win_rate"]
        wr_b = run_b["win_rate"]
        print(f"  ability_on  vs Basic: {wr_a:.2f}% | Avg Turns: {run_a['avg_turns']:.2f}")
        print(f"  ability_off vs Basic: {wr_b:.2f}% | Avg Turns: {run_b['avg_turns']:.2f}")
        diff_ab = wr_a - wr_b
        print(f"  Improvement vs Basic: {diff_ab:+.2f}%")
    else:
        print("  Runs A & B results not found.")

    # 3. Performance vs RandomPlayer (Run D)
    print("\n--- Run D: Performance vs RandomPlayer ---")
    run_d = runs.get("ability_on vs Random")
    if run_d:
        print(f"  ability_on vs Random: {run_d['win_rate']:.2f}% ({run_d['wins']}/{run_d['finished']})")
    else:
        print("  Run D results not found.")

    # 4. Parser for log events if logs/ability_benchmark.log exists
    if os.path.exists(log_file):
        print("\n--- Logged Ability Events from logs/ability_benchmark.log ---")
        block_pattern = re.compile(r"\[Ability Block\] (.*?) \|")
        absorb_pattern = re.compile(r"\[Ability Absorb\] (.*?) \|")
        redirect_pattern = re.compile(r"\[Ability Redirection\] (.*?) \|")
        mult_pattern = re.compile(r"\[Ability Multiplier\] target_mult=(.*?) vs (\S+)")
        status_pattern = re.compile(r"\[Status Blocked\] (.*?) \|")

        blocks = []
        absorbs = []
        redirects = []
        multipliers = []
        status_blocks = []

        with open(log_file, "r") as lf:
            for line in lf:
                if "[Ability Block]" in line:
                    m = block_pattern.search(line)
                    if m:
                        blocks.append(m.group(1))
                elif "[Ability Absorb]" in line:
                    m = absorb_pattern.search(line)
                    if m:
                        absorbs.append(m.group(1))
                elif "[Ability Redirection]" in line:
                    m = redirect_pattern.search(line)
                    if m:
                        redirects.append(m.group(1))
                elif "[Ability Multiplier]" in line:
                    m = mult_pattern.search(line)
                    if m:
                        multipliers.append(m.group(2))
                elif "[Status Blocked]" in line:
                    m = status_pattern.search(line)
                    if m:
                        status_blocks.append(m.group(1))

        print(f"  Total Damage Blocks Avoided      : {len(blocks)}")
        print(f"  Total Absorbs/Immunities Avoided : {len(absorbs)}")
        print(f"  Total Redirections Avoided       : {len(redirects)}")
        print(f"  Total Status Blocks Avoided      : {len(status_blocks)}")

        # Print top common events
        event_counter = Counter(blocks + absorbs + status_blocks)
        if event_counter:
            print("\n  Top 5 Avoided Mistakes:")
            for event, count in event_counter.most_common(5):
                print(f"    - {event}: {count} times")
    else:
        print("\n--- Metric Totals from CSV ---")
        # Fallback to display sums recorded in CSV
        total_blocks = sum(r["blocks_avoided"] for r in runs.values())
        total_absorbs = sum(r["absorbs_avoided"] for r in runs.values())
        total_redirects = sum(r["redirects_avoided"] for r in runs.values())
        total_spreads = sum(r["ally_safe_spreads_used"] for r in runs.values())
        total_mults = sum(r["multipliers_applied"] for r in runs.values())
        print(f"  Ability Blocks Avoided   : {total_blocks}")
        print(f"  Absorbs Avoided          : {total_absorbs}")
        print(f"  Redirections Avoided     : {total_redirects}")
        print(f"  Ally-Safe Spreads Used   : {total_spreads}")
        print(f"  Multipliers Applied      : {total_mults}")

    # 5. Recommendation logic
    print("\n--- Final Recommendation ---")
    recommend_default = False
    reasons = []

    # Check Run C head-to-head or Run A vs Run B
    if run_c:
        diff_head = run_c["win_rate"] - 50.0
        if diff_head >= 3.0:
            reasons.append(f"beats ability_off head-to-head by {diff_head:+.2f}% (>= 3.0%)")
            recommend_default = True
        else:
            reasons.append(f"head-to-head win rate vs ability_off is {run_c['win_rate']:.2f}% (only {diff_head:+.2f}% improvement, need >= +3.0%)")
    elif run_a and run_b:
        diff_basic = run_a["win_rate"] - run_b["win_rate"]
        if diff_basic >= 3.0:
            reasons.append(f"beats ability_off against Basic Player by {diff_basic:+.2f}% (>= 3.0%)")
            recommend_default = True
        else:
            reasons.append(f"improvement against Basic Player is {diff_basic:+.2f}% (need >= +3.0%)")

    # Safety checks
    if run_a and run_b:
        turns_diff = run_a["avg_turns"] - run_b["avg_turns"]
        if turns_diff > 0.5:
            print(f"  WARNING: Average turns increased by {turns_diff:+.2f} (exceeds +0.5 threshold)")
            # Do not force recommend if average turns spiked
            if recommend_default and turns_diff > 0.8:
                recommend_default = False
                reasons.append(f"average turn increase of {turns_diff:+.2f} is too high")

    if recommend_default:
        print("  RECOMMENDATION: Enable Ability-Aware Scoring by default!")
        print("  Reason:")
        for r in reasons:
            print(f"    - {r}")
    else:
        print("  RECOMMENDATION: Keep Ability-Aware Scoring optional and DISABLED by default.")
        print("  Reason:")
        for r in reasons:
            print(f"    - {r}")
    print("=" * 80)


if __name__ == "__main__":
    main()
