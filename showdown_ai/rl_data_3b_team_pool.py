"""Phase 7 validated local team pool.

Ponytail: pure helpers, no poke-env runtime, no network,
no I/O beyond reading local JSON files. Used by the data
expansion collection script to draw random team pairs from
the existing curated JSON pool. Do not fetch online data
from this module.

The pool is loaded from one or more local directories of
JSON team files (curated Showdown-export format). Each file
is validated fail-hard. Only ``VALID_READY_FOR_POOL`` teams
are exposed to the sampler.

The fixed matchup in
``rl_data_3b_small_local_audit.py:OPP_TEAM`` +
``OUR_TEAM_JSON`` is preserved for regression; this module
adds a separate pool mode that must be explicitly selected
via ``--team-mode pool``.
"""

import hashlib
import json
import os
import random
from typing import Any, Dict, List, Optional, Tuple

# ponytail: explicit classification strings. Mirror the
# audit-style enum in
# logs/phase7_team_pool_and_support_coverage_audit/.
VALID_READY_FOR_POOL = "VALID_READY_FOR_POOL"
INVALID_MISSING_LEVEL = "INVALID_MISSING_LEVEL"
INVALID_NON_50_LEVEL = "INVALID_NON_50_LEVEL"
INVALID_WRONG_COUNT = "INVALID_WRONG_COUNT"
INVALID_MISSING_ITEM = "INVALID_MISSING_ITEM"
INVALID_MISSING_ABILITY = "INVALID_MISSING_ABILITY"
INVALID_MISSING_NATURE = "INVALID_MISSING_NATURE"
INVALID_BAD_MOVES = "INVALID_BAD_MOVES"
INVALID_MALFORMED_JSON = "INVALID_MALFORMED_JSON"
INVALID_UNKNOWN_SCHEMA = "INVALID_UNKNOWN_SCHEMA"

# ponytail: move-id classification tables. Used for support
# coverage reporting only; not for scoring.
_PROTECT_DETECT_IDS = frozenset({
    "protect", "detect", "endure", "kingsshield", "obstruct",
    "maxguard", "silktrap", "spikyshield", "quickguard",
})
_FAKE_OUT_IDS = frozenset({"fakeout"})
_REDIRECTION_IDS = frozenset({
    "followme", "ragepowder", "spotlight",
})
_SPEED_CONTROL_IDS = frozenset({
    "tailwind", "trickroom", "icywind", "electroweb",
    "thunderwave", "glare", "nuzzle", "scaryface",
})
_PIVOT_IDS = frozenset({
    "uturn", "voltswitch", "partingshot", "batonpass",
    "teleport", "chillyreception", "flipturn",
})
_SETUP_IDS = frozenset({
    "swordsdance", "nastyplot", "dragondance", "calmmind",
    "bulkup", "quiverdance", "coil", "shiftgear",
    "shellsmash", "workup", "agility", "rockpolish",
    "flamecharge", "irondefense", "amnesia", "acidarmor",
    "barrier", "cosmicpower", "bellydrum", "clangoroussoul",
    "honeclaws", "laserfocus", "powertrick",
})
_SUPPORT_STATUS_IDS = frozenset({
    "helpinghand", "coaching", "healpulse", "willowisp",
    "taunt", "encore", "spore", "sleeppowder", "stunspore",
    "yawn", "haze", "mist", "safeguard", "aromatherapy",
    "healbell", "pollenpuff", "toxic", "poisonpowder",
    "toxicthread", "confuseray", "disable", "swagger",
    "substitute",
})
_SCREENS_IDS = frozenset({
    "reflect", "lightscreen", "auroraveil",
})
_HEALING_IDS = frozenset({
    "recover", "roost", "softboiled", "morningsun",
    "moonlight", "milkdrink", "slackoff", "healorder",
    "shoreup", "strengthsap", "leechseed", "wish",
    "lifedew", "moonlight",
})
_TERRAIN_WEATHER_IDS = frozenset({
    "raindance", "sunnyday", "sandstorm", "snowscape",
    "grassyterrain", "electricterrain", "psychicterrain",
    "mistyterrain",
})
_SPREAD_DAMAGE_IDS = frozenset({
    "rockslide", "heatwave", "earthquake", "dazzlinggleam",
    "makeitrain", "muddywater", "snarl", "boomburst",
    "hypervoice", "breakingswipe", "blizzard", "originpulse",
    "glaciate", "sludgewave", "precipiceblades",
    "diamondstorm", "clangingscales", "eruption",
    "waterspout", "incinerate", "overdrive", "surf",
    "discharge", "magnitude", "lavaplume", "bulldoze",
    "earthpower", "sludgebomb", "drainpunch",
})
_PRIORITY_MOVE_IDS = frozenset({
    "fakeout", "extremespeed", "suckerpunch", "aquajet",
    "vacuumwave", "thunderclap", "machpunch", "bulletpunch",
    "iceshard", "shadowstrike", "accelerock", "quickattack",
    "firstimpression", "trick",
})
_PRANKSTER_ABILITY_IDS = frozenset({"prankster"})


