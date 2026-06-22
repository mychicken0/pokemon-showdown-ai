#!/usr/bin/env python3
"""Phase RL-2 — Read-Only Team-Preview Dataset Quality Analyzer.

Aggregates quality metrics for team-preview / V3c dataset
and qualification artifacts. Read-only: no training, no
battles, no policy changes.

Inputs (any subset, at least one required):
  - --csv  : paired battle CSV
  - --jsonl: paired battle JSONL
  - --model: V3c.1 model JSON

Outputs:
  - Markdown report (--md, required)
  - Optional JSON summary (--json)
"""
import argparse
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple


# Hidden-info / non-observable feature name patterns.
# V3c.1 features are all observable (species, ability, moves,
# types from open team-sheet). This set is a safety net for
# future features.
_HIDDEN_INFO_PATTERNS = [
    "hidden",
    "secret",
    "internal",
    "private",
    "unknown_move",
    "opp_item",
    "opp_ability_unknown",
    "future_turn",
    "outcome",
    "won",
    "win",
    "score",
]


def _load_csv(path: str) -> Tuple[List[Dict[str, Any]], int, int]:
    """Load a paired battle CSV. Returns (rows, parse_errors, total_lines)."""
    rows: List[Dict[str, Any]] = []
    parse_errors = 0
    total = 0
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            rows.append(row)
    return rows, parse_errors, total


def _load_jsonl(path: str) -> Tuple[List[Dict[str, Any]], int, int]:
    """Load a paired battle JSONL. Returns (rows, parse_errors, total_lines)."""
    rows: List[Dict[str, Any]] = []
    parse_errors = 0
    total = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                parse_errors += 1
    return rows, parse_errors, total


