"""Phase 7 friendly-fire monitor v2.

Ponytail: pure helpers. No poke-env runtime, no network,
no I/O beyond JSON file writes. Imports are minimal.

This module consumes:
  - raw Showdown protocol lines (per-battle JSONL)
  - audit JSONL with state_snapshot / v4a_selected_joint_key

It produces:
  - a MonitorV2 summary dict (machine-readable)
  - per-event classification JSONL

Classification rules (see audit requirements doc):
  ACTUAL_SINGLE_TARGET_FRIENDLY_FIRE
  FALSE_POSITIVE_SPREAD_DAMAGE
  FALSE_POSITIVE_WEATHER_CHIP
  FALSE_POSITIVE_STATUS_CHIP
  FALSE_POSITIVE_HAZARD_DAMAGE
  FALSE_POSITIVE_RECOIL
  FALSE_POSITIVE_ITEM_DAMAGE
  FALSE_POSITIVE_ABILITY_DAMAGE
  FALSE_POSITIVE_END_OF_TURN_CHIP
  FALSE_POSITIVE_TARGET_LABEL_NOISE_NO_DAMAGE
  UNKNOWN_NEEDS_RAW_PROTOCOL
  UNKNOWN_UNSUPPORTED_PROTOCOL_PATTERN
  NOT_FRIENDLY_FIRE
"""

from typing import Optional

# Canonical spread-move set. Use the move ID lowercase.
SPREAD_MOVE_IDS = frozenset({
    "earthquake", "surf", "discharge", "heatwave", "lavaplume",
    "eruption", "waterspout", "dazzlinggleam", "magnitude",
    "bulldoze", "explosion", "selfdestruct", "muddywater",
    "sludgewave", "diamondstorm", "rockslide", "rocklide",
    "icywind", "snarl", "incinerate", "hypervoice", "boomburst",
    "overdrive", "clangingscales", "precipiceblades", "originpulse",
    "glaciate",
})

# Status move indicators
STATUS_FROM_TOKENS = frozenset({"brn", "psn", "tox", "frz", "par"})

# Weather chip sources
WEATHER_CHIP_TOKENS = frozenset({"Sandstorm", "Hail", "Snow"})

# Recoil move indicators
RECOIL_MOVES = frozenset({
    "flareblitz", "bravebird", "volttackle", "doubleedge",
    "takedown", "submission", "headsmash", "wildcharge",
    "woodhammer", "headcharger", "explosion", "selfdestruct",
    "clanger", "mindblown", "shadowend", "wavecrash",
    "pkbuster", "chloroblast", "torchsong", "barbbarrage",
    "makeitrain", "armorcannon", "dragondarts",
})

# Item damage sources
ITEM_DAMAGE_TOKENS = frozenset({
    "Life Orb", "Rocky Helmet",
})

# Ability damage sources
ABILITY_DAMAGE_TOKENS = frozenset({
    "Rough Skin", "Iron Barbs", "Aftermath",
})

# Hazard sources
HAZARD_DAMAGE_TOKENS = frozenset({
    "Stealth Rock", "Spikes", "Toxic Spikes",
})


def classify_damage_event_from_protocol(
    actor_side: str,
    actor_id: str,
    move_id: str,
    target_side: str,
    target_id: str,
    from_token: str = "",
    move_target_token: str = "",
    raw_line: str = "",
    confirmed_damage: bool = False,
) -> str:
    """Classify a single damage event using parsed protocol fields.

    Args:
        actor_side: ``p1`` or ``p2``.
        actor_id: e.g., ``p1a: Volcarona``.
        move_id: lowercase move id, e.g., ``bugbuzz``.
        target_side: ``p1`` or ``p2``.
        target_id: e.g., ``p1b: Tornadus``.
        from_token: parsed ``[from]`` field, e.g., ``Sandstorm``.
        move_target_token: parsed target field if present.
        raw_line: original protocol line for evidence.
        confirmed_damage: if True, a subsequent ``|-damage|`` line
            confirms actual HP loss on the target from this move.
            Default False means the move had a same-side target
            but no HP loss was confirmed (submitted-target noise).

    Returns:
        classification string
    """
    same_side = actor_side == target_side
    from_lc = (from_token or "").lower()
    move_lc = (move_id or "").lower()

    # Chip / indirect damage sources (not actual friendly-fire)
    if from_token in WEATHER_CHIP_TOKENS:
        return "FALSE_POSITIVE_WEATHER_CHIP"
    if from_lc in {t.lower() for t in STATUS_FROM_TOKENS}:
        return "FALSE_POSITIVE_STATUS_CHIP"
    if from_token in HAZARD_DAMAGE_TOKENS:
        return "FALSE_POSITIVE_HAZARD_DAMAGE"
    if from_token in ITEM_DAMAGE_TOKENS or "item" in from_lc:
        return "FALSE_POSITIVE_ITEM_DAMAGE"
    if from_token in ABILITY_DAMAGE_TOKENS or "ability" in from_lc:
        return "FALSE_POSITIVE_ABILITY_DAMAGE"
    if from_token in RECOIL_MOVES or "recoil" in from_lc:
        return "FALSE_POSITIVE_RECOIL"

    # Spread moves (always hit all adjacent slots including ally)
    if move_lc in SPREAD_MOVE_IDS:
        return "FALSE_POSITIVE_SPREAD_DAMAGE"

    # Recoil moves (deduced from move id when [from] is absent)
    if move_lc in RECOIL_MOVES and same_side:
        return "FALSE_POSITIVE_RECOIL"

    # Same-side single-target damaging move.
    if same_side:
        if move_lc and not _is_status_move(move_lc):
            if confirmed_damage:
                return "CONFIRMED_ACTUAL_SINGLE_TARGET_FRIENDLY_FIRE"
            else:
                return "SUBMITTED_TARGET_NOISE_NO_CONFIRMED_DAMAGE"
        # Status/support move targeting self or ally is not FF
        return "NOT_FRIENDLY_FIRE"

    # Different side: normal opponent-targeting move
    if not same_side:
        return "NOT_FRIENDLY_FIRE"

    return "UNKNOWN_UNSUPPORTED_PROTOCOL_PATTERN"


