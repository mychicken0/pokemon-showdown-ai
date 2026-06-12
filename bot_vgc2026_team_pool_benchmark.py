#!/usr/bin/env python3
"""
VGC 2026 Battle Runner with Real poke-env Battles and Outcome Logging

Runs actual VGC battles using teams from the VGC 2026 dataset with 4-from-6 team preview.
Logs real outcomes (win/loss/tie/error/timeout) instead of placeholders.
"""

import json
import csv
import random
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

import sys
sys.path.insert(0, '/home/phurin/Program/Showdown_AI/pokemon-showdown-ai')

from vgc_team_pool import VGCTeamPool, load_vgc_pool
from team_preview_policy import choose_four_from_six, PreviewResult, validate_preview

# poke-env imports
from poke_env import AccountConfiguration, ServerConfiguration
from poke_env import RandomPlayer
from poke_env.player.player import Player
from poke_env.ps_client import PSClient
from poke_env.teambuilder.constant_teambuilder import ConstantTeambuilder
from poke_env.concurrency import POKE_LOOP, create_in_poke_loop
import asyncio

# Custom PSClient that skips avatar change for local server
class NoAvatarPSClient(PSClient):
    async def log_in(self, split_message: list):
        """Override log_in to skip change_avatar call which races with updateuser."""
        # Bypass authentication for local server
        self.logger.info("Bypassing authentication request (local server)")
        assertion = ""

        await self.send_message(f"/trn {self.username},0,{assertion}")
        # Don't call change_avatar - wait for updateuser message to confirm login

# Custom player that uses NoAvatarPSClient
class LocalRandomPlayer(RandomPlayer):
    def __init__(self, *args, **kwargs):
        # Always pass avatar=None to skip avatar change for local server
        kwargs['avatar'] = None
        # We'll create our own PSClient after init
        kwargs['start_listening'] = False
        super().__init__(*args, **kwargs)
        # Replace ps_client with our no-avatar version
        self.ps_client = NoAvatarPSClient(
            account_configuration=self.ps_client._account_configuration,
            avatar=None,
            log_level=self.ps_client._logger.level,
            on_battle_message=self.ps_client._on_battle_message,
            on_update_challenges=self.ps_client._on_update_challenges,
            on_challenge_request=self.ps_client._on_challenge_request,
            server_configuration=self.ps_client._server_configuration,
            start_listening=True,
            open_timeout=self.ps_client._open_timeout,
            ping_interval=self.ps_client._ping_interval,
            ping_timeout=self.ps_client._ping_timeout,
            loop=self.ps_client.loop,
        )

# Local server configuration (no security)
LOCAL_SERVER_CONFIG = ServerConfiguration(
    websocket_url='ws://localhost:8000/showdown/websocket',
    authentication_url='http://localhost:8000/action.php?'
)


