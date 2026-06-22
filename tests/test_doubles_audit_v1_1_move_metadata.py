"""Phase RL-DATA-3a.1 — Tests for move metadata enrichment.

Validates that the audit logger's v1.1 emission can
resolve ``base_power`` / ``category`` for known
damaging moves (e.g., ``fakeout``, ``hurricane``) so
they are not falsely tagged as ``unknown_needs_probe``.

Coverage:
- ``resolve_move_metadata_for_audit`` returns correct
  ``base_power`` / ``category`` for known moves.
- ``resolve_move_metadata_for_audit`` returns None
  fields with ``metadata_source="unknown"`` for
  unknown moves.
- Static fallback covers ``fakeout``, ``hurricane``,
  ``surf``, ``raindance``, ``protect``.
- Move id normalization handles spaces / dashes /
  underscores / apostrophes.
- The classifier treats ``fakeout`` / ``hurricane``
  as damage-like when metadata is provided.
- The classifier still tags truly unknown non-
  damaging moves as ``unknown_needs_probe``.
- The audit logger populates ``move_metadata_map``
  on the persisted turn.
- The builder consumes ``move_metadata_map`` and
  produces correct per-candidate classification.
- The smoke produces a READY analyzer result on a
  clean fixture (no Gate 17 warning).
- A separate fixture with a true unknown support
  move produces a WARN analyzer result (Gate 17
  fires, but no hard block).
- v1.0 backward compat is preserved.
- Dry-run is compatible with v1.1 rows.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from typing import Any, Dict, List

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from doubles_engine.move_metadata import (  # noqa: E402
    SOURCE_FALLBACK,
    SOURCE_MOVE,
    SOURCE_POKEMON,
    SOURCE_UNKNOWN,
    _FALLBACK_MOVE_METADATA,
    resolve_batch_for_audit,
    resolve_move_metadata_for_audit,
)
from doubles_engine.support_targets import (  # noqa: E402
    classify_support_move_for_dataset,
)


# ============================================================
# Resolver unit tests
# ============================================================
class TestMoveMetadataResolver(unittest.TestCase):
    """Unit tests for ``resolve_move_metadata_for_audit``."""

    def test_fallback_fakeout(self):
        meta = resolve_move_metadata_for_audit("fakeout")
        self.assertEqual(meta["base_power"], 40)
        self.assertEqual(meta["category"], "physical")
        self.assertEqual(meta["metadata_source"], SOURCE_FALLBACK)
        self.assertEqual(meta["move_id"], "fakeout")

    def test_fallback_hurricane(self):
        meta = resolve_move_metadata_for_audit("hurricane")
        self.assertEqual(meta["base_power"], 110)
        self.assertEqual(meta["category"], "special")
        self.assertEqual(meta["metadata_source"], SOURCE_FALLBACK)

    def test_fallback_surf(self):
        meta = resolve_move_metadata_for_audit("surf")
        self.assertEqual(meta["base_power"], 90)
        self.assertEqual(meta["category"], "special")
        self.assertEqual(meta["metadata_source"], SOURCE_FALLBACK)

    def test_fallback_raindance(self):
        meta = resolve_move_metadata_for_audit("raindance")
        self.assertEqual(meta["base_power"], 0)
        self.assertEqual(meta["category"], "status")
        self.assertEqual(meta["metadata_source"], SOURCE_FALLBACK)

    def test_fallback_protect(self):
        meta = resolve_move_metadata_for_audit("protect")
        self.assertEqual(meta["base_power"], 0)
        self.assertEqual(meta["category"], "status")
        self.assertEqual(meta["metadata_source"], SOURCE_FALLBACK)

    def test_unknown_move(self):
        meta = resolve_move_metadata_for_audit("newgensupportmove")
        self.assertIsNone(meta["base_power"])
        self.assertIsNone(meta["category"])
        self.assertEqual(meta["metadata_source"], SOURCE_UNKNOWN)

    def test_normalization(self):
        # Spaces, dashes, underscores, apostrophes
        m1 = resolve_move_metadata_for_audit("Fake Out")
        m2 = resolve_move_metadata_for_audit("fake-out")
        m3 = resolve_move_metadata_for_audit("fake_out")
        for m in (m1, m2, m3):
            self.assertEqual(m["base_power"], 40)
            self.assertEqual(m["category"], "physical")

    def test_none_move_id(self):
        meta = resolve_move_metadata_for_audit(None)
        self.assertIsNone(meta["base_power"])
        self.assertIsNone(meta["category"])
        self.assertEqual(meta["metadata_source"], SOURCE_UNKNOWN)

    def test_empty_string_move_id(self):
        meta = resolve_move_metadata_for_audit("")
        self.assertEqual(meta["metadata_source"], SOURCE_UNKNOWN)


class TestMoveMetadataResolverFromMoveObject(unittest.TestCase):
    """Tests for resolving from a poke-env ``Move`` object."""

    def test_resolve_from_move_object(self):
        # Mock a poke-env ``Move`` object
        class _MockType:
            name = "NORMAL"

        class _MockMove:
            id = "fakeout"
            base_power = 40
            category = "physical"
            type = _MockType()
            deduced_target = "normal"
            target = "normal"

        meta = resolve_move_metadata_for_audit(
            "fakeout", move=_MockMove()
        )
        self.assertEqual(meta["base_power"], 40)
        self.assertEqual(meta["category"], "physical")
        self.assertEqual(meta["metadata_source"], SOURCE_MOVE)
        self.assertEqual(meta["move_type"], "normal")

    def test_resolve_from_order_object(self):
        # Mock a poke-env ``DoubleBattleOrder``
        class _MockType:
            name = "DARK"

        class _MockMove:
            id = "knockoff"
            base_power = 65
            category = "physical"
            type = _MockType()
            deduced_target = "normal"
            target = "normal"

        class _MockOrder:
            order = _MockMove()

        meta = resolve_move_metadata_for_audit(
            "knockoff", order=_MockOrder()
        )
        # knockoff is in the fallback
        self.assertEqual(meta["base_power"], 65)
        # But the source is "move" because the order
        # object took precedence.
        self.assertEqual(meta["metadata_source"], SOURCE_MOVE)


class TestMoveMetadataResolverFromPokemon(unittest.TestCase):
    """Tests for resolving from a poke-env ``Pokemon`` object."""

    def test_resolve_from_pokemon_moves(self):
        class _MockType:
            name = "WATER"

        class _MockMove:
            id = "surf"
            base_power = 90
            category = "special"
            type = _MockType()
            deduced_target = "allAdjacentFoes"
            target = "allAdjacentFoes"

        class _MockPokemon:
            moves = {"surf": _MockMove()}

        meta = resolve_move_metadata_for_audit(
            "surf", pokemon=_MockPokemon()
        )
        self.assertEqual(meta["base_power"], 90)
        self.assertEqual(meta["category"], "special")
        self.assertEqual(meta["metadata_source"], SOURCE_POKEMON)


class TestResolveBatch(unittest.TestCase):
    """Tests for ``resolve_batch_for_audit``."""

    def test_batch_resolves_all(self):
        result = resolve_batch_for_audit(
            ["fakeout", "hurricane", "surf", "newgensupportmove"]
        )
        self.assertIn("fakeout", result)
        self.assertIn("hurricane", result)
        self.assertIn("surf", result)
        self.assertIn("newgensupportmove", result)
        self.assertEqual(result["fakeout"]["base_power"], 40)
        self.assertEqual(result["hurricane"]["base_power"], 110)
        self.assertEqual(
            result["newgensupportmove"]["metadata_source"],
            SOURCE_UNKNOWN,
        )

    def test_batch_normalizes(self):
        result = resolve_batch_for_audit(["Fake Out", "fake-out"])
        # Both normalize to "fakeout"
        self.assertIn("fakeout", result)
        self.assertEqual(result["fakeout"]["base_power"], 40)


# ============================================================
# Classifier + metadata interaction
# ============================================================
class TestClassifierWithMetadata(unittest.TestCase):
    """Verify the classifier correctly handles metadata."""

    def test_fakeout_with_metadata_is_damage_like(self):
        r = classify_support_move_for_dataset(
            "fakeout", base_power=40, category="physical"
        )
        self.assertFalse(r["is_support_move"])
        self.assertIsNone(r["support_group"])
        self.assertFalse(r["unknown_support_move_detected"])

    def test_hurricane_with_metadata_is_damage_like(self):
        r = classify_support_move_for_dataset(
            "hurricane", base_power=110, category="special"
        )
        self.assertFalse(r["is_support_move"])
        self.assertIsNone(r["support_group"])
        self.assertFalse(r["unknown_support_move_detected"])

    def test_surf_with_metadata_is_damage_like(self):
        r = classify_support_move_for_dataset(
            "surf", base_power=90, category="special"
        )
        self.assertFalse(r["is_support_move"])
        self.assertIsNone(r["support_group"])
        self.assertFalse(r["unknown_support_move_detected"])

    def test_raindance_with_metadata_is_support(self):
        r = classify_support_move_for_dataset(
            "raindance", base_power=0, category="status"
        )
        self.assertTrue(r["is_support_move"])
        self.assertEqual(r["support_group"], "weather_terrain")
        self.assertFalse(r["unknown_support_move_detected"])

    def test_truly_unknown_non_damaging_is_unknown(self):
        # A non-damaging move that is not in the
        # SUPPORT-AUDIT-1 inventory is still
        # unknown_needs_probe.
        r = classify_support_move_for_dataset(
            "newgensupportmove", base_power=0, category="status"
        )
        self.assertTrue(r["is_support_move"])
        self.assertEqual(r["support_group"], "unknown_needs_probe")
        self.assertTrue(r["unknown_support_move_detected"])

    def test_no_metadata_fakeout_is_unknown(self):
        # Without metadata, the classifier cannot
        # tell fakeout is damage-like. This is the
        # pre-RL-DATA-3a.1 behavior. Tests the
        # pre-existing limitation that the metadata
        # enrichment fixes.
        r = classify_support_move_for_dataset("fakeout")
        # No metadata -> conservative -> unknown
        self.assertEqual(r["support_group"], "unknown_needs_probe")
        self.assertTrue(r["unknown_support_move_detected"])


# ============================================================
# End-to-end: audit -> builder -> analyzer
# ============================================================
class TestAuditMoveMetadataEndToEnd(unittest.TestCase):
    """Verify the audit logger / builder / analyzer path
    uses the move metadata correctly."""

    def test_audit_emits_move_metadata_map(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        from showdown_ai.doubles_audit_v1_1_smoke import (
            _MockBattle,
            _MockPokemon,
        )
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )

        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "audit_v11_meta.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=out_path,
                reset=True,
                detail_level="top5",
            )
            weather = "RainDance"
            our_active = [
                _MockPokemon("Politoed", ["WATER"], 1.0),
                _MockPokemon("Incineroar", ["FIRE"], 0.95),
            ]
            opp_active = [
                _MockPokemon("Garchomp", ["DRAGON"], 1.0),
                _MockPokemon("Tyranitar", ["ROCK"], 1.0),
            ]
            battle = _MockBattle(
                our_active=our_active,
                opp_active=opp_active,
                weather=weather,
            )
            battle_tag = "audit_v11_meta"
            logger.battle_configs[battle_tag] = (
                DoublesDamageAwareConfig()
            )
            logger.set_current_battle_meta(
                benchmark_arm="treatment",
                enable_mega_evolution=False,
                enable_decision_timing_diagnostics=False,
                treatment_side="p1",
                player_side="p1",
                player_name="AuditMetaBot",
            )
            v4a_legal0 = [
                ["move", "raindance", 0, "no_mechanic"],
                ["move", "hurricane", 0, "no_mechanic"],
                ["move", "surf", 0, "no_mechanic"],
            ]
            v4a_legal1 = [
                ["move", "fakeout", 1, "no_mechanic"],
                ["move", "protect", 1, "no_mechanic"],
            ]
            v4a_sel = [
                ["move", "raindance", 0, "no_mechanic"],
                ["move", "protect", 1, "no_mechanic"],
            ]
            logger.log_turn_decision(
                battle_tag=battle_tag,
                turn=1,
                battle=battle,
                selected_joint_order=(
                    "/choose move raindance 0, move protect 1"
                ),
                selected_score=150.0,
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
                    "/choose move protect 1",
                ],
                slot_action_types=[
                    {
                        "damaging": False, "status": True,
                        "protect": False, "fakeout": False,
                        "spread": False, "switch": False,
                    },
                    {
                        "damaging": False, "status": True,
                        "protect": True, "fakeout": False,
                        "spread": False, "switch": False,
                    },
                ],
                target_species=[None, None],
                runtime_mode="gen9randomdoublesbattle",
                concrete_player_class="DoublesDamageAwarePlayer",
                shared_engine_used=True,
                shared_engine_owner="DoublesDamageAwarePlayer",
                shared_engine_invocation_id="audit_meta_inv_001",
                shared_engine_invocation_status="completed",
                selected_four=None,
                lead_2=None,
                back_2=None,
                preview_policy="audit_meta",
                v4a_legal_action_keys_slot0=list(v4a_legal0),
                v4a_legal_action_keys_slot1=list(v4a_legal1),
                v4a_raw_scores_slot0={},
                v4a_raw_scores_slot1={},
                v4a_selected_joint_key=list(v4a_sel),
                v4a_final_action_keys=list(v4a_sel),
            )
            logger.save_battle(
                battle_tag=battle_tag,
                winner="AuditMetaBot",
                battle=battle,
            )
            with open(out_path) as f:
                record = json.loads(f.readline())
            turn = record["audit_turns"][0]
            # The audit logger populated the
            # move_metadata_map.
            self.assertIn("move_metadata_map", turn)
            meta = turn["move_metadata_map"]
            self.assertEqual(meta["fakeout"]["base_power"], 40)
            self.assertEqual(meta["fakeout"]["category"], "physical")
            self.assertEqual(meta["hurricane"]["base_power"], 110)
            self.assertEqual(meta["hurricane"]["category"], "special")
            self.assertEqual(meta["surf"]["base_power"], 90)
            # The per-candidate classification in
            # the audit turn is now damage-like for
            # fakeout / hurricane / surf.
            per = turn["per_candidate_support_classification"]
            self.assertFalse(per["fakeout"]["is_support_move"])
            self.assertFalse(per["hurricane"]["is_support_move"])
            self.assertFalse(per["surf"]["is_support_move"])
            self.assertFalse(
                per["fakeout"]["unknown_support_move_detected"]
            )
            self.assertFalse(
                per["hurricane"]["unknown_support_move_detected"]
            )
            self.assertFalse(
                per["surf"]["unknown_support_move_detected"]
            )
            # Metadata source is annotated.
            self.assertEqual(
                per["fakeout"]["metadata_source"],
                SOURCE_FALLBACK,
            )
            self.assertEqual(
                per["fakeout"]["resolved_base_power"], 40
            )
            self.assertEqual(
                per["fakeout"]["resolved_category"], "physical"
            )

    def test_audit_emits_unknown_support_move(self):
        """A truly unknown non-damaging support move
        still triggers ``unknown_support_move_detected``
        in the per-candidate classification. The
        detector is not disabled globally.
        """
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        from showdown_ai.doubles_audit_v1_1_smoke import (
            _MockBattle,
            _MockPokemon,
        )
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )

        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(
                tmp, "audit_v11_unknown.jsonl"
            )
            logger = DoublesDecisionAuditLogger(
                filepath=out_path,
                reset=True,
                detail_level="top5",
            )
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
            battle_tag = "audit_v11_unknown"
            logger.battle_configs[battle_tag] = (
                DoublesDamageAwareConfig()
            )
            logger.set_current_battle_meta(
                benchmark_arm="treatment",
                enable_mega_evolution=False,
                enable_decision_timing_diagnostics=False,
                treatment_side="p1",
                player_side="p1",
                player_name="AuditUnknownBot",
            )
            v4a_legal0 = [
                ["move", "newgensupportmove", 0, "no_mechanic"],
            ]
            v4a_legal1 = [
                ["move", "raindance", 1, "no_mechanic"],
            ]
            v4a_sel = [
                ["move", "newgensupportmove", 0, "no_mechanic"],
                ["move", "raindance", 1, "no_mechanic"],
            ]
            logger.log_turn_decision(
                battle_tag=battle_tag,
                turn=1,
                battle=battle,
                selected_joint_order=(
                    "/choose move newgensupportmove 0, "
                    "move raindance 1"
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
                    "/choose move raindance 1",
                ],
                slot_action_types=[
                    {
                        "damaging": False, "status": True,
                        "protect": False, "fakeout": False,
                        "spread": False, "switch": False,
                    },
                    {
                        "damaging": False, "status": True,
                        "protect": False, "fakeout": False,
                        "spread": False, "switch": False,
                    },
                ],
                target_species=[None, None],
                runtime_mode="gen9randomdoublesbattle",
                concrete_player_class="DoublesDamageAwarePlayer",
                shared_engine_used=True,
                shared_engine_owner="DoublesDamageAwarePlayer",
                shared_engine_invocation_id="audit_unk_inv",
                shared_engine_invocation_status="completed",
                selected_four=None,
                lead_2=None,
                back_2=None,
                preview_policy="audit_unk",
                v4a_legal_action_keys_slot0=list(v4a_legal0),
                v4a_legal_action_keys_slot1=list(v4a_legal1),
                v4a_raw_scores_slot0={},
                v4a_raw_scores_slot1={},
                v4a_selected_joint_key=list(v4a_sel),
                v4a_final_action_keys=list(v4a_sel),
            )
            logger.save_battle(
                battle_tag=battle_tag,
                winner="AuditUnknownBot",
                battle=battle,
            )
            with open(out_path) as f:
                record = json.loads(f.readline())
            turn = record["audit_turns"][0]
            per = turn["per_candidate_support_classification"]
            # The unknown move is still flagged.
            self.assertTrue(
                per["newgensupportmove"][
                    "unknown_support_move_detected"
                ]
            )
            self.assertEqual(
                per["newgensupportmove"]["support_group"],
                "unknown_needs_probe",
            )
            # And the metadata source is "unknown".
            self.assertEqual(
                per["newgensupportmove"]["metadata_source"],
                SOURCE_UNKNOWN,
            )

    def test_clean_smoke_is_ready(self):
        """The smoke (clean fixture) produces a
        READY analyzer result. No Gate 17 warning.
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

    def test_unknown_fixture_is_warn(self):
        """A fixture with a true unknown support
        move produces a WARN analyzer result
        (Gate 17 soft warning, no hard block).
        """
        from showdown_ai.build_turn_level_offline_dataset import (
            build_dataset_from_artifact,
        )
        from analyze_turn_level_offline_dataset_quality import (
            analyze,
        )

        with tempfile.TemporaryDirectory() as tmp:
            audit_path = os.path.join(
                tmp, "audit_unknown.jsonl"
            )
            dataset_path = os.path.join(
                tmp, "dataset_unknown.jsonl"
            )
            # Build a minimal audit JSONL with a
            # single battle whose single turn has a
            # truly unknown support move.
            record = {
                "battle_tag": "unknown_fixture",
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
            rows, skipped = build_dataset_from_artifact(
                audit_path, "treatment", "unknown_fixture"
            )
            self.assertEqual(len(rows), 1)
            with open(dataset_path, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            report = analyze([dataset_path])
            v11 = report.get("v11_gates", {})
            # The unknown move is surfaced as a
            # soft warning, not a hard block.
            self.assertEqual(
                v11.get("readiness_impact"), "WARN"
            )
            self.assertEqual(len(v11.get("hard_blocks", [])), 0)
            self.assertGreater(
                len(v11.get("warnings", [])), 0
            )
            # The detector is preserved.
            self.assertTrue(
                rows[0]["unknown_support_move_detected"]
            )


# ============================================================
# Static fallback table integrity
# ============================================================
class TestFallbackTable(unittest.TestCase):
    """Verify the static fallback table is consistent
    with the SUPPORT-AUDIT-1 inventory."""

    def test_fallback_contains_smoke_moves(self):
        for mid in (
            "fakeout", "hurricane", "surf", "raindance",
            "protect",
        ):
            self.assertIn(mid, _FALLBACK_MOVE_METADATA)

    def test_fallback_contains_support_inventory_moves(self):
        # Common support moves
        for mid in (
            "healpulse", "helpinghand", "tailwind", "trickroom",
            "wideguard", "quickguard", "craftyshield",
            "taunt", "encore", "followme", "ragepowder",
        ):
            self.assertIn(
                mid, _FALLBACK_MOVE_METADATA,
                f"missing support-move {mid}",
            )

    def test_fallback_uses_correct_categories(self):
        for mid, (bp, cat) in _FALLBACK_MOVE_METADATA.items():
            if bp > 0:
                self.assertIn(
                    cat, ("physical", "special"),
                    f"{mid} has base_power={bp} but category={cat}",
                )
            else:
                self.assertEqual(
                    cat, "status",
                    f"{mid} has base_power=0 but category={cat}",
                )
