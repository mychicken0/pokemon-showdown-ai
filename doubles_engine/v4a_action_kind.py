"""Phase RL-DATA-3b-followup — V4a action-kind classification.

V4a legal-action keys mix move actions and switch
actions. The support classifier should only run on
real move actions. Switch actions and pass actions
should be excluded from support classification so
that switch target species names are not falsely
flagged as ``unknown_needs_probe``.

V4a legal-action key shapes (per slot):

```text
["move",    "raindance",  target_pos, mechanic]   # move action
["switch",  "volcarona",  target_pos, ""]         # switch action
["pass",    "pass",        0,         ""]         # pass action
["unknown", "/choose pass", 0,       ""]         # some passes are "unknown"
```

The first element of the key is the action kind. The
audit logger emits the kind as one of:

* ``"move"`` — a real move action. The second
  element is a move id (e.g., ``"raindance"``,
  ``"fakeout"``). Support classification applies.
* ``"switch"`` — a switch action. The second
  element is a species name. Support classification
  does NOT apply (the species is not a move).
* ``"pass"`` — an explicit pass action. The
  second element is ``"pass"``. Support
  classification does NOT apply.
* ``"unknown"`` — an action whose kind the
  audit logger could not classify. The second
  element is a literal string (e.g.,
  ``"/choose pass"``). The helper falls back
  to detecting a ``"pass"`` substring to be
  conservative.

This module is pure: no file I/O, no network, no
species inference, no hidden-state reads. The
audit logger and the builder both call
``resolve_candidate_action_kind(v4a_key)`` to
classify the action kind before deciding whether
to call the support classifier.

Phase RL-DATA-3b-followup scope: data
instrumentation only. No scoring / behavior /
default change.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple


# Action kind labels.
ACTION_KIND_MOVE = "move"
ACTION_KIND_SWITCH = "switch"
ACTION_KIND_PASS = "pass"
ACTION_KIND_UNKNOWN = "unknown"


def resolve_candidate_action_kind(
    v4a_key: Any,
) -> str:
    """Resolve the action kind for a V4a legal-action
    key.

    Returns one of:
    - ``"move"`` for real move actions
    - ``"switch"`` for switch actions
    - ``"pass"`` for explicit pass actions
    - ``"unknown"`` otherwise (caller should be
      conservative and skip support classification)

    Pure function. No I/O, no species inference, no
    hidden-state reads. The first element of the
    key is the action kind; the second element is
    the move id (for ``"move"``) or the species
    name (for ``"switch"``).
    """
    if not isinstance(v4a_key, (list, tuple)) or len(v4a_key) < 2:
        return ACTION_KIND_UNKNOWN
    raw_kind = v4a_key[0]
    if not isinstance(raw_kind, str):
        return ACTION_KIND_UNKNOWN
    kind = raw_kind.lower().strip()
    if kind == ACTION_KIND_MOVE:
        return ACTION_KIND_MOVE
    if kind == ACTION_KIND_SWITCH:
        return ACTION_KIND_SWITCH
    if kind == ACTION_KIND_PASS:
        return ACTION_KIND_PASS
    # Defensive: some passes are emitted as
    # ``["unknown", "/choose pass", 0, ""]``. The
    # audit logger's _enum_keys path can produce
    # this for empty / malformed actions. Detect
    # "pass" / "choose pass" as a substring in the
    # second element.
    if len(v4a_key) >= 2 and isinstance(v4a_key[1], str):
        second = v4a_key[1].lower().strip()
        if second in ("pass", "/choose pass", "choose pass"):
            return ACTION_KIND_PASS
    if kind == ACTION_KIND_UNKNOWN:
        return ACTION_KIND_UNKNOWN
    # Anything else (e.g., ``"mega"``, ``"zmove"``,
    # ``"dynamax"``, ``"terastallize"``) — these are
    # mechanic variants of a move action. Treat as
    # ``"move"`` so the support classifier still
    # applies. The move id is the third element of
    # the key in some encodings, but the audit
    # logger normalizes this; the second element
    # is the move id for our purposes.
    if kind in (
        "mega",
        "zmove",
        "dynamax",
        "terastallize",
        "maxmove",
    ):
        return ACTION_KIND_MOVE
    return ACTION_KIND_UNKNOWN


def is_move_action(v4a_key: Any) -> bool:
    """Return ``True`` iff the V4a key is a real move
    action. Switch / pass / unknown actions return
    ``False``.
    """
    return resolve_candidate_action_kind(v4a_key) == ACTION_KIND_MOVE


def is_switch_action(v4a_key: Any) -> bool:
    """Return ``True`` iff the V4a key is a switch
    action (the second element is a species name).
    """
    return resolve_candidate_action_kind(v4a_key) == ACTION_KIND_SWITCH


def is_pass_action(v4a_key: Any) -> bool:
    """Return ``True`` iff the V4a key is a pass
    action.
    """
    return resolve_candidate_action_kind(v4a_key) == ACTION_KIND_PASS


def split_candidate_id_from_v4a_key(
    v4a_key: Any,
) -> Tuple[str, str]:
    """Return ``(action_kind, candidate_id)`` for a
    V4a key. The ``candidate_id`` is the normalized
    identifier used as the per-candidate dict key.

    For ``"move"`` actions, the candidate id is
    the normalized move id (e.g., ``"raindance"``).
    For ``"switch"`` actions, the candidate id is
    the species name with a ``"switch:"`` prefix
    so it does not collide with any real move id.
    For ``"pass"`` actions, the candidate id is
    ``"pass"``. For ``"unknown"`` actions, the
    candidate id is the raw second element (a
    string) prefixed with ``"unknown:"``.

    The ``"switch:"`` / ``"pass:"`` / ``"unknown:"``
    prefixes are reserved by this helper. Real move
    ids in the SUPPORT-AUDIT-1 inventory do not use
    these prefixes.
    """
    kind = resolve_candidate_action_kind(v4a_key)
    if not isinstance(v4a_key, (list, tuple)) or len(v4a_key) < 2:
        return kind, ""
    second = v4a_key[1]
    if not isinstance(second, str):
        second = str(second)
    if kind == ACTION_KIND_MOVE:
        return kind, second.lower().strip()
    if kind == ACTION_KIND_SWITCH:
        return kind, f"switch:{second.lower().strip()}"
    if kind == ACTION_KIND_PASS:
        return kind, "pass"
    return kind, f"unknown:{second.lower().strip()}"


# Pre-built conservative classification for non-move
# actions. The audit logger / builder returns this
# dict directly for switch / pass / unknown actions
# without calling ``classify_support_move_for_dataset``.
# This prevents species names like ``"volcarona"``
# from being misclassified as
# ``unknown_needs_probe``.
NON_MOVE_CLASSIFICATION: dict = {
    "support_group": None,
    "support_status_from_audit": None,
    "is_support_move": False,
    "safety_only": False,
    "positive_strategy_known": False,
    "opt_in_flag_required": None,
    "default_enabled": None,
    # CRITICAL: do not set ``unknown_support_move_detected``
    # to ``True`` for non-move actions. A switch target
    # species name is NOT a support-move candidate;
    # tagging it as ``unknown_needs_probe`` would
    # falsely inflate Gate 17.
    "unknown_support_move_detected": False,
}


def build_non_move_classification(
    action_kind: str,
    metadata_source: str = "n/a",
    resolved_base_power: Optional[int] = None,
    resolved_category: Optional[str] = None,
) -> dict:
    """Build a per-candidate classification dict for
    a non-move action (switch, pass, unknown).

    Returns a copy of ``NON_MOVE_CLASSIFICATION``
    with the action kind, metadata source, and
    resolved metadata fields populated. The
    returned dict has all the keys the audit
    logger / builder expect, but
    ``unknown_support_move_detected=False`` so
    the support classifier is not falsely triggered.
    """
    out = dict(NON_MOVE_CLASSIFICATION)
    out["action_kind"] = action_kind
    out["is_move_action"] = action_kind == ACTION_KIND_MOVE
    out["is_switch_action"] = action_kind == ACTION_KIND_SWITCH
    out["is_pass_action"] = action_kind == ACTION_KIND_PASS
    out["metadata_source"] = metadata_source
    out["resolved_base_power"] = resolved_base_power
    out["resolved_category"] = resolved_category
    return out
