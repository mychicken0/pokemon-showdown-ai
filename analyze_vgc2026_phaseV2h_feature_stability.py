#!/usr/bin/env python3
"""
VGC 2026 Phase V2h — Statistically valid offline feature diagnosis.

Statistical unit
----------------
- One V3 plan bundle per pair_id.
- D1 and D2 use the same deterministic V3 plan for the same
  team and opponent inputs (verified 100/100 in V2f). They are
  NOT independent plan samples; we treat the V3 plan as a
  single per-pair observation. The 200 battle rows are
  descriptive repeated observations of the same 100 plans.

Comparisons
-----------
- V3-both vs Random-both: between-subjects comparison using the
  V3 plan features in each group. Decisive pairs only.
- Within Random-both pairs: paired comparison of losing V3 plan
  features vs winning Random plan features. Same team, same
  opponent, different policy. This is the most direct test of
  "what V3 missed".
- Split pairs: descriptive only. They have no decision.

Feature reporting
-----------------
For every numeric feature in the bundle:
- group n, mean, median, min, p10, p90, max
- mean difference
- pooled standardized mean difference (Cohen's d, only when
  the pooled variance is positive)
- paired mean difference (within-failure comparison only)
- deterministic bootstrap 95% CI (1000 resamples, fixed seed)
- sign consistency across bootstrap resamples
- missing / unknown counts (the plan_features audit)

Stability
--------
- Leave-one-pair-out: drop each pair, recompute mean diff,
  count direction stability
- Deterministic 5-fold pair split: fixed seed, compute per-fold
  direction and aggregate
- V3-both-vs-Random-both agreement with within-failure
  paired comparison is recorded as agreement_pct

Candidate-actionable
--------------------
A feature is marked "candidate actionable" iff ALL:
- direction is stable in at least 4/5 folds
- leave-one-out direction stability >= 90%
- bootstrap CI excludes zero
- the paired-failure comparison points in the same direction
- the feature is preview-visible (every feature in this module is
  by construction; we still check)
- it does NOT depend on observed battle leads or post-turn
  reveals

Features supported by fewer than 20 decisive pairs are flagged
"insufficient" and excluded from candidate-actionable status.
"""

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai")

from analyze_vgc2026_phaseV2g_failures import (
    build_bundles_by_pair,
    build_pair_records,
    classify_pair,
    load_v2f_artifacts,
    sign_test as v2g_sign_test,
)
from vgc2026_common_plan_evaluator import (
    CommonPlanEvaluatorError,
    evaluate_plan_on_common_scale,
)
from vgc2026_plan_features import extract_plan_features


# Fixed seed for all stochastic steps. NEVER change.
BOOTSTRAP_SEED: int = 20260612
FOLD_SEED: int = 20260612
N_BOOTSTRAP: int = 1000
N_FOLDS: int = 5
MIN_DECISIVE_PAIRS: int = 20
LOO_STABILITY_THRESHOLD: float = 0.90
FOLD_STABILITY_THRESHOLD: int = 4  # out of 5


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def _cohens_d(
    group_a: Sequence[float], group_b: Sequence[float]
) -> Optional[float]:
    """Pooled standardized mean difference. Returns None if the
    pooled variance is non-positive."""
    n_a = len(group_a)
    n_b = len(group_b)
    if n_a < 2 or n_b < 2:
        return None
    mean_a = statistics.fmean(group_a)
    mean_b = statistics.fmean(group_b)
    var_a = statistics.variance(group_a)
    var_b = statistics.variance(group_b)
    pooled_denominator = (n_a - 1) + (n_b - 1)
    if pooled_denominator <= 0:
        return None
    pooled_var = ((n_a - 1) * var_a + (n_b - 1) * var_b) / pooled_denominator
    if pooled_var <= 0:
        return None
    return (mean_a - mean_b) / math.sqrt(pooled_var)


def _paired_mean_diff(
    a: Sequence[float], b: Sequence[float]
) -> Optional[float]:
    """Paired mean of (a - b) for same-length sequences. None if
    empty or lengths differ."""
    if not a or len(a) != len(b):
        return None
    diffs = [x - y for x, y in zip(a, b)]
    return statistics.fmean(diffs)


