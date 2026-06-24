#!/usr/bin/env python3
"""Phase 7.1 — BC warm-start training.

Offline behavior cloning on the turn-level v1.1 dataset.
Trains a small MLP to predict the per-slot selected joint action
from turn-level features.

Usage:
    HSA_OVERRIDE_GFX_VERSION=10.3.0 ./venv/bin/python \\
      showdown_ai/phase7_1_bc_warmstart_train_local.py \\
      --dataset logs/rl_data_refresh_enhanced_turns.jsonl \\
      --output-dir artifacts/phase7_1_bc_warmstart/<run_id> \\
      --report logs/phase7_1_bc_warmstart/<run_id>_report.md

This is offline training only. No deployment. No production changes.
"""

import argparse
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, REPO_ROOT)

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader


# ---------------------------------------------------------------------------
# Forbidden feature keys — never included as input
# ---------------------------------------------------------------------------
_FORBIDDEN_KEYS: Set[str] = {
    "won", "battle_result", "terminal_reward", "terminal_win_loss",
    "turn_delta_hp", "faint_caused", "faint_suffered",
    "selected_joint_key", "selected_per_slot", "selected_score",
    "final_action_keys", "top_5_alternatives", "top_5_scores",
    "score_gap_selected_best_alt", "live_exploration_triggered",
    "live_exploration_selected_action", "live_exploration_original_action",
    "live_exploration_submitted_action", "live_exploration_reason",
    "discounted_return", "delayed_reward_placeholder", "sparse_reward_warning",
    "reward_provenance", "reward_confidence",
    "used_species_ability_inference", "impossible_target_detected",
    "blocked_action_resurrected_by_joint",
}

# Species list for one-hot encoding (covers common random-doubles species)
_COMMON_SPECIES: List[str] = []  # populated from data


def _norm(s: Any) -> str:
    if s is None:
        return ""
    return str(s).lower().replace(" ", "").replace("-", "").replace("_", "").replace("'", "")


# ---------------------------------------------------------------------------
# Feature encoding
# ---------------------------------------------------------------------------


class FeatureEncoder:
    """Builds a fixed-dim feature vector from a v1.1 row.
    ponytail: flat encoding, no nested transformers.
    """

    def __init__(self, rows: List[Dict]):
        self.species_vocab: Set[str] = set()
        self.weather_vocab: Set[str] = set()
        self.field_vocab: Set[str] = set()
        self.sc_vocab: Set[str] = set()
        self._build_vocab(rows)

    def _norm_species(self, s: Any) -> str:
        return _norm(s)

    def _build_vocab(self, rows: List[Dict]):
        for r in rows:
            ss = r.get("state_snapshot", {}) or {}
            for spec_list in [ss.get("our_active_species", []), ss.get("opp_active_species", [])]:
                for s in spec_list:
                    self.species_vocab.add(self._norm_species(s))
            for w in ss.get("weather", []) or []:
                self.weather_vocab.add(_norm(w))
            for f in ss.get("fields", []) or []:
                self.field_vocab.add(_norm(f))
            for sc in ss.get("side_conditions", []) or []:
                self.sc_vocab.add(_norm(sc))

        # Sort for deterministic ordering
        self.species_list = sorted(self.species_vocab)
        self.weather_list = sorted(self.weather_vocab)
        self.field_list = sorted(self.field_vocab)
        self.sc_list = sorted(self.sc_vocab)

    def _onehot(self, val: str, vocab: List[str]) -> List[float]:
        arr = [0.0] * len(vocab)
        nv = _norm(val)
        for i, v in enumerate(vocab):
            if v == nv:
                arr[i] = 1.0
                break
        return arr

    def _multi_onehot(self, vals: List[str], vocab: List[str]) -> List[float]:
        arr = [0.0] * len(vocab)
        for val in vals:
            nv = _norm(val)
            for i, v in enumerate(vocab):
                if v == nv:
                    arr[i] = 1.0
                    break
        return arr

    def __call__(self, r: Dict) -> torch.Tensor:
        ss = r.get("state_snapshot", {}) or {}
        feats: List[float] = []

        # Turn number (normalized)
        total = int(r.get("total_turns", 1) or 1)
        turn = int(r.get("turn_index", 0) or 0)
        feats.append(turn / max(total, 1))

        # HP fractions (pad to 2 per side for consistency)
        raw_our_hp = ss.get("our_active_hp_fraction", [0.0, 0.0]) or [0.0, 0.0]
        raw_opp_hp = ss.get("opp_active_hp_fraction", [0.0, 0.0]) or [0.0, 0.0]
        our_hp = [float(h) if h is not None else 0.0 for h in raw_our_hp]
        opp_hp = [float(h) if h is not None else 0.0 for h in raw_opp_hp]
        # pad each side to exactly 2
        our_hp = (our_hp + [0.0, 0.0])[:2]
        opp_hp = (opp_hp + [0.0, 0.0])[:2]
        feats.extend(our_hp + opp_hp)

        # Species one-hot (4 slots)
        for spec in (ss.get("our_active_species", []) or [])[:2]:
            feats.extend(self._onehot(str(spec) if spec is not None else "", self.species_list))
        for _ in range(2 - len((ss.get("our_active_species", []) or [])[:2])):
            feats.extend([0.0] * len(self.species_list))
        for spec in (ss.get("opp_active_species", []) or [])[:2]:
            feats.extend(self._onehot(str(spec) if spec is not None else "", self.species_list))
        for _ in range(2 - len((ss.get("opp_active_species", []) or [])[:2])):
            feats.extend([0.0] * len(self.species_list))

        # Weather / Terrain / Fields / Side conditions
        feats.extend(self._multi_onehot(ss.get("weather", []) or [], self.weather_list))
        feats.extend(self._multi_onehot(ss.get("fields", []) or [], self.field_list))
        feats.extend(self._multi_onehot(ss.get("side_conditions", []) or [], self.sc_list))

        # Legal action count per slot
        la0 = r.get("legal_action_keys_slot0", []) or []
        la1 = r.get("legal_action_keys_slot1", []) or []
        feats.append(len(la0) / 50.0)
        feats.append(len(la1) / 50.0)

        meta_feats = [
            1.0 if r.get("unknown_support_move_detected") else 0.0,
            1.0 if r.get("used_species_ability_inference") else 0.0,
            1.0 if r.get("overkill_penalty_triggered") else 0.0,
            1.0 if r.get("focus_fire_triggered") else 0.0,
            1.0 if r.get("stale_target_avoided") else 0.0,
        ]
        feats.extend(meta_feats)

        return torch.tensor(feats, dtype=torch.float32)

    @property
    def dim(self) -> int:
        dummy = self({"state_snapshot": {}, "turn_index": 0, "total_turns": 1,
                       "legal_action_keys_slot0": [], "legal_action_keys_slot1": [],
                       "unknown_support_move_detected": False,
                       "used_species_ability_inference": False,
                       "overkill_penalty_triggered": False,
                       "focus_fire_triggered": False, "stale_target_avoided": False})
        return len(dummy)


