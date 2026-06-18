"""Action identity / legal-order telemetry helpers.

ponytail: pure helpers extracted from
``bot_doubles_damage_aware.py``. Preserves legacy
V2l.1 key semantics (3-tuple) and adds V4a
mechanic-aware keys (4-tuple) separately. The
canonical engine still calls these through the
shim in ``bot_doubles_damage_aware`` for
backward compatibility.
"""
from typing import Any, Iterable, List, Optional, Tuple

# V2l.1 legacy 3-tuple key: (action_type, action_id, target)
# V4a mechanic-aware 4-tuple key:
#   (action_type, action_id, target, mechanic)
#
# These are the only two key shapes used in the
# canonical engine. They are NOT used for ordering
# (V2l.1) — they are identity keys that allow us to
# dedupe / compare orders across a turn. The V2l.1
# key is preserved as-is so legacy V2l.1 parity
# artifacts keep matching.
V2L1_KEY_LEN = 3
V4A_KEY_LEN = 4


def _order_action_key(order) -> tuple:
    """Normalized key for comparing two SingleBattleOrder objects.

    Returns (action_type, action_id, target) where action_type is 'move'
    or 'switch', action_id is the move id or Pokemon species, and target
    is the move target position (0 for switches).
    """
    if order is None:
        return ("none", "", 0)
    from poke_env.battle.double_battle import SingleBattleOrder

    if isinstance(order, SingleBattleOrder):
        inner = order.order
        if inner is None:
            return ("none", "", 0)
        if hasattr(inner, "id"):
            return ("move", inner.id, getattr(order, "move_target", 0))
        elif hasattr(inner, "species"):
            return ("switch", inner.species, 0)
    return ("unknown", str(order) if order is not None else "", 0)


def _order_mechanic_label(order) -> str:
    """Return the one-per-side battle mechanic flag on a move order."""
    if order is None:
        return ""
    if getattr(order, "mega", False):
        return "mega"
    if getattr(order, "z_move", False):
        return "zmove"
    if getattr(order, "dynamax", False):
        return "dynamax"
    if getattr(order, "terastallize", False):
        return "terastallize"
    return ""


def _order_action_key_with_mechanic(order) -> tuple:
    """Action key that preserves Mega/Z/Dynamax/Tera variants.

    The older ``_order_action_key`` intentionally remains a 3-tuple for
    compatibility with existing V2l.1 parity artifacts. This V4a key is the
    RL/debug identity: ``("move", move_id, target, mechanic)`` or
    ``("switch", species, 0, "")``.
    """
    if order is None:
        return ("none", "", 0, "")
    from poke_env.battle.double_battle import SingleBattleOrder

    if isinstance(order, SingleBattleOrder):
        inner = order.order
        if inner is None:
            return ("none", "", 0, "")
        mechanic = _order_mechanic_label(order)
        if hasattr(inner, "id"):
            return (
                "move",
                inner.id,
                getattr(order, "move_target", 0),
                mechanic,
            )
        elif hasattr(inner, "species"):
            return ("switch", inner.species, 0, "")
    return ("unknown", str(order) if order is not None else "", 0, "")


def _legal_action_keys_for_slot(
    valid_orders, slot_idx: int
) -> list:
    """V2l.1 — return a list of ``_order_action_key``
    tuples for one slot of ``valid_orders``.

    This is a tiny pure helper. The canonical
    ``choose_move`` calls it so the audit logger
    records the legal action keys for parity tests.
    """
    if not valid_orders or slot_idx >= len(valid_orders):
        return []
    out = []
    for order in valid_orders[slot_idx] or []:
        try:
            out.append(_order_action_key(order))
        except Exception:
            continue
    return out


def _legal_action_keys_with_mechanic_for_slot(
    valid_orders, slot_idx: int
) -> list:
    """V4a — same as ``_legal_action_keys_for_slot`` but
    with mechanic-aware 4-tuple keys.
    """
    if not valid_orders or slot_idx >= len(valid_orders):
        return []
    out = []
    for order in valid_orders[slot_idx] or []:
        try:
            out.append(_order_action_key_with_mechanic(order))
        except Exception:
            continue
    return out


def _raw_score_map_for_slot(
    slot_scores: dict, valid_orders, slot_idx: int
) -> dict:
    """V2l.1 — return a JSON-serializable raw score
    map for one slot. Keys are action-key tuples
    (canonical) and values are raw float scores
    produced by ``score_action`` BEFORE any
    runtime-specific metadata.
    """
    if not valid_orders or slot_idx >= len(valid_orders):
        return {}
    out = {}
    for order in valid_orders[slot_idx] or []:
        try:
            key = _order_action_key(order)
            out[key] = float(
                slot_scores.get(id(order), 0.0) or 0.0
            )
        except Exception:
            continue
    return out


