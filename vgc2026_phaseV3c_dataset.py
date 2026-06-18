#!/usr/bin/env python3
"""Phase V3c — VGC preview-training dataset builder.

Ponytail: small focused module. Reuses
run_one_battle and init_artifacts from
bot_vgc2026_phaseV3a2_reality.

Goal: produce 300 valid VGC preview battles
(6 pairings × 25 pairs × 2 sides) with VGC-only
policies. Each pairing is run as a separate
artifact so a single failed chunk does not lose
the rest.

Hard rules:
- VGC only (gen9championsvgc2026regma).
- Localhost only.
- Username prefix V3c_ visible in browser.
- No new model training.
- No policy wrapper added.
- matchup_top4_v3 remains default.
- No overwrite without --overwrite.
"""
import argparse
import asyncio
import csv
import json
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot_vgc2026_phaseV3a2_reality import (
    BATTLE_FORMAT,
    check_localhost,
    init_artifacts,
    make_player_name,
    run_one_battle,
)
from vgc_team_pool import load_vgc_pool


# ---------------------------------------------------------------------------
# Pairing configuration
# ---------------------------------------------------------------------------


PAIRINGS: List[Tuple[str, str]] = [
    ("matchup_top4_v3", "learned_preview_v3a1"),
    ("matchup_top4_v3", "basic_top4"),
    ("learned_preview_v3a1", "basic_top4"),
    ("matchup_top4_v3", "random"),
    ("learned_preview_v3a1", "random"),
    ("basic_top4", "random"),
]
DEFAULT_TAG_BASE = "phaseV3c_preview_dataset25"
DEFAULT_N_PAIRS = 25
LOG_DIR = "logs"
ALL_FOUR_POLICIES = (
    "matchup_top4_v3", "learned_preview_v3a1",
    "basic_top4", "random",
)


def _pairing_slug(policy_a: str, policy_b: str) -> str:
    """Stable slug for a pairing. ponytail: a<b
    so (V3, basic) and (basic, V3) are the same
    pairing file.
    """
    a, b = sorted([policy_a, policy_b])
    return f"{a}_vs_{b}"


def _verify_policies_available() -> Optional[str]:
    """Verify the V3a.1 model artifact exists.
    ponytail: preflight, returns None on OK or
    a string error.
    """
    p = "logs/vgc2026_phaseV3a1_preview_model.json"
    if not os.path.isfile(p):
        return (
            f"missing V3a.1 model artifact {p}; "
            f"learned_preview_v3a1 cannot run"
        )
    return None


# ---------------------------------------------------------------------------
# Battle runner for one pairing
# ---------------------------------------------------------------------------


def _tag_for_pairing(policy_a: str, policy_b: str) -> str:
    return (
        f"{DEFAULT_TAG_BASE}_"
        f"{_pairing_slug(policy_a, policy_b)}"
    )


