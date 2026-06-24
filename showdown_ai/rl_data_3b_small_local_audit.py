#!/usr/bin/env python3
"""Phase RL-DATA-3b-small — Small real local battle audit smoke.

Runs a small (5-50 battle) audit on the already-running
local Pokemon Showdown server and writes the audit JSONL
using the real ``DoublesDecisionAuditLogger`` with the
v1.1 audit logger emission enabled (RL-DATA-3a / 3a.1 /
3a.2). Then builds a v1.1 dataset, runs the analyzer
gates, and reports metadata quality metrics.

This is a small local-only smoke, not a benchmark. The
default is 5 battles. Win rate is not the main success
metric; dataset quality and logger stability are.

Hard guards:

* Only connects to ``localhost:8000``. Refuses any
  non-local server URL.
* Uses the existing ``DoublesDamageAwarePlayer`` so
  the audit logger is the same one used in production.
* Does not train, does not flip opt-in flags, does not
  change defaults.
* Watchdog timeouts prevent runaway battles.

The bot's ``choose_move`` path calls
``_v1_1_live_move_metadata_for_audit`` to populate the
``move_metadata_map_override`` kwarg. The audit logger's
v1.1 emission then records per-candidate classification
with ``metadata_source = "order"`` (from live
``DoubleBattleOrder.order`` poke-env ``Move`` objects),
``metadata_source = "pokemon"`` (from the active mon's
``pokemon.moves``), or ``metadata_source = "fallback"``
(from the static fallback table in
``doubles_engine.move_metadata``).
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

# Make the showdown_ai/ and doubles_engine/ packages importable.
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
from rl_data_3b_raw_protocol_capture import RawProtocolCapture

# ---- Hard guards ----
# Only local server. Never default to official.
LOCAL_BASE = "RLData3b"
HEALTH_URL = "http://localhost:8000"
HEALTH_TIMEOUT = 5.0
DEFAULT_BATTLES = 5

# Opponent policy: which bot class plays the opposing side.
# Default is `damage_aware` (the same DoublesDamageAwarePlayer
# already used safely in production). `random` is the legacy
# RandomPlayer which can systematically target its own ally
# with single-target damaging moves; it is NOT safe for data
# expansion baseline scale-up and requires an explicit unsafe
# opt-in flag. See
# `logs/phase7_stage2_actual_friendly_fire_incident_audit/`
# for the root-cause analysis.
OPPONENT_POLICY_CHOICES = ("damage_aware", "random")
DEFAULT_OPPONENT_POLICY = "damage_aware"

# Module-level state set from CLI args in main(). Used by
# run_single_battle so the existing async API does not need
# new parameters threaded through.
_OPPONENT_POLICY = DEFAULT_OPPONENT_POLICY
_ALLOW_UNSAFE_RANDOM = False
# Phase RL-DATA-3c: raised from 50 to 600 to support
# the 5,000+ row dataset build. The script is still
# local-only and small (5 battles is the default
# smoke). The hard cap is just a safety guard; it
# is not a benchmark / qualification limit.
MAX_BATTLES = 600

# Watchdog timeouts. A real doubles battle typically
# takes 30-90s. We use conservative bounds for the
# 5-battle smoke.
HEARTBEAT_INTERVAL = 20
STALL_TIMEOUT = 180
ARM_TIMEOUT = 300

# Our team: a small set of random-doubles-style
# Pokemon. We use the curated WT-2 audit team because
# it has setter MOVE coverage (Politoed has Rain Dance
# without Drizzle) and a normal mixed attacker (Incineroar
# has Fake Out / Flare Blitz). This gives the v1.1
# audit a healthy mix of setter, support, and damaging
# moves.
OUR_TEAM_JSON = "data/curated_teams/custom/wt2_audit_team_v1.json"

# Opp team: a generic bulky team with no setters.
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


class RawCaptureBot(DoublesDamageAwarePlayer):
    """DoublesDamageAwarePlayer that also captures raw
    Showdown protocol lines via the optional ``raw_callback``
    kwarg. Falls back silently if the poke-env version does
    not expose ``_handle_battle_message``."""

    def __init__(self, *args, raw_callback=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._raw_callback = raw_callback

    def _handle_battle_message(self, split_messages: list) -> None:
        """Override to capture each raw message before
        passing to the superclass.

        ``split_messages`` is a ``List[List[str]]`` — a batch
        of messages, each split on ``|``.
        """
        try:
            if self._raw_callback is not None:
                for msg in split_messages:
                    raw_line = "|".join(msg)
                    self._raw_callback(raw_line)
        except Exception:
            pass
        try:
            return super()._handle_battle_message(split_messages)
        except Exception:
            return None


def make_opponent(
    policy: str,
    opp_name: str,
    team: str = OPP_TEAM,
    allow_unsafe_random: bool = False,
) -> Any:
    """Build the opponent player for collection.

    Args:
        policy: ``damage_aware`` (default, safe) or ``random``
            (unsafe for data expansion; requires
            ``allow_unsafe_random=True``).
        opp_name: Showdown username.
        team: Showdown-format team string.
        allow_unsafe_random: explicit unsafe opt-in for
            ``random`` policy.

    Returns:
        A poke-env player instance.

    Raises:
        ValueError: if ``random`` is requested without the
            explicit unsafe opt-in, or if ``policy`` is
            unknown.
    """
    if policy == "damage_aware":
        return DoublesDamageAwarePlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            max_concurrent_battles=1,
            log_level=30,
            battle_format="gen9doublescustomgame",
            team=team,
        )
    if policy == "random":
        if not allow_unsafe_random:
            raise ValueError(
                "opponent-policy=random is unsafe for data expansion "
                "baseline scale-up: RandomPlayer can systematically "
                "target its own ally with single-target damaging moves "
                "(see logs/phase7_stage2_actual_friendly_fire_incident_audit/). "
                "Pass --allow-unsafe-random-opponent to opt in for "
                "diagnostic use only."
            )
        return RandomPlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            max_concurrent_battles=1,
            log_level=30,
            battle_format="gen9doublescustomgame",
            team=team,
        )
    raise ValueError(
        f"unknown opponent policy: {policy!r}; "
        f"choose from {OPPONENT_POLICY_CHOICES}"
    )


def check_localhost_healthy(timeout: float = HEALTH_TIMEOUT) -> bool:
    """Verify the local Showdown server is healthy.

    Hard guard: refuses to run if the local server is
    not healthy. The probe never falls back to the
    official Showdown.
    """
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def json_to_showdown(team_dict: Dict[str, Any]) -> str:
    """Convert a JSON team dict to Showdown text format."""
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
    raw_capture: Optional[RawProtocolCapture] = None,
) -> Dict[str, Any]:
    """Run a single battle with the bot vs a random opp.

    Returns a dict with battle_id, elapsed time, and
    bot / opp names.
    """
    suffix = str(idx) + str(int(time.time() * 1000) % 100000)[-5:]
    bot_name = f"{LOCAL_BASE}Bot_{suffix}"[:18]
    opp_name = f"{LOCAL_BASE}Opp_{suffix}"[:18]
    battle_tag_guess = f"battle-gen9doublescustomgame-{idx}"

    raw_cb = raw_capture.feed if raw_capture is not None else None
    if raw_cb is not None:
        bot = RawCaptureBot(
            account_configuration=AccountConfiguration(bot_name, None),
            audit_logger=audit_logger,
            max_concurrent_battles=1,
            log_level=30,
            battle_format="gen9doublescustomgame",
            team=our_team_showdown,
            raw_callback=raw_cb,
        )
    else:
        bot = DoublesDamageAwarePlayer(
            account_configuration=AccountConfiguration(bot_name, None),
            audit_logger=audit_logger,
            max_concurrent_battles=1,
            log_level=30,
            battle_format="gen9doublescustomgame",
            team=our_team_showdown,
        )
    opp = make_opponent(
        _OPPONENT_POLICY,
        opp_name,
        team=OPP_TEAM,
        allow_unsafe_random=_ALLOW_UNSAFE_RANDOM,
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
    raw_protocol_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the small audit smoke.

    Returns a dict with battle results, audit path,
    and a one-line summary.

    If ``raw_protocol_dir`` is provided, raw Showdown
    protocol lines are written to
    ``{raw_protocol_dir}/{battle_id}.jsonl`` per battle.
    """
    if not check_localhost_healthy():
        return {
            "error": (
                f"localhost:8000 not healthy; "
                f"refusing to run."
            ),
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

    # The audit logger writes to ``output_path`` (one
    # line per battle record). The bot's choose_move
    # path triggers ``log_turn_decision`` which fills
    # in the v1.1 fields including
    # ``move_metadata_map``.
    audit_logger = DoublesDecisionAuditLogger(
        filepath=output_path, reset=True, detail_level="top5"
    )
    # Set battle-arm metadata so save_battle can
    # populate the persisted row's metadata. This is
    # the same call the production runner does.
    audit_logger.set_current_battle_meta(
        benchmark_arm="rl_data_3b_small",
        enable_mega_evolution=False,
        enable_decision_timing_diagnostics=False,
        treatment_side="p1",
        player_side="p1",
        player_name=f"{LOCAL_BASE}Bot",
    )

    print(
        f"Running {battles} battles (RL-DATA-3b-small "
        f"local audit smoke)...",
        flush=True,
    )
    if raw_protocol_dir is not None:
        print(
            f"  raw protocol capture enabled: {raw_protocol_dir}",
            flush=True,
        )
    battle_results: List[Dict[str, Any]] = []
    for idx in range(1, battles + 1):
        try:
            capture = None
            if raw_protocol_dir is not None:
                capture = RawProtocolCapture(
                    battle_id=f"battle-{idx}",
                    out_dir=raw_protocol_dir,
                )
            r = await run_single_battle(
                idx, battles, audit_logger, our_team_showdown,
                raw_capture=capture,
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

    return {
        "battles_attempted": battles,
        "battle_results": battle_results,
        "audit_path": output_path,
        "raw_protocol_dir": raw_protocol_dir,
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
        default="logs/rl_data_3b_small_audit.jsonl",
        help="Output audit JSONL path",
    )
    parser.add_argument(
        "--opponent-policy",
        choices=OPPONENT_POLICY_CHOICES,
        default=DEFAULT_OPPONENT_POLICY,
        help=(
            "Opponent policy for collection. Default "
            f"{DEFAULT_OPPONENT_POLICY!r} uses the same "
            "DoublesDamageAwarePlayer as the bot side, which "
            "is safe for data expansion. 'random' uses "
            "poke_env RandomPlayer which can systematically "
            "target its own ally with single-target damaging "
            "moves and is NOT safe for data expansion "
            "baseline scale-up. 'random' requires the "
            "--allow-unsafe-random-opponent flag for "
            "diagnostic use only."
        ),
    )
    parser.add_argument(
        "--allow-unsafe-random-opponent",
        action="store_true",
        dest="allow_unsafe_random",
        help=(
            "Required to use --opponent-policy random. This "
            "is the only way to opt into the unsafe random "
            "opponent. Diagnostic use only; never use for "
            "data expansion baseline scale-up."
        ),
    )
    parser.add_argument(
        "--raw-protocol-dir",
        default=None,
        help=(
            "If set, raw Showdown protocol lines are written "
            "to this directory as {battle_id}.jsonl. Required "
            "for the friendly-fire monitor v2 to definitively "
            "classify suspected events. Default: disabled. "
            "Directory must be under logs/."
        ),
    )
    args = parser.parse_args()

    if args.opponent_policy == "random" and not args.allow_unsafe_random:
        print(
            "ERROR: --opponent-policy random requires "
            "--allow-unsafe-random-opponent. RandomPlayer "
            "is unsafe for data expansion (it can target "
            "its own ally with single-target damaging moves). "
            "Use the default 'damage_aware' policy for "
            "data expansion baseline scale-up."
        )
        sys.exit(2)

    # Set module-level state used by run_single_battle.
    global _OPPONENT_POLICY, _ALLOW_UNSAFE_RANDOM
    _OPPONENT_POLICY = args.opponent_policy
    _ALLOW_UNSAFE_RANDOM = args.allow_unsafe_random

    if args.n_battles < 1:
        print("ERROR: --n-battles must be >= 1")
        sys.exit(1)
    if args.n_battles > MAX_BATTLES:
        print(
            f"ERROR: --n-battles must be <= {MAX_BATTLES} "
            f"(got {args.n_battles})"
        )
        sys.exit(1)

    # Hard guard: refuse to write to a non-logs path.
    output_path = os.path.abspath(args.output)
    if not output_path.startswith(
        os.path.join(REPO_ROOT, "logs")
    ):
        print(
            f"ERROR: --output must be under logs/ "
            f"(got {output_path})"
        )
        sys.exit(1)

    raw_protocol_dir = None
    if args.raw_protocol_dir:
        raw_dir_abs = os.path.abspath(args.raw_protocol_dir)
        if not raw_dir_abs.startswith(
            os.path.join(REPO_ROOT, "logs")
        ):
            print(
                f"ERROR: --raw-protocol-dir must be under "
                f"logs/ (got {raw_dir_abs})"
            )
            sys.exit(1)
        raw_protocol_dir = raw_dir_abs

    result = asyncio.run(
        run_smoke(
            args.n_battles,
            output_path,
            raw_protocol_dir=raw_protocol_dir,
        )
    )
    if result.get("error"):
        print(f"ERROR: {result['error']}")
        sys.exit(1)
    print()
    print("=" * 60)
    print("RL-DATA-3b-small smoke summary")
    print("=" * 60)
    print(f"  audit path: {result['audit_path']}")
    print(f"  opponent policy: {_OPPONENT_POLICY}")
    if _OPPONENT_POLICY == "random":
        print("  WARNING: unsafe random opponent is in use; do not")
        print("           use this dataset for baseline training.")
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
    print()
    print("Next: build v1.1 dataset and run analyzer gates.")


if __name__ == "__main__":
    main()
