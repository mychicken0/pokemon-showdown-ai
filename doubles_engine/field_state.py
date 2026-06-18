"""Field state, weather, terrain, gravity, and form/type consumption helpers.

ponytail: Phase Ponytail Refactor Step 4A.
Extracted the field/type block from
``bot_doubles_damage_aware.py`` to a focused module.

The helpers in this module are the same code that
used to live at lines 960-1197 of
``bot_doubles_damage_aware.py``. The behavior is
bit-for-bit identical.

Dependency notes:
- ``is_gravity_active`` uses
  ``_normalize_ability_name`` which is defined
  later in ``bot_doubles_damage_aware.py``. The
  reference is function-local (the original code
  resolves the name at call time). We use a lazy
  import to preserve the late-binding pattern.
- ``is_type_consumed`` uses
  ``_TYPE_CONSUMING_MOVES`` which is also defined
  later in ``bot_doubles_damage_aware.py``. Same
  lazy-import pattern.
- ``resolve_effective_move_type`` and the helpers
  in ``types.py`` use ``doubles_mechanics`` (the
  shared layer, imported as ``_dm`` in the bot).
  This is a top-level import because
  ``doubles_mechanics`` is independent of the bot
  (no cycle).
- The module-level form/type state dicts
  (``_pokemon_forms``, ``_ident_to_obj``,
  ``_replay_cursors``) live here so the
  ``record_observed_form_change``,
  ``get_observed_form``, ``clear_observed_form_state``,
  ``_scan_replay_for_form_changes``, and
  ``_scan_replay_for_type_consumption`` helpers
  can mutate them as before. The shim re-exports
  these names so existing call sites and tests
  continue to work.
"""

from typing import Any, Dict, Optional, Set, Tuple


# Phase 6.5: Moves that consume the user's type
_TYPE_CONSUMING_MOVES = {
    "doubleshock": "ELECTRIC",
    "burnup": "FIRE",
}

# Phase 6.3.7h: Object-identity form tracker
# _pokemon_forms: (battle_tag, id(pokemon)) -> observed_form
# _ident_to_obj: (battle_tag, normalized_ident) -> id(pokemon)
# _replay_cursors: (battle_tag) -> replay cursor
_pokemon_forms: Dict[Tuple[str, int], str] = {}
_ident_to_obj: Dict[Tuple[str, str], int] = {}
_replay_cursors: Dict[str, int] = {}

# Dynamic-type moves (form-dependent) — used by
# ``resolve_effective_move_type`` in ``types.py``.
# This is a duplicate of the bot-local
# ``DYNAMIC_TYPE_MOVES`` and is the canonical
# source. The bot shim imports it from here.
DYNAMIC_TYPE_MOVES = {
    "aurawheel": {
        "attacker_base_species": "morpeko",
        "form_map": {
            "morpeko": "ELECTRIC",
            "morpekohangry": "DARK",
        },
    },
}


def is_gravity_active(battle) -> bool:
    try:
        for field in getattr(battle, "fields", {}) or {}:
            field_name = getattr(field, "name", str(field))
            if _normalize_ability_name(field_name) == "gravity":
                return True
    except Exception:
        pass
    return False


def get_max_type_threat(our_active, opponent, battle=None) -> float:
    """Get the maximum type effectiveness of any of the opponents  types against our active.

    Uses both type_1 and type_2 of the opponent. Returns the max multiplier.
    Never calculates from type_1 alone."""
    if not our_active or not opponent:
        return 0.0
    try:
        best = 0.0
        opp_type_1 = getattr(opponent, "type_1", None)
        opp_type_2 = getattr(opponent, "type_2", None)
        for t in (opp_type_1, opp_type_2):
            if t is None:
                continue
            try:
                mult = our_active.damage_multiplier(t)
                if mult > best:
                    best = mult
            except Exception:
                pass
        return best
    except Exception:
        return 0.0


def _normalize_form_name(s) -> str:
    return str(s).lower().replace("-", "").replace("_", "").replace(" ", "")


def _normalize_ident(ident) -> str:
    return str(ident).strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def record_observed_form_change(
    battle_tag: str, ident: str, new_form: str, pokemon=None
):
    bt = str(battle_tag)
    nf = _normalize_form_name(new_form)
    if pokemon is not None:
        key = (bt, id(pokemon))
        _pokemon_forms[key] = nf
    id_key = (bt, _normalize_ident(ident))
    _ident_to_obj[id_key] = id(pokemon) if pokemon is not None else 0


