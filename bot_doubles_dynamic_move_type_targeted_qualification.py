#!/usr/bin/env python3
"""Phase 6.3.7n.1 — Fixed-Team Targeted Aura Wheel Qualification (corrected).

Deterministic custom doubles scenario with protocol-revealed Volt Absorb.
Uses exact adopted defaults (no absorb avoidance override).

Watchdogs: heartbeat 10s, stall 60s, total 300s.

Usage:
  ./venv/bin/python bot_doubles_dynamic_move_type_targeted_qualification.py --artifact-tag mytag [--overwrite]
"""
import argparse
import asyncio
import csv
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
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig, find_protocol_ability_reveal_turn
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

HEARTBEAT_INTERVAL = 10
STALL_TIMEOUT = 60
ARM_TIMEOUT = 300


OUR_TEAM = """Morpeko @ Leftovers
Ability: Hunger Switch
EVs: 252 HP / 252 Atk
Adamant Nature
- Aura Wheel
- Protect
- Knock Off
- Fake Out

Blissey @ Leftovers
Ability: Natural Cure
EVs: 252 HP / 252 Def
Bold Nature
- Heal Pulse
- Protect
- Soft-Boiled
- Helping Hand"""

OPP_TEAM = """Lanturn @ Leftovers
Ability: Volt Absorb
EVs: 252 HP / 252 Def
Bold Nature
- Protect
- Volt Switch
- Scald
- Thunder Wave

Umbreon @ Leftovers
Ability: Synchronize
EVs: 252 HP / 252 Def
Bold Nature
- Protect
- Wish
- Foul Play
- Heal Bell"""


class ScriptedOpponent(Player):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("battle_format", "gen9doublescustomgame")
        kwargs.setdefault("team", ConstantTeambuilder(OPP_TEAM))
        super().__init__(*args, **kwargs)

    def choose_move(self, battle):
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)
        turn = battle.turn
        phase = (turn - 1) % 4
        strategy = [
            ("protect", "protect"),
            ("voltswitch", "protect"),
            ("protect", "protect"),
            ("scald", "healbell"),
        ]
        act0, act1 = strategy[phase]
        try:
            valid = battle.valid_orders
            def _pick(orders, move_id):
                for o in orders:
                    if hasattr(o, "order") and hasattr(o.order, "id") and o.order.id == move_id:
                        return o
                for o in orders:
                    if hasattr(o, "order") and hasattr(o, "order"):
                        return o
                return orders[0] if orders else None
            o0 = _pick(valid[0], act0)
            o1 = _pick(valid[1], act1)
            if o0 and o1:
                return DoubleBattleOrder(o0, o1)
        except Exception:
            pass
        return self.choose_random_move(battle)


class StallError(Exception):
    pass


# ========================== Evidence extraction ==========================

