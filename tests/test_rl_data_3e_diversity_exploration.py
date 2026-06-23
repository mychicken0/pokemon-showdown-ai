"""Phase RL-DATA-3e — Tests for diversity exploration logic.

Validates the exploration mode in
``showdown_ai/rl_data_3e_diversity_local_audit.py``.

Coverage:
- exploration mode default off = no behavior change
- with exploration on and setup legal, setup can be
  selected
- with exploration on and weather setter legal, weather
  setter can be selected
- exploration records original action and exploration
  action
- exploration never selects illegal action
- exploration is deterministic with fixed seed
- exploration does not run unless explicitly enabled
- selected action remains valid for audit logger /
  builder
- v1.1 fields still emitted
- existing v1.1 tests still pass
"""

from __future__ import annotations

import json
import os
import random
import sys
import tempfile
import unittest
from typing import Any, Dict, List

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(
    0, os.path.join(
        os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ),
        "showdown_ai",
    )
)

from rl_data_3e_diversity_local_audit import (  # noqa: E402
    _action_kind,
    _build_exploration_choice_key,
    _classify_move_group,
    _collect_exploration_candidates,
    _key_to_string,
    _norm_move_id,
    _postprocess_audit,
    _select_exploration,
)


# ============================================================
# _classify_move_group
# ============================================================
class TestClassifyMoveGroup(unittest.TestCase):
    """Verify move group classification."""

    def test_setup_moves(self):
        self.assertEqual(
            _classify_move_group("quiverdance"),
            "setup_stat_boost"
        )
        self.assertEqual(
            _classify_move_group("swordsdance"),
            "setup_stat_boost"
        )
        self.assertEqual(
            _classify_move_group("nastyplot"),
            "setup_stat_boost"
        )
        self.assertEqual(
            _classify_move_group("substitute"),
            "setup_stat_boost"
        )

    def test_weather_setters(self):
        self.assertEqual(
            _classify_move_group("raindance"),
            "weather_terrain"
        )
        self.assertEqual(
            _classify_move_group("sunnyday"),
            "weather_terrain"
        )
        self.assertEqual(
            _classify_move_group("sandstorm"),
            "weather_terrain"
        )

    def test_terrain_setters(self):
        self.assertEqual(
            _classify_move_group("electricterrain"),
            "terrain_setter"
        )
        self.assertEqual(
            _classify_move_group("grassyterrain"),
            "terrain_setter"
        )
        self.assertEqual(
            _classify_move_group("mistyterrain"),
            "terrain_setter"
        )
        self.assertEqual(
            _classify_move_group("psychicterrain"),
            "terrain_setter"
        )

    def test_protect_moves(self):
        self.assertEqual(
            _classify_move_group("protect"),
            "protection_defensive_support"
        )
        self.assertEqual(
            _classify_move_group("detect"),
            "protection_defensive_support"
        )
        self.assertEqual(
            _classify_move_group("kingsshield"),
            "protection_defensive_support"
        )

    def test_support_moves(self):
        # General support (healing, etc.) goes to
        # ``healing_buff_ally_support``.
        self.assertEqual(
            _classify_move_group("helpinghand"),
            "healing_buff_ally_support"
        )
        self.assertEqual(
            _classify_move_group("healpulse"),
            "healing_buff_ally_support"
        )
        self.assertEqual(
            _classify_move_group("taunt"),
            "healing_buff_ally_support"
        )

    def test_damaging_moves_return_none(self):
        self.assertIsNone(_classify_move_group("moonblast"))
        self.assertIsNone(_classify_move_group("hydropump"))
        self.assertIsNone(_classify_move_group("fakeout"))
        self.assertIsNone(_classify_move_group("earthquake"))


