"""Support-target helpers extracted from ``bot_doubles_damage_aware.py``.

ponytail: Phase Ponytail Refactor Step 3.
Extracted the support-target classification and
wrong-side block helpers to a focused module.

The helpers in this module are the same code that
used to live at lines 286-378 (consts) and
389-957 (6 helpers) of ``bot_doubles_damage_aware``.
The behavior is bit-for-bit identical.

No import cycle:
- The original code only used ``DoublesDamageAwareConfig``
  and ``Move`` from poke_env (both top-level imports).
- ``DoublesDamageAwareConfig`` is referenced in the wrong-side
  block helpers as a fallback when ``config`` is None.
  Because the config class is defined in
  ``bot_doubles_damage_aware.py`` (line 31) and the original
  code references it at module load (it appears inside
  function bodies, not at top level), the reference works
  via late binding: the function is only called at runtime,
  by which time the bot module is fully loaded.

  In this new module, we use a lazy import inside the two
  wrong-side block functions to obtain
  ``DoublesDamageAwareConfig``, matching the late-binding
  pattern of the original.

The other dependencies (``Move``) come from poke_env and
are stable top-level imports.
"""

from typing import Any, Dict, List, Optional, Tuple

from poke_env.battle.move import Move


# Phase 6.3.8: Support move target intent classification
_SUPPORT_ALLY_BENEFICIAL_SINGLE = {
    "healpulse",
    "floralhealing",
    "decorate",
}
_SUPPORT_ALLY_BENEFICIAL_SINGLE_REASON = {
    "healpulse": "Heal Pulse restores HP; intended for ally",
    "floralhealing": "Floral Healing restores HP; intended for ally",
    "decorate": "Decorate sharply boosts ally's stats",
}
_SUPPORT_ALLY_BENEFICIAL_ALLIES = {
    "helpinghand",
    "coaching",
    "howl",
    "lifedew",
}
_SUPPORT_ALLY_BENEFICIAL_ALLIES_REASON = {
    "helpinghand": "Helping Hand boosts ally's move power",
    "coaching": "Coaching boosts ally's Attack and Defense",
    "howl": "Howl boosts ally's Attack",
    "lifedew": "Life Dew heals all allies",
}
_SUPPORT_ALLY_BENEFICIAL_TEAM = {
    "aromatherapy",
    "healbell",
}
_SUPPORT_ALLY_BENEFICIAL_TEAM_REASON = {
    "aromatherapy": "Aromatherapy cures team status",
    "healbell": "Heal Bell cures team status",
}

_SUPPORT_OPPONENT_DISRUPTIVE_SINGLE = {
    "taunt",
    "encore",
    "disable",
    "torment",
    "thunderwave",
    "willowisp",
    "toxic",
    "spore",
    "sleeppowder",
    "charm",
    "scaryface",
    "screech",
    "faketears",
    "metalsound",
    "gastroacid",
}
_SUPPORT_OPPONENT_DISRUPTIVE_REASON = {
    "taunt": "Taunt disables opponent's status moves",
    "encore": "Encore locks opponent into a repeated move",
    "disable": "Disable temporarily prevents opponent from using a move",
    "torment": "Torment prevents opponent from using the same move twice",
    "thunderwave": "Thunder Wave paralyzes opponent",
    "willowisp": "Will-o-Wisp burns opponent",
    "toxic": "Toxic badly poisons opponent",
    "spore": "Spore puts opponent to sleep",
    "sleeppowder": "Sleep Powder puts opponent to sleep",
    "charm": "Charm sharply lowers opponent's Attack",
    "scaryface": "Scary Face sharply lowers opponent's Speed",
    "screech": "Screech sharply lowers opponent's Defense",
    "faketears": "Fake Tears sharply lowers opponent's Sp.Def",
    "metalsound": "Metal Sound sharply lowers opponent's Sp.Def",
    "gastroacid": "Gastro Acid removes opponent's ability",
}
# Skill Swap is excluded from opponent-disruptive because it can
# legitimately target an ally (e.g., give them a useful ability).

# Moves with legitimate dual-side tactical use remain unclassified.
_SUPPORT_EITHER_MOVE_IDS = {
    "skillswap",
}
_SUPPORT_EITHER_REASON = {
    "skillswap": "Skill Swap can target ally or opponent strategically",
}

# Phase 6.3.8d: Narrow ally-heal wrong-side allowlist.
# These are the ONLY moves that the narrow flag
# hard-blocks. They are always ally-beneficial,
# single-target status moves that would be a
# severe mistake (healing an opponent) if aimed
# at the wrong side.
_NARROW_ALLY_HEAL_MOVE_IDS = {
    "healpulse",
    "floralhealing",
    "decorate",
}
_NARROW_ALLY_HEAL_REASON = {
    "healpulse": "Heal Pulse restores ally HP; aimed at opponent is severe mistake",
    "floralhealing": "Floral Healing restores ally HP; aimed at opponent is severe mistake",
    "decorate": "Decorate sharply boosts ally stats; aimed at opponent is severe mistake",
}

# Pollen Puff is special: damaging vs opponent, healing vs ally
_POLLEN_PUFF_MOVE_ID = "pollenpuff"


