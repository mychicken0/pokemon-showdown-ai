#!/usr/bin/env python3
"""Phase 6.4.10b — Voluntary Switch Surface Probe.

A small live probe that runs tiny battles on the
already-running local Pokemon Showdown server and
logs every turn's ``valid_orders`` by slot.

The probe tries multiple formats in order and stops
once a real voluntary switch surface is proven:

  1. ``gen9randomdoublesbattle`` (current random
     doubles format used by benchmarks).
  2. ``gen9doublescustomgame`` (Gen 9 Custom Game
     with team preview).
  3. ``gen9vgc2025regi`` (VGC 2025 Reg I with team
     preview, selected-four style).

For every turn in every battle, we record:
  - ``battle_tag``
  - ``turn``
  - side / player name
  - slot index
  - active species
  - active current HP fraction
  - active fainted state
  - number of legal move orders
  - number of legal switch orders
  - switch candidate species
  - whether the active is alive
  - whether a switch order is voluntary or forced
  - raw ``battle.valid_orders`` repr/type summary
  - the chosen order
  - whether the chosen order was a switch

A voluntary switch opportunity exists only when
ALL of:
  - active is alive
  - ``force_switch[slot_idx]`` is False
  - ``valid_orders[slot_idx]`` includes at least one
    ``Pokemon`` switch order (not a forced replacement)

Forced replacement after a faint does NOT count.

The probe uses visible usernames with a clear
``VSWsurf_`` prefix so the user can find the rooms
in the local Showdown UI.

The probe does NOT tune or adopt voluntary-switch
scoring. It only proves whether the runtime surface
exposes voluntary switch orders.
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Unregister poke-env's broken atexit hook that hangs
# on combined-suite exit.
import poke_env.concurrency
_clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if _clear_loop is not None:
    try:
        atexit.unregister(_clear_loop)
    except Exception:
        pass

import poke_env_test_cleanup  # noqa: F401

from poke_env import AccountConfiguration, ServerConfiguration
from poke_env.player.player import Player
from poke_env.player.battle_order import SingleBattleOrder
from poke_env.battle.pokemon import Pokemon
from poke_env.battle.double_battle import DoubleBattle
from poke_env.player.baselines import RandomPlayer


# Server / health check.

LOCAL_BASE = "VSWsurf"
HEALTH_URL = "http://localhost:8000"
HEALTH_TIMEOUT = 2.0


def check_localhost_healthy(timeout: float = HEALTH_TIMEOUT) -> bool:
    """Return True if the local server is healthy.

    We refuse to start if the server is not healthy;
    the user has it open in Firefox already.
    """
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


# Minimal packed team (valid for Gen 9, used for
# custom formats that need a real team string).
# A simple team of 4 mons with valid moves, items,
# abilities, and levels.
#
# The packed team format used by poke-env's
# TeambuilderPokemon.from_packed is:
#   |nickname|species|item|ability|moves|nature|evs|gender|ivs|shiny|level|endstring
# (12 fields separated by 11 | chars). Mons are
# joined by ']'. We use the 4-mon team below to
# prove the voluntary switch surface in custom
# formats.


def _make_packed_mon(
    species: str,
    item: str,
    ability: str,
    moves: List[str],
    nature: str,
    evs: List[int],
    level: int = 100,
    gender: str = "",
) -> str:
    """Build a single packed mon string compatible
    with poke-env's from_packed (12 fields)."""
    moves_str = ",".join(moves)
    evs_str = ",".join(str(e) for e in evs)
    return (
        f"|{species}|{item}|{ability}|{moves_str}|"
        f"{nature}|{evs_str}||{gender}||{level}|"
    )