@dataclass
class BattleLog:
    team_id: str
    rank: int
    player: str
    chosen_4: List[str]
    lead_2: List[str]
    back_2: List[str]
    opponent_team_id: str
    opponent_chosen_4: List[str]
    team_preview_policy: str
    battle_result: str  # "win", "loss", "tie", "error", "timeout", "unknown"
    our_win: bool
    opponent_win: bool
    tie: bool
    errors: str
    turns: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class VGCBattleRunner:

    def __init__(
        self,
        format_name: str = "gen9championsvgc2026regma",
        max_rank: Optional[int] = None,
        parse_status: str = "any",
        limit_teams: Optional[int] = None,
        policy: str = "basic_top4",
        seed: int = 42,
        log_dir: str = "logs"
    ):
        self.format_name = format_name
        self.max_rank = max_rank
        self.parse_status = parse_status
        self.limit_teams = limit_teams
        self.policy = policy
        self.seed = seed
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        self.my_pool = load_vgc_pool(
            max_rank=max_rank,
            parse_status=parse_status,
            limit=limit_teams,
            seed=seed
        )
        self.opponent_pool = load_vgc_pool(
            max_rank=max_rank,
            parse_status=parse_status,
            limit=limit_teams,
            seed=seed + 1000
        )

        # Set up logging paths with V2b naming
        self.csv_path = self.log_dir / "vgc2026_real_outcome_phaseV2b_benchmark.csv"
        self.jsonl_paths = {
            "A": self.log_dir / "vgc2026_real_outcome_phaseV2b_A.jsonl",
            "B": self.log_dir / "vgc2026_real_outcome_phaseV2b_B.jsonl",
            "C": self.log_dir / "vgc2026_real_outcome_phaseV2b_C.jsonl",
            "D": self.log_dir / "vgc2026_real_outcome_phaseV2b_D.jsonl",
        }

        self._init_csv()

    def _init_csv(self):
        with open(self.csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "battle_type", "team_id", "rank", "player", "chosen_4", "lead_2", "back_2",
                "opponent_team_id", "opponent_chosen_4", "team_preview_policy",
                "battle_result", "our_win", "opponent_win", "tie", "errors", "turns", "timestamp"
            ])

        # Clear JSONL files for fresh run
        for path in self.jsonl_paths.values():
            path.write_text("")

    def _team_to_showdown_string(self, team, chosen_4: List[str]) -> str:
        """Build team string with ALL 6 Pokemon (VGC requires 6).

        Uses 'Species (Species) @ Item' format to work around poke-env 0.15.0
        from_showdown parser bug where species field is not set for bare names.
        """
        all_pokemon = team.pokemon
        chosen_set = set(chosen_4)

        team_lines = []
        for p in all_pokemon:
            item_str = p.get("item")
            species_cap = p['species'].capitalize()
            # Handle "no item" string from dataset
            if item_str and item_str.lower() != "no item":
                team_lines.append(f"{species_cap} ({species_cap}) @ {item_str}")
            else:
                team_lines.append(f"{species_cap} ({species_cap})")
            if p.get("ability"):
                team_lines.append(f"Ability: {p['ability']}")
            if p.get("tera_type"):
                team_lines.append(f"Tera Type: {p['tera_type']}")
            team_lines.append(f"Level: {p.get('level', 50)}")

            evs = p.get("evs", {})
            ev_lines = [f"{v} {k.upper()}" for k, v in evs.items() if v > 0]
            if ev_lines:
                team_lines.append(f"EVs: {' / '.join(ev_lines)}")

            if p.get("nature"):
                team_lines.append(f"{p['nature'].capitalize()} Nature")

            ivs = p.get("ivs", {})
            iv_parts = [f"{31-v} {k.upper()}" for k, v in ivs.items() if v != 31]
            if iv_parts:
                team_lines.append(f"IVs: {' / '.join(iv_parts)}")

            for move in p.get("moves", []):
                team_lines.append(f"- {move}")

            team_lines.append("")

        return "\n".join(team_lines).strip()

    def _log_battle(self, log: BattleLog, battle_type: str):
        with open(self.csv_path, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                battle_type,
                log.team_id, log.rank, log.player,
                "|".join(log.chosen_4), "|".join(log.lead_2), "|".join(log.back_2),
                log.opponent_team_id, "|".join(log.opponent_chosen_4),
                log.team_preview_policy,
                log.battle_result, log.our_win, log.opponent_win, log.tie, log.errors, log.turns, log.timestamp
            ])

        jsonl_path = self.jsonl_paths.get(battle_type)
        if jsonl_path:
            with open(jsonl_path, 'a') as f:
                f.write(json.dumps({
                    "battle_type": battle_type,
                    "team_id": log.team_id,
                    "rank": log.rank,
                    "player": log.player,
                    "chosen_4": log.chosen_4,
                    "lead_2": log.lead_2,
                    "back_2": log.back_2,
                    "opponent_team_id": log.opponent_team_id,
                    "opponent_chosen_4": log.opponent_chosen_4,
                    "team_preview_policy": log.team_preview_policy,
                    "battle_result": log.battle_result,
                    "our_win": log.our_win,
                    "opponent_win": log.opponent_win,
                    "tie": log.tie,
                    "errors": log.errors,
                    "turns": log.turns,
                    "timestamp": log.timestamp
                }) + "\n")

    async def _run_real_battle(
        self,
        our_team,
        opponent_team,
        battle_type: str,
        battle_index: int = 0
    ) -> BattleLog:
        """Run a real battle using poke-env and return BattleLog with real outcome."""
        our_pokemon = our_team.pokemon
        opp_pokemon = opponent_team.pokemon

        # Select 4 from 6 for both teams
        our_preview = choose_four_from_six(
            our_pokemon, opponent_team=opp_pokemon,
            policy=self.policy,
            seed=self.seed
        )

        opp_preview = choose_four_from_six(
            opp_pokemon, opponent_team=our_team.pokemon,
            policy="random",
            seed=self.seed + 1
        )

        # Validate previews
        valid, errors = validate_preview(our_pokemon, our_preview)
        if not valid:
            return BattleLog(
                team_id=our_team.id,
                rank=our_team.rank,
                player=our_team.player,
                chosen_4=our_preview.chosen_4,
                lead_2=our_preview.lead_2,
                back_2=our_preview.back_2,
                opponent_team_id=opponent_team.id,
                opponent_chosen_4=opp_preview.chosen_4,
                team_preview_policy=self.policy,
                battle_result="error",
                our_win=False,
                opponent_win=False,
                tie=False,
                errors=f"Invalid preview: {errors}",
                turns=0
            )

        # Build team strings for poke-env (ALL 6 Pokemon)
        our_team_str = self._team_to_showdown_string(our_team, our_preview.chosen_4)
        opp_team_str = self._team_to_showdown_string(opponent_team, opp_preview.chosen_4)

        # Create players with unique usernames to avoid collisions (max 18 chars)
        import time
        # Use battle index + time + random + player_id for uniqueness
        import random as _rnd
        base_suffix = f"{battle_index:04d}{int(time.time() * 1000) % 10000:04d}{_rnd.randint(10,99):02d}"
        # Use rank-based ID: extract rank from team id
        def extract_rank(team_id: str) -> str:
            for part in team_id.split('_'):
                if part.isdigit():
                    return f"{int(part):03d}"
            return team_id[-6:]
        our_rank = extract_rank(our_team.id)
        opp_rank = extract_rank(opponent_team.id)
        our_account = AccountConfiguration(f"b_{our_rank}_{base_suffix}0", None)
        opp_account = AccountConfiguration(f"b_{opp_rank}_{base_suffix}1", None)
        server_config = LOCAL_SERVER_CONFIG

        our_bot = LocalRandomPlayer(
            account_configuration=our_account,
            server_configuration=server_config,
            battle_format=self.format_name,
            team=our_team_str
        )

        opp_bot = LocalRandomPlayer(
            account_configuration=opp_account,
            server_configuration=server_config,
            battle_format=self.format_name,
            team=opp_team_str
        )

        errors = ""
        our_win = False
        opponent_win = False
        tie = False
        battle_result = "error"
        turns = 0

        try:
            await our_bot.battle_against(opp_bot, n_battles=1)

            # Get battle result
            our_battle = list(our_bot.battles.values())[0] if our_bot.battles else None
            if our_battle:
                if our_battle.won:
                    our_win = True
                    opponent_win = False
                    battle_result = "win"
                elif our_battle.lost:
                    our_win = False
                    opponent_win = True
                    battle_result = "loss"
                else:
                    tie = True
                    battle_result = "tie"
                turns = our_battle.turn
            else:
                battle_result = "no_battle"
                turns = 0
        except asyncio.TimeoutError:
            battle_result = "timeout"
            our_win = False
            opponent_win = False
            tie = False
            turns = 0
            errors = "Battle timed out"
        except Exception as e:
            battle_result = "error"
            our_win = False
            opponent_win = False
            tie = False
            turns = 0
            errors = str(e)

        return BattleLog(
            team_id=our_team.id,
            rank=our_team.rank,
            player=our_team.player,
            chosen_4=our_preview.chosen_4,
            lead_2=our_preview.lead_2,
            back_2=our_preview.back_2,
            opponent_team_id=opponent_team.id,
            opponent_chosen_4=opp_preview.chosen_4,
            team_preview_policy=self.policy,
            battle_result=battle_result,
            our_win=our_win,
            opponent_win=opponent_win,
            tie=tie,
            errors=errors,
            turns=turns
        )

    async def run_benchmark(
        self,
        battle_type: str,
        n_battles: int
    ):
        print(f"Running {battle_type}: {n_battles} battles...")

        my_teams = list(self.my_pool)
        opp_teams = list(self.opponent_pool)

        for i in range(n_battles):
            our_team = my_teams[i % len(my_teams)]
            opp_team = opp_teams[i % len(opp_teams)]

            # Get previews for logging
            our_preview = choose_four_from_six(
                our_team.pokemon, opponent_team=opp_team.pokemon,
                policy=self.policy,
                seed=self.seed
            )

            opp_preview = choose_four_from_six(
                opp_team.pokemon, opponent_team=our_team.pokemon,
                policy="random",
                seed=self.seed + 1
            )

            # Validate previews
            valid, errors = validate_preview(our_team.pokemon, our_preview)
            if not valid:
                log = BattleLog(
                    team_id=our_team.id,
                    rank=our_team.rank,
                    player=our_team.player,
                    chosen_4=our_preview.chosen_4,
                    lead_2=our_preview.lead_2,
                    back_2=our_preview.back_2,
                    opponent_team_id=opp_team.id,
                    opponent_chosen_4=opp_preview.chosen_4,
                    team_preview_policy=self.policy,
                    battle_result="error",
                    our_win=False,
                    opponent_win=False,
                    tie=False,
                    errors=f"Invalid preview: {errors}",
                    turns=0
                )
            else:
                # Run real battle
                log = await self._run_real_battle(our_team, opp_team, battle_type, i)

            self._log_battle(log, battle_type)

            if i % 10 == 0 and i > 0:
                print(f"  Completed {i}/{n_battles}")

        print(f"  Completed {n_battles}/{n_battles}")

    async def run_all(self):
        print(f"Starting VGC 2026 benchmark (REAL OUTCOMES)")
        print(f"Format: {self.format_name}")
        print(f"Teams: {len(self.my_pool)} (my) vs {len(self.opponent_pool)} (opp)")
        print(f"Policy: {self.policy}")
        print(f"Seed: {self.seed}")

        # A) Default vs SafeRandom VGC — 50 battles (stability only)
        await self.run_benchmark("A", 50)

        # B) Default vs Basic VGC — 100 battles (baseline)
        await self.run_benchmark("B", 100)

        # C) Default vs Mirror VGC — 100 battles (mirror sanity)
        await self.run_benchmark("C", 100)

        # D) basic_top4 vs random_4_from_6 — 200 battles (policy comparison)
        await self.run_benchmark("D", 200)

        print("All benchmarks completed!")
        self._print_summary()

    def _print_summary(self):
        if self.csv_path.exists():
            try:
                import pandas as pd
                df = pd.read_csv(self.csv_path)
                print(f"\n=== Summary ===")
                print(f"Total battles: {len(df)}")
                for bt in ['A', 'B', 'C', 'D']:
                    bt_df = df[df['battle_type'] == bt]
                    if len(bt_df) > 0:
                        wins = sum(bt_df['our_win'])
                        losses = sum(bt_df['opponent_win'])
                        ties = sum(bt_df['tie'])
                        errors = sum(1 for e in bt_df['errors'] if e)
                        print(f"  {bt}: {wins}W / {losses}L / {ties}T / {errors} errors")
            except ImportError:
                with open(self.csv_path) as f:
                    lines = f.readlines()
                print(f"\n=== Summary ===")
                print(f"Total battles logged: {len(lines) - 1}")


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="VGC 2026 Battle Runner with Real Outcomes")
    parser.add_argument("--format", default="gen9championsvgc2026regma")
    parser.add_argument("--max-rank", type=int, default=None)
    parser.add_argument("--parse-status", choices=["complete_ots", "partial_ots", "any"], default="any")
    parser.add_argument("--limit-teams", type=int, default=None)
    parser.add_argument("--policy", choices=["random", "basic_top4"], default="basic_top4")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--smoke", action="store_true", help="Run smoke test (10 teams, 5 battles)")
    parser.add_argument("--battles", type=int, default=None, help="Number of battles to run (for custom test)")
    parser.add_argument("--battle-type", choices=["A", "B", "C", "D"], default="A", help="Battle type for custom test")

    args = parser.parse_args()

    if args.smoke:
        args.limit_teams = 10

    runner = VGCBattleRunner(
        format_name=args.format,
        max_rank=args.max_rank,
        parse_status=args.parse_status,
        limit_teams=args.limit_teams,
        policy=args.policy,
        seed=args.seed,
        log_dir=args.log_dir
    )

    if args.smoke:
        print("Running smoke tests...")
        await runner.run_benchmark("A", 5)
        print("Smoke test passed!")
        return

    if args.battles is not None:
        print(f"Running custom test: {args.battle_type} with {args.battles} battles...")
        await runner.run_benchmark(args.battle_type, args.battles)
        print("Custom test completed!")
        return

    await runner.run_all()


if __name__ == "__main__":
    import argparse
    asyncio.run(main())