def classify_support_move_target_intent(move) -> dict:
    """Classify a move's intended target side based on its known behavior.

    Returns:
        dict with keys:
            classified (bool): True if we can determine the intent
            intended_side (str): "ally" | "opponent" | "self" | "field" | "either" | "unknown"
            reason (str): Human-readable explanation
            source (str): "move_metadata" | "explicit_allowlist" | "unclassified"
    """
    if not move:
        return {
            "classified": False,
            "intended_side": "unknown",
            "reason": "No move object",
            "source": "unclassified",
        }

    move_id = getattr(move, "id", "")
    if not move_id:
        return {
            "classified": False,
            "intended_side": "unknown",
            "reason": "Move has no ID",
            "source": "unclassified",
        }

    # Pollen Puff: dual-purpose, handled separately
    if move_id == _POLLEN_PUFF_MOVE_ID:
        return {
            "classified": True,
            "intended_side": "either",
            "reason": "Pollen Puff damages opponents, heals allies",
            "source": "explicit_allowlist",
        }

    # Check metadata first
    target_str = (
        str(getattr(move, "target", "") or "").lower().replace("_", "").replace(" ", "")
    )
    deduced_target = getattr(move, "deduced_target", None)
    deduced_str = str(deduced_target or "").lower().replace("_", "").replace(" ", "")

    # Self-targeting moves
    if target_str in ("self",) or deduced_str in ("self",):
        return {
            "classified": True,
            "intended_side": "self",
            "reason": "Move targets the user (metadata: self)",
            "source": "move_metadata",
        }

    # Ally-only targeting (adjacentAlly)
    if target_str in ("adjacentally",) or deduced_str in ("adjacentally",):
        return {
            "classified": True,
            "intended_side": "ally",
            "reason": "Move only targets ally (metadata: adjacentAlly)",
            "source": "move_metadata",
        }

    # Allies team-wide (allies, allySide, allyTeam)
    if target_str in ("allies", "allyside", "allyteam") or deduced_str in (
        "allies",
        "allyside",
        "allyteam",
    ):
        return {
            "classified": True,
            "intended_side": "field",
            "reason": "Move targets/allies team side (metadata)",
            "source": "move_metadata",
        }

    # Field-wide (all, allAdjacent, allAdjacentFoes, foeSide)
    if target_str in (
        "all",
        "alladjacent",
        "alladjacentfoes",
        "foeside",
        "randomnormal",
        "scripted",
    ) or deduced_str in (
        "all",
        "alladjacent",
        "alladjacentfoes",
        "foeside",
        "randomnormal",
        "scripted",
    ):
        return {
            "classified": True,
            "intended_side": "field",
            "reason": f"Field-wide/automatic targeting move (metadata: {target_str})",
            "source": "move_metadata",
        }

    # Adjacent Foe only (adjacentFoe)
    if target_str in ("adjacentfoe",) or deduced_str in ("adjacentfoe",):
        return {
            "classified": True,
            "intended_side": "opponent",
            "reason": "Move only targets adjacent foes (metadata: adjacentFoe)",
            "source": "move_metadata",
        }

    # Adjacent Ally Or Self (ADJACENT_ALLY_OR_SELF)
    if target_str in ("adjacentallyorself",) or deduced_str in ("adjacentallyorself",):
        return {
            "classified": True,
            "intended_side": "ally",
            "reason": "Move targets ally or self (metadata: adjacentAllyOrSelf)",
            "source": "move_metadata",
        }

    # Now use explicit allowlists for moves with "normal" or "any" target
    # that have a clear intended direction

    # Ally-beneficial single-target moves
    if move_id in _SUPPORT_ALLY_BENEFICIAL_SINGLE:
        reason = _SUPPORT_ALLY_BENEFICIAL_SINGLE_REASON.get(
            move_id, "Ally-beneficial support move"
        )
        return {
            "classified": True,
            "intended_side": "ally",
            "reason": reason,
            "source": "explicit_allowlist",
        }

    if move_id in _SUPPORT_ALLY_BENEFICIAL_ALLIES:
        reason = _SUPPORT_ALLY_BENEFICIAL_ALLIES_REASON.get(
            move_id, "Ally-boosting support move"
        )
        return {
            "classified": True,
            "intended_side": "ally",
            "reason": reason,
            "source": "explicit_allowlist",
        }

    if move_id in _SUPPORT_ALLY_BENEFICIAL_TEAM:
        reason = _SUPPORT_ALLY_BENEFICIAL_TEAM_REASON.get(
            move_id, "Team-curing support move"
        )
        return {
            "classified": True,
            "intended_side": "field",
            "reason": reason,
            "source": "explicit_allowlist",
        }

    # Moves that can legitimately target either side
    if move_id in _SUPPORT_EITHER_MOVE_IDS:
        reason = _SUPPORT_EITHER_REASON.get(move_id, "Move can target either side")
        return {
            "classified": True,
            "intended_side": "either",
            "reason": reason,
            "source": "explicit_allowlist",
        }

    # Opponent-directed disruptive status moves
    if move_id in _SUPPORT_OPPONENT_DISRUPTIVE_SINGLE:
        reason = _SUPPORT_OPPONENT_DISRUPTIVE_REASON.get(
            move_id, "Opponent-disruptive status move"
        )
        return {
            "classified": True,
            "intended_side": "opponent",
            "reason": reason,
            "source": "explicit_allowlist",
        }

    # Not classified
    return {
        "classified": False,
        "intended_side": "unknown",
        "reason": "Move not in classification lists",
        "source": "unclassified",
    }


