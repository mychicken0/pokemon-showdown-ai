#!/usr/bin/env python3
"""
VGC 2026 Phase V2i Inspector

CLI for inspecting one pair's V2i matchup evaluation. Supports
per-policy inspection, per-component drill-down, and per-opponent
lead-pair filtering.

Usage:
    ./venv/bin/python inspect_vgc2026_phaseV2i_matchup.py \\
        --pair 0 --policy v3
    ./venv/bin/python inspect_vgc2026_phaseV2i_matchup.py \\
        --pair 0 --policy v3 --component offensive_move_type_pressure
    ./venv/bin/python inspect_vgc2026_phaseV2i_matchup.py \\
        --pair 0 --compare-policies
    ./venv/bin/python inspect_vgc2026_phaseV2i_matchup.py \\
        --pair 0 --policy v3 --worst-leads 5
    ./venv/bin/python inspect_vgc2026_phaseV2i_matchup.py \\
        --pair 0 --policy v3 --best-leads 5
    ./venv/bin/python inspect_vgc2026_phaseV2i_matchup.py \\
        --pair 0 --policy v3 --ablation top10
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # project root

from vgc2026_matchup_evaluator_v2 import (
    COMPONENT_SPECS,
    COMPONENT_WEIGHTS,
    evaluate_matchup,
)
from vgc2026_common_plan_evaluator import evaluate_plan_on_common_scale
from analyze_vgc2026_phaseV2i_matchup_evaluator import (
    ANALYZER_FROZEN_FINGERPRINT,
    build_bundles_by_pair,
    build_pair_records,
    build_synthetic_inputs,
    load_v2f_outcomes_with_freeze_proof,
    _team_to_pokemon_list,
)


DEFAULT_LOGS_DIR = Path(
    "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs"
)
DEFAULT_ARTIFACT_PREFIX = (
    "vgc2026_phaseV2c_phaseV2f_v3_paired_qualification"
)


def _load_v2f_pair(
    pair_id: int, logs_dir: Path, artifact_prefix: str
) -> Dict[str, Any]:
    """Load benchmark + preview + team data, build pair records,
    and return the bundles for the requested pair_id.
    """
    benchmark_rows, preview_rows, team_lookup = (
        load_v2f_outcomes_with_freeze_proof(logs_dir, artifact_prefix)
    )
    pair_records = build_pair_records(
        benchmark_rows, preview_rows, team_lookup
    )
    bundles = build_bundles_by_pair(pair_records, team_lookup)
    if pair_id not in bundles:
        raise SystemExit(f"Pair {pair_id} not found in artifacts")
    return bundles[pair_id]


def _load_synthetic_pair(pair_id: int) -> Dict[str, Any]:
    """Build only the requested synthetic pair for fast CLI tests."""
    inputs = build_synthetic_inputs()
    pair_records = [
        pair for pair in inputs["pair_records"]
        if int(pair["pair_id"]) == pair_id
    ]
    bundles = build_bundles_by_pair(pair_records, inputs["team_lookup"])
    if pair_id not in bundles:
        raise SystemExit(f"Synthetic pair {pair_id} not found")
    return bundles[pair_id]


def _format_component(
    name: str, value: float, per_pair: List[float]
) -> str:
    if not per_pair:
        return f"  {name}: {value:.3f}"
    return (
        f"  {name}: mean={value:.3f} "
        f"min={min(per_pair):.3f} max={max(per_pair):.3f}"
    )


def _print_pair_overview(
    pair_id: int, entry: Dict[str, Any]
) -> None:
    print(f"Pair {pair_id}")
    print(
        f"  Team ID: {entry.get('v3_plan', {}).get('chosen_4')}"
    )
    print(
        f"  Opponent ID: see team_lookup; species: "
        f"{[p.get('species') for p in entry.get('opp_pokemon', [])]}"
    )
    print(f"  Frozen fingerprint: {ANALYZER_FROZEN_FINGERPRINT[:16]}...")


def _print_plan(
    policy: str, plan_score_obj: Any
) -> None:
    print(f"\n[{policy}] plan:")
    print(f"  chosen_4: {plan_score_obj.plan['chosen_4']}")
    print(f"  lead_2:   {plan_score_obj.plan['lead_2']}")
    print(f"  back_2:   {plan_score_obj.plan['back_2']}")
    print(f"  v2i_score (mean matchup): {plan_score_obj.v2i_score:.3f}")
    print(f"  v1_score (common total):  {plan_score_obj.v1_score:.3f}")
    eval_obj = plan_score_obj.eval_obj
    u = eval_obj.uncertainty
    print("  uncertainty aggregation:")
    for key in (
        "n_lead_pairs", "mean_matchup", "worst_matchup",
        "lower_quartile_matchup", "matchup_variance",
        "n_severely_bad", "n_favorable",
    ):
        print(f"    {key}: {u[key]}")
    print(f"  unknown_moves: {eval_obj.unknown_moves}")


def _print_components(
    policy: str, plan_score_obj: Any, only: str = None
) -> None:
    eval_obj = plan_score_obj.eval_obj
    print(f"\n[{policy}] components (mean across 15 opponent lead pairs):")
    for spec in COMPONENT_SPECS:
        if only is not None and spec.name != only:
            continue
        value = eval_obj.component_means.get(spec.name, 0.0)
        per_pair = [
            m.component_values.get(spec.name, 0.0)
            for m in eval_obj.lead_pair_matchups
        ]
        print(
            f"  {spec.name} (sign={spec.sign}, "
            f"weight={spec.weight:.2f}, range={spec.range}): "
            f"mean={value:+.3f} "
            f"min={min(per_pair):+.3f} max={max(per_pair):+.3f} "
            f"preview-visible={spec.preview_visible}"
        )


def _print_worst_leads(
    policy: str, plan_score_obj: Any, n: int
) -> None:
    eval_obj = plan_score_obj.eval_obj
    sorted_pairs = sorted(
        eval_obj.lead_pair_matchups, key=lambda m: m.component_total
    )
    print(f"\n[{policy}] worst {n} opponent lead pairs:")
    for i, matchup in enumerate(sorted_pairs[:n]):
        print(
            f"  {i+1}. {matchup.opponent_lead_2}: "
            f"total={matchup.component_total:.3f}"
        )


def _print_best_leads(
    policy: str, plan_score_obj: Any, n: int
) -> None:
    eval_obj = plan_score_obj.eval_obj
    sorted_pairs = sorted(
        eval_obj.lead_pair_matchups,
        key=lambda m: m.component_total, reverse=True,
    )
    print(f"\n[{policy}] best {n} opponent lead pairs:")
    for i, matchup in enumerate(sorted_pairs[:n]):
        print(
            f"  {i+1}. {matchup.opponent_lead_2}: "
            f"total={matchup.component_total:.3f}"
        )


def _print_opponent_lead(
    policy: str, plan_score_obj: Any, opp_pair: tuple
) -> None:
    eval_obj = plan_score_obj.eval_obj
    a, b = sorted([s.strip().lower() for s in opp_pair])
    target = (a, b)
    for matchup in eval_obj.lead_pair_matchups:
        if matchup.opponent_lead_2 == target:
            print(
                f"\n[{policy}] opponent lead pair {target}: "
                f"total={matchup.component_total:.3f}"
            )
            for spec in COMPONENT_SPECS:
                v = matchup.component_values.get(spec.name, 0.0)
                print(
                    f"  {spec.name}: {v:+.3f} (sign={spec.sign}, "
                    f"weight={spec.weight:.2f}, "
                    f"preview-visible={spec.preview_visible})"
                )
            return
    print(
        f"\n[{policy}] opponent lead pair {target} not found. "
        f"Available pairs: "
        f"{[m.opponent_lead_2 for m in eval_obj.lead_pair_matchups]}"
    )


def _print_compare_policies(entry: Dict[str, Any]) -> None:
    v3 = entry.get("v3")
    rnd = entry.get("random")
    if v3 is None or rnd is None:
        print("V3 or Random plan missing in pair")
        return
    print("Policy comparison (V3 vs Random):")
    for name in ("v2i_score", "v1_score"):
        v3_v = getattr(v3, name)
        rnd_v = getattr(rnd, name)
        delta = v3_v - rnd_v
        print(f"  {name}: V3={v3_v:.3f} | Random={rnd_v:.3f} | "
              f"delta={delta:+.3f}")


def _print_ablation(
    plan_score_obj: Any, limit: int = 10
) -> None:
    """Top contributors to the plan score, by mean weighted
    contribution. Drop a single component (zero it) and report
    the resulting total. This is a deterministic single-pass
    ablation.
    """
    eval_obj = plan_score_obj.eval_obj
    full_total = plan_score_obj.v2i_score
    contributions: List[Dict[str, Any]] = []
    for spec in COMPONENT_SPECS:
        value = eval_obj.component_means.get(spec.name, 0.0)
        weight = spec.weight
        contribution = value * weight
        ablated_total = full_total - contribution
        contributions.append({
            "component": spec.name,
            "mean": value,
            "weight": weight,
            "contribution": contribution,
            "ablated_total": ablated_total,
        })
    contributions.sort(key=lambda r: abs(r["contribution"]), reverse=True)
    print(f"\nAblation (top {limit} contributors):")
    print("| Component | Mean | Weight | Contribution | Ablated total |")
    print("|---|---:|---:|---:|---:|")
    for row in contributions[:limit]:
        print(
            f"| {row['component']} | {row['mean']:+.3f} | "
            f"{row['weight']:.2f} | {row['contribution']:+.3f} | "
            f"{row['ablated_total']:.3f} |"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pair", type=int, required=True,
        help="Pair ID to inspect",
    )
    parser.add_argument(
        "--policy", choices=["v3", "random"], default="v3",
        help="Which plan to inspect (default: v3)",
    )
    parser.add_argument(
        "--component", default=None,
        help="Show only this component name",
    )
    parser.add_argument(
        "--opponent-lead", default=None,
        help="SPECIES,SPECIES — show the matchup vs this opponent lead",
    )
    parser.add_argument(
        "--worst-leads", type=int, default=None,
        help="Show the N worst opponent lead pairs",
    )
    parser.add_argument(
        "--best-leads", type=int, default=None,
        help="Show the N best opponent lead pairs",
    )
    parser.add_argument(
        "--compare-policies", action="store_true",
        help="Print V3 vs Random plan score side-by-side",
    )
    parser.add_argument(
        "--ablation", default=None,
        help="Show the top contributors (e.g. 'top10')",
    )
    parser.add_argument(
        "--logs-dir", type=Path, default=DEFAULT_LOGS_DIR,
    )
    parser.add_argument(
        "--artifact-prefix", default=DEFAULT_ARTIFACT_PREFIX,
    )
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Use deterministic synthetic pair data instead of V2f artifacts.",
    )
    args = parser.parse_args()

    entry = (
        _load_synthetic_pair(args.pair)
        if args.synthetic
        else _load_v2f_pair(args.pair, args.logs_dir, args.artifact_prefix)
    )
    _print_pair_overview(args.pair, entry)
    plan = entry.get(args.policy)
    if plan is None:
        print(f"Policy {args.policy!r} not found in pair")
        return 1
    _print_plan(args.policy, plan)
    if args.compare_policies:
        _print_compare_policies(entry)
    if args.component:
        _print_components(args.policy, plan, only=args.component)
    else:
        _print_components(args.policy, plan)
    if args.opponent_lead:
        opp_pair = tuple(
            s.strip() for s in args.opponent_lead.split(",")
        )
        if len(opp_pair) != 2:
            print("--opponent-lead expects SPECIES,SPECIES")
            return 2
        _print_opponent_lead(args.policy, plan, opp_pair)
    if args.worst_leads is not None:
        _print_worst_leads(args.policy, plan, args.worst_leads)
    if args.best_leads is not None:
        _print_best_leads(args.policy, plan, args.best_leads)
    if args.ablation is not None:
        limit = 10
        if args.ablation.startswith("top"):
            try:
                limit = int(args.ablation[3:])
            except ValueError:
                limit = 10
        _print_ablation(plan, limit=limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
