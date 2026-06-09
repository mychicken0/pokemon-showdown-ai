import asyncio
import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Union
from poke_env.player import Player
from poke_env import AccountConfiguration
from poke_env.battle.abstract_battle import AbstractBattle
from poke_env.battle.double_battle import DoubleBattle
from poke_env.battle.pokemon import Pokemon
from poke_env.battle.move import Move
from poke_env.battle.target import Target
from poke_env.player.battle_order import (
    BattleOrder,
    DoubleBattleOrder,
    SingleBattleOrder,
    PassBattleOrder,
    DefaultBattleOrder
)
from doubles_battle_logger import DoublesBattleLogger
from doubles_decision_audit_logger import DoublesDecisionAuditLogger
import ability_rules
import meta_model
import random_set_model

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
    rs_enable_protect_overcommit_penalty: bool = True   # Rule 1: penalize joint double-target when Protect likely
    rs_enable_fakeout_bonus: bool = True                 # Rule 2: Protect bonus when opponent likely has Fake Out
    rs_enable_priority_bonus: bool = True                # Rule 3: Protect bonus when opponent has priority + we are low HP
    rs_enable_spread_bonus: bool = True                  # Rule 4: Protect bonus when opponent has spread + we are low HP
    rs_enable_setup_targeting: bool = True               # Rule 5: small targeting bonus when opponent likely has setup move
    rs_enable_speed_control_bonus: bool = True           # Rule 6: Protect bonus when opponent has speed control + we are low HP
    # -- Per-rule thresholds (overrides random_set_probability_threshold if > 0) --
    rs_protect_threshold: float = 0.0    # 0 = use global threshold
    rs_fakeout_threshold: float = 0.0
    rs_priority_threshold: float = 0.0
    rs_spread_threshold: float = 0.0
    rs_setup_threshold: float = 0.0
    rs_speed_control_threshold: float = 0.0
    # -- Per-rule deltas (0 = use built-in defaults) --
    rs_protect_overcommit_delta: float = 0.0   # built-in: -12
    rs_fakeout_protect_delta: float = 0.0      # built-in: +18
    rs_priority_protect_delta: float = 0.0     # built-in: +20
    rs_spread_protect_delta: float = 0.0       # built-in: +12
    rs_setup_targeting_delta: float = 0.0      # built-in: +8
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

    # Phase 6.4.4: Forced Switch Replacement Safety (disabled by default)
    enable_forced_switch_replacement_safety: bool = False
    forced_switch_super_effective_penalty: float = 90.0
    forced_switch_quad_weak_penalty: float = 180.0
    forced_switch_double_threat_penalty: float = 120.0
    forced_switch_resistance_bonus: float = 25.0
    forced_switch_immunity_bonus: float = 35.0
    forced_switch_low_hp_penalty: float = 30.0
    forced_switch_fainted_or_unavailable_penalty: float = 9999.0

    # Phase 6.4.5: Stale Target / Retarget Immunity Safety
    enable_stale_target_after_ally_ko_safety: bool = False
    stale_target_after_ally_ko_penalty: float = 120.0
    stale_target_type_immune_penalty: float = 250.0


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
        if is_status_str == "STATUS" and getattr(attacker, "ability", None) == "prankster":
            priority += 1
            
    move_type = getattr(move, "type", None)
    if move_type:
        m_type = move_type.name.upper() if hasattr(move_type, "name") else str(move_type).upper()
        if m_type == "FLYING" and getattr(attacker, "ability", None) == "galewings":
            if getattr(attacker, "current_hp_fraction", 0) == 1.0:
                priority += 1
                
    result["priority"] = priority
    result["is_priority_move"] = (priority > 0)
    
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
            if opp_ability in ("armortail", "queenlymajesty", "dazzling") and not res["is_currently_suppressed"]:
                blocking_ability = opp_ability
                blocking_source = res["source"]
                break
                
    if blocking_ability:
        result["known_side_blocking_ability"] = True
        result["blocking_ability"] = blocking_ability
        result["blocking_ability_source"] = blocking_source

    is_opponent = (intended_target in battle.opponent_active_pokemon)
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
                suffix = "".join(c for c in str(value).split(":", 1)[1].lower() if c.isalnum())
                if suffix:
                    names.add(suffix)
    return names


def _pokemon_is_on_our_team(pokemon, battle) -> bool:
    if not pokemon or not battle:
        return False
    for collection_name in ("active_pokemon", "team"):
        collection = getattr(battle, collection_name, None)
        values = collection.values() if isinstance(collection, dict) else (collection or [])
        if any(mon is pokemon for mon in values if mon):
            return True
    return False


def get_known_ability(pokemon, battle=None) -> str | None:
    if not pokemon:
        return None
    try:
        ability = _normalize_ability_name(getattr(pokemon, "ability", None))
        replay_data = getattr(battle, "_replay_data", None) if battle is not None else None
        if battle is None or replay_data is None or getattr(battle, "battle_tag", None) == "test" or _pokemon_is_on_our_team(pokemon, battle):
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
                name == subject_norm or subject_norm.endswith(name)
                for name in names
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
                        revealed_ab = _normalize_ability_name(lower.split("ability:", 1)[1])
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


def is_gravity_active(battle) -> bool:
    try:
        for field in getattr(battle, "fields", {}) or {}:
            field_name = getattr(field, "name", str(field))
            if _normalize_ability_name(field_name) == "gravity":
                return True
    except Exception:
        pass
    return False


def get_max_type_threat(our_active, opponent, battle=None) -> float:
    """Get the maximum type effectiveness of any of the opponents  types against our active.
    
    Uses both type_1 and type_2 of the opponent. Returns the max multiplier.
    Never calculates from type_1 alone."""
    if not our_active or not opponent:
        return 0.0
    try:
        best = 0.0
        opp_type_1 = getattr(opponent, "type_1", None)
        opp_type_2 = getattr(opponent, "type_2", None)
        for t in (opp_type_1, opp_type_2):
            if t is None:
                continue
            try:
                mult = our_active.damage_multiplier(t)
                if mult > best:
                    best = mult
            except Exception:
                pass
        return best
    except Exception:
        return 0.0


DYNAMIC_TYPE_MOVES = {
    "aurawheel": {
        "attacker_base_species": "morpeko",
        "form_map": {
            "morpeko": "ELECTRIC",
            "morpekohangry": "DARK",
        },
    },
}


def resolve_effective_move_type(move, attacker=None, battle=None) -> dict:
    """Resolve the effective move type accounting for dynamic form changes.

    Returns dict with: declared_type, effective_type, source, dynamic_applied,
    observed_form. Uses attacker observable species - never turn parity.
    """
    result = {
        "declared_type": "",
        "effective_type": "",
        "source": "static",
        "dynamic_applied": False,
        "observed_form": "",
    }

    declared = _get_declared_move_type(move)
    result["declared_type"] = declared

    if not declared:
        return result

    move_id = ""
    if move is not None:
        if hasattr(move, "id") and move.id:
            move_id = move.id.lower().replace(" ", "").replace("-", "").replace("_", "")
        elif isinstance(move, str):
            move_id = move.lower().replace(" ", "").replace("-", "").replace("_", "")

    if move_id in DYNAMIC_TYPE_MOVES and attacker:
        config = DYNAMIC_TYPE_MOVES[move_id]
        attacker_base = config["attacker_base_species"]
        attacker_species = getattr(attacker, "species", "")
        if attacker_species and attacker_base in attacker_species.lower().replace("-", "").replace("_", ""):
            form_key = attacker_species.lower().replace("-", "").replace("_", "").strip()
            form_map = config["form_map"]
            if form_key in form_map:
                result["effective_type"] = form_map[form_key]
                result["source"] = f"dynamic_form:{form_key}"
                result["dynamic_applied"] = True
                result["observed_form"] = attacker_species
                return result

    result["effective_type"] = declared
    return result


def _get_declared_move_type(move) -> str:
    """Extract declared move.type as uppercase string."""
    if move is None:
        return ""
    move_type = getattr(move, "type", None)
    if move_type is not None:
        if hasattr(move_type, "name"):
            return move_type.name.upper()
        return str(move_type).upper()
    if isinstance(move, str):
        return move.upper()
    return ""


def get_effective_move_type(move, attacker=None, battle=None) -> str:
    """Compatibility wrapper: return effective type string."""
    return resolve_effective_move_type(move, attacker, battle)["effective_type"]


def resolve_known_ability(pokemon, battle=None, config=None) -> dict:
    """Resolve the known ability of a Pokemon.
    
    Returns:
        dict with keys: ability, source, possible_abilities, is_deterministic,
        is_currently_suppressed, suppression_reason
    """
    result = {
        "ability": None,
        "source": "unknown",
        "possible_abilities": [],
        "is_deterministic": False,
        "is_currently_suppressed": False,
        "suppression_reason": "",
    }
    
    if not pokemon:
        return result
    
    # 1. Check if this is our own team's Pokemon (always known)
    if _pokemon_is_on_our_team(pokemon, battle):
        result["ability"] = _normalize_ability_name(getattr(pokemon, "ability", None))
        result["source"] = "our_team_known"
        result["is_deterministic"] = True
        return result
    
    # 2. Check explicit protocol reveal
    revealed = get_known_ability(pokemon, battle)
    if revealed:
        result["ability"] = revealed
        result["source"] = "protocol_revealed"
        result["is_deterministic"] = True
        return result
    
    # 3. Check for temporary ability changes (Trace, Skill Swap, etc.)
    temp_ability = getattr(pokemon, "temporary_ability", None)
    if temp_ability:
        norm = _normalize_ability_name(temp_ability)
        if norm:
            result["ability"] = norm
            result["source"] = "temporary_changed"
            result["is_deterministic"] = True
            return result
    
    # 4. Check for Gastro Acid suppression
    # (would be tracked as a status condition)
    status = getattr(pokemon, "status", None)
    if status and _normalize_ability_name(str(status)) == "gastroacid":
        result["is_currently_suppressed"] = True
        result["suppression_reason"] = "gastro_acid"
    
    # 5. Check for Neutralizing Gas on field
    if battle:
        fields = getattr(battle, "fields", {}) or {}
        for field in fields:
            fname = getattr(field, "name", str(field)) if hasattr(field, "name") else str(field)
            if _normalize_ability_name(fname) == "neutralizinggas":
                result["is_currently_suppressed"] = True
                result["suppression_reason"] = "neutralizing_gas"
                break
    
    # 6. Deterministic singleton deduction (only when flag enabled)
    allow_singleton = False
    if config:
        allow_singleton = getattr(config, "ability_hard_safety_allow_singleton_deduction", False)
    
    if allow_singleton and not result["is_currently_suppressed"]:
        try:
            possible = getattr(pokemon, "possible_abilities", None)
            if possible is not None:
                norm_possible = normalize_possible_abilities(possible)
                result["possible_abilities"] = norm_possible
                
                # Check if exactly one distinct ability
                if len(norm_possible) == 1:
                    the_ability = norm_possible[0]
                    current_ability = _normalize_ability_name(getattr(pokemon, "ability", None))
                    
                    # pokemon.ability should be empty or match the singleton
                    if not current_ability or current_ability == the_ability:
                        result["ability"] = the_ability
                        result["source"] = "deterministic_singleton"
                        result["is_deterministic"] = True
        except Exception:
            pass
    
    return result


def ability_hard_blocks_move(move, attacker, target, battle=None, config=None) -> tuple[bool, str]:
    if not target or not move:
        return False, ""
    try:
        # Use resolve_known_ability to get ability (supports singleton deduction)
        resolution = resolve_known_ability(target, battle, config)
        t_ability = resolution["ability"]
        if not t_ability:
            return False, ""

        if attacker_ignores_target_ability(attacker, battle):
            return False, ""

        move_id = getattr(move, "id", "").lower()
        m_type = get_effective_move_type(move, attacker, battle)

        flags = getattr(move, "flags", {})

        # 1. Levitate:
        if t_ability == "levitate" and m_type == "GROUND":
            is_grounded = False
            if is_gravity_active(battle):
                is_grounded = True
            elif move_id == "thousandarrows":
                is_grounded = True
            else:
                # Check Smack Down in battle fields (for unit tests)
                if battle:
                    for field in getattr(battle, "fields", {}) or {}:
                        field_name = getattr(field, "name", str(field))
                        if _normalize_ability_name(field_name) == "smackdown":
                            is_grounded = True
                            break
                # Also check volatile status on target
                if not is_grounded and target:
                    for attr in ("effects", "status", "volatiles"):
                        val = getattr(target, attr, None)
                        if val:
                            if isinstance(val, dict):
                                if any("smackdown" in str(k).lower() for k in val.keys()):
                                    is_grounded = True
                                    break
                            elif isinstance(val, (list, tuple, set)):
                                if any("smackdown" in str(item).lower() for item in val):
                                    is_grounded = True
                                    break
                            elif "smackdown" in str(val).lower():
                                is_grounded = True
                                break
            if is_grounded:
                return False, ""
            return True, "ground_into_levitate"

        # 2. Earth Eater: Ground immunity
        if t_ability == "eartheater" and m_type == "GROUND":
            return True, "ground_into_eartheater"

        # 3. Water Absorb: Water immunity
        if t_ability == "waterabsorb" and m_type == "WATER":
            return True, "water_into_waterabsorb"

        # 4. Storm Drain: Water immunity
        if t_ability == "stormdrain" and m_type == "WATER":
            return True, "water_into_stormdrain"

        # 5. Dry Skin: Water immunity
        if t_ability == "dryskin" and m_type == "WATER":
            return True, "water_into_dryskin"

        # 6. Volt Absorb: Electric immunity
        if t_ability == "voltabsorb" and m_type == "ELECTRIC":
            return True, "electric_into_voltabsorb"

        # 7. Motor Drive: Electric immunity
        if t_ability == "motordrive" and m_type == "ELECTRIC":
            return True, "electric_into_motordrive"

        # 8. Lightning Rod: Electric immunity
        if t_ability == "lightningrod" and m_type == "ELECTRIC":
            return True, "electric_into_lightningrod"

        # 9. Flash Fire: Fire immunity
        if t_ability == "flashfire" and m_type == "FIRE":
            return True, "fire_into_flashfire"

        # 10. Well-Baked Body: Fire immunity
        if t_ability == "wellbakedbody" and m_type == "FIRE":
            return True, "fire_into_wellbakedbody"

        # 11. Sap Sipper: Grass immunity
        if t_ability == "sapsipper" and m_type == "GRASS":
            return True, "grass_into_sapsipper"

        # Optional blocks
        if t_ability == "soundproof" and "sound" in flags:
            return True, "sound_into_soundproof"
        if t_ability == "bulletproof" and "bullet" in flags:
            return True, "bullet_into_bulletproof"
        if t_ability == "damp" and move_id in ("explosion", "selfdestruct", "mindblown", "mistyexplosion"):
            return True, "explosion_into_damp"

    except Exception:
        pass
    return False, ""

def direct_known_absorb_blocks_move(move, attacker, target, battle=None, order=None) -> tuple[bool, str]:
    if not move or not target:
        return False, ""
    try:
        # damaging move only
        base_power = getattr(move, "base_power", 0)
        if base_power <= 0:
            return False, ""
            
        # Do not call is_opponent_spread_move(move) without order context.
        # Gate direct safety using order context.
        if order is not None and is_opponent_spread_move(move, order):
            return False, ""
            
        # ALLOWLIST: protocol-revealed-only direct absorb check
        blocks, reason = ability_hard_blocks_move(move, attacker, target, battle, config=None)
        if blocks:
            t_ability = get_known_ability(target, battle)
            if t_ability in (
                "waterabsorb",
                "stormdrain",
                "dryskin",
                "voltabsorb",
                "motordrive",
                "lightningrod",
                "flashfire",
                "wellbakedbody",
                "sapsipper"
            ):
                return True, reason
    except Exception:
        pass
    return False, ""

def ability_redirects_single_target_move(
    move, intended_target, opponent_targets, attacker=None, battle=None
) -> tuple[bool, str]:
    if not move or not intended_target:
        return False, ""
    try:
        if is_opponent_spread_move(move) or attacker_ignores_target_ability(attacker, battle):
            return False, ""
        move_id = getattr(move, "id", "").lower()
        m_type = ""
        m_type_obj = getattr(move, "type", None)
        if m_type_obj:
            m_type = m_type_obj.name.upper() if hasattr(m_type_obj, "name") else str(m_type_obj).upper()

        for opp in opponent_targets:
            if opp and opp != intended_target and not getattr(opp, "fainted", False):
                opp_ability = get_known_ability(opp, battle)
                if not opp_ability:
                    continue
                if m_type == "WATER" and opp_ability == "stormdrain":
                    return True, "redirected_by_stormdrain"
                if m_type == "ELECTRIC" and opp_ability == "lightningrod":
                    return True, "redirected_by_lightningrod"
    except Exception:
        pass
    return False, ""

def ally_ability_makes_safe(ally, move, battle=None) -> tuple[bool, str]:
    if not ally or not move:
        return False, ""
    try:
        ally_ab = get_known_ability(ally, battle)
        if not ally_ab:
            return False, ""
        if ally_ab == "telepathy":
            return True, "telepathy"

        move_id = getattr(move, "id", "").lower()
        m_type = ""
        m_type_obj = getattr(move, "type", None)
        if m_type_obj:
            m_type = m_type_obj.name.upper() if hasattr(m_type_obj, "name") else str(m_type_obj).upper()

        if ally_ab == "levitate" and m_type == "GROUND" and move_id != "thousandarrows" and not is_gravity_active(battle):
            return True, "levitate"
        if ally_ab == "eartheater" and m_type == "GROUND":
            return True, "eartheater"
        if ally_ab in ("waterabsorb", "stormdrain", "dryskin") and m_type == "WATER":
            return True, ally_ab
        if ally_ab in ("voltabsorb", "lightningrod", "motordrive") and m_type == "ELECTRIC":
            return True, ally_ab
        if ally_ab in ("flashfire", "wellbakedbody") and m_type == "FIRE":
            return True, ally_ab
        if ally_ab == "sapsipper" and m_type == "GRASS":
            return True, "sapsipper"
    except Exception:
        pass
    return False, ""


def _ability_block_enabled(config, reason: str) -> bool:
    if not config or not getattr(config, "enable_ability_hard_safety_only", False):
        return False
    if reason in ("sound_into_soundproof", "bullet_into_bulletproof", "explosion_into_damp"):
        return False
    absorb_prefixes = ("water_into_", "electric_into_", "fire_into_", "grass_into_")
    if reason.startswith(absorb_prefixes):
        return bool(getattr(config, "ability_hard_safety_avoid_absorb", True))
    return True


def _order_action_key(order) -> tuple:
    """Normalized key for comparing two SingleBattleOrder objects.

    Returns (action_type, action_id, target) where action_type is 'move'
    or 'switch', action_id is the move id or Pokemon species, and target
    is the move target position (0 for switches).
    """
    if order is None:
        return ("none", "", 0)
    from poke_env.battle.double_battle import SingleBattleOrder
    if isinstance(order, SingleBattleOrder):
        inner = order.order
        if inner is None:
            return ("none", "", 0)
        if hasattr(inner, "id"):
            return ("move", inner.id, getattr(order, "move_target", 0))
        elif hasattr(inner, "species"):
            return ("switch", inner.species, 0)
    return ("unknown", str(order) if order is not None else "", 0)


def classify_only_legal(joint_orders, slot_idx, selected_order, safety_blocked=None) -> bool:
    """Production helper: True when the selected blocked action has no
    non-safety-blocked alternative for *slot_idx* across all joint orders.

    Args:
        joint_orders: list of joint orders
        slot_idx: 0 or 1
        selected_order: the actually selected order for this slot
        safety_blocked: dict mapping id(order) -> True for safety-blocked
            orders.  If None, treats no orders as blocked.

    Returns True only when every alternative for this slot is also
    safety-blocked (or there are no alternatives).  Two different blocked
    Ground actions still count as no safe alternative.
    """
    if safety_blocked is None:
        safety_blocked = {}

    sel_key = _order_action_key(selected_order)
    # If selected action is not blocked, only_legal is irrelevant
    if not safety_blocked.get(id(selected_order), False):
        return False

    for jo in joint_orders:
        order = jo.first_order if slot_idx == 0 else jo.second_order
        if order is None:
            continue
        order_key = _order_action_key(order)
        # Different action AND not safety-blocked => safe alternative exists
        if order_key != sel_key and not safety_blocked.get(id(order), False):
            return False

    return True


def _compute_order_safety_blocks(battle, config, valid_orders):
    """Canonical safety precomputation for all valid orders.

    Returns (_direct_absorb_blocked, _safety_blocked) dicts keyed by id(order).
    Used by both actual choose_move selection and pure counterfactual selection.
    """
    _direct_absorb_blocked = {}
    _direct_absorb_enabled = (
        getattr(config, "enable_ability_hard_safety_only", False)
        and getattr(config, "ability_hard_safety_direct_absorb_only", False)
    )
    if _direct_absorb_enabled:
        for slot_idx, orders in enumerate(valid_orders):
            for ord in orders:
                if ord and hasattr(ord.order, "base_power"):
                    t_pos = ord.move_target
                    if t_pos in (1, 2):
                        t_mon = battle.opponent_active_pokemon[t_pos - 1]
                        a_mon = battle.active_pokemon[slot_idx]
                        if t_mon and a_mon:
                            if not is_opponent_spread_move(ord.order, ord):
                                blocked, _ = direct_known_absorb_blocks_move(
                                    ord.order, a_mon, t_mon, battle, ord
                                )
                                if blocked:
                                    _direct_absorb_blocked[id(ord)] = True

    _safety_blocked = {}
    for slot_idx, orders in enumerate(valid_orders):
        if not orders:
            continue
        active_mon = battle.active_pokemon[slot_idx]
        if not active_mon:
            continue
        for ord in orders:
            if ord and hasattr(ord.order, "base_power"):
                move = ord.order
                target_pos = ord.move_target
                if target_pos in (1, 2):
                    target_mon = battle.opponent_active_pokemon[target_pos - 1]
                    if target_mon:
                        base_power = getattr(move, "base_power", 0)
                        category = getattr(move, "category", None)
                        category_name = getattr(category, "name", "STATUS")

                        is_blocked = False
                        if category_name == "STATUS" or base_power == 0:
                            if getattr(config, "enable_priority_field_hard_safety", False):
                                priority_res = evaluate_priority_move_legality(
                                    move, active_mon, target_mon, battle, config
                                )
                                if priority_res["blocked"]:
                                    is_blocked = True
                        else:
                            blocks = False
                            reason = ""
                            if getattr(config, "enable_ability_hard_safety_only", False):
                                blocks, reason = ability_hard_blocks_move(
                                    move, active_mon, target_mon, battle, config=config
                                )
                            applies = blocks and _ability_block_enabled(config, reason)

                            applies_direct = False
                            if (getattr(config, "enable_ability_hard_safety_only", False)
                                    and getattr(config, "ability_hard_safety_direct_absorb_only", False)):
                                if not is_opponent_spread_move(move, ord):
                                    blocks_direct, _ = direct_known_absorb_blocks_move(
                                        move, active_mon, target_mon, battle, ord
                                    )
                                    if blocks_direct:
                                        applies_direct = True

                            applies_priority = False
                            if getattr(config, "enable_priority_field_hard_safety", False):
                                priority_res = evaluate_priority_move_legality(
                                    move, active_mon, target_mon, battle, config
                                )
                                if priority_res["blocked"]:
                                    applies_priority = True

                            if applies or applies_direct or applies_priority:
                                is_blocked = True

                            if (not is_blocked
                                    and getattr(config, "enable_ability_hard_safety_only", False)
                                    and getattr(config, "ability_hard_safety_avoid_redirection", False)):
                                redirects, red_reason = ability_redirects_single_target_move(
                                    move, target_mon, battle.opponent_active_pokemon,
                                    active_mon, battle
                                )
                                if redirects:
                                    red_target = None
                                    for opp in battle.opponent_active_pokemon:
                                        if (opp and opp != target_mon
                                                and not getattr(opp, "fainted", False)):
                                            opp_ability = get_known_ability(opp, battle)
                                            if opp_ability in ("stormdrain", "lightningrod"):
                                                red_target = opp
                                                break
                                    if red_target:
                                        blocks_red, reason_red = ability_hard_blocks_move(
                                            move, active_mon, red_target, battle, config=config
                                        )
                                        if blocks_red and _ability_block_enabled(config, reason_red):
                                            is_blocked = True

                        if is_blocked:
                            _safety_blocked[id(ord)] = True

    _ally_redirect_blocked = {}
    _ally_redirect_blocked_meta = {}
    if getattr(config, "enable_known_ally_redirection_hard_safety", False):
        for slot_idx, orders in enumerate(valid_orders):
            for ord in orders:
                if ord and hasattr(ord.order, "base_power") and getattr(ord.order, "base_power", 0) > 0:
                    t_pos = ord.move_target
                    if t_pos in (1, 2):
                        ally_idx = 1 - slot_idx
                        ally = battle.active_pokemon[ally_idx] if ally_idx < len(battle.active_pokemon) else None
                        if ally and not getattr(ally, "fainted", False):
                            redirects, reason = ally_redirects_our_single_target_move(
                                ord.order, battle.active_pokemon[slot_idx], ally, battle
                            )
                            if redirects:
                                oid = id(ord)
                                _ally_redirect_blocked[oid] = True
                                target_opp = None
                                if len(battle.opponent_active_pokemon) > t_pos - 1:
                                    target_opp = battle.opponent_active_pokemon[t_pos - 1]
                                ally_ab = get_known_ability(ally, battle) or ""
                                _ally_redirect_blocked_meta[oid] = {
                                    "move_id": getattr(ord.order, "id", ""),
                                    "attacker_species": getattr(battle.active_pokemon[slot_idx], "species", ""),
                                    "target_species": getattr(target_opp, "species", "") if target_opp else "",
                                    "ally_species": getattr(ally, "species", "") if ally else "",
                                    "ally_ability": ally_ab,
                                    "reason": reason,
                                    "known_before_decision": bool(ally_ab),
                                }

    return _direct_absorb_blocked, _safety_blocked, _ally_redirect_blocked, _ally_redirect_blocked_meta


def get_spread_target_effectiveness_with_ability(move, attacker, opponent_targets, config, battle=None) -> dict:
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
                blocks, reason = ability_hard_blocks_move(move, attacker, opp, battle, config=config)
                if blocks and _ability_block_enabled(config, reason):
                    is_immune = True
                    
            if is_immune:
                immune_targets += 1
                immune_target_names.append(opp.species)
            else:
                damaged_targets += 1
                damaged_target_names.append(opp.species)
                
    all_targets_immune = (total_targets > 0 and immune_targets == total_targets)
    partial_immunity = (total_targets > 1 and immune_targets > 0 and damaged_targets > 0)
    
    return {
        "total_targets": total_targets,
        "immune_targets": immune_targets,
        "damaged_targets": damaged_targets,
        "immune_target_names": immune_target_names,
        "damaged_target_names": damaged_target_names,
        "all_targets_immune": all_targets_immune,
        "partial_immunity": partial_immunity
    }


def get_spread_ability_partial_immunity(move, attacker, opponent_targets, config, battle=None) -> bool:
    if not opponent_targets or not move:
        return False
    total_targets = 0
    ability_blocked_targets = 0
    non_ability_blocked_targets = 0
    for opp in opponent_targets:
        if opp:
            total_targets += 1
            blocks_flag, reason = ability_hard_blocks_move(move, attacker, opp, battle, config=config)
            if blocks_flag and _ability_block_enabled(config, reason):
                ability_blocked_targets += 1
            else:
                non_ability_blocked_targets += 1
    return total_targets > 1 and ability_blocked_targets > 0 and non_ability_blocked_targets > 0


def is_known_absorb_ability(ability_name: str) -> bool:
    if not ability_name:
        return False
    normalized = "".join(c for c in str(ability_name).lower() if c.isalnum())
    return normalized in (
        "waterabsorb", "stormdrain", "dryskin",
        "voltabsorb", "motordrive", "lightningrod",
        "flashfire", "wellbakedbody", "sapsipper"
    )


def is_alternative_safe_damaging_predicate(alt_order, active_mon, battle, config=None) -> bool:
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
        blocked, _ = ability_hard_blocks_move(alt_move, active_mon, alt_target, battle, config=config)
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
            if red_target and is_known_absorb_ability(get_known_ability(red_target, battle)):
                return False

    elif is_opponent_spread_move(alt_move, alt_order):
        opponents = [opp for opp in battle.opponent_active_pokemon if opp and not getattr(opp, "fainted", False)]
        if not opponents:
            return False
        any_hit = False
        for opp in opponents:
            opp_blocks, _ = ability_hard_blocks_move(alt_move, active_mon, opp, battle, config=config)
            opp_type_imm, _ = is_type_immune(alt_move, active_mon, opp, battle)
            if not opp_blocks and not opp_type_imm:
                any_hit = True
                break
        if not any_hit:
            return False
    else:
        return False

    return True


def is_alternative_safe_damaging(alt_order, idx, active_mon, battle, config, player) -> tuple[bool, float]:
    """Compatibility wrapper retained for any callers outside choose_move.
    Uses score_action to compute the score. For choose_move, prefer the
    canonical slot_scores path to avoid re-evaluation side effects.
    """
    if not is_alternative_safe_damaging_predicate(alt_order, active_mon, battle, config=config):
        return False, 0.0
    alt_score = player.score_action(alt_order, idx, battle, with_tiebreaker=False, is_selected=False, in_spread_check=True, config=config)
    if alt_score <= 0.0:
        return False, 0.0
    return True, alt_score


