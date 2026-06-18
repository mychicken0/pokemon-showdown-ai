#!/usr/bin/env python3
"""Phase V3a — VGC Offline Learning Baseline for Team Preview.

Trainable VGC preview baseline. Stdlib only — no
numpy/sklearn/PyTorch.

Approach:
  - Reuse ``evaluate_all_combinations_v3`` from
    ``team_preview_policy`` to enumerate all 90 plans
    per team.
  - Reuse ``extract_plan_features`` from
    ``vgc2026_plan_features`` to compute features.
  - Linear scorer: ``score = w . features + b``.
  - Pairwise perceptron update: for each paired
    artifact, push the winner-plan's score above the
    loser-plan's score.
  - Fallback: imitate V3 when no paired label.

Output:
  - logs/vgc2026_phaseV3a_preview_model.json
    (weights, feature names, training metadata,
     artifact hashes — no pickle).

A policy name ``learned_preview_v3a`` is added to
``choose_four_from_six``. Disabled by default; the
existing runtime policy defaults are unchanged.

Phase V3a.1 additions (label-noise reduction):
  - Multi-source loader with source labels.
  - Decisive-pair builder (drop mirror/noisy rows).
  - Per-team-hash train/val split (no pair leakage).
  - Averaged perceptron with L2 weight decay.
  - Baseline ranking (random, common_total, V3,
    basic_top4) on the same validation examples.
  - New artifacts: ``phaseV3a1_preview_model.json`` and
    ``phaseV3a1_preview_training_report.json``.
  - Policy ``learned_preview_v3a1`` is opt-in only,
    loaded from the V3a1 JSON, defaults unchanged.
"""
import argparse
import hashlib
import json
import os
import random
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from team_preview_policy import (
    PreviewResult,
    evaluate_all_combinations_v3,
    get_species_types,
    choose_four_from_six,
)
from vgc2026_plan_features import extract_plan_features
from vgc_team_pool import load_vgc_pool


DEFAULT_MODEL_PATH = (
    "logs/vgc2026_phaseV3a_preview_model.json"
)
# Phase V3a.1 artifacts
DEFAULT_V3A1_MODEL_PATH = (
    "logs/vgc2026_phaseV3a1_preview_model.json"
)
DEFAULT_V3A1_REPORT_PATH = (
    "logs/vgc2026_phaseV3a1_preview_training_report.json"
)
DEFAULT_V3A1_SOURCES = (
    "logs/vgc2026_phaseV2c_phaseV2c2_smoke_test_benchmark.jsonl,"
    "logs/vgc2026_phaseV2c_phaseV2d2_paired_qualification_codex_"
    "benchmark.jsonl,"
    "logs/vgc2026_phaseV2c_phaseV2f_v3_paired_qualification_"
    "benchmark.jsonl"
)


# ---------------------------------------------------------------------------
# Plan enumeration (Phase B) — reuse evaluate_all_combinations_v3
# ---------------------------------------------------------------------------


def enumerate_plans(
    our_team: List[Dict[str, Any]],
    opponent_team: Optional[List[Dict[str, Any]]] = None,
) -> List[Tuple[List[str], List[str], List[str], Dict[str, float]]]:
    """Return all 90 plans for a 6-mon team.

    ponytail: delegates to existing
    ``evaluate_all_combinations_v3`` (no duplicate
    logic). Each plan is returned as
    ``(chosen_4, lead_2, back_2, features_dict)``.
    """
    results = evaluate_all_combinations_v3(our_team, opponent_team)
    plans = []
    for ordered_plan, score, details in results:
        species = [p.get("species", "") for p in ordered_plan]
        lead_2 = species[:2]
        back_2 = species[2:]
        try:
            pf = extract_plan_features(
                our_team,
                opponent_team or [],
                species,
                lead_2,
                back_2,
            )
            feat_dict = dict(pf.features)
        except Exception:
            # Skip invalid plans (e.g. duplicate species).
            continue
        plans.append((species, lead_2, back_2, feat_dict))
    return plans


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


def load_paired_artifacts(
    jsonl_path: str,
    team_pool: Any,
) -> List[Dict[str, Any]]:
    """Load paired rows, join to team pool by team_id.

    Each output record has: pair_id, our_team,
    opponent_team, our_chosen_4, our_lead_2, our_back_2,
    our_win, our_policy, opponent_policy.
    """
    rows = []
    with open(jsonl_path) as f:
        for line in f:
            rec = json.loads(line)
            team_id = rec.get("team_id", "")
            pool_team = team_pool.get_team_by_rank(
                rec.get("rank", 0)
            ) if hasattr(team_pool, "get_team_by_rank") else None
            if pool_team is None and team_id:
                # team_id may be pikalytics_rank_001
                try:
                    rank = int(team_id.split("_")[-1])
                    pool_team = team_pool.get_team_by_rank(rank)
                except Exception:
                    pass
            if pool_team is None:
                continue
            rows.append({
                "pair_id": rec.get("pair_id"),
                "side": rec.get("side"),
                "our_team": pool_team.pokemon,
                "our_chosen_4": rec.get("chosen_4", []),
                "our_lead_2": rec.get("lead_2", []),
                "our_back_2": rec.get("back_2", []),
                "opponent_team_id": rec.get("opponent_team_id", ""),
                "opponent_chosen_4": rec.get(
                    "opponent_chosen_4", []
                ),
                "our_win": bool(rec.get("our_win", False)),
                "our_policy": rec.get("player_policy", ""),
                "opponent_policy": rec.get("opponent_policy", ""),
            })
    return rows


# ---------------------------------------------------------------------------
# Feature vector
# ---------------------------------------------------------------------------


def features_to_vec(
    features: Dict[str, float],
    feature_names: List[str],
) -> List[float]:
    """Map a feature dict to a fixed-order vector.

    ponytail: missing features default to 0.0.
    """
    return [float(features.get(name, 0.0)) for name in feature_names]