def _load_model(path: str) -> Optional[Dict[str, Any]]:
    """Load a V3c.1 model JSON."""
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _entropy_from_counts(counts: Counter) -> float:
    """Shannon entropy in nats from a Counter."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    h = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            h -= p * math.log(p)
    return h


def _wilson_ci(s: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson 95% CI for a proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = s / n
    denom = 1 + (z ** 2) / n
    center = (p + (z ** 2) / (2 * n)) / denom
    half = (z / denom) * math.sqrt(
        p * (1 - p) / n + (z ** 2) / (4 * n ** 2)
    )
    return (max(0.0, center - half), min(1.0, center + half))


def _bootstrap_ci(
    values: List[float], n_boot: int = 1000, seed: int = 42,
) -> Tuple[float, float, float]:
    """Paired bootstrap CI for the mean. Returns (mean, lo, hi)."""
    import random
    if not values:
        return (0.0, 0.0, 0.0)
    random.seed(seed)
    n = len(values)
    mean = sum(values) / n
    boot_means = []
    for _ in range(n_boot):
        sample = [values[random.randrange(n)] for _ in range(n)]
        boot_means.append(sum(sample) / n)
    boot_means.sort()
    lo = boot_means[int(0.025 * n_boot)]
    hi = boot_means[int(0.975 * n_boot)]
    return (mean, lo, hi)


def _aggregate(
    csv_rows: List[Dict[str, Any]],
    jsonl_rows: List[Dict[str, Any]],
    model: Optional[Dict[str, Any]],
    csv_path: Optional[str],
    jsonl_path: Optional[str],
    model_path: Optional[str],
) -> Dict[str, Any]:
    """Aggregate all metrics."""
    data_quality = {
        "csv_path": csv_path,
        "jsonl_path": jsonl_path,
        "model_path": model_path,
        "csv_rows": len(csv_rows),
        "jsonl_rows": len(jsonl_rows),
        "csv_status_counts": {},
        "jsonl_status_counts": {},
        "timeout_count": 0,
        "error_count": 0,
        "no_battle_count": 0,
    }
    pair_integrity = {
        "total_rows": 0,
        "complete_pairs": 0,
        "missing_d1_count": 0,
        "missing_d2_count": 0,
        "valid_pairs": 0,
        "perspective_invalid_rows": 0,
        "side_balance": {},
        "duplicate_pair_ids": 0,
        "duplicate_battle_tags": 0,
    }
    preview_plan_quality = {
        "preview_validation_rate": 0.0,
        "unique_selected_4": 0,
        "unique_lead_2": 0,
        "unique_back_2": 0,
        "selected_4_entropy": 0.0,
        "plan_change_rate": None,
    }
    outcome_quality = {
        "learned_wins": 0,
        "baseline_wins": 0,
        "total_decisive_pairs": 0,
        "learned_both": 0,
        "baseline_both": 0,
        "split": 0,
        "treatment_effect": None,
        "wilson_lo": None,
        "wilson_hi": None,
        "bootstrap_lo": None,
        "bootstrap_hi": None,
    }
    leakage_risk = {
        "duplicate_team_hashes": 0,
        "duplicate_selected_4_rows": 0,
        "non_observable_feature_names": [],
    }
    feature_model_quality = {
        "feature_count": 0,
        "nonzero_weight_count": 0,
        "top_positive_weights": [],
        "top_negative_weights": [],
        "weight_magnitude_max": 0.0,
        "weight_magnitude_mean": 0.0,
        "bias": None,
        "feature_family_counts": {},
        "suspicious_feature_names": [],
    }
    rl_readiness = {
        "state_availability": "unknown",
        "action_availability": "unknown",
        "reward_availability": "unknown",
        "episode_boundary_availability": "unknown",
        "opponent_action_availability": "unknown",
        "counterfactual_availability": "unknown",
        "volume_adequacy": "unknown",
        "recommendation": "unknown",
    }
    recommendations: List[str] = []

    # CSV analysis
    for row in csv_rows:
        status = row.get("status", "")
        data_quality["csv_status_counts"][status] = (
            data_quality["csv_status_counts"].get(status, 0) + 1
        )
        if status == "timeout":
            data_quality["timeout_count"] += 1
        elif status == "error":
            data_quality["error_count"] += 1
        elif status == "no_battle":
            data_quality["no_battle_count"] += 1

    # JSONL analysis
    for row in jsonl_rows:
        status = row.get("status", "")
        data_quality["jsonl_status_counts"][status] = (
            data_quality["jsonl_status_counts"].get(status, 0) + 1
        )
        if status == "timeout":
            data_quality["timeout_count"] += 1
        elif status == "error":
            data_quality["error_count"] += 1
        elif status == "no_battle":
            data_quality["no_battle_count"] += 1

    # Combine rows for pair analysis (prefer JSONL if both present)
    all_rows = jsonl_rows if jsonl_rows else csv_rows
    pair_integrity["total_rows"] = len(all_rows)

    # Side balance
    side_count: Counter = Counter()
    for row in all_rows:
        side = row.get("side", "")
        side_count[side] += 1
    pair_integrity["side_balance"] = dict(side_count)

    # Pair integrity
    pairs = defaultdict(dict)
    battle_tags: List[str] = []
    for row in all_rows:
        pid = row.get("pair_id")
        side = row.get("side", "")
        if pid is not None and side:
            pairs[pid][side] = row
        bt = row.get("battle_tag", "")
        if bt:
            battle_tags.append(bt)

    for pid, sides in pairs.items():
        if "p1" in sides and "p2" in sides:
            pair_integrity["complete_pairs"] += 1
            r1 = sides["p1"]
            r2 = sides["p2"]
            # Valid if both ok and not perspective invalid.
            if r1.get("status") == "ok" and r2.get("status") == "ok":
                pair_integrity["valid_pairs"] += 1
        else:
            if "p1" not in sides:
                pair_integrity["missing_d1_count"] += 1
            if "p2" not in sides:
                pair_integrity["missing_d2_count"] += 1

    # Duplicate detection
    pair_ids = [r.get("pair_id") for r in all_rows if r.get("pair_id") is not None]
    pair_id_counts = Counter(pair_ids)
    pair_integrity["duplicate_pair_ids"] = sum(
        c - 1 for c in pair_id_counts.values() if c > 1
    )
    bt_counts = Counter(battle_tags)
    pair_integrity["duplicate_battle_tags"] = sum(
        c - 1 for c in bt_counts.values() if c > 1
    )

    # Preview plan quality
    selected_4_counts: Counter = Counter()
    lead_2_counts: Counter = Counter()
    back_2_counts: Counter = Counter()
    ok_count = 0
    for row in all_rows:
        if row.get("status") != "ok":
            continue
        ok_count += 1
        sel4 = row.get("our_chosen_4") or row.get("selected_4")
        if sel4:
            if isinstance(sel4, list):
                selected_4_counts[tuple(sel4)] += 1
            elif isinstance(sel4, str):
                selected_4_counts[tuple(sel4.split("|"))] += 1
        lead2 = row.get("our_lead_2") or row.get("lead_2")
        if lead2:
            if isinstance(lead2, list):
                lead_2_counts[tuple(lead2)] += 1
            elif isinstance(lead2, str):
                lead_2_counts[tuple(lead2.split("|"))] += 1
        back2 = row.get("our_back_2") or row.get("back_2")
        if back2:
            if isinstance(back2, list):
                back_2_counts[tuple(back2)] += 1
            elif isinstance(back2, str):
                back_2_counts[tuple(back2.split("|"))] += 1
    if ok_count > 0:
        preview_plan_quality["preview_validation_rate"] = ok_count / len(all_rows)
    preview_plan_quality["unique_selected_4"] = len(selected_4_counts)
    preview_plan_quality["unique_lead_2"] = len(lead_2_counts)
    preview_plan_quality["unique_back_2"] = len(back_2_counts)
    preview_plan_quality["selected_4_entropy"] = _entropy_from_counts(
        Counter({tuple(sorted(k)): v for k, v in selected_4_counts.items()})
    )

    # Outcome quality (per-pair analysis)
    treatments: List[float] = []
    decisive = 0
    learned_both = 0
    baseline_both = 0
    split_count = 0
    for pid, sides in pairs.items():
        if "p1" not in sides or "p2" not in sides:
            continue
        r1 = sides["p1"]
        r2 = sides["p2"]
        if r1.get("status") != "ok" or r2.get("status") != "ok":
            continue
        w1 = r1.get("our_win")
        w2 = r2.get("our_win")
        if w1 is None or w2 is None:
            continue
        if w1 and not w2:
            t = 1.0
            outcome_quality["learned_both"] += 1
        elif w2 and not w1:
            t = -1.0
            outcome_quality["baseline_both"] += 1
        else:
            t = 0.0
            split_count += 1
        treatments.append(t)
        decisive += 1
    outcome_quality["total_decisive_pairs"] = decisive
    outcome_quality["split"] = split_count
    # Wins
    for r in all_rows:
        if r.get("status") != "ok":
            continue
        if r.get("our_policy") == "learned_preview_v3c1":
            if r.get("our_win"):
                outcome_quality["learned_wins"] += 1
        elif r.get("our_policy") == "matchup_top4_v3":
            if r.get("our_win"):
                outcome_quality["baseline_wins"] += 1
    if treatments:
        te = sum(treatments) / len(treatments)
        outcome_quality["treatment_effect"] = te
        s = sum(1 for t in treatments if t > 0)
        n = len(treatments)
        lo, hi = _wilson_ci(s, n)
        outcome_quality["wilson_lo"] = lo
        outcome_quality["wilson_hi"] = hi
        bmean, blo, bhi = _bootstrap_ci(treatments)
        outcome_quality["bootstrap_lo"] = blo
        outcome_quality["bootstrap_hi"] = bhi

    # Leakage risk
    if model:
        feature_names = model.get("feature_names", [])
        for fname in feature_names:
            fn = fname.lower()
            for pat in _HIDDEN_INFO_PATTERNS:
                if pat in fn:
                    leakage_risk["non_observable_feature_names"].append(fname)
                    break
    # Duplicate selected_4 rows
    sel4_list: List[Tuple] = []
    for row in all_rows:
        sel4 = row.get("our_chosen_4") or row.get("selected_4")
        if sel4:
            if isinstance(sel4, list):
                sel4_list.append(tuple(sel4))
            elif isinstance(sel4, str):
                sel4_list.append(tuple(sel4.split("|")))
    sel4_counts = Counter(sel4_list)
    leakage_risk["duplicate_selected_4_rows"] = sum(
        c - 1 for c in sel4_counts.values() if c > 1
    )

    # Feature/model quality
    if model:
        feature_names = model.get("feature_names", [])
        weights = model.get("weights", {})
        feature_model_quality["feature_count"] = len(feature_names)
        nonzero = {
            k: v for k, v in weights.items() if abs(v) > 1e-9
        }
        feature_model_quality["nonzero_weight_count"] = len(nonzero)
        sorted_pos = sorted(
            nonzero.items(), key=lambda x: -x[1]
        )[:5]
        sorted_neg = sorted(
            nonzero.items(), key=lambda x: x[1]
        )[:5]
        feature_model_quality["top_positive_weights"] = [
            {"feature": k, "weight": v} for k, v in sorted_pos
        ]
        feature_model_quality["top_negative_weights"] = [
            {"feature": k, "weight": v} for k, v in sorted_neg
        ]
        if weights:
            mags = [abs(v) for v in weights.values()]
            feature_model_quality["weight_magnitude_max"] = max(mags)
            feature_model_quality["weight_magnitude_mean"] = sum(mags) / len(mags)
        feature_model_quality["bias"] = model.get("bias")
        # Feature family counts
        family_counts: Counter = Counter()
        for fname in feature_names:
            if fname.startswith("back_"):
                family_counts["back"] += 1
            elif fname.startswith("lead_"):
                family_counts["lead"] += 1
            elif fname.startswith("opp_"):
                family_counts["opponent"] += 1
            elif fname.startswith("our_"):
                family_counts["our_team"] += 1
            elif fname.startswith("sc_"):
                family_counts["speed_control"] += 1
            else:
                family_counts["other"] += 1
        # V3d.1 fine-grained feature family counts (if the
        # feature names are in the V3d.1 set).
        try:
            from vgc2026_phaseV3d1_opponent_features import (
                V3D1_FEATURE_FAMILY,
            )
            v3d1_fine: Counter = Counter()
            for fname in feature_names:
                if fname in V3D1_FEATURE_FAMILY:
                    v3d1_fine[V3D1_FEATURE_FAMILY[fname]] += 1
            if v3d1_fine:
                family_counts["v3d1_type_synergy"] = (
                    v3d1_fine.get("type_synergy", 0)
                )
                family_counts["v3d1_speed_tier"] = (
                    v3d1_fine.get("speed_tier", 0)
                )
                family_counts["v3d1_speed_control"] = (
                    v3d1_fine.get("speed_control", 0)
                )
                family_counts["v3d1_role_balance"] = (
                    v3d1_fine.get("role_balance", 0)
                )
                family_counts["v3d1_lead_pair_synergy"] = (
                    v3d1_fine.get("lead_pair_synergy", 0)
                )
                family_counts["v3d1_anti_meta_coverage"] = (
                    v3d1_fine.get("anti_meta_coverage", 0)
                )
        except ImportError:
            pass
        feature_model_quality["feature_family_counts"] = dict(family_counts)
        # Suspicious feature names
        for fname in feature_names:
            fn = fname.lower()
            for pat in _HIDDEN_INFO_PATTERNS:
                if pat in fn:
                    feature_model_quality["suspicious_feature_names"].append(fname)
                    break

    # RL readiness
    if csv_rows or jsonl_rows:
        rl_readiness["state_availability"] = "yes"  # team species, HP, etc.
        rl_readiness["action_availability"] = "yes"  # 90 plans
        rl_readiness["reward_availability"] = "yes"  # win/loss
        rl_readiness["episode_boundary_availability"] = "yes"  # per-battle
        rl_readiness["opponent_action_availability"] = "yes"  # opp_chosen_4
        rl_readiness["counterfactual_availability"] = (
            "partial" if not preview_plan_quality["plan_change_rate"] else "yes"
        )
        if decisive >= 100:
            rl_readiness["volume_adequacy"] = "adequate"
        elif decisive >= 50:
            rl_readiness["volume_adequacy"] = "marginal"
        else:
            rl_readiness["volume_adequacy"] = "insufficient"
        if all(
            v in ("yes", "partial", "adequate")
            for v in [
                rl_readiness["state_availability"],
                rl_readiness["action_availability"],
                rl_readiness["reward_availability"],
                rl_readiness["episode_boundary_availability"],
                rl_readiness["opponent_action_availability"],
                rl_readiness["counterfactual_availability"],
                rl_readiness["volume_adequacy"],
            ]
        ):
            rl_readiness["recommendation"] = "ready"
        elif rl_readiness["volume_adequacy"] == "insufficient":
            rl_readiness["recommendation"] = "not ready (volume)"
        else:
            rl_readiness["recommendation"] = "partial"

    # Recommendations
    if data_quality["timeout_count"] > 0 or data_quality["error_count"] > 0:
        recommendations.append(
            f"Data has {data_quality['timeout_count']} timeouts and "
            f"{data_quality['error_count']} errors. Investigate."
        )
    if leakage_risk["non_observable_feature_names"]:
        recommendations.append(
            f"Found {len(leakage_risk['non_observable_feature_names'])} "
            f"potentially hidden-info features: "
            f"{leakage_risk['non_observable_feature_names']}"
        )
    if outcome_quality["treatment_effect"] is not None:
        te = outcome_quality["treatment_effect"]
        if te < 0:
            recommendations.append(
                f"Treatment effect is negative ({te:.3f}). "
                f"Learned policy underperforms baseline."
            )
        elif te < 0.02:
            recommendations.append(
                f"Treatment effect is small ({te:.3f}). "
                f"Learned policy shows minimal improvement."
            )
    if leakage_risk["duplicate_selected_4_rows"] > 0:
        recommendations.append(
            f"Found {leakage_risk['duplicate_selected_4_rows']} "
            f"duplicate selected_4 rows. May indicate low plan diversity."
        )
    if pair_integrity["duplicate_battle_tags"] > 0:
        recommendations.append(
            f"Found {pair_integrity['duplicate_battle_tags']} "
            f"duplicate battle tags. May indicate data corruption."
        )
    if preview_plan_quality["unique_selected_4"] < 10:
        recommendations.append(
            f"Only {preview_plan_quality['unique_selected_4']} unique "
            f"selected_4 plans. Low plan diversity."
        )
    if not recommendations:
        recommendations.append(
            "No major issues found. Data quality is adequate."
        )

    return {
        "data_quality": data_quality,
        "pair_integrity": pair_integrity,
        "preview_plan_quality": preview_plan_quality,
        "outcome_quality": outcome_quality,
        "leakage_risk": leakage_risk,
        "feature_model_quality": feature_model_quality,
        "rl_readiness": rl_readiness,
        "recommendations": recommendations,
    }


def _write_markdown(
    input_paths: Dict[str, Optional[str]],
    agg: Dict[str, Any],
    md_path: str,
) -> None:
    """Phase RL-2: write the markdown report."""
    dq = agg["data_quality"]
    pi = agg["pair_integrity"]
    ppq = agg["preview_plan_quality"]
    oq = agg["outcome_quality"]
    lr = agg["leakage_risk"]
    fmq = agg["feature_model_quality"]
    rlr = agg["rl_readiness"]
    recs = agg["recommendations"]

    lines: List[str] = []
    lines.append("# Phase RL-2 — Team-Preview Dataset Quality Analysis")
    lines.append("")
    lines.append("## TL;DR")
    lines.append("")
    lines.append(f"- CSV rows: {dq['csv_rows']}")
    lines.append(f"- JSONL rows: {dq['jsonl_rows']}")
    lines.append(f"- Model loaded: {dq['model_path'] is not None}")
    if oq["treatment_effect"] is not None:
        lines.append(
            f"- Treatment effect: {oq['treatment_effect']:.3f} "
            f"(bootstrap [{oq['bootstrap_lo']:.3f}, "
            f"{oq['bootstrap_hi']:.3f}])"
        )
    lines.append(f"- RL readiness: {rlr['recommendation']}")
    lines.append(f"- Recommendations: {len(recs)}")
    lines.append("")
    lines.append("## Inputs")
    lines.append("")
    for k, v in input_paths.items():
        lines.append(f"- {k}: `{v}`")
    lines.append("")
    lines.append("## Data Quality")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    lines.append(f"| CSV rows | {dq['csv_rows']} |")
    lines.append(f"| JSONL rows | {dq['jsonl_rows']} |")
    lines.append(
        f"| CSV status counts | {dq['csv_status_counts']} |"
    )
    lines.append(
        f"| JSONL status counts | {dq['jsonl_status_counts']} |"
    )
    lines.append(f"| timeout count | {dq['timeout_count']} |")
    lines.append(f"| error count | {dq['error_count']} |")
    lines.append(f"| no_battle count | {dq['no_battle_count']} |")
    lines.append("")
    lines.append("## Pair Integrity")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    lines.append(f"| total rows | {pi['total_rows']} |")
    lines.append(f"| complete pairs | {pi['complete_pairs']} |")
    lines.append(f"| missing D1 | {pi['missing_d1_count']} |")
    lines.append(f"| missing D2 | {pi['missing_d2_count']} |")
    lines.append(f"| valid pairs | {pi['valid_pairs']} |")
    lines.append(
        f"| side balance | {pi['side_balance']} |"
    )
    lines.append(
        f"| duplicate pair ids | {pi['duplicate_pair_ids']} |"
    )
    lines.append(
        f"| duplicate battle tags | {pi['duplicate_battle_tags']} |"
    )
    lines.append("")
    lines.append("## Preview Plan Quality")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    lines.append(
        f"| preview validation rate | "
        f"{ppq['preview_validation_rate']:.3f} |"
    )
    lines.append(
        f"| unique selected_4 | {ppq['unique_selected_4']} |"
    )
    lines.append(
        f"| unique lead_2 | {ppq['unique_lead_2']} |"
    )
    lines.append(
        f"| unique back_2 | {ppq['unique_back_2']} |"
    )
    lines.append(
        f"| selected_4 entropy | {ppq['selected_4_entropy']:.3f} |"
    )
    lines.append("")
    lines.append("## Outcome / Label Quality")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    lines.append(f"| learned wins | {oq['learned_wins']} |")
    lines.append(f"| baseline wins | {oq['baseline_wins']} |")
    lines.append(
        f"| total decisive pairs | {oq['total_decisive_pairs']} |"
    )
    lines.append(f"| learned_both | {oq['learned_both']} |")
    lines.append(f"| baseline_both | {oq['baseline_both']} |")
    lines.append(f"| split | {oq['split']} |")
    if oq["treatment_effect"] is not None:
        lines.append(
            f"| treatment effect | "
            f"{oq['treatment_effect']:.3f} |"
        )
        lines.append(
            f"| Wilson 95% CI | "
            f"[{oq['wilson_lo']:.3f}, {oq['wilson_hi']:.3f}] |"
        )
        lines.append(
            f"| Bootstrap 95% CI | "
            f"[{oq['bootstrap_lo']:.3f}, {oq['bootstrap_hi']:.3f}] |"
        )
    lines.append("")
    lines.append("## Leakage and Duplicate Risk")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    lines.append(
        f"| duplicate team hashes | "
        f"{lr['duplicate_team_hashes']} |"
    )
    lines.append(
        f"| duplicate selected_4 rows | "
        f"{lr['duplicate_selected_4_rows']} |"
    )
    lines.append(
        f"| non-observable feature names | "
        f"{lr['non_observable_feature_names']} |"
    )
    lines.append("")
    lines.append("## Feature / Model Quality")
    lines.append("")
    if fmq["feature_count"] > 0:
        lines.append("| metric | value |")
        lines.append("|---|---|")
        lines.append(
            f"| feature count | {fmq['feature_count']} |"
        )
        lines.append(
            f"| nonzero weight count | "
            f"{fmq['nonzero_weight_count']} |"
        )
        lines.append(
            f"| weight magnitude max | "
            f"{fmq['weight_magnitude_max']:.4f} |"
        )
        lines.append(
            f"| weight magnitude mean | "
            f"{fmq['weight_magnitude_mean']:.4f} |"
        )
        lines.append(f"| bias | {fmq['bias']} |")
        lines.append(
            f"| feature family counts | "
            f"{fmq['feature_family_counts']} |"
        )
        lines.append(
            f"| suspicious feature names | "
            f"{fmq['suspicious_feature_names']} |"
        )
        lines.append("")
        lines.append("### Top positive weights")
        lines.append("")
        lines.append("| feature | weight |")
        lines.append("|---|---|")
        for w in fmq["top_positive_weights"]:
            lines.append(f"| {w['feature']} | {w['weight']:.4f} |")
        lines.append("")
        lines.append("### Top negative weights")
        lines.append("")
        lines.append("| feature | weight |")
        lines.append("|---|---|")
        for w in fmq["top_negative_weights"]:
            lines.append(f"| {w['feature']} | {w['weight']:.4f} |")
    else:
        lines.append("No model provided.")
    lines.append("")
    lines.append("## RL Readiness")
    lines.append("")
    lines.append("| requirement | status |")
    lines.append("|---|---|")
    lines.append(
        f"| state availability | {rlr['state_availability']} |"
    )
    lines.append(
        f"| action availability | {rlr['action_availability']} |"
    )
    lines.append(
        f"| reward availability | {rlr['reward_availability']} |"
    )
    lines.append(
        f"| episode boundary availability | "
        f"{rlr['episode_boundary_availability']} |"
    )
    lines.append(
        f"| opponent action availability | "
        f"{rlr['opponent_action_availability']} |"
    )
    lines.append(
        f"| counterfactual availability | "
        f"{rlr['counterfactual_availability']} |"
    )
    lines.append(
        f"| volume adequacy | {rlr['volume_adequacy']} |"
    )
    lines.append(
        f"| recommendation | {rlr['recommendation']} |"
    )
    lines.append("")
    lines.append("## Recommendations")
    lines.append("")
    for i, r in enumerate(recs, 1):
        lines.append(f"{i}. {r}")
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "- This analyzer is read-only. It does not change "
        "production code, training, or data."
    )
    lines.append(
        "- It only sees what the artifacts contain. Missing "
        "fields are handled as unavailable."
    )
    lines.append(
        "- Team hash and feature vector leakage checks are "
        "limited to fields present in the artifacts."
    )
    lines.append(
        "- Plan change rate requires both learned and "
        "baseline plans in the same row pair."
    )
    lines.append("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))


def _write_json(
    agg: Dict[str, Any],
    json_path: str,
) -> None:
    """Phase RL-2: write the JSON summary."""
    with open(json_path, "w") as f:
        json.dump(agg, f, indent=2, default=str)


def main():
    parser = argparse.ArgumentParser(
        description="Phase RL-2 — Read-only team-preview "
                    "dataset quality analyzer"
    )
    parser.add_argument(
        "--csv", default=None,
        help="Paired battle CSV path (optional)"
    )
    parser.add_argument(
        "--jsonl", default=None,
        help="Paired battle JSONL path (optional)"
    )
    parser.add_argument(
        "--model", default=None,
        help="V3c.1 model JSON path (optional)"
    )
    parser.add_argument(
        "--md", required=True,
        help="Output markdown report path (required)"
    )
    parser.add_argument(
        "--json", default=None,
        help="Output JSON summary path (optional)"
    )
    args = parser.parse_args()

    if not (args.csv or args.jsonl or args.model):
        print(
            "Error: at least one of --csv, --jsonl, --model "
            "is required.",
            file=sys.stderr,
        )
        sys.exit(1)

    csv_rows, csv_errors, csv_total = [], 0, 0
    if args.csv:
        csv_rows, csv_errors, csv_total = _load_csv(args.csv)
    jsonl_rows, jsonl_errors, jsonl_total = [], 0, 0
    if args.jsonl:
        jsonl_rows, jsonl_errors, jsonl_total = _load_jsonl(
            args.jsonl
        )
    model = None
    if args.model:
        model = _load_model(args.model)

    input_paths = {
        "csv": args.csv,
        "jsonl": args.jsonl,
        "model": args.model,
    }
    agg = _aggregate(
        csv_rows, jsonl_rows, model,
        args.csv, args.jsonl, args.model,
    )
    # Add parse error counts to data quality.
    agg["data_quality"]["csv_parse_errors"] = csv_errors
    agg["data_quality"]["csv_total_lines"] = csv_total
    agg["data_quality"]["jsonl_parse_errors"] = jsonl_errors
    agg["data_quality"]["jsonl_total_lines"] = jsonl_total

    _write_markdown(input_paths, agg, args.md)
    print(f"Wrote markdown report: {args.md}")

    if args.json:
        _write_json(agg, args.json)
        print(f"Wrote JSON summary: {args.json}")


if __name__ == "__main__":
    main()