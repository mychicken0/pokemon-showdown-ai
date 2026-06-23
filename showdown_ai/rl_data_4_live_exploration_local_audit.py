"""Phase RL-DATA-4 — Real trajectory exploration collection.

This script runs a local-only battle audit on
``localhost:8000`` and collects **true trajectory
data** where the exploration action is **actually
submitted to the server** (not post-processed).

Unlike RL-DATA-3e (which post-processed the audit
JSONL after the battle), RL-DATA-4:

1. Uses a custom ``LiveExplorationDoublesDamageAwarePlayer``
   that subclasses ``DoublesDamageAwarePlayer``.
2. Overrides ``choose_move`` to call the parent's
   ``choose_move`` (which returns the normal order
   and records the audit).
3. If exploration triggers, finds a non-attack legal
   action in ``battle.valid_orders[slot_idx]`` and
   replaces the corresponding order in the joint order.
4. Calls
   ``audit_logger.update_pending_turn_with_live_exploration``
   to update the pending audit record with the
   explored order and the live_exploration fields.
5. Returns the modified joint order. The explored
   action is what the server actually receives.

The next battle state will reflect the explored action
(not the bot's normal choice). This is true trajectory
exploration, not post-processing.

This is **NOT** RL training. **NOT** Phase 7. **NOT**
production deployment. The exploration is enabled
only by an explicit CLI flag (``--enable-live-exploration``).
Default behavior is unchanged.

Hard guards:

* Only connects to ``localhost:8000``. Refuses any
  non-local server URL.
* Uses the existing ``DoublesDamageAwarePlayer`` so
  the audit logger is the same one used in production.
* Does not train, does not flip opt-in flags, does not
  change defaults.
* The explored action is always a legal action from
  ``battle.valid_orders[slot_idx]``.
* Watchdog timeouts prevent runaway battles.
* No post-processing of labels: the audit record's
  ``selected_joint_order`` and ``v4a_selected_joint_key``
  are updated at log time to the explored order.

The audit JSONL is enriched with these fields per turn
(emitted by the audit logger at log time):

* ``live_exploration_enabled``
* ``live_exploration_triggered``
* ``live_exploration_rate``
* ``live_exploration_seed``
* ``live_exploration_candidate_group``
* ``live_exploration_original_action``
* ``live_exploration_selected_action``
* ``live_exploration_submitted_action``
* ``live_exploration_reason``
* ``live_exploration_no_candidate_reason``
* ``live_exploration_action_was_legal``
* ``live_exploration_postprocess_only = False``
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
from poke_env.player.battle_order import (
    DoubleBattleOrder,
    SingleBattleOrder,
)

from bot_doubles_damage_aware import DoublesDamageAwarePlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

# ---- Hard guards ----
LOCAL_BASE = "RLData4"
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
# ``showdown_ai/rl_data_3e_diversity_local_audit.py``) ----
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


def _classify_move_group(mid_norm: str) -> Optional[str]:
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


def _order_kind(order: Any) -> str:
    """Return ``"move"`` / ``"switch"`` / ``"pass"`` / ``"unknown"``."""
    if order is None:
        return "unknown"
    inner = getattr(order, "order", None)
    if inner is None:
        return "pass"
    if hasattr(inner, "id"):
        return "move"
    if hasattr(inner, "name"):
        return "switch"
    return "unknown"


def _order_move_id_norm(order: Any) -> str:
    if order is None:
        return ""
    inner = getattr(order, "order", None)
    if inner is None:
        return ""
    if hasattr(inner, "id"):
        return _norm_move_id(inner.id)
    if hasattr(inner, "name"):
        return _norm_move_id(inner.name)
    return ""


def _collect_exploration_candidates(
    valid_orders: Any,
) -> List[Tuple[str, Any, int, str]]:
    """Return ``(group, order, slot, move)`` tuples of
    all legal non-attack move candidates.
    """
    candidates = []
    if not isinstance(valid_orders, (list, tuple)):
        return candidates
    for slot_idx, slot_orders in enumerate(valid_orders):
        if not isinstance(slot_orders, (list, tuple)):
            continue
        for order in slot_orders:
            if not isinstance(order, SingleBattleOrder):
                continue
            kind = _order_kind(order)
            if kind != "move":
                continue
            move = _order_move_id_norm(order)
            if not move:
                continue
            group = _classify_move_group(move)
            if group is None:
                continue
            candidates.append(
                (group, order, slot_idx, move)
            )
    return candidates


def _select_exploration(
    rng: random.Random,
    candidates: List[Tuple[str, Any, int, str]],
) -> Optional[Tuple[str, Any, int, str, str]]:
    """Pick one exploration candidate, prioritized by
    group. Returns ``(group, order, slot, move, reason)``
    or ``None``.
    """
    if not candidates:
        return None
    priority = {
        "setup_stat_boost": 0,
        "weather_terrain": 1,
        "terrain_setter": 2,
        "protection_defensive_support": 3,
        "healing_buff_ally_support": 4,
    }
    sorted_candidates = sorted(
        candidates,
        key=lambda c: (priority.get(c[0], 99), rng.random()),
    )
    group, order, slot, move = sorted_candidates[0]
    reason = (
        f"exploration chose {group} move ({move}) for slot {slot}"
    )
    return (group, order, slot, move, reason)


def _order_message(order: Any) -> str:
    """Return the poke-env message string for an order."""
    if order is None:
        return "/choose pass"
    try:
        return order.message
    except Exception:
        return "/choose pass"


def _build_explored_joint(
    original_joint: DoubleBattleOrder,
    slot_idx: int,
    explored_order: SingleBattleOrder,
) -> DoubleBattleOrder:
    """Build a new joint order with the explored
    action in the given slot and the original action
    in the other slot.
    """
    if not isinstance(original_joint, DoubleBattleOrder):
        return original_joint
    first = (
        explored_order
        if slot_idx == 0
        else original_joint.first_order
    )
    second = (
        explored_order
        if slot_idx == 1
        else original_joint.second_order
    )
    return DoubleBattleOrder(first_order=first, second_order=second)


def _slot_order_v4a_key(
    order: Any, target: int = 0
) -> List[Any]:
    """Build a v4a-style key for a single slot order.
    Returns a 4-element list:
    ``[kind, move_id, target_pos, mechanic]`` to match
    the v1.1 builder's expected format.
    """
    if order is None:
        return ["pass", "pass", 0, ""]
    kind = _order_kind(order)
    if kind == "move":
        inner = getattr(order, "order", None)
        mid = getattr(inner, "id", "") if inner else ""
        tgt = getattr(order, "move_target", 0) or target
        return ["move", str(mid), int(tgt), ""]
    if kind == "switch":
        inner = getattr(order, "order", None)
        name = getattr(inner, "name", "") if inner else ""
        return ["switch", str(name), 0, ""]
    return ["pass", "pass", 0, ""]


# ---- Live exploration player ----
class LiveExplorationDoublesDamageAwarePlayer(DoublesDamageAwarePlayer):
    """A ``DoublesDamageAwarePlayer`` that, when
    ``live_exploration_enabled=True``, occasionally
    replaces the selected action with a non-attack
    legal action and **actually submits it to the
    server**. The next battle state reflects the
    explored action (true trajectory).

    Default behavior is unchanged when
    ``live_exploration_enabled=False``.

    The override is non-invasive: it calls the
    parent's ``choose_move`` (which computes the best
    joint order and records the audit), then if
    exploration triggers, it updates the pending
    audit record with the explored order and the
    live_exploration fields, and returns the
    modified joint order.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Per-turn exploration state (set in choose_move)
        # Counters for the audit
        self._live_exploration_trigger_count: int = 0
        self._live_exploration_no_candidate_count: int = 0
        self._live_exploration_selected_groups: Dict[str, int] = {}

    def choose_move(self, battle):
        """Call the parent's choose_move, then if
        exploration triggers, replace the selected
        action with a non-attack legal action and
        return the modified joint order. The explored
        action is the action actually submitted to
        the server.
        """
        # Get the normal selected action
        normal_joint = super().choose_move(battle)
        # Check if exploration is enabled
        exploration_enabled = bool(
            getattr(self, "_live_exploration_enabled", False)
        )
        if not exploration_enabled or not isinstance(
            normal_joint, DoubleBattleOrder
        ):
            return normal_joint
        # Collect exploration candidates
        valid_orders = getattr(battle, "valid_orders", None)
        candidates = _collect_exploration_candidates(valid_orders)
        if not candidates:
            self._live_exploration_no_candidate_count += 1
            return normal_joint
        # Decide whether to explore
        explore_rate = float(
            getattr(self, "_live_exploration_rate", 0.20)
        )
        rng = random.Random()
        seed = int(getattr(self, "_live_exploration_seed", 123))
        battle_tag = getattr(battle, "battle_tag", "")
        # Deterministic per turn
        turn = getattr(battle, "turn", 0)
        rng.seed(
            seed * 1_000_003
            + (hash(battle_tag) & 0xFFFF_FFFF)
            + turn * 31
        )
        if rng.random() >= explore_rate:
            return normal_joint
        # Pick an exploration candidate
        choice = _select_exploration(rng, candidates)
        if choice is None:
            self._live_exploration_no_candidate_count += 1
            return normal_joint
        group, explored_order, slot, move, reason = choice
        # Build the new joint order
        new_joint = _build_explored_joint(
            normal_joint, slot, explored_order
        )
        # Update counters
        self._live_exploration_trigger_count += 1
        self._live_exploration_selected_groups[group] = (
            self._live_exploration_selected_groups.get(group, 0) + 1
        )
        # Build the v4a key for the explored joint
        new_v4a_key = [
            _slot_order_v4a_key(
                new_joint.first_order, 0
            ),
            _slot_order_v4a_key(
                new_joint.second_order, 0
            ),
        ]
        # Build the live_exploration state
        original_msg = _order_message(
            normal_joint.first_order
            if slot == 0
            else normal_joint.second_order
        )
        explored_msg = _order_message(explored_order)
        live_exploration_state = {
            "live_exploration_enabled": True,
            "live_exploration_triggered": True,
            "live_exploration_rate": explore_rate,
            "live_exploration_seed": seed,
            "live_exploration_candidate_group": group,
            "live_exploration_original_action": original_msg,
            "live_exploration_selected_action": explored_msg,
            "live_exploration_submitted_action": explored_msg,
            "live_exploration_reason": reason,
            "live_exploration_no_candidate_reason": "",
            "live_exploration_action_was_legal": True,
            "live_exploration_postprocess_only": False,
        }
        # Update the pending audit record with the
        # explored order and the live_exploration fields.
        audit_logger = getattr(self, "audit_logger", None)
        if audit_logger is not None:
            try:
                audit_logger.update_pending_turn_with_live_exploration(
                    battle_tag=battle_tag,
                    turn=turn,
                    explored_selected_joint_order=new_joint.message,
                    explored_v4a_selected_joint_key=new_v4a_key,
                    live_exploration_state=live_exploration_state,
                )
            except Exception as e:
                # Never let an audit update error break
                # the battle. The audit will be missing
                # the exploration fields, but the action
                # is still submitted.
                print(
                    f"  WARNING: failed to update pending "
                    f"turn with live exploration: {e}",
                    flush=True,
                )
        return new_joint


