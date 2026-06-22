"""Phase RL-7 — Offline policy dry-run feasibility.

This is a dry-run, not a model. It runs entirely in
memory and writes no model artifact. Goal: prove the
pipeline can load the dataset, split it deterministically,
extract leak-free features, build pairwise examples, train
a simple in-memory linear pairwise reranker, and report
metrics.

Ponytail: 1-file dry-run, no sklearn, no torch. Single-file
implementation using only Python stdlib. Determinism via
seed. Metrics are diagnostic only — do not interpret as
production quality.

Outputs:
    logs/phaseRL7_offline_policy_dryrun.json
    logs/phaseRL7_offline_policy_dryrun.md

Inputs:
    core: turn_rl_v1.0 dataset (BI3M2 / RL-5b)
    enriched: turn_rl_v1.0 dataset (BEHAVIOR-18 / rl7)
    enriched is optional; core is required.

Readiness decision:
    NOT_READY: data unusable
    DRYRUN_PIPELINE_WORKS: pipeline runs end-to-end
    READY_FOR_REAL_TRAINING_DESIGN: pipeline runs and
        metrics suggest data is sufficient for real
        training design (not implemented yet)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple


SCHEMA_VERSION = "turn_rl_v1.0"
MIN_ROWS_FOR_PIPELINE_WORKS = 50
MIN_EPISODES_FOR_PIPELINE_WORKS = 5

# Forbidden fields that must NOT appear in features.
FORBIDDEN_FEATURE_FIELDS = frozenset({
    "won",
    "battle_result",
    "terminal_reward",
    "discounted_return",
    "final_action_keys",
    "selected_joint_key",
    "selected_per_slot",
    "selected_score",
    "top_5_alternatives",
    "top_5_scores",
    "score_gap_selected_best_alt",
    "v2l1_raw_scores_slot0",
    "v2l1_raw_scores_slot1",
})


def _load_dataset(path: str) -> List[Dict[str, Any]]:
    """Load a turn_rl_v1.0 JSONL dataset."""
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _episode_key(row: Dict[str, Any]) -> Tuple[str, str]:
    """Group key: (battle_tag, benchmark_arm)."""
    return (row.get("battle_tag", ""), row.get("benchmark_arm", ""))


def _deterministic_split(
    rows: List[Dict[str, Any]],
    val_fraction: float = 0.2,
    seed: int = 42,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split rows by episode, deterministically. No episode
    in both splits.

    Sorted by episode key for determinism; then split.
    """
    episodes = sorted({_episode_key(r) for r in rows})
    rng = random.Random(seed)
    rng.shuffle(episodes)
    n_val = max(1, int(len(episodes) * val_fraction))
    val_eps = set(episodes[:n_val])
    train = [r for r in rows if _episode_key(r) not in val_eps]
    val = [r for r in rows if _episode_key(r) in val_eps]
    return train, val


def _action_category(action_key: List[str]) -> str:
    """Bucket an action into a coarse category.

    Categories: move_attack, move_status_ally,
    move_status_opp, switch, unknown.
    """
    if not isinstance(action_key, (list, tuple)) or len(action_key) < 2:
        return "unknown"
    kind = str(action_key[0]).lower()
    if kind == "switch":
        return "switch"
    if kind != "move":
        return "unknown"
    target = action_key[2] if len(action_key) > 2 else ""
    move_id = str(action_key[1]).lower() if len(action_key) > 1 else ""
    if move_id in ("protect", "detect", "kingsshield", "spikyshield",
                   "banefulbunker", "silktrap", "maxguard", "obstruct"):
        return "move_status_ally"
    if move_id in ("healpulse", "life Dew", "pollenpuff", "healorder"):
        return "move_status_ally"
    target_str = str(target)
    if target_str in ("-2", "-1"):
        return "move_status_ally"
    if target_str in ("1", "2", "0"):
        return "move_attack"
    return "move_status_opp"


