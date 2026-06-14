#!/usr/bin/env python3
"""
Phase V2k — Shared Doubles Mechanics Layer.

The VGC 2026 evaluator pipeline and the Random Doubles player
both depend on the same Pokémon Showdown mechanics primitives
(type effectiveness, ability interactions, dynamic move types,
STAB, spread/priority/Fake Out/speed ordering, visibility
classification). This module is the single canonical home for
those primitives.

Design contract
---------------
- The module is pure: it does not import the large player class,
  it does not read battle outcomes, replay logs, network
  resources, or any global benchmark state.
- Battle-time callers (production Random Doubles player) may
  use only information already visible to the bot at decision
  time.
- Preview-time callers (VGC evaluators) may use only open
  team-sheet information: species, ability, moves, types from
  the local Gen 9 move dex.
- Unknown information stays unknown. The shared result types
  carry explicit ``unknown`` flags and ``reason`` codes so
  callers never have to infer hidden information.

Auditing guarantees
-------------------
- The function ``evaluate_move_effectiveness`` returns a
  ``MoveEffectivenessResult`` that distinguishes:
    * ``effective_multiplier``            (float)
    * ``is_type_immune``                  (bool)
    * ``is_explicit_ability_immune``      (bool)
    * ``explicit_ability_reason``         (str)
    * ``dynamic_move_type_source``        (str)
    * ``is_unresolved``                   (bool)
    * ``reason``                          (str)
    * ``information_explicitly_visible``  (bool)
- ``fake_out_legal_targets`` distinguishes
  Ghost-type / Flying / Levitate / Storm Drain targets.
- Speed ordering is deterministic and may return
  ``unresolved`` for any input that depends on hidden state.

Two pre-existing mature helpers are exposed as thin
compatibility wrappers:

- ``normalize_id`` is the canonical string-normalization used
  across the rest of the bot (``alnum only, lowercased``).
- ``get_effective_move_type`` is a public façade over
  ``resolve_effective_move_type`` and is the single point the
  Random Doubles player imports for Aura Wheel / Morpeko
  handling.

What this module does NOT do
-----------------------------
- It does not score moves.
- It does not choose actions.
- It does not read move / ability / item databases other than
  the installed ``poke-env`` Gen 9 move dex.
- It does not query network APIs.
- It does not log to disk.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.metadata import distribution
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    # Identity / normalization
    "normalize_id",
    "normalize_species",
    # Dynamic move type
    "DYNAMIC_TYPE_MOVES",
    "resolve_effective_move_type",
    "get_effective_move_type",
    "_get_declared_move_type",
    # Type effectiveness
    "TYPE_CHART",
    "calculate_type_multiplier",
    "IMMUNITY_TABLE",
    # Ability interactions
    "ABSORB_ABILITIES_BY_TYPE",
    "ATTACKER_IGNORES_ABILITY",
    "resolve_explicit_ability_interaction",
    # Move effectiveness (combined public API)
    "MoveEffectivenessResult",
    "evaluate_move_effectiveness",
    # Move classifications
    "MoveClassification",
    "classify_move",
    "move_is_damaging",
    "move_has_stab",
    "move_is_spread",
    "move_priority",
    "move_is_fake_out",
    "fake_out_legal_targets",
    # Spread / targeting
    "SPREAD_TARGETS",
    # Speed
    "SpeedOrdering",
    "resolve_deterministic_speed_order",
    # Visibility audit
    "VisibleInformation",
    "audit_visible_information",
    # Frosting on the cake: the type-specific absorb and
    # immunity ability allowlist. Kept in this module so any
    # caller that wants the canonical allowlist can import it
    # without going through a player or evaluator.
    "EXPLICIT_ABSORB_ABILITIES",
    "EXPLICIT_REDIRECTION_ABILITIES",
    "EXPLICIT_IMMUNITY_ABILITIES",
]


# ---------------------------------------------------------------------------
# 0. String normalization
# ---------------------------------------------------------------------------


def normalize_id(value: Any) -> str:
    """Canonical Pokémon-style identifier: lowercase, alnum only.

    Examples
    --------
    >>> normalize_id("Fake Out")
    'fakeout'
    >>> normalize_id("  Morpeko-Hangry ")
    'morpekohangry'
    """
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def normalize_species(value: Any) -> str:
    """Trim + lowercase a species name (kept separate from
    ``normalize_id`` because species tokens may contain spaces
    for display but the dex always stores alnum keys)."""
    return str(value).strip().lower()


# ---------------------------------------------------------------------------
# 1. Dynamic move types (Aura Wheel / Morpeko and similar)
# ---------------------------------------------------------------------------


# Map of normalized move id -> {attacker_base_species, form_map}
# The form_map keys are normalized form species names (lowercase,
# alnum only); values are the upper-cased effective types.
#
# Adding a new dynamic-type move here is the ONLY supported way
# to introduce one. The Random Doubles player and the VGC
# evaluators both consume ``resolve_effective_move_type``.
DYNAMIC_TYPE_MOVES: Dict[str, Dict[str, Any]] = {
    "aurawheel": {
        "attacker_base_species": "morpeko",
        "form_map": {
            "morpeko": "ELECTRIC",
            "morpekohangry": "DARK",
        },
    },
}


@lru_cache(maxsize=1)
def _gen9_moves() -> Dict[str, Dict[str, Any]]:
    """Return the local Gen 9 move dex from the installed
    poke-env package. The bot's own production player reads the
    same JSON file via poke-env. We do this so the shared module
    never imports poke-env directly."""
    path = distribution("poke-env").locate_file(
        "poke_env/data/static/moves/gen9moves.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _get_declared_move_type(move: Any) -> str:
    """Uppercase declared type string from a move-like object.

    Three input forms are supported:

    1. Move-like object with a ``.type`` attribute (PokemonType
       enum or a string). The attribute is read and
       upper-cased.
    2. Move-like object with a ``.id`` attribute and no
       ``.type`` attribute. The local Gen 9 move dex is
       consulted and the declared type is returned.
    3. String input. The local Gen 9 move dex is consulted.
       Unknown move ids return the empty string -- they
       MUST NOT be treated as a type name.

    In all three forms the returned type is uppercase. The
    function never infers a type from a move-id string when
    the move is unknown; doing so would turn a misspelled
    ability name into a fake type and silently propagate
    downstream.
    """
    if move is None:
        return ""

    # Form 1: object with a real type attribute.
    move_type = getattr(move, "type", None)
    if move_type is not None:
        if hasattr(move_type, "name"):
            return str(move_type.name).upper()
        return str(move_type).upper()

    # Form 2/3: derive a move-id string and look it up in
    # the local Gen 9 dex. The type, if any, is upper-cased
    # exactly once.
    move_id = ""
    if hasattr(move, "id") and move.id:
        move_id = normalize_id(move.id)
    elif isinstance(move, str):
        move_id = normalize_id(move)
    if not move_id:
        return ""
    data = _gen9_moves().get(move_id, {})
    if not data:
        return ""
    raw_type = data.get("type", "")
    if raw_type is None:
        return ""
    return str(raw_type).strip().upper()


def _get_move_entry(move: Any) -> Mapping[str, Any]:
    """Return local, visible move metadata for a move-like input."""
    if move is None:
        return {}
    entry = getattr(move, "entry", None)
    if isinstance(entry, Mapping):
        return entry
    move_id = ""
    if hasattr(move, "id") and getattr(move, "id", None):
        move_id = normalize_id(move.id)
    elif isinstance(move, str):
        move_id = normalize_id(move)
    if not move_id:
        return {}
    data = _gen9_moves().get(move_id, {})
    return data if isinstance(data, Mapping) else {}


def _get_move_category(move: Any) -> str:
    """Return ``PHYSICAL``, ``SPECIAL``, ``STATUS``, or ``""``."""
    category = getattr(move, "category", None)
    if category is not None:
        if hasattr(category, "name"):
            return str(category.name).strip().upper()
        value = str(category).strip().upper()
        if "." in value:
            value = value.rsplit(".", 1)[-1]
        return value
    return str(_get_move_entry(move).get("category", "")).strip().upper()


def _get_move_flags(move: Any) -> Mapping[str, Any]:
    """Return the move's canonical flag mapping."""
    flags = getattr(move, "flags", None)
    if isinstance(flags, Mapping):
        return flags
    entry_flags = _get_move_entry(move).get("flags", {})
    return entry_flags if isinstance(entry_flags, Mapping) else {}


