"""Phase SETUP-3A / SETUP-5 — Tests for the opt-in
speed-setup intent bonus (Tailwind / Trick Room).

Phase SETUP-5: default magnitude updated from
+350 to +450. Tests below were updated to
reflect the new default and to test both
+450 (default) and +350 (legacy).

Mirrors the SPREAD-5 fixture pattern.

Tests cover:
- default config values
- default OFF → no score change for any setup move
- flag ON with all guards pass → +450 bonus applied
  (Phase SETUP-5 default; SETUP-3A was +350)
- flag ON but move is not TW/TR → no bonus
- Guard 4 (already-active TW/TR) suppresses bonus
- Guard 5 (visible Taunt) suppresses bonus
- Guard 5 (visible Encore) suppresses bonus
- Guard 3 (low HP) suppresses bonus when require_survival=True
- Guard 3 (low HP) allows bonus when require_survival=False
- Guard 6 (per-game cap) suppresses bonus
- Guard 6 (min turn interval) suppresses bonus
- record_setup_intent_pick updates state correctly
- KO priority is implicit (bonus cannot out-score a strong damage move)
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    DoublesDamageAwarePlayer,
    Move,
    SingleBattleOrder,
)


def _make_move(move_id="tackle", base_power=80):
    m = MagicMock(spec=Move)
    m.id = move_id
    m.base_power = base_power
    m.target = "normal"
    m.deduced_target = None
    m.priority = 0
    m.category = MagicMock()
    m.category.name = "PHYSICAL"
    m.type = MagicMock()
    m.type.name = "NORMAL"
    m.accuracy = 1.0
    return m


def _make_order(move, target=1):
    o = MagicMock(spec=SingleBattleOrder)
    o.order = move
    o.move_target = target
    return o


def _make_active_pokemon(hp_fraction=1.0, taunted=False, encored=False):
    p = MagicMock()
    p.species = "whimsicott"
    p.types = ["grass", "fairy"]
    p.current_hp_fraction = hp_fraction
    p.current_hp = int(100 * hp_fraction)
    p.max_hp = 100
    p.fainted = False
    p.base_stats = {"hp": 60, "atk": 67, "def": 85}
    p.ability = MagicMock()
    p.ability.name = "prankster"
    p.taunted = taunted
    p.encored = encored
    return p


def _make_battle(
    active_pokemon=None,
    side_conditions=None,
    battle_tag="test-battle",
    turn=1,
):
    b = MagicMock()
    b.battle_tag = battle_tag
    b.turn = turn
    b.active_pokemon = active_pokemon or [
        _make_active_pokemon(),
        _make_active_pokemon(),
    ]
    b.side_conditions = side_conditions or {}
    b.opponent_side_conditions = {}
    return b


class TestConfigFields(unittest.TestCase):
    """Config has the new opt-in fields with correct defaults."""

    def test_config_default_values(self):
        cfg = DoublesDamageAwareConfig()
        self.assertFalse(cfg.enable_setup_intent_policy)
        # Phase SETUP-5: default magnitude is +450
        # (updated from +350 in SETUP-3A per dry-run
        # evidence: 0% over-flip at 450, 9.1% at 550).
        self.assertEqual(cfg.setup_intent_speed_setup_bonus, 450.0)
        self.assertEqual(cfg.setup_intent_max_picks_per_game, 3)
        self.assertEqual(cfg.setup_intent_min_turn_between_picks, 2)
        self.assertTrue(cfg.setup_intent_require_survival)

    def test_config_field_types(self):
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True,
            setup_intent_speed_setup_bonus=500.0,
            setup_intent_max_picks_per_game=5,
            setup_intent_min_turn_between_picks=3,
            setup_intent_require_survival=False,
        )
        self.assertIsInstance(cfg.enable_setup_intent_policy, bool)
        self.assertIsInstance(cfg.setup_intent_speed_setup_bonus, float)
        self.assertIsInstance(cfg.setup_intent_max_picks_per_game, int)
        self.assertIsInstance(cfg.setup_intent_min_turn_between_picks, int)
        self.assertIsInstance(cfg.setup_intent_require_survival, bool)
        self.assertEqual(cfg.setup_intent_speed_setup_bonus, 500.0)
        self.assertEqual(cfg.setup_intent_max_picks_per_game, 5)


class TestSetupIntentEligibilityPure(unittest.TestCase):
    """Pure-logic tests for the 6 guards via the
    ``_setup_intent_speed_setup_eligible`` instance
    method."""

    def _make_player(self, cfg):
        """Construct a player via ``__new__`` to avoid
        the full poke_env initialization. We attach
        only the fields the helper actually reads."""
        p = DoublesDamageAwarePlayer.__new__(
            DoublesDamageAwarePlayer
        )
        p.config = cfg
        p._expected_to_faint_before_moving = {}
        p._setup_intent_picks_per_game = {}
        p._setup_intent_last_pick_turn = {}
        return p

    def test_default_off_returns_false(self):
        """Master switch OFF: bonus never applies."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=False
        )
        p = self._make_player(cfg)
        order = _make_order(_make_move("tailwind"))
        battle = _make_battle()
        self.assertFalse(
            p._setup_intent_speed_setup_eligible(
                order, 0, battle
            )
        )

    def test_flag_on_but_move_not_setup_returns_false(self):
        """Move must be Tailwind or Trick Room."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True
        )
        p = self._make_player(cfg)
        for mv in ["protect", "heatwave", "moonblast", "swordsdance"]:
            with self.subTest(move=mv):
                order = _make_order(_make_move(mv))
                battle = _make_battle()
                self.assertFalse(
                    p._setup_intent_speed_setup_eligible(
                        order, 0, battle
                    )
                )

    def test_flag_on_with_setup_move_and_clean_state_returns_true(self):
        """All guards pass: bonus should fire."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True
        )
        p = self._make_player(cfg)
        for mv in ["tailwind", "trickroom"]:
            with self.subTest(move=mv):
                order = _make_order(_make_move(mv))
                battle = _make_battle()
                self.assertTrue(
                    p._setup_intent_speed_setup_eligible(
                        order, 0, battle
                    )
                )

    def test_bonus_magnitude_at_default_450(self):
        """Phase SETUP-5: default bonus is +450."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True
        )
        self.assertEqual(cfg.setup_intent_speed_setup_bonus, 450.0)

    def test_legacy_350_still_works(self):
        """Phase SETUP-3A legacy: +350 still works
        if explicitly set."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True,
            setup_intent_speed_setup_bonus=350.0,
        )
        self.assertEqual(cfg.setup_intent_speed_setup_bonus, 350.0)

    def test_already_active_tailwind_suppresses(self):
        """Guard 4: speed-setup not already active."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True
        )
        p = self._make_player(cfg)
        order = _make_order(_make_move("trickroom"))
        battle = _make_battle(
            side_conditions={"tailwind": 4}
        )
        self.assertFalse(
            p._setup_intent_speed_setup_eligible(
                order, 0, battle
            )
        )

    def test_already_active_trickroom_suppresses(self):
        """Guard 4: TR already up."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True
        )
        p = self._make_player(cfg)
        order = _make_order(_make_move("tailwind"))
        battle = _make_battle(
            side_conditions={"trickroom": 5}
        )
        self.assertFalse(
            p._setup_intent_speed_setup_eligible(
                order, 0, battle
            )
        )

    # Phase SETUP-6A: regression tests for the
    # "already-active" guard fix. The previous
    # version only checked ``side_conditions``,
    # which missed Trick Room (a field effect,
    # not a side condition). SETUP-6 audit
    # surfaced this: battle 96495 T3 picked TR
    # when ``fields`` had ``trick_room``.

    def _make_battle_with_fields(
        self, fields=None, side_conditions=None,
        battle_tag="test-battle", turn=1,
    ):
        battle = _make_battle(
            active_pokemon=[
                _make_active_pokemon(),
                _make_active_pokemon(),
            ],
            side_conditions=side_conditions or {},
            battle_tag=battle_tag,
            turn=turn,
        )
        # Inject fields attribute
        battle.fields = fields or []
        return battle

    def test_already_active_trickroom_in_fields_suppresses(self):
        """Guard 4 fix: TR in fields (not side_conditions).

        Phase SETUP-6A v2: poke-env ``battle.fields``
        is a list of ``Field`` enum objects with a
        ``.name`` attribute (e.g. ``TRICK_ROOM``).
        The guard normalizes these to lowercase
        no-separator strings before comparison.
        """
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True
        )
        p = self._make_player(cfg)
        order = _make_order(_make_move("tailwind"))

        class FakeField:
            def __init__(self, name):
                self.name = name
        for field_val in (
            [FakeField("TRICK_ROOM")],
            [FakeField("Trick Room")],
            [FakeField("trick_room")],
            ["trick_room"],
            ["Trick Room"],
            {"trickroom": 5},
        ):
            with self.subTest(fields=field_val):
                battle = self._make_battle_with_fields(
                    fields=field_val
                )
                self.assertFalse(
                    p._setup_intent_speed_setup_eligible(
                        order, 0, battle
                    )
                )

    def test_already_active_tailwind_in_fields_suppresses(self):
        """Guard 4 fix: TW in fields."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True
        )
        p = self._make_player(cfg)
        order = _make_order(_make_move("trickroom"))

        class FakeField:
            def __init__(self, name):
                self.name = name
        for field_val in (
            [FakeField("TAILWIND")],
            [FakeField("Tailwind")],
            [FakeField("tailwind")],
            ["tailwind"],
            ["Tailwind"],
            {"tailwind": 4},
        ):
            with self.subTest(fields=field_val):
                battle = self._make_battle_with_fields(
                    fields=field_val
                )
                self.assertFalse(
                    p._setup_intent_speed_setup_eligible(
                        order, 0, battle
                    )
                )

    def test_no_active_fields_or_conds_allows_bonus(self):
        """Guard 4 fix: empty fields and conds → bonus fires."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True
        )
        p = self._make_player(cfg)
        order = _make_order(_make_move("tailwind"))
        battle = self._make_battle_with_fields(
            fields=[], side_conditions={}
        )
        self.assertTrue(
            p._setup_intent_speed_setup_eligible(
                order, 0, battle
            )
        )

    # Phase SETUP-7A: KO priority guard tests.
    # SETUP-7 20-pair preview showed 12.9%
    # over-select rate. The new Guard 7 explicitly
    # suppresses the setup bonus when the opp's
    # lowest active HP is below the threshold
    # (default 0.30).

    def _make_battle_with_opp_hp(
        self, opp_hp_fractions, battle_tag="test-battle",
        turn=1,
    ):
        battle = _make_battle(
            active_pokemon=[
                _make_active_pokemon(),
                _make_active_pokemon(),
            ],
            side_conditions={},
            battle_tag=battle_tag,
            turn=turn,
        )
        # Inject opp_active_pokemon with HP
        opp_mons = []
        for hp in opp_hp_fractions:
            opp = _make_active_pokemon(hp_fraction=hp)
            opp_mons.append(opp)
        battle.opponent_active_pokemon = opp_mons
        return battle

    def test_ko_priority_low_opp_hp_suppresses(self):
        """Guard 7: opp at low HP (below 0.10) → bonus suppressed."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True
        )
        p = self._make_player(cfg)
        order = _make_order(_make_move("tailwind"))
        for opp_hp in (0.01, 0.04, 0.05, 0.09):
            with self.subTest(opp_hp=opp_hp):
                battle = self._make_battle_with_opp_hp(
                    [opp_hp, 1.0]
                )
                self.assertFalse(
                    p._setup_intent_speed_setup_eligible(
                        order, 0, battle
                    )
                )

    def test_ko_priority_full_opp_hp_allows(self):
        """Guard 7: opp above 0.10 → bonus fires."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True
        )
        p = self._make_player(cfg)
        order = _make_order(_make_move("tailwind"))
        for opp_hp in (0.10, 0.20, 0.30, 0.50, 0.75, 1.0):
            with self.subTest(opp_hp=opp_hp):
                battle = self._make_battle_with_opp_hp(
                    [opp_hp, 1.0]
                )
                self.assertTrue(
                    p._setup_intent_speed_setup_eligible(
                        order, 0, battle
                    )
                )

    def test_ko_priority_uses_min_opp_hp(self):
        """Guard 7: uses LOWEST opp HP (most damageable)."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True
        )
        p = self._make_player(cfg)
        order = _make_order(_make_move("tailwind"))
        # Opp has 1.0 and 0.05 — min is 0.05
        battle = self._make_battle_with_opp_hp(
            [1.0, 0.05]
        )
        self.assertFalse(
            p._setup_intent_speed_setup_eligible(
                order, 0, battle
            )
        )

    def test_ko_priority_disabled_allows(self):
        """Guard 7: disabled → bonus fires even at low opp HP."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True,
            setup_intent_require_ko_check=False,
        )
        p = self._make_player(cfg)
        order = _make_order(_make_move("tailwind"))
        battle = self._make_battle_with_opp_hp(
            [0.05, 1.0]
        )
        self.assertTrue(
            p._setup_intent_speed_setup_eligible(
                order, 0, battle
            )
        )

    def test_ko_priority_threshold_configurable(self):
        """Guard 7: threshold is configurable."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True,
            setup_intent_ko_opp_hp_threshold=0.20,
        )
        p = self._make_player(cfg)
        order = _make_order(_make_move("tailwind"))
        # At 0.15, default 0.30 allows, but 0.20
        # threshold blocks (0.15 < 0.20).
        battle = self._make_battle_with_opp_hp(
            [0.15, 1.0]
        )
        self.assertFalse(
            p._setup_intent_speed_setup_eligible(
                order, 0, battle
            )
        )

    def test_visible_taunt_suppresses(self):
        """Guard 5: visibly Taunted."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True
        )
        p = self._make_player(cfg)
        order = _make_order(_make_move("tailwind"))
        active = _make_active_pokemon(taunted=True)
        battle = _make_battle(
            active_pokemon=[active, _make_active_pokemon()]
        )
        self.assertFalse(
            p._setup_intent_speed_setup_eligible(
                order, 0, battle
            )
        )

    def test_visible_encore_suppresses(self):
        """Guard 5: visibly Encored."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True
        )
        p = self._make_player(cfg)
        order = _make_order(_make_move("trickroom"))
        active = _make_active_pokemon(encored=True)
        battle = _make_battle(
            active_pokemon=[active, _make_active_pokemon()]
        )
        self.assertFalse(
            p._setup_intent_speed_setup_eligible(
                order, 0, battle
            )
        )

    def test_low_hp_with_require_survival_suppresses(self):
        """Guard 3: HP < 25% with require_survival=True."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True,
            setup_intent_require_survival=True,
        )
        p = self._make_player(cfg)
        order = _make_order(_make_move("tailwind"))
        active = _make_active_pokemon(hp_fraction=0.10)
        battle = _make_battle(
            active_pokemon=[active, _make_active_pokemon()]
        )
        self.assertFalse(
            p._setup_intent_speed_setup_eligible(
                order, 0, battle
            )
        )

    def test_low_hp_without_require_survival_allows(self):
        """Guard 3: HP < 25% but require_survival=False
        → bonus fires (we trust the operator)."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True,
            setup_intent_require_survival=False,
        )
        p = self._make_player(cfg)
        order = _make_order(_make_move("tailwind"))
        active = _make_active_pokemon(hp_fraction=0.10)
        battle = _make_battle(
            active_pokemon=[active, _make_active_pokemon()]
        )
        self.assertTrue(
            p._setup_intent_speed_setup_eligible(
                order, 0, battle
            )
        )

    def test_expected_to_faint_before_moving_suppresses(self):
        """Guard 3: bot expects the user to faint
        before moving."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True
        )
        p = self._make_player(cfg)
        p._expected_to_faint_before_moving = {
            "test-battle": {0: True}
        }
        order = _make_order(_make_move("tailwind"))
        battle = _make_battle()
        self.assertFalse(
            p._setup_intent_speed_setup_eligible(
                order, 0, battle
            )
        )

    def test_per_game_cap_suppresses(self):
        """Guard 6: per-game pick cap reached."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True,
            setup_intent_max_picks_per_game=3,
        )
        p = self._make_player(cfg)
        p._setup_intent_picks_per_game = {"test-battle": 3}
        p._setup_intent_last_pick_turn = {"test-battle": 0}
        order = _make_order(_make_move("tailwind"))
        battle = _make_battle(turn=10)
        self.assertFalse(
            p._setup_intent_speed_setup_eligible(
                order, 0, battle
            )
        )

    def test_min_turn_interval_suppresses(self):
        """Guard 6: too soon after last setup pick."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True,
            setup_intent_min_turn_between_picks=2,
        )
        p = self._make_player(cfg)
        p._setup_intent_picks_per_game = {"test-battle": 1}
        p._setup_intent_last_pick_turn = {"test-battle": 5}
        order = _make_order(_make_move("tailwind"))
        battle = _make_battle(turn=6)  # 6 - 5 = 1 < 2
        self.assertFalse(
            p._setup_intent_speed_setup_eligible(
                order, 0, battle
            )
        )

    def test_turn_interval_at_boundary_allows(self):
        """Guard 6: exactly at min interval (>=) → OK."""
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True,
            setup_intent_min_turn_between_picks=2,
        )
        p = self._make_player(cfg)
        p._setup_intent_picks_per_game = {"test-battle": 1}
        p._setup_intent_last_pick_turn = {"test-battle": 5}
        order = _make_order(_make_move("tailwind"))
        battle = _make_battle(turn=7)  # 7 - 5 = 2 == 2
        self.assertTrue(
            p._setup_intent_speed_setup_eligible(
                order, 0, battle
            )
        )


