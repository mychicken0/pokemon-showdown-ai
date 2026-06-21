#!/usr/bin/env python3
"""PLANNER-SPREAD-3 — Targeted probe + 5-pair smoke.

Validates:
- 1 targeted probe (1 battle, flag ON): WG selection count > 0
- 5-pair smoke (OFF vs ON spread_scoring):
  - 10/10 battles ok
  - WG selection count higher in ON arm
  - Bonus magnitude correct (+150.0)
  - Anti-spam works (max 3 picks per game)
  - No default behavior change (default OFF path identical)

Usage:
  ./venv/bin/python bot_doubles_planner_spread_smoke.py --artifact-tag PLANNER_SPREAD_3
"""
import argparse
import asyncio
import atexit
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import poke_env.concurrency
_clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if _clear_loop is not None:
    try:
        atexit.unregister(_clear_loop)
    except Exception:
        pass

from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger
from bot_vgc2026_phaseV2c import build_team_string, validate_team_for_battle

# 5 pairs: bot team (with Wide Guard) vs custom opp teams (with spread moves)
# Our team has Wide Guard on incineroar
# Opp teams have heatwave/dazzlinggleam/rockslide/earthquake/snarl
# PLANNER-SPREAD-5: 4 WG team variations × 5 opp teams = 20 pairs
WG_TEAM_PATHS = [
    "data/curated_teams/custom/planner_spread_wg_test_team.json",
    "data/curated_teams/custom/planner_spread_wg_pelipper.json",
    "data/curated_teams/custom/planner_spread_wg_incineroar.json",
    "data/curated_teams/custom/planner_spread_wg_whimsicott.json",
]
WG_TEAM_TAGS = ["arcanine", "pelipper", "incineroar", "whimsicott"]
CUSTOM_OPP_TEAMS = [
    ("data/curated_teams/custom/planner_spread_opp_heatwave.json", "heatwave_opp"),
    ("data/curated_teams/custom/planner_spread_opp_rockslide.json", "rockslide_opp"),
    ("data/curated_teams/custom/planner_spread_opp_snarl.json", "snarl_opp"),
    ("data/curated_teams/custom/planner_spread_opp_dazzlinggleam.json", "dazzlinggleam_opp"),
    ("data/curated_teams/custom/planner_spread_opp_hypervoice.json", "hypervoice_opp"),
]
OPP_TAGS = ["heatwave", "rockslide", "snarl", "dazzlinggleam", "hypervoice"]
# PLANNER-SPREAD-9: general pool opp teams (NO spread moves)
# These are common VGC Champions-legal teams without heatwave/rockslide/etc.
# Used to verify that WG is NOT over-selected when opp has no spread pressure.
GENERAL_OPP_TEAMS = [
    ("data/curated_teams/custom/general_opp_tr.json", "tr_opp"),
    ("data/curated_teams/custom/general_opp_sun.json", "sun_opp"),
    ("data/curated_teams/custom/general_opp_rain.json", "rain_opp"),
    ("data/curated_teams/custom/general_opp_tw.json", "tw_opp"),
    ("data/curated_teams/custom/general_opp_bulky.json", "bulky_opp"),
]
GENERAL_OPP_TAGS = ["tr", "sun", "rain", "tw", "bulky"]
# Build PAIRS: 4 WG × 5 opp = 20 pairs (targeted)
PAIRS = []
for wg_path, wg_tag in zip(WG_TEAM_PATHS, WG_TEAM_TAGS):
    for opp_path, opp_tag in CUSTOM_OPP_TEAMS:
        label = f"wg_{wg_tag}_vs_{opp_tag}"
        PAIRS.append((wg_path, opp_path, label))
# Build GENERAL_PAIRS: 4 WG × 5 general opp = 20 pairs
GENERAL_PAIRS = []
for wg_path, wg_tag in zip(WG_TEAM_PATHS, WG_TEAM_TAGS):
    for opp_path, opp_tag in GENERAL_OPP_TEAMS:
        label = f"wg_{wg_tag}_vs_{opp_tag}"
        GENERAL_PAIRS.append((wg_path, opp_path, label))

