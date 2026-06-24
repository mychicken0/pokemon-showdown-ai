"""Tests for PHASE7_DATA_EXPANSION_FIX_SELF_TARGET_SCORING.

Ponytail: pure unit tests. No poke-env runtime, no network,
no battles, no GPU. Uses mock-like duck-typed arguments.
"""
import unittest
from typing import Any


# Re-import the target function
def _import_module():
    import sys
    sys.path.insert(0, "showdown_ai")
    # We can't easily import the bot module without poke-env
    # context, so we extract the helper by source inspection
    # or by importing directly.
    # The function is at module level so we can import it.
    from showdown_ai.bot_doubles_damage_aware import (
        _is_same_side_single_target_damage_blocked,
        _FF_SPREAD_MOVES,
    )
    return _is_same_side_single_target_damage_blocked, _FF_SPREAD_MOVES


class _Order:
    """Minimal duck-type for SingleBattleOrder.

    The real object has ``order`` (the inner Move-like object)
    and ``move_target`` (int).
    """
    def __init__(self, inner=None, move_target=0):
        self.order = inner
        self.move_target = move_target


class _Move:
    """Minimal duck-type for Move (poke-env's Move object)."""
    def __init__(self, move_id="", category="", target=""):
        self.id = move_id
        self._category = category
        self._target = target

    @property
    def category(self):
        return self._category

    @property
    def target(self):
        return self._target


# Import the target function
try:
    from showdown_ai.bot_doubles_damage_aware import (
        _is_same_side_single_target_damage_blocked,
        _FF_SPREAD_MOVES,
    )
except Exception:
    _is_same_side_single_target_damage_blocked = None
    _FF_SPREAD_MOVES = frozenset()


class TestSameSideDamageBlocking(unittest.TestCase):
    """Same-side single-target damaging moves are blocked."""

    def test_psychic_ally_target_blocked(self):
        """Psychic targeting ally (target=-2) is blocked."""
        if _is_same_side_single_target_damage_blocked is None:
            self.skipTest("target function not importable")
        move = _Move(move_id="psychic", category="Special", target="normal")
        order = _Order(inner=move, move_target=-2)
        self.assertTrue(_is_same_side_single_target_damage_blocked(order))

    def test_moonblast_ally_target_blocked(self):
        """Moonblast targeting ally is blocked."""
        if _is_same_side_single_target_damage_blocked is None:
            self.skipTest("target function not importable")
        move = _Move(move_id="moonblast", category="Special", target="normal")
        order = _Order(inner=move, move_target=-2)
        self.assertTrue(_is_same_side_single_target_damage_blocked(order))

    def test_dragon_claw_ally_target_blocked(self):
        """Dragon Claw targeting ally is blocked."""
        if _is_same_side_single_target_damage_blocked is None:
            self.skipTest("target function not importable")
        move = _Move(move_id="dragonclaw", category="Physical", target="normal")
        order = _Order(inner=move, move_target=-2)
        self.assertTrue(_is_same_side_single_target_damage_blocked(order))

    def test_bug_buzz_ally_target_blocked(self):
        """Bug Buzz targeting ally is blocked."""
        if _is_same_side_single_target_damage_blocked is None:
            self.skipTest("target function not importable")
        move = _Move(move_id="bugbuzz", category="Special", target="normal")
        order = _Order(inner=move, move_target=-2)
        self.assertTrue(_is_same_side_single_target_damage_blocked(order))

    def test_self_target_blocked(self):
        """Self-target (target=-1) is also blocked for safety."""
        if _is_same_side_single_target_damage_blocked is None:
            self.skipTest("target function not importable")
        move = _Move(move_id="psychic", category="Special", target="normal")
        order = _Order(inner=move, move_target=-1)
        self.assertTrue(_is_same_side_single_target_damage_blocked(order))