_STATUS_MOVE_HINTS = frozenset({
    "protect", "detect", "kingsshield", "obstruct",
    "banefulbunker", "spikyshield",
    "tailwind", "sunnyday", "raindance", "sandstorm",
    "hail", "snowscape", "electricterrain", "grassyterrain",
    "mistyterrain", "psychicterrain", "trickroom",
    "lightscreen", "reflect", "auroraveil",
    "spikes", "toxicspikes", "stealthrock", "stickyweb",
    "taunt", "encore", "torment", "disable",
    "willowisp", "thunderwave", "toxic", "spore",
    "sleeppowder", "yawn", "confuseray", "swagger",
    "substitute", "quiverdance", "swordsdance", "nastyplot",
    "dragondance", "agility", "bulkup", "calmmind",
    "growth", "coil", "curse", "recover", "roost",
    "synthesis", "moonlight", "morningsun", "wish",
    "leechseed", "healpulse", "floralhealing", "decorate",
    "coaching", "pollenpuff", "lifedew", "followme",
    "ragepowder", "healbell", "aromatherapy",
    "batonpass", "uturn", "voltswitch", "flipturn",
    "haze", "clearsmog", "defog", "rapidspin",
    "fakeout", "hypnosis", "thundercage",
})


def _is_status_move(move_lc: str) -> bool:
    if move_lc in _STATUS_MOVE_HINTS:
        return True
    return False


def parse_protocol_line(line: str):
    """Best-effort parser for Showdown protocol battle lines.

    Returns a dict with parsed fields. Not all lines can be
    parsed; unparseable lines return ``{"raw": line, "kind": "unknown"}``.

    The parser focuses on the events that matter for the
    friendly-fire monitor:
      - ``|move|`` -> actor + move + target
      - ``|-damage|`` -> target + amount + from_token
      - ``|-heal|`` -> target + amount
      - ``|-status|`` -> target + status + from_token
      - ``|-weather|`` -> weather + from_token
      - ``|-fieldstart|`` -> field + from_token
      - ``|-sidecondition|`` -> side + condition + from_token
      - ``|turn|`` -> turn number
    """
    raw = line.rstrip("\n")
    if not raw.startswith("|"):
        return {"raw": raw, "kind": "unknown"}
    # Split on '|' and keep the leading empty so positions
    # align with the protocol (|kind|...) e.g. parts[1] is
    # the kind token. Drop the empty first element but keep
    # the rest.
    parts = raw.split("|")
    # parts[0] is "" (before the first |)
    # parts[1] is the kind
    if len(parts) < 2:
        return {"raw": raw, "kind": "unknown"}
    kind = parts[1]
    out = {"raw": raw, "kind": kind}
    # extras are parts[2:]; tokens inside [...] are flags
    rest = parts[2:]
    # A flag starts with '['. Some flags have a closing ']'
    # but others (like "[from] Sandstorm") don't. Use a
    # prefix match.
    flags = [t for t in rest if t.startswith("[")]
    try:
        if kind == "move" and len(rest) >= 3:
            out.update({
                "actor_id": rest[0].strip(),
                "move_id": rest[1].strip(),
                "target_id": rest[2].strip(),
            })
            if flags:
                out["flags"] = flags
        elif kind == "-damage" and len(rest) >= 2:
            out.update({
                "target_id": rest[0].strip(),
                "amount": rest[1].strip(),
            })
            if flags:
                out["flags"] = flags
                from_tok = _extract_from_token(flags[0])
                if from_tok:
                    out["from_token"] = from_tok
        elif kind == "-heal" and len(rest) >= 2:
            out.update({
                "target_id": rest[0].strip(),
                "amount": rest[1].strip(),
            })
            if flags:
                out["flags"] = flags
        elif kind == "-status" and len(rest) >= 2:
            out.update({
                "target_id": rest[0].strip(),
                "status": rest[1].strip(),
            })
            if flags:
                out["flags"] = flags
                from_tok = _extract_from_token(flags[0])
                if from_tok:
                    out["from_token"] = from_tok
        elif kind == "-weather" and len(rest) >= 1:
            out.update({"weather": rest[0].strip()})
            if flags:
                out["flags"] = flags
                from_tok = _extract_from_token(flags[0])
                if from_tok:
                    out["from_token"] = from_tok
        elif kind == "-fieldstart" and len(rest) >= 1:
            out.update({"field": rest[0].strip()})
            if flags:
                out["flags"] = flags
                from_tok = _extract_from_token(flags[0])
                if from_tok:
                    out["from_token"] = from_tok
        elif kind == "-sidecondition" and len(rest) >= 2:
            out.update({
                "side": rest[0].strip(),
                "condition": rest[1].strip(),
            })
            if flags:
                out["flags"] = flags
                from_tok = _extract_from_token(flags[0])
                if from_tok:
                    out["from_token"] = from_tok
        elif kind == "turn" and len(rest) >= 1:
            out.update({"turn": rest[0].strip()})
    except Exception:
        out["parse_error"] = True
    return out


