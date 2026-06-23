"""Phase RL-DATA-3f — BC dry-run analysis on default vs diversity-merged datasets.

Runs a disposable behavior-cloning-style dry-run
analysis on the existing v1.1 datasets to answer:

Can a simple model learn the selected action
distribution, including setup / weather / support
actions, from the merged RL-DATA-3e dataset?

This is analysis-only. **NOT** RL training. **NOT** Phase 7.
**NOT** production model training. This script does
**NOT** save a model artifact. Trained models are
in-memory only and discarded after evaluation.

If scikit-learn is available, the script uses
``LogisticRegression`` / ``DecisionTreeClassifier`` for
the BC dry-run. If scikit-learn is not available, the
script implements a simple no-dependency frequency-table
baseline that predicts the action kind conditioned on
the legal action availability signature.

Leakage controls:

* No final outcome / terminal_win_loss in features.
* No reward fields in features.
* No selected action as a feature.
* No future HP delta in features.
* No species-based ability inference.
* No official server provenance.
* The "without exploration/source features" result
  is the more honest evaluation.

Usage:

```bash
./venv/bin/python scripts/analyze/analyze_rl_data_3f_bc_dryrun.py \
    --datasets-c  logs/rl_data_3c_dataset.jsonl \
    --datasets-e  logs/rl_data_3e_merged_dataset.jsonl \
    --output-json logs/rl_data_3f_bc_dryrun_analysis.json
```

Output paths:

* ``logs/rl_data_3f_bc_dryrun_analysis.json`` (machine-readable)
* Script prints a human-readable summary to stdout.
"""

import argparse
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(
    0, os.path.join(PROJECT_ROOT, "scripts", "analyze")
)

# Reuse the action-distribution helpers.
from analyze_rl_data_3d_action_distribution import (  # noqa: E402
    _action_kind,
    _is_protect_move,
    _is_setup_move,
    _is_support_move,
    _is_weather_setter,
    _move_id_norm,
    _norm_move_id,
)


# Local helper: terrain-setter detection.
# The 3d script does not export this; we define it here
# so the 3f BC dry-run can classify terrain setters.
TERRAIN_SETTER_MOVES = frozenset({
    "electricterrain", "grassyterrain",
    "mistyterrain", "psychicterrain",
})


def _is_terrain_setter(mid_norm: str) -> bool:
    return mid_norm in TERRAIN_SETTER_MOVES

# ---- Leakage-excluded fields (NEVER used as features) ----
LEAKAGE_FIELDS = frozenset({
    # Final outcome / reward
    "won", "battle_result", "terminal_reward",
    "terminal_win_loss", "discounted_return",
    # Future state
    "turn_delta_hp", "faint_caused", "faint_suffered",
    # Selected action (would directly identify label)
    "selected_joint_key", "selected_per_slot",
    "selected_action_kind", "selected_action_move_id",
    "selected_action_target_position",
    "selected_action_species", "selected_action_only_legal",
    "selected_score", "selected_joint_order",
    "v4a_selected_joint_key", "v4a_final_action_keys",
    "v2l1_selected_joint_key", "v2l1_final_action_keys",
    "final_action_keys",
    # Server provenance
    "local_only_provenance",  # always True; not useful
    # Ability inference
    "used_species_ability_inference",
    # Exploration / source flags (for the honest run)
    "dataset_source", "exploration_enabled",
    "exploration_candidate_group", "exploration_seed",
    "exploration_rate",
})


# ---- Action-kind label vocabulary ----
ACTION_KIND_LABELS = [
    "attack", "protect", "setup", "weather_setter",
    "terrain_setter", "support_other", "switch", "pass",
    "unknown",
]


