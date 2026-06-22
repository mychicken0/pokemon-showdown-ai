#!/usr/bin/env python3
"""Phase V3b.1 — diagnostic audit of V3b val_acc.

Ponytail: single focused module, stdlib only.
Extends the V3b trainer with 4 audits:
A) Dataset / label audit
B) Split stability audit (deterministic 30 seeds)
C) Feature scale audit
D) Ablation audit (variants × seeds)

Decision thresholds per the V3b.1 task:
- Recommend GO only if mean AND median val_acc
  across 30 seeds >= 0.60.
- Recommend battle check only if a variant
  beats V3 baseline on >= 80% of splits.
- Otherwise BLOCK.

No battles. No localhost. No policy wrapper.
All artifacts are diagnostic only.
"""
import argparse
import json
import os
import random
import statistics
import sys
from collections import Counter
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vgc2026_phaseV3a_learn_preview import (
    DEFAULT_V3A1_SOURCES,
    _pairwise_accuracy,
    assert_no_leakage,
    averaged_pairwise_update,
    baseline_validate,
    build_decisive_pair_targets,
    group_split,
)
from vgc2026_phaseV3b_train import (
    V3A1_VAL_ACC_REFERENCE,
    _load_v3b_rows,
    train_v3b,
)
from vgc_team_pool import load_vgc_pool


# ---------------------------------------------------------------------------
# Artifact paths
# ---------------------------------------------------------------------------

DATA_AUDIT_JSON = "logs/vgc2026_phaseV3b1_data_audit.json"
DATA_AUDIT_MD = "logs/vgc2026_phaseV3b1_data_audit.md"
SPLIT_STABILITY_JSON = (
    "logs/vgc2026_phaseV3b1_split_stability.json"
)
SPLIT_STABILITY_MD = (
    "logs/vgc2026_phaseV3b1_split_stability.md"
)
ABLATION_JSON = "logs/vgc2026_phaseV3b1_ablation.json"
ABLATION_MD = "logs/vgc2026_phaseV3b1_ablation.md"
DEFAULT_SEEDS = list(range(30))
V3A1_REF = V3A1_VAL_ACC_REFERENCE  # 0.75
GO_MEAN_MEDIAN_THRESHOLD = 0.60
GO_V3_BEAT_FRACTION = 0.80


# ---------------------------------------------------------------------------
# A) Dataset / label audit
# ---------------------------------------------------------------------------


def _policy_from_pair_row(row: Dict[str, Any]) -> str:
    """Extract the policy that was used by the
    row's own player. ponytail: read from
    our_policy field which is set by
    load_paired_artifacts.
    """
    return row.get("our_policy", "?") or "?"


def _build_pairs_with_meta(
    rows: List[Dict[str, Any]],
) -> Tuple[List, List[Dict[str, Any]]]:
    """Decisive pairs plus a per-row metadata trail
    for the dataset audit. ponytail: helper.
    """
    pairs, skipped = build_decisive_pair_targets(rows)
    return pairs, skipped


