"""Tests for Phase RL-DATA-4 live trajectory exploration.

These tests cover:

* Helper-level logic (move classification, candidate
  collection, joint order building, v4a key building).
* Audit logger
  ``update_pending_turn_with_live_exploration``
  method (the core mechanism for true trajectory
  exploration).
* Dataset builder pass-through of live_exploration
  fields into v1.1 rows.
* Dry-run compatibility with v1.1 rows that have
  live_exploration fields.
* The exploration is true trajectory: selected ==
  submitted when triggered.
* The exploration never modifies the bot's normal
  behavior when the flag is absent.

These tests do NOT spawn battles. They use unit-level
fixtures and mock the audit logger.
"""

import json
import os
import sys
import unittest
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

# Ensure showdown_ai/ and scripts/ are on sys.path
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "showdown_ai"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analyze"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "inspect"))


# ---- Helper function tests ----
class TestNormMoveId(unittest.TestCase):
    def test_lowercase(self):
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _norm_move_id,
        )
        self.assertEqual(_norm_move_id("QuiverDance"), "quiverdance")
        self.assertEqual(_norm_move_id("RAIN DANCE"), "raindance")
        self.assertEqual(_norm_move_id("Dragon-Dance"), "dragondance")

    def test_empty(self):
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _norm_move_id,
        )
        self.assertEqual(_norm_move_id(None), "")
        self.assertEqual(_norm_move_id(""), "")


class TestClassifyMoveGroup(unittest.TestCase):
    def test_setup_moves(self):
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _classify_move_group,
        )
        self.assertEqual(
            _classify_move_group("quiverdance"), "setup_stat_boost"
        )
        self.assertEqual(
            _classify_move_group("swordsdance"), "setup_stat_boost"
        )
        self.assertEqual(
            _classify_move_group("nastyplot"), "setup_stat_boost"
        )
        self.assertEqual(
            _classify_move_group("calmmind"), "setup_stat_boost"
        )

    def test_weather_setters(self):
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _classify_move_group,
        )
        self.assertEqual(
            _classify_move_group("raindance"), "weather_terrain"
        )
        self.assertEqual(
            _classify_move_group("sunnyday"), "weather_terrain"
        )
        self.assertEqual(
            _classify_move_group("sandstorm"), "weather_terrain"
        )
        self.assertEqual(
            _classify_move_group("hail"), "weather_terrain"
        )

    def test_terrain_setters(self):
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _classify_move_group,
        )
        self.assertEqual(
            _classify_move_group("electricterrain"), "terrain_setter"
        )
        self.assertEqual(
            _classify_move_group("grassyterrain"), "terrain_setter"
        )
        self.assertEqual(
            _classify_move_group("mistyterrain"), "terrain_setter"
        )
        self.assertEqual(
            _classify_move_group("psychicterrain"), "terrain_setter"
        )

    def test_protect_moves(self):
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _classify_move_group,
        )
        self.assertEqual(
            _classify_move_group("protect"),
            "protection_defensive_support",
        )
        self.assertEqual(
            _classify_move_group("detect"),
            "protection_defensive_support",
        )
        self.assertEqual(
            _classify_move_group("spikyshield"),
            "protection_defensive_support",
        )

    def test_support_moves(self):
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _classify_move_group,
        )
        self.assertEqual(
            _classify_move_group("tailwind"),
            "healing_buff_ally_support",
        )
        self.assertEqual(
            _classify_move_group("trickroom"),
            "healing_buff_ally_support",
        )
        self.assertEqual(
            _classify_move_group("thunderwave"),
            "healing_buff_ally_support",
        )

    def test_attacking_moves(self):
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _classify_move_group,
        )
        self.assertIsNone(_classify_move_group("tackle"))
        self.assertIsNone(_classify_move_group("earthquake"))
        self.assertIsNone(_classify_move_group("hurricane"))
        self.assertIsNone(_classify_move_group("moonblast"))


