#!/usr/bin/env python3
"""
VGC 2026 Phase V2e — Pair inspector for V2d qualification artifacts.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

sys.path.insert(0, '/home/phurin/Program/Showdown_AI/pokemon-showdown-ai')

from team_preview_policy import choose_four_from_six, PreviewResult
from vgc_team_pool import load_vgc_pool


def load_benchmark(artifact_tag: str = "phaseV2d2_paired_qualification_codex"):
    logs_dir = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs")
    prefix = f"vgc2026_phaseV2c_{artifact_tag}"
    path = logs_dir / f"{prefix}_benchmark.csv"
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


def load_preview(artifact_tag: str = "phaseV2d2_paired_qualification_codex"):
    logs_dir = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs")
    prefix = f"vgc2026_phaseV2c_{artifact_tag}"
    path = logs_dir / f"{prefix}_preview_evidence.csv"
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


def print_pair(pair_id: int, artifact_tag: str = "phaseV2d2_paired_qualification_codex"):
    """Print detailed analysis for a specific pair."""
    benchmark_rows = load_benchmark(artifact_tag)
    preview_rows = load_preview(artifact_tag)

    d1_rows = [r for r in benchmark_rows
               if r['battle_tag'].startswith('D1_')
               and int(r['pair_id']) == pair_id]
    d2_rows = [r for r in benchmark_rows
               if r['battle_tag'].startswith('D2_')
               and int(r['pair_id']) == pair_id]

    if not d1_rows or not d2_rows:
        print(f"Pair {pair_id} not found in D1/D2")
        return

    d1 = d1_rows[0]
    d2 = d2_rows[0]

    # Determine outcomes
    d1_v2 = "win" if d1['our_win'] == 'True' else "loss"
    d2_v2 = "win" if d2['opponent_win'] == 'True' else "loss"

    if d1_v2 == "win" and d2_v2 == "win":
        outcome = "V2 BOTH WIN"
    elif d1_v2 == "loss" and d2_v2 == "loss":
        outcome = "RANDOM BOTH WIN"
    else:
        outcome = "SPLIT"

    print(f"\n{'='*60}")
    print(f"PAIR {pair_id}: {outcome}")
    print(f"{'='*60}")
    print(f"D1 (V2 as player):  {d1['battle_tag']} -> {d1['battle_result']} ({d1_v2})")
    print(f"D2 (V2 as opponent): {d2['battle_tag']} -> {d2['battle_result']} ({d2_v2})")

    print(f"\nTeams:")
    print(f"  Our team (D1):     {d1['team_id']} vs {d1['opponent_team_id']}")
    print(f"  Our team (D2):     {d2['team_id']} vs {d2['opponent_team_id']}")

    # Preview selections
    print(f"\nD1 Preview Selections (V2):")
    print(f"  Chosen 4: {d1['chosen_4']}")
    print(f"  Lead 2:   {d1['lead_2']}")
    print(f"  Back 2:   {d1['back_2']}")
    print(f"  Opp 4:    {d1['opponent_chosen_4']}")
    print(f"  Result:   {d1['battle_result']} ({d1['turns']} turns)")

    print(f"\nD2 Preview Selections (V2):")
    print(f"  Chosen 4: {d2['chosen_4']}")
    print(f"  Lead 2:   {d2['lead_2']}")
    print(f"  Back 2:   {d2['back_2']}")
    print(f"  Opp 4:    {d2['opponent_chosen_4']}")
    print(f"  Result:   {d2['battle_result']} ({d2['turns']} turns)")

    # Preview evidence
    d1_previews = [p for p in load_preview(artifact_tag)
                   if int(p['pair_id']) == pair_id and p['battle_tag'].startswith('D1')]
    d2_previews = [p for p in load_preview(artifact_tag)
                   if int(p['pair_id']) == pair_id and p['battle_tag'].startswith('D2')]

    print(f"\nPreview Evidence (D1):")
    if d1_previews:
        p = d1_previews[0]
        print(f"  Planned Lead 2: {p['planned_lead_2']}")
        print(f"  Emitted:        {p['emitted_teampreview']}")
        print(f"  Observed Lead:  {p['observed_actual_lead_on_turn1']}")
        print(f"  Match:          {p['preview_matches_plan']}")

    print(f"Preview Evidence (D2):")
    if d2_previews:
        p = d2_previews[0]
        print(f"  Planned Lead 2: {p['planned_lead_2']}")
        print(f"  Emitted:        {p['emitted_teampreview']}")
        print(f"  Observed Lead:  {p['observed_actual_lead_on_turn1']}")
        print(f"  Match:          {p['preview_matches_plan']}")


def list_pairs(artifact_tag: str = "phaseV2d2_paired_qualification_codex"):
    """List all pairs with outcomes."""
    benchmark_rows = load_benchmark(artifact_tag)

    d_battles = [r for r in benchmark_rows
                 if r['battle_tag'].startswith(('D1_', 'D2_'))]

    pairs = []
    for pair_id in sorted(set(int(r['pair_id']) for r in d_battles)):
        d1 = next((r for r in d_battles if r['battle_tag'].startswith('D1_') and int(r['pair_id']) == pair_id), None)
        d2 = next((r for r in d_battles if r['battle_tag'].startswith('D2_') and int(r['pair_id']) == pair_id), None)

        if d1 and d2:
            d1_v2 = "WIN" if d1['our_win'] == 'True' else "LOSS"
            d2_v2 = "WIN" if d2['opponent_win'] == 'True' else "LOSS"

            if d1['our_win'] == 'True' and d2['opponent_win'] == 'True':
                outcome = "V2 BOTH"
            elif d1['our_win'] != 'True' and d2['opponent_win'] != 'True':
                outcome = "RAND BOTH"
            else:
                outcome = "SPLIT"

            pairs.append({
                "pair_id": pair_id,
                "outcome": outcome,
                "d1_result": d1['battle_result'],
                "d2_result": d2['battle_result'],
                "d1_chosen": d1['chosen_4'],
                "d2_chosen": d2['chosen_4'],
                "turns": f"{d1['turns']}/{d2['turns']}",
            })

    # Print table
    print(f"\n{'Pair':>4}  {'Outcome':<10}  {'D1':>5}  {'D2':>5}  {'Turns':>6}  D1 Chosen")
    print("-" * 100)
    for p in pairs:
        print(f"{p['pair_id']:>4}  {p['outcome']:<10}  {p['d1_result']:>5}  {p['d2_result']:>5}  {p['turns']:>6}  {p['d1_chosen']}")


def main():
    parser = argparse.ArgumentParser(description="VGC 2026 Phase V2e Pair Inspector")
    parser.add_argument("--artifact-tag", default="phaseV2d2_paired_qualification_codex")
    parser.add_argument("--pair-id", type=int, help="Inspect specific pair")
    parser.add_argument("--list", action="store_true", help="List all pairs with outcomes")
    args = parser.parse_args()

    if args.list:
        list_pairs(args.artifact_tag)
    elif args.pair_id is not None:
        print_pair(args.pair_id, args.artifact_tag)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()