#!/usr/bin/env python3
"""
Phase T4 - Canonical Schema & Export (Updated)
Create canonical JSON, Showdown export, poke-env teams, and incomplete report for ALL 200 teams.
"""

import json
import csv
from pathlib import Path
from datetime import datetime
from collections import Counter

# Load detailed teams (already parsed)
detailed_path = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_teams_detailed.json")
with open(detailed_path) as f:
    detailed_teams = json.load(f)

# Load source index for ALL 200 teams
source_index_path = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/source_index.json")
with open(source_index_path) as f:
    source_index = json.load(f)

OUTPUT_DIR = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Build rank -> detailed team map
detailed_map = {t["rank"]: t for t in detailed_teams}
# Build rank -> source index map
meta_map = {e["rank"]: e for e in source_index}

def to_canonical_team(rank: int) -> dict:
    """Convert team data to canonical schema."""
    meta = meta_map.get(rank, {})
    detailed = detailed_map.get(rank)

    has_detail = detailed is not None
    pokemon_data = detailed.get("pokemon", []) if has_detail else []
    parse_status = "complete" if len(pokemon_data) == 6 else ("partial" if pokemon_data else "failed")

    # Build canonical pokemon
    canonical_pokemon = []
    if has_detail and detailed.get("pokemon"):
        for p in detailed.get("pokemon", []):
            clean_moves = []
            for m in p.get("moves", []):
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
                "tera_type": p.get("tera_type"),
                "nature": p.get("nature"),
                "evs": {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0},
                "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31},
                "moves": clean_moves
            })

    meta = meta_map.get(detailed.get("rank") if detailed else None, {}) if detailed else {}

    return {
        "id": f"pikalytics_rank_{rank:03d}",
        "rank": rank,
        "player": (detailed.get("player") if has_detail else meta.get("player", "Unknown")),
        "event": (detailed.get("tournament") if has_detail else meta.get("event", "Unknown")),
        "record": (detailed.get("record") if has_detail else meta.get("record", "Unknown")),
        "source_platform": (detailed.get("source") if has_detail else meta.get("source_platform", "unknown")),
        "source_url": (detailed.get("url") if has_detail else meta.get("source_url", "")),
        "pikalytics_species": detailed.get("pikalytics_species", []) if has_detail else meta.get("pikalytics_species", []),
        "parse_status": "complete" if detailed and len(detailed.get("pokemon", [])) == 6 else ("partial" if detailed else "failed"),
        "parse_warnings": [] if detailed else ["No detailed data available - source URL missing or not scraped"],
        "team": [
            {
                "species": p.get("species", ""),
                "nickname": None,
                "gender": None,
                "level": 50,
                "item": p.get("item"),
                "ability": p.get("ability"),
                "tera_type": p.get("tera_type"),
                "nature": p.get("nature"),
                "evs": {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0},
                "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31},
                "moves": p.get("moves", [])
            }
            for p in (detailed.get("pokemon", []) if detailed else [])
        ]
    }

def team_to_showdown(team_dict: dict) -> str:
    """Convert a canonical team dict to Showdown import format."""
    lines = []
    for p in team_dict["team"]:
        item_str = p["item"] or "No Item"
        lines.append(f"{p['species']} @ {item_str}")
        if p.get("ability"):
            lines.append(f"Ability: {p['ability']}")
        if p.get("tera_type"):
            lines.append(f"Tera Type: {p['tera_type']}")
        lines.append(f"Level: {p['level']}")

        # EVs (all 0 in our data)
        ev_lines = [f"{v} {k.upper()}" for k, v in p.get("evs", {}).items() if v > 0]
        if ev_lines:
            lines.append(f"EVs: {' / '.join(ev_lines)}")

        if p.get("nature"):
            lines.append(f"{p['nature']} Nature")

        # IVs
        iv_parts = [f"{31-v} {k.upper()}" for k, v in p.get("ivs", {}).items() if v != 31]
        if iv_parts:
            lines.append(f"IVs: {' / '.join(iv_parts)}")

        for move in p.get("moves", []):
            lines.append(f"- {move}")

        lines.append("")  # blank line between Pokemon

    return "\n".join(lines).strip() + "\n"

