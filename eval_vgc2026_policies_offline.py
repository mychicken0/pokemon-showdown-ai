#!/usr/bin/env python3
"""Offline comparison of VGC team-preview policies."""

import argparse
import json
import math
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from team_preview_policy import choose_four_from_six, score_combination
from vgc_team_pool import load_vgc_pool


POLICIES = ("basic_top4", "random", "matchup_top4_v2")


def shannon_entropy_from_counts(counts: Iterable[int]) -> float:
    """Return Shannon entropy for a count distribution."""
    values = [int(value) for value in counts if int(value) > 0]
    total = sum(values)
    if total == 0:
        return 0.0
    return -sum((value / total) * math.log2(value / total) for value in values)


def percentile(values: Sequence[float], fraction: float) -> float:
    """Linear-interpolated percentile without a numpy dependency."""
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _species_lookup(team: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {pokemon.get("species", ""): pokemon for pokemon in team}


def score_preview_plan(
    team: List[Dict[str, Any]],
    opponent_team: List[Dict[str, Any]],
    lead_2: Sequence[str],
    back_2: Sequence[str],
) -> Tuple[float, Dict[str, Any]]:
    """Score a persisted preview order with the common joint objective."""
    lookup = _species_lookup(team)
    ordered = [lookup[species] for species in list(lead_2) + list(back_2)]
    return score_combination(ordered, opponent_team)


def eval_all_policies(limit_teams: Optional[int] = None) -> Dict[str, Any]:
    """Evaluate all policies over the same deterministic team/opponent pairs."""
    teams = list(load_vgc_pool(max_rank=None, parse_status="any", limit=limit_teams, seed=42))
    opponents = list(
        load_vgc_pool(max_rank=None, parse_status="any", limit=limit_teams, seed=1042)
    )
    results = {policy: [] for policy in POLICIES}

    for index, team in enumerate(teams):
        opponent = opponents[(index + 1) % len(opponents)]
        alternate_opponent = opponents[(index + 2) % len(opponents)]
        seed = 42 + index

        for policy in POLICIES:
            started = time.perf_counter()
            preview = choose_four_from_six(
                team.pokemon,
                opponent_team=opponent.pokemon,
                policy=policy,
                seed=seed,
            )
            runtime_ms = (time.perf_counter() - started) * 1000.0
            joint_score, score_details = score_preview_plan(
                team.pokemon,
                opponent.pokemon,
                preview.lead_2,
                preview.back_2,
            )

            record = {
                "team_id": team.id,
                "opponent_team_id": opponent.id,
                "chosen": list(preview.chosen_4),
                "leads": list(preview.lead_2),
                "backs": list(preview.back_2),
                "joint_score": joint_score,
                "score_details": score_details,
                "runtime_ms": runtime_ms,
            }

            if policy == "matchup_top4_v2":
                alternate = choose_four_from_six(
                    team.pokemon,
                    opponent_team=alternate_opponent.pokemon,
                    policy=policy,
                    seed=seed,
                )
                record["alternate_opponent_team_id"] = alternate_opponent.id
                record["alternate_chosen"] = list(alternate.chosen_4)
                record["alternate_leads"] = list(alternate.lead_2)

            results[policy].append(record)

    return results


def _counter(records: List[Dict[str, Any]], field: str, sort_values: bool) -> Counter:
    values = []
    for record in records:
        value = record[field]
        values.append(tuple(sorted(value)) if sort_values else tuple(value))
    return Counter(values)


def _json_counter(counter: Counter, limit: int = 15) -> Dict[str, int]:
    return {" | ".join(key): value for key, value in counter.most_common(limit)}


def analyze_results(results: Dict[str, Any]) -> Dict[str, Any]:
    """Compute valid diversity, score, adaptation, and runtime metrics."""
    analysis: Dict[str, Any] = {}
    basic_records = results["basic_top4"]
    basic_scores = [record["joint_score"] for record in basic_records]

    for policy in POLICIES:
        records = results[policy]
        chosen_counts = _counter(records, "chosen", sort_values=True)
        lead_counts = _counter(records, "leads", sort_values=False)
        species_counts = Counter(
            species for record in records for species in record["chosen"]
        )
        runtimes = [record["runtime_ms"] for record in records]
        scores = [record["joint_score"] for record in records]

        changed_selections = 0
        changed_leads = 0
        margins = []
        if policy != "basic_top4":
            for basic, candidate in zip(basic_records, records):
                changed_selections += set(basic["chosen"]) != set(candidate["chosen"])
                changed_leads += tuple(basic["leads"]) != tuple(candidate["leads"])
                margins.append(candidate["joint_score"] - basic["joint_score"])
        else:
            margins = [0.0 for _ in records]

        opponent_adaptive = 0
        if policy == "matchup_top4_v2":
            opponent_adaptive = sum(
                set(record["chosen"]) != set(record["alternate_chosen"])
                or tuple(record["leads"]) != tuple(record["alternate_leads"])
                for record in records
            )

        analysis[policy] = {
            "teams_evaluated": len(records),
            "unique_chosen_combos": len(chosen_counts),
            "unique_lead_pairs": len(lead_counts),
            "unique_selected_species": len(species_counts),
            "species_slot_entropy_bits": shannon_entropy_from_counts(
                species_counts.values()
            ),
            "combination_entropy_bits": shannon_entropy_from_counts(
                chosen_counts.values()
            ),
            "lead_pair_entropy_bits": shannon_entropy_from_counts(
                lead_counts.values()
            ),
            "average_matchup_score": statistics.fmean(scores) if scores else 0.0,
            "minimum_matchup_score": min(scores, default=0.0),
            "average_score_margin_vs_basic": (
                statistics.fmean(margins) if margins else 0.0
            ),
            "minimum_score_margin_vs_basic": min(margins, default=0.0),
            "changed_selections_vs_basic": int(changed_selections),
            "changed_leads_vs_basic": int(changed_leads),
            "opponent_adaptive_changes": int(opponent_adaptive),
            "runtime_avg_ms": statistics.fmean(runtimes) if runtimes else 0.0,
            "runtime_p95_ms": percentile(runtimes, 0.95),
            "runtime_max_ms": max(runtimes, default=0.0),
            "top_chosen_species": dict(species_counts.most_common(10)),
            "top_lead_pairs": _json_counter(lead_counts),
        }

    analysis["cross_comparison"] = {
        "basic_vs_matchup_differ": analysis["matchup_top4_v2"][
            "changed_selections_vs_basic"
        ],
        "basic_vs_random_differ": analysis["random"][
            "changed_selections_vs_basic"
        ],
    }
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline preview-policy evaluation")
    parser.add_argument("--limit-teams", type=int, default=None)
    parser.add_argument(
        "--output",
        default="logs/vgc2026_policy_comparison_v2d1.json",
    )
    args = parser.parse_args()

    results = eval_all_policies(limit_teams=args.limit_teams)
    analysis = analyze_results(results)
    output = {
        "results_summary": {
            policy: f"{len(records)} teams" for policy, records in results.items()
        },
        "analysis": analysis,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2))

    for policy in POLICIES:
        metrics = analysis[policy]
        print(f"\n{policy}:")
        print(f"  Unique chosen-4 combos: {metrics['unique_chosen_combos']}")
        print(f"  Unique lead pairs: {metrics['unique_lead_pairs']}")
        print(
            f"  Species-slot entropy: "
            f"{metrics['species_slot_entropy_bits']:.3f} bits"
        )
        print(
            f"  Combination entropy: "
            f"{metrics['combination_entropy_bits']:.3f} bits"
        )
        print(
            f"  Matchup score avg/min: "
            f"{metrics['average_matchup_score']:.3f}/"
            f"{metrics['minimum_matchup_score']:.3f}"
        )
        print(
            f"  Runtime avg/p95/max: "
            f"{metrics['runtime_avg_ms']:.3f}/"
            f"{metrics['runtime_p95_ms']:.3f}/"
            f"{metrics['runtime_max_ms']:.3f} ms"
        )
        print(
            f"  Changed selection/lead vs basic: "
            f"{metrics['changed_selections_vs_basic']}/"
            f"{metrics['changed_leads_vs_basic']}"
        )

    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