@dataclass
class DynamicMoveTypeResult:
    """Result of resolving the effective type of a single move.

    Fields
    ------
    declared_type
        The type the move was registered with in the Gen 9 dex
        (e.g. ``"ELECTRIC"`` for Aura Wheel). Always uppercase.
    effective_type
        The type to use for STAB, immunity, ability, etc.
        Uppercase. May equal ``declared_type`` for static moves.
    source
        One of ``"static"``, ``"protocol_formechange:<form>"``,
        ``"species:<form>"``. ``"unresolved"`` if no form
        information is available for a known dynamic move.
    dynamic_applied
        True if the move is dynamic AND the effective type
        differs from declared.
    observed_form
        The protocol-observed or species-derived form key, or
        ``""`` for static moves.
    information_explicitly_visible
        True if the form was inferred from observable protocol
        state (replay scan, observed form change, or the
        attacker species string already updated after a form
        change). False if a species guess was used as a
        last-resort fallback.
    """

    declared_type: str = ""
    effective_type: str = ""
    source: str = "static"
    dynamic_applied: bool = False
    observed_form: str = ""
    information_explicitly_visible: bool = False


def resolve_effective_move_type(
    move: Any,
    attacker: Any = None,
    observed_form: Optional[str] = None,
    species_form: Optional[str] = None,
) -> DynamicMoveTypeResult:
    """Resolve the effective type of a move, applying form-aware
    dynamic type logic for moves in ``DYNAMIC_TYPE_MOVES``.

    The resolution order is:

    1. **Protocol-observed form** (``observed_form``) — the most
       trustworthy signal. The caller passes this in when the
       battle protocol has revealed a forme change for the
       attacker (e.g. ``morpekohangry``).
    2. **Species-derived form** (``species_form``) — used when
       the attacker species string itself has been updated to
       the new form, e.g. after the poke-env ``Pokemon`` object
       receives a ``-formechange`` event.
    3. **Static fallback** — the declared type.

    Parameters
    ----------
    move
        Anything with a ``.id``/``.type`` attribute or a string
        move id.
    attacker
        Unused by the deterministic form resolver but accepted
        for compatibility with the prior bot helper. The caller
        passes the *resolved* form via ``species_form`` so we
        never have to import the player class.
    observed_form
        Explicit protocol-observed form key. Normalized
        internally. Wins over every other input.
    species_form
        Species-derived form key from the poke-env Pokemon
        object's ``species`` attribute. Normalized internally.

    Returns
    -------
    DynamicMoveTypeResult
    """
    result = DynamicMoveTypeResult()
    result.declared_type = _get_declared_move_type(move)
    if not result.declared_type:
        return result

    move_id = ""
    if move is not None:
        if hasattr(move, "id") and move.id:
            move_id = normalize_id(move.id)
        elif isinstance(move, str):
            move_id = normalize_id(move)

    if move_id not in DYNAMIC_TYPE_MOVES:
        result.effective_type = result.declared_type
        return result

    config = DYNAMIC_TYPE_MOVES[move_id]
    form_map = config["form_map"]

    if observed_form:
        norm_observed = normalize_id(observed_form)
        if norm_observed in form_map:
            result.effective_type = form_map[norm_observed]
            result.source = f"protocol_formechange:{norm_observed}"
            result.dynamic_applied = True
            result.observed_form = norm_observed
            result.information_explicitly_visible = True
            return result

    if species_form:
        norm_species = normalize_id(species_form)
        if norm_species in form_map:
            result.effective_type = form_map[norm_species]
            result.source = f"species:{norm_species}"
            result.dynamic_applied = True
            result.observed_form = norm_species
            result.information_explicitly_visible = True
            return result

    # No form information at all. The move is dynamic but
    # the form is not visible. We MUST NOT guess.
    result.effective_type = result.declared_type
    result.source = "unresolved"
    return result


def get_effective_move_type(
    move: Any,
    attacker: Any = None,
    observed_form: Optional[str] = None,
    species_form: Optional[str] = None,
) -> str:
    """Backward-compatibility wrapper that returns just the
    effective type string. Existing call sites in the bot
    continue to work unchanged."""
    return resolve_effective_move_type(
        move, attacker, observed_form, species_form
    ).effective_type


# ---------------------------------------------------------------------------
# 2. Type effectiveness
# ---------------------------------------------------------------------------


# The local Gen 9 type chart. Mirrors
# ``team_preview_policy.TYPE_CHART`` but is owned here so VGC
# evaluators AND the Random Doubles player can both consume a
# single canonical source. Any change to this table MUST be
# accompanied by a parity-test update.
TYPE_CHART: Dict[str, Dict[str, float]] = {
    "normal": {"rock": 0.5, "ghost": 0.0, "steel": 0.5},
    "fire": {
        "fire": 0.5, "water": 0.5, "grass": 2.0, "ice": 2.0,
        "bug": 2.0, "rock": 0.5, "dragon": 0.5, "steel": 2.0,
    },
    "water": {
        "fire": 2.0, "water": 0.5, "grass": 0.5, "ground": 2.0,
        "rock": 2.0, "dragon": 0.5,
    },
    "electric": {
        "water": 2.0, "electric": 0.5, "grass": 0.5, "ground": 0.0,
        "flying": 2.0, "dragon": 0.5,
    },
    "grass": {
        "fire": 0.5, "water": 2.0, "grass": 0.5, "poison": 0.5,
        "ground": 2.0, "flying": 0.5, "bug": 0.5, "rock": 2.0,
        "dragon": 0.5, "steel": 0.5,
    },
    "ice": {
        "fire": 0.5, "water": 0.5, "grass": 2.0, "ice": 0.5,
        "ground": 2.0, "flying": 2.0, "dragon": 2.0, "steel": 0.5,
    },
    "fighting": {
        "normal": 2.0, "ice": 2.0, "poison": 0.5, "flying": 0.5,
        "psychic": 0.5, "bug": 0.5, "rock": 2.0, "ghost": 0.0,
        "dark": 2.0, "steel": 2.0, "fairy": 0.5,
    },
    "poison": {
        "grass": 2.0, "poison": 0.5, "ground": 0.5, "rock": 0.5,
        "ghost": 0.5, "steel": 0.0, "fairy": 2.0,
    },
    "ground": {
        "fire": 2.0, "electric": 2.0, "grass": 0.5, "poison": 2.0,
        "flying": 0.0, "bug": 0.5, "rock": 2.0, "steel": 2.0,
    },
    "flying": {
        "electric": 0.5, "grass": 2.0, "fighting": 2.0, "bug": 2.0,
        "rock": 0.5, "steel": 0.5,
    },
    "psychic": {
        "fighting": 2.0, "poison": 2.0, "psychic": 0.5,
        "dark": 0.0, "steel": 0.5,
    },
    "bug": {
        "fire": 0.5, "grass": 2.0, "fighting": 0.5, "poison": 0.5,
        "flying": 0.5, "psychic": 2.0, "ghost": 0.5, "dark": 2.0,
        "steel": 0.5, "fairy": 0.5,
    },
    "rock": {
        "fire": 2.0, "ice": 2.0, "fighting": 0.5, "ground": 0.5,
        "flying": 2.0, "bug": 2.0, "steel": 0.5,
    },
    "ghost": {
        "normal": 0.0, "psychic": 2.0, "ghost": 2.0, "dark": 0.5,
    },
    "dragon": {"dragon": 2.0, "steel": 0.5, "fairy": 0.0},
    "dark": {
        "fighting": 0.5, "psychic": 2.0, "ghost": 2.0,
        "dark": 0.5, "fairy": 0.5,
    },
    "steel": {
        "fire": 0.5, "water": 0.5, "electric": 0.5, "ice": 2.0,
        "rock": 2.0, "steel": 0.5, "fairy": 2.0,
    },
    "fairy": {
        "fire": 0.5, "fighting": 2.0, "poison": 0.5, "dragon": 2.0,
        "dark": 2.0, "steel": 0.5,
    },
}


