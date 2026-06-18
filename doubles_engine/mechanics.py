"""doubles_engine.mechanics: mechanics wrapper helpers.

ponytail: pure or near-pure mechanics helpers
extracted from ``bot_doubles_damage_aware.py``
(Phase Ponytail Refactor Step 2b). Preserves
behavior bit-for-bit.

ALL bot imports are function-local (lazy) to
break the known cycle. The cycle would otherwise
be:
    bot_doubles_damage_aware -> doubles_engine.mechanics
        -> bot_doubles_damage_aware
caused by mechanics helpers needing primitives
that are defined in the bot. Top-level imports
from the bot would be a problem because when
mechanics is loaded BY the bot's shim, the bot
is partially loaded and the function definitions
in mechanics haven't run yet, so re-importing
from mechanics back into the bot fails with
"partially initialized module" error.

Lazy imports inside each function body defer
the import to call time, when the bot is fully
loaded and the function names are available.

The 6 mechanics wrappers moved here:
- resolve_known_ability
- ability_hard_blocks_move
- direct_known_absorb_blocks_move
- ability_redirects_single_target_move
- ally_ability_makes_safe
- _ability_block_enabled
"""
from typing import Any, Dict, List, Optional, Tuple


# ponytail: NO module-level imports from
# ``bot_doubles_damage_aware``. All bot imports
# are function-local (lazy) to break the known
# cycle. See module docstring for details.


def resolve_known_ability(
    pokemon, battle=None, config=None
) -> dict:
    """Resolve the known ability of a Pokemon.

    Returns:
        dict with keys: ability, source, possible_abilities, is_deterministic,
        is_currently_suppressed, suppression_reason
    """
    # ponytail: lazy import. Early-defined bot
    # primitives (lines 959-1634) are available
    # by the time this function is called.
    from bot_doubles_damage_aware import (  # noqa: E402
        _normalize_ability_name,
        _pokemon_is_on_our_team,
        get_known_ability,
        normalize_possible_abilities,
    )
    result = {
        "ability": None,
        "source": "unknown",
        "possible_abilities": [],
        "is_deterministic": False,
        "is_currently_suppressed": False,
        "suppression_reason": "",
    }

    if not pokemon:
        return result

    # 1. Check if this is our own team's Pokemon (always known)
    if _pokemon_is_on_our_team(pokemon, battle):
        result["ability"] = _normalize_ability_name(
            getattr(pokemon, "ability", None)
        )
        result["source"] = "our_team_known"
        result["is_deterministic"] = True
        return result

    # 2. Check explicit protocol reveal
    revealed = get_known_ability(pokemon, battle)
    if revealed:
        result["ability"] = revealed
        result["source"] = "protocol_revealed"
        result["is_deterministic"] = True
        return result

    # 3. Check for temporary ability changes (Trace, Skill Swap, etc.)
    temp_ability = getattr(pokemon, "temporary_ability", None)
    if temp_ability:
        norm = _normalize_ability_name(temp_ability)
        if norm:
            result["ability"] = norm
            result["source"] = "temporary_changed"
            result["is_deterministic"] = True
            return result

    # 4. Check for Gastro Acid suppression
    # (would be tracked as a status condition)
    status = getattr(pokemon, "status", None)
    if status and _normalize_ability_name(str(status)) == "gastroacid":
        result["is_currently_suppressed"] = True
        result["suppression_reason"] = "gastro_acid"

    # 5. Check for Neutralizing Gas on field
    if battle:
        fields = getattr(battle, "fields", {}) or {}
        for field in fields:
            fname = (
                getattr(field, "name", str(field))
                if hasattr(field, "name")
                else str(field)
            )
            if _normalize_ability_name(fname) == "neutralizinggas":
                result["is_currently_suppressed"] = True
                result["suppression_reason"] = "neutralizing_gas"
                break

    # 6. Deterministic singleton deduction (only when flag enabled)
    allow_singleton = False
    if config:
        allow_singleton = getattr(
            config,
            "ability_hard_safety_allow_singleton_deduction",
            False,
        )

    if allow_singleton and not result["is_currently_suppressed"]:
        try:
            possible = getattr(pokemon, "possible_abilities", None)
            if possible is not None:
                norm_possible = normalize_possible_abilities(
                    possible
                )
                result["possible_abilities"] = norm_possible

                # Check if exactly one distinct ability
                if len(norm_possible) == 1:
                    the_ability = norm_possible[0]
                    current_ability = _normalize_ability_name(
                        getattr(pokemon, "ability", None)
                    )

                    # pokemon.ability should be empty or match the singleton
                    if not current_ability or current_ability == the_ability:
                        result["ability"] = the_ability
                        result["source"] = "deterministic_singleton"
                        result["is_deterministic"] = True
        except Exception:
            pass

    return result