def build_support_target_candidate_table(
    valid_orders_slot, slot_idx, battle, config=None
) -> list:
    """Build a candidate table of support-target orders for a slot-turn.

    Each row contains:
        move_id, attacker_species, target_position, target_side, target_species,
        intended_side, classification_source, blocked, block_reason,
        candidate_score, selected

    Deduplicated by (move_id, target_position).
    Only includes orders that have a classified intended side (opponent or ally).
    """
    rows = []
    seen = set()
    if not valid_orders_slot:
        return rows
    active_mon = (
        battle.active_pokemon[slot_idx]
        if slot_idx < len(battle.active_pokemon)
        else None
    )
    attacker_species = getattr(active_mon, "species", "") if active_mon else ""

    for order in valid_orders_slot:
        if not order or not hasattr(order, "order") or not hasattr(order.order, "id"):
            continue
        move = order.order
        move_id = getattr(move, "id", "")
        classification = classify_support_move_target_intent(move)
        if not classification["classified"]:
            continue
        intended_side = classification["intended_side"]
        # Only include ally/opponent classified moves
        if intended_side not in ("ally", "opponent"):
            continue
        target_pos = getattr(order, "move_target", 0)
        dedup_key = (move_id, target_pos)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        target_info = resolve_order_target_side(order, slot_idx, battle)
        blocked = False
        block_reason = ""
        if config and getattr(config, "enable_support_move_target_hard_safety", False):
            blocked, block_reason = support_move_wrong_side_block(
                order, slot_idx, battle, config=config
            )
        rows.append(
            {
                "move_id": move_id,
                "attacker_species": attacker_species,
                "slot": slot_idx,
                "target_position": target_pos,
                "target_side": target_info.get("side", "unknown"),
                "target_species": target_info.get("target_species", ""),
                "intended_side": intended_side,
                "classification_source": classification.get("source", ""),
                "blocked": blocked,
                "block_reason": block_reason,
                "selected": False,
            }
        )
    return rows


def build_narrow_ally_heal_candidate_table(
    valid_orders_slot, slot_idx, battle, config=None
) -> list:
    """Build a NARROW candidate table for the
    Phase 6.3.8d ally-heal wrong-side safety.

    Only the three narrow-allowlist moves are
    considered: Heal Pulse, Floral Healing, Decorate.
    Pollen Puff, Skill Swap, and opponent-disruption
    moves are NOT included. This avoids inflating the
    audit with non-applicable candidates.

    Each row contains:
        move_id, attacker_species, target_position,
        target_side, target_species, intended_side,
        classification_source, blocked, block_reason,
        selected

    The same dedup and target-resolution rules as
    ``build_support_target_candidate_table`` apply.
    """
    rows = []
    seen = set()
    if not valid_orders_slot:
        return rows
    active_mon = (
        battle.active_pokemon[slot_idx]
        if slot_idx < len(battle.active_pokemon)
        else None
    )
    attacker_species = getattr(active_mon, "species", "") if active_mon else ""

    for order in valid_orders_slot:
        if not order or not hasattr(order, "order") or not hasattr(order.order, "id"):
            continue
        move = order.order
        move_id = getattr(move, "id", "")

        # Narrow allowlist: only these three moves.
        if move_id not in _NARROW_ALLY_HEAL_MOVE_IDS:
            continue

        # All three are STATUS moves with
        # intended_side == "ally". We do not need
        # the broad classifier here because the
        # allowlist is authoritative.
        intended_side = "ally"
        target_pos = getattr(order, "move_target", 0)
        dedup_key = (move_id, target_pos)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        target_info = resolve_order_target_side(order, slot_idx, battle)
        blocked = False
        block_reason = ""
        if config and getattr(
            config, "enable_ally_heal_wrong_side_hard_safety", False
        ):
            blocked, block_reason = narrow_ally_heal_wrong_side_block(
                order, slot_idx, battle, config=config
            )
        rows.append(
            {
                "move_id": move_id,
                "attacker_species": attacker_species,
                "slot": slot_idx,
                "target_position": target_pos,
                "target_side": target_info.get("side", "unknown"),
                "target_species": target_info.get("target_species", ""),
                "intended_side": intended_side,
                "classification_source": "narrow_allowlist",
                "blocked": blocked,
                "block_reason": block_reason,
                "selected": False,
            }
        )
    return rows


def resolve_order_target_side(order, slot_idx, battle) -> dict:
    """Resolve which side an order targets.

    Returns:
        dict with keys:
            side (str): "ally" | "opponent" | "self" | "field" | "unknown"
            target_position (int | None): the move_target value
            target_species (str): species name of the target
            target_identity (str): identity string of the target
    """
    result = {
        "side": "unknown",
        "target_position": None,
        "target_species": "",
        "target_identity": "",
    }
    if not order or not battle:
        return result

    target_pos = getattr(order, "move_target", 0)
    result["target_position"] = target_pos

    if target_pos == 0:
        result["side"] = "field"
        return result

    # Our side: negative positions
    if target_pos in (-1, -2):
        ally_idx = abs(target_pos) - 1  # -1 -> 0, -2 -> 1
        result["side"] = (
            "self" if target_pos == (-1 if slot_idx == 0 else -2) else "ally"
        )
        # self = targeting your own slot; ally = targeting your partner's slot
        if ally_idx < len(battle.active_pokemon):
            mon = battle.active_pokemon[ally_idx]
            if mon:
                result["target_species"] = getattr(mon, "species", "")
                result["target_identity"] = getattr(
                    mon, "ident", getattr(mon, "name", "")
                )
        return result

    # Opponent side: positive positions
    if target_pos in (1, 2):
        result["side"] = "opponent"
        opp_idx = target_pos - 1
        if opp_idx < len(battle.opponent_active_pokemon):
            mon = battle.opponent_active_pokemon[opp_idx]
            if mon:
                result["target_species"] = getattr(mon, "species", "")
                result["target_identity"] = getattr(
                    mon, "ident", getattr(mon, "name", "")
                )
        return result

    return result


