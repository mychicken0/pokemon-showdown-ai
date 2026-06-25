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

# ponytail: optional team-pool mode. Imported lazily so
# test environments without it still work; see
# ``PHASE7_TEAM_POOL_VALIDATION_AND_RANDOM_PAIR_SAMPLER_FIX``.
try:
    from rl_data_3b_team_pool import (
        load_team_pool as _tp_load_team_pool,
        assert_pool_ready as _tp_assert_pool_ready,
        sample_team_pair as _tp_sample_team_pair,
        validate_sampled_pair as _tp_validate_sampled_pair,
        json_team_to_showdown as _tp_json_team_to_showdown,
        pair_metadata_report as _tp_pair_metadata_report,
        pool_summary_report as _tp_pool_summary_report,
    )

    class _TEAM_POOL:
        load_team_pool = staticmethod(_tp_load_team_pool)
        assert_pool_ready = staticmethod(_tp_assert_pool_ready)
        sample_team_pair = staticmethod(_tp_sample_team_pair)
        validate_sampled_pair = staticmethod(_tp_validate_sampled_pair)
        json_team_to_showdown = staticmethod(_tp_json_team_to_showdown)
        pair_metadata_report = staticmethod(_tp_pair_metadata_report)
        pool_summary_report = staticmethod(_tp_pool_summary_report)
except Exception:  # pragma: no cover - defensive
    _TEAM_POOL = None

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
Level: 50
EVs: 252 HP / 252 Atk
Adamant Nature
- Fake Out
- Flare Blitz
- Knock Off
- U-turn

Tornadus @ Heavy-Duty Boots
Ability: Prankster
Level: 50
EVs: 252 HP / 252 SpA
Modest Nature
- Tailwind
- Hurricane
- Rain Dance
- Protect

Clefable @ Leftovers
Ability: Magic Guard
Level: 50
EVs: 252 HP / 252 Def
Bold Nature
- Moonblast
- Wish
- Protect
- Thunder Wave

Garchomp @ Choice Scarf
Ability: Rough Skin
Level: 50
EVs: 252 Atk / 252 Spe
Jolly Nature
- Earthquake
- Rock Slide
- Outrage
- Dragon Claw

Tyranitar @ Smooth Rock
Ability: Sand Stream
Level: 50
EVs: 252 HP / 252 Atk
Adamant Nature
- Rock Slide
- Crunch
- Stone Edge
- Protect

