"""Phase RL-DATA-3d — Action distribution and baseline audit.

Analyzes the existing 5,923-row ``turn_rl_v1.1`` dataset from
RL-DATA-3c to answer the key question: is the dataset
actually usable for RL/BC dry-run, or is it too collapsed
toward attack actions?

This is a data analysis phase. It does NOT train any
model. It does NOT change scoring or behavior. It does
NOT flip opt-in flags.

The previous RL-DATA-3c report had suspicious overlapping
metrics:

* ``double_attack = 100%``
* ``double_protect = 1.0%``
* ``double_switch = 4.2%``

These were NOT mutually exclusive. This script computes
BOTH a mutually exclusive primary distribution AND
overlapping boolean tags, so the dataset's action
distribution is reported clearly.

Output:

* ``logs/rl_data_3d_action_distribution_baseline_audit.json``
  (machine-readable)
* The script prints a human-readable summary to stdout.

Usage:

```bash
./venv/bin/python scripts/analyze/analyze_rl_data_3d_action_distribution.py \
    --dataset logs/rl_data_3c_dataset.jsonl \
    --output logs/rl_data_3d_action_distribution_baseline_audit.json
```
"""

import argparse
import json
import os
import sys
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, PROJECT_ROOT)

# Move keyword sets (Phase RL-DATA-3c inventory).
# All lowercase, no spaces / dashes / underscores /
# apostrophes. Keep in sync with the SUPPORT-AUDIT-1
# inventory in ``doubles_engine.support_targets``.
SETUP_KEYWORDS = frozenset({
    "quiverdance", "swordsdance", "nastyplot", "dragondance",
    "calmmind", "bulkup", "irondefense", "amnesia", "agility",
    "shellsmash", "bellydrum", "growth", "workup", "curse",
    "cosmicpower", "coil", "honeclaws", "autotomize",
    "rockpolish", "shiftgear", "tailglow", "geomancy",
    "victorydance", "clangeroussoul", "tidyup", "substitute",
})
WEATHER_SETTER_KEYWORDS = frozenset({
    "raindance", "sunnyday", "sandstorm", "hail", "snowscape",
    "electricterrain", "grassyterrain", "mistyterrain",
    "psychicterrain",
})
PROTECT_KEYWORDS = frozenset({
    "protect", "detect", "spikyshield", "kingsshield",
    "banefulbunker", "silktrap", "burningbulwark", "obstruct",
    "maxguard",
})
# A move is "support" if it's in the SUPPORT-AUDIT-1
# inventory as a non-damaging, non-set-up move (Protect,
# weather/terrain setter, etc.). The simplest definition
# is: NOT a damaging move AND NOT a setup move AND
# NOT a weather setter. The per_candidate_support_classification
# field already records ``is_support_move`` and
# ``support_group`` per candidate. We use that for
# "has_support" detection.
SUPPORT_KEYWORDS = frozenset({
    # Protect / Detect / etc.
    "protect", "detect", "spikyshield", "kingsshield",
    "banefulbunker", "silktrap", "burningbulwark", "obstruct",
    "maxguard",
    # Wide / Quick / Crafty shield
    "wideguard", "quickguard", "craftyshield", "matblock",
    # Redirection
    "followme", "ragepowder",
    # Screens
    "lightscreen", "reflect", "auroraveil",
    # Healing
    "healpulse", "floralhealing", "lifedew", "wish",
    "aromatherapy", "healbell", "pollenpuff",
    # Ally buff
    "helpinghand", "coaching", "howl", "decorate",
    # Disruption
    "taunt", "encore", "disable", "torment",
    "thunderwave", "willowisp", "toxic", "spore",
    "sleeppowder", "charm", "scaryface", "screech",
    "faketears", "metalsound", "gastroacid",
    # Speed
    "tailwind", "trickroom", "icywind", "electroweb",
    # Hazards
    "stealthrock", "spikes", "toxicspikes",
    # Misc field
    "mist", "safeguard", "haze", "skillswap",
})


def _norm_move_id(mid: Any) -> str:
    """Normalize a move id to lowercase, no-sep form."""
    if mid is None:
        return ""
    s = str(mid).lower()
    return (
        s.replace(" ", "").replace("-", "").replace("_", "")
        .replace("'", "")
    )


