"""Pure data model for the local doubles decision graph viewer."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class GraphNode:
    node_id: str
    label: str
    kind: str
    column: int
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    source: str
    target: str
    label: str = ""
    kind: str = "normal"


@dataclass
class NodeLayout:
    x: float
    y: float
    width: float
    height: float


_LOCAL_NAMES: Optional[Dict[str, Dict[str, str]]] = None


def _load_local_names() -> Dict[str, Dict[str, str]]:
    global _LOCAL_NAMES
    if _LOCAL_NAMES is not None:
        return _LOCAL_NAMES
    _LOCAL_NAMES = {"moves": {}, "species": {}}
    base = (
        Path(sys.prefix) / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages" / "poke_env" / "data" / "static"
    )
    for key, path in (
        ("moves", base / "moves" / "gen9moves.json"),
        ("species", base / "pokedex" / "gen9pokedex.json"),
    ):
        try:
            with path.open(encoding="utf-8") as handle:
                data = json.load(handle)
            _LOCAL_NAMES[key] = {
                str(identifier): str(entry.get("name") or identifier)
                for identifier, entry in data.items()
            }
        except (OSError, ValueError, TypeError):
            pass
    return _LOCAL_NAMES


def display_name(identifier: Any, kind: str = "species") -> str:
    text = str(identifier or "").strip()
    if not text:
        return "Unknown"
    normalized = "".join(char for char in text.lower() if char.isalnum())
    local = _load_local_names().get(kind, {})
    return local.get(normalized, text.replace("_", " ").replace("-", " ").title())


def _active_species(turn_data: Dict[str, Any], side: str, index: int) -> str:
    values = turn_data.get(side) or []
    value = values[index] if index < len(values) else None
    if isinstance(value, dict):
        value = value.get("species") or value.get("name")
    return display_name(value) if value else f"Slot {index + 1}"


def parse_protocol_action(action: Any, slot_index: int, turn_data: Dict[str, Any],
                          target_override: Any = None) -> Dict[str, Any]:
    raw = str(action or "").strip()
    command = raw.removeprefix("/choose").strip()
    actor = _active_species(turn_data, "our_active", slot_index)
    if not command or command == "pass":
        return {"actor": actor, "verb": "Pass", "target": "", "kind": "pass", "raw": raw}
    parts = command.split()
    if parts[0] == "switch":
        destination = display_name(" ".join(parts[1:]))
        return {
            "actor": actor, "verb": f"Switch to {destination}", "target": "",
            "kind": "switch", "raw": raw,
        }
    if parts[0] == "move" and len(parts) >= 2:
        move = display_name(parts[1], "moves")
        target_position = next((int(part) for part in parts[2:] if part in ("1", "2")), None)
        if target_override:
            target = display_name(target_override)
        elif target_position:
            target = _active_species(turn_data, "opp_active", target_position - 1)
        else:
            target = "Opponents"
        modifiers = []
        if "terastallize" in parts:
            modifiers.append("Terastallize")
        if "mega" in parts:
            modifiers.append("Mega")
        verb = move + (f" · {' · '.join(modifiers)}" if modifiers else "")
        return {"actor": actor, "verb": verb, "target": target, "kind": "move", "raw": raw}
    return {"actor": actor, "verb": command, "target": "", "kind": "other", "raw": raw}


def describe_joint_order(order: Any, turn_data: Dict[str, Any]) -> str:
    raw = str(order or "").removeprefix("/choose").strip()
    segments = [segment.strip() for segment in raw.split(",")]
    descriptions = []
    for index, segment in enumerate(segments[:2]):
        action = parse_protocol_action(segment, index, turn_data)
        target = f" → {action['target']}" if action["target"] else ""
        descriptions.append(f"{action['actor']}: {action['verb']}{target}")
    return "\n".join(descriptions) if descriptions else "No action recorded"


def _slot_reasons(slot: Dict[str, Any], turn_data: Dict[str, Any]) -> List[str]:
    reasons = []
    if slot.get("expected_ko"):
        reasons.append("Expected knockout")
    damage = slot.get("expected_damage")
    if isinstance(damage, (int, float)) and damage > 0:
        reasons.append(f"Expected damage {damage * 100:.0f}%")
    action_types = slot.get("action_types") or {}
    if action_types.get("fakeout"):
        reasons.append("Fake Out pressure")
    if turn_data.get("focus_fire_triggered") or turn_data.get("both_slots_targeted_same_opp"):
        reasons.append("Focus fire")
    for key, label in (
        ("ability_hard_block_avoided", "Avoids known ability immunity"),
        ("speed_priority_protect_bonus_applied", "Protects against speed/priority threat"),
        ("speed_priority_switch_bonus_applied", "Safer switch under speed pressure"),
        ("revealed_switch_interception_selected", "Intercepts a revealed move"),
        ("priority_move_block_avoided", "Avoids field-blocked priority"),
    ):
        if slot.get(key):
            reasons.append(label)
    if not reasons:
        reasons.append("Highest-scoring legal joint plan")
    return reasons


def action_stories(turn_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    stories = []
    for slot_index in (0, 1):
        slot = turn_data.get(f"slot_{slot_index}") or {}
        action = parse_protocol_action(
            slot.get("action"), slot_index, turn_data, slot.get("target_species"),
        )
        action.update({
            "slot": slot_index + 1,
            "score": slot.get("selected_score"),
            "expected_damage": slot.get("expected_damage"),
            "expected_ko": slot.get("expected_ko"),
            "actual_damage": slot.get("actual_damage"),
            "actual_ko": slot.get("actual_ko"),
            "reasons": _slot_reasons(slot, turn_data),
            "detail": slot,
        })
        stories.append(action)
    return stories


def read_json_lines(path: str) -> Iterable[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(record, dict):
                    yield record
    except OSError:
        return


def _merge_dict(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = value
    return result


class DecisionStore:
    def __init__(self) -> None:
        self.battles: Dict[str, Dict[str, Any]] = {}

    def _battle(self, battle_tag: Any) -> Dict[str, Any]:
        tag = str(battle_tag or "unknown-battle")
        return self.battles.setdefault(tag, {"battle_tag": tag, "turns": {}})

    def apply_record(self, record: Dict[str, Any]) -> None:
        if not isinstance(record, dict):
            return
        battle = self._battle(record.get("battle_tag"))
        event = record.get("event")

        if "audit_turns" in record:
            for turn_data in record.get("audit_turns") or []:
                if isinstance(turn_data, dict) and turn_data.get("turn") is not None:
                    battle["turns"][int(turn_data["turn"])] = dict(turn_data)
            for key, value in record.items():
                if key != "audit_turns":
                    battle[key] = value
            return

        if event in ("decision", "outcome"):
            turn = record.get("turn")
            if turn is None:
                return
            turn = int(turn)
            old = battle["turns"].get(turn, {})
            update = {key: value for key, value in record.items()
                      if key not in ("event", "schema_version", "battle_tag")}
            battle["turns"][turn] = _merge_dict(old, update)
            return

        if event == "battle_end":
            for key, value in record.items():
                if key not in ("event", "schema_version"):
                    battle[key] = value

    def load_path(self, path: str) -> None:
        for record in read_json_lines(path):
            self.apply_record(record)

    def battle_tags(self) -> List[str]:
        return sorted(self.battles)

    def turn_numbers(self, battle_tag: str) -> List[int]:
        battle = self.battles.get(battle_tag, {})
        return sorted(battle.get("turns", {}))

    def get_turn(self, battle_tag: str, turn: int) -> Optional[Dict[str, Any]]:
        return self.battles.get(battle_tag, {}).get("turns", {}).get(int(turn))


class IncrementalJsonlTail:
    """Read only complete new JSONL records and recover from file truncation."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.offset = 0
        self.buffer = ""
        self._identity: Optional[Tuple[int, int]] = None
        self._prefix = b""

    def poll(self) -> List[Dict[str, Any]]:
        try:
            stat = os.stat(self.path)
        except OSError:
            return []

        identity = (stat.st_dev, stat.st_ino)
        replaced_same_size = False
        if self._identity == identity and self.offset and stat.st_size <= self.offset:
            try:
                with open(self.path, "rb") as probe:
                    replaced_same_size = probe.read(128) != self._prefix
            except OSError:
                return []
        if self._identity != identity or stat.st_size < self.offset or replaced_same_size:
            self.offset = 0
            self.buffer = ""
            self._identity = identity

        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                handle.seek(self.offset)
                chunk = handle.read()
                self.offset = handle.tell()
        except OSError:
            return []

        try:
            with open(self.path, "rb") as probe:
                self._prefix = probe.read(128)
        except OSError:
            pass
        if not chunk:
            return []
        text = self.buffer + chunk
        lines = text.split("\n")
        self.buffer = lines.pop()
        records = []
        for line in lines:
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(record, dict):
                records.append(record)
        return records


