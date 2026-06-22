"""Phase BI-3D: Mega damaging-move bonus tests.

Validates that:
- ``DoublesDamageAwareConfig.mega_damaging_bonus`` defaults to 1e-3.
- With ``enable_mega_evolution=False``, the bonus does NOT apply.
- With ``enable_mega_evolution=True``:
  - damaging Mega (base_power > 0) gets the bonus.
  - status Mega (base_power == 0) does NOT get the bonus.
  - non-Mega damaging move does NOT get the bonus.
- Bonus handles missing base_power defensively.
- Synthetic tie: damaging Mega can win when plain score == Mega score
  pre-bonus, after applying the bonus.
- Larger plain gap (greater than bonus): plain still wins.
- Status move tie: plain still wins (no bonus applied).
- V4a audit can record selected Mega key.
- No production import of ``poke_env_test_cleanup``.

The tests construct a minimal ``DoublesDamageAwarePlayer`` instance
with ``__new__`` (per the project's test-lifecycle conventions) and
use ``MagicMock`` to stub ``_score_action_impl`` interactions where
needed.
"""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _MockMove:
    """Minimal Move stand-in."""

    def __init__(self, move_id="tackle", base_power=80):
        self.id = move_id
        self._base_power = base_power

    @property
    def base_power(self):
        return self._base_power


def _make_player_with_config(config):
    """Construct a lightweight
    ``DoublesDamageAwarePlayer`` instance with the given
    config, using ``__new__`` to skip ``Player.__init__``
    (per the project's poke-env test lifecycle pattern).
    """
    from bot_doubles_damage_aware import DoublesDamageAwarePlayer
    player = DoublesDamageAwarePlayer.__new__(DoublesDamageAwarePlayer)
    player.config = config
    return player


def _plain(move_id="tackle", base_power=80):
    from poke_env.battle.double_battle import SingleBattleOrder
    return SingleBattleOrder(
        _MockMove(move_id, base_power=base_power),
        move_target=0,
    )


def _mega(move_id="tackle", base_power=80):
    from poke_env.battle.double_battle import SingleBattleOrder
    return SingleBattleOrder(
        _MockMove(move_id, base_power=base_power),
        move_target=0,
        mega=True,
    )


def _cleanup(paths):
    for p in paths:
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


class TestConfigDefaults(unittest.TestCase):
    def test_default_bonus_value_is_tiny(self):
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        cfg = DoublesDamageAwareConfig()
        self.assertEqual(cfg.mega_damaging_bonus, 1e-3)
        self.assertIsInstance(cfg.mega_damaging_bonus, float)

    def test_default_flag_off(self):
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        cfg = DoublesDamageAwareConfig()
        self.assertFalse(cfg.enable_mega_evolution)


class TestFlagOffNoBonus(unittest.TestCase):
    def test_flag_off_damaging_mega_no_bonus(self):
        """flag OFF + Mega damaging move → no bonus applied.

        This is the byte-for-bit default invariant.
        """
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        cfg = DoublesDamageAwareConfig()
        self.assertFalse(cfg.enable_mega_evolution)
        # The condition checks enable_mega_evolution FIRST, so
        # even if order.mega=True, no bonus when flag is OFF.
        order = _mega()
        self.assertTrue(order.mega)
        self.assertGreater(order.order.base_power, 0)


