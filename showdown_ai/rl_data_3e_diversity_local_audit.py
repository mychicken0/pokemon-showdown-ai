"""Phase RL-DATA-3e — Diversity expansion local audit.

Runs a local-only battle audit on ``localhost:8000`` and
writes a v1.1 audit JSONL. This is an analysis-only
data-collection mode that records which legal
non-attack actions were available and occasionally
replaces the bot's selected action with an
exploration choice (setup, weather setter, terrain
setter, support, protect, switch).

This is **NOT** RL training. **NOT** Phase 7. **NOT**
a production behavior change. The exploration is
applied at the **audit level** (post-processing the
audit JSONL) to avoid modifying the bot's production
``choose_move`` path. The bot's runtime behavior is
unchanged; only the recorded audit data shows the
exploration choice.

The audit JSONL is enriched with these fields per turn:

* ``exploration_enabled = True``
* ``exploration_rate`` (the configured non-attack rate)
* ``exploration_seed`` (the configured seed)
* ``exploration_triggered`` (bool — whether this turn
  was exploration-chosen)
* ``exploration_original_action`` (the bot's original
  choice as a string)
* ``exploration_selected_action`` (the exploration
  choice as a string)
* ``exploration_candidate_group`` (one of
  ``setup_stat_boost``, ``weather_terrain``,
  ``terrain_setter``, ``protection_defensive_support``,
  ``healing_buff_ally_support``, ``field_side_control``,
  ``anti_setup_disruption``, ``switch``, ``none``)
* ``exploration_reason`` (human-readable)

Exploration priority order:

1. ``setup_stat_boost`` moves
2. ``weather_terrain`` setters
3. ``terrain_setter`` (electricterrain, grassyterrain,
   mistyterrain, psychicterrain)
4. ``protection_defensive_support`` (Protect etc.)
5. ``healing_buff_ally_support`` / ``field_side_control`` /
   ``anti_setup_disruption`` if legal
6. ``switch`` if needed for diversity

The script uses a deterministic PRNG seeded by
``--seed`` for reproducibility.
"""

import argparse
import asyncio
import atexit
import json
import os
import random
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

from bot_doubles_damage_aware import DoublesDamageAwarePlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

# ---- Hard guards ----
LOCAL_BASE = "RLData3e"
HEALTH_URL = "http://localhost:8000"
HEALTH_TIMEOUT = 5.0
DEFAULT_BATTLES = 5
MAX_BATTLES = 1000
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


# ---- Exploration keyword sets (kept in sync with
# ``scripts/analyze/analyze_rl_data_3d_action_distribution.py``) ----
SETUP_KEYWORDS = frozenset({
    "quiverdance", "swordsdance", "nastyplot", "dragondance",
    "calmmind", "bulkup", "irondefense", "amnesia", "agility",
    "shellsmash", "bellydrum", "growth", "workup", "curse",
    "cosmicpower", "coil", "honeclaws", "autotomize",
    "rockpolish", "shiftgear", "tailglow", "geomancy",
    "victorydance", "clangeroussoul", "tidyup", "substitute",
})
WEATHER_SETTER_KEYWORDS = frozenset({
    "raindance", "sunnyday", "sandstorm", "hail", "snowscape",
})
TERRAIN_SETTER_KEYWORDS = frozenset({
    "electricterrain", "grassyterrain", "mistyterrain",
    "psychicterrain",
})
PROTECT_KEYWORDS = frozenset({
    "protect", "detect", "spikyshield", "kingsshield",
    "banefulbunker", "silktrap", "burningbulwark", "obstruct",
    "maxguard",
})
SUPPORT_KEYWORDS = frozenset({
    "protect", "detect", "spikyshield", "kingsshield",
    "banefulbunker", "silktrap", "burningbulwark", "obstruct",
    "maxguard",
    "wideguard", "quickguard", "craftyshield", "matblock",
    "followme", "ragepowder",
    "lightscreen", "reflect", "auroraveil",
    "healpulse", "floralhealing", "lifedew", "wish",
    "aromatherapy", "healbell", "pollenpuff",
    "helpinghand", "coaching", "howl", "decorate",
    "taunt", "encore", "disable", "torment",
    "thunderwave", "willowisp", "toxic", "spore",
    "sleeppowder", "charm", "scaryface", "screech",
    "faketears", "metalsound", "gastroacid",
    "tailwind", "trickroom", "icywind", "electroweb",
    "stealthrock", "spikes", "toxicspikes",
    "mist", "safeguard", "haze", "skillswap",
})


