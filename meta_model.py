#!/usr/bin/env python3
"""
meta_model.py

Opponent modeling engine for Doubles Phase 5.
Uses local cached Smogon stats files to estimate unseen opponent moves,
abilities, items, and features.
"""
import json
import logging
import os
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Standard move types mapping for super-effective coverage checks
MOVE_TYPES = {
    # Fire
    "flareblitz": "FIRE", "heatwave": "FIRE", "overheat": "FIRE", "flamethrower": "FIRE", "fireblast": "FIRE", "eruption": "FIRE", "burningjealousy": "FIRE",
    # Water
    "surgingstrikes": "WATER", "muddywater": "WATER", "surf": "WATER", "scald": "WATER", "hydropump": "WATER", "aquajet": "WATER", "liquidation": "WATER", "waterspout": "WATER", "wavecrash": "WATER",
    # Grass
    "grassyglide": "GRASS", "woodhammer": "GRASS", "hornleech": "GRASS", "leafstorm": "GRASS", "pollenpuff": "BUG", "powerwhip": "GRASS", "gigadrain": "GRASS", "energyball": "GRASS",
    # Electric
    "thunderbolt": "ELECTRIC", "electroweb": "ELECTRIC", "voltswitch": "ELECTRIC", "discharge": "ELECTRIC", "thunder": "ELECTRIC", "wildcharge": "ELECTRIC",
    # Ice
    "blizzard": "ICE", "icebeam": "ICE", "iceshard": "ICE", "iciclecrash": "ICE",
    # Fighting
    "closecombat": "FIGHTING", "drainpunch": "FIGHTING", "sacredsword": "FIGHTING", "vacuumwave": "FIGHTING", "aurasphere": "FIGHTING", "superpower": "FIGHTING",
    # Ground
    "earthquake": "GROUND", "stompingtantrum": "GROUND", "earthpower": "GROUND", "highhorsepower": "GROUND", "precipiceblades": "GROUND",
    # Flying
    "bleakwindstorm": "FLYING", "hurricane": "FLYING", "bravebird": "FLYING", "airslash": "FLYING",
    # Psychic
    "expandingforce": "PSYCHIC", "psychic": "PSYCHIC", "psyshock": "PSYCHIC", "zenheadbutt": "PSYCHIC",
    # Bug
    "bugbuzz": "BUG", "uturn": "BUG", "strugglebug": "BUG",
    # Rock
    "rockslide": "ROCK", "stoneedge": "ROCK", "powergem": "ROCK",
    # Ghost
    "shadowball": "GHOST", "shadowsneak": "GHOST", "astralbarrage": "GHOST", "poltergeist": "GHOST",
    # Dragon
    "dracometeor": "DRAGON", "dragonpulse": "DRAGON", "outrage": "DRAGON",
    # Dark
    "knockoff": "DARK", "suckerpunch": "DARK", "snarl": "DARK", "foulplay": "DARK", "darkpulse": "DARK", "wickedblow": "DARK",
    # Steel
    "makeitrain": "STEEL", "flashcannon": "STEEL", "ironhead": "STEEL", "gigatonhammer": "STEEL",
    # Fairy
    "moonblast": "FAIRY", "dazzlinggleam": "FAIRY", "playrough": "FAIRY", "spiritbreak": "FAIRY",
}


def normalize_species(name: str) -> str:
    if not name:
        return ""
    if not isinstance(name, str):
        try:
            name = str(name)
        except Exception:
            return ""
    return "".join(c.lower() for c in name if c.isalnum())


def normalize_move(name: str) -> str:
    if not name:
        return ""
    if not isinstance(name, str):
        try:
            name = str(name)
        except Exception:
            return ""
    return "".join(c.lower() for c in name if c.isalnum())


def normalize_ability(name: str) -> str:
    if not name:
        return ""
    if not isinstance(name, str):
        try:
            name = str(name)
        except Exception:
            return ""
    return "".join(c.lower() for c in name if c.isalnum())


def normalize_item(name: str) -> str:
    if not name:
        return ""
    if not isinstance(name, str):
        try:
            name = str(name)
        except Exception:
            return ""
    return "".join(c.lower() for c in name if c.isalnum())