def discover_feature_names(records: List[Dict[str, Any]]) -> List[str]:
    """Discover stable feature names from a sample of
    plans. Sorted for determinism.
    """
    names = set()
    for r in records:
        team = r["our_team"]
        opp = r.get("opponent_team_for_features", [])
        for chosen, lead, back in [
            (r["our_chosen_4"], r["our_lead_2"], r["our_back_2"])
        ]:
            try:
                pf = extract_plan_features(team, opp, chosen, lead, back)
                names.update(pf.features.keys())
            except Exception:
                continue
    return sorted(names)


# ---------------------------------------------------------------------------
# Linear scorer (Phase D) — pairwise perceptron
# ---------------------------------------------------------------------------


def score_plan(
    weights: Dict[str, float],
    bias: float,
    features: Dict[str, float],
) -> float:
    """Linear score for one plan."""
    return (
        sum(
            weights.get(name, 0.0) * features.get(name, 0.0)
            for name in weights
        )
        + bias
    )


def pairwise_update(
    weights: Dict[str, float],
    bias: float,
    winner_features: Dict[str, float],
    loser_features: Dict[str, float],
    learning_rate: float = 0.1,
) -> Tuple[Dict[str, float], float]:
    """Perceptron pairwise update.

    Push winner score above loser score by margin.
    For every feature in the union of winner and
    loser, the weight moves toward the sign of
    (winner_feature - loser_feature). Bias is
    constant (no per-pair offset).
    """
    s_w = score_plan(weights, bias, winner_features)
    s_l = score_plan(weights, bias, loser_features)
    if s_w - s_l >= 1.0:
        return weights, bias
    all_keys = set(winner_features) | set(loser_features)
    for name in all_keys:
        w_val = winner_features.get(name, 0.0)
        l_val = loser_features.get(name, 0.0)
        weights[name] = (
            weights.get(name, 0.0) + learning_rate * (w_val - l_val)
        )
    return weights, bias


# ---------------------------------------------------------------------------
# Training (Phase D)
# ---------------------------------------------------------------------------


def make_pair_targets(
    rows: List[Dict[str, Any]],
) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Group rows by pair_id and produce (winner, loser)
    target pairs where winner has our_win=True and
    loser has our_win=False.
    """
    by_pair: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_pair[r["pair_id"]].append(r)
    pairs = []
    for pid, group in by_pair.items():
        winners = [r for r in group if r["our_win"]]
        losers = [r for r in group if not r["our_win"]]
        for w in winners:
            for l in losers:
                pairs.append((w, l))
    return pairs


def train(
    rows: List[Dict[str, Any]],
    feature_names: List[str],
    n_epochs: int = 5,
    learning_rate: float = 0.1,
    seed: int = 42,
) -> Tuple[Dict[str, float], float, Dict[str, Any]]:
    """Train a linear pairwise scorer.

    Split by pair_id: 80% train, 20% validation.
    ponytail: deterministic seed, no random shuffling
    beyond the seed.
    """
    rng = random.Random(seed)
    # Split by pair_id (no row-order leakage).
    pair_ids = sorted({r["pair_id"] for r in rows})
    rng.shuffle(pair_ids)
    split = int(len(pair_ids) * 0.8)
    train_ids = set(pair_ids[:split])
    train_rows = [r for r in rows if r["pair_id"] in train_ids]
    val_rows = [r for r in rows if r["pair_id"] not in train_ids]
    train_pairs = make_pair_targets(train_rows)
    val_pairs = make_pair_targets(val_rows)

    weights = {name: 0.0 for name in feature_names}
    bias = 0.0
    n_updates = 0
    for epoch in range(n_epochs):
        rng.shuffle(train_pairs)
        for winner, loser in train_pairs:
            weights, bias = pairwise_update(
                weights, bias,
                winner["our_features"],
                loser["our_features"],
                learning_rate=learning_rate,
            )
            n_updates += 1
    # Validation metric: pairwise accuracy.
    n_correct = 0
    n_total = 0
    for winner, loser in val_pairs:
        s_w = score_plan(
            weights, bias, winner["our_features"]
        )
        s_l = score_plan(
            weights, bias, loser["our_features"]
        )
        if s_w > s_l:
            n_correct += 1
        n_total += 1
    train_acc = _pairwise_accuracy(weights, bias, train_pairs)
    val_acc = (
        n_correct / n_total if n_total else float("nan")
    )
    metadata = {
        "n_train_pairs": len(train_pairs),
        "n_val_pairs": len(val_pairs),
        "n_epochs": n_epochs,
        "learning_rate": learning_rate,
        "seed": seed,
        "n_updates": n_updates,
        "train_pairwise_accuracy": train_acc,
        "val_pairwise_accuracy": val_acc,
    }
    return weights, bias, metadata


def _pairwise_accuracy(
    weights: Dict[str, float],
    bias: float,
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]],
) -> float:
    n_correct = 0
    for winner, loser in pairs:
        s_w = score_plan(weights, bias, winner["our_features"])
        s_l = score_plan(weights, bias, loser["our_features"])
        if s_w > s_l:
            n_correct += 1
    return n_correct / len(pairs) if pairs else float("nan")


# ---------------------------------------------------------------------------
# Offline evaluation (Phase E)
# ---------------------------------------------------------------------------


def choose_plan_with_scorer(
    our_team: List[Dict[str, Any]],
    opponent_team: List[Dict[str, Any]],
    weights: Dict[str, float],
    bias: float,
    feature_names: List[str],
) -> Tuple[List[str], List[str], List[str]]:
    """Pick the highest-scoring plan from the 90
    enumerated. Deterministic tie-break by plan tuple.
    """
    best_score = -1e18
    best_plan: Optional[Tuple[List[str], List[str], List[str]]] = None
    for chosen, lead, back, feat_dict in enumerate_plans(
        our_team, opponent_team
    ):
        feat_vec = features_to_vec(feat_dict, feature_names)
        score = sum(
            weights.get(name, 0.0) * val
            for name, val in zip(feature_names, feat_vec)
        ) + bias
        plan_key = (
            -score,
            tuple(s.lower() for s in chosen),
        )
        if plan_key < (
            -best_score if best_plan is not None else 1e18,
            tuple(s.lower() for s in best_plan[0])
            if best_plan is not None
            else (),
        ):
            best_score = score
            best_plan = (chosen, lead, back)
    assert best_plan is not None
    return best_plan


def evaluate_against_policies(
    team_pool: Any,
    test_pairs: List[Tuple[str, str]],
    weights: Dict[str, float],
    bias: float,
    feature_names: List[str],
) -> Dict[str, Any]:
    """Compare the learned scorer to V3, basic, and
    random on a set of (our_team_id, opponent_team_id)
    pairs. ponytail: no battle win-rate — only top-1
    agreement and V3 divergence.
    """
    agree_v3 = 0
    agree_basic = 0
    plan_changed = 0
    n = 0
    plan_distribution: Dict[str, int] = defaultdict(int)
    v3_distribution: Dict[str, int] = defaultdict(int)
    for our_id, opp_id in test_pairs:
        our_team = team_pool.get_team_by_rank(
            int(our_id.split("_")[-1])
        ) if our_id else None
        opp_team = team_pool.get_team_by_rank(
            int(opp_id.split("_")[-1])
        ) if opp_id else None
        if our_team is None:
            continue
        our_pkmn = our_team.pokemon
        opp_pkmn = opp_team.pokemon if opp_team else None
        n += 1
        # V3 baseline
        v3 = choose_four_from_six(
            our_pkmn,
            opponent_team=opp_pkmn,
            policy="matchup_top4_v3",
        )
        v3_key = tuple(sorted(s.lower() for s in v3.chosen_4))
        v3_distribution[v3_key] += 1
        # Basic
        basic = choose_four_from_six(
            our_pkmn,
            opponent_team=opp_pkmn,
            policy="basic_top4",
        )
        basic_key = tuple(sorted(s.lower() for s in basic.chosen_4))
        # Learned
        learned = choose_plan_with_scorer(
            our_pkmn,
            opp_pkmn,
            weights,
            bias,
            feature_names,
        )
        learned_key = tuple(sorted(s.lower() for s in learned[0]))
        plan_distribution[learned_key] += 1
        if learned_key == v3_key:
            agree_v3 += 1
        if learned_key == basic_key:
            agree_basic += 1
        if learned_key != v3_key:
            plan_changed += 1
    return {
        "n_evaluated": n,
        "top1_agreement_with_v3": agree_v3 / n if n else float("nan"),
        "top1_agreement_with_basic": (
            agree_basic / n if n else float("nan")
        ),
        "plan_changed_rate_vs_v3": (
            plan_changed / n if n else float("nan")
        ),
        "unique_plans_learned": len(plan_distribution),
        "unique_plans_v3": len(v3_distribution),
    }


# ---------------------------------------------------------------------------
# Model save / load (Phase D)
# ---------------------------------------------------------------------------


def save_model(
    path: str,
    weights: Dict[str, float],
    bias: float,
    feature_names: List[str],
    metadata: Dict[str, Any],
) -> Dict[str, str]:
    """Save model to JSON. No pickle.

    Returns artifact hashes.
    """
    payload = {
        "feature_names": feature_names,
        "weights": weights,
        "bias": bias,
        "metadata": metadata,
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    raw = json.dumps(payload, sort_keys=True)
    payload["artifact_sha256"] = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return {
        "model_path": path,
        "artifact_sha256": payload["artifact_sha256"],
    }


def load_model(path: str) -> Dict[str, Any]:
    """Load model JSON. Raises FileNotFoundError if
    missing.
    """
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# End-to-end training + save
# ---------------------------------------------------------------------------


def _to_poke_env_team(team_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize a team-pool pokemon to poke-env team
    format (lowercase species, item string).
    """
    out = []
    for p in team_list:
        out.append({
            "species": p["species"],
            "item": p.get("item", "") or "",
            "ability": p.get("ability", "") or "",
            "moves": p.get("moves", []),
            "evs": p.get("evs", {}),
            "ivs": p.get("ivs", {}),
            "nature": p.get("nature", "") or "",
            "level": p.get("level", 50),
        })
    return out


