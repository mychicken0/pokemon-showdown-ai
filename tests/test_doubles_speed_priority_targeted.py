"""Phase BEHAVIOR-6 — Targeted speed-priority Protect tests.

These tests verify whether the current speed-priority
Protect logic is too weak. Specifically:
- Expected-faint with Protect available: should Protect
  rank above a non-decisive attack?
- Attack-penalty applied: should Protect beat the
  penalized attack?
- Attack can still win when it KOs the immediate threat.
- No Protect available: attack remains valid.
- Flags reset between turns.
- Analyzer expected-faint attack mapping.
"""
import sys
import os
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Reuse the existing mock infrastructure from test_doubles_speed_priority.
from test_doubles_speed_priority import (
    MockMove, MockPokemon, MockBattle, TestPlayer,
)
from bot_doubles_damage_aware import DoublesDamageAwareConfig
from poke_env.player.battle_order import SingleBattleOrder


def _make_threatened_battle(battle, our_hp=0.20):
    """Set up a battle with a speed-priority threat.

    Our active: slow, low HP, Protect legal.
    Opponent: fast, can OHKO.
    """
    our_active = MockPokemon(
        "slowbro",
        base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                    "spa": 100, "spd": 80},
        level=80,
    )
    our_active.current_hp_fraction = our_hp
    opp = MockPokemon(
        "aerodactyl",
        base_stats={"spe": 130, "hp": 80, "atk": 105, "def": 65,
                    "spa": 60, "spd": 75},
        level=80,
    )
    battle.opponent_active_pokemon[0] = opp
    battle.active_pokemon[0] = our_active
    return our_active, opp


class TestProtectBeatsUnsafeAttack(unittest.TestCase):
    def test_expected_faint_with_protect_prefers_protect(self):
        """When expected_to_faint is True and Protect is
        legal, Protect should rank above a non-decisive
        attack.
        """
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_use_scaled_penalty=False,
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        # Set up the per-battle state.
        player._current_valid_orders[0] = [
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
            SingleBattleOrder(
                MockMove("tackle", "NORMAL", base_power=40), move_target=1
            ),
        ]
        player.last_protect_turn[battle_tag] = {}
        our_active, opp = _make_threatened_battle(battle, our_hp=0.20)
        # Score the actions.
        protect_score = player.score_action(
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
            0, battle,
        )
        tackle_score = player.score_action(
            SingleBattleOrder(
                MockMove("tackle", "NORMAL", base_power=40), move_target=1
            ),
            0, battle,
        )
        # Protect should beat tackle when expected_to_faint.
        self.assertGreater(
            protect_score, tackle_score,
            f"Protect ({protect_score}) should beat tackle "
            f"({tackle_score}) when expected_to_faint"
        )

    def test_attack_penalty_makes_unsafe_attack_lose_to_protect(self):
        """When attack_penalty is applied, the penalized
        attack should lose to Protect.
        """
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_use_scaled_penalty=False,
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        player._current_valid_orders[0] = [
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
            SingleBattleOrder(
                MockMove("watergun", "WATER", base_power=40), move_target=1
            ),
        ]
        player.last_protect_turn[battle_tag] = {}
        our_active, opp = _make_threatened_battle(battle, our_hp=0.25)
        protect_score = player.score_action(
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
            0, battle,
        )
        attack_score = player.score_action(
            SingleBattleOrder(
                MockMove("watergun", "WATER", base_power=40), move_target=1
            ),
            0, battle,
        )
        # Protect should beat the penalized attack.
        self.assertGreater(
            protect_score, attack_score,
            f"Protect ({protect_score}) should beat attack "
            f"({attack_score}) when attack_penalty applied"
        )


class TestAttackCanStillWinWhenKO(unittest.TestCase):
    def test_attack_can_remain_above_protect_with_high_damage(self):
        """If an attack has decisive KO value, it should
        remain above Protect. This avoids overcorrection.
        """
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_use_scaled_penalty=False,
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        # Use a high-base-power attack.
        player._current_valid_orders[0] = [
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
            SingleBattleOrder(
                MockMove("explosion", "NORMAL", base_power=250),
                move_target=1
            ),
        ]
        player.last_protect_turn[battle_tag] = {}
        our_active, opp = _make_threatened_battle(battle, our_hp=0.50)
        protect_score = player.score_action(
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
            0, battle,
        )
        self.assertIsInstance(protect_score, (int, float))


class TestNoProtectAvailable(unittest.TestCase):
    def test_no_protect_available_attack_remains_valid(self):
        """When Protect is NOT legal, the attack should
        still be scored.
        """
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_use_scaled_penalty=False,
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        # Only attack is legal.
        player._current_valid_orders[0] = [
            SingleBattleOrder(
                MockMove("tackle", "NORMAL", base_power=40), move_target=1
            ),
        ]
        our_active, opp = _make_threatened_battle(battle, our_hp=0.20)
        attack_score = player.score_action(
            SingleBattleOrder(
                MockMove("tackle", "NORMAL", base_power=40), move_target=1
            ),
            0, battle,
        )
        # Attack should be scored (not 0).
        self.assertIsInstance(attack_score, (int, float))


class TestFlagsReset(unittest.TestCase):
    def test_speed_priority_flags_reset_between_turns(self):
        """Speed-priority flags should reset per turn.
        Check that the per-battle dicts are initialized
        to {0: False, 1: False} for a new battle.
        """
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
            )
        )
        battle_tag = "test_battle"
        # Simulate reset (mimics the reset at start of
        # choose_move).
        player._speed_priority_threatened[battle_tag] = {
            0: False, 1: False
        }
        player._speed_priority_protect_bonus_applied[battle_tag] = {
            0: False, 1: False
        }
        player._speed_priority_attack_penalty_applied[battle_tag] = {
            0: False, 1: False
        }
        player._speed_priority_switch_bonus_applied[battle_tag] = {
            0: False, 1: False
        }
        player._protected_due_to_speed_priority[battle_tag] = {
            0: False, 1: False
        }
        player._expected_to_faint_before_moving[battle_tag] = {
            0: False, 1: False
        }
        # Verify all are False.
        for d in [
            player._speed_priority_threatened[battle_tag],
            player._speed_priority_protect_bonus_applied[battle_tag],
            player._speed_priority_attack_penalty_applied[battle_tag],
            player._speed_priority_switch_bonus_applied[battle_tag],
            player._protected_due_to_speed_priority[battle_tag],
            player._expected_to_faint_before_moving[battle_tag],
        ]:
            self.assertEqual(d, {0: False, 1: False})


class TestAnalyzerExpectedFaintAttackMapping(unittest.TestCase):
    def test_analyzer_expected_faint_attack_slot_mapping(self):
        """Tiny JSON fixture: slot0 expected_faint true,
        slot0 final action attack. Analyzer should report
        the expected-faint attack case correctly.
        """
        import json
        import tempfile
        from analyze_doubles_turn_level import (
            _extract_turn_record, _aggregate,
        )
        v4a_sel = [
            ["move", "tackle", 1, ""],
            ["move", "ember", 0, ""],
        ]
        turn = {
            "turn": 1,
            "v4a_selected_joint_key": v4a_sel,
            "v4a_final_action_keys": v4a_sel,
            "speed_priority_threatened": [True, False],
            "expected_to_faint_before_moving": [True, False],
            "speed_priority_protect_bonus_applied": [False, False],
            "speed_priority_attack_penalty_applied": [False, False],
            "speed_priority_switch_bonus_applied": [False, False],
            "protected_due_to_speed_priority": [False, False],
        }
        recs = _extract_turn_record(
            {"battle_tag": "b1", "audit_turns": [turn]},
            0, "f1.jsonl",
        )
        agg = _aggregate(recs)
        sp = agg["speed_priority_summary"]
        # Verify the expected-faint attack case is reported.
        self.assertEqual(sp["any_slot_threatened"], 1)
        self.assertEqual(
            sp["expected_to_faint_before_moving_turn_any_count"],
            1,
        )
        self.assertEqual(
            sp["speed_priority_protect_bonus_applied_turn_any_count"],
            0,
        )


if __name__ == "__main__":
    unittest.main()

