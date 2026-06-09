#!/usr/bin/env python3
"""
ability_rules.py

Contains safe helper functions and ability groups for Doubles Damage-Aware Player.
Helpers return (value, reason) tuples for logging and debugging.
All functions use getattr and try/except to avoid any runtime crashes.
"""
import logging

logger = logging.getLogger(__name__)

# Core Ability Groups
IMMUNITY_ABILITIES = {
    "levitate", "flashfire", "waterabsorb", "stormdrain", "voltabsorb",
    "lightningrod", "sapsipper", "motordrive", "dryskin", "wonderguard",
    "soundproof", "bulletproof", "overcoat", "magicbounce", "goodasgold"
}

ALLY_SAFETY_ABILITIES = {
    "telepathy", "levitate", "waterabsorb", "stormdrain", "dryskin",
    "voltabsorb", "lightningrod", "motordrive", "flashfire", "sapsipper"
}

REDIRECTION_ABILITIES = {
    "stormdrain", "lightningrod"
}

DAMAGE_MODIFIERS = {
    "thickfat", "filter", "solidrock", "fluffy", "heatproof", "multiscale",
    "shadowshield", "tintedlens", "adaptability", "technician", "sheerforce",
    "hustle", "guts", "hugepower", "purepower"
}

STATUS_IMMUNITY_ABILITIES = {
    "magicbounce", "goodasgold", "soundproof", "overcoat"
}


def normalize_ability(ability) -> str:
    """Normalizes any string or ability name to a standardized lowercase ID."""
    if not ability:
        return ""
    if not isinstance(ability, str):
        try:
            ability = str(ability)
        except Exception:
            return ""
    return "".join(c.lower() for c in ability if c.isalnum())


def get_known_ability(pokemon) -> str:
    """Safely retrieves the active/known normalized ability of a Pokemon."""
    if not pokemon:
        return ""
    try:
        ab = getattr(pokemon, "ability", None)
        if ab:
            return normalize_ability(ab)
    except Exception:
        pass
    return ""


def get_move_type(move) -> str:
    """Safely retrieves the normalized lowercase type of a move."""
    if not move:
        return ""
    try:
        mtype = getattr(move, "type", None)
        if mtype:
            if isinstance(mtype, str):
                return mtype.lower()
            val = getattr(mtype, "name", None)
            if val:
                return str(val).lower()
            return str(mtype).lower()
    except Exception:
        pass
    return ""


def ability_blocks_move(target, move, attacker=None, battle=None) -> tuple[bool, str]:
    """
    Checks if target's ability completely blocks/immunizes it from the move.
    Returns (blocks_bool, reason_string).
    """
    if not target or not move:
        return False, ""
    try:
        target_ability = get_known_ability(target)
        if not target_ability:
            return False, ""

        # Attacker abilities that bypass target immunities (Mold Breaker, Teravolt, Turboblaze)
        if attacker:
            attacker_ability = get_known_ability(attacker)
            if attacker_ability in ("moldbreaker", "teravolt", "turboblaze"):
                # Good as Gold is NOT bypassed by Mold Breaker. Wonder Guard is also bypassed.
                if target_ability != "goodasgold":
                    return False, f"target's {target_ability} bypassed by attacker's {attacker_ability}"

        move_type = get_move_type(move)
        flags = getattr(move, "flags", set())

        # Levitate: Ground immunity (except Thousand Arrows)
        if target_ability == "levitate" and move_type == "ground":
            move_id = getattr(move, "id", "")
            if move_id == "thousandarrows":
                return False, "Thousand Arrows bypasses Levitate"
            return True, f"Levitate blocks Ground-type move {move.id}"

        # Flash Fire / Well-Baked Body: Fire immunity
        if target_ability in ("flashfire", "wellbakedbody") and move_type == "fire":
            return True, f"{target_ability} blocks Fire-type move {move.id}"

        # Water Absorb / Storm Drain / Dry Skin: Water immunity
        if target_ability in ("waterabsorb", "stormdrain", "dryskin") and move_type == "water":
            return True, f"{target_ability} blocks Water-type move {move.id}"

        # Volt Absorb / Lightning Rod / Motor Drive: Electric immunity
        if target_ability in ("voltabsorb", "lightningrod", "motordrive") and move_type == "electric":
            return True, f"{target_ability} blocks Electric-type move {move.id}"

        # Sap Sipper: Grass immunity
        if target_ability == "sapsipper" and move_type == "grass":
            return True, f"Sap Sipper blocks Grass-type move {move.id}"

        # Soundproof: sound move immunity
        if target_ability == "soundproof" and "sound" in flags:
            return True, f"Soundproof blocks sound move {move.id}"

        # Bulletproof: ball/bomb immunity
        if target_ability == "bulletproof" and "bullet" in flags:
            return True, f"Bulletproof blocks ball/bomb move {move.id}"

        # Overcoat: powder move immunity
        if target_ability == "overcoat" and "powder" in flags:
            return True, f"Overcoat blocks powder move {move.id}"

        # Wonder Guard: immune to all non-super-effective damage (status moves still hit)
        if target_ability == "wonderguard":
            category = getattr(move, "category", None)
            if category:
                cat_str = str(category.name).lower() if hasattr(category, "name") else str(category).lower()
                if cat_str in ("physical", "special"):
                    mult = 1.0
                    try:
                        mult = target.damage_multiplier(move)
                    except Exception:
                        pass
                    if mult <= 1.0:
                        return True, f"Wonder Guard blocks non-super-effective move {move.id} (multiplier: {mult})"
    except Exception as e:
        logger.error(f"Error in ability_blocks_move: {e}")
    return False, ""