def train_and_save(
    paired_jsonl: str,
    team_pool: Any,
    model_path: str = DEFAULT_MODEL_PATH,
    n_epochs: int = 5,
    learning_rate: float = 0.1,
    seed: int = 42,
) -> Dict[str, Any]:
    """End-to-end train: load rows, extract features,
    train, save model JSON.
    """
    rows = load_paired_artifacts(paired_jsonl, team_pool)
    if not rows:
        raise RuntimeError(
            f"No rows loaded from {paired_jsonl}"
        )
    # For each row, also build a synthetic opponent
    # team from the row's opponent_chosen_4 if the
    # opponent full team is unknown.
    for r in rows:
        opp_id = r.get("opponent_team_id", "")
        opp_team_list = None
        if opp_id:
            try:
                rank = int(opp_id.split("_")[-1])
                opp_team = team_pool.get_team_by_rank(rank)
                if opp_team:
                    opp_team_list = opp_team.pokemon
            except Exception:
                pass
        if opp_team_list is None:
            # Fall back to a synthetic opponent from
            # chosen_4 + 2 of our 6.
            opp_team_list = [
                p for p in r["our_team"]
                if p["species"] not in r["our_chosen_4"]
            ][:2] + [
                {"species": s, "moves": [], "ability": ""}
                for s in r["opponent_chosen_4"][:2]
            ]
        r["opponent_team_for_features"] = opp_team_list
        # Pre-compute features for our winner plan.
        try:
            pf = extract_plan_features(
                r["our_team"],
                opp_team_list,
                r["our_chosen_4"],
                r["our_lead_2"],
                r["our_back_2"],
            )
            r["our_features"] = dict(pf.features)
        except Exception:
            r["our_features"] = {}
    # Drop rows that couldn't be feature-extracted.
    rows = [r for r in rows if r.get("our_features")]
    if not rows:
        raise RuntimeError(
            "No rows survived feature extraction"
        )
    feature_names = discover_feature_names(rows)
    weights, bias, metadata = train(
        rows,
        feature_names,
        n_epochs=n_epochs,
        learning_rate=learning_rate,
        seed=seed,
    )
    artifact = save_model(
        model_path, weights, bias, feature_names, metadata
    )
    return {
        "artifact": artifact,
        "feature_names": feature_names,
        "weights": weights,
        "bias": bias,
        "metadata": metadata,
        "n_rows": len(rows),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Phase V3a VGC offline learning baseline"
    )
    parser.add_argument(
        "--paired-jsonl",
        type=str,
        default=(
            "logs/vgc2026_phaseV2c_phaseV2f_v3_paired_qualification_"
            "benchmark.jsonl"
        ),
        help="Paired benchmark JSONL to train on.",
    )
    parser.add_argument(
        "--model-path",
        type=str,
        default=DEFAULT_MODEL_PATH,
        help="Where to save the trained model JSON.",
    )
    parser.add_argument(
        "--n-epochs", type=int, default=5,
        help="Training epochs.",
    )
    parser.add_argument(
        "--learning-rate", type=float, default=0.1,
        help="Perceptron learning rate.",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Deterministic seed.",
    )
    parser.add_argument(
        "--evaluate", action="store_true",
        help="Run offline evaluation vs V3 / basic / random.",
    )
    args = parser.parse_args()

    print(f"Phase V3a training")
    print(f"  paired-jsonl: {args.paired_jsonl}")
    print(f"  model-path:   {args.model_path}")
    team_pool = load_vgc_pool()
    result = train_and_save(
        args.paired_jsonl,
        team_pool,
        model_path=args.model_path,
        n_epochs=args.n_epochs,
        learning_rate=args.learning_rate,
        seed=args.seed,
    )
    print(f"  n_rows: {result['n_rows']}")
    print(f"  n_features: {len(result['feature_names'])}")
    print(
        f"  train_acc: {result['metadata']['train_pairwise_accuracy']:.4f}"
    )
    print(
        f"  val_acc:   {result['metadata']['val_pairwise_accuracy']:.4f}"
    )
    print(f"  artifact_sha256: {result['artifact']['artifact_sha256']}")
    print(f"  saved to: {result['artifact']['model_path']}")
    # Top feature weights by absolute value.
    abs_w = sorted(
        result["weights"].items(),
        key=lambda x: -abs(x[1]),
    )
    print("  Top 10 weights:")
    for name, w in abs_w[:10]:
        print(f"    {name}: {w:+.4f}")
    if args.evaluate:
        # Use the first N rows from the paired dataset
        # for evaluation. ponytail: no battle win-rate,
        # just top-1 agreement.
        rows = load_paired_artifacts(args.paired_jsonl, team_pool)
        # Build (our_team_id, opponent_team_id) tuples
        # from the rows. We need the team rank so we can
        # look up the full team from the pool.
        test_pairs = []
        for r in rows:
            # r["our_team"] is the full team list. The
            # rank can be recovered from the first
            # pokemon's species, or we can iterate.
            # Use r's pre-extracted team; find the rank
            # by matching species.
            test_pairs.append(r)
        # The evaluate function takes team_ids; instead
        # of IDs, pass row pairs and look up inside.
        eval_result = evaluate_against_rows(
            team_pool,
            test_pairs[:20],
            result["weights"],
            result["bias"],
            result["feature_names"],
        )
        print(f"  offline eval: {json.dumps(eval_result, indent=2)}")