# Canonical immunity table — Gen 9 type immunities. The keys
# are upper-case attacker types, the values are frozensets of
# upper-case defender types. Used as a fast-path fallback in
# ``calculate_type_multiplier`` so behavior is identical even
# when no dex is available.
IMMUNITY_TABLE: Dict[str, frozenset] = {
    "NORMAL": frozenset({"GHOST"}),
    "FIGHTING": frozenset({"GHOST"}),
    "GHOST": frozenset({"NORMAL"}),
    "GROUND": frozenset({"FLYING"}),
    "ELECTRIC": frozenset({"GROUND"}),
    "PSYCHIC": frozenset({"DARK"}),
    "POISON": frozenset({"STEEL"}),
    "DRAGON": frozenset({"FAIRY"}),
}


def calculate_type_multiplier(
    move_type: str,
    defender_types: Sequence[str],
) -> float:
    """Return the complete dual-type multiplier for ``move_type``
    against the (one or two) ``defender_types``.

    ``move_type`` is upper-case (e.g. ``"GROUND"``).
    ``defender_types`` are upper-case (e.g. ``["FIRE", "FLYING"]``).
    Returns ``0.0`` for type immunity, ``1.0`` for neutral.
    """
    if not move_type or not defender_types:
        return 1.0
    atk = move_type.upper()
    table = TYPE_CHART.get(atk.lower(), {})
    combined = 1.0
    for raw in defender_types:
        if raw is None:
            continue
        defender = str(raw).upper()
        if not defender:
            continue
        if atk in IMMUNITY_TABLE and defender in IMMUNITY_TABLE[atk]:
            return 0.0
        combined *= table.get(defender.lower(), 1.0)
    return combined


def _calculate_type_multiplier_with_ignored_immunity(
    move_type: str,
    defender_types: Sequence[str],
    ignored_attacker_type: Optional[str] = None,
    ignored_defender_type: Optional[str] = None,
) -> float:
    """Compute the dual-type multiplier for ``move_type`` against
    ``defender_types``, optionally ignoring one type-chart
    immunity (e.g. Normal→Ghost when Scrappy is active, or
    Ground→Flying when the target is grounded).

    The ignored pair removes only that one (atk, def) immunity
    from the IMMUNITY_TABLE lookup; every other defender type
    is multiplied normally. This is the canonical mechanics
    rule: a bypass removes only the immunizing effect, never
    the secondary type multiplier.

    - ``ignored_attacker_type`` is upper-case (e.g.
      ``"NORMAL"``). When the move type equals this AND the
      defender type is the matching immunizing pair member,
      the immunity is dropped. Multiple Scrappy / Mind's Eye
      rules are encoded as
      ``ignored_attacker_type=("NORMAL", "FIGHTING")`` and
      ``ignored_defender_type="GHOST"``.
    - ``ignored_defender_type`` is upper-case (e.g. ``"GHOST"``,
      ``"FLYING"``).
    - ``None`` or empty values mean "no bypass".
    """
    if not move_type or not defender_types:
        return 1.0
    atk = move_type.upper()
    table = TYPE_CHART.get(atk.lower(), {})
    # Normalize the bypass spec into a set of (atk, def) pairs
    # to ignore.
    ignored_pairs: set = set()
    ignored_atk_iter = (
        ignored_attacker_type
        if isinstance(ignored_attacker_type, (list, tuple, set, frozenset))
        else [ignored_attacker_type]
    )
    ignored_def_iter = (
        ignored_defender_type
        if isinstance(ignored_defender_type, (list, tuple, set, frozenset))
        else [ignored_defender_type]
    )
    for ig_atk in ignored_atk_iter:
        if not ig_atk:
            continue
        for ig_def in ignored_def_iter:
            if not ig_def:
                continue
            ignored_pairs.add(
                (str(ig_atk).upper(), str(ig_def).upper())
            )
    combined = 1.0
    for raw in defender_types:
        if raw is None:
            continue
        defender = str(raw).upper()
        if not defender:
            continue
        is_immunized = (
            atk in IMMUNITY_TABLE
            and defender in IMMUNITY_TABLE[atk]
            and (atk, defender) not in ignored_pairs
        )
        if is_immunized:
            return 0.0
        if (atk, defender) in ignored_pairs:
            # Bypass the immunity, treat the type as neutral
            # (1.0) for this slot. The other defender type
            # is still multiplied normally.
            continue
        combined *= table.get(defender.lower(), 1.0)
    return combined


def _scrappy_bypass_active(
    attacker_ability_norm: str,
    effective_type: str,
    defender_types: Sequence[str],
) -> bool:
    """Return True when Scrappy / Mind's Eye bypass is
    applicable.

    The bypass applies ONLY when:

    - attacker ability (normalized) is "scrappy" or "mindseye";
    - move effective type is NORMAL or FIGHTING;
    - the defender has a GHOST type.

    It is the canonical VGC / battle rule; a missing or
    non-matching attacker ability is NOT a bypass.
    """
    if attacker_ability_norm not in ("scrappy", "mindseye"):
        return False
    if effective_type not in ("NORMAL", "FIGHTING"):
        return False
    return "GHOST" in [str(t).upper() for t in defender_types if t]


def _grounded_bypass_active(
    target_grounded: bool, effective_type: str, defender_types: Sequence[str]
) -> bool:
    """Return True when the Ground-vs-Flying bypass applies.

    The bypass applies ONLY when the target is grounded
    (Thousand Arrows, Gravity, Smack Down, Ingrain) AND
    the move is Ground AND the defender has a FLYING type.
    """
    if not target_grounded:
        return False
    if effective_type != "GROUND":
        return False
    return "FLYING" in [str(t).upper() for t in defender_types if t]


# ---------------------------------------------------------------------------
# 3. Explicit ability interactions (absorbs, redirects, immunities)
# ---------------------------------------------------------------------------


