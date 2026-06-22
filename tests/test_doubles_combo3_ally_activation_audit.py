"""Phase COMBO-3 — Tests for the new ally-activation
audit fields. Pure unit tests using a mock battle
object; no live poke-env, no Showdown.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from doubles_decision_audit_logger import (
    DoublesDecisionAuditLogger,
)


def _make_logger(path):
    """Build a logger with reset=True and write to a
    temp file. Returns the logger."""
    return DoublesDecisionAuditLogger(
        filepath=path, reset=True, detail_level="top5"
    )


def _make_battle_mock(
    selected_joint_key=None,
    our_actives=None,
    opp_actives=None,
    our_items=None,
    opp_abilities=None,
):
    """Build a MagicMock battle with selected action,
    our actives, opp actives, and known ally
    abilities/items.
    """
    battle = MagicMock()
    battle.active_pokemon = our_actives or []
    battle.opponent_active_pokemon = opp_actives or []
    battle.available_switches = []
    battle.force_switch = [False, False]
    battle.opponent_side_conditions = {}
    battle.side_conditions = {}
    battle.weather = None
    battle.fields = set()
    if selected_joint_key:
        battle.active_pokemon[0].active = True
    return battle


def _make_pokemon(
    species="",
    ability="",
    item="",
    types=("normal",),
    hp_fraction=1.0,
    fainted=False,
):
    p = MagicMock()
    p.species = species
    p.types = list(types)
    p.current_hp_fraction = hp_fraction
    p.fainted = fainted
    # poke_env.ability: ability.name
    ability_obj = MagicMock()
    ability_obj.name = ability if ability else "unknown"
    p.ability = ability_obj
    p.base_stats = {"hp": 100, "atk": 100, "def": 100}
    item_obj = MagicMock()
    item_obj.name = item if item else "none"
    p.item = item_obj
    return p


def _build_minimal_turn_call_kwargs(
    battle,
    selected_joint_order="/choose move surf 1",
    slot_actions=("", ""),
    slot_action_types=(
        {"damaging": True, "status": False},
        {"damaging": True, "status": False},
    ),
    target_species=("", ""),
    expected_damages=(0.0, 0.0),
    expected_kos=(False, False),
    target_hps=(1.0, 1.0),
    speed_priority_threatened=(False, False),
    expected_to_faint_before_moving=(False, False),
    protected_due_to_speed_priority=(False, False),
    # New COMBO-3 fields:
    selected_move_into_known_absorb_ally=(False, False),
    selected_move_into_known_redirect_ally=(False, False),
    selected_super_effective_into_weakness_policy_holder=(
        False, False
    ),
):
    """Build a minimal kwargs dict for log_turn_decision.
    The new COMBO-3 fields are the only ones we test.
    """
    return dict(
        battle_tag="test-battle-1",
        turn=1,
        battle=battle,
        selected_joint_order=selected_joint_order,
        selected_score=100.0,
        scored_joint_orders=[],
        expected_damages=expected_damages,
        expected_kos=expected_kos,
        target_hps=target_hps,
        overkill_triggered=False,
        focus_fire_triggered=False,
        ally_hit_penalty_triggered=False,
        spread_available=[True, True],
        best_spread_score=[0.0, 0.0],
        best_ko_score=[0.0, 0.0],
        low_hp_opponent_existed=False,
        low_hp_opponent_targeted=False,
        slot_actions=slot_actions,
        slot_action_types=slot_action_types,
        target_species=target_species,
        # New COMBO-3 fields:
        selected_move_into_known_absorb_ally=(
            selected_move_into_known_absorb_ally
        ),
        selected_move_into_known_redirect_ally=(
            selected_move_into_known_redirect_ally
        ),
        selected_super_effective_into_weakness_policy_holder=(
            selected_super_effective_into_weakness_policy_holder
        ),
        # Required defaults for the new template fields
        # to render as False:
        speed_priority_threatened=speed_priority_threatened,
        expected_to_faint_before_moving=(
            expected_to_faint_before_moving
        ),
        protected_due_to_speed_priority=(
            protected_due_to_speed_priority
        ),
    )


class TestLoggerAcceptsNewFields(unittest.TestCase):
    """The logger must accept the 3 new fields
    without raising TypeError. Their values must be
    persisted in the saved battle record.
    """

    def test_logger_accepts_known_absorb_ally(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            logger.log_turn_decision(
                **_build_minimal_turn_call_kwargs(
                    battle,
                    selected_move_into_known_absorb_ally=(
                        True, False
                    ),
                )
            )
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            self.assertIn("audit_turns", row)
            t = row["audit_turns"][0]
            # Per-slot fields are stored in slot_0 and
            # slot_1 sub-dicts.
            self.assertIn(
                "selected_move_into_known_absorb_ally",
                t["slot_0"],
            )
            self.assertEqual(
                t["slot_0"][
                    "selected_move_into_known_absorb_ally"
                ],
                True,
            )
            self.assertEqual(
                t["slot_1"][
                    "selected_move_into_known_absorb_ally"
                ],
                False,
            )
            self.assertEqual(
                t["slot_0"][
                    "selected_move_into_known_redirect_ally"
                ],
                False,
            )
            self.assertEqual(
                t["slot_0"][
                    "selected_super_effective_into_weakness_policy_holder"
                ],
                False,
            )

    def test_logger_accepts_known_redirect_ally(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            logger.log_turn_decision(
                **_build_minimal_turn_call_kwargs(
                    battle,
                    selected_move_into_known_redirect_ally=(
                        False, True
                    ),
                )
            )
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            self.assertEqual(
                t["slot_0"][
                    "selected_move_into_known_redirect_ally"
                ],
                False,
            )
            self.assertEqual(
                t["slot_1"][
                    "selected_move_into_known_redirect_ally"
                ],
                True,
            )

    def test_logger_accepts_weakness_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            logger.log_turn_decision(
                **_build_minimal_turn_call_kwargs(
                    battle,
                    selected_super_effective_into_weakness_policy_holder=(
                        True, True
                    ),
                )
            )
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            self.assertEqual(
                t["slot_0"][
                    "selected_super_effective_into_weakness_policy_holder"
                ],
                True,
            )
            self.assertEqual(
                t["slot_1"][
                    "selected_super_effective_into_weakness_policy_holder"
                ],
                True,
            )

    def test_logger_default_to_false_when_not_passed(self):
        """If the bot does not pass the new fields
        (older callers), they default to False. This
        is the backward-compat behavior.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            kwargs = _build_minimal_turn_call_kwargs(battle)
            # Strip the new fields to simulate an old
            # caller.
            for k in (
                "selected_move_into_known_absorb_ally",
                "selected_move_into_known_redirect_ally",
                "selected_super_effective_into_weakness_policy_holder",
            ):
                kwargs.pop(k, None)
            logger.log_turn_decision(**kwargs)
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            # All three default to False when not passed.
            for k in (
                "selected_move_into_known_absorb_ally",
                "selected_move_into_known_redirect_ally",
                "selected_super_effective_into_weakness_policy_holder",
            ):
                self.assertEqual(t["slot_0"][k], False)
                self.assertEqual(t["slot_1"][k], False)