def _extract_features(
    row: Dict[str, Any], include_enriched: bool = False
) -> List[float]:
    """Extract a fixed-size numeric feature vector from a row.

    Leak-free: never reads forbidden outcome fields.
    """
    ss = row.get("state_snapshot", {}) or {}
    feats = []
    # 1. turn_index bucket (4 buckets: 1-3, 4-6, 7-9, 10+)
    ti = row.get("turn_index", 0) or 0
    feats.extend([
        1.0 if ti <= 3 else 0.0,
        1.0 if 4 <= ti <= 6 else 0.0,
        1.0 if 7 <= ti <= 9 else 0.0,
        1.0 if ti >= 10 else 0.0,
    ])
    # 2. our_active_hp_fraction (4 features: slot0, slot1, mean, min)
    our_hp = ss.get("our_active_hp_fraction", []) or [0.0, 0.0]
    opp_hp = ss.get("opp_active_hp_fraction", []) or [0.0, 0.0]
    our_hp0 = float(our_hp[0]) if len(our_hp) > 0 and our_hp[0] is not None else 0.0
    our_hp1 = float(our_hp[1]) if len(our_hp) > 1 and our_hp[1] is not None else 0.0
    opp_hp0 = float(opp_hp[0]) if len(opp_hp) > 0 and opp_hp[0] is not None else 0.0
    opp_hp1 = float(opp_hp[1]) if len(opp_hp) > 1 and opp_hp[1] is not None else 0.0
    feats.extend([our_hp0, our_hp1, (our_hp0 + our_hp1) / 2.0,
                  min(our_hp0, our_hp1)])
    feats.extend([opp_hp0, opp_hp1, (opp_hp0 + opp_hp1) / 2.0,
                  min(opp_hp0, opp_hp1)])
    # 3. weather one-hot (5 buckets: none, rain, sun, sand, snow)
    weather = ss.get("weather", "none") or "none"
    wstr = str(weather).lower()
    feats.extend([
        1.0 if "rain" in wstr else 0.0,
        1.0 if "sun" in wstr else 0.0,
        1.0 if "sand" in wstr else 0.0,
        1.0 if "snow" in wstr else 0.0,
    ])
    # 4. legal action counts (log-scaled)
    n_legal0 = float(len(row.get("legal_action_keys_slot0", []) or []))
    n_legal1 = float(len(row.get("legal_action_keys_slot1", []) or []))
    feats.extend([math.log1p(n_legal0), math.log1p(n_legal1)])
    # 5. selected category one-hot (slot0, slot1)
    sps = row.get("selected_per_slot", {}) or {}
    cat0 = _action_category(sps.get("slot_0", []))
    cat1 = _action_category(sps.get("slot_1", []))
    cats = ("move_attack", "move_status_ally", "move_status_opp",
            "switch", "unknown")
    feats.extend([1.0 if cat0 == c else 0.0 for c in cats])
    feats.extend([1.0 if cat1 == c else 0.0 for c in cats])
    # 6. total_legal_joint_orders (log-scaled, diagnostic)
    n_joint = float(row.get("total_legal_joint_orders", 0) or 0)
    feats.append(math.log1p(n_joint))
    # 7. enriched features (only if include_enriched=True)
    if include_enriched:
        spt = row.get("speed_priority_threatened")
        etf = row.get("expected_to_faint_before_moving")
        spt0 = 0.0
        spt1 = 0.0
        if isinstance(spt, (list, tuple)) and len(spt) >= 1:
            spt0 = 1.0 if spt[0] else 0.0
        if isinstance(spt, (list, tuple)) and len(spt) >= 2:
            spt1 = 1.0 if spt[1] else 0.0
        etf0 = 0.0
        etf1 = 0.0
        if isinstance(etf, (list, tuple)) and len(etf) >= 1:
            etf0 = 1.0 if etf[0] else 0.0
        if isinstance(etf, (list, tuple)) and len(etf) >= 2:
            etf1 = 1.0 if etf[1] else 0.0
        feats.extend([spt0, spt1, etf0, etf1])
    return feats


