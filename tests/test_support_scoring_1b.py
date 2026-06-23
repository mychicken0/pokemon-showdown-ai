"""Phase SUPPORT-SCORING-1B — tests for the support
positive scoring helper and integration.

Scope: only ``helpinghand`` and ``tailwind``. All
other support moves (Wide Guard, Follow Me, Rage
Powder, Coaching, Life Dew, Pollen Puff, Haze, Clear
Smog, screens, hazards, Icy Wind, Electroweb, Snarl,
Taunt, Encore, spore, willowisp, thunderwave, fakeout,
protect, detect, healpulse, floralhealing, decorate)
return no bonus from this helper.

These tests verify:
- Helper semantics (Helping Hand, Tailwind)
- Config defaults (all support scoring flags OFF)
- Flag OFF behavior (identical to no helper)
- Flag ON behavior (positive bonus when appropriate)
- Negative cases (wrong side, redundant, invalid)
- No bonus leakage between candidates
- No interaction regression with WT-3 hook
- No interaction regression with narrow ally heal
  wrong-side hard safety
- No species-based ability inference
- No Magic Bounce species inference
- No Anti-TR behavior change
"""

import unittest
from unittest.mock import MagicMock

from doubles_engine.support_positive_scoring import (
    HELPING_HAND_MOVE_ID,
    TAILWIND_MOVE_ID,
    DEFAULT_HELPING_HAND_BONUS,
    DEFAULT_TAILWIND_BONUS,
    SCORED_MOVE_IDS,
    is_support_positive_scoring_move,
    get_support_positive_bonus,
    evaluate_helping_hand_semantics,
    evaluate_tailwind_semantics,
    SupportPositiveScoringResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_move(move_id, base_power=0, type_="NORMAL"):
    m = MagicMock()
    m.id = move_id
    m.base_power = base_power
    m.type = type_
    return m


def _make_pokemon(
    species="pikachu",
    fainted=False,
    moves=None,
    ability=None,
    types=None,
    current_hp_fraction=1.0,
):
    p = MagicMock()
    p.species = species
    p.fainted = fainted
    p.current_hp_fraction = current_hp_fraction
    p.ability = ability
    p.types = types or []
    if moves is not None:
        p.moves = moves
    else:
        p.moves = {}
    return p


def _make_damaging_move(move_id, base_power=80):
    m = MagicMock()
    m.id = move_id
    m.base_power = base_power
    return m


def _make_support_order(move_id, move_target):
    order = MagicMock()
    inner = _make_move(move_id)
    order.order = inner
    order.move_target = move_target
    return order


def _make_battle(our_active, opp_active, weather=None, fields=None):
    battle = MagicMock()
    battle.active_pokemon = our_active
    battle.opponent_active_pokemon = opp_active
    battle.weather = weather
    battle.fields = fields or []
    return battle


def _make_config(
    master_on=False,
    helping_hand_bonus=DEFAULT_HELPING_HAND_BONUS,
    tailwind_bonus=DEFAULT_TAILWIND_BONUS,
):
    config = MagicMock()
    config.enable_support_positive_scoring = master_on
    config.helping_hand_bonus = helping_hand_bonus
    config.tailwind_bonus = tailwind_bonus
    return config


# ---------------------------------------------------------------------------
# Helper identification tests
# ---------------------------------------------------------------------------


class TestIsSupportPositiveScoringMove(unittest.TestCase):
    def test_helpinghand_recognized(self):
        self.assertTrue(
            is_support_positive_scoring_move("helpinghand")
        )

    def test_tailwind_recognized(self):
        self.assertTrue(
            is_support_positive_scoring_move("tailwind")
        )

    def test_wideguard_not_in_1b(self):
        self.assertFalse(
            is_support_positive_scoring_move("wideguard")
        )

    def test_followme_not_in_1b(self):
        self.assertFalse(
            is_support_positive_scoring_move("followme")
        )

    def test_ragepowder_not_in_1b(self):
        self.assertFalse(
            is_support_positive_scoring_move("ragepowder")
        )

    def test_coaching_not_in_1b(self):
        self.assertFalse(
            is_support_positive_scoring_move("coaching")
        )

    def test_lifedew_not_in_1b(self):
        self.assertFalse(
            is_support_positive_scoring_move("lifedew")
        )

    def test_pollenpuff_not_in_1b(self):
        self.assertFalse(
            is_support_positive_scoring_move("pollenpuff")
        )

    def test_healpulse_not_in_1b(self):
        self.assertFalse(
            is_support_positive_scoring_move("healpulse")
        )

    def test_floralhealing_not_in_1b(self):
        self.assertFalse(
            is_support_positive_scoring_move("floralhealing")
        )

    def test_decorate_not_in_1b(self):
        self.assertFalse(
            is_support_positive_scoring_move("decorate")
        )

    def test_thunderbolt_not_in_1b(self):
        # Damaging move, not a support move
        self.assertFalse(
            is_support_positive_scoring_move("thunderbolt")
        )

    def test_unknown_move_not_in_1b(self):
        self.assertFalse(
            is_support_positive_scoring_move("unknownmove")
        )

    def test_normalization(self):
        # Case-insensitive
        self.assertTrue(
            is_support_positive_scoring_move("HELPINGHAND")
        )
        # Dash-insensitive
        self.assertTrue(
            is_support_positive_scoring_move("helping-hand")
        )
        # Underscore-insensitive
        self.assertTrue(
            is_support_positive_scoring_move("helping_hand")
        )
        # Space-insensitive
        self.assertTrue(
            is_support_positive_scoring_move("helping hand")
        )

    def test_scored_move_ids_set(self):
        self.assertEqual(
            SCORED_MOVE_IDS,
            {"helpinghand", "tailwind"},
        )


# ---------------------------------------------------------------------------
# Config default tests
# ---------------------------------------------------------------------------


class TestConfigDefaults(unittest.TestCase):
    def test_master_flag_default_off(self):
        config = _make_config()
        self.assertFalse(
            config.enable_support_positive_scoring
        )

    def test_helping_hand_bonus_default(self):
        config = _make_config()
        self.assertEqual(
            config.helping_hand_bonus,
            DEFAULT_HELPING_HAND_BONUS,
        )
        self.assertEqual(
            config.helping_hand_bonus, 120.0
        )

    def test_tailwind_bonus_default(self):
        config = _make_config()
        self.assertEqual(
            config.tailwind_bonus, DEFAULT_TAILWIND_BONUS
        )
        self.assertEqual(config.tailwind_bonus, 180.0)

    def test_explicit_true_enables(self):
        config = _make_config(master_on=True)
        self.assertTrue(
            config.enable_support_positive_scoring
        )


# ---------------------------------------------------------------------------
# Helping Hand tests
# ---------------------------------------------------------------------------


class TestHelpingHandFlagOff(unittest.TestCase):
    """Flag OFF: Helping Hand returns no bonus regardless
    of other conditions.
    """

    def test_flag_off_no_bonus(self):
        config = _make_config(master_on=False)
        ally = _make_pokemon(
            moves={
                "thunderbolt": _make_damaging_move(
                    "thunderbolt", base_power=80
                ),
            }
        )
        our = [_make_pokemon(), ally]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("helpinghand", -2)
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.bonus, 0.0)
        self.assertEqual(result.reason, "flag_off")

    def test_flag_off_with_perfect_ally(self):
        """Even with a perfect ally, flag OFF means no
        bonus.
        """
        config = _make_config(master_on=False)
        ally = _make_pokemon(
            moves={
                "thunderbolt": _make_damaging_move(
                    "thunderbolt", base_power=150
                ),
            }
        )
        our = [_make_pokemon(), ally]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("helpinghand", -2)
        result = evaluate_helping_hand_semantics(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.bonus, 0.0)


