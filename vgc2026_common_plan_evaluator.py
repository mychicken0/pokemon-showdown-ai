#!/usr/bin/env python3
"""
VGC 2026 Common Plan Evaluator

Policy-independent external evaluator for a 4-from-6 preview plan.

The evaluator must:
- be policy-independent (it never calls V2 or V3 scoring functions)
- score the EXACT selected 4/2/2 plan that a policy emits
- use only open team-sheet information (species, ability, moves, types)
- return a structured breakdown with the total, not just a number
- keep weights documented and fixed for all policies
- raise a clear error on malformed plan input

Components (weights are fixed for all policies; see COMPONENT_WEIGHTS):

  offensive_type_coverage    (weight 1.00)
      Sum of normalised STAB-style coverage of the 4 selected against
      the visible opponent types. Higher when the plan hits every
      opponent type super-effectively.

  defensive_weakness_exposure (weight 1.20)
      Average defensive resistance of the 4 selected against the visible
      opponent types. Lower when the plan carries a 4x weakness or two
      shared 2x weaknesses.

  lead_shared_weakness        (weight 1.00)
      Penalty for the two leads sharing a 2x or 4x weakness. Order
      symmetric.

  lead_speed_control_pressure (weight 0.80)
      Reward for the leads having at least one speed-control source
      (Tailwind / Trick Room). Order symmetric.

  fake_out_pressure           (weight 1.00)
      Reward for the leads (or back) carrying Fake Out. Order symmetric
      in component value; capped at the plan total so duplicates do not
      dominate.

  redirection_support         (weight 0.80)
      Reward for Follow Me / Rage Powder / Storm Drain / Lightning Rod
      type redirection in the plan.

  intimidate_support          (weight 0.80)
      Reward for Intimidate in the plan.

  spread_pressure             (weight 0.60)
      Reward for spread-damaging moves (Heat Wave, Earthquake, etc.)
      in the plan.

  protect_utility             (weight 0.15)  # capped low
      Small reward per Protect user. Capped low on purpose: it is
      always useful but should never dominate the score.

  lead_back_role_coverage     (weight 0.80)
      Counts distinct lead roles plus distinct back roles, divided
      by the total possible (8). Order symmetric.

  back_pivot_or_switch        (weight 0.50)
      Reward when the back carries pivot moves (U-turn, Volt Switch,
      Parting Shot, Baton Pass). Two pivots in the back are still
      counted once (see duplicate-role penalty).

  duplicate_role_penalty      (weight 0.40)
      Penalty applied per extra role occurrence beyond the first for
      a fixed role list (fake_out, tailwind, trick_room, redirection,
      intimidate). Prevents the score from being inflated by stacking
      the same narrow support role.

The final total is the weighted sum of the components and is the value
all policy comparisons must use.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from team_preview_policy import (
    TYPE_CHART,
    calculate_type_matchup,
    calculate_weakness_avoidance,
    get_move_category,
    get_ability_category,
    get_species_types,
)


# ---------------------------------------------------------------------------
# Fixed weights. Changing any of these is a V2e.1 schema change, not a tweak.
# ---------------------------------------------------------------------------

COMPONENT_WEIGHTS: Dict[str, float] = {
    "offensive_type_coverage": 1.00,
    "defensive_weakness_exposure": 1.20,
    "lead_shared_weakness": 1.00,
    "lead_speed_control_pressure": 0.80,
    "fake_out_pressure": 1.00,
    "redirection_support": 0.80,
    "intimidate_support": 0.80,
    "spread_pressure": 0.60,
    "protect_utility": 0.15,
    "lead_back_role_coverage": 0.80,
    "back_pivot_or_switch": 0.50,
    "duplicate_role_penalty": 0.40,
}

# Roles that are subject to the duplicate-role penalty. The component
# subtracts (count - 1) * weight * DUPLICATE_ROLE_PENALTY_SCALE per role
# that appears more than once.
DUPLICATE_ROLE_KEYS: Tuple[str, ...] = (
    "fake_out",
    "tailwind",
    "trick_room",
    "redirection",
    "intimidate",
)
DUPLICATE_ROLE_PENALTY_SCALE: float = 1.0

# What counts as a "pivot" for back-switch coverage.
PIVOT_MOVE_KEYWORDS: Tuple[str, ...] = (
    "u-turn",
    "uturn",
    "volt switch",
    "voltswitch",
    "parting shot",
    "baton pass",
)


# ---------------------------------------------------------------------------
# Plan representation
# ---------------------------------------------------------------------------


class CommonPlanEvaluatorError(ValueError):
    """Raised when a plan is malformed in a way that prevents evaluation."""


@dataclass
class CommonPlanScore:
    """Structured breakdown for a single 4-from-6 plan evaluation.

    `total` is the weighted sum of the component values in `components`.
    """

    team_size: int
    chosen_4: List[str]
    lead_2: List[str]
    back_2: List[str]
    opponent_team_size: int
    components: Dict[str, float] = field(default_factory=dict)
    total: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_species(species: str) -> str:
    return str(species).strip().lower()


def _all_attacking_types() -> Iterable[Tuple[str, Dict[str, float]]]:
    return TYPE_CHART.items()


def _composite_multiplier(attacker: str, defender_types: Sequence[str]) -> float:
    multipliers = TYPE_CHART.get(attacker, {})
    combined = 1.0
    for defender in defender_types:
        combined *= multipliers.get(defender, 1.0)
    return combined


def _is_pivot(move_lower: str) -> bool:
    return any(keyword in move_lower for keyword in PIVOT_MOVE_KEYWORDS)


# ---------------------------------------------------------------------------
# Component calculations
# ---------------------------------------------------------------------------


def _offensive_type_coverage(
    selected: Sequence[Mapping[str, Any]],
    opponent_team: Sequence[Mapping[str, Any]],
) -> float:
    """Mean best type matchup the plan can land on the opponent team."""
    if not opponent_team:
        return 0.0
    our_types: List[List[str]] = []
    for pokemon in selected:
        species_types = get_species_types(pokemon.get("species", ""))
        if species_types:
            our_types.append(species_types)
    if not our_types:
        return 0.0
    per_opponent: List[float] = []
    for opponent in opponent_team:
        opp_types = get_species_types(opponent.get("species", ""))
        if not opp_types:
            continue
        best = 0.0
        for our_type_list in our_types:
            best = max(
                best,
                calculate_type_matchup(our_type_list, opp_types),
            )
        per_opponent.append(best)
    if not per_opponent:
        return 0.0
    return sum(per_opponent) / len(per_opponent)


def _defensive_weakness_exposure(
    selected: Sequence[Mapping[str, Any]],
    opponent_team: Sequence[Mapping[str, Any]],
) -> float:
    """Average defensive resistance across the 4 selected against opponents."""
    if not opponent_team:
        return 0.0
    per_pokemon: List[float] = []
    for pokemon in selected:
        our_types = get_species_types(pokemon.get("species", ""))
        if not our_types:
            continue
        opp_matchups: List[float] = []
        for opponent in opponent_team:
            opp_types = get_species_types(opponent.get("species", ""))
            if opp_types:
                opp_matchups.append(
                    calculate_weakness_avoidance(our_types, opp_types)
                )
        if opp_matchups:
            per_pokemon.append(sum(opp_matchups) / len(opp_matchups))
    if not per_pokemon:
        return 0.0
    return sum(per_pokemon) / len(per_pokemon)


def _lead_shared_weakness(leads: Sequence[Mapping[str, Any]]) -> float:
    """Penalty when the two leads share a 2x or 4x weakness.

    Returns a non-positive value; 0 means no shared weakness.
    """
    if len(leads) != 2:
        return 0.0
    lead_types = [get_species_types(p.get("species", "")) for p in leads]
    if any(not types for types in lead_types):
        return 0.0
    penalty = 0.0
    for attack_type, _ in _all_attacking_types():
        weak = 0
        max_weakness = 0.0
        for defender_types in lead_types:
            mult = _composite_multiplier(attack_type, defender_types)
            if mult >= 2.0:
                weak += 1
                max_weakness = max(max_weakness, mult)
        if weak >= 2:
            if max_weakness >= 4.0:
                penalty -= 1.0  # Shared 4x weakness is the worst case.
            else:
                penalty -= 0.5  # Shared 2x weakness.
    return penalty


def _lead_speed_control_pressure(leads: Sequence[Mapping[str, Any]]) -> float:
    if len(leads) != 2:
        return 0.0
    has_tailwind = any(
        get_move_category(move) == "tailwind"
        for pokemon in leads
        for move in pokemon.get("moves", [])
    )
    has_trick_room = any(
        get_move_category(move) == "trick_room"
        for pokemon in leads
        for move in pokemon.get("moves", [])
    )
    return float(has_tailwind or has_trick_room)


def _fake_out_pressure(plan: Sequence[Mapping[str, Any]]) -> float:
    """Number of Fake Out users in the plan (capped at 2 to avoid
    stack dominance from duplicates; the duplicate-role penalty then
    discourages stacking the same role)."""
    return float(
        sum(
            1
            for pokemon in plan
            for move in pokemon.get("moves", [])
            if get_move_category(move) == "fake_out"
        )
    )


def _redirection_support(plan: Sequence[Mapping[str, Any]]) -> float:
    has_move_redirection = any(
        get_move_category(move) == "redirection"
        for pokemon in plan
        for move in pokemon.get("moves", [])
    )
    has_ability_redirection = any(
        get_ability_category(pokemon.get("ability", "")) == "redirection"
        for pokemon in plan
    )
    return float(has_move_redirection or has_ability_redirection)


def _intimidate_support(plan: Sequence[Mapping[str, Any]]) -> float:
    return float(
        any(
            get_ability_category(pokemon.get("ability", "")) == "intimidate"
            for pokemon in plan
        )
    )


def _spread_pressure(plan: Sequence[Mapping[str, Any]]) -> float:
    return float(
        any(
            get_move_category(move) == "spread"
            for pokemon in plan
            for move in pokemon.get("moves", [])
        )
    )


def _protect_utility(plan: Sequence[Mapping[str, Any]]) -> float:
    return float(
        sum(
            1
            for pokemon in plan
            for move in pokemon.get("moves", [])
            if get_move_category(move) == "protect"
        )
    )


def _lead_back_role_coverage(
    leads: Sequence[Mapping[str, Any]],
    backs: Sequence[Mapping[str, Any]],
) -> float:
    """Count of distinct roles across lead + back, normalised by the
    total role keys. The role keys are:

        fake_out, tailwind, trick_room, redirection, spread, intimidate
    """
    role_keys = (
        "fake_out",
        "tailwind",
        "trick_room",
        "redirection",
        "spread",
        "intimidate",
    )
    distinct: set = set()
    for pokemon in list(leads) + list(backs):
        for move in pokemon.get("moves", []):
            cat = get_move_category(move)
            if cat in role_keys:
                distinct.add(cat)
        if get_ability_category(pokemon.get("ability", "")) == "intimidate":
            distinct.add("intimidate")
    return len(distinct) / float(len(role_keys))


def _back_pivot_or_switch(backs: Sequence[Mapping[str, Any]]) -> float:
    if not backs:
        return 0.0
    pivot_users = sum(
        1
        for pokemon in backs
        for move in pokemon.get("moves", [])
        if _is_pivot(move.lower())
    )
    return float(min(pivot_users, 1))


def _duplicate_role_penalty(plan: Sequence[Mapping[str, Any]]) -> float:
    """Per extra role occurrence beyond the first for the fixed role list."""
    counter: Counter = Counter()
    for pokemon in plan:
        for move in pokemon.get("moves", []):
            cat = get_move_category(move)
            if cat in DUPLICATE_ROLE_KEYS:
                counter[cat] += 1
        if get_ability_category(pokemon.get("ability", "")) == "intimidate":
            counter["intimidate"] += 1
    penalty = 0.0
    for key, count in counter.items():
        if count > 1:
            penalty -= (count - 1)
    return penalty


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def evaluate_plan_on_common_scale(
    team: Sequence[Mapping[str, Any]],
    opponent_team: Sequence[Mapping[str, Any]],
    chosen_4: Sequence[str],
    lead_2: Sequence[str],
    back_2: Sequence[str],
) -> CommonPlanScore:
    """Score the exact 4/2/2 plan on a common, policy-independent scale.

    Parameters
    ----------
    team:
        The full 6-Pokémon team the plan was selected from. Used to
        resolve which ability and moves belong to each species.
    opponent_team:
        The opponent's full team as visible during preview. The
        evaluator only uses open team-sheet information: species,
        ability, moves, and types.
    chosen_4, lead_2, back_2:
        The species names exactly as the policy returned them. Lead
        and back must be subsets of chosen_4 with no overlap.

    Returns
    -------
    CommonPlanScore
        Structured breakdown with `components` (each named component
        value) and `total` (the weighted sum). Policy comparisons
        must use `total`.

    Raises
    ------
    CommonPlanEvaluatorError
        If the plan is malformed: any species is missing from the
        team, the lead/back partition is invalid, or there are
        duplicates. The error message identifies the defect.
    """
    if team is None or len(team) != 6:
        raise CommonPlanEvaluatorError(
            f"Team must have exactly 6 Pokémon, got {len(team) if team else 0}."
        )
    if opponent_team is None:
        raise CommonPlanEvaluatorError("Opponent team must be provided.")
    chosen_set = [_normalise_species(s) for s in chosen_4]
    if len(chosen_set) != 4:
        raise CommonPlanEvaluatorError(
            f"chosen_4 must contain exactly 4 species, got {len(chosen_set)}."
        )
    if len(set(chosen_set)) != 4:
        raise CommonPlanEvaluatorError(
            f"chosen_4 must contain 4 unique species, got {chosen_set}."
        )
    lead_set = [_normalise_species(s) for s in lead_2]
    back_set = [_normalise_species(s) for s in back_2]
    if len(lead_set) != 2:
        raise CommonPlanEvaluatorError(
            f"lead_2 must contain exactly 2 species, got {len(lead_set)}."
        )
    if len(back_set) != 2:
        raise CommonPlanEvaluatorError(
            f"back_2 must contain exactly 2 species, got {len(back_set)}."
        )
    if not set(lead_set).issubset(set(chosen_set)):
        missing = set(lead_set) - set(chosen_set)
        raise CommonPlanEvaluatorError(
            f"Lead species {missing} are not in chosen_4 {chosen_set}."
        )
    if not set(back_set).issubset(set(chosen_set)):
        missing = set(back_set) - set(chosen_set)
        raise CommonPlanEvaluatorError(
            f"Back species {missing} are not in chosen_4 {chosen_set}."
        )
    if set(lead_set).intersection(set(back_set)):
        overlap = set(lead_set).intersection(set(back_set))
        raise CommonPlanEvaluatorError(
            f"Lead and back share species {overlap}."
        )
    if set(lead_set).union(set(back_set)) != set(chosen_set):
        raise CommonPlanEvaluatorError(
            f"Lead and back must cover chosen_4 exactly; "
            f"missing {set(chosen_set) - set(lead_set).union(set(back_set))}."
        )

    resolved: List[Dict[str, Any]] = []
    for species in chosen_set:
        for entry in team:
            if _normalise_species(entry.get("species", "")) == species:
                resolved.append(dict(entry))
                break
        else:
            raise CommonPlanEvaluatorError(
                f"Species {species!r} is not present in the provided team."
            )
    lookup = {p["species"].strip().lower(): p for p in resolved}
    leads_resolved = [lookup[s] for s in lead_set]
    backs_resolved = [lookup[s] for s in back_set]
    plan = leads_resolved + backs_resolved

    components: Dict[str, float] = {
        "offensive_type_coverage": _offensive_type_coverage(
            plan, opponent_team
        ),
        "defensive_weakness_exposure": _defensive_weakness_exposure(
            plan, opponent_team
        ),
        "lead_shared_weakness": _lead_shared_weakness(leads_resolved),
        "lead_speed_control_pressure": _lead_speed_control_pressure(
            leads_resolved
        ),
        "fake_out_pressure": _fake_out_pressure(plan),
        "redirection_support": _redirection_support(plan),
        "intimidate_support": _intimidate_support(plan),
        "spread_pressure": _spread_pressure(plan),
        "protect_utility": _protect_utility(plan),
        "lead_back_role_coverage": _lead_back_role_coverage(
            leads_resolved, backs_resolved
        ),
        "back_pivot_or_switch": _back_pivot_or_switch(backs_resolved),
        "duplicate_role_penalty": _duplicate_role_penalty(plan),
    }
    total = 0.0
    for name, value in components.items():
        total += value * COMPONENT_WEIGHTS[name]

    return CommonPlanScore(
        team_size=len(team),
        chosen_4=list(chosen_4),
        lead_2=list(lead_2),
        back_2=list(back_2),
        opponent_team_size=len(opponent_team),
        components=components,
        total=total,
    )


# ---------------------------------------------------------------------------
# Sanity self-test
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    sample_team = [
        {"species": "Incineroar", "ability": "Intimidate",
         "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Throat Chop"]},
        {"species": "Garchomp", "ability": "Rough Skin",
         "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
        {"species": "Rillaboom", "ability": "Grassy Surge",
         "moves": ["Fake Out", "Grassy Glide", "High Horsepower", "U-turn"]},
        {"species": "Tornadus", "ability": "Prankster",
         "moves": ["Tailwind", "Taunt", "Hurricane", "Protect"]},
        {"species": "Flutter Mane", "ability": "Protosynthesis",
         "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"]},
        {"species": "Iron Hands", "ability": "Quark Drive",
         "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
    ]
    opp = [
        {"species": "Rillaboom", "moves": []},
        {"species": "Iron Hands", "moves": []},
        {"species": "Kingambit", "moves": []},
        {"species": "Incineroar", "moves": []},
        {"species": "Garchomp", "moves": []},
        {"species": "Tornadus", "moves": []},
    ]
    score = evaluate_plan_on_common_scale(
        sample_team,
        opp,
        ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
        ["Incineroar", "Tornadus"],
        ["Garchomp", "Rillaboom"],
    )
    print(f"Total: {score.total:.3f}")
    for k, v in score.components.items():
        print(f"  {k}: {v:.3f}")
