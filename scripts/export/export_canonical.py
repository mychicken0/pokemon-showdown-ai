#!/usr/bin/env python3
"""
Phase T4 - Canonical Schema & Export
Create canonical JSON, Showdown export, poke-env teams, and incomplete report.
"""

import json
from pathlib import Path
from dataclasses import asdict
from typing import List, Optional, Dict, Any
from datetime import datetime

# Load detailed teams (already parsed)
detailed_path = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/vgc2026_teams_detailed.json")
with open(detailed_path) as f:
    detailed_teams = json.load(f)

# Load source index for metadata
source_index_path = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/source_index.json")
with open(source_index_path) as f:
    source_index = json.load(f)

# Build rank -> source_index entry map
meta_map = {e["rank"]: e for e in source_index}

OUTPUT_DIR = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def normalize_species(name: str) -> str:
    """Normalize species name for Showdown."""
    # Remove form suffixes that aren't part of base name
    return name.replace("-Mega", "").replace("-Eternal", "").replace(" [Eternal Flower]", "").replace(" [Unremarkable Form]", "")

def to_canonical_team(detailed_team: dict) -> dict:
    """Convert detailed team to canonical schema."""
    rank = detailed_team.get("rank")
    meta = meta_map.get(rank, {})

    # Determine parse status
    pokemon_data = detailed_team.get("pokemon", [])
    parse_status = "complete" if len(pokemon_data) == 6 else ("partial" if pokemon_data else "failed")

    canonical_pokemon = []
    for p in pokemon_data:
        # Build moves list
        moves = p.get("moves", [])
        # Join split move names
        clean_moves = []
        for m in moves:
            if isinstance(m, list):
                clean_moves.append(" ".join(m))
            else:
                clean_moves.append(m)
        clean_moves = clean_moves[:4]

        canonical_pokemon.append({
            "species": p.get("species", ""),
            "nickname": None,
            "gender": None,
            "level": 50,
            "item": p.get("item"),
            "ability": p.get("ability"),
            "tera_type": p.get("tera_type"),  # Not available in source data
            "nature": p.get("nature"),
            "evs": {
                "hp": 0, "atk": 0, "def": 0,
                "spa": 0, "spd": 0, "spe": 0
            },
            "ivs": {
                "hp": 31, "atk": 31, "def": 31,
                "spa": 31, "spd": 31, "spe": 31
            },
            "moves": clean_moves
        })

    return {
        "id": f"pikalytics_rank_{rank:03d}",
        "rank": detailed_team.get("rank"),
        "player": detailed_team.get("player"),
        "event": detailed_team.get("tournament"),
        "record": detailed_team.get("record"),
        "source_platform": detailed_team.get("source", "unknown"),
        "source_url": detailed_team.get("url", ""),
        "pikalytics_species": detailed_team.get("pikalytics_species", []),
        "parse_status": "complete" if len(detailed_team.get("pokemon", [])) == 6 else "partial",
        "parse_warnings": [],
        "team": canonical_pokemon
    }

def to_showdown_text(team: dict) -> str:
    """Convert team to Showdown importable text format."""
    lines = []
    for p in team:
        lines.append(f"{p['species']} @ {p['item'] or 'No Item'}")
        if p.get('ability'):
            lines.append(f"Ability: {p['ability']}")
        if p.get('tera_type'):
            lines.append(f"Tera Type: {p['tera_type']}")
        lines.append(f"Level: {p['level']}")

        evs = p.get('evs', {})
        if any(v > 0 for v in evs.values()):
            ev_parts = []
            for stat, val in evs.items():
                if val > 0:
                    ev_parts.append(f"{val} {stat.upper()}")
            if ev_parts:
                lines.append(f"EVs: {' / '.join(ev_parts)}")

        if p.get('nature'):
            lines.append(f"{p['nature']} Nature")

        ivs = p.get('ivs', {})
        iv_parts = []
        for stat, val in ivs.items():
            if val != 31:
                iv_parts.append(f"{31-val} {stat.upper()}")
        if iv_parts:
            lines.append(f"IVs: {' / '.join(iv_parts)}")

        for move in p.get('moves', []):
            lines.append(f"- {move}")

        # Pokemon separator
        lines.append("")

    return "\n".join(lines).strip()

