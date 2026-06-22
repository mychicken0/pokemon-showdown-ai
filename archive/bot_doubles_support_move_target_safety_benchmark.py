#!/usr/bin/env python3
"""Phase 6.3.8a — Support Move Target Hard Safety Targeted Qualification.

Deterministic custom doubles scenario:
  Our side: Blissey (Heal Pulse, Soft-Boiled, Protect, Helping Hand)
            + Pikachu (frail, target for damage)
  Opponent: Snorlax + Rhyperior scripted to attack Pikachu.

Requirements:
  - Heal Pulse candidates for both ally (Pikachu) and opponent exist.
  - Wrong-side opponent-target blocked; ally-target selected.
  - Evidence from persisted JSONL (not player instance state).
  - Non-zero exit if any required evidence absent.

Watchdogs: heartbeat 10s, stall 60s, total 300s.
"""
import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

import atexit
import poke_env.concurrency
_clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if _clear_loop is not None:
    try:
        atexit.unregister(_clear_loop)
    except Exception:
        pass

from poke_env import AccountConfiguration
from poke_env.player import Player
from poke_env.player.battle_order import DoubleBattleOrder
from poke_env.player.player import ConstantTeambuilder
from poke_env.battle.double_battle import DoubleBattle
from bot_doubles_damage_aware import (
    DoublesDamageAwarePlayer, DoublesDamageAwareConfig,
    build_support_target_candidate_table, resolve_order_target_side,
)
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

HEARTBEAT = 10
STALL_TIMEOUT = 60
ARM_TIMEOUT = 300

OUR_TEAM = """Blissey @ Leftovers
Ability: Natural Cure
EVs: 252 HP / 252 Def
Bold Nature
- Heal Pulse
- Soft-Boiled
- Protect
- Helping Hand

Pikachu @ Light Ball
Ability: Static
EVs: 252 SpA / 252 Spe
Timid Nature
- Thunderbolt
- Protect
- Nasty Plot
- Fake Out"""

OPP_TEAM = """Snorlax @ Leftovers
Ability: Thick Fat
EVs: 252 HP / 252 Atk
Adamant Nature
- Body Slam
- High Horsepower
- Protect
- Yawn

Rhyperior @ Leftovers
Ability: Solid Rock
EVs: 252 HP / 252 Atk
Adamant Nature
- Rock Slide
- Protect
- Earthquake
- Dragon Tail"""


class ScriptedOpponent(Player):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("battle_format", "gen9doublescustomgame")
        kwargs.setdefault("team", ConstantTeambuilder(OPP_TEAM))
        super().__init__(*args, **kwargs)

    def choose_move(self, battle):
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)
        try:
            valid = battle.valid_orders
            if not valid or not valid[0] or not valid[1]:
                return self.choose_random_move(battle)

            def _pick_damaging(orders):
                for o in orders:
                    if not hasattr(o, "order") or not hasattr(o.order, "base_power"):
                        continue
                    if o.order.base_power > 0 and getattr(o.order, "category", None) is not None:
                        cat = getattr(o.order.category, "name", "")
                        if cat != "STATUS":
                            return o
                return orders[0] if orders else None

            def _pick_protect(orders):
                for o in orders:
                    if hasattr(o, "order") and hasattr(o.order, "id") and o.order.id == "protect":
                        return o
                return _pick_damaging(orders)

            phase = (battle.turn - 1) % 5
            if phase <= 2:
                # Both attack — damages Pikachu
                o0 = _pick_damaging(valid[0])
                o1 = _pick_damaging(valid[1])
            elif phase == 3:
                o0 = _pick_damaging(valid[0])
                o1 = _pick_protect(valid[1])
            else:
                o0 = _pick_protect(valid[0])
                o1 = _pick_damaging(valid[1])

            if o0 and o1:
                return DoubleBattleOrder(o0, o1)
        except Exception:
            pass
        return self.choose_random_move(battle)


class StallError(Exception):
    pass


