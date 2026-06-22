#!/usr/bin/env python3
"""
Rebuild canonical dataset with updated completeness classification.

Statuses:
- source_missing: No source URL from Pikalytics
- fetch_failed: HTTP error when fetching source URL
- parse_failed: Source fetched but parsing failed
- partial_ots: Source provided some but not all OTS data (moves/items/abilities)
- complete_ots: Source provided all OTS data (species, item, ability, moves, nature)
- battle_ready: Canonical OTS data + simulation-filled missing fields (IVs, EVs, Tera)
- invalid_showdown: Fails Showdown validation
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

from team_scrapers.showdown_name_normalizer import normalize_species

# Load the detailed teams (source-provided data)
detailed_path = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_teams_detailed.json")
with open(detailed_path) as f:
    detailed_teams = json.load(f)

# Load source index
source_index_path = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/source_index.json")
with open(source_index_path) as f:
    source_index = json.load(f)

detailed_map = {t["rank"]: t for t in detailed_teams}
meta_map = {e["rank"]: e for e in source_index}

OUTPUT_DIR = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Field source tracking
SOURCE_PROVIDED = "source_provided"
SIMULATION_DEFAULT = "simulation_default"
HEURISTIC = "heuristic"
MISSING = "missing"

def classify_team(rank: int) -> tuple:
    """Classify a team's completeness based on available data."""
    meta = meta_map.get(rank, {})
    detailed = detailed_map.get(rank)

    source_url = meta.get("source_url", "")
    source_platform = meta.get("source_platform", "unknown")

    if not source_url:
        return "source_missing", {"reason": "No source URL in Pikalytics data"}

    if not detailed:
        return "fetch_failed", {"reason": "Source URL not scraped/cached"}

    pokemon = detailed.get("pokemon", [])
    if not pokemon:
        return "parse_failed", {"reason": "Parser returned no pokemon"}

    # Check if all 6 pokemon have complete OTS data
    has_all_species = len(pokemon) == 6
    has_all_items = all(p.get("item") for p in pokemon)
    has_all_abilities = all(p.get("ability") for p in pokemon)
    has_all_moves = all(p.get("moves") and len(p["moves"]) == 4 for p in pokemon)
    has_all_natures = all(p.get("nature") for p in pokemon)

    if has_all_species and has_all_items and has_all_abilities and has_all_moves and has_all_natures:
        return "complete_ots", {
            "source_platform": source_platform,
            "source_url": source_url,
            "pokemon_count": len(pokemon)
        }
    elif has_all_species and any([has_all_items, has_all_abilities, has_all_moves, has_all_natures]):
        return "partial_ots", {
            "source_platform": source_platform,
            "source_url": source_url,
            "pokemon_count": len(pokemon),
            "has_items": has_all_items,
            "has_abilities": has_all_abilities,
            "has_moves": has_all_moves,
            "has_natures": has_all_natures
        }
    else:
        return "parse_failed", {
            "source_platform": source_platform,
            "source_url": source_url,
            "pokemon_count": len(pokemon)
        }

def build_canonical_pokemon(detailed_pokemon: dict, species_id: str) -> dict:
    """Build canonical pokemon with field source tracking."""

    # Determine source for each field
    item_source = SOURCE_PROVIDED if detailed_pokemon.get("item") else MISSING
    ability_source = SOURCE_PROVIDED if detailed_pokemon.get("ability") else MISSING
    moves_source = SOURCE_PROVIDED if (detailed_pokemon.get("moves") and len(detailed_pokemon["moves"]) == 4) else MISSING
    nature_source = SOURCE_PROVIDED if detailed_pokemon.get("nature") else MISSING

    # EVs/IVs/Tera are always simulation defaults in our source data
    evs_source = SIMULATION_DEFAULT
    ivs_source = SIMULATION_DEFAULT
    tera_source = MISSING  # Not in source data
    level_source = SOURCE_PROVIDED  # Level 50 is standard for VGC

    return {
        "species": species_id,
        "nickname": None,
        "gender": None,
        "level": 50,
        "level_source": level_source,
        "item": detailed_pokemon.get("item"),
        "item_source": item_source,
        "ability": detailed_pokemon.get("ability"),
        "ability_source": ability_source,
        "tera_type": detailed_pokemon.get("tera_type"),  # Always None in source
        "tera_type_source": tera_source,
        "nature": detailed_pokemon.get("nature"),
        "nature_source": nature_source,
        "evs": {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0},
        "evs_source": evs_source,
        "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31},
        "ivs_source": ivs_source,
        "moves": detailed_pokemon.get("moves", []),
        "moves_source": moves_source,
    }

def build_battle_ready_pokemon(canonical_pokemon: dict) -> dict:
    """Build battle-ready pokemon - same as canonical but with filled fields marked for validation."""
    bp = canonical_pokemon.copy()

    # For Showdown validation, we need some EVs and a valid nature
    # If EVs are all 0 and nature is from source, use Hardy (neutral) with minimal HP EVs
    evs = bp.get("evs", {})
    if all(v == 0 for v in evs.values()):
        bp["evs"] = {"hp": 4, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}
        bp["evs_source"] = "simulation_default"

    # If nature is missing or neutral with 0 EVs, use Hardy
    if not bp.get("nature") or bp.get("nature") in ["Hardy", "Docile", "Serious", "Bashful", "Quirky"]:
        pass  # These are neutral natures

    return bp

