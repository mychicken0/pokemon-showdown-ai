#!/usr/bin/env python3
"""
Phase 6.4.10 — Voluntary Switch Quality Paired Analyzer.

Reads the artifacts produced by
``bot_doubles_voluntary_switch_paired_qualification.py``
and computes paired statistics.

Statistical methodology is the same as
``analyze_doubles_support_move_target_safety_paired.py``
(Wilson 95% CI, paired categories, exact sign tests,
paired bootstrap CI for the mean treatment effect).

The D1-D2 difference is a side-position diagnostic,
NOT a treatment effect, and is reported separately.

Per-slot voluntary-switch metrics (read from
authoritative production-generated audit fields):

  - voluntary_switch_decision_eligible
  - voluntary_switch_selected
  - voluntary_switch_unnecessary_selected
  - voluntary_switch_unsafe_candidate_selected
  - voluntary_switch_repeat_selected
  - voluntary_switch_sacrifice_opportunity
  - voluntary_switch_healthy_bench_preserved
  - voluntary_switch_safer_candidate_available
  - voluntary_switch_selection_changed
  - voluntary_switch_joint_selection_changed

Counterfactual uses production-generated
``voluntary_switch_counterfactual_action`` and
``voluntary_switch_selected_action`` (raw score maps,
no recomputation).
"""
import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple


def wilson_ci(s: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 1.0)
    p = s / n
    denom = 1 + (z ** 2) / n
    center = (p + (z ** 2) / (2 * n)) / denom
    margin = (
        z * math.sqrt(p * (1 - p) / n + (z ** 2) / (4 * n * n))
    ) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def exact_binomial_two_sided(k: int, n: int) -> float:
    if n == 0:
        return 1.0
    from math import comb
    if k > n - k:
        k = n - k
    p_le = sum(comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * p_le)


def exact_binomial_one_sided(k: int, n: int) -> float:
    if n == 0:
        return 1.0
    from math import comb
    return sum(comb(n, i) for i in range(k + 1)) / (2 ** n)