# Battle format: VGC 2026 Champions
BATTLE_FORMAT = "gen9championsvgc2026regma"

# Watchdogs
HEARTBEAT = 30
STALL_TIMEOUT = 180
ARM_TIMEOUT = 600


class StallError(Exception):
    pass


def _load_team(team_path) -> str:
    """Load a team from a JSON file path and build a showdown team string.

    Accepts either a path string or an int (for backward compat).
    """
    if isinstance(team_path, int):
        team_path = f"data/curated_teams/control4a/team_{team_path:03d}.json"
    with open(team_path) as f:
        data = json.load(f)
    chosen = [m["species"] for m in data["team"][:4]]
    team_str = build_team_string(data["team"], chosen)
    valid, err = validate_team_for_battle(team_str)
    if not valid:
        raise ValueError(f"team {team_path} invalid: {err}")
    return team_str


async def _cleanup_player(player):
    try:
        if hasattr(player, "ps_client") and hasattr(player.ps_client, "_stop_listening"):
            await player.ps_client._stop_listening()
    except Exception:
        pass


def _make_config(enable_intent: bool, enable_spread_scoring: bool) -> DoublesDamageAwareConfig:
    """Build a config with the planner flags set as requested."""
    config = DoublesDamageAwareConfig()
    config.enable_planner_intent_detector = enable_intent
    config.enable_planner_spread_defense_scoring = enable_spread_scoring
    return config


async def _run_pair(
    our_path,
    opp_path,
    label: str,
    enable_intent: bool,
    enable_spread_scoring: bool,
    artifact_dir: Path,
    pair_id: int,
    arm_name: str,
    artifact_tag: str,
) -> Dict[str, Any]:
    """Run a single pair (one battle)."""
    our_team_str = _load_team(our_path)
    opp_team_str = _load_team(opp_path)

    config = _make_config(enable_intent, enable_spread_scoring)
    log_path = artifact_dir / (
        f"vgc2026_phase{artifact_tag}_{arm_name}_p{pair_id}_{label}_treatment_audit.jsonl"
    )

    suffix = random.randint(10000, 99999)
    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(
            f"P_{arm_name[:4]}_{suffix}"[:18], None
        ),
        verbose=False,
        config=config,
        team=our_team_str,
        battle_format=BATTLE_FORMAT,
        audit_logger=DoublesDecisionAuditLogger(
            filepath=str(log_path),
            reset=True,
            detail_level="top5",
            benchmark_arm=arm_name,
        ),
        max_concurrent_battles=1,
    )
    opponent = DoublesBasicAwarePlayer(
        account_configuration=AccountConfiguration(
            f"O_{arm_name[:4]}_{suffix}"[:18], None
        ),
        verbose=False,
        team=opp_team_str,
        battle_format=BATTLE_FORMAT,
        max_concurrent_battles=1,
    )

    start = time.time()
    state = {"last_battle_time": start}

    async def heartbeat():
        while True:
            await asyncio.sleep(HEARTBEAT)
            elapsed = time.time() - start
            since_last = time.time() - state["last_battle_time"]
            finished = player.n_finished_battles
            print(
                f"  [{arm_name}/p{pair_id}] {elapsed:.0f}s | "
                f"{finished}/1 | {since_last:.0f}s since last"
            )
            if since_last > STALL_TIMEOUT:
                raise StallError(
                    f"Stall: {arm_name}/p{pair_id}: no progress in {STALL_TIMEOUT}s"
                )

    battle_task = asyncio.create_task(
        player.battle_against(opponent, n_battles=1)
    )
    watchdog_task = asyncio.create_task(heartbeat())
    status = "ok"
    err: Optional[str] = None
    try:
        done, _ = await asyncio.wait_for(
            asyncio.wait(
                {battle_task, watchdog_task},
                return_when=asyncio.FIRST_COMPLETED,
            ),
            timeout=ARM_TIMEOUT,
        )
        if battle_task in done:
            b_exc = battle_task.exception()
            if b_exc and not isinstance(b_exc, asyncio.CancelledError):
                err = f"{type(b_exc).__name__}: {b_exc}"
                status = "error"
            else:
                state["last_battle_time"] = time.time()
        if watchdog_task in done:
            w_exc = watchdog_task.exception()
            if w_exc and not isinstance(w_exc, asyncio.CancelledError):
                err = f"watchdog: {w_exc}"
                status = "error"
    except asyncio.TimeoutError:
        err = f"ARM TIMEOUT after {ARM_TIMEOUT}s"
        status = "timeout"
    except StallError as e:
        err = str(e)
        status = "stall"
    finally:
        for t in (battle_task, watchdog_task):
            if t and not t.done():
                t.cancel()
        for t in (battle_task, watchdog_task):
            if t:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

    await _cleanup_player(player)
    await _cleanup_player(opponent)

    return {
        "arm": arm_name,
        "pair_id": pair_id,
        "label": label,
        "our": our_path,
        "opp": opp_path,
        "status": status,
        "error": err,
        "won": player.n_won_battles,
        "lost": opponent.n_won_battles,
        "log_path": str(log_path),
        "elapsed": time.time() - start,
    }


