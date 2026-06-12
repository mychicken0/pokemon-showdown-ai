"""Phase 6.3.8 — Support Move Target Hard Safety Tests."""
import unittest
from unittest.mock import MagicMock
import sys, os

import poke_env_test_cleanup  # noqa: F401
sys.path.insert(0, os.path.dirname(__file__))

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    classify_support_move_target_intent,
    resolve_order_target_side,
    support_move_wrong_side_block,
    build_support_target_candidate_table,
    _compute_order_safety_blocks,
    DoublesDamageAwarePlayer,
)
from poke_env.battle.move import Move
from poke_env.player.battle_order import SingleBattleOrder


class MockPokemon:
    def __init__(self, species="pokemon", fainted=False):
        self.species = species
        self.fainted = fainted
        self.current_hp_fraction = 1.0


class TestPlayer(DoublesDamageAwarePlayer):
    """Minimal player for support move scoring tests. Avoids Player.__init__
    which creates asyncio primitives."""

    def __init__(self, config=None):
        pass

    @staticmethod
    def create(config=None):
        p = DoublesDamageAwarePlayer.__new__(TestPlayer)
        p.config = config or DoublesDamageAwareConfig()
        p.verbose = False
        p.custom_logger = None
        p.audit_logger = None
        p._active_config_override = None
        p._base_scores_cache = {0: {}, 1: {}}
        return p


def _make_move_mock(move_id, base_power=0, category="STATUS", target="normal"):
    move = MagicMock(spec=Move)
    move.id = move_id
    move.base_power = base_power
    move.category = MagicMock()
    move.category.name = category
    move.target = target
    move.deduced_target = None
    move.priority = 0
    move._flags = {}
    return move


def _make_order(move, target=1):
    class OrderObj:
        def __init__(self, m, t):
            self.order = m
            self.move_target = t
    return OrderObj(move, target)


def _make_battle():
    battle = MagicMock()
    battle.battle_tag = "test_battle"
    battle.turn = 1
    battle.active_pokemon = [MockPokemon("our0"), MockPokemon("our1")]
    battle.opponent_active_pokemon = [MockPokemon("opp0"), MockPokemon("opp1")]
    battle.available_moves = [[], []]
    battle.force_switch = [False, False]
    return battle


