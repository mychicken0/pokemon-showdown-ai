#!/usr/bin/env python3
"""
Phase 6.3.8d.1 — Pair Repair Merge Analyzer

Reads:
  - Original Phase 6.3.8d paired artifacts (the
    198-battle, 99-valid-pair historical evidence)
  - New Phase 6.3.8d.1 repair artifacts (the missing
    D2 of pair 98, re-run with the same exact team
    and policies)

Produces:
  - A uniquely named Phase 6.3.8d.1 paired analysis
    (CSV, JSONL, JSON, MD) with exactly 100 complete
    pairs and 200 valid battles.
  - Identity validation: pair_id, side_swap, team_str,
    p1_config_narrow, p2_config_narrow must match
    between original and repair where they overlap.
  - Hard-fails on any duplicate battle_tag.
  - Re-runs the same statistical methodology as
    Phase 6.3.8d (Wilson's CI, paired categories,
    exact sign test, paired bootstrap 95% CI) and
    reports the corrected statistics.

The original 6.3.8d artifacts are NEVER overwritten.
"""
import argparse
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple


def wilson_ci(s, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = s / n
    denom = 1 + (z ** 2) / n
    center = (p + (z ** 2) / (2 * n)) / denom
    margin = (
        z * math.sqrt(p * (1 - p) / n + (z ** 2) / (4 * n * n))
    ) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def exact_binomial_two_sided(k, n):
    if n == 0:
        return 1.0
    from math import comb
    if k > n - k:
        k = n - k
    p_le = sum(comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * p_le)


def exact_binomial_one_sided(k, n):
    if n == 0:
        return 1.0
    from math import comb
    return sum(comb(n, i) for i in range(k + 1)) / (2 ** n)


def paired_bootstrap_treatment(
    treatment_scores, n_boot=2000, seed=6381
):
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


def _read_jsonl(path):
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


def _load_original_battles(orig_tag):
    """Load the original 6.3.8d paired-battle results.

    The original run stored a JSONL of the per-arm
    results (each line is one paired side-swap). Each
    record already contains p1_config_narrow,
    p2_config_narrow, p1_name, p2_name, team_str.
    """
    path = f"logs/narrow_ally_heal_paired_{orig_tag}.jsonl"
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Original 6.3.8d battle artifact missing: {path}"
        )
    return _read_jsonl(path)


def _load_repair_battles(repair_tag):
    """Load the new 6.3.8d.1 repair paired-battle results."""
    path = f"logs/narrow_ally_heal_paired_{repair_tag}.jsonl"
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Repair artifact missing: {path}"
        )
    return _read_jsonl(path)


def _validate_identity(orig_rec, repair_rec):
    """Hard-fail if pair/team/policy identity differs.

    The repair record must be the same pair_id and
    side_swap as the original record, and must use
    the same team_str and config flags.
    """
    for key in (
        "pair_id", "side_swap", "p1_arm", "p2_arm",
        "on_arm", "off_arm", "on_player_is_p1",
        "team_str", "p1_config_narrow", "p2_config_narrow",
    ):
        if orig_rec.get(key) != repair_rec.get(key):
            raise ValueError(
                f"Identity mismatch on key '{key}': "
                f"orig={orig_rec.get(key)!r} "
                f"repair={repair_rec.get(key)!r}"
            )


def _merge(original_battles, repair_battles):
    """Merge the original and repair battle records.

    For every (pair_id, side_swap) present in the
    repair set, the original record is REPLACED by
    the repair record. All other original records
    are preserved as-is.
    """
    repair_keys = set()
    for r in repair_battles:
        repair_keys.add((r["pair_id"], r["side_swap"]))

    repaired_keys = []
    merged = []
    for orig in original_battles:
        key = (orig["pair_id"], orig["side_swap"])
        if key in repair_keys:
            repair_rec = next(
                r for r in repair_battles
                if r["pair_id"] == key[0] and r["side_swap"] == key[1]
            )
            _validate_identity(orig, repair_rec)
            merged.append(repair_rec)
            repaired_keys.append(key)
        else:
            merged.append(orig)
    return merged, sorted(repaired_keys)


def _collect_narrow_metrics(audit_path):
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


def _write_csv(path, merged):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "pair_id", "side_swap", "p1_arm", "p2_arm",
            "on_arm", "off_arm", "on_player_is_p1",
            "battle_tag", "finished", "status",
            "p1_wins", "p2_wins", "on_won",
            "error_detail", "p1_name", "p2_name",
            "team_str", "p1_config_narrow", "p2_config_narrow",
            "p1_audit_path", "p2_audit_path",
        ])
        for r in merged:
            w.writerow([
                r.get("pair_id"), r.get("side_swap"),
                r.get("p1_arm"), r.get("p2_arm"),
                r.get("on_arm"), r.get("off_arm"),
                r.get("on_player_is_p1"), r.get("battle_tag"),
                r.get("finished"), r.get("status"),
                r.get("p1_wins"), r.get("p2_wins"),
                r.get("on_won"), r.get("error_detail"),
                r.get("p1_name"), r.get("p2_name"),
                r.get("team_str"), r.get("p1_config_narrow"),
                r.get("p2_config_narrow"),
                r.get("p1_audit_path"), r.get("p2_audit_path"),
            ])