def _extract_from_token(flag: str) -> str:
    """Extract the value of a ``[from] FLAG`` token.

    Examples:
        ``[from] Sandstorm`` -> ``Sandstorm``
        ``[from] item: Life Orb`` -> ``Life Orb``
        ``[from] brn`` -> ``brn``
        ``[Spread]`` -> ``Spread`` (treated as a tag, not a [from])

    For tags like ``[Spread]`` or ``[Flinch]`` that have no
    space-separated value, the function returns the empty
    string. The caller decides what to do with empty.
    """
    if not flag.startswith("["):
        return ""
    s = flag[1:]
    # If the tag itself has a "]" then it's a key-only tag
    if s.endswith("]"):
        inner = s[:-1]
        # Tags like [Spread] are key-only; [from] is special
        if inner.lower() == "from":
            return ""
        return inner
    # [from] VALUE format: after the "]" comes a space, then
    # the value. Find the first "]".
    if s.lower().startswith("from"):
        idx = s.find("]")
        if idx >= 0:
            return s[idx + 1:].strip()
        return s[4:].strip()
    # Unknown format
    return s.strip() or ""


def side_from_actor_id(actor_id: str) -> str:
    """Return ``p1`` or ``p2`` from a Showdown actor id like
    ``p1a: Volcarona``. Empty / unknown -> ``?``."""
    if not actor_id:
        return "?"
    a = actor_id.strip()
    if a.startswith("p1"):
        return "p1"
    if a.startswith("p2"):
        return "p2"
    return "?"


def get_required_summary_fields() -> list:
    """Return the list of summary fields required by the
    future run summary, per the audit spec."""
    return [
        "opponent_confirmed_actual_friendly_fire_count",
        "opponent_confirmed_actual_friendly_fire_battles",
        "bot_confirmed_actual_friendly_fire_count",
        "bot_confirmed_actual_friendly_fire_battles",
        "submitted_same_side_target_count",
        "bot_submitted_negative_target_count",
        "opponent_submitted_negative_target_count",
        "bot_selected_negative_target_rate",
        "false_positive_spread_damage_count",
        "false_positive_weather_chip_count",
        "false_positive_status_chip_count",
        "false_positive_hazard_damage_count",
        "false_positive_recoil_count",
        "false_positive_item_or_ability_damage_count",
        "false_positive_end_of_turn_chip_count",
        "unknown_friendly_fire_suspect_count",
        "raw_protocol_logs_present",
        "friendly_fire_monitor_version",
    ]


def make_empty_summary(raw_protocol_logs_present: bool = False) -> dict:
    """Return a summary dict with all required fields, default 0/False.

    ``opponent_actual_friendly_fire_count`` is kept as a
    backward-compatible alias for ``opponent_confirmed_actual_friendly_fire_count``.
    The gate uses the confirmed-only fields; submitted-target noise
    does NOT increment the confirmed count.
    """
    out = {
        # Confirmed actual damage (only incremented when HP loss is confirmed)
        "opponent_confirmed_actual_friendly_fire_count": 0,
        "opponent_confirmed_actual_friendly_fire_battles": 0,
        "bot_confirmed_actual_friendly_fire_count": 0,
        "bot_confirmed_actual_friendly_fire_battles": 0,
        # Submitted-target noise (reported separately, does NOT fail gate)
        "submitted_same_side_target_count": 0,
        "bot_submitted_negative_target_count": 0,
        "opponent_submitted_negative_target_count": 0,
        "bot_selected_negative_target_rate": 0.0,
        # False positives by cause
        "false_positive_spread_damage_count": 0,
        "false_positive_weather_chip_count": 0,
        "false_positive_status_chip_count": 0,
        "false_positive_hazard_damage_count": 0,
        "false_positive_recoil_count": 0,
        "false_positive_item_or_ability_damage_count": 0,
        "false_positive_end_of_turn_chip_count": 0,
        # Unknown (fail gate)
        "unknown_friendly_fire_suspect_count": 0,
        # Metadata
        "raw_protocol_logs_present": bool(raw_protocol_logs_present),
        "friendly_fire_monitor_version": "v3_confirmed_damage",
    }
    return out