def _is_protect_move(mid_norm: str) -> bool:
    return any(p in mid_norm for p in PROTECT_KEYWORDS)


def _is_setup_move(mid_norm: str) -> bool:
    return mid_norm in SETUP_KEYWORDS


def _is_weather_setter(mid_norm: str) -> bool:
    return mid_norm in WEATHER_SETTER_KEYWORDS


def _is_support_move(mid_norm: str) -> bool:
    return mid_norm in SUPPORT_KEYWORDS


def _action_kind(k: Any) -> str:
    """Return ``"move"``, ``"switch"``, ``"pass"``, or ``"unknown"``
    for a V4a / v1.0 action key.
    """
    if not isinstance(k, (list, tuple)) or len(k) < 2:
        return "unknown"
    raw = str(k[0]).lower().strip()
    if raw == "move":
        return "move"
    if raw == "switch":
        return "switch"
    if raw == "pass":
        return "pass"
    # Defensive: pass via "unknown" kind
    if len(k) >= 2:
        s = str(k[1]).lower().strip()
        if s in ("pass", "/choose pass", "choose pass"):
            return "pass"
    return "unknown"


def _move_id_norm(k: Any) -> str:
    if not isinstance(k, (list, tuple)) or len(k) < 2:
        return ""
    return _norm_move_id(k[1])


def _classify_selected_joint_primary(
    sel0_kind: str, sel1_kind: str,
    sel0_move: str, sel1_move: str,
) -> str:
    """Return the mutually exclusive primary category
    for a selected joint.
    """
    # No second slot (shouldn't happen in v1.1 data)
    if sel0_kind == "unknown" and sel1_kind == "unknown":
        return "unknown"
    # Pure switch / switch
    if sel0_kind == "switch" and sel1_kind == "switch":
        return "double_switch"
    # Switch + pass / unknown
    if sel0_kind == "switch" and sel1_kind in ("pass", "unknown"):
        return "attack_plus_switch"  # actually switch + pass
    if sel1_kind == "switch" and sel0_kind in ("pass", "unknown"):
        return "attack_plus_switch"
    # Pure pass / pass
    if sel0_kind in ("pass", "unknown") and sel1_kind in (
        "pass", "unknown"
    ):
        return "unknown"
    # move + pass
    if sel0_kind == "move" and sel1_kind in ("pass", "unknown"):
        return "single_move_plus_pass"
    if sel1_kind == "move" and sel0_kind in ("pass", "unknown"):
        return "single_move_plus_pass"
    # move + switch
    if sel0_kind == "move" and sel1_kind == "switch":
        return "move_plus_switch"
    if sel1_kind == "move" and sel0_kind == "switch":
        return "move_plus_switch"
    # move + move
    if sel0_kind == "move" and sel1_kind == "move":
        p0 = _is_protect_move(sel0_move)
        p1 = _is_protect_move(sel1_move)
        if p0 and p1:
            return "double_protect"
        if p0 or p1:
            return "attack_plus_protect"
        s0 = _is_setup_move(sel0_move)
        s1 = _is_setup_move(sel1_move)
        if s0 or s1:
            return "attack_plus_setup"
        w0 = _is_weather_setter(sel0_move)
        w1 = _is_weather_setter(sel1_move)
        if w0 or w1:
            return "attack_plus_weather_setter"
        # Check support moves
        sup0 = _is_support_move(sel0_move)
        sup1 = _is_support_move(sel1_move)
        if sup0 or sup1:
            return "attack_plus_support"
        return "double_attack"
    return "mixed_other"


