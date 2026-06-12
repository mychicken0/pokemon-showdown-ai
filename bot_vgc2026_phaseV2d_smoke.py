#!/usr/bin/env python3
"""Ten-battle structural smoke for matchup_top4_v2."""

import argparse
import asyncio
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from bot_vgc2026_phaseV2c import VGCBattleRunnerV2c


class V2dSmokeRunner(VGCBattleRunnerV2c):
    """V2c controlled-preview runner with explicit V2d policy arms."""

    def generate_arm_specifications(self) -> Dict[str, List[Dict[str, Any]]]:
        my_count = len(list(self.my_pool))
        opponent_count = len(list(self.opponent_pool))
        count = self.smoke_battles

        def specs(
            player_policy: str,
            opponent_policy: str,
            side: str = "p1",
            opponent_offset: int = 0,
        ) -> List[Dict[str, Any]]:
            return [
                {
                    "pair_id": index,
                    "our_team_idx": index % my_count,
                    "opp_team_idx": (index + opponent_offset) % opponent_count,
                    "side": side,
                    "player_policy": player_policy,
                    "opponent_policy": opponent_policy,
                }
                for index in range(count)
            ]

        return {
            "A": specs("matchup_top4_v2", "basic_top4"),
            "B": specs("matchup_top4_v2", "random", opponent_offset=1),
            "C": specs("matchup_top4_v2", "matchup_top4_v2", opponent_offset=2),
            "D1": specs("matchup_top4_v2", "random"),
            "D2": specs("random", "matchup_top4_v2", side="p2"),
        }


def validate_smoke(runner: V2dSmokeRunner) -> List[str]:
    """Validate exact counts, outcomes, tags, previews, and policy coverage."""
    errors: List[str] = []

    with runner.csv_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    with runner.preview_csv_path.open(newline="") as handle:
        preview_rows = list(csv.DictReader(handle))
    with runner.jsonl_path.open() as handle:
        json_rows = [json.loads(line) for line in handle if line.strip()]

    if len(rows) != 10:
        errors.append(f"benchmark rows={len(rows)}, expected 10")
    if len(json_rows) != 10:
        errors.append(f"jsonl records={len(json_rows)}, expected 10")
    if len(preview_rows) != 20:
        errors.append(f"preview rows={len(preview_rows)}, expected 20")

    arm_counts = Counter(row["battle_tag"].split("_", 1)[0] for row in rows)
    if arm_counts != Counter({"A": 2, "B": 2, "C": 2, "D1": 2, "D2": 2}):
        errors.append(f"wrong arm counts: {dict(arm_counts)}")

    tags = [row.get("battle_tag") for row in json_rows]
    if len(set(tags)) != len(tags):
        errors.append("duplicate battle tags")
    if any(row.get("battle_result") not in {"win", "loss", "tie"} for row in json_rows):
        errors.append("missing or invalid battle outcome")
    if any(row.get("preview_matches_plan") != "True" for row in preview_rows):
        errors.append("preview mismatch")

    policies = Counter(row.get("player_policy") for row in preview_rows)
    if policies["matchup_top4_v2"] == 0:
        errors.append("matchup_top4_v2 was not exercised")

    expected_policies = {
        "A": ("matchup_top4_v2", "basic_top4"),
        "B": ("matchup_top4_v2", "random"),
        "C": ("matchup_top4_v2", "matchup_top4_v2"),
        "D1": ("matchup_top4_v2", "random"),
        "D2": ("random", "matchup_top4_v2"),
    }
    for row in rows:
        arm = row["battle_tag"].split("_", 1)[0]
        actual = (row["player_policy"], row["opponent_policy"])
        if actual != expected_policies[arm]:
            errors.append(f"{arm} policies={actual}, expected={expected_policies[arm]}")

    return errors


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-tag",
        default=f"phaseV2d1_smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit-teams", type=int, default=10)
    args = parser.parse_args()

    runner = V2dSmokeRunner(
        limit_teams=args.limit_teams,
        artifact_tag=args.artifact_tag,
        overwrite=args.overwrite,
        smoke=True,
        smoke_battles=2,
    )
    await runner.run_all()

    errors = validate_smoke(runner)
    if errors:
        print("V2d smoke validation FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 2

    print("V2d smoke validation PASS")
    print(f"  CSV: {runner.csv_path}")
    print(f"  JSONL: {runner.jsonl_path}")
    print(f"  Preview: {runner.preview_csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
