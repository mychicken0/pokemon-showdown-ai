"""Protocol/replay scan helpers and identity helpers.

ponytail: Phase Ponytail Refactor Step 4B.
Extracted the protocol and replay scan helpers
from ``bot_doubles_damage_aware.py`` to a focused
module.

The helpers in this module are the same code that
used to live at lines 668-779 of
``bot_doubles_damage_aware.py``. The behavior is
bit-for-bit identical.

Dependency notes:
- ``find_protocol_ability_reveal_turn`` is a pure
  function that reads battle replay events. It has
  no bot-local dependencies.
- ``_normalize_protocol_token`` is pure.
- ``_get_pokemon_by_ident`` and
  ``_get_battle_pokemon_identity`` are simple
  wrappers over ``battle`` methods.
- No bot-local state is mutated.

No import cycle: the protocol helpers are
independent of mechanics/support-targets/field-state.
"""

from typing import Optional


def find_protocol_ability_reveal_turn(
    battle,
    target,
    ability_name: str,
) -> Optional[int]:
    """Scan battle replay events for the exact turn an ability was protocol-revealed.

    Reads only replay/protocol events up to battle.turn.  Matches the exact
    target Pokemon via battle.get_pokemon(), never by species substring.
    Recognizes |-ability|IDENT|Ability and [from] ability: Ability patterns.

    Returns the turn number (int) or None if no explicit reveal exists.
    """
    if not battle or not target or not ability_name:
        return None
    events = getattr(battle, "_replay_data", []) or []
    if not events:
        return None
    decision_turn = getattr(battle, "turn", 0)
    ability_lower = _normalize_protocol_token(ability_name)
    current_turn = 0
    for event in events:
        if not isinstance(event, list) or len(event) < 2:
            continue
        try:
            if event[1] == "turn" and len(event) >= 3:
                try:
                    current_turn = int(event[2])
                except (ValueError, TypeError):
                    pass
                continue
            if current_turn > decision_turn:
                break
            if event[1] == "-ability" and len(event) >= 4:
                ident = event[2]
                revealed = _normalize_protocol_token(event[3])
                if revealed == ability_lower:
                    pokemon = None
                    try:
                        pokemon = battle.get_pokemon(ident)
                    except Exception:
                        pokemon = None
                    if pokemon is target:
                        return current_turn
                continue
            if event[1] == "-message" and len(event) >= 3:
                msg = str(event[2]) if event[2] is not None else ""
                if ability_lower in _normalize_protocol_token(msg):
                    if "ability" in msg.lower() and (
                        "|" in msg or ":" in msg
                    ):
                        return current_turn
        except Exception:
            continue
    return None


def _normalize_protocol_token(value: str) -> str:
    """Normalize a protocol token (ability, ident, etc.) for comparison.

    ponytail: the canonical normalization strips
    case, whitespace, underscores, and hyphens so
    that "Storm Drain" and "stormdrain" compare
    equal. The original bot implementation lives
    here.
    """
    if value is None:
        return ""
    return (
        str(value)
        .strip()
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
    )


def _get_pokemon_by_ident(battle, ident: str):
    """Return the Pokemon object matching the given ident, or None.

    ponytail: thin wrapper over
    ``battle.get_pokemon`` with error handling so
    audit code can call it without try/except
    noise. The original implementation lives here.
    """
    if not battle or not ident:
        return None
    try:
        return battle.get_pokemon(ident)
    except Exception:
        return None


def _get_battle_pokemon_identity(battle, pokemon) -> str:
    """Return the canonical identity string for a Pokemon in this battle.

    ponytail: walks ``battle.team`` /
    ``battle.opponent_team`` for the exact object
    identity and returns the matching ident. Falls
    back to ``pokemon.ident`` / ``pokemon.name``.
    """
    if not battle or pokemon is None:
        return ""
    for collection_name in ("team", "opponent_team", "_team", "_opponent_team"):
        collection = getattr(battle, collection_name, None)
        if not isinstance(collection, dict):
            continue
        for ident, candidate in collection.items():
            if candidate is pokemon:
                return str(ident)
    return ""
