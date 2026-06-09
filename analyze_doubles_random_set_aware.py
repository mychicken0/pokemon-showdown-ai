#!/usr/bin/env python3
"""
analyze_doubles_random_set_aware.py

Phase 5.2: Analyzes benchmark results from:
    logs/doubles_random_set_aware_benchmark.csv

Prints:
- random_set_on vs random_set_off result
- random_set_on impact vs Basic
- safety check vs RandomPlayer
- prediction usage rates
- selected-action prediction rate
- coverage rate
- average score delta
- recommendation
"""
import csv
import os
import sys


CSV_PATH = "logs/doubles_random_set_aware_benchmark.csv"
ADOPTION_WIN_RATE_MIN = 50.0        # on vs off must be > 50%
ADOPTION_DELTA_VS_BASIC_MIN = 3.0   # on vs Basic must beat off vs Basic by +3%
ADOPTION_SAFETY_MIN = 95.0          # on vs RandomPlayer must be >= 95%
ADOPTION_PREDICTION_MAX = 5.0       # avg predictions/battle must be <= 5


def load_csv(path: str) -> list:
    if not os.path.exists(path):
        print(f"[ERROR] CSV not found: {path}")
        print("  Please run bot_doubles_random_set_aware_benchmark.py first.")
        sys.exit(1)
    rows = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: (float(v) if v.replace(".", "").replace("-", "").isdigit() else v) for k, v in row.items()})
    return rows


def find_row(rows: list, keyword: str) -> dict:
    for r in rows:
        if keyword.lower() in r.get("run", "").lower():
            return r
    return {}


def format_rate(val: float) -> str:
    return f"{val:.2f}%"


