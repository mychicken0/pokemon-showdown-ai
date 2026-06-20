#!/usr/bin/env python3
"""Phase SCENARIO-2 — Scenario Loader + Validator.

A pure function module for loading scenario
JSON files and validating their structure.
No runner integration yet. No battle run.
No scoring change.

Per SCENARIO-1 design (logs/phaseSCENARIO1_framework_design.md),
a scenario file has the schema:

```json
{
  "scenario_id": "anti_tr_room_basic",
  "description": "Optional description",
  "version": 1,
  "our_team_file": "data/curated_teams/.../team_X.json",
  "opp_team_file": "data/curated_teams/.../team_Y.json",
  "seed": 42,
  "audit_path_suffix": "anti_tr_room",
  "script": {
    "turn_1": {
      "opp_slot_0": {"move": "trickroom", "target_pos": null},
      "opp_slot_1": {"move": "protect", "target_pos": null}
    }
  },
  "validators": [
    {
      "name": "tr_actually_used",
      "type": "expected_opp_action_used",
      "expected": true,
      "field": "opponent_used_trickroom"
    }
  ]
}
```

This module:
- Parses the JSON
- Validates required fields
- Normalizes move IDs (lowercase, no spaces)
- Validates team file paths exist
- Validates action schema (move/switch/target_pos)
- Parses validators

Pure function: no side effects, no scoring
change, no battle run.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union


# Schema constants
REQUIRED_TOP_FIELDS = frozenset({
    "scenario_id", "our_team_file", "opp_team_file", "script",
})
OPTIONAL_TOP_FIELDS = frozenset({
    "description", "version", "seed", "audit_path_suffix",
    "validators",
    # Phase SCENARIO-4: optional lead
    # spec; maps slot keys to species
    # names. The scripted opp leads with
    # these species at teampreview.
    "lead",
})
ALLOWED_SLOT_KEYS = frozenset({"opp_slot_0", "opp_slot_1"})
ALLOWED_ACTION_KEYS = frozenset({"move", "switch", "target_pos"})
ALLOWED_TARGET_POS = frozenset({1, 2, -1, -2, 0})

VALID_VALIDATOR_TYPES = frozenset({
    "expected_opp_action_used",
    "expected_audit_signal",
    "expected_bot_legal_response",
    "no_script_failures",
})


# ----------------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------------

class ScenarioValidationError(ValueError):
    """Raised when a scenario file fails
    schema validation. The error message
    includes the path and a clear
    explanation of what is wrong.
    """
    pass


# ----------------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------------

@dataclass
class ScenarioAction:
    """A single scripted action for one
    slot in one turn.

    Exactly one of `move` or `switch` is
    set. `target_pos` is optional.
    """
    move: Optional[str] = None
    target_pos: Optional[int] = None
    switch: Optional[str] = None

    def is_noop(self) -> bool:
        """Return True if this action is empty."""
        return self.move is None and self.switch is None


@dataclass
class ScenarioTurn:
    """A turn's scripted actions. Maps slot
    key (e.g. 'opp_slot_0') to action.
    """
    actions: Dict[str, ScenarioAction] = field(default_factory=dict)


@dataclass
class ScenarioValidator:
    """A post-battle validator.

    type:
    - expected_opp_action_used: check
      that opponent_used_<field> equals
      expected
    - expected_audit_signal: check that
      state_snapshot.<field> matches
      expected
    - expected_bot_legal_response: check
      that bot had `expected` move legal
    - no_script_failures: check that
      no scripted action failed
    """
    name: str
    type: str
    expected: Any = None
    field: Optional[str] = None
    threshold: Optional[float] = None

    def describe(self) -> str:
        """Human-readable description of
        this validator's check."""
        if self.type == "expected_opp_action_used":
            return (
                f"{self.name}: check that "
                f"opponent_used_{self.field} == "
                f"{self.expected!r}"
            )
        if self.type == "expected_audit_signal":
            return (
                f"{self.name}: check that "
                f"state_snapshot.{self.field} matches "
                f"{self.expected!r}"
            )
        if self.type == "expected_bot_legal_response":
            return (
                f"{self.name}: check that bot had "
                f"move {self.expected!r} legal at some "
                f"turn"
            )
        if self.type == "no_script_failures":
            return (
                f"{self.name}: check that no scripted "
                f"action failed (all script orders were "
                f"valid)"
            )
        return f"{self.name}: unknown validator type {self.type!r}"


