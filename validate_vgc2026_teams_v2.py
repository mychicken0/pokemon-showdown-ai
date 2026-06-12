#!/usr/bin/env python3
"""
Validate VGC 2026 teams against local Pokémon Showdown.

Uses format: gen9championsvgc2026regma
"""

import json
import subprocess
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Any

def validate_team_showdown(team_data: Dict, format_name: str = "gen9championsvgc2026regma") -> Dict:
    """Validate a single team using local Showdown's validate-team command."""

    # Build Showdown format team text
    team_lines = []
    for p in team_data.get("team", []):
        item_str = p.get("item") or "No Item"
        # Skip if species is missing
        if not p.get("species"):
            continue

        team_lines.append(f"{p['species']} @ {item_str}")
        if p.get("ability"):
            team_lines.append(f"Ability: {p['ability']}")
        if p.get("tera_type"):
            team_lines.append(f"Tera Type: {p['tera_type']}")
        team_lines.append(f"Level: {p.get('level', 50)}")

        evs = p.get("evs", {})
        ev_parts = [f"{v} {k.upper()}" for k, v in evs.items() if v > 0]
        if ev_parts:
            team_lines.append(f"EVs: {' / '.join(ev_parts)}")

        if p.get("nature"):
            team_lines.append(f"{p['nature']} Nature")

        ivs = p.get("ivs", {})
        iv_parts = [f"{31-v} {k.upper()}" for k, v in ivs.items() if v != 31]
        if iv_parts:
            team_lines.append(f"IVs: {' / '.join(iv_parts)}")

        for move in p.get("moves", []):
            team_lines.append(f"- {move}")

        team_lines.append("")

    team_text = "\n".join(team_lines).strip()

    if not team_text:
        return {
            "valid": False,
            "error": "Empty team",
            "errors_detail": []
        }

    # Run validation using Showdown's validate-team
    showdown_script = "/home/phurin/Program/Showdown_AI/pokemon-showdown/pokemon-showdown"

    try:
        proc = subprocess.run(
            [showdown_script, "validate-team", "--format", format_name],
            input=team_text,
            text=True,
            capture_output=True,
            timeout=60,
            cwd="/home/phurin/Program/Showdown_AI/pokemon-showdown"
        )

        is_valid = proc.returncode == 0
        stderr = proc.stderr.strip()
        stdout = proc.stdout.strip()

        # Parse errors
        errors_detail = []
        if stderr:
            # Common error patterns
            for line in stderr.split('\n'):
                line = line.strip()
                if line and ('does not exist' in line or 'is not available' in line or
                           'cannot have' in line or 'is banned' in line or
                           'move' in line.lower() or 'ability' in line.lower() or
                           'item' in line.lower()):
                    errors_detail.append(line)

        return {
            "valid": is_valid,
            "error": stderr if not is_valid else "",
            "errors_detail": errors_detail,
            "raw_stdout": stdout,
            "raw_stderr": stderr
        }

    except subprocess.TimeoutExpired:
        return {
            "valid": False,
            "error": "Timeout",
            "errors_detail": ["Validation timed out after 60 seconds"]
        }
    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
            "errors_detail": [str(e)]
        }

