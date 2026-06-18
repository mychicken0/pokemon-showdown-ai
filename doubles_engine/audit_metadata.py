"""Audit metadata assembly helpers.

ponytail: Phase Ponytail Refactor Step 7A.
Extracted the V2l.1 action-key → string converters
from ``bot_doubles_damage_aware.DoublesDamageAwarePlayer``
to module-level pure functions.

The helpers in this module are the same code that
used to live at lines 11445-11484 of
``bot_doubles_damage_aware.py`` (as @staticmethod
and @classmethod on the player class). The
behavior is bit-for-bit identical.

Dependency notes:
- All three helpers are pure: they take a
  primitive/dict/tuple/None input and return
  a string (or dict, or None). No bot-local
  dependencies, no battle state reads, no
  score mutations, no choose_move control flow.
- No lazy imports needed.
"""

from typing import Any, Dict, Optional, Tuple


def v2l1_action_key_to_str(action_key: Any) -> str:
    """V2l.1 — convert an action-key tuple into a
    JSON-serializable string.

    The audit logger persists action keys without
    storing non-serializable ``BattleOrder``
    objects, so we convert them to ``"a|b|c"``
    strings here.

    ponytail: extracted from
    ``DoublesDamageAwarePlayer._v2l1_action_key_to_str``.
    """
    if not isinstance(action_key, tuple) or not action_key:
        return str(action_key)
    return "|".join(str(x) for x in action_key)


def v2l1_action_key_to_str_map(d: Optional[Dict[Any, Any]]) -> Dict[str, Any]:
    """V2l.1 — map every key in ``d`` to a string
    for JSON serialization.

    ponytail: extracted from
    ``DoublesDamageAwarePlayer._v2l1_action_key_to_str_map``.
    """
    out: Dict[str, Any] = {}
    for k, v in (d or {}).items():
        try:
            out[v2l1_action_key_to_str(k)] = v
        except Exception:
            continue
    return out


def v2l1_joint_key_to_str(joint_key: Any) -> Optional[str]:
    """V2l.1 — convert a joint key tuple pair into a
    single string for JSON serialization.

    Returns ``None`` if ``joint_key`` is falsy,
    ``str(joint_key)`` if it is not a 2-tuple,
    and ``"a;b"`` for a 2-tuple ``(a, b)``.

    ponytail: extracted from
    ``DoublesDamageAwarePlayer._v2l1_joint_key_to_str``.
    """
    if not joint_key:
        return None
    if not isinstance(joint_key, tuple):
        return str(joint_key)
    if len(joint_key) != 2:
        return str(joint_key)
    return (
        v2l1_action_key_to_str(joint_key[0])
        + ";"
        + v2l1_action_key_to_str(joint_key[1])
    )


