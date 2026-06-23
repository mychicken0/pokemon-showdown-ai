import json
import os

class DoublesDecisionAuditLogger:
    """
    A decision audit logger for Doubles battles to record per-turn decision scores,
    considered alternatives, and resolve actual turn outcomes (damage, KOs, protect status)
    offline and safe from crashing the battle loop.
    """
    # PLANNER-SPREAD-3d: class-level dict to track the player
    # for each battle_tag. The bot sets this before each
    # log_turn_decision call so the audit's _populate (a
    # @staticmethod without self access) can read picks
    # counters etc. from the player. Class-level because
    # the audit functions are staticmethod and have no self.
    _battle_player_refs = {}
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
        # Phase BI-3K.3: per-battle arm metadata. Set by the
        # runner before each battle so persisted rows can
        # distinguish treatment vs baseline and record whether
        # Mega was enabled. Map: battle_tag -> dict.
        self._battle_arm_meta = {}
        # Phase BI-3K.7: context-based battle metadata. Set
        # by the runner via ``set_current_battle_meta``
        # before each battle. ``save_battle`` reads and
        # clears this on each call, so a single shared
        # logger can be used across battles without
        # relying on battle_tag lookup (which fails when
        # the runner's tag differs from the poke-env
        # server-assigned tag).
        self._current_battle_meta = {}
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

    @staticmethod
    def _build_compact_state_snapshot(battle, battle_tag=None):
        """Phase BI-2B: Compact per-turn state snapshot for
        persisted JSONL. Uses only visible/current battle
        state (no hidden info). Returns a JSON-safe dict
        of primitives; missing attributes use safe
        defaults (None, []). Caller may include this
        in turn_data and live events.
        """
        snap = {
            "turn": None,
            "battle_tag": str(battle_tag) if battle_tag is not None else None,
            "our_active_species": [None, None],
            "opp_active_species": [None, None],
            "our_active_hp_fraction": [None, None],
            "opp_active_hp_fraction": [None, None],
            "our_active_types": [[], []],
            "opp_active_types": [[], []],
            # Phase ITEM-2: ability/item/revealed-moves
            # fields. Per AGENTS.md, only visible data
            # is captured (no hidden info, no meta, no
            # random-set inference). Poke-env exposes
            # these via Pokemon.ability / Pokemon.item /
            # Pokemon.moves (revealed subset).
            "our_active_ability": [None, None],
            "opp_active_ability": [None, None],
            "our_active_item": [None, None],
            "opp_active_item": [None, None],
            "our_active_moves_revealed": [[], []],
            "opp_active_moves_revealed": [[], []],
            "weather": None,
            "fields": [],
            "side_conditions": [],
            "opponent_side_conditions": [],
        }
        if battle is None:
            return snap
        try:
            snap["turn"] = int(getattr(battle, "turn", None)) if getattr(battle, "turn", None) is not None else None
        except (TypeError, ValueError):
            snap["turn"] = None
        our_active = list(getattr(battle, "active_pokemon", []) or [])
        opp_active = list(getattr(battle, "opponent_active_pokemon", []) or [])
        for slot_index, pokemon in enumerate(our_active[:2]):
            snap["our_active_species"][slot_index] = DoublesDecisionAuditLogger._safe_species(pokemon)
            snap["our_active_hp_fraction"][slot_index] = DoublesDecisionAuditLogger._safe_hp_fraction(pokemon)
            snap["our_active_types"][slot_index] = DoublesDecisionAuditLogger._safe_types(pokemon)
            # ITEM-2: ability/item/revealed-moves
            snap["our_active_ability"][slot_index] = DoublesDecisionAuditLogger._safe_ability(pokemon)
            snap["our_active_item"][slot_index] = DoublesDecisionAuditLogger._safe_item(pokemon)
            snap["our_active_moves_revealed"][slot_index] = DoublesDecisionAuditLogger._safe_moves_revealed(pokemon)
        for slot_index, pokemon in enumerate(opp_active[:2]):
            snap["opp_active_species"][slot_index] = DoublesDecisionAuditLogger._safe_species(pokemon)
            snap["opp_active_hp_fraction"][slot_index] = DoublesDecisionAuditLogger._safe_hp_fraction(pokemon)
            snap["opp_active_types"][slot_index] = DoublesDecisionAuditLogger._safe_types(pokemon)
            # ITEM-2: ability/item/revealed-moves
            snap["opp_active_ability"][slot_index] = DoublesDecisionAuditLogger._safe_ability(pokemon)
            snap["opp_active_item"][slot_index] = DoublesDecisionAuditLogger._safe_item(pokemon)
            snap["opp_active_moves_revealed"][slot_index] = DoublesDecisionAuditLogger._safe_moves_revealed(pokemon)
        snap["weather"] = DoublesDecisionAuditLogger._enum_keys(battle, "weather")
        snap["fields"] = DoublesDecisionAuditLogger._enum_keys(battle, "fields")
        snap["side_conditions"] = DoublesDecisionAuditLogger._enum_keys(battle, "side_conditions")
        snap["opponent_side_conditions"] = DoublesDecisionAuditLogger._enum_keys(
            battle, "opponent_side_conditions"
        )
        # PLANNER-IMPL-2: observational intent detector fields.
        # These are populated only when the per-turn IntentDetector
        # was run (i.e., enable_planner_intent_detector=True).
        # They never affect scoring. They are observational only.
        # When the detector was not run, all values are None/empty.
        DoublesDecisionAuditLogger._populate_planner_intent_fields(
            snap, battle
        )
        return snap

    @staticmethod
    def _populate_planner_intent_fields(snap, battle):
        """PLANNER-IMPL-2: write observational intent fields.

        Reads the per-turn IntentDecision from the battle
        (attached by choose_move when the detector is enabled)
        and writes planner_intent_* fields to the snapshot.
        Pure read of self-attached state. Never affects scoring.

        PLANNER-SPREAD-2: also writes planner_spread_defense_bonus_applied
        (audit of how much bonus was actually applied to Wide Guard candidates
        this turn). Default 0.0; only non-zero when scoring flag is ON.
        """
        # Default values (when detector is not run / OFF)
        snap["planner_intent_label"] = None
        snap["planner_intent_confidence"] = None
        snap["planner_intent_matched_moves"] = None
        snap["planner_intent_evidence_source"] = None
        snap["planner_intent_routed_to_policy"] = None
        snap["planner_intent_bonus_applied"] = 0.0
        snap["planner_intent_changed_selection"] = False
        # PLANNER-SPREAD-2: spread defense bonus audit
        snap["planner_spread_defense_bonus_applied"] = 0.0
        snap["planner_spread_defense_picks_this_game"] = 0
        # Try to read the decision attached to the battle
        try:
            decision = getattr(battle, "_planner_intent_decision", None)
            if decision is None:
                return
            snap["planner_intent_label"] = getattr(decision, "intent", None)
            snap["planner_intent_confidence"] = getattr(
                decision, "confidence", None
            )
            snap["planner_intent_matched_moves"] = list(
                getattr(decision, "matched_moves", []) or []
            )
            snap["planner_intent_evidence_source"] = getattr(
                decision, "evidence_source", None
            )
            snap["planner_intent_routed_to_policy"] = getattr(
                decision, "routed_to_policy", None
            )
            # bonus_applied and changed_selection remain 0.0 / False
            # because PLANNER-IMPL-2 does NOT add scoring bonus. The
            # existing per-move policies (anti_setup_disruption,
            # spread_defense, setup_intent) are separate and have
            # their own audit fields. PLANNER only LOGS intent.
            # PLANNER-SPREAD-2: read spread defense picks counter
            # PLANNER-SPREAD-3d: also check class-level
            # _battle_player_refs (set by the bot before
            # log_turn_decision) for the player reference,
            # since poke-env battle doesn't carry it and
            # _populate is a staticmethod without self access.
            player = getattr(battle, "_player", None) or getattr(
                battle, "player", None
            )
            if player is None:
                bt = getattr(battle, "battle_tag", "")
                player = DoublesDecisionAuditLogger._battle_player_refs.get(
                    bt
                )
            if player is not None:
                bt = getattr(battle, "battle_tag", "")
                picks = getattr(
                    player, "_planner_spread_defense_picks_per_game", {}
                ) or {}
                snap["planner_spread_defense_picks_this_game"] = picks.get(
                    bt, 0
                )
                # PLANNER-SPREAD-3d: read cumulative bonus
                bonus_applied = getattr(
                    player,
                    "_planner_spread_defense_bonus_applied_per_game",
                    {},
                ) or {}
                snap["planner_spread_defense_bonus_applied"] = float(
                    bonus_applied.get(bt, 0.0)
                )
        except Exception:
            # Defensive: never break the audit logger
            pass

    @staticmethod
    def _safe_species(pokemon):
        if pokemon is None:
            return None
        try:
            sp = getattr(pokemon, "species", None)
        except Exception:
            sp = None
        if sp is None or sp == "":
            try:
                sp = getattr(pokemon, "name", None)
            except Exception:
                sp = None
        if sp is None or sp == "":
            return None
        try:
            return str(sp)
        except Exception:
            return None

    @staticmethod
    def _safe_hp_fraction(pokemon):
        if pokemon is None:
            return None
        frac = getattr(pokemon, "current_hp_fraction", None)
        if frac is None:
            frac = getattr(pokemon, "hp_fraction", None)
        if frac is None:
            cur = getattr(pokemon, "current_hp", None)
            mx = getattr(pokemon, "max_hp", None)
            if cur is not None and mx:
                try:
                    frac = float(cur) / float(mx)
                except (TypeError, ValueError, ZeroDivisionError):
                    frac = None
        if frac is None:
            return None
        try:
            return float(frac)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_types(pokemon):
        if pokemon is None:
            return []
        out = []
        try:
            types = getattr(pokemon, "types", None)
        except Exception:
            types = None
        if types is None:
            try:
                t1 = getattr(pokemon, "type_1", None)
                t2 = getattr(pokemon, "type_2", None)
                types = [t for t in (t1, t2) if t is not None]
            except Exception:
                types = []
        if not types:
            return []
        for t in types:
            if t is None:
                continue
            try:
                name = getattr(t, "name", None)
            except Exception:
                name = None
            if name is None:
                try:
                    name = str(t)
                except Exception:
                    name = None
            if name:
                out.append(str(name).lower())
        return out

    @staticmethod
    def _safe_ability(pokemon):
        """ITEM-2: extract ability name from a
        Pokemon object, normalized to lowercase
        alphanumeric. Returns None if unknown
        (ability not yet revealed or pokemon
        fainted)."""
        if pokemon is None:
            return None
        try:
            ab = getattr(pokemon, "ability", None)
        except Exception:
            ab = None
        if ab is None:
            return None
        try:
            name = getattr(ab, "name", None)
        except Exception:
            name = None
        if name is None:
            try:
                name = str(ab)
            except Exception:
                return None
        try:
            normalized = "".join(
                c for c in str(name).lower() if c.isalnum()
            )
        except Exception:
            return None
        return normalized or None

    @staticmethod
    def _safe_item(pokemon):
        """ITEM-2: extract item name, normalized
        to lowercase alphanumeric. Returns None
        if no item (e.g., no held item) or
        item not yet revealed."""
        if pokemon is None:
            return None
        try:
            item = getattr(pokemon, "item", None)
        except Exception:
            item = None
        if item is None:
            return None
        try:
            name = getattr(item, "name", None)
        except Exception:
            name = None
        if name is None:
            try:
                name = str(item)
            except Exception:
                return None
        # Strip non-alphanumeric and lowercase
        try:
            normalized = "".join(
                c for c in str(name).lower() if c.isalnum()
            )
        except Exception:
            return None
        if normalized in ("noitem", "none", ""):
            return None
        return normalized or None

    @staticmethod
    def _safe_moves_revealed(pokemon):
        """ITEM-2: extract revealed move IDs.
        Returns empty list if no revealed moves.

        Note: only VISIBLE moves (per poke-env)
        are returned. Hidden info is not exposed
        per AGENTS.md.

        poke-env ``Pokemon.moves`` is a ``MoveSet``
        (dict-like, id -> Move). Iterate values,
        not keys.
        """
        if pokemon is None:
            return []
        try:
            moves = getattr(pokemon, "moves", None)
        except Exception:
            moves = None
        if moves is None:
            return []
        out = []
        try:
            # MoveSet is dict-like; iterate values
            items = list(moves.values())
        except Exception:
            try:
                items = list(moves)
            except Exception:
                return out
        for mv in items:
            try:
                mid = getattr(mv, "id", None)
            except Exception:
                mid = None
            if mid is None:
                try:
                    mid = getattr(mv, "name", None)
                except Exception:
                    mid = None
            if mid is not None:
                try:
                    out.append(str(mid).lower())
                except Exception:
                    continue
        return out

    @staticmethod
    def _enum_keys(battle, attr):
        try:
            obj = getattr(battle, attr, None)
        except Exception:
            return [] if attr != "weather" else None
        if obj is None:
            return [] if attr != "weather" else None
        if isinstance(obj, dict):
            keys = []
            for k in obj.keys():
                try:
                    name = getattr(k, "name", None)
                except Exception:
                    name = None
                if name is None:
                    try:
                        name = str(k)
                    except Exception:
                        name = None
                if name:
                    keys.append(str(name).lower())
            return keys
        try:
            return [str(getattr(k, "name", str(k))).lower() for k in obj]
        except Exception:
            return [] if attr != "weather" else None

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
        # Phase BI-1: V4a audit telemetry. Compact form
        # so JSONL rows stay small.
        v4a = {
            "v4a_selected_joint_key": turn_data.get("v4a_selected_joint_key"),
            "v4a_final_action_keys": turn_data.get("v4a_final_action_keys") or [],
        }
        v4a_legal = turn_data.get("v4a_legal_action_keys_slot0")
        if v4a_legal is not None:
            v4a["v4a_legal_action_keys_slot0"] = v4a_legal
        v4a_legal_1 = turn_data.get("v4a_legal_action_keys_slot1")
        if v4a_legal_1 is not None:
            v4a["v4a_legal_action_keys_slot1"] = v4a_legal_1
        # Phase BEHAVIOR-9: speed-priority score-diff
        # debug subdict (compact, only present when
        # computed).
        sp_score_debug = {}
        for _s in (0, 1):
            _p = turn_data.get(f"speed_priority_protect_score_slot{_s}")
            _a = turn_data.get(f"speed_priority_best_attack_score_slot{_s}")
            _d = turn_data.get(f"speed_priority_score_diff_slot{_s}")
            if _p is not None:
                sp_score_debug.setdefault("protect_score", []).append(_p)
            elif "protect_score" in sp_score_debug:
                sp_score_debug["protect_score"].append(None)
            else:
                pass
            if _a is not None:
                sp_score_debug.setdefault("best_attack_score", []).append(_a)
            elif "best_attack_score" in sp_score_debug:
                sp_score_debug["best_attack_score"].append(None)
            else:
                pass
            if _d is not None:
                sp_score_debug.setdefault("score_diff", []).append(_d)
            elif "score_diff" in sp_score_debug:
                sp_score_debug["score_diff"].append(None)
            else:
                pass
        if sp_score_debug:
            v4a["speed_priority_score_debug"] = sp_score_debug
        # Phase BI-1: voluntary switch telemetry.
        vsw = {
            "voluntary_switch_decision_eligible": turn_data.get(
                "voluntary_switch_decision_eligible"
            )
            or [False, False],
            "voluntary_switch_selected": turn_data.get(
                "voluntary_switch_selected"
            )
            or [False, False],
            "voluntary_switch_candidate_count": turn_data.get(
                "voluntary_switch_candidate_count"
            )
            or [0, 0],
            "voluntary_switch_selected_species": turn_data.get(
                "voluntary_switch_selected_species"
            )
            or ["", ""],
        }
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
            "v4a": v4a,
            "voluntary_switch": vsw,
            "switch_counterfactual": turn_data.get("switch_counterfactual") or {},
            "state_snapshot": turn_data.get("state_snapshot") or {},
            "slot_0": self._compact_slot(turn_data.get("slot_0"), self._LIVE_SLOT_KEYS),
            "slot_1": self._compact_slot(turn_data.get("slot_1"), self._LIVE_SLOT_KEYS),
            # Phase CONTROL-PRIORITY-2D: anti-TR target debug
            # (target-aware + mechanics block audit). JSON-safe
            # list of dicts, or empty list if no candidates.
            "anti_tr_target_debug": turn_data.get("anti_tr_target_debug") or [],
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
        # Phase BEHAVIOR-17: per-turn Protect floor
        # diagnostic. JSON-safe dict with per-slot
        # pre/post floor scores and floor_applied flag.
        speed_priority_protect_floor_debug=None,
        protect_like_available=None,
        switch_available=None,
        only_conditional_priority=None,
        stalling_field_condition=None,
        # Phase SPREAD-2: per-slot spread-defense
        # legal/selected fields (Wide Guard / Quick
        # Guard / Crafty Shield) plus the per-turn
        # opp-pressure-state flag. Pure
        # observation; the existing 8-move
        # ``protect_like_available`` allowlist does
        # NOT include these 3 moves.
        wide_guard_legal=None,
        quick_guard_legal=None,
        crafty_shield_legal=None,
        spread_defense_selected=None,
        opp_pressure_state=None,
        # Phase SPREAD-4: per-slot spread-defense
        # raw scores + score-gap vs selected. Pure
        # observation; the dry-run simulator uses
        # these to compute decision-flip counts at
        # hypothetical bonus magnitudes.
        wide_guard_score=None,
        quick_guard_score=None,
        crafty_shield_score=None,
        score_gap_wide_guard_vs_selected=None,
        score_gap_quick_guard_vs_selected=None,
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
         # Phase COMBO-3: Ally-activation combo audit
         # fields. Per-slot lists of 2 booleans. All
         # default to [False, False] (or None) when the
         # bot does not pass them. The bot computes
         # these from the selected action and known
         # ally abilities/items at the audit call site.
         # - selected_move_into_known_absorb_ally:
         #   selected/final action targets ally and
         #   ally has known absorb/immunity for that
         #   move type.
         # - selected_move_into_known_redirect_ally:
         #   selected single-target move would be
         #   redirected by known ally Storm Drain /
         #   Lightning Rod.
         # - selected_super_effective_into_weakness_policy_holder:
         #   selected ally-targeted damaging move is
         #   super-effective AND ally has known
         #   Weakness Policy item (when item is
         #   observable).
         selected_move_into_known_absorb_ally=None,
         selected_move_into_known_redirect_ally=None,
         selected_super_effective_into_weakness_policy_holder=None,
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
        # V2l — runtime mode boundary metadata. The
        # canonical engine and the VGC runtime both
        # log to the same JSONL; these fields let the
        # parity inspector prove which engine
        # produced each record. ``runtime_mode`` is
        # either ``"random_doubles"`` (the canonical
        # format) or ``"vgc_selected_four"`` (the
        # VGC runtime after preview).
        runtime_mode=None,
        concrete_player_class=None,
        shared_engine_used=None,
        shared_engine_owner=None,
        selected_four=None,
        lead_2=None,
        back_2=None,
        preview_policy=None,
        # V2l.1 — execution-derived per-decision
        # parity evidence. The canonical
        # ``DoublesDamageAwarePlayer.choose_move`` writes
        # these fields into the live player attributes
        # right before calling ``log_turn_decision``.
        # ``shared_engine_used`` is True ONLY when a
        # non-empty ``shared_engine_invocation_id`` is
        # present (proof bit).
        shared_engine_invocation_id=None,
        shared_engine_invocation_status=None,
        v2l1_legal_action_keys_slot0=None,
        v2l1_legal_action_keys_slot1=None,
        v2l1_raw_scores_slot0=None,
        v2l1_raw_scores_slot1=None,
        v2l1_safety_blocks_slot0=None,
        v2l1_safety_blocks_slot1=None,
        v2l1_selected_joint_key=None,
        v2l1_final_action_keys=None,
        # Phase BEHAVIOR-9: speed-priority score-diff
        # debug fields. Computed by the logger from the
        # v2l1_raw_scores; no new scoring is done.
        speed_priority_protect_score_slot0=None,
        speed_priority_protect_score_slot1=None,
        speed_priority_best_attack_score_slot0=None,
        speed_priority_best_attack_score_slot1=None,
        speed_priority_score_diff_slot0=None,
        speed_priority_score_diff_slot1=None,
        # Phase V4a — RL/debug action identity.
        # These preserve one-per-side battle mechanic
        # variants such as Mega, Z-Move, Dynamax, and
        # Terastallize beside the older V2l.1 fields.
        v4a_legal_action_keys_slot0=None,
        v4a_legal_action_keys_slot1=None,
        v4a_raw_scores_slot0=None,
        v4a_raw_scores_slot1=None,
        v4a_selected_joint_key=None,
        v4a_final_action_keys=None,
        # Phase RL-DATA-3a.2: optional live move
        # metadata override. ``move_metadata_map_override``
        # is a dict mapping normalized move id to a
        # metadata dict (with ``base_power`` /
        # ``category`` / ``move_type`` / ``target`` /
        # ``metadata_source``). When provided, the
        # v1.1 emission prefers these entries over
        # the static fallback. The audit logger
        # stores the override on the turn_data so
        # downstream tools (builder, analyzer) can
        # see the live source. If absent, the v1.1
        # emission falls back to the static
        # resolver. Optional kwarg; the v1.0 audit
        # logging path is unchanged.
        move_metadata_map_override=None,
        # Phase 6.3.8b — Support Move Target Hard Safety.
        # ``support_target_candidates`` is the full
        # per-turn candidate table produced by the
        # canonical engine. The per-slot fields
        # mirror the candidate table for the
        # currently-selected action per slot so the
        # inspector and analyzer can read them
        # without iterating the candidate list.
        support_target_candidates=None,
        anti_tr_target_debug=None,
        support_target_candidate_blocked_slot0=None,
        support_target_candidate_blocked_slot1=None,
        support_target_selected_slot0=None,
        support_target_selected_slot1=None,
        support_target_avoided_slot0=None,
        support_target_avoided_slot1=None,
        support_target_only_legal_slot0=None,
        support_target_only_legal_slot1=None,
        support_target_move_id_slot0=None,
        support_target_move_id_slot1=None,
        support_target_intended_side_slot0=None,
        support_target_intended_side_slot1=None,
        support_target_actual_side_slot0=None,
        support_target_actual_side_slot1=None,
        support_target_target_position_slot0=None,
        support_target_target_position_slot1=None,
        support_target_target_species_slot0=None,
        support_target_target_species_slot1=None,
        support_target_block_reason_slot0=None,
        support_target_block_reason_slot1=None,
        support_target_classification_source_slot0=None,
        support_target_classification_source_slot1=None,
        support_target_blocked_candidate_score_slot0=None,
        support_target_blocked_candidate_score_slot1=None,
        support_target_safe_alternative_kind_slot0=None,
        support_target_safe_alternative_kind_slot1=None,
        support_target_safe_alternative_move_id_slot0=None,
        support_target_safe_alternative_move_id_slot1=None,
        support_target_safe_alternative_target_position_slot0=None,
        support_target_safe_alternative_target_position_slot1=None,
        support_target_wrong_side_selected_slot0=None,
        support_target_wrong_side_selected_slot1=None,
        # Phase 6.3.8d: Narrow ally-heal
        # candidate table. Same shape as
        # ``support_target_candidates`` (a list
        # of dicts). Includes every narrow-allowlist
        # order encountered on this turn, with
        # ``blocked`` and ``block_reason`` filled
        # by ``narrow_ally_heal_wrong_side_block``.
        narrow_ally_heal_candidates=None,
        # Phase 6.3.8d: Narrow ally-heal wrong-side
        # hard safety. Same mirror pattern as
        # ``support_target_*_slotN`` so the
        # inspector and analyzer can read
        # narrow-side decisions without iterating
        # the candidate list. The fields are
        # ``narrow_ally_heal_candidate`` (boolean:
        # did the engine generate a narrow
        # candidate this turn), the per-slot
        # ``narrow_ally_heal_blocked``,
        # ``narrow_ally_heal_selected``,
        # ``narrow_ally_heal_avoided``,
        # ``narrow_ally_heal_only_legal``, plus
        # the diagnostic move_id / intended_side /
        # actual_side / target_position /
        # target_species / reason / classification_source
        # mirrors.
        narrow_ally_heal_candidate=None,
        narrow_ally_heal_candidate_blocked_slot0=None,
        narrow_ally_heal_candidate_blocked_slot1=None,
        narrow_ally_heal_selected_slot0=None,
        narrow_ally_heal_selected_slot1=None,
        narrow_ally_heal_avoided_slot0=None,
        narrow_ally_heal_avoided_slot1=None,
        narrow_ally_heal_only_legal_slot0=None,
        narrow_ally_heal_only_legal_slot1=None,
        narrow_ally_heal_move_id_slot0=None,
        narrow_ally_heal_move_id_slot1=None,
        narrow_ally_heal_intended_side_slot0=None,
        narrow_ally_heal_intended_side_slot1=None,
        narrow_ally_heal_actual_side_slot0=None,
        narrow_ally_heal_actual_side_slot1=None,
        narrow_ally_heal_target_position_slot0=None,
        narrow_ally_heal_target_position_slot1=None,
        narrow_ally_heal_target_species_slot0=None,
        narrow_ally_heal_target_species_slot1=None,
        narrow_ally_heal_block_reason_slot0=None,
        narrow_ally_heal_block_reason_slot1=None,
        narrow_ally_heal_classification_source_slot0=None,
        narrow_ally_heal_classification_source_slot1=None,
        # Phase 6.3.8b — Per-slot selected-action
        # structured metadata (kind / move id / target
        # position / species / only-legal). These are
        # the canonical per-slot fields the inspector
        # and benchmark use. The audit logger was
        # previously dropping them via ``**kwargs``;
        # the inspector and benchmark read them
        # directamente off each slot's dict.
        selected_action_kind=None,
        selected_action_move_id=None,
        selected_action_target_position=None,
        selected_action_species=None,
        selected_action_only_legal=None,
        selected_action_mechanic=None,
        # Phase 6.4.10c.1: VSW candidate and raw
        # switch order counts per slot.
        voluntary_switch_raw_switch_order_count=None,
        voluntary_switch_candidate_count=None,
        # Phase BI-1: voluntary switch eligibility /
        # selection / species telemetry. The bot's
        # audit call has always passed these as kwargs;
        # adding them to the signature prevents them
        # from being dropped via **kwargs and lets us
        # write them to turn_data and the live JSONL.
        voluntary_switch_decision_eligible=None,
        voluntary_switch_selected=None,
        voluntary_switch_selected_species=None,
        # Phase BI-2D: compact per-slot switch
        # counterfactual sub-dict. The bot assembles
        # this from existing _vsw_* locals; the logger
        # stores it as-is and projects it into the
        # live decision event.
        switch_counterfactual=None,
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
            "state_snapshot": self._build_compact_state_snapshot(
                battle, battle_tag
            ),
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
                # Phase 6.3.8b — Per-slot selected-action
                # structured metadata.
                "selected_action_kind": (
                    (selected_action_kind or [None, None])[0]
                ),
                "selected_action_move_id": (
                    (selected_action_move_id or [None, None])[0]
                ),
                "selected_action_target_position": (
                    (selected_action_target_position or [0, 0])[0]
                ),
                "selected_action_species": (
                    (selected_action_species or [None, None])[0]
                ),
                "selected_action_only_legal": (
                    (selected_action_only_legal or [False, False])[0]
                ),
                "selected_action_mechanic": (
                    (selected_action_mechanic or ["", ""])[0]
                ),
                "expected_damage": float(expected_damages[0]) if expected_damages[0] is not None else None,
                "expected_ko": bool(expected_kos[0]) if expected_kos[0] is not None else None,
                "target_hp_before": float(target_hps[0]) if target_hps[0] is not None else None,
                "target_species": target_species[0],
                "spread_available": bool(spread_available[0]),
                "best_spread_score": float(best_spread_score[0]) if best_spread_score[0] is not None else None,
                "best_ko_score": float(best_ko_score[0]) if best_ko_score[0] is not None else None,
                # Phase SPREAD-2: per-slot spread-defense
                # legal/selected fields. Wide Guard /
                # Quick Guard / Crafty Shield are NOT
                # in the 8-move protect-like allowlist
                # so they need their own per-slot
                # booleans. Pure observation; no
                # scoring change.
                "wide_guard_legal": bool(wide_guard_legal[0]) if (wide_guard_legal and len(wide_guard_legal) > 0) else False,
                "quick_guard_legal": bool(quick_guard_legal[0]) if (quick_guard_legal and len(quick_guard_legal) > 0) else False,
                "crafty_shield_legal": bool(crafty_shield_legal[0]) if (crafty_shield_legal and len(crafty_shield_legal) > 0) else False,
                "spread_defense_selected": str(spread_defense_selected[0]) if (spread_defense_selected and len(spread_defense_selected) > 0) else "",
                # Phase SPREAD-4: per-slot spread-defense
                # raw score. None when candidate not
                # legal.
                "wide_guard_score": float(wide_guard_score[0]) if (wide_guard_score is not None and len(wide_guard_score) > 0 and wide_guard_score[0] is not None) else None,
                "quick_guard_score": float(quick_guard_score[0]) if (quick_guard_score is not None and len(quick_guard_score) > 0 and quick_guard_score[0] is not None) else None,
                "crafty_shield_score": float(crafty_shield_score[0]) if (crafty_shield_score is not None and len(crafty_shield_score) > 0 and crafty_shield_score[0] is not None) else None,
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
                 # Phase COMBO-3: ally-activation combo
                 # audit. Per-slot booleans. When the
                 # bot does not pass these (default
                 # None), the audit field is False.
                 "selected_move_into_known_absorb_ally": bool(selected_move_into_known_absorb_ally[0]) if selected_move_into_known_absorb_ally else False,
                 "selected_move_into_known_redirect_ally": bool(selected_move_into_known_redirect_ally[0]) if selected_move_into_known_redirect_ally else False,
                 "selected_super_effective_into_weakness_policy_holder": bool(selected_super_effective_into_weakness_policy_holder[0]) if selected_super_effective_into_weakness_policy_holder else False,
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
                # Phase 6.3.8b — Per-slot selected-action
                # structured metadata.
                "selected_action_kind": (
                    (selected_action_kind or [None, None])[1]
                ),
                "selected_action_move_id": (
                    (selected_action_move_id or [None, None])[1]
                ),
                "selected_action_target_position": (
                    (selected_action_target_position or [0, 0])[1]
                ),
                "selected_action_species": (
                    (selected_action_species or [None, None])[1]
                ),
                "selected_action_only_legal": (
                    (selected_action_only_legal or [False, False])[1]
                ),
                "selected_action_mechanic": (
                    (selected_action_mechanic or ["", ""])[1]
                ),
                "expected_damage": float(expected_damages[1]) if expected_damages[1] is not None else None,
                "expected_ko": bool(expected_kos[1]) if expected_kos[1] is not None else None,
                "target_hp_before": float(target_hps[1]) if target_hps[1] is not None else None,
                "target_species": target_species[1],
                "spread_available": bool(spread_available[1]),
                "best_spread_score": float(best_spread_score[1]) if best_spread_score[1] is not None else None,
                "best_ko_score": float(best_ko_score[1]) if best_ko_score[1] is not None else None,
                # Phase SPREAD-2: per-slot spread-defense
                # mirror (slot 1).
                "wide_guard_legal": bool(wide_guard_legal[1]) if (wide_guard_legal and len(wide_guard_legal) > 1) else False,
                "quick_guard_legal": bool(quick_guard_legal[1]) if (quick_guard_legal and len(quick_guard_legal) > 1) else False,
                "crafty_shield_legal": bool(crafty_shield_legal[1]) if (crafty_shield_legal and len(crafty_shield_legal) > 1) else False,
                "spread_defense_selected": str(spread_defense_selected[1]) if (spread_defense_selected and len(spread_defense_selected) > 1) else "",
                # Phase SPREAD-4: per-slot score mirror.
                "wide_guard_score": float(wide_guard_score[1]) if (wide_guard_score is not None and len(wide_guard_score) > 1 and wide_guard_score[1] is not None) else None,
                "quick_guard_score": float(quick_guard_score[1]) if (quick_guard_score is not None and len(quick_guard_score) > 1 and quick_guard_score[1] is not None) else None,
                "crafty_shield_score": float(crafty_shield_score[1]) if (crafty_shield_score is not None and len(crafty_shield_score) > 1 and crafty_shield_score[1] is not None) else None,
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
                 # Phase COMBO-3: ally-activation combo
                 # audit. Per-slot booleans. When the
                 # bot does not pass these (default
                 # None), the audit field is False.
                 "selected_move_into_known_absorb_ally": bool(selected_move_into_known_absorb_ally[1]) if selected_move_into_known_absorb_ally else False,
                 "selected_move_into_known_redirect_ally": bool(selected_move_into_known_redirect_ally[1]) if selected_move_into_known_redirect_ally else False,
                 "selected_super_effective_into_weakness_policy_holder": bool(selected_super_effective_into_weakness_policy_holder[1]) if selected_super_effective_into_weakness_policy_holder else False,
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
                # Phase SPREAD-2: spread-defense
                # outcome fields. Computed by the
                # outcome resolver from the turn
                # events. Pure observation; no scoring
                # change.
                "opponent_used_spread": False,
                "opponent_used_protect": False,
                "opponent_used_wide_guard": False,
                "opponent_used_quick_guard": False,
                # Phase COUNTER-2: per-turn opponent
                # setup-move tracking. Per-move fields
                # for the eight explicit COUNTER-1
                # signals (speed_setup / redirection /
                # tempo_disruption), plus four
                # per-category fields for the broader
                # detection. All default False and
                # computed from the same turn-events
                # stream that powers
                # opponent_used_spread / _protect.
                # Pure observation; no scoring change.
                "opponent_used_tailwind": False,
                "opponent_used_trickroom": False,
                "opponent_used_followme": False,
                "opponent_used_ragepowder": False,
                "opponent_used_fakeout": False,
                "opponent_used_encore": False,
                "opponent_used_taunt": False,
                "opponent_used_quash": False,
                "opponent_used_stat_boost_setup": False,
                "opponent_used_screen_setup": False,
                "opponent_used_ally_activation_move": False,
                "opponent_used_absorb_redirect_ally": False,
            },
            # Phase 6.4.10c.1: VSW candidate and raw
            # switch order counts per slot. The
            # analyzer computes extraction mismatch
            # as raw != cand.
            "voluntary_switch_raw_switch_order_count": (
                list(voluntary_switch_raw_switch_order_count)
                if voluntary_switch_raw_switch_order_count is not None
                else [0, 0]
            ),
            "voluntary_switch_candidate_count": (
                list(voluntary_switch_candidate_count)
                if voluntary_switch_candidate_count is not None
                else [0, 0]
            ),
            # Phase BI-1: VSW eligibility / selection /
            # species telemetry. Previously dropped via
            # **kwargs. Compact form: per-slot list
            # (slot 0, slot 1) where applicable, scalar
            # where the bot emits a scalar.
            "voluntary_switch_decision_eligible": (
                list(voluntary_switch_decision_eligible)
                if voluntary_switch_decision_eligible is not None
                else [False, False]
            ),
            "voluntary_switch_selected": (
                list(voluntary_switch_selected)
                if voluntary_switch_selected is not None
                else [False, False]
            ),
            "voluntary_switch_selected_species": (
                list(voluntary_switch_selected_species)
                if voluntary_switch_selected_species is not None
                else ["", ""]
            ),
            # Phase BI-2D: compact per-slot switch
            # counterfactual sub-dict. Stored as-is
            # from the bot's assembled payload. The
            # helper assembles JSON-safe primitives
            # already; we keep None as a safe default
            # so existing call sites that omit the
            # kwarg continue to work.
            "switch_counterfactual": (
                switch_counterfactual
                if switch_counterfactual is not None
                else None
            ),

        }

        if self.detail_level == "full":
            turn_data["all_legal_joint_orders"] = [
                {"message": jo.message if jo else "/choose pass", "score": float(sc)}
                for jo, sc, _, _ in scored_joint_orders
            ]

        # V2l — runtime mode boundary audit metadata.
        # These fields are recorded for every turn so
        # the parity inspector can prove which engine
        # produced the decision and what runtime mode
        # was active. ``shared_engine_used`` must be
        # True for both random_doubles and
        # vgc_selected_four; a False value is a hard
        # parity violation.
        turn_data["runtime_mode"] = runtime_mode
        turn_data["concrete_player_class"] = (
            concrete_player_class
        )
        # V2l.1 — ``shared_engine_used`` is overridden
        # here so a non-empty invocation id is the
        # PROOF. A legacy caller that does not flow
        # through ``choose_move`` will not have an
        # invocation id and will report
        # ``shared_engine_used=False``.
        invocation_completed = (
            bool(shared_engine_invocation_id)
            and shared_engine_invocation_status == "completed"
        )
        if invocation_completed:
            turn_data["shared_engine_used"] = True
        else:
            turn_data["shared_engine_used"] = False
        turn_data["shared_engine_owner"] = shared_engine_owner
        turn_data["shared_engine_invocation_id"] = (
            shared_engine_invocation_id
        )
        turn_data["shared_engine_invocation_status"] = (
            shared_engine_invocation_status
        )
        turn_data["selected_four"] = selected_four
        turn_data["lead_2"] = lead_2
        turn_data["back_2"] = back_2
        turn_data["preview_policy"] = preview_policy
        # V2l.1 — per-decision parity evidence. These
        # are JSON-serializable strings / dicts, not
        # ``BattleOrder`` objects.
        turn_data["v2l1_legal_action_keys_slot0"] = (
            v2l1_legal_action_keys_slot0
        )
        turn_data["v2l1_legal_action_keys_slot1"] = (
            v2l1_legal_action_keys_slot1
        )
        turn_data["v2l1_raw_scores_slot0"] = (
            v2l1_raw_scores_slot0
        )
        turn_data["v2l1_raw_scores_slot1"] = (
            v2l1_raw_scores_slot1
        )
        # Phase BEHAVIOR-9: compute and persist
        # speed-priority score-diff debug fields from
        # the v2l1_raw_scores. No new scoring is done.
        for _slot_idx, _raw_key in (
            (0, "v2l1_raw_scores_slot0"),
            (1, "v2l1_raw_scores_slot1"),
        ):
            _p, _a, _d = _compute_slot_score_diff(
                turn_data.get(_raw_key)
            )
            if _p is not None:
                turn_data[
                    f"speed_priority_protect_score_slot{_slot_idx}"
                ] = _p
            if _a is not None:
                turn_data[
                    f"speed_priority_best_attack_score_slot{_slot_idx}"
                ] = _a
            if _d is not None:
                turn_data[
                    f"speed_priority_score_diff_slot{_slot_idx}"
                ] = _d
        turn_data["v2l1_safety_blocks_slot0"] = (
            v2l1_safety_blocks_slot0
        )
        turn_data["v2l1_safety_blocks_slot1"] = (
            v2l1_safety_blocks_slot1
        )
        turn_data["v2l1_selected_joint_key"] = (
            v2l1_selected_joint_key
        )
        turn_data["v2l1_final_action_keys"] = (
            v2l1_final_action_keys
        )
        turn_data["v4a_legal_action_keys_slot0"] = (
            v4a_legal_action_keys_slot0
        )
        turn_data["v4a_legal_action_keys_slot1"] = (
            v4a_legal_action_keys_slot1
        )
        turn_data["v4a_raw_scores_slot0"] = (
            v4a_raw_scores_slot0
        )
        turn_data["v4a_raw_scores_slot1"] = (
            v4a_raw_scores_slot1
        )
        turn_data["v4a_selected_joint_key"] = (
            v4a_selected_joint_key
        )
        turn_data["v4a_final_action_keys"] = (
            v4a_final_action_keys
        )
        # Phase RL-DATA-3a.2: stash the optional
        # ``move_metadata_map_override`` on the
        # turn_data so the v1.1 emission can
        # prefer live metadata over the static
        # fallback. The override is normalized in
        # ``_populate_v1_1_move_metadata_map``
        # (lazy import, try/except wrap).
        if move_metadata_map_override is not None:
            turn_data["_v11_move_metadata_override_raw"] = (
                move_metadata_map_override
            )
        # Phase 6.3.8b — Support Move Target Hard Safety
        # audit fields. The full candidate table is
        # written for the analyzer to iterate; the
        # per-slot fields are mirrored so the
        # inspector and per-slot counter can read
        # them without list iteration.
        turn_data["support_target_candidates"] = (
            support_target_candidates or []
        )
        turn_data["anti_tr_target_debug"] = (
            list(anti_tr_target_debug) if anti_tr_target_debug else []
        )
        turn_data["support_target_candidate_blocked"] = (
            bool(support_target_candidate_blocked_slot0)
            or bool(support_target_candidate_blocked_slot1)
        )
        # Per-slot mirror fields
        _per_slot_support_keys = {
            "support_target_candidate_blocked_slot0":
                support_target_candidate_blocked_slot0,
            "support_target_candidate_blocked_slot1":
                support_target_candidate_blocked_slot1,
            "support_target_selected_slot0":
                support_target_selected_slot0,
            "support_target_selected_slot1":
                support_target_selected_slot1,
            "support_target_avoided_slot0":
                support_target_avoided_slot0,
            "support_target_avoided_slot1":
                support_target_avoided_slot1,
            "support_target_only_legal_slot0":
                support_target_only_legal_slot0,
            "support_target_only_legal_slot1":
                support_target_only_legal_slot1,
            "support_target_move_id_slot0":
                support_target_move_id_slot0,
            "support_target_move_id_slot1":
                support_target_move_id_slot1,
            "support_target_intended_side_slot0":
                support_target_intended_side_slot0,
            "support_target_intended_side_slot1":
                support_target_intended_side_slot1,
            "support_target_actual_side_slot0":
                support_target_actual_side_slot0,
            "support_target_actual_side_slot1":
                support_target_actual_side_slot1,
            "support_target_target_position_slot0":
                support_target_target_position_slot0,
            "support_target_target_position_slot1":
                support_target_target_position_slot1,
            "support_target_target_species_slot0":
                support_target_target_species_slot0,
            "support_target_target_species_slot1":
                support_target_target_species_slot1,
            "support_target_block_reason_slot0":
                support_target_block_reason_slot0,
            "support_target_block_reason_slot1":
                support_target_block_reason_slot1,
            "support_target_classification_source_slot0":
                support_target_classification_source_slot0,
            "support_target_classification_source_slot1":
                support_target_classification_source_slot1,
            "support_target_blocked_candidate_score_slot0":
                support_target_blocked_candidate_score_slot0,
            "support_target_blocked_candidate_score_slot1":
                support_target_blocked_candidate_score_slot1,
            "support_target_safe_alternative_kind_slot0":
                support_target_safe_alternative_kind_slot0,
            "support_target_safe_alternative_kind_slot1":
                support_target_safe_alternative_kind_slot1,
            "support_target_safe_alternative_move_id_slot0":
                support_target_safe_alternative_move_id_slot0,
            "support_target_safe_alternative_move_id_slot1":
                support_target_safe_alternative_move_id_slot1,
            "support_target_safe_alternative_target_position_slot0":
                support_target_safe_alternative_target_position_slot0,
            "support_target_safe_alternative_target_position_slot1":
                support_target_safe_alternative_target_position_slot1,
            "support_target_wrong_side_selected_slot0":
                support_target_wrong_side_selected_slot0,
            "support_target_wrong_side_selected_slot1":
                support_target_wrong_side_selected_slot1,
        }
        for _k, _v in _per_slot_support_keys.items():
            turn_data[_k] = _v
        # Phase 6.3.8d: Narrow ally-heal wrong-side
        # per-slot mirrors. Same pattern as the
        # broad support-target fields above.
        _narrow_per_slot_keys = {
            "narrow_ally_heal_candidate":
                narrow_ally_heal_candidate,
            "narrow_ally_heal_candidate_blocked_slot0":
                narrow_ally_heal_candidate_blocked_slot0,
            "narrow_ally_heal_candidate_blocked_slot1":
                narrow_ally_heal_candidate_blocked_slot1,
            "narrow_ally_heal_selected_slot0":
                narrow_ally_heal_selected_slot0,
            "narrow_ally_heal_selected_slot1":
                narrow_ally_heal_selected_slot1,
            "narrow_ally_heal_avoided_slot0":
                narrow_ally_heal_avoided_slot0,
            "narrow_ally_heal_avoided_slot1":
                narrow_ally_heal_avoided_slot1,
            "narrow_ally_heal_only_legal_slot0":
                narrow_ally_heal_only_legal_slot0,
            "narrow_ally_heal_only_legal_slot1":
                narrow_ally_heal_only_legal_slot1,
            "narrow_ally_heal_move_id_slot0":
                narrow_ally_heal_move_id_slot0,
            "narrow_ally_heal_move_id_slot1":
                narrow_ally_heal_move_id_slot1,
            "narrow_ally_heal_intended_side_slot0":
                narrow_ally_heal_intended_side_slot0,
            "narrow_ally_heal_intended_side_slot1":
                narrow_ally_heal_intended_side_slot1,
            "narrow_ally_heal_actual_side_slot0":
                narrow_ally_heal_actual_side_slot0,
            "narrow_ally_heal_actual_side_slot1":
                narrow_ally_heal_actual_side_slot1,
            "narrow_ally_heal_target_position_slot0":
                narrow_ally_heal_target_position_slot0,
            "narrow_ally_heal_target_position_slot1":
                narrow_ally_heal_target_position_slot1,
            "narrow_ally_heal_target_species_slot0":
                narrow_ally_heal_target_species_slot0,
            "narrow_ally_heal_target_species_slot1":
                narrow_ally_heal_target_species_slot1,
            "narrow_ally_heal_block_reason_slot0":
                narrow_ally_heal_block_reason_slot0,
            "narrow_ally_heal_block_reason_slot1":
                narrow_ally_heal_block_reason_slot1,
            "narrow_ally_heal_classification_source_slot0":
                narrow_ally_heal_classification_source_slot0,
            "narrow_ally_heal_classification_source_slot1":
                narrow_ally_heal_classification_source_slot1,
        }
        for _k, _v in _narrow_per_slot_keys.items():
            turn_data[_k] = _v
        # Phase BEHAVIOR-3: Persist speed-priority threat
        # fields at the top level so the turn-level
        # analyzer can read them. Shapes:
        # - speed_priority_threatened: [slot0_bool, slot1_bool]
        # - faster_opponents: [slot0_list, slot1_list] (species)
        # - priority_opponents: [slot0_list, slot1_list] (species)
        # - expected_to_faint_before_moving: [slot0_bool, slot1_bool]
        # - protected_due_to_speed_priority: [slot0_bool, slot1_bool]
        # - speed_priority_protect_bonus_applied: [slot0_bool, slot1_bool]
        # - speed_priority_attack_penalty_applied: [slot0_bool, slot1_bool]
        # - speed_priority_switch_bonus_applied: [slot0_bool, slot1_bool]
        # - target_used_protect: [slot0_bool, slot1_bool]
        # No hidden info: species names only, no
        # abilities/items/EVs/nature.
        if speed_priority_threatened is not None:
            turn_data["speed_priority_threatened"] = [
                bool(speed_priority_threatened[0])
                if len(speed_priority_threatened) > 0
                else False,
                bool(speed_priority_threatened[1])
                if len(speed_priority_threatened) > 1
                else False,
            ]
        if faster_opponents is not None:
            turn_data["faster_opponents"] = [
                list(faster_opponents[0])
                if (len(faster_opponents) > 0
                    and faster_opponents[0])
                else [],
                list(faster_opponents[1])
                if (len(faster_opponents) > 1
                    and faster_opponents[1])
                else [],
            ]
        if priority_opponents is not None:
            turn_data["priority_opponents"] = [
                list(priority_opponents[0])
                if (len(priority_opponents) > 0
                    and priority_opponents[0])
                else [],
                list(priority_opponents[1])
                if (len(priority_opponents) > 1
                    and priority_opponents[1])
                else [],
            ]
        if expected_to_faint_before_moving is not None:
            turn_data["expected_to_faint_before_moving"] = [
                bool(expected_to_faint_before_moving[0])
                if len(expected_to_faint_before_moving) > 0
                else False,
                bool(expected_to_faint_before_moving[1])
                if len(expected_to_faint_before_moving) > 1
                else False,
            ]
        if protected_due_to_speed_priority is not None:
            turn_data["protected_due_to_speed_priority"] = [
                bool(protected_due_to_speed_priority[0])
                if len(protected_due_to_speed_priority) > 0
                else False,
                bool(protected_due_to_speed_priority[1])
                if len(protected_due_to_speed_priority) > 1
                else False,
            ]
        if speed_priority_protect_bonus_applied is not None:
            turn_data["speed_priority_protect_bonus_applied"] = [
                bool(speed_priority_protect_bonus_applied[0])
                if len(speed_priority_protect_bonus_applied) > 0
                else False,
                bool(speed_priority_protect_bonus_applied[1])
                if len(speed_priority_protect_bonus_applied) > 1
                else False,
            ]
        if speed_priority_attack_penalty_applied is not None:
            turn_data["speed_priority_attack_penalty_applied"] = [
                bool(speed_priority_attack_penalty_applied[0])
                if len(speed_priority_attack_penalty_applied) > 0
                else False,
                bool(speed_priority_attack_penalty_applied[1])
                if len(speed_priority_attack_penalty_applied) > 1
                else False,
            ]
        if speed_priority_switch_bonus_applied is not None:
            turn_data["speed_priority_switch_bonus_applied"] = [
                bool(speed_priority_switch_bonus_applied[0])
                if len(speed_priority_switch_bonus_applied) > 0
                else False,
                bool(speed_priority_switch_bonus_applied[1])
                if len(speed_priority_switch_bonus_applied) > 1
                else False,
            ]
        # Phase BEHAVIOR-17: persist the Protect floor
        # diagnostic if provided. JSON-safe dict.
        if speed_priority_protect_floor_debug is not None:
            turn_data["speed_priority_protect_floor_debug"] = (
                speed_priority_protect_floor_debug
            )
        # Phase SPREAD-2: persist the top-level
        # opp-pressure-state boolean (any live opp
        # has a revealed spread move and is healthy
        # enough to use it). Pure observation; no
        # scoring change.
        if opp_pressure_state is not None:
            turn_data["opp_pressure_state"] = bool(opp_pressure_state)
        # Phase SPREAD-4: persist score-gap lists at
        # top level so the dry-run simulator can
        # compute decision-flip counts.
        if score_gap_wide_guard_vs_selected is not None:
            turn_data["score_gap_wide_guard_vs_selected"] = [
                float(score_gap_wide_guard_vs_selected[0])
                if (
                    len(score_gap_wide_guard_vs_selected) > 0
                    and score_gap_wide_guard_vs_selected[0]
                    is not None
                )
                else None,
                float(score_gap_wide_guard_vs_selected[1])
                if (
                    len(score_gap_wide_guard_vs_selected) > 1
                    and score_gap_wide_guard_vs_selected[1]
                    is not None
                )
                else None,
            ]
        if score_gap_quick_guard_vs_selected is not None:
            turn_data["score_gap_quick_guard_vs_selected"] = [
                float(score_gap_quick_guard_vs_selected[0])
                if (
                    len(score_gap_quick_guard_vs_selected) > 0
                    and score_gap_quick_guard_vs_selected[0]
                    is not None
                )
                else None,
                float(score_gap_quick_guard_vs_selected[1])
                if (
                    len(score_gap_quick_guard_vs_selected) > 1
                    and score_gap_quick_guard_vs_selected[1]
                    is not None
                )
                else None,
            ]



        # Phase 6.3.8d: Persist the full narrow
        # candidate table for analyzer inspection.
        # The broad support_target_candidates is
        # also persisted; we mirror that pattern.
        turn_data["narrow_ally_heal_candidates"] = (
            list(narrow_ally_heal_candidates)
            if narrow_ally_heal_candidates is not None
            else []
        )
        # Per-slot flat fields for the inspector
        # (which reads e.g.
        # ``support_target_selected`` directamente off the
        # slot). We forward the per-slot mirror to
        # each slot_0 / slot_1 dict.
        for _slot_key, _slot_idx in (("slot_0", 0), ("slot_1", 1)):
            _slot = turn_data.get(_slot_key, {})
            if not isinstance(_slot, dict):
                continue
            _slot["support_target_candidate_blocked"] = (
                turn_data.get(
                    f"support_target_candidate_blocked_slot{_slot_idx}"
                )
            )
            _slot["support_target_selected"] = (
                turn_data.get(
                    f"support_target_selected_slot{_slot_idx}"
                )
            )
            _slot["support_target_avoided"] = (
                turn_data.get(
                    f"support_target_avoided_slot{_slot_idx}"
                )
            )
            _slot["support_target_only_legal"] = (
                turn_data.get(
                    f"support_target_only_legal_slot{_slot_idx}"
                )
            )
            _slot["support_target_move_id"] = (
                turn_data.get(
                    f"support_target_move_id_slot{_slot_idx}"
                )
            )
            _slot["support_target_intended_side"] = (
                turn_data.get(
                    f"support_target_intended_side_slot{_slot_idx}"
                )
            )
            _slot["support_target_actual_side"] = (
                turn_data.get(
                    f"support_target_actual_side_slot{_slot_idx}"
                )
            )
            _slot["support_target_target_position"] = (
                turn_data.get(
                    f"support_target_target_position_slot{_slot_idx}"
                )
            )
            _slot["support_target_target_species"] = (
                turn_data.get(
                    f"support_target_target_species_slot{_slot_idx}"
                )
            )
            _slot["support_target_reason"] = (
                turn_data.get(
                    f"support_target_block_reason_slot{_slot_idx}"
                )
            )
            _slot["support_target_classification_source"] = (
                turn_data.get(
                    f"support_target_classification_source_slot{_slot_idx}"
                )
            )
            _slot["support_target_blocked_candidate_score"] = (
                turn_data.get(
                    f"support_target_blocked_candidate_score_slot{_slot_idx}"
                )
            )
            _slot["support_target_safe_alternative_kind"] = (
                turn_data.get(
                    f"support_target_safe_alternative_kind_slot{_slot_idx}"
                )
            )
            _slot["support_target_safe_alternative_move_id"] = (
                turn_data.get(
                    f"support_target_safe_alternative_move_id_slot{_slot_idx}"
                )
            )
            _slot["support_target_safe_alternative_target_position"] = (
                turn_data.get(
                    f"support_target_safe_alternative_target_position_slot{_slot_idx}"
                )
            )
            _slot["support_target_wrong_side_selected"] = (
                turn_data.get(
                    f"support_target_wrong_side_selected_slot{_slot_idx}"
                )
            )
            # Phase 6.3.8d: Narrow ally-heal wrong-side
            # per-slot mirror. Same key naming as the
            # broad support-target fields.
            _slot["narrow_ally_heal_candidate_blocked"] = (
                turn_data.get(
                    f"narrow_ally_heal_candidate_blocked_slot{_slot_idx}"
                )
            )
            _slot["narrow_ally_heal_selected"] = (
                turn_data.get(
                    f"narrow_ally_heal_selected_slot{_slot_idx}"
                )
            )
            _slot["narrow_ally_heal_avoided"] = (
                turn_data.get(
                    f"narrow_ally_heal_avoided_slot{_slot_idx}"
                )
            )
            _slot["narrow_ally_heal_only_legal"] = (
                turn_data.get(
                    f"narrow_ally_heal_only_legal_slot{_slot_idx}"
                )
            )
            _slot["narrow_ally_heal_move_id"] = (
                turn_data.get(
                    f"narrow_ally_heal_move_id_slot{_slot_idx}"
                )
            )
            _slot["narrow_ally_heal_intended_side"] = (
                turn_data.get(
                    f"narrow_ally_heal_intended_side_slot{_slot_idx}"
                )
            )
            _slot["narrow_ally_heal_actual_side"] = (
                turn_data.get(
                    f"narrow_ally_heal_actual_side_slot{_slot_idx}"
                )
            )
            _slot["narrow_ally_heal_target_position"] = (
                turn_data.get(
                    f"narrow_ally_heal_target_position_slot{_slot_idx}"
                )
            )
            _slot["narrow_ally_heal_target_species"] = (
                turn_data.get(
                    f"narrow_ally_heal_target_species_slot{_slot_idx}"
                )
            )
            _slot["narrow_ally_heal_reason"] = (
                turn_data.get(
                    f"narrow_ally_heal_block_reason_slot{_slot_idx}"
                )
            )
            _slot["narrow_ally_heal_classification_source"] = (
                turn_data.get(
                    f"narrow_ally_heal_classification_source_slot{_slot_idx}"
                )
            )
            turn_data[_slot_key] = _slot

        # Phase RL-DATA-3a: emit the ``turn_rl_v1.1``
        # instrumentation fields directly into the
        # turn_data dict. The persisted JSONL therefore
        # carries the v1.1 fields; the builder's
        # ``_extract_v1_1_*`` helpers will read them
        # from ``turn.get("xxx")`` and pass them
        # through. The v1.1 emission is observational
        # only: it does not change scoring, behavior,
        # or selected actions. ``used_species_ability_inference``
        # is hardcoded to ``False`` and
        # ``local_only_provenance`` is hardcoded to
        # ``True``.
        self._emit_v1_1_fields(turn_data)

        self.pending_turns[battle_tag] = turn_data
        self._append_live_event(self._build_live_decision_event(battle_tag, turn_data))

    def update_pending_turn_with_live_exploration(
        self,
        battle_tag,
        turn,
        explored_selected_joint_order,
        explored_v4a_selected_joint_key,
        live_exploration_state,
    ):
        """
        Update the pending turn for ``battle_tag`` with
        live exploration metadata and the explored
        order. This is called by
        ``LiveExplorationDoublesDamageAwarePlayer``
        after the parent's ``choose_move`` returns the
        original (non-explored) order. The explored
        order is what will actually be submitted to the
        server (true trajectory). The audit record's
        ``selected_joint_order`` and
        ``v4a_selected_joint_key`` are updated to the
        explored order so the audit correctly reflects
        the action that was sent.

        If no pending turn exists (e.g. the parent's
        ``choose_move`` was not yet called), this is a
        no-op. If the pending turn is for a different
        turn number, it is also a no-op.
        """
        pending = self.pending_turns.get(battle_tag)
        if not pending:
            return
        if pending.get("turn") != turn:
            return
        # Update the selected order to the explored order
        pending["selected_joint_order"] = str(
            explored_selected_joint_order
        )
        pending["v4a_selected_joint_key"] = (
            explored_v4a_selected_joint_key
        )
        # Emit the live_exploration fields
        for key, value in live_exploration_state.items():
            pending[key] = value
        # Update the v1.1 emission so the dataset
        # builder sees the explored action
        # (v4a_selected_joint_key is already updated).

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

            # Phase SPREAD-2: detect opponent spread /
            # protect / wide_guard / quick_guard usage
            # from the same turn events. Pure
            # observation; persisted into
            # ``opp_actions``. The allowlists are
            # stable (no per-call mutation) so they
            # are evaluated inline here.
            _OPP_SPREAD_LIKE = frozenset({
                "hypervoice", "rockslide", "heatwave",
                "blizzard", "clangsour", "clangingscales",
                "dazzlinggleam", "muddywater", "snarl",
                "expandforce", "makeitrain", "glare",
                "icywind", "acidspray", "strugglebug",
                "waterspout", "eruption", "dragondarts",
                "earthquake", "surf", "discharge",
                "mindblown", "teeterdance",
            })
            _OPP_PROTECT_LIKE = frozenset({
                "protect", "detect", "spikyshield",
                "kingsshield", "banefulbunker", "silktrap",
                "burningbulwark", "maxguard", "obstruct",
            })
            for msg in turn_events:
                if len(msg) >= 3 and msg[0] == "move" and msg[1].startswith(opp_role):
                    move_name = self._normalize_name(msg[2])
                    if move_name == "wideguard":
                        opp_actions["opponent_used_wide_guard"] = True
                    if move_name == "quickguard":
                        opp_actions["opponent_used_quick_guard"] = True
                    if move_name in _OPP_PROTECT_LIKE:
                        opp_actions["opponent_used_protect"] = True
                    if move_name in _OPP_SPREAD_LIKE:
                        opp_actions["opponent_used_spread"] = True

            # Phase COUNTER-2: detect opponent setup
            # moves from the same turn events.
            # Per-move fields for the eight explicit
            # COUNTER-1 signals, plus three
            # per-category fields. Pure observation;
            # no scoring change. The speed_setup
            # category (tailwind / trickroom) is
            # covered by per-move fields
            # (``opponent_used_tailwind`` /
            # ``opponent_used_trickroom``), so no
            # separate category field is needed.
            _OPP_REDIRECTION = frozenset({
                "followme", "ragepowder",
            })
            _OPP_TEMPO_DISRUPT = frozenset({
                "fakeout", "encore", "taunt", "quash",
            })
            _OPP_STAT_BOOST = frozenset({
                "swordsdance", "nastyplot",
                "dragondance", "calmmind", "bulkup",
                "quiverdance", "shellsmash",
                "workup", "agility", "cosmicpower",
                "geomancy", "honeclaws", "charge",
                "rockpolish", "growth", "howl",
                "doubleteam", "acidarmor",
                "irondefense", "minimize",
                "autotomize",
            })
            _OPP_SCREEN = frozenset({
                "reflect", "lightscreen", "auroraveil",
            })
            _OPP_ALLY_ACTIVATION = frozenset({
                "beatup",
            })
            for msg in turn_events:
                if len(msg) >= 3 and msg[0] == "move" and msg[1].startswith(opp_role):
                    move_name = self._normalize_name(msg[2])
                    if move_name == "tailwind":
                        opp_actions["opponent_used_tailwind"] = True
                    if move_name == "trickroom":
                        opp_actions["opponent_used_trickroom"] = True
                    if move_name == "followme":
                        opp_actions["opponent_used_followme"] = True
                    if move_name == "ragepowder":
                        opp_actions["opponent_used_ragepowder"] = True
                    if move_name == "fakeout":
                        opp_actions["opponent_used_fakeout"] = True
                    if move_name == "encore":
                        opp_actions["opponent_used_encore"] = True
                    if move_name == "taunt":
                        opp_actions["opponent_used_taunt"] = True
                    if move_name == "quash":
                        opp_actions["opponent_used_quash"] = True
                    if move_name == "beatup":
                        opp_actions["opponent_used_ally_activation_move"] = True
                    if move_name in _OPP_STAT_BOOST:
                        opp_actions["opponent_used_stat_boost_setup"] = True
                    if move_name in _OPP_SCREEN:
                        opp_actions["opponent_used_screen_setup"] = True

            # Phase COUNTER-2: detect partner
            # absorb/redirect ability activations.
            # Tracks whether an opponent's mon
            # activated Lightning Rod, Storm Drain,
            # Water Absorb, Flash Fire, or Sap Sipper
            # during this turn (these would-be
            # counterplay signals). Pure observation;
            # no scoring change.
            _OPP_ABSORB_REDIRECT_ABILITIES = frozenset({
                "lightningrod", "stormdrain",
                "waterabsorb", "flashfire",
                "sapsipper", "wellbakedbody",
            })
            try:
                for msg in turn_events:
                    if (
                        len(msg) >= 3
                        and msg[0] == "-ability"
                        and msg[1].startswith(opp_role)
                    ):
                        ability_name = self._normalize_name(
                            msg[2]
                        )
                        if (
                            ability_name
                            in _OPP_ABSORB_REDIRECT_ABILITIES
                        ):
                            opp_actions[
                                "opponent_used_absorb_redirect_ally"
                            ] = True
                            break
            except Exception:
                pass

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

    def _emit_v1_1_fields(self, turn_data):
        """Phase RL-DATA-3a: add turn_rl_v1.1 fields to
        a turn_data dict in place.

        Delegates to
        ``doubles_engine.audit_v1_1_metadata.populate_v1_1_audit_fields``
        so the helper is the single source of truth for
        v1.1 field emission. Wrapped in try/except so a
        failure in the v1.1 emission path never breaks
        the audit logger's hot path (i.e., real battle
        decision logging is never lost because of a
        v1.1 instrumentation bug).

        Phase RL-DATA-3a.1: pre-compute a per-move
        metadata map (``base_power``, ``category``,
        ``move_type``, ``target``, ``metadata_source``)
        by walking the V4a legal-action keys and
        calling ``doubles_engine.move_metadata`` to
        resolve each move id. The map is stashed on
        the turn_data so the support classifier
        receives real ``base_power`` / ``category``
        values for known damaging moves such as
        ``fakeout`` and ``hurricane``. This prevents
        false ``unknown_needs_probe`` tags.

        Phase RL-DATA-3a.2: the metadata helper
        ``_populate_v1_1_move_metadata_map`` honors
        the optional ``_v11_move_metadata_override_raw``
        kwarg the caller may have stashed on the
        turn_data (via ``move_metadata_map_override``
        in ``log_turn_decision``). The override is
        normalized and used first; the static
        resolver fills in any missing entries.
        """
        try:
            self._populate_v1_1_move_metadata_map(turn_data)
            from doubles_engine.audit_v1_1_metadata import (
                populate_v1_1_audit_fields,
            )
            populate_v1_1_audit_fields(turn_data)
        except Exception as exc:
            # Observational only: never raise. Mark the
            # emission as failed so downstream tools
            # can detect a regression. The keys are
            # added with explicit safe defaults so the
            # analyzer still sees the gates.
            try:
                turn_data["v1_1_emission_failed"] = True
                turn_data["v1_1_emission_error"] = (
                    f"{type(exc).__name__}: {exc}"[:200]
                )
            except Exception:
                pass

    def _populate_v1_1_move_metadata_map(
        self, turn_data,
    ) -> None:
        """Phase RL-DATA-3a.1 + RL-DATA-3a.2: build a
        per-move metadata map from the V4a legal-action
        keys, with optional live override.

        The map is written to ``turn_data["move_metadata_map"]``
        so ``populate_v1_1_audit_fields`` can read it
        and pass ``base_power`` / ``category`` into
        the support classifier.

        The map keys are normalized move ids
        (lowercased, no spaces / dashes / underscores
        / apostrophes) so the audit fast path can do
        a direct ``dict.get`` lookup.

        Resolution order (per move id):

        1. **Live override** (``_v11_move_metadata_override_raw``):
           if the caller passed ``move_metadata_map_override``
           to ``log_turn_decision``, the override is
           normalized and used first. ``metadata_source =
           "override"`` unless the caller set a different
           label. This is the primary path for real
           production audits (RL-DATA-3a.2).
        2. The audit logger does not carry order
           objects or active-mons on the turn_data.
           A future ``move_metadata_map_override``
           pass-through from choose_move would inject
           live poke-env ``Move`` objects here.
        3. The static fallback table in
           ``doubles_engine.move_metadata`` (covers
           smoke / test fixtures and the SUPPORT-AUDIT-1
           inventory).

        Wrapped in try/except so a failure in the
        metadata path never breaks the v1.1 emission.
        """
        try:
            from doubles_engine.move_metadata import (
                resolve_move_metadata_for_audit,
                normalize_override,
            )
            from doubles_engine.audit_v1_1_metadata import (
                _normalize_v1_1_move_id as _norm,
            )
            out: dict = {}
            # 1) Override wins.
            override_raw = turn_data.get(
                "_v11_move_metadata_override_raw"
            )
            if isinstance(override_raw, dict):
                out.update(normalize_override(override_raw))
            # 2) Collect unique move ids from the V4a
            # legal-action keys.
            seen: set = set()
            move_ids: list = []
            for legal_key in (
                "v4a_legal_action_keys_slot0",
                "v4a_legal_action_keys_slot1",
            ):
                keys = turn_data.get(legal_key) or []
                if not isinstance(keys, list):
                    continue
                for k in keys:
                    if not isinstance(k, (list, tuple)) or len(k) < 2:
                        continue
                    mid_norm = _norm(k[1])
                    if not mid_norm or mid_norm in seen:
                        continue
                    seen.add(mid_norm)
                    move_ids.append(mid_norm)
            # 3) Fill any missing entries from the
            # static resolver. The audit logger
            # does not carry order objects or
            # active-mons on the turn_data, so the
            # resolver falls back to the static table
            # for known moves. A real production audit
            # (not the smoke) injects live metadata
            # via the override path.
            for mid in move_ids:
                if mid in out:
                    continue
                meta = resolve_move_metadata_for_audit(mid)
                out[mid] = meta
            turn_data["move_metadata_map"] = out
        except Exception as exc:
            # Observational only: a failure here means
            # the classifier will fall back to
            # ``base_power=None`` / ``category=None``,
            # which is the conservative default. We
            # mark the metadata map as failed so
            # downstream tools can detect a regression.
            try:
                turn_data["v1_1_move_metadata_failed"] = True
                turn_data["v1_1_move_metadata_error"] = (
                    f"{type(exc).__name__}: {exc}"[:200]
                )
                turn_data["move_metadata_map"] = {}
            except Exception:
                pass

    def set_battle_arm(
        self, battle_tag, benchmark_arm, enable_mega_evolution,
        treatment_side="",
    ):
        """Phase BI-3K.3: record per-battle arm metadata.

        The runner calls this before each battle starts so the
        persisted audit row can distinguish treatment vs baseline
        and verify Mega config assignment per side. The
        metadata is popped and persisted when ``save_battle``
        fires.
        """
        self._battle_arm_meta[str(battle_tag)] = {
            "benchmark_arm": str(benchmark_arm),
            "enable_mega_evolution": bool(enable_mega_evolution),
            "treatment_side": str(treatment_side),
        }

    def set_current_battle_meta(
        self, benchmark_arm, enable_mega_evolution,
        enable_decision_timing_diagnostics=False,
        treatment_side="", player_side="", player_name="",
        scenario_id=None, scripted_actions=None,
        script_failures=None,
    ):
        """Phase BI-3K.7: context-based battle metadata.

        The runner calls this before each battle starts.
        Unlike ``set_battle_arm`` (which keys by
        ``battle_tag``), this method sets a single
        "current" metadata context that ``save_battle``
        reads and clears. This avoids the battle_tag
        mismatch between the runner's tag and the
        poke-env server-assigned tag. The runner calls
        this for BOTH the treatment and baseline
        loggers before each battle.

        Phase RUNNER-TIMING-1: ``enable_decision_timing_diagnostics``
        is also stored so persisted audit rows identify
        which runs had timing on. Default False.

        Phase SCENARIO-3: ``scenario_id``,
        ``scripted_actions``, ``script_failures`` are
        scenario metadata captured when
        ``--scenario-file`` is set on the runner.
        ``scripted_actions`` and ``script_failures``
        are mutable lists that may be appended to
        during the battle; we copy them at read time
        in ``save_battle``. Default None / empty.
        """
        self._current_battle_meta = {
            "benchmark_arm": str(benchmark_arm),
            "enable_mega_evolution": bool(enable_mega_evolution),
            "enable_decision_timing_diagnostics": bool(
                enable_decision_timing_diagnostics
            ),
            "treatment_side": str(treatment_side),
            "player_side": str(player_side),
            "player_name": str(player_name),
            "scenario_id": scenario_id,
            # Phase SCENARIO-5: store the live
            # list reference (no copy) so
            # save_battle's later copy captures
            # the final state. Use
            # ``is not None`` (not truthiness)
            # since an empty list is a valid
            # live reference.
            "scripted_actions": (
                scripted_actions
                if scripted_actions is not None
                else []
            ),
            "script_failures": (
                script_failures
                if script_failures is not None
                else []
            ),
        }

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

        # Phase BI-3K.7: prefer context-based metadata
        # (set by runner via set_current_battle_meta),
        # fall back to per-battle-tag metadata from
        # set_battle_arm. Pop the context after read
        # so the next save_battle call starts clean.
        ctx_meta = self._current_battle_meta
        self._current_battle_meta = {}
        arm_meta = self._battle_arm_meta.pop(battle_tag, {})
        merged = {**arm_meta, **ctx_meta}
        mega_enabled = bool(merged.get("enable_mega_evolution", False))
        # Phase RUNNER-TIMING-1: include timing flag in
        # the persisted audit row so future reports can
        # distinguish timing-on vs timing-off runs.
        timing_enabled = bool(merged.get(
            "enable_decision_timing_diagnostics", False
        ))
        benchmark_arm = str(
            merged.get("benchmark_arm", self._benchmark_arm)
        )
        treatment_side = str(merged.get("treatment_side", ""))
        player_side = str(merged.get("player_side", ""))
        player_name = str(merged.get("player_name", ""))
        # Phase SCENARIO-3: scenario metadata captured
        # when --scenario-file is set. ``scripted_actions``
        # and ``script_failures`` are lists of dicts;
        # ``scenario_id`` is a string or None.
        scenario_id = merged.get("scenario_id")
        scripted_actions = merged.get("scripted_actions", [])
        script_failures = merged.get("script_failures", [])

        battle_record = {
            "battle_tag": str(battle_tag),
            "winner": str(winner),
            "won": bool(won),
            "total_turns": int(getattr(battle, "turn", 0)),
            "benchmark_arm": benchmark_arm,
            "singleton_safety_enabled": singleton_enabled,
            "priority_safety_enabled": priority_enabled,
            "enable_mega_evolution": mega_enabled,
            "enable_decision_timing_diagnostics": timing_enabled,
            "treatment_side": treatment_side,
            "player_side": player_side,
            "player_name": player_name,
            "scenario_id": scenario_id,
            "scripted_actions": list(scripted_actions),
            "script_failures": list(script_failures),
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
            "benchmark_arm": benchmark_arm,
            "enable_mega_evolution": mega_enabled,
            "treatment_side": treatment_side,
            "player_side": player_side,
            "player_name": player_name,
        })


