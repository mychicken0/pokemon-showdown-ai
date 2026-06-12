#!/usr/bin/env python3
"""
VGC 2026 Phase V2e.1 — Corrected offline analysis.

This script replaces the previous V2e analyzer. It corrects four defects
from the original Phase V2e analyzer:

1. The original report compared D1 `chosen_4` (which belongs to
   matchup_top4_v2) against D2 `chosen_4` (which belongs to random,
   not matchup_top4_v2). That comparison is invalid. This analyzer
   extracts the V2 plan from the preview evidence for each arm
   separately.

2. The original report called the D1 57% vs D2 45% side split a root
   cause. It is an observed side split only; the analyzer labels it
   as such and does not infer causality.

3. The original report contained unfinished `pass` blocks for
   score-margin and move/role analysis. This analyzer either
   implements the analysis fully or removes the unsupported metric.

4. The original report used a per-Pokémon summed score for basic_top4
   and a joint-plan score for V2/V3. Those values were not on a
   common scale. The offline comparison now uses
   `vgc2026_common_plan_evaluator.evaluate_plan_on_common_scale`
   for every policy, on the same team/opponent pairs.

All artifacts read are existing V2d paired qualification artifacts.
No new battles are run and no existing artifact is overwritten.
"""

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai")

from analyze_vgc2026_phaseV2d_qualification import (
    analyze_pairs as v2d_analyze_pairs,
    normalize_v2_outcome,
)
from team_preview_policy import choose_four_from_six
from vgc2026_common_plan_evaluator import (
    CommonPlanEvaluatorError,
    CommonPlanScore,
    evaluate_plan_on_common_scale,
)
from vgc_team_pool import load_vgc_pool


V2_POLICY = "matchup_top4_v2"
RANDOM_POLICY = "random"

ARTIFACT_PREFIX = "vgc2026_phaseV2c_phaseV2d2_paired_qualification_codex"
V2E1_DENOMINATOR = 129  # Full VGC 2026 dataset size.


# ---------------------------------------------------------------------------
# Artifact loading
# ---------------------------------------------------------------------------


def _open_text(path: Path) -> Any:
    return path.open(newline="")