def get_observed_form(battle, pokemon) -> Optional[str]:
    if battle is None or pokemon is None:
        return None
    bt = str(getattr(battle, "battle_tag", ""))
    # First try exact object lookup
    obj_key = (bt, id(pokemon))
    if obj_key in _pokemon_forms:
        return _pokemon_forms[obj_key]
    # Fall back to ident-based lookup via _ident_to_obj
    for (tag, ident), oid in _ident_to_obj.items():
        if tag == bt and oid == id(pokemon):
            obj_fallback = (bt, oid)
            if obj_fallback in _pokemon_forms:
                return _pokemon_forms[obj_fallback]
    return None


def clear_observed_form_state(battle_tag: str):
    bt = str(battle_tag)
    for k in list(_pokemon_forms.keys()):
        if k[0] == bt:
            del _pokemon_forms[k]
    for k in list(_ident_to_obj.keys()):
        if k[0] == bt:
            del _ident_to_obj[k]
    if bt in _replay_cursors:
        del _replay_cursors[bt]


def _scan_replay_for_form_changes(battle):
    replay = getattr(battle, "_replay_data", None)
    if not replay:
        return
    bt = str(getattr(battle, "battle_tag", ""))
    cursor = _replay_cursors.get(bt, 0)
    for idx in range(cursor, len(replay)):
        event = replay[idx]
        if not isinstance(event, list) or len(event) < 4:
            continue
        if event[1] in ("-formechange", "detailschange"):
            ident = event[2]
            species_str = event[3].split(",")[0]
            new_form = _normalize_form_name(species_str)
            pokemon = None
            try:
                pokemon = battle.get_pokemon(ident)
            except Exception:
                pass
            record_observed_form_change(bt, ident, new_form, pokemon=pokemon)
    _replay_cursors[bt] = len(replay)


def _scan_replay_for_type_consumption(battle, consumed_types):
    """Scan replay for type-consumption events (Double Shock, Burn Up).

    Updates consumed_types dict in place: consumed_types[battle_tag][pokemon_ident] = set of types.
    """
    replay = getattr(battle, "_replay_data", None)
    if not replay:
        return
    bt = str(getattr(battle, "battle_tag", ""))
    cursor = _replay_cursors.get(bt + "_type", 0)
    for idx in range(cursor, len(replay)):
        event = replay[idx]
        if not isinstance(event, list) or len(event) < 3:
            continue
        # Format: ["", "-usedup", "p1a: Pawmot", "Electric"]
        if event[1] == "-usedup":
            ident = event[2]
            consumed_type = event[3].upper().strip() if len(event) > 3 else ""
            if ident and consumed_type:
                if bt not in consumed_types:
                    consumed_types[bt] = {}
                if ident not in consumed_types[bt]:
                    consumed_types[bt][ident] = set()
                consumed_types[bt][ident].add(consumed_type)
    _replay_cursors[bt + "_type"] = len(replay)


def is_type_consumed(move, attacker, battle, consumed_types) -> bool:
    """Check if a move is blocked because the attacker consumed its required type.

    Moves like Double Shock require Electric type. If the user already used
    Double Shock, it loses its Electric type and the move will fail.
    """
    if not move or not attacker or not battle:
        return False
    move_id = getattr(move, "id", "")
    if not move_id or move_id not in _TYPE_CONSUMING_MOVES:
        return False
    bt = str(getattr(battle, "battle_tag", ""))
    if bt not in consumed_types:
        return False
    # Get the attacker's identity
    try:
        ident = battle.get_pokemon_identifier(attacker)
    except Exception:
        return False
    if not ident or ident not in consumed_types[bt]:
        return False
    needed_type = _TYPE_CONSUMING_MOVES[move_id]
    if needed_type in consumed_types[bt][ident]:
        return True
    return False


# Lazy import helper for _normalize_ability_name.
# ponytail: ``_normalize_ability_name`` is a
# bot-local helper that lives in
# ``bot_doubles_damage_aware.py``. We import it
# lazily here to avoid an import cycle: the bot
# would import from this module (via the shim),
# and this module would import from the bot.
def _normalize_ability_name(ability) -> str:
    """Lazy import wrapper for the bot-local
    ``_normalize_ability_name``.

    Returns the normalized ability name (lowercase
    alnum only). The bot's
    ``_normalize_ability_name`` is the
    authoritative implementation; this wrapper
    delegates to it via a function-local import.
    """
    from bot_doubles_damage_aware import _normalize_ability_name as _impl
    return _impl(ability)
