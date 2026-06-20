#!/usr/bin/env python3
"""Phase CONTROL-4A — Anti-Setup Disruption
Eligibility Helper (PURE FUNCTION).

This module is a **pure function** that
decides whether a turn's bot Taunt / Encore
/ Disable / Quash candidate should
hypothetically receive the anti-setup
disruption bonus, given the audit data
visible in the turn.

It does NOT touch the bot. It does NOT
change scoring. It is a measurement
instrument only.

The dry-run analyzer in
`analyze_anti_setup_dryrun.py` uses this
function to sweep magnitudes.

Per AGENTS.md:
- "Do not infer hidden moves from a
  species."
- "Opponent moves, abilities, forms,
  and effects explicitly revealed by
  the protocol" are allowed.
- "Deterministic singleton ability
  resolution under the approved flag"
  is the only allowed inference.

This module respects those rules by
using only:
- `state_snapshot.opp_active_moves_revealed`
  (revealed only)
- `opponent_used_*` counters (revealed
  per-turn)
- `state_snapshot.weather` / `.fields`
  (field state, visible to all)
- `state_snapshot.opp_active_ability` /
  `.opp_active_item` (revealed)

The bonus is purely additive in the
dry-run; the actual scoring change is
in CONTROL-4B (NOT in this phase).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set, Tuple


# Target moves (4 anti-setup disruption moves)
ANTI_SETUP_TARGETS: Set[str] = frozenset({
    "taunt", "encore", "disable", "quash",
})

# Stat-boost / setup move allowlist
# (used to detect opp revealed setup signals)
STAT_BOOST_MOVES: Set[str] = frozenset({
    "swordsdance", "nastyplot", "dragondance",
    "calmmind", "bulkup", "quiverdance",
    "shellsmash", "workup", "agility",
    "rockpolish", "geomancy", "honeclaws",
    "charge", "growth", "howl",
    "doubleteam", "cosmicpower",
    "irondefense", "acidarmor",
    "autotomize", "minimize", "shiftgear",
})

# High-base-power moves (relevant for Disable
# trigger: "opp has a high-BP move revealed")
HIGH_BP_MOVES: Set[str] = frozenset({
    "earthquake", "closecombat", "flareblitz",
    "wildcharge", "boomburst", "moonblast",
    "heatwave", "makeitrain", "dracometeor",
    "sludgewave", "leafstorm", "thunderbolt",
    "thunder", "icebeam", "psychic",
    "focusblast", "hydropump", "fireblast",
    "shadowball", "energyball", "darkpulse",
    "stoneedge", "earthpower", "flashcannon",
    "ironhead", "knockoff", "uturn",
    "voltswitch", "rapidspin",
})

# Survival threshold (matches SETUP-3A pattern)
DEFAULT_SURVIVAL_HP_FRACTION = 0.25

# Anti-spam defaults
DEFAULT_MAX_PICKS_PER_GAME = 2
DEFAULT_MIN_TURN_BETWEEN = 3


def _norm(s: Any) -> str:
    """Normalize a name: lowercase, no spaces,
    no dashes, no underscores, no apostrophes."""
    return (str(s or "").lower()
            .replace(" ", "")
            .replace("-", "")
            .replace("_", "")
            .replace("'", ""))


def _is_target_move(move_id: Any) -> bool:
    """Return True if move_id is in the
    anti-setup disruption family."""
    return _norm(move_id) in ANTI_SETUP_TARGETS


def _has_field_active(
    snap: Optional[Dict[str, Any]],
    field_name: str,
) -> bool:
    """Check if a field/weather condition is
    active. Per AGENTS.md, weather/fields are
    visible to both players."""
    if not snap:
        return False
    fnorm = _norm(field_name)
    for w in snap.get("weather", []) or []:
        if fnorm in _norm(w):
            return True
    for f in snap.get("fields", []) or []:
        if fnorm in _norm(f):
            return True
    for sc in snap.get("side_conditions", []) or []:
        if fnorm in _norm(sc):
            return True
    for osc in snap.get("opponent_side_conditions", []) or []:
        if fnorm in _norm(osc):
            return True
    return False


def _target_to_slot(target: Any) -> Optional[int]:
    """Convert a target string to opp slot
    index (0 or 1) or None if invalid.

    VGC convention:
    - 1 = opp slot 0
    - 2 = opp slot 1
    - -1 = self
    - -2 = ally
    - 0 = no target / entire field
    """
    if target is None:
        return None
    try:
        t = int(target)
    except (TypeError, ValueError):
        return None
    if t in (1, 2):
        return t - 1
    return None


def _opp_setup_signals(
    snap: Optional[Dict[str, Any]],
    opp_actions: Optional[Dict[str, Any]],
    target_slot: int,
    scoring_move: Optional[str] = None,
) -> float:
    """Compute the visible opp-setup signal
    sum for a given target slot.

    Each signal adds 1.0 (or 0.5 for
    weaker signals).

    Sources (all visible-only):
    - `opponent_used_stat_boost_setup`:
      strong signal (1.0)
    - `opponent_used_tailwind` /
      `opponent_used_trickroom`: 0.5 each
    - `state_snapshot.opp_active_moves_revealed[target_slot]`
      contains a stat-boost move: 1.0
    - Field TW/TR active: 0.5 each
      (ambiguous, but visible)
    - For Disable specifically: opp revealed
      a high-BP move: 1.0 (only if
      scoring_move == 'disable')

    The high-BP signal is move-aware: it's
    only relevant for Disable, since Disable
    is the move that "blocks the next use of
    the target's last move." For Taunt /
    Encore / Quash, the high-BP signal is
    not relevant.
    """
    score = 0.0
    if opp_actions:
        if opp_actions.get("opponent_used_stat_boost_setup"):
            score += 1.0
        if opp_actions.get("opponent_used_tailwind"):
            score += 0.5
        if opp_actions.get("opponent_used_trickroom"):
            score += 0.5
    if snap:
        # Revealed moves (ITEM-2)
        opp_moves_list = (
            snap.get("opp_active_moves_revealed", []) or []
        )
        if 0 <= target_slot < len(opp_moves_list):
            opp_moves = opp_moves_list[target_slot] or []
            for mv in opp_moves:
                if _norm(mv) in STAT_BOOST_MOVES:
                    score += 1.0
                elif _norm(mv) in HIGH_BP_MOVES:
                    # High-BP is only a signal for
                    # Disable (move-aware).
                    if scoring_move and _norm(scoring_move) == "disable":
                        score += 1.0
        # Field state
        if _has_field_active(snap, "tailwind"):
            score += 0.5
        if _has_field_active(snap, "trickroom"):
            score += 0.5
    return score


def _bot_survives(
    snap: Optional[Dict[str, Any]],
    active_idx: int,
) -> bool:
    """Return True if bot's active pokemon
    at active_idx has HP > 25% (or
    require_survival=False)."""
    if not snap:
        # If we can't determine HP, be safe
        # and let the bonus fire (assume alive)
        return True
    hp_list = (
        snap.get("our_active_hp_fraction", []) or []
    )
    if not (0 <= active_idx < len(hp_list)):
        return True
    hp = hp_list[active_idx]
    if hp is None:
        return True
    return float(hp) >= DEFAULT_SURVIVAL_HP_FRACTION


def _is_bot_taunted_or_encored(
    snap: Optional[Dict[str, Any]],
    active_idx: int,
) -> bool:
    """Check if bot's active mon is visibly
    Taunted or Encored. Per AGENTS.md, only
    visible volatiles are allowed. We check
    the snapshot's `our_active_*` fields.

    Note: The state_snapshot does not directly
    capture volatile statuses (Taunt/Encore).
    This function is a placeholder for the
    actual volatile lookup, which will be
    added if poke-env exposes them.

    For dry-run, we assume the bot is
    NOT Taunted/Encored (conservative:
    don't block the bonus based on this
    guard alone)."""
    # TODO: integrate with poke-env's
    # battle.active_pokemon[active_idx].taunted
    # when this helper is wired into the bot.
    return False


def _parse_legal_key(key: Any) -> Optional[Tuple[str, str, str]]:
    """Parse a legal action key into
    (kind, value, target).

    Accepts two formats:
    - String: 'kind|value|target'
      (used by raw_score keys)
    - List: [kind, value, target]
      (used by legal_action_keys in audit)

    Returns None on invalid input.
    """
    if isinstance(key, (list, tuple)) and len(key) >= 3:
        return (str(key[0]), str(key[1]), str(key[2]))
    if isinstance(key, str):
        parts = key.split("|")
        if len(parts) != 3:
            return None
        return (parts[0], parts[1], parts[2])
    return None


def _has_legal_anti_setup_per_slot(
    legal_action_keys: List[Any],
) -> Dict[int, Tuple[str, str, str]]:
    """For each opp slot (0 or 1), find the
    anti-setup move targeting that slot.

    Returns a dict: {target_slot:
    (kind, value, target)} where target_slot
    is 0 or 1 (opp slot index).

    If multiple anti-setup moves target the
    same opp slot, the one with the lowest
    target value is preferred (typically the
    single-target version).

    Skip non-opp targets (self, ally, etc.).
    """
    by_slot: Dict[int, List[Tuple[str, str, str]]] = {}
    for key in legal_action_keys or []:
        parsed = _parse_legal_key(key)
        if not parsed:
            continue
        kind, mv, target = parsed
        if kind != "move" or not _is_target_move(mv):
            continue
        target_slot = _target_to_slot(target)
        if target_slot is None:
            continue
        by_slot.setdefault(target_slot, []).append(parsed)
    # Pick best per slot (lowest target)
    return {
        slot: min(candidates, key=lambda x: int(x[2]))
        for slot, candidates in by_slot.items()
    }


def _has_legal_anti_setup(
    legal_action_keys: List[Any],
) -> Optional[Tuple[str, str, str]]:
    """Find the first anti-setup move in
    legal_action_keys. Returns the parsed
    (kind, value, target) or None.

    If multiple are present, the one with
    the lowest target (1 > 2) is preferred
    (slot 0 is the closer threat).
    """
    by_slot = _has_legal_anti_setup_per_slot(legal_action_keys)
    if not by_slot:
        return None
    # Prefer slot 0
    return by_slot[min(by_slot.keys())]


def anti_setup_eligible(
    snap: Optional[Dict[str, Any]],
    opp_actions: Optional[Dict[str, Any]],
    legal_action_keys: List[Any],
    selected_score: Optional[float],
    best_ko_score: Optional[float] = None,
    picks_used: int = 0,
    last_pick_turn: Optional[int] = None,
    current_turn: Optional[int] = None,
    min_opp_setup_signal: float = 1.0,
    max_picks_per_game: int = DEFAULT_MAX_PICKS_PER_GAME,
    min_turn_between: int = DEFAULT_MIN_TURN_BETWEEN,
    require_survival: bool = True,
) -> Dict[str, Any]:
    """Phase CONTROL-4A: decide if the bot's
    anti-setup disruption bonus should fire
    this turn.

    Returns a dict with:
    - "eligible": bool
    - "reason": str (one of: "no_legal",
      "not_target", "taunted", "no_survival",
      "no_signal", "spam_cap", "spam_gap",
      "obvious_ko", "ok")
    - "signal": float (computed signal sum)
    - "target_slot": int | None
    - "move": str | None

    Pure function: no side effects, no
    scoring change.
    """
    legal = _has_legal_anti_setup(legal_action_keys)
    if not legal:
        return {
            "eligible": False, "reason": "no_legal",
            "signal": 0.0, "target_slot": None,
            "move": None,
        }
    kind, mv, target = legal
    target_slot = _target_to_slot(target)
    if target_slot is None:
        return {
            "eligible": False, "reason": "not_target",
            "signal": 0.0, "target_slot": None,
            "move": mv,
        }
    if require_survival and not _bot_survives(snap, 0):
        return {
            "eligible": False, "reason": "no_survival",
            "signal": 0.0, "target_slot": target_slot,
            "move": mv,
        }
    if _is_bot_taunted_or_encored(snap, 0):
        return {
            "eligible": False, "reason": "taunted",
            "signal": 0.0, "target_slot": target_slot,
            "move": mv,
        }
    # Anti-spam
    if picks_used >= max_picks_per_game:
        return {
            "eligible": False, "reason": "spam_cap",
            "signal": 0.0, "target_slot": target_slot,
            "move": mv,
        }
    if (last_pick_turn is not None
            and current_turn is not None
            and (current_turn - last_pick_turn) < min_turn_between):
        return {
            "eligible": False, "reason": "spam_gap",
            "signal": 0.0, "target_slot": target_slot,
            "move": mv,
        }
    # Compute signal
    signal = _opp_setup_signals(
        snap, opp_actions, target_slot,
        scoring_move=mv,
    )
    if signal < min_opp_setup_signal:
        return {
            "eligible": False, "reason": "no_signal",
            "signal": signal, "target_slot": target_slot,
            "move": mv,
        }
    # Obvious KO alternative?
    if (best_ko_score is not None
            and best_ko_score > 100
            and selected_score is not None
            and (selected_score - best_ko_score) < 50):
        # Selected action is close to best_ko;
        # don't disrupt when a near-KO is in
        # play. (We use the gap, not absolute.)
        # This is conservative: only block if the
        # best KO was within 50 of the selected.
        # At dry-run, we just observe.
        return {
            "eligible": True, "reason": "obvious_ko_warn",
            "signal": signal, "target_slot": target_slot,
            "move": mv,
        }
    return {
        "eligible": True, "reason": "ok",
        "signal": signal, "target_slot": target_slot,
        "move": mv,
    }


def main() -> int:
    """Self-check: print a brief usage note."""
    print("anti_setup_eligibility.py — pure function module")
    print("Import anti_setup_eligible() to use.")
    print("This module does NOT change scoring.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