def main():
    print("=" * 70)
    print("  Phase 5.2: Random-Set-Aware Benchmark Analysis")
    print("=" * 70)
    print()

    rows = load_csv(CSV_PATH)

    # Retrieve individual runs
    row_on_basic = find_row(rows, "on vs basic")
    row_off_basic = find_row(rows, "off vs basic")
    row_on_off = find_row(rows, "on vs random_set_off")
    row_vs_random = find_row(rows, "randomplayerr") or find_row(rows, "randomplayer") or find_row(rows, "random")

    # If row_vs_random not found, try partial search
    if not row_vs_random:
        for r in rows:
            if "random" in r.get("run", "").lower() and "off" not in r.get("run", "").lower() and "basic" not in r.get("run", "").lower():
                row_vs_random = r
                break

    print("  Run Results:")
    print(f"  {'Run':<45} {'Win Rate':>10}  {'Wins':>6}  {'Battles':>7}")
    print("  " + "-" * 70)
    for r in rows:
        run_name = r.get("run", "?")
        wr = float(r.get("win_rate", 0))
        wins = int(r.get("wins", 0))
        finished = int(r.get("finished", 0))
        print(f"  {run_name:<45} {format_rate(wr):>10}  {wins:>6}  {finished:>7}")
    print()

    # Extract key numbers
    wr_on_basic = float(row_on_basic.get("win_rate", 0))
    wr_off_basic = float(row_off_basic.get("win_rate", 0))
    wr_on_off = float(row_on_off.get("win_rate", 0))
    wr_vs_random = float(row_vs_random.get("win_rate", 0)) if row_vs_random else 0.0
    delta = wr_on_basic - wr_off_basic

    # Prediction stats from on vs off run (most relevant)
    ref_row = row_on_off if row_on_off else row_on_basic
    candidates = int(float(ref_row.get("candidate_predictions", 0)))
    selected = int(float(ref_row.get("selected_predictions", 0)))
    used = int(float(ref_row.get("predictions_used", 0)))
    avg_used = float(ref_row.get("avg_used_per_battle", 0))
    avg_delta = float(ref_row.get("avg_score_delta", 0))
    coverage = float(ref_row.get("database_coverage_rate", 0))
    protect = int(float(ref_row.get("protect_predictions", 0)))
    fakeout = int(float(ref_row.get("fakeout_predictions", 0)))
    priority = int(float(ref_row.get("priority_predictions", 0)))
    spread = int(float(ref_row.get("spread_predictions", 0)))
    setup = int(float(ref_row.get("setup_predictions", 0)))
    speed_ctrl = int(float(ref_row.get("speed_control_predictions", 0)))

    selected_rate = (used / candidates * 100) if candidates > 0 else 0.0

    print("  Prediction Usage (from run: random_set_on vs random_set_off):")
    print(f"    Database Coverage Rate   : {coverage:.2f}%")
    print(f"    Candidate Predictions    : {candidates}")
    print(f"    Selected Predictions     : {selected}")
    print(f"    Predictions Used (total) : {used}")
    print(f"    Avg Used / Battle        : {avg_used:.2f}")
    print(f"    Selected Rate            : {selected_rate:.2f}%")
    print(f"    Avg Score Delta / Pred   : {avg_delta:.2f}")
    print()
    print(f"    Protect Predictions      : {protect}")
    print(f"    Fake Out Predictions     : {fakeout}")
    print(f"    Priority Predictions     : {priority}")
    print(f"    Spread Predictions       : {spread}")
    print(f"    Setup Predictions        : {setup}")
    print(f"    Speed Control Preds      : {speed_ctrl}")
    print()

    print("  Performance Summary:")
    print(f"    random_set_on vs Basic   : {format_rate(wr_on_basic)}")
    print(f"    random_set_off vs Basic  : {format_rate(wr_off_basic)}")
    print(f"    Delta (on - off vs Basic): {delta:+.2f}%")
    print(f"    random_set_on vs off     : {format_rate(wr_on_off)}")
    print(f"    random_set_on vs Random  : {format_rate(wr_vs_random)}")
    print()

    # Adoption rule checks
    print("  Adoption Rule Checks:")
    checks = [
        ("on vs off > 50.0%",        wr_on_off > ADOPTION_WIN_RATE_MIN,     f"{wr_on_off:.2f}%  vs {ADOPTION_WIN_RATE_MIN:.1f}%"),
        ("delta vs Basic >= +3.00%",  delta >= ADOPTION_DELTA_VS_BASIC_MIN,  f"{delta:+.2f}%  vs +{ADOPTION_DELTA_VS_BASIC_MIN:.1f}%"),
        ("safety vs Random >= 95%",   wr_vs_random >= ADOPTION_SAFETY_MIN,   f"{wr_vs_random:.2f}%  vs {ADOPTION_SAFETY_MIN:.1f}%"),
        ("avg used/battle <= 5.0",    avg_used <= ADOPTION_PREDICTION_MAX,   f"{avg_used:.2f}  vs {ADOPTION_PREDICTION_MAX:.1f}"),
    ]
    all_pass = True
    for name, passed, detail in checks:
        icon = "✅" if passed else "❌"
        if not passed:
            all_pass = False
        print(f"    {icon} {name:<35s} ({detail})")
    print()

    # Warnings
    warnings = []
    if avg_used > 5:
        warnings.append(f"Predictions used ({avg_used:.2f}/battle) exceeds threshold of 5.")
    if selected > 0 and selected_rate < 10:
        warnings.append(f"Selected prediction rate ({selected_rate:.2f}%) is very low.")
    if avg_delta > 25:
        warnings.append(f"Average score delta ({avg_delta:.2f}) is high — may cause instability.")
    if wr_on_off < 47:
        warnings.append(f"random_set_on vs random_set_off ({wr_on_off:.2f}%) shows possible regression.")

    if warnings:
        print("  Warnings:")
        for w in warnings:
            print(f"    ⚠️  {w}")
        print()

    # Recommendation
    print("=" * 70)
    if all_pass:
        print("  ✅ RECOMMENDATION: ENABLE random_set_opponent_modeling by default.")
        print()
        print("  All adoption criteria are met. Consider setting:")
        print("    enable_random_set_opponent_modeling = True")
        print("  as the new default in DoublesDamageAwareConfig.")
    else:
        print("  ❌ RECOMMENDATION: Keep enable_random_set_opponent_modeling = False (default).")
        print()
        print("  Reasons:")
        failed = [name for name, passed, _ in checks if not passed]
        for f in failed:
            print(f"    - {f} did not pass.")
        print()
        print("  random-set-aware scoring is available as an optional feature.")
        print("  To use it manually: DoublesDamageAwareConfig(enable_random_set_opponent_modeling=True)")
    print("=" * 70)


if __name__ == "__main__":
    main()