def _classify_selected_joint_tags(
    sel0_kind: str, sel1_kind: str,
    sel0_move: str, sel1_move: str,
) -> Dict[str, bool]:
    """Return overlapping boolean tags for a selected joint."""
    tags = {
        "has_attack": False,
        "has_protect": False,
        "has_switch": False,
        "has_pass": False,
        "has_support": False,
        "has_setup": False,
        "has_weather_setter": False,
        "has_terrain_setter": False,
        "has_unknown": False,
    }
    for kind, move in (
        (sel0_kind, sel0_move),
        (sel1_kind, sel1_move),
    ):
        if kind == "move":
            tags["has_attack"] = True
            if _is_protect_move(move):
                tags["has_protect"] = True
            if _is_setup_move(move):
                tags["has_setup"] = True
            if _is_weather_setter(move):
                tags["has_weather_setter"] = True
            # Terrain setter
            if move in (
                "electricterrain", "grassyterrain",
                "mistyterrain", "psychicterrain",
            ):
                tags["has_terrain_setter"] = True
            if _is_support_move(move):
                tags["has_support"] = True
        elif kind == "switch":
            tags["has_switch"] = True
        elif kind in ("pass", "unknown"):
            # Treat "unknown" as "pass" for tagging
            if "pass" in move or "/choose pass" in move:
                tags["has_pass"] = True
            else:
                tags["has_unknown"] = True
    return tags


def _classify_legal_tags(
    legal_slot0: List, legal_slot1: List
) -> Dict[str, bool]:
    """Return overlapping boolean tags for the legal
    candidates in a row.
    """
    tags = {
        "has_attack": False,
        "has_protect": False,
        "has_switch": False,
        "has_support": False,
        "has_setup": False,
        "has_weather_setter": False,
        "has_terrain_setter": False,
    }
    for legal in (legal_slot0, legal_slot1):
        for k in legal or []:
            if not isinstance(k, (list, tuple)) or len(k) < 2:
                continue
            kind = _action_kind(k)
            move = _move_id_norm(k)
            if kind == "move":
                if not tags["has_attack"]:
                    tags["has_attack"] = True
                if _is_protect_move(move) and not tags["has_protect"]:
                    tags["has_protect"] = True
                if _is_setup_move(move) and not tags["has_setup"]:
                    tags["has_setup"] = True
                if _is_weather_setter(move):
                    if not tags["has_weather_setter"]:
                        tags["has_weather_setter"] = True
                    if move in (
                        "electricterrain", "grassyterrain",
                        "mistyterrain", "psychicterrain",
                    ) and not tags["has_terrain_setter"]:
                        tags["has_terrain_setter"] = True
                if _is_support_move(move) and not tags["has_support"]:
                    tags["has_support"] = True
            elif kind == "switch" and not tags["has_switch"]:
                tags["has_switch"] = True
    return tags


