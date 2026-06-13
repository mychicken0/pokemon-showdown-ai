import json
import os

class DoublesDecisionAuditLogger:
    """
    A decision audit logger for Doubles battles to record per-turn decision scores,
    considered alternatives, and resolve actual turn outcomes (damage, KOs, protect status)
    offline and safe from crashing the battle loop.
    """
    PRIORITY_MOVES = {
        "extremespeed", "suckerpunch", "machpunch", "vacuumwave", "iceshard",
        "aquajet", "bulletpunch", "shadowsneak", "fakeout", "quickattack",
        "grassyglide", "firstimpression", "allyswitch", "helpinghand",
        "ragepowder", "followme", "protect", "detect", "spikyshield",
        "kingsshield", "banefulbunker", "silktrap", "feint", "watershuriken",
        "accelerock", "babyeyeddolls"
    }

    def __init__(self, filepath="logs/doubles_decision_audit.jsonl", reset=True, detail_level="top5",
                 benchmark_arm="", singleton_safety_enabled=False, priority_safety_enabled=False,
                 live_event_filepath=None, live_event_reset=True):
        self.filepath = filepath
        self.reset = reset
        self.detail_level = detail_level
        self.pending_turns = {}      # maps battle_tag -> turn_dict
        self.completed_turns = {}    # maps battle_tag -> list of turn_dicts
        self.battle_configs = {}     # maps battle_tag -> config (first seen)
        self._benchmark_arm = benchmark_arm
        self._singleton_safety_enabled = singleton_safety_enabled
        self._priority_safety_enabled = priority_safety_enabled
        self.live_event_filepath = live_event_filepath
        self._live_stream_failed = False

        # Ensure directory exists
        filepath_dir = os.path.dirname(self.filepath)
        if filepath_dir:
            os.makedirs(filepath_dir, exist_ok=True)

        # Clear file if reset is enabled
        if self.reset and os.path.exists(self.filepath):
            try:
                os.remove(self.filepath)
            except Exception:
                pass

        if self.live_event_filepath:
            try:
                live_dir = os.path.dirname(self.live_event_filepath)
                if live_dir:
                    os.makedirs(live_dir, exist_ok=True)
                if live_event_reset and os.path.exists(self.live_event_filepath):
                    os.remove(self.live_event_filepath)
            except Exception:
                self._live_stream_failed = True

    def _is_all_target_immune_damaging_spread(self, order, slot_idx, battle, config) -> bool:
        """Check if an order is a damaging spread move with all opponent targets immune."""
        if not order or not hasattr(order, "order"):
            return False
        # Check if it's a Move
        try:
            from poke_env.battle.move import Move
            if not isinstance(order.order, Move):
                return False
        except Exception:
            if not hasattr(order.order, "base_power"):
                return False

        move = order.order
        if getattr(move, "base_power", 0) <= 0:
            return False  # not a damaging move

        # Check if spread move targeting opponents
        target_pos = getattr(order, "move_target", None)
        if target_pos not in (0, 1, 2):
            return False

        is_spread = False
        target_type = getattr(move, "deduced_target", None)
        try:
            from poke_env.battle.move import Target
            if target_type in (Target.ALL, Target.ALL_ADJACENT, Target.ALL_ADJACENT_FOES):
                is_spread = True
        except Exception:
            pass
        target_str = getattr(move, "target", "")
        if target_str in ("allAdjacent", "allAdjacentFoes", "all"):
            is_spread = True

        if not is_spread:
            return False

        attacker = battle.active_pokemon[slot_idx] if slot_idx < len(battle.active_pokemon) else None
        if not attacker:
            return False

        opponent_actives = [opp for opp in battle.opponent_active_pokemon if opp and not getattr(opp, "fainted", False)]
        if not opponent_actives:
            return False

        from bot_doubles_damage_aware import is_type_immune
        for opp in opponent_actives:
            try:
                immune, _ = is_type_immune(move, attacker, opp, battle)
                if not immune:
                    return False
            except Exception:
                return False

        return True

    _LIVE_SLOT_KEYS = (
        "action", "move_type", "action_types", "selected_score",
        "expected_damage", "expected_ko", "target_species", "target_hp_before",
        "spread_available", "best_spread_score", "best_ko_score",
        "zero_effectiveness_move_selected", "all_targets_immune_spread_selected",
        "partial_immune_spread_selected", "partial_ability_immune_spread_selected",
        "efficient_partial_spread_selected", "inefficient_partial_spread_selected",
        "speed_priority_threatened", "faster_opponents", "priority_opponents",
        "expected_to_faint_before_moving", "protect_like_available", "switch_available",
        "ability_hard_block_avoided", "ability_immune_move_selected",
        "ground_into_levitate_selected", "ability_block_reason",
        "ability_blocked_target_species", "ability_blocked_target_ability",
        "direct_absorb_hard_block_avoided", "direct_absorb_immune_move_selected",
        "selected_switch_species", "selected_switch_types", "selected_switch_hp_fraction",
        "revealed_switch_prediction_available", "revealed_switch_interception_selected",
        "revealed_switch_selection_changed", "revealed_switch_prediction_reason",
        "singleton_ability_resolved", "singleton_ability_name",
        "singleton_ability_source", "singleton_hard_block_applied",
        "singleton_selection_changed_by_safety",
        "priority_move_field_blocked", "priority_move_block_reason",
        "priority_move_block_avoided", "priority_move_selected_into_psychic_terrain",
        "our_type_immune_move_selected", "our_type_immune_move_avoided",
    )
    _LIVE_OUTCOME_KEYS = (
        "outcome_known", "actual_ko", "actual_damage", "target_used_protect",
        "our_mon_fainted", "fainted_before_moving", "was_targeted",
        "opponent_survived_below_20", "revealed_switch_prediction_correct",
        "revealed_switch_prediction_wrong", "revealed_switch_post_turn_survived",
        "revealed_switch_candidate_fainted", "revealed_switch_post_turn_damage_taken",
    )

    def _compact_slot(self, slot, keys):
        slot = slot if isinstance(slot, dict) else {}
        return {key: slot.get(key) for key in keys if key in slot}

    def _append_live_event(self, event):
        if not self.live_event_filepath or self._live_stream_failed:
            return
        try:
            payload = dict(event)
            payload.setdefault("schema_version", 1)
            with open(self.live_event_filepath, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
        except Exception:
            # The visualizer is observational. Logging failure must never affect a battle.
            self._live_stream_failed = True

    def _build_live_decision_event(self, battle_tag, turn_data):
        slots = [turn_data.get("slot_0") or {}, turn_data.get("slot_1") or {}]
        flags = {
            key: turn_data.get(key)
            for key in (
                "focus_fire_triggered", "overkill_penalty_triggered",
                "ally_hit_penalty_triggered", "low_hp_opponent_existed",
                "low_hp_opponent_targeted", "partial_immune_spread_selected",
                "partial_ability_immune_spread_selected",
            )
            if key in turn_data
        }
        for key in ("partial_immune_spread_selected", "partial_ability_immune_spread_selected"):
            flags[key] = any(bool(slot.get(key)) for slot in slots)
        return {
            "event": "decision",
            "battle_tag": str(battle_tag),
            "turn": turn_data.get("turn"),
            "our_active": turn_data.get("our_active", []),
            "opp_active": turn_data.get("opp_active", []),
            "opponent_actives_state": turn_data.get("opponent_actives_state", []),
            "selected_joint_order": turn_data.get("selected_joint_order"),
            "selected_score": turn_data.get("selected_score"),
            "top_5_alternatives": turn_data.get("top_5_alternatives", []),
            "top_5_scores": turn_data.get("top_5_scores", []),
            "score_gap_selected_best_alt": turn_data.get("score_gap_selected_best_alt"),
            "total_legal_joint_orders": turn_data.get("total_legal_joint_orders"),
            "flags": flags,
            "slot_0": self._compact_slot(turn_data.get("slot_0"), self._LIVE_SLOT_KEYS),
            "slot_1": self._compact_slot(turn_data.get("slot_1"), self._LIVE_SLOT_KEYS),
        }

    def _build_live_outcome_event(self, battle_tag, turn_data):
        return {
            "event": "outcome",
            "battle_tag": str(battle_tag),
            "turn": turn_data.get("turn"),
            "slot_0": self._compact_slot(turn_data.get("slot_0"), self._LIVE_OUTCOME_KEYS),
            "slot_1": self._compact_slot(turn_data.get("slot_1"), self._LIVE_OUTCOME_KEYS),
            "opp_actions": turn_data.get("opp_actions", {}),
        }

    def _normalize_name(self, name: str) -> str:
        return "".join(c for c in name.lower() if c.isalnum())

    def _check_opponent_ability_errors(self, turn_events, player_role, opp_role):
        recognized = {
            "levitate", "eartheater", "waterabsorb", "stormdrain", "dryskin",
            "voltabsorb", "motordrive", "lightningrod", "flashfire",
            "wellbakedbody", "sapsipper", "soundproof", "bulletproof", "damp",
        }
        saw_resolvable_move = False
        ability_error = False
        ground_into_levitate = False

        for index, msg in enumerate(turn_events):
            if len(msg) < 3 or msg[0] != "move" or not msg[1].startswith(opp_role):
                continue

            # Gather all events for this move
            move_subevents = []
            for follow in turn_events[index + 1:]:
                if follow and follow[0] == "move":
                    break
                move_subevents.append(follow)

            # Find which player slots (e.g., p1a, p1b) were targeted or affected
            affected_slots = set()
            immune_slots = {}  # slot -> ability_name

            for sub_msg in move_subevents:
                if len(sub_msg) < 2:
                    continue
                subject = sub_msg[1]
                if subject.startswith(player_role):
                    slot = subject.split(":", 1)[0]
                    affected_slots.add(slot)

                    # Check if ability activated
                    revealed = ""
                    if sub_msg[0] == "-ability" and len(sub_msg) >= 3:
                        revealed = self._normalize_name(sub_msg[2])
                    else:
                        for part in sub_msg[2:]:
                            if "ability:" in part.lower():
                                revealed = self._normalize_name(part.lower().split("ability:", 1)[1])
                                break
                    if revealed in recognized:
                        immune_slots[slot] = revealed

            if not affected_slots:
                continue

            saw_resolvable_move = True

            # Specifically support spread moves: only count a spread move as an opponent ability error
            # if *all* of our active targets in the turn log are immune/blocked by that ability.
            if len(immune_slots) == len(affected_slots) and len(affected_slots) > 0:
                abilities = set(immune_slots.values())
                if len(abilities) == 1:
                    ability = list(abilities)[0]
                    ability_error = True
                    if ability == "levitate":
                        move_id = self._normalize_name(msg[2])
                        try:
                            from poke_env.battle.move import Move
                            m = Move(move_id, gen=9)
                            move_type = getattr(getattr(m, "type", None), "name", "")
                            if move_type == "GROUND":
                                ground_into_levitate = True
                        except Exception:
                            pass
                    break

        if not saw_resolvable_move:
            return None, None
        return ability_error, ground_into_levitate

    def log_turn_decision(
        self,
        battle_tag,
        turn,
        battle,
        selected_joint_order,
        selected_score,
        scored_joint_orders,
        expected_damages,
        expected_kos,
        target_hps,
        overkill_triggered,
        focus_fire_triggered,
        ally_hit_penalty_triggered,
        spread_available,
        best_spread_score,
        best_ko_score,
        low_hp_opponent_existed,
        low_hp_opponent_targeted,
        slot_actions,       # list of action representations (e.g. str(order))
        slot_action_types,  # list of dicts: {"damaging": bool, "status": bool, ...}
        target_species,     # list of target species name or None
        partial_immune_spread_selected=None,
        partial_ability_immune_spread_selected=None,
        efficient_partial_spread_selected=None,
        inefficient_partial_spread_selected=None,
        immune_target_species=None,
        damaged_target_species=None,
        best_single_target_alternative=None,
        speed_priority_threatened=None,
        faster_opponents=None,
        priority_opponents=None,
        speed_priority_protect_bonus_applied=None,
        speed_priority_attack_penalty_applied=None,
        speed_priority_switch_bonus_applied=None,
        order_aware_overkill_penalty_applied=None,
        expected_to_faint_before_moving=None,
        protected_due_to_speed_priority=None,
        protect_like_available=None,
        switch_available=None,
        only_conditional_priority=None,
        stalling_field_condition=None,
        ability_hard_block_avoided=None,
        ability_immune_move_selected=None,
        ground_into_levitate_selected=None,
        ability_block_reason=None,
        ability_blocked_target_species=None,
        ability_blocked_target_ability=None,
        ally_ability_safe_spread=None,
        ability_redirection_avoided=None,
        absorb_immune_move_selected=None,
        absorb_selection_forced=None,
        absorb_safe_alternative_available=None,
        absorb_best_safe_alternative_move=None,
        absorb_best_safe_alternative_target=None,
        absorb_best_safe_alternative_score=None,
        absorb_selected_score=None,
        absorb_selected_streak=None,
        avoidable_absorb_error=None,
        productive_partial_absorb_spread=None,
        absorb_error_reason=None,
        # Phase 6.3.2a new target diagnostic fields
        absorb_via_redirection=None,
        absorb_intended_target_species=None,
        absorb_intended_target_ability=None,
        absorb_effective_target_species=None,
        absorb_effective_target_ability=None,
        absorb_selected_move_id=None,
        direct_absorb_hard_block_avoided=None,
        direct_absorb_immune_move_selected=None,
        direct_absorb_block_reason=None,
        direct_absorb_target_species=None,
        direct_absorb_target_ability=None,
        direct_absorb_only_legal_action=None,
        # Phase 6.3.6: Known Absorb Hard Safety fields
        direct_known_absorb_repeat_selected=None,
        # Phase 6.4: Switch Candidate Safety fields
        forced_switch=None,
        switch_candidate_type_safety_applied=None,
        selected_switch_species=None,
        selected_switch_types=None,
        selected_switch_hp_fraction=None,
        selected_switch_raw_safety_score=None,
        selected_switch_relative_adjustment=None,
        selected_switch_worst_multiplier=None,
        selected_switch_double_threat=None,
        unsafe_switch_candidate_selected=None,
        safer_switch_candidate_available=None,
        best_safe_switch_species=None,
        best_safe_switch_score=None,
        switch_type_safety_avoided=None,
        # Phase 6.4.3a.2: Forced switch diagnostic fields
        forced_switch_candidate_count=None,
        forced_switch_selected_index=None,
        forced_switch_selected_species=None,
        forced_switch_best_safety_species=None,
        forced_switch_selected_safety_score=None,
        forced_switch_best_safety_score=None,
        forced_switch_order_fallback_used=None,
        # Phase 6.4.4: Forced switch replacement safety fields
        forced_switch_safety_enabled=None,
        forced_switch_safety_selection_changed=None,
        forced_switch_selected_double_threat=None,
        forced_switch_best_avoids_double_threat=None,
        forced_switch_selected_quad_weak=None,
        forced_switch_best_avoids_quad_weak=None,
        forced_switch_selected_low_hp=None,
        forced_switch_reason=None,
        forced_switch_candidate_safety_table=None,
        # Phase 6.4.3a.3: Decision timing diagnostics
        decision_time_ms=None,
        valid_order_time_ms=None,
        score_action_time_ms=None,
        joint_scoring_time_ms=None,
        audit_postprocess_time_ms=None,
        score_action_call_count=None,
        joint_order_count=None,
        # Phase 6.4: Negative boost diagnostics
        neg_boost_total_negative_stages=None,
        neg_boost_lowest_stage=None,
        neg_boost_offensive_negative_stages=None,
        neg_boost_defensive_negative_stages=None,
        neg_boost_speed_negative_stage=None,
        neg_boost_severe_negative_boost=None,
        neg_boost_was_switch=None,
        # Phase 6.4a: Negative-boost eligibility
        neg_boost_decision_eligible=None,
        neg_boost_selected_action_kind=None,
        neg_boost_legal_switch_count=None,
        neg_boost_best_switch_species=None,
        neg_boost_best_switch_score=None,
        neg_boost_best_move_score=None,
        neg_boost_switch_score_gap=None,
        neg_boost_relevant_offensive_drop=None,
        neg_boost_defensive_drop=None,
        neg_boost_speed_drop=None,
        # Phase 6.4.3: Stat-Drop Switch Diagnostics
        severe_neg_boost_active=None,
        severe_neg_boost_categories=None,
        severe_neg_boost_switch_available=None,
        severe_neg_boost_switched=None,
        severe_neg_boost_stayed=None,
        severe_neg_boost_stayed_productive=None,
        severe_neg_boost_stayed_unproductive=None,
        severe_neg_boost_only_legal_no_switch=None,
        severe_neg_boost_best_switch_candidate=None,
        severe_neg_boost_selected_action=None,
        severe_neg_boost_turn=None,
        severe_neg_boost_species=None,
        # Phase 6.4.2: Revealed-Move Switch Interception
        revealed_switch_prediction_available=None,
        revealed_switch_interception_selected=None,
        revealed_switch_selection_changed=None,
        revealed_switch_threatening_opponent=None,
        revealed_switch_threat_move_ids=None,
        revealed_switch_threat_move_types=None,
        revealed_switch_target_likelihood=None,
        revealed_switch_active_risk=None,
        revealed_switch_candidate_risk=None,
        revealed_switch_risk_reduction=None,
        revealed_switch_candidate_species=None,
        revealed_switch_candidate_types=None,
        revealed_switch_candidate_hp=None,
        revealed_switch_bonus_applied=None,
        revealed_switch_blocked_by_ko_action=None,
        revealed_switch_blocked_by_high_value_action=None,
        revealed_switch_rejected_worse_other_threat=None,
        revealed_switch_post_turn_damage_taken=None,
        revealed_switch_post_turn_survived=None,
        revealed_switch_predicted_move_used=None,
        revealed_switch_prediction_correct=None,
        revealed_switch_prediction_wrong=None,
        # Phase 6.4.2: Type-immune audit fields
        our_type_immune_move_selected=None,
        our_type_immune_only_legal=None,
        our_type_immune_move_avoided=None,
        opponent_type_immune_move_selected=None,
        our_type_immune_attacker=None,
        our_type_immune_move=None,
        our_type_immune_target=None,
        our_type_immune_target_types=None,
        our_type_immune_reason=None,
        # Phase 6.3.5: Ground-into-Flying audit fields
        ground_into_flying_selected=None,
        ground_into_secondary_flying_selected=None,
        ground_into_flying_avoided=None,
        ground_into_flying_only_legal=None,
        ground_flying_exception_applied=None,
        ground_flying_exception_reason=None,
        ground_flying_target_primary_type=None,
        ground_flying_target_secondary_type=None,
        # Phase 6.3.5: Singleton ability safety fields
        known_ability_resolution_source=None,
        deterministic_singleton_ability_used=None,
        deterministic_singleton_ability=None,
        deterministic_singleton_target_species=None,
        singleton_ability_hard_block_avoided=None,
        singleton_ground_into_levitate_selected=None,
        singleton_ability_conflict_detected=None,
        singleton_ability_suppressed=None,
        singleton_ability_suppression_reason=None,
        singleton_only_legal_action=None,
        priority_move_field_blocked=None,
        priority_move_block_reason=None,
        priority_move_selected_into_psychic_terrain=None,
        sucker_punch_selected_into_psychic_terrain=None,
        priority_move_block_avoided=None,
        priority_move_only_legal=None,
        priority_target_grounded=None,
        priority_target_species=None,
        priority_target_type_1=None,
        priority_target_type_2=None,
        priority_blocking_ability=None,
        priority_blocking_ability_source=None,
        singleton_levitate_opportunity_observed=None,
        singleton_ground_into_levitate_selected_observed=None,
        singleton_hard_block_applied=None,
        singleton_blocked_candidate_observed=None,
        singleton_selection_changed_by_safety=None,
        singleton_resolution_source=None,
        config=None,
        # Phase 6.4.5: Stale Target / Retarget Immunity Safety
        stale_target_selected=None,
        stale_target_avoided=None,
        stale_target_same_target_expected_ko=None,
        stale_target_caused_no_effect=None,
        stale_target_caused_type_immune=None,
        stale_target_first_slot=None,
        stale_target_first_move=None,
        stale_target_first_target=None,
        stale_target_second_slot=None,
        stale_target_second_move=None,
        stale_target_second_intended_target=None,
        stale_target_fallback_target=None,
        stale_target_reason=None,
        # Phase 6.4.7: Stat-drop switch scoring audit fields
        stat_drop_switch_scoring_enabled=None,
        stat_drop_switch_pressure_active=None,
        stat_drop_switch_pressure_categories=None,
        stat_drop_switch_pressure_score=None,
        stat_drop_switch_selected=None,
        stat_drop_switch_stayed=None,
        stat_drop_switch_stayed_productive=None,
        stat_drop_switch_stayed_unproductive=None,
        stat_drop_switch_selection_changed=None,
        stat_drop_switch_best_switch_species=None,
        stat_drop_switch_best_switch_score=None,
        stat_drop_switch_best_non_switch_score=None,
        stat_drop_switch_reason=None,
        stat_drop_switch_threshold_source=None,
        # Phase 6.3.6b: Known Ally Redirection
        known_ally_redirection_selected=None,
        known_ally_redirection_reason=None,
        known_ally_redirection_ally_species=None,
        known_ally_redirection_ally_ability=None,
        known_ally_redirection_move_id=None,
        known_ally_redirection_known_before_decision=None,
        known_ally_redirection_candidate_blocked=None,
        known_ally_redirection_avoided=None,
        known_ally_redirection_only_legal=None,
        known_ally_redirection_repeat_selected=None,
        known_ally_redirection_safe_alternative_available=None,
        our_known_ally_redirection_error=None,
        opponent_known_ally_redirection_error=None,
        # Phase 6.3.7: Dynamic move type fields
        declared_move_type=None,
        effective_move_type=None,
        effective_move_type_source=None,
        dynamic_move_type_applied=None,
        dynamic_move_type_form=None,
        # Phase 6.3.7f: Dynamic absorb candidate audit fields (per-slot lists)
        dynamic_type_absorb_candidate_blocked=None,
        dynamic_type_absorb_selected=None,
        dynamic_type_absorb_avoided=None,
        dynamic_type_absorb_reason=None,
        dynamic_type_absorb_target_species=None,
        dynamic_type_absorb_target_ability=None,
        dynamic_type_absorb_blocked_move_id=None,
        dynamic_type_absorb_blocked_candidate_score=None,
        dynamic_type_absorb_candidate_available=None,
        dynamic_type_absorb_candidate_move_id=None,
        dynamic_type_absorb_candidate_declared_type=None,
        dynamic_type_absorb_candidate_effective_type=None,
        dynamic_type_absorb_candidate_form=None,
        dynamic_type_absorb_candidate_source=None,
        dynamic_type_absorb_candidate_target_table=None,
        # Phase 6.3.6b.6: Blocked candidate metadata
        known_ally_redirection_opportunity_observed=None,
        known_ally_redirection_blocked_candidate_move_id=None,
        known_ally_redirection_blocked_candidate_attacker_species=None,
        known_ally_redirection_blocked_candidate_target_species=None,
        known_ally_redirection_blocked_candidate_ally_species=None,
        known_ally_redirection_blocked_candidate_ally_ability=None,
        known_ally_redirection_blocked_candidate_reason=None,
        known_ally_redirection_blocked_candidate_known_before=None,
        known_ally_redirection_blocked_candidate_score=None,
        known_ally_redirection_best_safe_alternative=None,
        known_ally_redirection_best_safe_alternative_score=None,
        **kwargs,
    ):

        """
        Record the decision metadata at the start of a turn. Resolves the previous turn's pending outcomes first.
        """
        # 1. Update previous turn's pending outcomes if they exist
        self.update_previous_turn(battle_tag, battle)

        # Store config for top-level metadata (first seen per battle)
        if battle_tag not in self.battle_configs and config is not None:
            self.battle_configs[battle_tag] = config

        # 2. Extract top 5 alternatives
        # scored_joint_orders is a list of (joint_order, score, score_1, score_2)
        total_legal_orders = len(scored_joint_orders)
        top_5_alts = []
        top_5_scores = []
        best_alt_score = 0.0

        # Exclude selected order which is first
        alt_candidates = scored_joint_orders[1:] if len(scored_joint_orders) > 1 else []
        for i, (joint_order, score, _, _) in enumerate(alt_candidates):
            if i < 5:
                top_5_alts.append(joint_order.message if joint_order else "/choose pass")
                top_5_scores.append(float(score))
            if i == 0:
                best_alt_score = float(score)

        score_gap = selected_score - best_alt_score if total_legal_orders > 1 else 0.0

        # Check if both slots targeted same opponent
        both_slots_same = False
        first_order = scored_joint_orders[0][0].first_order if total_legal_orders > 0 else None
        second_order = scored_joint_orders[0][0].second_order if total_legal_orders > 0 else None
        if first_order and second_order:
            if getattr(first_order, "move_target", None) == getattr(second_order, "move_target", None):
                if getattr(first_order, "move_target", None) in (1, 2):
                    both_slots_same = True

        # Compute new Phase 6.1 audit flags
        zero_effectiveness_0 = False
        zero_effectiveness_1 = False
        all_targets_immune_0 = False
        all_targets_immune_1 = False
        self_drop_candidate_0 = False
        self_drop_candidate_1 = False
        move_type_0 = ""
        move_type_1 = ""

        try:
            from bot_doubles_damage_aware import is_type_immune

            def check_slot_flags(slot_idx, order):
                zero_eff = False
                all_imm = False
                self_drop_cand = False
                move_type = ""

                if order and hasattr(order, "order") and order.order:
                    move_obj = order.order
                    type_obj = getattr(move_obj, "type", None)
                    move_type = getattr(type_obj, "name", str(type_obj or ""))
                    if hasattr(move_obj, "base_power") and move_obj.base_power > 0:
                        attacker_mon = battle.active_pokemon[slot_idx] if len(battle.active_pokemon) > slot_idx else None
                        target_pos = getattr(order, "move_target", None)

                        # 1. zero_effectiveness_move_selected
                        if target_pos in (1, 2):
                            target_mon = battle.opponent_active_pokemon[target_pos - 1] if len(battle.opponent_active_pokemon) > (target_pos - 1) else None
                            if attacker_mon and target_mon:
                                immune, _ = is_type_immune(move_obj, attacker_mon, target_mon, battle)
                                if immune:
                                    zero_eff = True

                        # 2. all_targets_immune_spread_selected
                        if target_pos == 0:
                            opps = [opp for opp in battle.opponent_active_pokemon if opp]
                            if opps:
                                all_targets_immune = True
                                for opp in opps:
                                    immune, _ = is_type_immune(move_obj, attacker_mon, opp, battle)
                                    if not immune:
                                        all_targets_immune = False
                                        break
                                if all_targets_immune:
                                    all_imm = True

                        # 3. self_drop_move_spam
                        move_id = move_obj.id.lower().replace(" ", "").replace("-", "").replace("_", "").strip() if hasattr(move_obj, "id") else ""
                        if move_id in ("dracometeor", "overheat", "leafstorm", "fleurcannon", "psychoboost"):
                            spa_boost = 0
                            if attacker_mon and hasattr(attacker_mon, "boosts") and attacker_mon.boosts:
                                spa_boost = attacker_mon.boosts.get("spa", 0)
                            if spa_boost <= -2:
                                self_drop_cand = True
                return zero_eff, all_imm, self_drop_cand, move_type

            first_order = scored_joint_orders[0][0].first_order if total_legal_orders > 0 else None
            zero_effectiveness_0, all_targets_immune_0, self_drop_candidate_0, move_type_0 = check_slot_flags(0, first_order)

            second_order = scored_joint_orders[0][0].second_order if total_legal_orders > 0 else None
            zero_effectiveness_1, all_targets_immune_1, self_drop_candidate_1, move_type_1 = check_slot_flags(1, second_order)
        except Exception:
            pass

        # Phase 6.4.10b: All-target immune spread flags
        all_target_immune_avoided = [False, False]
        all_target_immune_only_legal = [False, False]
        all_target_immune_penalized = [False, False]
        for slot_idx, order in enumerate([first_order, second_order]):
            if order and self._is_all_target_immune_damaging_spread(order, slot_idx, battle, config):
                # Check if there's a better joint order without this all-immune spread
                has_better_alternative = False
                for other_joint_order, other_score, other_s0, other_s1 in scored_joint_orders[1:]:
                    other_order = other_joint_order.first_order if slot_idx == 0 else other_joint_order.second_order
                    if not self._is_all_target_immune_damaging_spread(other_order, slot_idx, battle, config):
                        has_better_alternative = True
                        break
                if has_better_alternative:
                    all_target_immune_avoided[slot_idx] = True
                    all_target_immune_penalized[slot_idx] = True
                else:
                    all_target_immune_only_legal[slot_idx] = True

        # Build actives info
        active_1 = battle.active_pokemon[0] if len(battle.active_pokemon) > 0 else None
        active_2 = battle.active_pokemon[1] if len(battle.active_pokemon) > 1 else None
        opp_1 = battle.opponent_active_pokemon[0] if len(battle.opponent_active_pokemon) > 0 else None
        opp_2 = battle.opponent_active_pokemon[1] if len(battle.opponent_active_pokemon) > 1 else None

        opponents_info = []
        for opp in [opp_1, opp_2]:
            if not opp:
                opponents_info.append(None)
                continue

            from bot_doubles_damage_aware import resolve_known_ability, normalize_possible_abilities

            res = resolve_known_ability(opp, battle, config)
            ground_blocked = False
            if res["ability"] == "levitate" and not res["is_currently_suppressed"]:
                is_g = False
                if battle:
                    try:
                        is_g = battle.is_grounded(opp)
                    except Exception:
                        pass
                if not is_g:
                    ground_blocked = True

            singleton_flag = False
            if config:
                singleton_flag = getattr(config, "ability_hard_safety_allow_singleton_deduction", False)

            raw_poss = getattr(opp, "possible_abilities", [])
            opponents_info.append({
                "species": str(getattr(opp, "species", "")),
                "ability": str(getattr(opp, "ability", "")) if getattr(opp, "ability", None) else None,
                "temporary_ability": str(getattr(opp, "temporary_ability", "")) if getattr(opp, "temporary_ability", None) else None,
                "possible_abilities": raw_poss if isinstance(raw_poss, (dict, list, tuple, set)) else [raw_poss] if raw_poss else [],
                "normalized_possible_abilities": normalize_possible_abilities(raw_poss),
                "resolved_ability": res["ability"],
                "resolved_source": res["source"],
                "singleton_flag_state": singleton_flag,
                "ground_blocked": ground_blocked,
            })

        score_0 = float(scored_joint_orders[0][2]) if total_legal_orders > 0 else 0.0
        score_1 = float(scored_joint_orders[0][3]) if total_legal_orders > 0 else 0.0

        turn_data = {
            "turn": int(turn),
            "our_active": [
                {"species": active_1.species, "hp": float(active_1.current_hp_fraction)} if (active_1 and active_1.current_hp_fraction is not None) else None,
                {"species": active_2.species, "hp": float(active_2.current_hp_fraction)} if (active_2 and active_2.current_hp_fraction is not None) else None
            ],
            "opp_active": [
                {"species": opp_1.species, "hp": float(opp_1.current_hp_fraction)} if (opp_1 and opp_1.current_hp_fraction is not None) else None,
                {"species": opp_2.species, "hp": float(opp_2.current_hp_fraction)} if (opp_2 and opp_2.current_hp_fraction is not None) else None
            ],
            "opponent_actives_state": opponents_info,
            "selected_joint_order": str(selected_joint_order),
            "selected_score": float(selected_score),
            "top_5_alternatives": top_5_alts,
            "top_5_scores": top_5_scores,
            "score_gap_selected_best_alt": float(score_gap),
            "total_legal_joint_orders": int(total_legal_orders),
            "both_slots_targeted_same_opp": bool(both_slots_same),
            "overkill_penalty_triggered": bool(overkill_triggered),
            "focus_fire_triggered": bool(focus_fire_triggered),
            "ally_hit_penalty_triggered": bool(ally_hit_penalty_triggered),
            "low_hp_opponent_existed": bool(low_hp_opponent_existed),
            "low_hp_opponent_targeted": bool(low_hp_opponent_targeted),
            "order_aware_overkill_penalty_applied": bool(order_aware_overkill_penalty_applied) if order_aware_overkill_penalty_applied else False,
            # Phase 6.4.5: Stale target safety audit fields
            "stale_target_selected": bool(stale_target_selected) if stale_target_selected else False,
            "stale_target_avoided": bool(stale_target_avoided) if stale_target_avoided else False,
            "stale_target_same_target_expected_ko": bool(stale_target_same_target_expected_ko) if stale_target_same_target_expected_ko else False,
            "stale_target_caused_no_effect": bool(stale_target_caused_no_effect) if stale_target_caused_no_effect else False,
            "stale_target_caused_type_immune": bool(stale_target_caused_type_immune) if stale_target_caused_type_immune else False,
            "stale_target_first_slot": int(stale_target_first_slot) if stale_target_first_slot is not None else 0,
            "stale_target_first_move": str(stale_target_first_move) if stale_target_first_move else "",
            "stale_target_first_target": str(stale_target_first_target) if stale_target_first_target else "",
            "stale_target_second_slot": int(stale_target_second_slot) if stale_target_second_slot is not None else 1,
            "stale_target_second_move": str(stale_target_second_move) if stale_target_second_move else "",
            "stale_target_second_intended_target": str(stale_target_second_intended_target) if stale_target_second_intended_target else "",
            "stale_target_fallback_target": str(stale_target_fallback_target) if stale_target_fallback_target else "",
            "stale_target_reason": str(stale_target_reason) if stale_target_reason else "",
            # Phase 6.4.3a.3: Decision timing diagnostics (turn-level)
            "decision_time_ms": float(decision_time_ms) if decision_time_ms is not None else None,
            "valid_order_time_ms": float(valid_order_time_ms) if valid_order_time_ms is not None else None,
            "score_action_time_ms": float(score_action_time_ms) if score_action_time_ms is not None else None,
            "joint_scoring_time_ms": float(joint_scoring_time_ms) if joint_scoring_time_ms is not None else None,
            "audit_postprocess_time_ms": float(audit_postprocess_time_ms) if audit_postprocess_time_ms is not None else None,
            "score_action_call_count": int(score_action_call_count) if score_action_call_count is not None else None,
            "joint_order_count": int(joint_order_count) if joint_order_count is not None else None,
            "slot_0": {
                "action": str(slot_actions[0]) if slot_actions[0] else None,
                "move_type": move_type_0,
                "action_types": slot_action_types[0],
                "selected_score": score_0,
                "expected_damage": float(expected_damages[0]) if expected_damages[0] is not None else None,
                "expected_ko": bool(expected_kos[0]) if expected_kos[0] is not None else None,
                "target_hp_before": float(target_hps[0]) if target_hps[0] is not None else None,
                "target_species": target_species[0],
                "spread_available": bool(spread_available[0]),
                "best_spread_score": float(best_spread_score[0]) if best_spread_score[0] is not None else None,
                "best_ko_score": float(best_ko_score[0]) if best_ko_score[0] is not None else None,
                "zero_effectiveness_move_selected": bool(zero_effectiveness_0),
                "all_targets_immune_spread_selected": bool(all_targets_immune_0),
                "all_target_immune_spread_avoided": bool(all_target_immune_avoided[0]) if all_target_immune_avoided else False,
                "all_target_immune_spread_only_legal": bool(all_target_immune_only_legal[0]) if all_target_immune_only_legal else False,
                "all_target_immune_spread_joint_penalized": bool(all_target_immune_penalized[0]) if all_target_immune_penalized else False,
                "self_drop_spam_candidate": bool(self_drop_candidate_0),
                "self_drop_move_spam": False,
                "outcome_known": False,
                "actual_ko": None,
                "actual_damage": None,
                "target_used_protect": None,
                "our_mon_fainted": None,
                "fainted_before_moving": None,
                "partial_immune_spread_selected": bool(partial_immune_spread_selected[0]) if partial_immune_spread_selected else False,
                "partial_ability_immune_spread_selected": bool(partial_ability_immune_spread_selected[0]) if partial_ability_immune_spread_selected else False,
                "efficient_partial_spread_selected": bool(efficient_partial_spread_selected[0]) if efficient_partial_spread_selected else False,
                "inefficient_partial_spread_selected": bool(inefficient_partial_spread_selected[0]) if inefficient_partial_spread_selected else False,
                "immune_target_species": list(immune_target_species[0]) if (immune_target_species and immune_target_species[0]) else [],
                "damaged_target_species": list(damaged_target_species[0]) if (damaged_target_species and damaged_target_species[0]) else [],
                "best_single_target_alternative": str(best_single_target_alternative[0]) if (best_single_target_alternative and best_single_target_alternative[0]) else "",
                "speed_priority_threatened": bool(speed_priority_threatened[0]) if (speed_priority_threatened and len(speed_priority_threatened) > 0) else False,
                "faster_opponents": list(faster_opponents[0]) if (faster_opponents and len(faster_opponents) > 0 and faster_opponents[0]) else [],
                "priority_opponents": list(priority_opponents[0]) if (priority_opponents and len(priority_opponents) > 0 and priority_opponents[0]) else [],
                "speed_priority_protect_bonus_applied": bool(speed_priority_protect_bonus_applied[0]) if (speed_priority_protect_bonus_applied and len(speed_priority_protect_bonus_applied) > 0) else False,
                "speed_priority_attack_penalty_applied": bool(speed_priority_attack_penalty_applied[0]) if (speed_priority_attack_penalty_applied and len(speed_priority_attack_penalty_applied) > 0) else False,
                "speed_priority_switch_bonus_applied": bool(speed_priority_switch_bonus_applied[0]) if (speed_priority_switch_bonus_applied and len(speed_priority_switch_bonus_applied) > 0) else False,
                "expected_to_faint_before_moving": bool(expected_to_faint_before_moving[0]) if (expected_to_faint_before_moving and len(expected_to_faint_before_moving) > 0) else False,
                "protected_due_to_speed_priority": bool(protected_due_to_speed_priority[0]) if (protected_due_to_speed_priority and len(protected_due_to_speed_priority) > 0) else False,
                "protect_like_available": bool(protect_like_available[0]) if (protect_like_available and len(protect_like_available) > 0) else False,
                "switch_available": bool(switch_available[0]) if (switch_available and len(switch_available) > 0) else False,
                "only_conditional_priority": bool(only_conditional_priority[0]) if (only_conditional_priority and len(only_conditional_priority) > 0) else False,
                "stalling_field_condition": bool(stalling_field_condition[0]) if (stalling_field_condition and len(stalling_field_condition) > 0) else False,
                "ability_hard_block_avoided": bool(ability_hard_block_avoided[0]) if (ability_hard_block_avoided and len(ability_hard_block_avoided) > 0) else False,
                "ability_immune_move_selected": bool(ability_immune_move_selected[0]) if (ability_immune_move_selected and len(ability_immune_move_selected) > 0) else False,
                "our_bot_ability_error": bool(ability_immune_move_selected[0]) if (ability_immune_move_selected and len(ability_immune_move_selected) > 0) else False,
                "ground_into_levitate_selected": bool(ground_into_levitate_selected[0]) if (ground_into_levitate_selected and len(ground_into_levitate_selected) > 0) else False,
                "ability_block_reason": str(ability_block_reason[0]) if (ability_block_reason and len(ability_block_reason) > 0) else "",
                "ability_blocked_target_species": str(ability_blocked_target_species[0]) if (ability_blocked_target_species and len(ability_blocked_target_species) > 0) else "",
                "ability_blocked_target_ability": str(ability_blocked_target_ability[0]) if (ability_blocked_target_ability and len(ability_blocked_target_ability) > 0) else "",
                "ally_ability_safe_spread": bool(ally_ability_safe_spread[0]) if (ally_ability_safe_spread and len(ally_ability_safe_spread) > 0) else False,
                "ability_redirection_avoided": bool(ability_redirection_avoided[0]) if (ability_redirection_avoided and len(ability_redirection_avoided) > 0) else False,
                "absorb_immune_move_selected": bool(absorb_immune_move_selected[0]) if absorb_immune_move_selected else False,
                "absorb_selection_forced": bool(absorb_selection_forced[0]) if absorb_selection_forced else False,
                "absorb_safe_alternative_available": bool(absorb_safe_alternative_available[0]) if absorb_safe_alternative_available else False,
                "absorb_best_safe_alternative_move": str(absorb_best_safe_alternative_move[0]) if absorb_best_safe_alternative_move else "",
                "absorb_best_safe_alternative_target": str(absorb_best_safe_alternative_target[0]) if absorb_best_safe_alternative_target else "",
                "absorb_best_safe_alternative_score": float(absorb_best_safe_alternative_score[0]) if absorb_best_safe_alternative_score else 0.0,
                "absorb_selected_score": float(absorb_selected_score[0]) if absorb_selected_score else 0.0,
                "absorb_selected_streak": int(absorb_selected_streak[0]) if absorb_selected_streak else 0,
                "avoidable_absorb_error": bool(avoidable_absorb_error[0]) if avoidable_absorb_error else False,
                "productive_partial_absorb_spread": bool(productive_partial_absorb_spread[0]) if productive_partial_absorb_spread else False,
                "absorb_error_reason": str(absorb_error_reason[0]) if absorb_error_reason else "",
                "absorb_via_redirection": bool(absorb_via_redirection[0]) if absorb_via_redirection else False,
                "absorb_intended_target_species": str(absorb_intended_target_species[0]) if absorb_intended_target_species else "",
                "absorb_intended_target_ability": str(absorb_intended_target_ability[0]) if absorb_intended_target_ability else "",
                "absorb_effective_target_species": str(absorb_effective_target_species[0]) if absorb_effective_target_species else "",
                "absorb_effective_target_ability": str(absorb_effective_target_ability[0]) if absorb_effective_target_ability else "",
                "absorb_selected_move_id": str(absorb_selected_move_id[0]) if absorb_selected_move_id else "",
                "direct_absorb_hard_block_avoided": bool(direct_absorb_hard_block_avoided[0]) if direct_absorb_hard_block_avoided else False,
                "direct_absorb_immune_move_selected": bool(direct_absorb_immune_move_selected[0]) if direct_absorb_immune_move_selected else False,
                "direct_absorb_block_reason": str(direct_absorb_block_reason[0]) if direct_absorb_block_reason else "",
                "direct_absorb_target_species": str(direct_absorb_target_species[0]) if direct_absorb_target_species else "",
                "direct_absorb_target_ability": str(direct_absorb_target_ability[0]) if direct_absorb_target_ability else "",
                "direct_absorb_only_legal_action": bool(direct_absorb_only_legal_action[0]) if direct_absorb_only_legal_action else False,
                # Phase 6.3.6: Known Absorb Hard Safety
                "direct_known_absorb_repeat_selected": bool(direct_known_absorb_repeat_selected[0]) if direct_known_absorb_repeat_selected else False,
                # Phase 6.4: Switch Candidate Safety
                "forced_switch": bool(forced_switch[0]) if forced_switch else False,
                "switch_candidate_type_safety_applied": bool(switch_candidate_type_safety_applied[0]) if switch_candidate_type_safety_applied else False,
                "selected_switch_species": str(selected_switch_species[0]) if selected_switch_species else "",
                "selected_switch_types": str(selected_switch_types[0]) if selected_switch_types else "",
                "selected_switch_hp_fraction": float(selected_switch_hp_fraction[0]) if selected_switch_hp_fraction else 1.0,
                "selected_switch_raw_safety_score": float(selected_switch_raw_safety_score[0]) if selected_switch_raw_safety_score else 0.0,
                "selected_switch_relative_adjustment": float(selected_switch_relative_adjustment[0]) if selected_switch_relative_adjustment else 0.0,
                "selected_switch_worst_multiplier": float(selected_switch_worst_multiplier[0]) if selected_switch_worst_multiplier else 1.0,
                "selected_switch_double_threat": bool(selected_switch_double_threat[0]) if selected_switch_double_threat else False,
                "unsafe_switch_candidate_selected": bool(unsafe_switch_candidate_selected[0]) if unsafe_switch_candidate_selected else False,
                "safer_switch_candidate_available": bool(safer_switch_candidate_available[0]) if safer_switch_candidate_available else False,
                "best_safe_switch_species": str(best_safe_switch_species[0]) if best_safe_switch_species else "",
                "best_safe_switch_score": float(best_safe_switch_score[0]) if best_safe_switch_score else 0.0,
                "switch_type_safety_avoided": bool(switch_type_safety_avoided[0]) if switch_type_safety_avoided else False,
                # Phase 6.4.3a.2: Forced switch diagnostics (slot 0)
                "forced_switch_candidate_count": int(forced_switch_candidate_count[0]) if forced_switch_candidate_count else 0,
                "forced_switch_selected_index": int(forced_switch_selected_index[0]) if forced_switch_selected_index else -1,
                "forced_switch_selected_species": str(forced_switch_selected_species[0]) if forced_switch_selected_species else "",
                "forced_switch_best_safety_species": str(forced_switch_best_safety_species[0]) if forced_switch_best_safety_species else "",
                "forced_switch_selected_safety_score": float(forced_switch_selected_safety_score[0]) if forced_switch_selected_safety_score else 0.0,
                "forced_switch_best_safety_score": float(forced_switch_best_safety_score[0]) if forced_switch_best_safety_score else 0.0,
                "forced_switch_order_fallback_used": bool(forced_switch_order_fallback_used[0]) if forced_switch_order_fallback_used else False,
                # Phase 6.4.4: Forced switch replacement safety (slot 0)
                "forced_switch_safety_enabled": bool(forced_switch_safety_enabled[0]) if forced_switch_safety_enabled else False,
                "forced_switch_safety_selection_changed": bool(forced_switch_safety_selection_changed[0]) if forced_switch_safety_selection_changed else False,
                "forced_switch_selected_double_threat": bool(forced_switch_selected_double_threat[0]) if forced_switch_selected_double_threat else False,
                "forced_switch_best_avoids_double_threat": bool(forced_switch_best_avoids_double_threat[0]) if forced_switch_best_avoids_double_threat else False,
                "forced_switch_selected_quad_weak": bool(forced_switch_selected_quad_weak[0]) if forced_switch_selected_quad_weak else False,
                "forced_switch_best_avoids_quad_weak": bool(forced_switch_best_avoids_quad_weak[0]) if forced_switch_best_avoids_quad_weak else False,
                "forced_switch_selected_low_hp": bool(forced_switch_selected_low_hp[0]) if forced_switch_selected_low_hp else False,
                "forced_switch_reason": str(forced_switch_reason[0]) if forced_switch_reason else "",
                "forced_switch_candidate_safety_table": forced_switch_candidate_safety_table[0] if forced_switch_candidate_safety_table else None,
                # Phase 6.4: Negative Boost Diagnostics
                "neg_boost_total_negative_stages": int(neg_boost_total_negative_stages[0]) if neg_boost_total_negative_stages else 0,
                "neg_boost_lowest_stage": int(neg_boost_lowest_stage[0]) if neg_boost_lowest_stage else 0,
                "neg_boost_offensive_negative_stages": int(neg_boost_offensive_negative_stages[0]) if neg_boost_offensive_negative_stages else 0,
                "neg_boost_defensive_negative_stages": int(neg_boost_defensive_negative_stages[0]) if neg_boost_defensive_negative_stages else 0,
                "neg_boost_speed_negative_stage": int(neg_boost_speed_negative_stage[0]) if neg_boost_speed_negative_stage else 0,
                "neg_boost_severe_negative_boost": bool(neg_boost_severe_negative_boost[0]) if neg_boost_severe_negative_boost else False,
                "neg_boost_was_switch": bool(neg_boost_was_switch[0]) if neg_boost_was_switch else False,
                # Phase 6.4a: Corrected metric names (backward-compatible aliases)
                "final_unsafe_switch_selected": bool(unsafe_switch_candidate_selected[0]) if unsafe_switch_candidate_selected else False,
                "final_double_threat_switch_selected": bool(selected_switch_double_threat[0]) if selected_switch_double_threat else False,
                "legal_safer_joint_switch_available": bool(safer_switch_candidate_available[0]) if safer_switch_candidate_available else False,
                "unsafe_switch_avoided_by_type_safety": bool(switch_type_safety_avoided[0]) if switch_type_safety_avoided else False,
                "joint_switch_selection_changed_by_type_safety": bool(switch_type_safety_avoided[0]) if switch_type_safety_avoided else False,
                # Phase 6.4b: Negative-boost eligibility
                "negative_boost_decision_eligible": bool(neg_boost_decision_eligible[0]) if neg_boost_decision_eligible else False,
                "negative_boost_selected_action_kind": str(neg_boost_selected_action_kind[0]) if neg_boost_selected_action_kind else "",
                "negative_boost_legal_switch_count": int(neg_boost_legal_switch_count[0]) if neg_boost_legal_switch_count else 0,
                "negative_boost_best_switch_species": str(neg_boost_best_switch_species[0]) if neg_boost_best_switch_species else "",
                "negative_boost_best_switch_score": float(neg_boost_best_switch_score[0]) if neg_boost_best_switch_score else 0.0,
                "negative_boost_best_move_score": float(neg_boost_best_move_score[0]) if neg_boost_best_move_score else 0.0,
                "negative_boost_switch_score_gap": float(neg_boost_switch_score_gap[0]) if neg_boost_switch_score_gap else 0.0,
                "negative_boost_relevant_offensive_drop": bool(neg_boost_relevant_offensive_drop[0]) if neg_boost_relevant_offensive_drop else False,
                "negative_boost_defensive_drop": bool(neg_boost_defensive_drop[0]) if neg_boost_defensive_drop else False,
                "negative_boost_speed_drop": bool(neg_boost_speed_drop[0]) if neg_boost_speed_drop else False,
                # Phase 6.4.3: Stat-Drop Switch Diagnostics (slot 0)
                "severe_negative_boost_active": bool(severe_neg_boost_active[0]) if severe_neg_boost_active else False,
                "severe_negative_boost_categories": list(severe_neg_boost_categories[0]) if severe_neg_boost_categories else [],
                "severe_negative_boost_switch_available": bool(severe_neg_boost_switch_available[0]) if severe_neg_boost_switch_available else False,
                "severe_negative_boost_switched": bool(severe_neg_boost_switched[0]) if severe_neg_boost_switched else False,
                "severe_negative_boost_stayed": bool(severe_neg_boost_stayed[0]) if severe_neg_boost_stayed else False,
                "severe_negative_boost_stayed_productive": bool(severe_neg_boost_stayed_productive[0]) if severe_neg_boost_stayed_productive else False,
                "severe_negative_boost_stayed_unproductive": bool(severe_neg_boost_stayed_unproductive[0]) if severe_neg_boost_stayed_unproductive else False,
                "severe_negative_boost_only_legal_no_switch": bool(severe_neg_boost_only_legal_no_switch[0]) if severe_neg_boost_only_legal_no_switch else False,
                "severe_negative_boost_best_switch_candidate": str(severe_neg_boost_best_switch_candidate[0]) if severe_neg_boost_best_switch_candidate else "",
                "severe_negative_boost_selected_action": str(severe_neg_boost_selected_action[0]) if severe_neg_boost_selected_action else "",
                "severe_negative_boost_turn": int(severe_neg_boost_turn[0]) if severe_neg_boost_turn else 0,
                "severe_negative_boost_species": str(severe_neg_boost_species[0]) if severe_neg_boost_species else "",
                # Phase 6.4.7: Stat-drop switch scoring
                "stat_drop_switch_scoring_enabled": bool(stat_drop_switch_scoring_enabled[0]) if stat_drop_switch_scoring_enabled else False,
                "stat_drop_switch_pressure_active": bool(stat_drop_switch_pressure_active[0]) if stat_drop_switch_pressure_active else False,
                "stat_drop_switch_pressure_categories": list(stat_drop_switch_pressure_categories[0]) if stat_drop_switch_pressure_categories else [],
                "stat_drop_switch_pressure_score": float(stat_drop_switch_pressure_score[0]) if stat_drop_switch_pressure_score else 0.0,
                "stat_drop_switch_selected": bool(stat_drop_switch_selected[0]) if stat_drop_switch_selected else False,
                "stat_drop_switch_stayed": bool(stat_drop_switch_stayed[0]) if stat_drop_switch_stayed else False,
                "stat_drop_switch_stayed_productive": bool(stat_drop_switch_stayed_productive[0]) if stat_drop_switch_stayed_productive else False,
                "stat_drop_switch_stayed_unproductive": bool(stat_drop_switch_stayed_unproductive[0]) if stat_drop_switch_stayed_unproductive else False,
                "stat_drop_switch_selection_changed": bool(stat_drop_switch_selection_changed[0]) if stat_drop_switch_selection_changed else False,
                "stat_drop_switch_best_switch_species": str(stat_drop_switch_best_switch_species[0]) if stat_drop_switch_best_switch_species else "",
                "stat_drop_switch_best_switch_score": float(stat_drop_switch_best_switch_score[0]) if stat_drop_switch_best_switch_score else 0.0,
                "stat_drop_switch_best_non_switch_score": float(stat_drop_switch_best_non_switch_score[0]) if stat_drop_switch_best_non_switch_score else 0.0,
                "stat_drop_switch_reason": str(stat_drop_switch_reason[0]) if stat_drop_switch_reason else "",
                "stat_drop_switch_threshold_source": str(stat_drop_switch_threshold_source[0]) if stat_drop_switch_threshold_source else "",
                # Phase 6.3.6b: Known Ally Redirection
                "known_ally_redirection_selected": bool(known_ally_redirection_selected[0]) if known_ally_redirection_selected else False,
                "known_ally_redirection_reason": str(known_ally_redirection_reason[0]) if known_ally_redirection_reason else "",
                "known_ally_redirection_ally_species": str(known_ally_redirection_ally_species[0]) if known_ally_redirection_ally_species else "",
                "known_ally_redirection_ally_ability": str(known_ally_redirection_ally_ability[0]) if known_ally_redirection_ally_ability else "",
                "known_ally_redirection_move_id": str(known_ally_redirection_move_id[0]) if known_ally_redirection_move_id else "",
                "known_ally_redirection_known_before_decision": bool(known_ally_redirection_known_before_decision[0]) if known_ally_redirection_known_before_decision else False,
                "known_ally_redirection_candidate_blocked": bool(known_ally_redirection_candidate_blocked[0]) if known_ally_redirection_candidate_blocked else False,
                "known_ally_redirection_avoided": bool(known_ally_redirection_avoided[0]) if known_ally_redirection_avoided else False,
                "known_ally_redirection_only_legal": bool(known_ally_redirection_only_legal[0]) if known_ally_redirection_only_legal else False,
                "known_ally_redirection_repeat_selected": bool(known_ally_redirection_repeat_selected[0]) if known_ally_redirection_repeat_selected else False,
                "known_ally_redirection_safe_alternative_available": bool(known_ally_redirection_safe_alternative_available[0]) if known_ally_redirection_safe_alternative_available else False,
                "our_known_ally_redirection_error": bool(our_known_ally_redirection_error[0]) if our_known_ally_redirection_error else False,
                "opponent_known_ally_redirection_error": bool(opponent_known_ally_redirection_error[0]) if opponent_known_ally_redirection_error else False,
                # Phase 6.3.7: Dynamic move type
                "declared_move_type": str(declared_move_type[0]) if declared_move_type else "",
                "effective_move_type": str(effective_move_type[0]) if effective_move_type else "",
                "effective_move_type_source": str(effective_move_type_source[0]) if effective_move_type_source else "",
                "dynamic_move_type_applied": bool(dynamic_move_type_applied[0]) if dynamic_move_type_applied else False,
                "dynamic_move_type_form": str(dynamic_move_type_form[0]) if dynamic_move_type_form else "",
                # Phase 6.3.7f: Dynamic absorb candidate audit (slot 0)
                "dynamic_type_absorb_candidate_blocked": bool(dynamic_type_absorb_candidate_blocked[0]) if dynamic_type_absorb_candidate_blocked else False,
                "dynamic_type_absorb_selected": bool(dynamic_type_absorb_selected[0]) if dynamic_type_absorb_selected else False,
                "dynamic_type_absorb_avoided": bool(dynamic_type_absorb_avoided[0]) if dynamic_type_absorb_avoided else False,
                "dynamic_type_absorb_reason": str(dynamic_type_absorb_reason[0]) if dynamic_type_absorb_reason else "",
                "dynamic_type_absorb_target_species": str(dynamic_type_absorb_target_species[0]) if dynamic_type_absorb_target_species else "",
                "dynamic_type_absorb_target_ability": str(dynamic_type_absorb_target_ability[0]) if dynamic_type_absorb_target_ability else "",
                "dynamic_type_absorb_blocked_move_id": str(dynamic_type_absorb_blocked_move_id[0]) if dynamic_type_absorb_blocked_move_id else "",
                "dynamic_type_absorb_blocked_candidate_score": float(dynamic_type_absorb_blocked_candidate_score[0]) if dynamic_type_absorb_blocked_candidate_score else 0.0,
                "dynamic_type_absorb_candidate_available": bool(dynamic_type_absorb_candidate_available[0]) if dynamic_type_absorb_candidate_available else False,
                "dynamic_type_absorb_candidate_move_id": str(dynamic_type_absorb_candidate_move_id[0]) if dynamic_type_absorb_candidate_move_id else "",
                "dynamic_type_absorb_candidate_declared_type": str(dynamic_type_absorb_candidate_declared_type[0]) if dynamic_type_absorb_candidate_declared_type else "",
                "dynamic_type_absorb_candidate_effective_type": str(dynamic_type_absorb_candidate_effective_type[0]) if dynamic_type_absorb_candidate_effective_type else "",
                "dynamic_type_absorb_candidate_form": str(dynamic_type_absorb_candidate_form[0]) if dynamic_type_absorb_candidate_form else "",
                "dynamic_type_absorb_candidate_source": str(dynamic_type_absorb_candidate_source[0]) if dynamic_type_absorb_candidate_source else "",
                "dynamic_type_absorb_candidate_target_table": list(dynamic_type_absorb_candidate_target_table[0]) if (dynamic_type_absorb_candidate_target_table and dynamic_type_absorb_candidate_target_table[0]) else [],
                # Phase 6.3.6b.6: Blocked candidate metadata
                "known_ally_redirection_opportunity_observed": bool(known_ally_redirection_opportunity_observed[0]) if known_ally_redirection_opportunity_observed else False,
                "known_ally_redirection_blocked_candidate_move_id": str(known_ally_redirection_blocked_candidate_move_id[0]) if known_ally_redirection_blocked_candidate_move_id else "",
                "known_ally_redirection_blocked_candidate_attacker_species": str(known_ally_redirection_blocked_candidate_attacker_species[0]) if known_ally_redirection_blocked_candidate_attacker_species else "",
                "known_ally_redirection_blocked_candidate_target_species": str(known_ally_redirection_blocked_candidate_target_species[0]) if known_ally_redirection_blocked_candidate_target_species else "",
                "known_ally_redirection_blocked_candidate_ally_species": str(known_ally_redirection_blocked_candidate_ally_species[0]) if known_ally_redirection_blocked_candidate_ally_species else "",
                "known_ally_redirection_blocked_candidate_ally_ability": str(known_ally_redirection_blocked_candidate_ally_ability[0]) if known_ally_redirection_blocked_candidate_ally_ability else "",
                "known_ally_redirection_blocked_candidate_reason": str(known_ally_redirection_blocked_candidate_reason[0]) if known_ally_redirection_blocked_candidate_reason else "",
                "known_ally_redirection_blocked_candidate_known_before": bool(known_ally_redirection_blocked_candidate_known_before[0]) if known_ally_redirection_blocked_candidate_known_before else False,
                "known_ally_redirection_blocked_candidate_score": float(known_ally_redirection_blocked_candidate_score[0]) if known_ally_redirection_blocked_candidate_score else 0.0,
                "known_ally_redirection_best_safe_alternative": str(known_ally_redirection_best_safe_alternative[0]) if known_ally_redirection_best_safe_alternative else "",
                "known_ally_redirection_best_safe_alternative_score": float(known_ally_redirection_best_safe_alternative_score[0]) if known_ally_redirection_best_safe_alternative_score else 0.0,
                # Phase 6.4.2: Revealed-Move Switch Interception
                "revealed_switch_prediction_available": bool(revealed_switch_prediction_available[0]) if revealed_switch_prediction_available else False,
                "revealed_switch_interception_selected": bool(revealed_switch_interception_selected[0]) if revealed_switch_interception_selected else False,
                "revealed_switch_selection_changed": bool(revealed_switch_selection_changed[0]) if revealed_switch_selection_changed else False,
                "revealed_switch_threatening_opponent": str(revealed_switch_threatening_opponent[0]) if revealed_switch_threatening_opponent else "",
                "revealed_switch_threat_move_ids": list(revealed_switch_threat_move_ids[0]) if revealed_switch_threat_move_ids else [],
                "revealed_switch_threat_move_types": list(revealed_switch_threat_move_types[0]) if revealed_switch_threat_move_types else [],
                "revealed_switch_target_likelihood": list(revealed_switch_target_likelihood[0]) if revealed_switch_target_likelihood else [],
                "revealed_switch_active_risk": float(revealed_switch_active_risk[0]) if revealed_switch_active_risk else 0.0,
                "revealed_switch_candidate_risk": float(revealed_switch_candidate_risk[0]) if revealed_switch_candidate_risk else 0.0,
                "revealed_switch_risk_reduction": float(revealed_switch_risk_reduction[0]) if revealed_switch_risk_reduction else 0.0,
                "revealed_switch_candidate_species": str(revealed_switch_candidate_species[0]) if revealed_switch_candidate_species else "",
                "revealed_switch_candidate_types": str(revealed_switch_candidate_types[0]) if revealed_switch_candidate_types else "",
                "revealed_switch_candidate_hp": float(revealed_switch_candidate_hp[0]) if revealed_switch_candidate_hp else 1.0,
                "revealed_switch_bonus_applied": float(revealed_switch_bonus_applied[0]) if revealed_switch_bonus_applied else 0.0,
                "revealed_switch_blocked_by_ko_action": bool(revealed_switch_blocked_by_ko_action[0]) if revealed_switch_blocked_by_ko_action else False,
                "revealed_switch_blocked_by_high_value_action": bool(revealed_switch_blocked_by_high_value_action[0]) if revealed_switch_blocked_by_high_value_action else False,
                "revealed_switch_rejected_worse_other_threat": bool(revealed_switch_rejected_worse_other_threat[0]) if revealed_switch_rejected_worse_other_threat else False,
                "revealed_switch_post_turn_damage_taken": (float(revealed_switch_post_turn_damage_taken[0]) if revealed_switch_post_turn_damage_taken and revealed_switch_post_turn_damage_taken[0] is not None else None),
                "revealed_switch_post_turn_survived": (bool(revealed_switch_post_turn_survived[0]) if revealed_switch_post_turn_survived and revealed_switch_post_turn_survived[0] is not None else None),
                "revealed_switch_predicted_move_used": str(revealed_switch_predicted_move_used[0]) if revealed_switch_predicted_move_used else "",
                "revealed_switch_prediction_correct": bool(revealed_switch_prediction_correct[0]) if revealed_switch_prediction_correct else False,
                "revealed_switch_prediction_wrong": bool(revealed_switch_prediction_wrong[0]) if revealed_switch_prediction_wrong else False,
                # Phase 6.4.2: Type-immune audit fields (our actions only)
                "our_type_immune_move_selected": bool(our_type_immune_move_selected[0]) if our_type_immune_move_selected else False,
                "our_type_immune_only_legal": bool(our_type_immune_only_legal[0]) if our_type_immune_only_legal else False,
                "our_type_immune_move_avoided": bool(our_type_immune_move_avoided[0]) if our_type_immune_move_avoided else False,
                "our_type_immune_attacker": str(our_type_immune_attacker[0]) if our_type_immune_attacker else "",
                "our_type_immune_move": str(our_type_immune_move[0]) if our_type_immune_move else "",
                "our_type_immune_target": str(our_type_immune_target[0]) if our_type_immune_target else "",
                "our_type_immune_target_types": str(our_type_immune_target_types[0]) if our_type_immune_target_types else "",
                "our_type_immune_reason": str(our_type_immune_reason[0]) if our_type_immune_reason else "",
                # Phase 6.3.5: Ground-into-Flying audit fields
                "ground_into_flying_selected": bool(ground_into_flying_selected[0]) if ground_into_flying_selected else False,
                "ground_into_secondary_flying_selected": bool(ground_into_secondary_flying_selected[0]) if ground_into_secondary_flying_selected else False,
                "ground_into_flying_avoided": bool(ground_into_flying_avoided[0]) if ground_into_flying_avoided else False,
                "ground_into_flying_only_legal": bool(ground_into_flying_only_legal[0]) if ground_into_flying_only_legal else False,
                "ground_flying_exception_applied": bool(ground_flying_exception_applied[0]) if ground_flying_exception_applied else False,
                "ground_flying_exception_reason": str(ground_flying_exception_reason[0]) if ground_flying_exception_reason else "",
                "ground_flying_target_primary_type": str(ground_flying_target_primary_type[0]) if ground_flying_target_primary_type else "",
                "ground_flying_target_secondary_type": str(ground_flying_target_secondary_type[0]) if ground_flying_target_secondary_type else "",
                # Phase 6.3.5: Singleton ability safety fields
                "known_ability_resolution_source": str(known_ability_resolution_source[0]) if known_ability_resolution_source else "",
                "deterministic_singleton_ability_used": bool(deterministic_singleton_ability_used[0]) if deterministic_singleton_ability_used else False,
                "deterministic_singleton_ability": str(deterministic_singleton_ability[0]) if deterministic_singleton_ability else "",
                "deterministic_singleton_target_species": str(deterministic_singleton_target_species[0]) if deterministic_singleton_target_species else "",
                "singleton_ability_hard_block_avoided": bool(singleton_ability_hard_block_avoided[0]) if singleton_ability_hard_block_avoided else False,
                "singleton_ground_into_levitate_selected": bool(singleton_ground_into_levitate_selected[0]) if singleton_ground_into_levitate_selected else False,
                "singleton_ability_conflict_detected": bool(singleton_ability_conflict_detected[0]) if singleton_ability_conflict_detected else False,
                "singleton_ability_suppressed": bool(singleton_ability_suppressed[0]) if singleton_ability_suppressed else False,
                "singleton_ability_suppression_reason": str(singleton_ability_suppression_reason[0]) if singleton_ability_suppression_reason else "",
                "singleton_only_legal_action": bool(singleton_only_legal_action[0]) if singleton_only_legal_action else False,
                "singleton_levitate_opportunity_observed": bool(singleton_levitate_opportunity_observed[0]) if singleton_levitate_opportunity_observed else False,
                "singleton_ground_into_levitate_selected_observed": bool(singleton_ground_into_levitate_selected_observed[0]) if singleton_ground_into_levitate_selected_observed else False,
                "singleton_hard_block_applied": bool(singleton_hard_block_applied[0]) if singleton_hard_block_applied else False,
                "singleton_blocked_candidate_observed": bool(singleton_blocked_candidate_observed[0]) if singleton_blocked_candidate_observed else False,
                "singleton_selection_changed_by_safety": bool(singleton_selection_changed_by_safety[0]) if singleton_selection_changed_by_safety else False,
                "singleton_resolution_source": str(singleton_resolution_source[0]) if singleton_resolution_source else "",
                # Phase 6.3.5a: Priority blocking fields
                "priority_move_field_blocked": bool(priority_move_field_blocked[0]) if priority_move_field_blocked else False,
                "priority_move_block_reason": str(priority_move_block_reason[0]) if priority_move_block_reason else "",
                "priority_move_selected_into_psychic_terrain": bool(priority_move_selected_into_psychic_terrain[0]) if priority_move_selected_into_psychic_terrain else False,
                "sucker_punch_selected_into_psychic_terrain": bool(sucker_punch_selected_into_psychic_terrain[0]) if sucker_punch_selected_into_psychic_terrain else False,
                "priority_move_block_avoided": bool(priority_move_block_avoided[0]) if priority_move_block_avoided else False,
                "priority_move_only_legal": bool(priority_move_only_legal[0]) if priority_move_only_legal else False,
                "priority_target_grounded": bool(priority_target_grounded[0]) if priority_target_grounded else False,
                "priority_target_species": str(priority_target_species[0]) if priority_target_species else "",
                "priority_target_type_1": str(priority_target_type_1[0]) if priority_target_type_1 else "",
                "priority_target_type_2": str(priority_target_type_2[0]) if priority_target_type_2 else "",
                "priority_blocking_ability": str(priority_blocking_ability[0]) if priority_blocking_ability else "",
                "priority_blocking_ability_source": str(priority_blocking_ability_source[0]) if priority_blocking_ability_source else "",
            },
            "slot_1": {
                "action": str(slot_actions[1]) if slot_actions[1] else None,
                "move_type": move_type_1,
                "action_types": slot_action_types[1],
                "selected_score": score_1,
                "expected_damage": float(expected_damages[1]) if expected_damages[1] is not None else None,
                "expected_ko": bool(expected_kos[1]) if expected_kos[1] is not None else None,
                "target_hp_before": float(target_hps[1]) if target_hps[1] is not None else None,
                "target_species": target_species[1],
                "spread_available": bool(spread_available[1]),
                "best_spread_score": float(best_spread_score[1]) if best_spread_score[1] is not None else None,
                "best_ko_score": float(best_ko_score[1]) if best_ko_score[1] is not None else None,
                "zero_effectiveness_move_selected": bool(zero_effectiveness_1),
                "all_targets_immune_spread_selected": bool(all_targets_immune_1),
                "all_target_immune_spread_avoided": bool(all_target_immune_avoided[1]) if all_target_immune_avoided else False,
                "all_target_immune_spread_only_legal": bool(all_target_immune_only_legal[1]) if all_target_immune_only_legal else False,
                "all_target_immune_spread_joint_penalized": bool(all_target_immune_penalized[1]) if all_target_immune_penalized else False,
                "self_drop_spam_candidate": bool(self_drop_candidate_1),
                "self_drop_move_spam": False,
                "outcome_known": False,
                "actual_ko": None,
                "actual_damage": None,
                "target_used_protect": None,
                "our_mon_fainted": None,
                "fainted_before_moving": None,
                "partial_immune_spread_selected": bool(partial_immune_spread_selected[1]) if partial_immune_spread_selected else False,
                "partial_ability_immune_spread_selected": bool(partial_ability_immune_spread_selected[1]) if partial_ability_immune_spread_selected else False,
                "efficient_partial_spread_selected": bool(efficient_partial_spread_selected[1]) if efficient_partial_spread_selected else False,
                "inefficient_partial_spread_selected": bool(inefficient_partial_spread_selected[1]) if inefficient_partial_spread_selected else False,
                "immune_target_species": list(immune_target_species[1]) if (immune_target_species and immune_target_species[1]) else [],
                "damaged_target_species": list(damaged_target_species[1]) if (damaged_target_species and damaged_target_species[1]) else [],
                "best_single_target_alternative": str(best_single_target_alternative[1]) if (best_single_target_alternative and best_single_target_alternative[1]) else "",
                "speed_priority_threatened": bool(speed_priority_threatened[1]) if (speed_priority_threatened and len(speed_priority_threatened) > 1) else False,
                "faster_opponents": list(faster_opponents[1]) if (faster_opponents and len(faster_opponents) > 1 and faster_opponents[1]) else [],
                "priority_opponents": list(priority_opponents[1]) if (priority_opponents and len(priority_opponents) > 1 and priority_opponents[1]) else [],
                "speed_priority_protect_bonus_applied": bool(speed_priority_protect_bonus_applied[1]) if (speed_priority_protect_bonus_applied and len(speed_priority_protect_bonus_applied) > 1) else False,
                "speed_priority_attack_penalty_applied": bool(speed_priority_attack_penalty_applied[1]) if (speed_priority_attack_penalty_applied and len(speed_priority_attack_penalty_applied) > 1) else False,
                "speed_priority_switch_bonus_applied": bool(speed_priority_switch_bonus_applied[1]) if (speed_priority_switch_bonus_applied and len(speed_priority_switch_bonus_applied) > 1) else False,
                "expected_to_faint_before_moving": bool(expected_to_faint_before_moving[1]) if (expected_to_faint_before_moving and len(expected_to_faint_before_moving) > 1) else False,
                "protected_due_to_speed_priority": bool(protected_due_to_speed_priority[1]) if (protected_due_to_speed_priority and len(protected_due_to_speed_priority) > 1) else False,
                "protect_like_available": bool(protect_like_available[1]) if (protect_like_available and len(protect_like_available) > 1) else False,
                "switch_available": bool(switch_available[1]) if (switch_available and len(switch_available) > 1) else False,
                "only_conditional_priority": bool(only_conditional_priority[1]) if (only_conditional_priority and len(only_conditional_priority) > 1) else False,
                "stalling_field_condition": bool(stalling_field_condition[1]) if (stalling_field_condition and len(stalling_field_condition) > 1) else False,
                "ability_hard_block_avoided": bool(ability_hard_block_avoided[1]) if (ability_hard_block_avoided and len(ability_hard_block_avoided) > 1) else False,
                "ability_immune_move_selected": bool(ability_immune_move_selected[1]) if (ability_immune_move_selected and len(ability_immune_move_selected) > 1) else False,
                "our_bot_ability_error": bool(ability_immune_move_selected[1]) if (ability_immune_move_selected and len(ability_immune_move_selected) > 1) else False,
                "ground_into_levitate_selected": bool(ground_into_levitate_selected[1]) if (ground_into_levitate_selected and len(ground_into_levitate_selected) > 1) else False,
                "ability_block_reason": str(ability_block_reason[1]) if (ability_block_reason and len(ability_block_reason) > 1) else "",
                "ability_blocked_target_species": str(ability_blocked_target_species[1]) if (ability_blocked_target_species and len(ability_blocked_target_species) > 1) else "",
                "ability_blocked_target_ability": str(ability_blocked_target_ability[1]) if (ability_blocked_target_ability and len(ability_blocked_target_ability) > 1) else "",
                "ally_ability_safe_spread": bool(ally_ability_safe_spread[1]) if (ally_ability_safe_spread and len(ally_ability_safe_spread) > 1) else False,
                "ability_redirection_avoided": bool(ability_redirection_avoided[1]) if (ability_redirection_avoided and len(ability_redirection_avoided) > 1) else False,
                "absorb_immune_move_selected": bool(absorb_immune_move_selected[1]) if absorb_immune_move_selected else False,
                "absorb_selection_forced": bool(absorb_selection_forced[1]) if absorb_selection_forced else False,
                "absorb_safe_alternative_available": bool(absorb_safe_alternative_available[1]) if absorb_safe_alternative_available else False,
                "absorb_best_safe_alternative_move": str(absorb_best_safe_alternative_move[1]) if absorb_best_safe_alternative_move else "",
                "absorb_best_safe_alternative_target": str(absorb_best_safe_alternative_target[1]) if absorb_best_safe_alternative_target else "",
                "absorb_best_safe_alternative_score": float(absorb_best_safe_alternative_score[1]) if absorb_best_safe_alternative_score else 0.0,
                "absorb_selected_score": float(absorb_selected_score[1]) if absorb_selected_score else 0.0,
                "absorb_selected_streak": int(absorb_selected_streak[1]) if absorb_selected_streak else 0,
                "avoidable_absorb_error": bool(avoidable_absorb_error[1]) if avoidable_absorb_error else False,
                "productive_partial_absorb_spread": bool(productive_partial_absorb_spread[1]) if productive_partial_absorb_spread else False,
                "absorb_error_reason": str(absorb_error_reason[1]) if absorb_error_reason else "",
                "absorb_via_redirection": bool(absorb_via_redirection[1]) if absorb_via_redirection else False,
                "absorb_intended_target_species": str(absorb_intended_target_species[1]) if absorb_intended_target_species else "",
                "absorb_intended_target_ability": str(absorb_intended_target_ability[1]) if absorb_intended_target_ability else "",
                "absorb_effective_target_species": str(absorb_effective_target_species[1]) if absorb_effective_target_species else "",
                "absorb_effective_target_ability": str(absorb_effective_target_ability[1]) if absorb_effective_target_ability else "",
                "absorb_selected_move_id": str(absorb_selected_move_id[1]) if absorb_selected_move_id else "",
                "direct_absorb_hard_block_avoided": bool(direct_absorb_hard_block_avoided[1]) if direct_absorb_hard_block_avoided else False,
                "direct_absorb_immune_move_selected": bool(direct_absorb_immune_move_selected[1]) if direct_absorb_immune_move_selected else False,
                "direct_absorb_block_reason": str(direct_absorb_block_reason[1]) if direct_absorb_block_reason else "",
                "direct_absorb_target_species": str(direct_absorb_target_species[1]) if direct_absorb_target_species else "",
                "direct_absorb_target_ability": str(direct_absorb_target_ability[1]) if direct_absorb_target_ability else "",
                "direct_absorb_only_legal_action": bool(direct_absorb_only_legal_action[1]) if direct_absorb_only_legal_action else False,
                # Phase 6.3.6: Known Absorb Hard Safety
                "direct_known_absorb_repeat_selected": bool(direct_known_absorb_repeat_selected[1]) if direct_known_absorb_repeat_selected else False,
                # Phase 6.4: Switch Candidate Safety
                "forced_switch": bool(forced_switch[1]) if forced_switch else False,
                "switch_candidate_type_safety_applied": bool(switch_candidate_type_safety_applied[1]) if switch_candidate_type_safety_applied else False,
                "selected_switch_species": str(selected_switch_species[1]) if selected_switch_species else "",
                "selected_switch_types": str(selected_switch_types[1]) if selected_switch_types else "",
                "selected_switch_hp_fraction": float(selected_switch_hp_fraction[1]) if selected_switch_hp_fraction else 1.0,
                "selected_switch_raw_safety_score": float(selected_switch_raw_safety_score[1]) if selected_switch_raw_safety_score else 0.0,
                "selected_switch_relative_adjustment": float(selected_switch_relative_adjustment[1]) if selected_switch_relative_adjustment else 0.0,
                "selected_switch_worst_multiplier": float(selected_switch_worst_multiplier[1]) if selected_switch_worst_multiplier else 1.0,
                "selected_switch_double_threat": bool(selected_switch_double_threat[1]) if selected_switch_double_threat else False,
                "unsafe_switch_candidate_selected": bool(unsafe_switch_candidate_selected[1]) if unsafe_switch_candidate_selected else False,
                "safer_switch_candidate_available": bool(safer_switch_candidate_available[1]) if safer_switch_candidate_available else False,
                "best_safe_switch_species": str(best_safe_switch_species[1]) if best_safe_switch_species else "",
                "best_safe_switch_score": float(best_safe_switch_score[1]) if best_safe_switch_score else 0.0,
                "switch_type_safety_avoided": bool(switch_type_safety_avoided[1]) if switch_type_safety_avoided else False,
                # Phase 6.4.3a.2: Forced switch diagnostics (slot 1)
                "forced_switch_candidate_count": int(forced_switch_candidate_count[1]) if forced_switch_candidate_count else 0,
                "forced_switch_selected_index": int(forced_switch_selected_index[1]) if forced_switch_selected_index else -1,
                "forced_switch_selected_species": str(forced_switch_selected_species[1]) if forced_switch_selected_species else "",
                "forced_switch_best_safety_species": str(forced_switch_best_safety_species[1]) if forced_switch_best_safety_species else "",
                "forced_switch_selected_safety_score": float(forced_switch_selected_safety_score[1]) if forced_switch_selected_safety_score else 0.0,
                "forced_switch_best_safety_score": float(forced_switch_best_safety_score[1]) if forced_switch_best_safety_score else 0.0,
                "forced_switch_order_fallback_used": bool(forced_switch_order_fallback_used[1]) if forced_switch_order_fallback_used else False,
                # Phase 6.4.4: Forced switch replacement safety (slot 1)
                "forced_switch_safety_enabled": bool(forced_switch_safety_enabled[1]) if forced_switch_safety_enabled else False,
                "forced_switch_safety_selection_changed": bool(forced_switch_safety_selection_changed[1]) if forced_switch_safety_selection_changed else False,
                "forced_switch_selected_double_threat": bool(forced_switch_selected_double_threat[1]) if forced_switch_selected_double_threat else False,
                "forced_switch_best_avoids_double_threat": bool(forced_switch_best_avoids_double_threat[1]) if forced_switch_best_avoids_double_threat else False,
                "forced_switch_selected_quad_weak": bool(forced_switch_selected_quad_weak[1]) if forced_switch_selected_quad_weak else False,
                "forced_switch_best_avoids_quad_weak": bool(forced_switch_best_avoids_quad_weak[1]) if forced_switch_best_avoids_quad_weak else False,
                "forced_switch_selected_low_hp": bool(forced_switch_selected_low_hp[1]) if forced_switch_selected_low_hp else False,
                "forced_switch_reason": str(forced_switch_reason[1]) if forced_switch_reason else "",
                "forced_switch_candidate_safety_table": forced_switch_candidate_safety_table[1] if forced_switch_candidate_safety_table else None,
                # Phase 6.4: Negative Boost Diagnostics
                "neg_boost_total_negative_stages": int(neg_boost_total_negative_stages[1]) if neg_boost_total_negative_stages else 0,
                "neg_boost_lowest_stage": int(neg_boost_lowest_stage[1]) if neg_boost_lowest_stage else 0,
                "neg_boost_offensive_negative_stages": int(neg_boost_offensive_negative_stages[1]) if neg_boost_offensive_negative_stages else 0,
                "neg_boost_defensive_negative_stages": int(neg_boost_defensive_negative_stages[1]) if neg_boost_defensive_negative_stages else 0,
                "neg_boost_speed_negative_stage": int(neg_boost_speed_negative_stage[1]) if neg_boost_speed_negative_stage else 0,
                "neg_boost_severe_negative_boost": bool(neg_boost_severe_negative_boost[1]) if neg_boost_severe_negative_boost else False,
                "neg_boost_was_switch": bool(neg_boost_was_switch[1]) if neg_boost_was_switch else False,
                # Phase 6.4a: Corrected metric names (backward-compatible aliases)
                "final_unsafe_switch_selected": bool(unsafe_switch_candidate_selected[1]) if unsafe_switch_candidate_selected else False,
                "final_double_threat_switch_selected": bool(selected_switch_double_threat[1]) if selected_switch_double_threat else False,
                "legal_safer_joint_switch_available": bool(safer_switch_candidate_available[1]) if safer_switch_candidate_available else False,
                "unsafe_switch_avoided_by_type_safety": bool(switch_type_safety_avoided[1]) if switch_type_safety_avoided else False,
                "joint_switch_selection_changed_by_type_safety": bool(switch_type_safety_avoided[1]) if switch_type_safety_avoided else False,
                # Phase 6.4b: Negative-boost eligibility
                "negative_boost_decision_eligible": bool(neg_boost_decision_eligible[1]) if neg_boost_decision_eligible else False,
                "negative_boost_selected_action_kind": str(neg_boost_selected_action_kind[1]) if neg_boost_selected_action_kind else "",
                "negative_boost_legal_switch_count": int(neg_boost_legal_switch_count[1]) if neg_boost_legal_switch_count else 0,
                "negative_boost_best_switch_species": str(neg_boost_best_switch_species[1]) if neg_boost_best_switch_species else "",
                "negative_boost_best_switch_score": float(neg_boost_best_switch_score[1]) if neg_boost_best_switch_score else 0.0,
                "negative_boost_best_move_score": float(neg_boost_best_move_score[1]) if neg_boost_best_move_score else 0.0,
                "negative_boost_switch_score_gap": float(neg_boost_switch_score_gap[1]) if neg_boost_switch_score_gap else 0.0,
                "negative_boost_relevant_offensive_drop": bool(neg_boost_relevant_offensive_drop[1]) if neg_boost_relevant_offensive_drop else False,
                "negative_boost_defensive_drop": bool(neg_boost_defensive_drop[1]) if neg_boost_defensive_drop else False,
                "negative_boost_speed_drop": bool(neg_boost_speed_drop[1]) if neg_boost_speed_drop else False,
                # Phase 6.4.3: Stat-Drop Switch Diagnostics (slot 1)
                "severe_negative_boost_active": bool(severe_neg_boost_active[1]) if severe_neg_boost_active else False,
                "severe_negative_boost_categories": list(severe_neg_boost_categories[1]) if severe_neg_boost_categories else [],
                "severe_negative_boost_switch_available": bool(severe_neg_boost_switch_available[1]) if severe_neg_boost_switch_available else False,
                "severe_negative_boost_switched": bool(severe_neg_boost_switched[1]) if severe_neg_boost_switched else False,
                "severe_negative_boost_stayed": bool(severe_neg_boost_stayed[1]) if severe_neg_boost_stayed else False,
                "severe_negative_boost_stayed_productive": bool(severe_neg_boost_stayed_productive[1]) if severe_neg_boost_stayed_productive else False,
                "severe_negative_boost_stayed_unproductive": bool(severe_neg_boost_stayed_unproductive[1]) if severe_neg_boost_stayed_unproductive else False,
                "severe_negative_boost_only_legal_no_switch": bool(severe_neg_boost_only_legal_no_switch[1]) if severe_neg_boost_only_legal_no_switch else False,
                "severe_negative_boost_best_switch_candidate": str(severe_neg_boost_best_switch_candidate[1]) if severe_neg_boost_best_switch_candidate else "",
                "severe_negative_boost_selected_action": str(severe_neg_boost_selected_action[1]) if severe_neg_boost_selected_action else "",
                "severe_negative_boost_turn": int(severe_neg_boost_turn[1]) if severe_neg_boost_turn else 0,
                "severe_negative_boost_species": str(severe_neg_boost_species[1]) if severe_neg_boost_species else "",
                # Phase 6.4.7: Stat-drop switch scoring
                "stat_drop_switch_scoring_enabled": bool(stat_drop_switch_scoring_enabled[1]) if stat_drop_switch_scoring_enabled else False,
                "stat_drop_switch_pressure_active": bool(stat_drop_switch_pressure_active[1]) if stat_drop_switch_pressure_active else False,
                "stat_drop_switch_pressure_categories": list(stat_drop_switch_pressure_categories[1]) if stat_drop_switch_pressure_categories else [],
                "stat_drop_switch_pressure_score": float(stat_drop_switch_pressure_score[1]) if stat_drop_switch_pressure_score else 0.0,
                "stat_drop_switch_selected": bool(stat_drop_switch_selected[1]) if stat_drop_switch_selected else False,
                "stat_drop_switch_stayed": bool(stat_drop_switch_stayed[1]) if stat_drop_switch_stayed else False,
                "stat_drop_switch_stayed_productive": bool(stat_drop_switch_stayed_productive[1]) if stat_drop_switch_stayed_productive else False,
                "stat_drop_switch_stayed_unproductive": bool(stat_drop_switch_stayed_unproductive[1]) if stat_drop_switch_stayed_unproductive else False,
                "stat_drop_switch_selection_changed": bool(stat_drop_switch_selection_changed[1]) if stat_drop_switch_selection_changed else False,
                "stat_drop_switch_best_switch_species": str(stat_drop_switch_best_switch_species[1]) if stat_drop_switch_best_switch_species else "",
                "stat_drop_switch_best_switch_score": float(stat_drop_switch_best_switch_score[1]) if stat_drop_switch_best_switch_score else 0.0,
                "stat_drop_switch_best_non_switch_score": float(stat_drop_switch_best_non_switch_score[1]) if stat_drop_switch_best_non_switch_score else 0.0,
                "stat_drop_switch_reason": str(stat_drop_switch_reason[1]) if stat_drop_switch_reason else "",
                "stat_drop_switch_threshold_source": str(stat_drop_switch_threshold_source[1]) if stat_drop_switch_threshold_source else "",
                # Phase 6.3.6b: Known Ally Redirection
                "known_ally_redirection_selected": bool(known_ally_redirection_selected[1]) if known_ally_redirection_selected else False,
                "known_ally_redirection_reason": str(known_ally_redirection_reason[1]) if known_ally_redirection_reason else "",
                "known_ally_redirection_ally_species": str(known_ally_redirection_ally_species[1]) if known_ally_redirection_ally_species else "",
                "known_ally_redirection_ally_ability": str(known_ally_redirection_ally_ability[1]) if known_ally_redirection_ally_ability else "",
                "known_ally_redirection_move_id": str(known_ally_redirection_move_id[1]) if known_ally_redirection_move_id else "",
                "known_ally_redirection_known_before_decision": bool(known_ally_redirection_known_before_decision[1]) if known_ally_redirection_known_before_decision else False,
                "known_ally_redirection_candidate_blocked": bool(known_ally_redirection_candidate_blocked[1]) if known_ally_redirection_candidate_blocked else False,
                "known_ally_redirection_avoided": bool(known_ally_redirection_avoided[1]) if known_ally_redirection_avoided else False,
                "known_ally_redirection_only_legal": bool(known_ally_redirection_only_legal[1]) if known_ally_redirection_only_legal else False,
                "known_ally_redirection_repeat_selected": bool(known_ally_redirection_repeat_selected[1]) if known_ally_redirection_repeat_selected else False,
                "known_ally_redirection_safe_alternative_available": bool(known_ally_redirection_safe_alternative_available[1]) if known_ally_redirection_safe_alternative_available else False,
                "our_known_ally_redirection_error": bool(our_known_ally_redirection_error[1]) if our_known_ally_redirection_error else False,
                "opponent_known_ally_redirection_error": bool(opponent_known_ally_redirection_error[1]) if opponent_known_ally_redirection_error else False,
                # Phase 6.3.7: Dynamic move type
                "declared_move_type": str(declared_move_type[1]) if declared_move_type else "",
                "effective_move_type": str(effective_move_type[1]) if effective_move_type else "",
                "effective_move_type_source": str(effective_move_type_source[1]) if effective_move_type_source else "",
                "dynamic_move_type_applied": bool(dynamic_move_type_applied[1]) if dynamic_move_type_applied else False,
                "dynamic_move_type_form": str(dynamic_move_type_form[1]) if dynamic_move_type_form else "",
                # Phase 6.3.7f: Dynamic absorb candidate audit (slot 1)
                # Slot-1 guard: require len(value) > 1 to read [1]. Truthiness alone
                # is insufficient because a one-element list would raise IndexError.
                "dynamic_type_absorb_candidate_blocked": bool(dynamic_type_absorb_candidate_blocked[1]) if (dynamic_type_absorb_candidate_blocked is not None and len(dynamic_type_absorb_candidate_blocked) > 1) else False,
                "dynamic_type_absorb_selected": bool(dynamic_type_absorb_selected[1]) if (dynamic_type_absorb_selected is not None and len(dynamic_type_absorb_selected) > 1) else False,
                "dynamic_type_absorb_avoided": bool(dynamic_type_absorb_avoided[1]) if (dynamic_type_absorb_avoided is not None and len(dynamic_type_absorb_avoided) > 1) else False,
                "dynamic_type_absorb_reason": str(dynamic_type_absorb_reason[1]) if (dynamic_type_absorb_reason is not None and len(dynamic_type_absorb_reason) > 1) else "",
                "dynamic_type_absorb_target_species": str(dynamic_type_absorb_target_species[1]) if (dynamic_type_absorb_target_species is not None and len(dynamic_type_absorb_target_species) > 1) else "",
                "dynamic_type_absorb_target_ability": str(dynamic_type_absorb_target_ability[1]) if (dynamic_type_absorb_target_ability is not None and len(dynamic_type_absorb_target_ability) > 1) else "",
                "dynamic_type_absorb_blocked_move_id": str(dynamic_type_absorb_blocked_move_id[1]) if (dynamic_type_absorb_blocked_move_id is not None and len(dynamic_type_absorb_blocked_move_id) > 1) else "",
                "dynamic_type_absorb_blocked_candidate_score": float(dynamic_type_absorb_blocked_candidate_score[1]) if (dynamic_type_absorb_blocked_candidate_score is not None and len(dynamic_type_absorb_blocked_candidate_score) > 1) else 0.0,
                "dynamic_type_absorb_candidate_available": bool(dynamic_type_absorb_candidate_available[1]) if (dynamic_type_absorb_candidate_available is not None and len(dynamic_type_absorb_candidate_available) > 1) else False,
                "dynamic_type_absorb_candidate_move_id": str(dynamic_type_absorb_candidate_move_id[1]) if (dynamic_type_absorb_candidate_move_id is not None and len(dynamic_type_absorb_candidate_move_id) > 1) else "",
                "dynamic_type_absorb_candidate_declared_type": str(dynamic_type_absorb_candidate_declared_type[1]) if (dynamic_type_absorb_candidate_declared_type is not None and len(dynamic_type_absorb_candidate_declared_type) > 1) else "",
                "dynamic_type_absorb_candidate_effective_type": str(dynamic_type_absorb_candidate_effective_type[1]) if (dynamic_type_absorb_candidate_effective_type is not None and len(dynamic_type_absorb_candidate_effective_type) > 1) else "",
                "dynamic_type_absorb_candidate_form": str(dynamic_type_absorb_candidate_form[1]) if (dynamic_type_absorb_candidate_form is not None and len(dynamic_type_absorb_candidate_form) > 1) else "",
                "dynamic_type_absorb_candidate_source": str(dynamic_type_absorb_candidate_source[1]) if (dynamic_type_absorb_candidate_source is not None and len(dynamic_type_absorb_candidate_source) > 1) else "",
                "dynamic_type_absorb_candidate_target_table": list(dynamic_type_absorb_candidate_target_table[1]) if (dynamic_type_absorb_candidate_target_table is not None and len(dynamic_type_absorb_candidate_target_table) > 1 and dynamic_type_absorb_candidate_target_table[1]) else [],
                # Phase 6.3.6b.6: Blocked candidate metadata
                "known_ally_redirection_opportunity_observed": bool(known_ally_redirection_opportunity_observed[1]) if known_ally_redirection_opportunity_observed else False,
                "known_ally_redirection_blocked_candidate_move_id": str(known_ally_redirection_blocked_candidate_move_id[1]) if known_ally_redirection_blocked_candidate_move_id else "",
                "known_ally_redirection_blocked_candidate_attacker_species": str(known_ally_redirection_blocked_candidate_attacker_species[1]) if known_ally_redirection_blocked_candidate_attacker_species else "",
                "known_ally_redirection_blocked_candidate_target_species": str(known_ally_redirection_blocked_candidate_target_species[1]) if known_ally_redirection_blocked_candidate_target_species else "",
                "known_ally_redirection_blocked_candidate_ally_species": str(known_ally_redirection_blocked_candidate_ally_species[1]) if known_ally_redirection_blocked_candidate_ally_species else "",
                "known_ally_redirection_blocked_candidate_ally_ability": str(known_ally_redirection_blocked_candidate_ally_ability[1]) if known_ally_redirection_blocked_candidate_ally_ability else "",
                "known_ally_redirection_blocked_candidate_reason": str(known_ally_redirection_blocked_candidate_reason[1]) if known_ally_redirection_blocked_candidate_reason else "",
                "known_ally_redirection_blocked_candidate_known_before": bool(known_ally_redirection_blocked_candidate_known_before[1]) if known_ally_redirection_blocked_candidate_known_before else False,
                "known_ally_redirection_blocked_candidate_score": float(known_ally_redirection_blocked_candidate_score[1]) if known_ally_redirection_blocked_candidate_score else 0.0,
                "known_ally_redirection_best_safe_alternative": str(known_ally_redirection_best_safe_alternative[1]) if known_ally_redirection_best_safe_alternative else "",
                "known_ally_redirection_best_safe_alternative_score": float(known_ally_redirection_best_safe_alternative_score[1]) if known_ally_redirection_best_safe_alternative_score else 0.0,
                # Phase 6.4.2: Revealed-Move Switch Interception
                "revealed_switch_prediction_available": bool(revealed_switch_prediction_available[1]) if revealed_switch_prediction_available else False,
                "revealed_switch_interception_selected": bool(revealed_switch_interception_selected[1]) if revealed_switch_interception_selected else False,
                "revealed_switch_selection_changed": bool(revealed_switch_selection_changed[1]) if revealed_switch_selection_changed else False,
                "revealed_switch_threatening_opponent": str(revealed_switch_threatening_opponent[1]) if revealed_switch_threatening_opponent else "",
                "revealed_switch_threat_move_ids": list(revealed_switch_threat_move_ids[1]) if revealed_switch_threat_move_ids else [],
                "revealed_switch_threat_move_types": list(revealed_switch_threat_move_types[1]) if revealed_switch_threat_move_types else [],
                "revealed_switch_target_likelihood": list(revealed_switch_target_likelihood[1]) if revealed_switch_target_likelihood else [],
                "revealed_switch_active_risk": float(revealed_switch_active_risk[1]) if revealed_switch_active_risk else 0.0,
                "revealed_switch_candidate_risk": float(revealed_switch_candidate_risk[1]) if revealed_switch_candidate_risk else 0.0,
                "revealed_switch_risk_reduction": float(revealed_switch_risk_reduction[1]) if revealed_switch_risk_reduction else 0.0,
                "revealed_switch_candidate_species": str(revealed_switch_candidate_species[1]) if revealed_switch_candidate_species else "",
                "revealed_switch_candidate_types": str(revealed_switch_candidate_types[1]) if revealed_switch_candidate_types else "",
                "revealed_switch_candidate_hp": float(revealed_switch_candidate_hp[1]) if revealed_switch_candidate_hp else 1.0,
                "revealed_switch_bonus_applied": float(revealed_switch_bonus_applied[1]) if revealed_switch_bonus_applied else 0.0,
                "revealed_switch_blocked_by_ko_action": bool(revealed_switch_blocked_by_ko_action[1]) if revealed_switch_blocked_by_ko_action else False,
                "revealed_switch_blocked_by_high_value_action": bool(revealed_switch_blocked_by_high_value_action[1]) if revealed_switch_blocked_by_high_value_action else False,
                "revealed_switch_rejected_worse_other_threat": bool(revealed_switch_rejected_worse_other_threat[1]) if revealed_switch_rejected_worse_other_threat else False,
                "revealed_switch_post_turn_damage_taken": (float(revealed_switch_post_turn_damage_taken[1]) if revealed_switch_post_turn_damage_taken and revealed_switch_post_turn_damage_taken[1] is not None else None),
                "revealed_switch_post_turn_survived": (bool(revealed_switch_post_turn_survived[1]) if revealed_switch_post_turn_survived and revealed_switch_post_turn_survived[1] is not None else None),
                "revealed_switch_predicted_move_used": str(revealed_switch_predicted_move_used[1]) if revealed_switch_predicted_move_used else "",
                "revealed_switch_prediction_correct": bool(revealed_switch_prediction_correct[1]) if revealed_switch_prediction_correct else False,
                "revealed_switch_prediction_wrong": bool(revealed_switch_prediction_wrong[1]) if revealed_switch_prediction_wrong else False,
                # Phase 6.4.2: Type-immune audit fields
                "our_type_immune_move_selected": bool(our_type_immune_move_selected[1]) if our_type_immune_move_selected else False,
                "our_type_immune_only_legal": bool(our_type_immune_only_legal[1]) if our_type_immune_only_legal else False,
                "our_type_immune_move_avoided": bool(our_type_immune_move_avoided[1]) if our_type_immune_move_avoided else False,
                "our_type_immune_attacker": str(our_type_immune_attacker[1]) if our_type_immune_attacker else "",
                "our_type_immune_move": str(our_type_immune_move[1]) if our_type_immune_move else "",
                "our_type_immune_target": str(our_type_immune_target[1]) if our_type_immune_target else "",
                "our_type_immune_target_types": str(our_type_immune_target_types[1]) if our_type_immune_target_types else "",
                "our_type_immune_reason": str(our_type_immune_reason[1]) if our_type_immune_reason else "",
                # Phase 6.3.5: Ground-into-Flying audit fields
                "ground_into_flying_selected": bool(ground_into_flying_selected[1]) if ground_into_flying_selected else False,
                "ground_into_secondary_flying_selected": bool(ground_into_secondary_flying_selected[1]) if ground_into_secondary_flying_selected else False,
                "ground_into_flying_avoided": bool(ground_into_flying_avoided[1]) if ground_into_flying_avoided else False,
                "ground_into_flying_only_legal": bool(ground_into_flying_only_legal[1]) if ground_into_flying_only_legal else False,
                "ground_flying_exception_applied": bool(ground_flying_exception_applied[1]) if ground_flying_exception_applied else False,
                "ground_flying_exception_reason": str(ground_flying_exception_reason[1]) if ground_flying_exception_reason else "",
                "ground_flying_target_primary_type": str(ground_flying_target_primary_type[1]) if ground_flying_target_primary_type else "",
                "ground_flying_target_secondary_type": str(ground_flying_target_secondary_type[1]) if ground_flying_target_secondary_type else "",
                # Phase 6.3.5: Singleton ability safety fields
                "known_ability_resolution_source": str(known_ability_resolution_source[1]) if known_ability_resolution_source else "",
                "deterministic_singleton_ability_used": bool(deterministic_singleton_ability_used[1]) if deterministic_singleton_ability_used else False,
                "deterministic_singleton_ability": str(deterministic_singleton_ability[1]) if deterministic_singleton_ability else "",
                "deterministic_singleton_target_species": str(deterministic_singleton_target_species[1]) if deterministic_singleton_target_species else "",
                "singleton_ability_hard_block_avoided": bool(singleton_ability_hard_block_avoided[1]) if singleton_ability_hard_block_avoided else False,
                "singleton_ground_into_levitate_selected": bool(singleton_ground_into_levitate_selected[1]) if singleton_ground_into_levitate_selected else False,
                "singleton_ability_conflict_detected": bool(singleton_ability_conflict_detected[1]) if singleton_ability_conflict_detected else False,
                "singleton_ability_suppressed": bool(singleton_ability_suppressed[1]) if singleton_ability_suppressed else False,
                "singleton_ability_suppression_reason": str(singleton_ability_suppression_reason[1]) if singleton_ability_suppression_reason else "",
                "singleton_only_legal_action": bool(singleton_only_legal_action[1]) if singleton_only_legal_action else False,
                "singleton_levitate_opportunity_observed": bool(singleton_levitate_opportunity_observed[1]) if singleton_levitate_opportunity_observed else False,
                "singleton_ground_into_levitate_selected_observed": bool(singleton_ground_into_levitate_selected_observed[1]) if singleton_ground_into_levitate_selected_observed else False,
                "singleton_hard_block_applied": bool(singleton_hard_block_applied[1]) if singleton_hard_block_applied else False,
                "singleton_blocked_candidate_observed": bool(singleton_blocked_candidate_observed[1]) if singleton_blocked_candidate_observed else False,
                "singleton_selection_changed_by_safety": bool(singleton_selection_changed_by_safety[1]) if singleton_selection_changed_by_safety else False,
                "singleton_resolution_source": str(singleton_resolution_source[1]) if singleton_resolution_source else "",
                # Phase 6.3.5a: Priority blocking fields
                "priority_move_field_blocked": bool(priority_move_field_blocked[1]) if priority_move_field_blocked else False,
                "priority_move_block_reason": str(priority_move_block_reason[1]) if priority_move_block_reason else "",
                "priority_move_selected_into_psychic_terrain": bool(priority_move_selected_into_psychic_terrain[1]) if priority_move_selected_into_psychic_terrain else False,
                "sucker_punch_selected_into_psychic_terrain": bool(sucker_punch_selected_into_psychic_terrain[1]) if sucker_punch_selected_into_psychic_terrain else False,
                "priority_move_block_avoided": bool(priority_move_block_avoided[1]) if priority_move_block_avoided else False,
                "priority_move_only_legal": bool(priority_move_only_legal[1]) if priority_move_only_legal else False,
                "priority_target_grounded": bool(priority_target_grounded[1]) if priority_target_grounded else False,
                "priority_target_species": str(priority_target_species[1]) if priority_target_species else "",
                "priority_target_type_1": str(priority_target_type_1[1]) if priority_target_type_1 else "",
                "priority_target_type_2": str(priority_target_type_2[1]) if priority_target_type_2 else "",
                "priority_blocking_ability": str(priority_blocking_ability[1]) if priority_blocking_ability else "",
                "priority_blocking_ability_source": str(priority_blocking_ability_source[1]) if priority_blocking_ability_source else "",
            },
            "opp_actions": {
                "outcome_known": False,
                "opponent_used_priority": None,
                "opponent_moved_before_us": None,
                "opponent_ability_error": None,
                "opponent_ground_into_levitate": None,
                "opponent_type_immune_move_selected": False,
            }

        }

        if self.detail_level == "full":
            turn_data["all_legal_joint_orders"] = [
                {"message": jo.message if jo else "/choose pass", "score": float(sc)}
                for jo, sc, _, _ in scored_joint_orders
            ]

        self.pending_turns[battle_tag] = turn_data
        self._append_live_event(self._build_live_decision_event(battle_tag, turn_data))

    def update_previous_turn(self, battle_tag, battle):
        """
        Scan battle._replay_data and resolve the outcome of the previous turn.
        Safely falls back if information is not available.
        """
        pending = self.pending_turns.get(battle_tag)
        if not pending:
            return

        # Pop from pending so we only process it once
        self.pending_turns.pop(battle_tag, None)

        N_minus_1 = pending["turn"]
        player_role = getattr(battle, "player_role", None)
        if not player_role or not hasattr(battle, "_replay_data") or not battle._replay_data:
            pending["slot_0"]["outcome_known"] = False
            pending["slot_1"]["outcome_known"] = False
            pending["opp_actions"]["outcome_known"] = False
            self.completed_turns.setdefault(battle_tag, []).append(pending)
            self._append_live_event(self._build_live_outcome_event(battle_tag, pending))
            return

        opp_role = "p2" if player_role == "p1" else "p1"

        try:
            # Gather replay logs for turn N_minus_1
            turn_events = []
            found_start = False
            for msg in battle._replay_data:
                cleaned = [x.strip() for x in msg if x != ""]
                if len(cleaned) >= 2 and cleaned[0] == "turn":
                    if cleaned[1] == str(N_minus_1):
                        found_start = True
                        continue
                    elif found_start:
                        break
                if found_start:
                    turn_events.append(cleaned)

            # Resolve outcome fields for each slot
            for slot_key in ("slot_0", "slot_1"):
                slot_idx = 0 if slot_key == "slot_0" else 1
                slot_data = pending[slot_key]
                action_str = slot_data["action"] or ""

                # Default states
                slot_data["outcome_known"] = True
                slot_data["actual_ko"] = False
                slot_data["target_used_protect"] = False
                slot_data["our_mon_fainted"] = False
                slot_data["fainted_before_moving"] = False
                slot_data["was_targeted"] = False

                # 1. Did our Pokemon faint or get targeted?
                our_prefix = f"{player_role}a" if slot_idx == 0 else f"{player_role}b"
                for msg in turn_events:
                    if len(msg) >= 2 and msg[0] == "faint" and msg[1].startswith(our_prefix):
                        slot_data["our_mon_fainted"] = True
                    if len(msg) >= 4 and msg[0] == "move" and msg[1].startswith(opp_role):
                        if msg[3].startswith(our_prefix):
                            slot_data["was_targeted"] = True
                    if len(msg) >= 2 and msg[0] == "-damage" and msg[1].startswith(our_prefix):
                        slot_data["was_targeted"] = True

                # 2. Did our Pokemon faint before moving?
                if "move" in action_str:
                    faint_idx = None
                    move_idx = None
                    for idx, msg in enumerate(turn_events):
                        if len(msg) >= 2 and msg[0] == "faint" and msg[1].startswith(our_prefix):
                            if faint_idx is None:
                                faint_idx = idx
                        if len(msg) >= 3 and msg[0] == "move" and msg[1].startswith(our_prefix):
                            if move_idx is None:
                                move_idx = idx
                    if faint_idx is not None and (move_idx is None or faint_idx < move_idx):
                        slot_data["fainted_before_moving"] = True

                # 2.1 Resolve active_moved_before_threat tri-state
                slot_data["active_moved_before_threat"] = None
                our_move_idx = None
                for idx, msg in enumerate(turn_events):
                    if len(msg) >= 3 and msg[0] == "move" and msg[1].startswith(our_prefix):
                        our_move_idx = idx
                        break

                if our_move_idx is not None:
                    threat_opps = slot_data.get("faster_opponents", []) + slot_data.get("priority_opponents", [])
                    if threat_opps:
                        threat_move_idx = None
                        for idx, msg in enumerate(turn_events):
                            if len(msg) >= 3 and msg[0] == "move" and msg[1].startswith(opp_role):
                                opp_species_clean = msg[1].split(":")[1].strip().lower() if ":" in msg[1] else msg[1].strip().lower()
                                for t in threat_opps:
                                    if t.lower() in opp_species_clean or opp_species_clean in t.lower():
                                        threat_move_idx = idx
                                        break
                                if threat_move_idx is not None:
                                    break
                        if threat_move_idx is not None:
                            slot_data["active_moved_before_threat"] = (our_move_idx < threat_move_idx)
                        else:
                            slot_data["active_moved_before_threat"] = True
                else:
                    if slot_data["fainted_before_moving"]:
                        slot_data["active_moved_before_threat"] = False
                    else:
                        slot_data["active_moved_before_threat"] = None

                # 3. Resolve target outcomes if we used a single-target move
                # Single-target move targeting opponent: target slot 1 or 2
                target_str = None
                target_idx = None
                if "move " in action_str:
                    parts = action_str.split(" ")
                    if len(parts) >= 3:
                        target_pos_str = parts[-1]
                        if target_pos_str in ("1", "2"):
                            target_idx = int(target_pos_str) - 1
                            target_str = f"{opp_role}a" if target_idx == 0 else f"{opp_role}b"

                if target_str is not None:
                    # A. Did target faint?
                    for msg in turn_events:
                        if len(msg) >= 2 and msg[0] == "faint" and msg[1].startswith(target_str):
                            slot_data["actual_ko"] = True

                    # B. Did target use Protect?
                    for msg in turn_events:
                        if (len(msg) >= 3 and msg[0] == "move" and msg[1].startswith(target_str)
                                and self._normalize_name(msg[2]) in ("protect", "detect", "spikyshield", "kingsshield", "banefulbunker", "silktrap")):
                            slot_data["target_used_protect"] = True

                    # C. What was the actual damage dealt?
                    # Find target Pokemon in opponent team at the start of current turn N
                    target_species = slot_data["target_species"]
                    hp_before = slot_data["target_hp_before"]
                    if hp_before is not None:
                        hp_after = 0.0
                        if slot_data["actual_ko"]:
                            hp_after = 0.0
                        else:
                            # Search the opponent's active/team for S
                            target_mon = None
                            for opp in battle.opponent_active_pokemon:
                                if opp and opp.species == target_species:
                                    target_mon = opp
                                    break
                            if not target_mon:
                                for opp in battle.opponent_team.values():
                                    if opp.species == target_species:
                                        target_mon = opp
                                        break
                            if target_mon:
                                hp_after = float(target_mon.current_hp_fraction) if target_mon.current_hp_fraction is not None else 0.0

                        slot_data["actual_damage"] = max(0.0, hp_before - hp_after)
                        if slot_data["actual_damage"] > 0.0 and hp_after < 0.20 and hp_after > 0.0:
                            slot_data["opponent_survived_below_20"] = True
                        else:
                            slot_data["opponent_survived_below_20"] = False

                if slot_data.get("self_drop_spam_candidate") and not slot_data.get("actual_ko"):
                    slot_data["self_drop_move_spam"] = True

            # Phase 6.4.2: Resolve interception outcome from local events
            for slot_key in ("slot_0", "slot_1"):
                slot_idx = 0 if slot_key == "slot_0" else 1
                slot_data = pending[slot_key]

                if not slot_data.get("revealed_switch_interception_selected"):
                    continue

                our_prefix = f"{player_role}a" if slot_idx == 0 else f"{player_role}b"

                # Track switched-in Pokemon species for identity matching
                switched_species = slot_data.get("revealed_switch_candidate_species", "")
                predicted_moves = slot_data.get("revealed_switch_threat_move_ids", [])

                if not predicted_moves:
                    continue

                # Look for opponent move events targeting our switched-in slot
                opponent_moves_used = []
                targeted_our_slot = False
                damage_taken = 0.0

                for msg in turn_events:
                    if len(msg) >= 3 and msg[0] == "move" and msg[1].startswith(opp_role):
                        move_name = self._normalize_name(msg[2])
                        # Check if this move targets our slot
                        if len(msg) >= 4 and msg[3].startswith(our_prefix):
                            targeted_our_slot = True
                            opponent_moves_used.append(move_name)

                # Check if the switched-in Pokemon fainted
                survived = True
                for msg in turn_events:
                    if len(msg) >= 2 and msg[0] == "faint" and msg[1].startswith(our_prefix):
                        survived = False

                # Calculate damage from HP changes (if we can identify the Pokemon)
                if switched_species:
                    # Try to find the Pokemon in battle state to get HP
                    target_mon = None
                    for opp in battle.opponent_active_pokemon:
                        if opp and opp.species == switched_species:
                            target_mon = opp
                            break
                    if not target_mon:
                        for opp in battle.opponent_team.values():
                            if opp.species == switched_species:
                                target_mon = opp
                                break

                # Determine prediction correctness using three-state semantics
                prediction_correct = None
                prediction_wrong = None

                if targeted_our_slot:
                    # Did the opponent use one of our predicted moves?
                    predicted_move_normalized = [self._normalize_name(m) for m in predicted_moves]
                    used_predicted = any(m in predicted_move_normalized for m in opponent_moves_used)

                    if used_predicted:
                        prediction_correct = True
                    else:
                        # Opponent moved but not with predicted move
                        prediction_wrong = False
                elif opponent_moves_used:
                    # Opponent moved but not at our slot
                    prediction_wrong = False
                # else: no opponent move event - leave as None (unknown/unresolved)

                slot_data["revealed_switch_post_turn_survived"] = survived
                slot_data["revealed_switch_predicted_move_used"] = ",".join(opponent_moves_used) if opponent_moves_used else ""
                slot_data["revealed_switch_prediction_correct"] = prediction_correct
                slot_data["revealed_switch_prediction_wrong"] = prediction_wrong

            # Resolve opponent actions
            opp_actions = pending["opp_actions"]
            opp_actions["outcome_known"] = True
            opp_actions["opponent_used_priority"] = False
            opp_actions["opponent_moved_before_us"] = False

            # Check if any opponent used a priority move
            for msg in turn_events:
                if len(msg) >= 3 and msg[0] == "move" and msg[1].startswith(opp_role):
                    move_name = self._normalize_name(msg[2])
                    if move_name in self.PRIORITY_MOVES:
                        opp_actions["opponent_used_priority"] = True

            # Check if opponent moved before us
            # Find the indices of first move events
            first_opp_move_idx = None
            first_our_move_idx = None
            for idx, msg in enumerate(turn_events):
                if len(msg) >= 3 and msg[0] == "move":
                    if msg[1].startswith(opp_role) and first_opp_move_idx is None:
                        first_opp_move_idx = idx
                    if msg[1].startswith(player_role) and first_our_move_idx is None:
                        first_our_move_idx = idx

            if first_opp_move_idx is not None:
                if first_our_move_idx is None or first_opp_move_idx < first_our_move_idx:
                    opp_actions["opponent_moved_before_us"] = True

            (
                opp_actions["opponent_ability_error"],
                opp_actions["opponent_ground_into_levitate"],
            ) = self._check_opponent_ability_errors(turn_events, player_role, opp_role)

        except Exception:
            pending["slot_0"]["outcome_known"] = False
            pending["slot_1"]["outcome_known"] = False
            pending["opp_actions"]["outcome_known"] = False

        self.completed_turns.setdefault(battle_tag, []).append(pending)
        self._append_live_event(self._build_live_outcome_event(battle_tag, pending))

    def save_battle(self, battle_tag, winner, battle):
        """
        Finalize and save the battle record with top-level metadata.
        """
        # Update final pending turn if exists
        self.update_previous_turn(battle_tag, battle)

        turns = self.completed_turns.pop(battle_tag, [])
        won = (winner == battle.player_username)

        # Top-level config metadata — prefer per-battle config, fall back to constructor
        cfg = self.battle_configs.pop(battle_tag, None)
        if cfg is not None:
            singleton_enabled = bool(getattr(cfg, "ability_hard_safety_allow_singleton_deduction", False))
            priority_enabled = bool(getattr(cfg, "enable_priority_field_hard_safety", False))
        else:
            singleton_enabled = self._singleton_safety_enabled
            priority_enabled = self._priority_safety_enabled

        battle_record = {
            "battle_tag": str(battle_tag),
            "winner": str(winner),
            "won": bool(won),
            "total_turns": int(getattr(battle, "turn", 0)),
            "benchmark_arm": self._benchmark_arm,
            "singleton_safety_enabled": singleton_enabled,
            "priority_safety_enabled": priority_enabled,
            "audit_turns": turns
        }

        with open(self.filepath, "a") as f:
            f.write(json.dumps(battle_record) + "\n")
        self._append_live_event({
            "event": "battle_end",
            "battle_tag": str(battle_tag),
            "winner": str(winner),
            "won": bool(won),
            "total_turns": int(getattr(battle, "turn", 0)),
            "benchmark_arm": self._benchmark_arm,
        })