class TestHelpingHandFlagOn(unittest.TestCase):
    """Flag ON: Helping Hand returns positive bonus when
    conditions are met.
    """

    def test_flag_on_ally_has_damaging_move(self):
        config = _make_config(master_on=True)
        ally = _make_pokemon(
            moves={
                "thunderbolt": _make_damaging_move(
                    "thunderbolt", base_power=80
                ),
            }
        )
        our = [_make_pokemon(), ally]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("helpinghand", -2)
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertTrue(result.should_score)
        self.assertEqual(result.bonus, DEFAULT_HELPING_HAND_BONUS)
        self.assertEqual(result.target_side, "ally")
        self.assertIn("helpinghand", result.reason)

    def test_flag_on_custom_bonus(self):
        config = _make_config(
            master_on=True, helping_hand_bonus=200.0
        )
        ally = _make_pokemon(
            moves={
                "thunderbolt": _make_damaging_move(
                    "thunderbolt", base_power=80
                ),
            }
        )
        our = [_make_pokemon(), ally]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("helpinghand", -2)
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertTrue(result.should_score)
        self.assertEqual(result.bonus, 200.0)

    def test_flag_on_slot1(self):
        """Slot 1 (active_idx=1) targeting ally at -1."""
        config = _make_config(master_on=True)
        ally = _make_pokemon(
            moves={
                "thunderbolt": _make_damaging_move(
                    "thunderbolt", base_power=80
                ),
            }
        )
        our = [ally, _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("helpinghand", -1)
        result = get_support_positive_bonus(
            order, 1, battle, config=config
        )
        self.assertTrue(result.should_score)
        self.assertEqual(result.target_side, "ally")


class TestHelpingHandNegative(unittest.TestCase):
    """Negative cases: Helping Hand should not score."""

    def test_target_opponent_no_bonus(self):
        config = _make_config(master_on=True)
        ally = _make_pokemon(
            moves={
                "thunderbolt": _make_damaging_move(
                    "thunderbolt", base_power=80
                ),
            }
        )
        our = [_make_pokemon(), ally]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("helpinghand", 1)
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.target_side, "opponent")
        self.assertEqual(result.reason, "wrong_side_target")

    def test_ally_fainted_no_bonus(self):
        config = _make_config(master_on=True)
        ally = _make_pokemon(
            fainted=True,
            moves={
                "thunderbolt": _make_damaging_move(
                    "thunderbolt", base_power=80
                ),
            },
        )
        our = [_make_pokemon(), ally]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("helpinghand", -2)
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.reason, "ally_fainted_or_missing")

    def test_ally_no_damaging_move_no_bonus(self):
        config = _make_config(master_on=True)
        ally = _make_pokemon(
            moves={
                "recover": _make_move("recover", base_power=0),
            }
        )
        our = [_make_pokemon(), ally]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("helpinghand", -2)
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.reason, "ally_no_damaging_move")

    def test_zero_bonus_no_score(self):
        config = _make_config(
            master_on=True, helping_hand_bonus=0.0
        )
        ally = _make_pokemon(
            moves={
                "thunderbolt": _make_damaging_move(
                    "thunderbolt", base_power=80
                ),
            }
        )
        our = [_make_pokemon(), ally]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("helpinghand", -2)
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.reason, "zero_bonus")

    def test_high_bonus_cannot_bypass_wrong_side(self):
        config = _make_config(
            master_on=True, helping_hand_bonus=10000.0
        )
        ally = _make_pokemon(
            moves={
                "thunderbolt": _make_damaging_move(
                    "thunderbolt", base_power=80
                ),
            }
        )
        our = [_make_pokemon(), ally]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("helpinghand", 1)  # opp
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.bonus, 0.0)

    def test_high_bonus_cannot_bypass_no_ally_damage(self):
        config = _make_config(
            master_on=True, helping_hand_bonus=10000.0
        )
        ally = _make_pokemon(
            moves={
                "recover": _make_move("recover", base_power=0),
            }
        )
        our = [_make_pokemon(), ally]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("helpinghand", -2)
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.bonus, 0.0)


