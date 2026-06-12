#!/usr/bin/env python3
"""
VGC 2026 Phase V2g — Diagnose V3 battle failures.

Methodology:
- Merge D1/D2 by pair_id (never row position).
- Normalize every outcome from the V3 perspective.
- Extract V3 plans only from rows whose `player_policy ==
  "matchup_top4_v3"`. `opponent_policy` is metadata only.
- Reconstruct each V3 and Random preview plan from the preview
  evidence and re-evaluate it under the policy-independent
  common plan evaluator plus the new feature bundle.
- Compare outcome groups: V3-both vs Random-both, V3 wins vs V3
  losses, D1 vs D2, and the winning plan vs losing plan inside
  each split pair.
- Report mean, median, min, p10, p90 and denominators.
- Never assert battle causality from preview metadata alone.

The team details used to evaluate plans are loaded from the same
129-team pool the qualification ran against. This is necessary to
read open team-sheet data (moves, ability, types) and is not
optimization against battle outcomes.
"""

import argparse
import csv
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import sys

sys.path.insert(0, "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai")

from analyze_vgc2026_phaseV2f_qualification import (
    paired_sign_test as v2f_paired_sign_test,
    exact_binomial_p_value as v2f_exact_binomial_p_value,
    wilson_interval as v2f_wilson_interval,
)
from team_preview_policy import (
    SPECIES_TYPES,
    calculate_type_matchup,
    calculate_weakness_avoidance,
    get_ability_category,
    get_move_category,
    get_species_types,
)
from vgc2026_common_plan_evaluator import (
    CommonPlanEvaluatorError,
    evaluate_plan_on_common_scale,
)
from vgc2026_plan_features import (
    PlanFeatures,
    aggregate_features,
    extract_plan_features,
    shannon_entropy_from_counts,
)
from vgc_team_pool import load_vgc_pool


# ---------------------------------------------------------------------------
# Statistics helpers (re-use the V2f ones for exact behaviour)
# ---------------------------------------------------------------------------


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


# ---------------------------------------------------------------------------
# Artifact loading
# ---------------------------------------------------------------------------


def _split_pipe_species(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split("|") if part.strip()]


def _normalize_species(species: str) -> str:
    return str(species).strip().lower().replace(" ", "").replace(
        "-", ""
    ).replace("[", "").replace("]", "")


def load_v2f_artifacts(
    logs_dir: Path,
    artifact_prefix: str,
) -> Tuple[
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    Dict[str, Dict[str, Any]],
]:
    """Load benchmark CSV, preview CSV, and a team_id -> team lookup."""
    csv_path = logs_dir / f"{artifact_prefix}_benchmark.csv"
    preview_path = logs_dir / f"{artifact_prefix}_preview_evidence.csv"
    with csv_path.open(newline="") as handle:
        benchmark_rows = list(csv.DictReader(handle))
    with preview_path.open(newline="") as handle:
        preview_rows = list(csv.DictReader(handle))

    pool = list(
        load_vgc_pool(
            max_rank=None, parse_status="any", limit=None, seed=42
        )
    )
    team_lookup: Dict[str, Dict[str, Any]] = {}
    for team in pool:
        if not team_lookup.get(team.id):
            team_lookup[team.id] = {
                "id": team.id,
                "rank": team.rank,
                "player": team.player,
                "pokemon": list(team.pokemon),
            }
    return benchmark_rows, preview_rows, team_lookup


# ---------------------------------------------------------------------------
# Plan extraction
# ---------------------------------------------------------------------------


def _v3_plan_from_preview(
    preview_rows: Sequence[Mapping[str, Any]],
    battle_tag: str,
) -> Optional[Dict[str, Any]]:
    """V3 plan ownership is keyed ONLY on player_policy. The
    opponent_policy field is metadata and never selects the owner."""
    for row in preview_rows:
        if row.get("battle_tag") != battle_tag:
            continue
        if row.get("player_policy") != "matchup_top4_v3":
            continue
        chosen = _split_pipe_species(row.get("planned_chosen_4"))
        leads = _split_pipe_species(row.get("planned_lead_2"))
        backs = _split_pipe_species(row.get("planned_back_2"))
        if not (chosen and leads and backs):
            continue
        return {
            "chosen_4": chosen,
            "lead_2": leads,
            "back_2": backs,
            "side": row.get("side"),
            "source_player_policy": row.get("player_policy"),
        }
    return None