def _write_jsonl(path, merged):
    with open(path, "w") as f:
        for r in merged:
            f.write(json.dumps(r) + "\n")


def analyze(orig_tag, repair_tag, expected_n_pairs=100):
    original_battles = _load_original_battles(orig_tag)
    repair_battles = _load_repair_battles(repair_tag)

    if not original_battles:
        raise RuntimeError("No original 6.3.8d battles found")
    if not repair_battles:
        raise RuntimeError("No repair 6.3.8d.1 battles found")

    merged, repaired_keys = _merge(
        original_battles, repair_battles
    )

    # Battle-tag uniqueness (hard-fail).
    seen_tags = set()
    dup_tags = []
    for b in merged:
        bt = b.get("battle_tag", "") or ""
        if not bt:
            continue
        if bt in seen_tags:
            dup_tags.append(bt)
        seen_tags.add(bt)
    if dup_tags:
        raise RuntimeError(
            f"Duplicate battle_tags in merged set: {dup_tags}"
        )

    # Per-side audit file uniqueness (hard-fail).
    seen_audit = set()
    dup_audit = []
    for b in merged:
        for k in ("p1_audit_path", "p2_audit_path"):
            p = b.get(k) or ""
            if not p:
                continue
            if p in seen_audit:
                dup_audit.append(p)
            seen_audit.add(p)
    if dup_audit:
        raise RuntimeError(
            f"Duplicate per-side audit paths in merged set: {dup_audit}"
        )

    # Validate battle count and pair count.
    n_battles = len(merged)
    by_pair = defaultdict(dict)
    for b in merged:
        by_pair[b["pair_id"]][b["side_swap"]] = b
    n_pairs_total = len(by_pair)
    if n_pairs_total != expected_n_pairs:
        raise RuntimeError(
            f"Expected {expected_n_pairs} pairs, got {n_pairs_total}"
        )

    # Validate each pair is valid (no stall/error/no_battle).
    invalid_pairs = []
    for pid, sides in sorted(by_pair.items()):
        for ss in ("D1", "D2"):
            rec = sides.get(ss)
            if (
                not rec
                or rec.get("status") != "ok"
                or rec.get("on_won") is None
                or int(rec.get("finished", 0)) < 1
            ):
                invalid_pairs.append((pid, ss, rec and rec.get("status")))
    if invalid_pairs:
        raise RuntimeError(
            f"Invalid pairs after repair: {invalid_pairs}"
        )

    # Standard paired analysis.
    on_categories = {
        "ON_both": 0, "OFF_both": 0, "split": 0, "invalid": 0,
    }
    d1_wins = d2_wins = 0
    d1_losses = d2_losses = 0
    treatment_scores = []
    on_audit_paths = []
    off_audit_paths = []
    for pid in sorted(by_pair.keys()):
        d1 = by_pair[pid]["D1"]
        d2 = by_pair[pid]["D2"]
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
    d1_rate = d1_wins / n_pairs_valid
    d2_rate = d2_wins / n_pairs_valid
    side_collapse = abs(d1_rate - d2_rate)
    mean_treatment = sum(treatment_scores) / len(treatment_scores)
    boot_point, boot_lo, boot_hi = paired_bootstrap_treatment(
        treatment_scores, n_boot=2000, seed=6381,
    )

    on_m = {}
    for ap in set(on_audit_paths):
        m = _collect_narrow_metrics(ap)
        for k, v in m.items():
            on_m[k] = on_m.get(k, 0) + v
    off_m = {}
    for ap in set(off_audit_paths):
        m = _collect_narrow_metrics(ap)
        for k, v in m.items():
            off_m[k] = off_m.get(k, 0) + v

    csv_path = (
        f"logs/narrow_ally_heal_paired_phase638d1_paired100.csv"
    )
    jsonl_path = (
        f"logs/narrow_ally_heal_paired_phase638d1_paired100.jsonl"
    )
    analysis_json = (
        f"logs/narrow_ally_heal_paired_phase638d1_paired100_analysis.json"
    )
    analysis_md = (
        f"logs/narrow_ally_heal_paired_phase638d1_paired100_analysis.md"
    )

    _write_csv(csv_path, merged)
    _write_jsonl(jsonl_path, merged)

    report = {
        "audit_tag": "phase638d1_paired100",
        "original_tag": orig_tag,
        "repair_tag": repair_tag,
        "repaired_pairs": [
            {"pair_id": k[0], "side_swap": k[1]}
            for k in repaired_keys
        ],
        "n_pairs_total": n_pairs_total,
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
            "on_win_rate": combined_on_wins / (2 * n_pairs_valid),
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
        "identity_validation": {
            "battle_tags_unique": len(dup_tags) == 0,
            "audit_paths_unique": len(dup_audit) == 0,
            "all_pairs_ok": len(invalid_pairs) == 0,
        },
    }
    with open(analysis_json, "w") as f:
        json.dump(report, f, indent=2)

    md = []
    md.append("# Phase 6.3.8d.1 Paired Analysis — paired100 (repaired)")
    md.append("")
    md.append(
        "Repaired paired qualification: the original "
        "Phase 6.3.8d produced 99 valid pairs and 198 "
        "battles. The pair 98 D2 side-swap stalled. This "
        "Phase 6.3.8d.1 artifact reruns ONLY the missing "
        "D2 of pair 98 with the exact same team and "
        "policies, then merges into a complete 100-pair / "
        "200-battle dataset."
    )
    md.append("")
    md.append(f"- Original 6.3.8d tag: `{orig_tag}`")
    md.append(f"- Repair 6.3.8d.1 tag: `{repair_tag}`")
    md.append(
        f"- Repaired side-swaps: "
        f"{[(k[0], k[1]) for k in repaired_keys]}"
    )
    md.append(f"- Total pairs: {n_pairs_total}")
    md.append(f"- Valid pairs: {n_pairs_valid}")
    md.append(f"- Total battles: {2 * n_pairs_valid}")
    md.append(
        f"- Battle tags unique: "
        f"{report['identity_validation']['battle_tags_unique']}"
    )
    md.append(
        f"- Audit paths unique: "
        f"{report['identity_validation']['audit_paths_unique']}"
    )
    md.append(
        f"- All pairs ok: "
        f"{report['identity_validation']['all_pairs_ok']}"
    )
    md.append("")
    md.append("## Aggregated ON win rate (200 battles / 100 pairs)")
    md.append("")
    md.append(
        f"- Combined ON wins: {combined_on_wins}/"
        f"{2 * n_pairs_valid} = "
        f"{combined_on_wins / (2 * n_pairs_valid):.4f}"
    )
    md.append(
        f"- Wilson 95% CI: [{wilson_lo:.4f}, {wilson_hi:.4f}]"
    )
    md.append("")
    md.append("## Side-position diagnostic (NOT treatment effect)")
    md.append("")
    md.append(
        f"- D1 (ON as p1): {d1_wins}/{n_pairs_valid} = {d1_rate:.4f}"
    )
    md.append(
        f"- D2 (ON as p2): {d2_wins}/{n_pairs_valid} = {d2_rate:.4f}"
    )
    md.append(
        f"- |D1 - D2|: {side_collapse:.4f} "
        f"({'WARNING' if side_collapse > 0.10 else 'OK'})"
    )
    md.append("")
    md.append("## Paired categories")
    md.append("")
    md.append(f"- ON both:  {on_categories['ON_both']}")
    md.append(f"- OFF both: {on_categories['OFF_both']}")
    md.append(f"- Split:    {on_categories['split']}")
    md.append(f"- Invalid:  {on_categories['invalid']}")
    md.append("")
    md.append("## Paired treatment effect (this is the adoption gate)")
    md.append("")
    md.append("Treatment score per pair:")
    md.append("- +1 if ON won both D1 and D2 (ON_both)")
    md.append("-  0 if split")
    md.append("- -1 if OFF won both D1 and D2 (OFF_both)")
    md.append("")
    md.append(f"- Mean treatment effect: {mean_treatment:.4f}")
    md.append(
        f"- Paired bootstrap 95% CI: "
        f"[{boot_lo:.4f}, {boot_hi:.4f}]"
    )
    md.append(
        f"- **Adoption lower-bound gate reads this CI: "
        f"boot_lo = {boot_lo:.4f}**"
    )
    md.append("")
    md.append("## Sign tests (decisive pairs only)")
    md.append("")
    md.append(
        f"- Decisive pairs n = {decisive} "
        f"(={k_on_both} + {k_off_both})"
    )
    md.append(f"- Two-sided exact p: {p_two_sided:.4f}")
    md.append(
        f"- One-sided (ON regression) p: {p_one_sided_reg:.4f}"
    )
    md.append("")
    md.append("## ON safety metrics (paired audits)")
    md.append("")
    for k, v in on_m.items():
        md.append(f"- {k}: {v}")
    md.append("")
    md.append("## OFF safety metrics (paired audits)")
    md.append("")
    for k, v in off_m.items():
        md.append(f"- {k}: {v}")

    with open(analysis_md, "w") as f:
        f.write("\n".join(md) + "\n")

    return report


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Phase 6.3.8d.1 merge analyzer"
        )
    )
    parser.add_argument(
        "--orig-tag", type=str, default="phase638d_paired100",
        help="Original 6.3.8d artifact tag (default: phase638d_paired100).",
    )
    parser.add_argument(
        "--repair-tag", type=str, required=True,
        help="6.3.8d.1 repair artifact tag (required).",
    )
    args = parser.parse_args()
    try:
        report = analyze(args.orig_tag, args.repair_tag)
    except Exception as e:
        print(f"FATAL: {type(e).__name__}: {e}")
        sys.exit(1)
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