def main():
    parser = argparse.ArgumentParser(description="Validate VGC 2026 teams with local Showdown")
    parser.add_argument("--input", default="/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/vgc2026_top200_battle_ready.json")
    parser.add_argument("--format", default="gen9championsvgc2026regma")
    parser.add_argument("--output", default="/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/vgc2026_top200_validation_report.json")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of teams to validate")
    parser.add_argument("--dry-run", action="store_true", help="Just show what would be validated")

    args = parser.parse_args()

    print(f"Loading teams from {args.input}...")
    with open(args.input) as f:
        data = json.load(f)

    teams = data.get("teams", [])
    print(f"Total teams in dataset: {len(teams)}")

    # Filter teams with complete_ots or partial_ots
    validatable = [t for t in teams if t.get("parse_status") in ("complete_ots", "partial_ots") and t.get("team")]
    print(f"Validatable teams (complete_ots/partial_ots with team data): {len(validatable)}")

    if args.limit:
        validatable = validatable[:args.limit]
        print(f"Limited to first {args.limit} teams")

    if args.dry_run:
        for t in validatable:
            print(f"  Would validate: Rank {t['rank']} - {t['player']} ({t['parse_status']})")
        return

    results = {
        "format": args.format,
        "total_teams": len(teams),
        "validatable_teams": len(validatable),
        "validated_teams": 0,
        "valid_teams": 0,
        "invalid_teams": 0,
        "invalid_species": 0,
        "invalid_items": 0,
        "invalid_abilities": 0,
        "invalid_moves": 0,
        "missing_tera": 0,
        "incomplete_pokemon": 0,
        "teams_with_simulation_fields": 0,
        "team_results": []
    }

    for i, team in enumerate(validatable):
        rank = team.get("rank")
        player = team.get("player")
        status = team.get("parse_status")
        team_obj = team.get("team", [])

        print(f"[{i+1}/{len(validatable)}] Validating Rank {rank}: {player} ({status})")

        # Check for simulation-filled fields
        has_sim = any(
            p.get("evs_source") == "simulation_default" or
            p.get("ivs_source") == "simulation_default" or
            p.get("tera_type_source") == "missing"
            for p in team_obj
        )
        if has_sim:
            results["teams_with_simulation_fields"] += 1

        # Check for incomplete pokemon
        incomplete = any(
            not p.get("species") or
            not p.get("moves") or len(p.get("moves", [])) < 4
            for p in team_obj
        )
        if incomplete:
            results["incomplete_pokemon"] += 1

        # Validate
        result = validate_team_showdown(team, args.format)

        # Categorize errors
        error_text = result.get("error", "").lower()
        if "does not exist" in error_text and ("pokemon" in error_text or "species" in error_text):
            results["invalid_species"] += 1
        if "item" in error_text and ("does not exist" in error_text or "not available" in error_text):
            results["invalid_items"] += 1
        if "ability" in error_text and ("does not exist" in error_text or "not available" in error_text):
            results["invalid_abilities"] += 1
        if "move" in error_text and ("does not exist" in error_text or "not available" in error_text):
            results["invalid_moves"] += 1

        if any(p.get("tera_type_source") == "missing" for p in team_obj):
            results["missing_tera"] += 1

        results["validated_teams"] += 1
        if result["valid"]:
            results["valid_teams"] += 1
            print(f"  ✓ VALID")
        else:
            results["invalid_teams"] += 1
            print(f"  ✗ INVALID: {result['error'][:200]}")

        results["team_results"].append({
            "id": team.get("id"),
            "rank": rank,
            "player": player,
            "parse_status": status,
            "teams_count": len(team_obj),
            "valid": result["valid"],
            "error": result["error"],
            "errors_detail": result.get("errors_detail", [])
        })

        # Save progress every 10 teams
        if (i + 1) % 10 == 0:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2)

    # Final save
    with open(args.output, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n=== Validation Summary ===")
    print(f"Format: {results['format']}")
    print(f"Total teams in dataset: {results['total_teams']}")
    print(f"Validatable teams: {results['validatable_teams']}")
    print(f"Validated: {results['validated_teams']}")
    print(f"Valid: {results['valid_teams']}")
    print(f"Invalid: {results['invalid_teams']}")
    print(f"Invalid species: {results['invalid_species']}")
    print(f"Invalid items: {results['invalid_items']}")
    print(f"Invalid abilities: {results['invalid_abilities']}")
    print(f"Invalid moves: {results['invalid_moves']}")
    print(f"Missing Tera: {results['missing_tera']}")
    print(f"Incomplete Pokemon: {results['incomplete_pokemon']}")
    print(f"Teams with simulation fields: {results['teams_with_simulation_fields']}")
    print(f"Results saved to: {args.output}")

if __name__ == "__main__":
    main()