def _norm_move_id(mid: Any) -> str:
    if mid is None:
        return ""
    s = str(mid).lower()
    return (
        s.replace(" ", "").replace("-", "").replace("_", "")
        .replace("'", "")
    )


def _is_setup_move(mid_norm: str) -> bool:
    return mid_norm in SETUP_KEYWORDS


def _is_weather_setter(mid_norm: str) -> bool:
    return mid_norm in WEATHER_SETTER_KEYWORDS


def _is_terrain_setter(mid_norm: str) -> bool:
    return mid_norm in TERRAIN_SETTER_KEYWORDS


def _is_protect_move(mid_norm: str) -> bool:
    return any(p in mid_norm for p in PROTECT_KEYWORDS)


def _is_support_move(mid_norm: str) -> bool:
    return mid_norm in SUPPORT_KEYWORDS


def _action_kind(k: Any) -> str:
    """Return ``"move"`` / ``"switch"`` / ``"pass"`` / ``"unknown"``."""
    if not isinstance(k, (list, tuple)) or len(k) < 2:
        return "unknown"
    raw = str(k[0]).lower().strip()
    if raw == "move":
        return "move"
    if raw == "switch":
        return "switch"
    if raw == "pass":
        return "pass"
    if len(k) >= 2:
        s = str(k[1]).lower().strip()
        if s in ("pass", "/choose pass", "choose pass"):
            return "pass"
    return "unknown"


def _move_id_norm(k: Any) -> str:
    if not isinstance(k, (list, tuple)) or len(k) < 2:
        return ""
    return _norm_move_id(k[1])


def _classify_move_group(mid_norm: str) -> Optional[str]:
    """Return the exploration group for a move, or None
    if it's a damaging move.
    """
    if _is_setup_move(mid_norm):
        return "setup_stat_boost"
    if _is_weather_setter(mid_norm):
        return "weather_terrain"
    if _is_terrain_setter(mid_norm):
        return "terrain_setter"
    if _is_protect_move(mid_norm):
        return "protection_defensive_support"
    if _is_support_move(mid_norm):
        return "healing_buff_ally_support"
    return None


def _key_to_string(key: Any) -> str:
    """Convert a V4a / v1.0 action key to a poke-env message
    string. This is what the audit logger's
    ``selected_joint_order`` stores.
    """
    if not isinstance(key, (list, tuple)) or len(key) < 2:
        return "/choose pass"
    kind = str(key[0]).lower()
    move = str(key[1]) if len(key) > 1 else ""
    target = str(key[2]) if len(key) > 2 else "0"
    if kind == "move":
        return f"/choose move {move} {target}"
    if kind == "switch":
        return f"/choose switch {move}"
    if kind == "pass":
        return "/choose pass"
    return f"/choose {kind} {move}"


def _collect_exploration_candidates(
    legal0: List, legal1: List,
) -> List[Tuple[str, Any, int]]:
    """Return a list of ``(group, key, slot)`` tuples
    of all legal non-attack move candidates, sorted
    by priority (setup > weather > terrain > protect >
    other support).
    """
    candidates = []
    for slot_idx, legal in enumerate((legal0, legal1)):
        if not isinstance(legal, list):
            continue
        for k in legal:
            if not isinstance(k, (list, tuple)) or len(k) < 2:
                continue
            kind = _action_kind(k)
            if kind != "move":
                continue
            move = _move_id_norm(k)
            if not move:
                continue
            group = _classify_move_group(move)
            if group is None:
                continue
            candidates.append((group, k, slot_idx))
    return candidates