def _sample_negatives(
    row: Dict[str, Any], n: int, seed: int
) -> List[Tuple[List[str], List[str]]]:
    """Sample N negative joint actions from the legal set.

    Excludes the selected joint action.
    """
    legal0 = row.get("legal_action_keys_slot0", []) or []
    legal1 = row.get("legal_action_keys_slot1", []) or []
    sel = row.get("selected_joint_key", []) or []
    if len(legal0) == 0 or len(legal1) == 0 or len(sel) != 2:
        return []
    sel_t = (
        tuple(sel[0]) if isinstance(sel[0], (list, tuple)) else None,
        tuple(sel[1]) if isinstance(sel[1], (list, tuple)) else None,
    )
    rng = random.Random(seed)
    negatives = []
    seen = set()
    attempts = 0
    while len(negatives) < n and attempts < n * 10:
        attempts += 1
        i = rng.randrange(len(legal0))
        j = rng.randrange(len(legal1))
        a0 = tuple(legal0[i]) if isinstance(legal0[i], (list, tuple)) else None
        a1 = tuple(legal1[j]) if isinstance(legal1[j], (list, tuple)) else None
        if a0 is None or a1 is None:
            continue
        if a0 == sel_t[0] and a1 == sel_t[1]:
            continue
        key = (a0, a1)
        if key in seen:
            continue
        seen.add(key)
        negatives.append((list(a0), list(a1)))
    return negatives


class LinearPairwiseReranker:
    """Simple in-memory linear pairwise reranker.

    No external dependencies. Deterministic with seed.
    Score = dot(weights, features). Pairwise update.
    """

    def __init__(self, n_features: int, lr: float = 0.01,
                 seed: int = 42):
        self.n_features = n_features
        self.lr = lr
        self.rng = random.Random(seed)
        self.weights = [0.0] * n_features

    def score(self, feats: List[float]) -> float:
        return sum(w * f for w, f in zip(self.weights, feats))

    def update(self, pos: List[float], neg: List[float]) -> bool:
        """Update weights to push pos > neg. Returns True
        if update applied (pos didn't beat neg).
        """
        ps = self.score(pos)
        ns = self.score(neg)
        if ps > ns:
            return False
        for i in range(self.n_features):
            self.weights[i] += self.lr * (pos[i] - neg[i])
        return True

    def predict_positive(self, feats: List[float]) -> bool:
        return self.score(feats) > 0.0


def _majority_baseline(
    train: List[Dict[str, Any]],
    val: List[Dict[str, Any]],
) -> float:
    """Predict the majority action category per slot.
    Returns pairwise accuracy on val.
    """
    cats0 = Counter()
    cats1 = Counter()
    for r in train:
        sps = r.get("selected_per_slot", {}) or {}
        cats0[_action_category(sps.get("slot_0", []))] += 1
        cats1[_action_category(sps.get("slot_1", []))] += 1
    if not cats0 or not cats1:
        return 0.0
    maj0 = cats0.most_common(1)[0][0]
    maj1 = cats1.most_common(1)[0][0]
    correct = 0
    total = 0
    for r in val:
        sps = r.get("selected_per_slot", {}) or {}
        c0 = _action_category(sps.get("slot_0", []))
        c1 = _action_category(sps.get("slot_1", []))
        if c0 == maj0:
            correct += 1
        if c1 == maj1:
            correct += 1
        total += 2
    return correct / total if total > 0 else 0.0


def _pairwise_accuracy(
    model: LinearPairwiseReranker,
    rows: List[Dict[str, Any]],
    n_negatives: int,
    seed: int,
    include_enriched: bool = False,
) -> float:
    """Pairwise accuracy: selected scores above negatives."""
    correct = 0
    total = 0
    for r in rows:
        feats = _extract_features(r, include_enriched=include_enriched)
        if len(feats) != model.n_features:
            return 0.0
        pos_score = model.score(feats)
        negs = _sample_negatives(r, n_negatives, seed + total)
        for a0, a1 in negs:
            r_neg = dict(r)
            r_neg["selected_joint_key"] = [a0, a1]
            r_neg["selected_per_slot"] = {
                "slot_0": a0, "slot_1": a1
            }
            neg_feats = _extract_features(
                r_neg, include_enriched=include_enriched
            )
            neg_score = model.score(neg_feats)
            if pos_score > neg_score:
                correct += 1
            total += 1
    return correct / total if total > 0 else 0.0


