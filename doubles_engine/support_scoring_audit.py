"""Phase SUPPORT-SCORING-1A — support-move classification
helper.

This is a pure analysis module. It does NOT change
scoring, behavior, or selected actions. It is used
by the audit script and tests to classify support
moves for the SUPPORT-SCORING-1A audit.

Move classification buckets:

* READY_FOR_SCORING_1B
* NEEDS_EARLY_HOOK_LIKE_WT
* NEEDS_TARGET_SEMANTICS_FIRST
* SAFETY_ONLY_NOT_SCORING
* ALREADY_HANDLED
* NOT_OBSERVED
* BLOCKED_RISKY

The classifier is conservative. It does not enable
any default flips. It only categorizes moves for
audit purposes.
"""

from typing import Dict, List, Set


# Support move groups per SUPPORT-AUDIT-1.
# These names match the constants in
# doubles_engine.support_targets.
GROUP_TARGET_SIDE_SAFETY = "target_side_safety"
GROUP_ABILITY_MECHANICS_SAFETY = "ability_mechanics_safety"
GROUP_ANTI_SETUP_DISRUPTION = "anti_setup_disruption"
GROUP_PROTECTION_DEFENSIVE_SUPPORT = (
    "protection_defensive_support"
)
GROUP_SPEED_TURN_CONTROL = "speed_turn_control"
GROUP_WEATHER_TERRAIN = "weather_terrain"
GROUP_HEALING_BUFF_ALLY_SUPPORT = (
    "healing_buff_ally_support"
)
GROUP_FIELD_SIDE_CONTROL = "field_side_control"
GROUP_SETUP_STAT_BOOST = "setup_stat_boost"
GROUP_UNKNOWN_NEEDS_PROBE = "unknown_needs_probe"


# Classification buckets.
READY_FOR_SCORING_1B = "READY_FOR_SCORING_1B"
NEEDS_EARLY_HOOK_LIKE_WT = "NEEDS_EARLY_HOOK_LIKE_WT"
NEEDS_TARGET_SEMANTICS_FIRST = "NEEDS_TARGET_SEMANTICS_FIRST"
SAFETY_ONLY_NOT_SCORING = "SAFETY_ONLY_NOT_SCORING"
ALREADY_HANDLED = "ALREADY_HANDLED"
NOT_OBSERVED = "NOT_OBSERVED"
BLOCKED_RISKY = "BLOCKED_RISKY"


# Per-move conservative classification. This is the
# audit-only map used by SUPPORT-SCORING-1A. It does
# not change any runtime scoring or behavior.
_MOVE_CLASSIFICATION: Dict[str, str] = {
    # Tier 1: priority candidates for SUPPORT-SCORING-1B
    # but may need target semantics work first.
    "tailwind": NEEDS_TARGET_SEMANTICS_FIRST,
    "wideguard": NEEDS_TARGET_SEMANTICS_FIRST,
    "helpinghand": NEEDS_TARGET_SEMANTICS_FIRST,
    # Tier 2: candidate visibility / target-semantics
    # audit only. Complex or safety-first.
    "followme": NEEDS_TARGET_SEMANTICS_FIRST,
    "ragepowder": NEEDS_TARGET_SEMANTICS_FIRST,
    "quickguard": NEEDS_TARGET_SEMANTICS_FIRST,
    "coaching": NEEDS_TARGET_SEMANTICS_FIRST,
    "lifedew": NEEDS_TARGET_SEMANTICS_FIRST,
    "pollenpuff": NEEDS_TARGET_SEMANTICS_FIRST,
    "haze": NEEDS_TARGET_SEMANTICS_FIRST,
    "clearsmog": NEEDS_TARGET_SEMANTICS_FIRST,
    "reflect": NEEDS_TARGET_SEMANTICS_FIRST,
    "lightscreen": NEEDS_TARGET_SEMANTICS_FIRST,
    "auroraveil": NEEDS_TARGET_SEMANTICS_FIRST,
    "icywind": NEEDS_TARGET_SEMANTICS_FIRST,
    "electroweb": NEEDS_TARGET_SEMANTICS_FIRST,
    "snarl": NEEDS_TARGET_SEMANTICS_FIRST,
    # Tier 3: safety-first, not scoring candidates.
    # Already handled by the narrow ally heal hard
    # safety (SUPPORT-SAFETY-ADOPT-1). Must remain
    # safety-first, NOT scoring-first.
    "healpulse": SAFETY_ONLY_NOT_SCORING,
    "floralhealing": SAFETY_ONLY_NOT_SCORING,
    "decorate": SAFETY_ONLY_NOT_SCORING,
    # Tier 4: already handled by Protect, anti-setup
    # disruption, etc. Not scoring candidates.
    "willowisp": ALREADY_HANDLED,
    "thunderwave": ALREADY_HANDLED,
    "spore": ALREADY_HANDLED,
    "taunt": ALREADY_HANDLED,
    "encore": ALREADY_HANDLED,
    "fakeout": ALREADY_HANDLED,
    "protect": ALREADY_HANDLED,
    "detect": ALREADY_HANDLED,
}