def support_move_wrong_side_block(order, slot_idx, battle, config=None) -> tuple:
    """Check if an order is a wrong-side support move that should be blocked.

    Args:
        order: SingleBattleOrder to check
        slot_idx: which of our slots (0 or 1)
        battle: DoubleBattle instance
        config: DoublesDamageAwareConfig (or None to check defaults)

    Returns:
        tuple[bool, str]: (blocked, reason)
    """
    if not order or not battle:
        return (False, "")

    if config is None:
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        c = DoublesDamageAwareConfig()
        if not c.enable_support_move_target_hard_safety:
            return (False, "")
    else:
        if not config.enable_support_move_target_hard_safety:
            return (False, "")

    move = getattr(order, "order", None)
    if not move or not hasattr(move, "id"):
        return (False, "")

    # Only applies to Move orders
    if not isinstance(move, Move):
        return (False, "")

    # Skip damaging moves that are not Pollen Puff
    base_power = getattr(move, "base_power", 0)
    category = getattr(move, "category", None)
    category_name = getattr(category, "name", "STATUS") if category else "STATUS"

    move_id = getattr(move, "id", "")

    # Pollen Puff is special
    if move_id == _POLLEN_PUFF_MOVE_ID:
        target_pos = getattr(order, "move_target", 0)
        if target_pos in (1, 2):
            # Targeting opponent: damaging move, not blocked
            return (False, "")
        elif target_pos in (-1, -2):
            # Targeting ally: healing, not blocked (correct usage)
            return (False, "")
        else:
            return (False, "")

    # Only block STATUS moves (or moves with 0 base_power that are also status)
    if category_name != "STATUS" and base_power > 0:
        return (False, "")

    # Also block damaging moves with dual heal/damage behavior that are NOT
    # handled above — currently only Pollen Puff is classified as either.
    # Any future dual-purpose damaging moves would be added here.

    classification = classify_support_move_target_intent(move)
    if not classification["classified"]:
        return (False, "")

    intended_side = classification["intended_side"]
    target_side_info = resolve_order_target_side(order, slot_idx, battle)
    actual_side = target_side_info["side"]

    # Field/team/either/unknown moves are never blocked
    if intended_side in ("field", "either", "unknown"):
        return (False, "")

    if intended_side == "self":
        if actual_side != "self":
            return (
                True,
                f"Self-targeting move {move_id} targeting {actual_side} instead of self",
            )
        return (False, "")

    if intended_side == "ally":
        # Ally-beneficial: targeting opponent is wrong, targeting self might be OK
        if actual_side == "opponent":
            target_species = target_side_info.get("target_species", "?")
            return (
                True,
                f"Ally-beneficial move {move_id} targeting opponent ({target_species}): {classification.get('reason', '')}",
            )
        return (False, "")

    if intended_side == "opponent":
        # Opponent-disruptive: targeting ally/self is wrong
        if actual_side in ("ally", "self"):
            target_species = target_side_info.get("target_species", "?")
            return (
                True,
                f"Opponent-disruptive move {move_id} targeting {actual_side} ({target_species}): {classification.get('reason', '')}",
            )
        return (False, "")

    return (False, "")


def narrow_ally_heal_wrong_side_block(
    order, slot_idx, battle, config=None
) -> tuple:
    """Narrow Phase 6.3.8d hard-block: only block
    ally-beneficial single-target support moves
    (Heal Pulse, Floral Healing, Decorate) aimed
    at an opponent.

    This is the production-grade replacement for
    the broad Phase 6.3.8 wrong-side support
    safety. It fixes the actual severe bug (healing
    an opponent) without penalizing general
    opponent-disruption choices (Taunt, Encore,
    Thunder Wave, etc.) or dual-purpose moves
    (Pollen Puff, Skill Swap).

    The two runtime modes (Random Doubles and VGC
    selected-four) call this function through the
    same canonical ``DoublesDamageAwarePlayer.
    choose_move`` path. There is no VGC-specific
    branch here.

    Args:
        order: SingleBattleOrder to check
        slot_idx: which of our slots (0 or 1)
        battle: DoubleBattle instance
        config: DoublesDamageAwareConfig (or None to check defaults)

    Returns:
        tuple[bool, str]: (blocked, reason)
    """
    if not order or not battle:
        return (False, "")

    if config is None:
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        c = DoublesDamageAwareConfig()
        if not c.enable_ally_heal_wrong_side_hard_safety:
            return (False, "")
    else:
        if not getattr(
            config, "enable_ally_heal_wrong_side_hard_safety", False
        ):
            return (False, "")

    move = getattr(order, "order", None)
    if not move or not hasattr(move, "id"):
        return (False, "")

    # Only applies to Move orders
    if not isinstance(move, Move):
        return (False, "")

    move_id = getattr(move, "id", "")

    # Narrow allowlist: only these three moves.
    if move_id not in _NARROW_ALLY_HEAL_MOVE_IDS:
        return (False, "")

    # Resolve the actual target side using the
    # existing helper (kept in lockstep with
    # slot mappings: slot 0 self=-1 ally=-2
    # opponent=1/2; slot 1 self=-2 ally=-1
    # opponent=1/2).
    target_side_info = resolve_order_target_side(order, slot_idx, battle)
    actual_side = target_side_info["side"]

    # Only block when target is opponent.
    if actual_side != "opponent":
        return (False, "")

    target_species = target_side_info.get("target_species", "?")
    reason = _NARROW_ALLY_HEAL_REASON.get(
        move_id, "Narrow ally-heal wrong-side block"
    )
    return (
        True,
        f"Narrow ally-heal block: {move_id} aimed at "
        f"opponent ({target_species}): {reason}",
    )


