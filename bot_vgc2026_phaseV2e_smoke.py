#!/usr/bin/env python3
"""
VGC 2026 Phase V2e — Structural smoke test for matchup_top4_v3.
"""

import argparse
import asyncio
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from bot_vgc2026_phaseV2c import VGCBattleRunnerV2c


class V2eSmokeRunner(VGCBattleRunnerV2c):
    """Run structural smoke with matchup_top4_v3 in every relevant arm."""

    def __init__(self, *args, smoke_battles: int = 2, **kwargs):
        self.smoke_battles = smoke_battles
        super().__init__(*args, **kwargs)

    def generate_arm_specifications(self) -> Dict[str, List[Dict[str, Any]]]:
        my_count = len(list(self.my_pool))
        opponent_count = len(list(self.opponent_pool))

        specs = {"A": [], "B": [], "C": [], "D1": [], "D2": []}

        for battle_idx in range(self.smoke_battles):
            pair_id = battle_idx
            specs["A"].append({
                "pair_id": pair_id,
                "our_team_idx": pair_id % my_count,
                "opp_team_idx": pair_id % opponent_count,
                "side": "p1",
                "player_policy": "matchup_top4_v3",
                "opponent_policy": "basic_top4",
            })
            specs["B"].append({
                "pair_id": pair_id,
                "our_team_idx": pair_id % my_count,
                "opp_team_idx": pair_id % opponent_count,
                "side": "p1",
                "player_policy": "matchup_top4_v3",
                "opponent_policy": "random",
            })
            specs["C"].append({
                "pair_id": pair_id,
                "our_team_idx": pair_id % my_count,
                "opp_team_idx": pair_id % opponent_count,
                "side": "p1",
                "player_policy": "matchup_top4_v3",
                "opponent_policy": "matchup_top4_v3",
            })
            specs["D1"].append({
                "pair_id": pair_id,
                "our_team_idx": pair_id % my_count,
                "opp_team_idx": pair_id % opponent_count,
                "side": "p1",
                "player_policy": "matchup_top4_v3",
                "opponent_policy": "random",
            })
            specs["D2"].append({
                "pair_id": pair_id,
                "our_team_idx": pair_id % my_count,
                "opp_team_idx": pair_id % opponent_count,
                "side": "p2",
                "player_policy": "random",
                "opponent_policy": "matchup_top4_v3",
            })

        return specs

    def get_preview_seeds(
        self,
        pair_id: int,
        battle_index: int,
        player_policy: str,
        opponent_policy: str,
    ) -> Tuple[int, int]:
        """Use stable per-policy seeds across D1/D2 side swaps."""
        base = self.seed + pair_id * 1000 + battle_index * 100
        policy_offsets = {
            "matchup_top4_v3": 404,
            "matchup_top4_v2": 101,
            "random": 202,
            "basic_top4": 303,
        }
        return (
            base + policy_offsets.get(player_policy, 0),
            base + policy_offsets.get(opponent_policy, 0),
        )

    async def run_all(self):
        specs = self.generate_arm_specifications()
        print(f"Starting V2e structural smoke")
        print(f"Battles per arm: {self.smoke_battles}")
        print(f"Artifact tag: {self.artifact_tag}")

        results = {}
        for arm in ["A", "B", "C", "D1", "D2"]:
            print(f"Running {arm}: {len(specs[arm])} battles...")
            results[arm] = await self.run_arm(arm, specs[arm])

        self._print_summary(results)
        return results


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-teams", type=int, default=5)
    parser.add_argument("--smoke-battles", type=int, default=2)
    parser.add_argument(
        "--artifact-tag",
        default=(
            "phaseV2e_smoke_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
        ),
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    runner = V2eSmokeRunner(
        limit_teams=args.limit_teams,
        artifact_tag=args.artifact_tag,
        overwrite=args.overwrite,
        smoke=args.smoke_battles > 0,
        smoke_battles=args.smoke_battles,
    )
    await runner.run_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))