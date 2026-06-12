#!/usr/bin/env python3
"""
VGC 2026 Phase V2e.1 — Offline policy comparison.

Corrects the four V2e defects in the previous
`eval_vgc2026_phaseV2e_policies.py`:

1. Cross-policy score margins used different score scales (basic_top4
   summed individual Pokémon scores, V2/V3 used their own joint-plan
   scores). All four policies are now evaluated on the common external
   scale defined in `vgc2026_common_plan_evaluator`.

2. Score metrics used a 20-team sample and diversity metrics used 129
   teams. Both now use the same 129-team denominator by default, and
   the per-policy denominator is reported explicitly.

3. Opponent-adaptation used only a single 10-team sample. It now uses
   the full 129 teams against two distinct, deterministic opponents
   and reports the denominator.

4. Random policy used time-based seeds rather than a fixed seed. The
   random policy now receives an explicit seed and the analysis uses a
   deterministic seed schedule.

Inputs: identical team/opponent pairs for every policy. The opponent
is `opponents[(i + 1) % N]`, where `N` is the number of teams.

No battles are run. The script writes a single JSON report and a
Markdown summary.
"""

import argparse
import json
import math
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import sys

sys.path.insert(0, "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai")

from team_preview_policy import choose_four_from_six
from vgc2026_common_plan_evaluator import (
    CommonPlanEvaluatorError,
    CommonPlanScore,
    evaluate_plan_on_common_scale,
)
from vgc_team_pool import load_vgc_pool


POLICIES: Tuple[str, ...] = (
    "basic_top4",
    "random",
    "matchup_top4_v2",
    "matchup_top4_v3",
)
V2E1_DENOMINATOR: int = 129


# ---------------------------------------------------------------------------
# Per-team evaluation
# ---------------------------------------------------------------------------


def evaluate_team_against_opponent(
    team_pokemon: Sequence[Mapping[str, Any]],
    opponent_pokemon: Sequence[Mapping[str, Any]],
    seed: int,
) -> Dict[str, Any]:
    """Run every policy on the same team/opponent pair and evaluate
    each plan with the common external evaluator.

    Returns a per-team dictionary keyed by policy. Each entry contains
    the chosen plan plus the common-evaluator score breakdown.
    Runtime is measured per policy.
    """
    out: Dict[str, Any] = {"seed": seed, "policies": {}}
    for policy in POLICIES:
        started = time.perf_counter()
        preview = choose_four_from_six(
            team_pokemon,
            opponent_team=opponent_pokemon,
            policy=policy,
            seed=seed,
        )
        try:
            score = evaluate_plan_on_common_scale(
                team=team_pokemon,
                opponent_team=opponent_pokemon,
                chosen_4=preview.chosen_4,
                lead_2=preview.lead_2,
                back_2=preview.back_2,
            )
        except CommonPlanEvaluatorError as exc:
            out["policies"][policy] = {
                "error": str(exc),
                "chosen_4": list(preview.chosen_4),
                "lead_2": list(preview.lead_2),
                "back_2": list(preview.back_2),
                "runtime_ms": (time.perf_counter() - started) * 1000.0,
            }
            continue
        out["policies"][policy] = {
            "chosen_4": list(preview.chosen_4),
            "lead_2": list(preview.lead_2),
            "back_2": list(preview.back_2),
            "common_total": score.total,
            "components": score.components,
            "runtime_ms": (time.perf_counter() - started) * 1000.0,
        }
    return out


def evaluate_all_policies(
    limit_teams: Optional[int] = None,
) -> Dict[str, Any]:
    """Run the four policies on identical 129-team (or limited) inputs."""
    pool = list(
        load_vgc_pool(
            max_rank=None, parse_status="any", limit=limit_teams, seed=42
        )
    )
    opponent_pool = list(
        load_vgc_pool(
            max_rank=None, parse_status="any", limit=limit_teams,
            seed=1042,
        )
    )
    if not pool or not opponent_pool:
        return {
            "denominator_teams": 0,
            "denominator_opponents": 0,
            "policies": {},
            "per_team": [],
        }
    per_team: List[Dict[str, Any]] = []
    for index, team in enumerate(pool):
        opponent = opponent_pool[(index + 1) % len(opponent_pool)]
        per_team_record = evaluate_team_against_opponent(
            team.pokemon, opponent.pokemon, seed=42 + index
        )
        per_team_record["index"] = index
        per_team_record["team_id"] = team.id
        per_team_record["opponent_team_id"] = opponent.id
        per_team.append(per_team_record)
    return {
        "denominator_teams": len(pool),
        "denominator_opponents": len(opponent_pool),
        "policies": list(POLICIES),
        "per_team": per_team,
    }