def _classify_action_kind_label(mid_norm: str, kind: str) -> str:
    """Map a single move's normalized id + action kind
    to a label in ``ACTION_KIND_LABELS``.
    """
    if kind == "switch":
        return "switch"
    if kind in ("pass", "unknown"):
        # Both are "no real move" labels.
        if kind == "pass":
            return "pass"
        return "unknown"
    if kind != "move":
        return "unknown"
    if _is_setup_move(mid_norm):
        return "setup"
    if _is_weather_setter(mid_norm):
        return "weather_setter"
    if _is_terrain_setter(mid_norm):
        return "terrain_setter"
    if _is_protect_move(mid_norm):
        return "protect"
    if _is_support_move(mid_norm):
        return "support_other"
    return "attack"


def _label_for_selected_joint(
    sel0: Any, sel1: Any,
) -> str:
    """Return the selected_joint_primary_kind label
    for a 2-slot selected joint.
    """
    k0 = _action_kind(sel0)
    k1 = _action_kind(sel1)
    m0 = _move_id_norm(sel0)
    m1 = _move_id_norm(sel1)
    # Pure switch / switch
    if k0 == "switch" and k1 == "switch":
        return "double_switch"
    if k0 == "switch" and k1 in ("pass", "unknown"):
        return "move_plus_switch"  # actual: switch + pass
    if k1 == "switch" and k0 in ("pass", "unknown"):
        return "move_plus_switch"
    if k0 in ("pass", "unknown") and k1 in ("pass", "unknown"):
        return "single_move_plus_pass"  # actual: pass+pass
    if k0 == "move" and k1 in ("pass", "unknown"):
        return "single_move_plus_pass"
    if k1 == "move" and k0 in ("pass", "unknown"):
        return "single_move_plus_pass"
    if k0 == "move" and k1 == "switch":
        return "move_plus_switch"
    if k1 == "move" and k0 == "switch":
        return "move_plus_switch"
    if k0 == "move" and k1 == "move":
        p0 = _is_protect_move(m0)
        p1 = _is_protect_move(m1)
        if p0 and p1:
            return "double_protect"
        if p0 or p1:
            return "attack_plus_protect"
        s0 = _is_setup_move(m0)
        s1 = _is_setup_move(m1)
        if s0 or s1:
            return "attack_plus_setup"
        w0 = _is_weather_setter(m0)
        w1 = _is_weather_setter(m1)
        if w0 or w1:
            return "attack_plus_weather_setter"
        sup0 = _is_support_move(m0)
        sup1 = _is_support_move(m1)
        if sup0 or sup1:
            return "attack_plus_support"
        return "double_attack"
    return "mixed_other"


# ---- Feature extraction ----
def _legal_signature(legal: List) -> Dict[str, bool]:
    """Return a dict of legal-availability booleans."""
    sig = {
        "has_legal_attack": False,
        "has_legal_protect": False,
        "has_legal_switch": False,
        "has_legal_setup": False,
        "has_legal_weather_setter": False,
        "has_legal_terrain_setter": False,
        "has_legal_support": False,
        "has_legal_pass": False,
    }
    for k in legal or []:
        if not isinstance(k, (list, tuple)) or len(k) < 2:
            continue
        kind = _action_kind(k)
        move = _move_id_norm(k)
        if kind == "move":
            sig["has_legal_attack"] = True
            if _is_protect_move(move):
                sig["has_legal_protect"] = True
            if _is_setup_move(move):
                sig["has_legal_setup"] = True
            if _is_weather_setter(move):
                sig["has_legal_weather_setter"] = True
            if _is_terrain_setter(move):
                sig["has_legal_terrain_setter"] = True
            if _is_support_move(move):
                sig["has_legal_support"] = True
        elif kind == "switch":
            sig["has_legal_switch"] = True
        elif kind in ("pass", "unknown"):
            sig["has_legal_pass"] = True
    return sig


def _legal_counts(legal: List) -> Dict[str, int]:
    """Return counts of legal action kinds."""
    counts = {k: 0 for k in ACTION_KIND_LABELS}
    counts["n_legal_total"] = 0
    for k in legal or []:
        if not isinstance(k, (list, tuple)) or len(k) < 2:
            continue
        kind = _action_kind(k)
        move = _move_id_norm(k)
        label = _classify_action_kind_label(move, kind)
        counts[label] = counts.get(label, 0) + 1
        counts["n_legal_total"] += 1
    return counts