def classify_support_move(move_id: str) -> str:
    """Classify a support move for SUPPORT-SCORING-1A
    audit purposes only. Does NOT change any runtime
    behavior. Returns one of the 7 bucket strings.

    Unknown move ids return ``NOT_OBSERVED`` so the
    audit treats them as out-of-scope rather than
    silently mapping to a scoring bucket.
    """
    norm = _norm(move_id)
    if not norm:
        return NOT_OBSERVED
    if norm in _MOVE_CLASSIFICATION:
        return _MOVE_CLASSIFICATION[norm]
    return NOT_OBSERVED


def is_priority_1b_candidate(move_id: str) -> bool:
    """A support move is a SUPPORT-SCORING-1B priority
    candidate if it is classified as either
    ``READY_FOR_SCORING_1B`` or
    ``NEEDS_TARGET_SEMANTICS_FIRST`` (the Tier 1 moves
    audited in this phase).
    """
    cls = classify_support_move(move_id)
    return cls in (READY_FOR_SCORING_1B, NEEDS_TARGET_SEMANTICS_FIRST)


def group_support_move(move_id: str) -> str:
    """Return the SUPPORT-AUDIT-1 group for a move id
    (lower-cased, no spaces / dashes / underscores).
    Falls back to ``GROUP_UNKNOWN_NEEDS_PROBE`` if the
    move is not in the known inventory.
    """
    norm = _norm(move_id)
    inventory = _KNOWN_SUPPORT_INVENTORY_FLAT
    if norm in inventory:
        return inventory[norm]
    return GROUP_UNKNOWN_NEEDS_PROBE