# ============================================================
# Phase RL-DATA-2: Support-move dataset classification helpers
# ============================================================
# Per RL-DATA-1 schema plan, every candidate move in the dataset
# must be classified by SUPPORT-AUDIT-1 categories. This is a
# dataset-instrumentation helper; it does not change scoring,
# behavior, or selected actions.

# 9 support groups (per SUPPORT-AUDIT-1 + RL-DATA-1):
GROUP_TARGET_SIDE_SAFETY = "target_side_safety"
GROUP_ABILITY_MECHANICS_SAFETY = "ability_mechanics_safety"
GROUP_ANTI_SETUP_DISRUPTION = "anti_setup_disruption"
GROUP_PROTECTION_DEFENSIVE_SUPPORT = "protection_defensive_support"
GROUP_SPEED_TURN_CONTROL = "speed_turn_control"
GROUP_WEATHER_TERRAIN = "weather_terrain"
GROUP_HEALING_BUFF_ALLY_SUPPORT = "healing_buff_ally_support"
GROUP_FIELD_SIDE_CONTROL = "field_side_control"
GROUP_SETUP_STAT_BOOST = "setup_stat_boost"
GROUP_UNKNOWN_NEEDS_PROBE = "unknown_needs_probe"

ALL_SUPPORT_GROUPS = (
    GROUP_TARGET_SIDE_SAFETY,
    GROUP_ABILITY_MECHANICS_SAFETY,
    GROUP_ANTI_SETUP_DISRUPTION,
    GROUP_PROTECTION_DEFENSIVE_SUPPORT,
    GROUP_SPEED_TURN_CONTROL,
    GROUP_WEATHER_TERRAIN,
    GROUP_HEALING_BUFF_ALLY_SUPPORT,
    GROUP_FIELD_SIDE_CONTROL,
    GROUP_SETUP_STAT_BOOST,
    GROUP_UNKNOWN_NEEDS_PROBE,
)

# 10 statuses (per SUPPORT-AUDIT-1 + RL-DATA-1):
STATUS_HANDLED_DEFAULT = "handled_default"
STATUS_HANDLED_OPT_IN = "handled_opt_in"
STATUS_WIRED_DEFAULT_OFF = "wired_default_off"
STATUS_BLOCKED_NOT_PROMOTED = "blocked_not_promoted"
STATUS_AUDIT_ONLY = "audit_only"
STATUS_SCORING_GAP_CONFIRMED = "scoring_gap_confirmed"
STATUS_NO_POSITIVE_STRATEGY = "no_positive_strategy"
STATUS_MECHANICS_SAFETY_ONLY = "mechanics_safety_only"
STATUS_FUTURE_WORK = "future_work"
STATUS_UNKNOWN_NEEDS_PROBE = "unknown_needs_probe"

ALL_SUPPORT_STATUSES = (
    STATUS_HANDLED_DEFAULT,
    STATUS_HANDLED_OPT_IN,
    STATUS_WIRED_DEFAULT_OFF,
    STATUS_BLOCKED_NOT_PROMOTED,
    STATUS_AUDIT_ONLY,
    STATUS_SCORING_GAP_CONFIRMED,
    STATUS_NO_POSITIVE_STRATEGY,
    STATUS_MECHANICS_SAFETY_ONLY,
    STATUS_FUTURE_WORK,
    STATUS_UNKNOWN_NEEDS_PROBE,
)

# Known support-move inventory (per SUPPORT-AUDIT-1).
# Maps move_id (lowercased, no spaces/dashes/underscores) to
# (group, status). The classification function uses this
# to assign group/status. Moves not in this inventory are
# tagged as unknown_needs_probe.

