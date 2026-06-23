"""Phase WT-3 — Weather/Terrain positive scoring helper.

This module implements conservative positive scoring
for Weather / Terrain setter moves in doubles.

The bot currently has a ``SWITCH_SCORING_GAP``: setter
moves are legal in many turns but selected 0% of the
time (per WT-2 audit). WT-3 adds an opt-in positive
bonus for setters when there is clear, observable,
conservative synergy.

The scoring is **conservative**:

* Only applies when the master flag
  ``enable_weather_terrain_positive_scoring`` is True
  (default OFF).
* Only applies to Weather / Terrain setter moves
  (the 9 moves in ``_WT3_SETTER_MOVE_IDS``).
* No bonus if the target weather/terrain is already
  active (redundant setter prevention).
* No bonus if the opponent benefits more than our
  side (opponent-benefit penalty).
* Uses only revealed moves, visible active Pokémon
  types, and known battle state.
* Does NOT infer abilities from species
  (no Swift Swim / Chlorophyll / Sand Rush / Slush
  Rush / Surge abilities).
* Does NOT use Magic Bounce species inference.
* Hard safety still wins over WT-3 bonus (the
  scoring is added on top of the existing base
  score; hard-safety blocks run before this helper).

Bonus magnitudes (chosen conservatively, smaller than
existing opt-in bonuses like
``anti_trick_room_response_bonus=500.0`` and
``setup_intent_speed_setup_bonus=450.0``):

* weather_bonus: 150.0 (per clear synergy)
* terrain_bonus: 120.0 (smaller than weather because
  terrain bonuses are less well-tested in this repo)
* opponent_benefit_penalty: subtract the opponent's
  own_synergy_score from our own_synergy_score
* redundant_setter_penalty: 0.0 (no bonus at all if
  already active)

The module is **pure**: it does not read the bot
config, does not call into the bot engine, does not
open files. It only reads from the ``order``,
``active_idx``, ``battle`` arguments and the
``config`` argument.
"""

from typing import Any, Dict, List, Optional, Tuple

# Weather setter move ids (normalized: lowercase, no
# spaces/dashes/underscores/apostrophes).
RAIN_DANCE = "raindance"
SUNNY_DAY = "sunnyday"
SANDSTORM = "sandstorm"
SNOWSCAPE = "snowscape"
HAIL = "hail"

# Terrain setter move ids
ELECTRIC_TERRAIN = "electricterrain"
GRASSY_TERRAIN = "grassyterrain"
MISTY_TERRAIN = "mistyterrain"
PSYCHIC_TERRAIN = "psychicterrain"

# All WT-3 setter move ids (used by the bot for
# eligibility checks).
WT3_SETTER_MOVE_IDS = frozenset({
    RAIN_DANCE, SUNNY_DAY, SANDSTORM, SNOWSCAPE, HAIL,
    ELECTRIC_TERRAIN, GRASSY_TERRAIN, MISTY_TERRAIN,
    PSYCHIC_TERRAIN,
})

# Weather moves (subset of WT3_SETTER_MOVE_IDS).
WEATHER_SETTER_IDS = frozenset({
    RAIN_DANCE, SUNNY_DAY, SANDSTORM, SNOWSCAPE, HAIL,
})

# Terrain moves (subset of WT3_SETTER_MOVE_IDS).
TERRAIN_SETTER_IDS = frozenset({
    ELECTRIC_TERRAIN, GRASSY_TERRAIN, MISTY_TERRAIN,
    PSYCHIC_TERRAIN,
})

# Synergy move ids for weather/terrain scoring.
# These are revealed-only (no species inference).
RAIN_SYNERGY_MOVES = frozenset({
    # Water-type damaging moves that benefit from Rain.
    "waterpulse", "surf", "scald", "muddywater", "hydropump",
    "waterfall", "crabhammer", "dive", "originpulse",
    "sparklingaria", "snipeshot", "weatherball",
    # Thunder / Hurricane (100% accuracy in rain).
    "thunder", "hurricane", "bleakwindstorm", "wildboltstorm",
})

