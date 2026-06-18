#!/usr/bin/env python3
"""Phase V3c.1 — train VGC learned-preview model on
the V3c dataset.

Ponytail: small focused module. Reuses V3b feature
extraction and the V3a.1 averaged pairwise perceptron.
No new ML framework. Reuses the V3b.1 ablation grid
infrastructure.

Goal: train a V3c.1 model on the V3c dataset and
apply training gates from the V3c.1 spec. If gates
pass, save the model artifact and add an opt-in
``learned_preview_v3c1`` wrapper. Default policy
``matchup_top4_v3`` is unchanged either way.

No battles. No localhost. No new online API.
"""
import argparse
import hashlib
import json
import os
import random
import statistics
import sys
from collections import Counter
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vgc2026_phaseV3a_learn_preview import (
    _pairwise_accuracy,
    _stable_team_hash,
    assert_no_leakage,
    averaged_pairwise_update,
    baseline_validate,
    group_split,
    save_model,
)
from vgc2026_phaseV3b_opponent_features import (
    v3b_features_for_plan,
)
from vgc2026_phaseV3b_train import (
    V3A1_VAL_ACC_REFERENCE,
)
from vgc_team_pool import load_vgc_pool


# ---------------------------------------------------------------------------
# Artifact paths
# ---------------------------------------------------------------------------

V3C1_MODEL_PATH = "logs/vgc2026_phaseV3c1_model.json"
V3C1_REPORT_JSON = "logs/vgc2026_phaseV3c1_training_report.json"
V3C1_REPORT_MD = "logs/vgc2026_phaseV3c1_training_report.md"
V3C1_FEATURE_SCALE = "logs/vgc2026_phaseV3c1_feature_scale.json"
V3C1_SPLIT_STABILITY = (
    "logs/vgc2026_phaseV3c1_split_stability.json"
)

V3C_PAIRING_FILES = [
    "logs/vgc2026_phaseV3c_preview_dataset25_"
    "learned_preview_v3a1_vs_matchup_top4_v3.jsonl",
    "logs/vgc2026_phaseV3c_preview_dataset25_"
    "basic_top4_vs_matchup_top4_v3.jsonl",
    "logs/vgc2026_phaseV3c_preview_dataset25_"
    "basic_top4_vs_learned_preview_v3a1.jsonl",
    "logs/vgc2026_phaseV3c_preview_dataset25_"
    "matchup_top4_v3_vs_random.jsonl",
    "logs/vgc2026_phaseV3c_preview_dataset25_"
    "learned_preview_v3a1_vs_random.jsonl",
    "logs/vgc2026_phaseV3c_preview_dataset25_"
    "basic_top4_vs_random.jsonl",
]

