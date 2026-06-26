"""Phase 7 Protect-like stall and type-immunity hard-block helpers.

Ponytail: pure helpers, no poke-env runtime, no I/O.

This module is the Phase 7 production-path fix for two
residual bugs identified by the 3-battle diagnostic smoke
(see ``logs/phase7_protect_spam_diagnostic_smoke3_local_only_run/``):

1. **Protect-like variant loophole**: the previous hard-block
   applied only to the exact move id, so the bot could
   cycle through ``Protect -> Detect -> King's Shield`` and
   keep stalling for 25-38 consecutive turns. The fix
   normalises all self-protection moves into a single
   ``protect_like`` stall class.

2. **Spread-move type-immunity gap**: the previous
   no-effect hard-block excluded all spread moves
   (Earthquake, Surf, Dazzling Gleam, etc.) entirely, so
   Earthquake into two Flying targets was never blocked.
   The fix evaluates spread moves per-target: block only
   if ALL valid targets are immune.

The helpers here are intentionally small, pure, and
side-effect-free so they can be unit-tested without the
poke-env runtime. The bot source wires them into
``_score_action_impl`` and the parser/gate wires them
into ``parse_no_effect_attacks_from_raw_protocol``.
"""

from typing import Any, Dict, FrozenSet, List, Optional, Tuple


# Normalised Protect-like stall class. All moves in this
# set share the same consecutive-use semantics: clicking
# them 3+ times in a row by the same active pokemon is
# hard-blocked. Wide Guard and Quick Guard are excluded
# because they protect allies rather than the user; the
# "stall" concern is about self-protection only.
PROTECT_LIKE_MOVE_IDS: FrozenSet[str] = frozenset({
    "protect",
    "detect",
    "spikyshield",
    "kingsshield",
    "obstruct",
    "maxguard",
    "silktrap",
    "banefulbunker",
    "burningbulwark",
})


# Spread damaging moves that hit multiple targets. The
# no-effect hard-block for these moves is evaluated
# per-target: block only if ALL valid targets are immune.
SPREAD_DAMAGING_MOVE_IDS: FrozenSet[str] = frozenset({
    "earthquake",
    "surf",
    "discharge",
    "heatwave",
    "lavaplume",
    "eruption",
    "waterspout",
    "dazzlinggleam",
    "magnitude",
    "bulldoze",
    "explosion",
    "selfdestruct",
    "muddywater",
    "sludgewave",
    "diamondstorm",
    "rockslide",
    "icywind",
    "snarl",
    "incinerate",
    "hypervoice",
    "boomburst",
    "overdrive",
    "clangingscales",
    "precipiceblades",
    "originpulse",
    "glaciate",
    "blizzard",
    "breakingswipe",
    "makeitrain",
})


def normalise_protect_like_move_id(move_id: str) -> Optional[str]:
    """Return ``"protect_like"`` if the move is a Protect-like
    self-protection move, else return ``None``.

    This is the normalised stall class. Consecutive-use
    counting uses this class, not the raw move id, so
    ``Protect -> Detect -> King's Shield`` counts as 3
    consecutive Protect-like attempts.
    """
    if not move_id:
        return None
    m = str(move_id).lower().replace(" ", "").replace("-", "")
    if m in PROTECT_LIKE_MOVE_IDS:
        return "protect_like"
    return None


def is_spread_damaging_move(move_id: str) -> bool:
    """Return True if the move is a spread damaging move
    that hits multiple opponents.
    """
    if not move_id:
        return False
    m = str(move_id).lower().replace(" ", "").replace("-", "")
    return m in SPREAD_DAMAGING_MOVE_IDS


# Key for a per-(battle, slot, pokemon) Protect-like
# streak record. The streak is across the normalised
# stall class, not per move id.
ProtectStreakKey = Tuple[str, int, str]


def make_protect_streak_key(
    battle_tag: str,
    active_idx: int,
    pokemon_ident: str,
) -> ProtectStreakKey:
    """Build a (battle_tag, active_idx, pokemon_ident) key
    for the Protect-like streak state dict.

    Battle boundary resets the streak (new battle_tag).
    Slot boundary is independent (p1a vs p1b are separate
    keys). Pokemon boundary resets the streak (new ident).
    """
    return (battle_tag, active_idx, pokemon_ident)


