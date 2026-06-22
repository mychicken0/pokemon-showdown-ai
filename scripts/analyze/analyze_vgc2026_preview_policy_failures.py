#!/usr/bin/env python3
"""
VGC 2026 basic_top4 Policy Failure Analysis — Phase V2d

Offline diagnostic analysis of why basic_top4 underperforms.
Does not run battles; only inspects existing tagged artifacts.
"""

import json
import csv
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import Counter, defaultdict
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from team_preview_policy import (
    choose_four_from_six, PreviewResult, validate_preview,
    score_pokemon, calculate_type_matchup, get_species_types,
    SPECIES_TYPES, TYPE_CHART
)
from vgc_team_pool import load_vgc_pool

# Artifact safety: use only tagged artifacts
DEFAULT_ARTIFACT_TAG = "phaseV2c2_smoke_test"  # This is the 450-battle tagged run


@dataclass
class PairDiagnostic:
    """Diagnostic for a single D1/D2 pair."""
    pair_id: int
    our_team_idx: int
    opp_team_idx: int
    side: str  # "p1" or "p2"
    our_team_id: str
    opp_team_id: str
    our_chosen_4: List[str]
    our_lead_2: List[str]
    our_back_2: List[str]
    opp_chosen_4: List[str]
    opp_lead_2: List[str]
    opp_back_2: List[str]
    our_scores: List[Dict]
    opp_scores: List[Dict]
    battle_result: str
    our_win: bool


def load_tagged_artifact(artifact_tag: str, artifact_type: str) -> pd.DataFrame:
    """Load a tagged artifact CSV/JSONL."""
    logs_dir = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs")

    if artifact_type == "benchmark":
        path = logs_dir / f"vgc2026_phaseV2c_{artifact_tag}_benchmark.csv"
        return pd.read_csv(path)
    elif artifact_type == "benchmark_jsonl":
        path = logs_dir / f"vgc2026_phaseV2c_{artifact_tag}_benchmark.jsonl"
        records = []
        with open(path) as f:
            for line in f:
                records.append(json.loads(line))
        return pd.DataFrame(records)
    elif artifact_type == "preview":
        path = logs_dir / f"vgc2026_phaseV2c_{artifact_tag}_preview_evidence.csv"
        return pd.read_csv(path)
    else:
        raise ValueError(f"Unknown artifact_type: {artifact_type}")