def _random_plan_from_preview(
    preview_rows: Sequence[Mapping[str, Any]],
    battle_tag: str,
) -> Optional[Dict[str, Any]]:
    for row in preview_rows:
        if row.get("battle_tag") != battle_tag:
            continue
        if row.get("player_policy") != "random":
            continue
        chosen = _split_pipe_species(row.get("planned_chosen_4"))
        leads = _split_pipe_species(row.get("planned_lead_2"))
        backs = _split_pipe_species(row.get("planned_back_2"))
        if not (chosen and leads and backs):
            continue
        return {
            "chosen_4": chosen,
            "lead_2": leads,
            "back_2": backs,
            "side": row.get("side"),
            "source_player_policy": row.get("player_policy"),
        }
    return None


# ---------------------------------------------------------------------------
# Pair construction
# ---------------------------------------------------------------------------


def build_pair_records(
    benchmark_rows: Sequence[Mapping[str, Any]],
    preview_rows: Sequence[Mapping[str, Any]],
    team_lookup: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    by_pair: Dict[int, Dict[str, Mapping[str, Any]]] = {}
    for row in benchmark_rows:
        pair_id = int(row["pair_id"])
        arm = str(row["battle_tag"]).split("_", 1)[0]
        by_pair.setdefault(pair_id, {})[arm] = row

    records: List[Dict[str, Any]] = []
    for pair_id in sorted(by_pair):
        arms = by_pair[pair_id]
        d1 = arms.get("D1")
        d2 = arms.get("D2")
        record: Dict[str, Any] = {
            "pair_id": pair_id,
            "d1_battle": d1["battle_tag"] if d1 else None,
            "d2_battle": d2["battle_tag"] if d2 else None,
            "d1_outcome": (
                "win" if d1 and _parse_bool(d1.get("our_win"))
                else "loss" if d1 and _parse_bool(d1.get("our_win")) is False
                else "invalid"
            ) if d1 else "invalid",
            "d2_outcome": (
                "win" if d2 and _parse_bool(d2.get("opponent_win"))
                else "loss" if d2 and _parse_bool(d2.get("opponent_win")) is False
                else "invalid"
            ) if d2 else "invalid",
            "d1_team_id": d1.get("team_id") if d1 else None,
            "d1_opp_team_id": d1.get("opponent_team_id") if d1 else None,
            "d2_team_id": d2.get("team_id") if d2 else None,
            "d2_opp_team_id": d2.get("opponent_team_id") if d2 else None,
            "d1_v3_plan": None,
            "d2_v3_plan": None,
            "d1_random_plan": None,
            "d2_random_plan": None,
            "status": "ok",
        }
        if d1:
            record["d1_v3_plan"] = _v3_plan_from_preview(
                preview_rows, d1["battle_tag"]
            )
            record["d1_random_plan"] = _random_plan_from_preview(
                preview_rows, d1["battle_tag"]
            )
        if d2:
            record["d2_v3_plan"] = _v3_plan_from_preview(
                preview_rows, d2["battle_tag"]
            )
            record["d2_random_plan"] = _random_plan_from_preview(
                preview_rows, d2["battle_tag"]
            )
        record["v3_plans_match"] = (
            record["d1_v3_plan"] is not None
            and record["d2_v3_plan"] is not None
            and record["d1_v3_plan"]["chosen_4"]
            == record["d2_v3_plan"]["chosen_4"]
            and record["d1_v3_plan"]["lead_2"]
            == record["d2_v3_plan"]["lead_2"]
            and record["d1_v3_plan"]["back_2"]
            == record["d2_v3_plan"]["back_2"]
        )
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# Pair classification (decisive vs split)
# ---------------------------------------------------------------------------


def classify_pair(record: Mapping[str, Any]) -> str:
    d1 = record.get("d1_outcome")
    d2 = record.get("d2_outcome")
    if d1 == "win" and d2 == "win":
        return "v3_both"
    if d1 == "loss" and d2 == "loss":
        return "random_both"
    if d1 in {"win", "loss"} and d2 in {"win", "loss"}:
        return "split"
    return "invalid"


# ---------------------------------------------------------------------------
# Feature extraction for each plan
# ---------------------------------------------------------------------------


def _safe_extract(
    team_lookup: Mapping[str, Mapping[str, Any]],
    team_id: Optional[str],
) -> Optional[List[Mapping[str, Any]]]:
    if team_id is None:
        return None
    entry = team_lookup.get(team_id)
    if entry is None:
        return None
    return entry.get("pokemon")


def extract_plan_bundle(
    team_lookup: Mapping[str, Mapping[str, Any]],
    team_id: Optional[str],
    opponent_team_id: Optional[str],
    plan: Optional[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Compute the common-evaluator + plan-features bundle for one plan."""
    if plan is None:
        return None
    team = _safe_extract(team_lookup, team_id)
    opp_team = _safe_extract(team_lookup, opponent_team_id)
    if team is None or opp_team is None:
        return None
    chosen = plan["chosen_4"]
    leads = plan["lead_2"]
    backs = plan["back_2"]
    try:
        common = evaluate_plan_on_common_scale(
            team=team,
            opponent_team=opp_team,
            chosen_4=chosen,
            lead_2=leads,
            back_2=backs,
        )
        features = extract_plan_features(
            team=team,
            opponent_team=opp_team,
            chosen_4=chosen,
            lead_2=leads,
            back_2=backs,
        )
    except (CommonPlanEvaluatorError, KeyError, ValueError) as exc:
        return {"error": str(exc), "chosen_4": chosen, "lead_2": leads, "back_2": backs}
    return {
        "common_total": common.total,
        "components": dict(common.components),
        "features": dict(features.features),
        "categorical": dict(features.categorical),
        "chosen_4": list(common.chosen_4),
        "lead_2": list(common.lead_2),
        "back_2": list(common.back_2),
    }


# ---------------------------------------------------------------------------
# Aggregate analysis
# ---------------------------------------------------------------------------


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarise_features(
    bundles: Sequence[Mapping[str, Any]],
    feature_keys: Sequence[str],
) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for key in feature_keys:
        values: List[float] = []
        for bundle in bundles:
            if "error" in bundle:
                continue
            value = bundle.get("features", {}).get(key)
            if value is None:
                value = bundle.get("components", {}).get(key)
            if value is None:
                continue
            values.append(float(value))
        if not values:
            out[key] = {
                "n": 0, "mean": 0.0, "median": 0.0,
                "min": 0.0, "p10": 0.0, "p90": 0.0, "max": 0.0,
            }
            continue
        out[key] = {
            "n": len(values),
            "mean": statistics.fmean(values),
            "median": statistics.median(values),
            "min": min(values),
            "p10": percentile(values, 0.10),
            "p90": percentile(values, 0.90),
            "max": max(values),
        }
    return out


def shared_feature_keys(
    bundles: Sequence[Mapping[str, Any]],
) -> Tuple[List[str], List[str]]:
    common_keys: List[str] = []
    feature_keys: List[str] = []
    for bundle in bundles[:1]:
        if "error" in bundle:
            continue
        common_keys = list(bundle.get("components", {}).keys())
        feature_keys = list(bundle.get("features", {}).keys())
    return common_keys, feature_keys


# ---------------------------------------------------------------------------
# Side collapse
# ---------------------------------------------------------------------------


def d1_d2_winrates(
    pairs: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    d1_wins = 0
    d1_total = 0
    d2_wins = 0
    d2_total = 0
    for pair in pairs:
        outcome = classify_pair(pair)
        if outcome == "invalid":
            continue
        if pair.get("d1_outcome") == "win":
            d1_wins += 1
        if pair.get("d1_outcome") in {"win", "loss"}:
            d1_total += 1
        if pair.get("d2_outcome") == "win":
            d2_wins += 1
        if pair.get("d2_outcome") in {"win", "loss"}:
            d2_total += 1
    return {
        "d1_v3_wins": d1_wins,
        "d1_total": d1_total,
        "d1_v3_win_rate": d1_wins / d1_total if d1_total else 0.0,
        "d2_v3_wins": d2_wins,
        "d2_total": d2_total,
        "d2_v3_win_rate": d2_wins / d2_total if d2_total else 0.0,
    }


# ---------------------------------------------------------------------------
# Random-both failure pair drill-down
# ---------------------------------------------------------------------------


def failure_pair_features(
    pairs: Sequence[Mapping[str, Any]],
    bundles_by_pair: Sequence[Tuple[int, Dict[str, Dict[str, Any]]]],
) -> Dict[str, Any]:
    """Per-feature comparison on the 25 Random-both failure pairs.

    For each failure pair we collect:
        - V3 plan features (the plan V3 chose)
        - Random plan features (the plan Random chose)
    The V3 plan in these pairs is the battle-time loss plan. The
    Random plan is the winning plan V3 failed to find.
    """
    pairs_by_id = {p["pair_id"]: p for p in pairs}
    failure_pairs = [
        p for p in pairs if classify_pair(p) == "random_both"
    ]
    bundles_by_pair_dict = dict(bundles_by_pair)

    v3_bundles = []
    rand_bundles = []
    for pair in failure_pairs:
        pair_id = pair["pair_id"]
        bundles = bundles_by_pair_dict.get(pair_id, {})
        v3_bundle = bundles.get("v3")
        rand_bundle = bundles.get("random")
        if v3_bundle and "error" not in v3_bundle:
            v3_bundles.append(v3_bundle)
        if rand_bundle and "error" not in rand_bundle:
            rand_bundles.append(rand_bundle)

    common_keys, feature_keys = shared_feature_keys(v3_bundles)
    v3_summary = summarise_features(v3_bundles, common_keys + feature_keys)
    rand_summary = summarise_features(rand_bundles, common_keys + feature_keys)
    deltas: Dict[str, float] = {}
    for key in common_keys + feature_keys:
        v3_mean = v3_summary[key]["mean"]
        rand_mean = rand_summary[key]["mean"]
        deltas[key] = v3_mean - rand_mean
    return {
        "n_failure_pairs": len(failure_pairs),
        "v3_features": v3_summary,
        "random_features": rand_summary,
        "v3_minus_random_mean_delta": deltas,
    }


# ---------------------------------------------------------------------------
# Aggregate all pairs
# ---------------------------------------------------------------------------


def aggregate(
    pairs: Sequence[Mapping[str, Any]],
    bundles_by_pair: Sequence[Tuple[int, Dict[str, Dict[str, Any]]]],
) -> Dict[str, Any]:
    bundles_by_pair_dict = dict(bundles_by_pair)

    def _safe(pair: Mapping[str, Any], plan_key: str) -> Optional[Mapping[str, Any]]:
        pair_id = pair["pair_id"]
        bundles = bundles_by_pair_dict.get(pair_id, {})
        return bundles.get(plan_key)

    v3_both_v3 = [
        bundles_by_pair_dict[p["pair_id"]]["v3"]
        for p in pairs
        if classify_pair(p) == "v3_both"
        and bundles_by_pair_dict.get(p["pair_id"], {}).get("v3")
        and "error" not in bundles_by_pair_dict[p["pair_id"]]["v3"]
    ]
    random_both_v3 = [
        bundles_by_pair_dict[p["pair_id"]]["v3"]
        for p in pairs
        if classify_pair(p) == "random_both"
        and bundles_by_pair_dict.get(p["pair_id"], {}).get("v3")
        and "error" not in bundles_by_pair_dict[p["pair_id"]]["v3"]
    ]
    split_v3 = [
        bundles_by_pair_dict[p["pair_id"]]["v3"]
        for p in pairs
        if classify_pair(p) == "split"
        and bundles_by_pair_dict.get(p["pair_id"], {}).get("v3")
        and "error" not in bundles_by_pair_dict[p["pair_id"]]["v3"]
    ]
    d1_v3 = [
        bundles_by_pair_dict[p["pair_id"]]["v3"]
        for p in pairs
        if p.get("d1_outcome") == "win"
        and bundles_by_pair_dict.get(p["pair_id"], {}).get("v3")
        and "error" not in bundles_by_pair_dict[p["pair_id"]]["v3"]
    ]
    d2_v3 = [
        bundles_by_pair_dict[p["pair_id"]]["v3"]
        for p in pairs
        if p.get("d2_outcome") == "win"
        and bundles_by_pair_dict.get(p["pair_id"], {}).get("v3")
        and "error" not in bundles_by_pair_dict[p["pair_id"]]["v3"]
    ]
    v3_wins = d1_v3 + d2_v3
    v3_losses = [
        bundles_by_pair_dict[p["pair_id"]]["v3"]
        for p in pairs
        if (p.get("d1_outcome") == "loss" or p.get("d2_outcome") == "loss")
        and bundles_by_pair_dict.get(p["pair_id"], {}).get("v3")
        and "error" not in bundles_by_pair_dict[p["pair_id"]]["v3"]
    ]
    # Battle-level V3 wins: same plan emitted on D1 and D2; both
    # outcomes are wins when the pair is v3_both, but per battle we
    # look at the per-arm outcome.
    v3_win_bundles: List[Mapping[str, Any]] = []
    v3_loss_bundles: List[Mapping[str, Any]] = []
    for pair in pairs:
        pair_id = pair["pair_id"]
        bundles = bundles_by_pair_dict.get(pair_id, {})
        v3_bundle = bundles.get("v3")
        if not v3_bundle or "error" in v3_bundle:
            continue
        if pair.get("d1_outcome") == "win":
            v3_win_bundles.append(v3_bundle)
        elif pair.get("d1_outcome") == "loss":
            v3_loss_bundles.append(v3_bundle)
        if pair.get("d2_outcome") == "win":
            v3_win_bundles.append(v3_bundle)
        elif pair.get("d2_outcome") == "loss":
            v3_loss_bundles.append(v3_bundle)

    common_keys, feature_keys = shared_feature_keys(
        v3_wins or v3_losses
    )
    summary: Dict[str, Any] = {}
    all_keys = common_keys + feature_keys
    summary["v3_both_pairs"] = summarise_features(v3_both_v3, all_keys)
    summary["random_both_pairs"] = summarise_features(random_both_v3, all_keys)
    summary["split_pairs"] = summarise_features(split_v3, all_keys)
    summary["d1_v3_wins"] = summarise_features(d1_v3, all_keys)
    summary["d2_v3_wins"] = summarise_features(d2_v3, all_keys)
    summary["v3_battle_wins"] = summarise_features(v3_win_bundles, all_keys)
    summary["v3_battle_losses"] = summarise_features(v3_loss_bundles, all_keys)
    summary["failure_pair_drill_down"] = failure_pair_features(
        pairs, bundles_by_pair
    )
    return summary


# ---------------------------------------------------------------------------
# Sign-test re-verification (decisive-only)
# ---------------------------------------------------------------------------


def sign_test(pairs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Paired sign test on the 55 decisive pairs (30 V3-both, 25
    Random-both). Splits are EXCLUDED from the directional test.

    Verifies the corrected p-values:
        two-sided p = 0.590053
        one-sided p  = 0.295027
    """
    v3_both = 0
    random_both = 0
    split = 0
    for pair in pairs:
        outcome = classify_pair(pair)
        if outcome == "v3_both":
            v3_both += 1
        elif outcome == "random_both":
            random_both += 1
        elif outcome == "split":
            split += 1
    n = v3_both + random_both
    two_sided = v2f_exact_binomial_p_value(v3_both, n)
    one_sided = v2f_exact_binomial_p_value(
        v3_both, n, alternative="greater"
    )
    return {
        "v3_both": v3_both,
        "random_both": random_both,
        "split": split,
        "decisive_n": n,
        "two_sided_p": two_sided,
        "one_sided_p": one_sided,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def build_bundles_by_pair(
    pairs: Sequence[Mapping[str, Any]],
    team_lookup: Mapping[str, Mapping[str, Any]],
) -> List[Tuple[int, Dict[str, Dict[str, Any]]]]:
    out: List[Tuple[int, Dict[str, Dict[str, Any]]]] = []
    for pair in pairs:
        if pair.get("status") != "ok":
            out.append((pair["pair_id"], {}))
            continue
        d1_bundle = extract_plan_bundle(
            team_lookup,
            pair.get("d1_team_id"),
            pair.get("d1_opp_team_id"),
            pair.get("d1_v3_plan"),
        )
        d2_bundle = extract_plan_bundle(
            team_lookup,
            pair.get("d2_team_id"),
            pair.get("d2_opp_team_id"),
            pair.get("d2_v3_plan"),
        )
        d1_random_bundle = extract_plan_bundle(
            team_lookup,
            pair.get("d1_team_id"),
            pair.get("d1_opp_team_id"),
            pair.get("d1_random_plan"),
        )
        d2_random_bundle = extract_plan_bundle(
            team_lookup,
            pair.get("d2_team_id"),
            pair.get("d2_opp_team_id"),
            pair.get("d2_random_plan"),
        )
        # For the V3 bundle we use the deterministic D1 plan (it
        # matches the D2 plan for 100/100 pairs in V2f).
        v3_bundle = d1_bundle
        # The Random bundle is the battle-time Random plan, again
        # taken from D1 (D2's Random is the mirrored plan for the
        # same seed schedule).
        random_bundle = d1_random_bundle
        out.append((
            pair["pair_id"],
            {
                "v3": v3_bundle,
                "random": random_bundle,
                "d1_v3": d1_bundle,
                "d2_v3": d2_bundle,
                "d1_random": d1_random_bundle,
                "d2_random": d2_random_bundle,
            },
        ))
    return out


def run_analysis(
    logs_dir: Path,
    artifact_prefix: str,
) -> Dict[str, Any]:
    benchmark_rows, preview_rows, team_lookup = load_v2f_artifacts(
        logs_dir, artifact_prefix
    )
    pairs = build_pair_records(
        benchmark_rows, preview_rows, team_lookup
    )
    bundles_by_pair = build_bundles_by_pair(pairs, team_lookup)

    classification_counts = Counter()
    for pair in pairs:
        classification_counts[classify_pair(pair)] += 1

    sign_test_stats = sign_test(pairs)
    side_stats = d1_d2_winrates(pairs)
    feature_summary = aggregate(pairs, bundles_by_pair)

    return {
        "artifact_prefix": artifact_prefix,
        "row_counts": {
            "benchmark_csv": len(benchmark_rows),
            "preview_csv": len(preview_rows),
        },
        "team_pool_size": len(team_lookup),
        "total_pairs": len(pairs),
        "classification_counts": dict(classification_counts),
        "sign_test": sign_test_stats,
        "side_stats": side_stats,
        "feature_summary": feature_summary,
        "pairs": pairs,
        "bundles_by_pair": [
            {"pair_id": pair_id, "bundles": bundles}
            for pair_id, bundles in bundles_by_pair
        ],
    }


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
        "--output",
        type=Path,
        default=Path(
            "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs/"
            "vgc2026_phaseV2g_failures.json"
        ),
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path(
            "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs/"
            "vgc2026_phaseV2g_failures.md"
        ),
    )
    args = parser.parse_args()

    report = run_analysis(args.logs_dir, args.artifact_prefix)

    output = {
        "artifact_prefix": report["artifact_prefix"],
        "row_counts": report["row_counts"],
        "team_pool_size": report["team_pool_size"],
        "total_pairs": report["total_pairs"],
        "classification_counts": report["classification_counts"],
        "sign_test": report["sign_test"],
        "side_stats": report["side_stats"],
        "feature_summary": report["feature_summary"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, default=str))
    markdown = render_markdown(report)
    args.markdown.write_text(markdown)
    print(markdown)
    print(f"JSON: {args.output}")
    print(f"Markdown: {args.markdown}")
    return 0


def render_markdown(report: Mapping[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Phase V2g — V3 Battle Failure Diagnosis")
    lines.append("")
    lines.append(f"Artifact tag: `{report['artifact_prefix']}`")
    lines.append("")
    lines.append("## Pair classification (decisive-only sign test)")
    lines.append("")
    counts = report["classification_counts"]
    lines.append(
        f"V3-both: **{counts.get('v3_both', 0)}** | "
        f"Random-both: **{counts.get('random_both', 0)}** | "
        f"Split: **{counts.get('split', 0)}** | "
        f"Invalid: {counts.get('invalid', 0)}"
    )
    lines.append("")
    st = report["sign_test"]
    lines.append(
        f"Decisive paired trials (V3-both + Random-both): "
        f"**{st['decisive_n']}**"
    )
    lines.append(
        f"Two-sided exact p: **{st['two_sided_p']:.6f}**"
    )
    lines.append(
        f"One-sided V3 p: **{st['one_sided_p']:.6f}**"
    )
    lines.append("")
    side = report["side_stats"]
    lines.append("## Side collapse observation")
    lines.append("")
    lines.append(
        f"D1 V3 win rate: {side['d1_v3_wins']}/{side['d1_total']} = "
        f"{side['d1_v3_win_rate']:.1%}"
    )
    lines.append(
        f"D2 V3 win rate: {side['d2_v3_wins']}/{side['d2_total']} = "
        f"{side['d2_v3_win_rate']:.1%}"
    )
    lines.append("")
    lines.append(
        "This is **observed evidence only** — it is not a causal claim."
    )
    lines.append("")
    fs = report["feature_summary"]
    if "v3_battle_wins" in fs and fs["v3_battle_wins"]:
        lines.append("## V3 battle wins versus V3 battle losses")
        lines.append("")
        lines.append("Per-feature mean comparison (battle-level, "
                    "denominator varies by group):")
        lines.append("")
        lines.append(
            "D1 and D2 reuse the same deterministic V3 preview plan "
            "for each pair. These 200 battle rows are therefore "
            "descriptive repeated observations, not 200 independent "
            "plan samples."
        )
        lines.append("")
        lines.append("| Feature | Wins mean | Losses mean | Delta |")
        lines.append("|---|---:|---:|---:|")
        keys = list(fs["v3_battle_wins"].keys())
        for key in keys:
            w = fs["v3_battle_wins"][key]
            l = fs["v3_battle_losses"][key]
            delta = w["mean"] - l["mean"]
            lines.append(
                f"| {key} | {w['mean']:.3f} (n={w['n']}) | "
                f"{l['mean']:.3f} (n={l['n']}) | {delta:+.3f} |"
            )
        lines.append("")
    if "failure_pair_drill_down" in fs:
        fd = fs["failure_pair_drill_down"]
        lines.append("## Failure-pair drill-down (Random-both, 25 pairs)")
        lines.append("")
        lines.append(
            f"Number of failure pairs: {fd['n_failure_pairs']}"
        )
        lines.append("")
        lines.append("Mean per feature on the 25 loss-side V3 plans "
                    "versus the winning Random plans:")
        lines.append("")
        lines.append(
            "| Feature | V3 mean | Random mean | Delta |"
        )
        lines.append("|---|---:|---:|---:|")
        v3 = fd["v3_features"]
        rn = fd["random_features"]
        deltas = fd["v3_minus_random_mean_delta"]
        for key in v3.keys():
            lines.append(
                f"| {key} | {v3[key]['mean']:.3f} | "
                f"{rn[key]['mean']:.3f} | {deltas[key]:+.3f} |"
            )
        lines.append("")
    lines.append("## V3-both vs Random-both (V3 plan features)")
    lines.append("")
    if "v3_both_pairs" in fs:
        v3b = fs["v3_both_pairs"]
        rb = fs["random_both_pairs"]
        lines.append("| Feature | V3-both | Random-both |")
        lines.append("|---|---:|---:|")
        for key in v3b.keys():
            lines.append(
                f"| {key} | {v3b[key]['mean']:.3f} | "
                f"{rb[key]['mean']:.3f} |"
            )
        lines.append("")
    lines.append("## Split-pair V3 plans (45 pairs)")
    lines.append("")
    if "split_pairs" in fs:
        sp = fs["split_pairs"]
        lines.append("Number of split pairs with successful V3 plan "
                    "extraction: "
                    f"{sp.get('common_total', {}).get('n', 0)}")
        lines.append("")
        lines.append(
            "Split pairs are excluded from the directional sign test "
            "because each side picked a different winner."
        )
        lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