# Training gates from the V3c.1 spec.
GATE_MEAN_VAL = 0.60
GATE_MEDIAN_VAL = 0.60
GATE_BEATS_V3_FRACTION = 0.80
GATE_BEATS_LEARNED_FRACTION = 0.60
GATE_OVERFIT_GAP = 0.20
GATE_FEATURE_DOMINANCE = 0.35
GATE_MIN_VAL_DECISIVE = 10


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_v3c_pairing(
    jsonl_path: str, team_pool: Any
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Load one V3c pairing jsonl. Each row gets:
    - our_team: looked up from pair_id % len(pool)
    - opponent_team: same lookup (the V3a.2 runner
      uses the same team on both sides)
    - our_features: V3b features
    - pair_id, side, our_policy, opponent_policy
    - team_hash, opponent_team_hash
    - source: jsonl basename
    """
    rows: List[Dict[str, Any]] = []
    skipped: Dict[str, int] = {}
    if not os.path.isfile(jsonl_path):
        skipped["missing_file"] = 1
        return rows, skipped
    source = os.path.basename(jsonl_path)
    pool_size = len(team_pool)
    with open(jsonl_path) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                skipped["malformed"] = (
                    skipped.get("malformed", 0) + 1
                )
                continue
            pair_id = rec.get("pair_id")
            if pair_id is None:
                skipped["missing_pair_id"] = (
                    skipped.get("missing_pair_id", 0) + 1
                )
                continue
            team_idx = pair_id % pool_size
            team_row = team_pool.get_team(team_idx)
            if team_row is None:
                skipped["team_lookup_failed"] = (
                    skipped.get("team_lookup_failed", 0) + 1
                )
                continue
            our_team = team_row.pokemon
            opp_team = our_team  # V3a.2 runner uses
            # the same team on both sides
            try:
                features = v3b_features_for_plan(
                    our_team,
                    rec.get("our_chosen_4", []),
                    rec.get("our_lead_2", []),
                    rec.get("our_back_2", []),
                    opp_team,
                )
            except Exception:
                skipped["feature_extraction_failed"] = (
                    skipped.get(
                        "feature_extraction_failed", 0
                    ) + 1
                )
                continue
            if not features:
                skipped["empty_features"] = (
                    skipped.get("empty_features", 0) + 1
                )
                continue
            rows.append({
                "pair_id": pair_id,
                "side": rec.get("side"),
                "our_policy": rec.get("our_policy", ""),
                "opponent_policy": rec.get(
                    "opponent_policy", ""
                ),
                "our_chosen_4": rec.get("our_chosen_4", []),
                "our_lead_2": rec.get("our_lead_2", []),
                "our_back_2": rec.get("our_back_2", []),
                "opp_chosen_4": rec.get("opp_chosen_4", []),
                "opp_lead_2": rec.get("opp_lead_2", []),
                "opp_back_2": rec.get("opp_back_2", []),
                "our_win": rec.get("our_win"),
                "status": rec.get("status"),
                "turns": rec.get("turns"),
                "our_team": our_team,
                "opponent_team": opp_team,
                "team_hash": _stable_team_hash(our_team),
                "opponent_team_hash": _stable_team_hash(
                    opp_team
                ),
                "source": source,
                "our_features": dict(features),
            })
    return rows, skipped


def _load_all_v3c_rows(
    jsonl_paths: List[str], team_pool: Any
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Load all V3c pairings, validate, return
    concatenated rows plus validation report.
    """
    all_rows: List[Dict[str, Any]] = []
    skipped_total: Dict[str, int] = {}
    validation = {
        "n_files_expected": len(jsonl_paths),
        "n_files_loaded": 0,
        "files_missing": [],
    }
    for p in jsonl_paths:
        if not os.path.isfile(p):
            validation["files_missing"].append(p)
            continue
        rows, skipped = _load_v3c_pairing(p, team_pool)
        all_rows.extend(rows)
        for k, v in skipped.items():
            skipped_total[k] = skipped_total.get(k, 0) + v
        validation["n_files_loaded"] += 1
    return all_rows, {
        "validation": validation,
        "skipped": skipped_total,
    }


# ---------------------------------------------------------------------------
# Decisive pair extraction (per pairing)
# ---------------------------------------------------------------------------


def _build_decisive_pairs_per_pairing(
    rows: List[Dict[str, Any]],
) -> Tuple[List[Tuple[Dict[str, Any], Dict[str, Any]]],
           Dict[str, int]]:
    """For each (pairing, pair_id, team_hash), build
    a (winner, loser) pair only if the pair is
    decisive (one policy won both sides).

    Skipped:
      - single_policy: only one policy in the pair
      - tied_or_split: each policy won one side
      - identical_plans: same chosen_4

    Layout: D1 has policy_a as p1, policy_b as
    p2. D2 has policy_b as p1, policy_a as p2.
    So a_d1 = d1["our_win"] and a_d2 = not
    d2["our_win"]. a_both means a won both D1
    and D2. b_both means b won both D1 and D2.
    """
    skipped: Dict[str, int] = {}
    by_group: Dict[Tuple, List[Dict[str, Any]]] = {}
    for r in rows:
        key = (
            r.get("source"),
            r.get("pair_id"),
            r.get("team_hash"),
        )
        by_group.setdefault(key, []).append(r)
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for key, group in by_group.items():
        policies = {r.get("our_policy", "") for r in group}
        policies.discard("")
        if len(policies) < 2:
            skipped["single_policy"] = (
                skipped.get("single_policy", 0) + 1
            )
            continue
        d1 = next(
            (r for r in group if r.get("side") == "p1"),
            None,
        )
        d2 = next(
            (r for r in group if r.get("side") == "p2"),
            None,
        )
        if d1 is None or d2 is None:
            skipped["incomplete_sides"] = (
                skipped.get("incomplete_sides", 0) + 1
            )
            continue
        d1_win = d1.get("our_win")
        d2_win = d2.get("our_win")
        if d1_win is None or d2_win is None:
            skipped["missing_our_win"] = (
                skipped.get("missing_our_win", 0) + 1
            )
            continue
        d1_our_pol = d1.get("our_policy", "")
        d1_opp_pol = d1.get("opponent_policy", "")
        d2_our_pol = d2.get("our_policy", "")
        d2_opp_pol = d2.get("opponent_policy", "")
        # a_d1 = d1_our_pol won D1 = d1_win
        # a_d2 = d2_opp_pol won D2 = (not d2_win)
        # b_d1 = d1_opp_pol won D1 = (not d1_win)
        # b_d2 = d2_our_pol won D2 = d2_win
        a_d1 = bool(d1_win)
        a_d2 = not bool(d2_win)
        b_d1 = not bool(d1_win)
        b_d2 = bool(d2_win)
        if a_d1 and a_d2:
            winner_pol = d1_our_pol
            loser_pol = d2_our_pol
        elif b_d1 and b_d2:
            winner_pol = d1_opp_pol
            loser_pol = d2_opp_pol
        else:
            skipped["tied_or_split"] = (
                skipped.get("tied_or_split", 0) + 1
            )
            continue
        winner_row = next(
            (r for r in group if r.get("our_policy")
             == winner_pol),
            None,
        )
        loser_row = next(
            (r for r in group if r.get("our_policy")
             == loser_pol),
            None,
        )
        if winner_row is None or loser_row is None:
            skipped["missing_winner_or_loser_row"] = (
                skipped.get(
                    "missing_winner_or_loser_row", 0
                ) + 1
            )
            continue
        if (
            sorted(s.lower() for s in
                   winner_row.get("our_chosen_4", []))
            == sorted(s.lower() for s in
                      loser_row.get("our_chosen_4", []))
        ):
            skipped["identical_plans"] = (
                skipped.get("identical_plans", 0) + 1
            )
            continue
        pairs.append((winner_row, loser_row))
    return pairs, skipped


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_v3c_dataset(
    rows: List[Dict[str, Any]],
    file_validation: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate the loaded V3c rows. Returns a
    validation report.
    """
    n_battles = len(rows)
    n_pairs = len({r["pair_id"] for r in rows})
    n_status_ok = sum(
        1 for r in rows if r.get("status") == "ok"
    )
    n_bad = n_battles - n_status_ok
    # All battles have selected_four=4, lead_2=2,
    # back_2=2.
    n_ch4_ok = sum(
        1 for r in rows
        if len(r.get("our_chosen_4", [])) == 4
    )
    n_l2_ok = sum(
        1 for r in rows
        if len(r.get("our_lead_2", [])) == 2
    )
    n_b2_ok = sum(
        1 for r in rows
        if len(r.get("our_back_2", [])) == 2
    )
    # Battle tags.
    tags = [r.get("source", "") for r in rows]
    sources = Counter(tags)
    return {
        "n_battles": n_battles,
        "n_unique_pair_ids": n_pairs,
        "n_status_ok": n_status_ok,
        "n_status_bad": n_bad,
        "n_chosen_4_ok": n_ch4_ok,
        "n_lead_2_ok": n_l2_ok,
        "n_back_2_ok": n_b2_ok,
        "n_sources": dict(sources),
        "file_validation": file_validation,
    }


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def _train_perceptron(
    train_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]],
    feature_names: List[str],
    n_epochs: int = 5,
    learning_rate: float = 0.1,
    l2: float = 0.01,
    seed: int = 42,
) -> Tuple[Dict[str, float], float, Dict[str, Any]]:
    """Train averaged perceptron. Returns
    (weights, bias, meta). ponytail: same as
    V3a.1's averaged_pairwise_update.
    """
    weights = {n: 0.0 for n in feature_names}
    bias = 0.0
    accumulator = {n: 0.0 for n in feature_names}
    bias_accumulator = 0.0
    n_updates = 0
    rng = random.Random(seed)
    for _ in range(n_epochs):
        rng.shuffle(train_pairs)
        for winner, loser in train_pairs:
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
            for n in feature_names
        }
        avg_b = bias_accumulator / n_updates
    else:
        avg_w = dict(weights)
        avg_b = bias
    return avg_w, avg_b, {
        "n_updates": n_updates,
        "n_train_pairs": len(train_pairs),
    }


def _score_baselines_on_pairs(
    val_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]],
    team_pool: Any,
) -> Dict[str, float]:
    """Compute baseline accuracy (V3, learned, basic,
    random, common_total) on the val pairs.
    ponytail: reuses V3a.1 baseline_validate.
    """
    if not val_pairs:
        return {}
    raw = baseline_validate(val_pairs, team_pool)
    return {
        k: v.get("accuracy", 0.0)
        for k, v in raw.items()
        if isinstance(v, dict) and "accuracy" in v
    }


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------


def _split_by_pairing(
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]],
    val_fraction: float = 0.2,
    seed: int = 42,
) -> Tuple[List, List]:
    """Pairing-stratified split: each pairing
    contributes train/val. ponytail: simple
    per-pairing shuffle.
    """
    by_source: Dict[str, List] = {}
    for p in pairs:
        s = p[0].get("source", "?")
        by_source.setdefault(s, []).append(p)
    train: List = []
    val: List = []
    rng = random.Random(seed)
    for s, group in by_source.items():
        shuffled = list(group)
        rng.shuffle(shuffled)
        n_val = max(1, int(len(shuffled) * val_fraction))
        val.extend(shuffled[:n_val])
        train.extend(shuffled[n_val:])
    rng.shuffle(train)
    rng.shuffle(val)
    return train, val


def _group_split_pairs(
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]],
    val_fraction: float = 0.2,
    seed: int = 42,
) -> Tuple[List, List]:
    """Group split by team_hash so train and val
    share no team. ponytail: per-pair team_hash
    extraction.
    """
    by_team: Dict[str, List] = {}
    for p in pairs:
        # Both winner and loser are from the same
        # team (same pair_id). Use the winner's
        # team_hash.
        th = p[0].get("team_hash", "")
        by_team.setdefault(th, []).append(p)
    team_hashes = sorted(by_team.keys())
    rng = random.Random(seed)
    rng.shuffle(team_hashes)
    n_val = max(1, int(len(team_hashes) * val_fraction))
    val_hashes = set(team_hashes[:n_val])
    train: List = []
    val: List = []
    for th, group in by_team.items():
        if th in val_hashes:
            val.extend(group)
        else:
            train.extend(group)
    return train, val


# ---------------------------------------------------------------------------
# Stability
# ---------------------------------------------------------------------------


def _stability(
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]],
    feature_names: List[str],
    seeds: List[int],
    team_pool: Any,
) -> Dict[str, Any]:
    """Run group_split training across multiple
    seeds. Records per-seed val_acc and baseline
    comparisons.
    """
    per_seed: List[Dict[str, Any]] = []
    v3_baseline_accs: List[float] = []
    learned_baseline_accs: List[float] = []
    val_accs: List[float] = []
    for s in seeds:
        train, val = _group_split_pairs(
            pairs, val_fraction=0.2, seed=s
        )
        if not train or not val:
            continue
        w, b, _ = _train_perceptron(
            train, feature_names,
            n_epochs=5, learning_rate=0.1, l2=0.01,
            seed=s,
        )
        val_acc = _pairwise_accuracy(w, b, val)
        train_acc = _pairwise_accuracy(w, b, train)
        baselines = _score_baselines_on_pairs(val, team_pool)
        v3_acc = baselines.get("matchup_top4_v3", 0.0)
        learned_acc = baselines.get(
            "learned_preview_v3a1", 0.0
        )
        v3_baseline_accs.append(v3_acc)
        learned_baseline_accs.append(learned_acc)
        val_accs.append(val_acc)
        per_seed.append({
            "seed": s,
            "n_train_pairs": len(train),
            "n_val_pairs": len(val),
            "train_acc": train_acc,
            "val_acc": val_acc,
            "v3_baseline_acc": v3_acc,
            "learned_baseline_acc": learned_acc,
            "beats_v3": val_acc > v3_acc,
            "beats_learned": val_acc > learned_acc,
        })
    if not val_accs:
        return {
            "n_seeds": len(seeds),
            "per_seed": per_seed,
            "val_acc_mean": None,
            "val_acc_median": None,
            "val_acc_min": None,
            "val_acc_max": None,
            "val_acc_stdev": None,
            "train_acc_mean": None,
            "overfit_gap_mean": None,
            "beats_v3_count": 0,
            "beats_v3_fraction": 0.0,
            "beats_learned_count": 0,
            "beats_learned_fraction": 0.0,
        }
    train_accs = [
        s["train_acc"] for s in per_seed
    ]
    beats_v3 = sum(1 for s in per_seed if s["beats_v3"])
    beats_learned = sum(
        1 for s in per_seed if s["beats_learned"]
    )
    gaps = [
        s["train_acc"] - s["val_acc"] for s in per_seed
    ]
    return {
        "n_seeds": len(seeds),
        "per_seed": per_seed,
        "val_acc_mean": statistics.mean(val_accs),
        "val_acc_median": statistics.median(val_accs),
        "val_acc_min": min(val_accs),
        "val_acc_max": max(val_accs),
        "val_acc_stdev": (
            statistics.stdev(val_accs)
            if len(val_accs) > 1 else None
        ),
        "train_acc_mean": (
            statistics.mean(train_accs) if train_accs else None
        ),
        "overfit_gap_mean": (
            statistics.mean(gaps) if gaps else None
        ),
        "beats_v3_count": beats_v3,
        "beats_v3_fraction": (
            beats_v3 / len(per_seed) if per_seed else 0.0
        ),
        "beats_learned_count": beats_learned,
        "beats_learned_fraction": (
            beats_learned / len(per_seed) if per_seed else 0.0
        ),
    }


# ---------------------------------------------------------------------------
# Feature scale
# ---------------------------------------------------------------------------


def _feature_scale(
    rows: List[Dict[str, Any]],
    weights: Dict[str, float],
) -> Dict[str, Any]:
    """Per-feature mean/std/zero_frac + weight
    contribution.
    """
    feature_names = sorted(
        rows[0]["our_features"].keys()
    )
    per_feat = {}
    for fn in feature_names:
        vals = [
            r["our_features"].get(fn, 0.0) for r in rows
        ]
        mean = statistics.mean(vals)
        std = (
            statistics.stdev(vals) if len(set(vals)) > 1
            else 0.0
        )
        zero_frac = sum(1 for v in vals if v == 0.0) / len(
            vals
        )
        per_feat[fn] = {
            "min": min(vals),
            "max": max(vals),
            "mean": mean,
            "std": std,
            "zero_frac": zero_frac,
        }
    contribs = []
    total_abs = 0.0
    for fn in feature_names:
        w = weights.get(fn, 0.0)
        std = per_feat[fn]["std"]
        c = abs(w) * std
        total_abs += c
        contribs.append({
            "name": fn,
            "weight": w,
            "std": std,
            "contribution": c,
        })
    if total_abs > 0:
        for c in contribs:
            c["contribution_share"] = c["contribution"] / total_abs
    else:
        for c in contribs:
            c["contribution_share"] = 0.0
    contribs.sort(key=lambda x: -x["contribution"])
    return {
        "n_features": len(feature_names),
        "per_feature": per_feat,
        "top10_by_contribution": contribs[:10],
        "max_contribution_share": max(
            (c["contribution_share"] for c in contribs),
            default=0.0,
        ),
        "dominant_feature": (
            contribs[0]["name"] if contribs else None
        ),
    }


# ---------------------------------------------------------------------------
# Ablation
# ---------------------------------------------------------------------------


def _ablation(
    rows: List[Dict[str, Any]],
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]],
    seeds: List[int],
    team_pool: Any,
) -> Dict[str, Any]:
    """V3c.1 variant grid. ponytail: reuse the
    V3b.1 approach but with V3c data.
    """
    all_features = sorted(
        rows[0]["our_features"].keys()
    )
    delta_features = [
        f for f in all_features if f.startswith("delta_")
    ]
    base_features = [
        f for f in all_features if not f.startswith("delta_")
    ]
    l2_grid = [0.0, 0.001, 0.01, 0.1]
    variants = [
        {"name": "all_features", "features": all_features,
         "normalize": False},
        {"name": "no_deltas", "features": base_features,
         "normalize": False},
        {"name": "only_deltas", "features": delta_features,
         "normalize": False},
        {"name": "all_features_normalized",
         "features": all_features, "normalize": True},
    ]
    # V3 baseline per seed.
    v3_acc_by_seed: Dict[int, float] = {}
    for s in seeds:
        _t, val = _group_split_pairs(
            pairs, val_fraction=0.2, seed=s
        )
        if val:
            baselines = _score_baselines_on_pairs(
                val, team_pool
            )
            v3_acc_by_seed[s] = baselines.get(
                "matchup_top4_v3", 0.0
            )
        else:
            v3_acc_by_seed[s] = 0.0
    results = []
    for v in variants:
        for l2 in l2_grid:
            per_seed = []
            for s in seeds:
                train, val = _group_split_pairs(
                    pairs, val_fraction=0.2, seed=s
                )
                if not train or not val:
                    continue
                train_mean_std = {}
                if v["normalize"]:
                    # Compute train stats from the
                    # winner rows of the train pairs.
                    train_team_hashes = {
                        w["team_hash"] for w, _ in train
                    }
                    train_rows_for_stats = [
                        r for r in rows
                        if r["team_hash"] in train_team_hashes
                    ]
                    for fn in v["features"]:
                        vals = [
                            r["our_features"].get(fn, 0.0)
                            for r in train_rows_for_stats
                        ]
                        if not vals:
                            train_mean_std[fn] = (0.0, 1.0)
                            continue
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
                    for fn in v["features"]:
                        v0 = row["our_features"].get(fn, 0.0)
                        if v["normalize"]:
                            mu, sd = train_mean_std[fn]
                            out[fn] = (v0 - mu) / sd
                        else:
                            out[fn] = v0
                    return out
                norm_train = [
                    ({"our_features": _xf(w)},
                     {"our_features": _xf(l)})
                    for w, l in train
                ]
                norm_val = [
                    ({"our_features": _xf(w)},
                     {"our_features": _xf(l)})
                    for w, l in val
                ]
                w, b, _ = _train_perceptron(
                    norm_train, v["features"],
                    n_epochs=5, learning_rate=0.1, l2=l2,
                    seed=s,
                )
                train_acc = _pairwise_accuracy(
                    w, b, norm_train
                )
                val_acc = _pairwise_accuracy(w, b, norm_val)
                v3_acc = v3_acc_by_seed.get(s, 0.0)
                per_seed.append({
                    "seed": s,
                    "n_train_pairs": len(train),
                    "n_val_pairs": len(val),
                    "train_acc": train_acc,
                    "val_acc": val_acc,
                    "v3_baseline_acc": v3_acc,
                    "beats_v3": val_acc > v3_acc,
                })
            val_accs = [
                p["val_acc"] for p in per_seed
                if p["val_acc"] == p["val_acc"]
            ]
            train_accs = [
                p["train_acc"] for p in per_seed
                if p["train_acc"] == p["train_acc"]
            ]
            gaps = [
                p["train_acc"] - p["val_acc"]
                for p in per_seed
                if p["train_acc"] == p["train_acc"]
                and p["val_acc"] == p["val_acc"]
            ]
            beats_v3_count = sum(
                1 for p in per_seed if p["beats_v3"]
            )
            results.append({
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
                    statistics.mean(gaps) if gaps else None
                ),
                "beats_v3_count": beats_v3_count,
                "beats_v3_fraction": (
                    beats_v3_count / len(per_seed)
                    if per_seed else 0.0
                ),
            })
    return {
        "n_seeds": len(seeds),
        "n_variants": len(results),
        "variants": results,
    }


# ---------------------------------------------------------------------------
# Training gates
# ---------------------------------------------------------------------------


def _training_gates(
    stability: Dict[str, Any],
    scale: Dict[str, Any],
    seed42_val_decisive: int,
) -> Dict[str, Any]:
    """Apply the V3c.1 spec's training gates.
    """
    gates: Dict[str, bool] = {}
    gates["mean_val_acc_ge_0.60"] = (
        stability["val_acc_mean"] is not None
        and stability["val_acc_mean"] >= GATE_MEAN_VAL
    )
    gates["median_val_acc_ge_0.60"] = (
        stability["val_acc_median"] is not None
        and stability["val_acc_median"] >= GATE_MEDIAN_VAL
    )
    gates["beats_v3_fraction_ge_0.80"] = (
        stability["beats_v3_fraction"] >= GATE_BEATS_V3_FRACTION
    )
    gates["beats_learned_fraction_ge_0.60"] = (
        stability["beats_learned_fraction"]
        >= GATE_BEATS_LEARNED_FRACTION
    )
    gates["overfit_gap_le_0.20"] = (
        stability["overfit_gap_mean"] is not None
        and stability["overfit_gap_mean"] <= GATE_OVERFIT_GAP
    )
    gates["feature_dominance_le_0.35"] = (
        scale["max_contribution_share"] <= GATE_FEATURE_DOMINANCE
    )
    gates["val_decisive_n_ge_10"] = (
        seed42_val_decisive >= GATE_MIN_VAL_DECISIVE
    )
    overall = all(gates.values())
    return {
        "gates": gates,
        "overall_pass": overall,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _write_md(
    report: Dict[str, Any], path: str
) -> None:
    lines = [
        "# Phase V3c.1 — VGC Learned-Preview Training",
        "",
        f"- n_battles_loaded: {report['validation']['n_battles']}",
        f"- n_decisive_pairs: {report['n_decisive_pairs']}",
        f"- n_features: {report['n_features']}",
        f"- n_seeds: {report['stability']['n_seeds']}",
        f"- val_acc mean: "
        f"{report['stability']['val_acc_mean']:.3f}"
        if report['stability']['val_acc_mean'] is not None
        else "- val_acc mean: n/a",
        f"- val_acc median: "
        f"{report['stability']['val_acc_median']:.3f}"
        if report['stability']['val_acc_median'] is not None
        else "- val_acc median: n/a",
        f"- val_acc min/max: "
        f"{report['stability']['val_acc_min']:.3f} / "
        f"{report['stability']['val_acc_max']:.3f}"
        if report['stability']['val_acc_min'] is not None
        else "- val_acc min/max: n/a",
        f"- beats V3: "
        f"{report['stability']['beats_v3_count']}/"
        f"{report['stability']['n_seeds']} "
        f"({report['stability']['beats_v3_fraction']:.0%})",
        f"- beats learned: "
        f"{report['stability']['beats_learned_count']}/"
        f"{report['stability']['n_seeds']} "
        f"({report['stability']['beats_learned_fraction']:.0%})",
        "",
        "## Decisive pairs by source",
        "",
        "| source | count |",
        "|---|---:|",
    ]
    for s, n in sorted(
        report["decisive_by_source"].items(),
        key=lambda x: -x[1],
    ):
        lines.append(f"| {s} | {n} |")
    lines += [
        "",
        "## Decisive winner policy distribution",
        "",
        "| policy | count |",
        "|---|---:|",
    ]
    for s, n in sorted(
        report["decisive_winner_policies"].items(),
        key=lambda x: -x[1],
    ):
        lines.append(f"| {s} | {n} |")
    lines += [
        "",
        "## Training gates",
        "",
        "| gate | result |",
        "|---|:-:|",
    ]
    for k, v in report["gates"]["gates"].items():
        lines.append(f"| {k} | {'PASS' if v else 'FAIL'} |")
    lines += [
        "",
        f"**OVERALL: "
        f"{'GO_V3C1' if report['gates']['overall_pass'] else 'BLOCKED'}**",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def train_v3c1(
    jsonl_paths: List[str] = None,
    n_seeds: int = 30,
    n_epochs: int = 5,
    l2: float = 0.01,
    learning_rate: float = 0.1,
) -> Dict[str, Any]:
    """End-to-end V3c.1 training pipeline.
    Returns a report dict.
    """
    if jsonl_paths is None:
        jsonl_paths = V3C_PAIRING_FILES
    team_pool = load_vgc_pool()
    rows, file_info = _load_all_v3c_rows(
        jsonl_paths, team_pool
    )
    validation = _validate_v3c_dataset(rows, file_info)
    pairs, decisive_skipped = (
        _build_decisive_pairs_per_pairing(rows)
    )
    feature_names = sorted(
        rows[0]["our_features"].keys()
    )
    # Per-source decisive counts.
    dec_by_source = Counter(p[0].get("source", "?") for p in pairs)
    dec_winner_pols = Counter(
        p[0].get("our_policy", "?") for p in pairs
    )
    # Group split with seed 42 (canonical).
    train_42, val_42 = _group_split_pairs(
        pairs, val_fraction=0.2, seed=42
    )
    assert_no_leakage(
        [{"team_hash": p[0]["team_hash"]} for p in train_42],
        [{"team_hash": p[0]["team_hash"]} for p in val_42],
    )
    weights, bias, train_meta = _train_perceptron(
        train_42, feature_names,
        n_epochs=n_epochs, learning_rate=learning_rate,
        l2=l2, seed=42,
    )
    train_acc = _pairwise_accuracy(weights, bias, train_42)
    val_acc = _pairwise_accuracy(weights, bias, val_42)
    baselines = _score_baselines_on_pairs(val_42, team_pool)
    seed42_val_decisive = len(val_42)
    # Stability.
    seeds = list(range(n_seeds))
    stability = _stability(
        pairs, feature_names, seeds, team_pool
    )
    # Ablation.
    ablation = _ablation(
        rows, pairs, seeds, team_pool
    )
    # Feature scale.
    scale = _feature_scale(rows, weights)
    # Top positive/negative weights.
    sorted_w = sorted(
        weights.items(), key=lambda x: -abs(x[1])
    )
    top_pos = [[n, v] for n, v in sorted_w if v > 0][:5]
    top_neg = [[n, v] for n, v in sorted_w if v < 0][:5]
    # Gates.
    gates = _training_gates(
        stability, scale, seed42_val_decisive
    )
    overall = gates["overall_pass"]
    # Save model if gates pass.
    model_artifact = None
    if overall:
        model_artifact = save_model(
            V3C1_MODEL_PATH, weights, bias,
            feature_names, {
                "phase": "V3c.1",
                "n_decisive_pairs": len(pairs),
                "n_features": len(feature_names),
                "train_acc": train_acc,
                "val_acc": val_acc,
                "stability": stability,
                "baselines": baselines,
                "gates": gates,
            },
        )
    # Build report.
    report = {
        "phase": "V3c.1",
        "validation": validation,
        "decisive_by_source": dict(dec_by_source),
        "decisive_winner_policies": dict(dec_winner_pols),
        "decisive_skipped": decisive_skipped,
        "n_decisive_pairs": len(pairs),
        "n_features": len(feature_names),
        "feature_names_sample": feature_names[:5],
        "feature_names_total": len(feature_names),
        "seed42_train_n": len(train_42),
        "seed42_val_n": len(val_42),
        "seed42_train_acc": train_acc,
        "seed42_val_acc": val_acc,
        "seed42_baselines": baselines,
        "stability": stability,
        "ablation": ablation,
        "feature_scale": {
            "max_contribution_share": scale[
                "max_contribution_share"
            ],
            "dominant_feature": scale["dominant_feature"],
            "n_features": scale["n_features"],
            "top10_by_contribution": scale[
                "top10_by_contribution"
            ],
        },
        "gates": gates,
        "top_positive_weights": top_pos,
        "top_negative_weights": top_neg,
        "model_artifact_path": (
            V3C1_MODEL_PATH if overall else None
        ),
        "weight_norm": sum(v * v for v in weights.values())
        ** 0.5,
    }
    # Write artifacts.
    os.makedirs(
        os.path.dirname(V3C1_REPORT_JSON) or ".",
        exist_ok=True,
    )
    with open(V3C1_REPORT_JSON, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    _write_md(report, V3C1_REPORT_MD)
    with open(V3C1_FEATURE_SCALE, "w") as f:
        json.dump(scale, f, indent=2, sort_keys=True)
    with open(V3C1_SPLIT_STABILITY, "w") as f:
        json.dump(stability, f, indent=2, sort_keys=True)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Phase V3c.1 VGC learned-preview training"
    )
    parser.add_argument(
        "--n-seeds", type=int, default=30
    )
    parser.add_argument(
        "--n-epochs", type=int, default=5
    )
    parser.add_argument("--l2", type=float, default=0.01)
    parser.add_argument(
        "--learning-rate", type=float, default=0.1
    )
    args = parser.parse_args()
    report = train_v3c1(
        n_seeds=args.n_seeds,
        n_epochs=args.n_epochs,
        l2=args.l2,
        learning_rate=args.learning_rate,
    )
    overall = report["gates"]["overall_pass"]
    print(
        f"\n{'='*60}\n"
        f"V3c.1: overall = "
        f"{'GO_V3C1' if overall else 'BLOCKED'}\n"
        f"{'='*60}"
    )
    print(
        f"n_decisive_pairs={report['n_decisive_pairs']} "
        f"n_features={report['n_features']}"
    )
    print(
        f"val_acc mean={report['stability']['val_acc_mean']} "
        f"median={report['stability']['val_acc_median']}"
    )
    print(
        f"beats V3: {report['stability']['beats_v3_count']}/"
        f"{report['stability']['n_seeds']} "
        f"({report['stability']['beats_v3_fraction']:.0%})"
    )
    return 0 if overall else 6


if __name__ == "__main__":
    sys.exit(main())