class MetaQueryEngine:
    def __init__(self, data_path: Optional[str] = None):
        self.data: Dict = {}
        if data_path:
            self.load_data(data_path)

    def load_data(self, path: str) -> None:
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    self.data = json.load(f)
                logger.info(f"Successfully loaded meta stats from {path}")
            else:
                logger.warning(f"Meta stats path {path} does not exist.")
        except Exception as e:
            logger.error(f"Error loading meta stats from {path}: {e}")
            self.data = {}

    def get_species_entry(self, species: str) -> dict:
        norm = normalize_species(species)
        if not norm:
            return {}
        try:
            pokemon_data = self.data.get("pokemon", {})
            return pokemon_data.get(norm, {})
        except Exception:
            return {}

    def predict_moves(self, species: str, revealed_moves: Optional[List[str]] = None) -> List[Tuple[str, float]]:
        entry = self.get_species_entry(species)
        if not entry:
            return []
        try:
            moves = entry.get("moves", {})
            revealed_set = set(normalize_move(m) for m in (revealed_moves or []))
            pred = []
            for move_id, prob in moves.items():
                norm_move = normalize_move(move_id)
                if norm_move not in revealed_set:
                    pred.append((norm_move, float(prob)))
            pred.sort(key=lambda x: x[1], reverse=True)
            return pred
        except Exception as e:
            logger.error(f"Error in predict_moves for {species}: {e}")
            return []

    def predict_abilities(self, species: str) -> List[Tuple[str, float]]:
        entry = self.get_species_entry(species)
        if not entry:
            return []
        try:
            abilities = entry.get("abilities", {})
            pred = [(normalize_ability(ab), float(prob)) for ab, prob in abilities.items()]
            pred.sort(key=lambda x: x[1], reverse=True)
            return pred
        except Exception as e:
            logger.error(f"Error in predict_abilities for {species}: {e}")
            return []

    def predict_items(self, species: str) -> List[Tuple[str, float]]:
        entry = self.get_species_entry(species)
        if not entry:
            return []
        try:
            items = entry.get("items", {})
            pred = [(normalize_item(item), float(prob)) for item, prob in items.items()]
            pred.sort(key=lambda x: x[1], reverse=True)
            return pred
        except Exception as e:
            logger.error(f"Error in predict_items for {species}: {e}")
            return []

    # Prediction Helpers
    def likely_has_move(self, species: str, move_id: str, revealed_moves: Optional[List[str]] = None, threshold: float = 0.30) -> Tuple[bool, float, str]:
        try:
            norm_move = normalize_move(move_id)
            revealed_set = set(normalize_move(m) for m in (revealed_moves or []))
            if norm_move in revealed_set:
                return True, 1.0, "revealed"

            entry = self.get_species_entry(species)
            if not entry:
                return False, 0.0, "missing species data"

            moves = entry.get("moves", {})
            prob = float(moves.get(norm_move, 0.0))
            if prob >= threshold:
                return True, prob, f"predicted (prob={prob:.2f})"
            return False, prob, f"below threshold (prob={prob:.2f})"
        except Exception as e:
            logger.error(f"Error in likely_has_move for {species}/{move_id}: {e}")
            return False, 0.0, "error"

    def likely_has_protect(self, species: str, revealed_moves: Optional[List[str]] = None, threshold: float = 0.30) -> Tuple[bool, float, str]:
        protect_moves = ["protect", "detect", "spikyshield", "kingsshield", "banefulbunker", "silktrap"]
        max_prob = 0.0
        best_reason = "below threshold"
        has_protect = False

        for pm in protect_moves:
            ok, prob, reason = self.likely_has_move(species, pm, revealed_moves, threshold)
            if ok:
                has_protect = True
                if prob > max_prob:
                    max_prob = prob
                    best_reason = f"{pm} {reason}"
            else:
                if prob > max_prob:
                    max_prob = prob
                    best_reason = f"{pm} {reason}"

        if has_protect:
            return True, max_prob, best_reason
        return False, max_prob, best_reason

    def likely_has_fake_out(self, species: str, revealed_moves: Optional[List[str]] = None, threshold: float = 0.30) -> Tuple[bool, float, str]:
        return self.likely_has_move(species, "fakeout", revealed_moves, threshold)

    def likely_has_priority(self, species: str, revealed_moves: Optional[List[str]] = None, threshold: float = 0.30) -> Tuple[bool, float, str]:
        priority_moves = [
            "extremespeed", "feint", "fakeout", "suckerpunch", "machpunch",
            "bulletpunch", "vacuumwave", "iceshard", "aquajet", "shadowsneak",
            "watershuriken", "accelerock", "grassyglide", "jetpunch"
        ]
        max_prob = 0.0
        best_reason = "below threshold"
        has_prio = False

        for pm in priority_moves:
            ok, prob, reason = self.likely_has_move(species, pm, revealed_moves, threshold)
            if ok:
                has_prio = True
                if prob > max_prob:
                    max_prob = prob
                    best_reason = f"{pm} {reason}"
            else:
                if prob > max_prob:
                    max_prob = prob
                    best_reason = f"{pm} {reason}"

        if has_prio:
            return True, max_prob, best_reason
        return False, max_prob, best_reason

    def likely_has_spread_move(self, species: str, revealed_moves: Optional[List[str]] = None, threshold: float = 0.30) -> Tuple[bool, float, str]:
        spread_moves = [
            "earthquake", "rockslide", "blizzard", "heatwave", "surf",
            "muddywater", "hypervoice", "dazzlinggleam", "expandingforce",
            "makeitrain", "snarl", "electroweb", "icywind", "discharge",
            "eruption", "waterspout"
        ]
        max_prob = 0.0
        best_reason = "below threshold"
        has_spread = False

        for sm in spread_moves:
            ok, prob, reason = self.likely_has_move(species, sm, revealed_moves, threshold)
            if ok:
                has_spread = True
                if prob > max_prob:
                    max_prob = prob
                    best_reason = f"{sm} {reason}"
            else:
                if prob > max_prob:
                    max_prob = prob
                    best_reason = f"{sm} {reason}"

        if has_spread:
            return True, max_prob, best_reason
        return False, max_prob, best_reason

    def likely_has_setup_move(self, species: str, revealed_moves: Optional[List[str]] = None, threshold: float = 0.30) -> Tuple[bool, float, str]:
        setup_moves = [
            "swordsdance", "nastyplot", "dragondance", "calmmind",
            "quiverdance", "shellsmash", "bulkup", "irondefense", "cosmicpower"
        ]
        max_prob = 0.0
        best_reason = "below threshold"
        has_setup = False

        for sm in setup_moves:
            ok, prob, reason = self.likely_has_move(species, sm, revealed_moves, threshold)
            if ok:
                has_setup = True
                if prob > max_prob:
                    max_prob = prob
                    best_reason = f"{sm} {reason}"
            else:
                if prob > max_prob:
                    max_prob = prob
                    best_reason = f"{sm} {reason}"

        if has_setup:
            return True, max_prob, best_reason
        return False, max_prob, best_reason

    def likely_has_speed_control(self, species: str, revealed_moves: Optional[List[str]] = None, threshold: float = 0.30) -> Tuple[bool, float, str]:
        sc_moves = ["tailwind", "trickroom", "icywind", "electroweb", "thunderwave", "nuzzle", "glare"]
        max_prob = 0.0
        best_reason = "below threshold"
        has_sc = False

        for sm in sc_moves:
            ok, prob, reason = self.likely_has_move(species, sm, revealed_moves, threshold)
            if ok:
                has_sc = True
                if prob > max_prob:
                    max_prob = prob
                    best_reason = f"{sm} {reason}"
            else:
                if prob > max_prob:
                    max_prob = prob
                    best_reason = f"{sm} {reason}"

        if has_sc:
            return True, max_prob, best_reason
        return False, max_prob, best_reason

    def likely_has_super_effective_coverage(self, species: str, target_pokemon, revealed_moves: Optional[List[str]] = None, threshold: float = 0.30) -> Tuple[bool, float, str]:
        if not target_pokemon:
            return False, 0.0, "missing target"
        try:
            entry = self.get_species_entry(species)
            if not entry:
                return False, 0.0, "missing species data"

            moves = entry.get("moves", {})
            revealed_set = set(normalize_move(m) for m in (revealed_moves or []))

            # Combine revealed moves of the species and high-probability predicted moves
            candidate_moves = []
            for m_id in revealed_set:
                candidate_moves.append((m_id, 1.0, "revealed"))

            for m_id, prob in moves.items():
                norm_m = normalize_move(m_id)
                if norm_m not in revealed_set:
                    candidate_moves.append((norm_m, float(prob), f"predicted (prob={prob:.2f})"))

            max_prob = 0.0
            best_reason = "no super-effective move"
            has_coverage = False

            for m_id, prob, source in candidate_moves:
                move_type = MOVE_TYPES.get(m_id)
                if not move_type:
                    continue

                # Query type effectiveness multiplier
                try:
                    mult = target_pokemon.damage_multiplier(move_type)
                except Exception:
                    mult = 1.0

                if mult >= 2.0:
                    if source == "revealed" or prob >= threshold:
                        has_coverage = True
                        if prob > max_prob:
                            max_prob = prob
                            best_reason = f"{m_id} ({move_type}) {source} deals {mult:.1f}x"
                    else:
                        if prob > max_prob:
                            max_prob = prob
                            best_reason = f"{m_id} ({move_type}) below threshold deals {mult:.1f}x"

            if has_coverage:
                return True, max_prob, best_reason
            return False, max_prob, best_reason
        except Exception as e:
            logger.error(f"Error in likely_has_super_effective_coverage for {species}: {e}")
            return False, 0.0, "error"