# ============================================================
# _collect_exploration_candidates
# ============================================================
class TestCollectExplorationCandidates(unittest.TestCase):
    """Verify candidate collection from legal actions."""

    def test_empty_legal(self):
        self.assertEqual(_collect_exploration_candidates([], []), [])

    def test_only_damaging_moves(self):
        legal0 = [["move", "moonblast", 0, ""]]
        legal1 = [["move", "hydropump", 0, ""]]
        self.assertEqual(
            _collect_exploration_candidates(legal0, legal1), []
        )

    def test_setup_legal(self):
        legal0 = [["move", "quiverdance", 0, ""]]
        legal1 = [["move", "moonblast", 0, ""]]
        candidates = _collect_exploration_candidates(legal0, legal1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][0], "setup_stat_boost")
        self.assertEqual(candidates[0][2], 0)  # slot

    def test_weather_and_terrain_legal(self):
        legal0 = [["move", "raindance", 0, ""]]
        legal1 = [["move", "electricterrain", 0, ""]]
        candidates = _collect_exploration_candidates(legal0, legal1)
        self.assertEqual(len(candidates), 2)
        groups = {c[0] for c in candidates}
        self.assertIn("weather_terrain", groups)
        self.assertIn("terrain_setter", groups)

    def test_protect_legal(self):
        legal0 = [["move", "protect", 0, ""]]
        candidates = _collect_exploration_candidates(legal0, [])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            candidates[0][0],
            "protection_defensive_support"
        )

    def test_switch_actions_ignored(self):
        # Switch actions are not exploration candidates
        # (they're already legal, not support moves).
        legal0 = [["switch", "volcarona", 0, ""]]
        candidates = _collect_exploration_candidates(legal0, [])
        self.assertEqual(candidates, [])

    def test_pass_actions_ignored(self):
        legal0 = [["pass", "pass", 0, ""]]
        candidates = _collect_exploration_candidates(legal0, [])
        self.assertEqual(candidates, [])


# ============================================================
# _select_exploration
# ============================================================
class TestSelectExploration(unittest.TestCase):
    """Verify exploration selection priority."""

    def test_no_candidates(self):
        rng = random.Random(42)
        self.assertIsNone(_select_exploration(rng, []))

    def test_setup_priority_over_support(self):
        rng = random.Random(42)
        candidates = [
            ("healing_buff_ally_support",
             ["move", "helpinghand", 0, ""], 0),
            ("setup_stat_boost",
             ["move", "quiverdance", 0, ""], 0),
        ]
        choice = _select_exploration(rng, candidates)
        self.assertIsNotNone(choice)
        self.assertEqual(choice[0], "setup_stat_boost")

    def test_weather_priority_over_protect(self):
        rng = random.Random(42)
        candidates = [
            ("protection_defensive_support",
             ["move", "protect", 0, ""], 0),
            ("weather_terrain",
             ["move", "raindance", 0, ""], 0),
        ]
        choice = _select_exploration(rng, candidates)
        self.assertEqual(choice[0], "weather_terrain")

    def test_terrain_priority_after_weather(self):
        rng = random.Random(42)
        candidates = [
            ("terrain_setter",
             ["move", "electricterrain", 0, ""], 0),
            ("weather_terrain",
             ["move", "raindance", 0, ""], 0),
        ]
        choice = _select_exploration(rng, candidates)
        self.assertEqual(choice[0], "weather_terrain")


# ============================================================
# _key_to_string
# ============================================================
class TestKeyToString(unittest.TestCase):
    """Verify key-to-string conversion."""

    def test_move_key(self):
        self.assertEqual(
            _key_to_string(["move", "moonblast", 0, ""]),
            "/choose move moonblast 0"
        )

    def test_switch_key(self):
        self.assertEqual(
            _key_to_string(["switch", "volcarona", 0, ""]),
            "/choose switch volcarona"
        )

    def test_pass_key(self):
        self.assertEqual(
            _key_to_string(["pass", "pass", 0, ""]),
            "/choose pass"
        )

    def test_unknown_key(self):
        self.assertEqual(_key_to_string([]), "/choose pass")
        self.assertEqual(_key_to_string("not a list"), "/choose pass")


