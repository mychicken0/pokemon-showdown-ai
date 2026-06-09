#!/usr/bin/env python3
"""
parse_meta_stats.py

Parses a raw Smogon statistics file data/raw_meta_stats.txt (if provided manually)
and outputs data/meta_usage_stats.json.
Converts percentages (e.g. 85.0% or 85) to probabilities (0.0 to 1.0).
"""
import json
import os
import re

RAW_STATS_FILE = "data/raw_meta_stats.txt"
JSON_STATS_FILE = "data/meta_usage_stats.json"


def clean_name(name: str) -> str:
    return "".join(c.lower() for c in name if c.isalnum())


def parse_raw_file():
    if not os.path.exists(RAW_STATS_FILE):
        print(f"No raw input file found at {RAW_STATS_FILE}. Skipping parsing.")
        return

    print(f"Parsing raw stats from {RAW_STATS_FILE}...")
    
    # Simple parser for raw Smogon text data.
    # Typically, Smogon stats look like:
    # | Pokemon Name             |
    # | Abilities                |
    # | Intimidate 99.0%         |
    # | Moves                    |
    # | Fake Out 91.0%           |
    # | Items                    |
    # | Sitrus Berry 32.0%       |
    
    pokemon_data = {}
    current_pokemon = None
    current_section = None  # "moves", "abilities", "items"

    # Regex patterns
    divider_pattern = re.compile(r"^[+-]+$")
    pct_pattern = re.compile(r"^(.*?)\s+([\d.]+)\s*%?\s*$")

    with open(RAW_STATS_FILE, "r") as f:
        for line in f:
            line = line.strip().strip("|").strip()
            if not line or divider_pattern.match(line):
                continue
            
            # Detect section changes or new Pokémon
            line_lower = line.lower()
            if line_lower.startswith("abilities"):
                current_section = "abilities"
                continue
            elif line_lower.startswith("moves"):
                current_section = "moves"
                continue
            elif line_lower.startswith("items"):
                current_section = "items"
                continue
            elif line_lower.startswith("teammates"):
                current_section = "teammates"
                continue
            
            # If we see a separator or header like "Raw count" or similar, skip
            if "raw count" in line_lower or "avg. weight" in line_lower:
                continue

            # Check if this line indicates a new Pokémon
            # Smogon tables typically start a Pokémon with no percentage at the top of a block
            m = pct_pattern.match(line)
            if not m:
                # New Pokémon entry
                current_pokemon = clean_name(line)
                if current_pokemon:
                    pokemon_data[current_pokemon] = {
                        "moves": {},
                        "abilities": {},
                        "items": {},
                        "teammates": {}
                    }
                    current_section = None
                continue

            # It's an entry inside a section (ability, item, move) with percentage
            if current_pokemon and current_section:
                name_part, pct_part = m.groups()
                name_cleaned = clean_name(name_part)
                try:
                    prob = float(pct_part) / 100.0
                    # Clamp between 0.0 and 1.0
                    prob = max(0.0, min(1.0, prob))
                    if current_section in ("moves", "abilities", "items"):
                        pokemon_data[current_pokemon][current_section][name_cleaned] = round(prob, 4)
                except ValueError:
                    pass

    if pokemon_data:
        output_json = {
            "format": "gen9randomdoublesbattle",
            "source": "parsed_from_raw",
            "pokemon": pokemon_data
        }
        os.makedirs(os.path.dirname(JSON_STATS_FILE), exist_ok=True)
        with open(JSON_STATS_FILE, "w") as jf:
            json.dump(output_json, jf, indent=2)
        print(f"Successfully wrote parsed stats of {len(pokemon_data)} Pokémon to {JSON_STATS_FILE}")
    else:
        print("No valid Pokémon records parsed from raw file.")


if __name__ == "__main__":
    parse_raw_file()