def dataset_audit(
    jsonl_paths: List[str], team_pool: Any
) -> Dict[str, Any]:
    """A) Dataset / label audit. Returns a dict
    suitable for JSON serialization.
    """
    rows, source_skipped = _load_v3b_rows(
        jsonl_paths, team_pool
    )
    pairs, skipped = _build_pairs_with_meta(rows)
    sources = Counter(r.get("source", "?") for r in rows)
    # Split with the canonical seed (42) to match
    # V3b's training-time split.
    train_rows, val_rows, _split = group_split(
        rows, val_fraction=0.2, seed=42
    )
    train_pairs, _ = _build_pairs_with_meta(train_rows)
    val_pairs, _ = _build_pairs_with_meta(val_rows)
    # Source distribution in train/val.
    train_sources = Counter(
        r.get("source", "?") for r in train_rows
    )
    val_sources = Counter(
        r.get("source", "?") for r in val_rows
    )
    # Policy distribution in train/val rows.
    train_policies = Counter(
        _policy_from_pair_row(r) for r in train_rows
    )
    val_policies = Counter(
        _policy_from_pair_row(r) for r in val_rows
    )
    # Winner / loser policy distribution from
    # decisive pairs.
    def _policy_of(p):
        return _policy_from_pair_row(p)
    winner_policies = Counter(
        _policy_of(w) for w, _ in pairs
    )
    loser_policies = Counter(
        _policy_of(l) for _, l in pairs
    )
    train_winner = Counter(
        _policy_of(w) for w, _ in train_pairs
    )
    val_winner = Counter(
        _policy_of(w) for w, _ in val_pairs
    )
    train_loser = Counter(
        _policy_of(l) for _, l in train_pairs
    )
    val_loser = Counter(
        _policy_of(l) for _, l in val_pairs
    )
    # Team hash counts.
    train_team_hashes = {r["team_hash"] for r in train_rows}
    val_team_hashes = {r["team_hash"] for r in val_rows}
    # Outcome margin per pair (winner-our_win vs
    # loser-our_win). ponytail: each pair is
    # decisive so winner.our_win=True, loser.our_win
    # =False by construction.
    return {
        "n_total_raw_rows": len(rows),
        "n_source_skipped": dict(source_skipped),
        "n_decisive_pairs": len(pairs),
        "n_skipped": dict(skipped),
        "source_distribution": dict(sources),
        "train_n_rows": len(train_rows),
        "val_n_rows": len(val_rows),
        "train_n_pairs": len(train_pairs),
        "val_n_pairs": len(val_pairs),
        "train_n_teams": len(train_team_hashes),
        "val_n_teams": len(val_team_hashes),
        "train_source_distribution": dict(train_sources),
        "val_source_distribution": dict(val_sources),
        "train_policy_distribution": dict(train_policies),
        "val_policy_distribution": dict(val_policies),
        "winner_policy_distribution": dict(winner_policies),
        "loser_policy_distribution": dict(loser_policies),
        "train_winner_policy_distribution": dict(train_winner),
        "val_winner_policy_distribution": dict(val_winner),
        "train_loser_policy_distribution": dict(train_loser),
        "val_loser_policy_distribution": dict(val_loser),
    }


# ---------------------------------------------------------------------------
# B) Split stability audit
# ---------------------------------------------------------------------------


def split_stability_audit(
    rows: List[Dict[str, Any]],
    seeds: List[int] = DEFAULT_SEEDS,
    n_epochs: int = 5,
    l2: float = 0.01,
    learning_rate: float = 0.1,
) -> Dict[str, Any]:
    """B) Run train_v3b across N seeds with the
    same group_split seed varying. Records
    train_acc, val_acc, and baseline comparisons.
    """
    feature_names = sorted(
        rows[0]["our_features"].keys()
    ) if rows else []
    pool = load_vgc_pool()
    # Cache V3 baseline per seed (2.4s each).
    v3_acc_by_seed: Dict[int, float] = {}
    for s in seeds:
        train_rows, val_rows, _ = group_split(
            rows, val_fraction=0.2, seed=s
        )
        assert_no_leakage(train_rows, val_rows)
        val_pairs, _ = build_decisive_pair_targets(
            val_rows
        )
        if val_pairs:
            v3_baseline = baseline_validate(
                val_pairs, pool
            )
            v3_acc_by_seed[s] = v3_baseline.get(
                "matchup_top4_v3", {}
            ).get("accuracy", 0.0)
        else:
            v3_acc_by_seed[s] = 0.0
    per_seed: List[Dict[str, Any]] = []
    v3_baselines_seeds: List[float] = []
    v3a1_ref_seeds: List[float] = []
    for s in seeds:
        train_rows, val_rows, _ = group_split(
            rows, val_fraction=0.2, seed=s
        )
        assert_no_leakage(train_rows, val_rows)
        train_pairs, _ = build_decisive_pair_targets(
            train_rows
        )
        val_pairs, _ = build_decisive_pair_targets(
            val_rows
        )
        if not train_pairs or not val_pairs:
            per_seed.append({
                "seed": s,
                "n_train_pairs": len(train_pairs),
                "n_val_pairs": len(val_pairs),
                "train_acc": float("nan"),
                "val_acc": float("nan"),
                "v3_baseline_acc": float("nan"),
                "beats_v3": False,
                "beats_v3a1_ref": False,
            })
            continue
        weights, bias, meta = train_v3b(
            rows, feature_names,
            n_epochs=n_epochs, learning_rate=learning_rate,
            l2=l2, seed=s, val_fraction=0.2,
        )
        train_acc = meta["train_pairwise_accuracy"]
        val_acc = meta["val_pairwise_accuracy_used"]
        v3_acc = v3_acc_by_seed.get(s, 0.0)
        v3_baselines_seeds.append(v3_acc)
        v3a1_ref_seeds.append(val_acc)
        per_seed.append({
            "seed": s,
            "n_train_pairs": len(train_pairs),
            "n_val_pairs": len(val_pairs),
            "train_acc": train_acc,
            "val_acc": val_acc,
            "v3_baseline_acc": v3_acc,
            "beats_v3": val_acc > v3_acc,
            "beats_v3a1_ref": val_acc > V3A1_REF,
        })
    val_accs = [
        s["val_acc"] for s in per_seed
        if s["val_acc"] == s["val_acc"]
    ]  # nan filter
    train_accs = [
        s["train_acc"] for s in per_seed
        if s["train_acc"] == s["train_acc"]
    ]
    beats_v3 = sum(
        1 for s in per_seed if s.get("beats_v3")
    )
    beats_v3a1 = sum(
        1 for s in per_seed if s.get("beats_v3a1_ref")
    )
    return {
        "n_seeds": len(seeds),
        "n_features": len(feature_names),
        "per_seed": per_seed,
        "val_acc_mean": (
            statistics.mean(val_accs) if val_accs else None
        ),
        "val_acc_median": (
            statistics.median(val_accs) if val_accs else None
        ),
        "val_acc_min": min(val_accs) if val_accs else None,
        "val_acc_max": max(val_accs) if val_accs else None,
        "val_acc_stdev": (
            statistics.stdev(val_accs) if len(val_accs) > 1
            else None
        ),
        "train_acc_mean": (
            statistics.mean(train_accs) if train_accs else None
        ),
        "beats_v3_count": beats_v3,
        "beats_v3_fraction": (
            beats_v3 / len(per_seed) if per_seed else 0.0
        ),
        "beats_v3a1_ref_count": beats_v3a1,
        "beats_v3a1_ref_fraction": (
            beats_v3a1 / len(per_seed) if per_seed else 0.0
        ),
        "v3a1_reference": V3A1_REF,
    }


