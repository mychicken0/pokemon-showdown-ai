#!/usr/bin/env python3
"""Phase WT-3 — Weather/Terrain Positive Scoring Smoke.

A small local-only smoke that runs N battles with the
WT-3 flag OFF and N battles with the WT-3 flag ON,
then compares setter selection behavior.

This is a **smoke**, not a benchmark. The goal is to
verify the WT-3 hook does not crash and produces
non-zero setter selections when the flag is ON.

Local server only (localhost:8000). No official
server. No commits. No default flip.
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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, SCRIPT_DIR)

# Unregister poke-env's broken atexit hook.
import poke_env.concurrency
_clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if _clear_loop is not None:
    try:
        atexit.unregister(_clear_loop)
    except Exception:
        pass

import poke_env_test_cleanup  # noqa: F401

from poke_env import AccountConfiguration
from poke_env.player.baselines import RandomPlayer
from poke_env.player.battle_order import DoubleBattleOrder

from bot_doubles_damage_aware import DoublesDamageAwarePlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

HEALTH_URL = "http://localhost:8000"
DEFAULT_BATTLES_PER_ARM = 5
MAX_BATTLES = 50
HEARTBEAT_INTERVAL = 30
STALL_TIMEOUT = 180
ARM_TIMEOUT = 300

OUR_TEAM_JSON = "data/curated_teams/custom/wt2_audit_team_v1.json"

OPP_TEAM = """Incineroar @ Sitrus Berry
Ability: Intimidate
EVs: 252 HP / 252 Atk
Adamant Nature
- Fake Out
- Flare Blitz
- Knock Off
- U-turn

Tornadus @ Heavy-Duty Boots
Ability: Prankster
EVs: 252 HP / 252 SpA
Modest Nature
- Tailwind
- Hurricane
- Rain Dance
- Protect

Clefable @ Leftovers
Ability: Magic Guard
EVs: 252 HP / 252 Def
Bold Nature
- Moonblast
- Wish
- Protect
- Thunder Wave

Garchomp @ Choice Scarf
Ability: Rough Skin
EVs: 252 Atk / 252 Spe
Jolly Nature
- Earthquake
- Rock Slide
- Outrage
- Dragon Claw

Tyranitar @ Smooth Rock
Ability: Sand Stream
EVs: 252 HP / 252 Atk
Adamant Nature
- Rock Slide
- Crunch
- Stone Edge
- Protect