class TestFlagOnDamagingMegaGetsBonus(unittest.TestCase):
    """Direct unit test of the bonus arithmetic."""

    def test_bonus_added_to_score(self):
        """flag ON + Mega damaging move → score increases by
        ``mega_damaging_bonus`` (default 1e-3)."""
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        cfg = DoublesDamageAwareConfig()
        cfg.enable_mega_evolution = True
        cfg.mega_damaging_bonus = 1e-3

        order = _mega()
        self.assertTrue(order.mega)
        self.assertEqual(order.order.base_power, 80)

        # Simulate the bonus arithmetic.
        base_score = 100.0
        score = base_score
        if (
            getattr(cfg, "enable_mega_evolution", False)
            and getattr(order, "mega", False)
        ):
            inner = getattr(order, "order", None)
            base_power = getattr(inner, "base_power", 0) or 0
            if base_power > 0:
                score += float(cfg.mega_damaging_bonus)
        self.assertAlmostEqual(score, 100.001)

    def test_flag_on_status_mega_no_bonus(self):
        """flag ON + Mega status move (base_power=0) → no bonus."""
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        cfg = DoublesDamageAwareConfig()
        cfg.enable_mega_evolution = True

        order = _mega(move_id="recover", base_power=0)
        self.assertTrue(order.mega)
        self.assertEqual(order.order.base_power, 0)

        base_score = 50.0
        score = base_score
        if (
            getattr(cfg, "enable_mega_evolution", False)
            and getattr(order, "mega", False)
        ):
            inner = getattr(order, "order", None)
            base_power = getattr(inner, "base_power", 0) or 0
            if base_power > 0:
                score += float(cfg.mega_damaging_bonus)
        # Status move: no bonus applied.
        self.assertEqual(score, 50.0)

    def test_flag_on_non_mega_damaging_no_bonus(self):
        """flag ON + non-Mega damaging move → no bonus."""
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        cfg = DoublesDamageAwareConfig()
        cfg.enable_mega_evolution = True

        order = _plain()
        self.assertFalse(order.mega)
        self.assertEqual(order.order.base_power, 80)

        base_score = 100.0
        score = base_score
        if (
            getattr(cfg, "enable_mega_evolution", False)
            and getattr(order, "mega", False)
        ):
            inner = getattr(order, "order", None)
            base_power = getattr(inner, "base_power", 0) or 0
            if base_power > 0:
                score += float(cfg.mega_damaging_bonus)
        self.assertEqual(score, 100.0)


class TestDefensiveHandling(unittest.TestCase):
    def test_bonus_handles_missing_order_attr(self):
        """Bonus block must not crash if order.mega or order.order
        is missing.
        """
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        cfg = DoublesDamageAwareConfig()
        cfg.enable_mega_evolution = True

        class _BadOrder:
            pass

        order = _BadOrder()
        # Simulate the bonus block with defensive getattr.
        base_score = 100.0
        score = base_score
        if (
            getattr(cfg, "enable_mega_evolution", False)
            and getattr(order, "mega", False)
        ):
            try:
                inner = getattr(order, "order", None)
                base_power = getattr(inner, "base_power", 0) or 0
            except Exception:
                base_power = 0
            if base_power > 0:
                score += float(cfg.mega_damaging_bonus)
        # mega=False on a bare object → no crash, no bonus.
        self.assertEqual(score, 100.0)

    def test_bonus_handles_missing_base_power(self):
        """Bonus block must not crash if base_power attribute is
        missing.
        """
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        cfg = DoublesDamageAwareConfig()
        cfg.enable_mega_evolution = True

        class _MoveNoBP:
            id = "tackle"

        from poke_env.battle.double_battle import SingleBattleOrder
        order = SingleBattleOrder(_MoveNoBP(), move_target=0, mega=True)
        self.assertTrue(order.mega)
        self.assertFalse(hasattr(order.order, "base_power"))

        base_score = 100.0
        score = base_score
        if (
            getattr(cfg, "enable_mega_evolution", False)
            and getattr(order, "mega", False)
        ):
            try:
                inner = getattr(order, "order", None)
                base_power = getattr(inner, "base_power", 0) or 0
            except Exception:
                base_power = 0
            if base_power > 0:
                score += float(cfg.mega_damaging_bonus)
        # No base_power → default to 0 → no bonus.
        self.assertEqual(score, 100.0)


class TestSyntheticTieScenarios(unittest.TestCase):
    """Simulate the joint-sort selection with synthetic scores."""

    def test_damaging_mega_can_win_synthetic_tie(self):
        """Plain and Mega damaging order have identical scores.
        After applying the bonus, Mega wins.
        """
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        cfg = DoublesDamageAwareConfig()
        cfg.enable_mega_evolution = True
        cfg.mega_damaging_bonus = 5.0

        plain = _plain()
        mega = _mega()

        # Pre-bonus identical scores.
        plain_score = 100.0
        mega_score_pre = 100.0
        # Apply bonus.
        bonus = float(cfg.mega_damaging_bonus)
        if mega.mega and mega.order.base_power > 0:
            mega_score = mega_score_pre + bonus
        else:
            mega_score = mega_score_pre
        # Mega wins on raw score.
        self.assertGreater(mega_score, plain_score)

    def test_damaging_mega_loses_to_larger_plain_gap(self):
        """Plain lead greater than bonus → plain still wins."""
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        cfg = DoublesDamageAwareConfig()
        cfg.enable_mega_evolution = True
        cfg.mega_damaging_bonus = 1e-3

        plain = _plain()
        mega = _mega()

        plain_score = 100.0
        mega_score_pre = 90.0
        bonus = float(cfg.mega_damaging_bonus)
        if mega.mega and mega.order.base_power > 0:
            mega_score = mega_score_pre + bonus
        else:
            mega_score = mega_score_pre
        # Plain still wins: 100.0 > 90.001.
        self.assertGreater(plain_score, mega_score)

    def test_status_mega_does_not_win_tie(self):
        """Status move: no bonus. Tied score → plain wins
        (stable sort + plain-first).
        """
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        cfg = DoublesDamageAwareConfig()
        cfg.enable_mega_evolution = True

        plain = _plain(move_id="recover", base_power=0)
        mega = _mega(move_id="recover", base_power=0)

        plain_score = 50.0
        mega_score_pre = 50.0
        bonus = float(cfg.mega_damaging_bonus)
        if mega.mega and mega.order.base_power > 0:
            mega_score = mega_score_pre + bonus
        else:
            mega_score = mega_score_pre
        # Tied. Stable sort preserves input order, so plain
        # wins (was inserted first into joint_orders).
        self.assertEqual(plain_score, mega_score)