def paired_bootstrap_treatment(
    treatment_scores: List[int],
    n_boot: int = 2000,
    seed: int = 6410,
) -> Tuple[float, float, float]:
    if not treatment_scores:
        return (float("nan"), float("nan"), float("nan"))
    import random
    rng = random.Random(seed)
    n = len(treatment_scores)
    means = []
    for _ in range(n_boot):
        idxs = [rng.randrange(n) for _ in range(n)]
        sample = [treatment_scores[i] for i in idxs]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[int(0.975 * n_boot) - 1]
    point = sum(treatment_scores) / n
    return (point, lo, hi)


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _collect_vsw_metrics(audit_path: str) -> Dict[str, Any]:
    out = {
        "n_turns": 0,
        "n_eligible": 0,
        "n_selected": 0,
        "n_unnecessary": 0,
        "n_unsafe": 0,
        "n_repeat": 0,
        "n_sac_opp": 0,
        "n_healthy": 0,
        "n_safer_avail": 0,
        "n_sel_changed": 0,
        "n_joint_changed": 0,
        "spread_count": 0,
        "focus_fire_count": 0,
        "n_turns_counted": 0,
        "sel_active_risk_total": 0.0,
        "sel_candidate_risk_total": 0.0,
        "sel_risk_red_total": 0.0,
        "sel_best_stay_total": 0.0,
        "sel_score_adj_total": 0.0,
        "n_risk_red_with_nonzero": 0,
        "n_score_adj_n": 0,
        "n_best_stay_n": 0,
        # Phase 6.4.10d: new audit fields.
        "n_raw_switch_orders": 0,
        "n_candidate_total": 0,
        "n_extraction_mismatch": 0,
    }
    if not os.path.isfile(audit_path):
        return out
    records = _read_jsonl(audit_path)
    for rec in records:
        for td in rec.get("audit_turns", []) or []:
            out["n_turns"] += 1
            for sk in ("slot_0", "slot_1"):
                slot = td.get(sk, {}) or {}
                if (slot.get("action_types") or {}).get("spread"):
                    out["spread_count"] += 1
            if td.get("focus_fire_triggered"):
                out["focus_fire_count"] += 1
            # Phase 6.4.10d: eligibility from candidate_count
            # (the OLD voluntary_switch_decision_eligible
            # field was never populated, that was the
            # root cause of "0 opportunities" in 6.4.10).
            cand_count = td.get(
                "voluntary_switch_candidate_count", [0, 0]
            )
            raw_count = td.get(
                "voluntary_switch_raw_switch_order_count", [0, 0]
            )
            for si in (0, 1):
                cc = cand_count[si] if si < len(cand_count) else 0
                rc = raw_count[si] if si < len(raw_count) else 0
                out["n_candidate_total"] += cc
                out["n_raw_switch_orders"] += rc
                # Extraction mismatch: raw > 0 but cand == 0.
                # This is expected when active is None
                # (fainted) or force_switch is True
                # (forced replacement). The new audit
                # logger skips the VSW build in those
                # cases. raw still counts the forced
                # switch orders in valid_orders.
                if rc > 0 and cc == 0:
                    out["n_extraction_mismatch"] += 1
            eligible = [
                (cand_count[si] > 0) if si < len(cand_count) else False
                for si in (0, 1)
            ]
            selected = td.get(
                "voluntary_switch_selected", [False, False]
            )
            unnecessary = td.get(
                "voluntary_switch_unnecessary_selected",
                [False, False],
            )
            unsafe = td.get(
                "voluntary_switch_unsafe_candidate_selected",
                [False, False],
            )
            repeat = td.get(
                "voluntary_switch_repeat_selected", [False, False]
            )
            sac_opp = td.get(
                "voluntary_switch_sacrifice_opportunity",
                [False, False],
            )
            healthy = td.get(
                "voluntary_switch_healthy_bench_preserved",
                [False, False],
            )
            safer = td.get(
                "voluntary_switch_safer_candidate_available",
                [False, False],
            )
            sel_changed = td.get(
                "voluntary_switch_selection_changed",
                [False, False],
            )
            joint_changed = td.get(
                "voluntary_switch_joint_selection_changed", False
            )
            sel_active_risk = td.get(
                "voluntary_switch_selected_active_risk", [0.0, 0.0]
            )
            sel_candidate_risk = td.get(
                "voluntary_switch_selected_candidate_risk",
                [0.0, 0.0],
            )
            sel_risk_red = td.get(
                "voluntary_switch_selected_risk_reduction",
                [0.0, 0.0],
            )
            best_stay = td.get(
                "voluntary_switch_best_stay_score", [0.0, 0.0]
            )
            sel_score_adj = td.get(
                "voluntary_switch_selected_score_adjustment",
                [0.0, 0.0],
            )
            for si in (0, 1):
                if not (eligible[si] if si < len(eligible) else False):
                    continue
                out["n_eligible"] += 1
                if selected[si] if si < len(selected) else False:
                    out["n_selected"] += 1
                    out["n_turns_counted"] += 1
                    ar = (
                        sel_active_risk[si]
                        if si < len(sel_active_risk)
                        else 0.0
                    )
                    cr = (
                        sel_candidate_risk[si]
                        if si < len(sel_candidate_risk)
                        else 0.0
                    )
                    rr = (
                        sel_risk_red[si]
                        if si < len(sel_risk_red)
                        else 0.0
                    )
                    bs = best_stay[si] if si < len(best_stay) else 0.0
                    sa = (
                        sel_score_adj[si]
                        if si < len(sel_score_adj)
                        else 0.0
                    )
                    out["sel_active_risk_total"] += ar
                    out["sel_candidate_risk_total"] += cr
                    out["sel_risk_reduction_total"] += rr
                    out["sel_best_stay_total"] += bs
                    out["sel_score_adj_total"] += sa
                    out["n_risk_red_with_nonzero"] += 1
                    out["n_score_adj_n"] += 1
                    out["n_best_stay_n"] += 1
                    if unnecessary[si] if si < len(unnecessary) else False:
                        out["n_unnecessary"] += 1
                    if unsafe[si] if si < len(unsafe) else False:
                        out["n_unsafe"] += 1
                    if repeat[si] if si < len(repeat) else False:
                        out["n_repeat"] += 1
                if sac_opp[si] if si < len(sac_opp) else False:
                    out["n_sac_opp"] += 1
                if healthy[si] if si < len(healthy) else False:
                    out["n_healthy"] += 1
                if safer[si] if si < len(safer) else False:
                    out["n_safer_avail"] += 1
                if sel_changed[si] if si < len(sel_changed) else False:
                    out["n_sel_changed"] += 1
            if joint_changed:
                out["n_joint_changed"] += 1
    return out