Volcarona @ Leftovers
Ability: Flame Body
EVs: 252 SpA / 252 Spe
Timid Nature
- Heat Wave
- Bug Buzz
- Quiver Dance
- Protect"""


# Setter move ids (normalized).
WT3_SETTER_IDS = {
    "raindance", "sunnyday", "sandstorm", "snowscape", "hail",
    "electricterrain", "grassyterrain", "mistyterrain",
    "psychicterrain",
}


def check_localhost_healthy(timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def json_to_showdown(team_dict: Dict[str, Any]) -> str:
    lines = []
    for p in team_dict.get("team", []):
        species = p["species"]
        if p.get("item"):
            lines.append(f"{species} @ {p['item']}")
        else:
            lines.append(species)
        lines.append(f"Ability: {p['ability']}")
        evs = p.get("evs", {})
        if evs:
            ev_parts = [f"{v} {k.upper()}" for k, v in evs.items() if v > 0]
            if ev_parts:
                lines.append("EVs: " + " / ".join(ev_parts))
        if p.get("nature"):
            lines.append(f"{p['nature']} Nature")
        for move in p.get("moves", []):
            lines.append(f"- {move}")
        lines.append("")
    return "\n".join(lines)


def _norm_move_id(mid: Any) -> str:
    if mid is None:
        return ""
    s = str(mid).lower()
    return (
        s.replace(" ", "").replace("-", "").replace("_", "")
        .replace("'", "")
    )


def _extract_setters_from_audit(audit_path: str) -> Dict[str, int]:
    """Walk the audit JSONL and count setter moves that
    were legal and selected.
    """
    stats = {
        "n_turns": 0,
        "n_setter_legal": 0,
        "n_setter_selected": 0,
        "n_setter_selected_examples": 0,
        "setter_selected_moves": [],
    }
    if not os.path.exists(audit_path):
        return stats
    with open(audit_path) as f:
        for line in f:
            try:
                battle = json.loads(line)
            except json.JSONDecodeError:
                continue
            for turn in battle.get("audit_turns", []):
                stats["n_turns"] += 1
                sel_key = turn.get("v4a_selected_joint_key", [])
                # Detect selected setter
                sel_setter = False
                for k in sel_key:
                    if (
                        isinstance(k, (list, tuple))
                        and len(k) >= 2
                        and str(k[0]) == "move"
                        and _norm_move_id(k[1]) in WT3_SETTER_IDS
                    ):
                        sel_setter = True
                        stats["setter_selected_moves"].append(
                            _norm_move_id(k[1])
                        )
                        break
                if sel_setter:
                    stats["n_setter_selected"] += 1
                # Detect legal setter
                for slot_key in (
                    "v4a_legal_action_keys_slot0",
                    "v4a_legal_action_keys_slot1",
                ):
                    for k in turn.get(slot_key, []):
                        if (
                            isinstance(k, (list, tuple))
                            and len(k) >= 2
                            and str(k[0]) == "move"
                            and _norm_move_id(k[1]) in WT3_SETTER_IDS
                        ):
                            stats["n_setter_legal"] += 1
                            break
                    else:
                        continue
                    break
    return stats


async def run_single_battle(
    idx: int,
    total: int,
    audit_logger: DoublesDecisionAuditLogger,
    our_team_showdown: str,
    enable_wt3: bool,
) -> Dict[str, Any]:
    suffix = str(idx) + str(int(time.time() * 1000) % 100000)[-5:]
    bot_name = f"WT3Smoke_{suffix}"[:18]
    opp_name = f"WT3Opp_{suffix}"[:18]

    bot = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        audit_logger=audit_logger,
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9doublescustomgame",
        team=our_team_showdown,
    )
    # Apply WT-3 flag override
    bot.config.enable_weather_terrain_positive_scoring = enable_wt3

    opp = RandomPlayer(
        account_configuration=AccountConfiguration(opp_name, None),
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9doublescustomgame",
        team=OPP_TEAM,
    )

    start = time.time()

    async def heartbeat():
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            elapsed = time.time() - start
            print(
                f"  [{idx}/{total}] {elapsed:.0f}s | "
                f"finished={bot.n_finished_battles}",
                flush=True,
            )

    battle_task = asyncio.create_task(
        bot.battle_against(opp, n_battles=1)
    )
    hb_task = asyncio.create_task(heartbeat())
    try:
        await asyncio.wait_for(
            asyncio.wait(
                {battle_task}, return_when=asyncio.FIRST_COMPLETED
            ),
            timeout=ARM_TIMEOUT,
        )
    except asyncio.TimeoutError:
        print(f"  [{idx}] TIMEOUT", flush=True)
    finally:
        hb_task.cancel()
        try:
            await bot.ps_client._stop_listening()
            await opp.ps_client._stop_listening()
        except Exception:
            pass

    elapsed = time.time() - start
    return {
        "battle_idx": idx,
        "elapsed_s": elapsed,
        "bot_finished": bot.n_finished_battles,
    }


async def run_arm(
    battles: int,
    audit_path: str,
    enable_wt3: bool,
    our_team_showdown: str,
) -> Dict[str, Any]:
    audit_logger = DoublesDecisionAuditLogger(
        filepath=audit_path, reset=True, detail_level="top5"
    )
    audit_logger.set_current_battle_meta(
        benchmark_arm="wt3_smoke",
        enable_mega_evolution=False,
        enable_decision_timing_diagnostics=False,
        treatment_side="p1",
        player_side="p1",
        player_name="WT3SmokeBot",
    )
    print(
        f"  arm: enable_wt3={enable_wt3}, "
        f"battles={battles}, audit={audit_path}",
        flush=True,
    )
    results = []
    for idx in range(1, battles + 1):
        try:
            r = await run_single_battle(
                idx, battles, audit_logger, our_team_showdown,
                enable_wt3,
            )
            results.append(r)
            print(
                f"    [{idx}/{battles}] {r['elapsed_s']:.1f}s",
                flush=True,
            )
        except Exception as e:
            print(f"    Battle {idx} failed: {e}", flush=True)
            results.append({"battle_idx": idx, "error": str(e)})
    return {"results": results, "audit_path": audit_path}


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--battles-per-arm",
        type=int,
        default=DEFAULT_BATTLES_PER_ARM,
        help=(
            f"Number of battles per arm "
            f"(default: {DEFAULT_BATTLES_PER_ARM}, "
            f"max: {MAX_BATTLES})"
        ),
    )
    parser.add_argument(
        "--off-audit",
        default="logs/wt3_smoke_off_audit.jsonl",
        help="Audit path for OFF arm",
    )
    parser.add_argument(
        "--on-audit",
        default="logs/wt3_smoke_on_audit.jsonl",
        help="Audit path for ON arm",
    )
    args = parser.parse_args()

    if args.battles_per_arm < 1:
        print("ERROR: --battles-per-arm must be >= 1")
        sys.exit(1)
    if args.battles_per_arm > MAX_BATTLES:
        print(
            f"ERROR: --battles-per-arm must be <= {MAX_BATTLES}"
        )
        sys.exit(1)

    if not check_localhost_healthy():
        print(
            "ERROR: localhost:8000 not healthy; "
            "refusing to run."
        )
        sys.exit(1)

    with open(OUR_TEAM_JSON) as f:
        our_team_data = json.load(f)
    our_team_showdown = json_to_showdown(our_team_data)

    print("=" * 60)
    print("WT-3 Smoke (local only)")
    print("=" * 60)
    off_result = asyncio.run(
        run_arm(
            args.battles_per_arm,
            args.off_audit,
            False,
            our_team_showdown,
        )
    )
    on_result = asyncio.run(
        run_arm(
            args.battles_per_arm,
            args.on_audit,
            True,
            our_team_showdown,
        )
    )

    off_stats = _extract_setters_from_audit(args.off_audit)
    on_stats = _extract_setters_from_audit(args.on_audit)
    print()
    print("=" * 60)
    print("WT-3 Smoke Summary")
    print("=" * 60)
    print(f"  OFF arm: {args.off_audit}")
    print(f"    n_turns: {off_stats['n_turns']}")
    print(f"    n_setter_legal: {off_stats['n_setter_legal']}")
    print(f"    n_setter_selected: {off_stats['n_setter_selected']}")
    print(f"  ON arm: {args.on_audit}")
    print(f"    n_turns: {on_stats['n_turns']}")
    print(f"    n_setter_legal: {on_stats['n_setter_legal']}")
    print(f"    n_setter_selected: {on_stats['n_setter_selected']}")
    print()
    if on_stats["n_setter_legal"] > 0:
        on_rate = (
            100.0 * on_stats["n_setter_selected"]
            / on_stats["n_setter_legal"]
        )
        print(
            f"  ON setter selection rate: {on_rate:.1f}%"
        )
    if off_stats["n_setter_legal"] > 0:
        off_rate = (
            100.0 * off_stats["n_setter_selected"]
            / off_stats["n_setter_legal"]
        )
        print(
            f"  OFF setter selection rate: {off_rate:.1f}%"
        )


if __name__ == "__main__":
    main()