def analyze_dataset(dataset_path: str) -> Dict[str, Any]:
    """Run the full analysis on the dataset.

    Returns a dict with all metrics, ready to be
    serialized as JSON.
    """
    with open(dataset_path) as f:
        rows = [json.loads(ln) for ln in f if ln.strip()]

    n_rows = len(rows)
    schema_counter = Counter(r.get("schema_version", "?") for r in rows)
    local_only = sum(1 for r in rows if r.get("local_only_provenance") is True)
    used_species = sum(
        1 for r in rows if r.get("used_species_ability_inference") is True
    )
    hard_safety_clean = (
        local_only == n_rows
        and used_species == 0
    )

    # Score field coverage
    score_fields = {
        "raw_score": sum(1 for r in rows if r.get("raw_score") is not None),
        "final_score": sum(1 for r in rows if r.get("final_score") is not None),
        "selected_score": sum(1 for r in rows if r.get("selected_score") is not None),
        "v2l1_raw_scores_slot0": sum(
            1 for r in rows if r.get("v2l1_raw_scores_slot0")
        ),
        "v2l1_raw_scores_slot1": sum(
            1 for r in rows if r.get("v2l1_raw_scores_slot1")
        ),
    }

    # Selected joint classification
    primary_counter: Counter = Counter()
    tag_counter: Counter = Counter()
    legal_tag_counter: Counter = Counter()
    legal_setup_available = 0
    legal_weather_setter_available = 0
    legal_support_available = 0
    legal_protect_available = 0
    selected_setup = 0
    selected_weather_setter = 0
    selected_support = 0
    selected_protect = 0

    # For score-based baseline
    score_correct = 0
    score_total = 0
    per_slot_score_correct = 0
    per_slot_score_total = 0

    # For per-slot majority baseline
    slot0_actions: Counter = Counter()
    slot1_actions: Counter = Counter()
    slot0_move: Counter = Counter()
    slot1_move: Counter = Counter()
    slot0_kinds: Counter = Counter()
    slot1_kinds: Counter = Counter()

    # For action-kind baseline
    action_kind_correct = 0
    action_kind_total = 0

    for r in rows:
        sel = r.get("selected_joint_key", [])
        if not isinstance(sel, list) or len(sel) < 2:
            continue
        s0 = sel[0] if len(sel) > 0 else None
        s1 = sel[1] if len(sel) > 1 else None
        s0_kind = _action_kind(s0) if s0 else "unknown"
        s1_kind = _action_kind(s1) if s1 else "unknown"
        s0_move = _move_id_norm(s0)
        s1_move = _move_id_norm(s1)
        primary = _classify_selected_joint_primary(
            s0_kind, s1_kind, s0_move, s1_move
        )
        tags = _classify_selected_joint_tags(
            s0_kind, s1_kind, s0_move, s1_move
        )
        primary_counter[primary] += 1
        for tag, val in tags.items():
            if val:
                tag_counter[tag] += 1
        if tags["has_setup"]:
            selected_setup += 1
        if tags["has_weather_setter"]:
            selected_weather_setter += 1
        if tags["has_support"]:
            selected_support += 1
        if tags["has_protect"]:
            selected_protect += 1

        # Track per-slot actions
        if s0:
            slot0_actions[(s0_kind, s0_move)] += 1
            slot0_kinds[s0_kind] += 1
            if s0_kind == "move":
                slot0_move[s0_move] += 1
        if s1:
            slot1_actions[(s1_kind, s1_move)] += 1
            slot1_kinds[s1_kind] += 1
            if s1_kind == "move":
                slot1_move[s1_move] += 1

        # Legal tags
        legal0 = r.get("legal_action_keys_slot0", [])
        legal1 = r.get("legal_action_keys_slot1", [])
        legal_tags = _classify_legal_tags(legal0, legal1)
        for tag, val in legal_tags.items():
            if val:
                legal_tag_counter[tag] += 1
        if legal_tags["has_setup"]:
            legal_setup_available += 1
        if legal_tags["has_weather_setter"]:
            legal_weather_setter_available += 1
        if legal_tags["has_support"]:
            legal_support_available += 1
        if legal_tags["has_protect"]:
            legal_protect_available += 1

        # Score-based baseline: check if the
        # selected joint matches the max-score
        # candidate per slot.
        score0 = r.get("v2l1_raw_scores_slot0") or {}
        score1 = r.get("v2l1_raw_scores_slot1") or {}
        if score0 and isinstance(score0, dict) and s0:
            best_s0 = max(score0.values()) if score0 else None
            if best_s0 is not None:
                # Get the action key for the best
                s0_score = None
                for k, v in score0.items():
                    if v == best_s0:
                        # The key is pipe-joined
                        # ``"kind|move_id|target"``
                        parts = k.split("|")
                        if len(parts) >= 2 and parts[0] == "move":
                            s0_score = (
                                parts[0],
                                _norm_move_id(parts[1]),
                            )
                        else:
                            s0_score = (parts[0], "")
                        break
                if s0_score is not None and s0_score == (
                    s0_kind, s0_move
                ):
                    per_slot_score_correct += 1
                per_slot_score_total += 1
        if score1 and isinstance(score1, dict) and s1:
            best_s1 = max(score1.values()) if score1 else None
            if best_s1 is not None:
                s1_score = None
                for k, v in score1.items():
                    if v == best_s1:
                        parts = k.split("|")
                        if len(parts) >= 2 and parts[0] == "move":
                            s1_score = (
                                parts[0],
                                _norm_move_id(parts[1]),
                            )
                        else:
                            s1_score = (parts[0], "")
                        break
                if s1_score is not None and s1_score == (
                    s1_kind, s1_move
                ):
                    per_slot_score_correct += 1
                per_slot_score_total += 1

        # Action-kind baseline: predict based on
        # legal availability. The simplest heuristic:
        # if damaging move available, predict attack;
        # else if switch, predict switch; else pass.
        pred_s0_kind = "pass"
        pred_s1_kind = "pass"
        if legal_tags["has_attack"]:
            pred_s0_kind = "move"
        if legal0:
            # Use slot-specific availability
            for k in legal0:
                if isinstance(k, (list, tuple)) and len(k) >= 2:
                    kind = _action_kind(k)
                    if kind == "move":
                        pred_s0_kind = "move"
                        break
            if pred_s0_kind == "pass":
                for k in legal0:
                    if isinstance(k, (list, tuple)) and len(k) >= 2:
                        if _action_kind(k) == "switch":
                            pred_s0_kind = "switch"
                            break
        if legal_tags["has_attack"]:
            pred_s1_kind = "move"
        if legal1:
            for k in legal1:
                if isinstance(k, (list, tuple)) and len(k) >= 2:
                    kind = _action_kind(k)
                    if kind == "move":
                        pred_s1_kind = "move"
                        break
            if pred_s1_kind == "pass":
                for k in legal1:
                    if isinstance(k, (list, tuple)) and len(k) >= 2:
                        if _action_kind(k) == "switch":
                            pred_s1_kind = "switch"
                            break
        if s0_kind == pred_s0_kind:
            action_kind_correct += 1
        if s1_kind == pred_s1_kind:
            action_kind_correct += 1
        action_kind_total += 2

    # Compute baselines
    primary_dist = {
        k: v for k, v in sorted(
            primary_counter.items(), key=lambda x: -x[1]
        )
    }
    tag_dist = {
        k: v for k, v in sorted(
            tag_counter.items(), key=lambda x: -x[1]
        )
    }
    legal_tag_dist = {
        k: v for k, v in sorted(
            legal_tag_counter.items(), key=lambda x: -x[1]
        )
    }

    # Majority baselines
    majority_primary = (
        primary_counter.most_common(1)[0][0]
        if primary_counter else "none"
    )
    majority_primary_count = (
        primary_counter.most_common(1)[0][1]
        if primary_counter else 0
    )
    majority_primary_acc = (
        majority_primary_count / n_rows if n_rows else 0
    )

    # Per-slot majority
    slot0_maj = (
        slot0_actions.most_common(1)[0]
        if slot0_actions else None
    )
    slot1_maj = (
        slot1_actions.most_common(1)[0]
        if slot1_actions else None
    )
    slot0_maj_acc = (
        slot0_actions.most_common(1)[0][1] / n_rows
        if slot0_maj else 0
    )
    slot1_maj_acc = (
        slot1_actions.most_common(1)[0][1] / n_rows
        if slot1_maj else 0
    )

    # Per-slot kind majority
    slot0_maj_kind = (
        slot0_kinds.most_common(1)[0]
        if slot0_kinds else None
    )
    slot1_maj_kind = (
        slot1_kinds.most_common(1)[0]
        if slot1_kinds else None
    )

    # Action-kind baseline
    action_kind_acc = (
        action_kind_correct / action_kind_total
        if action_kind_total else 0
    )

    # Score baseline
    per_slot_score_acc = (
        per_slot_score_correct / per_slot_score_total
        if per_slot_score_total else 0
    )

    # Opportunity-to-selection ratios
    def _ratio(num: int, denom: int) -> float:
        if denom == 0:
            return 0.0
        return num / denom

    setup_ratio = _ratio(selected_setup, legal_setup_available)
    weather_ratio = _ratio(
        selected_weather_setter, legal_weather_setter_available
    )
    support_ratio = _ratio(selected_support, legal_support_available)
    protect_ratio = _ratio(selected_protect, legal_protect_available)

    # Policy collapse decision
    selected_attack_count = sum(
        v for k, v in primary_counter.items()
        if k in (
            "double_attack", "attack_plus_protect",
            "attack_plus_setup", "attack_plus_weather_setter",
            "attack_plus_support",
        )
    )
    selected_attack_rate = (
        selected_attack_count / n_rows if n_rows else 0
    )
    selected_setup_rate = (
        primary_counter.get("attack_plus_setup", 0) / n_rows
        if n_rows else 0
    )
    selected_weather_rate = (
        primary_counter.get("attack_plus_weather_setter", 0) / n_rows
        if n_rows else 0
    )
    selected_protect_rate = (
        (primary_counter.get("attack_plus_protect", 0) +
         primary_counter.get("double_protect", 0)) / n_rows
        if n_rows else 0
    )

    # Decision logic
    if (selected_setup_rate == 0 and selected_weather_rate == 0
            and selected_attack_rate > 0.50
            and legal_setup_available > 0
            and legal_weather_setter_available > 0):
        decision = "DATASET_WARN_POLICY_BIASED"
        decision_detail = (
            "Selected joints are dominated by attacks "
            f"({100*selected_attack_rate:.1f}%). Setup "
            f"({100*selected_setup_rate:.1f}%) and "
            f"weather setter ({100*selected_weather_rate:.1f}%) "
            "are NEVER selected, even though they are "
            f"legal in {legal_setup_available} and "
            f"{legal_weather_setter_available} rows "
            "respectively. The dataset is honest about "
            "this bias. The bot's policy never considers "
            "setup or weather/terrain as primary actions."
        )
    elif selected_attack_rate > 0.85:
        decision = "DATASET_WARN_POLICY_BIASED"
        decision_detail = (
            f"Attacks dominate ({100*selected_attack_rate:.1f}%) "
            "but some diversity exists."
        )
    else:
        decision = "DATASET_USABLE_FOR_RL_DRYRUN"
        decision_detail = (
            "Selected action distribution has meaningful "
            "diversity. Baselines are non-trivial."
        )

    return {
        "dataset_path": dataset_path,
        "n_rows": n_rows,
        "schema_distribution": dict(schema_counter),
        "hard_safety_clean": hard_safety_clean,
        "local_only_provenance_count": local_only,
        "used_species_ability_inference_count": used_species,
        "score_field_coverage": {
            k: {
                "key_present": v,
                "pct": v / n_rows if n_rows else 0,
            }
            for k, v in score_fields.items()
        },
        "selected_joint_primary_distribution": {
            k: {
                "count": v,
                "pct": v / n_rows if n_rows else 0,
            }
            for k, v in primary_dist.items()
        },
        "selected_joint_overlapping_tags": {
            k: {
                "count": v,
                "pct": v / n_rows if n_rows else 0,
            }
            for k, v in tag_dist.items()
        },
        "legal_overlapping_tags": {
            k: {
                "count": v,
                "pct": v / n_rows if n_rows else 0,
            }
            for k, v in legal_tag_dist.items()
        },
        "opportunity_to_selection_ratios": {
            "setup_selection_ratio": setup_ratio,
            "weather_setter_selection_ratio": weather_ratio,
            "support_selection_ratio": support_ratio,
            "protect_selection_ratio": protect_ratio,
            "setup_legal_available": legal_setup_available,
            "weather_setter_legal_available":
                legal_weather_setter_available,
            "support_legal_available": legal_support_available,
            "protect_legal_available": legal_protect_available,
            "setup_selected": selected_setup,
            "weather_setter_selected": selected_weather_setter,
            "support_selected": selected_support,
            "protect_selected": selected_protect,
        },
        "baselines": {
            "majority_selected_joint": {
                "predicted": majority_primary,
                "count": majority_primary_count,
                "accuracy": majority_primary_acc,
            },
            "per_slot_majority": {
                "slot0": {
                    "predicted": (
                        list(slot0_maj) if slot0_maj else None
                    ),
                    "count": (
                        slot0_maj[1] if slot0_maj else 0
                    ),
                    "accuracy": slot0_maj_acc,
                },
                "slot1": {
                    "predicted": (
                        list(slot1_maj) if slot1_maj else None
                    ),
                    "count": (
                        slot1_maj[1] if slot1_maj else 0
                    ),
                    "accuracy": slot1_maj_acc,
                },
                "slot0_majority_kind": (
                    list(slot0_maj_kind)
                    if slot0_maj_kind else None
                ),
                "slot1_majority_kind": (
                    list(slot1_maj_kind)
                    if slot1_maj_kind else None
                ),
            },
            "action_kind_baseline": {
                "accuracy": action_kind_acc,
                "correct": action_kind_correct,
                "total": action_kind_total,
                "description": (
                    "Predict attack if legal damaging "
                    "move available; else predict switch; "
                    "else predict pass."
                ),
            },
            "score_based_baseline": {
                "available": (
                    score_fields["v2l1_raw_scores_slot0"] == n_rows
                    and score_fields["v2l1_raw_scores_slot1"]
                    == n_rows
                ),
                "per_slot_max_score_accuracy": per_slot_score_acc,
                "per_slot_correct": per_slot_score_correct,
                "per_slot_total": per_slot_score_total,
                "description": (
                    "For each slot, predict the candidate "
                    "with the highest v2l1_raw_score."
                ),
            },
        },
        "policy_collapse_decision": decision,
        "policy_collapse_decision_detail": decision_detail,
        "selected_attack_rate": selected_attack_rate,
        "selected_setup_rate": selected_setup_rate,
        "selected_weather_setter_rate": selected_weather_rate,
        "selected_protect_rate": selected_protect_rate,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default="logs/rl_data_3c_dataset.jsonl",
        help="Path to v1.1 dataset JSONL",
    )
    parser.add_argument(
        "--output",
        default="logs/rl_data_3d_action_distribution_baseline_audit.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    if not os.path.exists(args.dataset):
        print(f"ERROR: dataset not found: {args.dataset}")
        sys.exit(1)

    result = analyze_dataset(args.dataset)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2, default=str)

    # Human-readable summary
    n = result["n_rows"]
    print(f"=== RL-DATA-3d Action Distribution & Baseline Audit ===")
    print(f"Dataset: {args.dataset}")
    print(f"Rows: {n}")
    print()
    print("--- Schema distribution ---")
    for k, v in result["schema_distribution"].items():
        print(f"  {k}: {v} ({100*v/n:.1f}%)")
    print()
    print("--- Selected joint primary distribution (MUTUALLY EXCLUSIVE) ---")
    for k, v in result["selected_joint_primary_distribution"].items():
        print(f"  {k}: {v['count']} ({100*v['pct']:.1f}%)")
    print()
    print("--- Selected joint overlapping tags ---")
    for k, v in result["selected_joint_overlapping_tags"].items():
        print(f"  {k}: {v['count']} ({100*v['pct']:.1f}%)")
    print()
    print("--- Legal overlapping tags ---")
    for k, v in result["legal_overlapping_tags"].items():
        print(f"  {k}: {v['count']} ({100*v['pct']:.1f}%)")
    print()
    print("--- Opportunity-to-selection ratios ---")
    r = result["opportunity_to_selection_ratios"]
    for k in (
        "setup", "weather_setter", "support", "protect"
    ):
        print(
            f"  {k}: legal={r[f'{k}_legal_available']}, "
            f"selected={r[f'{k}_selected']}, "
            f"ratio={r[f'{k}_selection_ratio']:.2%}"
        )
    print()
    print("--- Baselines ---")
    b = result["baselines"]
    print(
        f"  majority_selected_joint: {b['majority_selected_joint']['predicted']!r} "
        f"({100*b['majority_selected_joint']['accuracy']:.1f}%)"
    )
    psm = b["per_slot_majority"]
    print(
        f"  per_slot_majority slot0: {psm['slot0']['predicted']!r} "
        f"({100*psm['slot0']['accuracy']:.1f}%)"
    )
    print(
        f"  per_slot_majority slot1: {psm['slot1']['predicted']!r} "
        f"({100*psm['slot1']['accuracy']:.1f}%)"
    )
    print(
        f"  action_kind_baseline: {100*b['action_kind_baseline']['accuracy']:.1f}% "
        f"({b['action_kind_baseline']['correct']}/"
        f"{b['action_kind_baseline']['total']})"
    )
    sbb = b["score_based_baseline"]
    if sbb["available"]:
        print(
            f"  score_based_baseline: per-slot max-score "
            f"accuracy={100*sbb['per_slot_max_score_accuracy']:.1f}% "
            f"({sbb['per_slot_correct']}/{sbb['per_slot_total']})"
        )
    else:
        print("  score_based_baseline: unavailable")
    print()
    print("--- Policy collapse decision ---")
    print(f"  {result['policy_collapse_decision']}")
    print(f"  {result['policy_collapse_decision_detail']}")
    print()
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
