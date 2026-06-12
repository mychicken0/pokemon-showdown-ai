#!/usr/bin/env python3
"""Analyze the Phase V2d paired qualification artifacts."""

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def wilson_interval(wins: int, total: int) -> Tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    z = 1.959963984540054
    proportion = wins / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    radius = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return max(0.0, center - radius), min(1.0, center + radius)


def exact_binomial_p_value(
    successes: int,
    trials: int,
    alternative: str = "two-sided",
) -> float:
    if trials <= 0:
        return 1.0
    probabilities = [
        math.comb(trials, k) / (2 ** trials)
        for k in range(trials + 1)
    ]
    if alternative == "greater":
        return min(1.0, sum(probabilities[successes:]))
    observed = probabilities[successes]
    return min(
        1.0,
        sum(probability for probability in probabilities if probability <= observed + 1e-15),
    )


def normalize_v2_outcome(row: Dict[str, Any]) -> str:
    arm = str(row.get("battle_tag", "")).split("_", 1)[0]
    result = row.get("battle_result")
    if result == "tie":
        return "tie"
    if result not in {"win", "loss"}:
        return "invalid"
    if arm == "D1":
        return "win" if _parse_bool(row.get("our_win")) else "loss"
    if arm == "D2":
        return "win" if _parse_bool(row.get("opponent_win")) else "loss"
    return "invalid"