class TestClassifySupportMoveTargetIntent(unittest.TestCase):

    def test_heal_pulse_ally_beneficial(self):
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "ally")

    def test_helping_hand_ally_metadata(self):
        move = _make_move_mock("helpinghand", base_power=0, category="STATUS", target="adjacentAlly")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "ally")
        self.assertEqual(result["source"], "move_metadata")

    def test_taunt_opponent_disruptive(self):
        move = _make_move_mock("taunt", base_power=0, category="STATUS")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "opponent")

    def test_thunder_wave_opponent(self):
        move = _make_move_mock("thunderwave", base_power=0, category="STATUS")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "opponent")

    def test_protect_self(self):
        move = _make_move_mock("protect", base_power=0, category="STATUS", target="self")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "self")

    def test_tailwind_field(self):
        move = _make_move_mock("tailwind", base_power=0, category="STATUS", target="allySide")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "field")

    def test_trick_room_field(self):
        move = _make_move_mock("trickroom", base_power=0, category="STATUS", target="all")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "field")

    def test_damaging_move_unclassified(self):
        move = _make_move_mock("flamethrower", base_power=90, category="SPECIAL", target="normal")
        result = classify_support_move_target_intent(move)
        self.assertFalse(result["classified"])
        self.assertEqual(result["intended_side"], "unknown")

    def test_pollen_puff_either(self):
        move = _make_move_mock("pollenpuff", base_power=80, category="SPECIAL")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "either")

    def test_grid_classification(self):
        for move_id in ("healpulse", "floralhealing", "decorate"):
            move = _make_move_mock(move_id, base_power=0, category="STATUS")
            result = classify_support_move_target_intent(move)
            self.assertTrue(result["classified"], f"{move_id} not classified")
            self.assertEqual(result["intended_side"], "ally", f"{move_id} not ally")

    def test_opponent_disruption_classification(self):
        for move_id in ("taunt", "encore", "disable", "torment",
                        "thunderwave", "willowisp", "toxic", "spore",
                        "sleeppowder", "charm", "scaryface", "screech",
                        "faketears", "metalsound", "gastroacid"):
            move = _make_move_mock(move_id, base_power=0, category="STATUS")
            result = classify_support_move_target_intent(move)
            self.assertTrue(result["classified"], f"{move_id} not classified")
            self.assertEqual(result["intended_side"], "opponent", f"{move_id} not opponent")

    def test_skill_swap_either(self):
        move = _make_move_mock("skillswap", base_power=0, category="STATUS")
        result = classify_support_move_target_intent(move)
        self.assertTrue(result["classified"])
        self.assertEqual(result["intended_side"], "either")

    def test_skill_swap_into_ally_not_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        move = _make_move_mock("skillswap", base_power=0, category="STATUS")
        order = _make_order(move, target=-2)
        battle = _make_battle()
        blocked, _ = support_move_wrong_side_block(order, 0, battle, config)
        self.assertFalse(blocked)

    def test_skill_swap_into_opponent_not_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        move = _make_move_mock("skillswap", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        battle = _make_battle()
        blocked, _ = support_move_wrong_side_block(order, 0, battle, config)
        self.assertFalse(blocked)

    def test_classify_unclassified_move(self):
        move = _make_move_mock("unknownmove", base_power=80, category="SPECIAL", target="normal")
        result = classify_support_move_target_intent(move)
        self.assertFalse(result["classified"])
        self.assertEqual(result["source"], "unclassified")


class TestResolveOrderTargetSide(unittest.TestCase):

    def test_resolve_opponent_1_slot_0(self):
        battle = _make_battle()
        order = _make_order(None, target=1)
        result = resolve_order_target_side(order, 0, battle)
        self.assertEqual(result["side"], "opponent")

    def test_resolve_opponent_2_slot_0(self):
        battle = _make_battle()
        order = _make_order(None, target=2)
        result = resolve_order_target_side(order, 0, battle)
        self.assertEqual(result["side"], "opponent")

    def test_resolve_ally_slot_0(self):
        battle = _make_battle()
        order = _make_order(None, target=-2)
        result = resolve_order_target_side(order, 0, battle)
        self.assertEqual(result["side"], "ally")

    def test_resolve_self_slot_0(self):
        battle = _make_battle()
        order = _make_order(None, target=-1)
        result = resolve_order_target_side(order, 0, battle)
        self.assertEqual(result["side"], "self")

    def test_resolve_self_slot_1(self):
        battle = _make_battle()
        order = _make_order(None, target=-2)
        result = resolve_order_target_side(order, 1, battle)
        self.assertEqual(result["side"], "self")

    def test_resolve_ally_slot_1(self):
        battle = _make_battle()
        order = _make_order(None, target=-1)
        result = resolve_order_target_side(order, 1, battle)
        self.assertEqual(result["side"], "ally")

    def test_resolve_opponent_1_slot_1(self):
        battle = _make_battle()
        order = _make_order(None, target=1)
        result = resolve_order_target_side(order, 1, battle)
        self.assertEqual(result["side"], "opponent")


class TestSupportMoveWrongSideBlock(unittest.TestCase):

    def test_heal_pulse_into_opponent_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        battle = _make_battle()
        blocked, reason = support_move_wrong_side_block(order, 0, battle, config)
        self.assertTrue(blocked)

    def test_helping_hand_into_ally_legal(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        move = _make_move_mock("helpinghand", base_power=0, category="STATUS", target="adjacentAlly")
        order = _make_order(move, target=-2)
        battle = _make_battle()
        blocked, _ = support_move_wrong_side_block(order, 0, battle, config)
        self.assertFalse(blocked)

    def test_taunt_into_ally_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        move = _make_move_mock("taunt", base_power=0, category="STATUS")
        order = _make_order(move, target=-2)
        battle = _make_battle()
        blocked, _ = support_move_wrong_side_block(order, 0, battle, config)
        self.assertTrue(blocked)

    def test_disabled_feature(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = False
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        battle = _make_battle()
        blocked, reason = support_move_wrong_side_block(order, 0, battle, config)
        self.assertFalse(blocked)
        self.assertEqual(reason, "")

    def test_pollen_puff_into_opponent_not_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        move = _make_move_mock("pollenpuff", base_power=80, category="SPECIAL")
        order = _make_order(move, target=1)
        battle = _make_battle()
        blocked, _ = support_move_wrong_side_block(order, 0, battle, config)
        self.assertFalse(blocked)

    def test_pollen_puff_into_ally_not_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        move = _make_move_mock("pollenpuff", base_power=80, category="SPECIAL")
        order = _make_order(move, target=-2)
        battle = _make_battle()
        blocked, _ = support_move_wrong_side_block(order, 0, battle, config)
        self.assertFalse(blocked)

    def test_self_target_blocked_if_targets_other(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        move = _make_move_mock("recover", base_power=0, category="STATUS", target="self")
        order = _make_order(move, target=1)
        battle = _make_battle()
        blocked, _ = support_move_wrong_side_block(order, 0, battle, config)
        self.assertTrue(blocked)


class TestScoreActionSupportMoveTarget(unittest.TestCase):

    def test_score_action_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        player = TestPlayer.create(config)
        battle = _make_battle()
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = SingleBattleOrder(move, move_target=1)
        score = player.score_action(order, 0, battle)
        self.assertEqual(score, 0.0)

    def test_score_action_legal(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        player = TestPlayer.create(config)
        battle = _make_battle()
        hp = _make_move_mock("healpulse", base_power=0, category="STATUS")
        battle.available_moves = [[hp], []]
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = SingleBattleOrder(move, move_target=-2)
        score = player.score_action(order, 0, battle)
        self.assertGreater(score, 0.0)


class TestComputeOrderSafetyBlocks(unittest.TestCase):

    def test_heal_pulse_into_opponent_safety_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = _make_order(move, target=1)
        _, _, _, _, support_blocked, _ = _compute_order_safety_blocks(
            battle, config, [[order], []]
        )
        self.assertIn(id(order), support_blocked)

    def test_heal_pulse_into_ally_safe(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        battle = _make_battle()
        move = _make_move_mock("healpulse", base_power=0, category="STATUS")
        order = _make_order(move, target=-2)
        _, _, _, _, support_blocked, _ = _compute_order_safety_blocks(
            battle, config, [[order], []]
        )
        self.assertNotIn(id(order), support_blocked)


class TestBuildSupportTargetCandidateTable(unittest.TestCase):

    def test_candidate_table_schema(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        battle = _make_battle()
        hp = _make_move_mock("healpulse", base_power=0, category="STATUS")
        orders_slot0 = [
            _make_order(hp, target=1),
            _make_order(hp, target=-2),
        ]
        rows = build_support_target_candidate_table(orders_slot0, 0, battle, config)
        required_keys = {
            "move_id", "attacker_species", "target_position", "target_side",
            "target_species", "intended_side", "classification_source",
            "blocked", "block_reason", "selected",
        }
        for row in rows:
            self.assertTrue(required_keys.issubset(row.keys()),
                            f"Missing keys in {row}")
        self.assertEqual(len(rows), 2)

    def test_candidate_table_heal_pulse_wrong_side_and_ally(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        battle = _make_battle()
        hp = _make_move_mock("healpulse", base_power=0, category="STATUS")
        orders_slot0 = [
            _make_order(hp, target=1),
            _make_order(hp, target=-2),
        ]
        rows = build_support_target_candidate_table(orders_slot0, 0, battle, config)
        rows_by_tpos = {r["target_position"]: r for r in rows}
        self.assertIn(1, rows_by_tpos)
        self.assertIn(-2, rows_by_tpos)
        self.assertTrue(rows_by_tpos[1]["blocked"],
                        "Heal Pulse into opponent should be blocked")
        self.assertFalse(rows_by_tpos[-2]["blocked"],
                         "Heal Pulse into ally should not be blocked")
        self.assertEqual(rows_by_tpos[1]["target_side"], "opponent")
        self.assertEqual(rows_by_tpos[-2]["target_side"], "ally")

    def test_candidate_table_deduplicate(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        battle = _make_battle()
        hp = _make_move_mock("healpulse", base_power=0, category="STATUS")
        orders_slot0 = [
            _make_order(hp, target=1),
            _make_order(hp, target=1),
            _make_order(hp, target=-2),
        ]
        rows = build_support_target_candidate_table(orders_slot0, 0, battle, config)
        self.assertEqual(len(rows), 2, "Should deduplicate identical (move_id, target_position)")

    def test_candidate_table_no_blocked_means_avoided_false(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        battle = _make_battle()
        thunder = _make_move_mock("thunderwave", base_power=0, category="STATUS")
        orders_slot0 = [_make_order(thunder, target=1)]
        rows = build_support_target_candidate_table(orders_slot0, 0, battle, config)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["blocked"],
                         "Thunder Wave into opponent should not be blocked")

    def test_candidate_table_unknown_moves_excluded(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        battle = _make_battle()
        flamethrower = _make_move_mock("flamethrower", base_power=90, category="SPECIAL")
        orders_slot0 = [_make_order(flamethrower, target=1)]
        rows = build_support_target_candidate_table(orders_slot0, 0, battle, config)
        self.assertEqual(len(rows), 0, "Unclassified damaging moves should be excluded")

    def test_candidate_table_pollen_puff_excluded(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        battle = _make_battle()
        pp = _make_move_mock("pollenpuff", base_power=80, category="SPECIAL")
        orders_slot0 = [
            _make_order(pp, target=1),
            _make_order(pp, target=-2),
        ]
        rows = build_support_target_candidate_table(orders_slot0, 0, battle, config)
        self.assertEqual(len(rows), 0, "Pollen Puff (either) should be excluded from table")

    def test_candidate_table_skill_swap_excluded(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        battle = _make_battle()
        ss = _make_move_mock("skillswap", base_power=0, category="STATUS")
        orders_slot0 = [
            _make_order(ss, target=1),
            _make_order(ss, target=-2),
        ]
        rows = build_support_target_candidate_table(orders_slot0, 0, battle, config)
        self.assertEqual(len(rows), 0, "Skill Swap (either) should be excluded from table")

    def test_candidate_table_disabled_feature_returns_table(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = False
        battle = _make_battle()
        hp = _make_move_mock("healpulse", base_power=0, category="STATUS")
        orders_slot0 = [_make_order(hp, target=1), _make_order(hp, target=-2)]
        rows = build_support_target_candidate_table(orders_slot0, 0, battle, config)
        self.assertEqual(len(rows), 2)
        self.assertFalse(rows[0]["blocked"],
                         "With feature disabled, no move should be blocked")


class TestSelectedAvoidedMutualExclusion(unittest.TestCase):
    """Test candidate table invariants: selected and avoided are mutually exclusive."""

    def _simulate_selection(self, rows, selected_move_id, selected_target):
        """Given candidate rows and a selected action, compute per-slot accounting."""
        candidate_blocked = any(r["blocked"] for r in rows)
        selected_row = next(
            (r for r in rows if r["move_id"] == selected_move_id and r["target_position"] == selected_target),
            None,
        )
        selected_is_blocked = bool(selected_row and selected_row["blocked"])
        avoided = candidate_blocked and not selected_is_blocked
        only_legal = candidate_blocked and all(r["blocked"] for r in rows if r["intended_side"] in ("ally", "opponent"))
        return {
            "candidate_blocked": candidate_blocked,
            "selected": selected_is_blocked,
            "avoided": avoided,
            "only_legal": only_legal,
        }

    def test_heal_pulse_opponent_blocked_ally_selected(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        battle = _make_battle()
        hp = _make_move_mock("healpulse", base_power=0, category="STATUS")
        orders_slot0 = [
            _make_order(hp, target=1),
            _make_order(hp, target=-2),
        ]
        rows = build_support_target_candidate_table(orders_slot0, 0, battle, config)
        acct = self._simulate_selection(rows, "healpulse", -2)
        self.assertTrue(acct["candidate_blocked"])
        self.assertFalse(acct["selected"])
        self.assertTrue(acct["avoided"])

    def test_heal_pulse_opponent_selected(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        battle = _make_battle()
        hp = _make_move_mock("healpulse", base_power=0, category="STATUS")
        orders_slot0 = [
            _make_order(hp, target=1),
            _make_order(hp, target=-2),
        ]
        rows = build_support_target_candidate_table(orders_slot0, 0, battle, config)
        acct = self._simulate_selection(rows, "healpulse", 1)
        self.assertTrue(acct["candidate_blocked"])
        self.assertTrue(acct["selected"])
        self.assertFalse(acct["avoided"])

    def test_no_candidate_blocked(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        battle = _make_battle()
        tw = _make_move_mock("thunderwave", base_power=0, category="STATUS")
        orders_slot0 = [_make_order(tw, target=1)]
        rows = build_support_target_candidate_table(orders_slot0, 0, battle, config)
        acct = self._simulate_selection(rows, "thunderwave", 1)
        self.assertFalse(acct["candidate_blocked"])
        self.assertFalse(acct["selected"])
        self.assertFalse(acct["avoided"])

    def test_mutual_exclusion_invariant(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        battle = _make_battle()
        hp = _make_move_mock("healpulse", base_power=0, category="STATUS")
        orders_slot0 = [
            _make_order(hp, target=1),
            _make_order(hp, target=-2),
        ]
        rows = build_support_target_candidate_table(orders_slot0, 0, battle, config)
        # Selected
        acct_sel = self._simulate_selection(rows, "healpulse", 1)
        self.assertNotEqual(acct_sel["selected"], acct_sel["avoided"])
        # Avoided
        acct_avd = self._simulate_selection(rows, "healpulse", -2)
        self.assertNotEqual(acct_avd["selected"], acct_avd["avoided"])


class TestOnlyLegalSemantics(unittest.TestCase):

    def test_only_legal_when_all_blocked(self):
        """If every legal order for a slot is blocked, only_legal=True."""
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        battle = _make_battle()
        hp = _make_move_mock("healpulse", base_power=0, category="STATUS")
        # Only opponent-target Heal Pulse orders exist (no ally-target)
        orders_slot0 = [
            _make_order(hp, target=1),
            _make_order(hp, target=2),
        ]
        rows = build_support_target_candidate_table(orders_slot0, 0, battle, config)
        all_blocked = all(r["blocked"] for r in rows if r["intended_side"] in ("ally", "opponent"))
        self.assertTrue(all_blocked)
        # Accounting: when only_legal, candidate_blocked != selected + avoided
        # because there's no safe action to select.

    def test_not_only_legal_when_safe_candidate_exists(self):
        config = DoublesDamageAwareConfig()
        config.enable_support_move_target_hard_safety = True
        battle = _make_battle()
        hp = _make_move_mock("healpulse", base_power=0, category="STATUS")
        orders_slot0 = [
            _make_order(hp, target=1),
            _make_order(hp, target=-2),
        ]
        rows = build_support_target_candidate_table(orders_slot0, 0, battle, config)
        not_only_legal = not all(r["blocked"] for r in rows if r["intended_side"] in ("ally", "opponent"))
        self.assertTrue(not_only_legal,
                        "Should have a safe ally-target candidate")


if __name__ == "__main__":
    unittest.main()