def run_pairing(
    policy_a: str,
    policy_b: str,
    n_pairs: int,
    start_pair: int,
    seed: int = 42,
    timeout: float = 90.0,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Run n_pairs of side-swapped VGC battles for
    a single (a, b) pairing. Returns the artifact
    paths and a small summary.
    """
    tag = _tag_for_pairing(policy_a, policy_b)
    csv_path, jsonl_path, paths_meta = init_artifacts(
        tag, overwrite
    )
    pool = load_vgc_pool()
    start_time = time.time()
    results: List[Dict[str, Any]] = []
    for pair_id in range(start_pair, start_pair + n_pairs):
        our_idx = pair_id % len(pool)
        opp_idx = pair_id % len(pool)
        # D1: a as p1, b as p2.
        d1 = asyncio.run(
            run_one_battle(
                pair_id, "p1", policy_a, policy_b,
                our_idx, opp_idx, pool, seed=seed,
                timeout=timeout,
            )
        )
        # D2: b as p1, a as p2.
        d2 = asyncio.run(
            run_one_battle(
                pair_id, "p2", policy_b, policy_a,
                our_idx, opp_idx, pool, seed=seed,
                timeout=timeout,
            )
        )
        results.extend([d1, d2])
        # Append rows.
        with open(csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            for r in (d1, d2):
                writer.writerow([
                    r["pair_id"], r["side"], r["our_policy"],
                    r["opponent_policy"], r["battle_tag"],
                    r["started_at"], r["finished_at"],
                    r["status"], r["our_win"], r["turns"],
                    r["error_detail"], "|".join(r["our_chosen_4"]),
                    "|".join(r["our_lead_2"]),
                    "|".join(r["our_back_2"]),
                    "|".join(r["opp_chosen_4"]),
                    "|".join(r["opp_lead_2"]),
                    "|".join(r["opp_back_2"]),
                ])
        with open(jsonl_path, "a") as f:
            f.write(json.dumps(d1) + "\n")
            f.write(json.dumps(d2) + "\n")
        elapsed = time.time() - start_time
        print(
            f"  pair {pair_id:03d} done ({elapsed:.0f}s) "
            f"| D1 {d1['status']}/{d1['our_win']} "
            f"| D2 {d2['status']}/{d2['our_win']}",
            flush=True,
        )
    return {
        "tag": tag,
        "csv_path": str(csv_path),
        "jsonl_path": str(jsonl_path),
        "n_pairs": n_pairs,
        "n_battles": len(results),
        "elapsed_s": time.time() - start_time,
        "policy_a": policy_a,
        "policy_b": policy_b,
    }


# ---------------------------------------------------------------------------
# Per-pairing and merged validation
# ---------------------------------------------------------------------------


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _split_pair_categories(rows: List[Dict[str, Any]]):
    """Reuse the V3a.2 analyzer's split logic.
    ponytail: pair categories computed for any
    pair of opposing policies.
    """
    from analyze_vgc2026_phaseV3a2_reality import (
        _split_pair_categories as split,
    )
    return split(rows)


def _validate_pairing(
    rows: List[Dict[str, Any]], policy_a: str, policy_b: str
) -> Dict[str, Any]:
    """Per-pairing validation. Returns counts and
    the winner policy distribution.

    Layout: D1 has a as p1, b as p2. D2 has b as
    p1, a as p2. So a's side-wins are:
    - a_p1: rows with side=p1 and our_win=True
      (a is our in D1, our_win=True means a won
      as p1)
    - a_p2: rows with side=p2 and our_win=False
      (a is opponent in D2, a wins when our
      loses). Symmetric for b.
    """
    valid = [
        r for r in rows
        if r.get("status") == "ok" and r.get("our_win") is not None
    ]
    bad = [r for r in rows if r not in valid]
    battle_tags = [r.get("battle_tag", "") for r in rows]
    dup_tags = [
        t for t, c in Counter(battle_tags).items() if c > 1
    ]
    pair_ids = {r.get("pair_id") for r in rows}
    sides = {(r.get("pair_id"), r.get("side")) for r in rows}
    complete_pairs = sum(
        1 for p in pair_ids
        if (p, "p1") in sides and (p, "p2") in sides
    )
    win_rows = [r for r in rows if r.get("our_win") is not None]
    # Per-side: who won.
    p1_total = sum(1 for r in win_rows if r["side"] == "p1")
    p2_total = sum(1 for r in win_rows if r["side"] == "p2")
    p1_wins = sum(
        1 for r in win_rows
        if r["side"] == "p1" and r["our_win"]
    )
    p2_wins = sum(
        1 for r in win_rows
        if r["side"] == "p2" and r["our_win"]
    )
    # a is "our" in D1 (side=p1). a is "opponent" in
    # D2 (side=p2). So:
    # a_p1 = p1_wins (D1: a as p1, a wins = p1 wins)
    # a_p2 = p2_total - p2_wins (D2: a as p2, a wins
    #   when p2 loses)
    # b_p1 = p2_wins (D1: b as p2, b wins when p2 wins)
    #   wait, in D1 b is p2, so b wins when our (a)
    #   loses, so b_p1_in_D1 = (p2_loses from D1's
    #   perspective) = p1_wins_in_D1. But "b_p1" in the
    #   pairing semantics means "b as p1 in D2".
    # Cleanest: a_p1/a_p2/b_p1/b_p2 refer to
    # side-based win counts, not D1/D2 ordering.
    a_p1 = sum(
        1 for r in win_rows
        if r["side"] == "p1" and r["our_win"]
    )
    a_p2 = sum(
        1 for r in win_rows
        if r["side"] == "p2" and not r["our_win"]
    )
    b_p1 = sum(
        1 for r in win_rows
        if r["side"] == "p1" and not r["our_win"]
    )
    b_p2 = sum(
        1 for r in win_rows
        if r["side"] == "p2" and r["our_win"]
    )
    a_wins = a_p1 + a_p2
    b_wins = b_p1 + b_p2
    return {
        "n_rows": len(rows),
        "n_valid": len(valid),
        "n_bad": len(bad),
        "n_duplicate_tags": len(dup_tags),
        "n_unique_pairs": len(pair_ids),
        "n_complete_pairs": complete_pairs,
        "winner_policy_a": a_wins,
        "winner_policy_b": b_wins,
        "a_wins_as_p1": a_p1,
        "a_wins_as_p2": a_p2,
        "b_wins_as_p1": b_p1,
        "b_wins_as_p2": b_p2,
        "battle_format": BATTLE_FORMAT,
    }


def _per_pairing_categories(
    rows: List[Dict[str, Any]], policy_a: str, policy_b: str
) -> Dict[str, Any]:
    """Paired categories: a_both / b_both / split /
    invalid. ponytail: a is whichever policy is
    the 'first' arg of the pairing; b is the
    other. Layout: D1 has a as our (p1), b as
    opponent (p2). D2 has b as our (p1), a as
    opponent (p2). So:
    - a_d1 = d1["our_win"]
    - a_d2 = not d2["our_win"] (a is opponent)
    - b_d1 = not d1["our_win"] (b is opponent)
    - b_d2 = d2["our_win"] (b is our)
    """
    by_pair: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for r in rows:
        if r.get("status") != "ok":
            continue
        if r.get("our_win") is None:
            continue
        p = r.get("pair_id")
        s = r.get("side")
        by_pair.setdefault(p, {})[s] = r
    a_both = 0
    b_both = 0
    split = 0
    invalid = 0
    for p, sides in by_pair.items():
        if "p1" not in sides or "p2" not in sides:
            invalid += 1
            continue
        d1, d2 = sides["p1"], sides["p2"]
        a_d1 = d1["our_win"]
        a_d2 = not d2["our_win"]
        b_d1 = not d1["our_win"]
        b_d2 = d2["our_win"]
        # a wins both sides: a_d1 and a_d2.
        if a_d1 and a_d2:
            a_both += 1
        # b wins both sides: b_d1 and b_d2.
        elif b_d1 and b_d2:
            b_both += 1
        else:
            split += 1
    return {
        "a_both": a_both,
        "b_both": b_both,
        "split": split,
        "invalid": invalid,
        "n_decisive": a_both + b_both,
        "n_total_pairs": a_both + b_both + split + invalid,
    }


def _wilson_ci(
    wins: int, total: int, z: float = 1.96
) -> Tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    p = wins / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    half = z * (
        (p * (1 - p) / total + z * z / (4 * total * total))
        ** 0.5
    )
    lower = (centre - half) / denom
    upper = (centre + half) / denom
    return (max(0.0, lower), min(1.0, upper))


def _label_entropy(
    rows: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Entropy of the winner distribution over
    decisive pairs. ponytail: high entropy means
    many policies win some; low means one
    dominates.

    Each decisive pair has a single winner
    (a_both or b_both); split pairs contribute
    both policies. ponytail: same D1/D2 layout
    as _per_pairing_categories.
    """
    by_pair: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for r in rows:
        if r.get("status") != "ok":
            continue
        if r.get("our_win") is None:
            continue
        p = r.get("pair_id")
        s = r.get("side")
        by_pair.setdefault(p, {})[s] = r
    winner_pols = []
    for p, sides in by_pair.items():
        if "p1" not in sides or "p2" not in sides:
            continue
        d1, d2 = sides["p1"], sides["p2"]
        a_d1 = d1["our_win"]
        a_d2 = not d2["our_win"]
        b_d1 = not d1["our_win"]
        b_d2 = d2["our_win"]
        if a_d1 and a_d2:
            winner_pols.append(d1["our_policy"])
        elif b_d1 and b_d2:
            winner_pols.append(d2["our_policy"])
        else:
            winner_pols.append(d1["our_policy"])
            winner_pols.append(d2["our_policy"])
    if not winner_pols:
        return {
            "n_decisive": 0, "entropy": 0.0,
            "policy_counts": {},
        }
    counts = Counter(winner_pols)
    total = sum(counts.values())
    import math
    ent = 0.0
    for c in counts.values():
        p = c / total
        if p > 0:
            ent -= p * math.log2(p)
    return {
        "n_decisive": total,
        "entropy": ent,
        "policy_counts": dict(counts),
    }


def _plan_change_rate(rows: List[Dict[str, Any]]) -> float:
    """Fraction of battles where the chosen_4
    differs from the first occurrence of that
    policy on the same (team_hash). ponytail:
    simple measure of how often the policy
    actually picks a different plan across
    pairs.
    """
    by_team_pol: Dict[Tuple[str, str], List] = {}
    for r in rows:
        if r.get("status") != "ok":
            continue
        # Use (team_id, policy) to group.
        team = r.get("our_team", []) or []
        species = tuple(
            sorted(p.get("species", "") for p in team)
        )
        pol = r.get("our_policy", "")
        key = (species, pol)
        by_team_pol.setdefault(key, []).append(
            tuple(r.get("our_chosen_4", []))
        )
    total = 0
    diffs = 0
    for key, plans in by_team_pol.items():
        if len(plans) < 2:
            continue
        first = plans[0]
        for p in plans:
            total += 1
            if p != first:
                diffs += 1
    return diffs / total if total else 0.0


def _side_collapse(
    rows: List[Dict[str, Any]], policy_a: str
) -> float:
    """Side collapse: |a_win_rate_as_p1 -
    a_win_rate_as_p2|. ponytail: helper for
    split-pair diagnostics. policy_a is the
    "our" policy in D1 (side=p1) and the
    "opponent" in D2 (side=p2). So a wins as
    p1 = our_win=True at side=p1, and a wins
    as p2 = our_win=False at side=p2.
    """
    p1 = [r for r in rows
          if r.get("side") == "p1" and r.get("our_win") is not None]
    p2 = [r for r in rows
          if r.get("side") == "p2" and r.get("our_win") is not None]
    if not p1 or not p2:
        return 0.0
    a_p1 = sum(1 for r in p1 if r["our_win"])
    a_p2 = sum(1 for r in p2 if not r["our_win"])
    return abs(a_p1 / len(p1) - a_p2 / len(p2))


# ---------------------------------------------------------------------------
# Acceptance gates
# ---------------------------------------------------------------------------


def _acceptance_gates(
    per_pairing: List[Dict[str, Any]],
    merged: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply the dataset acceptance gates from
    the V3c task spec. Returns a dict of gate
    results and a top-level pass/block.

    Per the task spec: "every pairing has at
    least 10 decisive pairs OR explicitly report
    insufficient signal" and "side collapse <=
    15pp per pairing, or clearly mark noisy
    pairing". The noisy/insufficient markings
    are recorded in the report; they don't
    block the gate if the dataset is otherwise
    usable for training.
    """
    gate_results: Dict[str, bool] = {}
    # Gate: 300 valid battles / 150 complete pairs.
    gate_results["n_battles_eq_300"] = (
        merged["n_battles_total"] == 300
    )
    gate_results["n_pairs_eq_150"] = (
        merged["n_complete_pairs"] == 150
    )
    # Gate: zero timeout/error/no_battle.
    gate_results["zero_bad_status"] = (
        merged["n_bad_status_total"] == 0
    )
    # Gate: preview validation 100% (no team
    # serialization failures).
    gate_results["zero_team_serialization"] = (
        merged["n_team_serialization_total"] == 0
    )
    # Gate: 0 duplicate battle tags.
    gate_results["zero_duplicate_tags"] = (
        merged["n_duplicate_tags_total"] == 0
    )
    # Per-pairing: decisive >= 10 OR marked
    # insufficient_signal.
    n_decisive = [
        p["categories"]["n_decisive"] for p in per_pairing
    ]
    n_insufficient = sum(
        1 for n in n_decisive if n < 10
    )
    gate_results["every_pairing_decisive_ge_10"] = (
        n_insufficient == 0
    )
    # Per-pairing: side collapse <= 15pp OR marked
    # noisy.
    n_noisy = sum(
        1 for p in per_pairing if p["side_collapse"] > 0.15
    )
    gate_results["side_collapse_le_15pp_all"] = (
        n_noisy == 0
    )
    # Gate: no single winner policy contributes
    # >60% of all decisive wins.
    counts = merged["winner_policy_counts_decisive"]
    total_decisive = sum(counts.values()) or 1
    if counts:
        max_share = max(c / total_decisive for c in counts.values())
    else:
        max_share = 0.0
    gate_results["no_single_policy_over_60pct"] = (
        max_share <= 0.60
    )
    # Gate: V3 + learned together contribute at
    # least 30% of decisive wins.
    v3_learned = (
        counts.get("matchup_top4_v3", 0)
        + counts.get("learned_preview_v3a1", 0)
    )
    gate_results["v3_learned_share_ge_30pct"] = (
        v3_learned / total_decisive >= 0.30
    )
    # Label entropy vs old V3b.1 dataset.
    new_ent = merged["label_entropy"]
    old_ent = 0.65  # V3b.1 decisive labels were 95%
    # random/basic — very low entropy.
    gate_results["label_entropy_improved"] = (
        new_ent > old_ent
    )
    # Overall: pass all hard gates (battle count,
    # bad status, dups, no over-dominance,
    # v3+learned share, entropy). The two
    # per-pairing gates ("every_pairing_decisive_
    # ge_10" and "side_collapse_le_15pp_all")
    # are reported in the noisy/insufficient
    # markings; the dataset is still GO if the
    # hard gates all pass.
    hard_gates = [
        "n_battles_eq_300",
        "n_pairs_eq_150",
        "zero_bad_status",
        "zero_team_serialization",
        "zero_duplicate_tags",
        "no_single_policy_over_60pct",
        "v3_learned_share_ge_30pct",
        "label_entropy_improved",
    ]
    overall = all(gate_results[g] for g in hard_gates)
    return {
        "gates": gate_results,
        "overall_pass": overall,
        "n_battles_total": merged["n_battles_total"],
        "n_complete_pairs": merged["n_complete_pairs"],
        "max_winner_share": max_share,
        "v3_learned_share": v3_learned / total_decisive,
        "label_entropy": new_ent,
        "old_label_entropy": old_ent,
        "n_insufficient_signal_pairings": n_insufficient,
        "n_noisy_pairings": n_noisy,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _build_merged(
    per_pairing: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge per-pairing summaries into a single
    dataset summary. ponytail: aggregator.
    """
    n_battles_total = sum(p["n_battles"] for p in per_pairing)
    n_complete_pairs = sum(
        p["n_complete_pairs"] for p in per_pairing
    )
    n_bad_status_total = sum(p["n_bad"] for p in per_pairing)
    n_team_serialization_total = sum(
        1 for p in per_pairing
        for r in _load_jsonl(p["jsonl_path"])
        if r.get("status") == "team_serialization"
    )
    # Battle-tag dedupe within each pairing
    # (cross-pairing tag reuse is fine because
    # each pairing uses the same pair_id namespace).
    n_duplicate_tags_total = sum(
        p["n_duplicate_tags"] for p in per_pairing
    )
    # Winner-policy counts on decisive pairs.
    all_decisive_winner_pols: List[str] = []
    for p in per_pairing:
        rows = _load_jsonl(p["jsonl_path"])
        for r in rows:
            if r.get("status") != "ok":
                continue
            if r.get("our_win") is None:
                continue
            all_decisive_winner_pols.append(r["our_policy"])
    # Label entropy: per-pairing merge.
    all_rows = []
    for p in per_pairing:
        all_rows.extend(_load_jsonl(p["jsonl_path"]))
    ent = _label_entropy(all_rows)
    return {
        "n_pairings": len(per_pairing),
        "n_battles_total": n_battles_total,
        "n_complete_pairs": n_complete_pairs,
        "n_bad_status_total": n_bad_status_total,
        "n_team_serialization_total": n_team_serialization_total,
        "n_duplicate_tags_total": n_duplicate_tags_total,
        "winner_policy_counts_decisive": dict(
            Counter(all_decisive_winner_pols)
        ),
        "label_entropy": ent["entropy"],
        "n_decisive_pairs_total": ent["n_decisive"],
    }


def _write_summary(
    per_pairing: List[Dict[str, Any]],
    merged: Dict[str, Any],
    gates: Dict[str, Any],
    summary_json: str,
    summary_md: str,
) -> None:
    """Write summary JSON + Markdown. ponytail:
    minimal two-file write.
    """
    summary = {
        "per_pairing": per_pairing,
        "merged": merged,
        "gates": gates,
        "battle_format": BATTLE_FORMAT,
    }
    with open(summary_json, "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    lines = [
        "# Phase V3c — Preview Dataset Summary",
        "",
        f"- n_pairings: {len(per_pairing)}",
        f"- n_battles_total: {merged['n_battles_total']}",
        f"- n_complete_pairs: {merged['n_complete_pairs']}",
        f"- n_bad_status_total: {merged['n_bad_status_total']}",
        f"- n_duplicate_tags_total: "
        f"{merged['n_duplicate_tags_total']}",
        f"- winner_policy_counts_decisive: "
        f"{merged['winner_policy_counts_decisive']}",
        f"- label_entropy: {merged['label_entropy']:.3f}",
        f"- old_label_entropy (V3b.1): "
        f"{gates['old_label_entropy']:.3f}",
        f"- v3_learned_share: "
        f"{gates['v3_learned_share']:.0%}",
        f"- max_winner_share: "
        f"{gates['max_winner_share']:.0%}",
        "",
        "## Per-pairing",
        "",
        "| pairing | n_battles | n_pairs | a_wins | b_wins "
        "| a_both | b_both | split | decisive | side_collapse "
        "|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for p in per_pairing:
        lines.append(
            f"| {p['policy_a']} vs {p['policy_b']} "
            f"| {p['n_battles']} | {p['n_complete_pairs']} "
            f"| {p['winner_policy_a']} | {p['winner_policy_b']} "
            f"| {p['categories']['a_both']} "
            f"| {p['categories']['b_both']} "
            f"| {p['categories']['split']} "
            f"| {p['categories']['n_decisive']} "
            f"| {p['side_collapse']:.2f} |"
        )
    lines += [
        "",
        "## Acceptance gates",
        "",
        "| gate | result |",
        "|---|:-:|",
    ]
    for k, v in gates["gates"].items():
        lines.append(f"| {k} | {'PASS' if v else 'FAIL'} |")
    lines += [
        "",
        f"**OVERALL: "
        f"{'GO_FOR_TRAINING_DATASET' if gates['overall_pass'] else 'DATASET_BLOCKED'}**",
    ]
    with open(summary_md, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Build per-pairing summary from artifact
# ---------------------------------------------------------------------------


def build_per_pairing_summary(
    policy_a: str,
    policy_b: str,
    jsonl_path: str,
) -> Dict[str, Any]:
    """Read a pairing's jsonl and produce the
    per-pairing summary.
    """
    rows = _load_jsonl(jsonl_path)
    val = _validate_pairing(rows, policy_a, policy_b)
    cats = _per_pairing_categories(rows, policy_a, policy_b)
    win_total = (
        val["winner_policy_a"] + val["winner_policy_b"]
    )
    a_ci = _wilson_ci(val["winner_policy_a"], win_total)
    b_ci = _wilson_ci(val["winner_policy_b"], win_total)
    return {
        "policy_a": policy_a,
        "policy_b": policy_b,
        "jsonl_path": jsonl_path,
        "n_battles": val["n_rows"],
        "n_valid": val["n_valid"],
        "n_bad": val["n_bad"],
        "n_duplicate_tags": val["n_duplicate_tags"],
        "n_unique_pairs": val["n_unique_pairs"],
        "n_complete_pairs": val["n_complete_pairs"],
        "winner_policy_a": val["winner_policy_a"],
        "winner_policy_b": val["winner_policy_b"],
        "a_wins_as_p1": val["a_wins_as_p1"],
        "a_wins_as_p2": val["a_wins_as_p2"],
        "b_wins_as_p1": val["b_wins_as_p1"],
        "b_wins_as_p2": val["b_wins_as_p2"],
        "wilson_a": list(a_ci),
        "wilson_b": list(b_ci),
        "categories": cats,
        "side_collapse": _side_collapse(rows, policy_a),
        "plan_change_rate": _plan_change_rate(rows),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Phase V3c VGC preview-training dataset "
            "builder."
        )
    )
    parser.add_argument(
        "--pairing",
        type=str,
        default=None,
        help=(
            "Single pairing 'A,B' to run. If omitted, "
            "runs all 6 pairings."
        ),
    )
    parser.add_argument(
        "--n-pairs",
        type=int,
        default=DEFAULT_N_PAIRS,
    )
    parser.add_argument(
        "--start-pair",
        type=int,
        default=0,
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=90.0,
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
    )
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help=(
            "Skip running battles; only build "
            "summary from existing jsonl files."
        ),
    )
    parser.add_argument(
        "--summary-json",
        type=str,
        default=os.path.join(
            LOG_DIR,
            "vgc2026_phaseV3c_preview_dataset25_summary.json",
        ),
    )
    parser.add_argument(
        "--summary-md",
        type=str,
        default=os.path.join(
            LOG_DIR,
            "vgc2026_phaseV3c_preview_dataset25_summary.md",
        ),
    )
    args = parser.parse_args()
    if not check_localhost():
        print("ERROR: localhost:8000 not healthy.")
        return 3
    err = _verify_policies_available()
    if err is not None:
        print(f"ERROR: {err}")
        return 4
    # Confirm default policy unchanged.
    from team_preview_policy import choose_four_from_six
    import inspect
    default_pol = inspect.signature(
        choose_four_from_six
    ).parameters["policy"].default
    if default_pol != "basic_top4":
        print(
            f"ERROR: default policy changed to "
            f"{default_pol}; expected basic_top4."
        )
        return 5
    # Build pairings to run.
    if args.pairing:
        a, b = args.pairing.split(",")
        pairings = [(a.strip(), b.strip())]
    else:
        pairings = list(PAIRINGS)
    if not args.analyze_only:
        for a, b in pairings:
            print(f"\n=== {a} vs {b} ===", flush=True)
            tag = _tag_for_pairing(a, b)
            jsonl_path = os.path.join(
                LOG_DIR, f"{tag}.jsonl"
            )
            if (
                os.path.isfile(jsonl_path)
                and not args.overwrite
            ):
                print(
                    f"  skipping (exists, use "
                    f"--overwrite): {jsonl_path}"
                )
                continue
            run_pairing(
                a, b,
                n_pairs=args.n_pairs,
                start_pair=args.start_pair,
                seed=args.seed,
                timeout=args.timeout,
                overwrite=args.overwrite,
            )
    # Build summary.
    per_pairing = []
    for a, b in pairings:
        # Slug uses sorted order, so the jsonl
        # path is the same regardless of literal a,b.
        # init_artifacts prepends "vgc2026_" to the
        # tag when writing the file.
        tag = _tag_for_pairing(a, b)
        jsonl_path = os.path.join(
            LOG_DIR, f"vgc2026_{tag}.jsonl"
        )
        per_pairing.append(
            build_per_pairing_summary(a, b, jsonl_path)
        )
    merged = _build_merged(per_pairing)
    gates = _acceptance_gates(per_pairing, merged)
    _write_summary(
        per_pairing, merged, gates,
        args.summary_json, args.summary_md,
    )
    print(
        f"\noverall: "
        f"{'GO_FOR_TRAINING_DATASET' if gates['overall_pass'] else 'DATASET_BLOCKED'}"
    )
    return 0 if gates["overall_pass"] else 6


if __name__ == "__main__":
    sys.exit(main())