# Map: defending ability (normalized id) -> the attacker types it
# absorbs or is immune to.  Upper-cased type strings. Empty
# tuple if the ability is not a typed absorb.
ABSORB_ABILITIES_BY_TYPE: Dict[str, Tuple[str, ...]] = {
    "waterabsorb": ("WATER",),
    "stormdrain": ("WATER",),
    "dryskin": ("WATER",),
    "voltabsorb": ("ELECTRIC",),
    "lightningrod": ("ELECTRIC",),
    "motordrive": ("ELECTRIC",),
    "flashfire": ("FIRE",),
    "wellbakedbody": ("FIRE",),
    "sapsipper": ("GRASS",),
    "eartheater": ("GROUND",),
    "levitate": ("GROUND",),
}

# Map: defending ability (normalized id) -> ("sound" or "bullet"
# flag) or ("explosion", "selfdestruct", "mindblown", "mistyexplosion")
ATTACKER_IGNORES_ABILITY: frozenset = frozenset(
    {"moldbreaker", "teravolt", "turboblaze"}
)

# Public allowlists — these names appear in many call sites
# across the project.  All entries are normalized ids.
EXPLICIT_ABSORB_ABILITIES: frozenset = frozenset(
    {
        "waterabsorb", "stormdrain", "dryskin",
        "voltabsorb", "lightningrod", "motordrive",
        "flashfire", "wellbakedbody", "sapsipper",
        "eartheater", "levitate",
    }
)

EXPLICIT_REDIRECTION_ABILITIES: frozenset = frozenset(
    {"stormdrain", "lightningrod"}
)

# Typed-ability blocks that Mold Breaker / Teravolt /
# Turboblaze bypass. Pokémon Showdown marks Good as Gold
# as breakable, so it is included here. The bypass for
# conditional abilities (Soundproof,
# Bulletproof, Damp, Magic Bounce, Overcoat) is also
# gated by the per-move block flag — the bypass only
# activates when the ability would actually block the
# move (e.g. Soundproof only blocks sound moves).
EXPLICIT_IMMUNITY_ABILITIES: frozenset = frozenset(
    EXPLICIT_ABSORB_ABILITIES
    | {
        "wonderguard", "soundproof", "bulletproof",
        "goodasgold", "magicbounce", "overcoat",
        "damp",
    }
)


@dataclass
class AbilityInteractionResult:
    """Result of resolving an attacker's move against a
    target's known ability.

    Fields
    ------
    is_immune
        True if the target's known ability hard-blocks the
        move (Levitate into Ground, Volt Absorb into Electric,
        ...).
    is_absorb
        True if the target gains HP or otherwise benefits.
        Always implies ``is_immune``.
    is_redirect
        True if the target redirects single-target moves
        (Storm Drain / Lightning Rod).
    reason
        Canonical reason string, e.g. ``"water_into_waterabsorb"``,
        ``"ground_into_levitate"``. Empty if not blocked.
    bypassed
        True if the attacker's known ability is a Mold Breaker
        / Teravolt / Turboblaze variant and the defender's
        ability is not protected by a higher-priority rule.
    ability
        The (normalized) ability id actually consulted, or
        ``""`` if no ability was known.
    information_explicitly_visible
        True if the ability came from a known / revealed /
        singleton-deduced source. False if the caller passed
        None / "" or a multi-possible ability that we refused
        to guess.
    """

    is_immune: bool = False
    is_absorb: bool = False
    is_redirect: bool = False
    reason: str = ""
    bypassed: bool = False
    ability: str = ""
    information_explicitly_visible: bool = False