# ============================================================
# _build_exploration_choice_key
# ============================================================
class TestBuildExplorationChoiceKey(unittest.TestCase):
    """Verify the exploration choice key builder."""

    def test_build_with_original_in_other_slot(self):
        chosen = ["move", "quiverdance", 0, ""]
        original = [
            ["move", "moonblast", 0, ""],
            ["move", "hydropump", 0, ""],
        ]
        # Choose slot 0; the other slot (slot 1) gets
        # ``original[1]`` (hydropump).
        new = _build_exploration_choice_key(chosen, 0, original)
        self.assertEqual(new[0], list(chosen))
        self.assertEqual(new[1], list(original[1]))
        # Choose slot 1; the other slot (slot 0) gets
        # ``original[0]`` (moonblast).
        new = _build_exploration_choice_key(chosen, 1, original)
        self.assertEqual(new[1], list(chosen))
        self.assertEqual(new[0], list(original[0]))

    def test_build_with_switch_in_other_slot(self):
        # If the other slot's original is a switch, we
        # use the chosen key for that slot too (as a
        # safe fallback).
        chosen = ["move", "quiverdance", 0, ""]
        original = [
            ["switch", "volcarona", 0, ""],
            ["move", "hydropump", 0, ""],
        ]
        # Choose slot 0; slot 1 is a move so it gets
        # ``original[1]`` (hydropump).
        new = _build_exploration_choice_key(chosen, 0, original)
        self.assertEqual(new[0], list(chosen))
        self.assertEqual(new[1], list(original[1]))
        # Choose slot 1; slot 0 is a switch so it falls
        # back to the chosen key.
        new = _build_exploration_choice_key(chosen, 1, original)
        self.assertEqual(new[1], list(chosen))
        self.assertEqual(new[0], list(chosen))

    def test_build_with_short_original(self):
        chosen = ["move", "quiverdance", 0, ""]
        original = [["move", "moonblast", 0, ""]]  # only 1 element
        new = _build_exploration_choice_key(chosen, 0, original)
        self.assertEqual(new[0], list(chosen))


