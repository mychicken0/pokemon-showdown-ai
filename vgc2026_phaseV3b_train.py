#!/usr/bin/env python3
"""Phase V3b — train opponent-adaptive preview model.

Ponytail: extend the existing V3a.1 pairwise
learner and reuse its data loading. Only
substitute the feature extractor. Keep the
training algorithm, group split, and decisive-
pair filter unchanged.
"""
import argparse
import hashlib
import json
import os
import random
import statistics
import sys
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vgc2026_phaseV3a_learn_preview import (
    DEFAULT_V3A1_SOURCES,
    _stable_team_hash,
    assert_no_leakage,
    averaged_pairwise_update,
    baseline_validate,
    build_decisive_pair_targets,
    group_split,
    load_paired_artifacts,
    save_model,
    _pairwise_accuracy,
)
from vgc2026_phaseV3b_opponent_features import (
    v3b_features_for_plan,
)


# ---------------------------------------------------------------------------
# V3b artifact paths
# ---------------------------------------------------------------------------

DEFAULT_V3B_MODEL_PATH = (
    "logs/vgc2026_phaseV3b_preview_model.json"
)
DEFAULT_V3B_REPORT_PATH = (
    "logs/vgc2026_phaseV3b_training_report.json"
)
DEFAULT_V3B_AUDIT_JSON = (
    "logs/vgc2026_phaseV3b_feature_audit.json"
)
DEFAULT_V3B_AUDIT_MD = (
    "logs/vgc2026_phaseV3b_feature_audit.md"
)
V3A1_VAL_ACC_REFERENCE = 0.75


# ---------------------------------------------------------------------------
# V3b feature extraction
# ---------------------------------------------------------------------------


def _extract_v3b_features(
    our_team: List[Dict[str, Any]],
    opp_team: List[Dict[str, Any]],
    chosen_4: List[str],
    lead_2: List[str],
    back_2: List[str],
) -> Dict[str, float]:
    """Compute V3b features for a single plan.

    ponytail: training rows are battle-decisive
    pairs from V2c/V2d/V2f artifacts. The
    chosen_4 in those artifacts may not match
    any of the 90 enumerated plans (the artifacts
    record actual picks from the showdown server
    which use team preview numbering, not the
    pure enumeration). The base 20 V3b features
    are computed via v3b_features_for_plan which
    resolves the plan directly from chosen/lead/
    back. Deltas are computed at audit time, not
    at training time.
    """
    return v3b_features_for_plan(
        our_team, chosen_4, lead_2, back_2, opp_team
    )


def _discover_v3b_feature_names(
    rows: List[Dict[str, Any]],
) -> List[str]:
    """Discover V3b feature names from stored
    our_features keys. ponytail: bypasses V3a.1's
    discover_feature_names which rebuilds V3a.1
    features via extract_plan_features.
    """
    names: set = set()
    for r in rows:
        feats = r.get("our_features", {}) or {}
        names.update(feats.keys())
    return sorted(names)