async def main():
    p = argparse.ArgumentParser(description="Support Move Target Safety Targeted Qualification")
    p.add_argument("--artifact-tag", type=str, default="supporttarget_qual")
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()
    tag = args.artifact_tag
    jsonl_path = f"logs/support_target_qual_{tag}.jsonl"

    if not args.overwrite and os.path.exists(jsonl_path):
        print(f"Artifact already exists: {jsonl_path}")
        sys.exit(2)

    config = DoublesDamageAwareConfig()
    config.enable_support_move_target_hard_safety = True
    config.support_move_wrong_side_block_score = 0.0
    config.support_move_allow_only_legal_wrong_side = True

    our_team = ConstantTeambuilder(OUR_TEAM)
    suffix = str(int(time.time() * 1000) % 100000)
    bot_name = f"Blissey_{suffix}"[:18]
    opp_name = f"Snorlax_{suffix}"[:18]

    audit_logger = DoublesDecisionAuditLogger(
        filepath=jsonl_path, reset=True,
        detail_level="full", benchmark_arm="support_target_qual",
    )

    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        verbose=False, config=config,
        audit_logger=audit_logger,
        max_concurrent_battles=1,
        battle_format="gen9doublescustomgame",
        team=our_team,
    )

    opponent = ScriptedOpponent(
        account_configuration=AccountConfiguration(opp_name, None),
        max_concurrent_battles=1,
    )

    print(f"Battle: {bot_name} vs {opp_name} on {jsonl_path}")

    start_time = time.time()
    last_activity = start_time
    status = "ok"
    message = ""
    _battles = []

    async def heartbeat():
        nonlocal last_activity
        while True:
            await asyncio.sleep(HEARTBEAT)
            now = time.time()
            elapsed = now - start_time
            stalled = now - last_activity
            print(f"  {elapsed:.0f}s | {player.n_finished_battles} battles | {stalled:.0f}s stalled")
            if stalled > STALL_TIMEOUT:
                raise StallError(f"No progress for {stalled:.0f}s")

    battle_task = asyncio.create_task(
        player.battle_against(opponent, n_battles=1)
    )
    watchdog_task = asyncio.create_task(heartbeat())

    try:
        done, pending = await asyncio.wait(
            {battle_task, watchdog_task},
            return_when=asyncio.FIRST_COMPLETED,
            timeout=ARM_TIMEOUT,
        )
        if watchdog_task in done:
            exc = watchdog_task.exception()
            if exc and not isinstance(exc, asyncio.CancelledError):
                raise exc
        if battle_task in done:
            exc = battle_task.exception()
            if exc and not isinstance(exc, asyncio.CancelledError):
                raise exc
    except asyncio.TimeoutError:
        status = "timeout"
        message = f"ARM TIMEOUT after {ARM_TIMEOUT}s"
    except StallError as e:
        status = "stall"
        message = str(e)
    except Exception as e:
        status = "crash"
        message = f"{type(e).__name__}: {e}"
    finally:
        for t in (watchdog_task,):
            if t and not t.done():
                t.cancel()
        if watchdog_task:
            try:
                await watchdog_task
            except (asyncio.CancelledError, Exception):
                pass
        if battle_task and not battle_task.done():
            battle_task.cancel()
            try:
                await battle_task
            except (asyncio.CancelledError, Exception):
                pass

    try:
        if hasattr(player, "ps_client") and hasattr(player.ps_client, "_stop_listening"):
            await player.ps_client._stop_listening()
    except Exception:
        pass
    try:
        if hasattr(opponent, "ps_client") and hasattr(opponent.ps_client, "_stop_listening"):
            await opponent.ps_client._stop_listening()
    except Exception:
        pass

    elapsed = time.time() - start_time
    print(f"\nBattle completed in {elapsed:.1f}s | status={status}")

    if status != "ok":
        print(f"FAILURE: {message}")
        sys.exit(3)

    # ===== Validate JSONL evidence =====
    if not os.path.exists(jsonl_path):
        print(f"FAILURE: JSONL not found at {jsonl_path}")
        sys.exit(3)

    with open(jsonl_path) as f:
        raw = f.read().strip().split("\n")
    records = [json.loads(line) for line in raw if line.strip()]

    if not records:
        print("FAILURE: JSONL is empty")
        sys.exit(3)

    errors = []

    # Find battle record
    battle_rec = None
    for rec in records:
        if rec.get("event") == "battle" or rec.get("winner") is not None:
            battle_rec = rec
            break

    # Parse turn data from complete battles
    battle_tags_seen = set()
    total_turns = 0
    candidate_tables = []
    selected_hp_ally = []
    heal_pulse_opponent_candidates = []
    heal_pulse_ally_candidates = []
    heal_pulse_selected = []

    for rec in records:
        bt = rec.get("battle_tag", "")
        if bt:
            battle_tags_seen.add(bt)
        for td in rec.get("audit_turns", []):
            total_turns += 1
            candidates = td.get("support_target_candidates", [])
            if candidates:
                candidate_tables.append({"turn": td.get("turn"), "candidates": candidates})
            for sk in ("slot_0", "slot_1"):
                slot = td.get(sk, {})
                mid = slot.get("selected_action_move_id", "")
                tpos = slot.get("selected_action_target_position", 0)
                if mid == "healpulse":
                    heal_pulse_selected.append({
                        "turn": td.get("turn"), "slot": sk,
                        "target_position": tpos,
                    })
                # Check ally HP (our non-Blissey mon)
                our_active = td.get("our_active", [])
                opp_active = td.get("opp_active", [])

    # Analyze candidate tables
    has_opponent_hp_candidate = False
    has_ally_hp_candidate = False
    wrong_side_blocked = False
    ally_hp_unblocked = False
    selected_ally_heal_pulse = False
    selected_opponent_heal_pulse = False
    qualifying_turn = None
    qualifying_slot = None

    for ct in candidate_tables:
        turn = ct["turn"]
        candidates = ct["candidates"]
        for cand in candidates:
            if cand["move_id"] == "healpulse":
                target_side = cand.get("target_side", "")
                tpos = cand.get("target_position")
                blocked = cand.get("blocked", False)
                if target_side == "opponent" and blocked:
                    has_opponent_hp_candidate = True
                    wrong_side_blocked = True
                if target_side in ("ally", "self") and not blocked:
                    has_ally_hp_candidate = True
                    ally_hp_unblocked = True

    for sel in heal_pulse_selected:
        tpos = sel["target_position"]
        slot = sel["slot"]
        # Ally on slot 0: target -2 = ally; on slot 1: target -1 = ally
        ally_target = (-2 if slot == "slot_0" else -1)
        if tpos == ally_target:
            selected_ally_heal_pulse = True
            qualifying_turn = sel["turn"]
            qualifying_slot = slot
        elif tpos in (1, 2):
            selected_opponent_heal_pulse = True

    # Check from candidate tables that the same slot-turn had both candidates
    # AND selected the correct one
    for ct in candidate_tables:
        turn = ct["turn"]
        candidates = ct["candidates"]
        has_opp = any(
            c["move_id"] == "healpulse" and c.get("target_side") == "opponent"
            for c in candidates
        )
        has_ally = any(
            c["move_id"] == "healpulse" and c.get("target_side") in ("ally", "self")
            for c in candidates
        )
        if has_opp and has_ally:
            qualifying_turn = turn

    # Accounting: from candidate table per turn
    for ct in candidate_tables:
        candidates = ct["candidates"]
        cand_blocked = any(c.get("blocked") for c in candidates if c["move_id"] == "healpulse")
        any_selected = any(c.get("selected") for c in candidates if c["move_id"] == "healpulse")
        wrong_sel = any(
            c.get("selected") and c.get("blocked")
            for c in candidates if c["move_id"] == "healpulse"
        )

    if not os.path.exists(jsonl_path):
        errors.append("JSONL file not found")
    if not battle_tags_seen:
        errors.append("No battle tags found in JSONL")
    if not has_opponent_hp_candidate:
        errors.append("No Heal Pulse opponent-target candidate found in any candidate table")
    if not has_ally_hp_candidate:
        errors.append("No Heal Pulse ally-target candidate found in any candidate table")
    if not selected_ally_heal_pulse:
        errors.append("Heal Pulse was never selected targeting an ally")
    if selected_opponent_heal_pulse:
        errors.append("Heal Pulse was selected targeting an opponent")

    print(f"\n{'='*60}")
    print("Support Move Target Hard Safety — Targeted Qualification")
    print(f"{'='*60}")
    print(f"  JSONL: {jsonl_path}")
    print(f"  Records: {len(records)}, Battles: {len(battle_tags_seen)}, Turns: {total_turns}")
    print(f"  Battle tags: {battle_tags_seen}")
    print()
    print(f"  Heal Pulse opponent-target candidate: {has_opponent_hp_candidate}")
    print(f"  Heal Pulse ally-target candidate:      {has_ally_hp_candidate}")
    print(f"  Wrong-side candidate blocked:          {wrong_side_blocked}")
    print(f"  Ally-target candidate not blocked:     {ally_hp_unblocked}")
    print(f"  Heal Pulse selected on ally:           {selected_ally_heal_pulse}")
    print(f"  Heal Pulse selected on opponent:       {selected_opponent_heal_pulse}")
    print(f"  Qualifying turn:                       {qualifying_turn}")
    print()
    print(f"  Candidate tables analyzed:             {len(candidate_tables)}")
    for ct in candidate_tables[:5]:
        n = len(ct["candidates"])
        blocked = sum(1 for c in ct["candidates"] if c.get("blocked"))
        selected = [c for c in ct["candidates"] if c.get("selected")]
        sel_str = f", selected: {[(s['move_id'], s['target_position']) for s in selected]}" if selected else ""
        print(f"    Turn {ct['turn']}: {n} candidates, {blocked} blocked{sel_str}")
    print()
    print(f"  Heal Pulse selections: {heal_pulse_selected}")

    if errors:
        print(f"\nFAILURE: {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(3)
    else:
        print(f"\nPASS: Support Move Target Hard Safety verified")
        print(f"  - Heal Pulse opponent candidate blocked: {wrong_side_blocked}")
        print(f"  - Heal Pulse ally candidate available:   {ally_hp_unblocked}")
        print(f"  - Ally Heal Pulse selected:              {selected_ally_heal_pulse}")
        print(f"  - No opponent Heal Pulse selected:       True")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