def reconstruct_pair_diagnostics(
    benchmark_df: pd.DataFrame,
    preview_df: pd.DataFrame,
    my_pool,
    opp_pool
) -> List[PairDiagnostic]:
    """Reconstruct D1/D2 paired diagnostics from tagged artifacts."""

    # Filter to D arms only
    d_battles = benchmark_df[benchmark_df['battle_tag'].str.startswith(('D1_', 'D2_'))].copy()

    # Build species->team mapping for reconstruction
    my_teams = list(my_pool)
    opp_teams = list(opp_pool)

    my_team_lookup = {t.id: t for t in my_teams}
    opp_team_lookup = {t.id: t for t in opp_teams}

    diagnostics = []

    # Group by pair_id and side - D1 and D2 should share same pair_id
    for pair_id in sorted(d_battles['pair_id'].unique()):
        d1_row = d_battles[(d_battles['pair_id'] == pair_id) & (d_battles['side'] == 'p1')]
        d2_row = d_battles[(d_battles['pair_id'] == pair_id) & (d_battles['side'] == 'p2')]

        if len(d1_row) == 0 or len(d2_row) == 0:
            continue

        d1 = d1_row.iloc[0]
        d2 = d2_row.iloc[0]

        # For our side perspective (basic_top4 vs random)
        our_team = my_team_lookup.get(d1['team_id'])
        opp_team = opp_team_lookup.get(d1['opponent_team_id'])

        if not our_team or not opp_team:
            continue

        # Re-run basic_top4 policy to get scores
        our_preview = choose_four_from_six(
            our_team.pokemon, opponent_team=opp_team.pokemon,
            policy="basic_top4", seed=int((42 + pair_id * 1000) % (2**32))
        )

        opp_preview = choose_four_from_six(
            opp_team.pokemon, opponent_team=our_team.pokemon,
            policy="random", seed=int((42 + pair_id * 1000 + 1) % (2**32))
        )

        diag = PairDiagnostic(
            pair_id=pair_id,
            our_team_idx=my_teams.index(our_team) if our_team in my_teams else -1,
            opp_team_idx=opp_teams.index(opp_team) if opp_team in opp_teams else -1,
            side="p1",
            our_team_id=our_team.id,
            opp_team_id=opp_team.id,
            our_chosen_4=our_preview.chosen_4,
            our_lead_2=our_preview.lead_2,
            our_back_2=our_preview.back_2,
            opp_chosen_4=opp_preview.chosen_4,
            opp_lead_2=opp_preview.lead_2,
            opp_back_2=opp_preview.back_2,
            our_scores=[asdict(s) for s in our_preview.scores],
            opp_scores=[asdict(s) for s in opp_preview.scores],  # empty for random
            battle_result=d1['battle_result'],
            our_win=d1['our_win']
        )
        diagnostics.append(diag)

        # Also D2 perspective (same teams, swapped sides)
        diag2 = PairDiagnostic(
            pair_id=pair_id,
            our_team_idx=my_teams.index(our_team) if our_team in my_teams else -1,
            opp_team_idx=opp_teams.index(opp_team) if opp_team in opp_teams else -1,
            side="p2",
            our_team_id=our_team.id,
            opp_team_id=opp_team.id,
            our_chosen_4=our_preview.chosen_4,
            our_lead_2=our_preview.lead_2,
            our_back_2=our_preview.back_2,
            opp_chosen_4=opp_preview.chosen_4,
            opp_lead_2=opp_preview.lead_2,
            opp_back_2=opp_preview.back_2,
            our_scores=[asdict(s) for s in our_preview.scores],
            opp_scores=[asdict(s) for s in opp_preview.scores],
            battle_result=d2['battle_result'],
            our_win=d2['our_win']
        )
        diagnostics.append(diag2)

    return diagnostics


def analyze_score_breakdown(diagnostics: List[PairDiagnostic]) -> Dict[str, Any]:
    """Analyze scoring component breakdown across all pairs."""

    # Collect all score components
    components = defaultdict(list)
    all_scores = []

    for d in diagnostics:
        for s in d.our_scores:
            all_scores.append(s)
            for key in ['fake_out', 'intimidate', 'tailwind', 'trick_room',
                       'redirection', 'spread_move', 'protect',
                       'type_matchup', 'weakness_avoidance', 'total']:
                components[key].append(s.get(key, 0))

    analysis = {}
    for key, values in components.items():
        if values:
            analysis[key] = {
                'mean': float(np.mean(values)),
                'std': float(np.std(values)),
                'min': float(np.min(values)),
                'max': float(np.max(values)),
                'zero_count': sum(1 for v in values if v == 0),
                'nonzero_count': sum(1 for v in values if v > 0)
            }

    return analysis


def analyze_selection_patterns(diagnostics: List[PairDiagnostic]) -> Dict[str, Any]:
    """Analyze species/archetype selection patterns."""

    # Count chosen vs omitted
    chosen_counts = Counter()
    lead_counts = Counter()
    back_counts = Counter()
    omitted_in_favor_of = defaultdict(Counter)

    for d in diagnostics:
        chosen_set = set(d.our_chosen_4)
        lead_set = set(d.our_lead_2)
        back_set = set(d.our_back_2)

        for s in d.our_chosen_4:
            chosen_counts[s] += 1
        for s in d.our_lead_2:
            lead_counts[s] += 1
        for s in d.our_back_2:
            back_counts[s] += 1

    # Calculate selection rates
    total_pairs = len(diagnostics)
    selection_rates = {s: c/total_pairs for s, c in chosen_counts.items()}
    lead_rates = {s: c/total_pairs for s, c in lead_counts.items()}
    back_rates = {s: c/total_pairs for s, c in back_counts.items()}

    return {
        'chosen_counts': dict(chosen_counts),
        'lead_counts': dict(lead_counts),
        'back_counts': dict(back_counts),
        'selection_rates': selection_rates,
        'lead_rates': lead_rates,
        'back_rates': back_rates,
        'total_unique_chosen': len(chosen_counts),
        'total_pairs': total_pairs
    }