# Flattened subset of the known inventory for quick
# lookups in this audit module. Mirrors the inventory
# in doubles_engine.support_targets.
_KNOWN_SUPPORT_INVENTORY_FLAT: Dict[str, str] = {
    # Target-side safety
    "healpulse": GROUP_HEALING_BUFF_ALLY_SUPPORT,
    "floralhealing": GROUP_HEALING_BUFF_ALLY_SUPPORT,
    "decorate": GROUP_HEALING_BUFF_ALLY_SUPPORT,
    "helpinghand": GROUP_HEALING_BUFF_ALLY_SUPPORT,
    "coaching": GROUP_HEALING_BUFF_ALLY_SUPPORT,
    "howl": GROUP_HEALING_BUFF_ALLY_SUPPORT,
    "lifedew": GROUP_HEALING_BUFF_ALLY_SUPPORT,
    "aromatherapy": GROUP_HEALING_BUFF_ALLY_SUPPORT,
    "healbell": GROUP_HEALING_BUFF_ALLY_SUPPORT,
    "pollenpuff": GROUP_HEALING_BUFF_ALLY_SUPPORT,
    # Anti-setup / disruption
    "taunt": GROUP_ANTI_SETUP_DISRUPTION,
    "encore": GROUP_ANTI_SETUP_DISRUPTION,
    "disable": GROUP_ANTI_SETUP_DISRUPTION,
    "quash": GROUP_ANTI_SETUP_DISRUPTION,
    "torment": GROUP_ANTI_SETUP_DISRUPTION,
    "thunderwave": GROUP_ANTI_SETUP_DISRUPTION,
    "willowisp": GROUP_ANTI_SETUP_DISRUPTION,
    "toxic": GROUP_ANTI_SETUP_DISRUPTION,
    "spore": GROUP_ANTI_SETUP_DISRUPTION,
    "sleeppowder": GROUP_ANTI_SETUP_DISRUPTION,
    "charm": GROUP_ANTI_SETUP_DISRUPTION,
    "scaryface": GROUP_ANTI_SETUP_DISRUPTION,
    "screech": GROUP_ANTI_SETUP_DISRUPTION,
    "faketears": GROUP_ANTI_SETUP_DISRUPTION,
    "metalsound": GROUP_ANTI_SETUP_DISRUPTION,
    "gastroacid": GROUP_ANTI_SETUP_DISRUPTION,
    "skillswap": GROUP_FIELD_SIDE_CONTROL,
    "haze": GROUP_ANTI_SETUP_DISRUPTION,
    "clearsmog": GROUP_ANTI_SETUP_DISRUPTION,
    # Protection / defensive support
    "protect": GROUP_PROTECTION_DEFENSIVE_SUPPORT,
    "detect": GROUP_PROTECTION_DEFENSIVE_SUPPORT,
    "spikyshield": GROUP_PROTECTION_DEFENSIVE_SUPPORT,
    "kingsshield": GROUP_PROTECTION_DEFENSIVE_SUPPORT,
    "banefulbunker": GROUP_PROTECTION_DEFENSIVE_SUPPORT,
    "wideguard": GROUP_PROTECTION_DEFENSIVE_SUPPORT,
    "quickguard": GROUP_PROTECTION_DEFENSIVE_SUPPORT,
    "craftyshield": GROUP_PROTECTION_DEFENSIVE_SUPPORT,
    "followme": GROUP_PROTECTION_DEFENSIVE_SUPPORT,
    "ragepowder": GROUP_PROTECTION_DEFENSIVE_SUPPORT,
    "lightscreen": GROUP_FIELD_SIDE_CONTROL,
    "reflect": GROUP_FIELD_SIDE_CONTROL,
    # Speed / turn control
    "tailwind": GROUP_SPEED_TURN_CONTROL,
    "trickroom": GROUP_SPEED_TURN_CONTROL,
    "icywind": GROUP_SPEED_TURN_CONTROL,
    "electroweb": GROUP_SPEED_TURN_CONTROL,
    # Weather / Terrain (setter moves)
    "raindance": GROUP_WEATHER_TERRAIN,
    "sunnyday": GROUP_WEATHER_TERRAIN,
    "sandstorm": GROUP_WEATHER_TERRAIN,
    "hail": GROUP_WEATHER_TERRAIN,
    "snowscape": GROUP_WEATHER_TERRAIN,
    "electricterrain": GROUP_WEATHER_TERRAIN,
    "grassyterrain": GROUP_WEATHER_TERRAIN,
    "mistyterrain": GROUP_WEATHER_TERRAIN,
    "psychicterrain": GROUP_WEATHER_TERRAIN,
    # Field / side control
    "mist": GROUP_FIELD_SIDE_CONTROL,
    "safeguard": GROUP_FIELD_SIDE_CONTROL,
    "stealthrock": GROUP_FIELD_SIDE_CONTROL,
    "spikes": GROUP_FIELD_SIDE_CONTROL,
    "toxicspikes": GROUP_FIELD_SIDE_CONTROL,
    "snarl": GROUP_FIELD_SIDE_CONTROL,
}


def _norm(move_id: str) -> str:
    if move_id is None:
        return ""
    s = str(move_id)
    return (
        s.lower()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .replace("'", "")
    )