def resolve_explicit_ability_interaction(
    move: Any,
    attacker: Any,
    target: Any,
    target_ability: Optional[str],
    attacker_ability: Optional[str] = None,
    move_id: Optional[str] = None,
    move_type: Optional[str] = None,
    extra_grounded: bool = False,
    defender_types: Optional[Sequence[str]] = None,
) -> AbilityInteractionResult:
    """Resolve a single explicit-ability interaction.

    The function is pure: it does not query ``Pokemon`` or poke-env
    for hidden state. The caller is responsible for the
    target_ability string. If ``target_ability`` is None or empty
    the result reports ``information_explicitly_visible=False``
    and never blocks.

    Both ``target_ability`` and ``attacker_ability`` are
    normalized through :func:`normalize_id`, so any of
    ``"waterabsorb"``, ``"Water Absorb"``, ``"water absorb"``,
    ``"water-absorb"`` are accepted identically. The
    same normalization applies to the
    Mold Breaker / Teravolt / Turboblaze bypass set.

    Parameters
    ----------
    move
        Optional move-like object used only to determine the
        canonical id. Optional because some call sites have
        already done that lookup.
    attacker
        Unused. Retained for call-site compatibility.
    target
        Unused. Retained for call-site compatibility.
    target_ability
        The known target ability, in any of the accepted
        spelling forms. ``None`` / empty string means
        "not visible / not singleton-deducible".
    attacker_ability
        The known attacker ability, in any of the accepted
        spelling forms. Used only to detect Mold Breaker /
        Teravolt / Turboblaze.
    move_id, move_type
        Optional precomputed move id and upper-cased move type.
    extra_grounded
        True if the target is already grounded by Gravity,
        Thousand Arrows, Smack Down, Ingrain, or any other
        battle-engine state. The Levitate check respects this.
    defender_types
        Explicit visible defender types. Required only for
        Wonder Guard's non-super-effective damaging-move rule.
    """
    result = AbilityInteractionResult()

    # Empty / None ability short-circuits. We do this BEFORE
    # the normalization step because ``normalize_id(None)``
    # would otherwise yield the string ``"none"``, which
    # is not what callers mean when they pass ``None``.
    if target_ability is None or str(target_ability).strip() == "":
        result.ability = ""
        result.information_explicitly_visible = False
        return result

    # Normalize target_ability through normalize_id. This
    # collapses every accepted spelling form (``"Water
    # Absorb"``, ``"water-absorb"``, ``"waterabsorb"``, ...)
    # to a single canonical key that matches the entries in
    # ``ABSORB_ABILITIES_BY_TYPE`` and
    # ``EXPLICIT_IMMUNITY_ABILITIES``.
    target_ability_norm = normalize_id(target_ability)
    attacker_ability_norm = normalize_id(attacker_ability)
    result.ability = target_ability_norm
    result.information_explicitly_visible = bool(target_ability_norm)

    if not move_type:
        move_type = _get_declared_move_type(move)
    move_type = (move_type or "").upper()
    if not move_type:
        return result

    if not move_id:
        if move is not None and hasattr(move, "id") and move.id:
            move_id = normalize_id(move.id)
        elif isinstance(move, str):
            move_id = normalize_id(move)
        else:
            move_id = ""

    bypass_active = (
        attacker_ability_norm in ATTACKER_IGNORES_ABILITY
    )

    move_category = _get_move_category(move)
    move_flags = _get_move_flags(move)

    # Compute the per-move WOULD-BE-BLOCKED flag for every
    # typed-ability entry that the defender's ability
    # could possibly block. Mold Breaker et al. bypass
    # only the abilities that would ACTUALLY block THIS
    # specific move. For example:
    # - Tackle (Normal) into Soundproof: NOT blocked
    #   (Soundproof blocks sound moves only) → no bypass
    # - Hyper Voice (Normal, sound flag) into Soundproof:
    #   blocked → bypass activates
    # - Fire move into Water Absorb: NOT blocked
    #   (Water Absorb blocks Water moves only) → no bypass
    # - Water move into Water Absorb: blocked → bypass
    #   activates
    # The per-move would-blocked flags are stored in
    # ``per_move_blocked`` and consulted BEFORE
    # ``bypassed`` is set. The bypass is a no-op for
    # ability/move combinations that would not have
    # interacted in the first place.
    per_move_blocked: Dict[str, bool] = {}

    # Wonder Guard blocks damaging moves that are not
    # super-effective. Type-chart immunities are handled
    # before this ability layer by evaluate_move_effectiveness.
    if result.ability == "wonderguard":
        # V2k.5 — Wonder Guard blocks non-super-effective
        # damaging moves (mult in (0, 1]) and lets
        # super-effective moves (mult >= 2.0) through.
        # Status moves are NOT blocked by Wonder Guard.
        # Type-chart immunities (mult == 0.0) are
        # handled before this ability layer.
        if (
            move_category in {"PHYSICAL", "SPECIAL"}
            and defender_types
        ):
            mult = calculate_type_multiplier(
                move_type, defender_types
            )
            per_move_blocked["wonderguard"] = (
                0.0 < mult <= 1.0
            )
        else:
            per_move_blocked["wonderguard"] = False
    # Soundproof blocks sound moves.
    if result.ability == "soundproof":
        per_move_blocked["soundproof"] = bool(move_flags.get("sound"))
    # Bulletproof blocks bullet moves.
    if result.ability == "bulletproof":
        per_move_blocked["bulletproof"] = bool(move_flags.get("bullet"))
    # Damp blocks self-destruct / explosion / mind blown /
    # misty explosion.
    if result.ability == "damp":
        per_move_blocked["damp"] = move_id in {
            "explosion", "selfdestruct", "mindblown",
            "mistyexplosion",
        }
    # Magic Bounce reflects status moves.
    if result.ability == "magicbounce":
        per_move_blocked["magicbounce"] = bool(
            move_flags.get("reflectable")
        )
    # Overcoat blocks powder / spore moves.
    if result.ability == "overcoat":
        per_move_blocked["overcoat"] = bool(move_flags.get("powder"))
    # Good as Gold blocks status moves targeting the holder.
    # Pokemon Showdown marks it breakable, so Mold Breaker,
    # Teravolt, and Turboblaze bypass this interaction.
    if result.ability == "goodasgold":
        per_move_blocked["goodasgold"] = move_category == "STATUS"

    # V2k.4 — Mold Breaker / Teravolt / Turboblaze
    # bypasses an ability only when that ability
    # would ACTUALLY block the move. A Tackle (Normal)
    # into Soundproof is NOT blocked by Soundproof
    # (no sound flag) → bypassed=False. A Hyper Voice
    # (Normal, sound) into Soundproof IS blocked →
    # bypassed=True.
    if bypass_active and result.ability in EXPLICIT_IMMUNITY_ABILITIES:
        # The ability must be in the bypass-eligible
        # set AND must have been computed as a real
        # per-move block above. For the absorb set
        # (Water Absorb, Levitate, Flash Fire, ...),
        # the per-move block depends on the move's
        # TYPE matching the absorb type. For the
        # conditional abilities (Wonder Guard,
        # Soundproof, Bulletproof, Damp, Magic Bounce,
        # Overcoat), the per-move block depends on the
        # move's properties (multiplier, sound flag,
        # bullet flag, etc.). For every other
        # EXPLICIT_IMMUNITY_ABILITIES entry not
        # computed above, the per-move block defaults
        # to False (we have no evidence the move
        # interacts with that ability), so the
        # bypass is a no-op.
        would_block: Optional[bool] = None
        if result.ability in per_move_blocked:
            would_block = per_move_blocked[result.ability]
        elif result.ability in EXPLICIT_ABSORB_ABILITIES:
            # Absorb abilities block only when the move
            # type matches the absorb type. Fire move
            # into Water Absorb → not blocked →
            # bypass does NOT activate.
            absorbed = ABSORB_ABILITIES_BY_TYPE.get(
                result.ability, ()
            )
            would_block = (
                bool(move_type) and move_type in absorbed
            )
        else:
            would_block = False
        if would_block is True:
            result.bypassed = True
            return result
        # The ability exists but would not block this
        # move. The bypass does not apply. Fall
        # through to the rest of the evaluation; the
        # move is not immune.

    # Sound moves -> Soundproof (always hard-blocked)
    if result.ability == "soundproof":
        if move_flags.get("sound"):
            result.is_immune = True
            result.reason = "sound_into_soundproof"
            return result

    # Bullet moves -> Bulletproof
    if result.ability == "bulletproof":
        if move_flags.get("bullet"):
            result.is_immune = True
            result.reason = "bullet_into_bulletproof"
            return result

    # Damp blocks self-destruct / explosion / mind blown / misty explosion
    if result.ability == "damp" and move_id in {
        "explosion", "selfdestruct", "mindblown", "mistyexplosion"
    }:
        result.is_immune = True
        result.reason = "explosion_into_damp"
        return result

    if result.ability == "wonderguard":
        if per_move_blocked.get("wonderguard", False):
            result.is_immune = True
            result.reason = "non_super_effective_into_wonderguard"
            return result
    if result.ability == "goodasgold":
        if move_category == "STATUS":
            result.is_immune = True
            result.reason = "goodasgold_status_block"
            return result
    # Magic Bounce: reflects status moves (but is
    # bypassed by Mold Breaker — it lives in
    # ``EXPLICIT_IMMUNITY_ABILITIES``).
    if result.ability == "magicbounce":
        if move_flags.get("reflectable"):
            result.is_immune = True
            result.reason = "magicbounce_status_block"
            return result
    # Overcoat: blocks powder / spore moves (bypassed
    # by Mold Breaker).
    if result.ability == "overcoat":
        if move_flags.get("powder"):
            result.is_immune = True
            result.reason = "overcoat_powder_block"
            return result

    if result.ability in ABSORB_ABILITIES_BY_TYPE:
        absorbed_types = ABSORB_ABILITIES_BY_TYPE[result.ability]
        if move_type in absorbed_types:
            # Levitate -> Ground: respect grounded exception
            if result.ability == "levitate" and move_type == "GROUND":
                if extra_grounded or move_id == "thousandarrows":
                    return result
            result.is_immune = True
            result.is_absorb = result.ability in {
                "waterabsorb", "stormdrain", "dryskin",
                "voltabsorb", "lightningrod", "motordrive",
                "flashfire", "wellbakedbody", "sapsipper",
                "eartheater",
            }
            result.is_redirect = result.ability in {
                "stormdrain", "lightningrod"
            }
            result.reason = _ability_reason_string(
                result.ability, move_type
            )
            return result

    return result


def _ability_reason_string(ability: str, move_type: str) -> str:
    """Map ``(ability, move_type)`` to a canonical reason string.

    The reason strings are used as audit labels and are part of
    the bot's audit contract. New entries MUST be added to
    ``_ALLOWED_DYNAMIC_ABSORB_REASONS`` in the bot if the bot
    is to use them.

    ``ability`` must be the normalized-id form. ``move_type``
    is upper-case. The result is lower-cased move_type joined
    to the normalized ability by ``_into_``.
    """
    return f"{move_type.lower()}_into_{ability}"


# ---------------------------------------------------------------------------
# 4. Combined public API — evaluate_move_effectiveness
# ---------------------------------------------------------------------------


@dataclass
class MoveEffectivenessResult:
    """Combined result of a single move-vs-target evaluation.

    See module docstring for the contract.
    """

    effective_multiplier: float = 1.0
    is_type_immune: bool = False
    is_explicit_ability_immune: bool = False
    is_explicit_ability_absorb: bool = False
    explicit_ability_reason: str = ""
    dynamic_move_type_source: str = "static"
    is_unresolved: bool = False
    reason: str = ""
    information_explicitly_visible: bool = False


