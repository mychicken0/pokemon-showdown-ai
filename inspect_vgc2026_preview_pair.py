#!/usr/bin/env python3
"""
VGC 2026 Preview Pair Inspector — Phase V2d

Interactive/offline inspector for preview selections from tagged artifacts.
"""

import json
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import asdict

import pandas as pd

sys.path.insert(0, '/home/phurin/Program/Showdown_AI/pokemon-showdown-ai')

from team_preview_policy import choose_four_from_six, PreviewResult, validate_preview
from vgc_team_pool import load_vgc_pool


def load_artifact(artifact_tag: str, artifact_type: str) -> pd.DataFrame:
    logs_dir = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs")

    if artifact_type == "benchmark":
        path = logs_dir / f"vgc2026_phaseV2c_{artifact_tag}_benchmark.csv"
        return pd.read_csv(path)
    elif artifact_type == "preview":
        path = logs_dir / f"vgc2026_phaseV2c_{artifact_tag}_preview_evidence.csv"
        return pd.read_csv(path)
    else:
        raise ValueError(f"Unknown artifact_type: {artifact_type}")


def inspect_pair(
    artifact_tag: str,
    pair_id: int,
    my_pool,
    opp_pool,
    side: str = "p1"
) -> Dict[str, Any]:
    """Inspect a specific D1/D2 pair."""

    benchmark_df = load_artifact(artifact_tag, "benchmark")
    preview_df = load_artifact(artifact_tag, "preview")

    my_teams = list(my_pool)
    opp_teams = list(opp_pool)
    my_team_lookup = {t.id: t for t in my_teams}
    opp_team_lookup = {t.id: t for t in opp_teams}

    d_battles = benchmark_df[benchmark_df['battle_tag'].str.startswith(('D1_', 'D2_'))].copy()

    d1_row = d_battles[(d_battles['pair_id'] == pair_id) & (d_battles['side'] == side)].copy()
    if len(d1_row) == 0:
        raise ValueError(f"No battle found for pair_id={pair_id}, side={side}")

    d1 = d1_row.iloc[0]
    our_team = my_team_lookup.get(d1['team_id'])
    opp_team = opp_team_lookup.get(d1['opponent_team_id'])

    if not our_team or not opp_team:
        raise ValueError(f"Teams not found: {d1['team_id']} or {d1['opponent_team_id']}")

    # Re-run policies
    our_preview = choose_four_from_six(
        our_team.pokemon, opponent_team=opp_team.pokemon,
        policy="basic_top4", seed=int((42 + pair_id * 1000) % (2**32))
    )
    opp_preview = choose_four_from_six(
        opp_team.pokemon, opponent_team=our_team.pokemon,
        policy="random", seed=int((42 + pair_id * 1000 + 1) % (2**32))
    )

    # Also get the opposite side
    opp_side = "p2" if side == "p1" else "p1"

    return {
        "pair_id": pair_id,
        "side": side,
        "our_team": {
            "id": our_team.id,
            "rank": our_team.rank,
            "player": our_team.player,
            "pokemon": [p.get("species", "") for p in our_team.pokemon]
        },
        "opp_team": {
            "id": opp_team.id,
            "rank": opp_team.rank,
            "player": opp_team.player,
            "pokemon": [p.get("species", "") for p in opp_team.pokemon]
        },
        "our_policy": {
            "name": "basic_top4",
            "chosen_4": our_preview.chosen_4,
            "lead_2": our_preview.lead_2,
            "back_2": our_preview.back_2,
            "scores": [asdict(s) for s in our_preview.scores]
        },
        "opp_policy": {
            "name": "random",
            "chosen_4": opp_preview.chosen_4,
            "lead_2": opp_preview.lead_2,
            "back_2": opp_preview.back_2,
            "scores": []  # random has no scores
        },
        "battle_result": d1['battle_result'],
        "turns": d1['turns'],
        "our_win": d1['our_win'],
        "preview_evidence": preview_df[
            (preview_df['pair_id'] == pair_id) & (preview_df['side'] == side)
        ].to_dict('records')
    }