def _extract_evidence(log_path):
    battles = {}
    if not os.path.exists(log_path):
        return battles
    with open(log_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            bt = rec.get("battle_tag", "")
            if not bt:
                continue
            ev = _extract_one_battle(rec)
            battles[bt] = ev
    return battles


def _extract_one_battle(rec):
    bt = rec.get("battle_tag", "")
    ev = {
        "battle_tag": bt, "setup_valid": False,
        "reveal_turn": None, "ability_resolution_source": "",
        "setup_reveal_action_turn": None,
        "setup_reveal_action_move": "",
        "setup_reveal_was_unknown_before": False,
        "setup_target_identity": "",
        "full_belly_turn": None, "hangry_turn": None,
        "reverse_full_belly_turn": None,
        "full_belly_opportunity": False, "full_belly_blocked": False,
        "full_belly_selected": False, "full_belly_avoided": False,
        "full_belly_safe_action_kind": "",
        "full_belly_safe_action_move_id": "",
        "full_belly_safe_action_target_position": 0,
        "hangry_opportunity": False, "hangry_blocked": False,
        "hangry_selected": False,
        "reverse_full_belly_opportunity": False,
        "reverse_full_belly_blocked": False, "reverse_full_belly_selected": False,
        "reverse_full_belly_avoided": False,
        "reverse_full_belly_safe_action_kind": "",
        "reverse_full_belly_safe_action_move_id": "",
        "reverse_full_belly_safe_action_target_position": 0,
        "accounting_pass": True, "failure_reason": "",
    }

    blocked_total = 0; sel_total = 0; avd_total = 0
    reveal_turn = None; ability_source = ""
    setup_turn = None; setup_move = ""
    setup_candidates = []
    reasons = []

    turn_data = list(rec.get("audit_turns", []))

    # ---- PASS 1: detect setup (unknown-before selected Aura Wheel) ----
    for td in turn_data:
        turn = td.get("turn", 0)
        for sk in ("slot_0", "slot_1"):
            slot = td.get(sk, {})
            table = slot.get("dynamic_type_absorb_candidate_target_table", [])
            for row in table:
                move_id = row.get("move_id", "")
                form = row.get("form", "")
                eff = row.get("effective_type", "")
                tgt_species = (row.get("target_species", "") or "").lower()
                target_identity = row.get("target_identity", "") or ""
                tgt_abil = row.get("target_known_ability", "") or ""
                ab_src = row.get("target_known_ability_source", "") or ""
                known_before = row.get("target_ability_known_before_decision", False)
                row_reveal = row.get("target_ability_reveal_turn")
                row_dturn = row.get("decision_turn", 0)
                is_sel = row.get("selected", False)

                if move_id != "aurawheel":
                    continue
                if form != "morpeko" or eff != "ELECTRIC":
                    continue
                if tgt_species != "lanturn":
                    continue
                if not target_identity:
                    continue
                if not is_sel:
                    continue
                if tgt_abil != "" or ab_src != "" or known_before or row_reveal is not None:
                    continue

                if row_dturn != turn:
                    reasons.append(f"setup decision_turn mismatch row={row_dturn} turn={turn}")
                else:
                    setup_candidates.append({
                        "turn": turn,
                        "move_id": move_id,
                        "target_identity": target_identity,
                    })

    # ---- PASS 2: accumulate protocol reveal + measured phases ----
    for td in turn_data:
        turn = td.get("turn", 0)
        for sk in ("slot_0", "slot_1"):
            slot = td.get(sk, {})
            if slot.get("dynamic_type_absorb_candidate_blocked"):
                blocked_total += 1
            if slot.get("dynamic_type_absorb_selected"):
                sel_total += 1
            if slot.get("dynamic_type_absorb_avoided"):
                avd_total += 1
            if slot.get("dynamic_type_absorb_selected") and slot.get("dynamic_type_absorb_avoided"):
                ev["accounting_pass"] = False
            table = slot.get("dynamic_type_absorb_candidate_target_table", [])
            for row in table:
                form = row.get("form", "")
                eff = row.get("effective_type", "")
                tgt_abil = row.get("target_known_ability", "") or ""
                tgt_species = (row.get("target_species", "") or "").lower()
                target_identity = row.get("target_identity", "") or ""
                ac_blocked = row.get("ability_blocked", False)
                is_sel = row.get("selected", False)
                ab_src = row.get("target_known_ability_source", "") or ""
                known_before = row.get("target_ability_known_before_decision", False)
                row_reveal = row.get("target_ability_reveal_turn")
                row_dturn = row.get("decision_turn", 0)

                if tgt_abil != "voltabsorb":
                    continue
                if tgt_species != "lanturn":
                    continue
                if not target_identity:
                    continue
                if row_dturn != turn:
                    reasons.append(f"decision_turn mismatch row={row_dturn} turn={turn}")
                    continue
                if ab_src != "protocol_revealed" or not known_before or row_reveal is None:
                    continue

                if reveal_turn is None:
                    reveal_turn = row_reveal
                    ability_source = ab_src
                    ev["setup_target_identity"] = target_identity
                if target_identity != ev["setup_target_identity"]:
                    continue

                avoided = slot.get("dynamic_type_absorb_avoided", False)
                safe_action = _get_slot_safe_action(slot, row)

                if form == "morpeko" and eff == "ELECTRIC":
                    if ev["full_belly_turn"] is None and turn > reveal_turn:
                        ev["full_belly_turn"] = turn
                        ev["full_belly_opportunity"] = True
                        ev["full_belly_blocked"] = ac_blocked
                        ev["full_belly_selected"] = is_sel
                        ev["full_belly_avoided"] = avoided
                        if ac_blocked and not is_sel and avoided and safe_action:
                            ev["full_belly_safe_action_kind"] = safe_action["kind"]
                            ev["full_belly_safe_action_move_id"] = safe_action["move_id"]
                            ev["full_belly_safe_action_target_position"] = safe_action["target_position"]
                    elif ev["full_belly_turn"] is not None and ev["reverse_full_belly_turn"] is None:
                        if ev["hangry_turn"] is not None and turn > ev["hangry_turn"]:
                            ev["reverse_full_belly_turn"] = turn
                            ev["reverse_full_belly_opportunity"] = True
                            ev["reverse_full_belly_blocked"] = ac_blocked
                            ev["reverse_full_belly_selected"] = is_sel
                            ev["reverse_full_belly_avoided"] = avoided
                            if ac_blocked and not is_sel and avoided and safe_action:
                                ev["reverse_full_belly_safe_action_kind"] = safe_action["kind"]
                                ev["reverse_full_belly_safe_action_move_id"] = safe_action["move_id"]
                                ev["reverse_full_belly_safe_action_target_position"] = safe_action["target_position"]
                elif form == "morpekohangry" and eff == "DARK":
                    if ev["hangry_turn"] is None and ev["full_belly_turn"] is not None and turn > ev["full_belly_turn"]:
                        ev["hangry_turn"] = turn
                        ev["hangry_opportunity"] = True
                        ev["hangry_blocked"] = ac_blocked
                        ev["hangry_selected"] = is_sel

    ev["reveal_turn"] = reveal_turn
    ev["ability_resolution_source"] = ability_source

    matching_setup = next(
        (
            candidate for candidate in setup_candidates
            if candidate["turn"] == reveal_turn
            and candidate["target_identity"] == ev["setup_target_identity"]
        ),
        None,
    )
    if matching_setup:
        setup_turn = matching_setup["turn"]
        setup_move = matching_setup["move_id"]

    if setup_turn is not None and setup_move:
        ev["setup_reveal_action_turn"] = setup_turn
        ev["setup_reveal_action_move"] = setup_move
        ev["setup_reveal_was_unknown_before"] = True

    if blocked_total != sel_total + avd_total:
        ev["accounting_pass"] = False
        reasons.append("accounting invariant failed")

    if not ev["setup_reveal_was_unknown_before"]:
        reasons.append("no unknown-before setup Aura Wheel selected targeting Lanturn")
    elif ev["setup_reveal_action_turn"] != reveal_turn:
        reasons.append(f"setup turn {ev['setup_reveal_action_turn']} != reveal turn {reveal_turn}")
    if reveal_turn is None:
        reasons.append("no protocol reveal turn after setup")
    if not ev["full_belly_opportunity"]:
        reasons.append("missing post-reveal Full Belly opportunity")
    elif not ev["full_belly_blocked"]:
        reasons.append("Full Belly not blocked")
    elif ev["full_belly_selected"]:
        reasons.append("Full Belly selected (should be avoided)")
    elif not ev["full_belly_avoided"]:
        reasons.append("Full Belly avoided flag not set on slot")
    elif not ev["full_belly_safe_action_kind"]:
        reasons.append("no safe alternative action for blocked Full Belly")
    if not ev["hangry_opportunity"]:
        reasons.append("missing Hangry after Full Belly")
    elif ev["hangry_blocked"]:
        reasons.append("Hangry blocked (should be legal)")
    if not ev["reverse_full_belly_opportunity"]:
        reasons.append("missing reverse Full Belly after Hangry")
    elif not ev["reverse_full_belly_blocked"]:
        reasons.append("reverse Full Belly not blocked")
    elif ev["reverse_full_belly_selected"]:
        reasons.append("reverse Full Belly selected (should be avoided)")
    elif not ev["reverse_full_belly_avoided"]:
        reasons.append("reverse Full Belly avoided flag not set")
    elif not ev["reverse_full_belly_safe_action_kind"]:
        reasons.append("no safe alternative for reversed Full Belly")

    ev["setup_valid"] = len(reasons) == 0
    ev["failure_reason"] = "; ".join(reasons)
    return ev


def _get_slot_safe_action(slot, blocked_row):
    """Return structured evidence when this slot selected a safe alternative."""
    kind = str(slot.get("selected_action_kind", "") or "")
    move_id = str(slot.get("selected_action_move_id", "") or "")
    target_position = int(slot.get("selected_action_target_position", 0) or 0)
    species = str(slot.get("selected_action_species", "") or "")
    only_legal = bool(slot.get("selected_action_only_legal", False))
    if kind == "move":
        if not move_id:
            return None
        if (
            move_id == str(blocked_row.get("move_id", "") or "")
            and target_position == int(blocked_row.get("target_position", 0) or 0)
        ):
            return None
    elif kind == "switch":
        if not species:
            return None
    elif kind == "pass":
        if not only_legal:
            return None
    else:
        return None
    return {
        "kind": kind,
        "move_id": move_id,
        "target_position": target_position,
        "species": species,
        "only_legal": only_legal,
    }


# ========================== Runner ==========================

async def _cleanup_player(player):
    try:
        if hasattr(player, "ps_client") and hasattr(player.ps_client, "_stop_listening"):
            await player.ps_client._stop_listening()
    except Exception:
        pass


async def main():
    p = argparse.ArgumentParser(description="Targeted Aura Wheel Qualification")
    p.add_argument("--artifact-tag", type=str, required=True)
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()
    tag = args.artifact_tag
    jsonl_path = f"logs/dynamic_type_targeted_{tag}.jsonl"
    csv_path = f"logs/dynamic_type_targeted_{tag}.csv"

    if not args.overwrite:
        existing = [p for p in (jsonl_path, csv_path) if os.path.exists(p)]
        if existing:
            print("Artifacts already exist:")
            for ep in existing:
                print(f"  {ep}")
            sys.exit(2)

    config = DoublesDamageAwareConfig()
    assert config.enable_ability_hard_safety_only is True
    assert config.ability_hard_safety_direct_absorb_only is True
    assert config.ability_hard_safety_avoid_absorb is False
    assert config.enable_ability_awareness is False
    print("Default config verified.")

    MAX_BATTLES = 10
    REQUIRED_VALID = 3
    valid_count = 0
    attempt = 0
    any_failure = False
    all_evidence = {}
    our_team = ConstantTeambuilder(OUR_TEAM)

    while valid_count < REQUIRED_VALID and attempt < MAX_BATTLES:
        attempt += 1
        suffix = str(int(time.time() * 1000) % 100000)
        bot_name = f"Morpeko_{suffix}"[:18]
        opp_name = f"Lanturn_{suffix}"[:18]
        status = "ok"
        caught_exception = None

        audit_logger = DoublesDecisionAuditLogger(
            filepath=jsonl_path, reset=(attempt == 1),
            detail_level="top5", benchmark_arm=f"Q{attempt}",
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

        print(f"\n--- Battle {attempt}/{MAX_BATTLES} ---")

        start_time = time.time()
        state = {"last_battle_time": start_time, "last_finished": 0}

        async def heartbeat():
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                elapsed = time.time() - start_time
                finished = player.n_finished_battles
                since_last = time.time() - state["last_battle_time"]
                if finished > state["last_finished"]:
                    state["last_battle_time"] = time.time()
                    state["last_finished"] = finished
                print(f"  [{attempt}] {elapsed:.0f}s | {finished}/1 | {since_last:.0f}s since last")
                if since_last > STALL_TIMEOUT:
                    raise StallError(f"Stall: no progress in {STALL_TIMEOUT}s")

        battle_task = asyncio.create_task(player.battle_against(opponent, n_battles=1))
        watchdog_task = asyncio.create_task(heartbeat())
        try:
            done, pending = await asyncio.wait_for(
                asyncio.wait({battle_task, watchdog_task}, return_when=asyncio.FIRST_COMPLETED),
                timeout=ARM_TIMEOUT,
            )
            if watchdog_task in done:
                w_exc = watchdog_task.exception()
                if w_exc and not isinstance(w_exc, asyncio.CancelledError):
                    raise w_exc
            if battle_task in done:
                b_exc = battle_task.exception()
                if b_exc and not isinstance(b_exc, asyncio.CancelledError):
                    raise b_exc
        except asyncio.TimeoutError:
            caught_exception = f"ARM TIMEOUT after {ARM_TIMEOUT}s"
            status = "timeout"
            any_failure = True
        except StallError as e:
            caught_exception = str(e)
            status = "stall"
            any_failure = True
        except Exception as e:
            caught_exception = f"{type(e).__name__}: {e}"
            status = "crash"
            any_failure = True
        finally:
            for task in (watchdog_task, battle_task):
                if task and not task.done():
                    task.cancel()
            for task in (watchdog_task, battle_task):
                if task:
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

        await _cleanup_player(player)
        await _cleanup_player(opponent)

        if caught_exception:
            print(f"  [{attempt}] {status.upper()}: {caught_exception}")
            continue

        evidence = _extract_evidence(jsonl_path)
        for bt2, ev2 in list(evidence.items()):
            if bt2 not in all_evidence:
                all_evidence[bt2] = ev2
        valid_count = sum(1 for e in all_evidence.values() if e["setup_valid"])

        for bt2, ev2 in evidence.items():
            label = "VALID" if ev2["setup_valid"] else "DISCARD"
            r = "R" if ev2["reveal_turn"] else "-"
            fb = ev2["full_belly_turn"] or "-"
            hg = ev2["hangry_turn"] or "-"
            rv = ev2["reverse_full_belly_turn"] or "-"
            print(f"  {bt2}: {label} rev_t={r} fb_t={fb} hg_t={hg} r_t={rv} "
                  f"FB_blk={ev2['full_belly_blocked']} FB_sel={ev2['full_belly_selected']} "
                  f"FB_avd={ev2['full_belly_avoided']} "
                  f"HG_blk={ev2['hangry_blocked']} "
                  f"R_blk={ev2['reverse_full_belly_blocked']} R_avd={ev2['reverse_full_belly_avoided']}")
            if not ev2["setup_valid"]:
                print(f"    fail: {ev2['failure_reason']}")

        if valid_count >= REQUIRED_VALID:
            print(f"\n  Target met: {valid_count} valid battles")
            break

    total_valid = sum(1 for e in all_evidence.values() if e["setup_valid"])
    total_discarded = len(all_evidence) - total_valid

    print(f"\n=== Summary ===")
    print(f"  Attempted: {attempt}")
    print(f"  Valid: {total_valid}")
    print(f"  Discarded: {total_discarded}")

    csv_fields = [
        "battle_tag", "setup_valid", "reveal_turn",
        "setup_reveal_action_turn", "setup_reveal_action_move",
        "setup_reveal_was_unknown_before", "setup_target_identity",
        "full_belly_turn", "hangry_turn", "reverse_full_belly_turn",
        "ability_resolution_source",
        "full_belly_opportunity", "full_belly_blocked", "full_belly_selected",
        "full_belly_avoided", "full_belly_safe_action_kind",
        "full_belly_safe_action_move_id", "full_belly_safe_action_target_position",
        "hangry_opportunity", "hangry_blocked", "hangry_selected",
        "reverse_full_belly_opportunity", "reverse_full_belly_blocked",
        "reverse_full_belly_selected", "reverse_full_belly_avoided",
        "reverse_full_belly_safe_action_kind",
        "reverse_full_belly_safe_action_move_id",
        "reverse_full_belly_safe_action_target_position",
        "accounting_pass", "failure_reason",
    ]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields)
        w.writeheader()
        for bt, ev in all_evidence.items():
            w.writerow({k: ev.get(k, "") for k in csv_fields})
    print(f"\nSaved: {csv_path}")

    if total_valid < REQUIRED_VALID or any_failure:
        print(f"FAILURE: valid={total_valid} < required={REQUIRED_VALID}" if total_valid < REQUIRED_VALID else "FAILURE: timeout/stall/crash")
        sys.exit(3)
    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