def analyze_basic_losses(diagnostics: List[PairDiagnostic]) -> Dict[str, Any]:
    """Analyze species/archetypes overrepresented in basic_top4 losses."""

    losses = [d for d in diagnostics if not d.our_win]
    wins = [d for d in diagnostics if d.our_win]

    loss_chosen = Counter()
    win_chosen = Counter()
    loss_leads = Counter()
    win_leads = Counter()

    for d in losses:
        for s in d.our_chosen_4:
            loss_chosen[s] += 1
        for s in d.our_lead_2:
            loss_leads[s] += 1

    for d in wins:
        for s in d.our_chosen_4:
            win_chosen[s] += 1
        for s in d.our_lead_2:
            win_leads[s] += 1

    loss_rates = {s: c/len(losses) if losses else 0 for s, c in loss_chosen.items()}
    win_rates = {s: c/len(wins) if wins else 0 for s, c in win_chosen.items()}

    # Find overrepresented in losses
    overrepresented = {}
    for s in set(loss_chosen.keys()) | set(win_chosen.keys()):
        lr = loss_rates.get(s, 0)
        wr = win_rates.get(s, 0)
        if lr > wr * 1.5 and lr > 0.1:  # 50% higher rate in losses
            overrepresented[s] = {'loss_rate': lr, 'win_rate': wr, 'ratio': lr/wr if wr > 0 else float('inf')}

    return {
        'loss_species_rates': loss_rates,
        'win_species_rates': win_rates,
        'overrepresented_in_losses': overrepresented,
        'total_losses': len(losses),
        'total_wins': len(wins)
    }


def analyze_score_margins(diagnostics: List[PairDiagnostic]) -> Dict[str, Any]:
    """Analyze score margins between selected and omitted Pokémon."""

    margins = []
    low_diversity_pairs = 0

    for d in diagnostics:
        scores = {s['species']: s['total'] for s in d.our_scores}
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        if len(sorted_scores) >= 5:
            # Margin between 4th and 5th (selection boundary)
            margin_4_5 = sorted_scores[3][1] - sorted_scores[4][1]
            margins.append(margin_4_5)

            # Check for low diversity (top 4 all > X, bottom 2 all < Y)
            if sorted_scores[3][1] - sorted_scores[5][1] < 0.5:
                low_diversity_pairs += 1

    return {
        'margin_4th_vs_5th': {
            'mean': float(np.mean(margins)) if margins else 0,
            'std': float(np.std(margins)) if margins else 0,
            'min': float(np.min(margins)) if margins else 0,
            'median': float(np.median(margins)) if margins else 0
        },
        'low_diversity_pairs': low_diversity_pairs,
        'total_pairs': len(diagnostics)
    }


def analyze_lead_back_patterns(diagnostics: List[PairDiagnostic]) -> Dict[str, Any]:
    """Analyze lead and back-slot patterns."""

    lead_patterns = Counter()
    back_patterns = Counter()

    for d in diagnostics:
        lead_tuple = tuple(sorted(d.our_lead_2))
        back_tuple = tuple(sorted(d.our_back_2))
        lead_patterns[lead_tuple] += 1
        back_patterns[back_tuple] += 1

    # Check for fixed/predictable leads
    total = len(diagnostics)
    fixed_leads = sum(1 for c in lead_patterns.values() if c == total)
    dominant_lead = max(lead_patterns.items(), key=lambda x: x[1]) if lead_patterns else None

    return {
        'unique_lead_pairs': len(lead_patterns),
        'unique_back_pairs': len(back_patterns),
        'lead_pattern_counts': {str(k): v for k, v in lead_patterns.most_common(10)},
        'back_pattern_counts': {str(k): v for k, v in back_patterns.most_common(10)},
        'fixed_leads': fixed_leads,
        'dominant_lead': str(dominant_lead[0]) if dominant_lead else None,
        'dominant_lead_rate': dominant_lead[1]/total if dominant_lead else 0
    }