def stage2_gate_passes(summary: dict) -> bool:
    """Apply the post-fix Stage 2 hard gate.

    Fails if:
      - raw_protocol_logs_present is False
      - opponent_confirmed_actual_friendly_fire_count > 0
      - bot_confirmed_actual_friendly_fire_count > 0
      - unknown_friendly_fire_suspect_count > 0
      - priority_terrain_block_count > 0 (P0 policy gap)
      - prankster_psychic_terrain_block_count > 0 (Prankster gap)
      - unknown_prankster_psychic_terrain_suspect_count > 0
        (suspicious Prankster pattern with no ability evidence)
      - protect_policy_bug_count > 0 (Protect spam P0 gap)
      - repeated_protect_fail_count > 0
      - max_consecutive_protect_streak > 8
      - no_effect_policy_bug_count > 0 (no-effect / immunity
        attack policy gap; PHASE7_PRODUCTION_HARD_BLOCK_*
        investigation)
      - repeated_no_effect_move_count > 0

    Does NOT fail for submitted_same_side_target_count > 0.
    """
    if not summary.get("raw_protocol_logs_present"):
        return False
    if summary.get("opponent_confirmed_actual_friendly_fire_count", 0) > 0:
        return False
    if summary.get("bot_confirmed_actual_friendly_fire_count", 0) > 0:
        return False
    if summary.get("unknown_friendly_fire_suspect_count", 0) > 0:
        return False
    if summary.get("priority_terrain_block_count", 0) > 0:
        return False
    if summary.get("prankster_psychic_terrain_block_count", 0) > 0:
        return False
    if summary.get("unknown_prankster_psychic_terrain_suspect_count", 0) > 0:
        return False
    if summary.get("protect_policy_bug_count", 0) > 0:
        return False
    if summary.get("repeated_protect_fail_count", 0) > 0:
        return False
    if summary.get("max_consecutive_protect_streak", 0) > 8:
        return False
    if summary.get("no_effect_policy_bug_count", 0) > 0:
        return False
    if summary.get("repeated_no_effect_move_count", 0) > 0:
        return False
    return True