def main():
    # Load detailed teams
    detailed_path = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/vgc2026_teams_detailed.json")
    with open(detailed_path) as f:
        detailed_teams = json.load(f)

    print(f"Processing {len(detailed_teams)} teams...")

    # Build canonical dataset
    canonical = {
        "dataset": "pikalytics_topteams_vgc2026",
        "generated_at": datetime.now().isoformat(),
        "source_count": len(detailed_teams),
        "teams": []
    }

    complete_count = 0
    partial_count = 0
    failed_count = 0

    for dt in detailed_teams:
        canonical_team = to_canonical_team(dt)
        canonical["teams"].append(canonical_team)

        status = "complete" if len(dt.get("pokemon", [])) == 6 else ("partial" if dt.get("pokemon") else "failed")
        if status == "complete":
            complete_count += 1
        elif status == "partial":
            partial_count += 1
        else:
            failed_count += 1

    # Sort by rank
    canonical["teams"].sort(key=lambda x: x["rank"])
    canonical["source_count"] = len(canonical["teams"])

    # Save canonical JSON
    output_dir = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams")
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_dir / "vgc2026_top200_full_teams.json", 'w') as f:
        json.dump(canonical, f, indent=2)
    print(f"Saved canonical JSON")

    # Export Showdown text
    showdown_lines = []
    for ct in canonical["teams"]:
        if ct["parse_status"] == "complete":
            team_text = []
            for p in ct["team"]:
                lines = []
                item_str = p["item"] or "No Item"
                lines.append(f"{p['species']} @ {item_str}")
                if p.get("ability"):
                    lines.append(f"Ability: {p['ability']}")
                lines.append(f"Level: {p['level']}")

                # EVs (all 0 in our data, but include format)
                ev_lines = []
                for stat, val in p.get("evs", {}).items():
                    if val > 0:
                        ev_lines.append(f"{val} {stat.upper()}")
                if ev_lines:
                    lines.append(f"EVs: {' / '.join(ev_lines)}")

                if p.get("nature"):
                    lines.append(f"{p['nature']} Nature")

                # IVs
                iv_parts = []
                for stat, val in p.get("ivs", {}).items():
                    if val != 31:
                        iv_parts.append(f"{31-val} {stat.upper()}")
                if iv_parts:
                    lines.append(f"IVs: {' / '.join(iv_parts)}")

                for move in p.get("moves", []):
                    lines.append(f"- {move}")

                team_text.append("\n".join(lines))

            showdown_lines.append("\n".join(team_text))

    with open(output_dir / "vgc2026_top200_showdown.txt", 'w') as f:
        f.write("\n\n".join(showdown_lines))
    print(f"Saved Showdown export")

    # Export poke-env format (just the teams in a format poke-env can use)
    poke_env_teams = []
    for ct in canonical["teams"]:
        if ct["parse_status"] == "complete":
            poke_env_teams.append({
                "name": f"{ct['player']} (Rank {ct['rank']})",
                "team": [{
                    "species": p["species"],
                    "item": p["item"],
                    "ability": p["ability"],
                    "nature": p["nature"],
                    "evs": p["evs"],
                    "ivs": p["ivs"],
                    "moves": p["moves"]
                } for p in ct["team"]]
            })

    with open(output_dir / "vgc2026_top200_poke_env_teams.json", 'w') as f:
        json.dump(poke_env_teams, f, indent=2)
    print(f"Saved poke-env teams")

    # Incomplete report
    incomplete = []
    for ct in canonical["teams"]:
        if ct["parse_status"] != "complete":
            incomplete.append({
                "id": ct["id"],
                "rank": ct["rank"],
                "player": ct["player"],
                "status": ct["parse_status"],
                "pokemon_count": len(ct["team"]),
                "missing_fields": ["tera_type", "evs", "ivs"]  # Known missing
            })

    import csv
    with open(output_dir / "vgc2026_top200_incomplete_report.csv", 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["id", "rank", "player", "status", "pokemon_count", "missing_fields"])
        writer.writeheader()
        for row in incomplete:
            writer.writerow(row)
    print(f"Saved incomplete report ({len(incomplete)} teams)")

    # Fetch log already exists

    print(f"\n=== Summary ===")
    print(f"Total teams: {len(canonical['teams'])}")
    print(f"Complete: {sum(1 for t in canonical['teams'] if t['parse_status'] == 'complete')}")
    print(f"Partial: {sum(1 for t in canonical['teams'] if t['parse_status'] == 'partial')}")
    print(f"Failed: {sum(1 for t in canonical['teams'] if t['parse_status'] == 'failed')}")
    print(f"Output directory: {output_dir}")

if __name__ == "__main__":
    from datetime import datetime
    import csv
    main()