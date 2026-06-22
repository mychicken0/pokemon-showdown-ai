#!/usr/bin/env python3
"""
VGC 2026 Policy-Independent Matchup Evaluator V2

A richer, policy-independent matchup evaluator built from actual
preview-visible matchup mechanics rather than tuning weights
against V2f battle labels.

Hard boundary
-------------
This evaluator MUST be designed, defined, and tested BEFORE V2f
battle labels are read. The configuration fingerprint below is
computed at module import time. Any analyzer that loads V2f
labels must verify the fingerprint was frozen first.

Allowed inputs (preview-visible only)
-------------------------------------
- species, types, moves, abilities, held items only when present
  in the open team-sheet dataset
- local Gen 9 move dex metadata
- local type chart

Never used
----------
- battle labels (V2f win/loss tags)
- turn logs
- observed battle leads
- hidden EVs/IVs
- inferred abilities
- usage statistics
- online APIs

Battle labels may only be loaded for one diagnostic report
after this module's configuration is frozen. The analyzer
enforces that order.

Sign convention
---------------
- Higher score = better matchup.
- Negative components (e.g. shared weaknesses) subtract from the
  total.
- All ranges are documented per-component.

The 20+ components are defined in ``COMPONENT_SPECS``.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from team_preview_policy import (
    TYPE_CHART,
    calculate_type_matchup,
    calculate_weakness_avoidance,
    get_ability_category,
    get_move_category,
    get_species_types,
)


# ---------------------------------------------------------------------------
# Frozen configuration
# ---------------------------------------------------------------------------
#
# These constants define the evaluator. Changing any of them is a
# ``vgc2026_matchup_evaluator_v3`` change, not a tweak.
#
# Rationale notes are intentionally short and human-auditable.
# ---------------------------------------------------------------------------

# Sign convention: higher is better. Documented in COMPONENT_SPECS.

# Weight per component. Equal-weight by default so that no single
# dimension dominates. Lower values reduce the impact of a noisy
# signal. The sign convention is positive for "good" and negative
# for "bad".
COMPONENT_WEIGHTS: Dict[str, float] = {
    "offensive_move_type_pressure": 1.00,
    "defensive_move_type_exposure": 1.20,
    "immunity_aware_pressure": 0.80,
    "spread_move_pressure": 0.60,
    "priority_pressure": 0.80,
    "speed_control_access": 0.80,
    "fake_out_access": 0.80,
    "redirection_access": 0.80,
    "protect_utility": 0.15,
    "back_pivot_access": 0.50,
    "recovery_access": 0.50,
    "setup_with_support_compatibility": 0.60,
    "physical_special_balance": 0.50,
    "shared_lead_weakness": 1.00,
    "lead_coverage_overlap": 0.40,
    "back_switch_defensive_coverage": 0.60,
    "ability_item_synergy": 0.40,
    "dead_or_redundant_coverage": 0.40,
    "unsupported_setup_risk": 0.50,
    "board_pressure_dual_slot": 0.60,
    "worst_case_lead_pair_resilience": 1.00,
}

# Number of offensive type buckets that count as "covered" by a
# single damaging STAB. We count each of the 18 Gen 9 types once.
TOTAL_TYPES: int = 18

# Spread targets in the local Gen 9 move dex. The
# shared ``doubles_mechanics.SPREAD_TARGETS`` is the
# canonical home; this tuple is the camelCase spelling
# preserved for the V2i frozen fingerprint. Both
# spellings are accepted by ``move_metadata`` because
# ``is_spread`` is computed in the shared module and
# the move metadata is normalised to the dex case
# before comparison.
SPREAD_TARGETS: Tuple[str, ...] = (
    "allAdjacent",
    "allAdjacentFoes",
    "all",
)

# Pivot move keywords. Same list as the common evaluator.
PIVOT_MOVE_KEYWORDS: Tuple[str, ...] = (
    "u-turn",
    "uturn",
    "volt switch",
    "voltswitch",
    "parting shot",
    "baton pass",
    "teleport",
    "chilly reception",
)

# Hand-written role taxonomy. Kept small on purpose: unknown moves
# are reported explicitly and never silently remapped.
SETUP_MOVES = frozenset({
    "swords dance", "nasty plot", "calm mind", "bulk up",
    "dragon dance", "agility", "rock polish", "shell smash",
    "quiver dance", "coil", "curse", "work up", "coaching",
    "growth", "meditate", "hone claws", "tail glow", "victory dance",
})
RESTORATIVE_MOVES = frozenset({
    "recover", "roost", "soft-boiled", "soft boiled", "moonlight",
    "morning sun", "synthesis", "slackoff", "rest", "wish",
    "heal pulse", "life dew", "jungle healing", "milk drink",
    "heal order",
})
PIVOT_MOVES = frozenset({
    "u-turn", "uturn", "volt switch", "voltswitch", "parting shot",
    "baton pass", "teleport", "chilly reception", "trick",
    "ally switch", "flip turn", "shed tail",
})
REDIRECTION_MOVES = frozenset({
    "follow me", "rage powder", "spotlight",
})
SPEED_CONTROL_MOVES = frozenset({
    "tailwind", "trick room",
})

# Severe-bad threshold. Used for the "severely bad opponent lead
# pair" aggregation. A matchup score strictly below this many
# weighted units below the mean is severe.
SEVERE_BAD_ZSCORE_THRESHOLD: float = 0.5
# Favorable threshold. A matchup score strictly above this many
# weighted units above the mean is favorable.
FAVORABLE_ZSCORE_THRESHOLD: float = 0.5

# Bootstrap seed for analyzer stability diagnostics. Fixed.
BOOTSTRAP_SEED: int = 20260612
N_BOOTSTRAP: int = 1000

# Increment whenever evaluator semantics change without a corresponding
# component-weight change. This keeps the frozen fingerprint honest.
EVALUATOR_ALGORITHM_VERSION: str = "v2i.1-preview-move-types"


# ---------------------------------------------------------------------------
# Frozen configuration fingerprint
# ---------------------------------------------------------------------------
#
# This fingerprint is computed at import time and reflects the
# exact constants used to build any plan-evaluation result. Analyzers
# that read V2f battle labels must verify this fingerprint
# before loading labels. See ``freeze_fingerprint``.
# ---------------------------------------------------------------------------


def _freeze_fingerprint() -> str:
    """Deterministic SHA-256 over the frozen configuration.

    Includes all constant values that influence component
    computation. Any change to a constant changes the fingerprint.
    """
    payload: Dict[str, Any] = {
        "algorithm_version": EVALUATOR_ALGORITHM_VERSION,
        "component_weights": dict(COMPONENT_WEIGHTS),
        "total_types": TOTAL_TYPES,
        "spread_targets": list(SPREAD_TARGETS),
        "pivot_move_keywords": list(PIVOT_MOVE_KEYWORDS),
        "setup_moves": sorted(SETUP_MOVES),
        "restorative_moves": sorted(RESTORATIVE_MOVES),
        "pivot_moves": sorted(PIVOT_MOVES),
        "redirection_moves": sorted(REDIRECTION_MOVES),
        "speed_control_moves": sorted(SPEED_CONTROL_MOVES),
        "severe_bad_zscore_threshold": SEVERE_BAD_ZSCORE_THRESHOLD,
        "favorable_zscore_threshold": FAVORABLE_ZSCORE_THRESHOLD,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "n_bootstrap": N_BOOTSTRAP,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# FROZEN at module import time. Re-importing the module after
# editing constants produces a different fingerprint and is
# treated as a V2i break.
FROZEN_FINGERPRINT: str = _freeze_fingerprint()


# ---------------------------------------------------------------------------
# Public Move metadata adapter
# ---------------------------------------------------------------------------
#
# Wraps the local Gen 9 move dex used by ``vgc2026_plan_features``.
# Public, deterministic, no private helpers leaked.
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _gen9_moves() -> Dict[str, Dict[str, Any]]:
    """Load the installed poke-env Gen 9 move data."""
    from importlib.metadata import distribution
    import json as _json
    path = distribution("poke-env").locate_file(
        "poke_env/data/static/moves/gen9moves.json"
    )
    with open(str(path), "r", encoding="utf-8") as f:
        return _json.load(f)


def _move_id(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


@dataclass
class MoveMetadata:
    """Public, fully-typed view of a single move's Gen 9 metadata.

    All fields are populated by the public ``move_metadata`` adapter.
    Unknown moves return a fully-populated record with
    ``category=""``, ``base_power=0``, ``priority=0``, ``type=""``,
    ``target=""``, ``stalling=False`` and ``is_damaging=False``.
    """

    name: str
    move_id: str
    category: str
    base_power: float
    priority: float
    target: str
    stalling: bool
    move_type: str
    is_damaging: bool
    is_priority_offensive: bool
    is_spread: bool


def move_metadata(name: str) -> MoveMetadata:
    """Public adapter for Gen 9 move metadata.

    Returns a fully-populated ``MoveMetadata`` even for unknown
    moves. The returned record has ``is_damaging=False`` and
    ``is_spread=False`` for unknown moves. Callers must handle
    unknown moves explicitly.
    """
    mid = _move_id(name)
    data = _gen9_moves().get(mid, {})
    category = str(data.get("category", "")).strip().lower()
    try:
        base_power = float(data.get("basePower", 0) or 0)
    except (TypeError, ValueError):
        base_power = 0.0
    try:
        priority = float(data.get("priority", 0) or 0)
    except (TypeError, ValueError):
        priority = 0.0
    target = str(data.get("target", "")).strip()
    stalling = bool(data.get("stallingMove", False))
    move_type = str(data.get("type", "")).strip().lower()
    is_damaging = (
        category in {"physical", "special"} and base_power > 0
    )
    is_priority_offensive = (
        priority > 0 and not stalling and is_damaging
    )
    is_spread = (
        target in SPREAD_TARGETS and is_damaging
    )
    return MoveMetadata(
        name=str(name),
        move_id=mid,
        category=category,
        base_power=base_power,
        priority=priority,
        target=target,
        stalling=stalling,
        move_type=move_type,
        is_damaging=is_damaging,
        is_priority_offensive=is_priority_offensive,
        is_spread=is_spread,
    )


def classify_move(name: str) -> str:
    """Public classifier label for a single move.

    One of: physical, special, status, stall, priority, spread,
    setup, restorative, pivot, redirection, speed_control, unknown.

    Unknown moves return ``"unknown"`` and are never silently
    remapped.
    """
    if not isinstance(name, str) or not name.strip():
        return "unknown"
    meta = move_metadata(name)
    if meta.move_id not in _gen9_moves():
        return "unknown"
    if meta.stalling:
        return "stall"
    if meta.is_priority_offensive:
        return "priority"
    if meta.is_spread:
        return "spread"
    if meta.category == "physical":
        return "physical"
    if meta.category == "special":
        return "special"
    lower = name.strip().lower()
    if lower in SETUP_MOVES:
        return "setup"
    if lower in RESTORATIVE_MOVES:
        return "restorative"
    if lower in PIVOT_MOVES:
        return "pivot"
    if lower in REDIRECTION_MOVES:
        return "redirection"
    if lower in SPEED_CONTROL_MOVES:
        return "speed_control"
    if meta.category == "status":
        return "status"
    return "unknown"


# ---------------------------------------------------------------------------
# Component specification
# ---------------------------------------------------------------------------


@dataclass
class ComponentSpec:
    """Single, separately-reported component.

    ``sign`` is "+" for higher-is-better and "-" for lower-is-better.
    ``range`` is a (low, high) tuple of expected bounds.
    """

    name: str
    description: str
    sign: str
    range: Tuple[float, float]
    weight: float
    double_counted: bool = False
    preview_visible: bool = True


COMPONENT_SPECS: Tuple[ComponentSpec, ...] = (
    ComponentSpec(
        name="offensive_move_type_pressure",
        description=(
            "Mean best preview-visible damaging-move coverage across the 4 "
            "selected against the 6 opponents. Uses "
            "complete dual-type multiplier (max 4x = 1.0 "
            "normalised)."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=1.00,
    ),
    ComponentSpec(
        name="defensive_move_type_exposure",
        description=(
            "Average defensive resistance of the 4 selected "
            "against preview-visible opponent damaging moves."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=1.20,
    ),
    ComponentSpec(
        name="immunity_aware_pressure",
        description=(
            "Bonus when explicitly listed absorb/redirect "
            "abilities (Levitate, Water Absorb, Volt Absorb, "
            "Flash Fire, Storm Drain, Lightning Rod, Soundproof) "
            "match an opponent attacking type. Does NOT guess "
            "between multiple legal abilities."
        ),
        sign="+",
        range=(0.0, 2.0),
        weight=0.80,
    ),
    ComponentSpec(
        name="spread_move_pressure",
        description=(
            "Number of damaging spread moves in the plan "
            "(allAdjacent, allAdjacentFoes, all). Stalling and "
            "single-target moves do not count."
        ),
        sign="+",
        range=(0.0, 12.0),
        weight=0.60,
    ),
    ComponentSpec(
        name="priority_pressure",
        description=(
            "Number of offensive priority moves (priority > 0, "
            "not stalling, damaging). Protect is excluded even "
            "though it has priority=4."
        ),
        sign="+",
        range=(0.0, 8.0),
        weight=0.80,
    ),
    ComponentSpec(
        name="speed_control_access",
        description=(
            "1 if any Pokémon in the plan has Tailwind or "
            "Trick Room, else 0."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=0.80,
    ),
    ComponentSpec(
        name="fake_out_access",
        description=(
            "Number of Fake Out users in the plan. Capped at 1.0 "
            "in the displayed value; the duplicate-role penalty "
            "in the common evaluator discourages stacking."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=0.80,
    ),
    ComponentSpec(
        name="redirection_access",
        description=(
            "1 if any Pokémon in the plan has Follow Me, Rage "
            "Powder, Spotlight, or a Storm Drain / Lightning Rod "
            "ability. Else 0."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=0.80,
    ),
    ComponentSpec(
        name="protect_utility",
        description=(
            "Number of stalling moves in the plan. Capped low: "
            "Protect is utility, not offense."
        ),
        sign="+",
        range=(0.0, 4.0),
        weight=0.15,
    ),
    ComponentSpec(
        name="back_pivot_access",
        description=(
            "1 if the back carries a pivot move (U-turn, Volt "
            "Switch, Parting Shot, Baton Pass, Teleport, Chilly "
            "Reception). Capped at 1.0."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=0.50,
    ),
    ComponentSpec(
        name="recovery_access",
        description=(
            "1 if the plan carries a recovery move (Recover, "
            "Roost, Soft-Boiled, Slack Off, etc). Capped at 1.0."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=0.50,
    ),
    ComponentSpec(
        name="setup_with_support_compatibility",
        description=(
            "Counts the number of setup moves in the plan that "
            "have at least one supporting ally in the plan "
            "(Fake Out, Follow Me, Tailwind, Trick Room, "
            "Intimidate, pivot). No support -> 0; one supported "
            "setup = 1; two supported setups = 2 (capped)."
        ),
        sign="+",
        range=(0.0, 4.0),
        weight=0.60,
    ),
    ComponentSpec(
        name="physical_special_balance",
        description=(
            "1 - |physical_damaging - special_damaging| / 4. "
            "Rewards a balanced damaging mix. Range [0, 1]."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=0.50,
    ),
    ComponentSpec(
        name="shared_lead_weakness",
        description=(
            "Negative penalty: -1.0 per shared 4x weakness "
            "between the two leads and -0.5 per shared 2x "
            "weakness. 0 when no shared weakness."
        ),
        sign="-",
        range=(-4.0, 0.0),
        weight=1.00,
    ),
    ComponentSpec(
        name="lead_coverage_overlap",
        description=(
            "Negative: -(count of common super-effective "
            "attacking types between the two leads)/4. Penalises "
            "duplicate STAB coverage on the lead pair."
        ),
        sign="-",
        range=(-1.0, 0.0),
        weight=0.40,
    ),
    ComponentSpec(
        name="back_switch_defensive_coverage",
        description=(
            "Positive: number of back Pokémon whose defensive "
            "types are NOT 2x weak to any preview-visible "
            "opponent damaging move. "
            "Capped at 2.0."
        ),
        sign="+",
        range=(0.0, 2.0),
        weight=0.60,
    ),
    ComponentSpec(
        name="ability_item_synergy",
        description=(
            "Positive: explicit support-ability credit plus compatible "
            "Choice-item or Assault Vest credit on the lead pair. "
            "Item credit requires every listed, known move to be damaging. "
            "Missing items contribute nothing."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=0.40,
    ),
    ComponentSpec(
        name="dead_or_redundant_coverage",
        description=(
            "Negative: -(duplicate STAB type count)/4. "
            "Two STABs of the same type -> -0.25; three -> -0.5."
        ),
        sign="-",
        range=(-1.0, 0.0),
        weight=0.40,
    ),
    ComponentSpec(
        name="unsupported_setup_risk",
        description=(
            "Negative: -(count of setup moves without a "
            "supporting ally)/2. Capped at -1.0."
        ),
        sign="-",
        range=(-1.0, 0.0),
        weight=0.50,
    ),
    ComponentSpec(
        name="board_pressure_dual_slot",
        description=(
            "Positive: count of opposing slots (left + right) "
            "that the plan can meaningfully threaten. A "
            "threatening slot has at least one super-effective "
            "STAB from a back member. Capped at 2.0."
        ),
        sign="+",
        range=(0.0, 2.0),
        weight=0.60,
    ),
    ComponentSpec(
        name="worst_case_lead_pair_resilience",
        description=(
            "Positive: minimum threatened-slot fraction across all "
            "opponent lead pairs. 1 means every opponent "
            "lead pair is fully threatened by the plan; 0 means "
            "some opponent lead pair counters the plan."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=1.00,
    ),
)


def component_spec(name: str) -> ComponentSpec:
    for spec in COMPONENT_SPECS:
        if spec.name == name:
            return spec
    raise KeyError(f"Unknown component: {name!r}")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class LeadPairMatchup:
    """Matchup evaluation for one opponent lead pair (one of 15)."""

    opponent_lead_2: Tuple[str, str]
    component_values: Dict[str, float]
    component_total: float
    preview_visible: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opponent_lead_2": list(self.opponent_lead_2),
            "component_values": dict(self.component_values),
            "component_total": float(self.component_total),
            "preview_visible": dict(self.preview_visible),
        }


@dataclass
class MatchupEvaluation:
    """Full matchup evaluation of one 4/2/2 plan vs one opponent team."""

    team_size: int
    chosen_4: List[str]
    lead_2: List[str]
    back_2: List[str]
    opponent_team_size: int
    lead_pair_matchups: List[LeadPairMatchup] = field(default_factory=list)
    component_means: Dict[str, float] = field(default_factory=dict)
    uncertainty: Dict[str, float] = field(default_factory=dict)
    unknown_moves: List[str] = field(default_factory=list)
    fingerprint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "team_size": int(self.team_size),
            "chosen_4": list(self.chosen_4),
            "lead_2": list(self.lead_2),
            "back_2": list(self.back_2),
            "opponent_team_size": int(self.opponent_team_size),
            "fingerprint": str(self.fingerprint),
            "unknown_moves": list(self.unknown_moves),
            "lead_pair_matchups": [
                m.to_dict() for m in self.lead_pair_matchups
            ],
            "component_means": dict(self.component_means),
            "uncertainty": dict(self.uncertainty),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_species(species: str) -> str:
    return str(species).strip().lower()


def _all_attacker_multiplier(
    attacker: str, defender_types: Sequence[str]
) -> float:
    """Composite type multiplier.

    Delegates to ``doubles_mechanics.calculate_type_multiplier``
    to keep the canonical Gen 9 chart in one place. The
    shared module uses upper-case types internally; this
    wrapper accepts lower-case type strings from the VGC
    preview pipeline and returns the same float the
    pre-migration implementation returned.
    """
    from doubles_mechanics import calculate_type_multiplier
    if not attacker or not defender_types:
        return 1.0
    upper_defenders = [
        str(t).upper() for t in defender_types if t
    ]
    return calculate_type_multiplier(
        str(attacker).upper(), upper_defenders
    )


def _composite_multiplier(
    attacker: str, defender_types: Sequence[str]
) -> float:
    return _all_attacker_multiplier(attacker, defender_types)


def _is_pivot_keyword(name: str) -> bool:
    lower = str(name).strip().lower()
    return any(keyword in lower for keyword in PIVOT_MOVE_KEYWORDS)


def _ability_redirection(ability: str) -> bool:
    cat = get_ability_category(ability)
    return cat == "redirection"


# Explicitly listed absorb / redirect abilities. Matched against
# the species's open team-sheet ability. We never guess between
# multiple legal abilities; we only use the listed value.
#
# Compatibility shim: the keys are kept in the VGC natural
# language form (e.g. ``"water absorb"``) so the existing test
# surface and the inspector / analyzer paths continue to work
# unchanged. The values are stored as a tuple of lower-cased
# attacker type strings, identical to the pre-migration shape.
import doubles_mechanics as _dm_matchup
def _lc(t: str) -> str:
    return str(t).lower()
_ABSORB_TRANSLATION: Dict[str, Tuple[str, ...]] = {
    "levitate": tuple(_lc(t) for t in _dm_matchup.ABSORB_ABILITIES_BY_TYPE.get("levitate", ())),
    "water absorb": tuple(_lc(t) for t in _dm_matchup.ABSORB_ABILITIES_BY_TYPE.get("waterabsorb", ())),
    "volt absorb": tuple(_lc(t) for t in _dm_matchup.ABSORB_ABILITIES_BY_TYPE.get("voltabsorb", ())),
    "lightning rod": tuple(_lc(t) for t in _dm_matchup.ABSORB_ABILITIES_BY_TYPE.get("lightningrod", ())),
    "storm drain": tuple(_lc(t) for t in _dm_matchup.ABSORB_ABILITIES_BY_TYPE.get("stormdrain", ())),
    "flash fire": tuple(_lc(t) for t in _dm_matchup.ABSORB_ABILITIES_BY_TYPE.get("flashfire", ())),
    "soundproof": ("sound",),
    "thick fat": ("fire", "ice"),
    "sap sipper": tuple(_lc(t) for t in _dm_matchup.ABSORB_ABILITIES_BY_TYPE.get("sapsipper", ())),
    "motor drive": tuple(_lc(t) for t in _dm_matchup.ABSORB_ABILITIES_BY_TYPE.get("motordrive", ())),
}
ABSORB_ABILITIES: Dict[str, Tuple[str, ...]] = _ABSORB_TRANSLATION

# Storm drain / Lightning Rod are also redirection abilities, but
# here we only use them to count immunities (already covered by
# ABSORB_ABILITIES). The redirection component uses _redirection_moves
# in addition to ability-based redirection.


# ---------------------------------------------------------------------------
# Plan resolution
# ---------------------------------------------------------------------------


def _resolve_plan(
    team: Sequence[Mapping[str, Any]],
    chosen_4: Sequence[str],
    lead_2: Sequence[str],
    back_2: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Resolve chosen/lead/back to plan dicts. Returns (leads, backs).

    Validates strict 4/2/2 structure.
    """
    if team is None or len(team) != 6:
        raise MatchupEvaluatorError(
            f"Team must have exactly 6 Pokémon, got "
            f"{len(team) if team else 0}."
        )
    if chosen_4 is None or len(chosen_4) != 4:
        raise MatchupEvaluatorError(
            f"chosen_4 must contain exactly 4 species, "
            f"got {len(chosen_4) if chosen_4 else 0}."
        )
    if lead_2 is None or len(lead_2) != 2:
        raise MatchupEvaluatorError(
            f"lead_2 must contain exactly 2 species, "
            f"got {len(lead_2) if lead_2 else 0}."
        )
    if back_2 is None or len(back_2) != 2:
        raise MatchupEvaluatorError(
            f"back_2 must contain exactly 2 species, "
            f"got {len(back_2) if back_2 else 0}."
        )

    chosen_set = [_normalise_species(s) for s in chosen_4]
    if len(set(chosen_set)) != 4:
        raise MatchupEvaluatorError(
            f"chosen_4 must contain 4 unique species, "
            f"got {chosen_set}."
        )
    lead_set = [_normalise_species(s) for s in lead_2]
    back_set = [_normalise_species(s) for s in back_2]
    if not set(lead_set).issubset(set(chosen_set)):
        missing = set(lead_set) - set(chosen_set)
        raise MatchupEvaluatorError(
            f"Lead species {missing} not in chosen_4."
        )
    if not set(back_set).issubset(set(chosen_set)):
        missing = set(back_set) - set(chosen_set)
        raise MatchupEvaluatorError(
            f"Back species {missing} not in chosen_4."
        )
    if set(lead_set).intersection(set(back_set)):
        overlap = set(lead_set).intersection(set(back_set))
        raise MatchupEvaluatorError(
            f"Lead and back share species {overlap}."
        )
    if set(lead_set).union(set(back_set)) != set(chosen_set):
        raise MatchupEvaluatorError(
            f"Lead and back must cover chosen_4 exactly; "
            f"missing {set(chosen_set) - set(lead_set).union(set(back_set))}."
        )

    by_species: Dict[str, Dict[str, Any]] = {}
    for entry in team:
        key = _normalise_species(entry.get("species", ""))
        if key:
            by_species[key] = dict(entry)
    leads: List[Dict[str, Any]] = []
    backs: List[Dict[str, Any]] = []
    for species in lead_set:
        if species not in by_species:
            raise MatchupEvaluatorError(
                f"Lead species {species!r} not in team."
            )
        leads.append(by_species[species])
    for species in back_set:
        if species not in by_species:
            raise MatchupEvaluatorError(
                f"Back species {species!r} not in team."
            )
        backs.append(by_species[species])
    return leads, backs