# ---------------------------------------------------------------------------
# Tailwind tests
# ---------------------------------------------------------------------------


class TestTailwindFlagOff(unittest.TestCase):
    def test_flag_off_no_bonus(self):
        config = _make_config(master_on=False)
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = MagicMock()
        order.order = _make_move("tailwind")
        order.move_target = 0
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.bonus, 0.0)
        self.assertEqual(result.reason, "flag_off")


class TestTailwindFlagOn(unittest.TestCase):
    def test_flag_on_team_can_benefit(self):
        config = _make_config(master_on=True)
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = MagicMock()
        order.order = _make_move("tailwind")
        order.move_target = 0
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertTrue(result.should_score)
        self.assertEqual(result.bonus, DEFAULT_TAILWIND_BONUS)
        self.assertEqual(result.target_side, "field")

    def test_flag_on_custom_bonus(self):
        config = _make_config(
            master_on=True, tailwind_bonus=300.0
        )
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = MagicMock()
        order.order = _make_move("tailwind")
        order.move_target = 0
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertTrue(result.should_score)
        self.assertEqual(result.bonus, 300.0)


class TestTailwindNegative(unittest.TestCase):
    def test_tailwind_already_active_no_bonus(self):
        config = _make_config(master_on=True)
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp, weather="tailwind")
        order = MagicMock()
        order.order = _make_move("tailwind")
        order.move_target = 0
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.reason, "tailwind_already_active")

    def test_tailwind_already_active_in_fields_no_bonus(self):
        config = _make_config(master_on=True)
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(
            our, opp, fields=["TAILWIND"]
        )
        order = MagicMock()
        order.order = _make_move("tailwind")
        order.move_target = 0
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.reason, "tailwind_already_active")

    def test_not_enough_alive_allies_no_bonus(self):
        config = _make_config(master_on=True)
        our = [
            _make_pokemon(fainted=True),
            _make_pokemon(fainted=True),
        ]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = MagicMock()
        order.order = _make_move("tailwind")
        order.move_target = 0
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(
            result.reason, "not_enough_alive_allies"
        )

    def test_no_opponent_no_bonus(self):
        config = _make_config(master_on=True)
        our = [_make_pokemon(), _make_pokemon()]
        opp = []  # no opponent
        battle = _make_battle(our, opp)
        order = MagicMock()
        order.order = _make_move("tailwind")
        order.move_target = 0
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(
            result.reason, "no_opponent_to_outspeed"
        )

    def test_zero_bonus_no_score(self):
        config = _make_config(
            master_on=True, tailwind_bonus=0.0
        )
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = MagicMock()
        order.order = _make_move("tailwind")
        order.move_target = 0
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.reason, "zero_bonus")

    def test_high_bonus_cannot_bypass_redundant(self):
        config = _make_config(
            master_on=True, tailwind_bonus=10000.0
        )
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp, weather="tailwind")
        order = MagicMock()
        order.order = _make_move("tailwind")
        order.move_target = 0
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.bonus, 0.0)