def _load_v3b_rows(
    jsonl_paths: List[str], team_pool: Any
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Load rows with V3b features (drop empty).
    Reuses load_paired_artifacts from V3a.
    ponytail: V3b-specific data assembly. Uses
    the simple v3b_features_for_plan for the
    chosen_4 in the artifact (no enumeration
    needed for training).
    """
    rows: List[Dict[str, Any]] = []
    skipped: Dict[str, int] = {}
    for path in jsonl_paths:
        if not os.path.isfile(path):
            skipped[f"missing_source:{os.path.basename(path)}"] = (
                skipped.get(
                    f"missing_source:{os.path.basename(path)}", 0
                ) + 1
            )
            continue
        source = os.path.basename(path)
        for r in load_paired_artifacts(path, team_pool):
            # Look up opponent team from rank, same as
            # load_multi_source in V3a.1.
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
            try:
                pf = _extract_v3b_features(
                    r["our_team"],
                    opp_team_list,
                    r["our_chosen_4"],
                    r["our_lead_2"],
                    r["our_back_2"],
                )
                r["our_features"] = dict(pf)
            except Exception:
                r["our_features"] = {}
                skipped["feature_extraction_failed"] = (
                    skipped.get("feature_extraction_failed", 0) + 1
                )
                continue
            if not r["our_features"]:
                skipped["empty_features"] = (
                    skipped.get("empty_features", 0) + 1
                )
                continue
            rows.append(r)
    return rows, skipped


# ---------------------------------------------------------------------------
# Training (reuses V3a.1 averaged pairwise perceptron)
# ---------------------------------------------------------------------------


def train_v3b(
    rows: List[Dict[str, Any]],
    feature_names: List[str],
    n_epochs: int = 5,
    learning_rate: float = 0.1,
    l2: float = 0.01,
    min_margin: float = 1.0,
    averaged: bool = True,
    seed: int = 42,
    val_fraction: float = 0.2,
) -> Tuple[Dict[str, float], float, Dict[str, Any]]:
    """Train V3b with the V3a.1 averaged pairwise
    perceptron. ponytail: same algorithm.
    """
    train_rows, val_rows, split_meta = group_split(
        rows, val_fraction=val_fraction, seed=seed
    )
    assert_no_leakage(train_rows, val_rows)
    train_pairs, train_skipped = build_decisive_pair_targets(
        train_rows
    )
    val_pairs, val_skipped = build_decisive_pair_targets(val_rows)
    weights = {name: 0.0 for name in feature_names}
    bias = 0.0
    accumulator: Dict[str, float] = {
        name: 0.0 for name in feature_names
    }
    bias_accumulator = 0.0
    n_updates = 0
    rng = random.Random(seed)
    for _ in range(n_epochs):
        rng.shuffle(train_pairs)
        for winner, loser in train_pairs:
            weights, bias, accumulator, bias_accumulator = (
                averaged_pairwise_update(
                    weights, bias,
                    winner["our_features"], loser["our_features"],
                    learning_rate=learning_rate, l2=l2,
                    min_margin=min_margin,
                    accumulator=accumulator if averaged else None,
                    bias_accumulator=bias_accumulator
                    if averaged else None,
                )
            )
            n_updates += 1
    if averaged and n_updates > 0:
        avg_w = {
            name: accumulator[name] / n_updates
            for name in feature_names
        }
        avg_b = bias_accumulator / n_updates
    else:
        avg_w = dict(weights)
        avg_b = bias
    train_acc = _pairwise_accuracy(avg_w, avg_b, train_pairs)
    val_acc = _pairwise_accuracy(avg_w, avg_b, val_pairs)
    val_acc_raw = _pairwise_accuracy(weights, bias, val_pairs)
    if val_acc_raw > val_acc:
        final_w, final_b, used_avg, final_val = (
            weights, bias, False, val_acc_raw
        )
    else:
        final_w, final_b, used_avg, final_val = (
            avg_w, avg_b, True, val_acc
        )
    weight_norm = sum(v * v for v in final_w.values()) ** 0.5
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
        "val_pairwise_accuracy_used": final_val,
        "weight_norm": weight_norm,
        "top_positive": [
            [n, v] for n, v in sorted_w if v > 0
        ][:10],
        "top_negative": [
            [n, v] for n, v in sorted_w if v < 0
        ][:10],
    }
    return final_w, final_b, metadata


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


def train_v3b_and_save(
    jsonl_paths: List[str],
    team_pool: Any,
    model_path: str = DEFAULT_V3B_MODEL_PATH,
    report_path: str = DEFAULT_V3B_REPORT_PATH,
    n_epochs: int = 5,
    learning_rate: float = 0.1,
    l2: float = 0.01,
    min_margin: float = 1.0,
    averaged: bool = True,
    seed: int = 42,
    val_fraction: float = 0.2,
) -> Dict[str, Any]:
    """End-to-end V3b training pipeline."""
    rows, source_skipped = _load_v3b_rows(jsonl_paths, team_pool)
    if not rows:
        raise RuntimeError("No V3b rows loaded from any source")
    feature_names = _discover_v3b_feature_names(rows)
    weights, bias, train_meta = train_v3b(
        rows, feature_names,
        n_epochs=n_epochs, learning_rate=learning_rate,
        l2=l2, min_margin=min_margin, averaged=averaged,
        seed=seed, val_fraction=val_fraction,
    )
    model_artifact = save_model(
        model_path, weights, bias, feature_names, train_meta
    )
    val_hashes = set(
        train_meta["split_meta"]["val_team_hashes"]
    )
    val_rows = [r for r in rows if r["team_hash"] in val_hashes]
    val_pairs, _ = build_decisive_pair_targets(val_rows)
    baselines = baseline_validate(val_pairs, team_pool)
    val_acc = train_meta["val_pairwise_accuracy_used"]
    artifact_payload = json.loads(
        json.dumps(
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
        json.dumps(artifact_payload, sort_keys=True).encode()
    ).hexdigest()
    source_counts: Dict[str, int] = {}
    for r in rows:
        source_counts[r.get("source", "?")] = (
            source_counts.get(r.get("source", "?"), 0) + 1
        )
    val_improved_vs_v3a1 = val_acc > V3A1_VAL_ACC_REFERENCE
    report = {
        "phase": "V3b",
        "sources": sorted(jsonl_paths),
        "source_row_counts": dict(source_counts),
        "rows_after_filter": len(rows),
        "source_skipped": dict(source_skipped),
        "train_meta": train_meta,
        "val_baselines": baselines,
        "val_acc_v3a1_reference": V3A1_VAL_ACC_REFERENCE,
        "val_improved_vs_v3a1": val_improved_vs_v3a1,
        "artifact_sha256": artifact_hash,
        "model_path": model_path,
        "report_path": report_path,
        "default_policy": "matchup_top4_v3",
        "policy_wrapper": (
            "learned_preview_v3b (opt-in only, "
            "gated on val improvement)"
        ),
    }
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)
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
# Audit
# ---------------------------------------------------------------------------


def write_audit_files(
    audit_report: Dict[str, Any],
    audit_json_path: str = DEFAULT_V3B_AUDIT_JSON,
    audit_md_path: str = DEFAULT_V3B_AUDIT_MD,
) -> None:
    """Write the feature audit (JSON + Markdown)."""
    os.makedirs(os.path.dirname(audit_json_path) or ".",
                exist_ok=True)
    with open(audit_json_path, "w") as f:
        json.dump(audit_report, f, indent=2, sort_keys=True)
    lines = [
        "# Phase V3b Feature Audit",
        "",
        f"- n_features: {audit_report['n_features']}",
        f"- n_opp_sensitive: {audit_report['n_opp_sensitive']}",
        f"- n_plan_varying: {audit_report['n_plan_varying']}",
        f"- n_plan_opp_pairs_audited: "
        f"{audit_report['n_plan_opp_pairs_audited']}",
        f"- n_total_plan_records: "
        f"{audit_report['n_total_plan_records']}",
        "",
        "| Feature | nonzero | plan_var | opp_var | opp_sens "
        "| plan_var_flag |",
        "|---|---:|---:|---:|:-:|:-:|",
    ]
    for s in audit_report["feature_summary"]:
        lines.append(
            f"| {s['name']} | {s['nonzero_count']} | "
            f"{s['avg_var_across_plans_same_team']:.4f} | "
            f"{s['var_across_opps_same_team']:.4f} | "
            f"{'Y' if s['opponent_sensitive'] else 'N'} | "
            f"{'Y' if s['plan_varying'] else 'N'} |"
        )
    lines.append("")
    with open(audit_md_path, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main_v3b():
    parser = argparse.ArgumentParser(
        description=(
            "Phase V3b opponent-adaptive preview model "
            "trainer"
        )
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
        default=DEFAULT_V3B_MODEL_PATH,
    )
    parser.add_argument(
        "--report-path",
        type=str,
        default=DEFAULT_V3B_REPORT_PATH,
    )
    parser.add_argument(
        "--audit-json",
        type=str,
        default=DEFAULT_V3B_AUDIT_JSON,
    )
    parser.add_argument(
        "--audit-md",
        type=str,
        default=DEFAULT_V3B_AUDIT_MD,
    )
    parser.add_argument(
        "--audit-teams",
        type=int,
        default=15,
    )
    parser.add_argument(
        "--audit-opps",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--audit-seed",
        type=int,
        default=42,
    )
    parser.add_argument(
        "--n-epochs", type=int, default=5
    )
    parser.add_argument(
        "--learning-rate", type=float, default=0.1
    )
    parser.add_argument(
        "--l2", type=float, default=0.01
    )
    parser.add_argument(
        "--min-margin", type=float, default=1.0
    )
    parser.add_argument(
        "--no-train",
        action="store_true",
        help="Run audit only, skip training.",
    )
    args = parser.parse_args()
    sources = [s for s in args.sources.split(",") if s]
    from vgc_team_pool import load_vgc_pool
    pool = load_vgc_pool()
    print("=" * 60)
    print("Phase V3b feature audit")
    print("=" * 60)
    from vgc2026_phaseV3b_opponent_features import (
        audit_v3b_features,
    )
    audit = audit_v3b_features(
        pool,
        n_teams=args.audit_teams,
        n_opps_per_team=args.audit_opps,
        seed=args.audit_seed,
    )
    write_audit_files(audit, args.audit_json, args.audit_md)
    print(
        f"n_features={audit['n_features']} "
        f"n_opp_sensitive={audit['n_opp_sensitive']} "
        f"n_plan_varying={audit['n_plan_varying']}"
    )
    opp_sens_pass = audit["n_opp_sensitive"] >= 15
    plan_var_pass = audit["n_plan_varying"] >= 10
    print(
        f"gate_opp_sensitive (>=15): "
        f"{'PASS' if opp_sens_pass else 'FAIL'}"
    )
    print(
        f"gate_plan_varying (>=10): "
        f"{'PASS' if plan_var_pass else 'FAIL'}"
    )
    if not (opp_sens_pass and plan_var_pass):
        print("BLOCK: feature audit gates failed. "
              "No training.")
        return 1
    if args.no_train:
        print("Audit-only run; no training.")
        return 0
    print("=" * 60)
    print("Phase V3b training")
    print("=" * 60)
    out = train_v3b_and_save(
        sources, pool,
        model_path=args.model_path,
        report_path=args.report_path,
        n_epochs=args.n_epochs,
        learning_rate=args.learning_rate,
        l2=args.l2,
        min_margin=args.min_margin,
    )
    val_acc = out["train_meta"]["val_pairwise_accuracy_used"]
    print(f"train_acc={out['train_meta']['train_pairwise_accuracy']:.4f}")
    print(f"val_acc={val_acc:.4f}")
    print(
        f"val_acc_v3a1_reference="
        f"{V3A1_VAL_ACC_REFERENCE:.4f}, "
        f"improved={out['report']['val_improved_vs_v3a1']}"
    )
    print(f"weight_norm={out['train_meta']['weight_norm']:.4f}")
    print(f"artifact_sha256={out['report']['artifact_sha256']}")
    print(f"model_path={args.model_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main_v3b())