# ---------------------------------------------------------------------------
# Adjudication metrics
# ---------------------------------------------------------------------------


def shannon_entropy_from_counts(counts: Iterable[int]) -> float:
    values = [int(value) for value in counts if int(value) > 0]
    total = sum(values)
    if total == 0:
        return 0.0
    return -sum(
        (value / total) * math.log2(value / total) for value in values
    )


def percentile(values: Sequence[float], fraction: float) -> float:
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


def _selected_set(plan: Mapping[str, Any]) -> Tuple[str, ...]:
    return tuple(sorted(plan.get("chosen_4", [])))


def _lead_pair(plan: Mapping[str, Any]) -> Tuple[str, ...]:
    return tuple(plan.get("lead_2", []))


def _per_policy_metrics(
    per_team: Sequence[Mapping[str, Any]],
    policy: str,
) -> Dict[str, Any]:
    plans = [rec["policies"][policy] for rec in per_team]
    valid = [p for p in plans if "error" not in p]
    if not valid:
        return {
            "evaluated_teams": 0,
            "errors": len(plans) - len(valid),
            "common_total_avg": 0.0,
            "common_total_median": 0.0,
            "common_total_min": 0.0,
            "common_total_p10": 0.0,
            "common_total_p90": 0.0,
            "unique_selected_four": 0,
            "unique_lead_pairs": 0,
            "unique_selected_species": 0,
            "species_slot_entropy_bits": 0.0,
            "combination_entropy_bits": 0.0,
            "lead_pair_entropy_bits": 0.0,
            "component_averages": {},
            "runtime_avg_ms": 0.0,
            "runtime_p50_ms": 0.0,
            "runtime_p95_ms": 0.0,
            "runtime_max_ms": 0.0,
            "v2_plan_changes": 0,
            "v2_lead_changes": 0,
        }
    totals = [p["common_total"] for p in valid]
    runtimes = [
        p["runtime_ms"] for p in valid if "runtime_ms" in p
    ]
    selected_counts = Counter(_selected_set(p) for p in valid)
    lead_counts = Counter(_lead_pair(p) for p in valid)
    species_counts: Counter = Counter()
    for p in valid:
        for species in p["chosen_4"]:
            species_counts[species] += 1

    component_averages: Dict[str, float] = {}
    if valid:
        component_keys = list(valid[0]["components"].keys())
        for key in component_keys:
            component_averages[key] = statistics.fmean(
                p["components"][key] for p in valid
            )

    return {
        "evaluated_teams": len(valid),
        "errors": len(plans) - len(valid),
        "common_total_avg": statistics.fmean(totals) if totals else 0.0,
        "common_total_median": statistics.median(totals) if totals else 0.0,
        "common_total_min": min(totals) if totals else 0.0,
        "common_total_p10": percentile(totals, 0.10),
        "common_total_p90": percentile(totals, 0.90),
        "unique_selected_four": len(selected_counts),
        "unique_lead_pairs": len(lead_counts),
        "unique_selected_species": len(species_counts),
        "species_slot_entropy_bits": shannon_entropy_from_counts(
            species_counts.values()
        ),
        "combination_entropy_bits": shannon_entropy_from_counts(
            selected_counts.values()
        ),
        "lead_pair_entropy_bits": shannon_entropy_from_counts(
            lead_counts.values()
        ),
        "component_averages": component_averages,
        "runtime_avg_ms": statistics.fmean(runtimes) if runtimes else 0.0,
        "runtime_p50_ms": percentile(runtimes, 0.50),
        "runtime_p95_ms": percentile(runtimes, 0.95),
        "runtime_max_ms": max(runtimes) if runtimes else 0.0,
        "v2_plan_changes": 0,  # filled by analyze_results
        "v2_lead_changes": 0,  # filled by analyze_results
    }