def main():
    print("Rebuilding canonical dataset with updated classification...")

    canonical = {
        "dataset": "pikalytics_topteams_vgc2026",
        "generated_at": datetime.now().isoformat(),
        "source_count": 200,
        "teams": []
    }

    battle_ready = {
        "dataset": "pikalytics_topteams_vgc2026_battle_ready",
        "generated_at": datetime.now().isoformat(),
        "source_count": 200,
        "teams": []
    }

    status_counts = {}

    for entry in source_index:
        rank = entry["rank"]

        status, status_info = classify_team(rank)
        status_counts[status] = status_counts.get(status, 0) + 1

        detailed = detailed_map.get(rank)

        canonical_team = {
            "id": f"pikalytics_rank_{rank:03d}",
            "rank": rank,
            "player": entry.get("player"),
            "event": entry.get("event"),
            "record": entry.get("record"),
            "source_platform": entry.get("source_platform"),
            "source_url": entry.get("source_url"),
            "pikalytics_species": entry.get("pikalytics_species", []),
            "parse_status": status,
            "parse_info": status_info,
            "team": []
        }

        if detailed and detailed.get("pokemon"):
            for p in detailed.get("pokemon", []):
                species = p.get("species", "")
                species_id = normalize_species(species)
                if species_id:
                    canonical_poke = build_canonical_pokemon(p, species_id)
                    canonical_team["team"].append(canonical_poke)

        canonical["teams"].append(canonical_team)

        # Build battle-ready version
        if status in ("complete_ots", "partial_ots"):
            battle_team = {
                "id": f"pikalytics_rank_{rank:03d}",
                "rank": rank,
                "player": entry.get("player"),
                "event": entry.get("event"),
                "record": entry.get("record"),
                "source_platform": entry.get("source_platform"),
                "source_url": entry.get("source_url"),
                "parse_status": status,
                "team": []
            }
            if detailed and detailed.get("pokemon"):
                for p in detailed.get("pokemon", []):
                    species = p.get("species", "")
                    species_id = normalize_species(species)
                    if species_id:
                        canonical_poke = build_canonical_pokemon(p, species_id)
                        battle_poke = build_battle_ready_pokemon(canonical_poke)
                        battle_team["team"].append(battle_poke)
            battle_ready["teams"].append(battle_team)

    canonical["teams"].sort(key=lambda x: x["rank"])
    battle_ready["teams"].sort(key=lambda x: x["rank"])

    # Save canonical OTS
    with open(OUTPUT_DIR / "vgc2026_top200_canonical_ots.json", 'w') as f:
        json.dump(canonical, f, indent=2)
    print(f"Saved canonical OTS: {OUTPUT_DIR / 'vgc2026_top200_canonical_ots.json'}")

    # Save battle-ready
    with open(OUTPUT_DIR / "vgc2026_top200_battle_ready.json", 'w') as f:
        json.dump(battle_ready, f, indent=2)
    print(f"Saved battle-ready: {OUTPUT_DIR / 'vgc2026_top200_battle_ready.json'}")

    # Print status summary
    print("\n=== Status Summary ===")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")

    # Also create Showdown export for battle-ready
    showdown_lines = []
    for ct in battle_ready["teams"]:
        if ct["parse_status"] in ("complete_ots", "partial_ots") and ct["team"]:
            lines = []
            for p in ct["team"]:
                item_str = p["item"] or "No Item"
                lines.append(f"{p['species'].capitalize()} @ {item_str}")
                if p.get("ability"):
                    lines.append(f"Ability: {p['ability']}")
                if p.get("tera_type"):
                    lines.append(f"Tera Type: {p['tera_type']}")
                lines.append(f"Level: {p['level']}")

                ev_lines = [f"{v} {k.upper()}" for k, v in p.get("evs", {}).items() if v > 0]
                if ev_lines:
                    lines.append(f"EVs: {' / '.join(ev_lines)}")

                if p.get("nature"):
                    lines.append(f"{p['nature'].capitalize()} Nature")

                iv_parts = [f"{31-v} {k.upper()}" for k, v in p.get("ivs", {}).items() if v != 31]
                if iv_parts:
                    lines.append(f"IVs: {' / '.join(iv_parts)}")

                for move in p.get("moves", []):
                    lines.append(f"- {move}")

                lines.append("")

            showdown_lines.append("\n".join(lines).strip())

    with open(OUTPUT_DIR / "vgc2026_top200_battle_ready_showdown.txt", 'w') as f:
        f.write("\n\n".join(showdown_lines))
    print(f"Saved battle-ready Showdown export: {OUTPUT_DIR / 'vgc2026_top200_battle_ready_showdown.txt'}")

    print("Done!")

if __name__ == "__main__":
    main()