SUN_SYNERGY_MOVES = frozenset({
    # Fire-type damaging moves that benefit from Sun.
    "flamewheel", "flareblitz", "fireblast", "flamethrower",
    "heatwave", "lavaplume", "eruption", "sacredfire",
    "fusionflare", "mindblown", "searingshot", "burningjealousy",
    # Solar Beam / Solar Blade.
    "solarbeam", "solarblade", "solarbeam",
    # Growth (double speed in sun).
    "growth",
})

SAND_SYNERGY_TYPES = frozenset({"rock", "ground", "steel"})

SNOW_SYNERGY_TYPES = frozenset({"ice",})

ELECTRIC_TERRAIN_SYNERGY_MOVES = frozenset({
    "thunder", "thunderbolt", "thunderpunch", "wildcharge",
    "risingvoltage", "terapunch", "electroball", "voltswitch",
    "spark", "chargebeam", "discharge",
})

GRASSY_TERRAIN_SYNERGY_MOVES = frozenset({
    "energyball", "gigadrain", "leafstorm", "leafblade",
    "powerwhip", "seedbomb", "razorleaf", "solarbeam",
    "solarblade", "trailblaze",
})

MISTY_TERRAIN_SYNERGY_TYPES = frozenset({"dragon", "fairy", "psychic"})

PSYCHIC_TERRAIN_SYNERGY_MOVES = frozenset({
    "psychic", "psyshock", "psychicfang", "psystrike",
    "expandingforce", "futuresight", "mysticalfire",
    "storedpower",
})


def _norm_move_id(mid: Any) -> str:
    """Normalize a move id to a canonical form.

    Mirrors the normalization used elsewhere in the
    repo (lowercase, strip spaces/dashes/underscores/
    apostrophes).
    """
    if mid is None:
        return ""
    s = str(mid).lower()
    return (
        s.replace(" ", "").replace("-", "")
        .replace("_", "").replace("'", "")
    )


def _norm_pokemon_type(t: Any) -> str:
    """Normalize a Pokémon type to lowercase."""
    if t is None:
        return ""
    return str(t).lower().strip()


def get_active_weather(battle: Any) -> Optional[str]:
    """Return the normalized active weather on the
    field, or None if no weather is active.

    The poke-env ``battle.weather`` is a
    ``Weather`` enum (or None). This helper maps it to
    a normalized string:

    * ``Weather.RAIN`` / ``Weather.RAINDANCE`` ->
      ``"raindance"``
    * ``Weather.SUN`` / ``Weather.SUNNYDAY`` ->
      ``"sunnyday"``
    * ``Weather.SANDSTORM`` -> ``"sandstorm"``
    * ``Weather.HAIL`` -> ``"hail"``
    * ``Weather.SNOWSCAPE`` -> ``"snowscape"``
    * else -> None (unknown or no weather)

    This is conservative: unknown weather returns
    None, which the caller treats as "no weather
    active" for scoring purposes.
    """
    if battle is None:
        return None
    w = getattr(battle, "weather", None)
    if w is None:
        return None
    s = str(w).upper()
    if "RAIN" in s:
        return RAIN_DANCE
    if "SUN" in s:
        return SUNNY_DAY
    if "SAND" in s:
        return SANDSTORM
    if "SNOW" in s:
        return SNOWSCAPE
    if "HAIL" in s:
        return HAIL
    return None


def get_active_terrain(battle: Any) -> Optional[str]:
    """Return the normalized active terrain on the
    field, or None if no terrain is active.

    The poke-env ``battle.fields`` is a list of
    ``Field`` enums. This helper scans the list and
    returns:

    * ``"electricterrain"`` for ELECTRIC_TERRAIN
    * ``"grassyterrain"`` for GRASSY_TERRAIN
    * ``"mistyterrain"`` for MISTY_TERRAIN
    * ``"psychicterrain"`` for PSYCHIC_TERRAIN
    * else -> None
    """
    if battle is None:
        return None
    fields = getattr(battle, "fields", None)
    if not fields:
        return None
    for f in fields:
        s = str(f).upper()
        if "ELECTRIC" in s:
            return ELECTRIC_TERRAIN
        if "GRASSY" in s or "GRASS" in s:
            return GRASSY_TERRAIN
        if "MISTY" in s:
            return MISTY_TERRAIN
        if "PSYCHIC" in s:
            return PSYCHIC_TERRAIN
    return None