# ---------------------------------------------------------------------------
# Plan-level component computation (independent of opponent lead pair)
# ---------------------------------------------------------------------------


def _plan_pokemon_damaging_types(
    pokemon: Mapping[str, Any]
) -> List[str]:
    """Return the distinct types of damaging moves on the open sheet."""
    damaging_types: List[str] = []
    for move in pokemon.get("moves", []) or []:
        metadata = move_metadata(str(move))
        move_type = metadata.move_type.strip().lower()
        if metadata.is_damaging and move_type and move_type not in damaging_types:
            damaging_types.append(move_type)
    return damaging_types


def _team_damaging_types(
    team: Sequence[Mapping[str, Any]],
) -> List[str]:
    """Return distinct damaging move types visible across a team."""
    damaging_types: List[str] = []
    for pokemon in team:
        for move_type in _plan_pokemon_damaging_types(pokemon):
            if move_type not in damaging_types:
                damaging_types.append(move_type)
    return damaging_types


def _pokemon_super_effective_attacker_types(
    pokemon: Mapping[str, Any],
    defender_types: Sequence[str],
) -> List[str]:
    """List of attacking types that are >= 2x against ``defender_types``."""
    if not defender_types:
        return []
    our_types = _plan_pokemon_damaging_types(pokemon)
    super_eff: List[str] = []
    for atk in our_types:
        if _all_attacker_multiplier(atk, defender_types) >= 2.0:
            super_eff.append(atk)
    return super_eff


