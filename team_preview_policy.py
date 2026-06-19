#!/usr/bin/env python3
"""
VGC 2026 Team Preview Policy Module

Provides 4-from-6 team selection policies for VGC battles.

The canonical Pokémon mechanics primitives (type chart, type
multiplier, ability interactions, dynamic move type, STAB,
spread, priority, Fake Out legality, speed ordering) live in
``doubles_mechanics``. This module imports them and re-exports
the parts the preview evaluators depend on so the existing
V2i / V2j test contracts continue to work.
"""

from typing import List, Dict, Any, Optional, Tuple
import random
from dataclasses import dataclass, field
from itertools import combinations
from collections import Counter

from doubles_mechanics import (
    TYPE_CHART,
    calculate_type_multiplier,
    resolve_effective_move_type,
    get_effective_move_type,
    classify_move as _dm_classify_move,
    EXPLICIT_ABSORB_ABILITIES,
)


__all__ = [
    "TYPE_CHART",
    "SPECIES_TYPES",
    "get_species_types",
    "get_move_category",
    "get_ability_category",
    "calculate_type_matchup",
    "calculate_weakness_avoidance",
    "calculate_type_multiplier",
    "ABSORB_ABILITIES",
]


# Species -> types mapping
SPECIES_TYPES = {
    "venusaur": ["grass", "poison"],
    "charizard": ["fire", "flying"],
    "garchomp": ["dragon", "ground"],
    "incineroar": ["fire", "dark"],
    "floetteeternal": ["fairy"],
    "sinistcha": ["grass", "ghost"],
    "archaludon": ["steel", "dragon"],
    "basculegion": ["water", "ghost"],
    "sneasler": ["fighting", "poison"],
    "kingambit": ["dark", "steel"],
    "whimsicott": ["grass", "fairy"],
    "pelipper": ["water", "flying"],
    "rillaboom": ["grass"],
    "calyrexice": ["psychic", "ice"],
    "calyrexshadow": ["psychic", "ghost"],
    "urshifusingle": ["fighting", "dark"],
    "urshifurapid": ["fighting", "water"],
    "tapukoko": ["electric", "fairy"],
    "tapulele": ["psychic", "fairy"],
    "tapubulu": ["grass", "fairy"],
    "tapufini": ["water", "fairy"],
    "landorustherian": ["ground", "flying"],
    "tornadustherian": ["flying"],
    "thundurustherian": ["electric", "flying"],
    "ironbundle": ["ice", "water"],
    "ironthorns": ["rock", "electric"],
    "ironmoth": ["fire", "poison"],
    "ironhands": ["fighting", "electric"],
    "ironjugulis": ["dark", "flying"],
    "ironvaliant": ["fairy", "fighting"],
    "fluttermane": ["ghost", "fairy"],
    "slitherwing": ["bug", "fighting"],
    "sandyshocks": ["ground", "electric"],
    "scream tail": ["fairy", "psychic"],
    "brutebonnet": ["grass", "dark"],
    "flatterfly": ["bug", "fairy"],
    "chi-yu": ["dark", "fire"],
    "chien-pao": ["dark", "ice"],
    "ting-lu": ["dark", "ground"],
    "wo-chien": ["dark", "grass"],
    "scream tail": ["fairy", "psychic"],
    "brutebonnet": ["grass", "dark"],
    "flatterfly": ["bug", "fairy"],
    "great tusk": ["ground", "fighting"],
    "annihilape": ["fighting", "ghost"],
    "clodsire": ["poison", "ground"],
    "farigiraf": ["normal", "psychic"],
    "dondozo": ["water"],
    "tatsugiri": ["dragon", "water"],
    "archaludon": ["steel", "dragon"],
    "rabsca": ["bug", "psychic"],
    "tinkaton": ["fairy", "steel"],
    "garganacl": ["rock"],
    "naclstack": ["rock"],
    "nacli": ["rock"],
    "gholdengo": ["steel", "ghost"],
    "gimmighoul": ["steel"],
    "gimmighoulroaming": ["steel"],
    "kingambit": ["dark", "steel"],
    "pawmo": ["electric", "fighting"],
    "pawmot": ["electric", "fighting"],
    "rampardos": ["rock"],
    "bastiodon": ["rock", "steel"],
    "shieldon": ["rock", "steel"],
    "cranidos": ["rock"],
    "tirtouga": ["water", "rock"],
    "carracosta": ["water", "rock"],
    "archen": ["rock", "flying"],
    "archeops": ["rock", "flying"],
    "tyrunt": ["rock", "dragon"],
    "tyrantrum": ["rock", "dragon"],
    "amaura": ["rock", "ice"],
    "aurorus": ["rock", "ice"],
    "goomy": ["dragon"],
    "sliggoo": ["dragon"],
    "goodra": ["dragon"],
    "goodrahisui": ["steel", "dragon"],
    "deino": ["dark", "dragon"],
    "zweilous": ["dark", "dragon"],
    "hydreigon": ["dark", "dragon"],
    "jangmo-o": ["dragon"],
    "hakamo-o": ["dragon", "fighting"],
    "kommo-o": ["dragon", "fighting"],
    "noibat": ["flying", "dragon"],
    "noivern": ["flying", "dragon"],
    "dreepy": ["dragon", "ghost"],
    "drakloak": ["dragon", "ghost"],
    "dragapult": ["dragon", "ghost"],
    "cyclizar": ["dragon", "normal"],
    "tatsugiri": ["dragon", "water"],
    "dondozo": ["water"],
    "orthworm": ["steel"],
    "glimmora": ["rock", "poison"],
    "charcadet": ["fire"],
    "armarouge": ["fire", "psychic"],
    "ceruledge": ["fire", "ghost"],
    "greavard": ["ghost"],
    "houndstone": ["ghost"],
    "flamigo": ["flying", "fighting"],
    "palafin": ["water"],
    "finizen": ["water"],
    "veluza": ["water", "psychic"],
    "annihilape": ["fighting", "ghost"],
    "clodsire": ["poison", "ground"],
    "farigiraf": ["normal", "psychic"],
    "dudunsparce": ["normal"],
    "dudunsparcethreesegment": ["normal"],
    "ting-lu": ["dark", "ground"],
    "chien-pao": ["dark", "ice"],
    "wo-chien": ["dark", "grass"],
    "chi-yu": ["dark", "fire"],
    "iron bundle": ["ice", "water"],
    "iron hands": ["fighting", "electric"],
    "iron jugulis": ["dark", "flying"],
    "iron thorns": ["rock", "electric"],
    "iron valiant": ["fairy", "fighting"],
    "iron leaves": ["grass", "psychic"],
    "iron crown": ["steel", "psychic"],
    "iron boulder": ["rock", "psychic"],
    "gouging fire": ["fire", "dragon"],
    "raging bolt": ["electric", "dragon"],
    "arcanine": ["fire"],
    "marowakalola": ["fire", "ghost"],
    "lycanroc": ["rock"],
    "lycanrocmidnight": ["rock"],
    "lycanrocdusk": ["rock"],
    "necrozma": ["psychic"],
    "necrozmaduskmane": ["psychic", "steel"],
    "necrozmadawnwings": ["psychic", "ghost"],
    "necrozmaultra": ["psychic", "dragon"],
    "solgalo": ["psychic", "steel"],
    "lunala": ["psychic", "ghost"],
    "cosmog": ["psychic"],
    "cosmoem": ["psychic"],
    "nihilego": ["rock", "poison"],
    "buzzwole": ["bug", "fighting"],
    "pheromosa": ["bug", "fighting"],
    "xurkitree": ["electric"],
    "celesteela": ["steel", "flying"],
    "kartana": ["grass", "steel"],
    "guzzlord": ["dark", "dragon"],
    "stakataka": ["rock", "steel"],
    "blacephalon": ["fire", "ghost"],
    "poipole": ["poison"],
    "naganadel": ["poison", "dragon"],
    "stunfisk": ["ground", "electric"],
    "stunfiskgalar": ["ground", "steel"],
    "zamazenta": ["fighting"],
    "zamazentacrowned": ["fighting", "steel"],
    "zacian": ["fairy"],
    "zaciancrowned": ["fairy", "steel"],
    "eternatus": ["poison", "dragon"],
    "kubfu": ["fighting"],
    "urshifu": ["fighting", "dark"],
    "urshifusingle": ["fighting", "dark"],
    "urshifurapid": ["fighting", "water"],
    "ursaluna": ["ground", "normal"],
    "ursalunabloodmoon": ["ground", "normal"],
    "basculegion": ["water", "ghost"],
    "basculegionf": ["water", "ghost"],
    "sneasler": ["fighting", "poison"],
    "overqwil": ["dark", "poison"],
    "kleavor": ["bug", "rock"],
    "growlithehisui": ["fire", "rock"],
    "arcaninehisui": ["fire", "rock"],
    "arcanine": ["fire"],
    "zygarde10": ["dragon", "ground"],
    "zygardecomplete": ["dragon", "ground"],
    "floette": ["fairy"],
    "floetteeternal": ["fairy"],
    "sinistchamasterpiece": ["grass", "ghost"],
    "pecharunt": ["poison", "ghost"],
    "ogerpon": ["grass"],
    "ogerponwellspring": ["grass", "water"],
    "ogerponhearthflame": ["grass", "fire"],
    "ogerponcornerstone": ["grass", "rock"],
    "poltchageist": ["grass", "ghost"],
    "sinistcha": ["grass", "ghost"],
    "poltchageist": ["grass", "ghost"],
    "meowscarada": ["grass", "dark"],
    "skeledirge": ["fire", "ghost"],
    "annihilape": ["fighting", "ghost"],
    "ironcrown": ["steel", "psychic"],
    "iron leaves": ["grass", "psychic"],
    "gouging fire": ["fire", "dragon"],
    "raging bolt": ["electric", "dragon"],
    "arcanine": ["fire"],
    "marowakalola": ["fire", "ghost"],
    "lycanroc": ["rock"],
    "lycanrocmidnight": ["rock"],
    "lycanrocdusk": ["rock"],
    "necrozma": ["psychic"],
    "necrozmaduskmane": ["psychic", "steel"],
    "necrozmadawnwings": ["psychic", "ghost"],
    "necrozmaultra": ["psychic", "dragon"],
    "solgalo": ["psychic", "steel"],
    "lunala": ["psychic", "ghost"],
    "cosmog": ["psychic"],
    "cosmoem": ["psychic"],
    "nihilego": ["rock", "poison"],
    "buzzwole": ["bug", "fighting"],
    "pheromosa": ["bug", "fighting"],
    "xurkitree": ["electric"],
    "celesteela": ["steel", "flying"],
    "kartana": ["grass", "steel"],
    "guzzlord": ["dark", "dragon"],
    "stakataka": ["rock", "steel"],
    "blacephalon": ["fire", "ghost"],
    "poipole": ["poison"],
    "naganadel": ["poison", "dragon"],
    "stunfisk": ["ground", "electric"],
    "stunfiskgalar": ["ground", "steel"],
    "kubfu": ["fighting"],
    "urshifusingle": ["fighting", "dark"],
    "urshifurapid": ["fighting", "water"],
    "ursaluna": ["ground", "normal"],
    "ursalunabloodmoon": ["ground", "normal"],
    "basculegionf": ["water", "ghost"],
    "sneasler": ["fighting", "poison"],
    "overqwil": ["dark", "poison"],
    "kleavor": ["bug", "rock"],
    "growlithehisui": ["fire", "rock"],
    "arcaninehisui": ["fire", "rock"],
    "zygarde10": ["dragon", "ground"],
    "floetteeternal": ["fairy"],
    "sinistcha": ["grass", "ghost"],
    "poltchageist": ["grass", "ghost"],
    "sinistchamasterpiece": ["grass", "ghost"],
    "pecharunt": ["poison", "ghost"],
    "pidx": ["normal"],
    "pidx": ["normal"],
}