def ability_absorbs_or_benefits(target, move) -> tuple[bool, str]:
    """Checks if the target's ability absorbs or directly benefits from the move."""
    if not target or not move:
        return False, ""
    try:
        target_ability = get_known_ability(target)
        if not target_ability:
            return False, ""

        move_type = get_move_type(move)

        if target_ability in ("waterabsorb", "stormdrain", "dryskin") and move_type == "water":
            return True, f"Water-type move {move.id} is absorbed/boosts target with {target_ability}"

        if target_ability in ("voltabsorb", "lightningrod", "motordrive") and move_type == "electric":
            return True, f"Electric-type move {move.id} is absorbed/boosts target with {target_ability}"

        if target_ability == "sapsipper" and move_type == "grass":
            return True, f"Grass-type move {move.id} is absorbed/boosts target with Sap Sipper"

        if target_ability in ("flashfire", "wellbakedbody") and move_type == "fire":
            return True, f"Fire-type move {move.id} is absorbed/boosts target with {target_ability}"
    except Exception as e:
        logger.error(f"Error in ability_absorbs_or_benefits: {e}")
    return False, ""


def ability_redirects_move(active_pokemon, move) -> tuple[bool, str]:
    """
    Checks if an active pokemon's ability (like Storm Drain or Lightning Rod)
    redirects this move. Only single-target moves are redirectable.
    """
    if not active_pokemon or not move:
        return False, ""
    try:
        # Check target type to filter out spread moves
        move_target = getattr(move, "target", None)
        if move_target:
            target_str = str(move_target.name).lower() if hasattr(move_target, "name") else str(move_target).lower()
            if target_str in ("alladjacent", "alladjacentfoes", "adjacentally", "adjacentallyorfoes"):
                return False, ""

        ability = get_known_ability(active_pokemon)
        if not ability:
            return False, ""

        move_type = get_move_type(move)
        if ability == "stormdrain" and move_type == "water":
            return True, f"Water move redirected to {active_pokemon.species} by Storm Drain"
        if ability == "lightningrod" and move_type == "electric":
            return True, f"Electric move redirected to {active_pokemon.species} by Lightning Rod"
    except Exception as e:
        logger.error(f"Error in ability_redirects_move: {e}")
    return False, ""


def ally_is_safe_from_move(ally, move) -> tuple[bool, str]:
    """Checks if an ally is completely safe from the move."""
    if not ally or not move:
        return False, ""
    try:
        ally_ability = get_known_ability(ally)
        if not ally_ability:
            return False, ""

        if ally_ability == "telepathy":
            return True, f"Telepathy protects ally {ally.species} from allied spread move {move.id}"

        move_type = get_move_type(move)

        if ally_ability == "levitate" and move_type == "ground":
            move_id = getattr(move, "id", "")
            if move_id != "thousandarrows":
                return True, f"Levitate protects ally {ally.species} from allied Ground move {move.id}"

        if ally_ability in ("waterabsorb", "stormdrain", "dryskin") and move_type == "water":
            return True, f"{ally_ability} protects ally {ally.species} from allied Water move {move.id}"

        if ally_ability in ("voltabsorb", "lightningrod", "motordrive") and move_type == "electric":
            return True, f"{ally_ability} protects ally {ally.species} from allied Electric move {move.id}"

        if ally_ability == "flashfire" and move_type == "fire":
            return True, f"Flash Fire protects ally {ally.species} from allied Fire move {move.id}"

        if ally_ability == "sapsipper" and move_type == "grass":
            return True, f"Sap Sipper protects ally {ally.species} from allied Grass move {move.id}"
    except Exception as e:
        logger.error(f"Error in ally_is_safe_from_move: {e}")
    return False, ""