def protect_streak_should_block(
    state: Dict[ProtectStreakKey, Dict[str, Any]],
    battle_tag: str,
    active_idx: int,
    pokemon_ident: str,
    current_turn: int,
    move_id: str,
) -> Tuple[bool, bool]:
    """Pure decision: should this Protect-like move be
    hard-blocked?

    Returns ``(is_hard_blocked, should_record_observation)``.

    The state dict is NOT mutated by this function. The
    caller is responsible for updating the state once per
    final selected order, not once per candidate scoring
    call. This eliminates the "scoring call mutates state
    many times per turn" bug.

    Rules:

    * Non-Protect-like move: not hard-blocked.
    * Battle boundary (new battle_tag): not hard-blocked.
    * Pokemon boundary (new ident): not hard-blocked.
    * Turn gap > 1: not hard-blocked (streak broken by
      inactive turns).
    * First Protect-like attempt: not hard-blocked.
    * Second consecutive: not hard-blocked (heavy penalty
      applied by caller).
    * Third+ consecutive: hard-blocked.
    * Second+ whose previous attempt already failed:
      hard-blocked.

    ``should_record_observation`` is True if the caller
    should record the attempt in the state (it is a
    Protect-like move by the same pokemon on the same
    battle with no turn gap).
    """
    if not normalise_protect_like_move_id(move_id):
        return False, False
    key = make_protect_streak_key(battle_tag, active_idx, pokemon_ident)
    rec = state.get(key)
    if rec is None or rec.get("last_ident") != pokemon_ident:
        rec = {
            "last_turn": -1,
            "streak": 0,
            "last_ident": pokemon_ident,
            "last_failed": False,
        }
        state[key] = rec
    if rec["last_turn"] >= 0 and current_turn - rec["last_turn"] > 1:
        return False, True  # streak broken; record fresh attempt
    if rec["streak"] == 0:
        return False, True  # first attempt; record but not blocked
    if rec["streak"] >= 2:
        return True, True  # 3rd+ consecutive
    if rec["streak"] >= 1 and rec.get("last_failed"):
        return True, True  # 2nd+ after a failed attempt
    return False, True  # 2nd consecutive; not blocked, heavy penalty


def record_protect_like_attempt(
    state: Dict[ProtectStreakKey, Dict[str, Any]],
    battle_tag: str,
    active_idx: int,
    pokemon_ident: str,
    current_turn: int,
    move_id: str,
    failed: bool = False,
) -> Dict[str, Any]:
    """Record a Protect-like attempt in the streak state.

    Returns the updated record. The caller should call this
    EXACTLY ONCE per final selected order, not once per
    candidate scoring call. This is the single source of
    truth for state mutation.

    For non-Protect-like moves, the streak is RESET to 0
    (any non-Protect move breaks the stall chain). A
    switch (new ident) also resets. A battle boundary
    (new battle_tag) starts a fresh state.
    """
    key = make_protect_streak_key(battle_tag, active_idx, pokemon_ident)
    if not normalise_protect_like_move_id(move_id):
        # Non-Protect-like move: reset the streak for this
        # (battle, slot, pokemon) so the next Protect-like
        # attempt starts a fresh streak.
        rec = state.get(key)
        if rec is not None and rec.get("last_ident") == pokemon_ident:
            rec["streak"] = 0
            rec["last_failed"] = False
            state[key] = rec
        return {}
    rec = state.get(key)
    if rec is None or rec.get("last_ident") != pokemon_ident:
        rec = {
            "last_turn": -1,
            "streak": 0,
            "last_ident": pokemon_ident,
            "last_failed": False,
        }
    if rec["last_turn"] >= 0 and current_turn - rec["last_turn"] > 1:
        rec["streak"] = 0
        rec["last_failed"] = False
    rec["streak"] = rec["streak"] + 1
    rec["last_turn"] = current_turn
    rec["last_ident"] = pokemon_ident
    rec["last_failed"] = bool(failed)
    state[key] = rec
    return dict(rec)


def record_protect_like_failed(
    state: Dict[ProtectStreakKey, Dict[str, Any]],
    battle_tag: str,
    active_idx: int,
    pokemon_ident: str,
) -> None:
    """Mark the most recent Protect-like attempt as failed.
    Callers invoke this when a ``|-fail|`` line is observed
    for a Protect-like move in the same turn.

    This does NOT increment the streak. The next
    ``protect_streak_should_block`` call will see
    ``last_failed=True`` and block if streak >= 1.
    """
    key = make_protect_streak_key(battle_tag, active_idx, pokemon_ident)
    rec = state.get(key)
    if rec is None:
        return
    rec["last_failed"] = True


# Type-immunity no-effect helpers

