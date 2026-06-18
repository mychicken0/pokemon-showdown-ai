"""Canonical safety precomputation for all valid orders.

ponytail: Phase Ponytail Refactor Step 5.
Extracted ``_compute_order_safety_blocks`` from
``bot_doubles_damage_aware.py`` to a focused module.

The function in this module is the same code that
used to live at lines 783-1020 of
``bot_doubles_damage_aware.py``. The behavior is
bit-for-bit identical (8-tuple return shape,
narrow ally-heal integration preserved).

Return shape (8-tuple):
    (
        _direct_absorb_blocked,        # dict[order_id -> bool]
        _safety_blocked,                # dict[order_id -> bool]
        _ally_redirect_blocked,         # dict[order_id -> bool]
        _ally_redirect_blocked_meta,    # dict[order_id -> dict]
        _support_target_blocked,        # dict[order_id -> bool]
        _support_target_reasons,        # dict[order_id -> str]
        _narrow_blocked,                # dict[order_id -> bool]
        _narrow_reasons,                # dict[order_id -> str]
    )

Dependency notes:
- This module imports from
  ``doubles_engine.mechanics``,
  ``doubles_engine.support_targets`` at top level.
  Both are independent of the bot (no cycle).
- Four bot-local helpers are referenced via
  function-local lazy imports:
  - ``ally_redirects_our_single_target_move`` (bot line 554)
  - ``evaluate_priority_move_legality`` (bot line 312)
  - ``get_known_ability`` (bot line 456)
  - ``is_opponent_spread_move`` (bot line 1534)
  These are all defined later in the bot module
  than the safety_blocks shim, so a top-level
  import would create a cycle.
"""

from typing import Any, Dict, List, Optional, Tuple

from doubles_engine.mechanics import (
    _ability_block_enabled,
    ability_hard_blocks_move,
    ability_redirects_single_target_move,
    direct_known_absorb_blocks_move,
)
from doubles_engine.support_targets import (
    narrow_ally_heal_wrong_side_block,
    support_move_wrong_side_block,
)


def _bot_ally_redirects_our_single_target_move(*args, **kwargs):
    """Lazy import wrapper for the bot-local
    ``ally_redirects_our_single_target_move``.
    """
    from bot_doubles_damage_aware import (
        ally_redirects_our_single_target_move as _impl,
    )
    return _impl(*args, **kwargs)


def _bot_evaluate_priority_move_legality(*args, **kwargs):
    """Lazy import wrapper for the bot-local
    ``evaluate_priority_move_legality``.
    """
    from bot_doubles_damage_aware import (
        evaluate_priority_move_legality as _impl,
    )
    return _impl(*args, **kwargs)


def _bot_get_known_ability(*args, **kwargs):
    """Lazy import wrapper for the bot-local
    ``get_known_ability``.
    """
    from bot_doubles_damage_aware import get_known_ability as _impl
    return _impl(*args, **kwargs)


def _bot_is_opponent_spread_move(*args, **kwargs):
    """Lazy import wrapper for the bot-local
    ``is_opponent_spread_move``.
    """
    from bot_doubles_damage_aware import is_opponent_spread_move as _impl
    return _impl(*args, **kwargs)