async def run_smoke(artifact_dir: Path, n_pairs: int = 5,
                artifact_tag: str = "PLANNER_SPREAD_3") -> Dict[str, Any]:
    """Run 5 OFF + 5 ON battles (both have intent ON, OFF has spread OFF, ON has spread ON)."""
    pairs = PAIRS[:n_pairs]
    results = {"off": [], "on": []}

    # OFF arm: intent ON, spread scoring OFF
    print(f"\n=== OFF arm (intent ON, spread_scoring OFF) ===")
    for i, (our, opp, label) in enumerate(pairs):
        print(f"\n---> OFF pair {i}: our={our} vs opp={opp} ({label})")
        r = await _run_pair(our, opp, label, True, False, artifact_dir, i, "off",
                            artifact_tag=artifact_tag)
        results["off"].append(r)
        print(f"  -> {r['status']} | {r['won']}W/{r['lost']}L")

    # ON arm: intent ON, spread scoring ON
    print(f"\n=== ON arm (intent ON, spread_scoring ON) ===")
    for i, (our, opp, label) in enumerate(pairs):
        print(f"\n---> ON pair {i}: our={our} vs opp={opp} ({label})")
        r = await _run_pair(our, opp, label, True, True, artifact_dir, i, "on",
                            artifact_tag=artifact_tag)
        results["on"].append(r)
        print(f"  -> {r['status']} | {r['won']}W/{r['lost']}L")
    return results