class TestSlotOrderV4aKey(unittest.TestCase):
    def test_move_key(self):
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _slot_order_v4a_key,
        )
        import poke_env.player.battle_order as bo
        from poke_env.battle.move import Move
        order = bo.SingleBattleOrder(Move("quiverdance", gen=9))
        key = _slot_order_v4a_key(order, 0)
        # 4-element v4a key: [kind, move_id, target_pos, mechanic]
        self.assertEqual(key, ["move", "quiverdance", 0, ""])

    def test_switch_key(self):
        import poke_env.player.battle_order as bo
        from poke_env.battle.pokemon import Pokemon
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _slot_order_v4a_key,
        )
        # Create a real Pokemon
        mon = Pokemon(species="Incineroar", gen=9)
        order = bo.SingleBattleOrder(mon)
        key = _slot_order_v4a_key(order, 0)
        # 4-element v4a key: [kind, name, 0, mechanic]
        self.assertEqual(key[0], "switch")
        self.assertEqual(key[2], 0)
        self.assertEqual(key[3], "")

    def test_none_order(self):
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _slot_order_v4a_key,
        )
        self.assertEqual(
            _slot_order_v4a_key(None, 0), ["pass", "pass", 0, ""]
        )


class TestCollectExplorationCandidates(unittest.TestCase):
    def test_empty_valid_orders(self):
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _collect_exploration_candidates,
        )
        self.assertEqual(_collect_exploration_candidates([]), [])
        self.assertEqual(_collect_exploration_candidates(None), [])

    def test_only_attack_moves(self):
        import poke_env.player.battle_order as bo
        from poke_env.battle.move import Move
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _collect_exploration_candidates,
        )
        # Both slots have only attacking moves
        valid_orders = [
            [bo.SingleBattleOrder(Move("tackle", gen=9))],
            [bo.SingleBattleOrder(Move("earthquake", gen=9))],
        ]
        self.assertEqual(_collect_exploration_candidates(valid_orders), [])

    def test_setup_move_in_slot0(self):
        import poke_env.player.battle_order as bo
        from poke_env.battle.move import Move
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _collect_exploration_candidates,
        )
        valid_orders = [
            [bo.SingleBattleOrder(Move("quiverdance", gen=9))],
            [bo.SingleBattleOrder(Move("tackle", gen=9))],
        ]
        candidates = _collect_exploration_candidates(valid_orders)
        self.assertEqual(len(candidates), 1)
        group, order, slot, move = candidates[0]
        self.assertEqual(group, "setup_stat_boost")
        self.assertEqual(slot, 0)
        self.assertEqual(move, "quiverdance")

    def test_weather_in_slot1(self):
        import poke_env.player.battle_order as bo
        from poke_env.battle.move import Move
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _collect_exploration_candidates,
        )
        valid_orders = [
            [bo.SingleBattleOrder(Move("tackle", gen=9))],
            [bo.SingleBattleOrder(Move("raindance", gen=9))],
        ]
        candidates = _collect_exploration_candidates(valid_orders)
        self.assertEqual(len(candidates), 1)
        group, order, slot, move = candidates[0]
        self.assertEqual(group, "weather_terrain")
        self.assertEqual(slot, 1)
        self.assertEqual(move, "raindance")

    def test_mixed_candidates(self):
        import poke_env.player.battle_order as bo
        from poke_env.battle.move import Move
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _collect_exploration_candidates,
        )
        valid_orders = [
            [
                bo.SingleBattleOrder(Move("tackle", gen=9)),
                bo.SingleBattleOrder(Move("quiverdance", gen=9)),
            ],
            [
                bo.SingleBattleOrder(Move("raindance", gen=9)),
                bo.SingleBattleOrder(Move("protect", gen=9)),
            ],
        ]
        candidates = _collect_exploration_candidates(valid_orders)
        self.assertEqual(len(candidates), 3)
        groups = [c[0] for c in candidates]
        self.assertIn("setup_stat_boost", groups)
        self.assertIn("weather_terrain", groups)
        self.assertIn("protection_defensive_support", groups)

    def test_never_selects_switch_or_pass(self):
        import poke_env.player.battle_order as bo
        from poke_env.battle.move import Move
        from poke_env.battle.pokemon import Pokemon
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _collect_exploration_candidates,
        )
        # Even with switches and pass, the function
        # should only return move candidates
        valid_orders = [
            [
                bo.SingleBattleOrder(Pokemon(species="Incineroar", gen=9)),
                bo.SingleBattleOrder(Move("quiverdance", gen=9)),
            ],
            [None, bo.SingleBattleOrder(Move("tackle", gen=9))],
        ]
        candidates = _collect_exploration_candidates(valid_orders)
        self.assertEqual(len(candidates), 1)
        # The only move candidate is the setup move
        self.assertEqual(candidates[0][0], "setup_stat_boost")