# ponytail: Protect-spam raw protocol parser. Independent of
# poke-env. Walks every ``*.jsonl`` battle file in ``raw_dir``
# and emits per-event records + summary counters.
def parse_protect_spam_from_raw_protocol(raw_dir: str) -> dict:
    """Walk ``raw_dir`` for ``*.jsonl`` battle files and
    detect repeated low-value Protect usage.

    Detection rule (per battle, per actor):

      - Track the most recent ``|turn|N`` so the parser can
        increment the per-(battle, actor) consecutive
        Protect streak.
      - A ``|move|<actor>|Protect|...|`` line is a Protect
        attempt. Increment the actor's streak if the actor
        was the previous Protect actor in the immediately
        prior turn; otherwise reset streak to 1.
      - A ``|-fail|`` line in the same turn as the actor's
        most recent Protect attempt marks the attempt as
        failed. The first fail is NOT a repeated-fail; the
        second and subsequent consecutive fails are.
        A non-fail event between Protect moves resets the
        fail counter.
      - A ``|switch|`` line for the same actor resets the
        streak (new active pokemon).

    Returns dict with these fields:
      - protect_move_count
      - protect_success_count
      - protect_fail_count
      - consecutive_protect_attempt_count (>=2 streaks)
      - max_consecutive_protect_streak
      - repeated_protect_fail_count
      - protect_policy_bug_count (3+ streaks; or any
        repeated failed Protect)
      - protect_spam_gate_pass
      - protect_spam_battles
      - events (list of per-(battle, actor) policy-bug dicts)
    """
    import glob as _glob
    import os as _os
    out = {
        "protect_move_count": 0,
        "protect_success_count": 0,
        "protect_fail_count": 0,
        "consecutive_protect_attempt_count": 0,
        "max_consecutive_protect_streak": 0,
        "repeated_protect_fail_count": 0,
        "protect_policy_bug_count": 0,
        "protect_spam_gate_pass": True,
        "protect_spam_battles": 0,
        "events": [],
    }
    if not raw_dir or not _os.path.isdir(raw_dir):
        return out
    spam_battles = set()
    for fp in sorted(_glob.glob(_os.path.join(raw_dir, "*.jsonl"))):
        bname = _os.path.basename(fp)
        # Per-(battle, actor) state.
        streak = 0
        last_turn = -1
        last_actor = None
        # Track whether the most recent Protect attempt
        # for ``last_actor`` failed. Reset on any new Protect
        # attempt or any non-Protect move by the same actor.
        last_failed = False
        max_streak_local = 0
        try:
            with open(fp) as f:
                for ln in f:
                    try:
                        rec = __import__("json").loads(ln)
                    except Exception:
                        continue
                    line = rec.get("line", "")
                    if line.startswith("|turn|"):
                        try:
                            t = int(line.split("|")[2])
                        except Exception:
                            t = 0
                        if last_turn >= 0 and t - last_turn > 1:
                            # Streak broken by inactive turns.
                            streak = 0
                            last_failed = False
                        last_turn = t
                        continue
                    if line.startswith("|switch|"):
                        parts = line.split("|")
                        if len(parts) >= 3 and parts[2] == last_actor:
                            streak = 0
                            last_failed = False
                        continue
                    if line.startswith("|move|"):
                        parts = line.split("|")
                        if len(parts) < 5:
                            continue
                        actor = parts[2]
                        move_id = parts[3].lower().replace(" ", "").replace("'", "").replace("-", "")
                        if move_id not in {
                            "protect", "detect", "spikyshield",
                            "kingsshield", "obstruct", "maxguard",
                            "silktrap", "banefulbunker",
                            "burningbulwark",
                        }:
                            # Any non-Protect move by the same
                            # actor resets the streak and the
                            # fail counter.
                            if actor == last_actor:
                                streak = 0
                                last_failed = False
                            continue
                        out["protect_move_count"] += 1
                        if actor == last_actor and streak >= 1:
                            streak += 1
                        else:
                            streak = 1
                        last_actor = actor
                        # New Protect attempt: reset the
                        # per-attempt fail flag for this actor.
                        last_failed = False
                        if streak >= 2:
                            out["consecutive_protect_attempt_count"] += 1
                        if streak >= 3:
                            out["protect_policy_bug_count"] += 1
                            spam_battles.add(bname)
                            out["events"].append({
                                "battle": bname,
                                "actor": actor,
                                "turn": last_turn,
                                "streak": streak,
                                "classification": "POLICY_BUG_REPEATED_PROTECT_SPAM",
                            })
                        if streak > max_streak_local:
                            max_streak_local = streak
                        continue
                    if line.startswith("|-fail|"):
                        # Server-side fail in the same turn as
                        # the most recent Protect attempt.
                        # A non-Protect fail is ignored.
                        if last_actor is None:
                            continue
                        out["protect_fail_count"] += 1
                        if streak >= 2:
                            # 2nd+ consecutive Protect attempt
                            # also failed: this is a repeated
                            # fail. The first fail of a streak
                            # (streak=1) is not repeated; the
                            # second and later are.
                            out["repeated_protect_fail_count"] += 1
                            out["protect_policy_bug_count"] += 1
                            spam_battles.add(bname)
                            out["events"].append({
                                "battle": bname,
                                "actor": last_actor,
                                "turn": last_turn,
                                "streak": streak,
                                "classification": "POLICY_BUG_REPEATED_FAILED_PROTECT",
                            })
                        # Mark the current attempt as failed.
                        last_failed = True
                        continue
        except Exception:
            continue
        if max_streak_local > out["max_consecutive_protect_streak"]:
            out["max_consecutive_protect_streak"] = max_streak_local
    # successful = total - failed (approx; we did not
    # always know the server's success flag, so this is an
    # upper bound).
    out["protect_success_count"] = max(
        0, out["protect_move_count"] - out["protect_fail_count"]
    )
    out["protect_spam_battles"] = len(spam_battles)
    out["protect_spam_gate_pass"] = out["protect_policy_bug_count"] == 0
    return out


# ponytail: status-move / spread-move / move-id sets used by
# the no-effect parser to filter which failing moves
# count as type-immunity policy bugs.
_NO_EFFECT_STATUS_MOVE_IDS_PARSER = frozenset({
    "protect", "detect", "spikyshield", "kingsshield",
    "obstruct", "maxguard", "silktrap", "quickguard",
    "wideguard", "endure", "substitute", "taunt",
    "encore", "thunderwave", "willowisp", "toxic",
    "spore", "sleeppowder", "stunspore", "yawn",
    "haze", "confuseray", "disable", "swagger",
    "rest", "sleeptalk", "recover", "roost",
    "softboiled", "morningsun", "moonlight",
    "milkdrink", "slackoff", "wish", "lifedew",
    "tailwind", "trickroom", "sunnyday", "raindance",
    "sandstorm", "snowscape", "grassyterrain",
    "electricterrain", "psychicterrain", "mistyterrain",
    "helpinghand", "coaching", "healpulse",
})