def _raw_score_map_with_mechanic_for_slot(
    slot_scores: dict, valid_orders, slot_idx: int
) -> dict:
    """V4a — same as ``_raw_score_map_for_slot`` but
    with mechanic-aware 4-tuple keys.
    """
    if not valid_orders or slot_idx >= len(valid_orders):
        return {}
    out = {}
    for order in valid_orders[slot_idx] or []:
        try:
            key = _order_action_key_with_mechanic(order)
            out[key] = float(
                slot_scores.get(id(order), 0.0) or 0.0
            )
        except Exception:
            continue
    return out


def _safety_block_map_for_slot(
    safety_blocked: dict, valid_orders, slot_idx: int
) -> dict:
    """V2l.1 — return a JSON-serializable safety block
    map for one slot. Keys are action-key tuples and
    values are bool. Built from the id-keyed
    ``safety_blocked`` dict produced by
    ``_compute_order_safety_blocks``.
    """
    if not valid_orders or slot_idx >= len(valid_orders):
        return {}
    out = {}
    for order in valid_orders[slot_idx] or []:
        try:
            out[_order_action_key(order)] = bool(
                safety_blocked.get(id(order), False)
            )
        except Exception:
            continue
    return out


def _final_action_keys_from_joint(
    joint_order, slot_0_action: int = 0, slot_1_action: int = 1
) -> list:
    """V2l.1 — return the two final per-slot action
    keys for a joint order. The list is index-aligned
    with the slot order: [slot_0_key, slot_1_key].

    ponytail: Step 2b fix. The original returns a
    list, not a tuple. My Step 1 extraction changed
    the return type which broke the V3c runtime
    test_pure_helpers_final_action_keys_match. This
    restores the original return type and default
    None handling.
    """
    if joint_order is None:
        return [("none", "", 0), ("none", "", 0)]
    first = getattr(joint_order, "first_order", None)
    second = getattr(joint_order, "second_order", None)
    return [
        _order_action_key(first),
        _order_action_key(second),
    ]


def _final_action_keys_with_mechanic_from_joint(
    joint_order, slot_0_action: int = 0, slot_1_action: int = 1
) -> list:
    """V4a — same as ``_final_action_keys_from_joint``
    but with mechanic-aware 4-tuple keys.

    ponytail: Step 2b fix. Matches the V2l1 version's
    return type (list) and None handling for
    consistency.
    """
    if joint_order is None:
        return [("none", "", 0, ""), ("none", "", 0, "")]
    first = getattr(joint_order, "first_order", None)
    second = getattr(joint_order, "second_order", None)
    return [
        _order_action_key_with_mechanic(first),
        _order_action_key_with_mechanic(second),
    ]


def _selected_joint_key(joint_order) -> tuple:
    """V2l.1 — canonical key for the selected joint order.

    Returns a 2-tuple of ``_order_action_key`` for
    each slot. If the joint order is None, returns
    ``(("none", "", 0), ("none", "", 0))``.

    ponytail: Step 2b fix. The original returns a
    TUPLE with direct ``_order_action_key`` calls
    (NOT a call to ``_final_action_keys_from_joint``,
    which is a list). My Step 1 wrongly delegated to
    ``_final_action_keys_from_joint``, which is a
    list — this broke test_selected_joint_key_match.
    This restores the original tuple behavior.
    """
    if joint_order is None:
        return (("none", "", 0), ("none", "", 0))
    first = getattr(joint_order, "first_order", None)
    second = getattr(joint_order, "second_order", None)
    return (
        _order_action_key(first),
        _order_action_key(second),
    )


def _selected_joint_key_with_mechanic(joint_order) -> tuple:
    """V4a — same as ``_selected_joint_key`` but with
    mechanic-aware 4-tuple keys.

    ponytail: Step 2b fix. Same pattern as
    ``_selected_joint_key``: returns a tuple with
    direct calls (not delegated through the list
    variant).
    """
    if joint_order is None:
        return (("none", "", 0, ""), ("none", "", 0, ""))
    first = getattr(joint_order, "first_order", None)
    second = getattr(joint_order, "second_order", None)
    return (
        _order_action_key_with_mechanic(first),
        _order_action_key_with_mechanic(second),
    )