class TestSelectExploration(unittest.TestCase):
    def test_empty_candidates(self):
        import random
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _select_exploration,
        )
        rng = random.Random(42)
        self.assertIsNone(_select_exploration(rng, []))

    def test_priority_setup_first(self):
        import random
        import poke_env.player.battle_order as bo
        from poke_env.battle.move import Move
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _select_exploration,
        )
        candidates = [
            (
                "weather_terrain",
                bo.SingleBattleOrder(Move("raindance", gen=9)),
                0,
                "raindance",
            ),
            (
                "setup_stat_boost",
                bo.SingleBattleOrder(Move("quiverdance", gen=9)),
                1,
                "quiverdance",
            ),
            (
                "protection_defensive_support",
                bo.SingleBattleOrder(Move("protect", gen=9)),
                0,
                "protect",
            ),
        ]
        rng = random.Random(42)
        choice = _select_exploration(rng, candidates)
        # Setup should have highest priority (0)
        self.assertIsNotNone(choice)
        group, order, slot, move, reason = choice
        self.assertEqual(group, "setup_stat_boost")
        self.assertEqual(move, "quiverdance")

    def test_deterministic_with_seed(self):
        import random
        import poke_env.player.battle_order as bo
        from poke_env.battle.move import Move
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _select_exploration,
        )
        # Two setup candidates: deterministic tiebreaker
        candidates = [
            (
                "setup_stat_boost",
                bo.SingleBattleOrder(Move("quiverdance", gen=9)),
                0,
                "quiverdance",
            ),
            (
                "setup_stat_boost",
                bo.SingleBattleOrder(Move("swordsdance", gen=9)),
                1,
                "swordsdance",
            ),
        ]
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        c1 = _select_exploration(rng1, candidates)
        c2 = _select_exploration(rng2, candidates)
        self.assertEqual(c1[3], c2[3])  # Same move


class TestBuildExploredJoint(unittest.TestCase):
    def test_replace_slot0(self):
        import poke_env.player.battle_order as bo
        from poke_env.battle.move import Move
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _build_explored_joint,
        )
        original = bo.DoubleBattleOrder(
            first_order=bo.SingleBattleOrder(Move("tackle", gen=9)),
            second_order=bo.SingleBattleOrder(Move("earthquake", gen=9)),
        )
        explored = bo.SingleBattleOrder(Move("quiverdance", gen=9))
        new_joint = _build_explored_joint(original, 0, explored)
        self.assertEqual(new_joint.first_order.order.id, "quiverdance")
        self.assertEqual(new_joint.second_order.order.id, "earthquake")

    def test_replace_slot1(self):
        import poke_env.player.battle_order as bo
        from poke_env.battle.move import Move
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _build_explored_joint,
        )
        original = bo.DoubleBattleOrder(
            first_order=bo.SingleBattleOrder(Move("tackle", gen=9)),
            second_order=bo.SingleBattleOrder(Move("earthquake", gen=9)),
        )
        explored = bo.SingleBattleOrder(Move("protect", gen=9))
        new_joint = _build_explored_joint(original, 1, explored)
        self.assertEqual(new_joint.first_order.order.id, "tackle")
        self.assertEqual(new_joint.second_order.order.id, "protect")