# True if the move is a damaging single-target move
# (not a spread, not a status, not a self-target).
# The no-effect hard-block applies to these moves when
# the selected target is known-typed and immune.
def is_single_target_damaging_move(
    move_id: str,
    move_target: Any,
) -> bool:
    """Return True if the move is a single-target damaging
    move. Spread moves and status moves are excluded.
    """
    if not move_id:
        return False
    m = str(move_id).lower().replace(" ", "").replace("-", "")
    if is_spread_damaging_move(m):
        return False
    if not isinstance(move_target, int) or move_target < 0:
        return False
    return True


def all_spread_targets_immune(
    move_id: str,
    move_target: Any,
    opponent_active_pokemon: List[Any],
    is_type_immune_fn: Any,
    battle: Any,
) -> Tuple[bool, str]:
    """For a spread damaging move, check if ALL valid
    opponent targets are type-immune.

    Returns ``(all_immune, reason)``.

    Rules:

    * If the move is not a spread move, returns
      ``(False, "")``.
    * If the move has a single explicit target
      (``move_target`` is a valid index), check only that
      target. If the target is unknown-typed, returns
      ``(False, "unknown_target_type")`` (do not guess).
    * If the move has no explicit target (targets all
      opponents), check all opponent actives. If any
      opponent is unknown-typed, returns
      ``(False, "unknown_target_type")``.
    * Returns ``(True, reason)`` only when every
      checked target is confirmed type-immune.
    """
    if not is_spread_damaging_move(move_id):
        return False, ""
    if not isinstance(opponent_active_pokemon, list):
        return False, ""
    # For spread moves, ALWAYS check ALL opponent actives.
    # The move_target index is irrelevant for spread moves
    # because the move hits all adjacent opponents
    # regardless of the selected target slot. If even one
    # opponent can be affected, the action is not entirely
    # no-effect and must not be hard-blocked.
    targets = [
        t for t in opponent_active_pokemon if t is not None
    ]
    if not targets:
        return False, ""
    all_immune = True
    for tgt in targets:
        if tgt is None:
            continue
        t_types = list(getattr(tgt, "types", None) or ())
        if not t_types:
            return False, "unknown_target_type"
        try:
            immune, _reason = is_type_immune_fn(
                type("M", (), {"id": move_id})(),
                None,
                tgt,
                battle=battle,
            )
        except Exception:
            return False, "immunity_check_failed"
        if not immune:
            all_immune = False
            break
    if all_immune:
        return True, "all_spread_targets_immune"
    return False, ""


def is_damaging_no_effect_blocked(
    move_id: str,
    move_target: Any,
    opponent_active_pokemon: List[Any],
    is_type_immune_fn: Any,
    battle: Any,
) -> Tuple[bool, str]:
    """Return ``(is_blocked, reason)`` for a damaging move
    that is entirely no-effect against its selected target
    (or all spread targets).

    Rules:

    * Single-target damaging move: block if the selected
      target is known-typed and type-immune.
    * Spread damaging move: block only if ALL valid
      targets are known-typed and type-immune. If any
      target can be affected, do not block (the action
      is not entirely no-effect).
    * Unknown target type: do not block (do not guess).
    * Status moves: not handled here (the parser/gate
      handles status-move failures separately).
    """
    if not move_id:
        return False, ""
    m = str(move_id).lower().replace(" ", "").replace("-", "")
    if not m:
        return False, ""
    # Status moves are not handled here: a status move
    # failing against a Ghost-type target (e.g. Thunder
    # Wave) is a status-move failure, not a damaging
    # type-immunity no-effect. The parser/gate handles
    # status-move failures separately. We use the same
    # status-move set as _is_no_effect_attack_blocked.
    if m in {
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
    }:
        return False, ""
    if is_spread_damaging_move(m):
        return all_spread_targets_immune(
            m, move_target, opponent_active_pokemon,
            is_type_immune_fn, battle,
        )
    if not is_single_target_damaging_move(m, move_target):
        return False, ""
    if not isinstance(opponent_active_pokemon, list):
        return False, ""
    if not (isinstance(move_target, int)
            and 0 <= move_target < len(opponent_active_pokemon)):
        return False, ""
    tgt = opponent_active_pokemon[move_target]
    if tgt is None:
        return False, ""
    t_types = list(getattr(tgt, "types", None) or ())
    if not t_types:
        return False, "unknown_target_type"
    try:
        immune, _reason = is_type_immune_fn(
            type("M", (), {"id": m})(),
            None,
            tgt,
            battle=battle,
        )
    except Exception:
        return False, "immunity_check_failed"
    if immune:
        return True, "type_immunity"
    return False, ""