def _normalize_move_id(m: Any) -> str:
    if not isinstance(m, str):
        return ""
    return m.lower().replace(" ", "").replace("-", "").replace(
        "_", ""
    )


def classify_team_moves(team: List[Dict[str, Any]]) -> Dict[str, int]:
    """Return a per-category move-count dict for a team.

    Reporting only. Does NOT mutate scoring, support scoring,
    or any config flag.
    """
    cats = {
        "protect_detect": 0,
        "fake_out": 0,
        "redirection": 0,
        "speed_control": 0,
        "pivot": 0,
        "setup": 0,
        "support_status": 0,
        "screens": 0,
        "healing": 0,
        "terrain_weather": 0,
        "spread_damage": 0,
        "priority_moves": 0,
        "prankster_explicit": 0,
        "trick_room": 0,
    }
    for p in team or []:
        for m in (p.get("moves") or []):
            mid = _normalize_move_id(m)
            if not mid:
                continue
            if mid in _PROTECT_DETECT_IDS:
                cats["protect_detect"] += 1
            if mid in _FAKE_OUT_IDS:
                cats["fake_out"] += 1
            if mid in _REDIRECTION_IDS:
                cats["redirection"] += 1
            if mid in _SPEED_CONTROL_IDS:
                cats["speed_control"] += 1
                if mid == "trickroom":
                    cats["trick_room"] += 1
            if mid in _PIVOT_IDS:
                cats["pivot"] += 1
            if mid in _SETUP_IDS:
                cats["setup"] += 1
            if mid in _SUPPORT_STATUS_IDS:
                cats["support_status"] += 1
            if mid in _SCREENS_IDS:
                cats["screens"] += 1
            if mid in _HEALING_IDS:
                cats["healing"] += 1
            if mid in _TERRAIN_WEATHER_IDS:
                cats["terrain_weather"] += 1
            if mid in _SPREAD_DAMAGE_IDS:
                cats["spread_damage"] += 1
            if mid in _PRIORITY_MOVE_IDS:
                cats["priority_moves"] += 1
        # Prankster ability is explicit only; species is not
        # used to infer Prankster.
        abil = str(p.get("ability") or "").lower()
        if abil in _PRANKSTER_ABILITY_IDS:
            cats["prankster_explicit"] += 1
    return cats