def ability_damage_multiplier(target, move, attacker=None) -> tuple[float, str]:
    """Returns the defensive damage multiplier and reason based on target's ability."""
    multiplier = 1.0
    if not target or not move:
        return multiplier, ""
    try:
        if attacker:
            attacker_ability = get_known_ability(attacker)
            if attacker_ability in ("moldbreaker", "teravolt", "turboblaze"):
                # Defensive damage modifiers ignored by Mold Breaker
                return multiplier, ""

        target_ability = get_known_ability(target)
        if not target_ability:
            return multiplier, ""

        move_type = get_move_type(move)

        if target_ability == "thickfat" and move_type in ("fire", "ice"):
            return 0.5, f"Thick Fat halves Fire/Ice damage vs {target.species}"

        if target_ability == "heatproof" and move_type == "fire":
            return 0.5, f"Heatproof halves Fire damage vs {target.species}"

        if target_ability in ("filter", "solidrock"):
            try:
                if target.damage_multiplier(move) > 1.0:
                    return 0.75, f"{target_ability} reduces super-effective damage by 25% vs {target.species}"
            except Exception:
                pass

        if target_ability == "fluffy":
            flags = getattr(move, "flags", set())
            is_contact = "contact" in flags
            mult = 1.0
            reasons = []
            if move_type == "fire":
                mult *= 2.0
                reasons.append("Fire moves deal 2.0x")
            if is_contact:
                mult *= 0.5
                reasons.append("contact moves deal 0.5x")
            if mult != 1.0:
                return mult, f"Fluffy modified damage ({', '.join(reasons)}) vs {target.species}"

        if target_ability in ("multiscale", "shadowshield"):
            current_hp = getattr(target, "current_hp", None)
            max_hp = getattr(target, "max_hp", None)
            fraction = getattr(target, "current_hp_fraction", 1.0)
            if (current_hp is not None and max_hp is not None and current_hp == max_hp) or (fraction >= 0.99):
                return 0.5, f"{target_ability} halves damage at full HP vs {target.species}"
    except Exception as e:
        logger.error(f"Error in ability_damage_multiplier: {e}")
    return multiplier, ""


def attacker_ability_damage_multiplier(attacker, move, target=None) -> tuple[float, str]:
    """Returns the offensive damage multiplier and reason based on attacker's ability."""
    multiplier = 1.0
    if not attacker or not move:
        return multiplier, ""
    try:
        ability = get_known_ability(attacker)
        if not ability:
            return multiplier, ""

        category = getattr(move, "category", None)
        cat_str = str(category.name).lower() if hasattr(category, "name") else str(category).lower()
        is_physical = (cat_str == "physical")

        if ability in ("hugepower", "purepower") and is_physical:
            return 2.0, f"{ability} doubles Attack stat"

        if ability == "hustle" and is_physical:
            return 1.5, "Hustle boosts physical power by 1.5x"

        if ability == "guts" and is_physical:
            status = getattr(attacker, "status", None)
            if status:
                status_str = str(status.name).lower() if hasattr(status, "name") else str(status).lower()
                if status_str not in ("none", "null", ""):
                    return 1.5, "Guts boosts Attack by 1.5x when statused"

        if ability == "adaptability":
            move_type = get_move_type(move)
            attacker_types = []
            for attr in ("type_1", "type_2"):
                t = getattr(attacker, attr, None)
                if t:
                    t_str = str(t.name).lower() if hasattr(t, "name") else str(t).lower()
                    attacker_types.append(t_str)
            if move_type in attacker_types:
                return 1.33, "Adaptability boosts STAB modifier (from 1.5x to 2.0x)"

        if ability == "technician":
            base_power = getattr(move, "base_power", 0)
            try:
                bp = float(base_power)
            except Exception:
                bp = 0.0
            if 0.0 < bp <= 60.0:
                return 1.5, f"Technician boosts weak move {move.id} (<=60 BP) by 1.5x"

        if ability == "sheerforce":
            entry = getattr(move, "entry", {})
            if entry and (entry.get("secondaries") or entry.get("secondary")):
                return 1.3, "Sheer Force boosts moves with secondary effects by 1.3x"

        if ability == "tintedlens" and target is not None:
            try:
                if target.damage_multiplier(move) < 1.0:
                    return 2.0, "Tinted Lens doubles damage of resisted moves"
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Error in attacker_ability_damage_multiplier: {e}")
    return multiplier, ""


def should_avoid_status_into_ability(target, move) -> tuple[bool, str]:
    """Checks if a status move should be avoided due to the target's ability blocking or reflecting it."""
    if not target or not move:
        return False, ""
    try:
        category = getattr(move, "category", None)
        cat_str = str(category.name).lower() if hasattr(category, "name") else str(category).lower()
        if cat_str != "status":
            return False, ""

        target_ability = get_known_ability(target)
        if not target_ability:
            return False, ""

        if target_ability == "goodasgold":
            return True, f"Good as Gold blocks status moves vs {target.species}"

        if target_ability == "magicbounce":
            return True, f"Magic Bounce reflects status moves vs {target.species}"

        flags = getattr(move, "flags", set())

        if target_ability == "soundproof" and "sound" in flags:
            return True, f"Soundproof blocks sound-based status move {move.id} vs {target.species}"

        if target_ability == "overcoat" and "powder" in flags:
            return True, f"Overcoat blocks powder-based status move {move.id} vs {target.species}"
    except Exception as e:
        logger.error(f"Error in should_avoid_status_into_ability: {e}")
    return False, ""