def analyze_results(
    raw: Dict[str, Any],
    v2_records: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Build the per-policy analysis with identical-input denominators
    and a V2 cross-reference for plan/lead changes.

    `v2_records` is the list of V2 plan records from the same input
    iteration, used to count plan/lead changes vs V2 on identical
    inputs. (V2 vs V2 change counts are always zero by definition;
    we use the V2 records to confirm identity.)
    """
    per_team = raw["per_team"]
    analysis: Dict[str, Any] = {}
    by_policy = {policy: v2_records for policy in POLICIES}
    for policy in POLICIES:
        metrics = _per_policy_metrics(per_team, policy)
        # Plan/lead changes vs V2 on identical inputs.
        changes_plan = 0
        changes_lead = 0
        v2_plans = {rec["index"]: rec["policies"]["matchup_top4_v2"]
                    for rec in per_team}
        for rec in per_team:
            plan = rec["policies"].get(policy, {})
            v2 = v2_plans.get(rec["index"], {})
            if "error" in plan or "error" in v2:
                continue
            if set(plan["chosen_4"]) != set(v2["chosen_4"]):
                changes_plan += 1
            if tuple(plan["lead_2"]) != tuple(v2["lead_2"]):
                changes_lead += 1
        metrics["v2_plan_changes"] = changes_plan
        metrics["v2_lead_changes"] = changes_lead
        analysis[policy] = metrics
    analysis["denominator_teams"] = raw["denominator_teams"]
    analysis["denominator_opponents"] = raw["denominator_opponents"]
    return analysis


# ---------------------------------------------------------------------------
# Opponent adaptation (two distinct opponents, full 129 teams)
# ---------------------------------------------------------------------------


def opponent_adaptation(
    limit_teams: Optional[int] = None,
) -> Dict[str, Any]:
    """For each policy, evaluate plan/lead changes when the same team
    faces two distinct opponents. Reports the denominator explicitly.

    Opponent A is fetched by rank 1, opponent B by rank 50. These
    ranks are deterministic and produce two clearly different teams.
    """
    pool = list(
        load_vgc_pool(
            max_rank=None, parse_status="any", limit=limit_teams,
            seed=42,
        )
    )
    if not pool:
        return {
            "denominator_teams": 0,
            "opponent_a_id": None,
            "opponent_b_id": None,
            "policies": {
                policy: {
                    "denominator_teams": 0,
                    "selection_changes": 0,
                    "lead_changes": 0,
                } for policy in POLICIES
            },
        }
    pool_by_rank = {team.rank: team for team in pool}
    opponent_a = pool_by_rank.get(1) or pool[0]
    opponent_b = pool_by_rank.get(50) or pool[min(len(pool) - 1, 49)]
    if opponent_a.id == opponent_b.id and len(pool) >= 2:
        # Fallback: choose the first two distinct teams.
        opponent_b = pool[1]
    out: Dict[str, Any] = {}
    for policy in POLICIES:
        selection_changes = 0
        lead_changes = 0
        valid = 0
        for index, team in enumerate(pool):
            seed = 7000 + index
            plan_a = choose_four_from_six(
                team.pokemon,
                opponent_team=opponent_a.pokemon,
                policy=policy,
                seed=seed,
            )
            plan_b = choose_four_from_six(
                team.pokemon,
                opponent_team=opponent_b.pokemon,
                policy=policy,
                seed=seed,
            )
            valid += 1
            if set(plan_a.chosen_4) != set(plan_b.chosen_4):
                selection_changes += 1
            if tuple(plan_a.lead_2) != tuple(plan_b.lead_2):
                lead_changes += 1
        out[policy] = {
            "denominator_teams": valid,
            "selection_changes": selection_changes,
            "lead_changes": lead_changes,
        }
    return {
        "denominator_teams": len(pool),
        "opponent_a_id": opponent_a.id,
        "opponent_b_id": opponent_b.id,
        "policies": out,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def write_json_report(
    output_path: Path,
    raw: Dict[str, Any],
    analysis: Dict[str, Any],
    adaptation: Dict[str, Any],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "denominator_teams": raw["denominator_teams"],
        "denominator_opponents": raw["denominator_opponents"],
        "policies": raw["policies"],
        "analysis": analysis,
        "opponent_adaptation": adaptation,
    }
    with output_path.open("w") as handle:
        json.dump(report, handle, indent=2, default=str)


def render_markdown(
    raw: Dict[str, Any],
    analysis: Dict[str, Any],
    adaptation: Dict[str, Any],
) -> str:
    lines: List[str] = []
    lines.append("# Phase V2e.1 Offline Policy Comparison")
    lines.append("")
    lines.append(
        f"All four policies were evaluated on the same "
        f"{raw['denominator_teams']} team/opponent inputs. Each "
        f"selected plan was scored by the common external evaluator "
        f"`evaluate_plan_on_common_scale`. Score margins across "
        f"policies are NOT compared on a different scale."
    )
    lines.append("")
    lines.append("## Per-policy common evaluator totals")
    lines.append("")
    lines.append("| Policy | n | avg | median | min | p10 | p90 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for policy in POLICIES:
        m = analysis[policy]
        lines.append(
            f"| {policy} | {m['evaluated_teams']} | "
            f"{m['common_total_avg']:.3f} | "
            f"{m['common_total_median']:.3f} | "
            f"{m['common_total_min']:.3f} | "
            f"{m['common_total_p10']:.3f} | "
            f"{m['common_total_p90']:.3f} |"
        )
    lines.append("")
    lines.append("## Diversity")
    lines.append("")
    lines.append("| Policy | unique 4 | unique leads | unique species | species entropy | combo entropy | lead entropy |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for policy in POLICIES:
        m = analysis[policy]
        lines.append(
            f"| {policy} | {m['unique_selected_four']} | "
            f"{m['unique_lead_pairs']} | {m['unique_selected_species']} | "
            f"{m['species_slot_entropy_bits']:.3f} | "
            f"{m['combination_entropy_bits']:.3f} | "
            f"{m['lead_pair_entropy_bits']:.3f} |"
        )
    lines.append("")
    lines.append("## Runtime (per team)")
    lines.append("")
    lines.append("| Policy | avg ms | p50 ms | p95 ms | max ms |")
    lines.append("|---|---:|---:|---:|---:|")
    for policy in POLICIES:
        m = analysis[policy]
        lines.append(
            f"| {policy} | {m['runtime_avg_ms']:.3f} | "
            f"{m['runtime_p50_ms']:.3f} | "
            f"{m['runtime_p95_ms']:.3f} | "
            f"{m['runtime_max_ms']:.3f} |"
        )
    lines.append("")
    lines.append("## V2 plan / lead changes on identical inputs")
    lines.append("")
    lines.append("| Policy | n | plan changes vs V2 | lead changes vs V2 |")
    lines.append("|---|---:|---:|---:|")
    for policy in POLICIES:
        m = analysis[policy]
        lines.append(
            f"| {policy} | {m['evaluated_teams']} | "
            f"{m['v2_plan_changes']} | {m['v2_lead_changes']} |"
        )
    lines.append("")
    lines.append("## Opponent adaptation (two distinct opponents)")
    lines.append("")
    if adaptation.get("opponent_a_id") and adaptation.get("opponent_b_id"):
        lines.append(
            f"Opponent A id: `{adaptation['opponent_a_id']}`\n"
            f"Opponent B id: `{adaptation['opponent_b_id']}`\n"
            f"Denominator teams: {adaptation['denominator_teams']}"
        )
    else:
        lines.append("Opponents unavailable.")
    lines.append("")
    lines.append("| Policy | n | selection changes | lead changes |")
    lines.append("|---|---:|---:|---:|")
    for policy in POLICIES:
        m = adaptation["policies"].get(policy, {})
        lines.append(
            f"| {policy} | {m.get('denominator_teams', 0)} | "
            f"{m.get('selection_changes', 0)} | "
            f"{m.get('lead_changes', 0)} |"
        )
    lines.append("")
    lines.append("## Component averages")
    lines.append("")
    if analysis[POLICIES[0]]["component_averages"]:
        keys = list(analysis[POLICIES[0]]["component_averages"].keys())
        header = "| Component | " + " | ".join(POLICIES) + " |"
        sep = "|---|" + "|".join(["---:"] * len(POLICIES)) + "|"
        lines.append(header)
        lines.append(sep)
        for key in keys:
            row = [f"| {key} |"]
            for policy in POLICIES:
                row.append(
                    f"{analysis[policy]['component_averages'].get(key, 0.0):.3f} |"
                )
            lines.append(" ".join(row))
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Cross-policy score margins are NOT computed. Different "
        "policies may emit different plans; the common evaluator "
        "scores each plan on the same scale, but the previous V2e "
        "'+0.752 vs basic' and '-2.388 vs basic' cross-policy "
        "comparisons are not reproduced because they used "
        "policy-specific score scales."
    )
    lines.append(
        "- The 57% / 45% side split is reported as observed evidence "
        "only; it is not a root cause."
    )
    lines.append(
        "- Random and other policies use deterministic seeds so the "
        "comparison is repeatable."
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit-teams",
        type=int,
        default=None,
        help=(
            "Override the 129-team denominator. Default: use the full "
            "129-team pool."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs/"
            "vgc2026_phaseV2e1_policy_comparison.json"
        ),
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path(
            "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs/"
            "vgc2026_phaseV2e1_policy_comparison.md"
        ),
    )
    args = parser.parse_args()

    raw = evaluate_all_policies(limit_teams=args.limit_teams)
    v2_records = raw["per_team"]
    analysis = analyze_results(raw, v2_records)
    adaptation = opponent_adaptation(limit_teams=args.limit_teams)
    write_json_report(args.output, raw, analysis, adaptation)
    markdown = render_markdown(raw, analysis, adaptation)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(markdown)
    print(markdown)
    print(f"JSON: {args.output}")
    print(f"Markdown: {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