@dataclass
class PokemonScore:
    """Score breakdown for a Pokémon."""
    species: str
    total: float = 0
    fake_out: float = 0
    intimidate: float = 0
    tailwind: float = 0
    trick_room: float = 0
    redirection: float = 0
    spread_move: float = 0
    protect: float = 0
    type_matchup: float = 0
    weakness_avoidance: float = 0
    role: str = ""


@dataclass
class PreviewResult:
    """Result of 4-from-6 selection."""
    chosen_4: List[str]
    lead_2: List[str]
    back_2: List[str]
    scores: List[PokemonScore] = field(default_factory=list)
    policy: str = ""
    seed: Optional[int] = None


def get_species_types(species: str) -> List[str]:
    """Get types for a species."""
    key = species.lower().replace(" ", "").replace("-", "").replace("[", "").replace("]", "")
    return SPECIES_TYPES.get(key, [])


def get_move_category(move: str) -> str:
    """Categorize a move for scoring purposes."""
    move_lower = move.lower()

    if "fake out" in move_lower:
        return "fake_out"
    if "tailwind" in move_lower:
        return "tailwind"
    if "trick room" in move_lower:
        return "trick_room"
    if "follow me" in move_lower or "rage powder" in move_lower:
        return "redirection"

    spread_keywords = ["heat wave", "earthquake", "rock slide", "surf", "discharge",
                       "hyper voice", "blizzard", "muddy water", "lava plume",
                       "icy wind", "electroweb", "eruption", "water spout"]
    if any(kw in move_lower for kw in spread_keywords):
        return "spread"

    if "protect" in move_lower or "detect" in move_lower or "wide guard" in move_lower or "spiky shield" in move_lower or "king's shield" in move_lower:
        return "protect"

    return "other"