_KNOWN_SUPPORT_MOVE_INVENTORY: Dict[str, Tuple[str, str]] = {
    # Target-side safety
    "healpulse": (GROUP_HEALING_BUFF_ALLY_SUPPORT, STATUS_MECHANICS_SAFETY_ONLY),
    "floralhealing": (GROUP_HEALING_BUFF_ALLY_SUPPORT, STATUS_MECHANICS_SAFETY_ONLY),
    "decorate": (GROUP_HEALING_BUFF_ALLY_SUPPORT, STATUS_MECHANICS_SAFETY_ONLY),
    "helpinghand": (GROUP_HEALING_BUFF_ALLY_SUPPORT, STATUS_MECHANICS_SAFETY_ONLY),
    "coaching": (GROUP_HEALING_BUFF_ALLY_SUPPORT, STATUS_MECHANICS_SAFETY_ONLY),
    "howl": (GROUP_HEALING_BUFF_ALLY_SUPPORT, STATUS_MECHANICS_SAFETY_ONLY),
    "lifedew": (GROUP_HEALING_BUFF_ALLY_SUPPORT, STATUS_MECHANICS_SAFETY_ONLY),
    "aromatherapy": (GROUP_HEALING_BUFF_ALLY_SUPPORT, STATUS_MECHANICS_SAFETY_ONLY),
    "healbell": (GROUP_HEALING_BUFF_ALLY_SUPPORT, STATUS_MECHANICS_SAFETY_ONLY),
    "pollenpuff": (GROUP_HEALING_BUFF_ALLY_SUPPORT, STATUS_MECHANICS_SAFETY_ONLY),
    # Anti-setup / disruption
    "taunt": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_WIRED_DEFAULT_OFF),
    "encore": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_WIRED_DEFAULT_OFF),
    "disable": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_WIRED_DEFAULT_OFF),
    "quash": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_WIRED_DEFAULT_OFF),
    "torment": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_MECHANICS_SAFETY_ONLY),
    "thunderwave": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_MECHANICS_SAFETY_ONLY),
    "willowisp": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_MECHANICS_SAFETY_ONLY),
    "toxic": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_MECHANICS_SAFETY_ONLY),
    "spore": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_MECHANICS_SAFETY_ONLY),
    "sleeppowder": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_MECHANICS_SAFETY_ONLY),
    "charm": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_MECHANICS_SAFETY_ONLY),
    "scaryface": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_MECHANICS_SAFETY_ONLY),
    "screech": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_MECHANICS_SAFETY_ONLY),
    "faketears": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_MECHANICS_SAFETY_ONLY),
    "metalsound": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_MECHANICS_SAFETY_ONLY),
    "gastroacid": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_MECHANICS_SAFETY_ONLY),
    "skillswap": (GROUP_FIELD_SIDE_CONTROL, STATUS_MECHANICS_SAFETY_ONLY),
    # Protection / defensive support
    "protect": (GROUP_PROTECTION_DEFENSIVE_SUPPORT, STATUS_HANDLED_DEFAULT),
    "detect": (GROUP_PROTECTION_DEFENSIVE_SUPPORT, STATUS_HANDLED_DEFAULT),
    "spikyshield": (GROUP_PROTECTION_DEFENSIVE_SUPPORT, STATUS_HANDLED_DEFAULT),
    "kingsshield": (GROUP_PROTECTION_DEFENSIVE_SUPPORT, STATUS_HANDLED_DEFAULT),
    "banefulbunker": (GROUP_PROTECTION_DEFENSIVE_SUPPORT, STATUS_HANDLED_DEFAULT),
    "wideguard": (GROUP_PROTECTION_DEFENSIVE_SUPPORT, STATUS_WIRED_DEFAULT_OFF),
    "quickguard": (GROUP_PROTECTION_DEFENSIVE_SUPPORT, STATUS_MECHANICS_SAFETY_ONLY),
    "craftyshield": (GROUP_PROTECTION_DEFENSIVE_SUPPORT, STATUS_MECHANICS_SAFETY_ONLY),
    "followme": (GROUP_PROTECTION_DEFENSIVE_SUPPORT, STATUS_UNKNOWN_NEEDS_PROBE),
    "ragepowder": (GROUP_PROTECTION_DEFENSIVE_SUPPORT, STATUS_UNKNOWN_NEEDS_PROBE),
    "lightscreen": (GROUP_FIELD_SIDE_CONTROL, STATUS_UNKNOWN_NEEDS_PROBE),
    "reflect": (GROUP_FIELD_SIDE_CONTROL, STATUS_UNKNOWN_NEEDS_PROBE),
    # Speed / turn control
    "tailwind": (GROUP_SPEED_TURN_CONTROL, STATUS_WIRED_DEFAULT_OFF),
    "trickroom": (GROUP_SPEED_TURN_CONTROL, STATUS_WIRED_DEFAULT_OFF),
    "icywind": (GROUP_SPEED_TURN_CONTROL, STATUS_UNKNOWN_NEEDS_PROBE),
    "electroweb": (GROUP_SPEED_TURN_CONTROL, STATUS_UNKNOWN_NEEDS_PROBE),
    # Weather / Terrain (setter moves)
    "raindance": (GROUP_WEATHER_TERRAIN, STATUS_SCORING_GAP_CONFIRMED),
    "sunnyday": (GROUP_WEATHER_TERRAIN, STATUS_SCORING_GAP_CONFIRMED),
    "sandstorm": (GROUP_WEATHER_TERRAIN, STATUS_SCORING_GAP_CONFIRMED),
    "hail": (GROUP_WEATHER_TERRAIN, STATUS_SCORING_GAP_CONFIRMED),
    "snowscape": (GROUP_WEATHER_TERRAIN, STATUS_SCORING_GAP_CONFIRMED),
    "electricterrain": (GROUP_WEATHER_TERRAIN, STATUS_SCORING_GAP_CONFIRMED),
    "grassyterrain": (GROUP_WEATHER_TERRAIN, STATUS_SCORING_GAP_CONFIRMED),
    "mistyterrain": (GROUP_WEATHER_TERRAIN, STATUS_SCORING_GAP_CONFIRMED),
    "psychicterrain": (GROUP_WEATHER_TERRAIN, STATUS_SCORING_GAP_CONFIRMED),
    # Field / side control
    "mist": (GROUP_FIELD_SIDE_CONTROL, STATUS_UNKNOWN_NEEDS_PROBE),
    "safeguard": (GROUP_FIELD_SIDE_CONTROL, STATUS_UNKNOWN_NEEDS_PROBE),
    "stealthrock": (GROUP_FIELD_SIDE_CONTROL, STATUS_UNKNOWN_NEEDS_PROBE),
    "spikes": (GROUP_FIELD_SIDE_CONTROL, STATUS_UNKNOWN_NEEDS_PROBE),
    "toxicspikes": (GROUP_FIELD_SIDE_CONTROL, STATUS_UNKNOWN_NEEDS_PROBE),
    "haze": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_MECHANICS_SAFETY_ONLY),
    "clearsmog": (GROUP_ANTI_SETUP_DISRUPTION, STATUS_MECHANICS_SAFETY_ONLY),
    # Setup / stat-boost moves (Phase RL-DATA-3c). These
    # are real support moves that boost the user's
    # stats. The bot's scoring has not adopted a positive
    # strategy for these yet (the SUPPORT-AUDIT-1
    # inventory does not include them in the original
    # 52-move list). The classification is
    # ``no_positive_strategy``: the move is recognized
    # as a support move, but the bot does not yet
    # score it positively. ``unknown_support_move_detected``
    # is ``False`` so Gate 17 does not warn.
    "quiverdance": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "swordsdance": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "nastyplot": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "dragondance": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "calmmind": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "bulkup": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "irondefense": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "amnesia": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "agility": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "shellsmash": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "bellydrum": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "growth": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "workup": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "curse": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "cosmicpower": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "coil": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "honeclaws": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "autotomize": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "rockpolish": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "shiftgear": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "tailglow": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "geomancy": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "victorydance": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "clangeroussoul": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    "tidyup": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
    # Substitute is a pseudo-setup move (it gives the
    # user a free-switch / damage blocker). The
    # original SUPPORT-AUDIT-1 did not include it;
    # the bot can safely attempt it as a setup move.
    "substitute": (GROUP_SETUP_STAT_BOOST, STATUS_NO_POSITIVE_STRATEGY),
}