# ---- Script ----
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


async def run_single_battle(
    idx: int,
    total: int,
    audit_logger: DoublesDecisionAuditLogger,
    our_team_showdown: str,
    enable_live_exploration: bool,
    explore_rate: float,
    seed: int,
) -> Dict[str, Any]:
    suffix = str(idx) + str(int(time.time() * 1000) % 100000)[-5:]
    bot_name = f"{LOCAL_BASE}Bot_{suffix}"[:18]
    opp_name = f"{LOCAL_BASE}Opp_{suffix}"[:18]

    bot = LiveExplorationDoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        audit_logger=audit_logger,
        max_concurrent_battles=1,
        log_level=30,
        battle_format="gen9doublescustomgame",
        team=our_team_showdown,
    )
    # Set exploration parameters
    bot._live_exploration_enabled = enable_live_exploration
    bot._live_exploration_rate = explore_rate
    bot._live_exploration_seed = seed

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
                f"bot_finished={bot.n_finished_battles} | "
                f"explored={bot._live_exploration_trigger_count}",
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
        "live_exploration_trigger_count": (
            bot._live_exploration_trigger_count
        ),
        "live_exploration_no_candidate_count": (
            bot._live_exploration_no_candidate_count
        ),
        "live_exploration_selected_groups": dict(
            bot._live_exploration_selected_groups
        ),
    }


