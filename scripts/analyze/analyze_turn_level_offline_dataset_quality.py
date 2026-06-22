"""Phase RL-6 — Turn-level offline dataset quality analyzer.

Read-only analyzer for ``turn_rl_v1.0`` datasets.
No training, no model artifact, no behavior change.

Output:
    logs/phaseRL6_turn_level_dataset_quality.md
    logs/phaseRL6_turn_level_dataset_quality.json

Reports:
- Row/episode summary
- Reward summary (balance, by arm/turn/category)
- Action distribution (categories, entropy, top-N)
- Legal action space (counts, coverage)
- State coverage (HP/species/weather/turn)
- Score/margin summary
- Counterfactual/optional fields coverage
- Duplicate/bias checks
- RL readiness assessment
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

# Expected schema versions this analyzer accepts.
# Phase RL-DATA-2 (RL-5 2026): v1.0 emitted by the original builder.
# Phase RL-DATA-2 (2026): v1.1 emitted by the updated builder
# (adds support-move instrumentation, weather/terrain setter
# fields, safety assertions). v1.1 is a strict superset of
# v1.0 — every v1.0 row is a valid v1.1 row. The analyzer
# accepts both versions and does NOT reject v1.0 rows.
ACCEPTED_SCHEMAS = ("turn_rl_v1.0", "turn_rl_v1.1")
EXPECTED_SCHEMA = "turn_rl_v1.0"  # kept for backward compat

# Phase RL-DATA-2b: v1.1 instrumentation gates. Each gate
# checks for the presence of a v1.1 field in a row. Missing
# fields are warnings, not failures (existing analyzer style).
# "block" gates are hard failures: a v1.1 row that violates
# a block gate must be rejected.
V1_1_GATE_FIELDS = {
    # Gate 12 — support instrumentation. Note: support_group,
    # support_status_from_audit, and is_support_move are nested
    # inside per_candidate_support_classification (a dict
    # mapping move_id -> classification). They are NOT at the
    # top level. The top-level instrumentation fields are
    # unknown_support_move_detected, the classification dict,
    # and the distribution dict.
    "unknown_support_move_detected": "Gate 12",
    "per_candidate_support_classification": "Gate 12",
    "support_move_distribution": "Gate 12",
    # Gate 13 — safety / mechanics
    "used_species_ability_inference": "Gate 13",
    "impossible_target_detected": "Gate 13",
    "blocked_action_resurrected_by_joint": "Gate 13",
    # Gate 14 — Weather / Terrain
    "weather_current": "Gate 14",
    "terrain_current": "Gate 14",
    "setter_move_legal": "Gate 14",
    "setter_move_selected": "Gate 14",
    "type_boost_move_legal": "Gate 14",
    "type_boost_move_selected": "Gate 14",
    "wt2_relevance_flag": "Gate 14",
    "wt3_relevance_flag": "Gate 14",
    "wt4_relevance_flag": "Gate 14",
    # Gate 15 — reward placeholders
    "terminal_win_loss": "Gate 15",
    "turn_delta_hp": "Gate 15",
    "faint_caused": "Gate 15",
    "faint_suffered": "Gate 15",
    "sparse_reward_warning": "Gate 15",
    "reward_provenance": "Gate 15",
    "reward_confidence": "Gate 15",
    # Gate 16 — score trace placeholders
    # (these keys are added when source data is available;
    # v1.1 does not require their presence as a hard gate
    # because they are explicitly None when source is missing.
    # We check them as soft warnings only.)
    # Gate 18 — config / provenance
    "local_only_provenance": "Gate 18",
    "config_hash": "Gate 18",
    "config_snapshot": "Gate 18",
    "runtime_mode": "Gate 18",
}

# v1.1 hard-block fields. If a v1.1 row has these values,
# the row must be rejected (BLOCKED readiness).
V1_1_BLOCK_FIELDS = (
    "used_species_ability_inference",
    "impossible_target_detected",
    "blocked_action_resurrected_by_joint",
)

# HP bucket boundaries (inclusive upper bounds).
HP_BUCKETS = [0.25, 0.5, 0.75, 1.01]
HP_BUCKET_LABELS = ["<25%", "25-50%", "50-75%", "75-100%"]

# Turn bucket boundaries (exclusive upper bounds).
TURN_BUCKETS = [4, 7, 10, 100]
TURN_BUCKET_LABELS = ["1-3", "4-6", "7-9", "10+"]

# Action categories for selected actions.
ACTION_CATEGORIES = {
    "move_attack": "attack",
    "move_status_ally": "status_ally",
    "move_status_self": "status_self",
    "move_status_opp": "status_opp",
    "move_status_field": "status_field",
    "switch": "switch",
    "pass": "pass",
    "unknown": "unknown",
}


def _to_json_safe(value: Any) -> Any:
    """Recursively convert to JSON-safe primitives."""
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(v) for v in value]
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _bucket_hp(hp: float) -> str:
    """Bucket a single HP fraction into a label.

    Buckets: [0, 0.25), [0.25, 0.5), [0.5, 0.75), [0.75, 1.01]
    Labels:  <25%,          25-50%,       50-75%,       75-100%
    """
    if hp < HP_BUCKETS[0]:
        return HP_BUCKET_LABELS[0]
    for i, upper in enumerate(HP_BUCKETS):
        if hp < upper:
            return HP_BUCKET_LABELS[i]
    return HP_BUCKET_LABELS[-1]


def _bucket_turn(turn: int) -> str:
    """Bucket a turn index into a label.

    Buckets: [1, 4), [4, 7), [7, 10), [10, 100]
    Labels:  1-3,  4-6,   7-9,   10+
    """
    if turn < TURN_BUCKETS[0]:
        return TURN_BUCKET_LABELS[0]
    for i, upper in enumerate(TURN_BUCKETS):
        if turn < upper:
            return TURN_BUCKET_LABELS[i]
    return TURN_BUCKET_LABELS[-1]


def _classify_action(action_key: List) -> str:
    """Classify a single V4a action key into a category."""
    if not isinstance(action_key, list) or len(action_key) < 2:
        return "unknown"
    kind = str(action_key[0])
    if kind == "switch":
        return "switch"
    if kind == "pass":
        return "pass"
    if kind == "move":
        # Without base_power info, use a heuristic
        # based on the move_id.
        move_id = str(action_key[1])
        # Protect-like and ally-target status moves
        # share the "move_status_ally" category for
        # RL purposes. Protect is a self-targeting
        # move but for dataset action-category
        # distribution, it groups with ally-beneficial
        # status moves.
        STATUS_ALLY = {
            "protect", "detect", "spikyshield", "kingsshield",
            "banefulbunker", "silktrap", "burningbulwark", "obstruct",
            "maxguard", "healpulse", "floralhealing", "decorate",
            "helpinghand", "coaching", "howl", "lifedew",
            "aromatherapy", "healbell", "followme", "ragepowder",
        }
        # Opponent-target status moves.
        STATUS_OPP = {
            "thunderwave", "taunt", "encore", "disable", "torment",
            "willowisp", "toxic", "spore", "sleeppowder", "charm",
            "scaryface", "screech", "faketears", "metalsound",
            "gastroacid", "fakeout", "icywind", "electroweb",
        }
        # Field-target status moves.
        STATUS_FIELD = {
            "safeguard", "lightscreen", "reflect", "auroraveil",
            "tailwind", "trickroom", "magiccoat", "haze",
        }
        if move_id in STATUS_ALLY:
            return "move_status_ally"
        if move_id in STATUS_OPP:
            return "move_status_opp"
        if move_id in STATUS_FIELD:
            return "move_status_field"
        return "move_attack"
    return "unknown"


def _entropy(counter: Counter) -> float:
    """Compute Shannon entropy of a count distribution."""
    total = sum(counter.values())
    if total == 0:
        return 0.0
    h = 0.0
    for c in counter.values():
        if c > 0:
            p = c / total
            h -= p * math.log2(p)
    return h


def _action_key_to_tuple(key: Any) -> Optional[Tuple]:
    """Convert a V4a key to a tuple for hashing."""
    if not isinstance(key, list):
        return None
    return tuple(str(x) for x in key)


def _check_v1_1_gates(
    rows: List[Dict[str, Any]],
    schema_versions: Counter,
) -> Dict[str, Any]:
    """Phase RL-DATA-2b: implement v1.1 data-quality gates.

    Returns a dict with:
        - schema_coverage: dict (schema version -> count)
        - v11_n_rows: int
        - v10_n_rows: int
        - field_coverage: dict (field -> coverage_rate)
        - hard_blocks: list[str] (descriptions of hard-block
          violations; any non-empty list is a BLOCKED
          readiness)
        - warnings: list[str] (soft warnings; warnings do
          not block but are surfaced)
        - n_unknown_support_moves: int
        - support_group_counts: dict (group -> count)
        - readiness_impact: str (READY / WARN / BLOCKED)
    """
    v10_n_rows = schema_versions.get("turn_rl_v1.0", 0)
    v11_n_rows = schema_versions.get("turn_rl_v1.1", 0)
    n_total = len(rows)
    n_v11 = v11_n_rows
    n_v10 = v10_n_rows

    # Gate 11 — schema coverage
    schema_coverage = {
        "v10": v10_n_rows,
        "v11": v11_n_rows,
        "other": n_total - v10_n_rows - v11_n_rows,
    }

    # Field coverage for v1.1 rows
    v11_rows = [
        r for r in rows
        if r.get("schema_version") == "turn_rl_v1.1"
    ]
    field_coverage: Dict[str, float] = {}
    if n_v11 > 0:
        for f in V1_1_GATE_FIELDS:
            present = sum(
                1 for r in v11_rows if f in r
            )
            field_coverage[f] = present / n_v11

    # Hard-block checks
    hard_blocks: List[str] = []
    warnings: List[str] = []
    for r in v11_rows:
        bt = r.get("battle_tag", "?")
        ti = r.get("turn_index", "?")
        # Gate 13 — hard blocks
        if r.get("used_species_ability_inference") is True:
            hard_blocks.append(
                f"Gate 13: used_species_ability_inference=True "
                f"at battle={bt} turn={ti}"
            )
        if r.get("impossible_target_detected") is True:
            hard_blocks.append(
                f"Gate 13: impossible_target_detected=True "
                f"at battle={bt} turn={ti}"
            )
        if r.get("blocked_action_resurrected_by_joint") is True:
            hard_blocks.append(
                f"Gate 13: blocked_action_resurrected_by_joint=True "
                f"at battle={bt} turn={ti}"
            )
        # Gate 18 — official server provenance
        if r.get("local_only_provenance") is False:
            hard_blocks.append(
                f"Gate 18: local_only_provenance=False "
                f"at battle={bt} turn={ti}"
            )

    # Gate 17 — unknown support move detector
    n_unknown = sum(
        1 for r in v11_rows
        if r.get("unknown_support_move_detected") is True
    )

    # Aggregate support-group counts from per-candidate
    # classifications.
    support_group_counts: Dict[str, int] = {}
    for r in v11_rows:
        dist = r.get("support_move_distribution")
        if isinstance(dist, dict):
            for g, c in dist.items():
                support_group_counts[g] = (
                    support_group_counts.get(g, 0) + c
                )

    # Soft warnings (do not block)
    if n_v11 > 0:
        for f, gate in V1_1_GATE_FIELDS.items():
            cov = field_coverage.get(f, 1.0)
            if cov < 0.5:
                warnings.append(
                    f"{gate}: field `{f}` coverage "
                    f"= {cov:.1%} in v1.1 rows"
                )
        if n_unknown > 0:
            warnings.append(
                f"Gate 17: {n_unknown} v1.1 row(s) with "
                f"unknown_support_move_detected=True (not blocking)"
            )

    # Readiness impact
    if hard_blocks:
        readiness_impact = "BLOCKED"
    elif warnings or n_v11 == 0:
        readiness_impact = "WARN"
    else:
        readiness_impact = "READY"

    return {
        "schema_coverage": schema_coverage,
        "v11_n_rows": v11_n_rows,
        "v10_n_rows": v10_n_rows,
        "field_coverage": field_coverage,
        "hard_blocks": hard_blocks,
        "warnings": warnings,
        "n_unknown_support_moves": n_unknown,
        "support_group_counts": support_group_counts,
        "readiness_impact": readiness_impact,
    }


def analyze(input_paths: List[str], top_n: int = 20) -> Dict[str, Any]:
    """Run the full quality analysis. Returns a report dict."""
    rows = []
    malformed = 0
    source_artifacts = set()
    schema_versions = Counter()
    for path in input_paths:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                rows.append(r)
                if r.get("source_artifact"):
                    source_artifacts.add(r["source_artifact"])
                if r.get("schema_version"):
                    schema_versions[r["schema_version"]] += 1
    n = len(rows)

    # 1. Row / Episode summary.
    episodes = set(r.get("episode_id", "") for r in rows)
    battles = set(r.get("battle_tag", "") for r in rows)
    rows_per_episode = Counter()
    for r in rows:
        ep = r.get("episode_id", "")
        rows_per_episode[ep] += 1
    rpe_counts = list(rows_per_episode.values())
    row_summary = {
        "n_rows": n,
        "n_episodes": len(episodes),
        "n_battles": len(battles),
        "n_source_artifacts": len(source_artifacts),
        "source_artifacts": sorted(source_artifacts),
        "schema_versions": dict(schema_versions),
        "n_malformed_json": malformed,
        "rows_per_episode_min": min(rpe_counts) if rpe_counts else 0,
        "rows_per_episode_median": (
            sorted(rpe_counts)[len(rpe_counts) // 2]
            if rpe_counts
            else 0
        ),
        "rows_per_episode_max": max(rpe_counts) if rpe_counts else 0,
    }

    # 2. Reward summary.
    reward_total = Counter()
    reward_by_arm = defaultdict(Counter)
    reward_by_side = defaultdict(Counter)
    reward_by_turn_bucket = defaultdict(Counter)
    reward_by_cat = defaultdict(Counter)
    for r in rows:
        rw = r.get("terminal_reward")
        if rw is None:
            continue
        reward_total[rw] += 1
        reward_by_arm[r.get("benchmark_arm", "unknown")][rw] += 1
        reward_by_side[r.get("player_side", "unknown")][rw] += 1
        reward_by_turn_bucket[
            _bucket_turn(r.get("turn_index", 0))
        ][rw] += 1
        sel = r.get("selected_joint_key", [])
        cat0 = _classify_action(sel[0]) if len(sel) > 0 else "unknown"
        cat1 = _classify_action(sel[1]) if len(sel) > 1 else "unknown"
        joint_cat = f"{cat0}+{cat1}"
        reward_by_cat[joint_cat][rw] += 1
    reward_summary = {
        "total": dict(reward_total),
        "by_arm": {k: dict(v) for k, v in reward_by_arm.items()},
        "by_player_side": {k: dict(v) for k, v in reward_by_side.items()},
        "by_turn_bucket": {
            k: dict(v) for k, v in reward_by_turn_bucket.items()
        },
        "by_selected_category": {
            k: dict(v) for k, v in reward_by_cat.items()
        },
    }

    # 3. Action distribution.
    sel_cat_slot0 = Counter()
    sel_cat_slot1 = Counter()
    sel_joint_cat = Counter()
    sel_joint_key = Counter()
    sel_move_id = Counter()
    for r in rows:
        sel = r.get("selected_joint_key", [])
        if len(sel) >= 1:
            sel_cat_slot0[_classify_action(sel[0])] += 1
        if len(sel) >= 2:
            sel_cat_slot1[_classify_action(sel[1])] += 1
        if len(sel) >= 2:
            sel_joint_cat[
                f"{_classify_action(sel[0])}+{_classify_action(sel[1])}"
            ] += 1
        k = _action_key_to_tuple(sel)
        if k is not None:
            sel_joint_key[str(k)] += 1
        for k in sel:
            t = _action_key_to_tuple(k)
            if t is not None and len(t) >= 2 and t[0] == "move":
                sel_move_id[t[1]] += 1
    n_unique_joint = len(sel_joint_key)
    top_joint = sel_joint_key.most_common(top_n)
    top_move = sel_move_id.most_common(top_n)
    # Concentration ratios.
    total_sel = sum(sel_joint_key.values())
    top5_conc = (
        sum(c for _, c in sel_joint_key.most_common(5)) / total_sel
        if total_sel > 0
        else 0.0
    )
    top10_conc = (
        sum(c for _, c in sel_joint_key.most_common(10)) / total_sel
        if total_sel > 0
        else 0.0
    )
    action_distribution = {
        "selected_category_slot0": dict(sel_cat_slot0),
        "selected_category_slot1": dict(sel_cat_slot1),
        "selected_joint_category": dict(sel_joint_cat),
        "n_unique_selected_joint_keys": n_unique_joint,
        "selected_joint_entropy_bits": _entropy(sel_joint_key),
        "top_selected_joint_keys": top_joint,
        "top_selected_move_ids": top_move,
        "top5_concentration": top5_conc,
        "top10_concentration": top10_conc,
    }

    # 4. Legal action space.
    legal0_counts = []
    legal1_counts = []
    legal_joint_counts = []
    n_legal_violations = 0
    n_empty_legal = 0
    for r in rows:
        l0 = r.get("legal_action_keys_slot0") or []
        l1 = r.get("legal_action_keys_slot1") or []
        if not l0:
            n_empty_legal += 1
        if not l1:
            n_empty_legal += 1
        legal0_counts.append(len(l0))
        legal1_counts.append(len(l1))
        # Estimate joint legal as product (cartesian).
        legal_joint_counts.append(len(l0) * len(l1))
        # Check selected is in legal.
        sel = r.get("selected_joint_key", [])
        if sel:
            in0 = any(
                _action_key_to_tuple(k) == _action_key_to_tuple(sel[0])
                for k in l0
            )
            in1 = any(
                _action_key_to_tuple(k) == _action_key_to_tuple(sel[1])
                for k in l1
            )
            if not (in0 and in1):
                n_legal_violations += 1
    def _min_med_max(xs):
        if not xs:
            return (0, 0, 0)
        s = sorted(xs)
        return (
            s[0],
            s[len(s) // 2],
            s[-1],
        )
    legal_summary = {
        "slot0_min_median_max": _min_med_max(legal0_counts),
        "slot1_min_median_max": _min_med_max(legal1_counts),
        "joint_estimate_min_median_max": _min_med_max(legal_joint_counts),
        "n_legal_violations": n_legal_violations,
        "n_empty_legal": n_empty_legal,
    }

    # 5. State coverage.
    our_species = Counter()
    opp_species = Counter()
    our_hp = Counter()
    opp_hp = Counter()
    weather = Counter()
    fields = Counter()
    turn_bucket = Counter()
    for r in rows:
        ss = r.get("state_snapshot") or {}
        for s in ss.get("our_active_species") or []:
            our_species[str(s)] += 1
        for s in ss.get("opp_active_species") or []:
            opp_species[str(s)] += 1
        for h in ss.get("our_active_hp_fraction") or []:
            try:
                our_hp[_bucket_hp(float(h))] += 1
            except (TypeError, ValueError):
                pass
        for h in ss.get("opp_active_hp_fraction") or []:
            try:
                opp_hp[_bucket_hp(float(h))] += 1
            except (TypeError, ValueError):
                pass
        w = ss.get("weather")
        if w is not None:
            weather[str(w)] += 1
        f = ss.get("fields")
        if isinstance(f, list):
            fields[",".join(sorted(f)) if f else "none"] += 1
        elif f is not None:
            fields[str(f)] += 1
        else:
            fields["none"] += 1
        turn_bucket[_bucket_turn(r.get("turn_index", 0))] += 1
    state_coverage = {
        "our_active_species": dict(
            our_species.most_common(top_n)
        ),
        "opp_active_species": dict(
            opp_species.most_common(top_n)
        ),
        "our_active_hp_buckets": dict(our_hp),
        "opp_active_hp_buckets": dict(opp_hp),
        "weather": dict(weather),
        "fields": dict(fields),
        "turn_buckets": dict(turn_bucket),
        "n_unique_our_species": len(our_species),
        "n_unique_opp_species": len(opp_species),
    }

    # 6. Score / Margin summary.
    sel_scores = []
    margins = []
    n_with_score = 0
    n_with_margin = 0
    n_low_margin = 0
    n_high_margin = 0
    margin_by_reward = defaultdict(list)
    for r in rows:
        ss = r.get("selected_score")
        if ss is not None:
            sel_scores.append(float(ss))
            n_with_score += 1
        m = r.get("score_gap_selected_best_alt")
        if m is not None:
            margins.append(float(m))
            n_with_margin += 1
            if m < 10.0:
                n_low_margin += 1
            if m > 100.0:
                n_high_margin += 1
            rw = r.get("terminal_reward")
            if rw is not None:
                margin_by_reward[rw].append(float(m))
    def _stats(xs):
        if not xs:
            return {"count": 0, "min": None, "median": None, "max": None}
        s = sorted(xs)
        return {
            "count": len(xs),
            "min": s[0],
            "median": s[len(s) // 2],
            "max": s[-1],
        }
    margin_stats = _stats(margins)
    score_stats = _stats(sel_scores)
    margin_by_reward_stats = {
        str(rw): _stats(xs) for rw, xs in margin_by_reward.items()
    }
    score_margin_summary = {
        "selected_score": score_stats,
        "score_gap": margin_stats,
        "n_with_score": n_with_score,
        "n_with_margin": n_with_margin,
        "n_low_margin_under_10": n_low_margin,
        "n_high_margin_over_100": n_high_margin,
        "margin_by_reward": margin_by_reward_stats,
    }

    # 7. Counterfactual / optional fields coverage.
    n_scf = 0
    n_sp = 0
    n_stale = 0
    n_overkill = 0
    n_focus = 0
    missing = Counter()
    for r in rows:
        if r.get("switch_counterfactual"):
            n_scf += 1
        if r.get("speed_priority_threatened") is not None:
            n_sp += 1
        if r.get("stale_target_avoided") is not None:
            n_stale += 1
        if r.get("overkill_penalty_triggered") is not None:
            n_overkill += 1
        if r.get("focus_fire_triggered") is not None:
            n_focus += 1
        # Count missing optional fields (None or empty).
        for k in (
            "switch_counterfactual",
            "speed_priority_threatened",
            "expected_to_faint_before_moving",
            "stale_target_avoided",
            "overkill_penalty_triggered",
            "focus_fire_triggered",
            "joint_order_count",
            "total_legal_joint_orders",
        ):
            v = r.get(k)
            if v is None or v == "" or v == []:
                missing[k] += 1
    counterfactual_coverage = {
        "n_switch_counterfactual": n_scf,
        "n_speed_priority": n_sp,
        "n_stale_target": n_stale,
        "n_overkill": n_overkill,
        "n_focus_fire": n_focus,
        "missing_optional_field_counts": dict(missing),
    }

    # 8. Duplicate / bias checks.
    # Duplicate state-action pairs: (state_hash, joint_key).
    sa_pairs = set()
    n_dup_sa = 0
    n_dup_battle_turn_action = 0
    seen_bta = set()
    arm_counts = Counter()
    side_counts = Counter()
    for r in rows:
        ss = r.get("state_snapshot") or {}

        def _clean_list(v):
            """Convert each element to str, filter Nones."""
            return tuple(sorted(
                str(x) for x in (v or []) if x is not None
            ))

        def _clean_hp(v):
            return tuple(
                round(float(x), 3)
                for x in (v or [])
                if x is not None
            )

        ss_id = (
            _clean_list(ss.get("our_active_species")),
            _clean_list(ss.get("opp_active_species")),
            _clean_hp(ss.get("our_active_hp_fraction")),
            _clean_hp(ss.get("opp_active_hp_fraction")),
        )
        sel = r.get("selected_joint_key", [])
        sel_id = (
            _action_key_to_tuple(sel[0]) if len(sel) > 0 else None,
            _action_key_to_tuple(sel[1]) if len(sel) > 1 else None,
        )
        sa_key = (ss_id, sel_id)
        if sa_key in sa_pairs:
            n_dup_sa += 1
        else:
            sa_pairs.add(sa_key)
        bta_key = (
            r.get("battle_tag"),
            r.get("turn_index"),
            sel_id[0],
            sel_id[1],
        )
        if bta_key in seen_bta:
            n_dup_battle_turn_action += 1
        else:
            seen_bta.add(bta_key)
        arm_counts[r.get("benchmark_arm", "unknown")] += 1
        side_counts[r.get("player_side", "unknown")] += 1
    duplicate_bias = {
        "n_duplicate_state_action": n_dup_sa,
        "n_unique_state_action": len(sa_pairs),
        "n_dup_battle_turn_action": n_dup_battle_turn_action,
        "arm_counts": dict(arm_counts),
        "side_counts": dict(side_counts),
    }

    # 10. v1.1 quality gates (Phase RL-DATA-2b).
    v11_gates = _check_v1_1_gates(rows, schema_versions)

    # 9. RL readiness.
    criteria = {
        "schema_valid": (
            schema_versions.get(EXPECTED_SCHEMA, 0) == n
            and n > 0
        ),
        "rows_ge_500": n >= 500,
        "episodes_ge_40": len(episodes) >= 40,
        "reward_classes_both_present": (
            reward_total.get(1, 0) > 0
            and reward_total.get(-1, 0) > 0
        ),
        "selected_entropy_not_degenerate": (
            action_distribution["selected_joint_entropy_bits"] >= 2.0
        ),
        "legal_action_coverage_ge_95pct": (
            n_legal_violations / n < 0.05 if n > 0 else False
        ),
        "duplicate_state_action_ratio_not_extreme": (
            n_dup_sa / n < 0.30 if n > 0 else False
        ),
        "missing_required_lt_5pct": (
            row_summary.get("n_malformed_json", 0) / n < 0.05
            if n > 0
            else False
        ),
    }
    n_criteria_met = sum(1 for v in criteria.values() if v)
    if n_criteria_met == len(criteria):
        readiness = "READY_FOR_DRYRUN"
    elif n_criteria_met >= len(criteria) * 0.6:
        readiness = "PARTIAL"
    else:
        readiness = "NOT_READY"
    rl_readiness = {
        "readiness": readiness,
        "n_criteria_met": n_criteria_met,
        "n_criteria_total": len(criteria),
        "criteria": criteria,
    }

    # Adjust readiness based on v1.1 hard blocks.
    # A v1.1 hard block makes the dataset BLOCKED regardless
    # of v1.0 readiness criteria. v1.1 warnings are
    # surfaced but do not change v1.0 readiness.
    v11_impact = v11_gates.get("readiness_impact", "WARN")
    if v11_impact == "BLOCKED":
        readiness = "BLOCKED"
    rl_readiness["readiness"] = readiness
    rl_readiness["v11_impact"] = v11_impact
    rl_readiness["n_v11_hard_blocks"] = len(
        v11_gates.get("hard_blocks", [])
    )

    # Assemble report.
    report = {
        "row_summary": row_summary,
        "reward_summary": reward_summary,
        "action_distribution": action_distribution,
        "legal_summary": legal_summary,
        "state_coverage": state_coverage,
        "score_margin_summary": score_margin_summary,
        "counterfactual_coverage": counterfactual_coverage,
        "duplicate_bias": duplicate_bias,
        "v11_gates": v11_gates,
        "rl_readiness": rl_readiness,
    }
    return report


def write_markdown(report: Dict[str, Any], path: str) -> None:
    """Write a human-readable markdown report."""
    lines = []
    lines.append("# Turn-level offline dataset quality")
    lines.append("")
    rs = report.get("row_summary", {})
    lines.append("## Row / Episode Summary")
    lines.append("")
    lines.append(f"- rows: {rs.get('n_rows')}")
    lines.append(f"- episodes: {rs.get('n_episodes')}")
    lines.append(f"- battles: {rs.get('n_battles')}")
    lines.append(f"- source_artifacts: {rs.get('n_source_artifacts')}")
    lines.append(f"- schema_versions: {rs.get('schema_versions')}")
    lines.append(f"- malformed_json: {rs.get('n_malformed_json')}")
    lines.append(
        f"- rows_per_episode: min={rs.get('rows_per_episode_min')}, "
        f"median={rs.get('rows_per_episode_median')}, "
        f"max={rs.get('rows_per_episode_max')}"
    )
    lines.append("")
    # Reward.
    lines.append("## Reward Summary")
    lines.append("")
    rew = report.get("reward_summary", {})
    lines.append(f"- total: {rew.get('total')}")
    lines.append(f"- by_arm: {rew.get('by_arm')}")
    lines.append(f"- by_player_side: {rew.get('by_player_side')}")
    lines.append(f"- by_turn_bucket: {rew.get('by_turn_bucket')}")
    lines.append(
        f"- by_selected_category (top 10): "
        f"{dict(list(rew.get('by_selected_category', {}).items())[:10])}"
    )
    lines.append("")
    # Action distribution.
    lines.append("## Action Distribution")
    lines.append("")
    ad = report.get("action_distribution", {})
    lines.append(
        f"- selected_category_slot0: {ad.get('selected_category_slot0')}"
    )
    lines.append(
        f"- selected_category_slot1: {ad.get('selected_category_slot1')}"
    )
    lines.append(
        f"- selected_joint_category (top 10): "
        f"{dict(list(ad.get('selected_joint_category', {}).items())[:10])}"
    )
    lines.append(
        f"- n_unique_selected_joint_keys: "
        f"{ad.get('n_unique_selected_joint_keys')}"
    )
    lines.append(
        f"- selected_joint_entropy_bits: "
        f"{ad.get('selected_joint_entropy_bits'):.3f}"
    )
    lines.append(f"- top5_concentration: {ad.get('top5_concentration'):.3f}")
    lines.append(
        f"- top10_concentration: {ad.get('top10_concentration'):.3f}"
    )
    lines.append("")
    # Legal action space.
    lines.append("## Legal Action Space")
    lines.append("")
    ls = report.get("legal_summary", {})
    lines.append(
        f"- slot0: min={ls.get('slot0_min_median_max', (0, 0, 0))[0]}, "
        f"median={ls.get('slot0_min_median_max', (0, 0, 0))[1]}, "
        f"max={ls.get('slot0_min_median_max', (0, 0, 0))[2]}"
    )
    lines.append(
        f"- slot1: min={ls.get('slot1_min_median_max', (0, 0, 0))[0]}, "
        f"median={ls.get('slot1_min_median_max', (0, 0, 0))[1]}, "
        f"max={ls.get('slot1_min_median_max', (0, 0, 0))[2]}"
    )
    lines.append(
        f"- joint (cartesian est.): "
        f"min={ls.get('joint_estimate_min_median_max', (0, 0, 0))[0]}, "
        f"median={ls.get('joint_estimate_min_median_max', (0, 0, 0))[1]}, "
        f"max={ls.get('joint_estimate_min_median_max', (0, 0, 0))[2]}"
    )
    lines.append(f"- n_legal_violations: {ls.get('n_legal_violations')}")
    lines.append(f"- n_empty_legal: {ls.get('n_empty_legal')}")
    lines.append("")
    # State coverage.
    lines.append("## State Coverage")
    lines.append("")
    sc = report.get("state_coverage", {})
    lines.append(
        f"- n_unique_our_species: {sc.get('n_unique_our_species')}"
    )
    lines.append(
        f"- n_unique_opp_species: {sc.get('n_unique_opp_species')}"
    )
    lines.append(f"- our_active_hp_buckets: {sc.get('our_active_hp_buckets')}")
    lines.append(f"- opp_active_hp_buckets: {sc.get('opp_active_hp_buckets')}")
    lines.append(f"- weather: {sc.get('weather')}")
    lines.append(f"- fields: {sc.get('fields')}")
    lines.append(f"- turn_buckets: {sc.get('turn_buckets')}")
    lines.append(
        f"- our_active_species (top 10): "
        f"{dict(list(sc.get('our_active_species', {}).items())[:10])}"
    )
    lines.append(
        f"- opp_active_species (top 10): "
        f"{dict(list(sc.get('opp_active_species', {}).items())[:10])}"
    )
    lines.append("")
    # Score / margin.
    lines.append("## Score / Margin Summary")
    lines.append("")
    sm = report.get("score_margin_summary", {})
    lines.append(f"- selected_score: {sm.get('selected_score')}")
    lines.append(f"- score_gap: {sm.get('score_gap')}")
    lines.append(f"- n_with_score: {sm.get('n_with_score')}")
    lines.append(f"- n_with_margin: {sm.get('n_with_margin')}")
    lines.append(f"- n_low_margin_under_10: {sm.get('n_low_margin_under_10')}")
    lines.append(
        f"- n_high_margin_over_100: {sm.get('n_high_margin_over_100')}"
    )
    lines.append(f"- margin_by_reward: {sm.get('margin_by_reward')}")
    lines.append("")
    # Counterfactual coverage.
    lines.append("## Counterfactual / Optional Fields")
    lines.append("")
    cc = report.get("counterfactual_coverage", {})
    lines.append(
        f"- n_switch_counterfactual: {cc.get('n_switch_counterfactual')}"
    )
    lines.append(f"- n_speed_priority: {cc.get('n_speed_priority')}")
    lines.append(f"- n_stale_target: {cc.get('n_stale_target')}")
    lines.append(f"- n_overkill: {cc.get('n_overkill')}")
    lines.append(f"- n_focus_fire: {cc.get('n_focus_fire')}")
    lines.append(
        f"- missing_optional_field_counts: "
        f"{cc.get('missing_optional_field_counts')}"
    )
    lines.append("")
    # Duplicate / bias.
    lines.append("## Duplicate / Bias Checks")
    lines.append("")
    db = report.get("duplicate_bias", {})
    lines.append(
        f"- n_duplicate_state_action: {db.get('n_duplicate_state_action')}"
    )
    lines.append(
        f"- n_unique_state_action: {db.get('n_unique_state_action')}"
    )
    lines.append(
        f"- n_dup_battle_turn_action: {db.get('n_dup_battle_turn_action')}"
    )
    lines.append(f"- arm_counts: {db.get('arm_counts')}")
    lines.append(f"- side_counts: {db.get('side_counts')}")
    lines.append("")
    # RL readiness.
    lines.append("## RL Readiness")
    lines.append("")
    rlr = report.get("rl_readiness", {})
    lines.append(
        f"- readiness: **{rlr.get('readiness')}** "
        f"({rlr.get('n_criteria_met')}/{rlr.get('n_criteria_total')})"
    )
    lines.append("")
    lines.append("| criterion | pass |")
    lines.append("|---|---|")
    for k, v in rlr.get("criteria", {}).items():
        lines.append(f"| {k} | {v} |")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_summary(report: Dict[str, Any], path: str) -> None:
    """Write the JSON summary."""
    with open(path, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True, default=str)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only quality analyzer for turn_rl_v1.0 "
            "datasets."
        )
    )
    parser.add_argument(
        "--input", action="append", required=True,
        help="Input dataset JSONL. Pass multiple times.",
    )
    parser.add_argument(
        "--output-md", required=True,
        help="Output markdown report path.",
    )
    parser.add_argument(
        "--output-json", required=True,
        help="Output JSON summary path.",
    )
    parser.add_argument(
        "--top-n", type=int, default=20,
        help="Top N items to include in lists (default 20).",
    )
    args = parser.parse_args(argv)
    report = analyze(args.input, top_n=args.top_n)
    write_markdown(report, args.output_md)
    write_summary(report, args.output_json)
    print(
        f"Readiness: {report['rl_readiness']['readiness']}",
        file=sys.stderr,
    )
    print(f"Wrote {args.output_md}", file=sys.stderr)
    print(f"Wrote {args.output_json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