def analyze(artifact_tag: str, expected_n_pairs: int = 100,
            merge_tags: Optional[List[str]] = None):
    battle_path = f"logs/voluntary_switch_paired_{artifact_tag}.jsonl"

    # Load main battles
    battles = _read_jsonl(battle_path)
    if not battles:
        print(f"ERROR: no battles in {battle_path}")
        sys.exit(2)
    # Optionally merge in additional chunks
    if merge_tags:
        for extra in merge_tags:
            extra_path = (
                f"logs/voluntary_switch_paired_{extra}.jsonl"
            )
            extra_battles = _read_jsonl(extra_path)
            if not extra_battles:
                print(f"WARN: no battles in {extra_path}")
                continue
            # Skip duplicates (same pair_id + side_swap)
            seen = {(b["pair_id"], b["side_swap"]) for b in battles}
            for b in extra_battles:
                key = (b["pair_id"], b["side_swap"])
                if key not in seen:
                    battles.append(b)
                    seen.add(key)

    # Decide output file paths. When merging, write to
    # a separate "_merged" tag so we do not overwrite
    # the single-chunk analysis.
    if merge_tags:
        merge_suffix = "_merged"
        analysis_json = (
            f"logs/voluntary_switch_paired_{artifact_tag}"
            f"{merge_suffix}_analysis.json"
        )
        analysis_md = (
            f"logs/voluntary_switch_paired_{artifact_tag}"
            f"{merge_suffix}_analysis.md"
        )
    else:
        analysis_json = (
            f"logs/voluntary_switch_paired_{artifact_tag}_analysis.json"
        )
        analysis_md = (
            f"logs/voluntary_switch_paired_{artifact_tag}_analysis.md"
        )
    by_pair: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for b in battles:
        by_pair.setdefault(b["pair_id"], {})[b["side_swap"]] = b

    on_categories = {
        "ON_both": 0, "OFF_both": 0, "split": 0, "invalid": 0,
    }
    d1_wins = d2_wins = 0
    d1_losses = d2_losses = 0
    treatment_scores: List[int] = []
    on_audit_paths: List[str] = []
    off_audit_paths: List[str] = []
    for pid in sorted(by_pair.keys()):
        d1 = by_pair[pid].get("D1")
        d2 = by_pair[pid].get("D2")
        if not d1 or not d2:
            on_categories["invalid"] += 1
            continue
        if d1["status"] != "ok" or d2["status"] != "ok":
            on_categories["invalid"] += 1
            continue
        if d1["on_won"] is None or d2["on_won"] is None:
            on_categories["invalid"] += 1
            continue
        d1w = d1["on_won"]
        d2w = d2["on_won"]
        if d1w and d2w:
            on_categories["ON_both"] += 1
            treatment_scores.append(+1)
        elif (not d1w) and (not d2w):
            on_categories["OFF_both"] += 1
            treatment_scores.append(-1)
        else:
            on_categories["split"] += 1
            treatment_scores.append(0)
        if d1w:
            d1_wins += 1
        else:
            d1_losses += 1
        if d2w:
            d2_wins += 1
        else:
            d2_losses += 1
        on_audit_paths.append(d1["p1_audit_path"])
        off_audit_paths.append(d1["p2_audit_path"])
        off_audit_paths.append(d2["p1_audit_path"])
        on_audit_paths.append(d2["p2_audit_path"])

    n_pairs_valid = len(treatment_scores)
    total_pairs = len(by_pair)
    combined_on_wins = (
        on_categories["ON_both"] * 2 + on_categories["split"]
    )
    wilson_lo, wilson_hi = wilson_ci(
        combined_on_wins, 2 * n_pairs_valid
    )
    k_on_both = on_categories["ON_both"]
    k_off_both = on_categories["OFF_both"]
    decisive = k_on_both + k_off_both
    p_two_sided = exact_binomial_two_sided(k_on_both, decisive)
    p_one_sided_reg = exact_binomial_one_sided(k_on_both, decisive)
    d1_rate = d1_wins / n_pairs_valid if n_pairs_valid else float("nan")
    d2_rate = d2_wins / n_pairs_valid if n_pairs_valid else float("nan")
    side_collapse = abs(d1_rate - d2_rate) if n_pairs_valid else float("nan")
    mean_treatment = (
        sum(treatment_scores) / len(treatment_scores)
        if treatment_scores
        else float("nan")
    )
    boot_point, boot_lo, boot_hi = paired_bootstrap_treatment(
        treatment_scores, n_boot=2000, seed=6410,
    )

    on_m = {}
    for ap in set(on_audit_paths):
        m = _collect_vsw_metrics(ap)
        for k, v in m.items():
            on_m[k] = on_m.get(k, 0) + v
    off_m = {}
    for ap in set(off_audit_paths):
        m = _collect_vsw_metrics(ap)
        for k, v in m.items():
            off_m[k] = off_m.get(k, 0) + v

    # Phase 6.4.10d: average turns ON vs OFF.
    on_turns: List[int] = []
    off_turns: List[int] = []
    on_status_counts: Dict[str, int] = {}
    off_status_counts: Dict[str, int] = {}
    for b in battles:
        target_turns = (
            on_turns if b.get("p1_arm") == "ON" else off_turns
        )
        target_status = (
            on_status_counts if b.get("p1_arm") == "ON"
            else off_status_counts
        )
        # Actually turns is per-battle, not per-arm.
        # We tag by which side is ON.
        # Re-do: tag by p1_arm == "ON" means ON is p1.
        bt_turns = int(b.get("turns", 0) or 0)
        status = b.get("status", "")
        if b.get("p1_arm") == "ON":
            on_turns.append(bt_turns)
            on_status_counts[status] = (
                on_status_counts.get(status, 0) + 1
            )
        else:
            off_turns.append(bt_turns)
            off_status_counts[status] = (
                off_status_counts.get(status, 0) + 1
            )

    avg_turns_on = (
        sum(on_turns) / len(on_turns) if on_turns else 0.0
    )
    avg_turns_off = (
        sum(off_turns) / len(off_turns) if off_turns else 0.0
    )
    # Phase 6.4.10d: timeout / error / no_battle counts.
    timeout_count = sum(
        1 for b in battles if b.get("status") != "ok"
    )

    report = {
        "audit_tag": artifact_tag,
        "n_pairs_total": total_pairs,
        "n_pairs_valid": n_pairs_valid,
        "n_battles": 2 * n_pairs_valid,
        "D1": {
            "on_wins": d1_wins,
            "on_losses": d1_losses,
            "on_win_rate": d1_rate,
        },
        "D2": {
            "on_wins": d2_wins,
            "on_losses": d2_losses,
            "on_win_rate": d2_rate,
        },
        "combined": {
            "on_wins": combined_on_wins,
            "on_win_rate": (
                combined_on_wins / (2 * n_pairs_valid)
                if n_pairs_valid
                else float("nan")
            ),
            "wilson_95_lo": wilson_lo,
            "wilson_95_hi": wilson_hi,
        },
        "paired_categories": on_categories,
        "sign_test_two_sided_p": p_two_sided,
        "sign_test_one_sided_regression_p": p_one_sided_reg,
        "treatment_effect": {
            "mean": mean_treatment,
            "n_pairs": len(treatment_scores),
            "paired_bootstrap": {
                "point": boot_point,
                "ci_95_lo": boot_lo,
                "ci_95_hi": boot_hi,
                "n_boot": 2000,
                "seed": 6410,
            },
        },
        "side_position_diagnostic": {
            "D1_minus_D2_win_rate": side_collapse,
            "side_split": {
                "D1_ON_win_rate": d1_rate,
                "D2_ON_win_rate": d2_rate,
            },
            "is_treatment_effect": False,
        },
        "on_metrics": on_m,
        "off_metrics": off_m,
        "phase6410d": {
            "avg_turns_on": avg_turns_on,
            "avg_turns_off": avg_turns_off,
            "on_status_counts": on_status_counts,
            "off_status_counts": off_status_counts,
            "n_invalid_battles": timeout_count,
        },
    }
    with open(analysis_json, "w") as f:
        json.dump(report, f, indent=2)
    md_lines = [
        f"# Phase 6.4.10 Paired Analysis — {artifact_tag}",
        "",
        f"- Total pairs: {total_pairs}",
        f"- Valid pairs: {n_pairs_valid}",
        f"- Invalid pairs: {on_categories['invalid']}",
        f"- Total battles: {2 * n_pairs_valid}",
        "",
        "## Aggregated ON win rate (200 battles / 100 pairs)",
        "",
        f"- Combined ON wins: {combined_on_wins}/"
        f"{2 * n_pairs_valid} = "
        f"{combined_on_wins / (2 * n_pairs_valid) if n_pairs_valid else float('nan'):.4f}",
        f"- Wilson 95% CI (n={2 * n_pairs_valid}, "
        f"s={combined_on_wins}): "
        f"[{wilson_lo:.4f}, {wilson_hi:.4f}]",
        "",
        "## Side-position diagnostic (NOT treatment effect)",
        "",
        f"- D1 (ON as p1): wins {d1_wins}/{n_pairs_valid} = "
        f"{d1_rate:.4f}",
        f"- D2 (ON as p2): wins {d2_wins}/{n_pairs_valid} = "
        f"{d2_rate:.4f}",
        f"- |D1 - D2|: {side_collapse:.4f} "
        f"({'WARNING' if side_collapse > 0.10 else 'OK'})",
        "",
        "## Paired categories",
        "",
        f"- ON both:  {on_categories['ON_both']}",
        f"- OFF both: {on_categories['OFF_both']}",
        f"- Split:    {on_categories['split']}",
        f"- Invalid:  {on_categories['invalid']}",
        "",
        "## Paired treatment effect (this is the adoption gate)",
        "",
        "Treatment score per pair:",
        "- +1 if ON won both D1 and D2 (ON_both)",
        "-  0 if split",
        "- -1 if OFF won both D1 and D2 (OFF_both)",
        "",
        f"- Mean treatment effect: {mean_treatment:.4f}",
        f"- Paired bootstrap 95% CI: "
        f"[{boot_lo:.4f}, {boot_hi:.4f}]",
        f"- **Adoption lower-bound gate reads this CI: "
        f"boot_lo = {boot_lo:.4f}**",
        "",
        "## Sign tests (decisive pairs only)",
        "",
        f"- Decisive pairs n = {decisive} "
        f"(={k_on_both} + {k_off_both})",
        f"- Two-sided exact p: {p_two_sided:.4f}",
        f"- One-sided (ON regression) p: "
        f"{p_one_sided_reg:.4f}",
        "",
        "## VSW surface (Phase 6.4.10d new fields)",
        "",
        f"- ON raw switch order count: "
        f"{on_m.get('n_raw_switch_orders', 0)}",
        f"- ON candidate total: "
        f"{on_m.get('n_candidate_total', 0)}",
        f"- OFF raw switch order count: "
        f"{off_m.get('n_raw_switch_orders', 0)}",
        f"- OFF candidate total: "
        f"{off_m.get('n_candidate_total', 0)}",
        f"- ON extraction mismatch (raw>0 && cand==0): "
        f"{on_m.get('n_extraction_mismatch', 0)}",
        f"- OFF extraction mismatch: "
        f"{off_m.get('n_extraction_mismatch', 0)}",
        f"- ON n_eligible: {on_m.get('n_eligible', 0)}",
        f"- OFF n_eligible: {off_m.get('n_eligible', 0)}",
        "",
        "## Phase diagnostics (Phase 6.4.10d)",
        "",
        f"- Avg turns ON: {avg_turns_on:.1f}",
        f"- Avg turns OFF: {avg_turns_off:.1f}",
        f"- ON status counts: {on_status_counts}",
        f"- OFF status counts: {off_status_counts}",
        f"- Invalid battles: {timeout_count}",
        "",
        "## ON metrics (paired audits)",
        "",
    ]
    for k, v in on_m.items():
        md_lines.append(f"- {k}: {v}")
    md_lines += ["", "## OFF metrics (paired audits)", ""]
    for k, v in off_m.items():
        md_lines.append(f"- {k}: {v}")
    with open(analysis_md, "w") as f:
        f.write("\n".join(md_lines) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Phase 6.4.10 voluntary switch paired analyzer"
    )
    parser.add_argument(
        "--artifact-tag", type=str, required=True,
        help="Artifact tag to analyze",
    )
    parser.add_argument(
        "--merge-tags", type=str, nargs="+", default=None,
        help="Optional list of additional artifact tags "
        "to merge in. Used to combine chunked paired "
        "qualification runs into a single dataset.",
    )
    args = parser.parse_args()
    report = analyze(args.artifact_tag, merge_tags=args.merge_tags)
    print(
        f"\nMean paired treatment effect: "
        f"{report['treatment_effect']['mean']:.4f}"
    )
    print(
        f"  Paired bootstrap 95% CI: "
        f"[{report['treatment_effect']['paired_bootstrap']['ci_95_lo']:.4f}, "
        f"{report['treatment_effect']['paired_bootstrap']['ci_95_hi']:.4f}]"
    )
    print(
        f"  ON-both / OFF-both / Split: "
        f"{report['paired_categories']['ON_both']} / "
        f"{report['paired_categories']['OFF_both']} / "
        f"{report['paired_categories']['split']}"
    )
    print(
        f"  Two-sided exact p: "
        f"{report['sign_test_two_sided_p']:.4f}"
    )
    print(
        f"  One-sided (ON regression) p: "
        f"{report['sign_test_one_sided_regression_p']:.4f}"
    )


if __name__ == "__main__":
    main()
