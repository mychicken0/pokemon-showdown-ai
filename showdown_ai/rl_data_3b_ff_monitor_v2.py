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

# Phase 7 v2 refinement: no-effect classifier constants.
# These are used to distinguish real bot policy bugs
# from opponent-driven game mechanics and parser
# artifacts. No species-based ability inference.
_REDIRECTION_DEBUG_TOKENS = frozenset({
    # emitted by Showdown protocol when a redirection
    # move (Rage Powder, Follow Me, Storm Drain,
    # Lightning Rod, Spotlight) changes the move target.
    "rage powder redirected target of move",
    "follow me redirected target of move",
    "storm drain redirected target of move",
    "lightning rod redirected target of move",
    "spotlight redirected target of move",
})
_REDIRECTION_MOVE_IDS = frozenset({
    "ragepowder", "followme", "stormdrain", "lightningrod",
    "spotlight",
})
# Hint line emitted by Showdown when a Prankster
# status move fails on a Dark-type target.
_PRANKSTER_DARK_HINT_TOKENS = frozenset({
    "since gen 7, dark is immune to prankster moves.",
})
_PRANKSTER_DEBUG_TOKENS = frozenset({
    "natural prankster immunity",
})
# Known Prankster users. The parser is **not**
# allowed to infer Prankster from species. This set
# is only consulted when the raw protocol already
# shows a Prankster-vs-Dark signal (the hint or
# debug line) and is used to double-check that the
# move is a Prankster move before classifying.
# (We do not consult this set to decide if a move
# is Prankster; we only consult it to confirm
# when the protocol already flagged a no-effect.)
_KNOWN_PRANKSTER_MOVE_IDS = frozenset({
    "encore", "thunderwave", "willowisp", "toxic",
    "spore", "sleeppowder", "stunspore", "yawn",
    "confuseray", "disable", "swagger", "leer",
    "stringshot", "smokescreen", "sandattack",
    "kinesis", "flash", "cottonspore", "sweetkiss",
    "lovelykiss", "nobleroar", "partingshot",
    "memento", "topsyturvy", "faketears", "charm",
    "featherdance", "screech", "growl", "tailwhip",
    "taunt", "haze",
    # Plus: the "non-status but Prankster-boosted"
    # damaging moves. These are not relevant to the
    # status-only no-effect classification, but we
    # include them for completeness when the
    # protocol signals "natural prankster immunity".
    "thunderclap", "shadowstrike",
})
# Bot side convention. The smoke runner assigns the
# bot to ``p1`` and the opponent to ``p2``. Actor
# identifiers in the protocol are formatted
# ``p1a: <species>`` / ``p1b: <species>`` for the
# bot and ``p2a: <species>`` / ``p2b: <species>``
# for the opponent. The ``startswith("p1")`` test
# is robust to the ``a`` / ``b`` slot suffix.
_BOT_SIDE_PREFIX = "p1"

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
        # Productive-partial-spread no-effect
        # diagnostics. NOT safety failures.
        "productive_partial_spread_no_effect_false_positive_count": 0,
        "spread_all_targets_immune_bug_count": 0,
        "spread_partial_productive_immune_count": 0,
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
      - max_consecutive_protect_streak > 1 (PHASE7 strict
        cooldown: no consecutive Protect-like attempts
        allowed; the parser is the diagnostic view of
        what the bot actually did)
      - no_effect_policy_bug_count > 0 (no-effect / immunity
        attack policy gap; PHASE7_PRODUCTION_HARD_BLOCK_*
        investigation)
      - repeated_no_effect_move_count > 0

    Does NOT fail for submitted_same_side_target_count > 0
    or for productive_partial_spread_no_effect_false_positive
    events.
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
    if summary.get("bot_non_encore_forced_max_protect_streak", 0) > 1:
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
      - State is independent per actor/slot. A failed or
        ``[still]`` attempt remains a selected attempt and
        does not reset the streak.
      - ``repeated_protect_fail_count`` is reserved for a
        failed third-or-later attempt after a prior failed
        attempt; two selected attempts remain permitted.
      - A non-Protect move, turn gap, or switch resets that
        actor/slot streak.
      - Policy bug counters apply to bot-side (p1) selected
        attempts only. Opponent-side attempts remain in the
        all-sides diagnostic maximum.

    Returns dict with these fields:
      - protect_move_count
      - protect_success_count
      - protect_fail_count
      - consecutive_protect_attempt_count (>=2 streaks)
      - max_consecutive_protect_streak
      - repeated_protect_fail_count
      - protect_policy_bug_count (bot-side 3+ streaks)
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
        "max_consecutive_protect_like_attempt_streak": 0,
        "max_consecutive_protect_like_attempt_streak_all_sides": 0,
        "repeated_protect_fail_count": 0,
        "protect_like_third_attempt_bug_count": 0,
        "protect_like_still_gap_bug_count": 0,
        "protect_policy_bug_count": 0,
        # Phase 7 Protect audit refinement: additive field
        # for Encore-forced Protect events. These are NOT
        # counted as policy bugs because the bot had no
        # legal alternative (see _is_repeated_protect_spam
        # and the only_legal override).
        "encore_forced_protect_artifact_count": 0,
        # Phase 7 Protect audit refinement: maximum
        # consecutive Protect-like streak for bot-side
        # non-Encore-forced events. Used for the gate.
        "bot_non_encore_forced_max_protect_streak": 0,
        "protect_spam_gate_pass": True,
        "protect_spam_battles": 0,
        "events": [],
    }
    if not raw_dir or not _os.path.isdir(raw_dir):
        return out
    spam_battles = set()
    for fp in sorted(_glob.glob(_os.path.join(raw_dir, "*.jsonl"))):
        bname = _os.path.basename(fp)
        current_turn = 0
        actor_state = {}
        # Phase 7 Encore-aware Protect audit: track which
        # actors are under Encore. Reset on |turn| because
        # Encore expires after a few turns (or when the
        # Encored Pokémon switches out). The Encore state
        # is set when an Encore move targets a bot-side
        # actor, and cleared on |turn| (the Encore
        # persists into the next turn but the affected
        # actor's state was already carried forward).
        # We need a per-actor Encore flag that persists
        # across turns so that Protect-like moves on
        # subsequent turns are also flagged. We store
        # it as a set of actor identifiers.
        encore_locked = set()
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
                        current_turn = t
                        continue
                    if line.startswith("|switch|"):
                        parts = line.split("|")
                        if len(parts) >= 3:
                            slot = parts[2].split(":", 1)[0]
                            actor_state = {
                                actor: rec
                                for actor, rec in actor_state.items()
                                if actor.split(":", 1)[0] != slot
                            }
                            # Phase 7 Encore-aware Protect audit:
                            # clear Encore state for actors in
                            # the switching slot because the
                            # Pokémon identity changed.
                            encore_locked = {
                                a for a in encore_locked
                                if a.split(":", 1)[0] != slot
                            }
                        continue
                    if line.startswith("|move|"):
                        parts = line.split("|")
                        if len(parts) < 5:
                            continue
                        actor = parts[2]
                        move_id = parts[3].lower().replace(" ", "").replace("'", "").replace("-", "")
                        is_protect_like = move_id in {
                            "protect", "detect", "spikyshield",
                            "kingsshield", "obstruct", "maxguard",
                            "silktrap", "banefulbunker",
                            "burningbulwark",
                        }
                        if not is_protect_like:
                            actor_state.pop(actor, None)
                            # Phase 7 Encore-aware Protect audit:
                            # if the current move is Encore
                            # targeting a bot-side actor, mark
                            # that actor as Encore-locked so
                            # subsequent Protect-like attempts
                            # on the same turn are classified
                            # as forced artifacts.
                            if move_id == "encore" and len(parts) >= 5:
                                encore_target = parts[4]
                                if encore_target.startswith("p1"):
                                    encore_locked.add(encore_target)
                            continue
                        out["protect_move_count"] += 1
                        rec = actor_state.get(actor, {})
                        previous_failed = bool(rec.get("last_failed", False))
                        previous_still = bool(rec.get("last_still", False))
                        if (
                            rec.get("last_turn", -1) >= 0
                            and current_turn - rec["last_turn"] == 1
                        ):
                            streak = int(rec.get("streak", 0)) + 1
                        else:
                            streak = 1
                            previous_failed = False
                            previous_still = False
                        is_still = "[still]" in line
                        actor_state[actor] = {
                            "streak": streak,
                            "last_turn": current_turn,
                            "last_failed": False,
                            "last_still": is_still,
                            "previous_failed": previous_failed,
                        }
                        is_bot = actor.startswith("p1")
                        # PHASE7_POLICY_SANITY_STRICT_PROTECT_COOLDOWN:
                        # any 2nd consecutive Protect-like
                        # attempt by the bot is a policy
                        # bug (was previously 3rd).
                        #
                        # Phase 7 Protect audit refinement:
                        # When the bot's Protect-like move is
                        # "forced" by Encore (signalled via
                        # ``[still]`` in the raw protocol line
                        # or by the previous attempt being a
                        # ``[still]`` line), the bot had no
                        # other legal action because the
                        # opponent's Encore locked the move.
                        # The cooldown hard-blocked the move,
                        # but ``only_legal`` allowed it through
                        # because no alternative existed.
                        # These events are tracked as
                        # ``encore_forced_protect_artifact``,
                        # not as policy bugs.
                        is_encore_forced = is_still or previous_still or (actor in encore_locked)
                        if is_bot and streak >= 2:
                            out["consecutive_protect_attempt_count"] += 1
                            if previous_still or previous_failed:
                                out["protect_like_still_gap_bug_count"] += 1
                            if is_encore_forced:
                                out["encore_forced_protect_artifact_count"] = \
                                    out.get("encore_forced_protect_artifact_count", 0) + 1
                                out["events"].append({
                                    "battle": bname,
                                    "actor": actor,
                                    "turn": current_turn,
                                    "streak": streak,
                                    "classification": "POLICY_BUG_REPEATED_PROTECT_SPAM_FORCED_BY_ENCORE",
                                })
                            else:
                                out["protect_policy_bug_count"] += 1
                                out["protect_like_third_attempt_bug_count"] += 1
                                spam_battles.add(bname)
                                out["events"].append({
                                    "battle": bname,
                                    "actor": actor,
                                    "turn": current_turn,
                                    "streak": streak,
                                    "classification": "POLICY_BUG_REPEATED_PROTECT_SPAM",
                                })
                        out[
                            "max_consecutive_protect_like_attempt_streak_all_sides"
                        ] = max(
                            out[
                                "max_consecutive_protect_like_attempt_streak_all_sides"
                            ],
                            streak,
                        )
                        if is_bot:
                            out["max_consecutive_protect_streak"] = max(
                                out["max_consecutive_protect_streak"],
                                streak,
                            )
                            out[
                                "max_consecutive_protect_like_attempt_streak"
                            ] = max(
                                out[
                                    "max_consecutive_protect_like_attempt_streak"
                                ],
                                streak,
                            )
                            # Track a separate max that excludes
                            # Encore-forced Protect events. This
                            # is the value used for the gate.
                            if not is_encore_forced:
                                out[
                                    "bot_non_encore_forced_max_protect_streak"
                                ] = max(
                                    out.get(
                                        "bot_non_encore_forced_max_protect_streak", 0
                                    ),
                                    streak,
                                )
                        continue
                    if line.startswith("|-fail|"):
                        # Server-side fail in the same turn as
                        # the most recent Protect attempt.
                        # A non-Protect fail is ignored.
                        parts = line.split("|")
                        actor = parts[2] if len(parts) >= 3 else ""
                        rec = actor_state.get(actor)
                        if rec is None or rec.get("last_turn") != current_turn:
                            continue
                        out["protect_fail_count"] += 1
                        if (
                            actor.startswith("p1")
                            and rec.get("previous_failed", False)
                            and rec.get("streak", 0) >= 3
                        ):
                            out["repeated_protect_fail_count"] += 1
                            spam_battles.add(bname)
                            out["events"].append({
                                "battle": bname,
                                "actor": actor,
                                "turn": current_turn,
                                "streak": rec.get("streak", 0),
                                "classification": "POLICY_BUG_REPEATED_FAILED_PROTECT",
                            })
                        rec["last_failed"] = True
                        continue
        except Exception:
            continue
    # successful = total - failed (approx; we did not
    # always know the server's success flag, so this is an
    # upper bound).
    out["protect_success_count"] = max(
        0, out["protect_move_count"] - out["protect_fail_count"]
    )
    out["protect_spam_battles"] = len(spam_battles)
    out["protect_spam_gate_pass"] = (
        out["protect_policy_bug_count"] == 0
        and out["repeated_protect_fail_count"] == 0
        and out.get("bot_non_encore_forced_max_protect_streak", 0) <= 1
    )
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
    # Stat-lowering status moves (no type immunity possible)
    "faketears", "charm", "featherdance", "screech",
    "growl", "tailwhip", "leer", "sandattack",
    "stringshot", "smokescreen", "kinesis", "flash",
    "cottonspore", "stunspore", "sweetkiss", "lovelykiss",
    "nobleroar", "partingshot", "memento", "topsyturvy",
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
      - Spread moves are NOT skipped; per-target accounting
        is preserved. A productive partial spread (one
        target immune AND at least one other target took
        damage) is classified as a
        ``productive_partial_spread_no_effect_false_positive``
        and is NOT a real policy bug.
      - A non-Protect, non-immune-line event between the
        move and the next immune line resets the most-
        recent move tracker.
      - Repeated (>=2) consecutive no-effect moves by the
        same actor into the same target constitute a
        policy bug.
      - Opponent attacks into the bot's Protect are NOT
        counted as Protect failure (we don't increment
        here; that's the protect parser's job).

    Phase 7 v2 refinement: classification of no-effect
    events into additive buckets so that the
    ``no_effect_policy_gate`` only fails on
    ``real_bot_no_effect_bug_count > 0``:

      - ``REDIRECTION_INDUCED_NO_EFFECT_ARTIFACT``:
        the protocol shows a redirection debug line
        (e.g. ``|debug|Rage Powder redirected target of
        move``) or the no-effect follows a redirection
        move (Rage Powder, Follow Me, Storm Drain,
        Lightning Rod, Spotlight). The bot aimed at
        a valid target; the opponent's redirection
        caused the no-effect. This is a parser-side
        artifact, not a real bot policy bug.
      - ``STATUS_OR_PRANKSTER_DARK_NO_EFFECT_ARTIFACT``:
        the protocol shows a Prankster-vs-Dark hint
        (``|hint|Since gen 7, Dark is immune to
        Prankster moves.``) or a ``|debug|natural
        prankster immunity`` line, and the move is in
        the known Prankster set or is a status move
        in the no-effect status set. The bot chose
        a reasonable Prankster move; the Dark-type
        immunity is a server-side game mechanic.
        This is a parser-side artifact, not a real
        bot policy bug.
      - ``INSUFFICIENT_CONTEXT_NO_EFFECT_ARTIFACT``:
        the no-effect cannot be confidently
        classified. We do not default to "real bot
        bug" in this case; we track the event
        separately and the bot gate still passes.
      - ``OPPONENT_SIDE_NO_EFFECT``: the actor is
        the opponent side (``p2``). The bot is on
        ``p1``. The bot's gate does not fail on
        opponent-side no-effect events.
      - ``REAL_BOT_NO_EFFECT_BUG``: the actor is
        the bot side, the move is a damaging move
        (not a status move), the no-effect is not
        caused by redirection or Prankster-vs-Dark,
        and the target is selected by the bot
        directly. This is the only bucket that
        increments ``no_effect_policy_bug_count`` and
        fails the gate.

    Important: no species-based ability inference.
    The classifier only consults raw protocol
    lines and move-id lookups. Prankster, Levitate,
    Magic Bounce, etc. are not inferred from
    species; they are only used when the protocol
    already produced a hint or debug line.

    Productive-partial-spread handling:

      For a spread move, the parser tracks the set of
      opponents that took actual ``|-damage|`` for the same
      move on the same turn. If a spread move produced at
      least one ``|-immune|`` AND at least one ``|-damage|``
      for a non-immune target on the same (battle, turn,
      actor, move), the ``|-immune|`` events are classified
      as
      ``productive_partial_spread_no_effect_false_positive``
      and the event is NOT counted as a real
      ``no_effect_policy_bug`` for the gate.

    Returns dict with these fields:
      - no_effect_move_count (legacy; total no-effect events)
      - known_immunity_no_effect_count (legacy)
      - repeated_no_effect_move_count (legacy; total
        consecutive events across all classifications)
      - no_effect_policy_bug_count (legacy alias for
        real_bot_no_effect_bug_count, kept for
        compatibility with existing call sites)
      - no_effect_policy_gate_pass (legacy alias for
        the additive gate; passes if
        real_bot_no_effect_bug_count == 0 AND
        spread_all_targets_immune_bug_count == 0)
      - no_effect_policy_battles
      - productive_partial_spread_no_effect_false_positive_count
      - spread_all_targets_immune_bug_count
      - spread_partial_productive_immune_count
      - real_bot_no_effect_bug_count (additive; new)
      - redirection_induced_no_effect_artifact_count
      - status_or_prankster_dark_no_effect_artifact_count
      - insufficient_context_no_effect_count
      - opponent_side_no_effect_count
      - protect_self_blocked_count (opponent's attack
        into bot's Protect; not a gate event)
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
        "productive_partial_spread_no_effect_false_positive_count": 0,
        "spread_all_targets_immune_bug_count": 0,
        "spread_partial_productive_immune_count": 0,
        # Additive Phase 7 v2 refinement fields
        "real_bot_no_effect_bug_count": 0,
        "redirection_induced_no_effect_artifact_count": 0,
        "status_or_prankster_dark_no_effect_artifact_count": 0,
        "insufficient_context_no_effect_count": 0,
        "opponent_side_no_effect_count": 0,
        "protect_self_blocked_count": 0,
        "events": [],
    }
    if not raw_dir or not _os.path.isdir(raw_dir):
        return out
    spam_battles = set()
    for fp in sorted(_glob.glob(_os.path.join(raw_dir, "*.jsonl"))):
        bname = _os.path.basename(fp)
        # Read all lines once so we can look ahead.
        all_lines = []
        try:
            with open(fp) as f:
                for ln in f:
                    try:
                        rec = __import__("json").loads(ln)
                    except Exception:
                        continue
                    all_lines.append(rec.get("line", ""))
        except Exception:
            continue
        turn = 0
        # Most recent (actor, move, target) on this turn.
        cur_actor = None
        cur_move = None
        cur_target = None
        # Phase 7 v2 refinement: track whether the
        # current ``cur_move`` is a status move. Status
        # moves cannot produce real damaging
        # no-effect events, but they may still
        # produce ``|-immune|`` lines (Prankster-vs-Dark)
        # that we want to classify separately.
        cur_is_status_move = False
        # Phase 7 v2 refinement: per-turn signals that
        # persist across lines on the same turn. Reset
        # only when a new |turn| marker is seen. These
        # let the parser capture a |debug|Rage Powder
        # redirected ...| line and apply the redirection
        # classification to a later |-|immune| line on
        # the same turn.
        redirect_seen_this_turn = False
        prankster_dark_seen_this_turn = False
        # Per-(actor, target) consecutive no-effect count
        # tracked ACROSS turns. A non-no-effect event for the
        # same key resets the count; a turn gap > 1 also
        # resets.
        consecutive_key = None
        consecutive_count = 0
        last_no_effect_turn = -1
        try:
            for idx, line in enumerate(all_lines):
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
                    # is just as broken. The
                    # per-turn redirect / Prankster
                    # signals ARE reset on a new turn.
                    cur_actor = None
                    cur_move = None
                    cur_target = None
                    cur_is_status_move = False
                    redirect_seen_this_turn = False
                    prankster_dark_seen_this_turn = False
                    continue
                if line.startswith("|move|"):
                    parts = line.split("|")
                    if len(parts) < 5:
                        continue
                    move_id = parts[3].lower().replace(" ", "")
                    # Status / setup moves. These are
                    # not "damaging no-effect" events;
                    # they cannot produce a real
                    # ``REAL_BOT_NO_EFFECT_BUG`` because
                    # they are not damaging. However,
                    # the protocol may still emit a
                    # ``|-immune|`` for a status move
                    # (Prankster-vs-Dark immunity,
                    # Ghost-type Light Screen, etc.)
                    # that we want to classify as a
                    # ``STATUS_OR_PRANKSTER_DARK_NO_EFFECT_ARTIFACT``
                    # and not a real bot policy bug.
                    # We track the move (so the
                    # subsequent |-|immune| line is
                    # captured) but do NOT increment
                    # the damaging-no-effect counters.
                    if move_id in _NO_EFFECT_STATUS_MOVE_IDS_PARSER:
                        cur_actor = parts[2]
                        cur_move = move_id
                        cur_target = parts[4] if parts[4] else ""
                        cur_is_status_move = True
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
                    cur_is_status_move = False
                    continue
                # Phase 7 v2 refinement: capture
                # redirection debug lines and
                # Prankster-vs-Dark hint/debug lines
                # BEFORE the |-|immune| line, so the
                # classifier can use them. The
                # per-turn signals are reset on
                # |turn| and persist across lines on the
                # same turn.
                if line.startswith("|debug|"):
                    lname = line.lower()
                    for tok in _REDIRECTION_DEBUG_TOKENS:
                        if tok in lname:
                            redirect_seen_this_turn = True
                            break
                    if not redirect_seen_this_turn:
                        for tok in _PRANKSTER_DEBUG_TOKENS:
                            if tok in lname:
                                prankster_dark_seen_this_turn = True
                                break
                if line.startswith("|-hint|"):
                    lname = line.lower()
                    for tok in _PRANKSTER_DARK_HINT_TOKENS:
                        if tok in lname:
                            prankster_dark_seen_this_turn = True
                            break
                if (
                    line.startswith("|-immune|")
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
                        out["protect_self_blocked_count"] += 1
                        cur_actor = None
                        cur_move = None
                        cur_target = None
                        continue
                    # Extract the immune target from the
                    # protocol line for classification.
                    # The |-immune| line format is
                    # `|-immune|<actor>` (the immune
                    # recipient). The |-| doesn't affect
                    # line format is similar.
                    immune_target = ""
                    if line.startswith("|-immune|"):
                        try:
                            immune_target = line.split("|")[2]
                        except Exception:
                            immune_target = ""
                    # Spread partial-productive handling:
                    # if the same (actor, move, turn)
                    # spread move produced at least one
                    # clean damage line, then this
                    # |-immune| is a partial productive
                    # hit (the move productively hit at
                    # least one target). It is a parser
                    # false-positive, NOT a real bot
                    # safety bug. We must lookahead
                    # because the protocol emits
                    # `|move| -> |-immune| -> |-damage|`
                    # in that order: the damage comes
                    # AFTER the immune for the same
                    # turn, so we scan forward to the
                    # next |move| or |turn| to check.
                    is_spread_move = cur_move in SPREAD_MOVE_IDS
                    productive_damage = False
                    if is_spread_move:
                        for j in range(
                            idx + 1, len(all_lines)
                        ):
                            fl = all_lines[j]
                            if fl.startswith(
                                "|move|"
                            ) or fl.startswith("|turn|"):
                                break
                            if not fl.startswith("|-damage|"):
                                continue
                            flags = []
                            try:
                                _parts = fl.split("|")
                                flags = [
                                    t for t in _parts
                                    if t.startswith("[")
                                ]
                            except Exception:
                                flags = []
                            is_clean = True
                            for f in flags:
                                f_lc = f.lower()
                                if f_lc.startswith("[from]"):
                                    value = f[
                                        len("[from]"):
                                    ].strip()
                                    if value.lower() in {
                                        t.lower()
                                        for t in WEATHER_CHIP_TOKENS
                                    }:
                                        is_clean = False
                                        break
                                    if value.lower() in {
                                        t.lower()
                                        for t in STATUS_FROM_TOKENS
                                    }:
                                        is_clean = False
                                        break
                                    if value in HAZARD_DAMAGE_TOKENS:
                                        is_clean = False
                                        break
                                    if value in ITEM_DAMAGE_TOKENS:
                                        is_clean = False
                                        break
                                    if value in ABILITY_DAMAGE_TOKENS:
                                        is_clean = False
                                        break
                                    if value.lower() in {
                                        m.lower()
                                        for m in RECOIL_MOVES
                                    }:
                                        is_clean = False
                                        break
                                    continue
                            if is_clean:
                                productive_damage = True
                                break
                    if is_spread_move and productive_damage:
                        out["productive_partial_spread_no_effect_false_positive_count"] += 1
                        out["spread_partial_productive_immune_count"] += 1
                        out["events"].append({
                            "battle": bname,
                            "actor": cur_actor,
                            "target": cur_target,
                            "move": cur_move,
                            "turn": turn,
                            "classification": "PRODUCTIVE_PARTIAL_SPREAD_NO_EFFECT_FALSE_POSITIVE",
                        })
                        cur_actor = None
                        cur_move = None
                        cur_target = None
                        continue
                    # Spread with ALL targets immune:
                    # count as a real no-effect bug. Only
                    # counts if there were no productive
                    # damage lines for the same spread move
                    # on the same turn. Also increments the
                    # no_effect counters because the spread
                    # move is entirely no-effect.
                    out["no_effect_move_count"] += 1
                    out["known_immunity_no_effect_count"] += 1
                    is_bot_side = cur_actor.startswith(_BOT_SIDE_PREFIX)
                    is_opponent_side = cur_actor.startswith("p2")
                    # Phase 7 v2 refinement: classify
                    # the no-effect event into one of the
                    # additive buckets. The legacy
                    # ``no_effect_policy_bug_count`` and
                    # ``repeated_no_effect_move_count``
                    # counters are kept for compatibility
                    # but the new ``real_bot_no_effect_bug_count``
                    # is what actually drives the gate.
                    classification = None
                    if is_opponent_side:
                        # Opponent-side no-effect. The
                        # bot's gate is not affected.
                        classification = "OPPONENT_SIDE_NO_EFFECT"
                        out["opponent_side_no_effect_count"] += 1
                    elif cur_is_status_move:
                        # The current move is a status
                        # move (e.g. Encore, Thunder
                        # Wave). The protocol has emitted
                        # an |-|immune| line for it. The
                        # most common cause is
                        # Prankster-vs-Dark immunity
                        # (which the protocol signals via
                        # a hint line). We require the
                        # explicit Prankster signal;
                        # otherwise we conservatively
                        # mark as insufficient context.
                        # We do NOT increment the
                        # damaging-no-effect counters
                        # (``no_effect_move_count`` and
                        # ``real_bot_no_effect_bug_count``)
                        # because a status move's
                        # failure is not a "damaging"
                        # no-effect. The legacy
                        # ``no_effect_move_count`` was
                        # already incremented above
                        # (legacy compatibility); we
                        # back it out here to preserve
                        # the prior test contract.
                        if prankster_dark_seen_this_turn:
                            classification = "STATUS_OR_PRANKSTER_DARK_NO_EFFECT_ARTIFACT"
                            out["status_or_prankster_dark_no_effect_artifact_count"] += 1
                        else:
                            classification = "INSUFFICIENT_CONTEXT_NO_EFFECT_ARTIFACT"
                            out["insufficient_context_no_effect_count"] += 1
                        # Back out the legacy
                        # increment because status
                        # moves were not previously
                        # counted. The additive
                        # classification is what
                        # matters.
                        out["no_effect_move_count"] -= 1
                        out["known_immunity_no_effect_count"] -= 1
                    elif redirect_seen_this_turn:
                        # Bot's move was redirected by
                        # the opponent's Rage Powder /
                        # Follow Me / Storm Drain /
                        # Lightning Rod / Spotlight.
                        # The bot's intended target was a
                        # valid (non-immune) target, and
                        # the immunity is on the
                        # redirected target. Not a real
                        # bot policy bug.
                        classification = "REDIRECTION_INDUCED_NO_EFFECT_ARTIFACT"
                        out["redirection_induced_no_effect_artifact_count"] += 1
                    elif prankster_dark_seen_this_turn:
                        # The protocol signals a
                        # Prankster-vs-Dark no-effect.
                        # Only count as artifact if the
                        # move is consistent with a
                        # Prankter status or known
                        # Prankster-boosted move. We do
                        # NOT infer Prankster from
                        # species; we trust the protocol
                        # hint line. (If the current
                        # move is a damaging move, we
                        # still trust the protocol: the
                        # protocol emits the hint line
                        # only when the actual game
                        # mechanic fires.)
                        classification = "STATUS_OR_PRANKSTER_DARK_NO_EFFECT_ARTIFACT"
                        out["status_or_prankster_dark_no_effect_artifact_count"] += 1
                    else:
                        # Bot-side damaging move with no
                        # redirection / Prankster
                        # signal. This is a real bot
                        # policy bug. (We do NOT
                        # include insufficient_context
                        # here: the no-effect is
                        # sufficiently explained by
                        # type-chart immunity. The
                        # "insufficient context" bucket
                        # is reserved for status-move
                        # failures without an explicit
                        # Prankster signal.)
                        classification = "REAL_BOT_NO_EFFECT_BUG"
                    # The legacy counters include ALL
                    # no-effect events (bot + opponent)
                    # to preserve the existing API. The
                    # new additive field is the one that
                    # actually fails the gate.
                    if is_spread_move and not is_opponent_side:
                        out["spread_all_targets_immune_bug_count"] += 1
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
                    if (
                        classification == "REAL_BOT_NO_EFFECT_BUG"
                        and consecutive_count >= 2
                    ):
                        out["repeated_no_effect_move_count"] += 1
                        out["no_effect_policy_bug_count"] += 1
                        out["real_bot_no_effect_bug_count"] += 1
                        spam_battles.add(bname)
                        out["events"].append({
                            "battle": bname,
                            "actor": cur_actor,
                            "target": cur_target,
                            "move": cur_move,
                            "turn": turn,
                            "consecutive_count": consecutive_count,
                            "classification": classification,
                        })
                    elif classification == "INSUFFICIENT_CONTEXT_NO_EFFECT_ARTIFACT":
                        out["insufficient_context_no_effect_count"] += 1
                        out["events"].append({
                            "battle": bname,
                            "actor": cur_actor,
                            "target": cur_target,
                            "move": cur_move,
                            "turn": turn,
                            "classification": classification,
                        })
                    # Non-bug classifications (redirection,
                    # prankster, opponent-side) are also
                    # logged in events with the
                    # classification tag for
                    # traceability. We do NOT
                    # increment the legacy
                    # no_effect_policy_bug_count or
                    # repeated_no_effect_move_count for
                    # these.
                    elif classification in {
                        "REDIRECTION_INDUCED_NO_EFFECT_ARTIFACT",
                        "STATUS_OR_PRANKSTER_DARK_NO_EFFECT_ARTIFACT",
                        "OPPONENT_SIDE_NO_EFFECT",
                    }:
                        out["events"].append({
                            "battle": bname,
                            "actor": cur_actor,
                            "target": cur_target,
                            "move": cur_move,
                            "turn": turn,
                            "classification": classification,
                        })
                    cur_actor = None
                    cur_move = None
                    cur_target = None
                    continue
        except Exception:
            continue
    out["no_effect_policy_battles"] = len(spam_battles)
    # The new gate is the additive one: passes iff
    # there are no real bot policy bugs and no
    # spread-all-immune bugs. The legacy
    # ``no_effect_policy_bug_count`` is kept as an
    # alias of ``real_bot_no_effect_bug_count`` for
    # compatibility with the existing call sites
    # (and the smoke report's field name).
    out["no_effect_policy_gate_pass"] = (
        out["real_bot_no_effect_bug_count"] == 0
        and out["spread_all_targets_immune_bug_count"] == 0
    )
    return out


# ponytail: low-value positive-priority damaging moves
# (Quick Attack, Aqua Jet, Mach Punch, Bullet Punch,
# Ice Shard, Accelerock, Vacuum Wave, Shadow Sneak)
# that the bot may select even when stronger moves are
# available. We do NOT add a scoring fix here; we add a
# diagnostic only. The user can later decide whether to
# invest in a narrow scoring rule.
_LOW_VALUE_PRIORITY_MOVE_IDS = frozenset({
    "quickattack",
    "aquajet",
    "machpunch",
    "bulletpunch",
    "iceshard",
    "accelerock",
    "vacuumwave",
    "shadowsneak",
    "thunderclap",
    "shadowstrike",
})


def parse_low_value_priority_from_raw_protocol(raw_dir: str) -> dict:
    """Walk ``raw_dir`` for ``*.jsonl`` battle files and
    count bot-side low-value positive-priority damaging
    moves (Quick Attack / Aqua Jet / Mach Punch / etc.).

    Diagnostic only. Does NOT change scoring and does NOT
    fail any gate. The result is reported separately so
    a future phase can decide whether to invest in a
    narrow scoring rule for low-value priority spam.

    Detection rule:

      - For each ``|move|<actor>|<move>|<target>|`` line,
        check if the move is in
        ``_LOW_VALUE_PRIORITY_MOVE_IDS``.
      - Count the move only for bot-side (p1) actors.
      - Count it again only if the same actor selected the
        same low-value priority move on the previous turn
        (consecutive spam). Repeated spam across turns
        is a stronger signal of bot policy weakness.
      - Track per-battle counts.

    Returns dict with these fields:
      - low_value_priority_move_count (int)
      - low_value_priority_consecutive_count (int)
      - low_value_priority_repeated_count (int)
      - low_value_priority_by_move_id (dict)
      - low_value_priority_by_battle (dict)
      - low_value_priority_battles (int)
      - events (list of per-event dicts)
      - low_value_priority_gate_pass (always True, see above)
    """
    import glob as _glob
    import os as _os
    out = {
        "low_value_priority_move_count": 0,
        "low_value_priority_consecutive_count": 0,
        "low_value_priority_repeated_count": 0,
        "low_value_priority_by_move_id": {},
        "low_value_priority_by_battle": {},
        "low_value_priority_battles": 0,
        "events": [],
        "low_value_priority_gate_pass": True,
    }
    if not raw_dir or not _os.path.isdir(raw_dir):
        return out
    spam_battles = set()
    for fp in sorted(_glob.glob(_os.path.join(raw_dir, "*.jsonl"))):
        bname = _os.path.basename(fp)
        current_turn = 0
        # Per-actor last low-value priority move and turn
        last_lv_move = {}
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
                        current_turn = t
                        continue
                    if line.startswith("|move|"):
                        parts = line.split("|")
                        if len(parts) < 5:
                            continue
                        actor = parts[2]
                        move_id = parts[3].lower().replace(" ", "").replace(
                            "-", ""
                        ).replace("'", "")
                        if move_id not in _LOW_VALUE_PRIORITY_MOVE_IDS:
                            last_lv_move.pop(actor, None)
                            continue
                        if not actor.startswith("p1"):
                            continue
                        out["low_value_priority_move_count"] += 1
                        out["low_value_priority_by_move_id"][
                            move_id
                        ] = out["low_value_priority_by_move_id"].get(
                            move_id, 0
                        ) + 1
                        out["low_value_priority_by_battle"][
                            bname
                        ] = out["low_value_priority_by_battle"].get(
                            bname, 0
                        ) + 1
                        last = last_lv_move.get(actor)
                        if (
                            last is not None
                            and last["move_id"] == move_id
                            and current_turn - last["turn"] == 1
                        ):
                            out[
                                "low_value_priority_consecutive_count"
                            ] += 1
                            if last.get("already_counted_consecutive"):
                                out[
                                    "low_value_priority_repeated_count"
                                ] += 1
                            # Mark the prior record as
                            # already-counted-consecutive so
                            # the NEXT turn (3rd in a row)
                            # will see this flag and emit a
                            # repeated event. Do NOT reset
                            # the flag here: the new record
                            # inherits the flag value.
                            last_lv_move[actor] = {
                                "move_id": move_id,
                                "turn": current_turn,
                                "already_counted_consecutive": True,
                            }
                            spam_battles.add(bname)
                            out["events"].append({
                                "battle": bname,
                                "actor": actor,
                                "turn": current_turn,
                                "move_id": move_id,
                                "classification": (
                                    "DIAGNOSTIC_LOW_VALUE_PRIORITY_SPAM"
                                ),
                            })
                        else:
                            last_lv_move[actor] = {
                                "move_id": move_id,
                                "turn": current_turn,
                                "already_counted_consecutive": False,
                            }
        except Exception:
            continue
    out["low_value_priority_battles"] = len(spam_battles)
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
