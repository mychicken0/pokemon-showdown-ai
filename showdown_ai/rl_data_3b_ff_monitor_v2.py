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

    # Same-side single-target damaging move -> actual friendly-fire
    if same_side:
        if move_lc and not _is_status_move(move_lc):
            return "ACTUAL_SINGLE_TARGET_FRIENDLY_FIRE"

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
        "opponent_actual_friendly_fire_count",
        "opponent_actual_friendly_fire_battles",
        "opponent_actual_friendly_fire_turn_rate",
        "bot_actual_friendly_fire_count",
        "bot_actual_friendly_fire_battles",
        "bot_selected_negative_target_count",
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
    """Return a summary dict with all required fields, default 0/False."""
    out = {
        "opponent_actual_friendly_fire_count": 0,
        "opponent_actual_friendly_fire_battles": 0,
        "opponent_actual_friendly_fire_turn_rate": 0.0,
        "bot_actual_friendly_fire_count": 0,
        "bot_actual_friendly_fire_battles": 0,
        "bot_selected_negative_target_count": 0,
        "bot_selected_negative_target_rate": 0.0,
        "false_positive_spread_damage_count": 0,
        "false_positive_weather_chip_count": 0,
        "false_positive_status_chip_count": 0,
        "false_positive_hazard_damage_count": 0,
        "false_positive_recoil_count": 0,
        "false_positive_item_or_ability_damage_count": 0,
        "false_positive_end_of_turn_chip_count": 0,
        "unknown_friendly_fire_suspect_count": 0,
        "raw_protocol_logs_present": bool(raw_protocol_logs_present),
        "friendly_fire_monitor_version": "v2_raw_protocol",
    }
    return out


def stage2_gate_passes(summary: dict) -> bool:
    """Apply the post-fix Stage 2 hard gate."""
    if not summary.get("raw_protocol_logs_present"):
        return False
    if summary.get("opponent_actual_friendly_fire_count", 0) > 0:
        return False
    if summary.get("bot_actual_friendly_fire_count", 0) > 0:
        return False
    if summary.get("unknown_friendly_fire_suspect_count", 0) > 0:
        return False
    return True