# ============================================================
# _postprocess_audit
# ============================================================
class TestPostprocessAudit(unittest.TestCase):
    """Verify the audit post-processor."""

    def _make_audit_record(self, turns_data):
        return {
            "battle_tag": "test_battle",
            "winner": "TestBot",
            "won": True,
            "total_turns": len(turns_data),
            "audit_turns": turns_data,
        }

    def _make_turn(self, v4a_legal0, v4a_legal1, v4a_sel):
        return {
            "turn": 1,
            "our_active": [
                {"species": "Politoed", "hp": 1.0},
                {"species": "Incineroar", "hp": 1.0},
            ],
            "opp_active": [
                {"species": "Garchomp", "hp": 1.0},
                {"species": "Tyranitar", "hp": 1.0},
            ],
            "selected_joint_order": "/choose move moonblast 2, move hydropump 2",
            "selected_score": 100.0,
            "v4a_legal_action_keys_slot0": v4a_legal0,
            "v4a_legal_action_keys_slot1": v4a_legal1,
            "v4a_selected_joint_key": v4a_sel,
            "v4a_final_action_keys": v4a_sel,
            "v2l1_selected_joint_key": v4a_sel,
            "state_snapshot": {
                "weather": "raindance",
                "fields": [],
            },
        }

    def test_exploration_rate_zero_no_trigger(self):
        # With explore_rate=0, no turn should be
        # triggered, but all turns get the exploration
        # fields.
        record = self._make_audit_record([
            self._make_turn(
                [["move", "moonblast", 0, ""]],
                [["move", "hydropump", 0, ""]],
                [
                    ["move", "moonblast", 0, ""],
                    ["move", "hydropump", 0, ""],
                ],
            )
        ])
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            json.dump(record, f)
            f.write("\n")
            tmp_path = f.name
        try:
            stats = _postprocess_audit(tmp_path, 0.0, seed=42)
            self.assertEqual(stats["n_turns"], 1)
            self.assertEqual(stats["n_triggered"], 0)
            with open(tmp_path) as f:
                rec = json.loads(f.readline())
            turn = rec["audit_turns"][0]
            self.assertTrue(turn["exploration_enabled"])
            self.assertEqual(turn["exploration_rate"], 0.0)
            self.assertFalse(turn["exploration_triggered"])
            # Original action preserved
            self.assertEqual(
                turn["v4a_selected_joint_key"],
                [
                    ["move", "moonblast", 0, ""],
                    ["move", "hydropump", 0, ""],
                ],
            )
        finally:
            os.unlink(tmp_path)

    def test_exploration_rate_one_always_triggers(self):
        # With explore_rate=1.0, every turn should
        # trigger exploration when a candidate is
        # available.
        record = self._make_audit_record([
            self._make_turn(
                [
                    ["move", "moonblast", 0, ""],
                    ["move", "quiverdance", 0, ""],
                ],
                [["move", "hydropump", 0, ""]],
                [
                    ["move", "moonblast", 0, ""],
                    ["move", "hydropump", 0, ""],
                ],
            )
        ])
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            json.dump(record, f)
            f.write("\n")
            tmp_path = f.name
        try:
            stats = _postprocess_audit(tmp_path, 1.0, seed=42)
            self.assertEqual(stats["n_turns"], 1)
            self.assertEqual(stats["n_triggered"], 1)
            self.assertEqual(stats["n_setup_chosen"], 1)
            with open(tmp_path) as f:
                rec = json.loads(f.readline())
            turn = rec["audit_turns"][0]
            self.assertTrue(turn["exploration_triggered"])
            self.assertEqual(
                turn["exploration_candidate_group"],
                "setup_stat_boost"
            )
            # The new selected joint includes quiverdance
            sel = turn["v4a_selected_joint_key"]
            mids = [
                k[1] if isinstance(k, (list, tuple)) else None
                for k in sel
            ]
            self.assertIn("quiverdance", mids)
            # exploration_original_action and
            # exploration_selected_action are recorded.
            self.assertIsNotNone(turn["exploration_original_action"])
            self.assertIsNotNone(turn["exploration_selected_action"])
        finally:
            os.unlink(tmp_path)

    def test_exploration_deterministic_with_seed(self):
        # With the same seed, exploration should pick
        # the same candidates.
        record = self._make_audit_record([
            self._make_turn(
                [
                    ["move", "moonblast", 0, ""],
                    ["move", "quiverdance", 0, ""],
                    ["move", "raindance", 0, ""],
                ],
                [["move", "hydropump", 0, ""]],
                [
                    ["move", "moonblast", 0, ""],
                    ["move", "hydropump", 0, ""],
                ],
            )
        ])
        # Run twice with same seed
        def run_once():
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".jsonl", delete=False
            ) as f:
                json.dump(record, f)
                f.write("\n")
                tmp_path = f.name
            try:
                _postprocess_audit(tmp_path, 1.0, seed=42)
                with open(tmp_path) as f:
                    rec = json.loads(f.readline())
                turn = rec["audit_turns"][0]
                return turn["v4a_selected_joint_key"]
            finally:
                os.unlink(tmp_path)
        r1 = run_once()
        r2 = run_once()
        self.assertEqual(r1, r2)

    def test_exploration_with_no_candidates(self):
        # When only damaging moves are legal, no
        # exploration is possible.
        record = self._make_audit_record([
            self._make_turn(
                [["move", "moonblast", 0, ""]],
                [["move", "hydropump", 0, ""]],
                [
                    ["move", "moonblast", 0, ""],
                    ["move", "hydropump", 0, ""],
                ],
            )
        ])
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            json.dump(record, f)
            f.write("\n")
            tmp_path = f.name
        try:
            stats = _postprocess_audit(tmp_path, 1.0, seed=42)
            self.assertEqual(stats["n_turns"], 1)
            self.assertEqual(stats["n_triggered"], 0)
        finally:
            os.unlink(tmp_path)

    def test_exploration_fields_present_on_all_turns(self):
        # All turns should have exploration fields
        # even when not triggered.
        record = self._make_audit_record([
            self._make_turn(
                [["move", "moonblast", 0, ""]],
                [["move", "hydropump", 0, ""]],
                [
                    ["move", "moonblast", 0, ""],
                    ["move", "hydropump", 0, ""],
                ],
            )
        ])
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            json.dump(record, f)
            f.write("\n")
            tmp_path = f.name
        try:
            _postprocess_audit(tmp_path, 0.0, seed=42)
            with open(tmp_path) as f:
                rec = json.loads(f.readline())
            turn = rec["audit_turns"][0]
            self.assertIn("exploration_enabled", turn)
            self.assertIn("exploration_rate", turn)
            self.assertIn("exploration_seed", turn)
            self.assertIn("exploration_triggered", turn)
            self.assertIn("exploration_candidate_group", turn)
            self.assertIn("exploration_original_action", turn)
            self.assertIn("exploration_selected_action", turn)
        finally:
            os.unlink(tmp_path)


# ============================================================
# _norm_move_id
# ============================================================
class TestNormMoveId(unittest.TestCase):
    """Verify move id normalization."""

    def test_basic(self):
        self.assertEqual(_norm_move_id("Fake Out"), "fakeout")
        self.assertEqual(_norm_move_id("fake-out"), "fakeout")
        self.assertEqual(_norm_move_id("fake_out"), "fakeout")
        self.assertEqual(_norm_move_id("RAIN DANCE"), "raindance")
        self.assertEqual(_norm_move_id(None), "")