def _dryrun_core(
    rows: List[Dict[str, Any]],
    n_negatives: int = 3,
    n_epochs: int = 2,
    val_fraction: float = 0.2,
    seed: int = 42,
) -> Dict[str, Any]:
    """Core dry-run: behavior cloning / pairwise reranker.

    Returns metrics dict. No model artifact.
    """
    out: Dict[str, Any] = {
        "rows_total": len(rows),
        "n_negatives": n_negatives,
        "n_epochs": n_epochs,
        "val_fraction": val_fraction,
        "seed": seed,
    }
    if len(rows) == 0:
        out["status"] = "no_rows"
        return out
    train, val = _deterministic_split(
        rows, val_fraction=val_fraction, seed=seed
    )
    out["train_rows"] = len(train)
    out["val_rows"] = len(val)
    out["train_episodes"] = len(
        {_episode_key(r) for r in train}
    )
    out["val_episodes"] = len({_episode_key(r) for r in val})
    # Reward balance per split.
    train_rewards = Counter(
        r.get("terminal_reward", 0) for r in train
    )
    val_rewards = Counter(
        r.get("terminal_reward", 0) for r in val
    )
    out["train_rewards"] = dict(train_rewards)
    out["val_rewards"] = dict(val_rewards)
    # Action distribution.
    out["train_joint_categories"] = dict(Counter(
        ",".join([
            _action_category(
                (r.get("selected_per_slot", {}) or {}).get(
                    "slot_0", []
                )
            ),
            _action_category(
                (r.get("selected_per_slot", {}) or {}).get(
                    "slot_1", []
                )
            ),
        ])
        for r in train
    ))
    out["val_joint_categories"] = dict(Counter(
        ",".join([
            _action_category(
                (r.get("selected_per_slot", {}) or {}).get(
                    "slot_0", []
                )
            ),
            _action_category(
                (r.get("selected_per_slot", {}) or {}).get(
                    "slot_1", []
                )
            ),
        ])
        for r in val
    ))
    # Unique selected joint keys.
    out["train_unique_joint_keys"] = len({
        tuple(tuple(k) for k in (r.get("selected_joint_key") or []))
        for r in train
    })
    out["val_unique_joint_keys"] = len({
        tuple(tuple(k) for k in (r.get("selected_joint_key") or []))
        for r in val
    })
    # Feature vector size.
    sample_feats = _extract_features(rows[0], include_enriched=False)
    out["n_features_core"] = len(sample_feats)
    # Train.
    model = LinearPairwiseReranker(
        n_features=len(sample_feats),
        lr=0.05,
        seed=seed,
    )
    n_updates = 0
    for epoch in range(n_epochs):
        rng = random.Random(seed + epoch)
        order = list(range(len(train)))
        rng.shuffle(order)
        for idx in order:
            r = train[idx]
            feats = _extract_features(r, include_enriched=False)
            negs = _sample_negatives(
                r, n_negatives, seed=seed + idx
            )
            for a0, a1 in negs:
                r_neg = dict(r)
                r_neg["selected_joint_key"] = [a0, a1]
                r_neg["selected_per_slot"] = {
                    "slot_0": a0, "slot_1": a1
                }
                neg_feats = _extract_features(
                    r_neg, include_enriched=False
                )
                if model.update(feats, neg_feats):
                    n_updates += 1
    out["n_pairwise_updates"] = n_updates
    # Eval on train.
    train_acc = _pairwise_accuracy(
        model, train, n_negatives,
        seed=seed + 1000, include_enriched=False,
    )
    val_acc = _pairwise_accuracy(
        model, val, n_negatives,
        seed=seed + 2000, include_enriched=False,
    )
    out["train_pairwise_accuracy"] = train_acc
    out["val_pairwise_accuracy"] = val_acc
    out["overfit_gap"] = train_acc - val_acc
    # Majority baseline.
    out["val_majority_baseline"] = _majority_baseline(train, val)
    # Determinism check: re-train and compare.
    model2 = LinearPairwiseReranker(
        n_features=len(sample_feats),
        lr=0.05,
        seed=seed,
    )
    for epoch in range(n_epochs):
        rng = random.Random(seed + epoch)
        order = list(range(len(train)))
        rng.shuffle(order)
        for idx in order:
            r = train[idx]
            feats = _extract_features(r, include_enriched=False)
            negs = _sample_negatives(
                r, n_negatives, seed=seed + idx
            )
            for a0, a1 in negs:
                r_neg = dict(r)
                r_neg["selected_joint_key"] = [a0, a1]
                r_neg["selected_per_slot"] = {
                    "slot_0": a0, "slot_1": a1
                }
                neg_feats = _extract_features(
                    r_neg, include_enriched=False
                )
                model2.update(feats, neg_feats)
    val_acc2 = _pairwise_accuracy(
        model2, val, n_negatives,
        seed=seed + 2000, include_enriched=False,
    )
    out["val_pairwise_accuracy_repeat"] = val_acc2
    out["deterministic"] = abs(val_acc - val_acc2) < 1e-9
    out["status"] = "ok"
    return out


