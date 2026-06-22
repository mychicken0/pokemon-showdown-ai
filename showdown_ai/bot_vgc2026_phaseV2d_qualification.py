#!/usr/bin/env python3
"""Paired qualification for matchup_top4_v2 versus random preview."""

import argparse
import asyncio
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from bot_vgc2026_phaseV2c import VGCBattleRunnerV2c


class V2dPairedQualificationRunner(VGCBattleRunnerV2c):
    """Run D1/D2 policy swaps over identical team pairs."""

    def __init__(self, *args, pairs: int = 100, **kwargs):
        self.pairs = pairs
        super().__init__(*args, **kwargs)

    def get_preview_seeds(
        self,
        pair_id: int,
        battle_index: int,
        player_policy: str,
        opponent_policy: str,
    ) -> Tuple[int, int]:
        """Use stable per-policy seeds across D1/D2 side swaps."""
        base = self.seed + pair_id * 1000
        policy_offsets = {
            "matchup_top4_v2": 101,
            "random": 202,
            "basic_top4": 303,
        }
        return (
            base + policy_offsets[player_policy],
            base + policy_offsets[opponent_policy],
        )

    def generate_arm_specifications(self) -> Dict[str, List[Dict[str, Any]]]:
        my_count = len(list(self.my_pool))
        opponent_count = len(list(self.opponent_pool))
        d1 = []
        d2 = []
        for pair_id in range(self.pairs):
            common = {
                "pair_id": pair_id,
                "our_team_idx": pair_id % my_count,
                "opp_team_idx": pair_id % opponent_count,
            }
            d1.append({
                **common,
                "side": "p1",
                "player_policy": "matchup_top4_v2",
                "opponent_policy": "random",
            })
            d2.append({
                **common,
                "side": "p2",
                "player_policy": "random",
                "opponent_policy": "matchup_top4_v2",
            })
        return {"D1": d1, "D2": d2}

    async def run_all(self):
        specs = self.generate_arm_specifications()
        print("Starting V2d paired qualification")
        print(f"Pairs: {self.pairs}; battles: {self.pairs * 2}")
        print(f"Artifact tag: {self.artifact_tag}")
        results = {
            "D1": await self.run_arm("D1", specs["D1"]),
            "D2": await self.run_arm("D2", specs["D2"]),
        }
        self._print_summary(results)
        return results


def validate_qualification_artifacts(
    csv_path: Path,
    jsonl_path: Path,
    preview_path: Path,
    expected_pairs: int,
) -> List[str]:
    """Validate complete paired artifacts before analysis."""
    errors: List[str] = []
    for path in (csv_path, jsonl_path, preview_path):
        if not path.exists():
            errors.append(f"missing artifact: {path}")
    if errors:
        return errors
    with csv_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    with preview_path.open(newline="") as handle:
        previews = list(csv.DictReader(handle))
    with jsonl_path.open() as handle:
        records = [json.loads(line) for line in handle if line.strip()]

    expected_battles = expected_pairs * 2
    if len(rows) != expected_battles:
        errors.append(f"CSV rows={len(rows)}, expected={expected_battles}")
    if len(records) != expected_battles:
        errors.append(f"JSONL records={len(records)}, expected={expected_battles}")
    if len(previews) != expected_battles * 2:
        errors.append(
            f"preview rows={len(previews)}, expected={expected_battles * 2}"
        )

    tags = [record.get("battle_tag") for record in records]
    if len(set(tags)) != len(tags):
        errors.append("duplicate battle tags")
    if any(
        record.get("battle_result") not in {"win", "loss", "tie"}
        for record in records
    ):
        errors.append("invalid or missing outcomes")
    if any(row.get("preview_matches_plan") != "True" for row in previews):
        errors.append("preview mismatch")
    if any(not row.get("observed_actual_lead_on_turn1", "").strip() for row in previews):
        errors.append("missing observed lead")

    by_pair: Dict[int, set] = {}
    for row in rows:
        try:
            pair_id = int(row["pair_id"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"invalid pair_id in row: {row.get('battle_tag', '')}")
            continue
        arm = row["battle_tag"].split("_", 1)[0]
        if arm not in {"D1", "D2"}:
            errors.append(f"unexpected arm for {row['battle_tag']}")
            continue
        by_pair.setdefault(pair_id, set()).add(arm)
        expected = (
            ("matchup_top4_v2", "random")
            if arm == "D1"
            else ("random", "matchup_top4_v2")
        )
        if (row["player_policy"], row["opponent_policy"]) != expected:
            errors.append(f"wrong policies for {row['battle_tag']}")
    if len(by_pair) != expected_pairs:
        errors.append(f"unique pairs={len(by_pair)}, expected={expected_pairs}")
    if any(arms != {"D1", "D2"} for arms in by_pair.values()):
        errors.append("incomplete D1/D2 pair")
    return errors


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=100)
    parser.add_argument("--limit-teams", type=int, default=None)
    parser.add_argument(
        "--artifact-tag",
        default=(
            "phaseV2d2_paired_qualification_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
        ),
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    runner = V2dPairedQualificationRunner(
        pairs=args.pairs,
        limit_teams=args.limit_teams,
        artifact_tag=args.artifact_tag,
        overwrite=args.overwrite,
    )
    await runner.run_all()
    errors = validate_qualification_artifacts(
        runner.csv_path,
        runner.jsonl_path,
        runner.preview_csv_path,
        args.pairs,
    )
    if errors:
        print("Qualification artifact validation FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 2
    print("Qualification artifact validation PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
