"""Effective-move-type resolution helpers.

ponytail: Phase Ponytail Refactor Step 4A.
Extracted the effective-move-type resolution
helpers from ``bot_doubles_damage_aware.py`` to a
focused module.

The helpers in this module are the same code that
used to live at lines 1141-1197 of
``bot_doubles_damage_aware.py``. The behavior is
bit-for-bit identical.

Dependency notes:
- These helpers use ``doubles_mechanics`` (the
  shared layer, imported as ``_dm`` in the bot).
  This is a top-level import because
  ``doubles_mechanics`` is independent of the bot
  (no cycle).
- ``resolve_effective_move_type`` also uses
  ``get_observed_form`` which now lives in
  ``doubles_engine.field_state``. We import it
  lazily to avoid any cycle risk: the bot imports
  from this module (via the shim), and we import
  from ``field_state``. The cycle is real but
  breakable with a function-local lazy import.
"""

import doubles_mechanics as _dm

from doubles_engine.field_state import DYNAMIC_TYPE_MOVES


def resolve_effective_move_type(move, attacker=None, battle=None) -> dict:
    """Resolve the effective move type accounting for dynamic form changes.

    Returns dict with: declared_type, effective_type, source, dynamic_applied,
    observed_form, information_explicitly_visible. Uses the
    ``doubles_mechanics`` shared layer; the production form
    tracker (``get_observed_form``) and the attacker's
    species string are forwarded to the shared module so the
    Aura Wheel / Morpeko logic is identical between battle
    callers and preview callers.
    """
    from doubles_engine.field_state import get_observed_form
    observed = None
    species_form = None
    if move is not None:
        move_id = ""
        if hasattr(move, "id") and move.id:
            move_id = _dm.normalize_id(move.id)
        elif isinstance(move, str):
            move_id = _dm.normalize_id(move)
        if move_id in DYNAMIC_TYPE_MOVES and attacker:
            observed = get_observed_form(battle, attacker)
            species_form = getattr(attacker, "species", "") or None
    shared = _dm.resolve_effective_move_type(
        move, attacker,
        observed_form=observed,
        species_form=species_form,
    )
    return {
        "declared_type": shared.declared_type,
        "effective_type": shared.effective_type,
        "source": shared.source,
        "dynamic_applied": shared.dynamic_applied,
        "observed_form": shared.observed_form,
        "information_explicitly_visible": (
            shared.information_explicitly_visible
        ),
    }


def _get_declared_move_type(move) -> str:
    """Extract declared move.type as uppercase string.

    Delegates to ``doubles_mechanics`` to keep the canonical
    declared-type extraction in one place.
    """
    return _dm._get_declared_move_type(move)


def get_effective_move_type(move, attacker=None, battle=None) -> str:
    """Compatibility wrapper: return effective type string.

    Delegates to the shared module. The production
    ``resolve_effective_move_type`` is the authoritative
    implementation; this thin façade exists only because many
    call sites already import the string-returning variant.
    """
    return resolve_effective_move_type(move, attacker, battle)["effective_type"]