def _short(value: Any, limit: int = 42) -> str:
    text = str(value if value is not None else "")
    return text if len(text) <= limit else text[:limit - 1] + "..."


def _score_label(score: Any) -> str:
    try:
        return f"{float(score):.2f}"
    except (TypeError, ValueError):
        return "?"


def _active_label(active: Any, fallback: str) -> str:
    if isinstance(active, dict):
        species = active.get("species") or active.get("name") or fallback
        hp = active.get("hp_fraction", active.get("hp"))
        return f"{species}\nHP {float(hp) * 100:.0f}%" if isinstance(hp, (int, float)) else str(species)
    return _short(active or fallback)


def _iter_alternatives(turn_data: Dict[str, Any]) -> Iterable[Tuple[str, Any]]:
    alternatives = turn_data.get("top_5_alternatives") or []
    scores = turn_data.get("top_5_scores") or []
    for index, alternative in enumerate(alternatives[:5]):
        if isinstance(alternative, dict):
            label = alternative.get("message") or alternative.get("action") or str(alternative)
            score = alternative.get("score")
        else:
            label = alternative
            score = scores[index] if index < len(scores) else None
        yield str(label), score


def ranked_candidates(turn_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    summary = turn_summary(turn_data)
    warnings = summary.get("warnings", []) if isinstance(summary, dict) else []
    candidates = [{
        "label": str(turn_data.get("selected_joint_order") or "No selected order recorded"),
        "display": describe_joint_order(turn_data.get("selected_joint_order"), turn_data),
        "score": turn_data.get("selected_score"),
        "selected": True,
        "warnings": list(warnings),
    }]
    candidates.extend({
        "label": label,
        "display": describe_joint_order(label, turn_data),
        "score": score,
        "selected": False,
        "warnings": [],
    } for label, score in _iter_alternatives(turn_data))
    return candidates


def turn_summary(turn_data: Dict[str, Any]) -> Dict[str, Any]:
    flags = turn_data.get("flags") or turn_data
    warnings = []
    for slot_index in (0, 1):
        slot = turn_data.get(f"slot_{slot_index}") or {}
        for key, label in (
            ("ground_into_levitate_selected", "Ground into Levitate"),
            ("ability_immune_move_selected", "Ability immunity"),
            ("zero_effectiveness_move_selected", "Zero effectiveness"),
            ("priority_move_field_blocked", "Priority blocked by field"),
            ("expected_to_faint_before_moving", "Expected to faint first"),
        ):
            if slot.get(key) and label not in warnings:
                warnings.append(label)
    for key, label in (
        ("focus_fire_triggered", "Focus fire"),
        ("partial_immune_spread_selected", "Partial type immunity"),
        ("partial_ability_immune_spread_selected", "Partial ability immunity"),
    ):
        if flags.get(key) and label not in warnings:
            warnings.append(label)
    return {
        "selected_score": turn_data.get("selected_score"),
        "score_gap": turn_data.get("score_gap_selected_best_alt"),
        "legal_orders": turn_data.get("total_legal_joint_orders"),
        "signal": warnings[0] if warnings else "No safety warnings",
        "signal_kind": "warning" if warnings else "safe",
        "warnings": warnings,
    }


def inspector_sections(detail: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    detail = detail if isinstance(detail, dict) else {"value": detail}
    scoring_keys = {
        "selected_score", "expected_damage", "expected_ko", "best_spread_score",
        "best_ko_score", "score_gap_selected_best_alt", "total_legal_joint_orders",
        "actual_damage", "actual_ko",
    }
    safety_tokens = (
        "ability", "immune", "levitate", "priority", "safety", "threat",
        "faint", "protect", "redirection", "absorb", "effectiveness",
    )
    sections = {"Summary": {}, "Scoring": {}, "Safety": {}, "Raw": dict(detail)}
    for key, value in detail.items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        if key in scoring_keys or "score" in key or "damage" in key or key.endswith("_ko"):
            sections["Scoring"][key] = value
        elif any(token in key.lower() for token in safety_tokens):
            sections["Safety"][key] = value
        elif key in {
            "action", "move_type", "target_species", "selected_joint_order",
            "turn", "species", "hp", "hp_fraction", "outcome_known",
        }:
            sections["Summary"][key] = value
    if not sections["Summary"]:
        sections["Summary"] = {
            key: value for key, value in detail.items()
            if value not in (None, "", [], {}) and not isinstance(value, (dict, list))
        }
    return sections


def calculate_graph_layout(nodes: List[GraphNode]) -> Dict[str, NodeLayout]:
    columns = {0: 40.0, 1: 370.0, 2: 710.0, 3: 1050.0}
    grouped: Dict[int, List[GraphNode]] = {}
    for node in nodes:
        grouped.setdefault(node.column, []).append(node)
    layouts = {}
    for column, column_nodes in grouped.items():
        y = 40.0
        for node in column_nodes:
            line_count = max(1, node.label.count("\n") + 1)
            width = 250.0 if node.kind in ("candidate", "selected", "action") else 220.0
            height = max(76.0, 34.0 + line_count * 18.0)
            layouts[node.node_id] = NodeLayout(columns.get(column, 40.0 + column * 330.0),
                                               y, width, height)
            y += height + 30.0
    return layouts


def build_turn_graph(battle_tag: str, turn_data: Dict[str, Any]) -> Tuple[List[GraphNode], List[GraphEdge]]:
    turn = turn_data.get("turn", "?")
    nodes = [
        GraphNode("turn", f"Turn {turn}\n{_short(battle_tag, 34)}", "root", 0, turn_data),
    ]
    edges: List[GraphEdge] = []

    for index, active in enumerate(turn_data.get("our_active") or []):
        if active is None:
            continue
        node_id = f"our_{index}"
        active_label = display_name(active.get("species")) if isinstance(active, dict) else _active_label(active, "")
        nodes.append(GraphNode(node_id, f"OUR POKEMON\n{active_label}",
                               "context", 0, {"side": "our", "value": active}))
        edges.append(GraphEdge("turn", node_id, "active"))
    opponents = turn_data.get("opponent_actives_state") or turn_data.get("opp_active") or []
    for index, active in enumerate(opponents):
        if active is None:
            continue
        node_id = f"opp_{index}"
        active_label = display_name(active.get("species")) if isinstance(active, dict) else _active_label(active, "")
        nodes.append(GraphNode(node_id, f"OPPONENT\n{active_label}",
                               "opponent", 0, {"side": "opponent", "value": active}))
        edges.append(GraphEdge("turn", node_id, "observes"))

    for index, (label, score) in enumerate(_iter_alternatives(turn_data)):
        node_id = f"candidate_{index}"
        human_label = describe_joint_order(label, turn_data)
        nodes.append(GraphNode(node_id, f"ALTERNATIVE {index + 1}\n{_short(human_label, 70)}\nScore {_score_label(score)}",
                               "candidate", 1, {"action": label, "plan": human_label, "score": score}))
        edges.append(GraphEdge("turn", node_id, "considers"))

    selected = turn_data.get("selected_joint_order") or "No selected order recorded"
    selected_detail = {
        "selected_joint_order": selected,
        "plan": describe_joint_order(selected, turn_data),
        "selected_score": turn_data.get("selected_score"),
        "score_gap_selected_best_alt": turn_data.get("score_gap_selected_best_alt"),
        "total_legal_joint_orders": turn_data.get("total_legal_joint_orders"),
    }
    nodes.append(GraphNode(
        "selected",
        f"CHOSEN PLAN\n{_short(describe_joint_order(selected, turn_data), 76)}\nScore {_score_label(turn_data.get('selected_score'))}",
        "selected", 2, selected_detail,
    ))
    edges.append(GraphEdge("turn", "selected", "selects", "selected"))

    reason_specs = (
        ("ability_hard_block_avoided", "Ability block avoided", "blocked"),
        ("ability_immune_move_selected", "Ability-immune target", "blocked"),
        ("ground_into_levitate_selected", "Ground into Levitate", "blocked"),
        ("direct_absorb_hard_block_avoided", "Absorb block avoided", "blocked"),
        ("our_type_immune_move_selected", "Type-immune target", "blocked"),
        ("zero_effectiveness_move_selected", "Zero effectiveness", "blocked"),
        ("all_targets_immune_spread_selected", "All spread targets immune", "blocked"),
        ("partial_immune_spread_selected", "Partial type immunity", "warning"),
        ("partial_ability_immune_spread_selected", "Partial ability immunity", "warning"),
        ("speed_priority_threatened", "Speed/priority threat", "warning"),
        ("expected_to_faint_before_moving", "Expected to faint first", "warning"),
        ("singleton_hard_block_applied", "Singleton hard block", "blocked"),
        ("priority_move_field_blocked", "Priority blocked by field", "blocked"),
        ("revealed_switch_interception_selected", "Revealed-move interception", "reason"),
        ("expected_ko", "Expected KO", "outcome"),
    )
    stories = action_stories(turn_data)
    for slot_index in (0, 1):
        slot = turn_data.get(f"slot_{slot_index}") or {}
        story = stories[slot_index]
        action_id = f"slot_{slot_index}"
        target = f"\nTARGET: {story['target']}" if story["target"] else ""
        action_label = f"{story['actor']}\n{story['verb']}{target}"
        nodes.append(GraphNode(action_id, action_label, "action", 2, slot))
        edges.append(GraphEdge("selected", action_id, f"slot {slot_index + 1}", "selected"))

        for key, label, kind in reason_specs:
            if slot.get(key):
                reason_id = f"{action_id}_{key}"
                detail = {"reason": label, "field": key, "value": slot.get(key)}
                for extra in (
                    "ability_block_reason", "ability_blocked_target_species",
                    "ability_blocked_target_ability", "priority_move_block_reason",
                    "expected_damage", "actual_damage", "actual_ko",
                ):
                    if extra in slot:
                        detail[extra] = slot.get(extra)
                nodes.append(GraphNode(reason_id, label, kind, 3, detail))
                edges.append(GraphEdge(action_id, reason_id, "because"))

        if slot.get("outcome_known"):
            outcome = "KO" if slot.get("actual_ko") else f"Damage {slot.get('actual_damage', '?')}"
            outcome_id = f"{action_id}_outcome"
            nodes.append(GraphNode(outcome_id, f"Observed outcome\n{outcome}", "outcome", 3, slot))
            edges.append(GraphEdge(action_id, outcome_id, "resolved"))

    flags = turn_data.get("flags") or turn_data
    for key, label in (
        ("focus_fire_triggered", "Focus fire"),
        ("overkill_penalty_triggered", "Overkill penalty"),
        ("ally_hit_penalty_triggered", "Ally-hit penalty"),
        ("partial_immune_spread_selected", "Partial type immunity"),
        ("partial_ability_immune_spread_selected", "Partial ability immunity"),
    ):
        if flags.get(key):
            node_id = f"flag_{key}"
            nodes.append(GraphNode(node_id, label, "reason", 3, {"field": key, "value": True}))
            edges.append(GraphEdge("selected", node_id, "rule"))

    return nodes, edges


def format_detail(detail: Dict[str, Any]) -> str:
    if not isinstance(detail, dict):
        return str(detail)
    lines = []
    for key in sorted(detail):
        value = detail[key]
        if isinstance(value, (dict, list)):
            value = json.dumps(value, indent=2, ensure_ascii=False)
        lines.append(f"{key}: {value}")
    return "\n".join(lines)