def _plan_offensive_move_type_pressure(
    selected: Sequence[Mapping[str, Any]],
    opponent_team: Sequence[Mapping[str, Any]],
) -> float:
    """Preview-visible offensive pressure of the selected plan.

    Production scoring uses
    :func:`doubles_mechanics.evaluate_move_effectiveness` so
    the typed-ability block on the defender (e.g. a known
    ``Levitate`` opponent into Ground) propagates to the
    effective multiplier. We never call
    ``calculate_type_multiplier`` directly.
    """
    if not opponent_team:
        return 0.0
    per_opponent: List[float] = []
    for opponent in opponent_team:
        opp_types = get_species_types(opponent.get("species", ""))
        if not opp_types:
            continue
        opp_ability = str(opponent.get("ability", "") or "").strip()
        best = 0.0
        for pokemon in selected:
            # V2k.2: pass the open team-sheet attacker
            # ability through so Scrappy / Mind's Eye /
            # Mold Breaker bypasses apply.
            our_ability = str(
                pokemon.get("ability", "") or ""
            ).strip()
            for atk_type in _plan_pokemon_damaging_types(pokemon):
                res = _dm_matchup.evaluate_move_effectiveness(
                    move=None,
                    attacker=None,
                    target=None,
                    defender_types=opp_types,
                    target_ability=opp_ability,
                    attacker_ability=our_ability or None,
                    move_type_override=atk_type,
                )
                mult = res.effective_multiplier
                # Normalise: 4x -> 1.0, 2x -> 0.5
                best = max(best, min(mult / 4.0, 1.0))
        per_opponent.append(best)
    if not per_opponent:
        return 0.0
    return sum(per_opponent) / len(per_opponent)


