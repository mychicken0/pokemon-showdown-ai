#!/usr/bin/env python3
"""
VGC 2026 Phase V2h feature inspector.

Usage:

    inspect_vgc2026_phaseV2h_feature.py --feature common_total
    inspect_vgc2026_phaseV2h_feature.py --feature common_total --pair 0
    inspect_vgc2026_phaseV2h_feature.py --feature common_total --group random_both
    inspect_vgc2026_phaseV2h_feature.py --feature common_total --largest-positive 5
    inspect_vgc2026_phaseV2h_feature.py --feature common_total --largest-negative 5
    inspect_vgc2026_phaseV2h_feature.py --contradictory
    inspect_vgc2026_phaseV2h_feature.py --candidate-actionable

For every line the inspector prints the pair_id, the pair
outcome class, the exact V3 plan (chosen_4, lead_2, back_2),
the exact Random plan, the per-plan feature value, and a label
saying whether the value is preview-visible or post-battle-only.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_vgc2026_phaseV2g_failures import (
    build_bundles_by_pair,
    build_pair_records,
    classify_pair,
    load_v2f_artifacts,
)
from analyze_vgc2026_phaseV2h_feature_stability import (
    MIN_DECISIVE_PAIRS,
    run_analysis,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _feature_value(
    bundle: Optional[Mapping[str, Any]], feature: str
) -> Optional[float]:
    if bundle is None or "error" in bundle:
        return None
    return bundle.get("features", {}).get(feature)


def _label(visibility: str) -> str:
    return f"[{visibility}]"


# ---------------------------------------------------------------------------
# Per-pair view
# ---------------------------------------------------------------------------


def _print_pair(
    pair: Mapping[str, Any],
    bundles_by_pair: Dict[int, Mapping[str, Any]],
    feature: Optional[str],
) -> None:
    pair_id = pair["pair_id"]
    classification = classify_pair(pair)
    print(
        f"# Pair {pair_id} | classification={classification} | "
        f"team={pair.get('d1_team_id')} | "
        f"opponent={pair.get('d1_opp_team_id')}"
    )
    bundles = bundles_by_pair.get(pair_id, {})
    v3_b = bundles.get("v3")
    rand_b = bundles.get("random")
    if v3_b and "error" not in v3_b:
        plan = v3_b
        print(
            f"  V3 plan: chosen_4={plan['chosen_4']}, "
            f"leads={plan['lead_2']}, backs={plan['back_2']} "
            f"{_label('preview-visible')}"
        )
        if feature is not None:
            value = _feature_value(v3_b, feature)
            if value is not None:
                print(f"    {feature} = {value:.4f}")
    else:
        print("  V3 plan: <missing>")
    if rand_b and "error" not in rand_b:
        plan = rand_b
        print(
            f"  Random plan: chosen_4={plan['chosen_4']}, "
            f"leads={plan['lead_2']}, backs={plan['back_2']} "
            f"{_label('preview-visible')}"
        )
        if feature is not None:
            value = _feature_value(rand_b, feature)
            if value is not None:
                print(f"    {feature} = {value:.4f}")
    else:
        print("  Random plan: <missing>")


# ---------------------------------------------------------------------------
# Group view
# ---------------------------------------------------------------------------


def _print_group(
    feature: str,
    group: str,
    pairs: Sequence[Mapping[str, Any]],
    bundles_by_pair: Dict[int, Mapping[str, Any]],
    candidate_gates: Mapping[str, Mapping[str, Any]],
) -> None:
    if group in {"v3_both", "random_both", "split"}:
        matching = [p for p in pairs if classify_pair(p) == group]
    else:
        raise SystemExit(
            f"Unknown group {group!r}. Use v3_both|random_both|split."
        )
    gate = candidate_gates.get(feature, {})
    print(
        f"# Group {group} | {feature} | n={len(matching)} pairs"
    )
    print(
        f"# fold_stable={gate.get('fold_stable_count', 0)}/5, "
        f"loo_stable={gate.get('loo_stability', 0.0):.0%}, "
        f"bootstrap_excludes_zero={gate.get('bootstrap_paired_excludes_zero')}, "
        f"is_candidate_actionable={gate.get('is_candidate_actionable')}"
    )
    for pair in matching:
        bundles = bundles_by_pair.get(pair["pair_id"], {})
        v3_b = bundles.get("v3")
        value = _feature_value(v3_b, feature)
        if value is None:
            continue
        print(
            f"pair_id={pair['pair_id']} {feature}={value:.4f} "
            f"{_label('preview-visible')}"
        )


# ---------------------------------------------------------------------------
# Largest-positive / largest-negative
# ---------------------------------------------------------------------------


def _print_largest(
    feature: str,
    n: int,
    pairs: Sequence[Mapping[str, Any]],
    bundles_by_pair: Dict[int, Mapping[str, Any]],
    order: str,
) -> None:
    rows = []
    for pair in pairs:
        bundles = bundles_by_pair.get(pair["pair_id"], {})
        v3_b = bundles.get("v3")
        value = _feature_value(v3_b, feature)
        if value is None:
            continue
        rows.append((pair, value))
    rows.sort(key=lambda row: row[1], reverse=(order == "positive"))
    print(
        f"# {feature} | largest-{order} N={n} | "
        "V3 plan feature values (preview-visible)"
    )
    for pair, value in rows[:n]:
        print(
            f"pair_id={pair['pair_id']} "
            f"classification={classify_pair(pair)} "
            f"{feature}={value:+.4f}"
        )


# ---------------------------------------------------------------------------
# Contradictory / candidate-actionable
# ---------------------------------------------------------------------------


def _print_contradictory(
    report: Mapping[str, Any],
) -> None:
    contradictory = report.get("contradictory", [])
    print("# Contradictory features")
    print(
        f"# Definition: V3-both vs Random-both direction and "
        f"within-failure paired direction disagree. Sample size "
        f"is sufficient (n >= {MIN_DECISIVE_PAIRS})."
    )
    if not contradictory:
        print("(none)")
        return
    for feature in contradictory:
        v3_both = report["v3_both_table"][feature]
        within = report["within_failure_table"][feature]
        agreement = report["agreements"][feature]
        print(
            f"- {feature}: "
            f"v3_both-mean-diff={v3_both['mean_diff_v3_minus_random']:+.3f}, "
            f"within-failure-paired-diff="
            f"{within.get('paired_mean_diff_v3_minus_random', 0.0):+.3f}, "
            f"agree={agreement['agree']}"
        )


def _print_candidate_actionable(
    report: Mapping[str, Any],
) -> None:
    candidates = report.get("candidate_actionable", [])
    print("# Candidate-actionable features")
    if not candidates:
        print("(none)")
        return
    for feature in candidates:
        gate = report["candidate_gates"][feature]
        v3_both = report["v3_both_table"][feature]
        within = report["within_failure_table"][feature]
        print(
            f"- {feature}: fold={gate['fold_stable_count']}/5, "
            f"loo={gate['loo_stability']:.0%}, n={gate['n_decisive_pairs']}, "
            f"v3_both-mean-diff={v3_both['mean_diff_v3_minus_random']:+.3f}, "
            f"within-failure-paired-diff="
            f"{within.get('paired_mean_diff_v3_minus_random', 0.0):+.3f}, "
            f"bootstrap_excludes_zero={gate['bootstrap_paired_excludes_zero']}"
        )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=Path(
            "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs"
        ),
    )
    parser.add_argument(
        "--artifact-prefix",
        default=(
            "vgc2026_phaseV2c_phaseV2f_v3_paired_qualification"
        ),
    )
    parser.add_argument(
        "--feature",
        default=None,
        help=(
            "Feature name to inspect. Without --pair or --group, the "
            "feature is summarised across all 100 pairs."
        ),
    )
    parser.add_argument(
        "--pair", type=int, default=None,
        help="Single pair_id to inspect.",
    )
    parser.add_argument(
        "--group",
        choices=("v3_both", "random_both", "split"),
        default=None,
        help="Limit to one pair classification group.",
    )
    parser.add_argument(
        "--largest-positive", type=int, default=0,
        help="Print the N largest positive V3 plan feature values.",
    )
    parser.add_argument(
        "--largest-negative", type=int, default=0,
        help="Print the N largest negative V3 plan feature values.",
    )
    parser.add_argument(
        "--contradictory", action="store_true",
        help="Print contradictory features and exit.",
    )
    parser.add_argument(
        "--candidate-actionable", action="store_true",
        help="Print candidate-actionable features and exit.",
    )
    args = parser.parse_args()

    benchmark_rows, preview_rows, team_lookup = load_v2f_artifacts(
        args.logs_dir, args.artifact_prefix
    )
    pairs = build_pair_records(
        benchmark_rows, preview_rows, team_lookup
    )
    bundles_by_pair = dict(
        build_bundles_by_pair(pairs, team_lookup)
    )

    if args.contradictory or args.candidate_actionable:
        report = run_analysis(args.logs_dir, args.artifact_prefix)
        if args.contradictory:
            _print_contradictory(report)
        if args.candidate_actionable:
            _print_candidate_actionable(report)
        return 0

    if args.pair is not None:
        pair = next(
            (p for p in pairs if p["pair_id"] == args.pair), None
        )
        if pair is None:
            print(f"Pair {args.pair} not found")
            return 2
        _print_pair(
            pair, bundles_by_pair, args.feature
        )
        return 0

    if args.largest_positive or args.largest_negative:
        if args.feature is None:
            print("--feature is required with --largest-positive/--largest-negative")
            return 2
        if args.largest_positive:
            _print_largest(
                args.feature, args.largest_positive, pairs,
                bundles_by_pair, "positive",
            )
        if args.largest_negative:
            _print_largest(
                args.feature, args.largest_negative, pairs,
                bundles_by_pair, "negative",
            )
        return 0

    if args.group is not None:
        if args.feature is None:
            print("--feature is required with --group")
            return 2
        report = run_analysis(args.logs_dir, args.artifact_prefix)
        _print_group(
            args.feature, args.group, pairs, bundles_by_pair,
            report.get("candidate_gates", {}),
        )
        return 0

    if args.feature is not None:
        # Default: print the V3 plan feature value per pair.
        for pair in pairs:
            _print_pair(pair, bundles_by_pair, args.feature)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