# Damaging moves that LOOK like support (e.g., damage with status
# side-effect). These are NOT classified as support; the function
# returns is_support_move=False for them.
_DAMAGE_LIKE_NOT_SUPPORT = frozenset({
    "hurricane", "thunderbolt", "thunder", "icebeam", "psychic",
    "psyshock", "focusblast", "hydropump", "fireblast", "shadowball",
    "energyball", "darkpulse", "stoneedge", "earthpower", "flashcannon",
    "ironhead", "knockoff", "uturn", "voltswitch", "rapidspin",
    "heatwave", "makeitrain", "dracometeor", "sludgewave", "leafstorm",
    "moonblast", "dracometeor", "earthquake", "rockslide", "bugbuzz",
    "fakeout", "icepunch", "thunderpunch", "firepunch", "crunch",
    "drainpunch", "zenheadbutt", "woodhammer", "leafblade", "powerwhip",
    "stoneaxe", "poltergeist", "nightslash", "drillrun", "ironhead",
    "meteormash", "extremespeed", "uturn",
})

# Per-status opt-in flag (if any). None = no flag (always-on safety
# or audit-only).
_OPT_IN_FLAGS_BY_STATUS: Dict[str, Optional[str]] = {
    STATUS_HANDLED_DEFAULT: None,
    STATUS_HANDLED_OPT_IN: "opt_in_required",
    STATUS_WIRED_DEFAULT_OFF: "wired_default_off",
    STATUS_BLOCKED_NOT_PROMOTED: "blocked_not_promoted",
    STATUS_AUDIT_ONLY: None,
    STATUS_SCORING_GAP_CONFIRMED: "scoring_gap",
    STATUS_NO_POSITIVE_STRATEGY: None,
    STATUS_MECHANICS_SAFETY_ONLY: None,
    STATUS_FUTURE_WORK: "future_work",
    STATUS_UNKNOWN_NEEDS_PROBE: None,
}

# Per-status default_enabled flag. None = unknown / not applicable.
_DEFAULT_ENABLED_BY_STATUS: Dict[str, Optional[bool]] = {
    STATUS_HANDLED_DEFAULT: True,
    STATUS_HANDLED_OPT_IN: False,
    STATUS_WIRED_DEFAULT_OFF: False,
    STATUS_BLOCKED_NOT_PROMOTED: False,
    STATUS_AUDIT_ONLY: True,
    STATUS_SCORING_GAP_CONFIRMED: True,
    STATUS_NO_POSITIVE_STRATEGY: True,
    STATUS_MECHANICS_SAFETY_ONLY: True,
    STATUS_FUTURE_WORK: False,
    STATUS_UNKNOWN_NEEDS_PROBE: None,
}