def _plan_defensive_move_type_exposure(
    selected: Sequence[Mapping[str, Any]],
    opponent_team: Sequence[Mapping[str, Any]],
) -> float:
    """Preview-visible defensive exposure of the selected plan.

    Production scoring uses
    :func:`doubles_mechanics.evaluate_move_effectiveness` so
    the typed-ability block on our defender (e.g. a known
    ``Levitate`` Pokémon into Ground) propagates to the
    effective multiplier. We never call
    ``calculate_type_multiplier`` directly.
    """
    if not opponent_team:
        return 0.0
    per_pokemon: List[float] = []
    for pokemon in selected:
        our_types = get_species_types(pokemon.get("species", ""))
        if not our_types:
            continue
        our_ability = str(pokemon.get("ability", "")).strip()
        opponent_attack_types = _team_damaging_types(opponent_team)
        if not opponent_attack_types:
            continue
        # Worst multiplier across preview-visible damaging moves.
        worst = 1.0
        for atk in opponent_attack_types:
            res = _dm_matchup.evaluate_move_effectiveness(
                move=None,
                attacker=None,
                target=None,
                defender_types=our_types,
                target_ability=our_ability,
                move_type_override=atk,
            )
            m = res.effective_multiplier
            if m > worst:
                worst = m
        if worst >= 4.0:
            per_pokemon.append(0.0)
        elif worst >= 2.0:
            per_pokemon.append(0.5)
        else:
            per_pokemon.append(1.0)
    if not per_pokemon:
        return 0.0
    return sum(per_pokemon) / len(per_pokemon)