Volcarona @ Leftovers
Ability: Flame Body
Level: 50
EVs: 252 SpA / 252 Spe
Timid Nature
- Heat Wave
- Bug Buzz
- Quiver Dance
- Protect"""


_KNOWN_TEAMS_LIST = [
    ("OPP_TEAM", OPP_TEAM),
    ("OUR_TEAM (via json_to_showdown)", "data/curated_teams/custom/wt2_audit_team_v1.json"),
]


def _validate_team_levels(team_text: str, run_name: str = "default", expected_level: int = 50) -> None:
    """Validate that a Showdown-format team string has explicit
    Level: {expected_level} for every Pokemon.

    Raises ValueError with details if validation fails.
    Used before collection to catch missing/non-50 levels.
    """
    if expected_level <= 0 or expected_level > 100:
        raise ValueError(f"expected_level must be 1-100, got {expected_level}")
    lines = team_text.split("\n")
    sets: list = []
    current_set = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current_set is not None:
                current_set.setdefault("moves", []).append(stripped[2:])
        elif " @ " in stripped:
            if current_set is not None and "species" not in current_set:
                current_set["species"] = stripped.split(" @ ")[0]
            if current_set is not None and "species" in current_set:
                sets.append(current_set)
            current_set = {"species": stripped.split(" @ ")[0].strip(), "line": stripped}
        elif stripped.startswith("Ability:"):
            if current_set is not None:
                current_set["ability"] = stripped
        elif stripped.startswith("Level:"):
            if current_set is not None:
                try:
                    lv = int(stripped.split(":")[1].strip())
                    current_set["level"] = lv
                except ValueError:
                    raise ValueError(f"Invalid Level line in {run_name}: {stripped!r}")
        elif stripped.startswith("EVs:"):
            if current_set is not None:
                current_set["evs"] = stripped
        elif "Nature" in stripped or "Nature" in str(getattr(stripped, "lower", lambda: stripped)()):
            if current_set is not None:
                current_set["nature"] = stripped
    if current_set is not None and "species" in current_set:
        sets.append(current_set)

    errors = []
    for s in sets:
        species = s.get("species", "?")
        lv = s.get("level")
        if lv is None:
            errors.append(f"{species}: missing Level line")
        elif lv != expected_level:
            errors.append(f"{species}: Level {lv}, expected {expected_level}")

    if errors:
        msg = f"Team validation failed for {run_name} ({len(errors)} errors):\n"
        for e in errors:
            msg += f"  - {e}\n"
        raise ValueError(msg)
    # Also verify exactly 6 sets
    if len(sets) != 6:
        raise ValueError(f"Team {run_name} has {len(sets)} Pokemon, expected 6")


def _validate_all_teams(expected_level: int = 50) -> None:
    """Validate all teams used in data expansion.

    Fail-hard validator. Raises ``ValueError`` on:

    * ``OPP_TEAM`` missing ``Level:`` lines, non-50 levels, or wrong count.
    * OUR_TEAM JSON file missing, unreadable, malformed, missing ``team`` key,
      wrong Pokemon count, missing ``level`` field, or non-50 levels.

    This function never silently returns on a read/parse failure. The
    OUR_TEAM path is resolved relative to ``REPO_ROOT`` (not CWD) so the
    validator works regardless of where the script is invoked from.
    """
    import json as _json
    _validate_team_levels(OPP_TEAM, "OPP_TEAM (hardcoded)", expected_level=expected_level)
    _our_team_json_path = os.path.join(
        REPO_ROOT, "data", "curated_teams", "custom", "wt2_audit_team_v1.json"
    )
    if not os.path.isfile(_our_team_json_path):
        raise ValueError(f"OUR_TEAM JSON missing: {_our_team_json_path}")
    try:
        with open(_our_team_json_path) as _f:
            _data = _json.load(_f)
    except (OSError, ValueError) as _e:
        raise ValueError(
            f"OUR_TEAM JSON unreadable/malformed at {_our_team_json_path}: {_e}"
        ) from _e
    if not isinstance(_data, dict) or "team" not in _data:
        raise ValueError(
            f"OUR_TEAM JSON at {_our_team_json_path} missing 'team' key"
        )
    _team = _data.get("team", [])
    _errors = []
    if len(_team) != 6:
        _errors.append(f"OUR_TEAM has {len(_team)} Pokemon, expected 6")
    for _i, _p in enumerate(_team):
        _species = _p.get("species", f"pokemon_{_i}")
        _lv = _p.get("level")
        if _lv is None:
            _errors.append(f"{_species}: missing level in JSON")
        elif _lv != expected_level:
            _errors.append(f"{_species}: level {_lv}, expected {expected_level}")
    if _errors:
        raise ValueError("OUR_TEAM validation failed:\n" + "\n".join(f"  - {e}" for e in _errors))
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
    battle_meta: Optional[Dict[str, Any]] = None,
    opp_team_showdown: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a single battle with the bot vs a random opp.

    Returns a dict with battle_id, elapsed time, bot / opp
    names, and any per-battle metadata (team IDs/hashes/
    coverage from pool mode).
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
        team=opp_team_showdown if opp_team_showdown else OPP_TEAM,
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
    out = {
        "battle_idx": idx,
        "bot_name": bot_name,
        "opp_name": opp_name,
        "elapsed_s": elapsed,
        "bot_finished": bot.n_finished_battles,
    }
    if battle_meta is not None:
        out["battle_meta"] = battle_meta
    return out


async def run_smoke(
    battles: int,
    output_path: str,
    raw_protocol_dir: Optional[str] = None,
    team_mode: str = "fixed",
    team_pool_dirs: Optional[List[str]] = None,
    team_pool_seed: int = 20260702,
    team_pool_min_valid: int = 4,
    allow_mirror_teams: bool = False,
) -> Dict[str, Any]:
    """Run the small audit smoke.

    Returns a dict with battle results, audit path,
    and a one-line summary.

    If ``raw_protocol_dir`` is provided, raw Showdown
    protocol lines are written to
    ``{raw_protocol_dir}/{battle_id}.jsonl`` per battle.

    ``team_mode`` selects fixed-matchup (default, regression)
    or pool (random sampling from a local JSON team pool).
    """
    if team_mode not in ("fixed", "pool"):
        return {
            "error": (
                f"unknown team_mode {team_mode!r}; "
                f"must be 'fixed' or 'pool'"
            ),
        }
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

    # Phase 7 P0 hotfix: fail-hard team-level validation must run
    # BEFORE any team read, json_to_showdown conversion, audit logger
    # construction, raw capture wiring, or battle loop entry.
    # If validation raises, no battle can start, no collection data
    # is written, and the exception propagates cleanly.
    _validate_all_teams(expected_level=50)

    # Pool mode: load and validate the local JSON team pool
    # before any battle starts. Fail-hard on missing dir,
    # insufficient valid teams, or import error.
    pool = None
    pool_summary: Dict[str, Any] = {}
    if team_mode == "pool":
        if _TEAM_POOL is None:
            return {
                "error": (
                    "team_mode=pool requested but "
                    "rl_data_3b_team_pool could not be "
                    "imported. See PHASE7_TEAM_POOL_"
                    "VALIDATION_AND_RANDOM_PAIR_SAMPLER_FIX."
                ),
            }
        if not team_pool_dirs:
            return {
                "error": (
                    "team_mode=pool requires --team-pool-dir"
                ),
            }
        try:
            pool = _TEAM_POOL.load_team_pool(
                team_pool_dirs, expected_level=50
            )
            _TEAM_POOL.assert_pool_ready(
                pool, min_valid=team_pool_min_valid
            )
        except ValueError as e:
            return {
                "error": (
                    f"team pool validation failed: {e}"
                ),
            }
        pool_summary = _TEAM_POOL.pool_summary_report(
            pool=pool,
            seed=team_pool_seed,
            n_battles=battles,
            allow_mirror=allow_mirror_teams,
        )
        print(
            f"Pool mode: {pool['valid']} valid teams, "
            f"{pool['invalid']} invalid, "
            f"seed={team_pool_seed}, "
            f"mirror={allow_mirror_teams}",
            flush=True,
        )
        # The fixed OUR_TEAM_JSON is not used in pool mode.
        # We still load the OPP_TEAM for fallback safety, but
        # the actual sample is per-battle.
    else:
        # fixed mode: load our team once as before.
        with open(OUR_TEAM_JSON) as f:
            our_team_data = json.load(f)
        our_team_showdown = json_to_showdown(our_team_data)
        pool_summary = {
            "team_mode": "fixed",
            "team_pool_dirs": [],
            "team_pool_seed": team_pool_seed,
            "team_pool_valid_count": 1,
            "team_pool_invalid_count": 0,
            "team_pool_min_valid": 1,
            "allow_mirror_teams": allow_mirror_teams,
            "sampled_team_pair_count": battles,
        }

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
    pair_meta_records: List[Dict[str, Any]] = []
    for idx in range(1, battles + 1):
        try:
            # Pool mode: per-battle sample + validate pair.
            if team_mode == "pool":
                pair = _TEAM_POOL.sample_team_pair(
                    pool=pool,
                    seed=team_pool_seed,
                    battle_idx=idx,
                    allow_mirror=allow_mirror_teams,
                )
                validation = _TEAM_POOL.validate_sampled_pair(
                    pair
                )
                if not (
                    validation["bot_team_validation_pass"]
                    and validation["opp_team_validation_pass"]
                ):
                    return {
                        "error": (
                            f"battle {idx} sampled team failed "
                            f"validation: bot="
                            f"{validation['bot_team_validation_class']} "
                            f"opp={validation['opp_team_validation_class']}"
                        ),
                    }
                our_team_showdown = (
                    _TEAM_POOL.json_team_to_showdown(
                        pair["bot"]["team_dict"]
                    )
                )
                opp_team_showdown = (
                    _TEAM_POOL.json_team_to_showdown(
                        pair["opp"]["team_dict"]
                    )
                )
                battle_meta = _TEAM_POOL.pair_metadata_report(
                    pair=pair, validation=validation
                )
                # ponytail: ensure the emitted text has
                # explicit Level: 50 for every mon. The
                # helper always emits Level; this guard
                # rejects any drift.
                if "Level: 50" not in our_team_showdown:
                    return {
                        "error": (
                            f"battle {idx} bot team showdown "
                            f"missing explicit Level: 50"
                        ),
                    }
                if "Level: 50" not in opp_team_showdown:
                    return {
                        "error": (
                            f"battle {idx} opp team showdown "
                            f"missing explicit Level: 50"
                        ),
                    }
                pair_meta_records.append(battle_meta)
            else:
                battle_meta = None
                opp_team_showdown = None
            capture = None
            if raw_protocol_dir is not None:
                capture = RawProtocolCapture(
                    battle_id=f"battle-{idx}",
                    out_dir=raw_protocol_dir,
                )
            r = await run_single_battle(
                idx, battles, audit_logger,
                our_team_showdown,
                raw_capture=capture,
                battle_meta=battle_meta,
                opp_team_showdown=(
                    opp_team_showdown if team_mode == "pool" else None
                ),
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
        "team_pool_summary": pool_summary,
        "pair_meta_records": pair_meta_records,
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
    # ponytail: team-pool mode CLI. Default is fixed (the
    # existing regression matchup). Pool mode draws a
    # random team pair from local JSON pools each battle.
    # Pool mode is fail-hard: missing dir, missing module,
    # or fewer than --team-pool-min-valid valid teams
    # returns a clean error before any battle starts.
    parser.add_argument(
        "--team-mode",
        choices=("fixed", "pool"),
        default="fixed",
        help=(
            "fixed (default, regression-only) or pool "
            "(random sampling from --team-pool-dir)."
        ),
    )
    parser.add_argument(
        "--team-pool-dir",
        action="append",
        default=[],
        help=(
            "Local JSON team-pool directory. May be passed "
            "multiple times. Required when --team-mode pool."
        ),
    )
    parser.add_argument(
        "--team-pool-seed",
        type=int,
        default=20260702,
        help=(
            "Deterministic seed for random team pair sampling "
            "(default 20260702)."
        ),
    )
    parser.add_argument(
        "--team-pool-min-valid",
        type=int,
        default=4,
        help=(
            "Minimum number of valid teams in the pool. "
            "Pool mode fails hard if fewer are found "
            "(default 4)."
        ),
    )
    parser.add_argument(
        "--allow-mirror-teams",
        action="store_true",
        help=(
            "Allow the same team to be sampled on both sides. "
            "Default: reject mirror pairs."
        ),
    )
    parser.add_argument(
        "--team-pool-report",
        default=None,
        help=(
            "Optional path (under logs/) to write a JSON "
            "summary of the loaded pool + per-battle pair "
            "metadata. Default: not written."
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
            team_mode=args.team_mode,
            team_pool_dirs=args.team_pool_dir or None,
            team_pool_seed=args.team_pool_seed,
            team_pool_min_valid=args.team_pool_min_valid,
            allow_mirror_teams=args.allow_mirror_teams,
        )
    )
    if result.get("error"):
        print(f"ERROR: {result['error']}")
        sys.exit(1)
    # Optional pool report write.
    if args.team_pool_report:
        report_path = os.path.abspath(args.team_pool_report)
        if not report_path.startswith(
            os.path.join(REPO_ROOT, "logs")
        ):
            print(
                f"ERROR: --team-pool-report must be under "
                f"logs/ (got {report_path})"
            )
            sys.exit(1)
        if _TEAM_POOL is None:
            print(
                "ERROR: --team-pool-report requires "
                "rl_data_3b_team_pool import."
            )
            sys.exit(1)
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        # If pool was not loaded (fixed mode), build a
        # minimal report that records the mode only.
        if result.get("team_pool_summary"):
            pool_report = {
                "team_mode": result["team_pool_summary"].get(
                    "team_mode"
                ),
                "summary": result["team_pool_summary"],
                "per_battle": result.get("pair_meta_records", []),
            }
        else:
            pool_report = {
                "team_mode": "fixed",
                "summary": {
                    "team_mode": "fixed",
                    "team_pool_dirs": [],
                    "team_pool_valid_count": 1,
                    "team_pool_invalid_count": 0,
                    "sampled_team_pair_count": args.n_battles,
                },
                "per_battle": [],
            }
        with open(report_path, "w") as f:
            json.dump(pool_report, f, indent=2)
        print(f"  team pool report: {report_path}")
    print()
    print("=" * 60)
    print("RL-DATA-3b-small smoke summary")
    print("=" * 60)
    print(f"  audit path: {result['audit_path']}")
    print(f"  team mode: {args.team_mode}")
    if args.team_mode == "pool":
        s = result.get("team_pool_summary", {})
        print(
            f"  team pool: {s.get('team_pool_valid_count', 0)} "
            f"valid / {s.get('team_pool_invalid_count', 0)} invalid, "
            f"seed={s.get('team_pool_seed')}, "
            f"mirror={s.get('allow_mirror_teams')}"
        )
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
