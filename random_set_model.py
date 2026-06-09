#!/usr/bin/env python3
"""
random_set_model.py

Phase 5.1: Random-Set-Aware Opponent Modeling engine.
Loads species data extracted from the local Pokémon Showdown
data/random-battles/gen9/doubles-sets.json and provides safe
prediction helpers for use during battle decisions.

All helpers return neutral/False safely on missing data — they
will never crash the battle loop.
"""
import json
import logging
import os
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def normalize_species(name: str) -> str:
    """Convert a species name to a normalized lowercase alphanum ID."""
    if not name:
        return ""
    if not isinstance(name, str):
        try:
            name = str(name)
        except Exception:
            return ""
    return "".join(c.lower() for c in name if c.isalnum())


def normalize_move(name: str) -> str:
    """Convert a move name to a normalized lowercase alphanum ID."""
    if not name:
        return ""
    if not isinstance(name, str):
        try:
            name = str(name)
        except Exception:
            return ""
    return "".join(c.lower() for c in name if c.isalnum())


def normalize_ability(name: str) -> str:
    """Convert an ability name to a normalized lowercase alphanum ID."""
    if not name:
        return ""
    if not isinstance(name, str):
        try:
            name = str(name)
        except Exception:
            return ""
    return "".join(c.lower() for c in name if c.isalnum())


def normalize_item(name: str) -> str:
    """Convert an item name to a normalized lowercase alphanum ID."""
    if not name:
        return ""
    if not isinstance(name, str):
        try:
            name = str(name)
        except Exception:
            return ""
    return "".join(c.lower() for c in name if c.isalnum())


# ---------------------------------------------------------------------------
# Move classification sets (for prediction helpers)
# ---------------------------------------------------------------------------

PROTECT_MOVES = frozenset([
    "protect", "detect", "spikyshield", "kingsshield", "banefulbunker",
    "silktrap", "burningbulwark", "wideguard", "quickguard",
])

FAKE_OUT_MOVES = frozenset(["fakeout"])

PRIORITY_MOVES = frozenset([
    "extremespeed", "feint", "fakeout", "suckerpunch", "machpunch",
    "bulletpunch", "vacuumwave", "iceshard", "aquajet", "shadowsneak",
    "watershuriken", "accelerock", "grassyglide", "jetpunch", "quickattack",
    "firstimpression", "upperhand",
])

SPREAD_MOVES = frozenset([
    "earthquake", "rockslide", "blizzard", "heatwave", "surf",
    "muddywater", "hypervoice", "dazzlinggleam", "expandingforce",
    "makeitrain", "snarl", "electroweb", "icywind", "discharge",
    "eruption", "waterspout", "bleakwindstorm", "astralbarrage",
    "strugglebug",
])

SETUP_MOVES = frozenset([
    "swordsdance", "nastyplot", "dragondance", "calmmind",
    "quiverdance", "shellsmash", "bulkup", "irondefense", "cosmicpower",
    "agility", "autotomize", "rockpolish", "shiftgear", "victorydance",
    "workup", "growth", "tidyup", "noretreat",
])

SPEED_CONTROL_MOVES = frozenset([
    "tailwind", "trickroom", "icywind", "electroweb", "thunderwave",
    "nuzzle", "glare", "lowsweep", "quash",
])


# ---------------------------------------------------------------------------
# RandomSetQueryEngine
# ---------------------------------------------------------------------------