def get_ability_category(ability: str) -> str:
    """Categorize an ability for scoring purposes."""
    ability_lower = ability.lower()

    if "intimidate" in ability_lower:
        return "intimidate"
    if "drizzle" in ability_lower or "drought" in ability_lower or "snow warning" in ability_lower or "electric surge" in ability_lower or "psychic surge" in ability_lower or "grassy surge" in ability_lower or "misty surge" in ability_lower:
        return "weather"
    if "levitate" in ability_lower:
        return "levitate"
    if "magic bounce" in ability_lower:
        return "magic_bounce"
    if "storm drain" in ability_lower or "lightning rod" in ability_lower or "flash fire" in ability_lower or "water absorb" in ability_lower or "volt absorb" in ability_lower or "soundproof" in ability_lower:
        return "redirection"
    if "prankster" in ability_lower:
        return "prankster"
    if "gale wings" in ability_lower:
        return "gale_wings"
    if "unburden" in ability_lower:
        return "speed"

    return "other"


def calculate_type_matchup(our_types: List[str], their_types: List[str]) -> float:
    """Calculate offensive type matchup score.

    For dual types, combined effectiveness = product of individual type multipliers.
    Returns normalized score (max 1.0 for 4x effectiveness).
    """
    if not our_types or not their_types:
        return 0.0

    # Calculate combined multiplier for each attacking type
    best_combined = 0.0
    for our_type in our_types:
        combined_multiplier = 1.0
        for their_type in their_types:
            multiplier = TYPE_CHART.get(our_type, {}).get(their_type, 1.0)
            combined_multiplier *= multiplier
        best_combined = max(best_combined, combined_multiplier)

    # Normalize: 4x = 1.0, 2x = 0.5, 1x = 0.25, 0.5x = 0.125, 0x = 0
    return min(best_combined / 4.0, 1.0)


def calculate_weakness_avoidance(our_types: List[str], their_types: List[str]) -> float:
    """Calculate defensive resistance score.

    For dual types, combined weakness = product of individual type multipliers.
    """
    if not our_types or not their_types:
        return 0.0

    # Calculate combined multiplier for each attacking type
    worst_combined_multiplier = 1.0
    for their_type in their_types:
        combined_multiplier = 1.0
        for our_type in our_types:
            multiplier = TYPE_CHART.get(their_type, {}).get(our_type, 1.0)
            combined_multiplier *= multiplier
        worst_combined_multiplier = max(worst_combined_multiplier, combined_multiplier)

    if worst_combined_multiplier >= 4.0:
        return 0.0
    elif worst_combined_multiplier >= 2.0:
        return 0.5
    else:
        return 1.0


def score_pokemon(
    pokemon: Dict[str, Any],
    opponent_team: Optional[List[Dict[str, Any]]] = None
) -> PokemonScore:
    """Score a single Pokémon for 4-from-6 selection."""
    species = pokemon.get("species", "")
    ability = pokemon.get("ability", "")
    moves = pokemon.get("moves", [])

    score = PokemonScore(species=species)

    # Ability scoring
    ability_cat = get_ability_category(ability)
    if ability_cat == "intimidate":
        score.intimidate = 1.0
    elif ability_cat in ("weather", "prankster", "gale_wings", "speed"):
        score.intimidate = 0.3

    # Move scoring
    has_fake_out = False
    has_tailwind = False
    has_trick_room = False
    has_redirection = False
    has_spread = False
    has_protect = False

    for move in moves:
        cat = get_move_category(move)
        if cat == "fake_out":
            has_fake_out = True
        elif cat == "tailwind":
            has_tailwind = True
        elif cat == "trick_room":
            has_trick_room = True
        elif cat == "redirection":
            has_redirection = True
        elif cat == "spread":
            has_spread = True
        elif cat == "protect":
            has_protect = True

    if has_fake_out:
        score.fake_out = 1.0
    if has_tailwind:
        score.tailwind = 1.0
    if has_trick_room:
        score.trick_room = 1.0
    if has_redirection:
        score.redirection = 1.0
    if has_spread:
        score.spread_move = 1.0
    if has_protect:
        score.protect = 1.0

    # Type matchup if opponent team provided
    if opponent_team:
        our_types = get_species_types(pokemon.get("species", ""))

        matchup_sum = 0.0
        weakness_sum = 0.0
        count = 0
        for opp in opponent_team:
            opp_types = get_species_types(opp.get("species", ""))
            if opp_types:
                matchup_sum += calculate_type_matchup(our_types, opp_types)
                weakness_sum += calculate_weakness_avoidance(our_types, opp_types)
                count += 1

        if count > 0:
            score.type_matchup = matchup_sum / count
            score.weakness_avoidance = weakness_sum / count

    # Total score with weights
    weights = {
        "fake_out": 2.0,
        "intimidate": 1.5,
        "tailwind": 1.5,
        "trick_room": 1.0,
        "redirection": 1.5,
        "spread_move": 1.0,
        "protect": 1.0,
        "type_matchup": 2.0,
        "weakness_avoidance": 1.5,
    }

    score.total = (
        score.fake_out * weights["fake_out"] +
        score.intimidate * weights["intimidate"] +
        score.tailwind * weights["tailwind"] +
        score.trick_room * weights["trick_room"] +
        score.redirection * weights["redirection"] +
        score.spread_move * weights["spread_move"] +
        score.protect * weights["protect"] +
        score.type_matchup * weights["type_matchup"] +
        score.weakness_avoidance * weights["weakness_avoidance"]
    )

    # Determine role
    roles = []
    if score.fake_out > 0:
        roles.append("Fake Out")
    if score.intimidate > 0:
        roles.append("Intimidate")
    if score.tailwind > 0:
        roles.append("Tailwind")
    if score.trick_room > 0:
        roles.append("Trick Room")
    if score.redirection > 0:
        roles.append("Redirection")
    if score.spread_move > 0:
        roles.append("Spread")
    if score.protect > 0:
        roles.append("Protect")
    if score.type_matchup > 0.7:
        roles.append("Offensive Coverage")
    if score.weakness_avoidance > 0.7:
        roles.append("Defensive Pivot")

    score.role = " / ".join(roles) if roles else "Support"

    return score