@dataclass
class Scenario:
    """A loaded scenario file."""
    scenario_id: str
    description: str
    version: int
    our_team_file: str
    opp_team_file: str
    seed: Optional[int]
    audit_path_suffix: Optional[str]
    script: Dict[int, ScenarioTurn]  # turn -> actions
    validators: List[ScenarioValidator]
    # Phase SCENARIO-4: optional lead
    # specification. Maps slot keys
    # ('opp_slot_0', 'opp_slot_1') to
    # species names. The scripted opp
    # leads with these species at
    # teampreview.
    lead: Optional[Dict[str, str]] = None
    raw: Dict[str, Any] = field(default_factory=dict)  # original parsed JSON


# ----------------------------------------------------------------------------
# Move ID normalization
# ----------------------------------------------------------------------------

def _normalize_move_id(move_id: Any) -> str:
    """Normalize a move id: lowercase, strip
    whitespace, dashes, underscores,
    apostrophes. Examples:
      'Trick Room' -> 'trickroom'
      'Swords_Dance' -> 'swordsdance'
      "King's Shield" -> 'kingsshield'
    """
    return re.sub(r"[^a-z0-9]", "",
                  str(move_id or "").lower())


def _normalize_species(species: Any) -> str:
    """Normalize a species name."""
    return re.sub(r"[^a-z0-9]", "",
                  str(species or "").lower())


# ----------------------------------------------------------------------------
# Action parsing
# ----------------------------------------------------------------------------

def _parse_action(action_raw: Any, slot_key: str,
                 turn_key: int) -> ScenarioAction:
    """Parse a single action dict into a
    ScenarioAction. Raises
    ScenarioValidationError on invalid.
    """
    if not isinstance(action_raw, dict):
        raise ScenarioValidationError(
            f"turn {turn_key} {slot_key}: action must be "
            f"a dict, got {type(action_raw).__name__}"
        )
    bad_keys = set(action_raw.keys()) - ALLOWED_ACTION_KEYS
    if bad_keys:
        raise ScenarioValidationError(
            f"turn {turn_key} {slot_key}: invalid action "
            f"keys {sorted(bad_keys)}; allowed are "
            f"{sorted(ALLOWED_ACTION_KEYS)}"
        )
    has_move = "move" in action_raw
    has_switch = "switch" in action_raw
    if has_move and has_switch:
        raise ScenarioValidationError(
            f"turn {turn_key} {slot_key}: action has both "
            f"'move' and 'switch'; pick one"
        )
    if not has_move and not has_switch:
        # Noop action is OK (slot does nothing)
        return ScenarioAction()
    move = None
    target_pos = None
    switch = None
    if has_move:
        mv = action_raw["move"]
        if not isinstance(mv, str) or not mv.strip():
            raise ScenarioValidationError(
                f"turn {turn_key} {slot_key}: 'move' must "
                f"be a non-empty string, got {mv!r}"
            )
        move = _normalize_move_id(mv)
    if has_switch:
        sp = action_raw["switch"]
        if not isinstance(sp, str) or not sp.strip():
            raise ScenarioValidationError(
                f"turn {turn_key} {slot_key}: 'switch' "
                f"must be a non-empty string, got {sp!r}"
            )
        switch = _normalize_species(sp)
    if "target_pos" in action_raw:
        tp = action_raw["target_pos"]
        if tp is not None:
            if not isinstance(tp, int) or tp not in ALLOWED_TARGET_POS:
                raise ScenarioValidationError(
                    f"turn {turn_key} {slot_key}: "
                    f"'target_pos' must be one of "
                    f"{sorted(ALLOWED_TARGET_POS)} or "
                    f"null, got {tp!r}"
                )
            target_pos = tp
    return ScenarioAction(
        move=move, target_pos=target_pos, switch=switch,
    )


