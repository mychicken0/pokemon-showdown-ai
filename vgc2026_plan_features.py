#!/usr/bin/env python3
"""
VGC 2026 Plan Features

Policy-independent feature extractors for 4-from-6 preview plans.

A feature here is computed from a Pokémon list (the plan) and a visible
opponent team. The extractors never call V2, V3 or any other
policy's internal scoring function. They are used for diagnostic
analysis (V2g, V2h) and may be re-used by future policies, but
they themselves do not select a plan.

All features read only open team-sheet information: species, ability,
moves, and types from the local dex.

Dex metadata source
------------------
Move metadata is loaded from the installed ``poke-env`` static Gen 9
dex. The dex exposes ``category`` (Physical / Special / Status),
``priority`` (signed integer), ``target`` (targeting string),
``stallingMove`` (true for Protect / Detect / etc.) and ``flags``.

Move classifications
-------------------
- "Damaging" : category in {Physical, Special} AND basePower > 0.
- "Priority"  : priority > 0 AND NOT stallingMove.
- "Spread"    : target in {allAdjacent, allAdjacentFoes, all} AND
                Damaging.
- "Stall"     : stallingMove is true.
- "Setup"     : a small dictionary-driven list (swords dance, nasty
                plot, ...). Used only as a rough categorisation; the
                list is documented at the top of the module.
- "Restorative": recover / roost / slackoff / ...
- "Pivot"     : u-turn / volt switch / teleport / ...
Unknown moves are reported explicitly as "unknown" and never
silently mapped to a known status category.
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
    get_species_types,
)


# ---------------------------------------------------------------------------
# Hand-written role taxonomy (small, documented, not the dex's full surface)
# ---------------------------------------------------------------------------

# These are stable preview-visible role tags, not the full Gen 9 move
# surface. They cover the common setups and pivots. Any move outside
# this set is reported as "unknown" in the audit, never silently
# rewritten as a known role.
SETUP_MOVES = frozenset({
    "swords dance", "nasty plot", "calm mind", "bulk up",
    "dragon dance", "agility", "rock polish", "shell smash",
    "quiver dance", "coil", "curse", "work up", "coaching",
    "calm mind", "growth", "meditate", "hone claws",
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
    "heal order",
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
    audit: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "team_size": self.team_size,
            "chosen_4": list(self.chosen_4),
            "lead_2": list(self.lead_2),
            "back_2": list(self.back_2),
            "opponent_team_size": self.opponent_team_size,
            "features": dict(self.features),
            "categorical": dict(self.categorical),
            "audit": dict(self.audit),
        }


# ---------------------------------------------------------------------------
# Move / ability helpers
# ---------------------------------------------------------------------------


def _move_id(move_name: str) -> str:
    return "".join(ch for ch in str(move_name).lower() if ch.isalnum())


@lru_cache(maxsize=1)
def _gen9_moves() -> Dict[str, Dict[str, Any]]:
    """Load the installed poke-env Gen 9 move data without importing
    poke-env. The package's static JSON file is the same data the
    installed server uses."""
    path = distribution("poke-env").locate_file(
        "poke_env/data/static/moves/gen9moves.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _move_data(move_name: str) -> Mapping[str, Any]:
    return _gen9_moves().get(_move_id(move_name), {})


def _move_category(move_name: str) -> str:
    return str(_move_data(move_name).get("category", "")).strip().lower()


def _move_priority(move_name: str) -> float:
    raw = _move_data(move_name).get("priority", 0)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _move_is_stalling(move_name: str) -> bool:
    return bool(_move_data(move_name).get("stallingMove", False))


def _move_target(move_name: str) -> str:
    return str(_move_data(move_name).get("target", "")).strip()


def _move_base_power(move_name: str) -> float:
    raw = _move_data(move_name).get("basePower", 0)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _move_is_damaging(move_name: str) -> bool:
    return (
        _move_category(move_name) in {"physical", "special"}
        and _move_base_power(move_name) > 0
    )


def _is_priority_move(move_name: str) -> bool:
    """Priority that is not stalling.

    A Protect at +4 is NOT an offensive priority tool. The dex's
    `stallingMove` flag distinguishes the two.
    """
    return _move_priority(move_name) > 0 and not _move_is_stalling(move_name)


def _is_stall_move(move_name: str) -> bool:
    return _move_is_stalling(move_name)


def _is_spread_move(move_name: str) -> bool:
    return _move_target(move_name) in {
        "allAdjacent", "allAdjacentFoes", "all"
    } and _move_is_damaging(move_name)


def _is_pivot_move(move_name: str) -> bool:
    return move_name.lower() in PIVOT_MOVES


def _is_setup_move(move_name: str) -> bool:
    return move_name.lower() in SETUP_MOVES


def _is_restorative_move(move_name: str) -> bool:
    return move_name.lower() in RESTORATIVE_MOVES


def classify_move(move_name: str) -> str:
    """Return one of: physical, special, stall, priority, spread,
    setup, restorative, pivot, unknown.

    A single move gets exactly one label, in priority order. Unknown
    moves never get remapped to a known status.
    """
    if _move_id(move_name) not in _gen9_moves():
        return "unknown"
    if _is_stall_move(move_name):
        return "stall"
    if _is_priority_move(move_name):
        return "priority"
    if _is_spread_move(move_name):
        return "spread"
    if _move_category(move_name) == "physical":
        return "physical"
    if _move_category(move_name) == "special":
        return "special"
    if _is_setup_move(move_name):
        return "setup"
    if _is_restorative_move(move_name):
        return "restorative"
    if _is_pivot_move(move_name):
        return "pivot"
    if _move_category(move_name) == "status":
        return "status"
    return "unknown"


# ---------------------------------------------------------------------------
# Plan resolution
# ---------------------------------------------------------------------------


def _normalise_species(species: str) -> str:
    return str(species).strip().lower()


def _resolve_plan(
    team: Sequence[Mapping[str, Any]],
    chosen_4: Sequence[str],
    lead_2: Sequence[str],
    back_2: Sequence[str],
) -> List[Dict[str, Any]]:
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
        raise ValueError(f"Plan must contain 4 pokemon, got {len(plan)}")
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


def _lead_shared_weakness_count(
    leads: Sequence[Mapping[str, Any]]
) -> Tuple[int, int]:
    lead_types = [get_species_types(p.get("species", "")) for p in leads]
    if any(not t for t in lead_types):
        return 0, 0
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
    return shared_2x, shared_4x


def _physical_special_balance(
    plan: Sequence[Mapping[str, Any]]
) -> Tuple[int, int, int, int]:
    """Return (physical_damaging, special_damaging, physical_total,
    special_total). Total counts include damaging moves plus the
    physical/special status moves so the per-move audit is
    transparent."""
    physical_damaging = 0
    special_damaging = 0
    physical_total = 0
    special_total = 0
    for pokemon in plan:
        for move in pokemon.get("moves", []) or []:
            cat = _move_category(move)
            if cat == "physical":
                physical_total += 1
                if _move_is_damaging(move):
                    physical_damaging += 1
            elif cat == "special":
                special_total += 1
                if _move_is_damaging(move):
                    special_damaging += 1
    return physical_damaging, special_damaging, physical_total, special_total


def _weather_terrain_conflict(
    plan: Sequence[Mapping[str, Any]]
) -> Dict[str, List[str]]:
    weather_setters: List[str] = []
    terrain_setters: List[str] = []
    for pokemon in plan:
        ability = pokemon.get("ability", "").lower()
        if ability == "drizzle":
            weather_setters.append("rain")
        elif ability == "drought":
            weather_setters.append("sun")
        elif ability == "snow warning":
            weather_setters.append("snow")
        elif ability == "sand stream":
            weather_setters.append("sand")
        if ability == "electric surge":
            terrain_setters.append("electric")
        elif ability == "grassy surge":
            terrain_setters.append("grassy")
        elif ability == "misty surge":
            terrain_setters.append("misty")
        elif ability == "psychic surge":
            terrain_setters.append("psychic")
    return {
        "weather_setters": weather_setters,
        "terrain_setters": terrain_setters,
        "has_weather_setter": ["yes" if weather_setters else "no"],
        "has_terrain_setter": ["yes" if terrain_setters else "no"],
        "has_conflicting_weather": [
            "yes" if len(set(weather_setters)) > 1 else "no"
        ],
        "has_conflicting_terrain": [
            "yes" if len(set(terrain_setters)) > 1 else "no"
        ],
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
    """Compute the full policy-independent feature bundle for a 4/2/2
    plan. Plan membership is validated strictly. Moves not present
    in the Gen 9 dex are reported in the audit, not silently
    rewritten."""
    if team is None or len(team) != 6:
        raise ValueError(
            f"Team must have exactly 6 Pokémon, got {len(team) if team else 0}."
        )
    if opponent_team is None:
        raise ValueError("Opponent team must be provided.")
    plan = _resolve_plan(team, chosen_4, lead_2, back_2)
    leads = plan[:2]
    backs = plan[2:]
    all_types: List[List[str]] = [
        get_species_types(p["species"]) for p in plan
    ]

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
    features["lead_shared_weakness"] = _lead_shared_weakness(leads)
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

    common_total = sum(
        features[name] * COMPONENT_WEIGHTS[name]
        for name in COMPONENT_WEIGHTS
    )
    features["common_total"] = common_total

    shared_2x, shared_4x = _lead_shared_weakness_count(leads)
    features["lead_shared_2x_weakness_count"] = float(shared_2x)
    features["lead_shared_4x_weakness_count"] = float(shared_4x)

    # Back-pressure from the dex: priority + spread + setup. Never
    # counts stalling moves (Protect is a defensive tool, not
    # offensive pressure).
    back_priority = 0
    back_spread = 0
    back_setup = 0
    for pokemon in backs:
        for move in pokemon.get("moves", []) or []:
            if _is_priority_move(move):
                back_priority += 1
            if _is_spread_move(move):
                back_spread += 1
            if _is_setup_move(move):
                back_setup += 1
    features["back_priority_moves"] = float(back_priority)
    features["back_spread_moves"] = float(back_spread)
    features["back_setup_moves"] = float(back_setup)
    features["back_immediate_pressure"] = float(
        back_priority + 0.5 * back_spread + 0.5 * back_setup
    )

    # Lead immediate damage: damaging + priority. Stalls excluded.
    lead_damage_count = 0
    for pokemon in leads:
        for move in pokemon.get("moves", []) or []:
            if _move_is_damaging(move) or _is_priority_move(move):
                lead_damage_count += 1
    features["lead_immediate_damage"] = float(lead_damage_count)

    back_damage_count = 0
    for pokemon in backs:
        for move in pokemon.get("moves", []) or []:
            if _move_is_damaging(move) or _is_priority_move(move):
                back_damage_count += 1
    features["back_immediate_damage"] = float(back_damage_count)

    phys_dmg, spec_dmg, phys_total, spec_total = _physical_special_balance(
        plan
    )
    features["physical_damaging_moves"] = float(phys_dmg)
    features["special_damaging_moves"] = float(spec_dmg)
    features["physical_total_moves"] = float(phys_total)
    features["special_total_moves"] = float(spec_total)
    features["physical_special_balance_diff"] = float(phys_dmg - spec_dmg)

    setup_count = sum(
        1
        for pokemon in plan
        for move in pokemon.get("moves", []) or []
        if _is_setup_move(move)
    )
    features["setup_moves"] = float(setup_count)

    restorative_count = sum(
        1
        for pokemon in plan
        for move in pokemon.get("moves", []) or []
        if _is_restorative_move(move)
    )
    features["restorative_moves"] = float(restorative_count)

    stall_count = sum(
        1
        for pokemon in plan
        for move in pokemon.get("moves", []) or []
        if _is_stall_move(move)
    )
    features["stall_moves"] = float(stall_count)

    pivot_count = sum(
        1
        for pokemon in plan
        for move in pokemon.get("moves", []) or []
        if _is_pivot_move(move)
    )
    features["pivot_moves"] = float(pivot_count)

    features["type_count_unique"] = float(
        len({t for types in all_types for t in types})
    )

    # Audit / unknown-move reporting
    audit: Dict[str, Any] = {}
    move_classes: Counter = Counter()
    unknown_moves: List[str] = []
    for pokemon in plan:
        for move in pokemon.get("moves", []) or []:
            cls = classify_move(move)
            move_classes[cls] += 1
            if cls == "unknown":
                unknown_moves.append(move)
    audit["move_classes"] = dict(move_classes)
    audit["unknown_moves"] = sorted(set(unknown_moves))
    audit["unknown_count"] = len(unknown_moves)
    audit["opponent_unknown_moves"] = []
    for pokemon in opponent_team:
        for move in pokemon.get("moves", []) or []:
            if classify_move(move) == "unknown":
                audit["opponent_unknown_moves"].append(move)
    audit["opponent_unknown_moves"] = sorted(
        set(audit["opponent_unknown_moves"])
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
            get_move_category(move, _gen9_moves())
            if False
            else _move_id(move) == "fakeout"
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
            _move_id(move) in {"followme", "ragepowder"}
            for move in p.get("moves", [])
        )
        for p in plan
    )
    categorical["has_tailwind_or_trick_room"] = any(
        any(
            _move_id(move) in {"tailwind", "trickroom"}
            for move in p.get("moves", [])
        )
        for p in plan
    )

    return PlanFeatures(
        team_size=len(team),
        chosen_4=list(chosen_4),
        lead_2=list(lead_2),
        back_2=list(back_2),
        opponent_team_size=len(opponent_team),
        features=features,
        categorical=categorical,
        audit=audit,
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


# ---------------------------------------------------------------------------
# Smoke self-test
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import json
    sample_team = [
        {"species": "Incineroar", "ability": "Intimidate",
         "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Protect"]},
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
        sample_team, opp,
        ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
        ["Incineroar", "Tornadus"],
        ["Garchomp", "Rillaboom"],
    )
    print(json.dumps(bundle.to_dict(), indent=2, default=str))