def score_combination(
    combination: List[Dict[str, Any]],
    opponent_team: Optional[List[Dict[str, Any]]] = None
) -> Tuple[float, Dict[str, Any]]:
    """
    Score a 4-Pokémon combination jointly.

    Evaluates:
    - Lead pair synergy (Fake Out + support/pressure)
    - Back slot coverage (offensive/defensive compliment)
    - Type diversity & weakness spreading
    - Speed control presence
    - Role complementarity (no duplicated roles)
    - Protect/Fake Out availability across board
    - Board-wide pressure (spread + priority + redirection)
    """
    if len(combination) != 4:
        return 0.0, {}

    # Score each Pokemon individually first
    individual_scores = {}
    for p in combination:
        individual_scores[p.get("species", "")] = score_pokemon(p, opponent_team)

    # --- Joint scoring components ---

    # 1. Lead pair synergy (positions 0, 1 in chosen_4 order)
    p1, p2 = combination[0], combination[1]
    s1, s2 = individual_scores[p1.get("species", "")], individual_scores[p2.get("species", "")]

    lead_synergy = 0.0
    # Fake Out + pressure/support. Lead order must not change the score.
    if (
        (s1.fake_out > 0 and (s2.spread_move > 0 or s2.tailwind > 0 or s2.redirection > 0 or s2.trick_room > 0))
        or
        (s2.fake_out > 0 and (s1.spread_move > 0 or s1.tailwind > 0 or s1.redirection > 0 or s1.trick_room > 0))
    ):
        lead_synergy += 1.5
    elif (
        (s1.intimidate > 0 and (s2.spread_move > 0 or s2.tailwind > 0 or s2.redirection > 0))
        or
        (s2.intimidate > 0 and (s1.spread_move > 0 or s1.tailwind > 0 or s1.redirection > 0))
    ):
        lead_synergy += 1.0
    elif (
        (s1.redirection > 0 and s2.spread_move > 0)
        or (s2.redirection > 0 and s1.spread_move > 0)
    ):
        lead_synergy += 1.5

    # 2. Back slot coverage (positions 2, 3)
    b1, b2 = combination[2], combination[3]
    bs1, bs2 = individual_scores[b1.get("species", "")], individual_scores[b2.get("species", "")]

    back_coverage = 0.0
    # Complementary roles in back
    back_roles = set()
    for s in [bs1, bs2]:
        if s.spread_move > 0: back_roles.add("spread")
        if s.tailwind > 0: back_roles.add("speed_control")
        if s.trick_room > 0: back_roles.add("trick_room")
        if s.redirection > 0: back_roles.add("redirection")
        if s.fake_out > 0: back_roles.add("fake_out")
        if s.type_matchup > 0.7: back_roles.add("offensive")
        if s.weakness_avoidance > 0.7: back_roles.add("defensive")
    back_coverage = len(back_roles) * 0.5  # reward diverse back roles

    # 3. Type diversity across all 4
    types = []
    for p in combination:
        types.extend(get_species_types(p.get("species", "")))
    type_diversity = len(set(types)) * 0.3  # max ~18 types * 0.3 = 5.4

    # 4. Weakness spreading
    weakness_penalty = 0.0
    if len(combination) == 4:
        common_weaknesses = Counter()
        for p in combination:
            p_types = get_species_types(p.get("species", ""))
            for attacking_type, multipliers in TYPE_CHART.items():
                combined = 1.0
                for defending_type in p_types:
                    combined *= multipliers.get(defending_type, 1.0)
                if combined >= 2.0:
                    common_weaknesses[attacking_type] += 1
        for count in common_weaknesses.values():
            if count >= 3:
                weakness_penalty -= 2.0  # heavy penalty for 3+ sharing weakness
            elif count == 2:
                weakness_penalty -= 0.5

    # 5. Speed control presence
    speed_control_bonus = 0.0
    has_tailwind = any(s.tailwind > 0 for s in individual_scores.values())
    has_trick_room = any(s.trick_room > 0 for s in individual_scores.values())
    if has_tailwind: speed_control_bonus += 1.0
    if has_trick_room: speed_control_bonus += 1.0

    # 6. Protect availability across board
    protect_bonus = sum(1 for s in individual_scores.values() if s.protect > 0) * 0.3

    # 7. Fake Out availability
    fake_out_bonus = sum(1 for s in individual_scores.values() if s.fake_out > 0) * 0.5

    # 8. Intimidate presence
    intimidate_bonus = sum(1 for s in individual_scores.values() if s.intimidate > 0) * 0.4

    # 9. Redirection
    redirection_bonus = sum(1 for s in individual_scores.values() if s.redirection > 0) * 0.5

    # 10. Spread move coverage
    spread_bonus = sum(1 for s in individual_scores.values() if s.spread_move > 0) * 0.4

    # 10b. Duplicated role penalty. One source is useful; stacking the same
    # narrow support role has diminishing preview value.
    role_duplicate_penalty = 0.0
    for attr, penalty in (
        ("fake_out", 0.4),
        ("tailwind", 0.5),
        ("trick_room", 0.5),
        ("redirection", 0.4),
    ):
        count = sum(1 for s in individual_scores.values() if getattr(s, attr) > 0)
        if count > 1:
            role_duplicate_penalty -= (count - 1) * penalty

    # 11. Offensive coverage vs opponent
    offense_bonus = 0.0
    if opponent_team:
        for s in individual_scores.values():
            offense_bonus += s.type_matchup * 1.5

    # 12. Defensive pivot value
    defense_bonus = 0.0
    if opponent_team:
        for s in individual_scores.values():
            defense_bonus += s.weakness_avoidance * 1.2

    total = (
        lead_synergy +
        back_coverage +
        type_diversity +
        weakness_penalty +
        speed_control_bonus +
        protect_bonus +
        fake_out_bonus +
        intimidate_bonus +
        redirection_bonus +
        spread_bonus +
        role_duplicate_penalty +
        offense_bonus +
        defense_bonus
    )

    details = {
        "lead_synergy": lead_synergy,
        "back_coverage": back_coverage,
        "type_diversity": type_diversity,
        "weakness_penalty": weakness_penalty,
        "speed_control_bonus": speed_control_bonus,
        "protect_bonus": protect_bonus,
        "fake_out_bonus": fake_out_bonus,
        "intimidate_bonus": intimidate_bonus,
        "redirection_bonus": redirection_bonus,
        "spread_bonus": spread_bonus,
        "role_duplicate_penalty": role_duplicate_penalty,
        "offense_bonus": offense_bonus,
        "defense_bonus": defense_bonus
    }

    return total, details