def _plan_immunity_aware_pressure(
    selected: Sequence[Mapping[str, Any]],
    opponent_team: Sequence[Mapping[str, Any]],
) -> float:
    """Count of explicit absorb-aware matchups.

    Production scoring uses
    :func:`doubles_mechanics.resolve_explicit_ability_interaction`
    so a single ability / move-type / target-type triple
    is checked in one canonical call. We do NOT drive
    scoring from the local ``ABSORB_ABILITIES`` shim --
    the shim is kept for the frozen V2i fingerprint only.
    """
    if not opponent_team:
        return 0.0
    matched = 0
    for pokemon in selected:
        ability = str(pokemon.get("ability", "")).strip()
        if not ability:
            continue
        opp_attack_types = _team_damaging_types(opponent_team)
        for atk in opp_attack_types:
            res = _dm_matchup.resolve_explicit_ability_interaction(
                move=None,
                attacker=None,
                target=None,
                target_ability=ability,
                move_type=atk,
            )
            if res.is_immune:
                matched += 1
    if matched == 0:
        return 0.0
    # Normalise by total opponent types.
    norm = matched / float(max(1, len(opponent_team)))
    return min(norm * 2.0, 2.0)


def _plan_spread_move_pressure(
    selected: Sequence[Mapping[str, Any]]
) -> float:
    count = 0
    for pokemon in selected:
        for move in pokemon.get("moves", []) or []:
            if move_metadata(move).is_spread:
                count += 1
    return float(count)


def _plan_priority_pressure(
    selected: Sequence[Mapping[str, Any]]
) -> float:
    count = 0
    for pokemon in selected:
        for move in pokemon.get("moves", []) or []:
            if move_metadata(move).is_priority_offensive:
                count += 1
    return float(count)


def _plan_speed_control_access(
    selected: Sequence[Mapping[str, Any]]
) -> float:
    for pokemon in selected:
        for move in pokemon.get("moves", []) or []:
            if _normalise_species(move) in {
                "tailwind", "trickroom"
            } or move.strip().lower() in SPEED_CONTROL_MOVES:
                return 1.0
    return 0.0


def _plan_fake_out_access(
    selected: Sequence[Mapping[str, Any]]
) -> float:
    count = 0
    for pokemon in selected:
        for move in pokemon.get("moves", []) or []:
            if move.strip().lower() == "fake out":
                count += 1
    return float(min(count, 1))


