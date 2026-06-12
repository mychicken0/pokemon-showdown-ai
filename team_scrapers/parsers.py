#!/usr/bin/env python3
"""
Phase T3 - Team Parsers
Parsers for limitless, rk9, pokepaste formats
"""

import json
import re
from pathlib import Path
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from abc import ABC, abstractmethod

@dataclass
class Pokemon:
    species: str
    nickname: Optional[str] = None
    gender: Optional[str] = None
    level: int = 50
    item: Optional[str] = None
    ability: Optional[str] = None
    tera_type: Optional[str] = None
    nature: Optional[str] = None
    evs: Dict[str, int] = None
    ivs: Dict[str, int] = None
    moves: List[str] = None

    def __post_init__(self):
        if self.evs is None:
            self.evs = {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}
        if self.ivs is None:
            self.ivs = {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}
        if self.moves is None:
            self.moves = []


@dataclass
class ParsedTeam:
    parse_status: str  # "complete", "partial", "failed"
    warnings: List[str]
    pokemon: List[Pokemon]
    raw_pikalytics_species: List[str]


class BaseParser(ABC):
    """Base class for team parsers."""

    @abstractmethod
    def parse(self, content: str) -> ParsedTeam:
        pass

    def _clean_name(self, name: str) -> str:
        """Clean species name."""
        return name.strip()

    def _parse_ev_iv_line(self, line: str) -> tuple:
        """Parse EV/IV line from Showdown format."""
        evs = {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}
        ivs = {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}

        # Try EVs
        ev_match = re.search(r'EVs:\s*(.+?)(?:\s+[A-Za-z]+\s+Nature|$)', line)
        if ev_match:
            ev_str = ev_match.group(1)
            for part in ev_str.split('/'):
                part = part.strip()
                match = re.match(r'(\d+)\s+(HP|Atk|Def|SpA|SpD|Spe)', part, re.IGNORECASE)
                if match:
                    val = int(match.group(1))
                    stat = match.group(2).lower()
                    if stat == "hp": evs["hp"] = val
                    elif stat == "atk": evs["atk"] = val
                    elif stat == "def": evs["def"] = val
                    elif stat == "spa": evs["spa"] = val
                    elif stat == "spd": evs["spd"] = val
                    elif stat == "spe": evs["spe"] = val

        # Try IVs
        iv_match = re.search(r'IVs:\s*(.+?)(?:\s+[A-Za-z]+\s+Nature|$)', line)
        if iv_match:
            iv_str = iv_match.group(1)
            for part in iv_str.split('/'):
                part = part.strip()
                match = re.match(r'(\d+)\s+(HP|Atk|Def|SpA|SpD|Spe)', part, re.IGNORECASE)
                if match:
                    val = int(match.group(1))
                    stat = match.group(2).lower()
                    if stat == "hp": ivs["hp"] = val
                    elif stat == "atk": ivs["atk"] = val
                    elif stat == "def": ivs["def"] = val
                    elif stat == "spa": ivs["spa"] = val
                    elif stat == "spd": ivs["spd"] = val
                    elif stat == "spe": ivs["spe"] = val

        return evs, ivs

    def _parse_nature(self, line: str) -> Optional[str]:
        """Parse nature from line."""
        nature_match = re.search(r'(\w+)\s+Nature', line, re.IGNORECASE)
        if nature_match:
            return nature_match.group(1).capitalize()
        return None

    def _parse_item(self, line: str) -> Optional[str]:
        """Parse item from line (after @)."""
        if '@' in line:
            parts = line.split('@')
            return parts[-1].strip()
        return None

    def _parse_ability(self, line: str) -> Optional[str]:
        """Parse ability from line."""
        match = re.search(r'Ability:\s*(.+?)(?:\s+Level:|\s*$)', line, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def _parse_tera(self, line: str) -> Optional[str]:
        """Parse tera type from line."""
        match = re.search(r'Tera Type:\s*(.+?)(?:\s*$)', line, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None


class LimitlessParser(BaseParser):
    """Parser for limitlesstcg.com teamlist pages."""

    def parse(self, content: str) -> ParsedTeam:
        soup = BeautifulSoup(content, 'html.parser')
        warnings = []
        pokemon_list = []

        # Check if teamlist exists
        teamlist = soup.select('.teamlist .pkmn')
        if not teamlist:
            warnings.append("No .teamlist .pkmn elements found")
            return ParsedTeam(
                parse_status="failed",
                warnings=warnings,
                pokemon=[],
                raw_pikalytics_species=[]
            )

        pikalytics_species = []

        for pkmn in soup.select('.teamlist .pkmn'):
            try:
                name_elem = pkmn.select_one('.name span')
                species = self._clean_name(name_elem.get_text(strip=True)) if name_elem else ""

                item_elem = pkmn.select_one('.details .item')
                item = item_elem.get_text(strip=True) if item_elem else None

                ability_elem = pkmn.select_one('.details .ability')
                ability = ""
                if ability_elem:
                    ability = ability_elem.get_text(strip=True).replace('Ability:', '').strip()

                nature_elem = pkmn.select_one('.details .nature')
                nature = ""
                if nature_elem:
                    nature = nature_elem.get_text(strip=True).replace('Nature', '').strip()

                moves = [li.get_text(strip=True) for li in pkmn.select('.attacks li')][:4]

                if species:
                    pikalytics_species.append(species)
                    pokemon_list.append(Pokemon(
                        species=species,
                        item=item,
                        ability=ability,
                        nature=nature,
                        moves=moves,
                        evs={"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0},
                        ivs={"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}
                    ))
            except Exception as e:
                warnings.append(f"Failed to parse pokemon: {e}")

        status = "complete" if len(pokemon_list) == 6 else ("partial" if pokemon_list else "failed")

        return ParsedTeam(
            parse_status=status,
            warnings=warnings,
            pokemon=pokemon_list,
            raw_pikalytics_species=pikalytics_species
        )


class RK9Parser(BaseParser):
    """Parser for rk9.gg teamlist pages."""

    def parse(self, content: str) -> ParsedTeam:
        # RK9 pages are rendered with JS, so HTML might not have full data
        soup = BeautifulSoup(content, 'html.parser')
        text = soup.get_text()

        # Try to extract from the text representation
        return self._parse_from_text(text)

    def _parse_from_text(self, text: str) -> ParsedTeam:
        """Parse from extracted text (rk9 format)."""
        warnings = []
        pokemon_list = []
        pikalytics_species = []

        # Find all Pokemon name lines (ending with " EN")
        matches = list(re.finditer(r'^[^\n]*\s+EN$', text, re.MULTILINE))

        if len(matches) < 2:
            warnings.append("Could not find Pokemon entries in RK9 text")
            return ParsedTeam(
                parse_status="failed",
                warnings=warnings,
                pokemon=[],
                raw_pikalytics_species=[]
            )

        positions = [m.start() for m in matches]
        names = [m.group().replace('  EN', '').strip() for m in matches]

        for i, (start, name) in enumerate(zip(positions, names)):
            block_end = positions[i+1] if i+1 < len(positions) else len(text)
            block = text[start:block_end].strip()

            lines = [l.strip() for l in block.split('\n') if l.strip()]
            if len(lines) < 3:
                continue

            ability = ""
            item = ""
            if len(lines) > 1 and 'Ability:' in lines[1]:
                if 'Held Item:' in lines[1]:
                    parts = lines[1].split('Held Item:')
                    ability = parts[0].replace('Ability:', '').strip()
                    item = parts[1].strip()
                else:
                    ability = lines[1].replace('Ability:', '').strip()

            nature = ""
            if len(lines) > 2 and 'Stat Alignment:' in lines[2]:
                nature = lines[2].replace('Stat Alignment:', '').strip()

            moves = []
            for line in lines[3:]:
                if not line.endswith('  EN') and not line.startswith('Ability:') and not line.startswith('Stat Alignment:'):
                    moves.extend([m.strip() for m in line.split() if m.strip()])
            moves = moves[:4]

            if name:
                pikalytics_species.append(name)
                pokemon_list.append(Pokemon(
                    species=name,
                    item=item,
                    ability=ability,
                    nature=nature,
                    moves=moves,
                    evs={"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0},
                    ivs={"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}
                ))

        status = "complete" if len(pokemon_list) == 6 else ("partial" if pokemon_list else "failed")
        if len(pokemon_list) < 6:
            warnings.append(f"Only parsed {len(pokemon_list)} Pokemon")

        return ParsedTeam(
            parse_status=status,
            warnings=warnings,
            pokemon=pokemon_list,
            raw_pikalytics_species=pikalytics_species
        )


class PokepasteParser(BaseParser):
    """Parser for pokepast.es team pages."""

    def parse(self, content: str) -> ParsedTeam:
        """Parse pokepast.es exported text format."""
        warnings = []
        pokemon_list = []
        pikalytics_species = []

        # Pokepaste format:
        # Pokemon @ Item
        # Ability: Ability
        # Level: 50
        # Tera Type: Type
        # EVs: 252 HP / 4 Def / 252 SpA
        # Modest Nature
        # IVs: 0 Atk
        # - Move 1
        # - Move 2
        # - Move 3
        # - Move 4

        sections = re.split(r'\n\s*\n', content.strip())

        for section in sections:
            if not section.strip():
                continue

            lines = [l.strip() for l in section.split('\n') if l.strip()]
            if not lines:
                continue

            # Parse first line: "Pokemon @ Item" or just "Pokemon"
            first = lines[0]
            species = ""
            item = None
            if '@' in first:
                parts = first.split('@')
                species = self._clean_name(parts[0])
                item = parts[1].strip()
            else:
                species = self._clean_name(first)

            ability = None
            nature = None
            tera_type = None
            evs = {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}
            ivs = {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}
            moves = []

            for line in lines[1:]:
                if line.startswith('Ability:'):
                    ability = line.replace('Ability:', '').strip()
                elif 'Nature' in line and not line.startswith('Ability:'):
                    nature = self._parse_nature(line)
                elif line.startswith('Tera Type:'):
                    tera_type = line.replace('Tera Type:', '').strip()
                elif line.startswith('EVs:'):
                    evs_str = line.replace('EVs:', '').strip()
                    for part in evs_str.split('/'):
                        part = part.strip()
                        match = re.match(r'(\d+)\s+(HP|Atk|Def|SpA|SpD|Spe)', part, re.IGNORECASE)
                        if match:
                            val = int(match.group(1))
                            stat = match.group(2).lower()
                            if stat == "hp": evs["hp"] = val
                            elif stat == "atk": evs["atk"] = val
                            elif stat == "def": evs["def"] = val
                            elif stat == "spa": evs["spa"] = val
                            elif stat == "spd": evs["spd"] = val
                            elif stat == "spe": evs["spe"] = val
                elif line.startswith('IVs:'):
                    ivs_str = line.replace('IVs:', '').strip()
                    for part in ivs_str.split('/'):
                        part = part.strip()
                        match = re.match(r'(\d+)\s+(HP|Atk|Def|SpA|SpD|Spe)', part, re.IGNORECASE)
                        if match:
                            val = int(match.group(1))
                            stat = match.group(2).lower()
                            if stat == "hp": ivs["hp"] = val
                            elif stat == "atk": ivs["atk"] = val
                            elif stat == "def": ivs["def"] = val
                            elif stat == "spa": ivs["spa"] = val
                            elif stat == "spd": ivs["spd"] = val
                            elif stat == "spe": ivs["spe"] = val
                elif line.startswith('- '):
                    moves.append(line[2:].strip())

            if species:
                pikalytics_species.append(species)
                pokemon_list.append(Pokemon(
                    species=species,
                    item=item,
                    ability=ability,
                    tera_type=tera_type,
                    nature=nature,
                    evs=evs,
                    ivs=ivs,
                    moves=moves[:4]
                ))

        status = "complete" if len(pokemon_list) == 6 else ("partial" if pokemon_list else "failed")
        if len(pokemon_list) < 6:
            warnings.append(f"Only parsed {len(pokemon_list)} Pokemon")

        return ParsedTeam(
            parse_status=status,
            warnings=warnings,
            pokemon=pokemon_list,
            raw_pikalytics_species=pikalytics_species
        )


def get_parser_for_url(url: str) -> BaseParser:
    """Factory function to get appropriate parser for URL."""
    if "limitlesstcg.com" in url:
        return LimitlessParser()
    elif "rk9.gg" in url:
        return RK9Parser()
    elif "pokepast.es" in url:
        return PokepasteParser()
    else:
        # Default to limitless parser as fallback
        return LimitlessParser()


def main():
    """Test parsers with cached files."""
    cache_dir = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/cache")

    # Test with a limitless cache file
    cache_files = list(cache_dir.glob("*.html"))
    if cache_files:
        test_file = cache_files[0]
        print(f"Testing with {test_file}")

        content = test_file.read_text(encoding='utf-8')
        parser = get_parser_for_url("https://play.limitlesstcg.com/")
        result = parser.parse(content)

        print(f"Status: {result.parse_status}")
        print(f"Pokemon count: {len(result.pokemon)}")
        print(f"Warnings: {result.warnings}")
        for p in result.pokemon:
            print(f"  {p.species} | {p.item} | {p.ability} | {p.nature} | {p.moves}")

if __name__ == "__main__":
    main()