#!/usr/bin/env python3
"""
check_random_set_coverage.py

Phase 5.1: Measure database coverage for gen9randomdoublesbattle
BEFORE integrating predictions into scoring.

Method: Read existing doubles battle logs to extract all opponent species
encountered, then compare against data/random_doubles_set_stats.json.

If Option A logs don't have enough data, falls back to running fresh
100-battle matches using RandomPlayer.

Prints:
- total unique species encountered
- species found in database
- species missing from database
- database coverage rate (%)
- top missing species by frequency

Target: coverage >= 60% before proceeding to scoring integration.
"""
import asyncio
import json
import os
import sys
from collections import Counter
from typing import Optional


# ---------------------------------------------------------------------------
# Normalization (must match random_set_model.py / build_random_set_stats.py)
# ---------------------------------------------------------------------------

def normalize_species(name: str) -> str:
    if not name:
        return ""
    return "".join(c.lower() for c in str(name) if c.isalnum())


# ---------------------------------------------------------------------------
# Option A: Read existing battle logs
# ---------------------------------------------------------------------------

def load_species_from_logs(log_paths: list) -> Counter:
    """
    Parse existing doubles battle JSONL logs and collect all opponent
    species observed during battles.

    Returns a Counter of normalized_species -> occurrence_count.
    """
    species_counter: Counter = Counter()

    for log_path in log_paths:
        if not os.path.exists(log_path):
            continue
        print(f"  Reading log: {log_path}")
        with open(log_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    turns = record.get("turns", [])
                    for turn in turns:
                        # Collect both our and opponent species (full coverage view)
                        for field in [
                            "our_active_1", "our_active_2",
                            "opp_active_1", "opp_active_2",
                        ]:
                            raw = turn.get(field, "")
                            if raw and raw not in ("None", "none", ""):
                                norm = normalize_species(raw)
                                if norm:
                                    species_counter[norm] += 1
                except Exception:
                    pass

    return species_counter


# ---------------------------------------------------------------------------
# Option B: Run fresh battles to collect species
# ---------------------------------------------------------------------------

async def run_fresh_battles(n_battles: int = 100) -> Counter:
    """
    Run n_battles of gen9randomdoublesbattle between two RandomPlayers
    and collect all opponent species seen.
    """
    try:
        from poke_env import AccountConfiguration
        from poke_env.player import RandomPlayer
    except ImportError:
        print("[ERROR] poke_env not installed. Cannot run fresh battles.")
        return Counter()

    import random
    suffix = random.randint(1000, 9999)

    player_a = RandomPlayer(
        account_configuration=AccountConfiguration(f"CovCheckA_{suffix}", None),
        battle_format="gen9randomdoublesbattle",
        max_concurrent_battles=10,
    )
    player_b = RandomPlayer(
        account_configuration=AccountConfiguration(f"CovCheckB_{suffix}", None),
        battle_format="gen9randomdoublesbattle",
        max_concurrent_battles=10,
    )

    print(f"  Running {n_battles} fresh gen9randomdoublesbattle battles...")
    await player_a.battle_against(player_b, n_battles=n_battles)

    species_counter: Counter = Counter()
    for battle in player_a.battles.values():
        # Collect our team species
        for mon in battle.team.values():
            norm = normalize_species(mon.species)
            if norm:
                species_counter[norm] += 1
        # Collect opponent team species
        for mon in battle.opponent_team.values():
            norm = normalize_species(mon.species)
            if norm:
                species_counter[norm] += 1

    return species_counter


# ---------------------------------------------------------------------------
# Coverage analyzer
# ---------------------------------------------------------------------------

def analyze_coverage(
    species_counter: Counter,
    db_path: str,
    coverage_threshold: float = 60.0,
) -> None:
    """
    Compare species observed in battles against the database and print
    a detailed coverage report.
    """
    if not os.path.exists(db_path):
        print(f"[ERROR] Database not found: {db_path}")
        print("  Please run build_random_set_stats.py first.")
        sys.exit(1)

    with open(db_path, "r") as f:
        db = json.load(f)

    pokemon_db = db.get("pokemon", {})
    db_species_set = set(pokemon_db.keys())
    db_total = len(db_species_set)

    total_encounters = sum(species_counter.values())
    unique_species = set(species_counter.keys())
    unique_count = len(unique_species)

    found_species = unique_species & db_species_set
    missing_species = unique_species - db_species_set

    found_count = len(found_species)
    missing_count = len(missing_species)

    # Coverage by unique species
    if unique_count > 0:
        coverage_unique = (found_count / unique_count) * 100.0
    else:
        coverage_unique = 0.0

    # Coverage weighted by encounter frequency (more meaningful)
    found_encounters = sum(species_counter[sp] for sp in found_species)
    if total_encounters > 0:
        coverage_weighted = (found_encounters / total_encounters) * 100.0
    else:
        coverage_weighted = 0.0

    # Top missing species by encounter frequency
    missing_by_freq = sorted(
        [(sp, species_counter[sp]) for sp in missing_species],
        key=lambda x: x[1],
        reverse=True,
    )

    print()
    print("=" * 70)
    print("  Phase 5.1: Random Set Database Coverage Report")
    print("=" * 70)
    print()
    print(f"  Database Info:")
    print(f"    Source      : {db.get('source', 'unknown')}")
    print(f"    Format      : {db.get('format', 'unknown')}")
    print(f"    Total in DB : {db_total} species")
    print()
    print(f"  Battle Sample:")
    print(f"    Total encounters (slot-turns) : {total_encounters:,}")
    print(f"    Unique species seen           : {unique_count}")
    print()
    print(f"  Coverage Results:")
    print(f"    Species found in DB           : {found_count} / {unique_count}")
    print(f"    Species missing from DB       : {missing_count}")
    print(f"    Coverage (unique species)     : {coverage_unique:.2f}%")
    print(f"    Coverage (weighted encounters): {coverage_weighted:.2f}%")
    print()

    # Threshold check
    check_rate = coverage_weighted  # Use weighted coverage as primary metric
    if check_rate >= coverage_threshold:
        print(f"  ✅ PASS: Weighted coverage {check_rate:.2f}% >= {coverage_threshold:.0f}% threshold.")
        print("     Database is sufficient to proceed with scoring integration.")
    else:
        print(f"  ❌ FAIL: Weighted coverage {check_rate:.2f}% < {coverage_threshold:.0f}% threshold.")
        print("     Improve the database before enabling scoring integration.")

    print()
    if missing_by_freq:
        print(f"  Top Missing Species (by encounter frequency):")
        for i, (sp, count) in enumerate(missing_by_freq[:20]):
            print(f"    {i+1:3d}. {sp:<30s}  (seen {count:4d} times)")
    else:
        print("  No missing species!")

    print()
    if found_species:
        found_sample = sorted(list(found_species))[:10]
        print(f"  Sample species found in DB:")
        for sp in found_sample:
            print(f"    - {sp}")
    print()
    print("=" * 70)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(script_dir, "data", "random_doubles_set_stats.json")

    print("=" * 70)
    print("  Phase 5.1: Random Set Database Coverage Check")
    print("=" * 70)
    print()

    # Option A: Try existing battle logs first
    log_paths = [
        os.path.join(script_dir, "logs", "doubles_battle_results.jsonl"),
        os.path.join(script_dir, "logs", "battle_results.jsonl"),  # singles (for singles species only)
    ]

    print("Step 1: Trying to read existing doubles battle logs...")
    species_counter = load_species_from_logs(log_paths[:1])  # Only doubles log

    if len(species_counter) >= 50:
        print(f"  Found {len(species_counter)} unique species in existing logs.")
        print("  Using existing log data (Option A).")
    else:
        print(f"  Only {len(species_counter)} species found in existing logs.")
        print("  Running fresh battles to collect more species (Option B)...")
        fresh_counter = await run_fresh_battles(n_battles=100)
        for sp, count in fresh_counter.items():
            species_counter[sp] += count
        print(f"  After fresh battles: {len(species_counter)} unique species.")

    # Analyze coverage
    analyze_coverage(
        species_counter=species_counter,
        db_path=db_path,
        coverage_threshold=60.0,
    )


if __name__ == "__main__":
    asyncio.run(main())
