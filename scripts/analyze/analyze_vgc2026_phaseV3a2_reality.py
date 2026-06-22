#!/usr/bin/env python3
"""Phase V3a.2 — Reality-check analyzer.

Reads the CSV/JSONL artifacts from
``bot_vgc2026_phaseV3a2_reality.py`` and reports
the paired qualification metrics.

Reuses the same metrics style as
``analyze_vgc2026_phaseV2f_qualification.py``:
Wilson CI, paired categories, sign test, side
collapse. Adds preview-validation and plan-change
metrics specific to the V3a.2 reality check.

Decision: GO if all predeclared gates pass;
BLOCKED otherwise. The decision is printed, not
silently applied.
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    out = []
    if not os.path.isfile(path):
        return out
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


def _wilson_ci(s: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = s / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _exact_binomial_two_sided(k: int, n: int) -> float:
    """Two-sided exact binomial p-value using a
    simple enumeration. Adequate for small n.
    """
    if n == 0:
        return 1.0
    from math import comb
    p0 = k / n if n else 0
    # Probability of exactly k successes under p0.
    base = comb(n, k) * (p0 ** k) * ((1 - p0) ** (n - k))
    # Sum probabilities <= base.
    total = 0.0
    for i in range(n + 1):
        pi = comb(n, i) * (p0 ** i) * ((1 - p0) ** (n - i))
        if pi <= base + 1e-12:
            total += pi
    return min(1.0, total)


def _exact_binomial_one_sided(k: int, n: int) -> float:
    """One-sided p-value for P(X >= k) under H0:
    p=0.5 (learned not better than V3).
    """
    if n == 0:
        return 1.0
    from math import comb
    p0 = 0.5
    total = 0.0
    for i in range(k, n + 1):
        total += comb(n, i) * (p0 ** i) * ((1 - p0) ** (n - i))
    return min(1.0, total)


def _paired_bootstrap_ci(
    treatment_scores, n_boot=2000, seed=42
):
    """Paired bootstrap CI for mean treatment score.

    treatment_scores is a list of +1 / 0 / -1 per
    pair (on_both=+1, split=0, v3_both=-1). Returns
    (point, ci_lo, ci_hi).
    """
    import random as _r
    if not treatment_scores:
        return (0.0, 0.0, 0.0)
    rng = _r.Random(seed)
    n = len(treatment_scores)
    means = []
    for _ in range(n_boot):
        sample = [treatment_scores[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[int(0.975 * n_boot) - 1]
    return (sum(treatment_scores) / n, lo, hi)


def _row_perspective_result(
    row: Dict[str, Any],
    learned_policy: str,
    baseline_policy: str,
) -> Tuple[Optional[bool], Optional[bool], Optional[str]]:
    """Compute learned_won and baseline_won from a single
    battle row using policy-perspective semantics.

    ponytail: returns (learned_won, baseline_won,
    invalid_reason). invalid_reason is None if
    the row is well-formed; otherwise a short
    string explaining why. The function does NOT
    infer wins from side position (D1 vs D2); it
    looks at ``our_policy`` (the row's bot) and
    ``opponent_policy`` (the opponent) directly.
    This matches the V3a.2/V3c.2 runner's row
    schema (no separate player_policy field).

    Semantics:
    - learned_won = True iff the learned policy
      was on the winning side.
    - baseline_won = True iff the baseline policy
      was on the winning side.
    - Invalid if both or neither side uses one of
      the two named policies, or if the win field
      is missing/non-boolean.
    """
    if not isinstance(row, dict):
        return None, None, "row_not_dict"
    status = row.get("status")
    if status != "ok":
        return None, None, f"status_{status}"
    raw_win = row.get("our_win")
    if not isinstance(raw_win, bool):
        return None, None, "missing_our_win"
    # V3a.2/V3c.2 runner uses "our_policy" and
    # "opponent_policy" (no separate player_policy).
    player_policy = row.get("our_policy")
    opponent_policy = row.get("opponent_policy")
    if not isinstance(player_policy, str) or not isinstance(
        opponent_policy, str
    ):
        return None, None, "missing_policy"
    player_is_learned = player_policy == learned_policy
    opponent_is_learned = (
        opponent_policy == learned_policy
    )
    player_is_baseline = player_policy == baseline_policy
    opponent_is_baseline = (
        opponent_policy == baseline_policy
    )
    if player_is_learned and opponent_is_learned:
        return None, None, "both_sides_learned"
    if player_is_baseline and opponent_is_baseline:
        return None, None, "both_sides_baseline"
    if (
        not player_is_learned
        and not opponent_is_learned
    ):
        return None, None, "neither_side_learned"
    if (
        not player_is_baseline
        and not opponent_is_baseline
    ):
        return None, None, "neither_side_baseline"
    player_win = raw_win
    opponent_win = not raw_win
    learned_won: Optional[bool]
    baseline_won: Optional[bool]
    if player_is_learned:
        learned_won = player_win
        baseline_won = opponent_win
    else:
        learned_won = opponent_win
        baseline_won = player_win
    return learned_won, baseline_won, None


def analyze(
    tag: str,
    merge_tags=None,
    learned_policy: str = "learned_preview_v3a1",
    baseline_policy: str = "matchup_top4_v3",
) -> Dict[str, Any]:
    """Analyze paired reality-check artifacts.

    Reads logs/vgc2026_{tag}.jsonl and any
    additional tags in merge_tags. Duplicate
    pair_id+side rows are de-duped.

    Counting is policy-perspective correct: for
    each row, ``learned_won`` is computed from
    which side used the learned policy, not
    from D1/D2 labels. ponytail: side diagnostic
    (learned_as_p1 win rate, learned_as_p2 win
    rate) is reported separately from treatment
    effect.
    """
    jsonl_paths = [f"logs/vgc2026_{tag}.jsonl"]
    if merge_tags:
        for m in merge_tags:
            jsonl_paths.append(f"logs/vgc2026_{m}.jsonl")
    rows = []
    seen = set()
    for jp in jsonl_paths:
        for r in _read_jsonl(jp):
            key = (r.get("pair_id"), r.get("side"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(r)
    if not rows:
        print(f"ERROR: no rows in any of {jsonl_paths}")
        sys.exit(2)
    by_pair: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for r in rows:
        by_pair.setdefault(r["pair_id"], {})[r["side"]] = r

    # Per-row perspective result. ponytail:
    # compute once and reuse.
    row_perspective: Dict[
        Tuple[int, str], Tuple[Optional[bool], Optional[bool]]
    ] = {}
    invalid_reasons: Counter = Counter()
    for r in rows:
        lw, bw, reason = _row_perspective_result(
            r, learned_policy, baseline_policy
        )
        key = (r.get("pair_id"), r.get("side"))
        row_perspective[key] = (lw, bw)
        if reason is not None:
            invalid_reasons[reason] += 1

    # Integrity.
    total_pairs = len(by_pair)
    n_complete = 0
    n_invalid = 0
    n_timeout = 0
    n_error = 0
    n_no_battle = 0
    n_preview_invalid = 0
    n_perspective_invalid = sum(invalid_reasons.values())
    d1_turns: List[int] = []
    d2_turns: List[int] = []
    plan_changed: int = 0
    plan_total: int = 0
    treatment_scores: List[int] = []  # +1 learned_both, 0 split, -1 baseline_both
    v3_plan_dist: Counter = Counter()
    learned_plan_dist: Counter = Counter()
    preview_validation: int = 0
    preview_total: int = 0
    # Policy-perspective counts (across all valid rows).
    n_learned_wins: int = 0
    n_baseline_wins: int = 0
    n_perspective_valid: int = 0
    # Side-position diagnostic (where learned happened
    # to be p1 or p2 in the run). ponytail: separate
    # from treatment effect.
    n_learned_as_p1: int = 0
    n_learned_wins_as_p1: int = 0
    n_learned_as_p2: int = 0
    n_learned_wins_as_p2: int = 0
    for pid in sorted(by_pair.keys()):
        d1 = by_pair[pid].get("D1") or by_pair[pid].get("p1")
        d2 = by_pair[pid].get("D2") or by_pair[pid].get("p2")
        if not d1 or not d2:
            n_invalid += 1
            continue
        if d1["status"] != "ok" or d2["status"] != "ok":
            n_invalid += 1
            if d1["status"] == "timeout" or d2["status"] == "timeout":
                n_timeout += 1
            if d1["status"] == "error" or d2["status"] == "error":
                n_error += 1
            if d1["status"] == "no_battle" or d2["status"] == "no_battle":
                n_no_battle += 1
            continue
        # Preview validation: are 4 unique species
        # from our team in chosen_4?
        for r in (d1, d2):
            preview_total += 1
            chosen = r["our_chosen_4"]
            if len(set(chosen)) == 4 and len(chosen) == 4:
                preview_validation += 1
            else:
                n_preview_invalid += 1
        d1_turns.append(d1.get("turns", 0))
        d2_turns.append(d2.get("turns", 0))
        # Perspective-correct per-row counts.
        d1_lw, d1_bw = row_perspective[(pid, "p1")]
        d2_lw, d2_bw = row_perspective[(pid, "p2")]
        for lw, bw in ((d1_lw, d1_bw), (d2_lw, d2_bw)):
            if lw is None or bw is None:
                continue
            n_perspective_valid += 1
            if lw:
                n_learned_wins += 1
            if bw:
                n_baseline_wins += 1
        # Side-position diagnostic: in each row,
        # which side (p1 or p2) was the learned
        # policy on? ponytail: ``side`` is the row's
        # ``our`` side (p1 or p2). We check whether
        # learned appears in either the player slot
        # (our) or the opponent slot (the other side).
        # In a side-swap runner, learned is on p1 in
        # one row and on p2 in the other, so both
        # counters should be similar in magnitude.
        d1_side = d1.get("side", "")
        d1_our = d1.get("our_policy", "")
        d1_opp = d1.get("opponent_policy", "")
        if d1_our == learned_policy and d1_side == "p1":
            n_learned_as_p1 += 1
            if d1_lw:
                n_learned_wins_as_p1 += 1
        elif d1_opp == learned_policy and d1_side == "p2":
            # learned is opponent in this row, on
            # the p2 side (opposite of d1's our side).
            n_learned_as_p2 += 1
            if d1_lw:
                n_learned_wins_as_p2 += 1
        d2_side = d2.get("side", "")
        d2_our = d2.get("our_policy", "")
        d2_opp = d2.get("opponent_policy", "")
        if d2_our == learned_policy and d2_side == "p1":
            n_learned_as_p1 += 1
            if d2_lw:
                n_learned_wins_as_p1 += 1
        elif d2_opp == learned_policy and d2_side == "p2":
            n_learned_as_p2 += 1
            if d2_lw:
                n_learned_wins_as_p2 += 1
        # Paired categories: learned_both if learned
        # won both d1 and d2; baseline_both if lost
        # both; split otherwise; invalid if either is
        # invalid.
        if d1_lw is None or d2_lw is None:
            # Invalid pair — don't count it.
            n_invalid += 1
            continue
        if d1_lw and d2_lw:
            learned_both = True
            baseline_both = False
        elif (not d1_lw) and (not d2_lw):
            learned_both = False
            baseline_both = True
        else:
            learned_both = False
            baseline_both = False
        if learned_both:
            on_both_count = 1
            v3_both_count = 0
        elif baseline_both:
            on_both_count = 0
            v3_both_count = 1
        else:
            on_both_count = 0
            v3_both_count = 0
        # Use module-level counters via closure. We
        # need to declare them as nonlocal.
        # (ponytail: the original analyzer accumulated
        # these via outer-scope mutation; replicate.)
        if learned_both:
            treatment_scores.append(+1)
        elif baseline_both:
            treatment_scores.append(-1)
        else:
            treatment_scores.append(0)
        # Plan change rate: compare learned's plan in
        # d1 (or d2 where learned is our) vs baseline's
        # plan in the other row. ponytail: find the
        # row where learned is our and the row where
        # baseline is our, then compare chosen_4.
        # (the V3a.2/V3c.2 runner's row uses our_policy.)
        d1_our = d1.get("our_policy", "")
        d2_our = d2.get("our_policy", "")
        if d1_our == learned_policy:
            learned_row, baseline_row = d1, d2
        elif d2_our == learned_policy:
            learned_row, baseline_row = d2, d1
        else:
            learned_row = baseline_row = None
        if learned_row is not None:
            plan_total += 1
            learned_set = frozenset(
                s.lower() for s in learned_row["our_chosen_4"]
            )
            baseline_set = frozenset(
                s.lower() for s in baseline_row["our_chosen_4"]
            )
            learned_plan_dist[tuple(sorted(learned_set))] += 1
            v3_plan_dist[tuple(sorted(baseline_set))] += 1
            if learned_set != baseline_set:
                plan_changed += 1
        n_complete += 1
    # Re-derive on_both / v3_both / split from
    # treatment_scores (perspective-correct).
    on_both = sum(1 for s in treatment_scores if s > 0)
    v3_both = sum(1 for s in treatment_scores if s < 0)
    split = sum(1 for s in treatment_scores if s == 0)
    n_pairs_valid = n_complete
    total_battles = 2 * n_pairs_valid
    learned_win_rate = (
        n_learned_wins / n_perspective_valid
        if n_perspective_valid else 0.0
    )
    baseline_win_rate = (
        n_baseline_wins / n_perspective_valid
        if n_perspective_valid else 0.0
    )
    wilson_lo, wilson_hi = _wilson_ci(
        n_learned_wins, n_perspective_valid
    )
    decisive = on_both + v3_both
    p_two_sided = _exact_binomial_two_sided(on_both, decisive)
    learned_as_p1_rate = (
        n_learned_wins_as_p1 / n_learned_as_p1
        if n_learned_as_p1 else 0.0
    )
    learned_as_p2_rate = (
        n_learned_wins_as_p2 / n_learned_as_p2
        if n_learned_as_p2 else 0.0
    )
    side_collapse = abs(learned_as_p1_rate - learned_as_p2_rate)
    avg_turns = (
        sum(d1_turns + d2_turns) / (2 * n_pairs_valid)
        if n_pairs_valid else 0.0
    )
    plan_changed_rate = (
        plan_changed / plan_total if plan_total else 0.0
    )
    report = {
        "audit_tag": tag,
        "learned_policy": learned_policy,
        "baseline_policy": baseline_policy,
        "n_pairs_total": total_pairs,
        "n_pairs_valid": n_pairs_valid,
        "n_pairs_invalid": n_invalid,
        "n_battles": 2 * total_pairs,
        "n_valid_battles": 2 * n_pairs_valid,
        "preview_validation_count": preview_validation,
        "preview_validation_total": preview_total,
        "n_preview_invalid": n_preview_invalid,
        "n_perspective_valid": n_perspective_valid,
        "n_perspective_invalid": n_perspective_invalid,
        "invalid_reasons": dict(invalid_reasons),
        "learned_wins": n_learned_wins,
        "baseline_wins": n_baseline_wins,
        "learned_win_rate": learned_win_rate,
        "baseline_win_rate": baseline_win_rate,
        "wilson_95_lo": wilson_lo,
        "wilson_95_hi": wilson_hi,
        # Side diagnostic: clearly labeled.
        "learned_as_p1_n": n_learned_as_p1,
        "learned_as_p2_n": n_learned_as_p2,
        "learned_wins_as_p1": n_learned_wins_as_p1,
        "learned_wins_as_p2": n_learned_wins_as_p2,
        "learned_as_p1_win_rate": learned_as_p1_rate,
        "learned_as_p2_win_rate": learned_as_p2_rate,
        "side_collapse": side_collapse,
        # Paired categories: perspective-correct.
        "on_both": on_both,
        "v3_both": v3_both,
        "split": split,
        "sign_test_two_sided_p": p_two_sided,
        "sign_test_one_sided_p": (
            _exact_binomial_one_sided(on_both, on_both + v3_both)
        ),
        # Treatment effect: clearly labeled.
        "treatment_effect_mean": (
            sum(treatment_scores) / len(treatment_scores)
            if treatment_scores else 0.0
        ),
        "paired_bootstrap": (
            _paired_bootstrap_ci(treatment_scores)
        ),
        "avg_turns": avg_turns,
        "plan_changed_count": plan_changed,
        "plan_changed_rate_vs_v3": plan_changed_rate,
        "n_timeout": n_timeout,
        "n_error": n_error,
        "n_no_battle": n_no_battle,
        "n_unique_plans_learned": len(learned_plan_dist),
        "n_unique_plans_v3": len(v3_plan_dist),
    }
    return report




def _split_pair_categories(rows):
    """Group pairs into learned-p1-only, learned-p2-only,
    learned-both, learned-neither. Returns (dict, by_pair)."""
    from collections import defaultdict
    by_pair = defaultdict(dict)
    for r in rows:
        by_pair[r["pair_id"]][r["side"]] = r
    out = {
        "learned_p1_only": [],
        "learned_p2_only": [],
        "learned_both": [],
        "learned_neither": [],
    }
    for pid, arms in by_pair.items():
        d1 = arms.get("p1")
        d2 = arms.get("p2")
        if not d1 or not d2:
            continue
        d1w = bool(d1.get("our_win"))
        d2w = bool(d2.get("our_win"))
        if d1w and d2w:
            out["learned_both"].append(pid)
        elif d1w and not d2w:
            out["learned_p1_only"].append(pid)
        elif (not d1w) and d2w:
            out["learned_p2_only"].append(pid)
        else:
            out["learned_neither"].append(pid)
    return out, by_pair


def _validate_d1_d2_determinism(rows):
    """Confirm D1 our_chosen_4 == D2 opp_chosen_4 (learned
    plan) and D1 opp_chosen_4 == D2 our_chosen_4 (V3 plan).
    Returns (learned_mismatches, v3_mismatches)."""
    from collections import defaultdict
    by_pair = defaultdict(dict)
    for r in rows:
        by_pair[r["pair_id"]][r["side"]] = r
    learned_mismatches = []
    v3_mismatches = []
    for pid, arms in by_pair.items():
        d1 = arms.get("p1")
        d2 = arms.get("p2")
        if not d1 or not d2:
            continue
        if sorted(d1.get("our_chosen_4", [])) != sorted(
            d2.get("opp_chosen_4", [])
        ):
            learned_mismatches.append(pid)
        if sorted(d1.get("opp_chosen_4", [])) != sorted(
            d2.get("our_chosen_4", [])
        ):
            v3_mismatches.append(pid)
    return learned_mismatches, v3_mismatches


def audit_side_asymmetry(rows):
    """V3a.4 side-asymmetry audit. Returns a dict with
    categories, determinism check, split-pair overlap,
    and top contributors."""
    cats, by_pair = _split_pair_categories(rows)
    learned_mism, v3_mism = _validate_d1_d2_determinism(rows)
    chosen4_overlap = []
    lead_overlap = []
    turns_p1 = []
    turns_p2 = []
    for pid, arms in by_pair.items():
        d1 = arms.get("p1")
        d2 = arms.get("p2")
        if not d1 or not d2:
            continue
        d1w = bool(d1.get("our_win"))
        d2w = bool(d2.get("our_win"))
        if d1w == d2w:
            continue
        learned = frozenset(s.lower() for s in d1["our_chosen_4"])
        v3 = frozenset(s.lower() for s in d1["opp_chosen_4"])
        learned_lead = frozenset(s.lower() for s in d1["our_lead_2"])
        v3_lead = frozenset(s.lower() for s in d1["opp_lead_2"])
        chosen4_overlap.append(len(learned & v3))
        lead_overlap.append(len(learned_lead & v3_lead))
        turns_p1.append(d1.get("turns", 0))
        turns_p2.append(d2.get("turns", 0))
    return {
        "categories": {k: len(v) for k, v in cats.items()},
        "determinism": {
            "learned_mismatches": learned_mism,
            "v3_mismatches": v3_mism,
        },
        "split_pair_overlap": {
            "n_split_pairs": len(chosen4_overlap),
            "avg_chosen4_overlap": (
                sum(chosen4_overlap) / len(chosen4_overlap)
                if chosen4_overlap else 0.0
            ),
            "avg_lead_overlap": (
                sum(lead_overlap) / len(lead_overlap)
                if lead_overlap else 0.0
            ),
            "avg_turns_d1": (
                sum(turns_p1) / len(turns_p1) if turns_p1 else 0.0
            ),
            "avg_turns_d2": (
                sum(turns_p2) / len(turns_p2) if turns_p2 else 0.0
            ),
        },
        "top_p2_only": sorted(cats["learned_p2_only"])[:10],
        "top_p1_only": sorted(cats["learned_p1_only"])[:10],
    }


def _format_audit_table(by_pair, label, pids):
    """Markdown table of top contributors."""
    lines = [
        f"### Top {len(pids)} pair IDs: {label}",
        "",
        "| pair_id | battle_tag_d1 | chosen_4_d1 | "
        "battle_tag_d2 | chosen_4_d2 |",
        "|---|---|---|---|---|",
    ]
    for pid in pids:
        d1 = by_pair.get(pid, {}).get("p1")
        d2 = by_pair.get(pid, {}).get("p2")
        bt1 = d1.get("battle_tag", "") if d1 else ""
        bt2 = d2.get("battle_tag", "") if d2 else ""
        c1 = "|".join(d1.get("our_chosen_4", [])) if d1 else ""
        c2 = "|".join(d2.get("our_chosen_4", [])) if d2 else ""
        lines.append(
            f"| {pid} | {bt1} | {c1} | {bt2} | {c2} |"
        )
    lines.append("")
    return "\n".join(lines)


def format_audit_report(audit, by_pair):
    from collections import defaultdict
    bp = defaultdict(dict)
    for pid, arms in by_pair.items():
        d1 = arms.get("p1")
        d2 = arms.get("p2")
        if d1:
            bp[pid]["p1"] = d1
        if d2:
            bp[pid]["p2"] = d2
    lines = [
        "## V3a.4 side-asymmetry audit",
        "",
        "### Split pair categories",
        "",
    ]
    for k, v in audit["categories"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    det = audit["determinism"]
    lines.append("### D1/D2 determinism")
    lines.append("")
    lines.append(
        f"- learned plan mismatches: {len(det['learned_mismatches'])}"
    )
    lines.append(
        f"- V3 plan mismatches: {len(det['v3_mismatches'])}"
    )
    lines.append("")
    ov = audit["split_pair_overlap"]
    lines.append("### Split-pair overlap (learned vs V3)")
    lines.append("")
    lines.append(f"- n_split_pairs: {ov['n_split_pairs']}")
    lines.append(
        f"- avg chosen_4 overlap: {ov['avg_chosen4_overlap']:.2f} / 4"
    )
    lines.append(
        f"- avg lead overlap: {ov['avg_lead_overlap']:.2f} / 2"
    )
    lines.append(f"- avg turns D1: {ov['avg_turns_d1']:.1f}")
    lines.append(f"- avg turns D2: {ov['avg_turns_d2']:.1f}")
    lines.append("")
    lines.append(
        _format_audit_table(
            bp, "learned_p2_only (D2 wins, D1 loses)",
            audit["top_p2_only"],
        )
    )
    lines.append(
        _format_audit_table(
            bp, "learned_p1_only (D1 wins, D2 loses)",
            audit["top_p1_only"],
        )
    )
    return "\n".join(lines) + "\n"


def run_audit_cli(tag, merge_tags):
    """CLI entry: load rows, run audit, print results."""
    jsonl_paths = [f"logs/vgc2026_{tag}.jsonl"]
    if merge_tags:
        for m in merge_tags:
            jsonl_paths.append(f"logs/vgc2026_{m}.jsonl")
    rows = []
    seen = set()
    for jp in jsonl_paths:
        if not os.path.isfile(jp):
            continue
        with open(jp) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = (r.get("pair_id"), r.get("side"))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(r)
    if not rows:
        print(f"ERROR: no rows in {jsonl_paths}")
        sys.exit(2)
    audit = audit_side_asymmetry(rows)
    _, by_pair = _split_pair_categories(rows)
    text = format_audit_report(audit, by_pair)
    print(text)
    out_md = f"logs/vgc2026_{tag}_v3a4_audit.md"
    with open(out_md, "w") as f:
        f.write(text)
    out_json = f"logs/vgc2026_{tag}_v3a4_audit.json"
    with open(out_json, "w") as f:
        json.dump(audit, f, indent=2)
    print(f"Wrote {out_md}")
    print(f"Wrote {out_json}")
def decide_go_no_go(report: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the predeclared V3a.2 go/no-go gates.

    GO iff all of:
      - 40/40 battles valid (20 pairs)
      - 20/20 pairs complete
      - zero timeout/error/no_battle
      - preview validation == total
      - side collapse <= 0.15
      - learned_win_rate >= 0.50
      - on_both >= v3_both
    """
    total_battles = report["n_valid_battles"]
    n_pairs_valid = report["n_pairs_valid"]
    reasons_pass = []
    reasons_fail = []
    if total_battles == 40 and n_pairs_valid == 20:
        reasons_pass.append("40/40 battles valid")
    else:
        reasons_fail.append(
            f"only {total_battles}/40 battles valid, "
            f"{n_pairs_valid}/20 pairs complete"
        )
    if report["n_timeout"] == 0 and report["n_error"] == 0 and report["n_no_battle"] == 0:
        reasons_pass.append("zero timeout/error/no_battle")
    else:
        reasons_fail.append(
            f"timeouts={report['n_timeout']}, "
            f"errors={report['n_error']}, "
            f"no_battles={report['n_no_battle']}"
        )
    if (
        report["preview_validation_count"]
        == report["preview_validation_total"]
    ):
        reasons_pass.append("preview validation 100%")
    else:
        reasons_fail.append(
            f"preview validation "
            f"{report['preview_validation_count']}/"
            f"{report['preview_validation_total']}"
        )
    # V3a.3: stricter side-collapse gate (10pp).
    if report["side_collapse"] <= 0.10:
        reasons_pass.append(
            f"side collapse {report['side_collapse']:.3f} <= 0.10"
        )
    else:
        reasons_fail.append(
            f"side collapse {report['side_collapse']:.3f} > 0.10"
        )
    # V3a.3: treatment effect >= 0.
    if report["treatment_effect_mean"] >= 0.0:
        reasons_pass.append(
            f"treatment_effect {report['treatment_effect_mean']:.4f} >= 0"
        )
    else:
        reasons_fail.append(
            f"treatment_effect {report['treatment_effect_mean']:.4f} < 0"
        )
    if report["learned_win_rate"] >= 0.50:
        reasons_pass.append(
            f"learned_win_rate {report['learned_win_rate']:.3f} >= 0.50"
        )
    else:
        reasons_fail.append(
            f"learned_win_rate {report['learned_win_rate']:.3f} < 0.50"
        )
    if report["on_both"] >= report["v3_both"]:
        reasons_pass.append(
            f"on_both {report['on_both']} >= v3_both {report['v3_both']}"
        )
    else:
        reasons_fail.append(
            f"on_both {report['on_both']} < v3_both {report['v3_both']}"
        )
    is_go = len(reasons_fail) == 0
    return {
        "decision": "GO" if is_go else "BLOCKED",
        "reasons_pass": reasons_pass,
        "reasons_fail": reasons_fail,
    }


def format_report(report: Dict[str, Any], decision: Dict[str, Any]) -> str:
    lines = [
        f"# Phase V3a.2/V3a.3 Reality Check — {report['audit_tag']}",
        "",
        f"- learned_policy: {report.get('learned_policy', '?')}",
        f"- baseline_policy: {report.get('baseline_policy', '?')}",
        f"- Total pairs: {report['n_pairs_total']}",
        f"- Valid pairs: {report['n_pairs_valid']}",
        f"- Invalid pairs: {report['n_pairs_invalid']}",
        f"- Valid battles: {report['n_valid_battles']}",
        f"- Preview validation: {report['preview_validation_count']}/"
        f"{report['preview_validation_total']}",
        f"- Perspective invalid rows: "
        f"{report.get('n_perspective_invalid', 0)}",
        "",
        "## Aggregated learned win rate (policy-perspective)",
        "",
        f"- Learned wins: {report['learned_wins']}/"
        f"{report.get('n_perspective_valid', report['n_valid_battles'])} = "
        f"{report['learned_win_rate']:.4f}",
        f"- Baseline wins: {report['baseline_wins']}/"
        f"{report.get('n_perspective_valid', report['n_valid_battles'])} = "
        f"{report['baseline_win_rate']:.4f}",
        f"- Wilson 95% CI: "
        f"[{report['wilson_95_lo']:.4f}, {report['wilson_95_hi']:.4f}]",
        "",
        "## Side diagnostic (separate from treatment effect)",
        "",
        f"- learned_as_p1: {report['learned_as_p1_n']} rows, "
        f"wins {report['learned_wins_as_p1']}, "
        f"rate {report['learned_as_p1_win_rate']:.4f}",
        f"- learned_as_p2: {report['learned_as_p2_n']} rows, "
        f"wins {report['learned_wins_as_p2']}, "
        f"rate {report['learned_as_p2_win_rate']:.4f}",
        f"- side collapse |p1_rate - p2_rate|: "
        f"{report['side_collapse']:.4f}",
        "",
        "## Paired categories (policy-perspective)",
        "",
        f"- learned_both (on_both):  {report['on_both']}",
        f"- baseline_both (v3_both): {report['v3_both']}",
        f"- split:                  {report['split']}",
        f"- Decisive pairs: {report['on_both'] + report['v3_both']}",
        f"- Two-sided exact p: {report['sign_test_two_sided_p']:.4f}",
        f"- One-sided p (learned regression): "
        f"{report['sign_test_one_sided_p']:.4f}",
        f"- Treatment effect mean: "
        f"{report['treatment_effect_mean']:+.4f}",
        f"- Paired bootstrap 95% CI: "
        f"[{report['paired_bootstrap'][1]:+.4f}, "
        f"{report['paired_bootstrap'][2]:+.4f}]",
        "",
        "## Other metrics",
        "",
        f"- Avg turns: {report['avg_turns']:.1f}",
        f"- Plan changed rate (learned vs baseline): "
        f"{report['plan_changed_rate_vs_v3']:.4f}",
        f"- Unique learned plans: {report['n_unique_plans_learned']}",
        f"- Unique baseline plans: {report['n_unique_plans_v3']}",
        f"- Timeouts: {report['n_timeout']}",
        f"- Errors: {report['n_error']}",
        f"- No-battles: {report['n_no_battle']}",
        "",
        f"## Decision: {decision['decision']}",
        "",
    ]
    if decision["reasons_pass"]:
        lines.append("**Pass:**")
        for r in decision["reasons_pass"]:
            lines.append(f"  - {r}")
        lines.append("")
    if decision["reasons_fail"]:
        lines.append("**Fail:**")
        for r in decision["reasons_fail"]:
            lines.append(f"  - {r}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Phase V3a.2 reality check analyzer"
    )
    parser.add_argument("--tag", type=str, required=True)
    parser.add_argument(
        "--merge-tags", nargs="*", default=None,
        help="Additional artifact tags to merge (chunked runs).",
    )
    parser.add_argument("--md", type=str, default=None)
    parser.add_argument(
        "--learned-policy", type=str,
        default="learned_preview_v3a1",
        help=(
            "Learned-arm policy name (used for "
            "perspective-correct counting). Default "
            "V3a.1; pass e.g. learned_preview_v3c1 "
            "for V3c.2."
        ),
    )
    parser.add_argument(
        "--baseline-policy", type=str,
        default="matchup_top4_v3",
        help=(
            "Baseline-arm policy name (used for "
            "perspective-correct counting). Default "
            "matchup_top4_v3."
        ),
    )
    parser.add_argument(
        "--v3a4-audit", action="store_true",
        help="Run the V3a.4 side-asymmetry audit instead "
        "of (or in addition to) the V3a.2 go/no-go "
        "analysis. Outputs go to "
        "<tag>_v3a4_audit.{json,md}.",
    )
    args = parser.parse_args()
    if args.v3a4_audit:
        run_audit_cli(args.tag, args.merge_tags)
        return
    report = analyze(
        args.tag, merge_tags=args.merge_tags,
        learned_policy=args.learned_policy,
        baseline_policy=args.baseline_policy,
    )
    decision = decide_go_no_go(report)
    text = format_report(report, decision)
    print(text)
    if args.md:
        with open(args.md, "w") as f:
            f.write(text)
    # Save JSON.
    out_json = (
        f"logs/vgc2026_{args.tag}_analysis.json"
    )
    with open(out_json, "w") as f:
        json.dump(
            {"report": report, "decision": decision}, f, indent=2
        )


if __name__ == "__main__":
    main()
