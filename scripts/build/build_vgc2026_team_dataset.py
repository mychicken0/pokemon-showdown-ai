#!/usr/bin/env python3
"""
Phase T1 - Source Index
Load Pikalytics top teams JSON and normalize into structured index.
"""

import json
import re
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional
import sys

@dataclass
class TeamEntry:
    rank: int
    player: str
    record: str
    event: str
    rank_place: str
    date: str
    pikalytics_species: List[str]
    source_url: str
    source_platform: str  # limitless, rk9, pokepaste, unknown

def extract_source_url(entry: dict) -> str:
    """Extract source URL from Pikalytics entry if available."""
    # The original pikalytics file doesn't seem to have source URLs directly
    # We'll need to derive them or mark as unknown
    return ""

def detect_platform(source_url: str) -> str:
    """Detect platform from URL."""
    if not source_url:
        return "unknown"
    if "limitlesstcg.com" in source_url:
        return "limitless"
    elif "rk9.gg" in source_url:
        return "rk9"
    elif "pokepast.es" in source_url:
        return "pokepaste"
    return "unknown"

def parse_pikalytics(filepath: str) -> List[dict]:
    """Parse the Pikalytics top teams JSON."""
    with open(filepath, 'r') as f:
        data = json.load(f)
    return data

def normalize_entry(entry: dict) -> TeamEntry:
    """Normalize a Pikalytics entry into TeamEntry."""
    # Clean rank
    rank_str = entry.get("rank", "#0")
    rank = int(rank_str.replace("#", "")) if rank_str.startswith("#") else 0

    # Get player name
    player = entry.get("player", "").strip()

    # Get record
    record = entry.get("record", "").strip()

    # Get event
    event = entry.get("tournament", "").strip()

    # Get rank place
    rank_place = entry.get("rankPlace", "").strip()

    # Get date
    date = entry.get("date", "").strip()

    # Get species
    species = entry.get("pokemon", [])

    # The original file doesn't have source URLs - they need to be derived/fetched
    source_url = ""
    source_platform = "unknown"

    return TeamEntry(
        rank=rank,
        player=player,
        record=record,
        event=event,
        rank_place=rank_place,
        date=date,
        pikalytics_species=species,
        source_url=source_url,
        source_platform=source_platform
    )

def main():
    input_file = "/home/phurin/pikalytics_top200_teams.json"
    output_dir = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "source_index.json"

    print(f"Loading {input_file}...")
    raw_data = parse_pikalytics(input_file)
    print(f"Loaded {len(raw_data)} entries")

    teams = []
    for entry in raw_data:
        normalized = normalize_entry(entry)
        teams.append(asdict(normalized))

    # Sort by rank
    teams.sort(key=lambda x: x["rank"])

    # Save
    with open(output_file, 'w') as f:
        json.dump(teams, f, indent=2)

    print(f"Saved {len(teams)} teams to {output_file}")

    # Print summary
    platforms = {}
    for t in teams:
        p = t.get("source_platform", "unknown")
        platforms[p] = platforms.get(p, 0) + 1
    print(f"Platform distribution: {platforms}")

if __name__ == "__main__":
    main()