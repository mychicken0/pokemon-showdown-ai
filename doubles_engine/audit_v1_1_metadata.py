"""v1.1 audit logger emission helpers — Phase RL-DATA-3a.

Pure functions that add the ``turn_rl_v1.1`` instrumentation
fields to an audit-log turn dict. The helpers are used by
``showdown_ai/doubles_decision_audit_logger.py`` at the end
of ``log_turn_decision`` so that the persisted JSONL carries
v1.1 fields directly.

Phase RL-DATA-2 added v1.1 fields to the **builder**
(``showdown_ai/build_turn_level_offline_dataset.py``), which
synthesized v1.1 fields from the v1.0 audit JSONL. Phase
RL-DATA-3a moves that synthesis forward: the audit logger
itself emits the v1.1 fields so any future audit (not just
the existing legacy one) carries v1.1 fields by default.

Key invariants:

- ``used_species_ability_inference`` is always ``False``.
- ``local_only_provenance`` is always ``True``.
- Missing source data is emitted as ``None`` / empty list /
  ``False`` so analyzer gates can report explicit gaps.
- No scoring / behavior change. The audit logger is
  observational only.
- The bot is never the source of any v1.1 field that
  reflects a forbidden inference.

The helpers are pure: they take a ``turn_data`` dict and
mutate it in place. They do not read the bot config, do
not call into the bot engine, do not open files. They
import from ``doubles_engine.support_targets`` for the
per-candidate classifier (lazy import to avoid circular
dependency at module load time).

Source of fields (from the existing audit logger turn_data):

- v1.0 legal actions: ``v4a_legal_action_keys_slot0`` /
  ``v4a_legal_action_keys_slot1`` (preferred) or
  ``v2l1_legal_action_keys_slot0/1`` (fallback).
- v1.0 selected joint key: ``v4a_selected_joint_key`` /
  ``v4a_final_action_keys``.
- v1.0 raw scores: ``v2l1_raw_scores_slot0/1`` /
  ``v4a_raw_scores_slot0/1``.
- v1.0 state snapshot: ``state_snapshot`` with
  ``weather`` and ``fields`` keys.
- v1.0 safety fields: per-slot
  ``support_target_*_slot{0,1}`` and
  ``narrow_ally_heal_*_slot{0,1}`` (synthesized into
  the v1.1 block reasons).
- v1.0 ability source: per-slot
  ``singleton_ability_resolved`` /
  ``singleton_resolution_source`` /
  ``known_ability_resolution_source``.

Fields NOT emitted here (and why):

- ``reward_provenance`` / ``reward_confidence``: emitted
  as static values per the v1.1 plan. Not derived from
  per-turn data.
- ``terminal_win_loss``: filled by the builder from
  episode-level metadata (row_battle.won). The audit
  logger does not have this.
- ``turn_delta_hp``: not derivable from the pre-decision
  snapshot. Emitted as an empty dict.
- ``faint_caused`` / ``faint_suffered``: not derivable
  from the pre-decision snapshot. Emitted as ``None``.
- ``config_hash`` / ``config_snapshot`` / ``format`` /
  ``team_id`` / ``opponent_team_id``: not available to
  the audit logger. Emitted as ``None`` / empty dict.
- ``type_boost_applied``: would need execution-time
  damage / boost data. Emitted as an empty list.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

# v1.1 set of fields this module emits. The builder's
# _extract_v1_1_* helpers all read these from
# ``turn.get("xxx")`` first; if the audit logger has
# emitted them, the builder uses them. If absent, the
# builder falls back to synthesizing them from the v1.0
# legal actions / state snapshot.
V1_1_EMITTED_FIELDS = (
    # Metadata / provenance
    "config_hash",
    "config_snapshot",
    "local_only_provenance",
    "format",
    "team_id",
    "opponent_team_id",
    "runtime_mode",
    # Reward placeholders (filled by the builder from
    # episode metadata, but emitted here as None so the
    # keys are present and explicit).
    "terminal_win_loss",
    "turn_delta_hp",
    "faint_caused",
    "faint_suffered",
    "delayed_reward_placeholder",
    "sparse_reward_warning",
    "reward_provenance",
    "reward_confidence",
    # Weather / Terrain (Gate 14)
    "weather_current",
    "terrain_current",
    "setter_move_legal",
    "setter_move_selected",
    "setter_move_raw_score",
    "type_boost_move_legal",
    "type_boost_move_selected",
    "type_boost_applied",
    "wt2_relevance_flag",
    "wt3_relevance_flag",
    "wt4_relevance_flag",
    # Safety / mechanics (Gate 13)
    "block_reason_wrong_side",
    "block_reason_narrow_ally_heal",
    "block_reason_broad_support_target",
    "block_reason_ability_hard_safety",
    "revealed_ability_source",
    "used_species_ability_inference",
    "impossible_target_detected",
    "blocked_action_resurrected_by_joint",
    # Support instrumentation (Gate 12 / Gate 17)
    "per_candidate_support_classification",
    "support_move_distribution",
    "unknown_support_move_detected",
)


# Phase RL-DATA-3a: WT-2 weather/terrain setter move ids.
# Mirrors ``_WT2_SETTER_MOVE_IDS`` in the builder. The
# values must stay in sync.
_WT2_SETTER_MOVE_IDS = frozenset({
    "raindance", "sunnyday", "sandstorm", "hail", "snowscape",
    "electricterrain", "grassyterrain", "mistyterrain",
    "psychicterrain",
})

# Phase RL-DATA-3a: WT-3 type-boost move ids. Mirrors
# ``_TYPE_BOOST_MOVE_IDS`` in the builder. The values
# must stay in sync.
_TYPE_BOOST_MOVE_IDS = frozenset({
    # Rain
    "hurricane", "thunder", "watergun", "hydropump", "surf",
    "muddywater", "weatherball",
    # Sun
    "fireblast", "flamethrower", "solarbeam", "solarblade",
    "firepunch", "flamecharge",
    # Sand
    "rockslide", "stoneedge", "earthpower", "earthquake",
    # Electric terrain
    "thunderbolt", "thunderpunch", "voltswitch",
    # Grassy terrain
    "gigadrain", "razorleaf", "leafstorm", "energyball",
    "leafblade", "powerwhip",
    # Psychic terrain
    "psychic", "psyshock", "psybeam", "zenheadbutt",
    "extrasensory",
    # Misty terrain
    "moonblast", "drainingkiss", "fairywind",
})


def _to_json_safe(value: Any) -> Any:
    """Recursively convert to JSON-safe primitives."""
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(v) for v in value]
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _normalize_v1_1_move_id(move_id: Any) -> str:
    """Normalize a move id to a lowercased no-space string.

    Mirrors ``_normalize_v1_1_move_id`` in the builder. The
    values must stay consistent so audit-emitted and
    builder-synthesized support classifications agree.
    """
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


def _support_targets_classify():
    """Lazy import to avoid circular dependency.

    ``doubles_engine.support_targets`` has a top-level
    import chain that pulls in
    ``bot_doubles_damage_aware``. We defer the import
    to the call site that actually needs the classifier.
    """
    from doubles_engine.support_targets import (
        classify_support_move_for_dataset,
        aggregate_support_distribution,
    )
    return (
        classify_support_move_for_dataset,
        aggregate_support_distribution,
    )


def _extract_v1_1_weather(turn_data: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Pull weather / terrain strings from state_snapshot.

    Returns ``(weather_current, terrain_current)``. Either
    may be ``None`` if no value is available.

    The audit logger stores weather as a poke-env enum
    value (e.g. ``"RainDance"``) or a string. The
    builder's v1.1 extractor lowercases the value to
    a canonical form (``"raindance"``). We do the same
    here so the audit-emitted and builder-synthesized
    values agree on a real audit JSONL.

    Robustness: the audit logger's ``_enum_keys`` helper
    iterates the value. If the value is a string
    (poke-env enum), iterating yields single characters
    (``["r", "a", "i", "n", ...]``). We detect that
    case and join the list back into the original
    string before lowercasing.
    """
    def _canon(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            if not value or value == "none":
                return None
            return value.split(".")[-1].lower()
        if isinstance(value, list):
            if not value:
                return None
            # If the list elements are all single
            # characters, the audit logger's
            # _enum_keys iterated a string. Join
            # them back so the value is canonical.
            if all(
                isinstance(x, str) and len(x) == 1
                for x in value
            ):
                joined = "".join(value)
                return joined.split(".")[-1].lower() or None
            # Otherwise pick the first non-empty
            # element and canonicalize.
            for x in value:
                if not x:
                    continue
                s = str(x).split(".")[-1].lower()
                if s:
                    return s
            return None
        return None

    ss = turn_data.get("state_snapshot") or {}
    weather_current = _canon(ss.get("weather", None))
    terrain_current = _canon(ss.get("fields", []))
    return weather_current, terrain_current


def _setter_moves_in(keys: Any) -> List[str]:
    """Return the deduped sorted list of WT-2 setter moves
    in a V4a legal-action-keys list. Returns ``[]`` when
    the input is empty or not a list of keys.
    """
    out: List[str] = []
    if not isinstance(keys, list):
        return out
    for k in keys:
        if not isinstance(k, (list, tuple)) or len(k) < 2:
            continue
        mid = _normalize_v1_1_move_id(k[1])
        if mid in _WT2_SETTER_MOVE_IDS:
            out.append(mid)
    return out


def _type_boost_moves_in(keys: Any) -> List[str]:
    """Return the deduped sorted list of WT-3 type-boost
    moves in a V4a legal-action-keys list. Returns ``[]``
    when the input is empty or not a list of keys.
    """
    out: List[str] = []
    if not isinstance(keys, list):
        return out
    for k in keys:
        if not isinstance(k, (list, tuple)) or len(k) < 2:
            continue
        mid = _normalize_v1_1_move_id(k[1])
        if mid in _TYPE_BOOST_MOVE_IDS:
            out.append(mid)
    return out


def _extract_setter_raw_scores(
    turn_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a ``{move_id: raw_score}`` dict for setter
    moves that have a recorded raw score in the v2l1 or
    v4a raw-score dicts. Returns ``{}`` when no scores
    are present.

    The raw-score dict keys are pipe-joined action keys
    like ``"move|raindance|0|no_mechanic"``. We split
    on ``"|"`` and pull out the second element (the
    move id) before normalizing.
    """
    out: Dict[str, Any] = {}
    for raw_key in (
        "v2l1_raw_scores_slot0",
        "v2l1_raw_scores_slot1",
        "v4a_raw_scores_slot0",
        "v4a_raw_scores_slot1",
    ):
        raw = turn_data.get(raw_key)
        if not isinstance(raw, dict):
            continue
        for k, v in raw.items():
            key_str = str(k)
            # Pipe-joined action key: split and take
            # the move id (index 1).
            if "|" in key_str:
                parts = key_str.split("|")
                if len(parts) >= 2:
                    mid = _normalize_v1_1_move_id(parts[1])
                else:
                    mid = _normalize_v1_1_move_id(key_str)
            else:
                mid = _normalize_v1_1_move_id(key_str)
            if mid in _WT2_SETTER_MOVE_IDS:
                out[mid] = _to_json_safe(v)
    return out


def _extract_v1_1_safety_block_reasons(
    turn_data: Dict[str, Any],
) -> Dict[str, Optional[str]]:
    """Synthesize the v1.1 block-reason fields from the
    existing per-slot support / narrow ally-heal /
    ability-hard-safety fields on the audit turn.

    Each block reason is a human-readable string or
    ``None`` when no block was recorded. The strings are
    intentionally simple: the analyzer uses them for
    gate counts, not for parsing.
    """
    def _reason(slot_idx: int, key_prefix: str) -> Optional[str]:
        for s in (slot_idx,):
            v = turn_data.get(f"{key_prefix}_slot{s}")
            if v in (True, "blocked", "wrong_side"):
                return f"{key_prefix}_slot{s}"
        return None

    wrong_side = _reason(0, "support_target_wrong_side_selected") or _reason(
        1, "support_target_wrong_side_selected"
    )
    narrow = _reason(0, "narrow_ally_heal_candidate_blocked") or _reason(
        1, "narrow_ally_heal_candidate_blocked"
    )
    broad = _reason(0, "support_target_candidate_blocked") or _reason(
        1, "support_target_candidate_blocked"
    )
    ability = turn_data.get("ability_block_reason_slot0") or turn_data.get(
        "ability_block_reason_slot1"
    )
    return {
        "block_reason_wrong_side": (
            "support_target_wrong_side"
            if wrong_side
            else None
        ),
        "block_reason_narrow_ally_heal": (
            "narrow_ally_heal_candidate_blocked"
            if narrow
            else None
        ),
        "block_reason_broad_support_target": (
            "support_target_candidate_blocked"
            if broad
            else None
        ),
        "block_reason_ability_hard_safety": (
            str(ability) if ability else None
        ),
    }


def _extract_v1_1_revealed_ability_source(
    turn_data: Dict[str, Any],
) -> str:
    """Determine the v1.1 ``revealed_ability_source`` from
    existing per-slot ability-resolution fields.

    The audit logger tracks:

    - ``singleton_ability_resolved`` (per-slot bool)
    - ``singleton_resolution_source`` (per-slot str:
      ``"revealed"`` / ``"singleton_deduction"`` / ``None``)
    - ``known_ability_resolution_source`` (per-slot str)

    We synthesize a single value per turn: if any slot
    used a singleton deduction, the source is
    ``"singleton_deduction"``; otherwise the source is
    ``"revealed"``. The default when no info is available
    is ``"revealed"`` (i.e., the conservative read).
    """
    for slot_idx in (0, 1):
        if turn_data.get(f"singleton_ability_resolved_slot{slot_idx}"):
            return "singleton_deduction"
    return "revealed"


def _extract_v1_1_support_classification(
    turn_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Classify every move in the V4a legal-action keys
    and return a per-candidate classification, the group
    distribution, and an unknown-flag.

    The classification is identical to what the builder
    does in ``_extract_v1_1_support_classification`` so
    the audit-emitted and builder-synthesized versions
    agree on a real audit JSONL.

    Phase RL-DATA-3a.1: pass ``base_power`` and
    ``category`` to the classifier. The audit logger
    does not natively record these, so we use the
    ``doubles_engine.move_metadata`` resolver
    (poke-env ``Move`` → active mon's
    ``pokemon.moves`` → static fallback table).
    Known damaging moves such as ``fakeout`` and
    ``hurricane`` are then correctly classified as
    damage-like (``is_support_move=False``) instead
    of being falsely tagged as ``unknown_needs_probe``.
    """
    classify, aggregate = _support_targets_classify()
    legal0 = turn_data.get("v4a_legal_action_keys_slot0") or []
    legal1 = turn_data.get("v4a_legal_action_keys_slot1") or []
    # Try to extract live move metadata from the
    # battle if it is available. The audit logger
    # does not pass the battle into the helper
    # directly (the helper is pure), so we look
    # for a pre-computed ``move_metadata_map`` on
    # the turn_data. The audit logger populates
    # this map via ``resolve_batch_for_audit`` when
    # the battle / order objects are available.
    move_metadata_map: Dict[str, Dict[str, Any]] = (
        turn_data.get("move_metadata_map") or {}
    )
    per_candidate: Dict[str, Any] = {}
    classifications: List[Dict[str, Any]] = []
    for keys in (legal0, legal1):
        if not isinstance(keys, list):
            continue
        for k in keys:
            if not isinstance(k, (list, tuple)) or len(k) < 2:
                continue
            mid = _normalize_v1_1_move_id(k[1])
            if not mid:
                continue
            # Look up metadata for this move. The
            # audit logger populates ``move_metadata_map``
            # via the resolver. The resolver tries
            # live poke-env objects first, then the
            # static fallback. If neither has the
            # move, we get ``metadata_source="unknown"``
            # and base_power/category are ``None``
            # (the conservative default).
            meta = move_metadata_map.get(mid) or {}
            base_power = meta.get("base_power")
            category = meta.get("category")
            cls = classify(
                mid,
                base_power=base_power,
                category=category,
            )
            # Annotate each per-candidate entry with
            # the metadata source so downstream
            # tools (analyzer, inspector) can see
            # whether the classification came from
            # a real poke-env object, the active
            # mon's moves, or the static fallback.
            cls_with_meta = dict(cls)
            cls_with_meta["metadata_source"] = meta.get(
                "metadata_source"
            ) or "unknown"
            cls_with_meta["resolved_base_power"] = base_power
            cls_with_meta["resolved_category"] = category
            classifications.append(cls_with_meta)
            per_candidate[mid] = cls_with_meta
    distribution = aggregate(classifications)
    any_unknown = any(
        c.get("unknown_support_move_detected", False)
        for c in classifications
    )
    return {
        "per_candidate_support_classification": per_candidate,
        "support_move_distribution": distribution,
        "unknown_support_move_detected": any_unknown,
    }


def populate_v1_1_audit_fields(turn_data: Dict[str, Any]) -> None:
    """Add ``turn_rl_v1.1`` fields to a turn_data dict
    in place. The audit logger calls this at the end of
    ``log_turn_decision`` so the persisted JSONL carries
    v1.1 fields directly.

    This function is pure: it does not read the bot
    config, does not call into the bot engine, does
    not open files. It only reads from the turn_data
    dict (which is the audit logger's own structure)
    and writes v1.1 fields back into it.

    Idempotency: calling this twice on the same
    turn_data dict is safe. The second call overwrites
    the v1.1 fields with the same values.
    """
    # ---- Metadata / provenance ----
    turn_data["config_hash"] = turn_data.get("config_hash", None)
    turn_data["config_snapshot"] = _to_json_safe(
        turn_data.get("config_snapshot") or {}
    )
    # The bot is local-only. Always True.
    turn_data["local_only_provenance"] = True
    turn_data["format"] = turn_data.get("format", None)
    turn_data["team_id"] = turn_data.get("team_id", None)
    turn_data["opponent_team_id"] = turn_data.get(
        "opponent_team_id", None
    )
    turn_data["runtime_mode"] = turn_data.get("runtime_mode", None)

    # ---- Reward placeholders ----
    # The audit logger does not have these. Emit explicit
    # defaults so the analyzer can read the keys.
    turn_data["terminal_win_loss"] = None
    turn_data["turn_delta_hp"] = _to_json_safe(
        turn_data.get("turn_delta_hp", {})
    )
    turn_data["faint_caused"] = None
    turn_data["faint_suffered"] = None
    turn_data["delayed_reward_placeholder"] = 0.0
    turn_data["sparse_reward_warning"] = True
    turn_data["reward_provenance"] = "terminal_only"
    turn_data["reward_confidence"] = 1.0

    # ---- Weather / Terrain (Gate 14) ----
    weather_current, terrain_current = _extract_v1_1_weather(turn_data)
    turn_data["weather_current"] = weather_current
    turn_data["terrain_current"] = terrain_current

    legal0 = turn_data.get("v4a_legal_action_keys_slot0") or []
    legal1 = turn_data.get("v4a_legal_action_keys_slot1") or []
    setter_legal = sorted(
        set(_setter_moves_in(legal0) + _setter_moves_in(legal1))
    )

    sel_joint = turn_data.get("v4a_selected_joint_key")
    setter_selected: List[str] = []
    if isinstance(sel_joint, (list, tuple)):
        for k in sel_joint:
            if isinstance(k, (list, tuple)) and len(k) >= 2:
                mid = _normalize_v1_1_move_id(k[1])
                if mid in _WT2_SETTER_MOVE_IDS:
                    setter_selected.append(mid)

    tb_legal = sorted(
        set(_type_boost_moves_in(legal0) + _type_boost_moves_in(legal1))
    )
    tb_selected: List[str] = []
    if isinstance(sel_joint, (list, tuple)):
        for k in sel_joint:
            if isinstance(k, (list, tuple)) and len(k) >= 2:
                mid = _normalize_v1_1_move_id(k[1])
                if mid in _TYPE_BOOST_MOVE_IDS:
                    tb_selected.append(mid)

    turn_data["setter_move_legal"] = setter_legal
    turn_data["setter_move_selected"] = setter_selected
    setter_raw = _extract_setter_raw_scores(turn_data)
    turn_data["setter_move_raw_score"] = (
        setter_raw if setter_raw else None
    )
    turn_data["type_boost_move_legal"] = tb_legal
    turn_data["type_boost_move_selected"] = tb_selected
    # type_boost_applied requires execution-time data the
    # audit logger does not have. Emit an empty list.
    turn_data["type_boost_applied"] = []
    turn_data["wt2_relevance_flag"] = bool(setter_legal)
    turn_data["wt3_relevance_flag"] = bool(tb_legal)
    turn_data["wt4_relevance_flag"] = bool(setter_selected)

    # ---- Safety / mechanics (Gate 13) ----
    block_reasons = _extract_v1_1_safety_block_reasons(turn_data)
    turn_data["block_reason_wrong_side"] = block_reasons[
        "block_reason_wrong_side"
    ]
    turn_data["block_reason_narrow_ally_heal"] = block_reasons[
        "block_reason_narrow_ally_heal"
    ]
    turn_data["block_reason_broad_support_target"] = block_reasons[
        "block_reason_broad_support_target"
    ]
    turn_data["block_reason_ability_hard_safety"] = block_reasons[
        "block_reason_ability_hard_safety"
    ]
    turn_data["revealed_ability_source"] = (
        _extract_v1_1_revealed_ability_source(turn_data)
    )
    # CRITICAL: never True.
    turn_data["used_species_ability_inference"] = False
    turn_data["impossible_target_detected"] = False
    turn_data["blocked_action_resurrected_by_joint"] = False

    # ---- Support instrumentation (Gate 12 / Gate 17) ----
    support = _extract_v1_1_support_classification(turn_data)
    turn_data["per_candidate_support_classification"] = support[
        "per_candidate_support_classification"
    ]
    turn_data["support_move_distribution"] = support[
        "support_move_distribution"
    ]
    turn_data["unknown_support_move_detected"] = support[
        "unknown_support_move_detected"
    ]