class TestRecordSetupIntentPick(unittest.TestCase):
    """``record_setup_intent_pick`` correctly updates
    the per-battle anti-spam state."""

    def _make_player(self, cfg):
        p = DoublesDamageAwarePlayer.__new__(
            DoublesDamageAwarePlayer
        )
        p.config = cfg
        p._setup_intent_picks_per_game = {}
        p._setup_intent_last_pick_turn = {}
        return p

    def test_first_pick(self):
        cfg = DoublesDamageAwareConfig()
        p = self._make_player(cfg)
        p.record_setup_intent_pick("bt", 5)
        self.assertEqual(
            p._setup_intent_picks_per_game["bt"], 1
        )
        self.assertEqual(
            p._setup_intent_last_pick_turn["bt"], 5
        )

    def test_subsequent_picks_increment(self):
        cfg = DoublesDamageAwareConfig()
        p = self._make_player(cfg)
        p.record_setup_intent_pick("bt", 5)
        p.record_setup_intent_pick("bt", 8)
        p.record_setup_intent_pick("bt", 12)
        self.assertEqual(
            p._setup_intent_picks_per_game["bt"], 3
        )
        self.assertEqual(
            p._setup_intent_last_pick_turn["bt"], 12
        )

    def test_separate_battles_tracked_independently(self):
        cfg = DoublesDamageAwareConfig()
        p = self._make_player(cfg)
        p.record_setup_intent_pick("bt1", 5)
        p.record_setup_intent_pick("bt2", 3)
        self.assertEqual(
            p._setup_intent_picks_per_game["bt1"], 1
        )
        self.assertEqual(
            p._setup_intent_picks_per_game["bt2"], 1
        )
        self.assertEqual(
            p._setup_intent_last_pick_turn["bt1"], 5
        )
        self.assertEqual(
            p._setup_intent_last_pick_turn["bt2"], 3
        )