# ---------------------------------------------------------------------------
# C) Feature scale audit
# ---------------------------------------------------------------------------


def feature_scale_audit(
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """C) Per-feature scale, variance, and weight
    contribution using a single training run
    (seed=42, default config).
    """
    feature_names = sorted(
        rows[0]["our_features"].keys()
    )
    per_feat = {}
    for fn in feature_names:
        vals = [
            r["our_features"].get(fn, 0.0) for r in rows
        ]
        mn = min(vals)
        mx = max(vals)
        mean = statistics.mean(vals)
        std = (
            statistics.stdev(vals) if len(set(vals)) > 1
            else 0.0
        )
        zero_frac = sum(1 for v in vals if v == 0.0) / len(
            vals
        )
        per_feat[fn] = {
            "min": mn,
            "max": mx,
            "mean": mean,
            "std": std,
            "zero_frac": zero_frac,
        }
    # Train with seed=42 to get weights.
    weights, bias, meta = train_v3b(
        rows, feature_names,
        n_epochs=5, l2=0.01, learning_rate=0.1,
        seed=42, val_fraction=0.2,
    )
    # Per-feature contribution: |w_i| * std_i.
    contribs = []
    for fn in feature_names:
        w = weights.get(fn, 0.0)
        std = per_feat[fn]["std"]
        contribs.append({
            "name": fn,
            "weight": w,
            "std": std,
            "abs_weight": abs(w),
            "contribution": abs(w) * std,
            "mean": per_feat[fn]["mean"],
            "zero_frac": per_feat[fn]["zero_frac"],
        })
    contribs.sort(key=lambda x: -x["contribution"])
    return {
        "n_features": len(feature_names),
        "per_feature": per_feat,
        "weight_norm": meta["weight_norm"],
        "top10_by_contribution": contribs[:10],
        "extreme_scale_features": [
            fn for fn, st in per_feat.items()
            if st["std"] == 0.0 or st["max"] > 100
        ],
    }


# ---------------------------------------------------------------------------
# D) Ablation audit
# ---------------------------------------------------------------------------


def _train_with_variant(
    rows: List[Dict[str, Any]],
    feature_filter: List[str],
    seed: int,
    l2: float,
    learning_rate: float,
    n_epochs: int,
    normalize: bool = False,
) -> Tuple[Dict[str, float], float, Dict[str, Any]]:
    """Train a V3b variant with a feature filter
    and optional z-score normalization using
    train stats only. ponytail: minimal
    per-call wrapper; no caching.
    """
    if not feature_filter:
        feature_filter = sorted(
            rows[0]["our_features"].keys()
        )
    train_rows, val_rows, _ = group_split(
        rows, val_fraction=0.2, seed=seed
    )
    assert_no_leakage(train_rows, val_rows)
    train_pairs, _ = build_decisive_pair_targets(
        train_rows
    )
    val_pairs, _ = build_decisive_pair_targets(val_rows)
    if not train_pairs or not val_pairs:
        return (
            {n: 0.0 for n in feature_filter},
            0.0,
            {
                "train_acc": float("nan"),
                "val_acc": float("nan"),
                "weight_norm": 0.0,
                "n_train_pairs": len(train_pairs),
                "n_val_pairs": len(val_pairs),
            },
        )
    # Optionally normalize train features using
    # train stats only.
    train_mean_std = {}
    if normalize:
        for fn in feature_filter:
            vals = [
                r["our_features"].get(fn, 0.0)
                for r in train_rows
            ]
            mu = statistics.mean(vals)
            sd = (
                statistics.stdev(vals)
                if len(set(vals)) > 1 else 1.0
            )
            if sd == 0:
                sd = 1.0
            train_mean_std[fn] = (mu, sd)
    def _xf(row):
        out = {}
        for fn in feature_filter:
            v = row["our_features"].get(fn, 0.0)
            if normalize:
                mu, sd = train_mean_std[fn]
                out[fn] = (v - mu) / sd
            else:
                out[fn] = v
        return out
    # Build training pairs with normalized features.
    norm_train_pairs = []
    for w, l in train_pairs:
        norm_train_pairs.append(
            ({"our_features": _xf(w)},
             {"our_features": _xf(l)})
        )
    # Train averaged perceptron on normalized data.
    weights = {n: 0.0 for n in feature_filter}
    bias = 0.0
    accumulator = {n: 0.0 for n in feature_filter}
    bias_accumulator = 0.0
    n_updates = 0
    rng = random.Random(seed)
    for _ in range(n_epochs):
        rng.shuffle(norm_train_pairs)
        for winner, loser in norm_train_pairs:
            weights, bias, accumulator, bias_accumulator = (
                averaged_pairwise_update(
                    weights, bias,
                    winner["our_features"],
                    loser["our_features"],
                    learning_rate=learning_rate, l2=l2,
                    min_margin=1.0,
                    accumulator=accumulator,
                    bias_accumulator=bias_accumulator,
                )
            )
            n_updates += 1
    if n_updates > 0:
        avg_w = {
            n: accumulator[n] / n_updates
            for n in feature_filter
        }
        avg_b = bias_accumulator / n_updates
    else:
        avg_w = dict(weights)
        avg_b = bias
    # Build val pairs with normalization.
    norm_val_pairs = []
    for w, l in val_pairs:
        norm_val_pairs.append(
            ({"our_features": _xf(w)},
             {"our_features": _xf(l)})
        )
    train_acc = _pairwise_accuracy(
        avg_w, avg_b, norm_train_pairs
    )
    val_acc = _pairwise_accuracy(
        avg_w, avg_b, norm_val_pairs
    )
    weight_norm = sum(v * v for v in avg_w.values()) ** 0.5
    return (
        avg_w,
        avg_b,
        {
            "train_acc": train_acc,
            "val_acc": val_acc,
            "weight_norm": weight_norm,
            "n_train_pairs": len(train_pairs),
            "n_val_pairs": len(val_pairs),
            "n_features": len(feature_filter),
        },
    )


def ablation_audit(
    rows: List[Dict[str, Any]],
    seeds: List[int] = DEFAULT_SEEDS,
) -> Dict[str, Any]:
    """D) Variant x seed grid. ponytail: 6 variants
    x 30 seeds x small L2 grid. Uses stdlib.
    """
    all_features = sorted(
        rows[0]["our_features"].keys()
    )
    delta_features = [f for f in all_features
                      if f.startswith("delta_")]
    base_features = [f for f in all_features
                     if not f.startswith("delta_")]
    matchup_features = [
        f for f in base_features if (
            f.startswith("lead_off_")
            or f.startswith("lead_def_")
            or f.startswith("back_")
            or f.startswith("opp_")
        )
    ]
    # L2 grid.
    l2_grid = [0.0, 0.001, 0.01, 0.1]
    variants = []
    variants.append({
        "name": "all_features",
        "features": all_features,
        "normalize": False,
        "l2_grid": l2_grid,
    })
    variants.append({
        "name": "no_deltas",
        "features": base_features,
        "normalize": False,
        "l2_grid": l2_grid,
    })
    variants.append({
        "name": "only_deltas",
        "features": delta_features,
        "normalize": False,
        "l2_grid": l2_grid,
    })
    variants.append({
        "name": "matchup_only",
        "features": matchup_features,
        "normalize": False,
        "l2_grid": l2_grid,
    })
    variants.append({
        "name": "all_features_normalized",
        "features": all_features,
        "normalize": True,
        "l2_grid": l2_grid,
    })
    pool = load_vgc_pool()
    # Cache V3 baseline per seed (2.4s each). ponytail:
    # 30 seeds * 5 variants * 4 L2 = 600 calls becomes
    # 30 calls.
    v3_acc_by_seed: Dict[int, float] = {}
    for s in seeds:
        train_rows, val_rows, _ = group_split(
            rows, val_fraction=0.2, seed=s
        )
        assert_no_leakage(train_rows, val_rows)
        val_pairs, _ = build_decisive_pair_targets(
            val_rows
        )
        if val_pairs:
            v3_baseline = baseline_validate(val_pairs, pool)
            v3_acc_by_seed[s] = v3_baseline.get(
                "matchup_top4_v3", {}
            ).get("accuracy", 0.0)
        else:
            v3_acc_by_seed[s] = 0.0
    variant_results = []
    for v in variants:
        for l2 in v["l2_grid"]:
            per_seed = []
            for s in seeds:
                _w, _b, meta = _train_with_variant(
                    rows, v["features"],
                    seed=s, l2=l2,
                    learning_rate=0.1, n_epochs=5,
                    normalize=v["normalize"],
                )
                per_seed.append({
                    "seed": s,
                    **meta,
                    "v3_baseline_acc": v3_acc_by_seed.get(
                        s, 0.0
                    ),
                })
            val_accs = [
                p["val_acc"] for p in per_seed
                if p["val_acc"] == p["val_acc"]
            ]
            train_accs = [
                p["train_acc"] for p in per_seed
                if p["train_acc"] == p["train_acc"]
            ]
            gap_vals = [
                p["train_acc"] - p["val_acc"]
                for p in per_seed
                if (
                    p["train_acc"] == p["train_acc"]
                    and p["val_acc"] == p["val_acc"]
                )
            ]
            variant_results.append({
                "name": v["name"],
                "l2": l2,
                "normalize": v["normalize"],
                "n_features": len(v["features"]),
                "val_acc_mean": (
                    statistics.mean(val_accs)
                    if val_accs else None
                ),
                "val_acc_median": (
                    statistics.median(val_accs)
                    if val_accs else None
                ),
                "val_acc_min": (
                    min(val_accs) if val_accs else None
                ),
                "val_acc_max": (
                    max(val_accs) if val_accs else None
                ),
                "val_acc_stdev": (
                    statistics.stdev(val_accs)
                    if len(val_accs) > 1 else None
                ),
                "train_acc_mean": (
                    statistics.mean(train_accs)
                    if train_accs else None
                ),
                "overfit_gap_mean": (
                    statistics.mean(gap_vals)
                    if gap_vals else None
                ),
                "beats_v3_fraction": None,  # filled below
                "beats_v3a1_ref_fraction": None,
                "per_seed": per_seed,
            })
    # Compute beats_v3 fraction per variant.
    for vr in variant_results:
        v3_beats = 0
        v3a1_beats = 0
        valid = 0
        for p in vr["per_seed"]:
            v3_acc = (
                p.get("v3_baseline_acc")
                if p.get("v3_baseline_acc")
                == p.get("v3_baseline_acc")
                else None
            )
            if v3_acc is None:
                continue
            valid += 1
            if p["val_acc"] > v3_acc:
                v3_beats += 1
            if p["val_acc"] > V3A1_REF:
                v3a1_beats += 1
        vr["beats_v3_fraction"] = (
            v3_beats / valid if valid else None
        )
        vr["beats_v3a1_ref_fraction"] = (
            v3a1_beats / valid if valid else None
        )
    return {
        "n_seeds": len(seeds),
        "n_variants": len(variant_results),
        "n_features_total": len(all_features),
        "variants": variant_results,
    }


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------


def recommend(
    data_audit: Dict[str, Any],
    split_audit: Dict[str, Any],
    ablation: Dict[str, Any],
) -> Dict[str, Any]:
    """Choose one recommendation based on the
    audit and ablation.
    """
    val_mean = split_audit.get("val_acc_mean")
    val_median = split_audit.get("val_acc_median")
    val_beats_v3 = split_audit.get("beats_v3_fraction", 0.0)
    # Find the best variant by mean val_acc that
    # also beats V3 on >= 80% of splits.
    best_variant = None
    for vr in ablation.get("variants", []):
        if vr["val_acc_mean"] is None:
            continue
        if vr["val_acc_mean"] >= GO_MEAN_MEDIAN_THRESHOLD:
            if (
                vr["val_acc_median"]
                and vr["val_acc_median"]
                >= GO_MEAN_MEDIAN_THRESHOLD
            ):
                if (
                    vr.get("beats_v3_fraction") or 0
                ) >= GO_V3_BEAT_FRACTION:
                    if (
                        best_variant is None
                        or vr["val_acc_mean"]
                        > best_variant["val_acc_mean"]
                    ):
                        best_variant = vr
    # Decision tree.
    if best_variant is not None:
        if best_variant["name"] == "all_features_normalized":
            return {
                "decision": "GO_NORMALIZED_RETRAIN",
                "reason": (
                    f"normalized variant beats V3 on "
                    f"{best_variant.get('beats_v3_fraction'):.0%} "
                    f"of splits with mean val_acc "
                    f"{best_variant['val_acc_mean']:.3f}"
                ),
                "best_variant": best_variant,
            }
        if best_variant["name"] in (
            "no_deltas", "matchup_only"
        ):
            return {
                "decision": "GO_FEATURE_PRUNE",
                "reason": (
                    f"{best_variant['name']} variant beats "
                    f"V3 on "
                    f"{best_variant.get('beats_v3_fraction'):.0%} "
                    f"of splits with mean val_acc "
                    f"{best_variant['val_acc_mean']:.3f}"
                ),
                "best_variant": best_variant,
            }
    # Label-quality check: if winners are dominated
    # by random/basic.
    winner_pols = data_audit.get(
        "winner_policy_distribution", {}
    )
    total_w = sum(winner_pols.values()) or 1
    weak_w = sum(
        v for k, v in winner_pols.items()
        if k in ("random", "basic_top4", "?")
    ) / total_w
    if weak_w > 0.5:
        return {
            "decision": "BLOCK_LABEL_QUALITY",
            "reason": (
                f"{weak_w:.0%} of decisive winners used "
                f"random/basic/? — labels are dominated "
                f"by weak policies"
            ),
        }
    if (
        val_mean is None
        or val_mean < GO_MEAN_MEDIAN_THRESHOLD
    ):
        return {
            "decision": "BLOCK_MORE_DATA",
            "reason": (
                f"val_acc mean {val_mean} below "
                f"GO threshold "
                f"{GO_MEAN_MEDIAN_THRESHOLD}"
            ),
        }
    return {
        "decision": "BLOCK_MODEL_CLASS",
        "reason": (
            f"val mean {val_mean} meets threshold but "
            f"no variant beats V3 on "
            f">{GO_V3_BEAT_FRACTION:.0%} of splits "
            f"(actual {val_beats_v3:.0%})"
        ),
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def render_data_audit_md(audit: Dict[str, Any]) -> str:
    lines = [
        "# Phase V3b.1 — Data / Label Audit",
        "",
        f"- n_total_raw_rows: {audit['n_total_raw_rows']}",
        f"- n_decisive_pairs: {audit['n_decisive_pairs']}",
        f"- n_source_skipped: {audit['n_source_skipped']}",
        f"- n_skipped: {audit['n_skipped']}",
        f"- train_n_rows: {audit['train_n_rows']}",
        f"- val_n_rows: {audit['val_n_rows']}",
        f"- train_n_pairs: {audit['train_n_pairs']}",
        f"- val_n_pairs: {audit['val_n_pairs']}",
        f"- train_n_teams: {audit['train_n_teams']}",
        f"- val_n_teams: {audit['val_n_teams']}",
        "",
        "## Source distribution (full)",
        "",
        "| source | count |",
        "|---|---:|",
    ]
    for k, v in sorted(
        audit["source_distribution"].items(),
        key=lambda x: -x[1],
    ):
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "## Source distribution (train vs val)",
        "",
        "| source | train | val |",
        "|---|---:|---:|",
    ]
    all_sources = set(
        audit["train_source_distribution"]
    ) | set(audit["val_source_distribution"])
    for s in sorted(all_sources):
        lines.append(
            f"| {s} | "
            f"{audit['train_source_distribution'].get(s, 0)} | "
            f"{audit['val_source_distribution'].get(s, 0)} |"
        )
    lines += [
        "",
        "## Winner policy distribution (decisive pairs)",
        "",
        "| policy | count |",
        "|---|---:|",
    ]
    for k, v in sorted(
        audit["winner_policy_distribution"].items(),
        key=lambda x: -x[1],
    ):
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "## Loser policy distribution (decisive pairs)",
        "",
        "| policy | count |",
        "|---|---:|",
    ]
    for k, v in sorted(
        audit["loser_policy_distribution"].items(),
        key=lambda x: -x[1],
    ):
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)


