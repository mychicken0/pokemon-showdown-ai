#!/usr/bin/env python3
"""
Phase T6 - Local Validation
Validate teams using local Pokémon Showdown's team validator.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any

def validate_teams(teams_file: str, format_name: str = "gen9vgc2023regulatione") -> Dict[str, Any]:
    """
    Validate teams using local Showdown's validate-team command.
    """
    # Read teams
    with open(teams_file) as f:
        data = json.load(f)

    results = {
        "format": format_name,
        "total_teams": 0,
        "valid_teams": 0,
        "invalid_teams": 0,
        "team_results": []
    }

    # Get all complete teams
    complete_teams = [t for t in data.get("teams", []) if t.get("parse_status") == "complete"]
    results["total_teams"] = len(complete_teams)

    showdown_path = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown")
    validate_script = showdown_path / "pokemon-showdown"

    # Try using the validate-team command
    for team_data in complete_teams:
        team_id = team_data["id"]
        rank = team_data["rank"]

        # Build Showdown format team text
        team_lines = []
        for p in team_data["team"]:
            item_str = p["item"] or "No Item"
            team_lines.append(f"{p['species']} @ {item_str}")
            if p.get("ability"):
                team_lines.append(f"Ability: {p['ability']}")
            if p.get("tera_type"):
                team_lines.append(f"Tera Type: {p['tera_type']}")
            team_lines.append(f"Level: {p['level']}")

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

        # Run validation using Showdown's validate-team
        try:
            # Use the command line tool
            cmd = [str(validate_script), "validate-team", "--format", format_name]

            # Write team to stdin
            proc = subprocess.run(
                cmd,
                input=team_text,
                text=True,
                capture_output=True,
                timeout=30,
                cwd=showdown_path
            )

            is_valid = proc.returncode == 0
            if is_valid:
                results["valid_teams"] += 1
            else:
                results["invalid_teams"] += 1

            results["team_results"].append({
                "id": team_id,
                "rank": rank,
                "valid": is_valid,
                "errors": proc.stderr.strip() if proc.stderr else "",
                "output": proc.stdout.strip() if proc.stdout else ""
            })

            print(f"  Rank {rank}: {'VALID' if is_valid else 'INVALID'}")

        except subprocess.TimeoutExpired:
            results["invalid_teams"] += 1
            results["team_results"].append({
                "id": team_id,
                "rank": rank,
                "valid": False,
                "errors": "Timeout",
                "output": ""
            })
            print(f"  Rank {rank}: TIMEOUT")
        except Exception as e:
            results["invalid_teams"] += 1
            results["team_results"].append({
                "id": team_id,
                "rank": rank,
                "valid": False,
                "errors": str(e),
                "output": ""
            })
            print(f"  Rank {rank}: ERROR - {e}")

    return results

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Validate VGC 2026 teams with local Showdown")
    parser.add_argument("--input", default="/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/vgc2026_top200_full_teams.json")
    parser.add_argument("--format", default="gen9vgc2023regulatione")
    parser.add_argument("--output", default="/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/vgc2026_top200_validation_report.json")

    args = parser.parse_args()

    print(f"Loading teams from {args.input}...")
    print(f"Validating with format: {args.format}")

    results = validate_teams(args.input, args.format)

    # Save results
    with open(args.output, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n=== Validation Summary ===")
    print(f"Format: {results['format']}")
    print(f"Total teams tested: {results['total_teams']}")
    print(f"Valid: {results['valid_teams']}")
    print(f"Invalid: {results['invalid_teams']}")
    print(f"Results saved to: {args.output}")

if __name__ == "__main__":
    main()