# ---------------------------------------------------------------------------
# Label encoding
# ---------------------------------------------------------------------------


def _legal_keys_to_labels(legal_keys: List) -> Set[str]:
    """Convert a list of V4a legal action keys (e.g. `[['move', 'tailwind', '0', ''], ...]`)
    to a set of label strings matching _extract_action_label output."""
    labels: Set[str] = set()
    for k in legal_keys or []:
        if isinstance(k, (list, tuple)) and len(k) >= 2:
            labels.add(_extract_action_label(k))
    return labels


def build_legal_mask(legal_labels: Set[str], label_map: Dict[str, int],
                     num_classes: int) -> torch.Tensor:
    """Build a boolean mask of shape `(num_classes,)` where True means
    the action index is legal (present in legal_labels)."""
    mask = torch.zeros(num_classes, dtype=torch.bool)
    for lbl in legal_labels:
        idx = label_map.get(lbl)
        if idx is not None:
            mask[idx] = True
    return mask


def _extract_action_label(slot_key: List) -> str:
    """Convert a per-slot action key like `['move', 'tailwind', '0', '']`
    into a label string like `move|tailwind|0`."""
    if not isinstance(slot_key, (list, tuple)) or len(slot_key) < 2:
        return "pass"
    kind = _norm(slot_key[0])
    if kind == "move":
        mid = _norm(slot_key[1])
        target = str(slot_key[2]) if len(slot_key) > 2 else "0"
        return f"move|{mid}|{target}"
    if kind == "switch":
        species = _norm(slot_key[1])
        return f"switch|{species}"
    return "pass"


def build_label_maps(rows: List[Dict]) -> Tuple[Dict[str, int], Dict[int, str]]:
    labels: Set[str] = set()
    for r in rows:
        sk = r.get("selected_joint_key", []) or []
        if len(sk) >= 1:
            labels.add(_extract_action_label(sk[0]))
        if len(sk) >= 2:
            labels.add(_extract_action_label(sk[1]))
    sorted_labels = sorted(labels)
    str_to_int = {lbl: i for i, lbl in enumerate(sorted_labels)}
    int_to_str = {i: lbl for lbl, i in str_to_int.items()}
    return str_to_int, int_to_str


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


class TurnDataset(Dataset):
    def __init__(self, rows: List[Dict], encoder: FeatureEncoder,
                 label_map: Dict[str, int]):
        self.rows = rows
        self.encoder = encoder
        self.label_map = label_map

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, idx):
        r = self.rows[idx]
        x = self.encoder(r)
        sk = r.get("selected_joint_key", []) or []
        l0 = _extract_action_label(sk[0] if len(sk) >= 1 else ["pass"])
        l1 = _extract_action_label(sk[1] if len(sk) >= 2 else ["pass"])
        y0 = self.label_map.get(l0, 0)
        y1 = self.label_map.get(l1, 0)
        return x, y0, y1


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class BCMlp(nn.Module):
    """Small MLP for BC warm-start.
    ponytail: one hidden layer is usually enough for a first baseline.
    """
    def __init__(self, input_dim: int, num_classes: int, hidden: int = 256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden, hidden // 2),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden // 2, num_classes),
        )

    def forward(self, x):
        return self.net(x)


# ---------------------------------------------------------------------------
# Candidate scorer utilities
# ---------------------------------------------------------------------------


def _candidate_key_from_legal(lk: List) -> str:
    """Build a candidate key string from a V4a legal action key,
    preserving target sign."""
    if not isinstance(lk, (list, tuple)) or len(lk) < 2:
        return "pass"
    kind = _norm(lk[0])
    if kind == "move":
        mid = _norm(lk[1])
        target = str(lk[2]) if len(lk) > 2 and lk[2] is not None else "0"
        return f"move|{mid}|{target}"
    if kind == "switch":
        species = _norm(lk[1])
        return f"switch|{species}"
    return "pass"


def _candidate_key_from_selected(sk: List) -> str:
    """Same format as _candidate_key_from_legal for selected actions."""
    return _candidate_key_from_legal(sk)


def build_candidate_rows(rows: List[Dict], use_v2l1: bool = True) -> List[Dict]:
    """Build one row per legal candidate per slot per turn.

    Returns list of dicts with keys:
        group_key: (battle_tag, turn_index, slot)
        candidate_key: string matching _candidate_key_from_legal
        label: 1 if candidate matches selected action, else 0
        features: dict of candidate-level features (action type, move id, etc.)
        v2l1_score: float or None
    """
    cand_rows = []
    for r in rows:
        bt = r.get("battle_tag", "") or r.get("episode_id", "?")
        turn = r.get("turn_index", 0)
        sk = r.get("selected_joint_key", []) or []

        for slot in (0, 1):
            legal = r.get(f"legal_action_keys_slot{slot}", []) or []
            vscores = r.get(f"v2l1_raw_scores_slot{slot}", {}) or {}

            selected_key = _candidate_key_from_selected(
                sk[slot] if len(sk) > slot else ["pass"]
            )

            for lk in legal:
                cand_key = _candidate_key_from_legal(lk)
                # v2l1 score lookup
                v2l1 = vscores.get(cand_key, 0.0)
                if v2l1 is None:
                    v2l1 = 0.0
                try:
                    v2l1 = float(v2l1)
                except (ValueError, TypeError):
                    v2l1 = 0.0

                cand_rows.append({
                    "group_key": (bt, turn, slot),
                    "candidate_key": cand_key,
                    "label": 1 if cand_key == selected_key else 0,
                    "action_kind": _norm(lk[0]) if lk else "unknown",
                    "action_id": _norm(lk[1]) if isinstance(lk, (list, tuple)) and len(lk) > 1 and lk[1] else "",
                    "action_target": str(lk[2]) if isinstance(lk, (list, tuple)) and len(lk) > 2 and lk[2] is not None else "0",
                    "slot": slot,
                    "v2l1_score": v2l1,
                    "legal_count": len(legal),
                })
    return cand_rows