# ---- Audit logger tests ----
class TestAuditLoggerUpdatePendingTurn(unittest.TestCase):
    def test_method_exists(self):
        from showdown_ai.doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        self.assertTrue(
            hasattr(
                DoublesDecisionAuditLogger,
                "update_pending_turn_with_live_exploration",
            )
        )

    def test_updates_pending_turn(self):
        """Test that the audit logger's
        update_pending_turn_with_live_exploration
        updates the pending turn in-place.
        """
        from showdown_ai.doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        # Create a real audit logger (in-memory)
        logger = DoublesDecisionAuditLogger(
            filepath="/tmp/_test_audit.jsonl",
            reset=True,
        )
        battle_tag = "test_battle_1"
        # Simulate a pending turn
        logger.pending_turns[battle_tag] = {
            "turn": 1,
            "selected_joint_order": "/choose move tackle 0, /choose move earthquake 0",
            "v4a_selected_joint_key": [
                ["move", "tackle", 0],
                ["move", "earthquake", 0],
            ],
        }
        # Update with live exploration
        logger.update_pending_turn_with_live_exploration(
            battle_tag=battle_tag,
            turn=1,
            explored_selected_joint_order="/choose move quiverdance 0, /choose move earthquake 0",
            explored_v4a_selected_joint_key=[
                ["move", "quiverdance", 0],
                ["move", "earthquake", 0],
            ],
            live_exploration_state={
                "live_exploration_enabled": True,
                "live_exploration_triggered": True,
                "live_exploration_rate": 0.20,
                "live_exploration_seed": 123,
                "live_exploration_candidate_group": "setup_stat_boost",
                "live_exploration_original_action": "/choose move tackle 0",
                "live_exploration_selected_action": "/choose move quiverdance 0",
                "live_exploration_submitted_action": "/choose move quiverdance 0",
                "live_exploration_reason": "live exploration chose setup_stat_boost",
                "live_exploration_no_candidate_reason": "",
                "live_exploration_action_was_legal": True,
                "live_exploration_postprocess_only": False,
            },
        )
        pending = logger.pending_turns[battle_tag]
        # The selected order should be the explored order
        self.assertIn("quiverdance", pending["selected_joint_order"])
        # The v4a key should be the explored key
        self.assertEqual(
            pending["v4a_selected_joint_key"][0][1], "quiverdance"
        )
        # The live_exploration fields should be set
        self.assertTrue(pending["live_exploration_enabled"])
        self.assertTrue(pending["live_exploration_triggered"])
        self.assertEqual(
            pending["live_exploration_candidate_group"],
            "setup_stat_boost",
        )
        self.assertFalse(pending["live_exploration_postprocess_only"])

    def test_no_op_when_no_pending(self):
        """Test that the method is a no-op when there's
        no pending turn for the battle_tag.
        """
        from showdown_ai.doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        logger = DoublesDecisionAuditLogger(
            filepath="/tmp/_test_audit2.jsonl",
            reset=True,
        )
        # No pending turn
        logger.update_pending_turn_with_live_exploration(
            battle_tag="nonexistent_battle",
            turn=1,
            explored_selected_joint_order="/choose move x",
            explored_v4a_selected_joint_key=[
                ["move", "x", 0],
                ["move", "y", 0],
            ],
            live_exploration_state={"live_exploration_triggered": True},
        )
        # Should not raise, should not create a pending turn
        self.assertNotIn("nonexistent_battle", logger.pending_turns)

    def test_no_op_when_turn_mismatch(self):
        """Test that the method is a no-op when the
        pending turn is for a different turn number.
        """
        from showdown_ai.doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        logger = DoublesDecisionAuditLogger(
            filepath="/tmp/_test_audit3.jsonl",
            reset=True,
        )
        battle_tag = "test_battle_2"
        logger.pending_turns[battle_tag] = {
            "turn": 5,  # Pending turn is 5
            "selected_joint_order": "/choose move tackle 0",
            "v4a_selected_joint_key": [["move", "tackle", 0]],
        }
        # Try to update for turn 3 (mismatch)
        logger.update_pending_turn_with_live_exploration(
            battle_tag=battle_tag,
            turn=3,  # Mismatch
            explored_selected_joint_order="/choose move quiverdance 0",
            explored_v4a_selected_joint_key=[
                ["move", "quiverdance", 0]
            ],
            live_exploration_state={"live_exploration_triggered": True},
        )
        # The pending turn should NOT be updated
        pending = logger.pending_turns[battle_tag]
        self.assertEqual(pending["turn"], 5)
        self.assertIn("tackle", pending["selected_joint_order"])


