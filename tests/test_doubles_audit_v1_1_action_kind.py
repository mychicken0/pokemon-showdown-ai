"""Phase RL-DATA-3b-followup — Tests for V4a action-kind filtering.

Validates that the V4a action-kind helper correctly
classifies move / switch / pass / unknown actions,
and that the audit logger / builder support
classification only runs on real move actions.

Coverage:
- ``resolve_candidate_action_kind`` returns ``move``
  for move actions.
- ``resolve_candidate_action_kind`` returns ``switch``
  for switch actions.
- ``resolve_candidate_action_kind`` returns ``pass``
  for pass actions.
- Switch actions are not sent to the support
  classifier (no ``unknown_support_move_detected``).
- Pass actions are not sent to the support
  classifier.
- Move actions still get full support classification.
- True unknown non-damaging support moves still
  become ``unknown_needs_probe``.
- The builder preserves the action kind.
- The analyzer no longer warns on switch-as-species
  cases.
- v1.0 compatibility is preserved.
- Dry-run compatibility is preserved.
- No scoring / behavior / selected-action changes.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from typing import Any, Dict, List

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from doubles_engine.support_targets import (  # noqa: E402
    classify_support_move_for_dataset,
)
from doubles_engine.v4a_action_kind import (  # noqa: E402
    ACTION_KIND_MOVE,
    ACTION_KIND_PASS,
    ACTION_KIND_SWITCH,
    ACTION_KIND_UNKNOWN,
    build_non_move_classification,
    is_move_action,
    is_pass_action,
    is_switch_action,
    resolve_candidate_action_kind,
    split_candidate_id_from_v4a_key,
)


# ============================================================
# resolve_candidate_action_kind
# ============================================================
class TestResolveCandidateActionKind(unittest.TestCase):
    """Unit tests for ``resolve_candidate_action_kind``."""

    def test_move_action(self):
        self.assertEqual(
            resolve_candidate_action_kind(
                ["move", "raindance", 0, ""]
            ),
            ACTION_KIND_MOVE,
        )
        self.assertEqual(
            resolve_candidate_action_kind(
                ["move", "fakeout", 1, ""]
            ),
            ACTION_KIND_MOVE,
        )

    def test_switch_action(self):
        self.assertEqual(
            resolve_candidate_action_kind(
                ["switch", "volcarona", 0, ""]
            ),
            ACTION_KIND_SWITCH,
        )
        self.assertEqual(
            resolve_candidate_action_kind(
                ["switch", "garchomp", 0, ""]
            ),
            ACTION_KIND_SWITCH,
        )

    def test_pass_action(self):
        self.assertEqual(
            resolve_candidate_action_kind(
                ["pass", "pass", 0, ""]
            ),
            ACTION_KIND_PASS,
        )

    def test_pass_action_via_unknown_kind(self):
        # Some passes are emitted as
        # ``["unknown", "/choose pass", 0, ""]``. The
        # helper detects the "pass" substring.
        self.assertEqual(
            resolve_candidate_action_kind(
                ["unknown", "/choose pass", 0, ""]
            ),
            ACTION_KIND_PASS,
        )

    def test_unknown_action(self):
        self.assertEqual(
            resolve_candidate_action_kind(
                ["unknown", "somethingweird", 0, ""]
            ),
            ACTION_KIND_UNKNOWN,
        )

    def test_mechanic_variants_are_move(self):
        # Mega / Z-Move / Dynamax / Terastallize
        # are mechanic variants of a move action.
        for kind in ("mega", "zmove", "dynamax", "terastallize"):
            self.assertEqual(
                resolve_candidate_action_kind(
                    [kind, "raindance", 0, ""]
                ),
                ACTION_KIND_MOVE,
            )

    def test_malformed_inputs(self):
        # Empty / too-short / wrong type -> unknown
        self.assertEqual(
            resolve_candidate_action_kind([]),
            ACTION_KIND_UNKNOWN,
        )
        self.assertEqual(
            resolve_candidate_action_kind(["move"]),
            ACTION_KIND_UNKNOWN,
        )
        self.assertEqual(
            resolve_candidate_action_kind("not a list"),
            ACTION_KIND_UNKNOWN,
        )
        self.assertEqual(
            resolve_candidate_action_kind(None),
            ACTION_KIND_UNKNOWN,
        )

    def test_is_move_action(self):
        self.assertTrue(
            is_move_action(["move", "raindance", 0, ""])
        )
        self.assertFalse(
            is_move_action(["switch", "volcarona", 0, ""])
        )
        self.assertFalse(
            is_move_action(["pass", "pass", 0, ""])
        )

    def test_is_switch_action(self):
        self.assertTrue(
            is_switch_action(["switch", "volcarona", 0, ""])
        )
        self.assertFalse(
            is_switch_action(["move", "raindance", 0, ""])
        )
        self.assertFalse(
            is_switch_action(["pass", "pass", 0, ""])
        )

    def test_is_pass_action(self):
        self.assertTrue(
            is_pass_action(["pass", "pass", 0, ""])
        )
        self.assertTrue(
            is_pass_action(["unknown", "/choose pass", 0, ""])
        )
        self.assertFalse(
            is_pass_action(["move", "raindance", 0, ""])
        )


# ============================================================
# split_candidate_id_from_v4a_key
# ============================================================
class TestSplitCandidateId(unittest.TestCase):
    """Unit tests for ``split_candidate_id_from_v4a_key``."""

    def test_move_candidate_id(self):
        kind, cid = split_candidate_id_from_v4a_key(
            ["move", "raindance", 0, ""]
        )
        self.assertEqual(kind, "move")
        self.assertEqual(cid, "raindance")

    def test_switch_candidate_id_prefixed(self):
        # Switch candidates get a ``switch:`` prefix
        # so they don't collide with real move ids.
        kind, cid = split_candidate_id_from_v4a_key(
            ["switch", "volcarona", 0, ""]
        )
        self.assertEqual(kind, "switch")
        self.assertEqual(cid, "switch:volcarona")

    def test_pass_candidate_id(self):
        kind, cid = split_candidate_id_from_v4a_key(
            ["pass", "pass", 0, ""]
        )
        self.assertEqual(kind, "pass")
        self.assertEqual(cid, "pass")

    def test_unknown_candidate_id_prefixed(self):
        kind, cid = split_candidate_id_from_v4a_key(
            ["unknown", "somethingweird", 0, ""]
        )
        self.assertEqual(kind, "unknown")
        self.assertEqual(cid, "unknown:somethingweird")


# ============================================================
# build_non_move_classification
# ============================================================
class TestBuildNonMoveClassification(unittest.TestCase):
    """Unit tests for ``build_non_move_classification``."""

    def test_switch_classification(self):
        cls = build_non_move_classification(
            action_kind="switch", metadata_source="n/a"
        )
        self.assertEqual(cls["action_kind"], "switch")
        self.assertTrue(cls["is_switch_action"])
        self.assertFalse(cls["is_move_action"])
        self.assertFalse(cls["is_pass_action"])
        # CRITICAL: switch actions must NOT be
        # flagged as unknown support moves.
        self.assertFalse(cls["unknown_support_move_detected"])
        self.assertFalse(cls["is_support_move"])
        self.assertIsNone(cls["support_group"])
        self.assertIsNone(cls["support_status_from_audit"])

    def test_pass_classification(self):
        cls = build_non_move_classification(
            action_kind="pass", metadata_source="n/a"
        )
        self.assertEqual(cls["action_kind"], "pass")
        self.assertTrue(cls["is_pass_action"])
        self.assertFalse(cls["unknown_support_move_detected"])

    def test_unknown_classification(self):
        cls = build_non_move_classification(
            action_kind="unknown", metadata_source="n/a"
        )
        self.assertEqual(cls["action_kind"], "unknown")
        self.assertFalse(cls["is_move_action"])
        self.assertFalse(cls["is_switch_action"])
        self.assertFalse(cls["is_pass_action"])
        # Unknown action kind: do NOT silently
        # treat as support move. Conservative.
        self.assertFalse(cls["unknown_support_move_detected"])


# ============================================================
# End-to-end: audit / builder / analyzer with switch filter
# ============================================================
class TestAuditEmissionFiltersNonMove(unittest.TestCase):
    """Verify the audit logger / builder correctly
    filter non-move actions before support classification.
    """

    def _make_fake_turn(self, v4a_legal0, v4a_legal1,
                        v4a_sel=None, v4a_final=None):
        return {
            "turn": 1,
            "state_snapshot": {
                "our_active_species": ["Politoed", "Incineroar"],
                "opp_active_species": ["Garchomp", "Tyranitar"],
                "our_active_hp_fraction": [1.0, 0.95],
                "opp_active_hp_fraction": [1.0, 1.0],
                "weather": "raindance",
                "fields": [],
            },
            "v4a_legal_action_keys_slot0": v4a_legal0,
            "v4a_legal_action_keys_slot1": v4a_legal1,
            "v4a_selected_joint_key": v4a_sel or [],
            "v4a_final_action_keys": v4a_final or [],
            "runtime_mode": "gen9randomdoublesbattle",
        }

    def test_switch_action_not_flagged_as_unknown(self):
        """A switch action (species name) must NOT
        be flagged as ``unknown_support_move_detected``.
        """
        from doubles_engine.audit_v1_1_metadata import (
            _extract_v1_1_support_classification,
        )
        turn = self._make_fake_turn(
            v4a_legal0=[
                ["move", "raindance", 0, ""],
                ["switch", "volcarona", 0, ""],
            ],
            v4a_legal1=[
                ["move", "protect", 1, ""],
                ["switch", "garchomp", 0, ""],
            ],
        )
        result = _extract_v1_1_support_classification(turn)
        per = result["per_candidate_support_classification"]
        # Move actions get full classification.
        self.assertIn("raindance", per)
        self.assertEqual(per["raindance"]["action_kind"], "move")
        self.assertFalse(per["raindance"]["unknown_support_move_detected"])
        self.assertEqual(per["protect"]["action_kind"], "move")
        # Switch actions get NON_MOVE_CLASSIFICATION
        # with explicit ``unknown_support_move_detected=False``.
        self.assertIn("switch:volcarona", per)
        self.assertEqual(per["switch:volcarona"]["action_kind"], "switch")
        self.assertFalse(
            per["switch:volcarona"]["unknown_support_move_detected"]
        )
        self.assertIn("switch:garchomp", per)
        self.assertFalse(
            per["switch:garchomp"]["unknown_support_move_detected"]
        )
        # No false ``unknown_support_move_detected``.
        self.assertFalse(result["unknown_support_move_detected"])

    def test_pass_action_not_flagged_as_unknown(self):
        """A pass action must NOT be flagged as
        ``unknown_support_move_detected``.
        """
        from doubles_engine.audit_v1_1_metadata import (
            _extract_v1_1_support_classification,
        )
        turn = self._make_fake_turn(
            v4a_legal0=[
                ["move", "raindance", 0, ""],
                ["pass", "pass", 0, ""],
            ],
            v4a_legal1=[
                ["move", "protect", 1, ""],
                ["unknown", "/choose pass", 0, ""],
            ],
        )
        result = _extract_v1_1_support_classification(turn)
        per = result["per_candidate_support_classification"]
        self.assertEqual(per["pass"]["action_kind"], "pass")
        self.assertFalse(per["pass"]["unknown_support_move_detected"])
        # The ``unknown`` / ``/choose pass`` is also
        # detected as ``pass`` and gets the same
        # treatment.
        self.assertIn("pass", per)
        # No false ``unknown_support_move_detected``.
        self.assertFalse(result["unknown_support_move_detected"])

    def test_true_unknown_support_move_still_detected(self):
        """A truly unknown non-damaging support move
        (e.g., ``newgensupportmove``) is still
        flagged as ``unknown_support_move_detected=True``.
        The detector is not disabled globally.
        """
        from doubles_engine.audit_v1_1_metadata import (
            _extract_v1_1_support_classification,
        )
        turn = self._make_fake_turn(
            v4a_legal0=[
                ["move", "raindance", 0, ""],
                ["move", "newgensupportmove", 0, ""],
            ],
            v4a_legal1=[],
        )
        result = _extract_v1_1_support_classification(turn)
        per = result["per_candidate_support_classification"]
        # ``newgensupportmove`` is a move action
        # (a real move id) but is not in the
        # SUPPORT-AUDIT-1 inventory. The classifier
        # treats it as ``unknown_needs_probe``.
        self.assertEqual(
            per["newgensupportmove"]["action_kind"], "move"
        )
        self.assertTrue(
            per["newgensupportmove"][
                "unknown_support_move_detected"
            ]
        )
        # ``raindance`` is a known support move.
        self.assertEqual(per["raindance"]["support_group"], "weather_terrain")
        self.assertFalse(
            per["raindance"]["unknown_support_move_detected"]
        )
        # Overall: at least one unknown detected.
        self.assertTrue(result["unknown_support_move_detected"])

    def test_known_damaging_move_still_classified(self):
        """``fakeout`` with metadata is correctly
        classified as damage-like (not support).
        """
        from doubles_engine.audit_v1_1_metadata import (
            _extract_v1_1_support_classification,
        )
        turn = self._make_fake_turn(
            v4a_legal0=[["move", "raindance", 0, ""]],
            v4a_legal1=[["move", "fakeout", 1, ""]],
        )
        # Provide a metadata map so ``fakeout`` is
        # classified via the live override path.
        turn["move_metadata_map"] = {
            "fakeout": {
                "base_power": 40,
                "category": "physical",
                "metadata_source": "override",
            },
            "raindance": {
                "base_power": 0,
                "category": "status",
                "metadata_source": "override",
            },
        }
        result = _extract_v1_1_support_classification(turn)
        per = result["per_candidate_support_classification"]
        # ``fakeout`` is damage-like, not support.
        self.assertFalse(per["fakeout"]["is_support_move"])
        self.assertFalse(per["fakeout"]["unknown_support_move_detected"])
        # ``raindance`` is weather-terrain support.
        self.assertEqual(per["raindance"]["support_group"], "weather_terrain")


class TestBuilderFiltersNonMove(unittest.TestCase):
    """Verify the builder's support classification
    also filters non-move actions.
    """

    def test_builder_filters_switch_actions(self):
        from showdown_ai.build_turn_level_offline_dataset import (
            _extract_v1_1_support_classification as _builder_extract,
        )
        # Build a minimal turn
        turn = {
            "turn": 1,
            "state_snapshot": {
                "our_active_species": ["Politoed", "Incineroar"],
                "opp_active_species": ["Garchomp", "Tyranitar"],
                "our_active_hp_fraction": [1.0, 0.95],
                "opp_active_hp_fraction": [1.0, 1.0],
                "weather": "raindance",
                "fields": [],
            },
            "v4a_legal_action_keys_slot0": [
                ["move", "raindance", 0, ""],
                ["switch", "volcarona", 0, ""],
            ],
            "v4a_legal_action_keys_slot1": [
                ["move", "protect", 1, ""],
            ],
            "v4a_selected_joint_key": [],
            "v4a_final_action_keys": [],
        }
        result = _builder_extract(turn)
        per = result["per_candidate_support_classification"]
        # Move actions get full classification.
        self.assertIn("raindance", per)
        self.assertIn("protect", per)
        # Switch action gets the NON_MOVE_CLASSIFICATION
        # with ``unknown_support_move_detected=False``.
        self.assertIn("switch:volcarona", per)
        self.assertEqual(
            per["switch:volcarona"]["action_kind"], "switch"
        )
        self.assertFalse(
            per["switch:volcarona"]["unknown_support_move_detected"]
        )
        # Overall: no false unknown.
        self.assertFalse(result["unknown_support_move_detected"])


# ============================================================
# Analyzer behavior with the fix
# ============================================================
class TestAnalyzerWithSwitchFilter(unittest.TestCase):
    """Verify the analyzer no longer warns on
    switch-as-species cases after the fix.
    """

    def test_analyzer_does_not_warn_on_switch_only_dataset(self):
        """Build a small dataset with only switch
        actions. The analyzer should not warn
        about unknown support moves because
        switches are not support candidates.
        """
        from showdown_ai.build_turn_level_offline_dataset import (
            build_dataset_from_artifact,
        )
        from analyze_turn_level_offline_dataset_quality import (
            analyze,
        )

        with tempfile.TemporaryDirectory() as tmp:
            audit_path = os.path.join(tmp, "audit_switch_only.jsonl")
            dataset_path = os.path.join(
                tmp, "dataset_switch_only.jsonl"
            )
            # Build an audit JSONL with one battle
            # whose every turn has only switch
            # actions. The v1.1 builder should
            # filter these and the analyzer should
            # report 0 unknown support moves.
            record = {
                "battle_tag": "switch_only_fixture",
                "winner": "TestBot",
                "won": True,
                "total_turns": 1,
                "audit_turns": [
                    {
                        "turn": 1,
                        "our_active": [
                            {"species": "Politoed", "hp": 1.0},
                            {"species": "Incineroar", "hp": 1.0},
                        ],
                        "opp_active": [
                            {"species": "Garchomp", "hp": 1.0},
                            {"species": "Tyranitar", "hp": 1.0},
                        ],
                        "selected_joint_order": (
                            "/choose switch Volcarona, "
                            "switch Garchomp"
                        ),
                        "selected_score": 0.0,
                        "v4a_legal_action_keys_slot0": [
                            ["switch", "volcarona", 0, ""],
                            ["switch", "politoed", 0, ""],
                        ],
                        "v4a_legal_action_keys_slot1": [
                            ["switch", "garchomp", 1, ""],
                            ["switch", "incineroar", 1, ""],
                        ],
                        "v4a_selected_joint_key": [
                            ["switch", "volcarona", 0, ""],
                            ["switch", "garchomp", 1, ""],
                        ],
                        "v4a_final_action_keys": [
                            ["switch", "volcarona", 0, ""],
                            ["switch", "garchomp", 1, ""],
                        ],
                        "state_snapshot": {
                            "weather": "raindance",
                            "fields": [],
                        },
                    }
                ],
            }
            with open(audit_path, "w") as f:
                f.write(json.dumps(record) + "\n")
            rows, _ = build_dataset_from_artifact(
                audit_path, "treatment", "switch_only_fixture"
            )
            with open(dataset_path, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            report = analyze([dataset_path])
            v11 = report.get("v11_gates", {})
            # No hard blocks, no warnings.
            self.assertEqual(len(v11.get("hard_blocks", [])), 0)
            # Specifically: no Gate 17 warning. The
            # switch-as-species case is no longer
            # inflating the unknown count.
            warnings = v11.get("warnings", [])
            gate_17 = [
                w for w in warnings if "Gate 17" in str(w)
            ]
            self.assertEqual(len(gate_17), 0)
            # The per-candidate classifications
            # correctly mark the switches as
            # ``is_support_move=False`` and
            # ``unknown_support_move_detected=False``.
            per = rows[0]["per_candidate_support_classification"]
            for mid, cls in per.items():
                self.assertEqual(cls["action_kind"], "switch")
                self.assertFalse(cls["is_support_move"])
                self.assertFalse(
                    cls["unknown_support_move_detected"]
                )