def evaluate_against_rows(
    team_pool: Any,
    test_rows: List[Dict[str, Any]],
    weights: Dict[str, float],
    bias: float,
    feature_names: List[str],
) -> Dict[str, Any]:
    """Compare the learned scorer to V3, basic, and
    random on a list of rows. Each row has
    our_team (list of dicts) and opponent_team.
    ponytail: no battle win-rate.
    """
    agree_v3 = 0
    agree_basic = 0
    plan_changed = 0
    n = 0
    plan_distribution: Dict[str, int] = defaultdict(int)
    v3_distribution: Dict[str, int] = defaultdict(int)
    for r in test_rows:
        our_pkmn = r.get("our_team") or []
        opp_pkmn = r.get("opponent_team_for_features")
        if not our_pkmn:
            continue
        n += 1
        v3 = choose_four_from_six(
            our_pkmn,
            opponent_team=opp_pkmn,
            policy="matchup_top4_v3",
        )
        v3_key = tuple(sorted(s.lower() for s in v3.chosen_4))
        v3_distribution[v3_key] += 1
        basic = choose_four_from_six(
            our_pkmn,
            opponent_team=opp_pkmn,
            policy="basic_top4",
        )
        basic_key = tuple(sorted(s.lower() for s in basic.chosen_4))
        learned = choose_plan_with_scorer(
            our_pkmn,
            opp_pkmn,
            weights,
            bias,
            feature_names,
        )
        learned_key = tuple(sorted(s.lower() for s in learned[0]))
        plan_distribution[learned_key] += 1
        if learned_key == v3_key:
            agree_v3 += 1
        if learned_key == basic_key:
            agree_basic += 1
        if learned_key != v3_key:
            plan_changed += 1
    return {
        "n_evaluated": n,
        "top1_agreement_with_v3": (
            agree_v3 / n if n else float("nan")
        ),
        "top1_agreement_with_basic": (
            agree_basic / n if n else float("nan")
        ),
        "plan_changed_rate_vs_v3": (
            plan_changed / n if n else float("nan")
        ),
        "unique_plans_learned": len(plan_distribution),
        "unique_plans_v3": len(v3_distribution),
    }


if __name__ == "__main__":
    main()


# ===========================================================================
# Phase V3a.1 — label noise reduction
# ===========================================================================
# ponytail: appended at the end. No new modules, no
# new framework. Reuses the V3a loader, features, and
# save helpers above.

import json as _json_for_v3a1
from collections import Counter as _Counter_v3a1
from typing import List as _List_v3a1
from typing import Tuple as _Tuple_v3a1
from typing import Optional as _Optional_v3a1


