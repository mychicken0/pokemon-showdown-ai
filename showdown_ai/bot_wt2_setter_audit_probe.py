#!/usr/bin/env python3
"""Phase WT-2 — Setter Move Selection Audit Probe.

A small live probe that runs N battles on the
already-running local Pokemon Showdown server and
records every turn's selected actions, state snapshot
(weather/fields), and per-slot legal actions.

Question: Does the bot ever select a setter MOVE
(raindance, sunnyday, electricterrain, etc.) when
the bot team has the setter as a legal action?

The probe uses battle_against (not ladder) so the
custom teams work in gen9doublescustomgame format.

Watchdogs: heartbeat 30s, stall 180s, total 300s.

The probe does NOT tune or adopt setter scoring.
It only audits whether the bot selects setter moves.
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
# Also add project root (for doubles_engine)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Unregister poke-env's broken atexit hook
import poke_env.concurrency
_clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if _clear_loop is not None:
    try:
        atexit.unregister(_clear_loop)
    except Exception:
        pass

import poke_env_test_cleanup  # noqa: F401

from poke_env import AccountConfiguration
from poke_env.player.player import Player
from poke_env.player.battle_order import DoubleBattleOrder
from poke_env.battle.double_battle import DoubleBattle
from poke_env.player.baselines import RandomPlayer

from bot_doubles_damage_aware import DoublesDamageAwarePlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

LOCAL_BASE = "WT2set"
HEALTH_URL = "http://localhost:8000"
HEALTH_TIMEOUT = 2.0

HEARTBEAT_INTERVAL = 30
STALL_TIMEOUT = 180
ARM_TIMEOUT = 300


def check_localhost_healthy(timeout: float = HEALTH_TIMEOUT) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def json_to_showdown(team_dict: Dict[str, Any]) -> str:
    """Convert a JSON team dict to Showdown text format."""
    lines = []
    for p in team_dict.get('team', []):
        species = p['species']
        if p.get('item'):
            lines.append(f"{species} @ {p['item']}")
        else:
            lines.append(species)
        lines.append(f"Ability: {p['ability']}")
        evs = p.get('evs', {})
        if evs:
            ev_parts = [f"{v} {k.upper()}" for k, v in evs.items() if v > 0]
            if ev_parts:
                lines.append("EVs: " + " / ".join(ev_parts))
        if p.get('nature'):
            lines.append(f"{p['nature']} Nature")
        if p.get('level') and p['level'] != 100:
            lines.append(f"Level: {p['level']}")
        for move in p.get('moves', []):
            lines.append(f"- {move}")
        lines.append("")
    return "\n".join(lines)


# Our team: data/curated_teams/custom/wt2_audit_team_v1.json
OUR_TEAM_JSON = "data/curated_teams/custom/wt2_audit_team_v1.json"

# Opp team: a generic team with no setters
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


# Setter move IDs that we audit
SETTER_MOVES = {
    "raindance", "sunnyday", "sandstorm", "hail", "snowscape",
    "electricterrain", "grassyterrain", "mistyterrain", "psychicterrain",
}


def _enum_keys(battle, key):
    """Get list of weather/field keys from poke-env battle."""
    out = []
    try:
        if key == "weather":
            for k in battle.weather:
                out.append(str(k).split(".")[-1].lower())
        elif key == "fields":
            for k in battle.fields:
                out.append(str(k).split(".")[-1].lower())
    except Exception:
        pass
    return out


def _move_id_from_order(order):
    """Extract move ID from a battle order.

    The order can be:
    - A SingleBattleOrder with .order (the inner order) which has .id
    - A DoubleBattleOrder.first_order / .second_order
    - A Pokemon switch order with .poke / .pokemon
    """
    try:
        if order is None:
            return None
        # Unwrap DoubleBattleOrder
        if hasattr(order, "first_order") and not hasattr(order, "order"):
            # It's a joint order; recurse on both (we only use first)
            pass
        # SingleBattleOrder has .order
        if hasattr(order, "order") and order.order is not None:
            inner = order.order
            if hasattr(inner, "id"):
                return str(inner.id).lower()
            return str(inner).lower()
        # Switch order has .poke
        if hasattr(order, "poke") and order.poke is not None:
            p = order.poke
            if hasattr(p, "species"):
                return f"switch:{p.species}"
            return "switch"
        # Or .pokemon
        if hasattr(order, "pokemon") and order.pokemon is not None:
            p = order.pokemon
            if hasattr(p, "species"):
                return f"switch:{p.species}"
            return "switch"
        # Direct move
        if hasattr(order, "move") and order.move is not None:
            m = order.move
            if hasattr(m, "id"):
                return str(m.id).lower()
            return str(m).lower()
        # Fallback: try to use repr to find move name
        s = str(order)
        for m in SETTER_MOVES:
            if m in s.lower():
                return m
    except Exception as e:
        pass
    return None


def _get_active_species_doubles(battle, slot):
    """For doubles, get the species of active at slot 0 or 1.

    poke-env uses battle.active_pokemon for slot 0, and we need
    a different attribute for slot 1 in doubles.
    """
    try:
        # Try active_pokemons (doubles)
        if hasattr(battle, "active_pokemons"):
            ap = battle.active_pokemons
            if ap and slot < len(ap) and ap[slot] is not None:
                return ap[slot].species
        # Try active_pokemon (singles / slot 0)
        if slot == 0 and hasattr(battle, "active_pokemon") and battle.active_pokemon is not None:
            return battle.active_pokemon.species
    except Exception:
        pass
    return "?"


def _has_setter_legal(battle, slot):
    """Check if this slot has a setter MOVE in legal orders."""
    try:
        valid = battle.valid_orders
        if not valid or slot >= len(valid):
            return False, []
        orders = valid[slot]
        if not orders:
            return False, []
        setter_in_legal = []
        for order in orders:
            mid = _move_id_from_order(order)
            if mid and mid in SETTER_MOVES:
                setter_in_legal.append(mid)
        return len(setter_in_legal) > 0, setter_in_legal
    except Exception:
        return False, []


class Wt2ProbePlayer(DoublesDamageAwarePlayer):
    """DoublesDamageAwarePlayer that records setter selections."""

    def __init__(self, *args, audit_logger=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.audit_logger = audit_logger
        self.turn_records = []

    def choose_move(self, battle):
        # Record pre-decision state
        try:
            record = {
                "battle_tag": battle.battle_tag if hasattr(battle, "battle_tag") else "?",
                "turn": battle.turn,
                "our_active_slot0_species": _get_active_species_doubles(battle, 0),
                "our_active_slot1_species": _get_active_species_doubles(battle, 1),
                "weather": _enum_keys(battle, "weather"),
                "fields": _enum_keys(battle, "fields"),
                "slot0_has_setter_legal": None,
                "slot0_setter_in_legal": [],
                "slot1_has_setter_legal": None,
                "slot1_setter_in_legal": [],
                "slot0_selected_move": None,
                "slot1_selected_move": None,
            }
            has_s0, s0 = _has_setter_legal(battle, 0)
            has_s1, s1 = _has_setter_legal(battle, 1)
            record["slot0_has_setter_legal"] = has_s0
            record["slot0_setter_in_legal"] = s0
            record["slot1_has_setter_legal"] = has_s1
            record["slot1_setter_in_legal"] = s1

            # Get the bot's choice
            order = super().choose_move(battle)

            # Record selected moves
            if order is not None:
                if hasattr(order, "first_order"):
                    record["slot0_selected_move"] = _move_id_from_order(order.first_order)
                if hasattr(order, "second_order"):
                    record["slot1_selected_move"] = _move_id_from_order(order.second_order)

            self.turn_records.append(record)
            return order
        except Exception as e:
            print(f"  choose_move error: {e}")
            return super().choose_move(battle)


def write_audit(records, output_path):
    with open(output_path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def summarize(records):
    total_turns = len(records)
    setter_legal_turns = [r for r in records if r["slot0_has_setter_legal"] or r["slot1_has_setter_legal"]]
    setter_selected_turns = []
    for r in records:
        s0 = r.get("slot0_selected_move")
        s1 = r.get("slot1_selected_move")
        if s0 and s0 in SETTER_MOVES:
            setter_selected_turns.append({
                "battle_tag": r["battle_tag"],
                "turn": r["turn"],
                "slot": 0,
                "move": s0,
                "active_species": r["our_active_slot0_species"],
            })
        if s1 and s1 in SETTER_MOVES:
            setter_selected_turns.append({
                "battle_tag": r["battle_tag"],
                "turn": r["turn"],
                "slot": 1,
                "move": s1,
                "active_species": r["our_active_slot1_species"],
            })
    return {
        "total_turns": total_turns,
        "setter_legal_turns_count": len(setter_legal_turns),
        "setter_selected_count": len(setter_selected_turns),
        "setter_selected": setter_selected_turns,
    }


async def run_battle(idx, total, audit_logger, our_team_showdown):
    suffix = str(idx) + str(int(time.time() * 1000) % 100000)[-5:]
    bot_name = f"WT2setBot_{suffix}"[:18]
    opp_name = f"WT2setOpp_{suffix}"[:18]

    bot = Wt2ProbePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        audit_logger=audit_logger,
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9doublescustomgame",
        team=our_team_showdown,
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
            print(f"  [{idx}/{total}] {elapsed:.0f}s | finished={bot.n_finished_battles}")

    battle_task = asyncio.create_task(bot.battle_against(opp, n_battles=1))
    hb_task = asyncio.create_task(heartbeat())
    try:
        await asyncio.wait_for(
            asyncio.wait({battle_task}, return_when=asyncio.FIRST_COMPLETED),
            timeout=ARM_TIMEOUT,
        )
    except asyncio.TimeoutError:
        print(f"  [{idx}] TIMEOUT")
    finally:
        hb_task.cancel()
        try:
            await bot.ps_client._stop_listening()
            await opp.ps_client._stop_listening()
        except Exception:
            pass

    elapsed = time.time() - start
    print(f"  [{idx}/{total}] Done {elapsed:.1f}s, {len(bot.turn_records)} turns")
    return bot.turn_records


async def run_probe(battles: int, output_path: str) -> Dict[str, Any]:
    if not check_localhost_healthy():
        print("ERROR: localhost:8000 not healthy")
        sys.exit(1)

    with open(OUR_TEAM_JSON) as f:
        our_team_data = json.load(f)
    our_team_showdown = json_to_showdown(our_team_data)

    all_records = []
    print(f"Running {battles} battles (WT-2 setter audit probe)...")

    for idx in range(battles):
        audit_logger = DoublesDecisionAuditLogger(
            filepath=f"logs/wt2_setter_audit_decision_{idx}.jsonl",
            reset=True,
        )
        try:
            records = await run_battle(idx + 1, battles, audit_logger, our_team_showdown)
            all_records.extend(records)
        except Exception as e:
            print(f"  Battle {idx+1} failed: {e}")

    write_audit(all_records, output_path)
    summary = summarize(all_records)
    summary["battles_attempted"] = battles
    summary["battles_succeeded"] = len(set(r["battle_tag"] for r in all_records))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--battles", type=int, default=3, help="Number of battles to run")
    parser.add_argument("--output", default="logs/wt2_setter_audit.jsonl", help="Output audit path")
    parser.add_argument("--summary", default="logs/wt2_setter_audit_summary.json", help="Summary path")
    args = parser.parse_args()

    summary = asyncio.run(run_probe(args.battles, args.output))
    with open(args.summary, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nAudit written to: {args.output}")
    print(f"Summary: {args.summary}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