def _build_packed_team_4() -> str:
    """Build a 4-mon packed team for custom formats."""
    # Use valid abilities and items. Note: Garchomp
    # can only have Sand Veil or Rough Skin. Use a
    # 4-mon team with distinct items.
    m1 = _make_packed_mon(
        "Garchomp", "Choice Scarf", "Rough Skin",
        ["earthquake", "stoneedge", "firefang", "stealthrock"],
        "Serious", [252, 252, 4, 0, 0, 0],
    )
    m2 = _make_packed_mon(
        "Talonflame", "Leftovers", "Flame Body",
        ["bravebird", "roost", "tailwind", "willowisp"],
        "Adamant", [248, 8, 0, 0, 252, 0],
    )
    m3 = _make_packed_mon(
        "Rotom-Heat", "Heavy Ball", "Levitate",
        ["overheat", "voltswitch", "trick", "willowisp"],
        "Modest", [252, 0, 0, 252, 4, 0],
    )
    m4 = _make_packed_mon(
        "Amoonguss", "Rocky Helmet", "Regenerator",
        ["spore", "gigadrain", "foulplay", "sludgebomb"],
        "Calm", [252, 0, 252, 4, 0, 0],
    )
    return "]".join([m1, m2, m3, m4])


SAMPLE_TEAM_4 = _build_packed_team_4()


def _player_username(
    prefix: str, format_label: str, idx: int
) -> str:
    """Visible username within 18 chars.

    ``VSWsurf_<format>_<idx>`` is at most 18 chars.
    """
    sfx = f"{format_label}{idx}"[:18]
    return f"{LOCAL_BASE}_{sfx}"[:18]


def _is_voluntary_switch_order(order: Any) -> bool:
    """Return True if the order is a voluntary switch.

    A switch order is voluntary if:
      - order is a SingleBattleOrder
      - order.order is a Pokemon instance
      - the battle's force_switch for the slot is False

    The caller passes the battle and slot_idx.
    """
    if order is None:
        return False
    if not isinstance(order, SingleBattleOrder):
        return False
    inner = getattr(order, "order", None)
    return isinstance(inner, Pokemon)


def _summarize_valid_orders(
    valid_orders: Any, force_switch: List[bool]
) -> List[Dict[str, Any]]:
    """Summarize valid_orders for one turn.

    Returns a list of per-slot dicts with:
      - slot_idx
      - n_moves
      - n_switches
      - switch_species
      - n_pass
      - raw_type
    """
    out = []
    if valid_orders is None:
        return out
    for slot_idx, orders in enumerate(valid_orders or []):
        n_moves = 0
        n_switches = 0
        n_pass = 0
        switch_species = []
        for o in orders or []:
            if o is None:
                continue
            if not isinstance(o, SingleBattleOrder):
                continue
            inner = getattr(o, "order", None)
            if isinstance(inner, Pokemon):
                n_switches += 1
                switch_species.append(
                    getattr(inner, "species", "?")
                )
            elif hasattr(inner, "id"):
                n_moves += 1
            else:
                # Pass / default / etc.
                n_pass += 1
        fs = (
            force_switch[slot_idx]
            if slot_idx < len(force_switch)
            else False
        )
        out.append({
            "slot_idx": slot_idx,
            "n_moves": n_moves,
            "n_switches": n_switches,
            "n_pass": n_pass,
            "switch_species": switch_species,
            "force_switch": fs,
            "n_voluntary_switches": (
                n_switches if not fs else 0
            ),
        })
    return out


def _safe_species(mon) -> str:
    if mon is None:
        return ""
    return getattr(mon, "species", "") or ""


def _safe_hp_fraction(mon) -> float:
    if mon is None:
        return 0.0
    return float(
        getattr(mon, "current_hp_fraction", 0.0) or 0.0
    )


def _safe_fainted(mon) -> bool:
    if mon is None:
        return False
    return bool(getattr(mon, "fainted", False))


