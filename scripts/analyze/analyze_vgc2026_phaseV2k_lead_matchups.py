#!/usr/bin/env python3
"""
VGC 2026 Phase V2k — Lead Matchup Evaluator v3 Analyzer (Repaired).

This analyzer reads V2f battle labels ONLY after the V2j
evaluator's configuration fingerprint was frozen at import time.
The freeze is recorded at the moment the analyzer module is
imported, before any V2f artifact file is opened. The proof is
exposed in the report.

Compared to V2j, this analyzer:

1. Merges exclusively by ``pair_id`` (not row position).
2. Identifies the V3 plan owner from ``player_policy ==
   "matchup_top4_v3"`` and the Random plan owner from
   ``player_policy == "random"`` — never by row position.
3. Classifies pairs as ``v3_both`` (30), ``random_both`` (25),
   ``split`` (45), ``invalid`` (0). Total pairs = 100.
4. ``v3_both`` is evaluated by the V3 plan only (the winning
   plan on both battles).
5. ``random_both`` is evaluated by the LOSING V3 plan and the
   WINNING Random plan; the within-failure comparison is the
   V3-minus-Random difference per pair (25 paired samples).
6. Between-group comparison is V3 plans from ``v3_both``
   (n=30) versus V3 plans from ``random_both`` (n=25) on the
   SAME V3 plan evaluator — but ONLY on their own plans.
   The bootstrap is INDEPENDENT (unpaired) because the group
   sizes differ.
7. Within-failure bootstrap is PAIRED (25 matched pairs).
8. The strict actionable gate is satisfied only if BOTH the
   between-group CI and the within-failure CI exclude zero,
   and only on REAL artifacts. Synthetic mode cannot pass
   real freeze-proof or qualification gates.

Hard boundary
-------------
- The V2j evaluator's configuration is FROZEN at module
  import time (see ``FROZEN_FINGERPRINT`` in
  ``vgc2026_lead_matchup_evaluator_v3``).
- This analyzer records the freeze time at its own import
  time.
- V2f labels are loaded only after the freeze record exists.
- The report's ``outcome_freeze_proof`` records both
  timestamps and asserts that the freeze time is strictly
  before the first V2f label read.

Statistics
----------
- Between-group (v3_both n=30 vs random_both n=25):
  INDEPENDENT bootstrap mean-difference CI.
- Within-failure (random_both n=25 paired):
  PAIRED bootstrap mean-difference CI.
- A missing CI (e.g. because the inputs are degenerate) is
  reported as a ``missing_ci`` gate failure with an explicit
  reason.
- LOO stability, fold stability, and largest-removal
  robustness are computed on the appropriate array.
- Unknown rate, decisive support, and direction-agreement
  gates remain.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
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

# Reuse the V2j pair-merge, classification, and synthetic
# builder. They were correct in V2j; the bugs were only in
# the post-classification analysis.
from analyze_vgc2026_phaseV2j_lead_matchups import (
    ANALYZER_FROZEN_FINGERPRINT as _V2J_FROZEN_FP,
    _ANALYZER_FREEZE_TIME as _v2j_FROZEN_TIME,
    _split_pipe,
    build_pair_records as _v2j_build_pair_records,
    classify_pair as _v2j_classify_pair,
    sign_test as _v2j_sign_test,
    _team_to_pokemon_list as _v2j_team_to_pokemon_list,
    _load_v2f_artifacts as _v2j_load_v2f_artifacts,
    _record_first_outcome_load as _v2j_record_first_outcome_load,
)


# ---------------------------------------------------------------------------
# Outcome-isolation state (mirrors V2j)
# ---------------------------------------------------------------------------


_ANALYZER_FREEZE_TIME: float = _v2j_FROZEN_TIME
_FIRST_OUTCOME_LOAD_TIME: Optional[float] = None
ANALYZER_FROZEN_FINGERPRINT: str = _V2J_FROZEN_FP


def _record_first_outcome_load() -> None:
    global _FIRST_OUTCOME_LOAD_TIME
    if _FIRST_OUTCOME_LOAD_TIME is None:
        _FIRST_OUTCOME_LOAD_TIME = time.time()


def load_v2f_outcomes_with_freeze_proof(
    logs_dir: Path, artifact_prefix: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    _record_first_outcome_load()
    return _v2j_load_v2f_artifacts(logs_dir, artifact_prefix)


# ---------------------------------------------------------------------------
# Re-exports for backward compatibility with existing tests
# ---------------------------------------------------------------------------


build_pair_records = _v2j_build_pair_records
classify_pair = _v2j_classify_pair
sign_test = _v2j_sign_test
_team_to_pokemon_list = _v2j_team_to_pokemon_list


def build_synthetic_inputs() -> Dict[str, Any]:
    """V2k synthetic inputs.

    30 v3_both + 25 random_both + 45 split pairs. Each pair
    has its own team and its own opponent team, drawn from a
    4-team pool. The V3 plan and Random plan are fixed across
    pairs. Every team in the pool contains the V3 plan's four
    chosen Pokémon so the plan is always valid; the team
    composition variance comes from the BENCH slots (the two
    bench Pokémon are taken from the team pool).

    The team-composition variance produces non-zero variance
    in the V2j component_means per pair, so the bootstrap
    can compute non-degenerate CIs.
    """
    inputs: Dict[str, Any] = {
        "pair_records": [],
        "team_lookup": {},
        "synthetic": True,
    }
    v3_chosen = [
        {"species": "Incineroar", "ability": "Intimidate",
         "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
        {"species": "Tornadus", "ability": "Prankster",
         "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
        {"species": "Garchomp", "ability": "Rough Skin",
         "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
        {"species": "Rillaboom", "ability": "Grassy Surge",
         "moves": ["Fake Out", "Grassy Glide", "U-turn", "Protect"]},
    ]
    # Iron Hands is a member of the random plan's chosen_4
    # and MUST be present in every team so the random plan
    # is valid for every pair.
    iron_hands = {
        "species": "Iron Hands", "ability": "Quark Drive",
        "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"],
    }
    # 4 distinct bench pools. Each pool contains a single
    # bench Pokémon (the second bench slot is always
    # Iron Hands, the random plan's 4th species, so the
    # team is always valid for both the V3 and random
    # plans). The variable bench slot provides the
    # bootstrap variance.
    bench_pools = {
        0: {"species": "Flutter Mane", "ability": "Protosynthesis",
            "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"]},
        1: {"species": "Kingambit", "ability": "Supreme Overlord",
            "moves": ["Iron Head", "Sucker Punch", "Swords Dance", "Protect"]},
        2: {"species": "Amoonguss", "ability": "Regenerator",
            "moves": ["Spore", "Rage Powder", "Giga Drain", "Protect"]},
        3: {"species": "Pelipper", "ability": "Drizzle",
            "moves": ["Hurricane", "Scald", "U-turn", "Protect"]},
    }
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
    rand_chosen = [
        {"species": "Rillaboom", "ability": "Grassy Surge",
         "moves": ["Fake Out", "Grassy Glide", "U-turn", "Protect"]},
        {"species": "Garchomp", "ability": "Rough Skin",
         "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
        {"species": "Incineroar", "ability": "Intimidate",
         "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
        iron_hands,
    ]
    pair_records: List[Dict[str, Any]] = []
    for i in range(30):
        bench = bench_pools[i % 4]
        team = list(v3_chosen) + list(bench)
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
        bench = bench_pools[i % 4]
        team = list(v3_chosen) + list(bench)
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
        bench = bench_pools[i % 4]
        team = list(v3_chosen) + list(bench)
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
        idx = int(record["pair_id"])
        # Our team: V3 plan's 4 chosen + Iron Hands (random
        # plan's 4th) + 1 variable bench Pokémon. Both
        # plans are always valid.
        team = (
            list(v3_chosen)
            + [iron_hands]
            + [bench_pools[idx % 4]]
        )
        # Opponent team: random plan's 4 chosen + 2 distinct
        # bench Pokémon. The Iron Hands is the 4th random
        # plan species; the other bench slot is the variable.
        opp_bench_a = bench_pools[(idx + 1) % 4]
        opp_bench_b = bench_pools[(idx + 2) % 4]
        opp = (
            list(rand_chosen)
            + [opp_bench_a, opp_bench_b]
        )
        team_lookup[record["team_id"]] = {
            "id": record["team_id"], "pokemon": team,
        }
        team_lookup[record["opponent_team_id"]] = {
            "id": record["opponent_team_id"], "pokemon": opp,
        }
    inputs["team_lookup"] = team_lookup
    return inputs


# ---------------------------------------------------------------------------
# Plan evaluation
# ---------------------------------------------------------------------------


@dataclass
class PlanScore:
    plan: Dict[str, Any]
    v2j_score: float
    eval_obj: Any


def _evaluate_plan(
    team_pokemon: Sequence[Mapping[str, Any]],
    opponent_pokemon: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any],
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
    """Build per-pair evaluation bundles keyed by ``pair_id``.

    The merge is by ``pair_id``, not row position. The V3 plan
    and Random plan are loaded from the row's plan fields
    (which the upstream ``build_pair_records`` populated from
    the preview rows' ``player_policy`` field).
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
# Statistics helpers (independent + paired)
# ---------------------------------------------------------------------------


def _summarise(values: Sequence[float]) -> Dict[str, float]:
    if not values:
        return {
            "n": 0, "mean": 0.0, "median": 0.0, "min": 0.0,
            "p10": 0.0, "p90": 0.0, "max": 0.0,
        }
    ordered = sorted(float(v) for v in values)
    n = len(ordered)
    mean = sum(ordered) / n
    median = (
        ordered[n // 2]
        if n % 2 == 1
        else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    )
    p10 = _percentile(ordered, 0.10)
    p90 = _percentile(ordered, 0.90)
    return {
        "n": n,
        "mean": mean,
        "median": median,
        "min": ordered[0],
        "p10": p10,
        "p90": p90,
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


def _bootstrap_independent_mean_diff_ci(
    a: Sequence[float],
    b: Sequence[float],
    n_resamples: int = N_BOOTSTRAP,
    alpha: float = 0.05,
    seed: int = BOOTSTRAP_SEED,
) -> Optional[Tuple[float, float, float]]:
    """Independent (unpaired) bootstrap CI of mean(a) - mean(b).

    Returns ``(observed_diff, lo, hi)`` or ``None`` when the
    inputs are degenerate (empty or single-element).
    """
    if not a or not b:
        return None
    if len(a) < 2 or len(b) < 2:
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
    """Paired bootstrap CI of mean(a - b) for matched samples.

    Returns ``None`` when ``len(a) != len(b)`` or any input is
    empty.
    """
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


def _ci_present(
    ci: Optional[Tuple[float, float, float]]
) -> bool:
    return ci is not None


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
    return (statistics.fmean(a) - statistics.fmean(b)) / math.sqrt(
        pooled_var
    )


def _loo_stability(values: Sequence[float]) -> float:
    """Backward-compatible LOO stability for one group of
    positive-only values. New code should use
    :func:`_loo_stability_difference` for the proper
    between-group difference statistic. Kept for callers
    that only have one group.
    """
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


# Frozen signal-stability margin. When the absolute
# between-group difference ``|D_full|`` is below this
# threshold, the signal is treated as effectively zero
# and the stability gates (LOO / fold / not-driven-by-one)
# report 0 / False. The margin is large enough to
# absorb the floating-point residuals that ``1 if d > 0
# else -1`` would otherwise assign a sign to. A 30-
# element group whose mean differs from a 25-element
# group by 1e-5 is a numerical artifact, not a signal.
# Without a non-trivial margin, the spec's "D = 0
# must fail the gate" rule is bypassed by a small
# residual.
SIGNAL_MARGIN: float = 1e-5


def _sign_with_margin(value: float) -> int:
    """Return the sign of ``value`` with a margin guard.

    - 1  when ``value > SIGNAL_MARGIN``
    - -1 when ``value < -SIGNAL_MARGIN``
    - 0  when ``|value| <= SIGNAL_MARGIN``

    The function is the single sign oracle used by the
    LOO, fold, and not-driven-by-one stability checks.
    Every comparison (``D_full``, ``D_i``, ``D_k``,
    ``D_j``) must use this helper so a near-zero
    residual is treated as "unresolved" rather than
    being coerced to the negative sign by a floating-
    point tie-break.

    V2k.4 — the spec requires the SAME helper be used
    for every stability check, not only for the full
    statistic.
    """
    if value > SIGNAL_MARGIN:
        return 1
    if value < -SIGNAL_MARGIN:
        return -1
    return 0


def _loo_stability_difference(
    group_a: Sequence[float],
    group_b: Sequence[float],
) -> float:
    """Leave-one-out stability of the between-group
    difference statistic.

    D_full = mean(group_a) - mean(group_b).

    We remove one observation at a time:

    - From group A (rest_a = group_a without element i)
    - From group B (rest_b = group_b without element j)

    For each omission, recompute D_i = mean(rest_a) - mean(rest_b).
    The omission matches the full statistic if D_i has the
    same SIGN as D_full. A D_full whose absolute value is
    below :data:`SIGNAL_MARGIN` is treated as effectively
    zero (the floating-point residual carries no signal)
    and the gate returns 0.0 — NOT a stable negative
    difference. The spec forbids treating a zero signal as
    a stable negative one.

    V2k.4 — the same :func:`_sign_with_margin` helper is
    used for D_full, D_i, and D_j so a near-zero D_i
    (``|D_i| < SIGNAL_MARGIN``) is treated as "no
    match" rather than a stable negative sign. Without
    this, D_i = 0 would be coerced to sign -1 by the
    raw ``1 if d > 0 else -1`` pattern and counted as
    a match when D_full is negative.

    Returns
    -------
    float
        Fraction of A+B omissions whose signed
        :func:`_sign_with_margin` matches the full
        statistic sign. Returns 0.0 if either group has
        fewer than 2 elements or D_full is below the
        :data:`SIGNAL_MARGIN`.
    """
    if len(group_a) < 2 or len(group_b) < 2:
        return 0.0
    mean_a = statistics.fmean(group_a)
    mean_b = statistics.fmean(group_b)
    d_full = mean_a - mean_b
    if abs(d_full) < SIGNAL_MARGIN:
        # Full difference is effectively zero (degenerate
        # signal). The stability check cannot be defined
        # against a zero reference sign; treat as 0.0.
        # Crucially, the sign of 0 is NOT propagated to
        # the omission checks.
        return 0.0
    full_sign = _sign_with_margin(d_full)
    if full_sign == 0:
        # Defensive: D_full is non-zero in absolute
        # value but the helper still considers it
        # unresolved. Treat as 0.0.
        return 0.0
    matches = 0
    total = 0
    # Omit one from A.
    for i in range(len(group_a)):
        rest_a = [v for j, v in enumerate(group_a) if j != i]
        if not rest_a:
            continue
        d_i = statistics.fmean(rest_a) - mean_b
        sign_i = _sign_with_margin(d_i)
        total += 1
        # Match requires a defined sign on BOTH the
        # full statistic and the omission. An omission
        # with sign 0 (near-zero D_i) is NOT a match —
        # the residual does not have the full statistic
        # sign.
        if sign_i == full_sign:
            matches += 1
    # Omit one from B.
    for j in range(len(group_b)):
        rest_b = [v for k, v in enumerate(group_b) if k != j]
        if not rest_b:
            continue
        d_j = mean_a - statistics.fmean(rest_b)
        sign_j = _sign_with_margin(d_j)
        total += 1
        if sign_j == full_sign:
            matches += 1
    return matches / total if total else 0.0


def _fold_stability(
    values: Sequence[float], n_folds: int = 5
) -> Tuple[float, List[str]]:
    """Backward-compatible per-fold stability for one group
    of values. New code should use
    :func:`_fold_stability_difference` for the proper
    between-group difference statistic.
    """
    if len(values) < n_folds:
        return 0.0, ["n/a"] * len(values)
    full_mean = statistics.fmean(values)
    full_sign = 1 if full_mean >= 0 else -1
    # Do NOT sort values. The fold assignment is
    # deterministic by row order. Sorting would mix the
    # values across folds and destroy the assignment
    # invariant. The spec requires deterministic
    # assignment using the frozen seed.
    ordered = [float(v) for v in values]
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


def _fallback_observation_ids(values: Sequence[float]) -> List[str]:
    """Build order-invariant identities when pair IDs are unavailable."""
    sorted_values = sorted(float(value) for value in values)
    occurrences: Dict[str, int] = {}
    identities: List[str] = []
    for value in sorted_values:
        value_key = format(value, ".17g")
        occurrence = occurrences.get(value_key, 0)
        occurrences[value_key] = occurrence + 1
        identities.append(f"value:{value_key}:occurrence:{occurrence}")
    return identities


def _balanced_fold_assignment(
    observation_ids: Sequence[Any],
    n_folds: int,
    seed: int,
) -> Dict[str, int]:
    """Assign stable identities to balanced deterministic folds."""
    if n_folds <= 0:
        raise ValueError("n_folds must be positive")
    normalized = [str(value) for value in observation_ids]
    if len(set(normalized)) != len(normalized):
        raise ValueError("observation_ids must be unique")
    ranked = sorted(
        normalized,
        key=lambda value: hashlib.sha256(
            f"{seed}:{value}".encode("utf-8")
        ).digest(),
    )
    return {
        observation_id: index % n_folds
        for index, observation_id in enumerate(ranked)
    }


def _fold_stability_difference(
    group_a: Sequence[float],
    group_b: Sequence[float],
    n_folds: int = 5,
    seed: int = BOOTSTRAP_SEED,
    group_a_ids: Optional[Sequence[Any]] = None,
    group_b_ids: Optional[Sequence[Any]] = None,
) -> Tuple[float, List[float], List[str], List[str]]:
    """Five-fold stability of the between-group difference
    statistic.

    D_full = mean(group_a) - mean(group_b).

    V2k.5 assigns each observation from its stable identity.
    Production passes ``pair_id`` values. The identities are
    hash-ranked with the frozen seed and distributed round-robin,
    so all folds are populated when each group has enough rows.

    For each fold index ``k``:

    - rest_a = all of group_a EXCEPT values whose
      fold index is ``k``
    - rest_b = all of group_b EXCEPT values whose
      fold index is ``k``
    - D_k = mean(rest_a) - mean(rest_b)

    ``D_full`` whose absolute value is below
    :data:`SIGNAL_MARGIN` fails the gate: stability is
    not defined against a zero reference sign.
    """
    if len(group_a) < n_folds or len(group_b) < n_folds:
        return (
            0.0,
            [],
            ["n/a"] * n_folds,
            ["n/a"] * n_folds,
        )
    mean_a_full = statistics.fmean(group_a)
    mean_b_full = statistics.fmean(group_b)
    d_full = mean_a_full - mean_b_full
    if abs(d_full) < SIGNAL_MARGIN:
        return (
            0.0,
            [],
            ["n/a"] * n_folds,
            ["n/a"] * n_folds,
        )
    full_sign = _sign_with_margin(d_full)
    if full_sign == 0:
        return (
            0.0,
            [],
            ["n/a"] * n_folds,
            ["n/a"] * n_folds,
        )
    if group_a_ids is None:
        a_values = sorted(float(value) for value in group_a)
        a_ids = _fallback_observation_ids(a_values)
    else:
        a_values = [float(value) for value in group_a]
        a_ids = [str(value) for value in group_a_ids]
    if group_b_ids is None:
        b_values = sorted(float(value) for value in group_b)
        b_ids = _fallback_observation_ids(b_values)
    else:
        b_values = [float(value) for value in group_b]
        b_ids = [str(value) for value in group_b_ids]
    if len(a_ids) != len(group_a) or len(b_ids) != len(group_b):
        raise ValueError("fold identity and value lengths must match")
    a_pairs = list(zip(a_ids, a_values))
    b_pairs = list(zip(b_ids, b_values))
    fold_of_a = _balanced_fold_assignment(a_ids, n_folds, seed)
    fold_of_b = _balanced_fold_assignment(b_ids, n_folds, seed + 1)
    fold_diffs: List[float] = []
    fold_signs_a: List[str] = []
    fold_signs_b: List[str] = []
    stable_fold_count = 0
    for k in range(n_folds):
        rest_a = [
            value for identity, value in a_pairs
            if fold_of_a[identity] != k
        ]
        rest_b = [
            value for identity, value in b_pairs
            if fold_of_b[identity] != k
        ]
        if not rest_a or not rest_b:
            continue
        d_k = statistics.fmean(rest_a) - statistics.fmean(rest_b)
        fold_diffs.append(d_k)
        # V2k.4 — use the same :func:`_sign_with_margin`
        # helper for D_k and the per-group means so a
        # near-zero D_k is treated as "no match" rather
        # than a stable sign.
        sign_k = _sign_with_margin(d_k)
        sign_a = _sign_with_margin(statistics.fmean(rest_a))
        sign_b = _sign_with_margin(statistics.fmean(rest_b))
        fold_signs_a.append(
            "+" if sign_a == 1 else ("-" if sign_a == -1 else "?")
        )
        fold_signs_b.append(
            "+" if sign_b == 1 else ("-" if sign_b == -1 else "?")
        )
        if sign_k == full_sign:
            stable_fold_count += 1
    return (
        stable_fold_count,
        fold_diffs,
        fold_signs_a,
        fold_signs_b,
    )


def _not_driven_by_one(
    values: Sequence[float],
    labels: Sequence[str],
) -> bool:
    """Backward-compatible not-driven-by-one check on one
    group of values. New code should use
    :func:`_not_driven_by_one_difference` for the proper
    between-group difference statistic.
    """
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


def _not_driven_by_one_difference(
    group_a: Sequence[float],
    group_b: Sequence[float],
) -> bool:
    """Not-driven-by-one stability of the between-group
    difference statistic.

    D_full = mean(group_a) - mean(group_b).

    For every element in group_a, recompute D with that
    element removed. For every element in group_b,
    recompute D with that element removed. The gate
    passes only if NO single removal flips the sign of
    D from the full-D sign. ``D_full`` whose absolute
    value is below :data:`SIGNAL_MARGIN` MUST fail this
    gate (a near-zero signal carries no useful sign to
    anchor against; a tiny positive residual is
    floating-point noise, NOT a stable positive
    difference).

    V2k.4 — the same :func:`_sign_with_margin` helper is
    used for D_i / D_j so a near-zero omission is
    treated as "not matching" rather than being
    coerced to the negative sign.
    """
    if len(group_a) < 2 or len(group_b) < 2:
        return False
    mean_a = statistics.fmean(group_a)
    mean_b = statistics.fmean(group_b)
    d_full = mean_a - mean_b
    if abs(d_full) < SIGNAL_MARGIN:
        return False
    full_sign = _sign_with_margin(d_full)
    if full_sign == 0:
        return False
    # Omit one from A.
    for i in range(len(group_a)):
        rest_a = [v for j, v in enumerate(group_a) if j != i]
        if not rest_a:
            continue
        d_i = statistics.fmean(rest_a) - mean_b
        if _sign_with_margin(d_i) != full_sign:
            return False
    # Omit one from B.
    for j in range(len(group_b)):
        rest_b = [v for k, v in enumerate(group_b) if k != j]
        if not rest_b:
            continue
        d_j = mean_a - statistics.fmean(rest_b)
        if _sign_with_margin(d_j) != full_sign:
            return False
    return True


# ---------------------------------------------------------------------------
# Component gate evaluation
# ---------------------------------------------------------------------------


GATE_NAMES: Tuple[str, ...] = (
    "decisive_support_ge_20",
    "between_group_bootstrap_ci_excludes_zero",
    "within_failure_paired_bootstrap_ci_excludes_zero",
    "between_within_direction_agree",
    "loo_stability_ge_90pct",
    "fold_stability_ge_4_of_5",
    "unknown_rate_le_10pct",
    "not_driven_by_one",
)


def evaluate_component(
    component: str,
    v3_both_values: Sequence[float],
    v3_in_random_both_values: Sequence[float],
    random_in_random_both_values: Sequence[float],
    v3_both_unknown_rates: Sequence[float],
    v3_both_pair_ids: Optional[Sequence[Any]] = None,
    random_both_pair_ids: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Run the strict actionable gate for one component.

    Inputs
    ------
    component
        Component name.
    v3_both_values
        V3 plan's per-component means on the 30 v3_both
        pairs (the WINNING V3 plan, evaluated on the team
        pair that won both D1 and D2).
    v3_in_random_both_values
        V3 plan's per-component means on the 25
        random_both pairs (the LOSING V3 plan, evaluated on
        the team pair that lost both D1 and D2).
    random_in_random_both_values
        Random plan's per-component means on the 25
        random_both pairs (the WINNING Random plan, on the
        same losing team pair).
    v3_both_unknown_rates
        Per-pair unknown rates for the 30 v3_both pairs
        only.

    Definitions
    -----------
    between_mean
        mean(v3_both_values) - mean(v3_in_random_both_values).
        This is the actual between-group difference. It
        MUST equal ``between_bootstrap_ci[0]`` and the
        direction-agreement sign MUST use this difference,
        not the raw v3_both mean.
    within_mean
        mean of the per-pair V3 - Random differences on the
        25 random_both pairs. The within-failure paired
        bootstrap is called on the matched (v3, random)
        arrays, NOT on a hand-rolled one-sample bootstrap
        of pre-computed differences.
    between_sign / within_sign
        signs of the two actual differences.
    """
    gates: Dict[str, bool] = {}
    gate_reasons: Dict[str, str] = {}

    # ---- Decisive support ----
    n_v3_both = len(v3_both_values)
    n_v3_in_random = len(v3_in_random_both_values)
    n_random_in_random = len(random_in_random_both_values)
    n_within = min(n_v3_in_random, n_random_in_random)
    gates["decisive_support_ge_20"] = n_v3_both >= 20
    if n_v3_both < 20:
        gate_reasons["decisive_support_ge_20"] = (
            f"v3_both_n={n_v3_both} < 20"
        )

    # ---- Between-group: independent bootstrap on the
    # ACTUAL group difference ----
    between_ci = _bootstrap_independent_mean_diff_ci(
        v3_both_values, v3_in_random_both_values,
    )
    if between_ci is None:
        gates["between_group_bootstrap_ci_excludes_zero"] = False
        gate_reasons["between_group_bootstrap_ci_excludes_zero"] = (
            "missing_ci: between-group arrays are degenerate "
            "(empty or < 2 elements each)"
        )
        between_observed = 0.0
    else:
        between_observed = float(between_ci[0])
        gates["between_group_bootstrap_ci_excludes_zero"] = (
            _ci_excludes_zero(between_ci)
        )
        if not _ci_excludes_zero(between_ci):
            gate_reasons[
                "between_group_bootstrap_ci_excludes_zero"
            ] = (
                f"ci covers zero: "
                f"[{between_ci[1]:+.3f}, {between_ci[2]:+.3f}]"
            )

    # ---- Within-failure: PAIRED bootstrap on matched
    # (v3, random) arrays directly ----
    # The V3 plan's value and the Random plan's value are
    # both taken on the same pair. Call the shared paired
    # bootstrap with the two raw arrays. UNEQUAL LENGTHS
    # are a hard failure: a partial pairing would silently
    # misalign which pair is compared to which.
    if (
        len(v3_in_random_both_values)
        != len(random_in_random_both_values)
    ):
        gates["within_failure_paired_bootstrap_ci_excludes_zero"] = False
        gate_reasons["within_failure_paired_bootstrap_ci_excludes_zero"] = (
            f"hard_fail: paired arrays have unequal lengths "
            f"(v3_n={len(v3_in_random_both_values)}, "
            f"random_n={len(random_in_random_both_values)})"
        )
        within_observed = 0.0
        within_ci = None
    else:
        within_ci = _bootstrap_paired_mean_diff_ci(
            v3_in_random_both_values, random_in_random_both_values,
        )
        if within_ci is None:
            gates["within_failure_paired_bootstrap_ci_excludes_zero"] = False
            gate_reasons["within_failure_paired_bootstrap_ci_excludes_zero"] = (
                "missing_ci: within-failure paired arrays are degenerate "
                "(empty)"
            )
            within_observed = 0.0
        else:
            within_observed = float(within_ci[0])
            gates["within_failure_paired_bootstrap_ci_excludes_zero"] = (
                _ci_excludes_zero(within_ci)
            )
            if not _ci_excludes_zero(within_ci):
                gate_reasons[
                    "within_failure_paired_bootstrap_ci_excludes_zero"
                ] = (
                    f"ci covers zero: "
                    f"[{within_ci[1]:+.3f}, {within_ci[2]:+.3f}]"
            )

    # ---- Direction agreement: sign of the actual
    # between-group difference vs the actual within-failure
    # paired difference ----
    # Use the canonical :func:`_sign_with_margin` helper
    # so a near-zero residual is treated as unresolved
    # (the sign is undefined) rather than being
    # propagated as a positive or negative sign based
    # on a floating-point tie-break. The same helper is
    # used by the LOO / fold / not-driven-by-one gates
    # and by the direction-agreement gate to keep the
    # sign definition consistent across all stability
    # checks.
    between_sign = _sign_with_margin(between_observed)
    within_sign = _sign_with_margin(within_observed)
    # Direction agreement: both signs must be defined
    # AND must match. A zero / unresolved sign in
    # either side fails the agreement gate (no
    # direction to agree on).
    gates["between_within_direction_agree"] = (
        between_sign != 0
        and within_sign != 0
        and between_sign == within_sign
    )
    if not gates["between_within_direction_agree"]:
        gate_reasons["between_within_direction_agree"] = (
            f"between_sign={between_sign:+d}, "
            f"within_sign={within_sign:+d} "
            f"(between={between_observed:+.4f}, "
            f"within={within_observed:+.4f})"
        )

    # ---- LOO / fold stability (V2k.2 — difference-based) ----
    # The LOO/fold/not-driven-by-one gates operate on the
    # ACTUAL between-group difference statistic:
    #   D = mean(v3_both_values) - mean(v3_in_random_both_values)
    # Removing one observation from group A or B
    # recomputes D from the remaining observations. The
    # full statistic's sign is the reference; a D_full of
    # exactly zero fails the gate (no nonzero reference).
    if n_v3_both >= 2 and n_v3_in_random >= 2:
        loo_stab = _loo_stability_difference(
            v3_both_values, v3_in_random_both_values,
        )
        # >= 90% of A+B omissions have the same sign as
        # the full statistic.
        gates["loo_stability_ge_90pct"] = loo_stab >= 0.9
        if not gates["loo_stability_ge_90pct"]:
            gate_reasons["loo_stability_ge_90pct"] = (
                f"loo_sign_match={loo_stab:.3f} < 0.9 "
                f"(between_diff={between_observed:+.4f})"
            )
    else:
        gates["loo_stability_ge_90pct"] = False
        gate_reasons["loo_stability_ge_90pct"] = (
            f"insufficient n: v3_both_n={n_v3_both}, "
            f"v3_in_random_n={n_v3_in_random} (need >= 2 each)"
        )

    if n_v3_both >= 5 and n_v3_in_random >= 5:
        stable_fold_count, fold_diffs, fold_signs_a, fold_signs_b = (
            _fold_stability_difference(
                v3_both_values, v3_in_random_both_values,
                n_folds=5,
                group_a_ids=v3_both_pair_ids,
                group_b_ids=random_both_pair_ids,
            )
        )
        # >= 4 of 5 fold differences share the full-stat
        # sign. fold_stability_ge_4_of_5 == True iff
        # stable_fold_count >= 4.
        gates["fold_stability_ge_4_of_5"] = (
            stable_fold_count >= 4
        )
        if not gates["fold_stability_ge_4_of_5"]:
            gate_reasons["fold_stability_ge_4_of_5"] = (
                f"stable_folds={stable_fold_count}/5 "
                f"(between_diff={between_observed:+.4f}); "
                f"fold_diffs={[f'{d:+.3f}' for d in fold_diffs]}"
            )
    else:
        gates["fold_stability_ge_4_of_5"] = False
        gate_reasons["fold_stability_ge_4_of_5"] = (
            f"insufficient n: v3_both_n={n_v3_both}, "
            f"v3_in_random_n={n_v3_in_random} (need >= 5 each)"
        )

    # ---- Unknown rate ----
    if v3_both_unknown_rates:
        mean_unknown = statistics.fmean(v3_both_unknown_rates)
    else:
        mean_unknown = 1.0
    gates["unknown_rate_le_10pct"] = mean_unknown <= 0.10
    if not gates["unknown_rate_le_10pct"]:
        gate_reasons["unknown_rate_le_10pct"] = (
            f"mean_unknown_rate={mean_unknown:.3f} > 0.10"
        )

    # ---- Not driven by one outlier (V2k.2 — difference
    # statistic). Remove every single element from each
    # group; the gate passes only if NO removal flips the
    # full-D sign. Full D = 0 MUST fail this gate. ----
    not_driven = _not_driven_by_one_difference(
        v3_both_values, v3_in_random_both_values,
    )
    gates["not_driven_by_one"] = not_driven
    if not not_driven:
        gate_reasons["not_driven_by_one"] = (
            f"between_diff={between_observed:+.4f}: a single "
            f"element removal flips the sign (or D is "
            f"exactly zero)."
        )

    return {
        "component": component,
        "n_v3_both": n_v3_both,
        "n_v3_in_random_both": n_v3_in_random,
        "n_random_in_random_both": n_random_in_random,
        "n_within": n_within,
        # Aliases for back-compat with the test surface and
        # the markdown renderer.
        "n_random_both": n_v3_in_random,
        "between_mean": float(between_observed),
        "within_mean": float(within_observed),
        "between_sign": (
            "+" if between_sign == 1 else
            ("-" if between_sign == -1 else "?")
        ),
        "within_sign": (
            "+" if within_sign == 1 else
            ("-" if within_sign == -1 else "?")
        ),
        "between_bootstrap_ci": between_ci,
        "within_bootstrap_ci": within_ci,
        "loo_stability": loo_stab if (
            n_v3_both >= 2 and n_v3_in_random >= 2
        ) else 0.0,
        "fold_stability": (
            float(stable_fold_count) if (
                n_v3_both >= 5 and n_v3_in_random >= 5
            ) else 0.0
        ),
        "fold_diffs": (
            fold_diffs if (
                n_v3_both >= 5 and n_v3_in_random >= 5
            ) else []
        ),
        "fold_signs_a": (
            fold_signs_a if (
                n_v3_both >= 5 and n_v3_in_random >= 5
            ) else []
        ),
        "fold_signs_b": (
            fold_signs_b if (
                n_v3_both >= 5 and n_v3_in_random >= 5
            ) else []
        ),
        "mean_unknown_rate": float(mean_unknown),
        "gates": gates,
        "gate_reasons": gate_reasons,
        "candidate_actionable": all(gates.values()),
    }


# ---------------------------------------------------------------------------
# Run analysis
# ---------------------------------------------------------------------------


def _safe_run(
    inputs: Mapping[str, Any],
    evidence_mode: str = "real",
    real_artifact_paths: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
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
    v3_both_pairs = [p for p in decisive_pairs if classify_pair(p) == "v3_both"]
    random_both_pairs = [
        p for p in decisive_pairs if classify_pair(p) == "random_both"
    ]

    feature_keys = [spec.name for spec in COMPONENT_SPECS]

    # Per-component means:
    # - v3_both_components:  V3 plan values on v3_both pairs (n=30)
    # - v3_in_random_both_components: V3 plan values on random_both
    #   pairs (n=25) — the LOSING V3 plan.
    # - random_in_random_both_components: Random plan values on
    #   random_both pairs (n=25) — the WINNING Random plan.
    # - within_failure_components: V3 - Random differences on
    #   random_both pairs (n=25).
    v3_both_components: Dict[str, List[float]] = {
        k: [] for k in feature_keys
    }
    v3_in_random_both_components: Dict[str, List[float]] = {
        k: [] for k in feature_keys
    }
    random_in_random_both_components: Dict[str, List[float]] = {
        k: [] for k in feature_keys
    }
    within_components: Dict[str, List[float]] = {
        k: [] for k in feature_keys
    }
    split_components: Dict[str, List[float]] = {
        k: [] for k in feature_keys
    }
    v3_both_unknown_rates: List[float] = []
    v3_both_pair_ids: List[int] = []
    random_both_pair_ids: List[int] = []
    pair_labels: List[str] = []

    for pair in v3_both_pairs:
        pair_id = int(pair.get("pair_id", -1))
        bundle = bundles_by_pair_dict.get(pair_id)
        if not bundle:
            continue
        v3_eval = bundle["v3"].eval_obj
        v3_both_unknown_rates.append(
            v3_eval.uncertainty.get("unknown_rate", 0.0)
        )
        v3_both_pair_ids.append(pair_id)
        pair_labels.append(f"pair_{pair_id}_v3_both")
        for k in feature_keys:
            v3_both_components[k].append(
                v3_eval.component_means.get(k, 0.0)
            )

    for pair in random_both_pairs:
        pair_id = int(pair.get("pair_id", -1))
        bundle = bundles_by_pair_dict.get(pair_id)
        if not bundle:
            continue
        v3_eval = bundle["v3"].eval_obj
        rnd_eval = bundle["random"].eval_obj
        random_both_pair_ids.append(pair_id)
        pair_labels.append(f"pair_{pair_id}_random_both")
        for k in feature_keys:
            v3_in_random_both_components[k].append(
                v3_eval.component_means.get(k, 0.0)
            )
            random_in_random_both_components[k].append(
                rnd_eval.component_means.get(k, 0.0)
            )
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

    gate_table: List[Dict[str, Any]] = []
    for k in feature_keys:
        result = evaluate_component(
            k,
            v3_both_components[k],
            v3_in_random_both_components[k],
            random_in_random_both_components[k],
            v3_both_unknown_rates,
            v3_both_pair_ids,
            random_both_pair_ids,
        )
        gate_table.append(result)

    actionable = [r for r in gate_table if r["candidate_actionable"]]
    contradictory = [
        r for r in gate_table
        if r["gates"]["between_group_bootstrap_ci_excludes_zero"]
        and not r["gates"]["between_within_direction_agree"]
    ]

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

    v3_both_summary = {
        k: _summarise(v3_both_components[k]) for k in feature_keys
    }
    v3_in_random_both_summary = {
        k: _summarise(v3_in_random_both_components[k])
        for k in feature_keys
    }
    random_in_random_both_summary = {
        k: _summarise(random_in_random_both_components[k])
        for k in feature_keys
    }
    within_summary = {
        k: _summarise(within_components[k]) for k in feature_keys
    }
    split_summary = {
        k: _summarise(split_components[k]) for k in feature_keys
    }

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

    # Real-artifact / freeze-proof gates. The gate passes
    # only when ALL six conditions are satisfied (V2k.2):
    #   1. evidence_mode == "real"
    #   2. first_outcome_load_unix is non-null
    #   3. freeze_time_unix < first_outcome_load_unix
    #   4. all three validated artifact paths exist
    #   5. exact counts: 200 benchmark rows, 200 JSONL
    #      records, 400 preview rows
    #   6. pair-record shape: 100 complete pairs
    #      (v3_both=30, random_both=25, split=45,
    #      decisive=55)
    # bool(real_artifact_paths) alone is NOT sufficient.
    real_artifact_proof: Dict[str, Any] = {
        "evidence_mode": evidence_mode,
        "frozen_before_outcomes": proof["frozen_before_outcomes"],
        "freeze_time_unix": proof["freeze_time_unix"],
        "first_outcome_load_unix": proof["first_outcome_load_unix"],
        "elapsed_seconds": proof[
            "elapsed_between_freeze_and_first_load_seconds"
        ],
        "real_artifact_paths": real_artifact_paths or {},
    }

    real_gate_reasons: List[str] = []

    if evidence_mode != "real":
        real_gate_reasons.append(
            f"evidence_mode={evidence_mode!r} != 'real'"
        )
    if proof["first_outcome_load_unix"] is None:
        real_gate_reasons.append(
            "first_outcome_load_unix is None"
        )
    elif not proof["frozen_before_outcomes"]:
        real_gate_reasons.append(
            f"freeze_time_unix={proof['freeze_time_unix']:.6f} "
            f"not < first_outcome_load_unix="
            f"{proof['first_outcome_load_unix']:.6f}"
        )
    if not real_artifact_paths:
        real_gate_reasons.append(
            "real_artifact_paths is empty"
        )
    else:
        # Condition 4: all three artifact paths exist.
        for path_key in (
            "benchmark_csv",
            "preview_evidence_csv",
            "benchmark_jsonl",
        ):
            if path_key not in real_artifact_paths:
                real_gate_reasons.append(
                    f"missing artifact path: {path_key}"
                )
                continue
            info = real_artifact_paths[path_key]
            if not info.get("exists"):
                real_gate_reasons.append(
                    f"artifact {path_key} does not exist: "
                    f"{info.get('path')}"
                )
        # Condition 5: exact counts.
        bench_csv_info = real_artifact_paths.get("benchmark_csv", {})
        prev_csv_info = real_artifact_paths.get(
            "preview_evidence_csv", {}
        )
        jsonl_info = real_artifact_paths.get("benchmark_jsonl", {})
        if bench_csv_info.get("data_rows") != 200:
            real_gate_reasons.append(
                f"benchmark_csv data_rows="
                f"{bench_csv_info.get('data_rows')} != 200"
            )
        if prev_csv_info.get("data_rows") != 400:
            real_gate_reasons.append(
                f"preview_evidence_csv data_rows="
                f"{prev_csv_info.get('data_rows')} != 400"
            )
        if jsonl_info.get("record_count") != 200:
            real_gate_reasons.append(
                f"benchmark_jsonl record_count="
                f"{jsonl_info.get('record_count')} != 200"
            )
    # Condition 6: pair-record shape. The decisive +
    # split counts are reported by the analyzer.
    pair_total = (
        len(v3_both_pairs) + len(random_both_pairs) + len(split_pairs)
    )
    if pair_total != 100:
        real_gate_reasons.append(
            f"pair_total={pair_total} != 100"
        )
    if len(v3_both_pairs) != 30:
        real_gate_reasons.append(
            f"v3_both_n={len(v3_both_pairs)} != 30"
        )
    if len(random_both_pairs) != 25:
        real_gate_reasons.append(
            f"random_both_n={len(random_both_pairs)} != 25"
        )
    if len(split_pairs) != 45:
        real_gate_reasons.append(
            f"split_n={len(split_pairs)} != 45"
        )
    if len(decisive_pairs) != 55:
        real_gate_reasons.append(
            f"decisive_n={len(decisive_pairs)} != 55"
        )

    real_gate = len(real_gate_reasons) == 0
    real_artifact_proof["real_freeze_gate_passed"] = real_gate
    real_artifact_proof["real_freeze_gate_reasons"] = (
        real_gate_reasons
    )

    return {
        "decisive_n": len(decisive_pairs),
        "v3_both_n": len(v3_both_pairs),
        "random_both_n": len(random_both_pairs),
        "split_n": len(split_pairs),
        "sign_test": sign_stats,
        "v3_both_summary": v3_both_summary,
        "v3_in_random_both_summary": v3_in_random_both_summary,
        "random_in_random_both_summary": random_in_random_both_summary,
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
        "real_artifact_proof": real_artifact_proof,
    }


def run_analysis(
    inputs: Mapping[str, Any],
    evidence_mode: str = "real",
    real_artifact_paths: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return _safe_run(inputs, evidence_mode, real_artifact_paths)


# ---------------------------------------------------------------------------
# Render markdown
# ---------------------------------------------------------------------------


def _gate_check(gate_value: bool) -> str:
    return "PASS" if gate_value else "FAIL"


def _fmt_ci(ci: Optional[Tuple[float, float, float]]) -> str:
    if ci is None:
        return "n/a"
    return f"[{ci[1]:+.3f}, {ci[2]:+.3f}]"


def render_markdown(report: Mapping[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Phase V2k — Lead Matchup Evaluator v3 (Repaired)")
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
    rap = report.get("real_artifact_proof", {})
    lines.append("## Real-artifact proof")
    lines.append("")
    lines.append(f"- Evidence mode: **{rap.get('evidence_mode')}**")
    lines.append(
        f"- Real-freeze gate passed: "
        f"**{rap.get('real_freeze_gate_passed')}**"
    )
    paths = rap.get("real_artifact_paths", {}) or {}
    if paths:
        for k, v in paths.items():
            lines.append(f"- {k}: `{v}`")
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
        "| Component | n_v3_both | n_random | between | within | "
        "between-CI | within-CI | LOO | Fold | Unknown | Reason | Actionable |"
    )
    lines.append(
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for row in report["gate_table"]:
        gates = row["gates"]
        reason_text = "; ".join(
            f"{k}:{v[:40]}" for k, v in row["gate_reasons"].items()
        )
        # V2k.2: loo_stability is now a fraction in
        # [0, 1] (not a mean of one-group stabilities);
        # fold_stability is a count in [0, 5].
        loo_disp = f"{row['loo_stability']:.3f}"
        fold_disp = f"{int(row['fold_stability'])}/5"
        lines.append(
            f"| {row['component']} | {row['n_v3_both']} | "
            f"{row['n_random_both']} | "
            f"{row['between_mean']:+.3f} | {row['within_mean']:+.3f} | "
            f"{_fmt_ci(row['between_bootstrap_ci'])} | "
            f"{_fmt_ci(row['within_bootstrap_ci'])} | "
            f"{loo_disp} | {fold_disp} | "
            f"{_gate_check(gates['unknown_rate_le_10pct'])} | "
            f"{reason_text or '-'} | "
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
    json_name: str = "vgc2026_phaseV2k_lead_matchups.json",
    md_name: str = "vgc2026_phaseV2k_lead_matchups.md",
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


def _summarise_artifact(path: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not info["exists"]:
        return info
    info["size_bytes"] = path.stat().st_size
    return info


def _validate_artifact(
    logs_dir: Path, prefix: str
) -> Tuple[bool, Dict[str, Any]]:
    """Verify the V2f artifact prefix is real and complete.

    Returns ``(is_real, paths)``. ``is_real`` is True only if
    the benchmark CSV, the preview evidence CSV, and the
    benchmark JSONL exist and contain the expected number of
    records (200 / 400 / 200).
    """
    bench_csv = logs_dir / f"{prefix}_benchmark.csv"
    prev_csv = logs_dir / f"{prefix}_preview_evidence.csv"
    bench_jsonl = logs_dir / f"{prefix}_benchmark.jsonl"
    paths = {
        "benchmark_csv": _summarise_artifact(bench_csv),
        "preview_evidence_csv": _summarise_artifact(prev_csv),
        "benchmark_jsonl": _summarise_artifact(bench_jsonl),
    }
    is_real = all(
        v.get("exists") for v in paths.values()
    )
    if is_real:
        # Count data rows.
        with open(bench_csv, "r", encoding="utf-8") as f:
            bench_rows = sum(1 for _ in csv.DictReader(f))
        with open(prev_csv, "r", encoding="utf-8") as f:
            prev_rows = sum(1 for _ in csv.DictReader(f))
        with open(bench_jsonl, "r", encoding="utf-8") as f:
            jsonl_rows = sum(1 for _ in f)
        paths["benchmark_csv"]["data_rows"] = bench_rows
        paths["preview_evidence_csv"]["data_rows"] = prev_rows
        paths["benchmark_jsonl"]["record_count"] = jsonl_rows
        # Sanity: the V2f 100-pair qualification is 200
        # benchmark rows, 400 preview evidence rows, 200
        # JSONL records.
        is_real = (
            bench_rows == 200
            and prev_rows == 400
            and jsonl_rows == 200
        )
    return is_real, paths


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
        help=(
            "Use synthetic inputs (no battle labels required). "
            "Synthetic mode reports evidence_mode=synthetic "
            "and cannot pass real-freeze / qualification "
            "gates."
        ),
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
        # Synthetic path: build inputs, run, write
        # artifacts labelled "synthetic".
        inputs = build_synthetic_inputs()
        report = run_analysis(
            inputs,
            evidence_mode="synthetic",
            real_artifact_paths={},
        )
        json_name = (
            f"vgc2026_phaseV2k_lead_matchups_synthetic.json"
        )
        md_name = (
            f"vgc2026_phaseV2k_lead_matchups_synthetic.md"
        )
        json_path, md_path = write_artifacts(
            report, args.output_dir,
            json_name=json_name, md_name=md_name,
        )
        print(render_markdown(report))
        print(f"JSON: {json_path}")
        print(f"Markdown: {md_path}")
        return 0

    # Real-artifact path. We HARD-FAIL on validation
    # errors and NEVER fall back to synthetic data.
    is_real, real_artifact_paths = _validate_artifact(
        args.logs_dir, args.artifact_prefix,
    )
    if not is_real:
        report_lines = [
            "ERROR: V2f artifact validation failed.",
            f"  logs_dir: {args.logs_dir}",
            f"  artifact_prefix: {args.artifact_prefix}",
            "  real_artifact_paths:",
        ]
        for k, v in real_artifact_paths.items():
            report_lines.append(f"    {k}: {v}")
        report_lines.append(
            "  The analyzer NEVER falls back to synthetic "
            "data when called without --synthetic."
        )
        print("\n".join(report_lines))
        return 2
    benchmark_rows, preview_rows, team_lookup = (
        load_v2f_outcomes_with_freeze_proof(
            args.logs_dir, args.artifact_prefix,
        )
    )
    pair_records = build_pair_records(
        benchmark_rows, preview_rows, team_lookup
    )
    inputs = {
        "pair_records": pair_records,
        "team_lookup": team_lookup,
    }
    report = run_analysis(
        inputs,
        evidence_mode="real",
        real_artifact_paths=real_artifact_paths,
    )
    if not report["real_artifact_proof"]["real_freeze_gate_passed"]:
        # Defense in depth: real_freeze_gate must be True
        # for any real-artifact run.
        print(
            "ERROR: real-freeze gate failed; refusing to "
            "produce a real-artifact report."
        )
        return 3
    json_path, md_path = write_artifacts(
        report, args.output_dir,
        json_name="vgc2026_phaseV2k5_lead_matchups.json",
        md_name="vgc2026_phaseV2k5_lead_matchups.md",
    )
    print(render_markdown(report))
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