def _own_moves_set(battle: Any, active_idx: int) -> set:
    """Return the normalized set of revealed moves
    available to our active Pokémon at ``active_idx``.

    Uses ``battle.available_moves[active_idx]`` and
    reads ``move.id``. Revealed-only: does not look
    at ``team`` or any hidden info.
    """
    out: set = set()
    if battle is None:
        return out
    moves = getattr(battle, "available_moves", None)
    if not moves or active_idx >= len(moves):
        return out
    for m in moves[active_idx] or []:
        if m is None:
            continue
        mid = getattr(m, "id", None)
        if mid is not None:
            out.add(_norm_move_id(mid))
    return out


def _own_active_types(battle: Any) -> List[Tuple[int, str]]:
    """Return ``[(active_idx, type_str), ...]`` for
    our active Pokémon. Revealed types from
    ``pokemon.types`` only. Does not infer types from
    species when types are unknown.
    """
    out: List[Tuple[int, str]] = []
    if battle is None:
        return out
    actives = getattr(battle, "active_pokemon", None)
    if not actives:
        return out
    for idx, mon in enumerate(actives):
        if mon is None:
            continue
        types = getattr(mon, "types", None) or []
        for t in types:
            out.append((idx, _norm_pokemon_type(t)))
    return out


def _opp_active_types(battle: Any) -> List[Tuple[int, str]]:
    """Return ``[(active_idx, type_str), ...]`` for
    the opponent's active Pokémon. Revealed types
    only.
    """
    out: List[Tuple[int, str]] = []
    if battle is None:
        return out
    opps = getattr(battle, "opponent_active_pokemon", None)
    if not opps:
        return out
    for idx, mon in enumerate(opps):
        if mon is None:
            continue
        types = getattr(mon, "types", None) or []
        for t in types:
            out.append((idx, _norm_pokemon_type(t)))
    return out


def _opp_moves_set(battle: Any) -> set:
    """Return the normalized set of all revealed
    opponent moves across active Pokémon.

    Revealed-only: reads from poke-env's
    ``opponent_active_pokemon``. Does not guess
    hidden moves.
    """
    out: set = set()
    if battle is None:
        return out
    opps = getattr(battle, "opponent_active_pokemon", None)
    if not opps:
        return out
    for mon in opps:
        if mon is None:
            continue
        moves = getattr(mon, "moves", None) or {}
        for mid in moves.keys():
            out.add(_norm_move_id(mid))
    return out


def _score_rain_synergy(
    battle: Any,
    active_idx: int,
) -> float:
    """Return the own-side rain synergy score.

    Counts revealed synergy moves available to our
    active Pokémon:

    * Water-type damaging moves (rain boost)
    * Thunder / Hurricane (100% accuracy in rain)

    Returns a non-negative synergy score. Higher =
    stronger synergy.
    """
    own_moves = _own_moves_set(battle, active_idx)
    score = 0.0
    for m in own_moves:
        if m in RAIN_SYNERGY_MOVES:
            score += 1.0
    return score


def _score_sun_synergy(
    battle: Any,
    active_idx: int,
) -> float:
    """Return the own-side sun synergy score.

    Counts revealed Fire-type synergy moves:
    * Fire damaging moves (sun boost)
    * Solar Beam / Solar Blade (no charge in sun)
    * Growth (double speed in sun)
    """
    own_moves = _own_moves_set(battle, active_idx)
    score = 0.0
    for m in own_moves:
        if m in SUN_SYNERGY_MOVES:
            score += 1.0
    return score


def _score_sand_synergy(battle: Any) -> float:
    """Return the own-side sand synergy score.

    Sandstorm chip damage and SpDef boost benefit
    Rock / Ground / Steel types. Counts our active
    Pokémon whose revealed types are in those
    categories.
    """
    score = 0.0
    for idx, t in _own_active_types(battle):
        if t in SAND_SYNERGY_TYPES:
            score += 1.0
    return score


def _score_snow_synergy(battle: Any) -> float:
    """Return the own-side snow synergy score.

    Snowscape provides 50% Defense boost to Ice
    types and chip damage. Counts our active
    Pokémon whose revealed types are Ice.
    """
    score = 0.0
    for idx, t in _own_active_types(battle):
        if t in SNOW_SYNERGY_TYPES:
            score += 1.0
    return score


