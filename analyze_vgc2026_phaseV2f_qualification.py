#!/usr/bin/env python3
"""Analyze the V2f paired qualification for matchup_top4_v3 vs random.

Behavior:
- Merge D1/D2 by pair_id, never row position.
- Normalize all outcomes from V3 policy perspective.
  - D1: V3 is the player; V3 won iff our_win == True.
  - D2: V3 is the opponent; V3 won iff opponent_win == True.
- Extract V3 plans ONLY from preview rows where
  player_policy == "matchup_top4_v3". The opponent_policy field is
  metadata only and must never be used to attribute plan ownership.
- Cross-check D1 vs D2 V3 plan equality for the same team/opponent
  input (with deterministic seeds).
- Render JSON + Markdown reports.
"""

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


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
    successes: int, trials: int, alternative: str = "two-sided"
) -> float:
    if trials <= 0:
        return 1.0
    probabilities = [
        math.comb(trials, k) / (2 ** trials) for k in range(trials + 1)
    ]
    if alternative == "greater":
        return min(1.0, sum(probabilities[successes:]))
    observed = probabilities[successes]
    return min(
        1.0,
        sum(
            probability
            for probability in probabilities
            if probability <= observed + 1e-15
        ),
    )


def paired_sign_test(
    pairs: Sequence[Mapping[str, Any]],
) -> Tuple[int, int, int, int, float, float]:
    """Return (v3_both, random_both, split, invalid, two_sided_p, one_sided_p).

    V3 perspective per pair:
        - v3_both: V3 wins both D1 and D2.
        - random_both: V3 loses both.
        - split: V3 wins one, loses the other.
        - invalid: incomplete / non-decisive pair.
    """
    v3_both = 0
    random_both = 0
    split = 0
    invalid = 0
    for pair in pairs:
        d1 = pair.get("d1_v3")
        d2 = pair.get("d2_v3")
        if d1 is None or d2 is None or "outcome" not in d1 or "outcome" not in d2:
            invalid += 1
            continue
        outcome_d1 = d1["outcome"]
        outcome_d2 = d2["outcome"]
        if "win" in (outcome_d1, outcome_d2) and "loss" in (
            outcome_d1, outcome_d2
        ):
            split += 1
        elif outcome_d1 == "win" and outcome_d2 == "win":
            v3_both += 1
        elif outcome_d1 == "loss" and outcome_d2 == "loss":
            random_both += 1
        else:
            invalid += 1
    # Split pairs contain one win for each policy and therefore provide no
    # direction for the paired sign test. Only same-winner pairs are decisive.
    n = v3_both + random_both
    wins = v3_both
    two_sided = exact_binomial_p_value(wins, n)
    one_sided = exact_binomial_p_value(wins, n, alternative="greater")
    return v3_both, random_both, split, invalid, two_sided, one_sided


# ---------------------------------------------------------------------------
# Pair extraction
# ---------------------------------------------------------------------------


