"""Dynamic-type absorb candidate classification helper.

ponytail: Phase Ponytail Refactor Step 4B.
Extracted ``classify_dynamic_type_absorb_candidates``
from ``bot_doubles_damage_aware.py`` to a focused
module.

The helper in this module is the same code that
used to live at lines 780-957 of
``bot_doubles_damage_aware.py``. The behavior is
bit-for-bit identical.

Dependency notes:
- This module imports from
  ``doubles_engine.mechanics``,
  ``doubles_engine.protocol``,
  ``doubles_engine.types`` and
  ``doubles_engine.support_targets`` at top level.
  All those modules are independent of the bot
  (no cycle).
- ``_ALLOWED_DYNAMIC_ABSORB_REASONS`` is a
  frozenset of reason strings that the helper
  uses to decide whether a blocked move is a
  dynamic-type absorb opportunity. The
  authoritative copy lives here.
"""

from doubles_engine.mechanics import (
    ability_hard_blocks_move,
    resolve_known_ability,
)
from doubles_engine.protocol import find_protocol_ability_reveal_turn
from doubles_engine.types import resolve_effective_move_type


def _get_known_ability(pokemon, battle=None):
    """Lazy import wrapper for the bot-local
    ``get_known_ability`` (not in
    ``doubles_engine.mechanics``).

    ponytail: ``get_known_ability`` lives in
    ``bot_doubles_damage_aware.py`` at line 456 and
    is referenced here via late binding. We import
    lazily to avoid the bot -> engine -> bot cycle.
    """
    from bot_doubles_damage_aware import get_known_ability as _impl
    return _impl(pokemon, battle)


_ALLOWED_DYNAMIC_ABSORB_REASONS = frozenset(
    {
        "water_into_waterabsorb",
        "water_into_stormdrain",
        "water_into_dryskin",
        "electric_into_voltabsorb",
        "electric_into_motordrive",
        "electric_into_lightningrod",
        "fire_into_flashfire",
        "fire_into_wellbakedbody",
        "grass_into_sapsipper",
    }
)