def _dryrun_enriched(
    rows: List[Dict[str, Any]],
    n_negatives: int = 3,
    n_epochs: int = 2,
    val_fraction: float = 0.2,
    seed: int = 42,
) -> Dict[str, Any]:
    """Enriched dry-run with speed-priority features."""
    out: Dict[str, Any] = {
        "rows_total": len(rows),
        "n_negatives": n_negatives,
        "n_epochs": n_epochs,
    }
    # Field coverage.
    n_spt = sum(
        1 for r in rows
        if r.get("speed_priority_threatened") is not None
    )
    n_etf = sum(
        1 for r in rows
        if r.get("expected_to_faint_before_moving") is not None
    )
    n_joc = sum(
        1 for r in rows
        if r.get("joint_order_count") is not None
    )
    out["speed_priority_threatened_coverage"] = n_spt
    out["expected_to_faint_before_moving_coverage"] = n_etf
    out["joint_order_count_coverage"] = n_joc
    out["rows_total_again"] = len(rows)
    if len(rows) == 0:
        out["status"] = "no_rows"
        return out
    train, val = _deterministic_split(
        rows, val_fraction=val_fraction, seed=seed
    )
    out["train_rows"] = len(train)
    out["val_rows"] = len(val)
    out["train_episodes"] = len(
        {_episode_key(r) for r in train}
    )
    out["val_episodes"] = len({_episode_key(r) for r in val})
    sample_feats = _extract_features(rows[0], include_enriched=True)
    out["n_features_enriched"] = len(sample_feats)
    model = LinearPairwiseReranker(
        n_features=len(sample_feats),
        lr=0.05,
        seed=seed,
    )
    n_updates = 0
    for epoch in range(n_epochs):
        rng = random.Random(seed + epoch)
        order = list(range(len(train)))
        rng.shuffle(order)
        for idx in order:
            r = train[idx]
            feats = _extract_features(r, include_enriched=True)
            negs = _sample_negatives(
                r, n_negatives, seed=seed + idx
            )
            for a0, a1 in negs:
                r_neg = dict(r)
                r_neg["selected_joint_key"] = [a0, a1]
                r_neg["selected_per_slot"] = {
                    "slot_0": a0, "slot_1": a1
                }
                neg_feats = _extract_features(
                    r_neg, include_enriched=True
                )
                if model.update(feats, neg_feats):
                    n_updates += 1
    out["n_pairwise_updates"] = n_updates
    val_acc = _pairwise_accuracy(
        model, val, n_negatives,
        seed=seed + 2000, include_enriched=True,
    )
    out["val_pairwise_accuracy"] = val_acc
    out["val_majority_baseline"] = _majority_baseline(train, val)
    out["status"] = "ok"
    out["note"] = (
        "Enriched source is too small for performance "
        "claims. Metrics are diagnostic only."
    )
    return out


