#!/usr/bin/env python3
"""Phase 6.4.10b — Visible Live Switch Surface Demo.

Three small live scenarios that prove the
voluntary switch surface in the default format
(``gen9randomdoublesbattle``) and in a custom
format (``gen9doublescustomgame``) with the 4-mon
team.

Each scenario prints a clear visible username with
``VSWdemo_`` prefix so the user can find the room
in the local Showdown UI at http://localhost:8000.

The scenarios are:

  Scenario 1: Random Doubles (gen9randomdoublesbattle)
    - 1 battle, 2 players
    - Logs every turn's valid_orders and prints
      visible battle tag for the user to watch.

  Scenario 2: Custom Game (gen9doublescustomgame)
    - 1 battle, 2 players with the 4-mon packed team
    - Same logging as Scenario 1.

  Scenario 3: VGC 2025 Reg I (gen9vgc2025regi)
    - 1 battle, 2 players with the 4-mon packed team
    - Same logging as Scenario 1.

This demo does NOT adopt voluntary-switch scoring.
It only proves the surface is visible and accessible
in the live runtime.
"""
import argparse
import asyncio
import atexit
import json
import os
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Unregister poke-env's broken atexit hook.
import poke_env.concurrency
_clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if _clear_loop is not None:
    try:
        atexit.unregister(_clear_loop)
    except Exception:
        pass

import poke_env_test_cleanup  # noqa: F401

from bot_doubles_voluntary_switch_surface_probe import (
    SurfaceProbePlayer,
    _make_probe_player,
    _build_packed_team_4,
    SAMPLE_TEAM_4,
    check_localhost_healthy,
    _player_username,
    HEALTH_URL,
)


DEMO_BASE = "VSWdemo"


async def _run_scenario(
    scenario_label: str,
    format_label: str,
    battle_format: str,
    team: Optional[str],
    n_battles: int = 1,
    timeout: float = 90.0,
) -> List[Dict[str, Any]]:
    """Run one live scenario and return records."""
    p1_name = _player_username(DEMO_BASE, format_label, 1)
    p2_name = _player_username(DEMO_BASE, format_label, 2)
    p1 = _make_probe_player(p1_name, team, battle_format)
    p2 = _make_probe_player(p2_name, team, battle_format)
    print(
        f"  Scenario {scenario_label} ({battle_format}): "
        f"{p1_name} vs {p2_name}"
    )
    try:
        await asyncio.wait_for(
            p1.battle_against(p2, n_battles=n_battles),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        print(
            f"  WARNING: {scenario_label} timed out after "
            f"{timeout}s"
        )
    except Exception as e:
        print(f"  WARNING: {scenario_label} error: {e}")
    records: List[Dict[str, Any]] = []
    for p in (p1, p2):
        for r in p.surface_records:
            records.append(r)
    for p in (p1, p2):
        try:
            if hasattr(p, "ps_client") and hasattr(
                p.ps_client, "_stop_listening"
            ):
                await p.ps_client._stop_listening()
        except Exception:
            pass
    return records


def _print_scenario_summary(
    scenario_label: str, records: List[Dict[str, Any]]
):
    n_voluntary = sum(
        1 for r in records
        if (
            not r.get("active_fainted", False)
            and not r.get("force_switch", False)
            and r.get("n_voluntary_switches", 0) > 0
        )
    )
    battle_tags = set(
        r.get("battle_tag", "") for r in records
    )
    print(
        f"  [{scenario_label}] n_battles={len(battle_tags)} "
        f"n_records={len(records)} n_voluntary={n_voluntary}"
    )
    # Print battle tags so the user can find them.
    for bt in sorted(battle_tags):
        if bt:
            print(f"    battle tag: {bt}")
    if n_voluntary > 0:
        # Find first voluntary.
        for r in records:
            if (
                not r.get("active_fainted", False)
                and not r.get("force_switch", False)
                and r.get("n_voluntary_switches", 0) > 0
            ):
                print(
                    f"    first voluntary: turn {r['turn']} "
                    f"slot {r['slot']} "
                    f"active={r['active_species']} "
                    f"candidates={r['switch_candidate_species']}"
                )
                break


async def main_async(args):
    if not check_localhost_healthy():
        print(
            "ERROR: localhost:8000 is not healthy. "
            "Refusing to run."
        )
        sys.exit(3)
    print(
        f"Phase 6.4.10b visible live switch surface demo "
        f"starting on {HEALTH_URL}"
    )
    scenarios = [
        ("1", "A1", "gen9randomdoublesbattle", None),
        ("2", "B1", "gen9doublescustomgame", SAMPLE_TEAM_4),
        ("3", "C1", "gen9vgc2025regi", SAMPLE_TEAM_4),
    ]
    all_records: List[Dict[str, Any]] = []
    for s_label, f_label, fmt, team in scenarios:
        recs = await _run_scenario(
            scenario_label=s_label,
            format_label=f_label,
            battle_format=fmt,
            team=team,
            n_battles=1,
            timeout=args.timeout,
        )
        all_records.extend(recs)
        _print_scenario_summary(s_label, recs)
    # Write JSONL.
    if args.artifact_tag:
        jsonl_path = (
            f"logs/voluntary_switch_surface_demo_{args.artifact_tag}.jsonl"
        )
        if os.path.exists(jsonl_path) and not args.overwrite:
            print(
                f"WARNING: {jsonl_path} exists, not overwriting"
            )
        else:
            if os.path.exists(jsonl_path):
                os.remove(jsonl_path)
            with open(jsonl_path, "w") as f:
                for r in all_records:
                    f.write(json.dumps(r) + "\n")
            print(f"\nWrote: {jsonl_path}")
    n_voluntary = sum(
        1 for r in all_records
        if (
            not r.get("active_fainted", False)
            and not r.get("force_switch", False)
            and r.get("n_voluntary_switches", 0) > 0
        )
    )
    print(
        f"\nTotal: {len(all_records)} records, "
        f"{n_voluntary} voluntary switch opportunities"
    )
    if n_voluntary > 0:
        print(
            "RESULT: voluntary switch surface is VISIBLE in the "
            "live runtime."
        )
    else:
        print(
            "RESULT: no voluntary switch opportunities in this "
            "demo run."
        )


def main():
    parser = argparse.ArgumentParser(
        description="Phase 6.4.10b visible live switch surface demo"
    )
    parser.add_argument(
        "--artifact-tag", type=str, default="",
        help="Artifact tag for output JSONL.",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing artifact.",
    )
    parser.add_argument(
        "--timeout", type=float, default=90.0,
        help="Per-scenario timeout in seconds.",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