def assemble_v2l1_metadata(
    v2l1_legal_keys_slot0: Optional[list],
    v2l1_legal_keys_slot1: Optional[list],
    v2l1_raw_scores_slot0: Optional[Dict[Any, Any]],
    v2l1_raw_scores_slot1: Optional[Dict[Any, Any]],
    v2l1_safety_blocks_slot0: Optional[Dict[Any, Any]],
    v2l1_safety_blocks_slot1: Optional[Dict[Any, Any]],
    v2l1_selected_joint_key: Any,
    v2l1_final_keys: Optional[list],
) -> Dict[str, Any]:
    """V2l.1 — assemble the per-decision audit
    sub-dict from already-computed self.X state.

    The 8 input arguments correspond to the 8
    ``self.X`` reads that the original audit block
    did via ``getattr(self, ...)``. The function
    packages them into a dict with 6 keys that the
    audit logger consumes.

    ponytail: extracted from the V2l.1 sub-dict
    block at lines 11373-11433 of
    ``bot_doubles_damage_aware.py`` (which is part
    of the kwargs to ``audit_logger.log_turn_decision``).
    Behavior preserved bit-for-bit. Each input
    defaults to a safe empty value (``[]``, ``{}``,
    or ``None``) to mirror the original ``getattr``
    defaults.
    """
    return {
        "v2l1_legal_action_keys_slot0": list(
            v2l1_legal_keys_slot0
            if v2l1_legal_keys_slot0 is not None
            else []
        ),
        "v2l1_legal_action_keys_slot1": list(
            v2l1_legal_keys_slot1
            if v2l1_legal_keys_slot1 is not None
            else []
        ),
        "v2l1_raw_scores_slot0": dict(
            v2l1_action_key_to_str_map(
                v2l1_raw_scores_slot0
                if v2l1_raw_scores_slot0 is not None
                else {}
            )
        ),
        "v2l1_raw_scores_slot1": dict(
            v2l1_action_key_to_str_map(
                v2l1_raw_scores_slot1
                if v2l1_raw_scores_slot1 is not None
                else {}
            )
        ),
        "v2l1_safety_blocks_slot0": dict(
            v2l1_action_key_to_str_map(
                v2l1_safety_blocks_slot0
                if v2l1_safety_blocks_slot0 is not None
                else {}
            )
        ),
        "v2l1_safety_blocks_slot1": dict(
            v2l1_action_key_to_str_map(
                v2l1_safety_blocks_slot1
                if v2l1_safety_blocks_slot1 is not None
                else {}
            )
        ),
        "v2l1_selected_joint_key": v2l1_joint_key_to_str(
            v2l1_selected_joint_key
        ),
        "v2l1_final_action_keys": [
            v2l1_action_key_to_str(k)
            for k in (v2l1_final_keys or [])
        ],
    }


def assemble_partial_spread_state(
    battle_tag,
    partial_immune_spread_by_battle,
    partial_ability_immune_spread_by_battle,
    efficient_partial_spread_by_battle,
    inefficient_partial_spread_by_battle,
    immune_target_species_by_battle,
    damaged_target_species_by_battle,
) -> Dict[str, Any]:
    """Partial-spread audit readout — packages the
    per-slot readouts of 6 per-battle tracking dicts
    into the audit-dict shape the logger consumes.

    ponytail: Phase Ponytail Refactor Step 7D.
    Extracted from lines 10562-10608 of
    ``bot_doubles_damage_aware.py`` (the
    ``partial_*_selected`` and
    ``*_target_species`` audit kwargs in the
    ``audit_logger.log_turn_decision(...)`` call).
    Behavior preserved bit-for-bit.

    The function takes the 6 per-battle tracking
    dicts plus the current ``battle_tag``. For each
    dict, it performs the equivalent of
    ``dict.setdefault(battle_tag, default)[0]`` and
    ``[1]`` and packages the per-slot values into a
    result dict.

    The boolean-by-slot dicts default to
    ``{0: False, 1: False}``; the species-by-slot
    dicts default to ``{0: [], 1: []}``. This matches
    the original ``setdefault`` defaults.

    ponytail: the function preserves the mutation
    semantics of the original code. Each passed
    dict is mutated via ``setdefault`` exactly as
    before, so per-battle tracking state is
    consistent with the prior call site. The
    function does not mutate any other inputs.

    Output keys (matching the existing audit
    ``log_turn_decision`` kwargs):
    - ``partial_immune_spread_selected`` → ``[slot0, slot1]`` from
      ``partial_immune_spread_by_battle``
    - ``partial_ability_immune_spread_selected`` → ``[slot0, slot1]`` from
      ``partial_ability_immune_spread_by_battle``
    - ``efficient_partial_spread_selected`` → ``[slot0, slot1]`` from
      ``efficient_partial_spread_by_battle``
    - ``inefficient_partial_spread_selected`` → ``[slot0, slot1]`` from
      ``inefficient_partial_spread_by_battle``
    - ``immune_target_species`` → ``[slot0, slot1]`` from
      ``immune_target_species_by_battle``
    - ``damaged_target_species`` → ``[slot0, slot1]`` from
      ``damaged_target_species_by_battle``
    """
    p0 = partial_immune_spread_by_battle.setdefault(
        battle_tag, {0: False, 1: False}
    )
    p1 = partial_ability_immune_spread_by_battle.setdefault(
        battle_tag, {0: False, 1: False}
    )
    p2 = efficient_partial_spread_by_battle.setdefault(
        battle_tag, {0: False, 1: False}
    )
    p3 = inefficient_partial_spread_by_battle.setdefault(
        battle_tag, {0: False, 1: False}
    )
    p4 = immune_target_species_by_battle.setdefault(
        battle_tag, {0: [], 1: []}
    )
    p5 = damaged_target_species_by_battle.setdefault(
        battle_tag, {0: [], 1: []}
    )
    return {
        "partial_immune_spread_selected": [p0[0], p0[1]],
        "partial_ability_immune_spread_selected": [p1[0], p1[1]],
        "efficient_partial_spread_selected": [p2[0], p2[1]],
        "inefficient_partial_spread_selected": [p3[0], p3[1]],
        "immune_target_species": [p4[0], p4[1]],
        "damaged_target_species": [p5[0], p5[1]],
    }