# ----------------------------------------------------------------------------
# Turn / script parsing
# ----------------------------------------------------------------------------

_TURN_KEY_RE = re.compile(r"^turn_(\d+)$")


def _parse_turn(turn_key: Any, turn_raw: Any) -> Tuple[int, ScenarioTurn]:
    """Parse a single turn entry. Returns
    (turn_number, ScenarioTurn). Raises
    ScenarioValidationError on invalid.
    """
    if not isinstance(turn_key, str):
        raise ScenarioValidationError(
            f"script key {turn_key!r} must be a string "
            f"like 'turn_1'"
        )
    m = _TURN_KEY_RE.match(turn_key)
    if not m:
        raise ScenarioValidationError(
            f"script key {turn_key!r} must match "
            f"pattern 'turn_<N>' where N is a positive "
            f"integer"
        )
    turn_num = int(m.group(1))
    if turn_num < 1:
        raise ScenarioValidationError(
            f"turn number must be >= 1, got {turn_num} "
            f"in key {turn_key!r}"
        )
    if not isinstance(turn_raw, dict):
        raise ScenarioValidationError(
            f"script[{turn_key!r}] must be a dict, got "
            f"{type(turn_raw).__name__}"
        )
    bad_slots = set(turn_raw.keys()) - ALLOWED_SLOT_KEYS
    if bad_slots:
        raise ScenarioValidationError(
            f"script[{turn_key!r}] has invalid slot "
            f"keys {sorted(bad_slots)}; allowed are "
            f"{sorted(ALLOWED_SLOT_KEYS)}"
        )
    actions: Dict[str, ScenarioAction] = {}
    for slot_key, action_raw in turn_raw.items():
        actions[slot_key] = _parse_action(
            action_raw, slot_key, turn_num
        )
    return turn_num, ScenarioTurn(actions=actions)


# ----------------------------------------------------------------------------
# Validator parsing
# ----------------------------------------------------------------------------

def _parse_validator(
    vraw: Any, idx: int,
) -> ScenarioValidator:
    """Parse a single validator entry."""
    if not isinstance(vraw, dict):
        raise ScenarioValidationError(
            f"validators[{idx}] must be a dict, got "
            f"{type(vraw).__name__}"
        )
    bad_keys = set(vraw.keys()) - {
        "name", "type", "expected", "field", "threshold",
    }
    if bad_keys:
        raise ScenarioValidationError(
            f"validators[{idx}] has invalid keys "
            f"{sorted(bad_keys)}"
        )
    name = vraw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ScenarioValidationError(
            f"validators[{idx}] 'name' must be a "
            f"non-empty string, got {name!r}"
        )
    vtype = vraw.get("type")
    if vtype not in VALID_VALIDATOR_TYPES:
        raise ScenarioValidationError(
            f"validators[{idx}] 'type' must be one of "
            f"{sorted(VALID_VALIDATOR_TYPES)}, got {vtype!r}"
        )
    # Field is required for some types
    if vtype in (
        "expected_opp_action_used",
        "expected_audit_signal",
    ) and "field" not in vraw:
        raise ScenarioValidationError(
            f"validators[{idx}] ({name!r}) type "
            f"{vtype!r} requires 'field'"
        )
    field = vraw.get("field")
    if field is not None and not isinstance(field, str):
        raise ScenarioValidationError(
            f"validators[{idx}] 'field' must be a string, "
            f"got {field!r}"
        )
    threshold = vraw.get("threshold")
    if threshold is not None and not isinstance(
        threshold, (int, float)
    ):
        raise ScenarioValidationError(
            f"validators[{idx}] 'threshold' must be a "
            f"number, got {threshold!r}"
        )
    expected = vraw.get("expected")
    return ScenarioValidator(
        name=name,
        type=vtype,
        expected=expected,
        field=field,
        threshold=threshold,
    )