# ponytail: per-team validator. Strict fail-hard rules.
def validate_team_dict(
    team_obj: Any, expected_level: int = 50
) -> Tuple[str, List[str]]:
    """Classify a single team.

    Returns (classification, reasons). classification is one
    of the ``VALID_READY_FOR_POOL`` or ``INVALID_*`` strings.
    ``reasons`` is a list of human-readable error strings.
    """
    if not isinstance(team_obj, dict):
        return INVALID_UNKNOWN_SCHEMA, ["team is not a dict"]
    if "team" not in team_obj or not isinstance(
        team_obj["team"], list
    ):
        return INVALID_UNKNOWN_SCHEMA, ["no 'team' list"]
    team = team_obj["team"]
    if len(team) != 6:
        return INVALID_WRONG_COUNT, [
            f"n_mons={len(team)} != 6"
        ]
    bad_moves: List[str] = []
    reasons: List[str] = []
    for i, p in enumerate(team):
        if not isinstance(p, dict):
            reasons.append(f"mon {i} not dict")
            continue
        if not p.get("species"):
            reasons.append(f"mon {i} missing species")
        if "level" not in p:
            reasons.append(f"mon {i} missing level")
        elif p["level"] != expected_level:
            reasons.append(
                f"mon {i} level {p['level']} != "
                f"{expected_level}"
            )
        if not p.get("item"):
            reasons.append(f"mon {i} missing item")
        if not p.get("ability"):
            reasons.append(f"mon {i} missing ability")
        if not p.get("nature"):
            reasons.append(f"mon {i} missing nature")
        moves = p.get("moves", [])
        if not isinstance(moves, list):
            bad_moves.append(f"mon {i} moves not list")
        elif len(moves) != 4:
            bad_moves.append(
                f"mon {i} moves count={len(moves)} != 4"
            )
        for m in moves:
            if not isinstance(m, str) or not m.strip():
                bad_moves.append(f"mon {i} bad move: {m!r}")
    if reasons:
        # Pick the first matching INVALID_* label.
        if any("missing level" in r for r in reasons):
            return INVALID_MISSING_LEVEL, reasons
        if any("level " in r and "!= 50" in r for r in reasons):
            return INVALID_NON_50_LEVEL, reasons
        if any("missing item" in r for r in reasons):
            return INVALID_MISSING_ITEM, reasons
        if any("missing ability" in r for r in reasons):
            return INVALID_MISSING_ABILITY, reasons
        if any("missing nature" in r for r in reasons):
            return INVALID_MISSING_NATURE, reasons
        return INVALID_UNKNOWN_SCHEMA, reasons
    if bad_moves:
        return INVALID_BAD_MOVES, bad_moves
    return VALID_READY_FOR_POOL, []


def _team_hash(team_obj: Dict[str, Any]) -> str:
    """Stable SHA-256 hash of the normalized team JSON."""
    norm = json.dumps(
        team_obj, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]


def _relative_team_id(pool_root: str, team_path: str) -> str:
    rel = os.path.relpath(team_path, pool_root)
    if rel.endswith(".json"):
        rel = rel[:-5]
    return rel.replace(os.sep, "/")