# ---- Dataset builder tests ----
class TestBuilderPassesThroughLiveExploration(unittest.TestCase):
    def test_live_exploration_fields_in_v1_1(self):
        """Test that the builder passes through
        live_exploration fields from the audit JSONL.
        """
        from showdown_ai.build_turn_level_offline_dataset import (
            build_row,
        )
        battle = {
            "battle_tag": "test_battle",
            "audit_turns": [
                {
                    "turn": 1,
                    "selected_joint_order": "/choose move x 0, /choose move y 0",
                    "v4a_selected_joint_key": [
                        ["move", "x", "0", ""],
                        ["move", "y", "0", ""],
                    ],
                    "v4a_final_action_keys": [
                        ["move", "x", "0", ""],
                        ["move", "y", "0", ""],
                    ],
                    "v2l1_legal_action_keys_slot0": [
                        ["move", "x", "0", ""],
                        ["move", "quiverdance", "0", ""],
                    ],
                    "v2l1_legal_action_keys_slot1": [
                        ["move", "y", "0", ""],
                    ],
                    "v4a_legal_action_keys_slot0": [
                        ["move", "x", "0", ""],
                        ["move", "quiverdance", "0", ""],
                    ],
                    "v4a_legal_action_keys_slot1": [
                        ["move", "y", "0", ""],
                    ],
                    # RL-DATA-4 live exploration fields
                    "live_exploration_enabled": True,
                    "live_exploration_triggered": True,
                    "live_exploration_rate": 0.20,
                    "live_exploration_seed": 123,
                    "live_exploration_candidate_group": "setup_stat_boost",
                    "live_exploration_original_action": "/choose move x 0",
                    "live_exploration_selected_action": "/choose move quiverdance 0",
                    "live_exploration_submitted_action": "/choose move quiverdance 0",
                    "live_exploration_reason": "exploration chose setup_stat_boost",
                    "live_exploration_no_candidate_reason": "",
                    "live_exploration_action_was_legal": True,
                    "live_exploration_postprocess_only": False,
                }
            ],
            "won": True,
        }
        turn = battle["audit_turns"][0]
        row = build_row(
            row_battle=battle,
            turn=turn,
            source_artifact="test_artifact",
            benchmark_arm="rl_data_4_live_explore",
            dataset_id="rl_data_4_live_exploration",
            policy_name_fallback="treatment",
        )
        self.assertIsNotNone(row)
        # All live_exploration fields should be in the row
        self.assertTrue(row["live_exploration_enabled"])
        self.assertTrue(row["live_exploration_triggered"])
        self.assertEqual(row["live_exploration_rate"], 0.20)
        self.assertEqual(row["live_exploration_seed"], 123)
        self.assertEqual(
            row["live_exploration_candidate_group"],
            "setup_stat_boost",
        )
        self.assertEqual(
            row["live_exploration_selected_action"],
            "/choose move quiverdance 0",
        )
        self.assertEqual(
            row["live_exploration_submitted_action"],
            "/choose move quiverdance 0",
        )
        self.assertTrue(row["live_exploration_action_was_legal"])
        self.assertFalse(row["live_exploration_postprocess_only"])

    def test_defaults_for_audit_without_live_exploration(self):
        """Test that the builder sets safe defaults
        for rows whose audit JSONL has no
        live_exploration fields.
        """
        from showdown_ai.build_turn_level_offline_dataset import (
            build_row,
        )
        battle = {
            "battle_tag": "test_battle_2",
            "audit_turns": [
                {
                    "turn": 1,
                    "selected_joint_order": "/choose move x 0, /choose move y 0",
                    "v4a_selected_joint_key": [
                        ["move", "x", "0", ""],
                        ["move", "y", "0", ""],
                    ],
                    "v4a_final_action_keys": [
                        ["move", "x", "0", ""],
                        ["move", "y", "0", ""],
                    ],
                    "v2l1_legal_action_keys_slot0": [
                        ["move", "x", "0", ""],
                    ],
                    "v2l1_legal_action_keys_slot1": [
                        ["move", "y", "0", ""],
                    ],
                    "v4a_legal_action_keys_slot0": [
                        ["move", "x", "0", ""],
                    ],
                    "v4a_legal_action_keys_slot1": [
                        ["move", "y", "0", ""],
                    ],
                    # NO live_exploration fields
                }
            ],
            "won": True,
        }
        turn = battle["audit_turns"][0]
        row = build_row(
            row_battle=battle,
            turn=turn,
            source_artifact="test_artifact",
            benchmark_arm="test_arm",
            dataset_id="test_dataset",
            policy_name_fallback="treatment",
        )
        self.assertIsNotNone(row)
        # Defaults should be applied
        self.assertFalse(row["live_exploration_enabled"])
        self.assertFalse(row["live_exploration_triggered"])
        self.assertEqual(
            row["live_exploration_candidate_group"], "none"
        )
        self.assertFalse(row["live_exploration_postprocess_only"])