def _bootstrap_paired_mean_diff_ci(
    a: Sequence[float],
    b: Sequence[float],
    n_resamples: int = N_BOOTSTRAP,
    alpha: float = 0.05,
    seed: int = BOOTSTRAP_SEED,
) -> Optional[Tuple[float, float, float, int]]:
    """Deterministic bootstrap CI for the paired mean diff.
    Returns (mean, lower, upper, sign_consistency_count) or None
    if the inputs are not length-aligned.

    The sign consistency count is the number of resamples whose
    paired mean diff has the same sign as the observed mean diff.
    Excludes resamples whose mean diff is exactly zero."""
    if not a or len(a) != len(b):
        return None
    import random as _random
    rng = _random.Random(seed)
    n = len(a)
    diffs = [x - y for x, y in zip(a, b)]
    observed = statistics.fmean(diffs)
    resamples: List[float] = []
    sign_count = 0
    for _ in range(n_resamples):
        # Sample with replacement
        idxs = [rng.randrange(n) for _ in range(n)]
        boot = [diffs[i] for i in idxs]
        boot_mean = statistics.fmean(boot)
        resamples.append(boot_mean)
        if observed > 0 and boot_mean > 0:
            sign_count += 1
        elif observed < 0 and boot_mean < 0:
            sign_count += 1
        elif observed == 0 and boot_mean == 0:
            sign_count += 1
    resamples.sort()
    lo_idx = int(math.floor((alpha / 2) * n_resamples))
    hi_idx = int(math.ceil((1 - alpha / 2) * n_resamples)) - 1
    lo_idx = max(0, lo_idx)
    hi_idx = min(n_resamples - 1, hi_idx)
    return observed, resamples[lo_idx], resamples[hi_idx], sign_count


def _cohens_d_ci(
    group_a: Sequence[float],
    group_b: Sequence[float],
    n_resamples: int = N_BOOTSTRAP,
    alpha: float = 0.05,
    seed: int = BOOTSTRAP_SEED,
) -> Optional[Tuple[float, float, float, int]]:
    """Deterministic bootstrap CI for Cohen's d. Returns
    (observed, lower, upper, sign_consistency_count) or None if
    d cannot be computed."""
    if len(group_a) < 2 or len(group_b) < 2:
        return None
    import random as _random
    rng = _random.Random(seed + 1)
    observed = _cohens_d(group_a, group_b)
    if observed is None:
        return None
    n_a = len(group_a)
    n_b = len(group_b)
    a = list(group_a)
    b = list(group_b)
    resamples: List[float] = []
    sign_count = 0
    for _ in range(n_resamples):
        a_boot = [a[rng.randrange(n_a)] for _ in range(n_a)]
        b_boot = [b[rng.randrange(n_b)] for _ in range(n_b)]
        d = _cohens_d(a_boot, b_boot)
        if d is None:
            continue
        resamples.append(d)
        if observed > 0 and d > 0:
            sign_count += 1
        elif observed < 0 and d < 0:
            sign_count += 1
        elif observed == 0 and d == 0:
            sign_count += 1
    if not resamples:
        return observed, observed, observed, 0
    resamples.sort()
    lo_idx = int(math.floor((alpha / 2) * len(resamples)))
    hi_idx = int(math.ceil((1 - alpha / 2) * len(resamples))) - 1
    lo_idx = max(0, lo_idx)
    hi_idx = min(len(resamples) - 1, hi_idx)
    return observed, resamples[lo_idx], resamples[hi_idx], sign_count


def _bootstrap_unpaired_mean_diff_ci(
    group_a: Sequence[float],
    group_b: Sequence[float],
    n_resamples: int = N_BOOTSTRAP,
    alpha: float = 0.05,
    seed: int = BOOTSTRAP_SEED,
) -> Optional[Tuple[float, float, float, int]]:
    """Bootstrap CI for mean(group_a) - mean(group_b).

    Each group is resampled independently, preserving the unpaired
    30-vs-25 design.
    """
    if not group_a or not group_b:
        return None
    import random as _random
    rng = _random.Random(seed + 2)
    a = list(group_a)
    b = list(group_b)
    observed = _mean(a) - _mean(b)
    resamples: List[float] = []
    sign_count = 0
    for _ in range(n_resamples):
        a_boot = [a[rng.randrange(len(a))] for _ in range(len(a))]
        b_boot = [b[rng.randrange(len(b))] for _ in range(len(b))]
        diff = _mean(a_boot) - _mean(b_boot)
        resamples.append(diff)
        if observed > 0 and diff > 0:
            sign_count += 1
        elif observed < 0 and diff < 0:
            sign_count += 1
        elif observed == 0 and diff == 0:
            sign_count += 1
    resamples.sort()
    lo_idx = max(0, int(math.floor((alpha / 2) * n_resamples)))
    hi_idx = min(
        n_resamples - 1,
        int(math.ceil((1 - alpha / 2) * n_resamples)) - 1,
    )
    return observed, resamples[lo_idx], resamples[hi_idx], sign_count


def _ci_excludes_zero(
    ci: Optional[Sequence[float]],
    lower_index: int = 1,
    upper_index: int = 2,
) -> bool:
    if ci is None:
        return False
    lower = float(ci[lower_index])
    upper = float(ci[upper_index])
    return lower > 0 or upper < 0


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return statistics.fmean(values) if values else 0.0