# ---------------------------------------------------------------------------
# Non-covered moves: no bonus
# ---------------------------------------------------------------------------


class TestNonCoveredMoves(unittest.TestCase):
    def test_wideguard_no_bonus(self):
        config = _make_config(master_on=True)
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("wideguard", 0)
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.reason, "not_in_1b_allowlist")

    def test_followme_no_bonus(self):
        config = _make_config(master_on=True)
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("followme", 0)
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.reason, "not_in_1b_allowlist")

    def test_ragepowder_no_bonus(self):
        config = _make_config(master_on=True)
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("ragepowder", 0)
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.reason, "not_in_1b_allowlist")

    def test_healpulse_no_bonus(self):
        config = _make_config(master_on=True)
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("healpulse", -2)
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.reason, "not_in_1b_allowlist")

    def test_protect_no_bonus(self):
        config = _make_config(master_on=True)
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("protect", 0)
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.reason, "not_in_1b_allowlist")

    def test_damaging_move_no_bonus(self):
        config = _make_config(master_on=True)
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = MagicMock()
        order.order = _make_damaging_move("thunderbolt", 80)
        order.move_target = 1
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.reason, "not_in_1b_allowlist")

    def test_switch_action_no_bonus(self):
        config = _make_config(master_on=True)
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = MagicMock()
        order.order = None  # switch
        order.move_target = 0
        result = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        # Switch actions have no move_id, so the reason
        # is "empty_move_id" (not a recognized support
        # move).
        self.assertEqual(result.reason, "empty_move_id")


# ---------------------------------------------------------------------------
# No bonus leakage tests
# ---------------------------------------------------------------------------


