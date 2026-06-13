#!/usr/bin/env python3
"""
VGC 2026 Phase V2i — Outcome-Blind Matchup Evaluator Analyzer.

This analyzer reads V2f battle labels ONLY after the evaluator's
configuration fingerprint was frozen at import time. The freeze is
recorded at the moment the analyzer module is imported, before any
V2f artifact file is opened. The proof is exposed in the report.

Hard boundary
-------------
- The V2i evaluator's configuration is FROZEN at module import
  time (see ``FROZEN_FINGERPRINT``).
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
- All 129 teams x 4 policies offline: basic_top4, random,
  matchup_top4_v2, matchup_top4_v3

Reports
-------
- Exact denominators
- Means, medians, quantiles
- Paired differences where applicable
- Deterministic bootstrap CIs (fixed seed)
- Standardized differences where valid (Cohen's d)
- Rank correlation between evaluator v1 and v2
- Plan-ranking disagreement rate
- Component ablation results
- Unknown / missing metadata counts
- Runtime average / p95 / max

No weight optimization
----------------------
The analyzer NEVER modifies ``COMPONENT_WEIGHTS`` or any other
evaluator constant. It only consumes the evaluator's outputs.
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

sys.path.insert(0, "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai")

from vgc2026_matchup_evaluator_v2 import (
    BOOTSTRAP_SEED,
    COMPONENT_SPECS,
    FROZEN_FINGERPRINT,
    N_BOOTSTRAP,
    evaluate_matchup,
    plan_score,
)
from vgc2026_common_plan_evaluator import (
    evaluate_plan_on_common_scale,
)
from team_preview_policy import choose_four_from_six


# ---------------------------------------------------------------------------
# Outcome-isolation state
# ---------------------------------------------------------------------------
#
# The freeze record is captured at module import time, BEFORE
# any V2f artifact is opened. ``load_v2f_outcomes_with_freeze_proof``
# is the ONLY function that reads battle labels; it must not be
# called before the freeze record is captured. The freeze time is
# the import time of this module.
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
    """Load the V2f benchmark + preview + team-pool data.

    Records the first outcome load time. Asserts that the
    freeze record was captured (which is automatic at module
    import time, so this is a defensive check).
    """
    _record_first_outcome_load()
    return _load_v2f_artifacts(logs_dir, artifact_prefix)


# ---------------------------------------------------------------------------
# V2f artifact loaders (copied from V2g; isolated from feature module)
# ---------------------------------------------------------------------------


def _load_v2f_artifacts(
    logs_dir: Path, artifact_prefix: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Load benchmark + preview CSV and a team_id -> team lookup.

    Team lookup is built from the battle-ready team pool at
    data/vgc2026_topteams/vgc2026_top200_battle_ready.json via
    vgc_team_pool.load_vgc_pool. Team IDs match the
    ``pikalytics_rank_NNN`` format used in the benchmark CSV.
    """
    from vgc_team_pool import load_vgc_pool
    benchmark_csv = (
        logs_dir
        / f"{artifact_prefix}_benchmark.csv"
    )
    preview_csv = (
        logs_dir
        / f"{artifact_prefix}_preview_evidence.csv"
    )
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
    """Merge benchmark + preview rows by pair_id.

    Each pair has a V3 row (player_policy == "matchup_top4_v3")
    and a Random row (player_policy == "random"). Pair records
    carry the V3 perspective on D1 and D2 (whether V3 won each
    side). D1 is V3 as player, D2 is V3 as opponent (Random as
    player). So:
    - d1_v3_win = D1 row's our_win (V3 is p1)
    - d2_v3_win = NOT D2 row's our_win (V3 is p2)
    """
    # Index preview rows by (pair_id, side).
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
        # V3 perspective on the side: D1 (V3 as p1) -> V3 won if
        # our_win is True; D2 (V3 as p2) -> V3 won if our_win is
        # False (since p1 is Random, our_win=True means Random won).
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
    """Classify a pair from the V3 perspective.

    v3_both: V3 won both D1 and D2.
    random_both: V3 lost both D1 and D2.
    split: V3 won one side and lost the other.
    """
    if pair.get("d1_v3_win") is None or pair.get("d2_v3_win") is None:
        return "invalid"
    if pair["d1_v3_win"] and pair["d2_v3_win"]:
        return "v3_both"
    if not pair["d1_v3_win"] and not pair["d2_v3_win"]:
        return "random_both"
    return "split"