def _score_electric_terrain_synergy(
    battle: Any,
    active_idx: int,
) -> float:
    """Return the own-side Electric Terrain synergy
    score.

    Electric Terrain boosts Electric moves (1.3x in
    non-Doubles, but in Doubles the boost is 1.3x
    when not grounded vs opponent -- conservative
    counting). Also prevents sleep on grounded
    Pokémon.
    """
    own_moves = _own_moves_set(battle, active_idx)
    score = 0.0
    for m in own_moves:
        if m in ELECTRIC_TERRAIN_SYNERGY_MOVES:
            score += 1.0
    return score


def _score_grassy_terrain_synergy(
    battle: Any,
    active_idx: int,
) -> float:
    """Return the own-side Grassy Terrain synergy
    score.

    Grassy Terrain boosts Grass moves and heals
    grounded Pokémon by 1/16 each turn. Earth-
    quake-style moves are weakened (0.5x).
    """
    own_moves = _own_moves_set(battle, active_idx)
    score = 0.0
    for m in own_moves:
        if m in GRASSY_TERRAIN_SYNERGY_MOVES:
            score += 1.0
    return score


# Misty Terrain conservative signals.
# The helper counts revealed Dragon-type active mons
# on the opponent side (the threat side) and revealed
# Dragon-type damaging moves on the opponent side.
# Fairies and Psychics are NOT threats that Misty
# blocks; including them in the synergy set was a
# pre-WT-4a bug. WT-4a narrows the signal to
# Dragon-only and adds a status-prevention signal
# (opponent revealed status moves, since Misty
# prevents status on grounded).
DRAGON_TYPE = "dragon"
# Dragon-type damaging moves that Misty halves.
DRAGON_DAMAGING_MOVES = frozenset({
    "dragonclaw", "dragontail", "outrage", "dracometeor",
    "dracopulse", "dragonpulse", "spacialrend",
    "roaroftime", "dragonrush", "dragonbreath",
    "twister", "breaking swipe", "scale shot",
    "clanging scales", "clangorous soul",
    "eternabeam", "fusionbolt",
    "dragonhammer", "nobleroar", "glaciallance",
})
STATUS_INFLICTING_MOVES = frozenset({
    # Status moves that Misty Terrain prevents on
    # grounded Pokémon.
    "thunderwave", "willowisp", "toxic", "spore",
    "sleeppowder", "stunspore", "poisonpowder",
    "hypnosis", "sing", "grasswhistle", "darkvoid",
    "confuseray", "supersonic", "sweetkiss",
    "charm", "flatter", "swagger", "taunt",
    "encore", "disable", "torment",
    "attract", "captivate",
})


def _score_misty_terrain_synergy(battle: Any) -> float:
    """Return the own-side Misty Terrain synergy
    score.

    WT-4a fix: Misty Terrain primarily
    * halves Dragon-type damage against grounded
      Pokémon
    * prevents status conditions on grounded
      Pokémon

    Conservative signals (revealed-only):
    * opponent has revealed Dragon-type damaging
      moves (Misty halves Dragon damage from
      opponent to our side)
    * opponent has revealed status-inflicting moves
      (status prevention is useful for our side)
    """
    score = 0.0
    opp_moves = _opp_moves_set(battle)
    # Signal 1: opponent has revealed Dragon-type
    # damaging moves (the threat to our side)
    if any(m in DRAGON_DAMAGING_MOVES for m in opp_moves):
        score += 1.0
    # Signal 2: opponent has revealed status moves
    if any(m in STATUS_INFLICTING_MOVES for m in opp_moves):
        score += 1.0
    return score


def _score_psychic_terrain_synergy(
    battle: Any,
    active_idx: int,
) -> float:
    """Return the own-side Psychic Terrain synergy
    score.

    Psychic Terrain boosts Psychic moves (1.3x)
    and blocks priority moves targeting grounded
    Pokémon. Conservative: counts revealed Psychic
    synergy moves.
    """
    own_moves = _own_moves_set(battle, active_idx)
    score = 0.0
    for m in own_moves:
        if m in PSYCHIC_TERRAIN_SYNERGY_MOVES:
            score += 1.0
    return score


def _score_opponent_rain_synergy(battle: Any) -> float:
    """Return the opponent's rain synergy score.

    Conservative: counts revealed opponent moves
    that would benefit from rain.
    """
    opp_moves = _opp_moves_set(battle)
    score = 0.0
    for m in opp_moves:
        if m in RAIN_SYNERGY_MOVES:
            score += 1.0
    return score