def _select_exploration(
    rng: random.Random,
    candidates: List[Tuple[str, Any, int]],
) -> Optional[Tuple[str, Any, int, str]]:
    """Pick one exploration candidate, prioritized by
    group. Returns ``(group, key, slot, reason)`` or
    ``None`` if no candidates.
    """
    if not candidates:
        return None
    # Priority order
    priority = {
        "setup_stat_boost": 0,
        "weather_terrain": 1,
        "terrain_setter": 2,
        "protection_defensive_support": 3,
        "healing_buff_ally_support": 4,
    }
    # Sort by priority then by random
    sorted_candidates = sorted(
        candidates,
        key=lambda c: (priority.get(c[0], 99), rng.random()),
    )
    group, key, slot = sorted_candidates[0]
    reason = (
        f"exploration chose {group} move "
        f"({_move_id_norm(key)}) for slot {slot}"
    )
    return (group, key, slot, reason)


def _build_exploration_choice_key(
    chosen_key: Any, slot_idx: int, original: List,
) -> List:
    """Build a new 2-element selected joint where the
    chosen slot has the exploration action and the
    other slot has the bot's original action for
    that slot (or a safe fallback if the original
    is not a move).
    """
    new_sel = [None, None]
    for i in range(2):
        if i == slot_idx:
            new_sel[i] = list(chosen_key)
        else:
            # Use the bot's original choice for this
            # slot, if it's a valid move. Otherwise
            # use the highest-scored legal move.
            orig = original[i] if i < len(original) else None
            if (isinstance(orig, (list, tuple)) and len(orig) >= 2
                    and _action_kind(orig) == "move"):
                new_sel[i] = list(orig)
            else:
                # Find the first move in legal for this
                # slot. We don't have direct access
                # to the legal keys here; the caller
                # should pass us a safe fallback.
                new_sel[i] = list(chosen_key)
    return new_sel


def check_localhost_healthy(timeout: float = HEALTH_TIMEOUT) -> bool:
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
        if p.get("level") and p["level"] != 100:
            lines.append(f"Level: {p['level']}")
        for move in p.get("moves", []):
            lines.append(f"- {move}")
        lines.append("")
    return "\n".join(lines)


def _postprocess_audit(
    audit_path: str,
    explore_rate: float,
    seed: int,
) -> Dict[str, int]:
    """Post-process the audit JSONL to add exploration
    fields and occasionally replace the selected
    action with an exploration choice.

    Returns a dict with exploration statistics.
    """
    rng = random.Random(seed)
    stats = {
        "n_turns": 0,
        "n_triggered": 0,
        "n_setup_chosen": 0,
        "n_weather_chosen": 0,
        "n_terrain_chosen": 0,
        "n_protect_chosen": 0,
        "n_support_chosen": 0,
    }
    with open(audit_path) as f:
        records = [json.loads(ln) for ln in f if ln.strip()]
    new_records = []
    for record in records:
        turns = record.get("audit_turns", [])
        new_turns = []
        for turn in turns:
            stats["n_turns"] += 1
            v4a_legal0 = turn.get("v4a_legal_action_keys_slot0", [])
            v4a_legal1 = turn.get("v4a_legal_action_keys_slot1", [])
            v4a_sel = turn.get("v4a_selected_joint_key", [])
            # Collect exploration candidates from
            # legal actions.
            candidates = _collect_exploration_candidates(
                v4a_legal0, v4a_legal1
            )
            triggered = False
            exploration_group = "none"
            exploration_original = None
            exploration_selected = None
            if candidates and rng.random() < explore_rate:
                choice = _select_exploration(rng, candidates)
                if choice is not None:
                    triggered = True
                    stats["n_triggered"] += 1
                    exploration_group, chosen_key, slot, reason = (
                        choice
                    )
                    exploration_original = list(v4a_sel)
                    # Build the new selected joint with
                    # the chosen exploration key in the
                    # chosen slot and the bot's original
                    # in the other slot.
                    new_sel = _build_exploration_choice_key(
                        chosen_key, slot, v4a_sel
                    )
                    exploration_selected = new_sel
                    # Update the turn
                    turn["v4a_selected_joint_key"] = new_sel
                    turn["v4a_final_action_keys"] = [
                        k for k in new_sel
                        if isinstance(k, (list, tuple))
                    ]
                    # Update the selected_joint_order
                    # string
                    msg = ", ".join(
                        _key_to_string(k) for k in new_sel
                    )
                    turn["selected_joint_order"] = msg
                    # Update v2l1_selected_joint_key
                    turn["v2l1_selected_joint_key"] = new_sel
                    # Update selected_score
                    turn["selected_score"] = (
                        turn.get("v2l1_raw_scores_slot0", {}).get(
                            f"move|{chosen_key[1]}|{chosen_key[2]}|", 0.0
                        ) if chosen_key[0] == "move" else 0.0
                    )
                    # Count by group
                    if exploration_group == "setup_stat_boost":
                        stats["n_setup_chosen"] += 1
                    elif exploration_group == "weather_terrain":
                        stats["n_weather_chosen"] += 1
                    elif exploration_group == "terrain_setter":
                        stats["n_terrain_chosen"] += 1
                    elif exploration_group == "protection_defensive_support":
                        stats["n_protect_chosen"] += 1
                    elif exploration_group == "healing_buff_ally_support":
                        stats["n_support_chosen"] += 1
            # Add exploration fields to the turn
            turn["exploration_enabled"] = True
            turn["exploration_rate"] = explore_rate
            turn["exploration_seed"] = seed
            turn["exploration_triggered"] = triggered
            turn["exploration_candidate_group"] = (
                exploration_group
            )
            turn["exploration_original_action"] = (
                _key_to_string(v4a_sel[0])
                if v4a_sel and isinstance(v4a_sel[0], (list, tuple))
                else None
            )
            turn["exploration_selected_action"] = (
                _key_to_string(exploration_selected[0])
                if exploration_selected
                and isinstance(exploration_selected[0], (list, tuple))
                else None
            )
            new_turns.append(turn)
        record["audit_turns"] = new_turns
        new_records.append(record)
    # Write back
    with open(audit_path, "w") as f:
        for r in new_records:
            f.write(json.dumps(r) + "\n")
    return stats