def is_type_immune(move, attacker, target, battle=None) -> tuple[bool, str]:
    try:
        # 1. Normalize move type -- use effective type for dynamic moves like Aura Wheel
        m_type = get_effective_move_type(move, attacker, battle)
        if not m_type:
            return False, ""

        # 2. Normalize target types
        t_types = []
        if target is not None:
            if hasattr(target, "types") and target.types:
                for t in target.types:
                    if t:
                        if hasattr(t, "name"):
                            t_types.append(t.name.upper().strip())
                        elif isinstance(t, str):
                            t_types.append(t.upper().strip())
                        else:
                            t_types.append(str(t).upper().strip())
            else:
                if hasattr(target, "type_1") and target.type_1:
                    t_1 = target.type_1
                    t_1_str = t_1.name if hasattr(t_1, "name") else str(t_1)
                    t_types.append(t_1_str.upper().strip())
                if hasattr(target, "type_2") and target.type_2:
                    t_2 = target.type_2
                    t_2_str = t_2.name if hasattr(t_2, "name") else str(t_2)
                    t_types.append(t_2_str.upper().strip())

        if not t_types:
            return False, ""

        # 3. Normalize attacker ability
        a_ability = None
        if attacker is not None:
            if hasattr(attacker, "ability") and attacker.ability:
                a_ability = attacker.ability
                if hasattr(a_ability, "name"):
                    a_ability = a_ability.name
            elif isinstance(attacker, str):
                a_ability = attacker
            
            if isinstance(a_ability, str):
                a_ability = a_ability.lower().replace(" ", "").replace("-", "").replace("_", "").strip()

        # 4. Check exceptions
        # Move ID exceptions
        move_id = ""
        if move is not None:
            if hasattr(move, "id") and move.id:
                move_id = move.id.lower().replace(" ", "").replace("-", "").replace("_", "").strip()
            elif isinstance(move, str):
                move_id = move.lower().replace(" ", "").replace("-", "").replace("_", "").strip()

        # Exception 1: Thousand Arrows can hit Flying targets.
        if move_id == "thousandarrows" and m_type == "GROUND" and "FLYING" in t_types:
            return False, ""

        # Exception 2: Scrappy / Mind's Eye allow Normal and Fighting to hit Ghost.
        if a_ability in ("scrappy", "mindseye") and m_type in ("NORMAL", "FIGHTING") and "GHOST" in t_types:
            return False, ""

        # Exception 3: Gravity allows Ground moves to hit Flying targets.
        if battle and hasattr(battle, "fields") and battle.fields:
            has_gravity = False
            for f in battle.fields:
                f_str = f.name.lower() if hasattr(f, "name") else str(f).lower()
                if "gravity" in f_str:
                    has_gravity = True
                    break
            if has_gravity and m_type == "GROUND" and "FLYING" in t_types:
                return False, ""

        # 5. Method 1: Use poke-env / target type effectiveness method if available and reliable
        if hasattr(target, "damage_multiplier"):
            try:
                mult = None
                if hasattr(move, "type"):
                    mult = target.damage_multiplier(move)
                else:
                    from poke_env.battle.pokemon_type import PokemonType
                    try:
                        p_type = PokemonType[m_type]
                        mult = target.damage_multiplier(p_type)
                    except Exception:
                        pass
                
                if mult is not None:
                    if mult == 0.0:
                        return True, f"[Mechanics] type immunity: {m_type} vs {', '.join(t_types)} -> score 0"
                    else:
                        return False, ""
            except Exception:
                pass

        # 6. Fallback Method: Hard-coded fallback table
        IMMUNITY_TABLE = {
            "NORMAL": {"GHOST"},
            "FIGHTING": {"GHOST"},
            "GHOST": {"NORMAL"},
            "GROUND": {"FLYING"},
            "ELECTRIC": {"GROUND"},
            "PSYCHIC": {"DARK"},
            "POISON": {"STEEL"},
            "DRAGON": {"FAIRY"}
        }

        if m_type in IMMUNITY_TABLE:
            immune_targets = IMMUNITY_TABLE[m_type]
            for t_type in t_types:
                if t_type in immune_targets:
                    return True, f"[Mechanics] type immunity: {m_type} vs {t_type} -> score 0"

        return False, ""

    except Exception:
        return False, ""


def get_self_stat_drop_penalty(attacker, move, expected_ko=False, has_reasonable_alternative=True) -> tuple[float, str]:
    try:
        # Normalize move ID
        move_id = ""
        if move is not None:
            if hasattr(move, "id") and move.id:
                move_id = move.id.lower().replace(" ", "").replace("-", "").replace("_", "").strip()
            elif isinstance(move, str):
                move_id = move.lower().replace(" ", "").replace("-", "").replace("_", "").strip()

        HARSH_DROP_MOVES = {"dracometeor", "overheat", "leafstorm", "fleurcannon", "psychoboost"}
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
            return 0.35, f"[Mechanics] self stat drop penalty for {move_id}: SpA={spa_boost} -> multiplier 0.35"
        elif move_id in LIGHT_DROP_MOVES:
            return 0.65, f"[Mechanics] self stat drop penalty for {move_id}: SpA={spa_boost} -> multiplier 0.65"

        return 1.0, ""
    except Exception:
        return 1.0, ""