# Phase BEHAVIOR-9: protect-like move IDs for score-diff.
# Used to identify Protect scores in the v2l1_raw_scores.
_PROTECT_LIKE_MOVE_IDS = frozenset({
    "protect", "detect", "spikyshield", "kingsshield",
    "banefulbunker", "silktrap", "burningbulwark",
    "obstruct", "maxguard",
})


def _compute_slot_score_diff(v2l1_raw_scores):
    """Phase BEHAVIOR-9: compute protect_score,
    best_non_protect_move_score, and score_diff from
    v2l1_raw_scores.

    Returns (protect_score, best_non_protect_move_score,
    score_diff). Any of them may be None if not
    computable.

    No new scoring is done. This only inspects the
    already-computed raw scores.
    """
    if not isinstance(v2l1_raw_scores, dict):
        return None, None, None
    protect_score = None
    best_non_protect = None
    for k, v in v2l1_raw_scores.items():
        if not isinstance(k, str):
            continue
        # Key format: 'kind|move_id|target_pos' e.g.
        # 'move|protect|0' or 'switch|garchomp|0'.
        parts = k.split("|")
        if len(parts) < 3:
            continue
        kind = parts[0]
        move_id = parts[1].lower()
        try:
            score = float(v)
        except (TypeError, ValueError):
            continue
        if kind == "move":
            if move_id in _PROTECT_LIKE_MOVE_IDS:
                if (
                    protect_score is None
                    or score > protect_score
                ):
                    protect_score = score
            else:
                if (
                    best_non_protect is None
                    or score > best_non_protect
                ):
                    best_non_protect = score
    if protect_score is not None and best_non_protect is not None:
        score_diff = protect_score - best_non_protect
    else:
        score_diff = None
    return protect_score, best_non_protect, score_diff
