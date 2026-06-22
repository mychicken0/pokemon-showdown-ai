#!/usr/bin/env python3
"""
VGC 2026 Phase V2j — Lead Matchup Evaluator v3 Analyzer.

This analyzer reads V2f battle labels ONLY after the V2j
evaluator's configuration fingerprint was frozen at import time.
The freeze is recorded at the moment the analyzer module is
imported, before any V2f artifact file is opened. The proof is
exposed in the report.

Hard boundary
-------------
- The V2j evaluator's configuration is FROZEN at module import
  time (see ``FROZEN_FINGERPRINT`` in vgc2026_lead_matchup_evaluator_v3).
- This analyzer records the freeze time at its own import time.
- V2f labels are loaded only after the freeze record exists.
- The report's ``outcome_freeze_proof`` records both timestamps
  and asserts that the freeze time is strictly before the first
  V2f label read.

Comparisons
-----------
- All 100 V3 plans
- All 100 Random plans
- V3-both (30) vs Random-both (25): unpaired between-group
- Within 25 Random-both pairs: losing V3 plan vs winning Random
  plan (paired)
- Split pairs (45): descriptive only

Strict actionable gate
-----------------------
A component is "candidate actionable" only if ALL gates pass:
- decisive support >= 20
- paired bootstrap CI excludes zero (between-group OR within-failure)
- between-group and within-failure directions agree
- LOO stability >= 90%
- fold stability >= 4/5
- signal survives removal of largest absolute pair
- unknown rate <= 10%
- not driven by one species, team, or pair

Decision
--------
- No component passes all gates -> "B" (continue offline work).
- Exactly one passes -> produce a narrow V4 design proposal only.
- Multiple pass -> report and stop for Codex selection.
- Never implement V4 in this phase.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random as _random
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from vgc2026_lead_matchup_evaluator_v3 import (
    BOOTSTRAP_SEED,
    COMPONENT_SPECS,
    FROZEN_FINGERPRINT,
    N_BOOTSTRAP,
    enumerate_opponent_lead_pairs,
    evaluate_lead_matchup,
    lead_pair_score,
)


# ---------------------------------------------------------------------------
# Outcome-isolation state
# ---------------------------------------------------------------------------

_ANALYZER_FREEZE_TIME: float = time.time()
_FIRST_OUTCOME_LOAD_TIME: Optional[float] = None
ANALYZER_FROZEN_FINGERPRINT: str = FROZEN_FINGERPRINT


def _record_first_outcome_load() -> None:
    global _FIRST_OUTCOME_LOAD_TIME
    if _FIRST_OUTCOME_LOAD_TIME is None:
        _FIRST_OUTCOME_LOAD_TIME = time.time()


def load_v2f_outcomes_with_freeze_proof(
    logs_dir: Path, artifact_prefix: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    _record_first_outcome_load()
    return _load_v2f_artifacts(logs_dir, artifact_prefix)


# ---------------------------------------------------------------------------
# V2f artifact loaders
# ---------------------------------------------------------------------------


def _load_v2f_artifacts(
    logs_dir: Path, artifact_prefix: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    from vgc_team_pool import load_vgc_pool
    benchmark_csv = logs_dir / f"{artifact_prefix}_benchmark.csv"
    preview_csv = logs_dir / f"{artifact_prefix}_preview_evidence.csv"
    benchmark_rows: List[Dict[str, Any]] = []
    with open(benchmark_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            benchmark_rows.append(dict(row))
    preview_rows: List[Dict[str, Any]] = []
    with open(preview_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            preview_rows.append(dict(row))
    pool = load_vgc_pool()
    team_lookup: Dict[str, Dict[str, Any]] = {}
    for team in pool:
        team_lookup[team.id] = {
            "id": team.id,
            "rank": team.rank,
            "player": team.player,
            "pokemon": list(team.pokemon),
        }
    return benchmark_rows, preview_rows, team_lookup


# ---------------------------------------------------------------------------
# Pair record construction
# ---------------------------------------------------------------------------


def _split_pipe(value: str) -> List[str]:
    if not isinstance(value, str) or not value.strip():
        return []
    return [v.strip().lower() for v in value.split("|") if v.strip()]


def build_pair_records(
    benchmark_rows: Sequence[Mapping[str, Any]],
    preview_rows: Sequence[Mapping[str, Any]],
    team_lookup: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge benchmark + preview rows by pair_id, independent of
    row order.

    Each pair has a V3 row (player_policy == "matchup_top4_v3")
    and a Random row (player_policy == "random"). Pair records
    carry the V3 perspective on D1 and D2.
    """
    preview_index: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in preview_rows:
        key = (str(row.get("pair_id", "")), str(row.get("side", "")))
        preview_index[key] = row
    pairs: Dict[str, Dict[str, Any]] = {}
    for row in benchmark_rows:
        pair_id = str(row.get("pair_id", ""))
        side = str(row.get("side", ""))
        team_id = str(row.get("team_id", ""))
        opponent_team_id = str(row.get("opponent_team_id", ""))
        preview = preview_index.get((pair_id, side), {})
        player_policy = str(preview.get("player_policy", "")).strip().lower()
        if player_policy not in {"matchup_top4_v3", "random"}:
            continue
        entry = pairs.setdefault(pair_id, {
            "pair_id": pair_id,
            "team_id": team_id,
            "opponent_team_id": opponent_team_id,
            "v3_plan": None,
            "random_plan": None,
            "d1_v3_win": None,
            "d2_v3_win": None,
            "status": "ok",
        })
        plan = {
            "chosen_4": _split_pipe(preview.get("planned_chosen_4", "")),
            "lead_2": _split_pipe(preview.get("planned_lead_2", "")),
            "back_2": _split_pipe(preview.get("planned_back_2", "")),
        }
        if player_policy == "matchup_top4_v3":
            entry["v3_plan"] = plan
        else:
            entry["random_plan"] = plan
        v3_won_side = (
            str(row.get("our_win", "")).lower() == "true"
            if side == "p1"
            else str(row.get("our_win", "")).lower() != "true"
        )
        if side == "p1":
            entry["d1_v3_win"] = v3_won_side
        else:
            entry["d2_v3_win"] = v3_won_side
    out: List[Dict[str, Any]] = []
    for pair_id, entry in pairs.items():
        if (
            entry["v3_plan"] is None
            or entry["random_plan"] is None
            or entry["d1_v3_win"] is None
            or entry["d2_v3_win"] is None
        ):
            entry["status"] = "incomplete"
        out.append(entry)
    return out