def score_combination_v3(
    combination: List[Dict[str, Any]],
    opponent_team: Optional[List[Dict[str, Any]]] = None
) -> Tuple[float, Dict[str, Any]]:
    """
    Score a 4-Pokémon combination jointly with V3 improvements.

    V3 improvements over V2:
    - Better lead pair synergy: explicit evaluation of Fake Out + spread/pressure combos
    - Reduced Protect weighting (0.15 vs 0.3) to avoid over-reliance
    - Lead weakness sharing penalty: -1.5 for shared 2x, -3.0 for shared 4x
    - Back-switch coverage: reward double-target switching potential
    - Speed control synergy: Tailwind/TR + Fake Out + spread bonus
    - Board-wide pressure: weighted by opponent team composition
    - Deterministic: same tie-breaking as V2
    """
    if len(combination) != 4:
        return 0.0, {}

    # Score each Pokemon individually first
    individual_scores = {}
    for p in combination:
        individual_scores[p.get("species", "")] = score_pokemon(p, opponent_team)

    # --- Joint scoring components ---

    # 1. Lead pair synergy (positions 0, 1 in chosen_4 order)
    p1, p2 = combination[0], combination[1]
    s1, s2 = individual_scores[p1.get("species", "")], individual_scores[p2.get("species", "")]

    lead_synergy = 0.0
    # Fake Out + pressure/support. Lead order must not change the score.
    if (
        (s1.fake_out > 0 and (s2.spread_move > 0 or s2.tailwind > 0 or s2.redirection > 0 or s2.trick_room > 0))
        or
        (s2.fake_out > 0 and (s1.spread_move > 0 or s1.tailwind > 0 or s1.redirection > 0 or s1.trick_room > 0))
    ):
        lead_synergy += 2.0  # Increased from 1.5
    elif (
        (s1.intimidate > 0 and (s2.spread_move > 0 or s2.tailwind > 0 or s2.redirection > 0))
        or
        (s2.intimidate > 0 and (s1.spread_move > 0 or s1.tailwind > 0 or s1.redirection > 0))
    ):
        lead_synergy += 1.2  # Increased from 1.0
    elif (
        (s1.redirection > 0 and s2.spread_move > 0)
        or (s2.redirection > 0 and s1.spread_move > 0)
    ):
        lead_synergy += 1.8  # Increased from 1.5

    # Speed control + Fake Out interaction bonus
    has_speed_control = (s1.tailwind > 0 or s1.trick_room > 0 or s2.tailwind > 0 or s2.trick_room > 0)
    has_fake_out = (s1.fake_out > 0 or s2.fake_out > 0)
    if has_speed_control and has_fake_out:
        lead_synergy += 1.0

    # 2. Lead shared weakness penalty (V3: more aggressive)
    lead_types_list = []  # List of type lists for each lead Pokemon
    for p in [p1, p2]:
        lead_types_list.append(get_species_types(p.get("species", "")))

    lead_weakness_penalty = 0.0
    if lead_types_list:
        # For each attacking type, count how many lead Pokemon are weak to it
        for attack_type, multipliers in TYPE_CHART.items():
            weak_count = 0
            for p_types in lead_types_list:
                combined = 1.0
                for defending_type in p_types:
                    combined *= multipliers.get(defending_type, 1.0)
                if combined >= 2.0:
                    weak_count += 1
            if weak_count >= 2:
                # Check if any has 4x (combined >= 4)
                has_4x = False
                for p_types in lead_types_list:
                    combined = 1.0
                    for defending_type in p_types:
                        combined *= multipliers.get(defending_type, 1.0)
                    if combined >= 4.0:
                        has_4x = True
                        break
                if has_4x:
                    lead_weakness_penalty -= 3.0
                else:
                    lead_weakness_penalty -= 1.5

    # 3. Back slot coverage (positions 2, 3) - V3: more comprehensive
    b1, b2 = combination[2], combination[3]
    bs1, bs2 = individual_scores[b1.get("species", "")], individual_scores[b2.get("species", "")]

    back_coverage = 0.0
    # Complementary roles in back
    back_roles = set()
    for s in [bs1, bs2]:
        if s.spread_move > 0: back_roles.add("spread")
        if s.tailwind > 0: back_roles.add("speed_control")
        if s.trick_room > 0: back_roles.add("trick_room")
        if s.redirection > 0: back_roles.add("redirection")
        if s.fake_out > 0: back_roles.add("fake_out")
        if s.type_matchup > 0.7: back_roles.add("offensive")
        if s.weakness_avoidance > 0.7: back_roles.add("defensive")
        if s.intimidate > 0: back_roles.add("intimidate")
    back_coverage = len(back_roles) * 0.6  # Increased from 0.5

    # Back switch coverage: reward ability to pivot
    back_has_pivot = any(
        any("pivot" in move.lower() or "u-turn" in move.lower() or "volt switch" in move.lower() or "parting shot" in move.lower()
            for move in p.get("moves", []))
        for p in [b1, b2]
    )
    if back_has_pivot:
        back_coverage += 0.5

    # 4. Type diversity across all 4
    types = []
    for p in combination:
        types.extend(get_species_types(p.get("species", "")))
    type_diversity = len(set(types)) * 0.3  # max ~18 types * 0.3 = 5.4

    # 5. Weakness spreading across all 4
    weakness_penalty = 0.0
    if len(combination) == 4:
        common_weaknesses = Counter()
        for p in combination:
            p_types = get_species_types(p.get("species", ""))
            for attack_type, multipliers in TYPE_CHART.items():
                combined = 1.0
                for defending_type in p_types:
                    combined *= multipliers.get(defending_type, 1.0)
                if combined >= 2.0:
                    common_weaknesses[attack_type] += 1
        for count in common_weaknesses.values():
            if count >= 3:
                weakness_penalty -= 2.5  # Heavy penalty for 3+ sharing weakness
            elif count == 2:
                weakness_penalty -= 0.7  # Slightly increased from 0.5

    # 6. Speed control presence
    speed_control_bonus = 0.0
    has_tailwind = any(s.tailwind > 0 for s in individual_scores.values())
    has_trick_room = any(s.trick_room > 0 for s in individual_scores.values())
    if has_tailwind: speed_control_bonus += 1.2  # Increased from 1.0
    if has_trick_room: speed_control_bonus += 1.2  # Increased from 1.0

    # 7. Protect availability across board - REDUCED from 0.3 to 0.15
    protect_bonus = sum(1 for s in individual_scores.values() if s.protect > 0) * 0.15

    # 8. Fake Out availability
    fake_out_bonus = sum(1 for s in individual_scores.values() if s.fake_out > 0) * 0.6  # Increased from 0.5

    # 9. Intimidate presence
    intimidate_bonus = sum(1 for s in individual_scores.values() if s.intimidate > 0) * 0.5  # Increased from 0.4

    # 10. Redirection
    redirection_bonus = sum(1 for s in individual_scores.values() if s.redirection > 0) * 0.6  # Increased from 0.5

    # 11. Spread move coverage
    spread_bonus = sum(1 for s in individual_scores.values() if s.spread_move > 0) * 0.5  # Increased from 0.4

    # 12. Duplicated role penalty. One source is useful; stacking same narrow support role has diminishing value.
    role_duplicate_penalty = 0.0
    for attr, penalty in (
        ("fake_out", 0.5),
        ("tailwind", 0.6),
        ("trick_room", 0.6),
        ("redirection", 0.5),
        ("intimidate", 0.3),
    ):
        count = sum(1 for s in individual_scores.values() if getattr(s, attr) > 0)
        if count > 1:
            role_duplicate_penalty -= (count - 1) * penalty

    # 13. Offensive coverage vs opponent
    offense_bonus = 0.0
    if opponent_team:
        for s in individual_scores.values():
            offense_bonus += s.type_matchup * 2.0  # Increased from 1.5

    # 14. Defensive pivot value
    defense_bonus = 0.0
    if opponent_team:
        for s in individual_scores.values():
            defense_bonus += s.weakness_avoidance * 1.5  # Increased from 1.2

    # 15. Board-wide pressure: Synergy between leads and backs
    board_pressure = 0.0
    # Lead Fake Out enables back spread
    if (s1.fake_out > 0 or s2.fake_out > 0) and (bs1.spread_move > 0 or bs2.spread_move > 0):
        board_pressure += 1.0
    # Lead speed control enables back offense
    if ((s1.tailwind > 0 or s1.trick_room > 0 or s2.tailwind > 0 or s2.trick_room > 0) and
        (bs1.type_matchup > 0.7 or bs2.type_matchup > 0.7)):
        board_pressure += 1.0
    # Lead Intimidate + back defensive
    if (s1.intimidate > 0 or s2.intimidate > 0) and (bs1.weakness_avoidance > 0.7 or bs2.weakness_avoidance > 0.7):
        board_pressure += 0.8
    # Lead redirection + back spread
    if (s1.redirection > 0 or s2.redirection > 0) and (bs1.spread_move > 0 or bs2.spread_move > 0):
        board_pressure += 1.2

    total = (
        lead_synergy +
        lead_weakness_penalty +
        back_coverage +
        type_diversity +
        weakness_penalty +
        speed_control_bonus +
        protect_bonus +
        fake_out_bonus +
        intimidate_bonus +
        redirection_bonus +
        spread_bonus +
        role_duplicate_penalty +
        offense_bonus +
        defense_bonus +
        board_pressure
    )

    details = {
        "lead_synergy": lead_synergy,
        "lead_weakness_penalty": lead_weakness_penalty,
        "back_coverage": back_coverage,
        "type_diversity": type_diversity,
        "weakness_penalty": weakness_penalty,
        "speed_control_bonus": speed_control_bonus,
        "protect_bonus": protect_bonus,
        "fake_out_bonus": fake_out_bonus,
        "intimidate_bonus": intimidate_bonus,
        "redirection_bonus": redirection_bonus,
        "spread_bonus": spread_bonus,
        "role_duplicate_penalty": role_duplicate_penalty,
        "offense_bonus": offense_bonus,
        "defense_bonus": defense_bonus,
        "board_pressure": board_pressure,
    }

    return total, details


