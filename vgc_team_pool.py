#!/usr/bin/env python3
"""
VGC 2026 Team Pool Loader

Loads battle-ready teams from the VGC 2026 dataset with filtering support.
"""

import json
import random
from pathlib import Path
from typing import List, Dict, Any, Optional, Iterator
from dataclasses import dataclass


@dataclass
class VGCTeam:
    """Represents a VGC 2026 team with 6 Pokémon."""
    id: str
    rank: int
    player: str
    event: str
    record: str
    source_platform: str
    source_url: str
    parse_status: str
    pokemon: List[Dict[str, Any]]


class VGCTeamPool:
    """Loads and filters VGC 2026 teams from the battle-ready dataset."""

    def __init__(
        self,
        data_path: str = "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/vgc2026_top200_battle_ready.json",
        max_rank: Optional[int] = None,
        parse_status: str = "any",  # "complete_ots", "partial_ots", "any"
        limit: Optional[int] = None,
        seed: int = 42
    ):
        self.data_path = Path(data_path)
        self.max_rank = max_rank
        self.parse_status = parse_status
        self.limit = limit
        self.seed = seed

        self._teams: List[VGCTeam] = []
        self._load()

    def _load(self):
        """Load teams from JSON file with filtering."""
        with open(self.data_path) as f:
            data = json.load(f)

        for team_data in data.get("teams", []):
            # Filter by parse_status
            if self.parse_status != "any" and team_data.get("parse_status") != self.parse_status:
                continue

            # Filter by max_rank
            if self.max_rank is not None and team_data.get("rank", 0) > self.max_rank:
                continue

            # Validate team has 6 Pokémon
            pokemon = team_data.get("team", [])
            if len(pokemon) != 6:
                continue

            # Validate each Pokémon has required fields
            valid = True
            for p in pokemon:
                if not p.get("species") or not p.get("moves") or len(p.get("moves", [])) != 4:
                    valid = False
                    break
            if not valid:
                continue

            team = VGCTeam(
                id=team_data["id"],
                rank=team_data["rank"],
                player=team_data["player"],
                event=team_data["event"],
                record=team_data["record"],
                source_platform=team_data["source_platform"],
                source_url=team_data["source_url"],
                parse_status=team_data["parse_status"],
                pokemon=pokemon
            )
            self._teams.append(team)

        # Apply limit with shuffling
        if self.limit and len(self._teams) > self.limit:
            random.seed(self.seed)
            random.shuffle(self._teams)
            self._teams = self._teams[:self.limit]

        print(f"Loaded {len(self._teams)} teams (parse_status={self.parse_status}, max_rank={self.max_rank}, limit={self.limit})")

    def __iter__(self) -> Iterator[VGCTeam]:
        return iter(self._teams)

    def __len__(self) -> int:
        return len(self._teams)

    def get_team(self, index: int) -> Optional[VGCTeam]:
        """Get team by index."""
        if 0 <= index < len(self._teams):
            return self._teams[index]
        return None

    def get_team_by_rank(self, rank: int) -> Optional[VGCTeam]:
        """Get team by rank."""
        for team in self._teams:
            if team.rank == rank:
                return team
        return None

    def to_showdown_format(self, team: VGCTeam, include_tera: bool = False) -> str:
        """Convert a VGCTeam to Showdown importable format."""
        lines = []
        for p in team.pokemon:
            item_str = p.get("item") or "No Item"
            lines.append(f"{p['species'].capitalize()} @ {item_str}")

            if p.get("ability"):
                lines.append(f"Ability: {p['ability']}")

            if include_tera and p.get("tera_type"):
                lines.append(f"Tera Type: {p['tera_type']}")

            lines.append(f"Level: {p.get('level', 50)}")

            evs = p.get("evs", {})
            ev_lines = [f"{v} {k.upper()}" for k, v in evs.items() if v > 0]
            if ev_lines:
                lines.append(f"EVs: {' / '.join(ev_lines)}")

            nature = p.get("nature")
            if nature:
                lines.append(f"{nature.capitalize()} Nature")

            ivs = p.get("ivs", {})
            iv_parts = [f"{31-v} {k.upper()}" for k, v in ivs.items() if v != 31]
            if iv_parts:
                lines.append(f"IVs: {' / '.join(iv_parts)}")

            for move in p.get("moves", []):
                lines.append(f"- {move}")

            lines.append("")

        return "\n".join(lines).strip()

    def to_poke_env_team(self, team: VGCTeam) -> List[Dict[str, Any]]:
        """Convert a VGCTeam to poke-env compatible team format."""
        poke_env_team = []
        for p in team.pokemon:
            poke_env_team.append({
                "species": p["species"].capitalize(),
                "item": p.get("item", ""),
                "ability": p.get("ability", ""),
                "evs": p.get("evs", {}),
                "ivs": p.get("ivs", {}),
                "nature": p.get("nature", ""),
                "moves": p.get("moves", []),
                "level": p.get("level", 50)
            })
        return poke_env_team


def load_vgc_pool(
    max_rank: Optional[int] = None,
    parse_status: str = "any",
    limit: Optional[int] = None,
    seed: int = 42,
    data_path: Optional[str] = None
) -> VGCTeamPool:
    """Convenience function to load VGC team pool."""
    return VGCTeamPool(
        data_path=data_path or "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/vgc2026_top200_battle_ready.json",
        max_rank=max_rank,
        parse_status=parse_status,
        limit=limit,
        seed=seed
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Load VGC 2026 team pool")
    parser.add_argument("--max-rank", type=int, default=None)
    parser.add_argument("--parse-status", choices=["complete_ots", "partial_ots", "any"], default="any")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--show", action="store_true", help="Show loaded teams")
    parser.add_argument("--export-showdown", action="store_true", help="Export as Showdown format")

    args = parser.parse_args()

    pool = load_vgc_pool(
        max_rank=args.max_rank,
        parse_status=args.parse_status,
        limit=args.limit,
        seed=args.seed
    )

    if args.show:
        for team in pool:
            print(f"Rank {team.rank}: {team.player} ({team.event}) - {team.parse_status}")
            for p in team.pokemon:
                print(f"  {p['species']} @ {p.get('item')} | {p.get('ability')} | {p.get('nature')} | {p.get('moves')}")

    if args.export_showdown:
        for team in pool:
            print(pool.to_showdown_format(team))
            print("\n===\n")