def main():
    output_dir = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load source index for all 200 teams
    with open("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/source_index.json") as f:
        source_index = json.load(f)

    # Load detailed teams
    with open("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_teams_detailed.json") as f:
        detailed_teams = json.load(f)

    detailed_map = {t["rank"]: t for t in detailed_teams}
    meta_map = {e["rank"]: e for e in source_index}

    # Build canonical dataset for ALL 200 teams
    canonical = {
        "dataset": "pikalytics_topteams_vgc2026",
        "generated_at": datetime.now().isoformat(),
        "source_count": 200,
        "teams": []
    }

    # Process ALL 200 ranks
    for entry in source_index:
        rank = entry["rank"]
        canonical_team = {
            "id": f"pikalytics_rank_{rank:03d}",
            "rank": rank,
            "player": meta_map.get(rank, {}).get("player", entry.get("player", "Unknown")),
            "event": meta_map.get(rank, {}).get("event", entry.get("event", "Unknown")),
            "record": meta_map.get(rank, {}).get("record", entry.get("record", "Unknown")),
            "source_platform": meta_map.get(rank, {}).get("source_platform", entry.get("source_platform", "unknown")),
            "source_url": meta_map.get(rank, {}).get("source_url", entry.get("source_url", "")),
            "pikalytics_species": entry.get("pikalytics_species", []),
            "parse_status": "complete" if rank in detailed_map and len(detailed_map[rank].get("pokemon", [])) == 6 else ("partial" if rank in detailed_map else "failed"),
            "parse_warnings": [] if rank in detailed_map else ["No detailed data available - source URL missing or not scraped"],
            "team": []
        }

        if rank in detailed_map:
            detailed = detailed_map[rank]
            for p in detailed.get("pokemon", []):
                clean_moves = []
                for m in p.get("moves", []):
                    if isinstance(m, list):
                        clean_moves.append(" ".join(m))
                    else:
                        clean_moves.append(m)
                clean_moves = clean_moves[:4]

                canonical_team["team"].append({
                    "species": p.get("species", ""),
                    "nickname": None,
                    "gender": None,
                    "level": 50,
                    "item": p.get("item"),
                    "ability": p.get("ability"),
                    "tera_type": p.get("tera_type"),
                    "nature": p.get("nature"),
                    "evs": {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0},
                    "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31},
                    "moves": clean_moves
                })

        canonical["teams"].append(canonical_team)

    canonical["teams"].sort(key=lambda x: x["rank"])
    canonical["source_count"] = len(canonical["teams"])

    # Save canonical JSON
    output_dir = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams")
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_dir / "vgc2026_top200_full_teams.json", 'w') as f:
        json.dump(canonical, f, indent=2)
    print(f"Saved canonical JSON ({len(canonical['teams'])} teams)")

    # Export Showdown text
    showdown_texts = []
    for ct in canonical["teams"]:
        if ct["parse_status"] == "complete":
            lines = []
            for p in ct["team"]:
                item_str = p["item"] or "No Item"
                lines.append(f"{p['species']} @ {item_str}")
                if p.get("ability"):
                    lines.append(f"Ability: {p['ability']}")
                if p.get("tera_type"):
                    lines.append(f"Tera Type: {p['tera_type']}")
                lines.append(f"Level: {p['level']}")

                # EVs
                ev_lines = [f"{v} {k.upper()}" for k, v in p.get("evs", {}).items() if v > 0]
                if ev_lines:
                    lines.append(f"EVs: {' / '.join(ev_lines)}")

                if p.get("nature"):
                    lines.append(f"{p['nature']} Nature")

                # IVs
                iv_parts = [f"{31-v} {k.upper()}" for k, v in p.get("ivs", {}).items() if v != 31]
                if iv_parts:
                    lines.append(f"IVs: {' / '.join(iv_parts)}")

                for move in p.get("moves", []):
                    lines.append(f"- {move}")

                lines.append("")

            if lines:
                showdown_texts.append("\n".join(lines).strip())

    with open(output_dir / "vgc2026_top200_showdown.txt", 'w') as f:
        f.write("\n\n".join(showdown_texts))
    print(f"Saved Showdown export ({len(showdown_texts)} complete teams)")

    # Export poke-env format
    poke_env_teams = []
    for ct in canonical["teams"]:
        if ct["parse_status"] == "complete":
            poke_env_teams.append({
                "name": f"{ct['player']} (Rank {ct['rank']})",
                "team": ct["team"]
            })

    with open(output_dir / "vgc2026_top200_poke_env_teams.json", 'w') as f:
        json.dump(poke_env_teams, f, indent=2)
    print(f"Saved poke-env teams ({len(poke_env_teams)} teams)")

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
                "missing_fields": "No source URL / not scraped" if ct["parse_status"] == "failed" else "Missing moves/items/abilities",
                "source_url": ct["source_url"],
                "source_platform": ct["source_platform"]
            })

    with open(output_dir / "vgc2026_top200_incomplete_report.csv", 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["id", "rank", "player", "status", "pokemon_count", "missing_fields", "source_url", "source_platform"])
        writer.writeheader()
        for row in incomplete:
            writer.writerow({
                **row,
                "missing_fields": row["missing_fields"] if isinstance(row["missing_fields"], str) else "; ".join(row["missing_fields"])
            })
    print(f"Saved incomplete report ({len(incomplete)} teams)")

    # Fetch log already exists
    fetch_log_src = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/vgc2026_top200_fetch_log.csv")
    fetch_log_dst = output_dir / "vgc2026_top200_fetch_log.csv"
    if fetch_log_src.exists():
        import shutil
        shutil.copy(fetch_log_src, fetch_log_dst)
        print(f"Copied fetch log")

    # Summary
    stats = Counter(ct["parse_status"] for ct in canonical["teams"])
    platforms = Counter(ct["source_platform"] for ct in canonical["teams"])

    print(f"\n=== Summary ===")
    print(f"Total teams: {len(canonical['teams'])}")
    print(f"Complete: {stats.get('complete', 0)}")
    print(f"Partial: {stats.get('partial', 0)}")
    print(f"Failed: {stats.get('failed', 0)}")
    print(f"Platforms: {dict(platforms)}")
    print(f"Output directory: {output_dir}")

if __name__ == "__main__":
    from datetime import datetime
    from collections import Counter
    import csv
    main()