"""Phase BI-3B: Mega tie behavior, higher-score selection, V4a audit.

These tests prove:
- On equal score: plain always wins (stable sort + plain-first join_orders).
- On strictly higher score: Mega wins (selection is by max score).
- The audit logger can serialize a v4a_selected_joint_key whose
  mechanic field is "mega".

The tests do NOT change production code. They inspect the
existing selection pipeline (join_orders, sorted scoring,
audit logger) at the unit level.

The tests do NOT run a real Showdown battle.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _MockMove:
    """Minimal Move stand-in."""

    def __init__(self, move_id="tackle"):
        self.id = move_id


def _plain(move_id="tackle", move_target=0):
    from poke_env.battle.double_battle import SingleBattleOrder
    return SingleBattleOrder(
        _MockMove(move_id), move_target=move_target
    )


def _mega(move_id="tackle", move_target=0):
    from poke_env.battle.double_battle import SingleBattleOrder
    return SingleBattleOrder(
        _MockMove(move_id), move_target=move_target, mega=True
    )


def _cleanup(paths):
    for p in paths:
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


class TestTieBehaviorPrefersPlain(unittest.TestCase):
    """When scores are equal, plain order wins because
    join_orders iterates plain-first and Python's sort
    is stable."""

    def test_join_orders_iterates_plain_first(self):
        from poke_env.player.battle_order import DoubleBattleOrder
        plain0 = _plain()
        mega0 = _mega()
        plain1 = _plain(move_target=1)
        mega1 = _mega(move_target=1)
        jo = DoubleBattleOrder.join_orders(
            [plain0, mega0], [plain1, mega1]
        )
        # 3 valid combos (both-mega is filtered by poke-env).
        self.assertEqual(len(jo), 3)
        # First combo: plain/plain.
        self.assertFalse(jo[0].first_order.mega)
        self.assertFalse(jo[0].second_order.mega)
        # Second combo: plain/mega.
        self.assertFalse(jo[1].first_order.mega)
        self.assertTrue(jo[1].second_order.mega)
        # Third combo: mega/plain.
        self.assertTrue(jo[2].first_order.mega)
        self.assertFalse(jo[2].second_order.mega)

    def test_both_mega_filtered_by_join_orders(self):
        """poke-env's join_orders explicitly forbids
        both-slots-mega. This is a Showdown-level rule
        (only one Pokemon can Mega per side per battle).
        """
        from poke_env.player.battle_order import DoubleBattleOrder
        plain0 = _plain()
        mega0 = _mega()
        plain1 = _plain(move_target=1)
        mega1 = _mega(move_target=1)
        jo = DoubleBattleOrder.join_orders(
            [plain0, mega0], [plain1, mega1]
        )
        # No combo has both first.mega=True AND second.mega=True.
        for combo in jo:
            self.assertFalse(
                combo.first_order.mega and combo.second_order.mega
            )

    def test_stable_sort_preserves_plain_first_on_tie(self):
        """Python's list.sort is stable. So when two
        joint orders tie, the one that appeared first
        in the input list (plain/plain) is selected.
        """
        from poke_env.player.battle_order import DoubleBattleOrder
        plain0 = _plain()
        mega0 = _mega()
        plain1 = _plain(move_target=1)
        jo = DoubleBattleOrder.join_orders([plain0, mega0], [plain1])
        # jo[0] = plain/plain, jo[1] = mega/plain.
        self.assertEqual(len(jo), 2)
        # Build equal-score list.
        scored = [
            (jo[0], 100.0, 50.0, 50.0),
            (jo[1], 100.0, 60.0, 50.0),
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        # Stable sort: plain/plain stays first.
        self.assertFalse(scored[0][0].first_order.mega)
        self.assertFalse(scored[0][0].second_order.mega)

    def test_higher_score_mega_can_win(self):
        """When Mega score is strictly higher than plain,
        Mega wins — selection is by max score, not by
        tie-breaking.
        """
        from poke_env.player.battle_order import DoubleBattleOrder
        plain0 = _plain()
        mega0 = _mega()
        plain1 = _plain(move_target=1)
        jo = DoubleBattleOrder.join_orders([plain0, mega0], [plain1])
        # Plain/plain = 100, Mega/plain = 110.
        scored = [
            (jo[0], 100.0, 50.0, 50.0),
            (jo[1], 110.0, 60.0, 50.0),
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        # Mega/plain wins on strict score.
        self.assertTrue(scored[0][0].first_order.mega)
        self.assertFalse(scored[0][0].second_order.mega)


class TestMegaPathInSort(unittest.TestCase):
    """Confirm the BI-3A legal-order list goes through
    the existing scoring path without modification.
    """

    def test_augmented_orders_pass_through_join_orders(self):
        """The augmented valid_orders[si] is a list of
        plain-then-mega per move. join_orders takes the
        cartesian product and respects plain-first order.
        """
        from doubles_engine.action_keys import (
            _augment_valid_orders_with_mega,
        )
        from poke_env.player.battle_order import DoubleBattleOrder

        class _Battle:
            can_mega_evolve = [True, True]
            # Phase BI-3G: include active_pokemon with a
            # Mega-capable species so the species guard
            # passes.

            class _P:
                def __init__(self, species):
                    self.species = species
            active_pokemon = [
                _P("charizard"), _P("charizard"),
            ]

        class _Cfg:
            enable_mega_evolution = True

        plain0 = _plain()
        plain1 = _plain(move_target=1)
        aug = _augment_valid_orders_with_mega(
            _Battle(), [[plain0], [plain1]], _Cfg()
        )
        # Each slot has 2 orders (plain, mega).
        self.assertEqual(len(aug[0]), 2)
        self.assertEqual(len(aug[1]), 2)
        # join_orders takes the cartesian product.
        jo = DoubleBattleOrder.join_orders(aug[0], aug[1])
        # Plain/plain, plain/mega, mega/plain (no mega/mega).
        self.assertEqual(len(jo), 3)


class TestV4aAuditMegaRecord(unittest.TestCase):
    """V4a audit can record Mega selected/final keys."""

    def test_v4a_selected_joint_key_with_mega_serializes(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False
        ) as f:
            main_path = f.name
        with tempfile.NamedTemporaryFile(
            suffix=".live.jsonl", delete=False
        ) as f:
            live_path = f.name
        try:
            logger = DoublesDecisionAuditLogger(
                filepath=main_path,
                reset=True,
                detail_level="top5",
                live_event_filepath=live_path,
            )

            class FB:
                player_username = "test"
                turn = 1
                active_pokemon = [None, None]
                opponent_active_pokemon = [None, None]

            v4a_selected = (
                ("move", "tackle", 0, "mega"),
                ("move", "earthquake", 1, ""),
            )
            v4a_final = [
                ("move", "tackle", 0, "mega"),
                ("move", "earthquake", 1, ""),
            ]
            logger.completed_turns["tag"] = []
            logger.log_turn_decision(
                battle_tag="tag",
                turn=1,
                battle=FB(),
                selected_joint_order="pass",
                selected_score=0.0,
                scored_joint_orders=[],
                expected_damages=[None, None],
                expected_kos=[None, None],
                target_hps=[1.0, 1.0],
                overkill_triggered=[False, False],
                focus_fire_triggered=[False, False],
                ally_hit_penalty_triggered=[False, False],
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=[None, None],
                slot_action_types=[None, None],
                target_species=[None, None],
                v2l1_legal_action_keys_slot0=[],
                v2l1_legal_action_keys_slot1=[],
                v2l1_raw_scores_slot0={},
                v2l1_raw_scores_slot1={},
                v2l1_safety_blocks_slot0={},
                v2l1_safety_blocks_slot1={},
                v2l1_selected_joint_key=None,
                v2l1_final_action_keys=[],
                v4a_legal_action_keys_slot0=[
                    ("move", "tackle", 0, "mega"),
                    ("move", "tackle", 0, ""),
                ],
                v4a_legal_action_keys_slot1=[],
                v4a_selected_joint_key=v4a_selected,
                v4a_final_action_keys=v4a_final,
            )
            logger.save_battle("tag", "test", FB())
            with open(main_path) as f:
                record = json.loads(f.readline())
            persisted = record["audit_turns"][0]
            # The selected joint key serializes as JSON array.
            self.assertEqual(
                persisted["v4a_selected_joint_key"],
                [["move", "tackle", 0, "mega"],
                 ["move", "earthquake", 1, ""]],
            )
            # Final action keys serialize with "mega" preserved.
            self.assertEqual(
                persisted["v4a_final_action_keys"],
                [["move", "tackle", 0, "mega"],
                 ["move", "earthquake", 1, ""]],
            )
            # Live event also projects Mega v4a.
            with open(live_path) as f:
                lines = [l for l in f if l.strip()]
            events = [json.loads(l) for l in lines]
            decision = [e for e in events if e.get("event") == "decision"][0]
            self.assertIn("v4a", decision)
            self.assertEqual(
                decision["v4a"]["v4a_selected_joint_key"],
                [["move", "tackle", 0, "mega"],
                 ["move", "earthquake", 1, ""]],
            )
        finally:
            _cleanup([main_path, live_path])


class TestNoProductionCleanupImport(unittest.TestCase):
    def test_bot_does_not_import_cleanup(self):
        import bot_doubles_damage_aware as m
        with open(m.__file__) as f:
            content = f.read()
        self.assertNotIn("import poke_env_test_cleanup", content)
        self.assertNotIn("from poke_env_test_cleanup", content)


if __name__ == "__main__":
    unittest.main()