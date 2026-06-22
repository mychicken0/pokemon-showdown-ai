"""Phase RL-DATA-3a — Tiny local audit smoke.

This script verifies the end-to-end flow:

1. Audit logger (DoublesDecisionAuditLogger) calls
   ``log_turn_decision`` with a tiny mocked battle
   state and V4a legal-action keys.
2. Audit logger persists a battle JSONL to
   ``logs/doubles_audit_v1_1_smoke.jsonl``.
3. The v1.1 builder
   (``showdown_ai/build_turn_level_offline_dataset.py``)
   reads the JSONL and produces a v1.1 dataset.
4. The v1.1 analyzer
   (``scripts/analyze/analyze_turn_level_offline_dataset_quality.py``)
   runs the 8 v1.1 data-quality gates (gates 11-18)
   on the dataset.
5. The dry-run
   (``showdown_ai/dryrun_turn_level_offline_policy.py``)
   loads the dataset (v1.0/v1.1 compat).
6. The script reports the final analyzer result
   (READY / WARN / BLOCKED).

This script does **not** train any model. It does
**not** build a 5k dataset. It does **not** run
battles. It uses 1 mocked battle with 1 turn.

It is a tiny local smoke only, sized to verify
that audit-emitted v1.1 fields are accepted by the
builder, analyzer, and dry-run end-to-end.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from typing import Any, Dict, List, Optional

# Ensure the project root is on sys.path so the
# builder / analyzer / dry-run can be imported.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(PROJECT_ROOT)
sys.path.insert(0, REPO_ROOT)

from doubles_decision_audit_logger import (  # noqa: E402
    DoublesDecisionAuditLogger,
)


# ------------------------------------------------------------------
# Mocked battle / pokemon
# ------------------------------------------------------------------
class _MockMove:
    """A minimal move stand-in for the audit logger."""

    def __init__(self, move_id):
        self.id = move_id
        self.base_power = 0
        self.type = None
        self.category = None
        self.target = "normal"


class _MockPokemon:
    """A minimal Pokemon stand-in for the audit logger."""

    def __init__(self, species, types=None, hp_fraction=1.0,
                 ability=None, item=None, moves=None):
        self.species = species
        self._types = types or []
        self._hp_fraction = hp_fraction
        self.ability = ability
        self.item = item
        self._moves = moves or []
        self.boosts = {}
        self.status = None
        self.fainted = False
        self.active = True

    @property
    def types(self):
        return list(self._types)

    @property
    def current_hp_fraction(self):
        return self._hp_fraction

    @property
    def moves(self):
        return dict(self._moves)


class _MockBattle:
    """A minimal battle stand-in for the audit logger."""

    def __init__(self, our_active, opp_active,
                 weather=None, fields=None, side_conditions=None,
                 opp_side_conditions=None,
                 player_role="p1", player_username="AuditSmokeBot"):
        self.active_pokemon = list(our_active)
        self.opponent_active_pokemon = list(opp_active)
        self.weather = weather
        self.fields = fields or []
        self.side_conditions = side_conditions or {}
        self.opponent_side_conditions = opp_side_conditions or {}
        self.player_role = player_role
        self.player_username = player_username
        self.turn = 1
        self._replay_data = []


# ------------------------------------------------------------------
# Smoke run
# ------------------------------------------------------------------
def _build_smoke_battle() -> Dict[str, Any]:
    """Build a tiny 1-battle 1-turn record via the
    real audit logger.

    Returns a dict with the audit logger, the
    ``battle_tag`` used, and the V4a legal / selected
    keys for the smoke.
    """
    weather = "RainDance"  # poke-env enum-like
    fields: List[Any] = []
    our_active = [
        _MockPokemon("Politoed", ["WATER"], hp_fraction=1.0),
        _MockPokemon("Incineroar", ["FIRE", "DARK"], hp_fraction=0.95),
    ]
    opp_active = [
        _MockPokemon("Garchomp", ["DRAGON", "GROUND"], hp_fraction=1.0),
        _MockPokemon("Tyranitar", ["ROCK", "DARK"], hp_fraction=1.0),
    ]
    battle = _MockBattle(
        our_active=our_active,
        opp_active=opp_active,
        weather=weather,
        fields=fields,
    )

    # Use a real ``logs/`` path so the smoke can be
    # inspected by humans.
    out_path = os.path.join(
        REPO_ROOT, "logs", "doubles_audit_v1_1_smoke.jsonl"
    )
    logger = DoublesDecisionAuditLogger(
        filepath=out_path, reset=True, detail_level="top5"
    )

    battle_tag = "audit_v1_1_smoke_battle_001"
    # Required by log_turn_decision; pick a minimal
    # valid config object.
    from bot_doubles_damage_aware import (
        DoublesDamageAwareConfig,
    )
    logger.battle_configs[battle_tag] = DoublesDamageAwareConfig()

    # Set battle-arm metadata so save_battle can
    # populate the persisted row's metadata.
    logger.set_current_battle_meta(
        benchmark_arm="treatment",
        enable_mega_evolution=False,
        enable_decision_timing_diagnostics=False,
        treatment_side="p1",
        player_side="p1",
        player_name="AuditSmokeBot",
    )

    v4a_legal0 = [
        ["move", "raindance", 0, "no_mechanic"],
        ["move", "hurricane", 0, "no_mechanic"],
        ["move", "surf", 0, "no_mechanic"],
        # Phase RL-DATA-3a.2: ``boltstrike`` is a
        # damaging move that is NOT in the static
        # fallback table. The smoke proves that the
        # override path correctly classifies it as
        # damage-like (rather than
        # ``unknown_needs_probe``).
        ["move", "boltstrike", 0, "no_mechanic"],
    ]
    v4a_legal1 = [
        ["move", "fakeout", 1, "no_mechanic"],
        ["move", "protect", 1, "no_mechanic"],
    ]
    v4a_sel = [
        ["move", "raindance", 0, "no_mechanic"],
        ["move", "protect", 1, "no_mechanic"],
    ]
    v4a_final = list(v4a_sel)

    v2l1_legal0 = [
        ("move", "raindance", 0, "no_mechanic"),
        ("move", "hurricane", 0, "no_mechanic"),
        ("move", "surf", 0, "no_mechanic"),
    ]
    v2l1_legal1 = [
        ("move", "fakeout", 1, "no_mechanic"),
        ("move", "protect", 1, "no_mechanic"),
    ]
    v2l1_sel = (
        ("move", "raindance", 0, "no_mechanic"),
        ("move", "protect", 1, "no_mechanic"),
    )
    v2l1_final = list(v2l1_sel)

    # Use a real ``_MockBattle`` but call log_turn_decision
    # with a minimal / safe set of kwargs. Many kwargs
    # default to None and the audit logger handles None.
    logger.log_turn_decision(
        battle_tag=battle_tag,
        turn=1,
        battle=battle,
        selected_joint_order="/choose move raindance 0, move protect 1",
        selected_score=150.0,
        scored_joint_orders=[],
        expected_damages=[0.0, 0.0],
        expected_kos=[False, False],
        target_hps=[1.0, 1.0],
        overkill_triggered=False,
        focus_fire_triggered=False,
        ally_hit_penalty_triggered=False,
        spread_available=[False, False],
        best_spread_score=[0.0, 0.0],
        best_ko_score=[0.0, 0.0],
        low_hp_opponent_existed=False,
        low_hp_opponent_targeted=False,
        slot_actions=[
            "/choose move raindance 0",
            "/choose move protect 1",
        ],
        slot_action_types=[
            {
                "damaging": False, "status": True, "protect": False,
                "fakeout": False, "spread": False, "switch": False,
            },
            {
                "damaging": False, "status": True, "protect": True,
                "fakeout": False, "spread": False, "switch": False,
            },
        ],
        target_species=[None, None],
        # V2l.1 / V4a kwargs
        runtime_mode="gen9randomdoublesbattle",
        concrete_player_class="DoublesDamageAwarePlayer",
        shared_engine_used=True,
        shared_engine_owner="DoublesDamageAwarePlayer",
        shared_engine_invocation_id="smoke_inv_001",
        shared_engine_invocation_status="completed",
        selected_four=None,
        lead_2=None,
        back_2=None,
        preview_policy="audit_smoke",
        v2l1_legal_action_keys_slot0=list(v2l1_legal0),
        v2l1_legal_action_keys_slot1=list(v2l1_legal1),
        v2l1_raw_scores_slot0={
            "move|raindance|0|no_mechanic": 80.0,
            "move|hurricane|0|no_mechanic": 60.0,
            "move|surf|0|no_mechanic": 70.0,
        },
        v2l1_raw_scores_slot1={
            "move|fakeout|1|no_mechanic": 70.0,
            "move|protect|1|no_mechanic": 50.0,
        },
        v2l1_selected_joint_key=list(v2l1_sel),
        v2l1_final_action_keys=list(v2l1_final),
        v4a_legal_action_keys_slot0=list(v4a_legal0),
        v4a_legal_action_keys_slot1=list(v4a_legal1),
        v4a_raw_scores_slot0={
            "move|raindance|0|no_mechanic": 80.0,
        },
        v4a_raw_scores_slot1={},
        v4a_selected_joint_key=list(v4a_sel),
        v4a_final_action_keys=list(v4a_final),
        # Phase RL-DATA-3a.2: pass a live move
        # metadata override. The override provides
        # ``fakeout`` and ``hurricane`` (both already
        # in the static fallback) and an unusual
        # damaging move ``boltstrike`` that is NOT
        # in the static fallback. Without the
        # override, ``boltstrike`` would be flagged
        # as ``unknown_needs_probe``. With the
        # override, the classifier receives
        # ``base_power=130, category=physical`` and
        # correctly identifies it as damage-like.
        # The override also covers ``raindance`` and
        # ``protect`` to demonstrate that override
        # entries (with ``metadata_source="override"``)
        # take precedence over the static fallback
        # (which would have set
        # ``metadata_source="fallback"``).
        move_metadata_map_override={
            "fakeout": {
                "base_power": 40,
                "category": "physical",
                "move_type": "normal",
                "target": "normal",
            },
            "hurricane": {
                "base_power": 110,
                "category": "special",
                "move_type": "flying",
                "target": "allAdjacentFoes",
            },
            "boltstrike": {
                "base_power": 130,
                "category": "physical",
                "move_type": "electric",
                "target": "normal",
            },
            "raindance": {
                "base_power": 0,
                "category": "status",
                "move_type": "water",
                "target": "all",
            },
            "protect": {
                "base_power": 0,
                "category": "status",
                "move_type": "normal",
                "target": "self",
            },
        },
    )
    # Mark a winner and save. The smoke uses a simple
    # deterministic winner.
    logger.save_battle(
        battle_tag=battle_tag,
        winner="AuditSmokeBot",
        battle=battle,
    )

    return {
        "logger": logger,
        "battle_tag": battle_tag,
        "out_path": out_path,
    }


def _run_smoke() -> Dict[str, Any]:
    """Run the smoke end-to-end.

    Returns a report dict with the result of each
    stage and the final analyzer result.
    """
    from showdown_ai.build_turn_level_offline_dataset import (
        build_dataset_from_artifact,
    )
    from showdown_ai.dryrun_turn_level_offline_policy import (
        _load_dataset as dryrun_load,
    )
    from analyze_turn_level_offline_dataset_quality import (
        analyze,
    )

    info = _build_smoke_battle()
    out_path = info["out_path"]
    assert os.path.exists(out_path), (
        f"smoke did not write {out_path}"
    )
    with open(out_path) as f:
        first_line = f.readline().strip()
    assert first_line, "smoke JSONL is empty"
    battle_record = json.loads(first_line)
    assert battle_record.get("battle_tag") == info["battle_tag"]
    audit_turns = battle_record.get("audit_turns") or []
    assert len(audit_turns) == 1, (
        f"expected 1 audit turn, got {len(audit_turns)}"
    )
    first_turn = audit_turns[0]
    v11_keys_present = [
        k for k in (
            "local_only_provenance",
            "used_species_ability_inference",
            "weather_current",
            "setter_move_legal",
            "setter_move_selected",
            "type_boost_move_legal",
            "support_move_distribution",
            "unknown_support_move_detected",
        )
        if k in first_turn
    ]
    audit_emitted = {
        "v1_1_keys_present": v11_keys_present,
        "v1_1_keys_missing": [
            k for k in (
                "local_only_provenance",
                "used_species_ability_inference",
                "weather_current",
                "setter_move_legal",
                "setter_move_selected",
                "type_boost_move_legal",
                "support_move_distribution",
                "unknown_support_move_detected",
            )
            if k not in first_turn
        ],
    }

    rows, skipped = build_dataset_from_artifact(
        out_path, "treatment", "audit_v1_1_smoke"
    )
    assert rows, "builder produced zero rows"
    assert not skipped, f"builder skipped rows: {skipped[:3]}"

    # Write a tiny dataset JSONL so the analyzer can read it.
    dataset_path = os.path.join(
        REPO_ROOT, "logs", "doubles_audit_v1_1_smoke_dataset.jsonl"
    )
    with open(dataset_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    # Run the analyzer
    report = analyze([dataset_path])
    v11_gates = report.get("v11_gates", {})

    # Phase RL-DATA-3a.2: count per-source
    # classifications in the per-candidate
    # support_classification. The override path
    # should produce ``metadata_source="override"``
    # for moves that were in the override; the
    # static fallback should produce
    # ``metadata_source="fallback"`` for moves
    # that were not in the override.
    per_source: Dict[str, int] = {}
    for r in rows:
        per = r.get("per_candidate_support_classification", {})
        if not isinstance(per, dict):
            continue
        for mid, cls in per.items():
            if not isinstance(cls, dict):
                continue
            src = cls.get("metadata_source", "unknown")
            per_source[src] = per_source.get(src, 0) + 1

    # Confirm the dry-run can read the dataset
    dryrun_loaded = dryrun_load(dataset_path)
    assert len(dryrun_loaded) == len(rows), (
        f"dry-run loaded {len(dryrun_loaded)} rows, "
        f"expected {len(rows)}"
    )

    return {
        "audit_path": out_path,
        "dataset_path": dataset_path,
        "n_battle_records": 1,
        "n_audit_turns": len(audit_turns),
        "n_rows": len(rows),
        "n_skipped": len(skipped),
        "v11_emission": audit_emitted,
        "v11_gates": v11_gates,
        "analyzer_readiness_impact": (
            v11_gates.get("readiness_impact")
        ),
        "analyzer_v11_n_rows": v11_gates.get("v11_n_rows"),
        "analyzer_v10_n_rows": v11_gates.get("v10_n_rows"),
        "analyzer_hard_blocks": v11_gates.get("hard_blocks"),
        "analyzer_warnings": v11_gates.get("warnings"),
        "analyzer_field_coverage": v11_gates.get(
            "field_coverage"
        ),
        "per_candidate_source_counts": per_source,
        "dryrun_loaded_n_rows": len(dryrun_loaded),
    }


def main():
    print("=" * 70)
    print("RL-DATA-3a.2 — Tiny Local Audit Smoke (with override)")
    print("=" * 70)
    result = _run_smoke()
    print()
    print("Stage 1: Audit emission")
    print(f"  battle records: {result['n_battle_records']}")
    print(f"  audit turns: {result['n_audit_turns']}")
    print(f"  v1.1 keys present in turn: "
          f"{len(result['v11_emission']['v1_1_keys_present'])}")
    print(f"  v1.1 keys missing in turn: "
          f"{len(result['v11_emission']['v1_1_keys_missing'])}")
    if result['v11_emission']['v1_1_keys_missing']:
        print(f"  missing keys: "
              f"{result['v11_emission']['v1_1_keys_missing']}")
    print()
    print("Stage 2: Builder")
    print(f"  rows: {result['n_rows']}")
    print(f"  skipped: {result['n_skipped']}")
    print()
    print("Stage 3: Analyzer")
    print(f"  v1.1 readiness_impact: "
          f"{result['analyzer_readiness_impact']}")
    print(f"  v1.1 n_rows: {result['analyzer_v11_n_rows']}")
    print(f"  v1.0 n_rows: {result['analyzer_v10_n_rows']}")
    print(f"  hard_blocks: {result['analyzer_hard_blocks']}")
    print(f"  warnings: "
          f"{len(result['analyzer_warnings'])} item(s)")
    print()
    print("Per-candidate metadata source counts:")
    for src, count in sorted(
        result.get("per_candidate_source_counts", {}).items()
    ):
        print(f"  {src}: {count}")
    print()
    print("Stage 4: Dry-run")
    print(f"  loaded rows: {result['dryrun_loaded_n_rows']}")
    print()
    print("Result: see logs/doubles_audit_v1_1_smoke.jsonl and")
    print("        logs/doubles_audit_v1_1_smoke_dataset.jsonl")
    return result


if __name__ == "__main__":
    main()
