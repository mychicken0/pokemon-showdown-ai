#!/usr/bin/env python3
"""Phase PLANNER-2 — Intent Classifier (PURE FUNCTION).

Classifies a Pokemon move or action into an
intent_id. Used by the planner to map
candidates to intent families.

This is a **pure function** module. It does
NOT change scoring. It is a measurement
instrument for the planner.

Per AGENTS.md:
- Visible-only classification.
- No species guessing.
- No meta lookup.
- No random-set inference.

Intent families (per PLANNER-ROADMAP-1):

- DAMAGE: any damaging move (base_power > 0)
- STATUS: status move (base_power = 0, not
  protect/set-up/etc.)
- KO_NOW: damaging move with high damage
  (>= 50% target HP)
- SETUP: Tailwind, Trick Room, stat-boost
  (swordsdance, nastyplot, etc.)
- ANTI_SETUP: Taunt, Encore, Disable,
  Quash, Torment
- PROTECT: Protect, Detect, Spiky Shield,
  King's Shield, Baneful Bunker, Silk
  Trap, Burning Bulwark
- REDIRECT: Follow Me, Rage Powder,
  Spotlight
- SPREAD_DEFENSE: Wide Guard, Quick
  Guard, Crafty Shield
- COMBO: Helping Hand, Coaching, Decorate,
  Haze, Clear Smog, Beat Up, Life Dew,
  Heal Pulse, Pollen Puff, Ally Switch
- SWITCH: voluntary switch action
- PASS: pass action
- UNKNOWN: anything else

The classifier is **rule-based** using
allowlists. It does not infer from species
or use meta data.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


# Intent family: move id set (lowercase, no spaces/dashes)
INTENT_FAMILIES: Dict[str, set] = {
    "SETUP": {
        # Stat-boost moves
        "swordsdance", "nastyplot", "dragondance",
        "calmmind", "bulkup", "quiverdance",
        "shellsmash", "workup", "agility",
        "rockpolish", "geomancy", "honeclaws",
        "charge", "growth", "howl", "doubleteam",
        "cosmicpower", "irondefense", "acidarmor",
        "autotomize", "minimize", "shiftgear",
        # Speed control (SETUP family in the
        # existing CONTROL-1 analysis)
        "tailwind", "trickroom",
    },
    "ANTI_SETUP": {
        "taunt", "encore", "disable",
        "quash", "torment",
    },
    "PROTECT": {
        "protect", "detect", "spikyshield",
        "kingsshield", "banefulbunker", "silktrap",
        "burningbulwark", "maxguard", "obstruct",
    },
    "REDIRECT": {
        "followme", "ragepowder", "spotlight",
    },
    "SPREAD_DEFENSE": {
        "wideguard", "quickguard", "craftyshield",
        "matblock",
    },
    "COMBO": {
        "helpinghand", "coaching", "decorate",
        "haze", "clearsmog", "beatup", "lifedew",
        "healpulse", "pollenpuff", "allyswitch",
        "aromatherapy", "healbell",
    },
}


def _norm(s: Any) -> str:
    """Normalize a name: lowercase, no spaces,
    no dashes, no underscores, no apostrophes."""
    return (str(s or "").lower()
            .replace(" ", "")
            .replace("-", "")
            .replace("_", "")
            .replace("'", ""))


def _is_setup_move(move_id: str) -> bool:
    return _norm(move_id) in INTENT_FAMILIES["SETUP"]


def _is_anti_setup_move(move_id: str) -> bool:
    return _norm(move_id) in INTENT_FAMILIES["ANTI_SETUP"]


def _is_protect_move(move_id: str) -> bool:
    return _norm(move_id) in INTENT_FAMILIES["PROTECT"]


def _is_redirect_move(move_id: str) -> bool:
    return _norm(move_id) in INTENT_FAMILIES["REDIRECT"]


def _is_spread_defense_move(move_id: str) -> bool:
    return _norm(move_id) in INTENT_FAMILIES["SPREAD_DEFENSE"]


def _is_combo_move(move_id: str) -> bool:
    return _norm(move_id) in INTENT_FAMILIES["COMBO"]


def _is_damaging_move(move) -> bool:
    """Check if a move is damaging (base_power > 0).

    Per AGENTS.md, base_power is visible from
    the move's metadata (not inferred).
    """
    if not move:
        return False
    try:
        base_power = getattr(move, "base_power", 0)
    except Exception:
        return False
    if base_power is None:
        return False
    return float(base_power) > 0


def _is_ko_now(damage_pct: Optional[float]) -> bool:
    """A damaging move is KO_NOW if it deals
    >= 50% of target's max HP.
    """
    if damage_pct is None:
        return False
    return float(damage_pct) >= 0.5


def classify_move_intent(
    move_id: str,
    base_power: Optional[float] = None,
    damage_pct: Optional[float] = None,
) -> str:
    """Phase PLANNER-2: classify a move's
    intent_id.

    Args:
        move_id: the move name (e.g. "earthquake",
            "Swords Dance", "wideguard")
        base_power: optional base_power (if
            known); defaults to looking it up
            via _is_damaging_move
        damage_pct: optional damage fraction
            (0.0-1.0) for KO_NOW check

    Returns:
        intent_id (one of: "DAMAGE", "KO_NOW",
        "STATUS", "SETUP", "ANTI_SETUP",
        "PROTECT", "REDIRECT", "SPREAD_DEFENSE",
        "COMBO", "UNKNOWN")
    """
    norm_id = _norm(move_id)
    if not norm_id:
        return "UNKNOWN"
    # Most specific intents first
    if _is_anti_setup_move(norm_id):
        return "ANTI_SETUP"
    if _is_protect_move(norm_id):
        return "PROTECT"
    if _is_redirect_move(norm_id):
        return "REDIRECT"
    if _is_spread_defense_move(norm_id):
        return "SPREAD_DEFENSE"
    if _is_setup_move(norm_id):
        return "SETUP"
    if _is_combo_move(norm_id):
        return "COMBO"
    # Damaging vs status
    if base_power is not None:
        is_damaging = float(base_power) > 0
    else:
        is_damaging = None
    if is_damaging is True:
        if _is_ko_now(damage_pct):
            return "KO_NOW"
        return "DAMAGE"
    if is_damaging is False:
        return "STATUS"
    # Unknown base_power
    return "UNKNOWN"


def classify_order_intent(
    order: Any,
    damage_pct: Optional[float] = None,
) -> str:
    """Phase PLANNER-2: classify a poke-env
    order's intent.

    Args:
        order: a poke-env SingleBattleOrder
        damage_pct: optional damage fraction
            for KO_NOW detection

    Returns:
        intent_id string
    """
    if not order:
        return "UNKNOWN"
    # Check for switch / pass first
    inner = getattr(order, "order", None)
    if inner is None:
        return "PASS"
    # Pokemon switch
    if not hasattr(inner, "id"):
        # Could be a Pokemon instance
        if hasattr(inner, "species"):
            return "SWITCH"
        return "UNKNOWN"
    move_id = getattr(inner, "id", "")
    base_power = getattr(inner, "base_power", None)
    return classify_move_intent(
        move_id,
        base_power=base_power,
        damage_pct=damage_pct,
    )


def get_all_intent_ids() -> list:
    """Return the list of all intent_ids
    (excluding UNKNOWN)."""
    return [
        "DAMAGE", "KO_NOW", "STATUS", "SETUP",
        "ANTI_SETUP", "PROTECT", "REDIRECT",
        "SPREAD_DEFENSE", "COMBO", "SWITCH",
        "PASS",
    ]


def main() -> int:
    """Self-check: print a brief usage note."""
    print("intent_classifier.py — pure function module")
    print("Import classify_move_intent() or "
          "classify_order_intent() to use.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())


# ============================================================================
# PLANNER-IMPL-2: Per-turn IntentDetector
# Pure function: takes a context dict, returns IntentDecision.
# No state, no side effects, no scoring change.
# ============================================================================

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# Intent labels (MVP-only per PLANNER-IMPL-1B)
NO_INTENT = "NO_INTENT"
ANTI_TRICK_ROOM = "ANTI_TRICK_ROOM"
ANTI_TAILWIND = "ANTI_TAILWIND"
ANTI_STAT_BOOST = "ANTI_STAT_BOOST"
SPREAD_DEFENSE = "SPREAD_DEFENSE"

# All MVP intent labels (in priority order for emission)
MVP_INTENTS: Tuple[str, ...] = (
    ANTI_TRICK_ROOM,
    ANTI_TAILWIND,
    ANTI_STAT_BOOST,
    SPREAD_DEFENSE,
)

# Evidence source labels
EVIDENCE_REVEALED_MOVES = "revealed_moves"
EVIDENCE_FIELD_STATE = "field_state"
EVIDENCE_SIDE_CONDITION = "side_condition"
EVIDENCE_OPP_COUNTER = "opp_counter"
EVIDENCE_OPP_PRESSURE = "opp_pressure"
EVIDENCE_NONE = ""

# Route labels (which existing per-move policy is relevant)
ROUTE_NONE = "none"
ROUTE_ANTI_SETUP = "anti_setup_disruption"
ROUTE_SPREAD_DEFENSE = "spread_defense"


@dataclass(frozen=True)
class IntentDecision:
    """Per-turn intent decision. Pure data; no side effects.

    Fields:
        intent: one of MVP_INTENTS or NO_INTENT
        confidence: 0.0 to 1.0
        evidence_source: one of EVIDENCE_*
        matched_moves: tuple of move-id strings that triggered
        routed_to_policy: one of ROUTE_* (which existing policy is relevant)
        opp_pressure: PLANNER-SPREAD-3d — opp spread-move pressure at
            detect time. Stored on the decision so downstream consumers
            (e.g. _planner_spread_defense_eligible Guard 5) can use the
            detector's snapshot instead of re-evaluating the live battle
            state, which may have changed between detect and scoring
            (multiple choose_move calls per turn).
    """
    intent: str
    confidence: float
    evidence_source: str
    matched_moves: Tuple[str, ...]
    routed_to_policy: str
    opp_pressure: bool = False

    @classmethod
    def no_intent(cls) -> "IntentDecision":
        return cls(
            intent=NO_INTENT,
            confidence=0.0,
            evidence_source=EVIDENCE_NONE,
            matched_moves=(),
            routed_to_policy=ROUTE_NONE,
            opp_pressure=False,
        )


class IntentDetector:
    """Per-turn intent detector (pure function).

    Reads visible state (revealed moves, fields, side_conditions,
    opp counters) and emits a single intent label + confidence
    + evidence source + matched moves + routed policy.

    No scoring. No side effects. No state.

    Coverage: 4 MVP intents (ANTI_TRICK_ROOM, ANTI_TAILWIND,
    ANTI_STAT_BOOST, SPREAD_DEFENSE). Deferred intents
    (REDIRECTION_RESPONSE, WEATHER_CONTROL, TERRAIN_CONTROL,
    COMBO_ENABLE) are NOT covered by this detector.

    Configuration:
        min_confidence: minimum confidence to emit a non-NO_INTENT
                       decision (default 0.5).
    """

    # Move dictionaries (lowercase showdown IDs)
    TR_MOVES = frozenset({"trickroom"})
    TW_MOVES = frozenset({"tailwind"})
    STAT_BOOST_MOVES = frozenset({
        "swordsdance", "nastyplot", "dragondance", "calmmind",
        "bulkup", "quiverdance", "shellsmash", "workup",
        "agility", "rockpolish", "coil", "curse", "geomancy",
        "honeclaws", "charge", "growth", "howl", "doubleteam",
        "cosmicpower", "irondefense", "acidarmor", "autotomize",
        "minimize", "shiftgear", "tailglow", "bellydrum",
        "clangoroussoul", "victorydance", "takeheart", "torchsong",
    })
    # SPREAD_MOVES: target = "allAdjacent" / "allAdjacentFoes" / "all" in showdown.
    # Validated against data/moves.ts. See test_planner_spread_moves_fix.py.
    # PLANNER-SPREAD-1B: removed 14 false positives (waterpulse, alluringvoice,
    # drainingkiss, heatcrash, infernalparade, luminacrash, mudshot, mudslap,
    # mysticalfire, powergem, ruination, syrupbomb, temperflare, thundercage,
    # torchsong) that have target="any" or "normal" in showdown, not spread.
    SPREAD_MOVES = frozenset({
        # Common (validated)
        "heatwave", "rockslide", "earthquake", "dazzlinggleam",
        "surf", "eruption", "discharge", "sludgewave", "boomburst",
        "makeitrain", "snarl", "glaciate", "muddywater",
        "bleakwindstorm", "sandsearstorm", "wildboltstorm",
        "springtidestorm", "matchagotcha",
    })

    # Field/side-condition names (both raw and normalized forms)
    TR_FIELD_RAW = "trick_room"  # can appear as "trick_room" in fields
    TR_FIELD_NORM = "trickroom"  # normalized form (no underscore)
    TW_SIDE = "tailwind"         # can appear as "tailwind" in side_conditions
    TW_SIDE_NORM = "tailwind"    # normalized form (no change)

    def __init__(self, min_confidence: float = 0.5):
        self.min_confidence = float(min_confidence)

    def detect(self, ctx: Dict[str, Any]) -> IntentDecision:
        """Detect per-turn intent. Pure function.

        Args:
            ctx: dict with keys:
                - opp_revealed_moves: list of move-id strings
                - fields: list of field-enum name strings
                - side_conditions: list of side-condition name strings
                - opp_used_tr / opp_used_tw / opp_used_stat_boost: bool
                - opp_pressure: bool (for spread defense)
                - active_user_hp_fraction: float (0.0-1.0)
                - expected_to_faint: bool
                - target_already_taunted: bool

        Returns:
            IntentDecision (frozen dataclass).
        """
        if not ctx:
            return IntentDecision.no_intent()

        # Hard guards (suppress all intents)
        if ctx.get("expected_to_faint", False):
            return IntentDecision.no_intent()
        if ctx.get("target_already_taunted", False):
            return IntentDecision.no_intent()
        hp = ctx.get("active_user_hp_fraction", 1.0)
        if hp is not None and hp < 0.25:
            return IntentDecision.no_intent()

        # Check ANTI_TRICK_ROOM (highest priority — TR defines whole match)
        atr = self._detect_anti_trick_room(ctx)
        if atr and atr.confidence >= self.min_confidence:
            return self._with_opp_pressure(atr, ctx)

        # Check ANTI_TAILWIND
        atw = self._detect_anti_tailwind(ctx)
        if atw and atw.confidence >= self.min_confidence:
            return self._with_opp_pressure(atw, ctx)

        # Check ANTI_STAT_BOOST
        asb = self._detect_anti_stat_boost(ctx)
        if asb and asb.confidence >= self.min_confidence:
            return self._with_opp_pressure(asb, ctx)

        # Check SPREAD_DEFENSE
        sd = self._detect_spread_defense(ctx)
        if sd and sd.confidence >= self.min_confidence:
            return self._with_opp_pressure(sd, ctx)

        # No signal
        return IntentDecision.no_intent()

    @staticmethod
    def _with_opp_pressure(
        decision: IntentDecision, ctx: Dict[str, Any]
    ) -> IntentDecision:
        """PLANNER-SPREAD-3d: attach opp_pressure from ctx to the decision.

        Lets downstream consumers (e.g. Guard 5 of
        ``_planner_spread_defense_eligible``) use the detector's
        snapshot instead of re-evaluating the live battle state, which
        can drift between detect time and scoring time when poke-env
        calls ``choose_move`` multiple times per turn.
        """
        import dataclasses
        return dataclasses.replace(
            decision,
            opp_pressure=bool(ctx.get("opp_pressure", False)),
        )

    def _detect_anti_trick_room(self, ctx):
        revealed = self._norm_list(ctx.get("opp_revealed_moves", []))
        fields = self._norm_list(ctx.get("fields", []))

        # 1. Active TR in fields (highest confidence)
        # Check both raw "trick_room" and normalized "trickroom"
        if self.TR_FIELD_NORM in fields or self.TR_FIELD_RAW in fields:
            return IntentDecision(
                intent=ANTI_TRICK_ROOM,
                confidence=0.95,
                evidence_source=EVIDENCE_FIELD_STATE,
                matched_moves=(),
                routed_to_policy=ROUTE_ANTI_SETUP,
            )
        # 2. Revealed TR move
        matches = revealed & self.TR_MOVES
        if matches:
            return IntentDecision(
                intent=ANTI_TRICK_ROOM,
                confidence=0.7,
                evidence_source=EVIDENCE_REVEALED_MOVES,
                matched_moves=tuple(sorted(matches)),
                routed_to_policy=ROUTE_ANTI_SETUP,
            )
        # 3. Counter
        if ctx.get("opp_used_tr", False):
            return IntentDecision(
                intent=ANTI_TRICK_ROOM,
                confidence=0.85,
                evidence_source=EVIDENCE_OPP_COUNTER,
                matched_moves=(),
                routed_to_policy=ROUTE_ANTI_SETUP,
            )
        return None

    def _detect_anti_tailwind(self, ctx):
        revealed = self._norm_list(ctx.get("opp_revealed_moves", []))
        side_conditions = self._norm_list(ctx.get("side_conditions", []))

        # 1. Active TW in side_conditions (highest confidence)
        if self.TW_SIDE_NORM in side_conditions or self.TW_SIDE in side_conditions:
            return IntentDecision(
                intent=ANTI_TAILWIND,
                confidence=0.95,
                evidence_source=EVIDENCE_SIDE_CONDITION,
                matched_moves=(),
                routed_to_policy=ROUTE_ANTI_SETUP,
            )
        # 2. Revealed TW move
        matches = revealed & self.TW_MOVES
        if matches:
            return IntentDecision(
                intent=ANTI_TAILWIND,
                confidence=0.7,
                evidence_source=EVIDENCE_REVEALED_MOVES,
                matched_moves=tuple(sorted(matches)),
                routed_to_policy=ROUTE_ANTI_SETUP,
            )
        # 3. Counter
        if ctx.get("opp_used_tw", False):
            return IntentDecision(
                intent=ANTI_TAILWIND,
                confidence=0.85,
                evidence_source=EVIDENCE_OPP_COUNTER,
                matched_moves=(),
                routed_to_policy=ROUTE_ANTI_SETUP,
            )
        return None

    def _detect_anti_stat_boost(self, ctx):
        revealed = self._norm_list(ctx.get("opp_revealed_moves", []))

        # 1. Revealed stat-boost move
        matches = revealed & self.STAT_BOOST_MOVES
        if matches:
            return IntentDecision(
                intent=ANTI_STAT_BOOST,
                confidence=0.65,
                evidence_source=EVIDENCE_REVEALED_MOVES,
                matched_moves=tuple(sorted(matches)),
                routed_to_policy=ROUTE_ANTI_SETUP,
            )
        # 2. Counter
        if ctx.get("opp_used_stat_boost", False):
            return IntentDecision(
                intent=ANTI_STAT_BOOST,
                confidence=0.85,
                evidence_source=EVIDENCE_OPP_COUNTER,
                matched_moves=(),
                routed_to_policy=ROUTE_ANTI_SETUP,
            )
        return None

    def _detect_spread_defense(self, ctx):
        revealed = self._norm_list(ctx.get("opp_revealed_moves", []))

        # 1. Revealed spread move
        matches = revealed & self.SPREAD_MOVES
        if matches:
            return IntentDecision(
                intent=SPREAD_DEFENSE,
                confidence=0.65,
                evidence_source=EVIDENCE_REVEALED_MOVES,
                matched_moves=tuple(sorted(matches)),
                routed_to_policy=ROUTE_SPREAD_DEFENSE,
            )
        # 2. Opp pressure (audit field)
        if ctx.get("opp_pressure", False):
            return IntentDecision(
                intent=SPREAD_DEFENSE,
                confidence=0.6,
                evidence_source=EVIDENCE_OPP_PRESSURE,
                matched_moves=(),
                routed_to_policy=ROUTE_SPREAD_DEFENSE,
            )
        return None

    @staticmethod
    def _norm_list(items):
        """Normalize a list of strings (lowercase, no spaces/dashes/underscores/apostrophes)."""
        if not items:
            return frozenset()
        out = set()
        for it in items:
            n = (str(it or "").lower()
                 .replace(" ", "").replace("-", "")
                 .replace("_", "").replace("'", ""))
            if n:
                out.add(n)
        return frozenset(out)