class TestLoggerPreservesOldFields(unittest.TestCase):
    """Adding new fields must not break or remove old
    fields. The existing absorb_* and direct_absorb_*
    template fields must still appear in the audit
    record.
    """

    def test_old_absorb_fields_still_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            logger.log_turn_decision(
                **_build_minimal_turn_call_kwargs(battle)
            )
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            for k in (
                "absorb_immune_move_selected",
                "absorb_selection_forced",
                "absorb_safe_alternative_available",
                "absorb_via_redirection",
                "direct_absorb_immune_move_selected",
                "direct_known_absorb_repeat_selected",
            ):
                self.assertIn(k, t["slot_0"])


class TestFixtureAdequate(unittest.TestCase):
    """The fixture mock helpers above can produce a
    complete audit row.
    """

    def test_complete_row_has_all_new_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            logger = _make_logger(path)
            battle = _make_battle_mock()
            logger.log_turn_decision(
                **_build_minimal_turn_call_kwargs(
                    battle,
                    selected_move_into_known_absorb_ally=(
                        True, True
                    ),
                    selected_move_into_known_redirect_ally=(
                        True, False
                    ),
                    selected_super_effective_into_weakness_policy_holder=(
                        False, True
                    ),
                )
            )
            logger.save_battle("test-battle-1", "bot", battle)
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            t = row["audit_turns"][0]
            self.assertEqual(
                t["slot_0"][
                    "selected_move_into_known_absorb_ally"
                ],
                True,
            )
            self.assertEqual(
                t["slot_1"][
                    "selected_move_into_known_absorb_ally"
                ],
                True,
            )
            self.assertEqual(
                t["slot_0"][
                    "selected_move_into_known_redirect_ally"
                ],
                True,
            )
            self.assertEqual(
                t["slot_1"][
                    "selected_move_into_known_redirect_ally"
                ],
                False,
            )
            self.assertEqual(
                t["slot_0"][
                    "selected_super_effective_into_weakness_policy_holder"
                ],
                False,
            )
            self.assertEqual(
                t["slot_1"][
                    "selected_super_effective_into_weakness_policy_holder"
                ],
                True,
            )


if __name__ == "__main__":
    unittest.main()