def classify_only_legal(
    joint_orders, slot_idx, selected_order, safety_blocked=None
) -> bool:
    """Production helper: True when the selected blocked action has no
    non-safety-blocked alternative for *slot_idx* across all joint orders.

    Args:
        joint_orders: list of joint orders
        slot_idx: 0 or 1
        selected_order: the actually selected order for this slot
        safety_blocked: dict mapping id(order) -> True for safety-blocked
            orders.  If None, treats no orders as blocked.

    Returns True only when every alternative for this slot is also
    safety-blocked (or there are no alternatives).  Two different blocked
    Ground actions still count as no safe alternative.
    """
    if safety_blocked is None:
        safety_blocked = {}

    sel_key = _order_action_key(selected_order)
    # If selected action is not blocked, only_legal is irrelevant
    if not safety_blocked.get(id(selected_order), False):
        return False

    for jo in joint_orders:
        order = jo.first_order if slot_idx == 0 else jo.second_order
        if order is None:
            continue
        order_key = _order_action_key(order)
        # Different action AND not safety-blocked => safe alternative exists
        if order_key != sel_key and not safety_blocked.get(id(order), False):
            return False

    return True


# Phase BI-3G — Mega-capable species allowlist.
# poke-env's ``battle.can_mega_evolve`` flag is populated from
# the Showdown protocol's ``|canmega|`` message. In some
# formats / teams the protocol reports ``True`` even for
# species that do NOT have a Mega form (BI-3F-2 finding:
# pair 19 with a Dragonite lead got a Mega selection). To
# prevent the bot from generating / selecting Mega orders
# for non-Mega-capable species, we maintain a conservative
# local allowlist of base species with known Mega forms.
#
# The allowlist is normalized to ``str.lower()``; species
# strings like ``"Charizard-Mega-X"`` or
# ``"charizardmegax"`` are reduced to the base species via
# ``_normalize_species_for_mega``. Forms / variants / items /
# abilities are NOT inspected; only the base species
# matters here.
#
# This list deliberately excludes Dragonite, Incineroar, and
# any other species that have NO official Mega form in any
# generation. Garchomp is NOT on this list because Mega
# Garchomp exists in the data but we are conservatively
# excluding it for this format (the project can opt-in
# later by adding the species).
MEGA_CAPABLE_SPECIES = frozenset({
    # gen 1
    "venusaur",
    "charizard",
    "blastoise",
    "beedrill",
    "pidgeot",
    "alakazam",
    "slowbro",
    "gengar",
    "kangaskhan",
    "pinsir",
    "gyarados",
    "aerodactyl",
    "mewtwo",
    # gen 2
    "ampharos",
    "scizor",
    "heracross",
    "houndoom",
    "tyranitar",
    # gen 3
    "blaziken",
    "gardevoir",
    "mawile",
    "aggron",
    "medicham",
    "manectric",
    "sharpedo",
    "camerupt",
    "altaria",
    "banette",
    "absol",
    "glalie",
    "salamence",
    "metagross",
    "latias",
    "latios",
    "rayquaza",
    # gen 3 starters
    "swampert",
    "sceptile",
    # gen 4
    "lucario",
    "abomasnow",
    "gallade",
    # gen 4 evolution (via Metal Coat / Reaper Cloth)
    "steelix",
    # gen 5
    "audino",
    # gen 6
    "diancie",
    # gen 7
    "lopunny",
    # gen 3 alternate (Dusk Stone)
    "sableye",
})


def _normalize_species_for_mega(species: Any) -> str:
    """Phase BI-3G: Normalize a Pokemon species string to
    its base form for Mega-capability lookup.

    Handles forms like ``"Charizard-Mega-X"``,
    ``"charizardmegax"``, ``"Charizard Mega X"`` by reducing
    to ``"charizard"``. Non-string inputs return ``""``.
    """
    if species is None:
        return ""
    if not isinstance(species, str):
        try:
            species = str(species)
        except Exception:
            return ""
    s = species.strip().lower()
    if not s:
        return ""
    # Strip form suffixes: "-mega-*" or "-mega*" or " mega *".
    for sep in ("-mega ", "-mega", " mega ", " mega"):
        idx = s.find(sep)
        if idx > 0:
            s = s[:idx]
            break
    # Handle concatenated forms like "charizardmegax" or
    # "venusaurmega" by splitting at "mega" if it appears as
    # a substring (the dash-separated case was handled above).
    if "mega" in s:
        idx = s.find("mega")
        if idx > 0:
            s = s[:idx]
    # Strip non-alphanumeric.
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append(" ")
    s = "".join(out).strip()
    # After cleanup, also split on whitespace.
    s = s.split()[0] if s else ""
    return s