def _score_opponent_sun_synergy(battle: Any) -> float:
    """Return the opponent's sun synergy score."""
    opp_moves = _opp_moves_set(battle)
    score = 0.0
    for m in opp_moves:
        if m in SUN_SYNERGY_MOVES:
            score += 1.0
    return score


def _score_opponent_sand_synergy(battle: Any) -> float:
    """Return the opponent's sand synergy score
    (counted from opp's revealed types).
    """
    score = 0.0
    for idx, t in _opp_active_types(battle):
        if t in SAND_SYNERGY_TYPES:
            score += 1.0
    return score


def _score_opponent_snow_synergy(battle: Any) -> float:
    """Return the opponent's snow synergy score."""
    score = 0.0
    for idx, t in _opp_active_types(battle):
        if t in SNOW_SYNERGY_TYPES:
            score += 1.0
    return score


def _score_opponent_electric_terrain_synergy(battle: Any) -> float:
    """Return the opponent's Electric Terrain synergy
    score.
    """
    opp_moves = _opp_moves_set(battle)
    score = 0.0
    for m in opp_moves:
        if m in ELECTRIC_TERRAIN_SYNERGY_MOVES:
            score += 1.0
    return score


def _score_opponent_grassy_terrain_synergy(battle: Any) -> float:
    """Return the opponent's Grassy Terrain synergy
    score.
    """
    opp_moves = _opp_moves_set(battle)
    score = 0.0
    for m in opp_moves:
        if m in GRASSY_TERRAIN_SYNERGY_MOVES:
            score += 1.0
    return score


def _score_opponent_misty_terrain_synergy(battle: Any) -> float:
    """Return the opponent's Misty Terrain synergy
    score.

    WT-4a fix: opponent benefits from setting Misty
    if:
    * we have revealed Dragon-type damaging moves
      (Misty halves our Dragon damage to them)
    * we have revealed status-inflicting moves
      (Misty prevents our status on grounded)
    """
    score = 0.0
    own_moves: set = set()
    if battle is not None:
        actives = getattr(battle, "active_pokemon", None)
        if actives:
            for mon in actives:
                if mon is None:
                    continue
                moves = getattr(mon, "moves", None) or {}
                for mid in moves.keys():
                    own_moves.add(_norm_move_id(mid))
    if any(m in DRAGON_DAMAGING_MOVES for m in own_moves):
        score += 1.0
    if any(m in STATUS_INFLICTING_MOVES for m in own_moves):
        score += 1.0
    return score


def _score_opponent_psychic_terrain_synergy(battle: Any) -> float:
    """Return the opponent's Psychic Terrain synergy
    score.
    """
    opp_moves = _opp_moves_set(battle)
    score = 0.0
    for m in opp_moves:
        if m in PSYCHIC_TERRAIN_SYNERGY_MOVES:
            score += 1.0
    return score