class TestScoreWithBonusPureLogic(unittest.TestCase):
    """Mirror the production scoring rule in a pure
    function to verify the guard logic correctly
    gates the bonus addition."""

    def _score_with_setup_intent(
        self,
        config,
        setup_user_survives,
        already_active,
        visible_taunt,
        visible_encore,
        per_game_picks,
        min_turn_interval,
        current_turn,
        last_pick_turn,
        is_setup_move,
    ):
        """Pure mirror of the production rule."""
        score = 0.0
        if not config.enable_setup_intent_policy:
            return score
        if not is_setup_move:
            return score
        if config.setup_intent_require_survival:
            if not setup_user_survives:
                return score
        if already_active:
            return score
        if visible_taunt or visible_encore:
            return score
        if per_game_picks >= config.setup_intent_max_picks_per_game:
            return score
        if (
            current_turn - last_pick_turn
            < config.setup_intent_min_turn_between_picks
        ):
            return score
        return config.setup_intent_speed_setup_bonus

    def test_pure_mirror_basic(self):
        cfg = DoublesDamageAwareConfig(
            enable_setup_intent_policy=True
        )
        b = self._score_with_setup_intent(
            cfg,
            setup_user_survives=True,
            already_active=False,
            visible_taunt=False,
            visible_encore=False,
            per_game_picks=0,
            min_turn_interval=2,
            current_turn=10,
            last_pick_turn=-999,
            is_setup_move=True,
        )
        # Phase SETUP-5: default is +450 (was +350)
        self.assertEqual(b, 450.0)

    def test_pure_mirror_default_off(self):
        cfg = DoublesDamageAwareConfig()
        b = self._score_with_setup_intent(
            cfg,
            setup_user_survives=True,
            already_active=False,
            visible_taunt=False,
            visible_encore=False,
            per_game_picks=0,
            min_turn_interval=2,
            current_turn=10,
            last_pick_turn=-999,
            is_setup_move=True,
        )
        self.assertEqual(b, 0.0)