class RandomSetQueryEngine:
    """
    Loads the extracted gen9randomdoublesbattle set database and provides
    safe prediction helpers for all species in the pool.

    Data schema expected in the JSON:
    {
      "format": "gen9randomdoublesbattle",
      "source": "local_pokemon_showdown_random_sets",
      "pokemon": {
        "speciesid": {
          "moves": { "moveid": probability, ... },
          "abilities": { "abilityid": probability, ... },
          "items": { "itemid": probability, ... }
        }
      }
    }
    """

    def __init__(self, data_path: Optional[str] = None):
        self.data: Dict = {}
        self._move_threshold_cache: Dict = {}
        if data_path:
            self.load_from_json(data_path)

    def load_from_json(self, path: str) -> None:
        """Load species data from a pre-built JSON database."""
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    self.data = json.load(f)
                count = len(self.data.get("pokemon", {}))
                logger.info(f"RandomSetQueryEngine: loaded {count} species from {path}")
            else:
                logger.warning(f"RandomSetQueryEngine: path {path} does not exist.")
        except Exception as e:
            logger.error(f"RandomSetQueryEngine: error loading {path}: {e}")
            self.data = {}

    def save_json(self, path: str) -> None:
        """Save the current database to a JSON file."""
        try:
            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
            with open(path, "w") as f:
                json.dump(self.data, f, indent=2)
            logger.info(f"RandomSetQueryEngine: saved database to {path}")
        except Exception as e:
            logger.error(f"RandomSetQueryEngine: error saving to {path}: {e}")

    def get_species_entry(self, species: str) -> dict:
        """Return the data entry for a species. Returns empty dict if not found."""
        norm = normalize_species(species)
        if not norm:
            return {}
        try:
            return self.data.get("pokemon", {}).get(norm, {})
        except Exception:
            return {}

    def is_species_known(self, species: str) -> bool:
        """Return True if the species is in our database."""
        return bool(self.get_species_entry(species))

    def predict_moves(
        self,
        species: str,
        revealed_moves: Optional[List[str]] = None,
    ) -> List[Tuple[str, float]]:
        """
        Return a list of (moveid, probability) for unrevealed moves.
        Revealed moves are excluded from the prediction list.
        """
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
            logger.error(f"RandomSetQueryEngine.predict_moves({species}): {e}")
            return []

    def predict_abilities(self, species: str) -> List[Tuple[str, float]]:
        """Return a list of (abilityid, probability) for this species."""
        entry = self.get_species_entry(species)
        if not entry:
            return []
        try:
            abilities = entry.get("abilities", {})
            pred = [(normalize_ability(ab), float(prob)) for ab, prob in abilities.items()]
            pred.sort(key=lambda x: x[1], reverse=True)
            return pred
        except Exception as e:
            logger.error(f"RandomSetQueryEngine.predict_abilities({species}): {e}")
            return []

    def predict_items(self, species: str) -> List[Tuple[str, float]]:
        """Return a list of (itemid, probability) for this species."""
        entry = self.get_species_entry(species)
        if not entry:
            return []
        try:
            items = entry.get("items", {})
            pred = [(normalize_item(item), float(prob)) for item, prob in items.items()]
            pred.sort(key=lambda x: x[1], reverse=True)
            return pred
        except Exception as e:
            logger.error(f"RandomSetQueryEngine.predict_items({species}): {e}")
            return []

    # -----------------------------------------------------------------------
    # Low-level move probability helper
    # -----------------------------------------------------------------------

    def _move_prob(
        self,
        species: str,
        move_id: str,
        revealed_moves: Optional[List[str]],
        threshold: float,
    ) -> Tuple[bool, float, str]:
        """
        Return (has_move, probability, reason) for a specific move.
        If the move has been revealed, returns (True, 1.0, 'revealed').
        """
        try:
            norm_move = normalize_move(move_id)
            revealed_set = set(normalize_move(m) for m in (revealed_moves or []))
            if norm_move in revealed_set:
                return True, 1.0, "revealed"

            entry = self.get_species_entry(species)
            if not entry:
                return False, 0.0, "species not in database"

            prob = float(entry.get("moves", {}).get(norm_move, 0.0))
            if prob >= threshold:
                return True, prob, f"predicted (prob={prob:.2f})"
            return False, prob, f"below threshold (prob={prob:.2f})"
        except Exception as e:
            logger.error(f"RandomSetQueryEngine._move_prob({species}/{move_id}): {e}")
            return False, 0.0, "error"

    def _any_move_prob(
        self,
        species: str,
        move_set: frozenset,
        revealed_moves: Optional[List[str]],
        threshold: float,
    ) -> Tuple[bool, float, str]:
        """
        Check if ANY move in move_set has probability >= threshold.
        Returns the result for the highest-probability matching move.
        """
        max_prob = 0.0
        best_reason = "below threshold"
        has_any = False

        for move_id in move_set:
            ok, prob, reason = self._move_prob(species, move_id, revealed_moves, threshold)
            if ok:
                has_any = True
                if prob > max_prob:
                    max_prob = prob
                    best_reason = f"{move_id}: {reason}"
            else:
                if prob > max_prob:
                    max_prob = prob
                    best_reason = f"{move_id}: {reason}"

        return has_any, max_prob, best_reason

    # -----------------------------------------------------------------------
    # High-level prediction helpers
    # -----------------------------------------------------------------------

    def likely_has_protect(
        self,
        species: str,
        revealed_moves: Optional[List[str]] = None,
        threshold: float = 0.30,
    ) -> Tuple[bool, float, str]:
        """Return (True, prob, reason) if this species likely has a Protect variant."""
        return self._any_move_prob(species, PROTECT_MOVES, revealed_moves, threshold)

    def likely_has_fake_out(
        self,
        species: str,
        revealed_moves: Optional[List[str]] = None,
        threshold: float = 0.30,
    ) -> Tuple[bool, float, str]:
        """Return (True, prob, reason) if this species likely has Fake Out."""
        return self._any_move_prob(species, FAKE_OUT_MOVES, revealed_moves, threshold)

    def likely_has_priority(
        self,
        species: str,
        revealed_moves: Optional[List[str]] = None,
        threshold: float = 0.30,
    ) -> Tuple[bool, float, str]:
        """Return (True, prob, reason) if this species likely has a priority move."""
        return self._any_move_prob(species, PRIORITY_MOVES, revealed_moves, threshold)

    def likely_has_spread_move(
        self,
        species: str,
        revealed_moves: Optional[List[str]] = None,
        threshold: float = 0.30,
    ) -> Tuple[bool, float, str]:
        """Return (True, prob, reason) if this species likely has a spread move."""
        return self._any_move_prob(species, SPREAD_MOVES, revealed_moves, threshold)

    def likely_has_setup_move(
        self,
        species: str,
        revealed_moves: Optional[List[str]] = None,
        threshold: float = 0.30,
    ) -> Tuple[bool, float, str]:
        """Return (True, prob, reason) if this species likely has a setup move."""
        return self._any_move_prob(species, SETUP_MOVES, revealed_moves, threshold)

    def likely_has_speed_control(
        self,
        species: str,
        revealed_moves: Optional[List[str]] = None,
        threshold: float = 0.30,
    ) -> Tuple[bool, float, str]:
        """Return (True, prob, reason) if this species likely has a speed control move."""
        return self._any_move_prob(species, SPEED_CONTROL_MOVES, revealed_moves, threshold)

    # -----------------------------------------------------------------------
    # Database stats helpers
    # -----------------------------------------------------------------------

    def species_count(self) -> int:
        """Return total number of species in the database."""
        return len(self.data.get("pokemon", {}))

    def total_move_entries(self) -> int:
        """Return total number of (species, move) entries in the database."""
        return sum(len(e.get("moves", {})) for e in self.data.get("pokemon", {}).values())

    def total_ability_entries(self) -> int:
        """Return total number of (species, ability) entries in the database."""
        return sum(len(e.get("abilities", {})) for e in self.data.get("pokemon", {}).values())

    def total_item_entries(self) -> int:
        """Return total number of (species, item) entries in the database."""
        return sum(len(e.get("items", {})) for e in self.data.get("pokemon", {}).values())