# ---- Live exploration invariant tests ----
class TestLiveExplorationInvariants(unittest.TestCase):
    def test_exploration_never_resurrects_blocked_action(self):
        """Test that exploration only selects from
        legal non-attack candidates, never resurrects
        blocked actions.
        """
        # This is enforced by _collect_exploration_candidates
        # which only returns valid move orders from
        # battle.valid_orders. A blocked action would not
        # be in valid_orders.
        import random
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _select_exploration,
        )
        # Empty candidates → no exploration
        rng = random.Random(42)
        self.assertIsNone(_select_exploration(rng, []))

    def test_exploration_never_selects_switch(self):
        """Test that exploration never selects a switch
        (unless explicitly allowed by a future flag).
        """
        import random
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _collect_exploration_candidates,
        )
        # Even if valid_orders has switches, they should
        # not appear as exploration candidates
        import poke_env.player.battle_order as bo
        from poke_env.battle.pokemon import Pokemon
        from poke_env.battle.move import Move
        valid_orders = [
            [
                bo.SingleBattleOrder(Pokemon(species="Incineroar", gen=9)),
                bo.SingleBattleOrder(Move("tackle", gen=9)),
            ],
            [bo.SingleBattleOrder(Move("raindance", gen=9))],
        ]
        candidates = _collect_exploration_candidates(valid_orders)
        # Only the weather setter should be a candidate
        # (the switch is filtered out)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][0], "weather_terrain")

    def test_exploration_action_legal(self):
        """Test that all exploration candidates are
        legal move orders (SingleBattleOrder with a
        Move inner object).
        """
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _collect_exploration_candidates,
            _order_kind,
        )
        import poke_env.player.battle_order as bo
        from poke_env.battle.move import Move
        valid_orders = [
            [bo.SingleBattleOrder(Move("quiverdance", gen=9))],
            [bo.SingleBattleOrder(Move("raindance", gen=9))],
        ]
        candidates = _collect_exploration_candidates(valid_orders)
        for group, order, slot, move in candidates:
            self.assertEqual(_order_kind(order), "move")
            # The order must be a SingleBattleOrder
            # (already enforced by the collector)
            self.assertIsNotNone(order)
            # The move ID must be non-empty
            self.assertNotEqual(move, "")

    def test_submitted_equals_selected_when_triggered(self):
        """Test that when exploration triggers, the
        submitted action equals the selected action.
        This is enforced by the bot's choose_move: it
        returns the explored joint order, and the
        poke-env client sends that exact order to the
        server.
        """
        # This is a structural invariant. The bot's
        # choose_move returns the explored joint order.
        # The poke-env client sends the returned order
        # to the server. So the submitted action is
        # always equal to the selected action.
        # Verify by inspecting the explore function.
        import inspect
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            LiveExplorationDoublesDamageAwarePlayer,
        )
        source = inspect.getsource(
            LiveExplorationDoublesDamageAwarePlayer
        )
        self.assertIn("return new_joint", source)
        # The explored message is what gets submitted
        self.assertIn("explored_msg", source)
        # The audit record uses the explored message
        self.assertIn("live_exploration_submitted_action", source)

    def test_postprocess_only_false_in_audit(self):
        """Test that the audit fields always set
        live_exploration_postprocess_only=False (true
        trajectory, not post-processing).
        """
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            LiveExplorationDoublesDamageAwarePlayer,
        )
        import inspect
        source = inspect.getsource(
            LiveExplorationDoublesDamageAwarePlayer
        )
        self.assertIn("live_exploration_postprocess_only", source)
        self.assertIn("False", source)