def _plan_redirection_access(
    selected: Sequence[Mapping[str, Any]]
) -> float:
    for pokemon in selected:
        for move in pokemon.get("moves", []) or []:
            if move.strip().lower() in REDIRECTION_MOVES:
                return 1.0
        if _ability_redirection(str(pokemon.get("ability", ""))):
            return 1.0
    return 0.0


def _plan_protect_utility(
    selected: Sequence[Mapping[str, Any]]
) -> float:
    count = 0
    for pokemon in selected:
        for move in pokemon.get("moves", []) or []:
            if move_metadata(move).stalling:
                count += 1
    return float(count)


def _plan_back_pivot_access(
    backs: Sequence[Mapping[str, Any]]
) -> float:
    for pokemon in backs:
        for move in pokemon.get("moves", []) or []:
            if _is_pivot_keyword(move):
                return 1.0
    return 0.0


def _plan_recovery_access(
    selected: Sequence[Mapping[str, Any]]
) -> float:
    for pokemon in selected:
        for move in pokemon.get("moves", []) or []:
            if move.strip().lower() in RESTORATIVE_MOVES:
                return 1.0
    return 0.0


def _plan_setup_with_support_compatibility(
    selected: Sequence[Mapping[str, Any]]
) -> float:
    """Count of setup moves with at least one supporting ally.

    Support: Fake Out, Follow Me, Tailwind, Trick Room, Intimidate
    ability, or a pivot move. No double counting.
    """
    support_present = False
    for pokemon in selected:
        for move in pokemon.get("moves", []) or []:
            ml = move.strip().lower()
            if (
                ml == "fake out"
                or ml in REDIRECTION_MOVES
                or ml in SPEED_CONTROL_MOVES
                or _is_pivot_keyword(ml)
            ):
                support_present = True
                break
        if support_present:
            break
        if get_ability_category(
            str(pokemon.get("ability", ""))
        ) == "intimidate":
            support_present = True
            break
    if not support_present:
        return 0.0
    setup_count = 0
    for pokemon in selected:
        for move in pokemon.get("moves", []) or []:
            if move.strip().lower() in SETUP_MOVES:
                setup_count += 1
    return float(min(setup_count, 4))


def _plan_physical_special_balance(
    selected: Sequence[Mapping[str, Any]]
) -> float:
    phys = 0
    spec = 0
    for pokemon in selected:
        for move in pokemon.get("moves", []) or []:
            meta = move_metadata(move)
            if meta.is_damaging:
                if meta.category == "physical":
                    phys += 1
                elif meta.category == "special":
                    spec += 1
    diff = abs(phys - spec)
    return max(0.0, 1.0 - diff / 4.0)


def _plan_lead_shared_weakness(
    leads: Sequence[Mapping[str, Any]]
) -> float:
    if len(leads) != 2:
        return 0.0
    lead_types = [get_species_types(p.get("species", "")) for p in leads]
    if any(not t for t in lead_types):
        return 0.0
    penalty = 0.0
    for atk in TYPE_CHART:
        weak = 0
        max_w = 0.0
        for d_t in lead_types:
            m = _composite_multiplier(atk, d_t)
            if m >= 2.0:
                weak += 1
                max_w = max(max_w, m)
        if weak >= 2:
            if max_w >= 4.0:
                penalty -= 1.0
            else:
                penalty -= 0.5
    return penalty


def _plan_lead_coverage_overlap(
    leads: Sequence[Mapping[str, Any]]
) -> float:
    if len(leads) != 2:
        return 0.0
    # Use all STAB attacking types of each lead.
    a_types = set(_plan_pokemon_damaging_types(leads[0]))
    b_types = set(_plan_pokemon_damaging_types(leads[1]))
    overlap = a_types & b_types
    return -float(len(overlap)) / 4.0


def _plan_back_switch_defensive_coverage(
    backs: Sequence[Mapping[str, Any]],
    leads: Sequence[Mapping[str, Any]],
    opponent_team: Sequence[Mapping[str, Any]],
) -> float:
    """Count backs not weak to any preview-visible opponent attack."""
    if not backs:
        return 0.0
    opponent_attack_types = _team_damaging_types(opponent_team)
    if not opponent_attack_types:
        return 0.0
    safe = 0
    for back in backs:
        our_types = get_species_types(back.get("species", ""))
        if not our_types:
            continue
        vulnerable = False
        for atk in opponent_attack_types:
            if _composite_multiplier(atk, our_types) >= 2.0:
                vulnerable = True
                break
        if not vulnerable:
            safe += 1
    return float(min(safe, 2))


def _plan_ability_item_synergy(
    leads: Sequence[Mapping[str, Any]]
) -> float:
    """Score explicit lead ability and item compatibility.

    Ability credit is limited to preview-visible support categories.
    Choice items and Assault Vest receive item credit only when every
    listed, known move is damaging. Missing items contribute nothing.
    """
    score = 0.0
    for lead in leads:
        ability_category = get_ability_category(
            str(lead.get("ability", ""))
        )
        if ability_category in {
            "intimidate", "redirection", "weather", "prankster", "speed"
        }:
            score += 0.5

        item_id = _move_id(str(lead.get("item", "")))
        moves = [
            move_metadata(str(move))
            for move in (lead.get("moves", []) or [])
        ]
        known_moves = [move for move in moves if move.move_id in _gen9_moves()]
        all_known_damaging = bool(known_moves) and all(
            move.is_damaging for move in known_moves
        )
        if (
            item_id in {"choiceband", "choicescarf", "choicespecs", "assaultvest"}
            and all_known_damaging
        ):
            score += 0.5
    return min(score, 1.0)


def _plan_dead_or_redundant_coverage(
    selected: Sequence[Mapping[str, Any]]
) -> float:
    """Negative: -(duplicate STAB type count)/4.

    Two STABs of the same type -> -0.25; three -> -0.5.
    """
    type_counter: Counter = Counter()
    for pokemon in selected:
        for t in _plan_pokemon_damaging_types(pokemon):
            type_counter[t] += 1
    penalty = 0.0
    for t, count in type_counter.items():
        if count > 1:
            penalty -= (count - 1) * 0.25
    # Cap at -1.0.
    return max(penalty, -1.0)


