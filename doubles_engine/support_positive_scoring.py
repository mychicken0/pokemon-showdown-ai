"""Phase SUPPORT-SCORING-1B — Support positive scoring
helper (Helping Hand + Tailwind only).

This module implements conservative positive scoring
for two support moves in doubles:

* ``helpinghand``: boosts the partner's next move
  power by 50% (1.5x). Conservative positive
  scoring when the partner has a meaningful
  damaging move.
* ``tailwind``: doubles the speed of the user's
  team for 4 turns. Conservative positive
  scoring when the user's team can benefit and
  Tailwind is not already active.

The scoring is **conservative**:

* Only applies when the master flag
  ``enable_support_positive_scoring`` is True
  (default OFF).
* Only applies to the two covered moves above.
* No bonus if target semantics are wrong (wrong
  side, no ally, etc.).
* No bonus if conditions are not met (Tailwind
  already active, ally has no damaging move,
  etc.).
* Uses only revealed moves, visible active
  Pokémon, and known battle state.
* Does NOT infer abilities from species
  (no Gale Wings / Prankster / Chlorophyll /
  Swift Swim / etc.).
* Does NOT use Magic Bounce species inference.
* Hard safety still wins over support positive
  scoring (hard-safety blocks run before this
  helper).

Bonus magnitudes (chosen conservatively, similar
in scale to existing opt-in bonuses like
``anti_trick_room_response_bonus=500.0``):

* ``helping_hand_bonus``: 120.0
  (per clear ally-damage synergy)
* ``tailwind_bonus``: 180.0
  (per clear team-speed benefit)

The module is **pure**: it does not read the bot
config, does not call into the bot engine, does
not open files. It only reads from the ``order``,
``active_idx``, ``battle`` arguments and the
``config`` argument.

Scope: SUPPORT-SCORING-1B only implements scoring
for ``helpinghand`` and ``tailwind``. All other
support moves (Wide Guard, Follow Me, Rage
Powder, Coaching, Life Dew, Pollen Puff, Haze,
Clear Smog, screens, hazards, Icy Wind, Electroweb,
Snarl, etc.) return no bonus from this helper.
They are classified by ``doubles_engine.support_scoring_audit``
for future phases.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

# The two moves covered by SUPPORT-SCORING-1B.
HELPING_HAND_MOVE_ID = "helpinghand"
TAILWIND_MOVE_ID = "tailwind"

# Conservative default bonus magnitudes.
DEFAULT_HELPING_HAND_BONUS = 120.0
DEFAULT_TAILWIND_BONUS = 180.0

# The set of move ids this helper can score.
# Keep this conservative: only the two cleared moves.
SCORED_MOVE_IDS: Set[str] = {
    HELPING_HAND_MOVE_ID,
    TAILWIND_MOVE_ID,
}


def _norm(move_id: Any) -> str:
    if move_id is None:
        return ""
    s = str(move_id)
    return (
        s.lower()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .replace("'", "")
    )


def is_support_positive_scoring_move(move_id: Any) -> bool:
    """Return True if this move id is in the
    SUPPORT-SCORING-1B allowlist.
    """
    return _norm(move_id) in SCORED_MOVE_IDS


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


class SupportPositiveScoringResult:
    """Structured result of a support positive
    scoring evaluation.

    Fields:
        move_id: normalized move id
        bonus: positive bonus to add to the score
        should_score: True if the bonus should be
            applied (i.e. all checks passed)
        reason: human-readable explanation
        target_side: resolved target side
            ("ally" | "opponent" | "self" | "field"
            | "unknown")
        own_benefit_score: own-side benefit score
        opponent_benefit_score: opponent-side
            benefit score
        safety_blocked: True if a hard-safety block
            applies (caller should defer to that
            block)
    """

    def __init__(
        self,
        move_id: str,
        bonus: float = 0.0,
        should_score: bool = False,
        reason: str = "",
        target_side: str = "unknown",
        own_benefit_score: float = 0.0,
        opponent_benefit_score: float = 0.0,
        safety_blocked: bool = False,
    ):
        self.move_id = move_id
        self.bonus = float(bonus)
        self.should_score = bool(should_score)
        self.reason = str(reason)
        self.target_side = str(target_side)
        self.own_benefit_score = float(own_benefit_score)
        self.opponent_benefit_score = float(opponent_benefit_score)
        self.safety_blocked = bool(safety_blocked)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "move_id": self.move_id,
            "bonus": self.bonus,
            "should_score": self.should_score,
            "reason": self.reason,
            "target_side": self.target_side,
            "own_benefit_score": self.own_benefit_score,
            "opponent_benefit_score": (
                self.opponent_benefit_score
            ),
            "safety_blocked": self.safety_blocked,
        }


# ---------------------------------------------------------------------------
# Master flag and config access
# ---------------------------------------------------------------------------


def _master_flag_enabled(config: Any) -> bool:
    """Check the master ``enable_support_positive_scoring``
    flag. Returns False if config is None or the
    flag is missing or False.
    """
    if config is None:
        return False
    return bool(
        getattr(
            config,
            "enable_support_positive_scoring",
            False,
        )
    )


def _helping_hand_bonus(config: Any) -> float:
    return float(
        getattr(
            config, "helping_hand_bonus", DEFAULT_HELPING_HAND_BONUS
        )
    )


def _tailwind_bonus(config: Any) -> float:
    return float(
        getattr(config, "tailwind_bonus", DEFAULT_TAILWIND_BONUS)
    )


# ---------------------------------------------------------------------------
# Active field inspection (Tailwind, etc.)
# ---------------------------------------------------------------------------


def _get_active_weather(battle: Any) -> Optional[str]:
    """Return the normalized active weather, or None
    if no weather is active.
    """
    if battle is None:
        return None
    w = getattr(battle, "weather", None)
    if w is None:
        return None
    s = str(w).upper()
    if "TAILWIND" in s:
        return "tailwind"
    return None


def _get_active_fields(battle: Any) -> List[str]:
    """Return a list of normalized active fields
    (e.g. ['tailwind']).
    """
    if battle is None:
        return []
    fields = getattr(battle, "fields", None) or []
    out: List[str] = []
    for f in fields:
        s = str(f).upper()
        if "TAILWIND" in s:
            out.append("tailwind")
    return out


def _tailwind_active(battle: Any) -> bool:
    return _get_active_weather(battle) == "tailwind" or (
        "tailwind" in _get_active_fields(battle)
    )


# ---------------------------------------------------------------------------
# Ally and opponent inspection
# ---------------------------------------------------------------------------


def _active_pokemon(battle: Any, active_idx: int) -> Any:
    if battle is None:
        return None
    actives = getattr(battle, "active_pokemon", None) or []
    if not isinstance(actives, list):
        return None
    if active_idx < 0 or active_idx >= len(actives):
        return None
    return actives[active_idx]


def _opponent_active_pokemon(battle: Any) -> List[Any]:
    if battle is None:
        return []
    return list(getattr(battle, "opponent_active_pokemon", None) or [])


def _ally_index(active_idx: int) -> int:
    """Given the current slot (0 or 1), return the
    partner slot (1 or 0)."""
    return 1 - int(active_idx)


def _target_side_for_order(
    order: Any, active_idx: int, battle: Any
) -> str:
    """Resolve the target side of a Move order using
    the same helper logic as support_targets.

    Returns one of: "ally", "opponent", "self",
    "field", "unknown".
    """
    if order is None or battle is None:
        return "unknown"
    target_pos = getattr(order, "move_target", 0)
    if target_pos == 0:
        return "field"
    if target_pos in (-1, -2):
        ally_idx = abs(target_pos) - 1
        if ally_idx == active_idx:
            return "self"
        return "ally"
    if target_pos in (1, 2):
        return "opponent"
    return "unknown"


def _pokemon_fainted(mon: Any) -> bool:
    if mon is None:
        return True
    if getattr(mon, "fainted", False):
        return True
    hp = getattr(mon, "current_hp_fraction", 1.0)
    try:
        return float(hp) <= 0.0
    except Exception:
        return False


def _move_id_from_order(order: Any) -> str:
    inner = getattr(order, "order", None)
    if inner is None:
        return ""
    return _norm(getattr(inner, "id", ""))


def _move_base_power(mon: Any, move_id: str) -> int:
    """Return the base power of ``move_id`` for the
    given Pokemon, or 0 if not available. Looks at
    the Pokemon's revealed moves and the move's
    known base power.
    """
    if mon is None or not move_id:
        return 0
    moves = getattr(mon, "moves", None) or {}
    norm = _norm(move_id)
    for k, v in moves.items():
        if _norm(k) == norm:
            try:
                return int(getattr(v, "base_power", 0) or 0)
            except Exception:
                return 0
    return 0


def _ally_has_damaging_move(
    ally: Any, exclude_move_id: str = ""
) -> bool:
    """Return True if the ally has at least one
    legal damaging move (base_power > 0).
    """
    if ally is None:
        return False
    if _pokemon_fainted(ally):
        return False
    moves = getattr(ally, "moves", None) or {}
    excl = _norm(exclude_move_id)
    for k, v in moves.items():
        if _norm(k) == excl:
            continue
        try:
            bp = int(getattr(v, "base_power", 0) or 0)
        except Exception:
            bp = 0
        if bp > 0:
            return True
    return False


def _ally_alive_count(battle: Any, active_idx: int) -> int:
    """Count how many of our active Pokemon are
    alive (not fainted, hp > 0)."""
    count = 0
    for idx in (0, 1):
        mon = _active_pokemon(battle, idx)
        if mon is not None and not _pokemon_fainted(mon):
            count += 1
    return count


def _opp_alive_count(battle: Any) -> int:
    count = 0
    for mon in _opponent_active_pokemon(battle):
        if mon is not None and not _pokemon_fainted(mon):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Helping Hand evaluation
# ---------------------------------------------------------------------------


def evaluate_helping_hand_semantics(
    order: Any, active_idx: int, battle: Any, config: Any
) -> SupportPositiveScoringResult:
    """Conservative Helping Hand positive scoring.

    Returns a SupportPositiveScoringResult. The
    bonus is positive only if all checks pass.
    """
    move_id = _move_id_from_order(order)
    if move_id != HELPING_HAND_MOVE_ID:
        return SupportPositiveScoringResult(
            move_id=move_id,
            reason="not_helpinghand",
        )
    if not _master_flag_enabled(config):
        return SupportPositiveScoringResult(
            move_id=move_id,
            reason="flag_off",
        )
    if battle is None or order is None:
        return SupportPositiveScoringResult(
            move_id=move_id,
            reason="missing_battle_or_order",
        )
    target_side = _target_side_for_order(order, active_idx, battle)
    if target_side != "ally":
        return SupportPositiveScoringResult(
            move_id=move_id,
            reason="wrong_side_target",
            target_side=target_side,
        )
    ally_idx = _ally_index(active_idx)
    ally = _active_pokemon(battle, ally_idx)
    if ally is None or _pokemon_fainted(ally):
        return SupportPositiveScoringResult(
            move_id=move_id,
            reason="ally_fainted_or_missing",
            target_side=target_side,
        )
    if not _ally_has_damaging_move(ally, exclude_move_id=move_id):
        return SupportPositiveScoringResult(
            move_id=move_id,
            reason="ally_no_damaging_move",
            target_side=target_side,
        )
    own_score = 1.0
    opp_score = 0.0
    bonus = _helping_hand_bonus(config)
    if bonus <= 0.0:
        return SupportPositiveScoringResult(
            move_id=move_id,
            reason="zero_bonus",
            target_side=target_side,
        )
    return SupportPositiveScoringResult(
        move_id=move_id,
        bonus=bonus,
        should_score=True,
        reason="helpinghand_ally_has_damaging_move",
        target_side=target_side,
        own_benefit_score=own_score,
        opponent_benefit_score=opp_score,
    )


# ---------------------------------------------------------------------------
# Tailwind evaluation
# ---------------------------------------------------------------------------


def evaluate_tailwind_semantics(
    order: Any, active_idx: int, battle: Any, config: Any
) -> SupportPositiveScoringResult:
    """Conservative Tailwind positive scoring.

    Returns a SupportPositiveScoringResult. The
    bonus is positive only if all checks pass.
    """
    move_id = _move_id_from_order(order)
    if move_id != TAILWIND_MOVE_ID:
        return SupportPositiveScoringResult(
            move_id=move_id,
            reason="not_tailwind",
        )
    if not _master_flag_enabled(config):
        return SupportPositiveScoringResult(
            move_id=move_id,
            reason="flag_off",
        )
    if battle is None or order is None:
        return SupportPositiveScoringResult(
            move_id=move_id,
            reason="missing_battle_or_order",
        )
    if _tailwind_active(battle):
        return SupportPositiveScoringResult(
            move_id=move_id,
            reason="tailwind_already_active",
        )
    our_alive = _ally_alive_count(battle, active_idx)
    if our_alive < 2:
        return SupportPositiveScoringResult(
            move_id=move_id,
            reason="not_enough_alive_allies",
        )
    opp_alive = _opp_alive_count(battle)
    if opp_alive < 1:
        return SupportPositiveScoringResult(
            move_id=move_id,
            reason="no_opponent_to_outspeed",
        )
    own_score = 1.0
    opp_score = 0.0
    bonus = _tailwind_bonus(config)
    if bonus <= 0.0:
        return SupportPositiveScoringResult(
            move_id=move_id,
            reason="zero_bonus",
        )
    return SupportPositiveScoringResult(
        move_id=move_id,
        bonus=bonus,
        should_score=True,
        reason="tailwind_team_can_benefit",
        target_side="field",
        own_benefit_score=own_score,
        opponent_benefit_score=opp_score,
    )


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def get_support_positive_bonus(
    order: Any,
    active_idx: int,
    battle: Any,
    config: Any = None,
) -> SupportPositiveScoringResult:
    """Top-level entry point for support positive
    scoring. Returns a
    :class:`SupportPositiveScoringResult`.

    Dispatch:
    * ``helpinghand`` -> ``evaluate_helping_hand_semantics``
    * ``tailwind`` -> ``evaluate_tailwind_semantics``
    * other -> empty result (no bonus)
    """
    move_id = _move_id_from_order(order)
    if not move_id:
        return SupportPositiveScoringResult(
            move_id="", reason="empty_move_id"
        )
    if not is_support_positive_scoring_move(move_id):
        return SupportPositiveScoringResult(
            move_id=move_id, reason="not_in_1b_allowlist"
        )
    if not _master_flag_enabled(config):
        return SupportPositiveScoringResult(
            move_id=move_id, reason="flag_off"
        )
    if move_id == HELPING_HAND_MOVE_ID:
        return evaluate_helping_hand_semantics(
            order, active_idx, battle, config
        )
    if move_id == TAILWIND_MOVE_ID:
        return evaluate_tailwind_semantics(
            order, active_idx, battle, config
        )
    return SupportPositiveScoringResult(
        move_id=move_id, reason="not_in_1b_allowlist"
    )
