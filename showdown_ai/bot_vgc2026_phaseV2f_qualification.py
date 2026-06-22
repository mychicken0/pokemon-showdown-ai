#!/usr/bin/env python3
"""Paired qualification for matchup_top4_v3 versus random preview.

Reuses the V2c controlled-preview infrastructure and the V2d paired
qualification runner pattern. The only changes from V2d are:

- D1: matchup_top4_v3 as p1/player versus random as p2.
- D2: random as p1/player versus matchup_top4_v3 as p2.
- Policy-stable seeds use distinct offsets for v2 and v3.
- Artifact tag defaults to a unique, never-overwriting label.
- A V3-specific strict artifact validator is included.

The runner refuses to overwrite an existing artifact unless
`--overwrite` is supplied.
"""

import argparse
import asyncio
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from bot_vgc2026_phaseV2d_qualification import V2dPairedQualificationRunner
from bot_vgc2026_phaseV2c import VGCBattleRunnerV2c


class V2fPairedQualificationRunner(V2dPairedQualificationRunner):
    """Run D1/D2 policy swaps with matchup_top4_v3 versus random."""

    V3_POLICY: str = "matchup_top4_v3"
    RANDOM_POLICY: str = "random"

    def get_preview_seeds(
        self,
        pair_id: int,
        battle_index: int,
        player_policy: str,
        opponent_policy: str,
    ) -> Tuple[int, int]:
        """Stable per-policy seeds for V3 vs Random, distinct from
        the V2 offset to keep V2 qualification artifacts valid."""
        base = self.seed + pair_id * 1000
        policy_offsets = {
            "matchup_top4_v3": 401,
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
        d1: List[Dict[str, Any]] = []
        d2: List[Dict[str, Any]] = []
        for pair_id in range(self.pairs):
            common = {
                "pair_id": pair_id,
                "our_team_idx": pair_id % my_count,
                "opp_team_idx": pair_id % opponent_count,
            }
            d1.append({
                **common,
                "side": "p1",
                "player_policy": self.V3_POLICY,
                "opponent_policy": self.RANDOM_POLICY,
            })
            d2.append({
                **common,
                "side": "p2",
                "player_policy": self.RANDOM_POLICY,
                "opponent_policy": self.V3_POLICY,
            })
        return {"D1": d1, "D2": d2}


def validate_v2f_qualification_artifacts(
    csv_path: Path,
    jsonl_path: Path,
    preview_path: Path,
    expected_pairs: int,
) -> List[str]:
    """Strict validator for the V3 paired qualification.

    Hard-fails on any of the following:
    - wrong CSV/JSONL/preview row counts
    - malformed JSONL
    - duplicate battle tags
    - missing or non-boolean outcomes
    - timeout / error / no_battle outcomes
    - unexpected arms
    - wrong D1/D2 policy assignment
    - missing pair
    - duplicate D1 or D2 row for a pair
    - D1/D2 team identity mismatch
    - preview mismatch
    - missing observed leads
    - missing V3 preview evidence rows
    - V3 plan mismatch between D1 and D2 when both player_policy=V3
    - CSV/JSONL disagreement
    """
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
    try:
        with jsonl_path.open() as handle:
            records = [json.loads(line) for line in handle if line.strip()]
    except json.JSONDecodeError as exc:
        errors.append(f"malformed JSONL: {exc}")
        return errors

    expected_battles = expected_pairs * 2
    if len(rows) != expected_battles:
        errors.append(
            f"CSV rows={len(rows)}, expected={expected_battles}"
        )
    if len(records) != expected_battles:
        errors.append(
            f"JSONL records={len(records)}, expected={expected_battles}"
        )
    if len(previews) != expected_battles * 2:
        errors.append(
            f"preview rows={len(previews)}, "
            f"expected={expected_battles * 2}"
        )

    tags = [record.get("battle_tag") for record in records]
    if len(set(tags)) != len(tags):
        errors.append("duplicate battle tags")
    for record in records:
        outcome = record.get("battle_result")
        if outcome not in {"win", "loss", "tie"}:
            errors.append(
                f"missing or invalid outcome: {record.get('battle_tag')}"
            )
        if outcome in {"timeout", "error", "no_battle"}:
            errors.append(
                f"disallowed outcome {outcome!r} for "
                f"{record.get('battle_tag')}"
            )
        our_win = record.get("our_win")
        opponent_win = record.get("opponent_win")
        if not isinstance(our_win, bool):
            errors.append(
                f"non-boolean our_win for {record.get('battle_tag')}: "
                f"{our_win!r}"
            )
        if not isinstance(opponent_win, bool):
            errors.append(
                f"non-boolean opponent_win for "
                f"{record.get('battle_tag')}: {opponent_win!r}"
            )

    csv_tags = {row.get("battle_tag") for row in rows}
    jsonl_tags = {record.get("battle_tag") for record in records}
    if csv_tags != jsonl_tags:
        errors.append("CSV/JSONL disagreement on battle tags")
    csv_by_tag = {row.get("battle_tag"): row for row in rows}
    jsonl_by_tag = {record.get("battle_tag"): record for record in records}
    for tag in sorted(csv_tags & jsonl_tags):
        csv_row = csv_by_tag[tag]
        jsonl_row = jsonl_by_tag[tag]
        for field in (
            "pair_id", "team_id", "opponent_team_id",
            "player_policy", "opponent_policy", "battle_result",
        ):
            if str(csv_row.get(field)) != str(jsonl_row.get(field)):
                errors.append(
                    f"CSV/JSONL disagreement for {tag} field={field}"
                )
        for field in ("our_win", "opponent_win", "tie"):
            csv_value = str(csv_row.get(field)).strip().lower()
            json_value = jsonl_row.get(field)
            if csv_value not in {"true", "false"} or (
                (csv_value == "true") != json_value
            ):
                errors.append(
                    f"CSV/JSONL disagreement for {tag} field={field}"
                )

    expected_policies = {
        "D1": ("matchup_top4_v3", "random"),
        "D2": ("random", "matchup_top4_v3"),
    }
    by_pair: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for row in rows:
        try:
            pair_id = int(row["pair_id"])
        except (KeyError, TypeError, ValueError):
            errors.append(
                f"invalid pair_id in row: {row.get('battle_tag', '')}"
            )
            continue
        battle_tag = row.get("battle_tag", "")
        arm = battle_tag.split("_", 1)[0]
        if arm not in {"D1", "D2"}:
            errors.append(f"unexpected arm for {battle_tag}")
            continue
        actual = (row.get("player_policy"), row.get("opponent_policy"))
        if actual != expected_policies[arm]:
            errors.append(
                f"wrong policies for {battle_tag}: "
                f"got {actual}, expected {expected_policies[arm]}"
            )
        pair_rows = by_pair.setdefault(pair_id, {})
        if arm in pair_rows:
            errors.append(
                f"duplicate {arm} row for pair_id={pair_id}"
            )
        else:
            pair_rows[arm] = row

    if len(by_pair) != expected_pairs:
        errors.append(
            f"unique pairs={len(by_pair)}, expected={expected_pairs}"
        )
    for pair_id, arms in by_pair.items():
        if set(arms) != {"D1", "D2"}:
            errors.append(
                f"incomplete D1/D2 pair for pair_id={pair_id}"
            )
            continue
        d1_team_id = arms["D1"].get("team_id")
        d1_opp_id = arms["D1"].get("opponent_team_id")
        d2_team_id = arms["D2"].get("team_id")
        d2_opp_id = arms["D2"].get("opponent_team_id")
        if d1_team_id != d2_team_id:
            errors.append(
                f"D1/D2 team_id mismatch pair_id={pair_id}: "
                f"D1={d1_team_id}, D2={d2_team_id}"
            )
        if d1_opp_id != d2_opp_id:
            errors.append(
                f"D1/D2 opponent_team_id mismatch pair_id={pair_id}: "
                f"D1={d1_opp_id}, D2={d2_opp_id}"
            )

    for row in previews:
        if row.get("preview_matches_plan") != "True":
            errors.append(
                f"preview mismatch for {row.get('battle_tag')}"
            )
        if not row.get("observed_actual_lead_on_turn1", "").strip():
            errors.append(
                f"missing observed lead for {row.get('battle_tag')}"
            )

    # V3 plan consistency: when both D1 and D2 preview rows have
    # player_policy = matchup_top4_v3 (i.e. the V3-side perspective),
    # the planned plan must be identical because the team/opponent
    # inputs are identical and the policy is deterministic.
    def _v3_plan_rows_by_battle() -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = {}
        for row in previews:
            if row.get("player_policy") == "matchup_top4_v3":
                out.setdefault(row.get("battle_tag", ""), []).append(row)
        return out

    v3_rows = _v3_plan_rows_by_battle()
    if len(v3_rows) < expected_battles:
        errors.append(
            f"missing V3 preview evidence: expected "
            f"{expected_battles} battles with player_policy=V3, got "
            f"{len(v3_rows)}"
        )

    by_pair_v3: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for battle_tag, v3_plans in v3_rows.items():
        if not v3_plans:
            errors.append(
                f"no V3 plan for battle {battle_tag}"
            )
            continue
        try:
            pair_id = int(battle_tag.split("_")[1])
        except (IndexError, ValueError):
            errors.append(f"bad battle tag: {battle_tag}")
            continue
        arm = battle_tag.split("_", 1)[0]
        pair_plans = by_pair_v3.setdefault(pair_id, {})
        if arm in pair_plans:
            errors.append(
                f"duplicate V3 {arm} preview for pair_id={pair_id}"
            )
        else:
            pair_plans[arm] = v3_plans[0]

    for pair_id, arms in by_pair_v3.items():
        if set(arms) != {"D1", "D2"}:
            continue
        d1_row = arms["D1"]
        d2_row = arms["D2"]
        for field in (
            "planned_chosen_4",
            "planned_lead_2",
            "planned_back_2",
        ):
            if d1_row.get(field) != d2_row.get(field):
                errors.append(
                    f"V3 plan mismatch pair_id={pair_id} field={field}: "
                    f"D1={d1_row.get(field)}, D2={d2_row.get(field)}"
                )

    return errors


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=100)
    parser.add_argument("--limit-teams", type=int, default=None)
    parser.add_argument(
        "--artifact-tag",
        default=(
            "phaseV2f_v3_paired_qualification_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
        ),
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if not args.overwrite:
        csv_path = Path("logs") / (
            f"vgc2026_phaseV2c_{args.artifact_tag}_benchmark.csv"
        )
        jsonl_path = Path("logs") / (
            f"vgc2026_phaseV2c_{args.artifact_tag}_benchmark.jsonl"
        )
        preview_path = Path("logs") / (
            f"vgc2026_phaseV2c_{args.artifact_tag}_preview_evidence.csv"
        )
        if any(p.exists() for p in (csv_path, jsonl_path, preview_path)):
            print(
                f"Refusing to overwrite existing artifact for tag "
                f"{args.artifact_tag!r}. Use --overwrite to force."
            )
            return 2

    runner = V2fPairedQualificationRunner(
        pairs=args.pairs,
        limit_teams=args.limit_teams,
        artifact_tag=args.artifact_tag,
        overwrite=args.overwrite,
    )
    await runner.run_all()
    errors = validate_v2f_qualification_artifacts(
        runner.csv_path,
        runner.jsonl_path,
        runner.preview_csv_path,
        args.pairs,
    )
    if errors:
        print("V2f qualification artifact validation FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 2
    print("V2f qualification artifact validation PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