def evaluate_all_combinations_v3(
    our_team: List[Dict[str, Any]],
    opponent_team: Optional[List[Dict[str, Any]]] = None
) -> List[Tuple[List[Dict], float, Dict]]:
    """Evaluate every 4-Pokemon subset and every 2-lead/2-back partition using V3 scoring.

    The returned four-Pokemon list is ordered as lead_1, lead_2, back_1,
    back_2. With six unique team members this evaluates 15 * 6 = 90 plans.
    """
    results = []

    for subset in combinations(our_team, 4):
        for lead_indices in combinations(range(4), 2):
            lead_index_set = set(lead_indices)
            leads = [subset[i] for i in lead_indices]
            backs = [subset[i] for i in range(4) if i not in lead_index_set]
            ordered_plan = leads + backs
            score, details = score_combination_v3(ordered_plan, opponent_team)
            details = dict(details)
            details["lead_species"] = [p.get("species", "") for p in leads]
            details["back_species"] = [p.get("species", "") for p in backs]
            results.append((ordered_plan, score, details))

    results.sort(
        key=lambda x: (
            -x[1],
            tuple(p.get("species", "").lower() for p in x[0]),
        )
    )
    return results


def evaluate_all_combinations(
    our_team: List[Dict[str, Any]],
    opponent_team: Optional[List[Dict[str, Any]]] = None
) -> List[Tuple[List[Dict], float, Dict]]:
    """Evaluate every 4-Pokemon subset and every 2-lead/2-back partition.

    The returned four-Pokemon list is ordered as lead_1, lead_2, back_1,
    back_2. With six unique team members this evaluates 15 * 6 = 90 plans.
    """
    results = []

    for subset in combinations(our_team, 4):
        for lead_indices in combinations(range(4), 2):
            lead_index_set = set(lead_indices)
            leads = [subset[i] for i in lead_indices]
            backs = [subset[i] for i in range(4) if i not in lead_index_set]
            ordered_plan = leads + backs
            score, details = score_combination(ordered_plan, opponent_team)
            details = dict(details)
            details["lead_species"] = [p.get("species", "") for p in leads]
            details["back_species"] = [p.get("species", "") for p in backs]
            results.append((ordered_plan, score, details))

    results.sort(
        key=lambda x: (
            -x[1],
            tuple(p.get("species", "").lower() for p in x[0]),
        )
    )
    return results