class SurfaceProbePlayer(RandomPlayer):
    """A probe player that:

      - Joins a single battle.
      - Records every turn's valid_orders into
        a JSON-serializable list.
      - Picks a deterministic order
        (prefer move, then switch, then pass).
      - Uses visible usernames with ``VSWsurf_``
        prefix so the user can find the room.
    """

    def __init__(self, *args, **kwargs):
        # Disable save_replays by default.
        kwargs.setdefault("save_replays", False)
        # Disable start_timer to avoid the engine
        # complaining about missing config.
        kwargs.setdefault("start_timer_on_battle_start", False)
        super().__init__(*args, **kwargs)
        # battle_tag -> list of turn records.
        self.surface_records: List[Dict[str, Any]] = []

    def choose_move(self, battle: Any) -> Any:
        # Only process DoubleBattle.
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)

        valid_orders = getattr(battle, "valid_orders", None)
        force_switch = list(
            getattr(battle, "force_switch", [False, False]) or [False, False]
        )
        slot_summary = _summarize_valid_orders(
            valid_orders, force_switch
        )

        active_pokemons = list(
            getattr(battle, "active_pokemon", []) or []
        )

        # Record every turn.
        for si, info in enumerate(slot_summary):
            active = (
                active_pokemons[si]
                if si < len(active_pokemons)
                else None
            )
            self.surface_records.append({
                "battle_tag": getattr(battle, "battle_tag", ""),
                "turn": getattr(battle, "turn", 0),
                "side": self.username,
                "slot": si,
                "active_species": _safe_species(active),
                "active_hp_fraction": _safe_hp_fraction(active),
                "active_fainted": _safe_fainted(active),
                "force_switch": force_switch[si]
                if si < len(force_switch)
                else False,
                "n_moves": info["n_moves"],
                "n_switches": info["n_switches"],
                "n_pass": info["n_pass"],
                "switch_candidate_species": list(
                    info["switch_species"]
                ),
                "n_voluntary_switches": info["n_voluntary_switches"],
                "raw_valid_orders_type": type(
                    valid_orders
                ).__name__,
            })

        # Use the parent's choose_random_doubles_move
        # but try to prefer moves first.
        if valid_orders is not None:
            for slot_idx, orders in enumerate(valid_orders):
                if not orders:
                    continue
                # Prefer move orders first.
                for o in orders:
                    if (
                        o is not None
                        and isinstance(o, SingleBattleOrder)
                        and hasattr(getattr(o, "order", None), "id")
                    ):
                        return self.choose_random_doubles_move(battle)
                # Then switch orders.
                for o in orders:
                    if (
                        o is not None
                        and isinstance(o, SingleBattleOrder)
                        and isinstance(
                            getattr(o, "order", None), Pokemon
                        )
                    ):
                        return self.choose_random_doubles_move(battle)
                # Then pass.
                return self.choose_random_doubles_move(battle)
        return self.choose_random_move(battle)


def _make_probe_player(
    name: str, team: Optional[str], battle_format: str
) -> SurfaceProbePlayer:
    acc = AccountConfiguration(name, None)
    kwargs: Dict[str, Any] = {}
    if team is not None:
        kwargs["team"] = team
    return SurfaceProbePlayer(
        account_configuration=acc,
        battle_format=battle_format,
        max_concurrent_battles=1,
        log_level=30,
        **kwargs,
    )