def get_weather_terrain_positive_bonus(
    order: Any,
    active_idx: int,
    battle: Any,
    config: Any = None,
) -> Tuple[float, str]:
    """Return ``(bonus, reason)`` for a Weather /
    Terrain setter order under the WT-3 opt-in flag.

    Returns ``(0.0, "")`` when:

    * the master flag is OFF
    * the order is not a Move order
    * the move is not a WT-3 setter
    * the target weather/terrain is already active
      (redundant setter prevention)
    * the opponent's synergy is greater than our own
      (opponent-benefit penalty)
    * the net synergy score is non-positive

    Otherwise returns a positive bonus. The bonus
    magnitude is configurable (``weather_bonus`` /
    ``terrain_bonus``). The reason string is for
    audit / debug visibility.

    This function is **pure** and does not modify
    any state. It does not read or write to
    ``self.config`` directly; instead it takes
    ``config`` as an argument and uses ``getattr``
    with safe defaults.
    """
    if config is None:
        return 0.0, ""
    # Master flag guard
    if not bool(
        getattr(config, "enable_weather_terrain_positive_scoring", False)
    ):
        return 0.0, ""
    # Order must be a Move
    inner = getattr(order, "order", None)
    if inner is None or not hasattr(inner, "id"):
        return 0.0, ""
    move_id = _norm_move_id(getattr(inner, "id", ""))
    if move_id not in WT3_SETTER_MOVE_IDS:
        return 0.0, ""
    # Redundant setter prevention: if the target
    # weather/terrain is already active, no bonus.
    if move_id in WEATHER_SETTER_IDS:
        active_weather = get_active_weather(battle)
        if active_weather == move_id:
            return 0.0, "redundant_weather_penalty"
    if move_id in TERRAIN_SETTER_IDS:
        active_terrain = get_active_terrain(battle)
        if active_terrain == move_id:
            return 0.0, "redundant_terrain_penalty"
    # Compute own synergy and opponent synergy
    own_score = 0.0
    opp_score = 0.0
    reason = ""
    if move_id == RAIN_DANCE:
        own_score = _score_rain_synergy(battle, active_idx)
        opp_score = _score_opponent_rain_synergy(battle)
        reason = "rain_water_synergy"
    elif move_id == SUNNY_DAY:
        own_score = _score_sun_synergy(battle, active_idx)
        opp_score = _score_opponent_sun_synergy(battle)
        reason = "sun_fire_synergy"
    elif move_id in (SANDSTORM,):
        own_score = _score_sand_synergy(battle)
        opp_score = _score_opponent_sand_synergy(battle)
        reason = "sand_rock_ground_steel_synergy"
    elif move_id in (SNOWSCAPE, HAIL):
        own_score = _score_snow_synergy(battle)
        opp_score = _score_opponent_snow_synergy(battle)
        reason = "snow_ice_synergy"
    elif move_id == ELECTRIC_TERRAIN:
        own_score = _score_electric_terrain_synergy(
            battle, active_idx
        )
        opp_score = _score_opponent_electric_terrain_synergy(
            battle
        )
        reason = "terrain_electric_synergy"
    elif move_id == GRASSY_TERRAIN:
        own_score = _score_grassy_terrain_synergy(
            battle, active_idx
        )
        opp_score = _score_opponent_grassy_terrain_synergy(
            battle
        )
        reason = "terrain_grass_synergy"
    elif move_id == MISTY_TERRAIN:
        own_score = _score_misty_terrain_synergy(battle)
        opp_score = _score_opponent_misty_terrain_synergy(
            battle
        )
        reason = "terrain_status_dragon_block_synergy"
    elif move_id == PSYCHIC_TERRAIN:
        own_score = _score_psychic_terrain_synergy(
            battle, active_idx
        )
        opp_score = _score_opponent_psychic_terrain_synergy(
            battle
        )
        reason = "terrain_priority_block_synergy"
    # Opponent-benefit penalty: if opp benefits more,
    # net score is negative.
    net = own_score - opp_score
    if net <= 0:
        return 0.0, "opponent_benefit_penalty"
    # Apply bonus. Choose weather_bonus or
    # terrain_bonus based on move type.
    if move_id in WEATHER_SETTER_IDS:
        bonus = float(
            getattr(config, "weather_terrain_positive_weather_bonus", 150.0)
        )
    else:
        bonus = float(
            getattr(config, "weather_terrain_positive_terrain_bonus", 120.0)
        )
    return float(bonus), reason


def is_wt3_setter_move(move_id: str) -> bool:
    """Return True if the normalized ``move_id`` is a
    WT-3 setter (weather or terrain).
    """
    return _norm_move_id(move_id) in WT3_SETTER_MOVE_IDS


# Phase WT-4a: bad-setter detection. Given a selected
# setter and the battle state, return a list of
# suspicious-reason strings. An empty list means the
# setter selection is clean. This is analysis-only and
# does not block the selection.
BAD_SETTER_NO_OWN_SYNERGY = "no_own_synergy"
BAD_SETTER_OPP_BENEFITS = "opponent_benefits_more"
BAD_SETTER_REDUNDANT = "redundant_setter"
BAD_SETTER_NO_ACTIVE = "no_active_user"


