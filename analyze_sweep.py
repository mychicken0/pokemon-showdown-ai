import csv
import os

CSV_FILEPATH = "logs/switch_param_sweep.csv"

def format_config(row):
    return (f"margin={row['switch_margin']}, "
            f"override={row['high_score_attack_override']}, "
            f"limit={row['threatened_best_move_limit']}, "
            f"penalty={row['switch_penalty']}")

def analyze():
    if not os.path.exists(CSV_FILEPATH):
        print(f"Sweep results file not found at: {CSV_FILEPATH}")
        return

    configs = []
    with open(CSV_FILEPATH, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse row fields safely
            try:
                configs.append({
                    "switch_margin": float(row["switch_margin"]),
                    "high_score_attack_override": float(row["high_score_attack_override"]),
                    "threatened_best_move_limit": float(row["threatened_best_move_limit"]),
                    "switch_penalty": float(row["switch_penalty"]),
                    "wins": int(row["wins"]),
                    "losses": int(row["losses"]),
                    "win_rate": float(row["win_rate"]),
                    "average_turns": float(row["average_turns"]),
                    "average_strategic_switches": float(row["average_strategic_switches"])
                })
            except Exception as e:
                # Skip invalid rows (e.g. if benchmark is interrupted)
                continue

    if not configs:
        print("No valid configuration results found in the sweep file.")
        return

    print(f"\n================ Swept Configurations Analyzed: {len(configs)} ================")

    # 1. Top 10 configs by win rate
    top_by_win_rate = sorted(configs, key=lambda x: x["win_rate"], reverse=True)
    print("\n--- Top 10 Configurations by Win Rate ---")
    for idx, row in enumerate(top_by_win_rate[:10]):
        print(f"{idx+1:2d}. Win Rate: {row['win_rate']:.2f}% | {format_config(row)} | "
              f"wins={row['wins']}, losses={row['losses']}, avg_turns={row['average_turns']:.2f}, avg_switches={row['average_strategic_switches']:.2f}")

    # 2. Top 10 configs by win rate with average switches below 4.0
    under_4_switches = [c for c in configs if c["average_strategic_switches"] < 4.0]
    top_under_4 = sorted(under_4_switches, key=lambda x: x["win_rate"], reverse=True)
    print("\n--- Top 10 Configurations by Win Rate (Avg Switches < 4.0) ---")
    if top_under_4:
        for idx, row in enumerate(top_under_4[:10]):
            print(f"{idx+1:2d}. Win Rate: {row['win_rate']:.2f}% | {format_config(row)} | "
                  f"wins={row['wins']}, losses={row['losses']}, avg_turns={row['average_turns']:.2f}, avg_switches={row['average_strategic_switches']:.2f}")
    else:
        print("  No configurations found with average switches below 4.0.")

    # 3. Most efficient config using score: efficiency_score = win_rate - (avg_switches * 0.02)
    # Wait, the formula uses (avg_switches * 0.02). Let's calculate:
    for c in configs:
        c["efficiency_score"] = c["win_rate"] - (c["average_strategic_switches"] * 0.02)
        
    most_efficient = max(configs, key=lambda x: x["efficiency_score"])
    print("\n--- Most Efficient Configuration ---")
    print(f"Efficiency Score: {most_efficient['efficiency_score']:.4f}")
    print(f"Config: {format_config(most_efficient)}")
    print(f"Win Rate: {most_efficient['win_rate']:.2f}% | avg_switches={most_efficient['average_strategic_switches']:.2f} | avg_turns={most_efficient['average_turns']:.2f}")
    print("=================================================================\n")

if __name__ == "__main__":
    analyze()