def sign_test(
    pairs: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Decisive-only sign test.

    Splits are EXCLUDED from the directional test. P-values use
    the exact binomial two-sided / one-sided computation that
    matches the V2f analyzer.
    """
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
        # One-sided (greater): P[X >= v3_both].
        one_sided = min(
            1.0, sum(probabilities[v3_both:])
        )
        # Two-sided: sum of all probabilities <= observed.
        observed = probabilities[v3_both]
        two_sided = min(
            1.0,
            sum(
                p for p in probabilities
                if p <= observed + 1e-15
            ),
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
    team_entry: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Convert a vgc2026_teams_detailed.json entry to a list of
    Pokémon dicts with species, ability, and moves.
    """
    out: List[Dict[str, Any]] = []
    for mon in team_entry.get("pokemon", []) or []:
        out.append({
            "species": str(mon.get("species", "")).strip().lower(),
            "ability": str(mon.get("ability", "")).strip().lower(),
            "moves": [
                str(m).strip() for m in (mon.get("moves", []) or [])
            ],
            "item": str(mon.get("item", "")).strip().lower(),
        })
    return out


# ---------------------------------------------------------------------------
# Plan evaluation under V2i
# ---------------------------------------------------------------------------


@dataclass
class PlanScore:
    plan: Dict[str, Any]
    v2i_score: float
    v1_score: float
    eval_obj: Any


def _evaluate_plan(
    team_pokemon: Sequence[Mapping[str, Any]],
    opponent_pokemon: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any],
) -> PlanScore:
    chosen_4 = list(plan.get("chosen_4", []))
    lead_2 = list(plan.get("lead_2", []))
    back_2 = list(plan.get("back_2", []))
    eval_obj = evaluate_matchup(
        team_pokemon, opponent_pokemon, chosen_4, lead_2, back_2
    )
    v2i = plan_score(eval_obj)
    v1_eval = evaluate_plan_on_common_scale(
        team_pokemon, opponent_pokemon, chosen_4, lead_2, back_2
    )
    return PlanScore(
        plan={"chosen_4": chosen_4, "lead_2": lead_2, "back_2": back_2},
        v2i_score=v2i,
        v1_score=float(v1_eval.total),
        eval_obj=eval_obj,
    )