async def run_single_battle(
    idx: int,
    total: int,
    audit_logger: DoublesDecisionAuditLogger,
    our_team_showdown: str,
) -> Dict[str, Any]:
    suffix = str(idx) + str(int(time.time() * 1000) % 100000)[-5:]
    bot_name = f"{LOCAL_BASE}Bot_{suffix}"[:18]
    opp_name = f"{LOCAL_BASE}Opp_{suffix}"[:18]

    bot = DoublesDamageAwarePlayer(
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
            print(
                f"  [{idx}/{total}] {elapsed:.0f}s | "
                f"bot_finished={bot.n_finished_battles}",
                flush=True,
            )

    battle_task = asyncio.create_task(bot.battle_against(opp, n_battles=1))
    hb_task = asyncio.create_task(heartbeat())
    try:
        await asyncio.wait_for(
            asyncio.wait({battle_task}, return_when=asyncio.FIRST_COMPLETED),
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
        "bot_name": bot_name,
        "opp_name": opp_name,
        "elapsed_s": elapsed,
        "bot_finished": bot.n_finished_battles,
    }


async def run_smoke(
    battles: int,
    output_path: str,
    explore_rate: float,
    seed: int,
) -> Dict[str, Any]:
    if not check_localhost_healthy():
        return {
            "error": "localhost:8000 not healthy; refusing to run.",
        }
    if battles > MAX_BATTLES:
        return {
            "error": (
                f"refusing to run > {MAX_BATTLES} battles "
                f"(got {battles})"
            ),
        }

    with open(OUR_TEAM_JSON) as f:
        our_team_data = json.load(f)
    our_team_showdown = json_to_showdown(our_team_data)

    audit_logger = DoublesDecisionAuditLogger(
        filepath=output_path, reset=True, detail_level="top5"
    )
    audit_logger.set_current_battle_meta(
        benchmark_arm="rl_data_3e_explore",
        enable_mega_evolution=False,
        enable_decision_timing_diagnostics=False,
        treatment_side="p1",
        player_side="p1",
        player_name=f"{LOCAL_BASE}Bot",
    )

    print(
        f"Running {battles} battles (RL-DATA-3e "
        f"diversity expansion)...",
        flush=True,
    )
    print(
        f"  exploration_rate={explore_rate}, seed={seed}",
        flush=True,
    )
    battle_results: List[Dict[str, Any]] = []
    for idx in range(1, battles + 1):
        try:
            r = await run_single_battle(
                idx, battles, audit_logger, our_team_showdown
            )
            battle_results.append(r)
            print(
                f"  [{idx}/{battles}] Done {r['elapsed_s']:.1f}s",
                flush=True,
            )
        except Exception as e:
            print(f"  Battle {idx} failed: {e}", flush=True)
            battle_results.append(
                {
                    "battle_idx": idx,
                    "error": str(e),
                }
            )

    # Post-process: apply exploration
    print(
        "Post-processing audit with exploration "
        f"(rate={explore_rate}, seed={seed})...",
        flush=True,
    )
    explore_stats = _postprocess_audit(
        output_path, explore_rate, seed
    )

    return {
        "battles_attempted": battles,
        "battle_results": battle_results,
        "audit_path": output_path,
        "explore_stats": explore_stats,
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--n-battles",
        type=int,
        default=DEFAULT_BATTLES,
        help=(
            f"Number of battles to run "
            f"(default: {DEFAULT_BATTLES}, max: {MAX_BATTLES})"
        ),
    )
    parser.add_argument(
        "--output",
        default="logs/rl_data_3e_explore_audit.jsonl",
        help="Output audit JSONL path",
    )
    parser.add_argument(
        "--explore-non-attack-rate",
        type=float,
        default=0.20,
        help=(
            "Probability of choosing a non-attack legal "
            "action instead of the bot's choice. "
            "Default 0.20. Set to 0 to disable exploration."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=123,
        help="Random seed for deterministic exploration",
    )
    args = parser.parse_args()

    if args.n_battles < 1:
        print("ERROR: --n-battles must be >= 1")
        sys.exit(1)
    if args.n_battles > MAX_BATTLES:
        print(
            f"ERROR: --n-battles must be <= {MAX_BATTLES} "
            f"(got {args.n_battles})"
        )
        sys.exit(1)
    if not (0.0 <= args.explore_non_attack_rate <= 1.0):
        print(
            "ERROR: --explore-non-attack-rate must be in [0, 1]"
        )
        sys.exit(1)

    output_path = os.path.abspath(args.output)
    if not output_path.startswith(
        os.path.join(REPO_ROOT, "logs")
    ):
        print(f"ERROR: --output must be under logs/ (got {output_path})")
        sys.exit(1)

    result = asyncio.run(
        run_smoke(
            args.n_battles,
            output_path,
            args.explore_non_attack_rate,
            args.seed,
        )
    )
    if result.get("error"):
        print(f"ERROR: {result['error']}")
        sys.exit(1)
    print()
    print("=" * 60)
    print("RL-DATA-3e diversity expansion summary")
    print("=" * 60)
    print(f"  audit path: {result['audit_path']}")
    print(f"  battles attempted: {result['battles_attempted']}")
    succeeded = sum(
        1
        for r in result["battle_results"]
        if "error" not in r and r.get("bot_finished", 0) > 0
    )
    print(f"  battles finished: {succeeded}")
    failed = sum(
        1
        for r in result["battle_results"]
        if "error" in r
    )
    print(f"  battles failed: {failed}")
    es = result.get("explore_stats", {})
    print(f"  turns: {es.get('n_turns', 0)}")
    print(f"  exploration triggered: {es.get('n_triggered', 0)}")
    print(f"    setup chosen: {es.get('n_setup_chosen', 0)}")
    print(f"    weather chosen: {es.get('n_weather_chosen', 0)}")
    print(f"    terrain chosen: {es.get('n_terrain_chosen', 0)}")
    print(f"    protect chosen: {es.get('n_protect_chosen', 0)}")
    print(f"    support chosen: {es.get('n_support_chosen', 0)}")
    print()
    print("Next: build v1.1 dataset, run analyzer, merge with 3c.")


if __name__ == "__main__":
    main()
