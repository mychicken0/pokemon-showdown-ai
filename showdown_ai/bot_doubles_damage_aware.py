import asyncio
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from poke_env import AccountConfiguration
from poke_env.battle.abstract_battle import AbstractBattle
from poke_env.battle.double_battle import DoubleBattle
from poke_env.battle.move import Move
from poke_env.battle.pokemon import Pokemon
from poke_env.battle.target import Target
from poke_env.player import Player
from poke_env.player.battle_order import (
    BattleOrder,
    DefaultBattleOrder,
    DoubleBattleOrder,
    PassBattleOrder,
    SingleBattleOrder,
)

import ability_rules
import doubles_mechanics as _dm
import meta_model
import random_set_model
from doubles_battle_logger import DoublesBattleLogger
from doubles_decision_audit_logger import DoublesDecisionAuditLogger




# Phase BEHAVIOR-12: Helper to check if an action is an
# attack (non-Protect, non-switch, non-pass) for the
# expected-faint penalty.
_PROTECT_LIKE_MOVE_IDS_B12 = frozenset({
    "protect", "detect", "spikyshield", "kingsshield",
    "banefulbunker", "silktrap", "burningbulwark",
    "obstruct", "maxguard",
})


def _is_attack_action_under_expected_faint(order):
    """Phase BEHAVIOR-12: check if an action is a
    non-Protect, non-switch, non-pass action.

    Used to gate the expected-faint attack penalty.
    Returns True for attack moves only.
    """
    inner = getattr(order, "order", None)
    if inner is None:
        return False
    move_id = getattr(inner, "id", "")
    if not move_id:
        return False
    if move_id.lower() == "pass":
        return False
    # Switch action has a pokemon attribute, not id.
    if hasattr(inner, "pokemon"):
        return False
    # Protect-like action.
    if move_id.lower() in _PROTECT_LIKE_MOVE_IDS_B12:
        return False
    return True


def _is_protect_like_action(order):
    """Phase BEHAVIOR-15: True iff the order's move is
    a protect-like action. Reuses the same move-id
    frozenset as BEHAVIOR-12.
    """
    inner = getattr(order, "order", None)
    if inner is None:
        return False
    move_id = getattr(inner, "id", "")
    if not move_id:
        return False
    return move_id.lower() in _PROTECT_LIKE_MOVE_IDS_B12


def _is_switch_action(order):
    """Phase BEHAVIOR-15: True iff the order is a
    switch action (a SingleBattleOrder whose .order
    is a Pokemon).
    """
    inner = getattr(order, "order", None)
    if inner is None:
        return False
    return hasattr(inner, "pokemon")


def _apply_piecewise_expected_faint_to_slot(
    slot_scores,
    slot_orders,
    expected_faint,
    config,
):
    """Phase BEHAVIOR-15: apply piecewise expected-faint
    attack penalty to a single slot's score map.

    Mutates slot_scores in place. Source of attack_lead
    is the same map (slot_scores) that drives final
    selection and audit, so the post-adjustment map is
    what _compute_joint_scores and v2l1_raw_scores see.

    No-op if:
    - enable_speed_priority_piecewise_expected_faint_policy
      is False
    - enable_speed_priority_awareness is False
    - expected_faint is False

    Otherwise:
    - protect_score = max score of protect-like actions
    - best_attack = max score of non-Protect, non-switch,
      non-pass actions
    - lead = best_attack - protect_score
    - select penalty from configured bands
    - subtract penalty from every attack action in slot

    Note: when this helper runs (gated by
    enable_speed_priority_piecewise_expected_faint_policy=True),
    the BEHAVIOR-12 flat penalty in score_action is
    skipped, so this is the only adjustment applied
    to attack scores in the slot.
    """
    if not expected_faint:
        return
    if not getattr(
        config, "enable_speed_priority_awareness", True
    ):
        return
    if not getattr(
        config,
        "enable_speed_priority_piecewise_expected_faint_policy",
        False,
    ):
        return
    if not slot_orders or not slot_scores:
        return
    # Find protect_score and best_attack.
    protect_score = None
    best_attack = None
    for order in slot_orders:
        score = slot_scores.get(id(order))
        if score is None:
            continue
        if _is_protect_like_action(order):
            if protect_score is None or score > protect_score:
                protect_score = score
            continue
        if _is_switch_action(order):
            continue
        if not _is_attack_action_under_expected_faint(order):
            # pass or unknown — not an attack target
            continue
        if best_attack is None or score > best_attack:
            best_attack = score
    if protect_score is None or best_attack is None:
        return
    lead = best_attack - protect_score
    # Select penalty by band (first match wins).
    high_thr = float(
        getattr(
            config,
            "speed_priority_expected_faint_attack_lead_high",
            500.0,
        )
    )
    mid_thr = float(
        getattr(
            config,
            "speed_priority_expected_faint_attack_lead_mid",
            250.0,
        )
    )
    low_thr = float(
        getattr(
            config,
            "speed_priority_expected_faint_attack_lead_low",
            100.0,
        )
    )
    if lead > high_thr:
        penalty = float(
            getattr(
                config,
                "speed_priority_expected_faint_penalty_high_lead",
                0.0,
            )
        )
    elif lead > mid_thr:
        penalty = float(
            getattr(
                config,
                "speed_priority_expected_faint_penalty_mid_lead",
                75.0,
            )
        )
    elif lead > low_thr:
        penalty = float(
            getattr(
                config,
                "speed_priority_expected_faint_penalty_low_lead",
                200.0,
            )
        )
    else:
        penalty = float(
            getattr(
                config,
                "speed_priority_expected_faint_penalty_close_lead",
                250.0,
            )
        )
    if penalty <= 0.0:
        return
    # Apply to attack actions in this slot.
    for order in slot_orders:
        if not _is_attack_action_under_expected_faint(order):
            continue
        sid = id(order)
        if sid in slot_scores:
            slot_scores[sid] = slot_scores[sid] - penalty



@dataclass
class DoublesDamageAwareConfig:
    # Phase 5: Meta-Aware Opponent Modeling (old, disabled by default)
    enable_meta_opponent_modeling: bool = False
    meta_data_path: str = "data/meta_usage_stats.json"
    meta_move_probability_threshold: float = 0.30
    enable_meta_predicted_ability_soft_rules: bool = False
    meta_predicted_ability_threshold: float = 0.75
    meta_predicted_ability_soft_penalty: float = 0.60
    meta_max_protect_bonus_per_active: float = 30.0
    meta_max_score_delta_per_turn: float = 40.0

    # Phase 5.2: Random-Set-Aware Opponent Modeling (new, disabled by default)
    enable_random_set_opponent_modeling: bool = False
    random_set_data_path: str = "data/random_doubles_set_stats.json"
    random_set_probability_threshold: float = 0.50
    random_set_max_protect_bonus_per_active: float = 25.0
    random_set_max_score_delta_per_turn: float = 35.0

    # Phase 5.3: Variant control flags (all default to Phase 5.2 behavior)
    # -- Rule enable/disable --
    rs_enable_protect_overcommit_penalty: bool = (
        True  # Rule 1: penalize joint double-target when Protect likely
    )
    rs_enable_fakeout_bonus: bool = (
        True  # Rule 2: Protect bonus when opponent likely has Fake Out
    )
    rs_enable_priority_bonus: bool = (
        True  # Rule 3: Protect bonus when opponent has priority + we are low HP
    )
    rs_enable_spread_bonus: bool = (
        True  # Rule 4: Protect bonus when opponent has spread + we are low HP
    )
    rs_enable_setup_targeting: bool = (
        True  # Rule 5: small targeting bonus when opponent likely has setup move
    )
    rs_enable_speed_control_bonus: bool = (
        True  # Rule 6: Protect bonus when opponent has speed control + we are low HP
    )
    # -- Per-rule thresholds (overrides random_set_probability_threshold if > 0) --
    rs_protect_threshold: float = 0.0  # 0 = use global threshold
    rs_fakeout_threshold: float = 0.0
    rs_priority_threshold: float = 0.0
    rs_spread_threshold: float = 0.0
    rs_setup_threshold: float = 0.0
    rs_speed_control_threshold: float = 0.0
    # -- Per-rule deltas (0 = use built-in defaults) --
    rs_protect_overcommit_delta: float = 0.0  # built-in: -12
    rs_fakeout_protect_delta: float = 0.0  # built-in: +18
    rs_priority_protect_delta: float = 0.0  # built-in: +20
    rs_spread_protect_delta: float = 0.0  # built-in: +12
    rs_setup_targeting_delta: float = 0.0  # built-in: +8
    rs_speed_control_protect_delta: float = 0.0  # built-in: +8
    # -- Spread danger HP threshold (separate from priority's 0.20) --
    rs_spread_hp_threshold: float = 0.30
    # -- Close-score gating: only apply targeting bonuses when scores are within gap --
    rs_close_score_gate_enabled: bool = False
    rs_close_score_gate_gap: float = 30.0

    switch_baseline: float = 8.0
    hp_targeting_weight: float = 80.0
    ko_bonus: float = 350.0
    focus_fire_synergy_bonus: float = 80.0
    protect_score: float = 180.0
    spread_bonus: float = 50.0
    ally_hit_penalty: float = 300.0
    enable_protect: bool = True
    enable_fake_out: bool = True
    enable_spread_intelligence: bool = True
    enable_focus_fire_synergy: bool = True
    enable_threat_scoring: bool = False
    threat_targeting_weight: float = 40.0
    enable_speed_threat: bool = True
    enable_spread_threat: bool = True
    enable_setup_threat: bool = True
    enable_threat_tiebreaker: bool = False
    threat_tiebreaker_weight: float = 15.0
    threat_tiebreaker_score_gap: float = 80.0
    threat_only_if_no_ko_available: bool = True
    threat_only_if_no_low_hp_target: bool = True
    low_hp_target_threshold: float = 0.35
    enable_boosted_threat_override: bool = False
    boosted_threat_bonus: float = 120.0
    boosted_override_min_stage: int = 2
    boosted_override_emergency_stage: int = 4
    enable_fakeout_threat_targeting: bool = False
    enable_protect_threat_refinement: bool = False
    enable_ability_awareness: bool = False

    # Phase 6.1: Mechanics-Safe Scoring Fixes
    enable_type_immunity_safety: bool = True
    enable_self_drop_move_penalty: bool = True
    self_drop_repeat_penalty_multiplier: float = 0.35
    self_drop_repeat_penalty_stage: int = -2
    make_it_rain_repeat_penalty_multiplier: float = 0.65

    # Phase 6.1.2: Partial Spread Immunity Efficiency Fixes
    enable_partial_spread_immunity_penalty: bool = True
    partial_spread_immunity_penalty: float = 0.70
    partial_spread_immunity_flat_penalty: float = 35.0
    partial_spread_prefer_single_target_gap: float = 30.0

    # Phase 6.2: Conservative Speed & Priority Awareness / Order Gating
    enable_speed_priority_awareness: bool = True
    speed_priority_protect_only: bool = False
    speed_priority_protect_bonus: float = 60.0
    speed_priority_switch_bonus: float = 25.0
    speed_priority_attack_penalty: float = 45.0
    speed_priority_ko_override: bool = True
    speed_threat_hp_threshold: float = 0.35
    speed_threat_damage_threshold: float = 0.75
    speed_margin_required: float = 1.10
    priority_threat_hp_threshold: float = 0.40
    speed_priority_max_delta_per_action: float = 80.0
    enable_order_aware_overkill: bool = False
    order_aware_overkill_penalty: float = 120.0

    # Phase 6.2.1: Speed/Priority Safety Metric Cleanup & Conservative Tuning
    speed_priority_conditional_priority_weight: float = 0.50
    speed_priority_min_expected_damage_fraction: float = 0.35
    speed_priority_protect_bonus_low: float = 35.0
    speed_priority_protect_bonus_high: float = 60.0
    speed_priority_attack_penalty_low: float = 25.0
    speed_priority_attack_penalty_high: float = 45.0
    speed_priority_use_scaled_penalty: bool = True
    # Phase BEHAVIOR-11: Expected-faint Protect bonus.
    # Applied when the active slot is expected to faint
    # before moving and Protect is a legal candidate.
    # This is in addition to the existing is_threatened
    # bonus. Set to 0.0 to disable (pre-fix behavior).
    speed_priority_protect_bonus_under_expected_faint: float = 200.0
    # Phase BEHAVIOR-12: Expected-faint attack penalty.
    # Applied to non-Protect, non-switch, non-pass actions
    # when the active slot is expected to faint before
    # moving. Set to 0.0 to disable.
    speed_priority_expected_faint_attack_penalty: float = 75.0
    # Phase BEHAVIOR-16: Expected-faint Protect baseline
    # floor. When the active slot is expected to faint
    # before moving AND the candidate is a Protect-like
    # action AND the current Protect score is below the
    # floor, the score is raised to the floor (max-style,
    # not additive). This gives Protect a viable score
    # even when the older is_threatened branch did not
    # activate, so the piecewise attack penalty has
    # something to compete with. Set to 0.0 to disable
    # (revert to pre-BEHAVIOR-16 branch behavior).
    speed_priority_expected_faint_protect_score_floor: float = 240.0
    # Phase BEHAVIOR-15: opt-in piecewise expected-faint
    # attack penalty. When True, the penalty depends on
    # the slot's (best_attack - protect) attack_lead and
    # replaces the BEHAVIOR-12 flat 75.0 only if the
    # legacy single-knob above is 0.0. Default OFF.
    enable_speed_priority_piecewise_expected_faint_policy: bool = False
    # Phase BEHAVIOR-15: piecewise band thresholds on
    # attack_lead = best_attack_score - protect_score
    # in the same slot. The first matching band wins.
    speed_priority_expected_faint_attack_lead_high: float = 500.0
    speed_priority_expected_faint_attack_lead_mid: float = 250.0
    speed_priority_expected_faint_attack_lead_low: float = 100.0
    # Phase BEHAVIOR-15: per-band penalty. Each is
    # independently disable-able by setting to 0.0.
    speed_priority_expected_faint_penalty_high_lead: float = 0.0
    speed_priority_expected_faint_penalty_mid_lead: float = 75.0
    speed_priority_expected_faint_penalty_low_lead: float = 200.0
    speed_priority_expected_faint_penalty_close_lead: float = 250.0

    # Phase 6.3: Ability Hard Safety Only
    enable_ability_hard_safety_only: bool = True
    ability_hard_safety_block_score: float = 0.0
    ability_hard_safety_avoid_absorb: bool = False
    ability_hard_safety_avoid_redirection: bool = False
    ability_hard_safety_ally_spread_safety: bool = False
    ability_hard_safety_direct_absorb_only: bool = True

    # Phase 6.3.5: Deterministic Singleton Ability Safety (disabled by default)
    ability_hard_safety_allow_singleton_deduction: bool = True
    enable_priority_field_hard_safety: bool = False
    safety_block_joint_penalty: float = 1000.0

    # Phase 6.3.6b: Known Ally Redirection Hard Safety (disabled by default)
    enable_known_ally_redirection_hard_safety: bool = False
    known_ally_redirection_block_score: float = 0.0

    # Phase SPREAD-5: Opt-in spread-defense bonus.
    # Adds a bonus to Wide Guard's raw score when
    # ``opp_pressure_state`` is True (any live opp
    # has a revealed spread-move user that is
    # healthy). Default OFF so the production bot
    # behavior is unchanged. Only Wide Guard
    # receives the bonus; Quick Guard and Crafty
    # Shield are NOT included in this phase
    # because the SPREAD-4 evidence base did not
    # surface any Quick Guard / Crafty Shield
    # legal opportunities. Protect also does not
    # receive this bonus (Protect is governed by
    # ``protect_floor`` and the speed-priority
    # floor).
    enable_spread_defense_bonus: bool = False
    wide_guard_spread_pressure_bonus: float = 500.0

    # Phase SETUP-3A: opt-in speed-setup intent bonus.
    # Applies ONLY to Tailwind / Trick Room candidate
    # actions, and ONLY when all 5 guards pass (see
    # score_action). Default OFF. Per AGENTS.md,
    # the default stays OFF until adoption gates pass.
    # Phase SETUP-5: default magnitude updated from
    # 350.0 → 450.0 based on dry-run (SETUP-4)
    # evidence: 0% over-flip at 450, 9.1% over-flip
    # at 550. The 450 value trades a small increase
    # in flips for 0% over-flip rate.
    # Phase SETUP-7A: added KO priority guard
    # (``setup_intent_require_ko_check`` +
    # ``setup_intent_ko_opp_hp_threshold``) to
    # address 12.9% over-select rate observed in
    # SETUP-7 20-pair preview. The guard
    # suppresses the setup bonus when the opp's
    # lowest active HP is below the threshold
    # (default 0.10, conservative). Catches 2 of
    # 4 SETUP-7 over-select cases (the CLEAR
    # cases with opp_hp < 0.05). A higher
    # threshold (e.g. 0.30) was tested but caused
    # -10pp win rate regression (over-suppressed
    # valid setup picks). 0.10 strikes balance.
    enable_setup_intent_policy: bool = False
    setup_intent_speed_setup_bonus: float = 450.0
    setup_intent_max_picks_per_game: int = 3
    setup_intent_min_turn_between_picks: int = 2
    setup_intent_require_survival: bool = True
    setup_intent_require_ko_check: bool = True
    setup_intent_ko_opp_hp_threshold: float = 0.10

    # Phase CONTROL-4B: opt-in anti-setup disruption
    # intent policy. Adds a positive score to
    # Taunt / Encore / Disable / Quash candidates
    # when opp has a visible setup/control/status
    # signal. Per AGENTS.md: visible-only, no
    # species guessing. Default OFF. Bonus magnitude
    # +200.0 chosen via CONTROL-4A dry-run (5-pair
    # probe showed 0% over-flip at all magnitudes,
    # so +200 is the middle ground, lower than
    # setup_intent_speed_setup_bonus = +450).
    enable_anti_setup_disruption_intent: bool = False
    anti_setup_disruption_bonus: float = 200.0
    anti_setup_disruption_max_picks_per_game: int = 2
    anti_setup_disruption_min_turn_between_picks: int = 3
    anti_setup_disruption_require_survival: bool = True
    anti_setup_disruption_min_opp_setup_signal: float = 1.0

    # PLANNER-ANTI-TR: opt-in Anti-Trick Room response.
    # When opp has TR (active or revealed), boost Taunt/Encore/Disable
    # to disrupt the TR setter, and boost damaging moves (KO pressure)
    # to KO before TR expires. TR-specific (not general anti-setup).
    # Default OFF (opt-in).
    enable_anti_trick_room_response: bool = False
    # PLANNER-ANTI-TR v4: tuned bonus. Was 200/100.
    # +200 was insufficient to overcome the bot's damage scoring
    # (Salt Cure 80 BP + Flare Blitz 120 BP ≈ 200 base). With +500,
    # Taunt+Flare Blitz = 10+200+500 = 710 vs Salt Cure+Flare Blitz = 200.
    # Anti-TR now reliably wins in 1v1 comparisons.
    anti_trick_room_response_bonus: float = 500.0  # Taunt/Encore/Disable
    anti_trick_room_ko_bonus: float = 200.0  # Damaging moves vs TR
    anti_trick_room_response_max_picks_per_game: int = 2
    anti_trick_room_response_min_turn_between_picks: int = 3
    anti_trick_room_ko_max_picks_per_game: int = 3
    anti_trick_room_ko_min_turn_between_picks: int = 1
    anti_trick_room_response_require_survival: bool = True

    # Phase CONTROL-PRIORITY-2A: Status-move ability safety.
    # When True, status moves (Taunt, Encore, Disable, etc.)
    # into a target with a known status-blocking ability are
    # blocked (set score to 0 if damage alternative, else -100).
    # This is a NARROW exception to "no full ability awareness":
    # only specific known abilities (Magic Bounce, Good as Gold,
    # Aroma Veil) are tracked, only for status moves, only when
    # revealed. Attacker with Mold Breaker / Teravolt / Turboblaze
    # correctly bypasses (the existing helper bug is fixed).
    #
    # Sub-flags control which abilities are tracked.
    # Default OFF preserves pre-2A behavior (no production change).
    enable_status_move_ability_safety: bool = False
    status_ability_safety_track_magic_bounce: bool = True
    status_ability_safety_track_good_as_gold: bool = True
    status_ability_safety_track_aroma_veil: bool = True
    status_ability_safety_track_aroma_veil_ally: bool = True

    # Phase CONTROL-PRIORITY-2B: Target-aware anti-TR scoring.
    # When True, the anti-TR response bonus is only applied
    # when the target opp's revealed moves include Trick Room.
    # This avoids wasting the bonus on wrong-target Taunts
    # (e.g., bot's Taunt on Gardevoir when Hatterene is the
    # actual TR setter). Revealed-only (no species inference).
    # Default OFF preserves pre-2B behavior.
    # Independent of CONTROL-PRIORITY-2A (status-move ability
    # safety). Both can be enabled independently.
    enable_anti_tr_target_aware_scoring: bool = False

    # PLANNER-IMPL-2: opt-in per-turn intent detector.
    # When True, the bot runs IntentDetector.detect() per
    # turn and writes observational audit fields
    # (planner_intent_label, planner_intent_confidence, etc.).
    # Default OFF. NO scoring change. NO default flip.
    # The detector only LOGS; it does NOT add bonus tables
    # and does NOT trigger existing per-move policies.
    # The existing enable_anti_setup_disruption_intent /
    # enable_spread_defense_bonus / enable_setup_intent_policy
    # flags remain the source of truth for per-move bonuses.
    # See logs/phasePLANNER_IMPL_1B_bonus_table_hardening.md
    # for the full design.
    enable_planner_intent_detector: bool = False
    planner_intent_min_confidence: float = 0.5

    # PLANNER-SPREAD-2: opt-in narrow spread defense scoring.
    # When True, the bot uses the per-turn IntentDetector
    # (enable_planner_intent_detector) decision to boost
    # Wide Guard candidates. Default OFF. NO default flip.
    # Only fires when the intent is SPREAD_DEFENSE with
    # sufficient confidence.
    # Requires:
    #   - enable_planner_intent_detector = True
    #   - intent = SPREAD_DEFENSE
    #   - confidence >= planner_spread_defense_min_confidence
    #   - Wide Guard is the move (per existing normalization)
    #   - opp pressure detected (reuses _slot_in_opp_pressure)
    enable_planner_spread_defense_scoring: bool = False
    planner_spread_defense_wg_bonus: float = 150.0
    # PLANNER-SPREAD-2 + 8A: confidence gate. Default 0.65.
    # PLANNER-SPREAD-8A: tightened from 0.5 to 0.65 to filter the
    # opp_pressure-only branch (0.6 conf) and any borderline decisions.
    # The revealed_moves path returns 0.65, so 0.65 still allows that path.
    planner_spread_defense_min_confidence: float = 0.65
    # Anti-spam: max picks per game, min turns between picks.
    planner_spread_defense_max_picks_per_game: int = 3
    planner_spread_defense_min_turn_between_picks: int = 2
    # PLANNER-SPREAD-8B: partner threat relevance guard. Suppress
    # WG boost when the team is not in actual spread-move danger
    # (both mons at/above the threat threshold). The threshold
    # represents the HP below which a single spread hit is
    # meaningful (e.g., a Rock Slide or Heat Wave at ~30-50% HP).
    # Default 0.7: a mon with >=70% HP can comfortably tank one hit.
    planner_spread_defense_partner_threat_threshold: float = 0.7

    # Phase ACCURACY-2: opt-in hard-safety block
    # for damaging moves targeting self (target=-1)
    # or ally (target=-2). When True, sets v2l1
    # score=0 for any damaging move with self/ally
    # target, so the joint scoring won't pick a
    # wasted-turn option. ACCURACY-1 audit found
    # 45 such cases (100% of zero-damage damaging
    # picks) across SETUP-5/6/6A/7/7A/8 probes.
    # Default OFF; opt-in for safe rollout.
    enable_accuracy_self_ally_block: bool = False

    # Phase 6.3.5: Ground-into-Flying audit fields (generic dual-type)
    # (no config fields needed for Part 0A - the fix is in the scoring logic)

    # Phase 6.4: Known-Type Switch Candidate Ranking (adopted)
    enable_switch_candidate_type_safety: bool = False
    switch_candidate_super_effective_penalty: float = 80.0
    switch_candidate_quad_weak_penalty: float = 160.0
    switch_candidate_double_threat_penalty: float = 100.0
    switch_candidate_resistance_bonus: float = 20.0
    switch_candidate_immunity_bonus: float = 30.0
    switch_candidate_low_hp_penalty: float = 30.0

    # Phase 6.4.2: Revealed-Move One-Ply Defensive Switching (disabled by default)
    enable_revealed_move_switch_interception: bool = False
    revealed_switch_min_threat_multiplier: float = 2.0
    revealed_switch_min_risk_reduction: float = 0.50
    revealed_switch_min_candidate_hp: float = 0.35
    revealed_switch_likely_target_weight: float = 1.00
    revealed_switch_tied_target_weight: float = 0.50
    revealed_switch_ko_threat_bonus: float = 260.0
    revealed_switch_severe_threat_bonus: float = 140.0
    revealed_switch_resist_bonus: float = 45.0
    revealed_switch_immunity_bonus: float = 70.0
    revealed_switch_max_bonus: float = 320.0
    revealed_switch_high_value_action_threshold: float = 250.0
    revealed_switch_ko_action_override: bool = True

    # Phase 6.4.3: Stat-Drop Switch Diagnostics (diagnostic-only, no scoring)
    enable_stat_drop_switch_diagnostics: bool = True
    stat_drop_offensive_stage_threshold: int = -2
    stat_drop_defensive_stage_threshold: int = -2
    stat_drop_speed_stage_threshold: int = -2
    stat_drop_meaningful_damage_fraction: float = 0.25

    # Phase 6.4.7: Conservative Stat-Drop Switch Scoring (disabled by default)
    enable_stat_drop_switch_scoring: bool = False
    stat_drop_switch_offensive_penalty: float = 90.0
    stat_drop_switch_defensive_penalty: float = 35.0
    stat_drop_switch_speed_penalty: float = 20.0
    stat_drop_switch_unproductive_bonus: float = 80.0
    stat_drop_switch_safe_switch_bonus: float = 80.0
    stat_drop_switch_low_hp_block_threshold: float = 0.20
    stat_drop_switch_min_active_hp: float = 0.25
    stat_drop_switch_offensive_stage_threshold: int = -1
    stat_drop_switch_defensive_stage_threshold: int = -2
    stat_drop_switch_speed_stage_threshold: int = -2

    # Phase 6.4.3a.3: Decision Timing Diagnostics (disabled by default)
    enable_decision_timing_diagnostics: bool = False

    # Phase 6.4.4: Forced Switch Replacement Safety (adopted)
    enable_forced_switch_replacement_safety: bool = True
    forced_switch_super_effective_penalty: float = 50.0
    forced_switch_quad_weak_penalty: float = 100.0
    forced_switch_double_threat_penalty: float = 70.0
    forced_switch_resistance_bonus: float = 15.0
    forced_switch_immunity_bonus: float = 20.0
    forced_switch_low_hp_penalty: float = 30.0
    forced_switch_fainted_or_unavailable_penalty: float = 9999.0

    # Phase 6.4.5: Stale Target / Retarget Immunity Safety
    enable_stale_target_after_ally_ko_safety: bool = False
    stale_target_after_ally_ko_penalty: float = 120.0
    stale_target_type_immune_penalty: float = 250.0

    # Phase 6.4.10b: All-Target Immune Spread Joint Penalty
    all_target_immune_spread_joint_penalty: float = 1000.0

    # Phase 6.5: Type Consumption Tracking (Double Shock, Burn Up)
    enable_type_consumption_tracking: bool = True

    # Phase 6.3.8: Support Move Target Hard Safety
    enable_support_move_target_hard_safety: bool = False
    support_move_wrong_side_block_score: float = 0.0
    support_move_allow_only_legal_wrong_side: bool = True

    # Phase 6.3.8d: Narrow ally-heal wrong-side hard safety
    # (production-grade replacement for the broad
    # support-target safety; only blocks Heal Pulse,
    # Floral Healing, Decorate aimed at an opponent).
    enable_ally_heal_wrong_side_hard_safety: bool = False
    ally_heal_wrong_side_block_score: float = 0.0

    # Phase 6.4.9: Voluntary Switch Quality and Sacrifice Awareness
    enable_voluntary_switch_quality_diagnostics: bool = True
    enable_voluntary_switch_quality_scoring: bool = True
    # Phase BI-3A: Mega Evolution legal-order generation
    # capability. Default OFF preserves bit-for-bit pre-BI-3A
    # behavior. When ON, the canonical engine augments
    # ``battle.valid_orders`` with parallel Mega variants
    # (``SingleBattleOrder(..., mega=True)``) for any
    # active mon whose ``battle.can_mega_evolve[slot_idx]``
    # is True and whose selected action is a non-switch
    # move order that does not already carry a mechanic
    # flag. V4a keys distinguish plain vs Mega via the
    # ``mechanic`` field; V2l.1 keys remain 3-tuples for
    # backward compatibility.
    enable_mega_evolution: bool = False
    # Phase BI-3D: Mega damaging-move tie-breaker bonus.
    # Only applies when ``enable_mega_evolution=True`` and
    # the underlying move has ``base_power > 0``. Default
    # 1e-3 is a near-tie breaker: it lets Mega win a
    # genuine tie on joint score, but does not override
    # any real scoring gap (typical joint scores are
    # 50–500). Status moves never get the bonus.
    mega_damaging_bonus: float = 1e-3
    # Phase BI-3M: Mega damaging-move intent bonus. Only
    # applies when ``enable_mega_evolution=True`` and
    # the underlying move has ``base_power > 0``. Default
    # 1.0 makes Mega behavior intentional (not just a
    # tie-breaker) when the feature is opted in: a
    # damaging Mega move beats a same-move plain order on
    # equal scoring by ``mega_intent_bonus``, and can
    # outweigh small plain-vs-Mega gaps on the same
    # scoring axis. Status moves and non-Mega orders
    # receive zero bonus. With ``enable_mega_evolution``
    # default False, this field has no effect on the
    # default policy. To restore pure tie-breaker
    # behavior, set ``mega_intent_bonus=0.0``.
    mega_intent_bonus: float = 1.0
    voluntary_switch_min_risk_reduction: float = 1.0
    voluntary_switch_tempo_penalty: float = 35.0
    voluntary_switch_unsafe_candidate_penalty: float = 120.0
    voluntary_switch_double_threat_penalty: float = 160.0
    voluntary_switch_quad_weak_penalty: float = 180.0
    voluntary_switch_low_hp_candidate_penalty: float = 35.0
    voluntary_switch_repeat_penalty: float = 80.0
    voluntary_switch_sacrifice_hp_threshold: float = 0.15
    voluntary_switch_useful_action_threshold: float = 40.0
    voluntary_switch_high_value_action_threshold: float = 120.0
    voluntary_switch_sacrifice_preserve_bench_bonus: float = 70.0
    # Phase 6.4.9k: Redesigned scoring formula (additive bonus + stay penalty)
    voluntary_switch_risk_reduction_multiplier: float = 0.5
    voluntary_switch_stay_penalty: float = 100.0







def _normalize_ability_name(ability) -> str:
    if not ability:
        return ""
    try:
        return "".join(c for c in str(ability).lower() if c.isalnum())
    except Exception:
        return ""


def normalize_possible_abilities(raw) -> list[str]:
    if not raw:
        return []
    values_to_process = []
    if isinstance(raw, dict):
        values_to_process = list(raw.values())
    elif isinstance(raw, (list, tuple, set)):
        values_to_process = list(raw)
    else:
        values_to_process = [raw]

    norm_possible = []
    for ab in values_to_process:
        if ab:
            if str(ab) in ("0", "1", "H", "h"):
                continue
            n = _normalize_ability_name(ab)
            if n and n not in norm_possible:
                norm_possible.append(n)
    norm_possible.sort()
    return norm_possible


def evaluate_priority_move_legality(
    move,
    attacker,
    intended_target,
    battle,
    config=None,
) -> dict:
    result = {
        "priority": 0,
        "is_priority_move": False,
        "intended_target_grounded": False,
        "psychic_terrain_active": False,
        "known_side_blocking_ability": False,
        "blocked": False,
        "reason": "",
        "resolution_source": "unknown",
        "blocking_ability": "",
        "blocking_ability_source": "",
    }
    if not move or not attacker or not intended_target or not battle:
        return result

    priority = getattr(move, "priority", 0)
    is_status = getattr(move, "category", None)
    if is_status:
        is_status_str = getattr(is_status, "name", str(is_status)).upper()
        if (
            is_status_str == "STATUS"
            and getattr(attacker, "ability", None) == "prankster"
        ):
            priority += 1

    move_type = getattr(move, "type", None)
    if move_type:
        m_type = (
            move_type.name.upper()
            if hasattr(move_type, "name")
            else str(move_type).upper()
        )
        if m_type == "FLYING" and getattr(attacker, "ability", None) == "galewings":
            if getattr(attacker, "current_hp_fraction", 0) == 1.0:
                priority += 1

    result["priority"] = priority
    result["is_priority_move"] = priority > 0

    if priority <= 0:
        return result

    psychic_terrain = False
    if hasattr(battle, "fields") and battle.fields:
        for f in battle.fields:
            f_str = f.name.lower() if hasattr(f, "name") else str(f).lower()
            f_str = f_str.replace("_", "").replace(" ", "")
            if "psychicterrain" in f_str:
                psychic_terrain = True
                break
    result["psychic_terrain_active"] = psychic_terrain

    target_grounded = False
    try:
        target_grounded = battle.is_grounded(intended_target)
    except Exception:
        pass
    result["intended_target_grounded"] = target_grounded

    blocking_ability = ""
    blocking_source = ""
    for opp in battle.opponent_active_pokemon:
        if opp and not getattr(opp, "fainted", False):
            res = resolve_known_ability(opp, battle, config)
            opp_ability = res["ability"]
            if (
                opp_ability in ("armortail", "queenlymajesty", "dazzling")
                and not res["is_currently_suppressed"]
            ):
                blocking_ability = opp_ability
                blocking_source = res["source"]
                break

    if blocking_ability:
        result["known_side_blocking_ability"] = True
        result["blocking_ability"] = blocking_ability
        result["blocking_ability_source"] = blocking_source

    is_opponent = intended_target in battle.opponent_active_pokemon
    if is_opponent:
        if blocking_ability:
            result["blocked"] = True
            result["reason"] = f"priority_blocked_by_ability_{blocking_ability}"
            result["resolution_source"] = blocking_source
        elif psychic_terrain and target_grounded:
            result["blocked"] = True
            result["reason"] = "priority_blocked_by_psychic_terrain"
            result["resolution_source"] = "field"

    return result


def priority_move_is_field_blocked(
    move,
    attacker,
    target,
    battle,
    config=None,
) -> tuple[bool, str]:
    if not move or not attacker or not target or not battle:
        return False, ""
    res = evaluate_priority_move_legality(move, attacker, target, battle, config)
    if res["blocked"]:
        return True, res["reason"]
    return False, ""


def _pokemon_replay_names(pokemon) -> set[str]:
    names = set()
    for attr in ("ident", "name", "species"):
        value = getattr(pokemon, attr, None)
        if value:
            normalized = "".join(c for c in str(value).lower() if c.isalnum())
            if normalized:
                names.add(normalized)
            if ":" in str(value):
                suffix = "".join(
                    c for c in str(value).split(":", 1)[1].lower() if c.isalnum()
                )
                if suffix:
                    names.add(suffix)
    return names


def _pokemon_is_on_our_team(pokemon, battle) -> bool:
    if not pokemon or not battle:
        return False
    for collection_name in ("active_pokemon", "team"):
        collection = getattr(battle, collection_name, None)
        values = (
            collection.values() if isinstance(collection, dict) else (collection or [])
        )
        if any(mon is pokemon for mon in values if mon):
            return True
    return False


def get_known_ability(pokemon, battle=None) -> str | None:
    if not pokemon:
        return None
    try:
        ability = _normalize_ability_name(getattr(pokemon, "ability", None))
        replay_data = (
            getattr(battle, "_replay_data", None) if battle is not None else None
        )
        if (
            battle is None
            or replay_data is None
            or getattr(battle, "battle_tag", None) == "test"
            or _pokemon_is_on_our_team(pokemon, battle)
        ):
            return ability or None

        # Opponent Pokemon objects can contain request-derived ability data. Treat it
        # as known only after the protocol log explicitly reveals that ability.
        names = _pokemon_replay_names(pokemon)
        if not names:
            return None
        for raw_event in replay_data:
            event = [str(part).strip() for part in raw_event if str(part).strip()]
            if len(event) < 2:
                continue

            # Determine who this event's ability belongs to
            # Default to the primary subject in event[1]
            # NOTE: event[0] is the empty prefix from the "|" split.
            # Protocol events like "-ability" appear at event[1].
            subject_str = event[1] if len(event) > 1 else ""

            # Check if there is an '[of] ...' element
            of_target = None
            for part in event:
                if part.startswith("[of]"):
                    of_target = part[4:].strip()
                    break
                elif part.startswith("of]"):
                    of_target = part[3:].strip()
                    break

            if of_target:
                subject_str = of_target

            subject_norm = "".join(c for c in subject_str.lower() if c.isalnum())
            matches_pokemon = any(
                name == subject_norm or subject_norm.endswith(name) for name in names
            )
            if not matches_pokemon:
                continue

            revealed_ab = None
            # Check -ability event
            # Raw format: ["", "-ability", "pokemon", "Ability Name"]
            # After empty-string filtering: ["-ability", "pokemon", "Ability Name"]
            # The "-ability" marker may be at event[0] or event[1] depending on
            # whether the empty prefix was filtered. Check both positions.
            ability_idx = None
            for _ai, _ev in enumerate(event):
                if _ev == "-ability":
                    ability_idx = _ai
                    break
            if ability_idx is not None and ability_idx + 2 < len(event):
                revealed_ab = _normalize_ability_name(event[ability_idx + 2])

            # Check [from] ability: in -heal or -damage events
            # e.g., ["", "-heal", "pokemon", "100/100", "[from] ability: Storm Drain"]
            if not revealed_ab:
                for part in event:
                    lower = part.lower()
                    if "ability:" in lower:
                        revealed_ab = _normalize_ability_name(
                            lower.split("ability:", 1)[1]
                        )
                        break

            if revealed_ab:
                return revealed_ab
        return None
    except Exception:
        return None


def attacker_ignores_target_ability(attacker, battle=None) -> bool:
    if not attacker:
        return False
    try:
        ab = get_known_ability(attacker, battle)
        return ab in ("moldbreaker", "teravolt", "turboblaze")
    except Exception:
        return False


WATER_REDIRECT_ABILITIES = {"stormdrain"}
ELECTRIC_REDIRECT_ABILITIES = {"lightningrod"}


def ally_redirects_our_single_target_move(
    move,
    attacker,
    ally,
    battle=None,
) -> tuple[bool, str]:
    if not move or not attacker or not ally:
        return False, ""
    if getattr(ally, "fainted", False):
        return False, ""
    if getattr(move, "base_power", 0) <= 0:
        return False, ""

    m_type = get_effective_move_type(move, attacker, battle)

    ally_ability = get_known_ability(ally, battle)
    if not ally_ability:
        return False, ""

    if attacker_ignores_target_ability(attacker, battle):
        return False, ""

    if ally_ability in WATER_REDIRECT_ABILITIES and m_type == "WATER":
        return True, "ally_stormdrain_redirects_water"
    if ally_ability in ELECTRIC_REDIRECT_ABILITIES and m_type == "ELECTRIC":
        return True, "ally_lightningrod_redirects_electric"

    return False, ""


def is_single_target_move(move, order=None) -> bool:
    if not move:
        return False
    target_pos = None
    if order is not None:
        target_pos = getattr(order, "move_target", None)
    if target_pos in (1, 2):
        return True
    if target_pos == 0:
        return False
    target_str = getattr(move, "target", "")
    if isinstance(target_str, str):
        ts = target_str.lower().replace(" ", "").replace("_", "").replace("-", "")
        if ts in ("normal", "any", "adjacentally"):
            return True
    return False


def classify_known_ally_redirection_audit(
    is_selected_blocked: bool,
    candidate_blocked_exists: bool,
    safe_alternative_exists: bool,
) -> dict:
    """Pure helper: classify known-ally-redirection audit states."""
    return {
        "avoidable_selected": bool(is_selected_blocked and safe_alternative_exists),
        "only_legal": bool(is_selected_blocked and not safe_alternative_exists),
        "avoided": bool(candidate_blocked_exists and not is_selected_blocked),
    }


def update_known_ally_redirection_repeat_state(
    key: tuple,
    battle_tag: str,
    current_turn: int,
    streak_state: dict,
) -> dict:
    """Pure helper: update cross-turn repeat detection state."""
    result = {"repeat_detected": False, "streak_state": dict(streak_state)}
    battle_map = result["streak_state"].setdefault(battle_tag, {})
    prev = battle_map.get(key)
    if prev and prev.get("turn", 0) < current_turn:
        result["repeat_detected"] = True
        battle_map[key] = {"turn": current_turn, "streak": prev.get("streak", 0) + 1}
    else:
        battle_map[key] = {"turn": current_turn, "streak": 1}
    return result


def classify_known_ally_redirection_error(
    selected: bool,
    known_before_decision: bool,
    is_our_action: bool,
) -> tuple[bool, bool]:
    """Pure helper: classify our/opponent error for known ally redirection.

    Returns (our_error, opponent_error).
    - Our selected error: selected + known_before + our action
    - Reveal-after-decision: neither error
    - Opponent error: observational only (not set for our own slots)
    - Our action slot never becomes opponent error
    """
    if not is_our_action:
        return (False, False)
    if selected and known_before_decision:
        return (True, False)
    return (False, False)


# ponytail: Protocol/replay scan helpers and
# identity helpers extracted to
# doubles_engine.protocol (Phase Ponytail
# Refactor Step 4B). The shim re-exports the
# helpers under their original names so existing
# call sites and tests keep working. Behavior
# is preserved bit-for-bit.
from doubles_engine.protocol import (
    find_protocol_ability_reveal_turn,
    _normalize_protocol_token,
    _get_pokemon_by_ident,
    _get_battle_pokemon_identity,
)

# ponytail: Audit metadata assembly helper
# extracted to doubles_engine.audit_metadata
# (Phase Ponytail Refactor Step 7B). The shim
# re-exports the assembly function so the
# audit-dict construction at the
# ``audit_logger.log_turn_decision`` call site
# can delegate to a module function. Behavior
# is preserved bit-for-bit.
from doubles_engine.audit_metadata import (
    assemble_v2l1_metadata,
    assemble_partial_spread_state,
    assemble_shared_engine_metadata,
    assemble_switch_counterfactual_slot,
)
# ponytail: Dynamic-type absorb candidate
# classification helper extracted to
# doubles_engine.type_absorb (Phase Ponytail
# Refactor Step 4B). The shim re-exports the
# helper and the allowlist frozenset under
# their original names so existing call sites
# and tests keep working. Behavior is preserved
# bit-for-bit.
from doubles_engine.type_absorb import (
    classify_dynamic_type_absorb_candidates,
    _ALLOWED_DYNAMIC_ABSORB_REASONS,
)

# ponytail: Field state, weather, terrain, gravity,
# and form/type consumption helpers extracted
# to doubles_engine.field_state (Phase Ponytail
# Refactor Step 4A). The shim re-exports the
# helpers and module-level state under their
# original names so existing call sites and
# tests keep working. Behavior is preserved
# bit-for-bit.
from doubles_engine.field_state import (
    _TYPE_CONSUMING_MOVES,
    DYNAMIC_TYPE_MOVES,
    _pokemon_forms,
    _ident_to_obj,
    _replay_cursors,
    is_gravity_active,
    get_max_type_threat,
    _normalize_form_name,
    _normalize_ident,
    record_observed_form_change,
    get_observed_form,
    clear_observed_form_state,
    _scan_replay_for_form_changes,
    _scan_replay_for_type_consumption,
    is_type_consumed,
)

# ponytail: Effective-move-type resolution
# helpers extracted to doubles_engine.types
# (Phase Ponytail Refactor Step 4A). The shim
# re-exports the helpers under their original
# names so existing call sites and tests keep
# working. Behavior is preserved bit-for-bit.
from doubles_engine.types import (
    resolve_effective_move_type,
    _get_declared_move_type,
    get_effective_move_type,
)

# ponytail: Support-target intent classification and
# wrong-side block helpers extracted to
# doubles_engine.support_targets (Phase Ponytail
# Refactor Step 3). The shim re-exports the
# constants and helpers under their original
# names so existing call sites and tests keep
# working. Behavior is preserved bit-for-bit.
from doubles_engine.support_targets import (
    _SUPPORT_ALLY_BENEFICIAL_SINGLE,
    _SUPPORT_ALLY_BENEFICIAL_SINGLE_REASON,
    _SUPPORT_ALLY_BENEFICIAL_ALLIES,
    _SUPPORT_ALLY_BENEFICIAL_ALLIES_REASON,
    _SUPPORT_ALLY_BENEFICIAL_TEAM,
    _SUPPORT_ALLY_BENEFICIAL_TEAM_REASON,
    _SUPPORT_OPPONENT_DISRUPTIVE_SINGLE,
    _SUPPORT_OPPONENT_DISRUPTIVE_REASON,
    _SUPPORT_EITHER_MOVE_IDS,
    _SUPPORT_EITHER_REASON,
    _NARROW_ALLY_HEAL_MOVE_IDS,
    _NARROW_ALLY_HEAL_REASON,
    _POLLEN_PUFF_MOVE_ID,
    classify_support_move_target_intent,
    build_support_target_candidate_table,
    build_narrow_ally_heal_candidate_table,
    resolve_order_target_side,
    support_move_wrong_side_block,
    narrow_ally_heal_wrong_side_block,
)

# ponytail: Ability mechanics wrappers extracted to
# doubles_engine.mechanics (Phase Ponytail Refactor
# Step 2b). The shim re-exports them under their
# original names so existing call sites and tests
# keep working. Behavior is preserved bit-for-bit.
from doubles_engine.mechanics import (
    resolve_known_ability,
    ability_hard_blocks_move,
    direct_known_absorb_blocks_move,
    ability_redirects_single_target_move,
    ally_ability_makes_safe,
    _ability_block_enabled,
)

# ponytail: action identity / legal-order telemetry
# helpers extracted to doubles_engine.action_keys
# (Phase Ponytail Refactor Step 1). The shim
# re-exports them under their original private
# names so existing call sites and tests keep
# working. Behavior is preserved bit-for-bit.
from doubles_engine.action_keys import (
    _order_action_key,
    _order_mechanic_label,
    _order_action_key_with_mechanic,
    _legal_action_keys_for_slot,
    _legal_action_keys_with_mechanic_for_slot,
    _raw_score_map_for_slot,
    _raw_score_map_with_mechanic_for_slot,
    _safety_block_map_for_slot,
    _final_action_keys_from_joint,
    _final_action_keys_with_mechanic_from_joint,
    _selected_joint_key,
    _selected_joint_key_with_mechanic,
    classify_only_legal,
    _augment_valid_orders_with_mega,
)

# ponytail: Canonical safety precomputation
# helper extracted to doubles_engine.safety_blocks
# (Phase Ponytail Refactor Step 5). The shim
# re-exports the 8-tuple return function under
# its original name so existing call sites and
# tests keep working. Behavior is preserved
# bit-for-bit, including narrow ally-heal
# integration and ally-redirect integration.
from doubles_engine.safety_blocks import (
    _compute_order_safety_blocks,
)

def get_spread_target_effectiveness_with_ability(
    move, attacker, opponent_targets, config, battle=None
) -> dict:
    total_targets = 0
    immune_targets = 0
    damaged_targets = 0
    immune_target_names = []
    damaged_target_names = []

    for opp in opponent_targets:
        if opp:
            total_targets += 1
            is_immune = False
            immune_flag, _ = is_type_immune(move, attacker, opp, battle)
            if immune_flag:
                is_immune = True
            else:
                if hasattr(opp, "damage_multiplier"):
                    try:
                        mult = opp.damage_multiplier(move)
                        if mult == 0.0:
                            is_immune = True
                    except Exception:
                        pass

            if not is_immune and config and config.enable_ability_hard_safety_only:
                blocks, reason = ability_hard_blocks_move(
                    move, attacker, opp, battle, config=config
                )
                if blocks and _ability_block_enabled(config, reason):
                    is_immune = True

            if is_immune:
                immune_targets += 1
                immune_target_names.append(opp.species)
            else:
                damaged_targets += 1
                damaged_target_names.append(opp.species)

    all_targets_immune = total_targets > 0 and immune_targets == total_targets
    partial_immunity = total_targets > 1 and immune_targets > 0 and damaged_targets > 0

    return {
        "total_targets": total_targets,
        "immune_targets": immune_targets,
        "damaged_targets": damaged_targets,
        "immune_target_names": immune_target_names,
        "damaged_target_names": damaged_target_names,
        "all_targets_immune": all_targets_immune,
        "partial_immunity": partial_immunity,
    }


def get_spread_ability_partial_immunity(
    move, attacker, opponent_targets, config, battle=None
) -> bool:
    if not opponent_targets or not move:
        return False
    total_targets = 0
    ability_blocked_targets = 0
    non_ability_blocked_targets = 0
    for opp in opponent_targets:
        if opp:
            total_targets += 1
            blocks_flag, reason = ability_hard_blocks_move(
                move, attacker, opp, battle, config=config
            )
            if blocks_flag and _ability_block_enabled(config, reason):
                ability_blocked_targets += 1
            else:
                non_ability_blocked_targets += 1
    return (
        total_targets > 1
        and ability_blocked_targets > 0
        and non_ability_blocked_targets > 0
    )


def is_known_absorb_ability(ability_name: str) -> bool:
    if not ability_name:
        return False
    normalized = "".join(c for c in str(ability_name).lower() if c.isalnum())
    return normalized in (
        "waterabsorb",
        "stormdrain",
        "dryskin",
        "voltabsorb",
        "motordrive",
        "lightningrod",
        "flashfire",
        "wellbakedbody",
        "sapsipper",
    )


def is_alternative_safe_damaging_predicate(
    alt_order, active_mon, battle, config=None
) -> bool:
    """Pure safety predicate: returns True if the candidate order is safe to use.

    Safety means:
    - Is a damaging move (base_power > 0)
    - Targets an active (non-fainted) opponent for single-target moves
    - Not type-immune
    - Not blocked by a known ability
    - Not redirected into a known absorb ability
    - For spread moves: at least one opponent can be hit

    NOTE: Does NOT call score_action. Use slot_scores for the canonical score.
    """
    if not alt_order or not isinstance(alt_order.order, Move):
        return False
    alt_move = alt_order.order
    if getattr(alt_move, "base_power", 0) <= 0:
        return False

    if alt_order.move_target in (1, 2):
        target_pos = alt_order.move_target
        alt_target = battle.opponent_active_pokemon[target_pos - 1]
        if not alt_target or getattr(alt_target, "fainted", False):
            return False

        # Is not type-immune
        type_imm, _ = is_type_immune(alt_move, active_mon, alt_target, battle)
        if type_imm:
            return False

        # Is not blocked by a known ability
        blocked, _ = ability_hard_blocks_move(
            alt_move, active_mon, alt_target, battle, config=config
        )
        if blocked:
            return False

        # Is not redirected into a known absorb ability
        redirects, _ = ability_redirects_single_target_move(
            alt_move, alt_target, battle.opponent_active_pokemon, active_mon, battle
        )
        if redirects:
            red_target = None
            for opp in battle.opponent_active_pokemon:
                if opp and opp != alt_target and not getattr(opp, "fainted", False):
                    opp_ability = get_known_ability(opp, battle)
                    if opp_ability in ("stormdrain", "lightningrod"):
                        red_target = opp
                        break
            if red_target and is_known_absorb_ability(
                get_known_ability(red_target, battle)
            ):
                return False

    elif is_opponent_spread_move(alt_move, alt_order):
        opponents = [
            opp
            for opp in battle.opponent_active_pokemon
            if opp and not getattr(opp, "fainted", False)
        ]
        if not opponents:
            return False
        any_hit = False
        for opp in opponents:
            opp_blocks, _ = ability_hard_blocks_move(
                alt_move, active_mon, opp, battle, config=config
            )
            opp_type_imm, _ = is_type_immune(alt_move, active_mon, opp, battle)
            if not opp_blocks and not opp_type_imm:
                any_hit = True
                break
        if not any_hit:
            return False
    else:
        return False

    return True


def is_alternative_safe_damaging(
    alt_order, idx, active_mon, battle, config, player
) -> tuple[bool, float]:
    """Compatibility wrapper retained for any callers outside choose_move.
    Uses score_action to compute the score. For choose_move, prefer the
    canonical slot_scores path to avoid re-evaluation side effects.
    """
    if not is_alternative_safe_damaging_predicate(
        alt_order, active_mon, battle, config=config
    ):
        return False, 0.0
    alt_score = player.score_action(
        alt_order,
        idx,
        battle,
        with_tiebreaker=False,
        is_selected=False,
        in_spread_check=True,
        config=config,
    )
    if alt_score <= 0.0:
        return False, 0.0
    return True, alt_score


def is_type_immune(move, attacker, target, battle=None) -> tuple[bool, str]:
    """Return ``(is_immune, reason)`` for a move against a target.

    Behaviour-preserving wrapper over the shared
    ``doubles_mechanics.resolve_type_immunity`` helper.
    The reason string format
    ``"[Mechanics] type immunity: <type> vs <defender types> -> score 0"``
    is kept identical so the existing audit-field consumers
    and tests do not need to change.

    The wrapper:

    1. Extracts the target type list and attacker ability
       from the poke-env objects.
    2. Lets the shared module resolve the effective move
       type, the type-chart lookup, the typed-ability block,
       and the Scrappy / Mind's Eye / Mold Breaker /
       Thousand Arrows / Gravity / Smack Down exceptions.

    The wrapper does NOT contain any immunity table or
    exception formula.
    """
    try:
        m_type = get_effective_move_type(move, attacker, battle)
        if not m_type:
            return False, ""

        t_types = _extract_target_types(target)
        if not t_types:
            return False, ""

        a_ability_norm = _extract_ability(attacker)
        t_ability_norm = _extract_ability(target)

        move_id = _extract_move_id(move)

        # Grounded state (Thousand Arrows / Gravity / Smack
        # Down / Ingrain) is owned by the shared module.
        grounded = _dm.resolve_extra_grounded(
            move, target, battle=battle, move_id=move_id,
        )
        # Mind's Eye / Scrappy bypass is also owned by the
        # shared module.

        # Call the shared helper. The helper's reason
        # string is the canonical type-immunity reason.
        is_immune, shared_reason = _dm.resolve_type_immunity(
            move=move,
            attacker=attacker,
            target=target,
            attacker_ability=a_ability_norm,
            target_ability=t_ability_norm,
            target_grounded=grounded,
            move_type=m_type,
            move_id=move_id,
        )
        if not is_immune:
            return False, ""
        # Preserve the legacy reason string format.
        if shared_reason and shared_reason.startswith("type_immunity:"):
            # Re-format for legacy audit compatibility.
            types_str = ", ".join(t_types)
            return (
                True,
                f"[Mechanics] type immunity: {m_type} vs "
                f"{types_str} -> score 0",
            )
        if shared_reason:
            return True, shared_reason
        return (
            True,
            f"[Mechanics] type immunity: {m_type} vs "
            f"{', '.join(t_types)} -> score 0",
        )
    except Exception:
        return False, ""


def _extract_target_types(target: Any) -> List[str]:
    """Extract upper-case defender type list from a poke-env
    target object. Shared with the V2k.1 bot wrappers; the
    shared ``doubles_mechanics`` module owns a parallel
    helper but the bot's poke-env adapter stays here to
    avoid an import cycle.
    """
    if target is None:
        return []
    out: List[str] = []
    types_attr = getattr(target, "types", None)
    if types_attr:
        for t in types_attr:
            if t is None:
                continue
            if hasattr(t, "name"):
                out.append(str(t.name).upper().strip())
            elif isinstance(t, str):
                out.append(t.upper().strip())
            else:
                out.append(str(t).upper().strip())
        if out:
            return out
    for attr in ("type_1", "type_2"):
        v = getattr(target, attr, None)
        if v is None:
            continue
        v_str = v.name if hasattr(v, "name") else str(v)
        if v_str:
            out.append(v_str.upper().strip())
    return out


def _extract_ability(pokemon: Any) -> Optional[str]:
    """Extract a normalized ability string from a poke-env
    object. ``None`` if the ability is unknown or empty.
    """
    if pokemon is None:
        return None
    raw = getattr(pokemon, "ability", None)
    if raw is None:
        return None
    if hasattr(raw, "name"):
        raw = raw.name
    if not isinstance(raw, str):
        return None
    if not raw.strip():
        return None
    return raw.strip()


def _extract_move_id(move: Any) -> str:
    """Extract a normalized move id from a poke-env move or
    string. Empty string if the move is unknown.
    """
    if move is None:
        return ""
    raw_id = getattr(move, "id", "")
    if isinstance(raw_id, str) and raw_id:
        return _dm.normalize_id(raw_id)
    if isinstance(move, str):
        return _dm.normalize_id(move)
    return ""


def get_self_stat_drop_penalty(
    attacker, move, expected_ko=False, has_reasonable_alternative=True
) -> tuple[float, str]:
    try:
        # Normalize move ID
        move_id = ""
        if move is not None:
            if hasattr(move, "id") and move.id:
                move_id = (
                    move.id.lower()
                    .replace(" ", "")
                    .replace("-", "")
                    .replace("_", "")
                    .strip()
                )
            elif isinstance(move, str):
                move_id = (
                    move.lower()
                    .replace(" ", "")
                    .replace("-", "")
                    .replace("_", "")
                    .strip()
                )

        HARSH_DROP_MOVES = {
            "dracometeor",
            "overheat",
            "leafstorm",
            "fleurcannon",
            "psychoboost",
        }
        LIGHT_DROP_MOVES = {"makeitrain"}

        if move_id not in HARSH_DROP_MOVES and move_id not in LIGHT_DROP_MOVES:
            return 1.0, ""

        # Get attacker's Sp. Atk boost safely
        spa_boost = 0
        if attacker is not None and hasattr(attacker, "boosts") and attacker.boosts:
            spa_boost = attacker.boosts.get("spa", 0)

        # If Sp. Atk is not severely dropped (not <= -2), no penalty
        if spa_boost > -2:
            return 1.0, ""

        # If expected KO, skip penalty
        if expected_ko:
            return 1.0, ""

        # If no reasonable alternative damaging move exists, allow the move
        if not has_reasonable_alternative:
            return 1.0, ""

        # Apply penalty
        if move_id in HARSH_DROP_MOVES:
            return (
                0.35,
                f"[Mechanics] self stat drop penalty for {move_id}: SpA={spa_boost} -> multiplier 0.35",
            )
        elif move_id in LIGHT_DROP_MOVES:
            return (
                0.65,
                f"[Mechanics] self stat drop penalty for {move_id}: SpA={spa_boost} -> multiplier 0.65",
            )

        return 1.0, ""
    except Exception:
        return 1.0, ""


# Phase SPREAD-2: Spread-defense move allowlist.
# Wide Guard protects the user and ally from any
# opposing move that targets multiple Pokemon
# (target = "allAdjacentFoes"). Quick Guard does
# the same for priority moves. Crafty Shield
# protects the user and ally from status moves.
# These are priority=3 in ``get_move_priority``
# but were NOT in the 8-move protect-like
# allowlist. The audit/analyzer gap is sealed in
# SPREAD-2 by adding per-slot legal/selected
# fields. Pure observation; no scoring change.
_SPREAD_DEFENSE_MOVE_IDS = frozenset({
    "wideguard",
    "quickguard",
    "craftyshield",
})


def _normalize_move_id_for_spread_defense(move_id: str) -> str:
    if not isinstance(move_id, str):
        return ""
    return (
        move_id.lower()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .strip()
    )


def is_spread_defense_move(move_id: str) -> bool:
    """Phase SPREAD-2: True if ``move_id`` is a
    spread-defense counter move (Wide Guard / Quick
    Guard / Crafty Shield). Pure observation; used
    for audit wiring, not scoring.
    """
    norm = _normalize_move_id_for_spread_defense(move_id)
    return norm in _SPREAD_DEFENSE_MOVE_IDS


def compute_opp_pressure_state_for_battle(battle) -> bool:
    """Phase SPREAD-5: True if any live opp has
    a revealed spread-move user that is healthy
    enough to use it (HP >= 0.5). Mirrors the
    SPREAD-2 audit ``opp_pressure_state`` logic
    but is callable from ``score_action`` where
    the per-turn flag is not yet available.
    """
    try:
        live_opps = [
            opp
            for opp in (getattr(battle, "opponent_active_pokemon", None) or [])
            if opp and not getattr(opp, "fainted", False)
        ]
        if not live_opps:
            return False
        for opp in live_opps:
            opp_hp = getattr(opp, "current_hp_fraction", 1.0)
            if opp_hp is None or opp_hp < 0.5:
                continue
            opp_moves_dict = getattr(opp, "moves", {}) or {}
            if not opp_moves_dict:
                continue
            for opp_move in opp_moves_dict.values():
                if opp_move is None:
                    continue
                try:
                    if is_opponent_spread_move(opp_move, None):
                        return True
                except Exception:
                    continue
    except Exception:
        return False
    return False


def is_opponent_only_spread_move(move, order=None) -> bool:
    try:
        if move is not None:
            # Check target string directly
            target_str = getattr(move, "target", "")
            if isinstance(target_str, str):
                target_str_clean = (
                    target_str.lower()
                    .replace(" ", "")
                    .replace("_", "")
                    .replace("-", "")
                )
                if target_str_clean == "alladjacentfoes":
                    return True
            # Check deduced target
            target_type = getattr(move, "deduced_target", None)
            if target_type is not None:
                target_str = str(target_type).upper()
                if "ALLADJACENTFOES" in target_str or "ALL_ADJACENT_FOES" in target_str:
                    return True

            # Known opponent-only spread move list fallback
            move_id = getattr(move, "id", "")
            if isinstance(move_id, str):
                move_id_clean = (
                    move_id.lower().replace(" ", "").replace("-", "").replace("_", "")
                )
                KNOWN_OPPONENT_ONLY_SPREAD = {
                    "hypervoice",
                    "rockslide",
                    "heatwave",
                    "blizzard",
                    "clangsour",
                    "clangingscales",
                    "dazzlinggleam",
                    "muddywater",
                    "snarl",
                    "expandforce",
                    "makeitrain",
                    "glare",
                    "icywind",
                    "acidspray",
                    "strugglebug",
                    "waterspout",
                    "eruption",
                    "dragondarts",
                }
                if move_id_clean in KNOWN_OPPONENT_ONLY_SPREAD:
                    return True
        return False
    except Exception:
        return False


def is_ally_hitting_spread_move(move, order=None) -> bool:
    try:
        if move is not None:
            # Check target string directly
            target_str = getattr(move, "target", "")
            if isinstance(target_str, str):
                target_str_clean = (
                    target_str.lower()
                    .replace(" ", "")
                    .replace("_", "")
                    .replace("-", "")
                )
                if target_str_clean in ("alladjacent", "all"):
                    return True
            # Check deduced target
            target_type = getattr(move, "deduced_target", None)
            if target_type is not None:
                target_str = str(target_type).upper()
                if (
                    any(x in target_str for x in ("ALLADJACENT", "ALL_ADJACENT", "ALL"))
                    and "FOES" not in target_str
                ):
                    return True

            # Known ally-hitting spread move list fallback
            move_id = getattr(move, "id", "")
            if isinstance(move_id, str):
                move_id_clean = (
                    move_id.lower().replace(" ", "").replace("-", "").replace("_", "")
                )
                KNOWN_ALLY_HITTING_SPREAD = {
                    "earthquake",
                    "surf",
                    "discharge",
                    "mindblown",
                    "teeterdance",
                }
                if move_id_clean in KNOWN_ALLY_HITTING_SPREAD:
                    return True
        return False
    except Exception:
        return False


def is_opponent_spread_move(move, order=None) -> bool:
    try:
        if is_opponent_only_spread_move(move, order) or is_ally_hitting_spread_move(
            move, order
        ):
            return True

        # Check order target position fallback
        if order is not None:
            t_pos = getattr(order, "move_target", None)
            if t_pos == 0:
                return True

        # Generic check for target or deduced target just in case
        if move is not None:
            target_type = getattr(move, "deduced_target", None)
            if target_type is not None:
                target_str = str(target_type).upper()
                if "ALL" in target_str or "ADJACENT" in target_str:
                    return True
            target_str = getattr(move, "target", "")
            if isinstance(target_str, str):
                target_str_clean = (
                    target_str.lower()
                    .replace(" ", "")
                    .replace("_", "")
                    .replace("-", "")
                )
                if target_str_clean in ("alladjacent", "alladjacentfoes", "all"):
                    return True

        return False
    except Exception:
        return False


def get_spread_target_effectiveness(
    move, attacker, opponent_targets, battle=None
) -> dict:
    total_targets = 0
    immune_targets = 0
    damaged_targets = 0
    immune_target_names = []
    damaged_target_names = []

    # We only evaluate active opponent targets
    for opp in opponent_targets:
        if opp:
            total_targets += 1
            is_immune = False
            immune_flag, _ = is_type_immune(move, attacker, opp, battle)
            if immune_flag:
                is_immune = True
            else:
                if hasattr(opp, "damage_multiplier"):
                    try:
                        mult = opp.damage_multiplier(move)
                        if mult == 0.0:
                            is_immune = True
                    except Exception:
                        pass

            if is_immune:
                immune_targets += 1
                immune_target_names.append(opp.species)
            else:
                damaged_targets += 1
                damaged_target_names.append(opp.species)

    all_targets_immune = total_targets > 0 and immune_targets == total_targets
    partial_immunity = total_targets > 1 and immune_targets > 0 and damaged_targets > 0

    return {
        "total_targets": total_targets,
        "immune_targets": immune_targets,
        "damaged_targets": damaged_targets,
        "immune_target_names": immune_target_names,
        "damaged_target_names": damaged_target_names,
        "all_targets_immune": all_targets_immune,
        "partial_immunity": partial_immunity,
    }


# ponytail: Switch candidate type safety
# helper extracted to doubles_engine.switch_safety
# (Phase Ponytail Refactor Step 6B). The shim
# re-exports the helper under its original name
# so existing call sites and tests keep working.
# Behavior is preserved bit-for-bit.
from doubles_engine.switch_safety import (
    evaluate_switch_candidate_type_safety,
)

# ponytail: Forced switch replacement safety
# helper extracted to doubles_engine.forced_switch
# (Phase Ponytail Refactor Step 6A). The shim
# re-exports the helper under its original name
# so existing call sites and tests keep working.
# Behavior is preserved bit-for-bit.
from doubles_engine.forced_switch import (
    evaluate_forced_switch_replacement_safety,
)

# ponytail: Voluntary switch quality helper
# extracted to doubles_engine.voluntary_switch
# (Phase Ponytail Refactor Step 6E). The shim
# re-exports the helper under its original name
# so existing call sites and tests keep working.
# Behavior is preserved bit-for-bit.
from doubles_engine.voluntary_switch import (
    evaluate_voluntary_switch_quality,
)

# ponytail: Stat-drop scoring and switch-pressure
# helpers extracted to doubles_engine.stat_drops
# (Phase Ponytail Refactor Step 6D). The shim
# re-exports the helpers under their original
# names so existing call sites and tests keep
# working. Behavior is preserved bit-for-bit.
from doubles_engine.stat_drops import (
    summarize_negative_boosts,
    classify_stat_drop_severity,
    evaluate_stat_drop_switch_pressure,
)

# ponytail: Revealed-move switch interception
# helpers extracted to doubles_engine.revealed_switch
# (Phase Ponytail Refactor Step 6C). The shim
# re-exports the helpers under their original
# names so existing call sites and tests keep
# working. Behavior is preserved bit-for-bit.
from doubles_engine.revealed_switch import (
    get_revealed_damaging_moves,
    evaluate_revealed_move_incoming_risk,
    estimate_revealed_move_target_likelihood,
    summarize_revealed_move_threats,
    evaluate_revealed_move_switch_interception,
)

def select_best_joint_from_score_maps(
    battle,
    config,
    joint_orders,
    slot_0_scores,
    slot_1_scores,
    direct_absorb_blocked=None,
    safety_blocked=None,
    ally_redirect_blocked=None,
    support_target_blocked=None,
) -> tuple:
    """Pure selection from explicit score maps without recomputing action scores.

    Returns (best_joint_order, best_score, score_1, score_2) or
    (None, 0, 0, 0) if no joint orders.

    Applies only safety-block penalties. Synergy rules (KO, focus fire,
    overkill) are intentionally excluded because both ON and OFF paths
    share the same synergy behavior when comparing counterfactual selections.
    """
    if not joint_orders:
        return (None, 0.0, 0.0, 0.0)

    da = direct_absorb_blocked or {}
    sb = safety_blocked or {}
    ar = ally_redirect_blocked or {}
    st = support_target_blocked or {}

    scored = []
    for joint_order in joint_orders:
        first = joint_order.first_order
        second = joint_order.second_order

        s1 = slot_0_scores.get(id(first), 0.0) if first else 0.0
        s2 = slot_1_scores.get(id(second), 0.0) if second else 0.0
        js = s1 + s2

        blocked = any(
            [
                da.get(id(first), False) if first else False,
                da.get(id(second), False) if second else False,
                sb.get(id(first), False) if first else False,
                sb.get(id(second), False) if second else False,
                ar.get(id(first), False) if first else False,
                ar.get(id(second), False) if second else False,
                st.get(id(first), False) if first else False,
                st.get(id(second), False) if second else False,
            ]
        )

        if blocked:
            from dataclasses import dataclass

            pen = getattr(config, "safety_block_joint_penalty", 1000.0)
            js -= pen

        scored.append((joint_order, js, s1, s2))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0] if scored else (None, 0.0, 0.0, 0.0)


def build_voluntary_switch_candidate_table(
    active_mon,
    switch_orders,
    slot_idx,
    battle,
    best_stay_score,
    config,
    player=None,
    voluntary_switch_history=None,
) -> list:
    """Build a complete candidate table of all voluntary switch candidates.

    Each candidate is evaluated exactly once.  Returns a list of dict rows
    with all quality metrics plus adjusted_switch_score.

    Score convention:
      raw_switch_score = switch_baseline (config)
      score_adjustment = tempo_penalty - risk_reduction_bonus + candidate_penalty
                         + repeat_penalty + sacrifice_penalty + stay_value_penalty
      adjusted_switch_score = raw_switch_score - score_adjustment

      score_adjustment > 0 means the switch is penalised.
    """
    rows = []
    if not active_mon or not switch_orders:
        return rows
    if slot_idx < len(battle.force_switch) and battle.force_switch[slot_idx]:
        return rows  # voluntary only

    cfg = config or DoublesDamageAwareConfig()
    switch_baseline = getattr(cfg, "switch_baseline", 8.0)

    # Track consecutive switch
    key = (getattr(battle, "battle_tag", ""), slot_idx)
    # Build full history from the switch_history dict if available
    history = {}
    if voluntary_switch_history is not None:
        history = voluntary_switch_history.get(key, {})

    # Determine if this is a repeat
    is_repeat = False
    if history.get("last_switch_turn") is not None:
        current_turn = getattr(battle, "turn", 0)
        if current_turn - history.get("last_switch_turn") == 1:
            is_repeat = True

    for idx, order in enumerate(switch_orders):
        if not order or not isinstance(order.order, Pokemon):
            continue
        candidate = order.order
        candidate_action_key = _order_action_key(order)
        eval_result = evaluate_voluntary_switch_quality(
            active_mon,
            candidate,
            slot_idx,
            battle,
            best_stay_score,
            cfg,
            player=player,
        )

        raw_score = switch_baseline
        adj = eval_result["score_adjustment"]
        tempo = eval_result["tempo_penalty"]
        cand_penalty = eval_result["candidate_penalty"]
        repeat = 0.0
        if is_repeat:
            repeat = getattr(cfg, "voluntary_switch_repeat_penalty", 80.0)

        # Rebuild adjustment including sacrifice, stay value, and repeat
        risk_reduction = eval_result["risk_reduction"]
        # Phase 6.4.9k: Redesigned additive formula
        # Switch score = switch_baseline + risk_reduction_bonus - penalties
        # where risk_reduction_bonus = risk_reduction * best_stay_score * multiplier
        risk_reduction_multiplier = getattr(
            cfg, "voluntary_switch_risk_reduction_multiplier", 0.5
        )
        risk_reduction_bonus = (
            risk_reduction * best_stay_score * risk_reduction_multiplier
            if risk_reduction > 0
            else 0.0
        )

        stay_value_penalty = 0.0
        if eval_result["active_has_high_value_action"]:
            stay_value_penalty = 50.0  # Fixed penalty - active has great moves
        elif eval_result["active_has_useful_action"]:
            stay_value_penalty = 25.0  # Fixed penalty - active has decent moves

        sacrifice_penalty = 0.0
        if eval_result["active_low_hp"] and eval_result["active_has_useful_action"]:
            sacrifice_penalty = 30.0  # Fixed penalty to preserve bench

        # Additive formula: baseline + bonus - penalties
        total_penalties = (
            tempo + cand_penalty + repeat + stay_value_penalty + sacrifice_penalty
        )
        adjusted = switch_baseline + risk_reduction_bonus - total_penalties

        # Store full_adj for diagnostic compatibility
        full_adj = total_penalties - risk_reduction_bonus

        is_safer = eval_result["switch_improves_position"]

        row = {
            "candidate_index": idx,
            "candidate_action_key": candidate_action_key,
            "species": getattr(candidate, "species", ""),
            "hp": getattr(candidate, "current_hp_fraction", 1.0),
            "raw_switch_score": raw_score,
            "adjusted_switch_score": max(
                adjusted, -200.0
            ),  # allow negative for differentiation
            "active_risk": eval_result["active_risk"],
            "candidate_risk": eval_result["candidate_risk"],
            "risk_reduction": risk_reduction,
            "tempo_penalty": tempo,
            "candidate_penalty": cand_penalty,
            "repeat_penalty": repeat,
            "sacrifice_penalty": sacrifice_penalty,
            "stay_value_penalty": stay_value_penalty,
            "score_adjustment": full_adj,
            "double_threat": eval_result["candidate_double_threat"],
            "quad_weak": eval_result["candidate_quad_weak"],
            "low_hp": eval_result["candidate_low_hp"],
            "switch_improves_position": is_safer,
            "safer_than_active": is_safer,
            "best_stay_score": best_stay_score,
            "active_has_useful_action": eval_result["active_has_useful_action"],
            "active_has_high_value_action": eval_result["active_has_high_value_action"],
            "sacrifice_preferred": eval_result["sacrifice_preferred"],
            "reason_codes": list(eval_result["reason_codes"]),
            "selected": False,
        }
        rows.append(row)

    return rows

    # Calculate bonus
    bonus = 0.0
    if result["likely_lethal"] or any(r.get("likely_ko_pressure", False) for r in []):
        bonus += config.revealed_switch_ko_threat_bonus
    elif result["super_effective_threat"]:
        bonus += config.revealed_switch_severe_threat_bonus

    for move_id in result["moves_made_immune"]:
        bonus += config.revealed_switch_immunity_bonus
    for move_id in result["moves_resisted"]:
        bonus += config.revealed_switch_resist_bonus

    bonus = min(bonus, config.revealed_switch_max_bonus)
    result["proposed_score_bonus"] = bonus
    result["interception_valid"] = True

    return result


def detect_stale_target_after_ally_ko_risk(
    first_order,
    second_order,
    first_expected_ko: bool,
    first_target,
    second_target,
    visible_opponents,
    battle=None,
    config=None,
) -> dict:
    result = {
        "risk": False,
        "reason": "",
        "fallback_target_species": "",
        "fallback_target_type_immune": False,
        "fallback_target_no_effect": False,
        "first_move_id": "",
        "second_move_id": "",
        "first_target_species": "",
        "second_target_species": "",
    }

    if not first_order or not second_order:
        return result
    if not hasattr(first_order, "order") or not hasattr(second_order, "order"):
        return result
    first_move = getattr(first_order, "order", None)
    second_move = getattr(second_order, "order", None)
    if not first_move or not second_move:
        return result
    if (
        getattr(first_move, "base_power", 0) <= 0
        or getattr(second_move, "base_power", 0) <= 0
    ):
        return result

    first_target_pos = getattr(first_order, "move_target", None)
    second_target_pos = getattr(second_order, "move_target", None)

    if first_target_pos not in (1, 2) or second_target_pos not in (1, 2):
        return result

    if first_target_pos != second_target_pos:
        return result

    if not first_target or not second_target:
        return result

    first_move_id = getattr(first_move, "id", "")
    second_move_id = getattr(second_move, "id", "")
    first_target_species = getattr(first_target, "species", "")
    second_target_species = getattr(second_target, "species", "")

    result["first_move_id"] = first_move_id
    result["second_move_id"] = second_move_id
    result["first_target_species"] = first_target_species
    result["second_target_species"] = second_target_species

    if not first_expected_ko:
        return result

    fallback_idx = 1 if first_target_pos == 1 else 0
    fallback_target = None
    if visible_opponents and len(visible_opponents) > fallback_idx:
        fallback_target = visible_opponents[fallback_idx]

    if not fallback_target or getattr(fallback_target, "fainted", False):
        result["risk"] = True
        result["reason"] = "no_fallback_target_after_ally_ko"
        result["fallback_target_no_effect"] = True
        return result

    fallback_species = getattr(fallback_target, "species", "")
    result["fallback_target_species"] = fallback_species

    immune, reason = is_type_immune(second_move, None, fallback_target, battle)
    if immune:
        result["risk"] = True
        result["reason"] = f"fallback_type_immune:{reason}"
        result["fallback_target_type_immune"] = True
        return result

    result["risk"] = True
    result["reason"] = "stale_target_after_ally_ko"
    return result


class DoublesDamageAwarePlayer(Player):
    def __init__(
        self, *args, verbose=True, logger=None, audit_logger=None, config=None, **kwargs
    ):
        if "battle_format" not in kwargs:
            kwargs["battle_format"] = "gen9randomdoublesbattle"
        super().__init__(*args, **kwargs)
        self.verbose = verbose
        self.custom_logger = logger
        self.audit_logger = audit_logger
        # V2l — runtime mode boundary. The canonical
        # engine defaults to ``"random_doubles"``.
        # Subclasses (e.g. the VGC runtime) override
        # this in their ``__init__`` via
        # ``self._runtime_mode = "vgc_selected_four"``.
        # The audit logger reads this for every turn's
        # record so the parity inspector can prove
        # which runtime mode was active. The base
        # class sets the boundary in ``__init__``
        # BEFORE the ``config`` setter is invoked, so
        # the setter does not overwrite the runtime
        # mode after the subclass sets it.
        self._runtime_mode = "random_doubles"
        self._concrete_player_class = type(self).__name__
        self._selected_four = None
        self._lead_2 = None
        self._back_2 = None
        self._preview_policy = None
        # V2l.1 — execution-derived invocation marker.
        # Each call to ``choose_move`` writes a fresh
        # invocation id and clears the per-turn scoring
        # snapshot. The audit logger reads these fields
        # so ``shared_engine_used`` is a real
        # execution-derived bit, NOT a hardcoded value.
        self._v2l1_invocation_id = None
        self._v2l1_invocation_count = 0
        self._v2l1_invocation_status = "idle"
        self._v2l1_legal_keys_slot0 = []
        self._v2l1_legal_keys_slot1 = []
        self._v2l1_raw_scores_slot0 = {}
        self._v2l1_raw_scores_slot1 = {}
        self._v2l1_safety_blocks_slot0 = {}
        self._v2l1_safety_blocks_slot1 = {}
        self._v2l1_selected_joint_key = None
        self._v2l1_final_keys = []
        # Phase BI-1: V4a mechanic-aware audit attrs.
        # Populated per turn right before the audit
        # call. Data-assembly only; no scoring change.
        self._v4a_legal_keys_slot0 = []
        self._v4a_legal_keys_slot1 = []
        self._v4a_selected_joint_key = None
        self._v4a_final_keys = []
        # ``self.config = ...`` MUST come after the
        # V2l attribute initialization, otherwise the
        # config setter would overwrite them.
        self.config = config or DoublesDamageAwareConfig()
        self._active_config_override = None

    @property
    def config(self):
        if (
            hasattr(self, "_active_config_override")
            and self._active_config_override is not None
        ):
            return self._active_config_override
        return self._real_config

    @config.setter
    def config(self, val):
        self._real_config = val

        # Phase 2 tracking state
        self.last_protect_turn = {}
        self.active_turns = {}
        self.battle_metrics = {}

        # Phase 3 tracking state
        self.tiebreaker_activations_by_battle = {}
        self.boosted_override_activations_by_battle = {}
        self._base_scores_cache = {0: {}, 1: {}}

        # Phase 4 tracking state (per battle tag)
        self.ability_blocks_avoided_by_battle = {}
        self.ability_absorbs_avoided_by_battle = {}
        self.ability_redirects_avoided_by_battle = {}
        self.ally_safe_spreads_by_battle = {}
        self.ability_multipliers_applied_by_battle = {}

        # Phase 6.1 tracking state (per battle tag)
        self.draco_penalties_applied_by_battle = {}
        self.make_it_rain_penalties_applied_by_battle = {}

        # Phase 5 tracking state (per battle tag)
        self.meta_engine = None
        if self.config.enable_meta_opponent_modeling:
            self.meta_engine = meta_model.MetaQueryEngine(self.config.meta_data_path)

        self.meta_predictions_used_by_battle = {}
        self.meta_protect_predictions_by_battle = {}
        self.meta_fakeout_predictions_by_battle = {}
        self.meta_priority_predictions_by_battle = {}
        self.meta_spread_predictions_by_battle = {}
        self.meta_setup_predictions_by_battle = {}
        self.meta_coverage_predictions_by_battle = {}
        self.meta_ability_soft_penalties_by_battle = {}

        self.meta_species_found_by_battle = {}
        self.meta_species_missing_by_battle = {}

        self.candidate_meta_predictions_by_battle = {}
        self.selected_meta_predictions_by_battle = {}
        self.total_meta_score_delta_by_battle = {}

        # Phase 5.2: Random-Set-Aware tracking state (per battle tag)
        self.random_set_engine = None
        if self.config.enable_random_set_opponent_modeling:
            try:
                self.random_set_engine = random_set_model.RandomSetQueryEngine(
                    self.config.random_set_data_path
                )
                if self.random_set_engine.species_count() == 0:
                    print(
                        "[RandomSet] WARNING: Database loaded but is empty. Disabling random-set modeling."
                    )
                    self.random_set_engine = None
            except Exception as e:
                print(
                    f"[RandomSet] WARNING: Failed to load database ({e}). Disabling random-set modeling."
                )
                self.random_set_engine = None

        self.rs_predictions_used_by_battle = {}
        self.rs_protect_predictions_by_battle = {}
        self.rs_fakeout_predictions_by_battle = {}
        self.rs_priority_predictions_by_battle = {}
        self.rs_spread_predictions_by_battle = {}
        self.rs_setup_predictions_by_battle = {}
        self.rs_speed_control_predictions_by_battle = {}
        self.rs_candidate_predictions_by_battle = {}
        self.rs_selected_predictions_by_battle = {}
        self.rs_score_delta_by_battle = {}
        self.rs_species_found_by_battle = {}
        self.rs_species_missing_by_battle = {}

        # Phase 6.1.2 tracking state (per battle tag)
        self.partial_immune_spread_by_battle = {}
        self.partial_ability_immune_spread_by_battle = {}
        self.efficient_partial_spread_by_battle = {}
        self.inefficient_partial_spread_by_battle = {}
        self.immune_target_species_by_battle = {}
        self.damaged_target_species_by_battle = {}
        self.best_single_alternative_by_battle = {}

        # Phase 6.2 tracking state (per battle tag)
        self._speed_priority_threatened = {}
        self._faster_opponents = {}
        self._priority_opponents = {}
        self._speed_priority_protect_bonus_applied = {}
        self._speed_priority_attack_penalty_applied = {}
        self._speed_priority_switch_bonus_applied = {}
        self._protected_due_to_speed_priority = {}
        self._expected_to_faint_before_moving = {}
        # Phase BEHAVIOR-17: per-turn diagnostic for the
        # Protect floor path audit. Populated in
        # score_action (the wrapper) for every Protect-
        # like action. Read at the end of choose_move
        # and passed to the audit logger. Reset at the
        # start of each choose_move call. Keyed by
        # battle_tag -> slot_idx -> list of action-level
        # debug dicts.
        self._b17_protect_floor_debug = {}
        self._order_aware_overkill_penalty_applied = {}

        # Phase SETUP-3A: per-battle state for the
        # setup-intent anti-spam guards.
        #   _setup_intent_picks_per_game: battle_tag ->
        #     count of setup-move picks in this game
        #   _setup_intent_last_pick_turn: battle_tag ->
        #     last turn a setup move was picked
        self._setup_intent_picks_per_game = {}
        self._setup_intent_last_pick_turn = {}

        # Phase CONTROL-4B: per-battle state for the
        # anti-setup disruption intent anti-spam guards.
        #   _anti_setup_disrupt_picks_per_game: battle_tag ->
        #     count of anti-setup disruption picks in
        #     this game
        #   _anti_setup_disrupt_last_pick_turn: battle_tag ->
        #     last turn an anti-setup disruption move
        #     was picked
        self._anti_setup_disrupt_picks_per_game = {}
        self._anti_setup_disrupt_last_pick_turn = {}

        # Phase 6.3 tracking state (per battle tag)
        self._ability_hard_block_avoided = {}
        self._ability_immune_move_selected = {}
        self._ground_into_levitate_selected = {}
        self._ability_block_reason = {}
        self._ability_blocked_target_species = {}
        self._ability_blocked_target_ability = {}
        self._ally_ability_safe_spread = {}
        self._ability_redirection_avoided = {}

        # Phase 6.3.3 tracking state (per battle tag)
        self._direct_absorb_hard_block_avoided = {}
        self._direct_absorb_immune_move_selected = {}
        self._direct_absorb_block_reason = {}
        self._direct_absorb_target_species = {}
        self._direct_absorb_target_ability = {}
        self._direct_absorb_only_legal_action = {}

        # Phase 6.3.6b: Known Ally Redirection tracking state (per battle tag)
        self._known_ally_redirect_selected = {}
        self._known_ally_redirect_reason = {}
        self._known_ally_redirect_ally_species = {}
        self._known_ally_redirect_ally_ability = {}
        self._known_ally_redirect_move_id = {}
        self._known_ally_redirect_known_before = {}

        # Phase 6.3.8: Support Move Target Hard Safety tracking state (per battle tag)
        self._support_target_wrong_side_blocked = {}
        self._support_target_block_reason = {}

        # Phase 6.4.9: Voluntary switch history (per battle tag, per slot)
        # Stores dicts with keys: last_switch_turn, last_switch_out_identity, last_switch_in_identity
        self._voluntary_switch_history = {}
        # Phase 6.4.9: Voluntary switch quality per turn (slot -> latest evaluated)
        self._voluntary_switch_quality_data = {}
        self._voluntary_switch_adjustment_applied = {}
        self._voluntary_switch_penalized = {}
        self._voluntary_switch_selection_changed = {}
        self._voluntary_switch_joint_selection_changed = {}
        self._voluntary_switch_counterfactual_actions = {}

        # Phase 6.5: Type consumption tracking (Double Shock, Burn Up)
        # Key: battle_tag -> dict of pokemon_identity -> set of consumed type names
        self._consumed_types = {}

        # Phase 6.3.2 streak tracking state (per battle tag)
        # Key: battle_tag -> dict of attacker_ident -> {"move": ..., "effective_target": ..., "reason": ..., "turn": ..., "streak": int}
        # Using attacker identity (not slot index) so slot switches don't break streaks.
        self._absorb_streak_state = {}

        # Phase 6.4 tracking state (per battle tag)
        self._switch_candidate_safety_data = {}  # battle_tag -> {slot_idx: safety_dict}

        # Phase 6.4.5: Stale target tracking state (per battle tag)
        self._stale_target_selected = {}
        self._stale_target_same_target_expected_ko = {}
        self._stale_target_caused_no_effect = {}
        self._stale_target_caused_type_immune = {}
        self._stale_target_first_slot = {}
        self._stale_target_first_move = {}
        self._stale_target_first_target = {}
        self._stale_target_second_slot = {}
        self._stale_target_second_move = {}
        self._stale_target_second_intended_target = {}
        self._stale_target_fallback_target = {}
        self._stale_target_reason = {}

    def safe_get_joint_message(self, joint_order) -> str:
        if not joint_order:
            return ""
        try:
            msg = joint_order.message
            if msg is not None:
                return str(msg)
        except Exception:
            pass
        parts = []
        for order in [
            getattr(joint_order, "first_order", None),
            getattr(joint_order, "second_order", None),
        ]:
            if order is not None:
                try:
                    msg = order.message
                    if msg is not None:
                        parts.append(str(msg))
                    else:
                        try:
                            s = str(order)
                            parts.append(s if s is not None else repr(order))
                        except Exception:
                            parts.append(repr(order))
                except Exception:
                    try:
                        s = str(order)
                        parts.append(s if s is not None else repr(order))
                    except Exception:
                        parts.append(repr(order))
        if len(parts) == 2:
            first_msg = parts[0]
            second_msg = parts[1]
            if second_msg.startswith("default ") and len(second_msg) > 8:
                second_msg = second_msg[8:]
            return f"{first_msg}, {second_msg}"
        elif len(parts) == 1:
            return parts[0]
        return ""

    def _compute_joint_scores(
        self,
        battle: DoubleBattle,
        config,
        joint_orders,
        slot_0_scores: dict,
        slot_1_scores: dict,
        _direct_absorb_blocked: dict,
        _safety_blocked: dict,
        _ally_redirect_blocked: dict = None,
        _support_target_blocked: dict = None,
        _narrow_blocked: dict = None,
    ) -> list:
        """Canonical pure-capable joint scoring and ranking.

        Returns list of (joint_order, joint_score, score_1, score_2) sorted
        descending by joint_score.  Deterministic tie-break preserves
        insertion order of joint_orders.
        """
        scored_joint_orders = []
        for joint_order in joint_orders:
            first = joint_order.first_order
            second = joint_order.second_order

            score_1 = slot_0_scores.get(id(first), 0.0) if first else 0.0
            score_2 = slot_1_scores.get(id(second), 0.0) if second else 0.0
            joint_score = score_1 + score_2

            first_blocked = (
                _direct_absorb_blocked.get(id(first), False) if first else False
            )
            second_blocked = (
                _direct_absorb_blocked.get(id(second), False) if second else False
            )
            first_safety_blocked = (
                _safety_blocked.get(id(first), False) if first else False
            )
            second_safety_blocked = (
                _safety_blocked.get(id(second), False) if second else False
            )
            ar_map = _ally_redirect_blocked or {}
            first_ar_blocked = ar_map.get(id(first), False) if first else False
            second_ar_blocked = ar_map.get(id(second), False) if second else False
            st_map = _support_target_blocked or {}
            first_st_blocked = st_map.get(id(first), False) if first else False
            second_st_blocked = st_map.get(id(second), False) if second else False
            nb_map = _narrow_blocked or {}
            first_nb_blocked = nb_map.get(id(first), False) if first else False
            second_nb_blocked = nb_map.get(id(second), False) if second else False
            either_blocked = (
                first_blocked
                or second_blocked
                or first_safety_blocked
                or second_safety_blocked
                or first_ar_blocked
                or second_ar_blocked
                or first_st_blocked
                or second_st_blocked
                or first_nb_blocked
                or second_nb_blocked
            )

            if not either_blocked:
                if isinstance(first.order, Move) and isinstance(second.order, Move):
                    if (
                        first.move_target == second.move_target
                        and first.move_target in (1, 2)
                    ):
                        target_opp = battle.opponent_active_pokemon[
                            first.move_target - 1
                        ]
                        if target_opp:
                            ko_1 = self.check_move_will_ko(
                                first.order,
                                battle.active_pokemon[0],
                                target_opp,
                                battle,
                                config=config,
                            )
                            ko_2 = self.check_move_will_ko(
                                second.order,
                                battle.active_pokemon[1],
                                target_opp,
                                battle,
                                config=config,
                            )
                            opp_hp_fraction = getattr(
                                target_opp, "current_hp_fraction", 1.0
                            )

                            if (
                                (ko_1 and ko_2)
                                or (ko_1 or ko_2)
                                and opp_hp_fraction < 0.15
                                or opp_hp_fraction < 0.08
                            ):
                                allow_double = False
                                if config.enable_threat_scoring:
                                    threat_score = self.score_opponent_threat(
                                        target_opp, battle
                                    )
                                    if threat_score >= 0.50:
                                        allow_double = True
                                if not allow_double:
                                    joint_score -= 250.0

                            if (
                                config.enable_meta_opponent_modeling
                                and self.meta_engine
                            ):
                                t_species = target_opp.species
                                t_revealed = list(target_opp.moves.keys())
                                likely_protect, prob, reason = (
                                    self.meta_engine.likely_has_protect(
                                        t_species,
                                        t_revealed,
                                        threshold=config.meta_move_probability_threshold,
                                    )
                                )
                                if likely_protect:
                                    joint_score -= 15.0

                            if (
                                config.enable_random_set_opponent_modeling
                                and self.random_set_engine
                                and config.rs_enable_protect_overcommit_penalty
                            ):
                                t_species = target_opp.species
                                t_revealed = list(target_opp.moves.keys())
                                prot_thr = (
                                    config.rs_protect_threshold
                                    if config.rs_protect_threshold > 0.0
                                    else config.random_set_probability_threshold
                                )
                                likely_protect, prob, _ = (
                                    self.random_set_engine.likely_has_protect(
                                        t_species, t_revealed, threshold=prot_thr
                                    )
                                )
                                if likely_protect:
                                    overcommit_delta = (
                                        config.rs_protect_overcommit_delta
                                        if config.rs_protect_overcommit_delta > 0.0
                                        else 12.0
                                    )
                                    joint_score -= overcommit_delta

                if config.enable_order_aware_overkill:
                    if self.selected_target_will_be_koed_before_second_action(
                        first, second, battle, config=config
                    ):
                        joint_score -= config.order_aware_overkill_penalty

                if isinstance(first.order, Move) and isinstance(second.order, Move):
                    if (
                        first.move_target == second.move_target
                        and first.move_target in (1, 2)
                    ):
                        target_opp = battle.opponent_active_pokemon[
                            first.move_target - 1
                        ]
                        if target_opp:
                            # Stale target after ally KO safety (Phase 6.4.5)
                            if config.enable_stale_target_after_ally_ko_safety:
                                if not self.is_spread_move(
                                    first.order
                                ) and not self.is_spread_move(second.order):
                                    if (
                                        getattr(first.order, "base_power", 0) > 0
                                        and getattr(second.order, "base_power", 0) > 0
                                    ):
                                        ko_1 = self.check_move_will_ko(
                                            first.order,
                                            battle.active_pokemon[0],
                                            target_opp,
                                            battle,
                                            config=config,
                                        )
                                        if ko_1:
                                            visible_opps = [
                                                o
                                                for o in battle.opponent_active_pokemon
                                                if o
                                                and not getattr(o, "fainted", False)
                                            ]
                                            stale = (
                                                detect_stale_target_after_ally_ko_risk(
                                                    first,
                                                    second,
                                                    ko_1,
                                                    target_opp,
                                                    target_opp,
                                                    visible_opps,
                                                    battle=battle,
                                                    config=config,
                                                )
                                            )
                                            if stale["risk"]:
                                                joint_score -= config.stale_target_after_ally_ko_penalty
                                                if stale["fallback_target_type_immune"]:
                                                    joint_score -= config.stale_target_type_immune_penalty

                            opp_hp_fraction = getattr(
                                target_opp, "current_hp_fraction", 1.0
                            )
                            other_idx = 1 if first.move_target == 1 else 0
                            other_opp = battle.opponent_active_pokemon[other_idx]
                            other_hp_fraction = (
                                getattr(other_opp, "current_hp_fraction", 1.0)
                                if other_opp
                                else 1.0
                            )
                            if (
                                opp_hp_fraction <= other_hp_fraction
                                and opp_hp_fraction < 0.75
                            ):
                                if config.enable_focus_fire_synergy:
                                    joint_score += config.focus_fire_synergy_bonus
                            elif opp_hp_fraction >= 0.50:
                                joint_score += 50.0

            if config.enable_type_immunity_safety:
                waste_penalty = 0.0
                for slot_idx, order in enumerate([first, second]):
                    if order and isinstance(order.order, Move):
                        move_obj = order.order
                        target_pos = getattr(order, "move_target", None)
                        if target_pos in (1, 2) and move_obj.base_power > 0:
                            target_mon = battle.opponent_active_pokemon[target_pos - 1]
                            if target_mon:
                                try:
                                    immune, _ = is_type_immune(
                                        move_obj,
                                        battle.active_pokemon[slot_idx],
                                        target_mon,
                                        battle,
                                    )
                                    if immune:
                                        if self.is_spread_move(move_obj):
                                            other_opps = [
                                                o
                                                for o in battle.opponent_active_pokemon
                                                if o and o != target_mon
                                            ]
                                            any_not_immune = False
                                            for other_opp in other_opps:
                                                try:
                                                    other_immune, _ = is_type_immune(
                                                        move_obj,
                                                        battle.active_pokemon[slot_idx],
                                                        other_opp,
                                                        battle,
                                                    )
                                                    if not other_immune:
                                                        any_not_immune = True
                                                        break
                                                except Exception:
                                                    pass
                                            if any_not_immune:
                                                continue
                                        waste_penalty += 1.0
                                except Exception:
                                    pass
                joint_score -= waste_penalty

            # Phase 6.4.10b: All-target immune spread joint penalty
            # Penalize joint orders where a slot uses a damaging spread move
            # with all opponent targets immune, unless it's the only legal action.
            for slot_idx, order in enumerate([first, second]):
                if order and self._is_all_target_immune_damaging_spread(
                    order, slot_idx, battle, config
                ):
                    # Check if this slot has any non-wasted alternative
                    slot_scores = slot_0_scores if slot_idx == 0 else slot_1_scores
                    has_alternative = False
                    for other_order, other_score in slot_scores.items():
                        if other_order is not order and other_score > 0:
                            has_alternative = True
                            break
                    if has_alternative:
                        joint_score -= config.all_target_immune_spread_joint_penalty

            if either_blocked and (
                first_safety_blocked
                or second_safety_blocked
                or first_ar_blocked
                or second_ar_blocked
                or first_st_blocked
                or second_st_blocked
                or first_nb_blocked
                or second_nb_blocked
            ):
                joint_score -= config.safety_block_joint_penalty

            scored_joint_orders.append((joint_order, joint_score, score_1, score_2))

        scored_joint_orders.sort(key=lambda x: x[1], reverse=True)
        return scored_joint_orders

    @property
    def total_meta_predictions_used(self) -> int:
        return sum(self.meta_predictions_used_by_battle.values())

    @property
    def total_meta_protect_predictions(self) -> int:
        return sum(self.meta_protect_predictions_by_battle.values())

    @property
    def total_meta_fakeout_predictions(self) -> int:
        return sum(self.meta_fakeout_predictions_by_battle.values())

    @property
    def total_meta_priority_predictions(self) -> int:
        return sum(self.meta_priority_predictions_by_battle.values())

    @property
    def total_meta_spread_predictions(self) -> int:
        return sum(self.meta_spread_predictions_by_battle.values())

    @property
    def total_meta_setup_predictions(self) -> int:
        return sum(self.meta_setup_predictions_by_battle.values())

    @property
    def total_meta_coverage_predictions(self) -> int:
        return sum(self.meta_coverage_predictions_by_battle.values())

    @property
    def total_meta_ability_soft_penalties(self) -> int:
        return sum(self.meta_ability_soft_penalties_by_battle.values())

    @property
    def total_meta_species_found(self) -> int:
        return sum(self.meta_species_found_by_battle.values())

    @property
    def total_meta_species_missing(self) -> int:
        return sum(self.meta_species_missing_by_battle.values())

    @property
    def total_candidate_meta_predictions(self) -> int:
        return sum(self.candidate_meta_predictions_by_battle.values())

    @property
    def total_selected_meta_predictions(self) -> int:
        return sum(self.selected_meta_predictions_by_battle.values())

    @property
    def total_meta_score_delta(self) -> float:
        return sum(self.total_meta_score_delta_by_battle.values())

    @property
    def total_ability_blocks_avoided(self) -> int:
        return sum(self.ability_blocks_avoided_by_battle.values())

    @property
    def total_ability_absorbs_avoided(self) -> int:
        return sum(self.ability_absorbs_avoided_by_battle.values())

    @property
    def total_ability_redirects_avoided(self) -> int:
        return sum(self.ability_redirects_avoided_by_battle.values())

    @property
    def total_ally_safe_spreads(self) -> int:
        return sum(self.ally_safe_spreads_by_battle.values())

    @property
    def total_ability_multipliers_applied(self) -> int:
        return sum(self.ability_multipliers_applied_by_battle.values())

    # Phase 5.2 aggregate properties
    @property
    def total_rs_predictions_used(self) -> int:
        return sum(self.rs_predictions_used_by_battle.values())

    @property
    def total_rs_protect_predictions(self) -> int:
        return sum(self.rs_protect_predictions_by_battle.values())

    @property
    def total_rs_fakeout_predictions(self) -> int:
        return sum(self.rs_fakeout_predictions_by_battle.values())

    @property
    def total_rs_priority_predictions(self) -> int:
        return sum(self.rs_priority_predictions_by_battle.values())

    @property
    def total_rs_spread_predictions(self) -> int:
        return sum(self.rs_spread_predictions_by_battle.values())

    @property
    def total_rs_setup_predictions(self) -> int:
        return sum(self.rs_setup_predictions_by_battle.values())

    @property
    def total_rs_speed_control_predictions(self) -> int:
        return sum(self.rs_speed_control_predictions_by_battle.values())

    @property
    def total_rs_candidate_predictions(self) -> int:
        return sum(self.rs_candidate_predictions_by_battle.values())

    @property
    def total_rs_selected_predictions(self) -> int:
        return sum(self.rs_selected_predictions_by_battle.values())

    @property
    def total_rs_score_delta(self) -> float:
        return sum(self.rs_score_delta_by_battle.values())

    @property
    def total_rs_species_found(self) -> int:
        return sum(self.rs_species_found_by_battle.values())

    @property
    def total_rs_species_missing(self) -> int:
        return sum(self.rs_species_missing_by_battle.values())

    def increment_metric(self, dict_metric: dict, battle_tag: str, amount: int = 1):
        if getattr(self, "_pure_scoring_mode", False):
            return
        if not battle_tag:
            return
        if battle_tag not in dict_metric:
            dict_metric[battle_tag] = 0
        dict_metric[battle_tag] += amount

    @property
    def total_protect_count(self) -> int:
        return sum(m.get("protect", 0) for m in self.battle_metrics.values())

    @property
    def total_fake_out_count(self) -> int:
        return sum(m.get("fake_out", 0) for m in self.battle_metrics.values())

    @property
    def total_spread_count(self) -> int:
        return sum(m.get("spread", 0) for m in self.battle_metrics.values())

    @property
    def total_valid_spread_count(self) -> int:
        return sum(m.get("valid_spread", 0) for m in self.battle_metrics.values())

    @property
    def total_focus_fire_count(self) -> int:
        return sum(m.get("focus_fire", 0) for m in self.battle_metrics.values())

    @property
    def total_threat_contribution(self) -> float:
        return sum(
            m.get("threat_contribution", 0.0) for m in self.battle_metrics.values()
        )

    @property
    def total_tiebreaker_activations(self) -> int:
        return sum(
            m.get("tiebreaker_activations", 0) for m in self.battle_metrics.values()
        )

    @property
    def total_boosted_override_activations(self) -> int:
        return sum(
            m.get("boosted_override_activations", 0)
            for m in self.battle_metrics.values()
        )

    @property
    def total_draco_penalties_applied(self) -> int:
        return sum(self.draco_penalties_applied_by_battle.values())

    @property
    def total_make_it_rain_penalties_applied(self) -> int:
        return sum(self.make_it_rain_penalties_applied_by_battle.values())

    def get_valid_orders_for_slot(self, slot_idx: int, battle: DoubleBattle) -> list:
        val = getattr(self, "_current_valid_orders", None)
        if not val:
            val = battle.valid_orders
        if val and len(val) > slot_idx:
            return val[slot_idx]
        return []

    def get_pokemon_identifier(self, pokemon: Optional[Pokemon]) -> str:
        if not pokemon:
            return ""
        ident = getattr(pokemon, "ident", None)
        if ident:
            return str(ident)
        last_req = getattr(pokemon, "_last_request", None)
        if last_req and isinstance(last_req, dict) and "ident" in last_req:
            return str(last_req["ident"])
        name = getattr(pokemon, "name", None)
        if name:
            return str(name)
        return str(pokemon.species)

    def get_priority(self, move: Move) -> int:
        try:
            return getattr(move, "priority", 0)
        except Exception:
            return 0

    def get_recoil(self, move: Move) -> float:
        try:
            return getattr(move, "recoil", 0.0)
        except Exception:
            return 0.0

    def get_accuracy(self, move: Move) -> float:
        try:
            acc = getattr(move, "accuracy", 1.0)
            if acc is True or acc is None:
                return 1.0
            if isinstance(acc, (int, float)):
                if acc == 100:
                    return 1.0
                if acc > 1.0:
                    return acc / 100.0
                return acc
            return 1.0
        except Exception:
            return 1.0

    def get_stats(self, pokemon: Pokemon) -> dict:
        try:
            return getattr(pokemon, "stats", {})
        except Exception:
            return {}

    def get_base_stats(self, pokemon: Pokemon) -> dict:
        try:
            return getattr(pokemon, "base_stats", {})
        except Exception:
            return {}

    def get_boosts(self, pokemon: Pokemon) -> dict:
        try:
            return getattr(pokemon, "boosts", {})
        except Exception:
            return {}

    def get_boosted_stat(self, pokemon: Optional[Pokemon], stat_name: str) -> float:
        if not pokemon:
            return 100.0

        stats = self.get_stats(pokemon) or {}
        base_stats = self.get_base_stats(pokemon) or {}

        if stats.get(stat_name):
            base_val = float(stats[stat_name])
        else:
            base_val = float(base_stats.get(stat_name, 100.0))
            level = getattr(pokemon, "level", 80) or 80
            # Standard Random Battles stat formula (31 IVs, 85 EVs)
            base_val = (2.0 * base_val + 52.0) * level / 100.0 + 5.0

        boosts = self.get_boosts(pokemon) or {}
        stage = boosts.get(stat_name, 0)

        if stage > 0:
            multiplier = (2.0 + stage) / 2.0
        elif stage < 0:
            multiplier = 2.0 / (2.0 - stage)
        else:
            multiplier = 1.0
        return float(base_val) * multiplier

    def has_tailwind(self, side_conditions) -> bool:
        if not side_conditions:
            return False
        try:
            from poke_env.battle.side_condition import SideCondition

            if SideCondition.TAILWIND in side_conditions:
                return True
        except Exception:
            pass
        for cond in side_conditions:
            cond_str = cond.name if hasattr(cond, "name") else str(cond)
            if "TAILWIND" in cond_str.upper():
                return True
        return False

    def get_effective_speed(self, pokemon, battle=None) -> float:
        if not pokemon:
            return 0.0
        try:
            speed = float(self.get_boosted_stat(pokemon, "spe"))
            status = getattr(pokemon, "status", None)
            if status:
                status_str = status.name if hasattr(status, "name") else str(status)
                if status_str.upper() == "PAR":
                    speed *= 0.5

            if battle:
                is_our_side = False
                for p in battle.active_pokemon.values():
                    if (
                        p
                        and p.species == pokemon.species
                        and getattr(p, "active", False)
                    ):
                        is_our_side = True
                        break
                if is_our_side:
                    if self.has_tailwind(getattr(battle, "side_conditions", {})):
                        speed *= 2.0
                else:
                    if self.has_tailwind(
                        getattr(battle, "opponent_side_conditions", {})
                    ):
                        speed *= 2.0

            item = getattr(pokemon, "item", None)
            if item:
                item_str = item.name if hasattr(item, "name") else str(item)
                item_str_clean = (
                    item_str.lower().replace(" ", "").replace("-", "").replace("_", "")
                )
                if "choicescarf" in item_str_clean:
                    speed *= 1.5

            return speed
        except Exception:
            return 0.0

    def is_trick_room_active(self, battle) -> bool:
        if not battle:
            return False
        fields = getattr(battle, "fields", {})
        if fields:
            try:
                from poke_env.battle.field import Field

                if Field.TRICK_ROOM in fields:
                    return True
            except Exception:
                pass
            for f in fields:
                f_str = f.name if hasattr(f, "name") else str(f)
                if "TRICK_ROOM" in f_str.upper() or "TRICKROOM" in f_str.upper():
                    return True
        return False

    def get_move_priority(self, move) -> int:
        if not move:
            return 0
        prio = None
        try:
            prio = getattr(move, "priority", None)
        except Exception:
            pass
        if isinstance(prio, int):
            return prio

        move_id = ""
        try:
            move_id = getattr(move, "id", "")
        except Exception:
            pass
        if not move_id and isinstance(move, str):
            move_id = move
        move_id_clean = (
            str(move_id).lower().replace(" ", "").replace("-", "").replace("_", "")
        )

        if move_id_clean in (
            "protect",
            "detect",
            "spikyshield",
            "banefulbunker",
            "kingsshield",
            "obstruct",
            "silktrap",
            "burningbulwark",
        ):
            return 4
        if move_id_clean in ("fakeout", "quickguard", "wideguard", "craftyshield"):
            return 3
        if move_id_clean in ("extremespeed", "feint", "allyswitch"):
            return 2
        if move_id_clean in (
            "aquajet",
            "bulletpunch",
            "iceshard",
            "machpunch",
            "shadowsneak",
            "suckerpunch",
            "vacuumwave",
            "watershuriken",
            "bastonpass",
            "babyeyedomination",
            "firstimpression",
            "grassyglide",
            "accelgor",
        ):
            return 1

        return 0

    def get_opponent_active_turns(self, opponent, battle) -> int:
        if not battle or not opponent:
            return 1
        battle_tag = battle.battle_tag
        if (
            not hasattr(self, "opponent_active_turns")
            or battle_tag not in self.opponent_active_turns
        ):
            return 1
        mon_id = self.get_pokemon_identifier(opponent)
        for i, mon in enumerate(battle.opponent_active_pokemon):
            if mon and mon.species == opponent.species:
                key = (i, mon_id)
                if key in self.opponent_active_turns[battle_tag]:
                    count, _ = self.opponent_active_turns[battle_tag][key]
                    return count
        return 1

    def opponent_has_revealed_priority_move(self, opponent, battle=None) -> dict:
        result = {
            "has_priority": False,
            "has_guaranteed_priority": False,
            "has_conditional_priority": False,
            "conditional_priority_moves": [],
        }
        if not opponent:
            return result
        moves = getattr(opponent, "moves", {})
        for move_id, move in moves.items():
            priority = self.get_move_priority(move)
            if priority > 0:
                move_id_clean = (
                    move_id.lower().replace(" ", "").replace("-", "").replace("_", "")
                )
                if move_id_clean == "firstimpression":
                    turns = self.get_opponent_active_turns(opponent, battle)
                    if turns > 1:
                        continue

                result["has_priority"] = True
                if move_id_clean in ("suckerpunch", "firstimpression"):
                    result["has_conditional_priority"] = True
                    result["conditional_priority_moves"].append(move_id_clean)
                else:
                    result["has_guaranteed_priority"] = True

        return result

    def estimate_speed_priority_threat(
        self, our_active, opponent_actives, battle=None, candidate_action=None
    ) -> dict:
        result = {
            "is_threatened": False,
            "speed_threatened": False,
            "priority_threatened": False,
            "faint_before_moving": False,
            "faster_opponents": [],
            "priority_opponents": [],
            "threat_confidence": 0.0,
            "only_conditional_priority": False,
        }
        if not our_active or not opponent_actives:
            return result

        our_hp = getattr(our_active, "current_hp_fraction", 1.0)

        is_protect = False
        is_switch = False
        candidate_priority = 0
        is_attacking = False

        if candidate_action:
            if isinstance(candidate_action.order, Pokemon):
                is_switch = True
                candidate_priority = 6
            elif isinstance(candidate_action.order, Move):
                move_id = getattr(candidate_action.order, "id", "").lower()
                if move_id in (
                    "protect",
                    "detect",
                    "spikyshield",
                    "banefulbunker",
                    "kingsshield",
                    "obstruct",
                    "silktrap",
                    "burningbulwark",
                ):
                    is_protect = True
                    candidate_priority = 4
                else:
                    candidate_priority = self.get_move_priority(candidate_action.order)
                category = getattr(candidate_action.order, "category", None)
                category_name = getattr(category, "name", "STATUS")
                is_attacking = category_name != "STATUS"

        tr = self.is_trick_room_active(battle)
        our_speed = self.get_effective_speed(our_active, battle)

        max_opp_conf = 0.0
        has_any_prio_threat = False
        only_cond = True

        def get_multiplier(mon, typ):
            try:
                return mon.damage_multiplier(typ)
            except Exception:
                return 1.0

        for opp in opponent_actives:
            if not opp or getattr(opp, "fainted", False):
                continue

            opp_speed = self.get_effective_speed(opp, battle)

            if tr:
                is_opp_faster = (
                    our_speed >= opp_speed * self.config.speed_margin_required
                )
            else:
                is_opp_faster = (
                    opp_speed >= our_speed * self.config.speed_margin_required
                )

            prio_info = self.opponent_has_revealed_priority_move(opp, battle)

            priority_threat_active = False

            if prio_info["has_priority"]:
                if (
                    prio_info["has_conditional_priority"]
                    and not prio_info["has_guaranteed_priority"]
                ):
                    has_sucker = any(
                        m == "suckerpunch"
                        for m in prio_info["conditional_priority_moves"]
                    )
                    if has_sucker:
                        if candidate_action is None:
                            priority_threat_active = (
                                our_hp <= self.config.speed_threat_hp_threshold
                            )
                        elif is_attacking:
                            priority_threat_active = (
                                our_hp <= self.config.priority_threat_hp_threshold
                            )
                        else:
                            priority_threat_active = False
                    else:
                        priority_threat_active = (
                            our_hp <= self.config.priority_threat_hp_threshold
                        )
                else:
                    priority_threat_active = (
                        our_hp <= self.config.priority_threat_hp_threshold
                    )

            opp_conf = 0.0
            opp_is_threat = False

            if is_opp_faster and our_hp <= self.config.speed_threat_hp_threshold:
                opp_is_threat = True
                result["speed_threatened"] = True
                result["is_threatened"] = True
                if opp.species not in result["faster_opponents"]:
                    result["faster_opponents"].append(opp.species)

                # Phase BEHAVIOR-18: candidate-independent
                # expected-faint (speed-threat branch).
                # The flag describes the active-slot state,
                # not the candidate action type. If the slot
                # is speed-threatened, faint_before_moving is
                # True regardless of whether the candidate is
                # Protect, switch, or attack. The downstream
                # BEHAVIOR-16 Protect floor and BEHAVIOR-12/15
                # attack penalties still gate on their own
                # action-type checks, so Protect/switch are
                # not affected.
                #
                # Note: in real poke-env, Protect has
                # priority=4 and switch has priority=6, so
                # the original ``candidate_priority == 0``
                # check would still exclude Protect and
                # switch. The equivalent smallest safe
                # implementation removes BOTH the
                # ``is_protect or is_switch`` gating AND
                # the ``candidate_priority == 0`` check,
                # so the flag fires whenever the slot is
                # speed-threatened.
                result["faint_before_moving"] = True

                # Compute confidence for speed threat -- use max multiplier across both opponent types
                max_threat = get_max_type_threat(our_active, opp, battle)
                if our_hp <= 0.15:
                    opp_conf = max(opp_conf, 1.0)
                elif our_hp <= 0.25:
                    if max_threat >= 1.5:
                        opp_conf = max(opp_conf, 1.0)
                    else:
                        opp_conf = max(opp_conf, 0.75)
                elif max_threat >= 2.0 and our_hp <= 0.35:
                    opp_conf = max(opp_conf, 0.75)
                elif max_threat >= 1.0:
                    opp_conf = max(opp_conf, 0.75)
                else:
                    opp_conf = max(opp_conf, 0.25)

            if priority_threat_active:
                opp_is_threat = True
                has_any_prio_threat = True
                result["priority_threatened"] = True
                result["is_threatened"] = True
                if opp.species not in result["priority_opponents"]:
                    result["priority_opponents"].append(opp.species)

                opp_max_prio = 1
                for m_id, m in getattr(opp, "moves", {}).items():
                    opp_max_prio = max(opp_max_prio, self.get_move_priority(m))

                # Phase BEHAVIOR-18: candidate-independent
                # expected-faint (priority branch). Same
                # rationale as the speed-threat branch
                # above: the flag describes the slot
                # state, not the candidate action type.
                # The flag fires whenever the slot is
                # priority-threatened, regardless of the
                # candidate's priority.
                result["faint_before_moving"] = True

                # Compute confidence for priority threat -- use max multiplier
                max_prio_threat = get_max_type_threat(our_active, opp, battle)
                if prio_info.get("has_conditional_priority") and not prio_info.get(
                    "has_guaranteed_priority"
                ):
                    opp_conf = max(
                        opp_conf, self.config.speed_priority_conditional_priority_weight
                    )
                else:
                    only_cond = False
                    if our_hp <= 0.20 or max_prio_threat >= 1.5:
                        opp_conf = max(opp_conf, 1.0)
                    else:
                        opp_conf = max(opp_conf, 0.75)

            if opp_is_threat:
                max_opp_conf = max(max_opp_conf, opp_conf)

        result["threat_confidence"] = max_opp_conf
        result["only_conditional_priority"] = (
            only_cond if has_any_prio_threat else False
        )
        return result

    def is_protect_available_for_slot(self, slot_idx: int, battle) -> bool:
        valid_orders = getattr(self, "_current_valid_orders", None)
        if (
            not valid_orders
            or len(valid_orders) <= slot_idx
            or not valid_orders[slot_idx]
        ):
            return False
        for order in valid_orders[slot_idx]:
            if order and isinstance(order.order, Move):
                move_id = getattr(order.order, "id", "").lower()
                if move_id in (
                    "protect",
                    "detect",
                    "spikyshield",
                    "banefulbunker",
                    "kingsshield",
                    "obstruct",
                    "silktrap",
                    "burningbulwark",
                ):
                    return True
        return False

    def _build_b17_protect_floor_debug_for_turn(
        self, battle_tag, valid_orders
    ):
        """Phase BEHAVIOR-17: aggregate the per-action
        Protect floor diagnostic into a per-turn,
        per-slot JSON-safe dict.

        Returns an empty dict if no Protect-like actions
        were scored in this turn.

        The per-action debug is populated by score_action
        (the wrapper) for every Protect-like action,
        regardless of whether the floor conditions are
        met. This aggregation reads that dict and
        computes:

        - expected_faint: from the first action's
          recorded flag (all actions in the slot share
          the same expected_faint value at scoring time)
        - protect_like_keys: pipe-joined list of
          order_key strings
        - protect_score_before_floor: best pre-floor
          score across all Protect-like actions
        - protect_score_after_floor: best post-floor
          score
        - floor_applied: True iff any action had
          floor_applied=True
        - floor_value: the configured floor
        - selected_action_key: the selected joint key
          for this slot (from v2l1_selected_joint_key)
        - action_count: number of Protect-like actions
          scored
        """
        per_action = self._b17_protect_floor_debug.get(
            battle_tag, {}
        )
        if not per_action:
            return {}
        sel_joint = getattr(self, "_v2l1_selected_joint_key", None) or ""
        if not isinstance(sel_joint, str):
            sel_joint = ""
        sel_keys = sel_joint.split(";") if sel_joint else ["", ""]
        out = {}
        for slot_idx in (0, 1):
            actions = per_action.get(slot_idx, [])
            if not actions:
                continue
            keys = [a["order_key"] for a in actions]
            pre_vals = [a["pre_floor_score"] for a in actions]
            post_vals = [a["post_floor_score"] for a in actions]
            any_applied = any(a["floor_applied"] for a in actions)
            expected_faint = actions[0]["expected_faint"]
            floor_value = actions[0]["floor_value"]
            out["slot{}".format(slot_idx)] = {
                "expected_faint": bool(expected_faint),
                "protect_like_keys": keys,
                "protect_score_before_floor": (
                    max(pre_vals) if pre_vals else None
                ),
                "protect_score_after_floor": (
                    max(post_vals) if post_vals else None
                ),
                "floor_applied": bool(any_applied),
                "floor_value": float(floor_value),
                "action_count": len(actions),
                "selected_action_key": (
                    sel_keys[slot_idx]
                    if slot_idx < len(sel_keys)
                    else ""
                ),
            }
        return out

    def has_legal_protect_like_action(
        self, active, battle, slot_index=None, valid_orders=None
    ) -> bool:
        if valid_orders is None:
            valid_orders = getattr(self, "_current_valid_orders", None)

        if slot_index is None:
            if battle and active:
                for idx, p in enumerate(battle.active_pokemon):
                    if p and p.species == active.species:
                        slot_index = idx
                        break

        if (
            valid_orders
            and slot_index is not None
            and len(valid_orders) > slot_index
            and valid_orders[slot_index]
        ):
            for order in valid_orders[slot_index]:
                if order and isinstance(order.order, Move):
                    move_id = getattr(order.order, "id", "").lower()
                    if move_id in (
                        "protect",
                        "detect",
                        "spikyshield",
                        "banefulbunker",
                        "kingsshield",
                        "obstruct",
                        "silktrap",
                        "burningbulwark",
                    ):
                        return True
            return False

        if active and hasattr(active, "moves") and active.moves:
            for move in active.moves.values():
                move_id = getattr(move, "id", "").lower()
                if move_id in (
                    "protect",
                    "detect",
                    "spikyshield",
                    "banefulbunker",
                    "kingsshield",
                    "obstruct",
                    "silktrap",
                    "burningbulwark",
                ):
                    return True
        return False

    def is_high_value_action_under_threat(
        self, action, actor, battle, opponent_actives, config=None
    ) -> bool:
        resolved_config = config if config is not None else self.config
        if not action or not isinstance(action.order, Move):
            return False

        move = action.order

        if self.get_move_priority(move) > 0:
            return True

        for opp in opponent_actives:
            if opp and self.check_move_will_ko(
                move, actor, opp, battle, config=resolved_config
            ):
                return True

        if is_opponent_spread_move(move, action):
            opps_count = sum(
                1
                for opp in opponent_actives
                if opp and not getattr(opp, "fainted", False)
            )
            if opps_count >= 2:
                base_pow = getattr(move, "base_power", 0)
                if base_pow >= 75:
                    return True

        target_pos = action.move_target
        if target_pos in (1, 2) and opponent_actives:
            opp = (
                opponent_actives[target_pos - 1]
                if len(opponent_actives) > (target_pos - 1)
                else None
            )
            if opp:
                expected_dmg_frac = self.get_expected_damage(
                    move, actor, opp, battle, config=resolved_config
                )
                if (
                    expected_dmg_frac
                    >= resolved_config.speed_priority_min_expected_damage_fraction
                ):
                    return True

        if target_pos in (1, 2) and opponent_actives:
            opp = (
                opponent_actives[target_pos - 1]
                if len(opponent_actives) > (target_pos - 1)
                else None
            )
            if opp and getattr(opp, "current_hp_fraction", 1.0) <= 0.20:
                expected_dmg_frac = self.get_expected_damage(
                    move, actor, opp, battle, config=resolved_config
                )
                if expected_dmg_frac > 0.05:
                    return True

        return False

    def selected_target_will_be_koed_before_second_action(
        self, order_0, order_1, battle, config=None
    ) -> bool:
        if not order_0 or not order_1 or not battle:
            return False
        if not isinstance(order_0.order, Move) or not isinstance(order_1.order, Move):
            return False
        if order_0.move_target != order_1.move_target or order_0.move_target not in (
            1,
            2,
        ):
            return False

        target_opp = battle.opponent_active_pokemon[order_0.move_target - 1]
        if not target_opp or getattr(target_opp, "fainted", False):
            return False

        prio_0 = self.get_move_priority(order_0.order)
        prio_1 = self.get_move_priority(order_1.order)

        if prio_0 > prio_1:
            slot_0_is_faster = True
        elif prio_1 > prio_0:
            slot_0_is_faster = False
        else:
            speed_0 = self.get_effective_speed(battle.active_pokemon[0], battle)
            speed_1 = self.get_effective_speed(battle.active_pokemon[1], battle)
            tr = self.is_trick_room_active(battle)
            if tr:
                slot_0_is_faster = speed_0 < speed_1
            else:
                slot_0_is_faster = speed_0 > speed_1

        faster_order = order_0 if slot_0_is_faster else order_1
        slower_order = order_1 if slot_0_is_faster else order_0
        faster_active = (
            battle.active_pokemon[0] if slot_0_is_faster else battle.active_pokemon[1]
        )

        faster_ko = self.check_move_will_ko(
            faster_order.order, faster_active, target_opp, battle, config=config
        )
        if not faster_ko:
            return False

        acc = getattr(faster_order.order, "accuracy", 1.0)
        acc_mult = 1.0
        if acc is True or acc is None:
            acc_mult = 1.0
        elif isinstance(acc, (int, float)):
            acc_mult = acc if acc <= 1.0 else acc / 100.0
        if acc_mult < 0.85:
            return False

        threat_score = self.score_opponent_threat(target_opp, battle)
        if threat_score >= 0.50:
            return False

        if is_opponent_spread_move(slower_order.order):
            return False

        has_protect = False
        for m_id in getattr(target_opp, "moves", {}).items():
            m_id_clean = (
                m_id[0].lower().replace(" ", "").replace("-", "").replace("_", "")
            )
            if m_id_clean in (
                "protect",
                "detect",
                "spikyshield",
                "banefulbunker",
                "kingsshield",
                "obstruct",
                "silktrap",
                "burningbulwark",
            ):
                has_protect = True
                break
        if (
            not has_protect
            and self.config.enable_random_set_opponent_modeling
            and self.random_set_engine
        ):
            likely_p, _, _ = self.random_set_engine.likely_has_protect(
                target_opp.species, list(target_opp.moves.keys())
            )
            if likely_p:
                has_protect = True
        if has_protect:
            return False

        return True

    def get_type_effectiveness(
        self, move: Move, opponent: Optional[Pokemon], attacker=None
    ) -> float:

        if not opponent:
            return 1.0
        try:
            etype = get_effective_move_type(move, attacker)
            declared = _get_declared_move_type(move)
            if etype != declared and etype:
                from poke_env.battle.pokemon_type import PokemonType

                try:
                    return opponent.damage_multiplier(PokemonType[etype])
                except Exception:
                    pass
            return opponent.damage_multiplier(move)
        except Exception:
            try:
                move_type = getattr(move, "type", None)
                if move_type:
                    return opponent.damage_multiplier(move_type)
            except Exception:
                pass
        return 1.0

    def estimate_opponent_max_hp(self, opponent: Optional[Pokemon]) -> float:
        if not opponent:
            return 300.0
        try:
            base_stats = self.get_base_stats(opponent) or {}
            base_hp = float(base_stats.get("hp", 100.0))
            level = getattr(opponent, "level", 80) or 80
            # HP formula for Random Battles (31 IVs, 85 EVs)
            return (2.0 * base_hp + 52.0) * level / 100.0 + level + 10.0
        except Exception:
            level = getattr(opponent, "level", 80) or 80
            return float(level) * 3.5

    def score_opponent_threat(
        self,
        opponent: Optional[Pokemon],
        battle: DoubleBattle,
        our_pokemon: Optional[Pokemon] = None,
    ) -> float:
        if not opponent:
            return 0.0

        try:
            hp_factor = getattr(opponent, "current_hp_fraction", 1.0)
            if hp_factor is None or hp_factor == 0.0:
                return 0.0

            opp_atk = self.get_boosted_stat(opponent, "atk")
            opp_spa = self.get_boosted_stat(opponent, "spa")
            stat_factor = max(opp_atk, opp_spa) / 150.0
            stat_factor = min(2.0, max(0.0, stat_factor))

            spe_factor = 0.0
            faster_bonus = 0.0
            if self.config.enable_speed_threat:
                opp_spe = self.get_boosted_stat(opponent, "spe")
                spe_factor = opp_spe / 150.0
                spe_factor = min(2.0, max(0.0, spe_factor))

                target_ours = (
                    [our_pokemon]
                    if our_pokemon
                    else [active for active in battle.active_pokemon if active]
                )
                for active in target_ours:
                    if active:
                        our_spe = self.get_boosted_stat(active, "spe")
                        if opp_spe > our_spe:
                            faster_bonus = 0.2
                            break

            has_spread = 0.0
            if self.config.enable_spread_threat:
                for move in opponent.moves.values():
                    if self.is_spread_move(move):
                        has_spread = 0.15
                        break

            has_priority = 0.0
            # Always check priority moves
            for move in opponent.moves.values():
                if self.get_priority(move) > 0:
                    has_priority = 0.15
                    break

            has_setup = 0.0
            if self.config.enable_setup_threat:
                setup_move_ids = {
                    "swordsdance",
                    "dragondance",
                    "calmmind",
                    "nastyplot",
                    "agility",
                    "quiverdance",
                    "shellsmash",
                    "bulkup",
                    "cosmicpower",
                    "doubleteam",
                    "acidarmor",
                    "irondefense",
                    "honeclaws",
                    "workup",
                    "growth",
                    "howl",
                    "charge",
                    "minimize",
                    "autotomize",
                    "rockpolish",
                    "geomancy",
                }
                for move in opponent.moves.values():
                    is_setup_id = move.id in setup_move_ids
                    is_setup_boost = False
                    target_str = str(getattr(move, "target", ""))
                    if "self" in target_str.lower():
                        boosts = getattr(move, "boosts", {})
                        if boosts and any(val > 0 for val in boosts.values()):
                            is_setup_boost = True
                    if is_setup_id or is_setup_boost:
                        has_setup = 0.15
                        break

            has_speed_control = 0.0
            spe_control_move_ids = {
                "tailwind",
                "trickroom",
                "icywind",
                "electroweb",
                "bulldoze",
                "nuzzle",
                "glare",
                "thunderwave",
                "stringshot",
                "scaryface",
            }
            for move in opponent.moves.values():
                is_spe_id = move.id in spe_control_move_ids
                is_spe_boost = False
                boosts = getattr(move, "boosts", {})
                if boosts and "spe" in boosts and boosts["spe"] < 0:
                    is_spe_boost = True
                if is_spe_id or is_spe_boost:
                    has_speed_control = 0.15
                    break

            super_effective = 0.0
            target_ours = (
                [our_pokemon]
                if our_pokemon
                else [active for active in battle.active_pokemon if active]
            )
            for active in target_ours:
                if active:
                    for move in opponent.moves.values():
                        if active.damage_multiplier(move) >= 2.0:
                            super_effective = 0.25
                            break
                    if super_effective > 0.0:
                        break
                    for t in getattr(opponent, "types", []):
                        if t and active.damage_multiplier(t) >= 2.0:
                            super_effective = 0.20
                            break
                    if super_effective > 0.0:
                        break

            threat_score = (
                (stat_factor + spe_factor) * hp_factor
                + faster_bonus
                + has_spread
                + has_priority
                + has_setup
                + has_speed_control
                + super_effective
            )
            return min(1.0, max(0.0, threat_score / 5.0))
        except Exception:
            return 0.0

    def get_expected_damage(
        self,
        move: Move,
        active: Optional[Pokemon],
        opponent: Optional[Pokemon],
        battle: Optional[DoubleBattle] = None,
        config=None,
        is_single_target_direct: bool = False,
    ) -> float:
        resolved_config = (
            config if config is not None else getattr(self, "config", None)
        )
        base_power = getattr(move, "base_power", 0)
        if base_power == 0 or not opponent or not active:
            return 0.0
        if resolved_config and resolved_config.enable_type_immunity_safety:
            immune, reason = is_type_immune(move, active, opponent, battle)
            if immune:
                return 0.0
        if resolved_config and getattr(
            resolved_config, "enable_ability_hard_safety_only", False
        ):
            blocks, reason = ability_hard_blocks_move(
                move, active, opponent, battle, resolved_config
            )
            if blocks and _ability_block_enabled(resolved_config, reason):
                return 0.0

            # Phase 6.3.3 direct safety
            if (
                getattr(
                    resolved_config, "ability_hard_safety_direct_absorb_only", False
                )
                and is_single_target_direct
            ):
                if not self.is_spread_move(move):
                    blocks_direct, reason_direct = direct_known_absorb_blocks_move(
                        move, active, opponent, battle
                    )
                    if blocks_direct:
                        return 0.0

        # Phase 6.3.6b: Known Ally Redirection Hard Safety
        if resolved_config and getattr(
            resolved_config, "enable_known_ally_redirection_hard_safety", False
        ):
            if battle and is_single_target_direct:
                active_pokemon = getattr(battle, "active_pokemon", [])
                if len(active_pokemon) >= 2:
                    ally = None
                    if active is active_pokemon[0]:
                        ally = active_pokemon[1]
                    elif active is active_pokemon[1]:
                        ally = active_pokemon[0]
                    if ally and not getattr(ally, "fainted", False):
                        redirects, _ = ally_redirects_our_single_target_move(
                            move, active, ally, battle
                        )
                        if redirects:
                            return 0.0

        # Phase 6.3.5a: Priority Terrain / Ability Safety
        if resolved_config and getattr(
            resolved_config, "enable_priority_field_hard_safety", False
        ):
            priority_blocked, _ = priority_move_is_field_blocked(
                move, active, opponent, battle, resolved_config
            )
            if priority_blocked:
                return 0.0
        try:
            category = getattr(move, "category", None)
            category_name = getattr(category, "name", "PHYSICAL")
            if category_name == "SPECIAL":
                attacking_stat = self.get_boosted_stat(active, "spa")
                defending_stat = self.get_boosted_stat(opponent, "spd")
            else:
                attacking_stat = self.get_boosted_stat(active, "atk")
                defending_stat = self.get_boosted_stat(opponent, "def")
            level = getattr(active, "level", 100)
            base_damage = (
                (
                    (2.0 * level / 5.0 + 2.0)
                    * base_power
                    * attacking_stat
                    / max(defending_stat, 1.0)
                )
                / 50.0
            ) + 2.0
            active_types = getattr(active, "types", [])
            etype = get_effective_move_type(move, active)
            stab = 1.0
            if etype:
                for t in active_types:
                    t_name = getattr(t, "name", str(t)).upper() if t else ""
                    if t_name == etype:
                        stab = 1.5
                        break
            eff = self.get_type_effectiveness(move, opponent, attacker=active)
            estimated_damage = base_damage * stab * eff
            accuracy = self.get_accuracy(move)
            expected_damage = estimated_damage * accuracy
            # Apply 0.75 spread reduction if there are 2 active opponents
            if (
                self.is_spread_move(move)
                and battle
                and resolved_config
                and resolved_config.enable_spread_intelligence
            ):
                opps = [o for o in battle.opponent_active_pokemon if o]
                if len(opps) == 2:
                    expected_damage *= 0.75
            return expected_damage
        except Exception:
            return 0.0

    def check_move_will_ko(
        self,
        move: Move,
        active: Optional[Pokemon],
        opponent: Optional[Pokemon],
        battle: Optional[DoubleBattle] = None,
        config=None,
    ) -> bool:
        expected_damage = self.get_expected_damage(
            move, active, opponent, battle, config=config
        )
        if expected_damage == 0.0 or not opponent:
            return False
        try:
            opp_hp_fraction = getattr(opponent, "current_hp_fraction", 1.0)
            if opp_hp_fraction is None:
                return False
            opp_max_hp = self.estimate_opponent_max_hp(opponent)
            return expected_damage >= (opp_hp_fraction * opp_max_hp)
        except Exception:
            return False

    def is_spread_move(self, move: Move) -> bool:
        target_type = getattr(move, "deduced_target", None)
        if target_type in (Target.ALL, Target.ALL_ADJACENT, Target.ALL_ADJACENT_FOES):
            return True
        target_str = getattr(move, "target", "")
        if target_str in ("allAdjacent", "allAdjacentFoes", "all"):
            return True
        return False

    def _slot_in_opp_pressure(
        self, active_idx: int, battle
    ) -> bool:
        """Phase SPREAD-5: instance wrapper around
        ``compute_opp_pressure_state_for_battle``.
        The ``active_idx`` argument is unused but
        is kept for symmetry with future slot-
        specific opp-pressure rules. The current
        rule is per-turn (any live opp), not per-
        slot, because Wide Guard protects both
        slots in a doubles battle.
        """
        del active_idx  # currently unused
        return compute_opp_pressure_state_for_battle(battle)

    def _planner_spread_defense_partner_threat_relevant(
        self, decision, active_idx: int, battle
    ) -> bool:
        """PLANNER-SPREAD-8B: partner threat relevance guard.

        Returns True if applying the WG bonus would provide
        meaningful team value. The guard is threat-based, not
        pure HP-based:

        - If BOTH allies are at/above the threat threshold
          (default 0.7 HP), there is no immediate spread-move
          danger. Both can tank a hit. Suppress (no team value).
        - If WG user is below threshold (self-preservation
          scenario), allow.
        - If partner is below threshold (capitalization
          scenario), allow.
        - If partner is fainted (None) and WG user is also
          safe, suppress (no team benefit, only individual).
        - If partner is fainted and WG user is threatened,
          allow (self-preservation).

        The threshold represents the HP below which a single
        spread hit is meaningful (typical Rock Slide or Heat
        Wave does 30-50% HP). A mon with >=70% HP can
        comfortably tank one hit.
        """
        threshold = float(getattr(
            self.config,
            "planner_spread_defense_partner_threat_threshold", 0.7
        ))

        # Get both mons (active_idx is the WG user's slot, partner is other slot)
        try:
            active_pokemon = getattr(battle, "active_pokemon", None) or []
        except Exception:
            active_pokemon = []
        try:
            partner_idx = 1 - int(active_idx)
        except Exception:
            partner_idx = 1 - active_idx

        wg_user_mon = None
        if 0 <= active_idx < len(active_pokemon):
            wg_user_mon = active_pokemon[active_idx]
        partner_mon = None
        if 0 <= partner_idx < len(active_pokemon):
            partner_mon = active_pokemon[partner_idx]

        # Get HP fractions defensively
        def _safe_hp(mon):
            if mon is None:
                return None
            if getattr(mon, "fainted", False):
                return 0.0
            hp = getattr(mon, "current_hp_fraction", None)
            if hp is None:
                return 1.0
            try:
                return float(hp)
            except (TypeError, ValueError):
                # Mock or non-numeric; treat as healthy
                return 1.0

        wg_user_hp = _safe_hp(wg_user_mon)
        partner_hp = _safe_hp(partner_mon)

        # Partner fainted (None or 0 HP)
        if partner_hp is None or partner_hp <= 0.0:
            # Only allow if WG user is also threatened (self-preservation)
            if wg_user_hp is None or wg_user_hp >= threshold:
                return False
            return True

        # Both alive. Check if at least one is threatened.
        wg_user_threatened = wg_user_hp < threshold
        partner_threatened = partner_hp < threshold

        # If at least one is threatened, allow WG (team value)
        if wg_user_threatened or partner_threatened:
            return True

        # Neither threatened: no immediate danger, suppress
        return False

    def _planner_spread_defense_eligible(
        self, order, active_idx: int, battle
    ) -> bool:
        """PLANNER-SPREAD-2: return True if the
        Wide Guard boost should apply to this order.

        Guards (all must pass):
        0. ``enable_planner_spread_defense_scoring`` is True
           (master switch).
        1. ``enable_planner_intent_detector`` is True
           (the detector must be running).
        2. The current turn's IntentDecision is set and
           intent == "SPREAD_DEFENSE".
        3. ``order`` is Wide Guard.
        4. Confidence >= ``planner_spread_defense_min_confidence``.
        5. Opp pressure detected (reuse ``_slot_in_opp_pressure``).
        6. Anti-spam: per-game pick count
           < ``planner_spread_defense_max_picks_per_game`` AND
           turns since last pick >=
           ``planner_spread_defense_min_turn_between_picks``.
        """
        # Guard 0: master switch
        if not getattr(
            self.config, "enable_planner_spread_defense_scoring", False
        ):
            return False
        # Guard 1: detector must be running
        if not getattr(
            self.config, "enable_planner_intent_detector", False
        ):
            return False
        # Guard 2: intent decision exists and is SPREAD_DEFENSE
        # Read from battle (where choose_move attaches it) or self
        decision = getattr(battle, "_planner_intent_decision", None)
        if decision is None:
            decision = getattr(self, "_planner_intent_decision", None)
        if decision is None:
            return False
        if getattr(decision, "intent", None) != "SPREAD_DEFENSE":
            return False
        # Guard 3: move is Wide Guard
        if not isinstance(getattr(order, "order", None), Move):
            return False
        move_id_raw = getattr(order.order, "id", "")
        move_id_norm = (
            str(move_id_raw or "").lower()
            .replace(" ", "").replace("-", "")
            .replace("_", "").replace("'", "")
        )
        if move_id_norm != "wideguard":
            return False
        # Guard 4: confidence
        min_conf = float(getattr(
            self.config, "planner_spread_defense_min_confidence", 0.5
        ))
        if float(getattr(decision, "confidence", 0.0)) < min_conf:
            return False
        # Guard 5: opp pressure (PLANNER-SPREAD-3d: use detector's
        # snapshot if available). poke-env calls choose_move multiple
        # times per turn, so the live state at scoring time can
        # differ from the state at detect time. Prefer the snapshot
        # stored on the decision; fall back to live state for legacy
        # decisions (mocks / pre-SPREAD-3d objects) that don't carry it.
        use_snapshot = False
        snapshot_val = False
        try:
            from bot_doubles_intent_classifier import IntentDecision as _ID
            if isinstance(decision, _ID):
                use_snapshot = True
                snapshot_val = bool(
                    getattr(decision, "opp_pressure", False)
                )
        except Exception:
            pass
        if use_snapshot:
            if not snapshot_val:
                return False
        else:
            if not self._slot_in_opp_pressure(active_idx, battle):
                return False
        # Guard 6: partner threat relevance (PLANNER-SPREAD-8B)
        # Suppress WG boost when the team is not in actual
        # spread-move danger (both mons at/above threat threshold).
        # Pure HP-based guards would be too aggressive; this guard
        # uses threat-relevance: is there a team value from
        # preventing spread damage?
        if not self._planner_spread_defense_partner_threat_relevant(
            decision, active_idx, battle
        ):
            return False
        # Guard 7: anti-spam
        battle_tag = getattr(battle, "battle_tag", "")
        if not battle_tag:
            return False
        # Initialize per-game pick counter if needed
        if not hasattr(self, "_planner_spread_defense_picks_per_game"):
            self._planner_spread_defense_picks_per_game = {}
        if not hasattr(self, "_planner_spread_defense_last_pick_turn"):
            self._planner_spread_defense_last_pick_turn = {}
        max_picks = int(getattr(
            self.config,
            "planner_spread_defense_max_picks_per_game", 3
        ))
        current_picks = self._planner_spread_defense_picks_per_game.get(
            battle_tag, 0
        )
        if current_picks >= max_picks:
            return False
        min_gap = int(getattr(
            self.config,
            "planner_spread_defense_min_turn_between_picks", 2
        ))
        current_turn = int(getattr(battle, "turn", 0) or 0)
        last_pick_turn = self._planner_spread_defense_last_pick_turn.get(
            battle_tag, -999
        )
        if current_turn - last_pick_turn < min_gap:
            return False
        return True

    def _planner_spread_defense_record_pick(
        self, battle, active_idx: int,
    ) -> None:
        """PLANNER-SPREAD-2: record a Wide Guard pick for anti-spam.
        PLANNER-SPREAD-3d: also track the bonus magnitude so the
        audit can verify the bonus was applied.
        """
        battle_tag = getattr(battle, "battle_tag", "")
        if not battle_tag:
            return
        if not hasattr(self, "_planner_spread_defense_picks_per_game"):
            self._planner_spread_defense_picks_per_game = {}
        if not hasattr(self, "_planner_spread_defense_last_pick_turn"):
            self._planner_spread_defense_last_pick_turn = {}
        if not hasattr(self, "_planner_spread_defense_bonus_applied_per_game"):
            self._planner_spread_defense_bonus_applied_per_game = {}
        self._planner_spread_defense_picks_per_game[battle_tag] = (
            self._planner_spread_defense_picks_per_game.get(battle_tag, 0) + 1
        )
        self._planner_spread_defense_last_pick_turn[battle_tag] = int(
            getattr(battle, "turn", 0) or 0
        )
        # Track bonus magnitude (cumulative for the battle)
        bonus = float(
            getattr(
                self.config, "planner_spread_defense_wg_bonus", 0.0
            )
        )
        self._planner_spread_defense_bonus_applied_per_game[battle_tag] = (
            self._planner_spread_defense_bonus_applied_per_game.get(
                battle_tag, 0.0
            ) + bonus
        )

    def _setup_intent_speed_setup_eligible(
        self, order, active_idx: int, battle
    ) -> bool:
        """Phase SETUP-3A: return True if the bonus
        should apply to this order.

        Guards (all must pass):
        1. ``enable_setup_intent_policy`` is True.
        2. ``order`` is a Tailwind or Trick Room move.
        3. Active user survives this turn (HP > 25%
           OR ``setup_intent_require_survival=False``).
        4. Speed-setup is not already active on the
           field (no Tailwind, no Trick Room up).
        5. User is not visibly Taunted or Encored
           (information-integrity: only visible).
        6. Anti-spam: per-game pick count
           < ``setup_intent_max_picks_per_game`` AND
           turns since last pick >=
           ``setup_intent_min_turn_between_picks``.

        KO priority suppression: the bonus is
        implicitly suppressed when a damage move in
        the same slot would still score higher than
        setup + bonus. The natural score ranking
        handles this without an explicit guard.
        """
        # Guard 1: master switch
        if not getattr(
            self.config, "enable_setup_intent_policy", False
        ):
            return False
        # Guard 2: move is Tailwind or Trick Room
        if not isinstance(getattr(order, "order", None), Move):
            return False
        move_id = _normalize_move_id_for_spread_defense(
            getattr(order.order, "id", "")
        )
        if move_id not in ("tailwind", "trickroom"):
            return False
        # Guard 3: active user survives
        if getattr(
            self.config, "setup_intent_require_survival", True
        ):
            battle_tag = getattr(battle, "battle_tag", "")
            if self._expected_to_faint_before_moving.get(
                battle_tag, {}
            ).get(active_idx, False):
                return False
            try:
                our_active = (
                    battle.active_pokemon[active_idx]
                    if active_idx < len(battle.active_pokemon)
                    else None
                )
                if our_active is not None:
                    hp_frac = (
                        our_active.current_hp_fraction
                        if hasattr(
                            our_active, "current_hp_fraction"
                        )
                        else (
                            our_active.current_hp
                            / max(1, our_active.max_hp)
                            if hasattr(our_active, "current_hp")
                            and hasattr(our_active, "max_hp")
                            else 1.0
                        )
                    )
                    if hp_frac is not None and hp_frac < 0.25:
                        return False
            except Exception:
                # If we can't determine HP, be safe and
                # let the bonus fire (assume alive).
                pass
        # Guard 4: speed-setup not already active.
        # Phase SETUP-6A: fixed to also check
        # ``battle.fields``. Tailwind is a
        # ``side_condition``; Trick Room is a
        # ``field`` effect. The previous version
        # only checked ``side_conditions``, so
        # it missed already-active Trick Room.
        # Test: 96495 T3 picked TR when fields
        # had ``trick_room``. See SETUP-6
        # report and SETUP-6A fix.
        # Phase SETUP-6A v2: poke-env exposes
        # ``battle.fields`` as a list of
        # ``Field`` enum objects. Each has a
        # ``.name`` attribute (e.g. ``TRICK_ROOM``).
        # Need to convert to normalized strings.
        try:
            our_side = (
                getattr(battle, "side_conditions", None) or {}
            )
            sc_has_tw = "tailwind" in our_side
            sc_has_tr = "trickroom" in our_side
            our_fields = (
                getattr(battle, "fields", None) or []
            )
            fld_has_tw = False
            fld_has_tr = False
            for f in our_fields:
                # Convert to normalized string
                if hasattr(f, "name"):
                    f_str = f.name.lower()
                else:
                    f_str = str(f).lower()
                f_str = (
                    f_str.replace("_", "").replace(" ", "")
                )
                if "tailwind" in f_str:
                    fld_has_tw = True
                if "trickroom" in f_str:
                    fld_has_tr = True
            if sc_has_tw or sc_has_tr or fld_has_tw or fld_has_tr:
                return False
        except Exception:
            pass
        # Guard 5: not visibly Taunted or Encored
        try:
            our_active = (
                battle.active_pokemon[active_idx]
                if active_idx < len(battle.active_pokemon)
                else None
            )
            if our_active is not None:
                if getattr(our_active, "taunted", False):
                    return False
                if getattr(our_active, "encored", False):
                    return False
                # Some poke-env versions use
                # ``must_recharge`` etc. but Taunt/
                # Encore are the relevant volátiles
                # for status-move setup.
        except Exception:
            pass
        # Guard 6: anti-spam
        battle_tag = getattr(battle, "battle_tag", "")
        picks = self._setup_intent_picks_per_game.get(
            battle_tag, 0
        )
        if picks >= getattr(
            self.config,
            "setup_intent_max_picks_per_game",
            3,
        ):
            return False
        current_turn = getattr(battle, "turn", 0)
        last_turn = self._setup_intent_last_pick_turn.get(
            battle_tag, -999
        )
        if current_turn - last_turn < getattr(
            self.config,
            "setup_intent_min_turn_between_picks",
            2,
        ):
            return False
        # Guard 7: KO priority. Phase SETUP-7A.
        # SETUP-7 20-pair preview showed 12.9%
        # over-select rate (4/31 setup picks) where
        # the bot picked setup when the opp was
        # in KO range (opp_hp 0.01-0.28 with
        # top_dmg 554-587). The SETUP-2 design
        # documented this as "implicit via
        # natural ranking" but that wasn't
        # strong enough — the joint scoring
        # sometimes picked setup over a
        # near-guaranteed KO. This guard
        # explicitly checks opp's lowest active
        # HP and suppresses the setup bonus if
        # the opp is in KO range. Threshold
        # ``setup_intent_ko_opp_hp_threshold``
        # (default 0.30). Catches the 4 SETUP-7
        # over-select cases:
        # - battle 96525 T4: opp_hp 0.04
        # - battle 96527 T3: opp_hp 0.28
        # - battle 96534 T5: opp_hp 0.01
        # - battle 96555 T3: opp_hp 0.20
        if getattr(
            self.config,
            "setup_intent_require_ko_check",
            True,
        ):
            opp_hp_min = None
            try:
                ss = getattr(
                    battle, "state_snapshot", None
                )
                if ss is not None:
                    for hp in (
                        ss.get("opp_active_hp_fraction", [])
                        or []
                    ):
                        if hp is None:
                            continue
                        if (
                            opp_hp_min is None
                            or hp < opp_hp_min
                        ):
                            opp_hp_min = hp
                if opp_hp_min is None:
                    # Fallback: try poke-env directly
                    for opp in (
                        getattr(
                            battle,
                            "opponent_active_pokemon",
                            None,
                        )
                        or []
                    ):
                        if opp is None:
                            continue
                        hp = (
                            getattr(
                                opp,
                                "current_hp_fraction",
                                None,
                            )
                        )
                        if hp is None:
                            continue
                        if (
                            opp_hp_min is None
                            or hp < opp_hp_min
                        ):
                            opp_hp_min = hp
            except Exception:
                opp_hp_min = None
            threshold = getattr(
                self.config,
                "setup_intent_ko_opp_hp_threshold",
                0.30,
            )
            if (
                opp_hp_min is not None
                and opp_hp_min < threshold
            ):
                return False
        return True

    def record_setup_intent_pick(
        self, battle_tag: str, turn: int
    ):
        """Phase SETUP-3A: record a setup-move pick
        for the anti-spam guards. Called from
        ``choose_move`` seam when the selected joint
        order includes a setup-move action.
        """
        self._setup_intent_picks_per_game[battle_tag] = (
            self._setup_intent_picks_per_game.get(battle_tag, 0)
            + 1
        )
        self._setup_intent_last_pick_turn[battle_tag] = turn

    # Phase CONTROL-4B: anti-setup disruption intent
    # policy. Adds a positive score to Taunt / Encore
    # / Disable / Quash candidates when opp has a
    # visible setup/control/status signal. Per
    # AGENTS.md: visible-only, no species guessing.
    # Default OFF. See
    # logs/phaseCONTROL3_anti_setup_design.md and
    # logs/phaseCONTROL4A_anti_setup_dryrun.md.
    ANTI_SETUP_DISRUPTION_TARGETS = frozenset({
        "taunt", "encore", "disable", "quash",
    })
    ANTI_SETUP_STAT_BOOST_MOVES = frozenset({
        "swordsdance", "nastyplot", "dragondance",
        "calmmind", "bulkup", "quiverdance",
        "shellsmash", "workup", "agility",
        "rockpolish", "geomancy", "honeclaws",
        "charge", "growth", "howl", "doubleteam",
        "cosmicpower", "irondefense", "acidarmor",
        "autotomize", "minimize", "shiftgear",
    })
    ANTI_SETUP_HIGH_BP_MOVES = frozenset({
        "earthquake", "closecombat", "flareblitz",
        "wildcharge", "boomburst", "moonblast",
        "heatwave", "makeitrain", "dracometeor",
        "sludgewave", "leafstorm", "thunderbolt",
        "thunder", "icebeam", "psychic", "focusblast",
        "hydropump", "fireblast", "shadowball",
        "energyball", "darkpulse", "stoneedge",
        "earthpower", "flashcannon", "ironhead",
        "knockoff", "uturn", "voltswitch", "rapidspin",
    })

    def _anti_setup_disruption_eligible(
        self, order, active_idx: int, battle
    ) -> bool:
        """Phase CONTROL-4B: return True if the
        anti-setup disruption bonus should apply
        to this order.

        Guards (all must pass):
        0. ``enable_anti_setup_disruption_intent``
           is True (master switch).
        1. ``order`` is one of: taunt, encore,
           disable, quash.
        2. Active user survives this turn
           (HP > 25% or
           ``anti_setup_disruption_require_survival=False``).
        3. The action targets a visible opp mon
           (slot 1 or 2 in poke-env convention).
        4. Opp has at least 1.0 visible setup
           signal (stat-boost used, field TW/TR
           active, opp revealed setup move, etc.)
        5. Anti-spam: per-game pick count
           < ``anti_setup_disruption_max_picks_per_game``
           AND turns since last pick >=
           ``anti_setup_disruption_min_turn_between_picks``.
        """
        # Guard 0: master switch
        if not getattr(
            self.config,
            "enable_anti_setup_disruption_intent",
            False,
        ):
            return False
        # Guard 1: move is one of 4 anti-setup moves
        if not isinstance(getattr(order, "order", None), Move):
            return False
        move_id_raw = getattr(order.order, "id", "")
        move_id_norm = (
            str(move_id_raw or "").lower()
            .replace(" ", "").replace("-", "")
            .replace("_", "").replace("'", "")
        )
        if move_id_norm not in self.ANTI_SETUP_DISRUPTION_TARGETS:
            return False
        # Guard 2: active user survives
        if getattr(
            self.config,
            "anti_setup_disruption_require_survival",
            True,
        ):
            battle_tag = getattr(battle, "battle_tag", "")
            if self._expected_to_faint_before_moving.get(
                battle_tag, {}
            ).get(active_idx, False):
                return False
            try:
                our_active = (
                    battle.active_pokemon[active_idx]
                    if active_idx < len(battle.active_pokemon)
                    else None
                )
                if our_active is not None:
                    hp_frac = (
                        our_active.current_hp_fraction
                        if hasattr(our_active, "current_hp_fraction")
                        else (
                            our_active.current_hp
                            / max(1, our_active.max_hp)
                            if hasattr(our_active, "current_hp")
                            and hasattr(our_active, "max_hp")
                            else 1.0
                        )
                    )
                    if hp_frac is not None and hp_frac < 0.25:
                        return False
            except Exception:
                pass
        # Guard 3: target is opp slot 1 or 2
        # poke-env convention: target=1 means opp slot 0,
        # target=2 means opp slot 1. target=-1 self,
        # target=-2 ally.
        target_str = getattr(order, "move_target", None)
        target_norm = (
            str(target_str or "").lstrip("+-")
            if target_str is not None else ""
        )
        if target_str not in (1, 2):
            return False
        # Guard 4: opp has visible setup signal
        signal = self._compute_opp_setup_signal(
            battle, target_slot=int(target_str) - 1,
            scoring_move=move_id_norm,
        )
        min_signal = float(getattr(
            self.config,
            "anti_setup_disruption_min_opp_setup_signal",
            1.0,
        ))
        if signal < min_signal:
            return False
        # Guard 5: anti-spam
        battle_tag = getattr(battle, "battle_tag", "")
        picks = self._anti_setup_disrupt_picks_per_game.get(
            battle_tag, 0
        )
        max_picks = int(getattr(
            self.config,
            "anti_setup_disruption_max_picks_per_game",
            2,
        ))
        if picks >= max_picks:
            return False
        current_turn = getattr(battle, "turn", 0)
        last_turn = self._anti_setup_disrupt_last_pick_turn.get(
            battle_tag, -999
        )
        min_gap = int(getattr(
            self.config,
            "anti_setup_disruption_min_turn_between_picks",
            3,
        ))
        if current_turn - last_turn < min_gap:
            return False
        return True

    def _anti_trick_room_response_eligible(
        self, order, active_idx: int, battle
    ) -> bool:
        """PLANNER-ANTI-TR: return True if the
        anti-TR disruption bonus should apply.

        Guards (all must pass):
        0. ``enable_anti_trick_room_response``
           is True (master switch).
        1. ``order`` is Taunt, Encore, or Disable
           (NOT Quash — Quash is for setup disruption, not TR).
        2. The IntentDetector fired ANTI_TRICK_ROOM
           (read from battle._planner_intent_decision).
        3. Active user survives this turn
           (HP > 25% or
           ``anti_trick_room_response_require_survival=False``).
        4. Target is opp slot 1 or 2.
        5. Anti-spam: per-game pick count
           < ``anti_trick_room_response_max_picks_per_game``
           AND turns since last pick
           >= ``anti_trick_room_response_min_turn_between_picks``.
        """
        # Guard 0: master switch
        if not getattr(
            self.config, "enable_anti_trick_room_response", False
        ):
            return False
        # Guard 1: move is Taunt/Encore/Disable
        if not isinstance(getattr(order, "order", None), Move):
            return False
        move_id_raw = getattr(order.order, "id", "")
        move_id_norm = (
            str(move_id_raw or "").lower()
            .replace(" ", "").replace("-", "")
            .replace("_", "").replace("'", "")
        )
        if move_id_norm not in ("taunt", "encore", "disable"):
            return False
        # Guard 2: ANTI_TRICK_ROOM intent fired
        decision = getattr(battle, "_planner_intent_decision", None)
        if decision is None:
            return False
        if getattr(decision, "intent", None) != "ANTI_TRICK_ROOM":
            return False
        # Guard 3: active user survives
        if getattr(
            self.config,
            "anti_trick_room_response_require_survival", True
        ):
            try:
                our_active = (
                    battle.active_pokemon[active_idx]
                    if active_idx < len(battle.active_pokemon)
                    else None
                )
                if our_active is not None:
                    hp_frac = getattr(
                        our_active, "current_hp_fraction", 1.0
                    )
                    if hp_frac is not None and hp_frac < 0.25:
                        return False
            except Exception:
                pass
        # Guard 4: target is opp slot 1 or 2
        target_str = getattr(order, "move_target", None)
        if target_str not in (1, 2):
            return False
        # Guard 6 (Phase CONTROL-PRIORITY-2B): target is the
        # actual TR setter. When enable_anti_tr_target_aware_scoring
        # is True, the bonus is only applied when the target's
        # revealed moves include Trick Room. Revealed-only (no
        # species inference). Independent of CONTROL-PRIORITY-2A.
        if getattr(
            self.config,
            "enable_anti_tr_target_aware_scoring", False
        ):
            try:
                opps = getattr(battle, "opponent_active_pokemon", []) or []
                target_slot = int(target_str) - 1
                if 0 <= target_slot < len(opps):
                    target_opp = opps[target_slot]
                    if target_opp and not ability_rules.opp_has_trick_room(target_opp):
                        return False
            except Exception:
                # Be safe: if we can't determine the target's
                # revealed moves, default to the existing
                # behavior (allow bonus) to avoid breaking.
                pass
        # Guard 5: anti-spam
        battle_tag = getattr(battle, "battle_tag", "")
        if not battle_tag:
            return False
        if not hasattr(
            self, "_anti_trick_room_response_picks_per_game"
        ):
            self._anti_trick_room_response_picks_per_game = {}
        if not hasattr(
            self, "_anti_trick_room_response_last_pick_turn"
        ):
            self._anti_trick_room_response_last_pick_turn = {}
        max_picks = int(getattr(
            self.config,
            "anti_trick_room_response_max_picks_per_game", 2
        ))
        current_picks = (
            self._anti_trick_room_response_picks_per_game
            .get(battle_tag, 0)
        )
        if current_picks >= max_picks:
            return False
        current_turn = int(getattr(battle, "turn", 0) or 0)
        last_turn = self._anti_trick_room_response_last_pick_turn.get(
            battle_tag, -999
        )
        min_gap = int(getattr(
            self.config,
            "anti_trick_room_response_min_turn_between_picks", 3
        ))
        if current_turn - last_turn < min_gap:
            return False
        return True

    def _anti_trick_room_ko_pressure_eligible(
        self, order, active_idx: int, battle
    ) -> bool:
        """PLANNER-ANTI-TR: return True if the
        KO pressure bonus should apply to a damaging move.

        When ANTI_TRICK_ROOM is fired, the bot should favor
        damaging moves to KO the TR setter before TR expires.
        The bonus is smaller than the anti-setup bonus
        (200 vs 100) to avoid over-prioritizing damage.

        Guards (all must pass):
        0. ``enable_anti_trick_room_response`` is True.
        1. ``order`` is a damaging move (BP > 0).
        2. ANTI_TRICK_ROOM intent fired.
        3. Target is opp slot 1 or 2.
        4. Anti-spam.
        """
        # Guard 0: master switch
        if not getattr(
            self.config, "enable_anti_trick_room_response", False
        ):
            return False
        # Guard 1: damaging move
        if not isinstance(getattr(order, "order", None), Move):
            return False
        bp = getattr(order.order, "base_power", 0)
        if bp is None or bp <= 0:
            return False
        # Guard 2: ANTI_TRICK_ROOM intent
        decision = getattr(battle, "_planner_intent_decision", None)
        if decision is None:
            return False
        if getattr(decision, "intent", None) != "ANTI_TRICK_ROOM":
            return False
        # Guard 3: target is opp slot 1 or 2
        target_str = getattr(order, "move_target", None)
        if target_str not in (1, 2):
            return False
        # Guard 4: anti-spam
        battle_tag = getattr(battle, "battle_tag", "")
        if not battle_tag:
            return False
        if not hasattr(
            self, "_anti_trick_room_ko_picks_per_game"
        ):
            self._anti_trick_room_ko_picks_per_game = {}
        if not hasattr(
            self, "_anti_trick_room_ko_last_pick_turn"
        ):
            self._anti_trick_room_ko_last_pick_turn = {}
        max_picks = int(getattr(
            self.config,
            "anti_trick_room_ko_max_picks_per_game", 3
        ))
        current_picks = (
            self._anti_trick_room_ko_picks_per_game.get(battle_tag, 0)
        )
        if current_picks >= max_picks:
            return False
        current_turn = int(getattr(battle, "turn", 0) or 0)
        last_turn = self._anti_trick_room_ko_last_pick_turn.get(
            battle_tag, -999
        )
        min_gap = int(getattr(
            self.config,
            "anti_trick_room_ko_min_turn_between_picks", 1
        ))
        if current_turn - last_turn < min_gap:
            return False
        return True

    def _record_anti_trick_room_response_pick(
        self, battle, active_idx: int
    ) -> None:
        """PLANNER-ANTI-TR: record a Taunt/Encore/Disable pick."""
        battle_tag = getattr(battle, "battle_tag", "")
        if not battle_tag:
            return
        if not hasattr(
            self, "_anti_trick_room_response_picks_per_game"
        ):
            self._anti_trick_room_response_picks_per_game = {}
        if not hasattr(
            self, "_anti_trick_room_response_last_pick_turn"
        ):
            self._anti_trick_room_response_last_pick_turn = {}
        self._anti_trick_room_response_picks_per_game[battle_tag] = (
            self._anti_trick_room_response_picks_per_game
            .get(battle_tag, 0) + 1
        )
        self._anti_trick_room_response_last_pick_turn[battle_tag] = (
            int(getattr(battle, "turn", 0) or 0)
        )

    def _record_anti_trick_room_ko_pick(
        self, battle, active_idx: int
    ) -> None:
        """PLANNER-ANTI-TR: record a KO pressure damaging pick."""
        battle_tag = getattr(battle, "battle_tag", "")
        if not battle_tag:
            return
        if not hasattr(
            self, "_anti_trick_room_ko_picks_per_game"
        ):
            self._anti_trick_room_ko_picks_per_game = {}
        if not hasattr(
            self, "_anti_trick_room_ko_last_pick_turn"
        ):
            self._anti_trick_room_ko_last_pick_turn = {}
        self._anti_trick_room_ko_picks_per_game[battle_tag] = (
            self._anti_trick_room_ko_picks_per_game
            .get(battle_tag, 0) + 1
        )
        self._anti_trick_room_ko_last_pick_turn[battle_tag] = (
            int(getattr(battle, "turn", 0) or 0)
        )

    def _record_anti_tr_target_debug(
        self,
        order,
        active_idx: int,
        battle,
        eligible: bool,
        block_reason: str = "",
        bonus_applied: float = 0.0,
        mechanics_block_enabled: bool = False,
        blocked_by_magic_bounce: bool = False,
        blocked_by_good_as_gold: bool = False,
        blocked_by_aroma_veil: bool = False,
        blocked_by_aroma_veil_ally: bool = False,
    ) -> None:
        """Phase CONTROL-PRIORITY-2D: record anti-TR candidate
        debug info for runtime audit visibility.

        Stores a JSON-safe dict on self._anti_tr_target_debug_per_battle
        (per battle tag). The audit logger reads this list and
        writes it to the snapshot as ``anti_tr_target_debug``.

        Pure observation. No scoring change. No defaults change.
        """
        battle_tag = getattr(battle, "battle_tag", "")
        if not battle_tag:
            return
        if not hasattr(self, "_anti_tr_target_debug_per_battle"):
            self._anti_tr_target_debug_per_battle = {}
        # Target info
        target_slot = getattr(order, "move_target", None)
        target_species = None
        target_revealed_moves = []
        target_has_revealed_trickroom = False
        try:
            opps = getattr(battle, "opponent_active_pokemon", []) or []
            if isinstance(target_slot, int) and 0 <= target_slot - 1 < len(opps):
                target_opp = opps[target_slot - 1]
                if target_opp is not None:
                    target_species = getattr(target_opp, "species", None)
                    try:
                        moves = getattr(target_opp, "moves", None)
                        if moves:
                            if hasattr(moves, "keys"):
                                target_revealed_moves = list(moves.keys())
                            else:
                                target_revealed_moves = list(moves)
                    except Exception:
                        target_revealed_moves = []
                    target_has_revealed_trickroom = (
                        ability_rules.opp_has_trick_room(target_opp)
                    )
        except Exception:
            pass
        # Move info
        move_id = None
        try:
            inner_move = getattr(order, "order", None)
            if inner_move is not None:
                move_id = getattr(inner_move, "id", None)
        except Exception:
            move_id = None
        # 2B target-aware info
        target_aware_enabled = bool(
            getattr(self.config, "enable_anti_tr_target_aware_scoring", False)
        )
        target_aware_allowed = True
        if target_aware_enabled:
            try:
                opps = getattr(battle, "opponent_active_pokemon", []) or []
                if isinstance(target_slot, int) and 0 <= target_slot - 1 < len(opps):
                    target_opp = opps[target_slot - 1]
                    if target_opp and not ability_rules.opp_has_trick_room(target_opp):
                        target_aware_allowed = False
            except Exception:
                target_aware_allowed = True
        # Build debug dict
        debug = {
            "move": move_id,
            "slot": active_idx,
            "target_slot": target_slot,
            "target_species": target_species,
            "target_revealed_moves": target_revealed_moves,
            "target_has_revealed_trickroom": bool(target_has_revealed_trickroom),
            "target_aware_enabled": target_aware_enabled,
            "target_aware_allowed": target_aware_allowed,
            "mechanics_block_enabled": bool(mechanics_block_enabled),
            "blocked_by_magic_bounce": bool(blocked_by_magic_bounce),
            "blocked_by_good_as_gold": bool(blocked_by_good_as_gold),
            "blocked_by_aroma_veil": bool(blocked_by_aroma_veil),
            "blocked_by_aroma_veil_ally": bool(blocked_by_aroma_veil_ally),
            "eligible": bool(eligible),
            "block_reason": block_reason,
            "bonus_applied": float(bonus_applied),
        }
        self._anti_tr_target_debug_per_battle.setdefault(
            battle_tag, []
        ).append(debug)

    def _run_planner_intent_detector(self, battle):
        """PLANNER-IMPL-2: per-turn intent detector runner.

        Pure observation. No scoring change. No side effects
        beyond storing the decision on self for the audit logger.

        Reads visible state only (per AGENTS.md):
        - opp_revealed_moves: from poke-env's opponent_active_pokemon
        - fields: from battle.fields (e.g., "trick_room")
        - side_conditions: from battle.side_conditions (e.g., "tailwind")
        - opp_used_tr / opp_used_tw / opp_used_stat_boost: counters
        - opp_pressure: from existing _slot_in_opp_pressure
        - active_user_hp_fraction: from battle.active_pokemon[0].hp
        - expected_to_faint: from _expected_to_faint_before_moving
        - target_already_taunted: best-effort from battle state

        Returns an IntentDecision or None on error.
        """
        try:
            from bot_doubles_intent_classifier import (
                IntentDetector, IntentDecision,
            )
        except ImportError:
            return None

        try:
            # Build context (visible-only)
            ctx = {
                "opp_revealed_moves": self._safe_opp_revealed_moves(battle),
                "fields": self._safe_field_names(battle),
                "side_conditions": self._safe_side_condition_names(battle),
                "opp_used_tr": self._safe_get_last_opp_signal(
                    battle, "trickroom"
                ),
                "opp_used_tw": self._safe_get_last_opp_signal(
                    battle, "tailwind"
                ),
                "opp_used_stat_boost": self._safe_get_last_opp_signal(
                    battle, "stat_boost"
                ),
                "opp_pressure": self._safe_opp_pressure(battle),
                "active_user_hp_fraction": self._safe_active_hp_fraction(
                    battle, 0
                ),
                "expected_to_faint": self._safe_expected_to_faint(
                    battle, 0
                ),
                "target_already_taunted": False,
            }
            min_conf = float(getattr(
                self.config, "planner_intent_min_confidence", 0.5
            ))
            det = IntentDetector(min_confidence=min_conf)
            return det.detect(ctx)
        except Exception:
            # Defensive: detector failure must NEVER affect scoring
            return None

    def _safe_opp_revealed_moves(self, battle):
        """Collect opp revealed moves from poke-env battle state."""
        try:
            opp_actives = (
                getattr(battle, "opponent_active_pokemon", None) or []
            )
            moves = set()
            for pkmn in opp_actives:
                if pkmn is None:
                    continue
                pkmn_moves = getattr(pkmn, "moves", None) or {}
                for mv_id in pkmn_moves.keys():
                    if mv_id:
                        moves.add(str(mv_id))
            return list(moves)
        except Exception:
            return []

    def _safe_field_names(self, battle):
        """Extract field-effect names (lowercased)."""
        try:
            fields = getattr(battle, "fields", None) or []
            names = []
            for f in fields:
                if hasattr(f, "name"):
                    names.append(str(f.name).lower())
                else:
                    names.append(str(f).lower())
            return names
        except Exception:
            return []

    def _safe_side_condition_names(self, battle):
        """Extract side-condition names."""
        try:
            sc = getattr(battle, "side_conditions", None) or {}
            if isinstance(sc, dict):
                return [str(k).lower() for k in sc.keys()]
            return []
        except Exception:
            return []

    def _safe_get_last_opp_signal(self, battle, key):
        """Read from _last_opp_action_signals (or compatible)."""
        try:
            sig = getattr(self, "_last_opp_action_signals", None) or {}
            return bool(sig.get(key, False))
        except Exception:
            return False

    def _safe_opp_pressure(self, battle):
        """Reuse existing _slot_in_opp_pressure helper (best-effort)."""
        try:
            return bool(self._slot_in_opp_pressure(0, battle))
        except Exception:
            return False

    def _safe_active_hp_fraction(self, battle, slot):
        try:
            active = getattr(battle, "active_pokemon", None) or []
            if slot < 0 or slot >= len(active) or active[slot] is None:
                return 1.0
            p = active[slot]
            frac = getattr(p, "current_hp_fraction", None)
            if frac is not None:
                return float(frac)
            cur = getattr(p, "current_hp", None)
            mx = getattr(p, "max_hp", None)
            if cur is not None and mx and mx > 0:
                return float(cur) / float(mx)
            return 1.0
        except Exception:
            return 1.0

    def _safe_expected_to_faint(self, battle, slot):
        try:
            bt = getattr(battle, "battle_tag", "")
            slot_map = self._expected_to_faint_before_moving.get(bt, {})
            return bool(slot_map.get(slot, False))
        except Exception:
            return False

    def _compute_opp_setup_signal(
        self, battle, target_slot: int, scoring_move: str
    ) -> float:
        """Phase CONTROL-4B: compute visible opp
        setup signal sum for the given target
        slot. Per AGENTS.md: visible-only, no
        species guessing.

        Sources (all visible):
        - ``opponent_used_stat_boost_setup`` counter
        - ``opponent_used_tailwind`` /
          ``opponent_used_trickroom``
        - Field state TW/TR (visible, but
          ambiguous about who set it)
        - Revealed stat-boost moves
          (via ``get_known_revealed_moves`` helper
          in poke-env)
        - Revealed high-BP moves (Disable only)
        """
        score = 0.0
        # Counter signals (audit logger or similar)
        opp_revealed_counters = getattr(
            self, "_last_opp_action_signals", None
        ) or {}
        if opp_revealed_counters.get("stat_boost"):
            score += 1.0
        if opp_revealed_counters.get("tailwind"):
            score += 0.5
        if opp_revealed_counters.get("trickroom"):
            score += 0.5
        # Field state
        try:
            our_side = getattr(battle, "side_conditions", None) or {}
            sc_has_tw = "tailwind" in our_side
            sc_has_tr = "trickroom" in our_side
            our_fields = getattr(battle, "fields", None) or []
            fld_has_tw = False
            fld_has_tr = False
            for f in our_fields:
                if hasattr(f, "name"):
                    f_str = f.name.lower()
                else:
                    f_str = str(f).lower()
                f_str = f_str.replace("_", "").replace(" ", "")
                if "tailwind" in f_str:
                    fld_has_tw = True
                if "trickroom" in f_str:
                    fld_has_tr = True
            if sc_has_tw or fld_has_tw:
                score += 0.5
            if sc_has_tr or fld_has_tr:
                score += 0.5
        except Exception:
            pass
        # Revealed moves on opp (poke-env's
        # battle.opponent_active_pokemon[slot].moves
        # contains all revealed moves for that mon)
        try:
            opp_actives = (
                getattr(battle, "opponent_active_pokemon", None) or []
            )
            if 0 <= target_slot < len(opp_actives):
                opp_pkmn = opp_actives[target_slot]
                opp_moves = (
                    getattr(opp_pkmn, "moves", None) or {}
                )
                for mv_id, mv in opp_moves.items():
                    mv_norm = (
                        str(mv_id or "").lower()
                        .replace(" ", "").replace("-", "")
                        .replace("_", "").replace("'", "")
                    )
                    if mv_norm in self.ANTI_SETUP_STAT_BOOST_MOVES:
                        score += 1.0
                    elif (
                        mv_norm in self.ANTI_SETUP_HIGH_BP_MOVES
                        and scoring_move == "disable"
                    ):
                        # High-BP is only a signal for
                        # Disable.
                        score += 1.0
        except Exception:
            pass
        return score

    def record_anti_setup_disrupt_pick(
        self, battle_tag: str, turn: int
    ):
        """Phase CONTROL-4B: record an anti-setup
        disruption pick for the anti-spam guards.
        Called from ``choose_move`` seam when the
        selected joint order includes an anti-setup
        disruption action.
        """
        self._anti_setup_disrupt_picks_per_game[battle_tag] = (
            self._anti_setup_disrupt_picks_per_game.get(
                battle_tag, 0
            ) + 1
        )
        self._anti_setup_disrupt_last_pick_turn[battle_tag] = turn

    def _is_all_target_immune_damaging_spread(
        self, order, slot_idx: int, battle, config
    ) -> bool:
        """Check if an order is a damaging spread move with all opponent targets immune.

        Returns True if:
        - Order is a damaging Move
        - Move is a spread move targeting opponents (target == 0 or hits all adjacent foes)
        - All visible opponent Pokémon are immune to the move's type
        - Move has base_power > 0 (damaging)
        """
        if not order or not isinstance(order.order, Move):
            return False

        move = order.order
        if getattr(move, "base_power", 0) <= 0:
            return False  # not a damaging move

        if not self.is_spread_move(move):
            return False  # not a spread move

        # Check if move targets opponents (target 0 = all adjacent foes, or explicit spread)
        target_pos = getattr(order, "move_target", None)
        targets_opponents = (
            target_pos == 0  # all adjacent foes
            or (target_pos in (1, 2) and self.is_spread_move(move))  # spread to specific target
        )
        if not targets_opponents:
            return False

        attacker = battle.active_pokemon[slot_idx] if slot_idx < len(battle.active_pokemon) else None
        if not attacker:
            return False

        # Check immunity against all visible opponent Pokémon
        opponent_actives = [opp for opp in battle.opponent_active_pokemon if opp and not getattr(opp, "fainted", False)]
        if not opponent_actives:
            return False

        for opp in opponent_actives:
            try:
                immune, _ = is_type_immune(move, attacker, opp, battle)
                if not immune:
                    return False  # at least one target is not immune
            except Exception:
                # If we can't determine, assume not immune
                return False

        return True  # all targets immune

    def hits_ally(self, move: Move) -> bool:
        target_type = getattr(move, "deduced_target", None)
        if target_type in (Target.ALL, Target.ALL_ADJACENT):
            return True
        target_str = getattr(move, "target", "")
        if target_str in ("allAdjacent", "all"):
            return True
        return False

    def ally_safe_against_move(self, ally: Pokemon, move: Move) -> bool:
        try:
            if ally.damage_multiplier(move) == 0.0:
                return True
        except Exception:
            pass
        return False

    def score_action_raw_damage(
        self,
        order: SingleBattleOrder,
        active_idx: int,
        battle: DoubleBattle,
        config=None,
    ) -> float:
        resolved_config = config if config is not None else self.config
        active_mon = battle.active_pokemon[active_idx]
        if not active_mon or not isinstance(order.order, Move):
            return 0.0

        move = order.order
        target_pos = order.move_target

        target_mon = None
        if target_pos == 1:
            target_mon = battle.opponent_active_pokemon[0]
        elif target_pos == 2:
            target_mon = battle.opponent_active_pokemon[1]
        elif target_pos == -1:
            target_mon = battle.active_pokemon[0]
        elif target_pos == -2:
            target_mon = battle.active_pokemon[1]

        if target_pos in (1, 2) and not target_mon:
            return 0.0

        base_power = getattr(move, "base_power", 0)
        if base_power == 0:
            return 0.0

        # Phase 6.5: Type consumption check (Double Shock, Burn Up)
        if resolved_config.enable_type_consumption_tracking:
            if is_type_consumed(move, active_mon, battle, self._consumed_types):
                if self.verbose:
                    print(
                        f"[Type Consumed] {move.id} blocked — {getattr(active_mon, 'species', '?')} already used its {_TYPE_CONSUMING_MOVES.get(getattr(move, 'id', ''), '?')} type"
                    )
                return 0.0

        active_types = getattr(active_mon, "types", [])
        etype = get_effective_move_type(move, active_mon)
        stab_multiplier = 1.0
        if etype:
            for t in active_types:
                t_name = getattr(t, "name", str(t)).upper() if t else ""
                if t_name == etype:
                    stab_multiplier = 1.5
                    break
        accuracy_multiplier = self.get_accuracy(move)

        category = getattr(move, "category", None)
        category_name = getattr(category, "name", "PHYSICAL")
        if category_name == "SPECIAL":
            attacking_stat = self.get_boosted_stat(active_mon, "spa")
        else:
            attacking_stat = self.get_boosted_stat(active_mon, "atk")

        # Type Immunity safety check
        if resolved_config.enable_type_immunity_safety:
            if target_pos in (1, 2) and target_mon:
                immune, reason = is_type_immune(move, active_mon, target_mon, battle)
                if immune:
                    if self.verbose:
                        print(
                            f"[Immunity Block] {reason} | Attacker: {active_mon.species}, Target: {target_mon.species}"
                        )
                    return 0.0

        # Phase 6.3.3: Direct Known-Absorb Hard Safety
        if (
            resolved_config.enable_ability_hard_safety_only
            and resolved_config.ability_hard_safety_direct_absorb_only
        ):
            if (
                target_pos in (1, 2)
                and not is_opponent_spread_move(move, order)
                and target_mon
            ):
                blocks_direct, reason_direct = direct_known_absorb_blocks_move(
                    move, active_mon, target_mon, battle, order
                )
                if blocks_direct:
                    if self.verbose:
                        print(
                            f"[Direct Absorb Hard Block] {reason_direct} | Attacker: {active_mon.species}, Target: {target_mon.species}"
                        )
                    return 0.0

        # Phase 6.3.6b: Known Ally Redirection Hard Safety
        if resolved_config.enable_known_ally_redirection_hard_safety:
            if target_pos in (1, 2) and target_mon:
                ally_idx = 1 - active_idx
                ally = (
                    battle.active_pokemon[ally_idx]
                    if ally_idx < len(battle.active_pokemon)
                    else None
                )
                if ally and not getattr(ally, "fainted", False):
                    redirects, red_reason = ally_redirects_our_single_target_move(
                        move, active_mon, ally, battle
                    )
                    if redirects:
                        if self.verbose:
                            print(
                                f"[Ally Redirection Block] {red_reason} | Ally: {ally.species}"
                            )
                        return 0.0

        # Phase 6.3: Ability hard safety block check for single target
        if resolved_config.enable_ability_hard_safety_only:
            if target_pos in (1, 2) and target_mon:
                blocks, reason = ability_hard_blocks_move(
                    move, active_mon, target_mon, battle, config=resolved_config
                )
                if blocks and _ability_block_enabled(resolved_config, reason):
                    if self.verbose:
                        print(
                            f"[Ability Hard Block] {reason} | Attacker: {active_mon.species}, Target: {target_mon.species}"
                        )
                    return 0.0

                # Check redirection for single-target Water/Electric moves
                if resolved_config.ability_hard_safety_avoid_redirection:
                    redirects, red_reason = ability_redirects_single_target_move(
                        move,
                        target_mon,
                        battle.opponent_active_pokemon,
                        active_mon,
                        battle,
                    )
                    if redirects:
                        # Find the redirection target
                        red_target = None
                        for opp in battle.opponent_active_pokemon:
                            if (
                                opp
                                and opp != target_mon
                                and not getattr(opp, "fainted", False)
                            ):
                                opp_ability = get_known_ability(opp, battle)
                                if opp_ability in ("stormdrain", "lightningrod"):
                                    red_target = opp
                                    break
                        # Score 0 only if the redirected target is bad/immune/benefits.
                        if red_target:
                            blocks_red, reason_red = ability_hard_blocks_move(
                                move,
                                active_mon,
                                red_target,
                                battle,
                                config=resolved_config,
                            )
                            if blocks_red and _ability_block_enabled(
                                resolved_config, reason_red
                            ):
                                if self.verbose:
                                    print(
                                        f"[Ability Redirection Hard Safety] {red_reason} | Attacker: {active_mon.species}, Intended Target: {target_mon.species} (blocked by redirected target {red_target.species})"
                                    )
                                return 0.0
                            else:
                                # Redirection target is not immune! Calculate redirected score.
                                red_type_multiplier = self.get_type_effectiveness(
                                    move, red_target, attacker=active_mon
                                )
                                if red_type_multiplier == 0.0:
                                    return 0.0
                                if category_name == "SPECIAL":
                                    red_defending_stat = self.get_boosted_stat(
                                        red_target, "spd"
                                    )
                                else:
                                    red_defending_stat = self.get_boosted_stat(
                                        red_target, "def"
                                    )
                                red_score = (
                                    float(base_power)
                                    * (attacking_stat / max(red_defending_stat, 1.0))
                                    * stab_multiplier
                                    * red_type_multiplier
                                    * accuracy_multiplier
                                )
                                # Return a slightly reduced score
                                return 0.8 * red_score

        # Ability-Aware block checks for single target
        if resolved_config.enable_ability_awareness:
            if target_pos in (1, 2) and target_mon:
                blocks, reason = ability_rules.ability_blocks_move(
                    target_mon, move, attacker=active_mon
                )
                if blocks:
                    if self.verbose:
                        print(
                            f"[Ability Block] {reason} | Attacker: {ability_rules.get_known_ability(active_mon)}, Target: {ability_rules.get_known_ability(target_mon)}"
                        )
                    self.increment_metric(
                        self.ability_blocks_avoided_by_battle, battle.battle_tag
                    )
                    return 0.0
                absorbs, reason = ability_rules.ability_absorbs_or_benefits(
                    target_mon, move
                )
                if absorbs:
                    if self.verbose:
                        print(
                            f"[Ability Absorb] {reason} | Attacker: {ability_rules.get_known_ability(active_mon)}, Target: {ability_rules.get_known_ability(target_mon)}"
                        )
                    self.increment_metric(
                        self.ability_absorbs_avoided_by_battle, battle.battle_tag
                    )
                    return 0.0
                # Redirection check
                for opp in battle.opponent_active_pokemon:
                    if opp and opp != target_mon:
                        redirects, reason = ability_rules.ability_redirects_move(
                            opp, move
                        )
                        if redirects:
                            if self.verbose:
                                print(
                                    f"[Ability Redirection] {reason} | Attacker: {ability_rules.get_known_ability(active_mon)}, Target: {ability_rules.get_known_ability(target_mon)}"
                                )
                            self.increment_metric(
                                self.ability_redirects_avoided_by_battle,
                                battle.battle_tag,
                            )
                            return 0.0

        if target_pos == 0:
            opps = [opp for opp in battle.opponent_active_pokemon if opp]
            if not opps:
                return 0.0
            total_damage = 0.0
            for opp in opps:
                if resolved_config.enable_type_immunity_safety:
                    immune, reason = is_type_immune(move, active_mon, opp, battle)
                    if immune:
                        if self.verbose:
                            print(
                                f"[Immunity Block Spread] {reason} | Attacker: {active_mon.species}, Target: {opp.species}"
                            )
                        continue
                if resolved_config.enable_ability_hard_safety_only:
                    blocks, reason = ability_hard_blocks_move(
                        move, active_mon, opp, battle, config=resolved_config
                    )
                    if blocks and _ability_block_enabled(resolved_config, reason):
                        if self.verbose:
                            print(
                                f"[Ability Hard Block Spread] {reason} | Attacker: {active_mon.species}, Target: {opp.species}"
                            )
                        continue
                if resolved_config.enable_ability_awareness:
                    blocks, reason = ability_rules.ability_blocks_move(
                        opp, move, attacker=active_mon
                    )
                    if blocks:
                        if self.verbose:
                            print(
                                f"[Ability Block Spread] {reason} | Attacker: {ability_rules.get_known_ability(active_mon)}, Target: {ability_rules.get_known_ability(opp)}"
                            )
                        self.increment_metric(
                            self.ability_blocks_avoided_by_battle, battle.battle_tag
                        )
                        continue
                    absorbs, reason = ability_rules.ability_absorbs_or_benefits(
                        opp, move
                    )
                    if absorbs:
                        if self.verbose:
                            print(
                                f"[Ability Absorb Spread] {reason} | Attacker: {ability_rules.get_known_ability(active_mon)}, Target: {ability_rules.get_known_ability(opp)}"
                            )
                        self.increment_metric(
                            self.ability_absorbs_avoided_by_battle, battle.battle_tag
                        )
                        continue
                type_multiplier = self.get_type_effectiveness(
                    move, opp, attacker=active_mon
                )
                if type_multiplier == 0.0:
                    continue
                if category_name == "SPECIAL":
                    defending_stat = self.get_boosted_stat(opp, "spd")
                else:
                    defending_stat = self.get_boosted_stat(opp, "def")
                opp_score = (
                    float(base_power)
                    * (attacking_stat / max(defending_stat, 1.0))
                    * stab_multiplier
                    * type_multiplier
                    * accuracy_multiplier
                )

                if resolved_config.enable_ability_awareness:
                    t_mult, t_reason = ability_rules.ability_damage_multiplier(
                        opp, move, attacker=active_mon
                    )
                    a_mult, a_reason = ability_rules.attacker_ability_damage_multiplier(
                        active_mon, move, target=opp
                    )
                    if t_mult != 1.0 or a_mult != 1.0:
                        if self.verbose:
                            print(
                                f"[Ability Multiplier Spread] target_mult={t_mult} ({t_reason or 'None'}), attacker_mult={a_mult} ({a_reason or 'None'}) vs {opp.species}"
                            )
                        self.increment_metric(
                            self.ability_multipliers_applied_by_battle,
                            battle.battle_tag,
                        )
                    opp_score *= t_mult * a_mult

                total_damage += opp_score
            if len(opps) == 2 and resolved_config.enable_spread_intelligence:
                total_damage *= 0.75
            return total_damage

        if target_mon:
            type_multiplier = self.get_type_effectiveness(
                move, target_mon, attacker=active_mon
            )
        else:
            type_multiplier = 1.0

        if type_multiplier == 0.0:
            return 0.0

        if category_name == "SPECIAL":
            defending_stat = (
                self.get_boosted_stat(target_mon, "spd") if target_mon else 100.0
            )
        else:
            defending_stat = (
                self.get_boosted_stat(target_mon, "def") if target_mon else 100.0
            )

        score = (
            float(base_power)
            * (attacking_stat / max(defending_stat, 1.0))
            * stab_multiplier
            * type_multiplier
            * accuracy_multiplier
        )

        if resolved_config.enable_ability_awareness and target_mon:
            t_mult, t_reason = ability_rules.ability_damage_multiplier(
                target_mon, move, attacker=active_mon
            )
            a_mult, a_reason = ability_rules.attacker_ability_damage_multiplier(
                active_mon, move, target=target_mon
            )
            if t_mult != 1.0 or a_mult != 1.0:
                if self.verbose:
                    print(
                        f"[Ability Multiplier] target_mult={t_mult} ({t_reason or 'None'}), attacker_mult={a_mult} ({a_reason or 'None'}) vs {target_mon.species}"
                    )
                self.increment_metric(
                    self.ability_multipliers_applied_by_battle, battle.battle_tag
                )
            score *= t_mult * a_mult

        return score

    def best_move_score_for_slot(self, slot_idx: int, battle: DoubleBattle) -> float:
        active_mon = battle.active_pokemon[slot_idx]
        if (
            not active_mon
            or battle.force_switch[slot_idx]
            or not battle.available_moves[slot_idx]
        ):
            return 0.0

        best_score = 0.0
        for move in battle.available_moves[slot_idx]:
            targets = battle.get_possible_showdown_targets(move, active_mon)
            for target in targets:
                order = SingleBattleOrder(move, move_target=target)
                score = self.score_action_raw_damage(order, slot_idx, battle)
                if score > best_score:
                    best_score = score
        return best_score

    def score_action(
        self,
        order: SingleBattleOrder,
        active_idx: int,
        battle: DoubleBattle,
        with_tiebreaker: bool = True,
        is_selected: bool = False,
        in_spread_check: bool = False,
        config=None,
        pure=False,
    ) -> float:
        old_pure = getattr(self, "_pure_scoring_mode", False)
        old_override = getattr(self, "_active_config_override", None)
        old_cache = self._base_scores_cache

        if pure:
            self._pure_scoring_mode = True
            self._base_scores_cache = {0: {}, 1: {}}
        if config is not None:
            self._active_config_override = config

        try:
            score = self._score_action_impl(
                order,
                active_idx,
                battle,
                with_tiebreaker=with_tiebreaker,
                is_selected=is_selected,
                in_spread_check=in_spread_check,
            )
            # Phase SPREAD-5: Opt-in Wide Guard
            # spread-defense bonus. Apply only when
            # ALL of the following are true:
            #   * enable_spread_defense_bonus is True
            #     (default OFF; opt-in only)
            #   * candidate action is Wide Guard
            #   * opp_pressure_state is True (any
            #     live opp has a revealed spread-move
            #     user that is healthy)
            #   * bonus magnitude is positive
            # This is intentionally narrow:
            #   - Quick Guard: NOT included
            #   - Crafty Shield: NOT included
            #   - Protect: NOT included (governed by
            #     protect_floor)
            #   - non-pressure turns: NOT included
            #   - default config: NOT included
            if (
                getattr(
                    self.config,
                    "enable_spread_defense_bonus",
                    False,
                )
                and isinstance(order.order, Move)
                and _normalize_move_id_for_spread_defense(
                    getattr(order.order, "id", "")
                ) == "wideguard"
                and self._slot_in_opp_pressure(
                    active_idx, battle
                )
                and getattr(
                    self.config,
                    "wide_guard_spread_pressure_bonus",
                    500.0,
                )
                > 0.0
            ):
                score = float(score) + float(
                    self.config.wide_guard_spread_pressure_bonus
                )
            # Phase SETUP-3A: opt-in speed-setup intent
            # bonus. Applies ONLY to Tailwind / Trick Room
            # candidate actions, and ONLY when all 5 guards
            # pass. Default OFF. See SETUP-2 design for
            # full guard spec.
            if self._setup_intent_speed_setup_eligible(
                order, active_idx, battle
            ):
                score = float(score) + float(
                    self.config.setup_intent_speed_setup_bonus
                )
            # Phase CONTROL-4B: opt-in anti-setup
            # disruption intent bonus. Applies ONLY to
            # Taunt / Encore / Disable / Quash
            # candidates, and ONLY when all 6 guards
            # pass. Default OFF. See
            # logs/phaseCONTROL3_anti_setup_design.md.
            if self._anti_setup_disruption_eligible(
                order, active_idx, battle
            ):
                score = float(score) + float(
                    self.config.anti_setup_disruption_bonus
                )
            # PLANNER-ANTI-TR: opt-in TR-specific response.
            # When opp has TR (active or revealed), boost
            # Taunt/Encore/Disable to disrupt the TR setter.
            # Default OFF. TR-specific (not general anti-setup).
            anti_tr_eligible = self._anti_trick_room_response_eligible(
                order, active_idx, battle
            )
            if anti_tr_eligible:
                score = float(score) + float(
                    self.config.anti_trick_room_response_bonus
                )
                self._record_anti_trick_room_response_pick(
                    battle, active_idx
                )
            # CONTROL-PRIORITY-2D: record debug for audit visibility.
            # Only record if this order is Taunt/Encore/Disable
            # (the anti-TR moves). Use the eligible check to know
            # the block reason for non-eligible cases.
            try:
                inner_move = getattr(order, "order", None)
                if inner_move is not None:
                    inner_move_id = (
                        getattr(inner_move, "id", "") or ""
                    ).lower().replace(" ", "").replace("-", "").replace("_", "").replace("'", "")
                    if inner_move_id in ("taunt", "encore", "disable", "quash"):
                        # Determine block reason for non-eligible cases
                        block_reason = ""
                        if not anti_tr_eligible:
                            block_reason = "anti_tr_eligible_returned_false"
                        self._record_anti_tr_target_debug(
                            order=order,
                            active_idx=active_idx,
                            battle=battle,
                            eligible=anti_tr_eligible,
                            block_reason=block_reason,
                            bonus_applied=(
                                float(self.config.anti_trick_room_response_bonus)
                                if anti_tr_eligible else 0.0
                            ),
                            mechanics_block_enabled=bool(
                                getattr(
                                    self.config,
                                    "enable_status_move_ability_safety",
                                    False,
                                )
                            ),
                        )
            except Exception:
                pass
            # PLANNER-ANTI-TR: KO pressure on damaging moves.
            # When opp has TR, favor damaging moves to KO before
            # TR expires. Smaller bonus than anti-setup.
            if self._anti_trick_room_ko_pressure_eligible(
                order, active_idx, battle
            ):
                score = float(score) + float(
                    self.config.anti_trick_room_ko_bonus
                )
                self._record_anti_trick_room_ko_pick(
                    battle, active_idx
                )
            # PLANNER-SPREAD-2: opt-in narrow spread defense
            # scoring. Applies ONLY to Wide Guard candidates,
            # and ONLY when all 6 guards pass. Default OFF.
            # See logs/phasePLANNER_SPREAD_1_design.md and
            # logs/phasePLANNER_SPREAD_1B_classifier_fix.md.
            # This is intentionally narrow: only Wide Guard,
            # not Protect or Quick Guard, only when the
            # IntentDetector fired SPREAD_DEFENSE with
            # sufficient confidence and opp pressure exists.
            if self._planner_spread_defense_eligible(
                order, active_idx, battle
            ):
                score = float(score) + float(
                    self.config.planner_spread_defense_wg_bonus
                )
                # Record the pick for anti-spam
                self._planner_spread_defense_record_pick(
                    battle, active_idx
                )
            # Phase ACCURACY-2: hard-safety block for
            # damaging moves targeting self (target=-1) or
            # ally (target=-2). When enabled, sets score=0
            # so the joint scoring won't pick a wasted-turn
            # option. ACCURACY-1 audit found 45 such cases
            # across SETUP-5/6/6A/7/7A/8 probes (100% bug
            # rate). Default OFF; opt-in for safe rollout.
            if getattr(
                self.config,
                "enable_accuracy_self_ally_block",
                False,
            ):
                try:
                    _inner_acc = getattr(order, "order", None)
                    if isinstance(_inner_acc, Move):
                        _tgt_acc = getattr(order, "move_target", 0)
                        if _tgt_acc in (-1, -2):
                            score = 0.0
                except Exception:
                    pass
            # Phase BEHAVIOR-12: Expected-faint attack penalty.
            # Applied to non-Protect, non-switch, non-pass
            # actions when the active slot is expected to
            # faint before moving. Set config to 0.0 to disable.
            # Phase BEHAVIOR-15: when
            # enable_speed_priority_piecewise_expected_faint_policy
            # is True, the piecewise penalty replaces this
            # flat one and is applied later at the slot-score-
            # map level (see choose_move seam).
            if (
                getattr(
                    self.config,
                    "enable_speed_priority_awareness",
                    True,
                )
                and getattr(
                    self.config,
                    "speed_priority_expected_faint_attack_penalty",
                    75.0,
                )
                > 0.0
                and not getattr(
                    self.config,
                    "enable_speed_priority_piecewise_expected_faint_policy",
                    False,
                )
                and self._expected_to_faint_before_moving.get(
                    getattr(battle, "battle_tag", ""), {}
                ).get(active_idx, False)
                and _is_attack_action_under_expected_faint(order)
            ):
                score -= float(
                    self.config.speed_priority_expected_faint_attack_penalty
                )
            # Phase BEHAVIOR-16: Expected-faint Protect
            # baseline floor. Applied as max(score, floor)
            # so it never reduces an existing higher
            # Protect score. Only triggers for Protect-like
            # candidates in slots with
            # expected_to_faint_before_moving=True. Does
            # NOT apply to attack, switch, pass, or
            # support moves. Independent of the BEHAVIOR-12
            # flat attack penalty and the BEHAVIOR-15
            # piecewise attack penalty.
            _pre_floor_score = score
            _floor_conditions_met = (
                getattr(
                    self.config,
                    "enable_speed_priority_awareness",
                    True,
                )
                and float(
                    getattr(
                        self.config,
                        "speed_priority_expected_faint_protect_score_floor",
                        240.0,
                    )
                )
                > 0.0
                and self._expected_to_faint_before_moving.get(
                    getattr(battle, "battle_tag", ""), {}
                ).get(active_idx, False)
                and _is_protect_like_action(order)
            )
            if _floor_conditions_met:
                floor = float(
                    self.config
                    .speed_priority_expected_faint_protect_score_floor
                )
                if score < floor:
                    score = floor
            # Phase BEHAVIOR-17: per-action Protect floor
            # diagnostic. Record the pre-floor and post-
            # floor scores for every Protect-like action,
            # regardless of whether the floor conditions
            # are met. This is read-only instrumentation;
            # it does not change scoring.
            if _is_protect_like_action(order):
                _bt = getattr(battle, "battle_tag", "")
                _ef = self._expected_to_faint_before_moving.get(
                    _bt, {}
                ).get(active_idx, False)
                _sp = getattr(
                    self.config,
                    "enable_speed_priority_awareness",
                    True,
                )
                _fv = float(
                    getattr(
                        self.config,
                        "speed_priority_expected_faint_protect_score_floor",
                        240.0,
                    )
                )
                _applied = bool(
                    _floor_conditions_met and _pre_floor_score < _fv
                )
                _inner = getattr(order, "order", None)
                _mid = getattr(_inner, "id", "?")
                _tgt = getattr(order, "move_target", 0)
                _ok = "move|{}|{}".format(_mid, _tgt)
                if _bt not in self._b17_protect_floor_debug:
                    self._b17_protect_floor_debug[_bt] = {0: [], 1: []}
                if active_idx not in self._b17_protect_floor_debug[_bt]:
                    self._b17_protect_floor_debug[_bt][active_idx] = []
                self._b17_protect_floor_debug[_bt][active_idx].append({
                    "expected_faint": _ef,
                    "pre_floor_score": _pre_floor_score,
                    "post_floor_score": score,
                    "floor_applied": _applied,
                    "floor_value": _fv,
                    "sp_enabled": _sp,
                    "order_key": _ok,
                })
            return score
        finally:
            self._pure_scoring_mode = old_pure
            self._active_config_override = old_override
            self._base_scores_cache = old_cache

    def _score_action_impl(
        self,
        order: SingleBattleOrder,
        active_idx: int,
        battle: DoubleBattle,
        with_tiebreaker: bool = True,
        is_selected: bool = False,
        in_spread_check: bool = False,
    ) -> float:
        active_mon = battle.active_pokemon[active_idx]

        battle_tag = battle.battle_tag
        current_turn = battle.turn

        # Defensive mock safety initialization
        for attr in (
            "_ability_hard_block_avoided",
            "_ability_immune_move_selected",
            "_ground_into_levitate_selected",
            "_ability_block_reason",
            "_ability_blocked_target_species",
            "_ability_blocked_target_ability",
            "_ally_ability_safe_spread",
            "_ability_redirection_avoided",
            "_direct_absorb_hard_block_avoided",
            "_direct_absorb_immune_move_selected",
            "_direct_absorb_block_reason",
            "_direct_absorb_target_species",
            "_direct_absorb_target_ability",
            "_direct_absorb_only_legal_action",
            "_support_target_wrong_side_blocked",
            "_support_target_block_reason",
            "_voluntary_switch_quality_data",
            "_voluntary_switch_adjustment_applied",
            "_voluntary_switch_penalized",
        ):
            if not hasattr(self, attr):
                setattr(self, attr, {})

        for attr in (
            "_ability_hard_block_avoided",
            "_ability_immune_move_selected",
            "_ground_into_levitate_selected",
            "_ally_ability_safe_spread",
            "_ability_redirection_avoided",
            "_direct_absorb_hard_block_avoided",
            "_direct_absorb_immune_move_selected",
            "_direct_absorb_only_legal_action",
            "_support_target_wrong_side_blocked",
            "_voluntary_switch_adjustment_applied",
            "_voluntary_switch_penalized",
        ):
            d = getattr(self, attr)
            if battle_tag not in d:
                d[battle_tag] = {0: False, 1: False}

        for attr in (
            "_ability_block_reason",
            "_ability_blocked_target_species",
            "_ability_blocked_target_ability",
            "_direct_absorb_block_reason",
            "_direct_absorb_target_species",
            "_direct_absorb_target_ability",
            "_support_target_block_reason",
        ):
            d = getattr(self, attr)
            if battle_tag not in d:
                d[battle_tag] = {0: "", 1: ""}

        # --- Pass / Default orders (processed before active_mon check) ---
        if (
            isinstance(order, PassBattleOrder)
            or getattr(order, "order", None) == "/choose pass"
        ):
            if battle.force_switch[active_idx]:
                return 10.0
            return 0.0

        if (
            isinstance(order, DefaultBattleOrder)
            or getattr(order, "order", None) == "/choose default"
        ):
            return 1.0

        # --- Switch orders (scored even when active slot is empty) ---
        if isinstance(order.order, Pokemon):
            switch_score = self.config.switch_baseline

            # Phase 6.4: Switch candidate type safety ranking
            if self.config.enable_switch_candidate_type_safety:
                switch_candidate = order.order
                active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                safety = evaluate_switch_candidate_type_safety(
                    switch_candidate, active_opps, self.config
                )
                # Store safety data for audit logging if this is the selected action
                if is_selected:
                    if not hasattr(self, "_switch_candidate_safety_data"):
                        self._switch_candidate_safety_data = {}
                    self._switch_candidate_safety_data[battle_tag] = (
                        self._switch_candidate_safety_data.get(battle_tag, {})
                    )
                    self._switch_candidate_safety_data[battle_tag][active_idx] = safety
                # Apply relative adjustment later in the ranking phase (see choose_move)

            # Speed/priority switch bonus: only when a live active Pokemon exists
            if (
                active_mon
                and self.config.enable_speed_priority_awareness
                and not self.config.speed_priority_protect_only
            ):
                active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                threat_info = self.estimate_speed_priority_threat(
                    active_mon, active_opps, battle
                )
                if threat_info["is_threatened"]:
                    has_protect = self.has_legal_protect_like_action(
                        active_mon, battle, slot_index=active_idx
                    )
                    mon_id = self.get_pokemon_identifier(active_mon)
                    key = (active_idx, mon_id)
                    last_turn = self.last_protect_turn.get(battle_tag, {}).get(key, -9)
                    protect_consecutive = current_turn - last_turn == 1

                    if not has_protect or protect_consecutive:
                        can_ko = False
                        has_strong_spread = False
                        for ord in self.get_valid_orders_for_slot(active_idx, battle):
                            if ord and isinstance(ord.order, Move):
                                m = ord.order
                                t_pos = ord.move_target
                                if t_pos in (1, 2):
                                    t_mon = battle.opponent_active_pokemon[t_pos - 1]
                                    if t_mon and self.check_move_will_ko(
                                        m, active_mon, t_mon, battle, config=self.config
                                    ):
                                        can_ko = True
                                if is_opponent_spread_move(m, ord):
                                    base_pow = getattr(m, "base_power", 0)
                                    if base_pow >= 60:
                                        has_strong_spread = True

                        if not can_ko and not has_strong_spread:
                            bonus = self.config.speed_priority_switch_bonus
                            bonus = min(
                                bonus, self.config.speed_priority_max_delta_per_action
                            )
                            switch_score += bonus
                            if is_selected:
                                self._speed_priority_switch_bonus_applied[battle_tag][
                                    active_idx
                                ] = True

            # Phase 6.4.4: Forced switch replacement safety scoring
            is_forced_switch = (
                battle.force_switch[active_idx]
                if active_idx < len(battle.force_switch)
                else False
            )
            if is_forced_switch and self.config.enable_forced_switch_replacement_safety:
                switch_candidate = order.order
                active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                safety = evaluate_forced_switch_replacement_safety(
                    switch_candidate, active_opps, battle=battle, config=self.config
                )
                switch_score += safety["score"]
                # Store for audit logging
                if is_selected:
                    if not hasattr(self, "_forced_switch_safety_data"):
                        self._forced_switch_safety_data = {}
                    self._forced_switch_safety_data[battle_tag] = (
                        self._forced_switch_safety_data.get(battle_tag, {})
                    )
                    self._forced_switch_safety_data[battle_tag][active_idx] = safety

            # Phase 6.4.9: Voluntary switch quality scoring is applied later in
            # choose_move() after all raw slot scores are computed (see the
            # slot score re-ranking section).  Diagnostics and scoring both
            # run there, not inside per-order score_action().

            # Bug fix: max(0) clamp wipes out safety differentiation when
            # safety penalties are below -8 (baseline).  For forced switches
            # with safety enabled, allow negative scores so the ranking can
            # differentiate between terrible and merely bad candidates.
            if is_forced_switch and self.config.enable_forced_switch_replacement_safety:
                return switch_score
            return max(switch_score, 0.0)

        # --- Everything below requires a live active Pokemon ---
        if not active_mon:
            return 0.0

        if is_selected:
            active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
            threat_info = self.estimate_speed_priority_threat(
                active_mon, active_opps, battle, order
            )

            self._speed_priority_threatened[battle_tag][active_idx] = threat_info[
                "is_threatened"
            ]
            self._faster_opponents[battle_tag][active_idx] = threat_info[
                "faster_opponents"
            ]
            self._priority_opponents[battle_tag][active_idx] = threat_info[
                "priority_opponents"
            ]

        # Phase BEHAVIOR-18: expected_to_faint_before_moving
        # is now set for EVERY scored order, not just the
        # selected one. This is required for the
        # BEHAVIOR-16 Protect floor to work: the floor
        # checks expected_to_faint_before_moving at
        # score_action time, but the selected action is
        # only known AFTER joint scoring. Previously
        # the flag was only set when is_selected=True,
        # so non-selected Protect orders never saw the
        # expected-faint state and the floor never
        # applied. The other speed-priority flags
        # (_speed_priority_threatened, _faster_opponents,
        # _priority_opponents) remain gated by
        # is_selected because they are used for
        # audit/display only, not for scoring.
        active_opps_for_ef = [
            opp for opp in battle.opponent_active_pokemon if opp
        ]
        threat_info_for_ef = self.estimate_speed_priority_threat(
            active_mon, active_opps_for_ef, battle, order
        )
        if battle_tag not in self._expected_to_faint_before_moving:
            self._expected_to_faint_before_moving[battle_tag] = {
                0: False, 1: False
            }
        self._expected_to_faint_before_moving[battle_tag][active_idx] = (
            threat_info_for_ef["faint_before_moving"]
        )

        # Move orders
        if isinstance(order.order, Move):
            move = order.order
            target_pos = order.move_target

            target_mon = None
            if target_pos == 1:
                target_mon = battle.opponent_active_pokemon[0]
            elif target_pos == 2:
                target_mon = battle.opponent_active_pokemon[1]
            elif target_pos == -1:
                target_mon = battle.active_pokemon[0]
            elif target_pos == -2:
                target_mon = battle.active_pokemon[1]

            if target_pos in (1, 2) and not target_mon:
                return 0.0

            base_power = getattr(move, "base_power", 0)
            category = getattr(move, "category", None)
            category_name = getattr(category, "name", "STATUS")

            # 1. Protect Heuristic
            if move.id in (
                "protect",
                "detect",
                "spikyshield",
                "kingsshield",
                "banefulbunker",
            ):
                if not self.config.enable_protect:
                    return 0.0
                mon_id = self.get_pokemon_identifier(active_mon)
                key = (active_idx, mon_id)
                last_turn = self.last_protect_turn.get(battle_tag, {}).get(key, -9)

                if current_turn - last_turn == 1:
                    return 0.0

                hp_fraction = getattr(active_mon, "current_hp_fraction", 1.0)
                hp_thresh = 0.35

                active_opps = [opp for opp in battle.opponent_active_pokemon if opp]

                threat_info = None
                if self.config.enable_speed_priority_awareness:
                    threat_info = self.estimate_speed_priority_threat(
                        active_mon, active_opps, battle
                    )
                    if threat_info["priority_threatened"]:
                        hp_thresh = self.config.priority_threat_hp_threshold

                if hp_fraction >= hp_thresh:
                    return 0.0

                ally_can_attack = (
                    self.best_move_score_for_slot(1 - active_idx, battle) > 30.0
                )
                if not ally_can_attack:
                    return 0.0

                is_threatened = False

                # Type matchup threat: opponent type hits us super-effectively
                for opp in active_opps:
                    for t in getattr(opp, "types", []):
                        if t and active_mon.damage_multiplier(t) >= 2.0:
                            is_threatened = True
                            break

                # Speed threat: opponent can outspeed and hit us this turn
                our_spe = self.get_boosted_stat(active_mon, "spe")
                for opp in active_opps:
                    opp_spe = self.get_boosted_stat(opp, "spe")
                    if (
                        opp_spe > our_spe
                        and get_max_type_threat(active_mon, opp, battle) >= 1.5
                    ):
                        is_threatened = True
                        break

                # Critical HP: very low HP and any opponent exists
                if hp_fraction < 0.15 and len(active_opps) > 0:
                    is_threatened = True

                # Phase 6.2 Speed/Priority Threat
                if (
                    self.config.enable_speed_priority_awareness
                    and threat_info
                    and threat_info["is_threatened"]
                ):
                    if self.has_legal_protect_like_action(
                        active_mon, battle, slot_index=active_idx
                    ):
                        is_threatened = True

                if is_threatened:
                    base_protect = self.config.protect_score
                    if (
                        self.config.enable_speed_priority_awareness
                        and threat_info
                        and threat_info["is_threatened"]
                    ):
                        if self.has_legal_protect_like_action(
                            active_mon, battle, slot_index=active_idx
                        ):
                            confidence = threat_info.get("threat_confidence", 1.0)
                            if self.config.speed_priority_use_scaled_penalty:
                                bonus = (
                                    self.config.speed_priority_protect_bonus_low
                                    + confidence
                                    * (
                                        self.config.speed_priority_protect_bonus_high
                                        - self.config.speed_priority_protect_bonus_low
                                    )
                                )
                            else:
                                bonus = self.config.speed_priority_protect_bonus
                            bonus = min(
                                bonus, self.config.speed_priority_max_delta_per_action
                            )
                            base_protect += bonus
                            if is_selected:
                                self._speed_priority_protect_bonus_applied[battle_tag][
                                    active_idx
                                ] = True
                                self._protected_due_to_speed_priority[battle_tag][
                                    active_idx
                                ] = True
                    # Phase BEHAVIOR-11: Expected-faint Protect
                    # bonus. Applied in addition to the
                    # is_threatened bonus when the active slot
                    # is expected to faint before moving.
                    # Does not change existing audit flag
                    # semantics (is_threatened bonus path is
                    # unchanged). The new bonus is reflected
                    # in the base_protect score only.
                    if (
                        self.config.enable_speed_priority_awareness
                        and self.config.speed_priority_protect_bonus_under_expected_faint > 0.0
                        and self._expected_to_faint_before_moving.get(
                            battle_tag, {}
                        ).get(active_idx, False)
                    ):
                        base_protect += (
                            self.config.speed_priority_protect_bonus_under_expected_faint
                        )

                    if self.config.enable_protect_threat_refinement:
                        max_threat = 0.0
                        for opp in active_opps:
                            t_score = self.score_opponent_threat(
                                opp, battle, our_pokemon=active_mon
                            )
                            if t_score > max_threat:
                                max_threat = t_score
                        return base_protect + max_threat * 30.0
                    return base_protect
                return 0.0

            # 2. Fake Out Heuristic
            if move.id == "fakeout" and self.config.enable_fake_out:
                mon_id = self.get_pokemon_identifier(active_mon)
                key = (active_idx, mon_id)
                active_turn_count = 1
                if (
                    battle_tag in self.active_turns
                    and key in self.active_turns[battle_tag]
                ):
                    active_turn_count, last_turn = self.active_turns[battle_tag][key]

                if active_turn_count != 1:
                    return 0.0

                if target_mon:
                    type_multiplier = self.get_type_effectiveness(
                        move, target_mon, attacker=active_mon
                    )
                    is_ghost = "GHOST" in [
                        t.name for t in getattr(target_mon, "types", []) if t
                    ]
                    if type_multiplier == 0.0 or is_ghost:
                        return 0.0
                else:
                    return 0.0

                score = self.score_action_raw_damage(order, active_idx, battle)
                score += 250.0

                if self.check_move_will_ko(
                    move, active_mon, target_mon, battle, config=self.config
                ):
                    score += 200.0
                else:
                    opps = [opp for opp in battle.opponent_active_pokemon if opp]
                    if len(opps) == 2:
                        if self.config.enable_fakeout_threat_targeting:
                            threat_0 = self.score_opponent_threat(opps[0], battle)
                            threat_1 = self.score_opponent_threat(opps[1], battle)
                            dangerous_opp = opps[0] if threat_0 >= threat_1 else opps[1]
                        else:
                            opp1_power = max(
                                self.get_boosted_stat(opps[0], "atk"),
                                self.get_boosted_stat(opps[0], "spa"),
                            )
                            opp2_power = max(
                                self.get_boosted_stat(opps[1], "atk"),
                                self.get_boosted_stat(opps[1], "spa"),
                            )
                            dangerous_opp = (
                                opps[0] if opp1_power >= opp2_power else opps[1]
                            )
                        if target_mon == dangerous_opp:
                            score += 50.0

                return max(score, 0.0)

            # 3. Generic Status Moves
            if category_name == "STATUS" or base_power == 0:
                if (
                    self.config.enable_priority_field_hard_safety
                    and target_pos in (1, 2)
                    and target_mon
                ):
                    priority_res = evaluate_priority_move_legality(
                        move, active_mon, target_mon, battle, self.config
                    )
                    if priority_res["blocked"]:
                        return float(self.config.ability_hard_safety_block_score)

                # Phase CONTROL-PRIORITY-2A: Status-move ability safety
                # (narrow). When True, status moves into a target
                # with a known status-blocking ability are blocked.
                # Independent of enable_ability_awareness. Covers
                # Magic Bounce, Good as Gold, Aroma Veil (target +
                # ally). Attacker with Mold Breaker family correctly
                # bypasses via the helper.
                if (
                    self.config.enable_status_move_ability_safety
                    and target_pos in (1, 2)
                    and target_mon
                ):
                    # Track which sub-flag matched (so we can
                    # filter by user's choice).
                    avoid, reason = (
                        ability_rules.should_avoid_status_into_ability(
                            target_mon, move, attacker=active_mon
                        )
                    )
                    track_target = False
                    if avoid:
                        if (
                            self.config.status_ability_safety_track_magic_bounce
                            and "Magic Bounce" in reason
                        ):
                            track_target = True
                        if (
                            self.config.status_ability_safety_track_good_as_gold
                            and "Good as Gold" in reason
                        ):
                            track_target = True
                        if (
                            self.config.status_ability_safety_track_aroma_veil
                            and "Aroma Veil" in reason
                        ):
                            track_target = True

                    # Check ally-side Aroma Veil (only for the
                    # specific moves Aroma Veil blocks).
                    track_ally = False
                    if (
                        not track_target
                        and self.config.status_ability_safety_track_aroma_veil_ally
                        and ability_rules.ally_has_aroma_veil(
                            target_mon, battle
                        )
                    ):
                        move_id = (
                            getattr(move, "id", "") or ""
                        ).lower().replace(" ", "").replace("-", "").replace("_", "").replace("'", "")
                        if move_id in ("taunt", "encore", "disable"):
                            reason = f"Ally Aroma Veil blocks {move_id} vs {target_mon.species}"
                            track_ally = True

                    if track_target or track_ally:
                        if self.verbose:
                            print(
                                f"[Status Ability Block] {reason} | Attacker: {ability_rules.get_known_ability(active_mon)}, Target: {ability_rules.get_known_ability(target_mon)}"
                            )
                        self.increment_metric(
                            self.ability_blocks_avoided_by_battle, battle.battle_tag
                        )
                        has_damaging_move = any(
                            getattr(m, "base_power", 0) > 0
                            for m in battle.available_moves[active_idx]
                        )
                        if has_damaging_move:
                            return 0.0
                        return -100.0

                if self.config.enable_ability_awareness:
                    if target_mon and target_pos in (1, 2):
                        avoid, reason = ability_rules.should_avoid_status_into_ability(
                            target_mon, move, attacker=active_mon
                        )
                        if avoid:
                            if self.verbose:
                                print(
                                    f"[Status Blocked] {reason} | Attacker: {ability_rules.get_known_ability(active_mon)}, Target: {ability_rules.get_known_ability(target_mon)}"
                                )
                            self.increment_metric(
                                self.ability_blocks_avoided_by_battle, battle.battle_tag
                            )
                            has_damaging_move = any(
                                getattr(m, "base_power", 0) > 0
                                for m in battle.available_moves[active_idx]
                            )
                            if has_damaging_move:
                                return 0.0
                            return -100.0
                    elif target_pos == 0:
                        for opp in battle.opponent_active_pokemon:
                            if opp:
                                avoid, reason = (
                                    ability_rules.should_avoid_status_into_ability(
                                        opp, move, attacker=active_mon
                                    )
                                )
                                if avoid:
                                    if self.verbose:
                                        print(
                                            f"[Status Blocked Spread] {reason} | Attacker: {ability_rules.get_known_ability(active_mon)}, Target: {ability_rules.get_known_ability(opp)}"
                                        )
                                    self.increment_metric(
                                        self.ability_blocks_avoided_by_battle,
                                        battle.battle_tag,
                                    )
                                    has_damaging_move = any(
                                        getattr(m, "base_power", 0) > 0
                                        for m in battle.available_moves[active_idx]
                                    )
                                    if has_damaging_move:
                                        return 0.0
                                    return -100.0

                # Phase 6.3.8: Support Move Target Hard Safety
                if self.config.enable_support_move_target_hard_safety:
                    blocked_st, reason_st = support_move_wrong_side_block(
                        order, active_idx, battle, config=self.config
                    )
                    if blocked_st:
                        if self.verbose:
                            print(f"[Support Target Block] {reason_st}")
                        self._support_target_wrong_side_blocked[battle_tag][
                            active_idx
                        ] = True
                        self._support_target_block_reason[battle_tag][active_idx] = (
                            reason_st
                        )
                        return float(self.config.support_move_wrong_side_block_score)

                # Phase 6.3.8a: Narrow Ally-Heal Wrong-Side Hard Safety
                # Production-grade replacement that only blocks Heal Pulse,
                # Floral Healing, and Decorate aimed at an opponent.
                # Independent of the broad flag — fires whether the broad
                # flag is on or off. The broad flag (above) handles the
                # wider wrong-side set first; this is a strict narrow subset.
                if self.config.enable_ally_heal_wrong_side_hard_safety:
                    blocked_narrow, reason_narrow = narrow_ally_heal_wrong_side_block(
                        order, active_idx, battle, config=self.config
                    )
                    if blocked_narrow:
                        if self.verbose:
                            print(f"[Narrow Ally Heal Block] {reason_narrow}")
                        self._support_target_wrong_side_blocked[battle_tag][
                            active_idx
                        ] = True
                        self._support_target_block_reason[battle_tag][active_idx] = (
                            reason_narrow
                        )
                        return float(self.config.ally_heal_wrong_side_block_score)

                has_damaging_move = any(
                    getattr(m, "base_power", 0) > 0
                    for m in battle.available_moves[active_idx]
                )
                if has_damaging_move:
                    return 0.0
                return 10.0

            # 4. Damaging Moves
            score = self.score_action_raw_damage(order, active_idx, battle)

            # ability awareness. Selected-action error flags are recorded even in
            # the benchmark's safety-off arm.
            if target_pos in (1, 2) and target_mon:
                blocks, reason = ability_hard_blocks_move(
                    move, active_mon, target_mon, battle, config=self.config
                )
                applies = blocks and _ability_block_enabled(self.config, reason)

                # Phase 6.3.3: Direct Known-Absorb Hard Safety
                applies_direct = False
                if (
                    self.config.enable_ability_hard_safety_only
                    and self.config.ability_hard_safety_direct_absorb_only
                ):
                    if not is_opponent_spread_move(move, order):
                        blocks_direct, reason_direct = direct_known_absorb_blocks_move(
                            move, active_mon, target_mon, battle, order
                        )
                        if blocks_direct:
                            applies_direct = True
                            reason = reason_direct

                if (blocks or applies_direct) and is_selected:
                    self._ability_immune_move_selected[battle_tag][active_idx] = True
                    if reason == "ground_into_levitate":
                        self._ground_into_levitate_selected[battle_tag][active_idx] = (
                            True
                        )
                    self._ability_block_reason[battle_tag][active_idx] = reason
                    self._ability_blocked_target_species[battle_tag][active_idx] = (
                        target_mon.species
                    )
                    self._ability_blocked_target_ability[battle_tag][active_idx] = (
                        get_known_ability(target_mon, battle) or ""
                    )

                    if applies_direct:
                        self._direct_absorb_immune_move_selected[battle_tag][
                            active_idx
                        ] = True
                        self._direct_absorb_block_reason[battle_tag][active_idx] = (
                            reason
                        )
                        self._direct_absorb_target_species[battle_tag][active_idx] = (
                            target_mon.species
                        )
                        self._direct_absorb_target_ability[battle_tag][active_idx] = (
                            get_known_ability(target_mon, battle) or ""
                        )

                # Phase 6.3.5a: Priority Terrain / Ability Safety
                applies_priority = False
                if self.config.enable_priority_field_hard_safety:
                    priority_res = evaluate_priority_move_legality(
                        move, active_mon, target_mon, battle, self.config
                    )
                    if priority_res["blocked"]:
                        applies_priority = True
                        reason = priority_res["reason"]

                # Phase 6.3.6b: Known Ally Redirection Hard Safety
                applies_ally_redirect = False
                ally_redirect_reason = ""
                if self.config.enable_known_ally_redirection_hard_safety:
                    ally_idx = 1 - active_idx
                    ally = (
                        battle.active_pokemon[ally_idx]
                        if ally_idx < len(battle.active_pokemon)
                        else None
                    )
                    if ally and not getattr(ally, "fainted", False):
                        redirects, red_reason = ally_redirects_our_single_target_move(
                            move, active_mon, ally, battle
                        )
                        if redirects:
                            applies_ally_redirect = True
                            ally_redirect_reason = red_reason
                            if is_selected:
                                self._known_ally_redirect_selected[battle_tag][
                                    active_idx
                                ] = True
                                self._known_ally_redirect_reason[battle_tag][
                                    active_idx
                                ] = red_reason
                                self._known_ally_redirect_ally_species[battle_tag][
                                    active_idx
                                ] = ally.species
                                self._known_ally_redirect_ally_ability[battle_tag][
                                    active_idx
                                ] = get_known_ability(ally, battle) or ""
                                self._known_ally_redirect_move_id[battle_tag][
                                    active_idx
                                ] = getattr(move, "id", "")

                if (
                    applies
                    or applies_direct
                    or applies_priority
                    or applies_ally_redirect
                ):
                    return float(self.config.ability_hard_safety_block_score)

                if (
                    self.config.enable_ability_hard_safety_only
                    and self.config.ability_hard_safety_avoid_redirection
                ):
                    redirects, red_reason = ability_redirects_single_target_move(
                        move,
                        target_mon,
                        battle.opponent_active_pokemon,
                        active_mon,
                        battle,
                    )
                    if redirects:
                        red_target = None
                        for opp in battle.opponent_active_pokemon:
                            if (
                                opp
                                and opp != target_mon
                                and not getattr(opp, "fainted", False)
                            ):
                                opp_ability = get_known_ability(opp, battle)
                                if opp_ability in ("stormdrain", "lightningrod"):
                                    red_target = opp
                                    break
                        if red_target:
                            blocks_red, reason_red = ability_hard_blocks_move(
                                move, active_mon, red_target, battle, config=self.config
                            )
                            if blocks_red and _ability_block_enabled(
                                self.config, reason_red
                            ):
                                if is_selected:
                                    self._ability_immune_move_selected[battle_tag][
                                        active_idx
                                    ] = True
                                    self._ability_block_reason[battle_tag][
                                        active_idx
                                    ] = red_reason
                                    self._ability_blocked_target_species[battle_tag][
                                        active_idx
                                    ] = red_target.species
                                    self._ability_blocked_target_ability[battle_tag][
                                        active_idx
                                    ] = get_known_ability(red_target, battle) or ""
                                return float(
                                    self.config.ability_hard_safety_block_score
                                )

            elif is_opponent_spread_move(move, order):
                ability_blocked = []
                for opp in battle.opponent_active_pokemon:
                    if not opp:
                        continue
                    blocked, reason = ability_hard_blocks_move(
                        move, active_mon, opp, battle, config=self.config
                    )
                    if blocked:
                        ability_blocked.append((opp, reason))
                if ability_blocked:
                    if is_selected:
                        blocked_target, blocked_reason = ability_blocked[0]
                        self._ability_immune_move_selected[battle_tag][active_idx] = (
                            True
                        )
                        self._ability_block_reason[battle_tag][active_idx] = (
                            blocked_reason
                        )
                        self._ability_blocked_target_species[battle_tag][active_idx] = (
                            blocked_target.species
                        )
                        self._ability_blocked_target_ability[battle_tag][active_idx] = (
                            get_known_ability(blocked_target, battle) or ""
                        )
                        if any(
                            reason == "ground_into_levitate"
                            for _, reason in ability_blocked
                        ):
                            self._ground_into_levitate_selected[battle_tag][
                                active_idx
                            ] = True

            # Phase 6.1.2: Partial Spread Immunity Penalty and Alternative Gate
            if is_opponent_spread_move(move, order):
                eff = get_spread_target_effectiveness_with_ability(
                    move,
                    active_mon,
                    battle.opponent_active_pokemon,
                    self.config,
                    battle,
                )

                # Apply penalty and cap score if enabled
                if self.config.enable_partial_spread_immunity_penalty:
                    if eff["all_targets_immune"]:
                        score = 0.0
                    elif eff["partial_immunity"]:
                        # score from score_action_raw_damage already only sums the non-immune/non-blocked targets
                        expected_ko_on_non_immune_target = False
                        for opp_name in eff["damaged_target_names"]:
                            opp_mon = None
                            for opp in battle.opponent_active_pokemon:
                                if opp and opp.species == opp_name:
                                    opp_mon = opp
                                    break
                            if opp_mon and self.check_move_will_ko(
                                move, active_mon, opp_mon, battle, config=self.config
                            ):
                                expected_ko_on_non_immune_target = True
                                break

                        # Apply penalty
                        if expected_ko_on_non_immune_target:
                            score *= 0.90
                        else:
                            score *= self.config.partial_spread_immunity_penalty
                            score -= self.config.partial_spread_immunity_flat_penalty
                            score = max(0.0, score)

                        # Alternative Gate (only if not in nested spread check to avoid recursion)
                        if not in_spread_check:
                            best_single_score = 0.0
                            best_single_can_ko = False
                            best_single_order = None

                            # Loop through available actions for the same active slot only
                            for ord in self.get_valid_orders_for_slot(
                                active_idx, battle
                            ):
                                if ord and isinstance(ord.order, Move):
                                    m = ord.order
                                    # Filter only for single-target damaging moves
                                    if (
                                        not is_opponent_spread_move(m, ord)
                                        and getattr(m, "base_power", 0) > 0
                                    ):
                                        alt_score = self.score_action(
                                            ord,
                                            active_idx,
                                            battle,
                                            with_tiebreaker=False,
                                            is_selected=False,
                                            in_spread_check=True,
                                        )
                                        if alt_score > best_single_score:
                                            best_single_score = alt_score
                                            best_single_order = ord

                                        # Check KO
                                        t_pos = ord.move_target
                                        t_mon = None
                                        if t_pos == 1:
                                            t_mon = battle.opponent_active_pokemon[0]
                                        elif t_pos == 2:
                                            t_mon = battle.opponent_active_pokemon[1]
                                        if t_mon and self.check_move_will_ko(
                                            m,
                                            active_mon,
                                            t_mon,
                                            battle,
                                            config=self.config,
                                        ):
                                            best_single_can_ko = True

                            if is_selected and best_single_order:
                                self.best_single_alternative_by_battle[battle_tag][
                                    active_idx
                                ] = best_single_order.order.id

                            # If single-target can KO while spread cannot, heavily penalize spread
                            spread_can_ko = expected_ko_on_non_immune_target
                            if best_single_can_ko and not spread_can_ko:
                                score = max(0.0, score - 200.0)
                            # If single-target score is close (within 30 gap), prefer single target
                            elif (
                                best_single_score > 0.0
                                and best_single_score
                                >= score
                                - self.config.partial_spread_prefer_single_target_gap
                            ):
                                score = min(score, best_single_score - 1.0)

                # Populate audit flags if this is the final selected action rerun
                if is_selected:
                    self.partial_immune_spread_by_battle[battle_tag][active_idx] = eff[
                        "partial_immunity"
                    ]
                    self.partial_ability_immune_spread_by_battle[battle_tag][
                        active_idx
                    ] = get_spread_ability_partial_immunity(
                        move,
                        active_mon,
                        battle.opponent_active_pokemon,
                        self.config,
                        battle,
                    )
                    self.immune_target_species_by_battle[battle_tag][active_idx] = eff[
                        "immune_target_names"
                    ]
                    self.damaged_target_species_by_battle[battle_tag][active_idx] = eff[
                        "damaged_target_names"
                    ]
                    if eff["partial_immunity"]:
                        spread_can_ko = False
                        for opp_name in eff["damaged_target_names"]:
                            opp_mon = None
                            for opp in battle.opponent_active_pokemon:
                                if opp and opp.species == opp_name:
                                    opp_mon = opp
                                    break
                            if opp_mon and self.check_move_will_ko(
                                move, active_mon, opp_mon, battle, config=self.config
                            ):
                                spread_can_ko = True
                                break

                        best_single_score = 0.0
                        best_single_can_ko = False
                        best_single_order = None
                        for ord in self.get_valid_orders_for_slot(active_idx, battle):
                            if ord and isinstance(ord.order, Move):
                                m = ord.order
                                if (
                                    not is_opponent_spread_move(m, ord)
                                    and getattr(m, "base_power", 0) > 0
                                ):
                                    alt_score = self.score_action(
                                        ord,
                                        active_idx,
                                        battle,
                                        with_tiebreaker=False,
                                        is_selected=False,
                                        in_spread_check=True,
                                    )
                                    if alt_score > best_single_score:
                                        best_single_score = alt_score
                                        best_single_order = ord
                                    t_pos = ord.move_target
                                    t_mon = None
                                    if t_pos == 1:
                                        t_mon = battle.opponent_active_pokemon[0]
                                    elif t_pos == 2:
                                        t_mon = battle.opponent_active_pokemon[1]
                                    if t_mon and self.check_move_will_ko(
                                        m, active_mon, t_mon, battle, config=self.config
                                    ):
                                        best_single_can_ko = True

                        if best_single_order:
                            self.best_single_alternative_by_battle[battle_tag][
                                active_idx
                            ] = best_single_order.order.id

                        is_inefficient = False
                        if not spread_can_ko:
                            # Use current score for comparison (might or might not be penalized/capped depending on config)
                            if (
                                best_single_score > 0.0
                                and best_single_score
                                >= score
                                - self.config.partial_spread_prefer_single_target_gap
                            ):
                                is_inefficient = True
                            if best_single_can_ko:
                                is_inefficient = True

                        self.inefficient_partial_spread_by_battle[battle_tag][
                            active_idx
                        ] = is_inefficient
                        self.efficient_partial_spread_by_battle[battle_tag][
                            active_idx
                        ] = not is_inefficient

            if score <= 0.0:
                return 0.0

            priority = self.get_priority(move)
            if priority > 0:
                score += 15.0

            if target_pos in (-1, -2):
                return 0.0

            # Spread move logic
            if self.is_spread_move(move) and self.config.enable_spread_intelligence:
                if self.hits_ally(move):
                    ally = battle.active_pokemon[1 - active_idx]
                    if ally:
                        is_safe = False
                        benefits = False
                        if self.config.enable_ability_awareness:
                            safe, reason = ability_rules.ally_is_safe_from_move(
                                ally, move
                            )
                            if safe:
                                is_safe = True
                                if self.verbose:
                                    print(
                                        f"[Ally Safe Spread] {reason} | Ally Ability: {ability_rules.get_known_ability(ally)}"
                                    )
                                self.increment_metric(
                                    self.ally_safe_spreads_by_battle, battle.battle_tag
                                )
                            absorbs, reason = ability_rules.ability_absorbs_or_benefits(
                                ally, move
                            )
                            if absorbs:
                                benefits = True
                        else:
                            is_safe = self.ally_safe_against_move(ally, move)
                            if (
                                not is_safe
                                and self.config.enable_ability_hard_safety_only
                                and self.config.ability_hard_safety_ally_spread_safety
                            ):
                                ability_safe, reason = ally_ability_makes_safe(
                                    ally, move, battle
                                )
                                if ability_safe:
                                    is_safe = True
                                    if is_selected:
                                        self._ally_ability_safe_spread[battle_tag][
                                            active_idx
                                        ] = True

                        if not is_safe:
                            score = max(0.0, score * 0.2 - self.config.ally_hit_penalty)
                        elif benefits:
                            if self.verbose:
                                print(
                                    f"[Ally Benefits Spread] {reason} | Ally Ability: {ability_rules.get_known_ability(ally)} (+30 bonus)"
                                )
                            score += 30.0
                else:
                    active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                    if len(active_opps) == 2:
                        score += self.config.spread_bonus

            # Target preferences (only if targeting an opponent)
            if target_mon and target_pos in (1, 2):
                opp_hp_fraction = getattr(target_mon, "current_hp_fraction", 1.0)
                if opp_hp_fraction is not None:
                    # Large bonus for targeting weakened opponents (focus fire)
                    score += (1.0 - opp_hp_fraction) * self.config.hp_targeting_weight

                if self.config.enable_threat_scoring:
                    threat_score = self.score_opponent_threat(target_mon, battle)
                    score += threat_score * self.config.threat_targeting_weight

                if self.check_move_will_ko(
                    move, active_mon, target_mon, battle, config=self.config
                ):
                    score += self.config.ko_bonus
                    if priority > 0:
                        score += 100.0

                # Boosted threat override
                if self.config.enable_boosted_threat_override:
                    boosts = self.get_boosts(target_mon)
                    atk_boost = boosts.get("atk", 0)
                    spa_boost = boosts.get("spa", 0)
                    spe_boost = boosts.get("spe", 0)
                    max_boost = max(atk_boost, spa_boost, spe_boost)

                    if max_boost >= self.config.boosted_override_min_stage:
                        # Check normal conditions
                        any_ko_exists = False
                        for cand_order in self.get_valid_orders_for_slot(
                            active_idx, battle
                        ):
                            if isinstance(
                                cand_order.order, Move
                            ) and cand_order.move_target in (1, 2):
                                t_mon = battle.opponent_active_pokemon[
                                    cand_order.move_target - 1
                                ]
                                if t_mon and self.check_move_will_ko(
                                    cand_order.order,
                                    active_mon,
                                    t_mon,
                                    battle,
                                    config=self.config,
                                ):
                                    any_ko_exists = True
                                    break

                        any_opp_low_hp = False
                        for opp in battle.opponent_active_pokemon:
                            if (
                                opp
                                and getattr(opp, "current_hp_fraction", 1.0)
                                < self.config.low_hp_target_threshold
                            ):
                                any_opp_low_hp = True
                                break

                        is_emergency = (
                            max_boost >= self.config.boosted_override_emergency_stage
                        )

                        if is_emergency or (not any_ko_exists and not any_opp_low_hp):
                            score += self.config.boosted_threat_bonus

                # Gated threat tiebreaker
                if with_tiebreaker and self.config.enable_threat_tiebreaker:
                    # Retrieve/populate cache for active_idx if not already populated
                    if not self._base_scores_cache[active_idx]:
                        for cand_order in self.get_valid_orders_for_slot(
                            active_idx, battle
                        ):
                            self._base_scores_cache[active_idx][id(cand_order)] = (
                                self.score_action(
                                    cand_order,
                                    active_idx,
                                    battle,
                                    with_tiebreaker=False,
                                )
                            )

                    # Conditions:
                    # 1. Action is a damaging move (BP > 0)
                    # 2. Target is an opponent (checked by outer block)
                    # 3. No candidate move can KO an opponent
                    any_ko_exists = False
                    for cand_order in self.get_valid_orders_for_slot(
                        active_idx, battle
                    ):
                        if isinstance(
                            cand_order.order, Move
                        ) and cand_order.move_target in (1, 2):
                            t_mon = battle.opponent_active_pokemon[
                                cand_order.move_target - 1
                            ]
                            if t_mon and self.check_move_will_ko(
                                cand_order.order,
                                active_mon,
                                t_mon,
                                battle,
                                config=self.config,
                            ):
                                any_ko_exists = True
                                break

                    # 4. No opponent has HP below 35%
                    any_opp_low_hp = False
                    for opp in battle.opponent_active_pokemon:
                        if opp and getattr(opp, "current_hp_fraction", 1.0) < 0.35:
                            any_opp_low_hp = True
                            break

                    if not any_ko_exists and not any_opp_low_hp:
                        # 5. Top candidate scores are close (gap <= threat_tiebreaker_score_gap)
                        cands = list(self._base_scores_cache[active_idx].values())
                        if len(cands) >= 2:
                            cands.sort(reverse=True)
                            gap = cands[0] - cands[1]
                            if gap <= self.config.threat_tiebreaker_score_gap:
                                threat_score = self.score_opponent_threat(
                                    target_mon, battle
                                )
                                score += (
                                    threat_score * self.config.threat_tiebreaker_weight
                                )

            elif target_pos == 0:
                for opp in battle.opponent_active_pokemon:
                    if opp and self.check_move_will_ko(
                        move, active_mon, opp, battle, config=self.config
                    ):
                        score += 150.0

            # Recoil/Self-destruct
            recoil = self.get_recoil(move)
            if recoil > 0:
                score -= 15.0 * recoil

            if move.id in {"selfdestruct", "explosion"}:
                score -= 50.0

            # Phase 5.2 / 5.3: Random-Set-Aware Opponent Modeling Adjustments
            if (
                self.config.enable_random_set_opponent_modeling
                and self.random_set_engine
            ):
                rs_base_score = score
                rs_protect_bonus = 0.0
                rs_targeting_bonus = 0.0
                cfg = self.config  # local alias for brevity

                # Resolve thresholds: per-rule override (if > 0) else global
                global_thr = cfg.random_set_probability_threshold

                def _thr(per_rule: float) -> float:
                    return per_rule if per_rule > 0.0 else global_thr

                active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                our_hp_fraction = getattr(active_mon, "current_hp_fraction", 1.0)

                # -- Protect-level adjustments --
                if move.id in (
                    "protect",
                    "detect",
                    "spikyshield",
                    "kingsshield",
                    "banefulbunker",
                    "silktrap",
                    "burningbulwark",
                ):
                    # Rule 2: Fake Out danger -- first-turn opponent
                    if cfg.rs_enable_fakeout_bonus:
                        fo_thr = _thr(cfg.rs_fakeout_threshold)
                        fo_delta = (
                            cfg.rs_fakeout_protect_delta
                            if cfg.rs_fakeout_protect_delta > 0.0
                            else 18.0
                        )
                        for opp_idx, opp in enumerate(active_opps):
                            opp_id = self.get_pokemon_identifier(opp)
                            key = (opp_idx, opp_id)
                            opp_active_turns_count = 1
                            if (
                                hasattr(self, "opponent_active_turns")
                                and battle_tag in self.opponent_active_turns
                            ):
                                if key in self.opponent_active_turns[battle_tag]:
                                    opp_active_turns_count, _ = (
                                        self.opponent_active_turns[battle_tag][key]
                                    )
                            if opp_active_turns_count == 1:
                                opp_revealed = list(opp.moves.keys())
                                likely_fo, prob, _ = (
                                    self.random_set_engine.likely_has_fake_out(
                                        opp.species, opp_revealed, threshold=fo_thr
                                    )
                                )
                                if likely_fo:
                                    our_ability = ability_rules.get_known_ability(
                                        active_mon
                                    )
                                    vulnerable = our_ability not in (
                                        "innerfocus",
                                        "shielddust",
                                    )
                                    if vulnerable:
                                        rs_protect_bonus += fo_delta
                                        self.increment_metric(
                                            self.rs_candidate_predictions_by_battle,
                                            battle_tag,
                                        )
                                        if is_selected:
                                            self.increment_metric(
                                                self.rs_selected_predictions_by_battle,
                                                battle_tag,
                                            )
                                            self.increment_metric(
                                                self.rs_predictions_used_by_battle,
                                                battle_tag,
                                            )
                                            self.increment_metric(
                                                self.rs_fakeout_predictions_by_battle,
                                                battle_tag,
                                            )
                                            if self.verbose:
                                                print(
                                                    f"[RS Prediction] fakeout: {opp.species} p={prob:.2f} +{fo_delta}"
                                                )

                    # Rule 3: Priority danger -- our HP < 20%
                    if cfg.rs_enable_priority_bonus and our_hp_fraction < 0.20:
                        prio_thr = _thr(cfg.rs_priority_threshold)
                        prio_delta = (
                            cfg.rs_priority_protect_delta
                            if cfg.rs_priority_protect_delta > 0.0
                            else 20.0
                        )
                        for opp in active_opps:
                            opp_revealed = list(opp.moves.keys())
                            likely_prio, prob, _ = (
                                self.random_set_engine.likely_has_priority(
                                    opp.species, opp_revealed, threshold=prio_thr
                                )
                            )
                            if likely_prio:
                                rs_protect_bonus += prio_delta
                                self.increment_metric(
                                    self.rs_candidate_predictions_by_battle, battle_tag
                                )
                                if is_selected:
                                    self.increment_metric(
                                        self.rs_selected_predictions_by_battle,
                                        battle_tag,
                                    )
                                    self.increment_metric(
                                        self.rs_predictions_used_by_battle, battle_tag
                                    )
                                    self.increment_metric(
                                        self.rs_priority_predictions_by_battle,
                                        battle_tag,
                                    )
                                    if self.verbose:
                                        print(
                                            f"[RS Prediction] priority: {opp.species} p={prob:.2f} +{prio_delta}"
                                        )

                    # Rule 4: Spread move danger -- our HP < rs_spread_hp_threshold (default 0.30)
                    if (
                        cfg.rs_enable_spread_bonus
                        and our_hp_fraction < cfg.rs_spread_hp_threshold
                    ):
                        spread_thr = _thr(cfg.rs_spread_threshold)
                        spread_delta = (
                            cfg.rs_spread_protect_delta
                            if cfg.rs_spread_protect_delta > 0.0
                            else 12.0
                        )
                        for opp in active_opps:
                            opp_revealed = list(opp.moves.keys())
                            likely_spread, prob, _ = (
                                self.random_set_engine.likely_has_spread_move(
                                    opp.species, opp_revealed, threshold=spread_thr
                                )
                            )
                            if likely_spread:
                                rs_protect_bonus += spread_delta
                                self.increment_metric(
                                    self.rs_candidate_predictions_by_battle, battle_tag
                                )
                                if is_selected:
                                    self.increment_metric(
                                        self.rs_selected_predictions_by_battle,
                                        battle_tag,
                                    )
                                    self.increment_metric(
                                        self.rs_predictions_used_by_battle, battle_tag
                                    )
                                    self.increment_metric(
                                        self.rs_spread_predictions_by_battle, battle_tag
                                    )
                                    if self.verbose:
                                        print(
                                            f"[RS Prediction] spread: {opp.species} p={prob:.2f} +{spread_delta}"
                                        )

                    # Rule 6: Speed control danger -- our HP < 40%
                    if cfg.rs_enable_speed_control_bonus and our_hp_fraction < 0.40:
                        sc_thr = _thr(cfg.rs_speed_control_threshold)
                        sc_delta = (
                            cfg.rs_speed_control_protect_delta
                            if cfg.rs_speed_control_protect_delta > 0.0
                            else 8.0
                        )
                        for opp in active_opps:
                            opp_revealed = list(opp.moves.keys())
                            likely_sc, prob, _ = (
                                self.random_set_engine.likely_has_speed_control(
                                    opp.species, opp_revealed, threshold=sc_thr
                                )
                            )
                            if likely_sc:
                                rs_protect_bonus += sc_delta
                                self.increment_metric(
                                    self.rs_candidate_predictions_by_battle, battle_tag
                                )
                                if is_selected:
                                    self.increment_metric(
                                        self.rs_selected_predictions_by_battle,
                                        battle_tag,
                                    )
                                    self.increment_metric(
                                        self.rs_predictions_used_by_battle, battle_tag
                                    )
                                    self.increment_metric(
                                        self.rs_speed_control_predictions_by_battle,
                                        battle_tag,
                                    )
                                    if self.verbose:
                                        print(
                                            f"[RS Prediction] speed_control: {opp.species} p={prob:.2f} +{sc_delta}"
                                        )

                    rs_protect_bonus = min(
                        rs_protect_bonus, cfg.random_set_max_protect_bonus_per_active
                    )
                    score += rs_protect_bonus

                # -- Targeting-level adjustments (damaging moves vs opponent) --
                if target_mon and target_pos in (1, 2):
                    opp_revealed = list(target_mon.moves.keys())

                    # Close-score gating: only apply targeting bonuses when scores are within gap
                    close_score_ok = True
                    if cfg.rs_close_score_gate_enabled:
                        # Populate cache if needed
                        if not self._base_scores_cache[active_idx]:
                            for cand_order in self.get_valid_orders_for_slot(
                                active_idx, battle
                            ):
                                self._base_scores_cache[active_idx][id(cand_order)] = (
                                    self.score_action(
                                        cand_order,
                                        active_idx,
                                        battle,
                                        with_tiebreaker=False,
                                    )
                                )
                        cands = list(self._base_scores_cache[active_idx].values())
                        if len(cands) >= 2:
                            cands_sorted = sorted(cands, reverse=True)
                            gap = cands_sorted[0] - cands_sorted[1]
                            close_score_ok = gap <= cfg.rs_close_score_gate_gap
                        # Also block if KO or low-HP target exists
                        any_ko_cl = False
                        any_low_hp_cl = False
                        for t_opp in active_opps:
                            if t_opp:
                                if (
                                    getattr(t_opp, "current_hp_fraction", 1.0)
                                    < cfg.low_hp_target_threshold
                                ):
                                    any_low_hp_cl = True
                                for cand_order in self.get_valid_orders_for_slot(
                                    active_idx, battle
                                ):
                                    if isinstance(
                                        cand_order.order, Move
                                    ) and cand_order.move_target in (1, 2):
                                        cand_t = battle.opponent_active_pokemon[
                                            cand_order.move_target - 1
                                        ]
                                        if cand_t and self.check_move_will_ko(
                                            cand_order.order,
                                            active_mon,
                                            cand_t,
                                            battle,
                                            config=self.config,
                                        ):
                                            any_ko_cl = True
                                            break
                        if any_ko_cl or any_low_hp_cl:
                            close_score_ok = False

                    if close_score_ok:
                        # Rule 5: Setup move danger -- only if no KO and no low-HP target
                        if cfg.rs_enable_setup_targeting:
                            setup_thr = _thr(cfg.rs_setup_threshold)
                            setup_delta = (
                                cfg.rs_setup_targeting_delta
                                if cfg.rs_setup_targeting_delta > 0.0
                                else 8.0
                            )
                            any_ko_exists = False
                            any_low_hp = False
                            for t_opp in active_opps:
                                if t_opp:
                                    if (
                                        getattr(t_opp, "current_hp_fraction", 1.0)
                                        < cfg.low_hp_target_threshold
                                    ):
                                        any_low_hp = True
                                    for cand_order in self.get_valid_orders_for_slot(
                                        active_idx, battle
                                    ):
                                        if isinstance(
                                            cand_order.order, Move
                                        ) and cand_order.move_target in (1, 2):
                                            cand_t = battle.opponent_active_pokemon[
                                                cand_order.move_target - 1
                                            ]
                                            if cand_t and self.check_move_will_ko(
                                                cand_order.order,
                                                active_mon,
                                                cand_t,
                                                battle,
                                                config=self.config,
                                            ):
                                                any_ko_exists = True
                                                break
                            if not any_ko_exists and not any_low_hp:
                                likely_setup, prob, _ = (
                                    self.random_set_engine.likely_has_setup_move(
                                        target_mon.species,
                                        opp_revealed,
                                        threshold=setup_thr,
                                    )
                                )
                                if likely_setup:
                                    rs_targeting_bonus += setup_delta
                                    self.increment_metric(
                                        self.rs_candidate_predictions_by_battle,
                                        battle_tag,
                                    )
                                    if is_selected:
                                        self.increment_metric(
                                            self.rs_selected_predictions_by_battle,
                                            battle_tag,
                                        )
                                        self.increment_metric(
                                            self.rs_predictions_used_by_battle,
                                            battle_tag,
                                        )
                                        self.increment_metric(
                                            self.rs_setup_predictions_by_battle,
                                            battle_tag,
                                        )
                                        if self.verbose:
                                            print(
                                                f"[RS Prediction] setup: {target_mon.species} p={prob:.2f} +{setup_delta}"
                                            )

                        # Rule 3 (KO targeting): priority user KO bonus
                        if cfg.rs_enable_priority_bonus and self.check_move_will_ko(
                            move, active_mon, target_mon, battle, config=self.config
                        ):
                            prio_thr = _thr(cfg.rs_priority_threshold)
                            likely_prio, prob, _ = (
                                self.random_set_engine.likely_has_priority(
                                    target_mon.species, opp_revealed, threshold=prio_thr
                                )
                            )
                            if likely_prio:
                                prio_ko_delta = (
                                    cfg.rs_priority_protect_delta
                                    if cfg.rs_priority_protect_delta > 0.0
                                    else 12.0
                                )
                                rs_targeting_bonus += prio_ko_delta
                                self.increment_metric(
                                    self.rs_candidate_predictions_by_battle, battle_tag
                                )
                                if is_selected:
                                    self.increment_metric(
                                        self.rs_selected_predictions_by_battle,
                                        battle_tag,
                                    )
                                    self.increment_metric(
                                        self.rs_predictions_used_by_battle, battle_tag
                                    )
                                    self.increment_metric(
                                        self.rs_priority_predictions_by_battle,
                                        battle_tag,
                                    )
                                    if self.verbose:
                                        print(
                                            f"[RS Prediction] priority_ko: {target_mon.species} p={prob:.2f} +{prio_ko_delta}"
                                        )

                score += rs_targeting_bonus

                # Clamp total delta per turn
                rs_diff = score - rs_base_score
                if abs(rs_diff) > cfg.random_set_max_score_delta_per_turn:
                    sign = 1.0 if rs_diff > 0 else -1.0
                    score = (
                        rs_base_score + sign * cfg.random_set_max_score_delta_per_turn
                    )
                    rs_diff = sign * cfg.random_set_max_score_delta_per_turn

                if is_selected and abs(rs_diff) > 0.0:
                    self.rs_score_delta_by_battle[battle_tag] = (
                        self.rs_score_delta_by_battle.get(battle_tag, 0.0)
                        + abs(rs_diff)
                    )

            # Phase 5: Meta-Aware Opponent Modeling Adjustments (old)
            if self.config.enable_meta_opponent_modeling and self.meta_engine:
                base_score_before_meta = score
                meta_protect_bonus = 0.0
                meta_targeting_bonus = 0.0
                meta_score_delta = 0.0

                active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                our_hp_fraction = getattr(active_mon, "current_hp_fraction", 1.0)

                # Check target predictions if it's a move targeting an opponent
                if target_mon and target_pos in (1, 2):
                    opp_revealed = list(target_mon.moves.keys())

                    # Setup move prediction (Rule 5)
                    # "do not directly target them if a KO or low-HP target exists"
                    any_ko_exists = False
                    any_low_hp = False
                    for t_opp in active_opps:
                        if t_opp:
                            if (
                                getattr(t_opp, "current_hp_fraction", 1.0)
                                < self.config.low_hp_target_threshold
                            ):
                                any_low_hp = True
                            for cand_order in self.get_valid_orders_for_slot(
                                active_idx, battle
                            ):
                                if isinstance(
                                    cand_order.order, Move
                                ) and cand_order.move_target in (1, 2):
                                    cand_t_mon = battle.opponent_active_pokemon[
                                        cand_order.move_target - 1
                                    ]
                                    if cand_t_mon and self.check_move_will_ko(
                                        cand_order.order,
                                        active_mon,
                                        cand_t_mon,
                                        battle,
                                        config=self.config,
                                    ):
                                        any_ko_exists = True
                                        break

                    if not any_ko_exists and not any_low_hp:
                        likely_setup, prob, reason = (
                            self.meta_engine.likely_has_setup_move(
                                target_mon.species,
                                opp_revealed,
                                threshold=self.config.meta_move_probability_threshold,
                            )
                        )
                        if likely_setup:
                            meta_targeting_bonus += 10.0
                            self.increment_metric(
                                self.candidate_meta_predictions_by_battle, battle_tag
                            )
                            if is_selected:
                                self.increment_metric(
                                    self.selected_meta_predictions_by_battle, battle_tag
                                )
                                self.increment_metric(
                                    self.meta_predictions_used_by_battle, battle_tag
                                )
                                self.increment_metric(
                                    self.meta_setup_predictions_by_battle, battle_tag
                                )
                                if self.verbose:
                                    print(
                                        f"[Meta Prediction] species={target_mon.species} type=setup prob={prob:.2f} action=target_setup delta=+10.0"
                                    )

                    # Priority KO check (Rule 3)
                    # "only add a small target preference bonus if our move can KO the priority user and scores are already close"
                    if self.check_move_will_ko(
                        move, active_mon, target_mon, battle, config=self.config
                    ):
                        likely_prio, prob, reason = (
                            self.meta_engine.likely_has_priority(
                                target_mon.species,
                                opp_revealed,
                                threshold=self.config.meta_move_probability_threshold,
                            )
                        )
                        if likely_prio:
                            meta_targeting_bonus += 15.0
                            self.increment_metric(
                                self.candidate_meta_predictions_by_battle, battle_tag
                            )
                            if is_selected:
                                self.increment_metric(
                                    self.selected_meta_predictions_by_battle, battle_tag
                                )
                                self.increment_metric(
                                    self.meta_predictions_used_by_battle, battle_tag
                                )
                                self.increment_metric(
                                    self.meta_priority_predictions_by_battle, battle_tag
                                )
                                if self.verbose:
                                    print(
                                        f"[Meta Prediction] species={target_mon.species} type=priority_ko prob={prob:.2f} action=target_ko_priority delta=+15.0"
                                    )

                # Check general threat predictions for Protect modifications (Rules 2, 3, 4, 6)
                if move.id in (
                    "protect",
                    "detect",
                    "spikyshield",
                    "kingsshield",
                    "banefulbunker",
                ):
                    # Rule 2: Fake Out Danger
                    for opp_idx, opp in enumerate(active_opps):
                        opp_id = self.get_pokemon_identifier(opp)
                        key = (opp_idx, opp_id)
                        opp_active_turns_count = 1
                        if (
                            battle_tag in self.opponent_active_turns
                            and key in self.opponent_active_turns[battle_tag]
                        ):
                            opp_active_turns_count, last_turn = (
                                self.opponent_active_turns[battle_tag][key]
                            )

                        if opp_active_turns_count == 1:
                            opp_revealed = list(opp.moves.keys())
                            likely_fo, prob, reason = (
                                self.meta_engine.likely_has_fake_out(
                                    opp.species,
                                    opp_revealed,
                                    threshold=self.config.meta_move_probability_threshold,
                                )
                            )
                            if likely_fo:
                                our_ability = ability_rules.get_known_ability(
                                    active_mon
                                )
                                vulnerable = our_ability not in (
                                    "innerfocus",
                                    "shielddust",
                                )
                                if vulnerable:
                                    meta_protect_bonus += 20.0
                                    self.increment_metric(
                                        self.candidate_meta_predictions_by_battle,
                                        battle_tag,
                                    )
                                    if is_selected:
                                        self.increment_metric(
                                            self.selected_meta_predictions_by_battle,
                                            battle_tag,
                                        )
                                        self.increment_metric(
                                            self.meta_predictions_used_by_battle,
                                            battle_tag,
                                        )
                                        self.increment_metric(
                                            self.meta_fakeout_predictions_by_battle,
                                            battle_tag,
                                        )
                                        if self.verbose:
                                            print(
                                                f"[Meta Prediction] species={opp.species} type=fakeout prob={prob:.2f} action=protect_bonus_fakeout delta=+20.0"
                                            )

                    # Rule 3: Priority Danger
                    if our_hp_fraction < 0.20:
                        for opp in active_opps:
                            opp_revealed = list(opp.moves.keys())
                            likely_prio, prob, reason = (
                                self.meta_engine.likely_has_priority(
                                    opp.species,
                                    opp_revealed,
                                    threshold=self.config.meta_move_probability_threshold,
                                )
                            )
                            if likely_prio:
                                meta_protect_bonus += 25.0
                                self.increment_metric(
                                    self.candidate_meta_predictions_by_battle,
                                    battle_tag,
                                )
                                if is_selected:
                                    self.increment_metric(
                                        self.selected_meta_predictions_by_battle,
                                        battle_tag,
                                    )
                                    self.increment_metric(
                                        self.meta_predictions_used_by_battle, battle_tag
                                    )
                                    self.increment_metric(
                                        self.meta_priority_predictions_by_battle,
                                        battle_tag,
                                    )
                                    if self.verbose:
                                        print(
                                            f"[Meta Prediction] species={opp.species} type=priority prob={prob:.2f} action=protect_bonus_priority delta=+25.0"
                                        )

                    # Rule 4: Spread Move Danger
                    if our_hp_fraction < 0.30:
                        for opp in active_opps:
                            opp_revealed = list(opp.moves.keys())
                            likely_spread, prob, reason = (
                                self.meta_engine.likely_has_spread_move(
                                    opp.species,
                                    opp_revealed,
                                    threshold=self.config.meta_move_probability_threshold,
                                )
                            )
                            if likely_spread:
                                meta_protect_bonus += 15.0
                                self.increment_metric(
                                    self.candidate_meta_predictions_by_battle,
                                    battle_tag,
                                )
                                if is_selected:
                                    self.increment_metric(
                                        self.selected_meta_predictions_by_battle,
                                        battle_tag,
                                    )
                                    self.increment_metric(
                                        self.meta_predictions_used_by_battle, battle_tag
                                    )
                                    self.increment_metric(
                                        self.meta_spread_predictions_by_battle,
                                        battle_tag,
                                    )
                                    if self.verbose:
                                        print(
                                            f"[Meta Prediction] species={opp.species} type=spread prob={prob:.2f} action=protect_bonus_spread delta=+15.0"
                                        )

                    # Rule 6: Super-effective Coverage
                    for opp in active_opps:
                        opp_revealed = list(opp.moves.keys())
                        likely_se, prob, reason = (
                            self.meta_engine.likely_has_super_effective_coverage(
                                opp.species,
                                active_mon,
                                opp_revealed,
                                threshold=self.config.meta_move_probability_threshold,
                            )
                        )
                        if likely_se:
                            meta_protect_bonus += 15.0
                            self.increment_metric(
                                self.candidate_meta_predictions_by_battle, battle_tag
                            )
                            if is_selected:
                                self.increment_metric(
                                    self.selected_meta_predictions_by_battle, battle_tag
                                )
                                self.increment_metric(
                                    self.meta_predictions_used_by_battle, battle_tag
                                )
                                self.increment_metric(
                                    self.meta_coverage_predictions_by_battle, battle_tag
                                )
                                if self.verbose:
                                    print(
                                        f"[Meta Prediction] species={opp.species} type=coverage prob={prob:.2f} action=protect_bonus_coverage delta=+15.0"
                                    )

                    # Cap total Protect bonus per active slot
                    meta_protect_bonus = min(
                        meta_protect_bonus,
                        self.config.meta_max_protect_bonus_per_active,
                    )
                    score += meta_protect_bonus

                # Apply meta targeting bonuses
                score += meta_targeting_bonus

                # Part 4: Predicted Ability Soft Rules (disabled by default)
                if (
                    self.config.enable_meta_predicted_ability_soft_rules
                    and target_mon
                    and target_pos in (1, 2)
                ):
                    known_ab = ability_rules.get_known_ability(target_mon)
                    if not known_ab:
                        preds = self.meta_engine.predict_abilities(target_mon.species)
                        if preds:
                            top_ab, prob = preds[0]
                            if prob >= self.config.meta_predicted_ability_threshold:
                                mtype = ability_rules.get_move_type(move)
                                is_immune = False
                                if (
                                    top_ab == "levitate"
                                    and mtype == "ground"
                                    and getattr(move, "id", "") != "thousandarrows"
                                ):
                                    is_immune = True
                                elif top_ab == "flashfire" and mtype == "fire":
                                    is_immune = True
                                elif (
                                    top_ab in ("waterabsorb", "stormdrain", "dryskin")
                                    and mtype == "water"
                                ):
                                    is_immune = True
                                elif (
                                    top_ab
                                    in ("voltabsorb", "lightningrod", "motordrive")
                                    and mtype == "electric"
                                ):
                                    is_immune = True
                                elif top_ab == "sapsipper" and mtype == "grass":
                                    is_immune = True

                                if is_immune:
                                    score *= (
                                        self.config.meta_predicted_ability_soft_penalty
                                    )
                                    self.increment_metric(
                                        self.candidate_meta_predictions_by_battle,
                                        battle_tag,
                                    )
                                    if is_selected:
                                        self.increment_metric(
                                            self.selected_meta_predictions_by_battle,
                                            battle_tag,
                                        )
                                        self.increment_metric(
                                            self.meta_predictions_used_by_battle,
                                            battle_tag,
                                        )
                                        self.increment_metric(
                                            self.meta_ability_soft_penalties_by_battle,
                                            battle_tag,
                                        )
                                        if self.verbose:
                                            print(
                                                f"[Meta Prediction] species={target_mon.species} type=predicted_ability_{top_ab} prob={prob:.2f} action=soft_penalty delta=-{abs(score - base_score_before_meta):.1f}"
                                            )

                # Cap total absolute score delta per turn
                diff = score - base_score_before_meta
                if abs(diff) > self.config.meta_max_score_delta_per_turn:
                    sign = 1.0 if diff > 0 else -1.0
                    score = (
                        base_score_before_meta
                        + sign * self.config.meta_max_score_delta_per_turn
                    )
                    diff = sign * self.config.meta_max_score_delta_per_turn

                if is_selected and abs(diff) > 0.0:
                    self.total_meta_score_delta_by_battle[battle_tag] = (
                        self.total_meta_score_delta_by_battle.get(battle_tag, 0.0)
                        + abs(diff)
                    )

            if self.config.enable_self_drop_move_penalty:
                expected_ko = False
                if target_mon:
                    expected_ko = self.check_move_will_ko(
                        move, active_mon, target_mon, battle, config=self.config
                    )
                has_alt = False
                if (
                    active_idx is not None
                    and battle.available_moves
                    and len(battle.available_moves) > active_idx
                ):
                    avail = battle.available_moves[active_idx]
                    if avail:
                        for m in avail:
                            if (
                                m
                                and getattr(m, "id", "") != move.id
                                and getattr(m, "base_power", 0) > 0
                            ):
                                has_alt = True
                                break
                multiplier, reason = get_self_stat_drop_penalty(
                    active_mon,
                    move,
                    expected_ko=expected_ko,
                    has_reasonable_alternative=has_alt,
                )
                if multiplier != 1.0:
                    score *= multiplier
                    if self.verbose and reason:
                        print(f"{reason} | score updated to {score:.2f}")
                    if is_selected:
                        m_id = (
                            getattr(move, "id", "")
                            .lower()
                            .replace(" ", "")
                            .replace("-", "")
                            .replace("_", "")
                            .strip()
                        )
                        if m_id in (
                            "dracometeor",
                            "overheat",
                            "leafstorm",
                            "fleurcannon",
                            "psychoboost",
                        ):
                            self.increment_metric(
                                self.draco_penalties_applied_by_battle, battle_tag
                            )
                        elif m_id == "makeitrain":
                            self.increment_metric(
                                self.make_it_rain_penalties_applied_by_battle,
                                battle_tag,
                            )

            # Phase 6.2 Speed/Priority Attack Penalty
            if (
                self.config.enable_speed_priority_awareness
                and not self.config.speed_priority_protect_only
                and move.id
                not in (
                    "protect",
                    "detect",
                    "spikyshield",
                    "kingsshield",
                    "banefulbunker",
                    "silktrap",
                    "burningbulwark",
                )
            ):
                active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                threat_info = self.estimate_speed_priority_threat(
                    active_mon, active_opps, battle, order
                )

                if threat_info["faint_before_moving"]:
                    bypass = False

                    # 1. KO threat
                    for opp in active_opps:
                        if (
                            opp
                            and opp.species
                            in threat_info["faster_opponents"]
                            + threat_info["priority_opponents"]
                        ):
                            if self.check_move_will_ko(
                                move, active_mon, opp, battle, config=self.config
                            ):
                                bypass = True
                                break

                    # 2. No safe defensive options
                    has_protect = self.has_legal_protect_like_action(
                        active_mon, battle, slot_index=active_idx
                    )
                    mon_id = self.get_pokemon_identifier(active_mon)
                    key = (active_idx, mon_id)
                    last_turn = self.last_protect_turn.get(battle_tag, {}).get(key, -9)
                    protect_consecutive = current_turn - last_turn == 1
                    protect_avail = has_protect and not protect_consecutive

                    switch_avail = len(getattr(battle, "available_switches", [])) > 0

                    if not protect_avail and not switch_avail:
                        bypass = True

                    # 3. High value action under threat
                    if self.is_high_value_action_under_threat(
                        order, active_mon, battle, active_opps
                    ):
                        bypass = True

                    if not bypass:
                        confidence = threat_info.get("threat_confidence", 1.0)
                        if self.config.speed_priority_use_scaled_penalty:
                            penalty = (
                                self.config.speed_priority_attack_penalty_low
                                + confidence
                                * (
                                    self.config.speed_priority_attack_penalty_high
                                    - self.config.speed_priority_attack_penalty_low
                                )
                            )
                        else:
                            penalty = self.config.speed_priority_attack_penalty
                        penalty = min(
                            penalty, self.config.speed_priority_max_delta_per_action
                        )
                        score -= penalty
                        if is_selected:
                            self._speed_priority_attack_penalty_applied[battle_tag][
                                active_idx
                            ] = True

            # Phase BI-3D / BI-3M: opt-in Mega bonus for
            # damaging moves. The total bonus is
            # ``config.mega_damaging_bonus +
            # config.mega_intent_bonus`` (defaults
            # 1e-3 + 1.0 = 1.001). The bonus is additive
            # and gated by both the
            # ``enable_mega_evolution`` config flag and
            # the underlying ``Move.base_power > 0``.
            # Status moves (base_power == 0) never get
            # the bonus. Non-Mega orders never get the
            # bonus. Default OFF (config flag False)
            # preserves bit-for-bit pre-BI-3D behavior.
            # Setting ``mega_intent_bonus=0.0`` restores
            # the BI-3D pure tie-breaker behavior.
            if (
                getattr(self.config, "enable_mega_evolution", False)
                and getattr(order, "mega", False)
            ):
                try:
                    inner = getattr(order, "order", None)
                    base_power = getattr(inner, "base_power", 0) or 0
                except Exception:
                    base_power = 0
                if base_power > 0:
                    score += float(
                        getattr(
                            self.config,
                            "mega_damaging_bonus",
                            1e-3,
                        )
                    ) + float(
                        getattr(
                            self.config,
                            "mega_intent_bonus",
                            1.0,
                        )
                    )

            return max(score, 0.0)

        return 0.0

    def _select_best_joint_order(
        self,
        battle: DoubleBattle,
        config,
        joint_orders,
        valid_orders,
        pure: bool = False,
    ) -> DoubleBattleOrder:
        old_override = getattr(self, "_active_config_override", None)
        old_pure = getattr(self, "_pure_scoring_mode", False)
        old_cache = self._base_scores_cache

        self._active_config_override = config
        if pure:
            self._pure_scoring_mode = True
            self._base_scores_cache = {0: {}, 1: {}}

        try:
            # 1. Pre-compute scores for each slot's valid orders
            slot_0_scores = {}
            slot_1_scores = {}
            if valid_orders[0]:
                for order_0 in valid_orders[0]:
                    slot_0_scores[id(order_0)] = self.score_action(
                        order_0, 0, battle, config=config, pure=pure
                    )
            if valid_orders[1]:
                for order_1 in valid_orders[1]:
                    slot_1_scores[id(order_1)] = self.score_action(
                        order_1, 1, battle, config=config, pure=pure
                    )

            # 2. Revealed-Move One-Ply Defensive Switch Interception
            if config.enable_revealed_move_switch_interception:
                for slot_idx in (0, 1):
                    active_mon = battle.active_pokemon[slot_idx]
                    if not active_mon:
                        continue
                    if (
                        slot_idx < len(battle.force_switch)
                        and battle.force_switch[slot_idx]
                    ):
                        continue

                    orders_slot = (
                        valid_orders[slot_idx]
                        if valid_orders and len(valid_orders) > slot_idx
                        else []
                    )
                    switch_orders = [
                        o for o in orders_slot if o and isinstance(o.order, Pokemon)
                    ]
                    if not switch_orders:
                        continue

                    active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                    our_actives = battle.active_pokemon
                    threats = summarize_revealed_move_threats(
                        active_mon, slot_idx, active_opps, our_actives, battle
                    )
                    if threats["max_pressure"] <= 0:
                        continue

                    best_action_score = 0.0
                    has_ko_action = False
                    for ord_cand in orders_slot:
                        if ord_cand and isinstance(ord_cand.order, Move):
                            cand_score = (
                                slot_0_scores.get(id(ord_cand), 0.0)
                                if slot_idx == 0
                                else slot_1_scores.get(id(ord_cand), 0.0)
                            )
                            if cand_score > best_action_score:
                                best_action_score = cand_score
                            t_pos = getattr(ord_cand, "move_target", None)
                            if t_pos in (1, 2):
                                t_mon = battle.opponent_active_pokemon[t_pos - 1]
                                if t_mon and self.check_move_will_ko(
                                    ord_cand.order,
                                    active_mon,
                                    t_mon,
                                    battle,
                                    config=config,
                                ):
                                    has_ko_action = True

                    best_bonus = 0.0
                    best_bonus_order = None
                    blocked_by_ko = False
                    blocked_by_high_value = False

                    if has_ko_action and config.revealed_switch_ko_action_override:
                        faint_before = False
                        for opp in active_opps:
                            for mv in get_revealed_damaging_moves(opp):
                                if self.check_move_will_ko(
                                    mv, opp, active_mon, battle, config=config
                                ):
                                    faint_before = True
                                    break
                            if faint_before:
                                break
                        if not faint_before:
                            blocked_by_ko = True

                    if (
                        best_action_score
                        >= config.revealed_switch_high_value_action_threshold
                    ):
                        blocked_by_high_value = True

                    if not (blocked_by_ko or blocked_by_high_value):
                        for sw_order in switch_orders:
                            candidate = sw_order.order
                            interception = evaluate_revealed_move_switch_interception(
                                active_mon, candidate, slot_idx, battle
                            )
                            if not interception["interception_valid"]:
                                continue
                            bonus = interception["proposed_score_bonus"]
                            if bonus > best_bonus:
                                best_bonus = bonus
                                best_bonus_order = sw_order

                        if best_bonus_order is not None and best_bonus > 0:
                            sid = id(best_bonus_order)
                            old_score = (
                                slot_0_scores.get(sid, 0.0)
                                if slot_idx == 0
                                else slot_1_scores.get(sid, 0.0)
                            )
                            if slot_idx == 0:
                                slot_0_scores[sid] = old_score + best_bonus
                            else:
                                slot_1_scores[sid] = old_score + best_bonus

            # 3/3b. Precompute safety blocks (canonical helper)
            (
                _direct_absorb_blocked,
                _safety_blocked,
                _ally_redirect_blocked,
                _ally_redirect_blocked_meta,
                _support_target_blocked,
                _support_target_reasons,
                _narrow_blocked,
                _narrow_reasons,
            ) = _compute_order_safety_blocks(battle, config, valid_orders)

            # 4. Switch candidate type safety ranking
            if config.enable_switch_candidate_type_safety:
                for slot_idx in (0, 1):
                    orders = (
                        valid_orders[slot_idx]
                        if valid_orders and len(valid_orders) > slot_idx
                        else []
                    )
                    switch_orders = [
                        o for o in orders if o and isinstance(o.order, Pokemon)
                    ]
                    if not switch_orders:
                        continue

                    active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                    candidate_safety = {}
                    for sw_order in switch_orders:
                        candidate = sw_order.order
                        safety = evaluate_switch_candidate_type_safety(
                            candidate, active_opps, config
                        )
                        candidate_safety[id(sw_order)] = safety

                    if candidate_safety:
                        best_raw = max(
                            s["raw_safety_score"] for s in candidate_safety.values()
                        )
                        for sw_order in switch_orders:
                            sid = id(sw_order)
                            raw = candidate_safety[sid]["raw_safety_score"]
                            relative_adj = min(0.0, raw - best_raw)
                            old_score = (
                                slot_0_scores.get(sid, 0.0)
                                if slot_idx == 0
                                else slot_1_scores.get(sid, 0.0)
                            )
                            new_score = old_score + relative_adj
                            if slot_idx == 0:
                                slot_0_scores[sid] = new_score
                            else:
                                slot_1_scores[sid] = new_score

            # 4b. Phase BEHAVIOR-15: opt-in piecewise
            # expected-faint attack penalty. Applied
            # to slot_*_scores AFTER all per-candidate
            # scoring adjustments, BEFORE
            # _compute_joint_scores. The same map drives
            # both final selection and v2l1_raw_scores
            # audit, so the adjustment reaches both.
            if getattr(
                config,
                "enable_speed_priority_piecewise_expected_faint_policy",
                False,
            ):
                _ef_map = self._expected_to_faint_before_moving.get(
                    getattr(battle, "battle_tag", ""), {}
                )
                if valid_orders and len(valid_orders) > 0:
                    _apply_piecewise_expected_faint_to_slot(
                        slot_0_scores,
                        valid_orders[0],
                        _ef_map.get(0, False),
                        config,
                    )
                if valid_orders and len(valid_orders) > 1:
                    _apply_piecewise_expected_faint_to_slot(
                        slot_1_scores,
                        valid_orders[1],
                        _ef_map.get(1, False),
                        config,
                    )

            # 5. Canonical joint scoring
            scored_joint_orders = self._compute_joint_scores(
                battle,
                config,
                joint_orders,
                slot_0_scores,
                slot_1_scores,
                _direct_absorb_blocked,
                _safety_blocked,
                _ally_redirect_blocked,
                _support_target_blocked=_support_target_blocked,
                _narrow_blocked=_narrow_blocked,
            )
            return scored_joint_orders[0]
        finally:
            self._active_config_override = old_override
            self._pure_scoring_mode = old_pure
            self._base_scores_cache = old_cache

    def choose_move(self, battle: AbstractBattle) -> BattleOrder:
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)

        # PLANNER-IMPL-2: per-turn intent detector (observational only).
        # When enable_planner_intent_detector is False, this block is
        # skipped entirely — no behavior change, no audit, no scoring.
        # When True, it stores an IntentDecision on self AND on
        # battle._planner_intent_decision for the audit logger.
        # NO scoring change. NO default flip.
        if getattr(
            self.config, "enable_planner_intent_detector", False
        ):
            decision = self._run_planner_intent_detector(battle)
            self._planner_intent_decision = decision
            # Attach to battle so the audit logger can read it
            try:
                setattr(battle, "_planner_intent_decision", decision)
            except Exception:
                pass
        else:
            # Default OFF path: no detector run, no decision.
            self._planner_intent_decision = None
            try:
                setattr(battle, "_planner_intent_decision", None)
            except Exception:
                pass

        # Phase BEHAVIOR-17: reset the per-turn Protect
        # floor diagnostic for this battle_tag. The dict
        # is repopulated by score_action (the wrapper)
        # for every Protect-like action in this turn.
        _bt0 = getattr(battle, "battle_tag", "")
        if _bt0 and _bt0 in self._b17_protect_floor_debug:
            # Clear per-slot lists but keep the entry so
            # we know the battle was processed.
            self._b17_protect_floor_debug[_bt0] = {0: [], 1: []}

        # V2l.1 — execution-derived invocation marker.
        # The canonical engine writes a fresh, non-empty
        # invocation id on entry. The id is preserved
        # through every turn's audit record so the
        # inspector can prove that ``shared_engine_used``
        # came from a real ``choose_move`` execution and
        # not from a hardcoded test fixture.
        # ``__new__``-based test fixtures may not have
        # these attributes; use ``getattr`` defaults so
        # the canonical engine never breaks existing
        # test fixtures.
        _v2l1_count = getattr(self, "_v2l1_invocation_count", 0)
        self._v2l1_invocation_id = f"v2l1-{id(self)}-{_v2l1_count}"
        self._v2l1_invocation_count = _v2l1_count + 1
        self._v2l1_invocation_status = "started"
        # Clear the per-turn snapshot on entry so a
        # failed choose_move does not leak prior state.
        self._v2l1_legal_keys_slot0 = []
        self._v2l1_legal_keys_slot1 = []
        self._v2l1_raw_scores_slot0 = {}
        self._v2l1_raw_scores_slot1 = {}
        self._v2l1_safety_blocks_slot0 = {}
        self._v2l1_safety_blocks_slot1 = {}
        self._v2l1_selected_joint_key = None
        self._v2l1_final_keys = []
        # Phase BI-1: clear V4a per-turn snapshot.
        self._v4a_legal_keys_slot0 = []
        self._v4a_legal_keys_slot1 = []
        self._v4a_selected_joint_key = None
        self._v4a_final_keys = []

        # Phase 6.3.7f: Scan replay for form change events before scoring
        _scan_replay_for_form_changes(battle)

        # Phase 6.4.3a.3: Timing diagnostics (optional)
        _timing_enabled = getattr(
            self.config, "enable_decision_timing_diagnostics", False
        )
        _t_start = time.time() if _timing_enabled else 0
        _t_valid_order = 0.0
        _t_score_action = 0.0
        _t_joint_scoring = 0.0
        _t_audit_postprocess = 0.0
        _score_action_call_count = 0
        _joint_order_count = 0

        # Reset cache at start of choose_move to avoid recursion
        self._base_scores_cache = {0: {}, 1: {}}

        battle_tag = battle.battle_tag
        current_turn = battle.turn

        # Phase 6.5: Scan replay for type consumption events
        if self.config.enable_type_consumption_tracking:
            _scan_replay_for_type_consumption(battle, self._consumed_types)
            if battle_tag not in self._consumed_types:
                self._consumed_types[battle_tag] = {}

        # Initialize tracking maps for the turn
        if battle_tag not in self.active_turns:
            self.active_turns[battle_tag] = {}
        if battle_tag not in self.last_protect_turn:
            self.last_protect_turn[battle_tag] = {}
        if (
            not hasattr(self, "opponent_active_turns")
            or self.opponent_active_turns is None
        ):
            self.opponent_active_turns = {}
        if battle_tag not in self.opponent_active_turns:
            self.opponent_active_turns[battle_tag] = {}

        # Initialize Phase 5 metrics maps if not already present
        self.meta_predictions_used_by_battle.setdefault(battle_tag, 0)
        self.meta_protect_predictions_by_battle.setdefault(battle_tag, 0)
        self.meta_fakeout_predictions_by_battle.setdefault(battle_tag, 0)
        self.meta_priority_predictions_by_battle.setdefault(battle_tag, 0)
        self.meta_spread_predictions_by_battle.setdefault(battle_tag, 0)
        self.meta_setup_predictions_by_battle.setdefault(battle_tag, 0)
        self.meta_coverage_predictions_by_battle.setdefault(battle_tag, 0)
        self.meta_ability_soft_penalties_by_battle.setdefault(battle_tag, 0)

        self.meta_species_found_by_battle.setdefault(battle_tag, 0)
        self.meta_species_missing_by_battle.setdefault(battle_tag, 0)

        self.candidate_meta_predictions_by_battle.setdefault(battle_tag, 0)
        self.selected_meta_predictions_by_battle.setdefault(battle_tag, 0)
        self.total_meta_score_delta_by_battle.setdefault(battle_tag, 0.0)

        # Initialize Phase 5.2 metrics maps
        self.rs_predictions_used_by_battle.setdefault(battle_tag, 0)
        self.rs_protect_predictions_by_battle.setdefault(battle_tag, 0)
        self.rs_fakeout_predictions_by_battle.setdefault(battle_tag, 0)
        self.rs_priority_predictions_by_battle.setdefault(battle_tag, 0)
        self.rs_spread_predictions_by_battle.setdefault(battle_tag, 0)
        self.rs_setup_predictions_by_battle.setdefault(battle_tag, 0)
        self.rs_speed_control_predictions_by_battle.setdefault(battle_tag, 0)
        self.rs_candidate_predictions_by_battle.setdefault(battle_tag, 0)
        self.rs_selected_predictions_by_battle.setdefault(battle_tag, 0)
        self.rs_score_delta_by_battle.setdefault(battle_tag, 0.0)
        self.rs_species_found_by_battle.setdefault(battle_tag, 0)
        self.rs_species_missing_by_battle.setdefault(battle_tag, 0)

        # Database coverage checking -- old meta
        if self.config.enable_meta_opponent_modeling and self.meta_engine:
            for opp in battle.opponent_active_pokemon:
                if opp:
                    entry = self.meta_engine.get_species_entry(opp.species)
                    if entry:
                        self.increment_metric(
                            self.meta_species_found_by_battle, battle_tag
                        )
                    else:
                        self.increment_metric(
                            self.meta_species_missing_by_battle, battle_tag
                        )

        # Database coverage checking -- random set
        if self.config.enable_random_set_opponent_modeling and self.random_set_engine:
            for opp in battle.opponent_active_pokemon:
                if opp:
                    if self.random_set_engine.is_species_known(opp.species):
                        self.increment_metric(
                            self.rs_species_found_by_battle, battle_tag
                        )
                    else:
                        self.increment_metric(
                            self.rs_species_missing_by_battle, battle_tag
                        )

        if battle_tag not in self.battle_metrics:
            self.battle_metrics[battle_tag] = {
                "protect": 0,
                "fake_out": 0,
                "spread": 0,
                "valid_spread": 0,
                "focus_fire": 0,
                "threat_contribution": 0.0,
                "tiebreaker_activations": 0,
                "boosted_override_activations": 0,
            }

        # Reset Phase 6.1.2 tracking maps for the current turn
        self.partial_immune_spread_by_battle[battle_tag] = {0: False, 1: False}
        self.partial_ability_immune_spread_by_battle[battle_tag] = {0: False, 1: False}
        self.efficient_partial_spread_by_battle[battle_tag] = {0: False, 1: False}
        self.inefficient_partial_spread_by_battle[battle_tag] = {0: False, 1: False}
        self.immune_target_species_by_battle[battle_tag] = {0: [], 1: []}
        self.damaged_target_species_by_battle[battle_tag] = {0: [], 1: []}
        self.best_single_alternative_by_battle[battle_tag] = {0: "", 1: ""}

        # Reset Phase 6.2 tracking maps for the current turn
        self._speed_priority_threatened[battle_tag] = {0: False, 1: False}
        self._faster_opponents[battle_tag] = {0: [], 1: []}
        self._priority_opponents[battle_tag] = {0: [], 1: []}
        self._speed_priority_protect_bonus_applied[battle_tag] = {0: False, 1: False}
        self._speed_priority_attack_penalty_applied[battle_tag] = {0: False, 1: False}
        self._speed_priority_switch_bonus_applied[battle_tag] = {0: False, 1: False}
        self._protected_due_to_speed_priority[battle_tag] = {0: False, 1: False}
        self._expected_to_faint_before_moving[battle_tag] = {0: False, 1: False}
        self._order_aware_overkill_penalty_applied[battle_tag] = False
        # Phase 6.4.9: Voluntary switch quality tracking
        self._voluntary_switch_quality_data[battle_tag] = {0: None, 1: None}
        self._voluntary_switch_adjustment_applied[battle_tag] = {0: False, 1: False}
        self._voluntary_switch_penalized[battle_tag] = {0: False, 1: False}
        # Phase 6.4.5: Stale target tracking
        self._stale_target_selected[battle_tag] = False
        self._stale_target_same_target_expected_ko[battle_tag] = False
        self._stale_target_caused_no_effect[battle_tag] = False
        self._stale_target_caused_type_immune[battle_tag] = False
        self._stale_target_first_slot[battle_tag] = 0
        self._stale_target_first_move[battle_tag] = ""
        self._stale_target_first_target[battle_tag] = ""
        self._stale_target_second_slot[battle_tag] = 1
        self._stale_target_second_move[battle_tag] = ""
        self._stale_target_second_intended_target[battle_tag] = ""
        self._stale_target_fallback_target[battle_tag] = ""
        self._stale_target_reason[battle_tag] = ""

        # Reset Phase 6.3 tracking maps for the current turn
        self._ability_hard_block_avoided[battle_tag] = {0: False, 1: False}
        self._ability_immune_move_selected[battle_tag] = {0: False, 1: False}
        self._ground_into_levitate_selected[battle_tag] = {0: False, 1: False}
        self._ability_block_reason[battle_tag] = {0: "", 1: ""}
        self._ability_blocked_target_species[battle_tag] = {0: "", 1: ""}
        self._ability_blocked_target_ability[battle_tag] = {0: "", 1: ""}
        self._ally_ability_safe_spread[battle_tag] = {0: False, 1: False}
        self._ability_redirection_avoided[battle_tag] = {0: False, 1: False}

        # Reset Phase 6.3.3 tracking maps for the current turn
        self._direct_absorb_hard_block_avoided[battle_tag] = {0: False, 1: False}
        self._direct_absorb_immune_move_selected[battle_tag] = {0: False, 1: False}
        self._direct_absorb_block_reason[battle_tag] = {0: "", 1: ""}
        self._direct_absorb_target_species[battle_tag] = {0: "", 1: ""}
        self._direct_absorb_target_ability[battle_tag] = {0: "", 1: ""}
        self._direct_absorb_only_legal_action[battle_tag] = {0: False, 1: False}

        # Reset Phase 6.3.8 tracking maps for the current turn
        self._support_target_wrong_side_blocked[battle_tag] = {0: False, 1: False}
        self._support_target_block_reason[battle_tag] = {0: "", 1: ""}

        # Reset Phase 6.3.6b tracking maps
        self._known_ally_redirect_selected[battle_tag] = {0: False, 1: False}
        self._known_ally_redirect_reason[battle_tag] = {0: "", 1: ""}
        self._known_ally_redirect_ally_species[battle_tag] = {0: "", 1: ""}
        self._known_ally_redirect_ally_ability[battle_tag] = {0: "", 1: ""}
        self._known_ally_redirect_move_id[battle_tag] = {0: "", 1: ""}
        self._known_ally_redirect_known_before[battle_tag] = {0: False, 1: False}

        self._absorb_streak_state.setdefault(battle_tag, {})

        # Track active turn count per slot
        for i, mon in enumerate(battle.active_pokemon):
            if mon:
                mon_id = self.get_pokemon_identifier(mon)
                key = (i, mon_id)
                if key in self.active_turns[battle_tag]:
                    count, last_turn = self.active_turns[battle_tag][key]
                    if current_turn == last_turn:
                        pass
                    elif current_turn - last_turn == 1:
                        self.active_turns[battle_tag][key] = (count + 1, current_turn)
                    else:
                        self.active_turns[battle_tag][key] = (1, current_turn)
                else:
                    self.active_turns[battle_tag][key] = (1, current_turn)

        # Track opponent active turn count per slot
        for i, mon in enumerate(battle.opponent_active_pokemon):
            if mon:
                mon_id = self.get_pokemon_identifier(mon)
                key = (i, mon_id)
                if key in self.opponent_active_turns[battle_tag]:
                    count, last_turn = self.opponent_active_turns[battle_tag][key]
                    if current_turn == last_turn:
                        pass
                    elif current_turn - last_turn == 1:
                        self.opponent_active_turns[battle_tag][key] = (
                            count + 1,
                            current_turn,
                        )
                    else:
                        self.opponent_active_turns[battle_tag][key] = (1, current_turn)
                else:
                    self.opponent_active_turns[battle_tag][key] = (1, current_turn)

        self._current_valid_orders = _augment_valid_orders_with_mega(
            battle, battle.valid_orders, self.config
        )
        valid_orders = self._current_valid_orders
        # V2l.1 — capture per-slot legal action keys.
        # The canonical engine uses ``_order_action_key``
        # (id-keyed tuple) for canonical comparison. We
        # materialize the legal action keys per slot so
        # the audit logger can prove which actions were
        # considered without storing non-serializable
        # ``BattleOrder`` objects.
        try:
            from poke_env.player.battle_order import (
                DoubleBattleOrder,
            )
            self._v2l1_legal_keys_slot0 = (
                _legal_action_keys_for_slot(valid_orders, 0)
            )
            self._v2l1_legal_keys_slot1 = (
                _legal_action_keys_for_slot(valid_orders, 1)
            )
        except Exception:
            # Defensive: legal-keys capture must never
            # break the canonical engine.
            self._v2l1_legal_keys_slot0 = []
            self._v2l1_legal_keys_slot1 = []
        if _timing_enabled:
            _t_valid_order = (time.time() - _t_start) * 1000
        if not valid_orders or (not valid_orders[0] and not valid_orders[1]):
            return self.choose_random_doubles_move(battle)

        joint_orders = DoubleBattleOrder.join_orders(valid_orders[0], valid_orders[1])
        if not joint_orders:
            return self.choose_random_doubles_move(battle)

        # Phase 6.3.6b: Snapshot known ally abilities before any candidate scoring
        _known_ally_ability_before = [{}, {}]
        for ally_idx in (0, 1):
            ally = (
                battle.active_pokemon[ally_idx]
                if ally_idx < len(battle.active_pokemon)
                else None
            )
            if ally:
                ab = get_known_ability(ally, battle)
                _known_ally_ability_before[ally_idx] = ab or ""

        # Pre-compute scores for each slot's valid orders to avoid redundant evaluations inside the joint loop
        slot_0_scores = {}
        slot_1_scores = {}
        _t_sa_start = time.time() if _timing_enabled else 0
        if valid_orders[0]:
            for order_0 in valid_orders[0]:
                slot_0_scores[id(order_0)] = self.score_action(order_0, 0, battle)
                _score_action_call_count += 1
        if valid_orders[1]:
            for order_1 in valid_orders[1]:
                slot_1_scores[id(order_1)] = self.score_action(order_1, 1, battle)
                _score_action_call_count += 1
        if _timing_enabled:
            _t_score_action = (time.time() - _t_sa_start) * 1000

        # Phase 6.4.2: Revealed-Move One-Ply Defensive Switch Interception
        # Applied in choose_move where canonical scores exist, not in score_action
        _revel_switch_interception_data = {0: None, 1: None}
        _legacy_slot_scores = {0: dict(slot_0_scores), 1: dict(slot_1_scores)}
        _selection_changed = False
        _sel_changed_per_slot = [False, False]

        if self.config.enable_revealed_move_switch_interception:
            for slot_idx in (0, 1):
                active_mon = battle.active_pokemon[slot_idx]
                if not active_mon:
                    continue
                if (
                    slot_idx < len(battle.force_switch)
                    and battle.force_switch[slot_idx]
                ):
                    continue

                orders_slot = (
                    valid_orders[slot_idx]
                    if valid_orders and len(valid_orders) > slot_idx
                    else []
                )
                switch_orders = [
                    o for o in orders_slot if o and isinstance(o.order, Pokemon)
                ]

                if not switch_orders:
                    continue

                # Summarize threats against current active
                active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                our_actives = battle.active_pokemon
                threats = summarize_revealed_move_threats(
                    active_mon, slot_idx, active_opps, our_actives, battle
                )

                if threats["max_pressure"] <= 0:
                    continue

                # Find best genuine legal move/action score for the active
                best_action_score = 0.0
                has_ko_action = False
                has_high_value_spread = False
                for ord_cand in orders_slot:
                    if ord_cand and isinstance(ord_cand.order, Move):
                        cand_score = (
                            slot_0_scores.get(id(ord_cand), 0.0)
                            if slot_idx == 0
                            else slot_1_scores.get(id(ord_cand), 0.0)
                        )
                        if cand_score > best_action_score:
                            best_action_score = cand_score
                        t_pos = getattr(ord_cand, "move_target", None)
                        if t_pos in (1, 2):
                            t_mon = battle.opponent_active_pokemon[t_pos - 1]
                            if t_mon and self.check_move_will_ko(
                                ord_cand.order,
                                active_mon,
                                t_mon,
                                battle,
                                config=self.config,
                            ):
                                has_ko_action = True
                        if self.is_spread_move(ord_cand.order):
                            base_pow = getattr(ord_cand.order, "base_power", 0)
                            if base_pow >= 60:
                                has_high_value_spread = True

                # Evaluate each switch candidate
                best_bonus = 0.0
                best_bonus_order = None
                blocked_by_ko = False
                blocked_by_high_value = False

                # Check KO/high-value gates
                if has_ko_action and self.config.revealed_switch_ko_action_override:
                    faint_before = False
                    for opp in active_opps:
                        for mv in get_revealed_damaging_moves(opp):
                            if self.check_move_will_ko(
                                mv, opp, active_mon, battle, config=self.config
                            ):
                                faint_before = True
                                break
                        if faint_before:
                            break
                    if not faint_before:
                        blocked_by_ko = True

                if (
                    best_action_score
                    >= self.config.revealed_switch_high_value_action_threshold
                ):
                    blocked_by_high_value = True

                if blocked_by_ko or blocked_by_high_value:
                    continue

                # Evaluate each switch candidate and track the best
                for sw_order in switch_orders:
                    candidate = sw_order.order
                    interception = evaluate_revealed_move_switch_interception(
                        active_mon, candidate, slot_idx, battle
                    )

                    if not interception["interception_valid"]:
                        continue

                    bonus = interception["proposed_score_bonus"]

                    # If this candidate has a better bonus than current best, update
                    if bonus > best_bonus:
                        best_bonus = bonus
                        best_bonus_order = sw_order

                # Apply the best bonus to the best switch candidate's score
                if best_bonus_order is not None and best_bonus > 0:
                    sid = id(best_bonus_order)
                    old_score = (
                        slot_0_scores.get(sid, 0.0)
                        if slot_idx == 0
                        else slot_1_scores.get(sid, 0.0)
                    )
                    slot_0_scores[sid] = (
                        old_score + best_bonus if slot_idx == 0 else old_score
                    )
                    slot_1_scores[sid] = (
                        old_score + best_bonus if slot_idx == 1 else old_score
                    )

                    # Build interception data for audit
                    candidate = best_bonus_order.order
                    interception = evaluate_revealed_move_switch_interception(
                        active_mon, candidate, slot_idx, battle
                    )
                    threats_for_audit = summarize_revealed_move_threats(
                        active_mon, slot_idx, active_opps, our_actives, battle
                    )
                    _revel_switch_interception_data[slot_idx] = {
                        "threatening_opponents": threats_for_audit[
                            "threatening_opponents"
                        ],
                        "threat_move_ids": threats_for_audit["revealed_move_ids"],
                        "threat_move_types": threats_for_audit["revealed_move_types"],
                        "target_likelihood": threats_for_audit[
                            "target_likelihood_weights"
                        ],
                        "active_risk": interception["active_risk"],
                        "candidate_risk": interception["candidate_risk"],
                        "risk_reduction": interception["risk_reduction"],
                        "candidate_species": getattr(candidate, "species", ""),
                        "candidate_types": [
                            str(t) for t in getattr(candidate, "types", []) if t
                        ],
                        "candidate_hp": interception["candidate_hp"],
                        "bonus_applied": interception["proposed_score_bonus"],
                        "blocked_by_ko": False,
                        "blocked_by_high_value": False,
                        "worse_other_threat": interception["rejection_reason"]
                        == "worse_other_threat",
                        "prediction_available": True,
                    }

        # Precompute safety blocks (canonical helper)
        (
            _direct_absorb_blocked,
            _safety_blocked,
            _ally_redirect_blocked,
            _ally_redirect_blocked_meta,
            _support_target_blocked,
            _support_target_reasons,
            _narrow_blocked,
            _narrow_reasons,
        ) = _compute_order_safety_blocks(battle, self.config, valid_orders)

        # Phase 6.4: Switch candidate type safety ranking
        # Diagnostics always run; score adjustments only when feature enabled
        _switch_safety_applied = {}
        _switch_best_raw_scores = {}
        _switch_safer_available = {}
        _switch_unsafe_selected = {}
        _switch_type_safety_avoided = {}
        _switch_best_safe_switch = {}
        _switch_forced = {}
        _switch_safety_data_per_slot = {}
        _neg_boost_data_per_slot = {}

        for slot_idx in (0, 1):
            orders = (
                valid_orders[slot_idx]
                if valid_orders and len(valid_orders) > slot_idx
                else []
            )
            switch_orders = [o for o in orders if o and isinstance(o.order, Pokemon)]

            if not switch_orders:
                continue

            # Evaluate type safety for each switch candidate (always for diagnostics)
            active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
            candidate_safety = {}
            for sw_order in switch_orders:
                candidate = sw_order.order
                safety = evaluate_switch_candidate_type_safety(
                    candidate, active_opps, self.config
                )
                candidate_safety[id(sw_order)] = safety

            # Find the best raw safety score among candidates
            if candidate_safety:
                best_raw = max(s["raw_safety_score"] for s in candidate_safety.values())
                _switch_best_raw_scores[slot_idx] = best_raw

                # Apply score adjustments only when feature is enabled
                if self.config.enable_switch_candidate_type_safety:
                    for sw_order in switch_orders:
                        sid = id(sw_order)
                        raw = candidate_safety[sid]["raw_safety_score"]
                        relative_adj = min(0.0, raw - best_raw)
                        old_score = (
                            slot_0_scores.get(sid, 0.0)
                            if slot_idx == 0
                            else slot_1_scores.get(sid, 0.0)
                        )
                        new_score = old_score + relative_adj

                        if slot_idx == 0:
                            slot_0_scores[sid] = new_score
                        else:
                            slot_1_scores[sid] = new_score

                        _switch_safety_applied[sid] = True

                # Find the best safe switch (highest adjusted score among safe candidates)
                best_safe_order = None
                best_safe_score = float("-inf")
                for sw_order in switch_orders:
                    sid = id(sw_order)
                    safety = candidate_safety[sid]
                    is_unsafe = (
                        safety["double_threat"] or safety["quad_weak_threat_count"] > 0
                    )
                    score = (
                        slot_0_scores.get(sid, 0.0)
                        if slot_idx == 0
                        else slot_1_scores.get(sid, 0.0)
                    )
                    if not is_unsafe and score > best_safe_score:
                        best_safe_score = score
                        best_safe_order = sw_order

                if best_safe_order:
                    _switch_best_safe_switch[slot_idx] = {
                        "species": best_safe_order.order.species,
                        "score": best_safe_score,
                    }

                _switch_safety_data_per_slot[slot_idx] = candidate_safety

        # Phase 6.4: Negative boost diagnostics (diagnostic-only, no score changes)
        for slot_idx in (0, 1):
            active_mon = battle.active_pokemon[slot_idx]
            if active_mon:
                neg_boosts = summarize_negative_boosts(active_mon)
                # Record whether the selected action is a switch
                # (determined later after best_joint is known)
                _neg_boost_data_per_slot[slot_idx] = neg_boosts

                # Compute eligibility fields
                neg_boosts["negative_boost_decision_eligible"] = False
                neg_boosts["negative_boost_selected_action_kind"] = ""
                neg_boosts["negative_boost_legal_switch_count"] = 0
                neg_boosts["negative_boost_best_switch_species"] = ""
                neg_boosts["negative_boost_best_switch_score"] = 0.0
                neg_boosts["negative_boost_best_move_score"] = 0.0
                neg_boosts["negative_boost_switch_score_gap"] = 0.0
                neg_boosts["negative_boost_relevant_offensive_drop"] = False
                neg_boosts["negative_boost_defensive_drop"] = (
                    neg_boosts.get("defensive_negative_stages", 0) > 0
                )
                neg_boosts["negative_boost_speed_drop"] = (
                    neg_boosts.get("speed_negative_stage", 0) > 0
                )

                # Check eligibility
                is_forced = (
                    battle.force_switch[slot_idx]
                    if slot_idx < len(battle.force_switch)
                    else False
                )
                has_legal_switches = len(battle.available_switches) > 0
                orders_slot = (
                    valid_orders[slot_idx]
                    if valid_orders and len(valid_orders) > slot_idx
                    else []
                )
                has_legal_moves = any(
                    o and isinstance(o.order, Move) for o in orders_slot
                )
                has_legal_switches_in_slot = any(
                    o and isinstance(o.order, Pokemon) for o in orders_slot
                )

                # Offensive drop relevant to available damaging moves
                if neg_boosts.get("offensive_negative_stages", 0) > 0:
                    for o in orders_slot:
                        if o and isinstance(o.order, Move):
                            cat = getattr(o.order, "category", None)
                            cat_name = getattr(cat, "name", "STATUS")
                            if (
                                cat_name != "STATUS"
                                and getattr(o.order, "base_power", 0) > 0
                            ):
                                neg_boosts["negative_boost_relevant_offensive_drop"] = (
                                    True
                                )
                                break

        # Phase 6.4.7: Conservative Stat-Drop Switch Scoring
        _stat_drop_scoring_data = {}
        for slot_idx in (0, 1):
            _sdata = {
                "enabled": bool(
                    getattr(self.config, "enable_stat_drop_switch_scoring", False)
                ),
                "pressure_active": False,
                "categories": [],
                "pressure_score": 0.0,
                "switch_selected": False,
                "stayed": False,
                "stayed_productive": False,
                "stayed_unproductive": False,
                "selection_changed": False,
                "best_switch_species": "",
                "best_switch_score": 0.0,
                "best_non_switch_score": 0.0,
                "reason": "",
                "threshold_source": "",
            }
            _stat_drop_scoring_data[slot_idx] = _sdata

            if not _sdata["enabled"]:
                continue

            active_mon = battle.active_pokemon[slot_idx]
            if not active_mon:
                continue

            is_forced = (
                battle.force_switch[slot_idx]
                if slot_idx < len(battle.force_switch)
                else False
            )
            if is_forced:
                continue

            orders_slot = (
                valid_orders[slot_idx]
                if valid_orders and len(valid_orders) > slot_idx
                else []
            )
            pressure = evaluate_stat_drop_switch_pressure(
                active_mon,
                orders_slot,
                battle,
                self.config,
                player=self,
            )

            if not pressure["should_consider_switch"]:
                _sdata["reason"] = "; ".join(pressure["reasons"])
                continue

            _sdata["pressure_active"] = True
            _sdata["categories"] = list(pressure["categories"])
            _sdata["stay_penalty"] = pressure["stay_penalty"]
            _sdata["reason"] = "; ".join(pressure["reasons"])
            _sdata["threshold_source"] = pressure.get("threshold_source", "")

            slot_scores = slot_0_scores if slot_idx == 0 else slot_1_scores

            best_switch_score_val = float("-inf")
            best_switch_species_val = ""
            best_non_switch_score_val = float("-inf")

            for o in orders_slot:
                if not o:
                    continue
                sid = id(o)
                sc = slot_scores.get(sid, 0.0)
                order_obj = getattr(o, "order", None)
                if order_obj is not None and getattr(order_obj, "species", None):
                    if sc > best_switch_score_val:
                        best_switch_score_val = sc
                        best_switch_species_val = getattr(o.order, "species", "")
                elif isinstance(o.order, Move):
                    if sc > best_non_switch_score_val:
                        best_non_switch_score_val = sc

            _sdata["best_switch_species"] = best_switch_species_val
            _sdata["best_switch_score"] = (
                best_switch_score_val if best_switch_score_val > float("-inf") else 0.0
            )
            _sdata["best_non_switch_score"] = (
                best_non_switch_score_val
                if best_non_switch_score_val > float("-inf")
                else 0.0
            )

            switch_bonus = (
                self.config.stat_drop_switch_safe_switch_bonus if self.config else 30.0
            )

            for o in orders_slot:
                if not o:
                    continue
                sid = id(o)
                sc = slot_scores.get(sid, 0.0)
                order_obj = getattr(o, "order", None)
                if order_obj is not None and getattr(order_obj, "species", None):
                    adjusted = sc + switch_bonus
                    slot_scores[sid] = adjusted
                else:
                    sc -= pressure["stay_penalty"]
                    slot_scores[sid] = sc

        # Preserve raw scores before VSW adjustments for counterfactual
        _vsw_raw_scores_0 = dict(slot_0_scores)
        _vsw_raw_scores_1 = dict(slot_1_scores)

        # Phase 6.4.9: Voluntary switch quality evaluation
        _voluntary_switch_candidate_tables = {0: [], 1: []}
        if self.config.enable_voluntary_switch_quality_diagnostics:
            for si in (0, 1):
                active_mon = (
                    battle.active_pokemon[si]
                    if si < len(battle.active_pokemon)
                    else None
                )
                if not active_mon:
                    continue
                if si < len(battle.force_switch) and battle.force_switch[si]:
                    continue
                orders_slot = (
                    valid_orders[si] if valid_orders and len(valid_orders) > si else []
                )
                switch_orders = [
                    o for o in orders_slot if o and isinstance(o.order, Pokemon)
                ]
                if not switch_orders:
                    continue
                # Best stay score from existing raw slot scores
                best_stay = 0.0
                for o in orders_slot:
                    if o and isinstance(o.order, Move):
                        sc = (
                            slot_0_scores.get(id(o), 0.0)
                            if si == 0
                            else slot_1_scores.get(id(o), 0.0)
                        )
                        if sc > best_stay:
                            best_stay = sc
                bt = battle_tag
                history = self._voluntary_switch_history.get((bt, si), {})
                cand_table = build_voluntary_switch_candidate_table(
                    active_mon,
                    switch_orders,
                    si,
                    battle,
                    best_stay,
                    self.config,
                    player=self,
                    voluntary_switch_history=self._voluntary_switch_history,
                )
                _voluntary_switch_candidate_tables[si] = cand_table

                # Build order lookup by action key (exact identity, not species text)
                _order_by_action_key = {}
                for o in switch_orders:
                    if o and isinstance(o.order, Pokemon):
                        ak = _order_action_key(o)
                        _order_by_action_key[ak] = o
                if self.config.enable_voluntary_switch_quality_scoring:
                    for row in cand_table:
                        ak = row.get("candidate_action_key")
                        if ak and ak in _order_by_action_key:
                            o = _order_by_action_key[ak]
                            oid = id(o)
                            adj = row["adjusted_switch_score"]
                            if si == 0:
                                slot_0_scores[oid] = adj
                            else:
                                slot_1_scores[oid] = adj

                    # Phase 6.4.9k: Apply stay penalty to non-switch orders when active is threatened
                    active_hp = getattr(active_mon, "current_hp_fraction", 1.0)
                    stay_penalty = getattr(
                        self.config, "voluntary_switch_stay_penalty", 100.0
                    )

                    # Apply penalty when active is low HP and has no high-value action
                    if active_hp < 0.20 and best_stay < 100.0:
                        # Check if there's at least one safer candidate
                        has_safer_candidate = any(
                            row.get("risk_reduction", 0) > 0.5 for row in cand_table
                        )
                        if has_safer_candidate:
                            # Penalize all non-switch orders for this slot
                            for o in orders_slot:
                                if o and isinstance(o.order, Move):
                                    oid = id(o)
                                    if si == 0:
                                        slot_0_scores[oid] = (
                                            slot_0_scores.get(oid, 0.0) - stay_penalty
                                        )
                                    else:
                                        slot_1_scores[oid] = (
                                            slot_1_scores.get(oid, 0.0) - stay_penalty
                                        )

        _t_js_start = time.time() if _timing_enabled else 0
        scored_joint_orders = self._compute_joint_scores(
            battle,
            self.config,
            joint_orders,
            slot_0_scores,
            slot_1_scores,
            _direct_absorb_blocked,
            _safety_blocked,
            _ally_redirect_blocked,
            _support_target_blocked=_support_target_blocked,
            _narrow_blocked=_narrow_blocked,
        )
        _joint_order_count = len(scored_joint_orders)
        best_joint, best_score, best_score_1, best_score_2 = scored_joint_orders[0]
        if _timing_enabled:
            _t_joint_scoring = (time.time() - _t_js_start) * 1000

        # Phase 6.4.9: Mark selected candidate in candidate tables
        for si in (0, 1):
            sel_order = best_joint.first_order if si == 0 else best_joint.second_order
            sel_key = _order_action_key(sel_order)
            for row in _voluntary_switch_candidate_tables.get(si, []):
                if row.get("candidate_action_key") == sel_key:
                    row["selected"] = True
                    break

        # Phase 6.3.5b: Pure Counterfactual Check for Singleton Levitate Safety (per-slot)
        singleton_selection_changed_by_safety_slot = [False, False]
        if self.config.ability_hard_safety_allow_singleton_deduction:
            import dataclasses

            config_no_singleton = dataclasses.replace(
                self.config, ability_hard_safety_allow_singleton_deduction=False
            )
            cf_result = self._select_best_joint_order(
                battle,
                config_no_singleton,
                joint_orders,
                valid_orders,
                pure=True,
            )
            cf_best_joint = cf_result[0]  # unpack (joint_order, score, s1, s2)
            for _slot_i in (0, 1):
                sel_order = (
                    best_joint.first_order if _slot_i == 0 else best_joint.second_order
                )
                cf_order = (
                    cf_best_joint.first_order
                    if _slot_i == 0
                    else cf_best_joint.second_order
                )
                sel_key = _order_action_key(sel_order)
                cf_key = _order_action_key(cf_order)
                if sel_key != cf_key:
                    singleton_selection_changed_by_safety_slot[_slot_i] = True

        # Phase 6.4.7c: Counterfactual -- stat-drop switch scoring selection changed
        _stat_drop_counterfactual_joint = None
        _stat_drop_counterfactual_actions = ["", ""]
        _stat_drop_actual_actions = ["", ""]
        if self.config.enable_stat_drop_switch_scoring:
            _stat_drop_actual_actions = [
                _order_action_key(best_joint.first_order),
                _order_action_key(best_joint.second_order),
            ]
            try:
                cf_result = self._select_best_joint_order(
                    battle,
                    self.config,
                    joint_orders,
                    valid_orders,
                    pure=True,
                )
                _stat_drop_counterfactual_joint = cf_result[0]
                _stat_drop_counterfactual_actions = [
                    _order_action_key(
                        cf_result[0].first_order if cf_result[0] else None
                    ),
                    _order_action_key(
                        cf_result[0].second_order if cf_result[0] else None
                    ),
                ]
            except Exception:
                _stat_drop_counterfactual_joint = None
                _stat_drop_counterfactual_actions = [("", "", 0), ("", "", 0)]

        # Phase 6.4.9: Counterfactual -- voluntary switch scoring selection changed
        _vsw_selection_changed = [False, False]
        _vsw_joint_selection_changed = False
        _vsw_counterfactual_actions = [("", "", 0), ("", "", 0)]
        _vsw_selected_actions = [
            _order_action_key(best_joint.first_order),
            _order_action_key(best_joint.second_order),
        ]
        if self.config.enable_voluntary_switch_quality_scoring:
            try:
                # Use raw (pre-VSW) scores for counterfactual
                cf_result = select_best_joint_from_score_maps(
                    battle,
                    self.config,
                    joint_orders,
                    _vsw_raw_scores_0,
                    _vsw_raw_scores_1,
                    _direct_absorb_blocked,
                    _safety_blocked,
                    _ally_redirect_blocked,
                    _support_target_blocked,
                )
                cf_best = cf_result[0]
                _vsw_counterfactual_actions = [
                    _order_action_key(cf_best.first_order if cf_best else None),
                    _order_action_key(cf_best.second_order if cf_best else None),
                ]
                for _si in (0, 1):
                    if _vsw_selected_actions[_si] != _vsw_counterfactual_actions[_si]:
                        _vsw_selection_changed[_si] = True
                if any(_vsw_selection_changed):
                    _vsw_joint_selection_changed = True
            except Exception:
                pass

        # Phase 6.4.2: Counterfactual - compute legacy best joint order (without interception bonuses)
        _legacy_joint_order = None
        _selection_changed = False
        _changed_to_switch = False
        if self.config.enable_revealed_move_switch_interception:
            # Re-score joint orders using legacy slot scores (before interception bonuses)
            legacy_scored_joint = []
            for joint_order in joint_orders:
                first = joint_order.first_order
                second = joint_order.second_order
                legacy_score_1 = (
                    _legacy_slot_scores[0].get(id(first), 0.0) if first else 0.0
                )
                legacy_score_2 = (
                    _legacy_slot_scores[1].get(id(second), 0.0) if second else 0.0
                )
                legacy_joint_score = legacy_score_1 + legacy_score_2
                # Apply same synergy penalties (but not interception bonuses)
                first_blocked = (
                    _direct_absorb_blocked.get(id(first), False) if first else False
                )
                second_blocked = (
                    _direct_absorb_blocked.get(id(second), False) if second else False
                )
                either_blocked = first_blocked or second_blocked
                if not either_blocked:
                    if isinstance(first.order, Move) and isinstance(second.order, Move):
                        if (
                            first.move_target == second.move_target
                            and first.move_target in (1, 2)
                        ):
                            target_opp = battle.opponent_active_pokemon[
                                first.move_target - 1
                            ]
                            if target_opp:
                                ko_1 = self.check_move_will_ko(
                                    first.order,
                                    battle.active_pokemon[0],
                                    target_opp,
                                    battle,
                                    config=self.config,
                                )
                                ko_2 = self.check_move_will_ko(
                                    second.order,
                                    battle.active_pokemon[1],
                                    target_opp,
                                    battle,
                                    config=self.config,
                                )
                                opp_hp_fraction = getattr(
                                    target_opp, "current_hp_fraction", 1.0
                                )
                                if (
                                    (ko_1 and ko_2)
                                    or (ko_1 or ko_2)
                                    and opp_hp_fraction < 0.15
                                    or opp_hp_fraction < 0.08
                                ):
                                    allow_double = False
                                    if self.config.enable_threat_scoring:
                                        threat_score = self.score_opponent_threat(
                                            target_opp, battle
                                        )
                                        if threat_score >= 0.50:
                                            allow_double = True
                                    if not allow_double:
                                        legacy_joint_score -= 250.0
                    if self.config.enable_order_aware_overkill:
                        if self.selected_target_will_be_koed_before_second_action(
                            first, second, battle, config=self.config
                        ):
                            legacy_joint_score -= (
                                self.config.order_aware_overkill_penalty
                            )
                legacy_scored_joint.append(
                    (joint_order, legacy_joint_score, legacy_score_1, legacy_score_2)
                )
            legacy_scored_joint.sort(key=lambda x: x[1], reverse=True)
            if legacy_scored_joint:
                _legacy_joint_order, _, _, _ = legacy_scored_joint[0]
                # Compare selected vs legacy
                legacy_msg = (
                    self.safe_get_joint_message(_legacy_joint_order)
                    if _legacy_joint_order
                    else ""
                )
                selected_msg = (
                    self.safe_get_joint_message(best_joint) if best_joint else ""
                )
                if legacy_msg != selected_msg:
                    _selection_changed = True
                    # Check if changed to a switch
                    if _legacy_joint_order:
                        l_first = _legacy_joint_order.first_order
                        l_second = _legacy_joint_order.second_order
                        if isinstance(l_first, SingleBattleOrder) and isinstance(
                            l_first.order, Pokemon
                        ):
                            _changed_to_switch = True
                        if isinstance(l_second, SingleBattleOrder) and isinstance(
                            l_second.order, Pokemon
                        ):
                            _changed_to_switch = True

        # Re-run score_action with is_selected=True to record predictions and Phase 6.1.2 flags on chosen moves
        needs_rerun = True
        if needs_rerun:
            if best_joint.first_order:
                self.score_action(best_joint.first_order, 0, battle, is_selected=True)
            if best_joint.second_order:
                self.score_action(best_joint.second_order, 1, battle, is_selected=True)

        # Phase 6.3.2 Lists
        absorb_immune_move_selected_list = [False, False]
        absorb_selection_forced_list = [False, False]
        absorb_safe_alternative_available_list = [False, False]
        absorb_best_safe_alternative_move_list = ["", ""]
        absorb_best_safe_alternative_target_list = ["", ""]
        absorb_best_safe_alternative_score_list = [0.0, 0.0]
        absorb_selected_score_list = [0.0, 0.0]
        absorb_selected_streak_list = [0, 0]
        direct_known_absorb_repeat_selected_list = [False, False]
        avoidable_absorb_error_list = [False, False]
        productive_partial_absorb_spread_list = [False, False]
        absorb_error_reason_list = ["", ""]
        # Phase 6.3.2a: new target diagnostic fields
        absorb_via_redirection_list = [False, False]
        absorb_intended_target_species_list = ["", ""]
        absorb_intended_target_ability_list = ["", ""]
        absorb_effective_target_species_list = ["", ""]
        absorb_effective_target_ability_list = ["", ""]
        absorb_selected_move_id_list = ["", ""]

        # Phase 6.3.5: Singleton ability safety tracking lists
        known_ability_resolution_source_list = ["", ""]
        deterministic_singleton_ability_used_list = [False, False]
        deterministic_singleton_ability_list = ["", ""]
        deterministic_singleton_target_species_list = ["", ""]
        singleton_ability_hard_block_avoided_list = [False, False]
        singleton_ground_into_levitate_selected_list = [False, False]
        singleton_ability_conflict_detected_list = [False, False]
        singleton_ability_suppressed_list = [False, False]
        singleton_ability_suppression_reason_list = ["", ""]
        singleton_only_legal_action_list = [False, False]

        # Phase 6.3.5b: Observer list variables
        singleton_levitate_opportunity_observed_list = [False, False]
        singleton_ground_into_levitate_selected_observed_list = [False, False]
        singleton_hard_block_applied_list = [False, False]
        singleton_blocked_candidate_observed_list = [False, False]
        singleton_selection_changed_by_safety_list = list(
            singleton_selection_changed_by_safety_slot
        )
        singleton_resolution_source_list = ["", ""]

        # Phase 6.3.5a: Priority Terrain / Ability Safety tracking lists
        priority_move_field_blocked_list = [False, False]
        priority_move_block_reason_list = ["", ""]
        priority_move_selected_into_psychic_terrain_list = [False, False]
        sucker_punch_selected_into_psychic_terrain_list = [False, False]
        priority_move_block_avoided_list = [False, False]
        priority_move_only_legal_list = [False, False]
        priority_target_grounded_list = [False, False]
        priority_target_species_list = ["", ""]
        priority_target_type_1_list = ["", ""]
        priority_target_type_2_list = ["", ""]
        priority_blocking_ability_list = ["", ""]
        priority_blocking_ability_source_list = ["", ""]

        # Phase 6.3.1: Post-process ability safety audit metrics strictly on final selections and legal candidates
        for active_idx in (0, 1):
            active_mon = battle.active_pokemon[active_idx]
            if not active_mon:
                continue

            valid_orders_slot = (
                valid_orders[active_idx]
                if valid_orders
                and len(valid_orders) > active_idx
                and valid_orders[active_idx]
                else []
            )

            # Phase 6.3.5b: Observer Config & Audit Separation
            import dataclasses

            observer_config = dataclasses.replace(
                self.config, ability_hard_safety_allow_singleton_deduction=True
            )

            # 1. singleton_levitate_opportunity_observed
            opportunity_observed = False
            for opp in battle.opponent_active_pokemon:
                if opp and not getattr(opp, "fainted", False):
                    res = resolve_known_ability(opp, battle, config=observer_config)
                    if (
                        res["source"] == "deterministic_singleton"
                        and res["ability"] == "levitate"
                    ):
                        opportunity_observed = True
            singleton_levitate_opportunity_observed_list[active_idx] = (
                opportunity_observed
            )

            # 2. singleton_ground_into_levitate_selected_observed
            ground_selected_observed = False
            chosen_order = (
                best_joint.first_order if active_idx == 0 else best_joint.second_order
            )
            if chosen_order and isinstance(chosen_order.order, Move):
                chosen_move = chosen_order.order
                target_pos = chosen_order.move_target
                if target_pos in (1, 2):
                    target_mon = battle.opponent_active_pokemon[target_pos - 1]
                    if target_mon and not getattr(target_mon, "fainted", False):
                        res = resolve_known_ability(
                            target_mon, battle, config=observer_config
                        )
                        if (
                            res["source"] == "deterministic_singleton"
                            and res["ability"] == "levitate"
                            and not res["is_currently_suppressed"]
                        ):
                            move_type = getattr(chosen_move, "type", None)
                            m_type = (
                                move_type.name.upper()
                                if move_type and hasattr(move_type, "name")
                                else str(move_type).upper()
                            )
                            base_power = getattr(chosen_move, "base_power", 0)
                            if m_type == "GROUND" and base_power > 0:
                                # Apply exclusions: Gravity, Thousand Arrows, Mold Breaker
                                if (
                                    not is_gravity_active(battle)
                                    and getattr(chosen_move, "id", "").lower()
                                    != "thousandarrows"
                                    and not attacker_ignores_target_ability(
                                        active_mon, battle
                                    )
                                ):
                                    ground_selected_observed = True
            singleton_ground_into_levitate_selected_observed_list[active_idx] = (
                ground_selected_observed
            )

            # 3. singleton_hard_block_applied
            hard_block_applied = False
            if self.config.ability_hard_safety_allow_singleton_deduction:
                for ord_cand in valid_orders_slot:
                    if ord_cand and isinstance(ord_cand.order, Move):
                        cand_move = ord_cand.order
                        cand_target_pos = ord_cand.move_target
                        if cand_target_pos in (1, 2):
                            cand_target_mon = battle.opponent_active_pokemon[
                                cand_target_pos - 1
                            ]
                            if cand_target_mon and not getattr(
                                cand_target_mon, "fainted", False
                            ):
                                res_cand = resolve_known_ability(
                                    cand_target_mon, battle, self.config
                                )
                                if (
                                    res_cand["source"] == "deterministic_singleton"
                                    and res_cand["ability"] == "levitate"
                                    and not res_cand["is_currently_suppressed"]
                                ):
                                    blocks_cand, reason = ability_hard_blocks_move(
                                        cand_move,
                                        active_mon,
                                        cand_target_mon,
                                        battle,
                                        config=self.config,
                                    )
                                    if blocks_cand and _ability_block_enabled(
                                        self.config, reason
                                    ):
                                        hard_block_applied = True
                                        break
            singleton_hard_block_applied_list[active_idx] = hard_block_applied

            # 4. singleton_blocked_candidate_observed
            blocked_candidate_observed = False
            for ord_cand in valid_orders_slot:
                if ord_cand and isinstance(ord_cand.order, Move):
                    cand_move = ord_cand.order
                    cand_target_pos = ord_cand.move_target
                    if cand_target_pos in (1, 2):
                        cand_target_mon = battle.opponent_active_pokemon[
                            cand_target_pos - 1
                        ]
                        if cand_target_mon and not getattr(
                            cand_target_mon, "fainted", False
                        ):
                            res_cand = resolve_known_ability(
                                cand_target_mon, battle, config=observer_config
                            )
                            if (
                                res_cand["source"] == "deterministic_singleton"
                                and res_cand["ability"] == "levitate"
                                and not res_cand["is_currently_suppressed"]
                            ):
                                move_type = getattr(cand_move, "type", None)
                                m_type = (
                                    move_type.name.upper()
                                    if move_type and hasattr(move_type, "name")
                                    else str(move_type).upper()
                                )
                                base_power = getattr(cand_move, "base_power", 0)
                                if m_type == "GROUND" and base_power > 0:
                                    if (
                                        not is_gravity_active(battle)
                                        and getattr(cand_move, "id", "").lower()
                                        != "thousandarrows"
                                        and not attacker_ignores_target_ability(
                                            active_mon, battle
                                        )
                                    ):
                                        blocked_candidate_observed = True
                                        break
            singleton_blocked_candidate_observed_list[active_idx] = (
                blocked_candidate_observed
            )

            # 5. singleton_only_legal_action
            only_legal = False
            if ground_selected_observed:
                only_legal = classify_only_legal(
                    joint_orders, active_idx, chosen_order, _safety_blocked
                )
            singleton_only_legal_action_list[active_idx] = only_legal

            # 6. singleton_resolution_source
            resolution_source = ""
            if chosen_order and isinstance(chosen_order.order, Move):
                chosen_target_pos = chosen_order.move_target
                if chosen_target_pos in (1, 2):
                    chosen_target_mon = battle.opponent_active_pokemon[
                        chosen_target_pos - 1
                    ]
                    if chosen_target_mon:
                        res = resolve_known_ability(
                            chosen_target_mon, battle, config=observer_config
                        )
                        resolution_source = res["source"]
            if not resolution_source:
                for ord_cand in valid_orders_slot:
                    if ord_cand and isinstance(ord_cand.order, Move):
                        cand_target_pos = ord_cand.move_target
                        if cand_target_pos in (1, 2):
                            cand_target_mon = battle.opponent_active_pokemon[
                                cand_target_pos - 1
                            ]
                            if cand_target_mon:
                                res_cand = resolve_known_ability(
                                    cand_target_mon, battle, config=observer_config
                                )
                                if res_cand["source"] == "deterministic_singleton":
                                    resolution_source = "deterministic_singleton"
                                    break
            singleton_resolution_source_list[active_idx] = resolution_source

            # Keep legacy resolution tracking compatibility for existing logger fields
            if chosen_order and isinstance(chosen_order.order, Move):
                chosen_move = chosen_order.order
                target_pos = chosen_order.move_target
                if target_pos in (1, 2):
                    target_mon = battle.opponent_active_pokemon[target_pos - 1]
                    if target_mon:
                        res = resolve_known_ability(target_mon, battle, self.config)
                        known_ability_resolution_source_list[active_idx] = res["source"]
                        if res["source"] == "deterministic_singleton":
                            deterministic_singleton_ability_used_list[active_idx] = True
                            deterministic_singleton_ability_list[active_idx] = res[
                                "ability"
                            ]
                            deterministic_singleton_target_species_list[active_idx] = (
                                target_mon.species
                            )
                        singleton_ability_suppressed_list[active_idx] = res[
                            "is_currently_suppressed"
                        ]
                        singleton_ability_suppression_reason_list[active_idx] = res[
                            "suppression_reason"
                        ]

                        move_type = getattr(chosen_move, "type", None)
                        m_type = (
                            move_type.name.upper()
                            if move_type and hasattr(move_type, "name")
                            else str(move_type).upper()
                        )
                        if (
                            res["ability"] == "levitate"
                            and m_type == "GROUND"
                            and res["source"] == "deterministic_singleton"
                            and not res["is_currently_suppressed"]
                        ):
                            singleton_ground_into_levitate_selected_list[active_idx] = (
                                True
                            )

            singleton_blocked_candidate_exists = False
            singleton_blocked_sample = None
            for ord_cand in valid_orders_slot:
                if not ord_cand or not isinstance(ord_cand.order, Move):
                    continue
                cand_move = ord_cand.order
                cand_target_pos = ord_cand.move_target
                if cand_target_pos in (1, 2):
                    cand_target_mon = battle.opponent_active_pokemon[
                        cand_target_pos - 1
                    ]
                    if cand_target_mon:
                        res_cand = resolve_known_ability(
                            cand_target_mon, battle, self.config
                        )
                        if (
                            res_cand["source"] == "deterministic_singleton"
                            and res_cand["ability"]
                            and not res_cand["is_currently_suppressed"]
                        ):
                            blocks_cand, _ = ability_hard_blocks_move(
                                cand_move,
                                active_mon,
                                cand_target_mon,
                                battle,
                                self.config,
                            )
                            if blocks_cand:
                                singleton_blocked_candidate_exists = True
                                singleton_blocked_sample = (res_cand, cand_target_mon)
                                break

            is_chosen_blocked = False
            if chosen_order and isinstance(chosen_order.order, Move):
                chosen_target_pos = chosen_order.move_target
                if chosen_target_pos in (1, 2):
                    chosen_target_mon = battle.opponent_active_pokemon[
                        chosen_target_pos - 1
                    ]
                    if chosen_target_mon:
                        is_chosen_blocked, _ = ability_hard_blocks_move(
                            chosen_order.order,
                            active_mon,
                            chosen_target_mon,
                            battle,
                            self.config,
                        )

            if singleton_blocked_candidate_exists and not is_chosen_blocked:
                singleton_ability_hard_block_avoided_list[active_idx] = True
                if singleton_blocked_sample:
                    res_cand, target_mon = singleton_blocked_sample
                    known_ability_resolution_source_list[active_idx] = res_cand[
                        "source"
                    ]
                    deterministic_singleton_ability_used_list[active_idx] = True
                    deterministic_singleton_ability_list[active_idx] = res_cand[
                        "ability"
                    ]
                    deterministic_singleton_target_species_list[active_idx] = (
                        target_mon.species
                    )
            chosen_order = (
                best_joint.first_order if active_idx == 0 else best_joint.second_order
            )
            slot_scores = slot_0_scores if active_idx == 0 else slot_1_scores

            # 1. Determine if the chosen action is a blocked action or redirected-blocked action
            is_chosen_blocked = False
            is_chosen_redirected = False

            if chosen_order and isinstance(chosen_order.order, Move):
                chosen_move = chosen_order.order
                chosen_target_pos = chosen_order.move_target
                if chosen_target_pos in (1, 2):
                    chosen_target_mon = battle.opponent_active_pokemon[
                        chosen_target_pos - 1
                    ]
                    if chosen_target_mon:
                        blocks, reason = ability_hard_blocks_move(
                            chosen_move,
                            active_mon,
                            chosen_target_mon,
                            battle,
                            config=self.config,
                        )
                        if blocks and _ability_block_enabled(self.config, reason):
                            is_chosen_blocked = True
                        else:
                            redirects, red_reason = (
                                ability_redirects_single_target_move(
                                    chosen_move,
                                    chosen_target_mon,
                                    battle.opponent_active_pokemon,
                                    active_mon,
                                    battle,
                                )
                            )
                            if redirects:
                                red_target = None
                                for opp in battle.opponent_active_pokemon:
                                    if (
                                        opp
                                        and opp != chosen_target_mon
                                        and not getattr(opp, "fainted", False)
                                    ):
                                        opp_ability = get_known_ability(opp, battle)
                                        if opp_ability in (
                                            "stormdrain",
                                            "lightningrod",
                                        ):
                                            red_target = opp
                                            break
                                if red_target:
                                    blocks_red, reason_red = ability_hard_blocks_move(
                                        chosen_move,
                                        active_mon,
                                        red_target,
                                        battle,
                                        config=self.config,
                                    )
                                    if blocks_red and _ability_block_enabled(
                                        self.config, reason_red
                                    ):
                                        is_chosen_redirected = True
                elif is_opponent_spread_move(chosen_move, chosen_order):
                    for opp in battle.opponent_active_pokemon:
                        if opp:
                            blocked, reason = ability_hard_blocks_move(
                                chosen_move, active_mon, opp, battle, config=self.config
                            )
                            if blocked and _ability_block_enabled(self.config, reason):
                                is_chosen_blocked = True
                                break

            # 2. Inspect legal orders once per slot to find any candidate scored down by enabled hard safety
            hard_block_candidate_exists = False
            redirection_candidate_exists = False
            block_sample = None  # (reason, target_mon)
            redirection_sample = None  # (reason, target_mon)

            for ord_cand in valid_orders_slot:
                if not ord_cand or not isinstance(ord_cand.order, Move):
                    continue
                cand_move = ord_cand.order
                cand_target_pos = ord_cand.move_target

                if cand_target_pos in (1, 2):
                    cand_target_mon = battle.opponent_active_pokemon[
                        cand_target_pos - 1
                    ]
                    if cand_target_mon:
                        blocks, reason = ability_hard_blocks_move(
                            cand_move,
                            active_mon,
                            cand_target_mon,
                            battle,
                            config=self.config,
                        )
                        if blocks and _ability_block_enabled(self.config, reason):
                            hard_block_candidate_exists = True
                            if not block_sample:
                                block_sample = (reason, cand_target_mon)
                        else:
                            redirects, red_reason = (
                                ability_redirects_single_target_move(
                                    cand_move,
                                    cand_target_mon,
                                    battle.opponent_active_pokemon,
                                    active_mon,
                                    battle,
                                )
                            )
                            if redirects:
                                red_target = None
                                for opp in battle.opponent_active_pokemon:
                                    if (
                                        opp
                                        and opp != cand_target_mon
                                        and not getattr(opp, "fainted", False)
                                    ):
                                        opp_ability = get_known_ability(opp, battle)
                                        if opp_ability in (
                                            "stormdrain",
                                            "lightningrod",
                                        ):
                                            red_target = opp
                                            break
                                if red_target:
                                    blocks_red, reason_red = ability_hard_blocks_move(
                                        cand_move,
                                        active_mon,
                                        red_target,
                                        battle,
                                        config=self.config,
                                    )
                                    if blocks_red and _ability_block_enabled(
                                        self.config, reason_red
                                    ):
                                        redirection_candidate_exists = True
                                        if not redirection_sample:
                                            redirection_sample = (
                                                red_reason,
                                                red_target,
                                            )
                elif is_opponent_spread_move(cand_move, ord_cand):
                    for opp in battle.opponent_active_pokemon:
                        if opp:
                            blocked, reason = ability_hard_blocks_move(
                                cand_move, active_mon, opp, battle, config=self.config
                            )
                            if blocked and _ability_block_enabled(self.config, reason):
                                hard_block_candidate_exists = True
                                if not block_sample:
                                    block_sample = (reason, opp)
                                break

            # 3. Set the avoided flags and deterministic samples
            if hard_block_candidate_exists and not is_chosen_blocked:
                self._ability_hard_block_avoided[battle_tag][active_idx] = True
                if (
                    block_sample
                    and not self._ability_block_reason[battle_tag][active_idx]
                ):
                    reason, target_mon = block_sample
                    self._ability_block_reason[battle_tag][active_idx] = reason
                    self._ability_blocked_target_species[battle_tag][active_idx] = (
                        target_mon.species
                    )
                    self._ability_blocked_target_ability[battle_tag][active_idx] = (
                        get_known_ability(target_mon, battle) or ""
                    )

            if redirection_candidate_exists and not is_chosen_redirected:
                self._ability_redirection_avoided[battle_tag][active_idx] = True
                if (
                    redirection_sample
                    and not self._ability_block_reason[battle_tag][active_idx]
                ):
                    reason, target_mon = redirection_sample
                    self._ability_block_reason[battle_tag][active_idx] = reason
                    self._ability_blocked_target_species[battle_tag][active_idx] = (
                        target_mon.species
                    )
                    self._ability_blocked_target_ability[battle_tag][active_idx] = (
                        get_known_ability(target_mon, battle) or ""
                    )

            # Phase 6.3.3 direct safety calculations (audit / logging paths)
            is_chosen_direct_blocked = False
            chosen_direct_reason = ""
            chosen_direct_target_mon = None
            if chosen_order and isinstance(chosen_order.order, Move):
                chosen_move = chosen_order.order
                chosen_target_pos = chosen_order.move_target
                if chosen_target_pos in (1, 2):
                    chosen_direct_target_mon = battle.opponent_active_pokemon[
                        chosen_target_pos - 1
                    ]
                    if chosen_direct_target_mon:
                        if not is_opponent_spread_move(chosen_move, chosen_order):
                            blocks_d, reason_d = direct_known_absorb_blocks_move(
                                chosen_move,
                                active_mon,
                                chosen_direct_target_mon,
                                battle,
                                chosen_order,
                            )
                            if blocks_d:
                                is_chosen_direct_blocked = True
                                chosen_direct_reason = reason_d

            if is_chosen_direct_blocked and chosen_direct_target_mon:
                self._direct_absorb_immune_move_selected[battle_tag][active_idx] = True
                self._direct_absorb_block_reason[battle_tag][active_idx] = (
                    chosen_direct_reason
                )
                self._direct_absorb_target_species[battle_tag][active_idx] = (
                    chosen_direct_target_mon.species
                )
                self._direct_absorb_target_ability[battle_tag][active_idx] = (
                    get_known_ability(chosen_direct_target_mon, battle) or ""
                )

            direct_block_candidate_exists = False
            direct_block_sample = None
            for ord_cand in valid_orders_slot:
                if not ord_cand or not isinstance(ord_cand.order, Move):
                    continue
                cand_move = ord_cand.order
                cand_target_pos = ord_cand.move_target
                if cand_target_pos in (1, 2):
                    cand_target_mon = battle.opponent_active_pokemon[
                        cand_target_pos - 1
                    ]
                    if cand_target_mon:
                        if not is_opponent_spread_move(cand_move, ord_cand):
                            blocks_d, reason_d = direct_known_absorb_blocks_move(
                                cand_move, active_mon, cand_target_mon, battle, ord_cand
                            )
                            if blocks_d:
                                direct_block_candidate_exists = True
                                if not direct_block_sample:
                                    direct_block_sample = (reason_d, cand_target_mon)

            if direct_block_candidate_exists and not is_chosen_direct_blocked:
                if getattr(
                    self.config, "ability_hard_safety_direct_absorb_only", False
                ):
                    self._direct_absorb_hard_block_avoided[battle_tag][active_idx] = (
                        True
                    )
                    if (
                        direct_block_sample
                        and not self._direct_absorb_block_reason[battle_tag][active_idx]
                    ):
                        reason_d, target_mon = direct_block_sample
                        self._direct_absorb_block_reason[battle_tag][active_idx] = (
                            reason_d
                        )
                        self._direct_absorb_target_species[battle_tag][active_idx] = (
                            target_mon.species
                        )
                        self._direct_absorb_target_ability[battle_tag][active_idx] = (
                            get_known_ability(target_mon, battle) or ""
                        )

            self._direct_absorb_only_legal_action[battle_tag][active_idx] = (
                is_chosen_direct_blocked and len(valid_orders_slot) == 1
            )

            # Phase 6.3.2 Calculations:
            absorb_immune_move_selected = False
            absorb_selection_forced = False
            absorb_safe_alternative_available = False
            absorb_best_safe_alternative_move = ""
            absorb_best_safe_alternative_target = ""
            absorb_best_safe_alternative_score = 0.0
            absorb_selected_score = best_score_1 if active_idx == 0 else best_score_2
            absorb_selected_streak = 0
            avoidable_absorb_error = False
            productive_partial_absorb_spread = False
            absorb_error_reason = ""
            # Phase 6.3.2a diagnostic fields
            absorb_via_redirection = False
            absorb_intended_target_species = ""
            absorb_intended_target_ability = ""
            absorb_effective_target_species = ""
            absorb_effective_target_ability = ""
            absorb_selected_move_id = ""

            blocked_target_species = ""  # effective target for streak key
            blocked_target_reason = ""

            if (
                chosen_order
                and isinstance(chosen_order.order, Move)
                and getattr(chosen_order.order, "base_power", 0) > 0
            ):
                chosen_move = chosen_order.order
                chosen_target_pos = chosen_order.move_target

                absorb_selected_move_id = chosen_move.id

                # Check single-target move
                if chosen_target_pos in (1, 2):
                    chosen_target_mon = battle.opponent_active_pokemon[
                        chosen_target_pos - 1
                    ]
                    if chosen_target_mon:
                        intended_species = chosen_target_mon.species
                        intended_ability = (
                            get_known_ability(chosen_target_mon, battle) or ""
                        )

                        # Check direct block
                        blocks, reason = ability_hard_blocks_move(
                            chosen_move,
                            active_mon,
                            chosen_target_mon,
                            battle,
                            config=self.config,
                        )
                        if blocks:
                            target_ab = get_known_ability(chosen_target_mon, battle)
                            if is_known_absorb_ability(target_ab):
                                absorb_immune_move_selected = True
                                absorb_error_reason = reason
                                # Direct: intended == effective
                                absorb_via_redirection = False
                                absorb_intended_target_species = intended_species
                                absorb_intended_target_ability = intended_ability
                                absorb_effective_target_species = intended_species
                                absorb_effective_target_ability = intended_ability
                                blocked_target_species = (
                                    chosen_target_mon.species
                                )  # effective for streak
                                blocked_target_reason = reason

                        # Check redirection block
                        if not absorb_immune_move_selected:
                            redirects, red_reason = (
                                ability_redirects_single_target_move(
                                    chosen_move,
                                    chosen_target_mon,
                                    battle.opponent_active_pokemon,
                                    active_mon,
                                    battle,
                                )
                            )
                            if redirects:
                                red_target = None
                                for opp in battle.opponent_active_pokemon:
                                    if (
                                        opp
                                        and opp != chosen_target_mon
                                        and not getattr(opp, "fainted", False)
                                    ):
                                        opp_ability = get_known_ability(opp, battle)
                                        if opp_ability in (
                                            "stormdrain",
                                            "lightningrod",
                                        ):
                                            red_target = opp
                                            break
                                if red_target:
                                    blocks_red, reason_red = ability_hard_blocks_move(
                                        chosen_move,
                                        active_mon,
                                        red_target,
                                        battle,
                                        config=self.config,
                                    )
                                    if blocks_red:
                                        target_ab = get_known_ability(
                                            red_target, battle
                                        )
                                        if is_known_absorb_ability(target_ab):
                                            absorb_immune_move_selected = True
                                            absorb_error_reason = reason_red
                                            # Redirection: intended is chosen slot, effective is redirector
                                            absorb_via_redirection = True
                                            absorb_intended_target_species = (
                                                intended_species
                                            )
                                            absorb_intended_target_ability = (
                                                intended_ability
                                            )
                                            absorb_effective_target_species = (
                                                red_target.species
                                            )
                                            absorb_effective_target_ability = (
                                                get_known_ability(red_target, battle)
                                                or ""
                                            )
                                            blocked_target_species = (
                                                red_target.species
                                            )  # effective for streak
                                            blocked_target_reason = reason_red

                # Check spread move
                elif is_opponent_spread_move(chosen_move, chosen_order):
                    opponents = [
                        opp
                        for opp in battle.opponent_active_pokemon
                        if opp and not getattr(opp, "fainted", False)
                    ]
                    if opponents:
                        blocked_opps = []
                        blocked_reasons = []
                        for opp in opponents:
                            blocked, reason = ability_hard_blocks_move(
                                chosen_move, active_mon, opp, battle, config=self.config
                            )
                            if blocked:
                                opp_ab = get_known_ability(opp, battle)
                                if is_known_absorb_ability(opp_ab):
                                    blocked_opps.append(opp)
                                    blocked_reasons.append(reason)

                        if len(blocked_opps) > 0:
                            absorb_immune_move_selected = True
                            if len(blocked_opps) < len(opponents):
                                productive_partial_absorb_spread = True
                            else:
                                productive_partial_absorb_spread = False
                            blocked_target_species = "+".join(
                                sorted([o.species for o in blocked_opps])
                            )
                            blocked_target_reason = "+".join(sorted(blocked_reasons))
                            absorb_error_reason = blocked_target_reason
                            # Spread: no redirection concept; intended == effective == all blocked
                            absorb_via_redirection = False
                            absorb_intended_target_species = blocked_target_species
                            absorb_intended_target_ability = "+".join(
                                sorted(
                                    [
                                        get_known_ability(o, battle) or ""
                                        for o in blocked_opps
                                    ]
                                )
                            )
                            absorb_effective_target_species = blocked_target_species
                            absorb_effective_target_ability = (
                                absorb_intended_target_ability
                            )

            if absorb_immune_move_selected:
                # Inspect alternative moves using canonical precomputed slot_scores.
                # Do NOT call score_action here to avoid mutating audit/streak state.
                best_safe_alt_move = ""
                best_safe_alt_target = ""
                best_safe_alt_score = 0.0
                safe_alt_available = False

                has_switch = False
                has_status = False

                for ord_cand in valid_orders_slot:
                    if not ord_cand:
                        continue
                    # Skip the selected order itself to avoid counting it as its own best alternative
                    if ord_cand is (
                        best_joint.first_order
                        if active_idx == 0
                        else best_joint.second_order
                    ):
                        continue
                    cand_score = slot_scores.get(id(ord_cand), 0.0)
                    if isinstance(ord_cand.order, Pokemon):
                        if cand_score > 0.0:
                            has_switch = True
                    elif isinstance(ord_cand.order, Move):
                        move_obj = ord_cand.order
                        if getattr(move_obj, "base_power", 0) > 0:
                            # Use canonical precomputed score; safety predicate only
                            is_safe = is_alternative_safe_damaging_predicate(
                                ord_cand, active_mon, battle
                            )
                            if is_safe and cand_score > 0.0:
                                safe_alt_available = True
                                if cand_score > best_safe_alt_score:
                                    best_safe_alt_score = cand_score
                                    best_safe_alt_move = move_obj.id
                                    if ord_cand.move_target in (1, 2):
                                        t_mon = battle.opponent_active_pokemon[
                                            ord_cand.move_target - 1
                                        ]
                                        best_safe_alt_target = (
                                            t_mon.species
                                            if t_mon
                                            else f"opponent_{ord_cand.move_target}"
                                        )
                                    else:
                                        best_safe_alt_target = "spread"
                        else:
                            if cand_score > 0.0:
                                has_status = True

                absorb_safe_alternative_available = safe_alt_available
                absorb_best_safe_alternative_move = best_safe_alt_move
                absorb_best_safe_alternative_target = best_safe_alt_target
                absorb_best_safe_alternative_score = best_safe_alt_score

                if not (safe_alt_available or has_switch or has_status):
                    absorb_selection_forced = True

                if safe_alt_available and not productive_partial_absorb_spread:
                    avoidable_absorb_error = True

                # Update streak tracking using stable attacker identity (not slot index).
                # Key: (attacker_ident, move_id, effective_target_species, reason)
                # Idempotent: if same (attacker, move, effective_target, reason, turn) as
                # previous recorded state, preserve streak without incrementing.
                curr_attacker_ident = self.get_pokemon_identifier(active_mon)
                curr_move_id = chosen_order.order.id
                curr_effective_target = (
                    blocked_target_species  # effective (redirected) target
                )
                curr_reason_key = blocked_target_reason
                curr_turn = battle.turn

                streak_key = curr_attacker_ident
                battle_streak_map = self._absorb_streak_state[battle_tag]
                prev_state = battle_streak_map.get(streak_key)

                if prev_state is not None and (
                    prev_state["move"] == curr_move_id
                    and prev_state["effective_target"] == curr_effective_target
                    and prev_state["reason"] == curr_reason_key
                ):
                    if prev_state["turn"] == curr_turn:
                        # Same event evaluated again on the same turn: idempotent, preserve streak
                        new_streak = prev_state["streak"]
                    elif curr_turn - prev_state["turn"] == 1:
                        # Same event on the immediately following turn: increment
                        new_streak = prev_state["streak"] + 1
                    else:
                        # Turn gap > 1: reset
                        new_streak = 1
                else:
                    # Different event (move, target, or reason changed): reset
                    new_streak = 1

                battle_streak_map[streak_key] = {
                    "move": curr_move_id,
                    "effective_target": curr_effective_target,
                    "reason": curr_reason_key,
                    "turn": curr_turn,
                    "streak": new_streak,
                }
                absorb_selected_streak = new_streak
            else:
                # Clear any existing streak for this attacker if no absorb this turn
                # Skip clearing if this is a mid-turn force-switch request where moves cannot be selected.
                if not any(battle.force_switch):
                    curr_attacker_ident = self.get_pokemon_identifier(active_mon)
                    self._absorb_streak_state[battle_tag].pop(curr_attacker_ident, None)
                absorb_selected_streak = 0

            # Phase 6.3.5a: Priority Terrain / Ability Safety Calculations
            chosen_order = (
                best_joint.first_order if active_idx == 0 else best_joint.second_order
            )

            # 1. Determine if the chosen action is a priority blocked action
            priority_blocked = False
            priority_block_reason = ""
            priority_selected_into_psychic_terrain = False
            sucker_punch_selected_into_psychic_terrain = False
            priority_target_grounded = False
            priority_target_species = ""
            priority_target_type_1 = ""
            priority_target_type_2 = ""
            priority_blocking_ability = ""
            priority_blocking_ability_source = ""

            if chosen_order and isinstance(chosen_order.order, Move):
                chosen_move = chosen_order.order
                target_pos = chosen_order.move_target
                if target_pos in (1, 2):
                    target_mon = battle.opponent_active_pokemon[target_pos - 1]
                    if target_mon:
                        priority_res = evaluate_priority_move_legality(
                            chosen_move, active_mon, target_mon, battle, self.config
                        )
                        if priority_res["is_priority_move"]:
                            priority_target_grounded = priority_res[
                                "intended_target_grounded"
                            ]
                            priority_target_species = target_mon.species
                            t_types = getattr(target_mon, "types", [])
                            if len(t_types) > 0 and t_types[0]:
                                priority_target_type_1 = (
                                    t_types[0].name.upper()
                                    if hasattr(t_types[0], "name")
                                    else str(t_types[0]).upper()
                                )
                            if len(t_types) > 1 and t_types[1]:
                                priority_target_type_2 = (
                                    t_types[1].name.upper()
                                    if hasattr(t_types[1], "name")
                                    else str(t_types[1]).upper()
                                )

                            priority_blocking_ability = priority_res["blocking_ability"]
                            priority_blocking_ability_source = priority_res[
                                "blocking_ability_source"
                            ]

                            if priority_res["blocked"]:
                                priority_blocked = True
                                priority_block_reason = priority_res["reason"]
                                if (
                                    priority_res["reason"]
                                    == "priority_blocked_by_psychic_terrain"
                                ):
                                    priority_selected_into_psychic_terrain = True
                                    if (
                                        getattr(chosen_move, "id", "").lower()
                                        == "suckerpunch"
                                    ):
                                        sucker_punch_selected_into_psychic_terrain = (
                                            True
                                        )

            # 2. Check if a blocked candidate was avoided
            priority_blocked_candidate_exists = False
            priority_blocked_sample = None

            for ord_cand in valid_orders_slot:
                if not ord_cand or not isinstance(ord_cand.order, Move):
                    continue
                cand_move = ord_cand.order
                cand_target_pos = ord_cand.move_target
                if cand_target_pos in (1, 2):
                    cand_target_mon = battle.opponent_active_pokemon[
                        cand_target_pos - 1
                    ]
                    if cand_target_mon:
                        priority_res_cand = evaluate_priority_move_legality(
                            cand_move, active_mon, cand_target_mon, battle, self.config
                        )
                        if priority_res_cand["blocked"]:
                            priority_blocked_candidate_exists = True
                            priority_blocked_sample = (
                                priority_res_cand,
                                cand_target_mon,
                            )
                            break

            priority_block_avoided = False
            if priority_blocked_candidate_exists and not priority_blocked:
                priority_block_avoided = True
                if priority_blocked_sample:
                    priority_res_cand, target_mon = priority_blocked_sample
                    priority_target_grounded = priority_res_cand[
                        "intended_target_grounded"
                    ]
                    priority_target_species = target_mon.species
                    t_types = getattr(target_mon, "types", [])
                    if len(t_types) > 0 and t_types[0]:
                        priority_target_type_1 = (
                            t_types[0].name.upper()
                            if hasattr(t_types[0], "name")
                            else str(t_types[0]).upper()
                        )
                    if len(t_types) > 1 and t_types[1]:
                        priority_target_type_2 = (
                            t_types[1].name.upper()
                            if hasattr(t_types[1], "name")
                            else str(t_types[1]).upper()
                        )
                    priority_blocking_ability = priority_res_cand["blocking_ability"]
                    priority_blocking_ability_source = priority_res_cand[
                        "blocking_ability_source"
                    ]
                    priority_block_reason = priority_res_cand["reason"]

            # 3. Check only-legal
            priority_only_legal = False
            if priority_blocked and len(valid_orders_slot) == 1:
                priority_only_legal = True

            # Assign lists
            priority_move_field_blocked_list[active_idx] = priority_blocked
            priority_move_block_reason_list[active_idx] = priority_block_reason
            priority_move_selected_into_psychic_terrain_list[active_idx] = (
                priority_selected_into_psychic_terrain
            )
            sucker_punch_selected_into_psychic_terrain_list[active_idx] = (
                sucker_punch_selected_into_psychic_terrain
            )
            priority_move_block_avoided_list[active_idx] = priority_block_avoided
            priority_move_only_legal_list[active_idx] = priority_only_legal
            priority_target_grounded_list[active_idx] = priority_target_grounded
            priority_target_species_list[active_idx] = priority_target_species
            priority_target_type_1_list[active_idx] = priority_target_type_1
            priority_target_type_2_list[active_idx] = priority_target_type_2
            priority_blocking_ability_list[active_idx] = priority_blocking_ability
            priority_blocking_ability_source_list[active_idx] = (
                priority_blocking_ability_source
            )

            # Assign lists
            absorb_immune_move_selected_list[active_idx] = absorb_immune_move_selected
            absorb_selection_forced_list[active_idx] = absorb_selection_forced
            absorb_safe_alternative_available_list[active_idx] = (
                absorb_safe_alternative_available
            )
            absorb_best_safe_alternative_move_list[active_idx] = (
                absorb_best_safe_alternative_move
            )
            absorb_best_safe_alternative_target_list[active_idx] = (
                absorb_best_safe_alternative_target
            )
            absorb_best_safe_alternative_score_list[active_idx] = (
                absorb_best_safe_alternative_score
            )
            absorb_selected_score_list[active_idx] = absorb_selected_score
            absorb_selected_streak_list[active_idx] = absorb_selected_streak
            # Phase 6.3.6: Direct known absorb repeat detection
            _direct_absorb_selected = self._direct_absorb_immune_move_selected.get(
                battle_tag, {}
            ).get(active_idx, False)
            direct_known_absorb_repeat_selected_list[active_idx] = (
                _direct_absorb_selected and absorb_selected_streak >= 2
            )
            avoidable_absorb_error_list[active_idx] = avoidable_absorb_error
            productive_partial_absorb_spread_list[active_idx] = (
                productive_partial_absorb_spread
            )
            absorb_error_reason_list[active_idx] = absorb_error_reason
            # Phase 6.3.2a new target diagnostic fields
            absorb_via_redirection_list[active_idx] = absorb_via_redirection
            absorb_intended_target_species_list[active_idx] = (
                absorb_intended_target_species
            )
            absorb_intended_target_ability_list[active_idx] = (
                absorb_intended_target_ability
            )
            absorb_effective_target_species_list[active_idx] = (
                absorb_effective_target_species
            )
            absorb_effective_target_ability_list[active_idx] = (
                absorb_effective_target_ability
            )
            absorb_selected_move_id_list[active_idx] = absorb_selected_move_id

        # Re-evaluate Synergy Rule 1 meta Protect penalty for chosen orders -- old meta engine
        if self.config.enable_meta_opponent_modeling and self.meta_engine:
            fo_1 = best_joint.first_order
            fo_2 = best_joint.second_order
            if (
                fo_1
                and fo_2
                and isinstance(fo_1.order, Move)
                and isinstance(fo_2.order, Move)
            ):
                if fo_1.move_target == fo_2.move_target and fo_1.move_target in (1, 2):
                    target_opp = battle.opponent_active_pokemon[fo_1.move_target - 1]
                    if target_opp:
                        t_species = target_opp.species
                        t_revealed = list(target_opp.moves.keys())
                        likely_protect, prob, reason = (
                            self.meta_engine.likely_has_protect(
                                t_species,
                                t_revealed,
                                threshold=self.config.meta_move_probability_threshold,
                            )
                        )
                        if likely_protect:
                            self.increment_metric(
                                self.selected_meta_predictions_by_battle, battle_tag
                            )
                            self.increment_metric(
                                self.meta_predictions_used_by_battle, battle_tag
                            )
                            self.increment_metric(
                                self.meta_protect_predictions_by_battle, battle_tag
                            )
                            self.total_meta_score_delta_by_battle[battle_tag] = (
                                self.total_meta_score_delta_by_battle.get(
                                    battle_tag, 0.0
                                )
                                + 15.0
                            )
                            if self.verbose:
                                print(
                                    f"[Meta Prediction] species={t_species} type=protect prob={prob:.2f} action=joint_double_target delta=-15.0"
                                )

        # Re-evaluate joint Protect double-targeting for random-set engine
        if self.config.enable_random_set_opponent_modeling and self.random_set_engine:
            fo_1 = best_joint.first_order
            fo_2 = best_joint.second_order
            if (
                fo_1
                and fo_2
                and isinstance(fo_1.order, Move)
                and isinstance(fo_2.order, Move)
            ):
                if fo_1.move_target == fo_2.move_target and fo_1.move_target in (1, 2):
                    target_opp = battle.opponent_active_pokemon[fo_1.move_target - 1]
                    if target_opp:
                        t_species = target_opp.species
                        t_revealed = list(target_opp.moves.keys())
                        likely_protect, prob, _ = (
                            self.random_set_engine.likely_has_protect(
                                t_species,
                                t_revealed,
                                threshold=self.config.random_set_probability_threshold,
                            )
                        )
                        if likely_protect:
                            self.increment_metric(
                                self.rs_selected_predictions_by_battle, battle_tag
                            )
                            self.increment_metric(
                                self.rs_predictions_used_by_battle, battle_tag
                            )
                            self.increment_metric(
                                self.rs_protect_predictions_by_battle, battle_tag
                            )
                            self.rs_score_delta_by_battle[battle_tag] = (
                                self.rs_score_delta_by_battle.get(battle_tag, 0.0)
                                + 12.0
                            )
                            if self.verbose:
                                print(
                                    f"[RS Prediction] protect: {t_species} p={prob:.2f} joint_double_target delta=-12.0"
                                )

        # Increment metrics and track Protect turn for chosen orders
        for idx, order in enumerate([best_joint.first_order, best_joint.second_order]):
            if order and isinstance(order.order, Move):
                m = order.order
                if m.id in (
                    "protect",
                    "detect",
                    "spikyshield",
                    "kingsshield",
                    "banefulbunker",
                ):
                    self.battle_metrics[battle_tag]["protect"] += 1
                    mon = battle.active_pokemon[idx]
                    if mon:
                        mon_id = self.get_pokemon_identifier(mon)
                        self.last_protect_turn.setdefault(battle_tag, {})[
                            (idx, mon_id)
                        ] = current_turn
                elif m.id == "fakeout":
                    self.battle_metrics[battle_tag]["fake_out"] += 1
                if is_opponent_spread_move(m, order):
                    self.battle_metrics[battle_tag]["spread"] += 1
                    is_inefficient = self.inefficient_partial_spread_by_battle.get(
                        battle_tag, {}
                    ).get(idx, False)
                    if not is_inefficient:
                        self.battle_metrics[battle_tag]["valid_spread"] = (
                            self.battle_metrics[battle_tag].get("valid_spread", 0) + 1
                        )

        # Check for focus-fire metric (both target the same opponent)
        fo_1 = best_joint.first_order
        fo_2 = best_joint.second_order
        if (
            fo_1
            and fo_2
            and isinstance(fo_1.order, Move)
            and isinstance(fo_2.order, Move)
        ):
            if fo_1.move_target == fo_2.move_target and fo_1.move_target in (1, 2):
                self.battle_metrics[battle_tag]["focus_fire"] += 1

        # Increment threat contribution metric if enabled
        if self.config.enable_threat_scoring:
            threat_contrib = 0.0
            for idx, order in enumerate(
                [best_joint.first_order, best_joint.second_order]
            ):
                if (
                    order
                    and isinstance(order.order, Move)
                    and order.move_target in (1, 2)
                ):
                    target_mon = battle.opponent_active_pokemon[order.move_target - 1]
                    if target_mon:
                        threat_score = self.score_opponent_threat(target_mon, battle)
                        threat_contrib += (
                            threat_score * self.config.threat_targeting_weight
                        )
            self.battle_metrics[battle_tag]["threat_contribution"] += threat_contrib

        # Check and increment tiebreaker and boosted override activations per battle
        for idx, order in enumerate([best_joint.first_order, best_joint.second_order]):
            if (
                order
                and isinstance(order.order, Move)
                and getattr(order.order, "base_power", 0) > 0
                and order.move_target in (1, 2)
            ):
                target_mon = battle.opponent_active_pokemon[order.move_target - 1]
                active_mon = battle.active_pokemon[idx]
                if target_mon and active_mon:
                    # Let's check tiebreaker
                    if self.config.enable_threat_tiebreaker:
                        # 1. No candidate move can KO
                        any_ko = False
                        for cand_order in self.get_valid_orders_for_slot(idx, battle):
                            if isinstance(
                                cand_order.order, Move
                            ) and cand_order.move_target in (1, 2):
                                t_mon = battle.opponent_active_pokemon[
                                    cand_order.move_target - 1
                                ]
                                if t_mon and self.check_move_will_ko(
                                    cand_order.order,
                                    battle.active_pokemon[idx],
                                    t_mon,
                                    battle,
                                    config=self.config,
                                ):
                                    any_ko = True
                                    break

                        # 2. No opponent HP < 35%
                        any_low_hp = any(
                            opp
                            and getattr(opp, "current_hp_fraction", 1.0)
                            < self.config.low_hp_target_threshold
                            for opp in battle.opponent_active_pokemon
                        )

                        if not any_ko and not any_low_hp:
                            # 3. Top candidate scores are close
                            if not self._base_scores_cache[idx]:
                                for cand_order in self.get_valid_orders_for_slot(
                                    idx, battle
                                ):
                                    self._base_scores_cache[idx][id(cand_order)] = (
                                        self.score_action(
                                            cand_order,
                                            idx,
                                            battle,
                                            with_tiebreaker=False,
                                        )
                                    )
                            cands = list(self._base_scores_cache[idx].values())
                            if len(cands) >= 2:
                                cands.sort(reverse=True)
                                if (
                                    cands[0] - cands[1]
                                    <= self.config.threat_tiebreaker_score_gap
                                ):
                                    self.battle_metrics[battle_tag][
                                        "tiebreaker_activations"
                                    ] += 1
                                    self.tiebreaker_activations_by_battle.setdefault(
                                        battle_tag, 0
                                    )
                                    self.tiebreaker_activations_by_battle[
                                        battle_tag
                                    ] += 1

                    # Let's check boosted override
                    if self.config.enable_boosted_threat_override:
                        boosts = self.get_boosts(target_mon)
                        atk_boost = boosts.get("atk", 0)
                        spa_boost = boosts.get("spa", 0)
                        spe_boost = boosts.get("spe", 0)
                        max_boost = max(atk_boost, spa_boost, spe_boost)
                        if max_boost >= self.config.boosted_override_min_stage:
                            # 1. No candidate move can KO
                            any_ko = False
                            for cand_order in self.get_valid_orders_for_slot(
                                idx, battle
                            ):
                                if isinstance(
                                    cand_order.order, Move
                                ) and cand_order.move_target in (1, 2):
                                    t_mon = battle.opponent_active_pokemon[
                                        cand_order.move_target - 1
                                    ]
                                    if t_mon and self.check_move_will_ko(
                                        cand_order.order,
                                        battle.active_pokemon[idx],
                                        t_mon,
                                        battle,
                                        config=self.config,
                                    ):
                                        any_ko = True
                                        break

                            # 2. No opponent HP < 35%
                            any_low_hp = any(
                                opp
                                and getattr(opp, "current_hp_fraction", 1.0)
                                < self.config.low_hp_target_threshold
                                for opp in battle.opponent_active_pokemon
                            )

                            is_emergency = (
                                max_boost
                                >= self.config.boosted_override_emergency_stage
                            )
                            if is_emergency or (not any_ko and not any_low_hp):
                                self.battle_metrics[battle_tag][
                                    "boosted_override_activations"
                                ] += 1
                                self.boosted_override_activations_by_battle.setdefault(
                                    battle_tag, 0
                                )
                                self.boosted_override_activations_by_battle[
                                    battle_tag
                                ] += 1

        active_1 = battle.active_pokemon[0]
        active_2 = battle.active_pokemon[1]
        opp_1 = battle.opponent_active_pokemon[0]
        opp_2 = battle.opponent_active_pokemon[1]

        if self.verbose:
            print(f"\n--- Turn {battle.turn} | Battle: {battle.battle_tag} ---")
            print(
                f"Actives: P1={active_1.species if active_1 else None} | P2={active_2.species if active_2 else None}"
            )
            print(
                f"Opponents: O1={opp_1.species if opp_1 else None} | O2={opp_2.species if opp_2 else None}"
            )
            print(
                f"Best Joint Order: {self.safe_get_joint_message(best_joint)} (Score: {best_score:.2f} = {best_score_1:.2f} + {best_score_2:.2f})"
            )

        if self.custom_logger:
            self.custom_logger.log_turn(
                battle_tag=battle.battle_tag,
                turn=battle.turn,
                our_actives=battle.active_pokemon,
                opp_actives=battle.opponent_active_pokemon,
                selected_order_message=self.safe_get_joint_message(best_joint),
                first_order=best_joint.first_order,
                second_order=best_joint.second_order,
                first_score=best_score_1,
                second_score=best_score_2,
            )

        # A completed marker is written only after the
        # canonical engine has selected a final joint
        # order. Entry alone is not sufficient proof.
        self._v2l1_invocation_status = "completed"

        # Collect decision audit data if audit_logger is present
        if self.audit_logger:
            # 1. overkill penalty triggered
            overkill_triggered = False
            first_order = best_joint.first_order
            second_order = best_joint.second_order
            if (
                first_order
                and second_order
                and isinstance(first_order.order, Move)
                and isinstance(second_order.order, Move)
            ):
                if (
                    first_order.move_target == second_order.move_target
                    and first_order.move_target in (1, 2)
                ):
                    target_opp = battle.opponent_active_pokemon[
                        first_order.move_target - 1
                    ]
                    if target_opp:
                        ko_1 = self.check_move_will_ko(
                            first_order.order,
                            battle.active_pokemon[0],
                            target_opp,
                            battle,
                            config=self.config,
                        )
                        ko_2 = self.check_move_will_ko(
                            second_order.order,
                            battle.active_pokemon[1],
                            target_opp,
                            battle,
                            config=self.config,
                        )
                        opp_hp_fraction = getattr(
                            target_opp, "current_hp_fraction", 1.0
                        )
                        if (
                            (ko_1 and ko_2)
                            or ((ko_1 or ko_2) and opp_hp_fraction < 0.15)
                            or opp_hp_fraction < 0.08
                        ):
                            allow_double = False
                            if self.config.enable_threat_scoring:
                                threat_score = self.score_opponent_threat(
                                    target_opp, battle
                                )
                                if threat_score >= 0.50:
                                    allow_double = True
                            if not allow_double:
                                overkill_triggered = True

            # 2. focus-fire bonus triggered
            focus_fire_triggered = False
            if (
                first_order
                and second_order
                and isinstance(first_order.order, Move)
                and isinstance(second_order.order, Move)
            ):
                if (
                    first_order.move_target == second_order.move_target
                    and first_order.move_target in (1, 2)
                ):
                    target_opp = battle.opponent_active_pokemon[
                        first_order.move_target - 1
                    ]
                    if target_opp:
                        opp_hp_fraction = getattr(
                            target_opp, "current_hp_fraction", 1.0
                        )
                        other_idx = 1 if first_order.move_target == 1 else 0
                        other_opp = battle.opponent_active_pokemon[other_idx]
                        other_hp_fraction = (
                            getattr(other_opp, "current_hp_fraction", 1.0)
                            if other_opp
                            else 1.0
                        )
                        if (
                            opp_hp_fraction <= other_hp_fraction
                            and opp_hp_fraction < 0.75
                        ):
                            if self.config.enable_focus_fire_synergy:
                                focus_fire_triggered = True

            # 3. ally-hit penalty triggered
            ally_hit_penalty_triggered = False
            for idx, order in enumerate([first_order, second_order]):
                if order and isinstance(order.order, Move):
                    m = order.order
                    if self.is_spread_move(m) and self.hits_ally(m):
                        ally = battle.active_pokemon[1 - idx]
                        if ally:
                            ally_safe = self.ally_safe_against_move(ally, m)
                            if (
                                not ally_safe
                                and self.config.enable_ability_hard_safety_only
                                and self.config.ability_hard_safety_ally_spread_safety
                            ):
                                ally_safe, _ = ally_ability_makes_safe(ally, m, battle)
                            if not ally_safe:
                                ally_hit_penalty_triggered = True

            # 4. spread available per slot
            spread_available = [False, False]
            for idx in (0, 1):
                if battle.available_moves[idx]:
                    for move in battle.available_moves[idx]:
                        if self.is_spread_move(move):
                            spread_available[idx] = True
                            break

            # Phase SPREAD-2: spread-defense move legal
            # per slot (Wide Guard / Quick Guard /
            # Crafty Shield). Distinct from
            # protect_like_available because those
            # 8 standard moves don't include any
            # spread-defense counter. Per-slot
            # booleans for the audit logger only;
            # no scoring change.
            wide_guard_legal = [False, False]
            quick_guard_legal = [False, False]
            crafty_shield_legal = [False, False]
            for idx in (0, 1):
                if battle.available_moves[idx]:
                    for move in battle.available_moves[idx]:
                        mid = _normalize_move_id_for_spread_defense(
                            getattr(move, "id", "")
                        )
                        if mid == "wideguard":
                            wide_guard_legal[idx] = True
                        elif mid == "quickguard":
                            quick_guard_legal[idx] = True
                        elif mid == "craftyshield":
                            crafty_shield_legal[idx] = True

            # 5. best spread score and best KO score per slot
            best_spread_score = [None, None]
            best_ko_score = [None, None]
            for idx in (0, 1):
                valid_orders_slot = (
                    valid_orders[idx] if valid_orders and valid_orders[idx] else []
                )
                for order in valid_orders_slot:
                    if isinstance(order.order, Move):
                        move = order.order
                        score = (
                            slot_0_scores.get(id(order), 0.0)
                            if idx == 0
                            else slot_1_scores.get(id(order), 0.0)
                        )
                        if self.is_spread_move(move):
                            if (
                                best_spread_score[idx] is None
                                or score > best_spread_score[idx]
                            ):
                                best_spread_score[idx] = score
                        target_mon = None
                        if order.move_target == 1:
                            target_mon = battle.opponent_active_pokemon[0]
                        elif order.move_target == 2:
                            target_mon = battle.opponent_active_pokemon[1]
                        if target_mon and self.check_move_will_ko(
                            move,
                            battle.active_pokemon[idx],
                            target_mon,
                            battle,
                            config=self.config,
                        ):
                            if best_ko_score[idx] is None or score > best_ko_score[idx]:
                                best_ko_score[idx] = score

            # 6. low HP opponent exists / targeted
            low_hp_opponent_existed = False
            for opp in battle.opponent_active_pokemon:
                if opp and getattr(opp, "current_hp_fraction", 1.0) <= 0.35:
                    low_hp_opponent_existed = True
                    break

            low_hp_opponent_targeted = False
            for order in (first_order, second_order):
                if (
                    order
                    and isinstance(order.order, Move)
                    and order.move_target in (1, 2)
                ):
                    target_opp = battle.opponent_active_pokemon[order.move_target - 1]
                    if (
                        target_opp
                        and getattr(target_opp, "current_hp_fraction", 1.0) <= 0.35
                    ):
                        low_hp_opponent_targeted = True

            # 7. expected damage, expected KO, target HP, action, action type, target species for selected slot orders
            expected_damages = [None, None]
            expected_kos = [None, None]
            target_hps = [None, None]
            slot_actions = [None, None]
            slot_action_types = [None, None]
            target_species = [None, None]
            selected_action_kind = ["pass", "pass"]
            selected_action_move_id = ["", ""]
            selected_action_target_position = [0, 0]
            selected_action_species = ["", ""]
            selected_action_only_legal = [False, False]

            for idx, order in enumerate([first_order, second_order]):
                orders_for_slot = (
                    valid_orders[idx]
                    if valid_orders and len(valid_orders) > idx
                    else []
                )
                selected_action_only_legal[idx] = (
                    len([o for o in orders_for_slot if o is not None]) <= 1
                )
                if order:
                    try:
                        slot_actions[idx] = str(order)
                    except Exception:
                        slot_actions[idx] = ""
                    if slot_actions[idx] is None:
                        slot_actions[idx] = ""
                    # Deduce action types
                    act_types = {
                        "damaging": False,
                        "status": False,
                        "protect": False,
                        "fakeout": False,
                        "spread": False,
                        "switch": False,
                    }
                    if isinstance(order.order, Move):
                        m = order.order
                        selected_action_kind[idx] = "move"
                        selected_action_move_id[idx] = getattr(m, "id", "")
                        selected_action_target_position[idx] = int(
                            getattr(order, "move_target", 0) or 0
                        )
                        cat_name = getattr(m.category, "name", "STATUS")
                        if cat_name == "STATUS":
                            act_types["status"] = True
                        else:
                            act_types["damaging"] = True
                        if m.id in (
                            "protect",
                            "detect",
                            "spikyshield",
                            "kingsshield",
                            "banefulbunker",
                            "silktrap",
                        ):
                            act_types["protect"] = True
                        if m.id == "fakeout":
                            act_types["fakeout"] = True
                        if self.is_spread_move(m):
                            act_types["spread"] = True

                        # Target info
                        target_mon = None
                        if order.move_target == 1:
                            target_mon = battle.opponent_active_pokemon[0]
                        elif order.move_target == 2:
                            target_mon = battle.opponent_active_pokemon[1]

                        if target_mon:
                            opp_max = self.estimate_opponent_max_hp(target_mon)
                            expected_damages[idx] = self.get_expected_damage(
                                m,
                                battle.active_pokemon[idx],
                                target_mon,
                                battle,
                                config=self.config,
                            ) / max(1.0, opp_max)
                            expected_kos[idx] = self.check_move_will_ko(
                                m,
                                battle.active_pokemon[idx],
                                target_mon,
                                battle,
                                config=self.config,
                            )
                            target_hps[idx] = (
                                float(target_mon.current_hp_fraction)
                                if target_mon.current_hp_fraction is not None
                                else 1.0
                            )
                            target_species[idx] = target_mon.species
                    elif isinstance(order.order, Pokemon):
                        act_types["switch"] = True
                        selected_action_kind[idx] = "switch"
                        selected_action_species[idx] = getattr(
                            order.order, "species", ""
                        )
                        # Phase 6.4.9: Track voluntary switch history (consecutive, not cumulative)
                        is_forced_switch = (
                            battle.force_switch[idx]
                            if idx < len(battle.force_switch)
                            else False
                        )
                        if (
                            not is_forced_switch
                            and battle.active_pokemon[idx] is not None
                        ):
                            key = (battle_tag, idx)
                            active_ident = self.get_pokemon_identifier(
                                battle.active_pokemon[idx]
                            )
                            self._voluntary_switch_history[key] = {
                                "last_switch_turn": current_turn,
                                "last_switch_out_identity": active_ident,
                                "last_switch_in_identity": getattr(
                                    order.order, "species", ""
                                ),
                            }
                    slot_action_types[idx] = act_types

            best_overkill_applied = False
            if best_joint.first_order and best_joint.second_order:
                best_overkill_applied = (
                    self.selected_target_will_be_koed_before_second_action(
                        best_joint.first_order,
                        best_joint.second_order,
                        battle,
                        config=self.config,
                    )
                )
            self._order_aware_overkill_penalty_applied[battle_tag] = (
                best_overkill_applied
            )

            protect_like_available = [False, False]
            switch_available = [False, False]
            only_conditional_priority = [False, False]
            stalling_field_condition = [False, False]

            # Phase SPREAD-2: which spread-defense
            # move (Wide Guard / Quick Guard /
            # Crafty Shield) did we select this turn,
            # per slot. Derived from the selected
            # action's move id (already computed as
            # ``selected_action_move_id``). Pure
            # observation; no scoring change.
            spread_defense_selected = [
                _normalize_move_id_for_spread_defense(
                    selected_action_move_id[0]
                )
                if selected_action_move_id[0]
                in _SPREAD_DEFENSE_MOVE_IDS
                else "",
                _normalize_move_id_for_spread_defense(
                    selected_action_move_id[1]
                )
                if selected_action_move_id[1]
                in _SPREAD_DEFENSE_MOVE_IDS
                else "",
            ]


            stalling = False
            if battle:
                if self.is_trick_room_active(battle):
                    stalling = True
                try:
                    from poke_env.battle.side_condition import SideCondition

                    if (
                        SideCondition.TAILWIND in battle.opponent_side_conditions
                        or SideCondition.TAILWIND in battle.side_conditions
                    ):
                        stalling = True
                except Exception:
                    pass
                if getattr(battle, "weather", None) is not None:
                    stalling = True
                if getattr(battle, "fields", None):
                    stalling = True

            for idx in (0, 1):
                active_mon = battle.active_pokemon[idx]
                if active_mon:
                    protect_like_available[idx] = self.has_legal_protect_like_action(
                        active_mon, battle, slot_index=idx
                    )
                    switch_available[idx] = len(battle.available_switches) > 0
                    stalling_field_condition[idx] = stalling

                    active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                    threat_info = self.estimate_speed_priority_threat(
                        active_mon, active_opps, battle
                    )
                    only_conditional_priority[idx] = threat_info.get(
                        "only_conditional_priority", False
                    )

            # Phase SPREAD-2: opp-pressure state. True
            # if at least one opp is alive AND has at
            # least one revealed spread move in its
            # known moveset AND is healthy enough to
            # use it. This is the trigger condition
            # that would make a Wide Guard legal-and-
            # useful. Pure observation; no scoring
            # change.
            opp_pressure_state = False
            try:
                live_opps = [
                    opp
                    for opp in battle.opponent_active_pokemon
                    if opp and not getattr(opp, "fainted", False)
                ]
                if len(live_opps) >= 1:
                    for opp in live_opps:
                        opp_hp = getattr(opp, "current_hp_fraction", 1.0)
                        if opp_hp is None or opp_hp < 0.5:
                            continue
                        opp_moves_dict = getattr(opp, "moves", {}) or {}
                        if not opp_moves_dict:
                            continue
                        for opp_move in opp_moves_dict.values():
                            if opp_move is None:
                                continue
                            try:
                                if is_opponent_spread_move(
                                    opp_move, None
                                ):
                                    opp_pressure_state = True
                                    break
                            except Exception:
                                continue
                        if opp_pressure_state:
                            break
            except Exception:
                opp_pressure_state = False

            # Phase SPREAD-4: per-slot Wide Guard /
            # Quick Guard / Crafty Shield raw scores
            # from the score_action pass. The bot
            # already computed slot_0_scores /
            # slot_1_scores above. Look up the
            # spread-defense candidate's raw score
            # so the analyzer can compute the
            # score-gap between WG and the
            # selected move. Pure observation; no
            # scoring change in the bot.
            wide_guard_score = [None, None]
            quick_guard_score = [None, None]
            crafty_shield_score = [None, None]
            # Per-slot best alternative (max non-WG /
            # non-QG / non-CS) score for the gap
            # calculation. This is the score of the
            # action the bot is likely picking instead
            # of the spread-defense move.
            best_alternative_score = [None, None]
            try:
                for idx in (0, 1):
                    slot_scores = (
                        slot_0_scores
                        if idx == 0
                        else slot_1_scores
                    )
                    if not valid_orders or idx >= len(valid_orders):
                        continue
                    if not valid_orders[idx]:
                        continue
                    best_alt = None
                    for order in valid_orders[idx]:
                        if not order or not isinstance(
                            order.order, Move
                        ):
                            continue
                        mid = (
                            _normalize_move_id_for_spread_defense(
                                getattr(order.order, "id", "")
                            )
                        )
                        score = float(
                            slot_scores.get(id(order), 0.0)
                        )
                        if mid == "wideguard":
                            wide_guard_score[idx] = score
                            continue
                        if mid == "quickguard":
                            quick_guard_score[idx] = score
                            continue
                        if mid == "craftyshield":
                            crafty_shield_score[idx] = score
                            continue
                        if best_alt is None or score > best_alt:
                            best_alt = score
                    best_alternative_score[idx] = best_alt
            except Exception:
                pass

            # Phase SPREAD-4: score gap per slot =
            # wide_guard_score - best_alternative_score.
            # Negative gap = selected alternative beat
            # WG; positive = WG was already winning.
            # The dry-run simulator uses this gap
            # distribution to pick a hypothetical
            # bonus magnitude.
            score_gap_wg_vs_selected = [None, None]
            score_gap_qg_vs_selected = [None, None]
            try:
                for idx in (0, 1):
                    wg = wide_guard_score[idx]
                    qg = quick_guard_score[idx]
                    alt = best_alternative_score[idx]
                    if wg is not None and alt is not None:
                        score_gap_wg_vs_selected[idx] = float(
                            wg - alt
                        )
                    if qg is not None and alt is not None:
                        score_gap_qg_vs_selected[idx] = float(
                            qg - alt
                        )
            except Exception:
                score_gap_wg_vs_selected = [None, None]
                score_gap_qg_vs_selected = [None, None]



            # Phase 6.4: Compute switch safety audit data for selected orders
            _t_audit_start = time.time() if _timing_enabled else 0
            forced_switch_list = [False, False]
            switch_type_safety_applied_list = [False, False]
            selected_switch_species_list = ["", ""]
            selected_switch_types_list = ["", ""]
            selected_switch_hp_fraction_list = [1.0, 1.0]
            selected_switch_raw_safety_score_list = [0.0, 0.0]
            selected_switch_relative_adjustment_list = [0.0, 0.0]
            selected_switch_worst_multiplier_list = [1.0, 1.0]
            selected_switch_double_threat_list = [False, False]
            unsafe_switch_candidate_selected_list = [False, False]
            safer_switch_candidate_available_list = [False, False]
            best_safe_switch_species_list = ["", ""]
            best_safe_switch_score_list = [0.0, 0.0]
            switch_type_safety_avoided_list = [False, False]
            neg_boost_total_list = [0, 0]
            neg_boost_lowest_list = [0, 0]
            neg_boost_offensive_list = [0, 0]
            neg_boost_defensive_list = [0, 0]
            neg_boost_speed_list = [0, 0]
            neg_boost_severe_list = [False, False]
            neg_boost_was_switch_list = [False, False]

            # Phase 6.4.3: Stat-drop switch diagnostic lists
            severe_neg_boost_active_list = [False, False]
            severe_neg_boost_categories_list = [[], []]
            severe_neg_boost_switch_available_list = [False, False]
            severe_neg_boost_switched_list = [False, False]
            severe_neg_boost_stayed_list = [False, False]
            severe_neg_boost_stayed_productive_list = [False, False]
            severe_neg_boost_stayed_unproductive_list = [False, False]
            severe_neg_boost_only_legal_no_switch_list = [False, False]
            severe_neg_boost_best_switch_candidate_list = ["", ""]
            severe_neg_boost_selected_action_list = ["", ""]
            severe_neg_boost_turn_list = [0, 0]
            severe_neg_boost_species_list = ["", ""]

            # Phase 6.4.7: Stat-drop switch scoring audit lists
            stat_drop_switch_scoring_enabled_list = [False, False]
            stat_drop_switch_pressure_active_list = [False, False]
            stat_drop_switch_pressure_categories_list = [[], []]
            stat_drop_switch_pressure_score_list = [0.0, 0.0]
            stat_drop_switch_selected_list = [False, False]
            stat_drop_switch_stayed_list = [False, False]
            stat_drop_switch_stayed_productive_list = [False, False]
            stat_drop_switch_stayed_unproductive_list = [False, False]
            stat_drop_switch_selection_changed_list = [False, False]
            stat_drop_switch_best_switch_species_list = ["", ""]
            stat_drop_switch_best_switch_score_list = [0.0, 0.0]
            stat_drop_switch_best_non_switch_score_list = [0.0, 0.0]
            stat_drop_switch_reason_list = ["", ""]
            stat_drop_switch_threshold_source_list = ["", ""]

            # Phase 6.3.6b: Known Ally Redirection audit lists
            known_ally_redirection_selected_list = [False, False]
            known_ally_redirection_reason_list = ["", ""]
            known_ally_redirection_ally_species_list = ["", ""]
            known_ally_redirection_ally_ability_list = ["", ""]
            known_ally_redirection_move_id_list = ["", ""]
            known_ally_redirection_known_before_decision_list = [False, False]
            known_ally_redirection_candidate_blocked_list = [False, False]
            known_ally_redirection_avoided_list = [False, False]
            known_ally_redirection_only_legal_list = [False, False]
            known_ally_redirection_repeat_selected_list = [False, False]
            known_ally_redirection_safe_alternative_available_list = [False, False]
            our_known_ally_redirection_error_list = [False, False]
            opponent_known_ally_redirection_error_list = [False, False]
            # Phase 6.3.6b.6: Blocked candidate metadata (for avoided cases)
            known_ally_redirection_opportunity_observed_list = [False, False]
            known_ally_redirection_blocked_candidate_move_id_list = ["", ""]
            known_ally_redirection_blocked_candidate_attacker_species_list = ["", ""]
            known_ally_redirection_blocked_candidate_target_species_list = ["", ""]
            known_ally_redirection_blocked_candidate_ally_species_list = ["", ""]
            known_ally_redirection_blocked_candidate_ally_ability_list = ["", ""]
            known_ally_redirection_blocked_candidate_reason_list = ["", ""]
            known_ally_redirection_blocked_candidate_known_before_list = [False, False]
            known_ally_redirection_blocked_candidate_score_list = [0.0, 0.0]
            known_ally_redirection_best_safe_alternative_list = ["", ""]
            known_ally_redirection_best_safe_alternative_score_list = [0.0, 0.0]
            # Phase 6.3.7: Dynamic move type audit fields
            effective_move_type_list = ["", ""]
            effective_move_type_source_list = ["", ""]
            dynamic_move_type_applied_list = [False, False]
            dynamic_move_type_form_list = ["", ""]
            declared_move_type_list = ["", ""]
            # Phase 6.3.7f: Dynamic absorb candidate audit
            dynamic_type_absorb_candidate_blocked_list = [False, False]
            dynamic_type_absorb_selected_list = [False, False]
            dynamic_type_absorb_avoided_list = [False, False]
            dynamic_type_absorb_reason_list = ["", ""]
            dynamic_type_absorb_target_species_list = ["", ""]
            dynamic_type_absorb_target_ability_list = ["", ""]
            dynamic_type_absorb_blocked_move_id_list = ["", ""]
            dynamic_type_absorb_blocked_candidate_score_list = [0.0, 0.0]
            dynamic_type_absorb_candidate_available_list = [False, False]
            dynamic_type_absorb_candidate_move_id_list = ["", ""]
            dynamic_type_absorb_candidate_declared_type_list = ["", ""]
            dynamic_type_absorb_candidate_effective_type_list = ["", ""]
            dynamic_type_absorb_candidate_form_list = ["", ""]
            # Phase COMBO-3: ally-activation combo audit
            # lists. Per-slot booleans. The bot does
            # not yet score beneficial ally activation;
            # this records whether the bot happened
            # to select such a move (e.g. Surf into
            # Water Absorb ally). False by default.
            # Observational only, no scoring change.
            selected_move_into_known_absorb_ally_list = [False, False]
            selected_move_into_known_redirect_ally_list = [False, False]
            selected_super_effective_into_weakness_policy_holder_list = [False, False]
            dynamic_type_absorb_candidate_source_list = ["", ""]
            dynamic_type_absorb_candidate_target_table_list = [[], []]

            # Phase 6.4.3a.1: Type-immune audit lists (computed, not hardcoded)
            our_type_immune_move_selected_list = [False, False]
            our_type_immune_only_legal_list = [False, False]
            our_type_immune_move_avoided_list = [False, False]
            opponent_type_immune_move_selected_list = [False, False]
            our_type_immune_attacker_list = ["", ""]
            our_type_immune_move_list = ["", ""]
            our_type_immune_target_list = ["", ""]
            our_type_immune_target_types_list = ["", ""]
            our_type_immune_reason_list = ["", ""]

            # Phase 6.4.3a.2 / 6.4.4: Forced switch diagnostic lists
            forced_switch_candidate_count_list = [0, 0]
            forced_switch_selected_index_list = [-1, -1]
            forced_switch_selected_species_list = ["", ""]
            forced_switch_best_safety_species_list = ["", ""]
            forced_switch_selected_safety_score_list = [0.0, 0.0]
            forced_switch_best_safety_score_list = [0.0, 0.0]
            forced_switch_order_fallback_used_list = [False, False]
            # Phase 6.4.4: Additional audit fields
            forced_switch_safety_enabled_list = [False, False]
            forced_switch_safety_selection_changed_list = [False, False]
            forced_switch_selected_double_threat_list = [False, False]
            forced_switch_best_avoids_double_threat_list = [False, False]
            forced_switch_selected_quad_weak_list = [False, False]
            forced_switch_best_avoids_quad_weak_list = [False, False]
            forced_switch_selected_low_hp_list = [False, False]
            forced_switch_reason_list = ["", ""]
            # Phase 6.4.4a: Per-candidate safety table (audit-only)
            forced_switch_candidate_safety_table_list = [None, None]

            for idx in (0, 1):
                chosen_order = (
                    best_joint.first_order if idx == 0 else best_joint.second_order
                )
                is_forced = (
                    battle.force_switch[idx]
                    if idx < len(battle.force_switch)
                    else False
                )
                forced_switch_list[idx] = is_forced

                # Negative boost diagnostics
                active_mon = battle.active_pokemon[idx]
                neg_boosts = _neg_boost_data_per_slot.get(idx, {})
                neg_boost_total_list[idx] = neg_boosts.get("total_negative_stages", 0)
                neg_boost_lowest_list[idx] = neg_boosts.get("lowest_stage", 0)
                neg_boost_offensive_list[idx] = neg_boosts.get(
                    "offensive_negative_stages", 0
                )
                neg_boost_defensive_list[idx] = neg_boosts.get(
                    "defensive_negative_stages", 0
                )
                neg_boost_speed_list[idx] = neg_boosts.get("speed_negative_stage", 0)
                neg_boost_severe_list[idx] = neg_boosts.get(
                    "severe_negative_boost", False
                )
                if chosen_order and hasattr(chosen_order, "order"):
                    neg_boost_was_switch_list[idx] = isinstance(
                        chosen_order.order, Pokemon
                    )

                # Complete negative-boost eligibility after best_joint is known
                if neg_boosts:
                    is_forced_nb = (
                        battle.force_switch[idx]
                        if idx < len(battle.force_switch)
                        else False
                    )
                    orders_slot_nb = (
                        valid_orders[idx]
                        if valid_orders and len(valid_orders) > idx
                        else []
                    )
                    has_legal_switches_nb = any(
                        o and isinstance(o.order, Pokemon) for o in orders_slot_nb
                    )
                    has_legal_moves_nb = any(
                        o and isinstance(o.order, Move) for o in orders_slot_nb
                    )

                    # Determine selected action kind
                    if chosen_order:
                        if isinstance(chosen_order.order, Pokemon):
                            neg_boosts["negative_boost_selected_action_kind"] = "switch"
                        elif isinstance(chosen_order.order, Move):
                            neg_boosts["negative_boost_selected_action_kind"] = "move"
                        elif isinstance(chosen_order, (type(None),)) or not hasattr(
                            chosen_order, "order"
                        ):
                            neg_boosts["negative_boost_selected_action_kind"] = "pass"
                        else:
                            neg_boosts["negative_boost_selected_action_kind"] = "other"
                    else:
                        neg_boosts["negative_boost_selected_action_kind"] = "none"

                    # Count legal switches
                    neg_boosts["negative_boost_legal_switch_count"] = sum(
                        1 for o in orders_slot_nb if o and isinstance(o.order, Pokemon)
                    )

                    # Find best switch and best move scores
                    best_sw_score = float("-inf")
                    best_sw_species = ""
                    best_mv_score = float("-inf")
                    for o in orders_slot_nb:
                        if not o:
                            continue
                        sid_o = id(o)
                        sc = (
                            slot_0_scores.get(sid_o, 0.0)
                            if idx == 0
                            else slot_1_scores.get(sid_o, 0.0)
                        )
                        if isinstance(o.order, Pokemon):
                            if sc > best_sw_score:
                                best_sw_score = sc
                                best_sw_species = getattr(o.order, "species", "")
                        elif isinstance(o.order, Move):
                            if sc > best_mv_score:
                                best_mv_score = sc
                    neg_boosts["negative_boost_best_switch_species"] = best_sw_species
                    neg_boosts["negative_boost_best_switch_score"] = (
                        best_sw_score if best_sw_score > float("-inf") else 0.0
                    )
                    neg_boosts["negative_boost_best_move_score"] = (
                        best_mv_score if best_mv_score > float("-inf") else 0.0
                    )
                    neg_boosts["negative_boost_switch_score_gap"] = (
                        best_sw_score if best_sw_score > float("-inf") else 0.0
                    ) - (best_mv_score if best_mv_score > float("-inf") else 0.0)

                    # Eligibility check
                    is_pass_default = neg_boosts[
                        "negative_boost_selected_action_kind"
                    ] in ("pass", "none")
                    # Deduplicate by stable decision event identifier
                    dedup_key = (
                        battle_tag,
                        current_turn,
                        idx,
                        getattr(active_mon, "species", ""),
                        neg_boosts["negative_boost_selected_action_kind"],
                        is_forced_nb,
                    )
                    is_duplicate = dedup_key in getattr(
                        self, "_neg_boost_dedup_keys", set()
                    )
                    if not hasattr(self, "_neg_boost_dedup_keys"):
                        self._neg_boost_dedup_keys = set()

                    eligible = (
                        active_mon is not None
                        and not getattr(active_mon, "fainted", False)
                        and not is_forced_nb
                        and has_legal_switches_nb
                        and has_legal_moves_nb
                        and not is_pass_default
                        and not is_duplicate
                    )
                    neg_boosts["negative_boost_decision_eligible"] = eligible
                    if eligible:
                        self._neg_boost_dedup_keys.add(dedup_key)

                # Phase 6.4.3: Stat-drop switch diagnostics (config-driven thresholds)
                if (
                    getattr(self.config, "enable_stat_drop_switch_diagnostics", False)
                    and active_mon
                ):
                    boosts = getattr(active_mon, "boosts", None)
                    orders_slot_sd = (
                        valid_orders[idx]
                        if valid_orders and len(valid_orders) > idx
                        else []
                    )
                    sd_class = classify_stat_drop_severity(
                        boosts, self.config, orders_slot_sd
                    )

                    severe_neg_boost_active_list[idx] = sd_class["severe"]
                    severe_neg_boost_categories_list[idx] = sd_class["categories"]
                    severe_neg_boost_turn_list[idx] = (
                        current_turn if sd_class["severe"] else 0
                    )
                    severe_neg_boost_species_list[idx] = (
                        getattr(active_mon, "species", "") if sd_class["severe"] else ""
                    )

                    if sd_class["severe"]:
                        is_forced_sd = (
                            battle.force_switch[idx]
                            if idx < len(battle.force_switch)
                            else False
                        )
                        has_switches_sd = any(
                            o and isinstance(o.order, Pokemon) for o in orders_slot_sd
                        )
                        severe_neg_boost_switch_available_list[idx] = (
                            has_switches_sd and not is_forced_sd
                        )

                        # Determine if switched or stayed
                        is_switch = chosen_order and isinstance(
                            chosen_order.order, Pokemon
                        )
                        severe_neg_boost_switched_list[idx] = is_switch
                        severe_neg_boost_stayed_list[idx] = (
                            not is_switch and not is_forced_sd
                        )

                        # Best switch candidate
                        best_sw_species = ""
                        best_sw_score = float("-inf")
                        slot_scores_sd = slot_0_scores if idx == 0 else slot_1_scores
                        for o in orders_slot_sd:
                            if o and isinstance(o.order, Pokemon):
                                sc = slot_scores_sd.get(id(o), 0.0)
                                if sc > best_sw_score:
                                    best_sw_score = sc
                                    best_sw_species = getattr(o.order, "species", "")
                        severe_neg_boost_best_switch_candidate_list[idx] = (
                            best_sw_species
                        )

                        # Selected action
                        if is_switch:
                            severe_neg_boost_selected_action_list[idx] = (
                                f"switch:{getattr(chosen_order.order, 'species', '')}"
                            )
                        elif chosen_order and isinstance(chosen_order.order, Move):
                            severe_neg_boost_selected_action_list[idx] = (
                                f"move:{getattr(chosen_order.order, 'id', '')}"
                            )
                        else:
                            severe_neg_boost_selected_action_list[idx] = "pass"

                        # Only legal no-switch
                        if not is_forced_sd and not has_switches_sd:
                            severe_neg_boost_only_legal_no_switch_list[idx] = True

                        # Productive stayed-in check
                        if severe_neg_boost_stayed_list[idx]:
                            productive = False
                            # Check KO
                            if chosen_order and isinstance(chosen_order.order, Move):
                                target_pos = getattr(chosen_order, "move_target", 0)
                                if target_pos in (1, 2):
                                    target_opp = battle.opponent_active_pokemon[
                                        target_pos - 1
                                    ]
                                    if target_opp and self.check_move_will_ko(
                                        chosen_order.order,
                                        active_mon,
                                        target_opp,
                                        battle,
                                        config=self.config,
                                    ):
                                        productive = True
                            # Check meaningful damage (configurable threshold)
                            if (
                                not productive
                                and chosen_order
                                and isinstance(chosen_order.order, Move)
                            ):
                                target_pos = getattr(chosen_order, "move_target", 0)
                                if target_pos in (1, 2):
                                    target_opp = battle.opponent_active_pokemon[
                                        target_pos - 1
                                    ]
                                    if target_opp:
                                        try:
                                            dmg = self.get_expected_damage(
                                                chosen_order.order,
                                                active_mon,
                                                target_opp,
                                                battle,
                                                config=self.config,
                                            )
                                            opp_max = self.estimate_opponent_max_hp(
                                                target_opp
                                            )
                                            frac = (
                                                getattr(
                                                    config,
                                                    "stat_drop_meaningful_damage_fraction",
                                                    0.25,
                                                )
                                                if config
                                                else 0.25
                                            )
                                            if opp_max > 0 and dmg / opp_max >= frac:
                                                productive = True
                                        except Exception:
                                            pass
                            # Check Protect (only if existing protect safety says it's safe)
                            if (
                                not productive
                                and chosen_order
                                and isinstance(chosen_order.order, Move)
                            ):
                                move_id = getattr(chosen_order.order, "id", "")
                                if move_id in (
                                    "protect",
                                    "detect",
                                    "spikyshield",
                                    "kingsshield",
                                    "banefulbunker",
                                    "silktrap",
                                ):
                                    productive = (
                                        True  # Protect is generally safe if selected
                                    )

                            severe_neg_boost_stayed_productive_list[idx] = productive
                            severe_neg_boost_stayed_unproductive_list[
                                idx
                            ] = not productive

                # Phase 6.4.7: Stat-drop switch scoring audit population
                sdata = _stat_drop_scoring_data.get(idx, {})
                stat_drop_switch_scoring_enabled_list[idx] = sdata.get("enabled", False)
                stat_drop_switch_pressure_active_list[idx] = sdata.get(
                    "pressure_active", False
                )
                stat_drop_switch_pressure_categories_list[idx] = list(
                    sdata.get("categories", [])
                )
                stat_drop_switch_pressure_score_list[idx] = sdata.get(
                    "stay_penalty", 0.0
                )
                stat_drop_switch_best_switch_species_list[idx] = sdata.get(
                    "best_switch_species", ""
                )
                stat_drop_switch_best_switch_score_list[idx] = sdata.get(
                    "best_switch_score", 0.0
                )
                stat_drop_switch_best_non_switch_score_list[idx] = sdata.get(
                    "best_non_switch_score", 0.0
                )
                stat_drop_switch_reason_list[idx] = sdata.get("reason", "")
                stat_drop_switch_threshold_source_list[idx] = sdata.get(
                    "threshold_source", ""
                )
                if sdata.get("pressure_active", False) and chosen_order:
                    order_obj = getattr(chosen_order, "order", None)
                    if order_obj is not None and getattr(order_obj, "species", None):
                        stat_drop_switch_selected_list[idx] = True
                    else:
                        stat_drop_switch_stayed_list[idx] = True
                        if sdata.get("productive_action_available", False):
                            stat_drop_switch_stayed_productive_list[idx] = True
                        else:
                            stat_drop_switch_stayed_unproductive_list[idx] = True

                # Phase 6.4.7c: Populate selection_changed from counterfactual
                if (
                    sdata.get("enabled", False)
                    and _stat_drop_counterfactual_joint is not None
                ):
                    actual_key = (
                        _stat_drop_actual_actions[idx]
                        if idx < len(_stat_drop_actual_actions)
                        else ("", "", 0)
                    )
                    cf_key = (
                        _stat_drop_counterfactual_actions[idx]
                        if idx < len(_stat_drop_counterfactual_actions)
                        else ("", "", 0)
                    )
                    if actual_key != cf_key:
                        stat_drop_switch_selection_changed_list[idx] = True

                # Phase 6.3.6b: Known Ally Redirection audit population
                known_ally_redirection_selected_list[idx] = (
                    self._known_ally_redirect_selected.get(battle_tag, {}).get(
                        idx, False
                    )
                )
                known_ally_redirection_reason_list[idx] = (
                    self._known_ally_redirect_reason.get(battle_tag, {}).get(idx, "")
                )
                known_ally_redirection_ally_species_list[idx] = (
                    self._known_ally_redirect_ally_species.get(battle_tag, {}).get(
                        idx, ""
                    )
                )
                known_ally_redirection_ally_ability_list[idx] = (
                    self._known_ally_redirect_ally_ability.get(battle_tag, {}).get(
                        idx, ""
                    )
                )
                known_ally_redirection_move_id_list[idx] = (
                    self._known_ally_redirect_move_id.get(battle_tag, {}).get(idx, "")
                )
                ally_before_ability = (
                    _known_ally_ability_before[1 - idx]
                    if (1 - idx) < len(_known_ally_ability_before)
                    else ""
                )
                ally_after_ability = self._known_ally_redirect_ally_ability.get(
                    battle_tag, {}
                ).get(idx, "")
                known_ally_redirection_known_before_decision_list[idx] = bool(
                    ally_before_ability and ally_before_ability == ally_after_ability
                )

                # Phase 6.3.7: Dynamic move type audit population
                if chosen_order and isinstance(chosen_order.order, Move):
                    ch_move = chosen_order.order
                    ch_active = (
                        battle.active_pokemon[idx]
                        if idx < len(battle.active_pokemon)
                        else None
                    )
                    resolved = resolve_effective_move_type(ch_move, ch_active, battle)
                    declared_move_type_list[idx] = resolved["declared_type"]
                    effective_move_type_list[idx] = resolved["effective_type"]
                    effective_move_type_source_list[idx] = resolved["source"]
                    dynamic_move_type_applied_list[idx] = resolved["dynamic_applied"]
                    dynamic_move_type_form_list[idx] = resolved["observed_form"]

                # Phase 6.3.7j: Dynamic absorb candidate classification
                orders_slot_abs = (
                    valid_orders[idx]
                    if valid_orders and len(valid_orders) > idx
                    else []
                )
                slot_scores_abs = slot_0_scores if idx == 0 else slot_1_scores
                active_abs = (
                    battle.active_pokemon[idx]
                    if idx < len(battle.active_pokemon)
                    else None
                )
                absorb_result = classify_dynamic_type_absorb_candidates(
                    orders_slot_abs,
                    chosen_order,
                    active_abs,
                    battle.opponent_active_pokemon,
                    battle,
                    self.config,
                    slot_scores_abs,
                )
                dynamic_type_absorb_candidate_blocked_list[idx] = absorb_result[
                    "candidate_blocked"
                ]
                dynamic_type_absorb_selected_list[idx] = absorb_result["selected"]
                dynamic_type_absorb_avoided_list[idx] = absorb_result["avoided"]
                dynamic_type_absorb_reason_list[idx] = absorb_result["reason"]
                dynamic_type_absorb_target_species_list[idx] = absorb_result[
                    "target_species"
                ]
                dynamic_type_absorb_target_ability_list[idx] = absorb_result[
                    "target_ability"
                ]
                dynamic_type_absorb_blocked_move_id_list[idx] = absorb_result[
                    "blocked_order_id"
                ]
                dynamic_type_absorb_blocked_candidate_score_list[idx] = absorb_result[
                    "blocked_candidate_score"
                ]
                dynamic_type_absorb_candidate_available_list[idx] = absorb_result[
                    "dynamic_candidate_available"
                ]
                dynamic_type_absorb_candidate_move_id_list[idx] = absorb_result[
                    "dynamic_candidate_move_id"
                ]
                dynamic_type_absorb_candidate_declared_type_list[idx] = absorb_result[
                    "dynamic_candidate_declared_type"
                ]
                dynamic_type_absorb_candidate_effective_type_list[idx] = absorb_result[
                    "dynamic_candidate_effective_type"
                ]
                dynamic_type_absorb_candidate_form_list[idx] = absorb_result[
                    "dynamic_candidate_form"
                ]
                dynamic_type_absorb_candidate_source_list[idx] = absorb_result[
                    "dynamic_candidate_source"
                ]
                dynamic_type_absorb_candidate_target_table_list[idx] = absorb_result[
                    "dynamic_candidate_target_table"
                ]

                # Phase COMBO-3: ally-activation combo
                # audit. Compute three per-slot booleans
                # from the selected action, the
                # active mon, the ally, and known
                # ally abilities / items. This is
                # observational only — no scoring
                # change. The fields help future
                # audits prove whether the bot ever
                # selected a beneficial ally-activation
                # move.
                try:
                    if (
                        chosen_order is not None
                        and isinstance(chosen_order.order, Move)
                    ):
                        sel_move = chosen_order.order
                        sel_move_id = (
                            getattr(sel_move, "id", "") or ""
                        ).lower()
                        sel_target = int(
                            getattr(chosen_order, "move_target", 0) or 0
                        )
                        # Resolve the selected move's
                        # effective type.
                        sel_eff_type = ""
                        try:
                            from doubles_engine.types import (
                                get_effective_move_type,
                            )
                            sel_eff_type = (
                                get_effective_move_type(
                                    sel_move, active_mon
                                ) or ""
                            ).upper()
                        except Exception:
                            sel_eff_type = ""
                        # Ally: the other slot (1-idx).
                        ally_idx = 1 - idx
                        ally_mon = (
                            battle.active_pokemon[ally_idx]
                            if (
                                len(battle.active_pokemon)
                                > ally_idx
                            )
                            else None
                        )
                        ally_ability = ""
                        if ally_mon is not None:
                            try:
                                ally_ability = (
                                    get_known_ability(
                                        ally_mon, battle
                                    ) or ""
                                )
                            except Exception:
                                ally_ability = ""
                        ally_ability_norm = "".join(
                            c
                            for c in ally_ability.lower()
                            if c.isalnum()
                        )
                        # Field 1: selected damaging move
                        # into known absorb ally.
                        # Conditions:
                        # - target is the ally (-1 or -2)
                        # OR the move is a spread move
                        # that would hit the ally.
                        # - ally ability is in the known
                        # absorb set and matches the
                        # selected move's type.
                        hits_ally = (
                            sel_target in (-1, -2)
                        ) or self.is_spread_move(sel_move)
                        if hits_ally and sel_eff_type:
                            # Map move type to expected
                            # absorb ability.
                            type_to_ability = {
                                "WATER": "waterabsorb",
                                "ELECTRIC": "voltabsorb",
                                "FIRE": "flashfire",
                                "GRASS": "sapsipper",
                            }
                            expected = type_to_ability.get(
                                sel_eff_type, ""
                            )
                            if (
                                expected
                                and ally_ability_norm
                                in (
                                    expected,
                                    "stormdrain",
                                    "lightningrod",
                                    "dryskin",
                                    "motordrive",
                                    "wellbakedbody",
                                )
                            ):
                                selected_move_into_known_absorb_ally_list[
                                    idx
                                ] = True
                        # Field 2: selected single-target
                        # move would be redirected by
                        # known ally Storm Drain or
                        # Lightning Rod.
                        if (
                            sel_target in (1, 2)
                            and ally_ability_norm
                            in ("stormdrain", "lightningrod")
                        ):
                            # Only count as "would be
                            # redirected into absorb ally"
                            # if the move is of the
                            # matching type and the
                            # original target is not
                            # already the redirector.
                            if sel_eff_type in (
                                "WATER", "ELECTRIC"
                            ):
                                selected_move_into_known_redirect_ally_list[
                                    idx
                                ] = True
                        # Field 3: selected move is
                        # super-effective into ally with
                        # known Weakness Policy.
                        # Weakness Policy item is
                        # observable in the bot's known
                        # data; if not observable, the
                        # field stays False.
                        if hits_ally and sel_eff_type:
                            try:
                                type_mult = (
                                    self.get_type_effectiveness(
                                        sel_move, ally_mon,
                                        active_mon
                                    )
                                )
                            except Exception:
                                type_mult = 1.0
                            ally_item_norm = ""
                            try:
                                ally_item = getattr(
                                    ally_mon, "item", None
                                )
                                if ally_item is not None:
                                    ally_item_norm = (
                                        "".join(
                                            c
                                            for c in str(
                                                ally_item
                                            ).lower()
                                            if c.isalnum()
                                        )
                                    )
                            except Exception:
                                ally_item_norm = ""
                            if (
                                type_mult is not None
                                and type_mult > 1.0
                                and ally_item_norm
                                == "weaknesspolicy"
                            ):
                                selected_super_effective_into_weakness_policy_holder_list[
                                    idx
                                ] = True
                except Exception:
                    # Observational only. On any
                    # error, leave the field False.
                    pass

                is_selected_ar = known_ally_redirection_selected_list[idx]
                is_known_before = known_ally_redirection_known_before_decision_list[idx]
                candidate_blocked = (
                    _ally_redirect_blocked.get(id(chosen_order), False)
                    if chosen_order
                    else False
                )
                known_ally_redirection_candidate_blocked_list[idx] = candidate_blocked

                # Safe alternative: any legal joint has a different non-blocked action for this slot
                safe_alt_exists = False
                if candidate_blocked or is_selected_ar:
                    for alt_best_joint, _, _, _ in scored_joint_orders[1:]:
                        alt_order = (
                            alt_best_joint.first_order
                            if idx == 0
                            else alt_best_joint.second_order
                        )
                        if alt_order and id(alt_order) != (
                            id(chosen_order) if chosen_order else None
                        ):
                            if not _ally_redirect_blocked.get(id(alt_order), False):
                                safe_alt_exists = True
                                break

                blocked_candidate_exists = (
                    any(
                        _ally_redirect_blocked.get(id(o), False)
                        for o in valid_orders[idx]
                    )
                    if valid_orders and len(valid_orders) > idx
                    else False
                )

                # Phase 6.3.6b pure helper: audit classification
                audit = classify_known_ally_redirection_audit(
                    is_selected_blocked=(candidate_blocked or is_selected_ar),
                    candidate_blocked_exists=blocked_candidate_exists,
                    safe_alternative_exists=safe_alt_exists,
                )
                known_ally_redirection_only_legal_list[idx] = audit["only_legal"]
                known_ally_redirection_safe_alternative_available_list[idx] = (
                    safe_alt_exists
                )
                known_ally_redirection_avoided_list[idx] = audit["avoided"]

                # Phase 6.3.6b pure helper: error ownership
                our_err, opp_err = classify_known_ally_redirection_error(
                    selected=is_selected_ar,
                    known_before_decision=is_known_before,
                    is_our_action=True,
                )
                our_known_ally_redirection_error_list[idx] = our_err
                opponent_known_ally_redirection_error_list[idx] = opp_err

                # Phase 6.3.6b pure helper: repeat detection
                if is_selected_ar:
                    key = (
                        self.get_pokemon_identifier(battle.active_pokemon[idx])
                        if battle.active_pokemon[idx]
                        else "",
                        known_ally_redirection_move_id_list[idx],
                        known_ally_redirection_ally_species_list[idx],
                        known_ally_redirection_ally_ability_list[idx],
                    )
                    s = getattr(self, "_known_ally_redirect_streak", {})
                    repeat_result = update_known_ally_redirection_repeat_state(
                        key, battle_tag, current_turn, s
                    )
                    self._known_ally_redirect_streak = repeat_result["streak_state"]
                    known_ally_redirection_repeat_selected_list[idx] = repeat_result[
                        "repeat_detected"
                    ]

                # Phase 6.3.6b.6: Populate blocked-candidate metadata from precomputation
                ar_meta = _ally_redirect_blocked_meta
                blocked_for_slot = {}
                best_safe_alt_id = None
                best_safe_alt_score = float("-inf")
                if ar_meta:
                    for oid, meta in ar_meta.items():
                        blocked_for_slot[oid] = meta
                    if safe_alt_exists:
                        for alt_best_joint, jscore, _, _ in scored_joint_orders[1:]:
                            alt_order = (
                                alt_best_joint.first_order
                                if idx == 0
                                else alt_best_joint.second_order
                            )
                            if alt_order and not ar_meta.get(id(alt_order)):
                                if jscore > best_safe_alt_score:
                                    best_safe_alt_score = jscore
                                    best_safe_alt_id = id(alt_order)
                # Pick first blocked candidate for this slot (there's usually at most one)
                first_blocked = None
                for oid, meta in (ar_meta or {}).items():
                    first_blocked = meta
                    break
                has_opportunity = len(ar_meta or {}) > 0
                known_ally_redirection_opportunity_observed_list[idx] = has_opportunity
                if has_opportunity and first_blocked:
                    known_ally_redirection_blocked_candidate_move_id_list[idx] = (
                        first_blocked.get("move_id", "")
                    )
                    known_ally_redirection_blocked_candidate_attacker_species_list[
                        idx
                    ] = first_blocked.get("attacker_species", "")
                    known_ally_redirection_blocked_candidate_target_species_list[
                        idx
                    ] = first_blocked.get("target_species", "")
                    known_ally_redirection_blocked_candidate_ally_species_list[idx] = (
                        first_blocked.get("ally_species", "")
                    )
                    known_ally_redirection_blocked_candidate_ally_ability_list[idx] = (
                        first_blocked.get("ally_ability", "")
                    )
                    known_ally_redirection_blocked_candidate_reason_list[idx] = (
                        first_blocked.get("reason", "")
                    )
                    known_ally_redirection_blocked_candidate_known_before_list[idx] = (
                        first_blocked.get("known_before_decision", False)
                    )
                slot_scores_for_pop = slot_0_scores if idx == 0 else slot_1_scores
                for oid in ar_meta or {}:
                    known_ally_redirection_blocked_candidate_score_list[idx] = (
                        slot_scores_for_pop.get(oid, 0.0)
                    )
                    break  # first blocked only
                if best_safe_alt_id is not None:
                    know_alt_order = None
                    for alt_best_joint, _, _, _ in scored_joint_orders[1:]:
                        alt_order = (
                            alt_best_joint.first_order
                            if idx == 0
                            else alt_best_joint.second_order
                        )
                        if alt_order and id(alt_order) == best_safe_alt_id:
                            known_ally_redirection_best_safe_alternative_list[idx] = (
                                getattr(getattr(alt_order, "order", None), "id", "")
                                if alt_order and hasattr(alt_order, "order")
                                else ""
                            )
                            break
                    known_ally_redirection_best_safe_alternative_score_list[idx] = (
                        best_safe_alt_score
                        if best_safe_alt_score > float("-inf")
                        else 0.0
                    )

                # Phase 6.4.3a.1: Type-immune audit computation
                if chosen_order and isinstance(chosen_order.order, Move):
                    chosen_move = chosen_order.order
                    chosen_active = (
                        battle.active_pokemon[idx]
                        if idx < len(battle.active_pokemon)
                        else None
                    )
                    chosen_target = None
                    if hasattr(chosen_order, "move_target"):
                        t_pos = chosen_order.move_target
                        if t_pos in (1, 2) and t_pos - 1 < len(
                            battle.opponent_active_pokemon
                        ):
                            chosen_target = battle.opponent_active_pokemon[t_pos - 1]

                    if (
                        chosen_active
                        and chosen_target
                        and getattr(chosen_move, "base_power", 0) > 0
                    ):
                        immune, reason = is_type_immune(
                            chosen_move, chosen_active, chosen_target, battle
                        )
                        if immune:
                            our_type_immune_move_selected_list[idx] = True
                            our_type_immune_attacker_list[idx] = getattr(
                                chosen_active, "species", ""
                            )
                            our_type_immune_move_list[idx] = getattr(
                                chosen_move, "id", ""
                            )
                            our_type_immune_target_list[idx] = getattr(
                                chosen_target, "species", ""
                            )
                            t_types_str = ""
                            if hasattr(chosen_target, "types") and chosen_target.types:
                                t_types_str = "+".join(
                                    t.name.title() if hasattr(t, "name") else str(t)
                                    for t in chosen_target.types
                                    if t
                                )
                            our_type_immune_target_types_list[idx] = t_types_str
                            our_type_immune_reason_list[idx] = reason

                            # Check if this was the only legal damaging move
                            orders_slot_imm = (
                                valid_orders[idx]
                                if valid_orders and len(valid_orders) > idx
                                else []
                            )
                            safe_alternatives = 0
                            for alt_o in orders_slot_imm:
                                if (
                                    alt_o
                                    and isinstance(alt_o.order, Move)
                                    and getattr(alt_o.order, "base_power", 0) > 0
                                ):
                                    alt_target = None
                                    if hasattr(
                                        alt_o, "move_target"
                                    ) and alt_o.move_target in (1, 2):
                                        alt_target = battle.opponent_active_pokemon[
                                            alt_o.move_target - 1
                                        ]
                                    if alt_target:
                                        alt_imm, _ = is_type_immune(
                                            alt_o.order,
                                            chosen_active,
                                            alt_target,
                                            battle,
                                        )
                                        if not alt_imm:
                                            alt_blocked, _ = ability_hard_blocks_move(
                                                alt_o.order,
                                                chosen_active,
                                                alt_target,
                                                battle,
                                                config=self.config,
                                            )
                                            if not alt_blocked:
                                                safe_alternatives += 1
                            if safe_alternatives == 0:
                                our_type_immune_only_legal_list[idx] = True
                            else:
                                our_type_immune_move_avoided_list[idx] = True

                # Phase 6.4.3a.2 / 6.4.4: Forced switch diagnostic computation
                if is_forced:
                    forced_switch_safety_enabled_list[idx] = bool(
                        getattr(
                            self.config,
                            "enable_forced_switch_replacement_safety",
                            False,
                        )
                    )
                    orders_slot_fs = (
                        valid_orders[idx]
                        if valid_orders and len(valid_orders) > idx
                        else []
                    )
                    switch_candidates = [
                        o for o in orders_slot_fs if o and isinstance(o.order, Pokemon)
                    ]
                    forced_switch_candidate_count_list[idx] = len(switch_candidates)

                    # Find the selected switch index and species
                    selected_safety_result = None
                    best_safety_result = None
                    if chosen_order and isinstance(chosen_order.order, Pokemon):
                        forced_switch_selected_species_list[idx] = getattr(
                            chosen_order.order, "species", ""
                        )
                        for ci, cand in enumerate(switch_candidates):
                            if id(cand) == id(chosen_order):
                                forced_switch_selected_index_list[idx] = ci
                                break

                    # Evaluate safety scores for all candidates using the SAME function
                    # as the actual scoring path (evaluate_forced_switch_replacement_safety).
                    # Previous code incorrectly used evaluate_switch_candidate_type_safety
                    # which has different scoring constants and thresholds.
                    best_safety_score = float("-inf")
                    best_safety_species = ""
                    selected_safety_score = 0.0
                    active_opps_fs = [o for o in battle.opponent_active_pokemon if o]
                    candidate_safety_table = []
                    for cand in switch_candidates:
                        cand_species = getattr(cand.order, "species", "")
                        safety = evaluate_forced_switch_replacement_safety(
                            cand.order,
                            active_opps_fs,
                            battle=battle,
                            config=self.config,
                        )
                        s_score = safety.get("score", 0.0)
                        # Build per-candidate audit entry
                        candidate_safety_table.append(
                            {
                                "species": cand_species,
                                "score": round(s_score, 2),
                                "max_threat_multiplier": safety.get(
                                    "max_threat_multiplier", 1.0
                                ),
                                "opponent_threat_count": safety.get(
                                    "opponent_threat_count", 0
                                ),
                                "quad_weak_count": safety.get("quad_weak_count", 0),
                                "resistance_count": safety.get("resistance_count", 0),
                                "immunity_count": safety.get("immunity_count", 0),
                                "low_hp_penalty_applied": safety.get(
                                    "low_hp_penalty_applied", False
                                ),
                                "reasons": safety.get("reasons", []),
                            }
                        )
                        if s_score > best_safety_score:
                            best_safety_score = s_score
                            best_safety_species = cand_species
                            best_safety_result = safety
                        if chosen_order and id(cand) == id(chosen_order):
                            selected_safety_score = s_score
                            selected_safety_result = safety

                    forced_switch_best_safety_species_list[idx] = best_safety_species
                    forced_switch_selected_safety_score_list[idx] = (
                        selected_safety_score
                    )
                    forced_switch_best_safety_score_list[idx] = (
                        best_safety_score if best_safety_score > float("-inf") else 0.0
                    )
                    forced_switch_candidate_safety_table_list[idx] = (
                        candidate_safety_table if candidate_safety_table else None
                    )

                    # Detect list-order fallback
                    if (
                        forced_switch_selected_index_list[idx] == 0
                        and len(switch_candidates) > 1
                    ):
                        forced_switch_order_fallback_used_list[idx] = True

                    # Phase 6.4.4: Additional audit fields
                    if selected_safety_result:
                        forced_switch_selected_double_threat_list[idx] = bool(
                            "double_threat" in selected_safety_result.get("reasons", [])
                        )
                        forced_switch_selected_quad_weak_list[idx] = bool(
                            "quad_weak" in selected_safety_result.get("reasons", [])
                        )
                        forced_switch_selected_low_hp_list[idx] = (
                            selected_safety_result.get("low_hp_penalty_applied", False)
                        )
                    if best_safety_result:
                        forced_switch_best_avoids_double_threat_list[idx] = (
                            "double_threat" not in best_safety_result.get("reasons", [])
                        )
                        forced_switch_best_avoids_quad_weak_list[idx] = (
                            "quad_weak" not in best_safety_result.get("reasons", [])
                        )

                    # Selection changed: best safety species differs from selected
                    if (
                        best_safety_species
                        and forced_switch_selected_species_list[idx]
                        and best_safety_species
                        != forced_switch_selected_species_list[idx]
                    ):
                        forced_switch_safety_selection_changed_list[idx] = True

                    # Reason string
                    if selected_safety_result:
                        forced_switch_reason_list[idx] = ",".join(
                            selected_safety_result.get("reasons", [])
                        )

                # Switch safety audit data (always collect for diagnostics)
                if chosen_order and isinstance(chosen_order.order, Pokemon):
                    switch_candidate = chosen_order.order
                    cand_safety = _switch_safety_data_per_slot.get(idx, {})
                    sid = id(chosen_order)
                    safety = cand_safety.get(sid, None)

                    if safety:
                        selected_switch_species_list[idx] = getattr(
                            switch_candidate, "species", ""
                        )
                        types = []
                        t1 = getattr(switch_candidate, "type_1", None)
                        t2 = getattr(switch_candidate, "type_2", None)
                        if t1:
                            types.append(
                                t1.name.title() if hasattr(t1, "name") else str(t1)
                            )
                        if t2:
                            types.append(
                                t2.name.title() if hasattr(t2, "name") else str(t2)
                            )
                        selected_switch_types_list[idx] = "+".join(types)
                        selected_switch_hp_fraction_list[idx] = safety.get(
                            "candidate_hp_fraction", 1.0
                        )
                        selected_switch_raw_safety_score_list[idx] = safety.get(
                            "raw_safety_score", 0.0
                        )
                        selected_switch_worst_multiplier_list[idx] = safety.get(
                            "worst_multiplier", 1.0
                        )
                        selected_switch_double_threat_list[idx] = safety.get(
                            "double_threat", False
                        )

                        best_raw = _switch_best_raw_scores.get(idx, 0.0)
                        relative_adj = min(
                            0.0, safety.get("raw_safety_score", 0.0) - best_raw
                        )
                        selected_switch_relative_adjustment_list[idx] = relative_adj

                        is_unsafe = (
                            safety.get("double_threat", False)
                            or safety.get("quad_weak_threat_count", 0) > 0
                        )
                        if is_unsafe:
                            unsafe_switch_candidate_selected_list[idx] = True

                            # Joint-legality: find best safe switch that doesn't conflict
                            # with the other slot's selected switch
                            other_idx = 1 - idx
                            other_chosen = (
                                best_joint.first_order
                                if other_idx == 0
                                else best_joint.second_order
                            )
                            other_species = None
                            if other_chosen and isinstance(other_chosen.order, Pokemon):
                                other_species = getattr(
                                    other_chosen.order, "species", None
                                )

                            best_safe_order = None
                            best_safe_score = float("-inf")
                            for sw_order in cand_safety.keys():
                                sw_safety = cand_safety[sw_order]
                                sw_unsafe = (
                                    sw_safety.get("double_threat", False)
                                    or sw_safety.get("quad_weak_threat_count", 0) > 0
                                )
                                if sw_unsafe:
                                    continue
                                # Find the actual order object to check species
                                for so in (
                                    switch_orders
                                    if idx == 0
                                    else (
                                        valid_orders[other_idx]
                                        if valid_orders
                                        and len(valid_orders) > other_idx
                                        else []
                                    )
                                ):
                                    if id(so) == sw_order:
                                        sw_species = getattr(so.order, "species", None)
                                        if (
                                            other_species
                                            and sw_species == other_species
                                        ):
                                            break  # conflicts with other slot
                                        sw_score = (
                                            slot_0_scores.get(sw_order, 0.0)
                                            if idx == 0
                                            else slot_1_scores.get(sw_order, 0.0)
                                        )
                                        if sw_score > best_safe_score:
                                            best_safe_score = sw_score
                                            best_safe_order = so
                                        break

                            if best_safe_order:
                                safer_switch_candidate_available_list[idx] = True
                                best_safe_switch_species_list[idx] = getattr(
                                    best_safe_order.order, "species", ""
                                )
                                best_safe_switch_score_list[idx] = best_safe_score
                            else:
                                safer_switch_candidate_available_list[idx] = False

                            # switch_type_safety_avoided: only when feature is ON and selection changed
                            if (
                                self.config.enable_switch_candidate_type_safety
                                and safer_switch_candidate_available_list[idx]
                            ):
                                switch_type_safety_avoided_list[idx] = True
                        else:
                            safer_switch_candidate_available_list[idx] = False

                        # switch_candidate_type_safety_applied: only when feature is ON
                        if self.config.enable_switch_candidate_type_safety:
                            switch_type_safety_applied_list[idx] = True

            # Phase 6.4.5: Stale target audit computation
            stale_target_selected = False
            stale_target_avoided = False
            stale_target_same_target_expected_ko = False
            stale_target_caused_no_effect = False
            stale_target_caused_type_immune = False
            stale_target_first_slot_val = 0
            stale_target_first_move = ""
            stale_target_first_target = ""
            stale_target_second_slot_val = 1
            stale_target_second_move = ""
            stale_target_second_intended_target = ""
            stale_target_fallback_target = ""
            stale_target_reason = ""

            first_order = best_joint.first_order
            second_order = best_joint.second_order
            if (
                first_order
                and second_order
                and isinstance(first_order.order, Move)
                and isinstance(second_order.order, Move)
            ):
                ft = getattr(first_order, "move_target", None)
                st = getattr(second_order, "move_target", None)
                if ft in (1, 2) and st in (1, 2) and ft == st:
                    if (
                        getattr(first_order.order, "base_power", 0) > 0
                        and getattr(second_order.order, "base_power", 0) > 0
                    ):
                        if not self.is_spread_move(
                            first_order.order
                        ) and not self.is_spread_move(second_order.order):
                            target_opp = battle.opponent_active_pokemon[ft - 1]
                            if target_opp:
                                ko_1 = self.check_move_will_ko(
                                    first_order.order,
                                    battle.active_pokemon[0],
                                    target_opp,
                                    battle,
                                    config=self.config,
                                )
                                if ko_1:
                                    visible_opps = [
                                        o
                                        for o in battle.opponent_active_pokemon
                                        if o and not getattr(o, "fainted", False)
                                    ]
                                    stale = detect_stale_target_after_ally_ko_risk(
                                        first_order,
                                        second_order,
                                        ko_1,
                                        target_opp,
                                        target_opp,
                                        visible_opps,
                                        battle=battle,
                                        config=self.config,
                                    )
                                    if stale["risk"]:
                                        stale_target_selected = True
                                        stale_target_same_target_expected_ko = True
                                        stale_target_caused_no_effect = stale[
                                            "fallback_target_no_effect"
                                        ]
                                        stale_target_caused_type_immune = stale[
                                            "fallback_target_type_immune"
                                        ]
                                        stale_target_first_slot_val = 0
                                        stale_target_first_move = stale["first_move_id"]
                                        stale_target_first_target = stale[
                                            "first_target_species"
                                        ]
                                        stale_target_second_slot_val = 1
                                        stale_target_second_move = stale[
                                            "second_move_id"
                                        ]
                                        stale_target_second_intended_target = stale[
                                            "second_target_species"
                                        ]
                                        stale_target_fallback_target = stale[
                                            "fallback_target_species"
                                        ]
                                        stale_target_reason = stale["reason"]

            # Check if stale target was avoided: any alternative had risk but selected didn't
            if (
                not stale_target_selected
                and self.config.enable_stale_target_after_ally_ko_safety
            ):
                for alt_joint, alt_score, _, _ in scored_joint_orders[
                    1 : min(6, len(scored_joint_orders))
                ]:
                    alt_first = alt_joint.first_order
                    alt_second = alt_joint.second_order
                    if (
                        alt_first
                        and alt_second
                        and isinstance(alt_first.order, Move)
                        and isinstance(alt_second.order, Move)
                    ):
                        at = getattr(alt_first, "move_target", None)
                        bt = getattr(alt_second, "move_target", None)
                        if at in (1, 2) and bt in (1, 2) and at == bt:
                            if (
                                getattr(alt_first.order, "base_power", 0) > 0
                                and getattr(alt_second.order, "base_power", 0) > 0
                            ):
                                if not self.is_spread_move(
                                    alt_first.order
                                ) and not self.is_spread_move(alt_second.order):
                                    alt_target = battle.opponent_active_pokemon[at - 1]
                                    if alt_target:
                                        alt_ko = self.check_move_will_ko(
                                            alt_first.order,
                                            battle.active_pokemon[0],
                                            alt_target,
                                            battle,
                                            config=self.config,
                                        )
                                        if alt_ko:
                                            vis_opps = [
                                                o
                                                for o in battle.opponent_active_pokemon
                                                if o
                                                and not getattr(o, "fainted", False)
                                            ]
                                            alt_stale = (
                                                detect_stale_target_after_ally_ko_risk(
                                                    alt_first,
                                                    alt_second,
                                                    alt_ko,
                                                    alt_target,
                                                    alt_target,
                                                    vis_opps,
                                                    battle=battle,
                                                    config=self.config,
                                                )
                                            )
                                            if alt_stale["risk"]:
                                                stale_target_avoided = True
                                                break

            self._stale_target_selected[battle_tag] = stale_target_selected
            self._stale_target_same_target_expected_ko[battle_tag] = (
                stale_target_same_target_expected_ko
            )
            self._stale_target_caused_no_effect[battle_tag] = (
                stale_target_caused_no_effect
            )
            self._stale_target_caused_type_immune[battle_tag] = (
                stale_target_caused_type_immune
            )
            self._stale_target_first_slot[battle_tag] = stale_target_first_slot_val
            self._stale_target_first_move[battle_tag] = stale_target_first_move
            self._stale_target_first_target[battle_tag] = stale_target_first_target
            self._stale_target_second_slot[battle_tag] = stale_target_second_slot_val
            self._stale_target_second_move[battle_tag] = stale_target_second_move
            self._stale_target_second_intended_target[battle_tag] = (
                stale_target_second_intended_target
            )
            self._stale_target_fallback_target[battle_tag] = (
                stale_target_fallback_target
            )
            self._stale_target_reason[battle_tag] = stale_target_reason

            # Phase 6.3.8b — Build support target candidate
            # table from valid orders
            _support_target_candidates = []
            for si in (0, 1):
                orders_slot = (
                    valid_orders[si] if valid_orders and len(valid_orders) > si else []
                )
                slot_candidates = build_support_target_candidate_table(
                    orders_slot, si, battle, config=self.config
                )
                # Mark the selected candidate
                sel_order = (
                    best_joint.first_order if si == 0 else best_joint.second_order
                )
                sel_move = (
                    getattr(getattr(sel_order, "order", None), "id", "")
                    if sel_order
                    else ""
                )
                sel_target = (
                    getattr(sel_order, "move_target", None) if sel_order else None
                )
                for row in slot_candidates:
                    if (
                        row["move_id"] == sel_move
                        and row["target_position"] == sel_target
                    ):
                        row["selected"] = True
                _support_target_candidates.extend(slot_candidates)

            # Phase 6.3.8b — Compute per-slot support
            # target audit summary. The full candidate
            # table is written to the audit log; these
            # mirrored per-slot fields let the inspector
            # and per-slot counters read them without
            # iterating the list.
            _sup_blocked = [False, False]
            _sup_selected = [False, False]
            _sup_avoided = [False, False]
            _sup_only_legal = [False, False]
            _sup_move_id = [None, None]
            _sup_intended_side = [None, None]
            _sup_actual_side = [None, None]
            _sup_target_position = [None, None]
            _sup_target_species = [None, None]
            _sup_block_reason = [None, None]
            _sup_classification_source = [None, None]
            _sup_blocked_candidate_score = [None, None]
            _sup_safe_alt_kind = [None, None]
            _sup_safe_alt_move_id = [None, None]
            _sup_safe_alt_target_position = [None, None]
            _sup_wrong_side_selected = [False, False]
            for _si in (0, 1):
                _si_candidates = [
                    c for c in _support_target_candidates
                    if c.get("slot") == _si
                ]
                if _si_candidates:
                    _sup_blocked[_si] = any(
                        c.get("blocked")
                        for c in _si_candidates
                    )
                    _sup_avoided[_si] = (
                        _sup_blocked[_si]
                        and not any(
                            c.get("selected") and c.get("blocked")
                            for c in _si_candidates
                        )
                    )
                    _sup_only_legal[_si] = (
                        _sup_blocked[_si]
                        and all(
                            c.get("blocked")
                            for c in _si_candidates
                            if c.get("intended_side")
                            in ("ally", "opponent")
                        )
                    )
                    _sel_row = next(
                        (c for c in _si_candidates if c.get("selected")),
                        None,
                    )
                    if _sel_row:
                        # ``support_target_selected`` means
                        # "wrong-side selected" (the
                        # selected support candidate was
                        # blocked). This is the
                        # ``candidate_blocked == selected +
                        # avoided`` invariant. A correct
                        # support selection (intended
                        # matches actual, not blocked)
                        # is NOT counted as
                        # ``support_target_selected``.
                        if _sel_row.get("blocked"):
                            _sup_selected[_si] = True
                            _sup_move_id[_si] = _sel_row.get("move_id")
                            _sup_intended_side[_si] = _sel_row.get(
                                "intended_side"
                            )
                            _sup_actual_side[_si] = _sel_row.get(
                                "target_side"
                            )
                            _sup_target_position[_si] = _sel_row.get(
                                "target_position"
                            )
                            _sup_target_species[_si] = _sel_row.get(
                                "target_species"
                            )
                            _sup_block_reason[_si] = _sel_row.get(
                                "block_reason"
                            )
                            _sup_classification_source[_si] = _sel_row.get(
                                "classification_source"
                            )
                            if (
                                _sel_row.get("intended_side")
                                in ("ally", "opponent")
                            ):
                                _sup_blocked_candidate_score[_si] = (
                                    float(
                                        self.config
                                        .support_move_wrong_side_block_score
                                    )
                                )
                        else:
                            # The selected support
                            # candidate is a CORRECT
                            # selection (not blocked).
                            # We still record the move
                            # metadata for the audit
                            # but mark _sup_selected as
                            # False to preserve the
                            # invariant.
                            _sup_move_id[_si] = _sel_row.get("move_id")
                            _sup_intended_side[_si] = _sel_row.get(
                                "intended_side"
                            )
                            _sup_actual_side[_si] = _sel_row.get(
                                "target_side"
                            )
                            _sup_target_position[_si] = _sel_row.get(
                                "target_position"
                            )
                            _sup_target_species[_si] = _sel_row.get(
                                "target_species"
                            )
                            _sup_classification_source[_si] = _sel_row.get(
                                "classification_source"
                            )
                        # Wrong-side: selected AND blocked
                        # AND the actual side does not match
                        # the intended side. The
                        # ``_sup_selected`` flag was already
                        # set above; we additionally mark
                        # ``_sup_wrong_side_selected`` to
                        # distinguish the actual wrong-side
                        # case (the auditor cares about
                        # wrong-side specifically).
                        if _sel_row.get("blocked") and (
                            (
                                _sel_row.get("intended_side")
                                == "opponent"
                                and _sel_row.get("target_side")
                                in ("ally", "self")
                            )
                            or (
                                _sel_row.get("intended_side")
                                == "ally"
                                and _sel_row.get("target_side")
                                in ("opponent", "self")
                            )
                            or (
                                _sel_row.get("intended_side")
                                == "self"
                                and _sel_row.get("target_side")
                                != "self"
                            )
                        ):
                            _sup_wrong_side_selected[_si] = True
                    # Safe alternative: if a blocked
                    # candidate was selected (only-legal),
                    # record the best safe alternative.
                    if _sup_only_legal[_si]:
                        # Find an unblocked candidate in
                        # the slot. Prefer the first
                        # unblocked candidate with the same
                        # move_id (or any unblocked).
                        _alt = next(
                            (
                                c for c in _si_candidates
                                if not c.get("blocked")
                            ),
                            None,
                        )
                        if _alt:
                            _sup_safe_alt_kind[_si] = (
                                "alternative_in_same_slot"
                            )
                            _sup_safe_alt_move_id[_si] = (
                                _alt.get("move_id")
                            )
                            _sup_safe_alt_target_position[_si] = (
                                _alt.get("target_position")
                            )

            # Phase 6.4.9: Compute authoritative VSW outcome fields
            _vsw_unnecessary = [False, False]
            _vsw_unsafe = [False, False]
            _vsw_repeat = [False, False]
            _vsw_sac_opp = [False, False]
            _vsw_healthy = [False, False]
            _vsw_safer = [False, False]
            _vsw_active_species = ["", ""]
            _vsw_active_hp = [0.0, 0.0]
            _vsw_best_stay = [0.0, 0.0]
            # Phase BI-2D: capture the non-switch action key
            # whose score equals _vsw_best_stay[_si]. Set
            # inside the existing best-stay loop below.
            _vsw_best_stay_action = [None, None]
            _vsw_sel_active_risk = [0.0, 0.0]
            _vsw_sel_cand_risk = [0.0, 0.0]
            _vsw_sel_risk_red = [0.0, 0.0]
            _vsw_sel_score_adj = [0.0, 0.0]
            _vsw_reason_codes = [[], []]
            for _si in (0, 1):
                _tbl = _voluntary_switch_candidate_tables.get(_si, [])
                _sel_row = next((r for r in _tbl if r.get("selected")), None)
                _active = (
                    battle.active_pokemon[_si]
                    if _si < len(battle.active_pokemon)
                    else None
                )
                if _active:
                    _vsw_active_species[_si] = getattr(_active, "species", "")
                    _vsw_active_hp[_si] = float(
                        getattr(_active, "current_hp_fraction", 1.0) or 1.0
                    )
                _vsw_selected_si = _sel_row is not None
                _best = 0.0
                _orders_si = (
                    valid_orders[_si]
                    if valid_orders and len(valid_orders) > _si
                    else []
                )
                for _o in _orders_si:
                    if _o and isinstance(_o.order, Move):
                        sc = (
                            slot_0_scores.get(id(_o), 0.0)
                            if _si == 0
                            else slot_1_scores.get(id(_o), 0.0)
                        )
                        if sc > _best:
                            _best = sc
                            # Phase BI-2D: observational capture
                            # of the action key whose score
                            # equals _vsw_best_stay. No
                            # comparison or scoring change.
                            try:
                                _vsw_best_stay_action[_si] = (
                                    _order_action_key(_o)
                                )
                            except Exception:
                                _vsw_best_stay_action[_si] = None
                _vsw_best_stay[_si] = _best
                _ar = 0.0
                if _sel_row:
                    _vsw_sel_active_risk[_si] = _sel_row.get("active_risk", 0.0)
                    _vsw_sel_cand_risk[_si] = _sel_row.get("candidate_risk", 0.0)
                    _vsw_sel_risk_red[_si] = _sel_row.get("risk_reduction", 0.0)
                    _vsw_sel_score_adj[_si] = _sel_row.get("score_adjustment", 0.0)
                    _vsw_reason_codes[_si] = list(_sel_row.get("reason_codes", []))
                    _has_use = _sel_row.get("active_has_useful_action", False)
                    _impr = _sel_row.get("switch_improves_position", False)
                    _dt = _sel_row.get("double_threat", False)
                    _qw = _sel_row.get("quad_weak", False)
                    _cr = _sel_row.get("candidate_risk", 0.0)
                    _ar = _sel_row.get("active_risk", 0.0)
                    if _has_use and (not _impr or _cr >= _ar or _dt or _qw):
                        _vsw_unnecessary[_si] = True
                    if _dt or _qw or _cr > _ar:
                        _vsw_unsafe[_si] = True
                    if _sel_row.get("repeat_penalty", 0) > 0:
                        _vsw_repeat[_si] = True
                    for _r in _tbl:
                        if _r.get("switch_improves_position", False) and not _r.get(
                            "selected", False
                        ):
                            _vsw_safer[_si] = True
                            break
                _active_low = _vsw_active_hp[_si] <= getattr(
                    self.config, "voluntary_switch_sacrifice_hp_threshold", 0.15
                )
                _has_useful = _best > getattr(
                    self.config, "voluntary_switch_useful_action_threshold", 40.0
                )
                _vsw_sac_opp[_si] = _active_low and _has_useful
                if not _vsw_selected_si and _vsw_sac_opp[_si]:
                    for _r in _tbl:
                        if (
                            _r.get("hp", 1.0) >= _vsw_active_hp[_si]
                            and _r.get("candidate_risk", 0.0) >= _ar
                        ):
                            _vsw_healthy[_si] = True
                            break

            # V2l.1 — capture the per-decision
            # execution-derived snapshot for parity
            # proof. These reads come from the live
            # in-progress variables in this
            # ``choose_move`` invocation, so the audit
            # logger can prove the legal keys, raw
            # scores, safety block maps, selected
            # joint-order key, and final per-slot
            # action keys were produced by THIS
            # ``choose_move`` call.
            self._v2l1_raw_scores_slot0 = (
                _raw_score_map_for_slot(
                    slot_0_scores, valid_orders, 0
                )
            )
            self._v2l1_raw_scores_slot1 = (
                _raw_score_map_for_slot(
                    slot_1_scores, valid_orders, 1
                )
            )
            self._v2l1_safety_blocks_slot0 = (
                _safety_block_map_for_slot(
                    _safety_blocked, valid_orders, 0
                )
            )
            self._v2l1_safety_blocks_slot1 = (
                _safety_block_map_for_slot(
                    _safety_blocked, valid_orders, 1
                )
            )
            self._v2l1_selected_joint_key = (
                _selected_joint_key(best_joint)
            )
            self._v2l1_final_keys = (
                _final_action_keys_from_joint(best_joint)
            )

            # Phase BI-1 audit-completeness: compute
            # V4a mechanic-aware audit fields. These are
            # data-assembly only (no scoring change). The
            # helpers already exist in
            # ``doubles_engine.action_keys``. For
            # ``best_joint`` (a joint order), the
            # mechanic label is derived from the per-slot
            # orders via ``_order_mechanic_label``.
            self._v4a_legal_keys_slot0 = (
                _legal_action_keys_with_mechanic_for_slot(
                    valid_orders, 0
                )
            )
            self._v4a_legal_keys_slot1 = (
                _legal_action_keys_with_mechanic_for_slot(
                    valid_orders, 1
                )
            )
            self._v4a_selected_joint_key = (
                _selected_joint_key_with_mechanic(best_joint)
            )
            self._v4a_final_keys = (
                _final_action_keys_with_mechanic_from_joint(
                    best_joint
                )
            )
            # Phase SETUP-3A: record setup-move picks for
            # the anti-spam guards. Check each slot's
            # selected order for a TW/TR move and record
            # the pick if any.
            for _si, _sel_order in (
                (0, best_joint.first_order),
                (1, best_joint.second_order),
            ):
                if _sel_order is None:
                    continue
                _sel_move = getattr(_sel_order, "order", None)
                if not isinstance(_sel_move, Move):
                    continue
                _mid = _normalize_move_id_for_spread_defense(
                    getattr(_sel_move, "id", "")
                )
                if _mid in ("tailwind", "trickroom"):
                    self.record_setup_intent_pick(
                        battle_tag, current_turn
                    )

            # PLANNER-SPREAD-3d: register self with the audit
            # logger so it can read per-pick counters
            # (e.g. _planner_spread_defense_picks_per_game)
            # from the player. poke-env battle object doesn't
            # carry the player reference, and the audit's
            # _populate is a @staticmethod without self access,
            # so we use the class-level dict.
            DoublesDecisionAuditLogger._battle_player_refs[battle_tag] = self

            self.audit_logger.log_turn_decision(
                battle_tag=battle_tag,
                turn=current_turn,
                battle=battle,
                selected_joint_order=self.safe_get_joint_message(best_joint),
                selected_score=best_score,
                scored_joint_orders=scored_joint_orders,
                expected_damages=expected_damages,
                expected_kos=expected_kos,
                target_hps=target_hps,
                overkill_triggered=overkill_triggered,
                focus_fire_triggered=focus_fire_triggered,
                ally_hit_penalty_triggered=ally_hit_penalty_triggered,
                spread_available=spread_available,
                best_spread_score=best_spread_score,
                best_ko_score=best_ko_score,
                low_hp_opponent_existed=low_hp_opponent_existed,
                low_hp_opponent_targeted=low_hp_opponent_targeted,
                slot_actions=slot_actions,
                slot_action_types=slot_action_types,
                target_species=target_species,
                selected_action_kind=selected_action_kind,
                selected_action_move_id=selected_action_move_id,
                selected_action_target_position=selected_action_target_position,
                selected_action_species=selected_action_species,
                selected_action_only_legal=selected_action_only_legal,
                # Phase 6.4 partial-spread audit readout
                # (Phase Ponytail Refactor Step 7D). The
                # repeated ``setdefault`` + index pattern
                # is delegated to
                # ``doubles_engine.audit_metadata.assemble_partial_spread_state``.
                # Behavior preserved bit-for-bit, including
                # the per-battle ``setdefault`` mutation
                # semantics.
                **assemble_partial_spread_state(
                    battle_tag,
                    self.partial_immune_spread_by_battle,
                    self.partial_ability_immune_spread_by_battle,
                    self.efficient_partial_spread_by_battle,
                    self.inefficient_partial_spread_by_battle,
                    self.immune_target_species_by_battle,
                    self.damaged_target_species_by_battle,
                ),
                best_single_target_alternative=[
                    self.best_single_alternative_by_battle.setdefault(
                        battle_tag, {0: "", 1: ""}
                    )[0],
                    self.best_single_alternative_by_battle.setdefault(
                        battle_tag, {0: "", 1: ""}
                    )[1],
                ],
                speed_priority_threatened=[
                    self._speed_priority_threatened.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[0],
                    self._speed_priority_threatened.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[1],
                ],
                faster_opponents=[
                    self._faster_opponents.setdefault(battle_tag, {0: [], 1: []})[0],
                    self._faster_opponents.setdefault(battle_tag, {0: [], 1: []})[1],
                ],
                priority_opponents=[
                    self._priority_opponents.setdefault(battle_tag, {0: [], 1: []})[0],
                    self._priority_opponents.setdefault(battle_tag, {0: [], 1: []})[1],
                ],
                speed_priority_protect_bonus_applied=[
                    self._speed_priority_protect_bonus_applied.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[0],
                    self._speed_priority_protect_bonus_applied.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[1],
                ],
                speed_priority_attack_penalty_applied=[
                    self._speed_priority_attack_penalty_applied.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[0],
                    self._speed_priority_attack_penalty_applied.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[1],
                ],
                # Phase BEHAVIOR-17: per-turn Protect
                # floor diagnostic. Aggregated from the
                # per-action debug dict populated by
                # score_action. JSON-safe: only strings,
                # numbers, booleans, and lists of
                # primitives.
                speed_priority_protect_floor_debug=(
                    self._build_b17_protect_floor_debug_for_turn(
                        battle_tag, valid_orders
                    )
                ),
                speed_priority_switch_bonus_applied=[
                    self._speed_priority_switch_bonus_applied.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[0],
                    self._speed_priority_switch_bonus_applied.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[1],
                ],
                order_aware_overkill_penalty_applied=self._order_aware_overkill_penalty_applied.setdefault(
                    battle_tag, False
                ),
                expected_to_faint_before_moving=[
                    self._expected_to_faint_before_moving.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[0],
                    self._expected_to_faint_before_moving.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[1],
                ],
                protected_due_to_speed_priority=[
                    self._protected_due_to_speed_priority.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[0],
                    self._protected_due_to_speed_priority.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[1],
                ],
                protect_like_available=protect_like_available,
                switch_available=switch_available,
                only_conditional_priority=only_conditional_priority,
                stalling_field_condition=stalling_field_condition,
                # Phase SPREAD-2: spread-defense audit
                # wiring (Wide Guard / Quick Guard /
                # Crafty Shield). Pure observation;
                # no scoring change. The logger writes
                # per-slot booleans to slot_0/slot_1
                # and persists the top-level
                # ``opp_pressure_state`` flag.
                wide_guard_legal=wide_guard_legal,
                quick_guard_legal=quick_guard_legal,
                crafty_shield_legal=crafty_shield_legal,
                spread_defense_selected=spread_defense_selected,
                opp_pressure_state=opp_pressure_state,
                # Phase SPREAD-4: per-slot spread-defense
                # raw score + score gap vs selected. Pure
                # observation; no scoring change in the
                # bot. The audit logger writes the per-
                # slot score fields and a top-level
                # ``score_gap_wide_guard_vs_selected``
                # list so the dry-run simulator can
                # compute decision-flip counts at
                # various hypothetical bonus magnitudes.
                wide_guard_score=wide_guard_score,
                quick_guard_score=quick_guard_score,
                crafty_shield_score=crafty_shield_score,
                score_gap_wide_guard_vs_selected=score_gap_wg_vs_selected,
                score_gap_quick_guard_vs_selected=score_gap_qg_vs_selected,
                ability_hard_block_avoided=[
                    self._ability_hard_block_avoided.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[0],
                    self._ability_hard_block_avoided.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[1],
                ],
                ability_immune_move_selected=[
                    self._ability_immune_move_selected.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[0],
                    self._ability_immune_move_selected.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[1],
                ],
                ground_into_levitate_selected=[
                    self._ground_into_levitate_selected.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[0],
                    self._ground_into_levitate_selected.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[1],
                ],
                ability_block_reason=[
                    self._ability_block_reason.setdefault(battle_tag, {0: "", 1: ""})[
                        0
                    ],
                    self._ability_block_reason.setdefault(battle_tag, {0: "", 1: ""})[
                        1
                    ],
                ],
                ability_blocked_target_species=[
                    self._ability_blocked_target_species.setdefault(
                        battle_tag, {0: "", 1: ""}
                    )[0],
                    self._ability_blocked_target_species.setdefault(
                        battle_tag, {0: "", 1: ""}
                    )[1],
                ],
                ability_blocked_target_ability=[
                    self._ability_blocked_target_ability.setdefault(
                        battle_tag, {0: "", 1: ""}
                    )[0],
                    self._ability_blocked_target_ability.setdefault(
                        battle_tag, {0: "", 1: ""}
                    )[1],
                ],
                ally_ability_safe_spread=[
                    self._ally_ability_safe_spread.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[0],
                    self._ally_ability_safe_spread.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[1],
                ],
                ability_redirection_avoided=[
                    self._ability_redirection_avoided.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[0],
                    self._ability_redirection_avoided.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[1],
                ],
                absorb_immune_move_selected=absorb_immune_move_selected_list,
                absorb_selection_forced=absorb_selection_forced_list,
                absorb_safe_alternative_available=absorb_safe_alternative_available_list,
                absorb_best_safe_alternative_move=absorb_best_safe_alternative_move_list,
                absorb_best_safe_alternative_target=absorb_best_safe_alternative_target_list,
                absorb_best_safe_alternative_score=absorb_best_safe_alternative_score_list,
                absorb_selected_score=absorb_selected_score_list,
                absorb_selected_streak=absorb_selected_streak_list,
                avoidable_absorb_error=avoidable_absorb_error_list,
                productive_partial_absorb_spread=productive_partial_absorb_spread_list,
                absorb_error_reason=absorb_error_reason_list,
                absorb_via_redirection=absorb_via_redirection_list,
                absorb_intended_target_species=absorb_intended_target_species_list,
                absorb_intended_target_ability=absorb_intended_target_ability_list,
                absorb_effective_target_species=absorb_effective_target_species_list,
                absorb_effective_target_ability=absorb_effective_target_ability_list,
                absorb_selected_move_id=absorb_selected_move_id_list,
                direct_absorb_hard_block_avoided=[
                    self._direct_absorb_hard_block_avoided.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[0],
                    self._direct_absorb_hard_block_avoided.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[1],
                ],
                direct_absorb_immune_move_selected=[
                    self._direct_absorb_immune_move_selected.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[0],
                    self._direct_absorb_immune_move_selected.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[1],
                ],
                direct_absorb_block_reason=[
                    self._direct_absorb_block_reason.setdefault(
                        battle_tag, {0: "", 1: ""}
                    )[0],
                    self._direct_absorb_block_reason.setdefault(
                        battle_tag, {0: "", 1: ""}
                    )[1],
                ],
                direct_absorb_target_species=[
                    self._direct_absorb_target_species.setdefault(
                        battle_tag, {0: "", 1: ""}
                    )[0],
                    self._direct_absorb_target_species.setdefault(
                        battle_tag, {0: "", 1: ""}
                    )[1],
                ],
                direct_absorb_target_ability=[
                    self._direct_absorb_target_ability.setdefault(
                        battle_tag, {0: "", 1: ""}
                    )[0],
                    self._direct_absorb_target_ability.setdefault(
                        battle_tag, {0: "", 1: ""}
                    )[1],
                ],
                direct_absorb_only_legal_action=[
                    self._direct_absorb_only_legal_action.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[0],
                    self._direct_absorb_only_legal_action.setdefault(
                        battle_tag, {0: False, 1: False}
                    )[1],
                ],
                direct_known_absorb_repeat_selected=direct_known_absorb_repeat_selected_list,
                forced_switch=forced_switch_list,
                switch_candidate_type_safety_applied=switch_type_safety_applied_list,
                selected_switch_species=selected_switch_species_list,
                selected_switch_types=selected_switch_types_list,
                selected_switch_hp_fraction=selected_switch_hp_fraction_list,
                selected_switch_raw_safety_score=selected_switch_raw_safety_score_list,
                selected_switch_relative_adjustment=selected_switch_relative_adjustment_list,
                selected_switch_worst_multiplier=selected_switch_worst_multiplier_list,
                selected_switch_double_threat=selected_switch_double_threat_list,
                unsafe_switch_candidate_selected=unsafe_switch_candidate_selected_list,
                safer_switch_candidate_available=safer_switch_candidate_available_list,
                best_safe_switch_species=best_safe_switch_species_list,
                best_safe_switch_score=best_safe_switch_score_list,
                switch_type_safety_avoided=switch_type_safety_avoided_list,
                # Phase 6.4.3a.2: Forced switch diagnostics
                forced_switch_candidate_count=forced_switch_candidate_count_list,
                forced_switch_selected_index=forced_switch_selected_index_list,
                forced_switch_selected_species=forced_switch_selected_species_list,
                forced_switch_best_safety_species=forced_switch_best_safety_species_list,
                forced_switch_selected_safety_score=forced_switch_selected_safety_score_list,
                forced_switch_best_safety_score=forced_switch_best_safety_score_list,
                forced_switch_order_fallback_used=forced_switch_order_fallback_used_list,
                # Phase 6.4.4: Forced switch replacement safety audit fields
                forced_switch_safety_enabled=forced_switch_safety_enabled_list,
                forced_switch_safety_selection_changed=forced_switch_safety_selection_changed_list,
                forced_switch_selected_double_threat=forced_switch_selected_double_threat_list,
                forced_switch_best_avoids_double_threat=forced_switch_best_avoids_double_threat_list,
                forced_switch_selected_quad_weak=forced_switch_selected_quad_weak_list,
                forced_switch_best_avoids_quad_weak=forced_switch_best_avoids_quad_weak_list,
                forced_switch_selected_low_hp=forced_switch_selected_low_hp_list,
                forced_switch_reason=forced_switch_reason_list,
                forced_switch_candidate_safety_table=forced_switch_candidate_safety_table_list,
                neg_boost_total_negative_stages=neg_boost_total_list,
                neg_boost_lowest_stage=neg_boost_lowest_list,
                neg_boost_offensive_negative_stages=neg_boost_offensive_list,
                neg_boost_defensive_negative_stages=neg_boost_defensive_list,
                neg_boost_speed_negative_stage=neg_boost_speed_list,
                neg_boost_severe_negative_boost=neg_boost_severe_list,
                neg_boost_was_switch=neg_boost_was_switch_list,
                neg_boost_decision_eligible=[
                    _neg_boost_data_per_slot.get(0, {}).get(
                        "negative_boost_decision_eligible", False
                    ),
                    _neg_boost_data_per_slot.get(1, {}).get(
                        "negative_boost_decision_eligible", False
                    ),
                ],
                neg_boost_selected_action_kind=[
                    _neg_boost_data_per_slot.get(0, {}).get(
                        "negative_boost_selected_action_kind", ""
                    ),
                    _neg_boost_data_per_slot.get(1, {}).get(
                        "negative_boost_selected_action_kind", ""
                    ),
                ],
                neg_boost_legal_switch_count=[
                    _neg_boost_data_per_slot.get(0, {}).get(
                        "negative_boost_legal_switch_count", 0
                    ),
                    _neg_boost_data_per_slot.get(1, {}).get(
                        "negative_boost_legal_switch_count", 0
                    ),
                ],
                neg_boost_best_switch_species=[
                    _neg_boost_data_per_slot.get(0, {}).get(
                        "negative_boost_best_switch_species", ""
                    ),
                    _neg_boost_data_per_slot.get(1, {}).get(
                        "negative_boost_best_switch_species", ""
                    ),
                ],
                neg_boost_best_switch_score=[
                    _neg_boost_data_per_slot.get(0, {}).get(
                        "negative_boost_best_switch_score", 0.0
                    ),
                    _neg_boost_data_per_slot.get(1, {}).get(
                        "negative_boost_best_switch_score", 0.0
                    ),
                ],
                neg_boost_best_move_score=[
                    _neg_boost_data_per_slot.get(0, {}).get(
                        "negative_boost_best_move_score", 0.0
                    ),
                    _neg_boost_data_per_slot.get(1, {}).get(
                        "negative_boost_best_move_score", 0.0
                    ),
                ],
                neg_boost_switch_score_gap=[
                    _neg_boost_data_per_slot.get(0, {}).get(
                        "negative_boost_switch_score_gap", 0.0
                    ),
                    _neg_boost_data_per_slot.get(1, {}).get(
                        "negative_boost_switch_score_gap", 0.0
                    ),
                ],
                neg_boost_relevant_offensive_drop=[
                    _neg_boost_data_per_slot.get(0, {}).get(
                        "negative_boost_relevant_offensive_drop", False
                    ),
                    _neg_boost_data_per_slot.get(1, {}).get(
                        "negative_boost_relevant_offensive_drop", False
                    ),
                ],
                neg_boost_defensive_drop=[
                    _neg_boost_data_per_slot.get(0, {}).get(
                        "negative_boost_defensive_drop", False
                    ),
                    _neg_boost_data_per_slot.get(1, {}).get(
                        "negative_boost_defensive_drop", False
                    ),
                ],
                neg_boost_speed_drop=[
                    _neg_boost_data_per_slot.get(0, {}).get(
                        "negative_boost_speed_drop", False
                    ),
                    _neg_boost_data_per_slot.get(1, {}).get(
                        "negative_boost_speed_drop", False
                    ),
                ],
                # Phase 6.4.3: Stat-drop switch diagnostic fields
                severe_neg_boost_active=severe_neg_boost_active_list,
                severe_neg_boost_categories=severe_neg_boost_categories_list,
                severe_neg_boost_switch_available=severe_neg_boost_switch_available_list,
                severe_neg_boost_switched=severe_neg_boost_switched_list,
                severe_neg_boost_stayed=severe_neg_boost_stayed_list,
                severe_neg_boost_stayed_productive=severe_neg_boost_stayed_productive_list,
                severe_neg_boost_stayed_unproductive=severe_neg_boost_stayed_unproductive_list,
                severe_neg_boost_only_legal_no_switch=severe_neg_boost_only_legal_no_switch_list,
                severe_neg_boost_best_switch_candidate=severe_neg_boost_best_switch_candidate_list,
                severe_neg_boost_selected_action=severe_neg_boost_selected_action_list,
                severe_neg_boost_turn=severe_neg_boost_turn_list,
                severe_neg_boost_species=severe_neg_boost_species_list,
                # Phase 6.4.7: Stat-drop switch scoring audit fields
                stat_drop_switch_scoring_enabled=stat_drop_switch_scoring_enabled_list,
                stat_drop_switch_pressure_active=stat_drop_switch_pressure_active_list,
                stat_drop_switch_pressure_categories=stat_drop_switch_pressure_categories_list,
                stat_drop_switch_pressure_score=stat_drop_switch_pressure_score_list,
                stat_drop_switch_selected=stat_drop_switch_selected_list,
                stat_drop_switch_stayed=stat_drop_switch_stayed_list,
                stat_drop_switch_stayed_productive=stat_drop_switch_stayed_productive_list,
                stat_drop_switch_stayed_unproductive=stat_drop_switch_stayed_unproductive_list,
                stat_drop_switch_selection_changed=stat_drop_switch_selection_changed_list,
                stat_drop_switch_best_switch_species=stat_drop_switch_best_switch_species_list,
                stat_drop_switch_best_switch_score=stat_drop_switch_best_switch_score_list,
                stat_drop_switch_best_non_switch_score=stat_drop_switch_best_non_switch_score_list,
                stat_drop_switch_reason=stat_drop_switch_reason_list,
                stat_drop_switch_threshold_source=stat_drop_switch_threshold_source_list,
                # Phase 6.3.6b: Known Ally Redirection audit fields
                known_ally_redirection_selected=known_ally_redirection_selected_list,
                known_ally_redirection_reason=known_ally_redirection_reason_list,
                known_ally_redirection_ally_species=known_ally_redirection_ally_species_list,
                known_ally_redirection_ally_ability=known_ally_redirection_ally_ability_list,
                known_ally_redirection_move_id=known_ally_redirection_move_id_list,
                known_ally_redirection_known_before_decision=known_ally_redirection_known_before_decision_list,
                known_ally_redirection_candidate_blocked=known_ally_redirection_candidate_blocked_list,
                known_ally_redirection_avoided=known_ally_redirection_avoided_list,
                known_ally_redirection_only_legal=known_ally_redirection_only_legal_list,
                known_ally_redirection_repeat_selected=known_ally_redirection_repeat_selected_list,
                known_ally_redirection_safe_alternative_available=known_ally_redirection_safe_alternative_available_list,
                our_known_ally_redirection_error=our_known_ally_redirection_error_list,
                opponent_known_ally_redirection_error=opponent_known_ally_redirection_error_list,
                # Phase 6.3.7: Dynamic move type audit
                declared_move_type=declared_move_type_list,
                effective_move_type=effective_move_type_list,
                effective_move_type_source=effective_move_type_source_list,
                dynamic_move_type_applied=dynamic_move_type_applied_list,
                dynamic_move_type_form=dynamic_move_type_form_list,
                # Phase 6.3.7f: Dynamic absorb candidate audit
                dynamic_type_absorb_candidate_blocked=dynamic_type_absorb_candidate_blocked_list,
                dynamic_type_absorb_selected=dynamic_type_absorb_selected_list,
                dynamic_type_absorb_avoided=dynamic_type_absorb_avoided_list,
                dynamic_type_absorb_reason=dynamic_type_absorb_reason_list,
                dynamic_type_absorb_target_species=dynamic_type_absorb_target_species_list,
                dynamic_type_absorb_target_ability=dynamic_type_absorb_target_ability_list,
                dynamic_type_absorb_blocked_move_id=dynamic_type_absorb_blocked_move_id_list,
                dynamic_type_absorb_blocked_candidate_score=dynamic_type_absorb_blocked_candidate_score_list,
                dynamic_type_absorb_candidate_available=dynamic_type_absorb_candidate_available_list,
                dynamic_type_absorb_candidate_move_id=dynamic_type_absorb_candidate_move_id_list,
                dynamic_type_absorb_candidate_declared_type=dynamic_type_absorb_candidate_declared_type_list,
                dynamic_type_absorb_candidate_effective_type=dynamic_type_absorb_candidate_effective_type_list,
                dynamic_type_absorb_candidate_form=dynamic_type_absorb_candidate_form_list,
                dynamic_type_absorb_candidate_source=dynamic_type_absorb_candidate_source_list,
                dynamic_type_absorb_candidate_target_table=dynamic_type_absorb_candidate_target_table_list,
                # Phase COMBO-3: ally-activation combo
                # audit. Per-slot booleans. Observational
                # only; no scoring change.
                selected_move_into_known_absorb_ally=selected_move_into_known_absorb_ally_list,
                selected_move_into_known_redirect_ally=selected_move_into_known_redirect_ally_list,
                selected_super_effective_into_weakness_policy_holder=selected_super_effective_into_weakness_policy_holder_list,
                # Phase 6.3.6b.6: Blocked candidate metadata
                known_ally_redirection_opportunity_observed=known_ally_redirection_opportunity_observed_list,
                known_ally_redirection_blocked_candidate_move_id=known_ally_redirection_blocked_candidate_move_id_list,
                known_ally_redirection_blocked_candidate_attacker_species=known_ally_redirection_blocked_candidate_attacker_species_list,
                known_ally_redirection_blocked_candidate_target_species=known_ally_redirection_blocked_candidate_target_species_list,
                known_ally_redirection_blocked_candidate_ally_species=known_ally_redirection_blocked_candidate_ally_species_list,
                known_ally_redirection_blocked_candidate_ally_ability=known_ally_redirection_blocked_candidate_ally_ability_list,
                known_ally_redirection_blocked_candidate_reason=known_ally_redirection_blocked_candidate_reason_list,
                known_ally_redirection_blocked_candidate_known_before=known_ally_redirection_blocked_candidate_known_before_list,
                known_ally_redirection_blocked_candidate_score=known_ally_redirection_blocked_candidate_score_list,
                known_ally_redirection_best_safe_alternative=known_ally_redirection_best_safe_alternative_list,
                known_ally_redirection_best_safe_alternative_score=known_ally_redirection_best_safe_alternative_score_list,
                # Phase 6.4.2: Revealed-Move Switch Interception audit fields
                revealed_switch_prediction_available=[
                    _revel_switch_interception_data.get(0) is not None,
                    _revel_switch_interception_data.get(1) is not None,
                ],
                revealed_switch_interception_selected=[
                    _revel_switch_interception_data.get(0, {}).get(
                        "prediction_available", False
                    )
                    if _revel_switch_interception_data.get(0)
                    and isinstance(best_joint.first_order, type(None)) is False
                    and best_joint.first_order
                    and isinstance(best_joint.first_order.order, Pokemon)
                    else False,
                    _revel_switch_interception_data.get(1, {}).get(
                        "prediction_available", False
                    )
                    if _revel_switch_interception_data.get(1)
                    and isinstance(best_joint.second_order, type(None)) is False
                    and best_joint.second_order
                    and isinstance(best_joint.second_order.order, Pokemon)
                    else False,
                ],
                revealed_switch_selection_changed=_sel_changed_per_slot,
                revealed_switch_threatening_opponent=[
                    _revel_switch_interception_data.get(0, {}).get(
                        "threatening_opponents", ""
                    )
                    if _revel_switch_interception_data.get(0)
                    else "",
                    _revel_switch_interception_data.get(1, {}).get(
                        "threatening_opponents", ""
                    )
                    if _revel_switch_interception_data.get(1)
                    else "",
                ],
                revealed_switch_threat_move_ids=[
                    _revel_switch_interception_data.get(0, {}).get(
                        "threat_move_ids", []
                    )
                    if _revel_switch_interception_data.get(0)
                    else [],
                    _revel_switch_interception_data.get(1, {}).get(
                        "threat_move_ids", []
                    )
                    if _revel_switch_interception_data.get(1)
                    else [],
                ],
                revealed_switch_threat_move_types=[
                    _revel_switch_interception_data.get(0, {}).get(
                        "threat_move_types", []
                    )
                    if _revel_switch_interception_data.get(0)
                    else [],
                    _revel_switch_interception_data.get(1, {}).get(
                        "threat_move_types", []
                    )
                    if _revel_switch_interception_data.get(1)
                    else [],
                ],
                revealed_switch_target_likelihood=[
                    _revel_switch_interception_data.get(0, {}).get(
                        "target_likelihood", []
                    )
                    if _revel_switch_interception_data.get(0)
                    else [],
                    _revel_switch_interception_data.get(1, {}).get(
                        "target_likelihood", []
                    )
                    if _revel_switch_interception_data.get(1)
                    else [],
                ],
                revealed_switch_active_risk=[
                    _revel_switch_interception_data.get(0, {}).get("active_risk", 0.0)
                    if _revel_switch_interception_data.get(0)
                    else 0.0,
                    _revel_switch_interception_data.get(1, {}).get("active_risk", 0.0)
                    if _revel_switch_interception_data.get(1)
                    else 0.0,
                ],
                revealed_switch_candidate_risk=[
                    _revel_switch_interception_data.get(0, {}).get(
                        "candidate_risk", 0.0
                    )
                    if _revel_switch_interception_data.get(0)
                    else 0.0,
                    _revel_switch_interception_data.get(1, {}).get(
                        "candidate_risk", 0.0
                    )
                    if _revel_switch_interception_data.get(1)
                    else 0.0,
                ],
                revealed_switch_risk_reduction=[
                    _revel_switch_interception_data.get(0, {}).get(
                        "risk_reduction", 0.0
                    )
                    if _revel_switch_interception_data.get(0)
                    else 0.0,
                    _revel_switch_interception_data.get(1, {}).get(
                        "risk_reduction", 0.0
                    )
                    if _revel_switch_interception_data.get(1)
                    else 0.0,
                ],
                revealed_switch_candidate_species=[
                    _revel_switch_interception_data.get(0, {}).get(
                        "candidate_species", ""
                    )
                    if _revel_switch_interception_data.get(0)
                    else "",
                    _revel_switch_interception_data.get(1, {}).get(
                        "candidate_species", ""
                    )
                    if _revel_switch_interception_data.get(1)
                    else "",
                ],
                revealed_switch_candidate_types=[
                    _revel_switch_interception_data.get(0, {}).get(
                        "candidate_types", ""
                    )
                    if _revel_switch_interception_data.get(0)
                    else "",
                    _revel_switch_interception_data.get(1, {}).get(
                        "candidate_types", ""
                    )
                    if _revel_switch_interception_data.get(1)
                    else "",
                ],
                revealed_switch_candidate_hp=[
                    _revel_switch_interception_data.get(0, {}).get("candidate_hp", 1.0)
                    if _revel_switch_interception_data.get(0)
                    else 1.0,
                    _revel_switch_interception_data.get(1, {}).get("candidate_hp", 1.0)
                    if _revel_switch_interception_data.get(1)
                    else 1.0,
                ],
                revealed_switch_bonus_applied=[
                    _revel_switch_interception_data.get(0, {}).get("bonus_applied", 0.0)
                    if _revel_switch_interception_data.get(0)
                    else 0.0,
                    _revel_switch_interception_data.get(1, {}).get("bonus_applied", 0.0)
                    if _revel_switch_interception_data.get(1)
                    else 0.0,
                ],
                revealed_switch_blocked_by_ko_action=[
                    _revel_switch_interception_data.get(0, {}).get(
                        "blocked_by_ko", False
                    )
                    if _revel_switch_interception_data.get(0)
                    else False,
                    _revel_switch_interception_data.get(1, {}).get(
                        "blocked_by_ko", False
                    )
                    if _revel_switch_interception_data.get(1)
                    else False,
                ],
                revealed_switch_blocked_by_high_value_action=[
                    _revel_switch_interception_data.get(0, {}).get(
                        "blocked_by_high_value", False
                    )
                    if _revel_switch_interception_data.get(0)
                    else False,
                    _revel_switch_interception_data.get(1, {}).get(
                        "blocked_by_high_value", False
                    )
                    if _revel_switch_interception_data.get(1)
                    else False,
                ],
                revealed_switch_rejected_worse_other_threat=[
                    _revel_switch_interception_data.get(0, {}).get(
                        "worse_other_threat", False
                    )
                    if _revel_switch_interception_data.get(0)
                    else False,
                    _revel_switch_interception_data.get(1, {}).get(
                        "worse_other_threat", False
                    )
                    if _revel_switch_interception_data.get(1)
                    else False,
                ],
                revealed_switch_post_turn_damage_taken=[None, None],
                revealed_switch_post_turn_survived=[None, None],
                revealed_switch_predicted_move_used=["", ""],
                revealed_switch_prediction_correct=[None, None],
                revealed_switch_prediction_wrong=[None, None],
                our_type_immune_move_selected=our_type_immune_move_selected_list,
                our_type_immune_only_legal=our_type_immune_only_legal_list,
                our_type_immune_move_avoided=our_type_immune_move_avoided_list,
                opponent_type_immune_move_selected=opponent_type_immune_move_selected_list,
                our_type_immune_attacker=our_type_immune_attacker_list,
                our_type_immune_move=our_type_immune_move_list,
                our_type_immune_target=our_type_immune_target_list,
                our_type_immune_target_types=our_type_immune_target_types_list,
                our_type_immune_reason=our_type_immune_reason_list,
                known_ability_resolution_source=known_ability_resolution_source_list,
                deterministic_singleton_ability_used=deterministic_singleton_ability_used_list,
                deterministic_singleton_ability=deterministic_singleton_ability_list,
                deterministic_singleton_target_species=deterministic_singleton_target_species_list,
                singleton_ability_hard_block_avoided=singleton_ability_hard_block_avoided_list,
                singleton_ground_into_levitate_selected=singleton_ground_into_levitate_selected_list,
                singleton_ability_conflict_detected=singleton_ability_conflict_detected_list,
                singleton_ability_suppressed=singleton_ability_suppressed_list,
                singleton_ability_suppression_reason=singleton_ability_suppression_reason_list,
                singleton_only_legal_action=singleton_only_legal_action_list,
                priority_move_field_blocked=priority_move_field_blocked_list,
                priority_move_block_reason=priority_move_block_reason_list,
                priority_move_selected_into_psychic_terrain=priority_move_selected_into_psychic_terrain_list,
                sucker_punch_selected_into_psychic_terrain=sucker_punch_selected_into_psychic_terrain_list,
                priority_move_block_avoided=priority_move_block_avoided_list,
                priority_move_only_legal=priority_move_only_legal_list,
                priority_target_grounded=priority_target_grounded_list,
                priority_target_species=priority_target_species_list,
                priority_target_type_1=priority_target_type_1_list,
                priority_target_type_2=priority_target_type_2_list,
                priority_blocking_ability=priority_blocking_ability_list,
                priority_blocking_ability_source=priority_blocking_ability_source_list,
                singleton_levitate_opportunity_observed=singleton_levitate_opportunity_observed_list,
                singleton_ground_into_levitate_selected_observed=singleton_ground_into_levitate_selected_observed_list,
                singleton_hard_block_applied=singleton_hard_block_applied_list,
                singleton_blocked_candidate_observed=singleton_blocked_candidate_observed_list,
                singleton_selection_changed_by_safety=singleton_selection_changed_by_safety_list,
                singleton_resolution_source=singleton_resolution_source_list,
                # Phase 6.4.3a.3: Decision timing diagnostics
                decision_time_ms=((time.time() - _t_start) * 1000)
                if _timing_enabled
                else None,
                valid_order_time_ms=_t_valid_order if _timing_enabled else None,
                score_action_time_ms=_t_score_action if _timing_enabled else None,
                joint_scoring_time_ms=_t_joint_scoring if _timing_enabled else None,
                audit_postprocess_time_ms=((time.time() - _t_audit_start) * 1000)
                if _timing_enabled
                else None,
                score_action_call_count=_score_action_call_count
                if _timing_enabled
                else None,
                joint_order_count=_joint_order_count if _timing_enabled else None,
                config=self.config,
                # Phase 6.4.5: Stale target safety audit fields
                stale_target_selected=stale_target_selected,
                stale_target_avoided=stale_target_avoided,
                stale_target_same_target_expected_ko=stale_target_same_target_expected_ko,
                stale_target_caused_no_effect=stale_target_caused_no_effect,
                stale_target_caused_type_immune=stale_target_caused_type_immune,
                stale_target_first_slot=stale_target_first_slot_val,
                stale_target_first_move=stale_target_first_move,
                stale_target_first_target=stale_target_first_target,
                stale_target_second_slot=stale_target_second_slot_val,
                stale_target_second_move=stale_target_second_move,
                stale_target_second_intended_target=stale_target_second_intended_target,
                stale_target_fallback_target=stale_target_fallback_target,
                stale_target_reason=stale_target_reason,
                support_target_candidates=_support_target_candidates,
                anti_tr_target_debug=self._anti_tr_target_debug_per_battle.get(battle_tag, []) if hasattr(self, "_anti_tr_target_debug_per_battle") else [],
                support_target_candidate_blocked_slot0=_sup_blocked[0],
                support_target_candidate_blocked_slot1=_sup_blocked[1],
                support_target_selected_slot0=_sup_selected[0],
                support_target_selected_slot1=_sup_selected[1],
                support_target_avoided_slot0=_sup_avoided[0],
                support_target_avoided_slot1=_sup_avoided[1],
                support_target_only_legal_slot0=_sup_only_legal[0],
                support_target_only_legal_slot1=_sup_only_legal[1],
                support_target_move_id_slot0=_sup_move_id[0],
                support_target_move_id_slot1=_sup_move_id[1],
                support_target_intended_side_slot0=_sup_intended_side[0],
                support_target_intended_side_slot1=_sup_intended_side[1],
                support_target_actual_side_slot0=_sup_actual_side[0],
                support_target_actual_side_slot1=_sup_actual_side[1],
                support_target_target_position_slot0=_sup_target_position[0],
                support_target_target_position_slot1=_sup_target_position[1],
                support_target_target_species_slot0=_sup_target_species[0],
                support_target_target_species_slot1=_sup_target_species[1],
                support_target_block_reason_slot0=_sup_block_reason[0],
                support_target_block_reason_slot1=_sup_block_reason[1],
                support_target_classification_source_slot0=_sup_classification_source[0],
                support_target_classification_source_slot1=_sup_classification_source[1],
                support_target_blocked_candidate_score_slot0=_sup_blocked_candidate_score[0],
                support_target_blocked_candidate_score_slot1=_sup_blocked_candidate_score[1],
                support_target_safe_alternative_kind_slot0=_sup_safe_alt_kind[0],
                support_target_safe_alternative_kind_slot1=_sup_safe_alt_kind[1],
                support_target_safe_alternative_move_id_slot0=_sup_safe_alt_move_id[0],
                support_target_safe_alternative_move_id_slot1=_sup_safe_alt_move_id[1],
                support_target_safe_alternative_target_position_slot0=_sup_safe_alt_target_position[0],
                support_target_safe_alternative_target_position_slot1=_sup_safe_alt_target_position[1],
                support_target_wrong_side_selected_slot0=_sup_wrong_side_selected[0],
                support_target_wrong_side_selected_slot1=_sup_wrong_side_selected[1],
                # Phase BI-2D: compact switch counterfactual
                # sub-dict. Built from existing _vsw_*
                # locals (no new scoring, no candidate
                # table persistence). Slot 0 and slot 1
                # each carry chosen/best-switch/best-non-
                # switch/counterfactual/delta/reason.
                switch_counterfactual={
                    "slot0": assemble_switch_counterfactual_slot(
                        slot_idx=0,
                        voluntary_switch_candidate_table=(
                            _voluntary_switch_candidate_tables.get(0, [])
                        ),
                        selected_action_key=_vsw_selected_actions[0]
                        if len(_vsw_selected_actions) > 0
                        else "",
                        counterfactual_action_key=_vsw_counterfactual_actions[0]
                        if len(_vsw_counterfactual_actions) > 0
                        else ("", "", 0),
                        best_stay_score=_vsw_best_stay[0]
                        if len(_vsw_best_stay) > 0
                        else 0.0,
                        best_stay_action_key=_vsw_best_stay_action[0]
                        if len(_vsw_best_stay_action) > 0
                        else None,
                        selection_changed=(
                            _vsw_selection_changed[0]
                            if len(_vsw_selection_changed) > 0
                            else False
                        ),
                        reason_codes=_vsw_reason_codes[0]
                        if len(_vsw_reason_codes) > 0
                        else [],
                    ),
                    "slot1": assemble_switch_counterfactual_slot(
                        slot_idx=1,
                        voluntary_switch_candidate_table=(
                            _voluntary_switch_candidate_tables.get(1, [])
                        ),
                        selected_action_key=_vsw_selected_actions[1]
                        if len(_vsw_selected_actions) > 1
                        else "",
                        counterfactual_action_key=_vsw_counterfactual_actions[1]
                        if len(_vsw_counterfactual_actions) > 1
                        else ("", "", 0),
                        best_stay_score=_vsw_best_stay[1]
                        if len(_vsw_best_stay) > 1
                        else 0.0,
                        best_stay_action_key=_vsw_best_stay_action[1]
                        if len(_vsw_best_stay_action) > 1
                        else None,
                        selection_changed=(
                            _vsw_selection_changed[1]
                            if len(_vsw_selection_changed) > 1
                            else False
                        ),
                        reason_codes=_vsw_reason_codes[1]
                        if len(_vsw_reason_codes) > 1
                        else [],
                    ),
                    "joint_selection_changed": _vsw_joint_selection_changed,
                },
                # Phase 6.4.9: Voluntary switch quality fields
                voluntary_switch_decision_eligible=[
                    bool(_voluntary_switch_candidate_tables.get(0, [])),
                    bool(_voluntary_switch_candidate_tables.get(1, [])),
                ],
                voluntary_switch_selected=[
                    any(
                        c.get("selected")
                        for c in _voluntary_switch_candidate_tables.get(0, [])
                    ),
                    any(
                        c.get("selected")
                        for c in _voluntary_switch_candidate_tables.get(1, [])
                    ),
                ],
                voluntary_switch_selected_species=[
                    next(
                        (
                            c.get("species", "")
                            for c in _voluntary_switch_candidate_tables.get(0, [])
                            if c.get("selected")
                        ),
                        "",
                    ),
                    next(
                        (
                            c.get("species", "")
                            for c in _voluntary_switch_candidate_tables.get(1, [])
                            if c.get("selected")
                        ),
                        "",
                    ),
                ],
                voluntary_switch_selection_changed=_vsw_selection_changed,
                voluntary_switch_joint_selection_changed=_vsw_joint_selection_changed,
                voluntary_switch_counterfactual_action=_vsw_counterfactual_actions,
                voluntary_switch_selected_action=_vsw_selected_actions,
                voluntary_switch_candidate_table=[
                    _voluntary_switch_candidate_tables.get(0, []),
                    _voluntary_switch_candidate_tables.get(1, []),
                ],
                voluntary_switch_unnecessary_selected=_vsw_unnecessary,
                voluntary_switch_unsafe_candidate_selected=_vsw_unsafe,
                voluntary_switch_repeat_selected=_vsw_repeat,
                voluntary_switch_sacrifice_opportunity=_vsw_sac_opp,
                voluntary_switch_healthy_bench_preserved=_vsw_healthy,
                voluntary_switch_safer_candidate_available=_vsw_safer,
                voluntary_switch_active_species=_vsw_active_species,
                voluntary_switch_active_hp=_vsw_active_hp,
                voluntary_switch_best_stay_score=_vsw_best_stay,
                voluntary_switch_selected_active_risk=_vsw_sel_active_risk,
                voluntary_switch_selected_candidate_risk=_vsw_sel_cand_risk,
                 voluntary_switch_selected_risk_reduction=_vsw_sel_risk_red,
                 voluntary_switch_selected_score_adjustment=_vsw_sel_score_adj,
                 voluntary_switch_reason_codes=_vsw_reason_codes,
                 # V2l.1 — shared-engine identity,
                 # invocation, and preview metadata.
                 # The packaging is delegated to
                 # ``doubles_engine.audit_metadata.assemble_shared_engine_metadata``
                 # (Phase Ponytail Refactor Step 7E).
                 # Behavior preserved bit-for-bit, including
                 # the ``shared_engine_used`` derivation
                 # (True only when
                 # ``v2l1_invocation_id`` is non-empty AND
                 # ``v2l1_invocation_status == "completed"``)
                 # and the constant
                 # ``shared_engine_owner`` string.
                 **assemble_shared_engine_metadata(
                     runtime_mode=getattr(
                         self, "_runtime_mode", "random_doubles"
                     ),
                     concrete_player_class=getattr(
                         self,
                         "_concrete_player_class",
                         type(self).__name__,
                     ),
                     v2l1_invocation_id=getattr(
                         self, "_v2l1_invocation_id", None
                     ),
                     v2l1_invocation_status=getattr(
                         self, "_v2l1_invocation_status", None
                     ),
                     selected_four=getattr(
                         self, "_selected_four", None
                     ),
                     lead_2=getattr(self, "_lead_2", None),
                     back_2=getattr(self, "_back_2", None),
                     preview_policy=getattr(
                         self, "_preview_policy", None
                     ),
                 ),
                # V2l.1 — per-decision execution-derived
                # parity fields. These are read from the
                # live player attributes that the
                # ``choose_move`` body writes right
                # before this call. The packaging is
                # delegated to ``doubles_engine.audit_metadata``
                # (Phase Ponytail Refactor Step 7B).
                **assemble_v2l1_metadata(
                    v2l1_legal_keys_slot0=getattr(
                        self, "_v2l1_legal_keys_slot0", []
                    ),
                    v2l1_legal_keys_slot1=getattr(
                        self, "_v2l1_legal_keys_slot1", []
                    ),
                    v2l1_raw_scores_slot0=getattr(
                        self, "_v2l1_raw_scores_slot0", {}
                    ),
                    v2l1_raw_scores_slot1=getattr(
                        self, "_v2l1_raw_scores_slot1", {}
                    ),
                    v2l1_safety_blocks_slot0=getattr(
                        self,
                        "_v2l1_safety_blocks_slot0",
                        {},
                    ),
                    v2l1_safety_blocks_slot1=getattr(
                        self,
                        "_v2l1_safety_blocks_slot1",
                        {},
                    ),
                    v2l1_selected_joint_key=getattr(
                        self, "_v2l1_selected_joint_key", None
                    ),
                    v2l1_final_keys=getattr(
                        self, "_v2l1_final_keys", []
                    ),
                ),
                # Phase BI-1: V4a mechanic-aware audit
                # kwargs. Read from the per-turn snapshot
                # attrs populated right before this call.
                # The audit logger writes them to
                # ``turn_data`` but currently the live
                # JSONL only persists a subset (see
                # logger ``_build_live_decision_event``).
                # No scoring or action selection change.
                # Note: V4a raw_scores dicts are not
                # passed because their 4-tuple keys
                # cannot be JSON-serialized. Legal keys
                # and final keys are passed as lists of
                # 4-tuples (JSON-serializable).
                v4a_legal_action_keys_slot0=getattr(
                    self, "_v4a_legal_keys_slot0", []
                ),
                v4a_legal_action_keys_slot1=getattr(
                    self, "_v4a_legal_keys_slot1", []
                ),
                v4a_selected_joint_key=getattr(
                    self, "_v4a_selected_joint_key", None
                ),
                v4a_final_action_keys=getattr(
                    self, "_v4a_final_keys", []
                ),
                # Phase RL-DATA-3a.2: pass live move
                # metadata from the audit path so the
                # v1.1 emission prefers live poke-env
                # ``Move`` / order data over the
                # static fallback. The helper is
                # observational only: it never changes
                # scoring or selected actions. If the
                # helper fails, ``log_turn_decision``
                # still works (it just gets a ``None``
                # override). The v1.0 audit logging
                # path is unchanged.
                move_metadata_map_override=(
                    self._v1_1_live_move_metadata_for_audit(
                        battle,
                        valid_orders,
                    )
                ),
            )

        return best_joint

    def _v1_1_live_move_metadata_for_audit(
        self, battle, valid_orders,
    ):
        """Phase RL-DATA-3a.2: collect live move
        metadata for the v1.1 audit override path.

        Returns a dict mapping normalized move id to
        a metadata dict. The audit logger's
        ``_populate_v1_1_move_metadata_map`` reads
        this dict first before falling back to the
        static resolver.

        The helper is wrapped in try/except so a
        failure here cannot break the bot's
        choose_move path. A failure returns
        ``None`` (the audit logger treats ``None``
        as "no override", i.e., use the static
        fallback).
        """
        try:
            from doubles_engine.move_metadata import (
                collect_live_move_metadata,
            )
            v4a_legal = (
                list(
                    getattr(self, "_v4a_legal_keys_slot0", [])
                    or []
                )
                + list(
                    getattr(self, "_v4a_legal_keys_slot1", [])
                    or []
                )
            )
            return collect_live_move_metadata(
                battle=battle,
                valid_orders=valid_orders,
                v4a_legal_keys=v4a_legal,
            )
        except Exception:
            return None

    @staticmethod
    def _v2l1_action_key_to_str(action_key) -> str:
        """V2l.1 — convert a ``_order_action_key``
        tuple into a JSON-serializable string. Used so
        the audit logger can persist action keys
        without storing non-serializable
        ``BattleOrder`` objects.

        ponytail: thin shim that delegates to
        ``doubles_engine.audit_metadata.v2l1_action_key_to_str``.
        Behavior preserved bit-for-bit.
        """
        from doubles_engine.audit_metadata import (
            v2l1_action_key_to_str as _impl,
        )
        return _impl(action_key)

    @classmethod
    def _v2l1_action_key_to_str_map(cls, d: dict) -> dict:
        """V2l.1 — map every key in ``d`` to a string
        for JSON serialization.

        ponytail: thin shim that delegates to
        ``doubles_engine.audit_metadata.v2l1_action_key_to_str_map``.
        """
        from doubles_engine.audit_metadata import (
            v2l1_action_key_to_str_map as _impl,
        )
        return _impl(d)

    @classmethod
    def _v2l1_joint_key_to_str(cls, joint_key) -> Optional[str]:
        """V2l.1 — convert a joint key tuple pair into
        a single string for JSON serialization.

        ponytail: thin shim that delegates to
        ``doubles_engine.audit_metadata.v2l1_joint_key_to_str``.
        """
        from doubles_engine.audit_metadata import (
            v2l1_joint_key_to_str as _impl,
        )
        return _impl(joint_key)

    def _battle_finished_callback(self, battle: AbstractBattle):
        clear_observed_form_state(getattr(battle, "battle_tag", ""))
        if self.custom_logger:
            if battle.won is True:
                winner = self.username
            elif battle.won is False:
                opp_name = getattr(battle, "opponent_username", None)
                if not opp_name:
                    try:
                        players = getattr(battle, "players", None)
                        if players:
                            opp_name = (
                                players[1]
                                if players[0] == self.username
                                else players[0]
                            )
                    except Exception:
                        pass
                winner = opp_name or "Opponent"
            else:
                winner = "Tie / Unknown"

            self.custom_logger.save_battle(
                battle_tag=getattr(battle, "battle_tag", "Unknown"),
                winner=winner,
                total_turns=getattr(battle, "turn", 0),
            )

        if self.audit_logger:
            if battle.won is True:
                winner = self.username
            elif battle.won is False:
                opp_name = getattr(battle, "opponent_username", None)
                if not opp_name:
                    try:
                        players = getattr(battle, "players", None)
                        if players:
                            opp_name = (
                                players[1]
                                if players[0] == self.username
                                else players[0]
                            )
                    except Exception:
                        pass
                winner = opp_name or "Opponent"
            else:
                winner = "Tie / Unknown"

            self.audit_logger.save_battle(
                battle_tag=getattr(battle, "battle_tag", "Unknown"),
                winner=winner,
                battle=battle,
            )

            # PLANNER-SPREAD-3d: clean up player ref after
            # the battle is saved (avoid memory leak).
            DoublesDecisionAuditLogger._battle_player_refs.pop(
                getattr(battle, "battle_tag", "Unknown"), None
            )

        bt = getattr(battle, "battle_tag", "")
        # History is keyed by (battle_tag, slot) tuples
        for key in list(self._voluntary_switch_history.keys()):
            if isinstance(key, tuple) and len(key) >= 1 and key[0] == bt:
                del self._voluntary_switch_history[key]
        self._voluntary_switch_quality_data.pop(bt, None)
        self._voluntary_switch_adjustment_applied.pop(bt, None)
        self._voluntary_switch_penalized.pop(bt, None)