def parse_no_effect_attacks_from_raw_protocol(raw_dir: str) -> dict:
    """Walk ``raw_dir`` for ``*.jsonl`` battle files and
    detect repeated no-effect attacking moves.

    Detection rule (per battle, per actor + target):

      - Track the most recent ``|move|actor|move|target|``
        line. A subsequent ``|-immune|<target>`` or
        ``It doesn't affect <target>`` line in the same
        turn is associated with the most recent move.
      - Status moves are excluded (they are not "no-effect
        type immunity" attacks).
      - Spread moves are excluded (a spread hit on a
        single immune target can still affect the other
        targets).
      - A non-Protect, non-immune-line event between the
        move and the next immune line resets the most-
        recent move tracker.
      - Repeated (>=2) consecutive no-effect moves by the
        same actor into the same target constitute a
        policy bug.
      - Opponent attacks into the bot's Protect are NOT
        counted as Protect failure (we don't increment
        here; that's the protect parser's job).

    Returns dict with these fields:
      - no_effect_move_count
      - known_immunity_no_effect_count
      - repeated_no_effect_move_count
      - no_effect_policy_bug_count
      - no_effect_policy_gate_pass
      - no_effect_policy_battles
      - events (list of per-(battle, actor, target) dicts)
    """
    import glob as _glob
    import os as _os
    out = {
        "no_effect_move_count": 0,
        "known_immunity_no_effect_count": 0,
        "repeated_no_effect_move_count": 0,
        "no_effect_policy_bug_count": 0,
        "no_effect_policy_gate_pass": True,
        "no_effect_policy_battles": 0,
        "events": [],
    }
    if not raw_dir or not _os.path.isdir(raw_dir):
        return out
    spam_battles = set()
    for fp in sorted(_glob.glob(_os.path.join(raw_dir, "*.jsonl"))):
        bname = _os.path.basename(fp)
        turn = 0
        # Most recent (actor, move, target) on this turn.
        cur_actor = None
        cur_move = None
        cur_target = None
        # Per-(actor, target) consecutive no-effect count
        # tracked ACROSS turns. A non-no-effect event for the
        # same key resets the count; a turn gap > 1 also
        # resets.
        consecutive_key = None
        consecutive_count = 0
        last_no_effect_turn = -1
        try:
            with open(fp) as f:
                for ln in f:
                    try:
                        rec = __import__("json").loads(ln)
                    except Exception:
                        continue
                    line = rec.get("line", "")
                    if line.startswith("|turn|"):
                        try:
                            turn = int(line.split("|")[2])
                        except Exception:
                            turn = 0
                        # New turn: reset the current-move
                        # tracker. We do NOT reset the
                        # consecutive_key / count because a
                        # bot that tries the same no-effect
                        # move on turn 14 and again on turn 19
                        # is just as broken.
                        cur_actor = None
                        cur_move = None
                        cur_target = None
                        continue
                    if line.startswith("|move|"):
                        parts = line.split("|")
                        if len(parts) < 5:
                            continue
                        move_id = parts[3].lower().replace(" ", "")
                        # Skip status / setup moves.
                        if move_id in _NO_EFFECT_STATUS_MOVE_IDS_PARSER:
                            cur_actor = None
                            cur_move = None
                            cur_target = None
                            continue
                        # Spread moves are NOT skipped: the
                        # |-immune| lines for each target
                        # drive the no-effect counting. A
                        # spread move into 2 Flying targets
                        # produces 2 |-immune| events, both
                        # for the same actor but different
                        # targets. Each is counted as a
                        # no-effect event for that
                        # (actor, target) pair. The
                        # "repeated" check then flags
                        # repeated no-effect into the same
                        # (actor, target).
                        cur_actor = parts[2]
                        cur_move = move_id
                        cur_target = parts[4] if parts[4] else ""
                        continue
                    if (
                        "|-immune|" in line
                        or "doesn't affect" in line
                    ):
                        if cur_actor is None or cur_move is None:
                            continue
                        # Phase 7 fix: if the current move
                        # is a Protect-like self-protection
                        # move, the |-immune| is an
                        # opponent attack blocked by our
                        # Protect, not a damaging type-
                        # immunity no-effect. Skip it.
                        if cur_move in {
                            "protect", "detect", "spikyshield",
                            "kingsshield", "obstruct", "maxguard",
                            "silktrap", "banefulbunker",
                            "burningbulwark",
                        }:
                            cur_actor = None
                            cur_move = None
                            cur_target = None
                            continue
                        out["no_effect_move_count"] += 1
                        out["known_immunity_no_effect_count"] += 1
                        key = (cur_actor, cur_target)
                        # "Repeated" = any 2+ no-effect events
                        # for the same (actor, target) in
                        # the same battle. We don't require
                        # consecutive turns because a
                        # bot that tries Electric into
                        # Ground on turn 14 and again on
                        # turn 19 is just as broken as
                        # turn 14 and 15.
                        if consecutive_key == key:
                            consecutive_count += 1
                        else:
                            consecutive_key = key
                            consecutive_count = 1
                        last_no_effect_turn = turn
                        if consecutive_count >= 2:
                            out["repeated_no_effect_move_count"] += 1
                            out["no_effect_policy_bug_count"] += 1
                            spam_battles.add(bname)
                            out["events"].append({
                                "battle": bname,
                                "actor": cur_actor,
                                "target": cur_target,
                                "move": cur_move,
                                "turn": turn,
                                "consecutive_count": consecutive_count,
                                "classification": "POLICY_BUG_REPEATED_NO_EFFECT",
                            })
                        cur_actor = None
                        cur_move = None
                        cur_target = None
                        continue
        except Exception:
            continue
    out["no_effect_policy_battles"] = len(spam_battles)
    out["no_effect_policy_gate_pass"] = out["no_effect_policy_bug_count"] == 0
    return out


