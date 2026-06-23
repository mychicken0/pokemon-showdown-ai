#!/usr/bin/env python3
"""Phase WT-4a — Weather/Terrain bonus sweep.

Runs a local-only sweep over a grid of weather /
terrain bonus values and reports per-setting
statistics. The goal is to find a bonus range where
setters start being selected in clear synergy
situations, while avoiding obvious bad setter
choices.

This is **not** the full WT-4 paired benchmark.
This is activation/tuning only.

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
from typing import Any, Dict, List, Optional, Tuple

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
from doubles_engine.wt3_weather_terrain_positive import (
    is_bad_setter_selection,
)

HEALTH_URL = "http://localhost:8000"
DEFAULT_BATTLES_PER_SETTING = 3
MAX_BATTLES = 20
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


def _analyze_audit(audit_path: str) -> Dict[str, Any]:
    """Walk the audit JSONL and compute per-setting
    statistics.
    """
    stats: Dict[str, Any] = {
        "n_turns": 0,
        "n_setter_legal": 0,
        "n_setter_selected": 0,
        "n_redundant_setter": 0,
        "n_bad_setter": 0,
        "setter_selected_moves": [],
        "bad_setter_examples": [],
        "setter_score_gaps": [],
    }
    if not os.path.exists(audit_path):
        return stats
    with open(audit_path) as f:
        for line in f:
            try:
                battle = json.loads(line)
            except json.JSONDecodeError:
                continue
            bt = battle.get("battle_tag", "?")
            for turn in battle.get("audit_turns", []):
                stats["n_turns"] += 1
                sel_key = turn.get("v4a_selected_joint_key", [])
                sel_score = turn.get("selected_score", 0) or 0
                # Check if a setter was selected
                sel_setter_move = None
                sel_setter_slot = None
                for slot_idx, k in enumerate(sel_key):
                    if (
                        isinstance(k, (list, tuple))
                        and len(k) >= 2
                        and str(k[0]) == "move"
                        and _norm_move_id(k[1]) in WT3_SETTER_IDS
                    ):
                        sel_setter_move = _norm_move_id(k[1])
                        sel_setter_slot = slot_idx
                        break
                if sel_setter_move:
                    stats["n_setter_selected"] += 1
                    stats["setter_selected_moves"].append(
                        sel_setter_move
                    )
                    # Score gap
                    raw_setter = turn.get(
                        "setter_move_raw_score", {}
                    ) or {}
                    raw = raw_setter.get(sel_setter_move, 0) or 0
                    stats["setter_score_gaps"].append(
                        sel_score - raw
                    )
                    # Bad setter detection
                    try:
                        from doubles_engine.wt3_weather_terrain_positive import (
                            get_active_weather,
                            get_active_terrain,
                        )
                        # Build minimal battle mock for
                        # is_bad_setter_selection
                        bmock = _build_battle_mock_from_turn(
                            turn
                        )
                        reasons = is_bad_setter_selection(
                            sel_setter_move,
                            sel_setter_slot,
                            bmock,
                        )
                        if reasons:
                            stats["n_bad_setter"] += 1
                            if "redundant_setter" in reasons:
                                stats["n_redundant_setter"] += 1
                            if len(
                                stats["bad_setter_examples"]
                            ) < 5:
                                stats["bad_setter_examples"].append(
                                    {
                                        "battle": bt,
                                        "turn": turn.get("turn"),
                                        "setter": sel_setter_move,
                                        "reasons": reasons,
                                        "selected_score": sel_score,
                                    }
                                )
                    except Exception as e:
                        pass
                # Check if a setter was legal
                for slot_key in (
                    "v4a_legal_action_keys_slot0",
                    "v4a_legal_action_keys_slot1",
                ):
                    found = False
                    for k in turn.get(slot_key, []):
                        if (
                            isinstance(k, (list, tuple))
                            and len(k) >= 2
                            and str(k[0]) == "move"
                            and _norm_move_id(k[1]) in WT3_SETTER_IDS
                        ):
                            found = True
                            break
                    if found:
                        stats["n_setter_legal"] += 1
                        break
    return stats


def _build_battle_mock_from_turn(turn: Dict[str, Any]) -> Any:
    """Build a minimal MagicMock battle for
    is_bad_setter_selection from an audit turn.
    """
    from unittest.mock import MagicMock
    battle = MagicMock()
    battle.weather = None
    # Try to read weather from state_snapshot
    state = turn.get("state_snapshot", {}) or {}
    weather_str = state.get("weather", "")
    if weather_str and weather_str != "none":
        # weather_str is a list (e.g. ["raindance"])
        if isinstance(weather_str, list) and weather_str:
            battle.weather = MagicMock()
            battle.weather.__str__ = lambda self: weather_str[
                0
            ].upper()
    battle.fields = None
    # Get opp types and moves from opp_actions
    opp_actions = turn.get("opp_actions", {}) or {}
    opp_mons = opp_actions.get("opp_active_mons", []) or []
    battle.opponent_active_pokemon = []
    for mon_data in opp_mons:
        if not isinstance(mon_data, dict):
            continue
        opp = MagicMock()
        opp.types = [
            str(t).lower()
            for t in (mon_data.get("types") or [])
        ]
        opp.moves = {
            str(m).lower(): True
            for m in (mon_data.get("moves") or [])
        }
        battle.opponent_active_pokemon.append(opp)
    battle.opponent_team = None
    # Our active types
    our_active = turn.get("our_active", {}) or {}
    our_types = [
        str(t).lower() for t in (our_active.get("types") or [])
    ]
    battle.active_pokemon = [MagicMock(), MagicMock()]
    battle.active_pokemon[0].types = our_types
    battle.active_pokemon[1].types = our_types
    battle.available_moves = [[], []]
    return battle


async def run_single_battle(
    idx: int,
    total: int,
    audit_logger: DoublesDecisionAuditLogger,
    our_team_showdown: str,
    weather_bonus: float,
    terrain_bonus: float,
) -> Dict[str, Any]:
    suffix = str(idx) + str(int(time.time() * 1000) % 100000)[-5:]
    bot_name = f"WT4aSmk_{suffix}"[:18]
    opp_name = f"WT4aOpp_{suffix}"[:18]

    bot = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        audit_logger=audit_logger,
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9doublescustomgame",
        team=our_team_showdown,
    )
    # Apply WT-3 flag and bonus values
    bot.config.enable_weather_terrain_positive_scoring = True
    bot.config.weather_terrain_positive_weather_bonus = (
        weather_bonus
    )
    bot.config.weather_terrain_positive_terrain_bonus = (
        terrain_bonus
    )

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
                f"  [{idx}/{total}] w={weather_bonus:.0f} "
                f"t={terrain_bonus:.0f} | "
                f"{elapsed:.0f}s | "
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
        print(
            f"  [{idx}] TIMEOUT w={weather_bonus:.0f} "
            f"t={terrain_bonus:.0f}",
            flush=True,
        )
    finally:
        hb_task.cancel()
        try:
            await bot.ps_client._stop_listening()
            await opp.ps_client._stop_listening()
        except Exception:
            pass

    return {
        "battle_idx": idx,
        "elapsed_s": time.time() - start,
        "bot_finished": bot.n_finished_battles,
        # Phase WT-4b: capture per-turn WT-3 decisions
        # for attribution. This is observational and
        # does not affect scoring.
        "wt3_decisions": getattr(bot, "_wt3_decisions", {}),
        # Phase WT-4c: capture WT-4c candidate
        # inclusions. This is observational and does
        # not affect scoring.
        "wt4c_inclusions": getattr(
            bot, "_wt4c_inclusions", []
        ),
    }


async def run_setting(
    setting_idx: int,
    total_settings: int,
    weather_bonus: float,
    terrain_bonus: float,
    battles: int,
    our_team_showdown: str,
    audit_dir: str,
) -> Dict[str, Any]:
    audit_path = os.path.join(
        audit_dir,
        f"wt4a_sweep_w{int(weather_bonus)}_t{int(terrain_bonus)}.jsonl",
    )
    audit_logger = DoublesDecisionAuditLogger(
        filepath=audit_path, reset=True, detail_level="top5"
    )
    audit_logger.set_current_battle_meta(
        benchmark_arm="wt4a_sweep",
        enable_mega_evolution=False,
        enable_decision_timing_diagnostics=False,
        treatment_side="p1",
        player_side="p1",
        player_name="WT4aSweepBot",
    )
    print(
        f"=== Setting {setting_idx}/{total_settings}: "
        f"weather_bonus={weather_bonus:.0f} "
        f"terrain_bonus={terrain_bonus:.0f} "
        f"battles={battles} ===",
        flush=True,
    )
    results = []
    for idx in range(1, battles + 1):
        try:
            r = await run_single_battle(
                idx, battles, audit_logger, our_team_showdown,
                weather_bonus, terrain_bonus,
            )
            results.append(r)
        except Exception as e:
            print(
                f"    Battle {idx} failed: {e}",
                flush=True,
            )
            results.append({"battle_idx": idx, "error": str(e)})
    stats = _analyze_audit(audit_path)
    n_finished = sum(
        1 for r in results
        if "error" not in r and r.get("bot_finished", 0) > 0
    )
    print(
        f"  finished: {n_finished}/{battles} | "
        f"setter_legal: {stats['n_setter_legal']} | "
        f"setter_selected: {stats['n_setter_selected']} | "
        f"bad_setter: {stats['n_bad_setter']}",
        flush=True,
    )
    # Phase WT-4c: collect all wt3 decisions and
    # wt4c inclusions across battles
    all_wt3_decisions = {}
    all_wt4c_inclusions = []
    for r in results:
        for bt, dl in r.get("wt3_decisions", {}).items():
            all_wt3_decisions.setdefault(bt, []).extend(dl)
        all_wt4c_inclusions.extend(
            r.get("wt4c_inclusions", [])
        )
    return {
        "weather_bonus": weather_bonus,
        "terrain_bonus": terrain_bonus,
        "battles": battles,
        "n_finished": n_finished,
        "audit_path": audit_path,
        "stats": stats,
        "wt3_decisions": all_wt3_decisions,
        "wt4c_inclusions": all_wt4c_inclusions,
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--battles-per-setting",
        type=int,
        default=DEFAULT_BATTLES_PER_SETTING,
    )
    parser.add_argument(
        "--weather-bonuses",
        default="150,300,500,750,1000",
        help="Comma-separated weather bonus values",
    )
    parser.add_argument(
        "--terrain-bonuses",
        default="120,250,400,600,800",
        help="Comma-separated terrain bonus values",
    )
    parser.add_argument(
        "--output",
        default="logs/wt4a_bonus_sweep.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--audit-dir",
        default="logs/wt4a_sweep_audits",
        help="Directory for per-setting audit files",
    )
    args = parser.parse_args()

    weather_bonuses = [
        float(x) for x in args.weather_bonuses.split(",")
    ]
    terrain_bonuses = [
        float(x) for x in args.terrain_bonuses.split(",")
    ]
    if args.battles_per_setting < 1:
        print("ERROR: --battles-per-setting must be >= 1")
        sys.exit(1)
    if args.battles_per_setting > MAX_BATTLES:
        print(
            f"ERROR: --battles-per-setting must be <= "
            f"{MAX_BATTLES}"
        )
        sys.exit(1)

    if not check_localhost_healthy():
        print(
            "ERROR: localhost:8000 not healthy; refusing to run."
        )
        sys.exit(1)

    os.makedirs(args.audit_dir, exist_ok=True)
    with open(OUR_TEAM_JSON) as f:
        our_team_data = json.load(f)
    our_team_showdown = json_to_showdown(our_team_data)

    # Build a paired grid: each weather bonus paired
    # with each terrain bonus.
    settings = []
    for w in weather_bonuses:
        for t in terrain_bonuses:
            settings.append((w, t))

    print("=" * 60)
    print("WT-4a bonus sweep")
    print(
        f"  {len(settings)} settings x "
        f"{args.battles_per_setting} battles each "
        f"= {len(settings) * args.battles_per_setting} "
        f"battles total"
    )
    print("=" * 60)

    all_results = []
    for idx, (w, t) in enumerate(settings, 1):
        r = asyncio.run(
            run_setting(
                idx, len(settings), w, t,
                args.battles_per_setting,
                our_team_showdown,
                args.audit_dir,
            )
        )
        all_results.append(r)

    # Write output
    output = {
        "settings": all_results,
        "summary": {
            "n_settings": len(all_results),
            "settings_with_selection": sum(
                1
                for r in all_results
                if r["stats"]["n_setter_selected"] > 0
            ),
            "settings_with_bad_setter": sum(
                1
                for r in all_results
                if r["stats"]["n_bad_setter"] > 0
            ),
        },
    }
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print()
    print("=" * 60)
    print("WT-4a sweep complete")
    print("=" * 60)
    print(f"  Output: {args.output}")
    print(
        f"  Settings with at least 1 setter selection: "
        f"{output['summary']['settings_with_selection']}/"
        f"{output['summary']['n_settings']}"
    )
    print(
        f"  Settings with at least 1 bad setter: "
        f"{output['summary']['settings_with_bad_setter']}/"
        f"{output['summary']['n_settings']}"
    )


if __name__ == "__main__":
    main()