def _action_key_to_str_safe(action_key):
    """Phase BI-2D: Convert an action-key tuple to a
    JSON-serializable string. Returns empty string for
    None or for non-tuple inputs (defensive against
    raw order objects leaking into the JSONL).
    """
    if action_key is None:
        return ""
    if not isinstance(action_key, tuple) or not action_key:
        return ""
    try:
        return "|".join(str(x) for x in action_key)
    except Exception:
        return ""


def assemble_switch_counterfactual_slot(
    slot_idx,
    voluntary_switch_candidate_table,
    selected_action_key,
    counterfactual_action_key,
    best_stay_score,
    best_stay_action_key,
    selection_changed,
    reason_codes,
):
    """Phase BI-2D: Assemble the per-slot sub-dict
    for the switch_counterfactual field.

    Reads only data already on hand in
    ``choose_move``: the per-slot voluntary switch
    candidate table and the existing _vsw_* locals.
    Returns a JSON-safe dict with 9 keys (chosen
    /counterfactual/best-switch/best-non-switch/delta/
    selection-changed/reason).

    Output keys:
      - chosen_is_switch
      - chosen_action_key
      - counterfactual_action_key
      - best_switch_action_key
      - best_switch_score
      - best_non_switch_action_key
      - best_non_switch_score
      - switch_vs_non_switch_delta
      - selection_changed
      - reason_codes

    Conventions:
      - chosen_is_switch: True iff the bot's
        selected_action_key starts with
        "switch|" (since action_type is the first
        element of the 3-tuple).
      - switch_vs_non_switch_delta = best_switch_score
        - best_non_switch_score when both are
        known. None if either is missing.
      - selection_changed: True iff the VSW
        scoring flipped the joint choice for this
        slot.

    Edge cases:
      - Empty candidate table -> best_switch_*
        fields are None.
      - best_stay_score is None or 0.0 -> both
        fields stay, delta may be None.
      - reason_codes must be a list of strings; any
        non-str values are coerced.
    """
    chosen_str = _action_key_to_str_safe(selected_action_key)
    cf_str = _action_key_to_str_safe(counterfactual_action_key)
    chosen_is_switch = chosen_str.startswith("switch|")
    best_switch_action_key = ""
    best_switch_score = None
    try:
        if voluntary_switch_candidate_table:
            best_row = max(
                voluntary_switch_candidate_table,
                key=lambda r: r.get("adjusted_switch_score", -1e9),
            )
            best_switch_action_key = _action_key_to_str_safe(
                best_row.get("candidate_action_key")
            )
            best_switch_score = float(
                best_row.get("adjusted_switch_score")
            )
    except Exception:
        best_switch_action_key = ""
        best_switch_score = None
    best_non_switch_action_key = _action_key_to_str_safe(
        best_stay_action_key
    )
    try:
        best_non_switch_score = (
            float(best_stay_score)
            if best_stay_score is not None
            else None
        )
    except (TypeError, ValueError):
        best_non_switch_score = None
    if best_switch_score is not None and best_non_switch_score is not None:
        switch_vs_non_switch_delta = (
            best_switch_score - best_non_switch_score
        )
    else:
        switch_vs_non_switch_delta = None
    if not isinstance(reason_codes, (list, tuple)):
        try:
            reason_codes = list(reason_codes) if reason_codes else []
        except Exception:
            reason_codes = []
    coerced_reasons = []
    for r in reason_codes:
        try:
            coerced_reasons.append(str(r))
        except Exception:
            continue
    return {
        "chosen_is_switch": bool(chosen_is_switch),
        "chosen_action_key": chosen_str,
        "counterfactual_action_key": cf_str,
        "best_switch_action_key": best_switch_action_key,
        "best_switch_score": best_switch_score,
        "best_non_switch_action_key": best_non_switch_action_key,
        "best_non_switch_score": best_non_switch_score,
        "switch_vs_non_switch_delta": switch_vs_non_switch_delta,
        "selection_changed": bool(selection_changed),
        "reason_codes": coerced_reasons,
    }