# ponytail: small positive-priority move-id set used by the raw
# protocol parser. Mirror of
# ``bot_doubles_damage_aware._PSYCHIC_TERRAIN_PRIORITY_BLOCK_MOVE_IDS``
# but kept independent so the audit module does not import the bot.
_PRIORITY_BLOCK_MOVE_IDS = frozenset({
    "fakeout",
    "extremespeed",
    "suckerpunch",
    "aquajet",
    "vacuumwave",
    "thunderclap",
    "quickguard",
    "machpunch",
    "bulletpunch",
    "iceshard",
    "shadowstrike",
    "accelerock",
})

# ponytail: status move-id set for the raw Prankster Psychic Terrain
# parser. Mirror of
# ``bot_doubles_damage_aware._PRANKSTER_PSYCHIC_TERRAIN_STATUS_MOVE_IDS``
# but kept independent.
_PRANKSTER_PSYCHIC_TERRAIN_STATUS_MOVE_IDS = frozenset({
    "taunt",
    "encore",
    "thunderwave",
    "willowisp",
    "disable",
    "confuseray",
    "yawn",
    "spore",
    "sleeppowder",
    "stunspore",
    "glare",
    "nuzzle",
    "toxic",
    "poisongas",
    "haze",
    "swaggersubstitute",
})