def render_split_stability_md(
    audit: Dict[str, Any]
) -> str:
    lines = [
        "# Phase V3b.1 — Split Stability Audit",
        "",
        f"- n_seeds: {audit['n_seeds']}",
        f"- n_features: {audit['n_features']}",
        (
            f"- val_acc mean: "
            f"{audit['val_acc_mean']:.3f}"
            if audit["val_acc_mean"] is not None
            else "- val_acc mean: n/a"
        ),
        (
            f"- val_acc median: "
            f"{audit['val_acc_median']:.3f}"
            if audit["val_acc_median"] is not None
            else "- val_acc median: n/a"
        ),
        (
            f"- val_acc min/max: "
            f"{audit['val_acc_min']:.3f} / "
            f"{audit['val_acc_max']:.3f}"
            if audit["val_acc_min"] is not None
            else "- val_acc min/max: n/a"
        ),
        (
            f"- val_acc stdev: "
            f"{audit['val_acc_stdev']:.3f}"
            if audit["val_acc_stdev"] is not None
            else "- val_acc stdev: n/a"
        ),
        (
            f"- train_acc mean: "
            f"{audit['train_acc_mean']:.3f}"
            if audit["train_acc_mean"] is not None
            else "- train_acc mean: n/a"
        ),
        (
            f"- beats V3 on {audit['beats_v3_count']} / "
            f"{audit['n_seeds']} seeds "
            f"({audit['beats_v3_fraction']:.0%})"
        ),
        (
            f"- beats V3a.1 ref {audit['v3a1_reference']:.2f} "
            f"on {audit['beats_v3a1_ref_count']} / "
            f"{audit['n_seeds']} seeds "
            f"({audit['beats_v3a1_ref_fraction']:.0%})"
        ),
        "",
        "## Per-seed",
        "",
        "| seed | n_train | n_val | train_acc | val_acc "
        "| v3_baseline | beats_v3 | beats_v3a1_ref |",
        "|---:|---:|---:|---:|---:|---:|:-:|:-:|",
    ]
    for p in audit["per_seed"]:
        v3_acc = p.get("v3_baseline_acc", float("nan"))
        lines.append(
            f"| {p['seed']} | {p.get('n_train_pairs', '?')} "
            f"| {p.get('n_val_pairs', '?')} "
            f"| {p.get('train_acc', float('nan')):.3f} "
            f"| {p.get('val_acc', float('nan')):.3f} "
            f"| {v3_acc:.3f} "
            f"| {'Y' if p.get('beats_v3') else 'N'} "
            f"| {'Y' if p.get('beats_v3a1_ref') else 'N'} |"
        )
    return "\n".join(lines)