# ----------------------------------------------------------------------------
# Top-level loader
# ----------------------------------------------------------------------------

def load_scenario_file(path: str) -> Scenario:
    """Load a scenario file from disk and
    return a validated Scenario object.
    Raises ScenarioValidationError on any
    schema issue. Raises FileNotFoundError
    if path does not exist.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"scenario file not found: {path}"
        )
    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ScenarioValidationError(
            f"scenario file {path!r} is not valid JSON: "
            f"{e}"
        )
    return load_scenario_dict(data, source_path=path)


def load_scenario_dict(
    data: Any, source_path: Optional[str] = None,
) -> Scenario:
    """Load a scenario from an already-parsed
    dict. Validates structure. Raises
    ScenarioValidationError on any issue.
    `source_path` is only used for error
    messages.
    """
    src = source_path or "<dict>"
    if not isinstance(data, dict):
        raise ScenarioValidationError(
            f"scenario {src} must be a JSON object, "
            f"got {type(data).__name__}"
        )
    missing = REQUIRED_TOP_FIELDS - set(data.keys())
    if missing:
        raise ScenarioValidationError(
            f"scenario {src} missing required fields: "
            f"{sorted(missing)}"
        )
    bad_top = set(data.keys()) - (
        REQUIRED_TOP_FIELDS | OPTIONAL_TOP_FIELDS
    )
    if bad_top:
        raise ScenarioValidationError(
            f"scenario {src} has invalid top-level "
            f"fields: {sorted(bad_top)}"
        )
    # scenario_id
    scenario_id = data["scenario_id"]
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ScenarioValidationError(
            f"scenario {src}: 'scenario_id' must be a "
            f"non-empty string, got {scenario_id!r}"
        )
    # description
    description = data.get("description", "")
    if not isinstance(description, str):
        raise ScenarioValidationError(
            f"scenario {src}: 'description' must be a "
            f"string, got {type(description).__name__}"
        )
    # version
    version = data.get("version", 1)
    if not isinstance(version, int) or version < 1:
        raise ScenarioValidationError(
            f"scenario {src}: 'version' must be a "
            f"positive int, got {version!r}"
        )
    # team files
    our_team = data["our_team_file"]
    opp_team = data["opp_team_file"]
    if not isinstance(our_team, str) or not our_team.strip():
        raise ScenarioValidationError(
            f"scenario {src}: 'our_team_file' must be a "
            f"non-empty string"
        )
    if not isinstance(opp_team, str) or not opp_team.strip():
        raise ScenarioValidationError(
            f"scenario {src}: 'opp_team_file' must be a "
            f"non-empty string"
        )
    if our_team == opp_team:
        raise ScenarioValidationError(
            f"scenario {src}: our_team_file and "
            f"opp_team_file must differ"
        )
    # Team file existence check. Only verify
    # paths that are project-relative
    # (starting with 'data/' or './'). Absolute
    # paths like '/tmp/foo.json' are accepted
    # as-is (the runner does the real check).
    if not our_team.startswith("/") and (
        our_team.startswith("data/") or
        our_team.startswith("./")
    ):
        if not os.path.isfile(our_team):
            raise ScenarioValidationError(
                f"scenario {src}: our_team_file "
                f"{our_team!r} does not exist"
            )
    if not opp_team.startswith("/") and (
        opp_team.startswith("data/") or
        opp_team.startswith("./")
    ):
        if not os.path.isfile(opp_team):
            raise ScenarioValidationError(
                f"scenario {src}: opp_team_file "
                f"{opp_team!r} does not exist"
            )
    # seed
    seed = data.get("seed")
    if seed is not None and not isinstance(seed, int):
        raise ScenarioValidationError(
            f"scenario {src}: 'seed' must be an int, "
            f"got {type(seed).__name__}"
        )
    # audit_path_suffix
    audit_suffix = data.get("audit_path_suffix")
    if audit_suffix is not None:
        if not isinstance(audit_suffix, str) or not audit_suffix.strip():
            raise ScenarioValidationError(
                f"scenario {src}: 'audit_path_suffix' "
                f"must be a non-empty string"
            )
    # script
    script_raw = data["script"]
    if not isinstance(script_raw, dict):
        raise ScenarioValidationError(
            f"scenario {src}: 'script' must be a dict"
        )
    script: Dict[int, ScenarioTurn] = {}
    for turn_key, turn_raw in script_raw.items():
        turn_num, turn = _parse_turn(turn_key, turn_raw)
        if turn_num in script:
            raise ScenarioValidationError(
                f"scenario {src}: duplicate turn "
                f"key {turn_key!r}"
            )
        script[turn_num] = turn
    # validators
    validators: List[ScenarioValidator] = []
    validators_raw = data.get("validators", [])
    if not isinstance(validators_raw, list):
        raise ScenarioValidationError(
            f"scenario {src}: 'validators' must be a "
            f"list, got {type(validators_raw).__name__}"
        )
    for idx, vraw in enumerate(validators_raw):
        validators.append(_parse_validator(vraw, idx))
    # Phase SCENARIO-4: optional lead dict
    lead: Optional[Dict[str, str]] = None
    lead_raw = data.get("lead", None)
    if lead_raw is not None:
        if not isinstance(lead_raw, dict):
            raise ScenarioValidationError(
                f"scenario {src}: 'lead' must be a "
                f"dict, got {type(lead_raw).__name__}"
            )
        for slot_key, species in lead_raw.items():
            if slot_key not in ALLOWED_SLOT_KEYS:
                raise ScenarioValidationError(
                    f"scenario {src}: 'lead' has "
                    f"invalid slot key {slot_key!r}, "
                    f"expected one of "
                    f"{sorted(ALLOWED_SLOT_KEYS)}"
                )
            if not isinstance(species, str) or not species.strip():
                raise ScenarioValidationError(
                    f"scenario {src}: 'lead' has "
                    f"non-string or empty species "
                    f"for {slot_key!r}"
                )
        lead = {k: v for k, v in lead_raw.items()}
    return Scenario(
        scenario_id=scenario_id,
        description=description,
        version=version,
        our_team_file=our_team,
        opp_team_file=opp_team,
        seed=seed,
        audit_path_suffix=audit_suffix,
        script=script,
        validators=validators,
        lead=lead,
        raw=data,
    )


# ----------------------------------------------------------------------------
# Validator execution (skeleton, runs against audit data)
# ----------------------------------------------------------------------------

def run_validators(
    scenario: Scenario,
    audit_data: Any,
) -> List[Tuple[ScenarioValidator, bool, str]]:
    """Run all validators against a parsed
    audit JSONL content. Returns a list of
    (validator, passed, message) tuples.

    This is a SKELETON. It demonstrates how
    validators would run. Real implementation
    in SCENARIO-3+ would extend this.

    Args:
        scenario: the loaded Scenario
        audit_data: parsed JSONL content
            (list of battle records, or single
            record)

    Returns:
        list of (validator, passed, message)
    """
    results: List[Tuple[ScenarioValidator, bool, str]] = []
    # Normalize audit_data to list of records
    if isinstance(audit_data, dict):
        records = [audit_data]
    elif isinstance(audit_data, list):
        records = audit_data
    else:
        return [
            (v, False, "audit_data must be a dict or list")
            for v in scenario.validators
        ]
    for validator in scenario.validators:
        passed, msg = _run_one_validator(
            validator, records,
        )
        results.append((validator, passed, msg))
    return results


def _run_one_validator(
    validator: ScenarioValidator,
    records: List[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Run a single validator. Returns
    (passed, message)."""
    if validator.type == "no_script_failures":
        # No audit data needed
        return (True, "no_script_failures (skeleton, no audit data)")
    if validator.type == "expected_opp_action_used":
        return _check_opp_action_used(
            validator, records
        )
    if validator.type == "expected_audit_signal":
        return _check_audit_signal(
            validator, records
        )
    if validator.type == "expected_bot_legal_response":
        return _check_bot_legal_response(
            validator, records
        )
    return (False, f"unknown validator type {validator.type!r}")


