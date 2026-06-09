#!/usr/bin/env python3
import json
import os
import sys

def analyze_audit_log(filepath="logs/doubles_decision_audit.jsonl"):
    if not os.path.exists(filepath):
        print(f"Error: Log file not found at {filepath}")
        sys.exit(1)

    total_battles = 0
    wins = 0
    losses = 0
    total_turns = 0
    total_turns_with_known_outcome = 0

    # Phase 6.3.2 diagnostic variables (action-level counts)
    absorb_selected_count = 0       # total absorb-immune actions selected (= absorb_selected_action_count)
    absorb_forced_count = 0         # actions where selection was forced (no useful scored alternative)
    absorb_avoidable_count = 0      # actions where a safe alternative existed (= absorb_avoidable_action_count)
    absorb_productive_partial_count = 0  # partial spread that still hits one opp
    absorb_streak_gte_2_count = 0   # action occurrences with streak >= 2
    absorb_max_streak = 0
    # Phase 6.3.2b exhaustive action counts
    forced_no_useful_scored_alt_action_count = 0
    avoidable_safe_damage_alt_action_count = 0
    productive_partial_spread_action_count = 0
    other_useful_scored_alt_action_count = 0
    unclassified_action_count = 0
    # Phase 6.3.2a: direct vs redirected action counts
    direct_absorb_selected_count = 0
    redirected_absorb_selected_count = 0
    direct_avoidable_absorb_count = 0
    redirected_avoidable_absorb_count = 0
    # Battle-level win/loss counters
    absorb_outcome_split = {
        "selected": {"wins": 0, "losses": 0},
        "forced": {"wins": 0, "losses": 0},
        "avoidable": {"wins": 0, "losses": 0},
        "productive_partial": {"wins": 0, "losses": 0}
    }
    # Per-battle tracking (to avoid double-counting at battle level)
    _battle_tags_with_absorb_selected_win = set()
    _battle_tags_with_absorb_selected_loss = set()
    _battle_tags_with_avoidable_win = set()
    _battle_tags_with_avoidable_loss = set()
    _battle_tags_with_forced_win = set()
    _battle_tags_with_forced_loss = set()
    _battle_tags_with_productive_win = set()
    _battle_tags_with_productive_loss = set()
    absorb_reason_split = {}
    absorb_samples = []

    # Phase 6.3.3: Direct Known-Absorb Safety Report variables
    direct_absorb_avoided_count = 0
    direct_absorb_immune_selected_count = 0
    direct_absorb_only_legal_count = 0
    direct_absorb_avoidable_selected_count = 0
    direct_absorb_reasons = {}
    direct_absorb_samples = []
    _battle_tags_with_direct_avoided_win = set()
    _battle_tags_with_direct_avoided_loss = set()
    _battle_tags_with_direct_selected_win = set()
    _battle_tags_with_direct_selected_loss = set()

    # Phase 6.3.6: Known Absorb Hard Safety Report variables
    known_absorb_selected_count = 0
    known_absorb_avoided_count = 0
    known_absorb_repeat_selected_count = 0
    known_absorb_only_legal_count = 0
    known_absorb_reasons = {}
    known_absorb_samples = []
    _known_absorb_selected_wins = 0
    known_absorb_selected_losses = 0
    # Track per-slot history for repeat detection
    _slot_absorb_history = {}  # (battle_tag, slot_idx) -> list of (turn, move_id, target_species, ability)

    # Phase 6.3.5a: Priority Field Safety Report variables
    priority_move_field_blocked_count = 0
    priority_move_block_avoided_count = 0
    priority_move_selected_into_psychic_terrain_count = 0
    sucker_punch_selected_into_psychic_terrain_count = 0
    priority_move_only_legal_count = 0
    priority_move_avoidable_selected_count = 0
    priority_blocking_ability_counts = {}
    priority_block_reasons = {}
    priority_samples = []
    _battle_tags_with_priority_avoided_win = set()
    _battle_tags_with_priority_avoided_loss = set()
    _battle_tags_with_priority_selected_win = set()
    _battle_tags_with_priority_selected_loss = set()

    ability_reports = {
        "our_ground_into_levitate_selected": 0,
        "opp_ground_into_levitate_selected": 0,
        "our_ability_immune_move_selected": 0,
        "opp_ability_immune_move_selected": 0,
        "ability_hard_blocks_avoided": 0,
        "ally_ability_safe_spread": 0,
        "ability_redirection_avoided": 0,
        "ground_block_avoided": 0,
        "absorb_block_avoided": 0,
        "optional_block_avoided": 0,
        "immune_singletarget_selected": 0,
        "partial_ability_immune_spread_selected": 0
    }
    ability_report_outcomes = {
        name: {"wins": 0, "losses": 0}
        for name in (
            "ground_into_levitate_selected",
            "ability_immune_move_selected",
            "ability_hard_block_avoided",
            "ally_ability_safe_spread",
            "ability_redirection_avoided",
            "ground_block_avoided",
            "absorb_block_avoided",
            "optional_block_avoided",
            "immune_singletarget_selected",
            "partial_ability_immune_spread_selected"
        )
    }
    ability_cases = []

    # Pattern counts in wins and losses
    # maps pattern_name -> count_in_losses, count_in_wins
    pattern_losses = {i: 0 for i in range(1, 32)}
    pattern_wins = {i: 0 for i in range(1, 32)}
    
    # Sample battle tags for each pattern
    pattern_loss_samples = {i: [] for i in range(1, 32)}
    pattern_win_samples = {i: [] for i in range(1, 32)}

    pattern_names = {
        1: "missed_ko",
        2: "failed_to_target_low_hp",
        3: "bad_double_target",
        4: "underused_spread",
        5: "bad_protect",
        6: "missed_protect",
        7: "bad_status_move",
        8: "speed_priority_loss",
        9: "switch_mistake",
        10: "damage_estimate_error",
        11: "zero_effectiveness_move_selected",
        12: "all_targets_immune_spread_selected",
        13: "self_drop_move_spam",
        14: "partial_immune_spread_selected",
        15: "efficient_partial_spread_selected",
        16: "inefficient_partial_spread_selected",
        17: "speed_priority_threat_unanswered",
        18: "successful_speed_priority_protect",
        19: "bad_speed_priority_protect",
        20: "order_aware_overkill",
        21: "detected_speed_priority_threat",
        22: "true_unanswered_speed_priority_threat",
        23: "productive_attack_under_threat",
        24: "false_positive_speed_priority_threat",
        25: "bad_speed_priority_protect_refined",
        26: "ability_immune_move_selected",
        27: "ground_into_levitate_selected",
        28: "ability_hard_block_avoided",
        29: "ally_ability_safe_spread",
        30: "ability_redirection_avoided",
        31: "partial_ability_immune_spread_selected"
    }


    with open(filepath, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                battle = json.loads(line)
            except Exception as e:
                print(f"Failed to parse line: {e}")
                continue

            total_battles += 1
            is_win = battle.get("won", False)
            if is_win:
                wins += 1
            else:
                losses += 1

            battle_tag = battle.get("battle_tag", "Unknown")
            audit_turns = battle.get("audit_turns", [])
            total_turns += len(audit_turns)

            # Keep track of triggered patterns for this battle (to increment battle-level occurrences)
            triggered_in_battle = set()

            for turn_data in audit_turns:
                our_active = turn_data.get("our_active", [None, None])
                opp_active = turn_data.get("opp_active", [None, None])
                slot_0 = turn_data.get("slot_0", {})
                slot_1 = turn_data.get("slot_1", {})
                opp_actions = turn_data.get("opp_actions", {})

                # Track outcome known rate
                if slot_0.get("outcome_known") or slot_1.get("outcome_known"):
                    total_turns_with_known_outcome += 1

                # Track ability reports
                for slot_index, slot in enumerate((slot_0, slot_1)):
                    reason = slot.get("ability_block_reason", "")
                    slot["ground_block_avoided"] = bool(slot.get("ability_hard_block_avoided") and reason.startswith("ground_"))
                    slot["absorb_block_avoided"] = bool(slot.get("ability_hard_block_avoided") and reason.startswith(("water_into_", "electric_into_", "fire_into_", "grass_into_")))
                    slot["optional_block_avoided"] = bool(slot.get("ability_hard_block_avoided") and reason.startswith(("sound_into_", "bullet_into_", "explosion_into_")))
                    slot["immune_singletarget_selected"] = bool(slot.get("ability_immune_move_selected") and not slot.get("action_types", {}).get("spread"))

                    if slot.get("ground_into_levitate_selected"):
                        ability_reports["our_ground_into_levitate_selected"] += 1
                    if slot.get("ability_immune_move_selected"):
                        ability_reports["our_ability_immune_move_selected"] += 1
                    if slot.get("ability_hard_block_avoided"):
                        ability_reports["ability_hard_blocks_avoided"] += 1
                    if slot.get("ally_ability_safe_spread"):
                        ability_reports["ally_ability_safe_spread"] += 1
                    if slot.get("ability_redirection_avoided"):
                        ability_reports["ability_redirection_avoided"] += 1
                    if slot.get("ground_block_avoided"):
                        ability_reports["ground_block_avoided"] += 1
                    if slot.get("absorb_block_avoided"):
                        ability_reports["absorb_block_avoided"] += 1
                    if slot.get("optional_block_avoided"):
                        ability_reports["optional_block_avoided"] += 1
                    if slot.get("immune_singletarget_selected"):
                        ability_reports["immune_singletarget_selected"] += 1
                    if slot.get("partial_ability_immune_spread_selected"):
                        ability_reports["partial_ability_immune_spread_selected"] += 1

                    for metric in ability_report_outcomes:
                        if slot.get(metric):
                            outcome = "wins" if is_win else "losses"
                            ability_report_outcomes[metric][outcome] += 1
                            if len(ability_cases) < 25:
                                attacker = "Unknown"
                                if len(our_active) > slot_index and our_active[slot_index]:
                                    attacker = our_active[slot_index].get("species", "Unknown")
                                ability_cases.append({
                                    "metric": metric,
                                    "battle_tag": battle_tag,
                                    "turn": turn_data.get("turn"),
                                    "won": is_win,
                                    "attacker": attacker,
                                    "move": slot.get("action", ""),
                                    "target": slot.get("ability_blocked_target_species") or slot.get("target_species") or "",
                                    "ability": slot.get("ability_blocked_target_ability", ""),
                                    "reason": slot.get("ability_block_reason", ""),
                                })

                    # Phase 6.3.3: Direct Known-Absorb Safety parsing
                    da_avoided = bool(slot.get("direct_absorb_hard_block_avoided", False))
                    da_selected = bool(slot.get("direct_absorb_immune_move_selected", False))
                    da_only_legal = bool(slot.get("direct_absorb_only_legal_action", False))
                    da_reason = slot.get("direct_absorb_block_reason", "")
                    da_species = slot.get("direct_absorb_target_species", "")
                    da_ability = slot.get("direct_absorb_target_ability", "")

                    if da_avoided:
                        direct_absorb_avoided_count += 1
                        if is_win:
                            _battle_tags_with_direct_avoided_win.add(battle_tag)
                        else:
                            _battle_tags_with_direct_avoided_loss.add(battle_tag)

                    if da_selected:
                        direct_absorb_immune_selected_count += 1
                        if da_only_legal:
                            direct_absorb_only_legal_count += 1
                        else:
                            direct_absorb_avoidable_selected_count += 1

                        if is_win:
                            _battle_tags_with_direct_selected_win.add(battle_tag)
                        else:
                            _battle_tags_with_direct_selected_loss.add(battle_tag)

                        if da_reason:
                            direct_absorb_reasons[da_reason] = direct_absorb_reasons.get(da_reason, 0) + 1

                        if len(direct_absorb_samples) < 25:
                            attacker_sp = "Unknown"
                            if len(our_active) > slot_index and our_active[slot_index]:
                                attacker_sp = our_active[slot_index].get("species", "Unknown")
                            direct_absorb_samples.append({
                                "battle_tag": battle_tag,
                                "turn": turn_data.get("turn"),
                                "won": is_win,
                                "attacker": attacker_sp,
                                "move": slot.get("action", ""),
                                "target": da_species,
                                "ability": da_ability,
                                "reason": da_reason,
                                "only_legal": da_only_legal
                            })

                    # Phase 6.3.6: Known Absorb Hard Safety parsing
                    ka_selected = bool(slot.get("direct_absorb_immune_move_selected", False))
                    ka_avoided = bool(slot.get("direct_absorb_hard_block_avoided", False))
                    ka_only_legal = bool(slot.get("direct_absorb_only_legal_action", False))
                    ka_reason = slot.get("direct_absorb_block_reason", "")
                    ka_species = slot.get("direct_absorb_target_species", "")
                    ka_ability = slot.get("direct_absorb_target_ability", "")

                    if ka_selected:
                        known_absorb_selected_count += 1
                        if ka_only_legal:
                            known_absorb_only_legal_count += 1
                        if is_win:
                            _known_absorb_selected_wins += 1
                        else:
                            known_absorb_selected_losses += 1
                        if ka_reason:
                            known_absorb_reasons[ka_reason] = known_absorb_reasons.get(ka_reason, 0) + 1

                        # Repeat detection: same slot, same ability, different turn
                        slot_key = (battle_tag, slot_index)
                        if slot_key not in _slot_absorb_history:
                            _slot_absorb_history[slot_key] = []
                        current_turn_num = turn_data.get("turn", 0)
                        move_id = slot.get("action", "")
                        for prev_turn, prev_move, prev_target, prev_ability in _slot_absorb_history[slot_key]:
                            if prev_ability == ka_ability and prev_turn < current_turn_num:
                                known_absorb_repeat_selected_count += 1
                                break
                        _slot_absorb_history[slot_key].append(
                            (current_turn_num, move_id, ka_species, ka_ability)
                        )

                        if len(known_absorb_samples) < 25:
                            attacker_sp = "Unknown"
                            if len(our_active) > slot_index and our_active[slot_index]:
                                attacker_sp = our_active[slot_index].get("species", "Unknown")
                            known_absorb_samples.append({
                                "battle_tag": battle_tag,
                                "turn": turn_data.get("turn"),
                                "won": is_win,
                                "attacker": attacker_sp,
                                "move": move_id,
                                "target": ka_species,
                                "ability": ka_ability,
                                "reason": ka_reason,
                                "only_legal": ka_only_legal,
                            })

                    if ka_avoided:
                        known_absorb_avoided_count += 1

                    # Phase 6.3.5a: Priority Field Safety parsing
                    p_blocked = bool(slot.get("priority_move_field_blocked", False))
                    p_avoided = bool(slot.get("priority_move_block_avoided", False))
                    p_only_legal = bool(slot.get("priority_move_only_legal", False))
                    p_reason = slot.get("priority_move_block_reason", "")
                    p_selected_psychic = bool(slot.get("priority_move_selected_into_psychic_terrain", False))
                    sp_selected_psychic = bool(slot.get("sucker_punch_selected_into_psychic_terrain", False))
                    p_species = slot.get("priority_target_species", "")
                    p_grounded = bool(slot.get("priority_target_grounded", False))
                    p_blocking_ab = slot.get("priority_blocking_ability", "")
                    p_blocking_source = slot.get("priority_blocking_ability_source", "")

                    if p_blocked:
                        priority_move_field_blocked_count += 1
                        if p_selected_psychic:
                            priority_move_selected_into_psychic_terrain_count += 1
                        if sp_selected_psychic:
                            sucker_punch_selected_into_psychic_terrain_count += 1
                        if p_only_legal:
                            priority_move_only_legal_count += 1
                        else:
                            priority_move_avoidable_selected_count += 1

                        if is_win:
                            _battle_tags_with_priority_selected_win.add(battle_tag)
                        else:
                            _battle_tags_with_priority_selected_loss.add(battle_tag)

                        if p_reason:
                            priority_block_reasons[p_reason] = priority_block_reasons.get(p_reason, 0) + 1
                        if p_blocking_ab:
                            priority_blocking_ability_counts[p_blocking_ab] = priority_blocking_ability_counts.get(p_blocking_ab, 0) + 1

                        if len(priority_samples) < 25:
                            attacker_sp = "Unknown"
                            if len(our_active) > slot_index and our_active[slot_index]:
                                attacker_sp = our_active[slot_index].get("species", "Unknown")
                            priority_samples.append({
                                "battle_tag": battle_tag,
                                "turn": turn_data.get("turn"),
                                "won": is_win,
                                "attacker": attacker_sp,
                                "move": slot.get("action", ""),
                                "target": p_species,
                                "grounded": p_grounded,
                                "reason": p_reason,
                                "blocking_ability": p_blocking_ab,
                                "blocking_source": p_blocking_source,
                                "only_legal": p_only_legal
                            })

                    if p_avoided:
                        priority_move_block_avoided_count += 1
                        if is_win:
                            _battle_tags_with_priority_avoided_win.add(battle_tag)
                        else:
                            _battle_tags_with_priority_avoided_loss.add(battle_tag)

                    # Phase 6.3.2 diagnostic populating
                    if slot.get("absorb_immune_move_selected"):
                        absorb_selected_count += 1
                        is_redirected = bool(slot.get("absorb_via_redirection", False))
                        if is_redirected:
                            redirected_absorb_selected_count += 1
                        else:
                            direct_absorb_selected_count += 1

                        if is_win:
                            absorb_outcome_split["selected"]["wins"] += 1
                            _battle_tags_with_absorb_selected_win.add(battle_tag)
                        else:
                            absorb_outcome_split["selected"]["losses"] += 1
                            _battle_tags_with_absorb_selected_loss.add(battle_tag)

                        reason_val = slot.get("absorb_error_reason") or slot.get("ability_block_reason") or "unknown"
                        absorb_reason_split[reason_val] = absorb_reason_split.get(reason_val, 0) + 1

                        if slot.get("absorb_selection_forced"):
                            absorb_forced_count += 1
                            if is_win:
                                absorb_outcome_split["forced"]["wins"] += 1
                                _battle_tags_with_forced_win.add(battle_tag)
                            else:
                                absorb_outcome_split["forced"]["losses"] += 1
                                _battle_tags_with_forced_loss.add(battle_tag)

                        if slot.get("avoidable_absorb_error"):
                            absorb_avoidable_count += 1
                            if is_redirected:
                                redirected_avoidable_absorb_count += 1
                            else:
                                direct_avoidable_absorb_count += 1
                            if is_win:
                                absorb_outcome_split["avoidable"]["wins"] += 1
                                _battle_tags_with_avoidable_win.add(battle_tag)
                            else:
                                absorb_outcome_split["avoidable"]["losses"] += 1
                                _battle_tags_with_avoidable_loss.add(battle_tag)

                        if slot.get("productive_partial_absorb_spread"):
                            absorb_productive_partial_count += 1
                            if is_win:
                                absorb_outcome_split["productive_partial"]["wins"] += 1
                                _battle_tags_with_productive_win.add(battle_tag)
                            else:
                                absorb_outcome_split["productive_partial"]["losses"] += 1
                                _battle_tags_with_productive_loss.add(battle_tag)

                        # Exhaustive classification
                        if slot.get("productive_partial_absorb_spread"):
                            classification = "PRODUCTIVE_PARTIAL_SPREAD"
                            productive_partial_spread_action_count += 1
                        elif slot.get("avoidable_absorb_error"):
                            classification = "AVOIDABLE_SAFE_DAMAGE_ALT"
                            avoidable_safe_damage_alt_action_count += 1
                        elif slot.get("absorb_selection_forced"):
                            classification = "FORCED_NO_USEFUL_SCORED_ALT"
                            forced_no_useful_scored_alt_action_count += 1
                        elif not slot.get("absorb_safe_alternative_available") and not slot.get("absorb_selection_forced"):
                            classification = "OTHER_USEFUL_SCORED_ALT"
                            other_useful_scored_alt_action_count += 1
                        else:
                            classification = "UNCLASSIFIED"
                            unclassified_action_count += 1

                        streak = slot.get("absorb_selected_streak", 0)
                        if streak >= 2:
                            absorb_streak_gte_2_count += 1
                        if streak > absorb_max_streak:
                            absorb_max_streak = streak

                        # Collect samples
                        if len(absorb_samples) < 25:
                            attacker_sp = "Unknown"
                            if len(our_active) > slot_index and our_active[slot_index]:
                                attacker_sp = our_active[slot_index].get("species", "Unknown")
                            absorb_samples.append({
                                "battle_tag": battle_tag,
                                "turn": turn_data.get("turn"),
                                "won": is_win,
                                "attacker": attacker_sp,
                                "move": slot.get("absorb_selected_move_id") or slot.get("action", ""),
                                "via_redirection": is_redirected,
                                "intended_target": slot.get("absorb_intended_target_species") or slot.get("ability_blocked_target_species") or slot.get("target_species") or "",
                                "intended_ability": slot.get("absorb_intended_target_ability") or slot.get("ability_blocked_target_ability") or "",
                                "effective_target": slot.get("absorb_effective_target_species") or slot.get("ability_blocked_target_species") or slot.get("target_species") or "",
                                "effective_ability": slot.get("absorb_effective_target_ability") or slot.get("ability_blocked_target_ability") or "",
                                "selected_canonical_score": float(slot.get("absorb_selected_score") or 0.0),
                                "best_alt_move": slot.get("absorb_best_safe_alternative_move") or "",
                                "best_alt_target": slot.get("absorb_best_safe_alternative_target") or "",
                                "best_alt_canonical_score": float(slot.get("absorb_best_safe_alternative_score") or 0.0),
                                "forced": slot.get("absorb_selection_forced", False),
                                "avoidable": slot.get("avoidable_absorb_error", False),
                                "productive_partial": slot.get("productive_partial_absorb_spread", False),
                                "streak": streak,
                                "reason": reason_val,
                                "classification": classification
                            })
                if opp_actions.get("opponent_ability_error"):
                    ability_reports["opp_ability_immune_move_selected"] += 1
                if opp_actions.get("opponent_ground_into_levitate"):
                    ability_reports["opp_ground_into_levitate_selected"] += 1

                # 1. missed_ko
                # expected_ko == True but actual_ko == False, OR opponent survived below 20%
                for slot in (slot_0, slot_1):
                    if slot.get("outcome_known"):
                        if slot.get("expected_ko") and not slot.get("actual_ko"):
                            triggered_in_battle.add(1)
                        if slot.get("opponent_survived_below_20"):
                            triggered_in_battle.add(1)

                # 2. failed_to_target_low_hp
                # opponent HP <= 35% existed, selected actions did not target that opponent, and no KO secured
                low_hp_opponents = []
                for opp in opp_active:
                    if opp and opp.get("hp") is not None and opp["hp"] <= 0.35 and opp["hp"] > 0:
                        low_hp_opponents.append(opp["species"])
                if low_hp_opponents:
                    targeted_any = False
                    for slot in (slot_0, slot_1):
                        if slot.get("target_species") in low_hp_opponents:
                            targeted_any = True
                    no_ko = (slot_0.get("actual_ko") != True and slot_1.get("actual_ko") != True)
                    if not targeted_any and no_ko:
                        triggered_in_battle.add(2)

                # 3. bad_double_target
                # both slots targeted same opponent, and one was expected to KO or actually KOed
                if turn_data.get("both_slots_targeted_same_opp"):
                    if slot_0.get("expected_ko") or slot_0.get("actual_ko") or slot_1.get("expected_ko") or slot_1.get("actual_ko"):
                        if slot_0.get("outcome_known") and slot_1.get("outcome_known"):
                            triggered_in_battle.add(3)

                # 4. underused_spread
                # spread move was available, both opponents active, selected was single-target, best spread score was close (gap <= 30)
                opps_count = sum(1 for opp in opp_active if opp and opp.get("hp", 0) > 0)
                if opps_count == 2:
                    if not slot_0.get("action_types", {}).get("spread") and not slot_1.get("action_types", {}).get("spread"):
                        if slot_0.get("spread_available") or slot_1.get("spread_available"):
                            close_0 = (slot_0.get("spread_available") and
                                       slot_0.get("best_spread_score") is not None and
                                       slot_0.get("selected_score", 0.0) - slot_0.get("best_spread_score", 0.0) <= 30.0)
                            close_1 = (slot_1.get("spread_available") and
                                       slot_1.get("best_spread_score") is not None and
                                       slot_1.get("selected_score", 0.0) - slot_1.get("best_spread_score", 0.0) <= 30.0)
                            if close_0 or close_1:
                                triggered_in_battle.add(4)

                # 5. bad_protect
                # bot used Protect, no opponent targeted that slot, and ally did not secure KO or high damage (damage >= 0.30)
                for idx, (slot, other) in enumerate([(slot_0, slot_1), (slot_1, slot_0)]):
                    if slot.get("action_types", {}).get("protect") and slot.get("outcome_known"):
                        if not slot.get("was_targeted"):
                            ally_did_good = (other.get("actual_ko") or
                                             (other.get("actual_damage") is not None and other["actual_damage"] >= 0.30))
                            if not ally_did_good:
                                triggered_in_battle.add(5)

                # 6. missed_protect
                # active HP < 35%, did not use Protect, and active fainted
                for idx, slot in enumerate((slot_0, slot_1)):
                    mon = our_active[idx]
                    if mon and mon.get("hp") is not None and mon["hp"] < 0.35 and mon["hp"] > 0:
                        if not slot.get("action_types", {}).get("protect"):
                            if slot.get("outcome_known") and slot.get("our_mon_fainted"):
                                triggered_in_battle.add(6)

                # 7. bad_status_move
                # status move selected while damaging KO was available
                for slot in (slot_0, slot_1):
                    if slot.get("action_types", {}).get("status"):
                        if slot.get("best_ko_score") is not None:
                            triggered_in_battle.add(7)

                # 8. speed_priority_loss
                # active fainted before moving, or opponent moved first/used priority and KOed us
                for slot in (slot_0, slot_1):
                    if slot.get("outcome_known"):
                        if slot.get("fainted_before_moving"):
                            triggered_in_battle.add(8)
                        elif slot.get("our_mon_fainted") and (opp_actions.get("opponent_moved_before_us") or opp_actions.get("opponent_used_priority")):
                            triggered_in_battle.add(8)

                # 9. switch_mistake
                # switch selected while active had a move that could KO
                for slot in (slot_0, slot_1):
                    if slot.get("action_types", {}).get("switch"):
                        if slot.get("best_ko_score") is not None:
                            triggered_in_battle.add(9)

                # 10. damage_estimate_error
                # estimated damage and actual damage differ by > 0.25 HP fraction
                for slot in (slot_0, slot_1):
                    if slot.get("outcome_known"):
                        est = slot.get("expected_damage")
                        act = slot.get("actual_damage")
                        if est is not None and act is not None:
                            if abs(est - act) > 0.25:
                                triggered_in_battle.add(10)

                # 11. zero_effectiveness_move_selected
                for slot in (slot_0, slot_1):
                    if slot.get("zero_effectiveness_move_selected"):
                        triggered_in_battle.add(11)

                # 12. all_targets_immune_spread_selected
                for slot in (slot_0, slot_1):
                    if slot.get("all_targets_immune_spread_selected"):
                        triggered_in_battle.add(12)

                # 13. self_drop_move_spam
                for slot in (slot_0, slot_1):
                    if slot.get("self_drop_move_spam"):
                        triggered_in_battle.add(13)

                # 14. partial_immune_spread_selected
                for slot in (slot_0, slot_1):
                    if slot.get("partial_immune_spread_selected"):
                        triggered_in_battle.add(14)

                # 15. efficient_partial_spread_selected
                for slot in (slot_0, slot_1):
                    if slot.get("efficient_partial_spread_selected"):
                        triggered_in_battle.add(15)

                # 16. inefficient_partial_spread_selected
                for slot in (slot_0, slot_1):
                    if slot.get("inefficient_partial_spread_selected"):
                        triggered_in_battle.add(16)

                # 17. speed_priority_threat_unanswered
                for slot in (slot_0, slot_1):
                    if slot.get("outcome_known") and slot.get("speed_priority_threatened"):
                        if slot.get("expected_to_faint_before_moving") and slot.get("fainted_before_moving"):
                            triggered_in_battle.add(17)

                # 18. successful_speed_priority_protect
                for slot in (slot_0, slot_1):
                    if slot.get("outcome_known") and slot.get("speed_priority_threatened"):
                        if slot.get("protected_due_to_speed_priority") and not slot.get("our_mon_fainted"):
                            triggered_in_battle.add(18)

                # 19. bad_speed_priority_protect
                for slot in (slot_0, slot_1):
                    if slot.get("outcome_known") and slot.get("protected_due_to_speed_priority"):
                        if slot.get("was_targeted") == False:
                            triggered_in_battle.add(19)

                # 20. order_aware_overkill
                if turn_data.get("order_aware_overkill_penalty_applied"):
                    triggered_in_battle.add(20)

                # Refined Phase 6.2.1 patterns:
                for idx, (slot, other) in enumerate([(slot_0, slot_1), (slot_1, slot_0)]):
                    if not slot.get("outcome_known"):
                        continue
                    
                    # 21. detected_speed_priority_threat
                    if slot.get("speed_priority_threatened"):
                        triggered_in_battle.add(21)
                        
                        # 22. true_unanswered_speed_priority_threat
                        is_protect = slot.get("action_types", {}).get("protect")
                        is_switch = slot.get("action_types", {}).get("switch")
                        if not is_protect and not is_switch:
                            # Strict conditions to NOT count as unanswered:
                            not_unanswered = (
                                slot.get("fainted_before_moving") == False or
                                slot.get("actual_ko") == True or
                                (slot.get("action_types", {}).get("spread") and slot.get("actual_damage") is not None and slot.get("actual_damage") >= 0.20) or
                                slot.get("protect_like_available") == False or
                                slot.get("switch_available") == False or
                                slot.get("only_conditional_priority") == True or
                                slot.get("was_targeted") == False or
                                slot.get("active_moved_before_threat") == True
                            )
                            if not not_unanswered:
                                triggered_in_battle.add(22)
                                
                            # 23. productive_attack_under_threat
                            is_attack = not is_protect and not is_switch and slot.get("action") and "pass" not in slot.get("action", "")
                            if is_attack:
                                is_productive = (
                                    slot.get("actual_ko") == True or
                                    (slot.get("action_types", {}).get("spread") and slot.get("actual_damage") is not None and slot.get("actual_damage") > 0.0) or
                                    (slot.get("actual_damage") is not None and slot.get("actual_damage") >= 0.30)
                                )
                                if is_productive:
                                    triggered_in_battle.add(23)
                                    
                        # 24. false_positive_speed_priority_threat
                        if slot.get("was_targeted") == False or slot.get("our_mon_fainted") == False:
                            triggered_in_battle.add(24)

                    # 25. bad_speed_priority_protect_refined
                    if slot.get("protected_due_to_speed_priority") and slot.get("action_types", {}).get("protect"):
                        if slot.get("was_targeted") == False:
                            ally_did_good = (other.get("actual_ko") or (other.get("actual_damage") is not None and other["actual_damage"] >= 0.30))
                            if not ally_did_good:
                                is_stalling = slot.get("stalling_field_condition", False)
                                if not is_stalling:
                                    triggered_in_battle.add(25)

                # 26. ability_immune_move_selected
                for slot in (slot_0, slot_1):
                    if slot.get("ability_immune_move_selected"):
                        triggered_in_battle.add(26)

                # 27. ground_into_levitate_selected
                for slot in (slot_0, slot_1):
                    if slot.get("ground_into_levitate_selected"):
                        triggered_in_battle.add(27)

                # 28. ability_hard_block_avoided
                for slot in (slot_0, slot_1):
                    if slot.get("ability_hard_block_avoided"):
                        triggered_in_battle.add(28)

                # 29. ally_ability_safe_spread
                for slot in (slot_0, slot_1):
                    if slot.get("ally_ability_safe_spread"):
                        triggered_in_battle.add(29)

                # 30. ability_redirection_avoided
                for slot in (slot_0, slot_1):
                    if slot.get("ability_redirection_avoided"):
                        triggered_in_battle.add(30)

                # 31. partial_ability_immune_spread_selected
                for slot in (slot_0, slot_1):
                    if slot.get("partial_ability_immune_spread_selected"):
                        triggered_in_battle.add(31)


            # Aggregate battle-level pattern counts
            for p_id in triggered_in_battle:
                if is_win:
                    pattern_wins[p_id] += 1
                    if len(pattern_win_samples[p_id]) < 3:
                        pattern_win_samples[p_id].append(battle_tag)
                else:
                    pattern_losses[p_id] += 1
                    if len(pattern_loss_samples[p_id]) < 3:
                        pattern_loss_samples[p_id].append(battle_tag)

    win_rate = (wins / total_battles) * 100 if total_battles > 0 else 0
    avg_turns = total_turns / total_battles if total_battles > 0 else 0
    unknown_outcome_rate = ((total_turns - total_turns_with_known_outcome) / total_turns * 100) if total_turns > 0 else 0

    print("======================================================================")
    print("  Double Battle Decision Audit Analysis Results")
    print("======================================================================")
    print(f"  Total Battles Analyzed : {total_battles}")
    print(f"  Wins / Losses          : {wins} / {losses}")
    print(f"  Win Rate               : {win_rate:.2f}%")
    print(f"  Average Turns/Battle   : {avg_turns:.2f}")
    print(f"  Unknown Outcome Rate   : {unknown_outcome_rate:.2f}%")
    print()

    # Sort loss patterns by frequency in losses
    sorted_patterns = sorted(pattern_losses.keys(), key=lambda k: pattern_losses[k], reverse=True)

    print(f"  {'Rank':<4} {'Pattern Name':<28} {'Loss Freq':<10} {'Loss %':<8} {'Win Freq':<9} {'Win %':<7} {'L/W Ratio':<9}")
    print("  " + "-" * 82)

    for rank, p_id in enumerate(sorted_patterns, 1):
        name = pattern_names[p_id]
        l_cnt = pattern_losses[p_id]
        l_pct = (l_cnt / losses * 100) if losses > 0 else 0
        w_cnt = pattern_wins[p_id]
        w_pct = (w_cnt / wins * 100) if wins > 0 else 0
        ratio = f"{l_cnt / max(1, w_cnt):.2f}"
        
        print(f"  {rank:<4} {name:<28} {l_cnt:<10} {l_pct:>6.1f}% {w_cnt:<9} {w_pct:>5.1f}% {ratio:>9}")

    print()
    print("  Pattern Samples in Losses:")
    print("  " + "-" * 40)
    for p_id in sorted_patterns:
        name = pattern_names[p_id]
        samples = pattern_loss_samples[p_id]
        samples_str = ", ".join(samples) if samples else "None"
        print(f"  - {name:<28}: {samples_str}")

    print()
    # Recommended Next Tuning Target Heuristics
    print("  Analysis & Recommendation:")
    print("  " + "-" * 40)
    
    top_pattern_id = sorted_patterns[0]
    top_pattern_name = pattern_names[top_pattern_id]
    top_pattern_pct = (pattern_losses[top_pattern_id] / losses * 100) if losses > 0 else 0

    print(f"  * The most frequent issue in losses is: {top_pattern_name} ({top_pattern_pct:.1f}% of lost battles).")
    
    if top_pattern_name == "missed_ko":
        print("    Recommendation: Refine damage/KO threshold checks or account for opponent healing/defensive abilities.")
    elif top_pattern_name == "failed_to_target_low_hp":
        print("    Recommendation: Increase targeting focus weight on opponents below 35% HP to finish them off.")
    elif top_pattern_name == "bad_double_target":
        print("    Recommendation: Tighten the overkill penalty checks in joint scoring to prevent wasting move slots on low-HP targets.")
    elif top_pattern_name == "underused_spread":
        print("    Recommendation: Re-evaluate the spread score penalty/multiplier so the bot is less hesitant to use spread moves when both opponents are out.")
    elif top_pattern_name == "bad_protect":
        print("    Recommendation: Refine the threat-detection gating for Protect so the bot only uses it when actually targeted by dangerous moves.")
    elif top_pattern_name == "missed_protect":
        print("    Recommendation: Enable a lightweight speed-aware Protect heuristic when our active Pokemon is at critical HP and can be outrun.")
    elif top_pattern_name == "bad_status_move":
        print("    Recommendation: Always prioritize damaging KO choices over status move checks.")
    elif top_pattern_name == "speed_priority_loss":
        print("    Recommendation: Implement speed-tier awareness and priority move modeling in threat estimation so the bot doesn't stay in to faint before moving.")
    elif top_pattern_name == "switch_mistake":
        print("    Recommendation: Add a check to prevent switching when active can secure a KO, and evaluate switch-in threats.")
    elif top_pattern_name == "damage_estimate_error":
        print("    Recommendation: Correct stat calculation boosts or item modifiers (such as Choice items or Life Orb) in get_expected_damage.")

    # Extra reporting for partial spread immunity cases
    partial_spread_cases = []
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    battle = json.loads(line)
                except Exception:
                    continue
                is_win = battle.get("won", False)
                battle_tag = battle.get("battle_tag", "Unknown")
                for turn_data in battle.get("audit_turns", []):
                    for slot_key in ("slot_0", "slot_1"):
                        slot = turn_data.get(slot_key, {})
                        if slot.get("partial_immune_spread_selected"):
                            partial_spread_cases.append({
                                "battle_tag": battle_tag,
                                "is_win": is_win,
                                "turn": turn_data.get("turn", 0),
                                "move": slot.get("action", ""),
                                "immune_targets": slot.get("immune_target_species", []),
                                "damaged_targets": slot.get("damaged_target_species", []),
                                "best_single": slot.get("best_single_target_alternative", ""),
                                "is_efficient": slot.get("efficient_partial_spread_selected", False)
                            })

    if partial_spread_cases:
        print("\n======================================================================")
        print(f"  Partial Spread Immunity Cases Report ({len(partial_spread_cases)} total)")
        print("======================================================================")
        for idx, case in enumerate(partial_spread_cases[:10], 1):
            outcome = "Win" if case["is_win"] else "Loss"
            eff_str = "Efficient" if case["is_efficient"] else "Inefficient"
            print(f"  {idx}. Battle: {case['battle_tag']} ({outcome}) | Turn: {case['turn']} | {eff_str}")
            print(f"     Move: {case['move']}")
            print(f"     Immune Target(s): {', '.join(case['immune_targets'])}")
            print(f"     Damaged Target(s): {', '.join(case['damaged_targets'])}")
            print(f"     Best Single-Target Alternative: {case['best_single']}")
            print()
        if len(partial_spread_cases) > 10:
            print(f"  ... and {len(partial_spread_cases) - 10} more cases.")

    # Extra reporting for unanswered speed priority threats in lost battles
    unanswered_threat_cases = []
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    battle = json.loads(line)
                except Exception:
                    continue
                is_win = battle.get("won", False)
                if not is_win: # only lost battles
                    battle_tag = battle.get("battle_tag", "Unknown")
                    for turn_data in battle.get("audit_turns", []):
                        for slot_idx, slot_key in enumerate(("slot_0", "slot_1")):
                            slot = turn_data.get(slot_key, {})
                            if slot.get("speed_priority_threatened") and slot.get("expected_to_faint_before_moving") and slot.get("fainted_before_moving"):
                                our_species = "Unknown"
                                our_hp = 1.0
                                our_actives = turn_data.get("our_active", [])
                                if len(our_actives) > slot_idx and our_actives[slot_idx]:
                                    our_species = our_actives[slot_idx].get("species", "Unknown")
                                    our_hp = our_actives[slot_idx].get("hp", 1.0)
                                unanswered_threat_cases.append({
                                    "battle_tag": battle_tag,
                                    "turn": turn_data.get("turn", 0),
                                    "species": our_species,
                                    "hp": our_hp,
                                    "action": slot.get("action", ""),
                                    "faster_opponents": slot.get("faster_opponents", []),
                                    "priority_opponents": slot.get("priority_opponents", [])
                                })

    if unanswered_threat_cases:
        print("\n======================================================================")
        print(f"  Unanswered Speed/Priority Threats in Lost Battles ({len(unanswered_threat_cases)} total)")
        print("======================================================================")
        for idx, case in enumerate(unanswered_threat_cases[:10], 1):
            opps = ", ".join(case["faster_opponents"] + case["priority_opponents"])
            print(f"  {idx}. Battle: {case['battle_tag']} | Turn: {case['turn']}")
            print(f"     Our Pokemon: {case['species']} (HP: {case['hp']:.2f})")
            print(f"     Chosen Action: {case['action']}")
            print(f"     Threatening Opponent(s): {opps}")
            print()
        if len(unanswered_threat_cases) > 10:
            print(f"  ... and {len(unanswered_threat_cases) - 10} more cases.")

    # Extra reporting for refined bad protect cases
    bad_protect_refined_cases = []
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    battle = json.loads(line)
                except Exception:
                    continue
                is_win = battle.get("won", False)
                battle_tag = battle.get("battle_tag", "Unknown")
                for turn_data in battle.get("audit_turns", []):
                    for slot_idx, slot_key in enumerate(("slot_0", "slot_1")):
                        slot = turn_data.get(slot_key, {})
                        other = turn_data.get("slot_1" if slot_key == "slot_0" else "slot_0", {})
                        
                        if slot.get("protected_due_to_speed_priority") and slot.get("action_types", {}).get("protect"):
                            our_species = "Unknown"
                            our_actives = turn_data.get("our_active", [])
                            if len(our_actives) > slot_idx and our_actives[slot_idx]:
                                our_species = our_actives[slot_idx].get("species", "Unknown")
                                
                            opps = [opp.get("species", "Unknown") for opp in turn_data.get("opp_active", []) if opp]
                            
                            classification = "bad"
                            if slot.get("was_targeted") == True:
                                classification = "good"
                            else:
                                ally_did_good = (other.get("actual_ko") or (other.get("actual_damage") is not None and other["actual_damage"] >= 0.30))
                                if ally_did_good:
                                    classification = "good"
                                elif slot.get("stalling_field_condition", False):
                                    classification = "neutral"
                                    
                            bad_protect_refined_cases.append({
                                "battle_tag": battle_tag,
                                "turn": turn_data.get("turn", 0),
                                "species": our_species,
                                "opponents": opps,
                                "targeted": slot.get("was_targeted"),
                                "ally_action": other.get("action", ""),
                                "ally_damage": other.get("actual_damage", 0.0),
                                "ally_ko": other.get("actual_ko", False),
                                "classification": classification
                            })

    if bad_protect_refined_cases:
        print("\n======================================================================")
        print(f"  Refined Speed/Priority Protect Cases Report ({len(bad_protect_refined_cases)} total)")
        print("======================================================================")
        for idx, case in enumerate(bad_protect_refined_cases[:10], 1):
            opps_str = ", ".join(case["opponents"])
            target_str = "Yes" if case["targeted"] else "No"
            dmg_val = f"{case['ally_damage']:.2f}" if case['ally_damage'] is not None else "None"
            ally_val = f"KO={case['ally_ko']}, DMG={dmg_val}" if case['ally_action'] else "None"
            print(f"  {idx}. Battle: {case['battle_tag']} | Turn: {case['turn']}")
            print(f"     Protected Pokemon: {case['species']}")
            print(f"     Opponent Pair    : {opps_str}")
            print(f"     Reason for Prot  : Speed/Priority Threatened")
            print(f"     Was Targeted     : {target_str}")
            print(f"     Ally Action/Value: {case['ally_action']} ({ally_val})")
            print(f"     Classification   : {case['classification'].upper()}")
            print()
        if len(bad_protect_refined_cases) > 10:
            print(f"  ... and {len(bad_protect_refined_cases) - 10} more cases.")

    print("======================================================================")

    # Special report: Ability Hard Safety Report
    print("\n======================================================================")
    print("  Ability Hard Safety Report")
    print("======================================================================")
    print(f"  Ground into Levitate selected count:")
    print(f"    - Our Bot : {ability_reports['our_ground_into_levitate_selected']}")
    print(f"    - Opponent: {ability_reports['opp_ground_into_levitate_selected']}")
    print(f"  Ability immune move selected count:")
    print(f"    - Our Bot : {ability_reports['our_ability_immune_move_selected']}")
    print(f"    - Opponent: {ability_reports['opp_ability_immune_move_selected']}")
    print(f"  Ability hard blocks avoided count   : {ability_reports['ability_hard_blocks_avoided']}")
    print(f"    - Ground blocks avoided           : {ability_reports['ground_block_avoided']}")
    print(f"    - Absorb blocks avoided           : {ability_reports['absorb_block_avoided']}")
    print(f"    - Redirection avoided             : {ability_reports['ability_redirection_avoided']}")
    print(f"    - Optional blocks avoided         : {ability_reports['optional_block_avoided']}")
    print(f"  Ally ability-safe spread count      : {ability_reports['ally_ability_safe_spread']}")
    print(f"  Selected immune single-target count : {ability_reports['immune_singletarget_selected']}")
    print(f"  Selected partial ability spread count: {ability_reports['partial_ability_immune_spread_selected']}")
    print("\n  Counts by battle outcome:")
    for metric, counts in ability_report_outcomes.items():
        print(f"    - {metric}: wins={counts['wins']} losses={counts['losses']}")
    if ability_cases:
        print("\n  Sample cases:")
        for case in ability_cases[:10]:
            outcome = "win" if case["won"] else "loss"
            print(
                f"    - {case['battle_tag']} turn {case['turn']} ({outcome}) | "
                f"{case['attacker']} | {case['move']} | target={case['target']} "
                f"ability={case['ability']} reason={case['reason']} "
                f"[{case['metric']}]"
            )
    print("======================================================================")

    # Phase 6.3.2: Absorb Error Qualification Report
    n_battles = total_battles
    per100 = (100.0 / n_battles) if n_battles > 0 else 0.0
    print("\n======================================================================")
    print("  Absorb Error Qualification Report (Phase 6.3.2a)")
    print("======================================================================")
    print(f"  Battles analyzed            : {n_battles}")
    print()
    print("  Action-level counts:")
    print(f"    absorb_selected_action_count                 : {absorb_selected_count}  ({absorb_selected_count * per100:.2f} per 100 battles)")
    print(f"    direct_absorb_selected_count                 : {direct_absorb_selected_count}")
    print(f"    redirected_absorb_selected_count             : {redirected_absorb_selected_count}")
    print(f"    absorb_avoidable_action_count                : {absorb_avoidable_count}  ({absorb_avoidable_count * per100:.2f} per 100 battles)")
    print(f"    direct_avoidable_absorb_count                : {direct_avoidable_absorb_count}")
    print(f"    redirected_avoidable_absorb_count            : {redirected_avoidable_absorb_count}")
    print(f"    forced_no_useful_scored_alt_action_count     : {forced_no_useful_scored_alt_action_count}  ({forced_no_useful_scored_alt_action_count * per100:.2f} per 100 battles)")
    print(f"    avoidable_safe_damage_alt_action_count       : {avoidable_safe_damage_alt_action_count}  ({avoidable_safe_damage_alt_action_count * per100:.2f} per 100 battles)")
    print(f"    productive_partial_spread_action_count       : {productive_partial_spread_action_count}  ({productive_partial_spread_action_count * per100:.2f} per 100 battles)")
    print(f"    other_useful_scored_alt_action_count         : {other_useful_scored_alt_action_count}  ({other_useful_scored_alt_action_count * per100:.2f} per 100 battles)")
    print(f"    unclassified_action_count                    : {unclassified_action_count}  ({unclassified_action_count * per100:.2f} per 100 battles)")
    
    classified_total = (forced_no_useful_scored_alt_action_count + 
                        avoidable_safe_damage_alt_action_count + 
                        productive_partial_spread_action_count + 
                        other_useful_scored_alt_action_count + 
                        unclassified_action_count)
    consistency = "PASS" if classified_total == absorb_selected_count else "FAIL"
    print(f"    classified_total == selected_total           : {consistency} (classified: {classified_total}, selected: {absorb_selected_count})")
    print(f"    classified_total == selected_total: {consistency}")
    print(f"    Repeat streaks >= 2 (actions)                : {absorb_streak_gte_2_count}")
    print(f"    Maximum repeat streak                        : {absorb_max_streak}")
    print()
    print("  Battle-level win/loss (battles containing at least one absorb event):")
    print(f"    battles_with_absorb_selected_win  : {len(_battle_tags_with_absorb_selected_win)}")
    print(f"    battles_with_absorb_selected_loss : {len(_battle_tags_with_absorb_selected_loss)}")
    print(f"    battles_with_absorb_avoidable_win  : {len(_battle_tags_with_avoidable_win)}")
    print(f"    battles_with_absorb_avoidable_loss : {len(_battle_tags_with_avoidable_loss)}")
    print(f"    battles_with_forced_win           : {len(_battle_tags_with_forced_win)}")
    print(f"    battles_with_forced_loss          : {len(_battle_tags_with_forced_loss)}")
    print(f"    battles_with_productive_spread_win: {len(_battle_tags_with_productive_win)}")
    print(f"    battles_with_productive_spread_loss:{len(_battle_tags_with_productive_loss)}")
    print()
    print("  Action-level outcome split (every absorb action counted individually):")
    print(f"    Selected          : wins={absorb_outcome_split['selected']['wins']} losses={absorb_outcome_split['selected']['losses']}")
    print(f"    Forced            : wins={absorb_outcome_split['forced']['wins']} losses={absorb_outcome_split['forced']['losses']}")
    print(f"    Avoidable         : wins={absorb_outcome_split['avoidable']['wins']} losses={absorb_outcome_split['avoidable']['losses']}")
    print(f"    Productive Spread : wins={absorb_outcome_split['productive_partial']['wins']} losses={absorb_outcome_split['productive_partial']['losses']}")
    print()
    print("  Reason split:")
    for r, c in sorted(absorb_reason_split.items(), key=lambda x: x[1], reverse=True):
        print(f"    - {r}: {c}")
    if absorb_samples:
        print("\n  Sample cases (up to 10):")
        for idx, s in enumerate(absorb_samples[:10], 1):
            outcome = "win" if s["won"] else "loss"
            class_str = s["classification"]
            direction = "REDIRECTED" if s.get("via_redirection") else "DIRECT"
            print(f"    {idx}. [{class_str}][{direction}] Battle: {s['battle_tag']} turn {s['turn']} ({outcome}) | Streak: {s['streak']}")
            intended = s.get('intended_target', s.get('target', ''))
            effective = s.get('effective_target', s.get('target', ''))
            int_ab = s.get('intended_ability', s.get('ability', ''))
            eff_ab = s.get('effective_ability', s.get('ability', ''))
            print(f"       Move: {s['move']} -> intended={intended} (ab={int_ab}) effective={effective} (ab={eff_ab})")
            print(f"       Selected canonical score: {s.get('selected_canonical_score', s.get('selected_score', 0.0)):.1f} | reason: {s['reason']}")
            if s["best_alt_move"]:
                alt_score = s.get('best_alt_canonical_score', s.get('best_alt_score', 0.0))
                print(f"       Best safe alt: {s['best_alt_move']} -> {s['best_alt_target']} (canonical score: {alt_score:.1f})")
            else:
                print(f"       Best safe alt: None")
    print("======================================================================")

    # Phase 6.3.3: Direct Absorb Safety Report
    print("\n======================================================================")
    print("  Direct Absorb Safety Report (Phase 6.3.3)")
    print("======================================================================")
    print(f"  Battles analyzed                     : {n_battles}")
    print()
    print("  Action-level counts:")
    print(f"    direct_absorb_hard_block_avoided     : {direct_absorb_avoided_count}")
    print(f"    direct_absorb_immune_move_selected   : {direct_absorb_immune_selected_count}")
    print(f"    direct_absorb_only_legal_action      : {direct_absorb_only_legal_count}")
    print(f"    direct_absorb_avoidable_selected     : {direct_absorb_avoidable_selected_count}")
    print()
    print("  Battle-level win/loss:")
    print(f"    battles_with_direct_avoided_win      : {len(_battle_tags_with_direct_avoided_win)}")
    print(f"    battles_with_direct_avoided_loss     : {len(_battle_tags_with_direct_avoided_loss)}")
    print(f"    battles_with_direct_selected_win     : {len(_battle_tags_with_direct_selected_win)}")
    print(f"    battles_with_direct_selected_loss    : {len(_battle_tags_with_direct_selected_loss)}")
    print()
    print("  Reason split for direct absorb immune move selections:")
    for r, c in sorted(direct_absorb_reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"    - {r}: {c}")
    if direct_absorb_samples:
        print("\n  Sample cases (up to 10):")
        for idx, s in enumerate(direct_absorb_samples[:10], 1):
            outcome = "win" if s["won"] else "loss"
            only_legal_str = "ONLY_LEGAL" if s["only_legal"] else "AVOIDABLE"
            print(f"    {idx}. [{only_legal_str}] Battle: {s['battle_tag']} turn {s['turn']} ({outcome})")
            print(f"       Move: {s['move']} -> target={s['target']} (ab={s['ability']})")
            print(f"       Reason: {s['reason']}")
    print("======================================================================")

    # Phase 6.3.6: Known Absorb Hard Safety Report
    print("\n======================================================================")
    print("  Known Absorb Hard Safety Report (Phase 6.3.6)")
    print("======================================================================")
    print(f"  Battles analyzed                     : {n_battles}")
    print()
    print("  Action-level counts:")
    print(f"    direct_known_absorb_move_selected  : {known_absorb_selected_count}")
    print(f"    direct_known_absorb_move_avoided   : {known_absorb_avoided_count}")
    print(f"    direct_known_absorb_repeat_selected: {known_absorb_repeat_selected_count}")
    print(f"    direct_known_absorb_only_legal     : {known_absorb_only_legal_count}")
    print()
    print("  Wins/losses for selected absorb moves:")
    print(f"    wins                               : {_known_absorb_selected_wins}")
    print(f"    losses                             : {known_absorb_selected_losses}")
    print()
    print("  Reason split:")
    for r, c in sorted(known_absorb_reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"    - {r}: {c}")
    if known_absorb_samples:
        print("\n  Sample cases (up to 10):")
        for idx, s in enumerate(known_absorb_samples[:10], 1):
            outcome = "win" if s["won"] else "loss"
            only_legal_str = "ONLY_LEGAL" if s["only_legal"] else "AVOIDABLE"
            print(f"    {idx}. [{only_legal_str}] Battle: {s['battle_tag']} turn {s['turn']} ({outcome})")
            print(f"       Attacker: {s['attacker']} Move: {s['move']} Type: {s.get('move_type', '')}")
            print(f"       Target: {s['target']} Ability: {s['ability']}")
            print(f"       Reason: {s['reason']}")
    print("======================================================================")

    # Phase 6.3.5a: Priority Field Safety Report
    print("\n======================================================================")
    print("  Priority Field Safety Report (Phase 6.3.5a)")
    print("======================================================================")
    print(f"  Battles analyzed                             : {n_battles}")
    print()
    print("  Action-level counts:")
    print(f"    priority_move_block_avoided                : {priority_move_block_avoided_count}")
    print(f"    priority_move_field_blocked                : {priority_move_field_blocked_count}")
    print(f"    priority_move_selected_into_psychic_terrain: {priority_move_selected_into_psychic_terrain_count}")
    print(f"    sucker_punch_selected_into_psychic_terrain : {sucker_punch_selected_into_psychic_terrain_count}")
    print(f"    priority_move_only_legal_action            : {priority_move_only_legal_count}")
    print(f"    priority_move_avoidable_selected           : {priority_move_avoidable_selected_count}")
    print()
    print("  Battle-level win/loss:")
    print(f"    battles_with_priority_avoided_win          : {len(_battle_tags_with_priority_avoided_win)}")
    print(f"    battles_with_priority_avoided_loss         : {len(_battle_tags_with_priority_avoided_loss)}")
    print(f"    battles_with_priority_selected_win         : {len(_battle_tags_with_priority_selected_win)}")
    print(f"    battles_with_priority_selected_loss        : {len(_battle_tags_with_priority_selected_loss)}")
    print()
    print("  Reason split for priority blocked selections:")
    for r, c in sorted(priority_block_reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"    - {r}: {c}")
    print()
    print("  Blocking abilities split:")
    for a, c in sorted(priority_blocking_ability_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"    - {a}: {c}")
    if priority_samples:
        print("\n  Sample cases (up to 10):")
        for idx, s in enumerate(priority_samples[:10], 1):
            outcome = "win" if s["won"] else "loss"
            only_legal_str = "ONLY_LEGAL" if s["only_legal"] else "AVOIDABLE"
            grounded_str = "grounded" if s["grounded"] else "ungrounded"
            ab_str = f" (blocking_ability={s['blocking_ability']} source={s['blocking_source']})" if s['blocking_ability'] else ""
            print(f"    {idx}. [{only_legal_str}] Battle: {s['battle_tag']} turn {s['turn']} ({outcome})")
            print(f"       Move: {s['move']} -> target={s['target']} ({grounded_str}){ab_str}")
            print(f"       Reason: {s['reason']}")
    print("======================================================================")



    # ===== Phase 6.4: Switch Candidate Safety Report =====
    print("\n" + "=" * 70)
    print("  Switch Candidate Safety Report (Phase 6.4)")
    print("=" * 70)

    forced_switch_count = 0
    final_unsafe_count = 0
    legal_safer_joint_count = 0
    avoided_count = 0
    selection_changed_count = 0
    selected_double_threat_count = 0
    severe_neg_boost_switch_count = 0
    severe_neg_boost_non_switch_count = 0
    eligible_neg_boost_count = 0
    off_drop_count = 0
    def_drop_count = 0
    spd_drop_count = 0
    unique_eligible_neg_battles = set()
    samples = []

    for filepath_line in filepath if isinstance(filepath, list) else [filepath]:
        if not os.path.exists(filepath_line):
            continue
        with open(filepath_line, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    battle = json.loads(line)
                    battle_tag = battle.get("battle_tag", "")
                    won = battle.get("won", False)
                    for turn in battle.get("audit_turns", []):
                        turn_num = turn.get("turn", 0)
                        for slot_key in ("slot_0", "slot_1"):
                            slot = turn.get(slot_key, {})
                            if not slot:
                                continue
                            is_forced = bool(slot.get("forced_switch"))
                            is_final_unsafe = bool(slot.get("final_unsafe_switch_selected"))
                            is_legal_safer = bool(slot.get("legal_safer_joint_switch_available"))
                            is_avoided = bool(slot.get("unsafe_switch_avoided_by_type_safety"))
                            is_sel_changed = bool(slot.get("joint_switch_selection_changed_by_type_safety"))
                            is_dt = bool(slot.get("final_double_threat_switch_selected"))
                            is_eligible_neg = bool(slot.get("negative_boost_decision_eligible"))
                            is_off_drop = bool(slot.get("negative_boost_relevant_offensive_drop"))
                            is_def_drop = bool(slot.get("negative_boost_defensive_drop"))
                            is_spd_drop = bool(slot.get("negative_boost_speed_drop"))
                            is_sev_sw = bool(slot.get("neg_boost_severe_negative_boost")) and bool(slot.get("action_types", {}).get("switch"))
                            is_sev_nsw = bool(slot.get("neg_boost_severe_negative_boost")) and not bool(slot.get("action_types", {}).get("switch"))

                            if is_forced:
                                forced_switch_count += 1
                            if is_final_unsafe:
                                final_unsafe_count += 1
                            if is_legal_safer:
                                legal_safer_joint_count += 1
                            if is_avoided:
                                avoided_count += 1
                            if is_sel_changed:
                                selection_changed_count += 1
                            if is_dt:
                                selected_double_threat_count += 1
                            if is_sev_sw:
                                severe_neg_boost_switch_count += 1
                            if is_sev_nsw:
                                severe_neg_boost_non_switch_count += 1
                            if is_eligible_neg:
                                eligible_neg_boost_count += 1
                                unique_eligible_neg_battles.add(battle_tag)
                            if is_off_drop:
                                off_drop_count += 1
                            if is_def_drop:
                                def_drop_count += 1
                            if is_spd_drop:
                                spd_drop_count += 1

                            if is_final_unsafe or is_avoided:
                                sp = slot.get("selected_switch_species", "")
                                st = slot.get("selected_switch_types", "")
                                wm = slot.get("selected_switch_worst_multiplier", 1.0)
                                hp = slot.get("selected_switch_hp_fraction", 1.0)
                                bs = slot.get("best_safe_switch_species", "")
                                outcome = "win" if won else "loss"
                                tag_str = "AVOIDED" if is_avoided else "UNSAFE_SELECTED"
                                samples.append({
                                    "battle_tag": battle_tag, "turn": turn_num,
                                    "outcome": outcome, "tag": tag_str,
                                    "species": sp, "types": st, "worst_mult": wm,
                                    "hp": hp, "best_safe": bs,
                                })
                except Exception:
                    continue

    print(f"  forced-switch count                     : {forced_switch_count}")
    print(f"  final unsafe switch selected            : {final_unsafe_count}")
    print(f"  legal safer joint switch available      : {legal_safer_joint_count}")
    print(f"  unsafe avoided by type-safety           : {avoided_count}")
    print(f"  joint selection changed                 : {selection_changed_count}")
    print(f"  selected double-threat count            : {selected_double_threat_count}")
    print(f"  eligible negative-boost decisions       : {eligible_neg_boost_count}")
    print(f"    unique battles with eligible neg-boost: {len(unique_eligible_neg_battles)}")
    print(f"    offensive drops                       : {off_drop_count}")
    print(f"    defensive drops                       : {def_drop_count}")
    print(f"    speed drops                           : {spd_drop_count}")
    print(f"  severe negative-boost switch count      : {severe_neg_boost_switch_count}")
    print(f"  severe negative-boost non-switch count  : {severe_neg_boost_non_switch_count}")
    print()
    print("  Sample cases (up to 10):")
    for idx, s in enumerate(samples[:10], 1):
        print(f"    {idx}. [{s['tag']}] Battle: {s['battle_tag']} turn {s['turn']} ({s['outcome']})")
        print(f"       Species: {s['species']} Types: {s['types']} WorstMult: {s['worst_mult']:.2f} HP: {s['hp']:.2f}")
        if s['best_safe']:
            print(f"       Best Safe Alternative: {s['best_safe']}")
    print("=" * 70)


    # ===== Phase 6.4.4: Forced Switch Replacement Safety Report =====
    print("\n" + "=" * 70)
    print("  Forced Switch Replacement Safety Report (Phase 6.4.4)")
    print("=" * 70)

    fs_count = 0
    fs_safety_on_count = 0
    fs_selected_dt_count = 0
    fs_selected_qw_count = 0
    fs_sel_changed_count = 0
    fs_fallback_count = 0
    fs_score_gap_sum = 0.0
    fs_score_gap_count = 0
    fs_wins = 0
    fs_losses = 0
    fs_samples = []

    for filepath_line in filepath if isinstance(filepath, list) else [filepath]:
        if not os.path.exists(filepath_line):
            continue
        with open(filepath_line, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    battle = json.loads(line)
                    battle_tag = battle.get("battle_tag", "")
                    won = battle.get("won", False)
                    for turn in battle.get("audit_turns", []):
                        turn_num = turn.get("turn", 0)
                        for slot_key in ("slot_0", "slot_1"):
                            slot = turn.get(slot_key, {})
                            if not slot:
                                continue
                            if not bool(slot.get("forced_switch")):
                                continue
                            fs_count += 1
                            if won:
                                fs_wins += 1
                            else:
                                fs_losses += 1

                            if bool(slot.get("forced_switch_safety_enabled")):
                                fs_safety_on_count += 1
                            if bool(slot.get("forced_switch_selected_double_threat")):
                                fs_selected_dt_count += 1
                            if bool(slot.get("forced_switch_selected_quad_weak")):
                                fs_selected_qw_count += 1
                            if bool(slot.get("forced_switch_safety_selection_changed")):
                                fs_sel_changed_count += 1
                            if bool(slot.get("forced_switch_order_fallback_used")):
                                fs_fallback_count += 1

                            sel_score = float(slot.get("forced_switch_selected_safety_score", 0.0))
                            best_score = float(slot.get("forced_switch_best_safety_score", 0.0))
                            gap = best_score - sel_score
                            if gap != 0.0:
                                fs_score_gap_sum += gap
                                fs_score_gap_count += 1

                            if len(fs_samples) < 10:
                                fs_samples.append({
                                    "battle_tag": battle_tag,
                                    "turn": turn_num,
                                    "slot": slot_key,
                                    "outcome": "win" if won else "loss",
                                    "selected": slot.get("forced_switch_selected_species", ""),
                                    "best": slot.get("forced_switch_best_safety_species", ""),
                                    "sel_score": sel_score,
                                    "best_score": best_score,
                                    "candidate_count": slot.get("forced_switch_candidate_count", 0),
                                    "reason": slot.get("forced_switch_reason", ""),
                                    "double_threat": bool(slot.get("forced_switch_selected_double_threat")),
                                    "quad_weak": bool(slot.get("forced_switch_selected_quad_weak")),
                                })
                except Exception:
                    continue

    print(f"  forced switch count                     : {fs_count}")
    print(f"    wins / losses                         : {fs_wins} / {fs_losses}")
    print(f"  safety enabled count                    : {fs_safety_on_count}")
    print(f"  selected double-threat count            : {fs_selected_dt_count}")
    print(f"  selected quad-weak count                : {fs_selected_qw_count}")
    print(f"  safety selection changed count          : {fs_sel_changed_count}")
    print(f"  fallback used count                     : {fs_fallback_count}")
    if fs_score_gap_count > 0:
        print(f"  avg selected-best score gap             : {fs_score_gap_sum / fs_score_gap_count:.2f}")
    else:
        print(f"  avg selected-best score gap             : N/A")
    print()
    print("  Sample cases (up to 10):")
    for idx, s in enumerate(fs_samples[:10], 1):
        print(f"    {idx}. Battle: {s['battle_tag']} turn {s['turn']} {s['slot']} ({s['outcome']})")
        print(f"       Selected: {s['selected']} (score={s['sel_score']:.1f}) | Best: {s['best']} (score={s['best_score']:.1f})")
        print(f"       Candidates: {s['candidate_count']} | DT={s['double_threat']} QW={s['quad_weak']}")
        if s['reason']:
            print(f"       Reasons: {s['reason']}")
    print("=" * 70)


    # ===== Phase 6.4.3: Stat-Drop Switch Diagnostics Report =====
    print("\n" + "=" * 70)
    print("  Stat-Drop Switch Diagnostics Report (Phase 6.4.3)")
    print("=" * 70)

    sd_total = 0
    sd_switch_avail = 0
    sd_switched = 0
    sd_stayed = 0
    sd_productive = 0
    sd_unproductive = 0
    sd_only_legal = 0
    sd_win_count = 0
    sd_loss_count = 0
    sd_samples = []

    for filepath_line in filepath if isinstance(filepath, list) else [filepath]:
        if not os.path.exists(filepath_line):
            continue
        with open(filepath_line, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    battle = json.loads(line)
                    battle_tag = battle.get("battle_tag", "")
                    won = battle.get("won", False)
                    for turn in battle.get("audit_turns", []):
                        turn_num = turn.get("turn", 0)
                        for slot_key in ("slot_0", "slot_1"):
                            slot = turn.get(slot_key, {})
                            if not slot:
                                continue
                            is_severe = bool(slot.get("severe_negative_boost_active"))
                            if not is_severe:
                                continue
                            sd_total += 1
                            if won:
                                sd_win_count += 1
                            else:
                                sd_loss_count += 1
                            if bool(slot.get("severe_negative_boost_switch_available")):
                                sd_switch_avail += 1
                            if bool(slot.get("severe_negative_boost_switched")):
                                sd_switched += 1
                            if bool(slot.get("severe_negative_boost_stayed")):
                                sd_stayed += 1
                            if bool(slot.get("severe_negative_boost_stayed_productive")):
                                sd_productive += 1
                            if bool(slot.get("severe_negative_boost_stayed_unproductive")):
                                sd_unproductive += 1
                            if bool(slot.get("severe_negative_boost_only_legal_no_switch")):
                                sd_only_legal += 1

                            if len(sd_samples) < 10:
                                sd_samples.append({
                                    "battle_tag": battle_tag,
                                    "turn": turn_num,
                                    "species": slot.get("severe_negative_boost_species", ""),
                                    "categories": slot.get("severe_negative_boost_categories", []),
                                    "selected_action": slot.get("severe_negative_boost_selected_action", ""),
                                    "best_switch": slot.get("severe_negative_boost_best_switch_candidate", ""),
                                    "switched": bool(slot.get("severe_negative_boost_switched")),
                                    "productive": bool(slot.get("severe_negative_boost_stayed_productive")),
                                    "won": won,
                                })
                except Exception:
                    continue

    print(f"  total severe negative boost turns        : {sd_total}")
    print(f"    in wins                                : {sd_win_count}")
    print(f"    in losses                              : {sd_loss_count}")
    print(f"  switch available count                   : {sd_switch_avail}")
    print(f"  switched count                           : {sd_switched}")
    print(f"  stayed count                             : {sd_stayed}")
    print(f"    stayed productive                      : {sd_productive}")
    print(f"    stayed unproductive                    : {sd_unproductive}")
    print(f"  only-legal no-switch count               : {sd_only_legal}")
    print()
    print("  Sample cases (up to 10):")
    for idx, s in enumerate(sd_samples[:10], 1):
        outcome = "WON" if s["won"] else "LOST"
        prod_str = "productive" if s["productive"] else "unproductive" if s["switched"] is False else ""
        print(f"    {idx}. [{s['battle_tag']}] turn {s['turn']} ({outcome})")
        print(f"       Species: {s['species']} Categories: {','.join(s['categories'])}")
        print(f"       Selected: {s['selected_action']} Best switch: {s['best_switch'] or 'none'}")
        if not s["switched"]:
            print(f"       Stayed: {prod_str}")
        else:
            print(f"       Switched out")
    print("=" * 70)


    # ===== Phase 6.4.2: Revealed-Move Switch Interception Report =====
    print("\n" + "=" * 70)
    print("  Revealed-Move Switch Interception Report (Phase 6.4.2)")
    print("=" * 70)

    prediction_available_count = 0
    interception_selected_count = 0
    selection_changed_count = 0
    correct_prediction_count = 0
    wrong_prediction_count = 0
    survived_count = 0
    candidate_fainted_count = 0
    ko_override_count = 0
    high_value_override_count = 0
    worse_other_threat_count = 0
    our_type_immune_error_count = 0
    opponent_type_immune_error_count = 0
    electric_ground_count = 0
    unique_prediction_battles = set()
    unique_correct_battles = set()
    unique_wrong_battles = set()

    for filepath_line in filepath if isinstance(filepath, list) else [filepath]:
        if not os.path.exists(filepath_line):
            continue
        with open(filepath_line, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    battle = json.loads(line)
                    battle_tag = battle.get("battle_tag", "")
                    won = battle.get("won", False)
                    for turn in battle.get("audit_turns", []):
                        for slot_key in ("slot_0", "slot_1"):
                            slot = turn.get(slot_key, {})
                            if not slot:
                                continue

                            if slot.get("revealed_switch_prediction_available"):
                                prediction_available_count += 1
                                unique_prediction_battles.add(battle_tag)
                            if slot.get("revealed_switch_interception_selected"):
                                interception_selected_count += 1
                            if slot.get("revealed_switch_selection_changed"):
                                selection_changed_count += 1
                            if slot.get("revealed_switch_prediction_correct"):
                                correct_prediction_count += 1
                                unique_correct_battles.add(battle_tag)
                            if slot.get("revealed_switch_prediction_wrong"):
                                wrong_prediction_count += 1
                                unique_wrong_battles.add(battle_tag)
                            if not slot.get("revealed_switch_post_turn_survived", True):
                                candidate_fainted_count += 1
                            if slot.get("revealed_switch_blocked_by_ko_action"):
                                ko_override_count += 1
                            if slot.get("revealed_switch_blocked_by_high_value_action"):
                                high_value_override_count += 1
                            if slot.get("revealed_switch_rejected_worse_other_threat"):
                                worse_other_threat_count += 1
                            if slot.get("our_type_immune_move_selected"):
                                our_type_immune_error_count += 1
                            if slot.get("opponent_type_immune_move_selected"):
                                opponent_type_immune_error_count += 1
                            if slot.get("action_types", {}).get("switch"):
                                # Check for Electric/Ground immunity case
                                species = slot.get("selected_switch_species", "")
                                types = slot.get("selected_switch_types", "")
                                if "Electric" in str(types) and "Ground" in str(types):
                                    electric_ground_count += 1

                except Exception:
                    continue

    print(f"  predictions available                   : {prediction_available_count}")
    print(f"    unique battles with predictions       : {len(unique_prediction_battles)}")
    print(f"  interceptions selected                  : {interception_selected_count}")
    print(f"  selections changed                      : {selection_changed_count}")
    print(f"  correct predictions                     : {correct_prediction_count}")
    print(f"    unique battles with correct           : {len(unique_correct_battles)}")
    print(f"  wrong predictions                       : {wrong_prediction_count}")
    print(f"    unique battles with wrong             : {len(unique_wrong_battles)}")
    print(f"  candidate fainted after switch          : {candidate_fainted_count}")
    print(f"  blocked by KO action override           : {ko_override_count}")
    print(f"  blocked by high-value action            : {high_value_override_count}")
    print(f"  rejected worse-other-threat             : {worse_other_threat_count}")
    print(f"  our type-immune errors                  : {our_type_immune_error_count}")
    print(f"  opponent type-immune errors (observational): {opponent_type_immune_error_count}")
    print(f"  Electric/Ground immunity cases          : {electric_ground_count}")

    if correct_prediction_count + wrong_prediction_count > 0:
        precision = correct_prediction_count / (correct_prediction_count + wrong_prediction_count) * 100
        print(f"  prediction precision                    : {precision:.1f}%")
    else:
        print(f"  prediction precision                    : N/A (no predictions)")

    print("=" * 70)

    # ===== Phase 6.3.5b: Deterministic Singleton Levitate Safety Report =====
    print("\n" + "=" * 70)
    print("  Deterministic Singleton Levitate Safety Report (Phase 6.3.5b)")
    print("=" * 70)

    arms = {
        True: { # ON arm
            "opportunities": 0,
            "selected_blocked": 0,
            "hard_block_applied": 0,
            "blocked_candidate_observed": 0,
            "selection_changed": 0,
            "only_legal": 0,
            "resolution_source_det": 0,
        },
        False: { # OFF arm
            "opportunities": 0,
            "selected_blocked": 0,
            "hard_block_applied": 0,
            "blocked_candidate_observed": 0,
            "selection_changed": 0,
            "only_legal": 0,
            "resolution_source_det": 0,
        }
    }

    unique_opp_battles = {True: set(), False: set()}
    unique_selected_battles = {True: set(), False: set()}
    unique_changed_battles = {True: set(), False: set()}

    for filepath_line in filepath if isinstance(filepath, list) else [filepath]:
        if not os.path.exists(filepath_line):
            continue
        with open(filepath_line, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    battle = json.loads(line)
                    battle_tag = battle.get("battle_tag", "")

                    # Determine arm from top-level metadata (preferred) or
                    # fall back to first turn's opponent_actives_state.
                    battle_is_on = battle.get("singleton_safety_enabled", None)
                    if battle_is_on is None:
                        # Legacy fallback for old JSONL without top-level metadata
                        turns = battle.get("audit_turns", [])
                        battle_is_on = False
                        if turns:
                            opponents_info = turns[0].get("opponent_actives_state", [])
                            if opponents_info:
                                for info in opponents_info:
                                    if info and info.get("singleton_flag_state", False):
                                        battle_is_on = True
                                        break
                    benchmark_arm = battle.get("benchmark_arm", "")

                    arm = arms[battle_is_on]

                    for turn in battle.get("audit_turns", []):
                        for slot_key in ("slot_0", "slot_1"):
                            slot = turn.get(slot_key, {})
                            if not slot:
                                continue
                            if slot.get("singleton_levitate_opportunity_observed"):
                                arm["opportunities"] += 1
                                unique_opp_battles[battle_is_on].add(battle_tag)
                            if slot.get("singleton_ground_into_levitate_selected_observed"):
                                arm["selected_blocked"] += 1
                                unique_selected_battles[battle_is_on].add(battle_tag)
                            if slot.get("singleton_hard_block_applied"):
                                arm["hard_block_applied"] += 1
                            if slot.get("singleton_blocked_candidate_observed"):
                                arm["blocked_candidate_observed"] += 1
                            if slot.get("singleton_selection_changed_by_safety"):
                                arm["selection_changed"] += 1
                                unique_changed_battles[battle_is_on].add(battle_tag)
                            if slot.get("singleton_only_legal_action"):
                                arm["only_legal"] += 1
                            if slot.get("singleton_resolution_source") == "deterministic_singleton":
                                arm["resolution_source_det"] += 1
                except Exception:
                    continue

    for is_on, name in [(True, "ON Arm (Safety Enabled)"), (False, "OFF Arm (Safety Disabled)")]:
        arm = arms[is_on]
        print(f"  {name}:")
        print(f"    Levitate opportunities observed            : {arm['opportunities']} (in {len(unique_opp_battles[is_on])} battles)")
        print(f"    Ground-into-Levitate selected (observed)   : {arm['selected_blocked']} (in {len(unique_selected_battles[is_on])} battles)")
        print(f"    Safety hard-block score applied            : {arm['hard_block_applied']}")
        print(f"    Blocked Ground candidate available         : {arm['blocked_candidate_observed']}")
        print(f"    Selection changed by safety counterfactual : {arm['selection_changed']} (in {len(unique_changed_battles[is_on])} battles)")
        print(f"    Only-legal blocked action (no alternatives) : {arm['only_legal']}")
        print(f"    Deterministic singleton resolution source  : {arm['resolution_source_det']}")
        print()
    print("=" * 70)

    # ===== Phase 6.4.5: Stale Target / Retarget Safety Report =====
    print("\n" + "=" * 70)
    print("  Stale Target / Retarget Safety Report (Phase 6.4.5)")
    print("=" * 70)

    st_selected = 0
    st_avoided = 0
    st_same_ko = 0
    st_type_immune = 0
    st_no_effect = 0
    st_wins = 0
    st_losses = 0
    st_samples = []

    for filepath_line in filepath if isinstance(filepath, list) else [filepath]:
        if not os.path.exists(filepath_line):
            continue
        with open(filepath_line, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                battle_tag = record.get("battle_tag", "Unknown")
                is_win = record.get("won", False)
                for turn_data in record.get("audit_turns", []):
                    if turn_data.get("stale_target_selected"):
                        st_selected += 1
                        if is_win:
                            st_wins += 1
                        else:
                            st_losses += 1
                        if turn_data.get("stale_target_same_target_expected_ko"):
                            st_same_ko += 1
                        if turn_data.get("stale_target_caused_type_immune"):
                            st_type_immune += 1
                        if turn_data.get("stale_target_caused_no_effect"):
                            st_no_effect += 1
                        if len(st_samples) < 10:
                            st_samples.append({
                                "battle_tag": battle_tag,
                                "turn": turn_data.get("turn", 0),
                                "outcome": "WIN" if is_win else "LOSS",
                                "first_move": turn_data.get("stale_target_first_move", ""),
                                "first_target": turn_data.get("stale_target_first_target", ""),
                                "second_move": turn_data.get("stale_target_second_move", ""),
                                "second_intended_target": turn_data.get("stale_target_second_intended_target", ""),
                                "fallback_target": turn_data.get("stale_target_fallback_target", ""),
                                "reason": turn_data.get("stale_target_reason", ""),
                                "type_immune": turn_data.get("stale_target_caused_type_immune", False),
                                "no_effect": turn_data.get("stale_target_caused_no_effect", False),
                            })
                    if turn_data.get("stale_target_avoided"):
                        st_avoided += 1

    print(f"  stale_target_selected count              : {st_selected}")
    print(f"  stale_target_avoided count               : {st_avoided}")
    print(f"  same_target_expected_ko count            : {st_same_ko}")
    print(f"  type-immune fallback risk count          : {st_type_immune}")
    print(f"  no-effect risk count                     : {st_no_effect}")
    print(f"  wins / losses                            : {st_wins} / {st_losses}")
    print()
    if st_samples:
        print("  Sample cases (up to 10):")
        for idx, s in enumerate(st_samples, 1):
            print(f"    {idx}. Battle: {s['battle_tag']} turn {s['turn']} ({s['outcome']})")
            print(f"       First move/target     : {s['first_move']} -> {s['first_target']}")
            print(f"       Second move/target    : {s['second_move']} -> {s['second_intended_target']}")
            print(f"       Fallback target       : {s['fallback_target']}")
            print(f"       Reason                : {s['reason']}")
            flags = []
            if s['type_immune']:
                flags.append("type-immune")
            if s['no_effect']:
                flags.append("no-effect")
            if flags:
                print(f"       Flags                 : {', '.join(flags)}")
    else:
        print("  (No stale target events found)")
    print("=" * 70)

    # ===== Phase 6.4.6: Decision Timing Report =====
    print("\n" + "=" * 70)
    print("  Decision Timing Report (Phase 6.4.6)")
    print("=" * 70)

    timing_values = []
    timing_rows = []

    for filepath_line in filepath if isinstance(filepath, list) else [filepath]:
        if not os.path.exists(filepath_line):
            continue
        with open(filepath_line, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                battle_tag = record.get("battle_tag", "Unknown")
                for turn_data in record.get("audit_turns", []):
                    dt = turn_data.get("decision_time_ms")
                    if dt is None:
                        continue
                    timing_values.append(float(dt))
                    timing_rows.append({
                        "battle_tag": battle_tag,
                        "turn": turn_data.get("turn", 0),
                        "decision_time_ms": float(dt),
                        "valid_order_time_ms": turn_data.get("valid_order_time_ms"),
                        "score_action_time_ms": turn_data.get("score_action_time_ms"),
                        "joint_scoring_time_ms": turn_data.get("joint_scoring_time_ms"),
                        "audit_postprocess_time_ms": turn_data.get("audit_postprocess_time_ms"),
                        "score_action_call_count": turn_data.get("score_action_call_count"),
                        "joint_order_count": turn_data.get("joint_order_count"),
                        "selected_joint_order": turn_data.get("selected_joint_order", ""),
                        "stale_target": turn_data.get("stale_target_selected", False),
                        "forced_switch": any(
                            turn_data.get(sk, {}).get("forced_switch", False)
                            for sk in ("slot_0", "slot_1")
                        ),
                        "severe_neg_boost": any(
                            turn_data.get(sk, {}).get("severe_neg_boost_active", False)
                            for sk in ("slot_0", "slot_1")
                        ),
                        "direct_absorb": any(
                            turn_data.get(sk, {}).get("direct_absorb_immune_move_selected", False)
                            for sk in ("slot_0", "slot_1")
                        ),
                    })

    if not timing_values:
        print("  (No timing data found — enable_decision_timing_diagnostics may be off)")
        print("=" * 70)
    else:
        timing_values.sort()
        n = len(timing_values)

        avg = sum(timing_values) / n
        p50 = timing_values[n // 2]
        p95_idx = int(n * 0.95)
        p95 = timing_values[p95_idx] if p95_idx < n else timing_values[-1]
        mx = timing_values[-1]

        print(f"  turns with timing data                  : {n}")
        print(f"  avg decision_time_ms                    : {avg:.2f}")
        print(f"  p50 decision_time_ms                    : {p50:.2f}")
        print(f"  p95 decision_time_ms                    : {p95:.2f}")
        print(f"  max decision_time_ms                    : {mx:.2f}")

        def _safe_avg(lst):
            vals = [x for x in lst if x is not None]
            return sum(vals) / len(vals) if vals else None

        def _safe_p95(lst):
            vals = sorted([x for x in lst if x is not None])
            if not vals:
                return None
            idx = int(len(vals) * 0.95)
            return vals[idx] if idx < len(vals) else vals[-1]

        sa_vals = [r["score_action_time_ms"] for r in timing_rows]
        js_vals = [r["joint_scoring_time_ms"] for r in timing_rows]
        ap_vals = [r["audit_postprocess_time_ms"] for r in timing_rows]
        sac_vals = [r["score_action_call_count"] for r in timing_rows]
        jo_vals = [r["joint_order_count"] for r in timing_rows]

        print(f"  avg / p95 score_action_time_ms          : {_safe_avg(sa_vals):.2f} / {_safe_p95(sa_vals):.2f}" if _safe_avg(sa_vals) else "  avg / p95 score_action_time_ms          : N/A")
        print(f"  avg / p95 joint_scoring_time_ms         : {_safe_avg(js_vals):.2f} / {_safe_p95(js_vals):.2f}" if _safe_avg(js_vals) else "  avg / p95 joint_scoring_time_ms         : N/A")
        print(f"  avg / p95 audit_postprocess_time_ms     : {_safe_avg(ap_vals):.2f} / {_safe_p95(ap_vals):.2f}" if _safe_avg(ap_vals) else "  avg / p95 audit_postprocess_time_ms     : N/A")
        print(f"  avg score_action_call_count             : {_safe_avg(sac_vals):.1f}" if _safe_avg(sac_vals) else "  avg score_action_call_count             : N/A")
        print(f"  avg joint_order_count                   : {_safe_avg(jo_vals):.1f}" if _safe_avg(jo_vals) else "  avg joint_order_count                   : N/A")
        print()

        # Top 20 slowest turns
        timing_rows.sort(key=lambda x: x["decision_time_ms"], reverse=True)
        print("  Top 20 slowest turns:")
        for idx, r in enumerate(timing_rows[:20], 1):
            flags = []
            if r["stale_target"]:
                flags.append("stale-target")
            if r["forced_switch"]:
                flags.append("forced-switch")
            if r["severe_neg_boost"]:
                flags.append("severe-neg-boost")
            if r["direct_absorb"]:
                flags.append("direct-absorb")
            flag_str = " | ".join(flags) if flags else "none"

            dt = r["decision_time_ms"]
            sc = r["score_action_call_count"]
            jo = r["joint_order_count"]
            sa = f"{r['score_action_time_ms']:.1f}" if r["score_action_time_ms"] is not None else "-"
            ap = f"{r['audit_postprocess_time_ms']:.1f}" if r["audit_postprocess_time_ms"] is not None else "-"

            print(f"    {idx:2d}. {r['battle_tag'][:20]} turn {r['turn']:2d}  "
                  f"decision={dt:.1f}ms  sa_calls={sc}  joint_orders={jo}")
            print(f"         score_action={sa}ms  audit_post={ap}ms  flags=[{flag_str}]")
            if idx <= 5:
                sel = r["selected_joint_order"][:80]
                if sel:
                    print(f"         selected: {sel}")
    print("=" * 70)

    # ===== Phase 6.4.7: Stat-Drop Switch Scoring Report =====
    print("\n" + "=" * 70)
    print("  Stat-Drop Switch Scoring Report (Phase 6.4.7)")
    print("=" * 70)

    sds_enabled = 0
    sds_pressure = 0
    sds_switch_selected = 0
    sds_stayed_productive = 0
    sds_stayed_unproductive = 0
    sds_sel_changed = 0
    sds_offensive = 0
    sds_defensive = 0
    sds_speed = 0
    sds_wins = 0
    sds_losses = 0
    sds_samples = []

    for filepath_line in filepath if isinstance(filepath, list) else [filepath]:
        if not os.path.exists(filepath_line):
            continue
        with open(filepath_line, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                battle_tag = record.get("battle_tag", "Unknown")
                is_win = record.get("won", False)
                for turn_data in record.get("audit_turns", []):
                    for sk in ("slot_0", "slot_1"):
                        slot = turn_data.get(sk, {})
                        if not slot:
                            continue
                        if slot.get("stat_drop_switch_scoring_enabled"):
                            sds_enabled += 1
                        if slot.get("stat_drop_switch_pressure_active"):
                            sds_pressure += 1
                            if is_win:
                                sds_wins += 1
                            else:
                                sds_losses += 1
                            cats = slot.get("stat_drop_switch_pressure_categories", [])
                            if "offensive" in cats:
                                sds_offensive += 1
                            if "defensive" in cats:
                                sds_defensive += 1
                            if "speed" in cats:
                                sds_speed += 1
                            if slot.get("stat_drop_switch_selected"):
                                sds_switch_selected += 1
                            if slot.get("stat_drop_switch_stayed_productive"):
                                sds_stayed_productive += 1
                            if slot.get("stat_drop_switch_stayed_unproductive"):
                                sds_stayed_unproductive += 1
                            if slot.get("stat_drop_switch_selection_changed"):
                                sds_sel_changed += 1
                            if len(sds_samples) < 10:
                                sds_samples.append({
                                    "battle_tag": battle_tag,
                                    "turn": turn_data.get("turn", 0),
                                    "outcome": "WIN" if is_win else "LOSS",
                                    "categories": cats,
                                    "selected_action": turn_data.get("selected_joint_order", "")[:60],
                                    "best_switch": slot.get("stat_drop_switch_best_switch_species", ""),
                                    "best_switch_score": slot.get("stat_drop_switch_best_switch_score", 0.0),
                                    "best_non_switch_score": slot.get("stat_drop_switch_best_non_switch_score", 0.0),
                                    "reason": slot.get("stat_drop_switch_reason", ""),
                                })

    print(f"  scoring enabled turns                   : {sds_enabled}")
    print(f"  pressure active count                   : {sds_pressure}")
    print(f"  switch selected count                   : {sds_switch_selected}")
    print(f"  stayed productive count                 : {sds_stayed_productive}")
    print(f"  stayed unproductive count               : {sds_stayed_unproductive}")
    print(f"  selection changed count                 : {sds_sel_changed}")
    print(f"  offensive / defensive / speed split     : {sds_offensive} / {sds_defensive} / {sds_speed}")
    print(f"  wins / losses                           : {sds_wins} / {sds_losses}")
    print()
    if sds_samples:
        print("  Sample cases (up to 10):")
        for idx, s in enumerate(sds_samples, 1):
            print(f"    {idx}. Battle: {s['battle_tag']} turn {s['turn']} ({s['outcome']})")
            print(f"       Categories          : {s['categories']}")
            print(f"       Selected action     : {s['selected_action']}")
            print(f"       Best switch         : {s['best_switch']} ({s['best_switch_score']:.1f})")
            print(f"       Best non-switch     : {s['best_non_switch_score']:.1f}")
            print(f"       Reason              : {s['reason']}")
    else:
        print("  (No stat-drop switch scoring events)")
    # Phase 6.4.7b: Deeper pressure quality metrics
    if sds_pressure > 0:
        sw_scores = []
        ns_scores = []
        gaps = []
        act_types = {"switch": 0, "damaging": 0, "protect": 0, "pass": 0, "other": 0}
        neg_gap = 0
        pos_gap = 0
        had_switch_avail = 0
        for filepath_line in filepath if isinstance(filepath, list) else [filepath]:
            if not os.path.exists(filepath_line):
                continue
            with open(filepath_line, "r") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    for td in rec.get("audit_turns", []):
                        sel = td.get("selected_joint_order", "")
                        for sk in ("slot_0", "slot_1"):
                            s = td.get(sk, {})
                            if not s.get("stat_drop_switch_pressure_active"):
                                continue
                            bsw = s.get("stat_drop_switch_best_switch_score", 0)
                            bns = s.get("stat_drop_switch_best_non_switch_score", 0)
                            sw_scores.append(bsw)
                            ns_scores.append(bns)
                            gaps.append(bsw - bns)
                            if bsw - bns < 0:
                                neg_gap += 1
                            elif bsw - bns > 0:
                                pos_gap += 1
                            if s.get("stat_drop_switch_selected"):
                                act_types["switch"] += 1
                            elif s.get("stat_drop_switch_stayed_unproductive"):
                                if "protect" in sel.lower():
                                    act_types["protect"] += 1
                                elif "move" in sel.lower():
                                    act_types["damaging"] += 1
                                elif "pass" in sel.lower():
                                    act_types["pass"] += 1
                                else:
                                    act_types["other"] += 1
                            elif s.get("stat_drop_switch_stayed_productive"):
                                act_types["damaging"] += 1
                            if s.get("stat_drop_switch_best_switch_species", ""):
                                had_switch_avail += 1
        avg_sw = sum(sw_scores) / len(sw_scores) if sw_scores else 0
        avg_ns = sum(ns_scores) / len(ns_scores) if ns_scores else 0
        avg_gap = sum(gaps) / len(gaps) if gaps else 0
        print(f"  avg best_switch_score                  : {avg_sw:.1f}")
        print(f"  avg best_non_switch_score              : {avg_ns:.1f}")
        print(f"  avg gap (sw - ns)                      : {avg_gap:.1f}")
        print(f"  negative gap cases                     : {neg_gap}")
        print(f"  positive gap cases                     : {pos_gap}")
        print(f"  action type split                      : {act_types}")
        print(f"  had switch available                   : {had_switch_avail}")
    print("=" * 70)

    # ===== Phase 6.4.8: Disabled Safety Feature Attribution Report =====
    print("\n" + "=" * 70)
    print("  Disabled Safety Feature Attribution Report (Phase 6.4.8)")
    print("=" * 70)

    # Single-pass aggregation across all three features
    fs_agg = {"count": 0, "enabled_arms": set(), "dt": 0, "qw": 0, "low_hp": 0,
              "sel_changed": 0, "fallback": 0, "gap_sum": 0.0, "gap_count": 0,
              "wins": 0, "losses": 0, "top_losses": []}
    st_agg = {"count": 0, "avoided": 0, "type_imm": 0, "no_eff": 0,
              "wins": 0, "losses": 0, "top_losses": []}
    sd_agg = {"count": 0, "sel": 0, "prod": 0, "unprod": 0, "changed": 0,
              "off": 0, "def": 0, "spd": 0, "wins": 0, "losses": 0, "top_losses": []}
    changed_cases = []
    lost_with_enabled = []

    for filepath_line in filepath if isinstance(filepath, list) else [filepath]:
        if not os.path.exists(filepath_line):
            continue
        with open(filepath_line, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                bt = rec.get("battle_tag", "Unknown")
                won = rec.get("won", False)
                arm = rec.get("benchmark_arm", "")
                for td in rec.get("audit_turns", []):
                    turn = td.get("turn", 0)

                    # Forced switch (per-slot)
                    for sk in ("slot_0", "slot_1"):
                        slot = td.get(sk, {})
                        if slot.get("forced_switch"):
                            fs_agg["count"] += 1
                            if slot.get("forced_switch_safety_enabled"):
                                fs_agg["enabled_arms"].add(arm)
                            if slot.get("forced_switch_selected_double_threat"):
                                fs_agg["dt"] += 1
                            if slot.get("forced_switch_selected_quad_weak"):
                                fs_agg["qw"] += 1
                            if slot.get("forced_switch_selected_low_hp"):
                                fs_agg["low_hp"] += 1
                            if slot.get("forced_switch_safety_selection_changed"):
                                fs_agg["sel_changed"] += 1
                            if slot.get("forced_switch_order_fallback_used"):
                                fs_agg["fallback"] += 1
                            sel_sc = slot.get("forced_switch_selected_safety_score", 0)
                            best_sc = slot.get("forced_switch_best_safety_score", 0)
                            gap = best_sc - sel_sc
                            if gap != 0:
                                fs_agg["gap_sum"] += gap
                                fs_agg["gap_count"] += 1
                            if won:
                                fs_agg["wins"] += 1
                            else:
                                fs_agg["losses"] += 1
                                dt = slot.get("forced_switch_selected_double_threat", False)
                                qw = slot.get("forced_switch_selected_quad_weak", False)
                                if dt or qw and len(fs_agg["top_losses"]) < 10:
                                    fs_agg["top_losses"].append({
                                        "battle": bt, "turn": turn, "slot": sk,
                                        "dt": dt, "qw": qw,
                                        "sel": slot.get("forced_switch_selected_species", ""),
                                        "best": slot.get("forced_switch_best_safety_species", ""),
                                    })
                        # Stat-drop (per-slot)
                        if slot.get("stat_drop_switch_pressure_active"):
                            sd_agg["count"] += 1
                            if slot.get("stat_drop_switch_selected"):
                                sd_agg["sel"] += 1
                            if slot.get("stat_drop_switch_stayed_productive"):
                                sd_agg["prod"] += 1
                            if slot.get("stat_drop_switch_stayed_unproductive"):
                                sd_agg["unprod"] += 1
                            if slot.get("stat_drop_switch_selection_changed"):
                                sd_agg["changed"] += 1
                            cats = slot.get("stat_drop_switch_pressure_categories", [])
                            if "offensive" in cats:
                                sd_agg["off"] += 1
                            if "defensive" in cats:
                                sd_agg["def"] += 1
                            if "speed" in cats:
                                sd_agg["spd"] += 1
                            if won:
                                sd_agg["wins"] += 1
                            else:
                                sd_agg["losses"] += 1
                                unprod = slot.get("stat_drop_switch_stayed_unproductive", False)
                                if unprod and len(sd_agg["top_losses"]) < 10:
                                    sd_agg["top_losses"].append({
                                        "battle": bt, "turn": turn, "slot": sk,
                                        "categories": cats,
                                        "best_switch": slot.get("stat_drop_switch_best_switch_species", ""),
                                    })

                    # Stale target (turn-level)
                    if td.get("stale_target_selected"):
                        st_agg["count"] += 1
                        if td.get("stale_target_caused_type_immune"):
                            st_agg["type_imm"] += 1
                        if td.get("stale_target_caused_no_effect"):
                            st_agg["no_eff"] += 1
                        if won:
                            st_agg["wins"] += 1
                        else:
                            st_agg["losses"] += 1
                            if len(st_agg["top_losses"]) < 10:
                                st_agg["top_losses"].append({
                                    "battle": bt, "turn": turn,
                                    "first": td.get("stale_target_first_move", ""),
                                    "second": td.get("stale_target_second_move", ""),
                                    "fallback": td.get("stale_target_fallback_target", ""),
                                    "ti": td.get("stale_target_caused_type_immune"),
                                    "ne": td.get("stale_target_caused_no_effect"),
                                })
                    if td.get("stale_target_avoided"):
                        st_agg["avoided"] += 1

                    # Selection-changed cases across features
                    for sk in ("slot_0", "slot_1"):
                        slot = td.get(sk, {})
                        fsc = slot.get("forced_switch_safety_selection_changed", False)
                        sdc = slot.get("stat_drop_switch_selection_changed", False)
                        if fsc or sdc:
                            changed_cases.append({
                                "battle": bt, "turn": turn, "slot": sk, "won": won,
                                "forced": fsc, "statdrop": sdc,
                                "order": td.get("selected_joint_order", "")[:60],
                            })
                    # Lost-with-enabled cases
                    if not won:
                        for sk in ("slot_0", "slot_1"):
                            slot = td.get(sk, {})
                            fs_en = slot.get("forced_switch_safety_enabled", False)
                            sd_en = slot.get("stat_drop_switch_scoring_enabled", False)
                            st_used = td.get("stale_target_selected", False)
                            if fs_en and (slot.get("forced_switch_selected_double_threat") or
                                          slot.get("forced_switch_selected_quad_weak")):
                                if len(lost_with_enabled) < 10:
                                    lost_with_enabled.append({
                                        "battle": bt, "turn": turn, "slot": sk, "feat": "forced-switch",
                                        "dt": slot.get("forced_switch_selected_double_threat"),
                                        "qw": slot.get("forced_switch_selected_quad_weak"),
                                    })
                            elif sd_en and slot.get("stat_drop_switch_stayed_unproductive"):
                                if len(lost_with_enabled) < 10:
                                    lost_with_enabled.append({
                                        "battle": bt, "turn": turn, "slot": sk, "feat": "stat-drop",
                                    })
                            elif st_used and (td.get("stale_target_caused_type_immune") or
                                              td.get("stale_target_caused_no_effect")):
                                if len(lost_with_enabled) < 10:
                                    lost_with_enabled.append({
                                        "battle": bt, "turn": turn, "slot": "turn", "feat": "stale-target",
                                    })

    # Print sections
    print("  Forced Switch Replacement Safety:")
    print(f"    forced switch events                 : {fs_agg['count']}")
    print(f"    enabled arms                         : {sorted(fs_agg['enabled_arms'])}")
    print(f"    selected double-threat               : {fs_agg['dt']}")
    print(f"    selected quad-weak                   : {fs_agg['qw']}")
    print(f"    selected low-hp                      : {fs_agg['low_hp']}")
    print(f"    selection changed                    : {fs_agg['sel_changed']}")
    print(f"    fallback used                        : {fs_agg['fallback']}")
    if fs_agg["gap_count"] > 0:
        print(f"    avg / max safety score gap           : {fs_agg['gap_sum']/fs_agg['gap_count']:.1f} / "
              f"{fs_agg['gap_sum']:.1f}")
    print(f"    wins / losses                        : {fs_agg['wins']} / {fs_agg['losses']}")
    if fs_agg["top_losses"]:
        print(f"    worst loss cases (dt/qw):")
        for s in fs_agg["top_losses"][:5]:
            print(f"      {s['battle'][:25]} t{s['turn']} dt={s['dt']} qw={s['qw']} "
                  f"sel={s['sel']} best={s['best']}")

    print()
    print("  Stale Target Safety:")
    print(f"    stale_target_selected                : {st_agg['count']}")
    print(f"    stale_target_avoided                 : {st_agg['avoided']}")
    print(f"    type-immune fallback                 : {st_agg['type_imm']}")
    print(f"    no-effect fallback                   : {st_agg['no_eff']}")
    print(f"    wins / losses                        : {st_agg['wins']} / {st_agg['losses']}")
    if st_agg["top_losses"]:
        print(f"    worst loss cases:")
        for s in st_agg["top_losses"][:5]:
            print(f"      {s['battle'][:25]} t{s['turn']} {s['first']}/{s['second']} "
                  f"fallback={s['fallback']} ti={s['ti']} ne={s['ne']}")

    print()
    print("  Stat-Drop Switch Scoring:")
    print(f"    pressure active                      : {sd_agg['count']}")
    print(f"    switch selected                      : {sd_agg['sel']}")
    print(f"    stayed productive                    : {sd_agg['prod']}")
    print(f"    stayed unproductive                  : {sd_agg['unprod']}")
    print(f"    selection changed                    : {sd_agg['changed']}")
    print(f"    offensive/defensive/speed            : {sd_agg['off']}/{sd_agg['def']}/{sd_agg['spd']}")
    print(f"    wins / losses                        : {sd_agg['wins']} / {sd_agg['losses']}")
    if sd_agg["top_losses"]:
        print(f"    worst loss cases (unproductive):")
        for s in sd_agg["top_losses"][:5]:
            print(f"      {s['battle'][:25]} t{s['turn']} cats={s['categories']} "
                  f"best_switch={s['best_switch']}")

    if changed_cases:
        print(f"\n  Selection-Changed Cases ({len(changed_cases)}):")
        for s in changed_cases[:10]:
            print(f"    {s['battle'][:25]} t{s['turn']} {s['slot']} forced={s['forced']} "
                  f"statdrop={s['statdrop']} won={s['won']}")
            print(f"      order: {s['order']}")

    if lost_with_enabled:
        print(f"\n  Lost with Feature Enabled ({len(lost_with_enabled)}):")
        for s in lost_with_enabled[:10]:
            print(f"    {s['battle'][:25]} t{s['turn']} feat={s['feat']} "
                  f"{s.get('dt','')}{s.get('qw','')}")

    print("=" * 70)

    # ===== Phase 6.3.6b: Known Ally Redirection Hard Safety Report =====
    print("\n" + "=" * 70)
    print("  Known Ally Redirection Hard Safety Report (Phase 6.3.6b)")
    print("=" * 70)

    ar_sel = 0; ar_avoided = 0; ar_only_legal = 0; ar_repeat = 0
    ar_sd = 0; ar_lr = 0; ar_known = 0; ar_after = 0
    ar_wins = 0; ar_losses = 0; ar_samples = []

    for fp in filepath if isinstance(filepath, list) else [filepath]:
        if not os.path.exists(fp): continue
        with open(fp) as f:
            for line in f:
                if not line.strip(): continue
                try: rec = json.loads(line)
                except Exception: continue
                bt = rec.get("battle_tag",""); won = rec.get("won",False)
                for td in rec.get("audit_turns", []):
                    for sk in ("slot_0","slot_1"):
                        s = td.get(sk,{})
                        if not s: continue
                        if s.get("known_ally_redirection_selected"):
                            ar_sel += 1
                            if won: ar_wins += 1
                            else: ar_losses += 1
                            r = s.get("known_ally_redirection_reason","")
                            if "stormdrain" in r: ar_sd += 1
                            if "lightningrod" in r: ar_lr += 1
                            if s.get("known_ally_redirection_known_before_decision"): ar_known += 1
                            else: ar_after += 1
                            if s.get("known_ally_redirection_repeat_selected"): ar_repeat += 1
                            if s.get("known_ally_redirection_only_legal"): ar_only_legal += 1
                            if len(ar_samples) < 10:
                                ar_samples.append({
                                    "bt": bt, "turn": td.get("turn",0), "slot": sk, "won": won,
                                    "move": s.get("known_ally_redirection_move_id",""),
                                    "ally": s.get("known_ally_redirection_ally_species",""),
                                    "ally_ab": s.get("known_ally_redirection_ally_ability",""),
                                    "known": s.get("known_ally_redirection_known_before_decision",False),
                                    "reason": r, "repeat": s.get("known_ally_redirection_repeat_selected",False),
                                })
                        if s.get("known_ally_redirection_avoided"): ar_avoided += 1

    print(f"  selected count                         : {ar_sel}")
    print(f"  avoided count                          : {ar_avoided}")
    print(f"  only-legal count                       : {ar_only_legal}")
    print(f"  repeat selected count                  : {ar_repeat}")
    print(f"  Storm Drain split                      : {ar_sd}")
    print(f"  Lightning Rod split                    : {ar_lr}")
    print(f"  known-before-decision                  : {ar_known}")
    print(f"  revealed-after-decision                : {ar_after}")
    print(f"  wins / losses                          : {ar_wins} / {ar_losses}")
    if ar_samples:
        print()
        print("  Sample cases:")
        for i, s in enumerate(ar_samples, 1):
            print(f"    {i}. {s['bt'][:25]} t{s['turn']} {s['slot']} ({'WIN' if s['won'] else 'LOSS'})")
            print(f"       Move: {s['move']}  Ally: {s['ally']} ({s['ally_ab']})")
            print(f"       KnownBefore: {s['known']}  Repeat: {s['repeat']}  Reason: {s['reason']}")
    else:
        print("  (No ally redirection events)")
    print("=" * 70)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Analyze doubles decision audit logs")
    parser.add_argument("filepath", nargs="?", default="logs/doubles_decision_audit.jsonl", help="Path to audit JSONL file")
    args = parser.parse_args()
    analyze_audit_log(args.filepath)