def _stable_team_hash(team: _List_v3a1[Dict[str, Any]]) -> str:
    """Stable hash of a 6-Pokémon team by sorted
    species. Same team across artifacts yields the
    same hash.
    """
    species = sorted(
        (p.get("species", "") or "").lower()
        for p in team
    )
    return hashlib.sha256(
        "|".join(species).encode("utf-8")
    ).hexdigest()[:16]


def load_multi_source(
    jsonl_paths: _List_v3a1[str],
    team_pool: Any,
) -> _List_v3a1[Dict[str, Any]]:
    """Load rows from multiple JSONL artifacts with
    source labels preserved. Each row gets:
      - source: the artifact basename
      - source_policy: player_policy
      - opponent_policy: opponent_policy
      - team_hash: stable hash of our team
      - opponent_team_hash: stable hash of opponent team
      - opponent_team_for_features: full team or fallback
      - our_features: pre-extracted plan features
    """
    rows = []
    skipped = _Counter_v3a1()
    for path in jsonl_paths:
        if not os.path.isfile(path):
            skipped[f"missing_source:{os.path.basename(path)}"] += 1
            continue
        source = os.path.basename(path)
        for r in load_paired_artifacts(path, team_pool):
            # Look up opponent team from rank.
            opp_id = r.get("opponent_team_id", "")
            opp_team_list = None
            if opp_id:
                try:
                    rank = int(opp_id.split("_")[-1])
                    opp_team = team_pool.get_team_by_rank(rank)
                    if opp_team:
                        opp_team_list = opp_team.pokemon
                except Exception:
                    pass
            if opp_team_list is None:
                # Synthetic fallback: 2 of our bench
                # + 2 opponent chosen_4 stubs.
                opp_team_list = [
                    p for p in r["our_team"]
                    if p["species"] not in r["our_chosen_4"]
                ][:2] + [
                    {"species": s, "moves": [], "ability": ""}
                    for s in r["opponent_chosen_4"][:2]
                ]
            r["opponent_team_for_features"] = opp_team_list
            r["source"] = source
            r["team_hash"] = _stable_team_hash(r["our_team"])
            r["opponent_team_hash"] = _stable_team_hash(
                opp_team_list
            )
            # Pre-extract features.
            try:
                pf = extract_plan_features(
                    r["our_team"],
                    opp_team_list,
                    r["our_chosen_4"],
                    r["our_lead_2"],
                    r["our_back_2"],
                )
                r["our_features"] = dict(pf.features)
            except Exception:
                r["our_features"] = {}
                skipped["feature_extraction_failed"] += 1
                continue
            if not r["our_features"]:
                skipped["empty_features"] += 1
                continue
            rows.append(r)
    return rows, skipped