# Per-status safety_only and positive_strategy_known.
# safety_only: the bot can block bad use but cannot choose good use.
# positive_strategy_known: the bot has a positive scoring bonus for
# this category.
_SAFETY_ONLY_BY_STATUS: Dict[str, bool] = {
    STATUS_HANDLED_DEFAULT: False,
    STATUS_HANDLED_OPT_IN: False,
    STATUS_WIRED_DEFAULT_OFF: False,
    STATUS_BLOCKED_NOT_PROMOTED: False,
    STATUS_AUDIT_ONLY: False,
    STATUS_SCORING_GAP_CONFIRMED: True,
    STATUS_NO_POSITIVE_STRATEGY: True,
    STATUS_MECHANICS_SAFETY_ONLY: True,
    STATUS_FUTURE_WORK: True,
    STATUS_UNKNOWN_NEEDS_PROBE: True,
}
_POSITIVE_STRATEGY_BY_STATUS: Dict[str, bool] = {
    STATUS_HANDLED_DEFAULT: True,
    STATUS_HANDLED_OPT_IN: True,
    STATUS_WIRED_DEFAULT_OFF: True,
    STATUS_BLOCKED_NOT_PROMOTED: True,
    STATUS_AUDIT_ONLY: False,
    STATUS_SCORING_GAP_CONFIRMED: False,
    STATUS_NO_POSITIVE_STRATEGY: False,
    STATUS_MECHANICS_SAFETY_ONLY: False,
    STATUS_FUTURE_WORK: False,
    STATUS_UNKNOWN_NEEDS_PROBE: False,
}


def _normalize_move_id(move_id: Any) -> str:
    """Normalize a move id to a lowercased, no-space string."""
    if move_id is None:
        return ""
    s = str(move_id)
    s = s.lower().replace(" ", "").replace("-", "").replace("_", "")
    s = s.replace("'", "")
    return s


def classify_support_move_for_dataset(
    move_id: Any,
    base_power: Optional[int] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Classify a move for the RL-DATA-1 v1.1 schema.

    Returns a dict with the v1.1 per-candidate support-move fields:
        - support_group: str
        - support_status_from_audit: str
        - is_support_move: bool
        - safety_only: bool
        - positive_strategy_known: bool
        - opt_in_flag_required: str | None
        - default_enabled: bool | None
        - unknown_support_move_detected: bool

    The function is for dataset-instrumentation only; it does not
    change scoring, behavior, or selected actions.

    Logic:
        1. Normalize the move id.
        2. If the move is in the known support-move inventory,
           return the (group, status) from the inventory plus
           opt_in_flag_required / default_enabled / safety_only /
           positive_strategy_known derived from the status.
        3. If the move is a damaging move (base_power > 0 or
           category == "physical" / "special"), it is not a support
           move. is_support_move = False, group = None, etc.
        4. Otherwise, tag it as unknown_needs_probe. The detector
           returns unknown_support_move_detected = True. The bot's
           selected action is NOT changed by this tag.
    """
    norm = _normalize_move_id(move_id)

    # Damaging moves: not support.
    if (
        (base_power is not None and base_power > 0)
        or (category is not None and str(category).lower() in ("physical", "special"))
    ):
        return {
            "support_group": None,
            "support_status_from_audit": None,
            "is_support_move": False,
            "safety_only": False,
            "positive_strategy_known": False,
            "opt_in_flag_required": None,
            "default_enabled": None,
            "unknown_support_move_detected": False,
        }

    # Known support-move inventory.
    if norm in _KNOWN_SUPPORT_MOVE_INVENTORY:
        group, status = _KNOWN_SUPPORT_MOVE_INVENTORY[norm]
        return {
            "support_group": group,
            "support_status_from_audit": status,
            "is_support_move": True,
            "safety_only": _SAFETY_ONLY_BY_STATUS[status],
            "positive_strategy_known": _POSITIVE_STRATEGY_BY_STATUS[status],
            "opt_in_flag_required": _OPT_IN_FLAGS_BY_STATUS[status],
            "default_enabled": _DEFAULT_ENABLED_BY_STATUS[status],
            "unknown_support_move_detected": False,
        }

    # Unknown: tag as unknown_needs_probe.
    # This is a non-damaging move that is not in the known support
    # inventory. Examples: a Gen X new support move, a custom move,
    # a future DLC move.
    return {
        "support_group": GROUP_UNKNOWN_NEEDS_PROBE,
        "support_status_from_audit": STATUS_UNKNOWN_NEEDS_PROBE,
        "is_support_move": True,
        "safety_only": _SAFETY_ONLY_BY_STATUS[STATUS_UNKNOWN_NEEDS_PROBE],
        "positive_strategy_known": _POSITIVE_STRATEGY_BY_STATUS[STATUS_UNKNOWN_NEEDS_PROBE],
        "opt_in_flag_required": _OPT_IN_FLAGS_BY_STATUS[STATUS_UNKNOWN_NEEDS_PROBE],
        "default_enabled": _DEFAULT_ENABLED_BY_STATUS[STATUS_UNKNOWN_NEEDS_PROBE],
        "unknown_support_move_detected": True,
    }


def aggregate_support_distribution(
    classifications: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Aggregate support-group counts from a list of v1.1
    per-candidate classifications.

    Returns a dict mapping support_group -> count. The dict
    always includes all 9 groups (zero counts for missing
    groups) so the action-distribution gate can verify coverage.
    """
    out = {g: 0 for g in ALL_SUPPORT_GROUPS}
    for c in classifications:
        g = c.get("support_group")
        if g in out:
            out[g] += 1
    return out