def compute_entropy(selection_rates: Dict[str, float]) -> float:
    """Compute Shannon entropy of selection distribution."""
    probs = list(selection_rates.values())
    if not probs:
        return 0.0
    return -sum(p * np.log2(p) for p in probs if p > 0)


def run_analysis(artifact_tag: str = DEFAULT_ARTIFACT_TAG, output_dir: str = "logs") -> Dict[str, Any]:
    """Run complete basic_top4 failure analysis."""

    print(f"Loading artifacts with tag: {artifact_tag}")
    benchmark_df = load_tagged_artifact(artifact_tag, "benchmark")
    preview_df = load_tagged_artifact(artifact_tag, "preview")

    print(f"Loading team pools...")
    my_pool = load_vgc_pool(max_rank=None, parse_status="any", limit=None, seed=42)
    opp_pool = load_vgc_pool(max_rank=None, parse_status="any", limit=None, seed=42 + 1000)

    print(f"Reconstructing {len(benchmark_df)} battles...")
    diagnostics = reconstruct_pair_diagnostics(benchmark_df, preview_df, my_pool, opp_pool)
    print(f"Diagnostics for {len(diagnostics)} paired sides ({len(diagnostics)//2} unique pairs)")

    # Run all analyses
    score_analysis = analyze_score_breakdown(diagnostics)
    selection_patterns = analyze_selection_patterns(diagnostics)
    basic_losses = analyze_basic_losses(diagnostics)
    score_margins = analyze_score_margins(diagnostics)
    lead_back = analyze_lead_back_patterns(diagnostics)

    # Compute entropy
    entropy = compute_entropy(selection_patterns['selection_rates'])

    # Build final report
    report = {
        'artifact_tag': artifact_tag,
        'total_battles_analyzed': len(benchmark_df),
        'unique_pairs_analyzed': len(diagnostics) // 2,
        'score_breakdown': score_analysis,
        'selection_patterns': selection_patterns,
        'basic_losses_analysis': basic_losses,
        'score_margins': score_margins,
        'lead_back_patterns': lead_back,
        'selection_entropy': entropy,
        'summary': {
            'unique_species_chosen': selection_patterns['total_unique_chosen'],
            'entropy': entropy,
            'overrepresented_in_losses': len(basic_losses['overrepresented_in_losses']),
            'low_diversity_pairs': score_margins['low_diversity_pairs'],
            'unique_lead_pairs': lead_back['unique_lead_pairs'],
            'dominant_lead_rate': lead_back['dominant_lead_rate'],
            'mean_selection_margin': score_margins['margin_4th_vs_5th']['mean']
        }
    }

    # Save JSON report
    output_path = Path(output_dir) / f"vgc2026_basic_top4_diagnostic_{artifact_tag}.json"
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Report saved to {output_path}")

    return report


def main():
    parser = argparse.ArgumentParser(description="VGC 2026 basic_top4 Policy Failure Analysis")
    parser.add_argument("--artifact-tag", default=DEFAULT_ARTIFACT_TAG)
    parser.add_argument("--output-dir", default="logs")
    args = parser.parse_args()

    report = run_analysis(args.artifact_tag, args.output_dir)

    # Print summary
    s = report['summary']
    print(f"\n=== Summary ===")
    print(f"Artifact: {report['artifact_tag']}")
    print(f"Unique pairs analyzed: {report['unique_pairs_analyzed']}")
    print(f"Unique species chosen: {s['unique_species_chosen']}")
    print(f"Selection entropy: {s['entropy']:.3f} bits")
    print(f"Overrepresented in losses: {s['overrepresented_in_losses']} species")
    print(f"Low-diversity pairs: {s['low_diversity_pairs']}/{report['unique_pairs_analyzed']}")
    print(f"Unique lead pairs: {s['unique_lead_pairs']}")
    print(f"Dominant lead rate: {s['dominant_lead_rate']:.1%}")
    print(f"Mean selection margin (4th vs 5th): {s['mean_selection_margin']:.3f}")

    # Score breakdown
    print(f"\n=== Score Breakdown ===")
    for comp, stats in report['score_breakdown'].items():
        print(f"  {comp}: mean={stats['mean']:.3f}, zero={stats['zero_count']}, nonzero={stats['nonzero_count']}")


if __name__ == "__main__":
    main()