# Phase BI-3A — Mega Evolution legal-order generation.
# Default OFF: ``_current_valid_orders`` remains exactly
# ``battle.valid_orders`` (no Mega variants appended).
# Flag ON: each per-slot move order whose underlying
# ``Move`` is non-switch and whose order has no existing
# mechanic flag gets a parallel Mega variant appended
# adjacent to the plain order.
def _filter_non_mega_capable_orders(battle, slot_idx, base_orders):
    """Phase BI-3G: Strip Mega-flagged orders whose active
    Pokemon is NOT in the ``MEGA_CAPABLE_SPECIES`` allowlist.

    This counteracts poke-env's permissive
    ``battle.valid_orders`` augmentation, which appends
    Mega variants whenever ``can_mega_evolve[si]`` is True
    regardless of whether the active species can actually
    Mega. The filter is a no-op for orders that are not
    Mega-flagged.
    """
    if not base_orders:
        return list(base_orders) if base_orders else []
    try:
        active_pokemon = getattr(battle, "active_pokemon", None)
        if not active_pokemon or slot_idx < 0 or slot_idx >= len(active_pokemon):
            return list(base_orders)
        active_mon = active_pokemon[slot_idx]
    except Exception:
        return list(base_orders)
    if active_mon is None:
        return list(base_orders)
    species_norm = _normalize_species_for_mega(
        getattr(active_mon, "species", None)
    )
    if species_norm in MEGA_CAPABLE_SPECIES:
        # Active species is Mega-capable; no filtering needed.
        return list(base_orders)
    out = []
    for order in base_orders:
        try:
            is_mega = bool(getattr(order, "mega", False))
        except Exception:
            is_mega = False
        if is_mega:
            # Drop the Mega variant for non-Mega-capable species.
            continue
        out.append(order)
    return out


def _can_generate_mega_order_for_slot(battle, slot_idx, order):
    """Phase BI-3A: Return True iff a Mega variant of
    ``order`` is safe to generate for slot ``slot_idx``.

    Rules:
      - ``battle.can_mega_evolve[slot_idx]`` must be True.
      - The active Pokemon's base species must be in the
        ``MEGA_CAPABLE_SPECIES`` allowlist (BI-3G). This is
        a safety guard against poke-env's permissive
        ``can_mega_evolve`` flag (BI-3F-2 finding).
      - ``order`` must be a ``SingleBattleOrder`` wrapping
        a ``Move`` (not a switch, not a string pass).
      - The order must not already carry a mechanic flag
        (mega / z_move / dynamax / terastallize).
      - Defensive: any unexpected attribute shape returns
        False (no Mega variant).

    Hidden-info safe: only reads visible state
    (``can_mega_evolve`` and the active Pokemon's
    ``species`` attribute) which are exposed in the
    protocol request and reflected in poke-env's request
    parsing.
    """
    if order is None:
        return False
    try:
        from poke_env.battle.double_battle import SingleBattleOrder
        if not isinstance(order, SingleBattleOrder):
            return False
    except Exception:
        return False
    if getattr(order, "mega", False):
        return False
    if getattr(order, "z_move", False):
        return False
    if getattr(order, "dynamax", False):
        return False
    if getattr(order, "terastallize", False):
        return False
    inner = getattr(order, "order", None)
    if inner is None:
        return False
    if not hasattr(inner, "id"):
        return False
    # Phase BI-3G: read the active Pokemon for this slot and
    # confirm its base species is Mega-capable. This is the
    # safety guard against poke-env's permissive
    # ``can_mega_evolve`` flag.
    try:
        active_pokemon = getattr(battle, "active_pokemon", None)
        if not active_pokemon or slot_idx < 0 or slot_idx >= len(active_pokemon):
            return False
        active_mon = active_pokemon[slot_idx]
    except Exception:
        return False
    if active_mon is None:
        return False
    species_raw = getattr(active_mon, "species", None)
    species_norm = _normalize_species_for_mega(species_raw)
    if species_norm not in MEGA_CAPABLE_SPECIES:
        return False
    try:
        can_mega = getattr(battle, "can_mega_evolve", None)
    except Exception:
        can_mega = None
    if not can_mega or not isinstance(can_mega, (list, tuple)):
        return False
    if slot_idx < 0 or slot_idx >= len(can_mega):
        return False
    try:
        return bool(can_mega[slot_idx])
    except Exception:
        return False