def is_bad_setter_selection(
    move_id: str,
    active_idx: int,
    battle: Any,
) -> List[str]:
    """Return a list of suspicious-reason strings for a
    selected WT-3 setter. Empty list = clean.

    This is conservative: only flags a setter as
    suspicious if at least one of the following is
    true:

    * target weather/terrain is already active
      (redundant)
    * own synergy score is 0 (no revealed own-side
      synergy)
    * opponent synergy score > own synergy score
      (opponent benefits more)
    * the active user is None (no actual user)
    """
    reasons: List[str] = []
    mid = _norm_move_id(move_id)
    if mid not in WT3_SETTER_MOVE_IDS:
        return reasons
    if battle is None:
        return reasons
    # Redundant setter
    if mid in WEATHER_SETTER_IDS:
        active_weather = get_active_weather(battle)
        if active_weather == mid:
            reasons.append(BAD_SETTER_REDUNDANT)
    if mid in TERRAIN_SETTER_IDS:
        active_terrain = get_active_terrain(battle)
        if active_terrain == mid:
            reasons.append(BAD_SETTER_REDUNDANT)
    # No active user
    if active_idx is None:
        reasons.append(BAD_SETTER_NO_ACTIVE)
    # Own synergy score
    own_score = 0.0
    opp_score = 0.0
    if mid == RAIN_DANCE:
        own_score = _score_rain_synergy(battle, active_idx)
        opp_score = _score_opponent_rain_synergy(battle)
    elif mid == SUNNY_DAY:
        own_score = _score_sun_synergy(battle, active_idx)
        opp_score = _score_opponent_sun_synergy(battle)
    elif mid == SANDSTORM:
        own_score = _score_sand_synergy(battle)
        opp_score = _score_opponent_sand_synergy(battle)
    elif mid in (SNOWSCAPE, HAIL):
        own_score = _score_snow_synergy(battle)
        opp_score = _score_opponent_snow_synergy(battle)
    elif mid == ELECTRIC_TERRAIN:
        own_score = _score_electric_terrain_synergy(
            battle, active_idx
        )
        opp_score = _score_opponent_electric_terrain_synergy(
            battle
        )
    elif mid == GRASSY_TERRAIN:
        own_score = _score_grassy_terrain_synergy(
            battle, active_idx
        )
        opp_score = _score_opponent_grassy_terrain_synergy(
            battle
        )
    elif mid == MISTY_TERRAIN:
        own_score = _score_misty_terrain_synergy(battle)
        opp_score = _score_opponent_misty_terrain_synergy(
            battle
        )
    elif mid == PSYCHIC_TERRAIN:
        own_score = _score_psychic_terrain_synergy(
            battle, active_idx
        )
        opp_score = _score_opponent_psychic_terrain_synergy(
            battle
        )
    if own_score <= 0:
        reasons.append(BAD_SETTER_NO_OWN_SYNERGY)
    if opp_score > own_score:
        reasons.append(BAD_SETTER_OPP_BENEFITS)
    return reasons


# Phase WT-4c: candidate inclusion helper.
# This helper decides whether a Weather/Terrain
# setter should be force-included in the scored
# candidate set when the bot's natural valid_orders
# might exclude it. It is narrow and opt-in only.
#
# Inclusion criteria (ALL must pass):
# 1. enable_weather_terrain_positive_scoring is True
# 2. move is a known WT-3 setter
# 3. WT-3 helper returns positive own_synergy
# 4. opp_synergy does not cancel the bonus
# 5. target weather/terrain is not already active
# 6. config bonus is positive
#
# Returns a dict with:
#   include: bool
#   reason: str
#   bonus: float
#   target: weather/terrain id
#   own_synergy_score: float
#   opponent_synergy_score: float
#   net_synergy_score: float
INCLUSION_REJECTED_FLAG_OFF = "flag_off"
INCLUSION_REJECTED_NOT_SETTER = "not_a_wt_setter"
INCLUSION_REJECTED_REDUNDANT = "redundant_setter"
INCLUSION_REJECTED_OPP_BENEFITS = "opponent_benefits_more"
INCLUSION_REJECTED_NO_SYNERGY = "no_positive_synergy"
INCLUSION_REJECTED_ZERO_BONUS = "zero_bonus"
INCLUSION_ACCEPTED = "accepted"


