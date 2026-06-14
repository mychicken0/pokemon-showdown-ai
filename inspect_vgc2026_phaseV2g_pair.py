#!/usr/bin/env python3
"""VGC 2026 Phase V2g pair inspector.

Print the full diagnostic record for a single V2f pair by pair_id.
Includes:
- D1 and D2 outcome from V3 perspective
- V3 plan and Random plan on each side (extracted from preview
  evidence using player_policy as the sole ownership key)
- Common-evaluator score for each plan
- Plan-features bundle for each plan
- A short note about pair classification (v3_both / random_both /
  split) and the contribution to the paired sign test
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_vgc2026_phaseV2g_failures import (
    build_bundles_by_pair,
    build_pair_records,
    classify_pair,
    load_v2f_artifacts,
    sign_test,
)
from vgc2026_common_plan_evaluator import evaluate_plan_on_common_scale


def _format_bundle(name: str, bundle: Optional[Mapping[str, Any]]) -> str:
    if bundle is None:
        return f"## {name}: <missing>\n"
    if "error" in bundle:
        return (
            f"## {name}: ERROR: {bundle['error']}\n"
            f"- chosen_4: {bundle.get('chosen_4')}\n"
            f"- lead_2: {bundle.get('lead_2')}\n"
            f"- back_2: {bundle.get('back_2')}\n"
        )
    lines: list[str] = [f"## {name}"]
    lines.append(f"- chosen_4: {bundle.get('chosen_4')}")
    lines.append(f"- lead_2: {bundle.get('lead_2')}")
    lines.append(f"- back_2: {bundle.get('back_2')}")
    lines.append(f"- common_total: {bundle.get('common_total'):.3f}")
    lines.append("### Common components")
    for key, value in sorted(bundle.get("components", {}).items()):
        lines.append(f"  - {key}: {value:.3f}")
    lines.append("### Plan features")
    for key, value in sorted(bundle.get("features", {}).items()):
        lines.append(f"  - {key}: {value:.3f}")
    cat = bundle.get("categorical", {})
    if cat:
        lines.append("### Categorical")
        for key, value in sorted(cat.items()):
            lines.append(f"  - {key}: {value}")
    return "\n".join(lines) + "\n"


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
    parser.add_argument("--pair-id", type=int, required=True)
    args = parser.parse_args()

    benchmark_rows, preview_rows, team_lookup = load_v2f_artifacts(
        args.logs_dir, args.artifact_prefix
    )
    pairs = build_pair_records(
        benchmark_rows, preview_rows, team_lookup
    )
    pair = next(
        (p for p in pairs if p["pair_id"] == args.pair_id), None
    )
    if pair is None:
        print(f"Pair {args.pair_id} not found")
        return 2

    bundles_by_pair = build_bundles_by_pair([pair], team_lookup)
    pair_bundles = dict(bundles_by_pair).get(args.pair_id, {})
    classification = classify_pair(pair)
    sign_stats = sign_test([pair])

    out: list[str] = []
    out.append(f"# Pair {args.pair_id}")
    out.append("")
    out.append(f"D1 battle tag: `{pair.get('d1_battle')}`")
    out.append(f"D2 battle tag: `{pair.get('d2_battle')}`")
    out.append(f"Team id: `{pair.get('d1_team_id')}`")
    out.append(f"Opponent team id: `{pair.get('d1_opp_team_id')}`")
    out.append(
        f"D1 V3 outcome: {pair.get('d1_outcome')} | "
        f"D2 V3 outcome: {pair.get('d2_outcome')}"
    )
    out.append(f"Classification: **{classification}**")
    out.append(
        "This pair is "
        + ("DECISIVE for the paired sign test (V3-both or Random-both)."
           if classification in {"v3_both", "random_both"}
           else "EXCLUDED from the paired sign test (split).")
    )
    out.append("")
    out.append("## V3 plans (player_policy=matchup_top4_v3 only)")
    out.append(_format_bundle(
        "D1 V3 plan", pair_bundles.get("d1_v3")
    ))
    out.append(_format_bundle(
        "D2 V3 plan", pair_bundles.get("d2_v3")
    ))
    out.append(
        f"V3 plans match (D1 == D2): "
        f"{'YES' if pair.get('v3_plans_match') else 'NO'}"
    )
    out.append("")
    out.append("## Random plans (player_policy=random only)")
    out.append(_format_bundle(
        "D1 Random plan", pair_bundles.get("d1_random")
    ))
    out.append(_format_bundle(
        "D2 Random plan", pair_bundles.get("d2_random")
    ))
    out.append("")
    out.append("## Sign test contribution")
    out.append(
        f"v3_both: {sign_stats['v3_both']}, "
        f"random_both: {sign_stats['random_both']}, "
        f"split: {sign_stats['split']}"
    )
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