class TestNoBonusLeakage(unittest.TestCase):
    def test_two_consecutive_calls_same_input_same_output(self):
        config = _make_config(master_on=True)
        ally = _make_pokemon(
            moves={
                "thunderbolt": _make_damaging_move(
                    "thunderbolt", base_power=80
                ),
            }
        )
        our = [_make_pokemon(), ally]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("helpinghand", -2)
        r1 = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        r2 = get_support_positive_bonus(
            order, 0, battle, config=config
        )
        self.assertEqual(r1.bonus, r2.bonus)
        self.assertEqual(r1.should_score, r2.should_score)

    def test_setter_then_non_setter_no_leakage(self):
        """Score a positive WT setter, then a non-WT
        support move. The non-support move must not
        inherit any bonus.
        """
        config = MagicMock()
        config.enable_weather_terrain_positive_scoring = True
        config.weather_terrain_positive_weather_bonus = 500.0
        config.weather_terrain_positive_terrain_bonus = 400.0
        config.enable_support_positive_scoring = True
        config.helping_hand_bonus = 120.0
        config.tailwind_bonus = 180.0
        ally = _make_pokemon(
            moves={
                "thunderbolt": _make_damaging_move(
                    "thunderbolt", base_power=80
                ),
            }
        )
        our = [_make_pokemon(), ally]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        # First call: a non-covered move
        order1 = MagicMock()
        order1.order = _make_damaging_move("thunderbolt", 80)
        order1.move_target = 1
        r1 = get_support_positive_bonus(
            order1, 0, battle, config=config
        )
        self.assertEqual(r1.bonus, 0.0)
        # Second call: helping hand
        order2 = _make_support_order("helpinghand", -2)
        r2 = get_support_positive_bonus(
            order2, 0, battle, config=config
        )
        self.assertEqual(r2.bonus, 120.0)
        # Third call: tailwind
        order3 = MagicMock()
        order3.order = _make_move("tailwind")
        order3.move_target = 0
        r3 = get_support_positive_bonus(
            order3, 0, battle, config=config
        )
        self.assertEqual(r3.bonus, 180.0)
        # Fourth call: thunderbolt again
        r4 = get_support_positive_bonus(
            order1, 0, battle, config=config
        )
        self.assertEqual(r4.bonus, 0.0)


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
    def test_none_config(self):
        """None config: no bonus, no crash."""
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        order = _make_support_order("helpinghand", -2)
        result = get_support_positive_bonus(
            order, 0, battle, config=None
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.bonus, 0.0)
        self.assertEqual(result.reason, "flag_off")

    def test_none_battle(self):
        config = _make_config(master_on=True)
        order = _make_support_order("helpinghand", -2)
        result = get_support_positive_bonus(
            order, 0, None, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(
            result.reason, "missing_battle_or_order"
        )

    def test_none_order(self):
        config = _make_config(master_on=True)
        our = [_make_pokemon(), _make_pokemon()]
        opp = [_make_pokemon(), _make_pokemon()]
        battle = _make_battle(our, opp)
        result = get_support_positive_bonus(
            None, 0, battle, config=config
        )
        self.assertFalse(result.should_score)
        self.assertEqual(result.reason, "empty_move_id")

    def test_result_to_dict(self):
        result = SupportPositiveScoringResult(
            move_id="helpinghand",
            bonus=120.0,
            should_score=True,
            reason="test",
            target_side="ally",
        )
        d = result.to_dict()
        self.assertEqual(d["move_id"], "helpinghand")
        self.assertEqual(d["bonus"], 120.0)
        self.assertTrue(d["should_score"])
        self.assertEqual(d["reason"], "test")
        self.assertEqual(d["target_side"], "ally")


# ---------------------------------------------------------------------------
# No species-based ability inference / no Magic Bounce
# ---------------------------------------------------------------------------


class TestNoSpeciesAbilityInference(unittest.TestCase):
    """The helper must NOT infer abilities from the
    active Pokemon's species. The decision is based
    solely on revealed moves, visible state, and
    the battle state.
    """

    def test_hatterene_with_magic_bounce_no_diff(self):
        """Even with Magic Bounce on Hatterene (just
        for the test), the helper decision is the same
        for a Hatterene-like setup and a Pikachu-like
        setup.
        """
        config = _make_config(master_on=True)
        ally_a = _make_pokemon(
            species="hatterene",
            ability="Magic Bounce",
            moves={
                "thunderbolt": _make_damaging_move(
                    "thunderbolt", base_power=80
                ),
            },
        )
        ally_b = _make_pokemon(
            species="pikachu",
            ability="Static",
            moves={
                "thunderbolt": _make_damaging_move(
                    "thunderbolt", base_power=80
                ),
            },
        )
        our_a = [_make_pokemon(), ally_a]
        our_b = [_make_pokemon(), ally_b]
        opp = [_make_pokemon(), _make_pokemon()]
        battle_a = _make_battle(our_a, opp)
        battle_b = _make_battle(our_b, opp)
        order = _make_support_order("helpinghand", -2)
        r_a = get_support_positive_bonus(
            order, 0, battle_a, config=config
        )
        r_b = get_support_positive_bonus(
            order, 0, battle_b, config=config
        )
        # Same result regardless of species or ability.
        self.assertEqual(r_a.bonus, r_b.bonus)
        self.assertEqual(r_a.should_score, r_b.should_score)
        self.assertTrue(r_a.should_score)


if __name__ == "__main__":
    unittest.main()