def analyze_pairs(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_pair: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for row in rows:
        pair_id = int(row["pair_id"])
        arm = str(row["battle_tag"]).split("_", 1)[0]
        by_pair.setdefault(pair_id, {})[arm] = row

    v2_both = 0
    random_both = 0
    split = 0
    invalid = 0
    details = []
    for pair_id in sorted(by_pair):
        pair = by_pair[pair_id]
        if set(pair) != {"D1", "D2"}:
            invalid += 1
            details.append({"pair_id": pair_id, "outcome": "incomplete"})
            continue
        first = normalize_v2_outcome(pair["D1"])
        second = normalize_v2_outcome(pair["D2"])
        if "invalid" in {first, second} or "tie" in {first, second}:
            invalid += 1
            outcome = "invalid"
        elif first == "win" and second == "win":
            v2_both += 1
            outcome = "v2_both"
        elif first == "loss" and second == "loss":
            random_both += 1
            outcome = "random_both"
        else:
            split += 1
            outcome = "split"
        details.append({
            "pair_id": pair_id,
            "d1_v2": first,
            "d2_v2": second,
            "outcome": outcome,
        })

    decisive = v2_both + random_both
    return {
        "pairs": len(by_pair),
        "v2_both": v2_both,
        "random_both": random_both,
        "split": split,
        "invalid": invalid,
        "decisive_pairs": decisive,
        "two_sided_p_value": exact_binomial_p_value(v2_both, decisive),
        "one_sided_greater_p_value": exact_binomial_p_value(
            v2_both, decisive, alternative="greater"
        ),
        "details": details,
    }


def analyze_artifacts(
    csv_path: Path,
    jsonl_path: Path,
    preview_path: Path,
    expected_pairs: int,
) -> Dict[str, Any]:
    with csv_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    with jsonl_path.open() as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    with preview_path.open(newline="") as handle:
        previews = list(csv.DictReader(handle))

    outcomes = [normalize_v2_outcome(row) for row in rows]
    wins = outcomes.count("win")
    losses = outcomes.count("loss")
    ties = outcomes.count("tie")
    invalid_outcomes = outcomes.count("invalid")
    total = len(outcomes)
    decisive = wins + losses
    ci_low, ci_high = wilson_interval(wins, decisive)

    arm_results: Dict[str, Dict[str, Any]] = {}
    for arm in ("D1", "D2"):
        arm_rows = [
            row for row in rows
            if str(row.get("battle_tag", "")).startswith(f"{arm}_")
        ]
        arm_outcomes = [normalize_v2_outcome(row) for row in arm_rows]
        arm_wins = arm_outcomes.count("win")
        arm_losses = arm_outcomes.count("loss")
        arm_results[arm] = {
            "battles": len(arm_rows),
            "v2_wins": arm_wins,
            "v2_losses": arm_losses,
            "v2_win_rate": arm_wins / max(arm_wins + arm_losses, 1),
        }

    preview_matches = [
        row.get("preview_matches_plan") == "True"
        for row in previews
    ]
    observed_leads = [
        bool(row.get("observed_actual_lead_on_turn1", "").strip())
        for row in previews
    ]
    record_tags = [record.get("battle_tag") for record in records]
    pair_analysis = analyze_pairs(rows)

    artifact_checks = {
        "csv_count": total == expected_pairs * 2,
        "jsonl_count": len(records) == expected_pairs * 2,
        "preview_count": len(previews) == expected_pairs * 4,
        "unique_jsonl_tags": len(record_tags) == len(set(record_tags)),
        "all_real_outcomes": invalid_outcomes == 0,
        "preview_match_100_percent": bool(preview_matches) and all(preview_matches),
        "observed_lead_100_percent": bool(observed_leads) and all(observed_leads),
        "complete_pairs": (
            pair_analysis["pairs"] == expected_pairs
            and pair_analysis["invalid"] == 0
        ),
    }
    aggregate_p = exact_binomial_p_value(wins, decisive)
    gate_checks = {
        "artifacts_valid": all(artifact_checks.values()),
        "aggregate_v2_above_50_percent": wins > losses,
        "paired_direction_favors_v2": (
            pair_analysis["v2_both"] > pair_analysis["random_both"]
        ),
        "paired_two_sided_significant": (
            pair_analysis["two_sided_p_value"] < 0.05
        ),
    }
    return {
        "expected_pairs": expected_pairs,
        "aggregate": {
            "battles": total,
            "v2_wins": wins,
            "v2_losses": losses,
            "ties": ties,
            "invalid": invalid_outcomes,
            "v2_win_rate": wins / max(decisive, 1),
            "wilson_95_ci": [ci_low, ci_high],
            "two_sided_binomial_p_value": aggregate_p,
        },
        "arms": arm_results,
        "paired": pair_analysis,
        "artifact_checks": artifact_checks,
        "gate_checks": gate_checks,
        "qualification_pass": all(gate_checks.values()),
    }


def render_markdown(analysis: Dict[str, Any], artifact_tag: str) -> str:
    aggregate = analysis["aggregate"]
    paired = analysis["paired"]
    lines = [
        "# Phase V2d Paired Qualification",
        "",
        f"Artifact tag: `{artifact_tag}`",
        "",
        "## Aggregate",
        "",
        "| Battles | V2 wins | V2 losses | Win rate | Wilson 95% CI | Exact p |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| {aggregate['battles']} | {aggregate['v2_wins']} | "
            f"{aggregate['v2_losses']} | {aggregate['v2_win_rate']:.1%} | "
            f"{aggregate['wilson_95_ci'][0]:.1%} - "
            f"{aggregate['wilson_95_ci'][1]:.1%} | "
            f"{aggregate['two_sided_binomial_p_value']:.6f} |"
        ),
        "",
        "## Paired Result",
        "",
        "| V2 wins both | Random wins both | Split | Invalid | Two-sided p |",
        "|---:|---:|---:|---:|---:|",
        (
            f"| {paired['v2_both']} | {paired['random_both']} | "
            f"{paired['split']} | {paired['invalid']} | "
            f"{paired['two_sided_p_value']:.6f} |"
        ),
        "",
        "## Gate",
        "",
    ]
    for name, passed in analysis["gate_checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'}: `{name}`")
    lines.extend([
        "",
        f"**Qualification: {'PASS' if analysis['qualification_pass'] else 'BLOCKED'}**",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-tag", required=True)
    parser.add_argument("--pairs", type=int, default=100)
    parser.add_argument("--log-dir", type=Path, default=Path("logs"))
    args = parser.parse_args()

    prefix = f"vgc2026_phaseV2c_{args.artifact_tag}"
    analysis = analyze_artifacts(
        args.log_dir / f"{prefix}_benchmark.csv",
        args.log_dir / f"{prefix}_benchmark.jsonl",
        args.log_dir / f"{prefix}_preview_evidence.csv",
        args.pairs,
    )
    json_path = args.log_dir / f"{args.artifact_tag}_analysis.json"
    markdown_path = args.log_dir / f"{args.artifact_tag}_analysis.md"
    with json_path.open("w") as handle:
        json.dump(analysis, handle, indent=2)
    markdown = render_markdown(analysis, args.artifact_tag)
    with markdown_path.open("w") as handle:
        handle.write(markdown)
    print(markdown)
    print(f"JSON: {json_path}")
    print(f"Markdown: {markdown_path}")
    return 0 if analysis["artifact_checks"]["complete_pairs"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