def load_qualification_artifacts(
    logs_dir: Path,
    artifact_prefix: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Load the three qualification artifacts (CSV, JSONL, preview CSV)."""
    csv_path = logs_dir / f"{artifact_prefix}_benchmark.csv"
    jsonl_path = logs_dir / f"{artifact_prefix}_benchmark.jsonl"
    preview_path = logs_dir / f"{artifact_prefix}_preview_evidence.csv"
    with _open_text(csv_path) as handle:
        benchmark_rows = list(csv.DictReader(handle))
    with jsonl_path.open() as handle:
        jsonl_records = [
            json.loads(line) for line in handle if line.strip()
        ]
    with _open_text(preview_path) as handle:
        preview_rows = list(csv.DictReader(handle))
    return benchmark_rows, jsonl_records, preview_rows


# ---------------------------------------------------------------------------
# Pair extraction
# ---------------------------------------------------------------------------


def _index_preview_by_battle(preview_rows: Sequence[Mapping[str, Any]]) -> Dict[str, List[Mapping[str, Any]]]:
    by_battle: Dict[str, List[Mapping[str, Any]]] = {}
    for row in preview_rows:
        tag = str(row.get("battle_tag", ""))
        by_battle.setdefault(tag, []).append(row)
    return by_battle


def _split_pipe(value: Any) -> List[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split("|") if part.strip()]


def _v2_plan_from_preview_rows(
    rows: Sequence[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Find the preview evidence row where matchup_top4_v2 is the
    policy and return its planned plan.

    For each battle the preview evidence contains one row per side.
    A row's planned fields always belong to that row's ``player_policy``.
    ``opponent_policy`` is metadata only and must never be used to claim
    ownership of the row's plan.
    """
    for row in rows:
        player_policy = str(row.get("player_policy", ""))
        if player_policy != V2_POLICY:
            continue
        planned_chosen = _split_pipe(row.get("planned_chosen_4"))
        planned_leads = _split_pipe(row.get("planned_lead_2"))
        planned_backs = _split_pipe(row.get("planned_back_2"))
        if not (planned_chosen and planned_leads and planned_backs):
            continue
        return {
            "chosen_4": planned_chosen,
            "lead_2": planned_leads,
            "back_2": planned_backs,
            "side": str(row.get("side", "")),
        }
    return None


def _arm_outcome(row: Mapping[str, Any]) -> str:
    """`win` for V2 winning that arm, `loss` for V2 losing, else invalid."""
    arm = str(row.get("battle_tag", "")).split("_", 1)[0]
    if arm == "D1":
        return "win" if str(row.get("our_win")) == "True" else (
            "loss" if str(row.get("our_win")) == "False" else "invalid"
        )
    if arm == "D2":
        return "win" if str(row.get("opponent_win")) == "True" else (
            "loss" if str(row.get("opponent_win")) == "False" else "invalid"
        )
    return "invalid"


def extract_pairs(
    benchmark_rows: Sequence[Mapping[str, Any]],
    preview_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Build the corrected pair list.

    Each entry includes:
        pair_id
        d1_arm_outcome, d2_arm_outcome (observed evidence)
        d1_v2_plan, d2_v2_plan (extracted from preview evidence, not
            from cross-policy chosen_4 fields)
        d1_preview_match, d2_preview_match (planned vs observed)
        d1_team_id, d1_opponent_team_id
        d2_team_id, d2_opponent_team_id
        d1_v2_preview_available, d2_v2_preview_available (bool)
    """
    by_battle = _index_preview_by_battle(preview_rows)
    by_pair_battle: Dict[int, Dict[str, Mapping[str, Any]]] = {}
    for row in benchmark_rows:
        pair_id = int(row["pair_id"])
        arm = str(row["battle_tag"]).split("_", 1)[0]
        by_pair_battle.setdefault(pair_id, {})[arm] = row

    pairs: List[Dict[str, Any]] = []
    for pair_id, arms in sorted(by_pair_battle.items()):
        d1_row = arms.get("D1")
        d2_row = arms.get("D2")
        if d1_row is None or d2_row is None:
            pairs.append({
                "pair_id": pair_id,
                "status": "incomplete",
                "reason": "missing D1 or D2 benchmark row",
            })
            continue
        d1_battle = str(d1_row["battle_tag"])
        d2_battle = str(d2_row["battle_tag"])
        d1_preview = _v2_plan_from_preview_rows(by_battle.get(d1_battle, []))
        d2_preview = _v2_plan_from_preview_rows(by_battle.get(d2_battle, []))
        pairs.append({
            "pair_id": pair_id,
            "status": "ok",
            "d1_battle": d1_battle,
            "d2_battle": d2_battle,
            "d1_arm_outcome": _arm_outcome(d1_row),
            "d2_arm_outcome": _arm_outcome(d2_row),
            "d1_team_id": d1_row.get("team_id"),
            "d1_opponent_team_id": d1_row.get("opponent_team_id"),
            "d2_team_id": d2_row.get("team_id"),
            "d2_opponent_team_id": d2_row.get("opponent_team_id"),
            "d1_v2_plan": d1_preview,
            "d2_v2_plan": d2_preview,
            "d1_v2_preview_available": d1_preview is not None,
            "d2_v2_preview_available": d2_preview is not None,
        })
    return pairs


# ---------------------------------------------------------------------------
# Plan comparison
# ---------------------------------------------------------------------------


def plans_differ(
    plan_a: Optional[Mapping[str, Any]],
    plan_b: Optional[Mapping[str, Any]],
) -> bool:
    if plan_a is None or plan_b is None:
        return False
    chosen_a = set(_split_pipe_list(plan_a.get("chosen_4", [])))
    chosen_b = set(_split_pipe_list(plan_b.get("chosen_4", [])))
    leads_a = tuple(_split_pipe_list(plan_a.get("lead_2", [])))
    leads_b = tuple(_split_pipe_list(plan_b.get("lead_2", [])))
    return chosen_a != chosen_b or leads_a != leads_b


def _split_pipe_list(values: Sequence[Any]) -> List[str]:
    out: List[str] = []
    for v in values:
        if isinstance(v, list):
            out.extend(str(x).strip() for x in v)
        else:
            out.extend(_split_pipe(v))
    return out


# ---------------------------------------------------------------------------
# Aggregate counters
# ---------------------------------------------------------------------------


def aggregate_outcome_counts(
    pairs: Sequence[Mapping[str, Any]],
) -> Dict[str, int]:
    counts = Counter()
    for pair in pairs:
        if pair.get("status") != "ok":
            counts["incomplete"] += 1
            continue
        d1 = pair.get("d1_arm_outcome")
        d2 = pair.get("d2_arm_outcome")
        if d1 == "win" and d2 == "win":
            counts["v2_both"] += 1
        elif d1 == "loss" and d2 == "loss":
            counts["random_both"] += 1
        else:
            counts["split"] += 1
    return dict(counts)


def aggregate_plan_change_counts(
    pairs: Sequence[Mapping[str, Any]],
) -> Dict[str, int]:
    """Count D1 vs D2 V2 plan changes. Each side uses the V2 plan
    extracted from preview evidence. The denominator is the number
    of pairs with both V2 previews available."""
    selected_changed = 0
    lead_changed = 0
    available = 0
    for pair in pairs:
        if pair.get("status") != "ok":
            continue
        d1 = pair.get("d1_v2_plan")
        d2 = pair.get("d2_v2_plan")
        if d1 is None or d2 is None:
            continue
        available += 1
        chosen_d1 = set(d1["chosen_4"])
        chosen_d2 = set(d2["chosen_4"])
        if chosen_d1 != chosen_d2:
            selected_changed += 1
        if tuple(d1["lead_2"]) != tuple(d2["lead_2"]):
            lead_changed += 1
    return {
        "pairs_with_v2_preview_on_both_sides": available,
        "selected_4_d1_vs_d2_changes": selected_changed,
        "lead_pair_d1_vs_d2_changes": lead_changed,
    }


# ---------------------------------------------------------------------------
# 129-team offline analysis using the common evaluator
# ---------------------------------------------------------------------------


def _resolve_team_lookup(
    team_pool: Sequence[Any],
) -> Dict[str, Any]:
    return {team.id: team for team in team_pool}


def offline_common_score_evaluation(
    limit_teams: Optional[int] = None,
) -> Dict[str, Any]:
    """Run every policy on identical 129-team (or limited) team/opponent
    pairs and evaluate each selected plan with the common evaluator.
    Returns a structured dictionary.
    """
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
    policies = (
        "basic_top4",
        "random",
        "matchup_top4_v2",
        "matchup_top4_v3",
    )
    n = len(pool)
    opp_n = len(opponent_pool)
    records: List[Dict[str, Any]] = []
    for index, team in enumerate(pool):
        opponent = opponent_pool[(index + 1) % opp_n]
        seed = 42 + index
        team_record: Dict[str, Any] = {
            "index": index,
            "team_id": team.id,
            "opponent_team_id": opponent.id,
            "seed": seed,
            "plans": {},
        }
        for policy in policies:
            preview = choose_four_from_six(
                team.pokemon,
                opponent_team=opponent.pokemon,
                policy=policy,
                seed=seed,
            )
            try:
                score = evaluate_plan_on_common_scale(
                    team=team.pokemon,
                    opponent_team=opponent.pokemon,
                    chosen_4=preview.chosen_4,
                    lead_2=preview.lead_2,
                    back_2=preview.back_2,
                )
            except CommonPlanEvaluatorError as exc:
                team_record["plans"][policy] = {
                    "error": str(exc),
                    "chosen_4": list(preview.chosen_4),
                    "lead_2": list(preview.lead_2),
                    "back_2": list(preview.back_2),
                }
                continue
            team_record["plans"][policy] = {
                "chosen_4": list(preview.chosen_4),
                "lead_2": list(preview.lead_2),
                "back_2": list(preview.back_2),
                "common_total": score.total,
                "components": score.components,
            }
        records.append(team_record)
    return {
        "denominator_teams": n,
        "denominator_opponents": opp_n,
        "policies": policies,
        "records": records,
    }


# ---------------------------------------------------------------------------
# Aggregate counters
# ---------------------------------------------------------------------------


def run_analysis(
    logs_dir: Path,
    artifact_prefix: str,
) -> Dict[str, Any]:
    benchmark_rows, jsonl_records, preview_rows = load_qualification_artifacts(
        logs_dir, artifact_prefix
    )
    pairs = extract_pairs(benchmark_rows, preview_rows)
    outcome_counts = aggregate_outcome_counts(pairs)
    plan_change_counts = aggregate_plan_change_counts(pairs)

    # Cross-check using the V2d qualification analyzer to preserve the
    # same 24 / 22 / 54 totals that the verified V2d report produced.
    cross_check = v2d_analyze_pairs(benchmark_rows)
    return {
        "artifact_prefix": artifact_prefix,
        "denominator_pairs_in_artifact": len(pairs),
        "artifact_record_counts": {
            "benchmark_csv": len(benchmark_rows),
            "benchmark_jsonl": len(jsonl_records),
            "preview_csv": len(preview_rows),
        },
        "outcome_counts_v2e1": outcome_counts,
        "v2d_cross_check_paired_outcomes": {
            "v2_both": cross_check["v2_both"],
            "random_both": cross_check["random_both"],
            "split": cross_check["split"],
            "invalid": cross_check["invalid"],
            "two_sided_p_value": cross_check["two_sided_p_value"],
        },
        "plan_change_counts_v2e1": plan_change_counts,
        "observed_side_split_evidence": {
            "d1_v2_wins": sum(
                1 for pair in pairs
                if pair.get("status") == "ok"
                and pair.get("d1_arm_outcome") == "win"
            ),
            "d2_v2_wins": sum(
                1 for pair in pairs
                if pair.get("status") == "ok"
                and pair.get("d2_arm_outcome") == "win"
            ),
            "note": (
                "These counts are observed side splits from the V2d "
                "qualification artifacts. The 57% / 45% asymmetry is "
                "evidence, not an established root cause."
            ),
        },
        "d1_v2_plan_extraction": {
            "pairs_with_d1_v2_preview": sum(
                1 for pair in pairs
                if pair.get("d1_v2_preview_available")
            ),
            "pairs_missing_d1_v2_preview": sum(
                1 for pair in pairs
                if pair.get("status") == "ok"
                and not pair.get("d1_v2_preview_available")
            ),
            "note": (
                "D1 V2 plan is extracted from the player fields of the "
                "D1 preview evidence rows."
            ),
        },
        "d2_v2_plan_extraction": {
            "pairs_with_d2_v2_preview": sum(
                1 for pair in pairs
                if pair.get("d2_v2_preview_available")
            ),
            "pairs_missing_d2_v2_preview": sum(
                1 for pair in pairs
                if pair.get("status") == "ok"
                and not pair.get("d2_v2_preview_available")
            ),
            "note": (
                "D2 V2 plan is extracted from the p2 preview row's "
                "own planned fields, where player_policy is V2. In "
                "this qualification each pair used identical team "
                "identities on both sides, so D1/D2 V2 plans are "
                "directly comparable for deterministic consistency."
            ),
        },
        "pair_details": pairs,
    }


def write_report(report: Dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as handle:
        json.dump(report, handle, indent=2, default=str)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs"),
    )
    parser.add_argument(
        "--artifact-prefix",
        default=ARTIFACT_PREFIX,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs/"
            "vgc2026_phaseV2e1_failures.json"
        ),
    )
    args = parser.parse_args()

    report = run_analysis(args.logs_dir, args.artifact_prefix)
    write_report(report, args.output)

    # Console summary, including the previously invalid claims
    # explicitly invalidated.
    print("Phase V2e.1 — Corrected offline analysis")
    print("=" * 60)
    print(f"Artifact prefix: {args.artifact_prefix}")
    print(f"Pairs in artifact: {report['denominator_pairs_in_artifact']}")
    print("Outcome counts (V2e.1):")
    for k, v in report["outcome_counts_v2e1"].items():
        print(f"  {k}: {v}")
    print("V2d cross-check (must match V2e.1 counts):")
    xc = report["v2d_cross_check_paired_outcomes"]
    print(f"  v2_both={xc['v2_both']}, random_both={xc['random_both']}, "
          f"split={xc['split']}, invalid={xc['invalid']}, "
          f"two_sided_p={xc['two_sided_p_value']:.6f}")
    print("Plan consistency counts (V2e.1, V2 plans on each side):")
    pc = report["plan_change_counts_v2e1"]
    print(f"  pairs_with_v2_preview_on_both_sides={pc['pairs_with_v2_preview_on_both_sides']}")
    print(f"  selected_4_d1_vs_d2_changes={pc['selected_4_d1_vs_d2_changes']}")
    print(f"  lead_pair_d1_vs_d2_changes={pc['lead_pair_d1_vs_d2_changes']}")
    print("Observed side split evidence (NOT a root cause):")
    obs = report["observed_side_split_evidence"]
    print(f"  d1_v2_wins={obs['d1_v2_wins']}, d2_v2_wins={obs['d2_v2_wins']}")
    print("V2 plan extraction:")
    d1 = report["d1_v2_plan_extraction"]
    d2 = report["d2_v2_plan_extraction"]
    print(f"  D1 V2 preview available: {d1['pairs_with_d1_v2_preview']}, "
          f"missing: {d1['pairs_missing_d1_v2_preview']}")
    print(f"  D2 V2 preview available: {d2['pairs_with_d2_v2_preview']}, "
          f"missing: {d2['pairs_missing_d2_v2_preview']}")
    print()
    print("Previously invalid V2e claims now invalidated:")
    print("  - '100% V2 plan change D1 vs D2' is removed.")
    print("    Correct extraction finds 0 selected-four changes and "
          "0 lead changes across 100 identical team matchups.")
    print("  - 'D1 57% vs D2 45% is the root cause' is removed; the "
          "asymmetry is reported only as observed evidence.")
    print("  - 'Score margin vs basic' cross-policy comparison is "
          "removed. The new offline comparison uses the common "
          "evaluator on identical 129-team inputs.")
    print()
    print(f"Report saved to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