def extract_pairs(
    benchmark_rows: Sequence[Mapping[str, Any]],
    preview_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Build the pair list, with V3-perspective outcomes and V3 plan
    ownership keyed on player_policy only."""
    preview_by_battle: Dict[str, List[Mapping[str, Any]]] = {}
    for row in preview_rows:
        preview_by_battle.setdefault(
            str(row.get("battle_tag", "")), []
        ).append(row)

    by_pair: Dict[int, Dict[str, Mapping[str, Any]]] = {}
    for row in benchmark_rows:
        pair_id = int(row["pair_id"])
        arm = str(row.get("battle_tag", "")).split("_", 1)[0]
        by_pair.setdefault(pair_id, {})[arm] = row

    pairs: List[Dict[str, Any]] = []
    for pair_id in sorted(by_pair):
        arms = by_pair[pair_id]
        d1 = arms.get("D1")
        d2 = arms.get("D2")
        if d1 is None or d2 is None:
            pairs.append({
                "pair_id": pair_id,
                "status": "incomplete",
                "reason": "missing D1 or D2 benchmark row",
            })
            continue
        d1_v3 = _v3_perspective(d1)
        d2_v3 = _v3_perspective(d2)
        d1_battle = str(d1.get("battle_tag", ""))
        d2_battle = str(d2.get("battle_tag", ""))
        d1_v3_plan = _v3_plan_from_preview_rows(
            preview_by_battle.get(d1_battle, [])
        )
        d2_v3_plan = _v3_plan_from_preview_rows(
            preview_by_battle.get(d2_battle, [])
        )
        pairs.append({
            "pair_id": pair_id,
            "status": "ok",
            "d1_battle": d1_battle,
            "d2_battle": d2_battle,
            "d1_team_id": d1.get("team_id"),
            "d1_opp_team_id": d1.get("opponent_team_id"),
            "d2_team_id": d2.get("team_id"),
            "d2_opp_team_id": d2.get("opponent_team_id"),
            "team_identity_match": (
                d1.get("team_id") == d2.get("team_id")
                and d1.get("opponent_team_id") == d2.get("opponent_team_id")
            ),
            "d1_v3": d1_v3,
            "d2_v3": d2_v3,
            "d1_v3_plan": d1_v3_plan,
            "d2_v3_plan": d2_v3_plan,
            "v3_plans_match": _plans_equal(d1_v3_plan, d2_v3_plan),
            "d1_v3_plan_available": d1_v3_plan is not None,
            "d2_v3_plan_available": d2_v3_plan is not None,
        })
    return pairs


def _v3_perspective(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Return V3-perspective outcome for one arm."""
    arm = str(row.get("battle_tag", "")).split("_", 1)[0]
    if arm == "D1":
        # V3 is the player.
        won = _parse_bool(row.get("our_win"))
    elif arm == "D2":
        # V3 is the opponent.
        won = _parse_bool(row.get("opponent_win"))
    else:
        return {"outcome": "invalid", "reason": f"unexpected arm {arm!r}"}
    return {
        "outcome": "win" if won else "loss",
        "battle_result": row.get("battle_result"),
    }


def _v3_plan_from_preview_rows(
    rows: Sequence[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """V3 plan ownership is keyed ONLY on player_policy. The
    opponent_policy field is metadata and never selects the owner."""
    for row in rows:
        if row.get("player_policy") != "matchup_top4_v3":
            continue
        chosen = str(row.get("planned_chosen_4", ""))
        leads = str(row.get("planned_lead_2", ""))
        backs = str(row.get("planned_back_2", ""))
        if not (chosen and leads and backs):
            continue
        return {
            "chosen_4": chosen.split("|"),
            "lead_2": leads.split("|"),
            "back_2": backs.split("|"),
            "source_battle_tag": row.get("battle_tag"),
            "source_player_policy": row.get("player_policy"),
        }
    return None


def _plans_equal(
    plan_a: Optional[Mapping[str, Any]],
    plan_b: Optional[Mapping[str, Any]],
) -> Optional[bool]:
    if plan_a is None or plan_b is None:
        return None
    for field in ("chosen_4", "lead_2", "back_2"):
        if plan_a.get(field) != plan_b.get(field):
            return False
    return True


# ---------------------------------------------------------------------------
# Aggregate analysis
# ---------------------------------------------------------------------------


def aggregate(pairs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Build the per-arm and paired statistics."""
    d1_v3_wins = 0
    d1_v3_losses = 0
    d1_v3_ties = 0
    d2_v3_wins = 0
    d2_v3_losses = 0
    d2_v3_ties = 0
    for pair in pairs:
        if pair.get("status") != "ok":
            continue
        d1 = pair["d1_v3"]
        d2 = pair["d2_v3"]
        if d1["outcome"] == "win":
            d1_v3_wins += 1
        elif d1["outcome"] == "loss":
            d1_v3_losses += 1
        else:
            d1_v3_ties += 1
        if d2["outcome"] == "win":
            d2_v3_wins += 1
        elif d2["outcome"] == "loss":
            d2_v3_losses += 1
        else:
            d2_v3_ties += 1

    combined_wins = d1_v3_wins + d2_v3_wins
    combined_losses = d1_v3_losses + d2_v3_losses
    combined_ties = d1_v3_ties + d2_v3_ties
    decisive = combined_wins + combined_losses
    win_rate = combined_wins / decisive if decisive else 0.0
    ci_low, ci_high = wilson_interval(combined_wins, decisive)
    aggregate_p = exact_binomial_p_value(combined_wins, decisive)

    v3_both, random_both, split, invalid, two_sided_p, one_sided_p = (
        paired_sign_test(pairs)
    )

    d1_decisive = d1_v3_wins + d1_v3_losses
    d2_decisive = d2_v3_wins + d2_v3_losses
    d1_win_rate = (
        d1_v3_wins / d1_decisive if d1_decisive else 0.0
    )
    d2_win_rate = (
        d2_v3_wins / d2_decisive if d2_decisive else 0.0
    )

    return {
        "total_pairs": len(pairs),
        "completed_pairs": sum(
            1 for p in pairs if p.get("status") == "ok"
        ),
        "d1": {
            "battles": d1_decisive,
            "v3_wins": d1_v3_wins,
            "v3_losses": d1_v3_losses,
            "v3_ties": d1_v3_ties,
            "v3_win_rate": d1_win_rate,
        },
        "d2": {
            "battles": d2_decisive,
            "v3_wins": d2_v3_wins,
            "v3_losses": d2_v3_losses,
            "v3_ties": d2_v3_ties,
            "v3_win_rate": d2_win_rate,
        },
        "combined": {
            "battles": decisive,
            "v3_wins": combined_wins,
            "v3_losses": combined_losses,
            "v3_ties": combined_ties,
            "v3_win_rate": win_rate,
            "wilson_95_ci": [ci_low, ci_high],
            "two_sided_binomial_p_value": aggregate_p,
        },
        "paired": {
            "v3_both": v3_both,
            "random_both": random_both,
            "split": split,
            "invalid": invalid,
            "two_sided_p_value": two_sided_p,
            "one_sided_greater_p_value": one_sided_p,
        },
    }


def preview_evidence_stats(
    preview_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, int]:
    matches = sum(
        1 for row in preview_rows
        if row.get("preview_matches_plan") == "True"
    )
    observed = sum(
        1 for row in preview_rows
        if str(row.get("observed_actual_lead_on_turn1", "")).strip()
    )
    v3_rows = [
        row for row in preview_rows
        if row.get("player_policy") == "matchup_top4_v3"
    ]
    return {
        "preview_rows": len(preview_rows),
        "preview_matches": matches,
        "observed_leads_populated": observed,
        "v3_player_policy_rows": len(v3_rows),
    }


def plan_consistency_stats(
    pairs: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Count D1 vs D2 V3 plan equality across pairs where both
    plans are available."""
    both_available = 0
    matches = 0
    mismatches: List[Dict[str, Any]] = []
    for pair in pairs:
        if pair.get("status") != "ok":
            continue
        if not (pair.get("d1_v3_plan_available") and pair.get("d2_v3_plan_available")):
            continue
        both_available += 1
        if pair.get("v3_plans_match") is True:
            matches += 1
        else:
            mismatches.append({
                "pair_id": pair["pair_id"],
                "d1_plan": pair["d1_v3_plan"],
                "d2_plan": pair["d2_v3_plan"],
            })
    return {
        "pairs_with_both_v3_plans": both_available,
        "v3_plan_matches": matches,
        "v3_plan_mismatches": len(mismatches),
        "v3_plan_mismatch_pairs": mismatches,
    }


# ---------------------------------------------------------------------------
# Qualification gate evaluation
# ---------------------------------------------------------------------------


GATE_NAMES = (
    "all_tests_pass",
    "exactly_200_battles",
    "zero_timeouts_or_errors",
    "preview_match_400_400",
    "observed_leads_400_400",
    "all_100_d1_d2_pairs_complete",
    "v3_plans_deterministic",
    "combined_v3_win_rate_above_50",
    "v3_both_above_random_both",
    "paired_sign_test_significant",
    "no_suspicious_side_collapse",
)


def evaluate_gates(
    aggregate_data: Mapping[str, Any],
    preview_stats: Mapping[str, int],
    plan_stats: Mapping[str, Any],
    tests_passed: bool,
) -> Dict[str, bool]:
    combined = aggregate_data["combined"]
    paired = aggregate_data["paired"]
    d1 = aggregate_data["d1"]
    d2 = aggregate_data["d2"]
    return {
        "all_tests_pass": tests_passed,
        "exactly_200_battles": combined["battles"] == 200,
        "zero_timeouts_or_errors": (
            combined["v3_ties"] == 0
            and preview_stats["preview_rows"]
            == preview_stats["preview_matches"]
        ),
        "preview_match_400_400": preview_stats["preview_matches"] == 400,
        "observed_leads_400_400": (
            preview_stats["observed_leads_populated"] == 400
        ),
        "all_100_d1_d2_pairs_complete": (
            aggregate_data["completed_pairs"] == 100
        ),
        "v3_plans_deterministic": (
            plan_stats["v3_plan_mismatches"] == 0
            and plan_stats["pairs_with_both_v3_plans"] == 100
        ),
        "combined_v3_win_rate_above_50": (
            combined["v3_win_rate"] > 0.5
        ),
        "v3_both_above_random_both": (
            paired["v3_both"] > paired["random_both"]
        ),
        "paired_sign_test_significant": (
            paired["two_sided_p_value"] < 0.05
        ),
        "no_suspicious_side_collapse": (
            d1["v3_win_rate"] >= 0.4 and d2["v3_win_rate"] >= 0.4
        ),
    }


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def load_artifacts(
    logs_dir: Path,
    artifact_prefix: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    csv_path = logs_dir / f"{artifact_prefix}_benchmark.csv"
    jsonl_path = logs_dir / f"{artifact_prefix}_benchmark.jsonl"
    preview_path = logs_dir / f"{artifact_prefix}_preview_evidence.csv"
    with csv_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    with jsonl_path.open() as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    with preview_path.open(newline="") as handle:
        previews = list(csv.DictReader(handle))
    return rows, records, previews


def write_json_report(
    report: Mapping[str, Any],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as handle:
        json.dump(report, handle, indent=2, default=str)


def render_markdown(
    aggregate_data: Mapping[str, Any],
    preview_stats: Mapping[str, int],
    plan_stats: Mapping[str, Any],
    gate_results: Mapping[str, bool],
    artifact_prefix: str,
) -> str:
    lines: List[str] = []
    lines.append("# Phase V2f Paired Qualification — matchup_top4_v3 vs random")
    lines.append("")
    lines.append(f"Artifact tag: `{artifact_prefix}`")
    lines.append("")
    lines.append("## D1 / D2 rows")
    lines.append("")
    lines.append("| Arm | Battles | V3 wins | V3 losses | V3 ties | Win rate |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for arm in ("d1", "d2"):
        stats = aggregate_data[arm]
        lines.append(
            f"| {arm.upper()} | {stats['battles']} | "
            f"{stats['v3_wins']} | {stats['v3_losses']} | "
            f"{stats['v3_ties']} | {stats['v3_win_rate']:.1%} |"
        )
    lines.append("")
    lines.append("## Combined statistics")
    lines.append("")
    combined = aggregate_data["combined"]
    lines.append(f"Battles: {combined['battles']}")
    lines.append(f"V3 wins: {combined['v3_wins']}")
    lines.append(f"V3 losses: {combined['v3_losses']}")
    lines.append(f"V3 ties: {combined['v3_ties']}")
    lines.append(f"V3 win rate: {combined['v3_win_rate']:.1%}")
    ci = combined["wilson_95_ci"]
    lines.append(
        f"Wilson 95% CI: {ci[0]:.1%} - {ci[1]:.1%}"
    )
    lines.append(
        f"Exact aggregate two-sided binomial p-value: "
        f"{combined['two_sided_binomial_p_value']:.6f}"
    )
    lines.append("")
    lines.append("## Paired statistics")
    lines.append("")
    paired = aggregate_data["paired"]
    lines.append("| V3 wins both | Random wins both | Split | Invalid | Two-sided p | One-sided p (V3) |")
    lines.append("|---:|---:|---:|---:|---:|---:|")
    lines.append(
        f"| {paired['v3_both']} | {paired['random_both']} | "
        f"{paired['split']} | {paired['invalid']} | "
        f"{paired['two_sided_p_value']:.6f} | "
        f"{paired['one_sided_greater_p_value']:.6f} |"
    )
    lines.append("")
    lines.append("## Preview evidence")
    lines.append("")
    lines.append(f"Preview rows: {preview_stats['preview_rows']}")
    lines.append(
        f"Preview matched plan: {preview_stats['preview_matches']} / "
        f"{preview_stats['preview_rows']}"
    )
    lines.append(
        f"Observed leads populated: "
        f"{preview_stats['observed_leads_populated']} / "
        f"{preview_stats['preview_rows']}"
    )
    lines.append(
        f"Rows with player_policy=matchup_top4_v3: "
        f"{preview_stats['v3_player_policy_rows']}"
    )
    lines.append("")
    lines.append("## V3 plan consistency across D1/D2")
    lines.append("")
    lines.append(
        f"Pairs with both V3 plans available: "
        f"{plan_stats['pairs_with_both_v3_plans']}"
    )
    lines.append(
        f"V3 plans match: {plan_stats['v3_plan_matches']} / "
        f"{plan_stats['pairs_with_both_v3_plans']}"
    )
    lines.append(
        f"V3 plan mismatches: {plan_stats['v3_plan_mismatches']}"
    )
    if plan_stats["v3_plan_mismatch_pairs"]:
        lines.append("")
        lines.append("Mismatched pairs:")
        for entry in plan_stats["v3_plan_mismatch_pairs"]:
            lines.append(f"- pair_id={entry['pair_id']}")
    lines.append("")
    lines.append("## Qualification gates")
    lines.append("")
    lines.append("| Gate | Result |")
    lines.append("|---|:---:|")
    for name in GATE_NAMES:
        passed = gate_results.get(name, False)
        lines.append(f"| {name} | {'PASS' if passed else 'FAIL'} |")
    lines.append("")
    all_passed = all(gate_results.values())
    lines.append(
        f"**Qualification: {'PASS' if all_passed else 'BLOCKED'}**"
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
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
        required=True,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs/"
            "vgc2026_phaseV2f_analysis.json"
        ),
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path(
            "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs/"
            "vgc2026_phaseV2f_analysis.md"
        ),
    )
    parser.add_argument(
        "--tests-passed",
        action="store_true",
        help="Mark the all_tests_pass gate as satisfied.",
    )
    args = parser.parse_args()

    rows, records, previews = load_artifacts(
        args.logs_dir, args.artifact_prefix
    )
    pairs = extract_pairs(rows, previews)
    aggregate_data = aggregate(pairs)
    preview_stats = preview_evidence_stats(previews)
    plan_stats = plan_consistency_stats(pairs)
    gate_results = evaluate_gates(
        aggregate_data, preview_stats, plan_stats, args.tests_passed
    )

    report = {
        "artifact_prefix": args.artifact_prefix,
        "rows": {"benchmark_csv": len(rows), "jsonl": len(records)},
        "preview_stats": preview_stats,
        "aggregate": aggregate_data,
        "plan_consistency": plan_stats,
        "gates": gate_results,
        "all_gates_pass": all(gate_results.values()),
        "pair_details": pairs,
    }
    write_json_report(report, args.output)
    markdown = render_markdown(
        aggregate_data, preview_stats, plan_stats, gate_results,
        args.artifact_prefix,
    )
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(markdown)
    print(markdown)
    print(f"JSON: {args.output}")
    print(f"Markdown: {args.markdown}")
    return 0 if all(gate_results.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