def parse_priority_terrain_blocks_from_raw_protocol(
    raw_dir: str,
    known_prankster_users_by_battle: Optional[dict] = None,
) -> dict:
    """Walk ``raw_dir`` for ``*.jsonl`` battle files and return a
    summary dict with the Psychic Terrain priority-block counts.

    Detection rule:
      A ``|-activate|<target>|move: Psychic Terrain`` line is a
      Psychic Terrain priority block when the most recent
      ``|move|...|<move>|...|`` line on the same battle selected
      a positive-priority move (ordinary allowlist) or a
      Prankster-boosted status move (Prankster allowlist).

    Prankster status moves only count as a confirmed
    ``POLICY_BUG_PRANKSTER_STATUS_IN_PSYCHIC_TERRAIN`` if the
    user's Prankster ability is explicitly known for the same
    battle. The optional ``known_prankster_users_by_battle`` is a
    dict ``{battle_id: set([actor_ident, ...])}`` of actors whose
    Prankster ability is explicitly known (e.g. from the bot's
    own team metadata or a raw ``|-ability|...|Prankster|``
    reveal). If the ability is not explicitly known, the event
    is classified as
    ``UNKNOWN_PRANKSTER_PRIORITY_NEEDS_ABILITY_EVIDENCE`` and
    counted in
    ``unknown_prankster_psychic_terrain_suspect_count``.

    Returns dict with these fields:
      - priority_terrain_block_count (int)
      - fake_out_psychic_terrain_block_count (int)
      - priority_psychic_terrain_block_count (int)
      - prankster_psychic_terrain_block_count (int)
      - unknown_prankster_psychic_terrain_suspect_count (int)
      - priority_terrain_block_battles (int)
      - failed_move_policy_bug_count (int) — alias for the gate
      - priority_terrain_block_gate_pass (bool)
      - failed_move_policy_gate_pass (bool)
      - prankster_priority_block_gate_pass (bool)
      - events (list of dict) — per-event record
    """
    import glob as _glob
    import os as _os
    out = {
        "priority_terrain_block_count": 0,
        "fake_out_psychic_terrain_block_count": 0,
        "priority_psychic_terrain_block_count": 0,
        "prankster_psychic_terrain_block_count": 0,
        "unknown_prankster_psychic_terrain_suspect_count": 0,
        "priority_terrain_block_battles": 0,
        "failed_move_policy_bug_count": 0,
        "priority_terrain_block_gate_pass": True,
        "failed_move_policy_gate_pass": True,
        "prankster_priority_block_gate_pass": True,
        "events": [],
    }
    if not raw_dir or not _os.path.isdir(raw_dir):
        return out
    known = known_prankster_users_by_battle or {}
    battles_with_block = set()
    for fp in sorted(_glob.glob(_os.path.join(raw_dir, "*.jsonl"))):
        bname = _os.path.basename(fp)
        # Per-battle: most recent priority-eligible move, plus the
        # battle's known-Prankster set derived from raw
        # ``|-ability|...|Prankster|`` reveals.
        last_priority_move = None  # dict {actor, target, move, kind, status}
        known_prankster_actors = set(known.get(bname, set()))
        try:
            with open(fp) as f:
                for ln in f:
                    try:
                        rec = __import__("json").loads(ln)
                    except Exception:
                        continue
                    line = rec.get("line", "")
                    if line.startswith("|turn|"):
                        last_priority_move = None
                        continue
                    # Track Prankster reveals via ``|-ability|``.
                    # Format: |-ability|<actor>|<ability>
                    if line.startswith("|-ability|") and "Prankster" in line:
                        parts = line.split("|")
                        if len(parts) >= 4:
                            known_prankster_actors.add(parts[2])
                        continue
                    # Some protocols use |detailschange|...|Prankster
                    if (
                        line.startswith("|detailschange|")
                        and "Prankster" in line
                    ):
                        parts = line.split("|")
                        if len(parts) >= 3:
                            # actor ident is parts[2]
                            known_prankster_actors.add(parts[2])
                        continue
                    if line.startswith("|move|"):
                        parts = line.split("|")
                        if len(parts) >= 5:
                            move_id = parts[3].lower()
                            move_id_compact = move_id.replace(" ", "").replace(
                                "-", ""
                            )
                            if (
                                move_id in _PRIORITY_BLOCK_MOVE_IDS
                                or move_id_compact in _PRIORITY_BLOCK_MOVE_IDS
                            ):
                                last_priority_move = {
                                    "actor": parts[2],
                                    "target": parts[4],
                                    "move": parts[3],
                                    "kind": "ordinary",
                                }
                            elif move_id_compact in _PRANKSTER_PSYCHIC_TERRAIN_STATUS_MOVE_IDS:
                                last_priority_move = {
                                    "actor": parts[2],
                                    "target": parts[4],
                                    "move": parts[3],
                                    "kind": "prankster_status",
                                }
                        continue
                    if (
                        line.startswith("|-activate|")
                        and "move: Psychic Terrain" in line
                    ):
                        parts = line.split("|")
                        target = parts[2] if len(parts) > 2 else ""
                        if last_priority_move is not None:
                            move_norm = (
                                last_priority_move["move"]
                                .lower()
                                .replace(" ", "")
                                .replace("-", "")
                            )
                            kind = last_priority_move.get("kind", "ordinary")
                            is_prankster_block = kind == "prankster_status"
                            actor = last_priority_move["actor"]
                            ability_known = actor in known_prankster_actors

                            if is_prankster_block:
                                if ability_known:
                                    cls = "POLICY_BUG_PRANKSTER_STATUS_IN_PSYCHIC_TERRAIN"
                                else:
                                    cls = "UNKNOWN_PRANKSTER_PRIORITY_NEEDS_ABILITY_EVIDENCE"
                            else:
                                cls = (
                                    "POLICY_BUG_FAKE_OUT_IN_PSYCHIC_TERRAIN"
                                    if move_norm == "fakeout"
                                    else "POLICY_BUG_PRIORITY_BLOCKED_BY_PSYCHIC_TERRAIN"
                                )

                            out["priority_terrain_block_count"] += 1
                            out["failed_move_policy_bug_count"] += 1
                            if move_norm == "fakeout":
                                out["fake_out_psychic_terrain_block_count"] += 1
                            elif is_prankster_block:
                                if ability_known:
                                    out["prankster_psychic_terrain_block_count"] += 1
                                else:
                                    out[
                                        "unknown_prankster_psychic_terrain_suspect_count"
                                    ] += 1
                            else:
                                out["priority_psychic_terrain_block_count"] += 1
                            battles_with_block.add(bname)
                            event_record = {
                                "battle": bname,
                                "actor": actor,
                                "target": target,
                                "move": last_priority_move["move"],
                                "classification": cls,
                                "ability_known": ability_known,
                                "kind": kind,
                                "raw_line": line.strip()[:200],
                            }
                            out["events"].append(event_record)
                            # Reset so the same priority move is not
                            # counted twice if a single |-activate|
                            # arrives later for a different reason.
                            last_priority_move = None
        except Exception:
            continue
    out["priority_terrain_block_battles"] = len(battles_with_block)
    out["priority_terrain_block_gate_pass"] = (
        out["priority_terrain_block_count"] == 0
    )
    out["failed_move_policy_gate_pass"] = (
        out["failed_move_policy_bug_count"] == 0
    )
    out["prankster_priority_block_gate_pass"] = (
        out["prankster_psychic_terrain_block_count"] == 0
        and out["unknown_prankster_psychic_terrain_suspect_count"] == 0
    )
    return out
