#!/usr/bin/env python3
"""Tests for the extracted doubles_engine.audit_metadata
module.

ponytail: focused unit tests for the V2l.1
action-key → string converters.

Behavior-preservation evidence: the production
audit-dict assembly code in
``bot_doubles_damage_aware.py`` calls these
helpers via the classmethod/staticmethod shims,
and ``test_vgc2026_runtime_engine_parity`` exercises
the same audit assembly through the real
``choose_move`` path. The shim delegation is verified
by classmethod/staticmethod tests below.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# v2l1_action_key_to_str
# ---------------------------------------------------------------------------


class TestV2l1ActionKeyToStr(unittest.TestCase):
    def test_tuple_of_3(self):
        from doubles_engine.audit_metadata import v2l1_action_key_to_str
        self.assertEqual(
            v2l1_action_key_to_str(("move", "tackle", 0)),
            "move|tackle|0",
        )

    def test_tuple_of_4_v4a(self):
        from doubles_engine.audit_metadata import v2l1_action_key_to_str
        self.assertEqual(
            v2l1_action_key_to_str(("move", "tackle", 0, "STAB")),
            "move|tackle|0|STAB",
        )

    def test_empty_tuple(self):
        from doubles_engine.audit_metadata import v2l1_action_key_to_str
        # Empty tuple is falsy; str() is returned.
        self.assertEqual(v2l1_action_key_to_str(()), "()")

    def test_none(self):
        from doubles_engine.audit_metadata import v2l1_action_key_to_str
        # None is not a tuple; str() is returned.
        self.assertEqual(v2l1_action_key_to_str(None), "None")

    def test_non_tuple(self):
        from doubles_engine.audit_metadata import v2l1_action_key_to_str
        # Non-tuple returns str(value).
        self.assertEqual(v2l1_action_key_to_str(42), "42")


# ---------------------------------------------------------------------------
# v2l1_action_key_to_str_map
# ---------------------------------------------------------------------------


class TestV2l1ActionKeyToStrMap(unittest.TestCase):
    def test_empty(self):
        from doubles_engine.audit_metadata import v2l1_action_key_to_str_map
        self.assertEqual(v2l1_action_key_to_str_map({}), {})

    def test_none(self):
        from doubles_engine.audit_metadata import v2l1_action_key_to_str_map
        self.assertEqual(v2l1_action_key_to_str_map(None), {})

    def test_single(self):
        from doubles_engine.audit_metadata import v2l1_action_key_to_str_map
        result = v2l1_action_key_to_str_map(
            {("move", "tackle", 0): 1.0}
        )
        self.assertEqual(result, {"move|tackle|0": 1.0})

    def test_multiple(self):
        from doubles_engine.audit_metadata import v2l1_action_key_to_str_map
        result = v2l1_action_key_to_str_map({
            ("move", "tackle", 0): 1.0,
            ("move", "ember", 1): 2.0,
            ("switch", "pikachu", -1): 0.5,
        })
        self.assertEqual(
            result,
            {
                "move|tackle|0": 1.0,
                "move|ember|1": 2.0,
                "switch|pikachu|-1": 0.5,
            },
        )


# ---------------------------------------------------------------------------
# v2l1_joint_key_to_str
# ---------------------------------------------------------------------------


class TestV2l1JointKeyToStr(unittest.TestCase):
    def test_none(self):
        from doubles_engine.audit_metadata import v2l1_joint_key_to_str
        self.assertIsNone(v2l1_joint_key_to_str(None))

    def test_empty_tuple(self):
        from doubles_engine.audit_metadata import v2l1_joint_key_to_str
        # Empty tuple is falsy; returns None.
        self.assertIsNone(v2l1_joint_key_to_str(()))

    def test_two_tuple(self):
        from doubles_engine.audit_metadata import v2l1_joint_key_to_str
        self.assertEqual(
            v2l1_joint_key_to_str(
                (("move", "tackle", 0), ("switch", "pikachu", -1))
            ),
            "move|tackle|0;switch|pikachu|-1",
        )

    def test_three_tuple(self):
        from doubles_engine.audit_metadata import v2l1_joint_key_to_str
        # 3-tuple is not a 2-tuple; str() is returned.
        self.assertEqual(
            v2l1_joint_key_to_str((1, 2, 3)),
            "(1, 2, 3)",
        )

    def test_non_tuple(self):
        from doubles_engine.audit_metadata import v2l1_joint_key_to_str
        # Non-tuple returns str(value).
        self.assertEqual(v2l1_joint_key_to_str("foo"), "foo")


# ---------------------------------------------------------------------------
# Shim verification: the class methods on DoublesDamageAwarePlayer
# still work and delegate to the module-level functions.
# ---------------------------------------------------------------------------


class TestClassShim(unittest.TestCase):
    def test_staticmethod(self):
        from doubles_engine.audit_metadata import (
            v2l1_action_key_to_str as eng,
        )
        import bot_doubles_damage_aware as b
        # Call the static method via the class.
        result = b.DoublesDamageAwarePlayer._v2l1_action_key_to_str(
            ("move", "tackle", 0)
        )
        self.assertEqual(result, eng(("move", "tackle", 0)))

    def test_classmethod_str_map(self):
        from doubles_engine.audit_metadata import (
            v2l1_action_key_to_str_map as eng,
        )
        import bot_doubles_damage_aware as b
        result = (
            b.DoublesDamageAwarePlayer._v2l1_action_key_to_str_map(
                {("move", "tackle", 0): 1.0}
            )
        )
        self.assertEqual(result, eng({("move", "tackle", 0): 1.0}))

    def test_classmethod_joint_key(self):
        from doubles_engine.audit_metadata import (
            v2l1_joint_key_to_str as eng,
        )
        import bot_doubles_damage_aware as b
        result = b.DoublesDamageAwarePlayer._v2l1_joint_key_to_str(
            (("move", "tackle", 0), ("switch", "pikachu", -1))
        )
        self.assertEqual(
            result,
            eng(
                (("move", "tackle", 0), ("switch", "pikachu", -1))
            ),
        )


# ---------------------------------------------------------------------------
# assemble_v2l1_metadata
# ---------------------------------------------------------------------------


class TestAssembleV2l1Metadata(unittest.TestCase):
    def test_minimal_valid_shape(self):
        from doubles_engine.audit_metadata import (
            assemble_v2l1_metadata,
        )
        result = assemble_v2l1_metadata(
            v2l1_legal_keys_slot0=[],
            v2l1_legal_keys_slot1=[],
            v2l1_raw_scores_slot0={},
            v2l1_raw_scores_slot1={},
            v2l1_safety_blocks_slot0={},
            v2l1_safety_blocks_slot1={},
            v2l1_selected_joint_key=None,
            v2l1_final_keys=[],
        )
        # All 8 expected keys present, all empty.
        self.assertEqual(
            set(result.keys()),
            {
                "v2l1_legal_action_keys_slot0",
                "v2l1_legal_action_keys_slot1",
                "v2l1_raw_scores_slot0",
                "v2l1_raw_scores_slot1",
                "v2l1_safety_blocks_slot0",
                "v2l1_safety_blocks_slot1",
                "v2l1_selected_joint_key",
                "v2l1_final_action_keys",
            },
        )
        self.assertEqual(result["v2l1_legal_action_keys_slot0"], [])
        self.assertEqual(result["v2l1_legal_action_keys_slot1"], [])
        self.assertEqual(result["v2l1_raw_scores_slot0"], {})
        self.assertEqual(result["v2l1_raw_scores_slot1"], {})
        self.assertEqual(result["v2l1_safety_blocks_slot0"], {})
        self.assertEqual(result["v2l1_safety_blocks_slot1"], {})
        self.assertIsNone(result["v2l1_selected_joint_key"])
        self.assertEqual(result["v2l1_final_action_keys"], [])

    def test_none_inputs_default_to_empty(self):
        from doubles_engine.audit_metadata import (
            assemble_v2l1_metadata,
        )
        # All None inputs should default to safe empty values.
        result = assemble_v2l1_metadata(
            v2l1_legal_keys_slot0=None,
            v2l1_legal_keys_slot1=None,
            v2l1_raw_scores_slot0=None,
            v2l1_raw_scores_slot1=None,
            v2l1_safety_blocks_slot0=None,
            v2l1_safety_blocks_slot1=None,
            v2l1_selected_joint_key=None,
            v2l1_final_keys=None,
        )
        self.assertEqual(result["v2l1_legal_action_keys_slot0"], [])
        self.assertEqual(result["v2l1_legal_action_keys_slot1"], [])
        self.assertEqual(result["v2l1_raw_scores_slot0"], {})
        self.assertEqual(result["v2l1_raw_scores_slot1"], {})
        self.assertEqual(result["v2l1_safety_blocks_slot0"], {})
        self.assertEqual(result["v2l1_safety_blocks_slot1"], {})
        self.assertIsNone(result["v2l1_selected_joint_key"])
        self.assertEqual(result["v2l1_final_action_keys"], [])

    def test_tuple_action_key_stringified(self):
        from doubles_engine.audit_metadata import (
            assemble_v2l1_metadata,
        )
        result = assemble_v2l1_metadata(
            v2l1_legal_keys_slot0=[("move", "tackle", 0)],
            v2l1_legal_keys_slot1=[],
            v2l1_raw_scores_slot0={("move", "tackle", 0): 1.0},
            v2l1_raw_scores_slot1={},
            v2l1_safety_blocks_slot0={},
            v2l1_safety_blocks_slot1={},
            v2l1_selected_joint_key=None,
            v2l1_final_keys=[("move", "tackle", 0)],
        )
        # Action key tuple preserved as list in legal_keys.
        self.assertEqual(
            result["v2l1_legal_action_keys_slot0"],
            [("move", "tackle", 0)],
        )
        # Action key tuple in raw_scores is stringified.
        self.assertEqual(
            result["v2l1_raw_scores_slot0"],
            {"move|tackle|0": 1.0},
        )
        # Action key tuple in final_keys is stringified.
        self.assertEqual(
            result["v2l1_final_action_keys"],
            ["move|tackle|0"],
        )

    def test_v4a_4tuple_action_key(self):
        from doubles_engine.audit_metadata import (
            assemble_v2l1_metadata,
        )
        # V4a mechanic-aware 4-tuple action key.
        result = assemble_v2l1_metadata(
            v2l1_legal_keys_slot0=[],
            v2l1_legal_keys_slot1=[],
            v2l1_raw_scores_slot0={
                ("move", "tackle", 0, "STAB"): 2.5
            },
            v2l1_raw_scores_slot1={},
            v2l1_safety_blocks_slot0={},
            v2l1_safety_blocks_slot1={},
            v2l1_selected_joint_key=None,
            v2l1_final_keys=[("move", "tackle", 0, "STAB")],
        )
        self.assertEqual(
            result["v2l1_raw_scores_slot0"],
            {"move|tackle|0|STAB": 2.5},
        )
        self.assertEqual(
            result["v2l1_final_action_keys"],
            ["move|tackle|0|STAB"],
        )

    def test_selected_joint_key(self):
        from doubles_engine.audit_metadata import (
            assemble_v2l1_metadata,
        )
        # Joint key as a 2-tuple is converted to "a;b" string.
        result = assemble_v2l1_metadata(
            v2l1_legal_keys_slot0=[],
            v2l1_legal_keys_slot1=[],
            v2l1_raw_scores_slot0={},
            v2l1_raw_scores_slot1={},
            v2l1_safety_blocks_slot0={},
            v2l1_safety_blocks_slot1={},
            v2l1_selected_joint_key=(
                ("move", "tackle", 0),
                ("switch", "pikachu", -1),
            ),
            v2l1_final_keys=[],
        )
        self.assertEqual(
            result["v2l1_selected_joint_key"],
            "move|tackle|0;switch|pikachu|-1",
        )

    def test_safety_blocks_preserved(self):
        from doubles_engine.audit_metadata import (
            assemble_v2l1_metadata,
        )
        # Safety block dicts are also string-keyed.
        result = assemble_v2l1_metadata(
            v2l1_legal_keys_slot0=[],
            v2l1_legal_keys_slot1=[],
            v2l1_raw_scores_slot0={},
            v2l1_raw_scores_slot1={},
            v2l1_safety_blocks_slot0={
                ("move", "tackle", 0): True
            },
            v2l1_safety_blocks_slot1={},
            v2l1_selected_joint_key=None,
            v2l1_final_keys=[],
        )
        self.assertEqual(
            result["v2l1_safety_blocks_slot0"],
            {"move|tackle|0": True},
        )

    def test_legal_keys_passed_through_as_list(self):
        from doubles_engine.audit_metadata import (
            assemble_v2l1_metadata,
        )
        # Input is converted via list() to ensure a new
        # list is returned (defensive copy).
        original = [("move", "a", 0), ("move", "b", 1)]
        result = assemble_v2l1_metadata(
            v2l1_legal_keys_slot0=original,
            v2l1_legal_keys_slot1=[],
            v2l1_raw_scores_slot0={},
            v2l1_raw_scores_slot1={},
            v2l1_safety_blocks_slot0={},
            v2l1_safety_blocks_slot1={},
            v2l1_selected_joint_key=None,
            v2l1_final_keys=[],
        )
        # Output is a list (not the original).
        self.assertEqual(
            result["v2l1_legal_action_keys_slot0"],
            original,
        )
        self.assertIsNot(
            result["v2l1_legal_action_keys_slot0"],
            original,
        )


# ---------------------------------------------------------------------------
# assemble_partial_spread_state
# ---------------------------------------------------------------------------


class TestAssemblePartialSpreadState(unittest.TestCase):
    def test_empty_dicts_create_defaults(self):
        from doubles_engine.audit_metadata import (
            assemble_partial_spread_state,
        )
        # All empty dicts + new battle_tag → all defaults.
        result = assemble_partial_spread_state(
            "bt1",
            {}, {}, {}, {}, {}, {},
        )
        # 6 expected keys.
        self.assertEqual(
            set(result.keys()),
            {
                "partial_immune_spread_selected",
                "partial_ability_immune_spread_selected",
                "efficient_partial_spread_selected",
                "inefficient_partial_spread_selected",
                "immune_target_species",
                "damaged_target_species",
            },
        )
        # 4 boolean-by-slot values default to [False, False].
        self.assertEqual(
            result["partial_immune_spread_selected"],
            [False, False],
        )
        self.assertEqual(
            result["partial_ability_immune_spread_selected"],
            [False, False],
        )
        self.assertEqual(
            result["efficient_partial_spread_selected"],
            [False, False],
        )
        self.assertEqual(
            result["inefficient_partial_spread_selected"],
            [False, False],
        )
        # 2 species-by-slot values default to [[], []].
        self.assertEqual(
            result["immune_target_species"],
            [[], []],
        )
        self.assertEqual(
            result["damaged_target_species"],
            [[], []],
        )

    def test_pre_populated_values_preserved(self):
        from doubles_engine.audit_metadata import (
            assemble_partial_spread_state,
        )
        # All dicts have a 'bt1' key with pre-populated values.
        p0 = {"bt1": {0: True, 1: False}}
        p1 = {"bt1": {0: False, 1: True}}
        p2 = {"bt1": {0: True, 1: True}}
        p3 = {"bt1": {0: False, 1: False}}
        p4 = {"bt1": {0: ["a"], 1: []}}
        p5 = {"bt1": {0: [], 1: ["b"]}}
        result = assemble_partial_spread_state(
            "bt1", p0, p1, p2, p3, p4, p5,
        )
        self.assertEqual(
            result["partial_immune_spread_selected"],
            [True, False],
        )
        self.assertEqual(
            result["partial_ability_immune_spread_selected"],
            [False, True],
        )
        self.assertEqual(
            result["efficient_partial_spread_selected"],
            [True, True],
        )
        self.assertEqual(
            result["inefficient_partial_spread_selected"],
            [False, False],
        )
        self.assertEqual(
            result["immune_target_species"],
            [["a"], []],
        )
        self.assertEqual(
            result["damaged_target_species"],
            [[], ["b"]],
        )

    def test_slot_order_is_zero_then_one(self):
        from doubles_engine.audit_metadata import (
            assemble_partial_spread_state,
        )
        # Use distinct values to verify slot order.
        p0 = {"bt1": {0: "ZERO", 1: "ONE"}}
        result = assemble_partial_spread_state(
            "bt1", p0, {}, {}, {}, {}, {},
        )
        # Result for p0 is [ZERO, ONE].
        self.assertEqual(
            result["partial_immune_spread_selected"],
            ["ZERO", "ONE"],
        )

    def test_species_lists_preserved(self):
        from doubles_engine.audit_metadata import (
            assemble_partial_spread_state,
        )
        p4 = {"bt1": {0: ["a", "b"], 1: ["c"]}}
        p5 = {"bt1": {0: ["x"], 1: ["y", "z"]}}
        result = assemble_partial_spread_state(
            "bt1", {}, {}, {}, {}, p4, p5,
        )
        # Lists are preserved exactly (not copied).
        self.assertEqual(
            result["immune_target_species"],
            [["a", "b"], ["c"]],
        )
        self.assertEqual(
            result["damaged_target_species"],
            [["x"], ["y", "z"]],
        )

    def test_setdefault_inserts_battle_tag(self):
        from doubles_engine.audit_metadata import (
            assemble_partial_spread_state,
        )
        # Empty dicts + new battle_tag → dicts are mutated
        # to include the battle_tag key with default value.
        p0 = {}
        p4 = {}
        result = assemble_partial_spread_state(
            "bt_new", p0, {}, {}, {}, p4, {},
        )
        # Both dicts now have the new battle_tag key.
        self.assertIn("bt_new", p0)
        self.assertEqual(p0["bt_new"], {0: False, 1: False})
        self.assertIn("bt_new", p4)
        self.assertEqual(p4["bt_new"], {0: [], 1: []})

    def test_unrelated_battle_tags_not_modified(self):
        from doubles_engine.audit_metadata import (
            assemble_partial_spread_state,
        )
        # Pre-populate with a different battle_tag.
        p0 = {"bt_other": {0: True, 1: True}}
        p4 = {"bt_other": {0: ["x"], 1: ["y"]}}
        # Snapshot the inner dicts for the unrelated tag.
        original_inner_p0 = p0["bt_other"]
        original_inner_p4 = p4["bt_other"]
        assemble_partial_spread_state(
            "bt_new", p0, {}, {}, {}, p4, {},
        )
        # The 'bt_other' inner dict is untouched (same
        # object identity, not a new dict).
        self.assertIs(p0["bt_other"], original_inner_p0)
        self.assertIs(p4["bt_other"], original_inner_p4)
        # The 'bt_new' key was added.
        self.assertIn("bt_new", p0)
        self.assertEqual(p0["bt_new"], {0: False, 1: False})
        self.assertIn("bt_new", p4)
        self.assertEqual(p4["bt_new"], {0: [], 1: []})

    def test_setdefault_does_not_overwrite_existing(self):
        from doubles_engine.audit_metadata import (
            assemble_partial_spread_state,
        )
        # Existing battle_tag entry is preserved (not overwritten).
        p0 = {"bt1": {0: True, 1: False}}
        original_inner = {0: True, 1: False}
        p0["bt1"] = original_inner
        # Reference a new dict to check identity later.
        result = assemble_partial_spread_state(
            "bt1", p0, {}, {}, {}, {}, {},
        )
        # The inner dict is the SAME object as before
        # (setdefault returned the existing entry, did
        # not insert the default).
        self.assertIs(p0["bt1"], original_inner)
        self.assertEqual(
            result["partial_immune_spread_selected"],
            [True, False],
        )


# ---------------------------------------------------------------------------
# assemble_shared_engine_metadata
# ---------------------------------------------------------------------------


class TestAssembleSharedEngineMetadata(unittest.TestCase):
    def test_minimal_all_none(self):
        from doubles_engine.audit_metadata import (
            assemble_shared_engine_metadata,
        )
        # All None inputs.
        result = assemble_shared_engine_metadata(
            runtime_mode=None,
            concrete_player_class=None,
            v2l1_invocation_id=None,
            v2l1_invocation_status=None,
            selected_four=None,
            lead_2=None,
            back_2=None,
            preview_policy=None,
        )
        # 10 expected keys.
        self.assertEqual(
            set(result.keys()),
            {
                "runtime_mode",
                "concrete_player_class",
                "shared_engine_used",
                "shared_engine_owner",
                "shared_engine_invocation_id",
                "shared_engine_invocation_status",
                "selected_four",
                "lead_2",
                "back_2",
                "preview_policy",
            },
        )
        # shared_engine_used is False when invocation is not
        # completed.
        self.assertFalse(result["shared_engine_used"])
        # shared_engine_owner is the constant string.
        self.assertEqual(
            result["shared_engine_owner"],
            "bot_doubles_damage_aware.DoublesDamageAwarePlayer",
        )
        # All other fields are None.
        self.assertIsNone(result["runtime_mode"])
        self.assertIsNone(result["concrete_player_class"])
        self.assertIsNone(result["shared_engine_invocation_id"])
        self.assertIsNone(result["shared_engine_invocation_status"])
        self.assertIsNone(result["selected_four"])
        self.assertIsNone(result["lead_2"])
        self.assertIsNone(result["back_2"])
        self.assertIsNone(result["preview_policy"])

    def test_shared_engine_used_true_when_completed(self):
        from doubles_engine.audit_metadata import (
            assemble_shared_engine_metadata,
        )
        result = assemble_shared_engine_metadata(
            runtime_mode="random_doubles",
            concrete_player_class="DoublesDamageAwarePlayer",
            v2l1_invocation_id="inv-123",
            v2l1_invocation_status="completed",
            selected_four=None,
            lead_2=None,
            back_2=None,
            preview_policy=None,
        )
        self.assertTrue(result["shared_engine_used"])
        self.assertEqual(result["runtime_mode"], "random_doubles")
        self.assertEqual(
            result["concrete_player_class"],
            "DoublesDamageAwarePlayer",
        )
        self.assertEqual(
            result["shared_engine_invocation_id"], "inv-123"
        )
        self.assertEqual(
            result["shared_engine_invocation_status"], "completed"
        )

    def test_shared_engine_used_false_when_not_completed(self):
        from doubles_engine.audit_metadata import (
            assemble_shared_engine_metadata,
        )
        result = assemble_shared_engine_metadata(
            runtime_mode="random_doubles",
            concrete_player_class="DoublesDamageAwarePlayer",
            v2l1_invocation_id="inv-123",
            v2l1_invocation_status="in_progress",
            selected_four=None,
            lead_2=None,
            back_2=None,
            preview_policy=None,
        )
        self.assertFalse(result["shared_engine_used"])

    def test_shared_engine_used_false_when_id_empty(self):
        from doubles_engine.audit_metadata import (
            assemble_shared_engine_metadata,
        )
        # Empty string is falsy.
        result = assemble_shared_engine_metadata(
            runtime_mode="random_doubles",
            concrete_player_class="DoublesDamageAwarePlayer",
            v2l1_invocation_id="",
            v2l1_invocation_status="completed",
            selected_four=None,
            lead_2=None,
            back_2=None,
            preview_policy=None,
        )
        self.assertFalse(result["shared_engine_used"])

    def test_selected_four_lead_2_back_2_list_behavior(self):
        from doubles_engine.audit_metadata import (
            assemble_shared_engine_metadata,
        )
        # Lists are preserved exactly (same object, no copy).
        sf = ["a", "b", "c", "d"]
        l2 = ["e", "f"]
        b2 = ["g", "h"]
        result = assemble_shared_engine_metadata(
            runtime_mode=None,
            concrete_player_class=None,
            v2l1_invocation_id=None,
            v2l1_invocation_status=None,
            selected_four=sf,
            lead_2=l2,
            back_2=b2,
            preview_policy=None,
        )
        # The function does not copy or transform lists.
        self.assertIs(result["selected_four"], sf)
        self.assertIs(result["lead_2"], l2)
        self.assertIs(result["back_2"], b2)

    def test_preview_policy_preservation(self):
        from doubles_engine.audit_metadata import (
            assemble_shared_engine_metadata,
        )
        result = assemble_shared_engine_metadata(
            runtime_mode=None,
            concrete_player_class=None,
            v2l1_invocation_id=None,
            v2l1_invocation_status=None,
            selected_four=None,
            lead_2=None,
            back_2=None,
            preview_policy="matchup_top4_v3",
        )
        self.assertEqual(result["preview_policy"], "matchup_top4_v3")

    def test_runtime_modes(self):
        from doubles_engine.audit_metadata import (
            assemble_shared_engine_metadata,
        )
        # Both runtime modes are valid.
        for mode in ("random_doubles", "vgc_selected_four"):
            result = assemble_shared_engine_metadata(
                runtime_mode=mode,
                concrete_player_class=None,
                v2l1_invocation_id=None,
                v2l1_invocation_status=None,
                selected_four=None,
                lead_2=None,
                back_2=None,
                preview_policy=None,
            )
            self.assertEqual(result["runtime_mode"], mode)


if __name__ == "__main__":
    unittest.main()