def classify_pair(pair: Mapping[str, Any]) -> str:
    if pair.get("d1_v3_win") is None or pair.get("d2_v3_win") is None:
        return "invalid"
    if pair["d1_v3_win"] and pair["d2_v3_win"]:
        return "v3_both"
    if not pair["d1_v3_win"] and not pair["d2_v3_win"]:
        return "random_both"
    return "split"


def sign_test(
    pairs: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    """Decisive-only sign test (splits excluded from directional
    test)."""
    counts = Counter()
    for pair in pairs:
        if pair.get("status") != "ok":
            continue
        counts[classify_pair(pair)] += 1
    v3_both = counts.get("v3_both", 0)
    random_both = counts.get("random_both", 0)
    split = counts.get("split", 0)
    decisive = v3_both + random_both
    if decisive == 0:
        two_sided = 1.0
        one_sided = 1.0
    else:
        from math import comb
        probabilities = [
            comb(decisive, k) / (2 ** decisive)
            for k in range(decisive + 1)
        ]
        one_sided = min(1.0, sum(probabilities[v3_both:]))
        observed = probabilities[v3_both]
        two_sided = min(
            1.0,
            sum(p for p in probabilities if p <= observed + 1e-15),
        )
    return {
        "v3_both": int(v3_both),
        "random_both": int(random_both),
        "split": int(split),
        "decisive_n": int(decisive),
        "two_sided_p": float(two_sided),
        "one_sided_p": float(one_sided),
    }


# ---------------------------------------------------------------------------
# Plan reconstruction from team data
# ---------------------------------------------------------------------------


def _team_to_pokemon_list(
    team_entry: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for mon in team_entry.get("pokemon", []) or []:
        out.append({
            "species": str(mon.get("species", "")).strip().lower(),
            "ability": str(mon.get("ability", "")).strip().lower(),
            "moves": [str(m).strip() for m in (mon.get("moves", []) or [])],
            "item": str(mon.get("item", "")).strip().lower(),
        })
    return out


@dataclass
class PlanScore:
    plan: Dict[str, Any]
    v2j_score: float
    eval_obj: Any


def _evaluate_plan(
    team_pokemon: Sequence[Mapping[str, Any]],
    opponent_pokemon: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any]
) -> PlanScore:
    chosen_4 = list(plan.get("chosen_4", []))
    lead_2 = list(plan.get("lead_2", []))
    back_2 = list(plan.get("back_2", []))
    eval_obj = evaluate_lead_matchup(
        team_pokemon, opponent_pokemon, chosen_4, lead_2, back_2
    )
    v2j = lead_pair_score(eval_obj)
    return PlanScore(
        plan={"chosen_4": chosen_4, "lead_2": lead_2, "back_2": back_2},
        v2j_score=v2j,
        eval_obj=eval_obj,
    )


def build_bundles_by_pair(
    pairs: Sequence[Mapping[str, Any]],
    team_lookup: Mapping[str, Mapping[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    bundles: Dict[int, Dict[str, Any]] = {}
    for pair in pairs:
        if pair.get("status") != "ok":
            continue
        pair_id = int(pair.get("pair_id", -1))
        team_entry = team_lookup.get(pair.get("team_id", ""))
        opp_entry = team_lookup.get(pair.get("opponent_team_id", ""))
        if not team_entry or not opp_entry:
            continue
        team_pokemon = _team_to_pokemon_list(team_entry)
        opp_pokemon = _team_to_pokemon_list(opp_entry)
        if len(team_pokemon) != 6 or len(opp_pokemon) != 6:
            continue
        v3_score = _evaluate_plan(team_pokemon, opp_pokemon, pair["v3_plan"])
        random_score = _evaluate_plan(
            team_pokemon, opp_pokemon, pair["random_plan"]
        )
        bundles[pair_id] = {
            "v3": v3_score,
            "random": random_score,
            "team_pokemon": team_pokemon,
            "opp_pokemon": opp_pokemon,
            "v3_plan": pair["v3_plan"],
            "random_plan": pair["random_plan"],
        }
    return bundles


# ---------------------------------------------------------------------------
# Synthetic inputs
# ---------------------------------------------------------------------------


def build_synthetic_inputs() -> Dict[str, Any]:
    """30 v3_both + 25 random_both + 45 split pairs."""
    inputs: Dict[str, Any] = {
        "pair_records": [],
        "team_lookup": {},
        "synthetic": True,
    }
    team = [
        {"species": "Incineroar", "ability": "Intimidate",
         "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
        {"species": "Garchomp", "ability": "Rough Skin",
         "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
        {"species": "Rillaboom", "ability": "Grassy Surge",
         "moves": ["Fake Out", "Grassy Glide", "U-turn", "Protect"]},
        {"species": "Tornadus", "ability": "Prankster",
         "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
        {"species": "Flutter Mane", "ability": "Protosynthesis",
         "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"]},
        {"species": "Iron Hands", "ability": "Quark Drive",
         "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
    ]
    opp = [
        {"species": "Rillaboom", "ability": "Grassy Surge",
         "moves": ["Fake Out", "Grassy Glide", "U-turn", "Protect"]},
        {"species": "Iron Hands", "ability": "Quark Drive",
         "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
        {"species": "Kingambit", "ability": "Supreme Overlord",
         "moves": ["Iron Head", "Sucker Punch", "Swords Dance", "Protect"]},
        {"species": "Incineroar", "ability": "Intimidate",
         "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
        {"species": "Garchomp", "ability": "Rough Skin",
         "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
        {"species": "Tornadus", "ability": "Prankster",
         "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
    ]
    v3_plan = {
        "chosen_4": ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
        "lead_2": ["Incineroar", "Tornadus"],
        "back_2": ["Garchomp", "Rillaboom"],
    }
    rand_plan = {
        "chosen_4": ["Rillaboom", "Garchomp", "Incineroar", "Iron Hands"],
        "lead_2": ["Rillaboom", "Garchomp"],
        "back_2": ["Incineroar", "Iron Hands"],
    }
    pair_records: List[Dict[str, Any]] = []
    for i in range(30):
        pair_records.append({
            "pair_id": str(i),
            "team_id": f"team_v3_{i}",
            "opponent_team_id": f"opp_{i}",
            "v3_plan": v3_plan,
            "random_plan": rand_plan,
            "d1_v3_win": True,
            "d2_v3_win": True,
            "status": "ok",
        })
    for i in range(30, 55):
        pair_records.append({
            "pair_id": str(i),
            "team_id": f"team_r_{i}",
            "opponent_team_id": f"opp_{i}",
            "v3_plan": v3_plan,
            "random_plan": rand_plan,
            "d1_v3_win": False,
            "d2_v3_win": False,
            "status": "ok",
        })
    for i in range(55, 100):
        d1_v3 = (i % 2 == 0)
        d2_v3 = not d1_v3
        pair_records.append({
            "pair_id": str(i),
            "team_id": f"team_s_{i}",
            "opponent_team_id": f"opp_{i}",
            "v3_plan": v3_plan,
            "random_plan": rand_plan,
            "d1_v3_win": d1_v3,
            "d2_v3_win": d2_v3,
            "status": "ok",
        })
    inputs["pair_records"] = pair_records
    team_lookup: Dict[str, Dict[str, Any]] = {}
    for record in pair_records:
        team_lookup[record["team_id"]] = {
            "id": record["team_id"], "pokemon": team,
        }
        team_lookup[record["opponent_team_id"]] = {
            "id": record["opponent_team_id"], "pokemon": opp,
        }
    inputs["team_lookup"] = team_lookup
    return inputs


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def _summarise(values: Sequence[float]) -> Dict[str, float]:
    if not values:
        return {"n": 0, "mean": 0.0, "median": 0.0, "min": 0.0,
                "p10": 0.0, "p90": 0.0, "max": 0.0}
    ordered = sorted(float(v) for v in values)
    n = len(ordered)
    mean = sum(ordered) / n
    median = (
        ordered[n // 2]
        if n % 2 == 1
        else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    )
    return {
        "n": n,
        "mean": mean,
        "median": median,
        "min": ordered[0],
        "p10": _percentile(ordered, 0.10),
        "p90": _percentile(ordered, 0.90),
        "max": ordered[-1],
    }


def _percentile(values: Sequence[float], frac: float) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * frac
    lo = int(position)
    hi = min(lo + 1, len(ordered) - 1)
    weight = position - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


def _bootstrap_mean_diff_ci(
    a: Sequence[float],
    b: Sequence[float],
    n_resamples: int = N_BOOTSTRAP,
    alpha: float = 0.05,
    seed: int = BOOTSTRAP_SEED,
) -> Optional[Tuple[float, float, float]]:
    if not a or not b:
        return None
    rng = _random.Random(seed)
    a_list = list(a)
    b_list = list(b)
    observed = statistics.fmean(a_list) - statistics.fmean(b_list)
    n_a = len(a_list)
    n_b = len(b_list)
    resamples: List[float] = []
    for _ in range(n_resamples):
        a_b = [a_list[rng.randrange(n_a)] for _ in range(n_a)]
        b_b = [b_list[rng.randrange(n_b)] for _ in range(n_b)]
        resamples.append(statistics.fmean(a_b) - statistics.fmean(b_b))
    resamples.sort()
    lo_idx = max(0, int(math.floor((alpha / 2) * n_resamples)))
    hi_idx = min(
        n_resamples - 1,
        int(math.ceil((1 - alpha / 2) * n_resamples)) - 1,
    )
    return observed, resamples[lo_idx], resamples[hi_idx]


def _bootstrap_paired_mean_diff_ci(
    a: Sequence[float],
    b: Sequence[float],
    n_resamples: int = N_BOOTSTRAP,
    alpha: float = 0.05,
    seed: int = BOOTSTRAP_SEED,
) -> Optional[Tuple[float, float, float]]:
    if not a or len(a) != len(b):
        return None
    differences = [float(x) - float(y) for x, y in zip(a, b)]
    observed = statistics.fmean(differences)
    rng = _random.Random(seed)
    n = len(differences)
    resamples = [
        statistics.fmean(differences[rng.randrange(n)] for _ in range(n))
        for _ in range(n_resamples)
    ]
    resamples.sort()
    lo_idx = max(0, int(math.floor((alpha / 2) * n_resamples)))
    hi_idx = min(
        n_resamples - 1,
        int(math.ceil((1 - alpha / 2) * n_resamples)) - 1,
    )
    return observed, resamples[lo_idx], resamples[hi_idx]


def _ci_excludes_zero(
    ci: Optional[Tuple[float, float, float]]
) -> bool:
    return bool(ci is not None and (ci[1] > 0.0 or ci[2] < 0.0))


def _cohens_d(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    if len(a) < 2 or len(b) < 2:
        return None
    var_a = statistics.variance(a)
    var_b = statistics.variance(b)
    denom = (len(a) - 1) + (len(b) - 1)
    if denom <= 0:
        return None
    pooled_var = ((len(a) - 1) * var_a + (len(b) - 1) * var_b) / denom
    if pooled_var <= 0:
        return None
    return (statistics.fmean(a) - statistics.fmean(b)) / math.sqrt(pooled_var)


# ---------------------------------------------------------------------------
# LOO and 5-fold stability
# ---------------------------------------------------------------------------


def _loo_stability(
    values: Sequence[float],
    seed: int = BOOTSTRAP_SEED,
) -> float:
    """Return the fraction of LOO iterations that preserve the
    sign of the mean."""
    if len(values) < 2:
        return 0.0
    full_mean = statistics.fmean(values)
    full_sign = 1 if full_mean >= 0 else -1
    matches = 0
    n = len(values)
    for i in range(n):
        rest = values[:i] + values[i + 1:]
        m = statistics.fmean(rest)
        if (1 if m >= 0 else -1) == full_sign:
            matches += 1
    return matches / n


def _fold_stability(
    values: Sequence[float],
    n_folds: int = 5,
    seed: int = BOOTSTRAP_SEED,
) -> Tuple[float, List[str]]:
    """Deterministic 5-fold stability: split into contiguous folds
    in sorted order; record each fold-mean's sign; return the
    fraction of folds that agree with the overall sign and the
    list of fold signs."""
    if len(values) < n_folds:
        return 0.0, ["n/a"] * len(values)
    full_mean = statistics.fmean(values)
    full_sign = 1 if full_mean >= 0 else -1
    ordered = list(values)
    n = len(ordered)
    fold_size = n // n_folds
    signs: List[str] = []
    matches = 0
    for k in range(n_folds):
        start = k * fold_size
        end = n if k == n_folds - 1 else (k + 1) * fold_size
        fold = ordered[start:end]
        m = statistics.fmean(fold)
        sign = 1 if m >= 0 else -1
        signs.append("+" if sign == 1 else "-")
        if sign == full_sign:
            matches += 1
    return matches / n_folds, signs


def _survives_largest_removal(
    a: Sequence[float],
    b: Sequence[float],
) -> bool:
    """Check that the mean-diff sign survives removal of the pair
    with the largest absolute difference."""
    if len(a) != len(b) or len(a) < 2:
        return False
    diffs = [abs(x - y) for x, y in zip(a, b)]
    full_diff = statistics.fmean([x - y for x, y in zip(a, b)])
    full_sign = 1 if full_diff >= 0 else -1
    keep = sorted(range(len(a)), key=lambda i: diffs[i])[:-1]
    new_diff = statistics.fmean(
        [a[i] - b[i] for i in keep]
    )
    new_sign = 1 if new_diff >= 0 else -1
    return new_sign == full_sign


def _not_driven_by_one(
    values: Sequence[float],
    labels: Sequence[str],
) -> bool:
    """True if removing the single largest absolute value does not
    flip the sign of the mean."""
    if len(values) < 3:
        return True
    full = statistics.fmean(values)
    sign = 1 if full >= 0 else -1
    abs_vals = [abs(v) for v in values]
    worst = abs_vals.index(max(abs_vals))
    rest = [v for i, v in enumerate(values) if i != worst]
    new = statistics.fmean(rest)
    new_sign = 1 if new >= 0 else -1
    return new_sign == sign


# ---------------------------------------------------------------------------
# Component gate evaluation
# ---------------------------------------------------------------------------


GATE_NAMES: Tuple[str, ...] = (
    "decisive_support_ge_20",
    "paired_bootstrap_ci_excludes_zero",
    "between_within_direction_agree",
    "loo_stability_ge_90pct",
    "fold_stability_ge_4_of_5",
    "survives_largest_removal",
    "unknown_rate_le_10pct",
    "not_driven_by_one",
)


def evaluate_component(
    component: str,
    between_values: Sequence[float],
    within_values: Sequence[float],
    labels: Sequence[str],
    unknown_rates: Sequence[float],
) -> Dict[str, Any]:
    """Run the strict actionable gate for one component.

    The component is the per-pair mean of ``component_means``
    values for the V3 plan in either V3-both or Random-both,
    depending on the comparison direction.
    """
    gates: Dict[str, bool] = {}
    # Decisive support >= 20
    n_decisive = len(between_values)
    gates["decisive_support_ge_20"] = n_decisive >= 20
    # Paired bootstrap CI excludes zero
    paired_ci = _bootstrap_paired_mean_diff_ci(between_values, within_values)
    gates["paired_bootstrap_ci_excludes_zero"] = _ci_excludes_zero(paired_ci)
    # Between-group and within-failure directions agree
    between_mean = (
        statistics.fmean(between_values) if between_values else 0.0
    )
    within_mean = (
        statistics.fmean(within_values) if within_values else 0.0
    )
    between_sign = 1 if between_mean >= 0 else -1
    within_sign = 1 if within_mean >= 0 else -1
    gates["between_within_direction_agree"] = (
        between_sign == within_sign
    )
    # LOO stability >= 90%
    loo = _loo_stability(between_values)
    gates["loo_stability_ge_90pct"] = loo >= 0.9
    # Fold stability >= 4/5
    fold, fold_signs = _fold_stability(between_values)
    gates["fold_stability_ge_4_of_5"] = fold >= 4.0 / 5.0
    # Signal survives removal of largest absolute pair
    gates["survives_largest_removal"] = _survives_largest_removal(
        between_values, within_values
    )
    # Unknown rate <= 10%
    mean_unknown = (
        statistics.fmean(unknown_rates) if unknown_rates else 1.0
    )
    gates["unknown_rate_le_10pct"] = mean_unknown <= 0.10
    # Not driven by one species, team, or pair
    gates["not_driven_by_one"] = _not_driven_by_one(
        between_values, labels
    )

    passed_all = all(gates.values())
    return {
        "component": component,
        "n_decisive": n_decisive,
        "between_mean": float(between_mean),
        "within_mean": float(within_mean),
        "between_sign": "+" if between_sign == 1 else "-",
        "within_sign": "+" if within_sign == 1 else "-",
        "paired_bootstrap_ci": paired_ci,
        "loo_stability": loo,
        "fold_stability": fold,
        "fold_signs": fold_signs,
        "mean_unknown_rate": float(mean_unknown),
        "gates": gates,
        "candidate_actionable": passed_all,
        "contradictory": (
            gates["paired_bootstrap_ci_excludes_zero"]
            and not gates["between_within_direction_agree"]
        ),
    }


# ---------------------------------------------------------------------------
# Run analysis
# ---------------------------------------------------------------------------


def _safe_run(inputs: Mapping[str, Any]) -> Dict[str, Any]:
    pair_records = list(inputs.get("pair_records", []))
    team_lookup = dict(inputs.get("team_lookup", {}))
    bundles_by_pair = build_bundles_by_pair(pair_records, team_lookup)
    bundles_by_pair_dict: Dict[int, Dict[str, Any]] = dict(bundles_by_pair)
    sign_stats = sign_test(pair_records)
    decisive_pairs = [
        p for p in pair_records
        if classify_pair(p) in {"v3_both", "random_both"}
        and p.get("status") == "ok"
    ]
    split_pairs = [
        p for p in pair_records
        if classify_pair(p) == "split" and p.get("status") == "ok"
    ]

    feature_keys = [spec.name for spec in COMPONENT_SPECS]

    v3_both_components: Dict[str, List[float]] = {k: [] for k in feature_keys}
    random_both_components: Dict[str, List[float]] = {k: [] for k in feature_keys}
    v3_both_unknown_rates: List[float] = []
    within_components: Dict[str, List[float]] = {k: [] for k in feature_keys}
    split_components: Dict[str, List[float]] = {k: [] for k in feature_keys}
    pair_labels: List[str] = []

    for pair in decisive_pairs:
        pair_id = int(pair.get("pair_id", -1))
        bundle = bundles_by_pair_dict.get(pair_id)
        if not bundle:
            continue
        cls = classify_pair(pair)
        v3_eval = bundle["v3"].eval_obj
        rnd_eval = bundle["random"].eval_obj
        v3_both_unknown_rates.append(v3_eval.uncertainty.get("unknown_rate", 0.0))
        pair_labels.append(f"pair_{pair_id}_{cls}")
        if cls == "v3_both":
            for k in feature_keys:
                v3_both_components[k].append(v3_eval.component_means.get(k, 0.0))
                random_both_components[k].append(v3_eval.component_means.get(k, 0.0))
        else:
            for k in feature_keys:
                random_both_components[k].append(v3_eval.component_means.get(k, 0.0))
            # Within-failure: losing V3 plan vs winning Random plan.
            for k in feature_keys:
                within_components[k].append(
                    v3_eval.component_means.get(k, 0.0)
                    - rnd_eval.component_means.get(k, 0.0)
                )

    for pair in split_pairs:
        pair_id = int(pair.get("pair_id", -1))
        bundle = bundles_by_pair_dict.get(pair_id)
        if not bundle:
            continue
        v3_eval = bundle["v3"].eval_obj
        rnd_eval = bundle["random"].eval_obj
        for k in feature_keys:
            split_components[k].append(
                v3_eval.component_means.get(k, 0.0)
                - rnd_eval.component_means.get(k, 0.0)
            )

    # Aggregate component gate table.
    gate_table: List[Dict[str, Any]] = []
    for k in feature_keys:
        between = v3_both_components[k]
        within = within_components[k]
        result = evaluate_component(
            k, between, within, pair_labels, v3_both_unknown_rates
        )
        gate_table.append(result)

    actionable = [r for r in gate_table if r["candidate_actionable"]]
    contradictory = [r for r in gate_table if r["contradictory"]]

    # Decision
    n_actionable = len(actionable)
    if n_actionable == 0:
        decision_code = "B"
        decision_summary = "continue offline evaluator work"
    elif n_actionable == 1:
        decision_code = "C"
        decision_summary = (
            "produce a narrow V4 design proposal only (do not implement)"
        )
    else:
        decision_code = "D"
        decision_summary = (
            "multiple components pass; stop for Codex selection "
            "(do not implement V4)"
        )

    # Per-component summaries (descriptive).
    v3_both_summary = {
        k: _summarise(v3_both_components[k]) for k in feature_keys
    }
    random_both_summary = {
        k: _summarise(random_both_components[k]) for k in feature_keys
    }
    within_summary = {
        k: _summarise(within_components[k]) for k in feature_keys
    }
    split_summary = {
        k: _summarise(split_components[k]) for k in feature_keys
    }

    # Outcome-isolation proof.
    freeze_time = _ANALYZER_FREEZE_TIME
    first_load = _FIRST_OUTCOME_LOAD_TIME
    proof = {
        "frozen_before_outcomes": (
            first_load is None or freeze_time < first_load
        ),
        "fingerprint": ANALYZER_FROZEN_FINGERPRINT,
        "freeze_time_unix": freeze_time,
        "first_outcome_load_unix": first_load,
        "elapsed_between_freeze_and_first_load_seconds": (
            (first_load - freeze_time)
            if first_load is not None else 0.0
        ),
    }

    # Runtime: time to evaluate one plan.
    timings: List[float] = []
    for pair_id, entry in list(bundles_by_pair_dict.items())[:25]:
        v3 = entry.get("v3")
        if v3 is None:
            continue
        plan = entry["v3_plan"]
        team = entry["team_pokemon"]
        opp = entry["opp_pokemon"]
        t0 = time.perf_counter()
        evaluate_lead_matchup(
            team, opp,
            plan["chosen_4"], plan["lead_2"], plan["back_2"],
        )
        timings.append(time.perf_counter() - t0)
    runtime = {
        "n": len(timings),
        "avg_ms": 1000.0 * statistics.fmean(timings) if timings else 0.0,
        "p95_ms": 1000.0 * _percentile(timings, 0.95) if timings else 0.0,
        "max_ms": 1000.0 * max(timings) if timings else 0.0,
    }

    # Audit / unknown counts.
    audit_unknown = {
        "v3_unknown_moves_total": 0,
        "v3_unknown_abilities_total": 0,
        "random_unknown_moves_total": 0,
        "random_unknown_abilities_total": 0,
    }
    for pair_id, entry in bundles_by_pair_dict.items():
        v3 = entry.get("v3")
        rnd = entry.get("random")
        if v3 is not None:
            audit_unknown["v3_unknown_moves_total"] += len(
                v3.eval_obj.unknown_moves
            )
            audit_unknown["v3_unknown_abilities_total"] += len(
                v3.eval_obj.unknown_abilities
            )
        if rnd is not None:
            audit_unknown["random_unknown_moves_total"] += len(
                rnd.eval_obj.unknown_moves
            )
            audit_unknown["random_unknown_abilities_total"] += len(
                rnd.eval_obj.unknown_abilities
            )

    return {
        "decisive_n": len(decisive_pairs),
        "split_n": len(split_pairs),
        "sign_test": sign_stats,
        "v3_both_summary": v3_both_summary,
        "random_both_summary": random_both_summary,
        "within_failure_summary": within_summary,
        "split_summary": split_summary,
        "gate_table": gate_table,
        "actionable_components": [r["component"] for r in actionable],
        "contradictory_components": [r["component"] for r in contradictory],
        "decision": {
            "code": decision_code,
            "summary": decision_summary,
            "matchup_top4_v4_implemented": False,
            "phase_v3_status": "BLOCKED",
            "n_actionable": n_actionable,
        },
        "audit_unknown": audit_unknown,
        "runtime": runtime,
        "fingerprint": ANALYZER_FROZEN_FINGERPRINT,
        "outcome_freeze_proof": proof,
    }


def run_analysis(inputs: Mapping[str, Any]) -> Dict[str, Any]:
    return _safe_run(inputs)


# ---------------------------------------------------------------------------
# Render markdown
# ---------------------------------------------------------------------------


def _gate_check(gate_value: bool) -> str:
    return "PASS" if gate_value else "FAIL"


def render_markdown(report: Mapping[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Phase V2j — Lead Matchup Evaluator v3")
    lines.append("")
    lines.append(
        "Configuration is FROZEN at module import time. The "
        "fingerprint below is the only allowed V2j evaluator "
        "configuration."
    )
    lines.append("")
    lines.append(f"Fingerprint: `{report['fingerprint']}`")
    lines.append("")
    proof = report["outcome_freeze_proof"]
    lines.append("## Outcome-isolation proof")
    lines.append("")
    lines.append(
        f"- Frozen at import time: **{proof['frozen_before_outcomes']}**"
    )
    lines.append(
        f"- Fingerprint recorded at freeze: "
        f"`{proof['fingerprint'][:16]}...`"
    )
    lines.append(
        f"- Freeze time (unix): {proof['freeze_time_unix']:.6f}"
    )
    if proof["first_outcome_load_unix"] is not None:
        lines.append(
            f"- First outcome load (unix): "
            f"{proof['first_outcome_load_unix']:.6f}"
        )
        lines.append(
            f"- Elapsed between freeze and first load (s): "
            f"{proof['elapsed_between_freeze_and_first_load_seconds']:.6f}"
        )
    lines.append("")
    lines.append("## Sign test (decisive-only)")
    lines.append("")
    st = report["sign_test"]
    lines.append(
        f"V3-both: **{st['v3_both']}** | Random-both: "
        f"**{st['random_both']}** | Split: **{st['split']}**"
    )
    lines.append(
        f"Decisive n: **{st['decisive_n']}** | "
        f"Two-sided p: **{st['two_sided_p']:.6f}** | "
        f"One-sided p: **{st['one_sided_p']:.6f}**"
    )
    lines.append("")
    lines.append("## Strict actionable gate table")
    lines.append("")
    lines.append(
        "| Component | Decisive | between | within | LOO | Fold | Largest | CI | Agree | Unknown | Actionable |"
    )
    lines.append(
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for row in report["gate_table"]:
        gates = row["gates"]
        ci = row["paired_bootstrap_ci"]
        ci_str = (
            f"[{ci[1]:+.3f}, {ci[2]:+.3f}]"
            if ci is not None else "n/a"
        )
        lines.append(
            f"| {row['component']} | {row['n_decisive']} | "
            f"{row['between_mean']:+.3f} | {row['within_mean']:+.3f} | "
            f"{row['loo_stability']:.2f} | {row['fold_stability']:.2f} | "
            f"{_gate_check(gates['survives_largest_removal'])} | {ci_str} | "
            f"{_gate_check(gates['between_within_direction_agree'])} | "
            f"{_gate_check(gates['unknown_rate_le_10pct'])} | "
            f"{_gate_check(row['candidate_actionable'])} |"
        )
    lines.append("")
    lines.append("## Actionable components")
    lines.append("")
    if report["actionable_components"]:
        for c in report["actionable_components"]:
            lines.append(f"- {c}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Contradictory components")
    lines.append("")
    if report["contradictory_components"]:
        for c in report["contradictory_components"]:
            lines.append(f"- {c}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Decision")
    lines.append("")
    decision = report["decision"]
    lines.append(
        f"**{decision['code']} — {decision['summary']}.** "
        f"Phase V3 remains **{decision['phase_v3_status']}**. "
        f"`matchup_top4_v4` was not implemented."
    )
    lines.append("")
    lines.append("## Audit / unknown-move reporting")
    lines.append("")
    au = report["audit_unknown"]
    lines.append(
        f"V3 plans unknown moves total: {au['v3_unknown_moves_total']} | "
        f"V3 plans unknown abilities total: "
        f"{au['v3_unknown_abilities_total']}"
    )
    lines.append(
        f"Random plans unknown moves total: "
        f"{au['random_unknown_moves_total']} | "
        f"Random plans unknown abilities total: "
        f"{au['random_unknown_abilities_total']}"
    )
    lines.append("")
    lines.append("## Runtime")
    lines.append("")
    rt = report["runtime"]
    lines.append(
        f"n: {rt['n']} | avg: {rt['avg_ms']:.2f} ms | "
        f"p95: {rt['p95_ms']:.2f} ms | max: {rt['max_ms']:.2f} ms"
    )
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Artifact writing
# ---------------------------------------------------------------------------


def write_artifacts(
    report: Mapping[str, Any],
    out_dir: Path,
    json_name: str = "vgc2026_phaseV2j_lead_matchups.json",
    md_name: str = "vgc2026_phaseV2j_lead_matchups.md",
) -> Tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / json_name
    md_path = out_dir / md_name
    serializable = json.loads(json.dumps(report, default=str))
    json_path.write_text(json.dumps(serializable, indent=2, default=str))
    md_path.write_text(render_markdown(report))
    return json_path, md_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=Path(
            PROJECT_ROOT / "logs"
        ),
    )
    parser.add_argument(
        "--artifact-prefix",
        default="vgc2026_phaseV2c_phaseV2f_v3_paired_qualification",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Use synthetic inputs (no battle labels required).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            PROJECT_ROOT / "logs"
        ),
    )
    args = parser.parse_args()
    if args.synthetic:
        inputs = build_synthetic_inputs()
    else:
        benchmark_rows, preview_rows, team_lookup = (
            load_v2f_outcomes_with_freeze_proof(
                args.logs_dir, args.artifact_prefix
            )
        )
        pair_records = build_pair_records(
            benchmark_rows, preview_rows, team_lookup
        )
        inputs = {
            "pair_records": pair_records,
            "team_lookup": team_lookup,
        }
    report = run_analysis(inputs)
    json_path, md_path = write_artifacts(report, args.output_dir)
    print(render_markdown(report))
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