def _state_features(state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract state features that are safe (no leakage)."""
    feats = {}
    if not isinstance(state, dict):
        return feats
    weather = state.get("weather")
    if isinstance(weather, str):
        feats["weather_is_raindance"] = (weather == "raindance")
        feats["weather_is_sunnyday"] = (weather == "sunnyday")
        feats["weather_is_sandstorm"] = (weather == "sandstorm")
        feats["weather_is_none"] = (weather in ("none", None, ""))
    fields = state.get("fields", [])
    if isinstance(fields, list) and fields:
        feats["terrain_active"] = True
    else:
        feats["terrain_active"] = False
    return feats


def extract_features(
    row: Dict[str, Any],
    include_exploration_features: bool = False,
) -> Tuple[Dict[str, Any], Set[str]]:
    """Extract features from a dataset row.

    Returns ``(features, leakage_fields_present)``.

    Leakage checks: any field in ``LEAKAGE_FIELDS`` that
    appears in the row is reported. The features dict
    never includes those fields (defense in depth).
    """
    feats = {}
    leakage_present: Set[str] = set()
    # Check for leakage in the row
    for f in LEAKAGE_FIELDS:
        if f in row:
            leakage_present.add(f)
    # Legal availability
    legal0 = row.get("legal_action_keys_slot0", [])
    legal1 = row.get("legal_action_keys_slot1", [])
    sig0 = _legal_signature(legal0)
    sig1 = _legal_signature(legal1)
    for k, v in sig0.items():
        feats[f"{k}_slot0"] = v
    for k, v in sig1.items():
        feats[f"{k}_slot1"] = v
    # Legal counts
    counts0 = _legal_counts(legal0)
    counts1 = _legal_counts(legal1)
    for k, v in counts0.items():
        feats[f"{k}_slot0"] = v
    for k, v in counts1.items():
        feats[f"{k}_slot1"] = v
    # State features
    state = row.get("state_snapshot", {})
    if isinstance(state, dict):
        for k, v in _state_features(state).items():
            feats[f"state_{k}"] = v
    # HP fractions (legal pre-action state)
    for slot_key, slot_label in (
        ("our_active_hp_fraction_slot0", "our_hp0"),
        ("our_active_hp_fraction_slot1", "our_hp1"),
        ("opp_active_hp_fraction_slot0", "opp_hp0"),
        ("opp_active_hp_fraction_slot1", "opp_hp1"),
    ):
        if slot_key in state and isinstance(state[slot_key], (int, float)):
            feats[slot_label] = float(state[slot_key])
    # Score features (v2l1 max score per category) — safe
    # (these are the bot's score estimates, not the
    # selected action).
    for slot_key, slot_label in (
        ("v2l1_raw_scores_slot0", "slot0"),
        ("v2l1_raw_scores_slot1", "slot1"),
    ):
        scores = row.get(slot_key) or {}
        if not isinstance(scores, dict) or not scores:
            continue
        # We do NOT include the score for the selected
        # action (that would leak the label). We include
        # the max and min scores and the count.
        vals = [v for v in scores.values() if isinstance(v, (int, float))]
        if vals:
            feats[f"score_max_{slot_label}"] = max(vals)
            feats[f"score_min_{slot_label}"] = min(vals)
            feats[f"score_n_{slot_label}"] = len(vals)
    # Exploration / source features (optional, for the
    # less-honest run).
    if include_exploration_features:
        feats["dataset_source_3c"] = (
            row.get("dataset_source", "") == "rl_data_3c_default"
        )
        feats["dataset_source_3e"] = (
            row.get("dataset_source", "") == "rl_data_3e_exploration"
        )
        feats["exploration_triggered"] = bool(
            row.get("exploration_triggered", False)
        )
        exp_group = row.get("exploration_candidate_group", "none")
        feats[f"exploration_group_{exp_group}"] = True
    return feats, leakage_present


def extract_labels(row: Dict[str, Any]) -> Dict[str, str]:
    """Extract ground-truth labels from a dataset row."""
    sel = row.get("selected_joint_key", [])
    sel0 = sel[0] if len(sel) > 0 else None
    sel1 = sel[1] if len(sel) > 1 else None
    primary = _label_for_selected_joint(sel0, sel1)
    k0 = _action_kind(sel0)
    k1 = _action_kind(sel1)
    m0 = _move_id_norm(sel0)
    m1 = _move_id_norm(sel1)
    slot0_label = _classify_action_kind_label(m0, k0)
    slot1_label = _classify_action_kind_label(m1, k1)
    return {
        "primary": primary,
        "slot0": slot0_label,
        "slot1": slot1_label,
    }


# ---- Metrics ----
def _safe_div(num: float, denom: float) -> float:
    if denom == 0:
        return 0.0
    return num / denom


def _per_class_metrics(
    y_true: List[str], y_pred: List[str],
    labels: List[str],
) -> Dict[str, Dict[str, float]]:
    """Compute precision / recall / F1 per class.

    Returns a dict ``{label: {precision, recall, f1, support}}``.
    """
    out: Dict[str, Dict[str, float]] = {}
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        support = sum(1 for t in y_true if t == label)
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        out[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }
    return out


def _confusion_matrix(
    y_true: List[str], y_pred: List[str], labels: List[str],
) -> Dict[str, Dict[str, int]]:
    """Compute a confusion matrix as a dict of dicts."""
    cm = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(y_true, y_pred):
        if t in cm and p in cm[t]:
            cm[t][p] += 1
    return cm


def _accuracy(y_true: List[str], y_pred: List[str]) -> float:
    if not y_true:
        return 0.0
    return _safe_div(
        sum(1 for t, p in zip(y_true, y_pred) if t == p),
        len(y_true),
    )


# ---- Baselines ----
def majority_baseline(
    rows: List[Dict[str, Any]], label_key: str,
) -> Dict[str, Any]:
    """Majority class baseline: predict the most
    common label for all rows.
    """
    counter: Counter = Counter()
    for r in rows:
        labels = extract_labels(r)
        counter[labels[label_key]] += 1
    if not counter:
        return {
            "label_key": label_key,
            "predicted": "none",
            "count": 0,
            "accuracy": 0.0,
        }
    most_common = counter.most_common(1)[0]
    y_true = [extract_labels(r)[label_key] for r in rows]
    y_pred = [most_common[0]] * len(rows)
    return {
        "label_key": label_key,
        "predicted": most_common[0],
        "count": most_common[1],
        "accuracy": _accuracy(y_true, y_pred),
        "y_true": y_true,
        "y_pred": y_pred,
    }


def legal_heuristic_baseline(
    rows: List[Dict[str, Any]], label_key: str,
) -> Dict[str, Any]:
    """Simple rule: predict attack if legal, else
    switch, else protect, else pass.
    """
    y_true = []
    y_pred = []
    for r in rows:
        labels = extract_labels(r)
        y_true.append(labels[label_key])
        # Determine slot
        slot_idx = 0 if label_key == "slot0" else (
            1 if label_key == "slot1" else None
        )
        if slot_idx is not None:
            legal_key = f"legal_action_keys_slot{slot_idx}"
        else:
            # Primary label: look at the most extreme
            # tag.
            legal_key = None
        if label_key == "primary":
            # For primary, we predict "double_attack" if
            # both slots have attack legal.
            sig0 = _legal_signature(
                r.get("legal_action_keys_slot0", [])
            )
            sig1 = _legal_signature(
                r.get("legal_action_keys_slot1", [])
            )
            if sig0["has_legal_attack"] and sig1["has_legal_attack"]:
                y_pred.append("double_attack")
            elif sig0["has_legal_protect"] or sig1["has_legal_protect"]:
                y_pred.append("attack_plus_protect")
            elif sig0["has_legal_switch"] or sig1["has_legal_switch"]:
                y_pred.append("move_plus_switch")
            else:
                y_pred.append("single_move_plus_pass")
        else:
            sig = _legal_signature(
                r.get(legal_key, [])
            )
            if sig["has_legal_attack"]:
                y_pred.append("attack")
            elif sig["has_legal_protect"]:
                y_pred.append("protect")
            elif sig["has_legal_switch"]:
                y_pred.append("switch")
            elif sig["has_legal_pass"]:
                y_pred.append("pass")
            else:
                y_pred.append("unknown")
    return {
        "label_key": label_key,
        "y_true": y_true,
        "y_pred": y_pred,
        "accuracy": _accuracy(y_true, y_pred),
    }


def score_baseline(
    rows: List[Dict[str, Any]], label_key: str,
) -> Dict[str, Any]:
    """Score-based baseline: predict the per-slot
    action with the highest v2l1_raw_score. For
    primary label, combine the two max scores into
    a coarse primary category.
    """
    y_true = []
    y_pred = []
    available = True
    for r in rows:
        labels = extract_labels(r)
        y_true.append(labels[label_key])
        if label_key == "primary":
            s0 = r.get("v2l1_raw_scores_slot0") or {}
            s1 = r.get("v2l1_raw_scores_slot1") or {}
            if not s0 or not s1:
                available = False
                y_pred.append("unknown")
                continue
            # Find the max-score key per slot
            k0_max = max(s0, key=s0.get)
            k1_max = max(s1, key=s1.get)
            m0 = _norm_move_id(k0_max.split("|")[1]) if "|" in k0_max else ""
            m1 = _norm_move_id(k1_max.split("|")[1]) if "|" in k1_max else ""
            kind0 = "move" if k0_max.startswith("move") else (
                "switch" if k0_max.startswith("switch") else "unknown"
            )
            kind1 = "move" if k1_max.startswith("move") else (
                "switch" if k1_max.startswith("switch") else "unknown"
            )
            label0 = _classify_action_kind_label(m0, kind0)
            label1 = _classify_action_kind_label(m1, kind1)
            # Construct a coarse primary
            if label0 == "attack" and label1 == "attack":
                y_pred.append("double_attack")
            elif label0 == "protect" or label1 == "protect":
                y_pred.append("attack_plus_protect")
            elif label0 == "setup" or label1 == "setup":
                y_pred.append("attack_plus_setup")
            elif label0 == "weather_setter" or label1 == "weather_setter":
                y_pred.append("attack_plus_weather_setter")
            elif label0 == "switch" or label1 == "switch":
                y_pred.append("move_plus_switch")
            else:
                y_pred.append("double_attack")
        else:
            slot_idx = 0 if label_key == "slot0" else 1
            scores = r.get(f"v2l1_raw_scores_slot{slot_idx}") or {}
            if not scores:
                available = False
                y_pred.append("unknown")
                continue
            k_max = max(scores, key=scores.get)
            m = _norm_move_id(k_max.split("|")[1]) if "|" in k_max else ""
            kind = "move" if k_max.startswith("move") else (
                "switch" if k_max.startswith("switch") else "unknown"
            )
            y_pred.append(_classify_action_kind_label(m, kind))
    return {
        "label_key": label_key,
        "y_true": y_true,
        "y_pred": y_pred,
        "accuracy": _accuracy(y_true, y_pred),
        "available": available,
    }


# ---- Simple no-dependency BC model ----
class _NaiveBayesClassifier:
    """A simple multinomial Naive Bayes classifier for
    binary features. No dependencies. In-memory only.

    Each feature is a boolean. The classifier computes
    P(label | features) proportional to
    P(label) * prod_i P(feature_i | label).
    """

    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha
        self.class_priors: Dict[str, float] = {}
        self.feature_probs: Dict[Tuple[str, str], float] = {}

    def fit(
        self,
        X: List[Dict[str, bool]],
        y: List[str],
        feature_keys: List[str],
    ) -> None:
        n = len(y)
        if n == 0:
            return
        # Class priors
        class_counts: Counter = Counter(y)
        for c, cnt in class_counts.items():
            self.class_priors[c] = cnt / n
        # Feature probabilities with Laplace smoothing
        for c in class_counts:
            for fk in feature_keys:
                pos = sum(
                    1
                    for xi, yi in zip(X, y)
                    if yi == c and xi.get(fk, False)
                )
                self.feature_probs[(c, fk)] = (
                    (pos + self.alpha) /
                    (class_counts[c] + 2 * self.alpha)
                )

    def predict(self, X: List[Dict[str, bool]]) -> List[str]:
        preds = []
        for x in X:
            scores = {}
            for c, p in self.class_priors.items():
                log_p = 0.0  # log(1) = 0
                import math
                for (cc, fk), fp in self.feature_probs.items():
                    if cc != c:
                        continue
                    if x.get(fk, False):
                        log_p += math.log(max(fp, 1e-10))
                    else:
                        log_p += math.log(max(1 - fp, 1e-10))
                scores[c] = log_p + math.log(max(p, 1e-10))
            preds.append(max(scores, key=scores.get) if scores else "unknown")
        return preds


def _to_bool_features(
    feature_dicts: List[Dict[str, Any]],
    feature_keys: List[str],
) -> List[Dict[str, bool]]:
    """Convert feature dicts to a list of bool feature
    dicts using the provided key list.
    """
    out = []
    for fd in feature_dicts:
        out.append({k: bool(fd.get(k, False)) for k in feature_keys})
    return out


def bc_model_dryrun(
    rows_train: List[Dict[str, Any]],
    rows_test: List[Dict[str, Any]],
    label_key: str,
    include_exploration_features: bool = False,
    seed: int = 123,
) -> Dict[str, Any]:
    """Run a simple BC dry-run using a no-dependency
    Naive Bayes classifier.
    """
    empty_result = {
        "label_key": label_key,
        "accuracy": 0.0,
        "available": True,
        "n_train": len(rows_train) if rows_train else 0,
        "n_test": len(rows_test) if rows_test else 0,
        "per_class_metrics": {},
        "confusion_matrix": {},
        "y_true": [],
        "y_pred": [],
        "n_features": 0,
        "leakage_fields_train": [],
        "leakage_fields_test": [],
        "include_exploration_features": include_exploration_features,
        "model_type": "naive_bayes_no_dependency",
        "model_artifact_saved": False,
        "scikit_learn_used": False,
    }
    if not rows_train or not rows_test:
        return empty_result
    rng = random.Random(seed)
    # Extract features
    X_train_raw, leak_train = [], set()
    y_train = []
    for r in rows_train:
        feats, leak = extract_features(
            r, include_exploration_features
        )
        leak_train |= leak
        X_train_raw.append(feats)
        y_train.append(extract_labels(r)[label_key])
    X_test_raw, leak_test = [], set()
    y_test = []
    for r in rows_test:
        feats, leak = extract_features(
            r, include_exploration_features
        )
        leak_test |= leak
        X_test_raw.append(feats)
        y_test.append(extract_labels(r)[label_key])
    # Determine feature keys (union of all keys)
    feature_keys_set: Set[str] = set()
    for fd in X_train_raw + X_test_raw:
        feature_keys_set.update(fd.keys())
    feature_keys = sorted(feature_keys_set)
    # Convert to bool
    X_train = _to_bool_features(X_train_raw, feature_keys)
    X_test = _to_bool_features(X_test_raw, feature_keys)
    # Train
    clf = _NaiveBayesClassifier(alpha=1.0)
    clf.fit(X_train, y_train, feature_keys)
    # Predict
    y_pred = clf.predict(X_test)
    # Metrics
    all_labels = sorted(set(y_train) | set(y_test))
    metrics = _per_class_metrics(y_test, y_pred, all_labels)
    cm = _confusion_matrix(y_test, y_pred, all_labels)
    return {
        "label_key": label_key,
        "accuracy": _accuracy(y_test, y_pred),
        "y_true": y_test,
        "y_pred": y_pred,
        "per_class_metrics": metrics,
        "confusion_matrix": cm,
        "n_features": len(feature_keys),
        "n_train": len(rows_train),
        "n_test": len(rows_test),
        "leakage_fields_train": sorted(leak_train),
        "leakage_fields_test": sorted(leak_test),
        "include_exploration_features": include_exploration_features,
        "model_type": "naive_bayes_no_dependency",
        "model_artifact_saved": False,
        "scikit_learn_used": False,
    }


# ---- Analysis pipeline ----
def analyze_dataset(
    dataset_path: str,
    label,
    include_exploration_features: bool = False,
    seed: int = 123,
    train_pct: float = 0.8,
) -> Dict[str, Any]:
    """Run the full BC dry-run analysis on a dataset."""
    with open(dataset_path) as f:
        rows = [json.loads(ln) for ln in f if ln.strip()]
    n_rows = len(rows)
    # Sanity checks
    schema_counter = Counter(r.get("schema_version", "?") for r in rows)
    local_only = sum(1 for r in rows if r.get("local_only_provenance") is True)
    used_species = sum(
        1 for r in rows if r.get("used_species_ability_inference") is True
    )
    # Train/test split
    rng = random.Random(seed)
    indices = list(range(n_rows))
    rng.shuffle(indices)
    split = int(n_rows * train_pct)
    train_idx = set(indices[:split])
    rows_train = [rows[i] for i in indices[:split]]
    rows_test = [rows[i] for i in indices[split:]]
    # Per-label BC results
    bc_results: Dict[str, Any] = {}
    for label_key in ("primary", "slot0", "slot1"):
        # With exploration features (less honest)
        r_with = bc_model_dryrun(
            rows_train, rows_test, label_key,
            include_exploration_features=True,
            seed=seed,
        )
        # Without exploration features (more honest)
        r_without = bc_model_dryrun(
            rows_train, rows_test, label_key,
            include_exploration_features=False,
            seed=seed,
        )
        # Baselines
        mj = majority_baseline(rows_test, label_key)
        lh = legal_heuristic_baseline(rows_test, label_key)
        sc = score_baseline(rows_test, label_key)
        bc_results[label_key] = {
            "bc_with_exploration": r_with,
            "bc_without_exploration": r_without,
            "majority": {
                "predicted": mj["predicted"],
                "accuracy": mj["accuracy"],
            },
            "legal_heuristic": {
                "accuracy": lh["accuracy"],
            },
            "score_based": {
                "available": sc.get("available", True),
                "accuracy": sc.get("accuracy", 0.0),
            },
        }
    # Leakage check: scan ALL rows for any LEAKAGE_FIELDS
    # presence. This is a runtime check; the feature
    # extractor also has a defense-in-depth check.
    leakage_rows: Dict[str, int] = defaultdict(int)
    for r in rows:
        for f in LEAKAGE_FIELDS:
            if f in r:
                leakage_rows[f] += 1
    # Prediction distribution collapse check
    pred_dist: Counter = Counter()
    for label_key, res in bc_results.items():
        for p in res["bc_without_exploration"]["y_pred"]:
            pred_dist[label_key + "_" + p] += 1
    pred_dist_dict = dict(pred_dist)
    return {
        "dataset_path": dataset_path,
        "n_rows": n_rows,
        "schema_distribution": dict(schema_counter),
        "local_only_provenance_count": local_only,
        "used_species_ability_inference_count": used_species,
        "n_train": len(rows_train),
        "n_test": len(rows_test),
        "bc_results": bc_results,
        "leakage_check": {
            "leakage_field_row_counts": dict(leakage_rows),
            "leakage_detected": sum(leakage_rows.values()) > 0,
        },
        "prediction_distribution": pred_dist_dict,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--datasets-c",
        default="logs/rl_data_3c_dataset.jsonl",
    )
    parser.add_argument(
        "--datasets-e",
        default="logs/rl_data_3e_merged_dataset.jsonl",
    )
    parser.add_argument(
        "--dataset-4",
        default="",
        help=(
            "Optional 4th dataset (RL-DATA-4 live "
            "trajectory). Empty = skip."
        ),
    )
    parser.add_argument(
        "--output-json",
        default="logs/rl_data_3f_bc_dryrun_analysis.json",
    )
    parser.add_argument(
        "--seed", type=int, default=123,
    )
    parser.add_argument(
        "--train-pct", type=float, default=0.8,
    )
    args = parser.parse_args()
    if not os.path.exists(args.datasets_c):
        print(f"ERROR: 3c dataset not found: {args.datasets_c}")
        sys.exit(1)
    if not os.path.exists(args.datasets_e):
        print(f"ERROR: 3e merged dataset not found: {args.datasets_e}")
        sys.exit(1)
    print("=== RL-DATA-3f BC dry-run analysis ===")
    print(f"3c dataset: {args.datasets_c}")
    print(f"3e merged dataset: {args.datasets_e}")
    if args.dataset_4:
        if not os.path.exists(args.dataset_4):
            print(f"ERROR: 4 dataset not found: {args.dataset_4}")
            sys.exit(1)
        print(f"4 dataset: {args.dataset_4}")
    print()
    results = {
        "rl_data_3c": analyze_dataset(
            args.datasets_c, "3c",
            include_exploration_features=False,
            seed=args.seed,
            train_pct=args.train_pct,
        ),
        "rl_data_3e_merged": analyze_dataset(
            args.datasets_e, "3e_merged",
            include_exploration_features=False,
            seed=args.seed,
            train_pct=args.train_pct,
        ),
        "metadata": {
            "script": __file__,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "seed": args.seed,
            "train_pct": args.train_pct,
            "model_artifact_saved": False,
            "scikit_learn_used": False,
            "model_type": "naive_bayes_no_dependency",
        },
    }
    if args.dataset_4:
        results["rl_data_4_live_trajectory"] = analyze_dataset(
            args.dataset_4, "4_live_trajectory",
            include_exploration_features=False,
            seed=args.seed,
            train_pct=args.train_pct,
        )
    with open(args.output_json, "w") as f:
        json.dump(results, f, indent=2, default=str)
    # Human-readable summary
    summary_labels = [("3c", "rl_data_3c"), ("3e_merged", "rl_data_3e_merged")]
    if args.dataset_4:
        summary_labels.append(("4_live_trajectory", "rl_data_4_live_trajectory"))
    for label, key in summary_labels:
        r = results[key]
        print(f"--- {label} ---")
        print(f"  n_rows: {r['n_rows']}")
        print(f"  leakage_detected: {r['leakage_check']['leakage_detected']}")
        if r['leakage_check']['leakage_detected']:
            print(f"    leakage fields: {r['leakage_check']['leakage_field_row_counts']}")
        for label_key, bc in r["bc_results"].items():
            print(f"  {label_key}:")
            print(f"    majority: {100*bc['majority']['accuracy']:.1f}% ({bc['majority']['predicted']!r})")
            print(f"    legal_heuristic: {100*bc['legal_heuristic']['accuracy']:.1f}%")
            sc = bc['score_based']
            if sc['available']:
                print(f"    score_based: {100*sc['accuracy']:.1f}%")
            else:
                print(f"    score_based: unavailable")
            bcwo = bc["bc_without_exploration"]
            print(f"    bc_without_exploration: {100*bcwo['accuracy']:.1f}%")
            # Per-class recall for minority classes
            for cls_name in ("setup", "weather_setter", "support_other",
                              "protect", "switch"):
                m = bcwo["per_class_metrics"].get(cls_name)
                if m and m["support"] > 0:
                    print(f"      {cls_name} recall: {100*m['recall']:.1f}% "
                          f"(support={m['support']}, tp={m['tp']}, "
                          f"fp={m['fp']}, fn={m['fn']})")
        print()
    print(f"Output: {args.output_json}")


if __name__ == "__main__":
    main()
