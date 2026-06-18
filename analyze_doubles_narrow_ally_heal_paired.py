#!/usr/bin/env python3
"""
Phase 6.3.8d — Narrow Ally-Heal Wrong-Side Safety
Paired Analyzer.

Reads artifacts produced by
``bot_doubles_narrow_ally_heal_paired_qualification.py``
and computes paired statistics.

Same statistical methodology as the broad
6.3.8c.1 analyzer, but only the narrow metrics:

  - D1/D2 ON win rate
  - Wilson 95% CI (n=200, s=combined_on_wins)
  - Paired categories: ON both / OFF both / split
  - Exact two-sided sign test (decisive pairs)
  - Exact one-sided regression p
  - Paired bootstrap 95% CI (resample 100 pairs)
  - Side-position diagnostic (D1-D2) separately
  - Narrow opportunities / blocked / selected /
    avoided / only-legal
  - Heal Pulse / Floral Healing / Decorate into
    opponent
  - Pollen Puff and Skill Swap false blocks
  - Spread / focus-fire counts
  - Accounting and mutual-exclusion invariants
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
    seed: int = 6381,
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


def _audit_path_for(battle: Dict[str, Any], which: str) -> str:
    if which == "p1":
        return battle.get("p1_audit_path") or ""
    return battle.get("p2_audit_path") or ""


def _collect_narrow_metrics(audit_path: str) -> Dict[str, Any]:
    out = {
        "n_turns": 0,
        "n_candidate_turns": 0,
        "n_blocked_turns": 0,
        "n_selected_wrong_side": 0,
        "n_only_legal": 0,
        "healpulse_into_opp": 0,
        "floralhealing_into_opp": 0,
        "decorate_into_opp": 0,
        "healpulse_into_ally": 0,
        "floralhealing_into_ally": 0,
        "decorate_into_ally": 0,
        "pollenpuff_blocked": 0,
        "skillswap_blocked": 0,
        "pollenpuff_candidates": 0,
        "skillswap_candidates": 0,
        "spread_count": 0,
        "focus_fire_count": 0,
        "accounting_fail": 0,
        "mutual_exclusion_fail": 0,
    }
    if not os.path.isfile(audit_path):
        return out
    records = _read_jsonl(audit_path)
    for rec in records:
        for turn in rec.get("audit_turns", []) or []:
            out["n_turns"] += 1
            cand_flag = turn.get("narrow_ally_heal_candidate", False)
            if cand_flag:
                out["n_candidate_turns"] += 1
            for sk in ("slot_0", "slot_1"):
                slot = turn.get(sk, {}) or {}
                if (slot.get("action_types") or {}).get("spread"):
                    out["spread_count"] += 1
            if turn.get("focus_fire_triggered"):
                out["focus_fire_count"] += 1
            for sk in ("slot_0", "slot_1"):
                s = turn.get(sk, {}) or {}
                if not s:
                    continue
                if s.get("narrow_ally_heal_candidate_blocked", False):
                    out["n_blocked_turns"] += 1
                if s.get("narrow_ally_heal_selected", False):
                    out["n_selected_wrong_side"] += 1
                if s.get("narrow_ally_heal_only_legal", False):
                    out["n_only_legal"] += 1
            # Per-candidate-table scan.
            for c in turn.get("narrow_ally_heal_candidates", []) or []:
                mid = c.get("move_id", "")
                tgt = c.get("target_side", "")
                if mid == "healpulse":
                    if tgt == "opponent":
                        out["healpulse_into_opp"] += 1
                    elif tgt == "ally":
                        out["healpulse_into_ally"] += 1
                elif mid == "floralhealing":
                    if tgt == "opponent":
                        out["floralhealing_into_opp"] += 1
                    elif tgt == "ally":
                        out["floralhealing_into_ally"] += 1
                elif mid == "decorate":
                    if tgt == "opponent":
                        out["decorate_into_opp"] += 1
                    elif tgt == "ally":
                        out["decorate_into_ally"] += 1
                elif mid == "pollenpuff":
                    out["pollenpuff_candidates"] += 1
                    if c.get("blocked"):
                        out["pollenpuff_blocked"] += 1
                elif mid == "skillswap":
                    out["skillswap_candidates"] += 1
                    if c.get("blocked"):
                        out["skillswap_blocked"] += 1
            # Accounting invariant: blocked ==
            # selected + avoided. Per-slot.
            for sk in ("slot_0", "slot_1"):
                s = turn.get(sk, {}) or {}
                if not s:
                    continue
                cb = s.get("narrow_ally_heal_candidate_blocked", False)
                sl = s.get("narrow_ally_heal_selected", False)
                av = s.get("narrow_ally_heal_avoided", False)
                if cb and not (sl or av):
                    out["accounting_fail"] += 1
                if cb and sl and av:
                    out["mutual_exclusion_fail"] += 1
    return out


def analyze(artifact_tag: str, expected_n_pairs: int = 100):
    csv_path = (
        f"logs/narrow_ally_heal_paired_{artifact_tag}.csv"
    )
    battle_path = (
        f"logs/narrow_ally_heal_paired_{artifact_tag}.jsonl"
    )
    analysis_json = (
        f"logs/narrow_ally_heal_paired_{artifact_tag}_analysis.json"
    )
    analysis_md = (
        f"logs/narrow_ally_heal_paired_{artifact_tag}_analysis.md"
    )

    battles = _read_jsonl(battle_path)
    if not battles:
        print(f"ERROR: no battles in {battle_path}")
        sys.exit(2)
    by_pair: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for b in battles:
        by_pair.setdefault(b["pair_id"], {})[b["side_swap"]] = b

    on_decisive_wins: List[bool] = []
    treatment_scores: List[int] = []
    on_invalid: List[int] = []
    on_categories = {
        "ON_both": 0, "OFF_both": 0, "split": 0, "invalid": 0,
    }
    d1_wins = d2_wins = 0
    d1_losses = d2_losses = 0
    on_audit_paths: List[str] = []
    off_audit_paths: List[str] = []
    for pid in sorted(by_pair.keys()):
        d1 = by_pair[pid].get("D1")
        d2 = by_pair[pid].get("D2")
        if not d1 or not d2:
            on_invalid.append(pid)
            on_categories["invalid"] += 1
            continue
        if d1["status"] != "ok" or d2["status"] != "ok":
            on_invalid.append(pid)
            on_categories["invalid"] += 1
            continue
        if d1["on_won"] is None or d2["on_won"] is None:
            on_invalid.append(pid)
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
        on_decisive_wins.append(d1w)
        # Audit paths
        on_audit_paths.append(d1["p1_audit_path"])
        off_audit_paths.append(d1["p2_audit_path"])
        off_audit_paths.append(d2["p1_audit_path"])
        on_audit_paths.append(d2["p2_audit_path"])

    n_pairs_valid = len(on_decisive_wins)
    total_pairs = len(by_pair)
    # Combined ON wins across both D1 and D2:
    # ON_both: 2 ON wins per pair
    # split: 1 ON win per pair
    # OFF_both: 0 ON wins per pair
    combined_on_wins = (
        on_categories["ON_both"] * 2 + on_categories["split"]
    )
    wilson_lo, wilson_hi = wilson_ci(combined_on_wins, 2 * n_pairs_valid)
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
        if treatment_scores else float("nan")
    )
    boot_point, boot_lo, boot_hi = paired_bootstrap_treatment(
        treatment_scores, n_boot=2000, seed=6381,
    )
    # ON / OFF safety metrics
    on_m = {}
    for ap in set(on_audit_paths):
        m = _collect_narrow_metrics(ap)
        for k, v in m.items():
            if isinstance(v, dict):
                on_m[k] = {
                    **on_m.get(k, {}),
                    **{kk: vv + on_m.get(k, {}).get(kk, 0)
                       for kk, vv in v.items()},
                }
            else:
                on_m[k] = on_m.get(k, 0) + v
    off_m = {}
    for ap in set(off_audit_paths):
        m = _collect_narrow_metrics(ap)
        for k, v in m.items():
            if isinstance(v, dict):
                off_m[k] = {
                    **off_m.get(k, {}),
                    **{kk: vv + off_m.get(k, {}).get(kk, 0)
                       for kk, vv in v.items()},
                }
            else:
                off_m[k] = off_m.get(k, 0) + v

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
                if n_pairs_valid else float("nan")
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
            "treatment_score": {
                "ON_both_value": +1,
                "split_value": 0,
                "OFF_both_value": -1,
            },
            "paired_bootstrap": {
                "point": boot_point,
                "ci_95_lo": boot_lo,
                "ci_95_hi": boot_hi,
                "n_boot": 2000,
                "seed": 6381,
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
    }
    with open(analysis_json, "w") as f:
        json.dump(report, f, indent=2)
    md_lines = [
        f"# Phase 6.3.8d Paired Analysis — {artifact_tag}",
        "",
        f"- Total pairs: {total_pairs}",
        f"- Valid pairs: {n_pairs_valid}",
        f"- Invalid pairs: {len(on_invalid)}",
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
        "## ON safety metrics (paired audits)",
        "",
    ]
    for k, v in on_m.items():
        if isinstance(v, dict):
            md_lines.append(f"- {k}: {dict(sorted(v.items()))}")
        else:
            md_lines.append(f"- {k}: {v}")
    md_lines += ["", "## OFF safety metrics (paired audits)", ""]
    for k, v in off_m.items():
        if isinstance(v, dict):
            md_lines.append(f"- {k}: {dict(sorted(v.items()))}")
        else:
            md_lines.append(f"- {k}: {v}")
    with open(analysis_md, "w") as f:
        f.write("\n".join(md_lines) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Phase 6.3.8d narrow paired analyzer"
    )
    parser.add_argument(
        "--artifact-tag", type=str, required=True,
        help="Artifact tag to analyze",
    )
    args = parser.parse_args()
    report = analyze(args.artifact_tag)
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