def _compute_order_safety_blocks(battle, config, valid_orders):
    """Canonical safety precomputation for all valid orders.

    Returns (_direct_absorb_blocked, _safety_blocked) dicts keyed by id(order).
    Used by both actual choose_move selection and pure counterfactual selection.
    """
    _direct_absorb_blocked = {}
    _direct_absorb_enabled = getattr(
        config, "enable_ability_hard_safety_only", False
    ) and getattr(config, "ability_hard_safety_direct_absorb_only", False)
    if _direct_absorb_enabled:
        for slot_idx, orders in enumerate(valid_orders):
            for ord in orders:
                if ord and hasattr(ord.order, "base_power"):
                    t_pos = ord.move_target
                    if t_pos in (1, 2):
                        t_mon = battle.opponent_active_pokemon[t_pos - 1]
                        a_mon = battle.active_pokemon[slot_idx]
                        if t_mon and a_mon:
                            if not _bot_is_opponent_spread_move(ord.order, ord):
                                blocked, _ = direct_known_absorb_blocks_move(
                                    ord.order, a_mon, t_mon, battle, ord
                                )
                                if blocked:
                                    _direct_absorb_blocked[id(ord)] = True

    _safety_blocked = {}
    for slot_idx, orders in enumerate(valid_orders):
        if not orders:
            continue
        active_mon = battle.active_pokemon[slot_idx]
        if not active_mon:
            continue
        for ord in orders:
            if ord and hasattr(ord.order, "base_power"):
                move = ord.order
                target_pos = ord.move_target
                if target_pos in (1, 2):
                    target_mon = battle.opponent_active_pokemon[target_pos - 1]
                    if target_mon:
                        base_power = getattr(move, "base_power", 0)
                        category = getattr(move, "category", None)
                        category_name = getattr(category, "name", "STATUS")

                        is_blocked = False
                        if category_name == "STATUS" or base_power == 0:
                            if getattr(
                                config,
                                "enable_priority_field_hard_safety",
                                False,
                            ):
                                priority_res = _bot_evaluate_priority_move_legality(
                                    move, active_mon, target_mon, battle, config
                                )
                                if priority_res and priority_res[0]:
                                    is_blocked = True
                                    reason_prio = priority_res[1]
                                    if not _ability_block_enabled(config, reason_prio):
                                        is_blocked = False

                        # Phase 6.4.5d: Type immunity hard safety
                        if not is_blocked:
                            from bot_doubles_damage_aware import (
                                is_type_immune,
                            )
                            immune, reason_imm = is_type_immune(
                                move, active_mon, target_mon, battle
                            )
                            if immune:
                                is_blocked = True
                                if not _ability_block_enabled(
                                    config, reason_imm
                                ):
                                    is_blocked = False

                        if not is_blocked:
                            blocked_h, reason_h = ability_hard_blocks_move(
                                move, active_mon, target_mon, battle, config
                            )
                            if blocked_h and _ability_block_enabled(
                                config, reason_h
                            ):
                                is_blocked = True

                        if is_blocked:
                            _safety_blocked[id(ord)] = True

    # Phase 6.3.8: Support Move Target Hard Safety
    _support_target_blocked = {}
    _support_target_reasons = {}
    if getattr(config, "enable_support_move_target_hard_safety", False):
        for slot_idx, orders in enumerate(valid_orders):
            if not orders:
                continue
            for ord_obj in orders:
                if ord_obj and hasattr(ord_obj.order, "id"):
                    blocked, reason = support_move_wrong_side_block(
                        ord_obj, slot_idx, battle, config=config
                    )
                    if blocked:
                        _support_target_blocked[id(ord_obj)] = True
                        _support_target_reasons[id(ord_obj)] = reason

    _ally_redirect_blocked = {}
    _ally_redirect_blocked_meta = {}
    if getattr(config, "enable_known_ally_redirection_hard_safety", False):
        for slot_idx, orders in enumerate(valid_orders):
            for ord in orders:
                if (
                    ord
                    and hasattr(ord.order, "base_power")
                    and getattr(ord.order, "base_power", 0) > 0
                ):
                    t_pos = ord.move_target
                    if t_pos in (1, 2):
                        ally_idx = 1 - slot_idx
                        ally = (
                            battle.active_pokemon[ally_idx]
                            if ally_idx < len(battle.active_pokemon)
                            else None
                        )
                        if ally and not getattr(ally, "fainted", False):
                            redirects, reason = (
                                _bot_ally_redirects_our_single_target_move(
                                    ord.order,
                                    battle.active_pokemon[slot_idx],
                                    ally,
                                    battle,
                                )
                            )
                            if redirects:
                                oid = id(ord)
                                _ally_redirect_blocked[oid] = True
                                target_opp = None
                                if len(battle.opponent_active_pokemon) > t_pos - 1:
                                    target_opp = battle.opponent_active_pokemon[
                                        t_pos - 1
                                    ]
                                ally_ab = (
                                    _bot_get_known_ability(ally, battle) or ""
                                )
                                _ally_redirect_blocked_meta[oid] = {
                                    "move_id": getattr(ord.order, "id", ""),
                                    "attacker_species": getattr(
                                        battle.active_pokemon[slot_idx],
                                        "species",
                                        "",
                                    ),
                                    "target_species": (
                                        getattr(target_opp, "species", "")
                                        if target_opp
                                        else ""
                                    ),
                                    "ally_species": (
                                        getattr(ally, "species", "")
                                        if ally
                                        else ""
                                    ),
                                    "ally_ability": ally_ab,
                                    "reason": reason,
                                    "known_before_decision": bool(ally_ab),
                                }

    # Phase 6.3.8d: Narrow ally-heal wrong-side hard safety.
    # Only Heal Pulse / Floral Healing / Decorate
    # aimed at an opponent are blocked. This is the
    # production-grade replacement for the broad
    # support-target hard safety (Phase 6.3.8).
    _narrow_blocked = {}
    _narrow_reasons = {}
    if getattr(config, "enable_ally_heal_wrong_side_hard_safety", False):
        for slot_idx, orders in enumerate(valid_orders):
            if not orders:
                continue
            for ord_obj in orders:
                if ord_obj and hasattr(ord_obj.order, "id"):
                    blocked, reason = narrow_ally_heal_wrong_side_block(
                        ord_obj, slot_idx, battle, config=config
                    )
                    if blocked:
                        _narrow_blocked[id(ord_obj)] = True
                        _narrow_reasons[id(ord_obj)] = reason

    return (
        _direct_absorb_blocked,
        _safety_blocked,
        _ally_redirect_blocked,
        _ally_redirect_blocked_meta,
        _support_target_blocked,
        _support_target_reasons,
        _narrow_blocked,
        _narrow_reasons,
    )