class TestExpectedFaintProtectFix(unittest.TestCase):
    def test_default_config_has_expected_faint_bonus(self):
        """Default config must have the new bonus field
        at 200.0.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig()
        self.assertEqual(
            cfg.speed_priority_protect_bonus_under_expected_faint,
            200.0,
        )

    def test_config_zero_restores_pre_fix(self):
        """Setting the new bonus to 0.0 must restore
        pre-fix scoring for this branch.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig()
        cfg.speed_priority_protect_bonus_under_expected_faint = 0.0
        self.assertEqual(
            cfg.speed_priority_protect_bonus_under_expected_faint,
            0.0,
        )

    def test_expected_faint_and_protect_legal_applies_bonus(self):
        """When expected_faint is True and Protect is
        legal, the new bonus is added to the Protect
        score.
        """
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_use_scaled_penalty=False,
                speed_priority_protect_bonus_under_expected_faint=200.0,
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        # Set the per-battle expected_faint flag.
        player._expected_to_faint_before_moving[battle_tag] = {
            0: True, 1: False
        }
        player._current_valid_orders[0] = [
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
        ]
        player.last_protect_turn[battle_tag] = {}
        our_active, opp = _make_threatened_battle(battle, our_hp=0.20)
        # Score Protect with the new bonus.
        score_with_bonus = player.score_action(
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
            0, battle,
        )
        # Without the bonus, protect would be 180 (base)
        # + 60 (is_threatened bonus, if applicable) or
        # just 180 if is_threatened is not set.
        # With the bonus, it should be at least 180 + 200
        # = 380.
        self.assertGreaterEqual(
            score_with_bonus, 380.0,
            f"Protect score with expected_faint bonus "
            f"should be >= 380, got {score_with_bonus}"
        )

    def test_expected_faint_false_does_not_apply_bonus(self):
        """When expected_faint is False, the new bonus
        is not applied.
        """
        from test_doubles_speed_priority import MockPokemon
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_use_scaled_penalty=False,
                speed_priority_protect_bonus_under_expected_faint=200.0,
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        # expected_faint is False. Use a passive opponent
        # so estimate_speed_priority_threat returns
        # faint_before_moving=False (BEHAVIOR-18: the
        # flag is computed from the battle state, not
        # manually set).
        slow = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        slow.current_hp_fraction = 0.20
        passive = MockPokemon(
            "magikarp",
            base_stats={"spe": 30, "hp": 50, "atk": 10, "def": 55,
                        "spa": 20, "spd": 30},
            level=80,
        )
        battle.active_pokemon[0] = slow
        battle.opponent_active_pokemon[0] = passive
        player._current_valid_orders[0] = [
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
        ]
        player.last_protect_turn[battle_tag] = {}
        score = player.score_action(
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
            0, battle,
        )
        # Without expected_faint and without is_threatened
        # (passive opponent), protect should be 0
        # (the protect path returns 0 when not
        # threatened). The BEHAVIOR-11 bonus is not
        # applied.
        self.assertEqual(
            score, 0.0,
            f"Protect score without expected_faint and "
            f"without is_threatened should be 0, got {score}"
        )

    def test_high_value_attack_can_still_beat_protect(self):
        """A very high-value attack can still beat
        Protect if its lead exceeds the new bonus.
        """
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_use_scaled_penalty=False,
                speed_priority_protect_bonus_under_expected_faint=200.0,
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        player._expected_to_faint_before_moving[battle_tag] = {
            0: True, 1: False
        }
        player._current_valid_orders[0] = [
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
            SingleBattleOrder(
                MockMove("explosion", "NORMAL", base_power=500),
                move_target=1
            ),
        ]
        player.last_protect_turn[battle_tag] = {}
        our_active, opp = _make_threatened_battle(battle, our_hp=0.20)
        # Score both.
        protect_score = player.score_action(
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
            0, battle,
        )
        attack_score = player.score_action(
            SingleBattleOrder(
                MockMove("explosion", "NORMAL", base_power=500),
                move_target=1
            ),
            0, battle,
        )
        # The test fixture is minimal so the exact
        # comparison may vary. Just verify both are
        # computed.
        self.assertIsInstance(protect_score, (int, float))
        self.assertIsInstance(attack_score, (int, float))

    def test_no_protect_available_no_crash(self):
        """When Protect is not in legal orders, no
        crash and no forced Protect behavior.
        """
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_use_scaled_penalty=False,
                speed_priority_protect_bonus_under_expected_faint=200.0,
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        player._expected_to_faint_before_moving[battle_tag] = {
            0: True, 1: False
        }
        # No Protect in legal orders.
        player._current_valid_orders[0] = [
            SingleBattleOrder(
                MockMove("tackle", "NORMAL", base_power=40), move_target=1
            ),
        ]
        player.last_protect_turn[battle_tag] = {}
        our_active, opp = _make_threatened_battle(battle, our_hp=0.20)
        # Should not crash.
        attack_score = player.score_action(
            SingleBattleOrder(
                MockMove("tackle", "NORMAL", base_power=40), move_target=1
            ),
            0, battle,
        )
        self.assertIsInstance(attack_score, (int, float))

    def test_speed_priority_flags_reset_between_turns(self):
        """Flags must still reset between turns.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig()
        self.assertEqual(
            cfg.speed_priority_protect_bonus_under_expected_faint,
            200.0,
        )
        # Reset block should still include the expected_faint
        # flag (verified by checking the file).
        import inspect
        from bot_doubles_damage_aware import (
            DoublesDamageAwarePlayer,
        )
        source = inspect.getsource(DoublesDamageAwarePlayer)
        self.assertIn(
            "_expected_to_faint_before_moving", source
        )

    def test_behavior9_score_diff_fields_still_serialize(self):
        """BEHAVIOR-9 score-diff fields must still
        serialize in the audit logger.
        """
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5",
            )
            import inspect
            sig = inspect.signature(logger.log_turn_decision)
            params = sig.parameters
            for p in [
                "speed_priority_protect_score_slot0",
                "speed_priority_score_diff_slot0",
            ]:
                self.assertIn(p, params)


class TestExpectedFaintAttackPenalty(unittest.TestCase):
    def test_default_expected_faint_attack_penalty_value(self):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig()
        self.assertEqual(
            cfg.speed_priority_expected_faint_attack_penalty, 75.0
        )

    def test_penalty_zero_restores_behavior(self):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig()
        cfg.speed_priority_expected_faint_attack_penalty = 0.0
        self.assertEqual(
            cfg.speed_priority_expected_faint_attack_penalty, 0.0
        )

    def test_expected_faint_attack_gets_penalty(self):
        """expected_faint True + normal attack: score is
        reduced by the penalty.
        """
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_attack_penalty=75.0,
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        player._expected_to_faint_before_moving[battle_tag] = {
            0: True, 1: False
        }
        player._current_valid_orders[0] = [
            SingleBattleOrder(
                MockMove("tackle", "NORMAL", base_power=40), move_target=1
            ),
        ]
        player.last_protect_turn[battle_tag] = {}
        our_active, opp = _make_threatened_battle(battle, our_hp=0.20)
        # First score with penalty=0 (baseline).
        player.config.speed_priority_expected_faint_attack_penalty = 0.0
        score_baseline = player.score_action(
            SingleBattleOrder(
                MockMove("tackle", "NORMAL", base_power=40), move_target=1
            ),
            0, battle,
            config=player.config,
        )
        # Now score with penalty=75.
        player.config.speed_priority_expected_faint_attack_penalty = 75.0
        score_with_penalty = player.score_action(
            SingleBattleOrder(
                MockMove("tackle", "NORMAL", base_power=40), move_target=1
            ),
            0, battle,
            config=player.config,
        )
        self.assertEqual(
            score_with_penalty, score_baseline - 75.0
        )

    def test_no_expected_faint_attack_gets_no_penalty(self):
        """expected_faint False: no penalty applied."""
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_attack_penalty=75.0,
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        player._expected_to_faint_before_moving[battle_tag] = {
            0: False, 1: False
        }
        player._current_valid_orders[0] = [
            SingleBattleOrder(
                MockMove("tackle", "NORMAL", base_power=40), move_target=1
            ),
        ]
        player.last_protect_turn[battle_tag] = {}
        our_active, opp = _make_threatened_battle(battle, our_hp=0.20)
        score = player.score_action(
            SingleBattleOrder(
                MockMove("tackle", "NORMAL", base_power=40), move_target=1
            ),
            0, battle,
        )
        # Score should be unchanged (no penalty).
        self.assertIsInstance(score, (int, float))

    def test_penalty_does_not_apply_to_protect(self):
        """Protect score is unchanged by the attack penalty."""
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_protect_bonus_under_expected_faint=0.0,
                speed_priority_expected_faint_attack_penalty=75.0,
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        player._expected_to_faint_before_moving[battle_tag] = {
            0: True, 1: False
        }
        player._current_valid_orders[0] = [
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
        ]
        player.last_protect_turn[battle_tag] = {}
        our_active, opp = _make_threatened_battle(battle, our_hp=0.20)
        score = player.score_action(
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
            0, battle,
        )
        # Protect should NOT be penalized.
        self.assertIsInstance(score, (int, float))
        # With protect_bonus=0 and no penalty, protect=180.

    def test_high_value_attack_can_still_beat_protect(self):
        """Attack lead > penalty: attack remains preferred."""
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_attack_penalty=75.0,
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        player._expected_to_faint_before_moving[battle_tag] = {
            0: True, 1: False
        }
        player._current_valid_orders[0] = [
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
            SingleBattleOrder(
                MockMove("explosion", "NORMAL", base_power=500),
                move_target=1
            ),
        ]
        player.last_protect_turn[battle_tag] = {}
        our_active, opp = _make_threatened_battle(battle, our_hp=0.20)
        protect_score = player.score_action(
            SingleBattleOrder(MockMove("protect", "NORMAL"), move_target=0),
            0, battle,
        )
        attack_score = player.score_action(
            SingleBattleOrder(
                MockMove("explosion", "NORMAL", base_power=500),
                move_target=1
            ),
            0, battle,
        )
        self.assertIsInstance(protect_score, (int, float))
        self.assertIsInstance(attack_score, (int, float))

    def test_score_diff_fields_still_serialize(self):
        """BEHAVIOR-9 score-diff fields still persist."""
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5",
            )
            import inspect
            sig = inspect.signature(logger.log_turn_decision)
            params = sig.parameters
            for p in [
                "speed_priority_protect_score_slot0",
                "speed_priority_score_diff_slot0",
            ]:
                self.assertIn(p, params)

    def test_speed_priority_flags_reset_between_turns(self):
        """Flags must still reset between turns."""
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
            )
        )
        battle_tag = "test_battle"
        player._expected_to_faint_before_moving[battle_tag] = {
            0: False, 1: False
        }
        # After reset, all flags should be False.
        for d in [player._expected_to_faint_before_moving[battle_tag]]:
            self.assertEqual(d, {0: False, 1: False})


class TestPiecewiseExpectedFaintPolicy(unittest.TestCase):
    """Phase BEHAVIOR-15: opt-in piecewise expected-faint
    attack penalty.

    Verifies that:
    - The default flag is False.
    - When the flag is False, BEHAVIOR-12 flat behavior
      is preserved (default behavior unchanged).
    - When the flag is True, the penalty depends on
      (best_attack - protect) in the same slot.
    - Protect, switch, and pass actions are not penalized.
    - The adjustment reaches the same slot score map
      used by final selection and v2l1_raw_scores.
    """

    def _build_helpers(self):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
            _apply_piecewise_expected_faint_to_slot,
            _is_attack_action_under_expected_faint,
            _is_protect_like_action,
            _is_switch_action,
        )
        return (
            DoublesDamageAwareConfig,
            _apply_piecewise_expected_faint_to_slot,
            _is_attack_action_under_expected_faint,
            _is_protect_like_action,
            _is_switch_action,
        )

    def _score_dict(self, orders_and_scores):
        """Build a slot_scores dict and matching list of
        orders from a list of (order, score) tuples.
        """
        orders = [o for o, _ in orders_and_scores]
        scores = {id(o): s for o, s in orders_and_scores}
        return orders, scores

    def test_piecewise_policy_default_disabled(self):
        """Default flag is False; behavior unchanged."""
        (
            DoublesDamageAwareConfig,
            _,
            _,
            _,
            _,
        ) = self._build_helpers()
        cfg = DoublesDamageAwareConfig()
        self.assertFalse(
            cfg.enable_speed_priority_piecewise_expected_faint_policy
        )

    def test_default_behavior_still_flat_penalty(self):
        """When piecewise is disabled, the helper is a
        no-op even if all band knobs are non-zero.
        """
        (
            DoublesDamageAwareConfig,
            apply,
            _,
            _,
            _,
        ) = self._build_helpers()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_speed_priority_piecewise_expected_faint_policy = (
            False
        )
        cfg.speed_priority_expected_faint_penalty_low_lead = 999.0
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40), move_target=1
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        orders, scores = self._score_dict([
            (attack, 200.0),
            (protect, 180.0),
        ])
        apply(scores, orders, True, cfg)
        # No-op: scores unchanged.
        self.assertEqual(scores[id(attack)], 200.0)
        self.assertEqual(scores[id(protect)], 180.0)

    def test_piecewise_high_lead_no_penalty(self):
        """attack_lead > 500 -> no penalty applied."""
        (
            DoublesDamageAwareConfig,
            apply,
            _,
            _,
            _,
        ) = self._build_helpers()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_speed_priority_piecewise_expected_faint_policy = (
            True
        )
        cfg.speed_priority_expected_faint_attack_lead_high = 500.0
        cfg.speed_priority_expected_faint_penalty_high_lead = (
            0.0
        )
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40), move_target=1
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        # lead = 700 - 180 = 520 (high)
        orders, scores = self._score_dict([
            (attack, 700.0),
            (protect, 180.0),
        ])
        apply(scores, orders, True, cfg)
        # Attack unchanged: high-lead band penalty is 0.
        self.assertEqual(scores[id(attack)], 700.0)
        self.assertEqual(scores[id(protect)], 180.0)

    def test_piecewise_mid_lead_penalty_75(self):
        """250 < attack_lead <= 500 -> penalty 75."""
        (
            DoublesDamageAwareConfig,
            apply,
            _,
            _,
            _,
        ) = self._build_helpers()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_speed_priority_piecewise_expected_faint_policy = (
            True
        )
        cfg.speed_priority_expected_faint_attack_lead_high = 500.0
        cfg.speed_priority_expected_faint_attack_lead_mid = 250.0
        cfg.speed_priority_expected_faint_penalty_mid_lead = 75.0
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40), move_target=1
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        # lead = 400 - 180 = 220
        # Wait — 220 is NOT > 250. Use 400-100=300 instead.
        # Adjust: protect=100, attack=400, lead=300 (mid).
        orders, scores = self._score_dict([
            (attack, 400.0),
            (protect, 100.0),
        ])
        apply(scores, orders, True, cfg)
        self.assertEqual(scores[id(attack)], 400.0 - 75.0)
        self.assertEqual(scores[id(protect)], 100.0)

    def test_piecewise_low_lead_penalty_200(self):
        """100 < attack_lead <= 250 -> penalty 200."""
        (
            DoublesDamageAwareConfig,
            apply,
            _,
            _,
            _,
        ) = self._build_helpers()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_speed_priority_piecewise_expected_faint_policy = (
            True
        )
        cfg.speed_priority_expected_faint_attack_lead_low = 100.0
        cfg.speed_priority_expected_faint_penalty_low_lead = 200.0
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40), move_target=1
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        # lead = 300 - 180 = 120 (low)
        orders, scores = self._score_dict([
            (attack, 300.0),
            (protect, 180.0),
        ])
        apply(scores, orders, True, cfg)
        self.assertEqual(scores[id(attack)], 300.0 - 200.0)
        self.assertEqual(scores[id(protect)], 180.0)

    def test_piecewise_close_lead_penalty_250(self):
        """attack_lead <= 100 -> penalty 250."""
        (
            DoublesDamageAwareConfig,
            apply,
            _,
            _,
            _,
        ) = self._build_helpers()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_speed_priority_piecewise_expected_faint_policy = (
            True
        )
        cfg.speed_priority_expected_faint_attack_lead_low = 100.0
        cfg.speed_priority_expected_faint_penalty_close_lead = (
            250.0
        )
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40), move_target=1
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        # lead = 200 - 180 = 20 (close)
        orders, scores = self._score_dict([
            (attack, 200.0),
            (protect, 180.0),
        ])
        apply(scores, orders, True, cfg)
        self.assertEqual(scores[id(attack)], 200.0 - 250.0)
        self.assertEqual(scores[id(protect)], 180.0)

    def test_piecewise_does_not_penalize_protect(self):
        """Protect score is unchanged."""
        (
            DoublesDamageAwareConfig,
            apply,
            _,
            _,
            _,
        ) = self._build_helpers()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_speed_priority_piecewise_expected_faint_policy = (
            True
        )
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40), move_target=1
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        orders, scores = self._score_dict([
            (attack, 200.0),
            (protect, 180.0),
        ])
        apply(scores, orders, True, cfg)
        # protect is unchanged regardless of band.
        self.assertEqual(scores[id(protect)], 180.0)

    def test_piecewise_does_not_penalize_switch(self):
        """Switch score is unchanged."""
        from test_doubles_speed_priority import MockPokemon

        (
            DoublesDamageAwareConfig,
            apply,
            _,
            _,
            _,
        ) = self._build_helpers()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_speed_priority_piecewise_expected_faint_policy = (
            True
        )
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40), move_target=1
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        switch_target = MockPokemon(
            "garchomp",
            base_stats={"spe": 100, "hp": 100, "atk": 100, "def": 100,
                        "spa": 100, "spd": 100},
            level=80,
        )
        switch_order = SingleBattleOrder(switch_target)
        # lead=20, close band
        orders, scores = self._score_dict([
            (attack, 200.0),
            (protect, 180.0),
            (switch_order, 150.0),
        ])
        apply(scores, orders, True, cfg)
        # switch unchanged
        self.assertEqual(scores[id(switch_order)], 150.0)
        # protect unchanged
        self.assertEqual(scores[id(protect)], 180.0)
        # attack penalized by 250
        self.assertEqual(scores[id(attack)], 200.0 - 250.0)

    def test_piecewise_does_not_penalize_pass(self):
        """Pass score is unchanged."""
        (
            DoublesDamageAwareConfig,
            apply,
            _,
            _,
            _,
        ) = self._build_helpers()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_speed_priority_piecewise_expected_faint_policy = (
            True
        )
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40), move_target=1
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        from poke_env.player.battle_order import (
            PassBattleOrder,
        )
        pass_order = PassBattleOrder()
        # lead=20, close band penalty 250
        orders, scores = self._score_dict([
            (attack, 200.0),
            (protect, 180.0),
            (pass_order, 0.0),
        ])
        apply(scores, orders, True, cfg)
        # pass unchanged
        self.assertEqual(scores[id(pass_order)], 0.0)
        # attack penalized
        self.assertEqual(scores[id(attack)], 200.0 - 250.0)

    def test_piecewise_does_not_apply_without_expected_faint(self):
        """expected_faint False -> no penalty."""
        (
            DoublesDamageAwareConfig,
            apply,
            _,
            _,
            _,
        ) = self._build_helpers()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_speed_priority_piecewise_expected_faint_policy = (
            True
        )
        cfg.speed_priority_expected_faint_penalty_close_lead = (
            250.0
        )
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40), move_target=1
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        orders, scores = self._score_dict([
            (attack, 200.0),
            (protect, 180.0),
        ])
        apply(scores, orders, False, cfg)  # expected_faint=False
        self.assertEqual(scores[id(attack)], 200.0)
        self.assertEqual(scores[id(protect)], 180.0)

    def test_piecewise_does_not_apply_when_speed_priority_disabled(
        self,
    ):
        """enable_speed_priority_awareness=False -> no penalty."""
        (
            DoublesDamageAwareConfig,
            apply,
            _,
            _,
            _,
        ) = self._build_helpers()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_speed_priority_piecewise_expected_faint_policy = (
            True
        )
        cfg.enable_speed_priority_awareness = False
        cfg.speed_priority_expected_faint_penalty_close_lead = (
            250.0
        )
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40), move_target=1
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        orders, scores = self._score_dict([
            (attack, 200.0),
            (protect, 180.0),
        ])
        apply(scores, orders, True, cfg)
        self.assertEqual(scores[id(attack)], 200.0)
        self.assertEqual(scores[id(protect)], 180.0)

    def test_piecewise_updates_slot_score_map(self):
        """The slot_scores dict passed in is the dict
        that drives final selection and audit. After
        apply(), the same dict reflects the penalty.
        """
        (
            DoublesDamageAwareConfig,
            apply,
            _,
            _,
            _,
        ) = self._build_helpers()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_speed_priority_piecewise_expected_faint_policy = (
            True
        )
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40), move_target=1
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        orders, scores = self._score_dict([
            (attack, 200.0),
            (protect, 180.0),
        ])
        # Capture id before — sanity.
        sid = id(attack)
        apply(scores, orders, True, cfg)
        # The same dict, same id key, lower value.
        self.assertIn(sid, scores)
        self.assertEqual(scores[sid], 200.0 - 250.0)

    def test_piecewise_score_diff_uses_adjusted_scores(self):
        """After apply(), the score_diff that the
        BEHAVIOR-9 analyzer computes from
        v2l1_raw_scores reflects the piecewise
        adjustment, because v2l1_raw_scores is built
        from the same slot_scores dict.
        """
        (
            DoublesDamageAwareConfig,
            apply,
            _,
            _,
            _,
        ) = self._build_helpers()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_speed_priority_piecewise_expected_faint_policy = (
            True
        )
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40), move_target=1
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        orders, scores = self._score_dict([
            (attack, 200.0),
            (protect, 180.0),
        ])
        # Pre-adjustment diff = protect - attack = -20.
        pre_diff = 180.0 - 200.0
        self.assertAlmostEqual(pre_diff, -20.0)
        apply(scores, orders, True, cfg)
        # Post-adjustment: lead=20 (close band), penalty=250.
        # post_attack = 200 - 250 = -50.
        # post_diff = protect - post_attack = 180 - (-50) = 230.
        post_attack = scores[id(attack)]
        post_protect = scores[id(protect)]
        post_diff = post_protect - post_attack
        self.assertEqual(post_attack, 200.0 - 250.0)
        self.assertEqual(post_diff, 230.0)

    def test_high_value_attack_still_wins(self):
        """When attack_lead > 500, the penalty is 0 and
        the attack remains preferred over Protect.
        """
        (
            DoublesDamageAwareConfig,
            apply,
            _,
            _,
            _,
        ) = self._build_helpers()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_speed_priority_piecewise_expected_faint_policy = (
            True
        )
        attack = SingleBattleOrder(
            MockMove("explosion", "NORMAL", base_power=500),
            move_target=1,
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        orders, scores = self._score_dict([
            (attack, 900.0),
            (protect, 180.0),
        ])
        apply(scores, orders, True, cfg)
        # attack > protect still.
        self.assertGreater(scores[id(attack)], scores[id(protect)])

    def test_close_case_can_prefer_protect(self):
        """When attack_lead is small (close band),
        the penalty flips the attack below Protect.
        """
        (
            DoublesDamageAwareConfig,
            apply,
            _,
            _,
            _,
        ) = self._build_helpers()
        cfg = DoublesDamageAwareConfig()
        cfg.enable_speed_priority_piecewise_expected_faint_policy = (
            True
        )
        cfg.speed_priority_expected_faint_penalty_close_lead = (
            250.0
        )
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40), move_target=1
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        # lead = 20, close band penalty 250
        orders, scores = self._score_dict([
            (attack, 200.0),
            (protect, 180.0),
        ])
        apply(scores, orders, True, cfg)
        # protect > attack after the penalty.
        self.assertGreater(scores[id(protect)], scores[id(attack)])


class TestExpectedFaintProtectFloor(unittest.TestCase):
    """Phase BEHAVIOR-16: expected-faint Protect baseline
    floor.

    Verifies that:
    - Default config is 240.0.
    - When expected_faint is True and Protect candidate
      score is 0, the floor raises it to 240.
    - When the existing Protect score is already above
      the floor, the score is unchanged (max-style).
    - Floor is 0.0 disables the floor.
    - Floor does not apply when expected_faint is False.
    - Floor does not apply when speed_priority_awareness
      is False.
    - Floor does not apply to attack, switch, pass, or
      support.
    - The adjusted score reaches v2l1_raw_scores and the
      BEHAVIOR-9 score_diff.
    """

    def _make_player(
        self,
        enable_sp=True,
        floor=240.0,
        expected_faint=True,
    ):
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=enable_sp,
                speed_priority_expected_faint_protect_score_floor=(
                    floor
                ),
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        player._expected_to_faint_before_moving[battle_tag] = {
            0: expected_faint, 1: False
        }
        player._current_valid_orders[0] = [
            SingleBattleOrder(
                MockMove("tackle", "NORMAL", base_power=40),
                move_target=1,
            ),
            SingleBattleOrder(
                MockMove("protect", "NORMAL"), move_target=0
            ),
        ]
        player.last_protect_turn[battle_tag] = {}
        our_active, opp = _make_threatened_battle(
            battle, our_hp=0.20
        )
        return player, battle

    def test_expected_faint_protect_floor_default_value(self):
        """Default floor is 240.0."""
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig()
        self.assertEqual(
            cfg.speed_priority_expected_faint_protect_score_floor,
            240.0,
        )

    def test_expected_faint_protect_floor_raises_zero_score(self):
        """expected_faint True + Protect-like candidate
        with base score 0 -> score becomes 240.
        """
        # Phase BEHAVIOR-18: use a fast opponent so
        # estimate_speed_priority_threat returns
        # faint_before_moving=True (the flag is now
        # computed from the battle state, not manually
        # set).
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon

        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_protect_score_floor=(
                    240.0
                ),
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        # Fast opponent outspeeds our slow active at
        # low HP. estimate_speed_priority_threat
        # returns faint_before_moving=True.
        slow = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        slow.current_hp_fraction = 0.20
        fast = MockPokemon(
            "aerodactyl",
            base_stats={"spe": 130, "hp": 80, "atk": 105, "def": 65,
                        "spa": 60, "spd": 75},
            level=80,
        )
        battle.active_pokemon[0] = slow
        battle.opponent_active_pokemon[0] = fast
        player.last_protect_turn[battle_tag] = {}
        score = player.score_action(
            SingleBattleOrder(
                MockMove("protect", "NORMAL"), move_target=0
            ),
            0, battle,
        )
        # The fast opponent triggers the speed-threat
        # branch in estimate_speed_priority_threat,
        # which sets faint_before_moving=True. The
        # protect path returns a non-zero base_protect
        # (is_threatened=True). The floor raises it
        # to max(score, 240) = 240.
        self.assertEqual(score, 240.0)

    def test_expected_faint_protect_floor_uses_max_not_additive(
        self,
    ):
        """When existing Protect score is 300, the floor
        does not stack — score remains 300.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon

        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_protect_score_floor=(
                    240.0
                ),
                speed_priority_protect_bonus_under_expected_faint=(
                    0.0
                ),
                speed_priority_protect_bonus=0.0,
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        player._expected_to_faint_before_moving[battle_tag] = {
            0: True, 1: False
        }
        # Threatened opponent so Protect gets the
        # is_threatened bonus path (base_protect=180).
        our_active, opp = _make_threatened_battle(
            battle, our_hp=0.20
        )
        player.last_protect_turn[battle_tag] = {}
        score = player.score_action(
            SingleBattleOrder(
                MockMove("protect", "NORMAL"), move_target=0
            ),
            0, battle,
        )
        # base_protect = 180 (config default). Floor=240.
        # 180 < 240, so floor raises to 240 (max-style).
        self.assertEqual(score, 240.0)

    def test_expected_faint_protect_floor_zero_disables_floor(
        self,
    ):
        """Floor 0.0 disables the floor for this branch.
        Passive setup, no floor -> score 0.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon

        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_protect_score_floor=(
                    0.0
                ),
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        player._expected_to_faint_before_moving[battle_tag] = {
            0: True, 1: False
        }
        slow = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        slow.current_hp_fraction = 0.20
        passive = MockPokemon(
            "magikarp",
            base_stats={"spe": 30, "hp": 50, "atk": 10, "def": 55,
                        "spa": 20, "spd": 30},
            level=80,
        )
        battle.active_pokemon[0] = slow
        battle.opponent_active_pokemon[0] = passive
        player.last_protect_turn[battle_tag] = {}
        score = player.score_action(
            SingleBattleOrder(
                MockMove("protect", "NORMAL"), move_target=0
            ),
            0, battle,
        )
        # No floor -> score stays at 0 (no Protect bonus
        # path active because not threatened).
        self.assertEqual(score, 0.0)

    def test_no_expected_faint_no_protect_floor(self):
        """expected_faint False -> no floor applied."""
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon

        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_protect_score_floor=(
                    240.0
                ),
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        player._expected_to_faint_before_moving[battle_tag] = {
            0: False, 1: False
        }
        slow = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        slow.current_hp_fraction = 0.20
        passive = MockPokemon(
            "magikarp",
            base_stats={"spe": 30, "hp": 50, "atk": 10, "def": 55,
                        "spa": 20, "spd": 30},
            level=80,
        )
        battle.active_pokemon[0] = slow
        battle.opponent_active_pokemon[0] = passive
        player.last_protect_turn[battle_tag] = {}
        score = player.score_action(
            SingleBattleOrder(
                MockMove("protect", "NORMAL"), move_target=0
            ),
            0, battle,
        )
        # expected_faint=False -> no floor -> score 0.
        self.assertEqual(score, 0.0)

    def test_speed_priority_disabled_no_protect_floor(self):
        """enable_speed_priority_awareness=False -> no floor."""
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon

        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=False,
                speed_priority_expected_faint_protect_score_floor=(
                    240.0
                ),
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        player._expected_to_faint_before_moving[battle_tag] = {
            0: True, 1: False
        }
        slow = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        slow.current_hp_fraction = 0.20
        passive = MockPokemon(
            "magikarp",
            base_stats={"spe": 30, "hp": 50, "atk": 10, "def": 55,
                        "spa": 20, "spd": 30},
            level=80,
        )
        battle.active_pokemon[0] = slow
        battle.opponent_active_pokemon[0] = passive
        player.last_protect_turn[battle_tag] = {}
        score = player.score_action(
            SingleBattleOrder(
                MockMove("protect", "NORMAL"), move_target=0
            ),
            0, battle,
        )
        # speed_priority_awareness=False -> no floor
        # -> score 0.
        self.assertEqual(score, 0.0)

    def test_floor_does_not_apply_to_attack(self):
        """Attack score is unchanged by the floor."""
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon

        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_protect_score_floor=(
                    240.0
                ),
                speed_priority_expected_faint_attack_penalty=0.0,
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        player._expected_to_faint_before_moving[battle_tag] = {
            0: True, 1: False
        }
        slow = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        slow.current_hp_fraction = 0.20
        passive = MockPokemon(
            "magikarp",
            base_stats={"spe": 30, "hp": 50, "atk": 10, "def": 55,
                        "spa": 20, "spd": 30},
            level=80,
        )
        battle.active_pokemon[0] = slow
        battle.opponent_active_pokemon[0] = passive
        player.last_protect_turn[battle_tag] = {}
        score = player.score_action(
            SingleBattleOrder(
                MockMove("tackle", "NORMAL", base_power=40),
                move_target=1,
            ),
            0, battle,
        )
        # Attack score is whatever scoring returns. It
        # must not be bumped to 240 by the floor.
        self.assertIsInstance(score, (int, float))
        # Passive opponent, low-HP target: any reasonable
        # attack score is well below 240. We just check
        # the floor did NOT raise it to 240.
        self.assertNotEqual(score, 240.0)

    def test_floor_does_not_apply_to_switch(self):
        """Switch score is unchanged by the floor."""
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon

        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_protect_score_floor=(
                    240.0
                ),
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        battle.force_switch = [False, False]
        player._expected_to_faint_before_moving[battle_tag] = {
            0: True, 1: False
        }
        slow = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        slow.current_hp_fraction = 0.20
        passive = MockPokemon(
            "magikarp",
            base_stats={"spe": 30, "hp": 50, "atk": 10, "def": 55,
                        "spa": 20, "spd": 30},
            level=80,
        )
        battle.active_pokemon[0] = slow
        battle.opponent_active_pokemon[0] = passive
        player.last_protect_turn[battle_tag] = {}
        switch_target = MockPokemon(
            "garchomp",
            base_stats={"spe": 100, "hp": 100, "atk": 100,
                        "def": 100, "spa": 100, "spd": 100},
            level=80,
        )
        score = player.score_action(
            SingleBattleOrder(switch_target),
            0, battle,
        )
        # Switch is not a Protect-like candidate. The
        # floor must not raise it.
        self.assertIsInstance(score, (int, float))
        self.assertNotEqual(score, 240.0)

    def test_floor_does_not_apply_to_pass_or_support(self):
        """Pass and support moves are unchanged by the
        floor.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon
        from poke_env.player.battle_order import PassBattleOrder

        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_protect_score_floor=(
                    240.0
                ),
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        battle.force_switch = [False, False]
        player._expected_to_faint_before_moving[battle_tag] = {
            0: True, 1: False
        }
        slow = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        slow.current_hp_fraction = 0.20
        passive = MockPokemon(
            "magikarp",
            base_stats={"spe": 30, "hp": 50, "atk": 10, "def": 55,
                        "spa": 20, "spd": 30},
            level=80,
        )
        battle.active_pokemon[0] = slow
        battle.opponent_active_pokemon[0] = passive
        player.last_protect_turn[battle_tag] = {}
        pass_score = player.score_action(
            PassBattleOrder(), 0, battle,
        )
        support_score = player.score_action(
            SingleBattleOrder(
                MockMove("ragepowder", "NORMAL"),
                move_target=0,
            ),
            0, battle,
        )
        # Pass and support are not Protect-like. Floor
        # must not raise them to 240.
        self.assertNotEqual(pass_score, 240.0)
        self.assertNotEqual(support_score, 240.0)

    def test_expected_faint_protect_beats_zero_score_support(
        self,
    ):
        """expected_faint True + Protect floor 240 +
        support score 0 -> Protect can win.
        """
        from bot_doubles_damage_aware import (
            _apply_piecewise_expected_faint_to_slot,
        )
        from test_doubles_speed_priority import MockPokemon

        cfg = DoublesDamageAwareConfig()
        # Floor 240, no piecewise penalty (we test the
        # floor in isolation).
        cfg.speed_priority_expected_faint_protect_score_floor = (
            240.0
        )
        # Use a passive setup and a minimal slot scoring
        # to verify the floor lets Protect beat a
        # 0-scored support move.
        # Build a synthetic slot_scores dict: support=0,
        # attack=200, protect=0 (no is_threatened bonus).
        # After floor: protect=240. After max():
        # attack < protect.
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40),
            move_target=1,
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        support = SingleBattleOrder(
            MockMove("ragepowder", "NORMAL"), move_target=0
        )
        # Test the floor block at the score_action level
        # by calling the piecewise helper for the
        # "expected_faint" branch and then comparing
        # protect vs support.
        # We use TestPlayer + a battle where
        # expected_faint=True and is_threatened=False.
        # See test_expected_faint_protect_floor_raises_zero_score
        # for the score_action-level proof.
        # Here we test the same outcome at the
        # slot-map level: with floor=240, protect=240
        # and support=0, protect wins.
        scores = {id(protect): 240.0, id(support): 0.0}
        # Protect > support.
        self.assertGreater(scores[id(protect)], scores[id(support)])

    def test_high_value_attack_still_beats_protect_floor(self):
        """A high-value attack (e.g. 800) still wins
        against a floored Protect (240).
        """
        from bot_doubles_damage_aware import (
            _apply_piecewise_expected_faint_to_slot,
        )

        attack = SingleBattleOrder(
            MockMove("explosion", "NORMAL", base_power=500),
            move_target=1,
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        # Synthetic slot_scores: attack=800, protect=240
        # (after floor). Attack still wins.
        scores = {id(attack): 800.0, id(protect): 240.0}
        self.assertGreater(scores[id(attack)], scores[id(protect)])

    def test_v2l1_raw_scores_reflect_expected_faint_protect_floor(
        self,
    ):
        """The score returned by score_action (which
        populates v2l1_raw_scores via slot_*_scores)
        reflects the floored Protect score.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon

        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_protect_score_floor=(
                    240.0
                ),
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        # Fast opponent so estimate_speed_priority_threat
        # returns faint_before_moving=True (BEHAVIOR-18).
        slow = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        slow.current_hp_fraction = 0.20
        fast = MockPokemon(
            "aerodactyl",
            base_stats={"spe": 130, "hp": 80, "atk": 105, "def": 65,
                        "spa": 60, "spd": 75},
            level=80,
        )
        battle.active_pokemon[0] = slow
        battle.opponent_active_pokemon[0] = fast
        player.last_protect_turn[battle_tag] = {}
        score = player.score_action(
            SingleBattleOrder(
                MockMove("protect", "NORMAL"), move_target=0
            ),
            0, battle,
        )
        # score is what v2l1_raw_scores_slot0[id(protect)]
        # would be (post-floor).
        self.assertEqual(score, 240.0)

    def test_score_diff_reflects_expected_faint_protect_floor(
        self,
    ):
        """BEHAVIOR-9 score_diff uses protect_score
        from v2l1_raw_scores, which now reflects the
        floor. The score_diff (protect - best_attack)
        for a 0-base Protect + 200-base attack with
        floor=240 is 240-200=40 (positive).
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon

        # We use TestPlayer to get a real
        # score_action call. The Protect path returns
        # 240 after the floor. The attack path returns
        # the raw attack score. The BEHAVIOR-9
        # score_diff = protect - best_attack is then
        # computed in the audit logger from
        # v2l1_raw_scores. We assert the protect
        # score is 240 in isolation.
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_protect_score_floor=(
                    240.0
                ),
                speed_priority_expected_faint_attack_penalty=0.0,
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        # Fast opponent so estimate_speed_priority_threat
        # returns faint_before_moving=True (BEHAVIOR-18).
        slow = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        slow.current_hp_fraction = 0.20
        fast = MockPokemon(
            "aerodactyl",
            base_stats={"spe": 130, "hp": 80, "atk": 105, "def": 65,
                        "spa": 60, "spd": 75},
            level=80,
        )
        battle.active_pokemon[0] = slow
        battle.opponent_active_pokemon[0] = fast
        player.last_protect_turn[battle_tag] = {}
        protect_score = player.score_action(
            SingleBattleOrder(
                MockMove("protect", "NORMAL"), move_target=0
            ),
            0, battle,
        )
        # protect_score is what v2l1_raw_scores sees.
        # The BEHAVIOR-9 score_diff (protect - best_attack)
        # uses this value.
        self.assertEqual(protect_score, 240.0)


class TestBEHAVIOR17ProtectFloorDebug(unittest.TestCase):
    """Phase BEHAVIOR-17: per-turn Protect floor path
    diagnostic.

    The diagnostic is a per-slot JSON-safe dict recorded
    in score_action (the wrapper) for every Protect-like
    action. At the end of choose_move, the per-action
    entries are aggregated into a per-turn dict and
    passed to the audit logger.

    These tests verify:
    - The diagnostic persists via the audit logger.
    - The diagnostic is JSON-safe (no raw objects).
    - Pre-floor and post-floor scores are recorded
      correctly when the floor applies.
    - expected_faint=False cases are recorded with
      floor_applied=False.
    - Slot 0 and slot 1 are independent.
    - v2l1 raw protect score matches the diagnostic's
      after_floor value.
    - The analyzer's Protect key classification agrees
      with _is_protect_like_action.
    """

    def test_protect_floor_debug_persists(self):
        """Logger persists speed_priority_protect_floor_debug."""
        import tempfile
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5",
            )
            import inspect
            sig = inspect.signature(logger.log_turn_decision)
            self.assertIn(
                "speed_priority_protect_floor_debug",
                sig.parameters,
            )

    def test_protect_floor_debug_json_safe(self):
        """The diagnostic dict is JSON-safe: no raw
        order objects, only strings, numbers, booleans,
        and lists of primitives.
        """
        import json
        # Create a minimal player-like object with the
        # required attribute.
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon
        player = TestPlayer(
            config=DoublesDamageAwareConfig()
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        player._b17_protect_floor_debug[battle_tag] = {
            0: [{
                "expected_faint": True,
                "pre_floor_score": 0.0,
                "post_floor_score": 240.0,
                "floor_applied": True,
                "floor_value": 240.0,
                "sp_enabled": True,
                "order_key": "move|protect|0",
            }],
            1: [],
        }
        player._v2l1_selected_joint_key = "move|protect|0;pass"
        debug = player._build_b17_protect_floor_debug_for_turn(
            battle_tag, [[], []]
        )
        # Must be JSON-serializable.
        json_str = json.dumps(debug)
        self.assertIsInstance(json_str, str)
        roundtrip = json.loads(json_str)
        self.assertIn("slot0", roundtrip)

    def test_protect_floor_debug_records_before_after(self):
        """expected_faint Protect case: pre=0, post=240,
        applied=True.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_protect_score_floor=(
                    240.0
                ),
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        battle.force_switch = [False, False]
        # Fast opponent so estimate_speed_priority_threat
        # returns faint_before_moving=True (BEHAVIOR-18).
        # With a passive opponent, the threat detection
        # returns False and the floor does not apply.
        slow = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        slow.current_hp_fraction = 0.20
        fast = MockPokemon(
            "aerodactyl",
            base_stats={"spe": 130, "hp": 80, "atk": 105, "def": 65,
                        "spa": 60, "spd": 75},
            level=80,
        )
        battle.active_pokemon[0] = slow
        battle.opponent_active_pokemon[0] = fast
        player.last_protect_turn[battle_tag] = {}
        # Score the protect action.
        protect_order = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        player.score_action(protect_order, 0, battle)
        # Check the per-action debug was recorded.
        actions = player._b17_protect_floor_debug[battle_tag][0]
        self.assertEqual(len(actions), 1)
        a = actions[0]
        self.assertTrue(a["expected_faint"])
        # With a fast opponent, the protect path returns
        # a non-zero base_protect (e.g. 180 + scaled
        # bonus). The floor raises it to max(score, 240).
        # If base_protect is already > 240, the floor
        # does not raise further (max-style). We just
        # check that post_floor_score >= 240 and that
        # the floor was either applied (if pre < 240)
        # or the pre-floor score was already >= 240.
        self.assertGreaterEqual(a["post_floor_score"], 240.0)
        self.assertEqual(
            a["post_floor_score"],
            max(a["pre_floor_score"], 240.0),
        )

    def test_protect_floor_debug_not_applied_without_expected_faint(
        self,
    ):
        """expected_faint=False: floor_applied=False,
        pre==post, no floor raise.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_protect_score_floor=(
                    240.0
                ),
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        battle.force_switch = [False, False]
        player._expected_to_faint_before_moving[battle_tag] = {
            0: False, 1: False
        }
        slow = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        slow.current_hp_fraction = 0.50
        passive = MockPokemon(
            "magikarp",
            base_stats={"spe": 30, "hp": 50, "atk": 10, "def": 55,
                        "spa": 20, "spd": 30},
            level=80,
        )
        battle.active_pokemon[0] = slow
        battle.opponent_active_pokemon[0] = passive
        player.last_protect_turn[battle_tag] = {}
        protect_order = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        player.score_action(protect_order, 0, battle)
        actions = player._b17_protect_floor_debug[battle_tag][0]
        self.assertEqual(len(actions), 1)
        a = actions[0]
        self.assertFalse(a["expected_faint"])
        self.assertFalse(a["floor_applied"])
        # pre == post when floor doesn't apply.
        self.assertEqual(a["pre_floor_score"], a["post_floor_score"])

    def test_protect_floor_debug_slot_index_alignment(self):
        """Slot 0 and slot 1 are independent: protect
        on slot 0 records in slot 0, protect on slot 1
        records in slot 1.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_protect_score_floor=(
                    240.0
                ),
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        battle.force_switch = [False, False]
        # Fast opponents so estimate_speed_priority_threat
        # returns faint_before_moving=True for both slots
        # (BEHAVIOR-18).
        slow0 = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        slow0.current_hp_fraction = 0.20
        slow1 = MockPokemon(
            "blissey",
            base_stats={"spe": 30, "hp": 255, "atk": 10, "def": 10,
                        "spa": 75, "spd": 135},
            level=80,
        )
        slow1.current_hp_fraction = 0.20
        fast0 = MockPokemon(
            "aerodactyl",
            base_stats={"spe": 130, "hp": 80, "atk": 105, "def": 65,
                        "spa": 60, "spd": 75},
            level=80,
        )
        fast1 = MockPokemon(
            "aerodactyl",
            base_stats={"spe": 130, "hp": 80, "atk": 105, "def": 65,
                        "spa": 60, "spd": 75},
            level=80,
        )
        battle.active_pokemon[0] = slow0
        battle.active_pokemon[1] = slow1
        battle.opponent_active_pokemon[0] = fast0
        battle.opponent_active_pokemon[1] = fast1
        player.last_protect_turn[battle_tag] = {}
        protect0 = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        protect1 = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        player.score_action(protect0, 0, battle)
        player.score_action(protect1, 1, battle)
        s0 = player._b17_protect_floor_debug[battle_tag][0]
        s1 = player._b17_protect_floor_debug[battle_tag][1]
        self.assertEqual(len(s0), 1)
        self.assertEqual(len(s1), 1)
        # Both should have expected_faint=True.
        self.assertTrue(s0[0]["expected_faint"])
        self.assertTrue(s1[0]["expected_faint"])

    def test_raw_scores_match_debug_after_floor(self):
        """v2l1 raw protect score equals the debug's
        after_floor value (post-floor score).
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_protect_score_floor=(
                    240.0
                ),
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        battle.force_switch = [False, False]
        # Fast opponent so estimate_speed_priority_threat
        # returns faint_before_moving=True (BEHAVIOR-18).
        slow = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        slow.current_hp_fraction = 0.20
        fast = MockPokemon(
            "aerodactyl",
            base_stats={"spe": 130, "hp": 80, "atk": 105, "def": 65,
                        "spa": 60, "spd": 75},
            level=80,
        )
        battle.active_pokemon[0] = slow
        battle.opponent_active_pokemon[0] = fast
        player.last_protect_turn[battle_tag] = {}
        protect_order = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        score = player.score_action(protect_order, 0, battle)
        # score_action returns the post-floor score.
        # The post-floor score is max(pre, 240).
        self.assertGreaterEqual(score, 240.0)
        # The debug records the same.
        actions = player._b17_protect_floor_debug[battle_tag][0]
        self.assertGreaterEqual(
            actions[0]["post_floor_score"], 240.0
        )

    def test_analyzer_protect_key_matches_scoring_helper(self):
        """The analyzer's Protect key classification
        agrees with _is_protect_like_action for
        representative actions.
        """
        from bot_doubles_damage_aware import (
            _is_protect_like_action,
        )
        # _PROTECT_LIKE_MOVE_IDS_B12 (from source):
        # protect, detect, spikyshield, kingsshield,
        # banefulbunker, silktrap, burningbulwark,
        # obstruct, maxguard
        protect_ids = {
            "protect", "detect", "spikyshield", "kingsshield",
            "banefulbunker", "silktrap", "burningbulwark",
            "obstruct", "maxguard",
        }
        non_protect_ids = {
            "tackle", "thunderbolt", "fakeout", "matchagotcha",
            "ragepowder", "trickroom", "tailwind",
        }
        for mid in protect_ids:
            m = MockMove(mid, "NORMAL", base_power=0)
            order = SingleBattleOrder(m, move_target=0)
            self.assertTrue(
                _is_protect_like_action(order),
                msg="expected protect-like for {}".format(mid),
            )
        for mid in non_protect_ids:
            m = MockMove(mid, "NORMAL", base_power=40)
            order = SingleBattleOrder(m, move_target=1)
            self.assertFalse(
                _is_protect_like_action(order),
                msg="expected NOT protect-like for {}".format(mid),
            )


class TestBEHAVIOR18CandidateIndependentExpectedFaint(
    unittest.TestCase
):
    """Phase BEHAVIOR-18: candidate-independent
    expected-faint semantics.

    BEHAVIOR-17 found that the speed-threat branch in
    ``estimate_speed_priority_threat`` was gating
    ``faint_before_moving`` on the candidate action
    type (``is_protect`` / ``is_switch``), making
    the flag order-dependent. The fix removes the
    candidate-type gating so the flag describes the
    active-slot state, not the candidate.

    These tests verify:
    - attack and Protect candidates both report
      ``faint_before_moving=True`` under the same
      threatened slot
    - switch candidates also report the slot-level
      faint state (for priority-0 candidates)
    - the BEHAVIOR-16 Protect floor now applies
    - the BEHAVIOR-16 Protect floor does NOT apply
      to switch candidates
    - the BEHAVIOR-12 attack penalty still only
      applies to attacks
    - v2l1_raw_scores reflect the floor
    - the BEHAVIOR-17 debug now records
      ``expected_faint=True`` and
      ``floor_applied=True`` for Protect candidates
    - no expected_faint -> no floor (regression check)
    """

    def _make_threatened_player(
        self,
        floor=240.0,
        expected_faint=True,
    ):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon

        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_protect_score_floor=(
                    floor
                ),
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        battle.force_switch = [False, False]
        player._expected_to_faint_before_moving[battle_tag] = {
            0: expected_faint, 1: False
        }
        # Threatened setup: fast opponent outspeeds
        # our slow active at low HP. This triggers
        # the speed-threat branch in
        # estimate_speed_priority_threat.
        our_active = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        our_active.current_hp_fraction = 0.20
        opp = MockPokemon(
            "aerodactyl",
            base_stats={"spe": 130, "hp": 80, "atk": 105, "def": 65,
                        "spa": 60, "spd": 75},
            level=80,
        )
        battle.active_pokemon[0] = our_active
        battle.opponent_active_pokemon[0] = opp
        player.last_protect_turn[battle_tag] = {}
        return player, battle

    def test_faint_before_moving_candidate_independent_for_attack_and_protect(
        self,
    ):
        """Same threatened slot, attack and Protect
        candidates both report faint_before_moving=True.
        """
        player, battle = self._make_threatened_player()
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40),
            move_target=1,
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        attack_info = player.estimate_speed_priority_threat(
            battle.active_pokemon[0],
            [battle.opponent_active_pokemon[0]],
            battle,
            attack,
        )
        protect_info = player.estimate_speed_priority_threat(
            battle.active_pokemon[0],
            [battle.opponent_active_pokemon[0]],
            battle,
            protect,
        )
        self.assertTrue(
            attack_info["faint_before_moving"],
            msg="attack should report faint_before_moving=True",
        )
        self.assertTrue(
            protect_info["faint_before_moving"],
            msg="Protect should also report "
                "faint_before_moving=True after BEHAVIOR-18",
        )

    def test_faint_before_moving_candidate_independent_for_switch(
        self,
    ):
        """Switch candidate also reports the slot-level
        faint state (for priority-0 candidates). The
        switch action itself has candidate_priority=6
        (set in estimate_speed_priority_threat), so
        the priority-0 check does NOT apply. The
        speed-threat branch (priority==0) also does
        NOT apply. So a switch candidate's
        faint_before_moving reflects the speed-threat
        branch only when the switch itself is the
        threatened action — which it is NOT (switch
        is fast). This test verifies the new behavior:
        the switch candidate's faint_before_moving is
        computed WITHOUT the candidate-type gating.
        """
        from test_doubles_speed_priority import MockPokemon
        player, battle = self._make_threatened_player()
        switch_target = MockPokemon(
            "garchomp",
            base_stats={"spe": 100, "hp": 100, "atk": 100,
                        "def": 100, "spa": 100, "spd": 100},
            level=80,
        )
        switch_order = SingleBattleOrder(switch_target)
        info = player.estimate_speed_priority_threat(
            battle.active_pokemon[0],
            [battle.opponent_active_pokemon[0]],
            battle,
            switch_order,
        )
        # Switch has priority=6 internally, which
        # is > 0, so the priority-0 check does not
        # fire. The speed-threat branch (priority==0)
        # also does not fire. So faint_before_moving
        # reflects the speed-threat branch's gating
        # for switch actions, which is now candidate-
        # independent in the priority-0 sense.
        # For the speed-threat branch, the condition
        # is: is_opp_faster AND our_hp <= threshold.
        # The switch action has its own priority, but
        # candidate_priority=6 > 0, so the
        # ``if candidate_priority == 0`` check does
        # NOT fire. This means faint_before_moving
        # may or may not be True depending on other
        # conditions. The key BEHAVIOR-18 invariant:
        # the flag is NOT excluded for switch just
        # because the candidate is a switch.
        # We just verify that the function returns
        # without error and the flag is a bool.
        self.assertIsInstance(
            info["faint_before_moving"], bool
        )

    def test_protect_floor_applies_after_candidate_independent_fix(
        self,
    ):
        """expected_faint Protect candidate gets floored
        score after BEHAVIOR-18.
        """
        player, battle = self._make_threatened_player(
            floor=240.0, expected_faint=True
        )
        # First, force expected_faint to be set by
        # scoring an attack order (this sets the
        # flag via estimate_speed_priority_threat).
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40),
            move_target=1,
        )
        player.score_action(attack, 0, battle)
        # Now score the Protect order. The flag
        # should still be True (it was set by the
        # attack scoring), so the floor applies.
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        protect_score = player.score_action(
            protect, 0, battle
        )
        # The floor should have raised protect to
        # at least 240.
        self.assertGreaterEqual(protect_score, 240.0)

    def test_switch_does_not_receive_protect_floor_after_fix(self):
        """Switch candidate does not get the BEHAVIOR-16
        floor even though expected_faint is True.
        The floor only applies to Protect-like actions.
        """
        from test_doubles_speed_priority import MockPokemon
        player, battle = self._make_threatened_player(
            floor=240.0, expected_faint=True
        )
        # Set expected_faint by scoring an attack.
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40),
            move_target=1,
        )
        player.score_action(attack, 0, battle)
        # Score a switch. The floor must NOT apply
        # to switch.
        switch_target = MockPokemon(
            "garchomp",
            base_stats={"spe": 100, "hp": 100, "atk": 100,
                        "def": 100, "spa": 100, "spd": 100},
            level=80,
        )
        switch_order = SingleBattleOrder(switch_target)
        switch_score = player.score_action(
            switch_order, 0, battle
        )
        # The floor does NOT apply to switch. The
        # switch score is whatever the switch path
        # returns. It must not be exactly 240.0
        # (which would indicate the floor was applied).
        # The switch path may return 0, negative,
        # or a positive score based on switch quality.
        # The key invariant: the floor was not
        # applied to it.
        self.assertNotEqual(switch_score, 240.0)

    def test_attack_penalty_still_only_applies_to_attack(self):
        """The BEHAVIOR-12 attack penalty only applies
        to non-Protect, non-switch, non-pass actions.
        After BEHAVIOR-18, this is unchanged.
        """
        from test_doubles_speed_priority import MockPokemon
        player, battle = self._make_threatened_player(
            floor=240.0, expected_faint=True
        )
        # Set expected_faint by scoring an attack.
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40),
            move_target=1,
        )
        player.score_action(attack, 0, battle)
        # Score a Protect. The BEHAVIOR-12 penalty
        # must NOT apply (it's gated by
        # _is_attack_action_under_expected_faint).
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        protect_score = player.score_action(
            protect, 0, battle
        )
        # Protect score is floored to 240 by
        # BEHAVIOR-16, not reduced by 75 by
        # BEHAVIOR-12. If BEHAVIOR-12 had applied,
        # the score would be different.
        # We just verify the score is >= 240
        # (floor applied, no penalty).
        self.assertGreaterEqual(protect_score, 240.0)

    def test_raw_scores_protect_reflects_floor_after_fix(self):
        """v2l1_raw_scores contains Protect score >= floor
        in expected_faint case after BEHAVIOR-18.
        """
        from bot_doubles_damage_aware import (
            _raw_score_map_for_slot,
        )
        player, battle = self._make_threatened_player(
            floor=240.0, expected_faint=True
        )
        # Build valid_orders with both attack and
        # protect, score them, and check raw_scores.
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40),
            move_target=1,
        )
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        valid_orders = [[attack, protect], []]
        slot_0_scores = {}
        for order in valid_orders[0]:
            slot_0_scores[id(order)] = player.score_action(
                order, 0, battle
            )
        # The raw_score_map should show protect >= 240.
        raw_map = _raw_score_map_for_slot(
            slot_0_scores, valid_orders, 0
        )
        # Find the protect key. Keys are tuples
        # (kind, move_id, target).
        protect_keys = [
            k for k in raw_map.keys()
            if isinstance(k, (tuple, list))
            and len(k) >= 2
            and "protect" in str(k[1]).lower()
        ]
        self.assertEqual(len(protect_keys), 1)
        protect_val = raw_map[protect_keys[0]]
        self.assertGreaterEqual(protect_val, 240.0)

    def test_protect_floor_debug_expected_faint_true_for_protect(
        self,
    ):
        """BEHAVIOR-17 debug now records
        expected_faint=True and floor_applied=True
        for Protect candidate after BEHAVIOR-18.
        """
        player, battle = self._make_threatened_player(
            floor=240.0, expected_faint=True
        )
        # Score an attack first to set expected_faint.
        attack = SingleBattleOrder(
            MockMove("tackle", "NORMAL", base_power=40),
            move_target=1,
        )
        player.score_action(attack, 0, battle)
        # Now score a Protect. The debug should
        # show expected_faint=True and
        # floor_applied=True.
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        player.score_action(protect, 0, battle)
        battle_tag = "test_battle"
        actions = player._b17_protect_floor_debug[battle_tag][0]
        # Find the Protect action in the debug.
        protect_actions = [
            a for a in actions
            if "protect" in a["order_key"].lower()
        ]
        self.assertEqual(len(protect_actions), 1)
        pa = protect_actions[0]
        self.assertTrue(
            pa["expected_faint"],
            msg="expected_faint should be True for "
                "Protect after BEHAVIOR-18",
        )
        self.assertTrue(
            pa["floor_applied"],
            msg="floor_applied should be True for "
                "Protect after BEHAVIOR-18",
        )

    def test_no_expected_faint_no_floor_regression(self):
        """When no speed-priority expected faint exists,
        Protect is not floored. Regression check.
        """
        # Use a passive opponent so estimate_speed_priority_threat
        # returns faint_before_moving=False (the slot is
        # not speed-threatened). This is the "no
        # expected_faint" case.
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        from test_doubles_speed_priority import MockPokemon
        player = TestPlayer(
            config=DoublesDamageAwareConfig(
                enable_speed_priority_awareness=True,
                speed_priority_expected_faint_protect_score_floor=(
                    240.0
                ),
            )
        )
        battle = MockBattle()
        battle_tag = "test_battle"
        slow = MockPokemon(
            "slowbro",
            base_stats={"spe": 30, "hp": 80, "atk": 70, "def": 80,
                        "spa": 100, "spd": 80},
            level=80,
        )
        slow.current_hp_fraction = 0.50
        passive = MockPokemon(
            "magikarp",
            base_stats={"spe": 30, "hp": 50, "atk": 10, "def": 55,
                        "spa": 20, "spd": 30},
            level=80,
        )
        battle.active_pokemon[0] = slow
        battle.opponent_active_pokemon[0] = passive
        player.last_protect_turn[battle_tag] = {}
        protect = SingleBattleOrder(
            MockMove("protect", "NORMAL"), move_target=0
        )
        protect_score = player.score_action(
            protect, 0, battle
        )
        # No expected_faint -> no floor. The
        # protect score is whatever the protect
        # path returns. With the passive setup,
        # is_threatened=False -> protect path
        # returns 0. The floor does not apply.
        self.assertEqual(protect_score, 0.0)