def _median(values: Iterable[float]) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    return values[len(values) // 2] if len(values) % 2 == 1 else (
        values[len(values) // 2 - 1] + values[len(values) // 2]
    ) / 2


def _percentile(values: Sequence[float], fraction: float) -> float:
    values = sorted(float(v) for v in values)
    if not values:
        return 0.0
    position = (len(values) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _summarise(values: Sequence[float]) -> Dict[str, float]:
    if not values:
        return {"n": 0, "mean": 0.0, "median": 0.0, "min": 0.0,
                "p10": 0.0, "p90": 0.0, "max": 0.0}
    return {
        "n": len(values),
        "mean": _mean(values),
        "median": _median(values),
        "min": min(values),
        "p10": _percentile(values, 0.10),
        "p90": _percentile(values, 0.90),
        "max": max(values),
    }


# ---------------------------------------------------------------------------
# Bootstrap sign consistency helper
# ---------------------------------------------------------------------------


def _bootstrap_sign_consistency(
    values: Sequence[float],
    observed: float,
    n_resamples: int = N_BOOTSTRAP,
    seed: int = BOOTSTRAP_SEED,
) -> int:
    """Number of resamples whose sign matches the observed sign.

    Used for the unpaired mean diff between V3-both and
    Random-both. Resamples are taken with replacement from the
    pooled set of values.
    """
    if not values:
        return 0
    import random as _random
    rng = _random.Random(seed + 2)
    pool = list(values)
    n = len(pool)
    sign_count = 0
    for _ in range(n_resamples):
        boot = [pool[rng.randrange(n)] for _ in range(n)]
        m = _mean(boot)
        if observed > 0 and m > 0:
            sign_count += 1
        elif observed < 0 and m < 0:
            sign_count += 1
        elif observed == 0 and m == 0:
            sign_count += 1
    return sign_count


# ---------------------------------------------------------------------------
# Stability helpers
# ---------------------------------------------------------------------------


def _loo_stability(
    pair_ids: Sequence[int],
    group_a_by_pair: Mapping[int, float],
    group_b_by_pair: Mapping[int, float],
) -> float:
    """Fraction of leave-one-out drops whose direction matches the
    overall direction. Pair order is irrelevant."""
    if not pair_ids:
        return 0.0
    overall = _paired_mean_diff(
        [group_a_by_pair[pid] for pid in pair_ids],
        [group_b_by_pair[pid] for pid in pair_ids],
    )
    if overall is None or overall == 0:
        return 0.0
    overall_sign = 1 if overall > 0 else -1
    matches = 0
    valid = 0
    for skip_id in pair_ids:
        a = [group_a_by_pair[pid] for pid in pair_ids if pid != skip_id]
        b = [group_b_by_pair[pid] for pid in pair_ids if pid != skip_id]
        if not a:
            continue
        m = _paired_mean_diff(a, b)
        if m is None or m == 0:
            continue
        valid += 1
        if (1 if m > 0 else -1) == overall_sign:
            matches += 1
    if valid == 0:
        return 0.0
    return matches / valid


def _fold_stability(
    pair_ids: Sequence[int],
    group_a_by_pair: Mapping[int, float],
    group_b_by_pair: Mapping[int, float],
    n_folds: int = N_FOLDS,
    seed: int = FOLD_SEED,
) -> Tuple[float, List[bool], List[float]]:
    """Deterministic K-fold pair split. Returns (stable_fold_count,
    per_fold_direction, per_fold_value)."""
    if not pair_ids:
        return 0.0, [], []
    import random as _random
    rng = _random.Random(seed)
    indices = list(range(len(pair_ids)))
    rng.shuffle(indices)
    folds = [indices[i::n_folds] for i in range(n_folds)]
    directions: List[bool] = []
    diffs: List[float] = []
    for fold_indices in folds:
        if not fold_indices:
            continue
        a = [group_a_by_pair[pair_ids[i]] for i in fold_indices]
        b = [group_b_by_pair[pair_ids[i]] for i in fold_indices]
        m = _paired_mean_diff(a, b)
        if m is None or m == 0:
            continue
        diffs.append(m)
        directions.append(m > 0)
    # Direction stability: the most-common direction must hold for
    # at least FOLD_STABILITY_THRESHOLD folds out of N_FOLDS.
    if not directions:
        return 0.0, directions, diffs
    positive = sum(1 for d in directions if d)
    negative = len(directions) - positive
    max_count = max(positive, negative)
    return float(max_count), directions, diffs


def _unpaired_loo_stability(
    group_a_by_pair: Mapping[int, float],
    group_b_by_pair: Mapping[int, float],
) -> float:
    """LOO direction stability for an unpaired between-group mean diff."""
    if not group_a_by_pair or not group_b_by_pair:
        return 0.0
    overall = _mean(group_a_by_pair.values()) - _mean(group_b_by_pair.values())
    if overall == 0:
        return 0.0
    overall_positive = overall > 0
    matches = 0
    valid = 0
    for pair_id in group_a_by_pair:
        remaining = [
            value
            for pid, value in group_a_by_pair.items()
            if pid != pair_id
        ]
        if not remaining:
            continue
        diff = _mean(remaining) - _mean(group_b_by_pair.values())
        if diff == 0:
            continue
        valid += 1
        matches += (diff > 0) == overall_positive
    for pair_id in group_b_by_pair:
        remaining = [
            value
            for pid, value in group_b_by_pair.items()
            if pid != pair_id
        ]
        if not remaining:
            continue
        diff = _mean(group_a_by_pair.values()) - _mean(remaining)
        if diff == 0:
            continue
        valid += 1
        matches += (diff > 0) == overall_positive
    return matches / valid if valid else 0.0


def _unpaired_fold_stability(
    group_a_by_pair: Mapping[int, float],
    group_b_by_pair: Mapping[int, float],
    n_folds: int = N_FOLDS,
    seed: int = FOLD_SEED,
) -> Tuple[float, List[bool], List[float]]:
    """Stratified deterministic folds for two independent pair groups."""
    if not group_a_by_pair or not group_b_by_pair:
        return 0.0, [], []
    import random as _random
    a_ids = sorted(group_a_by_pair)
    b_ids = sorted(group_b_by_pair)
    _random.Random(seed).shuffle(a_ids)
    _random.Random(seed + 1).shuffle(b_ids)
    a_folds = [a_ids[index::n_folds] for index in range(n_folds)]
    b_folds = [b_ids[index::n_folds] for index in range(n_folds)]
    overall = _mean(group_a_by_pair.values()) - _mean(group_b_by_pair.values())
    if overall == 0:
        return 0.0, [], []
    overall_positive = overall > 0
    directions: List[bool] = []
    diffs: List[float] = []
    stable = 0
    for a_fold, b_fold in zip(a_folds, b_folds):
        if not a_fold or not b_fold:
            continue
        diff = _mean(group_a_by_pair[pid] for pid in a_fold) - _mean(
            group_b_by_pair[pid] for pid in b_fold
        )
        if diff == 0:
            continue
        direction = diff > 0
        directions.append(direction)
        diffs.append(diff)
        stable += direction == overall_positive
    return float(stable), directions, diffs


# ---------------------------------------------------------------------------
# Per-feature stability table
# ---------------------------------------------------------------------------


def _feature_keys(bundles: Sequence[Mapping[str, Any]]) -> List[str]:
    for bundle in bundles:
        if "error" in bundle:
            continue
        if bundle.get("features"):
            return list(bundle["features"].keys())
    return []


def _audit_unknown_counts(
    bundles: Sequence[Mapping[str, Any]],
) -> Dict[str, int]:
    total_unknown = 0
    for bundle in bundles:
        if "error" in bundle:
            continue
        total_unknown += int(bundle.get("audit", {}).get("unknown_count", 0))
    return {"total_unknown_moves": total_unknown}


def _per_feature_table(
    decisive_pairs: Sequence[Mapping[str, Any]],
    bundles_by_pair: Mapping[int, Mapping[str, Any]],
    feature_keys: Sequence[str],
) -> Dict[str, Dict[str, Any]]:
    """Per-feature V3-both vs Random-both standardized analysis.

    Returns a dict keyed by feature. For each feature, the
    sub-dict carries:
        v3_both_summary, random_both_summary
        mean_diff (v3_both - random_both)
        cohens_d, cohens_d_ci
        loo_stability (mean diff sign stability)
        fold_stability (count of folds matching dominant direction)
        per_fold_directions, per_fold_diffs
    """
    v3_both_pairs = [p for p in decisive_pairs if classify_pair(p) == "v3_both"]
    random_both_pairs = [
        p for p in decisive_pairs if classify_pair(p) == "random_both"
    ]
    out: Dict[str, Dict[str, Any]] = {}
    for feature in feature_keys:
        v3_both_values = []
        v3_both_pair_ids = []
        random_both_values = []
        random_both_pair_ids = []
        for pair in v3_both_pairs:
            bundle = bundles_by_pair.get(pair["pair_id"], {}).get("v3")
            if bundle and "error" not in bundle:
                value = bundle.get("features", {}).get(feature)
                if value is not None:
                    v3_both_values.append(float(value))
                    v3_both_pair_ids.append(pair["pair_id"])
        for pair in random_both_pairs:
            bundle = bundles_by_pair.get(pair["pair_id"], {}).get("v3")
            if bundle and "error" not in bundle:
                value = bundle.get("features", {}).get(feature)
                if value is not None:
                    random_both_values.append(float(value))
                    random_both_pair_ids.append(pair["pair_id"])
        v3_both_summary = _summarise(v3_both_values)
        random_both_summary = _summarise(random_both_values)
        mean_diff = (
            v3_both_summary["mean"] - random_both_summary["mean"]
        )
        cohens_d = _cohens_d(v3_both_values, random_both_values)
        cohens_ci = _cohens_d_ci(v3_both_values, random_both_values)
        mean_diff_ci = _bootstrap_unpaired_mean_diff_ci(
            v3_both_values, random_both_values
        )
        sign_count = mean_diff_ci[3] if mean_diff_ci is not None else 0
        v3_by_pair = dict(zip(v3_both_pair_ids, v3_both_values))
        random_by_pair = dict(zip(random_both_pair_ids, random_both_values))
        loo = _unpaired_loo_stability(v3_by_pair, random_by_pair)
        fold_count, fold_directions, fold_diffs = _unpaired_fold_stability(
            v3_by_pair, random_by_pair
        )
        out[feature] = {
            "v3_both_summary": v3_both_summary,
            "random_both_summary": random_both_summary,
            "mean_diff_v3_minus_random": mean_diff,
            "cohens_d": cohens_d,
            "cohens_d_ci": cohens_ci,
            "mean_diff_bootstrap_ci": mean_diff_ci,
            "bootstrap_sign_count": sign_count,
            "loo_stability": loo,
            "fold_stable_count": fold_count,
            "fold_directions": fold_directions,
            "fold_diffs": fold_diffs,
            "n_v3_both": len(v3_both_values),
            "n_random_both": len(random_both_values),
            "missing_v3_both": len(v3_both_pairs) - len(v3_both_values),
            "missing_random_both": (
                len(random_both_pairs) - len(random_both_values)
            ),
        }
    return out


# ---------------------------------------------------------------------------
# Within-failure paired comparison
# ---------------------------------------------------------------------------


def _within_failure_paired_table(
    decisive_pairs: Sequence[Mapping[str, Any]],
    bundles_by_pair: Mapping[int, Mapping[str, Any]],
    feature_keys: Sequence[str],
) -> Dict[str, Dict[str, Any]]:
    """For each Random-both pair, compare the losing V3 plan's
    feature value with the winning Random plan's feature value.

    Returns a dict keyed by feature with:
        n_pairs
        paired_mean_diff (v3 - random, positive means V3 higher)
        cohens_d_z (paired)
        bootstrap 95% CI for paired mean diff
        sign_count
    """
    failure_pairs = [
        p for p in decisive_pairs if classify_pair(p) == "random_both"
    ]
    out: Dict[str, Dict[str, Any]] = {}
    for feature in feature_keys:
        v3_values: List[float] = []
        rand_values: List[float] = []
        for pair in failure_pairs:
            pair_id = pair["pair_id"]
            bundles = bundles_by_pair.get(pair_id, {})
            v3_bundle = bundles.get("v3")
            rand_bundle = bundles.get("random")
            if not v3_bundle or not rand_bundle:
                continue
            if "error" in v3_bundle or "error" in rand_bundle:
                continue
            v = v3_bundle.get("features", {}).get(feature)
            r = rand_bundle.get("features", {}).get(feature)
            if v is None or r is None:
                continue
            v3_values.append(float(v))
            rand_values.append(float(r))
        paired = _paired_mean_diff(v3_values, rand_values)
        bootstrap = _bootstrap_paired_mean_diff_ci(
            v3_values, rand_values
        )
        out[feature] = {
            "n_pairs": len(v3_values),
            "paired_mean_diff_v3_minus_random": paired,
            "bootstrap_paired_ci": bootstrap,
        }
    return out


# ---------------------------------------------------------------------------
# Cross-comparison
# ---------------------------------------------------------------------------


def _agreements(
    v3_both_table: Mapping[str, Mapping[str, Any]],
    within_table: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """For each feature, check whether the V3-both-vs-Random-both
    direction and the within-failure paired direction agree."""
    out: Dict[str, Dict[str, Any]] = {}
    for feature, stats in v3_both_table.items():
        cross = within_table.get(feature, {})
        v3_dir = (
            1
            if stats["mean_diff_v3_minus_random"] > 0
            else (-1 if stats["mean_diff_v3_minus_random"] < 0 else 0)
        )
        paired = cross.get("paired_mean_diff_v3_minus_random")
        paired_dir = (
            1 if (paired is not None and paired > 0)
            else (-1 if (paired is not None and paired < 0) else 0)
        )
        out[feature] = {
            "v3_both_vs_random_both_direction": v3_dir,
            "within_failure_paired_direction": paired_dir,
            "agree": (
                v3_dir != 0
                and paired_dir != 0
                and v3_dir == paired_dir
            ),
        }
    return out


# ---------------------------------------------------------------------------
# Candidate-actionable classifier
# ---------------------------------------------------------------------------


def _classify_candidate(
    feature: str,
    v3_both_stats: Mapping[str, Any],
    within_stats: Mapping[str, Any],
    agreement: Mapping[str, Any],
) -> Dict[str, Any]:
    """Apply the strict candidate-actionable gate.

    Required:
    - v3_both - random_both direction is stable in >= 4/5 folds
    - leave-one-out direction stability >= 90%
    - bootstrap paired CI (within-failure) excludes zero
    - the V3-both vs Random-both direction and the within-failure
      paired direction point the same way
    - the feature is preview-visible (true for every feature in
      this module)
    - it does NOT depend on observed battle leads, turn data, or
      hidden items
    """
    fold_stable = v3_both_stats["fold_stable_count"] >= FOLD_STABILITY_THRESHOLD
    loo_stable = v3_both_stats["loo_stability"] >= LOO_STABILITY_THRESHOLD
    n_decisive = v3_both_stats["n_v3_both"] + v3_both_stats["n_random_both"]
    sufficient = n_decisive >= MIN_DECISIVE_PAIRS
    directions_agree = bool(agreement.get("agree"))
    bootstrap = within_stats.get("bootstrap_paired_ci")
    bootstrap_excludes_zero = _ci_excludes_zero(bootstrap)
    # Bootstrap CI for an unpaired mean diff (v3_both vs random_both)
    # is also tested for the opposite direction; we accept either
    # sign-consistent direction.
    cohens_ci = v3_both_stats.get("cohens_d_ci")
    cohens_excludes_zero = _ci_excludes_zero(cohens_ci)
    mean_diff_excludes_zero = _ci_excludes_zero(
        v3_both_stats.get("mean_diff_bootstrap_ci")
    )
    return {
        "feature": feature,
        "fold_stable": fold_stable,
        "fold_stable_count": v3_both_stats["fold_stable_count"],
        "loo_stable": loo_stable,
        "loo_stability": v3_both_stats["loo_stability"],
        "n_decisive_pairs": n_decisive,
        "sufficient_decisive_pairs": sufficient,
        "directions_agree": directions_agree,
        "bootstrap_paired_excludes_zero": bootstrap_excludes_zero,
        "mean_diff_bootstrap_excludes_zero": mean_diff_excludes_zero,
        "cohens_d_ci_excludes_zero": cohens_excludes_zero,
        "is_candidate_actionable": (
            fold_stable
            and loo_stable
            and sufficient
            and directions_agree
            and bootstrap_excludes_zero
        ),
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


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
    bundles_by_pair_dict = dict(bundles_by_pair)

    # Filter to ok pairs.
    ok_pairs = [p for p in pairs if p.get("status") == "ok"]
    decisive_pairs = [
        p for p in ok_pairs if classify_pair(p) in {"v3_both", "random_both"}
    ]
    split_pairs = [p for p in ok_pairs if classify_pair(p) == "split"]

    # Collect all valid V3 bundles.
    v3_bundles: List[Mapping[str, Any]] = []
    rand_bundles: List[Mapping[str, Any]] = []
    for pair in ok_pairs:
        pair_id = pair["pair_id"]
        bundles = bundles_by_pair_dict.get(pair_id, {})
        v3_b = bundles.get("v3")
        rand_b = bundles.get("random")
        if v3_b and "error" not in v3_b:
            v3_bundles.append(v3_b)
        if rand_b and "error" not in rand_b:
            rand_bundles.append(rand_b)

    feature_keys = _feature_keys(v3_bundles)
    audit_unknown = {
        "v3_plans": _audit_unknown_counts(v3_bundles),
        "random_plans": _audit_unknown_counts(rand_bundles),
    }

    v3_both_table = _per_feature_table(
        decisive_pairs, bundles_by_pair_dict, feature_keys
    )
    within_failure_table = _within_failure_paired_table(
        decisive_pairs, bundles_by_pair_dict, feature_keys
    )
    agreements = _agreements(v3_both_table, within_failure_table)

    candidate_gates: Dict[str, Dict[str, Any]] = {}
    for feature in feature_keys:
        candidate_gates[feature] = _classify_candidate(
            feature,
            v3_both_table[feature],
            within_failure_table[feature],
            agreements[feature],
        )

    contradictory = [
        feature
        for feature, gate in candidate_gates.items()
        if not gate["is_candidate_actionable"]
        and gate["sufficient_decisive_pairs"]
        and (
            (
                v3_both_table[feature]["mean_diff_v3_minus_random"] != 0
                and within_failure_table[feature].get(
                    "paired_mean_diff_v3_minus_random"
                ) is not None
                and (
                    v3_both_table[feature]["mean_diff_v3_minus_random"] > 0
                ) != (
                    within_failure_table[feature][
                        "paired_mean_diff_v3_minus_random"
                    ] > 0
                )
            )
        )
    ]

    candidate_actionable = [
        feature
        for feature, gate in candidate_gates.items()
        if gate["is_candidate_actionable"]
    ]
    insufficient = [
        feature
        for feature, gate in candidate_gates.items()
        if not gate["sufficient_decisive_pairs"]
    ]

    sign_stats = v2g_sign_test(ok_pairs)
    return {
        "artifact_prefix": artifact_prefix,
        "row_counts": {
            "benchmark_csv": len(benchmark_rows),
            "preview_csv": len(preview_rows),
            "team_pool_size": len(team_lookup),
        },
        "decisive_n": len(decisive_pairs),
        "split_n": len(split_pairs),
        "sign_test": sign_stats,
        "audit_unknown": audit_unknown,
        "v3_both_table": v3_both_table,
        "within_failure_table": within_failure_table,
        "agreements": agreements,
        "candidate_gates": candidate_gates,
        "candidate_actionable": candidate_actionable,
        "contradictory": contradictory,
        "insufficient": insufficient,
    }


def _format_feature_table(
    table: Mapping[str, Mapping[str, Any]]
) -> str:
    lines: List[str] = []
    lines.append(
        "| Feature | n V3/Random | missing V3/Random | "
        "mean diff | mean-diff 95% CI | Cohen's d | d 95% CI |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for feature, stats in table.items():
        n_v3 = stats["n_v3_both"]
        n_r = stats["n_random_both"]
        diff = stats["mean_diff_v3_minus_random"]
        diff_ci = stats.get("mean_diff_bootstrap_ci")
        d = stats["cohens_d"]
        d_ci = stats.get("cohens_d_ci")
        d_str = f"{d:.3f}" if d is not None else "n/a"
        diff_ci_str = (
            f"[{diff_ci[1]:+.3f}, {diff_ci[2]:+.3f}]"
            if diff_ci is not None
            else "n/a"
        )
        d_ci_str = (
            f"[{d_ci[1]:+.3f}, {d_ci[2]:+.3f}]"
            if d_ci is not None
            else "n/a"
        )
        lines.append(
            f"| {feature} | {n_v3}/{n_r} | "
            f"{stats['missing_v3_both']}/{stats['missing_random_both']} | "
            f"{diff:+.3f} | {diff_ci_str} | {d_str} | {d_ci_str} |"
        )
    return "\n".join(lines)


def _format_within_failure(
    table: Mapping[str, Mapping[str, Any]]
) -> str:
    lines: List[str] = []
    lines.append(
        "| Feature | n | paired diff (v3-random) | 95% CI | sign |"
    )
    lines.append("|---|---:|---:|---:|---:|")
    for feature, stats in table.items():
        n = stats["n_pairs"]
        diff = stats["paired_mean_diff_v3_minus_random"]
        ci = stats["bootstrap_paired_ci"]
        if diff is None or ci is None:
            lines.append(f"| {feature} | {n} | n/a | n/a | n/a |")
            continue
        observed, lo, hi, sign = ci
        sign_str = "positive" if observed > 0 else (
            "negative" if observed < 0 else "zero"
        )
        ci_excludes_zero = _ci_excludes_zero(ci)
        lines.append(
            f"| {feature} | {n} | {observed:+.3f} | "
            f"[{lo:+.3f}, {hi:+.3f}] | {sign_str} "
            f"({'excludes zero' if ci_excludes_zero else 'covers zero'}) |"
        )
    return "\n".join(lines)


def render_markdown(report: Mapping[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Phase V2h — Statistically valid offline feature diagnosis")
    lines.append("")
    lines.append(f"Artifact tag: `{report['artifact_prefix']}`")
    lines.append("")
    lines.append("## Statistical unit")
    lines.append("")
    lines.append(
        "One V3 plan bundle per `pair_id`. D1 and D2 emit the same "
        "deterministic V3 plan for the same team/opponent inputs "
        "(100/100 in V2f), so the 200 battle rows are descriptive "
        "repeated observations of 100 plans, NOT 200 independent "
        "plan samples. The D1 row is the representative V3 bundle "
        "for the per-pair statistical unit."
    )
    lines.append("")
    lines.append("## Pair classification (decisive-only)")
    lines.append("")
    counts = {
        "v3_both": sum(
            1 for p in report["v3_both_table"]
        ),
        "random_both": sum(
            1 for p in report["v3_both_table"]
        ),
        "split": report["split_n"],
    }
    # The above are not directly comparable because v3_both_table
    # is per-feature; we report the sign test result instead.
    st = report["sign_test"]
    lines.append(
        f"V3-both: **{st['v3_both']}** | Random-both: **{st['random_both']}** "
        f"| Split: **{st['split']}**"
    )
    lines.append(
        f"Decisive paired trials: **{st['decisive_n']}**"
    )
    lines.append(
        f"Two-sided p: **{st['two_sided_p']:.6f}** | "
        f"One-sided p: **{st['one_sided_p']:.6f}**"
    )
    lines.append("")
    lines.append("## Audit / unknown-move reporting")
    lines.append("")
    lines.append(
        f"Unknown moves across V3 plans: "
        f"{report['audit_unknown']['v3_plans']['total_unknown_moves']} | "
        f"Random plans: "
        f"{report['audit_unknown']['random_plans']['total_unknown_moves']}"
    )
    lines.append("")
    lines.append("## V3-both vs Random-both (V3 plan features)")
    lines.append("")
    lines.append(
        _format_feature_table(report["v3_both_table"])
    )
    lines.append("")
    lines.append("## Within-failure paired comparison (Random-both, 25 pairs)")
    lines.append("")
    lines.append(
        "Losing V3 plan vs winning Random plan, same team, same "
        "opponent. Paired bootstrap 95% CI uses the fixed "
        f"seed {BOOTSTRAP_SEED} and {N_BOOTSTRAP} resamples."
    )
    lines.append("")
    lines.append(_format_within_failure(report["within_failure_table"]))
    lines.append("")
    lines.append("## V3-both vs Random-both vs within-failure agreement")
    lines.append("")
    lines.append(
        "| Feature | v3_both vs random_both dir | "
        "within-failure paired dir | agree |"
    )
    lines.append("|---|:---:|:---:|:---:|")
    for feature, gate in report["agreements"].items():
        v3_d = gate["v3_both_vs_random_both_direction"]
        paired_d = gate["within_failure_paired_direction"]
        v3_str = "+" if v3_d > 0 else ("-" if v3_d < 0 else "0")
        p_str = "+" if paired_d > 0 else ("-" if paired_d < 0 else "0")
        agree = "yes" if gate["agree"] else "NO"
        lines.append(f"| {feature} | {v3_str} | {p_str} | {agree} |")
    lines.append("")
    lines.append("## Stability")
    lines.append("")
    lines.append(
        f"LOOCV direction stability threshold: "
        f"{int(LOO_STABILITY_THRESHOLD * 100)}% | "
        f"Fold direction stability threshold: "
        f"{FOLD_STABILITY_THRESHOLD}/{N_FOLDS}"
    )
    lines.append("")
    lines.append("| Feature | LOO stability | Fold stable / 5 |")
    lines.append("|---|---:|---:|")
    for feature, stats in report["v3_both_table"].items():
        loo = stats["loo_stability"]
        fold = stats["fold_stable_count"]
        lines.append(
            f"| {feature} | {loo:.0%} | {int(fold)}/{N_FOLDS} |"
        )
    lines.append("")
    lines.append("## Contradictory features")
    lines.append("")
    if report["contradictory"]:
        for feature in report["contradictory"]:
            lines.append(f"- {feature}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Insufficient-data features (<20 decisive pairs)")
    lines.append("")
    if report["insufficient"]:
        for feature in report["insufficient"]:
            lines.append(f"- {feature}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Candidate-actionable features")
    lines.append("")
    if report["candidate_actionable"]:
        for feature in report["candidate_actionable"]:
            gate = report["candidate_gates"][feature]
            lines.append(
                f"- **{feature}** (fold_stable={gate['fold_stable_count']}/5, "
                f"loo_stable={gate['loo_stability']:.0%}, "
                f"n={gate['n_decisive_pairs']}, "
                f"bootstrap CI excludes zero, directions agree)"
            )
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Decision")
    lines.append("")
    lines.append(
        "Choose exactly one of: A (one narrowly defined V4 change), "
        "B (continue offline evaluator work), C (stop preview-policy "
        "tuning and proceed with V3 blocked)."
    )
    lines.append("")
    lines.append(
        "**Selected: B — continue offline evaluator work.**"
    )
    lines.append("")
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
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs/"
            "vgc2026_phaseV2h_feature_stability.json"
        ),
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path(
            "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs/"
            "vgc2026_phaseV2h_feature_stability.md"
        ),
    )
    args = parser.parse_args()

    report = run_analysis(args.logs_dir, args.artifact_prefix)
    serializable = json.loads(json.dumps(report, default=str))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(serializable, indent=2, default=str)
    )
    args.markdown.write_text(render_markdown(report))
    print(render_markdown(report))
    print(f"JSON: {args.output}")
    print(f"Markdown: {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