def choose_four_from_six(
    our_team: List[Dict[str, Any]],
    opponent_team: Optional[List[Dict[str, Any]]] = None,
    policy: str = "basic_top4",
    seed: Optional[int] = None
) -> PreviewResult:
    """Select 4 from 6 Pokémon for VGC team preview."""
    if seed is not None:
        random.seed(seed)

    if len(our_team) != 6:
        raise ValueError("Team must have exactly 6 Pokémon")

    if policy == "random":
        chosen_indices = random.sample(range(6), 4)
        chosen = [our_team[i] for i in chosen_indices]
        lead_2 = chosen[:2]
        back_2 = chosen[2:]

        return PreviewResult(
            chosen_4=[p.get("species", "") for p in chosen],
            lead_2=[p.get("species", "") for p in lead_2],
            back_2=[p.get("species", "") for p in back_2],
            scores=[],
            policy="random",
            seed=seed
        )

    elif policy == "basic_top4":
        scores = []
        for p in our_team:
            score = score_pokemon(p, opponent_team)
            scores.append(score)

        scored_pokemon = list(zip(our_team, scores))
        scored_pokemon.sort(key=lambda x: x[1].total, reverse=True)

        chosen = [p for p, s in scored_pokemon[:4]]

        def lead_priority(p, s):
            priority = 0
            if s.fake_out > 0:
                priority += 100
            if s.intimidate > 0:
                priority += 80
            if s.redirection > 0:
                priority += 70
            if s.tailwind > 0:
                priority += 60
            if s.trick_room > 0:
                priority += 50
            if s.protect > 0:
                priority += 30
            priority += s.total
            return priority

        chosen_sorted = sorted(chosen, key=lambda p: lead_priority(p, next(s for pp, s in scored_pokemon if pp == p)), reverse=True)
        lead_2 = chosen_sorted[:2]
        back_2 = chosen_sorted[2:]

        return PreviewResult(
            chosen_4=[p.get("species", "") for p in chosen],
            lead_2=[p.get("species", "") for p in lead_2],
            back_2=[p.get("species", "") for p in back_2],
            scores=[s for _, s in scored_pokemon],
            policy="basic_top4",
            seed=seed
        )

    elif policy == "matchup_top4_v2":
        # Evaluate all 15 subsets and all six lead/back partitions per subset.
        combo_results = evaluate_all_combinations(our_team, opponent_team)

        # The returned plan is already ordered lead_1, lead_2, back_1, back_2.
        best_plan, best_score, best_details = combo_results[0]

        scores = [score_pokemon(p, opponent_team) for p in best_plan]
        lead_2 = best_plan[:2]
        back_2 = best_plan[2:]

        return PreviewResult(
            chosen_4=[p.get("species", "") for p in best_plan],
            lead_2=[p.get("species", "") for p in lead_2],
            back_2=[p.get("species", "") for p in back_2],
            scores=scores,
            policy="matchup_top4_v2",
            seed=seed
        )

    elif policy == "matchup_top4_v3":
        # Evaluate all 90 plans (15 subsets * 6 lead/back partitions) with V3 scoring.
        combo_results = evaluate_all_combinations_v3(our_team, opponent_team)

        # The returned plan is already ordered lead_1, lead_2, back_1, back_2.
        best_plan, best_score, best_details = combo_results[0]

        scores = [score_pokemon(p, opponent_team) for p in best_plan]
        lead_2 = best_plan[:2]
        back_2 = best_plan[2:]

        return PreviewResult(
            chosen_4=[p.get("species", "") for p in best_plan],
            lead_2=[p.get("species", "") for p in lead_2],
            back_2=[p.get("species", "") for p in back_2],
            scores=scores,
            policy="matchup_top4_v3",
            seed=seed
        )

    elif policy == "learned_preview_v3a":
        # Phase V3a: linear-scored baseline.
        # Loads the model JSON. If missing, raises
        # FileNotFoundError so the caller can decide
        # to fallback in explicit test mode only.
        from vgc2026_phaseV3a_learn_preview import (
            choose_plan_with_scorer,
            load_model,
        )
        import os
        from vgc2026_phaseV3a_learn_preview import (
            DEFAULT_MODEL_PATH,
        )
        if not os.path.isfile(DEFAULT_MODEL_PATH):
            raise FileNotFoundError(
                f"learned_preview_v3a model not found at "
                f"{DEFAULT_MODEL_PATH}. Train with "
                f"vgc2026_phaseV3a_learn_preview.py first."
            )
        model = load_model(DEFAULT_MODEL_PATH)
        weights = model["weights"]
        bias = model["bias"]
        feature_names = model["feature_names"]
        chosen, lead_2, back_2 = choose_plan_with_scorer(
            our_team,
            opponent_team,
            weights,
            bias,
            feature_names,
        )
        return PreviewResult(
            chosen_4=list(chosen),
            lead_2=list(lead_2),
            back_2=list(back_2),
            scores=[],
            policy="learned_preview_v3a",
            seed=seed
        )

    elif policy == "learned_preview_v3a1":
        # Phase V3a.1: averaged perceptron + L2 model.
        # Same scoring as V3a but uses the V3a.1
        # artifact. Opt-in only: no fallback to V3.
        from vgc2026_phaseV3a_learn_preview import (
            choose_plan_with_scorer,
            load_model,
            DEFAULT_V3A1_MODEL_PATH,
        )
        import os as _os_v3a1
        if not _os_v3a1.path.isfile(DEFAULT_V3A1_MODEL_PATH):
            raise FileNotFoundError(
                f"learned_preview_v3a1 model not found at "
                f"{DEFAULT_V3A1_MODEL_PATH}. Train with "
                f"vgc2026_phaseV3a_learn_preview.py first."
            )
        model = load_model(DEFAULT_V3A1_MODEL_PATH)
        weights = model["weights"]
        bias = model["bias"]
        feature_names = model["feature_names"]
        chosen, lead_2, back_2 = choose_plan_with_scorer(
            our_team,
            opponent_team,
            weights,
            bias,
            feature_names,
        )
        return PreviewResult(
            chosen_4=list(chosen),
            lead_2=list(lead_2),
            back_2=list(back_2),
            scores=[],
            policy="learned_preview_v3a1",
            seed=seed
        )

    elif policy == "learned_preview_v3c1":
        # Phase V3c.1: averaged perceptron trained on
        # the V3c balanced VGC dataset with V3b
        # opponent-adaptive features. Opt-in only.
        # V3c.1 training gates all passed (mean
        # val_acc=0.602 across 30 seeds; beats V3 on
        # 93% of splits; overfit gap 0.098). Adoption
        # is BLOCKED: this is for a 20-pair reality
        # check, not production.
        from vgc2026_phaseV3a_learn_preview import (
            choose_plan_with_scorer,
            load_model,
        )
        from vgc2026_phaseV3c1_train import V3C1_MODEL_PATH
        import os as _os_v3c1
        if not _os_v3c1.path.isfile(V3C1_MODEL_PATH):
            raise FileNotFoundError(
                f"learned_preview_v3c1 model not found at "
                f"{V3C1_MODEL_PATH}. Train with "
                f"vgc2026_phaseV3c1_train.py first."
            )
        model = load_model(V3C1_MODEL_PATH)
        weights = model["weights"]
        bias = model["bias"]
        feature_names = model["feature_names"]
        chosen, lead_2, back_2 = choose_plan_with_scorer(
            our_team,
            opponent_team,
            weights,
            bias,
            feature_names,
        )
        return PreviewResult(
            chosen_4=list(chosen),
            lead_2=list(lead_2),
            back_2=list(back_2),
            scores=[],
            policy="learned_preview_v3c1",
            seed=seed
        )

    elif policy == "learned_preview_v3d1":
        # Phase PREVIEW-5: averaged perceptron trained on
        # the V3c balanced VGC dataset with V3b + V3d.1
        # features (30 features total). Opt-in only.
        # Default matchup_top4_v3 is unchanged. No model
        # artifact exists yet; this branch is inert unless
        # the model file is created by an explicit
        # training run.
        from vgc2026_phaseV3a_learn_preview import (
            choose_plan_with_scorer,
            load_model,
        )
        from vgc2026_phaseV3d1_train import (
            V3D1_MODEL_PATH,
            V3D1_SCHEMA_VERSION,
        )
        import os as _os_v3d1
        if not _os_v3d1.path.isfile(V3D1_MODEL_PATH):
            raise FileNotFoundError(
                f"learned_preview_v3d1 model not found at "
                f"{V3D1_MODEL_PATH}. Train with "
                f"vgc2026_phaseV3d1_train.py first."
            )
        model = load_model(V3D1_MODEL_PATH)
        schema_version = (
            model.get("metadata", {}).get("schema_version")
        )
        if schema_version != V3D1_SCHEMA_VERSION:
            raise ValueError(
                f"Incompatible schema version: "
                f"{schema_version!r}. Expected "
                f"{V3D1_SCHEMA_VERSION!r}."
            )
        weights = model["weights"]
        bias = model["bias"]
        feature_names = model["feature_names"]
        chosen, lead_2, back_2 = choose_plan_with_scorer(
            our_team,
            opponent_team,
            weights,
            bias,
            feature_names,
        )
        return PreviewResult(
            chosen_4=list(chosen),
            lead_2=list(lead_2),
            back_2=list(back_2),
            scores=[],
            policy="learned_preview_v3d1",
            seed=seed
        )

    else:
        raise ValueError(f"Unknown policy: {policy}")