def is_opponent_only_spread_move(move, order=None) -> bool:
    try:
        if move is not None:
            # Check target string directly
            target_str = getattr(move, "target", "")
            if isinstance(target_str, str):
                target_str_clean = target_str.lower().replace(" ", "").replace("_", "").replace("-", "")
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
                move_id_clean = move_id.lower().replace(" ", "").replace("-", "").replace("_", "")
                KNOWN_OPPONENT_ONLY_SPREAD = {
                    "hypervoice", "rockslide", "heatwave", "blizzard", "clangsour", "clangingscales",
                    "dazzlinggleam", "muddywater", "snarl", "expandforce", "makeitrain", "glare",
                    "icywind", "acidspray", "strugglebug", "waterspout", "eruption", "dragondarts"
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
                target_str_clean = target_str.lower().replace(" ", "").replace("_", "").replace("-", "")
                if target_str_clean in ("alladjacent", "all"):
                    return True
            # Check deduced target
            target_type = getattr(move, "deduced_target", None)
            if target_type is not None:
                target_str = str(target_type).upper()
                if any(x in target_str for x in ("ALLADJACENT", "ALL_ADJACENT", "ALL")) and "FOES" not in target_str:
                    return True
                    
            # Known ally-hitting spread move list fallback
            move_id = getattr(move, "id", "")
            if isinstance(move_id, str):
                move_id_clean = move_id.lower().replace(" ", "").replace("-", "").replace("_", "")
                KNOWN_ALLY_HITTING_SPREAD = {
                    "earthquake", "surf", "discharge", "mindblown", "teeterdance"
                }
                if move_id_clean in KNOWN_ALLY_HITTING_SPREAD:
                    return True
        return False
    except Exception:
        return False


def is_opponent_spread_move(move, order=None) -> bool:
    try:
        if is_opponent_only_spread_move(move, order) or is_ally_hitting_spread_move(move, order):
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
                target_str_clean = target_str.lower().replace(" ", "").replace("_", "").replace("-", "")
                if target_str_clean in ("alladjacent", "alladjacentfoes", "all"):
                    return True
                    
        return False
    except Exception:
        return False


def get_spread_target_effectiveness(move, attacker, opponent_targets, battle=None) -> dict:
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
                
    all_targets_immune = (total_targets > 0 and immune_targets == total_targets)
    partial_immunity = (total_targets > 1 and immune_targets > 0 and damaged_targets > 0)
    
    return {
        "total_targets": total_targets,
        "immune_targets": immune_targets,
        "damaged_targets": damaged_targets,
        "immune_target_names": immune_target_names,
        "damaged_target_names": damaged_target_names,
        "all_targets_immune": all_targets_immune,
        "partial_immunity": partial_immunity
    }


def evaluate_switch_candidate_type_safety(candidate, opponent_actives, config=None) -> dict:
    """Evaluate type safety of a switch candidate against visible opponents.

    Uses only currently visible Pokemon types and HP. No species-based move
    assumptions, random-set data, possible abilities, hidden moves, hidden
    items, or unrevealed information.

    For each opponent, calculates the maximum incoming multiplier among that
    opponent visible types as a conservative STAB-type exposure signal.

    Returns a dict with raw safety score, worst multiplier, per-opponent
    worst multipliers, threat counts, double-threat boolean, opponent threat
    type names, candidate HP fraction, and immunity/resistance counts.
    """
    result = {
        "raw_safety_score": 0.0,
        "worst_multiplier": 1.0,
        "per_opponent_worst_multipliers": [],
        "super_effective_threat_count": 0,
        "quad_weak_threat_count": 0,
        "resistant_threat_count": 0,
        "immune_threat_count": 0,
        "double_threat": False,
        "opponent_threat_type_names": [],
        "candidate_hp_fraction": 1.0,
    }

    if not candidate:
        return result

    # Get candidate types
    cand_type_1 = getattr(candidate, "type_1", None)
    cand_type_2 = getattr(candidate, "type_2", None)

    # Get candidate HP fraction
    hp_frac = getattr(candidate, "current_hp_fraction", 1.0)
    if hp_frac is None:
        hp_frac = 1.0
    result["candidate_hp_fraction"] = hp_frac

    # Get config penalties/bonuses
    se_penalty = getattr(config, "switch_candidate_super_effective_penalty", 80.0) if config else 80.0
    quad_penalty = getattr(config, "switch_candidate_quad_weak_penalty", 160.0) if config else 160.0
    double_penalty = getattr(config, "switch_candidate_double_threat_penalty", 100.0) if config else 100.0
    res_bonus = getattr(config, "switch_candidate_resistance_bonus", 20.0) if config else 20.0
    imm_bonus = getattr(config, "switch_candidate_immunity_bonus", 30.0) if config else 30.0
    low_hp_penalty = getattr(config, "switch_candidate_low_hp_penalty", 30.0) if config else 30.0

    raw_score = 0.0
    worst_mult = 1.0
    se_count = 0
    quad_count = 0
    res_count = 0
    imm_count = 0
    threat_types = []
    per_opp = []

    if not opponent_actives:
        result["raw_safety_score"] = raw_score
        result["worst_multiplier"] = worst_mult
        return result

    for opp in opponent_actives:
        if not opp:
            per_opp.append(1.0)
            continue

        opp_type_1 = getattr(opp, "type_1", None)
        opp_type_2 = getattr(opp, "type_2", None)

        # Calculate max incoming multiplier from opponents  visible types
        max_mult = 0.0
        opp_best_type = None

        for opp_type in (opp_type_1, opp_type_2):
            if opp_type is None:
                continue
            try:
                if cand_type_1 is not None:
                    mult1 = candidate.damage_multiplier(opp_type)
                    if mult1 > max_mult:
                        max_mult = mult1
                        opp_best_type = opp_type
            except Exception:
                if max_mult < 1.0:
                    max_mult = 1.0

        if max_mult == 0.0 and (opp_type_1 is None and opp_type_2 is None):
            max_mult = 1.0
        elif max_mult == 0.0 and cand_type_1 is None:
            max_mult = 1.0

        per_opp.append(max_mult)

        if max_mult > worst_mult:
            worst_mult = max_mult

        # Classify using ONLY the maximum multiplier per opponent
        if max_mult >= 4.0:
            quad_count += 1
            se_count += 1
            if opp_best_type and opp_best_type.name.title() not in threat_types:
                threat_types.append(opp_best_type.name.title())
        elif max_mult >= 2.0:
            se_count += 1
            if opp_best_type and opp_best_type.name.title() not in threat_types:
                threat_types.append(opp_best_type.name.title())
        elif max_mult == 0.0:
            imm_count += 1
        elif max_mult <= 0.5:
            res_count += 1

    raw_score -= se_count * se_penalty
    raw_score -= quad_count * quad_penalty
    raw_score += res_count * res_bonus
    raw_score += imm_count * imm_bonus

    # Double threat: both opponents threaten super-effective
    is_double_threat = se_count >= 2
    if is_double_threat:
        raw_score -= double_penalty

    # Low HP penalty
    if hp_frac <= 0.35:
        raw_score -= low_hp_penalty * (1.0 - hp_frac)

    result["raw_safety_score"] = raw_score
    result["worst_multiplier"] = worst_mult
    result["per_opponent_worst_multipliers"] = per_opp
    result["super_effective_threat_count"] = se_count
    result["quad_weak_threat_count"] = quad_count
    result["resistant_threat_count"] = res_count
    result["immune_threat_count"] = imm_count
    result["double_threat"] = is_double_threat
    result["opponent_threat_type_names"] = threat_types
    result["candidate_hp_fraction"] = hp_frac

    return result


def evaluate_forced_switch_replacement_safety(candidate, opponent_actives, battle=None, config=None) -> dict:
    """Evaluate forced switch replacement safety for a single candidate.

    Used ONLY for required replacement switches (after faint), NOT voluntary pivots.
    Uses only visible opponent types, HP, and already-revealed moves.
    Does NOT infer hidden moves, abilities, items, or species sets.

    Returns dict with:
      - score: float (higher is safer)
      - max_threat_multiplier: float
      - opponent_threat_count: int (opponents with SE threat)
      - quad_weak_count: int
      - resistance_count: int
      - immunity_count: int
      - low_hp_penalty_applied: bool
      - reasons: list[str]
    """
    result = {
        "score": 0.0,
        "max_threat_multiplier": 1.0,
        "opponent_threat_count": 0,
        "quad_weak_count": 0,
        "resistance_count": 0,
        "immunity_count": 0,
        "low_hp_penalty_applied": False,
        "reasons": [],
    }

    if not candidate:
        return result

    # Config penalties/bonuses
    se_penalty = getattr(config, "forced_switch_super_effective_penalty", 90.0) if config else 90.0
    quad_penalty = getattr(config, "forced_switch_quad_weak_penalty", 180.0) if config else 180.0
    double_penalty = getattr(config, "forced_switch_double_threat_penalty", 120.0) if config else 120.0
    res_bonus = getattr(config, "forced_switch_resistance_bonus", 25.0) if config else 25.0
    imm_bonus = getattr(config, "forced_switch_immunity_bonus", 35.0) if config else 35.0
    low_hp_penalty = getattr(config, "forced_switch_low_hp_penalty", 30.0) if config else 30.0
    fainted_penalty = getattr(config, "forced_switch_fainted_or_unavailable_penalty", 9999.0) if config else 9999.0

    # Check fainted/unavailable
    if getattr(candidate, "fainted", False):
        result["score"] = -fainted_penalty
        result["reasons"].append("fainted")
        return result

    hp_frac = getattr(candidate, "current_hp_fraction", 1.0)
    if hp_frac is None:
        hp_frac = 1.0

    # Get candidate types
    cand_type_1 = getattr(candidate, "type_1", None)
    cand_type_2 = getattr(candidate, "type_2", None)

    raw_score = 0.0
    worst_mult = 1.0
    se_count = 0
    quad_count = 0
    res_count = 0
    imm_count = 0
    threat_types = []

    if not opponent_actives:
        result["score"] = raw_score
        result["max_threat_multiplier"] = worst_mult
        return result

    for opp in opponent_actives:
        if not opp or getattr(opp, "fainted", False):
            continue

        opp_type_1 = getattr(opp, "type_1", None)
        opp_type_2 = getattr(opp, "type_2", None)

        # Calculate max incoming multiplier from opponents  visible types
        max_mult = 0.0
        opp_best_type = None

        for opp_type in (opp_type_1, opp_type_2):
            if opp_type is None:
                continue
            try:
                if cand_type_1 is not None:
                    mult = candidate.damage_multiplier(opp_type)
                    if mult > max_mult:
                        max_mult = mult
                        opp_best_type = opp_type
            except Exception:
                if max_mult < 1.0:
                    max_mult = 1.0

        if max_mult == 0.0 and (opp_type_1 is None and opp_type_2 is None):
            max_mult = 1.0
        elif max_mult == 0.0 and cand_type_1 is None:
            max_mult = 1.0

        if max_mult > worst_mult:
            worst_mult = max_mult

        # Classify
        if max_mult >= 4.0:
            quad_count += 1
            se_count += 1
            if opp_best_type and opp_best_type.name.title() not in threat_types:
                threat_types.append(opp_best_type.name.title())
        elif max_mult >= 2.0:
            se_count += 1
            if opp_best_type and opp_best_type.name.title() not in threat_types:
                threat_types.append(opp_best_type.name.title())
        elif max_mult == 0.0:
            imm_count += 1
        elif max_mult <= 0.5:
            res_count += 1

    # Apply penalties and bonuses
    raw_score -= se_count * se_penalty
    raw_score -= quad_count * quad_penalty
    raw_score += res_count * res_bonus
    raw_score += imm_count * imm_bonus

    # Double threat: both opponents threaten super-effective
    is_double_threat = se_count >= 2
    if is_double_threat:
        raw_score -= double_penalty
        result["reasons"].append("double_threat")

    if quad_count > 0:
        result["reasons"].append("quad_weak")

    # Low HP penalty
    if hp_frac <= 0.35:
        raw_score -= low_hp_penalty * (1.0 - hp_frac)
        result["low_hp_penalty_applied"] = True
        result["reasons"].append("low_hp")

    if se_count > 0:
        result["reasons"].append("super_effective_threat")

    result["score"] = raw_score
    result["max_threat_multiplier"] = worst_mult
    result["opponent_threat_count"] = se_count
    result["quad_weak_count"] = quad_count
    result["resistance_count"] = res_count
    result["immunity_count"] = imm_count

    return result


def summarize_negative_boosts(pokemon) -> dict:
    """Summarize current revealed boost stages for diagnostic purposes.

    Records negative stages from the Pokemons current boosts only.
    Does NOT alter scores -- diagnostic-only for Phase 6.4.2.
    """
    result = {
        "total_negative_stages": 0,
        "lowest_stage": 0,
        "offensive_negative_stages": 0,  # atk, spa
        "defensive_negative_stages": 0,  # def, spd
        "speed_negative_stage": 0,
        "severe_negative_boost": False,
        "was_switch": False,
    }

    if not pokemon:
        return result

    boosts = getattr(pokemon, "boosts", None)
    if not boosts or not isinstance(boosts, dict):
        return result

    total_neg = 0
    lowest = 0
    offensive_neg = 0
    defensive_neg = 0
    speed_neg = 0

    for stat in ("atk", "spa"):
        val = boosts.get(stat, 0)
        if val < 0:
            offensive_neg += abs(val)
            total_neg += abs(val)
            lowest = min(lowest, val)

    for stat in ("def", "spd"):
        val = boosts.get(stat, 0)
        if val < 0:
            defensive_neg += abs(val)
            total_neg += abs(val)
            lowest = min(lowest, val)

    spe_val = boosts.get("spe", 0)
    if spe_val < 0:
        speed_neg = abs(spe_val)
        total_neg += abs(spe_val)
        lowest = min(lowest, spe_val)

    result["total_negative_stages"] = total_neg
    result["lowest_stage"] = lowest
    result["offensive_negative_stages"] = offensive_neg
    result["defensive_negative_stages"] = defensive_neg
    result["speed_negative_stage"] = speed_neg
    result["severe_negative_boost"] = (lowest <= -3)

    return result


def classify_stat_drop_severity(boosts: dict, config, orders_slot: list) -> dict:
    """Classify stat-drop severity using config thresholds and available moves.

    Diagnostic-only.  Does NOT alter scores.  Uses only visible boosts and
    available move categories -- never infers from species.

    Returns dict with:
      - severe: bool (any category meets its threshold)
      - categories: list of "offensive"/"defensive"/"speed" strings
      - offensive: bool
      - defensive: bool
      - speed: bool
    """
    result = {
        "severe": False,
        "categories": [],
        "offensive": False,
        "defensive": False,
        "speed": False,
    }
    if not config or not getattr(config, "enable_stat_drop_switch_diagnostics", False):
        return result
    if not boosts or not isinstance(boosts, dict):
        return result

    off_thresh = getattr(config, "stat_drop_offensive_stage_threshold", -2)
    def_thresh = getattr(config, "stat_drop_defensive_stage_threshold", -2)
    spd_thresh = getattr(config, "stat_drop_speed_stage_threshold", -2)

    # Offensive: check if any available damaging move uses the dropped stat
    has_physical = False
    has_special = False
    for o in (orders_slot or []):
        if o and getattr(o, "order", None) is not None and getattr(getattr(o, "order", None), "base_power", 0) > 0:
            cat = getattr(o.order, "category", None)
            cat_name = getattr(cat, "name", "STATUS")
            if cat_name == "PHYSICAL" and getattr(o.order, "base_power", 0) > 0:
                has_physical = True
            elif cat_name == "SPECIAL" and getattr(o.order, "base_power", 0) > 0:
                has_special = True

    atk_val = boosts.get("atk", 0)
    spa_val = boosts.get("spa", 0)
    if (has_physical and atk_val <= off_thresh) or (has_special and spa_val <= off_thresh):
        result["offensive"] = True
        result["categories"].append("offensive")

    # Defensive
    def_val = boosts.get("def", 0)
    spd_val = boosts.get("spd", 0)
    if def_val <= def_thresh or spd_val <= def_thresh:
        result["defensive"] = True
        result["categories"].append("defensive")

    # Speed
    spe_val = boosts.get("spe", 0)
    if spe_val <= spd_thresh:
        result["speed"] = True
        result["categories"].append("speed")

    result["severe"] = len(result["categories"]) > 0
    return result


def evaluate_stat_drop_switch_pressure(active_mon, orders_slot, battle, config, player=None) -> dict:
    result = {
        "should_consider_switch": False,
        "categories": [],
        "offensive_drop": False,
        "defensive_drop": False,
        "speed_drop": False,
        "productive_action_available": False,
        "best_non_switch_score": 0.0,
        "switch_available": False,
        "active_hp_fraction": 0.0,
        "reasons": [],
        "stay_penalty": 0.0,
        "threshold_source": "",
    }

    if not active_mon or not config:
        return result
    if not getattr(config, "enable_stat_drop_switch_scoring", False):
        result["reasons"].append("scoring_disabled")
        return result

    boosts = getattr(active_mon, "boosts", None)
    if not boosts or not isinstance(boosts, dict):
        result["reasons"].append("no_boosts")
        return result

    off_thresh = getattr(config, "stat_drop_switch_offensive_stage_threshold", -1)
    def_thresh = getattr(config, "stat_drop_switch_defensive_stage_threshold", -2)
    spd_thresh = getattr(config, "stat_drop_switch_speed_stage_threshold", -2)

    has_physical = False
    has_special = False
    for o in (orders_slot or []):
        order_obj = getattr(o, "order", None)
        if order_obj is None:
            continue
        if getattr(order_obj, "base_power", 0) > 0:
            cat = getattr(order_obj, "category", None)
            cat_name = getattr(cat, "name", "STATUS")
            if cat_name == "PHYSICAL":
                has_physical = True
            elif cat_name == "SPECIAL":
                has_special = True

    atk_val = boosts.get("atk", 0)
    spa_val = boosts.get("spa", 0)
    def_val = boosts.get("def", 0)
    spd_val = boosts.get("spd", 0)
    spe_val = boosts.get("spe", 0)

    threshold_sources = []
    if (has_physical and atk_val <= off_thresh) or (has_special and spa_val <= off_thresh):
        result["offensive_drop"] = True
        result["categories"].append("offensive")
        threshold_sources.append(f"offensive_{off_thresh}")
    if def_val <= def_thresh or spd_val <= def_thresh:
        result["defensive_drop"] = True
        result["categories"].append("defensive")
        threshold_sources.append(f"defensive_{def_thresh}")
    if spe_val <= spd_thresh:
        result["speed_drop"] = True
        result["categories"].append("speed")
        threshold_sources.append(f"speed_{spd_thresh}")

    if not result["categories"]:
        result["reasons"].append("no_severe_drop")
        return result

    if len(threshold_sources) >= 2:
        result["threshold_source"] = "mixed"
    elif threshold_sources:
        result["threshold_source"] = threshold_sources[0]

    active_hp = getattr(active_mon, "current_hp_fraction", 1.0) or 1.0
    result["active_hp_fraction"] = active_hp
    if active_hp < config.stat_drop_switch_low_hp_block_threshold:
        result["reasons"].append("active_hp_below_low_hp_block")
        return result

    switch_count = 0
    has_protect = False
    has_damaging = False
    for o in (orders_slot or []):
        if not o:
            continue
        order_obj = getattr(o, "order", None)
        if order_obj is None:
            continue
        if getattr(order_obj, "species", None):
            switch_count += 1
            continue
        base_pw = getattr(order_obj, "base_power", 0)
        if base_pw > 0:
            has_damaging = True
        move_id = getattr(order_obj, "id", "").lower()
        if move_id in ("protect", "detect", "spikyshield", "kingsshield", "banefulbunker", "silktrap"):
            has_protect = True

    result["switch_available"] = switch_count > 0
    if not result["switch_available"]:
        result["reasons"].append("no_legal_switch")
        return result

    productive = False
    if player and battle and has_damaging:
        for o in (orders_slot or []):
            if not o:
                continue
            order_obj = getattr(o, "order", None)
            if order_obj is None:
                continue
            if getattr(order_obj, "base_power", 0) <= 0:
                continue
            target_pos = getattr(o, "move_target", None)
            if target_pos in (1, 2):
                opps = getattr(battle, "opponent_active_pokemon", [])
                if opps and len(opps) > target_pos - 1:
                    target_opp = opps[target_pos - 1]
                    if target_opp and not getattr(target_opp, "fainted", False):
                        try:
                            if player.check_move_will_ko(o.order, active_mon, target_opp, battle, config=config):
                                productive = True
                                result["reasons"].append("ko_action_available")
                                break
                            dmg = player.get_expected_damage(o.order, active_mon, target_opp, battle, config=config)
                            opp_max = player.estimate_opponent_max_hp(target_opp)
                            frac = getattr(config, "stat_drop_meaningful_damage_fraction", 0.25)
                            if opp_max > 0 and dmg / max(1.0, opp_max) >= frac:
                                productive = True
                                result["reasons"].append("meaningful_damage_available")
                                break
                        except Exception:
                            pass
    if has_protect:
        productive = True
        result["reasons"].append("protect_available")

    result["productive_action_available"] = productive
    if productive:
        result["reasons"].append("productive_action_suppresses_pressure")
        return result

    result["should_consider_switch"] = True

    penalty = 0.0
    if result["offensive_drop"]:
        penalty += config.stat_drop_switch_offensive_penalty
        result["reasons"].append("offensive_drop_penalty")
    if result["defensive_drop"]:
        penalty += config.stat_drop_switch_defensive_penalty
        result["reasons"].append("defensive_drop_penalty")
    if result["speed_drop"]:
        penalty += config.stat_drop_switch_speed_penalty
        result["reasons"].append("speed_drop_penalty")

    if active_hp < config.stat_drop_switch_min_active_hp:
        penalty = penalty * 0.5
        result["reasons"].append("low_hp_penalty_halved")

    result["stay_penalty"] = penalty + config.stat_drop_switch_unproductive_bonus
    result["reasons"].append("unproductive_stay_pressure")

    return result


def get_revealed_damaging_moves(opponent) -> list:
    """Get revealed damaging moves from an opponent.

    Uses only opponent.moves.values() -- never infers from species.
    """
    result = []
    if not opponent:
        return result
    moves = getattr(opponent, "moves", None)
    if not moves:
        return result
    for move in moves.values():
        try:
            if move is None:
                continue
            base_power = getattr(move, "base_power", 0)
            if not base_power or base_power <= 0:
                continue
            cat = getattr(move, "category", None)
            cat_name = getattr(cat, "name", "STATUS") if cat else "STATUS"
            if cat_name == "STATUS":
                continue
            result.append(move)
        except Exception:
            continue
    return result


def evaluate_revealed_move_incoming_risk(
    move, opponent, defender, battle=None
) -> dict:
    """Evaluate incoming risk of a revealed move against a defender.

    Uses defender.damage_multiplier(move) for combined dual-type calculation.
    """
    result = {
        "type_multiplier": 1.0,
        "base_power": 0,
        "accuracy": 1.0,
        "stab": False,
        "priority": 0,
        "is_spread": False,
        "incoming_pressure": 0.0,
        "classification": "neutral",
        "likely_ko_pressure": False,
    }
    if not move or not defender:
        return result

    try:
        base_power = getattr(move, "base_power", 0)
        result["base_power"] = base_power

        accuracy = getattr(move, "accuracy", None)
        if accuracy is None:
            result["accuracy"] = 1.0
        else:
            result["accuracy"] = accuracy / 100.0 if accuracy > 1 else float(accuracy)

        priority = getattr(move, "priority", 0)
        result["priority"] = priority

        target_type = getattr(move, "target", "")
        result["is_spread"] = target_type in ("allAdjacent", "allAdjacentFoes", "all")

        # Calculate type multiplier using defender.damage_multiplier
        mult = 1.0
        try:
            mult = defender.damage_multiplier(move)
        except Exception:
            try:
                move_type = getattr(move, "type", None)
                if move_type:
                    mult = defender.damage_multiplier(move_type)
            except Exception:
                mult = 1.0

        result["type_multiplier"] = mult

        # Check STAB based only on visible opponent types
        move_type = getattr(move, "type", None)
        if move_type and opponent:
            # Normalize move_type to string for comparison
            if hasattr(move_type, "name"):
                move_type_str = move_type.name
            else:
                move_type_str = str(move_type)
            opp_types = getattr(opponent, "types", [])
            if opp_types:
                for ot in opp_types:
                    ot_str = ot.name if hasattr(ot, "name") else str(ot)
                    if ot_str.upper() == move_type_str.upper():
                        result["stab"] = True
                        break

        # Classification
        if mult == 0.0:
            result["classification"] = "immune"
        elif mult <= 0.5:
            result["classification"] = "resisted"
        elif mult < 1.0:
            result["classification"] = "resisted"
        elif mult == 1.0:
            result["classification"] = "neutral"
        elif mult < 4.0:
            result["classification"] = "super-effective"
        else:
            result["classification"] = "quad-effective"

        # Rough incoming pressure score
        stab_mult = 1.5 if result["stab"] else 1.0
        incoming_pressure = base_power * mult * stab_mult * result["accuracy"]
        if priority > 0:
            incoming_pressure *= (1.0 + priority * 0.3)
        result["incoming_pressure"] = incoming_pressure

        # Likely KO pressure: quad-effective or super-effective with high power
        if mult >= 4.0:
            result["likely_ko_pressure"] = True
        elif mult >= 2.0 and base_power >= 70:
            result["likely_ko_pressure"] = True

    except Exception:
        pass

    return result


def estimate_revealed_move_target_likelihood(
    move, opponent, our_actives, battle=None
) -> dict:
    """Estimate how likely the opponent is to target each of our actives.

    Returns per-slot target likelihood weights.
    """
    result = {
        "slot_0_weight": 0.0,
        "slot_1_weight": 0.0,
        "is_spread": False,
        "threatening_slots": [],
    }

    if not move or not our_actives:
        return result

    target_type = getattr(move, "target", "")
    result["is_spread"] = target_type in ("allAdjacent", "allAdjacentFoes", "all")

    risks = []
    for slot_idx in range(2):
        active = our_actives[slot_idx] if slot_idx < len(our_actives) else None
        if not active:
            risks.append(0.0)
            continue
        risk_info = evaluate_revealed_move_incoming_risk(move, opponent, active, battle)
        risks.append(risk_info["incoming_pressure"])

    if result["is_spread"]:
        # Spread move: both slots get full weight
        for slot_idx in range(2):
            if risks[slot_idx] > 0:
                result[f"slot_{slot_idx}_weight"] = 1.0
                result["threatening_slots"].append(slot_idx)
    else:
        # Single-target move: prefer the more vulnerable active
        max_risk = max(risks) if risks else 0.0
        if max_risk > 0:
            config = None  # Will use defaults
            likely_w = 1.0
            tied_w = 0.5
            for slot_idx in range(2):
                if risks[slot_idx] == max_risk and max_risk > 0:
                    result[f"slot_{slot_idx}_weight"] = likely_w
                    result["threatening_slots"].append(slot_idx)
                elif risks[slot_idx] > 0 and risks[slot_idx] == max_risk:
                    result[f"slot_{slot_idx}_weight"] = tied_w
                    result["threatening_slots"].append(slot_idx)

    return result


def summarize_revealed_move_threats(
    active, active_idx, opponent_actives, our_actives, battle=None
) -> dict:
    """Summarize revealed move threats against an active Pokemon."""
    result = {
        "threatening_opponents": [],
        "revealed_move_ids": [],
        "revealed_move_types": [],
        "target_likelihood_weights": [],
        "active_multipliers": [],
        "priority_moves": [],
        "spread_moves": [],
        "max_pressure": 0.0,
        "combined_pressure": 0.0,
        "likely_lethal": False,
        "super_effective_threat": False,
        "no_threat_reason": "",
    }

    if not active or not opponent_actives:
        result["no_threat_reason"] = "no_active_or_opponents"
        return result

    has_revealed = False
    for opp in opponent_actives:
        if not opp:
            continue
        revealed = get_revealed_damaging_moves(opp)
        if not revealed:
            continue
        has_revealed = True
        opp_species = getattr(opp, "species", "unknown")
        result["threatening_opponents"].append(opp_species)

        for move in revealed:
            risk = evaluate_revealed_move_incoming_risk(move, opp, active, battle)
            if risk["incoming_pressure"] <= 0:
                continue

            move_id = getattr(move, "id", "unknown")
            move_type_obj = getattr(move, "type", None)
            move_type = getattr(move_type_obj, "name", str(move_type_obj)) if move_type_obj else "unknown"

            target_likelihood = estimate_revealed_move_target_likelihood(
                move, opp, our_actives, battle
            )

            result["revealed_move_ids"].append(move_id)
            result["revealed_move_types"].append(move_type)
            result["target_likelihood_weights"].append(target_likelihood)
            result["active_multipliers"].append(risk["type_multiplier"])
            if risk["priority"] > 0:
                result["priority_moves"].append(move_id)
            if risk["is_spread"]:
                result["spread_moves"].append(move_id)

            if risk["incoming_pressure"] > result["max_pressure"]:
                result["max_pressure"] = risk["incoming_pressure"]
            result["combined_pressure"] += risk["incoming_pressure"]

            if risk["likely_ko_pressure"]:
                result["likely_lethal"] = True
            if risk["classification"] in ("super-effective", "quad-effective"):
                result["super_effective_threat"] = True

    if not has_revealed:
        result["no_threat_reason"] = "no_revealed_damaging_moves"

    return result


def evaluate_revealed_move_switch_interception(
    active, candidate, active_idx, battle=None
) -> dict:
    """Evaluate whether switching a candidate in would intercept revealed threats."""
    result = {
        "active_risk": 0.0,
        "candidate_risk": 0.0,
        "risk_reduction": 0.0,
        "fractional_risk_reduction": 0.0,
        "moves_resisted": [],
        "moves_made_immune": [],
        "moves_more_dangerous": [],
        "likely_lethal": False,
        "super_effective_threat": False,
        "candidate_hp": 1.0,
        "interception_valid": False,
        "rejection_reason": "",
        "proposed_score_bonus": 0.0,
    }

    if not active or not candidate or not battle:
        result["rejection_reason"] = "missing_active_or_candidate"
        return result

    # Check candidate HP
    candidate_hp = getattr(candidate, "current_hp_fraction", 1.0)
    if candidate_hp is None:
        candidate_hp = 1.0
    result["candidate_hp"] = candidate_hp

    # Get opponent actives
    opp_actives = [opp for opp in battle.opponent_active_pokemon if opp]
    if not opp_actives:
        result["rejection_reason"] = "no_opponent_actives"
        return result

    # Evaluate threats from each opponent
    total_active_risk = 0.0
    total_candidate_risk = 0.0
    any_threat = False

    for opp in opp_actives:
        revealed = get_revealed_damaging_moves(opp)
        for move in revealed:
            active_risk_info = evaluate_revealed_move_incoming_risk(move, opp, active, battle)
            candidate_risk_info = evaluate_revealed_move_incoming_risk(move, opp, candidate, battle)

            active_mult = active_risk_info["type_multiplier"]
            candidate_mult = candidate_risk_info["type_multiplier"]
            pressure = active_risk_info["incoming_pressure"]

            if pressure <= 0:
                continue

            any_threat = True
            total_active_risk += pressure
            total_candidate_risk += candidate_risk_info["incoming_pressure"]

            move_id = getattr(move, "id", "unknown")

            if candidate_mult == 0.0 and active_mult > 0:
                result["moves_made_immune"].append(move_id)
            elif candidate_mult < active_mult:
                result["moves_resisted"].append(move_id)
            elif candidate_mult > active_mult:
                result["moves_more_dangerous"].append(move_id)

            # Track lethal and super-effective threats
            if active_risk_info.get("likely_ko_pressure"):
                result["likely_lethal"] = True
            if active_risk_info.get("classification") in ("super-effective", "quad-effective"):
                result["super_effective_threat"] = True

    result["active_risk"] = total_active_risk
    result["candidate_risk"] = total_candidate_risk

    if total_active_risk > 0:
        result["risk_reduction"] = total_active_risk - total_candidate_risk
        result["fractional_risk_reduction"] = (total_active_risk - total_candidate_risk) / total_active_risk

    if not any_threat:
        result["rejection_reason"] = "no_revealed_threats"
        return result

    # Check rejection conditions
    config = DoublesDamageAwareConfig()

    if candidate_hp < config.revealed_switch_min_candidate_hp:
        result["rejection_reason"] = "candidate_hp_below_minimum"
        return result

    if result["fractional_risk_reduction"] < config.revealed_switch_min_risk_reduction:
        result["rejection_reason"] = "insufficient_risk_reduction"
        return result

    # Check if candidate is exposed to severe threats from other opponent
    other_opps = [opp for opp in battle.opponent_active_pokemon if opp]
    for opp in other_opps:
        revealed = get_revealed_damaging_moves(opp)
        for move in revealed:
            cand_risk = evaluate_revealed_move_incoming_risk(move, opp, candidate, battle)
            if cand_risk["type_multiplier"] >= 2.0 and cand_risk["incoming_pressure"] > 0:
                if cand_risk["incoming_pressure"] >= total_active_risk * 0.8:
                    result["rejection_reason"] = "worse_other_threat"
                    return result

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
    if getattr(first_move, "base_power", 0) <= 0 or getattr(second_move, "base_power", 0) <= 0:
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
    def __init__(self, *args, verbose=True, logger=None, audit_logger=None, config=None, **kwargs):
        if "battle_format" not in kwargs:
            kwargs["battle_format"] = "gen9randomdoublesbattle"
        super().__init__(*args, **kwargs)
        self.verbose = verbose
        self.custom_logger = logger
        self.audit_logger = audit_logger
        self.config = config or DoublesDamageAwareConfig()
        self._active_config_override = None

    @property
    def config(self):
        if hasattr(self, "_active_config_override") and self._active_config_override is not None:
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
                    print("[RandomSet] WARNING: Database loaded but is empty. Disabling random-set modeling.")
                    self.random_set_engine = None
            except Exception as e:
                print(f"[RandomSet] WARNING: Failed to load database ({e}). Disabling random-set modeling.")
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
        self._order_aware_overkill_penalty_applied = {}

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
        for order in [getattr(joint_order, "first_order", None), getattr(joint_order, "second_order", None)]:
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

            first_blocked = _direct_absorb_blocked.get(id(first), False) if first else False
            second_blocked = _direct_absorb_blocked.get(id(second), False) if second else False
            first_safety_blocked = _safety_blocked.get(id(first), False) if first else False
            second_safety_blocked = _safety_blocked.get(id(second), False) if second else False
            ar_map = _ally_redirect_blocked or {}
            first_ar_blocked = ar_map.get(id(first), False) if first else False
            second_ar_blocked = ar_map.get(id(second), False) if second else False
            either_blocked = (first_blocked or second_blocked or first_safety_blocked
                              or second_safety_blocked or first_ar_blocked or second_ar_blocked)

            if not either_blocked:
                if isinstance(first.order, Move) and isinstance(second.order, Move):
                    if first.move_target == second.move_target and first.move_target in (1, 2):
                        target_opp = battle.opponent_active_pokemon[first.move_target - 1]
                        if target_opp:
                            ko_1 = self.check_move_will_ko(first.order, battle.active_pokemon[0], target_opp, battle, config=config)
                            ko_2 = self.check_move_will_ko(second.order, battle.active_pokemon[1], target_opp, battle, config=config)
                            opp_hp_fraction = getattr(target_opp, "current_hp_fraction", 1.0)

                            if (ko_1 and ko_2) or (ko_1 or ko_2) and opp_hp_fraction < 0.15 or opp_hp_fraction < 0.08:
                                allow_double = False
                                if config.enable_threat_scoring:
                                    threat_score = self.score_opponent_threat(target_opp, battle)
                                    if threat_score >= 0.50:
                                        allow_double = True
                                if not allow_double:
                                    joint_score -= 250.0

                            if config.enable_meta_opponent_modeling and self.meta_engine:
                                t_species = target_opp.species
                                t_revealed = list(target_opp.moves.keys())
                                likely_protect, prob, reason = self.meta_engine.likely_has_protect(
                                    t_species, t_revealed, threshold=config.meta_move_probability_threshold
                                )
                                if likely_protect:
                                    joint_score -= 15.0

                            if (config.enable_random_set_opponent_modeling
                                    and self.random_set_engine
                                    and config.rs_enable_protect_overcommit_penalty):
                                t_species = target_opp.species
                                t_revealed = list(target_opp.moves.keys())
                                prot_thr = config.rs_protect_threshold if config.rs_protect_threshold > 0.0 else config.random_set_probability_threshold
                                likely_protect, prob, _ = self.random_set_engine.likely_has_protect(
                                    t_species, t_revealed, threshold=prot_thr
                                )
                                if likely_protect:
                                    overcommit_delta = config.rs_protect_overcommit_delta if config.rs_protect_overcommit_delta > 0.0 else 12.0
                                    joint_score -= overcommit_delta

                if config.enable_order_aware_overkill:
                    if self.selected_target_will_be_koed_before_second_action(first, second, battle, config=config):
                        joint_score -= config.order_aware_overkill_penalty

                if isinstance(first.order, Move) and isinstance(second.order, Move):
                    if first.move_target == second.move_target and first.move_target in (1, 2):
                        target_opp = battle.opponent_active_pokemon[first.move_target - 1]
                        if target_opp:
                            # Stale target after ally KO safety (Phase 6.4.5)
                            if config.enable_stale_target_after_ally_ko_safety:
                                if not self.is_spread_move(first.order) and not self.is_spread_move(second.order):
                                    if getattr(first.order, "base_power", 0) > 0 and getattr(second.order, "base_power", 0) > 0:
                                        ko_1 = self.check_move_will_ko(first.order, battle.active_pokemon[0], target_opp, battle, config=config)
                                        if ko_1:
                                            visible_opps = [o for o in battle.opponent_active_pokemon if o and not getattr(o, "fainted", False)]
                                            stale = detect_stale_target_after_ally_ko_risk(
                                                first, second, ko_1, target_opp, target_opp,
                                                visible_opps, battle=battle, config=config,
                                            )
                                            if stale["risk"]:
                                                joint_score -= config.stale_target_after_ally_ko_penalty
                                                if stale["fallback_target_type_immune"]:
                                                    joint_score -= config.stale_target_type_immune_penalty

                            opp_hp_fraction = getattr(target_opp, "current_hp_fraction", 1.0)
                            other_idx = 1 if first.move_target == 1 else 0
                            other_opp = battle.opponent_active_pokemon[other_idx]
                            other_hp_fraction = getattr(other_opp, "current_hp_fraction", 1.0) if other_opp else 1.0
                            if opp_hp_fraction <= other_hp_fraction and opp_hp_fraction < 0.75:
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
                                    immune, _ = is_type_immune(move_obj, battle.active_pokemon[slot_idx], target_mon, battle)
                                    if immune:
                                        if self.is_spread_move(move_obj):
                                            other_opps = [o for o in battle.opponent_active_pokemon if o and o != target_mon]
                                            any_not_immune = False
                                            for other_opp in other_opps:
                                                try:
                                                    other_immune, _ = is_type_immune(move_obj, battle.active_pokemon[slot_idx], other_opp, battle)
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

            if either_blocked and (first_safety_blocked or second_safety_blocked or first_ar_blocked or second_ar_blocked):
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
        return sum(m.get("threat_contribution", 0.0) for m in self.battle_metrics.values())

    @property
    def total_tiebreaker_activations(self) -> int:
        return sum(m.get("tiebreaker_activations", 0) for m in self.battle_metrics.values())

    @property
    def total_boosted_override_activations(self) -> int:
        return sum(m.get("boosted_override_activations", 0) for m in self.battle_metrics.values())

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
                    if p and p.species == pokemon.species and getattr(p, "active", False):
                        is_our_side = True
                        break
                if is_our_side:
                    if self.has_tailwind(getattr(battle, "side_conditions", {})):
                        speed *= 2.0
                else:
                    if self.has_tailwind(getattr(battle, "opponent_side_conditions", {})):
                        speed *= 2.0
            
            item = getattr(pokemon, "item", None)
            if item:
                item_str = item.name if hasattr(item, "name") else str(item)
                item_str_clean = item_str.lower().replace(" ", "").replace("-", "").replace("_", "")
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
        move_id_clean = str(move_id).lower().replace(" ", "").replace("-", "").replace("_", "")
        
        if move_id_clean in ("protect", "detect", "spikyshield", "banefulbunker", "kingsshield", "obstruct", "silktrap", "burningbulwark"):
            return 4
        if move_id_clean in ("fakeout", "quickguard", "wideguard", "craftyshield"):
            return 3
        if move_id_clean in ("extremespeed", "feint", "allyswitch"):
            return 2
        if move_id_clean in ("aquajet", "bulletpunch", "iceshard", "machpunch", "shadowsneak", "suckerpunch", "vacuumwave", "watershuriken", "bastonpass", "babyeyedomination", "firstimpression", "grassyglide", "accelgor"):
            return 1
            
        return 0

    def get_opponent_active_turns(self, opponent, battle) -> int:
        if not battle or not opponent:
            return 1
        battle_tag = battle.battle_tag
        if not hasattr(self, "opponent_active_turns") or battle_tag not in self.opponent_active_turns:
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
            "conditional_priority_moves": []
        }
        if not opponent:
            return result
        moves = getattr(opponent, "moves", {})
        for move_id, move in moves.items():
            priority = self.get_move_priority(move)
            if priority > 0:
                move_id_clean = move_id.lower().replace(" ", "").replace("-", "").replace("_", "")
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

    def estimate_speed_priority_threat(self, our_active, opponent_actives, battle=None, candidate_action=None) -> dict:
        result = {
            "is_threatened": False,
            "speed_threatened": False,
            "priority_threatened": False,
            "faint_before_moving": False,
            "faster_opponents": [],
            "priority_opponents": [],
            "threat_confidence": 0.0,
            "only_conditional_priority": False
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
                if move_id in ("protect", "detect", "spikyshield", "banefulbunker", "kingsshield", "obstruct", "silktrap", "burningbulwark"):
                    is_protect = True
                    candidate_priority = 4
                else:
                    candidate_priority = self.get_move_priority(candidate_action.order)
                category = getattr(candidate_action.order, "category", None)
                category_name = getattr(category, "name", "STATUS")
                is_attacking = (category_name != "STATUS")

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
                is_opp_faster = (our_speed >= opp_speed * self.config.speed_margin_required)
            else:
                is_opp_faster = (opp_speed >= our_speed * self.config.speed_margin_required)
                
            prio_info = self.opponent_has_revealed_priority_move(opp, battle)
            
            priority_threat_active = False
            
            if prio_info["has_priority"]:
                if prio_info["has_conditional_priority"] and not prio_info["has_guaranteed_priority"]:
                    has_sucker = any(m == "suckerpunch" for m in prio_info["conditional_priority_moves"])
                    if has_sucker:
                        if candidate_action is None:
                            priority_threat_active = (our_hp <= self.config.speed_threat_hp_threshold)
                        elif is_attacking:
                            priority_threat_active = (our_hp <= self.config.priority_threat_hp_threshold)
                        else:
                            priority_threat_active = False
                    else:
                        priority_threat_active = (our_hp <= self.config.priority_threat_hp_threshold)
                else:
                    priority_threat_active = (our_hp <= self.config.priority_threat_hp_threshold)

            opp_conf = 0.0
            opp_is_threat = False

            if is_opp_faster and our_hp <= self.config.speed_threat_hp_threshold:
                opp_is_threat = True
                result["speed_threatened"] = True
                result["is_threatened"] = True
                if opp.species not in result["faster_opponents"]:
                    result["faster_opponents"].append(opp.species)
                
                if not (is_protect or is_switch) and candidate_priority == 0:
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
                
                if not (is_protect or is_switch) and candidate_priority <= opp_max_prio:
                    result["faint_before_moving"] = True

                # Compute confidence for priority threat -- use max multiplier
                max_prio_threat = get_max_type_threat(our_active, opp, battle)
                if prio_info.get("has_conditional_priority") and not prio_info.get("has_guaranteed_priority"):
                    opp_conf = max(opp_conf, self.config.speed_priority_conditional_priority_weight)
                else:
                    only_cond = False
                    if our_hp <= 0.20 or max_prio_threat >= 1.5:
                        opp_conf = max(opp_conf, 1.0)
                    else:
                        opp_conf = max(opp_conf, 0.75)
            
            if opp_is_threat:
                max_opp_conf = max(max_opp_conf, opp_conf)

        result["threat_confidence"] = max_opp_conf
        result["only_conditional_priority"] = only_cond if has_any_prio_threat else False
        return result

    def is_protect_available_for_slot(self, slot_idx: int, battle) -> bool:
        valid_orders = getattr(self, "_current_valid_orders", None)
        if not valid_orders or len(valid_orders) <= slot_idx or not valid_orders[slot_idx]:
            return False
        for order in valid_orders[slot_idx]:
            if order and isinstance(order.order, Move):
                move_id = getattr(order.order, "id", "").lower()
                if move_id in ("protect", "detect", "spikyshield", "banefulbunker", "kingsshield", "obstruct", "silktrap", "burningbulwark"):
                    return True
        return False

    def has_legal_protect_like_action(self, active, battle, slot_index=None, valid_orders=None) -> bool:
        if valid_orders is None:
            valid_orders = getattr(self, "_current_valid_orders", None)
            
        if slot_index is None:
            if battle and active:
                for idx, p in enumerate(battle.active_pokemon):
                    if p and p.species == active.species:
                        slot_index = idx
                        break

        if valid_orders and slot_index is not None and len(valid_orders) > slot_index and valid_orders[slot_index]:
            for order in valid_orders[slot_index]:
                if order and isinstance(order.order, Move):
                    move_id = getattr(order.order, "id", "").lower()
                    if move_id in ("protect", "detect", "spikyshield", "banefulbunker", "kingsshield", "obstruct", "silktrap", "burningbulwark"):
                        return True
            return False

        if active and hasattr(active, "moves") and active.moves:
            for move in active.moves.values():
                move_id = getattr(move, "id", "").lower()
                if move_id in ("protect", "detect", "spikyshield", "banefulbunker", "kingsshield", "obstruct", "silktrap", "burningbulwark"):
                    return True
        return False

    def is_high_value_action_under_threat(self, action, actor, battle, opponent_actives, config=None) -> bool:
        resolved_config = config if config is not None else self.config
        if not action or not isinstance(action.order, Move):
            return False
            
        move = action.order
        
        if self.get_move_priority(move) > 0:
            return True
            
        for opp in opponent_actives:
            if opp and self.check_move_will_ko(move, actor, opp, battle, config=resolved_config):
                return True
                
        if is_opponent_spread_move(move, action):
            opps_count = sum(1 for opp in opponent_actives if opp and not getattr(opp, "fainted", False))
            if opps_count >= 2:
                base_pow = getattr(move, "base_power", 0)
                if base_pow >= 75:
                    return True
                    
        target_pos = action.move_target
        if target_pos in (1, 2) and opponent_actives:
            opp = opponent_actives[target_pos - 1] if len(opponent_actives) > (target_pos - 1) else None
            if opp:
                expected_dmg_frac = self.get_expected_damage(move, actor, opp, battle, config=resolved_config)
                if expected_dmg_frac >= resolved_config.speed_priority_min_expected_damage_fraction:
                    return True
                    
        if target_pos in (1, 2) and opponent_actives:
            opp = opponent_actives[target_pos - 1] if len(opponent_actives) > (target_pos - 1) else None
            if opp and getattr(opp, "current_hp_fraction", 1.0) <= 0.20:
                expected_dmg_frac = self.get_expected_damage(move, actor, opp, battle, config=resolved_config)
                if expected_dmg_frac > 0.05:
                    return True

        return False

    def selected_target_will_be_koed_before_second_action(self, order_0, order_1, battle, config=None) -> bool:
        if not order_0 or not order_1 or not battle:
            return False
        if not isinstance(order_0.order, Move) or not isinstance(order_1.order, Move):
            return False
        if order_0.move_target != order_1.move_target or order_0.move_target not in (1, 2):
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
                slot_0_is_faster = (speed_0 < speed_1)
            else:
                slot_0_is_faster = (speed_0 > speed_1)
                
        faster_order = order_0 if slot_0_is_faster else order_1
        slower_order = order_1 if slot_0_is_faster else order_0
        faster_active = battle.active_pokemon[0] if slot_0_is_faster else battle.active_pokemon[1]
        
        faster_ko = self.check_move_will_ko(faster_order.order, faster_active, target_opp, battle, config=config)
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
            m_id_clean = m_id[0].lower().replace(" ", "").replace("-", "").replace("_", "")
            if m_id_clean in ("protect", "detect", "spikyshield", "banefulbunker", "kingsshield", "obstruct", "silktrap", "burningbulwark"):
                has_protect = True
                break
        if not has_protect and self.config.enable_random_set_opponent_modeling and self.random_set_engine:
            likely_p, _, _ = self.random_set_engine.likely_has_protect(target_opp.species, list(target_opp.moves.keys()))
            if likely_p:
                has_protect = True
        if has_protect:
            return False
            
        return True

    def get_type_effectiveness(self, move: Move, opponent: Optional[Pokemon], attacker=None) -> float:

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

    def score_opponent_threat(self, opponent: Optional[Pokemon], battle: DoubleBattle, our_pokemon: Optional[Pokemon] = None) -> float:
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
                
                target_ours = [our_pokemon] if our_pokemon else [active for active in battle.active_pokemon if active]
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
                setup_move_ids = {"swordsdance", "dragondance", "calmmind", "nastyplot", "agility", "quiverdance", "shellsmash", "bulkup", "cosmicpower", "doubleteam", "acidarmor", "irondefense", "honeclaws", "workup", "growth", "howl", "charge", "minimize", "autotomize", "rockpolish", "geomancy"}
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
            spe_control_move_ids = {"tailwind", "trickroom", "icywind", "electroweb", "bulldoze", "nuzzle", "glare", "thunderwave", "stringshot", "scaryface"}
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
            target_ours = [our_pokemon] if our_pokemon else [active for active in battle.active_pokemon if active]
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
                        
            threat_score = (stat_factor + spe_factor) * hp_factor + faster_bonus + has_spread + has_priority + has_setup + has_speed_control + super_effective
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
        resolved_config = config if config is not None else getattr(self, "config", None)
        base_power = getattr(move, "base_power", 0)
        if base_power == 0 or not opponent or not active:
            return 0.0
        if resolved_config and resolved_config.enable_type_immunity_safety:
            immune, reason = is_type_immune(move, active, opponent, battle)
            if immune:
                return 0.0
        if resolved_config and getattr(resolved_config, "enable_ability_hard_safety_only", False):
            blocks, reason = ability_hard_blocks_move(move, active, opponent, battle, resolved_config)
            if blocks and _ability_block_enabled(resolved_config, reason):
                return 0.0
            
            # Phase 6.3.3 direct safety
            if getattr(resolved_config, "ability_hard_safety_direct_absorb_only", False) and is_single_target_direct:
                if not self.is_spread_move(move):
                    blocks_direct, reason_direct = direct_known_absorb_blocks_move(move, active, opponent, battle)
                    if blocks_direct:
                        return 0.0

        # Phase 6.3.6b: Known Ally Redirection Hard Safety
        if resolved_config and getattr(resolved_config, "enable_known_ally_redirection_hard_safety", False):
            if battle and is_single_target_direct:
                active_pokemon = getattr(battle, "active_pokemon", [])
                if len(active_pokemon) >= 2:
                    ally = None
                    if active is active_pokemon[0]:
                        ally = active_pokemon[1]
                    elif active is active_pokemon[1]:
                        ally = active_pokemon[0]
                    if ally and not getattr(ally, "fainted", False):
                        redirects, _ = ally_redirects_our_single_target_move(move, active, ally, battle)
                        if redirects:
                            return 0.0

        # Phase 6.3.5a: Priority Terrain / Ability Safety
        if resolved_config and getattr(resolved_config, "enable_priority_field_hard_safety", False):
            priority_blocked, _ = priority_move_is_field_blocked(move, active, opponent, battle, resolved_config)
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
            base_damage = (((2.0 * level / 5.0 + 2.0) * base_power * attacking_stat / max(defending_stat, 1.0)) / 50.0) + 2.0
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
            if self.is_spread_move(move) and battle and resolved_config and resolved_config.enable_spread_intelligence:
                opps = [o for o in battle.opponent_active_pokemon if o]
                if len(opps) == 2:
                    expected_damage *= 0.75
            return expected_damage
        except Exception:
            return 0.0

    def check_move_will_ko(self, move: Move, active: Optional[Pokemon], opponent: Optional[Pokemon], battle: Optional[DoubleBattle] = None, config=None) -> bool:
        expected_damage = self.get_expected_damage(move, active, opponent, battle, config=config)
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

    def score_action_raw_damage(self, order: SingleBattleOrder, active_idx: int, battle: DoubleBattle, config=None) -> float:
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
                        print(f"[Immunity Block] {reason} | Attacker: {active_mon.species}, Target: {target_mon.species}")
                    return 0.0

        # Phase 6.3.3: Direct Known-Absorb Hard Safety
        if resolved_config.enable_ability_hard_safety_only and resolved_config.ability_hard_safety_direct_absorb_only:
            if target_pos in (1, 2) and not is_opponent_spread_move(move, order) and target_mon:
                blocks_direct, reason_direct = direct_known_absorb_blocks_move(move, active_mon, target_mon, battle, order)
                if blocks_direct:
                    if self.verbose:
                        print(f"[Direct Absorb Hard Block] {reason_direct} | Attacker: {active_mon.species}, Target: {target_mon.species}")
                    return 0.0

        # Phase 6.3.6b: Known Ally Redirection Hard Safety
        if resolved_config.enable_known_ally_redirection_hard_safety:
            if target_pos in (1, 2) and target_mon:
                ally_idx = 1 - active_idx
                ally = battle.active_pokemon[ally_idx] if ally_idx < len(battle.active_pokemon) else None
                if ally and not getattr(ally, "fainted", False):
                    redirects, red_reason = ally_redirects_our_single_target_move(move, active_mon, ally, battle)
                    if redirects:
                        if self.verbose:
                            print(f"[Ally Redirection Block] {red_reason} | Ally: {ally.species}")
                        return 0.0

        # Phase 6.3: Ability hard safety block check for single target
        if resolved_config.enable_ability_hard_safety_only:
            if target_pos in (1, 2) and target_mon:
                blocks, reason = ability_hard_blocks_move(move, active_mon, target_mon, battle, config=resolved_config)
                if blocks and _ability_block_enabled(resolved_config, reason):
                    if self.verbose:
                        print(f"[Ability Hard Block] {reason} | Attacker: {active_mon.species}, Target: {target_mon.species}")
                    return 0.0
                
                # Check redirection for single-target Water/Electric moves
                if resolved_config.ability_hard_safety_avoid_redirection:
                    redirects, red_reason = ability_redirects_single_target_move(
                        move, target_mon, battle.opponent_active_pokemon, active_mon, battle
                    )
                    if redirects:
                        # Find the redirection target
                        red_target = None
                        for opp in battle.opponent_active_pokemon:
                            if opp and opp != target_mon and not getattr(opp, "fainted", False):
                                opp_ability = get_known_ability(opp, battle)
                                if opp_ability in ("stormdrain", "lightningrod"):
                                    red_target = opp
                                    break
                        # Score 0 only if the redirected target is bad/immune/benefits.
                        if red_target:
                            blocks_red, reason_red = ability_hard_blocks_move(move, active_mon, red_target, battle, config=resolved_config)
                            if blocks_red and _ability_block_enabled(resolved_config, reason_red):
                                if self.verbose:
                                    print(f"[Ability Redirection Hard Safety] {red_reason} | Attacker: {active_mon.species}, Intended Target: {target_mon.species} (blocked by redirected target {red_target.species})")
                                return 0.0
                            else:
                                # Redirection target is not immune! Calculate redirected score.
                                red_type_multiplier = self.get_type_effectiveness(move, red_target, attacker=active_mon)
                                if red_type_multiplier == 0.0:
                                    return 0.0
                                if category_name == "SPECIAL":
                                    red_defending_stat = self.get_boosted_stat(red_target, "spd")
                                else:
                                    red_defending_stat = self.get_boosted_stat(red_target, "def")
                                red_score = float(base_power) * (attacking_stat / max(red_defending_stat, 1.0)) * stab_multiplier * red_type_multiplier * accuracy_multiplier
                                # Return a slightly reduced score
                                return 0.8 * red_score

        # Ability-Aware block checks for single target
        if resolved_config.enable_ability_awareness:
            if target_pos in (1, 2) and target_mon:
                blocks, reason = ability_rules.ability_blocks_move(target_mon, move, attacker=active_mon)
                if blocks:
                    if self.verbose:
                        print(f"[Ability Block] {reason} | Attacker: {ability_rules.get_known_ability(active_mon)}, Target: {ability_rules.get_known_ability(target_mon)}")
                    self.increment_metric(self.ability_blocks_avoided_by_battle, battle.battle_tag)
                    return 0.0
                absorbs, reason = ability_rules.ability_absorbs_or_benefits(target_mon, move)
                if absorbs:
                    if self.verbose:
                        print(f"[Ability Absorb] {reason} | Attacker: {ability_rules.get_known_ability(active_mon)}, Target: {ability_rules.get_known_ability(target_mon)}")
                    self.increment_metric(self.ability_absorbs_avoided_by_battle, battle.battle_tag)
                    return 0.0
                # Redirection check
                for opp in battle.opponent_active_pokemon:
                    if opp and opp != target_mon:
                        redirects, reason = ability_rules.ability_redirects_move(opp, move)
                        if redirects:
                            if self.verbose:
                                print(f"[Ability Redirection] {reason} | Attacker: {ability_rules.get_known_ability(active_mon)}, Target: {ability_rules.get_known_ability(target_mon)}")
                            self.increment_metric(self.ability_redirects_avoided_by_battle, battle.battle_tag)
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
                            print(f"[Immunity Block Spread] {reason} | Attacker: {active_mon.species}, Target: {opp.species}")
                        continue
                if resolved_config.enable_ability_hard_safety_only:
                    blocks, reason = ability_hard_blocks_move(move, active_mon, opp, battle, config=resolved_config)
                    if blocks and _ability_block_enabled(resolved_config, reason):
                        if self.verbose:
                            print(f"[Ability Hard Block Spread] {reason} | Attacker: {active_mon.species}, Target: {opp.species}")
                        continue
                if resolved_config.enable_ability_awareness:
                    blocks, reason = ability_rules.ability_blocks_move(opp, move, attacker=active_mon)
                    if blocks:
                        if self.verbose:
                            print(f"[Ability Block Spread] {reason} | Attacker: {ability_rules.get_known_ability(active_mon)}, Target: {ability_rules.get_known_ability(opp)}")
                        self.increment_metric(self.ability_blocks_avoided_by_battle, battle.battle_tag)
                        continue
                    absorbs, reason = ability_rules.ability_absorbs_or_benefits(opp, move)
                    if absorbs:
                        if self.verbose:
                            print(f"[Ability Absorb Spread] {reason} | Attacker: {ability_rules.get_known_ability(active_mon)}, Target: {ability_rules.get_known_ability(opp)}")
                        self.increment_metric(self.ability_absorbs_avoided_by_battle, battle.battle_tag)
                        continue
                type_multiplier = self.get_type_effectiveness(move, opp, attacker=active_mon)
                if type_multiplier == 0.0:
                    continue
                if category_name == "SPECIAL":
                    defending_stat = self.get_boosted_stat(opp, "spd")
                else:
                    defending_stat = self.get_boosted_stat(opp, "def")
                opp_score = float(base_power) * (attacking_stat / max(defending_stat, 1.0)) * stab_multiplier * type_multiplier * accuracy_multiplier
                
                if resolved_config.enable_ability_awareness:
                    t_mult, t_reason = ability_rules.ability_damage_multiplier(opp, move, attacker=active_mon)
                    a_mult, a_reason = ability_rules.attacker_ability_damage_multiplier(active_mon, move, target=opp)
                    if t_mult != 1.0 or a_mult != 1.0:
                        if self.verbose:
                            print(f"[Ability Multiplier Spread] target_mult={t_mult} ({t_reason or 'None'}), attacker_mult={a_mult} ({a_reason or 'None'}) vs {opp.species}")
                        self.increment_metric(self.ability_multipliers_applied_by_battle, battle.battle_tag)
                    opp_score *= t_mult * a_mult

                total_damage += opp_score
            if len(opps) == 2 and resolved_config.enable_spread_intelligence:
                total_damage *= 0.75
            return total_damage

        if target_mon:
            type_multiplier = self.get_type_effectiveness(move, target_mon, attacker=active_mon)
        else:
            type_multiplier = 1.0

        if type_multiplier == 0.0:
            return 0.0

        if category_name == "SPECIAL":
            defending_stat = self.get_boosted_stat(target_mon, "spd") if target_mon else 100.0
        else:
            defending_stat = self.get_boosted_stat(target_mon, "def") if target_mon else 100.0

        score = float(base_power) * (attacking_stat / max(defending_stat, 1.0)) * stab_multiplier * type_multiplier * accuracy_multiplier

        if resolved_config.enable_ability_awareness and target_mon:
            t_mult, t_reason = ability_rules.ability_damage_multiplier(target_mon, move, attacker=active_mon)
            a_mult, a_reason = ability_rules.attacker_ability_damage_multiplier(active_mon, move, target=target_mon)
            if t_mult != 1.0 or a_mult != 1.0:
                if self.verbose:
                    print(f"[Ability Multiplier] target_mult={t_mult} ({t_reason or 'None'}), attacker_mult={a_mult} ({a_reason or 'None'}) vs {target_mon.species}")
                self.increment_metric(self.ability_multipliers_applied_by_battle, battle.battle_tag)
            score *= t_mult * a_mult

        return score



    def best_move_score_for_slot(self, slot_idx: int, battle: DoubleBattle) -> float:
        active_mon = battle.active_pokemon[slot_idx]
        if not active_mon or battle.force_switch[slot_idx] or not battle.available_moves[slot_idx]:
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
            return self._score_action_impl(
                order,
                active_idx,
                battle,
                with_tiebreaker=with_tiebreaker,
                is_selected=is_selected,
                in_spread_check=in_spread_check,
            )
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
        for attr in ("_ability_hard_block_avoided", "_ability_immune_move_selected", 
                     "_ground_into_levitate_selected", "_ability_block_reason", 
                     "_ability_blocked_target_species", "_ability_blocked_target_ability", 
                     "_ally_ability_safe_spread", "_ability_redirection_avoided",
                     "_direct_absorb_hard_block_avoided", "_direct_absorb_immune_move_selected",
                     "_direct_absorb_block_reason", "_direct_absorb_target_species",
                     "_direct_absorb_target_ability", "_direct_absorb_only_legal_action"):
            if not hasattr(self, attr):
                setattr(self, attr, {})
        
        for attr in ("_ability_hard_block_avoided", "_ability_immune_move_selected", 
                     "_ground_into_levitate_selected", "_ally_ability_safe_spread", 
                     "_ability_redirection_avoided", "_direct_absorb_hard_block_avoided",
                     "_direct_absorb_immune_move_selected", "_direct_absorb_only_legal_action"):
            d = getattr(self, attr)
            if battle_tag not in d:
                d[battle_tag] = {0: False, 1: False}
                
        for attr in ("_ability_block_reason", "_ability_blocked_target_species", 
                     "_ability_blocked_target_ability", "_direct_absorb_block_reason",
                     "_direct_absorb_target_species", "_direct_absorb_target_ability"):
            d = getattr(self, attr)
            if battle_tag not in d:
                d[battle_tag] = {0: "", 1: ""}

        # --- Pass / Default orders (processed before active_mon check) ---
        if isinstance(order, PassBattleOrder) or getattr(order, "order", None) == "/choose pass":
            if battle.force_switch[active_idx]:
                return 10.0
            return 0.0
        
        if isinstance(order, DefaultBattleOrder) or getattr(order, "order", None) == "/choose default":
            return 1.0

        # --- Switch orders (scored even when active slot is empty) ---
        if isinstance(order.order, Pokemon):
            switch_score = self.config.switch_baseline

            # Phase 6.4: Switch candidate type safety ranking
            if self.config.enable_switch_candidate_type_safety:
                switch_candidate = order.order
                active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                safety = evaluate_switch_candidate_type_safety(switch_candidate, active_opps, self.config)
                # Store safety data for audit logging if this is the selected action
                if is_selected:
                    if not hasattr(self, "_switch_candidate_safety_data"):
                        self._switch_candidate_safety_data = {}
                    self._switch_candidate_safety_data[battle_tag] = self._switch_candidate_safety_data.get(battle_tag, {})
                    self._switch_candidate_safety_data[battle_tag][active_idx] = safety
                # Apply relative adjustment later in the ranking phase (see choose_move)

            # Speed/priority switch bonus: only when a live active Pokemon exists
            if active_mon and self.config.enable_speed_priority_awareness and not self.config.speed_priority_protect_only:
                active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                threat_info = self.estimate_speed_priority_threat(active_mon, active_opps, battle)
                if threat_info["is_threatened"]:
                    has_protect = self.has_legal_protect_like_action(active_mon, battle, slot_index=active_idx)
                    mon_id = self.get_pokemon_identifier(active_mon)
                    key = (active_idx, mon_id)
                    last_turn = self.last_protect_turn.get(battle_tag, {}).get(key, -9)
                    protect_consecutive = (current_turn - last_turn == 1)
                    
                    if not has_protect or protect_consecutive:
                        can_ko = False
                        has_strong_spread = False
                        for ord in self.get_valid_orders_for_slot(active_idx, battle):
                            if ord and isinstance(ord.order, Move):
                                m = ord.order
                                t_pos = ord.move_target
                                if t_pos in (1, 2):
                                    t_mon = battle.opponent_active_pokemon[t_pos - 1]
                                    if t_mon and self.check_move_will_ko(m, active_mon, t_mon, battle, config=self.config):
                                        can_ko = True
                                if is_opponent_spread_move(m, ord):
                                    base_pow = getattr(m, "base_power", 0)
                                    if base_pow >= 60:
                                        has_strong_spread = True
                                        
                        if not can_ko and not has_strong_spread:
                            bonus = self.config.speed_priority_switch_bonus
                            bonus = min(bonus, self.config.speed_priority_max_delta_per_action)
                            switch_score += bonus
                            if is_selected:
                                self._speed_priority_switch_bonus_applied[battle_tag][active_idx] = True

            # Phase 6.4.4: Forced switch replacement safety scoring
            is_forced_switch = battle.force_switch[active_idx] if active_idx < len(battle.force_switch) else False
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
                    self._forced_switch_safety_data[battle_tag] = self._forced_switch_safety_data.get(battle_tag, {})
                    self._forced_switch_safety_data[battle_tag][active_idx] = safety

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
            threat_info = self.estimate_speed_priority_threat(active_mon, active_opps, battle, order)
            
            self._speed_priority_threatened[battle_tag][active_idx] = threat_info["is_threatened"]
            self._faster_opponents[battle_tag][active_idx] = threat_info["faster_opponents"]
            self._priority_opponents[battle_tag][active_idx] = threat_info["priority_opponents"]
            self._expected_to_faint_before_moving[battle_tag][active_idx] = threat_info["faint_before_moving"]

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
            if move.id in ("protect", "detect", "spikyshield", "kingsshield", "banefulbunker"):
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
                    threat_info = self.estimate_speed_priority_threat(active_mon, active_opps, battle)
                    if threat_info["priority_threatened"]:
                        hp_thresh = self.config.priority_threat_hp_threshold
                        
                if hp_fraction >= hp_thresh:
                    return 0.0

                ally_can_attack = self.best_move_score_for_slot(1 - active_idx, battle) > 30.0
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
                    if opp_spe > our_spe and get_max_type_threat(active_mon, opp, battle) >= 1.5:
                        is_threatened = True
                        break
                        
                # Critical HP: very low HP and any opponent exists
                if hp_fraction < 0.15 and len(active_opps) > 0:
                    is_threatened = True

                # Phase 6.2 Speed/Priority Threat
                if self.config.enable_speed_priority_awareness and threat_info and threat_info["is_threatened"]:
                    if self.has_legal_protect_like_action(active_mon, battle, slot_index=active_idx):
                        is_threatened = True

                if is_threatened:
                    base_protect = self.config.protect_score
                    if self.config.enable_speed_priority_awareness and threat_info and threat_info["is_threatened"]:
                        if self.has_legal_protect_like_action(active_mon, battle, slot_index=active_idx):
                            confidence = threat_info.get("threat_confidence", 1.0)
                            if self.config.speed_priority_use_scaled_penalty:
                                bonus = self.config.speed_priority_protect_bonus_low + confidence * (self.config.speed_priority_protect_bonus_high - self.config.speed_priority_protect_bonus_low)
                            else:
                                bonus = self.config.speed_priority_protect_bonus
                            bonus = min(bonus, self.config.speed_priority_max_delta_per_action)
                            base_protect += bonus
                            if is_selected:
                                self._speed_priority_protect_bonus_applied[battle_tag][active_idx] = True
                                self._protected_due_to_speed_priority[battle_tag][active_idx] = True
                                
                    if self.config.enable_protect_threat_refinement:
                        max_threat = 0.0
                        for opp in active_opps:
                            t_score = self.score_opponent_threat(opp, battle, our_pokemon=active_mon)
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
                if battle_tag in self.active_turns and key in self.active_turns[battle_tag]:
                    active_turn_count, last_turn = self.active_turns[battle_tag][key]
                
                if active_turn_count != 1:
                    return 0.0

                if target_mon:
                    type_multiplier = self.get_type_effectiveness(move, target_mon, attacker=active_mon)
                    is_ghost = "GHOST" in [t.name for t in getattr(target_mon, "types", []) if t]
                    if type_multiplier == 0.0 or is_ghost:
                        return 0.0
                else:
                    return 0.0

                score = self.score_action_raw_damage(order, active_idx, battle)
                score += 250.0

                if self.check_move_will_ko(move, active_mon, target_mon, battle, config=self.config):
                    score += 200.0
                else:
                    opps = [opp for opp in battle.opponent_active_pokemon if opp]
                    if len(opps) == 2:
                        if self.config.enable_fakeout_threat_targeting:
                            threat_0 = self.score_opponent_threat(opps[0], battle)
                            threat_1 = self.score_opponent_threat(opps[1], battle)
                            dangerous_opp = opps[0] if threat_0 >= threat_1 else opps[1]
                        else:
                            opp1_power = max(self.get_boosted_stat(opps[0], "atk"), self.get_boosted_stat(opps[0], "spa"))
                            opp2_power = max(self.get_boosted_stat(opps[1], "atk"), self.get_boosted_stat(opps[1], "spa"))
                            dangerous_opp = opps[0] if opp1_power >= opp2_power else opps[1]
                        if target_mon == dangerous_opp:
                            score += 50.0

                return max(score, 0.0)

            # 3. Generic Status Moves
            if category_name == "STATUS" or base_power == 0:
                if self.config.enable_priority_field_hard_safety and target_pos in (1, 2) and target_mon:
                    priority_res = evaluate_priority_move_legality(move, active_mon, target_mon, battle, self.config)
                    if priority_res["blocked"]:
                        return float(self.config.ability_hard_safety_block_score)

                if self.config.enable_ability_awareness:
                    if target_mon and target_pos in (1, 2):
                        avoid, reason = ability_rules.should_avoid_status_into_ability(target_mon, move)
                        if avoid:
                            if self.verbose:
                                print(f"[Status Blocked] {reason} | Attacker: {ability_rules.get_known_ability(active_mon)}, Target: {ability_rules.get_known_ability(target_mon)}")
                            self.increment_metric(self.ability_blocks_avoided_by_battle, battle.battle_tag)
                            has_damaging_move = any(getattr(m, "base_power", 0) > 0 for m in battle.available_moves[active_idx])
                            if has_damaging_move:
                                return 0.0
                            return -100.0
                    elif target_pos == 0:
                        for opp in battle.opponent_active_pokemon:
                            if opp:
                                avoid, reason = ability_rules.should_avoid_status_into_ability(opp, move)
                                if avoid:
                                    if self.verbose:
                                        print(f"[Status Blocked Spread] {reason} | Attacker: {ability_rules.get_known_ability(active_mon)}, Target: {ability_rules.get_known_ability(opp)}")
                                    self.increment_metric(self.ability_blocks_avoided_by_battle, battle.battle_tag)
                                    has_damaging_move = any(getattr(m, "base_power", 0) > 0 for m in battle.available_moves[active_idx])
                                    if has_damaging_move:
                                        return 0.0
                                    return -100.0

                has_damaging_move = any(getattr(m, "base_power", 0) > 0 for m in battle.available_moves[active_idx])
                if has_damaging_move:
                    return 0.0
                return 10.0

            # 4. Damaging Moves
            score = self.score_action_raw_damage(order, active_idx, battle)

            # ability awareness. Selected-action error flags are recorded even in
            # the benchmark's safety-off arm.
            if target_pos in (1, 2) and target_mon:
                blocks, reason = ability_hard_blocks_move(move, active_mon, target_mon, battle, config=self.config)
                applies = blocks and _ability_block_enabled(self.config, reason)
                
                # Phase 6.3.3: Direct Known-Absorb Hard Safety
                applies_direct = False
                if self.config.enable_ability_hard_safety_only and self.config.ability_hard_safety_direct_absorb_only:
                    if not is_opponent_spread_move(move, order):
                        blocks_direct, reason_direct = direct_known_absorb_blocks_move(move, active_mon, target_mon, battle, order)
                        if blocks_direct:
                            applies_direct = True
                            reason = reason_direct
                
                if (blocks or applies_direct) and is_selected:
                    self._ability_immune_move_selected[battle_tag][active_idx] = True
                    if reason == "ground_into_levitate":
                        self._ground_into_levitate_selected[battle_tag][active_idx] = True
                    self._ability_block_reason[battle_tag][active_idx] = reason
                    self._ability_blocked_target_species[battle_tag][active_idx] = target_mon.species
                    self._ability_blocked_target_ability[battle_tag][active_idx] = get_known_ability(target_mon, battle) or ""
                    
                    if applies_direct:
                        self._direct_absorb_immune_move_selected[battle_tag][active_idx] = True
                        self._direct_absorb_block_reason[battle_tag][active_idx] = reason
                        self._direct_absorb_target_species[battle_tag][active_idx] = target_mon.species
                        self._direct_absorb_target_ability[battle_tag][active_idx] = get_known_ability(target_mon, battle) or ""
                        
                # Phase 6.3.5a: Priority Terrain / Ability Safety
                applies_priority = False
                if self.config.enable_priority_field_hard_safety:
                    priority_res = evaluate_priority_move_legality(move, active_mon, target_mon, battle, self.config)
                    if priority_res["blocked"]:
                        applies_priority = True
                        reason = priority_res["reason"]
 
                # Phase 6.3.6b: Known Ally Redirection Hard Safety
                applies_ally_redirect = False
                ally_redirect_reason = ""
                if self.config.enable_known_ally_redirection_hard_safety:
                    ally_idx = 1 - active_idx
                    ally = battle.active_pokemon[ally_idx] if ally_idx < len(battle.active_pokemon) else None
                    if ally and not getattr(ally, "fainted", False):
                        redirects, red_reason = ally_redirects_our_single_target_move(move, active_mon, ally, battle)
                        if redirects:
                            applies_ally_redirect = True
                            ally_redirect_reason = red_reason
                            if is_selected:
                                self._known_ally_redirect_selected[battle_tag][active_idx] = True
                                self._known_ally_redirect_reason[battle_tag][active_idx] = red_reason
                                self._known_ally_redirect_ally_species[battle_tag][active_idx] = ally.species
                                self._known_ally_redirect_ally_ability[battle_tag][active_idx] = get_known_ability(ally, battle) or ""
                                self._known_ally_redirect_move_id[battle_tag][active_idx] = getattr(move, "id", "")

                if applies or applies_direct or applies_priority or applies_ally_redirect:
                    return float(self.config.ability_hard_safety_block_score)
 
                if self.config.enable_ability_hard_safety_only and self.config.ability_hard_safety_avoid_redirection:
                    redirects, red_reason = ability_redirects_single_target_move(
                        move, target_mon, battle.opponent_active_pokemon, active_mon, battle
                    )
                    if redirects:
                        red_target = None
                        for opp in battle.opponent_active_pokemon:
                            if opp and opp != target_mon and not getattr(opp, "fainted", False):
                                opp_ability = get_known_ability(opp, battle)
                                if opp_ability in ("stormdrain", "lightningrod"):
                                    red_target = opp
                                    break
                        if red_target:
                            blocks_red, reason_red = ability_hard_blocks_move(move, active_mon, red_target, battle, config=self.config)
                            if blocks_red and _ability_block_enabled(self.config, reason_red):
                                if is_selected:
                                    self._ability_immune_move_selected[battle_tag][active_idx] = True
                                    self._ability_block_reason[battle_tag][active_idx] = red_reason
                                    self._ability_blocked_target_species[battle_tag][active_idx] = red_target.species
                                    self._ability_blocked_target_ability[battle_tag][active_idx] = get_known_ability(red_target, battle) or ""
                                return float(self.config.ability_hard_safety_block_score)
 
            elif is_opponent_spread_move(move, order):
                ability_blocked = []
                for opp in battle.opponent_active_pokemon:
                    if not opp:
                        continue
                    blocked, reason = ability_hard_blocks_move(move, active_mon, opp, battle, config=self.config)
                    if blocked:
                        ability_blocked.append((opp, reason))
                if ability_blocked:
                    if is_selected:
                        blocked_target, blocked_reason = ability_blocked[0]
                        self._ability_immune_move_selected[battle_tag][active_idx] = True
                        self._ability_block_reason[battle_tag][active_idx] = blocked_reason
                        self._ability_blocked_target_species[battle_tag][active_idx] = blocked_target.species
                        self._ability_blocked_target_ability[battle_tag][active_idx] = get_known_ability(blocked_target, battle) or ""
                        if any(reason == "ground_into_levitate" for _, reason in ability_blocked):
                            self._ground_into_levitate_selected[battle_tag][active_idx] = True

            # Phase 6.1.2: Partial Spread Immunity Penalty and Alternative Gate
            if is_opponent_spread_move(move, order):
                eff = get_spread_target_effectiveness_with_ability(move, active_mon, battle.opponent_active_pokemon, self.config, battle)
                
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
                            if opp_mon and self.check_move_will_ko(move, active_mon, opp_mon, battle, config=self.config):
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
                            for ord in self.get_valid_orders_for_slot(active_idx, battle):
                                if ord and isinstance(ord.order, Move):
                                    m = ord.order
                                    # Filter only for single-target damaging moves
                                    if not is_opponent_spread_move(m, ord) and getattr(m, "base_power", 0) > 0:
                                        alt_score = self.score_action(ord, active_idx, battle, with_tiebreaker=False, is_selected=False, in_spread_check=True)
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
                                        if t_mon and self.check_move_will_ko(m, active_mon, t_mon, battle, config=self.config):
                                            best_single_can_ko = True
                            
                            if is_selected and best_single_order:
                                self.best_single_alternative_by_battle[battle_tag][active_idx] = best_single_order.order.id
                                
                            # If single-target can KO while spread cannot, heavily penalize spread
                            spread_can_ko = expected_ko_on_non_immune_target
                            if best_single_can_ko and not spread_can_ko:
                                score = max(0.0, score - 200.0)
                            # If single-target score is close (within 30 gap), prefer single target
                            elif best_single_score > 0.0 and best_single_score >= score - self.config.partial_spread_prefer_single_target_gap:
                                score = min(score, best_single_score - 1.0)
                            
                # Populate audit flags if this is the final selected action rerun
                if is_selected:
                    self.partial_immune_spread_by_battle[battle_tag][active_idx] = eff["partial_immunity"]
                    self.partial_ability_immune_spread_by_battle[battle_tag][active_idx] = get_spread_ability_partial_immunity(move, active_mon, battle.opponent_active_pokemon, self.config, battle)
                    self.immune_target_species_by_battle[battle_tag][active_idx] = eff["immune_target_names"]
                    self.damaged_target_species_by_battle[battle_tag][active_idx] = eff["damaged_target_names"]
                    if eff["partial_immunity"]:
                        spread_can_ko = False
                        for opp_name in eff["damaged_target_names"]:
                            opp_mon = None
                            for opp in battle.opponent_active_pokemon:
                                if opp and opp.species == opp_name:
                                    opp_mon = opp
                                    break
                            if opp_mon and self.check_move_will_ko(move, active_mon, opp_mon, battle, config=self.config):
                                spread_can_ko = True
                                break
                                
                        best_single_score = 0.0
                        best_single_can_ko = False
                        best_single_order = None
                        for ord in self.get_valid_orders_for_slot(active_idx, battle):
                            if ord and isinstance(ord.order, Move):
                                m = ord.order
                                if not is_opponent_spread_move(m, ord) and getattr(m, "base_power", 0) > 0:
                                    alt_score = self.score_action(ord, active_idx, battle, with_tiebreaker=False, is_selected=False, in_spread_check=True)
                                    if alt_score > best_single_score:
                                        best_single_score = alt_score
                                        best_single_order = ord
                                    t_pos = ord.move_target
                                    t_mon = None
                                    if t_pos == 1:
                                        t_mon = battle.opponent_active_pokemon[0]
                                    elif t_pos == 2:
                                        t_mon = battle.opponent_active_pokemon[1]
                                    if t_mon and self.check_move_will_ko(m, active_mon, t_mon, battle, config=self.config):
                                        best_single_can_ko = True
                                        
                        if best_single_order:
                            self.best_single_alternative_by_battle[battle_tag][active_idx] = best_single_order.order.id
                            
                        is_inefficient = False
                        if not spread_can_ko:
                            # Use current score for comparison (might or might not be penalized/capped depending on config)
                            if best_single_score > 0.0 and best_single_score >= score - self.config.partial_spread_prefer_single_target_gap:
                                is_inefficient = True
                            if best_single_can_ko:
                                is_inefficient = True
                                
                        self.inefficient_partial_spread_by_battle[battle_tag][active_idx] = is_inefficient
                        self.efficient_partial_spread_by_battle[battle_tag][active_idx] = not is_inefficient

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
                            safe, reason = ability_rules.ally_is_safe_from_move(ally, move)
                            if safe:
                                is_safe = True
                                if self.verbose:
                                    print(f"[Ally Safe Spread] {reason} | Ally Ability: {ability_rules.get_known_ability(ally)}")
                                self.increment_metric(self.ally_safe_spreads_by_battle, battle.battle_tag)
                            absorbs, reason = ability_rules.ability_absorbs_or_benefits(ally, move)
                            if absorbs:
                                benefits = True
                        else:
                            is_safe = self.ally_safe_against_move(ally, move)
                            if not is_safe and self.config.enable_ability_hard_safety_only and self.config.ability_hard_safety_ally_spread_safety:
                                ability_safe, reason = ally_ability_makes_safe(ally, move, battle)
                                if ability_safe:
                                    is_safe = True
                                    if is_selected:
                                        self._ally_ability_safe_spread[battle_tag][active_idx] = True
                            
                        if not is_safe:
                            score = max(0.0, score * 0.2 - self.config.ally_hit_penalty)
                        elif benefits:
                            if self.verbose:
                                print(f"[Ally Benefits Spread] {reason} | Ally Ability: {ability_rules.get_known_ability(ally)} (+30 bonus)")
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

                if self.check_move_will_ko(move, active_mon, target_mon, battle, config=self.config):
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
                        for cand_order in self.get_valid_orders_for_slot(active_idx, battle):
                            if isinstance(cand_order.order, Move) and cand_order.move_target in (1, 2):
                                t_mon = battle.opponent_active_pokemon[cand_order.move_target - 1]
                                if t_mon and self.check_move_will_ko(cand_order.order, active_mon, t_mon, battle, config=self.config):
                                    any_ko_exists = True
                                    break
                                    
                        any_opp_low_hp = False
                        for opp in battle.opponent_active_pokemon:
                            if opp and getattr(opp, "current_hp_fraction", 1.0) < self.config.low_hp_target_threshold:
                                any_opp_low_hp = True
                                break
                                
                        is_emergency = max_boost >= self.config.boosted_override_emergency_stage
                        
                        if is_emergency or (not any_ko_exists and not any_opp_low_hp):
                            score += self.config.boosted_threat_bonus
 
                # Gated threat tiebreaker
                if with_tiebreaker and self.config.enable_threat_tiebreaker:
                    # Retrieve/populate cache for active_idx if not already populated
                    if not self._base_scores_cache[active_idx]:
                        for cand_order in self.get_valid_orders_for_slot(active_idx, battle):
                            self._base_scores_cache[active_idx][id(cand_order)] = self.score_action(
                                cand_order, active_idx, battle, with_tiebreaker=False
                            )
                            
                    # Conditions:
                    # 1. Action is a damaging move (BP > 0)
                    # 2. Target is an opponent (checked by outer block)
                    # 3. No candidate move can KO an opponent
                    any_ko_exists = False
                    for cand_order in self.get_valid_orders_for_slot(active_idx, battle):
                        if isinstance(cand_order.order, Move) and cand_order.move_target in (1, 2):
                            t_mon = battle.opponent_active_pokemon[cand_order.move_target - 1]
                            if t_mon and self.check_move_will_ko(cand_order.order, active_mon, t_mon, battle, config=self.config):
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
                                threat_score = self.score_opponent_threat(target_mon, battle)
                                score += threat_score * self.config.threat_tiebreaker_weight

            elif target_pos == 0:
                for opp in battle.opponent_active_pokemon:
                    if opp and self.check_move_will_ko(move, active_mon, opp, battle, config=self.config):
                        score += 150.0

            # Recoil/Self-destruct
            recoil = self.get_recoil(move)
            if recoil > 0:
                score -= 15.0 * recoil

            if move.id in {"selfdestruct", "explosion"}:
                score -= 50.0

            # Phase 5.2 / 5.3: Random-Set-Aware Opponent Modeling Adjustments
            if self.config.enable_random_set_opponent_modeling and self.random_set_engine:
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
                if move.id in ("protect", "detect", "spikyshield", "kingsshield",
                               "banefulbunker", "silktrap", "burningbulwark"):

                    # Rule 2: Fake Out danger -- first-turn opponent
                    if cfg.rs_enable_fakeout_bonus:
                        fo_thr = _thr(cfg.rs_fakeout_threshold)
                        fo_delta = cfg.rs_fakeout_protect_delta if cfg.rs_fakeout_protect_delta > 0.0 else 18.0
                        for opp_idx, opp in enumerate(active_opps):
                            opp_id = self.get_pokemon_identifier(opp)
                            key = (opp_idx, opp_id)
                            opp_active_turns_count = 1
                            if hasattr(self, "opponent_active_turns") and battle_tag in self.opponent_active_turns:
                                if key in self.opponent_active_turns[battle_tag]:
                                    opp_active_turns_count, _ = self.opponent_active_turns[battle_tag][key]
                            if opp_active_turns_count == 1:
                                opp_revealed = list(opp.moves.keys())
                                likely_fo, prob, _ = self.random_set_engine.likely_has_fake_out(
                                    opp.species, opp_revealed, threshold=fo_thr
                                )
                                if likely_fo:
                                    our_ability = ability_rules.get_known_ability(active_mon)
                                    vulnerable = our_ability not in ("innerfocus", "shielddust")
                                    if vulnerable:
                                        rs_protect_bonus += fo_delta
                                        self.increment_metric(self.rs_candidate_predictions_by_battle, battle_tag)
                                        if is_selected:
                                            self.increment_metric(self.rs_selected_predictions_by_battle, battle_tag)
                                            self.increment_metric(self.rs_predictions_used_by_battle, battle_tag)
                                            self.increment_metric(self.rs_fakeout_predictions_by_battle, battle_tag)
                                            if self.verbose:
                                                print(f"[RS Prediction] fakeout: {opp.species} p={prob:.2f} +{fo_delta}")

                    # Rule 3: Priority danger -- our HP < 20%
                    if cfg.rs_enable_priority_bonus and our_hp_fraction < 0.20:
                        prio_thr = _thr(cfg.rs_priority_threshold)
                        prio_delta = cfg.rs_priority_protect_delta if cfg.rs_priority_protect_delta > 0.0 else 20.0
                        for opp in active_opps:
                            opp_revealed = list(opp.moves.keys())
                            likely_prio, prob, _ = self.random_set_engine.likely_has_priority(
                                opp.species, opp_revealed, threshold=prio_thr
                            )
                            if likely_prio:
                                rs_protect_bonus += prio_delta
                                self.increment_metric(self.rs_candidate_predictions_by_battle, battle_tag)
                                if is_selected:
                                    self.increment_metric(self.rs_selected_predictions_by_battle, battle_tag)
                                    self.increment_metric(self.rs_predictions_used_by_battle, battle_tag)
                                    self.increment_metric(self.rs_priority_predictions_by_battle, battle_tag)
                                    if self.verbose:
                                        print(f"[RS Prediction] priority: {opp.species} p={prob:.2f} +{prio_delta}")

                    # Rule 4: Spread move danger -- our HP < rs_spread_hp_threshold (default 0.30)
                    if cfg.rs_enable_spread_bonus and our_hp_fraction < cfg.rs_spread_hp_threshold:
                        spread_thr = _thr(cfg.rs_spread_threshold)
                        spread_delta = cfg.rs_spread_protect_delta if cfg.rs_spread_protect_delta > 0.0 else 12.0
                        for opp in active_opps:
                            opp_revealed = list(opp.moves.keys())
                            likely_spread, prob, _ = self.random_set_engine.likely_has_spread_move(
                                opp.species, opp_revealed, threshold=spread_thr
                            )
                            if likely_spread:
                                rs_protect_bonus += spread_delta
                                self.increment_metric(self.rs_candidate_predictions_by_battle, battle_tag)
                                if is_selected:
                                    self.increment_metric(self.rs_selected_predictions_by_battle, battle_tag)
                                    self.increment_metric(self.rs_predictions_used_by_battle, battle_tag)
                                    self.increment_metric(self.rs_spread_predictions_by_battle, battle_tag)
                                    if self.verbose:
                                        print(f"[RS Prediction] spread: {opp.species} p={prob:.2f} +{spread_delta}")

                    # Rule 6: Speed control danger -- our HP < 40%
                    if cfg.rs_enable_speed_control_bonus and our_hp_fraction < 0.40:
                        sc_thr = _thr(cfg.rs_speed_control_threshold)
                        sc_delta = cfg.rs_speed_control_protect_delta if cfg.rs_speed_control_protect_delta > 0.0 else 8.0
                        for opp in active_opps:
                            opp_revealed = list(opp.moves.keys())
                            likely_sc, prob, _ = self.random_set_engine.likely_has_speed_control(
                                opp.species, opp_revealed, threshold=sc_thr
                            )
                            if likely_sc:
                                rs_protect_bonus += sc_delta
                                self.increment_metric(self.rs_candidate_predictions_by_battle, battle_tag)
                                if is_selected:
                                    self.increment_metric(self.rs_selected_predictions_by_battle, battle_tag)
                                    self.increment_metric(self.rs_predictions_used_by_battle, battle_tag)
                                    self.increment_metric(self.rs_speed_control_predictions_by_battle, battle_tag)
                                    if self.verbose:
                                        print(f"[RS Prediction] speed_control: {opp.species} p={prob:.2f} +{sc_delta}")

                    rs_protect_bonus = min(rs_protect_bonus, cfg.random_set_max_protect_bonus_per_active)
                    score += rs_protect_bonus

                # -- Targeting-level adjustments (damaging moves vs opponent) --
                if target_mon and target_pos in (1, 2):
                    opp_revealed = list(target_mon.moves.keys())

                    # Close-score gating: only apply targeting bonuses when scores are within gap
                    close_score_ok = True
                    if cfg.rs_close_score_gate_enabled:
                        # Populate cache if needed
                        if not self._base_scores_cache[active_idx]:
                            for cand_order in self.get_valid_orders_for_slot(active_idx, battle):
                                self._base_scores_cache[active_idx][id(cand_order)] = self.score_action(
                                    cand_order, active_idx, battle, with_tiebreaker=False
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
                                if getattr(t_opp, "current_hp_fraction", 1.0) < cfg.low_hp_target_threshold:
                                    any_low_hp_cl = True
                                for cand_order in self.get_valid_orders_for_slot(active_idx, battle):
                                    if isinstance(cand_order.order, Move) and cand_order.move_target in (1, 2):
                                        cand_t = battle.opponent_active_pokemon[cand_order.move_target - 1]
                                        if cand_t and self.check_move_will_ko(cand_order.order, active_mon, cand_t, battle, config=self.config):
                                            any_ko_cl = True
                                            break
                        if any_ko_cl or any_low_hp_cl:
                            close_score_ok = False

                    if close_score_ok:
                        # Rule 5: Setup move danger -- only if no KO and no low-HP target
                        if cfg.rs_enable_setup_targeting:
                            setup_thr = _thr(cfg.rs_setup_threshold)
                            setup_delta = cfg.rs_setup_targeting_delta if cfg.rs_setup_targeting_delta > 0.0 else 8.0
                            any_ko_exists = False
                            any_low_hp = False
                            for t_opp in active_opps:
                                if t_opp:
                                    if getattr(t_opp, "current_hp_fraction", 1.0) < cfg.low_hp_target_threshold:
                                        any_low_hp = True
                                    for cand_order in self.get_valid_orders_for_slot(active_idx, battle):
                                        if isinstance(cand_order.order, Move) and cand_order.move_target in (1, 2):
                                            cand_t = battle.opponent_active_pokemon[cand_order.move_target - 1]
                                            if cand_t and self.check_move_will_ko(cand_order.order, active_mon, cand_t, battle, config=self.config):
                                                any_ko_exists = True
                                                break
                            if not any_ko_exists and not any_low_hp:
                                likely_setup, prob, _ = self.random_set_engine.likely_has_setup_move(
                                    target_mon.species, opp_revealed, threshold=setup_thr
                                )
                                if likely_setup:
                                    rs_targeting_bonus += setup_delta
                                    self.increment_metric(self.rs_candidate_predictions_by_battle, battle_tag)
                                    if is_selected:
                                        self.increment_metric(self.rs_selected_predictions_by_battle, battle_tag)
                                        self.increment_metric(self.rs_predictions_used_by_battle, battle_tag)
                                        self.increment_metric(self.rs_setup_predictions_by_battle, battle_tag)
                                        if self.verbose:
                                            print(f"[RS Prediction] setup: {target_mon.species} p={prob:.2f} +{setup_delta}")

                        # Rule 3 (KO targeting): priority user KO bonus
                        if cfg.rs_enable_priority_bonus and self.check_move_will_ko(move, active_mon, target_mon, battle, config=self.config):
                            prio_thr = _thr(cfg.rs_priority_threshold)
                            likely_prio, prob, _ = self.random_set_engine.likely_has_priority(
                                target_mon.species, opp_revealed, threshold=prio_thr
                            )
                            if likely_prio:
                                prio_ko_delta = cfg.rs_priority_protect_delta if cfg.rs_priority_protect_delta > 0.0 else 12.0
                                rs_targeting_bonus += prio_ko_delta
                                self.increment_metric(self.rs_candidate_predictions_by_battle, battle_tag)
                                if is_selected:
                                    self.increment_metric(self.rs_selected_predictions_by_battle, battle_tag)
                                    self.increment_metric(self.rs_predictions_used_by_battle, battle_tag)
                                    self.increment_metric(self.rs_priority_predictions_by_battle, battle_tag)
                                    if self.verbose:
                                        print(f"[RS Prediction] priority_ko: {target_mon.species} p={prob:.2f} +{prio_ko_delta}")

                score += rs_targeting_bonus

                # Clamp total delta per turn
                rs_diff = score - rs_base_score
                if abs(rs_diff) > cfg.random_set_max_score_delta_per_turn:
                    sign = 1.0 if rs_diff > 0 else -1.0
                    score = rs_base_score + sign * cfg.random_set_max_score_delta_per_turn
                    rs_diff = sign * cfg.random_set_max_score_delta_per_turn

                if is_selected and abs(rs_diff) > 0.0:
                    self.rs_score_delta_by_battle[battle_tag] = (
                        self.rs_score_delta_by_battle.get(battle_tag, 0.0) + abs(rs_diff)
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
                            if getattr(t_opp, "current_hp_fraction", 1.0) < self.config.low_hp_target_threshold:
                                any_low_hp = True
                            for cand_order in self.get_valid_orders_for_slot(active_idx, battle):
                                if isinstance(cand_order.order, Move) and cand_order.move_target in (1, 2):
                                    cand_t_mon = battle.opponent_active_pokemon[cand_order.move_target - 1]
                                    if cand_t_mon and self.check_move_will_ko(cand_order.order, active_mon, cand_t_mon, battle, config=self.config):
                                        any_ko_exists = True
                                        break
                    
                    if not any_ko_exists and not any_low_hp:
                        likely_setup, prob, reason = self.meta_engine.likely_has_setup_move(
                            target_mon.species, opp_revealed, threshold=self.config.meta_move_probability_threshold
                        )
                        if likely_setup:
                            meta_targeting_bonus += 10.0
                            self.increment_metric(self.candidate_meta_predictions_by_battle, battle_tag)
                            if is_selected:
                                self.increment_metric(self.selected_meta_predictions_by_battle, battle_tag)
                                self.increment_metric(self.meta_predictions_used_by_battle, battle_tag)
                                self.increment_metric(self.meta_setup_predictions_by_battle, battle_tag)
                                if self.verbose:
                                    print(f"[Meta Prediction] species={target_mon.species} type=setup prob={prob:.2f} action=target_setup delta=+10.0")

                    # Priority KO check (Rule 3)
                    # "only add a small target preference bonus if our move can KO the priority user and scores are already close"
                    if self.check_move_will_ko(move, active_mon, target_mon, battle, config=self.config):
                        likely_prio, prob, reason = self.meta_engine.likely_has_priority(
                            target_mon.species, opp_revealed, threshold=self.config.meta_move_probability_threshold
                        )
                        if likely_prio:
                            meta_targeting_bonus += 15.0
                            self.increment_metric(self.candidate_meta_predictions_by_battle, battle_tag)
                            if is_selected:
                                self.increment_metric(self.selected_meta_predictions_by_battle, battle_tag)
                                self.increment_metric(self.meta_predictions_used_by_battle, battle_tag)
                                self.increment_metric(self.meta_priority_predictions_by_battle, battle_tag)
                                if self.verbose:
                                    print(f"[Meta Prediction] species={target_mon.species} type=priority_ko prob={prob:.2f} action=target_ko_priority delta=+15.0")

                # Check general threat predictions for Protect modifications (Rules 2, 3, 4, 6)
                if move.id in ("protect", "detect", "spikyshield", "kingsshield", "banefulbunker"):
                    # Rule 2: Fake Out Danger
                    for opp_idx, opp in enumerate(active_opps):
                        opp_id = self.get_pokemon_identifier(opp)
                        key = (opp_idx, opp_id)
                        opp_active_turns_count = 1
                        if battle_tag in self.opponent_active_turns and key in self.opponent_active_turns[battle_tag]:
                            opp_active_turns_count, last_turn = self.opponent_active_turns[battle_tag][key]
                        
                        if opp_active_turns_count == 1:
                            opp_revealed = list(opp.moves.keys())
                            likely_fo, prob, reason = self.meta_engine.likely_has_fake_out(
                                opp.species, opp_revealed, threshold=self.config.meta_move_probability_threshold
                            )
                            if likely_fo:
                                our_ability = ability_rules.get_known_ability(active_mon)
                                vulnerable = our_ability not in ("innerfocus", "shielddust")
                                if vulnerable:
                                    meta_protect_bonus += 20.0
                                    self.increment_metric(self.candidate_meta_predictions_by_battle, battle_tag)
                                    if is_selected:
                                        self.increment_metric(self.selected_meta_predictions_by_battle, battle_tag)
                                        self.increment_metric(self.meta_predictions_used_by_battle, battle_tag)
                                        self.increment_metric(self.meta_fakeout_predictions_by_battle, battle_tag)
                                        if self.verbose:
                                            print(f"[Meta Prediction] species={opp.species} type=fakeout prob={prob:.2f} action=protect_bonus_fakeout delta=+20.0")

                    # Rule 3: Priority Danger
                    if our_hp_fraction < 0.20:
                        for opp in active_opps:
                            opp_revealed = list(opp.moves.keys())
                            likely_prio, prob, reason = self.meta_engine.likely_has_priority(
                                opp.species, opp_revealed, threshold=self.config.meta_move_probability_threshold
                            )
                            if likely_prio:
                                meta_protect_bonus += 25.0
                                self.increment_metric(self.candidate_meta_predictions_by_battle, battle_tag)
                                if is_selected:
                                    self.increment_metric(self.selected_meta_predictions_by_battle, battle_tag)
                                    self.increment_metric(self.meta_predictions_used_by_battle, battle_tag)
                                    self.increment_metric(self.meta_priority_predictions_by_battle, battle_tag)
                                    if self.verbose:
                                        print(f"[Meta Prediction] species={opp.species} type=priority prob={prob:.2f} action=protect_bonus_priority delta=+25.0")

                    # Rule 4: Spread Move Danger
                    if our_hp_fraction < 0.30:
                        for opp in active_opps:
                            opp_revealed = list(opp.moves.keys())
                            likely_spread, prob, reason = self.meta_engine.likely_has_spread_move(
                                opp.species, opp_revealed, threshold=self.config.meta_move_probability_threshold
                            )
                            if likely_spread:
                                meta_protect_bonus += 15.0
                                self.increment_metric(self.candidate_meta_predictions_by_battle, battle_tag)
                                if is_selected:
                                    self.increment_metric(self.selected_meta_predictions_by_battle, battle_tag)
                                    self.increment_metric(self.meta_predictions_used_by_battle, battle_tag)
                                    self.increment_metric(self.meta_spread_predictions_by_battle, battle_tag)
                                    if self.verbose:
                                        print(f"[Meta Prediction] species={opp.species} type=spread prob={prob:.2f} action=protect_bonus_spread delta=+15.0")

                    # Rule 6: Super-effective Coverage
                    for opp in active_opps:
                        opp_revealed = list(opp.moves.keys())
                        likely_se, prob, reason = self.meta_engine.likely_has_super_effective_coverage(
                            opp.species, active_mon, opp_revealed, threshold=self.config.meta_move_probability_threshold
                        )
                        if likely_se:
                            meta_protect_bonus += 15.0
                            self.increment_metric(self.candidate_meta_predictions_by_battle, battle_tag)
                            if is_selected:
                                self.increment_metric(self.selected_meta_predictions_by_battle, battle_tag)
                                self.increment_metric(self.meta_predictions_used_by_battle, battle_tag)
                                self.increment_metric(self.meta_coverage_predictions_by_battle, battle_tag)
                                if self.verbose:
                                    print(f"[Meta Prediction] species={opp.species} type=coverage prob={prob:.2f} action=protect_bonus_coverage delta=+15.0")

                    # Cap total Protect bonus per active slot
                    meta_protect_bonus = min(meta_protect_bonus, self.config.meta_max_protect_bonus_per_active)
                    score += meta_protect_bonus

                # Apply meta targeting bonuses
                score += meta_targeting_bonus

                # Part 4: Predicted Ability Soft Rules (disabled by default)
                if self.config.enable_meta_predicted_ability_soft_rules and target_mon and target_pos in (1, 2):
                    known_ab = ability_rules.get_known_ability(target_mon)
                    if not known_ab:
                        preds = self.meta_engine.predict_abilities(target_mon.species)
                        if preds:
                            top_ab, prob = preds[0]
                            if prob >= self.config.meta_predicted_ability_threshold:
                                mtype = ability_rules.get_move_type(move)
                                is_immune = False
                                if top_ab == "levitate" and mtype == "ground" and getattr(move, "id", "") != "thousandarrows":
                                    is_immune = True
                                elif top_ab == "flashfire" and mtype == "fire":
                                    is_immune = True
                                elif top_ab in ("waterabsorb", "stormdrain", "dryskin") and mtype == "water":
                                    is_immune = True
                                elif top_ab in ("voltabsorb", "lightningrod", "motordrive") and mtype == "electric":
                                    is_immune = True
                                elif top_ab == "sapsipper" and mtype == "grass":
                                    is_immune = True

                                if is_immune:
                                    score *= self.config.meta_predicted_ability_soft_penalty
                                    self.increment_metric(self.candidate_meta_predictions_by_battle, battle_tag)
                                    if is_selected:
                                        self.increment_metric(self.selected_meta_predictions_by_battle, battle_tag)
                                        self.increment_metric(self.meta_predictions_used_by_battle, battle_tag)
                                        self.increment_metric(self.meta_ability_soft_penalties_by_battle, battle_tag)
                                        if self.verbose:
                                            print(f"[Meta Prediction] species={target_mon.species} type=predicted_ability_{top_ab} prob={prob:.2f} action=soft_penalty delta=-{abs(score - base_score_before_meta):.1f}")

                # Cap total absolute score delta per turn
                diff = score - base_score_before_meta
                if abs(diff) > self.config.meta_max_score_delta_per_turn:
                    sign = 1.0 if diff > 0 else -1.0
                    score = base_score_before_meta + sign * self.config.meta_max_score_delta_per_turn
                    diff = sign * self.config.meta_max_score_delta_per_turn

                if is_selected and abs(diff) > 0.0:
                    self.total_meta_score_delta_by_battle[battle_tag] = self.total_meta_score_delta_by_battle.get(battle_tag, 0.0) + abs(diff)

            if self.config.enable_self_drop_move_penalty:
                expected_ko = False
                if target_mon:
                    expected_ko = self.check_move_will_ko(move, active_mon, target_mon, battle, config=self.config)
                has_alt = False
                if active_idx is not None and battle.available_moves and len(battle.available_moves) > active_idx:
                    avail = battle.available_moves[active_idx]
                    if avail:
                        for m in avail:
                            if m and getattr(m, "id", "") != move.id and getattr(m, "base_power", 0) > 0:
                                has_alt = True
                                break
                multiplier, reason = get_self_stat_drop_penalty(active_mon, move, expected_ko=expected_ko, has_reasonable_alternative=has_alt)
                if multiplier != 1.0:
                    score *= multiplier
                    if self.verbose and reason:
                        print(f"{reason} | score updated to {score:.2f}")
                    if is_selected:
                        m_id = getattr(move, "id", "").lower().replace(" ", "").replace("-", "").replace("_", "").strip()
                        if m_id in ("dracometeor", "overheat", "leafstorm", "fleurcannon", "psychoboost"):
                            self.increment_metric(self.draco_penalties_applied_by_battle, battle_tag)
                        elif m_id == "makeitrain":
                            self.increment_metric(self.make_it_rain_penalties_applied_by_battle, battle_tag)

            # Phase 6.2 Speed/Priority Attack Penalty
            if (self.config.enable_speed_priority_awareness and 
                    not self.config.speed_priority_protect_only and 
                    move.id not in ("protect", "detect", "spikyshield", "kingsshield", "banefulbunker", "silktrap", "burningbulwark")):
                
                active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                threat_info = self.estimate_speed_priority_threat(active_mon, active_opps, battle, order)
                
                if threat_info["faint_before_moving"]:
                    bypass = False
                    
                    # 1. KO threat
                    for opp in active_opps:
                        if opp and opp.species in threat_info["faster_opponents"] + threat_info["priority_opponents"]:
                            if self.check_move_will_ko(move, active_mon, opp, battle, config=self.config):
                                bypass = True
                                break
                                
                    # 2. No safe defensive options
                    has_protect = self.has_legal_protect_like_action(active_mon, battle, slot_index=active_idx)
                    mon_id = self.get_pokemon_identifier(active_mon)
                    key = (active_idx, mon_id)
                    last_turn = self.last_protect_turn.get(battle_tag, {}).get(key, -9)
                    protect_consecutive = (current_turn - last_turn == 1)
                    protect_avail = has_protect and not protect_consecutive
                    
                    switch_avail = len(getattr(battle, "available_switches", [])) > 0
                    
                    if not protect_avail and not switch_avail:
                        bypass = True
                        
                    # 3. High value action under threat
                    if self.is_high_value_action_under_threat(order, active_mon, battle, active_opps):
                        bypass = True
                        
                    if not bypass:
                        confidence = threat_info.get("threat_confidence", 1.0)
                        if self.config.speed_priority_use_scaled_penalty:
                            penalty = self.config.speed_priority_attack_penalty_low + confidence * (self.config.speed_priority_attack_penalty_high - self.config.speed_priority_attack_penalty_low)
                        else:
                            penalty = self.config.speed_priority_attack_penalty
                        penalty = min(penalty, self.config.speed_priority_max_delta_per_action)
                        score -= penalty
                        if is_selected:
                            self._speed_priority_attack_penalty_applied[battle_tag][active_idx] = True

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
                    slot_0_scores[id(order_0)] = self.score_action(order_0, 0, battle, config=config, pure=pure)
            if valid_orders[1]:
                for order_1 in valid_orders[1]:
                    slot_1_scores[id(order_1)] = self.score_action(order_1, 1, battle, config=config, pure=pure)

            # 2. Revealed-Move One-Ply Defensive Switch Interception
            if config.enable_revealed_move_switch_interception:
                for slot_idx in (0, 1):
                    active_mon = battle.active_pokemon[slot_idx]
                    if not active_mon:
                        continue
                    if slot_idx < len(battle.force_switch) and battle.force_switch[slot_idx]:
                        continue

                    orders_slot = valid_orders[slot_idx] if valid_orders and len(valid_orders) > slot_idx else []
                    switch_orders = [o for o in orders_slot if o and isinstance(o.order, Pokemon)]
                    if not switch_orders:
                        continue

                    active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                    our_actives = battle.active_pokemon
                    threats = summarize_revealed_move_threats(active_mon, slot_idx, active_opps, our_actives, battle)
                    if threats["max_pressure"] <= 0:
                        continue

                    best_action_score = 0.0
                    has_ko_action = False
                    for ord_cand in orders_slot:
                        if ord_cand and isinstance(ord_cand.order, Move):
                            cand_score = slot_0_scores.get(id(ord_cand), 0.0) if slot_idx == 0 else slot_1_scores.get(id(ord_cand), 0.0)
                            if cand_score > best_action_score:
                                best_action_score = cand_score
                            t_pos = getattr(ord_cand, "move_target", None)
                            if t_pos in (1, 2):
                                t_mon = battle.opponent_active_pokemon[t_pos - 1]
                                if t_mon and self.check_move_will_ko(ord_cand.order, active_mon, t_mon, battle, config=config):
                                    has_ko_action = True

                    best_bonus = 0.0
                    best_bonus_order = None
                    blocked_by_ko = False
                    blocked_by_high_value = False

                    if has_ko_action and config.revealed_switch_ko_action_override:
                        faint_before = False
                        for opp in active_opps:
                            for mv in get_revealed_damaging_moves(opp):
                                if self.check_move_will_ko(mv, opp, active_mon, battle, config=config):
                                    faint_before = True
                                    break
                            if faint_before:
                                break
                        if not faint_before:
                            blocked_by_ko = True

                    if best_action_score >= config.revealed_switch_high_value_action_threshold:
                        blocked_by_high_value = True

                    if not (blocked_by_ko or blocked_by_high_value):
                        for sw_order in switch_orders:
                            candidate = sw_order.order
                            interception = evaluate_revealed_move_switch_interception(active_mon, candidate, slot_idx, battle)
                            if not interception["interception_valid"]:
                                continue
                            bonus = interception["proposed_score_bonus"]
                            if bonus > best_bonus:
                                best_bonus = bonus
                                best_bonus_order = sw_order

                        if best_bonus_order is not None and best_bonus > 0:
                            sid = id(best_bonus_order)
                            old_score = slot_0_scores.get(sid, 0.0) if slot_idx == 0 else slot_1_scores.get(sid, 0.0)
                            if slot_idx == 0:
                                slot_0_scores[sid] = old_score + best_bonus
                            else:
                                slot_1_scores[sid] = old_score + best_bonus

            # 3/3b. Precompute safety blocks (canonical helper)
            _direct_absorb_blocked, _safety_blocked, _ally_redirect_blocked, _ally_redirect_blocked_meta = _compute_order_safety_blocks(
                battle, config, valid_orders
            )

            # 4. Switch candidate type safety ranking
            if config.enable_switch_candidate_type_safety:
                for slot_idx in (0, 1):
                    orders = valid_orders[slot_idx] if valid_orders and len(valid_orders) > slot_idx else []
                    switch_orders = [o for o in orders if o and isinstance(o.order, Pokemon)]
                    if not switch_orders:
                        continue

                    active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                    candidate_safety = {}
                    for sw_order in switch_orders:
                        candidate = sw_order.order
                        safety = evaluate_switch_candidate_type_safety(candidate, active_opps, config)
                        candidate_safety[id(sw_order)] = safety

                    if candidate_safety:
                        best_raw = max(s["raw_safety_score"] for s in candidate_safety.values())
                        for sw_order in switch_orders:
                            sid = id(sw_order)
                            raw = candidate_safety[sid]["raw_safety_score"]
                            relative_adj = min(0.0, raw - best_raw)
                            old_score = slot_0_scores.get(sid, 0.0) if slot_idx == 0 else slot_1_scores.get(sid, 0.0)
                            new_score = old_score + relative_adj
                            if slot_idx == 0:
                                slot_0_scores[sid] = new_score
                            else:
                                slot_1_scores[sid] = new_score

            # 5. Canonical joint scoring
            scored_joint_orders = self._compute_joint_scores(
                battle, config, joint_orders,
                slot_0_scores, slot_1_scores,
                _direct_absorb_blocked, _safety_blocked, _ally_redirect_blocked,
            )
            return scored_joint_orders[0]
        finally:
            self._active_config_override = old_override
            self._pure_scoring_mode = old_pure
            self._base_scores_cache = old_cache

    def choose_move(self, battle: AbstractBattle) -> BattleOrder:
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)

        # Phase 6.4.3a.3: Timing diagnostics (optional)
        _timing_enabled = getattr(self.config, "enable_decision_timing_diagnostics", False)
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

        # Initialize tracking maps for the turn
        if battle_tag not in self.active_turns:
            self.active_turns[battle_tag] = {}
        if battle_tag not in self.last_protect_turn:
            self.last_protect_turn[battle_tag] = {}
        if not hasattr(self, "opponent_active_turns") or self.opponent_active_turns is None:
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
                        self.increment_metric(self.meta_species_found_by_battle, battle_tag)
                    else:
                        self.increment_metric(self.meta_species_missing_by_battle, battle_tag)

        # Database coverage checking -- random set
        if self.config.enable_random_set_opponent_modeling and self.random_set_engine:
            for opp in battle.opponent_active_pokemon:
                if opp:
                    if self.random_set_engine.is_species_known(opp.species):
                        self.increment_metric(self.rs_species_found_by_battle, battle_tag)
                    else:
                        self.increment_metric(self.rs_species_missing_by_battle, battle_tag)

        if battle_tag not in self.battle_metrics:
            self.battle_metrics[battle_tag] = {
                "protect": 0,
                "fake_out": 0,
                "spread": 0,
                "valid_spread": 0,
                "focus_fire": 0,
                "threat_contribution": 0.0,
                "tiebreaker_activations": 0,
                "boosted_override_activations": 0
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
                        self.opponent_active_turns[battle_tag][key] = (count + 1, current_turn)
                    else:
                        self.opponent_active_turns[battle_tag][key] = (1, current_turn)
                else:
                    self.opponent_active_turns[battle_tag][key] = (1, current_turn)

        self._current_valid_orders = battle.valid_orders
        valid_orders = self._current_valid_orders
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
            ally = battle.active_pokemon[ally_idx] if ally_idx < len(battle.active_pokemon) else None
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
                if slot_idx < len(battle.force_switch) and battle.force_switch[slot_idx]:
                    continue

                orders_slot = valid_orders[slot_idx] if valid_orders and len(valid_orders) > slot_idx else []
                switch_orders = [o for o in orders_slot if o and isinstance(o.order, Pokemon)]

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
                        cand_score = slot_0_scores.get(id(ord_cand), 0.0) if slot_idx == 0 else slot_1_scores.get(id(ord_cand), 0.0)
                        if cand_score > best_action_score:
                            best_action_score = cand_score
                        t_pos = getattr(ord_cand, "move_target", None)
                        if t_pos in (1, 2):
                            t_mon = battle.opponent_active_pokemon[t_pos - 1]
                            if t_mon and self.check_move_will_ko(ord_cand.order, active_mon, t_mon, battle, config=self.config):
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
                            if self.check_move_will_ko(mv, opp, active_mon, battle, config=self.config):
                                faint_before = True
                                break
                        if faint_before:
                            break
                    if not faint_before:
                        blocked_by_ko = True

                if best_action_score >= self.config.revealed_switch_high_value_action_threshold:
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
                    old_score = slot_0_scores.get(sid, 0.0) if slot_idx == 0 else slot_1_scores.get(sid, 0.0)
                    slot_0_scores[sid] = old_score + best_bonus if slot_idx == 0 else old_score
                    slot_1_scores[sid] = old_score + best_bonus if slot_idx == 1 else old_score

                    # Build interception data for audit
                    candidate = best_bonus_order.order
                    interception = evaluate_revealed_move_switch_interception(
                        active_mon, candidate, slot_idx, battle
                    )
                    threats_for_audit = summarize_revealed_move_threats(
                        active_mon, slot_idx, active_opps, our_actives, battle
                    )
                    _revel_switch_interception_data[slot_idx] = {
                        "threatening_opponents": threats_for_audit["threatening_opponents"],
                        "threat_move_ids": threats_for_audit["revealed_move_ids"],
                        "threat_move_types": threats_for_audit["revealed_move_types"],
                        "target_likelihood": threats_for_audit["target_likelihood_weights"],
                        "active_risk": interception["active_risk"],
                        "candidate_risk": interception["candidate_risk"],
                        "risk_reduction": interception["risk_reduction"],
                        "candidate_species": getattr(candidate, "species", ""),
                        "candidate_types": [str(t) for t in getattr(candidate, "types", []) if t],
                        "candidate_hp": interception["candidate_hp"],
                        "bonus_applied": interception["proposed_score_bonus"],
                        "blocked_by_ko": False,
                        "blocked_by_high_value": False,
                        "worse_other_threat": interception["rejection_reason"] == "worse_other_threat",
                        "prediction_available": True,
                    }

        # Precompute safety blocks (canonical helper)
        _direct_absorb_blocked, _safety_blocked, _ally_redirect_blocked, _ally_redirect_blocked_meta = _compute_order_safety_blocks(
            battle, self.config, valid_orders
        )

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
            orders = valid_orders[slot_idx] if valid_orders and len(valid_orders) > slot_idx else []
            switch_orders = [o for o in orders if o and isinstance(o.order, Pokemon)]

            if not switch_orders:
                continue

            # Evaluate type safety for each switch candidate (always for diagnostics)
            active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
            candidate_safety = {}
            for sw_order in switch_orders:
                candidate = sw_order.order
                safety = evaluate_switch_candidate_type_safety(candidate, active_opps, self.config)
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
                        old_score = slot_0_scores.get(sid, 0.0) if slot_idx == 0 else slot_1_scores.get(sid, 0.0)
                        new_score = old_score + relative_adj

                        if slot_idx == 0:
                            slot_0_scores[sid] = new_score
                        else:
                            slot_1_scores[sid] = new_score

                        _switch_safety_applied[sid] = True

                # Find the best safe switch (highest adjusted score among safe candidates)
                best_safe_order = None
                best_safe_score = float('-inf')
                for sw_order in switch_orders:
                    sid = id(sw_order)
                    safety = candidate_safety[sid]
                    is_unsafe = safety["double_threat"] or safety["quad_weak_threat_count"] > 0
                    score = slot_0_scores.get(sid, 0.0) if slot_idx == 0 else slot_1_scores.get(sid, 0.0)
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
                neg_boosts["negative_boost_defensive_drop"] = neg_boosts.get("defensive_negative_stages", 0) > 0
                neg_boosts["negative_boost_speed_drop"] = neg_boosts.get("speed_negative_stage", 0) > 0

                # Check eligibility
                is_forced = battle.force_switch[slot_idx] if slot_idx < len(battle.force_switch) else False
                has_legal_switches = len(battle.available_switches) > 0
                orders_slot = valid_orders[slot_idx] if valid_orders and len(valid_orders) > slot_idx else []
                has_legal_moves = any(o and isinstance(o.order, Move) for o in orders_slot)
                has_legal_switches_in_slot = any(o and isinstance(o.order, Pokemon) for o in orders_slot)

                # Offensive drop relevant to available damaging moves
                if neg_boosts.get("offensive_negative_stages", 0) > 0:
                    for o in orders_slot:
                        if o and isinstance(o.order, Move):
                            cat = getattr(o.order, "category", None)
                            cat_name = getattr(cat, "name", "STATUS")
                            if cat_name != "STATUS" and getattr(o.order, "base_power", 0) > 0:
                                neg_boosts["negative_boost_relevant_offensive_drop"] = True
                                break

        # Phase 6.4.7: Conservative Stat-Drop Switch Scoring
        _stat_drop_scoring_data = {}
        for slot_idx in (0, 1):
            _sdata = {
                "enabled": bool(getattr(self.config, "enable_stat_drop_switch_scoring", False)),
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

            is_forced = battle.force_switch[slot_idx] if slot_idx < len(battle.force_switch) else False
            if is_forced:
                continue

            orders_slot = valid_orders[slot_idx] if valid_orders and len(valid_orders) > slot_idx else []
            pressure = evaluate_stat_drop_switch_pressure(
                active_mon, orders_slot, battle, self.config, player=self,
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
            _sdata["best_switch_score"] = best_switch_score_val if best_switch_score_val > float("-inf") else 0.0
            _sdata["best_non_switch_score"] = best_non_switch_score_val if best_non_switch_score_val > float("-inf") else 0.0

            switch_bonus = self.config.stat_drop_switch_safe_switch_bonus if self.config else 30.0

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

        _t_js_start = time.time() if _timing_enabled else 0
        scored_joint_orders = self._compute_joint_scores(
            battle, self.config, joint_orders,
            slot_0_scores, slot_1_scores,
            _direct_absorb_blocked, _safety_blocked, _ally_redirect_blocked,
        )
        _joint_order_count = len(scored_joint_orders)
        best_joint, best_score, best_score_1, best_score_2 = scored_joint_orders[0]
        if _timing_enabled:
            _t_joint_scoring = (time.time() - _t_js_start) * 1000

        # Phase 6.3.5b: Pure Counterfactual Check for Singleton Levitate Safety (per-slot)
        singleton_selection_changed_by_safety_slot = [False, False]
        if self.config.ability_hard_safety_allow_singleton_deduction:
            import dataclasses
            config_no_singleton = dataclasses.replace(
                self.config,
                ability_hard_safety_allow_singleton_deduction=False
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
                sel_order = best_joint.first_order if _slot_i == 0 else best_joint.second_order
                cf_order = cf_best_joint.first_order if _slot_i == 0 else cf_best_joint.second_order
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
                    _order_action_key(cf_result[0].first_order if cf_result[0] else None),
                    _order_action_key(cf_result[0].second_order if cf_result[0] else None),
                ]
            except Exception:
                _stat_drop_counterfactual_joint = None
                _stat_drop_counterfactual_actions = [("", "", 0), ("", "", 0)]

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
                legacy_score_1 = _legacy_slot_scores[0].get(id(first), 0.0) if first else 0.0
                legacy_score_2 = _legacy_slot_scores[1].get(id(second), 0.0) if second else 0.0
                legacy_joint_score = legacy_score_1 + legacy_score_2
                # Apply same synergy penalties (but not interception bonuses)
                first_blocked = _direct_absorb_blocked.get(id(first), False) if first else False
                second_blocked = _direct_absorb_blocked.get(id(second), False) if second else False
                either_blocked = first_blocked or second_blocked
                if not either_blocked:
                    if isinstance(first.order, Move) and isinstance(second.order, Move):
                        if first.move_target == second.move_target and first.move_target in (1, 2):
                            target_opp = battle.opponent_active_pokemon[first.move_target - 1]
                            if target_opp:
                                ko_1 = self.check_move_will_ko(first.order, battle.active_pokemon[0], target_opp, battle, config=self.config)
                                ko_2 = self.check_move_will_ko(second.order, battle.active_pokemon[1], target_opp, battle, config=self.config)
                                opp_hp_fraction = getattr(target_opp, "current_hp_fraction", 1.0)
                                if (ko_1 and ko_2) or (ko_1 or ko_2) and opp_hp_fraction < 0.15 or opp_hp_fraction < 0.08:
                                    allow_double = False
                                    if self.config.enable_threat_scoring:
                                        threat_score = self.score_opponent_threat(target_opp, battle)
                                        if threat_score >= 0.50:
                                            allow_double = True
                                    if not allow_double:
                                        legacy_joint_score -= 250.0
                    if self.config.enable_order_aware_overkill:
                        if self.selected_target_will_be_koed_before_second_action(first, second, battle, config=self.config):
                            legacy_joint_score -= self.config.order_aware_overkill_penalty
                legacy_scored_joint.append((joint_order, legacy_joint_score, legacy_score_1, legacy_score_2))
            legacy_scored_joint.sort(key=lambda x: x[1], reverse=True)
            if legacy_scored_joint:
                _legacy_joint_order, _, _, _ = legacy_scored_joint[0]
                # Compare selected vs legacy
                legacy_msg = self.safe_get_joint_message(_legacy_joint_order) if _legacy_joint_order else ""
                selected_msg = self.safe_get_joint_message(best_joint) if best_joint else ""
                if legacy_msg != selected_msg:
                    _selection_changed = True
                    # Check if changed to a switch
                    if _legacy_joint_order:
                        l_first = _legacy_joint_order.first_order
                        l_second = _legacy_joint_order.second_order
                        if isinstance(l_first, SingleBattleOrder) and isinstance(l_first.order, Pokemon):
                            _changed_to_switch = True
                        if isinstance(l_second, SingleBattleOrder) and isinstance(l_second.order, Pokemon):
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
        singleton_selection_changed_by_safety_list = list(singleton_selection_changed_by_safety_slot)
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
            
            valid_orders_slot = valid_orders[active_idx] if valid_orders and len(valid_orders) > active_idx and valid_orders[active_idx] else []

            # Phase 6.3.5b: Observer Config & Audit Separation
            import dataclasses
            observer_config = dataclasses.replace(self.config, ability_hard_safety_allow_singleton_deduction=True)

            # 1. singleton_levitate_opportunity_observed
            opportunity_observed = False
            for opp in battle.opponent_active_pokemon:
                if opp and not getattr(opp, "fainted", False):
                    res = resolve_known_ability(opp, battle, config=observer_config)
                    if res["source"] == "deterministic_singleton" and res["ability"] == "levitate":
                        opportunity_observed = True
            singleton_levitate_opportunity_observed_list[active_idx] = opportunity_observed

            # 2. singleton_ground_into_levitate_selected_observed
            ground_selected_observed = False
            chosen_order = best_joint.first_order if active_idx == 0 else best_joint.second_order
            if chosen_order and isinstance(chosen_order.order, Move):
                chosen_move = chosen_order.order
                target_pos = chosen_order.move_target
                if target_pos in (1, 2):
                    target_mon = battle.opponent_active_pokemon[target_pos - 1]
                    if target_mon and not getattr(target_mon, "fainted", False):
                        res = resolve_known_ability(target_mon, battle, config=observer_config)
                        if res["source"] == "deterministic_singleton" and res["ability"] == "levitate" and not res["is_currently_suppressed"]:
                            move_type = getattr(chosen_move, "type", None)
                            m_type = move_type.name.upper() if move_type and hasattr(move_type, "name") else str(move_type).upper()
                            base_power = getattr(chosen_move, "base_power", 0)
                            if m_type == "GROUND" and base_power > 0:
                                # Apply exclusions: Gravity, Thousand Arrows, Mold Breaker
                                if not is_gravity_active(battle) and getattr(chosen_move, "id", "").lower() != "thousandarrows" and not attacker_ignores_target_ability(active_mon, battle):
                                    ground_selected_observed = True
            singleton_ground_into_levitate_selected_observed_list[active_idx] = ground_selected_observed

            # 3. singleton_hard_block_applied
            hard_block_applied = False
            if self.config.ability_hard_safety_allow_singleton_deduction:
                for ord_cand in valid_orders_slot:
                    if ord_cand and isinstance(ord_cand.order, Move):
                        cand_move = ord_cand.order
                        cand_target_pos = ord_cand.move_target
                        if cand_target_pos in (1, 2):
                            cand_target_mon = battle.opponent_active_pokemon[cand_target_pos - 1]
                            if cand_target_mon and not getattr(cand_target_mon, "fainted", False):
                                res_cand = resolve_known_ability(cand_target_mon, battle, self.config)
                                if res_cand["source"] == "deterministic_singleton" and res_cand["ability"] == "levitate" and not res_cand["is_currently_suppressed"]:
                                    blocks_cand, reason = ability_hard_blocks_move(cand_move, active_mon, cand_target_mon, battle, config=self.config)
                                    if blocks_cand and _ability_block_enabled(self.config, reason):
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
                        cand_target_mon = battle.opponent_active_pokemon[cand_target_pos - 1]
                        if cand_target_mon and not getattr(cand_target_mon, "fainted", False):
                            res_cand = resolve_known_ability(cand_target_mon, battle, config=observer_config)
                            if res_cand["source"] == "deterministic_singleton" and res_cand["ability"] == "levitate" and not res_cand["is_currently_suppressed"]:
                                move_type = getattr(cand_move, "type", None)
                                m_type = move_type.name.upper() if move_type and hasattr(move_type, "name") else str(move_type).upper()
                                base_power = getattr(cand_move, "base_power", 0)
                                if m_type == "GROUND" and base_power > 0:
                                    if not is_gravity_active(battle) and getattr(cand_move, "id", "").lower() != "thousandarrows" and not attacker_ignores_target_ability(active_mon, battle):
                                        blocked_candidate_observed = True
                                        break
            singleton_blocked_candidate_observed_list[active_idx] = blocked_candidate_observed

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
                    chosen_target_mon = battle.opponent_active_pokemon[chosen_target_pos - 1]
                    if chosen_target_mon:
                        res = resolve_known_ability(chosen_target_mon, battle, config=observer_config)
                        resolution_source = res["source"]
            if not resolution_source:
                for ord_cand in valid_orders_slot:
                    if ord_cand and isinstance(ord_cand.order, Move):
                        cand_target_pos = ord_cand.move_target
                        if cand_target_pos in (1, 2):
                            cand_target_mon = battle.opponent_active_pokemon[cand_target_pos - 1]
                            if cand_target_mon:
                                res_cand = resolve_known_ability(cand_target_mon, battle, config=observer_config)
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
                            deterministic_singleton_ability_list[active_idx] = res["ability"]
                            deterministic_singleton_target_species_list[active_idx] = target_mon.species
                        singleton_ability_suppressed_list[active_idx] = res["is_currently_suppressed"]
                        singleton_ability_suppression_reason_list[active_idx] = res["suppression_reason"]

                        move_type = getattr(chosen_move, "type", None)
                        m_type = move_type.name.upper() if move_type and hasattr(move_type, "name") else str(move_type).upper()
                        if res["ability"] == "levitate" and m_type == "GROUND" and res["source"] == "deterministic_singleton" and not res["is_currently_suppressed"]:
                            singleton_ground_into_levitate_selected_list[active_idx] = True

            singleton_blocked_candidate_exists = False
            singleton_blocked_sample = None
            for ord_cand in valid_orders_slot:
                if not ord_cand or not isinstance(ord_cand.order, Move):
                    continue
                cand_move = ord_cand.order
                cand_target_pos = ord_cand.move_target
                if cand_target_pos in (1, 2):
                    cand_target_mon = battle.opponent_active_pokemon[cand_target_pos - 1]
                    if cand_target_mon:
                        res_cand = resolve_known_ability(cand_target_mon, battle, self.config)
                        if res_cand["source"] == "deterministic_singleton" and res_cand["ability"] and not res_cand["is_currently_suppressed"]:
                            blocks_cand, _ = ability_hard_blocks_move(cand_move, active_mon, cand_target_mon, battle, self.config)
                            if blocks_cand:
                                singleton_blocked_candidate_exists = True
                                singleton_blocked_sample = (res_cand, cand_target_mon)
                                break

            is_chosen_blocked = False
            if chosen_order and isinstance(chosen_order.order, Move):
                chosen_target_pos = chosen_order.move_target
                if chosen_target_pos in (1, 2):
                    chosen_target_mon = battle.opponent_active_pokemon[chosen_target_pos - 1]
                    if chosen_target_mon:
                        is_chosen_blocked, _ = ability_hard_blocks_move(chosen_order.order, active_mon, chosen_target_mon, battle, self.config)

            if singleton_blocked_candidate_exists and not is_chosen_blocked:
                singleton_ability_hard_block_avoided_list[active_idx] = True
                if singleton_blocked_sample:
                    res_cand, target_mon = singleton_blocked_sample
                    known_ability_resolution_source_list[active_idx] = res_cand["source"]
                    deterministic_singleton_ability_used_list[active_idx] = True
                    deterministic_singleton_ability_list[active_idx] = res_cand["ability"]
                    deterministic_singleton_target_species_list[active_idx] = target_mon.species
            chosen_order = best_joint.first_order if active_idx == 0 else best_joint.second_order
            slot_scores = slot_0_scores if active_idx == 0 else slot_1_scores
            
            # 1. Determine if the chosen action is a blocked action or redirected-blocked action
            is_chosen_blocked = False
            is_chosen_redirected = False
            
            if chosen_order and isinstance(chosen_order.order, Move):
                chosen_move = chosen_order.order
                chosen_target_pos = chosen_order.move_target
                if chosen_target_pos in (1, 2):
                    chosen_target_mon = battle.opponent_active_pokemon[chosen_target_pos - 1]
                    if chosen_target_mon:
                        blocks, reason = ability_hard_blocks_move(chosen_move, active_mon, chosen_target_mon, battle, config=self.config)
                        if blocks and _ability_block_enabled(self.config, reason):
                            is_chosen_blocked = True
                        else:
                            redirects, red_reason = ability_redirects_single_target_move(
                                chosen_move, chosen_target_mon, battle.opponent_active_pokemon, active_mon, battle
                            )
                            if redirects:
                                red_target = None
                                for opp in battle.opponent_active_pokemon:
                                    if opp and opp != chosen_target_mon and not getattr(opp, "fainted", False):
                                        opp_ability = get_known_ability(opp, battle)
                                        if opp_ability in ("stormdrain", "lightningrod"):
                                            red_target = opp
                                            break
                                if red_target:
                                    blocks_red, reason_red = ability_hard_blocks_move(chosen_move, active_mon, red_target, battle, config=self.config)
                                    if blocks_red and _ability_block_enabled(self.config, reason_red):
                                        is_chosen_redirected = True
                elif is_opponent_spread_move(chosen_move, chosen_order):
                    for opp in battle.opponent_active_pokemon:
                        if opp:
                            blocked, reason = ability_hard_blocks_move(chosen_move, active_mon, opp, battle, config=self.config)
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
                    cand_target_mon = battle.opponent_active_pokemon[cand_target_pos - 1]
                    if cand_target_mon:
                        blocks, reason = ability_hard_blocks_move(cand_move, active_mon, cand_target_mon, battle, config=self.config)
                        if blocks and _ability_block_enabled(self.config, reason):
                            hard_block_candidate_exists = True
                            if not block_sample:
                                block_sample = (reason, cand_target_mon)
                        else:
                            redirects, red_reason = ability_redirects_single_target_move(
                                cand_move, cand_target_mon, battle.opponent_active_pokemon, active_mon, battle
                            )
                            if redirects:
                                red_target = None
                                for opp in battle.opponent_active_pokemon:
                                    if opp and opp != cand_target_mon and not getattr(opp, "fainted", False):
                                        opp_ability = get_known_ability(opp, battle)
                                        if opp_ability in ("stormdrain", "lightningrod"):
                                            red_target = opp
                                            break
                                if red_target:
                                    blocks_red, reason_red = ability_hard_blocks_move(cand_move, active_mon, red_target, battle, config=self.config)
                                    if blocks_red and _ability_block_enabled(self.config, reason_red):
                                        redirection_candidate_exists = True
                                        if not redirection_sample:
                                            redirection_sample = (red_reason, red_target)
                elif is_opponent_spread_move(cand_move, ord_cand):
                    for opp in battle.opponent_active_pokemon:
                        if opp:
                            blocked, reason = ability_hard_blocks_move(cand_move, active_mon, opp, battle, config=self.config)
                            if blocked and _ability_block_enabled(self.config, reason):
                                hard_block_candidate_exists = True
                                if not block_sample:
                                    block_sample = (reason, opp)
                                break

            # 3. Set the avoided flags and deterministic samples
            if hard_block_candidate_exists and not is_chosen_blocked:
                self._ability_hard_block_avoided[battle_tag][active_idx] = True
                if block_sample and not self._ability_block_reason[battle_tag][active_idx]:
                    reason, target_mon = block_sample
                    self._ability_block_reason[battle_tag][active_idx] = reason
                    self._ability_blocked_target_species[battle_tag][active_idx] = target_mon.species
                    self._ability_blocked_target_ability[battle_tag][active_idx] = get_known_ability(target_mon, battle) or ""
            
            if redirection_candidate_exists and not is_chosen_redirected:
                self._ability_redirection_avoided[battle_tag][active_idx] = True
                if redirection_sample and not self._ability_block_reason[battle_tag][active_idx]:
                    reason, target_mon = redirection_sample
                    self._ability_block_reason[battle_tag][active_idx] = reason
                    self._ability_blocked_target_species[battle_tag][active_idx] = target_mon.species
                    self._ability_blocked_target_ability[battle_tag][active_idx] = get_known_ability(target_mon, battle) or ""

            # Phase 6.3.3 direct safety calculations (audit / logging paths)
            is_chosen_direct_blocked = False
            chosen_direct_reason = ""
            chosen_direct_target_mon = None
            if chosen_order and isinstance(chosen_order.order, Move):
                chosen_move = chosen_order.order
                chosen_target_pos = chosen_order.move_target
                if chosen_target_pos in (1, 2):
                    chosen_direct_target_mon = battle.opponent_active_pokemon[chosen_target_pos - 1]
                    if chosen_direct_target_mon:
                        if not is_opponent_spread_move(chosen_move, chosen_order):
                            blocks_d, reason_d = direct_known_absorb_blocks_move(chosen_move, active_mon, chosen_direct_target_mon, battle, chosen_order)
                            if blocks_d:
                                is_chosen_direct_blocked = True
                                chosen_direct_reason = reason_d

            if is_chosen_direct_blocked and chosen_direct_target_mon:
                self._direct_absorb_immune_move_selected[battle_tag][active_idx] = True
                self._direct_absorb_block_reason[battle_tag][active_idx] = chosen_direct_reason
                self._direct_absorb_target_species[battle_tag][active_idx] = chosen_direct_target_mon.species
                self._direct_absorb_target_ability[battle_tag][active_idx] = get_known_ability(chosen_direct_target_mon, battle) or ""

            direct_block_candidate_exists = False
            direct_block_sample = None
            for ord_cand in valid_orders_slot:
                if not ord_cand or not isinstance(ord_cand.order, Move):
                    continue
                cand_move = ord_cand.order
                cand_target_pos = ord_cand.move_target
                if cand_target_pos in (1, 2):
                    cand_target_mon = battle.opponent_active_pokemon[cand_target_pos - 1]
                    if cand_target_mon:
                        if not is_opponent_spread_move(cand_move, ord_cand):
                            blocks_d, reason_d = direct_known_absorb_blocks_move(cand_move, active_mon, cand_target_mon, battle, ord_cand)
                            if blocks_d:
                                direct_block_candidate_exists = True
                                if not direct_block_sample:
                                    direct_block_sample = (reason_d, cand_target_mon)

            if direct_block_candidate_exists and not is_chosen_direct_blocked:
                if getattr(self.config, "ability_hard_safety_direct_absorb_only", False):
                    self._direct_absorb_hard_block_avoided[battle_tag][active_idx] = True
                    if direct_block_sample and not self._direct_absorb_block_reason[battle_tag][active_idx]:
                        reason_d, target_mon = direct_block_sample
                        self._direct_absorb_block_reason[battle_tag][active_idx] = reason_d
                        self._direct_absorb_target_species[battle_tag][active_idx] = target_mon.species
                        self._direct_absorb_target_ability[battle_tag][active_idx] = get_known_ability(target_mon, battle) or ""

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
            
            if chosen_order and isinstance(chosen_order.order, Move) and getattr(chosen_order.order, "base_power", 0) > 0:
                chosen_move = chosen_order.order
                chosen_target_pos = chosen_order.move_target
                
                absorb_selected_move_id = chosen_move.id

                # Check single-target move
                if chosen_target_pos in (1, 2):
                    chosen_target_mon = battle.opponent_active_pokemon[chosen_target_pos - 1]
                    if chosen_target_mon:
                        intended_species = chosen_target_mon.species
                        intended_ability = get_known_ability(chosen_target_mon, battle) or ""

                        # Check direct block
                        blocks, reason = ability_hard_blocks_move(chosen_move, active_mon, chosen_target_mon, battle, config=self.config)
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
                                blocked_target_species = chosen_target_mon.species  # effective for streak
                                blocked_target_reason = reason

                        # Check redirection block
                        if not absorb_immune_move_selected:
                            redirects, red_reason = ability_redirects_single_target_move(
                                chosen_move, chosen_target_mon, battle.opponent_active_pokemon, active_mon, battle
                            )
                            if redirects:
                                red_target = None
                                for opp in battle.opponent_active_pokemon:
                                    if opp and opp != chosen_target_mon and not getattr(opp, "fainted", False):
                                        opp_ability = get_known_ability(opp, battle)
                                        if opp_ability in ("stormdrain", "lightningrod"):
                                            red_target = opp
                                            break
                                if red_target:
                                    blocks_red, reason_red = ability_hard_blocks_move(chosen_move, active_mon, red_target, battle, config=self.config)
                                    if blocks_red:
                                        target_ab = get_known_ability(red_target, battle)
                                        if is_known_absorb_ability(target_ab):
                                            absorb_immune_move_selected = True
                                            absorb_error_reason = reason_red
                                            # Redirection: intended is chosen slot, effective is redirector
                                            absorb_via_redirection = True
                                            absorb_intended_target_species = intended_species
                                            absorb_intended_target_ability = intended_ability
                                            absorb_effective_target_species = red_target.species
                                            absorb_effective_target_ability = get_known_ability(red_target, battle) or ""
                                            blocked_target_species = red_target.species  # effective for streak
                                            blocked_target_reason = reason_red

                # Check spread move
                elif is_opponent_spread_move(chosen_move, chosen_order):
                    opponents = [opp for opp in battle.opponent_active_pokemon if opp and not getattr(opp, "fainted", False)]
                    if opponents:
                        blocked_opps = []
                        blocked_reasons = []
                        for opp in opponents:
                            blocked, reason = ability_hard_blocks_move(chosen_move, active_mon, opp, battle, config=self.config)
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
                            blocked_target_species = "+".join(sorted([o.species for o in blocked_opps]))
                            blocked_target_reason = "+".join(sorted(blocked_reasons))
                            absorb_error_reason = blocked_target_reason
                            # Spread: no redirection concept; intended == effective == all blocked
                            absorb_via_redirection = False
                            absorb_intended_target_species = blocked_target_species
                            absorb_intended_target_ability = "+".join(sorted([get_known_ability(o, battle) or "" for o in blocked_opps]))
                            absorb_effective_target_species = blocked_target_species
                            absorb_effective_target_ability = absorb_intended_target_ability

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
                    if ord_cand is (best_joint.first_order if active_idx == 0 else best_joint.second_order):
                        continue
                    cand_score = slot_scores.get(id(ord_cand), 0.0)
                    if isinstance(ord_cand.order, Pokemon):
                        if cand_score > 0.0:
                            has_switch = True
                    elif isinstance(ord_cand.order, Move):
                        move_obj = ord_cand.order
                        if getattr(move_obj, "base_power", 0) > 0:
                            # Use canonical precomputed score; safety predicate only
                            is_safe = is_alternative_safe_damaging_predicate(ord_cand, active_mon, battle)
                            if is_safe and cand_score > 0.0:
                                safe_alt_available = True
                                if cand_score > best_safe_alt_score:
                                    best_safe_alt_score = cand_score
                                    best_safe_alt_move = move_obj.id
                                    if ord_cand.move_target in (1, 2):
                                        t_mon = battle.opponent_active_pokemon[ord_cand.move_target - 1]
                                        best_safe_alt_target = t_mon.species if t_mon else f"opponent_{ord_cand.move_target}"
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
                curr_effective_target = blocked_target_species  # effective (redirected) target
                curr_reason_key = blocked_target_reason
                curr_turn = battle.turn

                streak_key = curr_attacker_ident
                battle_streak_map = self._absorb_streak_state[battle_tag]
                prev_state = battle_streak_map.get(streak_key)

                if prev_state is not None and (
                    prev_state["move"] == curr_move_id and
                    prev_state["effective_target"] == curr_effective_target and
                    prev_state["reason"] == curr_reason_key
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
                    "streak": new_streak
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
            chosen_order = best_joint.first_order if active_idx == 0 else best_joint.second_order
            
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
                        priority_res = evaluate_priority_move_legality(chosen_move, active_mon, target_mon, battle, self.config)
                        if priority_res["is_priority_move"]:
                            priority_target_grounded = priority_res["intended_target_grounded"]
                            priority_target_species = target_mon.species
                            t_types = getattr(target_mon, "types", [])
                            if len(t_types) > 0 and t_types[0]:
                                priority_target_type_1 = t_types[0].name.upper() if hasattr(t_types[0], "name") else str(t_types[0]).upper()
                            if len(t_types) > 1 and t_types[1]:
                                priority_target_type_2 = t_types[1].name.upper() if hasattr(t_types[1], "name") else str(t_types[1]).upper()
                            
                            priority_blocking_ability = priority_res["blocking_ability"]
                            priority_blocking_ability_source = priority_res["blocking_ability_source"]
                            
                            if priority_res["blocked"]:
                                priority_blocked = True
                                priority_block_reason = priority_res["reason"]
                                if priority_res["reason"] == "priority_blocked_by_psychic_terrain":
                                    priority_selected_into_psychic_terrain = True
                                    if getattr(chosen_move, "id", "").lower() == "suckerpunch":
                                        sucker_punch_selected_into_psychic_terrain = True

            # 2. Check if a blocked candidate was avoided
            priority_blocked_candidate_exists = False
            priority_blocked_sample = None
            
            for ord_cand in valid_orders_slot:
                if not ord_cand or not isinstance(ord_cand.order, Move):
                    continue
                cand_move = ord_cand.order
                cand_target_pos = ord_cand.move_target
                if cand_target_pos in (1, 2):
                    cand_target_mon = battle.opponent_active_pokemon[cand_target_pos - 1]
                    if cand_target_mon:
                        priority_res_cand = evaluate_priority_move_legality(cand_move, active_mon, cand_target_mon, battle, self.config)
                        if priority_res_cand["blocked"]:
                            priority_blocked_candidate_exists = True
                            priority_blocked_sample = (priority_res_cand, cand_target_mon)
                            break
                            
            priority_block_avoided = False
            if priority_blocked_candidate_exists and not priority_blocked:
                priority_block_avoided = True
                if priority_blocked_sample:
                    priority_res_cand, target_mon = priority_blocked_sample
                    priority_target_grounded = priority_res_cand["intended_target_grounded"]
                    priority_target_species = target_mon.species
                    t_types = getattr(target_mon, "types", [])
                    if len(t_types) > 0 and t_types[0]:
                        priority_target_type_1 = t_types[0].name.upper() if hasattr(t_types[0], "name") else str(t_types[0]).upper()
                    if len(t_types) > 1 and t_types[1]:
                        priority_target_type_2 = t_types[1].name.upper() if hasattr(t_types[1], "name") else str(t_types[1]).upper()
                    priority_blocking_ability = priority_res_cand["blocking_ability"]
                    priority_blocking_ability_source = priority_res_cand["blocking_ability_source"]
                    priority_block_reason = priority_res_cand["reason"]
                    
            # 3. Check only-legal
            priority_only_legal = False
            if priority_blocked and len(valid_orders_slot) == 1:
                priority_only_legal = True

            # Assign lists
            priority_move_field_blocked_list[active_idx] = priority_blocked
            priority_move_block_reason_list[active_idx] = priority_block_reason
            priority_move_selected_into_psychic_terrain_list[active_idx] = priority_selected_into_psychic_terrain
            sucker_punch_selected_into_psychic_terrain_list[active_idx] = sucker_punch_selected_into_psychic_terrain
            priority_move_block_avoided_list[active_idx] = priority_block_avoided
            priority_move_only_legal_list[active_idx] = priority_only_legal
            priority_target_grounded_list[active_idx] = priority_target_grounded
            priority_target_species_list[active_idx] = priority_target_species
            priority_target_type_1_list[active_idx] = priority_target_type_1
            priority_target_type_2_list[active_idx] = priority_target_type_2
            priority_blocking_ability_list[active_idx] = priority_blocking_ability
            priority_blocking_ability_source_list[active_idx] = priority_blocking_ability_source

            # Assign lists
            absorb_immune_move_selected_list[active_idx] = absorb_immune_move_selected
            absorb_selection_forced_list[active_idx] = absorb_selection_forced
            absorb_safe_alternative_available_list[active_idx] = absorb_safe_alternative_available
            absorb_best_safe_alternative_move_list[active_idx] = absorb_best_safe_alternative_move
            absorb_best_safe_alternative_target_list[active_idx] = absorb_best_safe_alternative_target
            absorb_best_safe_alternative_score_list[active_idx] = absorb_best_safe_alternative_score
            absorb_selected_score_list[active_idx] = absorb_selected_score
            absorb_selected_streak_list[active_idx] = absorb_selected_streak
            # Phase 6.3.6: Direct known absorb repeat detection
            _direct_absorb_selected = self._direct_absorb_immune_move_selected.get(battle_tag, {}).get(active_idx, False)
            direct_known_absorb_repeat_selected_list[active_idx] = (
                _direct_absorb_selected and absorb_selected_streak >= 2
            )
            avoidable_absorb_error_list[active_idx] = avoidable_absorb_error
            productive_partial_absorb_spread_list[active_idx] = productive_partial_absorb_spread
            absorb_error_reason_list[active_idx] = absorb_error_reason
            # Phase 6.3.2a new target diagnostic fields
            absorb_via_redirection_list[active_idx] = absorb_via_redirection
            absorb_intended_target_species_list[active_idx] = absorb_intended_target_species
            absorb_intended_target_ability_list[active_idx] = absorb_intended_target_ability
            absorb_effective_target_species_list[active_idx] = absorb_effective_target_species
            absorb_effective_target_ability_list[active_idx] = absorb_effective_target_ability
            absorb_selected_move_id_list[active_idx] = absorb_selected_move_id


        # Re-evaluate Synergy Rule 1 meta Protect penalty for chosen orders -- old meta engine
        if self.config.enable_meta_opponent_modeling and self.meta_engine:
            fo_1 = best_joint.first_order
            fo_2 = best_joint.second_order
            if fo_1 and fo_2 and isinstance(fo_1.order, Move) and isinstance(fo_2.order, Move):
                if fo_1.move_target == fo_2.move_target and fo_1.move_target in (1, 2):
                    target_opp = battle.opponent_active_pokemon[fo_1.move_target - 1]
                    if target_opp:
                        t_species = target_opp.species
                        t_revealed = list(target_opp.moves.keys())
                        likely_protect, prob, reason = self.meta_engine.likely_has_protect(
                            t_species, t_revealed, threshold=self.config.meta_move_probability_threshold
                        )
                        if likely_protect:
                            self.increment_metric(self.selected_meta_predictions_by_battle, battle_tag)
                            self.increment_metric(self.meta_predictions_used_by_battle, battle_tag)
                            self.increment_metric(self.meta_protect_predictions_by_battle, battle_tag)
                            self.total_meta_score_delta_by_battle[battle_tag] = self.total_meta_score_delta_by_battle.get(battle_tag, 0.0) + 15.0
                            if self.verbose:
                                print(f"[Meta Prediction] species={t_species} type=protect prob={prob:.2f} action=joint_double_target delta=-15.0")

        # Re-evaluate joint Protect double-targeting for random-set engine
        if self.config.enable_random_set_opponent_modeling and self.random_set_engine:
            fo_1 = best_joint.first_order
            fo_2 = best_joint.second_order
            if fo_1 and fo_2 and isinstance(fo_1.order, Move) and isinstance(fo_2.order, Move):
                if fo_1.move_target == fo_2.move_target and fo_1.move_target in (1, 2):
                    target_opp = battle.opponent_active_pokemon[fo_1.move_target - 1]
                    if target_opp:
                        t_species = target_opp.species
                        t_revealed = list(target_opp.moves.keys())
                        likely_protect, prob, _ = self.random_set_engine.likely_has_protect(
                            t_species, t_revealed, threshold=self.config.random_set_probability_threshold
                        )
                        if likely_protect:
                            self.increment_metric(self.rs_selected_predictions_by_battle, battle_tag)
                            self.increment_metric(self.rs_predictions_used_by_battle, battle_tag)
                            self.increment_metric(self.rs_protect_predictions_by_battle, battle_tag)
                            self.rs_score_delta_by_battle[battle_tag] = (
                                self.rs_score_delta_by_battle.get(battle_tag, 0.0) + 12.0
                            )
                            if self.verbose:
                                print(f"[RS Prediction] protect: {t_species} p={prob:.2f} joint_double_target delta=-12.0")

        # Increment metrics and track Protect turn for chosen orders
        for idx, order in enumerate([best_joint.first_order, best_joint.second_order]):
            if order and isinstance(order.order, Move):
                m = order.order
                if m.id in ("protect", "detect", "spikyshield", "kingsshield", "banefulbunker"):
                    self.battle_metrics[battle_tag]["protect"] += 1
                    mon = battle.active_pokemon[idx]
                    if mon:
                        mon_id = self.get_pokemon_identifier(mon)
                        self.last_protect_turn.setdefault(battle_tag, {})[(idx, mon_id)] = current_turn
                elif m.id == "fakeout":
                    self.battle_metrics[battle_tag]["fake_out"] += 1
                if is_opponent_spread_move(m, order):
                    self.battle_metrics[battle_tag]["spread"] += 1
                    is_inefficient = self.inefficient_partial_spread_by_battle.get(battle_tag, {}).get(idx, False)
                    if not is_inefficient:
                        self.battle_metrics[battle_tag]["valid_spread"] = self.battle_metrics[battle_tag].get("valid_spread", 0) + 1

        # Check for focus-fire metric (both target the same opponent)
        fo_1 = best_joint.first_order
        fo_2 = best_joint.second_order
        if fo_1 and fo_2 and isinstance(fo_1.order, Move) and isinstance(fo_2.order, Move):
            if fo_1.move_target == fo_2.move_target and fo_1.move_target in (1, 2):
                self.battle_metrics[battle_tag]["focus_fire"] += 1

        # Increment threat contribution metric if enabled
        if self.config.enable_threat_scoring:
            threat_contrib = 0.0
            for idx, order in enumerate([best_joint.first_order, best_joint.second_order]):
                if order and isinstance(order.order, Move) and order.move_target in (1, 2):
                    target_mon = battle.opponent_active_pokemon[order.move_target - 1]
                    if target_mon:
                        threat_score = self.score_opponent_threat(target_mon, battle)
                        threat_contrib += threat_score * self.config.threat_targeting_weight
            self.battle_metrics[battle_tag]["threat_contribution"] += threat_contrib

        # Check and increment tiebreaker and boosted override activations per battle
        for idx, order in enumerate([best_joint.first_order, best_joint.second_order]):
            if order and isinstance(order.order, Move) and getattr(order.order, "base_power", 0) > 0 and order.move_target in (1, 2):
                target_mon = battle.opponent_active_pokemon[order.move_target - 1]
                active_mon = battle.active_pokemon[idx]
                if target_mon and active_mon:
                    # Let's check tiebreaker
                    if self.config.enable_threat_tiebreaker:
                        # 1. No candidate move can KO
                        any_ko = False
                        for cand_order in self.get_valid_orders_for_slot(idx, battle):
                            if isinstance(cand_order.order, Move) and cand_order.move_target in (1, 2):
                                t_mon = battle.opponent_active_pokemon[cand_order.move_target - 1]
                                if t_mon and self.check_move_will_ko(cand_order.order, battle.active_pokemon[idx], t_mon, battle, config=self.config):
                                    any_ko = True
                                    break
                        
                        # 2. No opponent HP < 35%
                        any_low_hp = any(opp and getattr(opp, "current_hp_fraction", 1.0) < self.config.low_hp_target_threshold for opp in battle.opponent_active_pokemon)
                        
                        if not any_ko and not any_low_hp:
                            # 3. Top candidate scores are close
                            if not self._base_scores_cache[idx]:
                                for cand_order in self.get_valid_orders_for_slot(idx, battle):
                                    self._base_scores_cache[idx][id(cand_order)] = self.score_action(
                                        cand_order, idx, battle, with_tiebreaker=False
                                    )
                            cands = list(self._base_scores_cache[idx].values())
                            if len(cands) >= 2:
                                cands.sort(reverse=True)
                                if cands[0] - cands[1] <= self.config.threat_tiebreaker_score_gap:
                                    self.battle_metrics[battle_tag]["tiebreaker_activations"] += 1
                                    self.tiebreaker_activations_by_battle.setdefault(battle_tag, 0)
                                    self.tiebreaker_activations_by_battle[battle_tag] += 1
 
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
                            for cand_order in self.get_valid_orders_for_slot(idx, battle):
                                if isinstance(cand_order.order, Move) and cand_order.move_target in (1, 2):
                                    t_mon = battle.opponent_active_pokemon[cand_order.move_target - 1]
                                    if t_mon and self.check_move_will_ko(cand_order.order, battle.active_pokemon[idx], t_mon, battle, config=self.config):
                                        any_ko = True
                                        break
                            
                            # 2. No opponent HP < 35%
                            any_low_hp = any(opp and getattr(opp, "current_hp_fraction", 1.0) < self.config.low_hp_target_threshold for opp in battle.opponent_active_pokemon)
                            
                            is_emergency = max_boost >= self.config.boosted_override_emergency_stage
                            if is_emergency or (not any_ko and not any_low_hp):
                                self.battle_metrics[battle_tag]["boosted_override_activations"] += 1
                                self.boosted_override_activations_by_battle.setdefault(battle_tag, 0)
                                self.boosted_override_activations_by_battle[battle_tag] += 1

        active_1 = battle.active_pokemon[0]
        active_2 = battle.active_pokemon[1]
        opp_1 = battle.opponent_active_pokemon[0]
        opp_2 = battle.opponent_active_pokemon[1]

        if self.verbose:
            print(f"\n--- Turn {battle.turn} | Battle: {battle.battle_tag} ---")
            print(f"Actives: P1={active_1.species if active_1 else None} | P2={active_2.species if active_2 else None}")
            print(f"Opponents: O1={opp_1.species if opp_1 else None} | O2={opp_2.species if opp_2 else None}")
            print(f"Best Joint Order: {self.safe_get_joint_message(best_joint)} (Score: {best_score:.2f} = {best_score_1:.2f} + {best_score_2:.2f})")

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
                second_score=best_score_2
            )

        # Collect decision audit data if audit_logger is present
        if self.audit_logger:
            # 1. overkill penalty triggered
            overkill_triggered = False
            first_order = best_joint.first_order
            second_order = best_joint.second_order
            if first_order and second_order and isinstance(first_order.order, Move) and isinstance(second_order.order, Move):
                if first_order.move_target == second_order.move_target and first_order.move_target in (1, 2):
                    target_opp = battle.opponent_active_pokemon[first_order.move_target - 1]
                    if target_opp:
                        ko_1 = self.check_move_will_ko(first_order.order, battle.active_pokemon[0], target_opp, battle, config=self.config)
                        ko_2 = self.check_move_will_ko(second_order.order, battle.active_pokemon[1], target_opp, battle, config=self.config)
                        opp_hp_fraction = getattr(target_opp, "current_hp_fraction", 1.0)
                        if (ko_1 and ko_2) or ((ko_1 or ko_2) and opp_hp_fraction < 0.15) or opp_hp_fraction < 0.08:
                            allow_double = False
                            if self.config.enable_threat_scoring:
                                threat_score = self.score_opponent_threat(target_opp, battle)
                                if threat_score >= 0.50:
                                    allow_double = True
                            if not allow_double:
                                overkill_triggered = True

            # 2. focus-fire bonus triggered
            focus_fire_triggered = False
            if first_order and second_order and isinstance(first_order.order, Move) and isinstance(second_order.order, Move):
                if first_order.move_target == second_order.move_target and first_order.move_target in (1, 2):
                    target_opp = battle.opponent_active_pokemon[first_order.move_target - 1]
                    if target_opp:
                        opp_hp_fraction = getattr(target_opp, "current_hp_fraction", 1.0)
                        other_idx = 1 if first_order.move_target == 1 else 0
                        other_opp = battle.opponent_active_pokemon[other_idx]
                        other_hp_fraction = getattr(other_opp, "current_hp_fraction", 1.0) if other_opp else 1.0
                        if opp_hp_fraction <= other_hp_fraction and opp_hp_fraction < 0.75:
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

            # 5. best spread score and best KO score per slot
            best_spread_score = [None, None]
            best_ko_score = [None, None]
            for idx in (0, 1):
                valid_orders_slot = valid_orders[idx] if valid_orders and valid_orders[idx] else []
                for order in valid_orders_slot:
                    if isinstance(order.order, Move):
                        move = order.order
                        score = slot_0_scores.get(id(order), 0.0) if idx == 0 else slot_1_scores.get(id(order), 0.0)
                        if self.is_spread_move(move):
                            if best_spread_score[idx] is None or score > best_spread_score[idx]:
                                best_spread_score[idx] = score
                        target_mon = None
                        if order.move_target == 1:
                            target_mon = battle.opponent_active_pokemon[0]
                        elif order.move_target == 2:
                            target_mon = battle.opponent_active_pokemon[1]
                        if target_mon and self.check_move_will_ko(move, battle.active_pokemon[idx], target_mon, battle, config=self.config):
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
                if order and isinstance(order.order, Move) and order.move_target in (1, 2):
                    target_opp = battle.opponent_active_pokemon[order.move_target - 1]
                    if target_opp and getattr(target_opp, "current_hp_fraction", 1.0) <= 0.35:
                        low_hp_opponent_targeted = True

            # 7. expected damage, expected KO, target HP, action, action type, target species for selected slot orders
            expected_damages = [None, None]
            expected_kos = [None, None]
            target_hps = [None, None]
            slot_actions = [None, None]
            slot_action_types = [None, None]
            target_species = [None, None]

            for idx, order in enumerate([first_order, second_order]):
                if order:
                    try:
                        slot_actions[idx] = str(order)
                    except Exception:
                        slot_actions[idx] = ""
                    if slot_actions[idx] is None:
                        slot_actions[idx] = ""
                    # Deduce action types
                    act_types = {"damaging": False, "status": False, "protect": False, "fakeout": False, "spread": False, "switch": False}
                    if isinstance(order.order, Move):
                        m = order.order
                        cat_name = getattr(m.category, "name", "STATUS")
                        if cat_name == "STATUS":
                            act_types["status"] = True
                        else:
                            act_types["damaging"] = True
                        if m.id in ("protect", "detect", "spikyshield", "kingsshield", "banefulbunker", "silktrap"):
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
                            expected_damages[idx] = self.get_expected_damage(m, battle.active_pokemon[idx], target_mon, battle, config=self.config) / max(1.0, opp_max)
                            expected_kos[idx] = self.check_move_will_ko(m, battle.active_pokemon[idx], target_mon, battle, config=self.config)
                            target_hps[idx] = float(target_mon.current_hp_fraction) if target_mon.current_hp_fraction is not None else 1.0
                            target_species[idx] = target_mon.species
                    elif isinstance(order.order, Pokemon):
                        act_types["switch"] = True
                    slot_action_types[idx] = act_types

            best_overkill_applied = False
            if best_joint.first_order and best_joint.second_order:
                best_overkill_applied = self.selected_target_will_be_koed_before_second_action(
                    best_joint.first_order, best_joint.second_order, battle, config=self.config
                )
            self._order_aware_overkill_penalty_applied[battle_tag] = best_overkill_applied

            protect_like_available = [False, False]
            switch_available = [False, False]
            only_conditional_priority = [False, False]
            stalling_field_condition = [False, False]

            stalling = False
            if battle:
                if self.is_trick_room_active(battle):
                    stalling = True
                try:
                    from poke_env.battle.side_condition import SideCondition
                    if SideCondition.TAILWIND in battle.opponent_side_conditions or SideCondition.TAILWIND in battle.side_conditions:
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
                    protect_like_available[idx] = self.has_legal_protect_like_action(active_mon, battle, slot_index=idx)
                    switch_available[idx] = len(battle.available_switches) > 0
                    stalling_field_condition[idx] = stalling
                    
                    active_opps = [opp for opp in battle.opponent_active_pokemon if opp]
                    threat_info = self.estimate_speed_priority_threat(active_mon, active_opps, battle)
                    only_conditional_priority[idx] = threat_info.get("only_conditional_priority", False)

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
                chosen_order = best_joint.first_order if idx == 0 else best_joint.second_order
                is_forced = battle.force_switch[idx] if idx < len(battle.force_switch) else False
                forced_switch_list[idx] = is_forced

                # Negative boost diagnostics
                active_mon = battle.active_pokemon[idx]
                neg_boosts = _neg_boost_data_per_slot.get(idx, {})
                neg_boost_total_list[idx] = neg_boosts.get("total_negative_stages", 0)
                neg_boost_lowest_list[idx] = neg_boosts.get("lowest_stage", 0)
                neg_boost_offensive_list[idx] = neg_boosts.get("offensive_negative_stages", 0)
                neg_boost_defensive_list[idx] = neg_boosts.get("defensive_negative_stages", 0)
                neg_boost_speed_list[idx] = neg_boosts.get("speed_negative_stage", 0)
                neg_boost_severe_list[idx] = neg_boosts.get("severe_negative_boost", False)
                if chosen_order and hasattr(chosen_order, "order"):
                    neg_boost_was_switch_list[idx] = isinstance(chosen_order.order, Pokemon)

                # Complete negative-boost eligibility after best_joint is known
                if neg_boosts:
                    is_forced_nb = battle.force_switch[idx] if idx < len(battle.force_switch) else False
                    orders_slot_nb = valid_orders[idx] if valid_orders and len(valid_orders) > idx else []
                    has_legal_switches_nb = any(o and isinstance(o.order, Pokemon) for o in orders_slot_nb)
                    has_legal_moves_nb = any(o and isinstance(o.order, Move) for o in orders_slot_nb)

                    # Determine selected action kind
                    if chosen_order:
                        if isinstance(chosen_order.order, Pokemon):
                            neg_boosts["negative_boost_selected_action_kind"] = "switch"
                        elif isinstance(chosen_order.order, Move):
                            neg_boosts["negative_boost_selected_action_kind"] = "move"
                        elif isinstance(chosen_order, (type(None),)) or not hasattr(chosen_order, "order"):
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
                    best_sw_score = float('-inf')
                    best_sw_species = ""
                    best_mv_score = float('-inf')
                    for o in orders_slot_nb:
                        if not o:
                            continue
                        sid_o = id(o)
                        sc = slot_0_scores.get(sid_o, 0.0) if idx == 0 else slot_1_scores.get(sid_o, 0.0)
                        if isinstance(o.order, Pokemon):
                            if sc > best_sw_score:
                                best_sw_score = sc
                                best_sw_species = getattr(o.order, "species", "")
                        elif isinstance(o.order, Move):
                            if sc > best_mv_score:
                                best_mv_score = sc
                    neg_boosts["negative_boost_best_switch_species"] = best_sw_species
                    neg_boosts["negative_boost_best_switch_score"] = best_sw_score if best_sw_score > float('-inf') else 0.0
                    neg_boosts["negative_boost_best_move_score"] = best_mv_score if best_mv_score > float('-inf') else 0.0
                    neg_boosts["negative_boost_switch_score_gap"] = (
                        (best_sw_score if best_sw_score > float('-inf') else 0.0)
                        - (best_mv_score if best_mv_score > float('-inf') else 0.0)
                    )

                    # Eligibility check
                    is_pass_default = neg_boosts["negative_boost_selected_action_kind"] in ("pass", "none")
                    # Deduplicate by stable decision event identifier
                    dedup_key = (battle_tag, current_turn, idx,
                                 getattr(active_mon, "species", ""),
                                 neg_boosts["negative_boost_selected_action_kind"],
                                 is_forced_nb)
                    is_duplicate = dedup_key in getattr(self, "_neg_boost_dedup_keys", set())
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
                if getattr(self.config, "enable_stat_drop_switch_diagnostics", False) and active_mon:
                    boosts = getattr(active_mon, "boosts", None)
                    orders_slot_sd = valid_orders[idx] if valid_orders and len(valid_orders) > idx else []
                    sd_class = classify_stat_drop_severity(boosts, self.config, orders_slot_sd)

                    severe_neg_boost_active_list[idx] = sd_class["severe"]
                    severe_neg_boost_categories_list[idx] = sd_class["categories"]
                    severe_neg_boost_turn_list[idx] = current_turn if sd_class["severe"] else 0
                    severe_neg_boost_species_list[idx] = getattr(active_mon, "species", "") if sd_class["severe"] else ""

                    if sd_class["severe"]:
                        is_forced_sd = battle.force_switch[idx] if idx < len(battle.force_switch) else False
                        has_switches_sd = any(o and isinstance(o.order, Pokemon) for o in orders_slot_sd)
                        severe_neg_boost_switch_available_list[idx] = has_switches_sd and not is_forced_sd

                        # Determine if switched or stayed
                        is_switch = chosen_order and isinstance(chosen_order.order, Pokemon)
                        severe_neg_boost_switched_list[idx] = is_switch
                        severe_neg_boost_stayed_list[idx] = not is_switch and not is_forced_sd

                        # Best switch candidate
                        best_sw_species = ""
                        best_sw_score = float('-inf')
                        slot_scores_sd = slot_0_scores if idx == 0 else slot_1_scores
                        for o in orders_slot_sd:
                            if o and isinstance(o.order, Pokemon):
                                sc = slot_scores_sd.get(id(o), 0.0)
                                if sc > best_sw_score:
                                    best_sw_score = sc
                                    best_sw_species = getattr(o.order, "species", "")
                        severe_neg_boost_best_switch_candidate_list[idx] = best_sw_species

                        # Selected action
                        if is_switch:
                            severe_neg_boost_selected_action_list[idx] = f"switch:{getattr(chosen_order.order, 'species', '')}"
                        elif chosen_order and isinstance(chosen_order.order, Move):
                            severe_neg_boost_selected_action_list[idx] = f"move:{getattr(chosen_order.order, 'id', '')}"
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
                                target_pos = getattr(chosen_order, 'move_target', 0)
                                if target_pos in (1, 2):
                                    target_opp = battle.opponent_active_pokemon[target_pos - 1]
                                    if target_opp and self.check_move_will_ko(chosen_order.order, active_mon, target_opp, battle, config=self.config):
                                        productive = True
                            # Check meaningful damage (configurable threshold)
                            if not productive and chosen_order and isinstance(chosen_order.order, Move):
                                target_pos = getattr(chosen_order, 'move_target', 0)
                                if target_pos in (1, 2):
                                    target_opp = battle.opponent_active_pokemon[target_pos - 1]
                                    if target_opp:
                                        try:
                                            dmg = self.get_expected_damage(chosen_order.order, active_mon, target_opp, battle, config=self.config)
                                            opp_max = self.estimate_opponent_max_hp(target_opp)
                                            frac = getattr(config, "stat_drop_meaningful_damage_fraction", 0.25) if config else 0.25
                                            if opp_max > 0 and dmg / opp_max >= frac:
                                                productive = True
                                        except Exception:
                                            pass
                            # Check Protect (only if existing protect safety says it's safe)
                            if not productive and chosen_order and isinstance(chosen_order.order, Move):
                                move_id = getattr(chosen_order.order, 'id', '')
                                if move_id in ("protect", "detect", "spikyshield", "kingsshield", "banefulbunker", "silktrap"):
                                    productive = True  # Protect is generally safe if selected

                            severe_neg_boost_stayed_productive_list[idx] = productive
                            severe_neg_boost_stayed_unproductive_list[idx] = not productive

                # Phase 6.4.7: Stat-drop switch scoring audit population
                sdata = _stat_drop_scoring_data.get(idx, {})
                stat_drop_switch_scoring_enabled_list[idx] = sdata.get("enabled", False)
                stat_drop_switch_pressure_active_list[idx] = sdata.get("pressure_active", False)
                stat_drop_switch_pressure_categories_list[idx] = list(sdata.get("categories", []))
                stat_drop_switch_pressure_score_list[idx] = sdata.get("stay_penalty", 0.0)
                stat_drop_switch_best_switch_species_list[idx] = sdata.get("best_switch_species", "")
                stat_drop_switch_best_switch_score_list[idx] = sdata.get("best_switch_score", 0.0)
                stat_drop_switch_best_non_switch_score_list[idx] = sdata.get("best_non_switch_score", 0.0)
                stat_drop_switch_reason_list[idx] = sdata.get("reason", "")
                stat_drop_switch_threshold_source_list[idx] = sdata.get("threshold_source", "")
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
                if sdata.get("enabled", False) and _stat_drop_counterfactual_joint is not None:
                    actual_key = _stat_drop_actual_actions[idx] if idx < len(_stat_drop_actual_actions) else ("", "", 0)
                    cf_key = _stat_drop_counterfactual_actions[idx] if idx < len(_stat_drop_counterfactual_actions) else ("", "", 0)
                    if actual_key != cf_key:
                        stat_drop_switch_selection_changed_list[idx] = True

                # Phase 6.3.6b: Known Ally Redirection audit population
                known_ally_redirection_selected_list[idx] = self._known_ally_redirect_selected.get(battle_tag, {}).get(idx, False)
                known_ally_redirection_reason_list[idx] = self._known_ally_redirect_reason.get(battle_tag, {}).get(idx, "")
                known_ally_redirection_ally_species_list[idx] = self._known_ally_redirect_ally_species.get(battle_tag, {}).get(idx, "")
                known_ally_redirection_ally_ability_list[idx] = self._known_ally_redirect_ally_ability.get(battle_tag, {}).get(idx, "")
                known_ally_redirection_move_id_list[idx] = self._known_ally_redirect_move_id.get(battle_tag, {}).get(idx, "")
                ally_before_ability = _known_ally_ability_before[1 - idx] if (1 - idx) < len(_known_ally_ability_before) else ""
                ally_after_ability = self._known_ally_redirect_ally_ability.get(battle_tag, {}).get(idx, "")
                known_ally_redirection_known_before_decision_list[idx] = bool(ally_before_ability and ally_before_ability == ally_after_ability)

                # Phase 6.3.7: Dynamic move type audit population
                if chosen_order and isinstance(chosen_order.order, Move):
                    ch_move = chosen_order.order
                    ch_active = battle.active_pokemon[idx] if idx < len(battle.active_pokemon) else None
                    resolved = resolve_effective_move_type(ch_move, ch_active, battle)
                    declared_move_type_list[idx] = resolved["declared_type"]
                    effective_move_type_list[idx] = resolved["effective_type"]
                    effective_move_type_source_list[idx] = resolved["source"]
                    dynamic_move_type_applied_list[idx] = resolved["dynamic_applied"]
                    dynamic_move_type_form_list[idx] = resolved["observed_form"]

                is_selected_ar = known_ally_redirection_selected_list[idx]
                is_known_before = known_ally_redirection_known_before_decision_list[idx]
                candidate_blocked = _ally_redirect_blocked.get(id(chosen_order), False) if chosen_order else False
                known_ally_redirection_candidate_blocked_list[idx] = candidate_blocked

                # Safe alternative: any legal joint has a different non-blocked action for this slot
                safe_alt_exists = False
                if candidate_blocked or is_selected_ar:
                    for alt_best_joint, _, _, _ in scored_joint_orders[1:]:
                        alt_order = alt_best_joint.first_order if idx == 0 else alt_best_joint.second_order
                        if alt_order and id(alt_order) != (id(chosen_order) if chosen_order else None):
                            if not _ally_redirect_blocked.get(id(alt_order), False):
                                safe_alt_exists = True
                                break

                blocked_candidate_exists = any(_ally_redirect_blocked.get(id(o), False) for o in valid_orders[idx]) if valid_orders and len(valid_orders) > idx else False

                # Phase 6.3.6b pure helper: audit classification
                audit = classify_known_ally_redirection_audit(
                    is_selected_blocked=(candidate_blocked or is_selected_ar),
                    candidate_blocked_exists=blocked_candidate_exists,
                    safe_alternative_exists=safe_alt_exists,
                )
                known_ally_redirection_only_legal_list[idx] = audit["only_legal"]
                known_ally_redirection_safe_alternative_available_list[idx] = safe_alt_exists
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
                    key = (self.get_pokemon_identifier(battle.active_pokemon[idx]) if battle.active_pokemon[idx] else "",
                           known_ally_redirection_move_id_list[idx],
                           known_ally_redirection_ally_species_list[idx],
                           known_ally_redirection_ally_ability_list[idx])
                    s = getattr(self, "_known_ally_redirect_streak", {})
                    repeat_result = update_known_ally_redirection_repeat_state(key, battle_tag, current_turn, s)
                    self._known_ally_redirect_streak = repeat_result["streak_state"]
                    known_ally_redirection_repeat_selected_list[idx] = repeat_result["repeat_detected"]

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
                            alt_order = alt_best_joint.first_order if idx == 0 else alt_best_joint.second_order
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
                    known_ally_redirection_blocked_candidate_move_id_list[idx] = first_blocked.get("move_id", "")
                    known_ally_redirection_blocked_candidate_attacker_species_list[idx] = first_blocked.get("attacker_species", "")
                    known_ally_redirection_blocked_candidate_target_species_list[idx] = first_blocked.get("target_species", "")
                    known_ally_redirection_blocked_candidate_ally_species_list[idx] = first_blocked.get("ally_species", "")
                    known_ally_redirection_blocked_candidate_ally_ability_list[idx] = first_blocked.get("ally_ability", "")
                    known_ally_redirection_blocked_candidate_reason_list[idx] = first_blocked.get("reason", "")
                    known_ally_redirection_blocked_candidate_known_before_list[idx] = first_blocked.get("known_before_decision", False)
                slot_scores_for_pop = slot_0_scores if idx == 0 else slot_1_scores
                for oid in (ar_meta or {}):
                    known_ally_redirection_blocked_candidate_score_list[idx] = slot_scores_for_pop.get(oid, 0.0)
                    break  # first blocked only
                if best_safe_alt_id is not None:
                    know_alt_order = None
                    for alt_best_joint, _, _, _ in scored_joint_orders[1:]:
                        alt_order = alt_best_joint.first_order if idx == 0 else alt_best_joint.second_order
                        if alt_order and id(alt_order) == best_safe_alt_id:
                            known_ally_redirection_best_safe_alternative_list[idx] = getattr(getattr(alt_order, "order", None), "id", "") if alt_order and hasattr(alt_order, "order") else ""
                            break
                    known_ally_redirection_best_safe_alternative_score_list[idx] = best_safe_alt_score if best_safe_alt_score > float("-inf") else 0.0

                # Phase 6.4.3a.1: Type-immune audit computation
                if chosen_order and isinstance(chosen_order.order, Move):
                    chosen_move = chosen_order.order
                    chosen_active = battle.active_pokemon[idx] if idx < len(battle.active_pokemon) else None
                    chosen_target = None
                    if hasattr(chosen_order, 'move_target'):
                        t_pos = chosen_order.move_target
                        if t_pos in (1, 2) and t_pos - 1 < len(battle.opponent_active_pokemon):
                            chosen_target = battle.opponent_active_pokemon[t_pos - 1]

                    if chosen_active and chosen_target and getattr(chosen_move, 'base_power', 0) > 0:
                        immune, reason = is_type_immune(chosen_move, chosen_active, chosen_target, battle)
                        if immune:
                            our_type_immune_move_selected_list[idx] = True
                            our_type_immune_attacker_list[idx] = getattr(chosen_active, 'species', '')
                            our_type_immune_move_list[idx] = getattr(chosen_move, 'id', '')
                            our_type_immune_target_list[idx] = getattr(chosen_target, 'species', '')
                            t_types_str = ""
                            if hasattr(chosen_target, 'types') and chosen_target.types:
                                t_types_str = "+".join(
                                    t.name.title() if hasattr(t, 'name') else str(t)
                                    for t in chosen_target.types if t
                                )
                            our_type_immune_target_types_list[idx] = t_types_str
                            our_type_immune_reason_list[idx] = reason

                            # Check if this was the only legal damaging move
                            orders_slot_imm = valid_orders[idx] if valid_orders and len(valid_orders) > idx else []
                            safe_alternatives = 0
                            for alt_o in orders_slot_imm:
                                if alt_o and isinstance(alt_o.order, Move) and getattr(alt_o.order, 'base_power', 0) > 0:
                                    alt_target = None
                                    if hasattr(alt_o, 'move_target') and alt_o.move_target in (1, 2):
                                        alt_target = battle.opponent_active_pokemon[alt_o.move_target - 1]
                                    if alt_target:
                                        alt_imm, _ = is_type_immune(alt_o.order, chosen_active, alt_target, battle)
                                        if not alt_imm:
                                            alt_blocked, _ = ability_hard_blocks_move(alt_o.order, chosen_active, alt_target, battle, config=self.config)
                                            if not alt_blocked:
                                                safe_alternatives += 1
                            if safe_alternatives == 0:
                                our_type_immune_only_legal_list[idx] = True
                            else:
                                our_type_immune_move_avoided_list[idx] = True

                # Phase 6.4.3a.2 / 6.4.4: Forced switch diagnostic computation
                if is_forced:
                    forced_switch_safety_enabled_list[idx] = bool(
                        getattr(self.config, "enable_forced_switch_replacement_safety", False)
                    )
                    orders_slot_fs = valid_orders[idx] if valid_orders and len(valid_orders) > idx else []
                    switch_candidates = [o for o in orders_slot_fs if o and isinstance(o.order, Pokemon)]
                    forced_switch_candidate_count_list[idx] = len(switch_candidates)

                    # Find the selected switch index and species
                    selected_safety_result = None
                    best_safety_result = None
                    if chosen_order and isinstance(chosen_order.order, Pokemon):
                        forced_switch_selected_species_list[idx] = getattr(chosen_order.order, 'species', '')
                        for ci, cand in enumerate(switch_candidates):
                            if id(cand) == id(chosen_order):
                                forced_switch_selected_index_list[idx] = ci
                                break

                    # Evaluate safety scores for all candidates using the SAME function
                    # as the actual scoring path (evaluate_forced_switch_replacement_safety).
                    # Previous code incorrectly used evaluate_switch_candidate_type_safety
                    # which has different scoring constants and thresholds.
                    best_safety_score = float('-inf')
                    best_safety_species = ""
                    selected_safety_score = 0.0
                    active_opps_fs = [o for o in battle.opponent_active_pokemon if o]
                    candidate_safety_table = []
                    for cand in switch_candidates:
                        cand_species = getattr(cand.order, 'species', '')
                        safety = evaluate_forced_switch_replacement_safety(
                            cand.order,
                            active_opps_fs,
                            battle=battle,
                            config=self.config
                        )
                        s_score = safety.get("score", 0.0)
                        # Build per-candidate audit entry
                        candidate_safety_table.append({
                            "species": cand_species,
                            "score": round(s_score, 2),
                            "max_threat_multiplier": safety.get("max_threat_multiplier", 1.0),
                            "opponent_threat_count": safety.get("opponent_threat_count", 0),
                            "quad_weak_count": safety.get("quad_weak_count", 0),
                            "resistance_count": safety.get("resistance_count", 0),
                            "immunity_count": safety.get("immunity_count", 0),
                            "low_hp_penalty_applied": safety.get("low_hp_penalty_applied", False),
                            "reasons": safety.get("reasons", []),
                        })
                        if s_score > best_safety_score:
                            best_safety_score = s_score
                            best_safety_species = cand_species
                            best_safety_result = safety
                        if chosen_order and id(cand) == id(chosen_order):
                            selected_safety_score = s_score
                            selected_safety_result = safety

                    forced_switch_best_safety_species_list[idx] = best_safety_species
                    forced_switch_selected_safety_score_list[idx] = selected_safety_score
                    forced_switch_best_safety_score_list[idx] = best_safety_score if best_safety_score > float('-inf') else 0.0
                    forced_switch_candidate_safety_table_list[idx] = candidate_safety_table if candidate_safety_table else None

                    # Detect list-order fallback
                    if forced_switch_selected_index_list[idx] == 0 and len(switch_candidates) > 1:
                        forced_switch_order_fallback_used_list[idx] = True

                    # Phase 6.4.4: Additional audit fields
                    if selected_safety_result:
                        forced_switch_selected_double_threat_list[idx] = bool(
                            "double_threat" in selected_safety_result.get("reasons", [])
                        )
                        forced_switch_selected_quad_weak_list[idx] = bool(
                            "quad_weak" in selected_safety_result.get("reasons", [])
                        )
                        forced_switch_selected_low_hp_list[idx] = selected_safety_result.get("low_hp_penalty_applied", False)
                    if best_safety_result:
                        forced_switch_best_avoids_double_threat_list[idx] = (
                            "double_threat" not in best_safety_result.get("reasons", [])
                        )
                        forced_switch_best_avoids_quad_weak_list[idx] = (
                            "quad_weak" not in best_safety_result.get("reasons", [])
                        )

                    # Selection changed: best safety species differs from selected
                    if (best_safety_species
                            and forced_switch_selected_species_list[idx]
                            and best_safety_species != forced_switch_selected_species_list[idx]):
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
                        selected_switch_species_list[idx] = getattr(switch_candidate, "species", "")
                        types = []
                        t1 = getattr(switch_candidate, "type_1", None)
                        t2 = getattr(switch_candidate, "type_2", None)
                        if t1:
                            types.append(t1.name.title() if hasattr(t1, "name") else str(t1))
                        if t2:
                            types.append(t2.name.title() if hasattr(t2, "name") else str(t2))
                        selected_switch_types_list[idx] = "+".join(types)
                        selected_switch_hp_fraction_list[idx] = safety.get("candidate_hp_fraction", 1.0)
                        selected_switch_raw_safety_score_list[idx] = safety.get("raw_safety_score", 0.0)
                        selected_switch_worst_multiplier_list[idx] = safety.get("worst_multiplier", 1.0)
                        selected_switch_double_threat_list[idx] = safety.get("double_threat", False)

                        best_raw = _switch_best_raw_scores.get(idx, 0.0)
                        relative_adj = min(0.0, safety.get("raw_safety_score", 0.0) - best_raw)
                        selected_switch_relative_adjustment_list[idx] = relative_adj

                        is_unsafe = safety.get("double_threat", False) or safety.get("quad_weak_threat_count", 0) > 0
                        if is_unsafe:
                            unsafe_switch_candidate_selected_list[idx] = True

                            # Joint-legality: find best safe switch that doesn't conflict
                            # with the other slot's selected switch
                            other_idx = 1 - idx
                            other_chosen = best_joint.first_order if other_idx == 0 else best_joint.second_order
                            other_species = None
                            if other_chosen and isinstance(other_chosen.order, Pokemon):
                                other_species = getattr(other_chosen.order, "species", None)

                            best_safe_order = None
                            best_safe_score = float('-inf')
                            for sw_order in (cand_safety.keys()):
                                sw_safety = cand_safety[sw_order]
                                sw_unsafe = sw_safety.get("double_threat", False) or sw_safety.get("quad_weak_threat_count", 0) > 0
                                if sw_unsafe:
                                    continue
                                # Find the actual order object to check species
                                for so in switch_orders if idx == 0 else (valid_orders[other_idx] if valid_orders and len(valid_orders) > other_idx else []):
                                    if id(so) == sw_order:
                                        sw_species = getattr(so.order, "species", None)
                                        if other_species and sw_species == other_species:
                                            break  # conflicts with other slot
                                        sw_score = slot_0_scores.get(sw_order, 0.0) if idx == 0 else slot_1_scores.get(sw_order, 0.0)
                                        if sw_score > best_safe_score:
                                            best_safe_score = sw_score
                                            best_safe_order = so
                                        break

                            if best_safe_order:
                                safer_switch_candidate_available_list[idx] = True
                                best_safe_switch_species_list[idx] = getattr(best_safe_order.order, "species", "")
                                best_safe_switch_score_list[idx] = best_safe_score
                            else:
                                safer_switch_candidate_available_list[idx] = False

                            # switch_type_safety_avoided: only when feature is ON and selection changed
                            if (self.config.enable_switch_candidate_type_safety
                                    and safer_switch_candidate_available_list[idx]):
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
            if first_order and second_order and isinstance(first_order.order, Move) and isinstance(second_order.order, Move):
                ft = getattr(first_order, "move_target", None)
                st = getattr(second_order, "move_target", None)
                if ft in (1, 2) and st in (1, 2) and ft == st:
                    if getattr(first_order.order, "base_power", 0) > 0 and getattr(second_order.order, "base_power", 0) > 0:
                        if not self.is_spread_move(first_order.order) and not self.is_spread_move(second_order.order):
                            target_opp = battle.opponent_active_pokemon[ft - 1]
                            if target_opp:
                                ko_1 = self.check_move_will_ko(first_order.order, battle.active_pokemon[0], target_opp, battle, config=self.config)
                                if ko_1:
                                    visible_opps = [o for o in battle.opponent_active_pokemon if o and not getattr(o, "fainted", False)]
                                    stale = detect_stale_target_after_ally_ko_risk(
                                        first_order, second_order, ko_1, target_opp, target_opp,
                                        visible_opps, battle=battle, config=self.config,
                                    )
                                    if stale["risk"]:
                                        stale_target_selected = True
                                        stale_target_same_target_expected_ko = True
                                        stale_target_caused_no_effect = stale["fallback_target_no_effect"]
                                        stale_target_caused_type_immune = stale["fallback_target_type_immune"]
                                        stale_target_first_slot_val = 0
                                        stale_target_first_move = stale["first_move_id"]
                                        stale_target_first_target = stale["first_target_species"]
                                        stale_target_second_slot_val = 1
                                        stale_target_second_move = stale["second_move_id"]
                                        stale_target_second_intended_target = stale["second_target_species"]
                                        stale_target_fallback_target = stale["fallback_target_species"]
                                        stale_target_reason = stale["reason"]

            # Check if stale target was avoided: any alternative had risk but selected didn't
            if not stale_target_selected and self.config.enable_stale_target_after_ally_ko_safety:
                for alt_joint, alt_score, _, _ in scored_joint_orders[1:min(6, len(scored_joint_orders))]:
                    alt_first = alt_joint.first_order
                    alt_second = alt_joint.second_order
                    if alt_first and alt_second and isinstance(alt_first.order, Move) and isinstance(alt_second.order, Move):
                        at = getattr(alt_first, "move_target", None)
                        bt = getattr(alt_second, "move_target", None)
                        if at in (1, 2) and bt in (1, 2) and at == bt:
                            if getattr(alt_first.order, "base_power", 0) > 0 and getattr(alt_second.order, "base_power", 0) > 0:
                                if not self.is_spread_move(alt_first.order) and not self.is_spread_move(alt_second.order):
                                    alt_target = battle.opponent_active_pokemon[at - 1]
                                    if alt_target:
                                        alt_ko = self.check_move_will_ko(alt_first.order, battle.active_pokemon[0], alt_target, battle, config=self.config)
                                        if alt_ko:
                                            vis_opps = [o for o in battle.opponent_active_pokemon if o and not getattr(o, "fainted", False)]
                                            alt_stale = detect_stale_target_after_ally_ko_risk(
                                                alt_first, alt_second, alt_ko, alt_target, alt_target,
                                                vis_opps, battle=battle, config=self.config,
                                            )
                                            if alt_stale["risk"]:
                                                stale_target_avoided = True
                                                break

            self._stale_target_selected[battle_tag] = stale_target_selected
            self._stale_target_same_target_expected_ko[battle_tag] = stale_target_same_target_expected_ko
            self._stale_target_caused_no_effect[battle_tag] = stale_target_caused_no_effect
            self._stale_target_caused_type_immune[battle_tag] = stale_target_caused_type_immune
            self._stale_target_first_slot[battle_tag] = stale_target_first_slot_val
            self._stale_target_first_move[battle_tag] = stale_target_first_move
            self._stale_target_first_target[battle_tag] = stale_target_first_target
            self._stale_target_second_slot[battle_tag] = stale_target_second_slot_val
            self._stale_target_second_move[battle_tag] = stale_target_second_move
            self._stale_target_second_intended_target[battle_tag] = stale_target_second_intended_target
            self._stale_target_fallback_target[battle_tag] = stale_target_fallback_target
            self._stale_target_reason[battle_tag] = stale_target_reason

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
                partial_immune_spread_selected=[
                    self.partial_immune_spread_by_battle.setdefault(battle_tag, {0: False, 1: False})[0],
                    self.partial_immune_spread_by_battle.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                partial_ability_immune_spread_selected=[
                    self.partial_ability_immune_spread_by_battle.setdefault(battle_tag, {0: False, 1: False})[0],
                    self.partial_ability_immune_spread_by_battle.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                efficient_partial_spread_selected=[
                    self.efficient_partial_spread_by_battle.setdefault(battle_tag, {0: False, 1: False})[0],
                    self.efficient_partial_spread_by_battle.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                inefficient_partial_spread_selected=[
                    self.inefficient_partial_spread_by_battle.setdefault(battle_tag, {0: False, 1: False})[0],
                    self.inefficient_partial_spread_by_battle.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                immune_target_species=[
                    self.immune_target_species_by_battle.setdefault(battle_tag, {0: [], 1: []})[0],
                    self.immune_target_species_by_battle.setdefault(battle_tag, {0: [], 1: []})[1]
                ],
                damaged_target_species=[
                    self.damaged_target_species_by_battle.setdefault(battle_tag, {0: [], 1: []})[0],
                    self.damaged_target_species_by_battle.setdefault(battle_tag, {0: [], 1: []})[1]
                ],
                best_single_target_alternative=[
                    self.best_single_alternative_by_battle.setdefault(battle_tag, {0: "", 1: ""})[0],
                    self.best_single_alternative_by_battle.setdefault(battle_tag, {0: "", 1: ""})[1]
                ],
                speed_priority_threatened=[
                    self._speed_priority_threatened.setdefault(battle_tag, {0: False, 1: False})[0],
                    self._speed_priority_threatened.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                faster_opponents=[
                    self._faster_opponents.setdefault(battle_tag, {0: [], 1: []})[0],
                    self._faster_opponents.setdefault(battle_tag, {0: [], 1: []})[1]
                ],
                priority_opponents=[
                    self._priority_opponents.setdefault(battle_tag, {0: [], 1: []})[0],
                    self._priority_opponents.setdefault(battle_tag, {0: [], 1: []})[1]
                ],
                speed_priority_protect_bonus_applied=[
                    self._speed_priority_protect_bonus_applied.setdefault(battle_tag, {0: False, 1: False})[0],
                    self._speed_priority_protect_bonus_applied.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                speed_priority_attack_penalty_applied=[
                    self._speed_priority_attack_penalty_applied.setdefault(battle_tag, {0: False, 1: False})[0],
                    self._speed_priority_attack_penalty_applied.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                speed_priority_switch_bonus_applied=[
                    self._speed_priority_switch_bonus_applied.setdefault(battle_tag, {0: False, 1: False})[0],
                    self._speed_priority_switch_bonus_applied.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                order_aware_overkill_penalty_applied=self._order_aware_overkill_penalty_applied.setdefault(battle_tag, False),
                expected_to_faint_before_moving=[
                    self._expected_to_faint_before_moving.setdefault(battle_tag, {0: False, 1: False})[0],
                    self._expected_to_faint_before_moving.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                protected_due_to_speed_priority=[
                    self._protected_due_to_speed_priority.setdefault(battle_tag, {0: False, 1: False})[0],
                    self._protected_due_to_speed_priority.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                protect_like_available=protect_like_available,
                switch_available=switch_available,
                only_conditional_priority=only_conditional_priority,
                stalling_field_condition=stalling_field_condition,
                ability_hard_block_avoided=[
                    self._ability_hard_block_avoided.setdefault(battle_tag, {0: False, 1: False})[0],
                    self._ability_hard_block_avoided.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                ability_immune_move_selected=[
                    self._ability_immune_move_selected.setdefault(battle_tag, {0: False, 1: False})[0],
                    self._ability_immune_move_selected.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                ground_into_levitate_selected=[
                    self._ground_into_levitate_selected.setdefault(battle_tag, {0: False, 1: False})[0],
                    self._ground_into_levitate_selected.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                ability_block_reason=[
                    self._ability_block_reason.setdefault(battle_tag, {0: "", 1: ""})[0],
                    self._ability_block_reason.setdefault(battle_tag, {0: "", 1: ""})[1]
                ],
                ability_blocked_target_species=[
                    self._ability_blocked_target_species.setdefault(battle_tag, {0: "", 1: ""})[0],
                    self._ability_blocked_target_species.setdefault(battle_tag, {0: "", 1: ""})[1]
                ],
                ability_blocked_target_ability=[
                    self._ability_blocked_target_ability.setdefault(battle_tag, {0: "", 1: ""})[0],
                    self._ability_blocked_target_ability.setdefault(battle_tag, {0: "", 1: ""})[1]
                ],
                ally_ability_safe_spread=[
                    self._ally_ability_safe_spread.setdefault(battle_tag, {0: False, 1: False})[0],
                    self._ally_ability_safe_spread.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                ability_redirection_avoided=[
                    self._ability_redirection_avoided.setdefault(battle_tag, {0: False, 1: False})[0],
                    self._ability_redirection_avoided.setdefault(battle_tag, {0: False, 1: False})[1]
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
                    self._direct_absorb_hard_block_avoided.setdefault(battle_tag, {0: False, 1: False})[0],
                    self._direct_absorb_hard_block_avoided.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                direct_absorb_immune_move_selected=[
                    self._direct_absorb_immune_move_selected.setdefault(battle_tag, {0: False, 1: False})[0],
                    self._direct_absorb_immune_move_selected.setdefault(battle_tag, {0: False, 1: False})[1]
                ],
                direct_absorb_block_reason=[
                    self._direct_absorb_block_reason.setdefault(battle_tag, {0: "", 1: ""})[0],
                    self._direct_absorb_block_reason.setdefault(battle_tag, {0: "", 1: ""})[1]
                ],
                direct_absorb_target_species=[
                    self._direct_absorb_target_species.setdefault(battle_tag, {0: "", 1: ""})[0],
                    self._direct_absorb_target_species.setdefault(battle_tag, {0: "", 1: ""})[1]
                ],
                direct_absorb_target_ability=[
                    self._direct_absorb_target_ability.setdefault(battle_tag, {0: "", 1: ""})[0],
                    self._direct_absorb_target_ability.setdefault(battle_tag, {0: "", 1: ""})[1]
                ],
                direct_absorb_only_legal_action=[
                    self._direct_absorb_only_legal_action.setdefault(battle_tag, {0: False, 1: False})[0],
                    self._direct_absorb_only_legal_action.setdefault(battle_tag, {0: False, 1: False})[1]
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
                neg_boost_decision_eligible=[_neg_boost_data_per_slot.get(0, {}).get("negative_boost_decision_eligible", False), _neg_boost_data_per_slot.get(1, {}).get("negative_boost_decision_eligible", False)],
                neg_boost_selected_action_kind=[_neg_boost_data_per_slot.get(0, {}).get("negative_boost_selected_action_kind", ""), _neg_boost_data_per_slot.get(1, {}).get("negative_boost_selected_action_kind", "")],
                neg_boost_legal_switch_count=[_neg_boost_data_per_slot.get(0, {}).get("negative_boost_legal_switch_count", 0), _neg_boost_data_per_slot.get(1, {}).get("negative_boost_legal_switch_count", 0)],
                neg_boost_best_switch_species=[_neg_boost_data_per_slot.get(0, {}).get("negative_boost_best_switch_species", ""), _neg_boost_data_per_slot.get(1, {}).get("negative_boost_best_switch_species", "")],
                neg_boost_best_switch_score=[_neg_boost_data_per_slot.get(0, {}).get("negative_boost_best_switch_score", 0.0), _neg_boost_data_per_slot.get(1, {}).get("negative_boost_best_switch_score", 0.0)],
                neg_boost_best_move_score=[_neg_boost_data_per_slot.get(0, {}).get("negative_boost_best_move_score", 0.0), _neg_boost_data_per_slot.get(1, {}).get("negative_boost_best_move_score", 0.0)],
                neg_boost_switch_score_gap=[_neg_boost_data_per_slot.get(0, {}).get("negative_boost_switch_score_gap", 0.0), _neg_boost_data_per_slot.get(1, {}).get("negative_boost_switch_score_gap", 0.0)],
                neg_boost_relevant_offensive_drop=[_neg_boost_data_per_slot.get(0, {}).get("negative_boost_relevant_offensive_drop", False), _neg_boost_data_per_slot.get(1, {}).get("negative_boost_relevant_offensive_drop", False)],
                neg_boost_defensive_drop=[_neg_boost_data_per_slot.get(0, {}).get("negative_boost_defensive_drop", False), _neg_boost_data_per_slot.get(1, {}).get("negative_boost_defensive_drop", False)],
                neg_boost_speed_drop=[_neg_boost_data_per_slot.get(0, {}).get("negative_boost_speed_drop", False), _neg_boost_data_per_slot.get(1, {}).get("negative_boost_speed_drop", False)],
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
                revealed_switch_prediction_available=[_revel_switch_interception_data.get(0) is not None, _revel_switch_interception_data.get(1) is not None],
                revealed_switch_interception_selected=[_revel_switch_interception_data.get(0, {}).get("prediction_available", False) if _revel_switch_interception_data.get(0) and isinstance(best_joint.first_order, type(None)) is False and best_joint.first_order and isinstance(best_joint.first_order.order, Pokemon) else False, _revel_switch_interception_data.get(1, {}).get("prediction_available", False) if _revel_switch_interception_data.get(1) and isinstance(best_joint.second_order, type(None)) is False and best_joint.second_order and isinstance(best_joint.second_order.order, Pokemon) else False],
                revealed_switch_selection_changed=_sel_changed_per_slot,
                revealed_switch_threatening_opponent=[_revel_switch_interception_data.get(0, {}).get("threatening_opponents", "") if _revel_switch_interception_data.get(0) else "", _revel_switch_interception_data.get(1, {}).get("threatening_opponents", "") if _revel_switch_interception_data.get(1) else ""],
                revealed_switch_threat_move_ids=[_revel_switch_interception_data.get(0, {}).get("threat_move_ids", []) if _revel_switch_interception_data.get(0) else [], _revel_switch_interception_data.get(1, {}).get("threat_move_ids", []) if _revel_switch_interception_data.get(1) else []],
                revealed_switch_threat_move_types=[_revel_switch_interception_data.get(0, {}).get("threat_move_types", []) if _revel_switch_interception_data.get(0) else [], _revel_switch_interception_data.get(1, {}).get("threat_move_types", []) if _revel_switch_interception_data.get(1) else []],
                revealed_switch_target_likelihood=[_revel_switch_interception_data.get(0, {}).get("target_likelihood", []) if _revel_switch_interception_data.get(0) else [], _revel_switch_interception_data.get(1, {}).get("target_likelihood", []) if _revel_switch_interception_data.get(1) else []],
                revealed_switch_active_risk=[_revel_switch_interception_data.get(0, {}).get("active_risk", 0.0) if _revel_switch_interception_data.get(0) else 0.0, _revel_switch_interception_data.get(1, {}).get("active_risk", 0.0) if _revel_switch_interception_data.get(1) else 0.0],
                revealed_switch_candidate_risk=[_revel_switch_interception_data.get(0, {}).get("candidate_risk", 0.0) if _revel_switch_interception_data.get(0) else 0.0, _revel_switch_interception_data.get(1, {}).get("candidate_risk", 0.0) if _revel_switch_interception_data.get(1) else 0.0],
                revealed_switch_risk_reduction=[_revel_switch_interception_data.get(0, {}).get("risk_reduction", 0.0) if _revel_switch_interception_data.get(0) else 0.0, _revel_switch_interception_data.get(1, {}).get("risk_reduction", 0.0) if _revel_switch_interception_data.get(1) else 0.0],
                revealed_switch_candidate_species=[_revel_switch_interception_data.get(0, {}).get("candidate_species", "") if _revel_switch_interception_data.get(0) else "", _revel_switch_interception_data.get(1, {}).get("candidate_species", "") if _revel_switch_interception_data.get(1) else ""],
                revealed_switch_candidate_types=[_revel_switch_interception_data.get(0, {}).get("candidate_types", "") if _revel_switch_interception_data.get(0) else "", _revel_switch_interception_data.get(1, {}).get("candidate_types", "") if _revel_switch_interception_data.get(1) else ""],
                revealed_switch_candidate_hp=[_revel_switch_interception_data.get(0, {}).get("candidate_hp", 1.0) if _revel_switch_interception_data.get(0) else 1.0, _revel_switch_interception_data.get(1, {}).get("candidate_hp", 1.0) if _revel_switch_interception_data.get(1) else 1.0],
                revealed_switch_bonus_applied=[_revel_switch_interception_data.get(0, {}).get("bonus_applied", 0.0) if _revel_switch_interception_data.get(0) else 0.0, _revel_switch_interception_data.get(1, {}).get("bonus_applied", 0.0) if _revel_switch_interception_data.get(1) else 0.0],
                revealed_switch_blocked_by_ko_action=[_revel_switch_interception_data.get(0, {}).get("blocked_by_ko", False) if _revel_switch_interception_data.get(0) else False, _revel_switch_interception_data.get(1, {}).get("blocked_by_ko", False) if _revel_switch_interception_data.get(1) else False],
                revealed_switch_blocked_by_high_value_action=[_revel_switch_interception_data.get(0, {}).get("blocked_by_high_value", False) if _revel_switch_interception_data.get(0) else False, _revel_switch_interception_data.get(1, {}).get("blocked_by_high_value", False) if _revel_switch_interception_data.get(1) else False],
                revealed_switch_rejected_worse_other_threat=[_revel_switch_interception_data.get(0, {}).get("worse_other_threat", False) if _revel_switch_interception_data.get(0) else False, _revel_switch_interception_data.get(1, {}).get("worse_other_threat", False) if _revel_switch_interception_data.get(1) else False],
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
                decision_time_ms=((time.time() - _t_start) * 1000) if _timing_enabled else None,
                valid_order_time_ms=_t_valid_order if _timing_enabled else None,
                score_action_time_ms=_t_score_action if _timing_enabled else None,
                joint_scoring_time_ms=_t_joint_scoring if _timing_enabled else None,
                audit_postprocess_time_ms=((time.time() - _t_audit_start) * 1000) if _timing_enabled else None,
                score_action_call_count=_score_action_call_count if _timing_enabled else None,
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
            )


        return best_joint

    def _battle_finished_callback(self, battle: AbstractBattle):
        if self.custom_logger:
            if battle.won is True:
                winner = self.username
            elif battle.won is False:
                opp_name = getattr(battle, "opponent_username", None)
                if not opp_name:
                    try:
                        players = getattr(battle, "players", None)
                        if players:
                            opp_name = players[1] if players[0] == self.username else players[0]
                    except Exception:
                        pass
                winner = opp_name or "Opponent"
            else:
                winner = "Tie / Unknown"
                
            self.custom_logger.save_battle(
                battle_tag=getattr(battle, "battle_tag", "Unknown"),
                winner=winner,
                total_turns=getattr(battle, "turn", 0)
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
                            opp_name = players[1] if players[0] == self.username else players[0]
                    except Exception:
                        pass
                winner = opp_name or "Opponent"
            else:
                winner = "Tie / Unknown"
                
            self.audit_logger.save_battle(
                battle_tag=getattr(battle, "battle_tag", "Unknown"),
                winner=winner,
                battle=battle
            )
