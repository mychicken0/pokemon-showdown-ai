#!/usr/bin/env python3
"""
VGC 2026 Phase V2j — Lead Matchup Evaluator v3.

A frozen, deterministic, preview-visible evaluator that scores our
selected lead pair directly against every one of the 15 unordered
opponent lead pairs. The score decomposes into auditable
components that distinguish known mechanics (immunity, type
effectiveness, spread pressure, priority, Fake Out, speed
control, redirection, Protect, setup vulnerability, pivoting,
physical/special balance, etc.) from explicit unknowns.

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
- exact visible base stats only when the local dex exposes them

Never used
----------
- battle labels (V2f win/loss tags)
- turn logs
- observed battle leads
- hidden EVs/IVs
- inferred abilities (except explicit absorb/levitate list matches)
- usage statistics
- online APIs

Battle labels may only be loaded for one diagnostic report
after this module's configuration is frozen. The analyzer
enforces that order.

Sign convention
---------------
- Higher score = better matchup for our lead pair.
- Negative components subtract from the total.
- No damage estimation: only categorical type-effectiveness
  buckets ("immune", "resisted", "neutral", "super_effective",
  "four_times_effective", "unresolved").

The 15+ components are defined in ``COMPONENT_SPECS``.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from team_preview_policy import (
    TYPE_CHART,
    get_ability_category,
    get_move_category,
    get_species_types,
)

import doubles_mechanics as _dm


# ---------------------------------------------------------------------------
# V2k.1 — Production helper: combined shared-mechanics call
# ---------------------------------------------------------------------------
#
# The VGC preview-visible plan evaluation must call
# ``doubles_mechanics.evaluate_move_effectiveness`` for every
# damaging move against every target. The combined result
# resolves the effective type (incl. dynamic form moves),
# applies the type chart, and checks the explicit team-sheet
# ability in a single call. Production scoring components
# read ``effective_multiplier`` and the audit flags from
# the returned dataclass; the per-component / per-pair code
# never falls back to a hand-rolled immunity table.
#
# An empty / None team-sheet ability is treated as
# "unknown" and NEVER blocks. The helper enforces that.


def _combined_move_matchup(
    move_id: str,
    attacker_types: Sequence[str],
    defender_types: Sequence[str],
    defender_ability: Optional[str] = None,
    attacker_move_type: Optional[str] = None,
    attacker_ability: Optional[str] = None,
) -> _dm.MoveEffectivenessResult:
    """Preview-visible combined move matchup for one
    (move, attacker, defender) triple.

    The caller passes the move id (any spelling form), the
    upper-case attacker and defender type lists, the
    open team-sheet defender ability (any spelling form, or
    ``None``/empty for "not visible / not singleton
    deducible"), and — when known from the open team
    sheet — the attacker's open team-sheet ability. The
    shared module resolves the effective type, applies the
    type chart, and applies the typed ability interaction.
    Production scoring components must consume
    ``result.effective_multiplier`` and the audit flags
    directly.

    This is the VGC preview-side adapter for the
    shared-mechanics layer. It does NOT call poke-env
    objects and does NOT read move metadata twice — the
    shared module's ``evaluate_move_effectiveness`` is
    authoritative for the multiplier.

    ``attacker_move_type`` overrides the move-id-based
    declared type lookup. Use it when the caller is iterating
    a type chart for a hypothetical matchup (e.g. shared
    weakness) and there is no real move id. Pass it as a
    single upper-case type string. The string is used as-is;
    it is NOT treated as a move name.

    ``attacker_ability`` enables Scrappy / Mind's Eye /
    Mold Breaker / Teravolt / Turboblaze bypasses for
    preview-side scoring. Pass the open team-sheet
    ability as-is (any spelling form); the shared
    module normalizes the id. The attacker ability
    must come from the V2f preview artifacts (or
    equivalent visible source) — it is NEVER inferred
    from the species string.
    """
    if attacker_move_type is not None:
        # Use the override directly; do NOT go through the
        # move-id-to-dex path.
        return _dm.evaluate_move_effectiveness(
            move=None,
            attacker=None,
            target=None,
            defender_types=list(defender_types),
            target_ability=defender_ability,
            attacker_ability=attacker_ability,
            move_type_override=attacker_move_type,
        )
    return _dm.evaluate_move_effectiveness(
        move=move_id,
        attacker=None,
        target=None,
        defender_types=list(defender_types),
        target_ability=defender_ability,
        attacker_ability=attacker_ability,
        move_id=_dm.normalize_id(move_id),
    )


# ---------------------------------------------------------------------------
# Frozen configuration
# ---------------------------------------------------------------------------
#
# These constants define the evaluator. Changing any of them is a
# ``vgc2026_lead_matchup_evaluator_v4`` change, not a tweak.
# ---------------------------------------------------------------------------

# Per-component weights. Higher means more important. All weights
# are positive so that no single dimension dominates and the
# sign convention is consistent (higher score = better lead
# matchup).
COMPONENT_WEIGHTS: Dict[str, float] = {
    "lead_offensive_effectiveness": 1.00,
    "lead_offensive_stab_pressure": 0.80,
    "lead_defensive_resistance": 1.00,
    "lead_immunity_aware_pressure": 0.80,
    "lead_spread_threat": 0.60,
    "lead_priority_threat": 0.80,
    "lead_fake_out_threat": 0.80,
    "lead_speed_control_pressure": 0.60,
    "lead_redirection_pressure": 0.60,
    "lead_protect_utility": 0.15,
    "lead_setup_vulnerability": 0.80,
    "lead_shared_weakness": 1.00,
    "lead_pivoting_pressure": 0.60,
    "lead_physical_special_balance": 0.40,
    "lead_target_concentration": 0.60,
    "lead_unresolved_count": 0.50,
    "back_switch_defensive_coverage": 0.50,
}

# Per-target-type bucket that classifies a single (move, defender)
# pair. Returned by ``_effectiveness_bucket`` and used as the
# granularity for every offensive/defensive component.
EFFECTIVENESS_BUCKETS: Tuple[str, ...] = (
    "immune",
    "resisted",
    "neutral",
    "super_effective",
    "four_times_effective",
    "unresolved",
)

# Spread targets in the local Gen 9 move dex.
SPREAD_TARGETS: Tuple[str, ...] = (
    "allAdjacent",
    "allAdjacentFoes",
    "all",
)

# Explicit absorb/redirect abilities that match the open
# team-sheet ability exactly. We never guess between multiple
# legal abilities.
#
# Compatibility shim: keys are kept in VGC natural-language
# form (e.g. ``"water absorb"``) so the existing test surface
# and the inspector / analyzer paths continue to work. Values
# are lower-cased attacker type tuples, sourced from
# ``doubles_mechanics.ABSORB_ABILITIES_BY_TYPE`` so the
# canonical type pairing is owned in exactly one place.
import doubles_mechanics as _dm_lead
def _lc_lead(t: str) -> str:
    return str(t).lower()
_ABSORB_ABILITIES_LEAD: Dict[str, Tuple[str, ...]] = {
    "levitate": tuple(_lc_lead(t) for t in _dm_lead.ABSORB_ABILITIES_BY_TYPE.get("levitate", ())),
    "water absorb": tuple(_lc_lead(t) for t in _dm_lead.ABSORB_ABILITIES_BY_TYPE.get("waterabsorb", ())),
    "volt absorb": tuple(_lc_lead(t) for t in _dm_lead.ABSORB_ABILITIES_BY_TYPE.get("voltabsorb", ())),
    "lightning rod": tuple(_lc_lead(t) for t in _dm_lead.ABSORB_ABILITIES_BY_TYPE.get("lightningrod", ())),
    "storm drain": tuple(_lc_lead(t) for t in _dm_lead.ABSORB_ABILITIES_BY_TYPE.get("stormdrain", ())),
    "flash fire": tuple(_lc_lead(t) for t in _dm_lead.ABSORB_ABILITIES_BY_TYPE.get("flashfire", ())),
    "soundproof": ("sound",),
    "thick fat": ("fire", "ice"),
    "sap sipper": tuple(_lc_lead(t) for t in _dm_lead.ABSORB_ABILITIES_BY_TYPE.get("sapsipper", ())),
    "motor drive": tuple(_lc_lead(t) for t in _dm_lead.ABSORB_ABILITIES_BY_TYPE.get("motordrive", ())),
}
ABSORB_ABILITIES: Dict[str, Tuple[str, ...]] = _ABSORB_ABILITIES_LEAD

# Hand-written role taxonomy. Kept small on purpose: unknown
# moves are reported explicitly and never silently remapped.
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
    "tailwind", "trick room", "icy wind",
})

# Setup vulnerability: opponent setup moves that we must answer.
# A defensive mon with Rest is "covered"; a setup-mon without a
# pivot into it is exposed.

# Severe-bad and favorable thresholds for the 15-pair aggregation.
SEVERE_BAD_ZSCORE_THRESHOLD: float = 0.5
FAVORABLE_ZSCORE_THRESHOLD: float = 0.5

# Bootstrap seed for paired bootstrap (analyzer). Fixed.
BOOTSTRAP_SEED: int = 20260613
N_BOOTSTRAP: int = 2000

# Increment whenever evaluator semantics change. This keeps the
# frozen fingerprint honest.
EVALUATOR_ALGORITHM_VERSION: str = "v2j.0-lead-matchup"


# ---------------------------------------------------------------------------
# Frozen configuration fingerprint
# ---------------------------------------------------------------------------
#
# This fingerprint is computed at import time and reflects the
# exact constants used to build any matchup result. Analyzers
# that read V2f battle labels must verify this fingerprint
# before loading labels.
# ---------------------------------------------------------------------------


def _freeze_fingerprint() -> str:
    payload: Dict[str, Any] = {
        "algorithm_version": EVALUATOR_ALGORITHM_VERSION,
        "component_weights": dict(COMPONENT_WEIGHTS),
        "effectiveness_buckets": list(EFFECTIVENESS_BUCKETS),
        "spread_targets": list(SPREAD_TARGETS),
        "absorb_abilities": {
            k: list(v) for k, v in ABSORB_ABILITIES.items()
        },
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


# FROZEN at module import time.
FROZEN_FINGERPRINT: str = _freeze_fingerprint()


# ---------------------------------------------------------------------------
# Public Move metadata adapter
# ---------------------------------------------------------------------------
#
# Wraps the local Gen 9 move dex. No private helpers leaked.
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _gen9_moves() -> Dict[str, Dict[str, Any]]:
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
    """One of: physical, special, status, stall, priority, spread,
    setup, restorative, pivot, redirection, speed_control, unknown.
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
    name: str
    description: str
    sign: str
    range: Tuple[float, float]
    weight: float
    double_counted: bool = False
    preview_visible: bool = True


COMPONENT_SPECS: Tuple[ComponentSpec, ...] = (
    ComponentSpec(
        name="lead_offensive_effectiveness",
        description=(
            "Mean effectiveness bucket (0..4) of our 2 leads' "
            "damaging moves against the 2 opponent lead Pokémon. "
            "0 = immune, 1 = resisted, 2 = neutral, 3 = "
            "super_effective, 4 = four_times_effective. 5 = "
            "unresolved (unknown)."
        ),
        sign="+",
        range=(0.0, 4.0),
        weight=1.00,
    ),
    ComponentSpec(
        name="lead_offensive_stab_pressure",
        description=(
            "Fraction of our damaging moves that share a type "
            "with the attacker (STAB). Encodes offensive "
            "coverage strength independent of opponent type."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=0.80,
    ),
    ComponentSpec(
        name="lead_defensive_resistance",
        description=(
            "Mean defensive-resistance bucket (0..4) of our 2 "
            "leads against the opponent lead pair's damaging "
            "moves. 0 = 4x weak, 1 = 2x weak, 2 = neutral, "
            "3 = resisted, 4 = immune."
        ),
        sign="+",
        range=(0.0, 4.0),
        weight=1.00,
    ),
    ComponentSpec(
        name="lead_immunity_aware_pressure",
        description=(
            "Bonus for our lead having an explicit absorb or "
            "Levitate ability that matches an opponent lead "
            "attacking type."
        ),
        sign="+",
        range=(0.0, 2.0),
        weight=0.80,
    ),
    ComponentSpec(
        name="lead_spread_threat",
        description=(
            "Count of damaging spread moves in our lead pair "
            "that threaten at least one opponent lead. Stalling "
            "and single-target moves do not count."
        ),
        sign="+",
        range=(0.0, 6.0),
        weight=0.60,
    ),
    ComponentSpec(
        name="lead_priority_threat",
        description=(
            "Count of offensive priority moves in our lead pair. "
            "Protect is excluded even though it has priority=4."
        ),
        sign="+",
        range=(0.0, 4.0),
        weight=0.80,
    ),
    ComponentSpec(
        name="lead_fake_out_threat",
        description=(
            "Count of Fake Out users in our lead pair. Capped at "
            "1 in the displayed value."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=0.80,
    ),
    ComponentSpec(
        name="lead_speed_control_pressure",
        description=(
            "1 if either lead has Tailwind, Trick Room, or Icy "
            "Wind, else 0."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=0.60,
    ),
    ComponentSpec(
        name="lead_redirection_pressure",
        description=(
            "1 if either lead has Follow Me, Rage Powder, or "
            "Spotlight, or has a Storm Drain / Lightning Rod "
            "ability. Else 0."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=0.60,
    ),
    ComponentSpec(
        name="lead_protect_utility",
        description=(
            "Count of stalling moves in our lead pair. Protect "
            "is utility, not offense."
        ),
        sign="+",
        range=(0.0, 2.0),
        weight=0.15,
    ),
    ComponentSpec(
        name="lead_setup_vulnerability",
        description=(
            "Negative: -(count of opponent lead setup moves "
            "that are not answered by our Fake Out / pivot / "
            "redirection / Intimidate). Capped at -2.0."
        ),
        sign="-",
        range=(-2.0, 0.0),
        weight=0.80,
    ),
    ComponentSpec(
        name="lead_shared_weakness",
        description=(
            "Negative: -1.0 per shared 4x weakness between the "
            "two leads and -0.5 per shared 2x weakness. 0 when "
            "no shared weakness."
        ),
        sign="-",
        range=(-4.0, 0.0),
        weight=1.00,
    ),
    ComponentSpec(
        name="lead_pivoting_pressure",
        description=(
            "Positive: 0.5 per pivot move in our lead pair "
            "(U-turn, Volt Switch, Parting Shot). Capped at 1.0."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=0.60,
    ),
    ComponentSpec(
        name="lead_physical_special_balance",
        description=(
            "1 - |physical_damaging - special_damaging| / 4. "
            "Rewards a balanced damaging mix. Range [0, 1]."
        ),
        sign="+",
        range=(0.0, 1.0),
        weight=0.40,
    ),
    ComponentSpec(
        name="lead_target_concentration",
        description=(
            "Count of opponent lead slots that our lead pair "
            "can super-effectively threaten with a damaging move. "
            "Capped at 2."
        ),
        sign="+",
        range=(0.0, 2.0),
        weight=0.60,
    ),
    ComponentSpec(
        name="lead_unresolved_count",
        description=(
            "Negative: -(count of unknown moves / unknown "
            "abilities in the lead pair)/4. Capped at -1.0."
        ),
        sign="-",
        range=(-1.0, 0.0),
        weight=0.50,
    ),
    ComponentSpec(
        name="back_switch_defensive_coverage",
        description=(
            "Count of back Pokémon whose defensive types are "
            "not 2x weak to any opponent lead's preview-visible "
            "damaging move. Capped at 2.0."
        ),
        sign="+",
        range=(0.0, 2.0),
        weight=0.50,
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
    """One opponent lead pair's matchup result against our lead pair."""

    opponent_lead_2: Tuple[str, str]
    component_values: Dict[str, float]
    component_total: float
    effectiveness_buckets: Dict[str, int] = field(default_factory=dict)
    preview_visible: Dict[str, bool] = field(default_factory=dict)
    uncertainty_reasons: List[str] = field(default_factory=list)
    speed_evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opponent_lead_2": list(self.opponent_lead_2),
            "component_values": dict(self.component_values),
            "component_total": float(self.component_total),
            "effectiveness_buckets": dict(self.effectiveness_buckets),
            "preview_visible": dict(self.preview_visible),
            "uncertainty_reasons": list(self.uncertainty_reasons),
            "speed_evidence": dict(self.speed_evidence),
        }


@dataclass
class LeadMatchupEvaluation:
    """Full lead-matchup evaluation of one 4/2/2 plan vs one opponent team.

    The evaluation scores the OUR LEAD PAIR against all 15
    unordered opponent lead pairs and aggregates the result.
    """

    team_size: int
    chosen_4: List[str]
    lead_2: List[str]
    back_2: List[str]
    opponent_team_size: int
    lead_pair_matchups: List[LeadPairMatchup] = field(default_factory=list)
    component_means: Dict[str, float] = field(default_factory=dict)
    uncertainty: Dict[str, float] = field(default_factory=dict)
    unknown_moves: List[str] = field(default_factory=list)
    unknown_abilities: List[str] = field(default_factory=list)
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
            "unknown_abilities": list(self.unknown_abilities),
            "lead_pair_matchups": [
                m.to_dict() for m in self.lead_pair_matchups
            ],
            "component_means": dict(self.component_means),
            "uncertainty": dict(self.uncertainty),
        }


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LeadMatchupEvaluatorError(ValueError):
    """Raised when a plan is malformed in a way that prevents evaluation."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_species(species: str) -> str:
    return str(species).strip().lower()


def _extract_visible_speed(pokemon: Mapping[str, Any]) -> Optional[float]:
    """Pure visible-speed extractor.

    Returns the exact effective speed from the preview /
    team record ONLY when explicitly present under one of
    these fields (in this order, all upper-case trimmed):

    - ``"speed"`` (e.g. ``120.0`` or ``120``)
    - ``"resolved_speed"``
    - ``"eff_speed"``

    Returns ``None`` when the speed is missing, hidden, or
    not a positive number. The function NEVER derives
    exact speed from species base stats alone, and NEVER
    guesses EVs, nature, Choice Scarf, boosts, paralysis,
    Tailwind, or Trick Room.
    """
    if pokemon is None:
        return None
    for key in ("speed", "resolved_speed", "eff_speed"):
        if key in pokemon and pokemon[key] is not None:
            try:
                value = float(pokemon[key])
            except (TypeError, ValueError):
                return None
            if value > 0:
                return value
    return None


def _extract_visible_trick_room(
    lead_pair: Sequence[Mapping[str, Any]],
) -> Optional[bool]:
    """Read the visible Trick Room state from a lead
    pair. Returns ``True`` / ``False`` when the field is
    explicitly present in any of the four lead records;
    returns ``None`` when the field state is hidden /
    not exposed. The function never guesses Tailwind or
    Trick Room from species.
    """
    if not lead_pair:
        return None
    for lead in lead_pair:
        if not isinstance(lead, Mapping):
            continue
        # Look for the canonical key first, then
        # common synonyms.
        for key in (
            "trick_room", "trickroom", "trick-room",
            "is_trick_room", "field_trick_room",
        ):
            if key in lead and lead[key] is not None:
                value = lead[key]
                if isinstance(value, bool):
                    return value
                if isinstance(value, str):
                    norm = value.strip().lower()
                    if norm in ("true", "1", "yes", "on"):
                        return True
                    if norm in ("false", "0", "no", "off"):
                        return False
                if isinstance(value, (int, float)):
                    return bool(value)
    return None


def _extract_visible_tailwind(
    lead_pair: Sequence[Mapping[str, Any]],
) -> Optional[bool]:
    """Read the visible Tailwind state from a lead pair.

    Returns ``True`` / ``False`` when the field is
    explicitly present in any of the four lead records;
    returns ``None`` when the field state is hidden /
    not exposed.
    """
    if not lead_pair:
        return None
    for lead in lead_pair:
        if not isinstance(lead, Mapping):
            continue
        for key in (
            "tailwind", "is_tailwind", "field_tailwind",
        ):
            if key in lead and lead[key] is not None:
                value = lead[key]
                if isinstance(value, bool):
                    return value
                if isinstance(value, str):
                    norm = value.strip().lower()
                    if norm in ("true", "1", "yes", "on"):
                        return True
                    if norm in ("false", "0", "no", "off"):
                        return False
                if isinstance(value, (int, float)):
                    return bool(value)
    return None


def _build_speed_evidence(
    our_leads: Sequence[Mapping[str, Any]],
    opponent_lead_2: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Speed evidence audit record for one (our_lead_pair,
    opponent_lead_pair) matchup.

    V2k.2 / V2k.3 — the function CALLS the shared
    ``doubles_mechanics.resolve_deterministic_speed_order``
    for every relevant lead-vs-lead comparison. The
    production scoring does NOT use a deterministic-speed
    bonus because the V2f preview artifacts do not expose
    base speed, nature, item, boosts, status, or field
    state for either side. The audit record is the single
    place where the shared resolver is consulted for the
    VGC preview-side speed evidence path.

    V2k.3 — the function also reads the visible Trick
    Room and Tailwind state from the lead pair
    dictionaries and forwards it to the shared resolver
    when present. When the field state is missing, the
    resolver receives ``None`` and returns
    ``unresolved`` with the appropriate reason.

    Behavior contract
    -----------------
    - The function never infers exact speed from species
      base stats alone. It only reads explicit visible
      fields (``speed`` / ``resolved_speed`` / ``eff_speed``).
    - It never guesses EVs, nature, Choice Scarf, boosts,
      paralysis, Tailwind, or Trick Room. When field
      state is missing the shared resolver returns
      ``unresolved`` and the audit record preserves that.
    - When the V2f artifacts expose Trick Room or
      Tailwind in the lead pair dicts, the shared
      resolver is consulted with the visible value and
      may return a resolved result.
    - Per-comparison evidence is stored with species,
      supplied speed values, result, reason.
    - Aggregate ``resolved_count`` and ``unresolved_count``
      are reported.
    - Production scoring components are not modified;
      no deterministic-speed bonus is introduced in this
      phase.
    """
    if not our_leads or len(opponent_lead_2) < 2:
        return {
            "resolved": False,
            "result": "unresolved",
            "reason": "missing_input",
            "resolved_count": 0,
            "unresolved_count": 0,
            "comparisons": [],
        }

    # V2k.3 — read the visible Trick Room state from
    # the lead pair. ``None`` when missing; ``True`` /
    # ``False`` when explicitly present. The Tailwind
    # state is recorded in the audit for future
    # consumption but the shared resolver does not
    # consume it yet (it only inverts the speed
    # comparison for Trick Room).
    full_pair = list(our_leads) + list(opponent_lead_2)
    trick_room = _extract_visible_trick_room(full_pair)
    tailwind = _extract_visible_tailwind(full_pair)

    comparisons: List[Dict[str, Any]] = []
    resolved_count = 0
    unresolved_count = 0
    for our_lead in our_leads[:2]:
        our_speed = _extract_visible_speed(our_lead)
        our_species = str(our_lead.get("species", "")).strip()
        for opp_lead in opponent_lead_2[:2]:
            opp_speed = _extract_visible_speed(opp_lead)
            opp_species = str(opp_lead.get("species", "")).strip()
            # If either speed is missing, call the shared
            # resolver with None and let it record
            # unresolved.
            res = _dm.resolve_deterministic_speed_order(
                our_speed, opp_speed,
                trick_room=trick_room,
            )
            comparison = {
                "our_species": our_species,
                "opp_species": opp_species,
                "our_supplied_speed": our_speed,
                "opp_supplied_speed": opp_speed,
                "trick_room_supplied": trick_room,
                "tailwind_supplied": tailwind,
                "result": res.result,
                "reason": res.reason,
                "information_explicitly_visible": (
                    res.information_explicitly_visible
                ),
            }
            comparisons.append(comparison)
            if res.result == "unresolved":
                unresolved_count += 1
            else:
                resolved_count += 1

    if resolved_count == 0:
        return {
            "resolved": False,
            "result": "unresolved",
            "reason": (
                "v2f_artifacts_lack_visible_speed" if (
                    unresolved_count == len(comparisons)
                    and all(
                        c["our_supplied_speed"] is None
                        and c["opp_supplied_speed"] is None
                        for c in comparisons
                    )
                ) else "no_resolved_comparisons"
            ),
            "resolved_count": resolved_count,
            "unresolved_count": unresolved_count,
            "comparisons": comparisons,
            "details": (
                "V2f preview artifacts do not expose "
                "visible base speed, nature, item, boosts, "
                "status, or field state (Tailwind / Trick "
                "Room). The shared resolver refuses to "
                "commit. No deterministic-speed bonus is "
                "awarded."
            ),
        }
    return {
        "resolved": True,
        "result": "mixed" if unresolved_count > 0 else "resolved",
        "reason": "ok" if unresolved_count == 0 else "mixed",
        "resolved_count": resolved_count,
        "unresolved_count": unresolved_count,
        "comparisons": comparisons,
    }


def _all_attacker_multiplier(
    attacker: str, defender_types: Sequence[str]
) -> float:
    """Composite type multiplier.

    Delegates to ``doubles_mechanics.calculate_type_multiplier``
    so the canonical Gen 9 chart lives in exactly one place.
    The shared module accepts upper-case type strings; this
    wrapper normalises the call site's lower-case type
    strings and returns the same float as the pre-migration
    code.
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
    return any(keyword in lower for keyword in PIVOT_MOVES)


def _ability_redirection(ability: str) -> bool:
    cat = get_ability_category(ability)
    return cat == "redirection"


def _effectiveness_bucket(multiplier: float) -> str:
    """Map a complete type multiplier to a categorical bucket.

    Returns one of: immune, resisted, neutral, super_effective,
    four_times_effective.
    """
    if multiplier <= 0.0:
        return "immune"
    if multiplier < 1.0:
        return "resisted"
    if multiplier == 1.0:
        return "neutral"
    if multiplier < 4.0:
        return "super_effective"
    return "four_times_effective"


def _defensive_bucket(multiplier: float) -> str:
    """Inverse perspective: how badly WE are hit by their move."""
    if multiplier <= 0.0:
        return "immune"  # 4-valued: 0/1/2/3/4
    if multiplier < 1.0:
        return "resisted"
    if multiplier == 1.0:
        return "neutral"
    if multiplier < 4.0:
        return "super_effective"
    return "four_times_effective"


# Reverse mapping for defensive scoring (lower is better for the
# attacker, higher is better for the defender). We use a numeric
# bucket that returns 0..4 where 4 = immune, 0 = 4x weak.
def _defensive_score_bucket(multiplier: float) -> int:
    if multiplier <= 0.0:
        return 4
    if multiplier < 1.0:
        return 3
    if multiplier == 1.0:
        return 2
    if multiplier < 4.0:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Plan resolution
# ---------------------------------------------------------------------------


def _resolve_plan(
    team: Sequence[Mapping[str, Any]],
    chosen_4: Sequence[str],
    lead_2: Sequence[str],
    back_2: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Validate strict 4/2/2 structure and return (leads, backs)."""
    if team is None or len(team) != 6:
        raise LeadMatchupEvaluatorError(
            f"Team must have exactly 6 Pokémon, got "
            f"{len(team) if team else 0}."
        )
    if chosen_4 is None or len(chosen_4) != 4:
        raise LeadMatchupEvaluatorError(
            f"chosen_4 must contain exactly 4 species, "
            f"got {len(chosen_4) if chosen_4 else 0}."
        )
    if lead_2 is None or len(lead_2) != 2:
        raise LeadMatchupEvaluatorError(
            f"lead_2 must contain exactly 2 species, "
            f"got {len(lead_2) if lead_2 else 0}."
        )
    if back_2 is None or len(back_2) != 2:
        raise LeadMatchupEvaluatorError(
            f"back_2 must contain exactly 2 species, "
            f"got {len(back_2) if back_2 else 0}."
        )

    chosen_set = [_normalise_species(s) for s in chosen_4]
    if len(set(chosen_set)) != 4:
        raise LeadMatchupEvaluatorError(
            f"chosen_4 must contain 4 unique species, "
            f"got {chosen_set}."
        )
    lead_set = [_normalise_species(s) for s in lead_2]
    back_set = [_normalise_species(s) for s in back_2]
    if not set(lead_set).issubset(set(chosen_set)):
        missing = set(lead_set) - set(chosen_set)
        raise LeadMatchupEvaluatorError(
            f"Lead species {missing} not in chosen_4."
        )
    if not set(back_set).issubset(set(chosen_set)):
        missing = set(back_set) - set(chosen_set)
        raise LeadMatchupEvaluatorError(
            f"Back species {missing} not in chosen_4."
        )
    if set(lead_set).intersection(set(back_set)):
        overlap = set(lead_set).intersection(set(back_set))
        raise LeadMatchupEvaluatorError(
            f"Lead and back share species {overlap}."
        )
    if set(lead_set).union(set(back_set)) != set(chosen_set):
        missing = set(chosen_set) - set(lead_set).union(set(back_set))
        raise LeadMatchupEvaluatorError(
            f"Lead and back must cover chosen_4 exactly; "
            f"missing {missing}."
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
            raise LeadMatchupEvaluatorError(
                f"Lead species {species!r} not in team."
            )
        leads.append(by_species[species])
    for species in back_set:
        if species not in by_species:
            raise LeadMatchupEvaluatorError(
                f"Back species {species!r} not in team."
            )
        backs.append(by_species[species])
    return leads, backs


# ---------------------------------------------------------------------------
# Per-Pokémon move metadata helpers
# ---------------------------------------------------------------------------


def _pokemon_damaging_types(
    pokemon: Mapping[str, Any]
) -> List[str]:
    """Distinct types of damaging moves on the open sheet."""
    damaging_types: List[str] = []
    for move in pokemon.get("moves", []) or []:
        metadata = move_metadata(str(move))
        move_type = metadata.move_type.strip().lower()
        if metadata.is_damaging and move_type and move_type not in damaging_types:
            damaging_types.append(move_type)
    return damaging_types


def _pokemon_damaging_move_count(
    pokemon: Mapping[str, Any]
) -> int:
    n = 0
    for move in pokemon.get("moves", []) or []:
        if move_metadata(str(move)).is_damaging:
            n += 1
    return n


def _team_damaging_types(
    team: Sequence[Mapping[str, Any]]
) -> List[str]:
    damaging_types: List[str] = []
    for pokemon in team:
        for move_type in _pokemon_damaging_types(pokemon):
            if move_type not in damaging_types:
                damaging_types.append(move_type)
    return damaging_types


# ---------------------------------------------------------------------------
# Lead-pair component computation
# ---------------------------------------------------------------------------


def _lead_offensive_effectiveness(
    our_leads: Sequence[Mapping[str, Any]],
    opponent_lead_2: Sequence[Mapping[str, Any]],
) -> Tuple[float, Dict[str, int], List[str]]:
    """Bucket effectiveness of our leads' damaging moves against the
    opponent lead pair.

    Returns the mean bucket value (0..4) over all (our-lead, opp-lead,
    damaging move) triples, the bucket counts, and any unknown
    reasons.

    This function calls the shared
    :func:`doubles_mechanics.evaluate_move_effectiveness` for
    every (move, defender) pair so the type-chart lookup and
    the typed-ability block are computed in a single place.
    The production scoring reads
    ``MoveEffectivenessResult.effective_multiplier`` and the
    audit flags directly. We never call
    ``calculate_type_multiplier`` directly here.
    """
    if not our_leads or len(opponent_lead_2) < 2:
        return 0.0, {}, []
    reasons: List[str] = []
    bucket_counts: Counter = Counter()
    total = 0.0
    n = 0
    for our_lead in our_leads:
        our_species = our_lead.get("species", "")
        our_types = get_species_types(our_species)
        # V2k.2 — pass the open team-sheet attacker
        # ability through. ``our_lead.get("ability", "")``
        # is the preview-visible team-sheet entry;
        # an empty / None value means "not visible" and
        # disables Scrappy / Mold Breaker bypass.
        our_ability = str(our_lead.get("ability", "") or "").strip()
        for opp in opponent_lead_2[:2]:
            opp_types = get_species_types(opp.get("species", ""))
            if not opp_types:
                reasons.append(
                    f"unknown opponent lead type: {opp.get('species', '')}"
                )
                bucket_counts["unresolved"] += 1
                n += 1
                continue
            opp_ability = str(opp.get("ability", "") or "").strip()
            for move in our_lead.get("moves", []) or []:
                meta = move_metadata(str(move))
                if not meta.is_damaging:
                    continue
                # Combined move matchup: type + dynamic type +
                # typed ability in a single shared-module call.
                # V2k.2: include the preview-visible attacker
                # ability so Scrappy / Mind's Eye / Mold
                # Breaker / Teravolt / Turboblaze bypasses
                # actually trigger.
                res = _combined_move_matchup(
                    move_id=str(move),
                    attacker_types=our_types,
                    defender_types=opp_types,
                    defender_ability=opp_ability,
                    attacker_ability=our_ability or None,
                )
                mult = res.effective_multiplier
                if res.is_unresolved or not res.dynamic_move_type_source or res.dynamic_move_type_source == "unresolved":
                    bucket_counts["unresolved"] += 1
                    n += 1
                    if res.reason:
                        reasons.append(
                            f"unknown damaging move type: {our_species} {move}"
                        )
                    continue
                bucket_counts[_effectiveness_bucket(mult)] += 1
                n += 1
                if mult <= 0.0:
                    total += 0.0
                elif mult < 1.0:
                    total += 1.0
                elif mult == 1.0:
                    total += 2.0
                elif mult < 4.0:
                    total += 3.0
                else:
                    total += 4.0
    if n == 0:
        return 0.0, dict(bucket_counts), reasons
    mean = total / float(n)
    return mean, dict(bucket_counts), reasons


def _lead_offensive_stab_pressure(
    our_leads: Sequence[Mapping[str, Any]]
) -> float:
    """Fraction of damaging moves that share a type with the
    attacker (STAB)."""
    total = 0
    stab = 0
    for pokemon in our_leads:
        our_types = set(get_species_types(pokemon.get("species", "")))
        for move in pokemon.get("moves", []) or []:
            meta = move_metadata(str(move))
            if meta.is_damaging:
                total += 1
                if meta.move_type in our_types:
                    stab += 1
    if total == 0:
        return 0.0
    return stab / float(total)


def _lead_defensive_resistance(
    our_leads: Sequence[Mapping[str, Any]],
    opponent_lead_2: Sequence[Mapping[str, Any]],
) -> Tuple[float, List[str]]:
    """Defensive resistance of our leads to opponent lead damaging
    moves. Returns the mean bucket (0..4, higher better).

    Production scoring uses the shared
    :func:`doubles_mechanics.evaluate_move_effectiveness` so
    the typed-ability block on the defender (e.g. a known
    ``Levitate`` Pokémon into Ground) propagates to the
    effective multiplier for the incoming opponent move
    whenever the open team sheet reveals such an ability.
    """
    if not our_leads or len(opponent_lead_2) < 2:
        return 0.0, []
    reasons: List[str] = []
    total = 0.0
    n = 0
    for our_lead in our_leads:
        our_types = get_species_types(our_lead.get("species", ""))
        if not our_types:
            reasons.append(
                f"unknown our lead type: {our_lead.get('species', '')}"
            )
            continue
        our_ability = str(our_lead.get("ability", "")).strip()
        for opp in opponent_lead_2[:2]:
            # V2k.2: read the OPPONENT's ability so the
            # shared module can apply Mold Breaker /
            # Teravolt / Turboblaze bypass when the
            # preview explicitly shows the opponent has
            # one of those abilities.
            opp_ability = str(opp.get("ability", "") or "").strip()
            for move in opp.get("moves", []) or []:
                meta = move_metadata(str(move))
                if not meta.is_damaging:
                    continue
                res = _combined_move_matchup(
                    move_id=str(move),
                    attacker_types=[],
                    defender_types=our_types,
                    defender_ability=our_ability,
                    attacker_ability=opp_ability or None,
                    attacker_move_type=meta.move_type and meta.move_type or None,
                )
                mult = res.effective_multiplier
                if meta.move_type and not res.is_unresolved:
                    total += _defensive_score_bucket(mult)
                    n += 1
                else:
                    reasons.append(
                        f"unknown opponent move type: {opp.get('species', '')} {move}"
                    )
    if n == 0:
        return 0.0, reasons
    return total / float(n), reasons


def _lead_immunity_aware_pressure(
    our_leads: Sequence[Mapping[str, Any]],
    opponent_lead_2: Sequence[Mapping[str, Any]],
) -> float:
    """1.0 per matched lead absorb ability against opponent lead
    attacking types. Capped at 2.0.

    Production scoring uses
    :func:`doubles_mechanics.resolve_explicit_ability_interaction`
    so the typed-ability block is checked in one canonical
    call. We do NOT drive scoring from the local
    ``ABSORB_ABILITIES`` shim -- the shim is kept for the
    frozen V2j fingerprint only.
    """
    if not our_leads or len(opponent_lead_2) < 2:
        return 0.0
    opp_attack_types: List[str] = []
    for opp in opponent_lead_2[:2]:
        for move in opp.get("moves", []) or []:
            meta = move_metadata(str(move))
            if meta.is_damaging and meta.move_type:
                if meta.move_type not in opp_attack_types:
                    opp_attack_types.append(meta.move_type)
    matched = 0
    for pokemon in our_leads:
        ability = str(pokemon.get("ability", "")).strip()
        if not ability:
            continue
        for atk in opp_attack_types:
            res = _dm.resolve_explicit_ability_interaction(
                move=None,
                attacker=None,
                target=None,
                target_ability=ability,
                move_type=atk,
            )
            if res.is_immune:
                matched += 1
                break
    return float(min(matched, 2))


def _lead_spread_threat(
    our_leads: Sequence[Mapping[str, Any]],
    opponent_lead_2: Sequence[Mapping[str, Any]],
) -> float:
    """Count of damaging spread moves in our leads that threaten at
    least one opponent lead.

    Production scoring uses
    :func:`doubles_mechanics.evaluate_move_effectiveness` so
    the typed-ability block on the defender (e.g. a known
    ``Levitate`` opponent into a Ground spread) propagates
    to the effective multiplier. We never call
    ``calculate_type_multiplier`` directly.
    """
    if not our_leads or len(opponent_lead_2) < 2:
        return 0.0
    count = 0.0
    for pokemon in our_leads:
        # V2k.2: pass the OUR lead's preview-visible
        # ability as attacker_ability so Mold Breaker /
        # Scrappy etc. trigger when the open team sheet
        # shows them.
        our_ability = str(pokemon.get("ability", "") or "").strip()
        for move in pokemon.get("moves", []) or []:
            meta = move_metadata(str(move))
            if not meta.is_spread:
                continue
            threatens_any = False
            for opp in opponent_lead_2[:2]:
                opp_types = get_species_types(opp.get("species", ""))
                if not opp_types:
                    continue
                opp_ability = str(opp.get("ability", "") or "").strip()
                res = _combined_move_matchup(
                    move_id=str(move),
                    attacker_types=[],
                    defender_types=opp_types,
                    defender_ability=opp_ability,
                    attacker_ability=our_ability or None,
                    attacker_move_type=meta.move_type,
                )
                if res.effective_multiplier > 0:
                    threatens_any = True
                    break
            if threatens_any:
                count += 1.0
    return min(count, 6.0)


def _lead_priority_threat(
    our_leads: Sequence[Mapping[str, Any]]
) -> float:
    count = 0
    for pokemon in our_leads:
        for move in pokemon.get("moves", []) or []:
            if move_metadata(str(move)).is_priority_offensive:
                count += 1
    return float(min(count, 4))


def _lead_fake_out_threat(
    our_leads: Sequence[Mapping[str, Any]],
    opponent_lead_pair: Optional[Sequence[Mapping[str, Any]]] = None,
) -> float:
    """Count of Fake Out users in our lead pair (capped at 1.0)
    multiplied by the shared
    :func:`doubles_mechanics.fake_out_legal_targets` count
    against the opponent lead pair.

    The opponent-lead-pair version is the production path
    used by ``_matchup_components_for_lead_pair``: it
    delegates the legality check to the shared module so
    Ghost / fainted / Wonder-Guard-style edge cases are
    applied in one canonical call. Two Ghost targets -> 0
    legal -> 0 pressure contribution. One Ghost + one legal
    target -> 1 legal -> partial pressure. Two legal
    targets -> 2 -> full pressure. ``Protect`` is never
    counted as offensive priority here because the
    shared module's ``is_priority_offensive`` filters it
    out by the ``stallingMove`` flag.

    VGC team-sheet dicts do not carry a ``types`` field;
    they only carry ``species``. The production adapter
    therefore resolves types by looking up the species in
    the local SPECIES_TYPES table. This makes the call
    work for real VGC dict targets, poke-env-like objects
    with a ``types`` attribute, and fainted / unknown
    targets that must NOT count as legal.

    The legacy single-argument signature is preserved for
    callers that don't have an opponent lead pair.
    """
    if not our_leads:
        return 0.0
    has_fake_out = any(
        _dm.move_is_fake_out(str(move))
        for pokemon in our_leads
        for move in pokemon.get("moves", []) or []
    )
    if not has_fake_out:
        return 0.0
    if opponent_lead_pair is None:
        return 1.0

    def _resolve_target_types(target: Any) -> List[str]:
        """Adapter: read types from a poke-env-like object
        or a VGC team-sheet dict. Returns upper-case
        Pokemon type strings. Empty list if the target
        has no resolvable type list.
        """
        if target is None:
            return []
        if isinstance(target, Mapping):
            if "types" in target and target["types"]:
                return [
                    str(t).upper() for t in target["types"] if t
                ]
            species = target.get("species", "")
            if species:
                # Use the team_preview_policy resolver. The
                # SPECIES_TYPES dict is keyed by lower-case
                # species with spaces / hyphens removed.
                from team_preview_policy import get_species_types
                return [
                    t.upper() for t in get_species_types(str(species))
                ]
            return []
        # poke-env-like object
        types_attr = getattr(target, "types", None)
        if types_attr:
            out: List[str] = []
            for t in types_attr:
                if t is None:
                    continue
                if hasattr(t, "name"):
                    out.append(str(t.name).upper())
                elif isinstance(t, str):
                    out.append(t.upper())
                else:
                    out.append(str(t).upper())
            return out
        return []

    legal = _dm.fake_out_legal_targets(
        "fakeout", opponent_lead_pair,
        resolve_target_types=_resolve_target_types,
    )
    if legal <= 0:
        return 0.0
    if legal >= 2:
        return 1.0
    return 0.5


def _lead_speed_control_pressure(
    our_leads: Sequence[Mapping[str, Any]]
) -> float:
    for pokemon in our_leads:
        for move in pokemon.get("moves", []) or []:
            if str(move).strip().lower() in SPEED_CONTROL_MOVES:
                return 1.0
    return 0.0


def _lead_redirection_pressure(
    our_leads: Sequence[Mapping[str, Any]]
) -> float:
    for pokemon in our_leads:
        for move in pokemon.get("moves", []) or []:
            if str(move).strip().lower() in REDIRECTION_MOVES:
                return 1.0
        if _ability_redirection(str(pokemon.get("ability", ""))):
            return 1.0
    return 0.0


def _lead_protect_utility(
    our_leads: Sequence[Mapping[str, Any]]
) -> float:
    count = 0
    for pokemon in our_leads:
        for move in pokemon.get("moves", []) or []:
            if move_metadata(str(move)).stalling:
                count += 1
    return float(min(count, 2))


def _lead_setup_vulnerability(
    our_leads: Sequence[Mapping[str, Any]],
    opponent_lead_2: Sequence[Mapping[str, Any]],
) -> float:
    """Count of opponent lead setup moves that are not answered by
    our Fake Out, pivot, redirection, or Intimidate.

    Capped at -2.0.
    """
    if not our_leads or len(opponent_lead_2) < 2:
        return 0.0
    support_present = False
    for pokemon in our_leads:
        for move in pokemon.get("moves", []) or []:
            ml = str(move).strip().lower()
            if (
                ml == "fake out"
                or ml in REDIRECTION_MOVES
                or ml in PIVOT_MOVES
            ):
                support_present = True
                break
        if support_present:
            break
        if get_ability_category(str(pokemon.get("ability", ""))) == "intimidate":
            support_present = True
            break
    if support_present:
        return 0.0
    n_setup = 0
    for opp in opponent_lead_2[:2]:
        for move in opp.get("moves", []) or []:
            if str(move).strip().lower() in SETUP_MOVES:
                n_setup += 1
    return max(-float(n_setup), -2.0)


def _lead_shared_weakness(
    our_leads: Sequence[Mapping[str, Any]]
) -> float:
    if len(our_leads) != 2:
        return 0.0
    lead_types = [get_species_types(p.get("species", "")) for p in our_leads]
    if any(not t for t in lead_types):
        return 0.0
    lead_abilities = [str(p.get("ability", "")).strip() for p in our_leads]
    penalty = 0.0
    for atk in TYPE_CHART:
        weak = 0
        max_w = 0.0
        for our_types, our_ability in zip(lead_types, lead_abilities):
            # Use the shared combined-mechanics call so the
            # typed-ability block on the defender (e.g. a
            # known ``Levitate`` on a lead) propagates to
            # the multiplier for hypothetical attacker types.
            res = _combined_move_matchup(
                move_id="",
                attacker_types=[],
                defender_types=our_types,
                defender_ability=our_ability,
                attacker_move_type=atk.upper(),
            )
            m = res.effective_multiplier
            if m >= 2.0:
                weak += 1
                max_w = max(max_w, m)
        if weak >= 2:
            if max_w >= 4.0:
                penalty -= 1.0
            else:
                penalty -= 0.5
    return penalty


def _lead_pivoting_pressure(
    our_leads: Sequence[Mapping[str, Any]]
) -> float:
    count = 0
    for pokemon in our_leads:
        for move in pokemon.get("moves", []) or []:
            if _is_pivot_keyword(str(move)):
                count += 1
    return float(min(count, 2)) * 0.5


def _lead_physical_special_balance(
    our_leads: Sequence[Mapping[str, Any]]
) -> float:
    phys = 0
    spec = 0
    for pokemon in our_leads:
        for move in pokemon.get("moves", []) or []:
            meta = move_metadata(str(move))
            if meta.is_damaging:
                if meta.category == "physical":
                    phys += 1
                elif meta.category == "special":
                    spec += 1
    diff = abs(phys - spec)
    return max(0.0, 1.0 - diff / 4.0)


def _lead_target_concentration(
    our_leads: Sequence[Mapping[str, Any]],
    opponent_lead_2: Sequence[Mapping[str, Any]],
) -> float:
    """Count of opponent lead slots threatened super-effectively.

    Production scoring uses
    :func:`doubles_mechanics.evaluate_move_effectiveness` so
    the typed-ability block on the defender (e.g. a known
    ``Levitate`` opponent into Ground) propagates to the
    effective multiplier. We never call
    ``calculate_type_multiplier`` directly.
    """
    if not our_leads or len(opponent_lead_2) < 2:
        return 0.0
    threatened = 0
    for opp in opponent_lead_2[:2]:
        opp_types = get_species_types(opp.get("species", ""))
        if not opp_types:
            continue
        opp_ability = str(opp.get("ability", "") or "").strip()
        threatened_this = False
        for pokemon in our_leads:
            our_ability = str(
                pokemon.get("ability", "") or ""
            ).strip()
            for move in pokemon.get("moves", []) or []:
                meta = move_metadata(str(move))
                if not meta.is_damaging:
                    continue
                res = _combined_move_matchup(
                    move_id=str(move),
                    attacker_types=[],
                    defender_types=opp_types,
                    defender_ability=opp_ability,
                    attacker_ability=our_ability or None,
                    attacker_move_type=meta.move_type,
                )
                if res.effective_multiplier >= 2.0:
                    threatened_this = True
                    break
            if threatened_this:
                break
        if threatened_this:
            threatened += 1
    return float(min(threatened, 2))


def _lead_unresolved_count(
    our_leads: Sequence[Mapping[str, Any]]
) -> float:
    unknown_moves = 0
    unknown_abilities = 0
    for pokemon in our_leads:
        for move in pokemon.get("moves", []) or []:
            if classify_move(str(move)) == "unknown":
                unknown_moves += 1
        ability = str(pokemon.get("ability", "")).strip().lower()
        if not ability:
            unknown_abilities += 1
        elif ability not in ABSORB_ABILITIES and get_ability_category(ability) == "other":
            # Recognised by category but not in our explicit allowlist.
            # Not a guaranteed "unknown" -- just counts as 0.
            pass
    total = unknown_moves + unknown_abilities
    return -min(float(total) / 4.0, 1.0)


def _back_switch_defensive_coverage(
    backs: Sequence[Mapping[str, Any]],
    opponent_lead_2: Sequence[Mapping[str, Any]],
) -> float:
    """Count of back Pokémon whose defensive types are not 2x weak
    to any preview-visible opponent lead damaging move.

    Production scoring uses
    :func:`doubles_mechanics.evaluate_move_effectiveness` so
    the typed-ability block on the back (e.g. a back
    Pokémon with known ``Levitate`` into Ground) propagates
    to the effective multiplier. We never call
    ``calculate_type_multiplier`` directly.
    """
    if not backs or len(opponent_lead_2) < 2:
        return 0.0
    if not opponent_lead_2:
        return 0.0
    safe = 0
    for back in backs:
        our_types = get_species_types(back.get("species", ""))
        if not our_types:
            continue
        back_ability = str(back.get("ability", "") or "").strip()
        vulnerable = False
        for opp in opponent_lead_2[:2]:
            # V2k.2: opponent's preview-visible ability
            # propagates as attacker_ability (e.g. Mold
            # Breaker bypass on Levitate).
            opp_ability = str(opp.get("ability", "") or "").strip()
            for move in opp.get("moves", []) or []:
                meta = move_metadata(str(move))
                if not meta.is_damaging or not meta.move_type:
                    continue
                res = _combined_move_matchup(
                    move_id=str(move),
                    attacker_types=[],
                    defender_types=our_types,
                    defender_ability=back_ability,
                    attacker_ability=opp_ability or None,
                    attacker_move_type=meta.move_type,
                )
                if res.effective_multiplier >= 2.0:
                    vulnerable = True
                    break
            if vulnerable:
                break
        if not vulnerable:
            safe += 1
    return float(min(safe, 2))


# ---------------------------------------------------------------------------
# Per-lead-pair component computation
# ---------------------------------------------------------------------------


def _matchup_components_for_lead_pair(
    our_leads: Sequence[Mapping[str, Any]],
    backs: Sequence[Mapping[str, Any]],
    opponent_lead_2: Sequence[Mapping[str, Any]],
) -> Tuple[Dict[str, float], Dict[str, int], List[str]]:
    """Compute every component for one opponent lead pair.

    Returns the component_values dict, the per-pair effectiveness
    bucket counts, and the uncertainty reasons.
    """
    components: Dict[str, float] = {}
    reasons: List[str] = []
    effectiveness_mean, bucket_counts, off_reasons = (
        _lead_offensive_effectiveness(our_leads, opponent_lead_2)
    )
    components["lead_offensive_effectiveness"] = effectiveness_mean
    reasons.extend(off_reasons)
    components["lead_offensive_stab_pressure"] = (
        _lead_offensive_stab_pressure(our_leads)
    )
    defensive_mean, def_reasons = _lead_defensive_resistance(
        our_leads, opponent_lead_2
    )
    components["lead_defensive_resistance"] = defensive_mean
    reasons.extend(def_reasons)
    components["lead_immunity_aware_pressure"] = (
        _lead_immunity_aware_pressure(our_leads, opponent_lead_2)
    )
    components["lead_spread_threat"] = _lead_spread_threat(
        our_leads, opponent_lead_2
    )
    components["lead_priority_threat"] = _lead_priority_threat(our_leads)
    components["lead_fake_out_threat"] = _lead_fake_out_threat(
        our_leads, opponent_lead_2
    )
    components["lead_speed_control_pressure"] = (
        _lead_speed_control_pressure(our_leads)
    )
    components["lead_redirection_pressure"] = (
        _lead_redirection_pressure(our_leads)
    )
    components["lead_protect_utility"] = _lead_protect_utility(our_leads)
    components["lead_setup_vulnerability"] = _lead_setup_vulnerability(
        our_leads, opponent_lead_2
    )
    components["lead_shared_weakness"] = _lead_shared_weakness(our_leads)
    components["lead_pivoting_pressure"] = _lead_pivoting_pressure(our_leads)
    components["lead_physical_special_balance"] = (
        _lead_physical_special_balance(our_leads)
    )
    components["lead_target_concentration"] = _lead_target_concentration(
        our_leads, opponent_lead_2
    )
    components["lead_unresolved_count"] = _lead_unresolved_count(our_leads)
    components["back_switch_defensive_coverage"] = (
        _back_switch_defensive_coverage(backs, opponent_lead_2)
    )
    return components, bucket_counts, reasons


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
    opponent_team: Sequence[Mapping[str, Any]]
) -> List[Tuple[str, str]]:
    """Enumerate all 15 unordered opponent lead pairs.

    Each pair is sorted alphabetically so the enumeration is
    deterministic.
    """
    if not opponent_team or len(opponent_team) != 6:
        raise LeadMatchupEvaluatorError(
            f"Opponent team must have exactly 6 Pokémon, got "
            f"{len(opponent_team) if opponent_team else 0}."
        )
    species = [
        _normalise_species(p.get("species", "")) for p in opponent_team
    ]
    if len(set(species)) != 6:
        raise LeadMatchupEvaluatorError(
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
# Unknown-move / unknown-ability reporting
# ---------------------------------------------------------------------------


def _collect_unknown_moves(
    team: Sequence[Mapping[str, Any]]
) -> List[str]:
    unknown: List[str] = []
    for pokemon in team:
        for move in pokemon.get("moves", []) or []:
            if not isinstance(move, str) or not move.strip():
                continue
            if classify_move(move) == "unknown":
                unknown.append(move)
    return sorted(set(unknown))


def _collect_unknown_abilities(
    team: Sequence[Mapping[str, Any]]
) -> List[str]:
    """List species whose ability is empty or unrecognised.

    An empty ability is reported as "<species>:unknown_ability".
    """
    unknown: List[str] = []
    for pokemon in team:
        ability = str(pokemon.get("ability", "")).strip().lower()
        species = str(pokemon.get("species", "")).strip().lower()
        if not ability:
            unknown.append(f"{species}:unknown_ability")
        elif (
            ability not in ABSORB_ABILITIES
            and get_ability_category(ability) == "other"
        ):
            unknown.append(f"{species}:unmatched_ability")
    return sorted(set(unknown))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def evaluate_lead_matchup(
    team: Sequence[Mapping[str, Any]],
    opponent_team: Sequence[Mapping[str, Any]],
    chosen_4: Sequence[str],
    lead_2: Sequence[str],
    back_2: Sequence[str],
) -> LeadMatchupEvaluation:
    """Score the OUR LEAD PAIR against all 15 opponent lead pairs.

    Returns a ``LeadMatchupEvaluation`` with per-pair component
    values, means, uncertainty, unknown reports, and the frozen
    fingerprint.
    """
    leads, backs = _resolve_plan(team, chosen_4, lead_2, back_2)
    if len(opponent_team) != 6:
        raise LeadMatchupEvaluatorError(
            f"Opponent team must have exactly 6 Pokémon, got "
            f"{len(opponent_team) if opponent_team else 0}."
        )

    unknown_moves = _collect_unknown_moves(team)
    unknown_abilities = _collect_unknown_abilities(team)
    lead_pairs = enumerate_opponent_lead_pairs(opponent_team)
    if len(lead_pairs) != 15:
        raise LeadMatchupEvaluatorError(
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
        components, bucket_counts, reasons = (
            _matchup_components_for_lead_pair(
                leads, backs, [opp_a, opp_b]
            )
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
            effectiveness_buckets=bucket_counts,
            preview_visible=dict(preview_visible_flags),
            uncertainty_reasons=sorted(set(reasons)),
            speed_evidence=_build_speed_evidence(leads, [opp_a, opp_b]),
        ))

    n_pairs = len(matchups)
    for name in component_means:
        component_means[name] = component_means[name] / float(n_pairs)

    uncertainty = _aggregate_uncertainty(matchup_totals)
    n_unknown_pairs = sum(
        1 for m in matchups
        if m.effectiveness_buckets.get("unresolved", 0) > 0
        or any("unknown" in r for r in m.uncertainty_reasons)
    )
    uncertainty["n_unknown_pairs"] = int(n_unknown_pairs)
    uncertainty["unknown_rate"] = (
        float(n_unknown_pairs) / float(n_pairs) if n_pairs else 0.0
    )

    return LeadMatchupEvaluation(
        team_size=len(team),
        chosen_4=[str(s) for s in chosen_4],
        lead_2=[str(s) for s in lead_2],
        back_2=[str(s) for s in back_2],
        opponent_team_size=len(opponent_team),
        lead_pair_matchups=matchups,
        component_means=component_means,
        uncertainty=uncertainty,
        unknown_moves=unknown_moves,
        unknown_abilities=unknown_abilities,
        fingerprint=FROZEN_FINGERPRINT,
    )


def lead_pair_score(evaluation: LeadMatchupEvaluation) -> float:
    """Single-number lead matchup score (mean weighted total)."""
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
    evaluation = evaluate_lead_matchup(
        sample_team, opp,
        ["Incineroar", "Tornadus", "Garchomp", "Rillaboom"],
        ["Incineroar", "Tornadus"],
        ["Garchomp", "Rillaboom"],
    )
    print(f"Lead pair score: {lead_pair_score(evaluation):.3f}")
    print(f"Fingerprint: {evaluation.fingerprint[:16]}...")
    print("Uncertainty:")
    for key, value in evaluation.uncertainty.items():
        print(f"  {key}: {value}")
    print(f"Unknown moves: {evaluation.unknown_moves}")
    print(f"Unknown abilities: {evaluation.unknown_abilities}")
    print(f"Lead pairs evaluated: {len(evaluation.lead_pair_matchups)}")