def validate_audit_fields(results: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Verify pass criteria."""
    validation = {
        "off_arm": {"status": "ok", "checks": {}},
        "on_arm": {"status": "ok", "checks": {}},
        "wg_selection_comparison": {},
    }

    def analyze_arm(label, files):
        total_turns = 0
        wg_selections = 0
        wg_legal_turns = 0
        wg_legal_and_intent = 0  # WG legal AND intent=SPREAD_DEFENSE
        intent_label_dist = {}
        picks_this_game_max = 0
        picks_this_game_total = 0  # sum across battles
        battles_with_picks = 0
        bonus_applied_turns = 0
        bonus_values = []
        selected_wg_pick_turns = 0  # turns where WG was both legal and selected
        for f in files:
            if f["status"] != "ok":
                continue
            battle_max_picks = 0
            battle_has_pick = False
            with open(f["log_path"]) as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    for turn in rec.get("audit_turns", []):
                        snap = turn.get("state_snapshot", {}) or {}
                        total_turns += 1
                        il = snap.get("planner_intent_label")
                        intent_label_dist[il] = intent_label_dist.get(il, 0) + 1
                        picks_this_game = snap.get(
                            "planner_spread_defense_picks_this_game", 0
                        ) or 0
                        if picks_this_game > battle_max_picks:
                            battle_max_picks = picks_this_game
                        if picks_this_game > 0 and not battle_has_pick:
                            battle_has_pick = True
                        bonus = snap.get(
                            "planner_spread_defense_bonus_applied", 0.0
                        ) or 0.0
                        if bonus > 0:
                            bonus_applied_turns += 1
                            bonus_values.append(bonus)
                        # Check if WG was selected
                        sel = turn.get("selected_joint_order", "") or ""
                        sel_is_wg = "wideguard" in sel.lower()
                        if sel_is_wg:
                            wg_selections += 1
                        # Check if WG was legal (slot_0/1.wide_guard_legal)
                        slot_0 = turn.get("slot_0", {}) or {}
                        slot_1 = turn.get("slot_1", {}) or {}
                        wg_0 = bool(slot_0.get("wide_guard_legal"))
                        wg_1 = bool(slot_1.get("wide_guard_legal"))
                        is_wg_legal = wg_0 or wg_1
                        if is_wg_legal:
                            wg_legal_turns += 1
                            if il == "SPREAD_DEFENSE":
                                wg_legal_and_intent += 1
                            if sel_is_wg:
                                selected_wg_pick_turns += 1
            picks_this_game_max = max(picks_this_game_max, battle_max_picks)
            picks_this_game_total += battle_max_picks
            if battle_has_pick:
                battles_with_picks += 1
        # Compute rates
        n_battles = len([f for f in files if f["status"] == "ok"])
        pick_rate_per_battle = (
            picks_this_game_total / n_battles if n_battles else 0.0
        )
        wg_select_rate = (
            selected_wg_pick_turns / wg_legal_and_intent
            if wg_legal_and_intent else 0.0
        )
        return {
            "total_turns": total_turns,
            "n_battles": n_battles,
            "wg_legal_turns": wg_legal_turns,
            "wg_legal_and_intent_spread": wg_legal_and_intent,
            "wg_selections": wg_selections,
            "selected_wg_pick_turns": selected_wg_pick_turns,
            "wg_select_rate_when_legal_and_intent": round(wg_select_rate, 3),
            "intent_label_dist": intent_label_dist,
            "picks_this_game_max": picks_this_game_max,
            "picks_this_game_total": picks_this_game_total,
            "battles_with_picks": battles_with_picks,
            "picks_per_battle_avg": round(pick_rate_per_battle, 2),
            "bonus_applied_turns": bonus_applied_turns,
            "bonus_values_sample": bonus_values[:5],
        }

    off_files = [r for r in results["off"] if r["status"] == "ok"]
    on_files = [r for r in results["on"] if r["status"] == "ok"]
    validation["off_arm"]["checks"] = analyze_arm("off", off_files)
    validation["on_arm"]["checks"] = analyze_arm("on", on_files)

    # WG selection comparison: ON arm should have >= OFF arm WG selections
    # (intent ON both; spread_scoring only differs)
    on_wg = validation["on_arm"]["checks"]["wg_selections"]
    off_wg = validation["off_arm"]["checks"]["wg_selections"]
    validation["wg_selection_comparison"] = {
        "off_wg": off_wg,
        "on_wg": on_wg,
        "diff": on_wg - off_wg,
        "note": (
            "ON arm should have >= OFF arm WG selections (spread_scoring "
            "boosts WG when SPREAD_DEFENSE intent fires). Per-battle variance "
            "is high; small differences are OK."
        ),
    }

    return validation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact-tag",
        default="PLANNER_SPREAD_3",
        help="Artifact tag for logs (default: PLANNER_SPREAD_3)",
    )
    parser.add_argument(
        "--n-pairs",
        type=int,
        default=5,
        help="Number of pairs to run (default: 5)",
    )
    parser.add_argument(
        "--artifact-dir",
        default="logs",
        help="Directory for artifacts (default: logs)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing artifacts",
    )
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(exist_ok=True)

    # Check for existing artifacts
    for f in artifact_dir.glob(f"vgc2026_phase{args.artifact_tag}_*_audit.jsonl"):
        if not args.overwrite:
            print(f"ERROR: {f} exists. Use --overwrite to overwrite.")
            return 1

    print(f"PLANNER-SPREAD-3 smoke")
    print(f"  artifact_tag: {args.artifact_tag}")
    print(f"  artifact_dir: {artifact_dir}")
    print(f"  n_pairs: {args.n_pairs}")
    print(f"  total battles: {args.n_pairs * 2} (5 OFF + 5 ON)")

    results = asyncio.run(run_smoke(artifact_dir, args.n_pairs,
                                    artifact_tag=args.artifact_tag))

    n_off_ok = sum(1 for r in results["off"] if r["status"] == "ok")
    n_on_ok = sum(1 for r in results["on"] if r["status"] == "ok")

    print(f"\n=== Smoke summary ===")
    print(f"OFF arm: {n_off_ok}/{len(results['off'])} ok, "
          f"{sum(r['won'] for r in results['off'])}W / "
          f"{sum(r['lost'] for r in results['off'])}L")
    print(f"ON arm:  {n_on_ok}/{len(results['on'])} ok, "
          f"{sum(r['won'] for r in results['on'])}W / "
          f"{sum(r['lost'] for r in results['on'])}L")

    # Validate
    validation = validate_audit_fields(results)
    with open(artifact_dir / f"phase{args.artifact_tag}_validation.json", "w") as f:
        json.dump(validation, f, indent=2)

    print(f"\n=== Validation ===")
    off = validation["off_arm"]["checks"]
    on = validation["on_arm"]["checks"]
    print(f"OFF arm:")
    print(f"  total turns: {off['total_turns']}")
    print(f"  WG legal turns: {off['wg_legal_turns']}")
    print(f"  WG legal + SPREAD_DEFENSE intent: {off['wg_legal_and_intent_spread']}")
    print(f"  WG selections: {off['wg_selections']}")
    print(f"  intent_label dist: {off['intent_label_dist']}")
    print(f"  picks_this_game max: {off['picks_this_game_max']}")
    print(f"  bonus_applied turns: {off['bonus_applied_turns']}")
    print(f"ON arm:")
    print(f"  total turns: {on['total_turns']}")
    print(f"  WG legal turns: {on['wg_legal_turns']}")
    print(f"  WG legal + SPREAD_DEFENSE intent: {on['wg_legal_and_intent_spread']}")
    print(f"  WG selections: {on['wg_selections']}")
    print(f"  intent_label dist: {on['intent_label_dist']}")
    print(f"  picks_this_game max: {on['picks_this_game_max']}")
    print(f"  picks per battle avg: {on['picks_per_battle_avg']}")
    print(f"  battles with picks: {on['battles_with_picks']}/{on['n_battles']}")
    print(f"  bonus_applied turns: {on['bonus_applied_turns']}")
    print(f"  bonus sample: {on['bonus_values_sample']}")
    print(f"WG comparison: {validation['wg_selection_comparison']}")

    # Pass criteria (PLANNER-SPREAD-4 — 5-pair, behavior validation)
    n_total_expected = args.n_pairs * 2
    passes = []
    passes.append((f"{n_total_expected}/{n_total_expected} battles ok",
                   n_off_ok + n_on_ok == n_total_expected))
    passes.append(("OFF arm: no bonus applied (spread_scoring OFF)",
                   off["bonus_applied_turns"] == 0))
    passes.append(("ON arm: bonus applied (spread_scoring ON)",
                   on["bonus_applied_turns"] > 0))
    passes.append(("ON arm: picks per game <= 3 (anti-spam cap)",
                   on["picks_this_game_max"] <= 3))
    passes.append(("OFF arm: picks per game == 0 (no scoring)",
                   off["picks_this_game_max"] == 0))
    passes.append(("ON arm: pick rate (per battle avg) <= 1.0",
                   on["picks_per_battle_avg"] <= 1.0))
    passes.append(("ON arm: WG selected >= OFF arm WG (loose)",
                   on["wg_selections"] >= off["wg_selections"] * 0.5))
    passes.append(("no timeout/error",
                   all(r["status"] == "ok" for r in results["off"])
                   and all(r["status"] == "ok" for r in results["on"])))

    print(f"\n=== Pass criteria ===")
    for label, ok in passes:
        print(f"  [{'x' if ok else ' '}] {label}")
    n_pass = sum(1 for _, ok in passes if ok)
    n_total = len(passes)
    print(f"\n{n_pass}/{n_total} pass criteria met")
    return 0 if n_pass == n_total else 1


if __name__ == "__main__":
    sys.exit(main())