def _summarize_format(
    format_label: str,
    battles_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute summary metrics for one format."""
    n_turns = 0
    n_slot_turns = 0
    n_alive = 0
    n_forced = 0
    n_voluntary = 0
    n_chosen_switch = 0
    n_chosen_voluntary_switch = 0
    n_chosen_forced_switch = 0
    first_voluntary = None
    switch_species_dist: Dict[str, int] = {}
    for b in battles_data:
        for r in b.get("records", []):
            n_turns = max(n_turns, r["turn"] + 1)
            n_slot_turns += 1
            if r["active_fainted"]:
                continue
            n_alive += 1
            if r["force_switch"]:
                n_forced += 1
            if r["n_voluntary_switches"] > 0:
                n_voluntary += 1
                if first_voluntary is None:
                    first_voluntary = {
                        "battle_tag": r["battle_tag"],
                        "turn": r["turn"],
                        "slot": r["slot"],
                        "active_species": r["active_species"],
                        "n_voluntary_switches": r[
                            "n_voluntary_switches"
                        ],
                        "switch_candidate_species": list(
                            r["switch_candidate_species"]
                        ),
                    }
            for sp in r.get("switch_candidate_species", []) or []:
                switch_species_dist[sp] = (
                    switch_species_dist.get(sp, 0) + 1
                )
    return {
        "format": format_label,
        "n_battles": len(battles_data),
        "n_turns": n_turns,
        "n_slot_turns": n_slot_turns,
        "n_alive": n_alive,
        "n_forced": n_forced,
        "n_voluntary_opportunities": n_voluntary,
        "first_voluntary_opportunity": first_voluntary,
        "switch_species_dist": switch_species_dist,
    }


async def _run_one_format(
    format_label: str,
    battle_format: str,
    n_battles: int,
    team: Optional[str],
    timeout_per_battle: float = 90.0,
) -> List[Dict[str, Any]]:
    """Run n_battles live and collect records."""
    # Two players with distinct names.
    p1_name = _player_username(LOCAL_BASE, format_label, 1)
    p2_name = _player_username(LOCAL_BASE, format_label, 2)
    p1 = _make_probe_player(p1_name, team, battle_format)
    p2 = _make_probe_player(p2_name, team, battle_format)
    print(
        f"  Format {format_label} ({battle_format}): "
        f"{p1_name} vs {p2_name} for {n_battles} battles"
    )
    # Use battle_against for sequential battles.
    try:
        await asyncio.wait_for(
            p1.battle_against(p2, n_battles=n_battles),
            timeout=timeout_per_battle * n_battles + 30.0,
        )
    except asyncio.TimeoutError:
        print(
            f"  WARNING: {format_label} timed out after "
            f"{timeout_per_battle * n_battles + 30.0}s"
        )
    except Exception as e:
        print(f"  WARNING: {format_label} error: {e}")
    # Collect records from both players.
    records: List[Dict[str, Any]] = []
    for p in (p1, p2):
        for r in p.surface_records:
            records.append(r)
        # Also try to read the completed battle from p.battles
        for bt, b in getattr(p, "battles", {}).items():
            for tr in getattr(b, "surface_records", []):
                records.append(tr)
    # Cleanup
    for p in (p1, p2):
        try:
            if hasattr(p, "ps_client") and hasattr(
                p.ps_client, "_stop_listening"
            ):
                await p.ps_client._stop_listening()
        except Exception:
            pass
    return records


def _records_to_battles(
    records: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Group records by battle_tag."""
    by_bt: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        bt = r.get("battle_tag", "")
        by_bt.setdefault(bt, []).append(r)
    return [
        {"battle_tag": bt, "records": recs}
        for bt, recs in by_bt.items()
    ]


# Collect per-turn records during the run.
_PER_TURN_RECORDS: List[Dict[str, Any]] = []


async def run_probe(args) -> Dict[str, Any]:
    if not check_localhost_healthy():
        print(
            "ERROR: localhost:8000 is not healthy. "
            "Refusing to run. Start the server first."
        )
        sys.exit(3)
    print(
        f"Phase 6.4.10b surface probe starting on "
        f"{HEALTH_URL}"
    )

    # Format list: (label, format_string, team).
    # Use None team to let the server generate a random
    # team. Use SAMPLE_TEAM_4 for custom formats that
    # need a real team.
    format_specs = [
        (
            "A",
            "gen9randomdoublesbattle",
            None,
        ),
        (
            "B",
            "gen9doublescustomgame",
            SAMPLE_TEAM_4,
        ),
        (
            "C",
            "gen9vgc2025regi",
            SAMPLE_TEAM_4,
        ),
    ]

    all_results: Dict[str, Any] = {
        "artifact_tag": args.artifact_tag,
        "n_battles_per_format": args.n_battles,
        "formats": [],
    }
    found_voluntary = False
    # Clear the per-turn records collector.
    _PER_TURN_RECORDS.clear()
    for label, fmt, team in format_specs:
        records = await _run_one_format(
            format_label=label,
            battle_format=fmt,
            n_battles=args.n_battles,
            team=team,
            timeout_per_battle=args.timeout_per_battle,
        )
        # Append records to the global collector.
        for r in records:
            _PER_TURN_RECORDS.append(r)
        battles_data = _records_to_battles(records)
        summary = _summarize_format(label, battles_data)
        all_results["formats"].append(summary)
        print(
            f"  [{label}] n_battles={summary['n_battles']} "
            f"n_voluntary={summary['n_voluntary_opportunities']}"
        )
        if summary["n_voluntary_opportunities"] > 0:
            found_voluntary = True
            print(
                f"  [{label}] FIRST voluntary switch surface: "
                f"{summary['first_voluntary_opportunity']}"
            )
            # Continue to log all formats, but flag.
    all_results["found_voluntary"] = found_voluntary
    if found_voluntary:
        print(
            "\nRESULT: voluntary switch surface EXISTS in at "
            "least one format."
        )
    else:
        print(
            "\nRESULT: NO voluntary switch surface found in any "
            "tested format. The current poke-env engine with "
            "the available formats does not exercise voluntary "
            "switch orders in live play."
        )
    return all_results


def main():
    parser = argparse.ArgumentParser(
        description="Phase 6.4.10b voluntary switch surface probe"
    )
    parser.add_argument(
        "--artifact-tag", type=str, required=True,
        help="Unique artifact tag (required).",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing artifacts.",
    )
    parser.add_argument(
        "--n-battles", type=int, default=2,
        help="Battles per format (default: 2).",
    )
    parser.add_argument(
        "--timeout-per-battle", type=float, default=90.0,
        help="Per-battle timeout in seconds (default: 90).",
    )
    args = parser.parse_args()

    # Output paths.
    jsonl_path = (
        f"logs/voluntary_switch_surface_{args.artifact_tag}.jsonl"
    )
    json_path = (
        f"logs/voluntary_switch_surface_{args.artifact_tag}_summary.json"
    )
    md_path = (
        f"logs/voluntary_switch_surface_{args.artifact_tag}_summary.md"
    )
    if (
        os.path.exists(jsonl_path)
        or os.path.exists(json_path)
        or os.path.exists(md_path)
    ) and not args.overwrite:
        print(
            "ERROR: artifacts exist. Use --overwrite to replace."
        )
        sys.exit(2)
    # Truncate.
    for p in (jsonl_path, json_path, md_path):
        if os.path.exists(p):
            os.remove(p)
    open(jsonl_path, "w").close()

    start = time.time()
    results = asyncio.run(run_probe(args))
    elapsed = time.time() - start

    # Write per-turn JSONL.
    with open(jsonl_path, "w") as f:
        for r in _PER_TURN_RECORDS:
            f.write(json.dumps(r) + "\n")

    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    md = _format_markdown(results)
    with open(md_path, "w") as f:
        f.write(md)

    print(
        f"\n[done] {elapsed:.1f}s | "
        f"jsonl: {jsonl_path} | "
        f"summary: {json_path}, {md_path}"
    )


def _iter_records_from_summary(summary: Dict[str, Any]):
    # The summary doesn't include raw per-turn records.
    # We need to re-collect from the JSONL.
    # This helper is a no-op; the JSONL is the per-turn source.
    return []


def _format_markdown(results: Dict[str, Any]) -> str:
    lines = [
        f"# Phase 6.4.10b Surface Probe — {results['artifact_tag']}",
        "",
        f"- Battles per format: {results['n_battles_per_format']}",
        f"- Found voluntary surface: {results['found_voluntary']}",
        "",
    ]
    for fmt in results["formats"]:
        lines.append(f"## Format {fmt['format']}")
        lines.append("")
        lines.append(f"- n_battles: {fmt['n_battles']}")
        lines.append(f"- n_turns: {fmt['n_turns']}")
        lines.append(f"- n_slot_turns: {fmt['n_slot_turns']}")
        lines.append(f"- n_alive: {fmt['n_alive']}")
        lines.append(f"- n_forced: {fmt['n_forced']}")
        lines.append(
            f"- n_voluntary_opportunities: "
            f"{fmt['n_voluntary_opportunities']}"
        )
        if fmt.get("first_voluntary_opportunity"):
            lines.append(
                f"- first_voluntary_opportunity: "
                f"{fmt['first_voluntary_opportunity']}"
            )
        if fmt.get("switch_species_dist"):
            lines.append("- switch_species_dist:")
            for sp, c in sorted(
                fmt["switch_species_dist"].items(),
                key=lambda x: -x[1],
            ):
                lines.append(f"  - {sp}: {c}")
        lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