def _plan_unsupported_setup_risk(
    selected: Sequence[Mapping[str, Any]]
) -> float:
    support_present = False
    for pokemon in selected:
        for move in pokemon.get("moves", []) or []:
            ml = move.strip().lower()
            if (
                ml == "fake out"
                or ml in REDIRECTION_MOVES
                or ml in SPEED_CONTROL_MOVES
                or _is_pivot_keyword(ml)
            ):
                support_present = True
                break
        if support_present:
            break
        if get_ability_category(
            str(pokemon.get("ability", ""))
        ) == "intimidate":
            support_present = True
            break
    if support_present:
        return 0.0
    setup_count = 0
    for pokemon in selected:
        for move in pokemon.get("moves", []) or []:
            if move.strip().lower() in SETUP_MOVES:
                setup_count += 1
    penalty = -float(setup_count) / 2.0
    return max(penalty, -1.0)


def _plan_board_pressure_dual_slot(
    backs: Sequence[Mapping[str, Any]],
    opponent_lead_2: Sequence[Mapping[str, Any]],
) -> float:
    """Count of opposing lead slots that a back member can
    super-effectively threaten."""
    if not backs or len(opponent_lead_2) < 2:
        return 0.0
    threatened = 0
    for opp in opponent_lead_2[:2]:
        opp_types = get_species_types(opp.get("species", ""))
        if not opp_types:
            continue
        for back in backs:
            our_types = _plan_pokemon_damaging_types(back)
            for atk in our_types:
                if _composite_multiplier(atk, opp_types) >= 2.0:
                    threatened += 1
                    break
            else:
                continue
            break
    return float(min(threatened, 2))


def _plan_worst_case_lead_pair_resilience(
    selected: Sequence[Mapping[str, Any]],
    opponent_team: Sequence[Mapping[str, Any]],
) -> float:
    """Minimum fraction of an opponent lead pair threatened by the plan."""
    if len(opponent_team) < 2 or not selected:
        return 0.0
    min_mean = 1.0
    for i in range(len(opponent_team)):
        for j in range(i + 1, len(opponent_team)):
            opp_a = opponent_team[i]
            opp_b = opponent_team[j]
            opp_types_a = get_species_types(opp_a.get("species", ""))
            opp_types_b = get_species_types(opp_b.get("species", ""))
            if not opp_types_a and not opp_types_b:
                continue
            count = 0
            for ot in (opp_types_a, opp_types_b):
                if not ot:
                    continue
                threatened = False
                for pokemon in selected:
                    for atk in _plan_pokemon_damaging_types(pokemon):
                        if _composite_multiplier(atk, ot) >= 2.0:
                            threatened = True
                            break
                    if threatened:
                        break
                if threatened:
                    count += 1
            mean = count / 2.0
            if mean < min_mean:
                min_mean = mean
    return max(0.0, min(1.0, min_mean))


# ---------------------------------------------------------------------------
# Per-lead-pair matchup (uses opponent lead_2)
# ---------------------------------------------------------------------------


def _matchup_components_for_lead_pair(
    leads: Sequence[Mapping[str, Any]],
    backs: Sequence[Mapping[str, Any]],
    selected: Sequence[Mapping[str, Any]],
    opponent_lead_2: Sequence[Mapping[str, Any]],
    opponent_team: Sequence[Mapping[str, Any]],
) -> Dict[str, float]:
    """Compute every component for one opponent lead pair.

    The values that depend on the opponent's lead pair are
    board_pressure_dual_slot and worst_case_lead_pair_resilience.
    All other components are plan-level and identical across lead
    pairs. We return the full dict so the caller can aggregate
    identically.
    """
    components: Dict[str, float] = {}
    components["offensive_move_type_pressure"] = (
        _plan_offensive_move_type_pressure(selected, opponent_team)
    )
    components["defensive_move_type_exposure"] = (
        _plan_defensive_move_type_exposure(selected, opponent_team)
    )
    components["immunity_aware_pressure"] = (
        _plan_immunity_aware_pressure(selected, opponent_team)
    )
    components["spread_move_pressure"] = (
        _plan_spread_move_pressure(selected)
    )
    components["priority_pressure"] = (
        _plan_priority_pressure(selected)
    )
    components["speed_control_access"] = (
        _plan_speed_control_access(selected)
    )
    components["fake_out_access"] = (
        _plan_fake_out_access(selected)
    )
    components["redirection_access"] = (
        _plan_redirection_access(selected)
    )
    components["protect_utility"] = (
        _plan_protect_utility(selected)
    )
    components["back_pivot_access"] = (
        _plan_back_pivot_access(backs)
    )
    components["recovery_access"] = (
        _plan_recovery_access(selected)
    )
    components["setup_with_support_compatibility"] = (
        _plan_setup_with_support_compatibility(selected)
    )
    components["physical_special_balance"] = (
        _plan_physical_special_balance(selected)
    )
    components["shared_lead_weakness"] = (
        _plan_lead_shared_weakness(leads)
    )
    components["lead_coverage_overlap"] = (
        _plan_lead_coverage_overlap(leads)
    )
    components["back_switch_defensive_coverage"] = (
        _plan_back_switch_defensive_coverage(backs, leads, opponent_team)
    )
    components["ability_item_synergy"] = (
        _plan_ability_item_synergy(leads)
    )
    components["dead_or_redundant_coverage"] = (
        _plan_dead_or_redundant_coverage(selected)
    )
    components["unsupported_setup_risk"] = (
        _plan_unsupported_setup_risk(selected)
    )
    components["board_pressure_dual_slot"] = (
        _plan_board_pressure_dual_slot(backs, opponent_lead_2)
    )
    components["worst_case_lead_pair_resilience"] = (
        _plan_worst_case_lead_pair_resilience(selected, opponent_team)
    )
    return components


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MatchupEvaluatorError(ValueError):
    """Raised when a plan is malformed in a way that prevents evaluation."""


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    position = (len(ordered) - 1) * fraction
    lo = int(position)
    hi = min(lo + 1, len(ordered) - 1)
    weight = position - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


def _aggregate_uncertainty(
    matchup_totals: Sequence[float],
) -> Dict[str, float]:
    if not matchup_totals:
        return {
            "n_lead_pairs": 0,
            "mean_matchup": 0.0,
            "worst_matchup": 0.0,
            "lower_quartile_matchup": 0.0,
            "upper_quartile_matchup": 0.0,
            "matchup_variance": 0.0,
            "n_severely_bad": 0,
            "n_favorable": 0,
            "severe_threshold": 0.0,
            "favorable_threshold": 0.0,
        }
    ordered = sorted(float(v) for v in matchup_totals)
    n = len(ordered)
    mean = sum(ordered) / n
    # Variance: population variance for stability with small n.
    if n > 1:
        variance = sum((v - mean) ** 2 for v in ordered) / float(n - 1)
    else:
        variance = 0.0
    severe_threshold = mean - SEVERE_BAD_ZSCORE_THRESHOLD * (
        variance ** 0.5 if variance > 0 else 0.0
    )
    favorable_threshold = mean + FAVORABLE_ZSCORE_THRESHOLD * (
        variance ** 0.5 if variance > 0 else 0.0
    )
    n_severe = sum(1 for v in ordered if v < severe_threshold)
    n_favorable = sum(1 for v in ordered if v > favorable_threshold)
    return {
        "n_lead_pairs": int(n),
        "mean_matchup": float(mean),
        "worst_matchup": float(ordered[0]),
        "lower_quartile_matchup": float(_percentile(ordered, 0.25)),
        "upper_quartile_matchup": float(_percentile(ordered, 0.75)),
        "matchup_variance": float(variance),
        "n_severely_bad": int(n_severe),
        "n_favorable": int(n_favorable),
        "severe_threshold": float(severe_threshold),
        "favorable_threshold": float(favorable_threshold),
    }