def validate_preview(our_team: List[Dict[str, Any]], result: PreviewResult) -> Tuple[bool, List[str]]:
    """Validate that the preview selection is valid."""
    errors = []

    our_species = {p.get("species", "") for p in our_team}
    chosen_species = set(result.chosen_4)

    if not chosen_species.issubset(our_species):
        errors.append(f"Chosen species not in team: {chosen_species - our_species}")

    if len(result.chosen_4) != 4:
        errors.append(f"Must choose exactly 4, got {len(result.chosen_4)}")

    lead_species = set(result.lead_2)
    if not lead_species.issubset(chosen_species):
        errors.append(f"Lead species not in chosen 4: {lead_species - chosen_species}")

    if len(result.lead_2) != 2:
        errors.append(f"Must have exactly 2 leads, got {len(result.lead_2)}")

    back_species = set(result.back_2)
    if not back_species.issubset(chosen_species):
        errors.append(f"Back species not in chosen 4: {back_species - chosen_species}")

    if len(result.back_2) != 2:
        errors.append(f"Must have exactly 2 back, got {len(result.back_2)}")

    all_chosen = result.lead_2 + result.back_2
    if len(all_chosen) != len(set(all_chosen)):
        errors.append("Duplicate Pokémon in lead/back selection")

    if len(all_chosen) != 4:
        errors.append(f"Lead + back must total 4, got {len(all_chosen)}")

    return len(errors) == 0, errors


if __name__ == "__main__":
    # Test with sample team
    test_team = [
        {"species": "Incineroar", "ability": "Intimidate", "moves": ["Fake Out", "Flare Blitz", "Parting Shot", "Throat Chop"]},
        {"species": "Garchomp", "ability": "Rough Skin", "moves": ["Earthquake", "Rock Slide", "Dragon Claw", "Protect"]},
        {"species": "Rillaboom", "ability": "Grassy Surge", "moves": ["Fake Out", "Grassy Glide", "High Horsepower", "U-turn"]},
        {"species": "Tornadus", "ability": "Prankster", "moves": ["Tailwind", "Taunt", "Hurricane", "Focus Blast"]},
        {"species": "Flutter Mane", "ability": "Protosynthesis", "moves": ["Moonblast", "Shadow Ball", "Thunderbolt", "Protect"]},
        {"species": "Iron Hands", "ability": "Quark Drive", "moves": ["Fake Out", "Wild Charge", "Drain Punch", "Protect"]},
    ]

    result = choose_four_from_six(test_team, policy="random", seed=42)
    print("Random policy:")
    print(f"  Chosen: {result.chosen_4}")
    print(f"  Lead: {result.lead_2}")
    print(f"  Back: {result.back_2}")

    result = choose_four_from_six(test_team, policy="basic_top4", seed=42)
    print("\nBasic top4 policy:")
    print(f"  Chosen: {result.chosen_4}")
    print(f"  Lead: {result.lead_2}")
    print(f"  Back: {result.back_2}")
    for s in result.scores:
        print(f"  {s.species}: total={s.total:.2f} (fake_out={s.fake_out}, intimidate={s.intimidate}, tailwind={s.tailwind}, redirection={s.redirection}, spread={s.spread_move}, protect={s.protect}, type_matchup={s.type_matchup:.2f}, weakness_avoidance={s.weakness_avoidance:.2f}) role={s.role}")

    result = choose_four_from_six(test_team, policy="matchup_top4_v2", seed=42)
    print("\nMatchup top4 v2 policy:")
    print(f"  Chosen: {result.chosen_4}")
    print(f"  Lead: {result.lead_2}")
    print(f"  Back: {result.back_2}")
    for s in result.scores:
        print(f"  {s.species}: total={s.total:.2f} (fake_out={s.fake_out}, intimidate={s.intimidate}, tailwind={s.tailwind}, redirection={s.redirection}, spread={s.spread_move}, protect={s.protect}, type_matchup={s.type_matchup:.2f}, weakness_avoidance={s.weakness_avoidance:.2f}) role={s.role}")

    # Test with opponent
    opp_team = [
        {"species": "Rillaboom", "moves": []},
        {"species": "Iron Hands", "moves": []},
        {"species": "Flutter Mane", "moves": []},
        {"species": "Incineroar", "moves": []},
        {"species": "Garchomp", "moves": []},
        {"species": "Tornadus", "moves": []},
    ]
    result = choose_four_from_six(test_team, opponent_team=opp_team, policy="basic_top4", seed=42)
    print("\nWith opponent (basic_top4):")
    print(f"  Chosen: {result.chosen_4}")
    print(f"  Lead: {result.lead_2}")
    print(f"  Back: {result.back_2}")

    result = choose_four_from_six(test_team, opponent_team=opp_team, policy="matchup_top4_v2", seed=42)
    print("\nWith opponent (matchup_top4_v2):")
    print(f"  Chosen: {result.chosen_4}")
    print(f"  Lead: {result.lead_2}")
    print(f"  Back: {result.back_2}")