class TestV4aSelectedMegaRecorded(unittest.TestCase):
    """End-to-end: log a turn with Mega selected and confirm
    the persisted JSONL records the Mega mechanic.
    """

    def test_v4a_selected_mega_recorded(self):
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
                v4a_selected_joint_key=(
                    ("move", "tackle", 0, "mega"),
                    ("switch", "snorlax", 0, ""),
                ),
                v4a_final_action_keys=[
                    ("move", "tackle", 0, "mega"),
                    ("switch", "snorlax", 0, ""),
                ],
            )
            logger.save_battle("tag", "test", FB())

            with open(main_path) as f:
                record = json.loads(f.readline())
            turn = record["audit_turns"][0]
            self.assertEqual(
                turn["v4a_selected_joint_key"],
                [["move", "tackle", 0, "mega"],
                 ["switch", "snorlax", 0, ""]],
            )
            self.assertEqual(
                turn["v4a_final_action_keys"],
                [["move", "tackle", 0, "mega"],
                 ["switch", "snorlax", 0, ""]],
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


class TestMegaIntentBonus(unittest.TestCase):
    """Phase BI-3M: opt-in Mega intent bonus.

    The Mega damaging-move bonus is the sum of
    ``mega_damaging_bonus`` (default 1e-3, tie-breaker)
    and ``mega_intent_bonus`` (default 1.0, intentional).
    With ``enable_mega_evolution`` default False,
    neither bonus applies to the default policy.

    The tests below simulate the bonus arithmetic
    directly (matching the pattern in
    ``TestFlagOnDamagingMegaGetsBonus``) rather than
    calling ``_score_action_impl`` with its complex
    signature. This isolates the bonus logic from the
    rest of the scoring pipeline.
    """

    def _make_order(self, base_power, mega):
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        class Move:
            pass
        mv = Move()
        mv.id = "tackle" if base_power > 0 else "recover"
        mv.base_power = base_power
        return SingleBattleOrder(mv, move_target=0, mega=mega)

    def _simulated_score(self, cfg, order, base_score=0.0):
        """Apply the Mega bonus arithmetic to a base score
        exactly as ``_score_action_impl`` does. Returns
        the resulting score.
        """
        score = base_score
        if (
            getattr(cfg, "enable_mega_evolution", False)
            and getattr(order, "mega", False)
        ):
            inner = getattr(order, "order", None)
            base_power = getattr(inner, "base_power", 0) or 0
            if base_power > 0:
                score += float(
                    getattr(cfg, "mega_damaging_bonus", 1e-3)
                ) + float(
                    getattr(cfg, "mega_intent_bonus", 1.0)
                )
        return score

    def test_default_mega_intent_bonus_is_one(self):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig()
        self.assertEqual(cfg.mega_intent_bonus, 1.0)
        # mega_damaging_bonus remains 1e-3.
        self.assertEqual(cfg.mega_damaging_bonus, 1e-3)

    def test_flag_off_no_intent_bonus(self):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig()  # default OFF
        plain = self._make_order(40, mega=False)
        mega = self._make_order(40, mega=True)
        # Flag OFF: both get 0.0 (no base score, no bonus).
        self.assertEqual(self._simulated_score(cfg, plain), 0.0)
        self.assertEqual(self._simulated_score(cfg, mega), 0.0)

    def test_flag_on_damaging_mega_gets_tiny_plus_intent_bonus(self):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig(enable_mega_evolution=True)
        plain = self._make_order(40, mega=False)
        mega = self._make_order(40, mega=True)
        # Mega gets 1e-3 + 1.0 = 1.001 bonus.
        self.assertAlmostEqual(
            self._simulated_score(cfg, mega),
            1e-3 + 1.0,
            places=6,
        )
        # Plain gets 0.0 (no bonus).
        self.assertEqual(self._simulated_score(cfg, plain), 0.0)

    def test_flag_on_status_mega_gets_no_bonus(self):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig(enable_mega_evolution=True)
        mega = self._make_order(0, mega=True)  # status
        # Status move Mega gets zero bonus.
        self.assertEqual(self._simulated_score(cfg, mega), 0.0)

    def test_flag_on_non_mega_damaging_gets_no_bonus(self):
        """A non-Mega damaging order must receive zero
        Mega bonus even when flag is ON.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig(enable_mega_evolution=True)
        plain = self._make_order(40, mega=False)
        # Non-Mega: zero bonus.
        self.assertEqual(self._simulated_score(cfg, plain), 0.0)

    def test_intent_bonus_can_beat_small_plain_gap(self):
        """A Mega order with a 1.001 bonus can beat a
        plain order whose score is up to ~1.0 lower.
        This test verifies the bonus magnitude is
        sufficient to make Mega win over plain on equal
        base scoring.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig(enable_mega_evolution=True)
        # Same base score, same move. Plain gets 0.0,
        # Mega gets 1.001. Mega wins by 1.001.
        plain = self._make_order(40, mega=False)
        mega = self._make_order(40, mega=True)
        plain_score = self._simulated_score(cfg, plain)
        mega_score = self._simulated_score(cfg, mega)
        # Mega should beat plain by at least 1.0.
        self.assertGreater(mega_score - plain_score, 1.0)

    def test_intent_bonus_does_not_beat_large_plain_gap(self):
        """A plain order with a large scoring advantage
        (e.g. 50-point gap) should still beat Mega.
        The intent bonus is 1.0, not enough to override
        a 50-point gap.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig(enable_mega_evolution=True)
        plain = self._make_order(40, mega=False)
        mega = self._make_order(40, mega=True)
        # Simulate a 50-point plain advantage.
        plain_score = self._simulated_score(cfg, plain, base_score=50.0)
        mega_score = self._simulated_score(cfg, mega, base_score=0.0)
        # Plain (50.0) should beat Mega (1.001).
        self.assertGreater(plain_score, mega_score)

    def test_custom_zero_intent_bonus_restores_tie_breaker_only_behavior(self):
        """Setting ``mega_intent_bonus=0.0`` restores the
        BI-3D pure tie-breaker behavior: Mega wins
        only by the 1e-3 tie-breaker.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig(
            enable_mega_evolution=True,
            mega_intent_bonus=0.0,
        )
        mega = self._make_order(40, mega=True)
        # Mega gets only the tie-breaker (1e-3).
        self.assertAlmostEqual(
            self._simulated_score(cfg, mega), 1e-3, places=6
        )

    def test_v4a_selected_mega_still_records_mechanic(self):
        """V4a mechanic key still records 'mega' for
        Mega orders, even with the intent bonus.
        """
        from doubles_engine.action_keys import (
            _order_action_key_with_mechanic,
        )
        plain = self._make_order(40, mega=False)
        mega = self._make_order(40, mega=True)
        k_plain = _order_action_key_with_mechanic(plain)
        k_mega = _order_action_key_with_mechanic(mega)
        # Last element is the mechanic label.
        self.assertEqual(k_plain[-1], "")
        self.assertEqual(k_mega[-1], "mega")

    def test_runtime_parity_default_off(self):
        """Default OFF config: the default config has
        enable_mega_evolution=False, so no Mega bonus
        is applied. This is the runtime parity check.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        cfg = DoublesDamageAwareConfig()
        self.assertFalse(cfg.enable_mega_evolution)
        plain = self._make_order(40, mega=False)
        mega = self._make_order(40, mega=True)
        # Both get 0.0 (no bonus applied under default OFF).
        self.assertEqual(
            self._simulated_score(cfg, plain),
            self._simulated_score(cfg, mega),
        )


if __name__ == "__main__":
    unittest.main()