def load_team_pool(
    pool_dirs: List[str],
    expected_level: int = 50,
) -> Dict[str, Any]:
    """Load and validate every ``*.json`` file under the given
    pool directories.

    Returns a dict:
      - pool_dirs: input list (resolved to abs paths)
      - total: int
      - valid: int
      - invalid: int
      - invalid_by_reason: dict
      - valid_teams: list of dict with keys
          path, team_id, team_hash, team_dict, classification
      - invalid_teams: list of dict with keys
          path, classification, reasons

    Raises ``ValueError`` on a missing pool directory. Does
    not raise on invalid teams; they are reported.
    """
    if not pool_dirs:
        raise ValueError("pool_dirs is empty")
    resolved: List[str] = []
    for d in pool_dirs:
        if not os.path.isdir(d):
            raise ValueError(f"pool dir not found: {d}")
        resolved.append(os.path.abspath(d))
    valid_teams: List[Dict[str, Any]] = []
    invalid_teams: List[Dict[str, Any]] = []
    invalid_by_reason: Dict[str, int] = {}
    total = 0
    for d in resolved:
        for root, _dirs, files in os.walk(d):
            for f in sorted(files):
                if not f.endswith(".json"):
                    continue
                # ponytail: do not silently swallow HTML or
                # .txt. JSON only.
                fp = os.path.join(root, f)
                total += 1
                try:
                    with open(fp) as fh:
                        team_obj = json.load(fh)
                except Exception as e:
                    invalid_teams.append({
                        "path": fp,
                        "classification": INVALID_MALFORMED_JSON,
                        "reasons": [f"json: {e}"],
                    })
                    invalid_by_reason[INVALID_MALFORMED_JSON] = (
                        invalid_by_reason.get(
                            INVALID_MALFORMED_JSON, 0
                        ) + 1
                    )
                    continue
                cls, reasons = validate_team_dict(
                    team_obj, expected_level=expected_level
                )
                if cls == VALID_READY_FOR_POOL:
                    valid_teams.append({
                        "path": fp,
                        "team_id": _relative_team_id(d, fp),
                        "team_hash": _team_hash(team_obj),
                        "team_dict": team_obj,
                        "classification": cls,
                    })
                else:
                    invalid_teams.append({
                        "path": fp,
                        "classification": cls,
                        "reasons": reasons,
                    })
                    invalid_by_reason[cls] = (
                        invalid_by_reason.get(cls, 0) + 1
                    )
    return {
        "pool_dirs": resolved,
        "total": total,
        "valid": len(valid_teams),
        "invalid": len(invalid_teams),
        "invalid_by_reason": invalid_by_reason,
        "valid_teams": valid_teams,
        "invalid_teams": invalid_teams,
    }


def assert_pool_ready(
    pool: Dict[str, Any],
    min_valid: int = 4,
) -> None:
    """Fail-hard if the pool has fewer than ``min_valid`` teams.

    Raises ``ValueError``. Also fails if there are fewer than
    2 valid teams (sampler cannot draw a non-mirror pair).
    """
    if pool["valid"] < 2:
        raise ValueError(
            f"team pool has {pool['valid']} valid teams; "
            f"need at least 2 to draw a non-mirror pair"
        )
    if pool["valid"] < min_valid:
        raise ValueError(
            f"team pool has {pool['valid']} valid teams; "
            f"need at least {min_valid}"
        )


def sample_team_pair(
    pool: Dict[str, Any],
    seed: int,
    battle_idx: int,
    allow_mirror: bool = False,
) -> Dict[str, Any]:
    """Sample one bot team and one opponent team from a
    validated pool. Deterministic for a given (seed,
    battle_idx).

    Raises ``ValueError`` if a non-mirror pair is requested
    but the pool has only 1 valid team.

    Returns dict with:
      - bot: dict (path, team_id, team_hash, team_dict)
      - opp: dict
      - mirror: bool
      - seed, battle_idx, allow_mirror
    """
    valid = pool["valid_teams"]
    if len(valid) < 1:
        raise ValueError("empty valid team pool")
    if not allow_mirror and len(valid) < 2:
        raise ValueError(
            "non-mirror pair requested but pool has only "
            "1 valid team"
        )
    rng = random.Random()
    rng.seed(int(seed) * 1_000_003 + int(battle_idx))
    bot = rng.choice(valid)
    if allow_mirror:
        opp = rng.choice(valid)
    else:
        # Reject mirror pair by resampling up to 8 times.
        for _ in range(8):
            cand = rng.choice(valid)
            if cand["team_id"] != bot["team_id"]:
                opp = cand
                break
        else:
            # All resamples hit the same team: force a
            # different one by index.
            idx = (valid.index(bot) + 1) % len(valid)
            opp = valid[idx]
    return {
        "bot": {
            "path": bot["path"],
            "team_id": bot["team_id"],
            "team_hash": bot["team_hash"],
            "team_dict": bot["team_dict"],
        },
        "opp": {
            "path": opp["path"],
            "team_id": opp["team_id"],
            "team_hash": opp["team_hash"],
            "team_dict": opp["team_dict"],
        },
        "mirror": bot["team_id"] == opp["team_id"],
        "seed": seed,
        "battle_idx": battle_idx,
        "allow_mirror": allow_mirror,
    }