def assemble_shared_engine_metadata(
    runtime_mode: Optional[str],
    concrete_player_class: Optional[str],
    v2l1_invocation_id: Optional[str],
    v2l1_invocation_status: Optional[str],
    selected_four: Optional[Any],
    lead_2: Optional[Any],
    back_2: Optional[Any],
    preview_policy: Optional[Any],
) -> Dict[str, Any]:
    """Shared-engine identity / invocation audit
    metadata — packages the engine fingerprint
    kwargs for the audit logger.

    ponytail: Phase Ponytail Refactor Step 7E.
    Extracted from lines 11315-11348 (engine
    identity) and 11386-11391 (selected-four/
    lead-2/back-2/preview-policy) of
    ``bot_doubles_damage_aware.py``. Behavior
    preserved bit-for-bit.

    The function takes 8 explicit inputs and
    produces 10 output keys. The extra output
    keys (``shared_engine_used`` and
    ``shared_engine_owner``) are derived inside
    the function from the inputs:

    - ``shared_engine_used`` is True only when
      ``v2l1_invocation_id`` is non-empty AND
      ``v2l1_invocation_status == "completed"``.
    - ``shared_engine_owner`` is the canonical
      string ``"bot_doubles_damage_aware.DoublesDamageAwarePlayer"``.

    ponytail: discrepancy from the prompt's
    expected signature — the real audit cluster
    has 10 fields but only 8 of them are
    state-derived. The other 2
    (``shared_engine_used`` and
    ``shared_engine_owner``) are derived inside
    the function. This keeps the input count
    under 15 while preserving all 10 audit
    kwargs bit-for-bit.

    Output keys (matching the existing audit
    ``log_turn_decision`` kwargs exactly):
    - ``runtime_mode``
    - ``concrete_player_class``
    - ``shared_engine_used``
    - ``shared_engine_owner``
    - ``shared_engine_invocation_id``
    - ``shared_engine_invocation_status``
    - ``selected_four``
    - ``lead_2``
    - ``back_2``
    - ``preview_policy``
    """
    return {
        "runtime_mode": runtime_mode,
        "concrete_player_class": concrete_player_class,
        "shared_engine_used": bool(
            v2l1_invocation_id
            and v2l1_invocation_status == "completed"
        ),
        "shared_engine_owner": (
            "bot_doubles_damage_aware.DoublesDamageAwarePlayer"
        ),
        "shared_engine_invocation_id": v2l1_invocation_id,
        "shared_engine_invocation_status": v2l1_invocation_status,
        "selected_four": selected_four,
        "lead_2": lead_2,
        "back_2": back_2,
        "preview_policy": preview_policy,
    }