def classify_dynamic_type_absorb_candidates(
    valid_orders,
    selected_order,
    attacker,
    opponent_targets,
    battle,
    config,
    candidate_scores,
) -> dict:
    """Classify dynamic-type absorb candidates for audit."""
    result = {
        "candidate_blocked": False,
        "selected": False,
        "avoided": False,
        "reason": "",
        "target_species": "",
        "target_ability": "",
        "blocked_order_id": "",
        "blocked_candidate_score": 0.0,
        "dynamic_candidate_available": False,
        "dynamic_candidate_move_id": "",
        "dynamic_candidate_declared_type": "",
        "dynamic_candidate_effective_type": "",
        "dynamic_candidate_form": "",
        "dynamic_candidate_source": "",
        "dynamic_candidate_target_table": [],
    }
    if not attacker or not valid_orders:
        return result
    selected_meta = None
    best_blocked_score = float("-inf")
    best_meta = None
    seen_opportunity = set()
    table_rows = {}
    for cand in valid_orders or []:
        if not cand or not hasattr(cand, "order"):
            continue
        move = getattr(cand, "order", None)
        if not move or getattr(move, "base_power", 0) <= 0:
            continue
        t_pos = getattr(cand, "move_target", None)
        if t_pos not in (1, 2):
            continue
        t_mon = (
            opponent_targets[t_pos - 1]
            if opponent_targets and len(opponent_targets) >= t_pos
            else None
        )
        if not t_mon or getattr(t_mon, "fainted", False):
            continue
        resolved = resolve_effective_move_type(move, attacker, battle)
        if not resolved["dynamic_applied"]:
            continue

        move_id = getattr(move, "id", "")
        form = resolved.get("observed_form", "")
        target_key = (move_id, form, t_pos)
        is_sel = cand is selected_order
        blocked, reason = ability_hard_blocks_move(
            move, attacker, t_mon, battle, config=config
        )
        absorb_blocked = blocked and reason in _ALLOWED_DYNAMIC_ABSORB_REASONS
        sc = candidate_scores.get(id(cand), 0.0) if candidate_scores else 0.0
        tgt_ability = _get_known_ability(t_mon, battle) or ""
        tgt_resolution = resolve_known_ability(t_mon, battle, config)
        decision_turn = int(getattr(battle, "turn", 0))
        reveal_turn_val = (
            find_protocol_ability_reveal_turn(battle, t_mon, tgt_ability)
            if tgt_ability
            else None
        )
        known_before = bool(
            tgt_ability
            and tgt_resolution["source"] == "protocol_revealed"
            and reveal_turn_val is not None
            and reveal_turn_val <= decision_turn
        )
        row_data = {
            "move_id": move_id,
            "declared_type": resolved.get("declared_type", ""),
            "effective_type": resolved.get("effective_type", ""),
            "target_species": getattr(t_mon, "species", ""),
            "target_ability": tgt_ability,
            "target_known_ability": tgt_ability,
            "target_known_ability_source": tgt_resolution["source"],
            "known_before_decision": known_before,
            "form": form,
            "source": resolved.get("source", ""),
            "blocked": absorb_blocked,
            "reason": reason if absorb_blocked else "",
            "move_target": t_pos,
        }
        table_rows[target_key] = row_data
        if absorb_blocked:
            seen_opportunity.add(target_key)
            if sc > best_blocked_score:
                best_blocked_score = sc
                best_meta = {
                    "order_id": id(cand),
                    "move_id": move_id,
                    "target_species": getattr(t_mon, "species", ""),
                    "target_ability": tgt_ability,
                    "target_ability_source": tgt_resolution["source"],
                    "known_before_decision": known_before,
                    "form": form,
                    "source": resolved.get("source", ""),
                    "reason": reason,
                }
            if is_sel:
                selected_meta = {
                    "reason": reason,
                    "target_species": getattr(t_mon, "species", ""),
                    "target_ability": tgt_ability,
                    "target_ability_source": tgt_resolution["source"],
                    "known_before_decision": known_before,
                }

    # If selected_order itself is a dynamic-type absorb opportunity,
    # mark ``selected = True`` and ``candidate_blocked = True``.
    if selected_order is not None:
        sel_move = getattr(selected_order, "order", None)
        sel_t_pos = getattr(selected_order, "move_target", None)
        sel_key = (
            getattr(sel_move, "id", "") if sel_move else "",
            "",
            sel_t_pos,
        )
        if sel_key in seen_opportunity:
            result["selected"] = True
            result["candidate_blocked"] = True
            if selected_meta is not None:
                result["reason"] = selected_meta["reason"]
                result["target_species"] = selected_meta["target_species"]
                result["target_ability"] = selected_meta["target_ability"]
                result["blocked_order_id"] = str(id(selected_order))
                result["blocked_candidate_score"] = (
                    candidate_scores.get(id(selected_order), 0.0)
                    if candidate_scores
                    else 0.0
                )
        else:
            # selected_order is NOT a dynamic-type absorb opportunity
            # (e.g. it picked a different move). If a dynamic-type
            # absorb opportunity existed and was avoided, mark
            # ``avoided = True``.
            if seen_opportunity:
                result["avoided"] = True
                result["dynamic_candidate_available"] = True
                if best_meta is not None:
                    result["reason"] = best_meta["reason"]
                    result["target_species"] = best_meta["target_species"]
                    result["target_ability"] = best_meta["target_ability"]
                    result["blocked_order_id"] = str(best_meta["order_id"])
                    result["blocked_candidate_score"] = best_blocked_score
                    result["dynamic_candidate_move_id"] = best_meta["move_id"]
                    result["dynamic_candidate_form"] = best_meta["form"]
                    result["dynamic_candidate_source"] = best_meta["source"]

    if best_meta is not None and not result["selected"]:
        # Populate the dynamic-candidate fields for the auditor.
        result["dynamic_candidate_available"] = True
        result["dynamic_candidate_move_id"] = best_meta["move_id"]
        result["dynamic_candidate_declared_type"] = (
            table_rows.get(
                (
                    best_meta["move_id"],
                    best_meta["form"],
                    getattr(selected_order, "move_target", None)
                    if selected_order is not None
                    else None,
                ),
                {},
            ).get("declared_type", "")
        )
        result["dynamic_candidate_effective_type"] = (
            table_rows.get(
                (
                    best_meta["move_id"],
                    best_meta["form"],
                    getattr(selected_order, "move_target", None)
                    if selected_order is not None
                    else None,
                ),
                {},
            ).get("effective_type", "")
        )
        result["dynamic_candidate_form"] = best_meta["form"]
        result["dynamic_candidate_source"] = best_meta["source"]
        result["dynamic_candidate_target_table"] = list(table_rows.values())

    if best_meta is not None and result["selected"]:
        # Still populate the candidate table for audit visibility.
        result["dynamic_candidate_target_table"] = list(table_rows.values())

    if best_meta is not None and not result["selected"] and not result["avoided"]:
        # No opportunity at all; nothing to avoid. But still record
        # the table for audit if any rows were produced.
        if table_rows:
            result["dynamic_candidate_target_table"] = list(
                table_rows.values()
            )

    if best_meta is not None:
        result["blocked_order_id"] = best_meta["order_id"]
        result["blocked_candidate_score"] = best_blocked_score
    return result
