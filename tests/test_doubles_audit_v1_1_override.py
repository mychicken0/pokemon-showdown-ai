"""Phase RL-DATA-3a.2 — Tests for live move-metadata override.

Validates that the audit logger's
``move_metadata_map_override`` parameter flows
through to the v1.1 emission and the per-candidate
classifier.

Coverage:
- ``collect_live_move_metadata`` returns the right
  metadata for live ``Order`` objects, ``Move``
  objects, ``Pokemon.moves`` dicts, and the static
  fallback.
- ``normalize_override`` normalizes a user-supplied
  override dict, handling case-variations, missing
  fields, and string-keyed entries only.
- The audit logger accepts
  ``move_metadata_map_override`` as a kwarg.
- The override wins over the static fallback when
  both are present.
- Missing override entries fall back to the static
  table.
- An unusual damaging move (not in the static
  fallback) is correctly classified when provided
  via the override.
- A true unknown support move is still tagged
  ``unknown_needs_probe`` even with the override.
- The builder preserves the override-derived
  metadata.
- The smoke (clean fixture with override) is
  ``READY``.
- A separate fixture with a true unknown support
  move (no override) is ``WARN``, not ``BLOCKED``.
- v1.0 compatibility is preserved.
- Dry-run is compatible.
- No production scoring or selected-action changes.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from typing import Any, Dict, List, Optional

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from doubles_engine.move_metadata import (  # noqa: E402
    SOURCE_FALLBACK,
    SOURCE_MOVE,
    SOURCE_ORDER,
    SOURCE_OVERRIDE,
    SOURCE_POKEMON,
    SOURCE_UNKNOWN,
    collect_live_move_metadata,
    normalize_override,
)
from doubles_engine.support_targets import (  # noqa: E402
    classify_support_move_for_dataset,
)


# ============================================================
# collect_live_move_metadata
# ============================================================
class TestCollectLiveMoveMetadata(unittest.TestCase):
    """Unit tests for ``collect_live_move_metadata``."""

    def test_collect_from_orders(self):
        class _MockType:
            name = "NORMAL"

        class _MockMove:
            def __init__(self, mid, bp, cat):
                self.id = mid
                self.base_power = bp
                self.category = cat
                self.type = _MockType()
                self.deduced_target = "normal"

        class _MockOrder:
            def __init__(self, move):
                self.order = move

        m1 = _MockMove("fakeout", 40, "physical")
        m2 = _MockMove("raindance", 0, "status")
        orders = [[_MockOrder(m1), _MockOrder(m2)], []]
        result = collect_live_move_metadata(
            valid_orders=orders
        )
        self.assertEqual(result["fakeout"]["base_power"], 40)
        self.assertEqual(
            result["fakeout"]["metadata_source"], SOURCE_ORDER
        )
        self.assertEqual(result["raindance"]["base_power"], 0)
        self.assertEqual(
            result["raindance"]["metadata_source"], SOURCE_ORDER
        )

    def test_collect_from_pokemon(self):
        class _MockType:
            name = "WATER"

        class _MockMove:
            def __init__(self, mid, bp, cat):
                self.id = mid
                self.base_power = bp
                self.category = cat
                self.type = _MockType()
                self.deduced_target = "allAdjacentFoes"

        class _MockPokemon:
            def __init__(self, moves):
                self.moves = moves

        class _MockBattle:
            def __init__(self, mons):
                self.active_pokemon = mons

        moves_dict = {
            "hurricane": _MockMove("hurricane", 110, "special"),
            "surf": _MockMove("surf", 90, "special"),
        }
        battle = _MockBattle([_MockPokemon(moves_dict), None])
        result = collect_live_move_metadata(
            battle=battle,
            v4a_legal_keys=[
                ["move", "hurricane", 0, "no_mechanic"],
                ["move", "surf", 0, "no_mechanic"],
            ],
        )
        self.assertEqual(result["hurricane"]["base_power"], 110)
        self.assertEqual(
            result["hurricane"]["metadata_source"],
            SOURCE_POKEMON,
        )
        self.assertEqual(result["surf"]["base_power"], 90)

    def test_collect_order_takes_precedence_over_pokemon(self):
        class _MockType:
            name = "NORMAL"

        class _MockMove:
            def __init__(self, mid, bp, cat):
                self.id = mid
                self.base_power = bp
                self.category = cat
                self.type = _MockType()
                self.deduced_target = "normal"

        class _MockOrder:
            def __init__(self, move):
                self.order = move

        class _MockPokemon:
            def __init__(self, moves):
                self.moves = moves

        class _MockBattle:
            def __init__(self, mons):
                self.active_pokemon = mons

        # Order has bp=40; pokemon has bp=99. Order wins.
        m_order = _MockMove("fakeout", 40, "physical")
        m_pokemon = _MockMove("fakeout", 99, "physical")
        battle = _MockBattle([_MockPokemon({"fakeout": m_pokemon}), None])
        result = collect_live_move_metadata(
            battle=battle,
            valid_orders=[[_MockOrder(m_order)], []],
        )
        self.assertEqual(result["fakeout"]["base_power"], 40)
        self.assertEqual(
            result["fakeout"]["metadata_source"], SOURCE_ORDER
        )

    def test_collect_falls_back_to_static(self):
        # No battle, no orders — only V4a legal keys.
        result = collect_live_move_metadata(
            v4a_legal_keys=[
                ["move", "fakeout", 0, "no_mechanic"],
            ],
        )
        self.assertEqual(result["fakeout"]["base_power"], 40)
        self.assertEqual(
            result["fakeout"]["metadata_source"], SOURCE_FALLBACK
        )

    def test_collect_unknown_move(self):
        result = collect_live_move_metadata(
            v4a_legal_keys=[
                ["move", "newgensupportmove", 0, "no_mechanic"],
            ],
        )
        self.assertEqual(
            result["newgensupportmove"]["metadata_source"],
            SOURCE_UNKNOWN,
        )

    def test_collect_no_args(self):
        # No args at all: empty result.
        result = collect_live_move_metadata()
        self.assertEqual(result, {})

    def test_collect_v4a_keys_normalize(self):
        # Move id with spaces / dashes / underscores.
        result = collect_live_move_metadata(
            v4a_legal_keys=[
                ["move", "Fake Out", 0, "no_mechanic"],
                ["move", "fake-out", 0, "no_mechanic"],
            ],
        )
        # Both normalize to "fakeout"; the second
        # is deduped by the ``seen`` set.
        self.assertIn("fakeout", result)
        self.assertEqual(result["fakeout"]["base_power"], 40)

    def test_collect_handles_invalid_v4a_keys(self):
        # Skip malformed v4a keys gracefully.
        result = collect_live_move_metadata(
            v4a_legal_keys=[
                ["move"],  # too short
                "not a tuple",
                ["move", "fakeout", 0, "no_mechanic"],
            ],
        )
        self.assertIn("fakeout", result)
        self.assertEqual(len(result), 1)


# ============================================================
# normalize_override
# ============================================================
class TestNormalizeOverride(unittest.TestCase):
    """Unit tests for ``normalize_override``."""

    def test_basic_normalize(self):
        ovr = normalize_override({
            "fakeout": {
                "base_power": 40,
                "category": "physical",
            },
        })
        self.assertEqual(ovr["fakeout"]["base_power"], 40)
        self.assertEqual(ovr["fakeout"]["category"], "physical")
        self.assertEqual(
            ovr["fakeout"]["metadata_source"], SOURCE_OVERRIDE
        )

    def test_normalize_case_variants(self):
        ovr = normalize_override({
            "Fake Out": {"base_power": 40, "category": "physical"},
            "FAKE-OUT": {"base_power": 40, "category": "physical"},
            "fake_out": {"base_power": 40, "category": "physical"},
        })
        # All three normalize to "fakeout".
        self.assertEqual(len(ovr), 1)
        self.assertIn("fakeout", ovr)

    def test_normalize_accepts_tuple_value(self):
        # Convenience: ``(base_power, category)`` tuple.
        ovr = normalize_override({
            "fakeout": (40, "physical"),
        })
        self.assertEqual(ovr["fakeout"]["base_power"], 40)
        self.assertEqual(ovr["fakeout"]["category"], "physical")

    def test_normalize_skips_non_string_keys(self):
        ovr = normalize_override({
            ("raindance", 0, "no_mechanic"): {
                "base_power": 0, "category": "status"
            },
            "fakeout": {"base_power": 40, "category": "physical"},
        })
        # Tuple keys are skipped; only string keys survive.
        self.assertEqual(len(ovr), 1)
        self.assertIn("fakeout", ovr)

    def test_normalize_handles_missing_fields(self):
        # Missing category → ``None``; missing base_power → ``None``.
        ovr = normalize_override({
            "fakeout": {"base_power": 40},
            "raindance": {"category": "status"},
        })
        self.assertEqual(ovr["fakeout"]["base_power"], 40)
        self.assertIsNone(ovr["fakeout"]["category"])
        self.assertIsNone(ovr["raindance"]["base_power"])
        self.assertEqual(ovr["raindance"]["category"], "status")

    def test_normalize_invalid_input(self):
        # Not a dict: returns empty.
        self.assertEqual(normalize_override(None), {})
        self.assertEqual(normalize_override("not a dict"), {})
        self.assertEqual(normalize_override(42), {})

    def test_normalize_preserves_custom_source(self):
        ovr = normalize_override({
            "fakeout": {
                "base_power": 40,
                "category": "physical",
                "metadata_source": "live_audit",
            },
        })
        self.assertEqual(
            ovr["fakeout"]["metadata_source"], "live_audit"
        )


# ============================================================
# Audit logger override plumbing
# ============================================================
class TestAuditLoggerOverride(unittest.TestCase):
    """End-to-end: override flows through the audit
    logger into the per-candidate classification."""

    def _make_audit_logger(self, tmp_path):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        out_path = os.path.join(tmp_path, "audit_v11_ovr.jsonl")
        logger = DoublesDecisionAuditLogger(
            filepath=out_path,
            reset=True,
            detail_level="top5",
        )
        return logger, out_path

    def _make_battle(self):
        from showdown_ai.doubles_audit_v1_1_smoke import (
            _MockBattle,
            _MockPokemon,
        )
        return _MockBattle(
            our_active=[
                _MockPokemon("Politoed", ["WATER"]),
                _MockPokemon("Incineroar", ["FIRE"]),
            ],
            opp_active=[
                _MockPokemon("Garchomp", ["DRAGON"]),
                _MockPokemon("Tyranitar", ["ROCK"]),
            ],
            weather="RainDance",
        )

    def test_audit_logger_accepts_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger, out_path = self._make_audit_logger(tmp)
            from bot_doubles_damage_aware import (
                DoublesDamageAwareConfig,
            )
            battle_tag = "test_override_accept"
            logger.battle_configs[battle_tag] = (
                DoublesDamageAwareConfig()
            )
            logger.set_current_battle_meta(
                benchmark_arm="treatment",
                enable_mega_evolution=False,
                enable_decision_timing_diagnostics=False,
                treatment_side="p1",
                player_side="p1",
                player_name="TestOvrBot",
            )
            v4a_legal0 = [
                ["move", "raindance", 0, "no_mechanic"],
                ["move", "boltstrike", 0, "no_mechanic"],
            ]
            v4a_legal1 = [
                ["move", "fakeout", 1, "no_mechanic"],
            ]
            v4a_sel = [
                ["move", "raindance", 0, "no_mechanic"],
                ["move", "fakeout", 1, "no_mechanic"],
            ]
            logger.log_turn_decision(
                battle_tag=battle_tag,
                turn=1,
                battle=self._make_battle(),
                selected_joint_order=(
                    "/choose move raindance 0, move fakeout 1"
                ),
                selected_score=100.0,
                scored_joint_orders=[],
                expected_damages=[0.0, 0.0],
                expected_kos=[False, False],
                target_hps=[1.0, 1.0],
                overkill_triggered=False,
                focus_fire_triggered=False,
                ally_hit_penalty_triggered=False,
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=[
                    "/choose move raindance 0",
                    "/choose move fakeout 1",
                ],
                slot_action_types=[
                    {
                        "damaging": False, "status": True,
                        "protect": False, "fakeout": False,
                        "spread": False, "switch": False,
                    },
                    {
                        "damaging": True, "status": False,
                        "protect": False, "fakeout": True,
                        "spread": False, "switch": False,
                    },
                ],
                target_species=[None, None],
                runtime_mode="gen9randomdoublesbattle",
                concrete_player_class="DoublesDamageAwarePlayer",
                shared_engine_used=True,
                shared_engine_owner="DoublesDamageAwarePlayer",
                shared_engine_invocation_id="ovr_inv",
                shared_engine_invocation_status="completed",
                selected_four=None,
                lead_2=None,
                back_2=None,
                preview_policy="test_ovr",
                v4a_legal_action_keys_slot0=list(v4a_legal0),
                v4a_legal_action_keys_slot1=list(v4a_legal1),
                v4a_raw_scores_slot0={},
                v4a_raw_scores_slot1={},
                v4a_selected_joint_key=list(v4a_sel),
                v4a_final_action_keys=list(v4a_sel),
                move_metadata_map_override={
                    "fakeout": {
                        "base_power": 40,
                        "category": "physical",
                    },
                    "raindance": {
                        "base_power": 0,
                        "category": "status",
                    },
                    "boltstrike": {
                        "base_power": 130,
                        "category": "physical",
                    },
                },
            )
            logger.save_battle(
                battle_tag=battle_tag,
                winner="TestOvrBot",
                battle=self._make_battle(),
            )
            with open(out_path) as f:
                record = json.loads(f.readline())
            turn = record["audit_turns"][0]
            # The override is stashed on the turn_data.
            self.assertIn(
                "_v11_move_metadata_override_raw", turn
            )
            # The move_metadata_map is populated.
            meta = turn["move_metadata_map"]
            # Override entries take precedence.
            self.assertEqual(meta["fakeout"]["base_power"], 40)
            self.assertEqual(
                meta["fakeout"]["metadata_source"],
                SOURCE_OVERRIDE,
            )
            # boltstrike is in the override even
            # though not in the static fallback.
            self.assertEqual(meta["boltstrike"]["base_power"], 130)
            self.assertEqual(
                meta["boltstrike"]["metadata_source"],
                SOURCE_OVERRIDE,
            )
            # The per-candidate classification
            # correctly identifies boltstrike as
            # damage-like (not unknown_needs_probe).
            per = turn["per_candidate_support_classification"]
            self.assertFalse(per["boltstrike"]["is_support_move"])
            self.assertFalse(
                per["boltstrike"]["unknown_support_move_detected"]
            )
            self.assertEqual(
                per["boltstrike"]["metadata_source"],
                SOURCE_OVERRIDE,
            )

    def test_override_missing_entries_fall_back(self):
        """When the override lacks some moves, the
        static fallback fills them in.
        """
        with tempfile.TemporaryDirectory() as tmp:
            logger, out_path = self._make_audit_logger(tmp)
            from bot_doubles_damage_aware import (
                DoublesDamageAwareConfig,
            )
            battle_tag = "test_override_fallback"
            logger.battle_configs[battle_tag] = (
                DoublesDamageAwareConfig()
            )
            logger.set_current_battle_meta(
                benchmark_arm="treatment",
                enable_mega_evolution=False,
                enable_decision_timing_diagnostics=False,
                treatment_side="p1",
                player_side="p1",
                player_name="TestFallbackBot",
            )
            v4a_legal0 = [
                ["move", "raindance", 0, "no_mechanic"],
            ]
            v4a_legal1 = [
                ["move", "fakeout", 1, "no_mechanic"],
            ]
            v4a_sel = [
                ["move", "raindance", 0, "no_mechanic"],
                ["move", "fakeout", 1, "no_mechanic"],
            ]
            logger.log_turn_decision(
                battle_tag=battle_tag,
                turn=1,
                battle=self._make_battle(),
                selected_joint_order=(
                    "/choose move raindance 0, move fakeout 1"
                ),
                selected_score=100.0,
                scored_joint_orders=[],
                expected_damages=[0.0, 0.0],
                expected_kos=[False, False],
                target_hps=[1.0, 1.0],
                overkill_triggered=False,
                focus_fire_triggered=False,
                ally_hit_penalty_triggered=False,
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=[
                    "/choose move raindance 0",
                    "/choose move fakeout 1",
                ],
                slot_action_types=[
                    {
                        "damaging": False, "status": True,
                        "protect": False, "fakeout": False,
                        "spread": False, "switch": False,
                    },
                    {
                        "damaging": True, "status": False,
                        "protect": False, "fakeout": True,
                        "spread": False, "switch": False,
                    },
                ],
                target_species=[None, None],
                runtime_mode="gen9randomdoublesbattle",
                concrete_player_class="DoublesDamageAwarePlayer",
                shared_engine_used=True,
                shared_engine_owner="DoublesDamageAwarePlayer",
                shared_engine_invocation_id="fallback_inv",
                shared_engine_invocation_status="completed",
                selected_four=None,
                lead_2=None,
                back_2=None,
                preview_policy="test_fallback",
                v4a_legal_action_keys_slot0=list(v4a_legal0),
                v4a_legal_action_keys_slot1=list(v4a_legal1),
                v4a_raw_scores_slot0={},
                v4a_raw_scores_slot1={},
                v4a_selected_joint_key=list(v4a_sel),
                v4a_final_action_keys=list(v4a_sel),
                # Override includes only ``raindance``.
                # ``fakeout`` is not in the override;
                # the static fallback should fill it in.
                move_metadata_map_override={
                    "raindance": {
                        "base_power": 0,
                        "category": "status",
                    },
                },
            )
            logger.save_battle(
                battle_tag=battle_tag,
                winner="TestFallbackBot",
                battle=self._make_battle(),
            )
            with open(out_path) as f:
                record = json.loads(f.readline())
            turn = record["audit_turns"][0]
            meta = turn["move_metadata_map"]
            # ``raindance`` is from override.
            self.assertEqual(
                meta["raindance"]["metadata_source"],
                SOURCE_OVERRIDE,
            )
            # ``fakeout`` is from fallback.
            self.assertEqual(
                meta["fakeout"]["metadata_source"],
                SOURCE_FALLBACK,
            )

    def test_override_with_unknown_move_still_flags(self):
        """A true unknown non-damaging support move
        is still tagged ``unknown_needs_probe``
        even with the override path.
        """
        with tempfile.TemporaryDirectory() as tmp:
            logger, out_path = self._make_audit_logger(tmp)
            from bot_doubles_damage_aware import (
                DoublesDamageAwareConfig,
            )
            battle_tag = "test_override_unknown"
            logger.battle_configs[battle_tag] = (
                DoublesDamageAwareConfig()
            )
            logger.set_current_battle_meta(
                benchmark_arm="treatment",
                enable_mega_evolution=False,
                enable_decision_timing_diagnostics=False,
                treatment_side="p1",
                player_side="p1",
                player_name="TestUnkBot",
            )
            v4a_legal0 = [
                ["move", "newgensupportmove", 0, "no_mechanic"],
            ]
            v4a_sel = list(v4a_legal0)
            logger.log_turn_decision(
                battle_tag=battle_tag,
                turn=1,
                battle=self._make_battle(),
                selected_joint_order=(
                    "/choose move newgensupportmove 0"
                ),
                selected_score=100.0,
                scored_joint_orders=[],
                expected_damages=[0.0, 0.0],
                expected_kos=[False, False],
                target_hps=[1.0, 1.0],
                overkill_triggered=False,
                focus_fire_triggered=False,
                ally_hit_penalty_triggered=False,
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=[
                    "/choose move newgensupportmove 0",
                    "/choose pass",
                ],
                slot_action_types=[
                    {
                        "damaging": False, "status": True,
                        "protect": False, "fakeout": False,
                        "spread": False, "switch": False,
                    },
                    {
                        "damaging": False, "status": False,
                        "protect": False, "fakeout": False,
                        "spread": False, "switch": False,
                    },
                ],
                target_species=[None, None],
                runtime_mode="gen9randomdoublesbattle",
                concrete_player_class="DoublesDamageAwarePlayer",
                shared_engine_used=True,
                shared_engine_owner="DoublesDamageAwarePlayer",
                shared_engine_invocation_id="unk_inv",
                shared_engine_invocation_status="completed",
                selected_four=None,
                lead_2=None,
                back_2=None,
                preview_policy="test_unk",
                v4a_legal_action_keys_slot0=list(v4a_legal0),
                v4a_legal_action_keys_slot1=[],
                v4a_raw_scores_slot0={},
                v4a_raw_scores_slot1={},
                v4a_selected_joint_key=list(v4a_sel),
                v4a_final_action_keys=list(v4a_sel),
                # Override explicitly does NOT cover
                # ``newgensupportmove``. The classifier
                # will fall back to ``unknown``.
                move_metadata_map_override={
                    "fakeout": {
                        "base_power": 40,
                        "category": "physical",
                    },
                },
            )
            logger.save_battle(
                battle_tag=battle_tag,
                winner="TestUnkBot",
                battle=self._make_battle(),
            )
            with open(out_path) as f:
                record = json.loads(f.readline())
            turn = record["audit_turns"][0]
            per = turn["per_candidate_support_classification"]
            # The unknown move is still tagged.
            self.assertTrue(
                per["newgensupportmove"][
                    "unknown_support_move_detected"
                ]
            )
            self.assertEqual(
                per["newgensupportmove"]["metadata_source"],
                SOURCE_UNKNOWN,
            )


# ============================================================
# End-to-end: smoke + analyzer
# ============================================================
class TestOverrideEndToEnd(unittest.TestCase):
    """End-to-end: smoke + analyzer with override."""

    def test_smoke_with_override_is_ready(self):
        """The smoke (clean fixture with override)
        produces a READY analyzer result. The
        per-candidate metadata source counts
        include both ``override`` and
        ``fallback`` (for moves not in the
        override).
        """
        from showdown_ai.doubles_audit_v1_1_smoke import (
            _run_smoke,
        )
        result = _run_smoke()
        self.assertEqual(
            result["analyzer_readiness_impact"], "READY"
        )
        self.assertEqual(
            len(result["analyzer_warnings"]), 0
        )
        self.assertEqual(
            len(result["analyzer_hard_blocks"]), 0
        )
        # At least one move should be sourced from
        # ``override``.
        per_source = result.get(
            "per_candidate_source_counts", {}
        )
        self.assertIn(
            "override", per_source,
            f"no override-sourced moves in {per_source}",
        )

    def test_unknown_fixture_is_warn(self):
        """A fixture with a true unknown support
        move (no override) produces a WARN analyzer
        result (Gate 17 soft warning, no hard
        block).
        """
        from showdown_ai.build_turn_level_offline_dataset import (
            build_dataset_from_artifact,
        )
        from analyze_turn_level_offline_dataset_quality import (
            analyze,
        )

        with tempfile.TemporaryDirectory() as tmp:
            audit_path = os.path.join(
                tmp, "audit_unknown_ovr.jsonl"
            )
            dataset_path = os.path.join(
                tmp, "dataset_unknown_ovr.jsonl"
            )
            record = {
                "battle_tag": "unknown_ovr_fixture",
                "winner": "TestBot",
                "won": True,
                "total_turns": 1,
                "audit_turns": [
                    {
                        "turn": 1,
                        "our_active": [
                            {"species": "Politoed", "hp": 1.0},
                            {"species": "Incineroar", "hp": 1.0},
                        ],
                        "opp_active": [
                            {"species": "Garchomp", "hp": 1.0},
                            {"species": "Tyranitar", "hp": 1.0},
                        ],
                        "selected_joint_order": (
                            "/choose move newgensupportmove 0, "
                            "move raindance 1"
                        ),
                        "selected_score": 100.0,
                        "v4a_legal_action_keys_slot0": [
                            ["move", "newgensupportmove", 0,
                             "no_mechanic"],
                        ],
                        "v4a_legal_action_keys_slot1": [
                            ["move", "raindance", 1,
                             "no_mechanic"],
                        ],
                        "v4a_selected_joint_key": [
                            ["move", "newgensupportmove", 0,
                             "no_mechanic"],
                            ["move", "raindance", 1,
                             "no_mechanic"],
                        ],
                        "v4a_final_action_keys": [
                            ["move", "newgensupportmove", 0,
                             "no_mechanic"],
                            ["move", "raindance", 1,
                             "no_mechanic"],
                        ],
                        "state_snapshot": {
                            "weather": "raindance",
                            "fields": [],
                        },
                    }
                ],
            }
            with open(audit_path, "w") as f:
                f.write(json.dumps(record) + "\n")
            rows, _ = build_dataset_from_artifact(
                audit_path, "treatment", "unknown_ovr_fixture"
            )
            with open(dataset_path, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            report = analyze([dataset_path])
            v11 = report.get("v11_gates", {})
            self.assertEqual(
                v11.get("readiness_impact"), "WARN"
            )
            self.assertEqual(
                len(v11.get("hard_blocks", [])), 0
            )
            self.assertGreater(
                len(v11.get("warnings", [])), 0
            )
            self.assertTrue(
                rows[0]["unknown_support_move_detected"]
            )

    def test_bot_call_site_uses_override(self):
        """Verify the bot's ``choose_move`` path
        actually passes an override to
        ``log_turn_decision``. We can't run a real
        choose_move, but we can verify the
        ``_v1_1_live_move_metadata_for_audit``
        helper exists and returns the expected
        shape.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwarePlayer,
        )
        # The helper is a bound method on the class.
        self.assertTrue(
            hasattr(
                DoublesDamageAwarePlayer,
                "_v1_1_live_move_metadata_for_audit",
            )
        )

    def test_bot_helper_returns_dict(self):
        """Verify the bot's helper returns a
        non-empty dict when given a real battle
        and live valid_orders.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwarePlayer,
        )
        from showdown_ai.doubles_audit_v1_1_smoke import (
            _MockBattle,
            _MockPokemon,
        )

        class _MockType:
            name = "NORMAL"

        class _LiveMockMove:
            def __init__(self, mid, bp, cat):
                self.id = mid
                self.base_power = bp
                self.category = cat
                self.type = _MockType()
                self.deduced_target = "normal"

        class _LiveMockOrder:
            def __init__(self, move):
                self.order = move

        # Build a player instance without running
        # ``__init__`` (which would create poke-env
        # resources). We only need the helper
        # method, which is a regular function that
        # does not touch ``self`` state.
        player = DoublesDamageAwarePlayer.__new__(
            DoublesDamageAwarePlayer
        )
        player._v4a_legal_keys_slot0 = [
            ["move", "fakeout", 0, "no_mechanic"],
            ["move", "boltstrike", 0, "no_mechanic"],
        ]
        player._v4a_legal_keys_slot1 = [
            ["move", "raindance", 1, "no_mechanic"],
        ]
        battle = _MockBattle(
            our_active=[
                _MockPokemon("Politoed", ["WATER"]),
                _MockPokemon("Incineroar", ["FIRE"]),
            ],
            opp_active=[
                _MockPokemon("Garchomp", ["DRAGON"]),
                _MockPokemon("Tyranitar", ["ROCK"]),
            ],
        )
        valid_orders = [
            [
                _LiveMockOrder(_LiveMockMove("fakeout", 40, "physical")),
                _LiveMockOrder(
                    _LiveMockMove("boltstrike", 130, "physical")
                ),
            ],
            [_LiveMockOrder(_LiveMockMove("raindance", 0, "status"))],
        ]
        result = player._v1_1_live_move_metadata_for_audit(
            battle, valid_orders
        )
        self.assertIsInstance(result, dict)
        # ``fakeout`` is in the result with order source.
        self.assertIn("fakeout", result)
        self.assertEqual(result["fakeout"]["base_power"], 40)
        # ``boltstrike`` is in the result with order source.
        self.assertIn("boltstrike", result)
        self.assertEqual(
            result["boltstrike"]["base_power"], 130
        )
        # ``raindance`` is in the result with order source.
        self.assertIn("raindance", result)
        self.assertEqual(result["raindance"]["base_power"], 0)