def render_ablation_md(audit: Dict[str, Any]) -> str:
    lines = [
        "# Phase V3b.1 — Ablation Audit",
        "",
        f"- n_seeds: {audit['n_seeds']}",
        f"- n_variants: {audit['n_variants']}",
        f"- n_features_total: {audit['n_features_total']}",
        "",
        "| variant | l2 | normalize | n_features "
        "| val_mean | val_median | val_min | val_max "
        "| train_mean | overfit_gap | beats_v3 | beats_v3a1_ref |",
        "|---|---:|:-:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for vr in audit["variants"]:
        lines.append(
            f"| {vr['name']} | {vr['l2']} "
            f"| {'Y' if vr['normalize'] else 'N'} "
            f"| {vr['n_features']} "
            f"| {vr['val_acc_mean']:.3f} "
            f"| {vr['val_acc_median']:.3f} "
            f"| {vr['val_acc_min']:.3f} "
            f"| {vr['val_acc_max']:.3f} "
            f"| {vr['train_acc_mean']:.3f} "
            f"| {vr['overfit_gap_mean']:.3f} "
            f"| {vr['beats_v3_fraction']:.0%} "
            f"| {vr['beats_v3a1_ref_fraction']:.0%} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Phase V3b.1 diagnostic audit."
    )
    parser.add_argument(
        "--sources",
        type=str,
        default=DEFAULT_V3A1_SOURCES,
    )
    parser.add_argument(
        "--n-seeds",
        type=int,
        default=30,
    )
    parser.add_argument(
        "--data-json",
        type=str,
        default=DATA_AUDIT_JSON,
    )
    parser.add_argument(
        "--data-md",
        type=str,
        default=DATA_AUDIT_MD,
    )
    parser.add_argument(
        "--split-json",
        type=str,
        default=SPLIT_STABILITY_JSON,
    )
    parser.add_argument(
        "--split-md",
        type=str,
        default=SPLIT_STABILITY_MD,
    )
    parser.add_argument(
        "--ablation-json",
        type=str,
        default=ABLATION_JSON,
    )
    parser.add_argument(
        "--ablation-md",
        type=str,
        default=ABLATION_MD,
    )
    parser.add_argument(
        "--skip-ablation",
        action="store_true",
        help="Skip the slow ablation grid.",
    )
    args = parser.parse_args()
    sources = [s for s in args.sources.split(",") if s]
    pool = load_vgc_pool()
    rows, _ = _load_v3b_rows(sources, pool)
    if not rows:
        print("No rows; aborting.")
        return 1
    seeds = list(range(args.n_seeds))
    print("=" * 60)
    print("A) Data / label audit")
    print("=" * 60)
    data = dataset_audit(sources, pool)
    print(
        f"n_total={data['n_total_raw_rows']} "
        f"pairs={data['n_decisive_pairs']} "
        f"train_pairs={data['train_n_pairs']} "
        f"val_pairs={data['val_n_pairs']}"
    )
    os.makedirs(
        os.path.dirname(args.data_json) or ".", exist_ok=True
    )
    with open(args.data_json, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    with open(args.data_md, "w") as f:
        f.write(render_data_audit_md(data))
    print("=" * 60)
    print("B) Split stability audit")
    print("=" * 60)
    split = split_stability_audit(
        rows, seeds=seeds
    )
    print(
        f"val mean={split['val_acc_mean']:.3f} "
        f"median={split['val_acc_median']:.3f} "
        f"min={split['val_acc_min']:.3f} "
        f"max={split['val_acc_max']:.3f}"
    )
    print(
        f"beats_v3: {split['beats_v3_count']}/"
        f"{split['n_seeds']} "
        f"({split['beats_v3_fraction']:.0%})"
    )
    with open(args.split_json, "w") as f:
        json.dump(split, f, indent=2, sort_keys=True)
    with open(args.split_md, "w") as f:
        f.write(render_split_stability_md(split))
    print("=" * 60)
    print("C) Feature scale audit")
    print("=" * 60)
    scale = feature_scale_audit(rows)
    print(
        f"top-3 by contribution: "
        f"{[(c['name'], c['contribution']) for c in scale['top10_by_contribution'][:3]]}"
    )
    print(
        f"extreme_scale: {len(scale['extreme_scale_features'])}"
    )
    with open(
        args.split_json.replace(
            "split_stability.json", "feature_scale.json"
        ), "w"
    ) as f:
        json.dump(scale, f, indent=2, sort_keys=True)
    if not args.skip_ablation:
        print("=" * 60)
        print("D) Ablation audit")
        print("=" * 60)
        abl = ablation_audit(rows, seeds=seeds)
        with open(args.ablation_json, "w") as f:
            json.dump(abl, f, indent=2, sort_keys=True)
        with open(args.ablation_md, "w") as f:
            f.write(render_ablation_md(abl))
    rec = recommend(data, split, abl if not args.skip_ablation else {})
    print("=" * 60)
    print("Recommendation")
    print("=" * 60)
    print(f"decision: {rec['decision']}")
    print(f"reason: {rec['reason']}")
    rec_path = (
        args.split_json.replace(
            "split_stability.json", "recommendation.json"
        )
    )
    with open(rec_path, "w") as f:
        json.dump(rec, f, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