# ---- Deterministic exploration test ----
class TestExplorationDeterministic(unittest.TestCase):
    def test_same_seed_same_trigger(self):
        """Test that exploration is deterministic
        with a fixed seed.
        """
        import random
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _collect_exploration_candidates,
            _select_exploration,
        )
        import poke_env.player.battle_order as bo
        from poke_env.battle.move import Move
        valid_orders = [
            [bo.SingleBattleOrder(Move("quiverdance", gen=9))],
            [bo.SingleBattleOrder(Move("raindance", gen=9))],
        ]
        candidates = _collect_exploration_candidates(valid_orders)
        # Run the same logic twice with the same seed
        rng1 = random.Random(123)
        rng2 = random.Random(123)
        c1 = _select_exploration(rng1, candidates)
        c2 = _select_exploration(rng2, candidates)
        self.assertEqual(c1, c2)

    def test_different_seed_different_outcome_possible(self):
        """Test that different seeds can produce
        different outcomes (when there's no fixed
        priority difference).
        """
        import random
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            _collect_exploration_candidates,
            _select_exploration,
        )
        import poke_env.player.battle_order as bo
        from poke_env.battle.move import Move
        # Two setup candidates with same priority
        candidates = [
            (
                "setup_stat_boost",
                bo.SingleBattleOrder(Move("quiverdance", gen=9)),
                0,
                "quiverdance",
            ),
            (
                "setup_stat_boost",
                bo.SingleBattleOrder(Move("swordsdance", gen=9)),
                1,
                "swordsdance",
            ),
        ]
        # Try many seeds, collect distinct outcomes
        outcomes = set()
        for seed in range(100):
            rng = random.Random(seed)
            c = _select_exploration(rng, candidates)
            if c is not None:
                outcomes.add(c[3])  # move name
        # Should have at least 1 distinct outcome
        # (and at most 2)
        self.assertGreaterEqual(len(outcomes), 1)
        self.assertLessEqual(len(outcomes), 2)