class TestOpponentTargetNotBlocked(unittest.TestCase):
    """Same moves targeting opponent are NOT blocked."""

    def test_psychic_opponent_not_blocked(self):
        move = _Move(move_id="psychic", category="Special", target="normal")
        order = _Order(inner=move, move_target=1)
        self.assertFalse(_is_same_side_single_target_damage_blocked(order))

    def test_moonblast_opponent_not_blocked(self):
        move = _Move(move_id="moonblast", category="Special", target="normal")
        order = _Order(inner=move, move_target=2)
        self.assertFalse(_is_same_side_single_target_damage_blocked(order))

    def test_dragon_claw_opponent_not_blocked(self):
        move = _Move(move_id="dragonclaw", category="Physical", target="normal")
        order = _Order(inner=move, move_target=1)
        self.assertFalse(_is_same_side_single_target_damage_blocked(order))

    def test_field_target_not_blocked(self):
        """Target=0 (field/self for spread) is not blocked."""
        move = _Move(move_id="psychic", category="Special", target="normal")
        order = _Order(inner=move, move_target=0)
        self.assertFalse(_is_same_side_single_target_damage_blocked(order))


class TestSpreadMovesNotBlocked(unittest.TestCase):
    """Spread moves that legitimately splash allies are NOT blocked."""

    def test_earthquake_not_blocked(self):
        move = _Move(move_id="earthquake", category="Physical", target="allAdjacent")
        order = _Order(inner=move, move_target=-2)
        self.assertFalse(_is_same_side_single_target_damage_blocked(order))

    def test_heat_wave_not_blocked(self):
        move = _Move(move_id="heatwave", category="Special", target="allAdjacent")
        order = _Order(inner=move, move_target=-2)
        self.assertFalse(_is_same_side_single_target_damage_blocked(order))

    def test_rock_slide_not_blocked(self):
        move = _Move(move_id="rockslide", category="Physical", target="allAdjacent")
        order = _Order(inner=move, move_target=-2)
        self.assertFalse(_is_same_side_single_target_damage_blocked(order))

    def test_surf_not_blocked(self):
        move = _Move(move_id="surf", category="Special", target="allAdjacent")
        order = _Order(inner=move, move_target=-2)
        self.assertFalse(_is_same_side_single_target_damage_blocked(order))


class TestSupportHealNotBlocked(unittest.TestCase):
    """Ally-targeted support/heal/status moves are NOT blocked."""

    def test_helping_hand_not_blocked(self):
        move = _Move(move_id="helpinghand", category="Status", target="adjacentAlly")
        order = _Order(inner=move, move_target=-2)
        self.assertFalse(_is_same_side_single_target_damage_blocked(order))

    def test_heal_pulse_not_blocked(self):
        move = _Move(move_id="healpulse", category="Status", target="normal")
        order = _Order(inner=move, move_target=-2)
        self.assertFalse(_is_same_side_single_target_damage_blocked(order))

    def test_tailwind_not_blocked(self):
        move = _Move(move_id="tailwind", category="Status", target="teamSide")
        order = _Order(inner=move, move_target=0)
        self.assertFalse(_is_same_side_single_target_damage_blocked(order))

    def test_protect_not_blocked(self):
        move = _Move(move_id="protect", category="Status", target="self")
        order = _Order(inner=move, move_target=0)
        self.assertFalse(_is_same_side_single_target_damage_blocked(order))


class TestNonMoveNotBlocked(unittest.TestCase):
    """Switch and pass actions are NOT blocked."""

    def test_switch_not_blocked(self):
        order = _Order(inner=None, move_target=0)
        self.assertFalse(_is_same_side_single_target_damage_blocked(order))

    def test_pass_not_blocked(self):
        order = _Order(inner=None, move_target=0)
        self.assertFalse(_is_same_side_single_target_damage_blocked(order))


class TestSpreadMoveSetDefined(unittest.TestCase):
    """The spread move set must be populated from the monitor module."""

    def test_spread_moves_contains_earthquake(self):
        self.assertIn("earthquake", _FF_SPREAD_MOVES)

    def test_spread_moves_contains_heatwave(self):
        self.assertIn("heatwave", _FF_SPREAD_MOVES)

    def test_spread_moves_contains_rockslide(self):
        self.assertIn("rockslide", _FF_SPREAD_MOVES)

    def test_single_target_not_in_spread(self):
        self.assertNotIn("psychic", _FF_SPREAD_MOVES)
        self.assertNotIn("moonblast", _FF_SPREAD_MOVES)
        self.assertNotIn("bugbuzz", _FF_SPREAD_MOVES)
        self.assertNotIn("dragonclaw", _FF_SPREAD_MOVES)


if __name__ == "__main__":
    unittest.main()