def validate_sampled_pair(pair: Dict[str, Any]) -> Dict[str, Any]:
    """Re-validate both selected teams and return per-side
    pass/fail. The validation is the same as
    ``validate_team_dict`` but operates on the inner
    ``team_dict`` already loaded.
    """
    bot_obj = pair["bot"]["team_dict"]
    opp_obj = pair["opp"]["team_dict"]
    bot_cls, bot_reasons = validate_team_dict(bot_obj)
    opp_cls, opp_reasons = validate_team_dict(opp_obj)
    return {
        "bot_team_validation_pass": bot_cls == VALID_READY_FOR_POOL,
        "bot_team_validation_class": bot_cls,
        "bot_team_validation_reasons": bot_reasons,
        "opp_team_validation_pass": opp_cls == VALID_READY_FOR_POOL,
        "opp_team_validation_class": opp_cls,
        "opp_team_validation_reasons": opp_reasons,
    }


def json_team_to_showdown(team_obj: Dict[str, Any]) -> str:
    """Convert a JSON team to Showdown text format.

    ponytail: explicit Level: 50 emitted for every mon so the
    raw protocol confirms L50, and the existing
    ``_validate_team_levels`` passes.
    """
    lines: List[str] = []
    for p in team_obj.get("team", []):
        species = p["species"]
        if p.get("item"):
            lines.append(f"{species} @ {p['item']}")
        else:
            lines.append(species)
        if p.get("ability"):
            lines.append(f"Ability: {p['ability']}")
        evs = p.get("evs", {}) or {}
        if evs:
            ev_parts = [
                f"{v} {k.upper()}"
                for k, v in evs.items()
                if v and v > 0
            ]
            if ev_parts:
                lines.append("EVs: " + " / ".join(ev_parts))
        if p.get("nature"):
            lines.append(f"{p['nature']} Nature")
        # Always emit explicit Level so the protocol and
        # validator see L50 explicitly. Even when level is
        # 100 (which should not happen for valid teams), we
        # still emit it so the rule is deterministic.
        if p.get("level") is not None:
            lines.append(f"Level: {p['level']}")
        else:
            lines.append("Level: 50")
        for move in p.get("moves", []) or []:
            lines.append(f"- {move}")
        lines.append("")
    return "\n".join(lines)


def pair_metadata_report(
    pair: Dict[str, Any],
    validation: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a per-battle metadata dict combining team
    IDs/hashes/validation and support-coverage classifications.
    """
    return {
        "bot_team_id": pair["bot"]["team_id"],
        "bot_team_hash": pair["bot"]["team_hash"],
        "bot_team_path": pair["bot"]["path"],
        "opp_team_id": pair["opp"]["team_id"],
        "opp_team_hash": pair["opp"]["team_hash"],
        "opp_team_path": pair["opp"]["path"],
        "mirror": pair["mirror"],
        "bot_team_validation_pass": validation[
            "bot_team_validation_pass"
        ],
        "opp_team_validation_pass": validation[
            "opp_team_validation_pass"
        ],
        "bot_team_support_coverage": classify_team_moves(
            pair["bot"]["team_dict"].get("team", [])
        ),
        "opp_team_support_coverage": classify_team_moves(
            pair["opp"]["team_dict"].get("team", [])
        ),
    }


def pool_summary_report(
    pool: Dict[str, Any],
    seed: int,
    n_battles: int,
    allow_mirror: bool,
) -> Dict[str, Any]:
    """Return a pool-level summary suitable for smoke reports."""
    return {
        "team_mode": "pool",
        "team_pool_dirs": pool["pool_dirs"],
        "team_pool_seed": seed,
        "team_pool_valid_count": pool["valid"],
        "team_pool_invalid_count": pool["invalid"],
        "team_pool_invalid_by_reason": pool["invalid_by_reason"],
        "team_pool_min_valid": 4,
        "allow_mirror_teams": allow_mirror,
        "sampled_team_pair_count": n_battles,
    }