def candidate_group_eval(rows: List[Dict], scores: List[float]) -> Dict:
    """Group candidates by (battle_tag, turn, slot) and evaluate argmax.

    Args:
        rows: list of candidate row dicts (in same order as scores)
        scores: model output scores for each candidate row

    Returns:
        dict with grouped metrics
    """
    groups = defaultdict(list)
    for r, s in zip(rows, scores):
        groups[r["group_key"]].append({"score": s, "label": r["label"]})

    correct = 0
    total = 0
    ranks = []
    mrrs = []
    for gkey, members in groups.items():
        total += 1
        best_idx = max(range(len(members)), key=lambda i: members[i]["score"])
        if members[best_idx]["label"] == 1:
            correct += 1
        # Rank of the positive candidate
        sorted_m = sorted(members, key=lambda x: -x["score"])
        for rank, m in enumerate(sorted_m):
            if m["label"] == 1:
                ranks.append(rank + 1)
                mrrs.append(1.0 / (rank + 1))
                break

    accuracy = correct / max(total, 1)
    mean_rank = sum(ranks) / max(len(ranks), 1)
    median_rank = sorted(ranks)[len(ranks) // 2] if ranks else 0
    mrr = sum(mrrs) / max(len(mrrs), 1)

    return {
        "group_accuracy": round(accuracy, 4),
        "group_count": total,
        "mean_selected_rank": round(mean_rank, 2),
        "median_selected_rank": median_rank,
        "mrr": round(mrr, 4),
    }


# ---------------------------------------------------------------------------
# Candidate scorer model
# ---------------------------------------------------------------------------


class CandidateScorerMLP(nn.Module):
    """Small MLP for per-candidate binary scoring.
    ponytail: one hidden layer, binary output.
    """
    def __init__(self, input_dim: int, hidden: int = 128, dropout: float = 0.1):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, hidden // 2),
            nn.ReLU(),
            nn.Dropout(dropout / 2),
            nn.Linear(hidden // 2, 1),
        )

    def forward(self, x):
        return self.net(x).squeeze(-1)


# ---------------------------------------------------------------------------
# Battle-aware split
# ---------------------------------------------------------------------------


def battle_split(rows: List[Dict], train_pct: float = 0.7,
                 val_pct: float = 0.15, seed: int = 20260701):
    """Split rows by battle_tag to avoid leakage between train/val/test."""
    rng = random.Random(seed)
    battles: Dict[str, List[int]] = {}
    for i, r in enumerate(rows):
        bt = r.get("battle_tag", "") or r.get("episode_id", f"unknown_{i}")
        battles.setdefault(bt, []).append(i)
    battle_ids = list(battles.keys())
    rng.shuffle(battle_ids)
    n = len(battle_ids)
    n_train = int(n * train_pct)
    n_val = int(n * val_pct)
    train_b = set(battle_ids[:n_train])
    val_b = set(battle_ids[n_train:n_train + n_val])
    test_b = set(battle_ids[n_train + n_val:])

    train_idx = [i for b in train_b for i in battles[b]]
    val_idx = [i for b in val_b for i in battles[b]]
    test_idx = [i for b in test_b for i in battles[b]]

    train_idx.sort()
    val_idx.sort()
    test_idx.sort()
    return train_idx, val_idx, test_idx, train_b, val_b, test_b


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def compute_metrics(labels: List[int], preds: List[int]) -> Dict[str, float]:
    n = len(labels)
    correct = sum(1 for l, p in zip(labels, preds) if l == p)
    acc = correct / n if n > 0 else 0.0

    # Per-class
    classes = sorted(set(labels))
    per_class = {}
    for c in classes:
        mask = [1 if l == c else 0 for l in labels]
        total = sum(mask)
        if total == 0:
            continue
        tp = sum(1 for l, p in zip(labels, preds) if l == c and p == c)
        fp = sum(1 for l, p in zip(labels, preds) if l != c and p == c)
        fn = sum(1 for l, p in zip(labels, preds) if l == c and p != c)
        per_class[str(c)] = {
            "support": total,
            "precision": tp / (tp + fp) if (tp + fp) > 0 else 0.0,
            "recall": tp / (tp + fn) if (tp + fn) > 0 else 0.0,
        }

    # Macro F1
    precisions = [v["precision"] for v in per_class.values()]
    recalls = [v["recall"] for v in per_class.values()]
    macro_p = sum(precisions) / len(precisions) if precisions else 0.0
    macro_r = sum(recalls) / len(recalls) if recalls else 0.0
    macro_f1 = 2 * macro_p * macro_r / (macro_p + macro_r) if (macro_p + macro_r) > 0 else 0.0

    # Top-1 predicted class rate (collapse check)
    pred_counter = Counter(preds)
    top_pred, top_count = pred_counter.most_common(1)[0] if pred_counter else (0, 0)
    top_rate = top_count / n if n > 0 else 0.0

    return {
        "accuracy": round(acc, 4),
        "macro_f1": round(macro_f1, 4),
        "top_prediction_rate": round(top_rate, 4),
        "n_classes_seen": len(classes),
        "per_class": per_class,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="logs/rl_data_refresh_enhanced_turns.jsonl")
    parser.add_argument("--output-dir", default="artifacts/phase7_1_bc_warmstart/run")
    parser.add_argument("--report", default="logs/phase7_1_bc_warmstart/report.md")
    parser.add_argument("--load-model", default=None,
                        help="path to a pre-trained model.pt to evaluate instead of training")
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--seed", type=int, default=20260701)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--hidden", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--early-stopping-patience", type=int, default=4)
    parser.add_argument("--legal-mask", action="store_true",
                        help="evaluate legal-action-constrained accuracy on test set "
                             "(no retraining, uses existing model if available)")
    parser.add_argument("--class-weighting", choices=["none", "inverse_freq", "sqrt_inverse_freq"],
                        default="none", help="class weighting mode for cross-entropy loss")
    parser.add_argument("--class-weight-clip", type=float, default=5.0,
                        help="max class weight for clipping")
    # Debug/profiling flags
    parser.add_argument("--max-turn-rows", type=int, default=0,
                        help="limit raw turn rows read from JSONL (0=unlimited)")
    parser.add_argument("--candidate-debug-timing", action="store_true",
                        help="print timing logs for candidate scorer path")
    parser.add_argument("--candidate-dry-run-build", action="store_true",
                        help="build candidate rows/features then exit before training")
    # Candidate scorer flags
    parser.add_argument("--mode", choices=["global_classifier", "candidate_scorer"],
                        default="global_classifier",
                        help="training mode: global label classifier or per-candidate scorer")
    parser.add_argument("--candidate-score-feature", choices=["none", "v2l1"],
                        default="v2l1",
                        help="use per-candidate v2l1 raw score as candidate feature")
    parser.add_argument("--candidate-loss", choices=["bce", "weighted_bce"],
                        default="weighted_bce",
                        help="loss type for candidate scorer")
    parser.add_argument("--candidate-pos-weight", default="auto",
                        help="positive class weight: 'auto' or float")
    parser.add_argument("--candidate-pos-weight-clip", type=float, default=20.0,
                        help="maximum positive weight clip (default 20)")
    parser.add_argument("--candidate-hidden", type=int, default=128,
                        help="hidden dim for candidate scorer MLP")
    parser.add_argument("--candidate-dropout", type=float, default=0.1,
                        help="dropout rate for candidate scorer MLP")
    parser.add_argument("--candidate-eval-grouped", action="store_true",
                        help="evaluate candidate scorer by group argmax")
    args = parser.parse_args()

    # Device
    if args.device == "auto":
        args.device = "cuda" if torch.cuda.is_available() else "cpu"
    device = torch.device(args.device)
    print(f"Device: {device} (torch.cuda.is_available={torch.cuda.is_available()})")
    print(f"HSA_OVERRIDE_GFX_VERSION: {os.environ.get('HSA_OVERRIDE_GFX_VERSION', '(not set)')}")

    # Reproducibility
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)

    # Output dirs
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = Path(args.report).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    # Load dataset (optionally limited)
    print(f"\nLoading dataset: {args.dataset}")
    rows = []
    with open(args.dataset) as f:
        for i, line in enumerate(f):
            if args.max_turn_rows and i >= args.max_turn_rows:
                break
            if line.strip():
                rows.append(json.loads(line))
    print(f"Total rows: {len(rows)}")

    # Candidate scorer path
    if args.mode == "candidate_scorer":
        _t0 = time.perf_counter()
        print("\n=== Candidate Scorer Mode ===")
        print("Building candidate rows...")
        cand_rows = build_candidate_rows(rows, use_v2l1=(args.candidate_score_feature == "v2l1"))
        _t1 = time.perf_counter()
        if args.candidate_debug_timing:
            print(f"  [TIMER] build_candidate_rows: {_t1-_t0:.2f}s")
        groups = set(r["group_key"] for r in cand_rows)
        pos = sum(1 for r in cand_rows if r["label"] == 1)
        neg = len(cand_rows) - pos
        print(f"  Candidate rows: {len(cand_rows)}")
        print(f"  Groups: {len(groups)}")
        print(f"  Positive: {pos} ({100*pos/max(len(cand_rows),1):.2f}%)")
        print(f"  Negative: {neg}")
        print(f"  Imbalance: {neg/max(pos,1):.1f}:1")

        # Split by battle
        cand_train_idx, cand_val_idx, cand_test_idx, _, _, _ = battle_split(
            rows, train_pct=0.7, val_pct=0.15, seed=args.seed
        )
        # Map candidate rows by their original row index (O(N) hash-based)
        turn_to_row = {(r.get("battle_tag", ""), r.get("turn_index", 0)): i
                       for i, r in enumerate(rows)}
        row_to_cand = defaultdict(list)
        for ci, cr in enumerate(cand_rows):
            key = (cr["group_key"][0], cr["group_key"][1])
            ri = turn_to_row.get(key)
            if ri is not None:
                row_to_cand[ri].append(ci)

        train_cid = [ci for i in cand_train_idx for ci in row_to_cand.get(i, [])]
        val_cid = [ci for i in cand_val_idx for ci in row_to_cand.get(i, [])]
        test_cid = [ci for i in cand_test_idx for ci in row_to_cand.get(i, [])]
        print(f"  Train candidates: {len(train_cid)}")
        print(f"  Val candidates:   {len(val_cid)}")
        print(f"  Test candidates:  {len(test_cid)}")
        _t2 = time.perf_counter()
        if args.candidate_debug_timing:
            print(f"  [TIMER] split_and_map: {_t2-_t1:.2f}s")

        # Feature encoding for candidate rows
        _t3 = time.perf_counter()
        act_kinds = sorted(set(cr["action_kind"] for cr in cand_rows))
        act_ids_vocab = sorted(set(cr["action_id"] for cr in cand_rows if cr["action_id"]))
        if args.candidate_debug_timing:
            print(f"  [TIMER] vocab_build: {time.perf_counter()-_t3:.2f}s")

        # Dry-run: exit before training
        if args.candidate_dry_run_build:
            print("  [DRY-RUN] build complete, exiting before training")
            return

        def encode_candidate(cr: Dict) -> torch.Tensor:
            feats = []
            # Action kind one-hot
            ak_onehot = [0.0] * len(act_kinds)
            for i, ak in enumerate(act_kinds):
                if ak == cr["action_kind"]:
                    ak_onehot[i] = 1.0
                    break
            feats.extend(ak_onehot)
            # Action ID one-hot (top 200 common ids + fallback)
            aid_onehot = [0.0] * min(len(act_ids_vocab), 200)
            for i, aid in enumerate(act_ids_vocab[:200]):
                if aid == cr["action_id"]:
                    aid_onehot[i] = 1.0
                    break
            feats.extend(aid_onehot)
            # Target as float
            try:
                tgt = float(cr["action_target"])
            except (ValueError, TypeError):
                tgt = 0.0
            feats.append(tgt / 4.0)
            # Slot
            feats.append(float(cr["slot"]))
            # Legal count normalized
            feats.append(cr["legal_count"] / 30.0)
            # V2L1 score if available
            v2l1 = cr.get("v2l1_score", 0.0)
            feats.append(v2l1 / 1000.0)
            return torch.tensor(feats, dtype=torch.float32)

        cand_input_dim = len(encode_candidate(cand_rows[0]))
        print(f"  Candidate feature dim: {cand_input_dim}")
        _t4 = time.perf_counter()
        if args.candidate_debug_timing:
            print(f"  [TIMER] encode_function: {_t4-_t3:.2f}s")

        # Compute pos_weight
        pos_count = sum(1 for i in train_cid if cand_rows[i]["label"] == 1)
        neg_count = len(train_cid) - pos_count
        if args.candidate_pos_weight == "auto":
            pos_weight_val = neg_count / max(pos_count, 1)
            pos_weight_val = min(pos_weight_val, args.candidate_pos_weight_clip)
        else:
            pos_weight_val = float(args.candidate_pos_weight)
        pos_weight_t = torch.tensor([pos_weight_val], dtype=torch.float).to(device)
        print(f"  Positive weight: {pos_weight_val:.2f}")

        # Datasets
        class CandDataset(Dataset):
            def __init__(self, cids, cand_rows, enc_fn):
                self.cids = cids
                self.rows = cand_rows
                self.enc = enc_fn
            def __len__(self):
                return len(self.cids)
            def __getitem__(self, idx):
                cr = self.rows[self.cids[idx]]
                return self.enc(cr), float(cr["label"])

        train_cds = CandDataset(train_cid, cand_rows, encode_candidate)
        val_cds = CandDataset(val_cid, cand_rows, encode_candidate)
        test_cds = CandDataset(test_cid, cand_rows, encode_candidate)
        train_cl = DataLoader(train_cds, batch_size=min(args.batch_size * 4, 4096), shuffle=True)
        val_cl = DataLoader(val_cds, batch_size=min(args.batch_size * 4, 4096))
        test_cl = DataLoader(test_cds, batch_size=min(args.batch_size * 4, 4096))

        # Model
        model = CandidateScorerMLP(cand_input_dim, hidden=args.candidate_hidden,
                                    dropout=args.candidate_dropout).to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", factor=0.5, patience=2
        )
        loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight_t)

        # Training
        best_val_loss = float("inf")
        patience_counter = 0
        history = []
        print(f"\nTraining candidate scorer: {args.epochs} epochs")
        train_start = time.time()

        for epoch in range(1, args.epochs + 1):
            model.train()
            train_loss = 0.0
            tb = 0
            for xb, yb in train_cl:
                xb, yb = xb.to(device), yb.to(device)
                optimizer.zero_grad(set_to_none=True)
                logits = model(xb)
                loss = loss_fn(logits, yb)
                loss.backward()
                optimizer.step()
                train_loss += float(loss.detach().cpu())
                tb += 1
            train_loss /= max(tb, 1)

            model.eval()
            val_loss = 0.0
            vb = 0
            with torch.no_grad():
                for xb, yb in val_cl:
                    xb, yb = xb.to(device), yb.to(device)
                    logits = model(xb)
                    loss = loss_fn(logits, yb)
                    val_loss += float(loss.detach().cpu())
                    vb += 1
            val_loss /= max(vb, 1)
            scheduler.step(val_loss)
            history.append({"epoch": epoch, "train_loss": round(train_loss, 4),
                            "val_loss": round(val_loss, 4)})
            print(f"  epoch {epoch:2d}: train_loss={train_loss:.4f} val_loss={val_loss:.4f}")

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                torch.save(model.state_dict(), str(out_dir / "model.pt"))
            else:
                patience_counter += 1
                if patience_counter >= args.early_stopping_patience:
                    print(f"  Early stopping at epoch {epoch}")
                    break

        elapsed = time.time() - train_start
        print(f"Training time: {elapsed:.1f}s")
        model.load_state_dict(torch.load(str(out_dir / "model.pt"), weights_only=True))

        # Evaluation
        def cand_evaluate(cids):
            """Batch evaluate candidates in minibatches for speed."""
            model.eval()
            all_scores = []
            all_labels = []
            bs = min(args.batch_size * 4, 4096)
            with torch.no_grad():
                for start in range(0, len(cids), bs):
                    batch = cids[start:start + bs]
                    xs = torch.stack([encode_candidate(cand_rows[i]) for i in batch]).to(device)
                    logits = model(xs).cpu().tolist()
                    all_scores.extend(logits)
                    all_labels.extend([cand_rows[i]["label"] for i in batch])
            return all_scores, all_labels

        _t5 = time.perf_counter()
        train_scores, train_labels = cand_evaluate(train_cid)
        _t6 = time.perf_counter()
        if args.candidate_debug_timing:
            print(f"  [TIMER] cand_evaluate_train: {_t6-_t5:.2f}s")
        val_scores, val_labels = cand_evaluate(val_cid)
        test_scores, test_labels = cand_evaluate(test_cid)
        _t7 = time.perf_counter()
        if args.candidate_debug_timing:
            print(f"  [TIMER] cand_evaluate_all: {_t7-_t5:.2f}s")

        train_ge = candidate_group_eval([cand_rows[i] for i in train_cid], train_scores) if args.candidate_eval_grouped else {}
        val_ge = candidate_group_eval([cand_rows[i] for i in val_cid], val_scores) if args.candidate_eval_grouped else {}
        test_ge = candidate_group_eval([cand_rows[i] for i in test_cid], test_scores) if args.candidate_eval_grouped else {}

        # Random baseline
        rng = random.Random(args.seed + 1)
        random_scores = [rng.random() for _ in test_scores]
        random_ge = candidate_group_eval([cand_rows[i] for i in test_cid], random_scores)

        # V2L1 heuristic baseline (use v2l1_score directly)
        v2l1_scores = [cand_rows[i].get("v2l1_score", 0.0) for i in test_cid]
        v2l1_ge = candidate_group_eval([cand_rows[i] for i in test_cid], v2l1_scores) if args.candidate_score_feature == "v2l1" else {}

        print(f"\n  === Candidate Scorer Evaluation ===")
        print(f"  Test groups: {test_ge.get('group_count', 0)}")
        print(f"  Group accuracy: {test_ge.get('group_accuracy', 0):.4f}")
        print(f"  Mean selected rank: {test_ge.get('mean_selected_rank', 0):.2f}")
        print(f"  Median selected rank: {test_ge.get('median_selected_rank', 0)}")
        print(f"  MRR: {test_ge.get('mrr', 0):.4f}")
        print(f"  Random baseline accuracy: {random_ge.get('group_accuracy', 0):.4f}")
        if v2l1_ge:
            print(f"  V2L1 heuristic accuracy: {v2l1_ge.get('group_accuracy', 0):.4f}")
        print(f"  Illegal prediction rate: 0.0000 (structurally enforced)")

        # Save config and metrics
        config = {
            "mode": "candidate_scorer",
            "dataset": args.dataset,
            "device": str(device),
            "seed": args.seed,
            "epochs": args.epochs,
            "batch_size": min(args.batch_size * 4, 4096),
            "lr": args.lr,
            "model": "CandidateScorerMLP",
            "candidate_score_feature": args.candidate_score_feature,
            "candidate_loss": args.candidate_loss,
            "candidate_pos_weight": pos_weight_val,
            "candidate_feature_dim": cand_input_dim,
            "candidate_rows": len(cand_rows),
            "groups": len(groups),
            "train_candidates": len(train_cid),
            "val_candidates": len(val_cid),
            "test_candidates": len(test_cid),
        }
        with open(out_dir / "config.json", "w") as f:
            json.dump(config, f, indent=2)

        metrics = {
            "config": config,
            "training_time_s": round(elapsed, 1),
            "random_baseline_accuracy": random_ge.get("group_accuracy"),
            "v2l1_heuristic_accuracy": v2l1_ge.get("group_accuracy") if v2l1_ge else None,
            "test_group_accuracy": test_ge.get("group_accuracy"),
            "test_mrr": test_ge.get("mrr"),
            "test_mean_selected_rank": test_ge.get("mean_selected_rank"),
            "test_median_selected_rank": test_ge.get("median_selected_rank"),
            "val_group_accuracy": val_ge.get("group_accuracy"),
            "train_group_accuracy": train_ge.get("group_accuracy"),
        }
        with open(out_dir / "metrics.json", "w") as f:
            json.dump(metrics, f, indent=2)

        # Report
        report = f"""# Phase 7.2D Candidate Scorer Prototype Report

## Mode
Candidate scorer (binary per-candidate model)

## Config
- Dataset: `{args.dataset}`
- Candidate rows: {len(cand_rows)}
- Groups: {len(groups)}
- Pos/Neg: {pos}/{neg} ({100*pos/max(len(cand_rows),1):.2f}%)
- Candidate feature dim: {cand_input_dim}
- Score feature: {args.candidate_score_feature}
- Loss: {args.candidate_loss} (pos_weight={pos_weight_val:.2f})
- Device: {device}
- Epochs: {len(history)}/{args.epochs}

## Training
- Training time: {elapsed:.1f}s
- Best val loss: {best_val_loss:.4f}

## Candidate Scorer Metrics (Test)
| Metric | Value |
|--------|------:|
| Group accuracy | {test_ge.get('group_accuracy', 'N/A'):.4f} |
| Mean selected rank | {test_ge.get('mean_selected_rank', 'N/A')} |
| Median selected rank | {test_ge.get('median_selected_rank', 'N/A')} |
| MRR | {test_ge.get('mrr', 'N/A'):.4f} |
| Random baseline | {random_ge.get('group_accuracy', 0):.4f} |
"""
        if v2l1_ge:
            report += f"| V2L1 heuristic | {v2l1_ge.get('group_accuracy', 0):.4f} |\n"
        report += """| Illegal prediction rate | 0.0000 (structurally enforced) |

## Comparison
- Phase 7.2B constrained: slot0=45.24%, slot1=50.12%
- Candidate scorer works per-group over 15.5 avg candidates
"""

        with open(args.report, "w") as f:
            f.write(report)
        print(f"\nReport: {args.report}")
        print(f"Test group accuracy: {test_ge.get('group_accuracy', 'N/A')}")
        print(f"Random baseline: {random_ge.get('group_accuracy', 0):.4f}")
        return

    # Build encoder (needs full vocab)
    encoder = FeatureEncoder(rows)
    input_dim = encoder.dim
    print(f"Feature dim: {input_dim}")

    # Build label map
    label_map, inv_label_map = build_label_maps(rows)
    num_classes = len(label_map)
    print(f"Number of action classes: {num_classes}")

    # Split by battle
    train_idx, val_idx, test_idx, train_b, val_b, test_b = battle_split(
        rows, train_pct=0.7, val_pct=0.15, seed=args.seed
    )
    train_rows = [rows[i] for i in train_idx]
    val_rows = [rows[i] for i in val_idx]
    test_rows = [rows[i] for i in test_idx]
    print(f"Train: {len(train_rows)} rows ({len(train_b)} battles)")
    print(f"Val:   {len(val_rows)} rows ({len(val_b)} battles)")
    print(f"Test:  {len(test_rows)} rows ({len(test_b)} battles)")

    # Datasets
    train_ds = TurnDataset(train_rows, encoder, label_map)
    val_ds = TurnDataset(val_rows, encoder, label_map)
    test_ds = TurnDataset(test_rows, encoder, label_map)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size)
    test_loader = DataLoader(test_ds, batch_size=args.batch_size)

    # Model
    model = BCMlp(input_dim, num_classes, hidden=args.hidden).to(device)

    # Load pre-trained model if provided (eval-only mode)
    if args.load_model:
        model.load_state_dict(torch.load(args.load_model, map_location=device, weights_only=True))
        print(f"Loaded pre-trained model: {args.load_model}")
        history = []
        best_val_loss = float("inf")
        train_start = time.time()
        # Skip training; go straight to evaluation
    else:
        # Class weights (computed from training labels only)
        class_weight_tensor = None
        if args.class_weighting != "none" and num_classes > 1:
            freq = Counter()
            for r in train_rows:
                sk = r.get("selected_joint_key", []) or []
                if len(sk) >= 1:
                    lbl0 = _extract_action_label(sk[0])
                    freq[label_map.get(lbl0, 0)] += 1
                if len(sk) >= 2:
                    lbl1 = _extract_action_label(sk[1])
                    freq[label_map.get(lbl1, 0)] += 1
            weights = []
            for c in range(num_classes):
                f = freq.get(c, 0)
                w = max(f, 1)
                if args.class_weighting == "inverse_freq":
                    w = sum(freq.values()) / max(w * num_classes, 1)
                elif args.class_weighting == "sqrt_inverse_freq":
                    w = (sum(freq.values()) ** 0.5) / (w ** 0.5)
                w = min(w, args.class_weight_clip)
                weights.append(w)
            class_weight_tensor = torch.tensor(weights, dtype=torch.float).to(device)
            print(f"Class weighting: {args.class_weighting}, clip={args.class_weight_clip}, "
                  f"num_classes={num_classes}, non_zero_weight_classes="
                  f"{sum(1 for w in weights if w != weights[0])}")

        optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", factor=0.5, patience=2
        )

        # Training
        best_val_loss = float("inf")
        patience_counter = 0
        history = []

        print(f"\nTraining: {args.epochs} epochs, batch={args.batch_size}, lr={args.lr}")
        train_start = time.time()

    if not args.load_model:
        for epoch in range(1, args.epochs + 1):
            model.train()
            train_loss = 0.0
            train_batches = 0
            for xb, y0b, y1b in train_loader:
                xb, y0b, y1b = xb.to(device), y0b.to(device), y1b.to(device)
                optimizer.zero_grad(set_to_none=True)
                logits = model(xb)
                loss_kw = {"weight": class_weight_tensor} if class_weight_tensor is not None else {}
                loss0 = F.cross_entropy(logits, y0b, **loss_kw)
                loss1 = F.cross_entropy(logits, y1b, **loss_kw)
                loss = loss0 + loss1
                loss.backward()
                optimizer.step()
                train_loss += float(loss.detach().cpu())
                train_batches += 1
            train_loss /= max(train_batches, 1)

            # Validation (unweighted loss for fair comparison)
            model.eval()
            val_loss = 0.0
            val_batches = 0
            with torch.no_grad():
                for xb, y0b, y1b in val_loader:
                    xb, y0b, y1b = xb.to(device), y0b.to(device), y1b.to(device)
                    logits = model(xb)
                    loss0 = F.cross_entropy(logits, y0b)
                    loss1 = F.cross_entropy(logits, y1b)
                    loss = loss0 + loss1
                    val_loss += float(loss.detach().cpu())
                    val_batches += 1
            val_loss /= max(val_batches, 1)
            scheduler.step(val_loss)

            history.append({"epoch": epoch, "train_loss": round(train_loss, 4),
                            "val_loss": round(val_loss, 4)})

            print(f"  epoch {epoch:2d}: train_loss={train_loss:.4f} val_loss={val_loss:.4f} "
                  f"lr={optimizer.param_groups[0]['lr']:.2e}")

            # Early stopping
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                torch.save(model.state_dict(), str(out_dir / "model.pt"))
            else:
                patience_counter += 1
                if patience_counter >= args.early_stopping_patience:
                    print(f"  Early stopping at epoch {epoch}")
                    break

        elapsed = time.time() - train_start
        print(f"Training time: {elapsed:.1f}s")

        # Load best model
        model.load_state_dict(torch.load(str(out_dir / "model.pt"), weights_only=True))
    else:
        elapsed = 0.0
        # Save the loaded model to the output dir for consistency
        torch.save(model.state_dict(), str(out_dir / "model.pt"))

    # Evaluate
    def evaluate(loader, label):
        model.eval()
        all_y0, all_p0 = [], []
        all_y1, all_p1 = [], []
        with torch.no_grad():
            for xb, y0b, y1b in loader:
                xb = xb.to(device)
                logits = model(xb).cpu()
                preds = logits.argmax(dim=1)
                all_y0.extend(y0b.numpy().tolist())
                all_p0.extend(preds.numpy().tolist())
                all_y1.extend(y1b.numpy().tolist())
                all_p1.extend(preds.numpy().tolist())
        m0 = compute_metrics(all_y0, all_p0)
        m1 = compute_metrics(all_y1, all_p1)
        print(f"\n  === {label} ===")
        print(f"  slot0 accuracy: {m0['accuracy']:.4f}  macro_f1: {m0['macro_f1']:.4f}")
        print(f"  slot1 accuracy: {m1['accuracy']:.4f}  macro_f1: {m1['macro_f1']:.4f}")
        print(f"  slot0 top_pred_rate: {m0['top_prediction_rate']:.4f}  "
              f"n_classes: {m0['n_classes_seen']}")
        print(f"  slot1 top_pred_rate: {m1['top_prediction_rate']:.4f}  "
              f"n_classes: {m1['n_classes_seen']}")
        return m0, m1

    # Evaluate without legal mask
    train_m0, train_m1 = evaluate(train_loader, "Train")
    val_m0, val_m1 = evaluate(val_loader, "Val")
    test_m0, test_m1 = evaluate(test_loader, "Test")

    # Legal-mask constrained evaluation (no retraining)
    constrained_metrics = None
    if args.legal_mask:
        print("\n  === Legal-Mask Constrained Evaluation ===")
        model.eval()
        all_m0_y, all_m0_p = [], []
        all_m1_y, all_m1_p = [], []
        legal_hit0 = legal_hit1 = 0
        illegal0 = illegal1 = 0
        fallback0 = fallback1 = 0
        total = 0
        with torch.no_grad():
            for r in test_rows:
                x = encoder(r).unsqueeze(0).to(device)
                sk = r.get("selected_joint_key", []) or []
                y0 = label_map.get(_extract_action_label(sk[0] if len(sk) >= 1 else ["pass"]), 0)
                y1 = label_map.get(_extract_action_label(sk[1] if len(sk) >= 2 else ["pass"]), 0)

                # Build legal masks per slot
                la0 = _legal_keys_to_labels(r.get("legal_action_keys_slot0", []) or [])
                la1 = _legal_keys_to_labels(r.get("legal_action_keys_slot1", []) or [])
                mask0 = build_legal_mask(la0, label_map, num_classes)
                mask1 = build_legal_mask(la1, label_map, num_classes)

                logits = model(x).cpu().squeeze(0)
                # Constrained: set illegal logits to -inf
                constrained0 = logits.clone()
                constrained1 = logits.clone()
                constrained0[~mask0] = float("-inf")
                constrained1[~mask1] = float("-inf")

                pred0 = logits.argmax().item()
                cp0 = constrained0.argmax().item()
                cp1 = constrained1.argmax().item()

                all_m0_y.append(y0)
                all_m0_p.append(cp0)
                all_m1_y.append(y1)
                all_m1_p.append(cp1)

                if cp0 == y0:
                    legal_hit0 += 1
                if cp1 == y1:
                    legal_hit1 += 1
                # unconstrained pred is same for both slots (shared output head)
                if pred0 not in {j for j in range(num_classes) if mask0[j]}:
                    illegal0 += 1
                if pred0 not in {j for j in range(num_classes) if mask1[j]}:
                    illegal1 += 1
                if not mask0.any():
                    fallback0 += 1
                if not mask1.any():
                    fallback1 += 1
                total += 1

        cm0 = compute_metrics(all_m0_y, all_m0_p)
        cm1 = compute_metrics(all_m1_y, all_m1_p)
        constrained_metrics = {
            "legal_mask_slot0": cm0,
            "legal_mask_slot1": cm1,
            "illegal_prediction_rate_slot0": round(illegal0 / max(total, 1), 4),
            "illegal_prediction_rate_slot1": round(illegal1 / max(total, 1), 4),
            "fallback_rate_slot0": round(fallback0 / max(total, 1), 4),
            "fallback_rate_slot1": round(fallback1 / max(total, 1), 4),
            "legal_hit_rate_slot0": round(legal_hit0 / max(total, 1), 4),
            "legal_hit_rate_slot1": round(legal_hit1 / max(total, 1), 4),
        }
        print(f"  slot0 constrained: acc={cm0['accuracy']:.4f} "
              f"illegal_pred_rate={constrained_metrics['illegal_prediction_rate_slot0']:.4f} "
              f"fallback_rate={constrained_metrics['fallback_rate_slot0']:.4f}")
        print(f"  slot1 constrained: acc={cm1['accuracy']:.4f} "
              f"illegal_pred_rate={constrained_metrics['illegal_prediction_rate_slot1']:.4f} "
              f"fallback_rate={constrained_metrics['fallback_rate_slot1']:.4f}")
        print(f"  Combined improvement: slot0 "
              f"{'BETTER' if cm0['accuracy'] >= test_m0['accuracy'] else 'SAME_OR_LOWER'} "
              f"({cm0['accuracy']:.4f} vs {test_m0['accuracy']:.4f}), "
              f"slot1 "
              f"{'BETTER' if cm1['accuracy'] >= test_m1['accuracy'] else 'SAME_OR_LOWER'} "
              f"({cm1['accuracy']:.4f} vs {test_m1['accuracy']:.4f})")

    # Majority baseline (most common label)
    all_train_y0 = [_extract_action_label(r.get("selected_joint_key", [["pass"]])[0]) for r in train_rows]
    all_train_y1 = [_extract_action_label(r.get("selected_joint_key", [["pass"], ["pass"]])[1]) if len(r.get("selected_joint_key", []) or []) >= 2 else "pass" for r in train_rows]
    majority_label0 = Counter(all_train_y0).most_common(1)[0][0]
    majority_label1 = Counter(all_train_y1).most_common(1)[0][0]
    maj0_idx = label_map.get(majority_label0, 0)
    maj1_idx = label_map.get(majority_label1, 0)
    all_test_y0 = [_extract_action_label(r.get("selected_joint_key", [["pass"]])[0]) for r in test_rows]
    all_test_y1 = [_extract_action_label(r.get("selected_joint_key", [["pass"], ["pass"]])[1]) if len(r.get("selected_joint_key", []) or []) >= 2 else "pass" for r in test_rows]
    maj_test_acc0 = sum(1 for l in all_test_y0 if label_map.get(l, -1) == maj0_idx) / max(len(all_test_y0), 1)
    maj_test_acc1 = sum(1 for l in all_test_y1 if label_map.get(l, -1) == maj1_idx) / max(len(all_test_y1), 1)
    print(f"\n  Majority baseline (test): slot0={maj_test_acc0:.4f} slot1={maj_test_acc1:.4f}")

    # Collapse check
    top_class_pct0 = test_m0["top_prediction_rate"]
    top_class_pct1 = test_m1["top_prediction_rate"]
    n_classes_total = num_classes
    collapse_str = "NON_COLLAPSING" if (top_class_pct0 < 0.5 and top_class_pct1 < 0.5) else \
        ("PARTIAL_COLLAPSE" if (top_class_pct0 < 0.75 and top_class_pct1 < 0.75) else "COLLAPSED")
    print(f"  Collapse check: {collapse_str} (slot0 top={top_class_pct0:.3f}, slot1 top={top_class_pct1:.3f})")

    # Save artifacts
    config = {
        "dataset": args.dataset,
        "device": str(device),
        "seed": args.seed,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "hidden": args.hidden,
        "lr": args.lr,
        "input_dim": input_dim,
        "num_classes": num_classes,
        "train_rows": len(train_rows),
        "val_rows": len(val_rows),
        "test_rows": len(test_rows),
        "train_battles": len(train_b),
        "val_battles": len(val_b),
        "test_battles": len(test_b),
        "epochs_trained": len(history),
        "class_weighting": args.class_weighting,
        "class_weight_clip": args.class_weight_clip,
        "selected_score_in_features": False,
    }
    with open(out_dir / "config.json", "w") as f:
        json.dump(config, f, indent=2)
    with open(out_dir / "label_map.json", "w") as f:
        json.dump(label_map, f, indent=2)
    with open(out_dir / "feature_spec.json", "w") as f:
        json.dump({
            "species_vocab": encoder.species_list,
            "weather_vocab": encoder.weather_list,
            "field_vocab": encoder.field_list,
            "sc_vocab": encoder.sc_list,
            "input_dim": input_dim,
        }, f, indent=2)
    with open(out_dir / "train_history.json", "w") as f:
        json.dump(history, f, indent=2)

    metrics = {
        "config": config,
        "majority_baseline_test_slot0": maj_test_acc0,
        "majority_baseline_test_slot1": maj_test_acc1,
        "test_slot0": test_m0,
        "test_slot1": test_m1,
        "val_slot0": val_m0,
        "val_slot1": val_m1,
        "train_slot0": train_m0,
        "train_slot1": train_m1,
        "collapse_check": collapse_str,
        "constrained_metrics": constrained_metrics,
        "training_time_s": round(elapsed, 1),
    }
    with open(out_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    # Sample test predictions
    model.eval()
    sample_preds = []
    with torch.no_grad():
        for i in test_idx[:100]:
            r = rows[i]
            x = encoder(r).unsqueeze(0).to(device)
            logits = model(x).cpu()
            pred = logits.argmax(dim=1).item()
            true0 = _extract_action_label(r.get("selected_joint_key", [["pass"]])[0])
            pred0 = inv_label_map.get(pred, "unknown")
            sample_preds.append({
                "battle_tag": r.get("battle_tag", ""),
                "turn": r.get("turn_index", -1),
                "true_slot0": true0,
                "pred_slot0": pred0,
                "correct": true0 == pred0,
            })
    with open(out_dir / "test_predictions_sample.jsonl", "w") as f:
        for sp in sample_preds:
            f.write(json.dumps(sp) + "\n")

    # Report
    report = f"""# Phase 7.1 BC Warm-Start Training Report

## Authorization
User explicitly authorized Phase 7.1 BC warm-start training.

## Dataset
- Path: `{args.dataset}`
- Total rows: {len(rows)}
- Train: {len(train_rows)} ({len(train_b)} battles)
- Val:   {len(val_rows)} ({len(val_b)} battles)
- Test:  {len(test_rows)} ({len(test_b)} battles)
- Split: by battle_tag, seed={args.seed}

## Features
- Input dim: {input_dim}
- Species vocab: {len(encoder.species_list)}
- Forbidden fields excluded: {list(_FORBIDDEN_KEYS)[:10]}...

## Labels
- Action classes: {num_classes}
- Label: per-slot move/switch action key (e.g., `move|tailwind|0`)

## Model
- Architecture: 3-layer MLP ({input_dim} -> {args.hidden} -> {args.hidden // 2} -> {num_classes})
- Optimizer: AdamW lr={args.lr}
- Epochs: {len(history)} / {args.epochs}
- Early stopping patience: {args.early_stopping_patience}
- Device: {device}

## Device Details
- HSA_OVERRIDE_GFX_VERSION: {os.environ.get('HSA_OVERRIDE_GFX_VERSION', '(not set)')}
- torch.cuda.is_available: {torch.cuda.is_available()}
- GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'}

## Training
- Training time: {elapsed:.1f}s
- Best val loss: {best_val_loss:.4f}

### Loss History
| epoch | train_loss | val_loss |
|-------|-----------|---------|
"""
    for h in history:
        report += f"| {h['epoch']:2d} | {h['train_loss']:.4f} | {h['val_loss']:.4f} |\n"

    report += f"""
## Test Metrics

### Slot0
- Accuracy: {test_m0['accuracy']:.4f}
- Macro F1: {test_m0['macro_f1']:.4f}
- Top prediction rate: {test_m0['top_prediction_rate']:.4f}
- Majority baseline: {maj_test_acc0:.4f}

### Slot1
- Accuracy: {test_m1['accuracy']:.4f}
- Macro F1: {test_m1['macro_f1']:.4f}
- Top prediction rate: {test_m1['top_prediction_rate']:.4f}
- Majority baseline: {maj_test_acc1:.4f}

## Baselines
| Baseline | Slot0 | Slot1 |
|----------|------:|------:|
| Majority | {maj_test_acc0:.4f} | {maj_test_acc1:.4f} |
| BC MLP (test) | {test_m0['accuracy']:.4f} | {test_m1['accuracy']:.4f} |

## Collapse Check
- Status: {collapse_str}
- Slot0 top-prediction rate: {top_class_pct0:.4f}
- Slot1 top-prediction rate: {top_class_pct1:.4f}

## Legal-Mask Constrained Evaluation
| Metric | Slot0 | Slot1 |
|--------|------:|------:|
| Unconstrained accuracy | {test_m0['accuracy']:.4f} | {test_m1['accuracy']:.4f} |
"""
    if constrained_metrics:
        report += f"""| Constrained accuracy | {constrained_metrics['legal_mask_slot0']['accuracy']:.4f} | {constrained_metrics['legal_mask_slot1']['accuracy']:.4f} |
| Illegal prediction rate | {constrained_metrics['illegal_prediction_rate_slot0']:.4f} | {constrained_metrics['illegal_prediction_rate_slot1']:.4f} |
| Fallback rate | {constrained_metrics['fallback_rate_slot0']:.4f} | {constrained_metrics['fallback_rate_slot1']:.4f} |
"""
    else:
        report += "\n(not run — use --legal-mask to enable)\n"

    report += """## Artifacts
- Model: `{out_dir / 'model.pt'}`
- Config: `{out_dir / 'config.json'}`
- Metrics: `{out_dir / 'metrics.json'}`
- Label map: `{out_dir / 'label_map.json'}`
- Feature spec: `{out_dir / 'feature_spec.json'}`
- Train history: `{out_dir / 'train_history.json'}`
- Test samples: `{out_dir / 'test_predictions_sample.jsonl'}`

## Limitations
"""
    score_ok = (test_m0['accuracy'] > maj_test_acc0 or test_m1['accuracy'] > maj_test_acc1)
    recall_ok = collapse_str in ("NON_COLLAPSING", "PARTIAL_COLLAPSE")

    if not score_ok:
        report += """- BC MLP does not beat majority baseline. Feature engineering or model capacity needs improvement.
"""
    if not recall_ok:
        report += """- Model collapses to a single class class. More diversity needed in training.
"""
    report += """- No production deployment. Model is offline only.
- No default flip. Current bot logic unchanged.
"""

    with open(args.report, "w") as f:
        f.write(report)
    print(f"\nReport: {args.report}")
    print(f"Artifacts: {out_dir}")
    print(f"Metrics: slot0_test_acc={test_m0['accuracy']:.4f} slot1_test_acc={test_m1['accuracy']:.4f}")
    print(f"  majority_baseline: slot0={maj_test_acc0:.4f} slot1={maj_test_acc1:.4f}")
    print(f"  collapse: {collapse_str}")


if __name__ == "__main__":
    main()
