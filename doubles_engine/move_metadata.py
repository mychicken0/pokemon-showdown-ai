"""Move metadata resolver for the v1.1 audit path — Phase RL-DATA-3a.1.

The audit logger persists per-turn decisions to a
JSONL artifact. The v1.1 schema (per
``logs/rl_data_1_turn_level_schema_plan.md``) requires
the support-move classifier to receive ``base_power``
and ``category`` so known damaging moves are not
falsely tagged as ``unknown_needs_probe``.

The audit logger does NOT record ``base_power`` or
``category`` for V4a legal-action keys. This module
provides a small resolver that:

1. Tries the live poke-env ``Move`` object if the
   caller has access to it (e.g., via the order
   object, the bot's active mon's move list, or a
   pre-computed lookup).
2. Tries a poke-env ``Pokemon.moves`` dict if the
   caller passes the active mon.
3. Falls back to a small explicit static table for
   the moves that smoke / tests / analyses need.

The static fallback is intentionally tiny. We do not
build a hand-written Pokédex. The fallback covers
moves that:

- appear in the SUPPORT-AUDIT-1 inventory
  (``raindance``, ``protect``, ``helpinghand``, ...),
- appear in the smoke / test fixtures
  (``fakeout``, ``hurricane``, ``surf``),
- appear in the bot's runtime move-id usage
  (``tackle``, ``thunderbolt``, ``icebeam``, ...).

Phase RL-DATA-3a.1 scope is strictly metadata
enrichment. No scoring / behavior / default change.

Key invariants:

- ``metadata_source`` is one of:
    - ``"move"`` — resolved from a real poke-env
      ``Move`` object passed in by the caller.
    - ``"pokemon"`` — resolved from an active mon's
      ``moves`` dict.
    - ``"fallback"`` — resolved from the static
      table (smoke / tests only).
    - ``"unknown"`` — no source had the move; the
      returned fields are all ``None``.

- Missing fields are emitted as ``None`` with
  ``metadata_source="unknown"``. The classifier
  treats these as "not damaging" — i.e., a move
  with no metadata falls into the unknown-support
  branch (which is the safe / conservative default).
- No hidden-state inference. The resolver never
  reads a Pokédex file or species. It only matches
  on the move id.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


# Source labels.
SOURCE_MOVE = "move"
SOURCE_POKEMON = "pokemon"
SOURCE_FALLBACK = "fallback"
SOURCE_UNKNOWN = "unknown"
# Phase RL-DATA-3a.2: additional source labels for
# the live override path. ``override`` means the
# caller passed a pre-computed ``move_metadata_map_override``
# to the audit logger. ``order`` means the resolver
# found a real poke-env ``DoubleBattleOrder`` object
# at the call site. ``live`` is a generic label for
# a pre-resolved entry the bot passed in.
SOURCE_OVERRIDE = "override"
SOURCE_ORDER = "order"
SOURCE_LIVE = "live"


# Small static fallback for moves that smoke / tests
# need. The list is intentionally tiny. Adding to
# this list is OK only when:
#   (a) the move is in the SUPPORT-AUDIT-1 inventory,
#   (b) the move is in the bot's run-time usage, or
#   (c) the move appears in a test / smoke fixture.
#
# Format: move_id (lowercased no-sep) -> (base_power,
# category). ``category`` is one of "physical",
# "special", "status".
_FALLBACK_MOVE_METADATA: Dict[str, Tuple[int, str]] = {
    # Smoke / test fixtures
    "fakeout": (40, "physical"),
    "hurricane": (110, "special"),
    "surf": (90, "special"),
    # Common support moves
    "raindance": (0, "status"),
    "sunnyday": (0, "status"),
    "sandstorm": (0, "status"),
    "hail": (0, "status"),
    "snowscape": (0, "status"),
    "electricterrain": (0, "status"),
    "grassyterrain": (0, "status"),
    "mistyterrain": (0, "status"),
    "psychicterrain": (0, "status"),
    "tailwind": (0, "status"),
    "trickroom": (0, "status"),
    "protect": (0, "status"),
    "detect": (0, "status"),
    "spikyshield": (0, "status"),
    "kingsshield": (0, "status"),
    "banefulbunker": (0, "status"),
    "silktrap": (0, "status"),
    "burningbulwark": (0, "status"),
    "obstruct": (0, "status"),
    "maxguard": (0, "status"),
    "healpulse": (0, "status"),
    "floralhealing": (0, "status"),
    "decorate": (0, "status"),
    "helpinghand": (0, "status"),
    "coaching": (0, "status"),
    "howl": (0, "status"),
    "lifedew": (0, "status"),
    "aromatherapy": (0, "status"),
    "healbell": (0, "status"),
    "followme": (0, "status"),
    "ragepowder": (0, "status"),
    "wideguard": (0, "status"),
    "quickguard": (0, "status"),
    "craftyshield": (0, "status"),
    "matblock": (0, "status"),
    "taunt": (0, "status"),
    "encore": (0, "status"),
    "disable": (0, "status"),
    "torment": (0, "status"),
    "thunderwave": (0, "status"),
    "willowisp": (0, "status"),
    "toxic": (0, "status"),
    "spore": (0, "status"),
    "sleeppowder": (0, "status"),
    "stunspore": (0, "status"),
    "charm": (0, "status"),
    "scaryface": (0, "status"),
    "screech": (0, "status"),
    "faketears": (0, "status"),
    "metalsound": (0, "status"),
    "gastroacid": (0, "status"),
    "icywind": (0, "status"),
    "electroweb": (0, "status"),
    "safeguard": (0, "status"),
    "lightscreen": (0, "status"),
    "reflect": (0, "status"),
    "auroraveil": (0, "status"),
    "magiccoat": (0, "status"),
    "haze": (0, "status"),
    "mist": (0, "status"),
    "courtchange": (0, "status"),
    "allyswitch": (0, "status"),
    "partingshot": (0, "status"),
    "memento": (0, "status"),
    "superpower": (120, "physical"),
    "closecombat": (120, "physical"),
    "voltswitch": (70, "special"),
    "uturn": (70, "physical"),
    "rapidspin": (50, "physical"),
    "thunderbolt": (90, "special"),
    "icebeam": (90, "special"),
    "flamethrower": (90, "special"),
    "psychic": (90, "special"),
    "earthquake": (100, "physical"),
    "rockslide": (75, "physical"),
    "stoneedge": (100, "physical"),
    "fireblast": (110, "special"),
    "hydropump": (110, "special"),
    "leafstorm": (130, "special"),
    "dracometeor": (130, "special"),
    "thunder": (110, "special"),
    "scald": (80, "special"),
    "matchagotcha": (90, "special"),
    "drainpunch": (75, "physical"),
    "gunkshot": (120, "physical"),
    "boltstrike": (130, "physical"),
    "waterfall": (80, "physical"),
    # Phase RL-DATA-3c: setup / stat-boost moves.
    # All are 0 power, status. The classifier
    # uses these to correctly identify setup
    # moves as damage-like (not support) for
    # the purpose of Gate 17.
    "quiverdance": (0, "status"),
    "swordsdance": (0, "status"),
    "nastyplot": (0, "status"),
    "dragondance": (0, "status"),
    "calmmind": (0, "status"),
    "bulkup": (0, "status"),
    "irondefense": (0, "status"),
    "amnesia": (0, "status"),
    "agility": (0, "status"),
    "shellsmash": (0, "status"),
    "bellydrum": (0, "status"),
    "growth": (0, "status"),
    "workup": (0, "status"),
    "curse": (0, "status"),
    "cosmicpower": (0, "status"),
    "coil": (0, "status"),
    "honeclaws": (0, "status"),
    "autotomize": (0, "status"),
    "rockpolish": (0, "status"),
    "shiftgear": (0, "status"),
    "tailglow": (0, "status"),
    "geomancy": (0, "status"),
    "victorydance": (0, "status"),
    "clangeroussoul": (0, "status"),
    "tidyup": (0, "status"),
    "substitute": (0, "status"),
}


def _normalize_move_id_for_metadata(move_id: Any) -> str:
    """Normalize a move id to the canonical form used
    by the resolver. Mirrors
    ``doubles_engine.audit_v1_1_metadata._normalize_v1_1_move_id``
    and ``doubles_engine.support_targets._normalize_move_id``
    so the fallback table is keyed consistently.
    """
    if move_id is None:
        return ""
    s = str(move_id)
    s = s.lower()
    s = s.replace(" ", "").replace("-", "").replace("_", "").replace("'", "")
    return s


def _category_str(cat: Any) -> Optional[str]:
    """Convert a poke-env ``Move.category`` (which can
    be a ``MoveCategory`` enum or a string) to a
    canonical lowercase string.
    """
    if cat is None:
        return None
    s = getattr(cat, "name", None) or str(cat)
    s = s.lower()
    # poke-env uses "physique" / "special" / "status"
    if s in ("physical", "special", "status"):
        return s
    return None


def _base_power_int(bp: Any) -> Optional[int]:
    """Convert a poke-env ``Move.base_power`` to a
    JSON-safe int. Returns ``None`` if the value is
    missing, ``None``, or not a number.
    """
    if bp is None:
        return None
    try:
        return int(bp)
    except (TypeError, ValueError):
        return None


def _resolve_from_move_obj(
    move_obj: Any,
) -> Optional[Dict[str, Any]]:
    """Try to extract metadata from a poke-env
    ``Move`` object. Returns ``None`` if the object
    is missing required fields.
    """
    if move_obj is None:
        return None
    move_id = getattr(move_obj, "id", None)
    if not move_id:
        return None
    bp = _base_power_int(getattr(move_obj, "base_power", None))
    cat = _category_str(getattr(move_obj, "category", None))
    type_obj = getattr(move_obj, "type", None)
    move_type = (
        getattr(type_obj, "name", None) if type_obj is not None else None
    )
    if move_type is not None:
        move_type = str(move_type).lower()
    target = getattr(move_obj, "deduced_target", None) or getattr(
        move_obj, "target", None
    )
    return {
        "move_id": _normalize_move_id_for_metadata(move_id),
        "base_power": bp,
        "category": cat,
        "move_type": move_type,
        "target": str(target) if target is not None else None,
        "metadata_source": SOURCE_MOVE,
    }


def _resolve_from_pokemon(
    pokemon: Any,
) -> Dict[str, Dict[str, Any]]:
    """Extract a per-move metadata map from a
    poke-env ``Pokemon`` object. Returns a dict
    ``{normalized_move_id: metadata_dict}`` for
    every move in ``pokemon.moves``. If ``pokemon``
    is missing or has no moves, returns ``{}``.
    """
    if pokemon is None:
        return {}
    moves = getattr(pokemon, "moves", None)
    if not isinstance(moves, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for move_id, move_obj in moves.items():
        meta = _resolve_from_move_obj(move_obj)
        if meta is not None:
            # Override the source to ``pokemon``.
            meta = dict(meta)
            meta["metadata_source"] = SOURCE_POKEMON
            out[meta["move_id"]] = meta
    return out


def _resolve_from_fallback(
    move_id_norm: str,
) -> Optional[Dict[str, Any]]:
    """Try the static fallback table. Returns
    ``None`` if the move is not in the table.
    """
    entry = _FALLBACK_MOVE_METADATA.get(move_id_norm)
    if entry is None:
        return None
    bp, cat = entry
    return {
        "move_id": move_id_norm,
        "base_power": bp,
        "category": cat,
        "move_type": None,
        "target": None,
        "metadata_source": SOURCE_FALLBACK,
    }


def resolve_move_metadata_for_audit(
    move_id: Any,
    order: Any = None,
    move: Any = None,
    pokemon: Any = None,
) -> Dict[str, Any]:
    """Resolve metadata for a single move id.

    Resolution order:

    1. If ``order`` is provided and has an ``.order``
       attribute that looks like a ``Move`` object,
       use it.
    2. If ``move`` is provided directly, use it.
    3. If ``pokemon`` is provided, look the move up
       in ``pokemon.moves``.
    4. Otherwise, fall back to the static table.

    The return dict always has the keys
    ``move_id`` / ``base_power`` / ``category`` /
    ``move_type`` / ``target`` / ``metadata_source``.
    Missing fields are ``None``. ``metadata_source``
    is one of ``"move"`` / ``"pokemon"`` / ``"fallback"``
    / ``"unknown"``.

    Pure function. No file I/O, no network, no species
    inference, no hidden-state reads.
    """
    move_id_norm = _normalize_move_id_for_metadata(move_id)

    # 1) Try the order object.
    if order is not None:
        candidate = getattr(order, "order", None)
        meta = _resolve_from_move_obj(candidate)
        if meta is not None:
            return meta

    # 2) Try a direct move object.
    if move is not None:
        meta = _resolve_from_move_obj(move)
        if meta is not None:
            return meta

    # 3) Try the active mon.
    if pokemon is not None:
        pokemon_map = _resolve_from_pokemon(pokemon)
        if move_id_norm in pokemon_map:
            return pokemon_map[move_id_norm]

    # 4) Static fallback.
    if move_id_norm:
        meta = _resolve_from_fallback(move_id_norm)
        if meta is not None:
            return meta

    return {
        "move_id": move_id_norm,
        "base_power": None,
        "category": None,
        "move_type": None,
        "target": None,
        "metadata_source": SOURCE_UNKNOWN,
    }


def resolve_batch_for_audit(
    move_ids: list,
    battle: Any = None,
    slot_idx: Optional[int] = None,
) -> Dict[str, Dict[str, Any]]:
    """Resolve metadata for a batch of move ids.

    ``battle`` is the poke-env battle. ``slot_idx`` is
    the active-mon's slot (0 or 1). The resolver looks
    up the active mon in ``battle.active_pokemon[slot_idx]``
    and walks the mon's ``moves`` dict before falling
    back to the static table.

    Returns a dict ``{normalized_move_id: metadata}``.
    """
    pokemon = None
    if battle is not None and slot_idx is not None:
        actives = getattr(battle, "active_pokemon", None)
        if isinstance(actives, (list, tuple)) and slot_idx < len(actives):
            pokemon = actives[slot_idx]
    out: Dict[str, Dict[str, Any]] = {}
    for mid in move_ids:
        norm = _normalize_move_id_for_metadata(mid)
        if not norm:
            continue
        # Try the live mon first.
        if pokemon is not None:
            pokemon_map = _resolve_from_pokemon(pokemon)
            if norm in pokemon_map:
                out[norm] = pokemon_map[norm]
                continue
        # Static fallback.
        meta = _resolve_from_fallback(norm)
        if meta is not None:
            out[norm] = meta
        else:
            out[norm] = {
                "move_id": norm,
                "base_power": None,
                "category": None,
                "move_type": None,
                "target": None,
                "metadata_source": SOURCE_UNKNOWN,
            }
    return out


def _resolve_from_order_obj(
    order: Any,
) -> Optional[Dict[str, Any]]:
    """Phase RL-DATA-3a.2: resolve metadata from a
    poke-env ``DoubleBattleOrder`` (or any object
    with an ``.order`` attribute that is a poke-env
    ``Move``).

    Used by ``collect_live_move_metadata`` when the
    bot has access to live orders at choose_move
    time. Returns ``None`` if the order is missing
    or has no ``.order`` attribute.
    """
    if order is None:
        return None
    move_obj = getattr(order, "order", None)
    if move_obj is None:
        return None
    meta = _resolve_from_move_obj(move_obj)
    if meta is not None:
        # Re-label the source to ``order`` so the
        # audit JSONL distinguishes "from the order
        # object" from "from a direct move argument".
        meta = dict(meta)
        meta["metadata_source"] = SOURCE_ORDER
    return meta


def collect_live_move_metadata(
    battle: Any = None,
    valid_orders: Any = None,
    v4a_legal_keys: Any = None,
) -> Dict[str, Dict[str, Any]]:
    """Phase RL-DATA-3a.2: collect live move
    metadata for a turn, suitable for passing as
    ``move_metadata_map_override`` to the audit
    logger.

    Resolution order (per move id):

    1. **Order object**: if the caller passes
       ``valid_orders`` (a list per slot of
       ``DoubleBattleOrder`` objects) and an order
       has ``.order`` (a poke-env ``Move``) with
       the right id, use it. ``metadata_source =
       "order"``.
    2. **Active mon's moves**: if the caller
       passes ``battle`` and a mon has the move
       in its ``moves`` dict, use it.
       ``metadata_source = "pokemon"``.
    3. **V4a legal keys**: if the caller passes
       ``v4a_legal_keys`` (a flat list of V4a
       action keys), the move id is used to
       look up the order / pokemon again. The
       V4a legal keys do not carry move objects
       themselves, so this is just a way to
       enumerate the move ids to collect.
    4. **Static fallback**: ``metadata_source =
       "fallback"``.
    5. **Unknown**: ``metadata_source =
       "unknown"``.

    The returned dict is keyed by normalized move
    id and is safe to pass directly as
    ``move_metadata_map_override`` to
    ``DoublesDecisionAuditLogger.log_turn_decision``.

    Pure: no file I/O, no network, no species
    inference, no hidden-state reads. The bot
    may call this from ``choose_move`` where
    ``valid_orders`` is a list of
    ``DoubleBattleOrder`` objects.
    """
    out: Dict[str, Dict[str, Any]] = {}
    seen: set = set()

    # Build a quick ``{normalized_id: order_obj}``
    # map from the live ``valid_orders``. This lets
    # us resolve each move id to its order object
    # in O(1).
    order_by_id: Dict[str, Any] = {}
    if isinstance(valid_orders, (list, tuple)):
        for slot_orders in valid_orders:
            if not isinstance(slot_orders, (list, tuple)):
                continue
            for order in slot_orders:
                move_obj = getattr(order, "order", None)
                if move_obj is None:
                    continue
                move_id_norm = _normalize_move_id_for_metadata(
                    getattr(move_obj, "id", None)
                )
                if not move_id_norm:
                    continue
                # First order wins. The bot's
                # ``valid_orders`` may contain Mega
                # / Z-Move / Dynamax / Terastallize
                # variants of the same move id; we
                # keep the first one and the audit
                # logger records all variants in the
                # legal-action keys.
                order_by_id.setdefault(move_id_norm, order)

    # Build a quick ``{normalized_id: pokemon}`` map
    # from the active mons.
    pokemon_by_id: Dict[str, Any] = {}
    if battle is not None:
        actives = getattr(battle, "active_pokemon", None)
        if isinstance(actives, (list, tuple)):
            for pokemon in actives:
                if pokemon is None:
                    continue
                moves = getattr(pokemon, "moves", None)
                if not isinstance(moves, dict):
                    continue
                for move_id, move_obj in moves.items():
                    move_id_norm = _normalize_move_id_for_metadata(
                        move_id
                    )
                    if not move_id_norm:
                        continue
                    pokemon_by_id.setdefault(
                        move_id_norm, move_obj
                    )

    # Build the set of move ids we care about. Prefer
    # the V4a legal keys (canonical); fall back to
    # the order objects; fall back to the active
    # mons' moves.
    move_ids: list = []
    if isinstance(v4a_legal_keys, (list, tuple)):
        for k in v4a_legal_keys:
            if isinstance(k, (list, tuple)) and len(k) >= 2:
                mid_norm = _normalize_move_id_for_metadata(k[1])
                if mid_norm and mid_norm not in seen:
                    seen.add(mid_norm)
                    move_ids.append(mid_norm)
    if not move_ids:
        for mid in order_by_id:
            if mid not in seen:
                seen.add(mid)
                move_ids.append(mid)
    if not move_ids:
        for mid in pokemon_by_id:
            if mid not in seen:
                seen.add(mid)
                move_ids.append(mid)

    for mid in move_ids:
        # 1) Order object.
        order = order_by_id.get(mid)
        if order is not None:
            meta = _resolve_from_order_obj(order)
            if meta is not None:
                out[mid] = meta
                continue
        # 2) Active mon's moves.
        move_obj = pokemon_by_id.get(mid)
        if move_obj is not None:
            meta = _resolve_from_move_obj(move_obj)
            if meta is not None:
                # Re-label the source to ``pokemon``
                # so the audit JSONL distinguishes
                # "from the active mon's moves" from
                # "from a direct move argument".
                meta = dict(meta)
                meta["metadata_source"] = SOURCE_POKEMON
                out[mid] = meta
                continue
        # 3) Static fallback.
        meta = _resolve_from_fallback(mid)
        if meta is not None:
            out[mid] = meta
        else:
            out[mid] = {
                "move_id": mid,
                "base_power": None,
                "category": None,
                "move_type": None,
                "target": None,
                "metadata_source": SOURCE_UNKNOWN,
            }
    return out


def normalize_override(
    override: Any,
) -> Dict[str, Dict[str, Any]]:
    """Phase RL-DATA-3a.2: normalize a user-supplied
    ``move_metadata_map_override`` dict.

    The override is expected to map a normalized
    move id (or any case-variation of a move id) to
    a dict with at least ``base_power`` and
    ``category``. The override may have keys that
    are NOT normalized (e.g., ``"Fake Out"``,
    ``"fake-out"``); this helper normalizes them.

    Each entry is annotated with
    ``metadata_source = "override"`` unless the
    caller already provided one.

    Missing entries are filled with safe defaults
    (``None`` / ``None`` / ``"override"``).

    The returned dict is safe to merge into the
    audit logger's ``move_metadata_map``.
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(override, dict):
        return out
    for raw_key, raw_value in override.items():
        # Only accept string keys. A caller may have
        # a ``dict`` keyed by an action-key tuple or
        # some other structure; we normalize only the
        # string-keyed entries.
        if not isinstance(raw_key, str):
            continue
        norm_key = _normalize_move_id_for_metadata(raw_key)
        if not norm_key:
            continue
        if not isinstance(raw_value, dict):
            # Convenience: allow the override value
            # to be a (base_power, category) tuple.
            if (
                isinstance(raw_value, (list, tuple))
                and len(raw_value) >= 2
            ):
                raw_value = {
                    "base_power": raw_value[0],
                    "category": raw_value[1],
                }
            else:
                continue
        bp = raw_value.get("base_power")
        cat = raw_value.get("category")
        # Accept enum / poke-env ``Move.category``
        # objects.
        cat = _category_str(cat)
        move_type = raw_value.get("move_type")
        target = raw_value.get("target")
        target_str = (
            str(target) if target is not None else None
        )
        source = raw_value.get("metadata_source") or SOURCE_OVERRIDE
        out[norm_key] = {
            "move_id": norm_key,
            "base_power": _base_power_int(bp),
            "category": cat,
            "move_type": (
                str(move_type).lower()
                if move_type is not None
                else None
            ),
            "target": target_str,
            "metadata_source": source,
        }
    return out
