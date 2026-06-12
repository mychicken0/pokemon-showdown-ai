#!/usr/bin/env python3
"""
VGC 2026 Plan Features

Policy-independent feature extractors for 4-from-6 preview plans.

A feature here is computed from a Pokémon list (the plan) and a visible
opponent team. The extractors never call V2, V3 or any other
policy's internal scoring function. They are used for diagnostic
analysis (V2g) and may be re-used by future policies, but they
themselves do not select a plan.

All features read only open team-sheet information: species, ability,
moves, and types from the local dex.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.metadata import distribution
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from team_preview_policy import (
    TYPE_CHART,
    get_ability_category,
    get_move_category,
    get_species_types,
)


# ---------------------------------------------------------------------------
# Move / ability / role taxonomy
# ---------------------------------------------------------------------------


WEATHER_SETTERS = {
    "drizzle": "rain",
    "drought": "sun",
    "snow warning": "snow",
    "sand stream": "sand",
}
TERRAIN_SETTERS = {
    "electric surge": "electric",
    "grassy surge": "grassy",
    "misty surge": "misty",
    "psychic surge": "psychic",
}
WEATHER_ABOLISHERS = {
    "cloud nine", "air lock",
}
SETUP_MOVES = frozenset({
    "swords dance", "nasty plot", "calm mind", "bulk up",
    "dragon dance", "agility", "rock polish", "shell smash",
    "quiver dance", "coil", "curse", "work up", "coaching",
})
PIVOT_MOVES = frozenset({
    "u-turn", "uturn", "volt switch", "voltswitch", "parting shot",
    "baton pass", "teleport", "chilly reception", "trick",
    "ally switch", "flip turn", "shed tail",
})
RESTORATIVE_MOVES = frozenset({
    "recover", "roost", "soft-boiled", "soft boiled", "moonlight",
    "morning sun", "synthesis", "slackoff", "rest", "wish",
    "heal pulse", "life dew", "jungle healing", "milk drink",
})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PlanFeatures:
    """All plan-level features produced for a single 4/2/2 plan."""

    team_size: int
    chosen_4: List[str]
    lead_2: List[str]
    back_2: List[str]
    opponent_team_size: int
    features: Dict[str, float] = field(default_factory=dict)
    categorical: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "team_size": self.team_size,
            "chosen_4": list(self.chosen_4),
            "lead_2": list(self.lead_2),
            "back_2": list(self.back_2),
            "opponent_team_size": self.opponent_team_size,
            "features": dict(self.features),
            "categorical": dict(self.categorical),
        }


# ---------------------------------------------------------------------------
# Plan resolution helpers
# ---------------------------------------------------------------------------


def _normalise_species(species: str) -> str:
    return str(species).strip().lower()


def _resolve_plan(
    team: Sequence[Mapping[str, Any]],
    chosen_4: Sequence[str],
    lead_2: Sequence[str],
    back_2: Sequence[str],
) -> List[Dict[str, Any]]:
    """Resolve species names to team dicts. Order follows lead_2 + back_2.

    Raises KeyError on missing species.
    """
    by_species: Dict[str, Dict[str, Any]] = {}
    for entry in team:
        key = _normalise_species(entry.get("species", ""))
        if key:
            by_species[key] = dict(entry)
    plan: List[Dict[str, Any]] = []
    for species in list(lead_2) + list(back_2):
        key = _normalise_species(species)
        if key not in by_species:
            raise KeyError(f"Species {species!r} not in team")
        plan.append(by_species[key])
    if len(plan) != 4:
        raise ValueError(
            f"Plan must contain 4 pokemon, got {len(plan)}"
        )
    seen = {p["species"].strip().lower() for p in plan}
    if len(seen) != 4:
        raise ValueError("Plan contains duplicate species")
    chosen_set = {_normalise_species(s) for s in chosen_4}
    if chosen_set != seen:
        raise ValueError(
            f"chosen_4 {chosen_set} does not match resolved plan {seen}"
        )
    lead_set = {_normalise_species(s) for s in lead_2}
    back_set = {_normalise_species(s) for s in back_2}
    if lead_set & back_set:
        raise ValueError("Lead and back share species")
    if (lead_set | back_set) != chosen_set:
        raise ValueError("Lead and back do not cover chosen_4")
    return plan


# ---------------------------------------------------------------------------
# Atomic classifiers (single Pokémon)
# ---------------------------------------------------------------------------


def _move_id(move_name: str) -> str:
    return "".join(ch for ch in str(move_name).lower() if ch.isalnum())


@lru_cache(maxsize=1)
def _gen9_moves() -> Dict[str, Dict[str, Any]]:
    """Load the installed poke-env Gen 9 move data without importing poke-env.

    Importing the package starts its background event loop. Reading the
    installed static JSON through package metadata keeps this offline
    diagnostic process free of that lifecycle side effect.
    """
    path = distribution("poke-env").locate_file(
        "poke_env/data/static/moves/gen9moves.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _move_data(move_name: str) -> Mapping[str, Any]:
    return _gen9_moves().get(_move_id(move_name), {})


def _move_kind(move_name: str) -> str:
    """Return 'physical', 'special' or 'other'."""
    category = str(_move_data(move_name).get("category", "")).lower()
    if category == "physical":
        return "physical"
    if category == "special":
        return "special"
    return "other"


def _is_priority_move(move_name: str) -> bool:
    data = _move_data(move_name)
    priority = data.get("priority", 0)
    return (
        isinstance(priority, (int, float))
        and priority > 0
        and not bool(data.get("stallingMove"))
    )


def _is_pivot_move(move_name: str) -> bool:
    return move_name.lower() in PIVOT_MOVES


def _is_setup_move(move_name: str) -> bool:
    return move_name.lower() in SETUP_MOVES


def _is_damaging_move(move_name: str) -> bool:
    data = _move_data(move_name)
    base_power = data.get("basePower", 0)
    return (
        _move_kind(move_name) in {"physical", "special"}
        and isinstance(base_power, (int, float))
        and base_power > 0
    )


def _is_restorative(move_name: str) -> bool:
    return move_name.lower() in RESTORATIVE_MOVES


def _has_weather_setter(pokemon: Mapping[str, Any]) -> Optional[str]:
    ability = pokemon.get("ability", "")
    return WEATHER_SETTERS.get(ability.lower())


def _has_terrain_setter(pokemon: Mapping[str, Any]) -> Optional[str]:
    ability = pokemon.get("ability", "")
    return TERRAIN_SETTERS.get(ability.lower())


def _has_weather_abolisher(pokemon: Mapping[str, Any]) -> bool:
    return pokemon.get("ability", "").lower() in WEATHER_ABOLISHERS


# ---------------------------------------------------------------------------
# Plan-level feature calculations
# ---------------------------------------------------------------------------


def _all_attacker_multiplier(
    attacker: str, defender_types: Sequence[str]
) -> float:
    multipliers = TYPE_CHART.get(attacker, {})
    combined = 1.0
    for defender in defender_types:
        combined *= multipliers.get(defender, 1.0)
    return combined


def _lead_shared_weakness_count(leads: Sequence[Mapping[str, Any]]) -> Tuple[int, int, float]:
    """Return (shared_2x_count, shared_4x_count, attack_type_breakdown_dict)."""
    lead_types = [get_species_types(p.get("species", "")) for p in leads]
    if any(not t for t in lead_types):
        return 0, 0, 0.0
    shared_2x = 0
    shared_4x = 0
    for attack_type in TYPE_CHART:
        weak_count = 0
        max_weak = 0.0
        for defender_types in lead_types:
            mult = _all_attacker_multiplier(attack_type, defender_types)
            if mult >= 2.0:
                weak_count += 1
                max_weak = max(max_weak, mult)
        if weak_count >= 2:
            if max_weak >= 4.0:
                shared_4x += 1
            else:
                shared_2x += 1
    return shared_2x, shared_4x, 0.0  # last is reserved for future


def _back_pressure(backs: Sequence[Mapping[str, Any]]) -> float:
    """Immediate-pressure score for the back: priority + spread + setup."""
    score = 0.0
    for pokemon in backs:
        moves = pokemon.get("moves", []) or []
        for move in moves:
            if _is_priority_move(move):
                score += 1.0
            data = _move_data(move)
            if _is_damaging_move(move) and data.get("target") in {
                "allAdjacent", "allAdjacentFoes", "all",
            }:
                score += 0.5
            if _is_setup_move(move):
                score += 0.5
    return score


def _physical_special_balance(
    plan: Sequence[Mapping[str, Any]],
) -> Dict[str, int]:
    physical = 0
    special = 0
    for pokemon in plan:
        for move in pokemon.get("moves", []) or []:
            kind = _move_kind(move)
            if kind == "physical":
                physical += 1
            elif kind == "special":
                special += 1
    return {"physical_moves": physical, "special_moves": special}


def _weather_terrain_conflict(
    plan: Sequence[Mapping[str, Any]],
) -> Dict[str, List[str]]:
    weather_setters: List[str] = []
    terrain_setters: List[str] = []
    for pokemon in plan:
        weather = _has_weather_setter(pokemon)
        if weather:
            weather_setters.append(weather)
        terrain = _has_terrain_setter(pokemon)
        if terrain:
            terrain_setters.append(terrain)
    has_weather = bool(weather_setters)
    has_terrain = bool(terrain_setters)
    has_multiple_weather = len(set(weather_setters)) > 1
    has_multiple_terrain = len(set(terrain_setters)) > 1
    return {
        "weather_setters": weather_setters,
        "terrain_setters": terrain_setters,
        "has_weather_setter": ["yes" if has_weather else "no"],
        "has_terrain_setter": ["yes" if has_terrain else "no"],
        "has_conflicting_weather": ["yes" if has_multiple_weather else "no"],
        "has_conflicting_terrain": ["yes" if has_multiple_terrain else "no"],
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def extract_plan_features(
    team: Sequence[Mapping[str, Any]],
    opponent_team: Sequence[Mapping[str, Any]],
    chosen_4: Sequence[str],
    lead_2: Sequence[str],
    back_2: Sequence[str],
) -> PlanFeatures:
    """Compute the full policy-independent feature bundle for a 4/2/2 plan.

    Parameters mirror those of `evaluate_plan_on_common_scale`. The
    function refuses to invent data; if the plan is malformed it
    raises `KeyError` or `ValueError` rather than returning a guess.
    """
    if team is None or len(team) != 6:
        raise ValueError(
            f"Team must have exactly 6 Pokémon, got {len(team) if team else 0}."
        )
    if opponent_team is None:
        raise ValueError("Opponent team must be provided.")
    plan = _resolve_plan(team, chosen_4, lead_2, back_2)
    leads = plan[:2]
    backs = plan[2:]
    all_types: List[List[str]] = [get_species_types(p["species"]) for p in plan]

    # Common-evaluator components are also useful as features.
    from vgc2026_common_plan_evaluator import (
        COMPONENT_WEIGHTS,
        _offensive_type_coverage,
        _defensive_weakness_exposure,
        _lead_shared_weakness,
        _lead_speed_control_pressure,
        _fake_out_pressure,
        _redirection_support,
        _intimidate_support,
        _spread_pressure,
        _protect_utility,
        _lead_back_role_coverage,
        _back_pivot_or_switch,
        _duplicate_role_penalty,
    )
    features: Dict[str, float] = {}
    features["offensive_type_coverage"] = (
        _offensive_type_coverage(plan, opponent_team)
    )
    features["defensive_weakness_exposure"] = (
        _defensive_weakness_exposure(plan, opponent_team)
    )
    features["lead_shared_weakness"] = (
        _lead_shared_weakness(leads)
    )
    features["lead_speed_control_pressure"] = (
        _lead_speed_control_pressure(leads)
    )
    features["fake_out_pressure"] = _fake_out_pressure(plan)
    features["redirection_support"] = _redirection_support(plan)
    features["intimidate_support"] = _intimidate_support(plan)
    features["spread_pressure"] = _spread_pressure(plan)
    features["protect_utility"] = _protect_utility(plan)
    features["lead_back_role_coverage"] = _lead_back_role_coverage(
        leads, backs
    )
    features["back_pivot_or_switch"] = _back_pivot_or_switch(backs)
    features["duplicate_role_penalty"] = _duplicate_role_penalty(plan)

    # Weights are kept identical to the common evaluator so that the
    # common total and the feature sum are mutually consistent.
    common_total = sum(
        features[name] * COMPONENT_WEIGHTS[name]
        for name in COMPONENT_WEIGHTS
    )
    features["common_total"] = common_total

    # Newly exposed features.
    shared_2x, shared_4x, _ = _lead_shared_weakness_count(leads)
    features["lead_shared_2x_weakness_count"] = float(shared_2x)
    features["lead_shared_4x_weakness_count"] = float(shared_4x)
    features["back_immediate_pressure"] = _back_pressure(backs)
    balance = _physical_special_balance(plan)
    features["physical_damaging_moves"] = float(balance["physical_moves"])
    features["special_damaging_moves"] = float(balance["special_moves"])
    features["physical_special_balance_diff"] = float(
        balance["physical_moves"] - balance["special_moves"]
    )
    features["lead_immediate_damage"] = float(
        sum(
            1
            for pokemon in leads
            for move in pokemon.get("moves", []) or []
            if _is_damaging_move(move) or _is_priority_move(move)
        )
    )
    features["back_immediate_damage"] = float(
        sum(
            1
            for pokemon in backs
            for move in pokemon.get("moves", []) or []
            if _is_damaging_move(move) or _is_priority_move(move)
        )
    )
    features["setup_moves"] = float(
        sum(
            1
            for pokemon in plan
            for move in pokemon.get("moves", []) or []
            if _is_setup_move(move)
        )
    )
    features["restorative_moves"] = float(
        sum(
            1
            for pokemon in plan
            for move in pokemon.get("moves", []) or []
            if _is_restorative(move)
        )
    )
    features["type_count_unique"] = float(
        len({t for types in all_types for t in types})
    )
    categorical: Dict[str, Any] = {}
    categorical.update(_weather_terrain_conflict(plan))
    categorical["lead_pair"] = "|".join(
        sorted(p["species"] for p in leads)
    )
    categorical["back_pair"] = "|".join(
        sorted(p["species"] for p in backs)
    )
    categorical["chosen_4"] = sorted(p["species"] for p in plan)
    categorical["has_fake_out_in_leads"] = any(
        any(
            get_move_category(move) == "fake_out"
            for move in p.get("moves", [])
        )
        for p in leads
    )
    categorical["has_intimidate_in_leads"] = any(
        get_ability_category(p.get("ability", "")) == "intimidate"
        for p in leads
    )
    categorical["has_redirection_in_plan"] = any(
        any(
            get_move_category(move) == "redirection"
            for move in p.get("moves", [])
        )
        for p in plan
    )
    categorical["has_tailwind_or_trick_room"] = any(
        any(
            get_move_category(move) in {"tailwind", "trick_room"}
            for move in p.get("moves", [])
        )
        for p in plan
    )
    categorical["has_weather_abolisher_in_plan"] = any(
        _has_weather_abolisher(p) for p in plan
    )
    return PlanFeatures(
        team_size=len(team),
        chosen_4=list(chosen_4),
        lead_2=list(lead_2),
        back_2=list(back_2),
        opponent_team_size=len(opponent_team),
        features=features,
        categorical=categorical,
    )


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------


def shannon_entropy_from_counts(counts: Iterable[int]) -> float:
    values = [int(c) for c in counts if int(c) > 0]
    total = sum(values)
    if total <= 0:
        return 0.0
    return -sum(
        (value / total) * __import__("math").log2(value / total)
        for value in values
    )


def aggregate_features(
    bundles: Sequence[PlanFeatures],
) -> Dict[str, float]:
    """Mean, median, min, p10, p90 of every numeric feature."""
    if not bundles:
        return {}
    keys = list(bundles[0].features.keys())
    aggregate: Dict[str, float] = {}
    for key in keys:
        values = [b.features[key] for b in bundles]
        ordered = sorted(values)
        n = len(ordered)
        mean = sum(values) / n
        median = (
            ordered[n // 2]
            if n % 2 == 1
            else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
        )
        minimum = ordered[0]
        maximum = ordered[-1]
        # Linear-interpolated percentiles (10th and 90th).
        def _pct(frac: float) -> float:
            pos = (n - 1) * frac
            lo = int(pos)
            hi = min(lo + 1, n - 1)
            weight = pos - lo
            return ordered[lo] * (1 - weight) + ordered[hi] * weight
        aggregate[f"{key}_mean"] = mean
        aggregate[f"{key}_median"] = median
        aggregate[f"{key}_min"] = minimum
        aggregate[f"{key}_p10"] = _pct(0.10)
        aggregate[f"{key}_p90"] = _pct(0.90)
        aggregate[f"{key}_max"] = maximum
    return aggregate


if __name__ == "__main__":
    import json
    sample = [
        {"species": "Incineroar", "ability": "Intimidate",
         "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Throat Chop"]},
        {"species": "Garchomp", "ability": "Rough Skin",
         "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
        {"species": "Rillaboom", "ability": "Grassy Surge",
         "moves": ["Fake Out", "Grassy Glide", "U-turn", "Protect"]},
        {"species": "Tornadus", "ability": "Prankster",
         "moves": ["Tailwind", "Taunt", "Hurricane", "Focus Blast"]},
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
    bundle = extract_plan_features(
        sample, opp,
        ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
        ["Incineroar", "Tornadus"],
        ["Garchomp", "Rillaboom"],
    )
    print(json.dumps(bundle.to_dict(), indent=2, default=str))