def _build_mega_legal_orders_for_slot(battle, slot_idx, base_orders):
    """Phase BI-3A: Return a list of legal orders for
    slot ``slot_idx`` that augments ``base_orders`` with
    parallel Mega variants when eligible.

    Ordering invariant: plain order first, Mega variant
    immediately after. If the order is not eligible for
    Mega, the plain order is returned as-is.

    The Mega variant is a fresh ``SingleBattleOrder``
    instance wrapping the same ``Move`` and same
    ``move_target`` with ``mega=True``.
    """
    if not base_orders:
        return list(base_orders) if base_orders else []
    from poke_env.battle.double_battle import SingleBattleOrder
    out = []
    for order in base_orders:
        out.append(order)
        if _can_generate_mega_order_for_slot(battle, slot_idx, order):
            try:
                inner = order.order
                target = getattr(order, "move_target", 0)
                mega_order = SingleBattleOrder(
                    inner, move_target=target, mega=True
                )
                out.append(mega_order)
            except Exception:
                # Defensive: if the Mega variant cannot be
                # constructed for any reason, the plain
                # order stays in the legal list.
                continue
    return out




def _filter_all_mega_orders(slot_orders):
    """Phase BI-3K: Strip ALL Mega-flagged orders from
    ``slot_orders``. Used when ``enable_mega_evolution=False``
    to ensure a true OFF baseline (no Mega variants in the
    bot's view of valid orders, regardless of poke-env's
    pre-augmentation).
    """
    if not slot_orders:
        return list(slot_orders) if slot_orders else []
    out = []
    for order in slot_orders:
        try:
            is_mega = bool(getattr(order, "mega", False))
        except Exception:
            is_mega = False
        if is_mega:
            continue
        out.append(order)
    return out


def _augment_valid_orders_with_mega(battle, valid_orders, config):
    """Phase BI-3A: Wrapper around ``battle.valid_orders``
    that augments each slot with Mega variants when
    ``config.enable_mega_evolution`` is True.

    Flag OFF (default): returns ``valid_orders`` with ALL
    Mega-flagged orders stripped (Phase BI-3K). This makes the
    OFF baseline truly OFF — poke-env's pre-augmentation of
    valid_orders (which adds Mega variants whenever
    ``can_mega_evolve[i]`` is True) is reverted.
    Flag ON: replaces each per-slot list with the augmented
    list from ``_build_mega_legal_orders_for_slot``, after
    also filtering non-Mega-capable species (Phase BI-3G).

    Phase BI-3G: when flag ON, this helper also filters out
    any Mega-flagged orders whose active Pokemon is NOT in
    the ``MEGA_CAPABLE_SPECIES`` allowlist. poke-env's
    ``battle.valid_orders`` already appends Mega variants
    when ``can_mega_evolve[i]`` is True, regardless of
    species. Without this filter, non-Mega-capable species
    (e.g. Dragonite) would still receive Mega orders from
    poke-env, defeating the BI-3G species guard.

    Phase BI-3K: when flag OFF, this helper strips ALL Mega
    variants regardless of allowlist. This ensures the OFF
    baseline is a true OFF — the bot sees zero Mega orders
    in its valid_orders list. This is required for a valid
    ON-vs-OFF qualification comparison.
    """
    if not valid_orders:
        return valid_orders
    try:
        slots = max(len(valid_orders), 2)
    except Exception:
        return valid_orders
    # Phase BI-3K: flag OFF strips ALL Mega variants for a
    # true OFF baseline. Flag ON filters non-allowlisted Mega
    # variants (BI-3G) then augments.
    if config is None or not getattr(
        config, "enable_mega_evolution", False
    ):
        # Flag OFF: strip all Mega variants.
        stripped = []
        for si in range(slots):
            slot_orders = (
                valid_orders[si]
                if si < len(valid_orders)
                else []
            )
            stripped.append(_filter_all_mega_orders(slot_orders))
        return stripped
    # Flag ON: filter non-allowlisted Mega variants, then
    # augment with allowlisted Mega variants.
    filtered = []
    for si in range(slots):
        slot_orders = (
            valid_orders[si]
            if si < len(valid_orders)
            else []
        )
        slot_orders = _filter_non_mega_capable_orders(
            battle, si, slot_orders
        )
        filtered.append(slot_orders)
    augmented = []
    for si in range(slots):
        augmented.append(
            _build_mega_legal_orders_for_slot(
                battle, si, filtered[si]
            )
        )
    return augmented