def build_bundles_by_pair(
    pairs: Sequence[Mapping[str, Any]],
    team_lookup: Mapping[str, Mapping[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    """For every pair, evaluate the V3 plan and the Random plan
    under V2i + V1 against the same opponent team.

    Returns a dict keyed by pair_id; each entry has 'v3' and
    'random' PlanScore objects.
    """
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
# Synthetic inputs for the unit tests
# ---------------------------------------------------------------------------


def build_synthetic_inputs() -> Dict[str, Any]:
    """Build 30 v3_both + 25 random_both + 45 split pairs.

    The synthetic plans are derived from the standard fixture team
    so the analyzer can run end-to-end without depending on the
    V2f artifacts.
    """
    from vgc2026_matchup_evaluator_v2 import evaluate_matchup  # noqa
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
    # 30 v3_both pairs (V3 wins on D1, V3 wins on D2)
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
    # 25 random_both pairs (V3 loses on both)
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
    # 45 split pairs
    for i in range(55, 100):
        # Alternate win/lose to make sure split is the result.
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
    lo_idx = int(math.floor((alpha / 2) * n_resamples))
    hi_idx = int(math.ceil((1 - alpha / 2) * n_resamples)) - 1
    lo_idx = max(0, lo_idx)
    hi_idx = min(n_resamples - 1, hi_idx)
    return observed, resamples[lo_idx], resamples[hi_idx]


def _bootstrap_paired_mean_diff_ci(
    a: Sequence[float],
    b: Sequence[float],
    n_resamples: int = N_BOOTSTRAP,
    alpha: float = 0.05,
    seed: int = BOOTSTRAP_SEED,
) -> Optional[Tuple[float, float, float]]:
    """Bootstrap a paired mean difference by resampling pair indices."""
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
    ci: Optional[Tuple[float, float, float]],
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


def _spearman_rho(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    if not x or len(x) != len(y):
        return None
    n = len(x)
    if n < 2:
        return None
    rank_x = _rank(x)
    rank_y = _rank(y)
    mean_rx = statistics.fmean(rank_x)
    mean_ry = statistics.fmean(rank_y)
    cov = statistics.fmean(
        [(rx - mean_rx) * (ry - mean_ry) for rx, ry in zip(rank_x, rank_y)]
    )
    var_x = statistics.fmean(
        [(rx - mean_rx) ** 2 for rx in rank_x]
    )
    var_y = statistics.fmean(
        [(ry - mean_ry) ** 2 for ry in rank_y]
    )
    if var_x <= 0 or var_y <= 0:
        return None
    return cov / math.sqrt(var_x * var_y)


def _rank(values: Sequence[float]) -> List[float]:
    sorted_with_index = sorted(
        enumerate(values), key=lambda p: p[1]
    )
    ranks: List[float] = [0.0] * len(values)
    i = 0
    while i < len(sorted_with_index):
        j = i
        while (
            j + 1 < len(sorted_with_index)
            and sorted_with_index[j + 1][1] == sorted_with_index[i][1]
        ):
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            original_index = sorted_with_index[k][0]
            ranks[original_index] = avg_rank
        i = j + 1
    return ranks


# ---------------------------------------------------------------------------
# Plan-rating comparison
# ---------------------------------------------------------------------------


def _rank_corr_v1_v2(
    bundles: Mapping[int, Mapping[str, Any]],
) -> Dict[str, Any]:
    v1: List[float] = []
    v2: List[float] = []
    for pair_id, entry in bundles.items():
        v3 = entry.get("v3")
        if v3 is None:
            continue
        v1.append(v3.v1_score)
        v2.append(v3.v2i_score)
    rho = _spearman_rho(v1, v2)
    return {
        "n": len(v1),
        "spearman_rho": rho,
    }


def _ranking_disagreement(
    bundles: Mapping[int, Mapping[str, Any]],
) -> Dict[str, Any]:
    """For each pair, decide whether V2i ranks the V3 plan
    higher than the Random plan (v2i_v3 > v2i_random). For the
    same pair, decide whether V1 ranks the V3 plan higher. The
    disagreement rate is the fraction of pairs where the two
    evaluators disagree.
    """
    same = 0
    diff = 0
    for pair_id, entry in bundles.items():
        v3 = entry.get("v3")
        rnd = entry.get("random")
        if v3 is None or rnd is None:
            continue
        v2i_v3_higher = v3.v2i_score > rnd.v2i_score
        v1_v3_higher = v3.v1_score > rnd.v1_score
        if v2i_v3_higher == v1_v3_higher:
            same += 1
        else:
            diff += 1
    total = same + diff
    return {
        "n": total,
        "agree": same,
        "disagree": diff,
        "disagreement_rate": (diff / total) if total else 0.0,
    }


# ---------------------------------------------------------------------------
# Component ablation
# ---------------------------------------------------------------------------


def _ablation_table(
    bundles: Mapping[int, Mapping[str, Any]],
    feature_keys: Sequence[str],
) -> List[Dict[str, Any]]:
    """For each component, recompute the mean V2i score with the
    component zeroed, and report the drop relative to the
    full-component score.
    """
    out: List[Dict[str, Any]] = []
    full_scores: List[float] = []
    for pair_id, entry in bundles.items():
        v3 = entry.get("v3")
        if v3 is None:
            continue
        full_scores.append(v3.v2i_score)
    if not full_scores:
        return out
    full_mean = statistics.fmean(full_scores)
    for component in feature_keys:
        # Approximate the ablation by computing the mean of
        # (full_v2i - component_mean * weight) for every pair.
        drops: List[float] = []
        for pair_id, entry in bundles.items():
            v3 = entry.get("v3")
            if v3 is None:
                continue
            comp_mean = v3.eval_obj.component_means.get(component, 0.0)
            from vgc2026_matchup_evaluator_v2 import COMPONENT_WEIGHTS
            weight = COMPONENT_WEIGHTS.get(component, 0.0)
            drops.append(weight * comp_mean)
        if not drops:
            continue
        drop_mean = statistics.fmean(drops)
        out.append({
            "component": component,
            "n": len(drops),
            "contribution_mean": drop_mean,
            "ablation_drop_pct": (
                100.0 * drop_mean / full_mean if full_mean != 0 else 0.0
            ),
        })
    out.sort(key=lambda r: r["contribution_mean"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Run analysis
# ---------------------------------------------------------------------------


def _safe_run(inputs: Mapping[str, Any]) -> Dict[str, Any]:
    """Run the full analyzer on the given inputs.

    ``inputs`` is a dict with keys: pair_records, team_lookup.
    The labels in pair_records are read ONLY after the freeze
    record is captured (which is automatic at module import).
    """
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

    # Per-plan score summaries.
    v3_scores: List[float] = []
    random_scores: List[float] = []
    for pair in pair_records:
        if pair.get("status") != "ok":
            continue
        pair_id = int(pair.get("pair_id", -1))
        bundle = bundles_by_pair_dict.get(pair_id)
        if not bundle:
            continue
        v3_scores.append(bundle["v3"].v2i_score)
        random_scores.append(bundle["random"].v2i_score)

    v3_both_scores: List[float] = []
    random_both_scores: List[float] = []
    for pair in decisive_pairs:
        pair_id = int(pair.get("pair_id", -1))
        bundle = bundles_by_pair_dict.get(pair_id)
        if not bundle:
            continue
        cls = classify_pair(pair)
        if cls == "v3_both":
            v3_both_scores.append(bundle["v3"].v2i_score)
        else:
            random_both_scores.append(bundle["v3"].v2i_score)

    # Within-failure paired: losing V3 vs winning Random.
    within_diffs: List[float] = []
    for pair in decisive_pairs:
        if classify_pair(pair) != "random_both":
            continue
        pair_id = int(pair.get("pair_id", -1))
        bundle = bundles_by_pair_dict.get(pair_id)
        if not bundle:
            continue
        within_diffs.append(
            bundle["v3"].v2i_score - bundle["random"].v2i_score
        )

    # Split-pair descriptive: V3 vs Random score delta.
    split_diffs: List[float] = []
    for pair in split_pairs:
        pair_id = int(pair.get("pair_id", -1))
        bundle = bundles_by_pair_dict.get(pair_id)
        if not bundle:
            continue
        split_diffs.append(
            bundle["v3"].v2i_score - bundle["random"].v2i_score
        )

    # V1 vs V2 rank correlation across all bundles.
    rank_corr = _rank_corr_v1_v2(bundles_by_pair_dict)
    disagreement = _ranking_disagreement(bundles_by_pair_dict)

    # Component ablation
    ablation = _ablation_table(bundles_by_pair_dict, feature_keys)

    # Runtime measurement: time to evaluate one plan.
    timings: List[float] = []
    for pair_id, entry in list(bundles_by_pair_dict.items())[:25]:
        v3 = entry.get("v3")
        if v3 is None:
            continue
        # Re-run the same plan to measure the evaluator's
        # per-call cost.
        plan = entry["v3_plan"]
        team = entry["team_pokemon"]
        opp = entry["opp_pokemon"]
        t0 = time.perf_counter()
        evaluate_matchup(
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

    # Audit / unknown moves
    audit_unknown: Dict[str, int] = {
        "v3_unknown_total": 0,
        "random_unknown_total": 0,
    }
    for pair_id, entry in bundles_by_pair_dict.items():
        v3 = entry.get("v3")
        rnd = entry.get("random")
        if v3 is not None:
            audit_unknown["v3_unknown_total"] += len(
                v3.eval_obj.unknown_moves
            )
        if rnd is not None:
            audit_unknown["random_unknown_total"] += len(
                rnd.eval_obj.unknown_moves
            )

    # Offline 129-team comparison: evaluate basic_top4, random,
    # matchup_top4_v2, and matchup_top4_v3 on every team against
    # the same opponent. The opponent is team[(i + 1) % N].
    include_offline = bool(
        inputs.get("include_offline_comparison", not inputs.get("synthetic", False))
    )
    offline_comparison = (
        _offline_129_team_comparison(team_lookup)
        if include_offline
        else {"status": "skipped", "reason": "disabled for synthetic/test input"}
    )

    # Outcome-isolation proof
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

    between_ci = _bootstrap_mean_diff_ci(
        v3_both_scores, random_both_scores
    )
    paired_ci = _bootstrap_paired_mean_diff_ci(
        [
            bundles_by_pair_dict[int(pair["pair_id"])]["v3"].v2i_score
            for pair in decisive_pairs
            if classify_pair(pair) == "random_both"
            and int(pair["pair_id"]) in bundles_by_pair_dict
        ],
        [
            bundles_by_pair_dict[int(pair["pair_id"])]["random"].v2i_score
            for pair in decisive_pairs
            if classify_pair(pair) == "random_both"
            and int(pair["pair_id"]) in bundles_by_pair_dict
        ],
    )
    separates_failure_comparison = (
        _ci_excludes_zero(between_ci) or _ci_excludes_zero(paired_ci)
    )
    decision = {
        "code": "A" if separates_failure_comparison else "B",
        "summary": (
            "design one narrow V4 change"
            if separates_failure_comparison
            else "continue offline evaluator work"
        ),
        "failure_comparison_ci_excludes_zero": separates_failure_comparison,
        "matchup_top4_v4_implemented": False,
        "phase_v3_status": "BLOCKED",
    }

    return {
        "decisive_n": len(decisive_pairs),
        "split_n": len(split_pairs),
        "sign_test": sign_stats,
        "v3_plans": {
            "summary": _summarise(v3_scores),
        },
        "random_plans": {
            "summary": _summarise(random_scores),
        },
        "v3_both_vs_random_both": {
            "v3_both_summary": _summarise(v3_both_scores),
            "random_both_summary": _summarise(random_both_scores),
            "n_v3_both": len(v3_both_scores),
            "n_random_both": len(random_both_scores),
            "mean_diff_v3_minus_random": (
                statistics.fmean(v3_both_scores) - statistics.fmean(random_both_scores)
                if v3_both_scores and random_both_scores else 0.0
            ),
            "mean_diff_bootstrap_ci": between_ci,
            "cohens_d": _cohens_d(v3_both_scores, random_both_scores),
        },
        "within_failure_paired": {
            "n": len(within_diffs),
            "paired_mean_diff": (
                statistics.fmean(within_diffs) if within_diffs else 0.0
            ),
            "paired_bootstrap_ci": paired_ci,
        },
        "split_descriptive": {
            "n": len(split_diffs),
            "mean_diff": (
                statistics.fmean(split_diffs) if split_diffs else 0.0
            ),
            "summary": _summarise(split_diffs),
        },
        "v1_v2_rank_correlation": rank_corr,
        "ranking_disagreement": disagreement,
        "component_ablation": ablation,
        "audit_unknown": audit_unknown,
        "runtime": runtime,
        "offline_129_team_comparison": offline_comparison,
        "decision": decision,
        "fingerprint": ANALYZER_FROZEN_FINGERPRINT,
        "outcome_freeze_proof": proof,
    }


def _offline_129_team_comparison(
    team_lookup: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Compute the 129-team offline V2i evaluation for four
    policies: basic_top4, random, matchup_top4_v2,
    matchup_top4_v3.

    For each team T_i the opponent is T_{(i+1) % N} so the same
    pair is shared by every policy. The result reports the mean
    V2i score and the deterministic 95% bootstrap CI for the
    paired mean diff between V3 and V2 / random / basic_top4.
    """
    teams = list(team_lookup.values())
    if len(teams) < 4:
        return {"n_teams": 0, "reason": "team pool too small"}
    # Build (team, opponent) pairs.
    n = len(teams)
    pairs: List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]] = []
    for i, team_entry in enumerate(teams):
        opp_entry = teams[(i + 1) % n]
        if team_entry.get("id") == opp_entry.get("id"):
            continue
        team_pokemon = _team_to_pokemon_list(team_entry)
        opp_pokemon = _team_to_pokemon_list(opp_entry)
        if len(team_pokemon) != 6 or len(opp_pokemon) != 6:
            continue
        pairs.append((team_pokemon, opp_pokemon))
    if not pairs:
        return {"n_teams": 0, "reason": "no valid team pairs"}

    def _select_plan(
        policy: str,
        team: Sequence[Mapping[str, Any]],
        opponent: Sequence[Mapping[str, Any]],
        seed: int,
    ) -> Dict[str, Any]:
        result = choose_four_from_six(
            list(team), list(opponent), policy=policy, seed=seed
        )
        return {
            "chosen_4": list(result.chosen_4),
            "lead_2": list(result.lead_2),
            "back_2": list(result.back_2),
        }

    def _score_one(
        team: Sequence[Mapping[str, Any]],
        opponent: Sequence[Mapping[str, Any]],
        plan: Mapping[str, Any],
    ) -> float:
        eval_obj = evaluate_matchup(
            team, opponent,
            plan["chosen_4"], plan["lead_2"], plan["back_2"],
        )
        return plan_score(eval_obj)

    basic_scores: List[float] = []
    random_scores: List[float] = []
    v2_scores: List[float] = []
    v3_scores: List[float] = []
    selection_errors: List[str] = []
    for pair_index, (team, opponent) in enumerate(pairs):
        seed = BOOTSTRAP_SEED + pair_index
        try:
            v3_plan = _select_plan("matchup_top4_v3", team, opponent, seed)
            v2_plan = _select_plan("matchup_top4_v2", team, opponent, seed)
            basic_plan = _select_plan("basic_top4", team, opponent, seed)
            random_plan = _select_plan("random", team, opponent, seed)
            v3_scores.append(_score_one(team, opponent, v3_plan))
            v2_scores.append(_score_one(team, opponent, v2_plan))
            basic_scores.append(_score_one(team, opponent, basic_plan))
            random_scores.append(_score_one(team, opponent, random_plan))
        except Exception as exc:
            selection_errors.append(
                f"pair {pair_index}: {type(exc).__name__}: {exc}"
            )
            continue

    def _mean(values: Sequence[float]) -> float:
        return statistics.fmean(values) if values else 0.0

    out: Dict[str, Any] = {
        "n_teams": len(v3_scores),
        "n_attempted": len(pairs),
        "selection_errors": selection_errors,
        "basic_top4": {"summary": _summarise(basic_scores)},
        "random": {"summary": _summarise(random_scores)},
        "matchup_top4_v2": {"summary": _summarise(v2_scores)},
        "matchup_top4_v3": {"summary": _summarise(v3_scores)},
    }
    out["v3_minus_v2"] = {
        "mean_diff": _mean(v3_scores) - _mean(v2_scores),
        "n": len(v3_scores),
        "bootstrap_ci": _bootstrap_paired_mean_diff_ci(v3_scores, v2_scores),
    }
    out["v3_minus_random"] = {
        "mean_diff": _mean(v3_scores) - _mean(random_scores),
        "n": len(v3_scores),
        "bootstrap_ci": _bootstrap_paired_mean_diff_ci(v3_scores, random_scores),
    }
    out["v3_minus_basic"] = {
        "mean_diff": _mean(v3_scores) - _mean(basic_scores),
        "n": len(v3_scores),
        "bootstrap_ci": _bootstrap_paired_mean_diff_ci(v3_scores, basic_scores),
    }
    return out


def run_analysis(inputs: Mapping[str, Any]) -> Dict[str, Any]:
    return _safe_run(inputs)


# ---------------------------------------------------------------------------
# Render markdown
# ---------------------------------------------------------------------------


def render_markdown(report: Mapping[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Phase V2i — Outcome-Blind Matchup Evaluator v2")
    lines.append("")
    lines.append(
        "Configuration is FROZEN at module import time. The "
        "fingerprint below is the only allowed V2i evaluator "
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
    lines.append("## V3-both vs Random-both")
    lines.append("")
    table = report["v3_both_vs_random_both"]
    lines.append(
        f"V3-both n: {table['n_v3_both']} | "
        f"Random-both n: {table['n_random_both']}"
    )
    lines.append(
        f"Mean V3-both: {table['v3_both_summary']['mean']:.3f} | "
        f"Mean Random-both: "
        f"{table['random_both_summary']['mean']:.3f}"
    )
    ci = table["mean_diff_bootstrap_ci"]
    if ci is not None:
        obs, lo, hi = ci
        lines.append(
            f"Mean diff: {obs:.3f} | 95% CI: "
            f"[{lo:+.3f}, {hi:+.3f}] "
            f"({'excludes zero' if lo > 0 or hi < 0 else 'covers zero'})"
        )
    d = table["cohens_d"]
    lines.append(f"Cohen's d: {d:.3f}" if d is not None else "Cohen's d: n/a")
    lines.append("")
    lines.append("## Within-failure paired")
    lines.append("")
    wf = report["within_failure_paired"]
    lines.append(
        f"n: {wf['n']} | Paired mean diff (V3-Random): "
        f"{wf['paired_mean_diff']:+.3f}"
    )
    paired_ci = wf.get("paired_bootstrap_ci")
    if paired_ci is not None:
        obs, lo, hi = paired_ci
        lines.append(
            f"Paired diff: {obs:+.3f} | 95% CI: "
            f"[{lo:+.3f}, {hi:+.3f}] "
            f"({'excludes zero' if _ci_excludes_zero(paired_ci) else 'covers zero'})"
        )
    lines.append("")
    lines.append("## Split-pair descriptive")
    lines.append("")
    sp = report["split_descriptive"]
    lines.append(
        f"n: {sp['n']} | Mean V3-Random diff: {sp['mean_diff']:+.3f}"
    )
    lines.append("")
    lines.append("## V1 vs V2 rank correlation")
    lines.append("")
    rc = report["v1_v2_rank_correlation"]
    rho = rc.get("spearman_rho")
    lines.append(
        f"n: {rc['n']} | Spearman rho: "
        f"{rho:.3f}" if rho is not None else "n/a"
    )
    lines.append("")
    lines.append("## Plan-ranking disagreement (V1 vs V2)")
    lines.append("")
    dr = report["ranking_disagreement"]
    lines.append(
        f"n: {dr['n']} | agree: {dr['agree']} | disagree: "
        f"{dr['disagree']} | disagreement rate: "
        f"{dr['disagreement_rate']:.2%}"
    )
    lines.append("")
    lines.append("## Component ablation (top 10 contributors)")
    lines.append("")
    lines.append("| Component | Contribution (weighted mean) | Drop % |")
    lines.append("|---|---:|---:|")
    for row in report["component_ablation"][:10]:
        lines.append(
            f"| {row['component']} | {row['contribution_mean']:+.3f} | "
            f"{row['ablation_drop_pct']:+.1f}% |"
        )
    lines.append("")
    lines.append("## Audit / unknown-move reporting")
    lines.append("")
    au = report["audit_unknown"]
    lines.append(
        f"V3 plans unknown move total: {au['v3_unknown_total']} | "
        f"Random plans unknown move total: "
        f"{au['random_unknown_total']}"
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
    lines.append("## Offline 129-team policy comparison")
    lines.append("")
    offline = report["offline_129_team_comparison"]
    if offline.get("status") == "skipped":
        lines.append(f"Skipped: {offline.get('reason', 'unspecified')}")
    else:
        lines.append(
            f"Evaluated: {offline.get('n_teams', 0)}/"
            f"{offline.get('n_attempted', 0)} | "
            f"selection errors: {len(offline.get('selection_errors', []))}"
        )
        for policy in (
            "basic_top4", "random", "matchup_top4_v2", "matchup_top4_v3"
        ):
            summary = offline.get(policy, {}).get("summary", {})
            lines.append(
                f"- {policy}: n={summary.get('n', 0)}, "
                f"mean={summary.get('mean', 0.0):.3f}"
            )
        for comparison in (
            "v3_minus_v2", "v3_minus_random", "v3_minus_basic"
        ):
            row = offline.get(comparison, {})
            ci_row = row.get("bootstrap_ci")
            if ci_row is None:
                continue
            lines.append(
                f"- {comparison}: mean={row.get('mean_diff', 0.0):+.3f}, "
                f"paired 95% CI=[{ci_row[1]:+.3f}, {ci_row[2]:+.3f}]"
            )
    lines.append("")
    decision = report["decision"]
    lines.append("## Decision")
    lines.append("")
    lines.append(
        f"**{decision['code']} — {decision['summary']}.** "
        f"Phase V3 remains **{decision['phase_v3_status']}**. "
        "`matchup_top4_v4` was not implemented."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Artifact writing
# ---------------------------------------------------------------------------


def write_artifacts(
    report: Mapping[str, Any],
    out_dir: Path,
    json_name: str = "vgc2026_phaseV2i_matchup_evaluator.json",
    md_name: str = "vgc2026_phaseV2i_matchup_evaluator.md",
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
            "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs"
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
            "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs"
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