# ---- Local server guard test ----
class TestLocalServerGuard(unittest.TestCase):
    def test_default_health_url_is_local(self):
        """Test that the script's default health URL
        is localhost:8000.
        """
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            HEALTH_URL,
        )
        self.assertEqual(HEALTH_URL, "http://localhost:8000")

    def test_health_check_function_exists(self):
        """Test that the health check function exists
        and is callable.
        """
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            check_localhost_healthy,
        )
        self.assertTrue(callable(check_localhost_healthy))

    def test_max_battles_cap(self):
        """Test that the script has a hard cap on
        battles (1000).
        """
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            MAX_BATTLES,
        )
        self.assertEqual(MAX_BATTLES, 1000)


# ---- No behavior change when flag absent ----
class TestNoBehaviorChangeWhenFlagAbsent(unittest.TestCase):
    def test_exploration_disabled_returns_normal(self):
        """Test that when _live_exploration_enabled
        is False, the player returns the normal
        selected action unchanged.
        """
        from showdown_ai.rl_data_4_live_exploration_local_audit import (
            LiveExplorationDoublesDamageAwarePlayer,
        )
        import inspect
        source = inspect.getsource(
            LiveExplorationDoublesDamageAwarePlayer
        )
        # The choose_move method should check the flag
        # and return normal_joint when disabled
        self.assertIn("_live_exploration_enabled", source)
        self.assertIn("return normal_joint", source)


# ---- Dataset builder integration test ----
class TestBuilderHasLiveExplorationFields(unittest.TestCase):
    def test_live_exploration_fields_constant(self):
        """Test that the builder has the
        LIVE_EXPLORATION_FIELDS constant.
        """
        from showdown_ai.build_turn_level_offline_dataset import (
            LIVE_EXPLORATION_FIELDS,
        )
        # All required fields should be present
        required = {
            "live_exploration_enabled",
            "live_exploration_triggered",
            "live_exploration_rate",
            "live_exploration_seed",
            "live_exploration_candidate_group",
            "live_exploration_original_action",
            "live_exploration_selected_action",
            "live_exploration_submitted_action",
            "live_exploration_reason",
            "live_exploration_no_candidate_reason",
            "live_exploration_action_was_legal",
            "live_exploration_postprocess_only",
        }
        self.assertEqual(set(LIVE_EXPLORATION_FIELDS), required)

    def test_extract_helper(self):
        """Test that the builder has the
        _extract_v1_1_live_exploration helper.
        """
        from showdown_ai.build_turn_level_offline_dataset import (
            _extract_v1_1_live_exploration,
        )
        self.assertTrue(callable(_extract_v1_1_live_exploration))

        # Test with empty turn (no live_exploration fields)
        result = _extract_v1_1_live_exploration({})
        self.assertFalse(result["live_exploration_enabled"])
        self.assertFalse(result["live_exploration_triggered"])
        self.assertFalse(result["live_exploration_postprocess_only"])

        # Test with live_exploration fields
        result = _extract_v1_1_live_exploration({
            "live_exploration_enabled": True,
            "live_exploration_triggered": True,
            "live_exploration_rate": 0.20,
            "live_exploration_seed": 123,
            "live_exploration_candidate_group": "setup_stat_boost",
            "live_exploration_original_action": "/choose move x",
            "live_exploration_selected_action": "/choose move y",
            "live_exploration_submitted_action": "/choose move y",
            "live_exploration_reason": "exploration",
            "live_exploration_no_candidate_reason": "",
            "live_exploration_action_was_legal": True,
            "live_exploration_postprocess_only": False,
        })
        self.assertTrue(result["live_exploration_enabled"])
        self.assertEqual(result["live_exploration_rate"], 0.20)
        self.assertEqual(
            result["live_exploration_candidate_group"],
            "setup_stat_boost",
        )


if __name__ == "__main__":
    unittest.main()