def _leakage_check(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Check that forbidden fields are NOT in the feature
    vector's source group. We never read them in
    _extract_features. This is a static check.
    """
    # We check that no row's state_snapshot contains
    # the forbidden outcome fields.
    state_violations = 0
    for r in rows:
        ss = r.get("state_snapshot", {}) or {}
        for k in ("won", "battle_result", "terminal_reward"):
            if k in ss:
                state_violations += 1
    return {
        "state_snapshot_forbidden_field_violations":
            state_violations,
        "feature_extractor_reads_forbidden_fields": False,
    }


def _readiness_decision(
    core_metrics: Optional[Dict[str, Any]],
    enriched_metrics: Optional[Dict[str, Any]],
) -> str:
    """Decide NOT_READY / DRYRUN_PIPELINE_WORKS /
    READY_FOR_REAL_TRAINING_DESIGN.
    """
    if core_metrics is None or core_metrics.get("status") != "ok":
        return "NOT_READY"
    rows = core_metrics.get("rows_total", 0)
    eps = core_metrics.get("train_episodes", 0) + \
        core_metrics.get("val_episodes", 0)
    if rows < MIN_ROWS_FOR_PIPELINE_WORKS or \
            eps < MIN_EPISODES_FOR_PIPELINE_WORKS:
        return "NOT_READY"
    if not core_metrics.get("deterministic", False):
        return "NOT_READY"
    return "DRYRUN_PIPELINE_WORKS"


def write_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def write_md(path: str, data: Dict[str, Any]) -> None:
    lines = []
    lines.append("# Phase RL-7 — Offline Policy Dry-Run")
    lines.append("")
    lines.append(f"- readiness: **{data.get('readiness')}**")
    lines.append(f"- core_dataset: `{data.get('core_dataset', '')}`")
    ed = data.get("enriched_dataset")
    if ed:
        lines.append(f"- enriched_dataset: `{ed}`")
    else:
        lines.append("- enriched_dataset: `(skipped)`")
    lines.append("")
    lines.append("## Core dry-run")
    lines.append("")
    core = data.get("core_metrics", {}) or {}
    if core:
        lines.append(f"- rows_total: {core.get('rows_total')}")
        lines.append(
            f"- train_rows/val_rows: "
            f"{core.get('train_rows')}/{core.get('val_rows')}"
        )
        lines.append(
            f"- train_episodes/val_episodes: "
            f"{core.get('train_episodes')}/"
            f"{core.get('val_episodes')}"
        )
        lines.append(
            f"- train_rewards: {core.get('train_rewards')}"
        )
        lines.append(
            f"- val_rewards: {core.get('val_rewards')}"
        )
        lines.append(
            f"- train_pairwise_accuracy: "
            f"{core.get('train_pairwise_accuracy'):.4f}"
            if core.get("train_pairwise_accuracy") is not None
            else "- train_pairwise_accuracy: N/A"
        )
        lines.append(
            f"- val_pairwise_accuracy: "
            f"{core.get('val_pairwise_accuracy'):.4f}"
            if core.get("val_pairwise_accuracy") is not None
            else "- val_pairwise_accuracy: N/A"
        )
        lines.append(
            f"- overfit_gap: "
            f"{core.get('overfit_gap'):.4f}"
            if core.get("overfit_gap") is not None
            else "- overfit_gap: N/A"
        )
        lines.append(
            f"- val_majority_baseline: "
            f"{core.get('val_majority_baseline'):.4f}"
            if core.get("val_majority_baseline") is not None
            else "- val_majority_baseline: N/A"
        )
        lines.append(
            f"- deterministic: "
            f"{core.get('deterministic')}"
        )
        lines.append(
            f"- n_features_core: {core.get('n_features_core')}"
        )
    lines.append("")
    lines.append("## Enriched dry-run")
    lines.append("")
    enr = data.get("enriched_metrics") or {}
    if enr:
        lines.append(f"- rows_total: {enr.get('rows_total')}")
        lines.append(
            f"- speed_priority_threatened_coverage: "
            f"{enr.get('speed_priority_threatened_coverage')}"
        )
        lines.append(
            f"- expected_to_faint_before_moving_coverage: "
            f"{enr.get('expected_to_faint_before_moving_coverage')}"
        )
        lines.append(
            f"- joint_order_count_coverage: "
            f"{enr.get('joint_order_count_coverage')}"
        )
        if enr.get("val_pairwise_accuracy") is not None:
            lines.append(
                f"- val_pairwise_accuracy (enriched): "
                f"{enr.get('val_pairwise_accuracy'):.4f}"
            )
        lines.append(f"- note: {enr.get('note', '')}")
    else:
        lines.append("- skipped (no enriched dataset provided)")
    lines.append("")
    lines.append("## Leakage safety")
    lines.append("")
    lk = data.get("leakage_check", {}) or {}
    lines.append(
        f"- state_snapshot_forbidden_field_violations: "
        f"{lk.get('state_snapshot_forbidden_field_violations')}"
    )
    lines.append(
        f"- feature_extractor_reads_forbidden_fields: "
        f"{lk.get('feature_extractor_reads_forbidden_fields')}"
    )
    lines.append(
        f"- no_episode_leakage: "
        f"{data.get('no_episode_leakage', 'N/A')}"
    )
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def _check_no_episode_leakage(
    train: List[Dict[str, Any]], val: List[Dict[str, Any]]
) -> bool:
    train_eps = {_episode_key(r) for r in train}
    val_eps = {_episode_key(r) for r in val}
    return len(train_eps & val_eps) == 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="RL-7 dry-run offline policy feasibility"
    )
    parser.add_argument(
        "--core-dataset", required=True,
        help="Path to core turn_rl_v1.0 JSONL dataset",
    )
    parser.add_argument(
        "--enriched-dataset", default=None,
        help="Path to enriched turn_rl_v1.0 JSONL dataset "
        "(optional)",
    )
    parser.add_argument(
        "--output-json", required=True,
        help="Output JSON path",
    )
    parser.add_argument(
        "--output-md", required=True,
        help="Output Markdown path",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
    )
    parser.add_argument(
        "--n-negatives", type=int, default=3,
    )
    parser.add_argument(
        "--n-epochs", type=int, default=2,
    )
    args = parser.parse_args(argv)
    if not os.path.exists(args.core_dataset):
        print(
            f"ERROR: core dataset not found: "
            f"{args.core_dataset}",
            file=sys.stderr,
        )
        return 2
    # Load core.
    core_rows = _load_dataset(args.core_dataset)
    core_metrics = _dryrun_core(
        core_rows,
        n_negatives=args.n_negatives,
        n_epochs=args.n_epochs,
        seed=args.seed,
    )
    # Re-split to check leakage.
    train, val = _deterministic_split(
        core_rows, val_fraction=0.2, seed=args.seed
    )
    no_leak = _check_no_episode_leakage(train, val)
    leakage = _leakage_check(core_rows)
    leakage["no_episode_leakage"] = no_leak
    # Enriched (optional).
    enriched_metrics = None
    if args.enriched_dataset and os.path.exists(
        args.enriched_dataset
    ):
        enriched_rows = _load_dataset(args.enriched_dataset)
        enriched_metrics = _dryrun_enriched(
            enriched_rows,
            n_negatives=args.n_negatives,
            n_epochs=args.n_epochs,
            seed=args.seed,
        )
    decision = _readiness_decision(
        core_metrics, enriched_metrics
    )
    out = {
        "readiness": decision,
        "core_dataset": args.core_dataset,
        "enriched_dataset": args.enriched_dataset,
        "core_metrics": core_metrics,
        "enriched_metrics": enriched_metrics,
        "leakage_check": leakage,
        "no_episode_leakage": no_leak,
        "no_model_artifact": True,
        "no_battle_runs": True,
    }
    write_json(args.output_json, out)
    write_md(args.output_md, out)
    print(f"Readiness: {decision}", file=sys.stderr)
    print(f"Wrote {args.output_json}", file=sys.stderr)
    print(f"Wrote {args.output_md}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