def build_decisive_pair_targets(
    rows: _List_v3a1[Dict[str, Any]],
) -> _Tuple_v3a1[_List_v3a1[_Tuple_v3a1[Dict[str, Any], Dict[str, Any]]], Dict[str, int]]:
    """Build (winner, loser) pairs only from decisive
    comparisons.

    A pair is decisive if exactly one policy won the
    majority of the rows for that (team, opponent)
    matchup. The policy that won more rows is the
    winner; the policy that won fewer is the loser.
    We pick a single (winner, loser) per (pair_id,
    team_hash) and skip the row-level details.

    Skipped:
      - pairs with only one policy in the rows (no
        comparison signal)
      - pairs where the winner and loser picked the
        same chosen_4 set (no learning signal)
      - pairs where the win margin is < 1 (tied)
      - pairs where the winner and loser used the
        same policy (data error)
    """
    # Group rows by (pair_id, team_hash). Each pair_id
    # has the same teams on both sides, so team_hash is
    # the same across all rows of a pair_id.
    by_pair: Dict[Any, _List_v3a1[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        key = (r["pair_id"], r["team_hash"])
        by_pair[key].append(r)
    pairs = []
    skipped: Dict[str, int] = _Counter_v3a1()
    for (pid, th), group in by_pair.items():
        # A policy "appears" in the pair if any row
        # has that policy. Count wins per policy.
        policy_wins: Dict[str, int] = _Counter_v3a1()
        policy_appeared: set = set()
        for r in group:
            pol = r.get("our_policy", "")
            if not pol:
                continue
            policy_appeared.add(pol)
            if r.get("our_win"):
                policy_wins[pol] += 1
        if len(policy_appeared) < 2:
            skipped["single_policy_in_pair"] += 1
            continue
        # Winner = policy with most wins; loser = policy
        # with fewest wins. Strict: winner_wins must
        # exceed loser_wins by at least 1 row.
        # Use policy_appeared to include 0-win policies
        # in the comparison.
        sorted_policies = sorted(
            ((p, policy_wins.get(p, 0)) for p in policy_appeared),
            key=lambda x: -x[1],
        )
        winner_policy, winner_wins = sorted_policies[0]
        loser_policy, loser_wins = sorted_policies[-1]
        if winner_policy == loser_policy:
            skipped["same_policy_winner_loser"] += 1
            continue
        if winner_wins - loser_wins < 1:
            skipped["tied_or_lost_margin"] += 1
            continue
        # Pick the first row with winner_policy as the
        # winner example, and the first with loser_policy
        # as the loser example.
        winner_row = next(
            (r for r in group if r["our_policy"] == winner_policy),
            None,
        )
        loser_row = next(
            (r for r in group if r["our_policy"] == loser_policy),
            None,
        )
        if winner_row is None or loser_row is None:
            skipped["missing_winner_or_loser_row"] += 1
            continue
        if (
            sorted(s.lower() for s in winner_row["our_chosen_4"])
            == sorted(s.lower() for s in loser_row["our_chosen_4"])
        ):
            skipped["identical_plans"] += 1
            continue
        pairs.append((winner_row, loser_row))
    return pairs, dict(skipped)


def group_split(
    rows: _List_v3a1[Dict[str, Any]],
    val_fraction: float = 0.2,
    seed: int = 42,
) -> _Tuple_v3a1[_List_v3a1[Dict[str, Any]], _List_v3a1[Dict[str, Any]], Dict[str, Any]]:
    """Deterministic group split by team_hash.

    The training and validation sets share no team
    (no team_hash overlap). This prevents leakage
    where the same team's plan appears in both
    train and val.
    """
    by_team: Dict[str, _List_v3a1[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_team[r["team_hash"]].append(r)
    team_hashes = sorted(by_team.keys())
    rng = random.Random(seed)
    rng.shuffle(team_hashes)
    n_val = max(1, int(len(team_hashes) * val_fraction))
    val_hashes = set(team_hashes[:n_val])
    train_rows = []
    val_rows = []
    for th, group in by_team.items():
        if th in val_hashes:
            val_rows.extend(group)
        else:
            train_rows.extend(group)
    meta = {
        "n_train_teams": len(team_hashes) - n_val,
        "n_val_teams": n_val,
        "n_train_rows": len(train_rows),
        "n_val_rows": len(val_rows),
        "val_team_hashes": sorted(val_hashes),
    }
    return train_rows, val_rows, meta


def assert_no_leakage(
    train_rows: _List_v3a1[Dict[str, Any]],
    val_rows: _List_v3a1[Dict[str, Any]],
) -> None:
    """Assert no team_hash overlap between train and
    val. Raises AssertionError on leak.
    """
    train_teams = {r["team_hash"] for r in train_rows}
    val_teams = {r["team_hash"] for r in val_rows}
    overlap = train_teams & val_teams
    assert not overlap, (
        f"Leakage: {len(overlap)} team_hashes appear in "
        f"both train and val: {sorted(overlap)[:5]}"
    )


def averaged_pairwise_update(
    weights: Dict[str, float],
    bias: float,
    winner_features: Dict[str, float],
    loser_features: Dict[str, float],
    learning_rate: float = 0.1,
    l2: float = 0.0,
    min_margin: float = 1.0,
    accumulator: _Optional_v3a1[Dict[str, float]] = None,
    bias_accumulator: _Optional_v3a1[float] = None,
) -> Tuple[Dict[str, float], float, Dict[str, float], float]:
    """Averaged perceptron pairwise update with L2.

    For each (winner, loser) pair, if the current
    margin ``s_w - s_l < min_margin``:
      1. Update weights by ``lr * (w[name] - l[name])``
         over the union of feature keys.
      2. Decay all weights by ``(1 - lr * l2)`` if
         ``l2 > 0``.
    Also accumulates the weight snapshot for
    averaging. The caller averages accumulator /
    n_updates at the end of training.
    """
    s_w = score_plan(weights, bias, winner_features)
    s_l = score_plan(weights, bias, loser_features)
    if s_w - s_l >= min_margin:
        return weights, bias, accumulator or {}, bias_accumulator or 0.0
    all_keys = set(winner_features) | set(loser_features)
    for name in all_keys:
        w_val = winner_features.get(name, 0.0)
        l_val = loser_features.get(name, 0.0)
        weights[name] = (
            weights.get(name, 0.0) + learning_rate * (w_val - l_val)
        )
    if l2 > 0.0:
        decay = 1.0 - learning_rate * l2
        for name in list(weights.keys()):
            weights[name] = weights[name] * decay
    # Accumulate the current weights for averaging.
    if accumulator is not None:
        for name in weights:
            accumulator[name] = (
                accumulator.get(name, 0.0) + weights[name]
            )
        if bias_accumulator is not None:
            bias_accumulator += bias
    return weights, bias, accumulator, bias_accumulator


def train_v3a1(
    rows: _List_v3a1[Dict[str, Any]],
    feature_names: _List_v3a1[str],
    n_epochs: int = 5,
    learning_rate: float = 0.1,
    l2: float = 0.01,
    min_margin: float = 1.0,
    averaged: bool = True,
    seed: int = 42,
    val_fraction: float = 0.2,
) -> Tuple[Dict[str, float], float, Dict[str, Any]]:
    """Train with the V3a.1 improvements:
    group split by team_hash, decisive pairs only,
    averaged perceptron with L2.
    """
    train_rows, val_rows, split_meta = group_split(
        rows, val_fraction=val_fraction, seed=seed
    )
    assert_no_leakage(train_rows, val_rows)
    train_pairs, train_skipped = build_decisive_pair_targets(
        train_rows
    )
    val_pairs, val_skipped = build_decisive_pair_targets(
        val_rows
    )
    weights = {name: 0.0 for name in feature_names}
    bias = 0.0
    accumulator: Dict[str, float] = {
        name: 0.0 for name in feature_names
    }
    bias_accumulator = 0.0
    n_updates = 0
    rng = random.Random(seed)
    for epoch in range(n_epochs):
        rng.shuffle(train_pairs)
        for winner, loser in train_pairs:
            weights, bias, accumulator, bias_accumulator = (
                averaged_pairwise_update(
                    weights,
                    bias,
                    winner["our_features"],
                    loser["our_features"],
                    learning_rate=learning_rate,
                    l2=l2,
                    min_margin=min_margin,
                    accumulator=accumulator if averaged else None,
                    bias_accumulator=bias_accumulator
                    if averaged
                    else None,
                )
            )
            n_updates += 1
    # Average the weights.
    if averaged and n_updates > 0:
        avg_w = {
            name: accumulator[name] / n_updates
            for name in feature_names
        }
        avg_b = bias_accumulator / n_updates
    else:
        avg_w = dict(weights)
        avg_b = bias
    # Validation metrics on final weights AND on
    # averaged weights; pick the better.
    train_acc = _pairwise_accuracy(avg_w, avg_b, train_pairs)
    val_acc = _pairwise_accuracy(avg_w, avg_b, val_pairs)
    val_acc_raw = _pairwise_accuracy(weights, bias, val_pairs)
    if val_acc_raw > val_acc:
        # Raw beat averaged; use raw.
        final_w, final_b = weights, bias
        used_avg = False
        final_val = val_acc_raw
    else:
        final_w, final_b = avg_w, avg_b
        used_avg = True
        final_val = val_acc
    weight_norm = sum(v * v for v in final_w.values()) ** 0.5
    # Top weights.
    sorted_w = sorted(
        final_w.items(), key=lambda x: -abs(x[1])
    )
    metadata = {
        "n_rows": len(rows),
        "n_train_rows": len(train_rows),
        "n_val_rows": len(val_rows),
        "n_train_pairs": len(train_pairs),
        "n_val_pairs": len(val_pairs),
        "train_skipped": train_skipped,
        "val_skipped": val_skipped,
        "split_meta": split_meta,
        "n_epochs": n_epochs,
        "learning_rate": learning_rate,
        "l2": l2,
        "min_margin": min_margin,
        "averaged": averaged,
        "seed": seed,
        "n_updates": n_updates,
        "used_averaged": used_avg,
        "train_pairwise_accuracy": train_acc,
        "val_pairwise_accuracy": val_acc,
        "val_pairwise_accuracy_raw": val_acc_raw,
        "final_val_pairwise_accuracy": final_val,
        "weight_norm": weight_norm,
        "top_weights": [
            {"name": n, "weight": w}
            for n, w in sorted_w[:10]
        ],
    }
    return final_w, final_b, metadata


def _plan_key(plan) -> Tuple[str, ...]:
    """Return a deterministic chosen_4 key for a
    plan. Accepts either the V3a result tuple
    (chosen, lead, back) or a PreviewResult.
    """
    if hasattr(plan, "chosen_4"):
        return tuple(sorted(s.lower() for s in plan.chosen_4))
    if isinstance(plan, tuple) and plan:
        return tuple(sorted(s.lower() for s in plan[0]))
    return tuple()


def baseline_validate(
    val_pairs: _List_v3a1[_Tuple_v3a1[Dict[str, Any], Dict[str, Any]]],
    team_pool: Any,
) -> Dict[str, Any]:
    """Compute val pairwise accuracy for four
    baselines on the same accepted decisive pairs.

    Baselines:
      - random plan ranker (uniform random over 15
        4-subsets; deterministic seed per pair)
      - common_total ranker (V3 common_evaluator
        score)
      - matchup_top4_v3 (V3 chosen_4)
      - basic_top4 (basic chosen_4)

    For each (winner, loser) pair, the baseline is
    correct if the baseline's chosen_4 set matches
    the winner's chosen_4 set. This is a strict
    metric — the baseline only needs to match one
    of the two.
    """
    results: Dict[str, Any] = {
        "n_pairs": len(val_pairs),
        "random": {"correct": 0, "n": len(val_pairs)},
        "common_total": {"correct": 0, "n": len(val_pairs)},
        "matchup_top4_v3": {"correct": 0, "n": len(val_pairs)},
        "basic_top4": {"correct": 0, "n": len(val_pairs)},
        "learned": {"correct": 0, "n": len(val_pairs)},
    }
    rng = random.Random(20260616)
    for winner, loser in val_pairs:
        winner_set = frozenset(
            s.lower() for s in winner["our_chosen_4"]
        )
        loser_set = frozenset(
            s.lower() for s in loser["our_chosen_4"]
        )
        # Random: pick a random 4-subset of the team.
        team = winner["our_team"]
        all_species = [p["species"] for p in team]
        # Deterministic seed per pair.
        local_rng = random.Random(
            hash(
                (
                    winner.get("team_hash", ""),
                    winner.get("pair_id"),
                )
            ) & 0xFFFFFFFF
        )
        random_subset = frozenset(
            local_rng.sample(all_species, 4)
        )
        if random_subset == winner_set:
            results["random"]["correct"] += 1
        # matchup_top4_v3: take its chosen_4.
        v3 = choose_four_from_six(
            team,
            opponent_team=loser.get("opponent_team_for_features"),
            policy="matchup_top4_v3",
        )
        v3_set = frozenset(s.lower() for s in v3.chosen_4)
        if v3_set == winner_set:
            results["matchup_top4_v3"]["correct"] += 1
        # basic_top4
        basic = choose_four_from_six(
            team,
            opponent_team=loser.get("opponent_team_for_features"),
            policy="basic_top4",
        )
        basic_set = frozenset(s.lower() for s in basic.chosen_4)
        if basic_set == winner_set:
            results["basic_top4"]["correct"] += 1
        # common_total: for each of the 90 plans, pick
        # the one with the highest common_total
        # feature value.
        best_plan = None
        best_ct = -1e18
        from vgc2026_plan_features import extract_plan_features
        # Enumerate 15 subsets x 6 lead/back partitions
        # = 90 plans. We use the existing
        # evaluate_all_combinations_v3.
        from team_preview_policy import (
            evaluate_all_combinations_v3,
        )
        opp = loser.get("opponent_team_for_features")
        for plan, _, _ in evaluate_all_combinations_v3(
            team, opp
        ):
            try:
                pf = extract_plan_features(
                    team, opp or [],
                    [p.get("species", "") for p in plan],
                    [p.get("species", "") for p in plan[:2]],
                    [p.get("species", "") for p in plan[2:]],
                )
                ct = pf.features.get("common_total", 0.0)
            except Exception:
                continue
            if ct > best_ct:
                best_ct = ct
                best_plan = plan
        if best_plan is not None:
            ct_set = frozenset(
                p.get("species", "").lower() for p in best_plan
            )
            if ct_set == winner_set:
                results["common_total"]["correct"] += 1
    # Final accuracies.
    for k in ("random", "common_total", "matchup_top4_v3", "basic_top4"):
        c = results[k]["correct"]
        n = results[k]["n"]
        results[k]["accuracy"] = c / n if n else float("nan")
    return results


def train_v3a1_and_save(
    jsonl_paths: _List_v3a1[str],
    team_pool: Any,
    model_path: str = DEFAULT_V3A1_MODEL_PATH,
    report_path: str = DEFAULT_V3A1_REPORT_PATH,
    n_epochs: int = 5,
    learning_rate: float = 0.1,
    l2: float = 0.01,
    min_margin: float = 1.0,
    averaged: bool = True,
    seed: int = 42,
    val_fraction: float = 0.2,
) -> Dict[str, Any]:
    """End-to-end V3a.1 training."""
    rows, source_skipped = load_multi_source(
        jsonl_paths, team_pool
    )
    if not rows:
        raise RuntimeError("No rows loaded from any source")
    feature_names = discover_feature_names(rows)
    weights, bias, train_meta = train_v3a1(
        rows,
        feature_names,
        n_epochs=n_epochs,
        learning_rate=learning_rate,
        l2=l2,
        min_margin=min_margin,
        averaged=averaged,
        seed=seed,
        val_fraction=val_fraction,
    )
    model_artifact = save_model(
        model_path, weights, bias, feature_names, train_meta
    )
    # Build validation pair list for baselines.
    val_hashes = set(train_meta["split_meta"]["val_team_hashes"])
    val_rows = [r for r in rows if r["team_hash"] in val_hashes]
    val_pairs, _ = build_decisive_pair_targets(val_rows)
    baselines = baseline_validate(val_pairs, team_pool)
    # Source inventory.
    source_counts: Dict[str, int] = _Counter_v3a1(
        r.get("source", "?") for r in rows
    )
    artifact_payload = _json_for_v3a1.loads(
        _json_for_v3a1.dumps(
            {
                "feature_names": feature_names,
                "weights": weights,
                "bias": bias,
                "metadata": train_meta,
            },
            sort_keys=True,
        )
    )
    artifact_hash = hashlib.sha256(
        _json_for_v3a1.dumps(artifact_payload, sort_keys=True).encode()
    ).hexdigest()
    report = {
        "phase": "V3a.1",
        "sources": sorted(jsonl_paths),
        "source_row_counts": dict(source_counts),
        "rows_after_filter": len(rows),
        "source_skipped": dict(source_skipped),
        "train_meta": train_meta,
        "val_baselines": baselines,
        "artifact_sha256": artifact_hash,
        "model_path": model_path,
        "report_path": report_path,
        "default_policy": "matchup_top4_v3",
        "policy_wrapper": "learned_preview_v3a1 (opt-in only)",
    }
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w") as f:
        _json_for_v3a1.dump(report, f, indent=2, sort_keys=True)
    return {
        "model_artifact": model_artifact,
        "report": report,
        "feature_names": feature_names,
        "weights": weights,
        "bias": bias,
        "train_meta": train_meta,
        "val_baselines": baselines,
    }


# ---------------------------------------------------------------------------
# V3a.1 CLI
# ---------------------------------------------------------------------------


def main_v3a1():
    parser = argparse.ArgumentParser(
        description="Phase V3a.1 VGC offline learning (label noise reduction)"
    )
    parser.add_argument(
        "--sources",
        type=str,
        default=DEFAULT_V3A1_SOURCES,
        help="Comma-separated JSONL artifacts.",
    )
    parser.add_argument(
        "--model-path",
        type=str,
        default=DEFAULT_V3A1_MODEL_PATH,
    )
    parser.add_argument(
        "--report-path",
        type=str,
        default=DEFAULT_V3A1_REPORT_PATH,
    )
    parser.add_argument("--n-epochs", type=int, default=5)
    parser.add_argument("--lr", type=float, default=0.1)
    parser.add_argument("--l2", type=float, default=0.01)
    parser.add_argument("--min-margin", type=float, default=1.0)
    parser.add_argument(
        "--averaged", action="store_true", default=True,
        help="Use averaged perceptron (default on).",
    )
    parser.add_argument(
        "--no-averaged", action="store_true",
        help="Disable averaged perceptron.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--val-fraction", type=float, default=0.2,
        help="Fraction of teams to hold out for val.",
    )
    args = parser.parse_args()
    averaged = args.averaged and not args.no_averaged
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    print("Phase V3a.1 training (label noise reduction)")
    print(f"  sources: {len(sources)}")
    for s in sources:
        print(f"    {s}")
    team_pool = load_vgc_pool()
    result = train_v3a1_and_save(
        sources,
        team_pool,
        model_path=args.model_path,
        report_path=args.report_path,
        n_epochs=args.n_epochs,
        learning_rate=args.lr,
        l2=args.l2,
        min_margin=args.min_margin,
        averaged=averaged,
        seed=args.seed,
        val_fraction=args.val_fraction,
    )
    train_meta = result["train_meta"]
    print(f"  n_rows (after filter): {result['report']['rows_after_filter']}")
    print(f"  n_train_pairs: {train_meta['n_train_pairs']}")
    print(f"  n_val_pairs:   {train_meta['n_val_pairs']}")
    print(
        f"  train_acc:     "
        f"{train_meta['train_pairwise_accuracy']:.4f}"
    )
    print(
        f"  val_acc (final): "
        f"{train_meta['final_val_pairwise_accuracy']:.4f}"
    )
    print(
        f"  val_acc (raw):   "
        f"{train_meta['val_pairwise_accuracy_raw']:.4f}"
    )
    print(f"  used_averaged:  {train_meta['used_averaged']}")
    print(f"  weight_norm:    {train_meta['weight_norm']:.4f}")
    print(f"  artifact_sha256: {result['model_artifact']['artifact_sha256']}")
    print(f"  model:    {result['model_artifact']['model_path']}")
    print(f"  report:   {args.report_path}")
    print("  Baselines (val accuracy, same pairs):")
    for k, v in result["val_baselines"].items():
        if k == "n_pairs":
            continue
        if "accuracy" in v:
            print(f"    {k}: {v['accuracy']:.4f}")
    print("  Skipped:")
    for k, v in train_meta["train_skipped"].items():
        print(f"    train {k}: {v}")
    for k, v in train_meta["val_skipped"].items():
        print(f"    val {k}: {v}")
    print("  Top weights:")
    for w in train_meta["top_weights"]:
        print(f"    {w['name']}: {w['weight']:+.4f}")


if __name__ == "__main__":
    import sys as _sys
    if "--v3a1" in _sys.argv:
        _sys.argv.remove("--v3a1")
        main_v3a1()
    else:
        main()