def list_pairs(artifact_tag: str, arm: str = "D") -> List[Dict[str, Any]]:
    """List all pairs for a given arm."""
    benchmark_df = load_artifact(artifact_tag, "benchmark")

    if arm == "D":
        d_battles = benchmark_df[benchmark_df['battle_tag'].str.startswith(('D1_', 'D2_'))].copy()
    else:
        d_battles = benchmark_df[benchmark_df['battle_tag'].str.startswith(f'{arm}_')].copy()

    pairs = []
    for pair_id in sorted(d_battles['pair_id'].unique()):
        d1 = d_battles[(d_battles['pair_id'] == pair_id) & (d_battles['side'] == 'p1')]
        d2 = d_battles[(d_battles['pair_id'] == pair_id) & (d_battles['side'] == 'p2')]

        if len(d1) == 0 or len(d2) == 0:
            continue

        d1 = d1.iloc[0]
        d2 = d2.iloc[0]

        pairs.append({
            "pair_id": pair_id,
            "d1_result": d1['battle_result'],
            "d1_our_win": d1['our_win'],
            "d2_result": d2['battle_result'],
            "d2_our_win": d2['our_win'],
            "our_team_id": d1['team_id'],
            "opp_team_id": d1['opponent_team_id'],
            "our_chosen_4": d1['chosen_4'],
            "our_lead_2": d1['lead_2'],
            "our_back_2": d1['back_2'],
            "opp_chosen_4": d1['opponent_chosen_4'],
            "opp_lead_2": d1['opponent_lead_2'] if 'opponent_lead_2' in d1 else '',
            "opp_back_2": d1['opponent_back_2'] if 'opponent_back_2' in d1 else ''
        })

    return pairs


def print_pair_inspection(inspection: Dict[str, Any]):
    """Pretty print a pair inspection."""
    print(f"\n=== Pair {inspection['pair_id']} (side={inspection['side']}) ===")
    print(f"Battle result: {inspection['battle_result']} (our_win={inspection['our_win']}, turns={inspection['turns']})")

    print(f"\nOur team: {inspection['our_team']['id']} (rank {inspection['our_team']['rank']}, {inspection['our_team']['player']})")
    print(f"  Species: {', '.join(inspection['our_team']['pokemon'])}")

    print(f"\nOpponent team: {inspection['opp_team']['id']} (rank {inspection['opp_team']['rank']}, {inspection['opp_team']['player']})")
    print(f"  Species: {', '.join(inspection['opp_team']['pokemon'])}")

    print(f"\nOur policy ({inspection['our_policy']['name']}):")
    print(f"  Chosen 4: {', '.join(inspection['our_policy']['chosen_4'])}")
    print(f"  Leads:    {', '.join(inspection['our_policy']['lead_2'])}")
    print(f"  Backs:    {', '.join(inspection['our_policy']['back_2'])}")
    print(f"  Scores:")
    for s in inspection['our_policy']['scores']:
        print(f"    {s['species']}: total={s['total']:.2f} "
              f"(fo={s['fake_out']}, int={s['intimidate']}, tw={s['tailwind']}, "
              f"rd={s['redirection']}, spr={s['spread_move']}, pr={s['protect']}, "
              f"tm={s['type_matchup']:.2f}, wa={s['weakness_avoidance']:.2f}) "
              f"role={s['role']}")

    print(f"\nOpponent policy ({inspection['opp_policy']['name']}):")
    print(f"  Chosen 4: {', '.join(inspection['opp_policy']['chosen_4'])}")
    print(f"  Leads:    {', '.join(inspection['opp_policy']['lead_2'])}")
    print(f"  Backs:    {', '.join(inspection['opp_policy']['back_2'])}")


def print_pairs_list(pairs: List[Dict[str, Any]], arm: str):
    """Print a list of pairs."""
    print(f"\n=== {arm} Arm Pairs ({len(pairs)} pairs) ===")
    for p in pairs:
        our_result = "WIN" if p['d1_our_win'] else "LOSS"
        opp_result = "WIN" if p['d2_our_win'] else "LOSS"
        print(f"  Pair {p['pair_id']:3d}: D1={p['d1_result']:4s}({our_result:4s}) | "
              f"D2={p['d2_result']:4s}({opp_result:4s}) | "
              f"Our: {' > '.join(p['our_chosen_4'].split('|'))} | "
              f"Opp: {' > '.join(p['opp_chosen_4'].split('|'))}")


def main():
    parser = argparse.ArgumentParser(description="VGC 2026 Preview Pair Inspector")
    parser.add_argument("--artifact-tag", default="phaseV2c2_smoke_test")
    parser.add_argument("--pair-id", type=int, help="Inspect specific pair")
    parser.add_argument("--side", choices=["p1", "p2"], default="p1", help="Side to inspect")
    parser.add_argument("--list-arm", choices=["A", "B", "C", "D"], help="List all pairs for arm")

    args = parser.parse_args()

    my_pool = load_vgc_pool(max_rank=None, parse_status="any", limit=None, seed=42)
    opp_pool = load_vgc_pool(max_rank=None, parse_status="any", limit=None, seed=42 + 1000)

    if args.list_arm:
        pairs = list_pairs(args.artifact_tag, args.list_arm)
        print_pairs_list(pairs, args.list_arm)

    elif args.pair_id is not None:
        inspection = inspect_pair(args.artifact_tag, args.pair_id, my_pool, opp_pool, args.side)
        print_pair_inspection(inspection)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()