def ability_hard_blocks_move(
    move, attacker, target, battle=None, config=None
) -> tuple[bool, str]:
    # ponytail: ALL imports are lazy to break the
    # known cycle. ``resolve_known_ability`` is
    # in this same module so it's a local reference.
    from bot_doubles_damage_aware import (  # noqa: E402
        _extract_ability,
        _extract_move_id,
        _extract_target_types,
        attacker_ignores_target_ability,
        get_effective_move_type,
    )
    import doubles_mechanics as _dm
    if not target or not move:
        return False, ""
    try:
        # Use resolve_known_ability to get ability
        # (supports singleton deduction).
        resolution = resolve_known_ability(target, battle, config)
        t_ability = resolution["ability"]
        if not t_ability:
            return False, ""

        if attacker_ignores_target_ability(attacker, battle):
            return False, ""

        move_id = _extract_move_id(move)
        m_type = get_effective_move_type(move, attacker, battle)

        attacker_ability = _extract_ability(attacker)

        # Grounded state is owned by the shared module
        # so the bot wrapper does not duplicate the
        # rules for Thousand Arrows, Gravity, Smack
        # Down, and Ingrain.
        grounded = _dm.resolve_extra_grounded(
            move, target, battle=battle, move_id=move_id,
        )

        result = _dm.resolve_explicit_ability_interaction(
            move, attacker, target,
            target_ability=t_ability,
            attacker_ability=attacker_ability,
            move_id=move_id,
            move_type=m_type,
            extra_grounded=grounded,
            defender_types=_extract_target_types(target),
        )
        if result.is_immune and not result.bypassed:
            return True, result.reason
    except Exception:
        return False, ""
    return False, ""


def direct_known_absorb_blocks_move(
    move, attacker, target, battle=None, order=None
) -> tuple[bool, str]:
    # ponytail: lazy imports. ``ability_hard_blocks_move``
    # is in this same module.
    from bot_doubles_damage_aware import (  # noqa: E402
        get_known_ability,
        is_opponent_spread_move,
    )
    if not move or not target:
        return False, ""
    try:
        # damaging move only
        base_power = getattr(move, "base_power", 0)
        if base_power <= 0:
            return False, ""

        # Do not call is_opponent_spread_move(move) without
        # order context. Gate direct safety using order
        # context.
        if order is not None and is_opponent_spread_move(
            move, order
        ):
            return False, ""

        # ALLOWLIST: protocol-revealed-only direct absorb
        # check
        blocks, reason = ability_hard_blocks_move(
            move, attacker, target, battle, config=None
        )
        if blocks:
            t_ability = get_known_ability(target, battle)
            if t_ability in (
                "waterabsorb",
                "stormdrain",
                "dryskin",
                "voltabsorb",
                "motordrive",
                "lightningrod",
                "flashfire",
                "wellbakedbody",
                "sapsipper",
            ):
                return True, reason
    except Exception:
        pass
    return False, ""


def ability_redirects_single_target_move(
    move, intended_target, opponent_targets, attacker=None, battle=None
) -> tuple[bool, str]:
    # ponytail: lazy imports.
    from bot_doubles_damage_aware import (  # noqa: E402
        attacker_ignores_target_ability,
        get_known_ability,
        is_opponent_spread_move,
    )
    if not move or not intended_target:
        return False, ""
    try:
        if is_opponent_spread_move(move) or attacker_ignores_target_ability(
            attacker, battle
        ):
            return False, ""
        move_id = getattr(move, "id", "").lower()
        m_type = ""
        m_type_obj = getattr(move, "type", None)
        if m_type_obj:
            m_type = (
                m_type_obj.name.upper()
                if hasattr(m_type_obj, "name")
                else str(m_type_obj).upper()
            )

        for opp in opponent_targets:
            if opp and opp != intended_target and not getattr(
                opp, "fainted", False
            ):
                opp_ability = get_known_ability(opp, battle)
                if not opp_ability:
                    continue
                if m_type == "WATER" and opp_ability == "stormdrain":
                    return True, "redirected_by_stormdrain"
                if (
                    m_type == "ELECTRIC"
                    and opp_ability == "lightningrod"
                ):
                    return True, "redirected_by_lightningrod"
    except Exception:
        pass
    return False, ""


def ally_ability_makes_safe(
    ally, move, battle=None
) -> tuple[bool, str]:
    # ponytail: lazy imports.
    from bot_doubles_damage_aware import (  # noqa: E402
        get_known_ability,
        is_gravity_active,
    )
    if not ally or not move:
        return False, ""
    try:
        ally_ab = get_known_ability(ally, battle)
        if not ally_ab:
            return False, ""
        if ally_ab == "telepathy":
            return True, "telepathy"

        move_id = getattr(move, "id", "").lower()
        m_type = ""
        m_type_obj = getattr(move, "type", None)
        if m_type_obj:
            m_type = (
                m_type_obj.name.upper()
                if hasattr(m_type_obj, "name")
                else str(m_type_obj).upper()
            )

        if (
            ally_ab == "levitate"
            and m_type == "GROUND"
            and move_id != "thousandarrows"
            and not is_gravity_active(battle)
        ):
            return True, "levitate"
        if ally_ab == "eartheater" and m_type == "GROUND":
            return True, "eartheater"
        if ally_ab in ("waterabsorb", "stormdrain", "dryskin") and m_type == "WATER":
            return True, ally_ab
        if (
            ally_ab in ("voltabsorb", "lightningrod", "motordrive")
            and m_type == "ELECTRIC"
        ):
            return True, ally_ab
        if ally_ab in ("flashfire", "wellbakedbody") and m_type == "FIRE":
            return True, ally_ab
        if ally_ab == "sapsipper" and m_type == "GRASS":
            return True, "sapsipper"
    except Exception:
        pass
    return False, ""


def _ability_block_enabled(config, reason: str) -> bool:
    # ponytail: no bot deps. config-only.
    if not config or not getattr(
        config, "enable_ability_hard_safety_only", False
    ):
        return False
    if reason in (
        "sound_into_soundproof",
        "bullet_into_bulletproof",
        "explosion_into_damp",
    ):
        return False
    absorb_prefixes = (
        "water_into_",
        "electric_into_",
        "fire_into_",
        "grass_into_",
    )
    if reason.startswith(absorb_prefixes):
        return bool(
            getattr(config, "ability_hard_safety_avoid_absorb", True)
        )
    return True