def should_include_weather_terrain_setter_candidate(
    move_id: str,
    active_idx: int,
    battle: Any,
    config: Any,
) -> Dict[str, Any]:
    """Phase WT-4c: decide whether a Weather/Terrain
    setter should be force-included in the scored
    candidate set.

    This is a narrow opt-in helper. It returns a
    dict with ``include``, ``reason``, ``bonus``,
    ``target``, ``own_synergy_score``,
    ``opponent_synergy_score``, and
    ``net_synergy_score``.

    The helper is pure: it does not read or write
    bot state, does not call into the bot engine,
    and does not open files.
    """
    result: Dict[str, Any] = {
        "include": False,
        "reason": "",
        "bonus": 0.0,
        "target": "",
        "own_synergy_score": 0.0,
        "opponent_synergy_score": 0.0,
        "net_synergy_score": 0.0,
    }
    # 1. Master flag must be ON
    if config is None:
        result["reason"] = INCLUSION_REJECTED_FLAG_OFF
        return result
    if not bool(
        getattr(
            config, "enable_weather_terrain_positive_scoring",
            False,
        )
    ):
        result["reason"] = INCLUSION_REJECTED_FLAG_OFF
        return result
    # 2. Move must be a WT-3 setter
    norm = _norm_move_id(move_id)
    if norm not in WT3_SETTER_MOVE_IDS:
        result["reason"] = INCLUSION_REJECTED_NOT_SETTER
        return result
    result["target"] = norm
    # 3. Redundant setter check
    if norm in WEATHER_SETTER_IDS:
        active_weather = get_active_weather(battle)
        if active_weather == norm:
            result["reason"] = INCLUSION_REJECTED_REDUNDANT
            return result
    if norm in TERRAIN_SETTER_IDS:
        active_terrain = get_active_terrain(battle)
        if active_terrain == norm:
            result["reason"] = INCLUSION_REJECTED_REDUNDANT
            return result
    # 4. Compute own and opponent synergy
    own_score = 0.0
    opp_score = 0.0
    if norm == RAIN_DANCE:
        own_score = _score_rain_synergy(battle, active_idx)
        opp_score = _score_opponent_rain_synergy(battle)
    elif norm == SUNNY_DAY:
        own_score = _score_sun_synergy(battle, active_idx)
        opp_score = _score_opponent_sun_synergy(battle)
    elif norm == SANDSTORM:
        own_score = _score_sand_synergy(battle)
        opp_score = _score_opponent_sand_synergy(battle)
    elif norm in (SNOWSCAPE, HAIL):
        own_score = _score_snow_synergy(battle)
        opp_score = _score_opponent_snow_synergy(battle)
    elif norm == ELECTRIC_TERRAIN:
        own_score = _score_electric_terrain_synergy(
            battle, active_idx
        )
        opp_score = _score_opponent_electric_terrain_synergy(
            battle
        )
    elif norm == GRASSY_TERRAIN:
        own_score = _score_grassy_terrain_synergy(
            battle, active_idx
        )
        opp_score = _score_opponent_grassy_terrain_synergy(
            battle
        )
    elif norm == MISTY_TERRAIN:
        own_score = _score_misty_terrain_synergy(battle)
        opp_score = _score_opponent_misty_terrain_synergy(
            battle
        )
    elif norm == PSYCHIC_TERRAIN:
        own_score = _score_psychic_terrain_synergy(
            battle, active_idx
        )
        opp_score = _score_opponent_psychic_terrain_synergy(
            battle
        )
    result["own_synergy_score"] = own_score
    result["opponent_synergy_score"] = opp_score
    result["net_synergy_score"] = own_score - opp_score
    # 5. Own synergy must be positive
    if own_score <= 0:
        result["reason"] = INCLUSION_REJECTED_NO_SYNERGY
        return result
    # 6. Opp synergy must not cancel
    if opp_score > own_score:
        result["reason"] = INCLUSION_REJECTED_OPP_BENEFITS
        return result
    # 7. Compute bonus
    bonus = 0.0
    if norm in WEATHER_SETTER_IDS:
        bonus = float(
            getattr(
                config,
                "weather_terrain_positive_weather_bonus",
                150.0,
            )
        )
    else:
        bonus = float(
            getattr(
                config,
                "weather_terrain_positive_terrain_bonus",
                120.0,
            )
        )
    if bonus <= 0:
        result["reason"] = INCLUSION_REJECTED_ZERO_BONUS
        return result
    # All checks pass
    result["include"] = True
    result["reason"] = INCLUSION_ACCEPTED
    result["bonus"] = bonus
    return result