def evaluate_move_effectiveness(
    move: Any,
    attacker: Any,
    target: Any,
    defender_types: Sequence[str],
    target_ability: Optional[str] = None,
    attacker_ability: Optional[str] = None,
    target_grounded: bool = False,
    move_id: Optional[str] = None,
    move_type_override: Optional[str] = None,
    observed_form: Optional[str] = None,
    species_form: Optional[str] = None,
) -> MoveEffectivenessResult:
    """Pure combined effectiveness check.

    All inputs are pre-resolved. The function does not query
    poke-env. The result distinguishes the four failure modes
    the audit contract requires (type immunity, ability
    immunity/absorption, dynamic type, unresolved).

    The function consults the canonical ``Scrappy`` and
    ``Mind's Eye`` allowlist when the attacker has either
    ability. Both abilities bypass the type immunity of
    Ghost to Normal / Fighting moves. This logic lives in
    the shared module so callers don't have to re-implement
    it. Bot callers that have already extracted
    ``attacker_ability`` may pass it directly.
    """
    result = MoveEffectivenessResult()

    # Step 1 — resolve effective move type
    dyn = resolve_effective_move_type(
        move, attacker, observed_form, species_form
    )
    if dyn.source == "unresolved":
        result.is_unresolved = True
        result.dynamic_move_type_source = "unresolved"
    else:
        result.dynamic_move_type_source = dyn.source

    # If the caller passed a ``move_type_override``, that
    # is the EXPLICIT effective type the caller wants the
    # move evaluated as (e.g. the bot's
    # ``get_effective_move_type`` resolved a form-aware
    # dynamic type). The override takes priority over the
    # form-aware dynamic-type resolver's static fallback.
    if move_type_override:
        effective_type = move_type_override
    else:
        effective_type = dyn.effective_type or ""
    if not effective_type:
        result.is_unresolved = True
        result.reason = "unknown_effective_type"
        return result

    # Step 1.5 — Scrappy / Mind's Eye bypass Ghost immunity
    # for Normal / Fighting moves. The shared module owns
    # this so bot and VGC callers do not have to re-implement
    # the rule. The bypass removes only the (NORMAL|FIGHTING,
    # GHOST) immunity; the secondary type multiplier is
    # preserved.
    attacker_ability_norm = normalize_id(attacker_ability)
    scrappy_bypass = _scrappy_bypass_active(
        attacker_ability_norm, effective_type, defender_types
    )

    # Step 1.6 — Thousand Arrows / Gravity / Smack Down /
    # Ingrain: when the target is grounded AND the move is
    # Ground, the (GROUND, FLYING) immunity is removed. The
    # shared module owns this rule. The secondary type
    # multiplier is preserved.
    ground_flying_bypass = _grounded_bypass_active(
        target_grounded, effective_type, defender_types
    )

    # Step 2 — type immunity / multiplier.
    # When a bypass is active, the ignored pair
    # (NORMAL|FIGHTING, GHOST) for Scrappy or (GROUND, FLYING)
    # for grounded is removed from the immunity lookup. Every
    # remaining defender type is multiplied normally, so
    # dual-type outcomes (0.5x, 2x, 0.25x, 4x) are preserved.
    if scrappy_bypass and ground_flying_bypass:
        # Both bypasses active; ignore both pairs.
        mult = _calculate_type_multiplier_with_ignored_immunity(
            effective_type, defender_types,
            ignored_attacker_type=("NORMAL", "FIGHTING", "GROUND"),
            ignored_defender_type=("GHOST", "FLYING"),
        )
    elif scrappy_bypass:
        mult = _calculate_type_multiplier_with_ignored_immunity(
            effective_type, defender_types,
            ignored_attacker_type=("NORMAL", "FIGHTING"),
            ignored_defender_type="GHOST",
        )
    elif ground_flying_bypass:
        mult = _calculate_type_multiplier_with_ignored_immunity(
            effective_type, defender_types,
            ignored_attacker_type="GROUND",
            ignored_defender_type="FLYING",
        )
    else:
        mult = calculate_type_multiplier(effective_type, defender_types)
    result.effective_multiplier = mult
    if mult <= 0.0:
        result.is_type_immune = True
        result.reason = (
            f"type_immunity:{effective_type}_vs_"
            f"{','.join(t for t in defender_types if t)}"
        )
        if target_ability and not target_grounded:
            abil_res = resolve_explicit_ability_interaction(
                move, attacker, target,
                target_ability, attacker_ability,
                move_id=move_id, move_type=effective_type,
                extra_grounded=target_grounded,
                defender_types=defender_types,
            )
            if abil_res.is_immune and not abil_res.bypassed:
                result.is_explicit_ability_immune = True
                result.is_explicit_ability_absorb = abil_res.is_absorb
                result.explicit_ability_reason = abil_res.reason
                result.information_explicitly_visible = (
                    abil_res.information_explicitly_visible
                )
        return result

    # Step 3 — explicit ability check (only if not already immune)
    if target_ability:
        abil_res = resolve_explicit_ability_interaction(
            move, attacker, target,
            target_ability, attacker_ability,
            move_id=move_id, move_type=effective_type,
            extra_grounded=target_grounded,
            defender_types=defender_types,
        )
        if abil_res.is_immune and not abil_res.bypassed:
            result.is_explicit_ability_immune = True
            result.is_explicit_ability_absorb = abil_res.is_absorb
            result.explicit_ability_reason = abil_res.reason
            result.effective_multiplier = 0.0
            result.reason = abil_res.reason
        elif abil_res.bypassed:
            result.information_explicitly_visible = True
            result.explicit_ability_reason = (
                f"bypassed_by_{abil_res.ability or 'unknown'}"
            )
        else:
            result.information_explicitly_visible = (
                abil_res.information_explicitly_visible
            )

    return result