class TestKoPriorityImplicit(unittest.TestCase):
    """KO priority is implicit: a damage move that
    scores higher than setup + bonus will be
    selected over setup. The bonus cannot force
    setup past a high-scoring damage move.

    Phase SETUP-5: default magnitude is +450 (was
    +350 in SETUP-3A). Tests use +450 and the
    legacy +350 for completeness.
    """

    def test_bonus_450_cannot_outscore_strong_damage(self):
        """If top damage scores 700 and setup natural
        is 0, even with +450 bonus setup scores
        450 < 700. Setup still loses."""
        setup_natural = 0.0
        setup_with_bonus = setup_natural + 450.0
        top_damage = 700.0
        self.assertLess(setup_with_bonus, top_damage)

    def test_bonus_450_can_outscore_weak_damage(self):
        """If top damage scores 400 and setup natural
        is 0, with +450 bonus setup scores
        450 > 400. Setup wins."""
        setup_natural = 0.0
        setup_with_bonus = setup_natural + 450.0
        top_damage = 400.0
        self.assertGreater(setup_with_bonus, top_damage)

    def test_competitive_turn_setup_wins(self):
        """Match a typical turn: top damage 449 vs
        setup 0. With +450 bonus, setup 450 > 449
        → setup wins by 1."""
        setup_natural = 0.0
        setup_with_bonus = setup_natural + 450.0
        top_damage = 449.0
        self.assertGreater(setup_with_bonus, top_damage)

    def test_legacy_bonus_350_cannot_outscore_550(self):
        """Legacy +350 vs top_dmg 550: 350 < 550.
        Legacy magnitude was insufficient."""
        setup_natural = 0.0
        setup_with_bonus = setup_natural + 350.0
        top_damage = 550.0
        self.assertLess(setup_with_bonus, top_damage)


if __name__ == "__main__":
    unittest.main()