async def run_audit(
    battles: int,
    output_path: str,
    enable_live_exploration: bool,
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
        benchmark_arm="rl_data_4_live_explore",
        enable_mega_evolution=False,
        enable_decision_timing_diagnostics=False,
        treatment_side="p1",
        player_side="p1",
        player_name=f"{LOCAL_BASE}Bot",
    )

    print(
        f"Running {battles} battles (RL-DATA-4 "
        f"live trajectory exploration)...",
        flush=True,
    )
    print(
        f"  enable_live_exploration={enable_live_exploration}, "
        f"rate={explore_rate}, seed={seed}",
        flush=True,
    )
    battle_results: List[Dict[str, Any]] = []
    for idx in range(1, battles + 1):
        try:
            r = await run_single_battle(
                idx, battles, audit_logger, our_team_showdown,
                enable_live_exploration, explore_rate, seed,
            )
            battle_results.append(r)
            print(
                f"  [{idx}/{battles}] Done {r['elapsed_s']:.1f}s | "
                f"explored={r['live_exploration_trigger_count']}",
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

    return {
        "battles_attempted": battles,
        "battle_results": battle_results,
        "audit_path": output_path,
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
        default="logs/rl_data_4_live_explore_audit.jsonl",
        help="Output audit JSONL path",
    )
    parser.add_argument(
        "--enable-live-exploration",
        action="store_true",
        help=(
            "Enable live exploration. When enabled, the "
            "bot occasionally selects a non-attack legal "
            "action and actually submits it to the server."
        ),
    )
    parser.add_argument(
        "--explore-non-attack-rate",
        type=float,
        default=0.20,
        help=(
            "Probability of choosing a non-attack legal "
            "action. Default 0.20."
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
        run_audit(
            args.n_battles,
            output_path,
            args.enable_live_exploration,
            args.explore_non_attack_rate,
            args.seed,
        )
    )
    if result.get("error"):
        print(f"ERROR: {result['error']}")
        sys.exit(1)
    print()
    print("=" * 60)
    print("RL-DATA-4 live trajectory exploration summary")
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
    total_triggered = sum(
        r.get("live_exploration_trigger_count", 0)
        for r in result["battle_results"]
    )
    total_no_candidate = sum(
        r.get("live_exploration_no_candidate_count", 0)
        for r in result["battle_results"]
    )
    total_groups: Dict[str, int] = {}
    for r in result["battle_results"]:
        for g, c in r.get(
            "live_exploration_selected_groups", {}
        ).items():
            total_groups[g] = total_groups.get(g, 0) + c
    print(f"  live exploration triggered: {total_triggered}")
    print(f"  no-candidate count: {total_no_candidate}")
    for g, c in sorted(total_groups.items()):
        print(f"    {g}: {c}")
    print()
    print("Next: build v1.1 dataset, run analyzer, run BC dry-run.")


if __name__ == "__main__":
    main()