def resolve_type_immunity(
    move: Any,
    attacker: Any,
    target: Any,
    *,
    attacker_ability: Optional[str] = None,
    target_ability: Optional[str] = None,
    target_grounded: bool = False,
    move_type: Optional[str] = None,
    move_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """Convenience wrapper that returns ``(is_immune, reason)``.

    The shared module owns the type-immunity decision, the
    Thousand Arrows / Levitate / Gravity / Smack Down /
    Scrappy / Mind's Eye exceptions, and the typed-ability
    block. Bot callers convert their poke-env state to shared
    inputs and call this function. ``target_grounded`` should
    be ``True`` if Thousand Arrows is being used, Gravity is
    active, Smack Down / Ingrain has grounded the target, or
    any other battle-engine state has grounded the target.

    Returns ``(False, "")`` if the move is not type-immune.
    """
    res = evaluate_move_effectiveness(
        move=move,
        attacker=attacker,
        target=target,
        defender_types=_target_types(target),
        target_ability=target_ability,
        attacker_ability=attacker_ability,
        target_grounded=target_grounded,
        move_id=move_id,
        move_type_override=move_type,
    )
    if res.is_type_immune and not res.is_explicit_ability_immune:
        return True, res.reason
    if res.effective_multiplier <= 0.0 and (
        res.is_type_immune or res.is_explicit_ability_immune
    ):
        return True, res.reason or "immune"
    return False, ""


def _target_types(target: Any) -> List[str]:
    """Extract upper-case defender type list from a poke-env
    target. The shared module does NOT own poke-env objects;
    this helper is the only place where poke-env attributes
    are read. The result is upper-case type strings; empty
    when the target is unknown or uninitialised.
    """
    if target is None:
        return []
    out: List[str] = []
    types_attr = getattr(target, "types", None)
    if types_attr:
        for t in types_attr:
            if t is None:
                continue
            if hasattr(t, "name"):
                out.append(str(t.name).upper().strip())
            elif isinstance(t, str):
                out.append(t.upper().strip())
            else:
                out.append(str(t).upper().strip())
        if out:
            return out
    # Fallback: target.type_1 / target.type_2 (poke-env
    # internal layout)
    for attr in ("type_1", "type_2"):
        v = getattr(target, attr, None)
        if v is None:
            continue
        v_str = v.name if hasattr(v, "name") else str(v)
        if v_str:
            out.append(v_str.upper().strip())
    return out


def resolve_extra_grounded(
    move: Any,
    target: Any,
    battle: Any = None,
    move_id: Optional[str] = None,
) -> bool:
    """Return ``True`` if the target is grounded by a battle-engine
    effect that bypasses Levitate for the current move. The
    shared module owns Thousand Arrows, Gravity, Smack Down,
    and Ingrain detection so the bot wrapper does not have to
    re-implement the rules. The caller passes the
    poke-env ``battle`` object; the function reads only
    ``battle.fields`` and target volatile status to make the
    decision.

    This helper is for BATTLE-TIME callers. Preview-time
    callers must pass ``target_grounded=False`` and rely on
    the audit reason code instead.
    """
    norm_move_id = move_id
    if norm_move_id is None:
        raw_id = getattr(move, "id", "")
        if isinstance(raw_id, str):
            norm_move_id = normalize_id(raw_id)
    if norm_move_id == "thousandarrows":
        return True
    if battle is None:
        return False
    fields = getattr(battle, "fields", None) or {}
    for field in fields:
        field_name = getattr(field, "name", str(field))
        if "gravity" in field_name.lower():
            return True
        if "smackdown" in field_name.lower():
            return True
        if "ingrain" in field_name.lower():
            return True
    for attr in ("effects", "status", "volatiles"):
        val = getattr(target, attr, None) if target is not None else None
        if val is None:
            continue
        items: Iterable[Any]
        if isinstance(val, Mapping):
            items = val.keys()
        elif isinstance(val, (list, tuple, set)):
            items = val
        else:
            items = [val]
        for item in items:
            s = str(item).lower()
            if "smackdown" in s or "ingrain" in s:
                return True
    return False


# ---------------------------------------------------------------------------
# 5. Move classification (damaging, STAB, spread, priority, Fake Out)
# ---------------------------------------------------------------------------


SPREAD_TARGETS: Tuple[str, ...] = (
    "alladjacent",
    "alladjacentfoes",
    "all",
)


@dataclass
class MoveClassification:
    """Per-move classification.

    Fields
    ------
    move_id
        Normalized move id.
    name
        Original display name.
    is_known
        True if the move exists in the local Gen 9 dex.
    category
        ``"physical"``, ``"special"``, ``"status"`` or ``""``.
    base_power
        ``float``; 0.0 if unknown.
    priority
        ``float``; 0.0 if unknown.
    target
        Dex target string.
    stalling
        True if the dex marks this as a stalling move.
    is_damaging
        True if category is physical/special AND base power > 0.
    is_spread
        True if target is in ``SPREAD_TARGETS`` AND damaging.
    is_priority_offensive
        True if priority > 0 AND not stalling AND damaging.
    move_type
        Upper-case declared type. ``""`` if unknown.
    is_fake_out
        True if this is the move ``Fake Out``.
    """

    move_id: str = ""
    name: str = ""
    is_known: bool = False
    category: str = ""
    base_power: float = 0.0
    priority: float = 0.0
    target: str = ""
    stalling: bool = False
    is_damaging: bool = False
    is_spread: bool = False
    is_priority_offensive: bool = False
    move_type: str = ""
    is_fake_out: bool = False


def classify_move(name: str) -> MoveClassification:
    """Public, deterministic, pure classifier."""
    cls = MoveClassification()
    cls.name = str(name) if name is not None else ""
    cls.move_id = normalize_id(name) if cls.name else ""
    if not cls.move_id:
        return cls
    data = _gen9_moves().get(cls.move_id, {})
    if not data:
        return cls
    cls.is_known = True
    cls.category = str(data.get("category", "")).strip().lower()
    try:
        cls.base_power = float(data.get("basePower", 0) or 0)
    except (TypeError, ValueError):
        cls.base_power = 0.0
    try:
        cls.priority = float(data.get("priority", 0) or 0)
    except (TypeError, ValueError):
        cls.priority = 0.0
    cls.target = str(data.get("target", "")).strip()
    cls.stalling = bool(data.get("stallingMove", False))
    cls.is_damaging = (
        cls.category in {"physical", "special"} and cls.base_power > 0
    )
    cls.is_spread = (
        cls.target.lower() in SPREAD_TARGETS and cls.is_damaging
    )
    cls.is_priority_offensive = (
        cls.priority > 0 and not cls.stalling and cls.is_damaging
    )
    raw_type = data.get("type", "")
    if raw_type is not None:
        cls.move_type = str(raw_type).strip().upper()
    cls.is_fake_out = cls.move_id == "fakeout"
    return cls


def move_is_damaging(name: str) -> bool:
    return classify_move(name).is_damaging


def move_is_spread(name: str) -> bool:
    return classify_move(name).is_spread


def move_priority(name: str) -> int:
    """Return the Gen 9 dex ``priority`` field as an int.

    Unknown moves return 0. Stalling moves keep their real
    priority value — the offensive-vs-stalling distinction is
    exposed via ``is_priority_offensive`` on the classifier.
    """
    cls = classify_move(name)
    if not cls.is_known:
        return 0
    return int(cls.priority)


def move_has_stab(
    name: str,
    attacker_types: Sequence[str],
    move: Any = None,
    attacker: Any = None,
    observed_form: Optional[str] = None,
    species_form: Optional[str] = None,
) -> bool:
    """Return True if ``name`` is STAB for the given attacker
    types.

    For dynamic-type moves, the effective type is consulted.
    Stab is ``True`` if any of ``attacker_types`` (upper-case)
    matches the effective type.
    """
    cls = classify_move(name)
    if not cls.is_known:
        return False
    effective = cls.move_type
    if cls.move_id in DYNAMIC_TYPE_MOVES:
        dyn = resolve_effective_move_type(
            move, attacker, observed_form, species_form
        )
        if dyn.effective_type:
            effective = dyn.effective_type
    if not effective:
        return False
    upper_types = {str(t).upper() for t in attacker_types if t}
    return effective in upper_types


def move_is_fake_out(name: str) -> bool:
    return classify_move(name).is_fake_out


def fake_out_legal_targets(
    name: str,
    opponent_lead_pair: Sequence[Any],
    resolve_target_types: Optional[callable] = None,
) -> int:
    """Count the number of opponent lead slots where Fake Out
    is a legal damaging pressure tool.

    A target is "legal" if and only if:

    1. The target exists.
    2. The target's type list (resolved via
       ``resolve_target_types(target)``) does NOT include
       GHOST (Fake Out is Normal-type and immune to Ghost).
    3. The target is not fainted. The function checks both
       object attributes and dict keys.

    ``resolve_target_types`` is the canonical adapter. The
    default adapter reads ``getattr(target, "types", [])``
    and accepts both poke-env-like objects and the
    ``MagicMock`` shapes used in tests. Production VGC
    callers MUST supply a resolver that knows how to look
    up types by species (e.g.
    ``lambda target: get_species_types(target["species"])``
    for a team_preview_policy dict).

    If the resolver returns an empty list, the target does
    NOT count as legal. Empty / None targets are skipped.

    Returns
    -------
    int
        Number of legal targets. Always 0 for non-Fake Out
        moves.
    """
    if not move_is_fake_out(name):
        return 0
    if resolve_target_types is None:
        def _resolve(target: Any) -> List[str]:
            if target is None:
                return []
            types_attr = None
            if isinstance(target, Mapping):
                types_attr = target.get("types")
            else:
                types_attr = getattr(target, "types", None)
            if not types_attr:
                return []
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
        resolve_target_types = _resolve

    count = 0
    for target in opponent_lead_pair[:2]:
        if target is None:
            continue
        # Fainted check: dict key OR object attribute.
        if isinstance(target, Mapping):
            fainted = target.get("fainted", False)
        else:
            fainted = getattr(target, "fainted", False)
        if fainted:
            continue
        target_types = list(resolve_target_types(target) or [])
        if not target_types:
            # Unknown types → NOT legal (do not silently
            # count as legal). Callers can check the
            # audit evidence for unresolved counts.
            continue
        if "GHOST" in target_types:
            continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# 6. Speed ordering
# ---------------------------------------------------------------------------


@dataclass
class SpeedOrdering:
    """Result of a deterministic speed comparison between two
    Pokémon.

    Fields
    ------
    result
        One of ``"a_faster"``, ``"b_faster"``, ``"tie"``,
        ``"unresolved"``.
    margin
        ``speed_a / speed_b`` if both speeds are positive.
        ``1.0`` on a tie. ``0.0`` when unresolved.
    reason
        Human-readable explanation. ``""`` when trivial.
    information_explicitly_visible
        True if both speeds are derivable from observable
        information (base speed + visible boosts + visible
        items). False if any required boost is hidden.
    """

    result: str = "unresolved"
    margin: float = 0.0
    reason: str = ""
    information_explicitly_visible: bool = False


def resolve_deterministic_speed_order(
    speed_a: Optional[float],
    speed_b: Optional[float],
    *,
    visible_boosts_a: bool = True,
    visible_boosts_b: bool = True,
    visible_items_a: bool = True,
    visible_items_b: bool = True,
    visible_status_a: bool = True,
    visible_status_b: bool = True,
    visible_field_a: bool = True,
    visible_field_b: bool = True,
    trick_room: Optional[bool] = None,
    margin: float = 0.10,
) -> SpeedOrdering:
    """Deterministic speed comparison.

    The function refuses to commit a result when any required
    component is hidden. Trick Room flips the comparison only
    if the field state is visible; ``trick_room=None`` means
    "field state is hidden" → unresolved.

    Parameters
    ----------
    speed_a, speed_b
        The base effective speeds (positive numbers, after all
        known modifiers). ``None`` marks "unknown".
    visible_*_a / visible_*_b
        Flags indicating whether the respective modifier
        sources are known to the caller.
    trick_room
        ``True`` / ``False`` for the active Trick Room state,
        or ``None`` if hidden.
    margin
        The required multiplicative gap to call a non-tie
        (e.g. 0.10 means 10% faster).
    """
    if speed_a is None or speed_b is None or speed_a <= 0 or speed_b <= 0:
        return SpeedOrdering(
            result="unresolved",
            reason="missing_base_speed",
            information_explicitly_visible=False,
        )
    if (
        not visible_boosts_a or not visible_boosts_b
        or not visible_items_a or not visible_items_b
        or not visible_status_a or not visible_status_b
        or not visible_field_a or not visible_field_b
    ):
        return SpeedOrdering(
            result="unresolved",
            reason="hidden_modifier",
            information_explicitly_visible=False,
        )
    if trick_room is None:
        return SpeedOrdering(
            result="unresolved",
            reason="trick_room_unknown",
            information_explicitly_visible=False,
        )

    a = float(speed_a)
    b = float(speed_b)
    ratio = a / b if b > 0 else 1.0
    if trick_room:
        # Trick Room inverts the acting order. The
        # parameter named ``speed_a`` is the SLOWER
        # actor; ``speed_b`` is the FASTER actor. The
        # result labels ``"a_faster"`` and ``"b_faster"``
        # always refer to the parameters named
        # ``speed_a`` / ``speed_b`` (which one is the
        # faster actor under the active field).
        if a > b * (1.0 + margin):
            return SpeedOrdering(
                result="b_faster",
                margin=ratio,
                information_explicitly_visible=True,
            )
        if b > a * (1.0 + margin):
            return SpeedOrdering(
                result="a_faster",
                margin=ratio,
                information_explicitly_visible=True,
            )
        return SpeedOrdering(
            result="tie",
            margin=1.0,
            information_explicitly_visible=True,
        )

    if a > b * (1.0 + margin):
        return SpeedOrdering(
            result="a_faster",
            margin=ratio,
            information_explicitly_visible=True,
        )
    if b > a * (1.0 + margin):
        return SpeedOrdering(
            result="b_faster",
            margin=ratio,
            information_explicitly_visible=True,
        )
    return SpeedOrdering(
        result="tie",
        margin=1.0,
        information_explicitly_visible=True,
    )


# ---------------------------------------------------------------------------
# 7. Visible-information audit / metadata
# ---------------------------------------------------------------------------


@dataclass
class VisibleInformation:
    """Per-call visible-information audit.

    Fields
    ------
    ability_visible
        True iff the defender's ability is known, revealed, or
        singleton-deducible.
    form_visible
        True iff the attacker's form is observable from
        protocol state.
    weather_visible
        True iff the weather is known.
    terrain_visible
        True iff the terrain is known.
    boosts_visible
        True iff both side boosts are known.
    trick_room_visible
        True iff the Trick Room state is known.
    items_visible
        True iff relevant held items are known.
    unknown_reasons
        List of canonical reason codes describing any hidden
        inputs that prevented full evaluation.
    """

    ability_visible: bool = False
    form_visible: bool = False
    weather_visible: bool = False
    terrain_visible: bool = False
    boosts_visible: bool = False
    trick_room_visible: bool = False
    items_visible: bool = False
    unknown_reasons: List[str] = field(default_factory=list)


def audit_visible_information(
    *,
    ability_known: bool = False,
    form_known: bool = False,
    weather_known: bool = False,
    terrain_known: bool = False,
    boosts_known: bool = False,
    trick_room_known: bool = False,
    items_known: bool = False,
) -> VisibleInformation:
    """Build a ``VisibleInformation`` audit record from raw
    per-input known/unknown flags.

    This helper is the single place to translate the many
    scattered "is this visible?" checks into one canonical
    record. Any caller may add a custom unknown reason to the
    returned record.
    """
    info = VisibleInformation(
        ability_visible=ability_known,
        form_visible=form_known,
        weather_visible=weather_known,
        terrain_visible=terrain_known,
        boosts_visible=boosts_known,
        trick_room_visible=trick_room_known,
        items_visible=items_known,
    )
    if not ability_known:
        info.unknown_reasons.append("ability_hidden")
    if not form_known:
        info.unknown_reasons.append("form_hidden")
    if not weather_known:
        info.unknown_reasons.append("weather_hidden")
    if not terrain_known:
        info.unknown_reasons.append("terrain_hidden")
    if not boosts_known:
        info.unknown_reasons.append("boosts_hidden")
    if not trick_room_known:
        info.unknown_reasons.append("trick_room_hidden")
    if not items_known:
        info.unknown_reasons.append("items_hidden")
    return info
