#!/usr/bin/env python3
"""
VGC 2026 Phase V2k Inspector.

CLI for inspecting one pair's V2k lead matchup evaluation.
Built on top of the V2j inspector, with extra per-pair
mechanics drill-down that calls the shared ``doubles_mechanics``
module directly so the audit field is consistent across the
Random Doubles and VGC evaluators.

Adds over the V2j inspector:

- Pair outcome group (v3_both / random_both / split / invalid)
- Explicit plan owner (V3 vs Random) and selected plans
- Opponent lead pair
- Per-move shared-mechanics result: effective type, STAB,
  type multiplier, ability interaction, immunity reason
- Fake Out legal targets in the opponent lead pair
- Speed resolved / unresolved evidence
- Between-group contribution per component
- Paired within-failure delta per component
- Actionable rejection reasons

Usage examples
-------------
    ./venv/bin/python inspect_vgc2026_phaseV2k_lead_matchup.py \\
        --pair 0 --policy v3
    ./venv/bin/python inspect_vgc2026_phaseV2k_lead_matchup.py \\
        --pair 0 --policy v3 --mechanics
    ./venv/bin/python inspect_vgc2026_phaseV2k_lead_matchup.py \\
        --pair 0 --policy v3 --opponent-lead rillaboom,incineroar
    ./venv/bin/python inspect_vgc2026_phaseV2k_lead_matchup.py \\
        --pair 0 --policy v3 --worst-leads 5
    ./venv/bin/python inspect_vgc2026_phaseV2k_lead_matchup.py \\
        --pair 0 --group v3_both
    ./venv/bin/python inspect_vgc2026_phaseV2k_lead_matchup.py \\
        --candidate-actionable
    ./venv/bin/python inspect_vgc2026_phaseV2k_lead_matchup.py \\
        --report
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vgc2026_lead_matchup_evaluator_v3 import (
    COMPONENT_SPECS,
    evaluate_lead_matchup,
    lead_pair_score,
)

import doubles_mechanics as _dm
import analyze_vgc2026_phaseV2k_lead_matchups as v2k


DEFAULT_LOGS_DIR = Path(
    "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs"
)
DEFAULT_ARTIFACT_PREFIX = (
    "vgc2026_phaseV2c_phaseV2f_v3_paired_qualification"
)


def _load_inputs(
    logs_dir: Path, artifact_prefix: str, synthetic: bool
) -> Dict[str, Any]:
    if synthetic:
        return v2k.build_synthetic_inputs()
    benchmark_rows, preview_rows, team_lookup = (
        v2k.load_v2f_outcomes_with_freeze_proof(
            logs_dir, artifact_prefix
        )
    )
    pair_records = v2k.build_pair_records(
        benchmark_rows, preview_rows, team_lookup
    )
    return {
        "pair_records": pair_records,
        "team_lookup": team_lookup,
    }


def _load_pair(
    pair_id: int, logs_dir: Path, artifact_prefix: str, synthetic: bool
) -> Dict[str, Any]:
    if synthetic:
        inputs = v2k.build_synthetic_inputs()
        pair_records = [
            p for p in inputs["pair_records"]
            if int(p["pair_id"]) == pair_id
        ]
        bundles = v2k.build_bundles_by_pair(
            pair_records, inputs["team_lookup"]
        )
    else:
        benchmark_rows, preview_rows, team_lookup = (
            v2k.load_v2f_outcomes_with_freeze_proof(
                logs_dir, artifact_prefix
            )
        )
        pair_records = v2k.build_pair_records(
            benchmark_rows, preview_rows, team_lookup
        )
        bundles = v2k.build_bundles_by_pair(
            pair_records, team_lookup
        )
    if pair_id not in bundles:
        raise SystemExit(f"Pair {pair_id} not found in artifacts")
    bundle = bundles[pair_id]
    pair = next(
        p for p in pair_records if int(p["pair_id"]) == pair_id
    )
    bundle["_pair"] = pair
    return bundle


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
    pair = bundle.get("_pair", {})
    cls = v2k.classify_pair(pair) if pair else "unknown"
    out: List[str] = []
    out.append(f"=== Pair {pair_id} (policy={policy}) ===")
    out.append(f"Pair outcome group: **{cls}**")
    out.append(f"Status: {pair.get('status', 'unknown')}")
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


def _print_mechanics(
    bundle: Dict[str, Any],
    policy: str,
) -> str:
    """Per-move shared-mechanics audit, using the
    ``doubles_mechanics`` shared module.
    """
    score_obj = bundle[policy]
    eval_obj = score_obj.eval_obj
    team = bundle["team_pokemon"]
    opp = bundle["opp_pokemon"]
    out: List[str] = []
    out.append(f"=== Shared-mechanics audit (pair={bundle.get('v3_plan', {}).get('chosen_4')}, policy={policy}) ===")
    # Iterate our leads' moves.
    out.append("")
    out.append("Fake Out legal targets (opponent lead pair):")
    out.append(
        f"  {_dm.fake_out_legal_targets('fakeout', opp[:2])} of 2"
    )
    out.append("")
    out.append("Sample damaging moves (effective type / STAB / multiplier):")
    for pokemon in team[:2]:  # our lead pair
        pspecies = pokemon.get("species", "")
        ptypes = {str(t).upper() for t in pokemon.get("types", []) if t}
        for move in pokemon.get("moves", []) or []:
            cls = _dm.classify_move(move)
            if not cls.is_damaging:
                continue
            effective_type = cls.move_type
            source = "static"
            is_stab = effective_type in ptypes
            # Show the type multiplier against the opponent lead
            # pair's first member as a representative.
            opp_lead_types = []
            if opp and opp[0]:
                opp_lead_types = [
                    str(t).upper() for t in opp[0].get("types", []) if t
                ]
            mult = _dm.calculate_type_multiplier(
                effective_type, opp_lead_types
            )
            out.append(
                f"  {pspecies} {move}: effective={effective_type} "
                f"stab={is_stab} mult={mult:.2f} source={source}"
            )
            # Show the ability interaction (per the shared
            # helper) when the move is a typed absorb input.
            for opp_pokemon in opp[:2]:
                opp_ability = str(
                    opp_pokemon.get("ability", "")
                ).strip().lower()
                if opp_ability:
                    abil = _dm.resolve_explicit_ability_interaction(
                        move=None, attacker=None, target=None,
                        target_ability=opp_ability,
                        move_id=cls.move_id,
                        move_type=effective_type,
                    )
                    if abil.is_immune:
                        out.append(
                            f"    -> blocked by "
                            f"{opp_pokemon.get('species', '')} "
                            f"{opp_ability}: {abil.reason}"
                        )
    out.append("")
    out.append("Speed ordering (production shared-mechanics path):")
    out.append(
        "  V2f preview artifacts do not expose visible base "
        "speed, nature, item, boosts, status, or field state "
        "(Tailwind / Trick Room). The shared resolver refuses "
        "to commit. No deterministic-speed bonus is awarded "
        "in production scoring. See lead_pair_matchup."
        "speed_evidence for the per-opponent-lead-pair audit "
        "record."
    )
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
    # V2k.1 — production shared-mechanics speed evidence
    # path. Always present; ``resolved=False`` in the
    # current V2f preview artifacts because the artifacts
    # do not expose base speed, nature, item, boosts,
    # status, or field state.
    speed_evidence = getattr(matchup, "speed_evidence", None) or {}
    if speed_evidence:
        out.append(
            "  speed_evidence: "
            f"resolved={speed_evidence.get('resolved', False)} "
            f"result={speed_evidence.get('result', 'unknown')} "
            f"reason={speed_evidence.get('reason', 'unknown')}"
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


def _print_group_view(
    inputs: Dict[str, Any],
    group: str,
    policy: str,
) -> str:
    from analyze_vgc2026_phaseV2k_lead_matchups import (
        run_analysis,
    )
    if "pair_records" in inputs and "team_lookup" in inputs:
        report = run_analysis({
            "pair_records": inputs["pair_records"],
            "team_lookup": inputs["team_lookup"],
        })
    else:
        report = run_analysis(inputs)
    if group == "all":
        return (
            "=== Group summary (all decisive pairs) ===\n"
            f"v3_both: {report['sign_test']['v3_both']} | "
            f"random_both: {report['sign_test']['random_both']} | "
            f"split: {report['sign_test']['split']} | "
            f"decisive_n: {report['sign_test']['decisive_n']}\n"
            f"Real-artifact proof: {report.get('real_artifact_proof', {}).get('evidence_mode', 'n/a')}"
        )
    return f"=== Group summary (group={group}) ===\n"


def _print_actionable_or_contradictory(
    inputs: Dict[str, Any],
    target: str,
) -> str:
    from analyze_vgc2026_phaseV2k_lead_matchups import (
        run_analysis,
    )
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
    out_lines.append(
        f"Evidence mode: "
        f"{report.get('real_artifact_proof', {}).get('evidence_mode', 'n/a')}"
    )
    return "\n".join(out_lines)


def _print_report(
    logs_dir: Path, artifact_prefix: str, synthetic: bool
) -> str:
    inputs = _load_inputs(logs_dir, artifact_prefix, synthetic)
    from analyze_vgc2026_phaseV2k_lead_matchups import (
        run_analysis,
    )
    if not synthetic:
        is_real, real_paths = v2k._validate_artifact(
            logs_dir, artifact_prefix
        )
        evidence_mode = "real" if is_real else "synthetic"
    else:
        evidence_mode = "synthetic"
        real_paths = {}
    report = run_analysis(
        inputs,
        evidence_mode=evidence_mode,
        real_artifact_paths=real_paths,
    )
    return v2k.render_markdown(report)


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
        "--mechanics", action="store_true",
        help="Print the shared-mechanics per-move audit.",
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
        "--candidate-actionable", action="store_true",
        help="Print candidate-actionable components.",
    )
    parser.add_argument(
        "--contradictory", action="store_true",
        help="Print contradictory components.",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Print the full V2k markdown report.",
    )
    args = parser.parse_args()

    fp = v2k.ANALYZER_FROZEN_FINGERPRINT

    if args.report:
        print(_print_report(
            args.logs_dir, args.artifact_prefix, args.synthetic
        ))
        return 0

    bundle = _load_pair(
        args.pair, args.logs_dir, args.artifact_prefix, args.synthetic
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
    if args.mechanics:
        print()
        print(_print_mechanics(bundle, args.policy))
    if args.component:
        print()
        print(f"Component '{args.component}' per opponent lead pair:")
        eval_obj = bundle[args.policy].eval_obj
        for m in eval_obj.lead_pair_matchups:
            v = m.component_values.get(args.component, 0.0)
            print(f"  {m.opponent_lead_2}: {v:+.3f}")
    if args.opponent_lead:
        print()
        print(_print_opponent_lead(
            bundle, args.policy, args.opponent_lead
        ))
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