def _check_opp_action_used(
    validator: ScenarioValidator,
    records: List[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Check that opponent_used_<field>
    matches expected across all records."""
    field_name = f"opponent_used_{validator.field}"
    matches = 0
    for rec in records:
        for t in rec.get("audit_turns", []):
            opp = t.get("opponent_actions", {}) or {}
            if opp.get(field_name) == validator.expected:
                matches += 1
    if validator.expected is True and matches == 0:
        return (False, f"{field_name} never True across "
                f"{len(records)} records")
    if validator.expected is False and matches > 0:
        return (False, f"{field_name} True in {matches} "
                f"turns (expected False)")
    return (True, f"{field_name} ok ({matches} matches)")


def _check_audit_signal(
    validator: ScenarioValidator,
    records: List[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Check that state_snapshot.<field>
    matches expected."""
    seen_values: List[Any] = []
    for rec in records:
        for t in rec.get("audit_turns", []):
            snap = t.get("state_snapshot", {}) or {}
            if validator.field in snap:
                seen_values.append(snap[validator.field])
    expected = validator.expected
    # Compare using equality (works for both
    # hashable and unhashable types)
    for v in seen_values:
        if _values_equal(v, expected):
            return (
                True,
                f"state_snapshot.{validator.field} matches "
                f"{expected!r}",
            )
    return (
        False,
        f"state_snapshot.{validator.field} never "
        f"matched {expected!r} (seen: "
        f"{_truncate_list(seen_values)})",
    )


def _values_equal(a: Any, b: Any) -> bool:
    """Equality check that handles lists,
    dicts, and other types."""
    try:
        if a == b:
            return True
    except Exception:
        pass
    return False


def _truncate_list(vals: List[Any], n: int = 5) -> str:
    """Format list for error messages."""
    if len(vals) <= n:
        return str(vals)
    return str(vals[:n]) + f" ... ({len(vals)} total)"


def _check_bot_legal_response(
    validator: ScenarioValidator,
    records: List[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Check that bot had `expected` move
    legal at some turn."""
    target_move = _normalize_move_id(validator.expected)
    seen_turns: List[int] = []
    for rec in records:
        for t in rec.get("audit_turns", []):
            turn = t.get("turn")
            for slot in [0, 1]:
                legal = t.get(
                    f"v2l1_legal_action_keys_slot{slot}", []
                ) or []
                for entry in legal:
                    if not isinstance(entry, (list, tuple)):
                        continue
                    if len(entry) < 2:
                        continue
                    kind, mv = entry[0], entry[1]
                    if kind != "move":
                        continue
                    if _normalize_move_id(mv) == target_move:
                        seen_turns.append(turn)
                        break
    if not seen_turns:
        return (
            False,
            f"bot never had move {validator.expected!r} "
            f"legal",
        )
    return (
        True,
        f"bot had {validator.expected!r} legal in "
        f"{len(seen_turns)} turns",
    )


# ----------------------------------------------------------------------------
# Self-check
# ----------------------------------------------------------------------------

def main() -> int:
    print("scenario_probe.py — pure function module")
    print("Import load_scenario_file() and "
          "run_validators() to use.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