# ---------------------------------------------------------------------------
# Opponent lead-pair enumeration
# ---------------------------------------------------------------------------


def enumerate_opponent_lead_pairs(
    opponent_team: Sequence[Mapping[str, Any]],
) -> List[Tuple[str, str]]:
    """Enumerate all 15 unordered opponent lead pairs from a 6-mon
    team. Order within each pair is sorted alphabetically by
    species so the enumeration is deterministic.
    """
    if not opponent_team or len(opponent_team) != 6:
        raise MatchupEvaluatorError(
            f"Opponent team must have exactly 6 Pokémon, got "
            f"{len(opponent_team) if opponent_team else 0}."
        )
    species = [
        _normalise_species(p.get("species", "")) for p in opponent_team
    ]
    if len(set(species)) != 6:
        raise MatchupEvaluatorError(
            "Opponent team must contain 6 unique species."
        )
    pairs: List[Tuple[str, str]] = []
    for i in range(6):
        for j in range(i + 1, 6):
            a, b = species[i], species[j]
            if a > b:
                a, b = b, a
            pairs.append((a, b))
    return pairs


# ---------------------------------------------------------------------------
# Unknown-move reporting
# ---------------------------------------------------------------------------


def _collect_unknown_moves(
    team: Sequence[Mapping[str, Any]],
) -> List[str]:
    unknown: List[str] = []
    for pokemon in team:
        for move in pokemon.get("moves", []) or []:
            if not isinstance(move, str) or not move.strip():
                continue
            if classify_move(move) == "unknown":
                unknown.append(move)
    return sorted(set(unknown))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def evaluate_matchup(
    team: Sequence[Mapping[str, Any]],
    opponent_team: Sequence[Mapping[str, Any]],
    chosen_4: Sequence[str],
    lead_2: Sequence[str],
    back_2: Sequence[str],
) -> MatchupEvaluation:
    """Evaluate one 4/2/2 plan against the visible opponent team.

    The plan is scored against all 15 legal opponent lead pairs and
    aggregated using mean, worst-case, lower-quartile, variance,
    severe-bad count, and favorable count.

    Returns a ``MatchupEvaluation`` with full per-pair component
    values, means, uncertainty, and the frozen fingerprint.
    """
    leads, backs = _resolve_plan(team, chosen_4, lead_2, back_2)
    selected = leads + backs
    if len(opponent_team) != 6:
        raise MatchupEvaluatorError(
            f"Opponent team must have exactly 6 Pokémon, got "
            f"{len(opponent_team) if opponent_team else 0}."
        )

    unknown_moves = _collect_unknown_moves(team)
    lead_pairs = enumerate_opponent_lead_pairs(opponent_team)
    if len(lead_pairs) != 15:
        raise MatchupEvaluatorError(
            f"Expected 15 opponent lead pairs, got {len(lead_pairs)}."
        )

    by_species: Dict[str, Dict[str, Any]] = {}
    for entry in opponent_team:
        key = _normalise_species(entry.get("species", ""))
        if key:
            by_species[key] = dict(entry)

    matchups: List[LeadPairMatchup] = []
    matchup_totals: List[float] = []
    component_means: Dict[str, float] = {
        spec.name: 0.0 for spec in COMPONENT_SPECS
    }
    preview_visible_flags = {
        spec.name: spec.preview_visible for spec in COMPONENT_SPECS
    }
    for pair in lead_pairs:
        opp_a = by_species[pair[0]]
        opp_b = by_species[pair[1]]
        components = _matchup_components_for_lead_pair(
            leads, backs, selected, [opp_a, opp_b], opponent_team
        )
        # Weighted total.
        total = 0.0
        for spec in COMPONENT_SPECS:
            value = components[spec.name]
            total += value * spec.weight
            component_means[spec.name] += value
        matchup_totals.append(total)
        matchups.append(LeadPairMatchup(
            opponent_lead_2=pair,
            component_values=components,
            component_total=total,
            preview_visible=dict(preview_visible_flags),
        ))

    n_pairs = len(matchups)
    for name in component_means:
        component_means[name] = component_means[name] / float(n_pairs)
    uncertainty = _aggregate_uncertainty(matchup_totals)
    return MatchupEvaluation(
        team_size=len(team),
        chosen_4=[str(s) for s in chosen_4],
        lead_2=[str(s) for s in lead_2],
        back_2=[str(s) for s in back_2],
        opponent_team_size=len(opponent_team),
        lead_pair_matchups=matchups,
        component_means=component_means,
        uncertainty=uncertainty,
        unknown_moves=unknown_moves,
        fingerprint=FROZEN_FINGERPRINT,
    )


# ---------------------------------------------------------------------------
# Per-plan score (the single number used by the analyzer)
# ---------------------------------------------------------------------------


def plan_score(evaluation: MatchupEvaluation) -> float:
    """Single-number plan score (mean weighted matchup total)."""
    return float(evaluation.uncertainty.get("mean_matchup", 0.0))


# ---------------------------------------------------------------------------
# Sanity self-test
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    sample_team = [
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
        {"species": "Rillaboom", "moves": []},
        {"species": "Iron Hands", "moves": []},
        {"species": "Kingambit", "moves": []},
        {"species": "Incineroar", "moves": []},
        {"species": "Garchomp", "moves": []},
        {"species": "Tornadus", "moves": []},
    ]
    evaluation = evaluate_matchup(
        sample_team, opp,
        ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
        ["Incineroar", "Tornadus"],
        ["Garchomp", "Rillaboom"],
    )
    print(f"Plan score: {plan_score(evaluation):.3f}")
    print(f"Fingerprint: {evaluation.fingerprint[:16]}...")
    print("Uncertainty:")
    for key, value in evaluation.uncertainty.items():
        print(f"  {key}: {value}")
    print(f"Unknown moves: {evaluation.unknown_moves}")
    print(f"Lead pairs evaluated: {len(evaluation.lead_pair_matchups)}")
