#!/usr/bin/env python3
"""
VGC 2026 Phase V2j Inspector

CLI for inspecting one pair's V2j lead matchup evaluation. Supports
per-policy inspection, per-component drill-down, per-opponent
lead-pair filtering, contradiction / actionable filter, and
component ablations.

Usage:
    ./venv/bin/python inspect_vgc2026_phaseV2j_lead_matchup.py \\
        --pair 0 --policy v3
    ./venv/bin/python inspect_vgc2026_phaseV2j_lead_matchup.py \\
        --pair 0 --policy v3 --component lead_offensive_effectiveness
    ./venv/bin/python inspect_vgc2026_phaseV2j_lead_matchup.py \\
        --pair 0 --policy v3 --opponent-lead rillaboom,incineroar
    ./venv/bin/python inspect_vgc2026_phaseV2j_lead_matchup.py \\
        --pair 0 --policy v3 --worst-leads 5
    ./venv/bin/python inspect_vgc2026_phaseV2j_lead_matchup.py \\
        --pair 0 --policy v3 --best-leads 5
    ./venv/bin/python inspect_vgc2026_phaseV2j_lead_matchup.py \\
        --pair 0 --group v3_both
    ./venv/bin/python inspect_vgc2026_phaseV2j_lead_matchup.py \\
        --contradictory
    ./venv/bin/python inspect_vgc2026_phaseV2j_lead_matchup.py \\
        --candidate-actionable
    ./venv/bin/python inspect_vgc2026_phaseV2j_lead_matchup.py \\
        --ablation
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # project root

from vgc2026_lead_matchup_evaluator_v3 import (
    COMPONENT_SPECS,
    evaluate_lead_matchup,
    lead_pair_score,
)
from analyze_vgc2026_phaseV2j_lead_matchups import (
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
    inputs = build_synthetic_inputs()
    pair_records = [
        pair for pair in inputs["pair_records"]
        if int(pair["pair_id"]) == pair_id
    ]
    bundles = build_bundles_by_pair(pair_records, inputs["team_lookup"])
    if pair_id not in bundles:
        raise SystemExit(f"Synthetic pair {pair_id} not found")
    return bundles[pair_id]


def _print_pair_overview(
    pair_id: int,
    bundle: Dict[str, Any],
    policy: str,
    fp: str,
) -> str:
    if policy not in {"v3", "random"}:
        raise SystemExit(f"Unknown policy: {policy!r}")
    score_obj = bundle[policy]
    eval_obj = score_obj.eval_obj
    plan = score_obj.plan
    out: List[str] = []
    out.append(f"=== Pair {pair_id} (policy={policy}) ===")
    out.append(f"Fingerprint: {fp[:16]}...")
    out.append(
        f"Plan: chosen_4={plan['chosen_4']} "
        f"lead_2={plan['lead_2']} back_2={plan['back_2']}"
    )
    out.append(
        f"Lead pair score: {score_obj.v2j_score:.3f} | "
        f"n_lead_pairs: {eval_obj.uncertainty.get('n_lead_pairs', 0)}"
    )
    out.append(
        f"Mean / worst / p25 / p75: "
        f"{eval_obj.uncertainty.get('mean_matchup', 0):.3f} / "
        f"{eval_obj.uncertainty.get('worst_matchup', 0):.3f} / "
        f"{eval_obj.uncertainty.get('lower_quartile_matchup', 0):.3f} / "
        f"{eval_obj.uncertainty.get('upper_quartile_matchup', 0):.3f}"
    )
    out.append(
        f"Variance: {eval_obj.uncertainty.get('matchup_variance', 0):.3f} | "
        f"n_severely_bad: {eval_obj.uncertainty.get('n_severely_bad', 0)} | "
        f"n_favorable: {eval_obj.uncertainty.get('n_favorable', 0)}"
    )
    out.append(
        f"Unknown rate: {eval_obj.uncertainty.get('unknown_rate', 0):.2%} | "
        f"n_unknown_pairs: {eval_obj.uncertainty.get('n_unknown_pairs', 0)}"
    )
    if eval_obj.unknown_moves:
        out.append(f"Unknown moves: {eval_obj.unknown_moves}")
    if eval_obj.unknown_abilities:
        out.append(f"Unknown abilities: {eval_obj.unknown_abilities}")
    out.append("")
    out.append("Component means:")
    for spec in COMPONENT_SPECS:
        value = eval_obj.component_means.get(spec.name, 0.0)
        out.append(f"  {spec.name}: {value:+.3f}")
    return "\n".join(out)


def _print_lead_pair(
    matchup: Any,
) -> str:
    out: List[str] = []
    out.append(
        f"Opp lead: {matchup.opponent_lead_2} | "
        f"total={matchup.component_total:+.3f}"
    )
    for spec in COMPONENT_SPECS:
        v = matchup.component_values.get(spec.name, 0.0)
        out.append(f"  {spec.name}: {v:+.3f}")
    if matchup.effectiveness_buckets:
        out.append(
            "  buckets: " + ", ".join(
                f"{k}={v}" for k, v in sorted(
                    matchup.effectiveness_buckets.items()
                )
            )
        )
    if matchup.uncertainty_reasons:
        out.append(
            "  uncertainty: " + ", ".join(matchup.uncertainty_reasons)
        )
    return "\n".join(out)


def _print_worst_or_best(
    bundle: Dict[str, Any],
    policy: str,
    n: int,
    best: bool,
) -> str:
    eval_obj = bundle[policy].eval_obj
    matchups = list(eval_obj.lead_pair_matchups)
    matchups.sort(
        key=lambda m: m.component_total, reverse=best
    )
    out: List[str] = []
    label = "Best" if best else "Worst"
    out.append(
        f"=== {label} {n} opponent lead pairs "
        f"(pair={bundle['v3'].plan.get('chosen_4')}, "
        f"policy={policy}) ==="
    )
    for m in matchups[:n]:
        out.append(
            f"{m.opponent_lead_2}: {m.component_total:+.3f}"
        )
    return "\n".join(out)


def _print_opponent_lead(
    bundle: Dict[str, Any],
    policy: str,
    opp_lead: str,
) -> str:
    target = tuple(sorted(s.strip() for s in opp_lead.split(",")))
    eval_obj = bundle[policy].eval_obj
    for m in eval_obj.lead_pair_matchups:
        if tuple(m.opponent_lead_2) == target:
            return _print_lead_pair(m)
    return f"No match for opponent lead {target}"


def _print_component(
    bundle: Dict[str, Any],
    policy: str,
    component: str,
) -> str:
    eval_obj = bundle[policy].eval_obj
    out: List[str] = []
    out.append(
        f"=== Component '{component}' across 15 lead pairs "
        f"(policy={policy}) ==="
    )
    out.append(f"Mean: {eval_obj.component_means.get(component, 0.0):+.3f}")
    out.append("Per-pair values:")
    for m in eval_obj.lead_pair_matchups:
        v = m.component_values.get(component, 0.0)
        out.append(f"  {m.opponent_lead_2}: {v:+.3f}")
    return "\n".join(out)


def _print_compare_policies(
    bundle: Dict[str, Any],
) -> str:
    out: List[str] = []
    out.append("=== V3 vs Random head-to-head ===")
    for label, plan_label in (("V3", "v3"), ("Random", "random")):
        score_obj = bundle[plan_label]
        eval_obj = score_obj.eval_obj
        out.append(
            f"{label}: score={score_obj.v2j_score:+.3f} | "
            f"mean={eval_obj.uncertainty.get('mean_matchup', 0):.3f}"
        )
    return "\n".join(out)


def _print_ablation(
    bundle: Dict[str, Any],
    policy: str,
) -> str:
    eval_obj = bundle[policy].eval_obj
    out: List[str] = []
    out.append(
        f"=== Component ablation (policy={policy}) ==="
    )
    full_score = bundle[policy].v2j_score
    ablation: List[Dict[str, Any]] = []
    for spec in COMPONENT_SPECS:
        per_pair_drop = 0.0
        for m in eval_obj.lead_pair_matchups:
            per_pair_drop += m.component_values.get(spec.name, 0.0) * spec.weight
        per_pair_drop /= max(1, len(eval_obj.lead_pair_matchups))
        ablation.append({
            "component": spec.name,
            "weight": spec.weight,
            "per_pair_drop": per_pair_drop,
        })
    ablation.sort(key=lambda r: r["per_pair_drop"], reverse=True)
    for row in ablation:
        out.append(
            f"  {row['component']}: drop={row['per_pair_drop']:+.3f} "
            f"(weight={row['weight']:.2f})"
        )
    out.append(f"  Full score: {full_score:+.3f}")
    return "\n".join(out)


def _print_group_view(
    inputs: Dict[str, Any],
    group: str,
    policy: str,
) -> str:
    """Group-level overview across all decisive pairs."""
    from analyze_vgc2026_phaseV2j_lead_matchups import (
        classify_pair, run_analysis,
    )
    if "pair_records" in inputs and "team_lookup" in inputs:
        report = run_analysis({
            "pair_records": inputs["pair_records"],
            "team_lookup": inputs["team_lookup"],
        })
    else:
        report = run_analysis(inputs)
    if group == "all":
        out_lines: List[str] = [
            "=== Group summary (all decisive pairs) ===",
            f"v3_both: {report['sign_test']['v3_both']} | "
            f"random_both: {report['sign_test']['random_both']} | "
            f"split: {report['sign_test']['split']} | "
            f"decisive_n: {report['sign_test']['decisive_n']}",
        ]
    else:
        out_lines = [
            f"=== Group summary (group={group}) ===",
        ]
    return "\n".join(out_lines)


def _print_actionable_or_contradictory(
    inputs: Dict[str, Any],
    target: str,
) -> str:
    from analyze_vgc2026_phaseV2j_lead_matchups import run_analysis
    if "pair_records" in inputs and "team_lookup" in inputs:
        report = run_analysis({
            "pair_records": inputs["pair_records"],
            "team_lookup": inputs["team_lookup"],
        })
    else:
        report = run_analysis(inputs)
    if target == "candidate-actionable":
        items = report["actionable_components"]
        title = "Candidate actionable components"
    else:
        items = report["contradictory_components"]
        title = "Contradictory components"
    out_lines: List[str] = [f"=== {title} ==="]
    if not items:
        out_lines.append("(none)")
    else:
        for c in items:
            out_lines.append(f"- {c}")
    out_lines.append(
        f"Decision: {report['decision']['code']} - "
        f"{report['decision']['summary']}"
    )
    return "\n".join(out_lines)


def _load_inputs(
    logs_dir: Path, artifact_prefix: str, synthetic: bool
) -> Dict[str, Any]:
    if synthetic:
        return build_synthetic_inputs()
    benchmark_rows, preview_rows, team_lookup = (
        load_v2f_outcomes_with_freeze_proof(logs_dir, artifact_prefix)
    )
    pair_records = build_pair_records(
        benchmark_rows, preview_rows, team_lookup
    )
    return {
        "pair_records": pair_records,
        "team_lookup": team_lookup,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", type=int, required=True)
    parser.add_argument(
        "--policy",
        choices=["v3", "random"],
        default="v3",
    )
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Use synthetic inputs (no battle labels required).",
    )
    parser.add_argument("--logs-dir", type=Path, default=DEFAULT_LOGS_DIR)
    parser.add_argument(
        "--artifact-prefix", default=DEFAULT_ARTIFACT_PREFIX
    )
    parser.add_argument(
        "--component", default=None,
        help="Show one component's per-pair values.",
    )
    parser.add_argument(
        "--opponent-lead", default=None,
        help="Filter to one opponent lead pair (csv).",
    )
    parser.add_argument(
        "--worst-leads", type=int, default=None,
        help="Print N worst opponent lead pairs.",
    )
    parser.add_argument(
        "--best-leads", type=int, default=None,
        help="Print N best opponent lead pairs.",
    )
    parser.add_argument(
        "--compare-policies", action="store_true",
        help="V3 vs Random head-to-head.",
    )
    parser.add_argument(
        "--group", default=None,
        help="Group-level overview (v3_both, random_both, split, all).",
    )
    parser.add_argument(
        "--ablation", action="store_true",
        help="Component ablation table.",
    )
    parser.add_argument(
        "--candidate-actionable", action="store_true",
        help="Print candidate-actionable components.",
    )
    parser.add_argument(
        "--contradictory", action="store_true",
        help="Print contradictory components.",
    )
    args = parser.parse_args()

    fp = ANALYZER_FROZEN_FINGERPRINT
    if args.synthetic:
        bundle = _load_synthetic_pair(args.pair)
    else:
        bundle = _load_v2f_pair(
            args.pair, args.logs_dir, args.artifact_prefix
        )

    if args.candidate_actionable or args.contradictory or args.group:
        inputs = _load_inputs(
            args.logs_dir, args.artifact_prefix, args.synthetic
        )
        if args.candidate_actionable:
            print(_print_actionable_or_contradictory(
                inputs, "candidate-actionable"
            ))
        elif args.contradictory:
            print(_print_actionable_or_contradictory(
                inputs, "contradictory"
            ))
        elif args.group:
            print(_print_group_view(inputs, args.group, args.policy))
        return 0

    print(_print_pair_overview(args.pair, bundle, args.policy, fp))
    if args.component:
        print()
        print(_print_component(bundle, args.policy, args.component))
    if args.opponent_lead:
        print()
        print(_print_opponent_lead(bundle, args.policy, args.opponent_lead))
    if args.worst_leads is not None:
        print()
        print(_print_worst_or_best(
            bundle, args.policy, args.worst_leads, best=False
        ))
    if args.best_leads is not None:
        print()
        print(_print_worst_or_best(
            bundle, args.policy, args.best_leads, best=True
        ))
    if args.compare_policies:
        print()
        print(_print_compare_policies(bundle))
    if args.ablation:
        print()
        print(_print_ablation(bundle, args.policy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
